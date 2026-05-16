import base64
import logging
import os
import secrets
import uuid
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from ..core.database import get_db
from ..core.security import get_current_user, verify_erp_token, hash_erp_token
from ..core.config import settings
from ..repositories import MensagemRepository, AvaliacaoRepository
from ..repositories.config_repository import ConfigRepository


async def _encurtar_url(url: str) -> str:
    """Encurta via TinyURL. Retorna o link original se falhar."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"https://tinyurl.com/api-create.php?url={quote(url, safe='')}"
            )
            if r.status_code == 200 and r.text.startswith("http"):
                return r.text.strip()
    except Exception as exc:
        logger.debug("[erp] TinyURL falhou (%s) — usando link original", exc)
    return url

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
    # Busca todos os tokens ERP e compara — verify_erp_token suporta hash e plaintext
    rows = await ConfigRepository(db).get_all_erp_tokens()
    for row in rows:
        if verify_erp_token(x_token, row["value"]):
            # M8: migração transparente — se ainda era plaintext, salva hash no banco
            if len(row["value"]) != 64:
                try:
                    await db.execute(
                        """UPDATE config SET value = ? WHERE key='erp_token' AND empresa_id = ?""",
                        (hash_erp_token(x_token), row["empresa_id"]),
                    )
                    await db.commit()
                    logger.info("[erp] Token ERP migrado para SHA-256 (empresa %s)", row["empresa_id"])
                except Exception:
                    pass
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
    vendedor: Optional[str] = ""
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


# ── Helpers de negócio (extraídos para clareza) ───────────────────────────────

async def _queue_mensagem(db, empresa_id: int, telefone: str, nome: str, mensagem: str) -> None:
    """Insere uma mensagem de texto na fila de disparo."""
    await db.execute(
        "INSERT INTO mensagens (empresa_id, destinatario, nome_destinatario, mensagem, tipo, status) "
        "VALUES (?, ?, ?, ?, 'text', 'queued')",
        (empresa_id, telefone, nome, mensagem),
    )


async def _upsert_contato(db, empresa_id: int, phone: str, nome: str) -> None:
    """Cria ou atualiza contato na tabela de disparo em massa."""
    await db.execute(
        """INSERT INTO contatos (empresa_id, phone, nome, origem)
           VALUES (?, ?, ?, 'erp')
           ON CONFLICT (empresa_id, phone) DO UPDATE
           SET nome = CASE WHEN EXCLUDED.nome != '' THEN EXCLUDED.nome ELSE contatos.nome END,
               origem = 'erp'""",
        (empresa_id, phone, nome),
    )


async def _gerar_sufixo_avaliacao(db, empresa_id: int, telefone: str, nome: str,
                                   vendedor: str, valor: str) -> str | None:
    """
    Se avaliação estiver ativa para a empresa, gera token, insere registro e
    retorna o sufixo de texto a ser anexado à mensagem (com link encurtado).
    Retorna None se avaliação desabilitada ou em caso de erro.
    """
    async with db.execute(
        "SELECT value FROM config WHERE key='avaliacao_ativa' AND empresa_id=?", (empresa_id,)
    ) as cur:
        cfg_aval = await cur.fetchone()
    if not cfg_aval or cfg_aval["value"] != "1":
        return None

    token_aval = secrets.token_urlsafe(16)
    async with db.execute(
        "SELECT value FROM config WHERE key='avaliacao_url_base' AND empresa_id=?", (empresa_id,)
    ) as cur2:
        cfg_url = await cur2.fetchone()
    url_base = cfg_url["value"] if cfg_url else settings.public_url
    link_aval = await _encurtar_url(f"{url_base}/avaliacao?t={token_aval}")

    await db.execute(
        """INSERT INTO avaliacoes (empresa_id, token, phone, nome_cliente, vendedor, valor)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (empresa_id, token_aval, telefone, nome, vendedor, valor),
    )
    return f"\n\n⭐ Avalie nosso atendimento:\n{link_aval}"


@router.post("/venda")
async def receber_venda(
    body: VendaPayload,
    request: Request,
    x_token: Optional[str] = Header(default=None),
    db=Depends(get_db),
):
    empresa_id = await _verify_token(x_token, db, request)
    telefone = _normalizar_telefone(body.telefone)
    nome = body.nome or ""

    # Monta mensagem a partir do template (ou mensagem customizada do ERP)
    cfg_repo = ConfigRepository(db)
    template = await cfg_repo.get_mensagem_padrao(empresa_id)
    mensagem = body.mensagem_custom or _aplicar_template(template, body, telefone)

    # Anexa link de avaliação à mensagem (se recurso habilitado)
    try:
        sufixo = await _gerar_sufixo_avaliacao(
            db, empresa_id, telefone, nome,
            body.vendedor or "", body.valor_total or body.valor or "",
        )
        if sufixo:
            mensagem += sufixo
    except Exception as exc:
        logger.debug("[erp] Erro ao gerar link de avaliação: %s", exc)

    await MensagemRepository(db).enqueue(empresa_id, telefone, nome, mensagem)
    try:
        from ..repositories import ContatoRepository
        await ContatoRepository(db).upsert(empresa_id, telefone, nome, "erp")
    except Exception as exc:
        logger.debug("[erp] Upsert contato falhou (ignorado): %s", exc)

    await db.commit()
    _record_call(empresa_id, request, "/api/erp/venda", True)
    logger.info("[erp] venda enfileirada → empresa=%s fone=%s nome=%s ip=%s",
                empresa_id, telefone, nome or "?", request.client.host if request.client else "?")
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
    try:
        await _upsert_contato(db, empresa_id, telefone, "")
    except Exception as exc:
        logger.debug("[erp] Upsert contato (arquivo) falhou (ignorado): %s", exc)
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
    """
    M8: retorna se o token existe mas não o valor (hash não é reversível).
    O token bruto só é exibido no momento da geração (/gerar-token).
    """
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT value FROM config WHERE key='erp_token' AND empresa_id=?", (empresa_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return {"token": "", "configurado": False}
    # Retorna últimos 8 chars se plaintext legado, ou prefixo do hash para indicar existência
    stored = row["value"]
    preview = f"••••••••{stored[-4:]}" if stored else ""
    return {"token": preview, "configurado": bool(stored)}


@router.post("/config")
async def set_erp_config(
    body: dict,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """M8: salva hash SHA-256 do token informado (nunca o token em plaintext)."""
    empresa_id = user["empresa_id"]
    token = body.get("token", "").strip()
    if not token:
        return {"ok": False, "detail": "Token não pode ser vazio"}
    hashed = hash_erp_token(token)
    await db.execute(
        """INSERT INTO config (empresa_id, key, value) VALUES (?, 'erp_token', ?)
           ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value""",
        (empresa_id, hashed),
    )
    await db.commit()
    return {"ok": True}


@router.post("/gerar-token")
async def gerar_token(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    M8: gera novo token seguro, salva hash no banco.
    O token bruto é retornado APENAS nesta resposta — não há como recuperá-lo depois.
    """
    empresa_id = user["empresa_id"]
    novo_token = secrets.token_urlsafe(32)
    hashed = hash_erp_token(novo_token)
    await db.execute(
        """INSERT INTO config (empresa_id, key, value) VALUES (?, 'erp_token', ?)
           ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value""",
        (empresa_id, hashed),
    )
    await db.commit()
    logger.info("[erp] Novo token ERP gerado para empresa %s (armazenado como hash)", empresa_id)
    return {"ok": True, "token": novo_token}  # token bruto: visível UMA VEZ, copie agora
