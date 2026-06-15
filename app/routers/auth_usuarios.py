"""
app/routers/auth_usuarios.py — CRUD de usuários dentro da empresa.

  GET    /api/auth/usuarios          → listar usuários da empresa
  POST   /api/auth/usuarios          → criar usuário adicional
  PUT    /api/auth/usuarios/{uid}/senha → alterar senha de um usuário
  DELETE /api/auth/usuarios/{uid}    → remover usuário
"""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..core.database import get_db
from ..core.security import hash_password, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


class NovoUsuarioRequest(BaseModel):
    username: str
    password: str | None = None      # vazio = sistema gera senha aleatória
    email: str | None = None         # se preenchido, envia credenciais por e-mail
    send_welcome_email: bool = True


class AlterarSenhaRequest(BaseModel):
    password: str


@router.get("/usuarios")
async def listar_usuarios(db=Depends(get_db), user: dict = Depends(get_current_user)):
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT id, username, email, created_at FROM usuarios WHERE empresa_id = ? ORDER BY username",
        (empresa_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.post("/usuarios", status_code=status.HTTP_201_CREATED)
async def criar_usuario(
    body: NovoUsuarioRequest,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    import secrets as _secrets, string as _string
    empresa_id = user["empresa_id"]
    username = body.username.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="Nome de usuário inválido.")
    email = (body.email or "").strip().lower() or None
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        raise HTTPException(status_code=400, detail="E-mail inválido.")

    # Senha: usa a fornecida OU gera aleatória de 12 chars
    raw_password = (body.password or "").strip()
    autogerada = not raw_password
    if autogerada:
        alphabet = _string.ascii_letters + _string.digits + "!@#$%&*"
        raw_password = "".join(_secrets.choice(alphabet) for _ in range(12))
    if len(raw_password) < 6:
        raise HTTPException(status_code=400, detail="Senha muito curta (mínimo 6 caracteres).")

    try:
        cur = await db.execute(
            "INSERT INTO usuarios (empresa_id, username, email, password_hash, must_change_password) "
            "VALUES (?, ?, ?, ?, ?)",
            (empresa_id, username, email, hash_password(raw_password), autogerada),
        )
        await db.commit()
        usuario_id = cur.lastrowid
    except Exception as exc:
        # PostgreSQL UniqueViolation ou SQLite IntegrityError
        if "uniqu" in str(exc).lower() or "duplicate" in str(exc).lower() or isinstance(exc, sqlite3.IntegrityError):
            raise HTTPException(status_code=409, detail="Usuário ou e-mail já existe nesta empresa.")
        raise

    # Envia credenciais por e-mail (via monitor, que tem o SMTP)
    email_status = "skipped"
    if body.send_welcome_email and email:
        email_status = await _enviar_credenciais_via_monitor(username, email, raw_password)

    return {
        "id": usuario_id,
        "username": username,
        "email": email,
        "auto_password": autogerada,
        "temp_password": raw_password if autogerada else None,
        "email_status": email_status,
    }


async def _enviar_credenciais_via_monitor(username: str, email: str, senha: str) -> str:
    """Pede ao monitor pra enviar e-mail de boas-vindas (SMTP fica no monitor)."""
    from ..core.config import settings
    from ..core.http_client import get_http_client
    if not settings.monitor_url or not settings.monitor_client_token:
        return "monitor_nao_configurado"
    try:
        http = get_http_client()
        r = await http.post(
            f"{settings.monitor_url.rstrip('/')}/api/auth/enviar-credenciais",
            json={"email": email, "username": username, "senha": senha,
                  "app_url": settings.public_url},
            headers={"x-client-token": settings.monitor_client_token},
        )
        if r.status_code == 200:
            return "sent"
        try:
            return f"error: {r.json().get('detail', r.status_code)}"
        except Exception:
            return f"error: {r.status_code}"
    except Exception as exc:
        logger.warning("[usuarios] falha ao enviar credenciais via monitor: %s", exc)
        return f"error: {exc}"


@router.put("/usuarios/{uid}/senha", status_code=status.HTTP_200_OK)
async def alterar_senha(
    uid: int,
    body: AlterarSenhaRequest,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Senha muito curta (mínimo 6 caracteres).")

    async with db.execute(
        "SELECT id FROM usuarios WHERE id = ? AND empresa_id = ?", (uid, empresa_id)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    await db.execute(
        "UPDATE usuarios SET password_hash = ? WHERE id = ? AND empresa_id = ?",
        (hash_password(body.password), uid, empresa_id),
    )
    await db.commit()
    return {"ok": True}


@router.delete("/usuarios/{uid}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_usuario(uid: int, db=Depends(get_db), user: dict = Depends(get_current_user)):
    empresa_id = user["empresa_id"]
    if uid == user["uid"]:
        raise HTTPException(status_code=400, detail="Você não pode remover seu próprio usuário.")
    await db.execute(
        "DELETE FROM usuarios WHERE id = ? AND empresa_id = ?", (uid, empresa_id)
    )
    await db.commit()
