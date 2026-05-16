"""
app/services/campanha_service.py — Casos de uso de campanhas.

Lógica de negócio: iniciar, pausar, retomar, calcular progresso.
O router apenas delega para este service.
"""
from __future__ import annotations
import logging
from typing import Optional

from ..repositories import CampanhaRepository
from ..repositories.contato_repository import ContatoRepository
from ..domain.exceptions import CampanhaNaoEncontrada, SemContatosParaDisparar

logger = logging.getLogger(__name__)

# Status que permitem (re)iniciar uma campanha
_REINICIAVEL = {"draft", "done", "scheduled"}
# Status que permitem retomar
_RETOMAVEL   = {"paused"}


async def iniciar_campanha(
    db,
    empresa_id: int,
    campanha_id: int,
    contato_ids: Optional[list[int]] = None,
    grupo_id: Optional[int] = None,
) -> dict:
    """
    Inicia ou retoma uma campanha.

    Regras de negócio:
    - running → erro (já em execução)
    - draft/done/scheduled → recria envios e inicia
    - paused → retoma envios pausados sem recriar
    """
    camp_repo    = CampanhaRepository(db)
    contato_repo = ContatoRepository(db)

    camp = await camp_repo.get(empresa_id, campanha_id)
    if not camp:
        raise CampanhaNaoEncontrada(f"Campanha {campanha_id} não encontrada")

    if camp["status"] == "running":
        raise ValueError("Campanha já em execução")

    if camp["status"] in _REINICIAVEL:
        # Remove envios anteriores e recria
        await camp_repo.delete_envios(campanha_id)

        if grupo_id:
            contatos = await contato_repo.list_grupo_contatos_ativos(grupo_id, empresa_id)
        elif contato_ids:
            contatos = await contato_repo.list_by_ids(empresa_id, contato_ids)
        else:
            contatos = await contato_repo.list_ativos(empresa_id)

        if not contatos:
            raise SemContatosParaDisparar("Nenhum contato selecionado para disparar")

        await camp_repo.create_envios_batch(campanha_id, empresa_id, contatos)
        await camp_repo.iniciar(campanha_id, len(contatos))

        logger.info("[campanha] iniciada id=%d empresa=%d contatos=%d", campanha_id, empresa_id, len(contatos))
        return {"status": "running", "total": len(contatos)}

    elif camp["status"] in _RETOMAVEL:
        await camp_repo.retomar_envios_pausados(campanha_id)
        await camp_repo.update_status(campanha_id, "running")
        logger.info("[campanha] retomada id=%d empresa=%d", campanha_id, empresa_id)
        return {"status": "running", "total": camp["total"]}

    raise ValueError(f"Campanha em estado inválido para iniciar: {camp['status']}")


async def pausar_campanha(db, empresa_id: int, campanha_id: int) -> dict:
    """Pausa uma campanha em execução."""
    repo = CampanhaRepository(db)
    camp = await repo.get(empresa_id, campanha_id)
    if not camp:
        raise CampanhaNaoEncontrada(f"Campanha {campanha_id} não encontrada")

    await repo.pausar_envios(campanha_id)
    await repo.update_status(campanha_id, "paused")
    logger.info("[campanha] pausada id=%d empresa=%d", campanha_id, empresa_id)
    return {"status": "paused"}


async def calcular_progresso(db, empresa_id: int, campanha_id: int) -> dict:
    """Retorna progresso atual da campanha."""
    row = await CampanhaRepository(db).progresso(empresa_id, campanha_id)
    if not row:
        raise CampanhaNaoEncontrada(f"Campanha {campanha_id} não encontrada")
    pct = round(row["enviados"] / row["total"] * 100, 1) if row["total"] else 0.0
    return {
        "status":   row["status"],
        "total":    row["total"],
        "enviados": row["enviados"],
        "erros":    row["erros"],
        "pct":      pct,
    }
