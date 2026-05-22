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
    password: str


class AlterarSenhaRequest(BaseModel):
    password: str


@router.get("/usuarios")
async def listar_usuarios(db=Depends(get_db), user: dict = Depends(get_current_user)):
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT id, username, created_at FROM usuarios WHERE empresa_id = ? ORDER BY username",
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
    empresa_id = user["empresa_id"]
    username = body.username.strip().lower()
    if not username or len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Username inválido ou senha muito curta (mínimo 6 caracteres).")

    try:
        cur = await db.execute(
            "INSERT INTO usuarios (empresa_id, username, password_hash) VALUES (?, ?, ?)",
            (empresa_id, username, hash_password(body.password)),
        )
        await db.commit()
        return {"id": cur.lastrowid, "username": username}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Username já existe nesta empresa.")


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
