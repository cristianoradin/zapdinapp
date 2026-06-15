"""
app/core/migrations_runner.py — Runner de migrations SQL numeradas.

Convenção:
  app/migrations/001_descricao.sql
  app/migrations/002_outra_coisa.sql

Cada arquivo roda UMA vez, em ordem alfabética, dentro de uma transação.
Tracking na tabela `schema_migrations` (name UNIQUE). Re-deploy não re-aplica.

Para criar uma migration:
  1. Crie app/migrations/NNN_descricao.sql (NNN = próximo número de 3 dígitos)
  2. Escreva SQL idempotente sempre que possível (IF NOT EXISTS)
  3. Deploy — init_db() aplica automaticamente no startup
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


async def run_migrations(conn) -> int:
    """Aplica migrations pendentes. Retorna quantas foram aplicadas.

    Usa a tabela schema_migrations existente (version TEXT PK, descricao TEXT)
    — mesma onde o baseline registra 001_initial..011_system_logs.
    Migrations em arquivo começam em 100_ para não colidir com o histórico.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ DEFAULT NOW(),
            descricao  TEXT
        )
    """)

    if not MIGRATIONS_DIR.exists():
        return 0

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        return 0

    applied_rows = await conn.fetch("SELECT version FROM schema_migrations")
    applied = {r["version"] for r in applied_rows}

    count = 0
    for f in files:
        version = f.stem  # ex: '100_add_coluna_x'
        if version in applied:
            continue
        sql = f.read_text(encoding="utf-8").strip()
        if not sql:
            continue
        logger.info("[migrations] aplicando %s ...", f.name)
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version, descricao) VALUES ($1, $2)",
                version, f"arquivo app/migrations/{f.name}",
            )
        logger.info("[migrations] %s aplicada ✓", f.name)
        count += 1

    if count:
        logger.info("[migrations] %d migration(s) aplicada(s)", count)
    return count
