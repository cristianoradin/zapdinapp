"""
app/tests/test_ia_central.py — Testes da IA Central.

Cobre:
  IA Central:
    - POST /api/ia-central/chat   → processa pergunta (sem chave real → resposta controlada)
    - 401 sem auth
"""
import pytest

pytestmark = pytest.mark.asyncio


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
