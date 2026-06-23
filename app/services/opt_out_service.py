"""
app/services/opt_out_service.py — Opt-out automático (PARE/SAIR).

Quando um contato responde PARE/SAIR/CANCELAR etc., marca opt_out=TRUE e ele
para de receber campanhas/mensagens. Reduz denúncia = principal causa de ban.
Palavra de volta (RECEBER/VOLTAR) reativa.

Casa o inbound (evolution_service._processar_inbound) ANTES do chatbot:
se for comando de opt-out/in, trata + confirma e NÃO passa pro chatbot.
"""
import logging
import unicodedata

logger = logging.getLogger(__name__)

# Frases de saída (cliente quer parar de receber)
_OUT = {
    "pare", "parar", "para", "sair", "cancelar", "cancela", "stop",
    "remover", "remova", "descadastrar", "descadastre", "nao quero",
    "nao quero receber", "nao quero mais", "nao quero mais receber",
    "cancelar inscricao", "sair da lista", "me tira", "me remove",
}
# Frases de volta (cliente quer voltar a receber)
_IN = {
    "receber", "voltar", "quero receber", "voltar a receber",
    "cadastrar", "me cadastra", "reativar",
}

_CONFIRM_OUT = (
    "✅ Pronto! Você não vai mais receber nossas mensagens.\n"
    "Se mudar de ideia, responda *RECEBER* a qualquer momento."
)
_CONFIRM_IN = (
    "✅ Tudo certo! Você voltou a receber nossas mensagens.\n"
    "Para sair de novo, responda *PARE*."
)


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    # remove pontuação simples nas pontas
    return s.strip(" .!?\t\n\r-_")


def classificar(texto: str):
    """Retorna 'out', 'in' ou None. Só dispara em mensagem CURTA (evita falso
    positivo tipo 'não pare de mandar')."""
    n = _norm(texto)
    if not n or len(n) > 30:
        return None
    if n in _OUT:
        return "out"
    if n in _IN:
        return "in"
    return None


async def handle_inbound(empresa_id: int, phone_raw: str, texto: str) -> bool:
    """Se `texto` for comando opt-out/in: marca no banco, confirma e retorna True.
    Caso contrário retorna False (segue fluxo normal/chatbot)."""
    cls = classificar(texto)
    if not cls:
        return False
    try:
        from ..core.phone import normalize_phone
        phone = normalize_phone(phone_raw) or "".join(c for c in (phone_raw or "") if c.isdigit())
        if phone.startswith("55") and len(phone) > 11:
            phone = phone[2:]
        from ..core.database import get_db_direct
        from ..repositories.contato_repository import ContatoRepository
        async with get_db_direct() as db:
            repo = ContatoRepository(db)
            await repo.marcar_opt_out(empresa_id, phone, opted=(cls == "out"))
            await db.commit()
        # Confirmação (vai pela fila, prioritária)
        from .alerta_service import enviar_para_numeros
        await enviar_para_numeros(empresa_id, [phone],
                                  _CONFIRM_OUT if cls == "out" else _CONFIRM_IN,
                                  tipo="sistema")
        logger.info("[opt-out] empresa=%s phone=%s -> %s", empresa_id, phone, cls)
        return True
    except Exception as exc:
        logger.warning("[opt-out] erro empresa=%s: %s", empresa_id, exc)
        return False
