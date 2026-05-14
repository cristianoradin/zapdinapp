"""
ZapDin — Serviço de Auto-Atualização via Monitor (push seguro)
==============================================================
Fluxo sem acesso inbound (funciona atrás de NAT/firewall):
  1. A cada 30s, o heartbeat (reporter.py) é enviado ao Monitor
  2. Se houver update pendente, o Monitor inclui o comando na resposta
  3. reporter.py chama apply_monitor_update() em background task
  4. Esta função: baixa o .zip, verifica SHA-256, extrai, reinicia via NSSM

O NSSM (Windows) ou systemd (Linux) reinicia o processo automaticamente
após sys.exit(1), carregando o novo código.

Estrutura esperada do .zip:
  app/          ← sobrescreve a pasta app/ existente
    main.py
    core/
    routers/
    services/
  versao.json   ← atualiza a versão reportada no heartbeat
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Optional

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_update_in_progress = False   # evita updates simultâneos


# ─────────────────────────────────────────────────────────────────────────────
#  Utilitários
# ─────────────────────────────────────────────────────────────────────────────

def _root_dir() -> Path:
    """Pasta raiz do projeto (pai de app/)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent


def _current_version() -> str:
    try:
        return json.loads((_root_dir() / "versao.json").read_text())["versao"]
    except Exception:
        return "0.0.0"


def _version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


# ─────────────────────────────────────────────────────────────────────────────
#  Aplicação do update via Monitor
# ─────────────────────────────────────────────────────────────────────────────

async def apply_monitor_update(
    job_id: int,
    pacote_id: int,
    versao: str,
    checksum: str,
    monitor_url: str,
    client_token: str,
) -> None:
    """
    Baixa o pacote do Monitor, verifica integridade, extrai e reinicia.
    Chamado como background task pelo reporter.py quando o heartbeat retorna update.
    """
    global _update_in_progress

    if _update_in_progress:
        logger.info("[updater] Update já em progresso — ignorando comando duplicado.")
        return

    _update_in_progress = True
    monitor_url = monitor_url.rstrip("/")
    root = _root_dir()
    tmp_dir = root / "data" / "update_tmp"
    zip_path = tmp_dir / f"zapdin-{versao}.zip"
    extract_dir = tmp_dir / "extract"

    try:
        logger.info("[updater] ═══ Iniciando atualização v%s ═══", versao)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # ── 1. Notifica Monitor: downloading ─────────────────────────────────
        await _report_job_status(job_id, "downloading", None, monitor_url, client_token)

        # ── 2. Download ───────────────────────────────────────────────────────
        logger.info("[updater] Baixando pacote v%s de %s...", versao, monitor_url)
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.get(
                f"{monitor_url}/api/deploy/pacotes/{pacote_id}/download",
                headers={"x-client-token": client_token},
            )

        if resp.status_code != 200:
            raise RuntimeError(f"Download falhou: HTTP {resp.status_code}")

        content = resp.content
        zip_path.write_bytes(content)
        logger.info("[updater] Download concluído: %d bytes", len(content))

        # ── 3. Verifica SHA-256 ───────────────────────────────────────────────
        computed = hashlib.sha256(content).hexdigest()
        if computed != checksum:
            raise RuntimeError(
                f"Checksum inválido! Esperado {checksum[:16]}…, obtido {computed[:16]}…"
            )
        logger.info("[updater] Checksum OK ✓")

        # ── 4. Extrai o zip ───────────────────────────────────────────────────
        if extract_dir.exists():
            shutil.rmtree(extract_dir)

        with zipfile.ZipFile(zip_path) as zf:
            # Valida que o zip tem a estrutura esperada (app/ ou versao.json)
            names = zf.namelist()
            has_app = any(n.startswith("app/") for n in names)
            has_versao = "versao.json" in names
            if not has_app:
                raise RuntimeError("Zip inválido: não contém pasta app/")
            logger.info("[updater] Extraindo %d arquivos...", len(names))
            zf.extractall(extract_dir)

        # ── 5. Copia arquivos para a pasta do app ─────────────────────────────
        app_src = extract_dir / "app"
        if app_src.exists():
            shutil.copytree(str(app_src), str(root / "app"), dirs_exist_ok=True)
            logger.info("[updater] app/ atualizado ✓")

        versao_json_src = extract_dir / "versao.json"
        if versao_json_src.exists():
            shutil.copy2(str(versao_json_src), str(root / "versao.json"))
            logger.info("[updater] versao.json → %s ✓", versao)
        else:
            # Atualiza versao.json manualmente se não veio no zip
            (root / "versao.json").write_text(json.dumps({"versao": versao}))

        # ── 6. Limpeza ────────────────────────────────────────────────────────
        zip_path.unlink(missing_ok=True)
        shutil.rmtree(extract_dir, ignore_errors=True)

        logger.info("[updater] ═══ Atualização v%s aplicada com sucesso! Reiniciando... ═══", versao)

        # Notifica o Telegram antes de reiniciar (best-effort)
        try:
            from . import telegram_service
            await telegram_service.notify_update_applied(versao)
        except Exception:
            pass

        await asyncio.sleep(3)   # garante que o log foi escrito

        # Reinicia o processo no Windows via NSSM ou Task Scheduler
        if sys.platform == "win32":
            import subprocess
            restarted = False

            # Tentativa 1 — NSSM (instalações antigas)
            try:
                nssm = _root_dir() / "nssm.exe"
                if nssm.exists():
                    logger.info("[updater] Reiniciando via NSSM...")
                    subprocess.Popen(
                        [str(nssm), "restart", "ZapDinApp"],
                        creationflags=0x00000008,  # DETACHED_PROCESS
                    )
                    await asyncio.sleep(2)
                    restarted = True
            except Exception as _err:
                logger.warning("[updater] NSSM restart falhou: %s", _err)

            # Tentativa 2 — Task Scheduler (instalações novas via AtLogon)
            if not restarted:
                try:
                    logger.info("[updater] Reiniciando via Task Scheduler...")
                    subprocess.Popen(
                        ["schtasks", "/run", "/tn", "ZapDinApp"],
                        creationflags=0x00000008,  # DETACHED_PROCESS
                    )
                    await asyncio.sleep(3)
                    restarted = True
                except Exception as _err:
                    logger.warning("[updater] Task Scheduler restart falhou: %s", _err)

            if not restarted:
                logger.warning("[updater] Nenhum método de restart funcionou — o processo vai encerrar. Reinicie manualmente.")

        os._exit(1)              # systemd/NSSM reinicia automaticamente com exit code ≠ 0

    except Exception as exc:
        logger.error("[updater] ✗ Falha na atualização v%s: %s", versao, exc)
        # Notifica o Monitor do erro para exibir na UI
        await _report_job_status(job_id, "error", str(exc), monitor_url, client_token)
        # Limpa arquivos temporários
        zip_path.unlink(missing_ok=True)
        shutil.rmtree(extract_dir, ignore_errors=True)
    finally:
        _update_in_progress = False


async def _report_job_status(
    job_id: int,
    status: str,
    erro: Optional[str],
    monitor_url: str,
    client_token: str,
) -> None:
    """Informa o Monitor sobre o progresso do job de atualização."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{monitor_url}/api/deploy/jobs/{job_id}/status",
                json={"status": status, "erro": erro},
                headers={"x-client-token": client_token},
            )
    except Exception as exc:
        logger.debug("[updater] Falha ao reportar status '%s' ao Monitor: %s", status, exc)


# ─────────────────────────────────────────────────────────────────────────────
#  Loop de verificação periódica (mantido para compatibilidade)
#  O update principal ocorre via heartbeat (reporter.py → apply_monitor_update)
#  Este loop apenas loga a versão atual periodicamente.
# ─────────────────────────────────────────────────────────────────────────────

async def _loop() -> None:
    await asyncio.sleep(60)   # aguarda boot completo
    while True:
        try:
            versao = _current_version()
            logger.debug("[updater] Versão atual: %s", versao)
        except Exception as exc:
            logger.debug("[updater] Erro ao ler versão: %s", exc)
        await asyncio.sleep(3600)   # log a cada 1h — update real vem pelo heartbeat


def start() -> None:
    global _task
    _task = asyncio.create_task(_loop())
    logger.info("[updater] Serviço de atualização iniciado (modo Monitor-push).")


def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        _task = None
