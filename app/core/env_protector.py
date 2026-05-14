"""
env_protector.py — Proteção do arquivo .env via Windows DPAPI
=============================================================
O Windows DPAPI (Data Protection API) criptografa dados usando uma chave
derivada da identidade da máquina + usuário. O arquivo resultante (.env.enc):

  - É binário — ilegível por humanos
  - Só pode ser descriptografado na MESMA máquina (flag MACHINE-level)
  - Se copiado para outra máquina → CryptUnprotectData retorna erro

Uso no fluxo de ativação:
  1. Ativação escreve o .env normal (temporário)
  2. protect_env_file() converte .env → .env.enc e apaga o .env
  3. No próximo startup, config.py chama load_env_to_environ() que
     descriptografa o .enc e injeta os valores em os.environ
     (pydantic-settings lê os.environ antes do env_file)

Em desenvolvimento (Mac/Linux) o módulo é no-op — tudo passa pelo .env normal.
"""
from __future__ import annotations

import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Implementação DPAPI (Windows only) ───────────────────────────────────────

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    # CRYPTPROTECT_LOCAL_MACHINE = 4: qualquer processo na mesma máquina pode
    # descriptografar, independente do usuário. Necessário para serviços que
    # rodam como SYSTEM mas onde a ativação ocorreu como usuário normal.
    _DPAPI_FLAG = 4

    def _protect(data: bytes) -> bytes:
        blob_in = _BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_ubyte)))
        blob_out = _BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            ctypes.c_wchar_p("ZapDin"),
            None, None, None,
            _DPAPI_FLAG,
            ctypes.byref(blob_out),
        )
        if not ok:
            raise OSError(f"CryptProtectData falhou: {ctypes.GetLastError()}")
        result = bytes(blob_out.pbData[: blob_out.cbData])
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return result

    def _unprotect(data: bytes) -> bytes:
        blob_in = _BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_ubyte)))
        blob_out = _BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None, None, None, None,
            _DPAPI_FLAG,
            ctypes.byref(blob_out),
        )
        if not ok:
            raise OSError(f"CryptUnprotectData falhou: {ctypes.GetLastError()}")
        result = bytes(blob_out.pbData[: blob_out.cbData])
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return result

else:
    def _protect(data: bytes) -> bytes:  # type: ignore[misc]
        return data  # no-op fora do Windows

    def _unprotect(data: bytes) -> bytes:  # type: ignore[misc]
        return data  # no-op fora do Windows


# ── API pública ───────────────────────────────────────────────────────────────

def protect_env_file(env_path: Path) -> bool:
    """
    Criptografa env_path (.env) → env_path.with_suffix('.enc') via DPAPI.
    Apaga o .env original após sucesso.

    Retorna True se a proteção foi aplicada, False se já estava protegido
    ou se não é Windows.
    """
    if sys.platform != "win32":
        return False  # Só faz sentido no Windows

    enc_path = env_path.with_suffix(".enc")

    if not env_path.exists():
        logger.debug("[env_protector] .env não encontrado em %s — nada a proteger", env_path)
        return False

    try:
        plain = env_path.read_bytes()
        encrypted = _protect(plain)
        enc_path.write_bytes(encrypted)
        env_path.unlink()
        logger.info("[env_protector] .env protegido via DPAPI → %s", enc_path)
        return True
    except Exception as exc:
        logger.error("[env_protector] Falha ao proteger .env: %s", exc)
        return False


def load_env_to_environ(env_path: Path) -> bool:
    """
    Se existir um .env.enc, descriptografa via DPAPI e injeta os valores
    em os.environ (pydantic-settings lê os.environ antes do env_file).

    Retorna True se o .enc foi carregado com sucesso.
    """
    if sys.platform != "win32":
        return False

    enc_path = env_path.with_suffix(".enc")
    if not enc_path.exists():
        return False

    # Se .env existe junto com .env.enc, o .env é mais recente (escrito pela
    # ativação após falha do DPAPI). O .env.enc está desatualizado — apaga
    # para evitar que valores antigos (ex.: SQLite do instalador) tenham
    # prioridade sobre o .env correto (PostgreSQL da ativação).
    if env_path.exists():
        try:
            enc_path.unlink()
            logger.info("[env_protector] .env.enc desatualizado removido (coexistia com .env)")
        except Exception as _e:
            logger.warning("[env_protector] Não foi possível remover .env.enc antigo: %s", _e)
        return False

    try:
        encrypted = enc_path.read_bytes()
        plain = _unprotect(encrypted).decode("utf-8-sig")

        for line in plain.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Não sobrescreve variáveis já definidas no ambiente do processo
            if key and key not in os.environ:
                os.environ[key] = value

        logger.debug("[env_protector] .env.enc carregado com sucesso")
        return True
    except Exception as exc:
        logger.warning("[env_protector] Não foi possível carregar .env.enc: %s", exc)
        return False


def is_protected(env_path: Path) -> bool:
    """Retorna True se o ambiente já está usando o .env.enc (proteção ativa)."""
    return env_path.with_suffix(".enc").exists() and not env_path.exists()
