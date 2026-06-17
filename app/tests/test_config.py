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


class TestAlertaCritico:
    """Alerta crítico: multi-número + alerta de falha de envio (mesmos números)."""

    async def test_get_sem_auth_401(self, client):
        r = await client.get("/api/config/alerta-critico")
        assert r.status_code == 401

    async def test_roundtrip_destinos_por_numero(self, auth_client):
        payload = {
            "destinos": [
                {"numero": "11999998888", "avaliacao": True,  "falha": False},
                {"numero": "(67) 98888-7777", "avaliacao": False, "falha": True},
                {"numero": "11999998888", "avaliacao": True, "falha": True},  # dup → ignora
            ],
            "mensagem": "Nota baixa de {nome}",
            "falha_mensagem": "Falhou {numero} ({nome}): {erro}",
        }
        r = await auth_client.post("/api/config/alerta-critico", json=payload)
        assert r.status_code == 200 and r.json().get("ok")

        cfg = (await auth_client.get("/api/config/alerta-critico")).json()
        assert cfg["destinos"] == [
            {"numero": "11999998888", "avaliacao": True,  "falha": False},
            {"numero": "67988887777", "avaliacao": False, "falha": True},
        ]
        # derivados p/ retrocompat
        assert cfg["ativo"] is True          # algum recebe avaliação
        assert cfg["falha_ativo"] is True    # algum recebe falha
        assert cfg["falha_mensagem"] == "Falhou {numero} ({nome}): {erro}"

    async def test_retrocompat_telefone_legado_vira_destino(self, auth_client):
        # Cliente antigo: só `telefone` + `ativo` → vira destino com avaliacao=true
        r = await auth_client.post("/api/config/alerta-critico", json={
            "ativo": True, "telefone": "11955554444", "mensagem": "x",
        })
        assert r.status_code == 200
        cfg = (await auth_client.get("/api/config/alerta-critico")).json()
        assert cfg["destinos"] == [
            {"numero": "11955554444", "avaliacao": True, "falha": False},
        ]

    async def test_destinos_por_tipo_helper(self):
        from app.services.alerta_service import destinos_por_tipo
        cfg = {"destinos": [
            {"numero": "111", "avaliacao": True,  "falha": False},
            {"numero": "222", "avaliacao": False, "falha": True},
        ]}
        assert destinos_por_tipo(cfg, "avaliacao") == ["111"]
        assert destinos_por_tipo(cfg, "falha") == ["222"]


class TestAlertaService:
    """Classificador de erro inválido (número/cadastro vs infra)."""

    def test_classifica_numero_invalido(self):
        from app.services.alerta_service import is_invalid_number_error as f
        assert f("number not on whatsapp") is True
        assert f("invalid number") is True
        assert f("Número inválido") is True

    def test_classifica_infra_nao_alerta(self):
        from app.services.alerta_service import is_invalid_number_error as f
        assert f("connection timeout") is False
        assert f("sem sessão") is False
        assert f("agent: disconnected") is False
        assert f("") is False
        assert f(None) is False
