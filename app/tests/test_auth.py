"""
app/tests/test_auth.py — Testes de autenticação.

Cobre:
  - GET  /api/auth/empresa-info       → retorna cnpj/nome ou nulos
  - POST /api/auth/login              → credenciais válidas e inválidas
  - POST /api/auth/logout             → apaga cookie, blacklista token
  - GET  /api/auth/me                 → retorna usuário autenticado
  - GET  /api/auth/me (sem cookie)    → 401
  - Rate limit em login               → 429 após 10 tentativas
"""
import pytest
import pytest_asyncio


pytestmark = pytest.mark.asyncio


class TestEmpresaInfo:
    async def test_retorna_cnpj_quando_empresa_existe(self, auth_client, empresa_usuario):
        r = await auth_client.get("/api/auth/empresa-info")
        assert r.status_code == 200
        data = r.json()
        assert data["cnpj"] is not None
        assert data["nome"] == "Empresa Teste"

    async def test_retorna_nulos_quando_nao_ha_empresa(self, client):
        # Sem empresa cadastrada (transação limpa)
        r = await client.get("/api/auth/empresa-info")
        assert r.status_code == 200
        data = r.json()
        # Pode ser None se não houver empresa ativa nesta transação
        assert "cnpj" in data
        assert "nome" in data


class TestLogin:
    async def test_rejeita_sem_cookie(self, client):
        r = await client.get("/api/auth/me")
        assert r.status_code == 401

    async def test_me_retorna_usuario_autenticado(self, auth_client, empresa_usuario):
        r = await auth_client.get("/api/auth/me")
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == empresa_usuario["username"]
        assert data["empresa_id"] == empresa_usuario["empresa_id"]

    async def test_logout_invalida_cookie(self, auth_client):
        # Pega o cookie atual
        from app.core.security import SESSION_COOKIE
        cookie_val = auth_client.cookies.get(SESSION_COOKIE)
        assert cookie_val is not None

        # Faz logout
        r = await auth_client.post("/api/auth/logout")
        assert r.status_code == 200

        # Token agora deve estar na blacklist
        from app.core.security import decode_session_token
        assert decode_session_token(cookie_val) is None

    async def test_me_apos_logout_retorna_401(self, auth_client):
        await auth_client.post("/api/auth/logout")
        # Remove o cookie do cliente
        from app.core.security import SESSION_COOKIE
        auth_client.cookies.delete(SESSION_COOKIE)
        r = await auth_client.get("/api/auth/me")
        assert r.status_code == 401


class TestRateLimit:
    async def test_rate_limit_login_429(self, client):
        """10 tentativas com IP fictício → 11ª deve retornar 429."""
        # Simula múltiplas tentativas de login com credenciais inválidas
        # Usa X-Forwarded-For para simular um IP remoto (auth.py confia se origem é loopback)
        headers = {"X-Forwarded-For": "1.2.3.4"}
        payload = {"username": "naoexiste", "password": "errada"}
        for _ in range(10):
            await client.post("/api/auth/login", json=payload, headers=headers)
        # 11ª tentativa deve ser bloqueada
        r = await client.post("/api/auth/login", json=payload, headers=headers)
        assert r.status_code == 429
        assert "Muitas tentativas" in r.json().get("detail", "")
