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

def _chat_provider() -> Optional[str]:
    """
    Retorna o primeiro provider configurado com uso='chat'.
    Ordem de preferência: openai → gemini → anthropic → groq.
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

    for p in ordem:
        uso = uso_map.get(p) or ""
        key = key_map.get(p) or ""
        if "chat" in uso and key.strip():
            return p

    # Fallback: qualquer provider com chave configurada
    for p in ordem:
        if key_map.get(p, "").strip():
            return p

    return None


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
    import httpx

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

    try:
        async with get_db_direct() as db:
            # ── Verifica se chatbot está ativo para a empresa ──────────────────
            async with db.execute(
                """SELECT ativo, system_prompt, boas_vindas_ativo, boas_vindas_msg
                   FROM chatbot_config WHERE empresa_id=?""",
                (empresa_id,)
            ) as cur:
                cfg = await cur.fetchone()

            if cfg and not cfg["ativo"]:
                logger.debug("[chatbot] Chatbot desativado para empresa %s", empresa_id)
                return

            system_prompt = (cfg["system_prompt"] if cfg and cfg["system_prompt"]
                             else _DEFAULT_SYSTEM)
            boas_vindas_ativo = cfg["boas_vindas_ativo"] if cfg else False
            boas_vindas_msg   = cfg["boas_vindas_msg"]   if cfg else ""

            # Enriquece system prompt com nome da empresa
            system_prompt = (
                f"Você é o assistente virtual de {empresa_nome}. "
                + system_prompt
            )

            # ── Busca FAQ para injetar como exemplos no prompt ─────────────────
            async with db.execute(
                "SELECT pergunta, resposta FROM chatbot_faq WHERE empresa_id=? AND ativo=TRUE LIMIT 30",
                (empresa_id,)
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
                   WHERE empresa_id=? AND aprovado=TRUE
                   ORDER BY created_at DESC LIMIT 10""",
                (empresa_id,)
            ) as cur:
                exemplos = await cur.fetchall()

            if exemplos:
                ex_text = "\n\nExemplos aprovados de conversas anteriores:\n"
                for ex in exemplos:
                    ex_text += f"P: {ex['pergunta']}\nR: {ex['resposta']}\n\n"
                system_prompt += ex_text

            # ── Verifica se é a primeira mensagem (boas-vindas) ────────────────
            async with db.execute(
                "SELECT COUNT(*) AS cnt FROM chat_historico WHERE empresa_id=? AND phone=?",
                (empresa_id, phone)
            ) as cur:
                cnt_row = await cur.fetchone()
            is_primeira_mensagem = (cnt_row["cnt"] == 0) if cnt_row else True

            # ── Salva mensagem do usuário no histórico ─────────────────────────
            await db.execute(
                "INSERT INTO chat_historico(empresa_id, phone, role, conteudo) VALUES(?,?,?,?)",
                (empresa_id, phone, "user", texto)
            )
            await db.commit()

            # ── Recupera histórico recente ─────────────────────────────────────
            async with db.execute(
                """SELECT role, conteudo FROM chat_historico
                   WHERE empresa_id=? AND phone=?
                   ORDER BY created_at DESC LIMIT ?""",
                (empresa_id, phone, _HIST_LIMIT)
            ) as cur:
                rows = await cur.fetchall()

            # Inverte (mais antigo primeiro) e monta messages para a IA
            historico = list(reversed(rows))
            messages: list[dict] = [{"role": "system", "content": system_prompt}]
            for row in historico:
                messages.append({"role": row["role"], "content": row["conteudo"]})

        # ── Seleciona provider e chama IA ─────────────────────────────────────
        provider = _chat_provider()
        if not provider:
            logger.warning("[chatbot] Nenhum provider de IA configurado para chat")
            return

        logger.info("[chatbot] Chamando %s para %s (empresa %s)", provider, phone, empresa_id)
        resposta = await _chamar_ia(provider, messages)

        if not resposta:
            return

        # ── Salva resposta no histórico + registro de aprendizado ─────────────
        async with get_db_direct() as db:
            await db.execute(
                "INSERT INTO chat_historico(empresa_id, phone, role, conteudo) VALUES(?,?,?,?)",
                (empresa_id, phone, "assistant", resposta)
            )
            # Salva o par pergunta/resposta para revisão no painel de Aprendizado
            await db.execute(
                """INSERT INTO chatbot_aprendizado(empresa_id, phone, pergunta, resposta)
                   VALUES(?,?,?,?)""",
                (empresa_id, phone, texto[:500], resposta[:1000])
            )
            await db.commit()

        # ── Envia boas-vindas na primeira mensagem ────────────────────────────
        jid = phone if "@" in phone else f"{phone}@s.whatsapp.net"
        if is_primeira_mensagem and boas_vindas_ativo and boas_vindas_msg.strip():
            msg_bv = boas_vindas_msg.replace("{nome}", empresa_nome)
            await evo_manager.send_text(instance, jid, msg_bv)
            logger.info("[chatbot] Boas-vindas enviada para %s", phone)

        # ── Envia resposta pelo WhatsApp ──────────────────────────────────────
        await evo_manager.send_text(instance, jid, resposta)

        logger.info("[chatbot] Resposta enviada para %s via %s (%d chars)",
                    phone, provider, len(resposta))

    except Exception as exc:
        logger.error("[chatbot] Erro ao responder mensagem de %s: %s", phone, exc, exc_info=True)
