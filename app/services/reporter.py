"""
reporter.py — Serviço de Heartbeat (batimento cardíaco)
========================================================
A cada 30 segundos, envia um "sinal de vida" para o Monitor central informando:
  - Nome e CNPJ da empresa
  - Versão do app instalada
  - Porta em que o app está rodando
  - Status do WhatsApp (connected / qr_code / disconnected) e número conectado

Comportamento multi-empresa:
  O banco local pode ter múltiplas empresas cadastradas (tabela `empresas`).
  O heartbeat é enviado individualmente para cada empresa ativa, usando o
  token exclusivo de cada uma. Se o banco não estiver disponível, usa o
  token do .env como fallback.

Fluxo de auto-atualização (integrado):
  Se o Monitor responder com um campo "update" no JSON, significa que o
  admin disparou um deploy. O reporter cria uma background task que chama
  updater.apply_monitor_update() para baixar e aplicar a nova versão.
"""
import asyncio
import json
import logging
import os

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

# Task do loop de heartbeat, guardada para poder cancelar no shutdown
_task: asyncio.Task | None = None

# ── P2: Watchdog de workers ───────────────────────────────────────────────────
_WORKER_STALE_MINUTES = 5   # alerta se sem heartbeat por mais de 5 minutos
_WATCHED_WORKERS = ["queue_worker"]


async def _check_worker_heartbeats() -> None:
    """Verifica se workers estão enviando heartbeat. Alerta via Telegram se estale."""
    try:
        from ..core.database import get_db_direct
        from .telegram_service import notify_worker_stuck
        async with get_db_direct() as db:
            async with db.execute(
                """SELECT worker_name,
                          EXTRACT(EPOCH FROM (NOW() - last_seen)) / 60 AS minutes_ago,
                          status, detail
                   FROM worker_heartbeats
                   WHERE worker_name = ANY(?)""",
                (_WATCHED_WORKERS,),
            ) as cur:
                rows = {r["worker_name"]: r for r in await cur.fetchall()}

        for worker in _WATCHED_WORKERS:
            if worker not in rows:
                # Nunca enviou heartbeat — pode ter acabado de subir, ignora
                continue
            minutes_ago = int(rows[worker]["minutes_ago"] or 0)
            if minutes_ago >= _WORKER_STALE_MINUTES:
                logger.warning("[watchdog] %s sem heartbeat há %d min", worker, minutes_ago)
                await notify_worker_stuck(worker, minutes_ago)
    except Exception as exc:
        logger.debug("[watchdog] Erro ao checar heartbeats: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
#  Utilitários internos
# ─────────────────────────────────────────────────────────────────────────────

async def _read_version() -> str:
    """
    Lê a versão instalada do arquivo versao.json na raiz do projeto.
    Retorna '1.0.0' como fallback se o arquivo não existir ou estiver corrompido.
    """
    try:
        # Sobe dois níveis a partir de services/ para chegar na raiz do projeto (app/)
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "versao.json")) as f:
            return json.load(f).get("versao", "1.0.0")
    except Exception:
        return "1.0.0"


async def _wa_info_for_empresa(empresa_id: int) -> dict:
    """
    Retorna o status atual do WhatsApp para uma empresa específica.

    O sistema suporta dois backends de WhatsApp:
      - whatsapp_service (Playwright): gerenciado por WAManager
      - evolution_service (Evolution API): gerenciado por EvoManager

    As sessões são identificadas pelo prefixo "empresa_id:" (ex: "3:principal").
    A prioridade de status é: connected > qr_code > disconnected.

    Retorna dict com:
      wa_status: 'connected' | 'qr_code' | 'disconnected'
      wa_phone:  número conectado (ex: '5511999999999') ou None
    """
    try:
        # Import tardio para evitar importação circular no startup;
        # o manager correto é escolhido com base na configuração use_evolution
        from ..core.config import settings as _settings
        if _settings.use_evolution:
            from .evolution_service import evo_manager as wa_manager
        else:
            from .whatsapp_service import wa_manager

        # Filtra apenas as sessões pertencentes a esta empresa pelo prefixo
        prefix = f"{empresa_id}:"
        sessions = {k: s for k, s in wa_manager._sessions.items() if k.startswith(prefix)}

        # Coleta os status únicos de todas as sessões da empresa
        statuses = {s.status for s in sessions.values()}
        # Número da primeira sessão conectada com phone preenchido (memória)
        phone = next(
            (s.phone for s in sessions.values() if s.status == "connected" and s.phone),
            None,
        )
    except Exception as exc:
        logger.warning("[reporter] _wa_info_for_empresa(%s) memória erro: %s", empresa_id, exc)
        statuses, phone = set(), None

    # Fallback / fonte de verdade pro MODO AGENTE: o manager em memória não é
    # atualizado quando a conexão é via agent_bridge (QR/phone gravados só no DB
    # sessoes_wa por refresh-phone). Consulta o DB e mescla.
    try:
        from ..core.database import get_db_direct
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT status, phone FROM sessoes_wa WHERE empresa_id=?", (empresa_id,)
            ) as cur:
                for r in await cur.fetchall():
                    st = (r["status"] or "").strip()
                    if st:
                        statuses.add(st)
                    if st == "connected" and r["phone"] and not phone:
                        phone = r["phone"]

            # Agente compartilhado: empresa que usa o número de uma DONA herda o
            # status/telefone dela (mesmo número físico) — assim todas as filiais
            # mostram o número conectado, não só a dona.
            if not phone or "connected" not in statuses:
                async with db.execute(
                    "SELECT agente_dono_empresa_id FROM empresas WHERE id=?", (empresa_id,)
                ) as cur:
                    drow = await cur.fetchone()
                dona = drow["agente_dono_empresa_id"] if drow else None
                if dona:
                    async with db.execute(
                        "SELECT phone FROM sessoes_wa WHERE empresa_id=? AND status='connected' "
                        "AND phone IS NOT NULL AND phone <> '' ORDER BY last_seen DESC NULLS LAST LIMIT 1",
                        (dona,),
                    ) as cur:
                        dr = await cur.fetchone()
                    if dr and dr["phone"]:
                        statuses.add("connected")
                        phone = phone or dr["phone"]
    except Exception as exc:
        logger.debug("[reporter] _wa_info_for_empresa(%s) DB erro: %s", empresa_id, exc)

    logger.debug("[reporter] empresa=%s sessões=%s phone=%s", empresa_id, statuses or "nenhuma", phone)

    # Prioridade: connected > qr_code > disconnected
    if "connected" in statuses:
        return {"wa_status": "connected", "wa_phone": phone}
    if "qr_code" in statuses:
        return {"wa_status": "qr_code", "wa_phone": None}
    if statuses:
        return {"wa_status": "disconnected", "wa_phone": None}
    return {"wa_status": "disconnected", "wa_phone": None}


def _agents_for_empresa(empresa_id: int) -> list:
    """Retorna lista de agentes WS conectados para a empresa (modo híbrido NAT).

    Cada agente: {sid, version, connected_at, last_seen}. Lista vazia se nenhum.
    """
    try:
        from .agent_bridge import get_agent
        a = get_agent(empresa_id)
        if not a:
            return []
        return [{
            "sid":          a.get("sid"),
            "version":      a.get("version"),
            "connected_at": a.get("connected_at"),
            "last_seen":    a.get("last_seen"),
        }]
    except Exception as exc:
        logger.debug("[reporter] _agents_for_empresa(%s) erro: %s", empresa_id, exc)
        return []


async def _sessoes_for_empresa(empresa_id: int) -> list:
    """Lista de sessões (NÚMEROS) da empresa, cada uma com o MODO (servidor/agente).
    Pro monitor mostrar 1 número no servidor + 1 no agente separados. Modo = 'agente'
    se a sessão usa transporte agent:// (evolution_url), senão 'servidor' (Evolution)."""
    import json as _json
    out = []
    try:
        from ..core.database import get_db_direct
        from .evolution_service import _is_agent_mode
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT id, nome, phone, status, usos, evolution_url FROM sessoes_wa "
                "WHERE empresa_id=? ORDER BY id", (empresa_id,),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            usos = r["usos"]
            try:
                usos = _json.loads(usos) if isinstance(usos, str) else (usos or [])
            except Exception:
                usos = []
            out.append({
                "id":     r["id"],
                "nome":   r["nome"] or "",
                "phone":  r["phone"] or "",
                "status": r["status"] or "disconnected",
                "modo":   "agente" if _is_agent_mode(r["evolution_url"]) else "servidor",
                "usos":   usos,
            })
    except Exception as exc:
        logger.debug("[reporter] _sessoes_for_empresa(%s) erro: %s", empresa_id, exc)
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  Lógica principal do heartbeat
# ─────────────────────────────────────────────────────────────────────────────

async def _send_heartbeat() -> None:
    """
    Envia o heartbeat para cada empresa ativa cadastrada no banco.
    Se o banco não estiver disponível, usa os dados do .env como fallback.

    Após o envio bem-sucedido, verifica na resposta se o Monitor incluiu
    um comando de atualização (campo 'update'). Se sim, inicia o processo
    de auto-atualização em background (sem bloquear os próximos heartbeats).
    """
    version = await _read_version()
    monitor_url = settings.monitor_url.rstrip("/")

    # Atualiza mapa de agente compartilhado (grupo econômico) a cada ciclo
    await _refresh_owner_map()
    # Reflete no app conexões WhatsApp feitas via tray/agente (reconcile)
    await _reconcile_agent_sessions()

    # Tenta buscar lista de empresas do banco; se falhar usa fallback do .env
    try:
        empresas = await _get_empresas_ativas()
    except Exception as exc:
        logger.debug("Não foi possível buscar empresas para heartbeat: %s", exc)
        # Fallback: monta uma empresa fictícia com os dados do .env
        empresas = [{"token": settings.monitor_client_token,
                     "nome": settings.client_name,
                     "cnpj": settings.client_cnpj,
                     "id": 0}]

    # Reutiliza o mesmo cliente HTTP para todas as empresas desta rodada
    async with httpx.AsyncClient(timeout=10) as client:
        for emp in empresas:
            # Cada empresa tem seu próprio token de autenticação no Monitor
            token = emp.get("token") or settings.monitor_client_token
            if not token:
                continue  # empresa sem token não pode se identificar — pula

            wa_info = await _wa_info_for_empresa(emp.get("id", 0))
            agents_list = _agents_for_empresa(emp.get("id", 0))
            sessoes_list = await _sessoes_for_empresa(emp.get("id", 0))

            # Coleta logs acumulados desde o último heartbeat para enviar ao Monitor
            from ..core import log_collector as _lc
            logs_batch = _lc.flush()

            payload = {
                "nome":         emp.get("nome", settings.client_name),
                "cnpj":         emp.get("cnpj", settings.client_cnpj),
                "versao":       version,
                "porta":        settings.port,
                "wa_status":    wa_info["wa_status"],
                "wa_phone":     wa_info["wa_phone"],
                "agents":       agents_list,                # F3.6 — agentes WS conectados
                "agents_count": len(agents_list),
                "sessoes":      sessoes_list,               # por NÚMERO: {nome,phone,status,modo,usos}
                "logs":         logs_batch,                 # lista de {ts, nivel, cat, msg}
            }

            try:
                resp = await client.post(
                    f"{monitor_url}/api/report",
                    json=payload,
                    headers={"x-client-token": token},
                )

                if resp.status_code not in (200, 201):
                    logger.warning("Monitor respondeu %s para empresa %s", resp.status_code, emp.get("nome"))
                    continue

                # ── Verifica se o Monitor enviou um comando de atualização ──────
                # O campo "update" é incluído na resposta quando o admin disparou
                # um deploy para este cliente. Criamos uma background task para
                # não bloquear o heartbeat das outras empresas nem o loop principal.
                try:
                    resp_data = resp.json()

                    # ── Verifica comando de atualização ────────────────────────
                    update_cmd = resp_data.get("update")
                    if update_cmd:
                        logger.info("[reporter] Comando de update recebido: v%s", update_cmd.get("versao"))
                        # Import tardio para evitar importação circular
                        from . import updater as _updater
                        import asyncio as _asyncio
                        _asyncio.create_task(_updater.apply_monitor_update(
                            job_id=update_cmd["job_id"],
                            pacote_id=update_cmd["pacote_id"],
                            versao=update_cmd["versao"],
                            checksum=update_cmd["checksum"],
                            monitor_url=monitor_url,
                            client_token=token,
                        ))

                    # ── Verifica comando de reinício de sessão WA ──────────────
                    wa_restart = resp_data.get("wa_restart")
                    if wa_restart and isinstance(wa_restart, list):
                        logger.info("[reporter] Comando wa_restart recebido: %s", wa_restart)
                        import httpx as _httpx2
                        import asyncio as _asyncio2
                        async def _do_wa_restart(sessoes):
                            async with _httpx2.AsyncClient(timeout=30.0) as _wc:
                                for sid in sessoes:
                                    try:
                                        r = await _wc.post(
                                            f"http://127.0.0.1:{settings.port}/internal/wa-restart/{sid}"
                                        )
                                        logger.info("[reporter] wa-restart %s: %s", sid, r.json())
                                    except Exception as _we:
                                        logger.error("[reporter] Falha wa-restart %s: %s", sid, _we)
                        _asyncio2.create_task(_do_wa_restart(wa_restart))

                    # ── Fix 10: Verifica comando de rollback ────────────────────
                    rollback_cmd = resp_data.get("rollback")
                    if rollback_cmd:
                        logger.warning(
                            "[reporter] Comando de ROLLBACK recebido do Monitor (job_id=%s)",
                            rollback_cmd.get("job_id"),
                        )
                        try:
                            import httpx as _httpx
                            async with _httpx.AsyncClient(timeout=5.0) as _rc:
                                await _rc.post("http://127.0.0.1:%d/internal/rollback" % settings.port)
                        except Exception as _re:
                            logger.error("[reporter] Falha ao chamar /internal/rollback: %s", _re)

                    # ── Sincroniza menus da empresa (piggyback) ────────────────
                    # empresa_menus: None = todos liberados; lista = restrições
                    # Atualiza empresas.menus no banco local para que checkAuth()
                    # aplique as restrições corretamente no próximo carregamento.
                    empresa_menus = resp_data.get("empresa_menus", "UNCHANGED")
                    if empresa_menus != "UNCHANGED":
                        empresa_id = emp.get("id")
                        if empresa_id:
                            try:
                                from ..core.database import _pool as _pool_m
                                if _pool_m is not None:
                                    menus_json = json.dumps(empresa_menus) if empresa_menus is not None else None
                                    async with _pool_m.acquire() as conn:
                                        await conn.execute(
                                            "UPDATE empresas SET menus = $1 WHERE id = $2",
                                            menus_json,
                                            empresa_id,
                                        )
                                    logger.debug(
                                        "[reporter] Menus da empresa %s sincronizados: %s",
                                        empresa_id, empresa_menus,
                                    )
                            except Exception as exc:
                                logger.debug("[reporter] Erro ao sincronizar menus da empresa: %s", exc)

                    # ── Sincroniza cidade/UF para widget de clima ─────────────
                    # O Monitor retorna cidade e uf do cadastro do cliente.
                    # Salva em config (empresa_cidade / empresa_uf) para que
                    # GET /api/home/clima funcione sem configuração manual.
                    empresa_cidade = resp_data.get("empresa_cidade")
                    empresa_uf     = resp_data.get("empresa_uf")
                    if empresa_cidade:
                        empresa_id = emp.get("id")
                        if empresa_id:
                            try:
                                from ..core.database import _pool as _pool_clima
                                if _pool_clima is not None:
                                    async with _pool_clima.acquire() as conn:
                                        await conn.execute(
                                            """INSERT INTO config (empresa_id, key, value)
                                               VALUES ($1, 'empresa_cidade', $2)
                                               ON CONFLICT (empresa_id, key)
                                               DO UPDATE SET value = EXCLUDED.value""",
                                            empresa_id, empresa_cidade,
                                        )
                                        await conn.execute(
                                            """INSERT INTO config (empresa_id, key, value)
                                               VALUES ($1, 'empresa_uf', $2)
                                               ON CONFLICT (empresa_id, key)
                                               DO UPDATE SET value = EXCLUDED.value""",
                                            empresa_id, empresa_uf or "",
                                        )
                                    logger.debug(
                                        "[reporter] Cidade da empresa %s sincronizada: %s/%s",
                                        empresa_id, empresa_cidade, empresa_uf,
                                    )
                            except Exception as exc:
                                logger.debug("[reporter] Erro ao sincronizar cidade: %s", exc)

                    # ── Sincroniza avatares dos usuários ───────────────────────
                    # O Monitor inclui a lista de usuários (username + avatar_url)
                    # na resposta. O app atualiza o banco local para que o avatar
                    # apareça na topbar sem precisar de acesso direto ao cliente.
                    usuarios_sync = resp_data.get("usuarios")
                    if usuarios_sync:
                        empresa_id = emp.get("id")
                        if empresa_id:
                            try:
                                from ..core.database import _pool as _app_pool
                                if _app_pool is not None:
                                    async with _app_pool.acquire() as conn:
                                        for u in usuarios_sync:
                                            await conn.execute(
                                                """UPDATE usuarios
                                                   SET avatar_url = $1
                                                   WHERE username = $2 AND empresa_id = $3""",
                                                u.get("avatar_url"),
                                                u["username"],
                                                empresa_id,
                                            )
                                    logger.debug(
                                        "[reporter] Avatares sincronizados: %d usuário(s) empresa=%s",
                                        len(usuarios_sync), empresa_id,
                                    )
                            except Exception as exc:
                                logger.debug("[reporter] Erro ao sincronizar avatares: %s", exc)

                except Exception as exc:
                    logger.debug("[reporter] Erro ao processar resposta do heartbeat: %s", exc)

            except Exception as exc:
                logger.debug("Heartbeat falhou para %s: %s", emp.get("nome"), exc)


async def _reconcile_agent_sessions() -> None:
    """Para cada empresa com AGENTE conectado, garante que o app reflita a conexão
    WhatsApp feita por fora (ex: QR escaneado pelo tray). Consulta get_state via WS
    e atualiza/garante uma sessão agent-mode (status=connected + phone).

    Evita get_state redundante: só pergunta se ainda não há sessão agent conectada
    com phone pra empresa."""
    try:
        from . import agent_bridge
        from ..main import sio
        from ..core.database import get_db_direct, _pool
        if _pool is None:
            return
        import uuid as _uuid
        empresas = list(agent_bridge._agents.keys())  # empresas com WS direto (donas/standalone)
        for empresa_id in empresas:
            try:
                async with get_db_direct() as db:
                    async with db.execute(
                        "SELECT id, status, phone FROM sessoes_wa "
                        "WHERE empresa_id=? AND evolution_url='agent://' ORDER BY created_at LIMIT 1",
                        (empresa_id,),
                    ) as cur:
                        row = await cur.fetchone()
                    # Já conectado com phone → nada a fazer (não chama Chromium à toa)
                    if row and row["status"] == "connected" and row["phone"]:
                        continue
                # Pergunta o estado real ao agente
                res = await agent_bridge.send_command(
                    sio, empresa_id, "get_state", {"instance": "default"}, timeout=12
                )
                if not (isinstance(res, dict) and res.get("state") == "open"):
                    continue
                phone = res.get("phone") or ""
                nome = (res.get("nome") or "WhatsApp Principal").strip()[:60]
                async with get_db_direct() as db:
                    if row:
                        await db.execute(
                            "UPDATE sessoes_wa SET status='connected', phone=?, nome=?, last_seen=NOW() "
                            "WHERE id=? AND empresa_id=?",
                            (phone, nome, row["id"], empresa_id),
                        )
                    else:
                        await db.execute(
                            "INSERT INTO sessoes_wa (empresa_id, id, nome, status, evolution_url, phone) "
                            "VALUES (?, ?, ?, 'connected', 'agent://', ?)",
                            (empresa_id, str(_uuid.uuid4())[:8], nome, phone),
                        )
                    await db.commit()
                logger.info("[reporter] reconcile: empresa=%s WhatsApp conectado (phone=%s)", empresa_id, phone)
            except Exception as exc:
                logger.debug("[reporter] reconcile empresa=%s erro: %s", empresa_id, exc)
    except Exception as exc:
        logger.debug("[reporter] _reconcile_agent_sessions erro: %s", exc)


async def _refresh_owner_map() -> None:
    """Carrega empresas.agente_dono_empresa_id e atualiza o agent_bridge.
    Permite que empresas usem o agente (número) de uma empresa dona."""
    try:
        from ..core.database import _pool
        if _pool is None:
            return
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, agente_dono_empresa_id FROM empresas "
                "WHERE agente_dono_empresa_id IS NOT NULL"
            )
        mapping = {r["id"]: r["agente_dono_empresa_id"] for r in rows}
        from . import agent_bridge
        agent_bridge.set_owner_map(mapping)
    except Exception as exc:
        logger.debug("[reporter] _refresh_owner_map falhou: %s", exc)


async def _get_empresas_ativas() -> list:
    """
    Busca todas as empresas ativas que possuem token cadastrado no banco local.

    Import tardio de _pool para evitar importação circular durante o startup
    (database.py inicializa depois que reporter.py é importado).

    Retorna lista de dicts com: id, nome, cnpj, token
    """
    from ..core.database import _pool  # import tardio para evitar circular
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, nome, cnpj, token FROM empresas WHERE ativo = TRUE AND token IS NOT NULL"
        )
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
#  Controle do loop (iniciado/parado pelo lifespan do FastAPI em main.py)
# ─────────────────────────────────────────────────────────────────────────────

async def _cleanup_old_files(retention_days: int = 30) -> None:
    """
    Remove arquivos físicos em data/arquivos/ que já foram enviados (ou falharam)
    e têm mais de `retention_days` dias. Preserva arquivos com status 'queued'.
    """
    from ..core.database import get_db_direct

    cutoff_sql = f"NOW() - INTERVAL '{retention_days} days'"
    try:
        async with get_db_direct() as db:
            async with db.execute(
                f"SELECT nome_arquivo FROM arquivos "
                f"WHERE status IN ('sent', 'failed') AND sent_at < {cutoff_sql}",
            ) as cur:
                rows = await cur.fetchall()

        if not rows:
            return

        upload_dir = "data/arquivos"
        removidos = 0
        for row in rows:
            nome = row["nome_arquivo"]
            if not nome:
                continue
            caminho = os.path.join(upload_dir, nome)
            try:
                if os.path.exists(caminho):
                    os.remove(caminho)
                    removidos += 1
            except Exception as exc:
                logger.debug("[cleanup] Erro ao remover %s: %s", caminho, exc)

        if removidos:
            logger.info("[cleanup] %d arquivo(s) antigo(s) removido(s) (>%d dias)", removidos, retention_days)
    except Exception as exc:
        logger.debug("[cleanup] Falha na limpeza de arquivos: %s", exc)


async def _cleanup_invalidated_sessions() -> None:
    """M3: apaga sessões revogadas mais antigas que session_max_age do banco."""
    try:
        from datetime import datetime, timedelta, timezone
        from ..core.config import settings as _s
        from ..core.database import get_db_direct
        cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=_s.session_max_age)
        async with get_db_direct() as db:
            await db.execute(
                "DELETE FROM invalidated_sessions WHERE invalidated_at < ?", (cutoff,)
            )
            await db.commit()
        logger.debug("[reporter] Sessões revogadas antigas removidas do banco")
    except Exception as exc:
        logger.debug("[reporter] Falha ao limpar sessões revogadas: %s", exc)


async def _processar_alertas_pendentes() -> None:
    """
    Tenta reenviar alertas críticos que ficaram na fila por falta de sessão WA.
    Roda a cada ~2 minutos via reporter loop.
    Marca enviado_em ao confirmar envio. Incrementa tentativas em cada falha.
    Descarta após 48h sem envio (evita acúmulo indefinido).
    """
    try:
        from ..core.database import get_db_direct
        from .whatsapp_service import wa_manager
    except ImportError:
        try:
            from ..core.database import get_db_direct
            from .evolution_service import evo_manager as wa_manager
        except ImportError:
            return

    try:
        async with get_db_direct() as db:
            # Busca pendentes não enviados, com menos de 48h, máx 20 por ciclo
            async with db.execute(
                """SELECT p.id, p.empresa_id, p.nome, p.telefone_cliente,
                          p.nota, p.vendedor, p.comentario, p.data_avaliacao,
                          c.value as cfg_json
                   FROM alertas_criticos_pendentes p
                   LEFT JOIN config c ON c.empresa_id = p.empresa_id
                       AND c.key = 'alerta_critico'
                   WHERE p.enviado_em IS NULL
                     AND p.criado_em > NOW() - INTERVAL '48 hours'
                   ORDER BY p.criado_em ASC
                   LIMIT 20"""
            ) as cur:
                pendentes = await cur.fetchall()

        if not pendentes:
            return

        import json as _j
        from datetime import datetime, timezone

        for row in pendentes:
            empresa_id = row["empresa_id"]

            # Verifica se há sessão conectada para essa empresa
            sessoes = wa_manager.get_status(empresa_id)
            conectadas = [s for s in sessoes if s["status"] == "connected"]
            if not conectadas:
                continue  # ainda sem sessão — tenta no próximo ciclo

            # Carrega config do alerta
            try:
                cfg = _j.loads(row["cfg_json"] or "{}")
            except Exception:
                cfg = {}

            # Destinos que escolheram receber alerta de AVALIAÇÃO
            from .alerta_service import destinos_por_tipo
            telefones_destino = [
                (d[2:] if d.startswith("55") else d)
                for d in destinos_por_tipo(cfg, "avaliacao")
            ]
            if not telefones_destino:
                # Ninguém recebe avaliação → descarta pendente
                async with get_db_direct() as db:
                    await db.execute(
                        "UPDATE alertas_criticos_pendentes SET enviado_em = NOW() WHERE id = ?",
                        (row["id"],)
                    )
                    await db.commit()
                continue
            template = cfg.get("mensagem", "")
            if not template:
                continue

            tel_exibir = (row["telefone_cliente"] or "").lstrip("+").lstrip("55") or "—"
            data_fmt = row["data_avaliacao"].strftime("%d/%m/%Y %H:%M") if row["data_avaliacao"] else "—"

            mensagem = (
                template
                .replace("{nome}",       row["nome"] or "—")
                .replace("{telefone}",   tel_exibir)
                .replace("{nota}",       str(row["nota"]))
                .replace("{vendedor}",   row["vendedor"] or "—")
                .replace("{comentario}", row["comentario"] or "—")
                .replace("{data}",       data_fmt)
            )

            sessao_id = conectadas[0]["id"]
            enviou_algum = False
            ultimo_err = ""
            for fone in telefones_destino:
                ok, err = await wa_manager.send_text(sessao_id, empresa_id, fone, mensagem)
                if ok:
                    enviou_algum = True
                else:
                    ultimo_err = err or ""

            async with get_db_direct() as db:
                if enviou_algum:
                    await db.execute(
                        "UPDATE alertas_criticos_pendentes SET enviado_em = NOW() WHERE id = ?",
                        (row["id"],)
                    )
                    logger.info("[alertas_pendentes] enviado id=%d empresa=%d destinos=%d",
                                row["id"], empresa_id, len(telefones_destino))
                else:
                    await db.execute(
                        "UPDATE alertas_criticos_pendentes SET tentativas = tentativas + 1 WHERE id = ?",
                        (row["id"],)
                    )
                    logger.warning("[alertas_pendentes] falha id=%d: %s", row["id"], ultimo_err)
                await db.commit()

    except Exception as exc:
        logger.exception("[alertas_pendentes] erro no worker: %s", exc)


async def _loop() -> None:
    """Loop infinito: envia heartbeat a cada 30s e executa limpeza diária de arquivos."""
    _cleanup_tick = 0
    _CLEANUP_INTERVAL = 2880  # 30s × 2880 = 24 horas
    _SESSION_CLEANUP_INTERVAL = 720  # 30s × 720 = 6 horas
    _OCR_INTERVAL = 2   # 30s × 2  = 1 minuto
    _ALERTA_INTERVAL  = 4  # 30s × 4  = 2 minutos
    _AGENDA_INTERVAL  = 2  # 30s × 2  = 1 minuto

    while True:
        await _send_heartbeat()
        asyncio.create_task(_check_worker_heartbeats())  # P2: watchdog — fire-and-forget
        _cleanup_tick += 1
        if _cleanup_tick >= _CLEANUP_INTERVAL:
            _cleanup_tick = 0
            asyncio.create_task(_cleanup_old_files())  # roda em paralelo — não bloqueia heartbeat
        if _cleanup_tick % _SESSION_CLEANUP_INTERVAL == 0:
            asyncio.create_task(_cleanup_invalidated_sessions())  # M3: limpeza de sessões expiradas
        # OCR/contábil movido p/ projeto separado (zapdincontabil) — removido daqui.
        if _cleanup_tick % _ALERTA_INTERVAL == 0:
            # Reenvio de alertas críticos pendentes a cada ~2 minutos
            asyncio.create_task(_processar_alertas_pendentes())
        if _cleanup_tick % _AGENDA_INTERVAL == 0:
            # Alertas de agenda (antecedências configuradas) a cada ~1 minuto
            try:
                from .agenda_service import enviar_alertas_agenda, enviar_resumo_diario
                asyncio.create_task(enviar_alertas_agenda())
                asyncio.create_task(enviar_resumo_diario())
            except Exception:
                pass
        await asyncio.sleep(30)


def start() -> None:
    """Inicia o serviço de heartbeat como task assíncrona em background."""
    global _task
    _task = asyncio.create_task(_loop())


def stop() -> None:
    """Cancela o loop de heartbeat (chamado no shutdown do app)."""
    global _task
    if _task:
        _task.cancel()
        _task = None
