"""
app/routers/agents.py — Endpoints REST adicionais de gestão de agentes.

NOTA: GET /api/agents já existe em app/main.py:408 (lista da empresa logada).
Aqui ficam endpoints admin + métricas + ativação + auto-update:

  POST /api/agents/activate  — público: valida token + retorna empresa (instalador)
  GET  /api/agents/version   — público: versão atual + URL de download (auto-update)
  GET  /api/agents/all       — admin-only: lista TODOS os agentes (header X-Monitor-Token)
  GET  /metrics              — métricas Prometheus (texto plain) — público
"""
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.database import get_db_direct
from ..core.security import get_current_user
from ..services import agent_bridge

router = APIRouter(tags=["agents"])


# ── Ativação do instalador ───────────────────────────────────────────────────

class ActivatePayload(BaseModel):
    token: str = Field(min_length=8, max_length=256)


@router.post("/api/agents/activate")
async def activate_agent(body: ActivatePayload):
    """
    Valida token contra empresas.token e retorna empresa.
    Usado pelo instalador do agente pra dar feedback antes de gravar .env.
    Não cria sessão — apenas valida + retorna info da empresa.
    """
    token = body.token.strip()
    try:
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT id, nome, cnpj, ativo FROM empresas WHERE token = ? LIMIT 1",
                (token,),
            ) as cur:
                row = await cur.fetchone()
    except Exception as exc:
        raise HTTPException(503, f"Erro ao consultar banco: {exc}")

    if not row:
        raise HTTPException(401, "Token inválido. Verifique o token no painel ZapDin.")
    if not row["ativo"]:
        raise HTTPException(403, "Empresa inativa. Contate o suporte.")

    return {
        "ok": True,
        "empresa_id": row["id"],
        "empresa_nome": row["nome"] or "",
        "cnpj": row["cnpj"] or "",
    }


# ── Auto-update (agent polls daily) ──────────────────────────────────────────

# Versão alvo do agent. Bump quando uma release nova estiver pronta no GitHub.
AGENT_LATEST_VERSION = "0.2.41"
# .exe hospedado no próprio servidor (evita exigir GitHub auth — repo zapdinagent é private)
# Usa o instalador PRO (tray sem consoles) — é o que os clientes rodam.
AGENT_DOWNLOAD_URL = f"/static/downloads/ZapDinAgentSetup-Pro-{AGENT_LATEST_VERSION}.exe"


def _absolute_download_url(request: Request) -> str:
    """Constrói URL absoluta do .exe baseada no host da requisição."""
    base = str(request.base_url).rstrip("/")
    return base + AGENT_DOWNLOAD_URL


@router.get("/api/agents/download")
async def agent_download(request: Request):
    """Redirect 302 pro .exe hospedado no servidor."""
    return RedirectResponse(url=AGENT_DOWNLOAD_URL, status_code=302)


@router.get("/api/agents/install-script.bat")
async def install_script_personalized(request: Request, user: dict = Depends(get_current_user)):
    """Gera .bat personalizado com token da empresa do usuário.

    Cliente baixa, double-click → instala silencioso + ativa automatic.
    Sem CMD prompt, sem digitar token.
    """
    empresa_id = user["empresa_id"]
    try:
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT nome, cnpj, token FROM empresas WHERE id=? LIMIT 1", (empresa_id,),
            ) as cur:
                row = await cur.fetchone()
    except Exception as exc:
        raise HTTPException(503, f"Erro DB: {exc}")
    if not row or not row.get("token"):
        raise HTTPException(404, "Token da empresa não encontrado.")

    nome = (row["nome"] or "").replace('"', "").replace("\r", "").replace("\n", "")
    cnpj = (row["cnpj"] or "").replace('"', "").replace("\r", "").replace("\n", "")
    token = row["token"]
    base = str(request.base_url).rstrip("/")
    exe_url = base + AGENT_DOWNLOAD_URL

    bat_content = (
        "@echo off\r\n"
        "setlocal\r\n"
        "title Instalando ZapDin Agent\r\n"
        "echo.\r\n"
        "echo ============================================================\r\n"
        f"echo   ZapDin Agent - Instalacao Personalizada\r\n"
        f"echo   Empresa: {nome}\r\n"
        f"echo   CNPJ: {cnpj}\r\n"
        "echo ============================================================\r\n"
        "echo.\r\n"
        "\r\n"
        "REM Verifica admin\r\n"
        "net session >nul 2>&1\r\n"
        "if %errorLevel% NEQ 0 (\r\n"
        "    echo Solicitando privilegios de Administrador...\r\n"
        "    powershell -Command \"Start-Process -Verb RunAs -FilePath '%~f0'\"\r\n"
        "    exit /b 0\r\n"
        ")\r\n"
        "\r\n"
        f"set TOKEN={token}\r\n"
        f"set EXE_URL={exe_url}\r\n"
        "set SETUP=%TEMP%\\ZapDinAgentSetup.exe\r\n"
        "\r\n"
        "echo Baixando instalador...\r\n"
        "curl.exe -L -o \"%SETUP%\" \"%EXE_URL%\"\r\n"
        "if not exist \"%SETUP%\" (\r\n"
        "    echo ERRO: Download falhou.\r\n"
        "    pause\r\n"
        "    exit /b 2\r\n"
        ")\r\n"
        "\r\n"
        "echo Instalando ZapDin Agent (silencioso, ~2-4 min)...\r\n"
        "\"%SETUP%\" /SILENT /SUPPRESSMSGBOXES /NORESTART /TOKEN=%TOKEN%\r\n"
        "set RC=%errorlevel%\r\n"
        "\r\n"
        "echo.\r\n"
        "if %RC% EQU 0 (\r\n"
        "    echo Instalacao concluida com sucesso!\r\n"
        "    echo Servico ZapDinAgent registrado e iniciado.\r\n"
        ") else (\r\n"
        "    echo Instalacao retornou codigo %RC%. Verifique:\r\n"
        "    echo   C:\\Program Files\\ZapDin Agent\\install-service-debug.log\r\n"
        ")\r\n"
        "echo.\r\n"
        "pause\r\n"
    )

    safe_name = "".join(c if c.isalnum() else "_" for c in nome)[:30]
    filename = f"install-zapdin-{safe_name}.bat"
    return Response(
        content=bat_content,
        media_type="application/x-msdownload",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/changelog")
async def changelog():
    """Retorna histórico de versões (app + agent) — exibido na UI."""
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "changelog.json"
    if not p.exists():
        return {"versions": [], "agent_versions": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"changelog parse: {exc}")


@router.get("/api/agents/version")
async def agent_version(request: Request, current: Optional[str] = None):
    """
    Endpoint público consumido pelo agent client em loop de auto-update.

    Retorna:
      - latest: versão alvo (string semver-like)
      - download_url: URL HTTPS do .exe da release
      - update_available: True se `current` < `latest` (lexical compare por tuple)

    O agent passa `?current=0.2.0` e se update_available=True, baixa + executa /SILENT.
    """
    def _ver_tuple(v: str) -> tuple:
        parts = []
        for x in (v or "0").split("."):
            try: parts.append(int(x))
            except Exception: parts.append(0)
        return tuple(parts)

    # AUTO-UPDATE DESLIGADO por padrão: update é PUSH-ONLY (comando WS "update_now").
    # EXCEÇÃO bootstrap: versões legadas listadas em AGENT_BOOTSTRAP_VERSIONS (sem o
    # handler update_now) recebem update_available=True UMA vez pra se resgatarem via
    # poller. Após chegarem em AGENT_LATEST_VERSION (que não tem poller), param sozinhas.
    bootstrap = {v.strip() for v in (settings.agent_bootstrap_versions or "").split(",") if v.strip()}
    cur = current or ""
    update_available = bool(
        cur in bootstrap and _ver_tuple(cur) < _ver_tuple(AGENT_LATEST_VERSION)
    )
    # Agente remoto baixa da URL pública (não localhost).
    base = (settings.public_url or "").rstrip("/")
    download_url_abs = (base + AGENT_DOWNLOAD_URL) if base else _absolute_download_url(request)
    return {
        "latest": AGENT_LATEST_VERSION,
        "download_url": download_url_abs,
        "current": cur,
        "update_available": update_available,
    }


@router.get("/api/agents/ping")
async def agent_ping(user: dict = Depends(get_current_user)):
    """Pinga agent da empresa do usuário via WS — testa comunicação real.

    Retorna:
      connected      bool
      version        str (do agent registrado)
      last_seen_sec  float (segundos desde último heartbeat)
      latency_ms     int (RTT roundtrip Socket.IO; None se ping falhou)
      state          str (resultado do comando get_state: open/connecting/loading/close)
      error          str (se houver)
    """
    empresa_id = user["empresa_id"]
    ag = agent_bridge.get_agent(empresa_id)
    if not ag:
        return {
            "connected": False,
            "error": "Nenhum agent conectado para esta empresa.",
        }

    now = time.time()
    last_seen_sec = round(now - (ag.get("last_seen") or now), 1)
    version = ag.get("version", "?")

    # Round-trip via Socket.IO. Tenta ping (leve, v0.2.17+); fallback get_state.
    from ..main import sio
    import asyncio as _asyncio
    state = None
    err = None
    latency_ms = None

    # 1. Tenta ping (lightweight) — só responde em v0.2.17+
    t0 = time.perf_counter()
    res_ping = None
    try:
        res_ping = await sio.call(
            "ping",
            {"command": "ping", "payload": {}},
            to=ag["sid"],
            namespace="/agent",
            timeout=5,
        )
    except _asyncio.TimeoutError:
        res_ping = None
    except Exception:
        res_ping = None

    if isinstance(res_ping, dict) and res_ping.get("ok"):
        latency_ms = int((time.perf_counter() - t0) * 1000)
        state = "ready" if res_ping.get("chromium_started") else "idle"
    else:
        # 2. Fallback: get_state (spawn Chromium 1a vez = lento)
        t0 = time.perf_counter()
        try:
            res = await sio.call(
                "get_state",
                {"command": "get_state", "payload": {"instance": "ping"}},
                to=ag["sid"],
                namespace="/agent",
                timeout=45,
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if isinstance(res, dict) and res.get("ok"):
                state = res.get("state") or "?"
            else:
                err = (res or {}).get("error") if isinstance(res, dict) else "agent não respondeu"
        except _asyncio.TimeoutError:
            err = "Timeout — agent não respondeu em 45s. Chromium pode estar lento; tente em 1min."
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"

    return {
        "connected": True,
        "version": version,
        "last_seen_sec": last_seen_sec,
        "latency_ms": latency_ms,
        "state": state,
        "error": err,
    }


@router.get("/api/admin/queue-stats")
async def admin_queue_stats(
    x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token"),
):
    """Fila por empresa (pendentes/enviados hoje/erros) — consumido pelo Monitor."""
    expected = settings.monitor_client_token
    if not expected or not x_monitor_token or x_monitor_token != expected:
        raise HTTPException(401, "X-Monitor-Token inválido")
    try:
        async with get_db_direct() as db:
            async with db.execute(
                """
                SELECT e.id AS empresa_id, e.nome, e.token,
                  (SELECT COUNT(*) FROM mensagens m WHERE m.empresa_id=e.id AND m.status='queued')                          AS msgs_pendentes,
                  (SELECT COUNT(*) FROM mensagens m WHERE m.empresa_id=e.id AND m.status='failed' AND m.created_at::date = CURRENT_DATE) AS msgs_erro_hoje,
                  (SELECT COUNT(*) FROM mensagens m WHERE m.empresa_id=e.id AND m.status='sent'   AND m.sent_at::date = CURRENT_DATE)    AS msgs_enviadas_hoje,
                  (SELECT COUNT(*) FROM arquivos a WHERE a.empresa_id=e.id AND a.status='queued')                            AS arqs_pendentes,
                  (SELECT COUNT(*) FROM arquivos a WHERE a.empresa_id=e.id AND a.status='failed' AND a.created_at::date = CURRENT_DATE)  AS arqs_erro_hoje,
                  (SELECT COUNT(*) FROM campanha_envios ce JOIN campanhas c ON c.id=ce.campanha_id
                    WHERE ce.empresa_id=e.id AND ce.status='queued' AND c.status='running')                                  AS camp_pendentes
                FROM empresas e
                WHERE e.ativo = TRUE
                ORDER BY e.nome
                """,
                (),
            ) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        raise HTTPException(503, f"DB: {exc}")

    # Contagem de agentes: empresas com sessão modo agente vs online no agent_bridge
    agentes = {"online": 0, "offline": 0, "total": 0}
    try:
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT DISTINCT empresa_id FROM sessoes_wa WHERE evolution_url='agent://'",
                (),
            ) as cur:
                com_agente = {r["empresa_id"] for r in await cur.fetchall()}
        from ..services import agent_bridge as _ab
        online_ids = {a["empresa_id"] for a in _ab.list_agents()}
        online = len(com_agente & online_ids)
        agentes = {"online": online, "offline": len(com_agente) - online, "total": len(com_agente)}
    except Exception:
        pass  # contagem de agentes é best-effort

    return {"empresas": rows, "agentes": agentes}


class SysWhatsBody(BaseModel):
    numero: str = Field(min_length=8, max_length=20)
    mensagem: str = Field(min_length=1, max_length=4096)
    empresa_id: int = 1   # SGA Petro (número central) por padrão


@router.post("/api/admin/send-whatsapp")
async def admin_send_whatsapp(
    body: SysWhatsBody,
    x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token"),
):
    """Envio de WhatsApp do SISTEMA (monitor → app), via número central (SGA=empresa 1).
    Enfileira como tipo 'sistema' (prioritário). Usado por cadastro de cliente, etc."""
    expected = settings.monitor_client_token
    if not expected or not x_monitor_token or x_monitor_token != expected:
        raise HTTPException(401, "X-Monitor-Token inválido")
    from ..services.alerta_service import enviar_para_numeros
    ok = await enviar_para_numeros(body.empresa_id, [body.numero], body.mensagem, tipo="sistema")
    return {"ok": bool(ok)}


class EmpresaUpsertPayload(BaseModel):
    nome: str
    cnpj: str
    token: str
    ativo: bool = True


@router.post("/api/admin/empresas/upsert")
async def admin_upsert_empresa(
    body: EmpresaUpsertPayload,
    x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token"),
):
    """Cria/atualiza empresa no app DB + sessão WA default (modo Agente). Idempotente."""
    expected = settings.monitor_client_token
    if not expected or not x_monitor_token or x_monitor_token != expected:
        raise HTTPException(401, "X-Monitor-Token inválido")
    import uuid as _uuid
    try:
        async with get_db_direct() as db:
            await db.execute(
                """INSERT INTO empresas (nome, cnpj, token, ativo, modos_conexao)
                   VALUES (?, ?, ?, ?, 'servidor,local,agente')
                   ON CONFLICT (token) DO UPDATE SET nome=EXCLUDED.nome, cnpj=EXCLUDED.cnpj, ativo=EXCLUDED.ativo""",
                (body.nome, body.cnpj, body.token, body.ativo),
            )
            await db.commit()
            async with db.execute("SELECT id FROM empresas WHERE token=?", (body.token,)) as cur:
                row = await cur.fetchone()
            empresa_id = row["id"] if row else None

            # Auto-cria sessão WhatsApp default (modo Agente) se nao tiver nenhuma.
            # INSERT ... WHERE NOT EXISTS é atômico → evita corrida (2 sessões duplicadas
            # quando upsert + kit polling rodam concorrentes).
            if empresa_id:
                sessao_id = str(_uuid.uuid4())[:8]
                await db.execute(
                    """INSERT INTO sessoes_wa (empresa_id, id, nome, status, evolution_url)
                       SELECT ?, ?, 'WhatsApp Principal', 'disconnected', 'agent://'
                       WHERE NOT EXISTS (SELECT 1 FROM sessoes_wa WHERE empresa_id = ?)""",
                    (empresa_id, sessao_id, empresa_id),
                )
                await db.commit()
    except Exception as exc:
        raise HTTPException(503, f"DB: {exc}")
    return {"ok": True, "empresa_id": empresa_id}


@router.put("/api/admin/empresas/{empresa_id}/modos-conexao")
async def admin_set_modos_conexao(
    empresa_id: int,
    payload: dict,
    x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token"),
):
    """Monitor admin define modos permitidos por empresa. Auth via X-Monitor-Token."""
    expected = settings.monitor_client_token
    if not expected or not x_monitor_token or x_monitor_token != expected:
        raise HTTPException(401, "X-Monitor-Token inválido")
    modos_in = payload.get("modos") or []
    if not isinstance(modos_in, list):
        raise HTTPException(422, "modos deve ser lista")
    allowed = {"servidor", "local", "agente"}
    modos = [m for m in modos_in if isinstance(m, str) and m in allowed]
    if not modos:
        raise HTTPException(422, "Pelo menos 1 modo deve ser selecionado")
    csv_value = ",".join(modos)
    try:
        async with get_db_direct() as db:
            await db.execute("UPDATE empresas SET modos_conexao=? WHERE id=?", (csv_value, empresa_id))
            await db.commit()
    except Exception as exc:
        raise HTTPException(503, f"DB: {exc}")
    return {"ok": True, "empresa_id": empresa_id, "modos": modos}


@router.put("/api/admin/empresas/{empresa_id}/agente-dono")
async def admin_set_agente_dono(
    empresa_id: int,
    payload: dict,
    x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token"),
):
    """Define a empresa DONA do agente (grupo econômico): a empresa passa a usar o
    número/agente da dona pra enviar, mantendo seus próprios dados. dono=None desfaz.
    Auth via X-Monitor-Token."""
    expected = settings.monitor_client_token
    if not expected or not x_monitor_token or x_monitor_token != expected:
        raise HTTPException(401, "X-Monitor-Token inválido")
    dono = payload.get("dono_empresa_id")
    if dono is not None:
        try:
            dono = int(dono)
        except (TypeError, ValueError):
            raise HTTPException(422, "dono_empresa_id inválido")
        if dono == empresa_id:
            raise HTTPException(422, "Empresa não pode ser dona dela mesma")
    try:
        async with get_db_direct() as db:
            if dono is not None:
                # Dona precisa existir e NÃO ter dona (evita cadeia/ciclo — 1 nível só)
                async with db.execute(
                    "SELECT agente_dono_empresa_id FROM empresas WHERE id=?", (dono,)
                ) as cur:
                    row = await cur.fetchone()
                if not row:
                    raise HTTPException(404, "Empresa dona não encontrada")
                if row["agente_dono_empresa_id"] is not None:
                    raise HTTPException(422, "A dona já usa o agente de outra empresa — escolha a empresa raiz")
            await db.execute(
                "UPDATE empresas SET agente_dono_empresa_id=? WHERE id=?", (dono, empresa_id)
            )
            await db.commit()
            # Recarrega o mapa inteiro pra refletir já (sem esperar o heartbeat)
            async with db.execute(
                "SELECT id, agente_dono_empresa_id FROM empresas WHERE agente_dono_empresa_id IS NOT NULL"
            ) as cur:
                rows = await cur.fetchall()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, f"DB: {exc}")
    agent_bridge.set_owner_map({r["id"]: r["agente_dono_empresa_id"] for r in rows})
    return {"ok": True, "empresa_id": empresa_id, "dono_empresa_id": dono}


@router.post("/api/admin/empresas/{empresa_id}/unbind-device")
async def admin_unbind_device(
    empresa_id: int,
    x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token"),
):
    """Libera o vínculo de dispositivo do token (permite ativar em outra máquina).
    Auth via X-Monitor-Token."""
    expected = settings.monitor_client_token
    if not expected or x_monitor_token != expected:
        raise HTTPException(401, "X-Monitor-Token inválido")
    try:
        async with get_db_direct() as db:
            await db.execute("UPDATE empresas SET bound_device_id=NULL WHERE id=?", (empresa_id,))
            await db.commit()
    except Exception as exc:
        raise HTTPException(503, f"DB: {exc}")
    return {"ok": True, "empresa_id": empresa_id, "unbound": True}


@router.post("/api/admin/agents/{empresa_id}/update")
async def admin_push_update(
    empresa_id: int,
    request: Request,
    x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token"),
):
    """PUSH de atualização: manda o agente da empresa baixar+instalar a versão atual.
    Disparado pelo monitor (botão Atualizar agente). Auth via X-Monitor-Token."""
    expected = settings.monitor_client_token
    if not expected or not x_monitor_token or x_monitor_token != expected:
        raise HTTPException(401, "X-Monitor-Token inválido")
    if not agent_bridge.has_agent(empresa_id):
        raise HTTPException(409, "Agente não está conectado — não dá pra enviar update agora.")
    from ..main import sio
    # O agente está num posto remoto: precisa baixar da URL PÚBLICA do servidor,
    # não de request.base_url (que vira localhost quando o monitor chama internamente).
    base = (settings.public_url or "").rstrip("/")
    dl_url = (base + AGENT_DOWNLOAD_URL) if base else _absolute_download_url(request)
    try:
        res = await sio.call(
            "update_now",
            {"command": "update_now", "payload": {"download_url": dl_url, "version": AGENT_LATEST_VERSION}},
            to=agent_bridge.get_agent(empresa_id)["sid"],
            namespace="/agent",
            timeout=30,
        )
    except Exception as exc:
        # O agente baixa + se mata pra instalar — pode não responder o ACK. Não é erro fatal.
        return {"ok": True, "detail": f"Comando enviado (sem ACK: {exc}). Agente vai atualizar e reconectar."}
    return {"ok": True, "version": AGENT_LATEST_VERSION, "agent_response": res}


@router.post("/api/admin/agents/update-all")
async def admin_push_update_all(
    request: Request,
    x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token"),
):
    """PUSH em massa: manda TODOS os agentes conectados (que não estejam na versão
    atual) baixarem + instalarem o AGENT_LATEST_VERSION (silencioso). Disparado pelo
    portal. Cada agente baixa, se mata pra instalar e reconecta sozinho."""
    expected = settings.monitor_client_token
    if not expected or not x_monitor_token or x_monitor_token != expected:
        raise HTTPException(401, "X-Monitor-Token inválido")
    from ..main import sio
    base = (settings.public_url or "").rstrip("/")
    dl_url = (base + AGENT_DOWNLOAD_URL) if base else _absolute_download_url(request)
    sent, skipped = [], []
    for ag in agent_bridge.list_agents():
        eid = ag.get("empresa_id")
        if (ag.get("version") or "") == AGENT_LATEST_VERSION:
            skipped.append(eid)
            continue
        sid = ag.get("sid")
        if not sid:
            continue
        try:
            await sio.call(
                "update_now",
                {"command": "update_now", "payload": {"download_url": dl_url, "version": AGENT_LATEST_VERSION}},
                to=sid, namespace="/agent", timeout=8,
            )
        except Exception:
            pass  # agente baixa+se mata pra instalar — pode não dar ACK
        sent.append(eid)
    return {"ok": True, "latest": AGENT_LATEST_VERSION, "enviados": sent, "ja_atualizados": skipped}


@router.get("/api/agents/all")
async def list_all_agents(
    x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token"),
):
    """Admin: lista TODOS os agentes conectados (cross-empresa). Auth: token do monitor."""
    expected = settings.monitor_client_token
    if not expected or not x_monitor_token or x_monitor_token != expected:
        raise HTTPException(401, "X-Monitor-Token inválido")
    now = time.time()
    agents = []
    for ag in agent_bridge.list_agents():
        agents.append({
            **ag,
            "seconds_since_last_seen": round(now - (ag.get("last_seen") or 0), 1),
        })
    return {"total": len(agents), "agents": agents}


# ── Prometheus metrics ───────────────────────────────────────────────────────

@router.get("/metrics")
async def prometheus_metrics():
    """Métricas Prometheus em formato text/plain."""
    now = time.time()
    agents = agent_bridge.list_agents()

    lines = []

    # Total de agentes conectados
    lines.append("# HELP zapdin_agents_connected Total de agentes WebSocket atualmente conectados.")
    lines.append("# TYPE zapdin_agents_connected gauge")
    lines.append(f"zapdin_agents_connected {len(agents)}")

    # Por agente: segundos desde último heartbeat
    lines.append("")
    lines.append("# HELP zapdin_agent_seconds_since_last_seen Segundos desde último heartbeat por empresa.")
    lines.append("# TYPE zapdin_agent_seconds_since_last_seen gauge")
    for ag in agents:
        eid = ag.get("empresa_id")
        ver = (ag.get("version") or "?").replace('"', '\\"')
        sec = round(now - (ag.get("last_seen") or 0), 1)
        lines.append(
            f'zapdin_agent_seconds_since_last_seen{{empresa_id="{eid}",version="{ver}"}} {sec}'
        )

    # Uptime do agente (segundos desde connected_at)
    lines.append("")
    lines.append("# HELP zapdin_agent_uptime_seconds Tempo desde connect inicial por empresa.")
    lines.append("# TYPE zapdin_agent_uptime_seconds gauge")
    for ag in agents:
        eid = ag.get("empresa_id")
        ver = (ag.get("version") or "?").replace('"', '\\"')
        up = round(now - (ag.get("connected_at") or now), 1)
        lines.append(
            f'zapdin_agent_uptime_seconds{{empresa_id="{eid}",version="{ver}"}} {up}'
        )

    body = "\n".join(lines) + "\n"
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
