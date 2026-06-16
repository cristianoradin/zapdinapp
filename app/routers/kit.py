"""
app/routers/kit.py — Onboarding self-service (kit de instalação).

Fluxo:
  1. Monitor cria kit:  POST /api/admin/kits  (X-Monitor-Token) → URL única
  2. Cliente abre:      GET  /instalar/{kit_token}  → página assistente
  3. Página baixa:      GET  /api/kit/{kit_token}/installer.bat  → bat c/ token embutido
  4. Página acompanha:  GET  /api/kit/{kit_token}/status  → agent? WA? phone?
  5. Página mostra QR:  GET  /api/kit/{kit_token}/qr  → QR via agent_bridge
  6. WA conecta → kit marcado completed → QR/installer bloqueados (link vira inerte)

Segurança: kit_token é segredo de uso temporário (expira em 7 dias, morre no
sucesso). Endpoints públicos validam SEMPRE o kit antes de servir qualquer coisa.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from ..core.config import settings
from ..core.database import get_db_direct

logger = logging.getLogger(__name__)
router = APIRouter(tags=["kit"])

KIT_TTL_DAYS = 7


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _load_kit(kit_token: str) -> dict:
    """Carrega kit + empresa. Lança 404/410 conforme estado."""
    async with get_db_direct() as db:
        async with db.execute(
            """SELECT k.id, k.kit_token, k.empresa_id, k.expires_at, k.completed_at,
                      e.nome AS empresa_nome, e.cnpj, e.token AS empresa_token
               FROM install_kits k
               JOIN empresas e ON e.id = k.empresa_id AND e.ativo = TRUE
               WHERE k.kit_token = ?""",
            (kit_token,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Kit de instalação não encontrado.")
    exp = row["expires_at"]
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp and exp < datetime.now(timezone.utc):
        raise HTTPException(410, "Este link de instalação expirou. Solicite um novo.")
    return dict(row)


async def _marcar_completed(kit_id: int) -> None:
    async with get_db_direct() as db:
        await db.execute(
            "UPDATE install_kits SET completed_at = NOW() WHERE id = ? AND completed_at IS NULL",
            (kit_id,),
        )
        await db.commit()


async def _garantir_sessao(empresa_id: int) -> dict:
    """Retorna a 1ª sessão WA da empresa; cria default (modo agent) se não houver.
    Idempotente + auto-limpa duplicatas (corrida criava 2 'WhatsApp Principal')."""
    import uuid as _uuid
    async with get_db_direct() as db:
        # Auto-limpa duplicatas: remove 'WhatsApp Principal' (agent, desconectada)
        # extras, mantendo a mais antiga. Nunca apaga sessão conectada nem custom.
        await db.execute(
            """DELETE FROM sessoes_wa
                WHERE empresa_id = ? AND nome = 'WhatsApp Principal'
                  AND evolution_url = 'agent://' AND status <> 'connected'
                  AND id <> (
                      SELECT id FROM sessoes_wa WHERE empresa_id = ?
                       ORDER BY (status='connected') DESC, created_at ASC LIMIT 1
                  )""",
            (empresa_id, empresa_id),
        )
        await db.commit()
        async with db.execute(
            "SELECT id, status, phone FROM sessoes_wa WHERE empresa_id=? ORDER BY created_at LIMIT 1",
            (empresa_id,),
        ) as cur:
            sess = await cur.fetchone()
        if sess:
            return dict(sess)
        # Cria default — atômico (WHERE NOT EXISTS) pra evitar corrida
        sessao_id = str(_uuid.uuid4())[:8]
        await db.execute(
            """INSERT INTO sessoes_wa (empresa_id, id, nome, status, evolution_url)
               SELECT ?, ?, 'WhatsApp Principal', 'disconnected', 'agent://'
               WHERE NOT EXISTS (SELECT 1 FROM sessoes_wa WHERE empresa_id = ?)""",
            (empresa_id, sessao_id, empresa_id),
        )
        await db.commit()
        async with db.execute(
            "SELECT id, status, phone FROM sessoes_wa WHERE empresa_id=? ORDER BY created_at LIMIT 1",
            (empresa_id,),
        ) as cur:
            sess = await cur.fetchone()
        logger.info("[kit] sessão WA default garantida: empresa=%s", empresa_id)
        return dict(sess) if sess else {"id": sessao_id, "status": "disconnected", "phone": ""}


# ── Criação (Monitor → App) ───────────────────────────────────────────────────

class KitCreatePayload(BaseModel):
    empresa_token: str  # empresas.token (mesmo usado no upsert)


@router.post("/api/admin/kits")
async def criar_kit(
    body: KitCreatePayload,
    request: Request,
    x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token"),
):
    """Cria kit de instalação pra empresa. Retorna URL única."""
    expected = settings.monitor_client_token
    if not expected or not x_monitor_token or x_monitor_token != expected:
        raise HTTPException(401, "X-Monitor-Token inválido")

    async with get_db_direct() as db:
        async with db.execute(
            "SELECT id, nome FROM empresas WHERE token = ? AND ativo = TRUE", (body.empresa_token,)
        ) as cur:
            emp = await cur.fetchone()
        if not emp:
            raise HTTPException(404, "Empresa não encontrada no app (token).")

        kit_token = secrets.token_urlsafe(24)
        expires = datetime.now(timezone.utc) + timedelta(days=KIT_TTL_DAYS)
        await db.execute(
            "INSERT INTO install_kits (kit_token, empresa_id, expires_at) VALUES (?, ?, ?)",
            (kit_token, emp["id"], expires),
        )
        await db.commit()

    # public_url é o domínio externo (request.base_url seria localhost — monitor chama interno)
    base = (settings.public_url or str(request.base_url)).rstrip("/")
    url = f"{base}/instalar/{kit_token}"
    logger.info("[kit] criado para empresa=%s (%s) exp=%s", emp["id"], emp["nome"], expires.date())
    return {"ok": True, "kit_url": url, "expires_at": expires.isoformat(), "empresa_nome": emp["nome"]}


# ── Página pública do kit ─────────────────────────────────────────────────────

@router.get("/instalar/{kit_token}", response_class=HTMLResponse, include_in_schema=False)
async def pagina_kit(kit_token: str):
    kit = await _load_kit(kit_token)  # valida — 404/410 se inválido
    static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
    path = os.path.abspath(os.path.join(static_dir, "instalar.html"))
    html = open(path, encoding="utf-8").read()
    # Injeta dados básicos (sem expor empresa_token!)
    html = html.replace("__KIT_TOKEN__", kit_token)
    html = html.replace("__EMPRESA_NOME__", kit["empresa_nome"] or "")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


# ── Status ao vivo ────────────────────────────────────────────────────────────

@router.get("/api/kit/{kit_token}/status")
async def kit_status(kit_token: str):
    kit = await _load_kit(kit_token)
    empresa_id = kit["empresa_id"]

    from ..services import agent_bridge
    agent_on = agent_bridge.has_agent(empresa_id)

    sess = await _garantir_sessao(empresa_id)
    wa_status = sess.get("status") or "disconnected"
    wa_phone = sess.get("phone") or ""
    sessao_id = sess["id"]

    completed = kit["completed_at"] is not None
    if wa_status == "connected" and not completed:
        await _marcar_completed(kit["id"])
        completed = True

    return {
        "empresa_nome": kit["empresa_nome"],
        "agent_connected": agent_on,
        "wa_status": wa_status,
        "wa_phone": wa_phone,
        "sessao_id": sessao_id,
        "completed": completed,
    }


# ── Installer personalizado ───────────────────────────────────────────────────

@router.get("/api/kit/{kit_token}/installer.bat")
async def kit_installer(kit_token: str, request: Request):
    kit = await _load_kit(kit_token)
    if kit["completed_at"] is not None:
        raise HTTPException(410, "Instalação já concluída — kit encerrado.")

    from .agents import AGENT_DOWNLOAD_URL
    nome = (kit["empresa_nome"] or "").replace('"', "")
    cnpj = (kit["cnpj"] or "").replace('"', "")
    token = kit["empresa_token"]
    base = (settings.public_url or str(request.base_url)).rstrip("/")
    exe_url = base + AGENT_DOWNLOAD_URL

    bat = (
        "@echo off\r\n"
        "setlocal\r\n"
        "title Instalando ZapDin\r\n"
        "echo.\r\n"
        "echo ============================================================\r\n"
        "echo   ZapDin - Instalacao Automatica\r\n"
        f"echo   Empresa: {nome}\r\n"
        f"echo   CNPJ: {cnpj}\r\n"
        "echo ============================================================\r\n"
        "echo.\r\n"
        "net session >nul 2>&1\r\n"
        "if %errorLevel% NEQ 0 (\r\n"
        "    echo Solicitando privilegios de Administrador...\r\n"
        "    powershell -Command \"Start-Process -Verb RunAs -FilePath '%~f0'\"\r\n"
        "    exit /b 0\r\n"
        ")\r\n"
        f"set TOKEN={token}\r\n"
        f"set EXE_URL={exe_url}\r\n"
        "set SETUP=%TEMP%\\ZapDinAgentSetup.exe\r\n"
        "echo Baixando instalador...\r\n"
        "curl.exe -L -o \"%SETUP%\" \"%EXE_URL%\"\r\n"
        "if not exist \"%SETUP%\" (\r\n"
        "    echo ERRO: Download falhou. Verifique a internet.\r\n"
        "    pause\r\n"
        "    exit /b 2\r\n"
        ")\r\n"
        "echo Instalando (silencioso, 2-4 min)... NAO FECHE esta janela.\r\n"
        "\"%SETUP%\" /SILENT /SUPPRESSMSGBOXES /NORESTART /TOKEN=%TOKEN%\r\n"
        "set RC=%errorlevel%\r\n"
        "echo.\r\n"
        "if %RC% EQU 0 (\r\n"
        "    echo Instalacao concluida! Volte ao navegador para conectar o WhatsApp.\r\n"
        f"    start \"\" \"{base}/instalar/{kit_token}\"\r\n"
        ") else (\r\n"
        "    echo Instalacao terminou com codigo %RC%. Se houver erro, contate o suporte.\r\n"
        ")\r\n"
        "pause\r\n"
    )
    nome_arquivo = f"InstalarZapDin-{(nome or 'cliente').split()[0]}.bat"
    return Response(
        content=bat.encode("latin-1", errors="replace"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


# ── QR via agent (autenticado pelo kit) ───────────────────────────────────────

@router.get("/api/kit/{kit_token}/qr")
async def kit_qr(kit_token: str):
    kit = await _load_kit(kit_token)
    if kit["completed_at"] is not None:
        raise HTTPException(410, "WhatsApp já conectado — kit encerrado.")
    empresa_id = kit["empresa_id"]

    sess = await _garantir_sessao(empresa_id)
    sessao_id = sess["id"]

    from ..services import agent_bridge
    if not agent_bridge.has_agent(empresa_id):
        raise HTTPException(503, "Agente ainda não conectado — aguarde a instalação concluir.")

    from ..main import sio
    ag = agent_bridge.get_agent(empresa_id)
    try:
        res = await sio.call(
            "get_qr",
            {"command": "get_qr", "payload": {"instance": sessao_id}},
            to=ag["sid"],
            namespace="/agent",
            timeout=60,
        )
    except Exception as exc:
        raise HTTPException(504, f"Timeout/erro agent: {exc}")

    if isinstance(res, dict) and res.get("ok"):
        qr = res.get("qr") or ""
        state = res.get("state") or ""
        if not qr and state == "open":
            await _marcar_completed(kit["id"])
            return {"qr": "", "state": "open", "connected": True}
        if not qr:
            raise HTTPException(404, f"QR ainda não disponível (state={state}) — tente em 5s.")
        return {"qr": qr, "state": state, "connected": False}
    err = (res or {}).get("error") if isinstance(res, dict) else "agent não respondeu"
    raise HTTPException(502, f"Agent: {err}")
