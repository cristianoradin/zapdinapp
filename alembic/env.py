"""
alembic/env.py — ZapDin migrations com autogenerate via SQLAlchemy models.

Uso:
  app/.venv/bin/alembic upgrade head
  app/.venv/bin/alembic revision --autogenerate -m "add coluna x"
  app/.venv/bin/alembic history
  app/.venv/bin/alembic current
  app/.venv/bin/alembic downgrade -1
"""
from __future__ import annotations
import asyncio, os
from logging.config import fileConfig
from pathlib import Path
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# ── Importa metadata dos models (habilita autogenerate) ──────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.core.models import metadata as target_metadata  # noqa: E402

# ── DATABASE_URL ──────────────────────────────────────────────────────────────
def _load_db_url() -> str:
    if url := os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL"):
        return url
    env_path = Path(__file__).parent.parent / "app" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("DATABASE_URL não encontrada.")

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

_url = _load_db_url()
_url_async = _url.replace("postgresql://", "postgresql+asyncpg://", 1) \
    if "postgresql://" in _url and "+asyncpg" not in _url else _url

# ── Offline ───────────────────────────────────────────────────────────────────
def run_migrations_offline():
    context.configure(
        url=_url, target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
        compare_type=True, compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()

# ── Online (asyncpg) ──────────────────────────────────────────────────────────
def do_run_migrations(conn: Connection):
    context.configure(
        connection=conn, target_metadata=target_metadata,
        compare_type=True, compare_server_default=True,
    )
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
