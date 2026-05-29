"""
app/routers/ai_config_router.py — Configuração de provedores de IA.

Gerencia API keys e configuração de uso (OCR / Chatbot) para os
provedores OpenAI, Gemini, Anthropic e Groq.

Prefixo: /api/config  (mesmas URLs — retrocompatível)
"""
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.config import settings
from ..core.security import get_current_user

router = APIRouter(prefix="/api/config", tags=["ai-config"])

_AI_PROVIDERS = {
    "openai":    {"env": "OPENAI_API_KEY",    "attr": "openai_api_key",    "prefix": "sk-"},
    "gemini":    {"env": "GEMINI_API_KEY",     "attr": "gemini_api_key",    "prefix": "AIza"},
    "anthropic": {"env": "ANTHROPIC_API_KEY",  "attr": "anthropic_api_key", "prefix": "sk-ant-"},
    "groq":      {"env": "GROQ_API_KEY",       "attr": "groq_api_key",      "prefix": "gsk_"},
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


class AIUsoBody(BaseModel):
    provider: str
    ocr: bool = False
    chat: bool = False


class AIAtivoBody(BaseModel):
    provider: str
    ativo: bool


@router.get("/ai-keys")
async def get_ai_keys(user: dict = Depends(get_current_user)):
    """Retorna status de todos os provedores de IA com suas configurações de uso."""
    def _uso(raw: str) -> dict:
        parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
        return {"ocr": "ocr" in parts, "chat": "chat" in parts}

    return {
        "openai":    {**_key_preview(settings.openai_api_key or ""),    "uso": _uso(settings.ai_uso_openai),    "ativo": settings.ai_ativo_openai},
        "gemini":    {**_key_preview(settings.gemini_api_key or ""),    "uso": _uso(settings.ai_uso_gemini),    "ativo": settings.ai_ativo_gemini},
        "anthropic": {**_key_preview(settings.anthropic_api_key or ""), "uso": _uso(settings.ai_uso_anthropic), "ativo": settings.ai_ativo_anthropic},
        "groq":      {**_key_preview(settings.groq_api_key or ""),      "uso": _uso(settings.ai_uso_groq),      "ativo": settings.ai_ativo_groq},
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


@router.post("/ai-uso")
async def set_ai_uso(body: AIUsoBody, user: dict = Depends(get_current_user)):
    """Salva para que uso cada provedor de IA é destinado (OCR / Chatbot)."""
    provider = body.provider.strip().lower()
    if provider not in _AI_PROVIDERS:
        raise HTTPException(400, f"Provedor inválido: {provider}")
    parts = []
    if body.ocr:  parts.append("ocr")
    if body.chat: parts.append("chat")
    uso_str = ",".join(parts)
    env_key = f"AI_USO_{provider.upper()}"
    attr    = f"ai_uso_{provider}"
    _update_env_key(env_key, uso_str)
    setattr(settings, attr, uso_str)
    return {"ok": True}


@router.post("/ai-ativo")
async def set_ai_ativo(body: AIAtivoBody, user: dict = Depends(get_current_user)):
    """Ativa ou desativa um provider de IA sem apagar a chave ou a configuração de uso."""
    provider = body.provider.strip().lower()
    if provider not in _AI_PROVIDERS:
        raise HTTPException(400, f"Provedor inválido: {provider}")
    env_key = f"AI_ATIVO_{provider.upper()}"
    _update_env_key(env_key, "true" if body.ativo else "false")
    setattr(settings, f"ai_ativo_{provider}", body.ativo)
    return {"ok": True, "provider": provider, "ativo": body.ativo}


# Mantém compatibilidade com endpoint antigo
@router.get("/openai-key")
async def get_openai_key_status(user: dict = Depends(get_current_user)):
    return _key_preview(settings.openai_api_key or "")


@router.post("/openai-key")
async def set_openai_key(body: AIKeyBody, user: dict = Depends(get_current_user)):
    body.provider = "openai"
    return await set_ai_key(body, user)
