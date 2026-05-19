"""
app/tests/test_avaliacao.py — Testes do endpoint de avaliação.

Cobre:
  - POST /api/avaliacao/responder     → nota válida (1-5) aceita
  - POST /api/avaliacao/responder     → nota=0  → 422 (Field ge=1)
  - POST /api/avaliacao/responder     → nota=6  → 422 (Field le=5)
  - POST /api/avaliacao/responder     → token inválido → 404
  - POST /api/avaliacao/responder     → token DEMO  → 200 (sem gravar)
  - GET  /avaliacao                   → sem token → renderiza "Link inválido"
  - GET  /avaliacao?t=DEMO            → renderiza formulário demo
"""
import pytest
import pytest_asyncio
import secrets


pytestmark = pytest.mark.asyncio


class TestAvaliacaoResponder:
    async def test_token_invalido_retorna_404(self, client):
        r = await client.post("/api/avaliacao/responder", json={
            "token": "token-inexistente-xyzabc",
            "nota": 5,
            "comentario": "",
        })
        assert r.status_code == 404
        assert "Token inválido" in r.json().get("detail", "")

    async def test_nota_zero_retorna_422(self, client):
        r = await client.post("/api/avaliacao/responder", json={
            "token": "qualquer-token",
            "nota": 0,
        })
        assert r.status_code == 422

    async def test_nota_seis_retorna_422(self, client):
        r = await client.post("/api/avaliacao/responder", json={
            "token": "qualquer-token",
            "nota": 6,
        })
        assert r.status_code == 422

    async def test_nota_negativa_retorna_422(self, client):
        r = await client.post("/api/avaliacao/responder", json={
            "token": "qualquer-token",
            "nota": -1,
        })
        assert r.status_code == 422

    async def test_token_muito_longo_retorna_422(self, client):
        r = await client.post("/api/avaliacao/responder", json={
            "token": "x" * 200,   # max_length=128
            "nota": 5,
        })
        assert r.status_code == 422

    async def test_demo_token_aceito_sem_gravar(self, client):
        r = await client.post("/api/avaliacao/responder", json={
            "token": "DEMO",
            "nota": 4,
            "comentario": "Teste",
        })
        assert r.status_code == 200
        assert r.json().get("ok") is True

    async def test_avaliacao_completa(self, client, db_conn, empresa_usuario):
        """Cria avaliação pendente no banco e responde com nota válida."""
        token = secrets.token_hex(16)
        await db_conn.execute(
            """INSERT INTO avaliacoes
               (empresa_id, token, phone, nome_cliente, vendedor)
               VALUES ($1, $2, $3, $4, $5)""",
            empresa_usuario["empresa_id"], token,
            "11999990000", "Cliente Teste", "Vendedor A",
        )

        r = await client.post("/api/avaliacao/responder", json={
            "token": token,
            "nota": 5,
            "comentario": "Excelente atendimento!",
        })
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # Verifica que nota foi gravada
        row = await db_conn.fetchrow(
            "SELECT nota, comentario FROM avaliacoes WHERE token = $1", token
        )
        assert row["nota"] == 5
        assert row["comentario"] == "Excelente atendimento!"

    async def test_dupla_resposta_retorna_409(self, client, db_conn, empresa_usuario):
        """Segunda resposta para o mesmo token deve retornar 409."""
        token = secrets.token_hex(16)
        await db_conn.execute(
            """INSERT INTO avaliacoes
               (empresa_id, token, phone, nome_cliente, vendedor, nota)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            empresa_usuario["empresa_id"], token,
            "11999990001", "Cliente 2", "Vendedor B", 3,
        )

        r = await client.post("/api/avaliacao/responder", json={
            "token": token,
            "nota": 5,
        })
        assert r.status_code == 409
        assert "já registrada" in r.json().get("detail", "")


class TestAvaliacaoPage:
    async def test_sem_token_renderiza_invalido(self, client):
        r = await client.get("/avaliacao")
        assert r.status_code == 200
        assert "Link inválido" in r.text or "inválido" in r.text.lower()

    async def test_demo_renderiza_formulario(self, client):
        r = await client.get("/avaliacao?t=DEMO")
        assert r.status_code == 200
        assert "avaliacao" in r.text.lower() or "atendimento" in r.text.lower()
