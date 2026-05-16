"""
app/repositories/avaliacao_repository.py — Acesso a dados de avaliações.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from .base import BaseRepository


class AvaliacaoRepository(BaseRepository):

    async def create(
        self,
        empresa_id: int,
        token: str,
        phone: str,
        nome_cliente: str,
        vendedor: str,
        valor: str,
    ) -> None:
        await self._execute_no_commit(
            "INSERT INTO avaliacoes (empresa_id, token, phone, nome_cliente, vendedor, valor) "
            "VALUES (?,?,?,?,?,?)",
            (empresa_id, token, phone, nome_cliente, vendedor, valor),
        )

    async def get_by_token(self, token: str):
        return await self._fetchone(
            "SELECT id, empresa_id, nome_cliente, vendedor, nota FROM avaliacoes WHERE token=?",
            (token,),
        )

    async def responder(self, token: str, nota: int, comentario: str) -> None:
        now = datetime.now(timezone.utc)
        await self._execute(
            "UPDATE avaliacoes SET nota=?, comentario=?, respondido_em=? WHERE token=?",
            (nota, comentario, now, token),
        )

    async def list(self, empresa_id: int, dias: int, vendedor: Optional[str] = None) -> list:
        if vendedor:
            return await self._fetchall(
                f"SELECT id, phone, nome_cliente, vendedor, nota, comentario, created_at, respondido_em "
                f"FROM avaliacoes WHERE empresa_id=? AND vendedor=? "
                f"AND created_at >= NOW() - INTERVAL '{dias} days' ORDER BY created_at DESC",
                (empresa_id, vendedor),
            )
        return await self._fetchall(
            f"SELECT id, phone, nome_cliente, vendedor, nota, comentario, created_at, respondido_em "
            f"FROM avaliacoes WHERE empresa_id=? "
            f"AND created_at >= NOW() - INTERVAL '{dias} days' ORDER BY created_at DESC",
            (empresa_id,),
        )

    async def dashboard_totais(self, empresa_id: int, dias: int):
        return await self._fetchone(
            f"SELECT COUNT(*) AS total_enviadas, COUNT(nota) AS total_respondidas, "
            f"ROUND(AVG(nota)::numeric, 2) AS media_geral, "
            f"COUNT(CASE WHEN nota >= 4 THEN 1 END) AS positivas, "
            f"COUNT(CASE WHEN nota <= 2 THEN 1 END) AS negativas "
            f"FROM avaliacoes WHERE empresa_id=? AND created_at >= NOW() - INTERVAL '{dias} days'",
            (empresa_id,),
        )

    async def dashboard_distribuicao(self, empresa_id: int, dias: int) -> dict:
        rows = await self._fetchall(
            f"SELECT nota, COUNT(*) AS qtd FROM avaliacoes "
            f"WHERE empresa_id=? AND nota IS NOT NULL "
            f"AND created_at >= NOW() - INTERVAL '{dias} days' GROUP BY nota ORDER BY nota",
            (empresa_id,),
        )
        return {int(r["nota"]): r["qtd"] for r in rows}

    async def dashboard_vendedores(self, empresa_id: int, dias: int) -> list:
        rows = await self._fetchall(
            f"SELECT vendedor, COUNT(*) AS total, COUNT(nota) AS respondidas, "
            f"ROUND(AVG(nota)::numeric,2) AS media FROM avaliacoes "
            f"WHERE empresa_id=? AND vendedor != '' "
            f"AND created_at >= NOW() - INTERVAL '{dias} days' "
            f"GROUP BY vendedor ORDER BY media DESC NULLS LAST",
            (empresa_id,),
        )
        return [
            {
                "vendedor": r["vendedor"],
                "total": r["total"],
                "respondidas": r["respondidas"],
                "media": float(r["media"]) if r["media"] else None,
            }
            for r in rows
        ]

    async def dashboard_baixas(self, empresa_id: int, dias: int) -> list:
        rows = await self._fetchall(
            f"SELECT phone, nome_cliente, vendedor, nota, respondido_em FROM avaliacoes "
            f"WHERE empresa_id=? AND nota <= 2 AND nota IS NOT NULL "
            f"AND created_at >= NOW() - INTERVAL '{dias} days' "
            f"ORDER BY respondido_em DESC LIMIT 10",
            (empresa_id,),
        )
        return [
            {
                "nome": r["nome_cliente"] or "—",
                "telefone": r["phone"] or "",
                "vendedor": r["vendedor"] or "",
                "nota": r["nota"],
                "data": r["respondido_em"].strftime("%d/%m/%Y") if r["respondido_em"] else "—",
            }
            for r in rows
        ]
