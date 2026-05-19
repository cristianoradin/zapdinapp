"""
app/tests/conftest.py — Fixtures compartilhadas para todos os testes.

Estratégia:
  - Override de fastapi_app.dependency_overrides[get_db] — cada request usa
    uma conexão asyncpg direta (sem pool compartilhado entre loops distintos).
  - empresa_usuario criado uma vez por sessão usando asyncio.run().
  - auth_cookie emitido uma vez por sessão.
  - db_conn: conexão direta por teste para seeds SQL.

Configuração:
  export TEST_DATABASE_URL="postgresql://user@localhost/zapdin_test"
  cd ~/Zapdin2 && app/.venv/bin/python -m pytest app/tests/ -v
"""
import asyncio
import os
import pytest
import asyncpg
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# ── URL de teste ──────────────────────────────────────────────────────────────
_TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://cristianoradin@localhost/zapdin_test",  # default local
)


# ── Schema — inicializado uma vez por sessão ──────────────────────────────────

def _run(coro):
    """Executa coroutine no loop atual ou cria um novo."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Estamos dentro de pytest-asyncio — não podemos criar loop novo
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _init_schema():
    """
    Inicializa o schema no banco de teste.
    Usa DATABASE_URL apontando para zapdin_test, para que init_db()
    crie o pool e as tabelas no banco correto.
    """
    import os
    import app.core.database as _db_module

    # Salva URL original e força test URL
    original_url = os.environ.get("DATABASE_URL", "")
    os.environ["DATABASE_URL"] = _TEST_DB_URL

    # Reinicializa settings com nova URL
    try:
        from app.core.config import settings
        settings.__dict__["database_url"] = _TEST_DB_URL
    except Exception:
        pass

    original_pool = _db_module._pool
    try:
        await _db_module.init_db()
    finally:
        # Fecha o pool de teste criado pelo init_db
        if _db_module._pool and _db_module._pool is not original_pool:
            await _db_module._pool.close()
        _db_module._pool = original_pool

        # Restaura DATABASE_URL original
        if original_url:
            os.environ["DATABASE_URL"] = original_url
        else:
            os.environ.pop("DATABASE_URL", None)


async def _truncate_test_data():
    """Remove todos os dados de teste anteriores (exceto schema)."""
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        # Trunca empresas em cascade — limpa todas as tabelas dependentes
        await conn.execute("TRUNCATE TABLE empresas RESTART IDENTITY CASCADE")
        # Tabelas independentes (sem FK para empresas)
        await conn.execute("TRUNCATE TABLE empresas_contabil RESTART IDENTITY CASCADE")
    except Exception as e:
        print(f"[conftest] Truncate ignorado: {e}")
    finally:
        await conn.close()


async def _create_empresa_usuario():
    from app.core.security import hash_password
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        empresa_id = await conn.fetchval(
            """INSERT INTO empresas (cnpj, nome, token, ativo)
               VALUES ($1, $2, $3, TRUE)
               ON CONFLICT (cnpj) DO UPDATE SET nome = EXCLUDED.nome
               RETURNING id""",
            "00000000000001", "Empresa Teste", "token-teste",
        )
        user_id = await conn.fetchval(
            """INSERT INTO usuarios (empresa_id, username, password_hash)
               VALUES ($1, $2, $3)
               ON CONFLICT (empresa_id, username) DO UPDATE
               SET password_hash = EXCLUDED.password_hash
               RETURNING id""",
            empresa_id, "testuser", hash_password("senha123"),
        )
        return {"empresa_id": empresa_id, "user_id": user_id,
                "username": "testuser", "password": "senha123"}
    finally:
        await conn.close()


# Executa setup de forma síncrona antes de qualquer fixture
_empresa_usuario_data: dict = {}

def pytest_configure(config):
    """Hook que roda ANTES de qualquer fixture — inicializa schema e empresa."""
    if not os.environ.get("TEST_DATABASE_URL") and \
       "postgresql://cristianoradin@localhost/zapdin_test" not in _TEST_DB_URL:
        return  # sem banco, skip silencioso
    try:
        asyncio.run(_init_schema())
        asyncio.run(_truncate_test_data())
        _empresa_usuario_data.update(asyncio.run(_create_empresa_usuario()))
    except Exception as e:
        print(f"\n[conftest] Setup falhou: {e}")


# ── Fixtures de empresa/usuário ───────────────────────────────────────────────

@pytest.fixture(scope="session")
def empresa_usuario():
    """Dados da empresa e usuário de teste (criados em pytest_configure)."""
    if not _empresa_usuario_data:
        pytest.skip("Banco de dados de teste não disponível")
    return _empresa_usuario_data


@pytest.fixture
def auth_cookie(empresa_usuario):
    """
    Cookie de sessão autenticado — function-scoped.
    Novo token por teste para evitar que test_logout_invalida_cookie
    corroa os testes seguintes (token na blacklist do banco).
    """
    from app.core.security import create_session_token, SESSION_COOKIE
    token = create_session_token(
        empresa_usuario["user_id"],
        empresa_usuario["username"],
        empresa_usuario["empresa_id"],
    )
    return {SESSION_COOKIE: token}


# ── Limpeza da blacklist de tokens antes de cada teste ───────────────────────

@pytest.fixture(autouse=True)
def clear_token_blacklist():
    """
    Limpa _invalidated_hashes antes de cada teste.
    Necessário porque URLSafeTimedSerializer é determinístico para o mesmo
    segundo — tokens gerados no mesmo segundo têm o mesmo valor, então
    um logout em um teste não pode vazar para o próximo.
    """
    from app.core import security as _sec_mod
    _sec_mod._invalidated_hashes.clear()
    yield
    # Limpa também após, para não contaminar testes seguintes
    _sec_mod._invalidated_hashes.clear()


# ── Conexão direta por teste (para seeds) ────────────────────────────────────

@pytest_asyncio.fixture
async def db_conn(empresa_usuario):
    """Conexão asyncpg direta para inserção de dados em testes individuais."""
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        yield conn
    finally:
        await conn.close()


# ── App com get_db sobrescrito ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def _patched_app(empresa_usuario):
    """
    FastAPI app com dependency override de get_db e monkey-patch de get_db_direct.
    Cada requisição cria sua própria conexão asyncpg — sem pool compartilhado
    entre event loops. Isso elimina o RuntimeError 'Future attached to different loop'.
    """
    from contextlib import asynccontextmanager
    import app.core.database as _db_module
    from app.main import fastapi_app

    # 1) Override da FastAPI dependency get_db
    async def _test_get_db():
        conn = await asyncpg.connect(_TEST_DB_URL)
        try:
            yield _db_module.AsyncPGAdapter(conn)
        finally:
            await conn.close()

    fastapi_app.dependency_overrides[_db_module.get_db] = _test_get_db

    # 2) Monkey-patch de get_db_direct em todos os módulos que o importaram
    #    no nível de módulo (não lazy dentro de função).
    from contextlib import asynccontextmanager as _acm

    @_acm
    async def _test_get_db_direct():
        conn = await asyncpg.connect(_TEST_DB_URL)
        try:
            yield _db_module.AsyncPGAdapter(conn)
        finally:
            await conn.close()

    # Módulos com import-level: avaliacao.py, main.py, ocr_service.py
    import app.routers.avaliacao as _avaliacao_mod
    import app.main as _main_mod

    _originals = {}
    for mod in (_db_module, _avaliacao_mod, _main_mod):
        if hasattr(mod, "get_db_direct"):
            _originals[mod] = mod.get_db_direct
            mod.get_db_direct = _test_get_db_direct

    # ocr_service pode não estar importado ainda
    try:
        import app.services.ocr_service as _ocr_mod
        _originals[_ocr_mod] = _ocr_mod.get_db_direct
        _ocr_mod.get_db_direct = _test_get_db_direct
    except Exception:
        pass

    yield fastapi_app

    fastapi_app.dependency_overrides.clear()
    for mod, orig in _originals.items():
        mod.get_db_direct = orig


# ── Clientes HTTP ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(_patched_app):
    """Cliente HTTP sem autenticação."""
    transport = ASGITransport(app=_patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client(_patched_app, auth_cookie):
    """Cliente HTTP com cookie de sessão autenticado."""
    transport = ASGITransport(app=_patched_app)
    async with AsyncClient(
        transport=transport, base_url="http://test", cookies=auth_cookie
    ) as ac:
        yield ac
