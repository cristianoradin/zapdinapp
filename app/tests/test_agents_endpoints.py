"""Tests pros endpoints /api/agents + /metrics."""
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app as asgi_app
from app.services import agent_bridge


@pytest.fixture(autouse=True)
def _clean_registry():
    agent_bridge._agents.clear()
    agent_bridge._sid_to_empresa.clear()
    yield
    agent_bridge._agents.clear()
    agent_bridge._sid_to_empresa.clear()


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_format():
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as ac:
        resp = await ac.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "zapdin_agents_connected" in body
    assert "# TYPE zapdin_agents_connected gauge" in body
    assert "zapdin_agents_connected 0" in body  # registry vazio


@pytest.mark.asyncio
async def test_metrics_shows_registered_agents():
    agent_bridge.register_agent(1, "sid-aaa", {"version": "0.1.0"})
    agent_bridge.register_agent(2, "sid-bbb", {"version": "0.2.0"})
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as ac:
        resp = await ac.get("/metrics")
    body = resp.text
    assert "zapdin_agents_connected 2" in body
    assert 'empresa_id="1"' in body
    assert 'version="0.1.0"' in body
    assert "zapdin_agent_seconds_since_last_seen" in body
    assert "zapdin_agent_uptime_seconds" in body


@pytest.mark.asyncio
async def test_agents_all_requires_monitor_token():
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as ac:
        resp = await ac.get("/api/agents/all")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_activate_endpoint_token_curto():
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as ac:
        resp = await ac.post("/api/agents/activate", json={"token": "abc"})
    assert resp.status_code == 422  # Pydantic min_length=8


@pytest.mark.asyncio
async def test_activate_endpoint_token_inexistente():
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/agents/activate",
            json={"token": "token-inexistente-no-banco-12345"},
        )
    # 401 = token rejeitado (DB acessível); 503 = DB unavailable em teste sem TEST_DATABASE_URL.
    # Endpoint nunca retorna 200 com token inexistente — esse é o invariante real.
    assert resp.status_code in (401, 503)
    assert resp.status_code != 200


@pytest.mark.asyncio
async def test_agents_all_with_valid_token():
    from app.core.config import settings
    agent_bridge.register_agent(42, "sid-x", {"version": "0.1.0"})
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as ac:
        resp = await ac.get(
            "/api/agents/all",
            headers={"X-Monitor-Token": settings.monitor_client_token or "token-teste"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["agents"][0]["empresa_id"] == 42
    assert data["agents"][0]["version"] == "0.1.0"
    assert "seconds_since_last_seen" in data["agents"][0]




@pytest.mark.asyncio
async def test_agent_version_auto_update_desligado():
    """Auto-update é push-only: update_available SEMPRE False (mesmo current antigo).
    Evita o loop de auto-update que derrubava o agente a cada ~60s."""
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as ac:
        resp = await ac.get("/api/agents/version", params={"current": "0.1.0"})
    assert resp.status_code == 200
    d = resp.json()
    assert d["latest"]
    assert d["download_url"].startswith(("http://", "https://"))
    assert "ZapDinAgentSetup" in d["download_url"]
    assert d["update_available"] is False  # push-only


@pytest.mark.asyncio
async def test_agent_version_no_update():
    """current >= latest → update_available=False (sempre, push-only)"""
    from app.routers.agents import AGENT_LATEST_VERSION
    async with AsyncClient(transport=ASGITransport(app=asgi_app), base_url="http://test") as ac:
        resp = await ac.get("/api/agents/version", params={"current": AGENT_LATEST_VERSION})
    assert resp.status_code == 200
    d = resp.json()
    assert d["update_available"] is False
