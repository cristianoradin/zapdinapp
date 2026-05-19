"""
app/tests/test_config.py — Testes de configuração geral e chaves de IA.

Cobre:
  - GET  /api/config               → 401 sem auth, 200 com auth
  - GET  /api/config               → retorna template padrão quando vazio
  - POST /api/config               → salva e retorna chave
  - GET  /api/config/ai-keys       → 401 sem auth, 200 com auth
  - POST /api/config/ai-key        → provedor inválido → 400
  - POST /api/config/ai-key        → prefixo errado → 400
  - POST /api/config/ai-uso        → salva uso do provedor
"""
import pytest
import pytest_asyncio


pytestmark = pytest.mark.asyncio


class TestConfigGeral:
    async def test_sem_auth_retorna_401(self, client):
        r = await client.get("/api/config")
        assert r.status_code == 401

    async def test_com_auth_retorna_200(self, auth_client):
        r = await auth_client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert "mensagem_padrao" in data
        assert "client_name" in data

    async def test_retorna_template_padrao_quando_vazio(self, auth_client):
        r = await auth_client.get("/api/config")
        assert r.status_code == 200
        # Template padrão deve conter variáveis esperadas
        msg = r.json().get("mensagem_padrao", "")
        assert "{nome}" in msg or "Venda Confirmada" in msg

    async def test_salva_e_recupera_chave(self, auth_client):
        # Salva mensagem personalizada
        r = await auth_client.post("/api/config", json={
            "mensagem_padrao": "Olá {nome}, sua compra de {valor} foi confirmada!"
        })
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # Recupera e verifica
        r2 = await auth_client.get("/api/config")
        assert r2.status_code == 200
        assert r2.json()["mensagem_padrao"] == "Olá {nome}, sua compra de {valor} foi confirmada!"

    async def test_toggle_avaliacao(self, auth_client):
        r = await auth_client.post("/api/config", json={"avaliacao_ativa": "1"})
        assert r.status_code == 200
        r2 = await auth_client.get("/api/config")
        assert r2.json().get("avaliacao_ativa") == "1"


class TestAIConfig:
    async def test_ai_keys_sem_auth_retorna_401(self, client):
        r = await client.get("/api/config/ai-keys")
        assert r.status_code == 401

    async def test_ai_keys_com_auth_retorna_todos_provedores(self, auth_client):
        r = await auth_client.get("/api/config/ai-keys")
        assert r.status_code == 200
        data = r.json()
        for provider in ("openai", "gemini", "anthropic", "groq"):
            assert provider in data
            assert "configurado" in data[provider]
            assert "uso" in data[provider]

    async def test_ai_key_provedor_invalido_retorna_400(self, auth_client):
        r = await auth_client.post("/api/config/ai-key", json={
            "provider": "provedor-inexistente",
            "key": "sk-qualquer",
        })
        assert r.status_code == 400
        assert "inválido" in r.json().get("detail", "").lower()

    async def test_ai_key_prefixo_errado_retorna_400(self, auth_client):
        r = await auth_client.post("/api/config/ai-key", json={
            "provider": "openai",
            "key": "ERRADO-abc123",  # OpenAI deve começar com "sk-"
        })
        assert r.status_code == 400
        assert "sk-" in r.json().get("detail", "")

    async def test_ai_uso_provedor_invalido_retorna_400(self, auth_client):
        r = await auth_client.post("/api/config/ai-uso", json={
            "provider": "inexistente",
            "ocr": True,
            "chat": False,
        })
        assert r.status_code == 400
