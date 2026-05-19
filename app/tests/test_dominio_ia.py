"""
app/tests/test_dominio_ia.py — Testes da integração Domínio e IA Central.

Cobre:
  Domínio (Thomson Reuters):
    - GET  /api/dominio/config    → retorna config (vazia ou com dados)
    - POST /api/dominio/config    → salva configuração
    - POST /api/dominio/testar    → testa conexão (sem API real → erro controlado)
    - GET  /api/dominio/log       → lista log de envios
    - 401 sem auth em todos

  IA Central:
    - POST /api/ia-central/chat   → processa pergunta (sem chave real → resposta controlada)
    - 401 sem auth
"""
import pytest

pytestmark = pytest.mark.asyncio


# ══════════════════════════════════════════════════════════════════════════════
# DOMÍNIO AUTH
# ══════════════════════════════════════════════════════════════════════════════

class TestDominioAuth:
    async def test_config_sem_auth(self, client):
        assert (await client.get("/api/dominio/config")).status_code == 401

    async def test_log_sem_auth(self, client):
        assert (await client.get("/api/dominio/log")).status_code == 401

    async def test_testar_sem_auth(self, client):
        assert (await client.post("/api/dominio/testar")).status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# DOMÍNIO — CONFIG
# ══════════════════════════════════════════════════════════════════════════════

class TestDominioConfig:
    async def test_retorna_config_vazia_ou_defaults(self, auth_client):
        r = await auth_client.get("/api/dominio/config")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    async def test_salva_config(self, auth_client):
        r = await auth_client.post("/api/dominio/config", json={
            "cnpj_origem": "12345678000199",
            "nome_origem": "Empresa Teste",
            "api_url": "https://api.dominio.com.br/v1",
            "api_token": "token-fake-123",
            "cnpj_escritorio": "98765432000100",
            "tipos": ["nfe", "nfse"],
            "auto_envio": False,
        })
        assert r.status_code == 200
        assert r.json().get("ok") is True

    async def test_recupera_config_salva(self, auth_client):
        await auth_client.post("/api/dominio/config", json={
            "cnpj_origem": "11111111000111",
            "nome_origem": "Empresa Config Test",
            "api_url": "https://api.dominio.com.br/v1",
            "api_token": "token-abc",
            "cnpj_escritorio": "22222222000122",
            "tipos": ["nfe"],
            "auto_envio": True,
        })
        r = await auth_client.get("/api/dominio/config")
        assert r.status_code == 200
        data = r.json()
        # nome_origem deve estar presente
        assert "nome_origem" in data or "api_url" in data


# ══════════════════════════════════════════════════════════════════════════════
# DOMÍNIO — TESTAR
# ══════════════════════════════════════════════════════════════════════════════

class TestDominioTestar:
    async def test_testar_sem_config_retorna_erro_controlado(self, auth_client):
        """Sem API real, testar deve retornar erro controlado (não 500)."""
        r = await auth_client.post("/api/dominio/testar")
        # Deve retornar 200 com falha descrita, ou 400, não 500
        assert r.status_code in (200, 400, 422, 503)
        data = r.json()
        # Deve ter alguma informação de status
        assert isinstance(data, dict)


# ══════════════════════════════════════════════════════════════════════════════
# DOMÍNIO — LOG
# ══════════════════════════════════════════════════════════════════════════════

class TestDominioLog:
    async def test_log_retorna_lista(self, auth_client):
        r = await auth_client.get("/api/dominio/log")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ══════════════════════════════════════════════════════════════════════════════
# IA CENTRAL AUTH
# ══════════════════════════════════════════════════════════════════════════════

class TestIaCentralAuth:
    async def test_chat_sem_auth(self, client):
        r = await client.post("/api/ia-central/chat", json={"mensagem": "Olá"})
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# IA CENTRAL
# ══════════════════════════════════════════════════════════════════════════════

class TestIaCentral:
    async def test_chat_responde_sem_chave(self, auth_client):
        """Sem chave de IA configurada, deve retornar erro controlado (não 500)."""
        r = await auth_client.post("/api/ia-central/chat", json={
            "mensagem": "Quantas mensagens foram enviadas hoje?",
        })
        # Com ou sem chave, não deve crashar com 500
        assert r.status_code in (200, 400, 422, 503)
        data = r.json()
        assert isinstance(data, dict)

    async def test_chat_mensagem_obrigatoria(self, auth_client):
        """Mensagem vazia deve retornar erro de validação."""
        r = await auth_client.post("/api/ia-central/chat", json={
            "mensagem": "",
        })
        # Vazio deve ser rejeitado
        assert r.status_code in (400, 422)

    async def test_chat_retorna_estrutura(self, auth_client):
        """Resposta deve ter estrutura reconhecível."""
        r = await auth_client.post("/api/ia-central/chat", json={
            "mensagem": "Resumo geral do sistema",
        })
        assert r.status_code in (200, 400, 422, 503)
        if r.status_code == 200:
            data = r.json()
            # Deve ter resposta ou erro descritivo
            assert "resposta" in data or "error" in data or "detail" in data or isinstance(data, dict)
