"""Testes do roteamento híbrido — EvoSession.evolution_url override."""
import pytest
from app.services.evolution_service import EvoSession, EvoManager, _url
from app.core.config import settings


class TestEvoSessionUrl:
    def test_sem_evolution_url_usa_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "evolution_url", "http://servidor:8080")
        s = EvoSession("sess1", "Teste", 1)
        assert s.evolution_url is None
        assert s._url("message/sendText/x") == "http://servidor:8080/message/sendText/x"

    def test_com_evolution_url_usa_custom(self, monkeypatch):
        monkeypatch.setattr(settings, "evolution_url", "http://servidor:8080")
        s = EvoSession("sess2", "Cliente", 1, evolution_url="http://posto-cliente:8080")
        assert s.evolution_url == "http://posto-cliente:8080"
        assert s._url("message/sendText/x") == "http://posto-cliente:8080/message/sendText/x"

    def test_evolution_url_string_vazia_vira_none(self):
        s = EvoSession("sess3", "X", 1, evolution_url="")
        assert s.evolution_url is None

    def test_evolution_url_so_espacos_vira_none(self):
        s = EvoSession("sess4", "X", 1, evolution_url="   ")
        assert s.evolution_url is None

    def test_trailing_slash_normalizado(self):
        s = EvoSession("sess5", "X", 1, evolution_url="http://posto:8080/")
        # trailing slash removido no _url()
        assert s._url("a") == "http://posto:8080/a"


class TestEvoManagerRouteamento:
    def test_url_for_inst_sessao_nao_registrada_usa_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "evolution_url", "http://servidor:8080")
        m = EvoManager()
        # Sessão "inst-fake" não está no _inst_index → fallback global
        assert m._url_for_inst("inst-fake", "instance/x") == "http://servidor:8080/instance/x"

    def test_url_for_inst_com_sessao_custom(self, monkeypatch):
        monkeypatch.setattr(settings, "evolution_url", "http://servidor:8080")
        m = EvoManager()
        sess = EvoSession("s1", "Cliente", 1, evolution_url="http://posto:8080")
        m._inst_index["e1_s1"] = sess
        assert m._url_for_inst("e1_s1", "message/sendText/e1_s1") == \
               "http://posto:8080/message/sendText/e1_s1"

    def test_url_for_inst_sessao_sem_custom_url(self, monkeypatch):
        monkeypatch.setattr(settings, "evolution_url", "http://servidor:8080")
        m = EvoManager()
        sess = EvoSession("s2", "Remoto", 1)  # sem evolution_url
        m._inst_index["e1_s2"] = sess
        assert m._url_for_inst("e1_s2", "instance/x") == "http://servidor:8080/instance/x"


# ── Testes do endpoint POST /api/sessoes com evolution_url ──────────────────
import pytest_asyncio
pytestmark = pytest.mark.asyncio


class TestCriarSessaoHibrido:
    async def test_cria_sessao_modo_servidor_padrao(self, auth_client, empresa_usuario):
        r = await auth_client.post("/api/sessoes", json={"nome": "Servidor X"})
        assert r.status_code == 201, r.text
        d = r.json()
        assert d.get("evolution_url") is None  # modo servidor

    async def test_cria_sessao_modo_local_com_url(self, auth_client, empresa_usuario):
        r = await auth_client.post("/api/sessoes",
            json={"nome": "Local Y", "evolution_url": "http://posto-cliente:8080"})
        assert r.status_code == 201
        assert r.json()["evolution_url"] == "http://posto-cliente:8080"

    async def test_cria_sessao_url_vazia_vira_servidor(self, auth_client, empresa_usuario):
        r = await auth_client.post("/api/sessoes",
            json={"nome": "Z", "evolution_url": "   "})
        assert r.status_code == 201
        assert r.json().get("evolution_url") is None

    async def test_cria_sessao_url_invalida_422(self, auth_client, empresa_usuario):
        r = await auth_client.post("/api/sessoes",
            json={"nome": "X", "evolution_url": "192.168.1.1:8080"})  # sem http://
        assert r.status_code == 422

    async def test_lista_retorna_evolution_url(self, auth_client, empresa_usuario):
        await auth_client.post("/api/sessoes",
            json={"nome": "Local A", "evolution_url": "http://cliente:8080"})
        r = await auth_client.get("/api/sessoes")
        assert r.status_code == 200
        # Pelo menos 1 sessão deve ter evolution_url preenchido
        encontrou = [s for s in r.json() if s.get("evolution_url") == "http://cliente:8080"]
        assert len(encontrou) >= 1


class TestModosPermitidos:
    """Backend enforça os modos definidos no Monitor — não confia só no frontend."""

    async def _set_modos(self, empresa_id, csv):
        import asyncpg
        from app.tests.conftest import _TEST_DB_URL
        conn = await asyncpg.connect(_TEST_DB_URL)
        try:
            await conn.execute("UPDATE empresas SET modos_conexao=$1 WHERE id=$2", csv, empresa_id)
        finally:
            await conn.close()

    async def test_so_agente_bloqueia_servidor(self, auth_client, empresa_usuario):
        await self._set_modos(empresa_usuario["empresa_id"], "agente")
        try:
            # servidor (evo_url=None) deve ser rejeitado
            r = await auth_client.post("/api/sessoes", json={"nome": "Srv"})
            assert r.status_code == 403, r.text
            # local também bloqueado
            r2 = await auth_client.post("/api/sessoes",
                json={"nome": "Loc", "evolution_url": "http://x:8080"})
            assert r2.status_code == 403
            # agente permitido
            r3 = await auth_client.post("/api/sessoes",
                json={"nome": "Ag", "evolution_url": "agent://"})
            assert r3.status_code == 201, r3.text
        finally:
            await self._set_modos(empresa_usuario["empresa_id"], "servidor,local,agente")

    async def test_endpoint_modos_reflete_db(self, auth_client, empresa_usuario):
        await self._set_modos(empresa_usuario["empresa_id"], "agente")
        try:
            r = await auth_client.get("/api/sessoes/modos-permitidos")
            assert r.status_code == 200
            assert r.json()["modos"] == ["agente"]
        finally:
            await self._set_modos(empresa_usuario["empresa_id"], "servidor,local,agente")
