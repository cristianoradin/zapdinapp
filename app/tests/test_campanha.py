"""
app/tests/test_campanha.py — Testes de campanhas, contatos e grupos.

Cobre:
  Contatos:
    - GET  /api/campanha/contatos          → lista vazia e com dados
    - POST /api/campanha/contatos          → cria, telefone obrigatório
    - POST /api/campanha/contatos/importar → CSV válido, linha vazia ignorada
    - DELETE /api/campanha/contatos/{id}   → remove e 401 sem auth

  Grupos:
    - POST /api/campanha/grupos            → cria grupo, nome obrigatório
    - GET  /api/campanha/grupos            → lista grupos
    - PUT  /api/campanha/grupos/{id}       → renomeia
    - DELETE /api/campanha/grupos/{id}     → remove
    - POST /api/campanha/grupos/{id}/contatos → adiciona contatos
    - DELETE /api/campanha/grupos/{id}/contatos/{cid} → remove do grupo

  Campanhas:
    - POST /api/campanha                   → cria draft, cria scheduled
    - GET  /api/campanha                   → lista, filtra por status
    - DELETE /api/campanha/{id}            → remove campanha
    - POST /api/campanha/{id}/iniciar      → 400 sem contatos
    - POST /api/campanha/{id}/iniciar      → ok com contatos disponíveis
    - POST /api/campanha/{id}/pausar       → pausa campanha running
    - GET  /api/campanha/{id}/progresso    → 404 campanha inexistente

  Auth:
    - Todos os endpoints → 401 sem cookie
"""
import io
import pytest
import pytest_asyncio


pytestmark = pytest.mark.asyncio


# ── helpers ───────────────────────────────────────────────────────────────────

async def _criar_contato(client, phone="11999990001", nome="Contato Teste"):
    r = await client.post("/api/campanha/contatos", json={"phone": phone, "nome": nome})
    assert r.status_code == 200
    return r.json()["id"]


async def _criar_campanha(client, nome="Campanha Teste", tipo="text", mensagem="Olá {nome}!"):
    r = await client.post("/api/campanha", json={"nome": nome, "tipo": tipo, "mensagem": mensagem})
    assert r.status_code == 200
    return r.json()["id"]


# ── Autenticação ──────────────────────────────────────────────────────────────

class TestAuth:
    async def test_contatos_sem_auth(self, client):
        assert (await client.get("/api/campanha/contatos")).status_code == 401

    async def test_grupos_sem_auth(self, client):
        assert (await client.get("/api/campanha/grupos")).status_code == 401

    async def test_campanhas_sem_auth(self, client):
        assert (await client.get("/api/campanha")).status_code == 401

    async def test_criar_contato_sem_auth(self, client):
        r = await client.post("/api/campanha/contatos", json={"phone": "11999990000"})
        assert r.status_code == 401


# ── Contatos ──────────────────────────────────────────────────────────────────

class TestContatos:
    async def test_lista_vazia(self, auth_client):
        r = await auth_client.get("/api/campanha/contatos")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_cria_contato(self, auth_client):
        r = await auth_client.post("/api/campanha/contatos", json={
            "phone": "11999990001",
            "nome": "João Silva",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "id" in data

    async def test_telefone_obrigatorio(self, auth_client):
        r = await auth_client.post("/api/campanha/contatos", json={"phone": "", "nome": "Sem Phone"})
        assert r.status_code == 400

    async def test_upsert_mesmo_telefone(self, auth_client):
        """Mesmo telefone deve atualizar, não duplicar."""
        r1 = await auth_client.post("/api/campanha/contatos", json={"phone": "11888880001", "nome": "A"})
        r2 = await auth_client.post("/api/campanha/contatos", json={"phone": "11888880001", "nome": "B"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        # Lista deve ter apenas 1 entrada com este número
        r3 = await auth_client.get("/api/campanha/contatos?q=11888880001")
        assert len(r3.json()) == 1

    async def test_deleta_contato(self, auth_client):
        cid = await _criar_contato(auth_client, "11777770001")
        r = await auth_client.delete(f"/api/campanha/contatos/{cid}")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    async def test_busca_por_nome(self, auth_client):
        await _criar_contato(auth_client, "11666660001", "Maria Buscável")
        r = await auth_client.get("/api/campanha/contatos?q=Buscável")
        assert r.status_code == 200
        phones = [c["phone"] for c in r.json()]
        assert "11666660001" in phones

    async def test_importar_csv(self, auth_client):
        csv_content = b"11555550001,Carlos\n11555550002,Ana\n\n# comentario\n"
        r = await auth_client.post(
            "/api/campanha/contatos/importar",
            files={"file": ("contatos.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["importados"] == 2

    async def test_importar_csv_vazio(self, auth_client):
        r = await auth_client.post(
            "/api/campanha/contatos/importar",
            files={"file": ("vazio.csv", io.BytesIO(b"\n# apenas comentarios\n"), "text/csv")},
        )
        assert r.status_code == 200
        assert r.json()["importados"] == 0


# ── Grupos ────────────────────────────────────────────────────────────────────

class TestGrupos:
    async def test_cria_grupo(self, auth_client):
        r = await auth_client.post("/api/campanha/grupos", json={"nome": "VIP"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "id" in data

    async def test_nome_obrigatorio(self, auth_client):
        r = await auth_client.post("/api/campanha/grupos", json={"nome": ""})
        assert r.status_code == 400

    async def test_lista_grupos(self, auth_client):
        await auth_client.post("/api/campanha/grupos", json={"nome": "Grupo Lista"})
        r = await auth_client.get("/api/campanha/grupos")
        assert r.status_code == 200
        nomes = [g["nome"] for g in r.json()]
        assert "Grupo Lista" in nomes

    async def test_renomeia_grupo(self, auth_client):
        r = await auth_client.post("/api/campanha/grupos", json={"nome": "Antigo"})
        gid = r.json()["id"]
        r2 = await auth_client.put(f"/api/campanha/grupos/{gid}", json={"nome": "Novo Nome"})
        assert r2.status_code == 200

    async def test_deleta_grupo(self, auth_client):
        r = await auth_client.post("/api/campanha/grupos", json={"nome": "Para Deletar"})
        gid = r.json()["id"]
        r2 = await auth_client.delete(f"/api/campanha/grupos/{gid}")
        assert r2.status_code == 200
        assert r2.json()["ok"] is True

    async def test_adiciona_contato_ao_grupo(self, auth_client):
        # Cria grupo e contato
        gid = (await auth_client.post("/api/campanha/grupos", json={"nome": "G-Add"})).json()["id"]
        cid = await _criar_contato(auth_client, "11444440001", "Para Grupo")

        r = await auth_client.post(
            f"/api/campanha/grupos/{gid}/contatos",
            json={"contato_ids": [cid]},
        )
        assert r.status_code == 200
        assert r.json()["adicionados"] >= 1

    async def test_adiciona_a_grupo_inexistente_retorna_404(self, auth_client):
        r = await auth_client.post(
            "/api/campanha/grupos/99999/contatos",
            json={"contato_ids": [1]},
        )
        assert r.status_code == 404

    async def test_lista_contatos_do_grupo(self, auth_client):
        gid = (await auth_client.post("/api/campanha/grupos", json={"nome": "G-List"})).json()["id"]
        cid = await _criar_contato(auth_client, "11333330001", "No Grupo")
        await auth_client.post(f"/api/campanha/grupos/{gid}/contatos", json={"contato_ids": [cid]})

        r = await auth_client.get(f"/api/campanha/grupos/{gid}/contatos")
        assert r.status_code == 200
        phones = [c["phone"] for c in r.json()]
        assert "11333330001" in phones

    async def test_remove_contato_do_grupo(self, auth_client):
        gid = (await auth_client.post("/api/campanha/grupos", json={"nome": "G-Remove"})).json()["id"]
        cid = await _criar_contato(auth_client, "11222220001", "Remove Me")
        await auth_client.post(f"/api/campanha/grupos/{gid}/contatos", json={"contato_ids": [cid]})

        r = await auth_client.delete(f"/api/campanha/grupos/{gid}/contatos/{cid}")
        assert r.status_code == 200


# ── Campanhas ─────────────────────────────────────────────────────────────────

class TestCampanhas:
    async def test_cria_campanha_draft(self, auth_client):
        r = await auth_client.post("/api/campanha", json={
            "nome": "Campanha Draft",
            "tipo": "text",
            "mensagem": "Olá {nome}!",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "id" in data

    async def test_cria_campanha_agendada(self, auth_client):
        r = await auth_client.post("/api/campanha", json={
            "nome": "Campanha Agendada",
            "tipo": "text",
            "mensagem": "Promoção!",
            "agendado_em": "2027-12-31T10:00:00Z",
        })
        assert r.status_code == 200

    async def test_lista_campanhas(self, auth_client):
        await _criar_campanha(auth_client, "Listável")
        r = await auth_client.get("/api/campanha")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        nomes = [c["nome"] for c in r.json()]
        assert "Listável" in nomes

    async def test_filtra_campanhas_por_status(self, auth_client):
        await _criar_campanha(auth_client, "Draft Filtro")
        r = await auth_client.get("/api/campanha?status=draft")
        assert r.status_code == 200
        for c in r.json():
            assert c["status"] in ("draft", "scheduled")

    async def test_deleta_campanha(self, auth_client):
        cid = await _criar_campanha(auth_client, "Para Deletar")
        r = await auth_client.delete(f"/api/campanha/{cid}")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Verifica remoção
        r2 = await auth_client.get("/api/campanha")
        ids = [c["id"] for c in r2.json()]
        assert cid not in ids

    async def test_iniciar_sem_contatos_retorna_400(self, auth_client, db_conn, empresa_usuario):
        """Campanha sem nenhum contato ativo não pode iniciar."""
        # Remove todos os contatos para garantir que a fila esteja vazia
        await db_conn.execute(
            "DELETE FROM contatos WHERE empresa_id = $1",
            empresa_usuario["empresa_id"],
        )
        camp_id = await _criar_campanha(auth_client, "Sem Contatos")
        r = await auth_client.post(f"/api/campanha/{camp_id}/iniciar", json={})
        assert r.status_code == 400

    async def test_iniciar_com_contatos(self, auth_client):
        """Com pelo menos um contato ativo, iniciar deve funcionar."""
        await _criar_contato(auth_client, "11111110001", "Contato Ativo")
        camp_id = await _criar_campanha(auth_client, "Com Contato")
        r = await auth_client.post(f"/api/campanha/{camp_id}/iniciar", json={})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    async def test_iniciar_campanha_ja_running_retorna_400(self, auth_client):
        await _criar_contato(auth_client, "11111110002", "Ativo 2")
        camp_id = await _criar_campanha(auth_client, "Running Twice")
        await auth_client.post(f"/api/campanha/{camp_id}/iniciar", json={})
        r = await auth_client.post(f"/api/campanha/{camp_id}/iniciar", json={})
        assert r.status_code == 400
        assert "execução" in r.json().get("detail", "").lower()

    async def test_pausar_campanha(self, auth_client):
        await _criar_contato(auth_client, "11111110003", "Ativo 3")
        camp_id = await _criar_campanha(auth_client, "Para Pausar")
        await auth_client.post(f"/api/campanha/{camp_id}/iniciar", json={})
        r = await auth_client.post(f"/api/campanha/{camp_id}/pausar")
        assert r.status_code == 200

    async def test_progresso_campanha_inexistente_retorna_404(self, auth_client):
        r = await auth_client.get("/api/campanha/99999/progresso")
        assert r.status_code == 404

    async def test_progresso_campanha_existente(self, auth_client):
        await _criar_contato(auth_client, "11111110004", "Ativo 4")
        camp_id = await _criar_campanha(auth_client, "Com Progresso")
        await auth_client.post(f"/api/campanha/{camp_id}/iniciar", json={})
        r = await auth_client.get(f"/api/campanha/{camp_id}/progresso")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data or "enviados" in data

    async def test_iniciar_com_grupo(self, auth_client):
        """Iniciar campanha selecionando grupo específico."""
        gid = (await auth_client.post("/api/campanha/grupos", json={"nome": "Grupo Camp"})).json()["id"]
        cid = await _criar_contato(auth_client, "11111110005", "No Grupo Camp")
        await auth_client.post(f"/api/campanha/grupos/{gid}/contatos", json={"contato_ids": [cid]})

        camp_id = await _criar_campanha(auth_client, "Via Grupo")
        r = await auth_client.post(f"/api/campanha/{camp_id}/iniciar", json={"grupo_id": gid})
        assert r.status_code == 200

    async def test_dashboard_retorna_estrutura(self, auth_client):
        r = await auth_client.get("/api/campanha/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "resumo" in data
        assert "por_hora" in data
        assert "por_dia" in data
        assert "campanhas" in data
