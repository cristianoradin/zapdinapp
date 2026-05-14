"""
log_collector.py — Coletor de logs em memória para envio ao Monitor
====================================================================
Funciona como um Handler do Python logging que intercepta todos os registros
gerados pelo app e os armazena em um buffer circular (deque).

A cada heartbeat (30s), o reporter.py chama flush() para obter os logs acumulados
e os inclui no payload enviado ao Monitor. O Monitor armazena por cliente e exibe
na tela de Logs do painel administrativo.

Capacidade máxima: 500 entradas (proteção contra pico de logs em memória).
Se o buffer encher, os mais antigos são descartados automaticamente (deque).

Categorias mapeadas a partir do nome do logger:
  erp, whatsapp, fila, campanha, auth, update, heartbeat, ativacao, sistema
"""
import logging
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import List

# Mapa de prefixo do nome do logger → categoria amigável exibida no Monitor
_CAT_MAP = {
    "app.routers.erp":                   "erp",
    "app.routers.whatsapp":              "whatsapp",
    "app.routers.arquivos":              "whatsapp",
    "app.routers.campanha":              "campanha",
    "app.routers.auth":                  "auth",
    "app.routers.activation":            "ativacao",
    "app.routers.config_router":         "config",
    "app.routers.monitor_sync":          "sincronizacao",
    "app.routers.stats":                 "sistema",
    "app.services.evolution_service":    "whatsapp",
    "app.services.whatsapp_service":     "whatsapp",
    "app.services.queue_worker":         "fila",
    "app.services.reporter":             "heartbeat",
    "app.services.updater":              "update",
    "app.services.telegram_service":     "telegram",
    "app.core.activation":               "ativacao",
    "zapdin.worker":                     "fila",
}

# Níveis que NÃO enviamos ao Monitor (muito verbosos para armazenar)
_SKIP_LEVELS = {"DEBUG"}

# Mensagens que fazem pouco sentido no contexto do Monitor
_SKIP_PREFIXES = (
    "GET /",
    "POST /",
    "PUT /",
    "DELETE /",
)

_MAX_BUFFER = 500


def _categoria(name: str) -> str:
    """Mapeia nome do logger para categoria amigável."""
    for prefix, cat in _CAT_MAP.items():
        if name.startswith(prefix):
            return cat
    return "sistema"


class _LogCollectorHandler(logging.Handler):
    """
    Handler customizado do logging que armazena registros no buffer circular.
    Thread-safe (usa Lock interno).
    """
    def __init__(self):
        super().__init__()
        self._buffer: deque = deque(maxlen=_MAX_BUFFER)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        # Filtra níveis verbosos
        if record.levelname in _SKIP_LEVELS:
            return
        # Filtra logs de acesso HTTP do uvicorn (muito ruidosos)
        msg = self.format(record)
        if any(msg.lstrip().startswith(p) for p in _SKIP_PREFIXES):
            return

        entry = {
            "ts":    datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "nivel": record.levelname,     # INFO | WARNING | ERROR | CRITICAL
            "cat":   _categoria(record.name),
            "msg":   record.getMessage(),
        }
        with self._lock:
            self._buffer.append(entry)

    def flush_entries(self) -> List[dict]:
        """
        Retorna todos os logs acumulados desde o último flush e limpa o buffer.
        Chamado pelo reporter.py a cada heartbeat.
        """
        with self._lock:
            entries = list(self._buffer)
            self._buffer.clear()
        return entries


# ── Instância global ──────────────────────────────────────────────────────────
_handler = _LogCollectorHandler()
_handler.setLevel(logging.INFO)
_installed = False


def install() -> None:
    """
    Instala o handler no logger raiz do Python.
    Deve ser chamado UMA VEZ no startup do app (main.py).
    Após isso, qualquer logger.info/warning/error em qualquer módulo
    será automaticamente coletado.
    """
    global _installed
    if _installed:
        return
    root = logging.getLogger()
    root.addHandler(_handler)
    _installed = True


def flush() -> List[dict]:
    """
    Retorna e limpa os logs acumulados.
    Chamado pelo reporter.py antes de cada heartbeat.
    """
    return _handler.flush_entries()
