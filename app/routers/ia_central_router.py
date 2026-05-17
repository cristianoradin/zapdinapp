"""
app/routers/ia_central_router.py — IA Central (sem function calling).

Abordagem: detecta intenção na pergunta → busca dados no banco → injeta contexto →
uma única chamada ao modelo. Evita erros de tool_use e consome poucos tokens.
"""
from __future__ import annotations
import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.database import get_db
from ..core.security import get_current_user
from ..core.config import settings

router = APIRouter(prefix="/api/ia-central", tags=["ia-central"])
logger = logging.getLogger(__name__)


# ── Detecção de intenção ──────────────────────────────────────────────────────

def _detectar_intencoes(msg: str) -> dict:
    m = msg.lower()
    def _has(*words): return any(w in m for w in words)

    periodo = "mes"
    if _has("hoje"):            periodo = "hoje"
    elif _has("ontem"):         periodo = "ontem"
    elif _has("semana"):        periodo = "semana"
    elif _has("mês passado", "mes passado", "mês anterior"): periodo = "mes_passado"

    return {
        "envios":    _has("envio", "mensagem", "enviou", "disparo", "hoje", "ontem", "semana"),
        "chatbot":   _has("chatbot", "atendimento", "conversa", "bot", "cliente respondeu"),
        "campanhas": _has("campanha", "disparo", "lista", "em massa"),
        "sessoes":   _has("sessão", "sessao", "whatsapp", "número", "numero", "conectad"),
        "contatos":  _has("contato", "cliente", "base", "lista"),
        "memoria":   _has("memória", "memoria", "aprendizado", "conhecimento"),
        "grafico":   _has("gráfico", "grafico", "mostrar", "visual", "comparar", "evolução"),
        "resumo":    _has("resumo", "geral", "overview", "tudo", "panorama"),
        "periodo":   periodo,
    }


# ── Date filter (PostgreSQL) ──────────────────────────────────────────────────

def _date_filter(periodo: str) -> str:
    return {
        "hoje":        "created_at::date = CURRENT_DATE",
        "ontem":       "created_at::date = CURRENT_DATE - INTERVAL '1 day'",
        "semana":      "created_at >= NOW() - INTERVAL '7 days'",
        "mes":         "DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW())",
        "mes_passado": "DATE_TRUNC('month', created_at) = DATE_TRUNC('month', NOW() - INTERVAL '1 month')",
    }.get(periodo, "created_at::date = CURRENT_DATE")


# ── Fetchers de dados ─────────────────────────────────────────────────────────

async def _fetch_envios(db, empresa_id: int, periodo: str) -> dict:
    where = _date_filter(periodo)
    async with db.execute(
        f"""SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status='sent'  THEN 1 ELSE 0 END) AS enviados,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS falhas,
                   SUM(CASE WHEN status IN ('queued','pending') THEN 1 ELSE 0 END) AS pendentes
            FROM campanha_envios WHERE empresa_id=? AND {where}""",
        (empresa_id,)
    ) as cur:
        r = await cur.fetchone()

    breakdown = []
    if periodo in ("semana", "mes", "mes_passado"):
        async with db.execute(
            f"""SELECT created_at::date AS dia,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status='sent'   THEN 1 ELSE 0 END) AS enviados,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS falhas
                FROM campanha_envios WHERE empresa_id=? AND {where}
                GROUP BY created_at::date ORDER BY dia""",
            (empresa_id,)
        ) as cur:
            rows = await cur.fetchall()
        breakdown = [{"dia": str(d["dia"]), "enviados": d["enviados"] or 0,
                      "falhas": d["falhas"] or 0} for d in rows]

    return {"total": r["total"] or 0, "enviados": r["enviados"] or 0,
            "falhas": r["falhas"] or 0, "pendentes": r["pendentes"] or 0,
            "periodo": periodo, "breakdown": breakdown}


async def _fetch_chatbot(db, empresa_id: int, periodo: str) -> dict:
    where = _date_filter(periodo)
    async with db.execute(
        f"""SELECT COUNT(*) AS total_msgs,
                   SUM(CASE WHEN role='user' THEN 1 ELSE 0 END) AS msgs_usuario,
                   SUM(CASE WHEN role='assistant' THEN 1 ELSE 0 END) AS msgs_bot,
                   COUNT(DISTINCT phone) AS contatos_unicos
            FROM chat_historico WHERE empresa_id=? AND {where}""",
        (empresa_id,)
    ) as cur:
        r = await cur.fetchone()
    return {"total_msgs": r["total_msgs"] or 0, "msgs_usuario": r["msgs_usuario"] or 0,
            "msgs_bot": r["msgs_bot"] or 0, "contatos_unicos": r["contatos_unicos"] or 0,
            "periodo": periodo}


async def _fetch_campanhas(db, empresa_id: int) -> dict:
    async with db.execute(
        """SELECT c.nome, c.status,
                  COUNT(e.id) AS total_envios,
                  SUM(CASE WHEN e.status='sent'   THEN 1 ELSE 0 END) AS enviados,
                  SUM(CASE WHEN e.status='failed' THEN 1 ELSE 0 END) AS falhas
           FROM campanhas c
           LEFT JOIN campanha_envios e ON e.campanha_id = c.id
           WHERE c.empresa_id=?
           GROUP BY c.id, c.nome, c.status
           ORDER BY c.created_at DESC LIMIT 8""",
        (empresa_id,)
    ) as cur:
        rows = await cur.fetchall()
    return {"campanhas": [{"nome": r["nome"], "status": r["status"],
                           "enviados": r["enviados"] or 0, "falhas": r["falhas"] or 0,
                           "total": r["total_envios"] or 0} for r in rows]}


async def _fetch_sessoes(empresa_id: int) -> dict:
    try:
        from ..services.evolution_service import evo_manager
        sessoes = evo_manager.get_status(empresa_id)
        return {
            "conectadas": [s for s in sessoes if s.get("status") == "connected"],
            "desconectadas": [s for s in sessoes if s.get("status") != "connected"],
        }
    except Exception as e:
        return {"erro": str(e), "conectadas": [], "desconectadas": []}


async def _fetch_contatos(db, empresa_id: int) -> dict:
    async with db.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN ativo = TRUE  THEN 1 ELSE 0 END) AS ativos,
                  SUM(CASE WHEN ativo = FALSE THEN 1 ELSE 0 END) AS inativos,
                  SUM(CASE WHEN origem='erp'     THEN 1 ELSE 0 END) AS erp,
                  SUM(CASE WHEN origem='chatbot' THEN 1 ELSE 0 END) AS chatbot,
                  SUM(CASE WHEN origem='manual'  THEN 1 ELSE 0 END) AS manual
           FROM contatos WHERE empresa_id=?""",
        (empresa_id,)
    ) as cur:
        r = await cur.fetchone()
    return {"total": r["total"] or 0, "ativos": r["ativos"] or 0,
            "inativos": r["inativos"] or 0,
            "por_origem": {"erp": r["erp"] or 0, "chatbot": r["chatbot"] or 0,
                           "manual": r["manual"] or 0}}


async def _fetch_memoria(db, empresa_id: int) -> dict:
    async with db.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN aprovado = TRUE  THEN 1 ELSE 0 END) AS aprovadas,
                  SUM(CASE WHEN aprovado IS NULL  THEN 1 ELSE 0 END) AS pendentes,
                  COALESCE(SUM(usos), 0) AS total_usos
           FROM chatbot_memoria_ia WHERE empresa_id=?""",
        (empresa_id,)
    ) as cur:
        r = await cur.fetchone()
    return {"total": r["total"] or 0, "aprovadas": r["aprovadas"] or 0,
            "pendentes": r["pendentes"] or 0, "total_usos": r["total_usos"] or 0}


# ── Monta contexto de dados para o modelo ────────────────────────────────────

async def _coletar_contexto(intencoes: dict, db, empresa_id: int) -> tuple[str, dict | None]:
    """Retorna (texto_contexto, chart_data_ou_None)."""
    partes = []
    chart = None
    p = intencoes["periodo"]

    # Resumo geral busca tudo
    if intencoes["resumo"]:
        intencoes = {k: True for k in intencoes}
        intencoes["periodo"] = p

    try:
        if intencoes["envios"]:
            d = await _fetch_envios(db, empresa_id, p)
            partes.append(
                f"ENVIOS ({p.upper()}): total={d['total']} | enviados={d['enviados']} "
                f"| falhas={d['falhas']} | pendentes={d['pendentes']}"
            )
            if intencoes["grafico"] and d["breakdown"]:
                labels = [b["dia"] for b in d["breakdown"]]
                valores = [b["enviados"] for b in d["breakdown"]]
                chart = _make_chart("bar", f"Envios por dia ({p})", labels, valores, "#3d7f1f")
            elif intencoes["grafico"] and d["total"] > 0:
                chart = _make_chart("doughnut", f"Envios ({p})",
                                    ["Enviados", "Falhas", "Pendentes"],
                                    [d["enviados"], d["falhas"], d["pendentes"]],
                                    "#3d7f1f")

        if intencoes["chatbot"]:
            d = await _fetch_chatbot(db, empresa_id, p)
            partes.append(
                f"CHATBOT ({p.upper()}): mensagens={d['total_msgs']} | "
                f"usuário={d['msgs_usuario']} | bot={d['msgs_bot']} | "
                f"contatos únicos={d['contatos_unicos']}"
            )

        if intencoes["campanhas"]:
            d = await _fetch_campanhas(db, empresa_id)
            linhas = [f"  - {c['nome']} ({c['status']}): {c['enviados']}/{c['total']} enviados, {c['falhas']} falhas"
                      for c in d["campanhas"]]
            partes.append("CAMPANHAS RECENTES:\n" + "\n".join(linhas) if linhas else "CAMPANHAS: nenhuma")
            if intencoes["grafico"] and d["campanhas"]:
                chart = _make_chart("bar", "Envios por Campanha",
                                    [c["nome"][:20] for c in d["campanhas"]],
                                    [c["enviados"] for c in d["campanhas"]], "#3b82f6")

        if intencoes["sessoes"]:
            d = await _fetch_sessoes(empresa_id)
            con = [s.get("nome", s.get("id", "?")) for s in d["conectadas"]]
            des = [s.get("nome", s.get("id", "?")) for s in d["desconectadas"]]
            partes.append(
                f"SESSÕES WA: {len(con)} conectadas {con} | {len(des)} desconectadas {des}"
            )

        if intencoes["contatos"]:
            d = await _fetch_contatos(db, empresa_id)
            partes.append(
                f"CONTATOS: total={d['total']} | ativos={d['ativos']} | inativos={d['inativos']} "
                f"| ERP={d['por_origem']['erp']} | chatbot={d['por_origem']['chatbot']} | manual={d['por_origem']['manual']}"
            )

        if intencoes["memoria"]:
            d = await _fetch_memoria(db, empresa_id)
            partes.append(
                f"MEMÓRIA IA: total={d['total']} | aprovadas={d['aprovadas']} "
                f"| pendentes={d['pendentes']} | usos={d['total_usos']}"
            )

    except Exception as e:
        logger.error("[ia_central] Erro ao coletar contexto: %s", e, exc_info=True)
        partes.append(f"(erro ao buscar dados: {e})")

    ctx = "\n".join(partes)
    return ctx, chart


def _make_chart(tipo: str, titulo: str, labels: list, valores: list, cor: str) -> dict:
    cores = ["#3d7f1f", "#7cdc44", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"]
    bg = cores[:len(labels)] if tipo in ("pie", "doughnut") else cor
    return {
        "type": tipo,
        "data": {
            "labels": labels,
            "datasets": [{"label": titulo, "data": valores,
                          "backgroundColor": bg, "borderColor": cor,
                          "borderWidth": 2, "fill": False, "tension": 0.3}]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "legend": {"display": tipo in ("pie", "doughnut")},
                "title": {"display": True, "text": titulo, "font": {"size": 13, "weight": "bold"}}
            },
            "scales": {} if tipo in ("pie", "doughnut") else {"y": {"beginAtZero": True}}
        }
    }


# ── Chamada ao modelo (sem function calling) ──────────────────────────────────

async def _call_groq(messages: list, api_key: str) -> str:
    import asyncio as _asyncio
    for attempt in range(3):
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": messages,
                    "max_tokens": 800,
                    "temperature": 0.3,
                },
            )
        if r.status_code == 429:
            wait = min(int(r.headers.get("retry-after", 8)), 15)
            logger.warning("[ia_central] Groq 429 — aguardando %ss (tentativa %d/3)", wait, attempt + 1)
            await _asyncio.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    raise Exception("Rate limit Groq — tente novamente em alguns segundos.")


# ── Endpoint ──────────────────────────────────────────────────────────────────

class ChatBody(BaseModel):
    mensagem: str
    historico: list = []


@router.post("/chat")
async def ia_central_chat(
    body: ChatBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    api_key = getattr(settings, "groq_api_key", None) or ""
    if not api_key:
        raise HTTPException(400, "Chave Groq não configurada. Acesse Configurações → Integrações de IA → Groq.")

    empresa_id = user["empresa_id"]
    msg = body.mensagem.strip()

    # 1. Detecta intenção e coleta dados do banco
    intencoes = _detectar_intencoes(msg)
    contexto, chart = await _coletar_contexto(intencoes, db, empresa_id)

    # 2. Monta messages para o modelo
    system = (
        "Você é a IA Central do ZapDin (automação WhatsApp). "
        "Responda em português, seja direto e objetivo. "
        "Formate números com separadores de milhar (1.234). "
        "Use os DADOS DO SISTEMA abaixo para responder com precisão.\n\n"
    )
    if contexto:
        system += f"DADOS DO SISTEMA:\n{contexto}\n"

    messages = [{"role": "system", "content": system}]
    for h in body.historico[-8:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": msg})

    # 3. Chama o modelo
    try:
        resposta = await _call_groq(messages, api_key)
    except httpx.HTTPStatusError as e:
        logger.error("[ia_central] Groq HTTP error: %s", e.response.text)
        if e.response.status_code == 401:
            raise HTTPException(400, "Chave Groq inválida. Verifique em Configurações → Integrações de IA.")
        raise HTTPException(502, f"Erro na IA: {e.response.status_code}")
    except Exception as e:
        logger.error("[ia_central] Erro: %s", e, exc_info=True)
        raise HTTPException(500, str(e))

    return {"resposta": resposta, "chart": chart}
