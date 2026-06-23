import asyncio
import logging
import logging.handlers
import os
from contextlib import asynccontextmanager

import socketio
import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .core.config import settings
from .core import log_collector as _log_collector
from .core.security_headers import SecurityHeadersMiddleware

# ── Logging com arquivo rotacionado + coletor para Monitor ───────────────────
def _setup_logging() -> None:
    """
    Configura o sistema de logging do app:
      - Console: nível INFO, formato legível
      - Arquivo: data/zapdin.log, rotação 10 MB, mantém 5 arquivos
      - Monitor: handler que coleta logs para enviar via heartbeat
    """
    os.makedirs("data", exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    # Arquivo rotacionado (10 MB × 5 arquivos = até 50 MB de histórico)
    fh = logging.handlers.RotatingFileHandler(
        "data/zapdin.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Coletor para Monitor (instala handler no root logger)
    _log_collector.install()

_setup_logging()
from .core.database import init_db, get_db, get_db_direct
from .core.security import get_current_user
from .core.http_client import close_http_client
from .routers import whatsapp, erp, config_router, arquivos, stats, telegram_router
from .routers.ai_config_router import router as ai_config_router
from .routers.auth_login import router as auth_login_router
from .routers.auth_empresa import router as auth_empresa_router
from .routers.auth_usuarios import router as auth_usuarios_router
from .routers.activation import router as activation_router
from .routers.internal import router as internal_router
from .routers.monitor_sync import router as monitor_sync_router
from .routers.docs_router import router as docs_router
from .routers.campanha import router as campanha_router
from .routers.pdv_router import router as pdv_router
from .routers.avaliacao import router as avaliacao_router
from .routers.chatbot_router import router as chatbot_router
from .routers.syslog_router import router as syslog_router
from .routers.ia_central_router import router as ia_central_router
from .routers.home_router import router as home_router
from .routers.agents import router as agents_router
from .routers.chat_router import router as chat_router
from .services import reporter, updater, telegram_service, queue_worker
from .services import resumo_avaliacao_service
from .services.log_service import log_event
from .services.whatsapp_service import wa_manager as _playwright_manager
from .services.evolution_service import evo_manager as _evo_manager

# Seleciona o backend de WhatsApp conforme configuração
wa_manager = _evo_manager if settings.use_evolution else _playwright_manager

# ── Socket.IO ──────────────────────────────────────────────────────────────────
# Restringe CORS ao próprio host em vez de aceitar qualquer origem.
# O frontend é servido pelo mesmo processo (porta 4000), então localhost é suficiente.
_WS_ORIGINS = [
    "http://localhost:4000",
    "http://127.0.0.1:4000",
    f"http://localhost:{settings.port}",
    f"http://127.0.0.1:{settings.port}",
]
# ping_timeout alto (90s): o agente pode travar o loop durante o launch do
# Chromium (get_qr ~15-30s) e não responder o ping a tempo. Com timeout curto
# (default 20s) o servidor matava a conexão → agente caía ~1min após conectar.
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=_WS_ORIGINS,
    ping_interval=25,
    ping_timeout=90,
)

# Injeta sio no evolution_service para que comandos em modo agente sejam roteados via WS
try:
    from .services import evolution_service as _evo_svc
    _evo_svc.set_sio(sio)
except Exception:
    pass


@sio.event
async def connect(sid, environ):
    pass


@sio.event
async def disconnect(sid):
    pass


# ── Namespace /agent ─────────────────────────────────────────────────────────
# WebSocket persistente cliente-agente → servidor (atravessa NAT do posto).
# Agente Python no cliente conecta com auth={"token": <empresas.token>, "version": "..."}.
# Servidor valida token, registra sid no agent_bridge e pode chamar comandos.
from .services import agent_bridge as _agent_bridge

_agent_log = logging.getLogger("app.agent")


@sio.event(namespace="/agent")
async def connect(sid, environ, auth):
    token = None
    version = "?"
    device_id = None
    if isinstance(auth, dict):
        token = auth.get("token")
        version = auth.get("version", "?")
        device_id = auth.get("device_id")
    if not token:
        _agent_log.warning("[agent] connect rejeitado: sem token (sid=%s)", sid)
        return False

    from .core import database as _db_mod
    pool = _db_mod._pool
    if pool is None:
        _agent_log.error("[agent] pool de DB indisponível (sid=%s)", sid)
        return False

    empresa_id = await _agent_bridge._resolve_empresa_by_token(pool, token)
    if not empresa_id:
        _agent_log.warning("[agent] connect rejeitado: token inválido (sid=%s)", sid)
        return False

    # Trava de dispositivo: token vincula a 1 máquina. 1ª ativação vincula; mesma
    # máquina reativa; outra máquina é bloqueada. Agentes antigos (sem device_id)
    # não vinculam nem são bloqueados (compatibilidade).
    if device_id:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT bound_device_id FROM empresas WHERE id=$1", empresa_id)
                bound = row["bound_device_id"] if row else None
                if not bound:
                    await conn.execute("UPDATE empresas SET bound_device_id=$1 WHERE id=$2", device_id, empresa_id)
                    _agent_log.info("[agent] device vinculado: empresa=%s device=%s", empresa_id, device_id[:12])
                elif bound != device_id:
                    _agent_log.warning("[agent] connect REJEITADO: token da empresa=%s já vinculado a outro dispositivo (sid=%s)", empresa_id, sid)
                    return False
        except Exception as exc:
            _agent_log.debug("[agent] device-bind erro (segue): %s", exc)

    _agent_bridge.register_agent(empresa_id, sid, {"version": version})
    await sio.emit(
        "welcome",
        {"ok": True, "empresa_id": empresa_id},
        to=sid,
        namespace="/agent",
    )
    # Agente reconectou → reenfileira automaticamente as falhas que foram por
    # OFFLINE (não por número inválido). Espera a sessão estabilizar antes.
    async def _requeue_on_reconnect(eid: int):
        try:
            await asyncio.sleep(10)
            from .services.queue_worker import requeue_offline_failures
            await requeue_offline_failures(eid)
        except Exception as exc:
            _agent_log.debug("[requeue] task erro empresa=%s: %s", eid, exc)
    asyncio.create_task(_requeue_on_reconnect(empresa_id))
    return True


@sio.event(namespace="/agent")
async def disconnect(sid):
    _agent_bridge.unregister_by_sid(sid)


@sio.on("heartbeat", namespace="/agent")
async def agent_heartbeat(sid, data):
    _agent_bridge.touch(sid)
    import time as _t
    return {"ok": True, "t": _t.time()}


@sio.on("evo_event", namespace="/agent")
async def agent_evo_event(sid, payload):
    """Webhook reverso: agente local repassa eventos da Evolution dele via WS."""
    _agent_bridge.touch(sid)
    try:
        from .services.evolution_service import evo_manager
        evo_manager.handle_webhook(payload or {})
    except Exception as e:
        _agent_log.warning("[agent] evo_event erro: %s", e)
        return {"ok": False, "error": str(e)}
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
#  Middleware de Lock
#  Quando APP_STATE=locked, bloqueia tudo exceto as rotas de ativação.
# ─────────────────────────────────────────────────────────────────────────────

_LOCK_ALLOWED_PREFIXES = (
    "/activate",
    "/api/activate",
    "/api/evo-webhook",   # Evolution API envia eventos mesmo durante ativação
    "/api/evo-file/",
    "/login",
    "/static/",
    "/logo/",
    "/favicon",
    "/avaliacao",
    "/api/avaliacao/",
    "/instalar/",          # kit de instalação self-service
    "/api/kit/",
)


class LockMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if settings.is_locked:
            path = request.url.path
            allowed = any(path.startswith(p) for p in _LOCK_ALLOWED_PREFIXES)
            if not allowed:
                if path.startswith("/api/") or path.startswith("/internal/"):
                    return JSONResponse(
                        {"error": "Sistema bloqueado. Conclua a ativação em /activate."},
                        status_code=403,
                    )
                return RedirectResponse(url="/activate", status_code=302)
        return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
#  Rate limit global por IP
#  Protege contra abuso/scan/DDoS leve. Generoso (multi-terminal compartilha IP).
#  Isenta: localhost (webhook Evolution, worker interno) e arquivos estáticos.
# ─────────────────────────────────────────────────────────────────────────────

from .core.rate_limiter import global_limiter as _global_limiter
from .core.dependencies import client_ip as _client_ip

_RATE_EXEMPT_PREFIXES = (
    "/static/", "/logo/", "/favicon", "/internal/",
    "/api/evo-webhook", "/api/evo-file/",
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not any(path.startswith(p) for p in _RATE_EXEMPT_PREFIXES):
            ip = _client_ip(request)
            # localhost isento (worker, webhook, healthcheck local)
            if ip not in ("127.0.0.1", "::1", "unknown"):
                if not _global_limiter.is_allowed(ip):
                    return JSONResponse(
                        {"error": "Muitas requisições. Aguarde alguns segundos e tente novamente."},
                        status_code=429,
                        headers={"Retry-After": "10"},
                    )
        return await call_next(request)


# ── Lifespan ───────────────────────────────────────────────────────────────────
_startup_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Log de inicialização ──────────────────────────────────────────────────
    try:
        import json as _json
        from pathlib import Path as _vpath
        _vfile = _vpath(__file__).parent / "versao.json"
        _versao = _json.loads(_vfile.read_text()).get("versao", "?") if _vfile.exists() else "?"
    except Exception:
        _versao = "?"

    _backend = "Evolution API" if settings.use_evolution else "Playwright (WhatsApp Web)"
    _startup_logger.info(
        "[startup] ========== ZapDin v%s iniciando ==========", _versao
    )
    _startup_logger.info(
        "[startup] Porta=%s | Backend WhatsApp=%s | Monitor=%s",
        settings.port, _backend, settings.monitor_url,
    )
    _startup_logger.info(
        "[startup] Estado=%s | Token Monitor=%s",
        settings.app_state,
        ("configurado" if settings.monitor_client_token else "NÃO CONFIGURADO — reinstale ou ative o sistema"),
    )

    await init_db()
    await log_event(nivel="info", modulo="sistema", acao="app_start",
                    mensagem=f"ZapDin iniciado — {settings.client_name}")

    # M3: carrega blacklist de sessões invalidadas do banco para a memória
    # Tokens revogados antes de um restart continuam inválidos após reiniciar.
    try:
        from datetime import datetime, timedelta, timezone as _tz
        from .core.security import load_invalidated_hashes
        async with get_db_direct() as _db3:
            _cutoff = datetime.now(tz=_tz.utc) - timedelta(seconds=settings.session_max_age)
            async with _db3.execute(
                "SELECT token_hash FROM invalidated_sessions WHERE invalidated_at > ?", (_cutoff,)
            ) as _cur3:
                _rows3 = await _cur3.fetchall()
            load_invalidated_hashes([r["token_hash"] for r in _rows3])
            _startup_logger.info("[startup] M3: %d sessão(ões) revogada(s) carregada(s) do banco", len(_rows3))
    except Exception as _e3:
        _startup_logger.debug("[startup] M3: falha ao carregar sessões revogadas: %s", _e3)

    # Protege o .env via DPAPI na primeira execução após instalação/update (Windows)
    # Máquinas já instaladas com .env em texto puro são protegidas automaticamente
    try:
        from .core.env_protector import protect_env_file, is_protected
        from pathlib import Path as _Path
        _env = _Path(settings.model_config.get("env_file") or "")
        if _env.exists() and not is_protected(_env):
            protected = protect_env_file(_env)
            if protected:
                _startup_logger.info("[startup] .env protegido via DPAPI automaticamente")
    except Exception:
        pass  # Nunca bloqueia o startup

    if not settings.is_locked:
        # Carrega sessões WA de todas as empresas
        async with get_db_direct() as db:
            await wa_manager.load_from_db(db)
            # Telegram: carrega config do primeiro tenant que tiver configurado
            async with db.execute(
                "SELECT value FROM config WHERE key='tg_bot_token' LIMIT 1"
            ) as cur:
                tg_token_row = await cur.fetchone()
            async with db.execute(
                "SELECT value FROM config WHERE key='tg_chat_id' LIMIT 1"
            ) as cur:
                tg_chat_row = await cur.fetchone()
            if tg_token_row and tg_chat_row:
                telegram_service.configure(tg_token_row["value"], tg_chat_row["value"])

        reporter.start()
        updater.start()
        telegram_service.start()
        queue_worker.start()  # processa mensagens, arquivos e campanha_envios
        queue_worker.start_requeue_sweep(3600)  # varre falhas-offline a cada 60min
        resumo_avaliacao_service.start()  # resumo diário de avaliações por empresa
        _startup_logger.info("[startup] Todos os serviços iniciados — sistema pronto")
    else:
        _startup_logger.warning(
            "[startup] Sistema BLOQUEADO (APP_STATE=%s) — aguardando ativação em /activate",
            settings.app_state,
        )

    yield

    # ── Cleanup: para todas as sessões Playwright antes de encerrar ──────────
    # Sem isso, os processos Node.js do Playwright ficam órfãos e causam EPIPE
    # na próxima inicialização do app.
    import asyncio as _asyncio
    stop_tasks = [
        _asyncio.create_task(sess.stop())
        for sess in list(wa_manager._sessions.values())
    ]
    if stop_tasks:
        await _asyncio.gather(*stop_tasks, return_exceptions=True)

    reporter.stop()
    updater.stop()
    telegram_service.stop()
    queue_worker.stop()
    await close_http_client()


# ── App ────────────────────────────────────────────────────────────────────────
fastapi_app = FastAPI(title="ZapDin App", version="2.0.0", lifespan=lifespan)

# Middlewares (ordem: o último add_middleware é o primeiro a executar)
# Ordem de execução: SecurityHeaders → RateLimit → Lock → rotas.
# RateLimit antes do Lock: barra abuso mesmo no estado bloqueado.
fastapi_app.add_middleware(LockMiddleware)
fastapi_app.add_middleware(RateLimitMiddleware)
fastapi_app.add_middleware(SecurityHeadersMiddleware)

# Routers
fastapi_app.include_router(activation_router)   # /activate + /api/activate
fastapi_app.include_router(internal_router)     # /internal/* (localhost only)
fastapi_app.include_router(monitor_sync_router) # /api/monitor-sync/* (token auth, rede)
fastapi_app.include_router(auth_login_router)    # /api/auth/* — login, logout, me, check-cnpj
fastapi_app.include_router(auth_empresa_router)  # /api/auth/* — auto-setup, registrar-empresa
fastapi_app.include_router(auth_usuarios_router) # /api/auth/usuarios — CRUD usuários
fastapi_app.include_router(whatsapp.router)
fastapi_app.include_router(erp.router)
fastapi_app.include_router(config_router.router)
fastapi_app.include_router(ai_config_router)        # /api/config/ai-keys, ai-key, ai-uso
fastapi_app.include_router(arquivos.router)
fastapi_app.include_router(stats.router)
fastapi_app.include_router(telegram_router.router)
fastapi_app.include_router(docs_router)             # /api/docs/* (documentação)
fastapi_app.include_router(campanha_router)         # /api/campanha/* (disparo em massa)
fastapi_app.include_router(pdv_router)              # /api/pdv/* (ZapDin PDV local)
fastapi_app.include_router(avaliacao_router)        # /avaliacao + /api/avaliacao/* + /api/avaliacoes
fastapi_app.include_router(chatbot_router)          # /api/chatbot/* (chatbot IA)
fastapi_app.include_router(syslog_router)            # /api/syslog/* (log do sistema)
fastapi_app.include_router(ia_central_router)       # /api/ia-central/* (IA Central)
fastapi_app.include_router(home_router)             # /api/home/* (Home Dashboard)
fastapi_app.include_router(agents_router)           # /api/agents + /metrics (NAT agent + Prometheus)
fastapi_app.include_router(chat_router)             # /api/chat/* (integração chat/chamados — Evolution)
from .routers.kit import router as kit_router
fastapi_app.include_router(kit_router)               # /instalar/{kit} + /api/kit/* (onboarding self-service)


@fastapi_app.post("/api/logout")
async def logout_alias(request: Request, db=Depends(get_db)):
    from .core.security import SESSION_COOKIE, invalidate_token, get_token_hash
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        invalidate_token(token)
        # M3: persiste hash no banco para sobreviver a restarts
        try:
            await db.execute(
                "INSERT INTO invalidated_sessions (token_hash) VALUES (?) ON CONFLICT DO NOTHING",
                (get_token_hash(token),),
            )
            await db.commit()
        except Exception:
            pass  # falha no log não quebra o logout
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@fastapi_app.get("/api/agents")
async def list_connected_agents(user: dict = Depends(get_current_user)):
    """Lista agentes locais (postos) conectados via WS /agent.

    Requer sessão autenticada. Filtra por empresa_id do usuário.
    """
    agents = _agent_bridge.list_agents()
    emp_id = user.get("empresa_id") if isinstance(user, dict) else None
    if emp_id:
        agents = [a for a in agents if a.get("empresa_id") == emp_id]
    return {"agents": agents, "count": len(agents)}


@fastapi_app.get("/api/version")
async def api_version():
    """Versão atual do app (lida de versao.json)."""
    import json as _json2
    from pathlib import Path as _Path2
    p = _Path2(__file__).parent / "versao.json"
    if p.exists():
        try:
            return {"versao": _json2.loads(p.read_text()).get("versao", "?"), "build": APP_BUILD}
        except Exception:
            pass
    return {"versao": "?", "build": APP_BUILD}


@fastapi_app.get("/api/evo-file/{token}")
async def evo_file_serve(token: str):
    """Serve arquivos temporários para a Evolution API buscar via URL local."""
    from .services.evolution_service import _file_tokens, _file_tokens_lock
    with _file_tokens_lock:
        path = _file_tokens.get(token)
    if not path or not os.path.exists(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


@fastapi_app.post("/api/evo-webhook")
async def evo_webhook(request: Request):
    """Recebe eventos da Evolution API em tempo real (QR, conexão, etc.)."""
    import logging as _log
    _wh_log = _log.getLogger("app.webhook")
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False}, status_code=400)
    # Log temporário de diagnóstico — remover após confirmar funcionamento
    event = payload.get("event", "?")
    inst  = payload.get("instance", "?")
    data  = payload.get("data") or {}
    key   = data.get("key") or {}
    _wh_log.info("[webhook] event=%s inst=%s fromMe=%s jid=%s type=%s",
                 event, inst,
                 key.get("fromMe", "?"),
                 key.get("remoteJid", "?"),
                 data.get("messageType", "?"))
    wa_manager.handle_webhook(payload)
    return {"ok": True}


# ── Arquivos estáticos ────────────────────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "static")
_logo_dir = os.path.join(_static_dir, "logo")

_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
APP_BUILD = "20260623c"


from starlette.middleware.base import BaseHTTPMiddleware

class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/") or request.url.path.startswith("/logo/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

fastapi_app.add_middleware(NoCacheStaticMiddleware)


@fastapi_app.get("/favicon.ico")
@fastapi_app.get("/favicon.png")
async def serve_favicon():
    p = os.path.join(_static_dir, "logo", "favicon.png")
    if os.path.exists(p):
        return FileResponse(p, media_type="image/png")
    return Response(status_code=404)


@fastapi_app.get("/login")
async def serve_login():
    return FileResponse(os.path.join(_static_dir, "login.html"), headers=_NO_CACHE)


@fastapi_app.get("/redefinir-senha")
async def serve_redefinir_senha():
    return FileResponse(os.path.join(_static_dir, "redefinir-senha.html"), headers=_NO_CACHE)


@fastapi_app.get("/static/pages/{page_name}")
async def serve_page(page_name: str):
    pages_dir = os.path.join(_static_dir, "pages")
    page_file = os.path.join(pages_dir, page_name)
    if not os.path.exists(page_file) or not page_name.endswith(".html"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    with open(page_file, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content, headers=_NO_CACHE)


# Serve CSS, JS e outros assets estáticos (css/, js/, etc.)
# Este mount deve ficar antes do spa_fallback (/{full_path:path}) para ter prioridade.
# NOTA: serve_page (/static/pages/) deve ficar ANTES deste mount para ter prioridade.
fastapi_app.mount("/static", StaticFiles(directory=_static_dir), name="static")
if os.path.isdir(_logo_dir):
    fastapi_app.mount("/logo", StaticFiles(directory=_logo_dir), name="logo")


@fastapi_app.get("/{full_path:path}")
async def spa_fallback(request: Request, full_path: str):
    if full_path.startswith("api/") or full_path.startswith("internal/"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    index = os.path.join(_static_dir, "index.html")
    if os.path.exists(index):
        import asyncio as _aio
        def _read_index():
            with open(index, "r", encoding="utf-8") as f:
                return f.read()
        content = (await _aio.to_thread(_read_index)).replace("__BUILD__", APP_BUILD)
        return HTMLResponse(content=content, headers=_NO_CACHE, media_type="text/html; charset=utf-8")
    return JSONResponse({"error": "Frontend not found"}, status_code=404)


# ── ASGI wrapper com Socket.IO ─────────────────────────────────────────────────
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)


def main() -> None:
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=False)


if __name__ == "__main__":
    main()
