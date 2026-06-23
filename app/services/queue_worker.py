"""
Queue worker — processa mensagens e arquivos enfileirados com delays aleatórios.

Fluxo: ERP grava no banco com status='queued' e retorna imediatamente.
Este worker pega um item por vez, aguarda um delay randômico (anti-ban)
e dispara via WhatsApp. Nunca bloqueia a API.

Multi-tenant: cada item da fila tem empresa_id.
O worker carrega a config da empresa correspondente para aplicar
delays, limites diários, horários e spintax.

Funcionalidades de anti-banimento:
- Delay randômico configurável (wa_delay_min / wa_delay_max)
- Limite diário de mensagens por sessão (wa_daily_limit)
- Restrição de horário de funcionamento (wa_hora_inicio / wa_hora_fim)
- Motor de Spintax: {Olá|Oi|Bom dia} {nome} (wa_spintax=1)
"""
import asyncio
import logging
import os
import random
import re
import time
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)
from .log_service import log_event_sync


async def requeue_offline_failures(empresa_id: int) -> None:
    """Reenfileira mensagens/arquivos que FALHARAM por estar OFFLINE (agente/sessão
    caída) quando o agente da empresa reconecta. NÃO mexe em falha de número inválido
    ('Composer não encontrado'/'não está no WhatsApp') — essas não têm como entregar.
    Janela de 7 dias pra não ressuscitar envios antigos."""
    from ..core.database import get_db_direct
    cond = (
        "status='failed' AND empresa_id=? "
        "AND created_at > NOW() - INTERVAL '7 days' "
        "AND (erro ILIKE '%não está conectado%' OR erro ILIKE '%sem sess%' "
        "     OR erro ILIKE '%agent:%' OR erro ILIKE '%cancelado%' OR erro ILIKE '%desconect%') "
        "AND erro NOT ILIKE '%Composer não encontrado%' "
        "AND erro NOT ILIKE '%não está no WhatsApp%' "
        "AND erro NOT ILIKE '%inválid%'"
    )
    try:
        async with get_db_direct() as db:
            total = 0
            for tbl in ("mensagens", "arquivos"):
                async with db.execute(f"SELECT count(*) AS n FROM {tbl} WHERE {cond}", (empresa_id,)) as cur:
                    row = await cur.fetchone()
                    total += (row["n"] if row else 0)
                await db.execute(
                    f"UPDATE {tbl} SET status='queued', erro=NULL, sent_at=NULL WHERE {cond}",
                    (empresa_id,),
                )
            await db.commit()
            if total:
                logger.info("[requeue] empresa=%s reenfileiradas %s falhas-offline (agente reconectou)", empresa_id, total)
    except Exception as exc:
        logger.warning("[requeue] empresa=%s erro: %s", empresa_id, exc)


# ── Varredura periódica de falhas-offline ──────────────────────────────────────
# Além do reenfileiramento no reconnect do agente, varre a cada X (padrão 60min)
# as empresas com agente online e reenfileira falhas-offline — cobre o caso do
# agente ficar online mas a sessão WhatsApp ter piscado (sem evento de reconnect).
_sweep_task = None


async def _requeue_sweep_loop(interval: int = 3600) -> None:
    await asyncio.sleep(120)  # espera o boot estabilizar
    while True:
        try:
            from . import agent_bridge as _ab
            ids = {a["empresa_id"] for a in _ab.list_agents()}
            for eid in ids:
                await requeue_offline_failures(eid)
            if ids:
                logger.info("[requeue-sweep] varredura em %s empresa(s) com agente online", len(ids))
        except Exception as exc:
            logger.warning("[requeue-sweep] erro: %s", exc)
        await asyncio.sleep(interval)


def start_requeue_sweep(interval: int = 3600) -> None:
    """Inicia a varredura periódica (idempotente). interval em segundos."""
    global _sweep_task
    if _sweep_task and not _sweep_task.done():
        return
    _sweep_task = asyncio.create_task(_requeue_sweep_loop(interval))
    logger.info("[requeue-sweep] iniciada (intervalo=%ss)", interval)


# ── Heartbeat (P2) ────────────────────────────────────────────────────────────
_HEARTBEAT_INTERVAL = 30   # escreve no banco a cada 30 iterações de ~1s

async def _write_heartbeat(get_db_direct, status: str = "ok", detail: str = "") -> None:
    """Persiste timestamp no banco para watchdog do reporter."""
    try:
        async with get_db_direct() as db:
            await db.execute(
                """INSERT INTO worker_heartbeats (worker_name, last_seen, status, detail)
                   VALUES ('queue_worker', NOW(), ?, ?)
                   ON CONFLICT (worker_name) DO UPDATE
                   SET last_seen = NOW(), status = EXCLUDED.status, detail = EXCLUDED.detail""",
                (status, detail),
            )
            await db.commit()
    except Exception as exc:
        logger.debug("[worker] heartbeat falhou: %s", exc)

UPLOAD_DIR = "data/arquivos"


async def _notify_monitor_numero(phone: str, nome: str, settings) -> None:
    """Notifica o monitor sobre um número contactado. Fire-and-forget."""
    try:
        import httpx
        token = settings.monitor_client_token
        if not token:
            return
        monitor_url = settings.monitor_url.rstrip("/")
        async with httpx.AsyncClient(timeout=4) as client:
            await client.post(
                f"{monitor_url}/api/numeros/registrar",
                json={"phone": phone, "nome": nome},
                headers={"x-client-token": token},
            )
    except Exception as exc:
        logger.debug("_notify_monitor_numero erro: %s", exc)

_task = None

# ── Métricas do worker ────────────────────────────────────────────────────────
_last_processed_at: float = 0.0   # timestamp do último item processado
_processed_count: int = 0          # total de itens processados nesta sessão
_last_error: str = ""              # último erro registrado


def worker_status() -> dict:
    """Retorna métricas do worker para exibição no painel."""
    import time
    running = _task is not None and not _task.done()
    last = _last_processed_at
    ago = int(time.time() - last) if last else None
    return {
        "running": running,
        "processed_count": _processed_count,
        "last_processed_seconds_ago": ago,
        "last_error": _last_error,
    }


# ── Config cache por empresa (recarrega a cada 30s) ───────────────────────────
_cfg_cache: Dict[int, dict] = {}
_cfg_loaded_at: Dict[int, float] = {}
_CFG_TTL = 30.0

_WA_CFG_KEYS = (
    "wa_delay_min", "wa_delay_max",
    "wa_daily_limit",
    "wa_hora_inicio", "wa_hora_fim",
    "wa_spintax",
)


async def _load_cfg(empresa_id: int, get_db_direct) -> dict:
    global _cfg_cache, _cfg_loaded_at
    now = time.monotonic()
    if now - _cfg_loaded_at.get(empresa_id, 0) < _CFG_TTL and empresa_id in _cfg_cache:
        return _cfg_cache[empresa_id]
    try:
        keys_sql = ",".join(f"'{k}'" for k in _WA_CFG_KEYS)
        async with get_db_direct() as db:
            async with db.execute(
                f"SELECT key, value FROM config WHERE empresa_id=? AND key IN ({keys_sql})",
                (empresa_id,),
            ) as cur:
                rows = await cur.fetchall()
        _cfg_cache[empresa_id] = {r["key"]: r["value"] for r in rows}
        _cfg_loaded_at[empresa_id] = now
    except Exception as exc:
        logger.debug("_load_cfg error [empresa %s]: %s", empresa_id, exc)
        _cfg_cache.setdefault(empresa_id, {})
    return _cfg_cache[empresa_id]


def _cfg_float(cfg: dict, key: str, default: float) -> float:
    try:
        return float(cfg.get(key, default))
    except (ValueError, TypeError):
        return default


def _cfg_int(cfg: dict, key: str, default: int) -> int:
    try:
        return int(cfg.get(key, default))
    except (ValueError, TypeError):
        return default


# ── Simulação de digitação ────────────────────────────────────────────────────

def _composing_delay(text: str) -> float:
    """
    Calcula o tempo de 'digitando...' proporcional ao tamanho da mensagem.
    Simula velocidade humana de ~20 chars/s no celular.
    Mínimo: 1.0 s  |  Máximo: 8.0 s  |  Variação: ±15%
    """
    chars = max(len(text.strip()), 1)
    base  = min(max(chars / 20.0, 1.0), 8.0)
    return base * random.uniform(0.85, 1.15)


# ── Spintax ───────────────────────────────────────────────────────────────────

def process_spintax(text: str) -> str:
    """Expande {opção1|opção2|opção3} aninhado de dentro para fora."""
    pattern = re.compile(r'\{([^{}]+)\}')
    for _ in range(10):  # proteção contra recursão infinita
        new = pattern.sub(lambda m: random.choice(m.group(1).split('|')), text)
        if new == text:
            break
        text = new
    return text


# ── Business hours ────────────────────────────────────────────────────────────

def _within_hours(cfg: dict) -> bool:
    inicio = cfg.get("wa_hora_inicio", "").strip()
    fim = cfg.get("wa_hora_fim", "").strip()
    if not inicio or not fim:
        return True
    now = datetime.now().strftime("%H:%M")
    return inicio <= now <= fim


# ── Daily limit ───────────────────────────────────────────────────────────────

async def _daily_sent(db, sessao_id: str, empresa_id: int) -> int:
    """Total de mensagens + arquivos enviados hoje por esta sessão/empresa."""
    async with db.execute(
        "SELECT COUNT(*) as cnt FROM mensagens "
        "WHERE sessao_id=? AND empresa_id=? AND status='sent' AND sent_at::date = CURRENT_DATE",
        (sessao_id, empresa_id),
    ) as cur:
        row = await cur.fetchone()
    msg_count = row["cnt"] if row else 0

    async with db.execute(
        "SELECT COUNT(*) as cnt FROM arquivos "
        "WHERE sessao_id=? AND empresa_id=? AND status='sent' AND sent_at::date = CURRENT_DATE",
        (sessao_id, empresa_id),
    ) as cur:
        row = await cur.fetchone()
    arq_count = row["cnt"] if row else 0

    return msg_count + arq_count


# ── Loop principal ────────────────────────────────────────────────────────────

async def _loop() -> None:
    global _last_processed_at, _processed_count, _last_error
    from ..core.config import settings
    from ..core.database import get_db_direct
    if settings.use_evolution:
        from .evolution_service import evo_manager as wa_manager
    else:
        from .whatsapp_service import wa_manager

    logger.info("Queue worker loop iniciado")
    _bv_check_counter = 0  # verifica pendentes a cada ~30s (30 ciclos de 1s)
    _hb_counter = 0        # escreve heartbeat a cada _HEARTBEAT_INTERVAL ciclos
    while True:
        try:
            dispatched = await _process_next(wa_manager, settings, get_db_direct)
            if dispatched:
                _last_processed_at = time.time()
                _processed_count += 1
                _last_error = ""
        except Exception as exc:
            _last_error = str(exc)
            logger.error("Queue worker erro: %s", exc, exc_info=True)
            dispatched = False

        # Heartbeat a cada ~30s
        _hb_counter += 1
        if _hb_counter >= _HEARTBEAT_INTERVAL:
            _hb_counter = 0
            status = "error" if _last_error else "ok"
            asyncio.create_task(_write_heartbeat(get_db_direct, status, _last_error[:200]))

        # Boas-vindas contábil movido p/ projeto separado (zapdincontabil) — removido.

        await asyncio.sleep(0.2 if dispatched else 1.0)


# ── Round-robin por empresa (fairness multi-tenant) ──────────────────────────
# Sem isso: empresa com 10k itens com IDs menores monopoliza a fila, e pior —
# empresa bloqueada (fora de horário / sem sessão / limite diário) travava a
# fila GLOBAL com return False. Agora cada rodada tenta a próxima empresa
# elegível na rotação; bloqueio de uma empresa não afeta as outras.
_rr_ptrs: dict = {"msg": -1, "arq": -1, "camp": -1}


def _rotate(empresas: list, key: str) -> list:
    """Reordena lista de empresa_ids começando após o último servido."""
    if not empresas:
        return []
    last = _rr_ptrs.get(key, -1)
    after = [e for e in empresas if e > last]
    before = [e for e in empresas if e <= last]
    return after + before


async def _empresas_queued(get_db_direct, sql: str) -> list:
    async with get_db_direct() as db:
        async with db.execute(sql) as cur:
            return [r["empresa_id"] for r in await cur.fetchall()]


async def _process_next(wa_manager, settings, get_db_direct) -> bool:
    """Processa o próximo item na fila. Retorna True se processou algo."""
    now_dt = lambda: datetime.now()

    # ── Auto-inicia campanhas agendadas cujo horário chegou ──────────────────
    async with get_db_direct() as db:
        from datetime import timezone as _tz
        now_utc = datetime.now(_tz.utc)
        async with db.execute(
            """SELECT c.id, c.empresa_id FROM campanhas c
               WHERE c.status = 'scheduled' AND c.agendado_em <= ?""",
            (now_utc,),
        ) as cur:
            agendadas = await cur.fetchall()
        for camp in agendadas:
            try:
                await db.execute(
                    """INSERT INTO campanha_envios (campanha_id, empresa_id, phone, nome, status)
                       SELECT ?, co.empresa_id, co.phone, co.nome, 'queued'
                       FROM contatos co
                       WHERE co.empresa_id = ? AND co.ativo = TRUE
                       ON CONFLICT DO NOTHING""",
                    (camp["id"], camp["empresa_id"]),
                )
                async with db.execute(
                    "SELECT COUNT(*) as cnt FROM campanha_envios WHERE campanha_id = ? AND status='queued'",
                    (camp["id"],),
                ) as cnt_cur:
                    cnt_row = await cnt_cur.fetchone()
                total = cnt_row["cnt"] if cnt_row else 0
                await db.execute(
                    "UPDATE campanhas SET status='running', total=?, enviados=0, erros=0, started_at=NOW() WHERE id=?",
                    (total, camp["id"]),
                )
                await db.commit()
                logger.info("[worker] Campanha agendada %s iniciada automaticamente (%d contatos)", camp["id"], total)
            except Exception as exc:
                logger.warning("[worker] Erro ao auto-iniciar campanha agendada %s: %s", camp["id"], exc)

    # ── Mensagens de texto (round-robin por empresa) ──────────────────────────
    empresas_msg = await _empresas_queued(
        get_db_direct,
        "SELECT DISTINCT empresa_id FROM mensagens WHERE status='queued' ORDER BY empresa_id",
    )
    for empresa_id in _rotate(empresas_msg, "msg"):
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT id, empresa_id, destinatario, nome_destinatario, mensagem, tipo FROM mensagens "
                "WHERE status='queued' AND empresa_id=? ORDER BY id LIMIT 1",
                (empresa_id,),
            ) as cur:
                msg = await cur.fetchone()
        if not msg:
            continue

        cfg = await _load_cfg(empresa_id, get_db_direct)

        # Mensagens prioritárias (alerta/resumo/sistema) ignoram horário e limite diário —
        # um alerta crítico não pode esperar a janela comercial.
        _prio = (msg["tipo"] or "") in ("alerta", "resumo", "sistema", "teste")

        if not _prio and not _within_hours(cfg):
            continue  # só esta empresa fora do horário — tenta a próxima

        delay_min    = _cfg_float(cfg, "wa_delay_min", settings.dispatch_min_delay)
        delay_max    = _cfg_float(cfg, "wa_delay_max", settings.dispatch_max_delay)
        daily_limit  = _cfg_int(cfg, "wa_daily_limit", 0)
        spintax_on   = cfg.get("wa_spintax",    "1") not in ("0", "false", "")
        composing_on = cfg.get("wa_composing",  "1") not in ("0", "false", "")

        sessao_id = wa_manager.pick_session(empresa_id)
        if not sessao_id:
            logger.warning(
                "Queue: NENHUMA sessão WhatsApp conectada para empresa=%s — mensagem %s aguardando. "
                "Verifique se o WhatsApp está conectado no painel.",
                empresa_id, msg["id"],
            )
            # Alerta Telegram (throttled a cada 30min)
            try:
                from . import telegram_service
                asyncio.create_task(telegram_service.notify_queue_blocked(1))
            except Exception:
                pass
            continue  # empresa sem sessão não trava as outras

        # Checa limite diário (prioritários — alerta/resumo — ignoram)
        if not _prio and daily_limit > 0:
            async with get_db_direct() as db:
                sent_today = await _daily_sent(db, sessao_id, empresa_id)
            if sent_today >= daily_limit:
                logger.info(
                    "Queue: sessão %s empresa %s atingiu limite diário (%d) — envios pausados até meia-noite",
                    sessao_id, empresa_id, daily_limit,
                )
                continue  # limite só desta empresa

        _rr_ptrs["msg"] = empresa_id
        delay = random.uniform(delay_min, delay_max)
        logger.info("Queue: mensagem %s (empresa %s) → delay %.1fs", msg["id"], empresa_id, delay)
        await asyncio.sleep(delay)

        texto = process_spintax(msg["mensagem"]) if (spintax_on and not _prio) else msg["mensagem"]
        c_delay = _composing_delay(texto) if composing_on else 0.0

        ok, err = await wa_manager.send_text(sessao_id, empresa_id, msg["destinatario"], texto, composing_delay=c_delay)
        st = "sent" if ok else "failed"
        async with get_db_direct() as db:
            await db.execute(
                "UPDATE mensagens SET status=?, sessao_id=?, sent_at=?, erro=? WHERE id=? AND empresa_id=?",
                (st, sessao_id, now_dt() if ok else None, err, msg["id"], empresa_id),
            )
            await db.commit()
        if not ok:
            logger.error(
                "Queue: FALHA ao enviar mensagem %s para %s via sessão %s: %s",
                msg["id"], msg["destinatario"], sessao_id, err,
            )
            log_event_sync(empresa_id=empresa_id, nivel="error", modulo="worker", acao="msg_erro",
                           mensagem=f"Erro ao enviar: {msg['destinatario']} — {str(err or '')[:100]}")
            # Alerta de falha por número inválido (cadastro) → avisa os adms
            try:
                from .alerta_service import disparar_falha_cadastro
                nome_dest = msg["nome_destinatario"] if "nome_destinatario" in msg.keys() else ""
                asyncio.create_task(
                    disparar_falha_cadastro(empresa_id, msg["destinatario"], nome_dest or "", str(err or ""))
                )
            except Exception:
                pass
        logger.info("Queue: mensagem %s → %s", msg["id"], st)
        if ok:
            log_event_sync(empresa_id=empresa_id, nivel="info", modulo="worker", acao="msg_enviada",
                           mensagem=f"Mensagem enviada: {msg['destinatario']}")
            nome = msg["nome_destinatario"] if "nome_destinatario" in msg.keys() else ""
            asyncio.create_task(_notify_monitor_numero(msg["destinatario"], nome or "", settings))
            wa_manager.schedule_status_check(msg["id"], sessao_id, empresa_id, msg["destinatario"], table="mensagens")
        return True

    # ── Arquivos (round-robin por empresa) ────────────────────────────────────
    empresas_arq = await _empresas_queued(
        get_db_direct,
        "SELECT DISTINCT empresa_id FROM arquivos WHERE status='queued' ORDER BY empresa_id",
    )
    for empresa_id in _rotate(empresas_arq, "arq"):
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT id, empresa_id, destinatario, nome_destinatario, nome_arquivo, nome_original, caption "
                "FROM arquivos WHERE status='queued' AND empresa_id=? ORDER BY id LIMIT 1",
                (empresa_id,),
            ) as cur:
                arq = await cur.fetchone()
        if not arq:
            continue

        cfg = await _load_cfg(empresa_id, get_db_direct)

        if not _within_hours(cfg):
            continue

        delay_min    = _cfg_float(cfg, "wa_delay_min", settings.dispatch_min_delay)
        delay_max    = _cfg_float(cfg, "wa_delay_max", settings.dispatch_max_delay)
        daily_limit  = _cfg_int(cfg, "wa_daily_limit", 0)
        spintax_on   = cfg.get("wa_spintax",   "1") not in ("0", "false", "")
        composing_on = cfg.get("wa_composing", "1") not in ("0", "false", "")

        sessao_id = wa_manager.pick_session(empresa_id)
        if not sessao_id:
            logger.warning(
                "Queue: NENHUMA sessão WhatsApp conectada para empresa=%s — arquivo %s aguardando. "
                "Verifique se o WhatsApp está conectado no painel.",
                empresa_id, arq["id"],
            )
            try:
                from . import telegram_service
                asyncio.create_task(telegram_service.notify_queue_blocked(1))
            except Exception:
                pass
            continue

        # Checa limite diário
        if daily_limit > 0:
            async with get_db_direct() as db:
                sent_today = await _daily_sent(db, sessao_id, empresa_id)
            if sent_today >= daily_limit:
                logger.info(
                    "Queue: sessão %s empresa %s atingiu limite diário (%d) — envios pausados até meia-noite",
                    sessao_id, empresa_id, daily_limit,
                )
                continue

        _rr_ptrs["arq"] = empresa_id
        delay = random.uniform(delay_min, delay_max)
        logger.info("Queue: arquivo %s (empresa %s) → delay %.1fs", arq["id"], empresa_id, delay)
        await asyncio.sleep(delay)

        # Modo só-texto: arquivo vazio = enviar apenas a caption como mensagem
        nome_file_db = arq["nome_arquivo"] or ""
        caption = process_spintax(arq["caption"] or "") if spintax_on else (arq["caption"] or "")
        c_delay = _composing_delay(caption) if composing_on and caption else (random.uniform(1.5, 3.0) if composing_on else 0.0)

        if not nome_file_db:
            # Sem arquivo — envio como texto puro
            if not (caption and caption.strip()):
                async with get_db_direct() as db:
                    await db.execute(
                        "UPDATE arquivos SET status='failed', erro='Sem arquivo e sem mensagem' WHERE id=? AND empresa_id=?",
                        (arq["id"], empresa_id),
                    )
                    await db.commit()
                return True
            ok, err = await wa_manager.send_text(
                sessao_id, empresa_id, arq["destinatario"], caption,
                composing_delay=c_delay,
            )
        else:
            file_path = os.path.join(UPLOAD_DIR, nome_file_db)
            if not os.path.exists(file_path):
                logger.error(
                    "Queue: arquivo %s NÃO ENCONTRADO em disco: %s — marcado como failed. "
                    "O arquivo pode ter sido excluído manualmente.",
                    arq["id"], file_path,
                )
                async with get_db_direct() as db:
                    await db.execute(
                        "UPDATE arquivos SET status='failed', erro='Arquivo não encontrado no disco' WHERE id=? AND empresa_id=?",
                        (arq["id"], empresa_id),
                    )
                    await db.commit()
                return True

            ok, err = await wa_manager.send_file(
                sessao_id, empresa_id, arq["destinatario"], file_path,
                arq["nome_original"], caption or None,
                composing_delay=c_delay,
            )
        st = "sent" if ok else "failed"
        async with get_db_direct() as db:
            await db.execute(
                "UPDATE arquivos SET status=?, sessao_id=?, sent_at=?, erro=? WHERE id=? AND empresa_id=?",
                (st, sessao_id, now_dt() if ok else None, err, arq["id"], empresa_id),
            )
            await db.commit()
        if not ok:
            logger.error(
                "Queue: FALHA ao enviar arquivo %s (%s) para %s via sessão %s: %s",
                arq["id"], arq["nome_original"], arq["destinatario"], sessao_id, err,
            )
            log_event_sync(empresa_id=empresa_id, nivel="error", modulo="worker", acao="msg_erro",
                           mensagem=f"Erro ao enviar: {arq['destinatario']} — {str(err or '')[:100]}")
            try:
                from .alerta_service import disparar_falha_cadastro
                nome_dest = arq["nome_destinatario"] if "nome_destinatario" in arq.keys() else ""
                asyncio.create_task(
                    disparar_falha_cadastro(empresa_id, arq["destinatario"], nome_dest or "", str(err or ""))
                )
            except Exception:
                pass
        logger.info("Queue: arquivo %s → %s", arq["id"], st)
        if ok:
            log_event_sync(empresa_id=empresa_id, nivel="info", modulo="worker", acao="msg_enviada",
                           mensagem=f"Mensagem enviada: {arq['destinatario']}")
            nome = arq["nome_destinatario"] if "nome_destinatario" in arq.keys() else ""
            asyncio.create_task(_notify_monitor_numero(arq["destinatario"], nome or "", settings))
            wa_manager.schedule_status_check(arq["id"], sessao_id, empresa_id, arq["destinatario"])
        return True

    # ── Campanha Envios (round-robin por empresa) ─────────────────────────────
    empresas_camp = await _empresas_queued(
        get_db_direct,
        "SELECT DISTINCT ce.empresa_id FROM campanha_envios ce "
        "JOIN campanhas c ON c.id = ce.campanha_id "
        "WHERE ce.status='queued' AND c.status='running' ORDER BY ce.empresa_id",
    )
    for empresa_id in _rotate(empresas_camp, "camp"):
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT ce.id, ce.campanha_id, ce.empresa_id, ce.phone, ce.nome, "
                "       c.tipo, c.mensagem "
                "FROM campanha_envios ce "
                "JOIN campanhas c ON c.id = ce.campanha_id "
                "WHERE ce.status='queued' AND c.status='running' AND ce.empresa_id=? "
                "ORDER BY ce.id LIMIT 1",
                (empresa_id,),
            ) as cur:
                env = await cur.fetchone()
        if not env:
            continue

        campanha_id = env["campanha_id"]
        cfg = await _load_cfg(empresa_id, get_db_direct)

        if not _within_hours(cfg):
            continue

        delay_min    = _cfg_float(cfg, "wa_delay_min", settings.dispatch_min_delay)
        delay_max    = _cfg_float(cfg, "wa_delay_max", settings.dispatch_max_delay)
        spintax_on   = cfg.get("wa_spintax",   "1") not in ("0", "false", "")
        composing_on = cfg.get("wa_composing", "1") not in ("0", "false", "")

        sessao_id = wa_manager.pick_session(empresa_id)
        if not sessao_id:
            try:
                from . import telegram_service
                asyncio.create_task(telegram_service.notify_queue_blocked(1))
            except Exception:
                pass
            continue

        _rr_ptrs["camp"] = empresa_id
        delay = random.uniform(delay_min, delay_max)
        logger.info("Queue: campanha_envio %s campanha %s → delay %.1fs", env["id"], campanha_id, delay)
        await asyncio.sleep(delay)

        tipo = env["tipo"]
        ok = False
        err = None

        if tipo == "text":
            mensagem = env["mensagem"] or ""
            if spintax_on:
                mensagem = process_spintax(mensagem)
            c_delay = _composing_delay(mensagem) if composing_on else 0.0
            ok, err = await wa_manager.send_text(sessao_id, empresa_id, env["phone"], mensagem, composing_delay=c_delay)

        elif tipo == "file":
            # Busca arquivos da campanha
            async with get_db_direct() as db2:
                async with db2.execute(
                    "SELECT nome_original, nome_arquivo FROM campanha_arquivos WHERE campanha_id=? ORDER BY id",
                    (campanha_id,),
                ) as cur2:
                    camp_arqs = await cur2.fetchall()

            if not camp_arqs:
                ok, err = False, "Nenhum arquivo na campanha"
            else:
                # Envia todos os arquivos deste contato
                ok = True
                for ca in camp_arqs:
                    file_path = os.path.join(UPLOAD_DIR, ca["nome_arquivo"])
                    if not os.path.exists(file_path):
                        ok, err = False, f"Arquivo {ca['nome_original']} não encontrado"
                        break
                    mensagem = env["mensagem"] or ""
                    if spintax_on:
                        mensagem = process_spintax(mensagem)
                    _ok, _err = await wa_manager.send_file(
                        sessao_id, empresa_id, env["phone"], file_path,
                        ca["nome_original"], mensagem or None,
                    )
                    if not _ok:
                        ok, err = False, _err
                        break
                    await asyncio.sleep(random.uniform(1, 3))

        st = "sent" if ok else "failed"
        async with get_db_direct() as db3:
            await db3.execute(
                "UPDATE campanha_envios SET status=?, sent_at=?, erro=? WHERE id=?",
                (st, now_dt() if ok else None, err, env["id"]),
            )
            if ok:
                await db3.execute(
                    "UPDATE campanhas SET enviados = enviados + 1 WHERE id=?", (campanha_id,)
                )
            else:
                await db3.execute(
                    "UPDATE campanhas SET erros = erros + 1 WHERE id=?", (campanha_id,)
                )
            # Verifica se campanha terminou
            async with db3.execute(
                "SELECT COUNT(*) as cnt FROM campanha_envios WHERE campanha_id=? AND status='queued'",
                (campanha_id,),
            ) as cur3:
                remaining = await cur3.fetchone()
            if remaining and remaining["cnt"] == 0:
                await db3.execute(
                    "UPDATE campanhas SET status='done', done_at=NOW() WHERE id=? AND status IN ('running','paused')",
                    (campanha_id,),
                )
            await db3.commit()

        logger.info("Queue: campanha_envio %s → %s", env["id"], st)
        if ok:
            asyncio.create_task(_notify_monitor_numero(env["phone"], env["nome"] or "", settings))
            wa_manager.schedule_status_check(env["id"], sessao_id, empresa_id, env["phone"], table="campanha_envios")
        return True

    return False


def start() -> None:
    global _task
    _task = asyncio.create_task(_loop())
    logger.info("Queue worker iniciado")


def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        _task = None
