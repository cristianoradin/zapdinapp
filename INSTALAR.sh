#!/bin/bash
# ZapDin App — Instalador Mac/Linux
set -e

INSTALL_DIR="$HOME/ZapDinApp"
REPO_URL="https://github.com/cristianoradin/zapdinapp.git"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║         ZapDin App — Instalador          ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── Verifica Python ───────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "  [ERRO] Python3 não encontrado."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  Instale com: brew install python@3.12"
    else
        echo "  Instale com: sudo apt install python3 python3-venv python3-pip"
    fi
    exit 1
fi
PY_VER=$(python3 --version)
echo "  [OK] $PY_VER encontrado."

# ── Verifica Git ──────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    echo "  [ERRO] Git não encontrado."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  Instale com: brew install git"
    else
        echo "  Instale com: sudo apt install git"
    fi
    exit 1
fi
echo "  [OK] Git encontrado."

# ── Clona ou atualiza ─────────────────────────────────────────────────────────
echo ""
echo "  Pasta de instalação: $INSTALL_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  [INFO] Já instalado — atualizando..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    echo "  [INFO] Clonando repositório..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── Ambiente virtual ──────────────────────────────────────────────────────────
echo ""
echo "  [1/4] Criando ambiente virtual Python..."
python3 -m venv .venv
echo "  [OK]"

# ── Dependencias ─────────────────────────────────────────────────────────────
echo ""
echo "  [2/4] Instalando dependências (pode levar alguns minutos)..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
echo "  [OK]"

# ── Playwright ────────────────────────────────────────────────────────────────
echo ""
echo "  [3/4] Instalando navegador Playwright (Chromium)..."
.venv/bin/python -m playwright install chromium
echo "  [OK]"

# ── Pasta de dados ────────────────────────────────────────────────────────────
mkdir -p data

# ── Configuração .env ─────────────────────────────────────────────────────────
echo ""
echo "  [4/4] Configuração do sistema"
echo "  ─────────────────────────────────────────"
echo ""

if [ -f ".env" ]; then
    echo "  [INFO] Arquivo .env já existe. Pulando configuração."
else
    SECRET_KEY=$(.venv/bin/python -c "import secrets; print(secrets.token_hex(32))")

    read -p "  URL do Monitor (ex: http://147.93.13.29:5000): " MONITOR_URL
    read -p "  Token do cliente (gerado no painel Monitor): " CLIENT_TOKEN
    read -p "  Nome deste posto (ex: Loja Centro): " CLIENT_NAME

    cat > .env <<EOF
APP_STATE=locked
PORT=4000
DATABASE_URL=data/app.db
SECRET_KEY=${SECRET_KEY}
MONITOR_URL=${MONITOR_URL}
MONITOR_CLIENT_TOKEN=${CLIENT_TOKEN}
CLIENT_NAME=${CLIENT_NAME}
CLIENT_CNPJ=
ERP_TOKEN=
EOF
    echo "  [OK] Arquivo .env criado."
fi

# ── Script de inicialização ───────────────────────────────────────────────────
cat > "$INSTALL_DIR/INICIAR.sh" <<'EOF'
#!/bin/bash
cd "$(dirname "$0")"
echo "Iniciando ZapDin App em http://localhost:4000"
open "http://localhost:4000" 2>/dev/null || xdg-open "http://localhost:4000" 2>/dev/null || true
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 4000
EOF
chmod +x "$INSTALL_DIR/INICIAR.sh"

# ── LaunchAgent Mac (auto-start no login) ─────────────────────────────────────
if [[ "$OSTYPE" == "darwin"* ]]; then
    read -p "  Iniciar automaticamente no login do Mac? [S/N]: " AUTO_START
    if [[ "$AUTO_START" =~ ^[Ss]$ ]]; then
        PLIST="$HOME/Library/LaunchAgents/com.zapdin.app.plist"
        cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.zapdin.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>${INSTALL_DIR}/.venv/bin/python</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>main:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>4000</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${INSTALL_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${INSTALL_DIR}/data/zapdin.log</string>
    <key>StandardErrorPath</key>
    <string>${INSTALL_DIR}/data/zapdin.log</string>
</dict>
</plist>
EOF
        launchctl load "$PLIST"
        echo "  [OK] Serviço configurado para iniciar automaticamente."
    fi
fi

# ── systemd Linux ─────────────────────────────────────────────────────────────
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    read -p "  Instalar como serviço systemd (auto-start)? [S/N]: " AUTO_START
    if [[ "$AUTO_START" =~ ^[Ss]$ ]]; then
        SERVICE_FILE="/etc/systemd/system/zapdinapp.service"
        sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=ZapDin App
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 4000
Restart=always
RestartSec=5
StandardOutput=append:${INSTALL_DIR}/data/zapdin.log
StandardError=append:${INSTALL_DIR}/data/zapdin.log

[Install]
WantedBy=multi-user.target
EOF
        sudo systemctl daemon-reload
        sudo systemctl enable zapdinapp
        sudo systemctl start zapdinapp
        echo "  [OK] Serviço systemd instalado e iniciado."
    fi
fi

# ── Inicia agora ──────────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║         Instalação concluída!                ║"
echo "  ╠══════════════════════════════════════════════╣"
echo "  ║  Acesse: http://localhost:4000               ║"
echo "  ║  Pasta:  $INSTALL_DIR"
echo "  ║                                              ║"
echo "  ║  Próximo passo: ative o sistema com o        ║"
echo "  ║  token gerado no painel Monitor.             ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

open "http://localhost:4000" 2>/dev/null || xdg-open "http://localhost:4000" 2>/dev/null || true

# Inicia o app
cd "$INSTALL_DIR"
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 4000
