"""
app/routers/auth.py — Autenticação multi-tenant com CNPJ.

Fluxo de login em 2 etapas:
  1. POST /api/auth/check-cnpj  → verifica se o CNPJ está ativo
  2. POST /api/auth/login       → valida usuário vinculado àquele CNPJ

Ativação de empresa (onboarding):
  POST /api/auth/registrar-empresa → valida token no Monitor, cria empresa no DB
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from threading import Lock

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from ..core.config import settings
from ..core.database import get_db
from ..core.http_client import get_http_client
from ..core.security import (
    verify_password, hash_password, create_session_token,
    SESSION_COOKIE, get_current_user, normalize_cnpj, invalidate_token,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Rate limiter simples em memória ───────────────────────────────────────────

class _RateLimiter:
    """Limita chamadas por chave (IP) dentro de uma janela de tempo."""

    def __init__(self, max_calls: int, period_seconds: float):
        self._max = max_calls
        self._period = period_seconds
        self._calls: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            calls = self._calls[key]
            calls[:] = [t for t in calls if now - t < self._period]
            if len(calls) >= self._max:
                return False
            calls.append(now)
            return True


# 10 tentativas de login por IP por minuto
_login_limiter = _RateLimiter(max_calls=10, period_seconds=60)
# 5 tentativas de ativação/registro por IP por hora
_activation_limiter = _RateLimiter(max_calls=5, period_seconds=3600)


def _client_ip(request: Request) -> str:
    """Retorna IP real do cliente, ignorando X-Forwarded-For forjado."""
    # Só confia em X-Forwarded-For se vier de um proxy confiável (loopback)
    direct_ip = request.client.host if request.client else "unknown"
    if direct_ip in ("127.0.0.1", "::1"):
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        return forwarded or direct_ip
    return direct_ip


# ── Modelos ───────────────────────────────────────────────────────────────────

class CNPJCheck(BaseModel):
    cnpj: str


class LoginRequest(BaseModel):
    cnpj: str | None = None
    username: str
    password: str


class RegistrarEmpresaRequest(BaseModel):
    token: str


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
        raise HTTPException(status_code=503, detail="Token de ativação não configurado. Reinstale o sistema.")

    monitor_url = settings.monitor_url.rstrip("/")
    try:
        client = get_http_client()
        r = await client.get(f"{monitor_url}/api/auth/cliente/{settings.monitor_client_token}")
    except Exception as exc:
        logger.error("[auto-setup] Erro ao chamar Monitor: %s", exc)
        raise HTTPException(status_code=503, detail="Não foi possível conectar ao servidor de ativação.")

    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Token não encontrado no servidor.")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Monitor retornou erro {r.status_code}.")

    data = r.json()
    cnpj = normalize_cnpj(data.get("cnpj", ""))
    nome = data.get("nome", "Empresa")
    client_token = data.get("token", settings.monitor_client_token)
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

    logger.info("[auto-setup] Empresa registrada: %s (%s) — %d usuário(s)", nome, cnpj, usuarios_importados)
    return {"ok": True, "empresa": nome, "cnpj": cnpj, "usuarios_importados": usuarios_importados}


# ── Passo 1: Verifica CNPJ ────────────────────────────────────────────────────

@router.post("/check-cnpj")
async def check_cnpj(body: CNPJCheck, request: Request, db=Depends(get_db)):
    cnpj = normalize_cnpj(body.cnpj)
    if len(cnpj) != 14:
        raise HTTPException(status_code=400, detail="CNPJ inválido. Informe os 14 dígitos.")

    ip = _client_ip(request)
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
        client = get_http_client()
        r = await client.post(
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
    username = body.username.strip().lower()

    ip = _client_ip(request)
    if not _login_limiter.is_allowed(ip):
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
        raise HTTPException(status_code=503, detail="Sistema não ativado. Informe o token de ativação.")

    monitor_url = settings.monitor_url.rstrip("/")

    # Busca empresa enquanto valida no Monitor (em paralelo)
    async def _fetch_menus(emp_token: str):
        try:
            client = get_http_client()
            mr = await client.get(
                f"{monitor_url}/api/auth/usuario-menus/{username}",
                params={"client_token": emp_token},
            )
            if mr.status_code == 200:
                return mr.json().get("menus")
        except Exception as exc:
            logger.debug("[login] Não foi possível buscar menus do monitor: %s", exc)
        return None

    async def _fetch_empresa(cnpj: str | None):
        if cnpj:
            cnpj_norm = normalize_cnpj(cnpj)
            async with db.execute(
                "SELECT id, nome, token FROM empresas WHERE cnpj = ? AND ativo = TRUE", (cnpj_norm,)
            ) as cur:
                emp = await cur.fetchone()
            if emp:
                return emp
        async with db.execute(
            "SELECT id, nome, token FROM empresas WHERE ativo = TRUE ORDER BY id LIMIT 1"
        ) as cur:
            return await cur.fetchone()

    try:
        client = get_http_client()
        r = await client.post(
            f"{monitor_url}/api/auth/verificar",
            json={
                "username": username,
                "password": body.password,
                "client_token": client_token,
            },
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

    # Monitor validou — busca empresa e menus em paralelo
    emp = await _fetch_empresa(body.cnpj)
    if not emp:
        raise HTTPException(status_code=503, detail="Nenhuma empresa ativa. Ative o sistema primeiro.")

    empresa_id = emp["id"]
    empresa_nome = emp["nome"]
    emp_token = emp["token"] or client_token

    menus_from_monitor = await _fetch_menus(emp_token)

    # Busca ou cria usuário local
    async with db.execute(
        "SELECT id, password_hash FROM usuarios WHERE username = ? AND empresa_id = ?",
        (username, empresa_id),
    ) as cur:
        row = await cur.fetchone()

    menus_json = json.dumps(menus_from_monitor) if menus_from_monitor is not None else None

    if row:
        local_uid = row["id"]
        await db.execute(
            "UPDATE usuarios SET menus = ? WHERE id = ? AND empresa_id = ?",
            (menus_json, local_uid, empresa_id),
        )
        await db.commit()
    else:
        cur2 = await db.execute(
            "INSERT INTO usuarios (empresa_id, username, password_hash, menus) VALUES (?, ?, ?, ?)",
            (empresa_id, username, hash_password(""), menus_json),
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
async def logout(
    request: Request,
    response: Response,
):
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

    if empresa_id:
        async with db.execute(
            "SELECT nome, cnpj FROM empresas WHERE id = ?", (empresa_id,)
        ) as cur:
            emp = await cur.fetchone()
        if emp:
            empresa_nome = emp["nome"]
            empresa_cnpj = emp["cnpj"]

        async with db.execute(
            "SELECT menus FROM usuarios WHERE id = ? AND empresa_id = ?",
            (user["uid"], empresa_id),
        ) as cur:
            u = await cur.fetchone()
        if u and u["menus"]:
            try:
                menus = json.loads(u["menus"])
            except Exception:
                menus = None

    return {
        "username": user["usr"],
        "uid": user["uid"],
        "empresa_id": empresa_id,
        "empresa": empresa_nome,
        "cnpj": empresa_cnpj,
        "menus": menus,
    }


# ── Registrar nova empresa (onboarding via tokenForm) ─────────────────────────

@router.post("/registrar-empresa", status_code=status.HTTP_201_CREATED)
async def registrar_empresa(body: RegistrarEmpresaRequest, request: Request, db=Depends(get_db)):
    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token não pode ser vazio.")

    ip = _client_ip(request)
    if not _activation_limiter.is_allowed(ip):
        raise HTTPException(status_code=429, detail="Muitas tentativas de ativação. Aguarde 1 hora.")

    monitor_url = settings.monitor_url.rstrip("/")
    try:
        client = get_http_client()
        r = await client.get(f"{monitor_url}/api/auth/cliente/{token}")
    except Exception as exc:
        logger.error("Erro ao chamar Monitor: %s", exc)
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

    # Atualiza settings em memória para que login funcione imediatamente
    if client_token and not settings.monitor_client_token:
        settings.monitor_client_token = client_token

    logger.info("Empresa ativada: %s (%s) — %d usuário(s) importado(s)", nome, cnpj, usuarios_importados)
    return {
        "ok": True,
        "empresa": nome,
        "cnpj": cnpj,
        "usuarios_importados": usuarios_importados,
        "message": f"Empresa ativada! {usuarios_importados} usuário(s) importado(s). Faça login com seu usuário.",
    }


# ── Criar usuário adicional na empresa ────────────────────────────────────────

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
