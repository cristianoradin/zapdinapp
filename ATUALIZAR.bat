@echo off
chcp 65001 >nul
title ZapDin App — Atualizador

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║         ZapDin App — Atualizador         ║
echo  ╚══════════════════════════════════════════╝
echo.

set INSTALL_DIR=C:\ZapDinApp

IF NOT EXIST "%INSTALL_DIR%" (
    echo  [ERRO] ZapDin App nao esta instalado em %INSTALL_DIR%
    echo  Execute primeiro o INSTALAR.bat
    pause
    exit /b 1
)

cd /d "%INSTALL_DIR%"

:: ── 1. Para o serviço NSSM ───────────────────────────────────────────────────
echo  [1/5] Parando servico ZapDinApp...
sc query ZapDinApp >nul 2>&1
IF NOT ERRORLEVEL 1 (
    nssm.exe stop ZapDinApp >nul 2>&1
    echo  [OK] Servico parado.
) ELSE (
    echo  [INFO] Servico NSSM nao encontrado — verificando processos...
)

:: ── 2. Mata qualquer processo uvicorn/python rodando na porta 4000 ──────────
echo  [2/5] Encerrando processos na porta 4000...
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":4000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
    echo  [OK] Processo %%p encerrado.
)

:: Mata qualquer uvicorn restante
taskkill /F /IM "python.exe" /FI "WINDOWTITLE eq ZapDin*" >nul 2>&1
taskkill /F /FI "IMAGENAME eq python.exe" /FI "MODULES eq uvicorn*" >nul 2>&1

:: Aguarda liberar
timeout /t 2 /nobreak >nul
echo  [OK] Processos encerrados.

:: ── 3. Atualiza o repositório ─────────────────────────────────────────────────
echo.
echo  [3/5] Baixando atualizacoes do GitHub...
git fetch origin main
git reset --hard origin/main
echo  [OK] Codigo atualizado.

:: ── 4. Atualiza dependências ──────────────────────────────────────────────────
echo.
echo  [4/5] Atualizando dependencias Python...
.venv\Scripts\pip install -r requirements.txt -q --upgrade
echo  [OK] Dependencias atualizadas.

:: ── 5. Reinicia o serviço ─────────────────────────────────────────────────────
echo.
echo  [5/5] Reiniciando servico...

sc query ZapDinApp >nul 2>&1
IF NOT ERRORLEVEL 1 (
    nssm.exe start ZapDinApp
    timeout /t 3 /nobreak >nul
    sc query ZapDinApp | findstr "RUNNING" >nul 2>&1
    IF NOT ERRORLEVEL 1 (
        echo  [OK] Servico ZapDinApp reiniciado com sucesso.
    ) ELSE (
        echo  [AVISO] Servico pode nao ter iniciado. Verifique com: sc query ZapDinApp
    )
) ELSE (
    echo  [INFO] Iniciando sem servico NSSM...
    start "ZapDin App" /min cmd /c ".venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 4000"
    timeout /t 3 /nobreak >nul
    echo  [OK] App iniciado em background.
)

:: ── Resumo ────────────────────────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║         Atualizacao concluida!               ║
echo  ╠══════════════════════════════════════════════╣
echo  ║  Acesse: http://localhost:4000               ║
echo  ╚══════════════════════════════════════════════╝
echo.

timeout /t 2 /nobreak >nul
start http://localhost:4000

pause
