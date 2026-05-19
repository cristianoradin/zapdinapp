"""
app/tests/test_arquivos.py — Testes do módulo de arquivos enviados.

Cobre:
  - GET /api/arquivos → lista arquivos da empresa (vazia ou com dados)
  - 401 sem auth
"""
import pytest

pytestmark = pytest.mark.asyncio


class TestArquivosAuth:
    async def test_list_sem_auth(self, client):
        assert (await client.get("/api/arquivos")).status_code == 401


class TestArquivos:
    async def test_lista_arquivos(self, auth_client):
        r = await auth_client.get("/api/arquivos")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    async def test_campos_do_arquivo(self, auth_client, db_conn, empresa_usuario):
        """Se houver arquivos no banco, devem ter os campos esperados."""
        await db_conn.execute(
            """INSERT INTO arquivos
               (empresa_id, nome_original, tamanho, destinatario, status)
               VALUES ($1, $2, $3, $4, $5)""",
            empresa_usuario["empresa_id"],
            "documento.pdf",
            1024,
            "11999990000",
            "queued",
        )
        r = await auth_client.get("/api/arquivos")
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        arquivo = data[0]
        assert "nome_original" in arquivo
        assert "status" in arquivo
        assert "destinatario" in arquivo
