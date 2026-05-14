"""
app/core/http_client.py — Cliente HTTP global (singleton).

Reutiliza conexões TCP com o Monitor em vez de criar um novo
httpx.AsyncClient a cada requisição. Reduz latência e overhead de
handshake em endpoints chamados frequentemente (login, auto-setup, etc.).

Uso:
    from ..core.http_client import get_http_client
    client = get_http_client()
    r = await client.get("http://monitor.test/...")

Inicialização e fechamento gerenciados pelo lifespan do FastAPI (main.py).
"""
from __future__ import annotations

import httpx

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Retorna o cliente HTTP global. Cria um novo se ainda não existir."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30,
            ),
        )
    return _client


async def close_http_client() -> None:
    """Fecha o cliente HTTP global. Chamado no teardown do lifespan."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
