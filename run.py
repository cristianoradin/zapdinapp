"""
Ponto de entrada para PyInstaller.
Inicia o ZapDin App via uvicorn programaticamente.

IMPORTANTE — comportamento no frozen exe:
  - PyInstaller define __name__ == '__main__' em TODOS os módulos, inclusive nos
    worker-processes que ele spawna via multiprocessing.  Por isso o guard
    `if __name__ == '__main__'` sozinho NÃO protege contra múltiplas instâncias.
  - A solução correta é chamar freeze_support() ANTES de qualquer import pesado e
    depois testar `sys.frozen` + verificar se somos o processo pai (não um worker).
  - multiprocessing.current_process().name == 'MainProcess' distingue o processo
    pai dos workers spawned pelo Pool/Process.

SERVICE MODE (console=False):
  - Quando compilado sem console (production), nenhuma janela preta aparece.
  - Logs vão para zapdin.log no mesmo diretório do executável.
  - Guard de instância única: se a porta já estiver ocupada, loga e sai.
"""
import multiprocessing
import sys
import os
import socket
import logging

# DEVE ser a primeira chamada no script — habilita o mecanismo de spawn do
# PyInstaller para subprocessos (multiprocessing no Windows usa spawn).
multiprocessing.freeze_support()

# --- garante que só o processo principal (pai) sobe o uvicorn ----------------
if multiprocessing.current_process().name != 'MainProcess':
    sys.exit(0)

# --- configuração do ambiente frozen -----------------------------------------
if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
    os.chdir(base_dir)
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    os.environ.setdefault(
        'PLAYWRIGHT_BROWSERS_PATH',
        os.path.join(base_dir, 'ms-playwright'),
    )
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

# --- logging para arquivo (sempre) + console (quando disponível) -------------
log_path = os.path.join(base_dir, 'zapdin.log')

handlers = [logging.FileHandler(log_path, encoding='utf-8')]
# Adiciona console apenas se houver um terminal real disponível
try:
    if sys.stdout and sys.stdout.fileno() >= 0:
        handlers.append(logging.StreamHandler(sys.stdout))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    handlers=handlers,
    force=True,
)

logger = logging.getLogger('zapdin')

# --- guard de instância única ------------------------------------------------
def _porta_disponivel(port: int) -> bool:
    """Retorna True se ninguém está ouvindo na porta."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


import uvicorn
from app.main import app  # importa via pacote app — preserva imports relativos


def main():
    port = int(os.environ.get("PORT", "4000"))

    if not _porta_disponivel(port):
        logger.warning(
            "ZapDin já está rodando na porta %d. Esta instância será encerrada.", port
        )
        sys.exit(0)

    logger.info("=" * 60)
    logger.info("ZapDin App iniciando na porta %d ...", port)
    logger.info("Base dir: %s", base_dir)
    logger.info("=" * 60)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )


if __name__ == '__main__':
    main()
