import logging
import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from ..core.database import get_db
from ..core.security import get_current_user
from ..core.config import settings
from ..services.log_service import log_event

logger = logging.getLogger(__name__)

if settings.use_evolution:
    from ..services.evolution_service import evo_manager as wa_manager
else:
    from ..services.whatsapp_service import wa_manager

router = APIRouter(prefix="/api/sessoes", tags=["whatsapp"])

_MODOS_VALIDOS = {"servidor", "local", "agente"}


def _modo_from_url(evo_url: str | None) -> str:
    """Deriva o modo de conexão a partir da evolution_url da sessão."""
    u = (evo_url or "").strip().lower()
    if not u:
        return "servidor"
    if u.startswith("agent://"):
        return "agente"
    return "local"


async def _modos_permitidos(db, empresa_id: int) -> list[str]:
    """Lista de modos permitidos pra empresa (definido pelo Monitor admin)."""
    async with db.execute("SELECT modos_conexao FROM empresas WHERE id=?", (empresa_id,)) as cur:
        row = await cur.fetchone()
    raw = (row["modos_conexao"] if row else "") or "servidor,local,agente"
    modos = [m.strip() for m in raw.split(",") if m.strip() in _MODOS_VALIDOS]
    return modos or ["servidor"]


class SessaoCreate(BaseModel):
    nome: str
    # Modo híbrido: URL custom da Evolution local do cliente.
    # None/vazio → usa Evolution do servidor (modo padrão).
    evolution_url: str | None = None


@router.get("")
async def list_sessoes(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT id, nome, status, phone, last_seen, evolution_url FROM sessoes_wa "
        "WHERE empresa_id=? ORDER BY created_at",
        (empresa_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_sessao(
    body: SessaoCreate,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    import uuid
    empresa_id = user["empresa_id"]
    sessao_id = str(uuid.uuid4())[:8]
    # Normaliza evolution_url: vazio/só-espaços/inválido → None (usa servidor)
    evo_url = (body.evolution_url or "").strip() or None
    if evo_url and not evo_url.lower().startswith(("http://", "https://", "agent://")):
        raise HTTPException(status_code=422, detail="URL inválida. Use http://, https:// ou agent://")
    # Enforce modos permitidos no BACKEND (não confia só no frontend que esconde radios).
    # Ex: empresa restrita a "agente" não pode criar sessão "servidor" (evo_url=None).
    modo = _modo_from_url(evo_url)
    permitidos = await _modos_permitidos(db, empresa_id)
    if modo not in permitidos:
        raise HTTPException(
            status_code=403,
            detail=f"Modo de conexão '{modo}' não permitido para esta empresa. "
                   f"Permitidos: {', '.join(permitidos)}.",
        )
    await db.execute(
        "INSERT INTO sessoes_wa (empresa_id, id, nome, status, evolution_url) "
        "VALUES (?, ?, ?, 'disconnected', ?)",
        (empresa_id, sessao_id, body.nome, evo_url),
    )
    await db.commit()
    await wa_manager.add_session(sessao_id, body.nome, empresa_id, evolution_url=evo_url)
    logger.info("[whatsapp] Sessão criada: id=%s nome=%s empresa=%s evo_url=%s",
                sessao_id, body.nome, empresa_id, evo_url or "servidor")
    await log_event(empresa_id=empresa_id, nivel="info", modulo="whatsapp", acao="session_connect",
                    mensagem=f"WhatsApp conectado: {sessao_id} ({'local cliente' if evo_url else 'servidor'})")
    return {"ok": True, "id": sessao_id, "nome": body.nome, "status": "disconnected",
            "evolution_url": evo_url}


@router.delete("/{sessao_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sessao(
    sessao_id: str,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await wa_manager.remove_session(sessao_id, empresa_id)
    await db.execute(
        "DELETE FROM sessoes_wa WHERE id=? AND empresa_id=?", (sessao_id, empresa_id)
    )
    await db.commit()
    logger.info("[whatsapp] Sessão removida: id=%s empresa=%s", sessao_id, empresa_id)


@router.get("/live-status")
async def live_status(db=Depends(get_db), user: dict = Depends(get_current_user)):
    """Status das sessões. Agente: DB sessoes_wa é a verdade (atualizado pelo
    reconcile/refresh-phone — QR pelo tray reflete aqui). Servidor/local: usa o
    status em memória (real-time), com fallback pro DB."""
    empresa_id = user["empresa_id"]
    mem = {s["id"]: s for s in wa_manager.get_status(empresa_id)}
    out, seen = [], set()
    async with db.execute(
        "SELECT id, nome, status, phone, evolution_url, usos FROM sessoes_wa WHERE empresa_id=? ORDER BY created_at",
        (empresa_id,),
    ) as cur:
        rows = await cur.fetchall()
    import json as _json
    for r in rows:
        sid = r["id"]; evo = (r["evolution_url"] or "").strip()
        is_agent = evo.lower().startswith("agent://")
        m = mem.get(sid)
        if is_agent:
            status, phone = r["status"], r["phone"]
        else:
            status = (m or {}).get("status") or r["status"]
            phone = (m or {}).get("phone") or r["phone"]
        try:
            usos = _json.loads(r["usos"]) if r["usos"] else []
        except Exception:
            usos = []
        out.append({"id": sid, "nome": r["nome"], "status": status, "phone": phone,
                    "evolution_url": evo, "usos": usos,
                    "modo": "agente" if is_agent else ("local" if evo else "servidor")})
        seen.add(sid)
    for sid, m in mem.items():
        if sid not in seen:
            out.append(m)
    return out


@router.get("/modos-permitidos")
async def modos_permitidos(db=Depends(get_db), user: dict = Depends(get_current_user)):
    """Retorna lista de modos permitidos pra empresa (gerenciado pelo Monitor admin)."""
    empresa_id = user["empresa_id"]
    return {"modos": await _modos_permitidos(db, empresa_id)}


@router.post("/refresh-phone/{sessao_id}")
async def refresh_phone(sessao_id: str, db=Depends(get_db), user: dict = Depends(get_current_user)):
    """Pede ao agent get_state, extrai phone e grava em sessoes_wa.phone.
    Usado depois de scan QR pra identificar o número conectado."""
    empresa_id = user["empresa_id"]
    from ..services import agent_bridge
    if not agent_bridge.has_agent(empresa_id):
        raise HTTPException(503, "Nenhum agent conectado")
    ag = agent_bridge.get_agent(empresa_id)
    from ..main import sio
    try:
        res = await sio.call(
            "get_state",
            {"command": "get_state", "payload": {"instance": sessao_id}},
            to=ag["sid"], namespace="/agent", timeout=15,
        )
    except Exception as exc:
        raise HTTPException(504, f"Agent timeout: {exc}")
    if not isinstance(res, dict) or not res.get("ok"):
        err = (res or {}).get("error") if isinstance(res, dict) else "no response"
        raise HTTPException(502, f"Agent: {err}")
    state = res.get("state")
    phone = res.get("phone") or ""
    if state == "open" and phone:
        await db.execute(
            "UPDATE sessoes_wa SET status='connected', phone=?, last_seen=NOW() WHERE id=? AND empresa_id=?",
            (phone, sessao_id, empresa_id),
        )
        await db.commit()
        logger.info("[whatsapp] phone gravado: sessao=%s empresa=%s phone=%s", sessao_id, empresa_id, phone)
    return {"ok": True, "state": state, "phone": phone}


@router.get("/qr/{sessao_id}")
async def get_qr(sessao_id: str, db=Depends(get_db), user: dict = Depends(get_current_user)):
    empresa_id = user["empresa_id"]

    # Detecta modo da sessão: só roteia via agent se evolution_url == "agent://"
    async with db.execute(
        "SELECT evolution_url FROM sessoes_wa WHERE id=? AND empresa_id=?",
        (sessao_id, empresa_id),
    ) as cur:
        sess_row = await cur.fetchone()
    sess_url = (sess_row["evolution_url"] if sess_row else "") or ""
    # Enforce modo permitido também na conexão (sessão antiga "servidor" não pode
    # conectar se a empresa hoje só permite "agente").
    modo = _modo_from_url(sess_url)
    permitidos = await _modos_permitidos(db, empresa_id)
    if modo not in permitidos:
        raise HTTPException(
            status_code=403,
            detail=f"Modo '{modo}' não permitido para esta empresa. "
                   f"Permitidos: {', '.join(permitidos)}. Recrie a sessão no modo correto.",
        )
    is_agent_mode = sess_url.strip().lower().startswith("agent://")

    # Branch agent_bridge: só ativa se sessão configurada em "Agente (atravessa NAT)"
    from ..services import agent_bridge
    if is_agent_mode and agent_bridge.has_agent(empresa_id):
        from ..main import sio
        ag = agent_bridge.get_agent(empresa_id)
        logger.info("[whatsapp] get_qr via agent: empresa=%s sid=%s sessao=%s",
                    empresa_id, ag["sid"], sessao_id)
        try:
            res = await sio.call(
                "get_qr",
                {"command": "get_qr", "payload": {"instance": sessao_id}},
                to=ag["sid"],
                namespace="/agent",
                timeout=60,  # primeira chamada precisa spawn Chromium
            )
            logger.info("[whatsapp] agent response: %r", res)
            if isinstance(res, dict) and res.get("ok"):
                qr = res.get("qr") or ""
                state = res.get("state") or ""
                if not qr and state == "open":
                    raise HTTPException(status_code=409, detail="WhatsApp já conectado.")
                if not qr:
                    raise HTTPException(status_code=404, detail=f"QR ainda não disponível (state={state}), tente em 5s.")
                return {"qr": qr, "state": state, "via": "agent"}
            err = (res or {}).get("error") if isinstance(res, dict) else "agent não respondeu"
            logger.warning("[whatsapp] agent retornou erro: %s | res=%r", err, res)
            raise HTTPException(status_code=502, detail=f"Agent: {err}")
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("[whatsapp] get_qr via agent falhou")
            raise HTTPException(status_code=504, detail=f"Timeout/erro agent: {exc}")

    # Modo agente configurado mas agent não conectado → erro explícito
    if is_agent_mode and not agent_bridge.has_agent(empresa_id):
        raise HTTPException(
            status_code=503,
            detail="Sessão em modo Agente, mas nenhum ZapDinAgent conectado para esta empresa. Verifique o serviço no posto.",
        )

    # Fallback legacy (Evolution/Playwright server-side)
    qr = wa_manager.get_qr(sessao_id, empresa_id)
    if qr is None:
        logger.warning(
            "[whatsapp] QR não disponível: sessao=%s empresa=%s",
            sessao_id, empresa_id,
        )
        raise HTTPException(status_code=404, detail="QR não disponível")
    return {"qr": qr}


class SendTextBody(BaseModel):
    phone: str
    message: str


@router.post("/{sessao_id}/send-text")
async def send_text(
    sessao_id: str,
    body: SendTextBody,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Envio de teste — vai pela FILA (tipo='teste', prioritário). O worker envia
    (ignora horário/limite, com delay anti-ban). Resultado aparece no dashboard."""
    empresa_id = user["empresa_id"]
    from ..repositories import MensagemRepository
    repo = MensagemRepository(db)
    mid = await repo.enqueue(empresa_id, body.phone, "", body.message, tipo="teste")
    await db.commit()
    return {"ok": True, "queued": True, "id": mid}


@router.post("/{sessao_id}/send-file")
async def send_file(
    sessao_id: str,
    phone: str = Form(...),
    caption: str = Form(""),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        ok, err = await wa_manager.send_file(
            sessao_id, empresa_id, phone, tmp_path, file.filename, caption or None
        )
    finally:
        os.unlink(tmp_path)
    if not ok:
        logger.error(
            "[whatsapp] Falha ao enviar arquivo: sessao=%s empresa=%s fone=%s arquivo=%s erro=%s",
            sessao_id, empresa_id, phone, file.filename, err,
        )
        raise HTTPException(status_code=400, detail=err or "Erro ao enviar arquivo")
    return {"ok": True}
