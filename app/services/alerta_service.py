"""
app/services/alerta_service.py — Disparo de alertas WA para os administradores.

Reusa a config `alerta_critico` (por empresa) que guarda:
  - telefones[]  → números que recebem os alertas (avaliação negativa + falha de envio)
  - falha_ativo  → liga/desliga o alerta de FALHA de envio
  - falha_mensagem → template do alerta de falha (vars {numero} {nome} {erro} {data})

O alerta de avaliação negativa continua em avaliacao.py (loop nos telefones).
Aqui mora só o alerta de FALHA DE ENVIO (número inválido / cadastro errado),
disparado pelo queue_worker quando uma mensagem falha por número inválido.
"""
from __future__ import annotations

import json as _json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Throttle anti-spam: por (empresa_id, numero_destino) só 1 alerta a cada N segundos.
_THROTTLE_SECONDS = 6 * 3600  # 6h
_last_alerta: dict[tuple, float] = {}

# Erros que indicam NÚMERO INVÁLIDO / cadastro errado (devem alertar o adm).
# Conservador: só alerta quando o erro claramente aponta o destinatário.
_INVALID_MARKERS = (
    "not on whatsapp", "onwhatsapp", "not exist", "does not exist", "doesn't exist",
    "número inválido", "numero invalido", "invalid number", "invalid jid",
    "not registered", "no account", "no whatsapp", "sem whatsapp",
    "destinatário inválido", "destinatario invalido", "recipient",
)
# Erros de INFRA (conexão/sessão) — NUNCA alertam (senão spam quando WhatsApp cai).
_INFRA_MARKERS = (
    "sem sessão", "sem sessao", "no session", "disconnected", "desconect",
    "timeout", "timed out", "connection", "conexão", "conexao", "agent:",
    "econnrefused", "503", "502", "500", "closed", "fechad", "offline",
)


def is_invalid_number_error(err: Optional[str]) -> bool:
    """True só se o erro indica número inválido/inexistente (cadastro).
    Erros de infra (sessão caída, timeout) retornam False — não devem alertar."""
    if not err:
        return False
    e = err.lower()
    if any(m in e for m in _INFRA_MARKERS):
        return False
    return any(m in e for m in _INVALID_MARKERS)


async def _get_alerta_cfg(empresa_id: int) -> dict:
    from ..core.database import get_db_direct
    try:
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT value FROM config WHERE empresa_id=? AND key='alerta_critico'",
                (empresa_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return {}
        return _json.loads(row["value"])
    except Exception:
        return {}


def destinos_por_tipo(cfg: dict, tipo: str) -> list:
    """Números (só dígitos) que recebem alertas do `tipo` ('avaliacao' ou 'falha').
    Usa `destinos[]` (cada um com flags por número). Cai pro legado se ausente:
    `telefones`/`telefone` + `ativo` (avaliacao) / `falha_ativo` (falha)."""
    vistos, out = set(), []

    def _add(numero):
        d = "".join(c for c in (str(numero) or "") if c.isdigit())
        if d and d not in vistos:
            vistos.add(d)
            out.append(d)

    destinos = cfg.get("destinos")
    if destinos:
        for item in destinos:
            if isinstance(item, dict) and item.get(tipo):
                _add(item.get("numero", ""))
        return out

    # Legado: telefones recebem conforme o toggle global do tipo
    ligado = cfg.get("ativo") if tipo == "avaliacao" else cfg.get("falha_ativo")
    if ligado:
        brutos = list(cfg.get("telefones") or [])
        if cfg.get("telefone"):
            brutos.append(cfg["telefone"])
        for t in brutos:
            _add(t)
    return out


async def enviar_para_numeros(empresa_id: int, telefones: list, mensagem: str) -> None:
    """Envia `mensagem` para cada número (best-effort). Usa qualquer sessão conectada."""
    if not telefones or not mensagem:
        return
    try:
        from .whatsapp_service import wa_manager
    except ImportError:
        try:
            from .evolution_service import evo_manager as wa_manager
        except ImportError:
            logger.warning("[alerta] wa_manager indisponível")
            return

    sessoes = wa_manager.get_status(empresa_id)
    conectadas = [s for s in sessoes if s["status"] == "connected"]
    if not conectadas:
        logger.warning("[alerta] empresa=%s sem sessão conectada — alerta não enviado", empresa_id)
        return
    sessao = conectadas[0]["id"]
    for fone in telefones:
        envio = fone.lstrip("+")
        if envio.startswith("55"):
            envio = envio[2:]
        try:
            ok, err = await wa_manager.send_text(sessao, empresa_id, envio, mensagem)
            if not ok:
                logger.warning("[alerta] falha ao enviar p/ %s: %s", fone, err)
        except Exception as exc:
            logger.warning("[alerta] erro ao enviar p/ %s: %s", fone, exc)


async def disparar_falha_cadastro(empresa_id: int, numero: str, nome: str, erro: str) -> None:
    """Alerta os adms quando uma mensagem falhou por NÚMERO INVÁLIDO.
    Best-effort, com throttle por (empresa, número). Roda em background."""
    try:
        if not is_invalid_number_error(erro):
            return  # falha de infra → não alerta

        # Throttle: 1 alerta por número a cada 6h
        chave = (empresa_id, "".join(c for c in (numero or "") if c.isdigit()))
        agora = time.time()
        ult = _last_alerta.get(chave, 0.0)
        if agora - ult < _THROTTLE_SECONDS:
            return

        cfg = await _get_alerta_cfg(empresa_id)
        destinos = destinos_por_tipo(cfg, "falha")
        if not destinos:
            return

        template = cfg.get("falha_mensagem") or ""
        if not template:
            return

        num_exibir = (numero or "").lstrip("+")
        if num_exibir.startswith("55"):
            num_exibir = num_exibir[2:]
        mensagem = (
            template
            .replace("{numero}", num_exibir or "—")
            .replace("{nome}",   nome or "—")
            .replace("{erro}",   (erro or "—")[:120])
            .replace("{data}",   datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M"))
        )

        _last_alerta[chave] = agora
        await enviar_para_numeros(empresa_id, destinos, mensagem)
        logger.info("[alerta] falha de cadastro alertada — empresa=%s numero=%s", empresa_id, num_exibir)
    except Exception as exc:
        logger.exception("[alerta] erro ao disparar falha de cadastro: %s", exc)
