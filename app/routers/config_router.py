import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.config import settings
from ..core.database import get_db
from ..core.security import get_current_user

router = APIRouter(prefix="/api/config", tags=["config"])

# Template padrão usado na primeira vez (sem mensagem_padrao salva no banco)
_DEFAULT_TEMPLATE = (
    "✅ *Venda Confirmada!*\n\n"
    "👤 Cliente: {nome}\n"
    "💰 Valor Total: R$ {valor_total}\n"
    "📅 Data: {data}\n\n"
    "🛒 *Itens:*\n{produtos}\n\n"
    "Obrigado pela preferência! 🙏"
)


@router.get("")
async def get_config(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT key, value FROM config WHERE empresa_id=?", (empresa_id,)
    ) as cur:
        rows = await cur.fetchall()
    data = {r["key"]: r["value"] for r in rows}

    # Garante template padrão se ainda não foi salvo
    if "mensagem_padrao" not in data:
        data["mensagem_padrao"] = _DEFAULT_TEMPLATE

    # Expõe o nome da empresa da licença (somente leitura — não editável)
    data["client_name"] = settings.client_name or ""

    return data


@router.post("")
async def set_config(
    body: dict,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    for key, value in body.items():
        await db.execute(
            """INSERT INTO config (empresa_id, key, value) VALUES (?, ?, ?)
               ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value""",
            (empresa_id, key, str(value)),
        )
    await db.commit()
    return {"ok": True}


# ── IA Multi-provider ─────────────────────────────────────────────────────────

_AI_PROVIDERS = {
    "openai":    {"env": "OPENAI_API_KEY",    "attr": "openai_api_key",    "prefix": "sk-"},
    "gemini":    {"env": "GEMINI_API_KEY",     "attr": "gemini_api_key",    "prefix": "AIza"},
    "anthropic": {"env": "ANTHROPIC_API_KEY",  "attr": "anthropic_api_key", "prefix": "sk-ant-"},
}


def _update_env_key(env_key: str, value: str) -> None:
    """Grava/atualiza uma chave no .env em disco e em memória."""
    from ..core.config import _ENV_FILE
    env_path = Path(_ENV_FILE)

    lines_out: list[str] = []
    found = False
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(env_key + "=") or stripped.startswith(env_key + " ="):
                lines_out.append(f"{env_key}={value}")
                found = True
            else:
                lines_out.append(line)
    if not found:
        lines_out.append(f"{env_key}={value}")

    env_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    os.environ[env_key] = value


def _key_preview(key: str) -> dict:
    configurado = bool(key and len(key) > 8)
    preview = (key[:8] + "..." + key[-4:]) if configurado else ""
    return {"configurado": configurado, "preview": preview}


class AIKeyBody(BaseModel):
    provider: str
    key: str


class AIProviderBody(BaseModel):
    provider: str


@router.get("/ai-keys")
async def get_ai_keys(user: dict = Depends(get_current_user)):
    """Retorna status de todos os provedores de IA + provedor ativo."""
    return {
        "provider_ativo": settings.ai_provider or "openai",
        "openai":    _key_preview(settings.openai_api_key or ""),
        "gemini":    _key_preview(settings.gemini_api_key or ""),
        "anthropic": _key_preview(settings.anthropic_api_key or ""),
    }


@router.post("/ai-key")
async def set_ai_key(body: AIKeyBody, user: dict = Depends(get_current_user)):
    provider = body.provider.strip().lower()
    if provider not in _AI_PROVIDERS:
        raise HTTPException(400, f"Provedor inválido: {provider}")
    cfg = _AI_PROVIDERS[provider]
    key = body.key.strip()
    if key and not key.startswith(cfg["prefix"]):
        raise HTTPException(400, f"Chave inválida para {provider} — deve começar com '{cfg['prefix']}'")
    _update_env_key(cfg["env"], key)
    setattr(settings, cfg["attr"], key)
    return {"ok": True}


@router.post("/ai-provider")
async def set_ai_provider(body: AIProviderBody, user: dict = Depends(get_current_user)):
    provider = body.provider.strip().lower()
    if provider not in _AI_PROVIDERS:
        raise HTTPException(400, f"Provedor inválido: {provider}")
    _update_env_key("AI_PROVIDER", provider)
    settings.ai_provider = provider
    return {"ok": True}


# Mantém compatibilidade com endpoint antigo
@router.get("/openai-key")
async def get_openai_key_status(user: dict = Depends(get_current_user)):
    return _key_preview(settings.openai_api_key or "")


@router.post("/openai-key")
async def set_openai_key(body: AIKeyBody, user: dict = Depends(get_current_user)):
    body.provider = "openai"
    return await set_ai_key(body, user)
