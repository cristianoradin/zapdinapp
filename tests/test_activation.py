"""
test_activation.py — Testa o fluxo de ativação via /api/activate.

Estes testes cobrem especificamente o bug que causou v30 e v32/v33:
  - Após ativação bem-sucedida, settings em memória DEVEM ser atualizados
    imediatamente (app_state, monitor_client_token, monitor_url).
  - Sem isso, o LockMiddleware e o auth.py continuam bloqueando o login
    mesmo após o .env ser gravado corretamente.

Mocks usados:
  - respx: simula respostas HTTP do Monitor
  - unittest.mock.patch: substitui decrypt_config e apply_config_to_env
    para não depender de criptografia real nem de escrita em disco
"""
import pytest
import respx
import httpx
from unittest.mock import patch, AsyncMock, MagicMock

from app.core.config import settings

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Config que o monitor "retornaria" após descriptografia
_CONFIG_DESCRIPTOGRAFADA = {
    "APP_STATE":            "active",
    "monitor_client_token": "token-permanente-xyz",
    "MONITOR_URL":          "http://monitor.test",
    "CLIENT_NAME":          "POSTO PARAISO 2",
    "CLIENT_CNPJ":          "12345678000195",
}


def _mock_activation(monitor_status: int = 200):
    """Helper: configura todos os mocks necessários para simular uma ativação."""
    monitor_mock = respx.post("http://monitor.test/api/activate/validate").mock(
        return_value=httpx.Response(
            monitor_status,
            json={"encrypted": "dGVzdA==", "nonce": "dGVzdG5vbmNl"}
            if monitor_status == 200 else {},
        )
    )
    return monitor_mock


@respx.mock
async def test_ativacao_atualiza_app_state_em_memoria(client):
    """
    CRÍTICO: após POST /api/activate bem-sucedido, settings.app_state
    deve ser 'active' em memória — sem precisar reiniciar o processo.

    Regressão: v30 não atualizava settings → LockMiddleware continuava bloqueando.
    """
    settings.app_state = "locked"
    settings.monitor_client_token = ""

    _mock_activation(200)

    with patch("app.routers.activation.decrypt_config",
               return_value=_CONFIG_DESCRIPTOGRAFADA), \
         patch("app.routers.activation.apply_config_to_env"), \
         patch("app.routers.activation.asyncio.create_task"):  # não agenda restart

        resp = await client.post("/api/activate", json={"token": "2MTB-ACSD-5MXQ-93EH"})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Estado em memória deve estar atualizado IMEDIATAMENTE
    assert settings.app_state == "active", (
        "settings.app_state deve ser 'active' após ativação — "
        "sem isso o LockMiddleware bloqueia o login"
    )


@respx.mock
async def test_ativacao_atualiza_monitor_client_token_em_memoria(client):
    """
    CRÍTICO: após ativação, settings.monitor_client_token deve estar preenchido.

    Regressão: v32 atualizava app_state mas não monitor_client_token →
    auth.py retornava 'Sistema não ativado' no login.
    """
    settings.app_state = "locked"
    settings.monitor_client_token = ""

    _mock_activation(200)

    with patch("app.routers.activation.decrypt_config",
               return_value=_CONFIG_DESCRIPTOGRAFADA), \
         patch("app.routers.activation.apply_config_to_env"), \
         patch("app.routers.activation.asyncio.create_task"):

        await client.post("/api/activate", json={"token": "2MTB-ACSD-5MXQ-93EH"})

    assert settings.monitor_client_token == "token-permanente-xyz", (
        "settings.monitor_client_token deve ser preenchido após ativação — "
        "sem isso auth.py bloqueia o login com 'Sistema não ativado'"
    )


@respx.mock
async def test_ativacao_token_invalido_nao_altera_settings(client):
    """Token rejeitado pelo monitor não deve alterar settings."""
    settings.app_state = "locked"
    settings.monitor_client_token = ""

    _mock_activation(401)

    resp = await client.post("/api/activate", json={"token": "TOKEN-INVALIDO"})

    assert resp.status_code == 401
    assert settings.app_state == "locked"      # não deve ter mudado
    assert settings.monitor_client_token == ""  # não deve ter mudado


@respx.mock
async def test_ativacao_monitor_indisponivel_retorna_503(client):
    """Se o monitor estiver fora do ar, retorna 503 com mensagem clara."""
    settings.app_state = "locked"

    respx.post("http://monitor.test/api/activate/validate").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    resp = await client.post("/api/activate", json={"token": "QUALQUER-TOKEN"})

    assert resp.status_code == 503
    assert settings.app_state == "locked"


@respx.mock
async def test_ativacao_token_vazio_retorna_400(client):
    """Token vazio deve retornar 400 sem chamar o monitor."""
    resp = await client.post("/api/activate", json={"token": ""})

    assert resp.status_code == 400
    assert not respx.calls  # monitor não deve ter sido chamado
