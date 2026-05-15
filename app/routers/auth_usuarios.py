"""
app/routers/auth_usuarios.py — CRUD de usuários dentro da empresa.

  POST   /api/auth/usuarios        → criar usuário adicional
  GET    /api/auth/usuarios        → listar usuários da empresa
  DELETE /api/auth/usuarios/{uid}  → remover usuário
"""
from __future__ import annotations

import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..core.database import get_db
from ..core.security import hash_password, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


class NovoUsuarioRequest(BaseModel):
    username: str
    password: str


@router.post("/usuarios", status_code=status.HTTP_201_CREATED)
async def criar_usuario(
    body: NovoUsuarioRequest,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    username = body.username.strip().lower()
    if not username or len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Username inválido ou senha muito curta.")

    try:
        cur = await db.execute(
            "INSERT INTO usuarios (empresa_id, username, password_hash) VALUES (?, ?, ?)",
            (empresa_id, username, hash_password(body.password)),
        )
        await db.commit()
        return {"id": cur.lastrowid, "username": username}
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Username já existe nesta empresa.")


@router.get("/usuarios")
async def listar_usuarios(db=Depends(get_db), user: dict = Depends(get_current_user)):
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT id, username, created_at FROM usuarios WHERE empresa_id = ? ORDER BY username",
        (empresa_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.delete("/usuarios/{uid}", status_code=status.HTTP_204_NO_CONTENT)
async def remover_usuario(uid: int, db=Depends(get_db), user: dict = Depends(get_current_user)):
    empresa_id = user["empresa_id"]
    if uid == user["uid"]:
        raise HTTPException(status_code=400, detail="Você não pode remover seu próprio usuário.")
    await db.execute(
        "DELETE FROM usuarios WHERE id = ? AND empresa_id = ?", (uid, empresa_id)
    )
    await db.commit()
