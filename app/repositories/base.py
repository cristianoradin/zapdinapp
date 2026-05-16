"""
app/repositories/base.py — Classe base para todos os repositórios.

Recebe o adapter de banco (AsyncPGAdapter) e expõe helpers comuns.
Isso evita repetição de padrão execute/fetchone/fetchall em cada repositório.
"""
from __future__ import annotations
from typing import Any, Optional


class BaseRepository:
    def __init__(self, db) -> None:
        self._db = db

    async def _fetchone(self, sql: str, params: tuple = ()) -> Optional[Any]:
        async with self._db.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _fetchall(self, sql: str, params: tuple = ()) -> list:
        async with self._db.execute(sql, params) as cur:
            return await cur.fetchall()

    async def _execute(self, sql: str, params: tuple = ()) -> Any:
        cur = await self._db.execute(sql, params)
        await self._db.commit()
        return cur

    async def _execute_no_commit(self, sql: str, params: tuple = ()) -> Any:
        """Execute sem commit — útil quando múltiplas operações formam uma unidade."""
        return await self._db.execute(sql, params)

    async def _executemany(self, sql: str, params_list: list) -> None:
        await self._db.executemany(sql, params_list)
        await self._db.commit()
