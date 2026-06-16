"""
app/routers/chat_router.py — Integração de CHAT (sistema de chamados externo).

Só Evolution (servidor). Não toca no envio de campanha/ERP nem no modo agente.
Auth: header X-Token (mesmo token ERP da empresa) → resolve empresa_id.

Endpoints:
  POST /api/chat/send    {number, text}         → envia mensagem (1 número → cliente)
  POST /api/chat/typing  {number, state}        → presença (composing/paused/available)
  POST /api/chat/config  {webhook_url}          → URL pra onde o ZapDin repassa
                                                   mensagens recebidas + 'digitando' do cliente

Inbound + presence do cliente são repassados pra config.chat_webhook_url
(ver evolution_service.handle_webhook → _forward_chat).
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ..core.database import get_db
from ..services.evolution_service import evo_manager
from .erp import _verify_token  # X-Token → empresa_id (reusa validação do ERP)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class SendBody(BaseModel):
    number: str = Field(min_length=8, max_length=20)
    text: str = Field(min_length=1, max_length=4096)


class TypingBody(BaseModel):
    number: str = Field(min_length=8, max_length=20)
    state: str = "composing"   # composing | paused | available


class WebhookCfg(BaseModel):
    webhook_url: str = Field(default="", max_length=500)


@router.post("/send")
async def chat_send(body: SendBody, request: Request,
                    x_token: Optional[str] = Header(default=None), db=Depends(get_db)):
    empresa_id = await _verify_token(x_token, db, request)
    sid = evo_manager._first_session_id(empresa_id)
    if not sid:
        raise HTTPException(409, "Nenhuma sessão WhatsApp da empresa.")
    ok, err = await evo_manager.send_text(sid, empresa_id, body.number, body.text)
    if not ok:
        raise HTTPException(502, err or "Falha ao enviar")
    return {"ok": True}


@router.post("/typing")
async def chat_typing(body: TypingBody, request: Request,
                      x_token: Optional[str] = Header(default=None), db=Depends(get_db)):
    empresa_id = await _verify_token(x_token, db, request)
    state = body.state if body.state in ("composing", "paused", "available") else "composing"
    ok, err = await evo_manager.send_presence(empresa_id, body.number, state)
    return {"ok": ok, "error": err}


@router.post("/config")
async def chat_config(body: WebhookCfg, request: Request,
                      x_token: Optional[str] = Header(default=None), db=Depends(get_db)):
    empresa_id = await _verify_token(x_token, db, request)
    url = (body.webhook_url or "").strip()
    if url and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(422, "webhook_url inválida")
    await db.execute(
        """INSERT INTO config (empresa_id, key, value) VALUES (?, 'chat_webhook_url', ?)
           ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value""",
        (empresa_id, url),
    )
    await db.commit()
    return {"ok": True, "webhook_url": url}
