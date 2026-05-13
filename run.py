"""
Ponto de entrada para PyInstaller.
Inicia o ZapDin App via uvicorn programaticamente.
"""
import multiprocessing
import sys
import os

# Necessário para PyInstaller no Windows
multiprocessing.freeze_support()

# Garante que o diretório do executável seja o cwd
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

import uvicorn

if __name__ == '__main__':
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "4000")),
        log_level="info",
    )
