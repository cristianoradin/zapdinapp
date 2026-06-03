"""
test_agent_e2e.py — Smoke test end-to-end do modo agente.

Sobe o app (uvicorn) em porta livre, conecta um socketio.AsyncClient simulando
o agente, verifica:
  1. Conexão aceita (token válido)
  2. agent_bridge registra o agente
  3. Comando do servidor (`send_command`) chega no cliente e a resposta volta
  4. evo_event do cliente chega no servidor (handle_webhook chamado)
  5. Token inválido → connect rejeitado
  6. GET /api/agents lista o agente conectado
"""
import asyncio
import os
import socket
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
import socketio
import uvicorn
from unittest.mock import patch

from app.services import agent_bridge


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@asynccontextmanager
async def _running_server(port: int):
    """Sobe app.main:app via uvicorn em background, aguarda subir."""
    # Configura DATABASE_URL p/ teste
    os.environ["DATABASE_URL"] = os.environ.get(
        "TEST_DATABASE_URL", "postgresql://cristianoradin@localhost/zapdin_test"
    )
    # SECRET_KEY já deve estar setada por app/.env; força um valor estável caso ausente
    os.environ.setdefault("SECRET_KEY", "test-secret-key-e2e-agente")

    config = uvicorn.Config(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    # Espera estar pronto (uvicorn marca .started = True)
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.1)
    if not server.started:
        raise RuntimeError("uvicorn não subiu em 5s")
    try:
        yield port
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)


@pytest_asyncio.fixture
async def live_server():
    port = _free_port()
    async with _running_server(port) as p:
        # Limpa registry antes de cada teste
        agent_bridge._agents.clear()
        agent_bridge._sid_to_empresa.clear()
        yield p
        agent_bridge._agents.clear()
        agent_bridge._sid_to_empresa.clear()


# ─────────────────────────────────────────────────────────────────────────────
#  Testes
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_conecta_e_registra(live_server, empresa_usuario):
    """Agente com token válido conecta, fica registrado em agent_bridge."""
    port = live_server
    client = socketio.AsyncClient()
    welcome_data = {}

    @client.on("welcome", namespace="/agent")
    async def on_welcome(data):
        welcome_data.update(data or {})

    await client.connect(
        f"http://127.0.0.1:{port}",
        auth={"token": "token-teste", "version": "e2e-test"},
        namespaces=["/agent"],
        wait_timeout=5,
    )
    # Pequena espera para o servidor processar e emitir welcome
    await asyncio.sleep(0.3)
    try:
        assert agent_bridge.has_agent(empresa_usuario["empresa_id"])
        info = agent_bridge.get_agent(empresa_usuario["empresa_id"])
        assert info["version"] == "e2e-test"
        assert welcome_data.get("ok") is True
        assert welcome_data.get("empresa_id") == empresa_usuario["empresa_id"]
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_agent_token_invalido_rejeitado(live_server):
    """Token desconhecido → conexão recusada."""
    port = live_server
    client = socketio.AsyncClient()
    with pytest.raises(socketio.exceptions.ConnectionError):
        await client.connect(
            f"http://127.0.0.1:{port}",
            auth={"token": "token-invalido-xxx-yyy"},
            namespaces=["/agent"],
            wait_timeout=3,
        )


@pytest.mark.asyncio
async def test_send_command_round_trip(live_server, empresa_usuario):
    """Servidor envia send_text, agente responde via ACK."""
    port = live_server
    client = socketio.AsyncClient()

    @client.on("send_text", namespace="/agent")
    async def handle_send_text(envelope):
        payload = (envelope or {}).get("payload") or {}
        # Eco da requisição como confirmação
        return {"ok": True, "echoed": payload}

    await client.connect(
        f"http://127.0.0.1:{port}",
        auth={"token": "token-teste"},
        namespaces=["/agent"],
        wait_timeout=5,
    )
    await asyncio.sleep(0.2)
    try:
        # Pega o sio do servidor (importado pelo main)
        from app.main import sio as server_sio

        result = await agent_bridge.send_command(
            server_sio, empresa_usuario["empresa_id"],
            "send_text",
            {"instance": "inst-x", "number": "551199999", "text": "ping"},
            timeout=10.0,
        )
        assert result["ok"] is True
        assert result["echoed"]["text"] == "ping"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_evo_event_chega_no_handle_webhook(live_server, empresa_usuario):
    """Cliente emite evo_event; servidor chama evo_manager.handle_webhook."""
    port = live_server
    client = socketio.AsyncClient()
    await client.connect(
        f"http://127.0.0.1:{port}",
        auth={"token": "token-teste"},
        namespaces=["/agent"],
        wait_timeout=5,
    )
    await asyncio.sleep(0.2)

    captured = []
    try:
        from app.services import evolution_service
        with patch.object(evolution_service.evo_manager, "handle_webhook",
                          side_effect=lambda p: captured.append(p)) as _mock:
            ack = await client.call(
                "evo_event",
                {"event": "QRCODE_UPDATED", "instance": "inst-x", "data": {}},
                namespace="/agent",
                timeout=5,
            )
            assert ack["ok"] is True
            # Pequeno tempo para o handler do servidor terminar
            await asyncio.sleep(0.2)
            assert any(p.get("event") == "QRCODE_UPDATED" for p in captured)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_api_agents_lista_apos_conexao(live_server, empresa_usuario, auth_cookie):
    """GET /api/agents retorna o agente conectado."""
    port = live_server
    client = socketio.AsyncClient()
    await client.connect(
        f"http://127.0.0.1:{port}",
        auth={"token": "token-teste", "version": "0.1.0"},
        namespaces=["/agent"],
        wait_timeout=5,
    )
    await asyncio.sleep(0.2)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as hc:
            r = await hc.get(
                f"http://127.0.0.1:{port}/api/agents",
                cookies=auth_cookie,
            )
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["agents"][0]["empresa_id"] == empresa_usuario["empresa_id"]
        assert data["agents"][0]["version"] == "0.1.0"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_disconnect_remove_do_registry(live_server, empresa_usuario):
    port = live_server
    client = socketio.AsyncClient()
    await client.connect(
        f"http://127.0.0.1:{port}",
        auth={"token": "token-teste"},
        namespaces=["/agent"],
        wait_timeout=5,
    )
    await asyncio.sleep(0.2)
    assert agent_bridge.has_agent(empresa_usuario["empresa_id"])
    await client.disconnect()
    await asyncio.sleep(0.3)
    assert not agent_bridge.has_agent(empresa_usuario["empresa_id"])
