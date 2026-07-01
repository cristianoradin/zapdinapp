"""
qr_connect.py — Link DINÂMICO de conexão do WhatsApp.

Gera um link temporário por posto (assinado + expira). A pessoa abre → página mostra
o QR AO VIVO, atualizando sozinho (acompanha a rotação do WhatsApp) → escaneia →
conecta. Sem ninguém gerar QR na mão.

Fluxo:
  POST /api/admin/qr-link  {empresa_id}  (X-Monitor-Token) → { url }   ← monitor gera
  GET  /conectar/{token}                 → página HTML (QR vivo)         ← pessoa abre
  GET  /api/qr-live/{token}              → { state, qr }                 ← poll do JS

Segurança: token assinado (SECRET_KEY) + TTL 30min + 1 empresa. Não é QR eterno.
"""
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

from ..core.config import settings
from ..services import agent_bridge

router = APIRouter(tags=["qr-connect"])

_ser = URLSafeTimedSerializer(settings.secret_key, salt="qr-connect")
_TTL = 30 * 60  # 30 minutos


def _make_token(empresa_id: int) -> str:
    return _ser.dumps({"e": int(empresa_id)})


def _verify(token: str) -> int:
    try:
        data = _ser.loads(token, max_age=_TTL)
    except SignatureExpired:
        raise HTTPException(410, "Link expirado. Peça um novo.")
    except BadSignature:
        raise HTTPException(403, "Link inválido.")
    return int(data["e"])


class QrLinkBody(BaseModel):
    empresa_id: Optional[int] = None
    client_token: Optional[str] = None   # o monitor tem o token, não o empresa_id do app


@router.post("/api/admin/qr-link")
async def gerar_qr_link(body: QrLinkBody, request: Request,
                        x_monitor_token: Optional[str] = Header(default=None, alias="X-Monitor-Token")):
    """Gera o link dinâmico de conexão. Auth X-Monitor-Token. Aceita empresa_id OU
    client_token (resolve a empresa)."""
    if not settings.monitor_client_token or x_monitor_token != settings.monitor_client_token:
        raise HTTPException(401, "X-Monitor-Token inválido")
    empresa_id = body.empresa_id
    if empresa_id is None and body.client_token:
        from ..core import database as _dbm
        pool = _dbm._pool
        empresa_id = await agent_bridge._resolve_empresa_by_token(pool, body.client_token) if pool else None
    if not empresa_id:
        raise HTTPException(404, "empresa não resolvida (empresa_id ou client_token)")
    tok = _make_token(empresa_id)
    base = str(request.base_url).rstrip("/")
    return {"ok": True, "url": f"{base}/conectar/{tok}", "ttl_min": _TTL // 60}


@router.get("/api/qr-live/{token}")
async def qr_live(token: str):
    """Poll do QR ao vivo (chamado pela página). Devolve {state, qr}."""
    empresa_id = _verify(token)
    if not agent_bridge.has_agent(empresa_id):
        return {"state": "offline"}
    from ..main import sio
    try:
        res = await agent_bridge.send_command(sio, empresa_id, "get_qr", {"instance": "x"}, timeout=90.0)
        st = (res or {}).get("state", "loading")
        return {"state": st, "qr": (res or {}).get("qr", "")}
    except Exception as exc:
        return {"state": "erro", "error": str(exc)}


@router.get("/conectar/{token}", response_class=HTMLResponse)
async def conectar_page(token: str):
    _verify(token)   # valida antes de servir (senão 403/410)
    return HTMLResponse(_PAGE.replace("__TOKEN__", token))


_PAGE = """<!doctype html><html lang="pt-br"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conectar WhatsApp — ZapDin</title>
<style>
  :root{--accent:#3d7f1f;--accent2:#7cdc44;--bg:#f4f6f9;--txt:#1a1d23;--muted:#6b7280}
  *{box-sizing:border-box}
  body{margin:0;font-family:Inter,system-ui,Arial,sans-serif;background:var(--bg);color:var(--txt);
       display:flex;min-height:100vh;align-items:center;justify-content:center;padding:16px}
  .card{background:#fff;border-radius:18px;box-shadow:0 10px 40px -12px rgba(0,0,0,.18);
        max-width:420px;width:100%;padding:28px;text-align:center}
  h1{font-size:20px;margin:0 0 4px}
  .sub{color:var(--muted);font-size:13.5px;margin-bottom:18px}
  .qrbox{width:280px;height:280px;margin:0 auto;border-radius:14px;background:#fff;
         border:1px solid #e4e6ea;display:flex;align-items:center;justify-content:center;overflow:hidden}
  .qrbox img{width:100%;height:100%;display:block}
  .spin{width:44px;height:44px;border:4px solid #e4e6ea;border-top-color:var(--accent);
        border-radius:50%;animation:r 1s linear infinite}
  @keyframes r{to{transform:rotate(360deg)}}
  .msg{margin-top:16px;font-size:14px;min-height:20px}
  .ok{color:var(--accent);font-weight:700;font-size:18px}
  .steps{text-align:left;color:var(--muted);font-size:12.5px;margin-top:16px;line-height:1.7}
  .badge{display:inline-block;background:linear-gradient(90deg,var(--accent),var(--accent2));
         color:#fff;font-size:11px;font-weight:700;padding:3px 10px;border-radius:999px;margin-bottom:12px}
</style></head><body>
<div class="card">
  <span class="badge">ZapDin</span>
  <h1>Conectar WhatsApp</h1>
  <div class="sub">Escaneie o código abaixo no seu WhatsApp</div>
  <div class="qrbox" id="box"><div class="spin"></div></div>
  <div class="msg" id="msg">Gerando código…</div>
  <div class="steps">
    1. Abra o <b>WhatsApp</b> no celular do posto<br>
    2. Toque em <b>⋮ / Configurações → Aparelhos conectados</b><br>
    3. <b>Conectar um aparelho</b> → aponte pro código
  </div>
</div>
<script>
const TOKEN="__TOKEN__";
const box=document.getElementById('box'), msg=document.getElementById('msg');
let done=false;
async function tick(){
  if(done) return;
  try{
    const r=await fetch('/api/qr-live/'+TOKEN);
    const d=await r.json();
    if(d.state==='open'){ done=true; box.innerHTML='✅'; box.style.fontSize='90px';
      msg.innerHTML='<span class="ok">Conectado!</span><br>Já pode fechar esta página.'; return; }
    if(d.state==='offline'){ box.innerHTML='<div class="spin"></div>';
      msg.textContent='Agente do posto offline. Verifique se o computador está ligado.'; return; }
    if(d.qr){ box.innerHTML='<img src="'+d.qr+'" alt="QR">';
      msg.textContent='Escaneie agora (o código atualiza sozinho).'; }
    else { box.innerHTML='<div class="spin"></div>'; msg.textContent='Gerando código…'; }
  }catch(e){ msg.textContent='Reconectando…'; }
}
tick(); setInterval(tick, 18000);
</script></body></html>"""
