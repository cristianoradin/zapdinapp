"""
Rotas de Disparo em Massa — Contatos e Campanhas.

Router HTTP puro: recebe requisição, delega ao repositório, retorna resposta.
Nenhuma query SQL direta aqui — toda lógica de dados está nos repositories.
"""
import asyncio
import os
import uuid
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..core.database import get_db
from ..core.security import get_current_user
from ..repositories import ContatoRepository, CampanhaRepository
from ..domain.exceptions import (
    CampanhaNaoEncontrada,
    CampanhaEmExecucao,
    SemContatosParaDisparar,
    GrupoNaoEncontrado,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/campanha", tags=["campanha"])

UPLOAD_DIR = "data/arquivos"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _eid(user: dict) -> int:
    return user["empresa_id"]


def _isoformat(d) -> Optional[str]:
    return d.isoformat() if d else None


# ─────────────────────── DTOs de entrada ────────────────────────────────────

class ContatoIn(BaseModel):
    phone: str
    nome: Optional[str] = ""


class CampanhaIn(BaseModel):
    nome: str
    tipo: str = "text"
    mensagem: Optional[str] = ""
    agendado_em: Optional[str] = None


class GrupoIn(BaseModel):
    nome: str


class GrupoContatosIn(BaseModel):
    contato_ids: List[int]


class IniciarPayload(BaseModel):
    contato_ids: Optional[List[int]] = None
    grupo_id: Optional[int] = None


# ─────────────────────── Contatos ───────────────────────────────────────────

@router.get("/contatos")
async def list_contatos(q: str = "", db=Depends(get_db), user=Depends(get_current_user)):
    repo = ContatoRepository(db)
    rows = await repo.list(_eid(user), q)
    return [dict(r) for r in rows]


@router.post("/contatos")
async def create_contato(body: ContatoIn, db=Depends(get_db), user=Depends(get_current_user)):
    phone = body.phone.strip()
    if not phone:
        raise HTTPException(400, "Telefone obrigatório")
    try:
        repo = ContatoRepository(db)
        id_ = await repo.upsert(_eid(user), phone, body.nome or "")
        await db.commit()
        return {"ok": True, "id": id_}
    except Exception as exc:
        raise HTTPException(400, str(exc))


@router.post("/contatos/importar")
async def importar_contatos(
    file: UploadFile = File(...),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    empresa_id = _eid(user)
    content = await file.read()
    text = content.decode("utf-8-sig", errors="replace")

    registros, errors = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        phone = parts[0] if parts else ""
        nome = parts[1] if len(parts) > 1 else ""
        if phone:
            registros.append((empresa_id, phone, nome))

    if registros:
        repo = ContatoRepository(db)
        try:
            await repo.upsert_batch(registros)
        except Exception:
            for reg in registros:
                try:
                    await repo.upsert(reg[0], reg[1], reg[2])
                except Exception:
                    errors += 1
        await db.commit()

    return {"ok": True, "importados": len(registros) - errors, "erros": errors}


@router.delete("/contatos/{contato_id}")
async def delete_contato(contato_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    await ContatoRepository(db).delete(_eid(user), contato_id)
    return {"ok": True}


# ─────────────────────── Grupos ─────────────────────────────────────────────

@router.get("/grupos")
async def list_grupos(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await ContatoRepository(db).list_grupos(_eid(user))
    result = []
    for r in rows:
        d = dict(r)
        d["created_at"] = _isoformat(d.get("created_at"))
        result.append(d)
    return result


@router.post("/grupos")
async def create_grupo(body: GrupoIn, db=Depends(get_db), user=Depends(get_current_user)):
    nome = body.nome.strip()
    if not nome:
        raise HTTPException(400, "Nome obrigatório")
    try:
        id_ = await ContatoRepository(db).create_grupo(_eid(user), nome)
        return {"ok": True, "id": id_, "nome": nome}
    except Exception as exc:
        raise HTTPException(400, "Grupo já existe ou erro: " + str(exc))


@router.put("/grupos/{grupo_id}")
async def update_grupo(grupo_id: int, body: GrupoIn, db=Depends(get_db), user=Depends(get_current_user)):
    nome = body.nome.strip()
    if not nome:
        raise HTTPException(400, "Nome obrigatório")
    await ContatoRepository(db).update_grupo(_eid(user), grupo_id, nome)
    return {"ok": True}


@router.delete("/grupos/{grupo_id}")
async def delete_grupo(grupo_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    await ContatoRepository(db).delete_grupo(_eid(user), grupo_id)
    return {"ok": True}


@router.get("/grupos/{grupo_id}/contatos")
async def list_grupo_contatos(grupo_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    rows = await ContatoRepository(db).list_grupo_contatos(_eid(user), grupo_id)
    return [dict(r) for r in rows]


@router.post("/grupos/{grupo_id}/contatos")
async def add_grupo_contatos(grupo_id: int, body: GrupoContatosIn, db=Depends(get_db), user=Depends(get_current_user)):
    repo = ContatoRepository(db)
    grupo = await repo.get_grupo(_eid(user), grupo_id)
    if not grupo:
        raise HTTPException(404, "Grupo não encontrado")
    added = await repo.add_contatos_ao_grupo(grupo_id, body.contato_ids)
    return {"ok": True, "adicionados": added}


@router.delete("/grupos/{grupo_id}/contatos/{contato_id}")
async def remove_grupo_contato(grupo_id: int, contato_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    await ContatoRepository(db).remove_contato_do_grupo(_eid(user), grupo_id, contato_id)
    return {"ok": True}


# ─────────────────────── Campanhas ──────────────────────────────────────────

@router.get("/dashboard")
async def dashboard_campanhas(
    campanha_id: Optional[int] = None,
    dias: int = 30,
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    empresa_id = _eid(user)
    repo = CampanhaRepository(db)

    smap = await repo.count_envios_by_status(empresa_id, campanha_id)
    enviados  = smap.get("sent",   0)
    falhas    = smap.get("failed", 0)
    na_fila   = smap.get("queued", 0) + smap.get("paused", 0)
    total_env = enviados + falhas + na_fila
    taxa_suc  = round(enviados / total_env * 100, 1) if total_env else 0.0

    contatos_unicos = await repo.contatos_unicos(empresa_id, campanha_id)
    por_hora        = await repo.dashboard_por_hora(empresa_id, campanha_id)
    por_dia         = await repo.dashboard_por_dia(empresa_id, dias, campanha_id)
    top_contatos    = await repo.dashboard_top_contatos(empresa_id, campanha_id)
    campanhas_dash  = await repo.dashboard_campanhas(empresa_id, campanha_id)

    durs = [c["duracao_min"] for c in campanhas_dash if c.get("duracao_min") is not None and c["status"] == "done"]
    duracao_media = round(sum(durs) / len(durs), 1) if durs else None

    return {
        "resumo": {
            "total_enviados": enviados,
            "total_falhas": falhas,
            "na_fila": na_fila,
            "total_mensagens": total_env,
            "taxa_sucesso": taxa_suc,
            "contatos_unicos": contatos_unicos,
            "total_campanhas": len(campanhas_dash),
            "duracao_media_min": duracao_media,
        },
        "por_hora": por_hora,
        "por_dia": por_dia,
        "top_contatos": top_contatos,
        "campanhas": campanhas_dash,
    }


@router.get("")
async def list_campanhas(status: Optional[str] = None, db=Depends(get_db), user=Depends(get_current_user)):
    rows = await CampanhaRepository(db).list(_eid(user), status)
    result = []
    for r in rows:
        d = dict(r)
        for k in ("created_at", "started_at", "done_at", "agendado_em"):
            d[k] = _isoformat(d.get(k))
        result.append(d)
    return result


@router.post("")
async def create_campanha(body: CampanhaIn, db=Depends(get_db), user=Depends(get_current_user)):
    agendado_em = None
    status = "draft"
    if body.agendado_em:
        try:
            agendado_em = datetime.fromisoformat(body.agendado_em.replace("Z", "+00:00"))
            status = "scheduled"
        except Exception:
            pass
    id_ = await CampanhaRepository(db).create(
        _eid(user), body.nome.strip(), body.tipo, body.mensagem or "", status, agendado_em
    )
    return {"ok": True, "id": id_}


@router.delete("/{campanha_id}")
async def delete_campanha(campanha_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    repo = CampanhaRepository(db)
    await repo.delete_envios(campanha_id)
    nomes_arq = await repo.delete_todos_arquivos(campanha_id)
    for nome in nomes_arq:
        try:
            os.remove(os.path.join(UPLOAD_DIR, nome))
        except Exception:
            pass
    await repo.delete(_eid(user), campanha_id)
    return {"ok": True}


# ── Arquivos ─────────────────────────────────────────────────────────────────

@router.post("/{campanha_id}/arquivo")
async def upload_campanha_arquivo(
    campanha_id: int,
    file: UploadFile = File(...),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    repo = CampanhaRepository(db)
    camp = await repo.get(_eid(user), campanha_id)
    if not camp:
        raise HTTPException(404, "Campanha não encontrada")

    ext = os.path.splitext(file.filename or "")[-1]
    nome_arquivo = f"camp_{uuid.uuid4().hex}{ext}"
    content = await file.read()
    with open(os.path.join(UPLOAD_DIR, nome_arquivo), "wb") as f:
        f.write(content)

    await repo.add_arquivo(campanha_id, file.filename, nome_arquivo)
    return {"ok": True, "nome_original": file.filename, "nome_arquivo": nome_arquivo}


@router.get("/{campanha_id}/arquivos")
async def list_campanha_arquivos(campanha_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    rows = await CampanhaRepository(db).list_arquivos(_eid(user), campanha_id)
    return [dict(r) for r in rows]


@router.delete("/{campanha_id}/arquivo/{arq_id}")
async def delete_campanha_arquivo(campanha_id: int, arq_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    repo = CampanhaRepository(db)
    row = await repo.get_arquivo(_eid(user), campanha_id, arq_id)
    if row:
        try:
            os.remove(os.path.join(UPLOAD_DIR, row["nome_arquivo"]))
        except Exception:
            pass
        await repo.delete_arquivo(arq_id)
    return {"ok": True}


# ── Iniciar / Pausar ─────────────────────────────────────────────────────────

@router.post("/{campanha_id}/iniciar")
async def iniciar_campanha(
    campanha_id: int,
    body: IniciarPayload = IniciarPayload(),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    empresa_id = _eid(user)
    camp_repo    = CampanhaRepository(db)
    contato_repo = ContatoRepository(db)

    camp = await camp_repo.get(empresa_id, campanha_id)
    if not camp:
        raise HTTPException(404, "Campanha não encontrada")
    if camp["status"] == "running":
        raise HTTPException(400, "Campanha já em execução")

    if camp["status"] in ("draft", "done", "scheduled"):
        await camp_repo.delete_envios(campanha_id)

        if body.grupo_id:
            contatos = await contato_repo.list_grupo_contatos_ativos(body.grupo_id, empresa_id)
        elif body.contato_ids:
            contatos = await contato_repo.list_by_ids(empresa_id, body.contato_ids)
        else:
            contatos = await contato_repo.list_ativos(empresa_id)

        if not contatos:
            raise HTTPException(400, "Nenhum contato selecionado para disparar")

        await camp_repo.create_envios_batch(campanha_id, empresa_id, contatos)
        await camp_repo.iniciar(campanha_id, len(contatos))
    else:
        await camp_repo.retomar_envios_pausados(campanha_id)
        await camp_repo.update_status(campanha_id, "running")

    await db.commit()
    return {"ok": True}


@router.post("/{campanha_id}/pausar")
async def pausar_campanha(campanha_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    repo = CampanhaRepository(db)
    await repo.pausar_envios(campanha_id)
    await repo.update_status(campanha_id, "paused")
    return {"ok": True}


@router.get("/{campanha_id}/progresso")
async def campanha_progresso(campanha_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    row = await CampanhaRepository(db).progresso(_eid(user), campanha_id)
    if not row:
        raise HTTPException(404, "Campanha não encontrada")
    return dict(row)


# ── Status do worker ─────────────────────────────────────────────────────────

@router.get("/queue/status")
async def queue_status(db=Depends(get_db), user=Depends(get_current_user)):
    from ..services import queue_worker
    from ..repositories import MensagemRepository
    empresa_id = _eid(user)

    msg_map  = await MensagemRepository(db).count_by_status(empresa_id)
    camp_map = await CampanhaRepository(db).count_envios_by_status(empresa_id)

    async with db.execute(
        "SELECT status, COUNT(*) as cnt FROM arquivos WHERE empresa_id=? GROUP BY status",
        (empresa_id,),
    ) as cur:
        arq_rows = await cur.fetchall()
    arq_map = {r["status"]: r["cnt"] for r in arq_rows}

    return {
        "worker": queue_worker.worker_status(),
        "mensagens": msg_map,
        "arquivos": arq_map,
        "campanha_envios": camp_map,
    }


@router.post("/queue/restart")
async def queue_restart(user=Depends(get_current_user)):
    from ..services import queue_worker
    queue_worker.stop()
    await asyncio.sleep(0.5)
    queue_worker.start()
    return {"ok": True, "status": queue_worker.worker_status()}
