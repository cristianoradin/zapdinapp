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

# Grupo de agente compartilhado: empresa_id → empresa DONA do agente.
# Quando uma empresa usa o número de outra, seus comandos WS (send/qr/state) são
# roteados pro agente da dona. Populado periodicamente do banco (empresas.agente_dono_empresa_id).
_owner_map: Dict[int, int] = {}


def set_owner_map(mapping: Dict[int, int]) -> None:
    """Atualiza o mapa de agente compartilhado. {empresa_id: dona_empresa_id}.
    Ignora auto-referência (empresa apontando pra si mesma)."""
    global _owner_map
    _owner_map = {int(k): int(v) for k, v in (mapping or {}).items() if v and int(v) != int(k)}


def _eff(empresa_id: int) -> int:
    """Resolve a empresa cujo agente deve ser usado (transporte compartilhado)."""
    return _owner_map.get(empresa_id, empresa_id)


def get_agent(empresa_id: int) -> Optional[dict]:
    """Retorna info do agente conectado pra empresa (resolve dona), ou None."""
    return _agents.get(_eff(empresa_id))


def has_agent(empresa_id: int) -> bool:
    return _eff(empresa_id) in _agents


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
    # Resolve agente compartilhado (empresa pode usar o número de uma dona)
    eff = _eff(empresa_id)
    agent = _agents.get(eff)
    if not agent:
        extra = f" (dona {eff})" if eff != empresa_id else ""
        raise RuntimeError(f"Agente da empresa {empresa_id}{extra} não está conectado")
    sid = agent["sid"]

    # Socket.IO call() (request/response com timeout).
    # IMPORTANTE: o timeout INTERNO do sio.call() NÃO dispara de forma confiável em
    # certas condições (agente ACKa parcial / loop ocupado) → o await trava pra sempre
    # e o WORKER PARA (loop single-thread bloqueado num envio). asyncio.wait_for é um
    # teto RÍGIDO que SEMPRE libera o await, garantindo que o worker nunca congela.
    try:
        result = await asyncio.wait_for(
            sio.call(
                command,
                {"command": command, "payload": payload},
                to=sid,
                namespace="/agent",
                timeout=timeout,
            ),
            timeout=timeout + 5,
        )
    except asyncio.TimeoutError:
        raise RuntimeError(f"Timeout ({timeout:.0f}s) no comando '{command}' — agente empresa={empresa_id} não respondeu a tempo")
    except Exception as exc:
        # socketio.exceptions.TimeoutError NÃO é asyncio.TimeoutError e tem str() vazio.
        import socketio as _sio_mod
        if isinstance(exc, getattr(_sio_mod.exceptions, "TimeoutError", ())):
            raise RuntimeError(f"Timeout ({timeout:.0f}s) no comando '{command}' — agente empresa={empresa_id} não respondeu a tempo")
        raise RuntimeError(f"Erro no comando '{command}': {type(exc).__name__}: {exc}")

    if not isinstance(result, dict):
        return {"ok": False, "error": "Resposta inválida do agente"}
    return result
