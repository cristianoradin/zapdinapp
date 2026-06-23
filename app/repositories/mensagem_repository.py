"""
app/repositories/mensagem_repository.py — Acesso a dados de mensagens.

Centraliza todas as queries da tabela `mensagens`.
"""
from __future__ import annotations
from typing import Optional
from .base import BaseRepository


class MensagemRepository(BaseRepository):

    async def enqueue(
        self,
        empresa_id: int,
        destinatario: str,
        nome_destinatario: str,
        mensagem: str,
        tipo: str = "text",
    ) -> int:
        """Insere mensagem na fila. Retorna o id gerado."""
        cur = await self._execute_no_commit(
            "INSERT INTO mensagens "
            "(empresa_id, destinatario, nome_destinatario, mensagem, tipo, status) "
            "VALUES (?, ?, ?, ?, ?, 'queued')",
            (empresa_id, destinatario, nome_destinatario, mensagem, tipo),
        )
        return cur.lastrowid

    async def list_recent(self, empresa_id: int, limit: int = 50) -> list:
        return await self._fetchall(
            "SELECT id, destinatario, nome_destinatario, mensagem, tipo, status, "
            "created_at, sent_at, delivered_at, read_at, erro "
            "FROM mensagens WHERE empresa_id=? ORDER BY id DESC LIMIT ?",
            (empresa_id, limit),
        )

    async def requeue(self, empresa_id: int, msg_id: int) -> bool:
        """Reenfileira UMA mensagem falhada (failed/error) da empresa → status=queued.
        Worker reenvia. Retorna True se reenfileirou (era falha da própria empresa)."""
        await self._execute(
            "UPDATE mensagens SET status='queued', erro=NULL, sent_at=NULL "
            "WHERE id=? AND empresa_id=? AND status IN ('failed','error')",
            (msg_id, empresa_id),
        )
        row = await self._fetchone(
            "SELECT status FROM mensagens WHERE id=? AND empresa_id=?",
            (msg_id, empresa_id),
        )
        return bool(row and row["status"] == "queued")

    async def count_by_status(self, empresa_id: int) -> dict:
        rows = await self._fetchall(
            "SELECT status, COUNT(*) as cnt FROM mensagens WHERE empresa_id=? GROUP BY status",
            (empresa_id,),
        )
        return {r["status"]: r["cnt"] for r in rows}

    async def count_today(self, empresa_id: int) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) as cnt FROM mensagens "
            "WHERE empresa_id=? AND DATE(created_at) = CURRENT_DATE",
            (empresa_id,),
        )
        return row["cnt"] if row else 0

    async def count_total_sent(self, empresa_id: int) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) as cnt FROM mensagens WHERE empresa_id=? AND status='sent'",
            (empresa_id,),
        )
        return row["cnt"] if row else 0

    async def count_errors(self, empresa_id: int) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) as cnt FROM mensagens WHERE empresa_id=? AND status='error'",
            (empresa_id,),
        )
        return row["cnt"] if row else 0
