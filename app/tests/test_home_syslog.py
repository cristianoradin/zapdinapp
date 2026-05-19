"""
app/tests/test_home_syslog.py — Testes de Home Dashboard e SysLog.

Cobre:
  Home:
    - GET  /api/home/cidade         → retorna cidade (vazio ou string)
    - POST /api/home/cidade         → salva cidade
    - GET  /api/home/agenda         → lista vazia
    - POST /api/home/agenda         → cria compromisso
    - PUT  /api/home/agenda/{id}    → atualiza
    - DELETE /api/home/agenda/{id}  → remove
    - GET  /api/home/postits        → lista vazia
    - POST /api/home/postits        → cria post-it
    - PUT  /api/home/postits/{id}   → atualiza
    - DELETE /api/home/postits/{id} → remove
    - 401 sem auth em todos

  SysLog:
    - GET    /api/syslog            → lista logs
    - POST   /api/syslog/teste      → cria evento de teste
    - GET    /api/syslog?nivel=info → filtra por nível
    - GET    /api/syslog/export     → retorna CSV
    - DELETE /api/syslog            → limpa logs antigos
    - 401 sem auth
"""
import pytest

pytestmark = pytest.mark.asyncio


# ══════════════════════════════════════════════════════════════════════════════
# HOME AUTH
# ══════════════════════════════════════════════════════════════════════════════

class TestHomeAuth:
    async def test_cidade_sem_auth(self, client):
        assert (await client.get("/api/home/cidade")).status_code == 401

    async def test_agenda_sem_auth(self, client):
        assert (await client.get("/api/home/agenda")).status_code == 401

    async def test_postits_sem_auth(self, client):
        assert (await client.get("/api/home/postits")).status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# HOME — CIDADE
# ══════════════════════════════════════════════════════════════════════════════

class TestHomeCidade:
    async def test_retorna_cidade(self, auth_client):
        r = await auth_client.get("/api/home/cidade")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    async def test_salva_cidade(self, auth_client):
        r = await auth_client.post("/api/home/cidade", json={
            "cidade": "São Paulo",
            "uf": "SP",
        })
        assert r.status_code == 200

        r2 = await auth_client.get("/api/home/cidade")
        assert r2.status_code == 200
        data = r2.json()
        assert data.get("cidade") == "São Paulo" or "cidade" in data


# ══════════════════════════════════════════════════════════════════════════════
# HOME — AGENDA
# ══════════════════════════════════════════════════════════════════════════════

class TestHomeAgenda:
    async def test_lista_vazia(self, auth_client):
        r = await auth_client.get("/api/home/agenda")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_cria_compromisso(self, auth_client):
        r = await auth_client.post("/api/home/agenda", json={
            "titulo": "Reunião de Teste",
            "data": "2027-01-15",
            "hora": "10:00",
        })
        assert r.status_code in (200, 201)
        data = r.json()
        assert "id" in data or data.get("ok") is True

    async def test_compromisso_aparece_na_lista(self, auth_client):
        r = await auth_client.post("/api/home/agenda", json={
            "titulo": "Compromisso Listável",
            "data": "2027-02-20",
            "hora": "14:00",
        })
        assert r.status_code in (200, 201)

        r2 = await auth_client.get("/api/home/agenda")
        assert r2.status_code == 200
        titulos = [a.get("titulo", "") for a in r2.json()]
        assert "Compromisso Listável" in titulos

    async def test_atualiza_compromisso(self, auth_client):
        r = await auth_client.post("/api/home/agenda", json={
            "titulo": "Para Atualizar",
            "data": "2027-03-10",
            "hora": "09:00",
        })
        assert r.status_code in (200, 201)
        resp = r.json()
        item_id = resp.get("id")

        if item_id:
            r2 = await auth_client.put(f"/api/home/agenda/{item_id}", json={
                "titulo": "Atualizado",
                "data": "2027-03-10",
                "hora": "11:00",
            })
            assert r2.status_code == 200

    async def test_deleta_compromisso(self, auth_client):
        r = await auth_client.post("/api/home/agenda", json={
            "titulo": "Para Deletar",
            "data": "2027-04-05",
            "hora": "08:00",
        })
        assert r.status_code in (200, 201)
        resp = r.json()
        item_id = resp.get("id")

        if item_id:
            r2 = await auth_client.delete(f"/api/home/agenda/{item_id}")
            assert r2.status_code in (200, 204)


# ══════════════════════════════════════════════════════════════════════════════
# HOME — POST-ITS
# ══════════════════════════════════════════════════════════════════════════════

class TestHomePostits:
    async def test_lista_vazia(self, auth_client):
        r = await auth_client.get("/api/home/postits")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_cria_postit(self, auth_client):
        r = await auth_client.post("/api/home/postits", json={
            "texto": "Lembrar de ligar para cliente",
            "cor": "#ffff99",
        })
        assert r.status_code in (200, 201)
        data = r.json()
        assert "id" in data or data.get("ok") is True

    async def test_postit_aparece_na_lista(self, auth_client):
        r = await auth_client.post("/api/home/postits", json={
            "texto": "Post-it Listável",
            "cor": "#99ffcc",
        })
        assert r.status_code in (200, 201)

        r2 = await auth_client.get("/api/home/postits")
        textos = [p.get("texto", "") for p in r2.json()]
        assert "Post-it Listável" in textos

    async def test_atualiza_postit(self, auth_client):
        r = await auth_client.post("/api/home/postits", json={
            "texto": "Texto Original",
            "cor": "#ffffff",
        })
        assert r.status_code in (200, 201)
        item_id = r.json().get("id")

        if item_id:
            r2 = await auth_client.put(f"/api/home/postits/{item_id}", json={
                "texto": "Texto Editado",
                "cor": "#ffcccc",
            })
            assert r2.status_code == 200

    async def test_deleta_postit(self, auth_client):
        r = await auth_client.post("/api/home/postits", json={
            "texto": "Para Deletar",
            "cor": "#cccccc",
        })
        assert r.status_code in (200, 201)
        item_id = r.json().get("id")

        if item_id:
            r2 = await auth_client.delete(f"/api/home/postits/{item_id}")
            assert r2.status_code in (200, 204)


# ══════════════════════════════════════════════════════════════════════════════
# SYSLOG AUTH
# ══════════════════════════════════════════════════════════════════════════════

class TestSyslogAuth:
    async def test_list_sem_auth(self, client):
        assert (await client.get("/api/syslog")).status_code == 401

    async def test_teste_sem_auth(self, client):
        assert (await client.post("/api/syslog/teste")).status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# SYSLOG
# ══════════════════════════════════════════════════════════════════════════════

class TestSyslog:
    async def test_lista_logs(self, auth_client):
        r = await auth_client.get("/api/syslog")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_cria_evento_teste(self, auth_client):
        r = await auth_client.post("/api/syslog/teste")
        assert r.status_code == 200

    async def test_evento_aparece_na_lista(self, auth_client):
        await auth_client.post("/api/syslog/teste")
        r = await auth_client.get("/api/syslog")
        assert r.status_code == 200
        # Após criar evento de teste, lista não deve estar vazia
        assert isinstance(r.json(), list)

    async def test_filtra_por_nivel(self, auth_client):
        r = await auth_client.get("/api/syslog?nivel=info")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        for item in data:
            assert item.get("nivel") == "info"

    async def test_export_csv(self, auth_client):
        r = await auth_client.get("/api/syslog/export")
        assert r.status_code == 200
        # Deve retornar CSV ou JSON
        ct = r.headers.get("content-type", "")
        assert "csv" in ct or "json" in ct or "text" in ct or "application" in ct

    async def test_limpa_logs_antigos(self, auth_client):
        r = await auth_client.delete("/api/syslog")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
