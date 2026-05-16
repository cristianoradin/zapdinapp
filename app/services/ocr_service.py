"""
app/services/ocr_service.py
Extração de dados fiscais (NF-e, NF-Ce) via OpenAI GPT-4o Vision.

Fluxo:
  1. Recebe caminho do arquivo (imagem ou PDF convertido para imagem)
  2. Envia para GPT-4o Vision com prompt estruturado de extração fiscal
  3. Retorna dict com os campos padronizados da nota fiscal
  4. Atualiza documentos_fiscais + ocr_jobs no banco
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from ..core.config import settings
from ..core.database import get_db_direct

logger = logging.getLogger(__name__)

# Campos esperados na extração — alinhado com layout SEFAZ NF-e / NF-Ce
_PROMPT_FISCAL = """Você é um especialista em documentos fiscais brasileiros.
Analise a imagem de nota fiscal fornecida e extraia os dados no formato JSON abaixo.
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


async def _file_to_base64(path: str) -> tuple[str, str]:
    """Retorna (base64_data, mime_type). Converte PDF para JPEG via poppler se disponível."""
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        mime = "image/jpeg"

    if mime == "application/pdf":
        # Tenta converter primeira página do PDF para JPEG
        try:
            import subprocess
            out_prefix = path + "_page"
            result = subprocess.run(
                ["pdftoppm", "-jpeg", "-r", "150", "-f", "1", "-l", "1", path, out_prefix],
                capture_output=True, timeout=30
            )
            page_file = out_prefix + "-1.jpg"
            if result.returncode == 0 and os.path.exists(page_file):
                with open(page_file, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                os.unlink(page_file)
                return data, "image/jpeg"
        except Exception as e:
            logger.warning("[ocr] PDF→JPEG falhou (%s), enviando PDF direto", e)
        # Fallback: envia PDF codificado (GPT-4o aceita PDF base64 no Vision)
        mime = "application/pdf"

    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode(), mime


async def extrair_dados_fiscal(documento_id: int, arquivo_path: str) -> dict[str, Any]:
    """
    Chama GPT-4o Vision para extrair dados da nota fiscal.
    Atualiza o banco automaticamente.
    Retorna os dados extraídos ou lança exceção em caso de falha.
    """
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY não configurada no .env")

    logger.info("[ocr] Iniciando extração — doc_id=%d, arquivo=%s", documento_id, arquivo_path)

    # Marca job como processing
    async with get_db_direct() as db:
        await db.execute(
            "UPDATE ocr_jobs SET status='processing', tentativas=tentativas+1 "
            "WHERE documento_id=?",
            (documento_id,)
        )
        await db.commit()

    try:
        img_b64, mime = await _file_to_base64(arquivo_path)

        payload = {
            "model": "gpt-4o",
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{img_b64}",
                                "detail": "high"
                            }
                        },
                        {
                            "type": "text",
                            "text": _PROMPT_FISCAL
                        }
                    ]
                }
            ]
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload
            )
            resp.raise_for_status()

        result = resp.json()
        raw_text = result["choices"][0]["message"]["content"].strip()

        # Limpa markdown se GPT retornar ```json ... ```
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        dados = json.loads(raw_text)

        # Determina status baseado na confiança
        confianca = dados.get("confianca", "media")
        novo_status = "aprovado" if confianca == "alta" else "revisao_manual"

        # Extrai campos de nível superior para colunas indexadas
        chave = dados.get("chave_acesso")
        numero = dados.get("numero_nf")
        emit = dados.get("emitente", {}) or {}
        dest = dados.get("destinatario", {}) or {}
        totais = dados.get("totais", {}) or {}
        valor_total = totais.get("valor_total_nf")
        data_emis = dados.get("data_emissao")

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
            # Feed
            await db.execute(
                "INSERT INTO contabil_feed(documento_id, tipo, descricao) VALUES(?,?,?)",
                (documento_id, "ocr_ok",
                 f"OCR concluído — confiança {confianca} — NF {numero or '?'}")
            )
            await db.commit()

        logger.info("[ocr] Extração concluída — doc_id=%d, status=%s", documento_id, novo_status)
        return dados

    except json.JSONDecodeError as e:
        erro = f"Resposta da IA não é JSON válido: {e}"
        await _marcar_erro(documento_id, erro)
        raise
    except httpx.HTTPStatusError as e:
        erro = f"Erro HTTP OpenAI {e.response.status_code}: {e.response.text[:200]}"
        await _marcar_erro(documento_id, erro)
        raise
    except Exception as e:
        await _marcar_erro(documento_id, str(e))
        raise


async def _marcar_erro(documento_id: int, erro_msg: str) -> None:
    """Marca documento e job como erro no banco e insere no feed."""
    try:
        async with get_db_direct() as db:
            await db.execute(
                "UPDATE documentos_fiscais SET status='ocr_erro', erro_msg=?, updated_at=NOW() WHERE id=?",
                (erro_msg[:1000], documento_id)
            )
            await db.execute(
                "UPDATE ocr_jobs SET status='failed', erro=? WHERE documento_id=?",
                (erro_msg[:1000], documento_id)
            )
            await db.execute(
                "INSERT INTO contabil_feed(documento_id, tipo, descricao) VALUES(?,?,?)",
                (documento_id, "ocr_erro", f"Erro OCR: {erro_msg[:200]}")
            )
            await db.commit()
    except Exception as e2:
        logger.error("[ocr] Falha ao marcar erro no banco: %s", e2)
    logger.error("[ocr] Extração falhou — doc_id=%d: %s", documento_id, erro_msg)


async def processar_fila_ocr() -> None:
    """Processa todos os jobs pendentes na fila OCR. Chamado pelo reporter ou startup."""
    try:
        async with get_db_direct() as db:
            async with db.execute(
                """SELECT oj.documento_id, df.arquivo_path
                   FROM ocr_jobs oj
                   JOIN documentos_fiscais df ON df.id = oj.documento_id
                   WHERE oj.status = 'pending' AND oj.tentativas < 3
                   ORDER BY oj.criado_em
                   LIMIT 10"""
            ) as cur:
                jobs = await cur.fetchall()

        for job in jobs:
            doc_id = job["documento_id"]
            path = job["arquivo_path"]
            if path and os.path.exists(path):
                try:
                    await extrair_dados_fiscal(doc_id, path)
                except Exception as e:
                    logger.error("[ocr] Job %d falhou: %s", doc_id, e)
                await asyncio.sleep(1)  # Rate limit OpenAI
            else:
                await _marcar_erro(doc_id, f"Arquivo não encontrado: {path}")
    except Exception as e:
        logger.error("[ocr] processar_fila_ocr: %s", e)
