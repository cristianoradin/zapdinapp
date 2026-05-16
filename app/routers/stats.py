"""
app/routers/stats.py — Estatísticas e saúde do sistema.
"""
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from ..core.config import settings
from ..core.database import get_db
from ..core.security import get_current_user, verify_erp_token
from ..repositories import MensagemRepository
from ..repositories.config_repository import ConfigRepository

if settings.use_evolution:
    from ..services.evolution_service import evo_manager as wa_manager
else:
    from ..services.whatsapp_service import wa_manager

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _read_version() -> str:
    for base in (
        os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None,
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ):
        if base:
            try:
                return json.loads(open(os.path.join(base, "versao.json")).read())["versao"]
            except Exception:
                continue
    return "?"


@router.get("/version")
async def get_version(_: dict = Depends(get_current_user)):
    return {"versao": _read_version()}


@router.get("")
async def get_stats(db=Depends(get_db), user: dict = Depends(get_current_user)):
    empresa_id = user["empresa_id"]
    repo = MensagemRepository(db)

    total    = await repo.count_total_sent(empresa_id) + await repo.count_errors(empresa_id)
    enviadas = await repo.count_total_sent(empresa_id)
    falhas   = await repo.count_errors(empresa_id)
    hoje     = await repo.count_today(empresa_id)
    recentes = await repo.list_recent(empresa_id, limit=20)

    sessoes_ativas = sum(
        1 for s in wa_manager.get_status(empresa_id) if s["status"] == "connected"
    )

    return {
        "total_mensagens": total,
        "enviadas": enviadas,
        "falhas": falhas,
        "hoje": hoje,
        "sessoes_ativas": sessoes_ativas,
        "recentes": [dict(r) for r in recentes],
    }


@router.get("/queue")
async def get_queue_stats(
    db=Depends(get_db),
    x_token: Optional[str] = Header(default=None),
):
    """Estatísticas da fila — autenticado por token ERP (usado pelo PDV)."""
    if not x_token:
        raise HTTPException(status_code=401, detail="Token obrigatório")

    rows = await ConfigRepository(db).get_all_erp_tokens()
    empresa_id = next(
        (row["empresa_id"] for row in rows if verify_erp_token(x_token, row["value"])),
        None,
    )
    if not empresa_id:
        raise HTTPException(status_code=401, detail="Token inválido")

    repo = MensagemRepository(db)
    status_map = await repo.count_by_status(empresa_id)

    async with db.execute(
        "SELECT COUNT(*) as c FROM arquivos WHERE empresa_id=? AND status='queued'",
        (empresa_id,),
    ) as cur:
        arq_queued = (await cur.fetchone())["c"]

    sessoes   = wa_manager.get_status(empresa_id)
    conectadas = [s for s in sessoes if s["status"] == "connected"]

    return {
        "mensagens_queued":  status_map.get("queued", 0),
        "arquivos_queued":   arq_queued,
        "mensagens_sent":    status_map.get("sent", 0),
        "mensagens_failed":  status_map.get("failed", 0),
        "sessoes_conectadas": len(conectadas),
        "sessoes": sessoes,
    }


@router.get("/queue-health")
async def queue_health(db=Depends(get_db), user: dict = Depends(get_current_user)):
    """Verifica saúde da fila — alerta se item queued > 30 min sem processar."""
    empresa_id = user["empresa_id"]

    status_map = await MensagemRepository(db).count_by_status(empresa_id)
    msg_queued = status_map.get("queued", 0)

    async with db.execute(
        "SELECT COUNT(*) as c FROM arquivos WHERE empresa_id=? AND status='queued'",
        (empresa_id,),
    ) as cur:
        arq_queued = (await cur.fetchone())["c"]

    # Item mais antigo na fila
    stuck_minutes = None
    stuck_alert   = False
    async with db.execute(
        "SELECT MIN(created_at) as mais_antigo FROM ("
        "  SELECT created_at FROM mensagens WHERE empresa_id=? AND status='queued'"
        "  UNION ALL"
        "  SELECT created_at FROM arquivos   WHERE empresa_id=? AND status='queued'"
        ") q",
        (empresa_id, empresa_id),
    ) as cur:
        row = await cur.fetchone()

    if row and row["mais_antigo"]:
        try:
            mais_antigo = row["mais_antigo"]
            if hasattr(mais_antigo, "tzinfo") and mais_antigo.tzinfo is None:
                mais_antigo = mais_antigo.replace(tzinfo=timezone.utc)
            diff = (datetime.now(tz=timezone.utc) - mais_antigo).total_seconds() / 60
            stuck_minutes = round(diff, 1)
            stuck_alert   = diff > 30
        except Exception:
            pass

    sessoes   = wa_manager.get_status(empresa_id)
    conectadas = [s for s in sessoes if s["status"] == "connected"]

    return {
        "total_queued":   msg_queued + arq_queued,
        "msg_queued":     msg_queued,
        "arq_queued":     arq_queued,
        "stuck_minutes":  stuck_minutes,
        "stuck_alert":    stuck_alert,
        "wa_connected":   len(conectadas) > 0,
        "sessoes_ativas": len(conectadas),
    }
