"""
app/services/chatbot_service.py — Chatbot IA via WhatsApp.

Fluxo:
  1. Mensagem de texto chega pelo Evolution API webhook
  2. Verifica se remetente é cliente contábil cadastrado
  3. Verifica se chatbot está ativo para a empresa
  4. Busca histórico recente + system prompt configurado
  5. Chama o provider de IA marcado como "chat"
  6. Salva histórico e envia resposta via WhatsApp
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Máximo de mensagens do histórico enviadas à IA (memória de curto prazo)
_HIST_LIMIT = 20

# System prompt padrão (usado quando empresa não configurou um próprio)
_DEFAULT_SYSTEM = (
    "Você é um assistente virtual especializado em documentos fiscais e contabilidade. "
    "Responda de forma clara, objetiva e educada. "
    "Se não souber a resposta, diga que vai verificar com o contador responsável."
)


# ── Seleciona provider de chat ────────────────────────────────────────────────

def _chat_providers() -> list[str]:
    """
    Retorna TODOS os providers habilitados para chatbot, em ordem de preferência.
    Critério: possuem chave API E 'chat' em ai_uso_* (USAR PARA Chatbot ativado).
    Ordem: openai → gemini → anthropic → groq.

    Providers marcados APENAS para 'ocr' são ignorados.
    Se múltiplos estiverem habilitados, o chatbot tenta em sequência (fallback).
    """
    from ..core.config import settings

    ordem = ["openai", "gemini", "anthropic", "groq"]
    uso_map = {
        "openai":    settings.ai_uso_openai,
        "gemini":    settings.ai_uso_gemini,
        "anthropic": settings.ai_uso_anthropic,
        "groq":      settings.ai_uso_groq,
    }
    key_map = {
        "openai":    settings.openai_api_key,
        "gemini":    settings.gemini_api_key,
        "anthropic": settings.anthropic_api_key,
        "groq":      settings.groq_api_key,
    }

    return [
        p for p in ordem
        if "chat" in (uso_map.get(p) or "").split(",") and (key_map.get(p) or "").strip()
    ]


# ── Chamadas por provider ─────────────────────────────────────────────────────

async def _call_openai(messages: list[dict]) -> str:
    from ..core.config import settings
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}",
                     "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": messages, "max_tokens": 500},
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


async def _call_gemini(messages: list[dict]) -> str:
    from ..core.config import settings
    import httpx, asyncio

    # Converte formato OpenAI → Gemini
    contents = []
    for m in messages:
        if m["role"] == "system":
            continue  # system vai virar systemInstruction
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    # System instruction (pega do primeiro message com role=system)
    sys_inst = next((m["content"] for m in messages if m["role"] == "system"), _DEFAULT_SYSTEM)

    model = "gemini-2.0-flash"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={settings.gemini_api_key}"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": sys_inst}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 500},
    }
    # 1 retry rápido em caso de 429 — se ainda falhar, o fallback externo tenta outro provider
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=payload)
    if r.status_code == 429:
        logger.warning("[chatbot] Gemini rate limit (429) — aguardando 8s e tentando 1x mais…")
        await asyncio.sleep(8)
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=payload)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


async def _call_anthropic(messages: list[dict]) -> str:
    from ..core.config import settings
    import httpx

    sys_inst = next((m["content"] for m in messages if m["role"] == "system"), _DEFAULT_SYSTEM)
    msgs = [m for m in messages if m["role"] != "system"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 500,
                "system": sys_inst,
                "messages": msgs,
            },
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()


async def _call_groq(messages: list[dict]) -> str:
    from ..core.config import settings
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": messages,
                "max_tokens": 500,
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


async def _chamar_ia(provider: str, messages: list[dict]) -> str:
    if provider == "openai":
        return await _call_openai(messages)
    elif provider == "gemini":
        return await _call_gemini(messages)
    elif provider == "anthropic":
        return await _call_anthropic(messages)
    elif provider == "groq":
        return await _call_groq(messages)
    raise ValueError(f"Provider desconhecido: {provider}")


# ── Extração assíncrona de memória ───────────────────────────────────────────

async def _extrair_memoria(empresa_id: int, pergunta: str, resposta: str, provider: str) -> None:
    """
    Extrai conhecimento estruturado da conversa e salva na memória IA.
    Roda como task assíncrona sem bloquear o fluxo principal.
    """
    if not pergunta.strip() or not resposta.strip() or len(pergunta) < 8:
        return
    try:
        extraction_prompt = [
            {"role": "system", "content": (
                "Você é um extrator de conhecimento. Analise a pergunta e resposta "
                "e retorne APENAS um JSON válido (sem markdown, sem explicação) com:\n"
                '{"intencao": "nome_curto_da_intencao_sem_espacos_em_snake_case", '
                '"variacoes": ["como o cliente pode perguntar isso de outras formas (3 a 5 variações)"], '
                '"resposta_ideal": "a melhor resposta resumida para esta intenção"}'
            )},
            {"role": "user", "content": f"Pergunta do cliente: {pergunta}\nResposta do assistente: {resposta}"}
        ]
        raw = await _chamar_ia(provider, extraction_prompt)
        if not raw:
            return
        import json as _json
        # Remove markdown code blocks if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        data = _json.loads(raw)
        intencao = str(data.get("intencao", ""))[:100]
        variacoes = data.get("variacoes", [])
        if not isinstance(variacoes, list):
            variacoes = []
        resposta_ideal = str(data.get("resposta_ideal", resposta))[:2000]
        if not intencao:
            return

        from ..core.database import get_db_direct

        async with get_db_direct() as db:
            # Verifica se já existe entrada com mesma intenção para esta empresa
            async with db.execute(
                "SELECT id, usos FROM chatbot_memoria_ia WHERE empresa_id=$1 AND intencao=$2",
                (empresa_id, intencao),
            ) as cur:
                existing = await cur.fetchone()

            if existing:
                # Incrementa usos e atualiza confiança
                await db.execute(
                    """UPDATE chatbot_memoria_ia
                       SET usos=usos+1, updated_at=NOW(),
                           confianca=LEAST(100, confianca+5)
                       WHERE id=$1""",
                    (existing["id"],),
                )
            else:
                import json as _json2
                await db.execute(
                    """INSERT INTO chatbot_memoria_ia
                       (empresa_id, intencao, variacoes, resposta_ideal, confianca, usos, fonte)
                       VALUES($1,$2,$3,$4,$5,$6,'ia')""",
                    (empresa_id, intencao, _json2.dumps(variacoes, ensure_ascii=False),
                     resposta_ideal, 50, 1),
                )
            await db.commit()
        logger.info("[memoria_ia] Entrada '%s' salva/atualizada para empresa %s", intencao, empresa_id)
    except Exception as e:
        logger.warning("[memoria_ia] Falha ao extrair memória: %s", e)


# ── Função principal ──────────────────────────────────────────────────────────

async def responder_mensagem(
    empresa_id: int,
    phone: str,
    texto: str,
    instance: str,
    empresa_nome: str,
) -> None:
    """
    Recebe uma mensagem de texto, gera resposta via IA e envia pelo WhatsApp.
    Salva o histórico de conversa no banco.
    """
    from ..core.database import get_db_direct
    from .evolution_service import evo_manager

    logger.info("[chatbot] responder_mensagem iniciado — empresa=%s phone=%s inst=%s texto=%r",
                empresa_id, phone, instance, texto[:60])
    try:
        # Normaliza phone para formato local (sem 55)
        phone_local = phone.split("@")[0]
        if phone_local.startswith("55") and len(phone_local) >= 12:
            phone_local = phone_local[2:]

        async with get_db_direct() as db:
            # ── Verifica se chatbot está ativo para a empresa ──────────────────
            async with db.execute(
                """SELECT ativo, system_prompt, boas_vindas_ativo, boas_vindas_msg
                   FROM chatbot_config WHERE empresa_id=$1""",
                (empresa_id,),
            ) as cur:
                cfg = await cur.fetchone()

            if not cfg:
                logger.warning("[chatbot] Sem config de chatbot para empresa %s — prosseguindo com defaults", empresa_id)
            elif not cfg["ativo"]:
                logger.info("[chatbot] Chatbot desativado para empresa %s", empresa_id)
                return

            system_prompt = (cfg["system_prompt"] if cfg and cfg["system_prompt"]
                             else _DEFAULT_SYSTEM)
            boas_vindas_ativo = cfg["boas_vindas_ativo"] if cfg else False
            boas_vindas_msg   = cfg["boas_vindas_msg"]   if cfg else ""

            # ── Lookup / upsert do contato na tabela contatos ─────────────────
            # Tenta variantes de phone (10 ou 11 dígitos)
            variantes = [phone_local]
            if len(phone_local) == 10:
                variantes.append(phone_local[:2] + "9" + phone_local[2:])
            elif len(phone_local) == 11 and phone_local[2] == "9":
                variantes.append(phone_local[:2] + phone_local[3:])

            contato = None
            phone_key = phone_local  # chave usada no upsert
            for v in variantes:
                async with db.execute(
                    "SELECT id, nome, chatbot_ativo, boas_vindas_enviada "
                    "FROM contatos WHERE empresa_id=$1 AND phone=$2",
                    (empresa_id, v),
                ) as cur:
                    contato = await cur.fetchone()
                if contato:
                    phone_key = v
                    break

            if not contato:
                # Insere automaticamente com chatbot_ativo=TRUE
                await db.execute(
                    """INSERT INTO contatos(empresa_id, phone, nome, ativo, chatbot_ativo, origem)
                       VALUES($1,$2,$3,TRUE,TRUE,'chatbot')
                       ON CONFLICT(empresa_id, phone) DO UPDATE
                         SET chatbot_ativo=TRUE""",
                    (empresa_id, phone_key, phone_local),
                )
                await db.commit()
                nome_contato          = phone_local
                chatbot_ativo_contato = True
                boas_vindas_enviada   = False
            else:
                nome_contato          = contato["nome"] or phone_local
                chatbot_ativo_contato = bool(contato["chatbot_ativo"])
                boas_vindas_enviada   = bool(contato["boas_vindas_enviada"])

            # Se bot pausado para este contato, silencia
            if not chatbot_ativo_contato:
                logger.info("[chatbot] Bot pausado para %s (empresa %s)", phone_local, empresa_id)
                return

            # Enriquece system prompt com nome da empresa
            system_prompt = (
                f"Você é o assistente virtual de {empresa_nome}. "
                + system_prompt
            )

            # ── Busca FAQ para injetar como exemplos no prompt ─────────────────
            async with db.execute(
                "SELECT pergunta, resposta FROM chatbot_faq WHERE empresa_id=$1 AND ativo=TRUE LIMIT 30",
                (empresa_id,),
            ) as cur:
                faq_rows = await cur.fetchall()

            if faq_rows:
                faq_text = "\n\nExemplos de perguntas e respostas aprovadas:\n"
                for faq in faq_rows:
                    faq_text += f"P: {faq['pergunta']}\nR: {faq['resposta']}\n\n"
                system_prompt += faq_text

            # ── Busca exemplos aprovados pelo aprendizado ──────────────────────
            async with db.execute(
                """SELECT pergunta, resposta FROM chatbot_aprendizado
                   WHERE empresa_id=$1 AND aprovado=TRUE
                   ORDER BY created_at DESC LIMIT 10""",
                (empresa_id,),
            ) as cur:
                exemplos = await cur.fetchall()

            if exemplos:
                ex_text = "\n\nExemplos aprovados de conversas anteriores:\n"
                for ex in exemplos:
                    ex_text += f"P: {ex['pergunta']}\nR: {ex['resposta']}\n\n"
                system_prompt += ex_text

            # ── Busca Memória IA aprovada para injetar no contexto ────────────
            if cfg and cfg.get("memoria_ia_ativa", True):
                async with db.execute(
                    """SELECT intencao, variacoes, resposta_ideal FROM chatbot_memoria_ia
                       WHERE empresa_id=$1 AND aprovado=TRUE
                       ORDER BY usos DESC LIMIT 20""",
                    (empresa_id,),
                ) as cur:
                    mem_rows = await cur.fetchall()

                if mem_rows:
                    import json as _json
                    mem_text = "\n\nBase de conhecimento acumulada (use como referência):\n"
                    for m in mem_rows:
                        try:
                            vars_list = _json.loads(m["variacoes"]) if m["variacoes"] else []
                        except Exception:
                            vars_list = []
                        vars_str = " | ".join(vars_list[:3]) if vars_list else m["intencao"]
                        mem_text += f"Assunto: {m['intencao']}\nVariações: {vars_str}\nResposta: {m['resposta_ideal']}\n\n"
                    system_prompt += mem_text

            # ── Salva mensagem do usuário no histórico ─────────────────────────
            await db.execute(
                "INSERT INTO chat_historico(empresa_id, phone, role, conteudo) VALUES($1,$2,$3,$4)",
                (empresa_id, phone, "user", texto),
            )
            await db.commit()

            # ── Recupera histórico recente ─────────────────────────────────────
            async with db.execute(
                """SELECT role, conteudo FROM chat_historico
                   WHERE empresa_id=$1 AND phone=$2
                   ORDER BY created_at DESC LIMIT $3""",
                (empresa_id, phone, _HIST_LIMIT),
            ) as cur:
                rows = await cur.fetchall()

            # Inverte (mais antigo primeiro) e monta messages para a IA
            historico = list(reversed(rows))
            messages: list[dict] = [{"role": "system", "content": system_prompt}]
            for row in historico:
                messages.append({"role": row["role"], "content": row["conteudo"]})

        # ── Seleciona providers e chama IA com fallback ───────────────────────
        providers = _chat_providers()
        if not providers:
            logger.warning(
                "[chatbot] Nenhum provider habilitado para chatbot. "
                "Ative 'USAR PARA Chatbot' em pelo menos um provider com chave configurada."
            )
            return

        logger.info("[chatbot] Providers disponíveis para chat: %s", providers)
        resposta = None
        provider = None
        erros_chat: list[str] = []

        for p in providers:
            try:
                logger.info("[chatbot] Tentando %s para %s (empresa %s)…", p, phone, empresa_id)
                resposta = await _chamar_ia(p, messages)
                if resposta:
                    provider = p
                    break
            except Exception as e_ia:
                erros_chat.append(f"{p}: {e_ia}")
                logger.warning("[chatbot] %s falhou — %s | tentando próximo…", p, e_ia)

        if not resposta:
            logger.error("[chatbot] Todos os providers falharam: %s", " | ".join(erros_chat))
            return

        # ── Salva resposta no histórico + registro de aprendizado ─────────────
        async with get_db_direct() as db:
            await db.execute(
                "INSERT INTO chat_historico(empresa_id, phone, role, conteudo) VALUES($1,$2,$3,$4)",
                (empresa_id, phone, "assistant", resposta),
            )
            # Salva o par pergunta/resposta para revisão no painel de Aprendizado
            await db.execute(
                """INSERT INTO chatbot_aprendizado(empresa_id, phone, pergunta, resposta)
                   VALUES($1,$2,$3,$4)""",
                (empresa_id, phone, texto[:500], resposta[:1000]),
            )
            await db.commit()

        # ── Extrai conhecimento para Memória IA (async, não bloqueia) ─────────
        asyncio.create_task(
            _extrair_memoria(empresa_id, texto, resposta, provider)
        )

        # ── Envia boas-vindas na primeira mensagem ────────────────────────────
        jid = phone if "@" in phone else f"{phone}@s.whatsapp.net"
        # Extrai session_id do nome completo da instância (formato: e{empresa_id}_{session_id})
        session_id = instance.split("_", 1)[1] if "_" in instance else instance

        if not boas_vindas_enviada and boas_vindas_ativo and boas_vindas_msg.strip():
            msg_bv = boas_vindas_msg.replace("{nome}", nome_contato)
            await evo_manager.send_text(session_id, empresa_id, jid, msg_bv)
            logger.info("[chatbot] Boas-vindas enviada para %s", phone)
            # Marca flag no banco para não reenviar
            async with get_db_direct() as db:
                await db.execute(
                    "UPDATE contatos SET boas_vindas_enviada=TRUE WHERE empresa_id=$1 AND phone=$2",
                    (empresa_id, phone_key),
                )
                await db.commit()

        # ── Envia resposta pelo WhatsApp ──────────────────────────────────────
        await evo_manager.send_text(session_id, empresa_id, jid, resposta)

        logger.info("[chatbot] Resposta enviada para %s via %s (%d chars)",
                    phone, provider, len(resposta))

    except Exception as exc:
        logger.error("[chatbot] Erro ao responder mensagem de %s: %s", phone, exc, exc_info=True)
