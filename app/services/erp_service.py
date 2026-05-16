"""
app/services/erp_service.py — Casos de uso da integração ERP.

Contém a lógica de negócio pura do fluxo ERP → WhatsApp.
O router erp.py apenas chama estes métodos e retorna a resposta HTTP.
"""
from __future__ import annotations
import logging
import secrets
from datetime import datetime

from ..repositories import MensagemRepository, AvaliacaoRepository
from ..repositories.config_repository import ConfigRepository
from ..repositories.contato_repository import ContatoRepository

logger = logging.getLogger(__name__)


def normalizar_telefone(telefone: str) -> str:
    """Garante DDI 55 — ERP envia apenas DDD+número."""
    digits = "".join(c for c in telefone if c.isdigit())
    return digits if digits.startswith("55") else "55" + digits


def aplicar_template(template: str, nome: str, telefone: str, valor_total: str,
                     valor: str, valor_total_itens: str, data: str, produtos_str: str) -> str:
    return (
        template
        .replace("{nome}", nome)
        .replace("{telefone}", telefone)
        .replace("{valor}", valor_total or valor or "")
        .replace("{valor_total}", valor_total or valor or "")
        .replace("{valor_total_itens}", valor_total_itens or "")
        .replace("{data}", data)
        .replace("{produtos}", produtos_str)
    )


def montar_lista_produtos(produtos: list) -> str:
    linhas = []
    for p in produtos:
        qtd = int(p.quantidade) if p.quantidade == int(p.quantidade) else p.quantidade
        linha = f"• {p.nome} (x{qtd})"
        if p.valor_unitario:
            linha += f" — R$ {p.valor_unitario}"
        linhas.append(linha)
    return "\n".join(linhas)


async def processar_venda(db, empresa_id: int, body, public_url: str) -> dict:
    """
    Caso de uso: receber venda do ERP.

    1. Normaliza telefone
    2. Busca template de mensagem
    3. Monta mensagem final
    4. Gera link de avaliação (se habilitado)
    5. Enfileira mensagem
    6. Upsert contato

    Retorna dict com campos para logging.
    """
    telefone = normalizar_telefone(body.telefone)
    nome     = body.nome or ""

    cfg_repo  = ConfigRepository(db)
    msg_repo  = MensagemRepository(db)
    aval_repo = AvaliacaoRepository(db)
    cont_repo = ContatoRepository(db)

    # Monta mensagem
    template = await cfg_repo.get_mensagem_padrao(empresa_id)
    data_str = body.data or datetime.now().strftime("%d/%m/%Y")
    produtos_str = montar_lista_produtos(body.produtos) if body.produtos else ""

    mensagem = body.mensagem_custom or aplicar_template(
        template, nome, telefone,
        body.valor_total or "", body.valor or "",
        body.valor_total_itens or "", data_str, produtos_str,
    )

    # Avaliação (best-effort)
    try:
        if await cfg_repo.is_avaliacao_ativa(empresa_id):
            token_aval = secrets.token_urlsafe(16)
            url_base   = await cfg_repo.get_avaliacao_url_base(empresa_id, public_url)

            from ..routers.erp import _encurtar_url
            link = await _encurtar_url(f"{url_base}/avaliacao?t={token_aval}")
            mensagem += f"\n\n⭐ Avalie nosso atendimento:\n{link}"

            await aval_repo.create(
                empresa_id, token_aval, telefone, nome,
                body.vendedor or "", body.valor_total or body.valor or "",
            )
    except Exception as exc:
        logger.debug("[erp_service] Erro ao gerar avaliação: %s", exc)

    # Enfileira mensagem
    await msg_repo.enqueue(empresa_id, telefone, nome, mensagem)

    # Upsert contato (best-effort)
    try:
        await cont_repo.upsert(empresa_id, telefone, nome, "erp")
    except Exception as exc:
        logger.debug("[erp_service] Upsert contato falhou: %s", exc)

    return {"telefone": telefone, "nome": nome}


async def processar_arquivo(db, empresa_id: int, body) -> dict:
    """
    Caso de uso: receber arquivo do ERP para envio.
    Retorna dict com campos para logging.
    """
    import base64, os, uuid
    from ..repositories.contato_repository import ContatoRepository

    telefone   = normalizar_telefone(body.telefone)
    UPLOAD_DIR = "data/arquivos"
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    ext        = os.path.splitext(body.nome_arquivo)[1] or ".pdf"
    nome_salvo = f"{uuid.uuid4().hex}{ext}"
    caminho    = os.path.join(UPLOAD_DIR, nome_salvo)

    try:
        conteudo = base64.b64decode(body.conteudo_base64)
    except Exception as exc:
        raise ValueError(f"Conteúdo base64 inválido: {exc}") from exc

    with open(caminho, "wb") as f:
        f.write(conteudo)

    await db.execute(
        "INSERT INTO arquivos "
        "(empresa_id, nome_original, nome_arquivo, tamanho, destinatario, nome_destinatario, status, caption) "
        "VALUES (?,?,?,?,?,?,'queued',?)",
        (empresa_id, body.nome_arquivo, nome_salvo, len(conteudo), telefone, "", body.mensagem),
    )

    try:
        await ContatoRepository(db).upsert(empresa_id, telefone, "", "erp")
    except Exception:
        pass

    return {"telefone": telefone, "nome_arquivo": body.nome_arquivo, "tamanho": len(conteudo)}
