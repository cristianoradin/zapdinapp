"""
app/routers/chatbot_router.py — API do módulo Chatbot.

Endpoints:
  GET  /api/chatbot/config           → config do chatbot da empresa
  POST /api/chatbot/config           → salva config (ativo, system_prompt)
  GET  /api/chatbot/conversas        → lista de contatos com histórico recente
  GET  /api/chatbot/historico/{phone}→ histórico completo de um contato
  DELETE /api/chatbot/historico/{phone} → apaga histórico de um contato
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.database import get_db
from ..core.security import get_current_user

router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])


# ── Pydantic ──────────────────────────────────────────────────────────────────

class ChatbotConfigBody(BaseModel):
    ativo: bool = True
    system_prompt: str = ""


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_chatbot_config(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT ativo, system_prompt FROM chatbot_config WHERE empresa_id=?",
        (empresa_id,)
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return {"ativo": True, "system_prompt": ""}

    return {"ativo": bool(row["ativo"]), "system_prompt": row["system_prompt"] or ""}


@router.post("/config")
async def set_chatbot_config(
    body: ChatbotConfigBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await db.execute(
        """INSERT INTO chatbot_config(empresa_id, ativo, system_prompt)
           VALUES(?, ?, ?)
           ON CONFLICT(empresa_id) DO UPDATE
             SET ativo=excluded.ativo, system_prompt=excluded.system_prompt""",
        (empresa_id, body.ativo, body.system_prompt.strip())
    )
    await db.commit()
    return {"ok": True}


@router.get("/conversas")
async def list_conversas(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Lista de contatos com histórico, ordenados pela última mensagem."""
    empresa_id = user["empresa_id"]
    async with db.execute(
        """SELECT
             h.phone,
             e.nome AS empresa_nome,
             COUNT(*) AS total_msgs,
             MAX(h.created_at) AS ultima_msg,
             (SELECT conteudo FROM chat_historico
              WHERE empresa_id = h.empresa_id AND phone = h.phone
              ORDER BY created_at DESC LIMIT 1) AS ultima_preview
           FROM chat_historico h
           LEFT JOIN empresas_contabil e ON e.telefone = SUBSTRING(h.phone FROM 3)
           WHERE h.empresa_id = ?
           GROUP BY h.phone, e.nome
           ORDER BY ultima_msg DESC
           LIMIT 100""",
        (empresa_id,)
    ) as cur:
        rows = await cur.fetchall()

    result = []
    for r in rows:
        result.append({
            "phone": r["phone"],
            "nome": r["empresa_nome"] or r["phone"],
            "total_msgs": r["total_msgs"],
            "ultima_msg": r["ultima_msg"].isoformat() if r["ultima_msg"] else None,
            "ultima_preview": (r["ultima_preview"] or "")[:80],
        })
    return result


@router.get("/historico/{phone}")
async def get_historico(
    phone: str,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Retorna histórico completo de um contato (últimas 100 mensagens)."""
    empresa_id = user["empresa_id"]
    async with db.execute(
        """SELECT role, conteudo, created_at
           FROM chat_historico
           WHERE empresa_id=? AND phone=?
           ORDER BY created_at ASC
           LIMIT 100""",
        (empresa_id, phone)
    ) as cur:
        rows = await cur.fetchall()

    return [
        {
            "role": r["role"],
            "conteudo": r["conteudo"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.delete("/historico/{phone}")
async def delete_historico(
    phone: str,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Apaga todo o histórico de um contato."""
    empresa_id = user["empresa_id"]
    await db.execute(
        "DELETE FROM chat_historico WHERE empresa_id=? AND phone=?",
        (empresa_id, phone)
    )
    await db.commit()
    return {"ok": True}
