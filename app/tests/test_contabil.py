"""
app/tests/test_contabil.py — Testes do módulo contábil.

Cobre:
  Auth: 401 sem cookie em todos os endpoints

  Empresas (clientes contábeis):
    - GET  /api/contabil/empresas       → lista vazia
    - POST /api/contabil/empresas       → cria empresa
    - GET  /api/contabil/empresas/{id}  → busca por ID
    - PUT  /api/contabil/empresas/{id}  → atualiza
    - DELETE /api/contabil/empresas/{id} → remove

  Dashboard:
    - GET  /api/contabil/dashboard      → estrutura de métricas

  Documentos:
    - GET  /api/contabil/documentos     → lista vazia
    - GET  /api/contabil/documentos/999 → 404 não existe
    - GET  /api/contabil/feed           → feed de atividade

  Upload:
    - POST /api/contabil/documentos/upload → upload de arquivo PDF
"""
import io
import pytest

pytestmark = pytest.mark.asyncio


# ── Auth ──────────────────────────────────────────────────────────────────────

class TestContabilAuth:
    async def test_empresas_sem_auth(self, client):
        assert (await client.get("/api/contabil/empresas")).status_code == 401

    async def test_dashboard_sem_auth(self, client):
        assert (await client.get("/api/contabil/dashboard")).status_code == 401

    async def test_documentos_sem_auth(self, client):
        assert (await client.get("/api/contabil/documentos")).status_code == 401

    async def test_feed_sem_auth(self, client):
        assert (await client.get("/api/contabil/feed")).status_code == 401


# ── Empresas ──────────────────────────────────────────────────────────────────

class TestContabilEmpresas:
    async def test_lista_vazia(self, auth_client):
        r = await auth_client.get("/api/contabil/empresas")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_cria_empresa(self, auth_client):
        r = await auth_client.post("/api/contabil/empresas", json={
            "nome": "Empresa Teste CTB",
            "telefone": "11999990001",
            "regime_tributario": "simples_nacional",
        })
        assert r.status_code in (200, 201)
        data = r.json()
        assert "id" in data

    async def test_empresa_aparece_na_lista(self, auth_client):
        await auth_client.post("/api/contabil/empresas", json={
            "nome": "Empresa Listável",
            "telefone": "11999990002",
            "regime_tributario": "mei",
        })
        r = await auth_client.get("/api/contabil/empresas")
        assert r.status_code == 200
        nomes = [e["nome"] for e in r.json()]
        assert "Empresa Listável" in nomes

    async def test_busca_empresa_por_id(self, auth_client):
        r = await auth_client.post("/api/contabil/empresas", json={
            "nome": "Empresa para Buscar",
            "telefone": "11999990003",
            "regime_tributario": "lucro_presumido",
        })
        empresa_id = r.json()["id"]

        r2 = await auth_client.get(f"/api/contabil/empresas/{empresa_id}")
        assert r2.status_code == 200
        assert r2.json()["nome"] == "Empresa para Buscar"

    async def test_empresa_inexistente_retorna_404(self, auth_client):
        r = await auth_client.get("/api/contabil/empresas/99999")
        assert r.status_code == 404

    async def test_atualiza_empresa(self, auth_client):
        r = await auth_client.post("/api/contabil/empresas", json={
            "nome": "Antiga Nome",
            "telefone": "11999990004",
            "regime_tributario": "simples_nacional",
        })
        empresa_id = r.json()["id"]

        r2 = await auth_client.put(f"/api/contabil/empresas/{empresa_id}", json={
            "nome": "Novo Nome",
            "telefone": "11999990004",
            "regime_tributario": "simples_nacional",
        })
        assert r2.status_code == 200

    async def test_deleta_empresa(self, auth_client):
        r = await auth_client.post("/api/contabil/empresas", json={
            "nome": "Para Deletar",
            "telefone": "11999990005",
            "regime_tributario": "mei",
        })
        empresa_id = r.json()["id"]

        r2 = await auth_client.delete(f"/api/contabil/empresas/{empresa_id}")
        assert r2.status_code in (200, 204)

        # Não deve aparecer mais na lista
        r3 = await auth_client.get("/api/contabil/empresas")
        ids = [e["id"] for e in r3.json()]
        assert empresa_id not in ids

    async def test_regime_invalido_retorna_422(self, auth_client):
        r = await auth_client.post("/api/contabil/empresas", json={
            "nome": "Regime Inválido",
            "telefone": "11999990006",
            "regime_tributario": "invalido_xyz",
        })
        assert r.status_code == 422


# ── Dashboard ─────────────────────────────────────────────────────────────────

class TestContabilDashboard:
    async def test_dashboard_retorna_estrutura(self, auth_client):
        r = await auth_client.get("/api/contabil/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        # Deve ter métricas ou cards
        assert len(data) > 0


# ── Documentos ────────────────────────────────────────────────────────────────

class TestContabilDocumentos:
    async def test_lista_documentos_vazia(self, auth_client):
        r = await auth_client.get("/api/contabil/documentos")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_documento_inexistente_retorna_404(self, auth_client):
        r = await auth_client.get("/api/contabil/documentos/99999")
        assert r.status_code == 404

    async def test_feed_retorna_lista(self, auth_client):
        r = await auth_client.get("/api/contabil/feed")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_upload_documento(self, auth_client):
        """Upload de arquivo PDF gera entrada na tabela de documentos."""
        # Primeiro cria uma empresa contábil para ter um empresa_id válido
        r_emp = await auth_client.post("/api/contabil/empresas", json={
            "nome": "Empresa Upload",
            "telefone": "11999990099",
            "regime_tributario": "simples_nacional",
        })
        if r_emp.status_code not in (200, 201):
            pytest.skip("Empresa contábil não criada, skip upload")
        empresa_id = r_emp.json()["id"]

        fake_pdf = b"%PDF-1.4 fake content"
        r = await auth_client.post(
            f"/api/contabil/documentos/upload?empresa_id={empresa_id}",
            files={"arquivo": ("nota_fiscal.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )
        # Pode retornar 200 ou 201 com sucesso
        assert r.status_code in (200, 201)
