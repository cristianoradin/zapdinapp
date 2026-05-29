"""
app/routers/config_router.py — Configuração geral da empresa.

Gerencia chaves genéricas de configuração: mensagem padrão, nome do cliente,
toggle de avaliação e qualquer outra config armazenada na tabela `config`.

Prefixo: /api/config
Chaves de IA → ai_config_router.py
Token ERP    → erp.py
Chatbot      → chatbot_router.py
"""
import json as _json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..core.config import settings
from ..core.database import get_db
from ..core.security import get_current_user

router = APIRouter(prefix="/api/config", tags=["config"])

# Template padrão usado na primeira vez (sem mensagem_padrao salva no banco)
_DEFAULT_TEMPLATE = (
    "✅ *Venda Confirmada!*\n\n"
    "👤 Cliente: {nome}\n"
    "💰 Valor Total: R$ {valor_total}\n"
    "📅 Data: {data}\n\n"
    "🛒 *Itens:*\n{produtos}\n\n"
    "Obrigado pela preferência! 🙏"
)


@router.get("")
async def get_config(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT key, value FROM config WHERE empresa_id=?", (empresa_id,)
    ) as cur:
        rows = await cur.fetchall()
    data = {r["key"]: r["value"] for r in rows}

    # Garante template padrão se ainda não foi salvo
    if "mensagem_padrao" not in data:
        data["mensagem_padrao"] = _DEFAULT_TEMPLATE

    # Expõe o nome da empresa da licença (somente leitura — não editável)
    data["client_name"] = settings.client_name or ""

    return data


@router.post("")
async def set_config(
    body: dict,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    for key, value in body.items():
        await db.execute(
            """INSERT INTO config (empresa_id, key, value) VALUES (?, ?, ?)
               ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value""",
            (empresa_id, key, str(value)),
        )
    await db.commit()
    return {"ok": True}


# ── Alerta Crítico de Avaliação ───────────────────────────────────────────────

_ALERTA_KEY = "alerta_critico"

_ALERTA_DEFAULT_MSG = (
    "🚨 *Avaliação Negativa Recebida!*\n\n"
    "👤 *Cliente:* {nome}\n"
    "📞 *Telefone:* {telefone}\n"
    "⭐ *Nota:* {nota} estrela(s)\n"
    "👨‍💼 *Vendedor:* {vendedor}\n"
    "💬 *Comentário:* {comentario}\n"
    "📅 *Data:* {data}\n\n"
    "⚠️ Entre em contato com o cliente para resolver a situação!"
)


class AlertaCriticoConfig(BaseModel):
    ativo: bool = False
    telefone: Optional[str] = ""
    mensagem: Optional[str] = _ALERTA_DEFAULT_MSG


@router.get("/alerta-critico")
async def get_alerta_critico(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Retorna a configuração atual do alerta crítico de avaliação."""
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT value FROM config WHERE empresa_id=? AND key=?",
        (empresa_id, _ALERTA_KEY),
    ) as cur:
        row = await cur.fetchone()

    if row:
        try:
            data = _json.loads(row["value"])
        except Exception:
            data = {}
    else:
        data = {}

    return {
        "ativo":    data.get("ativo", False),
        "telefone": data.get("telefone", ""),
        "mensagem": data.get("mensagem", _ALERTA_DEFAULT_MSG),
    }


@router.post("/alerta-critico")
async def set_alerta_critico(
    body: AlertaCriticoConfig,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Salva a configuração do alerta crítico de avaliação."""
    empresa_id = user["empresa_id"]
    value = _json.dumps({
        "ativo":    body.ativo,
        "telefone": body.telefone or "",
        "mensagem": body.mensagem or _ALERTA_DEFAULT_MSG,
    })
    await db.execute(
        """INSERT INTO config (empresa_id, key, value) VALUES (?, ?, ?)
           ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value""",
        (empresa_id, _ALERTA_KEY, value),
    )
    await db.commit()
    return {"ok": True}


# ── Agenda — Alertas WA ───────────────────────────────────────────────────────

_AGENDA_ALERTA_KEY = "agenda_alerta"

_AGENDA_ALERTA_DEFAULT_MSG = (
    "📅 *Lembrete de Compromisso!*\n\n"
    "📌 *{titulo}*\n"
    "🕐 Horário: *{hora}*\n"
    "📝 {descricao}\n"
    "🔗 {link}\n\n"
    "⏰ Começa em 1 hora!"
)


class AgendaAlertaConfig(BaseModel):
    ativo: bool = False
    numero_alerta: Optional[str] = ""   # número que recebe os alertas automáticos
    numero_dono: Optional[str] = ""     # número que pode enviar comandos WA à agenda
    mensagem: Optional[str] = _AGENDA_ALERTA_DEFAULT_MSG


@router.get("/agenda-alerta")
async def get_agenda_alerta(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Retorna a configuração atual do alerta de agenda."""
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT value FROM config WHERE empresa_id=? AND key=?",
        (empresa_id, _AGENDA_ALERTA_KEY),
    ) as cur:
        row = await cur.fetchone()

    data = {}
    if row:
        try:
            data = _json.loads(row["value"])
        except Exception:
            data = {}

    return {
        "ativo":         data.get("ativo", False),
        "numero_alerta": data.get("numero_alerta", ""),
        "numero_dono":   data.get("numero_dono", ""),
        "mensagem":      data.get("mensagem", _AGENDA_ALERTA_DEFAULT_MSG),
    }


@router.post("/agenda-alerta")
async def set_agenda_alerta(
    body: AgendaAlertaConfig,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Salva a configuração do alerta de agenda."""
    empresa_id = user["empresa_id"]
    value = _json.dumps({
        "ativo":         body.ativo,
        "numero_alerta": body.numero_alerta or "",
        "numero_dono":   body.numero_dono or "",
        "mensagem":      body.mensagem or _AGENDA_ALERTA_DEFAULT_MSG,
    })
    await db.execute(
        """INSERT INTO config (empresa_id, key, value) VALUES (?, ?, ?)
           ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value""",
        (empresa_id, _AGENDA_ALERTA_KEY, value),
    )
    await db.commit()
    return {"ok": True}


# ── Agenda — Usuários WA (multi-usuário) ─────────────────────────────────────

def _norm_wa_phone(phone: str) -> str:
    """Remove DDI 55 e caracteres não-numéricos."""
    p = phone.strip().replace(" ", "").replace("-", "").replace("+", "").replace("(", "").replace(")", "")
    if p.startswith("55") and len(p) >= 12:
        p = p[2:]
    return p


class AgendaWaUsuarioPayload(BaseModel):
    phone: str
    nome: str
    ativo: bool = True
    recebe_alertas: bool = True


class AgendaWaUsuarioConfigPayload(BaseModel):
    morning_digest_hora: Optional[str] = None        # "08:00" ou null = desativado
    alert_antecedencias: Optional[list] = None       # [60, 30, 15]


@router.get("/agenda-wa-usuarios")
async def list_agenda_wa_usuarios(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT id, phone, nome, ativo, recebe_alertas, "
        "morning_digest_hora, alert_antecedencias "
        "FROM agenda_wa_usuarios WHERE empresa_id=? ORDER BY nome",
        (empresa_id,),
    ) as cur:
        rows = await cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["alert_antecedencias"] = _json.loads(d["alert_antecedencias"] or "[60]")
        except Exception:
            d["alert_antecedencias"] = [60]
        result.append(d)
    return result


@router.post("/agenda-wa-usuarios")
async def create_agenda_wa_usuario(
    body: AgendaWaUsuarioPayload,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    phone = _norm_wa_phone(body.phone)
    if not phone or not body.nome.strip():
        raise HTTPException(status_code=422, detail="Nome e telefone são obrigatórios")
    try:
        cur = await db.execute(
            "INSERT INTO agenda_wa_usuarios(empresa_id,phone,nome,ativo,recebe_alertas) "
            "VALUES(?,?,?,?,?)",
            (empresa_id, phone, body.nome.strip(), body.ativo, body.recebe_alertas),
        )
        await db.commit()
        return {"ok": True, "id": cur.lastrowid}
    except Exception:
        raise HTTPException(status_code=409, detail="Número já cadastrado para esta empresa")


@router.put("/agenda-wa-usuarios/{uid}")
async def update_agenda_wa_usuario(
    uid: int,
    body: AgendaWaUsuarioPayload,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    phone = _norm_wa_phone(body.phone)
    if not phone or not body.nome.strip():
        raise HTTPException(status_code=422, detail="Nome e telefone são obrigatórios")
    await db.execute(
        "UPDATE agenda_wa_usuarios SET phone=?,nome=?,ativo=?,recebe_alertas=? "
        "WHERE id=? AND empresa_id=?",
        (phone, body.nome.strip(), body.ativo, body.recebe_alertas, uid, empresa_id),
    )
    await db.commit()
    return {"ok": True}


@router.put("/agenda-wa-usuarios/{uid}/config")
async def update_agenda_wa_usuario_config(
    uid: int,
    body: AgendaWaUsuarioConfigPayload,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Salva config avançada: horário do resumo diário e antecedências de alerta."""
    empresa_id = user["empresa_id"]
    antecedencias = body.alert_antecedencias or [60]
    # Validar: lista de inteiros positivos, máximo 10 itens
    antecedencias = sorted(set(int(x) for x in antecedencias if 1 <= int(x) <= 1440), reverse=True)
    await db.execute(
        "UPDATE agenda_wa_usuarios SET morning_digest_hora=?, alert_antecedencias=? "
        "WHERE id=? AND empresa_id=?",
        (body.morning_digest_hora or None,
         _json.dumps(antecedencias),
         uid, empresa_id),
    )
    await db.commit()
    return {"ok": True}


@router.delete("/agenda-wa-usuarios/{uid}")
async def delete_agenda_wa_usuario(
    uid: int,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    await db.execute(
        "DELETE FROM agenda_wa_usuarios WHERE id=? AND empresa_id=?",
        (uid, empresa_id),
    )
    await db.commit()
    return {"ok": True}


# ── Sessões WA — configuração de propósito ───────────────────────────────────

_USOS_VALIDOS = {"chatbot", "campanhas", "arquivos", "agenda", "pdv"}


class SessaoUsoPayload(BaseModel):
    usos: list


@router.get("/sessao-usos/{sessao_id}")
async def get_sessao_usos(
    sessao_id: str,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT usos FROM sessoes_wa WHERE empresa_id=? AND id=?",
        (empresa_id, sessao_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Sessão não encontrada")
    try:
        usos = _json.loads(row["usos"] or "[]")
    except Exception:
        usos = ["chatbot", "campanhas", "arquivos", "agenda"]
    return {"usos": usos}


@router.put("/sessao-usos/{sessao_id}")
async def set_sessao_usos(
    sessao_id: str,
    body: SessaoUsoPayload,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    usos = [u for u in body.usos if u in _USOS_VALIDOS]
    await db.execute(
        "UPDATE sessoes_wa SET usos=? WHERE empresa_id=? AND id=?",
        (_json.dumps(usos), empresa_id, sessao_id),
    )
    await db.commit()
    return {"ok": True, "usos": usos}
