"""
test_evolution_agent_mode.py — F3.2: EvoManager roteia comandos via WS quando
a sessão é "agent://" (modo agente).

Mock do Socket.IO: AsyncMock com .call() controlado para cada comando.
Não dispara HTTP; só verifica que o comando certo foi enviado ao sid certo.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from app.services import evolution_service as evo
from app.services import agent_bridge


# ── _is_agent_mode helper ────────────────────────────────────────────────────

def test_is_agent_mode_detecta_agent_scheme():
    assert evo._is_agent_mode("agent://") is True
    assert evo._is_agent_mode("agent://qualquer-coisa") is True
    assert evo._is_agent_mode("AGENT://") is True


def test_is_agent_mode_rejeita_outros_schemes():
    assert evo._is_agent_mode(None) is False
    assert evo._is_agent_mode("") is False
    assert evo._is_agent_mode("http://10.0.0.1") is False
    assert evo._is_agent_mode("https://api.com") is False


def test_set_sio_injeta_global():
    sentinel = object()
    evo.set_sio(sentinel)
    assert evo._sio is sentinel
    evo.set_sio(None)


# ── Roteamento send_text via agent ───────────────────────────────────────────

def _clear_registry():
    agent_bridge._agents.clear()
    agent_bridge._sid_to_empresa.clear()


@pytest.mark.asyncio
async def test_send_text_roteia_via_agent():
    _clear_registry()
    empresa_id = 42
    agent_bridge.register_agent(empresa_id, "sid-test", {"version": "1"})

    # Mock sio.call para retornar sucesso
    sio_mock = AsyncMock()
    sio_mock.call.return_value = {"ok": True}
    evo.set_sio(sio_mock)

    # Cria sessão em modo agente
    mgr = evo.EvoManager()
    sess = evo.EvoSession("sess-x", "Teste", empresa_id, evolution_url="agent://")
    mgr._sessions[mgr._key(empresa_id, "sess-x")] = sess

    ok, err = await mgr.send_text("sess-x", empresa_id, "+5511999990000", "ola")
    assert ok is True
    assert err is None
    sio_mock.call.assert_called_once()
    args, kwargs = sio_mock.call.call_args
    # Primeiro arg é o comando
    assert args[0] == "send_text"
    payload_env = args[1]
    assert payload_env["payload"]["text"] == "ola"
    assert payload_env["payload"]["number"] == "5511999990000"
    assert payload_env["payload"]["instance"].startswith(f"e{empresa_id}_")
    assert kwargs["to"] == "sid-test"
    assert kwargs["namespace"] == "/agent"

    _clear_registry()
    evo.set_sio(None)


@pytest.mark.asyncio
async def test_send_text_agent_offline_retorna_erro():
    _clear_registry()
    empresa_id = 77
    evo.set_sio(AsyncMock())

    mgr = evo.EvoManager()
    sess = evo.EvoSession("sess-y", "Teste", empresa_id, evolution_url="agent://")
    mgr._sessions[mgr._key(empresa_id, "sess-y")] = sess

    ok, err = await mgr.send_text("sess-y", empresa_id, "5511999990000", "oi")
    assert ok is False
    assert "agent" in err.lower()

    evo.set_sio(None)


@pytest.mark.asyncio
async def test_send_text_agente_resposta_erro():
    _clear_registry()
    empresa_id = 8
    agent_bridge.register_agent(empresa_id, "sid-err", {})
    sio_mock = AsyncMock()
    sio_mock.call.return_value = {"ok": False, "error": "evolution offline"}
    evo.set_sio(sio_mock)

    mgr = evo.EvoManager()
    sess = evo.EvoSession("s1", "T", empresa_id, evolution_url="agent://")
    mgr._sessions[mgr._key(empresa_id, "s1")] = sess

    ok, err = await mgr.send_text("s1", empresa_id, "551199", "x")
    assert ok is False
    assert "evolution offline" in err

    _clear_registry()
    evo.set_sio(None)


@pytest.mark.asyncio
async def test_send_text_modo_servidor_nao_chama_agent():
    """Sessão sem agent:// não deve invocar sio.call mesmo se agente registrado."""
    _clear_registry()
    sio_mock = AsyncMock()
    sio_mock.call.return_value = {"ok": True}
    evo.set_sio(sio_mock)

    mgr = evo.EvoManager()
    # Sessão modo servidor (evolution_url=None)
    sess = evo.EvoSession("s-srv", "T", 1, evolution_url=None)
    mgr._sessions[mgr._key(1, "s-srv")] = sess

    # Mock httpx para não bater na rede
    with patch("app.services.evolution_service.httpx.AsyncClient") as mock_client:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        ctx = AsyncMock()
        ctx.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        mock_client.return_value = ctx

        await mgr.send_text("s-srv", 1, "551199", "y")

    sio_mock.call.assert_not_called()
    evo.set_sio(None)


# ── _ensure_instance via agent ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_instance_via_agent():
    _clear_registry()
    empresa_id = 33
    agent_bridge.register_agent(empresa_id, "sid-ei", {})
    sio_mock = AsyncMock()
    sio_mock.call.return_value = {"ok": True}
    evo.set_sio(sio_mock)

    mgr = evo.EvoManager()
    sess = evo.EvoSession("sx", "Nome X", empresa_id, evolution_url="agent://")
    inst = evo._instance_name(empresa_id, "sx")
    mgr._sessions[mgr._key(empresa_id, "sx")] = sess
    mgr._inst_index[inst] = sess

    ok = await mgr._ensure_instance(inst, nome="Nome X")
    assert ok is True
    sio_mock.call.assert_called_once()
    args, _ = sio_mock.call.call_args
    assert args[0] == "create_instance"
    assert args[1]["payload"]["instance"] == inst
    assert args[1]["payload"]["nome"] == "Nome X"

    _clear_registry()
    evo.set_sio(None)


# ── remove_session via agent ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remove_session_via_agent():
    _clear_registry()
    empresa_id = 4
    agent_bridge.register_agent(empresa_id, "sid-del", {})
    sio_mock = AsyncMock()
    sio_mock.call.return_value = {"ok": True}
    evo.set_sio(sio_mock)

    mgr = evo.EvoManager()
    sess = evo.EvoSession("sd", "Tdel", empresa_id, evolution_url="agent://")
    inst = evo._instance_name(empresa_id, "sd")
    mgr._sessions[mgr._key(empresa_id, "sd")] = sess
    mgr._inst_index[inst] = sess

    await mgr.remove_session("sd", empresa_id)
    # delete_instance deve ter sido o comando enviado
    assert any(c.args[0] == "delete_instance" for c in sio_mock.call.call_args_list)

    _clear_registry()
    evo.set_sio(None)


# ── Validação URL agent:// no router /api/sessoes ────────────────────────────

@pytest.mark.asyncio
async def test_post_sessoes_aceita_agent_scheme(auth_client):
    r = await auth_client.post("/api/sessoes", json={"nome": "AgenteTest", "evolution_url": "agent://"})
    assert r.status_code in (200, 201)
    data = r.json()
    assert data["evolution_url"] == "agent://"

    # Cleanup
    await auth_client.delete(f"/api/sessoes/{data['id']}")


@pytest.mark.asyncio
async def test_post_sessoes_rejeita_scheme_invalido(auth_client):
    r = await auth_client.post("/api/sessoes", json={"nome": "X", "evolution_url": "ftp://x"})
    assert r.status_code == 422
