"""
app/tests/conftest.py — Fixtures compartilhadas para todos os testes.

Estratégia de isolamento:
  - Usa banco de teste separado (TEST_DATABASE_URL ou zapdin_test no mesmo servidor)
  - Trunca tabelas críticas antes de cada sessão de testes
  - Cria empresa + usuário de teste via SQL direto (não via API)
  - Emite cookie de sessão assinado real para fixtures autenticadas

Configuração:
  Defina TEST_DATABASE_URL no .env ou como variável de ambiente.
  Se ausente, os testes que precisam de banco são pulados automaticamente.

Uso:
  cd ~/Zapdin2
  app/.venv/bin/python -m pytest app/tests/ -v
"""
import os
import pytest
import asyncpg
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# ── Detecta URL de teste ──────────────────────────────────────────────────────
_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

# Sinaliza ausência de banco de teste — testes que precisam de DB são marcados
# com @pytest.mark.skipif(not _TEST_DB_URL, ...) ou usam a fixture `db_conn`
# que já pula automaticamente.
_SKIP_DB = not _TEST_DB_URL


# ── Configuração pytest-asyncio ───────────────────────────────────────────────
# Todos os testes assíncronos usam o modo "auto" para evitar decoradores
# @pytest.mark.asyncio em cada função.
pytest_plugins = ("pytest_asyncio",)


# ── Fixtures de banco de dados ────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def db_pool():
    """Pool asyncpg apontando para o banco de teste. Pula se TEST_DATABASE_URL ausente."""
    if _SKIP_DB:
        pytest.skip("TEST_DATABASE_URL não configurada — pulando testes de banco")
    pool = await asyncpg.create_pool(_TEST_DB_URL, min_size=1, max_size=3)
    yield pool
    await pool.close()


@pytest_asyncio.fixture(scope="session")
async def db_schema(db_pool):
    """Inicializa o schema no banco de teste (idempotente — CREATE IF NOT EXISTS)."""
    # Importa e executa o init_db do app com o pool de teste
    import app.core.database as _db_module
    original_pool = _db_module._pool
    _db_module._pool = db_pool
    try:
        await _db_module.init_db()
    finally:
        _db_module._pool = original_pool
    yield


@pytest_asyncio.fixture
async def db_conn(db_pool, db_schema):
    """
    Conexão com transação revertida após cada teste.
    Garante isolamento sem precisar truncar tabelas.
    """
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        yield conn
        await tr.rollback()


# ── Fixtures de empresa/usuário de teste ─────────────────────────────────────

@pytest_asyncio.fixture
async def empresa_usuario(db_conn):
    """
    Cria empresa e usuário de teste na transação atual.
    Retorna dict com empresa_id, user_id, username, password.
    """
    from app.core.security import hash_password

    empresa_id = await db_conn.fetchval(
        """INSERT INTO empresas (cnpj, nome, token, ativo)
           VALUES ($1, $2, $3, TRUE)
           ON CONFLICT (cnpj) DO UPDATE SET nome = EXCLUDED.nome
           RETURNING id""",
        "00000000000001", "Empresa Teste", "token-teste",
    )

    user_id = await db_conn.fetchval(
        """INSERT INTO usuarios (empresa_id, username, password_hash)
           VALUES ($1, $2, $3)
           ON CONFLICT (empresa_id, username) DO UPDATE
           SET password_hash = EXCLUDED.password_hash
           RETURNING id""",
        empresa_id, "testuser", hash_password("senha123"),
    )

    return {
        "empresa_id": empresa_id,
        "user_id": user_id,
        "username": "testuser",
        "password": "senha123",
    }


# ── Fixture de cookie de sessão ───────────────────────────────────────────────

@pytest.fixture
def auth_cookie(empresa_usuario):
    """Retorna dict de cookies com sessão autenticada válida."""
    from app.core.security import create_session_token, SESSION_COOKIE
    token = create_session_token(
        empresa_usuario["user_id"],
        empresa_usuario["username"],
        empresa_usuario["empresa_id"],
    )
    return {SESSION_COOKIE: token}


# ── Fixture de cliente HTTP ───────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(db_pool, db_schema):
    """
    Cliente HTTP assíncrono apontando para o app FastAPI.
    Injeta o pool de teste no módulo de banco antes de cada requisição.
    """
    import app.core.database as _db_module
    original_pool = _db_module._pool
    _db_module._pool = db_pool

    # Importa a app FastAPI (sem o Socket.IO wrapper para testes HTTP)
    from app.main import fastapi_app
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    _db_module._pool = original_pool


@pytest_asyncio.fixture
async def auth_client(client, auth_cookie):
    """Cliente HTTP com cookie de sessão autenticado."""
    client.cookies.update(auth_cookie)
    yield client
