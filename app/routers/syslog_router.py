"""
syslog_router.py — Endpoints para consulta do log do sistema.

GET  /api/syslog          — lista logs com filtros
GET  /api/syslog/export   — exporta CSV
DELETE /api/syslog        — limpa logs antigos (> 30 dias)
POST /api/syslog/teste    — grava evento de teste
"""
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.log_service import log_event

router = APIRouter(prefix="/api/syslog", tags=["syslog"])


@router.get("")
async def list_logs(
    nivel: str = Query("", description="info|warn|error|critical"),
    modulo: str = Query("", description="whatsapp|ia|erp|..."),
    busca: str = Query("", description="texto livre"),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    where = ["(empresa_id = $1 OR empresa_id IS NULL)"]
    params: list = [empresa_id]
    idx = 2
    if nivel:
        where.append(f"nivel = ${idx}"); params.append(nivel); idx += 1
    if modulo:
        where.append(f"modulo = ${idx}"); params.append(modulo); idx += 1
    if busca:
        where.append(f"(mensagem ILIKE ${idx} OR acao ILIKE ${idx} OR detalhe ILIKE ${idx})")
        params.append(f"%{busca}%"); idx += 1

    where_sql = " AND ".join(where)
    total = await db.fetchval(f"SELECT COUNT(*) FROM system_logs WHERE {where_sql}", *params)
    rows = await db.fetch(
        f"""SELECT id, empresa_id, nivel, modulo, acao, mensagem, detalhe, created_at
            FROM system_logs WHERE {where_sql}
            ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}""",
        *params, limit, offset,
    )
    return {"total": total, "offset": offset, "limit": limit, "logs": [dict(r) for r in rows]}


@router.get("/export")
async def export_csv(
    nivel: str = Query(""),
    modulo: str = Query(""),
    busca: str = Query(""),
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    where = ["(empresa_id = $1 OR empresa_id IS NULL)"]
    params: list = [empresa_id]
    idx = 2
    if nivel:
        where.append(f"nivel = ${idx}"); params.append(nivel); idx += 1
    if modulo:
        where.append(f"modulo = ${idx}"); params.append(modulo); idx += 1
    if busca:
        where.append(f"(mensagem ILIKE ${idx} OR acao ILIKE ${idx})")
        params.append(f"%{busca}%"); idx += 1

    rows = await db.fetch(
        f"""SELECT created_at, nivel, modulo, acao, mensagem, detalhe
            FROM system_logs WHERE {" AND ".join(where)}
            ORDER BY created_at DESC LIMIT 5000""",
        *params,
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Data/Hora", "Nível", "Módulo", "Ação", "Mensagem", "Detalhe"])
    for r in rows:
        w.writerow([r["created_at"].isoformat(), r["nivel"], r["modulo"],
                    r["acao"], r["mensagem"], r["detalhe"] or ""])
    buf.seek(0)
    filename = f"zapdin_log_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.delete("")
async def clear_old_logs(
    dias: int = Query(30, ge=1, le=365),
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    deleted = await db.fetchval(
        "DELETE FROM system_logs WHERE created_at < NOW() - ($1 || ' days')::INTERVAL RETURNING id",
        str(dias),
    )
    return {"deleted": deleted or 0}


@router.post("/teste")
async def log_teste(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await log_event(empresa_id=user["empresa_id"], nivel="info", modulo="sistema",
                    acao="log_teste", mensagem="Evento de teste gravado pelo usuário")
    return {"ok": True}
