import hmac
import time
from typing import Optional

import bcrypt
from fastapi import Cookie, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

_serializer = URLSafeTimedSerializer(settings.secret_key)

SESSION_COOKIE = "zapdin_session"

# ── Blacklist de tokens invalidados (logout) ──────────────────────────────────
# Chave: token string — Valor: timestamp de quando foi invalidado
# Entradas são removidas automaticamente após session_max_age expirar
_invalidated_tokens: dict[str, float] = {}


def invalidate_token(token: str) -> None:
    """Adiciona token à blacklist. Limpa entradas expiradas automaticamente."""
    _invalidated_tokens[token] = time.time()
    cutoff = time.time() - settings.session_max_age
    expired = [k for k, v in _invalidated_tokens.items() if v < cutoff]
    for k in expired:
        del _invalidated_tokens[k]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verifica senha contra hash bcrypt. Retorna False para hashes inválidos/corrompidos."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        # Hash inválido ou corrompido — trata como verificação negativa
        return False


def create_session_token(user_id: int, username: str, empresa_id: int) -> str:
    return _serializer.dumps(
        {"uid": user_id, "usr": username, "empresa_id": empresa_id},
        salt="session",
    )


def decode_session_token(token: str) -> Optional[dict]:
    # Rejeita tokens explicitamente invalidados (logout)
    if token in _invalidated_tokens:
        return None
    try:
        return _serializer.loads(token, salt="session", max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(
    zapdin_session: Optional[str] = Cookie(default=None),
) -> dict:
    if not zapdin_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")
    payload = decode_session_token(zapdin_session)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão expirada")
    return payload


def normalize_cnpj(cnpj: str) -> str:
    """Remove pontuação e retorna apenas dígitos do CNPJ."""
    return "".join(c for c in cnpj if c.isdigit())


def verify_erp_token(token: str, stored_token: str) -> bool:
    """Comparação segura contra timing attacks."""
    return hmac.compare_digest(token.encode(), stored_token.encode())
