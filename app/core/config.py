import logging
import sys
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)

# Quando frozen pelo PyInstaller, os módulos ficam em _internal/ e __file__ aponta
# para dentro dessa pasta. O .env real está na pasta do executável (pai de _internal).
# Em dev, sobe dois níveis a partir de app/core/ → app/ → .env como antes.
if getattr(sys, "frozen", False):
    # Frozen: sys.executable = C:\ZapDinApp\ZapDinApp.exe → parent = C:\ZapDinApp\
    _ENV_FILE = str(Path(sys.executable).parent / ".env")
else:
    # Dev: app/core/config.py → app/core/ → app/ → app/.env
    _ENV_FILE = str(Path(__file__).parent.parent / ".env")

# Tenta descriptografar .env.enc via DPAPI (Windows) antes do pydantic-settings
# ler o env_file. Se o .enc existir, os valores são injetados em os.environ,
# que tem prioridade sobre o env_file no pydantic-settings.
try:
    from .env_protector import load_env_to_environ as _load_enc
    _load_enc(Path(_ENV_FILE))
except Exception:
    pass  # Nunca impede o startup — fallback para o .env normal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8-sig", extra="ignore")

    secret_key: str = "dev-secret-key-change-in-production"
    session_max_age: int = 86400
    database_url: str = "postgresql://postgres@localhost/zapdin_app"
    port: int = 4000

    # True apenas quando o app roda com HTTPS (produção cloud).
    # Manter False para instalações locais (HTTP) — caso contrário o browser
    # não envia o cookie e o login quebra.
    cookie_secure: bool = False

    # Estado de ativação: "locked" bloqueia todas as rotas exceto /activate
    app_state: str = "locked"

    erp_token: str = "meu-token-erp"

    monitor_url: str = "http://localhost:5000"
    monitor_client_token: str = ""

    client_name: str = "Posto Principal"
    client_cnpj: str = ""

    # Nome do serviço no Windows (Task Scheduler / NSSM).
    # O instalador grava este valor no .env para que o updater use ao reiniciar.
    service_name: str = "ZapDinApp"

    github_repo: str = "cristianoradin/zapdin2"

    # Velopack: URL do canal de atualizações
    velopack_channel_url: str = ""
    # Path para o Update.exe do Velopack (relativo à pasta do executável)
    velopack_update_exe: str = "Update.exe"

    dispatch_min_delay: float = 1.0   # segundos mínimos entre disparos
    dispatch_max_delay: float = 4.0   # segundos máximos entre disparos

    public_url: str = "http://localhost:4000"

    # Backend de WhatsApp: "playwright" (padrão) ou "evolution"
    wa_backend: str = "playwright"

    # Evolution API (usado quando wa_backend=evolution)
    evolution_url: str = "http://localhost:8080"
    evolution_api_key: str = ""

    # Módulo Contábil — OCR via IA (OpenAI / Google Gemini / Anthropic Claude)
    openai_api_key:    str = ""
    gemini_api_key:    str = ""
    anthropic_api_key: str = ""
    ai_provider:       str = "openai"   # openai | gemini | anthropic

    @property
    def is_locked(self) -> bool:
        return self.app_state.lower() == "locked"

    @property
    def use_evolution(self) -> bool:
        return self.wa_backend.lower() == "evolution"


settings = Settings()

_DEFAULT_SECRET = "dev-secret-key-change-in-production"
if settings.secret_key == _DEFAULT_SECRET:
    # Em produção (app_state=active), recusa subir com chave pública conhecida.
    # Em desenvolvimento (app_state=locked ou omitido), apenas avisa.
    if settings.app_state.lower() == "active":
        raise ValueError(
            "[config] ERRO FATAL: SECRET_KEY está com o valor padrão de desenvolvimento! "
            "Defina SECRET_KEY no .env antes de usar em produção — "
            "qualquer pessoa pode forjar cookies de sessão com este valor."
        )
    _logger.warning(
        "[config] ATENÇÃO: SECRET_KEY está com o valor padrão de desenvolvimento. "
        "Defina SECRET_KEY no .env antes de usar em produção."
    )
