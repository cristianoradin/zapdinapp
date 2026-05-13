# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — ZapDin App
# Compilar: pyinstaller zapdinapp.spec

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# ── Coleta automática de pacotes complexos ─────────────────────────────────────
datas_all = []
binaries_all = []
hiddenimports_all = []

for pkg in ['uvicorn', 'fastapi', 'starlette', 'pydantic', 'pydantic_settings',
            'socketio', 'engineio', 'asyncpg', 'httpx', 'httpcore',
            'cryptography', 'passlib', 'bcrypt', 'itsdangerous',
            'jose', 'multipart', 'qrcode', 'PIL', 'aiofiles',
            'anyio', 'sniffio', 'h11', 'h2', 'hpack', 'hyperframe']:
    d, b, h = collect_all(pkg)
    datas_all += d
    binaries_all += b
    hiddenimports_all += h

# ── Arquivos estáticos do app (dentro do pacote app/) ─────────────────────────
datas_app = [
    ('app/static',   'app/static'),    # frontend HTML/JS/CSS
    ('app/routers',  'app/routers'),   # módulos Python
    ('app/services', 'app/services'),
    ('app/core',     'app/core'),
    ('app/versao.json', 'app/'),
]

a = Analysis(
    ['run.py'],
    pathex=['.'],
    binaries=binaries_all,
    datas=datas_all + datas_app,
    hiddenimports=hiddenimports_all + [
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.loops.uvloop',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'asyncpg.pgproto.pgproto',
        'asyncpg.protocol',
        'asyncpg.protocol.protocol',
        'passlib.handlers.bcrypt',
        'passlib.handlers.sha2_crypt',
        'pydantic.deprecated.class_validators',
        'pydantic.deprecated.config',
        'pydantic.deprecated.tools',
        'pydantic_core',
        'email_validator',
        'python_multipart',
        'multipart',
        'app.main',
        'app.core',
        'app.core.config',
        'app.core.database',
        'app.core.security',
        'app.core.activation',
        'app.routers',
        'app.services',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'test', 'unittest', 'doctest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ZapDinApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,         # sem janela preta — roda silencioso em background
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ZapDinApp',
)
