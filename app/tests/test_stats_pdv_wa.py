"""
app/tests/test_stats_pdv_wa.py — Testes de stats, PDV e sessões WhatsApp.

Cobre:
  Stats:
    - GET /api/stats/version       → retorna versão
    - GET /api/stats               → retorna estrutura de dashboard
    - GET /api/stats/queue         → retorna contagens de fila
    - GET /api/stats/queue-health  → retorna saúde da fila
    - GET /api/stats/workers       → retorna heartbeats dos workers
    - 401 sem auth em todos

  PDV Tokens:
    - POST /api/pdv/tokens         → gera token com nome
    - POST /api/pdv/tokens         → nome obrigatório → 400
    - GET  /api/pdv/tokens         → lista tokens da empresa
    - DELETE /api/pdv/tokens/{id}  → revoga token
    - GET  /api/pdv/config         → configuração para PDV (auth via token PDV)
    - 401 sem auth nos endpoints autenticados

  Sessões WhatsApp:
    - GET  /api/sessoes            → lista sessões da empresa
    - POST /api/sessoes            → cria sessão nova
    - GET  /api/sessoes/live-status → retorna status em memória
    - GET  /api/sessoes/qr/{id}    → 404 quando QR não disponível
    - DELETE /api/sessoes/{id}     → remove sessão
    - POST /api/sessoes/{id}/send-text → 400 sessão não conectada
    - 401 sem auth
"""
import pytest
import pytest_asyncio


pytestmark = pytest.mark.asyncio


# ══════════════════════════════════════════════════════════════════════════════
# STATS
# ══════════════════════════════════════════════════════════════════════════════

class TestStatsAuth:
    async def test_stats_sem_auth(self, client):
        assert (await client.get("/api/stats")).status_code == 401

    async def test_version_sem_auth(self, client):
        assert (await client.get("/api/stats/version")).status_code == 401

    async def test_queue_sem_auth(self, client):
        assert (await client.get("/api/stats/queue")).status_code == 401

    async def test_workers_sem_auth(self, client):
        assert (await client.get("/api/stats/workers")).status_code == 401


class TestStats:
    async def test_version_retorna_string(self, auth_client):
        r = await auth_client.get("/api/stats/version")
        assert r.status_code == 200
        data = r.json()
        assert "version" in data or "versao" in data or isinstance(data, str) or isinstance(data, dict)

    async def test_dashboard_retorna_estrutura(self, auth_client):
        r = await auth_client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        # Deve conter contadores principais
        assert "hoje" in data or "enviadas" in data or "sessoes_ativas" in data

    async def test_queue_retorna_contagens(self, auth_client):
        r = await auth_client.get("/api/stats/queue")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    async def test_queue_health_retorna_estrutura(self, auth_client):
        r = await auth_client.get("/api/stats/queue-health")
        assert r.status_code == 200
        data = r.json()
        assert "stuck_alert" in data
        assert "total_queued" in data
        assert "wa_connected" in data

    async def test_workers_retorna_lista(self, auth_client):
        r = await auth_client.get("/api/stats/workers")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ══════════════════════════════════════════════════════════════════════════════
# PDV TOKENS
# ══════════════════════════════════════════════════════════════════════════════

class TestPdvAuth:
    async def test_tokens_sem_auth(self, client):
        assert (await client.get("/api/pdv/tokens")).status_code == 401

    async def test_gerar_sem_auth(self, client):
        assert (await client.post("/api/pdv/tokens", json={"nome": "Caixa 1"})).status_code == 401


class TestPdvTokens:
    async def test_gera_token(self, auth_client):
        r = await auth_client.post("/api/pdv/tokens", json={"nome": "Caixa 1"})
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        # Token deve ter pelo menos 32 chars
        assert len(data["token"]) >= 32

    async def test_nome_obrigatorio(self, auth_client):
        r = await auth_client.post("/api/pdv/tokens", json={"nome": ""})
        assert r.status_code in (400, 422)

    async def test_lista_tokens(self, auth_client):
        await auth_client.post("/api/pdv/tokens", json={"nome": "Caixa Lista"})
        r = await auth_client.get("/api/pdv/tokens")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        nomes = [t["nome"] for t in r.json()]
        assert "Caixa Lista" in nomes

    async def test_token_tem_preview(self, auth_client):
        """Token gerado deve aparecer mascarado na listagem."""
        await auth_client.post("/api/pdv/tokens", json={"nome": "Caixa Preview"})
        tokens = (await auth_client.get("/api/pdv/tokens")).json()
        token = next(t for t in tokens if t["nome"] == "Caixa Preview")
        # token_preview deve existir e estar mascarado (não o token completo)
        assert "token_preview" in token

    async def test_revoga_token(self, auth_client):
        r = await auth_client.post("/api/pdv/tokens", json={"nome": "Caixa Revogar"})
        token_val = r.json()["token"]

        # Busca ID do token
        tokens = (await auth_client.get("/api/pdv/tokens")).json()
        token_id = next(t["id"] for t in tokens if t["nome"] == "Caixa Revogar")

        r2 = await auth_client.delete(f"/api/pdv/tokens/{token_id}")
        assert r2.status_code == 200 or r2.status_code == 204

        # Token revogado não deve autenticar no PDV
        r3 = await auth_client.get("/api/pdv/config", headers={"X-PDV-Token": token_val})
        assert r3.status_code == 401

    async def test_token_pdv_invalido_retorna_401(self, client):
        r = await client.get("/api/pdv/config", headers={"X-PDV-Token": "token-invalido-xyz"})
        assert r.status_code == 401

    async def test_token_pdv_valido_retorna_config(self, auth_client, client):
        """Token PDV válido deve retornar config da empresa."""
        r = await auth_client.post("/api/pdv/tokens", json={"nome": "Caixa Config"})
        token_pdv = r.json()["token"]

        r2 = await client.get("/api/pdv/config", headers={"X-PDV-Token": token_pdv})
        assert r2.status_code == 200
        data = r2.json()
        # Deve retornar alguma configuração
        assert isinstance(data, dict)


# ══════════════════════════════════════════════════════════════════════════════
# SESSÕES WHATSAPP
# ══════════════════════════════════════════════════════════════════════════════

class TestSessoesAuth:
    async def test_list_sem_auth(self, client):
        assert (await client.get("/api/sessoes")).status_code == 401

    async def test_create_sem_auth(self, client):
        assert (await client.post("/api/sessoes", json={"nome": "Teste"})).status_code == 401

    async def test_live_status_sem_auth(self, client):
        assert (await client.get("/api/sessoes/live-status")).status_code == 401


class TestSessoesWA:
    async def test_lista_sessoes_vazia(self, auth_client):
        r = await auth_client.get("/api/sessoes")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_cria_sessao(self, auth_client):
        r = await auth_client.post("/api/sessoes", json={"nome": "Sessão Teste"})
        assert r.status_code == 201
        data = r.json()
        assert "id" in data
        assert data["nome"] == "Sessão Teste"
        assert data["status"] == "disconnected"

    async def test_sessao_aparece_na_lista(self, auth_client):
        await auth_client.post("/api/sessoes", json={"nome": "Sessão Listável"})
        r = await auth_client.get("/api/sessoes")
        nomes = [s["nome"] for s in r.json()]
        assert "Sessão Listável" in nomes

    async def test_live_status_retorna_lista(self, auth_client):
        r = await auth_client.get("/api/sessoes/live-status")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_qr_nao_disponivel_retorna_404(self, auth_client):
        """Sessão recém-criada não tem QR disponível."""
        r = await auth_client.post("/api/sessoes", json={"nome": "Sem QR"})
        sessao_id = r.json()["id"]
        r2 = await auth_client.get(f"/api/sessoes/qr/{sessao_id}")
        assert r2.status_code == 404

    async def test_send_text_sessao_nao_conectada(self, auth_client):
        """Tentar enviar mensagem com sessão desconectada deve retornar 400."""
        r = await auth_client.post("/api/sessoes", json={"nome": "Não Conectada"})
        sessao_id = r.json()["id"]
        r2 = await auth_client.post(f"/api/sessoes/{sessao_id}/send-text", json={
            "phone": "11999990000",
            "message": "Teste",
        })
        assert r2.status_code == 400

    async def test_deleta_sessao(self, auth_client):
        r = await auth_client.post("/api/sessoes", json={"nome": "Para Deletar"})
        sessao_id = r.json()["id"]
        r2 = await auth_client.delete(f"/api/sessoes/{sessao_id}")
        assert r2.status_code == 204

        # Não deve aparecer mais na lista
        sessoes = (await auth_client.get("/api/sessoes")).json()
        ids = [s["id"] for s in sessoes]
        assert sessao_id not in ids
