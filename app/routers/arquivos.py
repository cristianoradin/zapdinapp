import mimetypes
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..core.database import get_db
from ..core.security import get_current_user

router = APIRouter(prefix="/api/arquivos", tags=["arquivos"])

UPLOAD_DIR = "data/arquivos"


@router.get("")
async def list_arquivos(
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    empresa_id = user["empresa_id"]
    async with db.execute(
        """SELECT id, nome_original, tamanho, destinatario, status,
                  created_at, sent_at, delivered_at, read_at
           FROM arquivos
           WHERE empresa_id=?
           ORDER BY created_at DESC LIMIT 100""",
        (empresa_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


@router.get("/{arquivo_id}")
async def get_arquivo_meta(
    arquivo_id: int,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Metadata + caption (mensagem). Retorna info pra preview sem baixar conteúdo."""
    empresa_id = user["empresa_id"]
    async with db.execute(
        """SELECT id, nome_original, nome_arquivo, tamanho, destinatario,
                  nome_destinatario, status, caption,
                  created_at, sent_at, delivered_at, read_at
           FROM arquivos
           WHERE id=? AND empresa_id=?""",
        (arquivo_id, empresa_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    r = dict(row)
    r["has_file"] = bool(r.get("nome_arquivo"))
    mime, _ = mimetypes.guess_type(r.get("nome_original") or "")
    r["mime"] = mime or "application/octet-stream"
    return r


@router.get("/{arquivo_id}/download")
async def download_arquivo(
    arquivo_id: int,
    db=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Serve binário do arquivo (inline para PDFs/imagens, attachment caso contrário)."""
    empresa_id = user["empresa_id"]
    async with db.execute(
        "SELECT nome_original, nome_arquivo FROM arquivos WHERE id=? AND empresa_id=?",
        (arquivo_id, empresa_id),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    nome_original = row["nome_original"] or "arquivo"
    nome_salvo = row["nome_arquivo"]
    if not nome_salvo:
        raise HTTPException(status_code=404, detail="Envio sem arquivo (apenas mensagem).")
    caminho = os.path.join(UPLOAD_DIR, nome_salvo)
    if not os.path.isfile(caminho):
        raise HTTPException(status_code=410, detail="Arquivo removido do disco.")
    mime, _ = mimetypes.guess_type(nome_original)
    return FileResponse(
        caminho,
        media_type=mime or "application/octet-stream",
        filename=nome_original,
        headers={"Content-Disposition": f'inline; filename="{nome_original}"'},
    )
