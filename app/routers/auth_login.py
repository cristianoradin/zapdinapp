"""
app/routers/auth_login.py — Autenticação: login, logout, me, check-cnpj, empresa-info.

Fluxo de login em 2 etapas:
  1. POST /api/auth/check-cnpj  → verifica se o CNPJ está ativo no Monitor
  2. POST /api/auth/login       → valida usuário/senha (local ou fallback ao Monitor)
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from ..core.config import settings
from ..core.database import get_db
from ..core.http_client import get_http_client
from ..core.rate_limiter import login_limiter as _login_limiter, activation_limiter
from ..core.dependencies import client_ip
from ..core.security import (
    verify_password,
    create_session_token,
    SESSION_COOKIE,
    get_current_user,
    normalize_cnpj,
    invalidate_token,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# Rate limiters importados de core/rate_limiter.py (centralizados)


# client_ip importado de core/dependencies.py

# Sentinel: usuário criado localmente sem hash real (autenticado via monitor)
MONITOR_AUTH_SENTINEL = "__MONITOR_AUTH__"


# ── Modelos ───────────────────────────────────────────────────────────────────

class CNPJCheck(BaseModel):
    cnpj: str


class LoginRequest(BaseModel):
    cnpj: str | None = None
    username: str
    password: str


# ── Info pública da empresa instalada ─────────────────────────────────────────

@router.get("/empresa-info")
async def empresa_info(db=Depends(get_db)):
    """Retorna CNPJ e nome da empresa ativa (sem autenticação — usado pelo login.html)."""
    async with db.execute(
        "SELECT cnpj, nome FROM empresas WHERE ativo = TRUE ORDER BY id LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return {"cnpj": None, "nome": None}
    return {"cnpj": row["cnpj"], "nome": row["nome"]}


# ── Passo 1: Verifica CNPJ ────────────────────────────────────────────────────

@router.post("/check-cnpj")
async def check_cnpj(body: CNPJCheck, request: Request, db=Depends(get_db)):
    cnpj = normalize_cnpj(body.cnpj)
    if len(cnpj) != 14:
        raise HTTPException(status_code=400, detail="CNPJ inválido. Informe os 14 dígitos.")

    ip = client_ip(request)
    if not _login_limiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde 1 minuto.")

    client_token = settings.monitor_client_token
    if not client_token:
        async with db.execute(
            "SELECT token FROM empresas WHERE ativo = TRUE ORDER BY id LIMIT 1"
        ) as cur:
            _emp = await cur.fetchone()
        if _emp and _emp["token"]:
            client_token = _emp["token"]
            settings.monitor_client_token = client_token

    if not client_token:
        raise HTTPException(status_code=503, detail="Sistema não ativado. Informe o token de ativação.")

    monitor_url = settings.monitor_url.rstrip("/")
    try:
        http = get_http_client()
        r = await http.post(
            f"{monitor_url}/api/auth/check-cnpj",
            json={"cnpj": cnpj, "client_token": client_token},
        )
    except Exception as exc:
        logger.error("Erro ao contatar Monitor (check-cnpj): %s", exc)
        raise HTTPException(status_code=503, detail="Não foi possível conectar ao servidor de autenticação.")

    if r.status_code in (404, 403):
        detail = r.json().get("detail", "CNPJ não autorizado.")
        raise HTTPException(status_code=r.status_code, detail=detail)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Erro no servidor de autenticação ({r.status_code}).")

    data = r.json()
    return {"ok": True, "nome": data["nome"], "cnpj": cnpj}


# ── Passo 2: Login com usuário/senha ──────────────────────────────────────────

@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response, db=Depends(get_db)):
    """
    Fluxo de autenticação (SEC-04):
      1. Busca empresa e usuário local no banco
      2. Se o usuário tem hash real (importado do monitor) → verifica localmente.
         A senha NUNCA é enviada ao monitor neste caminho.
      3. Se não tem hash real (primeiro login) → fallback ao monitor para verificar.
         Após sucesso, cria usuário local com sentinel MONITOR_AUTH_SENTINEL.
    """
    username = body.username.strip().lower()

    ip = client_ip(request)
    if not _login_limiter.is_allowed(ip):
        logger.warning("[login] Rate limit atingido — IP=%s usuário='%s' bloqueado por 1 minuto", ip, username)
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde 1 minuto.")

    # Tenta obter token: primeiro de settings, depois do banco (fallback)
    client_token = settings.monitor_client_token
    if not client_token:
        async with db.execute(
            "SELECT token FROM empresas WHERE ativo = TRUE ORDER BY id LIMIT 1"
        ) as cur:
            _emp = await cur.fetchone()
        if _emp and _emp["token"]:
            client_token = _emp["token"]
            settings.monitor_client_token = client_token

    if not client_token:
        logger.error("[login] MONITOR_CLIENT_TOKEN ausente e nenhuma empresa ativa no banco")
        raise HTTPException(status_code=503, detail="Sistema não ativado. Informe o token de ativação.")

    monitor_url = settings.monitor_url.rstrip("/")

    # ── Busca empresa ─────────────────────────────────────────────────────────
    if body.cnpj:
        cnpj_norm = normalize_cnpj(body.cnpj)
        async with db.execute(
            "SELECT id, nome, token FROM empresas WHERE cnpj = ? AND ativo = TRUE", (cnpj_norm,)
        ) as cur:
            emp = await cur.fetchone()
    else:
        emp = None

    if not emp:
        async with db.execute(
            "SELECT id, nome, token FROM empresas WHERE ativo = TRUE ORDER BY id LIMIT 1"
        ) as cur:
            emp = await cur.fetchone()

    if not emp:
        logger.error("[login] Nenhuma empresa ativa no banco")
        raise HTTPException(status_code=503, detail="Nenhuma empresa ativa. Ative o sistema primeiro.")

    empresa_id   = emp["id"]
    empresa_nome = emp["nome"]
    emp_token    = emp["token"] or client_token

    # ── Busca usuário local ───────────────────────────────────────────────────
    async with db.execute(
        "SELECT id, password_hash FROM usuarios WHERE username = ? AND empresa_id = ?",
        (username, empresa_id),
    ) as cur:
        local_user = await cur.fetchone()

    has_real_hash = (
        local_user is not None
        and local_user["password_hash"]
        and local_user["password_hash"] != MONITOR_AUTH_SENTINEL
    )

    if has_real_hash:
        if not verify_password(body.password, local_user["password_hash"]):
            logger.warning("[login] Falha de autenticação local para '%s'", username)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas.")
        logger.debug("[login] Autenticação local para '%s'", username)

    else:
        # Sem hash local → chama monitor (primeiro login ou usuário sem hash real)
        logger.debug("[login] Sem hash local para '%s', verificando no Monitor", username)
        try:
            http = get_http_client()
            r = await http.post(
                f"{monitor_url}/api/auth/verificar",
                json={"username": username, "password": body.password, "client_token": client_token},
            )
        except Exception as exc:
            logger.error("Erro ao contatar Monitor (login): %s", exc)
            raise HTTPException(status_code=503, detail="Não foi possível conectar ao servidor de autenticação.")

        if r.status_code == 401:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas.")
        if r.status_code == 403:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Acesso não autorizado para este posto.")
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Erro no servidor de autenticação ({r.status_code}).")

    # ── Busca menus do monitor (sem senha) ────────────────────────────────────
    menus_from_monitor = None
    try:
        http = get_http_client()
        mr = await http.get(
            f"{monitor_url}/api/auth/usuario-menus/{username}",
            params={"client_token": emp_token},
        )
        if mr.status_code == 200:
            menus_from_monitor = mr.json().get("menus")
    except Exception as exc:
        logger.debug("[login] Não foi possível buscar menus do monitor: %s", exc)

    menus_json = json.dumps(menus_from_monitor) if menus_from_monitor is not None else None

    # ── Cria ou atualiza usuário local ────────────────────────────────────────
    if local_user:
        local_uid = local_user["id"]
        await db.execute(
            "UPDATE usuarios SET menus = ? WHERE id = ? AND empresa_id = ?",
            (menus_json, local_uid, empresa_id),
        )
        await db.commit()
    else:
        cur2 = await db.execute(
            "INSERT INTO usuarios (empresa_id, username, password_hash, menus) VALUES (?, ?, ?, ?)",
            (empresa_id, username, MONITOR_AUTH_SENTINEL, menus_json),
        )
        await db.commit()
        local_uid = cur2.lastrowid or 0

    token = create_session_token(local_uid, username, empresa_id)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_max_age,
    )
    return {"ok": True, "username": username, "empresa": empresa_nome}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        invalidate_token(token)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user), db=Depends(get_db)):
    empresa_id = user.get("empresa_id")
    empresa_nome = None
    empresa_cnpj = None
    menus = None
    u = None

    if empresa_id:
        async with db.execute(
            "SELECT nome, cnpj FROM empresas WHERE id = ?", (empresa_id,)
        ) as cur:
            emp = await cur.fetchone()
        if emp:
            empresa_nome = emp["nome"]
            empresa_cnpj = emp["cnpj"]

        async with db.execute(
            "SELECT menus, avatar_url FROM usuarios WHERE id = ? AND empresa_id = ?",
            (user["uid"], empresa_id),
        ) as cur:
            u = await cur.fetchone()
        if u and u["menus"]:
            try:
                menus = json.loads(u["menus"])
            except Exception:
                menus = None

    avatar_url = (u["avatar_url"] if u else None) if empresa_id else None

    return {
        "username": user["usr"],
        "uid": user["uid"],
        "empresa_id": empresa_id,
        "empresa": empresa_nome,
        "cnpj": empresa_cnpj,
        "menus": menus,
        "avatar_url": avatar_url,
    }


# ── Alterar usuário/senha local ───────────────────────────────────────────────

class AlterarUsuarioBody(BaseModel):
    senha_atual: str
    novo_username: str = ""
    nova_senha: str = ""
    confirmar_senha: str = ""


@router.put("/usuario")
async def alterar_usuario(
    body: AlterarUsuarioBody,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    uid        = user["uid"]
    empresa_id = user["empresa_id"]

    # Busca hash atual
    async with db.execute(
        "SELECT username, password_hash FROM usuarios WHERE id=? AND empresa_id=?",
        (uid, empresa_id),
    ) as cur:
        row = await cur.fetchone()

    if not row:
        raise HTTPException(404, "Usuário não encontrado")

    if not verify_password(body.senha_atual, row["password_hash"]):
        raise HTTPException(400, "Senha atual incorreta")

    novo_username = body.novo_username.strip() or row["username"]
    nova_senha    = body.nova_senha.strip()

    if nova_senha:
        if nova_senha != body.confirmar_senha.strip():
            raise HTTPException(400, "As senhas não coincidem")
        if len(nova_senha) < 6:
            raise HTTPException(400, "A nova senha deve ter pelo menos 6 caracteres")
        novo_hash = hash_password(nova_senha)
    else:
        novo_hash = row["password_hash"]

    # Verifica conflito de username
    if novo_username != row["username"]:
        async with db.execute(
            "SELECT id FROM usuarios WHERE empresa_id=? AND username=? AND id!=?",
            (empresa_id, novo_username, uid),
        ) as cur:
            conflict = await cur.fetchone()
        if conflict:
            raise HTTPException(400, "Nome de usuário já está em uso")

    await db.execute(
        "UPDATE usuarios SET username=?, password_hash=? WHERE id=? AND empresa_id=?",
        (novo_username, novo_hash, uid, empresa_id),
    )
    await db.commit()
    return {"ok": True, "username": novo_username}
