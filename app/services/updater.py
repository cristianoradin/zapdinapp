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

        # ── 2. Download com streaming (Fix 5: timeout 600s, sem carregar tudo na memória) ──
        logger.info("[updater] Baixando pacote v%s de %s...", versao, monitor_url)
        sha = hashlib.sha256()
        total_bytes = 0

        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0)) as client:
            async with client.stream(
                "GET",
                f"{monitor_url}/api/deploy/pacotes/{pacote_id}/download",
                headers={"x-client-token": client_token},
            ) as resp:
                if resp.status_code != 200:
                    raise RuntimeError(f"Download falhou: HTTP {resp.status_code}")

                # Fix 4: verifica espaço em disco via Content-Length antes de gravar
                content_length = int(resp.headers.get("content-length", 0))
                if content_length > 0:
                    free_bytes = shutil.disk_usage(str(tmp_dir)).free
                    needed = content_length * 3   # zip + extract + swap
                    if free_bytes < needed:
                        raise RuntimeError(
                            f"Espaço insuficiente em disco: "
                            f"{free_bytes // 1024 // 1024} MB livres, "
                            f"necessário ~{needed // 1024 // 1024} MB."
                        )

                # Grava em chunks — calcula SHA-256 simultaneamente
                with open(zip_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        sha.update(chunk)
                        total_bytes += len(chunk)

        logger.info("[updater] Download concluído: %d bytes", total_bytes)

        # ── 3. Verifica SHA-256 (já calculado durante o streaming) ───────────
        computed = sha.hexdigest()
        if computed != checksum:
            raise RuntimeError(
                f"Checksum inválido! Esperado {checksum[:16]}…, obtido {computed[:16]}…"
            )
        logger.info("[updater] Checksum OK ✓")

        # ── 4. Extrai o zip ───────────────────────────────────────────────────
        if extract_dir.exists():
            shutil.rmtree(extract_dir)

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if not any(n.startswith("app/") for n in names):
                raise RuntimeError("Zip inválido: não contém pasta app/")
            logger.info("[updater] Extraindo %d arquivos...", len(names))
            zf.extractall(extract_dir)

        # ── 5. Swap atômico: app_new → app (Fix 2) ───────────────────────────
        app_src  = extract_dir / "app"
        app_live = root / "app"
        app_new  = root / "app_new"
        app_old  = root / "app_old"   # backup mantido para rollback (Fix 10)

        if not app_src.exists():
            raise RuntimeError("Extração inválida: pasta app/ não encontrada no zip.")

        # Limpa resíduos de update anterior
        if app_new.exists():
            shutil.rmtree(app_new)
        if app_old.exists():
            shutil.rmtree(app_old)

        # 1) Copia novo código para app_new/ (isolado — app/ intacto se falhar aqui)
        shutil.copytree(str(app_src), str(app_new))
        logger.info("[updater] Cópia para app_new/ concluída ✓")

        # 2) Swap: app/ → app_old/ → app_new/ → app/
        app_live.rename(app_old)
        app_new.rename(app_live)
        logger.info("[updater] app/ → app_old/ (backup), app_new/ → app/ ✓")

        # versao.json — salva backup antes de sobrescrever (usado pelo rollback)
        versao_json_live = root / "versao.json"
        if versao_json_live.exists():
            shutil.copy2(str(versao_json_live), str(root / "versao.json.bak"))

        versao_json_src = extract_dir / "versao.json"
        if versao_json_src.exists():
            shutil.copy2(str(versao_json_src), str(versao_json_live))
        else:
            versao_json_live.write_text(json.dumps({"versao": versao}))
        logger.info("[updater] versao.json → %s ✓", versao)

        # ── 6. Limpeza do temporário (app_old/ é mantido para rollback) ───────
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

        # Fix 3: usa settings.service_name em vez de "ZapDinApp" hardcoded
        _restart_process(settings.service_name)

        os._exit(1)   # systemd/NSSM reinicia automaticamente com exit code ≠ 0

    except Exception as exc:
        logger.error("[updater] ✗ Falha na atualização v%s: %s", versao, exc)
        await _report_job_status(job_id, "error", str(exc), monitor_url, client_token)
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
#  Fix 3: Restart do processo via gerenciador de serviço (Fix 3)
# ─────────────────────────────────────────────────────────────────────────────

def _restart_process(service_name: str) -> None:
    """
    Tenta reiniciar o serviço via NSSM ou Task Scheduler (Windows) / systemd (Linux).
    É best-effort: mesmo que falhe, o os._exit(1) subsequente garante o restart
    pelo gerenciador de processos configurado.

    Windows (Task Scheduler — instalação padrão):
      schtasks /End /TN <service_name>  → encerra a tarefa
      O Task Scheduler reinicia automaticamente pelo RetryCount configurado.

    Windows (NSSM — instalação legada):
      nssm restart <service_name>

    Linux (systemd):
      systemctl restart <service_name>
    """
    import platform
    import subprocess

    system = platform.system()
    logger.info("[updater] Tentando restart via gerenciador de serviço: %s (%s)", service_name, system)

    if system == "Windows":
        # Tenta Task Scheduler primeiro (instalação padrão v4+)
        try:
            subprocess.Popen(
                ["schtasks", "/End", "/TN", service_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            logger.info("[updater] schtasks /End enviado para '%s' ✓", service_name)
            return
        except Exception as exc:
            logger.debug("[updater] schtasks falhou (%s) — tentando NSSM...", exc)

        # Fallback: NSSM (instalação legada)
        try:
            subprocess.Popen(
                ["nssm", "restart", service_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            logger.info("[updater] nssm restart enviado para '%s' ✓", service_name)
        except Exception as exc:
            logger.debug("[updater] nssm falhou também (%s) — confiando em os._exit(1)", exc)

    else:
        # Linux/macOS: systemd
        try:
            subprocess.Popen(
                ["systemctl", "restart", service_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("[updater] systemctl restart enviado para '%s' ✓", service_name)
        except Exception as exc:
            logger.debug("[updater] systemctl falhou (%s) — confiando em os._exit(1)", exc)


# ─────────────────────────────────────────────────────────────────────────────
#  Fix 10: Rollback — restaura app_old/ se update causou problema
# ─────────────────────────────────────────────────────────────────────────────

def rollback() -> dict:
    """
    Reverte para o código anterior restaurando app_old/ → app/.

    Retorna dict com {ok, message}.
    Chamado pelo endpoint interno POST /internal/rollback.

    Fluxo:
      1. Verifica que app_old/ existe (backup do update anterior)
      2. Move app/ → app_broken/ (para diagnóstico)
      3. Move app_old/ → app/
      4. Restaura versao.json de versao.json.bak (se existir)
      5. os._exit(1) → Task Scheduler / NSSM reinicia com código antigo
    """
    root = _root_dir()
    app_live   = root / "app"
    app_old    = root / "app_old"
    app_broken = root / "app_broken"

    if not app_old.exists():
        msg = "Rollback impossível: app_old/ não encontrado (nenhum update anterior registrado)."
        logger.warning("[updater] %s", msg)
        return {"ok": False, "message": msg}

    try:
        logger.warning("[updater] ═══ INICIANDO ROLLBACK ═══")

        # Limpa resíduo de rollback anterior
        if app_broken.exists():
            shutil.rmtree(app_broken)

        # Swap: app/ → app_broken/ e app_old/ → app/
        app_live.rename(app_broken)
        app_old.rename(app_live)
        logger.info("[updater] app/ → app_broken/, app_old/ → app/ ✓")

        # Restaura versao.json do backup (se existir)
        versao_bak = root / "versao.json.bak"
        if versao_bak.exists():
            shutil.copy2(str(versao_bak), str(root / "versao.json"))
            logger.info("[updater] versao.json restaurado de backup ✓")

        logger.warning("[updater] ═══ ROLLBACK CONCLUÍDO — reiniciando em 2s ═══")

        # Inicia restart em thread separada para que a resposta HTTP chegue ao cliente
        import threading
        def _do_exit():
            import time
            time.sleep(2)
            _restart_process(settings.service_name)
            os._exit(1)

        threading.Thread(target=_do_exit, daemon=True).start()
        return {"ok": True, "message": "Rollback iniciado. O serviço será reiniciado em 2 segundos."}

    except Exception as exc:
        logger.error("[updater] ✗ Falha no rollback: %s", exc)
        return {"ok": False, "message": f"Erro no rollback: {exc}"}


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
