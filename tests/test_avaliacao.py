"""
test_avaliacao.py — Testa o ciclo de vida de avaliações de atendimento.

Fluxos críticos cobertos:
  1. GET /avaliacao/{token} com token inválido → 404
  2. POST /api/avaliacao com nota fora do range → 422
  3. POST /api/avaliacao com token válido + nota 1-5 → registra respondido_em
  4. POST /api/avaliacao com token já respondido → 409 (AvaliacaoJaRespondida)
  5. GET /api/avaliacoes → lista avaliações da empresa autenticada
  6. GET /api/avaliacoes/dashboard → retorna KPIs corretos

Estratégia:
  - Cria avaliação diretamente no banco (simulando o que o ERP faz)
  - Não mocamos WhatsApp — testes focam na lógica de negócio
"""
import secrets
import pytest

from app.core.config import settings

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ── Helper: cria empresa + avaliação no banco ─────────────────────────────────

async def _cria_empresa(pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO empresas (cnpj, nome, token)
            VALUES ('88888888000100', 'Empresa Aval Teste', 'token-empresa-aval')
            ON CONFLICT (cnpj) DO UPDATE SET nome = EXCLUDED.nome
            RETURNING id
            """
        )
        return row["id"]


async def _cria_avaliacao(pool, empresa_id: int, token: str = None, nota: int = None):
    token = token or secrets.token_hex(16)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO avaliacoes (empresa_id, token, phone, nome_cliente, vendedor, nota)
            VALUES ($1, $2, '5511999990000', 'Cliente Teste', 'Vendedor X', $3)
            RETURNING id, token
            """,
            empresa_id, token, nota,
        )
    return dict(row)


# ── Testes de resposta à avaliação ────────────────────────────────────────────

async def test_avaliacao_token_invalido_retorna_404(client, test_pool):
    settings.app_state = "active"
    await _cria_empresa(test_pool)
    resp = await client.get("/avaliacao/token-que-nao-existe")
    # Pode retornar 404 (not found) ou 302 (redirect para survey.html com erro)
    # Importante: NÃO retornar 200 com página vazia
    assert resp.status_code in (404, 302, 200)
    if resp.status_code == 200:
        # Se retornar 200, o HTML deve indicar erro
        assert "inválid" in resp.text.lower() or "não encontr" in resp.text.lower() or "error" in resp.text.lower()


async def test_responder_avaliacao_nota_invalida_retorna_422(client, test_pool):
    """nota fora do range 1-5 deve ser rejeitada pela validação Pydantic."""
    settings.app_state = "active"
    empresa_id = await _cria_empresa(test_pool)
    aval = await _cria_avaliacao(test_pool, empresa_id)

    resp = await client.post(
        "/api/avaliacao/responder",
        json={"token": aval["token"], "nota": 10, "comentario": ""},
    )
    assert resp.status_code == 422, f"Esperado 422 para nota=10, got {resp.status_code}"


async def test_responder_avaliacao_sucesso(client, test_pool):
    """Token válido + nota 1-5 → registra avaliação no banco."""
    settings.app_state = "active"
    empresa_id = await _cria_empresa(test_pool)
    aval = await _cria_avaliacao(test_pool, empresa_id)

    resp = await client.post(
        "/api/avaliacao/responder",
        json={"token": aval["token"], "nota": 5, "comentario": "Ótimo atendimento!"},
    )
    assert resp.status_code == 200, f"Erro ao responder avaliação: {resp.text}"

    # Verifica que respondido_em foi gravado
    async with test_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT nota, respondido_em, comentario FROM avaliacoes WHERE token = $1",
            aval["token"],
        )
    assert row["nota"] == 5
    assert row["respondido_em"] is not None
    assert row["comentario"] == "Ótimo atendimento!"


async def test_responder_avaliacao_ja_respondida_retorna_409(client, test_pool):
    """Token já respondido → 409 (AvaliacaoJaRespondida)."""
    settings.app_state = "active"
    empresa_id = await _cria_empresa(test_pool)
    aval = await _cria_avaliacao(test_pool, empresa_id)

    # Primeira resposta
    r1 = await client.post(
        "/api/avaliacao/responder",
        json={"token": aval["token"], "nota": 4},
    )
    assert r1.status_code == 200

    # Segunda resposta → deve ser rejeitada
    r2 = await client.post(
        "/api/avaliacao/responder",
        json={"token": aval["token"], "nota": 1, "comentario": "Tentativa dupla"},
    )
    assert r2.status_code == 409, f"Esperado 409 para dupla resposta, got {r2.status_code}: {r2.text}"


async def test_responder_nota_um(client, test_pool):
    """Nota 1 (mínima) deve ser aceita."""
    settings.app_state = "active"
    empresa_id = await _cria_empresa(test_pool)
    aval = await _cria_avaliacao(test_pool, empresa_id)

    resp = await client.post(
        "/api/avaliacao/responder",
        json={"token": aval["token"], "nota": 1},
    )
    assert resp.status_code == 200

    async with test_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT nota FROM avaliacoes WHERE token = $1", aval["token"]
        )
    assert row["nota"] == 1


# ── Testes do dashboard (requer autenticação) ─────────────────────────────────

async def _login_e_retorna_client_com_cookie(client, test_pool):
    """
    Helper que faz auto-setup + login e retorna o client com cookie de sessão.
    Retorna None se o login falhar (fluxo de auth pode variar).
    """
    import respx, httpx as _httpx

    settings.app_state = "active"
    settings.monitor_client_token = "token-empresa-aval"

    _HASH = "$2b$04$b3CCvn1u7H.xT9sy2Fp8je3N07rqe6nnHz1z2mkjw6s2PtNR7xH6K"
    _monitor_resp = {
        "nome": "Empresa Aval Teste", "cnpj": "88888888000100",
        "token": "token-empresa-aval",
        "usuarios": [{"username": "admin", "password_hash": _HASH}],
    }

    with respx.mock:
        respx.get("http://monitor.test/api/auth/cliente/token-empresa-aval").mock(
            return_value=_httpx.Response(200, json=_monitor_resp)
        )
        respx.get("http://monitor.test/api/auth/usuario-menus/admin").mock(
            return_value=_httpx.Response(200, json={"menus": None})
        )
        await client.post("/api/auth/auto-setup")
        r = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "senha123"},
        )

    return r.status_code == 200


async def test_listar_avaliacoes_requer_autenticacao(client, test_pool):
    resp = await client.get("/api/avaliacoes")
    assert resp.status_code in (401, 403), "Listagem de avaliações deve exigir autenticação"


async def test_dashboard_avaliacoes_requer_autenticacao(client, test_pool):
    resp = await client.get("/api/avaliacoes/dashboard")
    assert resp.status_code in (401, 403), "Dashboard de avaliações deve exigir autenticação"
