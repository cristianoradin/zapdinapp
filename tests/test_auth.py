"""
test_auth.py — Testa os fluxos de autenticação: auto-setup e login.

Fluxos críticos cobertos:
  1. auto-setup: registra empresa automaticamente usando MONITOR_CLIENT_TOKEN do .env
     (sem interação do usuário — corrige o bug de pedir token duas vezes)
  2. login: bloqueia corretamente quando token vazio, libera quando configurado
  3. empresa-info: retorna dados da empresa registrada

Mocks:
  - respx: simula respostas do Monitor para /api/auth/cliente/{token}
            e /api/auth/verificar
"""
import pytest
import respx
import httpx

from app.core.config import settings

pytestmark = pytest.mark.asyncio(loop_scope="session")

# ── Dados de teste ─────────────────────────────────────────────────────────────

# Hashes bcrypt válidos (rounds=4, rápido para testes) para a senha "senha123"
# Geradas com: bcrypt.hashpw(b"senha123", bcrypt.gensalt(4)).decode()
_HASH_IHAN  = "$2b$04$b3CCvn1u7H.xT9sy2Fp8je3N07rqe6nnHz1z2mkjw6s2PtNR7xH6K"
_HASH_ADMIN = "$2b$04$s.AllDDEYm3ItPnFGhI8/.ysl0YoWjASxwz40YmUQURkW47z8rKVy"

_MONITOR_CLIENTE = {
    "nome":    "POSTO PARAISO 2",
    "cnpj":    "12345678000195",
    "token":   "client-token-permanente",
    "usuarios": [
        {"username": "ihan",  "password_hash": _HASH_IHAN},
        {"username": "admin", "password_hash": _HASH_ADMIN},
    ],
}


# ── auto-setup ─────────────────────────────────────────────────────────────────

@respx.mock
async def test_auto_setup_cria_empresa_e_usuarios(client):
    """
    POST /api/auth/auto-setup deve registrar a empresa no banco e importar usuários,
    usando apenas o MONITOR_CLIENT_TOKEN já configurado no .env (sem input do usuário).
    """
    settings.app_state = "active"
    settings.monitor_client_token = "test-token-abc"

    respx.get("http://monitor.test/api/auth/cliente/test-token-abc").mock(
        return_value=httpx.Response(200, json=_MONITOR_CLIENTE)
    )

    resp = await client.post("/api/auth/auto-setup")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["empresa"] == "POSTO PARAISO 2"
    assert data["cnpj"] == "12345678000195"
    assert data["usuarios_importados"] == 2


@respx.mock
async def test_auto_setup_idempotente(client):
    """
    Chamar auto-setup duas vezes não deve duplicar empresa nem falhar.
    Segunda chamada retorna os dados da empresa já registrada.
    """
    settings.app_state = "active"
    settings.monitor_client_token = "test-token-abc"

    respx.get("http://monitor.test/api/auth/cliente/test-token-abc").mock(
        return_value=httpx.Response(200, json=_MONITOR_CLIENTE)
    )

    resp1 = await client.post("/api/auth/auto-setup")
    resp2 = await client.post("/api/auth/auto-setup")  # segunda chamada

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp2.json()["empresa"] == "POSTO PARAISO 2"


async def test_auto_setup_sem_token_retorna_503(client):
    """
    Se MONITOR_CLIENT_TOKEN estiver vazio (instalação corrompida),
    auto-setup deve retornar 503 com mensagem clara.
    """
    settings.app_state = "active"
    settings.monitor_client_token = ""  # vazio

    resp = await client.post("/api/auth/auto-setup")

    assert resp.status_code == 503
    assert "token" in resp.json()["detail"].lower()


@respx.mock
async def test_auto_setup_monitor_retorna_404(client):
    """Token não encontrado no monitor → 404 com mensagem clara."""
    settings.app_state = "active"
    settings.monitor_client_token = "token-inexistente"

    respx.get("http://monitor.test/api/auth/cliente/token-inexistente").mock(
        return_value=httpx.Response(404)
    )

    resp = await client.post("/api/auth/auto-setup")

    assert resp.status_code == 404


# ── empresa-info ───────────────────────────────────────────────────────────────

async def test_empresa_info_sem_empresa_retorna_cnpj_null(client):
    """Sem empresa no banco, empresa-info retorna cnpj=null (banco limpo pelo fixture)."""
    settings.app_state = "active"
    resp = await client.get("/api/auth/empresa-info")

    assert resp.status_code == 200
    assert resp.json()["cnpj"] is None


@respx.mock
async def test_empresa_info_retorna_dados_apos_auto_setup(client):
    """Após auto-setup, empresa-info retorna CNPJ e nome da empresa registrada."""
    settings.app_state = "active"
    settings.monitor_client_token = "test-token-abc"

    respx.get("http://monitor.test/api/auth/cliente/test-token-abc").mock(
        return_value=httpx.Response(200, json=_MONITOR_CLIENTE)
    )

    await client.post("/api/auth/auto-setup")

    resp = await client.get("/api/auth/empresa-info")

    assert resp.status_code == 200
    data = resp.json()
    assert data["cnpj"] == "12345678000195"
    assert data["nome"] == "POSTO PARAISO 2"


# ── login ──────────────────────────────────────────────────────────────────────

async def test_login_bloqueado_sem_monitor_token(client):
    """
    CRÍTICO: login com MONITOR_CLIENT_TOKEN vazio E sem empresa no banco deve retornar 503.
    Mensagem deve ser 'Sistema não ativado' — indica configuração incompleta.
    """
    settings.app_state = "active"
    settings.monitor_client_token = ""  # simula instalação sem token

    resp = await client.post(
        "/api/auth/login",
        json={"username": "ihan", "password": "senha"},
    )

    assert resp.status_code == 503
    assert "não ativado" in resp.json()["detail"].lower()


@respx.mock
async def test_login_usa_token_do_banco_quando_settings_vazio(client):
    """
    REGRESSÃO v34: usuário entrou o token via tokenForm → registrar-empresa salvou no
    banco mas settings.monitor_client_token ficou vazio → login retornava 503.

    Com o fix, login lê o token da empresa no banco como fallback e funciona.
    """
    settings.app_state = "active"
    settings.monitor_client_token = ""  # simula .env sem token (bug do instalador antigo)

    # Primeiro: registra empresa via tokenForm (registrar-empresa)
    respx.get("http://monitor.test/api/auth/cliente/token-via-form").mock(
        return_value=httpx.Response(200, json=_MONITOR_CLIENTE)
    )
    r_reg = await client.post(
        "/api/auth/registrar-empresa",
        json={"token": "token-via-form"},
    )
    assert r_reg.status_code == 201

    # Após registrar-empresa, settings deve ter sido atualizado em memória
    assert settings.monitor_client_token == "client-token-permanente"

    # Agora zera settings novamente para simular reinício do processo
    # (token salvo no banco, mas settings vazio — o fallback deve resolver)
    settings.monitor_client_token = ""

    # Login deve funcionar usando o token salvo no banco.
    # SEC-04: usuário "ihan" foi importado com hash real (_HASH_IHAN) via registrar-empresa.
    # A verificação é LOCAL — o monitor não é chamado para /verificar.
    # Apenas usuario-menus é consultado pós-auth.
    respx.get("http://monitor.test/api/auth/usuario-menus/ihan").mock(
        return_value=httpx.Response(200, json={"menus": None})
    )

    resp = await client.post(
        "/api/auth/login",
        json={"username": "ihan", "password": "senha123"},  # senha que gerou _HASH_IHAN
    )

    assert resp.status_code == 200, f"Esperado 200, got {resp.status_code}: {resp.json()}"
    assert resp.json()["ok"] is True


@respx.mock
async def test_login_bloqueado_sem_empresa_no_banco(client):
    """
    Com token configurado mas sem empresa no banco,
    login deve retornar 503 com mensagem sobre empresa.
    """
    settings.app_state = "active"
    settings.monitor_client_token = "test-token"

    # Monitor valida credenciais OK
    respx.post("http://monitor.test/api/auth/verificar").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    resp = await client.post(
        "/api/auth/login",
        json={"username": "ihan", "password": "senha"},
    )

    # Não é bloqueio do middleware (403), é erro de configuração (503)
    assert resp.status_code == 503
    assert "empresa" in resp.json()["detail"].lower()


@respx.mock
async def test_login_credenciais_invalidas_retorna_401(client):
    """
    Credenciais erradas retornam 401.
    SEC-04: com hash local válido (importado via auto-setup), a verificação é
    feita localmente — o monitor NÃO é chamado para /api/auth/verificar.
    """
    settings.app_state = "active"
    settings.monitor_client_token = "client-token-permanente"

    # Registra empresa (banco limpo pelo clean_db)
    respx.get("http://monitor.test/api/auth/cliente/client-token-permanente").mock(
        return_value=httpx.Response(200, json=_MONITOR_CLIENTE)
    )
    await client.post("/api/auth/auto-setup")

    # Senha errada — verificação local → 401
    resp = await client.post(
        "/api/auth/login",
        json={"username": "ihan", "password": "senha_errada"},
    )

    assert resp.status_code == 401


@respx.mock
async def test_login_completo_apos_auto_setup(client):
    """
    Fluxo completo: auto-setup → login com credenciais válidas → cookie de sessão.
    Este é o fluxo da primeira abertura após instalação com v34+.
    """
    settings.app_state = "active"
    settings.monitor_client_token = "test-token-abc"

    # auto-setup
    respx.get("http://monitor.test/api/auth/cliente/test-token-abc").mock(
        return_value=httpx.Response(200, json=_MONITOR_CLIENTE)
    )
    await client.post("/api/auth/auto-setup")

    # login — SEC-04: verificação LOCAL (hash importado do monitor, senha bate)
    # O monitor NÃO é chamado para /api/auth/verificar neste caminho.
    # Mocamos usuario-menus apenas (ainda consultado após auth local bem-sucedida).
    respx.get(
        "http://monitor.test/api/auth/usuario-menus/ihan",
    ).mock(return_value=httpx.Response(200, json={"menus": None}))

    resp = await client.post(
        "/api/auth/login",
        json={"username": "ihan", "password": "senha123"},  # senha que gerou _HASH_IHAN
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["username"] == "ihan"
    # Cookie de sessão deve estar presente
    assert "zapdin_session" in resp.cookies or any(
        "zapdin" in k.lower() for k in resp.cookies
    )
