"""
app/repositories/contato_repository.py — Acesso a dados de contatos e grupos.
"""
from __future__ import annotations
from typing import Optional
from .base import BaseRepository


class ContatoRepository(BaseRepository):

    # ── Contatos ─────────────────────────────────────────────────────────────

    async def list(self, empresa_id: int, q: str = "") -> list:
        if q:
            return await self._fetchall(
                "SELECT id, phone, nome, ativo, COALESCE(origem,'manual') AS origem "
                "FROM contatos WHERE empresa_id=? AND (phone ILIKE ? OR nome ILIKE ?) ORDER BY nome",
                (empresa_id, f"%{q}%", f"%{q}%"),
            )
        return await self._fetchall(
            "SELECT id, phone, nome, ativo, COALESCE(origem,'manual') AS origem "
            "FROM contatos WHERE empresa_id=? ORDER BY nome",
            (empresa_id,),
        )

    async def upsert(self, empresa_id: int, phone: str, nome: str, origem: str = "manual") -> Optional[int]:
        cur = await self._execute_no_commit(
            "INSERT INTO contatos (empresa_id, phone, nome, origem) VALUES (?,?,?,?) "
            "ON CONFLICT (empresa_id, phone) DO UPDATE "
            "SET nome = CASE WHEN EXCLUDED.nome != '' THEN EXCLUDED.nome ELSE contatos.nome END, "
            "    origem = EXCLUDED.origem",
            (empresa_id, phone, nome, origem),
        )
        return cur.lastrowid

    async def upsert_batch(self, registros: list[tuple]) -> None:
        """Insere/atualiza múltiplos contatos em batch. Cada tuple: (empresa_id, phone, nome)."""
        await self._db.executemany(
            "INSERT INTO contatos (empresa_id, phone, nome) VALUES (?,?,?) "
            "ON CONFLICT (empresa_id, phone) DO UPDATE SET nome=EXCLUDED.nome",
            registros,
        )

    async def delete(self, empresa_id: int, contato_id: int) -> None:
        await self._execute(
            "DELETE FROM contatos WHERE id=? AND empresa_id=?",
            (contato_id, empresa_id),
        )

    async def list_ativos(self, empresa_id: int) -> list:
        return await self._fetchall(
            "SELECT phone, nome FROM contatos WHERE empresa_id=? AND ativo=TRUE ORDER BY nome",
            (empresa_id,),
        )

    async def list_by_ids(self, empresa_id: int, ids: list[int]) -> list:
        placeholders = ",".join("?" * len(ids))
        return await self._fetchall(
            f"SELECT phone, nome FROM contatos WHERE empresa_id=? AND ativo=TRUE AND id IN ({placeholders})",
            (empresa_id, *ids),
        )

    # ── Grupos ────────────────────────────────────────────────────────────────

    async def list_grupos(self, empresa_id: int) -> list:
        return await self._fetchall(
            "SELECT g.id, g.nome, g.created_at, COUNT(gc.contato_id) AS total "
            "FROM grupos_contatos g "
            "LEFT JOIN grupo_contatos gc ON gc.grupo_id = g.id "
            "WHERE g.empresa_id=? GROUP BY g.id, g.nome, g.created_at ORDER BY g.nome",
            (empresa_id,),
        )

    async def create_grupo(self, empresa_id: int, nome: str) -> int:
        cur = await self._execute(
            "INSERT INTO grupos_contatos (empresa_id, nome) VALUES (?,?)",
            (empresa_id, nome),
        )
        return cur.lastrowid

    async def update_grupo(self, empresa_id: int, grupo_id: int, nome: str) -> None:
        await self._execute(
            "UPDATE grupos_contatos SET nome=? WHERE id=? AND empresa_id=?",
            (nome, grupo_id, empresa_id),
        )

    async def delete_grupo(self, empresa_id: int, grupo_id: int) -> None:
        await self._execute(
            "DELETE FROM grupos_contatos WHERE id=? AND empresa_id=?",
            (grupo_id, empresa_id),
        )

    async def get_grupo(self, empresa_id: int, grupo_id: int):
        return await self._fetchone(
            "SELECT id FROM grupos_contatos WHERE id=? AND empresa_id=?",
            (grupo_id, empresa_id),
        )

    async def list_grupo_contatos(self, empresa_id: int, grupo_id: int) -> list:
        return await self._fetchall(
            "SELECT c.id, c.phone, c.nome, c.ativo "
            "FROM contatos c "
            "JOIN grupo_contatos gc ON gc.contato_id = c.id "
            "WHERE gc.grupo_id=? AND c.empresa_id=? ORDER BY c.nome",
            (grupo_id, empresa_id),
        )

    async def list_grupo_contatos_ativos(self, grupo_id: int, empresa_id: int) -> list:
        return await self._fetchall(
            "SELECT c.phone, c.nome FROM contatos c "
            "JOIN grupo_contatos gc ON gc.contato_id = c.id "
            "WHERE gc.grupo_id=? AND c.empresa_id=? AND c.ativo=TRUE ORDER BY c.nome",
            (grupo_id, empresa_id),
        )

    async def add_contatos_ao_grupo(self, grupo_id: int, contato_ids: list[int]) -> int:
        added = 0
        for cid in contato_ids:
            try:
                await self._execute_no_commit(
                    "INSERT INTO grupo_contatos (grupo_id, contato_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                    (grupo_id, cid),
                )
                added += 1
            except Exception:
                pass
        await self._db.commit()
        return added

    async def remove_contato_do_grupo(self, empresa_id: int, grupo_id: int, contato_id: int) -> None:
        await self._execute(
            "DELETE FROM grupo_contatos WHERE grupo_id=? AND contato_id=? "
            "AND grupo_id IN (SELECT id FROM grupos_contatos WHERE empresa_id=?)",
            (grupo_id, contato_id, empresa_id),
        )
