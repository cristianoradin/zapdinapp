import hashlib
import hmac
from typing import Optional

import bcrypt
from fastapi import Cookie, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

_serializer = URLSafeTimedSerializer(settings.secret_key)

SESSION_COOKIE = "zapdin_session"

# ── Blacklist de tokens invalidados (logout) ──────────────────────────────────
# M3: armazena SHA-256 do token (não o token cru) — mais seguro e suficiente
# para lookup. Persistência no banco: tabela invalidated_sessions.
# Populada no startup via load_invalidated_hashes().
_invalidated_hashes: set[str] = set()


def _token_hash(token: str) -> str:
    """SHA-256 do token de sessão — usado como chave na blacklist."""
    return hashlib.sha256(token.encode()).hexdigest()


def load_invalidated_hashes(hashes: list[str]) -> None:
    """Popula a blacklist em memória com hashes carregados do banco no startup."""
    _invalidated_hashes.update(hashes)


def invalidate_token(token: str) -> None:
    """Invalida token na memória. Persistência no banco feita pelo caller async."""
    _invalidated_hashes.add(_token_hash(token))


def get_token_hash(token: str) -> str:
    """Expõe o hash do token para que o caller async possa persistir no banco."""
    return _token_hash(token)


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
    # M3: rejeita tokens na blacklist (hash lookup — seguro e rápido)
    if _token_hash(token) in _invalidated_hashes:
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


def hash_erp_token(token: str) -> str:
    """SHA-256 do token ERP — valor a ser armazenado no banco."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_erp_token(token: str, stored: str) -> bool:
    """
    M8: comparação segura contra timing attacks.
    Suporta dois formatos no banco:
      - Hash SHA-256 (64 chars hex): compare hash(incoming) com stored  ← novo padrão
      - Plaintext legado: compare diretamente (migração transparente)
    """
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored):
        # Novo padrão: armazena hash, compara hash
        return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), stored)
    # Legado: plaintext — compara diretamente (tokens existentes continuam funcionando)
    return hmac.compare_digest(token.encode(), stored.encode())
