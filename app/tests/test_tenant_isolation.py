"""
test_tenant_isolation.py — Prova de isolamento multi-tenant.

Estratégia:
  1. Cria EMPRESA B ("intrusa") com dados seedados em TODAS as tabelas
     principais, marcados com o token XTENANTB.
  2. Loga como EMPRESA A (auth_client, fixture padrão).
  3. Verifica que NENHUMA listagem da A retorna o marker da B.
  4. Verifica que acesso direto por ID a recursos da B retorna 404/403.

Se um endpoint novo esquecer o filtro WHERE empresa_id, este teste quebra.
"""
import json
import pytest
import pytest_asyncio

# Marker único — se aparecer em qualquer payload da empresa A, é leak.
MARKER = "XTENANTB"


@pytest_asyncio.fixture
async def empresa_b(db_conn, empresa_usuario):
    """Cria a empresa B com dados em todas as tabelas críticas. Idempotente."""
    eb = await db_conn.fetchval(
        """INSERT INTO empresas (cnpj, nome, token, ativo)
           VALUES ('99999999999999', $1, 'token-intruso-b', TRUE)
           ON CONFLICT (cnpj) DO UPDATE SET nome = EXCLUDED.nome
           RETURNING id""",
        f"EMPRESA {MARKER}",
    )

    # Limpa seeds anteriores da B (re-execuções — function-scoped roda por teste)
    await db_conn.execute("DELETE FROM grupo_contatos WHERE grupo_id IN (SELECT id FROM grupos_contatos WHERE empresa_id = $1)", eb)
    for tbl in ("mensagens", "arquivos", "contatos", "campanhas", "avaliacoes", "grupos_contatos"):
        await db_conn.execute(f"DELETE FROM {tbl} WHERE empresa_id = $1", eb)
    await db_conn.execute("DELETE FROM sessoes_wa WHERE empresa_id = $1", eb)
    await db_conn.execute("DELETE FROM config WHERE empresa_id = $1", eb)
    try:
        await db_conn.execute("DELETE FROM system_logs WHERE empresa_id = $1", eb)
    except Exception:
        pass

    ids = {"empresa_id": eb}

    ids["mensagem_id"] = await db_conn.fetchval(
        """INSERT INTO mensagens (empresa_id, destinatario, mensagem, status)
           VALUES ($1, '5544999990000', $2, 'sent') RETURNING id""",
        eb, f"msg {MARKER}",
    )
    ids["arquivo_id"] = await db_conn.fetchval(
        """INSERT INTO arquivos (empresa_id, nome_original, nome_arquivo, destinatario, status)
           VALUES ($1, $2, $3, '5544999990000', 'sent') RETURNING id""",
        eb, f"doc-{MARKER}.pdf", f"x-{MARKER}.pdf",
    )
    ids["contato_id"] = await db_conn.fetchval(
        """INSERT INTO contatos (empresa_id, phone, nome, ativo)
           VALUES ($1, '44988887777', $2, TRUE) RETURNING id""",
        eb, f"Contato {MARKER}",
    )
    ids["campanha_id"] = await db_conn.fetchval(
        """INSERT INTO campanhas (empresa_id, nome, tipo, mensagem, status)
           VALUES ($1, $2, 'text', $3, 'draft') RETURNING id""",
        eb, f"Campanha {MARKER}", f"corpo {MARKER}",
    )
    await db_conn.execute(
        """INSERT INTO sessoes_wa (empresa_id, id, nome, status)
           VALUES ($1, $2, $3, 'disconnected')
           ON CONFLICT DO NOTHING""",
        eb, f"sess{MARKER.lower()}", f"Sessao {MARKER}",
    )
    ids["sessao_id"] = f"sess{MARKER.lower()}"
    ids["aval_token"] = f"tok-{MARKER}"
    ids["avaliacao_id"] = await db_conn.fetchval(
        """INSERT INTO avaliacoes (empresa_id, token, phone, nome_cliente, vendedor)
           VALUES ($1, $2, '5544977776666', $3, $4) RETURNING id""",
        eb, ids["aval_token"], f"Cliente {MARKER}", f"Vendedor {MARKER}",
    )
    await db_conn.execute(
        """INSERT INTO config (empresa_id, key, value) VALUES ($1, 'mensagem_padrao', $2)
           ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value""",
        eb, f"template secreto {MARKER}",
    )
    # Grupo da B (pra testar vínculo de contato cross-tenant no pivô)
    ids["grupo_id"] = await db_conn.fetchval(
        """INSERT INTO grupos_contatos (empresa_id, nome) VALUES ($1, $2) RETURNING id""",
        eb, f"Grupo {MARKER}",
    )
    # system_log antigo da B (pra testar DELETE cross-tenant)
    try:
        await db_conn.execute(
            """INSERT INTO system_logs (empresa_id, nivel, modulo, acao, mensagem, created_at)
               VALUES ($1, 'info', 'teste', 'seed', $2, NOW() - INTERVAL '400 days')""",
            eb, f"log {MARKER}",
        )
    except Exception:
        pass
    return ids


def _assert_no_marker(payload, endpoint: str):
    body = json.dumps(payload, ensure_ascii=False, default=str)
    assert MARKER not in body, f"LEAK multi-tenant em {endpoint}: marker da empresa B presente"


# ── Listagens não podem conter dados da B ─────────────────────────────────────

LIST_ENDPOINTS = [
    "/api/arquivos",
    "/api/campanha",
    "/api/campanha/contatos",
    "/api/campanha/grupos",
    "/api/campanha/dashboard",
    "/api/sessoes",
    "/api/avaliacoes",
    "/api/avaliacoes/dashboard",
    "/api/config",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", LIST_ENDPOINTS)
async def test_listagem_nao_vaza_empresa_b(auth_client, empresa_b, endpoint):
    r = await auth_client.get(endpoint)
    assert r.status_code == 200, f"{endpoint} retornou {r.status_code}"
    _assert_no_marker(r.json(), endpoint)


# ── Acesso direto por ID a recursos da B → 404 ────────────────────────────────

@pytest.mark.asyncio
async def test_get_arquivo_da_b_404(auth_client, empresa_b):
    r = await auth_client.get(f"/api/arquivos/{empresa_b['arquivo_id']}")
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_download_arquivo_da_b_404(auth_client, empresa_b):
    r = await auth_client.get(f"/api/arquivos/{empresa_b['arquivo_id']}/download")
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_delete_campanha_da_b_404(auth_client, empresa_b):
    r = await auth_client.delete(f"/api/campanha/{empresa_b['campanha_id']}")
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_progresso_campanha_da_b_404(auth_client, empresa_b):
    r = await auth_client.get(f"/api/campanha/{empresa_b['campanha_id']}/progresso")
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_pausar_campanha_da_b_404(auth_client, empresa_b):
    r = await auth_client.post(f"/api/campanha/{empresa_b['campanha_id']}/pausar")
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_iniciar_campanha_da_b_404(auth_client, empresa_b):
    r = await auth_client.post(f"/api/campanha/{empresa_b['campanha_id']}/iniciar", json={})
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_upload_arquivo_campanha_da_b_404(auth_client, empresa_b):
    r = await auth_client.post(
        f"/api/campanha/{empresa_b['campanha_id']}/arquivo",
        files={"file": ("x.jpg", b"bytes", "image/jpeg")},
    )
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_delete_contato_da_b_nao_remove(auth_client, empresa_b, db_conn):
    r = await auth_client.delete(f"/api/campanha/contatos/{empresa_b['contato_id']}")
    # Aceita 404 OU 200-noop — mas o contato da B deve continuar existindo
    ainda_existe = await db_conn.fetchval(
        "SELECT COUNT(*) FROM contatos WHERE id = $1", empresa_b["contato_id"]
    )
    assert ainda_existe == 1, "DELETE cross-tenant removeu contato de outra empresa!"


@pytest.mark.asyncio
async def test_delete_sessao_da_b_nao_remove(auth_client, empresa_b, db_conn):
    await auth_client.delete(f"/api/sessoes/{empresa_b['sessao_id']}")
    ainda_existe = await db_conn.fetchval(
        "SELECT COUNT(*) FROM sessoes_wa WHERE id = $1 AND empresa_id = $2",
        empresa_b["sessao_id"], empresa_b["empresa_id"],
    )
    assert ainda_existe == 1, "DELETE cross-tenant removeu sessão WA de outra empresa!"


# ── Config (client_name vem da empresa do cookie) ─────────────────────────────

@pytest.mark.asyncio
async def test_add_contato_da_b_ao_grupo_proprio_bloqueado(auth_client, empresa_b, db_conn, empresa_usuario):
    """Empresa A cria grupo próprio e tenta vincular contato da B — pivô não deve gravar."""
    grupo_a = await db_conn.fetchval(
        "INSERT INTO grupos_contatos (empresa_id, nome) VALUES ($1, 'GrupoA') RETURNING id",
        empresa_usuario["empresa_id"],
    )
    await auth_client.post(f"/api/campanha/grupos/{grupo_a}/contatos",
                           json={"contato_ids": [empresa_b["contato_id"]]})
    # O contato da B NÃO pode ter sido vinculado ao grupo da A
    cnt = await db_conn.fetchval(
        "SELECT COUNT(*) FROM grupo_contatos WHERE grupo_id=$1 AND contato_id=$2",
        grupo_a, empresa_b["contato_id"],
    )
    assert cnt == 0, "contato de outra empresa foi vinculado ao grupo (leak no pivô)!"


@pytest.mark.asyncio
async def test_delete_logs_nao_apaga_da_b(auth_client, empresa_b, db_conn):
    """DELETE /api/syslog não pode apagar system_logs de outra empresa."""
    await auth_client.request("DELETE", "/api/syslog", params={"dias": 1})
    sobrou = await db_conn.fetchval(
        "SELECT COUNT(*) FROM system_logs WHERE empresa_id=$1", empresa_b["empresa_id"]
    )
    assert sobrou >= 1, "DELETE de logs apagou registros de outra empresa (leak cross-tenant)!"


@pytest.mark.asyncio
async def test_config_client_name_e_da_empresa_logada(auth_client, empresa_b, empresa_usuario):
    r = await auth_client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert MARKER not in (data.get("client_name") or ""), \
        "client_name retornou nome da empresa B!"
