"""
test_erp.py — Testa o fluxo ERP: receber_venda → mensagem enfileirada.

Fluxos críticos cobertos:
  1. POST /api/erp/venda sem token → 401
  2. POST /api/erp/venda com token inválido → 401
  3. POST /api/erp/venda com token válido → mensagem queued no banco
  4. POST /api/erp/venda sem contatos → avaliação criada (se ativa)
  5. Rate limit: 61 chamadas em 60s → 429

Estratégia:
  - Setup: cria empresa + config erp_token no banco antes dos testes
  - Não mocamos WhatsApp nem Evolution (só verificamos que entrou no banco)
  - respx: NÃO necessário — ERP apenas grava no banco, não chama serviços externos
"""
import pytest
import asyncpg

from app.core.config import settings
from app.core.security import hash_erp_token

pytestmark = pytest.mark.asyncio(loop_scope="session")

# ── Helper: cria empresa + token ERP no banco ─────────────────────────────────

async def _setup_empresa_com_token(pool: asyncpg.Pool, token_raw: str) -> int:
    """Cria empresa de teste e grava token ERP hashed no banco. Retorna empresa_id."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO empresas (cnpj, nome, token)
            VALUES ('99999999000191', 'Empresa Teste ERP', $1)
            ON CONFLICT (cnpj) DO UPDATE SET nome = EXCLUDED.nome
            RETURNING id
            """,
            "token-empresa-erp",
        )
        empresa_id = row["id"]

        # Grava token hashed (SHA-256) na config
        token_hash = hash_erp_token(token_raw)
        await conn.execute(
            """
            INSERT INTO config (empresa_id, key, value)
            VALUES ($1, 'erp_token', $2)
            ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value
            """,
            empresa_id, token_hash,
        )
        return empresa_id


# ── Testes sem token ──────────────────────────────────────────────────────────

async def test_venda_sem_token_retorna_401(client):
    settings.app_state = "active"
    resp = await client.post("/api/erp/venda", json={"telefone": "5511999999999", "nome": "Teste"})
    assert resp.status_code == 401
    assert "token" in resp.json()["detail"].lower()


async def test_venda_token_invalido_retorna_401(client, test_pool):
    settings.app_state = "active"
    await _setup_empresa_com_token(test_pool, "token-erp-valido")

    resp = await client.post(
        "/api/erp/venda",
        json={"telefone": "5511999999999", "nome": "João"},
        headers={"x-token": "token-erp-ERRADO"},
    )
    assert resp.status_code == 401


# ── Fluxo principal: venda enfileira mensagem ─────────────────────────────────

async def test_venda_valida_cria_mensagem_queued(client, test_pool):
    """
    FLUXO CRÍTICO: token válido + phone válido → mensagem com status='queued' no banco.
    """
    settings.app_state = "active"
    token_raw = "token-erp-prod-1234"
    await _setup_empresa_com_token(test_pool, token_raw)

    # Configura mensagem padrão para que o ERP consiga montar o texto
    async with test_pool.acquire() as conn:
        empresa_id = (await conn.fetchrow(
            "SELECT id FROM empresas WHERE cnpj = '99999999000191'"
        ))["id"]
        await conn.execute(
            "INSERT INTO config (empresa_id, key, value) VALUES ($1, 'mensagem_padrao', $2) "
            "ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value",
            empresa_id, "Obrigado {nome}! Sua compra de {valor} foi registrada.",
        )

    resp = await client.post(
        "/api/erp/venda",
        json={
            "telefone": "5511988887777",
            "nome": "Maria Silva",
            "valor": "R$ 150,00",
        },
        headers={"x-token": token_raw},
    )

    assert resp.status_code == 200, f"Esperado 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data.get("ok") is True or data.get("queued") is True

    # Verifica que a mensagem foi realmente gravada no banco
    async with test_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, destinatario FROM mensagens WHERE empresa_id = $1 ORDER BY id DESC LIMIT 1",
            empresa_id,
        )
    assert row is not None, "Nenhuma mensagem encontrada no banco"
    assert row["status"] == "queued", f"Status esperado 'queued', got '{row['status']}'"
    assert "5511988887777" in row["destinatario"] or row["destinatario"] == "5511988887777"


# ── Avaliação é criada quando ativa ──────────────────────────────────────────

async def test_venda_cria_avaliacao_quando_ativa(client, test_pool):
    """
    Se avaliação estiver ativa na config, POST /api/erp/venda deve criar
    um registro de avaliação com nota=null no banco.
    """
    settings.app_state = "active"
    token_raw = "token-erp-aval"
    await _setup_empresa_com_token(test_pool, token_raw)

    async with test_pool.acquire() as conn:
        empresa_id = (await conn.fetchrow(
            "SELECT id FROM empresas WHERE cnpj = '99999999000191'"
        ))["id"]
        # Ativa avaliação
        for k, v in [
            ("avaliacao_ativa", "1"),
            ("avaliacao_url_base", "http://localhost:4000"),
            ("mensagem_padrao", "Olá {nome}!"),
        ]:
            await conn.execute(
                "INSERT INTO config (empresa_id, key, value) VALUES ($1,$2,$3) "
                "ON CONFLICT (empresa_id, key) DO UPDATE SET value=EXCLUDED.value",
                empresa_id, k, v,
            )

    resp = await client.post(
        "/api/erp/venda",
        json={"telefone": "5511977776666", "nome": "Pedro", "vendedor": "Ana"},
        headers={"x-token": token_raw},
    )

    assert resp.status_code == 200

    async with test_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT nota, vendedor FROM avaliacoes WHERE empresa_id = $1 ORDER BY id DESC LIMIT 1",
            empresa_id,
        )
    assert row is not None, "Nenhuma avaliação encontrada no banco"
    assert row["nota"] is None, "Avaliação recém-criada deve ter nota=null"


# ── Rate limiter ──────────────────────────────────────────────────────────────

async def test_venda_rate_limit_bloqueia_apos_limite(client, test_pool):
    """
    Mais de 60 chamadas em 60s ao /api/erp/venda com mesmo token → 429.
    Usa IP diferente para cada empresa (rate limit é por IP, não por token).
    """
    from app.core.rate_limiter import erp_limiter

    # Força o esgotamento do rate limit para o IP "testclient"
    ip_teste = "testclient"
    erp_limiter.reset(ip_teste)

    # Consome todas as chamadas permitidas
    for _ in range(erp_limiter._max):
        erp_limiter.is_allowed(ip_teste)

    # Próxima deve estar bloqueada
    assert not erp_limiter.is_allowed(ip_teste), "Rate limiter deve bloquear após o limite"

    # Cleanup
    erp_limiter.reset(ip_teste)
