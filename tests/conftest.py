"""
conftest.py — Fixtures compartilhadas para os testes do ZapDin App.

Estratégia:
  - loop_scope="session" em TODOS os fixtures async: pytest-asyncio 1.x cria
    um event loop por escopo. asyncpg não funciona entre loops diferentes.
    Com loop_scope="session", todos os fixtures e testes compartilham um loop.
  - APP_STATE=locked → lifespan não inicia background services.
  - Pool asyncpg criado uma vez (session) e reutilizado.
  - get_db sobrescrito para usar o pool de teste sem lifespan.
  - Tabelas truncadas entre cada teste.
  - settings restaurados entre cada teste.
"""
import os

# CRÍTICO: definir ANTES de qualquer import do app
os.environ.update({
    "APP_STATE":             "locked",
    "DATABASE_URL":          os.environ.get(
                                 "TEST_DATABASE_URL",
                                 f"postgresql://{os.environ.get('USER', 'postgres')}@localhost/zapdin_test",
                             ),
    "MONITOR_URL":           "http://monitor.test",
    "MONITOR_CLIENT_TOKEN":  "",
    "SECRET_KEY":            "a" * 64,
    "PORT":                  "4001",
    "CLIENT_NAME":           "Posto Teste",
    "CLIENT_CNPJ":           "12345678000195",
})

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import fastapi_app
from app.core.config import settings
from app.core import database as _db_module
from app.core.database import get_db, AsyncPGAdapter, init_db


# ─────────────────────────────────────────────────────────────────────────────
#  Pool de teste — loop_scope="session": mesmo loop que todos os outros fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_pool():
    """Pool asyncpg de teste. Criado uma vez, compartilhado via loop de sessão."""
    import asyncpg
    pool = await asyncpg.create_pool(
        os.environ["DATABASE_URL"],
        min_size=2,
        max_size=5,
    )
    _db_module._pool = pool

    # Garante que as tabelas existem (executando init_db sem fechar pool anterior)
    old_pool = _db_module._pool
    await init_db()
    if _db_module._pool is not old_pool:
        # init_db criou um pool novo — fecha o antigo e usa o novo
        await pool.close()
        pool = _db_module._pool

    yield pool
    await pool.close()
    _db_module._pool = None


# ─────────────────────────────────────────────────────────────────────────────
#  Limpeza entre testes — loop_scope="session" para usar o mesmo loop
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean_db(test_pool):
    """Trunca tabelas antes de cada teste para garantir isolamento."""
    async with test_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE empresas RESTART IDENTITY CASCADE")
    yield


# ─────────────────────────────────────────────────────────────────────────────
#  Cliente HTTP — loop_scope="session"
# ─────────────────────────────────────────────────────────────────────────────

def _make_db_override(pool):
    async def _override():
        async with pool.acquire() as conn:
            yield AsyncPGAdapter(conn)
    return _override


@pytest_asyncio.fixture(loop_scope="session")
async def client(test_pool):
    """
    Cliente HTTP que envia requests direto ao ASGI app sem rede.
    get_db sobrescrito para usar o pool de teste — sem precisar do lifespan.
    """
    fastapi_app.dependency_overrides[get_db] = _make_db_override(test_pool)
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app, raise_app_exceptions=True),
        base_url="http://test",
    ) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
#  Settings — restaura valores entre testes (sync fixture, sem loop)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_settings():
    _CAMPOS = ["app_state", "monitor_client_token", "monitor_url", "client_name"]
    saved = {k: getattr(settings, k) for k in _CAMPOS}
    yield
    for k, v in saved.items():
        setattr(settings, k, v)
