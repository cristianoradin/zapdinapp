"""
dominio_router.py — Integração com o sistema Domínio (Thomson Reuters)

Rotas:
  GET  /api/dominio/config        → retorna configuração salva
  POST /api/dominio/config        → salva configuração
  POST /api/dominio/testar        → testa conexão com a API Domínio
  GET  /api/dominio/log           → lista log de envios recentes
  POST /api/dominio/enviar/{id}   → (futuro) envia documento fiscal manualmente
"""

import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dominio", tags=["dominio"])

# ── Chaves de config armazenadas na tabela `config` ──────────────────────────

_KEY = "dominio_config"


# ── Schemas ──────────────────────────────────────────────────────────────────

class DominioConfig(BaseModel):
    cnpj_origem: str = ""
    nome_origem: str = ""
    api_url: str = "https://api.dominio.com.br/v1"
    api_token: str = ""
    cnpj_escritorio: str = ""
    tipos: list[str] = ["nfe"]
    auto_envio: bool = False


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_config(db, empresa_id: int) -> dict[str, Any]:
    row = await db.fetchrow(
        "SELECT valor FROM config WHERE empresa_id=$1 AND chave=$2",
        empresa_id, _KEY,
    )
    if not row:
        return {}
    try:
        return json.loads(row["valor"])
    except Exception:
        return {}


# ── Rotas ─────────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    return await _get_config(db, empresa_id)


@router.post("/config")
async def save_config(
    body: DominioConfig,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    payload = body.model_dump()
    # Não sobrescrever token em branco se já há um salvo
    if not payload.get("api_token"):
        existing = await _get_config(db, empresa_id)
        if existing.get("api_token"):
            payload["api_token"] = existing["api_token"]

    await db.execute(
        """
        INSERT INTO config (empresa_id, chave, valor)
        VALUES ($1, $2, $3)
        ON CONFLICT (empresa_id, chave) DO UPDATE SET valor = EXCLUDED.valor
        """,
        empresa_id, _KEY, json.dumps(payload),
    )
    logger.info("Domínio config salva — empresa %s", empresa_id)
    return {"ok": True}


@router.post("/testar")
async def testar_conexao(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    cfg = await _get_config(db, empresa_id)

    api_url   = cfg.get("api_url", "").rstrip("/")
    api_token = cfg.get("api_token", "")

    if not api_url or not api_token:
        raise HTTPException(
            status_code=400,
            detail="Configure a URL e o token antes de testar.",
        )

    # Tenta um GET no endpoint de health/status da API Domínio
    test_endpoints = ["/status", "/ping", "/health", "/empresas"]
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        for ep in test_endpoints:
            try:
                resp = await client.get(api_url + ep, headers=headers)
                if resp.status_code < 500:
                    ok = resp.status_code < 400
                    return {
                        "ok": ok,
                        "mensagem": (
                            f"API respondeu {resp.status_code} em {ep}"
                            if ok
                            else f"Autenticação recusada ({resp.status_code})"
                        ),
                        "status_code": resp.status_code,
                    }
            except httpx.ConnectError:
                pass
            except Exception as e:
                logger.warning("Domínio testar %s: %s", ep, e)

    return {
        "ok": False,
        "mensagem": "Não foi possível conectar à API Domínio. Verifique a URL e a conectividade.",
    }


@router.get("/log")
async def get_log(
    limit: int = 50,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    # Verifica se a tabela existe antes de consultar
    exists = await db.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='dominio_envios')"
    )
    if not exists:
        return []
    rows = await db.fetch(
        """
        SELECT id, chave_nfe, nome_arquivo, tipo_doc, status, resposta, created_at
        FROM dominio_envios
        WHERE empresa_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        empresa_id, limit,
    )
    return [dict(r) for r in rows]


@router.post("/enviar/{documento_id}")
async def enviar_documento(
    documento_id: int,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Envia um documento fiscal específico ao sistema Domínio (envio manual)."""
    empresa_id = user["empresa_id"]
    cfg = await _get_config(db, empresa_id)

    if not cfg.get("api_token") or not cfg.get("api_url"):
        raise HTTPException(
            status_code=400,
            detail="Integração Domínio não configurada. Configure token e URL primeiro.",
        )

    # Busca o documento no banco
    doc = await db.fetchrow(
        "SELECT * FROM documentos_fiscais WHERE id=$1 AND empresa_id=$2",
        documento_id, empresa_id,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    # Verifica se o tipo está habilitado
    tipos = cfg.get("tipos", ["nfe"])
    tipo_doc = (doc.get("tipo_doc") or "nfe").lower()
    if tipo_doc not in tipos:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo '{tipo_doc}' não habilitado na configuração.",
        )

    # Prepara e envia — multipart/form-data com o XML
    xml_content = doc.get("xml_content") or b""
    if isinstance(xml_content, str):
        xml_content = xml_content.encode()

    api_url   = cfg["api_url"].rstrip("/")
    api_token = cfg["api_token"]
    headers   = {"Authorization": f"Bearer {api_token}"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            files = {"arquivo": (f"{doc.get('chave_nfe', 'doc')}.xml", xml_content, "text/xml")}
            data  = {
                "cnpj_emitente":    cfg.get("cnpj_origem", ""),
                "cnpj_escritorio":  cfg.get("cnpj_escritorio", ""),
                "tipo_documento":   tipo_doc.upper(),
            }
            resp = await client.post(
                f"{api_url}/documentos",
                headers=headers,
                files=files,
                data=data,
            )

        status  = "sent" if resp.status_code < 400 else "error"
        resposta = resp.text[:500] if resp.text else str(resp.status_code)

    except Exception as e:
        status  = "error"
        resposta = str(e)[:500]
        logger.error("Domínio enviar doc %s: %s", documento_id, e)

    # Registra no log (cria tabela se não existir)
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS dominio_envios (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL,
            documento_id INTEGER,
            chave_nfe TEXT,
            nome_arquivo TEXT,
            tipo_doc TEXT,
            status TEXT DEFAULT 'pending',
            resposta TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    await db.execute(
        """
        INSERT INTO dominio_envios
            (empresa_id, documento_id, chave_nfe, nome_arquivo, tipo_doc, status, resposta)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        """,
        empresa_id,
        documento_id,
        doc.get("chave_nfe"),
        doc.get("nome_arquivo"),
        tipo_doc,
        status,
        resposta,
    )

    if status == "error":
        raise HTTPException(status_code=502, detail=f"Erro ao enviar ao Domínio: {resposta}")

    return {"ok": True, "status": status, "resposta": resposta}
