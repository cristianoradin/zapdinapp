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
"""
import multiprocessing
import sys
import os

# DEVE ser a primeira chamada no script — habilita o mecanismo de spawn do
# PyInstaller para subprocessos (multiprocessing no Windows usa spawn).
multiprocessing.freeze_support()

# --- garante que só o processo principal (pai) sobe o uvicorn ----------------
# Quando o PyInstaller spawna um worker de multiprocessing, ele chama este mesmo
# run.py com __name__ == '__main__', mas o nome do processo NÃO é 'MainProcess'.
if multiprocessing.current_process().name != 'MainProcess':
    # Este é um worker process — não deve iniciar o servidor.
    # freeze_support() já tratou o que era necessário; podemos sair.
    sys.exit(0)

# --- configuração do ambiente frozen -----------------------------------------
if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
    os.chdir(base_dir)
    # Adiciona o diretório do exe ao sys.path para que `from app.main import app`
    # funcione quando importado como pacote (não como módulo top-level).
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    # Aponta Playwright para os browsers embutidos no pacote
    os.environ.setdefault(
        'PLAYWRIGHT_BROWSERS_PATH',
        os.path.join(base_dir, 'ms-playwright'),
    )

import uvicorn
from app.main import app  # importa via pacote app — preserva imports relativos

def main():
    port = int(os.environ.get("PORT", "4000"))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        # workers=1 é o padrão quando passamos o objeto `app` diretamente.
        # NÃO usar workers > 1 aqui — cada worker tentaria abrir a mesma porta.
    )

if __name__ == '__main__':
    main()
