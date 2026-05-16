"""
app/core/dependencies.py — Dependências FastAPI centralizadas.

Evita repetir `db=Depends(get_db), user=Depends(get_current_user)` em todo router.
Também provê helpers de IP e validação de empresa.
"""
from __future__ import annotations
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .database import get_db
from .security import get_current_user


# ── Tipos anotados ────────────────────────────────────────────────────────────
# Uso: `async def endpoint(ctx: AppCtx)` em vez de dois Depends separados

DbDep   = Annotated[object, Depends(get_db)]
UserDep = Annotated[dict, Depends(get_current_user)]


# ── Helper: IP real do cliente ────────────────────────────────────────────────

def client_ip(request: Request) -> str:
    """Retorna IP real ignorando X-Forwarded-For forjado de redes externas."""
    direct_ip = request.client.host if request.client else "unknown"
    if direct_ip in ("127.0.0.1", "::1"):
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        return forwarded or direct_ip
    return direct_ip


# ── Helper: empresa_id do usuário logado ──────────────────────────────────────

def empresa_id_from(user: dict) -> int:
    eid = user.get("empresa_id")
    if not eid:
        raise HTTPException(status_code=403, detail="Empresa não identificada.")
    return int(eid)
