# ZapDin App — Instalador Windows

## Como gerar o ZapDin-Setup.exe

### Pré-requisito
Instale o **Inno Setup 6** na máquina de build:
https://jrsoftware.org/isdl.php

### Compilar
```cmd
cd instalador
build.bat
```

Gera o arquivo `instalador/ZapDin-Setup.exe`.

---

## O que o instalador faz automaticamente

| Etapa | Descrição |
|---|---|
| Python 3.12 | Baixa e instala silenciosamente se não tiver |
| Git | Baixa e instala silenciosamente se não tiver |
| PostgreSQL 16 | Baixa e instala silenciosamente se não tiver |
| Banco de dados | Cria o banco `zapdin_app` automaticamente |
| ZapDin App | Clona do GitHub |
| Dependências | Instala via pip |
| Playwright | Instala Chromium para WhatsApp Web |
| `.env` | Cria com as configurações informadas |
| Serviço NSSM | Registra como serviço Windows (auto-start) |
| Atalho | Cria na Área de Trabalho e no Menu Iniciar |

## O usuário responde apenas 3 perguntas

1. URL do Monitor
2. Token do cliente
3. Nome do posto
