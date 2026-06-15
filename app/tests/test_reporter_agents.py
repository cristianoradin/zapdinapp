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


# ── wa_info via DB (modo agente: manager em memória não tem a sessão) ──────────
import pytest


@pytest.mark.asyncio
async def test_wa_info_le_phone_do_db_modo_agente(_patched_app, db_conn, empresa_usuario):
    """Sessão conectada via agente grava phone só no DB; reporter deve lê-lo
    e reportar wa_status=connected + wa_phone no heartbeat."""
    empresa_id = empresa_usuario["empresa_id"]
    await db_conn.execute(
        "INSERT INTO sessoes_wa (empresa_id, id, nome, status, evolution_url, phone) "
        "VALUES ($1, $2, $3, 'connected', 'agent://', $4)",
        empresa_id, "sess-tq", "Taquari", "556791976484",
    )
    try:
        info = await rep._wa_info_for_empresa(empresa_id)
        assert info["wa_status"] == "connected"
        assert info["wa_phone"] == "556791976484"
    finally:
        await db_conn.execute("DELETE FROM sessoes_wa WHERE id='sess-tq'")
    assert rep._agents_for_empresa(99) == []
    _clear()
