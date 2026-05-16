"""
app/repositories/campanha_repository.py — Acesso a dados de campanhas e envios.
"""
from __future__ import annotations
from typing import Optional
from .base import BaseRepository


class CampanhaRepository(BaseRepository):

    # ── Campanhas ─────────────────────────────────────────────────────────────

    async def list(self, empresa_id: int, status: Optional[str] = None) -> list:
        if status:
            return await self._fetchall(
                "SELECT id, nome, tipo, mensagem, status, total, enviados, erros, "
                "created_at, started_at, done_at, agendado_em "
                "FROM campanhas WHERE empresa_id=? AND status=? ORDER BY id DESC",
                (empresa_id, status),
            )
        return await self._fetchall(
            "SELECT id, nome, tipo, mensagem, status, total, enviados, erros, "
            "created_at, started_at, done_at, agendado_em "
            "FROM campanhas WHERE empresa_id=? ORDER BY id DESC",
            (empresa_id,),
        )

    async def get(self, empresa_id: int, campanha_id: int):
        return await self._fetchone(
            "SELECT id, tipo, mensagem, status, total, enviados, erros "
            "FROM campanhas WHERE id=? AND empresa_id=?",
            (campanha_id, empresa_id),
        )

    async def create(
        self,
        empresa_id: int,
        nome: str,
        tipo: str,
        mensagem: str,
        status: str = "draft",
        agendado_em=None,
    ) -> int:
        cur = await self._execute(
            "INSERT INTO campanhas (empresa_id, nome, tipo, mensagem, status, agendado_em) "
            "VALUES (?,?,?,?,?,?)",
            (empresa_id, nome, tipo, mensagem, status, agendado_em),
        )
        return cur.lastrowid

    async def update_status(self, campanha_id: int, status: str) -> None:
        await self._execute(
            "UPDATE campanhas SET status=? WHERE id=?",
            (status, campanha_id),
        )

    async def iniciar(self, campanha_id: int, total: int) -> None:
        await self._execute(
            "UPDATE campanhas SET status='running', total=?, enviados=0, erros=0, started_at=NOW() WHERE id=?",
            (total, campanha_id),
        )

    async def delete(self, empresa_id: int, campanha_id: int) -> None:
        await self._execute(
            "DELETE FROM campanhas WHERE id=? AND empresa_id=?",
            (campanha_id, empresa_id),
        )

    async def progresso(self, empresa_id: int, campanha_id: int):
        return await self._fetchone(
            "SELECT status, total, enviados, erros FROM campanhas WHERE id=? AND empresa_id=?",
            (campanha_id, empresa_id),
        )

    # ── Envios ────────────────────────────────────────────────────────────────

    async def delete_envios(self, campanha_id: int) -> None:
        await self._execute_no_commit(
            "DELETE FROM campanha_envios WHERE campanha_id=?",
            (campanha_id,),
        )

    async def create_envios_batch(self, campanha_id: int, empresa_id: int, contatos: list) -> None:
        await self._db.executemany(
            "INSERT INTO campanha_envios (campanha_id, empresa_id, phone, nome, status) VALUES (?,?,?,?,?)",
            [(campanha_id, empresa_id, c["phone"], c["nome"] or "", "queued") for c in contatos],
        )

    async def retomar_envios_pausados(self, campanha_id: int) -> None:
        await self._execute(
            "UPDATE campanha_envios SET status='queued' WHERE campanha_id=? AND status='paused'",
            (campanha_id,),
        )

    async def pausar_envios(self, campanha_id: int) -> None:
        await self._execute(
            "UPDATE campanha_envios SET status='paused' WHERE campanha_id=? AND status='queued'",
            (campanha_id,),
        )

    async def count_envios_by_status(self, empresa_id: int, campanha_id: Optional[int] = None) -> dict:
        if campanha_id:
            rows = await self._fetchall(
                "SELECT status, COUNT(*) as cnt FROM campanha_envios "
                "WHERE empresa_id=? AND campanha_id=? GROUP BY status",
                (empresa_id, campanha_id),
            )
        else:
            rows = await self._fetchall(
                "SELECT status, COUNT(*) as cnt FROM campanha_envios "
                "WHERE empresa_id=? GROUP BY status",
                (empresa_id,),
            )
        return {r["status"]: r["cnt"] for r in rows}

    # ── Arquivos de campanha ──────────────────────────────────────────────────

    async def list_arquivos(self, empresa_id: int, campanha_id: int) -> list:
        return await self._fetchall(
            "SELECT ca.id, ca.nome_original, ca.nome_arquivo "
            "FROM campanha_arquivos ca "
            "JOIN campanhas c ON c.id=ca.campanha_id "
            "WHERE ca.campanha_id=? AND c.empresa_id=?",
            (campanha_id, empresa_id),
        )

    async def add_arquivo(self, campanha_id: int, nome_original: str, nome_arquivo: str) -> None:
        await self._execute(
            "INSERT INTO campanha_arquivos (campanha_id, nome_original, nome_arquivo) VALUES (?,?,?)",
            (campanha_id, nome_original, nome_arquivo),
        )

    async def get_arquivo(self, empresa_id: int, campanha_id: int, arq_id: int):
        return await self._fetchone(
            "SELECT ca.nome_arquivo FROM campanha_arquivos ca "
            "JOIN campanhas c ON c.id=ca.campanha_id "
            "WHERE ca.id=? AND ca.campanha_id=? AND c.empresa_id=?",
            (arq_id, campanha_id, empresa_id),
        )

    async def delete_arquivo(self, arq_id: int) -> None:
        await self._execute(
            "DELETE FROM campanha_arquivos WHERE id=?", (arq_id,)
        )

    async def delete_todos_arquivos(self, campanha_id: int) -> list:
        """Retorna nomes dos arquivos antes de deletar (para remoção do disco)."""
        rows = await self._fetchall(
            "SELECT nome_arquivo FROM campanha_arquivos WHERE campanha_id=?",
            (campanha_id,),
        )
        await self._execute_no_commit(
            "DELETE FROM campanha_arquivos WHERE campanha_id=?", (campanha_id,)
        )
        return [r["nome_arquivo"] for r in rows]

    # ── Dashboard ─────────────────────────────────────────────────────────────

    async def dashboard_por_hora(self, empresa_id: int, campanha_id: Optional[int] = None) -> list:
        if campanha_id:
            rows = await self._fetchall(
                "SELECT EXTRACT(HOUR FROM sent_at)::int as hora, COUNT(*) as cnt "
                "FROM campanha_envios WHERE empresa_id=? AND campanha_id=? AND sent_at IS NOT NULL "
                "GROUP BY hora ORDER BY hora",
                (empresa_id, campanha_id),
            )
        else:
            rows = await self._fetchall(
                "SELECT EXTRACT(HOUR FROM sent_at)::int as hora, COUNT(*) as cnt "
                "FROM campanha_envios WHERE empresa_id=? AND sent_at IS NOT NULL "
                "GROUP BY hora ORDER BY hora",
                (empresa_id,),
            )
        hora_map = {r["hora"]: r["cnt"] for r in rows}
        return [{"hora": h, "enviados": hora_map.get(h, 0)} for h in range(24)]

    async def dashboard_por_dia(self, empresa_id: int, dias: int, campanha_id: Optional[int] = None) -> list:
        if campanha_id:
            rows = await self._fetchall(
                f"SELECT DATE(sent_at) as dia, COUNT(*) as cnt "
                f"FROM campanha_envios WHERE empresa_id=? AND campanha_id=? "
                f"AND sent_at IS NOT NULL AND sent_at >= NOW() - INTERVAL '{dias} days' "
                f"GROUP BY dia ORDER BY dia",
                (empresa_id, campanha_id),
            )
        else:
            rows = await self._fetchall(
                f"SELECT DATE(sent_at) as dia, COUNT(*) as cnt "
                f"FROM campanha_envios WHERE empresa_id=? "
                f"AND sent_at IS NOT NULL AND sent_at >= NOW() - INTERVAL '{dias} days' "
                f"GROUP BY dia ORDER BY dia",
                (empresa_id,),
            )
        return [{"dia": str(r["dia"]), "enviados": r["cnt"]} for r in rows]

    async def dashboard_top_contatos(self, empresa_id: int, campanha_id: Optional[int] = None) -> list:
        if campanha_id:
            rows = await self._fetchall(
                "SELECT ce.phone, ce.nome, "
                "COUNT(DISTINCT ce.campanha_id) as total_campanhas, "
                "SUM(CASE WHEN ce.status='sent' THEN 1 ELSE 0 END) as enviados, "
                "SUM(CASE WHEN ce.status='failed' THEN 1 ELSE 0 END) as falhas "
                "FROM campanha_envios ce "
                "WHERE ce.empresa_id=? AND ce.campanha_id=? "
                "GROUP BY ce.phone, ce.nome ORDER BY enviados DESC LIMIT 10",
                (empresa_id, campanha_id),
            )
        else:
            rows = await self._fetchall(
                "SELECT ce.phone, ce.nome, "
                "COUNT(DISTINCT ce.campanha_id) as total_campanhas, "
                "SUM(CASE WHEN ce.status='sent' THEN 1 ELSE 0 END) as enviados, "
                "SUM(CASE WHEN ce.status='failed' THEN 1 ELSE 0 END) as falhas "
                "FROM campanha_envios ce WHERE ce.empresa_id=? "
                "GROUP BY ce.phone, ce.nome ORDER BY enviados DESC LIMIT 10",
                (empresa_id,),
            )
        return [dict(r) for r in rows]

    async def dashboard_campanhas(self, empresa_id: int, campanha_id: Optional[int] = None) -> list:
        if campanha_id:
            rows = await self._fetchall(
                "SELECT c.id, c.nome, c.status, c.total, c.enviados, c.erros, "
                "c.created_at, c.started_at, c.done_at, "
                "ROUND(EXTRACT(EPOCH FROM (COALESCE(c.done_at, NOW()) - c.started_at))/60)::int AS duracao_min, "
                "CASE WHEN c.total > 0 THEN ROUND(c.enviados::numeric / c.total * 100, 1) ELSE 0 END AS taxa_sucesso "
                "FROM campanhas c WHERE c.empresa_id=? AND c.id=? ORDER BY c.id DESC LIMIT 20",
                (empresa_id, campanha_id),
            )
        else:
            rows = await self._fetchall(
                "SELECT c.id, c.nome, c.status, c.total, c.enviados, c.erros, "
                "c.created_at, c.started_at, c.done_at, "
                "ROUND(EXTRACT(EPOCH FROM (COALESCE(c.done_at, NOW()) - c.started_at))/60)::int AS duracao_min, "
                "CASE WHEN c.total > 0 THEN ROUND(c.enviados::numeric / c.total * 100, 1) ELSE 0 END AS taxa_sucesso "
                "FROM campanhas c WHERE c.empresa_id=? ORDER BY c.id DESC LIMIT 20",
                (empresa_id,),
            )
        result = []
        for r in rows:
            d = dict(r)
            for k in ("created_at", "started_at", "done_at"):
                if d.get(k):
                    d[k] = d[k].isoformat()
            d["duracao_min"] = int(d["duracao_min"]) if d.get("duracao_min") is not None else None
            d["taxa_sucesso"] = float(d["taxa_sucesso"]) if d.get("taxa_sucesso") is not None else 0.0
            result.append(d)
        return result

    async def contatos_unicos(self, empresa_id: int, campanha_id: Optional[int] = None) -> int:
        if campanha_id:
            row = await self._fetchone(
                "SELECT COUNT(DISTINCT phone) as cnt FROM campanha_envios "
                "WHERE empresa_id=? AND campanha_id=?",
                (empresa_id, campanha_id),
            )
        else:
            row = await self._fetchone(
                "SELECT COUNT(DISTINCT phone) as cnt FROM campanha_envios WHERE empresa_id=?",
                (empresa_id,),
            )
        return row["cnt"] if row else 0
