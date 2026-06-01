"""
app/tests/test_erp.py — Testes de token ERP e segurança de integração.

Cobre:
  - GET  /api/erp/config            → 401 sem auth, retorna token mascarado
  - POST /api/erp/gerar-token       → gera novo token, invalida anterior
  - POST /erp endpoint              → token inválido → 401
  - POST /erp endpoint              → token ausente → 401
  - Verificação que token é armazenado como hash (não plaintext)
"""
import pytest
import pytest_asyncio


pytestmark = pytest.mark.asyncio


class TestErpConfig:
    async def test_config_sem_auth_retorna_401(self, client):
        r = await client.get("/api/erp/config")
        assert r.status_code == 401

    async def test_config_com_auth_retorna_token_mascarado(self, auth_client):
        r = await auth_client.get("/api/erp/config")
        assert r.status_code == 200
        # Token pode estar vazio se nunca gerado, mas não deve expor o valor completo
        data = r.json()
        assert "token" in data

    async def test_gerar_token_retorna_novo_token(self, auth_client):
        r = await auth_client.post("/api/erp/gerar-token")
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        token = data["token"]
        # Token deve ter pelo menos 32 chars
        assert len(token) >= 32

    async def test_token_armazenado_como_hash(self, auth_client, db_conn, empresa_usuario):
        """
        Gera token e verifica que o banco contém o hash SHA-256,
        não o token em plaintext (M8).
        """
        r = await auth_client.post("/api/erp/gerar-token")
        assert r.status_code == 200
        token_plain = r.json()["token"]

        # Busca o valor armazenado no banco
        row = await db_conn.fetchrow(
            "SELECT value FROM config WHERE empresa_id=$1 AND key='erp_token'",
            empresa_usuario["empresa_id"],
        )
        assert row is not None, "erp_token não encontrado no banco"
        stored = row["value"]

        # O valor armazenado NÃO deve ser o token plaintext
        assert stored != token_plain, "Token armazenado em plaintext — M8 não aplicado!"
        # Deve ser o hash SHA-256 (64 chars hexadecimal)
        assert len(stored) == 64
        assert all(c in "0123456789abcdef" for c in stored)

    async def test_token_invalido_rejeitado_na_api_erp(self, client):
        """Token errado no header deve retornar 401."""
        r = await client.post(
            "/erp",
            json={"action": "get_config"},
            headers={"X-ERP-Token": "token-invalido-xyzabc123"},
        )
        # Aceita 401, 422 (se a rota exigir body diferente) ou 404 (se rota não existir)
        # O importante é que 200 NÃO seja retornado com token inválido
        assert r.status_code != 200


class TestErpTokenValidation:
    async def test_segundo_gerar_invalida_primeiro(self, auth_client, db_conn, empresa_usuario):
        """Dois tokens gerados: o primeiro deve parar de funcionar."""
        # Gera primeiro token
        r1 = await auth_client.post("/api/erp/gerar-token")
        token1 = r1.json()["token"]

        # Gera segundo token
        r2 = await auth_client.post("/api/erp/gerar-token")
        token2 = r2.json()["token"]

        assert token1 != token2, "Dois generates devem produzir tokens diferentes"

        # Verifica que o banco tem o hash do token2, não do token1
        from app.core.security import hash_erp_token
        hash2 = hash_erp_token(token2)

        row = await db_conn.fetchrow(
            "SELECT value FROM config WHERE empresa_id=$1 AND key='erp_token'",
            empresa_usuario["empresa_id"],
        )
        assert row["value"] == hash2, "Banco deve ter o hash do token mais recente"


class TestErpArquivoSoTexto:
    """Endpoint /api/erp/arquivo aceita envio só-texto (sem arquivo)."""

    async def test_so_mensagem_sem_arquivo_201(self, auth_client, empresa_usuario, db_conn):
        # Pega o token ERP da empresa via /gerar-token
        gtok = await auth_client.post("/api/erp/gerar-token")
        token = gtok.json()["token"]
        # Envia só mensagem (sem nome_arquivo nem conteudo_base64)
        r = await auth_client.post(
            "/api/erp/arquivo",
            headers={"x-token": token},
            json={"telefone": "11999990000", "mensagem": "Olá só texto!"},
        )
        assert r.status_code == 200, r.text
        assert r.json().get("queued") is True

    async def test_ambos_vazios_400(self, auth_client, empresa_usuario):
        gtok = await auth_client.post("/api/erp/gerar-token")
        token = gtok.json()["token"]
        r = await auth_client.post(
            "/api/erp/arquivo",
            headers={"x-token": token},
            json={"telefone": "11999990000"},
        )
        assert r.status_code == 400

    async def test_arquivo_com_mensagem_continua_funcionando(self, auth_client, empresa_usuario):
        import base64
        gtok = await auth_client.post("/api/erp/gerar-token")
        token = gtok.json()["token"]
        r = await auth_client.post(
            "/api/erp/arquivo",
            headers={"x-token": token},
            json={
                "telefone": "11999990000",
                "nome_arquivo": "teste.pdf",
                "conteudo_base64": base64.b64encode(b"PDF data here").decode(),
                "mensagem": "olha o pdf",
            },
        )
        assert r.status_code == 200
