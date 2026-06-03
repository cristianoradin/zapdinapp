"""
test_agent_bridge.py — F3.1: registry de agentes WS + endpoint /api/agents.

Cobertura:
  - register_agent / unregister_by_sid / touch / has_agent / get_agent
  - reconexão (mesmo empresa_id, novo sid) descarta sid antigo
  - _resolve_empresa_by_token valida token na tabela empresas
  - GET /api/agents (sem auth → 401; auth → lista filtrada por empresa)
  - send_command lança RuntimeError quando agente offline
"""
import asyncio
import pytest
from app.services import agent_bridge


# ── Registry em memória ──────────────────────────────────────────────────────

def _clear_registry():
    agent_bridge._agents.clear()
    agent_bridge._sid_to_empresa.clear()


def test_register_e_get_agent():
    _clear_registry()
    agent_bridge.register_agent(42, "sid-xyz", {"version": "1.0.0"})
    info = agent_bridge.get_agent(42)
    assert info is not None
    assert info["sid"] == "sid-xyz"
    assert info["version"] == "1.0.0"
    assert agent_bridge.has_agent(42)


def test_unregister_by_sid_remove_e_retorna_empresa():
    _clear_registry()
    agent_bridge.register_agent(99, "sid-A", {})
    empresa = agent_bridge.unregister_by_sid("sid-A")
    assert empresa == 99
    assert not agent_bridge.has_agent(99)


def test_unregister_sid_inexistente_retorna_none():
    _clear_registry()
    assert agent_bridge.unregister_by_sid("inexistente") is None


def test_reconexao_descarta_sid_antigo():
    _clear_registry()
    agent_bridge.register_agent(7, "sid-velho", {"version": "1.0"})
    agent_bridge.register_agent(7, "sid-novo", {"version": "1.1"})
    # sid antigo não deve mais mapear para empresa 7
    assert "sid-velho" not in agent_bridge._sid_to_empresa
    assert agent_bridge._sid_to_empresa["sid-novo"] == 7
    assert agent_bridge.get_agent(7)["sid"] == "sid-novo"


def test_touch_atualiza_last_seen():
    _clear_registry()
    agent_bridge.register_agent(1, "sid-T", {})
    t0 = agent_bridge._agents[1]["last_seen"]
    import time
    time.sleep(0.01)
    agent_bridge.touch("sid-T")
    assert agent_bridge._agents[1]["last_seen"] > t0


def test_list_agents_retorna_todos():
    _clear_registry()
    agent_bridge.register_agent(1, "s1", {})
    agent_bridge.register_agent(2, "s2", {})
    lst = agent_bridge.list_agents()
    assert len(lst) == 2
    assert {a["empresa_id"] for a in lst} == {1, 2}


# ── Resolução de token via DB ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_empresa_by_token_valido(empresa_usuario):
    import asyncpg
    import os
    url = os.environ.get("TEST_DATABASE_URL", "postgresql://cristianoradin@localhost/zapdin_test")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        # Empresa criada no conftest tem token="token-teste"
        empresa_id = await agent_bridge._resolve_empresa_by_token(pool, "token-teste")
        assert empresa_id == empresa_usuario["empresa_id"]
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_resolve_empresa_token_invalido_retorna_none(empresa_usuario):
    import asyncpg
    import os
    url = os.environ.get("TEST_DATABASE_URL", "postgresql://cristianoradin@localhost/zapdin_test")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        assert await agent_bridge._resolve_empresa_by_token(pool, "token-falso-xxxx") is None
        assert await agent_bridge._resolve_empresa_by_token(pool, "") is None
        assert await agent_bridge._resolve_empresa_by_token(pool, "abc") is None
    finally:
        await pool.close()


# ── send_command sem agente conectado ────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_command_sem_agente_lanca_erro():
    _clear_registry()
    with pytest.raises(RuntimeError, match="não está conectado"):
        await agent_bridge.send_command(None, 9999, "send_text", {})


# ── Endpoint REST /api/agents ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_agents_sem_auth_retorna_401(client):
    r = await client.get("/api/agents")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_agents_filtra_por_empresa(auth_client, empresa_usuario):
    _clear_registry()
    # Registra um agente da empresa do usuário e outro de empresa diferente
    agent_bridge.register_agent(empresa_usuario["empresa_id"], "sid-mine", {"version": "1"})
    agent_bridge.register_agent(empresa_usuario["empresa_id"] + 999, "sid-other", {"version": "1"})

    r = await auth_client.get("/api/agents")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["agents"][0]["empresa_id"] == empresa_usuario["empresa_id"]
    assert data["agents"][0]["sid"] == "sid-mine"

    _clear_registry()


@pytest.mark.asyncio
async def test_api_agents_lista_vazia(auth_client):
    _clear_registry()
    r = await auth_client.get("/api/agents")
    assert r.status_code == 200
    assert r.json() == {"agents": [], "count": 0}
