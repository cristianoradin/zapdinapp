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
from fastapi import APIRouter, Depends
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
