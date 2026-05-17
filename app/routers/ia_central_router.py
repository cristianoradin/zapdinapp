"""
app/routers/ia_central_router.py — IA Central com agentes e sub-agentes.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.database import get_db
from ..core.security import get_current_user
from ..core.config import settings

router = APIRouter(prefix="/api/ia-central", tags=["ia-central"])
logger = logging.getLogger(__name__)

# ── System Prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Você é o assistente IA Central do ZapDin — plataforma de automação WhatsApp com campanhas em massa, chatbot IA, integração ERP e gestão de sessões WhatsApp.

SOBRE O SISTEMA:
- Campanhas: envio em massa de mensagens WhatsApp para listas de contatos
- Chatbot IA: atendimento automático com IA para mensagens recebidas
- Sessões WhatsApp: múltiplos números conectados simultaneamente via Evolution API
- ERP: integração com sistemas externos para confirmação de vendas
- Contatos: base de clientes com histórico completo
- Memória IA: base de conhecimento gerada automaticamente pelos atendimentos

INSTRUÇÕES:
- Responda SEMPRE em português brasileiro
- Use as funções disponíveis para buscar dados reais do banco
- Formate números com separadores (ex: 1.234 não 1234)
- Quando tiver dados numéricos comparativos, SEMPRE chame gerar_grafico para visualizar
- Seja direto e objetivo nas respostas
- Quando não souber algo, diga claramente
"""

# ── Ferramentas (Agentes) ─────────────────────────────────────────────────────

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_envios",
            "description": "Consulta estatísticas de envios de mensagens das campanhas: total, enviados com sucesso, falhas, pendentes. Use para perguntas sobre quantas mensagens foram enviadas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "periodo": {
                        "type": "string",
                        "enum": ["hoje", "ontem", "semana", "mes", "mes_passado"],
                        "description": "Período de consulta"
                    }
                },
                "required": ["periodo"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_chatbot",
            "description": "Consulta estatísticas do chatbot: total de conversas, mensagens trocadas, contatos únicos atendidos pela IA.",
            "parameters": {
                "type": "object",
                "properties": {
                    "periodo": {
                        "type": "string",
                        "enum": ["hoje", "ontem", "semana", "mes", "mes_passado"],
                        "description": "Período de consulta"
                    }
                },
                "required": ["periodo"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_sessoes",
            "description": "Retorna status atual de todas as sessões WhatsApp: quais números estão conectados, desconectados ou com erro.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_campanhas",
            "description": "Lista campanhas com seus status e estatísticas de envio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["todas", "done", "running", "paused", "queued"],
                        "description": "Filtrar por status"
                    },
                    "limite": {
                        "type": "integer",
                        "description": "Máximo de campanhas a retornar (padrão 10)"
                    }
                },
                "required": ["status"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_contatos",
            "description": "Estatísticas da base de contatos: total, ativos, inativos, por origem (manual, ERP, chatbot).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_memoria_ia",
            "description": "Estatísticas da memória IA: entradas aprovadas, pendentes, total de usos acumulados.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "gerar_grafico",
            "description": "Gera um gráfico visual para exibir no chat. Use sempre que tiver dados numéricos para comparar ou mostrar evolução.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {
                        "type": "string",
                        "enum": ["bar", "line", "pie", "doughnut"],
                        "description": "Tipo do gráfico"
                    },
                    "titulo": {
                        "type": "string",
                        "description": "Título do gráfico"
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Rótulos (eixo X ou fatias)"
                    },
                    "valores": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Valores numéricos"
                    },
                    "cor": {
                        "type": "string",
                        "description": "Cor principal em hex (padrão #3d7f1f)"
                    }
                },
                "required": ["tipo", "titulo", "labels", "valores"]
            }
        }
    }
]

# ── Executores das funções ────────────────────────────────────────────────────

def _date_filter(periodo: str) -> str:
    return {
        "hoje":        "DATE(created_at) = DATE('now')",
        "ontem":       "DATE(created_at) = DATE('now', '-1 day')",
        "semana":      "created_at >= DATE('now', '-7 days')",
        "mes":         "strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')",
        "mes_passado": "strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now', '-1 month')",
    }.get(periodo, "DATE(created_at) = DATE('now')")


async def _exec_consultar_envios(db, empresa_id: int, periodo: str) -> dict:
    where = _date_filter(periodo)
    async with db.execute(
        f"""SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS enviados,
              SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS falhas,
              SUM(CASE WHEN status IN ('queued','pending') THEN 1 ELSE 0 END) AS pendentes
            FROM campanha_envios
            WHERE empresa_id=? AND {where}""",
        (empresa_id,)
    ) as cur:
        r = await cur.fetchone()

    breakdown = []
    if periodo in ("semana", "mes", "mes_passado"):
        async with db.execute(
            f"""SELECT DATE(created_at) AS dia,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS enviados,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS falhas
                FROM campanha_envios
                WHERE empresa_id=? AND {where}
                GROUP BY DATE(created_at) ORDER BY dia""",
            (empresa_id,)
        ) as cur:
            rows = await cur.fetchall()
        breakdown = [{"dia": str(d["dia"]), "total": d["total"],
                      "enviados": d["enviados"], "falhas": d["falhas"]} for d in rows]

    return {"total": r["total"] or 0, "enviados": r["enviados"] or 0,
            "falhas": r["falhas"] or 0, "pendentes": r["pendentes"] or 0,
            "periodo": periodo, "breakdown_diario": breakdown}


async def _exec_consultar_chatbot(db, empresa_id: int, periodo: str) -> dict:
    where = _date_filter(periodo)
    async with db.execute(
        f"""SELECT
              COUNT(*) AS total_msgs,
              SUM(CASE WHEN role='user' THEN 1 ELSE 0 END) AS msgs_usuario,
              SUM(CASE WHEN role='assistant' THEN 1 ELSE 0 END) AS msgs_bot,
              COUNT(DISTINCT phone) AS contatos_unicos
            FROM chat_historico
            WHERE empresa_id=? AND {where}""",
        (empresa_id,)
    ) as cur:
        r = await cur.fetchone()

    breakdown = []
    if periodo in ("semana", "mes", "mes_passado"):
        async with db.execute(
            f"""SELECT DATE(created_at) AS dia,
                       COUNT(DISTINCT phone) AS contatos,
                       SUM(CASE WHEN role='user' THEN 1 ELSE 0 END) AS msgs_usuario
                FROM chat_historico
                WHERE empresa_id=? AND {where}
                GROUP BY DATE(created_at) ORDER BY dia""",
            (empresa_id,)
        ) as cur:
            rows = await cur.fetchall()
        breakdown = [{"dia": str(d["dia"]), "contatos": d["contatos"],
                      "msgs": d["msgs_usuario"]} for d in rows]

    return {"total_msgs": r["total_msgs"] or 0, "msgs_usuario": r["msgs_usuario"] or 0,
            "msgs_bot": r["msgs_bot"] or 0, "contatos_unicos": r["contatos_unicos"] or 0,
            "periodo": periodo, "breakdown_diario": breakdown}


async def _exec_consultar_sessoes(empresa_id: int) -> dict:
    try:
        from ..services.evolution_service import evo_manager
        sessoes = evo_manager.get_status(empresa_id)
        return {
            "total": len(sessoes),
            "conectadas": sum(1 for s in sessoes if s.get("status") == "connected"),
            "desconectadas": sum(1 for s in sessoes if s.get("status") != "connected"),
            "sessoes": [{"id": s.get("id"), "nome": s.get("nome"),
                         "status": s.get("status"), "phone": s.get("phone")} for s in sessoes]
        }
    except Exception as e:
        return {"erro": str(e), "total": 0, "conectadas": 0, "desconectadas": 0, "sessoes": []}


async def _exec_consultar_campanhas(db, empresa_id: int, status: str, limite: int) -> dict:
    where = "WHERE c.empresa_id=?"
    params: list = [empresa_id]
    if status != "todas":
        where += " AND c.status=?"
        params.append(status)
    async with db.execute(
        f"""SELECT c.id, c.nome, c.status, c.created_at,
                   COUNT(e.id) AS total_envios,
                   SUM(CASE WHEN e.status='sent' THEN 1 ELSE 0 END) AS enviados,
                   SUM(CASE WHEN e.status='failed' THEN 1 ELSE 0 END) AS falhas
            FROM campanhas c
            LEFT JOIN campanha_envios e ON e.campanha_id = c.id
            {where}
            GROUP BY c.id, c.nome, c.status, c.created_at
            ORDER BY c.created_at DESC LIMIT ?""",
        tuple(params) + (limite,)
    ) as cur:
        rows = await cur.fetchall()
    return {
        "total": len(rows),
        "campanhas": [{"id": r["id"], "nome": r["nome"], "status": r["status"],
                       "total_envios": r["total_envios"], "enviados": r["enviados"] or 0,
                       "falhas": r["falhas"] or 0} for r in rows]
    }


async def _exec_consultar_contatos(db, empresa_id: int) -> dict:
    async with db.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN ativo=1 THEN 1 ELSE 0 END) AS ativos,
             SUM(CASE WHEN ativo=0 THEN 1 ELSE 0 END) AS inativos,
             SUM(CASE WHEN origem='manual' THEN 1 ELSE 0 END) AS manual,
             SUM(CASE WHEN origem='erp' THEN 1 ELSE 0 END) AS erp,
             SUM(CASE WHEN origem='chatbot' THEN 1 ELSE 0 END) AS chatbot
           FROM contatos WHERE empresa_id=?""",
        (empresa_id,)
    ) as cur:
        r = await cur.fetchone()
    return {"total": r["total"] or 0, "ativos": r["ativos"] or 0,
            "inativos": r["inativos"] or 0,
            "por_origem": {"manual": r["manual"] or 0, "erp": r["erp"] or 0,
                           "chatbot": r["chatbot"] or 0}}


async def _exec_consultar_memoria_ia(db, empresa_id: int) -> dict:
    async with db.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN aprovado=1 THEN 1 ELSE 0 END) AS aprovadas,
                  SUM(CASE WHEN aprovado IS NULL THEN 1 ELSE 0 END) AS pendentes,
                  SUM(CASE WHEN aprovado=0 THEN 1 ELSE 0 END) AS rejeitadas,
                  COALESCE(SUM(usos),0) AS total_usos
           FROM chatbot_memoria_ia WHERE empresa_id=?""",
        (empresa_id,)
    ) as cur:
        r = await cur.fetchone()
    return {"total": r["total"] or 0, "aprovadas": r["aprovadas"] or 0,
            "pendentes": r["pendentes"] or 0, "rejeitadas": r["rejeitadas"] or 0,
            "total_usos": r["total_usos"] or 0}


def _exec_gerar_grafico(tipo: str, titulo: str, labels: list,
                         valores: list, cor: str = "#3d7f1f") -> dict:
    """Retorna config Chart.js para renderizar no frontend."""
    cores_palette = [
        "#3d7f1f", "#7cdc44", "#3b82f6", "#f59e0b",
        "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899"
    ]
    if tipo in ("pie", "doughnut"):
        bg_colors = cores_palette[:len(labels)]
    else:
        bg_colors = cor

    return {
        "type": tipo,
        "data": {
            "labels": labels,
            "datasets": [{
                "label": titulo,
                "data": valores,
                "backgroundColor": bg_colors,
                "borderColor": cor if tipo == "line" else None,
                "borderWidth": 2,
                "fill": False,
                "tension": 0.3,
            }]
        },
        "options": {
            "responsive": True,
            "plugins": {
                "legend": {"display": tipo in ("pie", "doughnut")},
                "title": {"display": True, "text": titulo,
                          "font": {"size": 13, "weight": "bold"}}
            },
            "scales": {} if tipo in ("pie", "doughnut") else {
                "y": {"beginAtZero": True},
                "x": {}
            }
        }
    }


# ── Dispatcher ────────────────────────────────────────────────────────────────

async def _dispatch_tool(name: str, args: dict, db, empresa_id: int) -> str:
    try:
        if name == "consultar_envios":
            r = await _exec_consultar_envios(db, empresa_id, args.get("periodo", "hoje"))
        elif name == "consultar_chatbot":
            r = await _exec_consultar_chatbot(db, empresa_id, args.get("periodo", "hoje"))
        elif name == "consultar_sessoes":
            r = await _exec_consultar_sessoes(empresa_id)
        elif name == "consultar_campanhas":
            r = await _exec_consultar_campanhas(
                db, empresa_id, args.get("status", "todas"), args.get("limite", 10))
        elif name == "consultar_contatos":
            r = await _exec_consultar_contatos(db, empresa_id)
        elif name == "consultar_memoria_ia":
            r = await _exec_consultar_memoria_ia(db, empresa_id)
        elif name == "gerar_grafico":
            r = _exec_gerar_grafico(
                args.get("tipo", "bar"), args.get("titulo", ""),
                args.get("labels", []), args.get("valores", []),
                args.get("cor", "#3d7f1f"))
        else:
            r = {"erro": f"Função desconhecida: {name}"}
        return json.dumps(r, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("[ia_central] Erro em %s: %s", name, e)
        return json.dumps({"erro": str(e)})


# ── Groq call ─────────────────────────────────────────────────────────────────

async def _call_groq(messages: list, api_key: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": messages,
                "tools": _TOOLS,
                "tool_choice": "auto",
                "max_tokens": 2048,
                "temperature": 0.3,
            }
        )
        r.raise_for_status()
        return r.json()


# ── Endpoint principal ────────────────────────────────────────────────────────

class ChatBody(BaseModel):
    mensagem: str
    historico: list = []   # [{role, content}] das últimas N trocas


@router.post("/chat")
async def ia_central_chat(
    body: ChatBody,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    from fastapi import HTTPException

    api_key = getattr(settings, "groq_api_key", None) or ""
    if not api_key:
        raise HTTPException(400, "Chave Groq não configurada. Acesse Configurações → Integrações de IA → Groq.")

    empresa_id = user["empresa_id"]

    # Monta messages: system + histórico recente + nova pergunta
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    # Inclui até 6 trocas anteriores para contexto
    for h in body.historico[-12:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": body.mensagem.strip()})

    chart_data = None

    try:
        # 1ª chamada ao Groq
        response = await _call_groq(messages, api_key)
        choice = response["choices"][0]

        # Loop de function calling (máx 3 rodadas)
        for _ in range(3):
            if choice.get("finish_reason") != "tool_calls":
                break

            tool_calls = choice["message"].get("tool_calls", [])
            if not tool_calls:
                break

            # Adiciona a mensagem do assistente com tool_calls
            messages.append(choice["message"])

            # Executa cada tool call
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = json.loads(tc["function"].get("arguments", "{}"))
                result  = await _dispatch_tool(fn_name, fn_args, db, empresa_id)

                # Se for gráfico, salva para retornar ao frontend
                if fn_name == "gerar_grafico":
                    try:
                        chart_data = json.loads(result)
                    except Exception:
                        pass

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            # Chama Groq novamente com os resultados
            response = await _call_groq(messages, api_key)
            choice = response["choices"][0]

        resposta = choice["message"].get("content") or "Não consegui gerar uma resposta."

    except httpx.HTTPStatusError as e:
        logger.error("[ia_central] Groq HTTP error: %s", e.response.text)
        if e.response.status_code == 401:
            raise HTTPException(401, "Chave Groq inválida.")
        raise HTTPException(502, f"Erro na IA: {e.response.status_code}")
    except Exception as e:
        logger.error("[ia_central] Erro geral: %s", e, exc_info=True)
        raise HTTPException(500, f"Erro interno: {e}")

    return {"resposta": resposta, "chart": chart_data}
