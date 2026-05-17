"""
app/services/ocr_service.py
Extração de dados fiscais via IA com roteamento inteligente multi-provider.

Roteamento por tipo de arquivo:
  PDF  → Gemini (nativo) → Claude (nativo) → converte imagem → OpenAI → Groq
  Foto → provider ativo → fallback na ordem configurada

Cada provider tem sua própria função de chamada isolada.
Se um falhar (sem chave, rate limit, erro HTTP), passa para o próximo automaticamente.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from ..core.config import settings
from ..core.database import get_db_direct

logger = logging.getLogger(__name__)

# ── Prompt fiscal ─────────────────────────────────────────────────────────────

_PROMPT_FISCAL = """Você é um especialista em documentos fiscais brasileiros.
Analise o documento fiscal fornecido e extraia os dados no formato JSON abaixo.
Retorne SOMENTE o JSON, sem texto adicional, sem markdown.

{
  "tipo": "nfe | nfce | cte | outro",
  "chave_acesso": "string 44 dígitos ou null",
  "numero_nf": "string ou null",
  "serie": "string ou null",
  "data_emissao": "YYYY-MM-DD ou null",
  "natureza_operacao": "string ou null",
  "emitente": {
    "nome": "string ou null",
    "cnpj": "string só dígitos ou null",
    "ie": "string ou null",
    "endereco": "string ou null",
    "cidade": "string ou null",
    "uf": "string 2 letras ou null"
  },
  "destinatario": {
    "nome": "string ou null",
    "cnpj": "string só dígitos ou null",
    "cpf": "string só dígitos ou null",
    "ie": "string ou null",
    "endereco": "string ou null",
    "cidade": "string ou null",
    "uf": "string 2 letras ou null"
  },
  "itens": [
    {
      "descricao": "string",
      "quantidade": "number ou null",
      "unidade": "string ou null",
      "valor_unitario": "number ou null",
      "valor_total": "number ou null",
      "ncm": "string ou null",
      "cfop": "string ou null"
    }
  ],
  "totais": {
    "valor_produtos": "number ou null",
    "valor_desconto": "number ou null",
    "valor_frete": "number ou null",
    "valor_seguro": "number ou null",
    "valor_ipi": "number ou null",
    "valor_icms": "number ou null",
    "valor_pis": "number ou null",
    "valor_cofins": "number ou null",
    "valor_total_nf": "number ou null"
  },
  "pagamento": {
    "forma": "string ou null",
    "valor": "number ou null"
  },
  "observacoes": "string ou null",
  "confianca": "alta | media | baixa"
}"""


# ── Utilitários ───────────────────────────────────────────────────────────────

def _is_pdf(path: str) -> bool:
    mime, _ = mimetypes.guess_type(path)
    return (mime or "").lower() == "application/pdf"


def _file_to_base64(path: str) -> tuple[str, str]:
    """Lê arquivo e retorna (base64, mime_type)."""
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        mime = "image/jpeg"
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode(), mime


def _pdf_to_image_base64(path: str) -> Optional[tuple[str, str]]:
    """
    Converte primeira página do PDF em JPEG via pdftoppm.
    Retorna (base64, 'image/jpeg') ou None se falhar.
    """
    try:
        out_prefix = path + "_ocr_page"
        result = subprocess.run(
            ["pdftoppm", "-jpeg", "-r", "200", "-f", "1", "-l", "1", path, out_prefix],
            capture_output=True, timeout=30
        )
        page_file = out_prefix + "-1.jpg"
        if result.returncode == 0 and os.path.exists(page_file):
            with open(page_file, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            os.unlink(page_file)
            return data, "image/jpeg"
    except Exception as e:
        logger.warning("[ocr] pdftoppm falhou: %s", e)
    return None


def _limpar_json(raw: str) -> str:
    """Remove blocos markdown ```json ... ``` se presentes."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


# ── Chamadas por provider ─────────────────────────────────────────────────────

async def _call_gemini(path: str, is_pdf: bool) -> str:
    """
    Gemini Flash — lê PDF e imagem nativamente via base64 inline.
    Gratuito: 1.500 req/dia, 15 req/min.
    """
    key = settings.gemini_api_key
    if not key:
        raise ValueError("Gemini: chave não configurada")

    b64, mime = _file_to_base64(path)

    # Gemini 2.0 Flash — melhor custo-benefício com suporte a PDF
    model = "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

    payload = {
        "contents": [{
            "parts": [
                {
                    "inline_data": {
                        "mime_type": mime,
                        "data": b64
                    }
                },
                {"text": _PROMPT_FISCAL}
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048,
        }
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code == 429:
            raise RuntimeError("Gemini: rate limit atingido")
        resp.raise_for_status()

    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _limpar_json(text)


async def _call_anthropic(path: str, is_pdf: bool) -> str:
    """
    Claude Haiku — lê PDF e imagem nativamente.
    Tier gratuito inicial; depois pago por token.
    """
    key = settings.anthropic_api_key
    if not key:
        raise ValueError("Anthropic: chave não configurada")

    b64, mime = _file_to_base64(path)

    if is_pdf:
        # Claude aceita PDF como document type
        content_block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": b64,
            }
        }
    else:
        content_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime,
                "data": b64,
            }
        }

    payload = {
        "model": "claude-haiku-4-5",
        "max_tokens": 2048,
        "messages": [{
            "role": "user",
            "content": [
                content_block,
                {"type": "text", "text": _PROMPT_FISCAL}
            ]
        }]
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload
        )
        if resp.status_code == 429:
            raise RuntimeError("Anthropic: rate limit atingido")
        resp.raise_for_status()

    data = resp.json()
    text = data["content"][0]["text"]
    return _limpar_json(text)


async def _call_openai(path: str, b64: str = None, mime: str = None) -> str:
    """
    GPT-4o Vision — só imagem (PDF precisa ser convertido antes).
    """
    key = settings.openai_api_key
    if not key:
        raise ValueError("OpenAI: chave não configurada")

    if b64 is None:
        b64, mime = _file_to_base64(path)

    payload = {
        "model": "gpt-4o",
        "max_tokens": 2048,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{b64}",
                        "detail": "high"
                    }
                },
                {"type": "text", "text": _PROMPT_FISCAL}
            ]
        }]
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload
        )
        if resp.status_code == 429:
            raise RuntimeError("OpenAI: rate limit atingido")
        resp.raise_for_status()

    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    return _limpar_json(text)


async def _call_groq(path: str, b64: str = None, mime: str = None) -> str:
    """
    Groq Llama-4 Scout Vision — só imagem. Gratuito: 1.000 req/dia.
    """
    key = settings.groq_api_key
    if not key:
        raise ValueError("Groq: chave não configurada")

    if b64 is None:
        b64, mime = _file_to_base64(path)

    payload = {
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "max_tokens": 2048,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"}
                },
                {"type": "text", "text": _PROMPT_FISCAL}
            ]
        }]
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload
        )
        if resp.status_code == 429:
            raise RuntimeError("Groq: rate limit atingido")
        resp.raise_for_status()

    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    return _limpar_json(text)


# ── Roteador principal ────────────────────────────────────────────────────────

def _ocr_providers_habilitados() -> list[str]:
    """
    Retorna providers disponíveis para OCR em ordem de prioridade fixa:
      OpenAI → Gemini → Anthropic → Groq

    Critério de inclusão:
      1. Possuem chave API configurada
      2. Estão marcados com 'ocr' no ai_uso_* (USAR PARA OCR toggle)

    O sistema tenta cada provider em sequência (fallback automático).
    A prioridade é controlada exclusivamente pelos toggles — sem seletor adicional.
    """
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
        p for p in ["openai", "gemini", "anthropic", "groq"]
        if "ocr" in (uso_map.get(p) or "").split(",") and (key_map.get(p) or "").strip()
    ]


async def _rodar_com_fallback(path: str) -> tuple[str, str]:
    """
    Tenta extrair o documento percorrendo a cadeia de providers.
    Retorna (json_texto, provider_usado).

    Lógica de roteamento:
      PDF  → [nativos com OCR habilitado: gemini, anthropic] primeiro
             → se falharem, converte para imagem → [demais com OCR habilitado]
      Foto → provider ativo primeiro → demais habilitados em ordem
    Respeita 'USAR PARA OCR' e 'PROVEDOR ATIVO PARA OCR' da configuração.
    """
    is_pdf = _is_pdf(path)
    todos_habilitados = _ocr_providers_habilitados()

    if not todos_habilitados:
        raise RuntimeError(
            "Nenhum provider habilitado para OCR. "
            "Configure a chave API e ative 'USAR PARA OCR' em pelo menos um provider."
        )

    erros: list[str] = []
    logger.info("[ocr] Providers habilitados para OCR: %s | Ativo: %s", todos_habilitados, ativo)

    if is_pdf:
        # ── PDF: providers nativos (lêem PDF diretamente) que estão habilitados ──
        _nativos_todos = ["gemini", "anthropic"]
        providers_nativos = [p for p in todos_habilitados if p in _nativos_todos]

        for provider in providers_nativos:
            try:
                logger.info("[ocr] Tentando %s (PDF nativo)…", provider)
                if provider == "gemini":
                    result = await _call_gemini(path, is_pdf=True)
                elif provider == "anthropic":
                    result = await _call_anthropic(path, is_pdf=True)
                else:
                    continue
                logger.info("[ocr] Sucesso com %s", provider)
                return result, provider
            except Exception as e:
                msg = f"{provider}: {e}"
                erros.append(msg)
                logger.warning("[ocr] %s falhou — %s", provider, e)

        # ── PDF: fallback via conversão para imagem (providers sem suporte nativo) ──
        logger.info("[ocr] Nativos falharam — convertendo PDF para imagem…")
        converted = _pdf_to_image_base64(path)
        if converted:
            b64_img, mime_img = converted
            # Providers habilitados que NÃO são nativos (ou os nativos também como img)
            providers_img = [p for p in todos_habilitados if p not in providers_nativos]
            for provider in providers_img:
                try:
                    logger.info("[ocr] Tentando %s (PDF→imagem)…", provider)
                    if provider == "openai":
                        result = await _call_openai(path, b64_img, mime_img)
                    elif provider == "groq":
                        result = await _call_groq(path, b64_img, mime_img)
                    elif provider == "gemini":
                        result = await _call_gemini(path, is_pdf=False)
                    else:
                        continue
                    logger.info("[ocr] Sucesso com %s (imagem convertida)", provider)
                    return result, f"{provider}(pdf→img)"
                except Exception as e:
                    msg = f"{provider}(img): {e}"
                    erros.append(msg)
                    logger.warning("[ocr] %s falhou — %s", provider, e)
        else:
            erros.append("pdftoppm: conversão falhou (poppler não instalado?)")

    else:
        # ── IMAGEM: provider ativo primeiro, depois demais habilitados ────────
        ordem = todos_habilitados  # já vem ordenado com ativo na frente

        for provider in ordem:
            try:
                logger.info("[ocr] Tentando %s (imagem)…", provider)
                if provider == "gemini":
                    result = await _call_gemini(path, is_pdf=False)
                elif provider == "openai":
                    result = await _call_openai(path)
                elif provider == "anthropic":
                    result = await _call_anthropic(path, is_pdf=False)
                elif provider == "groq":
                    result = await _call_groq(path)
                else:
                    continue
                logger.info("[ocr] Sucesso com %s", provider)
                return result, provider
            except Exception as e:
                msg = f"{provider}: {e}"
                erros.append(msg)
                logger.warning("[ocr] %s falhou — %s", provider, e)

    raise RuntimeError(
        f"Todos os providers falharam. Erros: {' | '.join(erros)}"
    )


# ── Função principal ──────────────────────────────────────────────────────────

async def extrair_dados_fiscal(documento_id: int, arquivo_path: str) -> dict[str, Any]:
    """
    Extrai dados fiscais usando roteamento inteligente multi-provider.
    Atualiza o banco automaticamente.
    """
    logger.info("[ocr] Iniciando extração — doc_id=%d, arquivo=%s", documento_id, arquivo_path)

    async with get_db_direct() as db:
        await db.execute(
            "UPDATE ocr_jobs SET status='processing', tentativas=tentativas+1 WHERE documento_id=?",
            (documento_id,)
        )
        await db.commit()

    try:
        raw_json, provider_usado = await _rodar_com_fallback(arquivo_path)
        dados = json.loads(raw_json)

        confianca   = dados.get("confianca", "media")
        novo_status = "aprovado" if confianca == "alta" else "revisao_manual"

        chave       = dados.get("chave_acesso")
        numero      = dados.get("numero_nf")
        emit        = dados.get("emitente", {}) or {}
        dest        = dados.get("destinatario", {}) or {}
        totais      = dados.get("totais", {}) or {}
        valor_total = totais.get("valor_total_nf")
        # asyncpg exige objeto date, não string ISO
        _data_raw = dados.get("data_emissao")
        try:
            from datetime import date as _date
            data_emis = _date.fromisoformat(str(_data_raw)) if _data_raw else None
        except Exception:
            data_emis = None

        async with get_db_direct() as db:
            await db.execute(
                """UPDATE documentos_fiscais SET
                    status=?, dados_ocr=?, chave_acesso=?, numero_nf=?,
                    emitente_nome=?, emitente_cnpj=?, destinatario_nome=?,
                    destinatario_cnpj=?, valor_total=?, data_emissao=?,
                    updated_at=NOW()
                   WHERE id=?""",
                (
                    novo_status, json.dumps(dados, ensure_ascii=False),
                    chave, numero,
                    emit.get("nome"), emit.get("cnpj"),
                    dest.get("nome"), dest.get("cnpj"),
                    valor_total, data_emis,
                    documento_id
                )
            )
            await db.execute(
                "UPDATE ocr_jobs SET status='done', processado_em=NOW() WHERE documento_id=?",
                (documento_id,)
            )
            await db.execute(
                "INSERT INTO contabil_feed(documento_id, tipo, descricao) VALUES(?,?,?)",
                (documento_id, "ocr_ok",
                 f"OCR concluído via {provider_usado} — confiança {confianca} — NF {numero or '?'}")
            )
            await db.commit()

        logger.info("[ocr] Extração concluída — doc_id=%d, provider=%s, status=%s",
                    documento_id, provider_usado, novo_status)
        return dados

    except json.JSONDecodeError as e:
        await _marcar_erro(documento_id, f"JSON inválido retornado pela IA: {e}")
        raise
    except Exception as e:
        await _marcar_erro(documento_id, str(e))
        raise


async def _marcar_erro(documento_id: int, erro_msg: str) -> None:
    # Rate limit é transitório — mantém pending para ser retentado pelo reporter
    _is_rate_limit = "rate limit" in erro_msg.lower()
    job_status = "pending" if _is_rate_limit else "failed"
    doc_status = "ocr_pendente" if _is_rate_limit else "ocr_erro"
    try:
        async with get_db_direct() as db:
            await db.execute(
                "UPDATE documentos_fiscais SET status=?, erro_msg=?, updated_at=NOW() WHERE id=?",
                (doc_status, erro_msg[:1000], documento_id)
            )
            await db.execute(
                "UPDATE ocr_jobs SET status=?, erro=? WHERE documento_id=?",
                (job_status, erro_msg[:1000], documento_id)
            )
            if not _is_rate_limit:
                await db.execute(
                    "INSERT INTO contabil_feed(documento_id, tipo, descricao) VALUES(?,?,?)",
                    (documento_id, "ocr_erro", f"Erro OCR: {erro_msg[:200]}")
                )
            await db.commit()
    except Exception as e2:
        logger.error("[ocr] Falha ao marcar erro: %s", e2)
    if _is_rate_limit:
        logger.warning("[ocr] doc_id=%d: rate limit — será retentado automaticamente", documento_id)
    else:
        logger.error("[ocr] Extração falhou — doc_id=%d: %s", documento_id, erro_msg)


async def processar_fila_ocr() -> None:
    """Processa jobs pendentes na fila. Chamado pelo reporter ou startup."""
    try:
        async with get_db_direct() as db:
            async with db.execute(
                """SELECT oj.documento_id, df.arquivo_path
                   FROM ocr_jobs oj
                   JOIN documentos_fiscais df ON df.id = oj.documento_id
                   WHERE oj.status IN ('pending', 'failed') AND oj.tentativas < 5
                   ORDER BY oj.criado_em
                   LIMIT 10"""
            ) as cur:
                jobs = await cur.fetchall()

        for job in jobs:
            doc_id = job["documento_id"]
            path   = job["arquivo_path"]
            if path and os.path.exists(path):
                try:
                    await extrair_dados_fiscal(doc_id, path)
                except Exception as e:
                    logger.error("[ocr] Job %d falhou: %s", doc_id, e)
                await asyncio.sleep(1)
            else:
                await _marcar_erro(doc_id, f"Arquivo não encontrado: {path}")
    except Exception as e:
        logger.error("[ocr] processar_fila_ocr: %s", e)
