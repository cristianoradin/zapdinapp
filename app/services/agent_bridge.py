"""
agent_bridge.py — Ponte WebSocket entre servidor e agentes locais (modo híbrido).

Cada cliente do posto roda o "ZapDin Agent" que conecta aqui via Socket.IO
namespace '/agent'. Permite o servidor enviar comandos (send_text, send_media,
get_qr) atravessando NAT/firewall do cliente.

Fluxo:
  1. Agente conecta com auth_data={"token": <client_token>}
  2. Servidor valida o token na tabela empresas
  3. Agente recebe sid; servidor mantém registry {empresa_id: sid}
  4. Servidor emite evento "command" ao sid; agente responde via ACK ou outro evento

Tabela `agent_sessions` opcional para audit (heartbeats persistentes).
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Registry em memória: empresa_id → {sid, connected_at, last_seen, info}
_agents: Dict[int, dict] = {}
_sid_to_empresa: Dict[str, int] = {}


def get_agent(empresa_id: int) -> Optional[dict]:
    """Retorna info do agente conectado pra empresa, ou None."""
    return _agents.get(empresa_id)


def has_agent(empresa_id: int) -> bool:
    return empresa_id in _agents


def list_agents() -> list[dict]:
    return [
        {"empresa_id": eid, **info}
        for eid, info in _agents.items()
    ]


async def _resolve_empresa_by_token(db_pool, token: str) -> Optional[int]:
    """Valida token e retorna empresa_id correspondente."""
    if not token or len(token) < 8:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM empresas WHERE token = $1 AND ativo = TRUE", token
        )
    return row["id"] if row else None


def register_agent(empresa_id: int, sid: str, info: dict) -> None:
    """Registra agente conectado. Substitui se já existia (reconnect)."""
    # Se já tinha agente antigo, marca pra desconectar depois
    old = _agents.get(empresa_id)
    if old and old.get("sid") and old["sid"] != sid:
        logger.info("[agent] Empresa %s reconectou; sid antigo %s será descartado", empresa_id, old["sid"])
        _sid_to_empresa.pop(old["sid"], None)
    _agents[empresa_id] = {
        "sid": sid,
        "connected_at": time.time(),
        "last_seen": time.time(),
        **info,
    }
    _sid_to_empresa[sid] = empresa_id
    logger.info("[agent] Agente registrado: empresa=%s sid=%s versão=%s",
                empresa_id, sid, info.get("version", "?"))


def unregister_by_sid(sid: str) -> Optional[int]:
    """Remove agente desconectado. Retorna empresa_id removida (ou None)."""
    empresa_id = _sid_to_empresa.pop(sid, None)
    if empresa_id is not None:
        cur = _agents.get(empresa_id)
        if cur and cur.get("sid") == sid:
            # Telemetria: quanto tempo ficou conectado + há quanto não dava heartbeat
            uptime = round(time.time() - cur.get("connected_at", time.time()))
            since_hb = round(time.time() - cur.get("last_seen", time.time()))
            _agents.pop(empresa_id, None)
            logger.info(
                "[agent] Agente desconectado: empresa=%s sid=%s uptime=%ss ultimo_heartbeat=há_%ss",
                empresa_id, sid, uptime, since_hb,
            )
    return empresa_id


def touch(sid: str) -> None:
    """Atualiza last_seen do agente (heartbeat)."""
    empresa_id = _sid_to_empresa.get(sid)
    if empresa_id is not None and empresa_id in _agents:
        _agents[empresa_id]["last_seen"] = time.time()


# ── Comandos do servidor → agente ────────────────────────────────────────────

async def send_command(sio, empresa_id: int, command: str, payload: dict,
                       timeout: float = 30.0) -> dict:
    """
    Envia comando ao agente e aguarda resposta (ACK callback).
    Lança RuntimeError se agente offline ou timeout.

    Comandos suportados pelo agente:
      - "send_text"   payload={instance, number, text, delay_ms}
      - "send_media"  payload={instance, number, mediatype, mimetype, media_b64, filename, caption}
      - "get_qr"      payload={instance}
      - "get_state"   payload={instance}
      - "create_instance"  payload={instance, nome}
      - "delete_instance"  payload={instance}
    """
    agent = _agents.get(empresa_id)
    if not agent:
        raise RuntimeError(f"Agente da empresa {empresa_id} não está conectado")
    sid = agent["sid"]

    # Socket.IO call() (request/response com timeout)
    try:
        result = await sio.call(
            command,
            {"command": command, "payload": payload},
            to=sid,
            namespace="/agent",
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise RuntimeError(f"Timeout no comando '{command}' para agente empresa={empresa_id}")
    except Exception as exc:
        raise RuntimeError(f"Erro no comando '{command}': {exc}")

    if not isinstance(result, dict):
        return {"ok": False, "error": "Resposta inválida do agente"}
    return result
