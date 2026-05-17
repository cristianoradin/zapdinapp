"""
app/routers/chatbot_router.py — API do módulo Chatbot.
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..core.database import get_db
from ..core.security import get_current_user

router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])


# ── Pydantic ──────────────────────────────────────────────────────────────────

class ChatbotConfigBody(BaseModel):
    ativo: bool = True
    system_prompt: str = ""

class BoasVindasBody(BaseModel):
    ativo: bool = False
    msg: str = ""

class FaqBody(BaseModel):
    pergunta: str
    resposta: str

class AprendizadoAvalBody(BaseModel):
    aprovado: bool

class ChatbotAtivoBody(BaseModel):
    chatbot_ativo: bool

class EnviarMsgBody(BaseModel):
    phone: str
    mensagem: str


# ── Config / Personalidade ────────────────────────────────────────────────────

@router.get("/config")
async def get_chatbot_config(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        """SELECT ativo, system_prompt, boas_vindas_ativo, boas_vindas_msg, memoria_ia_ativa
           FROM chatbot_config WHERE empresa_id=?""",
        (empresa_id,)
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return {"ativo": True, "system_prompt": "",
                "boas_vindas_ativo": False, "boas_vindas_msg": "",
                "memoria_ia_ativa": True}

    return {
        "ativo":             bool(row["ativo"]),
        "system_prompt":     row["system_prompt"] or "",
        "boas_vindas_ativo": bool(row["boas_vindas_ativo"]),
        "boas_vindas_msg":   row["boas_vindas_msg"] or "",
        "memoria_ia_ativa":  row["memoria_ia_ativa"] if row["memoria_ia_ativa"] is not None else True,
    }


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


# ── Boas-vindas ───────────────────────────────────────────────────────────────

@router.post("/boas-vindas")
async def set_boas_vindas(
    body: BoasVindasBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await db.execute(
        """INSERT INTO chatbot_config(empresa_id, boas_vindas_ativo, boas_vindas_msg)
           VALUES(?, ?, ?)
           ON CONFLICT(empresa_id) DO UPDATE
             SET boas_vindas_ativo=excluded.boas_vindas_ativo,
                 boas_vindas_msg=excluded.boas_vindas_msg""",
        (empresa_id, body.ativo, body.msg.strip())
    )
    await db.commit()
    return {"ok": True}


# ── FAQ ───────────────────────────────────────────────────────────────────────

@router.get("/faq")
async def list_faq(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT id, pergunta, resposta FROM chatbot_faq WHERE empresa_id=? AND ativo=TRUE ORDER BY id ASC",
        (empresa_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [{"id": r["id"], "pergunta": r["pergunta"], "resposta": r["resposta"]} for r in rows]


@router.post("/faq")
async def add_faq(
    body: FaqBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    if not body.pergunta.strip() or not body.resposta.strip():
        from fastapi import HTTPException
        raise HTTPException(400, "Pergunta e resposta são obrigatórias")
    await db.execute(
        "INSERT INTO chatbot_faq(empresa_id, pergunta, resposta) VALUES(?, ?, ?)",
        (empresa_id, body.pergunta.strip(), body.resposta.strip())
    )
    await db.commit()
    return {"ok": True}


@router.delete("/faq/{faq_id}")
async def delete_faq(
    faq_id: int,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await db.execute(
        "UPDATE chatbot_faq SET ativo=FALSE WHERE id=? AND empresa_id=?",
        (faq_id, empresa_id)
    )
    await db.commit()
    return {"ok": True}


# ── Aprendizado ───────────────────────────────────────────────────────────────

@router.get("/aprendizado")
async def list_aprendizado(
    filtro: Optional[str] = Query(None),
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    where = "WHERE empresa_id=?"
    params = [empresa_id]
    if filtro == "aprovados":
        where += " AND aprovado=TRUE"
    elif filtro == "pendentes":
        where += " AND aprovado IS NULL"

    async with db.execute(
        f"""SELECT id, phone, pergunta, resposta, aprovado, created_at
            FROM chatbot_aprendizado {where}
            ORDER BY created_at DESC LIMIT 200""",
        tuple(params)
    ) as cur:
        rows = await cur.fetchall()

    return [
        {
            "id": r["id"],
            "phone": r["phone"],
            "pergunta": r["pergunta"],
            "resposta": r["resposta"],
            "aprovado": r["aprovado"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.patch("/aprendizado/{item_id}")
async def avaliar_aprendizado(
    item_id: int,
    body: AprendizadoAvalBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await db.execute(
        "UPDATE chatbot_aprendizado SET aprovado=? WHERE id=? AND empresa_id=?",
        (body.aprovado, item_id, empresa_id)
    )
    await db.commit()
    return {"ok": True}


@router.delete("/aprendizado/{item_id}")
async def delete_aprendizado(
    item_id: int,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await db.execute(
        "DELETE FROM chatbot_aprendizado WHERE id=? AND empresa_id=?",
        (item_id, empresa_id)
    )
    await db.commit()
    return {"ok": True}


# ── Conversas / Histórico ─────────────────────────────────────────────────────

@router.get("/conversas")
async def list_conversas(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        """SELECT
             h.phone,
             COALESCE(c.nome, h.phone) AS contato_nome,
             COALESCE(c.chatbot_ativo, TRUE) AS chatbot_ativo,
             COUNT(*) AS total_msgs,
             MAX(h.created_at) AS ultima_msg,
             (SELECT conteudo FROM chat_historico ch2
              WHERE ch2.empresa_id = h.empresa_id AND ch2.phone = h.phone
              ORDER BY ch2.created_at DESC LIMIT 1) AS ultima_preview
           FROM chat_historico h
           LEFT JOIN contatos c ON c.empresa_id = h.empresa_id AND c.phone = REGEXP_REPLACE(h.phone, '^55', '')
           WHERE h.empresa_id = ?
           GROUP BY h.phone, h.empresa_id, c.nome, c.chatbot_ativo
           ORDER BY ultima_msg DESC
           LIMIT 100""",
        (empresa_id,),
    ) as cur:
        rows = await cur.fetchall()

    return [
        {
            "phone": r["phone"],
            "nome": r["contato_nome"],
            "chatbot_ativo": bool(r["chatbot_ativo"]),
            "total_msgs": r["total_msgs"],
            "ultima_msg": r["ultima_msg"].isoformat() if r["ultima_msg"] else None,
            "ultima_preview": (r["ultima_preview"] or "")[:80],
        }
        for r in rows
    ]


@router.get("/historico/{phone}")
async def get_historico(
    phone: str,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        """SELECT role, conteudo, created_at
           FROM chat_historico
           WHERE empresa_id=? AND phone=?
           ORDER BY created_at ASC LIMIT 100""",
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


@router.post("/enviar")
async def enviar_mensagem_manual(
    body: EnviarMsgBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Envia mensagem manual pelo WhatsApp e salva no histórico."""
    from fastapi import HTTPException
    from ..services.evolution_service import evo_manager

    empresa_id = user["empresa_id"]
    phone = body.phone.strip()
    mensagem = body.mensagem.strip()
    if not phone or not mensagem:
        raise HTTPException(400, "phone e mensagem obrigatórios")

    jid = phone if "@" in phone else f"{phone}@s.whatsapp.net"
    session_id = evo_manager.pick_session(empresa_id)
    if not session_id:
        raise HTTPException(503, "Nenhuma sessão WhatsApp ativa")

    ok, err = await evo_manager.send_text(session_id, empresa_id, jid, mensagem)
    if not ok:
        raise HTTPException(502, f"Falha ao enviar pelo WhatsApp: {err}")

    # Salva no histórico como 'assistant' para manter o contexto
    await db.execute(
        "INSERT INTO chat_historico(empresa_id, phone, role, conteudo) VALUES(?,?,?,?)",
        (empresa_id, phone, "assistant", mensagem),
    )
    await db.commit()
    return {"ok": True}


@router.patch("/contato/{phone}/chatbot-ativo")
async def toggle_chatbot_ativo(
    phone: str,
    body: ChatbotAtivoBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Ativa ou pausa o chatbot para um contato específico."""
    empresa_id = user["empresa_id"]
    # phone chega sem prefixo 55 (como guardado em contatos)
    phone_local = phone.replace("@s.whatsapp.net", "").replace("@lid", "")
    if phone_local.startswith("55") and len(phone_local) >= 12:
        phone_local = phone_local[2:]
    await db.execute(
        """INSERT INTO contatos(empresa_id, phone, chatbot_ativo, origem)
           VALUES(?,?,?,'chatbot')
           ON CONFLICT(empresa_id, phone) DO UPDATE SET chatbot_ativo=excluded.chatbot_ativo""",
        (empresa_id, phone_local, body.chatbot_ativo),
    )
    await db.commit()
    return {"ok": True}


@router.delete("/historico/{phone}")
async def delete_historico(
    phone: str,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await db.execute(
        "DELETE FROM chat_historico WHERE empresa_id=? AND phone=?",
        (empresa_id, phone)
    )
    await db.commit()
    return {"ok": True}


# ── Memória IA ────────────────────────────────────────────────────────────────

class MemoriaIaBody(BaseModel):
    intencao: str
    variacoes: str = "[]"
    resposta_ideal: str
    aprovado: Optional[bool] = None

class MemoriaIaAtivaBody(BaseModel):
    memoria_ia_ativa: bool


@router.get("/memoria-ia")
async def list_memoria_ia(
    filtro: Optional[str] = Query(None),
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    where = "WHERE empresa_id=?"
    params = [empresa_id]
    if filtro == "aprovadas":
        where += " AND aprovado=TRUE"
    elif filtro == "pendentes":
        where += " AND aprovado IS NULL"
    elif filtro == "rejeitadas":
        where += " AND aprovado=FALSE"
    async with db.execute(
        f"""SELECT id, intencao, variacoes, resposta_ideal, confianca, usos,
                   aprovado, fonte, created_at, updated_at
            FROM chatbot_memoria_ia {where}
            ORDER BY usos DESC, created_at DESC LIMIT 200""",
        tuple(params),
    ) as cur:
        rows = await cur.fetchall()
    return [
        {
            "id": r["id"],
            "intencao": r["intencao"],
            "variacoes": r["variacoes"],
            "resposta_ideal": r["resposta_ideal"],
            "confianca": r["confianca"],
            "usos": r["usos"],
            "aprovado": r["aprovado"],
            "fonte": r["fonte"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.get("/memoria-ia/stats")
async def stats_memoria_ia(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        """SELECT
             COUNT(*) AS total,
             COUNT(*) FILTER (WHERE aprovado=TRUE) AS aprovadas,
             COUNT(*) FILTER (WHERE aprovado IS NULL) AS pendentes,
             COUNT(*) FILTER (WHERE aprovado=FALSE) AS rejeitadas,
             COALESCE(SUM(usos),0) AS total_usos
           FROM chatbot_memoria_ia WHERE empresa_id=?""",
        (empresa_id,),
    ) as cur:
        r = await cur.fetchone()
    return {
        "total": r["total"],
        "aprovadas": r["aprovadas"],
        "pendentes": r["pendentes"],
        "rejeitadas": r["rejeitadas"],
        "total_usos": r["total_usos"],
    }


@router.post("/memoria-ia")
async def add_memoria_ia(
    body: MemoriaIaBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    from fastapi import HTTPException
    if not body.intencao.strip() or not body.resposta_ideal.strip():
        raise HTTPException(400, "intencao e resposta_ideal são obrigatórios")
    await db.execute(
        """INSERT INTO chatbot_memoria_ia(empresa_id, intencao, variacoes, resposta_ideal, fonte, aprovado)
           VALUES(?,?,?,?,'manual',?)""",
        (empresa_id, body.intencao.strip(), body.variacoes, body.resposta_ideal.strip(), body.aprovado),
    )
    await db.commit()
    return {"ok": True}


@router.patch("/memoria-ia/{item_id}")
async def update_memoria_ia(
    item_id: int,
    body: MemoriaIaBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await db.execute(
        """UPDATE chatbot_memoria_ia
           SET intencao=?, variacoes=?, resposta_ideal=?, aprovado=?, updated_at=NOW()
           WHERE id=? AND empresa_id=?""",
        (body.intencao.strip(), body.variacoes, body.resposta_ideal.strip(), body.aprovado, item_id, empresa_id),
    )
    await db.commit()
    return {"ok": True}


@router.patch("/memoria-ia/{item_id}/aprovar")
async def aprovar_memoria_ia(
    item_id: int,
    body: AprendizadoAvalBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await db.execute(
        "UPDATE chatbot_memoria_ia SET aprovado=?, updated_at=NOW() WHERE id=? AND empresa_id=?",
        (body.aprovado, item_id, empresa_id),
    )
    await db.commit()
    return {"ok": True}


@router.delete("/memoria-ia/{item_id}")
async def delete_memoria_ia(
    item_id: int,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await db.execute(
        "DELETE FROM chatbot_memoria_ia WHERE id=? AND empresa_id=?",
        (item_id, empresa_id),
    )
    await db.commit()
    return {"ok": True}


@router.post("/config/memoria-ia-ativa")
async def set_memoria_ia_ativa(
    body: MemoriaIaAtivaBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await db.execute(
        """INSERT INTO chatbot_config(empresa_id, memoria_ia_ativa)
           VALUES(?,?)
           ON CONFLICT(empresa_id) DO UPDATE SET memoria_ia_ativa=excluded.memoria_ia_ativa""",
        (empresa_id, body.memoria_ia_ativa),
    )
    await db.commit()
    return {"ok": True}
