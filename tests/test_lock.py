"""
test_lock.py — Testa o LockMiddleware.

Garante que:
  - Com APP_STATE=locked, rotas de API retornam 403 (não chegam ao handler)
  - Com APP_STATE=locked, rotas de ativação passam (não são bloqueadas)
  - Com APP_STATE=active, rotas de API são acessíveis (mesmo que retornem erro por
    outras razões — credenciais, empresa ausente, etc.)

Estes testes previnem regressão no comportamento do LockMiddleware,
que é o guardião principal do sistema.
"""
import pytest
from app.core.config import settings

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_login_bloqueado_quando_locked(client):
    """LockMiddleware deve retornar 403 no endpoint de login quando sistema bloqueado."""
    settings.app_state = "locked"

    resp = await client.post(
        "/api/auth/login",
        json={"username": "qualquer", "password": "qualquer"},
    )
    assert resp.status_code == 403
    assert "bloqueado" in resp.json()["error"].lower()


async def test_rota_generica_bloqueada_quando_locked(client):
    """Qualquer rota /api/ deve ser bloqueada com 403 quando sistema está locked."""
    settings.app_state = "locked"

    for rota in ["/api/stats", "/api/whatsapp/sessions"]:
        resp = await client.get(rota)
        assert resp.status_code == 403, f"Rota {rota} deveria estar bloqueada"


async def test_ativacao_acessivel_quando_locked(client):
    """
    /api/activate e /activate devem ser acessíveis mesmo com sistema bloqueado.
    São as únicas rotas permitidas no LockMiddleware quando locked.
    """
    settings.app_state = "locked"

    # Endpoint de status de ativação — sempre deve responder
    resp = await client.get("/api/activate/status")
    assert resp.status_code == 200
    assert resp.json()["state"] == "locked"


async def test_login_acessivel_quando_active(client):
    """
    Com APP_STATE=active, /api/auth/login deve ser acessível pelo middleware.
    (Pode falhar por outras razões — sem empresa, sem token — mas não por bloqueio.)
    """
    settings.app_state = "active"
    settings.monitor_client_token = "qualquer-token"

    resp = await client.post(
        "/api/auth/login",
        json={"username": "teste", "password": "teste"},
    )
    # Qualquer status exceto 403 (bloqueio do middleware) é aceitável aqui
    assert resp.status_code != 403


async def test_status_ativacao_reflete_estado_em_memoria(client):
    """
    GET /api/activate/status deve retornar o estado atual de settings em memória,
    não o valor do arquivo .env (que não muda durante o processo).
    """
    settings.app_state = "locked"
    resp = await client.get("/api/activate/status")
    assert resp.json()["state"] == "locked"

    settings.app_state = "active"
    resp = await client.get("/api/activate/status")
    assert resp.json()["state"] == "active"
