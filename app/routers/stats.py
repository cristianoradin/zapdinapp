import json
import os
import sys
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from ..core.config import settings
from ..core.database import get_db
from ..core.security import get_current_user, verify_erp_token

if settings.use_evolution:
    from ..services.evolution_service import evo_manager as wa_manager
else:
    from ..services.whatsapp_service import wa_manager

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _read_version() -> str:
    try:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return json.loads(open(os.path.join(base, "versao.json")).read())["versao"]
    except Exception:
        try:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            return json.loads(open(os.path.join(base, "versao.json")).read())["versao"]
        except Exception:
            return "?"


@router.get("/version")
async def get_version(_: dict = Depends(get_current_user)):
    """Retorna a versão atual do app (lida do versao.json)."""
    return {"versao": _read_version()}


@router.get("")
async def get_stats(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]

    async with db.execute(
        "SELECT COUNT(*) as total FROM mensagens WHERE empresa_id=?", (empresa_id,)
    ) as cur:
        total = (await cur.fetchone())["total"]

    async with db.execute(
        "SELECT COUNT(*) as total FROM mensagens WHERE empresa_id=? AND status='sent'",
        (empresa_id,),
    ) as cur:
        enviadas = (await cur.fetchone())["total"]

    async with db.execute(
        "SELECT COUNT(*) as total FROM mensagens WHERE empresa_id=? AND status='failed'",
        (empresa_id,),
    ) as cur:
        falhas = (await cur.fetchone())["total"]

    async with db.execute(
        "SELECT COUNT(*) as total FROM mensagens WHERE empresa_id=? AND created_at::date = CURRENT_DATE",
        (empresa_id,),
    ) as cur:
        hoje = (await cur.fetchone())["total"]

    sessoes_ativas = sum(
        1 for s in wa_manager.get_status(empresa_id) if s["status"] == "connected"
    )

    async with db.execute(
        """SELECT destinatario, mensagem, status, created_at
           FROM mensagens WHERE empresa_id=?
           ORDER BY created_at DESC LIMIT 20""",
        (empresa_id,),
    ) as cur:
        recentes = [dict(r) for r in await cur.fetchall()]

    return {
        "total_mensagens": total,
        "enviadas": enviadas,
        "falhas": falhas,
        "hoje": hoje,
        "sessoes_ativas": sessoes_ativas,
        "recentes": recentes,
    }


@router.get("/queue")
async def get_queue_stats(
    db=Depends(get_db),
    x_token: Optional[str] = Header(default=None),
):
    """
    Retorna estatísticas da fila de envio autenticado por token ERP.
    Usado pelo PDV local para exibir o status da fila sem login de sessão.
    """
    # Autentica pelo token ERP (mesmo mecanismo do /api/erp/*)
    if not x_token:
        raise HTTPException(status_code=401, detail="Token obrigatório")
    async with db.execute(
        "SELECT empresa_id, value FROM config WHERE key='erp_token'"
    ) as cur:
        rows = await cur.fetchall()
    empresa_id = None
    for row in rows:
        if verify_erp_token(x_token, row["value"]):
            empresa_id = row["empresa_id"]
            break
    if not empresa_id:
        raise HTTPException(status_code=401, detail="Token inválido")

    async with db.execute(
        "SELECT COUNT(*) as c FROM mensagens WHERE empresa_id=? AND status='queued'",
        (empresa_id,),
    ) as cur:
        msg_queued = (await cur.fetchone())["c"]

    async with db.execute(
        "SELECT COUNT(*) as c FROM arquivos WHERE empresa_id=? AND status='queued'",
        (empresa_id,),
    ) as cur:
        arq_queued = (await cur.fetchone())["c"]

    async with db.execute(
        "SELECT COUNT(*) as c FROM mensagens WHERE empresa_id=? AND status='sent' AND sent_at::date = CURRENT_DATE",
        (empresa_id,),
    ) as cur:
        msg_sent = (await cur.fetchone())["c"]

    async with db.execute(
        "SELECT COUNT(*) as c FROM mensagens WHERE empresa_id=? AND status='failed'",
        (empresa_id,),
    ) as cur:
        msg_failed = (await cur.fetchone())["c"]

    sessoes = wa_manager.get_status(empresa_id)
    conectadas = [s for s in sessoes if s["status"] == "connected"]

    return {
        "mensagens_queued": msg_queued,
        "arquivos_queued":  arq_queued,
        "mensagens_sent":   msg_sent,
        "mensagens_failed": msg_failed,
        "sessoes_conectadas": len(conectadas),
        "sessoes": sessoes,
    }
