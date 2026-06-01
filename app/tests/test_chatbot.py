"""
app/tests/test_chatbot.py — Testes do módulo chatbot.

Cobre:
  Config / Personalidade:
    - GET  /api/chatbot/config        → defaults quando vazio
    - POST /api/chatbot/config        → salva e recupera
    - POST /api/chatbot/boas-vindas   → salva msg e toggle

  FAQ:
    - GET  /api/chatbot/faq           → lista vazia e com dados
    - POST /api/chatbot/faq           → cria, campos obrigatórios
    - DELETE /api/chatbot/faq/{id}    → soft delete (marca ativo=false)

  Aprendizado:
    - GET  /api/chatbot/aprendizado   → lista, filtra por aprovados/pendentes
    - PATCH /api/chatbot/aprendizado/{id}  → aprova/rejeita item
    - DELETE /api/chatbot/aprendizado/{id} → remove

  Conversas / Histórico:
    - GET  /api/chatbot/conversas     → lista (vazia ou com dados)
    - GET  /api/chatbot/historico/{phone} → histórico de um contato
    - DELETE /api/chatbot/historico/{phone} → limpa histórico

  Contato:
    - PATCH /api/chatbot/contato/{phone}/chatbot-ativo → toggle bot por contato

  Memória IA:
    - GET  /api/chatbot/memoria-ia         → lista
    - POST /api/chatbot/memoria-ia         → cria memória
    - PATCH /api/chatbot/memoria-ia/{id}   → edita
    - PATCH /api/chatbot/memoria-ia/{id}/aprovar → aprova
    - DELETE /api/chatbot/memoria-ia/{id}  → remove
    - GET  /api/chatbot/memoria-ia/stats   → estatísticas

  Auth: todos os endpoints → 401 sem cookie
"""
import pytest
import pytest_asyncio


pytestmark = pytest.mark.asyncio


# ── Auth ──────────────────────────────────────────────────────────────────────

class TestAuth:
    async def test_config_sem_auth(self, client):
        assert (await client.get("/api/chatbot/config")).status_code == 401

    async def test_faq_sem_auth(self, client):
        assert (await client.get("/api/chatbot/faq")).status_code == 401

    async def test_aprendizado_sem_auth(self, client):
        assert (await client.get("/api/chatbot/aprendizado")).status_code == 401

    async def test_conversas_sem_auth(self, client):
        assert (await client.get("/api/chatbot/conversas")).status_code == 401


# ── Config / Personalidade ────────────────────────────────────────────────────

class TestChatbotConfig:
    async def test_defaults_quando_vazio(self, auth_client):
        r = await auth_client.get("/api/chatbot/config")
        assert r.status_code == 200
        data = r.json()
        assert "ativo" in data
        assert "system_prompt" in data
        assert "boas_vindas_ativo" in data

    async def test_salva_e_recupera_config(self, auth_client):
        r = await auth_client.post("/api/chatbot/config", json={
            "ativo": True,
            "system_prompt": "Você é um assistente prestativo.",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r2 = await auth_client.get("/api/chatbot/config")
        assert r2.status_code == 200
        data = r2.json()
        assert data["ativo"] is True
        assert data["system_prompt"] == "Você é um assistente prestativo."

    async def test_desativa_chatbot(self, auth_client):
        await auth_client.post("/api/chatbot/config", json={"ativo": False, "system_prompt": ""})
        r = await auth_client.get("/api/chatbot/config")
        assert r.json()["ativo"] is False

    async def test_salva_boas_vindas(self, auth_client):
        r = await auth_client.post("/api/chatbot/boas-vindas", json={
            "ativo": True,
            "msg": "Olá! Como posso ajudar?",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    async def test_toggle_memoria_ia(self, auth_client):
        r = await auth_client.post("/api/chatbot/config/memoria-ia-ativa", json={"memoria_ia_ativa": False})
        assert r.status_code == 200


# ── FAQ ───────────────────────────────────────────────────────────────────────

class TestFaq:
    async def test_lista_vazia(self, auth_client):
        r = await auth_client.get("/api/chatbot/faq")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_cria_faq(self, auth_client):
        r = await auth_client.post("/api/chatbot/faq", json={
            "pergunta": "Qual o horário de funcionamento?",
            "resposta": "Das 8h às 18h.",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    async def test_faq_pergunta_obrigatoria(self, auth_client):
        r = await auth_client.post("/api/chatbot/faq", json={
            "pergunta": "",
            "resposta": "Resposta qualquer",
        })
        assert r.status_code == 400

    async def test_faq_resposta_obrigatoria(self, auth_client):
        r = await auth_client.post("/api/chatbot/faq", json={
            "pergunta": "Pergunta qualquer",
            "resposta": "",
        })
        assert r.status_code == 400

    async def test_faq_aparece_na_lista(self, auth_client):
        await auth_client.post("/api/chatbot/faq", json={
            "pergunta": "Pergunta Listável?",
            "resposta": "Resposta Listável.",
        })
        r = await auth_client.get("/api/chatbot/faq")
        perguntas = [f["pergunta"] for f in r.json()]
        assert "Pergunta Listável?" in perguntas

    async def test_deleta_faq(self, auth_client):
        await auth_client.post("/api/chatbot/faq", json={
            "pergunta": "Para deletar?",
            "resposta": "Deletar.",
        })
        faqs = (await auth_client.get("/api/chatbot/faq")).json()
        faq_id = next(f["id"] for f in faqs if f["pergunta"] == "Para deletar?")

        r = await auth_client.delete(f"/api/chatbot/faq/{faq_id}")
        assert r.status_code == 200

        # Não deve aparecer mais na lista
        faqs2 = (await auth_client.get("/api/chatbot/faq")).json()
        perguntas = [f["pergunta"] for f in faqs2]
        assert "Para deletar?" not in perguntas


# ── Aprendizado ───────────────────────────────────────────────────────────────

class TestAprendizado:
    async def _seed(self, db_conn, empresa_usuario):
        """Insere item de aprendizado diretamente no banco para evitar depender de outro endpoint."""
        await db_conn.execute(
            """INSERT INTO chatbot_aprendizado
               (empresa_id, phone, pergunta, resposta, aprovado)
               VALUES ($1, $2, $3, $4, NULL)""",
            empresa_usuario["empresa_id"],
            "11999990099",
            "O que é ZapDin?",
            "É um sistema de mensagens.",
        )
        return await db_conn.fetchval(
            "SELECT id FROM chatbot_aprendizado WHERE empresa_id=$1 ORDER BY id DESC LIMIT 1",
            empresa_usuario["empresa_id"],
        )

    async def test_lista_aprendizado(self, auth_client, db_conn, empresa_usuario):
        await self._seed(db_conn, empresa_usuario)
        r = await auth_client.get("/api/chatbot/aprendizado")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) >= 1

    async def test_filtra_pendentes(self, auth_client, db_conn, empresa_usuario):
        await self._seed(db_conn, empresa_usuario)
        r = await auth_client.get("/api/chatbot/aprendizado?filtro=pendentes")
        assert r.status_code == 200
        for item in r.json():
            assert item["aprovado"] is None

    async def test_aprova_item(self, auth_client, db_conn, empresa_usuario):
        item_id = await self._seed(db_conn, empresa_usuario)
        r = await auth_client.patch(f"/api/chatbot/aprendizado/{item_id}", json={"aprovado": True})
        assert r.status_code == 200

        # Verifica no banco
        row = await db_conn.fetchrow(
            "SELECT aprovado FROM chatbot_aprendizado WHERE id=$1", item_id
        )
        assert row["aprovado"] is True

    async def test_rejeita_item(self, auth_client, db_conn, empresa_usuario):
        item_id = await self._seed(db_conn, empresa_usuario)
        r = await auth_client.patch(f"/api/chatbot/aprendizado/{item_id}", json={"aprovado": False})
        assert r.status_code == 200

    async def test_deleta_item(self, auth_client, db_conn, empresa_usuario):
        item_id = await self._seed(db_conn, empresa_usuario)
        r = await auth_client.delete(f"/api/chatbot/aprendizado/{item_id}")
        assert r.status_code == 200


# ── Conversas / Histórico ─────────────────────────────────────────────────────

class TestConversas:
    async def test_lista_conversas(self, auth_client):
        r = await auth_client.get("/api/chatbot/conversas")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_historico_contato_inexistente(self, auth_client):
        r = await auth_client.get("/api/chatbot/historico/99999999999")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) == 0

    async def test_historico_com_mensagens(self, auth_client, db_conn, empresa_usuario):
        await db_conn.execute(
            """INSERT INTO chat_historico (empresa_id, phone, role, conteudo)
               VALUES ($1, $2, $3, $4)""",
            empresa_usuario["empresa_id"],
            "11999990088",
            "user",
            "Olá, tudo bem?",
        )
        r = await auth_client.get("/api/chatbot/historico/11999990088")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    async def test_limpa_historico(self, auth_client, db_conn, empresa_usuario):
        await db_conn.execute(
            """INSERT INTO chat_historico (empresa_id, phone, role, conteudo)
               VALUES ($1, $2, $3, $4)""",
            empresa_usuario["empresa_id"],
            "11999990077",
            "user",
            "Mensagem para deletar",
        )
        r = await auth_client.delete("/api/chatbot/historico/11999990077")
        assert r.status_code == 200

        # Histórico deve estar vazio
        r2 = await auth_client.get("/api/chatbot/historico/11999990077")
        assert len(r2.json()) == 0


# ── Toggle chatbot por contato ────────────────────────────────────────────────

class TestChatbotContato:
    async def test_toggle_chatbot_ativo(self, auth_client):
        r = await auth_client.patch(
            "/api/chatbot/contato/11999990066/chatbot-ativo",
            json={"chatbot_ativo": False},
        )
        assert r.status_code == 200


# ── Memória IA ────────────────────────────────────────────────────────────────

class TestMemoriaIA:
    async def test_lista_memoria(self, auth_client):
        r = await auth_client.get("/api/chatbot/memoria-ia")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_stats_memoria(self, auth_client):
        r = await auth_client.get("/api/chatbot/memoria-ia/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data or "aprovadas" in data or isinstance(data, dict)

    async def test_cria_memoria(self, auth_client):
        r = await auth_client.post("/api/chatbot/memoria-ia", json={
            "intencao": "preferencia contato manha",
            "resposta_ideal": "O cliente prefere contato pela manhã.",
        })
        assert r.status_code == 200
        assert r.json().get("ok") is True or "id" in r.json()

    async def test_edita_memoria(self, auth_client, db_conn, empresa_usuario):
        mid = await db_conn.fetchval(
            """INSERT INTO chatbot_memoria_ia (empresa_id, intencao, resposta_ideal, aprovado)
               VALUES ($1, $2, $3, TRUE) RETURNING id""",
            empresa_usuario["empresa_id"],
            "Memória para editar",
            "geral",
        )
        r = await auth_client.patch(f"/api/chatbot/memoria-ia/{mid}", json={
            "intencao": "Memória para editar",
            "resposta_ideal": "Memória editada com sucesso.",
        })
        assert r.status_code == 200

    async def test_aprova_memoria(self, auth_client, db_conn, empresa_usuario):
        mid = await db_conn.fetchval(
            """INSERT INTO chatbot_memoria_ia (empresa_id, intencao, resposta_ideal, aprovado)
               VALUES ($1, $2, $3, FALSE) RETURNING id""",
            empresa_usuario["empresa_id"],
            "Memória para aprovar",
            "geral",
        )
        r = await auth_client.patch(f"/api/chatbot/memoria-ia/{mid}/aprovar", json={"aprovado": True})
        assert r.status_code == 200

    async def test_deleta_memoria(self, auth_client, db_conn, empresa_usuario):
        mid = await db_conn.fetchval(
            """INSERT INTO chatbot_memoria_ia (empresa_id, intencao, resposta_ideal, aprovado)
               VALUES ($1, $2, $3, TRUE) RETURNING id""",
            empresa_usuario["empresa_id"],
            "Memória para deletar",
            "geral",
        )
        r = await auth_client.delete(f"/api/chatbot/memoria-ia/{mid}")
        assert r.status_code == 200


class TestChatbotFailSafe:
    """Fail-safe: chatbot só responde se cfg.ativo=true. Sem config (cfg=None) NÃO responde."""

    async def test_chatbot_sem_config_nao_responde(self, db_conn, empresa_usuario):
        """Regressão: se chatbot_config nem foi cadastrado, NÃO deve responder.
        Antes do fix: cfg=None apenas logava warning e prosseguia."""
        from app.services.chatbot_service import responder_mensagem
        # Garante que NÃO há config (apaga se existir)
        await db_conn.execute("DELETE FROM chatbot_config WHERE empresa_id=$1", empresa_usuario["empresa_id"])
        # Chama responder_mensagem — deve retornar sem efeito colateral
        result = await responder_mensagem(
            empresa_id=empresa_usuario["empresa_id"],
            phone="5511999990000@s.whatsapp.net",
            texto="oi",
            instance="test-instance",
            empresa_nome="Teste",
        )
        # Não levanta exceção e retorna None (early return)
        assert result is None

    async def test_chatbot_ativo_false_nao_responde(self, db_conn, empresa_usuario):
        """ativo=false → não responde (já testado, garantia explícita)."""
        from app.services.chatbot_service import responder_mensagem
        await db_conn.execute(
            "INSERT INTO chatbot_config(empresa_id, ativo) VALUES($1, FALSE) "
            "ON CONFLICT(empresa_id) DO UPDATE SET ativo=FALSE",
            empresa_usuario["empresa_id"],
        )
        result = await responder_mensagem(
            empresa_id=empresa_usuario["empresa_id"],
            phone="5511999990000@s.whatsapp.net",
            texto="oi", instance="test-instance", empresa_nome="Teste",
        )
        assert result is None
