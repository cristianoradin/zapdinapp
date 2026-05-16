"""
app/core/security_headers.py — Middleware de cabeçalhos de segurança HTTP.

Adiciona cabeçalhos defensivos a todas as respostas:
  - X-Content-Type-Options: nosniff — previne MIME sniffing
  - X-Frame-Options: SAMEORIGIN   — previne clickjacking
  - Referrer-Policy               — limita vazamento via Referer
  - Permissions-Policy            — desativa APIs perigosas não usadas
  - X-XSS-Protection              — camada extra em browsers legados

O que NÃO é adicionado aqui (e por quê):
  - HSTS: só válido em HTTPS; adicionar em HTTP causa lockout de clientes
  - CSP: app usa inline JS extensivo (onclick, app.js) — CSP quebraria tudo
          sem uma refatoração completa dos templates. Registrado como débito técnico.
  - CORS: frontend e API no mesmo processo/porta — same-origin por design
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Cabeçalhos adicionados em TODAS as respostas
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options":        "SAMEORIGIN",
    "X-XSS-Protection":       "1; mode=block",
    "Referrer-Policy":        "strict-origin-when-cross-origin",
    "Permissions-Policy":     "geolocation=(), microphone=(), camera=(), payment=()",
}

# Cabeçalhos adicionais apenas para respostas de API (não para arquivos estáticos)
_API_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injeta cabeçalhos de segurança em todas as respostas HTTP."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        for key, value in _SECURITY_HEADERS.items():
            response.headers[key] = value

        # Rotas de API não devem ser cacheadas
        path = request.url.path
        if path.startswith("/api/") or path.startswith("/internal/"):
            for key, value in _API_SECURITY_HEADERS.items():
                response.headers.setdefault(key, value)

        return response
