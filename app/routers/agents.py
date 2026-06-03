"""
app/routers/agents.py — Endpoints REST adicionais de gestão de agentes.

NOTA: GET /api/agents já existe em app/main.py:408 (lista da empresa logada).
Aqui ficam endpoints admin + métricas + ativação:

  POST /api/agents/activate — público: valida token + retorna empresa (instalador)
  GET  /api/agents/all      — admin-only: lista TODOS os agentes (header X-Monitor-Token)
  GET  /metrics             — métricas Prometheus (texto plain) — público
"""
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.database import get_db_direct
from ..services import agent_bridge

router = APIRouter(tags=["agents"])


# ── Ativação do instalador ───────────────────────────────────────────────────

class ActivatePayload(BaseModel):
    token: str = Field(min_length=8, max_length=256)


@router.post("/api/agents/activate")
async def activate_agent(body: ActivatePayload):
    """
    Valida token contra empresas.token e retorna empresa.
    Usado pelo instalador do agente pra dar feedback antes de gravar .env.
    Não cria sessão — apenas valida + retorna info da empresa.
    """
    token = body.token.strip()
    try:
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT id, nome, cnpj, ativo FROM empresas WHERE token = ? LIMIT 1",
                (token,),
            ) as cur:
                row = await cur.fetchone()
    except Exception as exc:
        raise HTTPException(503, f"Erro ao consultar banco: {exc}")

    if not row:
        raise HTTPException(401, "Token inválido. Verifique o token no painel ZapDin.")
    if not row["ativo"]:
        raise HTTPException(403, "Empresa inativa. Contate o suporte.")

    return {
        "ok": True,
        "empresa_id": row["id"],
        "empresa_nome": row["nome"] or "",
        "cnpj": row["cnpj"] or "",
    }


@router.get("/api/agents/all")
async def list_all_agents(
    x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token"),
):
    """Admin: lista TODOS os agentes conectados (cross-empresa). Auth: token do monitor."""
    expected = settings.monitor_client_token
    if not expected or not x_monitor_token or x_monitor_token != expected:
        raise HTTPException(401, "X-Monitor-Token inválido")
    now = time.time()
    agents = []
    for ag in agent_bridge.list_agents():
        agents.append({
            **ag,
            "seconds_since_last_seen": round(now - (ag.get("last_seen") or 0), 1),
        })
    return {"total": len(agents), "agents": agents}


# ── Prometheus metrics ───────────────────────────────────────────────────────

@router.get("/metrics")
async def prometheus_metrics():
    """Métricas Prometheus em formato text/plain."""
    now = time.time()
    agents = agent_bridge.list_agents()

    lines = []

    # Total de agentes conectados
    lines.append("# HELP zapdin_agents_connected Total de agentes WebSocket atualmente conectados.")
    lines.append("# TYPE zapdin_agents_connected gauge")
    lines.append(f"zapdin_agents_connected {len(agents)}")

    # Por agente: segundos desde último heartbeat
    lines.append("")
    lines.append("# HELP zapdin_agent_seconds_since_last_seen Segundos desde último heartbeat por empresa.")
    lines.append("# TYPE zapdin_agent_seconds_since_last_seen gauge")
    for ag in agents:
        eid = ag.get("empresa_id")
        ver = (ag.get("version") or "?").replace('"', '\\"')
        sec = round(now - (ag.get("last_seen") or 0), 1)
        lines.append(
            f'zapdin_agent_seconds_since_last_seen{{empresa_id="{eid}",version="{ver}"}} {sec}'
        )

    # Uptime do agente (segundos desde connected_at)
    lines.append("")
    lines.append("# HELP zapdin_agent_uptime_seconds Tempo desde connect inicial por empresa.")
    lines.append("# TYPE zapdin_agent_uptime_seconds gauge")
    for ag in agents:
        eid = ag.get("empresa_id")
        ver = (ag.get("version") or "?").replace('"', '\\"')
        up = round(now - (ag.get("connected_at") or now), 1)
        lines.append(
            f'zapdin_agent_uptime_seconds{{empresa_id="{eid}",version="{ver}"}} {up}'
        )

    body = "\n".join(lines) + "\n"
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
