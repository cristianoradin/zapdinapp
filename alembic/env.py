"""
alembic/env.py — ZapDin migrations.
Lê DATABASE_URL do ambiente ou app/.env.
Uso:
  app/.venv/bin/alembic upgrade head
  app/.venv/bin/alembic revision -m "descricao"
  app/.venv/bin/alembic history
  app/.venv/bin/alembic current
"""
from __future__ import annotations
import asyncio, os
from logging.config import fileConfig
from pathlib import Path
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

def _load_db_url() -> str:
    if url := os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL"):
        return url
    env_path = Path(__file__).parent.parent / "app" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("DATABASE_URL não encontrada. Defina no ambiente ou app/.env.")

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

_url = _load_db_url()
_url_async = _url.replace("postgresql://", "postgresql+asyncpg://", 1) \
    if "postgresql://" in _url and "+asyncpg" not in _url else _url

target_metadata = None  # sem ORM models — SQL puro via init_db()

def run_migrations_offline():
    context.configure(url=_url, target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(conn: Connection):
    context.configure(connection=conn, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations():
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _url_async
    engine = async_engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()

def run_migrations_online():
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
