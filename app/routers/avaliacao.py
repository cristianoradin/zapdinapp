import html as _html
import json as _json
import os as _os
import secrets
import logging
from datetime import datetime, timezone
from pathlib import Path as _Path
from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..core.database import get_db, get_db_direct
from ..core.security import get_current_user
from ..core.config import settings
from ..repositories import AvaliacaoRepository

logger = logging.getLogger(__name__)
router = APIRouter(tags=["avaliacao"])


# ── M9: Template externo (app/static/survey.html) ─────────────────────────────
# HTML em arquivo separado → editável sem tocar em Python, sem risco de XSS.

def _survey_template_path() -> _Path:
    """Localiza survey.html relativo a este arquivo, compatível com PyInstaller."""
    import sys
    if getattr(sys, "frozen", False):
        base = _Path(sys.executable).parent
    else:
        base = _Path(__file__).parent.parent
    return base / "static" / "survey.html"


def _render_survey(body_html: str, nome_empresa: str, token: str) -> str:
    """Renderiza survey.html substituindo os placeholders com valores escapados."""
    try:
        tmpl = _survey_template_path().read_text(encoding="utf-8")
    except Exception:
        # Fallback mínimo se o arquivo não existir (improvável em produção)
        return f"<html><body>{body_html}</body></html>"
    return (
        tmpl
        .replace("{{EMPRESA}}", _html.escape(nome_empresa))
        .replace("{{TOKEN_JS}}", _json.dumps(token))   # JSON-encoded — seguro em contexto JS
        .replace("{{BODY_HTML}}", body_html)
    )


def _survey_page(nome_empresa: str, token: str, vendedor: str = "", already_answered: bool = False, invalid: bool = False) -> str:
    """Monta o HTML da página de avaliação usando o template externo."""
    if invalid:
        body_html = """
        <div class="card">
          <div class="icon-wrap">❌</div>
          <h1>Link inválido</h1>
          <p class="sub">Este link não é válido ou já expirou.</p>
        </div>"""
    elif already_answered:
        body_html = """
        <div class="card">
          <div class="icon-wrap animate-in">✅</div>
          <h1>Avaliação registrada!</h1>
          <p class="sub">Obrigado pelo seu feedback. Sua opinião é muito importante para nós.</p>
        </div>"""
    else:
        vendedor_html = (
            f'<div class="vendedor">Vendedor: <strong>{_html.escape(vendedor)}</strong></div>'
            if vendedor else ''
        )
        body_html = f"""
        <div class="card" id="formCard">
          <div class="empresa-name">{_html.escape(nome_empresa)}</div>
          <h1>Como foi seu atendimento?</h1>
          {vendedor_html}
          <p class="sub">Sua avaliação nos ajuda a melhorar cada dia mais.</p>
          <div class="stars" id="starsRow">
            <button class="star" data-v="1" onclick="setStar(1)" title="Péssimo">⭐</button>
            <button class="star" data-v="2" onclick="setStar(2)" title="Ruim">⭐</button>
            <button class="star" data-v="3" onclick="setStar(3)" title="Regular">⭐</button>
            <button class="star" data-v="4" onclick="setStar(4)" title="Bom">⭐</button>
            <button class="star" data-v="5" onclick="setStar(5)" title="Excelente">⭐</button>
          </div>
          <div class="star-labels">
            <span>Péssimo</span><span></span><span>Regular</span><span></span><span>Excelente</span>
          </div>
          <div id="nota-val" class="nota-label" style="display:none"></div>
          <textarea id="comentario" placeholder="Deixe um comentário (opcional)…" rows="3"></textarea>
          <button class="btn-send" id="btnEnviar" onclick="enviarAvaliacao()" disabled>Enviar Avaliação</button>
          <div id="msgErro" class="msg-erro" style="display:none"></div>
        </div>
        <div class="card" id="thanksCard" style="display:none">
          <div class="icon-wrap animate-in">✅</div>
          <h1>Obrigado!</h1>
          <p class="sub">Sua avaliação foi registrada com sucesso.<br>Agradecemos seu feedback!</p>
        </div>"""

    return _render_survey(body_html, nome_empresa, token)


# ── Rotas públicas ─────────────────────────────────────────────────────────────

@router.get("/avaliacao", response_class=HTMLResponse, include_in_schema=False)
async def survey_page(t: str = ""):
    if not t:
        return HTMLResponse(_survey_page("", "", invalid=True))
    # Token DEMO → página de demonstração com dados de exemplo
    if t.upper() == "DEMO":
        nome_emp = "Sua Empresa"
        async with get_db_direct() as db:
            async with db.execute("SELECT nome FROM empresas LIMIT 1") as cur:
                row_emp = await cur.fetchone()
            if row_emp:
                nome_emp = row_emp["nome"]
        return HTMLResponse(_survey_page(nome_emp, "DEMO", vendedor="João Silva"))
    async with get_db_direct() as db:
        async with db.execute(
            "SELECT empresa_id, nome_cliente, vendedor, nota FROM avaliacoes WHERE token = ?",
            (t,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return HTMLResponse(_survey_page("", t, invalid=True))
        if row["nota"] is not None:
            # Busca nome da empresa
            async with db.execute(
                "SELECT nome FROM empresas WHERE id = ?", (row["empresa_id"],)
            ) as cur2:
                emp = await cur2.fetchone()
            nome_emp = emp["nome"] if emp else ""
            return HTMLResponse(_survey_page(nome_emp, t, already_answered=True))
        # Busca nome da empresa
        async with db.execute(
            "SELECT nome FROM empresas WHERE id = ?", (row["empresa_id"],)
        ) as cur3:
            emp = await cur3.fetchone()
        nome_emp = emp["nome"] if emp else ""
        return HTMLResponse(_survey_page(nome_emp, t, vendedor=row["vendedor"] or ""))


_cached_demo_link: str = ""

@router.get("/api/avaliacao/link-demo")
async def get_link_demo(user=Depends(get_current_user)):
    """Retorna link encurtado do DEMO — cacheado em memória."""
    global _cached_demo_link
    if not _cached_demo_link:
        url = f"{settings.public_url}/avaliacao?t=DEMO"
        from ..routers.erp import _encurtar_url
        _cached_demo_link = await _encurtar_url(url)
    return {"link": _cached_demo_link}


@router.get("/avaliacao/preview", response_class=HTMLResponse, include_in_schema=False)
async def survey_preview(empresa_id: Optional[int] = None):
    """Demo preview — usado pelo monitor para pré-visualização."""
    nome_emp = "Sua Empresa"
    if empresa_id:
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT nome FROM empresas WHERE id = ?", (empresa_id,)
            ) as cur:
                row = await cur.fetchone()
            if row:
                nome_emp = row["nome"]
    return HTMLResponse(_survey_page(nome_emp, "DEMO", vendedor="João Silva"))


class AvaliacaoResposta(BaseModel):
    # M7: validação forte — rejeita nota fora de 1-5 e token suspeito antes de tocar o banco
    token: str = Field(min_length=1, max_length=128)
    nota: int = Field(ge=1, le=5)
    comentario: Optional[str] = Field(default="", max_length=1000)


@router.post("/api/avaliacao/responder")
async def responder_avaliacao(body: AvaliacaoResposta):
    if body.token.upper() == "DEMO":
        logger.info("[avaliacao] DEMO nota=%d (não gravado)", body.nota)
        return {"ok": True}
    async with get_db_direct() as db:
        repo = AvaliacaoRepository(db)
        row = await repo.get_by_token(body.token)
        if not row:
            return JSONResponse({"ok": False, "detail": "Token inválido."}, status_code=404)
        if row["nota"] is not None:
            return JSONResponse({"ok": False, "detail": "Avaliação já registrada."}, status_code=409)
        await repo.responder(body.token, body.nota, body.comentario or "")
    logger.info("[avaliacao] nota=%d token=%s", body.nota, body.token[:8])
    return {"ok": True}


# ── Rotas autenticadas ─────────────────────────────────────────────────────────

@router.get("/api/avaliacoes")
async def list_avaliacoes(
    dias: int = 30,
    vendedor: Optional[str] = None,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    repo = AvaliacaoRepository(db)
    rows = await repo.list(user["empresa_id"], dias, vendedor)
    return [
        {
            "id": r["id"],
            "telefone": r["phone"] or "",
            "nome": r["nome_cliente"] or "—",
            "vendedor": r["vendedor"] or "—",
            "nota": r["nota"],
            "comentario": r["comentario"] or "",
            "data": r["respondido_em"].strftime("%d/%m/%Y %H:%M") if r["respondido_em"] else (
                    r["created_at"].strftime("%d/%m/%Y") if r["created_at"] else "—"),
        }
        for r in rows
    ]


@router.get("/api/avaliacoes/dashboard")
async def dashboard_avaliacoes(
    dias: int = 30,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    repo = AvaliacaoRepository(db)

    totals       = await repo.dashboard_totais(empresa_id, dias)
    distribuicao = await repo.dashboard_distribuicao(empresa_id, dias)
    vendedores   = await repo.dashboard_vendedores(empresa_id, dias)
    baixas       = await repo.dashboard_baixas(empresa_id, dias)

    total_env  = totals["total_enviadas"] or 0
    total_resp = totals["total_respondidas"] or 0
    taxa = round((total_resp / total_env * 100), 1) if total_env else 0.0

    return {
        "total_enviadas": total_env,
        "total_respondidas": total_resp,
        "taxa_resposta": taxa,
        "media_geral": float(totals["media_geral"]) if totals["media_geral"] else None,
        "positivas": totals["positivas"] or 0,
        "negativas": totals["negativas"] or 0,
        "distribuicao": distribuicao,
        "ranking_vendedores": vendedores,
        "baixas": baixas,
    }
