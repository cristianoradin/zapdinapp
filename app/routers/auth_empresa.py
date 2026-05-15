"""
app/routers/auth_empresa.py — Onboarding e registro de empresa.

  POST /api/auth/auto-setup        → auto-registra via MONITOR_CLIENT_TOKEN do .env
  POST /api/auth/registrar-empresa → onboarding manual via token fornecido pelo usuário
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from ..core.config import settings
from ..core.database import get_db
from ..core.http_client import get_http_client
from ..core.security import normalize_cnpj
from .auth_login import activation_limiter, client_ip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegistrarEmpresaRequest(BaseModel):
    token: str


async def _sync_empresa_from_monitor(db, monitor_url: str, token: str) -> dict:
    """
    Consulta o Monitor com o token do cliente, cria/atualiza a empresa e importa usuários.
    Retorna dict com: nome, cnpj, usuarios_importados, client_token.
    Levanta HTTPException em caso de erro.
    """
    try:
        client = get_http_client()
        r = await client.get(f"{monitor_url}/api/auth/cliente/{token}")
    except Exception as exc:
        logger.error("[empresa-sync] Erro ao chamar Monitor: %s", exc)
        raise HTTPException(status_code=503, detail="Não foi possível conectar ao servidor de ativação.")

    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Token não encontrado. Verifique o token informado.")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Monitor retornou erro {r.status_code}.")

    data = r.json()
    cnpj = normalize_cnpj(data.get("cnpj", ""))
    nome = data.get("nome", "Empresa")
    client_token = data.get("token", token)
    usuarios_monitor = data.get("usuarios", [])

    if not cnpj:
        raise HTTPException(status_code=422, detail="Monitor não retornou CNPJ válido.")

    await db.execute(
        """INSERT INTO empresas (cnpj, nome, token, ativo)
           VALUES (?, ?, ?, TRUE)
           ON CONFLICT (cnpj) DO UPDATE
           SET nome = EXCLUDED.nome, token = EXCLUDED.token, ativo = TRUE""",
        (cnpj, nome, client_token),
    )
    await db.commit()

    async with db.execute("SELECT id FROM empresas WHERE cnpj = ?", (cnpj,)) as c:
        emp_row = await c.fetchone()
    empresa_id = emp_row["id"]

    usuarios_importados = 0
    for u in usuarios_monitor:
        username = u.get("username", "").strip().lower()
        password_hash = u.get("password_hash", "")
        if not username or not password_hash:
            continue
        await db.execute(
            """INSERT INTO usuarios (empresa_id, username, password_hash)
               VALUES (?, ?, ?)
               ON CONFLICT (empresa_id, username) DO UPDATE
               SET password_hash = EXCLUDED.password_hash""",
            (empresa_id, username, password_hash),
        )
        usuarios_importados += 1
    await db.commit()

    return {
        "nome": nome,
        "cnpj": cnpj,
        "client_token": client_token,
        "usuarios_importados": usuarios_importados,
    }


@router.post("/auto-setup")
async def auto_setup(db=Depends(get_db)):
    """
    Auto-registra a empresa usando MONITOR_CLIENT_TOKEN do .env, sem interação do usuário.
    Chamado pela tela de login na primeira abertura após instalação.
    """
    # Empresa já existe — retorna sem fazer nada
    async with db.execute(
        "SELECT cnpj, nome FROM empresas WHERE ativo = TRUE ORDER BY id LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
    if row:
        return {"ok": True, "empresa": row["nome"], "cnpj": row["cnpj"], "usuarios_importados": 0}

    if not settings.monitor_client_token:
        logger.error("[auto-setup] MONITOR_CLIENT_TOKEN não configurado no .env")
        raise HTTPException(status_code=503, detail="Token de ativação não configurado. Reinstale o sistema.")

    monitor_url = settings.monitor_url.rstrip("/")
    logger.info("[auto-setup] Registrando empresa via Monitor: %s", monitor_url)

    result = await _sync_empresa_from_monitor(db, monitor_url, settings.monitor_client_token)
    logger.info("[auto-setup] Empresa registrada: %s (%s) — %d usuário(s)",
                result["nome"], result["cnpj"], result["usuarios_importados"])

    return {
        "ok": True,
        "empresa": result["nome"],
        "cnpj": result["cnpj"],
        "usuarios_importados": result["usuarios_importados"],
    }


@router.post("/registrar-empresa", status_code=status.HTTP_201_CREATED)
async def registrar_empresa(body: RegistrarEmpresaRequest, request: Request, db=Depends(get_db)):
    """Onboarding manual: usuário informa token recebido do Monitor."""
    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token não pode ser vazio.")

    ip = client_ip(request)
    if not activation_limiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Muitas tentativas de ativação. Aguarde 1 hora.")

    monitor_url = settings.monitor_url.rstrip("/")
    result = await _sync_empresa_from_monitor(db, monitor_url, token)

    # Atualiza settings em memória para que login funcione imediatamente
    if result["client_token"] and not settings.monitor_client_token:
        settings.monitor_client_token = result["client_token"]

    logger.info("Empresa ativada: %s (%s) — %d usuário(s) importado(s)",
                result["nome"], result["cnpj"], result["usuarios_importados"])
    return {
        "ok": True,
        "empresa": result["nome"],
        "cnpj": result["cnpj"],
        "usuarios_importados": result["usuarios_importados"],
        "message": f"Empresa ativada! {result['usuarios_importados']} usuário(s) importado(s). Faça login com seu usuário.",
    }
