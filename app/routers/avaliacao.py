import html as _html
import json as _json
import secrets
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..core.database import get_db, get_db_direct
from ..core.security import get_current_user
from ..core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["avaliacao"])


# ── HTML da página de avaliação ───────────────────────────────────────────────

def _survey_page(nome_empresa: str, token: str, vendedor: str = "", already_answered: bool = False, invalid: bool = False) -> str:
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
        vendedor_html = f'<div class="vendedor">Vendedor: <strong>{_html.escape(vendedor)}</strong></div>' if vendedor else ''
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

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Avaliação de Atendimento — {_html.escape(nome_empresa)}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    min-height: 100dvh;
    background: linear-gradient(145deg, #1a5c08 0%, #3d7f1f 40%, #7cdc44 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    padding: 1.5rem 1rem;
  }}
  .card {{
    background: #fff;
    border-radius: 24px;
    padding: 2.25rem 2rem 2rem;
    width: 100%;
    max-width: 460px;
    box-shadow: 0 20px 60px rgba(0,0,0,.25), 0 4px 16px rgba(0,0,0,.12);
    text-align: center;
    animation: fadeUp .4s ease both;
  }}
  @keyframes fadeUp {{
    from {{ opacity: 0; transform: translateY(24px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}
  @keyframes popIn {{
    0%   {{ transform: scale(.5); opacity: 0; }}
    70%  {{ transform: scale(1.2); }}
    100% {{ transform: scale(1);   opacity: 1; }}
  }}
  .icon-wrap {{
    font-size: 3.5rem;
    line-height: 1;
    margin-bottom: 1rem;
    display: block;
  }}
  .animate-in {{ animation: popIn .5s ease both .2s; }}
  .empresa-name {{
    display: inline-block;
    background: linear-gradient(90deg, #3d7f1f, #7cdc44);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    font-size: 1.1rem;
    font-weight: 800;
    letter-spacing: .02em;
    margin-bottom: .6rem;
    padding: .25rem .75rem;
    border: 2px solid #7cdc44;
    border-radius: 999px;
  }}
  h1 {{
    font-size: 1.35rem;
    font-weight: 700;
    color: #1a1d23;
    margin-bottom: .4rem;
    line-height: 1.3;
  }}
  .vendedor {{
    font-size: .85rem;
    color: #6b7280;
    margin-bottom: .4rem;
  }}
  .sub {{
    font-size: .88rem;
    color: #6b7280;
    line-height: 1.5;
    margin-bottom: 1.5rem;
  }}
  .stars {{
    display: flex;
    justify-content: center;
    gap: .4rem;
    margin-bottom: .4rem;
  }}
  .star {{
    font-size: 2.6rem;
    background: none;
    border: none;
    cursor: pointer;
    filter: grayscale(1) opacity(.35);
    transition: filter .15s, transform .15s;
    padding: .1rem .15rem;
    border-radius: 8px;
    line-height: 1;
  }}
  .star:hover, .star.active {{
    filter: grayscale(0) opacity(1);
    transform: scale(1.18);
  }}
  .star.active {{ transform: scale(1.22); }}
  .star-labels {{
    display: flex;
    justify-content: space-between;
    font-size: .68rem;
    color: #9ca3af;
    padding: 0 .25rem;
    margin-bottom: .75rem;
  }}
  .nota-label {{
    font-size: .88rem;
    font-weight: 700;
    color: #3d7f1f;
    margin-bottom: .75rem;
    min-height: 1.2em;
  }}
  textarea {{
    width: 100%;
    border: 1.5px solid #e4e6ea;
    border-radius: 12px;
    padding: .75rem 1rem;
    font-size: .88rem;
    font-family: inherit;
    color: #1a1d23;
    resize: none;
    outline: none;
    transition: border-color .15s;
    margin-bottom: 1rem;
    background: #f9fafb;
  }}
  textarea:focus {{ border-color: #7cdc44; background: #fff; }}
  .btn-send {{
    width: 100%;
    background: linear-gradient(90deg, #3d7f1f, #7cdc44);
    color: #fff;
    border: none;
    border-radius: 14px;
    padding: .9rem 1.5rem;
    font-size: 1rem;
    font-weight: 700;
    cursor: pointer;
    transition: opacity .15s, transform .1s;
    letter-spacing: .02em;
  }}
  .btn-send:disabled {{ opacity: .4; cursor: not-allowed; }}
  .btn-send:not(:disabled):hover {{ opacity: .92; transform: translateY(-1px); }}
  .btn-send:not(:disabled):active {{ transform: translateY(0); }}
  .msg-erro {{
    color: #dc2626;
    font-size: .82rem;
    margin-top: .5rem;
  }}
  .powered {{
    width: 100%;
    text-align: center;
    font-size: .7rem;
    color: rgba(255,255,255,.55);
    padding: 1rem 0 .5rem;
  }}
</style>
</head>
<body style="flex-direction:column;gap:0;padding-bottom:.5rem;">
  {body_html}
  <div class="powered">Powered by ZapDin</div>
<script>
  var _nota = 0;
  var _labels = ['', 'Péssimo 😞', 'Ruim 😕', 'Regular 😐', 'Bom 😊', 'Excelente 🤩'];
  function setStar(v) {{
    _nota = v;
    document.querySelectorAll('.star').forEach(function(s) {{
      s.classList.toggle('active', parseInt(s.dataset.v) <= v);
    }});
    var lbl = document.getElementById('nota-val');
    if (lbl) {{ lbl.textContent = _labels[v]; lbl.style.display = 'block'; }}
    var btn = document.getElementById('btnEnviar');
    if (btn) btn.disabled = false;
  }}
  function enviarAvaliacao() {{
    if (!_nota) return;
    var btn = document.getElementById('btnEnviar');
    var erro = document.getElementById('msgErro');
    btn.disabled = true;
    btn.textContent = 'Enviando…';
    if (erro) erro.style.display = 'none';
    var comentario = (document.getElementById('comentario') || {{}}).value || '';
    fetch('/api/avaliacao/responder', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{token: {_json.dumps(token)}, nota: _nota, comentario: comentario}})
    }}).then(function(r) {{ return r.json(); }}).then(function(d) {{
      if (d.ok) {{
        document.getElementById('formCard').style.display = 'none';
        document.getElementById('thanksCard').style.display = 'block';
      }} else {{
        if (erro) {{ erro.textContent = d.detail || 'Erro ao enviar. Tente novamente.'; erro.style.display = 'block'; }}
        btn.disabled = false;
        btn.textContent = 'Enviar Avaliação';
      }}
    }}).catch(function() {{
      if (erro) {{ erro.textContent = 'Erro de conexão. Verifique sua internet.'; erro.style.display = 'block'; }}
      btn.disabled = false;
      btn.textContent = 'Enviar Avaliação';
    }});
  }}
</script>
</body>
</html>"""


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
    # Nota e token já validados pelo Pydantic — campos fora do range retornam 422
    # Token DEMO → simula envio bem-sucedido sem gravar no banco
    if body.token.upper() == "DEMO":
        logger.info("[avaliacao] DEMO nota=%d (não gravado)", body.nota)
        return {"ok": True}
    async with get_db_direct() as db:
        async with db.execute(
            "SELECT id, nota FROM avaliacoes WHERE token = ?", (body.token,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return JSONResponse({"ok": False, "detail": "Token inválido."}, status_code=404)
        if row["nota"] is not None:
            return JSONResponse({"ok": False, "detail": "Avaliação já registrada."}, status_code=409)
        now = datetime.now(timezone.utc)
        await db.execute(
            "UPDATE avaliacoes SET nota = ?, comentario = ?, respondido_em = ? WHERE token = ?",
            (body.nota, body.comentario or "", now, body.token),
        )
        await db.commit()
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
    empresa_id = user["empresa_id"]
    if vendedor:
        async with db.execute(
            """SELECT id, phone, nome_cliente, vendedor, nota, comentario, created_at, respondido_em
               FROM avaliacoes
               WHERE empresa_id = ? AND created_at >= NOW() - (? * INTERVAL '1 day') AND vendedor = ?
               ORDER BY created_at DESC""",
            (empresa_id, dias, vendedor),
        ) as cur:
            rows = await cur.fetchall()
    else:
        async with db.execute(
            """SELECT id, phone, nome_cliente, vendedor, nota, comentario, created_at, respondido_em
               FROM avaliacoes
               WHERE empresa_id = ? AND created_at >= NOW() - (? * INTERVAL '1 day')
               ORDER BY created_at DESC""",
            (empresa_id, dias),
        ) as cur:
            rows = await cur.fetchall()
    result = []
    for r in rows:
        result.append({
            "id": r["id"],
            "telefone": r["phone"] or "",
            "nome": r["nome_cliente"] or "—",
            "vendedor": r["vendedor"] or "—",
            "nota": r["nota"],
            "comentario": r["comentario"] or "",
            "data": r["respondido_em"].strftime("%d/%m/%Y %H:%M") if r["respondido_em"] else (
                    r["created_at"].strftime("%d/%m/%Y") if r["created_at"] else "—"),
        })
    return result


@router.get("/api/avaliacoes/dashboard")
async def dashboard_avaliacoes(
    dias: int = 30,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    # Totals
    async with db.execute(
        """SELECT
             COUNT(*) AS total_enviadas,
             COUNT(nota) AS total_respondidas,
             ROUND(AVG(nota)::numeric, 2) AS media_geral,
             COUNT(CASE WHEN nota >= 4 THEN 1 END) AS positivas,
             COUNT(CASE WHEN nota <= 2 THEN 1 END) AS negativas
           FROM avaliacoes
           WHERE empresa_id = ? AND created_at >= NOW() - (? * INTERVAL '1 day')""",
        (empresa_id, dias),
    ) as cur:
        totals = await cur.fetchone()
    # Distribuição por nota
    async with db.execute(
        """SELECT nota, COUNT(*) AS qtd
           FROM avaliacoes
           WHERE empresa_id = ? AND nota IS NOT NULL AND created_at >= NOW() - (? * INTERVAL '1 day')
           GROUP BY nota ORDER BY nota""",
        (empresa_id, dias),
    ) as cur:
        dist_rows = await cur.fetchall()
    distribuicao = {str(r["nota"]): r["qtd"] for r in dist_rows}
    # Por vendedor
    async with db.execute(
        """SELECT vendedor, COUNT(*) AS total, COUNT(nota) AS respondidas, ROUND(AVG(nota)::numeric,2) AS media
           FROM avaliacoes
           WHERE empresa_id = ? AND vendedor != '' AND created_at >= NOW() - (? * INTERVAL '1 day')
           GROUP BY vendedor ORDER BY media DESC NULLS LAST""",
        (empresa_id, dias),
    ) as cur:
        vend_rows = await cur.fetchall()
    vendedores = [{"vendedor": r["vendedor"], "total": r["total"], "respondidas": r["respondidas"], "media": float(r["media"]) if r["media"] else None} for r in vend_rows]
    # Taxa de resposta
    total_env = totals["total_enviadas"] or 0
    total_resp = totals["total_respondidas"] or 0
    taxa = round((total_resp / total_env * 100), 1) if total_env else 0.0
    # Distribuição com chaves numéricas
    distribuicao_num = {int(k): v for k, v in distribuicao.items()}
    # Baixas notas (≤ 2) para alerta
    async with db.execute(
        """SELECT phone, nome_cliente, vendedor, nota, respondido_em
           FROM avaliacoes
           WHERE empresa_id = $1 AND nota <= 2 AND nota IS NOT NULL
             AND created_at >= NOW() - ($2 * INTERVAL '1 day')
           ORDER BY respondido_em DESC LIMIT 10""",
        (empresa_id, dias),
    ) as cur:
        baixas_rows = await cur.fetchall()
    baixas = [
        {
            "nome": r["nome_cliente"] or "—",
            "telefone": r["phone"] or "",
            "vendedor": r["vendedor"] or "",
            "nota": r["nota"],
            "data": r["respondido_em"].strftime("%d/%m/%Y") if r["respondido_em"] else "—",
        }
        for r in baixas_rows
    ]
    return {
        "total_enviadas": total_env,
        "total_respondidas": total_resp,
        "taxa_resposta": taxa,
        "media_geral": float(totals["media_geral"]) if totals["media_geral"] else None,
        "positivas": totals["positivas"] or 0,
        "negativas": totals["negativas"] or 0,
        "distribuicao": distribuicao_num,
        "ranking_vendedores": vendedores,
        "baixas": baixas,
    }
