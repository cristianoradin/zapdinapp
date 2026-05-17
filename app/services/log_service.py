"""
log_service.py — Serviço centralizado de log do sistema ZapDin.

Uso:
    from app.services.log_service import log_event, SysLogHandler

    # direto
    await log_event(empresa_id=1, nivel='info', modulo='whatsapp',
                    acao='session_connect', mensagem='Sessão WA conectada', detalhe='...')

    # via logging padrão Python (automático via SysLogHandler)
    logger.info("Mensagem")
"""
import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Importação lazy do pool para evitar circular imports
def _get_pool():
    from app.core.database import _pool
    return _pool

async def log_event(
    empresa_id: int | None = None,
    nivel: str = "info",
    modulo: str = "sistema",
    acao: str = "",
    mensagem: str = "",
    detalhe: Any = None,
) -> None:
    """Grava um evento no log do sistema. Fire-and-forget — nunca levanta exceção."""
    try:
        pool = _get_pool()
        if pool is None:
            return
        det = None
        if detalhe is not None:
            det = json.dumps(detalhe, ensure_ascii=False, default=str) if not isinstance(detalhe, str) else detalhe
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO system_logs (empresa_id, nivel, modulo, acao, mensagem, detalhe)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                empresa_id, nivel[:20], modulo[:30], acao[:80], mensagem[:500], det,
            )
    except Exception as e:
        logger.debug("log_event falhou (ignorado): %s", e)


def log_event_sync(empresa_id=None, nivel="info", modulo="sistema", acao="", mensagem="", detalhe=None):
    """Versão síncrona — agenda coroutine no loop atual se possível."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(log_event(empresa_id=empresa_id, nivel=nivel, modulo=modulo,
                                    acao=acao, mensagem=mensagem, detalhe=detalhe))
    except RuntimeError:
        pass  # sem loop rodando — ignorar


class SysLogHandler(logging.Handler):
    """Handler de logging Python que espelha logs críticos para a tabela system_logs."""

    LEVEL_MAP = {
        logging.DEBUG:    "info",
        logging.INFO:     "info",
        logging.WARNING:  "warn",
        logging.ERROR:    "error",
        logging.CRITICAL: "critical",
    }
    # Módulos que mapeamos automaticamente por nome do logger
    MODULE_MAP = {
        "whatsapp": "whatsapp",
        "evolution": "whatsapp",
        "erp": "erp",
        "queue_worker": "worker",
        "campanha": "campanhas",
        "chatbot": "chatbot",
        "dominio": "dominio",
        "auth": "auth",
        "monitor": "monitor",
        "reporter": "monitor",
        "activation": "sistema",
        "uvicorn": "sistema",
        "fastapi": "sistema",
    }

    def emit(self, record: logging.LogRecord):
        if record.levelno < logging.WARNING:
            return  # só warn+ vai para o DB via handler automático
        nivel = self.LEVEL_MAP.get(record.levelno, "info")
        modulo = "sistema"
        for key, val in self.MODULE_MAP.items():
            if key in record.name.lower():
                modulo = val
                break
        msg = self.format(record)[:500]
        log_event_sync(nivel=nivel, modulo=modulo, acao="auto_log", mensagem=msg)
