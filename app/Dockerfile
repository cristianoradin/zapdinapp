# app/Dockerfile — ZapDin App
#
# Build em dois estágios:
#   1. builder: instala dependências Python (sem Playwright browsers)
#   2. runtime: imagem mínima + Playwright cromium

# ── Estágio 1: builder ────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Instala dependências do sistema necessárias para compilar pacotes
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Estágio 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Playwright precisa desses pacotes para rodar Chromium headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 && \
    rm -rf /var/lib/apt/lists/*

# Copia pacotes instalados do builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copia código da app
COPY . /app/app
COPY requirements.txt /app/

# Instala navegador do Playwright (apenas Chromium, ~100MB)
RUN python -m playwright install chromium --with-deps 2>/dev/null || true

# Cria diretórios de dados
RUN mkdir -p /app/data /app/uploads

# Variáveis de ambiente padrão (sobrescritas pelo docker-compose)
ENV APP_STATE=active \
    PORT=4000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 4000

# Comando padrão (sem --reload para produção)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4000"]
