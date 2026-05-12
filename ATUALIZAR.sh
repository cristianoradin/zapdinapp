#!/bin/bash
# ZapDin App — Atualizador Mac/Linux

INSTALL_DIR="$HOME/ZapDinApp"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║         ZapDin App — Atualizador         ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

if [ ! -d "$INSTALL_DIR" ]; then
    echo "  [ERRO] ZapDin App não está instalado em $INSTALL_DIR"
    echo "  Execute primeiro o INSTALAR.sh"
    exit 1
fi

cd "$INSTALL_DIR"

# ── 1. Para serviço Mac (LaunchAgent) ────────────────────────────────────────
PLIST="$HOME/Library/LaunchAgents/com.zapdin.app.plist"
if [[ "$OSTYPE" == "darwin"* ]] && [ -f "$PLIST" ]; then
    echo "  [1/5] Parando serviço LaunchAgent..."
    launchctl unload "$PLIST" 2>/dev/null || true
    echo "  [OK] Serviço parado."

# ── 1. Para serviço Linux (systemd) ──────────────────────────────────────────
elif [[ "$OSTYPE" == "linux-gnu"* ]] && systemctl is-active --quiet zapdinapp 2>/dev/null; then
    echo "  [1/5] Parando serviço systemd..."
    sudo systemctl stop zapdinapp
    echo "  [OK] Serviço parado."
else
    echo "  [1/5] Verificando processos..."
fi

# ── 2. Mata qualquer processo na porta 4000 ───────────────────────────────────
echo "  [2/5] Encerrando processos na porta 4000..."
# Mac
if [[ "$OSTYPE" == "darwin"* ]]; then
    lsof -ti :4000 | xargs kill -9 2>/dev/null || true
# Linux
else
    fuser -k 4000/tcp 2>/dev/null || true
fi
# Mata uvicorn pelo nome em qualquer plataforma
pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "uvicorn.*4000"    2>/dev/null || true
sleep 2
echo "  [OK] Processos encerrados."

# ── 3. Atualiza o repositório ─────────────────────────────────────────────────
echo ""
echo "  [3/5] Baixando atualizações do GitHub..."
git fetch origin main
git reset --hard origin/main
echo "  [OK] Código atualizado."

# ── 4. Atualiza dependências ──────────────────────────────────────────────────
echo ""
echo "  [4/5] Atualizando dependências Python..."
.venv/bin/pip install -r requirements.txt -q --upgrade
echo "  [OK] Dependências atualizadas."

# ── 5. Reinicia o serviço ─────────────────────────────────────────────────────
echo ""
echo "  [5/5] Reiniciando serviço..."

if [[ "$OSTYPE" == "darwin"* ]] && [ -f "$PLIST" ]; then
    launchctl load "$PLIST"
    sleep 2
    echo "  [OK] Serviço LaunchAgent reiniciado."

elif [[ "$OSTYPE" == "linux-gnu"* ]] && [ -f "/etc/systemd/system/zapdinapp.service" ]; then
    sudo systemctl start zapdinapp
    sleep 2
    if systemctl is-active --quiet zapdinapp; then
        echo "  [OK] Serviço systemd reiniciado."
    else
        echo "  [AVISO] Verifique o serviço: sudo systemctl status zapdinapp"
    fi

else
    # Sem serviço — inicia em background
    nohup .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 4000 \
        >> data/zapdin.log 2>&1 &
    sleep 2
    echo "  [OK] App iniciado em background (PID $!)."
fi

# ── Resumo ────────────────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║         Atualização concluída!               ║"
echo "  ╠══════════════════════════════════════════════╣"
echo "  ║  Acesse: http://localhost:4000               ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

open "http://localhost:4000" 2>/dev/null || xdg-open "http://localhost:4000" 2>/dev/null || true
