"""
app/routers/home_router.py — Home Dashboard.

Endpoints:
  GET  /api/home/clima          — clima atual + previsão 3 dias
  GET  /api/home/cidade         — retorna cidade/uf da config
  POST /api/home/cidade         — salva cidade/uf na config
  GET  /api/home/agenda         — lista compromissos do mês
  POST /api/home/agenda         — cria compromisso
  PUT  /api/home/agenda/{id}    — atualiza compromisso
  DELETE /api/home/agenda/{id}  — deleta compromisso
  GET  /api/home/postits        — lista post-its do usuário
  POST /api/home/postits        — cria post-it
  PUT  /api/home/postits/{id}   — atualiza post-it
  DELETE /api/home/postits/{id} — deleta post-it
  GET  /api/home/recados        — busca recados do Monitor
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.config import settings
from ..core.database import get_db
from ..core.security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/home", tags=["home"])

# ── Cache de clima (30 min) ───────────────────────────────────────────────────
_clima_cache: dict = {}  # key → (timestamp, data)
_CLIMA_TTL = 1800  # 30 min

_WEATHERCODE_DESC = {
    0: "Céu limpo", 1: "Poucas nuvens", 2: "Parcialmente nublado", 3: "Nublado",
    45: "Neblina", 48: "Neblina com gelo",
    51: "Garoa leve", 53: "Garoa", 55: "Garoa intensa",
    61: "Chuva leve", 63: "Chuva", 65: "Chuva forte",
    71: "Neve leve", 73: "Neve", 75: "Neve intensa",
    80: "Pancadas", 81: "Pancadas moderadas", 82: "Pancadas fortes",
    95: "Tempestade", 96: "Tempestade com granizo", 99: "Tempestade severa",
}


def _eid(user: dict) -> int:
    return user["empresa_id"]


def _uid(user: dict) -> int:
    return user["uid"]


# ── Clima ─────────────────────────────────────────────────────────────────────

@router.get("/clima")
async def get_clima(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    eid = _eid(user)
    cache_key = f"clima_{eid}"
    now = time.time()

    # Retorna do cache se ainda válido
    if cache_key in _clima_cache:
        ts, data = _clima_cache[cache_key]
        if now - ts < _CLIMA_TTL:
            return data

    # Busca cidade configurada
    cidade, uf = None, None
    async with db.execute(
        "SELECT key, value FROM config WHERE empresa_id=? AND key IN ('empresa_cidade','empresa_uf')",
        (eid,),
    ) as cur:
        rows = await cur.fetchall()
    for r in rows:
        if r["key"] == "empresa_cidade":
            cidade = r["value"]
        elif r["key"] == "empresa_uf":
            uf = r["value"]

    if not cidade:
        raise HTTPException(status_code=404, detail="Cidade não configurada")

    async with httpx.AsyncClient(timeout=10) as client:
        # Geocodifica
        geo_resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{cidade},{uf or 'Brasil'}", "format": "json", "limit": 1},
            headers={"User-Agent": "ZapDin/2.0 (cristiano@zapdin.com.br)"},
        )
        geo = geo_resp.json()
        if not geo:
            raise HTTPException(status_code=502, detail="Cidade não encontrada no geocoder")
        lat = float(geo[0]["lat"])
        lon = float(geo[0]["lon"])

        # Open-Meteo
        meteo_resp = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weathercode,windspeed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,weathercode",
                "timezone": "America/Sao_Paulo",
                "forecast_days": 3,
            },
        )
        meteo = meteo_resp.json()

    current = meteo.get("current", {})
    daily = meteo.get("daily", {})

    codigo = current.get("weathercode", 0)
    previsao = []
    dates = daily.get("time", [])
    maxs = daily.get("temperature_2m_max", [])
    mins = daily.get("temperature_2m_min", [])
    codes = daily.get("weathercode", [])
    for i in range(min(3, len(dates))):
        previsao.append({
            "data": dates[i],
            "max": maxs[i] if i < len(maxs) else None,
            "min": mins[i] if i < len(mins) else None,
            "codigo": codes[i] if i < len(codes) else 0,
        })

    result = {
        "cidade": cidade,
        "uf": uf,
        "temperatura": current.get("temperature_2m"),
        "umidade": current.get("relative_humidity_2m"),
        "codigo_clima": codigo,
        "vento": current.get("windspeed_10m"),
        "descricao_clima": _WEATHERCODE_DESC.get(codigo, "—"),
        "previsao": previsao,
    }
    _clima_cache[cache_key] = (now, result)
    return result


# ── Cidade ────────────────────────────────────────────────────────────────────

@router.get("/cidade")
async def get_cidade(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    eid = _eid(user)
    cidade, uf = None, None
    async with db.execute(
        "SELECT key, value FROM config WHERE empresa_id=? AND key IN ('empresa_cidade','empresa_uf')",
        (eid,),
    ) as cur:
        rows = await cur.fetchall()
    for r in rows:
        if r["key"] == "empresa_cidade":
            cidade = r["value"]
        elif r["key"] == "empresa_uf":
            uf = r["value"]
    return {"cidade": cidade, "uf": uf}


class CidadePayload(BaseModel):
    cidade: str
    uf: Optional[str] = ""


@router.post("/cidade")
async def save_cidade(
    payload: CidadePayload,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    eid = _eid(user)
    for key, val in [("empresa_cidade", payload.cidade), ("empresa_uf", payload.uf or "")]:
        await db.execute(
            "INSERT INTO config(empresa_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(empresa_id,key) DO UPDATE SET value=EXCLUDED.value",
            (eid, key, val),
        )
    await db.commit()
    # Invalida cache
    _clima_cache.pop(f"clima_{eid}", None)
    return {"ok": True}


# ── Agenda ────────────────────────────────────────────────────────────────────

class AgendaPayload(BaseModel):
    data: str  # YYYY-MM-DD — convertido para date no endpoint

    @property
    def data_date(self):
        from datetime import date as _date
        return _date.fromisoformat(self.data)
    hora_inicio: Optional[str] = None
    hora_fim: Optional[str] = None
    titulo: str
    descricao: Optional[str] = None
    cor: Optional[str] = "#3d7f1f"


@router.get("/agenda")
async def list_agenda(
    mes: str = "",  # YYYY-MM
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    from datetime import date as _date
    eid = _eid(user)
    uid = _uid(user)
    if mes:
        ano, m = mes.split("-")
        m_int = int(m)
        inicio = _date(int(ano), m_int, 1)
        if m_int == 12:
            fim = _date(int(ano) + 1, 1, 1)
        else:
            fim = _date(int(ano), m_int + 1, 1)
        async with db.execute(
            "SELECT * FROM agenda_compromissos "
            "WHERE empresa_id=? AND usuario_id=? AND data >= ? AND data < ? "
            "ORDER BY data, hora_inicio",
            (eid, uid, inicio, fim),
        ) as cur:
            rows = await cur.fetchall()
    else:
        async with db.execute(
            "SELECT * FROM agenda_compromissos WHERE empresa_id=? AND usuario_id=? ORDER BY data, hora_inicio",
            (eid, uid),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.post("/agenda")
async def create_agenda(
    payload: AgendaPayload,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    eid = _eid(user)
    uid = _uid(user)
    cur = await db.execute(
        "INSERT INTO agenda_compromissos(empresa_id,usuario_id,data,hora_inicio,hora_fim,titulo,descricao,cor) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (eid, uid, payload.data_date, payload.hora_inicio, payload.hora_fim,
         payload.titulo, payload.descricao, payload.cor or "#3d7f1f"),
    )
    await db.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.put("/agenda/{item_id}")
async def update_agenda(
    item_id: int,
    payload: AgendaPayload,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    eid = _eid(user)
    uid = _uid(user)
    await db.execute(
        "UPDATE agenda_compromissos SET data=?,hora_inicio=?,hora_fim=?,titulo=?,descricao=?,cor=? "
        "WHERE id=? AND empresa_id=? AND usuario_id=?",
        (payload.data_date, payload.hora_inicio, payload.hora_fim, payload.titulo,
         payload.descricao, payload.cor or "#3d7f1f", item_id, eid, uid),
    )
    await db.commit()
    return {"ok": True}


@router.delete("/agenda/{item_id}")
async def delete_agenda(
    item_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    eid = _eid(user)
    uid = _uid(user)
    await db.execute(
        "DELETE FROM agenda_compromissos WHERE id=? AND empresa_id=? AND usuario_id=?",
        (item_id, eid, uid),
    )
    await db.commit()
    return {"ok": True}


# ── Post-its ──────────────────────────────────────────────────────────────────

class PostitPayload(BaseModel):
    titulo: Optional[str] = ""
    conteudo: Optional[str] = ""
    cor: Optional[str] = "#fef08a"


@router.get("/postits")
async def list_postits(
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    eid = _eid(user)
    uid = _uid(user)
    async with db.execute(
        "SELECT * FROM postits WHERE empresa_id=? AND usuario_id=? ORDER BY ordem, created_at",
        (eid, uid),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.post("/postits")
async def create_postit(
    payload: PostitPayload,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    eid = _eid(user)
    uid = _uid(user)
    cur = await db.execute(
        "INSERT INTO postits(empresa_id,usuario_id,titulo,conteudo,cor) VALUES(?,?,?,?,?)",
        (eid, uid, payload.titulo or "", payload.conteudo or "", payload.cor or "#fef08a"),
    )
    await db.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.put("/postits/{postit_id}")
async def update_postit(
    postit_id: int,
    payload: PostitPayload,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    eid = _eid(user)
    uid = _uid(user)
    await db.execute(
        "UPDATE postits SET titulo=?,conteudo=?,cor=?,updated_at=NOW() "
        "WHERE id=? AND empresa_id=? AND usuario_id=?",
        (payload.titulo or "", payload.conteudo or "", payload.cor or "#fef08a",
         postit_id, eid, uid),
    )
    await db.commit()
    return {"ok": True}


@router.delete("/postits/{postit_id}")
async def delete_postit(
    postit_id: int,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    eid = _eid(user)
    uid = _uid(user)
    await db.execute(
        "DELETE FROM postits WHERE id=? AND empresa_id=? AND usuario_id=?",
        (postit_id, eid, uid),
    )
    await db.commit()
    return {"ok": True}


# ── Recados (busca do Monitor) ────────────────────────────────────────────────

@router.get("/recados")
async def get_recados(
    user: dict = Depends(get_current_user),
):
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                f"{settings.monitor_url}/api/recados/lista",
                json={"client_token": settings.monitor_client_token},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning("[home/recados] Falha ao buscar recados do Monitor: %s", exc)
    return []
