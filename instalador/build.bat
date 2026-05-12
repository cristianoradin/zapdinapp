@echo off
chcp 65001 >nul
title ZapDin — Compilar Setup

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║     ZapDin App — Compilar Instalador     ║
echo  ╚══════════════════════════════════════════╝
echo.

:: Localiza o Inno Setup
set ISCC=""
IF EXIST "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
IF EXIST "C:\Program Files\Inno Setup 6\ISCC.exe"       set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

IF %ISCC%=="" (
    echo  [ERRO] Inno Setup 6 nao encontrado.
    echo.
    echo  Baixe em: https://jrsoftware.org/isdl.php
    echo.
    pause
    exit /b 1
)

:: Gera icone padrao se nao existir
IF NOT EXIST "icon.ico" (
    echo  [INFO] Gerando icone padrao...
    python -c "
from PIL import Image, ImageDraw
img = Image.new('RGB', (64,64), '#3d7f1f')
d = ImageDraw.Draw(img)
d.text((10,15), 'ZD', fill='white')
img.save('icon.ico')
" 2>nul || (
        :: Cria um ico minimo se PIL nao estiver disponivel
        echo  [INFO] Usando icone padrao do sistema.
        copy "%SystemRoot%\system32\shell32.dll" icon.ico >nul 2>&1
    )
)

echo  [INFO] Compilando ZapDin-Setup.exe...
%ISCC% setup.iss

IF ERRORLEVEL 1 (
    echo.
    echo  [ERRO] Falha na compilacao. Verifique os erros acima.
    pause
    exit /b 1
)

echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║   ZapDin-Setup.exe gerado com sucesso!       ║
echo  ╚══════════════════════════════════════════════╝
echo.
echo  Arquivo: %~dp0ZapDin-Setup.exe
echo.
pause
