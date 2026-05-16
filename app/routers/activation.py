"""
ZapDin — Router de Ativação
============================
GET  /activate           → serve activate.html (kiosk first-run)
POST /api/activate       → valida token no Monitor, grava .env, agenda restart
GET  /api/activate/status → retorna estado atual (locked | active)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..core.activation import decrypt_config, apply_config_to_env, env_path as get_env_path
from ..core.config import settings
from ..core.dependencies import client_ip as _client_ip
from ..core.http_client import get_http_client
from ..core.rate_limiter import activation_limiter as _activate_limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["activation"])

_static_dir = Path(__file__).parent.parent / "static"


# ─────────────────────────────────────────────────────────────────────────────
#  Modelos
# ─────────────────────────────────────────────────────────────────────────────

class ActivatePayload(BaseModel):
    token: str


# ─────────────────────────────────────────────────────────────────────────────
#  Rotas
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/activate")
async def serve_activation_page():
    """Página de ativação servida no kiosk (primeiro uso)."""
    html = _static_dir / "activate.html"
    if not html.exists():
        return JSONResponse({"error": "Página de ativação não encontrada."}, status_code=500)
    return FileResponse(str(html))


@router.get("/api/activate/status")
async def activation_status():
    """Retorna se o sistema está bloqueado ou ativo."""
    return {"state": settings.app_state}


@router.post("/api/activate")
async def activate(body: ActivatePayload, request: Request):
    """
    Fluxo:
      1. Envia token ao Monitor (POST /api/activate/validate)
      2. Monitor retorna config cifrada com AES-GCM
      3. App descriptografa localmente
      4. Grava .env com APP_STATE=active
      5. Agenda restart do processo (NSSM reinicia o serviço)
    """
    token = body.token.strip()
    ip = _client_ip(request)

    if not token:
        logger.warning("[activation] Tentativa de ativação com token vazio de ip=%s", ip)
        return JSONResponse({"ok": False, "error": "Token não pode ser vazio."}, status_code=400)

    if not _activate_limiter.is_allowed(ip):
        logger.warning("[activation] Rate limit atingido para ip=%s — bloqueado por 1 hora", ip)
        return JSONResponse(
            {"ok": False, "error": "Muitas tentativas de ativação. Aguarde 1 hora."},
            status_code=429,
        )

    # Normaliza formato: remove hífens, maiúsculas (exibido como XXXX-XXXX mas armazenado sem)
    token = token.replace("-", "").upper()
    monitor_url = settings.monitor_url.rstrip("/")
    logger.info("[activation] Iniciando ativação: ip=%s token=%s... monitor=%s", ip, token[:4], monitor_url)

    # ── 1. Valida token no Monitor ────────────────────────────────────────────
    try:
        client = get_http_client()
        resp = await client.post(
            f"{monitor_url}/api/activate/validate",
            json={"activation_token": token},
            headers={"x-client-token": settings.monitor_client_token or ""},
        )
    except httpx.ConnectError:
        logger.warning("[activation] Monitor inalcançável em %s", monitor_url)
        return JSONResponse(
            {"ok": False, "error": "Não foi possível conectar ao servidor de ativação. Verifique a rede."},
            status_code=503,
        )
    except Exception as exc:
        logger.error("[activation] Erro ao chamar Monitor: %s", exc)
        return JSONResponse({"ok": False, "error": "Erro interno ao validar token."}, status_code=500)

    if resp.status_code == 401:
        logger.warning("[activation] Token inválido ou expirado: ip=%s token=%s...", ip, token[:4])
        return JSONResponse({"ok": False, "error": "Token inválido ou expirado."}, status_code=401)

    if resp.status_code != 200:
        logger.error("[activation] Monitor respondeu %s: %s", resp.status_code, resp.text[:300])
        return JSONResponse(
            {"ok": False, "error": f"Servidor de ativação retornou erro {resp.status_code}."},
            status_code=502,
        )

    data = resp.json()

    # ── 2. Descriptografa config ──────────────────────────────────────────────
    try:
        config = decrypt_config(
            token=token,
            encrypted_b64=data["encrypted"],
            nonce_b64=data["nonce"],
            salt_b64=data.get("salt"),  # SEC-12: salt aleatório (None = Monitor legado)
        )
    except ValueError as exc:
        logger.error("[activation] Falha na descriptografia: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except KeyError:
        logger.error("[activation] Resposta do Monitor sem campos 'encrypted'/'nonce': %s", data)
        return JSONResponse({"ok": False, "error": "Resposta inesperada do servidor."}, status_code=502)

    # ── 3. Grava .env e ativa ──────────────────────────────────────────────────
    try:
        env_path = get_env_path()
        apply_config_to_env(config, env_path)
        # Após gravar o .env, criptografa via DPAPI (Windows) e apaga o texto puro
        try:
            from ..core.env_protector import protect_env_file
            protected = protect_env_file(env_path)
            if protected:
                logger.info("[activation] .env protegido via DPAPI — arquivo criptografado em disco")
        except Exception as _pe:
            logger.warning("[activation] DPAPI indisponível, .env mantido em texto puro: %s", _pe)
    except Exception as exc:
        logger.error("[activation] Erro ao gravar .env: %s", exc)
        return JSONResponse({"ok": False, "error": "Erro ao salvar configurações."}, status_code=500)

    # ── 4. Atualiza settings em memória imediatamente ────────────────────────
    # LockMiddleware e auth.py consultam settings.* (RAM), não o .env em disco.
    # Sem isso, o login falha com "Sistema não ativado" mesmo após gravar o .env.
    settings.app_state = "active"
    if config.get("monitor_client_token"):
        settings.monitor_client_token = config["monitor_client_token"]
    if config.get("MONITOR_URL"):
        settings.monitor_url = config["MONITOR_URL"]
    if config.get("CLIENT_NAME"):
        settings.client_name = config["CLIENT_NAME"]
    logger.info("[activation] Ativação bem-sucedida. Settings em memória atualizados. Reiniciando em 3s…")

    # ── 5. Agenda restart para recarregar config completa (DB URL, secret…) ──
    asyncio.create_task(_delayed_restart())

    return JSONResponse({
        "ok": True,
        "message": "Sistema ativado! Redirecionando para o login…",
    })


async def _delayed_restart() -> None:
    """Aguarda 3s para que o cliente receba a resposta e então encerra o processo.

    Task Scheduler (Windows):
      - exit code 1 → tratado como falha → RestartCount=3 reinicia o processo.
      - exit code 0 → sucesso → Task Scheduler NÃO reinicia automaticamente.
    Por isso usamos sys.exit(1) para garantir o restart via Task Scheduler.

    Em dev (Mac): o .command faz loop e reinicia automaticamente de qualquer forma.
    """
    await asyncio.sleep(3)
    logger.info("[activation] Encerrando com código 1 para Task Scheduler reiniciar…")
    sys.exit(1)
