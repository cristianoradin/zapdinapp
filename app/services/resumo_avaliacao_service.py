"""
app/services/resumo_avaliacao_service.py — Resumo diário de avaliações.

Envia (por WhatsApp, pros destinos 'avaliacao' do Alerta Crítico) um resumo
das avaliações da empresa, no horário configurado por empresa.

Config (tabela config, por empresa):
  resumo_aval_ativo    '1'/'0'            (default '0')
  resumo_aval_hora     'HH:MM'            (default '08:00', fuso America/Sao_Paulo)
  resumo_aval_periodo  'ontem'|'hoje'|'7dias' (default 'ontem')
  resumo_aval_ultimo   'YYYY-MM-DD'       (controle interno: último dia enviado)

Loop verifica de minuto em minuto: se ativo, hora já passou e ainda não enviou
hoje → monta e envia, grava resumo_aval_ultimo. Catch-up: se o app subiu depois
da hora, envia no 1º tick (uma vez por dia).
"""
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import alerta_service

logger = logging.getLogger(__name__)
_TZ = ZoneInfo("America/Sao_Paulo")
_task = None


def _bounds(periodo: str):
    """Retorna (inicio_iso, fim_iso, label) conforme o período (fuso BR)."""
    agora = datetime.now(_TZ)
    hoje0 = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    if periodo == "hoje":
        ini, fim, label = hoje0, agora, "hoje"
    elif periodo == "7dias":
        ini, fim, label = (agora - timedelta(days=7)), agora, "últimos 7 dias"
    else:  # ontem (default)
        ini, fim, label = (hoje0 - timedelta(days=1)), hoje0, "ontem"
    return ini, fim, label  # datetime (asyncpg exige datetime, não string ISO)


def _estrelas(n) -> str:
    try:
        n = int(round(float(n)))
    except (TypeError, ValueError):
        return "—"
    return "⭐" * max(1, min(5, n))


async def montar_resumo(empresa_id: int, periodo: str) -> str | None:
    """Monta o texto do resumo (completo). Retorna None se não houve avaliações."""
    from ..core.database import get_db_direct
    ini, fim, label = _bounds(periodo)
    async with get_db_direct() as db:
        async with db.execute(
            "SELECT COUNT(*) AS total, COUNT(nota) AS resp, "
            "ROUND(AVG(nota)::numeric,2) AS media, "
            "COUNT(CASE WHEN nota>=4 THEN 1 END) AS pos, "
            "COUNT(CASE WHEN nota<=2 THEN 1 END) AS neg "
            "FROM avaliacoes WHERE empresa_id=? AND created_at >= ? AND created_at < ?",
            (empresa_id, ini, fim),
        ) as cur:
            t = await cur.fetchone()
        async with db.execute(
            "SELECT vendedor, COUNT(nota) AS resp, ROUND(AVG(nota)::numeric,2) AS media "
            "FROM avaliacoes WHERE empresa_id=? AND nota IS NOT NULL "
            "AND created_at >= ? AND created_at < ? "
            "GROUP BY vendedor ORDER BY media DESC NULLS LAST, resp DESC",
            (empresa_id, ini, fim),
        ) as cur:
            vendedores = await cur.fetchall()
        async with db.execute(
            "SELECT nome_cliente, vendedor, nota, comentario FROM avaliacoes "
            "WHERE empresa_id=? AND nota IS NOT NULL AND nota<=2 "
            "AND created_at >= ? AND created_at < ? ORDER BY nota ASC, created_at DESC LIMIT 10",
            (empresa_id, ini, fim),
        ) as cur:
            baixas = await cur.fetchall()

    total = (t["total"] if t else 0) or 0
    if total == 0:
        return None

    resp = (t["resp"] or 0)
    media = t["media"]
    pos = (t["pos"] or 0)
    neg = (t["neg"] or 0)
    pct = round(resp * 100 / total) if total else 0

    linhas = [
        f"📊 *Resumo de Avaliações — {label}*",
        "",
        f"📤 Enviadas: *{total}*",
        f"✅ Respondidas: *{resp}* ({pct}%)",
        f"⭐ Média geral: *{media if media is not None else '—'}*",
        f"👍 Positivas (4-5): *{pos}*",
        f"👎 Negativas (1-2): *{neg}*",
    ]

    vend_validos = [v for v in vendedores if (v["vendedor"] or "").strip() and v["media"] is not None]
    if vend_validos:
        linhas.append("")
        linhas.append("🏆 *Vendedores*")
        for v in vend_validos[:10]:
            linhas.append(f"• {v['vendedor']}: {v['media']}⭐ ({v['resp']} resp.)")

    if baixas:
        linhas.append("")
        linhas.append("⚠️ *Notas baixas*")
        for b in baixas:
            nome = (b["nome_cliente"] or "Cliente").strip()
            vend = (b["vendedor"] or "").strip()
            com = (b["comentario"] or "").strip()
            extra = f' — "{com}"' if com else ""
            vtxt = f" (vend. {vend})" if vend else ""
            linhas.append(f"• {nome}: {b['nota']}⭐{vtxt}{extra}")

    return "\n".join(linhas)


async def enviar_resumo(empresa_id: int, periodo: str = "ontem") -> bool:
    """Monta e envia o resumo pros destinos 'avaliacao'. Retorna True se enviou."""
    cfg_alerta = await alerta_service._get_alerta_cfg(empresa_id)
    destinos = alerta_service.destinos_por_tipo(cfg_alerta, "avaliacao")
    if not destinos:
        logger.info("[resumo-aval] empresa=%s sem destinos 'avaliacao' — pulando", empresa_id)
        return False
    texto = await montar_resumo(empresa_id, periodo)
    if not texto:
        logger.info("[resumo-aval] empresa=%s sem avaliações no período — nada a enviar", empresa_id)
        return False
    await alerta_service.enviar_para_numeros(empresa_id, destinos, texto)
    logger.info("[resumo-aval] empresa=%s resumo enviado p/ %s número(s)", empresa_id, len(destinos))
    return True


async def _set_ultimo(empresa_id: int, dia_iso: str) -> None:
    from ..core.database import get_db_direct
    async with get_db_direct() as db:
        await db.execute(
            "INSERT INTO config (empresa_id, key, value) VALUES (?, 'resumo_aval_ultimo', ?) "
            "ON CONFLICT (empresa_id, key) DO UPDATE SET value = EXCLUDED.value",
            (empresa_id, dia_iso),
        )
        await db.commit()


async def _check_resumos() -> None:
    """Verifica todas as empresas; envia as que estão na hora e ainda não enviaram hoje."""
    from ..core.database import get_db_direct
    agora = datetime.now(_TZ)
    hoje = agora.date().isoformat()
    nowhm = agora.strftime("%H:%M")
    async with get_db_direct() as db:
        async with db.execute(
            "SELECT empresa_id, key, value FROM config WHERE key IN "
            "('resumo_aval_ativo','resumo_aval_hora','resumo_aval_periodo','resumo_aval_ultimo')"
        ) as cur:
            rows = await cur.fetchall()
    porempresa: dict = {}
    for r in rows:
        porempresa.setdefault(r["empresa_id"], {})[r["key"]] = r["value"]
    for eid, c in porempresa.items():
        if (c.get("resumo_aval_ativo") or "0") != "1":
            continue
        hora = (c.get("resumo_aval_hora") or "08:00")[:5]
        if nowhm < hora:
            continue
        if (c.get("resumo_aval_ultimo") or "") == hoje:
            continue
        periodo = c.get("resumo_aval_periodo") or "ontem"
        try:
            await enviar_resumo(eid, periodo)
        except Exception as exc:
            logger.warning("[resumo-aval] empresa=%s erro ao enviar: %s", eid, exc)
        # grava mesmo se não enviou (0 avaliações / sem destino) → não retenta o dia todo
        await _set_ultimo(eid, hoje)


async def _loop() -> None:
    await asyncio.sleep(90)  # espera boot estabilizar
    while True:
        try:
            await _check_resumos()
        except Exception as exc:
            logger.warning("[resumo-aval] loop erro: %s", exc)
        await asyncio.sleep(60)


def start() -> None:
    """Inicia o loop do resumo diário (idempotente)."""
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_loop())
    logger.info("[resumo-aval] agendador iniciado")
