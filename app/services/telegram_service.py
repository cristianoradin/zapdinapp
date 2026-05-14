"""
telegram_service.py — Notificações e relatórios via Telegram Bot
================================================================
Envia alertas em tempo real e relatório periódico a cada 3 horas.

Notificações disponíveis:
  • Sessão WhatsApp desconectada (logout real)
  • Sessão WhatsApp reconectada automaticamente
  • Falha no envio de mensagem ou arquivo
  • Token ERP inválido recebido (possível tentativa de acesso indevido)
  • Fila bloqueada (mensagens acumulando sem sessão conectada)
  • Update aplicado com sucesso
  • Relatório de status a cada 3 horas

Todas as mensagens incluem o nome do cliente conforme licença no Monitor.
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

_task: Optional[asyncio.Task] = None

# Config carregada do banco no startup e atualizada via API
_bot_token: str = ""
_chat_id: str = ""

# Contadores para o relatório de 3h
_msgs_sent:   int = 0
_files_sent:  int = 0
_send_errors: int = 0

# Throttle para "fila bloqueada" — no máximo 1 alerta a cada 30min
_last_queue_blocked_alert: float = 0.0
_QUEUE_BLOCKED_COOLDOWN = 30 * 60   # 30 minutos


# ─────────────────────────────────────────────────────────────────────────────
#  Configuração
# ─────────────────────────────────────────────────────────────────────────────

def configure(bot_token: str, chat_id: str) -> None:
    global _bot_token, _chat_id
    _bot_token = bot_token.strip()
    _chat_id   = chat_id.strip()


def is_configured() -> bool:
    return bool(_bot_token and _chat_id)


def _client_name() -> str:
    """
    Retorna o nome do cliente conforme licença no Monitor.
    Usa settings.client_name (preenchido no .env após ativação).
    """
    return settings.client_name or "ZapDin"


# ─────────────────────────────────────────────────────────────────────────────
#  Contadores (chamados pelo evolution_service e queue_worker)
# ─────────────────────────────────────────────────────────────────────────────

def record_sent(tipo: str = "text") -> None:
    """Registra um envio bem-sucedido para o relatório de 3h."""
    global _msgs_sent, _files_sent
    if tipo == "file":
        _files_sent += 1
    else:
        _msgs_sent += 1


def record_error() -> None:
    """Registra um erro de envio para o relatório de 3h."""
    global _send_errors
    _send_errors += 1


# ─────────────────────────────────────────────────────────────────────────────
#  Envio base
# ─────────────────────────────────────────────────────────────────────────────

async def send(text: str) -> bool:
    """Envia uma mensagem de texto formatada (HTML) via Telegram Bot API."""
    if not is_configured():
        return False
    url     = f"https://api.telegram.org/bot{_bot_token}/sendMessage"
    payload = {"chat_id": _chat_id, "text": text, "parse_mode": "HTML"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            if r.status_code != 200:
                logger.warning("[telegram] Respondeu %s: %s", r.status_code, r.text[:200])
                return False
        return True
    except Exception as exc:
        logger.error("[telegram] Falha ao enviar: %s", exc)
        return False


def _now() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def _header() -> str:
    """Cabeçalho padrão com nome do cliente."""
    return f"🏢 <b>{_client_name()}</b>"


# ─────────────────────────────────────────────────────────────────────────────
#  Notificações
# ─────────────────────────────────────────────────────────────────────────────

async def notify_disconnected(sessao_nome: str) -> None:
    """WhatsApp desconectado por logout real (usuário removeu o dispositivo)."""
    record_error()
    await send(
        f"🔴 <b>ZapDin — Sessão Desconectada</b>\n"
        f"{_header()}\n\n"
        f"📱 Sessão: <b>{sessao_nome}</b>\n"
        f"⚠️ O dispositivo foi removido pelo usuário.\n"
        f"Acesse o painel e escaneie o QR Code novamente.\n"
        f"🕐 {_now()}"
    )


async def notify_reconnected(sessao_nome: str) -> None:
    """WhatsApp reconectou automaticamente após queda de rede."""
    await send(
        f"✅ <b>ZapDin — Sessão Reconectada</b>\n"
        f"{_header()}\n\n"
        f"📱 Sessão: <b>{sessao_nome}</b>\n"
        f"🔄 Reconectado automaticamente após queda de rede.\n"
        f"🕐 {_now()}"
    )


async def notify_send_failure(sessao_nome: str, destinatario: str, erro: str) -> None:
    """Falha ao enviar mensagem ou arquivo."""
    record_error()
    await send(
        f"⚠️ <b>ZapDin — Falha no Envio</b>\n"
        f"{_header()}\n\n"
        f"📱 Sessão: <b>{sessao_nome}</b>\n"
        f"📞 Destinatário: <code>{destinatario}</code>\n"
        f"❌ Erro: {erro}\n"
        f"🕐 {_now()}"
    )


async def notify_erp_invalid_token(ip: str) -> None:
    """Token ERP inválido recebido — possível tentativa de acesso indevido."""
    await send(
        f"🚨 <b>ZapDin — Tentativa de Acesso Inválido</b>\n"
        f"{_header()}\n\n"
        f"📡 ERP enviou token inválido\n"
        f"🌐 IP de origem: <code>{ip}</code>\n"
        f"🕐 {_now()}"
    )


async def notify_queue_blocked(pending_count: int) -> None:
    """
    Mensagens acumuladas na fila sem sessão WhatsApp disponível.
    Throttle: no máximo 1 alerta a cada 30 minutos.
    """
    global _last_queue_blocked_alert
    now = time.time()
    if now - _last_queue_blocked_alert < _QUEUE_BLOCKED_COOLDOWN:
        return
    _last_queue_blocked_alert = now
    await send(
        f"🚫 <b>ZapDin — Fila Bloqueada</b>\n"
        f"{_header()}\n\n"
        f"📨 {pending_count} mensagem(ns) aguardando envio.\n"
        f"❌ Nenhuma sessão WhatsApp conectada.\n"
        f"Acesse o painel para reconectar.\n"
        f"🕐 {_now()}"
    )


async def notify_update_applied(versao: str) -> None:
    """Auto-update aplicado com sucesso."""
    await send(
        f"🔄 <b>ZapDin — Atualização Aplicada</b>\n"
        f"{_header()}\n\n"
        f"✅ Versão <b>{versao}</b> instalada com sucesso.\n"
        f"🕐 {_now()}"
    )


async def notify_api_error(detail: str) -> None:
    """Erro genérico de API."""
    await send(
        f"🚨 <b>ZapDin — Erro na API</b>\n"
        f"{_header()}\n\n"
        f"{detail}\n"
        f"🕐 {_now()}"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Relatório periódico (a cada 3 horas)
# ─────────────────────────────────────────────────────────────────────────────

async def _send_status_report() -> None:
    """
    Envia relatório de status com:
      - Lista de sessões WhatsApp e seus status
      - Contagem de envios nas últimas 3h
    Usa o backend correto (Evolution ou Playwright) conforme configuração.
    """
    from ..core.config import settings as _settings

    # Seleciona o manager correto conforme backend configurado
    if _settings.use_evolution:
        from .evolution_service import evo_manager as wa_manager
    else:
        from .whatsapp_service import wa_manager

    # Coleta todas as sessões de todas as empresas
    sessoes = []
    for key, sess in wa_manager._sessions.items():
        sessoes.append({
            "nome":   sess.nome,
            "status": sess.status,
            "phone":  getattr(sess, "phone", None),
        })

    total       = len(sessoes)
    conectadas  = [s for s in sessoes if s["status"] == "connected"]
    desconect   = [s for s in sessoes if s["status"] not in ("connected", "connecting")]

    linhas = ""
    for s in sessoes:
        if s["status"] == "connected":
            phone_str = f" · <code>{s['phone']}</code>" if s.get("phone") else ""
            linhas += f"  ✅ {s['nome']} — conectado{phone_str}\n"
        elif s["status"] == "connecting":
            linhas += f"  🟡 {s['nome']} — conectando...\n"
        else:
            linhas += f"  🔴 {s['nome']} — desconectado\n"

    texto = (
        f"📊 <b>ZapDin — Relatório de Status</b>\n"
        f"{_header()}\n"
        f"🕐 {_now()}\n\n"
        f"<b>📱 Sessões WhatsApp ({total})</b>\n"
        f"{linhas or '  Nenhuma sessão cadastrada\n'}\n"
        f"<b>📤 Envios nas últimas 3h</b>\n"
        f"  ✉️ Mensagens: {_msgs_sent}\n"
        f"  📎 Arquivos: {_files_sent}\n"
        f"  ❌ Erros: {_send_errors}\n\n"
    )

    if not conectadas:
        texto += "⚠️ <b>Nenhuma sessão conectada!</b> O envio de mensagens está indisponível."
    else:
        texto += f"✅ {len(conectadas)} sessão(ões) ativa(s) e pronta(s) para envio."

    await send(texto)
    _reset_counters()


def _reset_counters() -> None:
    global _msgs_sent, _files_sent, _send_errors
    _msgs_sent   = 0
    _files_sent  = 0
    _send_errors = 0


# ─────────────────────────────────────────────────────────────────────────────
#  Loop periódico
# ─────────────────────────────────────────────────────────────────────────────

async def _loop() -> None:
    INTERVAL = 3 * 60 * 60  # 3 horas
    while True:
        await asyncio.sleep(INTERVAL)
        if is_configured():
            await _send_status_report()


def start() -> None:
    global _task
    _task = asyncio.create_task(_loop())


def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        _task = None
