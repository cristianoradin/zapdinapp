import base64
import logging
import os
import secrets
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from ..core.database import get_db
from ..core.security import get_current_user, verify_erp_token

logger = logging.getLogger(__name__)

# Limite máximo de arquivo via ERP: 50 MB decoded (~67 MB em base64)
_MAX_B64_LEN = 67 * 1024 * 1024

router = APIRouter(prefix="/api/erp", tags=["erp"])

UPLOAD_DIR = "data/arquivos"

# In-memory: last ERP connection info (per empresa_id)
_last_call: dict = {}


def _record_call(empresa_id: int, request: Request, endpoint: str, ok: bool) -> None:
    _last_call[empresa_id] = {
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "ip": request.client.host if request.client else "?",
        "endpoint": endpoint,
        "status": "ok" if ok else "error",
        "total_calls": _last_call.get(empresa_id, {}).get("total_calls", 0) + 1,
    }


async def _verify_token(x_token: Optional[str], db, request: Request = None) -> int:
    """
    Verifica o token ERP e retorna o empresa_id correspondente.
    Usa hmac.compare_digest para evitar timing attacks.
    """
    ip = request.client.host if request and request.client else "?"
    if not x_token:
        logger.warning("[erp] Requisição sem token de ip=%s", ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token ERP não informado",
        )
    # Busca todos os tokens ERP ativos e compara com compare_digest
    async with db.execute(
        "SELECT empresa_id, value FROM config WHERE key='erp_token'"
    ) as cur:
        rows = await cur.fetchall()
    for row in rows:
        if verify_erp_token(x_token, row["value"]):
            return row["empresa_id"]
    logger.warning("[erp] Token inválido recebido de ip=%s token=%s...", ip, x_token[:8] if x_token else "")
    # Alerta Telegram — possível tentativa de acesso indevido (best-effort)
    try:
        import asyncio
        from ..services import telegram_service
        asyncio.create_task(telegram_service.notify_erp_invalid_token(ip))
    except Exception:
        pass
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token ERP inválido",
    )


class Produto(BaseModel):
    nome: str
    quantidade: Optional[float] = 1
    valor_unitario: Optional[str] = ""


class VendaPayload(BaseModel):
    telefone: str
    nome: str
    # Campos financeiros
    valor_total_itens: Optional[str] = ""
    valor_total: Optional[str] = ""
    # Compatibilidade legada
    valor: Optional[str] = ""
    data: Optional[str] = None
    # Lista de produtos (opcional)
    produtos: Optional[List[Produto]] = None
    mensagem_custom: Optional[str] = None


class ArquivoPayload(BaseModel):
    telefone: str
    nome_arquivo: str
    conteudo_base64: str
    mensagem: Optional[str] = None

    @field_validator("conteudo_base64")
    @classmethod
    def check_tamanho(cls, v: str) -> str:
        if len(v) > _MAX_B64_LEN:
            raise ValueError("Arquivo muito grande. Limite: 50 MB.")
        return v


def _montar_lista_produtos(produtos: List[Produto]) -> str:
    linhas = []
    for p in produtos:
        qtd = int(p.quantidade) if p.quantidade == int(p.quantidade) else p.quantidade
        linha = f"• {p.nome} (x{qtd})"
        if p.valor_unitario:
            linha += f" — R$ {p.valor_unitario}"
        linhas.append(linha)
    return "\n".join(linhas)


def _normalizar_telefone(telefone: str) -> str:
    """Garante DDI 55 — ERP envia apenas DDD+número."""
    digits = "".join(c for c in telefone if c.isdigit())
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits


def _aplicar_template(template: str, body: VendaPayload, telefone_normalizado: str) -> str:
    data_str = body.data or datetime.now().strftime("%d/%m/%Y")
    valor_exibir = body.valor_total or body.valor or ""
    produtos_str = _montar_lista_produtos(body.produtos) if body.produtos else ""

    return (
        template
        .replace("{nome}", body.nome)
        .replace("{telefone}", telefone_normalizado)
        .replace("{valor}", valor_exibir)
        .replace("{valor_total}", body.valor_total or body.valor or "")
        .replace("{valor_total_itens}", body.valor_total_itens or "")
        .replace("{data}", data_str)
        .replace("{produtos}", produtos_str)
    )


@router.post("/venda")
async def receber_venda(
    body: VendaPayload,
    request: Request,
    x_token: Optional[str] = Header(default=None),
    db=Depends(get_db),
):
    empresa_id = await _verify_token(x_token, db, request)
    telefone = _normalizar_telefone(body.telefone)

    async with db.execute(
        "SELECT value FROM config WHERE key='mensagem_padrao' AND empresa_id=?", (empresa_id,)
    ) as cur:
        row = await cur.fetchone()

    template = row["value"] if row else "Olá {nome}, obrigado pela sua compra de {valor_total} em {data}!"
    mensagem = body.mensagem_custom or _aplicar_template(template, body, telefone)

    # Enfileira para disparo assíncrono — API retorna imediatamente
    await db.execute(
        "INSERT INTO mensagens (empresa_id, destinatario, nome_destinatario, mensagem, tipo, status) VALUES (?, ?, ?, ?, 'text', 'queued')",
        (empresa_id, telefone, body.nome or "", mensagem),
    )
    await db.commit()
    _record_call(empresa_id, request, "/api/erp/venda", True)
    logger.info("[erp] venda enfileirada → empresa=%s fone=%s nome=%s ip=%s",
                empresa_id, telefone, body.nome or "?", request.client.host if request.client else "?")
    return {"ok": True, "queued": True}


@router.post("/arquivo")
async def receber_arquivo(
    body: ArquivoPayload,
    request: Request,
    x_token: Optional[str] = Header(default=None),
    db=Depends(get_db),
):
    empresa_id = await _verify_token(x_token, db, request)
    telefone = _normalizar_telefone(body.telefone)

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(body.nome_arquivo)[1] or ".pdf"
    nome_salvo = f"{uuid.uuid4().hex}{ext}"
    caminho = os.path.join(UPLOAD_DIR, nome_salvo)

    try:
        conteudo = base64.b64decode(body.conteudo_base64)
    except Exception as exc:
        logger.error(
            "[erp] Erro ao decodificar base64: empresa=%s arquivo=%s erro=%s",
            empresa_id, body.nome_arquivo, exc,
        )
        raise HTTPException(status_code=400, detail="Conteúdo base64 inválido.")

    try:
        with open(caminho, "wb") as f:
            f.write(conteudo)
    except Exception as exc:
        logger.error(
            "[erp] Erro ao gravar arquivo em disco: empresa=%s caminho=%s erro=%s",
            empresa_id, caminho, exc,
        )
        raise HTTPException(status_code=500, detail="Erro ao salvar arquivo no servidor.")

    # Enfileira para disparo assíncrono — API retorna imediatamente
    await db.execute(
        """INSERT INTO arquivos
               (empresa_id, nome_original, nome_arquivo, tamanho, destinatario, nome_destinatario, status, caption)
           VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)""",
        (empresa_id, body.nome_arquivo, nome_salvo, len(conteudo), telefone, "", body.mensagem),
    )
    await db.commit()
    _record_call(empresa_id, request, "/api/erp/arquivo", True)
    logger.info("[erp] arquivo enfileirado → empresa=%s fone=%s arquivo=%s tamanho=%dKB ip=%s",
                empresa_id, telefone, body.nome_arquivo, len(conteudo) // 1024,
                request.client.host if request.client else "?")
    return {"ok": True, "queued": True}


@router.get("/status")
async def erp_status(user: dict = Depends(get_current_user)):
    empresa_id = user["empresa_id"]
    return _last_call.get(empresa_id, {
        "timestamp": None, "ip": None, "endpoint": None, "status": None, "total_calls": 0,
    })


@router.get("/config")
async def get_erp_config(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT value FROM config WHERE key='erp_token' AND empresa_id=?", (empresa_id,)
    ) as cur:
        row = await cur.fetchone()
    return {"token": row["value"] if row else ""}


@router.post("/config")
async def set_erp_config(
    body: dict,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    token = body.get("token", "")
    await db.execute(
        """INSERT INTO config (empresa_id, key, value) VALUES (?, 'erp_token', ?)
           ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value""",
        (empresa_id, token),
    )
    await db.commit()
    return {"ok": True}


@router.post("/gerar-token")
async def gerar_token(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    novo_token = secrets.token_urlsafe(32)
    await db.execute(
        """INSERT INTO config (empresa_id, key, value) VALUES (?, 'erp_token', ?)
           ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value""",
        (empresa_id, novo_token),
    )
    await db.commit()
    return {"ok": True, "token": novo_token}
