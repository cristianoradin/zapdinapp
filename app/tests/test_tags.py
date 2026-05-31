"""app/tests/test_tags.py — Etiquetas (tags) do chatbot."""
import pytest
pytestmark = pytest.mark.asyncio


class TestTags:
    async def test_cria_e_lista_tag(self, auth_client, empresa_usuario):
        r = await auth_client.post("/api/chatbot/tags", json={"label": "VIP", "cor": "#16A34A"})
        assert r.status_code == 200
        assert r.json()["id"] is not None       # regressão: RETURNING id não pode ser null
        r2 = await auth_client.get("/api/chatbot/tags")
        assert r2.status_code == 200
        assert any(t["label"] == "VIP" for t in r2.json())

    async def test_label_vazio_422(self, auth_client, empresa_usuario):
        r = await auth_client.post("/api/chatbot/tags", json={"label": "  "})
        assert r.status_code == 422

    async def test_atribui_e_remove_do_contato(self, auth_client, empresa_usuario):
        tag = (await auth_client.post("/api/chatbot/tags", json={"label": "Cliente"})).json()
        phone = "11999990000"
        r = await auth_client.post(f"/api/chatbot/contato/{phone}/tags", json={"tag_id": tag["id"]})
        assert r.status_code == 200
        got = (await auth_client.get(f"/api/chatbot/contato/{phone}/tags")).json()
        assert any(t["id"] == tag["id"] for t in got)
        # remove
        r2 = await auth_client.delete(f"/api/chatbot/contato/{phone}/tags/{tag['id']}")
        assert r2.status_code == 200
        got2 = (await auth_client.get(f"/api/chatbot/contato/{phone}/tags")).json()
        assert not any(t["id"] == tag["id"] for t in got2)

    async def test_atribui_tag_inexistente_404(self, auth_client, empresa_usuario):
        r = await auth_client.post("/api/chatbot/contato/11999990000/tags", json={"tag_id": 999999})
        assert r.status_code == 404

    async def test_tags_sem_auth_401(self, client):
        r = await client.get("/api/chatbot/tags")
        assert r.status_code == 401


class TestRespostasRapidas:
    async def test_cria_lista_remove(self, auth_client, empresa_usuario):
        r = await auth_client.post("/api/chatbot/respostas-rapidas", json={"atalho": "oi", "texto": "Olá!"})
        assert r.status_code == 200 and r.json()["id"] is not None
        rid = r.json()["id"]
        lst = (await auth_client.get("/api/chatbot/respostas-rapidas")).json()
        assert any(x["atalho"] == "oi" for x in lst)
        d = await auth_client.delete(f"/api/chatbot/respostas-rapidas/{rid}")
        assert d.status_code == 200

    async def test_campos_obrigatorios_422(self, auth_client, empresa_usuario):
        r = await auth_client.post("/api/chatbot/respostas-rapidas", json={"atalho": " ", "texto": " "})
        assert r.status_code == 422

    async def test_encerrar_atendimento(self, auth_client, empresa_usuario):
        r = await auth_client.patch("/api/chatbot/contato/11999990000/encerrar")
        assert r.status_code == 200

    async def test_respostas_sem_auth_401(self, client):
        r = await client.get("/api/chatbot/respostas-rapidas")
        assert r.status_code == 401
