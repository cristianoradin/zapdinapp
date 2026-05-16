"""
app/repositories/config_repository.py — Acesso a configurações por empresa.

Centraliza toda leitura/escrita da tabela `config`.
"""
from __future__ import annotations
from typing import Optional
from .base import BaseRepository


class ConfigRepository(BaseRepository):

    async def get(self, empresa_id: int, key: str) -> Optional[str]:
        row = await self._fetchone(
            "SELECT value FROM config WHERE key=? AND empresa_id=?",
            (key, empresa_id),
        )
        return row["value"] if row else None

    async def set(self, empresa_id: int, key: str, value: str) -> None:
        await self._execute(
            "INSERT INTO config (empresa_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (empresa_id, key) DO UPDATE SET value=EXCLUDED.value",
            (empresa_id, key, value),
        )

    async def get_many(self, empresa_id: int, keys: list[str]) -> dict[str, str]:
        """Busca múltiplas chaves em uma só query."""
        placeholders = ",".join("?" * len(keys))
        rows = await self._fetchall(
            f"SELECT key, value FROM config WHERE empresa_id=? AND key IN ({placeholders})",
            (empresa_id, *keys),
        )
        return {r["key"]: r["value"] for r in rows}

    async def get_all(self, empresa_id: int) -> dict[str, str]:
        rows = await self._fetchall(
            "SELECT key, value FROM config WHERE empresa_id=?",
            (empresa_id,),
        )
        return {r["key"]: r["value"] for r in rows}

    async def delete(self, empresa_id: int, key: str) -> None:
        await self._execute(
            "DELETE FROM config WHERE empresa_id=? AND key=?",
            (empresa_id, key),
        )

    # ── Helpers semânticos ────────────────────────────────────────────────────

    async def get_mensagem_padrao(self, empresa_id: int) -> str:
        val = await self.get(empresa_id, "mensagem_padrao")
        return val or "Olá {nome}, obrigado pela sua compra de {valor_total} em {data}!"

    async def get_erp_token(self, empresa_id: int) -> Optional[str]:
        return await self.get(empresa_id, "erp_token")

    async def set_erp_token(self, empresa_id: int, token_hash: str) -> None:
        await self.set(empresa_id, "erp_token", token_hash)

    async def is_avaliacao_ativa(self, empresa_id: int) -> bool:
        val = await self.get(empresa_id, "avaliacao_ativa")
        return val == "1"

    async def get_avaliacao_url_base(self, empresa_id: int, fallback: str) -> str:
        val = await self.get(empresa_id, "avaliacao_url_base")
        return val or fallback

    async def get_all_erp_tokens(self) -> list:
        """Retorna todos os tokens ERP com empresa_id (para autenticação)."""
        return await self._fetchall(
            "SELECT empresa_id, value FROM config WHERE key='erp_token'",
            (),
        )
