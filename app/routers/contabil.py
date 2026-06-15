"""
app/routers/contabil.py
Módulo Contábil — endpoints para escritório de contabilidade.

Router HTTP fino: validação de entrada, chamada ao repositório/serviço, resposta.
SQL em app/repositories/contabil_repository.py;
regra de negócio (boas-vindas WA) em app/services/contabil_service.py.

Rotas:
  GET/POST  /api/contabil/empresas
  GET/PUT/DELETE /api/contabil/empresas/{id}
  GET       /api/contabil/dashboard        — métricas 3 cards + feed
  GET       /api/contabil/documentos       — listagem com filtros
  GET       /api/contabil/documentos/{id}
  PUT       /api/contabil/documentos/{id}/manual — entrada manual de dados
  PUT       /api/contabil/documentos/{id}/aprovar
  POST      /api/contabil/webhook          — recebe docs do WhatsApp
  GET       /api/contabil/feed             — feed de atividade recente
"""
from __future__ import annotations

import logging
import shutil
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from ..core.database import get_db
from ..core.security import get_current_user
from ..repositories import ContabilRepository
from ..repositories.contabil_repository import EMPRESA_FIELDS
from ..services.contabil_service import (  # noqa: F401 — re-export p/ compatibilidade
    _MSG_BOAS_VINDAS,
    _enviar_boas_vindas,
    _entregar_boas_vindas,
    processar_boasvindas_pendentes,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contabil", tags=["contabil"])

_UPLOAD_DIR = Path("data/contabil_docs")
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_REGIMES = [
    "simples_nacional", "lucro_presumido", "lucro_real",
    "mei", "isento", "outro"
]

# ── Modelos Pydantic ──────────────────────────────────────────────────────────

class EmpresaContabilCreate(BaseModel):
    nome: str
    cnpj: Optional[str] = None
    ie: Optional[str] = None
    cpf: Optional[str] = None
    rg: Optional[str] = None
    endereco: Optional[str] = None
    numero_endereco: Optional[str] = None
    bairro: Optional[str] = None
    cep: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    telefone: str
    email: Optional[str] = None
    regime_tributario: str = "simples_nacional"

    @field_validator("telefone")
    @classmethod
    def normalizar_telefone(cls, v: str) -> str:
        return "".join(c for c in v if c.isdigit())

    @field_validator("regime_tributario")
    @classmethod
    def validar_regime(cls, v: str) -> str:
        if v not in _REGIMES:
            raise ValueError(f"Regime deve ser um de: {_REGIMES}")
        return v


class EmpresaContabilUpdate(EmpresaContabilCreate):
    telefone: Optional[str] = None  # type: ignore[assignment]


class DadosManuaisNF(BaseModel):
    tipo: Optional[str] = None
    chave_acesso: Optional[str] = None
    numero_nf: Optional[str] = None
    serie: Optional[str] = None
    data_emissao: Optional[date] = None
    natureza_operacao: Optional[str] = None
    emitente_nome: Optional[str] = None
    emitente_cnpj: Optional[str] = None
    emitente_ie: Optional[str] = None
    destinatario_nome: Optional[str] = None
    destinatario_cnpj: Optional[str] = None
    destinatario_cpf: Optional[str] = None
    valor_total: Optional[float] = None
    observacoes: Optional[str] = None
    itens: Optional[list] = None
    totais: Optional[dict] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _salvar_upload(arquivo: UploadFile) -> tuple[str, str]:
    """Salva o arquivo em disco. Retorna (dest_path, mime)."""
    ext = Path(arquivo.filename or "doc").suffix or ".jpg"
    nome_arquivo = f"{uuid.uuid4().hex}{ext}"
    dest_path = str(_UPLOAD_DIR / nome_arquivo)
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(arquivo.file, f)
    return dest_path, (arquivo.content_type or "image/jpeg")


# ── CRUD Empresas ─────────────────────────────────────────────────────────────

@router.get("/empresas")
async def listar_empresas(
    q: Optional[str] = None,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    tenant_id = user["empresa_id"]
    return await ContabilRepository(db).listar_empresas(tenant_id, q)


@router.post("/empresas", status_code=201)
async def criar_empresa(
    body: EmpresaContabilCreate,
    bg: BackgroundTasks,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    tenant_id = user["empresa_id"]
    repo = ContabilRepository(db)
    # Verifica duplicata de telefone DENTRO do mesmo tenant
    if await repo.telefone_existe(tenant_id, body.telefone):
        raise HTTPException(400, "Telefone já cadastrado para outra empresa.")

    empresa_id = await repo.criar_empresa(tenant_id, body.model_dump())

    # Feed
    await repo.add_evento(
        tenant_id, "cadastro", f"Empresa '{body.nome}' cadastrada", empresa_id=empresa_id
    )

    # Boas-vindas em background
    bg.add_task(_enviar_boas_vindas, empresa_id, body.telefone, body.nome, db)

    return {"id": empresa_id, "ok": True}


@router.get("/empresas/{empresa_id}")
async def get_empresa(empresa_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user["empresa_id"]
    row = await ContabilRepository(db).get_empresa(tenant_id, empresa_id)
    if not row:
        raise HTTPException(404, "Empresa não encontrada.")
    return dict(row)


@router.put("/empresas/{empresa_id}")
async def atualizar_empresa(
    empresa_id: int,
    body: EmpresaContabilUpdate,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    tenant_id = user["empresa_id"]
    repo = ContabilRepository(db)
    # Confirma posse antes de atualizar
    if not await repo.empresa_existe(tenant_id, empresa_id):
        raise HTTPException(404, "Empresa não encontrada.")
    campos = {
        f: getattr(body, f, None)
        for f in EMPRESA_FIELDS
        if getattr(body, f, None) is not None
    }
    if not campos:
        raise HTTPException(400, "Nenhum campo para atualizar.")
    await repo.atualizar_empresa(tenant_id, empresa_id, campos)
    return {"ok": True}


@router.delete("/empresas/{empresa_id}", status_code=204)
async def deletar_empresa(
    empresa_id: int, db=Depends(get_db), user=Depends(get_current_user)
):
    tenant_id = user["empresa_id"]
    await ContabilRepository(db).deletar_empresa(tenant_id, empresa_id)


@router.post("/empresas/{empresa_id}/reenviar-boasvindas")
async def reenviar_boasvindas(
    empresa_id: int,
    bg: BackgroundTasks,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Reenvia a mensagem de boas-vindas via WhatsApp para a empresa."""
    tenant_id = user["empresa_id"]
    repo = ContabilRepository(db)
    row = await repo.get_nome_telefone(tenant_id, empresa_id)
    if not row:
        raise HTTPException(404, "Empresa não encontrada.")

    nome, telefone = row["nome"], row["telefone"]

    # Reseta flag para que o reenvio seja registrado corretamente
    await repo.set_boas_vindas(tenant_id, empresa_id, False)

    bg.add_task(_enviar_boas_vindas, empresa_id, telefone, nome, db)
    return {"ok": True, "mensagem": f"Reenvio de boas-vindas agendado para {nome}."}


# ── Dashboard (3 cards + tabela de docs recentes) ────────────────────────────

@router.get("/dashboard")
async def dashboard(db=Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user["empresa_id"]
    repo = ContabilRepository(db)
    hoje = date.today()  # asyncpg exige date object, não string isoformat

    return {
        "docs_hoje": await repo.dashboard_docs_hoje(tenant_id, hoje),
        "pendencias": await repo.dashboard_pendencias(tenant_id),
        "taxa_ocr": await repo.dashboard_taxa_ocr(tenant_id),
        "documentos": await repo.dashboard_docs_recentes(tenant_id),
    }


# ── Documentos ────────────────────────────────────────────────────────────────

@router.get("/documentos")
async def listar_documentos(
    empresa_id: Optional[int] = None,
    status: Optional[str] = None,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    tenant_id = user["empresa_id"]
    return await ContabilRepository(db).listar_documentos(tenant_id, empresa_id, status)


@router.get("/documentos/{doc_id}")
async def get_documento(doc_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user["empresa_id"]
    doc = await ContabilRepository(db).get_documento(tenant_id, doc_id)
    if not doc:
        raise HTTPException(404, "Documento não encontrado.")
    return doc


@router.get("/documentos/{doc_id}/arquivo")
async def download_documento(doc_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    tenant_id = user["empresa_id"]
    row = await ContabilRepository(db).get_arquivo(tenant_id, doc_id)
    if not row or not row["arquivo_path"] or not os.path.exists(row["arquivo_path"]):
        raise HTTPException(404, "Arquivo não encontrado.")
    return FileResponse(
        row["arquivo_path"],
        media_type=row["arquivo_mime"] or "application/octet-stream",
        filename=row["arquivo_nome"] or f"doc_{doc_id}"
    )


@router.put("/documentos/{doc_id}/manual")
async def entrada_manual(
    doc_id: int,
    body: DadosManuaisNF,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Contador preenche manualmente os dados de um documento com erro de OCR."""
    tenant_id = user["empresa_id"]
    repo = ContabilRepository(db)
    # Confirma posse antes de atualizar
    if not await repo.documento_existe(tenant_id, doc_id):
        raise HTTPException(404, "Documento não encontrado.")
    await repo.entrada_manual(tenant_id, doc_id, body.model_dump(exclude_none=True))
    return {"ok": True}


@router.put("/documentos/{doc_id}/aprovar")
async def aprovar_documento(
    doc_id: int, db=Depends(get_db), user=Depends(get_current_user)
):
    tenant_id = user["empresa_id"]
    repo = ContabilRepository(db)
    if not await repo.documento_existe(tenant_id, doc_id):
        raise HTTPException(404, "Documento não encontrado.")
    await repo.aprovar_documento(tenant_id, doc_id)
    return {"ok": True}


@router.put("/documentos/{doc_id}/reprocessar")
async def reprocessar_ocr(
    doc_id: int,
    bg: BackgroundTasks,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Re-envia documento para a fila OCR."""
    tenant_id = user["empresa_id"]
    repo = ContabilRepository(db)
    row = await repo.get_documento_arquivo_path(tenant_id, doc_id)
    if not row:
        raise HTTPException(404, "Documento não encontrado.")

    await repo.reprocessar_documento(tenant_id, doc_id)

    from ..services.ocr_service import extrair_dados_fiscal
    bg.add_task(extrair_dados_fiscal, doc_id, row["arquivo_path"])
    return {"ok": True, "msg": "Reprocessamento iniciado"}


# ── Webhook WhatsApp (recebe documentos das empresas clientes) ─────────────────

@router.post("/webhook/wa-doc")
async def receber_doc_wa(
    bg: BackgroundTasks,
    empresa_id: int,
    arquivo: UploadFile = File(...),
    db=Depends(get_db),
):
    """
    Chamado internamente quando uma empresa registrada envia um documento via WA.
    Salva o arquivo, cria o documento_fiscal e enfileira OCR.
    tenant_id é herdado da empresas_contabil.
    """
    repo = ContabilRepository(db)
    # Resolve tenant_id pela empresa contábil
    tenant_id = await repo.get_tenant_da_empresa(empresa_id)
    if tenant_id is None and not await repo.empresa_existe_global(empresa_id):
        raise HTTPException(404, "Empresa contábil não encontrada.")

    dest_path, mime = _salvar_upload(arquivo)

    doc_id = await repo.criar_documento(
        tenant_id, empresa_id, dest_path, mime, arquivo.filename,
        "recebido", f"Documento recebido via WhatsApp: {arquivo.filename}",
    )

    from ..services.ocr_service import extrair_dados_fiscal
    bg.add_task(extrair_dados_fiscal, doc_id, dest_path)

    return {"ok": True, "documento_id": doc_id}


# ── Upload manual pelo contador ───────────────────────────────────────────────

@router.post("/documentos/upload")
async def upload_documento(
    bg: BackgroundTasks,
    empresa_id: int,
    arquivo: UploadFile = File(...),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Contador faz upload manual de um documento para uma empresa."""
    tenant_id = user["empresa_id"]
    repo = ContabilRepository(db)
    # Confirma que empresa_contabil pertence ao tenant
    if not await repo.empresa_existe(tenant_id, empresa_id):
        raise HTTPException(403, "Empresa contábil não pertence à sua organização.")

    dest_path, mime = _salvar_upload(arquivo)

    doc_id = await repo.criar_documento(
        tenant_id, empresa_id, dest_path, mime, arquivo.filename,
        "upload", f"Upload manual: {arquivo.filename}",
    )

    from ..services.ocr_service import extrair_dados_fiscal
    bg.add_task(extrair_dados_fiscal, doc_id, dest_path)

    return {"ok": True, "documento_id": doc_id}


# ── Feed de atividade ─────────────────────────────────────────────────────────

@router.get("/feed")
async def feed_atividade(
    limit: int = 50,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    tenant_id = user["empresa_id"]
    return await ContabilRepository(db).listar_feed(tenant_id, limit)


@router.get("/ai-status")
async def ai_status(provider: str = "openai", user=Depends(get_current_user)):
    """Verifica se o provider de IA está configurado e acessível."""
    from ..core.config import settings
    import httpx

    provider = provider.lower().strip()

    if provider == "openai":
        api_key = getattr(settings, "openai_api_key", "") or ""
        if not api_key:
            return {"ativa": False, "motivo": "OpenAI API key não configurada"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if r.status_code == 200:
                return {"ativa": True}
            return {"ativa": False, "motivo": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"ativa": False, "motivo": str(e)}

    elif provider == "gemini":
        api_key = getattr(settings, "gemini_api_key", "") or ""
        if not api_key:
            return {"ativa": False, "motivo": "Gemini API key não configurada"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                )
            if r.status_code == 200:
                return {"ativa": True}
            detail = r.json().get("error", {}).get("message", f"HTTP {r.status_code}")
            return {"ativa": False, "motivo": detail}
        except Exception as e:
            return {"ativa": False, "motivo": str(e)}

    elif provider == "anthropic":
        api_key = getattr(settings, "anthropic_api_key", "") or ""
        if not api_key:
            return {"ativa": False, "motivo": "Anthropic API key não configurada"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5",
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
            # 200 = ok, 400 com erro de validação ainda significa chave válida
            if r.status_code in (200, 400):
                return {"ativa": True}
            detail = r.json().get("error", {}).get("message", f"HTTP {r.status_code}")
            return {"ativa": False, "motivo": detail}
        except Exception as e:
            return {"ativa": False, "motivo": str(e)}

    elif provider == "groq":
        api_key = getattr(settings, "groq_api_key", "") or ""
        if not api_key:
            return {"ativa": False, "motivo": "Groq API key não configurada"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if r.status_code == 200:
                return {"ativa": True}
            detail = r.json().get("error", {}).get("message", f"HTTP {r.status_code}")
            return {"ativa": False, "motivo": detail}
        except Exception as e:
            return {"ativa": False, "motivo": str(e)}

    return {"ativa": False, "motivo": f"Provider desconhecido: {provider}"}
