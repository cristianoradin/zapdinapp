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


def _wa_info_for_empresa(empresa_id: int) -> dict:
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
        logger.debug("[reporter] empresa=%s sessões=%s", empresa_id, statuses or "nenhuma")

        # Prioridade: connected > qr_code > disconnected
        if "connected" in statuses:
            # Pega o número da primeira sessão conectada que tenha phone preenchido
            phone = next(
                (s.phone for s in sessions.values() if s.status == "connected" and s.phone),
                None,
            )
            return {"wa_status": "connected", "wa_phone": phone}

        if "qr_code" in statuses:
            # Aguardando leitura do QR code pelo usuário
            return {"wa_status": "qr_code", "wa_phone": None}

        if statuses:
            # Há sessões mas nenhuma conectada nem em QR
            return {"wa_status": "disconnected", "wa_phone": None}

    except Exception as exc:
        logger.warning("[reporter] _wa_info_for_empresa(%s) erro: %s", empresa_id, exc)

    # Padrão seguro: sem sessões ou erro inesperado → desconectado
    return {"wa_status": "disconnected", "wa_phone": None}


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

            wa_info = _wa_info_for_empresa(emp.get("id", 0))

            # Coleta logs acumulados desde o último heartbeat para enviar ao Monitor
            from ..core import log_collector as _lc
            logs_batch = _lc.flush()

            payload = {
                "nome":      emp.get("nome", settings.client_name),
                "cnpj":      emp.get("cnpj", settings.client_cnpj),
                "versao":    version,
                "porta":     settings.port,
                "wa_status": wa_info["wa_status"],
                "wa_phone":  wa_info["wa_phone"],
                "logs":      logs_batch,  # lista de {ts, nivel, cat, msg}
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


async def _loop() -> None:
    """Loop infinito: envia heartbeat a cada 30s e executa limpeza diária de arquivos."""
    _cleanup_tick = 0
    _CLEANUP_INTERVAL = 2880  # 30s × 2880 = 24 horas
    _SESSION_CLEANUP_INTERVAL = 720  # 30s × 720 = 6 horas

    while True:
        await _send_heartbeat()
        _cleanup_tick += 1
        if _cleanup_tick >= _CLEANUP_INTERVAL:
            _cleanup_tick = 0
            asyncio.create_task(_cleanup_old_files())  # roda em paralelo — não bloqueia heartbeat
        if _cleanup_tick % _SESSION_CLEANUP_INTERVAL == 0:
            asyncio.create_task(_cleanup_invalidated_sessions())  # M3: limpeza de sessões expiradas
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
