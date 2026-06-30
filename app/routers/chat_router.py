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
    session_id: Optional[str] = None    # SGADesk: responder por sessão/número específico


class TypingBody(BaseModel):
    number: str = Field(min_length=8, max_length=20)
    state: str = "composing"   # composing | paused | available
    session_id: Optional[str] = None


class SendFileBody(BaseModel):
    number: str = Field(min_length=8, max_length=20)
    media_base64: str = Field(min_length=1)             # arquivo em base64 (sem data URI)
    filename: str = Field(min_length=1, max_length=255)
    caption: Optional[str] = Field(default="", max_length=1024)
    session_id: Optional[str] = None


class WebhookCfg(BaseModel):
    webhook_url: str = Field(default="", max_length=500)
    webhook_secret: str = Field(default="", max_length=200)   # segredo HMAC do webhook


async def _resolve_session(session_id: Optional[str], empresa_id: int, db) -> str:
    """Resolve a sessão de envio (SGADesk multi-número):
    - session_id informado → valida que é da empresa E está conectado; senão 409.
    - omitido → cai no propósito 'chamados' (comportamento atual)."""
    if session_id:
        async with db.execute(
            "SELECT 1 FROM sessoes_wa WHERE id=? AND empresa_id=? AND status='connected'",
            (session_id, empresa_id),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            raise HTTPException(409, "sessao_nao_conectada")
        return session_id
    sid = await evo_manager.pick_session_uso(empresa_id, "chamados", strict=True)
    if not sid:
        raise HTTPException(409, "Nenhum número de WhatsApp com propósito 'chamados' conectado.")
    return sid


@router.post("/send")
async def chat_send(body: SendBody, request: Request,
                    x_token: Optional[str] = Header(default=None), db=Depends(get_db)):
    empresa_id = await _verify_token(x_token, db, request)
    sid = await _resolve_session(body.session_id, empresa_id, db)
    ok, err = await evo_manager.send_text(sid, empresa_id, body.number, body.text)
    if not ok:
        raise HTTPException(502, err or "Falha ao enviar")
    return {"ok": True}


@router.post("/send-file")
async def chat_send_file(body: SendFileBody, request: Request,
                        x_token: Optional[str] = Header(default=None), db=Depends(get_db)):
    empresa_id = await _verify_token(x_token, db, request)
    sid = await _resolve_session(body.session_id, empresa_id, db)
    ok, err = await evo_manager.send_file_b64(
        empresa_id, body.number,
        media_base64=body.media_base64,
        filename=body.filename,
        caption=body.caption or "",
        session_id=sid,
    )
    if not ok:
        # 409 = sem sessão; 502 = falha de envio
        code = 409 if (err or "").startswith("Nenhuma sessão") else 502
        raise HTTPException(code, err or "Falha ao enviar arquivo")
    return {"ok": True}


@router.post("/typing")
async def chat_typing(body: TypingBody, request: Request,
                      x_token: Optional[str] = Header(default=None), db=Depends(get_db)):
    empresa_id = await _verify_token(x_token, db, request)
    state = body.state if body.state in ("composing", "paused", "available") else "composing"
    sid = await _resolve_session(body.session_id, empresa_id, db) if body.session_id else None
    ok, err = await evo_manager.send_presence(empresa_id, body.number, state, session_id=sid)
    return {"ok": ok, "error": err}


@router.get("/sessions")
async def chat_sessions(request: Request, x_token: Optional[str] = Header(default=None),
                        db=Depends(get_db)):
    """Lista as sessões conectadas da empresa (SGADesk mapeia sessão→setor). Auth X-Token."""
    empresa_id = await _verify_token(x_token, db, request)
    async with db.execute(
        "SELECT id, nome, phone, status, usos FROM sessoes_wa "
        "WHERE empresa_id=? AND status='connected' ORDER BY id", (empresa_id,),
    ) as cur:
        rows = await cur.fetchall()
    import json as _json
    out = []
    for r in rows:
        usos = r["usos"]
        try:
            usos = _json.loads(usos) if isinstance(usos, str) else (usos or [])
        except Exception:
            usos = []
        out.append({"id": r["id"], "nome": r["nome"], "phone": r["phone"],
                    "status": r["status"], "usos": usos})
    return out


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
    secret = (body.webhook_secret or "").strip()
    if secret:
        await db.execute(
            """INSERT INTO config (empresa_id, key, value) VALUES (?, 'chat_webhook_secret', ?)
               ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value""",
            (empresa_id, secret),
        )
    await db.commit()
    return {"ok": True, "webhook_url": url, "secret_set": bool(secret)}
