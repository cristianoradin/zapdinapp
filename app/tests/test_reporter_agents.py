"""
test_reporter_agents.py — F3.6: reporter inclui agentes WS no payload do heartbeat.
"""
from app.services import reporter as rep
from app.services import agent_bridge


def _clear():
    agent_bridge._agents.clear()
    agent_bridge._sid_to_empresa.clear()


def test_agents_for_empresa_vazio_quando_sem_agente():
    _clear()
    assert rep._agents_for_empresa(123) == []


def test_agents_for_empresa_retorna_dados_do_registry():
    _clear()
    agent_bridge.register_agent(7, "sid-A", {"version": "0.1.0"})
    lst = rep._agents_for_empresa(7)
    assert len(lst) == 1
    a = lst[0]
    assert a["sid"] == "sid-A"
    assert a["version"] == "0.1.0"
    assert "connected_at" in a
    assert "last_seen" in a
    _clear()


def test_agents_for_empresa_filtra_por_empresa():
    """Empresa 5 tem agente; consulta empresa 99 deve retornar vazio."""
    _clear()
    agent_bridge.register_agent(5, "sid-5", {"version": "x"})
    assert rep._agents_for_empresa(5) != []
    assert rep._agents_for_empresa(99) == []
    _clear()
