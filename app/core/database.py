"""
app/core/database.py — PostgreSQL multi-tenant via asyncpg.

Cada empresa (CNPJ ativado) tem um registro em `empresas`.
Todos os dados (usuarios, config, sessoes_wa, mensagens, arquivos)
são isolados por empresa_id.
"""
from __future__ import annotations

import logging
import asyncpg
from contextlib import asynccontextmanager
from functools import lru_cache
from .config import settings

logger = logging.getLogger(__name__)

# ── Pool global ───────────────────────────────────────────────────────────────
_pool: asyncpg.Pool | None = None


@lru_cache(maxsize=512)
def _to_pg(sql: str) -> str:
    """Converte placeholders SQLite '?' → '$1', '$2', ... do PostgreSQL.
    Resultado cacheado — a maioria das queries são strings literais repetidas.

    Ignora '?' dentro de strings SQL (entre aspas simples ou duplas),
    evitando substituição incorreta em padrões como WHERE x = '?'.
    """
    n, out = 0, []
    in_single = False  # dentro de '...'
    in_double = False  # dentro de "..."
    i = 0
    while i < len(sql):
        ch = sql[i]
        # Aspas duplas escapadas ('')  dentro de string simples
        if in_single and ch == "'" and i + 1 < len(sql) and sql[i + 1] == "'":
            out.append("''")
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == '?' and not in_single and not in_double:
            n += 1
            out.append(f'${n}')
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


# ── Cursor proxy ──────────────────────────────────────────────────────────────

class _Cursor:
    __slots__ = ('lastrowid', '_rows')

    def __init__(self, rows=None, lastrowid: int | None = None):
        self.lastrowid = lastrowid
        self._rows: list = rows if rows is not None else []

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return self._rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


class _ExecProxy:
    __slots__ = ('_coro',)

    def __init__(self, coro):
        self._coro = coro

    def __await__(self):
        return self._coro.__await__()

    async def __aenter__(self):
        return await self._coro

    async def __aexit__(self, *_):
        pass


# ── Adapter principal ─────────────────────────────────────────────────────────

class AsyncPGAdapter:
    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    def execute(self, sql: str, params: tuple = ()) -> _ExecProxy:
        return _ExecProxy(self._run(sql, params))

    async def _run(self, sql: str, params: tuple) -> _Cursor:
        pg = _to_pg(sql)
        args = list(params)
        # Remove comentários de linha do início para detectar o tipo
        head = pg.lstrip().upper()
        # Ignora prefixo EXPLAIN / EXPLAIN ANALYZE
        if head.startswith('EXPLAIN'):
            rows = await self._conn.fetch(pg, *args)
            return _Cursor(rows=rows)

        if head.startswith('SELECT') or head.startswith('WITH'):
            rows = await self._conn.fetch(pg, *args)
            return _Cursor(rows=rows)

        if head.startswith('INSERT') and 'RETURNING' in head:
            # INSERT com RETURNING explícito — captura o valor retornado (1ª coluna)
            row = await self._conn.fetchrow(pg, *args)
            lr = None
            if row is not None:
                lr = row['id'] if 'id' in row.keys() else row[0]
            return _Cursor(lastrowid=lr)

        if head.startswith('INSERT') and 'RETURNING' not in head:
            pg_ret = pg.rstrip().rstrip(';') + ' RETURNING id'
            try:
                row = await self._conn.fetchrow(pg_ret, *args)
                return _Cursor(lastrowid=row['id'] if row else None)
            except (asyncpg.UndefinedColumnError, asyncpg.PostgresSyntaxError,
                    asyncpg.UndefinedFunctionError, asyncpg.InvalidColumnReferenceError) as _e:
                # Tabela sem coluna 'id' — executa sem RETURNING
                logger.debug("[db] INSERT sem RETURNING id (%s) — %s", type(_e).__name__, pg[:80])
                await self._conn.execute(pg, *args)
                return _Cursor()

        await self._conn.execute(pg, *args)
        return _Cursor()

    async def commit(self) -> None:
        """No-op: asyncpg usa autocommit fora de transações explícitas.
        Dentro de `async with db.transaction()`, o commit ocorre no __aexit__."""

    async def rollback(self) -> None:
        """No-op fora de transação explícita."""

    def transaction(self):
        """Retorna context manager de transação asyncpg.
        Uso:
            async with db.transaction():
                await db.execute(...)
                await db.execute(...)
        """
        return self._conn.transaction()

    async def executemany(self, sql: str, params_list):
        pg = _to_pg(sql)
        # asyncpg espera lista de listas/tuplas
        await self._conn.executemany(pg, [list(p) for p in params_list])

    async def executescript(self, script: str):
        for stmt in script.split(';'):
            s = stmt.strip()
            if s:
                await self._conn.execute(s)

    def __getattr__(self, name: str):
        """Delega ao asyncpg.Connection — permite fetchrow, fetchval, fetch nativos."""
        return getattr(self._conn, name)


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_db():
    async with _pool.acquire() as conn:
        yield AsyncPGAdapter(conn)


@asynccontextmanager
async def get_db_direct():
    async with _pool.acquire() as conn:
        yield AsyncPGAdapter(conn)


# ── Inicialização multi-tenant ────────────────────────────────────────────────

async def init_db() -> None:
    global _pool
    # Oculta senha na URL para o log
    _db_url_log = settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url
    logger.info("[db] Conectando ao PostgreSQL: %s", _db_url_log)
    try:
        _pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
    except Exception as exc:
        logger.error("[db] FALHA ao conectar ao PostgreSQL (%s): %s", _db_url_log, exc)
        raise
    logger.info("[db] Pool PostgreSQL criado (min=2 max=10)")

    from .schema_baseline import apply_baseline
    from .migrations_runner import run_migrations

    async with _pool.acquire() as conn:
        # 1) Schema congelado (idempotente) — NÃO adicionar DDL novo lá.
        await apply_baseline(conn)
        # 2) Migrations numeradas em app/migrations/*.sql (tracking em schema_migrations)
        await run_migrations(conn)

    logger.info("[db] Schema inicializado — baseline + migrations ok")
