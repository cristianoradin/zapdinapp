@echo off
chcp 65001 >nul
title ZapDin App — Instalador

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║         ZapDin App — Instalador          ║
echo  ╚══════════════════════════════════════════╝
echo.

set INSTALL_DIR=C:\ZapDinApp
set PG_VERSION=16
set PG_DIR=C:\Program Files\PostgreSQL\%PG_VERSION%
set PG_BIN=%PG_DIR%\bin
set PG_PASS=zapdin2024
set DB_NAME=zapdin_app

:: ── Verifica Python ───────────────────────────────────────────────────────────
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo  [ERRO] Python nao encontrado.
    echo.
    echo  Instale o Python 3.11 ou 3.12 em:
    echo  https://python.org/downloads
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
    echo  [INFO] Git nao encontrado. Instalando via winget...
    winget install --id Git.Git -e --source winget >nul 2>&1
    git --version >nul 2>&1
    IF ERRORLEVEL 1 (
        echo  [ERRO] Instale o Git manualmente: https://git-scm.com/download/win
        pause
        exit /b 1
    )
)
echo  [OK] Git encontrado.

:: ── Clona ou atualiza repositorio ────────────────────────────────────────────
echo.
echo  Pasta de instalacao: %INSTALL_DIR%
IF EXIST "%INSTALL_DIR%\.git" (
    echo  [INFO] Ja instalado — atualizando codigo...
    cd /d "%INSTALL_DIR%"
    git pull origin main
) ELSE (
    echo  [INFO] Clonando repositorio...
    git clone https://github.com/cristianoradin/zapdinapp.git "%INSTALL_DIR%"
    cd /d "%INSTALL_DIR%"
)

:: ── PostgreSQL ────────────────────────────────────────────────────────────────
echo.
echo  [1/5] Verificando PostgreSQL...

IF EXIST "%PG_BIN%\psql.exe" (
    echo  [OK] PostgreSQL %PG_VERSION% ja esta instalado.
) ELSE (
    echo  [INFO] PostgreSQL nao encontrado. Baixando instalador...
    echo  [INFO] Isso pode demorar alguns minutos...

    set PG_INSTALLER=%TEMP%\pg_installer.exe
    powershell -Command "Invoke-WebRequest -Uri 'https://get.enterprisedb.com/postgresql/postgresql-%PG_VERSION%.4-1-windows-x64.exe' -OutFile '%TEMP%\pg_installer.exe'" 2>nul

    IF NOT EXIST "%TEMP%\pg_installer.exe" (
        echo  [ERRO] Falha ao baixar PostgreSQL.
        echo  Baixe manualmente em: https://www.postgresql.org/download/windows/
        pause
        exit /b 1
    )

    echo  [INFO] Instalando PostgreSQL silenciosamente...
    "%TEMP%\pg_installer.exe" --mode unattended --superpassword "%PG_PASS%" --serverport 5432 --prefix "%PG_DIR%" --datadir "%PG_DIR%\data" >nul 2>&1

    IF NOT EXIST "%PG_BIN%\psql.exe" (
        echo  [ERRO] Falha na instalacao do PostgreSQL.
        pause
        exit /b 1
    )
    echo  [OK] PostgreSQL %PG_VERSION% instalado com sucesso.
    del "%TEMP%\pg_installer.exe" >nul 2>&1
)

:: ── Cria banco de dados ───────────────────────────────────────────────────────
echo  [INFO] Criando banco de dados %DB_NAME%...
set PGPASSWORD=%PG_PASS%
"%PG_BIN%\psql.exe" -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='%DB_NAME%'" 2>nul | findstr "1" >nul
IF ERRORLEVEL 1 (
    "%PG_BIN%\psql.exe" -U postgres -c "CREATE DATABASE %DB_NAME%;" >nul 2>&1
    echo  [OK] Banco %DB_NAME% criado.
) ELSE (
    echo  [OK] Banco %DB_NAME% ja existe.
)

:: ── Ambiente virtual ──────────────────────────────────────────────────────────
echo.
echo  [2/5] Criando ambiente virtual Python...
IF NOT EXIST "%INSTALL_DIR%\.venv" (
    python -m venv "%INSTALL_DIR%\.venv"
)
echo  [OK]

:: ── Dependencias ─────────────────────────────────────────────────────────────
echo.
echo  [3/5] Instalando dependencias Python (pode levar alguns minutos)...
"%INSTALL_DIR%\.venv\Scripts\python" -m pip install --upgrade pip -q
"%INSTALL_DIR%\.venv\Scripts\python" -m pip install -r "%INSTALL_DIR%\requirements.txt" -q
echo  [OK]

:: ── Playwright ────────────────────────────────────────────────────────────────
echo.
echo  [4/5] Instalando navegador Playwright (Chromium)...
"%INSTALL_DIR%\.venv\Scripts\python" -m playwright install chromium
echo  [OK]

:: ── Pasta de dados ────────────────────────────────────────────────────────────
IF NOT EXIST "%INSTALL_DIR%\data" mkdir "%INSTALL_DIR%\data"

:: ── Configuracao .env ─────────────────────────────────────────────────────────
echo.
echo  [5/5] Configuracao do sistema
echo  ─────────────────────────────────────────
echo.

IF EXIST "%INSTALL_DIR%\.env" (
    echo  [INFO] Arquivo .env ja existe. Pulando configuracao.
    goto :start_service
)

:: Gera SECRET_KEY
for /f %%k in ('"%INSTALL_DIR%\.venv\Scripts\python" -c "import secrets; print(secrets.token_hex(32))"') do set SECRET_KEY=%%k

:: Perguntas ao usuario
echo  Responda as perguntas abaixo:
echo.
set /p MONITOR_URL="  URL do Monitor [http://zapdin.gruposgapetro.com.br:5000/]: "
IF "%MONITOR_URL%"=="" set MONITOR_URL=http://zapdin.gruposgapetro.com.br:5000/
set /p CLIENT_TOKEN="  Token do cliente (gerado no painel Monitor): "

:: Busca o nome do cliente automaticamente pelo token
echo.
echo  Validando token no Monitor...
for /f "delims=" %%n in ('powershell -NoProfile -Command "(Invoke-RestMethod -Uri '%MONITOR_URL%api/activate/client-info?token=%CLIENT_TOKEN%' -Method GET -ErrorAction SilentlyContinue).nome"') do set CLIENT_NAME=%%n

IF "%CLIENT_NAME%"=="" (
    echo  [AVISO] Nao foi possivel validar o token. Verifique a URL e o token.
    set /p CLIENT_NAME="  Nome do posto (informe manualmente): "
) ELSE (
    echo  [OK] Cliente identificado: %CLIENT_NAME%
)

:: Grava .env
(
echo APP_STATE=locked
echo PORT=4000
echo DATABASE_URL=postgresql://postgres:%PG_PASS%@localhost/%DB_NAME%
echo SECRET_KEY=%SECRET_KEY%
echo MONITOR_URL=%MONITOR_URL%
echo MONITOR_CLIENT_TOKEN=%CLIENT_TOKEN%
echo CLIENT_NAME=%CLIENT_NAME%
echo CLIENT_CNPJ=
echo ERP_TOKEN=
) > "%INSTALL_DIR%\.env"

echo  [OK] Arquivo .env criado.

:start_service
:: ── NSSM ─────────────────────────────────────────────────────────────────────
echo.

IF NOT EXIST "%INSTALL_DIR%\nssm.exe" (
    echo  [INFO] Baixando NSSM...
    powershell -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile '%TEMP%\nssm.zip'" >nul 2>&1
    powershell -Command "Expand-Archive -Path '%TEMP%\nssm.zip' -DestinationPath '%TEMP%\nssm_tmp' -Force" >nul 2>&1
    copy "%TEMP%\nssm_tmp\nssm-2.24\win64\nssm.exe" "%INSTALL_DIR%\nssm.exe" >nul
    rd /s /q "%TEMP%\nssm_tmp" >nul 2>&1
    del "%TEMP%\nssm.zip" >nul 2>&1
)

:: Remove servico anterior se existir
"%INSTALL_DIR%\nssm.exe" stop ZapDinApp >nul 2>&1
"%INSTALL_DIR%\nssm.exe" remove ZapDinApp confirm >nul 2>&1
sc delete ZapDinApp >nul 2>&1
timeout /t 2 /nobreak >nul

:: Instala servico
"%INSTALL_DIR%\nssm.exe" install ZapDinApp "%INSTALL_DIR%\.venv\Scripts\python.exe" "-m uvicorn main:app --host 0.0.0.0 --port 4000"
"%INSTALL_DIR%\nssm.exe" set ZapDinApp AppDirectory "%INSTALL_DIR%"
"%INSTALL_DIR%\nssm.exe" set ZapDinApp DisplayName "ZapDin App"
"%INSTALL_DIR%\nssm.exe" set ZapDinApp Description "ZapDin — Servidor de envio WhatsApp"
"%INSTALL_DIR%\nssm.exe" set ZapDinApp Start SERVICE_AUTO_START
"%INSTALL_DIR%\nssm.exe" set ZapDinApp AppStdout "%INSTALL_DIR%\data\zapdin.log"
"%INSTALL_DIR%\nssm.exe" set ZapDinApp AppStderr "%INSTALL_DIR%\data\zapdin.log"
"%INSTALL_DIR%\nssm.exe" set ZapDinApp AppEnvironmentExtra PGPASSWORD=%PG_PASS%
"%INSTALL_DIR%\nssm.exe" start ZapDinApp

timeout /t 3 /nobreak >nul
sc query ZapDinApp | findstr "RUNNING" >nul
IF NOT ERRORLEVEL 1 (
    echo  [OK] Servico ZapDinApp iniciado com sucesso.
) ELSE (
    echo  [AVISO] Servico pode nao ter iniciado. Verifique o log:
    echo  type %INSTALL_DIR%\data\zapdin.log
)

:: ── Atalho na area de trabalho ────────────────────────────────────────────────
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\ZapDin App.lnk'); $s.TargetPath = 'http://localhost:4000'; $s.Save()" >nul 2>&1

:: ── Resumo ────────────────────────────────────────────────────────────────────
echo.
echo  ╔════════════════════════════════════════════════════╗
echo  ║           Instalacao concluida!                    ║
echo  ╠════════════════════════════════════════════════════╣
echo  ║  App:       http://localhost:4000                  ║
echo  ║  Banco:     PostgreSQL 16 — zapdin_app             ║
echo  ║  Servico:   ZapDinApp (auto-start)                 ║
echo  ║  Pasta:     C:\ZapDinApp                           ║
echo  ║                                                    ║
echo  ║  Proximo passo: ative com o token do Monitor.      ║
echo  ╚════════════════════════════════════════════════════╝
echo.

timeout /t 2 /nobreak >nul
start http://localhost:4000
pause
