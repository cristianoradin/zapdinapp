"""
app/routers/contabil.py
Módulo Contábil — endpoints para escritório de contabilidade.

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

import asyncio
import json
import logging
import os
import shutil
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from ..core.database import get_db
from ..core.security import get_current_user

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
    data_emissao: Optional[str] = None
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


# ── Helper: enviar boas-vindas WA ─────────────────────────────────────────────

async def _enviar_boas_vindas(empresa_id: int, telefone: str, nome: str, db) -> None:
    """Envia mensagem de boas-vindas via WhatsApp para o número cadastrado."""
    try:
        from ..main import wa_manager
        sessoes = list(wa_manager._sessions.values())
        if not sessoes:
            logger.warning("[contabil] Nenhuma sessão WA para enviar boas-vindas a %s", telefone)
            return

        sessao = sessoes[0]
        phone_wa = "55" + telefone if not telefone.startswith("55") else telefone

        msg = (
            f"👋 *Olá, {nome}!*\n\n"
            f"Seu cadastro no nosso escritório de contabilidade foi realizado com sucesso! ✅\n\n"
            f"*Como enviar seus documentos:*\n"
            f"📄 Envie suas *Notas Fiscais* (imagens ou PDF) diretamente aqui neste chat.\n"
            f"📊 Aceitamos NF-e, NF-Ce e CT-e.\n\n"
            f"Nossa equipe irá processar seus documentos e mantê-lo informado. 🚀\n\n"
            f"_Dúvidas? Responda esta mensagem._"
        )

        await sessao.send_text(phone_wa, msg)

        async with db.execute(
            "UPDATE empresas_contabil SET boas_vindas_enviadas=TRUE WHERE id=?",
            (empresa_id,)
        ):
            pass
        await db.commit()

        # Feed
        await db.execute(
            "INSERT INTO contabil_feed(empresa_id, tipo, descricao) VALUES(?,?,?)",
            (empresa_id, "boas_vindas", f"Mensagem de boas-vindas enviada para {nome}")
        )
        await db.commit()
        logger.info("[contabil] Boas-vindas enviadas para %s (%s)", nome, telefone)

    except Exception as e:
        logger.error("[contabil] Erro ao enviar boas-vindas: %s", e)


# ── CRUD Empresas ─────────────────────────────────────────────────────────────

@router.get("/empresas")
async def listar_empresas(
    q: Optional[str] = None,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    sql = """
        SELECT ec.*,
               COUNT(df.id) FILTER (WHERE df.status != 'aprovado') AS docs_pendentes,
               COUNT(df.id) FILTER (WHERE df.status = 'aprovado')  AS docs_aprovados,
               COUNT(df.id) FILTER (WHERE df.status = 'ocr_erro')  AS docs_erro,
               COUNT(df.id)                                         AS docs_total
        FROM empresas_contabil ec
        LEFT JOIN documentos_fiscais df ON df.empresa_id = ec.id
    """
    params = []
    if q:
        sql += " WHERE ec.nome ILIKE ? OR ec.cnpj LIKE ? OR ec.telefone LIKE ?"
        like = f"%{q}%"
        params = [like, like, like]
    sql += " GROUP BY ec.id ORDER BY ec.nome"

    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.post("/empresas", status_code=201)
async def criar_empresa(
    body: EmpresaContabilCreate,
    bg: BackgroundTasks,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    # Verifica duplicata de telefone
    async with db.execute(
        "SELECT id FROM empresas_contabil WHERE telefone=?", (body.telefone,)
    ) as cur:
        if await cur.fetchone():
            raise HTTPException(400, "Telefone já cadastrado para outra empresa.")

    async with db.execute(
        """INSERT INTO empresas_contabil
           (nome, cnpj, ie, cpf, rg, endereco, cidade, uf, telefone, email, regime_tributario)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (body.nome, body.cnpj, body.ie, body.cpf, body.rg,
         body.endereco, body.cidade, body.uf, body.telefone,
         body.email, body.regime_tributario)
    ) as cur:
        empresa_id = cur.lastrowid
    await db.commit()

    # Feed
    await db.execute(
        "INSERT INTO contabil_feed(empresa_id, tipo, descricao) VALUES(?,?,?)",
        (empresa_id, "cadastro", f"Empresa '{body.nome}' cadastrada")
    )
    await db.commit()

    # Boas-vindas em background
    bg.add_task(_enviar_boas_vindas, empresa_id, body.telefone, body.nome, db)

    return {"id": empresa_id, "ok": True}


@router.get("/empresas/{empresa_id}")
async def get_empresa(empresa_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    async with db.execute(
        "SELECT * FROM empresas_contabil WHERE id=?", (empresa_id,)
    ) as cur:
        row = await cur.fetchone()
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
    fields, params = [], []
    for f in ["nome", "cnpj", "ie", "cpf", "rg", "endereco", "cidade", "uf",
              "telefone", "email", "regime_tributario"]:
        val = getattr(body, f, None)
        if val is not None:
            fields.append(f"{f}=?")
            params.append(val)
    if not fields:
        raise HTTPException(400, "Nenhum campo para atualizar.")
    params.append(empresa_id)
    await db.execute(
        f"UPDATE empresas_contabil SET {', '.join(fields)}, updated_at=NOW() WHERE id=?",
        params
    )
    await db.commit()
    return {"ok": True}


@router.delete("/empresas/{empresa_id}", status_code=204)
async def deletar_empresa(
    empresa_id: int, db=Depends(get_db), user=Depends(get_current_user)
):
    await db.execute("DELETE FROM empresas_contabil WHERE id=?", (empresa_id,))
    await db.commit()


# ── Dashboard (3 cards + tabela de docs recentes) ────────────────────────────

@router.get("/dashboard")
async def dashboard(db=Depends(get_db), user=Depends(get_current_user)):
    hoje = date.today().isoformat()

    async with db.execute(
        "SELECT COUNT(*) AS total FROM documentos_fiscais WHERE created_at::date = ?", (hoje,)
    ) as cur:
        docs_hoje = (await cur.fetchone())["total"]

    async with db.execute(
        "SELECT COUNT(*) AS total FROM documentos_fiscais WHERE status IN ('ocr_pendente','revisao_manual')"
    ) as cur:
        pendencias = (await cur.fetchone())["total"]

    async with db.execute(
        """SELECT
            COUNT(*) FILTER (WHERE status = 'aprovado')  AS aprovados,
            COUNT(*) FILTER (WHERE status != 'recebido') AS processados
           FROM documentos_fiscais"""
    ) as cur:
        row = await cur.fetchone()
        aprovados = row["aprovados"] or 0
        processados = row["processados"] or 0
        taxa_ocr = round((aprovados / processados * 100), 1) if processados > 0 else 0.0

    async with db.execute(
        """SELECT df.*, ec.nome AS empresa_nome
           FROM documentos_fiscais df
           LEFT JOIN empresas_contabil ec ON ec.id = df.empresa_id
           ORDER BY df.created_at DESC
           LIMIT 50"""
    ) as cur:
        docs = [dict(r) for r in await cur.fetchall()]

    return {
        "docs_hoje": docs_hoje,
        "pendencias": pendencias,
        "taxa_ocr": taxa_ocr,
        "documentos": docs,
    }


# ── Documentos ────────────────────────────────────────────────────────────────

@router.get("/documentos")
async def listar_documentos(
    empresa_id: Optional[int] = None,
    status: Optional[str] = None,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    sql = """
        SELECT df.*, ec.nome AS empresa_nome
        FROM documentos_fiscais df
        LEFT JOIN empresas_contabil ec ON ec.id = df.empresa_id
        WHERE 1=1
    """
    params = []
    if empresa_id:
        sql += " AND df.empresa_id=?"
        params.append(empresa_id)
    if status:
        sql += " AND df.status=?"
        params.append(status)
    sql += " ORDER BY df.created_at DESC LIMIT 200"

    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.get("/documentos/{doc_id}")
async def get_documento(doc_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    async with db.execute(
        """SELECT df.*, ec.nome AS empresa_nome
           FROM documentos_fiscais df
           LEFT JOIN empresas_contabil ec ON ec.id = df.empresa_id
           WHERE df.id=?""",
        (doc_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Documento não encontrado.")
    d = dict(row)
    # Parse JSON fields
    for f in ("dados_ocr", "dados_manual"):
        if d.get(f) and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except Exception:
                pass
    return d


@router.get("/documentos/{doc_id}/arquivo")
async def download_documento(doc_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    async with db.execute(
        "SELECT arquivo_path, arquivo_mime, arquivo_nome FROM documentos_fiscais WHERE id=?",
        (doc_id,)
    ) as cur:
        row = await cur.fetchone()
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
    dados = body.model_dump(exclude_none=True)
    valor_total = dados.get("valor_total")
    emitente_nome = dados.get("emitente_nome")
    emitente_cnpj = dados.get("emitente_cnpj")
    dest_nome = dados.get("destinatario_nome")
    dest_cnpj = dados.get("destinatario_cnpj")
    chave = dados.get("chave_acesso")
    numero = dados.get("numero_nf")
    data_emis = dados.get("data_emissao")

    await db.execute(
        """UPDATE documentos_fiscais SET
            status='revisao_manual', dados_manual=?, chave_acesso=COALESCE(?,chave_acesso),
            numero_nf=COALESCE(?,numero_nf), emitente_nome=COALESCE(?,emitente_nome),
            emitente_cnpj=COALESCE(?,emitente_cnpj), destinatario_nome=COALESCE(?,destinatario_nome),
            destinatario_cnpj=COALESCE(?,destinatario_cnpj),
            valor_total=COALESCE(?,valor_total), data_emissao=COALESCE(?::date,data_emissao),
            updated_at=NOW()
           WHERE id=?""",
        (json.dumps(dados, ensure_ascii=False), chave, numero,
         emitente_nome, emitente_cnpj, dest_nome, dest_cnpj,
         valor_total, data_emis, doc_id)
    )
    await db.execute(
        "INSERT INTO contabil_feed(documento_id, tipo, descricao) VALUES(?,?,?)",
        (doc_id, "manual", f"Dados inseridos manualmente pelo contador — NF {numero or '?'}")
    )
    await db.commit()
    return {"ok": True}


@router.put("/documentos/{doc_id}/aprovar")
async def aprovar_documento(
    doc_id: int, db=Depends(get_db), user=Depends(get_current_user)
):
    await db.execute(
        "UPDATE documentos_fiscais SET status='aprovado', updated_at=NOW() WHERE id=?",
        (doc_id,)
    )
    await db.execute(
        "INSERT INTO contabil_feed(documento_id, tipo, descricao) VALUES(?,?,?)",
        (doc_id, "aprovado", "Documento aprovado pelo contador")
    )
    await db.commit()
    return {"ok": True}


@router.put("/documentos/{doc_id}/reprocessar")
async def reprocessar_ocr(
    doc_id: int,
    bg: BackgroundTasks,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Re-envia documento para a fila OCR."""
    async with db.execute(
        "SELECT arquivo_path FROM documentos_fiscais WHERE id=?", (doc_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(404, "Documento não encontrado.")

    await db.execute(
        "UPDATE documentos_fiscais SET status='ocr_pendente', erro_msg=NULL, updated_at=NOW() WHERE id=?",
        (doc_id,)
    )
    # Reseta o job
    await db.execute(
        """INSERT INTO ocr_jobs(documento_id, status, tentativas)
           VALUES(?, 'pending', 0)
           ON CONFLICT(documento_id) DO UPDATE SET status='pending', tentativas=0, erro=NULL""",
        (doc_id,)
    )
    await db.commit()

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
    """
    ext = Path(arquivo.filename or "doc").suffix or ".jpg"
    nome_arquivo = f"{uuid.uuid4().hex}{ext}"
    dest_path = str(_UPLOAD_DIR / nome_arquivo)

    with open(dest_path, "wb") as f:
        shutil.copyfileobj(arquivo.file, f)

    mime = arquivo.content_type or "image/jpeg"

    async with db.execute(
        """INSERT INTO documentos_fiscais
           (empresa_id, status, arquivo_path, arquivo_mime, arquivo_nome)
           VALUES (?, 'ocr_pendente', ?, ?, ?)""",
        (empresa_id, dest_path, mime, arquivo.filename)
    ) as cur:
        doc_id = cur.lastrowid
    await db.commit()

    # Cria job OCR
    await db.execute(
        "INSERT INTO ocr_jobs(documento_id) VALUES(?) ON CONFLICT DO NOTHING",
        (doc_id,)
    )
    await db.execute(
        "INSERT INTO contabil_feed(empresa_id, documento_id, tipo, descricao) VALUES(?,?,?,?)",
        (empresa_id, doc_id, "recebido", f"Documento recebido via WhatsApp: {arquivo.filename}")
    )
    await db.commit()

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
    ext = Path(arquivo.filename or "doc").suffix or ".jpg"
    nome_arquivo = f"{uuid.uuid4().hex}{ext}"
    dest_path = str(_UPLOAD_DIR / nome_arquivo)

    with open(dest_path, "wb") as f:
        shutil.copyfileobj(arquivo.file, f)

    mime = arquivo.content_type or "image/jpeg"

    async with db.execute(
        """INSERT INTO documentos_fiscais
           (empresa_id, status, arquivo_path, arquivo_mime, arquivo_nome)
           VALUES (?, 'ocr_pendente', ?, ?, ?)""",
        (empresa_id, dest_path, mime, arquivo.filename)
    ) as cur:
        doc_id = cur.lastrowid
    await db.commit()

    await db.execute(
        "INSERT INTO ocr_jobs(documento_id) VALUES(?) ON CONFLICT DO NOTHING", (doc_id,)
    )
    await db.execute(
        "INSERT INTO contabil_feed(empresa_id, documento_id, tipo, descricao) VALUES(?,?,?,?)",
        (empresa_id, doc_id, "upload", f"Upload manual: {arquivo.filename}")
    )
    await db.commit()

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
    async with db.execute(
        """SELECT cf.*, ec.nome AS empresa_nome
           FROM contabil_feed cf
           LEFT JOIN empresas_contabil ec ON ec.id = cf.empresa_id
           ORDER BY cf.criado_em DESC
           LIMIT ?""",
        (limit,)
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
