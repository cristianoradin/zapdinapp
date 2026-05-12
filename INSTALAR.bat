@echo off
chcp 65001 >nul
title ZapDin App — Instalador

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║         ZapDin App — Instalador          ║
echo  ╚══════════════════════════════════════════╝
echo.

:: ── Verifica Python ───────────────────────────────────────────────────────────
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo  [ERRO] Python nao encontrado.
    echo.
    echo  Instale o Python 3.11 ou 3.12 em:
    echo  https://python.org/downloads
    echo.
    echo  IMPORTANTE: Marque "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK] Python %PY_VER% encontrado.

:: ── Verifica Git ──────────────────────────────────────────────────────────────
git --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo.
    echo  [AVISO] Git nao encontrado. Tentando instalar via winget...
    winget install --id Git.Git -e --source winget >nul 2>&1
    git --version >nul 2>&1
    IF ERRORLEVEL 1 (
        echo  [ERRO] Nao foi possivel instalar o Git automaticamente.
        echo  Baixe em: https://git-scm.com/download/win
        pause
        exit /b 1
    )
)
echo  [OK] Git encontrado.

:: ── Pasta de instalacao ───────────────────────────────────────────────────────
set INSTALL_DIR=C:\ZapDinApp
echo.
echo  Pasta de instalacao: %INSTALL_DIR%
IF EXIST "%INSTALL_DIR%" (
    echo  [INFO] Pasta ja existe — atualizando...
    cd /d "%INSTALL_DIR%"
    git pull origin main
) ELSE (
    echo  [INFO] Clonando repositorio...
    git clone https://github.com/cristianoradin/zapdinapp.git "%INSTALL_DIR%"
    cd /d "%INSTALL_DIR%"
)

:: ── Ambiente virtual ──────────────────────────────────────────────────────────
echo.
echo  [1/4] Criando ambiente virtual Python...
python -m venv .venv
echo  [OK]

:: ── Dependencias ─────────────────────────────────────────────────────────────
echo.
echo  [2/4] Instalando dependencias (pode levar alguns minutos)...
.venv\Scripts\python -m pip install --upgrade pip -q
.venv\Scripts\python -m pip install -r requirements.txt -q
echo  [OK]

:: ── Playwright ────────────────────────────────────────────────────────────────
echo.
echo  [3/4] Instalando navegador Playwright (Chromium)...
.venv\Scripts\python -m playwright install chromium
echo  [OK]

:: ── Pasta de dados ────────────────────────────────────────────────────────────
IF NOT EXIST "data" mkdir data

:: ── Configuracao .env ─────────────────────────────────────────────────────────
echo.
echo  [4/4] Configuracao do sistema
echo  ─────────────────────────────────────────
echo.

IF EXIST ".env" (
    echo  [INFO] Arquivo .env ja existe. Pulando configuracao.
    goto :start_service
)

:: Gera SECRET_KEY
for /f %%k in ('.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"') do set SECRET_KEY=%%k

:: Perguntas ao usuario
echo  Responda as perguntas abaixo para configurar o sistema:
echo.

set /p MONITOR_URL="  URL do Monitor (ex: http://147.93.13.29:5000): "
set /p CLIENT_TOKEN="  Token do cliente (gerado no painel Monitor): "
set /p CLIENT_NAME="  Nome deste posto (ex: Loja Centro): "

:: Grava .env
(
echo APP_STATE=locked
echo PORT=4000
echo DATABASE_URL=data/app.db
echo SECRET_KEY=%SECRET_KEY%
echo MONITOR_URL=%MONITOR_URL%
echo MONITOR_CLIENT_TOKEN=%CLIENT_TOKEN%
echo CLIENT_NAME=%CLIENT_NAME%
echo CLIENT_CNPJ=
echo ERP_TOKEN=
) > .env

echo.
echo  [OK] Arquivo .env criado com sucesso.

:start_service
:: ── Instala como servico Windows (NSSM) ─────────────────────────────────────
echo.
set /p INSTALAR_SERVICO="  Instalar como servico Windows (inicia automatico)? [S/N]: "
IF /I "%INSTALAR_SERVICO%"=="S" (
    :: Baixa NSSM se nao tiver
    IF NOT EXIST "nssm.exe" (
        echo  Baixando NSSM...
        powershell -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile 'nssm.zip'" >nul 2>&1
        powershell -Command "Expand-Archive -Path 'nssm.zip' -DestinationPath 'nssm_tmp' -Force" >nul 2>&1
        copy "nssm_tmp\nssm-2.24\win64\nssm.exe" "nssm.exe" >nul
        rd /s /q nssm_tmp >nul 2>&1
        del nssm.zip >nul 2>&1
    )

    :: Remove servico anterior se existir
    nssm.exe stop ZapDinApp >nul 2>&1
    nssm.exe remove ZapDinApp confirm >nul 2>&1

    :: Instala servico
    nssm.exe install ZapDinApp "%INSTALL_DIR%\.venv\Scripts\python.exe" "-m uvicorn main:app --host 0.0.0.0 --port 4000"
    nssm.exe set ZapDinApp AppDirectory "%INSTALL_DIR%"
    nssm.exe set ZapDinApp DisplayName "ZapDin App"
    nssm.exe set ZapDinApp Description "ZapDin — Servidor de envio WhatsApp"
    nssm.exe set ZapDinApp Start SERVICE_AUTO_START
    nssm.exe set ZapDinApp AppStdout "%INSTALL_DIR%\data\zapdin.log"
    nssm.exe set ZapDinApp AppStderr "%INSTALL_DIR%\data\zapdin.log"
    nssm.exe start ZapDinApp

    echo  [OK] Servico ZapDinApp instalado e iniciado.
) ELSE (
    :: Cria atalho na area de trabalho
    powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\ZapDin App.lnk'); $s.TargetPath = '%INSTALL_DIR%\INICIAR.bat'; $s.WorkingDirectory = '%INSTALL_DIR%'; $s.IconLocation = 'shell32.dll,21'; $s.Save()"
    echo  [OK] Atalho criado na area de trabalho.
)

:: ── Cria INICIAR.bat ──────────────────────────────────────────────────────────
(
echo @echo off
echo title ZapDin App
echo cd /d "%INSTALL_DIR%"
echo start http://localhost:4000
echo .venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 4000
) > INICIAR.bat

:: ── Resumo ────────────────────────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║         Instalacao concluida!                ║
echo  ╠══════════════════════════════════════════════╣
echo  ║  Acesse: http://localhost:4000               ║
echo  ║  Pasta:  C:\ZapDinApp                        ║
echo  ║                                              ║
echo  ║  Proximo passo: ative o sistema com o        ║
echo  ║  token gerado no painel Monitor.             ║
echo  ╚══════════════════════════════════════════════╝
echo.

:: Abre o browser
start http://localhost:4000

pause
