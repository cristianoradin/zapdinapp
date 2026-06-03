"""
app/tests/test_login_multi.py — Login multi-empresa.
Mocka o Monitor (/api/auth/empresas-do-usuario) com respx.
"""
import pytest
import respx
from httpx import Response

from app.core.config import settings

pytestmark = pytest.mark.asyncio

_MON = settings.monitor_url.rstrip("/") + "/api/auth/empresas-do-usuario"


async def _seed_segunda_empresa(db_conn):
    """Cria uma 2ª empresa local + usuário, para testar seleção entre N."""
    await db_conn.execute(
        "INSERT INTO empresas (cnpj, nome, token, ativo) VALUES ($1,$2,$3,TRUE) "
        "ON CONFLICT (cnpj) DO UPDATE SET ativo=TRUE",
        "00000000000002", "Empresa Dois", "token-dois",
    )
    row = await db_conn.fetchrow("SELECT id FROM empresas WHERE cnpj='00000000000002'")
    return row["id"]


class TestLoginMulti:
    @respx.mock
    async def test_uma_empresa_loga_direto(self, client, empresa_usuario):
        # Monitor retorna 1 empresa (a de teste) → multi:false, cookie emitido
        respx.post(_MON).mock(return_value=Response(200, json={
            "ok": True, "username": "joao", "uid": 1,
            "empresas": [{"nome": "Empresa Teste", "cnpj": "00000000000001", "token": "token-teste"}],
        }))
        r = await client.post("/api/auth/login-empresas", json={"username": "joao", "password": "x"})
        assert r.status_code == 200
        assert r.json()["multi"] is False
        assert "zapdin_session" in r.cookies or r.cookies  # cookie emitido

    @respx.mock
    async def test_duas_empresas_retorna_lista(self, client, empresa_usuario, db_conn):
        await _seed_segunda_empresa(db_conn)
        respx.post(_MON).mock(return_value=Response(200, json={
            "ok": True, "username": "joao", "uid": 1,
            "empresas": [
                {"nome": "Empresa Teste", "cnpj": "00000000000001", "token": "token-teste"},
                {"nome": "Empresa Dois",  "cnpj": "00000000000002", "token": "token-dois"},
            ],
        }))
        r = await client.post("/api/auth/login-empresas", json={"username": "joao", "password": "x"})
        assert r.status_code == 200
        body = r.json()
        assert body["multi"] is True
        assert len(body["empresas"]) == 2

    @respx.mock
    async def test_sem_empresas_403(self, client, empresa_usuario):
        respx.post(_MON).mock(return_value=Response(200, json={"ok": True, "empresas": []}))
        r = await client.post("/api/auth/login-empresas", json={"username": "joao", "password": "x"})
        assert r.status_code == 403

    @respx.mock
    async def test_credencial_invalida_401(self, client, empresa_usuario):
        respx.post(_MON).mock(return_value=Response(401, json={"detail": "Credenciais inválidas."}))
        r = await client.post("/api/auth/login-empresas", json={"username": "joao", "password": "errada"})
        assert r.status_code == 401

    @respx.mock
    async def test_selecionar_empresa_ok(self, client, empresa_usuario):
        respx.post(_MON).mock(return_value=Response(200, json={
            "ok": True, "empresas": [{"nome": "Empresa Teste", "cnpj": "00000000000001", "token": "token-teste"}],
        }))
        eid = empresa_usuario["empresa_id"]
        r = await client.post("/api/auth/selecionar-empresa",
                              json={"username": "joao", "password": "x", "empresa_id": eid})
        assert r.status_code == 200

    @respx.mock
    async def test_selecionar_empresa_nao_vinculada_403(self, client, empresa_usuario, db_conn):
        eid2 = await _seed_segunda_empresa(db_conn)
        # Monitor só vincula a empresa de teste (não a "Dois")
        respx.post(_MON).mock(return_value=Response(200, json={
            "ok": True, "empresas": [{"nome": "Empresa Teste", "cnpj": "00000000000001", "token": "token-teste"}],
        }))
        r = await client.post("/api/auth/selecionar-empresa",
                              json={"username": "joao", "password": "x", "empresa_id": eid2})
        assert r.status_code == 403
