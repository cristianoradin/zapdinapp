"""
evolution_service.py — Integração com Evolution API (WhatsApp REST API)
========================================================================
Estratégia de estabilidade de conexão:
  - Webhook recebe eventos em tempo real (QR, estado de conexão, logout)
  - Distingue QUEDA DE REDE (reconecta automático) de LOGOUT REAL (pede novo QR)
  - Backoff exponencial na reconexão: 5s → 10s → 20s → 40s → 60s → 60s...
  - Heartbeat confirma estado a cada 60s (conectado) ou 20s (desconectado)
  - Nenhuma ação manual necessária em quedas de rede — só se o usuário
    remover o dispositivo no celular (WhatsApp → Aparelhos conectados → Remover)

Fluxo de reconexão automática:
  1. Webhook recebe CONNECTION_UPDATE com state != "open" e != "connecting"
  2. Se NÃO for logout real → inicia _reconnect_loop() em background
  3. _reconnect_loop() chama instance/connect a cada tentativa
     - Se retornar state "open" → já reconectou (sessão válida na memória do Baileys)
     - Se retornar QR code     → sessão expirou → exibe QR, para o loop
  4. Se for logout real (LOGGED_OUT / DISCONNECTED com statusReason=401)
     → marca como logged_out=True → pede novo QR sem tentar reconectar
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
from typing import Dict, List, Optional, Tuple

from ..core.phone import phone_for_wa

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0

# Backoff em segundos para tentativas de reconexão: 5, 10, 20, 40, 60, 60, 60...
_RECONNECT_BACKOFF: List[int] = [5, 10, 20, 40, 60, 60, 60]

# Modo agente: sessões com evolution_url == AGENT_SCHEME são roteadas via WS
# para o agente local (atravessa NAT do cliente). Nada de HTTP direto.
AGENT_SCHEME = "agent://"

# Cache de existência de número (onWhatsApp) — num -> (exists: bool, monotonic_ts).
# TTL longo: existência quase não muda; protege o número árbitro de excesso de queries.
_NUMEXIST_CACHE: dict = {}
_NUMEXIST_TTL = 6 * 3600

# Cache de foto de perfil — "inst:num" -> (url|None, monotonic_ts).
_PROFILEPIC_CACHE: dict = {}
_PROFILEPIC_TTL = 6 * 3600

# Injetado por app.main.py após criar o socketio.AsyncServer.
# Mantido fora do EvoManager para evitar import circular.
_sio = None


def set_sio(sio) -> None:
    """Registra a instância do Socket.IO usada para comandos /agent."""
    global _sio
    _sio = sio


def _is_agent_mode(evolution_url: Optional[str]) -> bool:
    return bool(evolution_url) and evolution_url.strip().lower().startswith(AGENT_SCHEME)

# ── Tokens temporários para servir arquivos à Evolution API ──────────────────
_file_tokens: Dict[str, str] = {}
_file_tokens_lock = threading.Lock()


def _url(path: str) -> str:
    return f"{settings.evolution_url.rstrip('/')}/{path.lstrip('/')}"


def _h() -> dict:
    return {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}


def _instance_name(empresa_id: int, session_id: str) -> str:
    return f"e{empresa_id}_{session_id}"


def _webhook_url() -> str:
    """URL que a Evolution API vai chamar quando houver eventos.
    Override por env EVO_WEBHOOK_URL (ex: http://zapdin-app:4545/api/evo-webhook)
    quando a Evolution roda em outro container/rede e não enxerga 127.0.0.1."""
    import os as _os
    base = _os.environ.get("EVO_WEBHOOK_URL", "").strip()
    if base:
        return base
    return f"http://127.0.0.1:{settings.port}/api/evo-webhook"


# ─────────────────────────────────────────────────────────────────────────────
#  Sessão local — representa uma instância do WhatsApp
# ─────────────────────────────────────────────────────────────────────────────

class EvoSession:
    def __init__(self, session_id: str, nome: str, empresa_id: int,
                 evolution_url: Optional[str] = None):
        self.session_id  = session_id
        self.nome        = nome
        self.empresa_id  = empresa_id
        self.status      = "disconnected"
        self.qr_data:  Optional[str] = None
        self.phone:    Optional[str] = None
        # Modo híbrido: URL custom da Evolution local do cliente (override per-sessão).
        # None → usa settings.evolution_url (modo padrão, servidor).
        self.evolution_url: Optional[str] = (evolution_url or "").strip() or None

        # True somente quando o usuário removeu o dispositivo no celular.
        # Neste caso NÃO tentamos reconectar — aguardamos novo QR.
        self._logged_out = False

        # Evita múltiplos loops de reconexão simultâneos
        self._reconnecting = False

        self._heartbeat_task:  Optional[asyncio.Task] = None
        self._reconnect_task:  Optional[asyncio.Task] = None

        # Detecção de "zumbi parcial" (modo agente): sessão reporta connected mas
        # os envios dão timeout (página do WhatsApp travada). Conta timeouts seguidos.
        self._send_fail_streak = 0
        self._last_reauth = 0.0   # timestamp do último re-QR forçado (throttle)

    def _url(self, path: str) -> str:
        """URL da Evolution API: usa custom desta sessão ou fallback ao settings."""
        base = (self.evolution_url or settings.evolution_url).rstrip("/")
        return f"{base}/{path.lstrip('/')}"

    # ─────────────────────────────────────────────────────────────────────────
    #  Handlers de webhook (chamados pelo EvoManager)
    # ─────────────────────────────────────────────────────────────────────────

    def on_qr_updated(self, qr_base64: str) -> None:
        """
        Novo QR code disponível (webhook QRCODE_UPDATED).
        Ao receber QR, a sessão NÃO está conectada e NÃO está em logout —
        é um estado intermediário aguardando o usuário escanear.
        """
        if not qr_base64.startswith("data:"):
            qr_base64 = "data:image/png;base64," + qr_base64
        self.qr_data     = qr_base64
        self.status      = "disconnected"
        self._logged_out = False   # recebeu QR novo → sessão pode ser recuperada
        self._stop_reconnect()     # para qualquer reconexão em andamento
        logger.info("[evo] [%s] QR atualizado — aguardando leitura", self.session_id)

    def on_connection_update(self, state: str, phone: Optional[str] = None) -> None:
        """
        Mudança de estado de conexão (webhook CONNECTION_UPDATE).

        Estados possíveis da Evolution/Baileys:
          open        → conectado com sucesso
          connecting  → escaneou QR, estabelecendo conexão
          pairingCode → usando código de pareamento (não QR)
          close       → conexão encerrada (queda de rede, restart, timeout)
        """
        prev = self.status

        if state == "open":
            # ── Conectado ────────────────────────────────────────────────────
            was_reconnecting = self._reconnecting or prev not in ("connected", "connecting")
            self.status      = "connected"
            self.qr_data     = None        # QR não é mais necessário
            self._logged_out = False
            self._reconnecting = False
            self._stop_reconnect()
            if phone:
                self.phone = phone
            elif not self.phone:
                # Phone não veio no webhook → agenda busca via fetchInstances
                asyncio.create_task(self._try_fetch_phone())
            # Notifica reconexão automática (só quando voltou de um estado não-conectado)
            if was_reconnecting and prev != "connected":
                try:
                    from . import telegram_service
                    asyncio.create_task(telegram_service.notify_reconnected(self.nome))
                except Exception:
                    pass

        elif state in ("connecting", "pairingCode"):
            # ── Conectando (usuário acabou de escanear o QR) ─────────────────
            self.status = "connecting"
            # Checa ativamente até confirmar "open" (o webhook às vezes atrasa)
            asyncio.create_task(self._poll_until_open())

        else:
            # ── Queda de conexão (close, unknown, etc.) ───────────────────────
            # Se NÃO foi um logout explícito, tentamos reconectar automaticamente.
            # Se foi logout real, apenas marcamos desconectado e aguardamos QR.
            self.status = "disconnected"
            if not self._logged_out:
                self._start_reconnect()

        if prev != self.status:
            logger.info("[evo] [%s] %s → %s", self.session_id, prev, self.status)
            asyncio.create_task(self._persist_status())   # DB reflete o estado real
            # Alerta IMEDIATO quando uma sessão CONECTADA cai (visibilidade — humano age
            # rápido se o auto-recover não resolver). Ênfase extra se for dona de agente
            # compartilhado (muitos postos dependem dela).
            if prev == "connected" and self.status != "connected":
                try:
                    from . import agent_bridge as _ab
                    from . import telegram_service
                    n_deps = sum(1 for v in getattr(_ab, "_owner_map", {}).values() if v == self.empresa_id)
                    extra = f" ⚠️ DONA COMPARTILHADA — {n_deps} posto(s) dependem!" if n_deps else ""
                    asyncio.create_task(telegram_service.notify_send_failure(
                        self.nome, "—", f"WhatsApp DESCONECTOU (auto-reconectando).{extra}"))
                except Exception:
                    pass

    def on_logout(self) -> None:
        """
        Usuário removeu este dispositivo no celular (WhatsApp → Aparelhos conectados).
        Neste caso NÃO tentamos reconectar — a sessão foi revogada pelo usuário.
        Um novo QR será necessário.
        """
        prev = self.status
        self.status      = "disconnected"
        self._logged_out = True
        self.qr_data     = None
        self.phone       = None
        self._stop_reconnect()
        logger.warning("[evo] [%s] LOGOUT REAL — dispositivo removido pelo usuário. Novo QR necessário.", self.session_id)
        asyncio.create_task(self._persist_status())   # DB: disconnected + phone limpo
        if prev != self.status:
            logger.info("[evo] [%s] %s → disconnected (logout)", self.session_id, prev)
        # Notifica via Telegram — sessão foi desconectada por logout real
        try:
            from . import telegram_service
            asyncio.create_task(telegram_service.notify_disconnected(self.nome))
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Reconexão automática com backoff exponencial
    # ─────────────────────────────────────────────────────────────────────────

    def _start_reconnect(self) -> None:
        """Inicia o loop de reconexão se ainda não estiver rodando."""
        if self._reconnecting:
            return
        self._reconnecting = True
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    def _stop_reconnect(self) -> None:
        """Cancela loop de reconexão (chamado ao conectar ou ao receber logout)."""
        self._reconnecting = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self._reconnect_task = None

    async def _reconnect_loop(self) -> None:
        """
        Tenta reconectar com backoff exponencial.

        Chama instance/connect na Evolution API:
          - Se retornar state "open"  → reconectou sem QR (sessão ainda válida)
          - Se retornar QR base64     → sessão expirou → exibe QR, para o loop
          - Se falhar (rede/timeout)  → aguarda próximo backoff e tenta de novo
        """
        inst = _instance_name(self.empresa_id, self.session_id)
        attempt = 0
        logger.info("[evo] [%s] Iniciando reconexão automática...", self.session_id)

        while self._reconnecting and not self._logged_out:
            delay = _RECONNECT_BACKOFF[min(attempt, len(_RECONNECT_BACKOFF) - 1)]
            logger.info("[evo] [%s] Tentativa %d — aguardando %ds...", self.session_id, attempt + 1, delay)
            await asyncio.sleep(delay)

            if not self._reconnecting or self._logged_out:
                break

            # Modo agente: usa fetch_qr_now (que roteia via WS)
            if _is_agent_mode(self.evolution_url):
                try:
                    await self.fetch_qr_now()
                    if self.status == "connected":
                        return
                except Exception as exc:
                    logger.debug("[evo-agent] reconnect [%s]: %s", self.session_id, exc)
                attempt += 1
                continue

            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    # Primeiro verifica se já reconectou sozinho (Baileys faz retry interno)
                    rs = await client.get(self._url(f"instance/connectionState/{inst}"), headers=_h())
                    if rs.status_code == 200:
                        state = (
                            rs.json().get("instance", {}).get("state")
                            or rs.json().get("state")
                            or "close"
                        )
                        if state == "open":
                            logger.info("[evo] [%s] Reconectado automaticamente (Baileys retry)!", self.session_id)
                            self.on_connection_update("open")
                            return

                    # Força tentativa de reconexão via instance/connect
                    r = await client.get(self._url(f"instance/connect/{inst}"), headers=_h())

                if r.status_code == 200:
                    d = r.json()

                    # Verifica se já está conectado
                    state = (
                        d.get("instance", {}).get("state")
                        or d.get("state")
                        or ""
                    )
                    if state == "open":
                        logger.info("[evo] [%s] Reconectado via instance/connect!", self.session_id)
                        self.on_connection_update("open")
                        return

                    # Retornou QR → sessão expirou, usuário precisa escanear
                    qr = (
                        d.get("base64")
                        or d.get("qrcode", {}).get("base64")
                        or d.get("qr", "")
                    )
                    if qr:
                        logger.info("[evo] [%s] Sessão expirada — novo QR gerado", self.session_id)
                        self.on_qr_updated(qr)
                        return   # para o loop — aguarda o usuário escanear

            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("[evo] [%s] Tentativa %d falhou: %s", self.session_id, attempt + 1, exc)

            attempt += 1

        self._reconnecting = False

    # ─────────────────────────────────────────────────────────────────────────
    #  Poll após leitura do QR (confirma "open" que pode atrasar no webhook)
    # ─────────────────────────────────────────────────────────────────────────

    async def _poll_until_open(self) -> None:
        """
        Após o usuário escanear o QR, o webhook pode demorar alguns segundos
        para confirmar "open". Este poll garante que o status seja atualizado
        rapidamente no frontend.
        Checa a cada 2s por até 30s.
        """
        for _ in range(15):
            await asyncio.sleep(2)
            if self.status == "connected":
                return
            try:
                await self._check_state()
            except Exception:
                pass
            if self.status == "connected":
                return

    # ─────────────────────────────────────────────────────────────────────────
    #  Heartbeat — confirma estado periodicamente
    # ─────────────────────────────────────────────────────────────────────────

    def start_heartbeat(self) -> None:
        """Inicia o heartbeat em background (chamado ao adicionar a sessão)."""
        if not self._heartbeat_task or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def stop_heartbeat(self) -> None:
        """Para o heartbeat (chamado ao remover a sessão)."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        """
        Confirma o estado real da conexão periodicamente consultando a Evolution API.

        Intervalos:
          - Conectado:     60s (estado estável, verificação de segurança)
          - Desconectado:  20s (pressão para reconectar mais rápido)
          - Reconectando:  aguarda (o loop de reconexão já está ativo)

        Nota: este heartbeat NÃO gera QR — apenas confirma estado.
        A reconexão é disparada pelo on_connection_update() via webhook.
        """
        await asyncio.sleep(5)   # aguarda estabilização no startup
        while True:
            try:
                await self._check_state()
            except Exception as exc:
                logger.debug("[evo] heartbeat [%s]: %s", self.session_id, exc)

            if self.status == "connected":
                await asyncio.sleep(30)   # estável: confere a cada 30s (detecta queda rápido)
            elif self._reconnecting:
                # Loop de reconexão já está tratando a situação
                await asyncio.sleep(15)
            else:
                # Desconectado sem reconexão ativa — pode ter perdido o webhook
                # Força tentativa de reconexão se não for logout real
                if not self._logged_out:
                    self._start_reconnect()
                await asyncio.sleep(20)

    async def _try_fetch_phone(self) -> None:
        """
        Busca o número de telefone via fetchInstances quando phone ainda não foi extraído.
        A Evolution API nem sempre inclui o phone no webhook CONNECTION_UPDATE — este
        método consulta a lista de instâncias para obter o owner/wuid da sessão ativa.
        Chamado periodicamente pelo heartbeat enquanto conectado mas sem phone.
        """
        inst = _instance_name(self.empresa_id, self.session_id)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.get(_url("instance/fetchInstances"), headers=_h())
            if r.status_code != 200:
                return
            for item in r.json():
                # Suporta formatos: {instance:{...}} e {...} flat; nome em instanceName OU name
                i = item.get("instance") or item
                nome_inst = i.get("instanceName") or i.get("name")
                if nome_inst != inst:
                    continue
                raw = (
                    i.get("owner")
                    or i.get("ownerJid")     # evoapicloud v2.3.x usa ownerJid
                    or i.get("wuid")
                    or i.get("phone")
                    or i.get("number")
                    or ""
                ).strip()
                if raw:
                    self.phone = raw.split("@")[0]
                    logger.info("[evo] [%s] Número extraído via API: %s", self.session_id, self.phone)
                    # Persiste no banco pra aparecer no app e no monitor
                    try:
                        from ..core.database import get_db_direct
                        async with get_db_direct() as db:
                            await db.execute(
                                "UPDATE sessoes_wa SET phone=?, status='connected' WHERE empresa_id=? AND id=?",
                                (self.phone, self.empresa_id, self.session_id),
                            )
                            await db.commit()
                    except Exception as _e:
                        logger.debug("[evo] persist phone erro: %s", _e)
                return
        except Exception as exc:
            logger.debug("[evo] _try_fetch_phone [%s]: %s", self.session_id, exc)

    async def _check_state(self) -> None:
        """Consulta connectionState na Evolution API e atualiza o status local."""
        inst = _instance_name(self.empresa_id, self.session_id)

        # Modo agente: pergunta estado via WS
        if _is_agent_mode(self.evolution_url):
            from . import agent_bridge as _ab
            try:
                resp = await _ab.send_command(
                    _sio, self.empresa_id, "get_state", {"instance": inst}, timeout=15.0,
                )
                if not resp.get("ok"):
                    return
                state = resp.get("state") or "close"
            except Exception:
                return
            if state == "open" and self.status != "connected":
                self.on_connection_update("open")
            elif self.status == "connected" and state in ("close", "qr", "qr_code", "connecting", "disconnected", "logged_out"):
                # SÓ derruba sessão conectada em sinal DEFINITIVO de queda/logout.
                # "loading"/"unknown" = detecção transitória do agente (seletor falhando)
                # → NÃO flapa connected→disconnected à toa (mantém o número conectado).
                logger.warning("[evo-agent] [%s] heartbeat detectou queda real: %s", self.session_id, state)
                self.on_connection_update(state)
            return

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(self._url(f"instance/connectionState/{inst}"), headers=_h())
        if r.status_code != 200:
            return
        data  = r.json()
        state = (
            data.get("instance", {}).get("state")
            or data.get("instance", {}).get("connectionStatus")
            or data.get("state")
            or data.get("connectionStatus")
            or "close"
        )
        # Só atualiza se mudou — evita log desnecessário
        if state == "open" and self.status != "connected":
            self.on_connection_update("open")
        elif state != "open" and self.status == "connected":
            # Estava conectado, agora não está → webhook perdido → inicia reconexão
            logger.warning("[evo] [%s] Heartbeat detectou queda — webhook perdido?", self.session_id)
            self.on_connection_update(state)
        # Retry: conectado mas phone ainda não extraído → consulta fetchInstances
        if self.status == "connected" and not self.phone:
            await self._try_fetch_phone()

    # ─────────────────────────────────────────────────────────────────────────
    #  Busca QR inicial (startup ou quando front abre a página)
    # ─────────────────────────────────────────────────────────────────────────

    async def fetch_qr_now(self) -> None:
        """
        Verifica estado atual e exibe QR se necessário.
        Chamado no startup e quando o frontend abre a página de sessões.
        Se já estiver conectado, não faz nada.
        Se estiver desconectado (e não em logout), solicita QR/reconexão.
        """
        inst = _instance_name(self.empresa_id, self.session_id)

        # Modo agente: solicita QR via WS, agente local consulta Evolution dele
        if _is_agent_mode(self.evolution_url):
            from . import agent_bridge as _ab
            try:
                resp = await _ab.send_command(
                    _sio, self.empresa_id, "get_qr", {"instance": inst}, timeout=30.0,
                )
                if resp.get("ok"):
                    state = resp.get("state") or ""
                    if state == "open":
                        self.on_connection_update("open")
                        return
                    qr = resp.get("qr") or resp.get("base64")
                    if qr:
                        self.on_qr_updated(qr)
            except Exception as exc:
                logger.debug("[evo-agent] fetch_qr_now [%s]: %s", self.session_id, exc)
            return

        try:
            # Primeiro verifica se já está conectado (evita gerar QR desnecessário)
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                rs = await client.get(self._url_for_inst(inst, f"instance/connectionState/{inst}"), headers=_h())
            if rs.status_code == 200:
                state = (
                    rs.json().get("instance", {}).get("state")
                    or rs.json().get("state")
                    or "close"
                )
                if state == "open":
                    self.on_connection_update("open")
                    return   # já conectado

            if self.status == "connected":
                return

            # Se foi logout real, não tenta reconectar automaticamente —
            # aguarda o frontend chamar explicitamente para gerar QR
            if self._logged_out:
                logger.info("[evo] [%s] Sessão em logout — aguardando ação manual", self.session_id)
                return

            # Tenta reconectar (pode retornar "open" ou QR)
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.get(self._url_for_inst(inst, f"instance/connect/{inst}"), headers=_h())
            if r.status_code == 200:
                d = r.json()
                qr = (
                    d.get("base64")
                    or d.get("qrcode", {}).get("base64")
                    or d.get("qr", "")
                )
                if qr:
                    self.on_qr_updated(qr)
        except Exception as exc:
            logger.debug("[evo] fetch_qr_now [%s]: %s", self.session_id, exc)

    async def _persist_status(self) -> None:
        """Reflete o status REAL da sessão no banco. CRÍTICO: live_status (app+monitor)
        e o worker leem o DB como verdade no modo agente. Sem isto, uma sessão que cai
        ou desloga fica eternamente 'connected'+phone no banco (zumbi) → monitor mente,
        worker tenta enviar e dá timeout. Limpa o phone quando não está conectado."""
        try:
            from ..core.database import get_db_direct
            ph = self.phone if self.status == "connected" else None
            async with get_db_direct() as db:
                await db.execute(
                    "UPDATE sessoes_wa SET status=?, phone=? WHERE empresa_id=? AND id=?",
                    (self.status, ph, self.empresa_id, self.session_id),
                )
                await db.commit()
        except Exception as exc:
            logger.debug("[evo] _persist_status [%s]: %s", self.session_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
#  Resolução LID → PN (Evolution v2.3+ manda presença com <lid>@lid)
# ─────────────────────────────────────────────────────────────────────────────
import re as _re

_LID_PN_CACHE: dict = {}        # lid(dígitos) → pn(dígitos, com 55)
_LID_PN_MAX = 5000
_LID_FETCH: dict = {}           # inst → ts do último findContacts (throttle)
_PRESENCE_NUDGE: dict = {}      # "inst|pn" → ts do último nudge de subscribe (throttle)


def _remember_lid_pn(*objs) -> None:
    """Aprende o mapa LID→PN de qualquer payload que traga os dois (ex: mensagens
    inbound, que vêm com remoteJid PN). Depois a presença (que só traz o LID)
    resolve o número real por aqui."""
    try:
        import json as _json
        blob = _json.dumps(objs, default=str)
        pns = _re.findall(r"(55\d{10,11})@s\.whatsapp\.net", blob)
        lids = _re.findall(r"(\d{6,})@lid", blob)
        if pns and lids:
            pn = pns[0]
            for lid in lids:
                if len(_LID_PN_CACHE) < _LID_PN_MAX:
                    _LID_PN_CACHE[lid] = pn
    except Exception:
        pass


def _resolve_presence_pn(data: dict) -> str:
    """Número PN (só dígitos, com 55) da presença, ou '' se não resolver.
    Evolution v2.3 manda data.id como <lid>@lid → tenta campos PN auxiliares e o cache."""
    cands = [
        data.get("remoteJidAlt"), data.get("senderPn"), data.get("participantPn"),
        data.get("remoteJid"), data.get("id"),
    ]
    pres = data.get("presences")
    if isinstance(pres, dict):
        cands.extend(pres.keys())
    # 1) prefere @s.whatsapp.net direto (PN real)
    for j in cands:
        s = str(j or "")
        if s.endswith("@s.whatsapp.net"):
            return s.split("@", 1)[0]
    # 2) LID → cache aprendido das mensagens
    for j in cands:
        s = str(j or "")
        if s.endswith("@lid"):
            pn = _LID_PN_CACHE.get(s.split("@", 1)[0])
            if pn:
                return pn
    return ""


# ─────────────────────────────────────────────────────────────────────────────
#  Manager — gerencia todas as sessões e despacha webhooks
# ─────────────────────────────────────────────────────────────────────────────

class EvoManager:
    def __init__(self):
        # Chave: "empresa_id:session_id" → EvoSession
        self._sessions: Dict[str, EvoSession] = {}
        # Índice inverso: instanceName Evolution → EvoSession (despacho rápido de webhook)
        self._inst_index: Dict[str, EvoSession] = {}
        self._rr_index = 0   # round-robin para pick_session

    def _key(self, empresa_id: int, session_id: str) -> str:
        return f"{empresa_id}:{session_id}"

    async def load_from_db(self, db) -> None:
        """Carrega todas as sessões salvas no banco ao iniciar o app."""
        async with db.execute("SELECT id, nome, empresa_id, evolution_url FROM sessoes_wa") as cur:
            rows = await cur.fetchall()
        for row in rows:
            await self.add_session(
                row["id"], row["nome"], row["empresa_id"],
                evolution_url=(row["evolution_url"] if "evolution_url" in row.keys() else None),
            )

    def _url_for_inst(self, inst: str, path: str) -> str:
        """URL da Evolution API para uma instância — usa custom da sessão se houver."""
        sess = self._inst_index.get(inst)
        if sess and sess.evolution_url:
            return sess._url(path)
        return _url(path)

    # ── Chat / chamados (integração externa) ─────────────────────────────────
    def _first_session_id(self, empresa_id: int) -> Optional[str]:
        """1ª sessão da empresa (prefere conectada) — usada pelo chat (1 número)."""
        prefix = f"{empresa_id}:"
        cand = [(k, s) for k, s in self._sessions.items() if k.startswith(prefix)]
        if not cand:
            return None
        cand.sort(key=lambda kv: (kv[1].status != "connected",))
        return cand[0][0].split(":", 1)[1]

    async def send_presence(self, empresa_id: int, number: str,
                            presence: str = "composing", delay_ms: int = 1500,
                            session_id: Optional[str] = None) -> tuple:
        """Envia presença (composing/paused/available) → cliente vê 'digitando…'.
        Separado do envio de mensagem. Só Evolution. session_id força a sessão (SGADesk)."""
        sid = session_id or self._first_session_id(empresa_id)
        if not sid:
            return False, "sem sessão"
        inst = _instance_name(empresa_id, sid)
        num = "".join(c for c in (number or "") if c.isdigit())
        if not num.startswith("55"):
            num = "55" + num
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.post(
                    self._url_for_inst(inst, f"chat/sendPresence/{inst}"),
                    json={"number": num, "presence": presence, "delay": delay_ms},
                    headers=_h(),
                )
            return (r.status_code in (200, 201)), (None if r.status_code in (200, 201) else r.text[:120])
        except Exception as exc:
            return False, str(exc)

    async def _forward_chat(self, empresa_id: int, payload: dict) -> None:
        """Repassa evento de chat (inbound/presence/mídia) pro sistema externo do cliente.
        URL + segredo em config (chat_webhook_url / chat_webhook_secret), por empresa.

        - Assina o corpo com HMAC-SHA256 (header X-Zapdin-Signature) se houver segredo.
        - Reentrega: tenta até 4x (0s, 2s, 10s, 30s) enquanto a resposta não for 200,
          pra não perder mensagem do cliente se o sistema externo estiver reiniciando."""
        try:
            from ..core.database import get_db_direct
            # Webhook POR SESSÃO (isola PROD/HML na mesma empresa): usa a chave da
            # sessão que originou o evento (payload.sessao_id); cai no legado empresa-wide
            # se a sessão não tiver webhook próprio. Evita que um ambiente apague o outro.
            sid = payload.get("sessao_id") or ""
            url, secret = "", ""
            url_s, secret_s = "", ""
            async with get_db_direct() as db:
                async with db.execute(
                    "SELECT key, value FROM config WHERE empresa_id=? AND key LIKE 'chat_webhook_%'",
                    (empresa_id,),
                ) as cur:
                    rows = await cur.fetchall()
            for r in rows:
                k, v = r["key"], (r["value"] or "")
                if k == "chat_webhook_url":                 url = v
                elif k == "chat_webhook_secret":            secret = v
                elif sid and k == f"chat_webhook_url__{sid}":    url_s = v
                elif sid and k == f"chat_webhook_secret__{sid}": secret_s = v
            # Sessão-específico tem prioridade sobre o legado (isola PROD/HML)
            if url_s:
                url, secret = url_s, (secret_s or secret)
            if not url:
                return

            payload = {**payload, "empresa_id": empresa_id}
            # corpo canônico (mesmo formato que o receptor reconstrói pra validar o HMAC)
            body = json.dumps(payload, separators=(",", ":")).encode()
            headers = {"Content-Type": "application/json"}
            if secret:
                sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
                headers["X-Zapdin-Signature"] = f"sha256={sig}"

            delays = (0, 2, 10, 30)
            for i, d in enumerate(delays):
                if d:
                    await asyncio.sleep(d)
                try:
                    async with httpx.AsyncClient(timeout=8.0) as client:
                        resp = await client.post(url, content=body, headers=headers)
                    if resp.status_code == 200:
                        return
                    logger.debug("[chat] webhook empresa=%s HTTP %s (tentativa %s)",
                                 empresa_id, resp.status_code, i + 1)
                except Exception as exc:
                    logger.debug("[chat] webhook empresa=%s erro (tentativa %s): %s",
                                 empresa_id, i + 1, exc)
            logger.warning("[chat] webhook empresa=%s falhou após %s tentativas", empresa_id, len(delays))
        except Exception as exc:
            logger.debug("[chat] forward falhou empresa=%s: %s", empresa_id, exc)

    async def _fetch_media_b64(self, inst: str, data: dict):
        """Busca o base64 de uma mídia recebida via Evolution (server mode).
        Retorna (base64, mimetype, filename) ou (None,None,None). Modo agente não suporta."""
        sess = self._inst_index.get(inst)
        if sess and _is_agent_mode(sess.evolution_url):
            return None, None, None
        try:
            # Evolution v2 aceita o objeto da mensagem (usa message.key pra localizar);
            # passar o data completo é mais robusto entre versões.
            body = {"message": data, "convertToMp4": False}
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    self._url_for_inst(inst, f"chat/getBase64FromMediaMessage/{inst}"),
                    json=body, headers=_h(),
                )
            if r.status_code in (200, 201):
                j = r.json()
                return j.get("base64"), j.get("mimetype"), j.get("fileName")
            logger.debug("[chat] getBase64 HTTP %s: %s", r.status_code, r.text[:160])
        except Exception as exc:
            logger.debug("[chat] getBase64 falhou: %s", exc)
        return None, None, None

    async def _forward_chat_media(self, empresa_id: int, inst: str, data: dict) -> None:
        """Inbound de mídia (imagem/áudio/documento) → evento tipo:'midia' no webhook."""
        key = data.get("key") or {}
        msg = data.get("message") or {}
        node = (
            msg.get("imageMessage")
            or msg.get("documentMessage")
            or ((msg.get("documentWithCaptionMessage") or {}).get("message") or {}).get("documentMessage")
            or msg.get("audioMessage")
            or msg.get("videoMessage")
            or msg.get("stickerMessage")
            or {}
        )
        caption = node.get("caption") or ""
        mime = node.get("mimetype") or ""
        fname = node.get("fileName") or ""
        b64, mime2, fname2 = await self._fetch_media_b64(inst, data)
        de = (key.get("remoteJid") or "").split("@", 1)[0]
        _sess = self._inst_index.get(inst)
        payload = {
            "tipo": "midia",
            "de": de,
            "message_id": key.get("id") or "",
            "mime": mime2 or mime,
            "nome_arquivo": fname2 or fname or "arquivo",
            "caption": caption,
            "nome": data.get("pushName") or "",
            "sessao_id": _sess.session_id if _sess else None,   # qual sessão recebeu (SGADesk)
            "numero_conectado": _sess.phone if _sess else None,
        }
        if b64:
            payload["media_base64"] = b64
        await self._forward_chat(empresa_id, payload)

    async def send_file_b64(self, empresa_id: int, number: str, media_base64: str,
                            filename: str, caption: str = "", session_id: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """Envia arquivo recebido em base64 (usado pela API /api/chat/send-file).
        Decodifica num temp, reaproveita o send_file existente, apaga o temp."""
        sid = session_id or self._first_session_id(empresa_id)
        if not sid:
            return False, "Nenhuma sessão WhatsApp da empresa."
        try:
            raw = base64.b64decode(media_base64, validate=False)
        except Exception:
            return False, "media_base64 inválido"
        import tempfile
        ext = os.path.splitext(filename)[1].lower()
        fd, tmp = tempfile.mkstemp(suffix=ext or "")
        try:
            def _w():
                with os.fdopen(fd, "wb") as f:
                    f.write(raw)
            await asyncio.to_thread(_w)
            return await self.send_file(sid, empresa_id, number, tmp, filename, caption or "")
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass

    async def add_session(self, session_id: str, nome: str, empresa_id: int,
                          evolution_url: Optional[str] = None) -> None:
        """
        Registra uma nova sessão WhatsApp.
        evolution_url (opcional): URL custom da Evolution local do cliente (modo híbrido).
        None = usa settings.evolution_url (servidor — modo padrão).
        """
        key = self._key(empresa_id, session_id)
        if key in self._sessions:
            return
        inst = _instance_name(empresa_id, session_id)
        sess = EvoSession(session_id, nome, empresa_id, evolution_url=evolution_url)
        # _ensure_instance precisa saber a URL antes de criar a instance
        self._sessions[key]     = sess
        self._inst_index[inst]  = sess
        await self._ensure_instance(inst, nome=nome)
        sess.start_heartbeat()
        asyncio.create_task(sess.fetch_qr_now())
        logger.info("[evo] Sessão registrada: %s (empresa %s, evo_url=%s)",
                    session_id, empresa_id, evolution_url or "default")

    async def remove_session(self, session_id: str, empresa_id: int) -> None:
        """
        Remove sessão localmente e deleta a instância na Evolution API.
        Chamado quando o usuário remove uma sessão pelo painel.
        """
        key  = self._key(empresa_id, session_id)
        sess = self._sessions.pop(key, None)
        if not sess:
            return
        sess.stop_heartbeat()
        sess._stop_reconnect()
        inst = _instance_name(empresa_id, session_id)
        self._inst_index.pop(inst, None)
        # Modo agente: deleta via WS
        if _is_agent_mode(sess.evolution_url):
            from . import agent_bridge as _ab
            try:
                await _ab.send_command(
                    _sio, empresa_id, "delete_instance", {"instance": inst}, timeout=30.0,
                )
                logger.info("[evo-agent] Instância deletada via agente: %s", inst)
            except Exception as exc:
                logger.debug("[evo-agent] remove_session erro: %s", exc)
            return
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                await client.delete(self._url_for_inst(inst, f"instance/delete/{inst}"), headers=_h())
            logger.info("[evo] Instância deletada: %s", inst)
        except Exception as exc:
            logger.debug("[evo] remove_session erro ao deletar instância: %s", exc)

    async def stop(self) -> None:
        """Para todos os heartbeats e reconexões (chamado no shutdown do app)."""
        for sess in list(self._sessions.values()):
            sess.stop_heartbeat()
            sess._stop_reconnect()

    # ─────────────────────────────────────────────────────────────────────────
    #  Webhook handler — ponto central de recebimento de eventos
    # ─────────────────────────────────────────────────────────────────────────

    def handle_webhook(self, payload: dict) -> None:
        """
        Processa evento recebido da Evolution API em tempo real.

        Eventos tratados:
          QRCODE_UPDATED   → novo QR disponível
          CONNECTION_UPDATE → mudança de estado (open/connecting/close)
          DISCONNECTED      → queda de conexão (trata como close, reconecta)
          LOGGED_OUT        → usuário removeu o dispositivo (NÃO reconecta)

        O event name pode vir com ponto (v2) ou underscore (v1):
          CONNECTION.UPDATE ou CONNECTION_UPDATE → ambos tratados.
        """
        event = (payload.get("event") or "").upper().replace(".", "_")
        inst  = payload.get("instance") or payload.get("instanceName") or ""
        data  = payload.get("data") or {}

        sess = self._inst_index.get(inst)
        if not sess:
            return

        if event == "QRCODE_UPDATED":
            qr = (
                data.get("base64")
                or data.get("qrcode", {}).get("base64")
                or ""
            )
            if qr:
                sess.on_qr_updated(qr)

        elif event == "CONNECTION_UPDATE":
            state = (
                data.get("state")
                or data.get("instance", {}).get("state")
                or data.get("connectionStatus")
                or data.get("instance", {}).get("connectionStatus")
                or ""
            )
            phone = (
                data.get("wuid")
                or data.get("ownerJid")     # evoapicloud v2.3.x
                or data.get("phone")
                or data.get("number")
                or None
            )
            if phone:
                phone = str(phone).split("@")[0]

            # statusReason=401 indica que o WhatsApp revogou a sessão (logout real)
            status_reason = data.get("statusReason") or data.get("status_reason") or 0
            if status_reason == 401 or state in ("loggedOut", "logged_out"):
                sess.on_logout()
            elif state:
                sess.on_connection_update(state, phone)

        elif event in ("LOGGED_OUT", "LOGOUT", "LOGOUT_INSTANCE"):
            # Evento explícito de logout (algumas versões da Evolution API enviam assim)
            sess.on_logout()

        elif event == "DISCONNECTED":
            # Queda de rede — NÃO é logout real, tenta reconectar
            sess.on_connection_update("close")

        elif event == "MESSAGES_UPSERT":
            # Nova mensagem recebida — rota para o módulo contábil se for mídia de cliente
            asyncio.create_task(self._processar_inbound(inst, data, sess.empresa_id))
            # Chat/chamados: repassa texto E mídia recebidos pro sistema externo (best-effort)
            try:
                key = data.get("key") or {}
                _remember_lid_pn(key, data)   # aprende LID→PN pra resolver presença depois
                if not key.get("fromMe") and "@g.us" not in (key.get("remoteJid") or ""):
                    msg = data.get("message") or {}
                    de = (key.get("remoteJid") or "").split("@", 1)[0]
                    # Nudge de presence-subscribe: após restart o Baileys perde o subscribe
                    # (em memória) e a Evolution para de emitir PRESENCE_UPDATE. Tenta
                    # re-disparar o subscribe ao receber msg do contato (best-effort).
                    if de:
                        asyncio.create_task(self._nudge_presence_subscribe(inst, de))
                    mtype = data.get("messageType") or ""
                    _MEDIA = {
                        "imageMessage", "documentMessage", "documentWithCaptionMessage",
                        "audioMessage", "videoMessage", "ptvMessage", "stickerMessage",
                    }
                    if mtype in _MEDIA:
                        asyncio.create_task(self._forward_chat_media(sess.empresa_id, inst, data))
                    else:
                        texto = msg.get("conversation") or (msg.get("extendedTextMessage") or {}).get("text") or ""
                        if texto:
                            asyncio.create_task(self._forward_chat(sess.empresa_id, {
                                "tipo": "mensagem", "de": de, "texto": texto,
                                "nome": data.get("pushName") or "",
                                "message_id": key.get("id") or "",
                                "sessao_id": sess.session_id,      # qual sessão/número recebeu (SGADesk)
                                "numero_conectado": sess.phone,    # número conectado (rótulo)
                            }))
            except Exception:
                pass

        elif event == "PRESENCE_UPDATE":
            # handle_webhook é SYNC → presença (que pode consultar a Evolution) vai em task async
            asyncio.create_task(self._handle_presence(inst, data, sess.empresa_id))

        elif event in ("MESSAGES_UPDATE", "MESSAGE_UPDATE"):
            # ACK de entrega/leitura (modo servidor/Evolution) → atualiza status no banco
            # + repassa webhook 'status' pro sistema externo (SGADesk, duplo-check ao vivo)
            asyncio.create_task(self._on_message_update(data, sess))

    async def _on_message_update(self, data, sess=None) -> None:
        """Processa ACK de status (SERVER_ACK/DELIVERY_ACK/READ/PLAYED/ERROR):
        atualiza mensagens pelo wa_msg_id E repassa um webhook tipo='status' ao
        sistema externo (SGADesk) pra duplo-check ao vivo. Só vale modo servidor."""
        try:
            from ..core.database import get_db_direct
            items = data if isinstance(data, list) else [data]
            for it in items:
                if not isinstance(it, dict):
                    continue
                key = it.get("key") or {}
                mid = key.get("id") or it.get("keyId") or it.get("id")
                raw = it.get("status") or (it.get("update") or {}).get("status") or ""
                status = str(raw).upper()
                if not mid or not status:
                    continue
                # Baileys ack → estado externo + (opcional) update no banco
                if status in ("READ", "PLAYED", "4", "5"):
                    estado = "lida"
                    sql = ("UPDATE mensagens SET status='read', read_at=NOW(), "
                           "delivered_at=COALESCE(delivered_at, NOW()) WHERE wa_msg_id=?")
                elif status in ("DELIVERY_ACK", "DELIVERED", "3"):
                    estado = "entregue"
                    sql = ("UPDATE mensagens SET delivered_at=COALESCE(delivered_at, NOW()), "
                           "status=CASE WHEN status='read' THEN status ELSE 'delivered' END WHERE wa_msg_id=?")
                elif status in ("SERVER_ACK", "2"):
                    estado, sql = "enviada", None
                elif status in ("ERROR", "0"):
                    estado, sql = "falha", None
                else:
                    continue
                if sql:
                    async with get_db_direct() as db:
                        await db.execute(sql, (str(mid),))
                        await db.commit()
                # Repassa ao sistema externo (best-effort; no-op se a empresa não tem
                # webhook configurado). SGADesk casa pelo message_id (externalId).
                if sess is not None:
                    de = (key.get("remoteJid") or "").split("@", 1)[0]
                    asyncio.create_task(self._forward_chat(sess.empresa_id, {
                        "tipo": "status",
                        "message_id": str(mid),
                        "estado": estado,
                        "de": de,
                        "sessao_id": sess.session_id,
                        "numero_conectado": sess.phone,
                    }))
        except Exception as exc:
            logger.debug("[evo] message_update erro: %s", exc)

    # ─────────────────────────────────────────────────────────────────────────
    #  Provisiona instância + webhook na Evolution API
    # ─────────────────────────────────────────────────────────────────────────

    async def _ensure_instance(self, inst: str, nome: str = "ZapDin") -> bool:
        """
        Garante que a instância existe na Evolution API com webhook configurado.
        Se já existir, apenas atualiza a URL do webhook (caso tenha mudado de porta).
        Se não existir, cria uma nova instância com Baileys + webhook.
        """
        # Modo agente: delega ao agente local — webhook reverso vem pelo WS
        sess_agent = self._inst_index.get(inst)
        if sess_agent and _is_agent_mode(sess_agent.evolution_url):
            from . import agent_bridge as _ab
            try:
                resp = await _ab.send_command(
                    _sio, sess_agent.empresa_id, "create_instance",
                    {"instance": inst, "nome": nome}, timeout=60.0,
                )
                return bool(resp.get("ok"))
            except Exception as exc:
                logger.warning("[evo-agent] _ensure_instance %s: %s", inst, exc)
                return False

        wh_url = _webhook_url()
        webhook_cfg = {
            "url":      wh_url,
            "byEvents": False,
            "base64":   False,
            "events":   [
                "QRCODE_UPDATED",
                "CONNECTION_UPDATE",
                "LOGOUT_INSTANCE",
                "MESSAGES_UPSERT",
                "MESSAGES_UPDATE",
                "SEND_MESSAGE",
                "PRESENCE_UPDATE",
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                # Verifica se já existe
                r = await client.get(_url("instance/fetchInstances"), headers=_h())
                if r.status_code == 200:
                    existentes = {
                        i.get("instance", {}).get("instanceName")
                        for i in r.json()
                    }
                    if inst in existentes:
                        # Atualiza webhook (URL pode ter mudado de porta/IP)
                        await client.post(
                            self._url_for_inst(inst, f"webhook/set/{inst}"),
                            json=webhook_cfg,
                            headers=_h(),
                        )
                        logger.info("[evo] Instância %s já existe — webhook atualizado", inst)
                        return True

                # Cria nova instância com webhook já configurado
                r2 = await client.post(
                    _url("instance/create"),
                    json={
                        "instanceName":       inst,
                        "qrcode":             True,
                        "integration":        "WHATSAPP-BAILEYS",
                        "webhook":            webhook_cfg,
                        "browserDescription": [nome or "ZapDin", "Desktop", "3.0"],
                    },
                    headers=_h(),
                )
                logger.info("[evo] Criando instância %s → HTTP %s", inst, r2.status_code)
                if r2.status_code in (200, 201):
                    # Configura webhook separadamente (compatibilidade v1/v2)
                    await client.post(
                        self._url_for_inst(inst, f"webhook/set/{inst}"),
                        json=webhook_cfg,
                        headers=_h(),
                    )
                    return True
                return False
        except Exception as exc:
            logger.error("[evo] _ensure_instance [%s]: %s", inst, exc)
            return False

    # ─────────────────────────────────────────────────────────────────────────
    #  Interface pública
    # ─────────────────────────────────────────────────────────────────────────

    def _connected_ids(self, empresa_id: int) -> list:
        prefix = f"{empresa_id}:"
        return [
            k.split(":", 1)[1]
            for k, s in self._sessions.items()
            if k.startswith(prefix) and s.status == "connected"
        ]

    def _rr_pick(self, ids: list) -> Optional[str]:
        if not ids:
            return None
        idx = self._rr_index % len(ids)
        self._rr_index += 1
        return ids[idx]

    def pick_session(self, empresa_id: int) -> Optional[str]:
        """Sessão conectada (round-robin), sem filtro de propósito."""
        return self._rr_pick(self._connected_ids(empresa_id))

    async def pick_session_uso(self, empresa_id: int, uso: Optional[str] = None,
                               strict: bool = False) -> Optional[str]:
        """Escolhe sessão conectada por PROPÓSITO (usos). strict=True → só envia se
        houver número com aquele propósito (senão None). strict=False → cai em qualquer."""
        conectadas = self._connected_ids(empresa_id)
        if not conectadas or not uso:
            return self._rr_pick(conectadas)
        # Lê usos das sessões conectadas no banco
        import json as _json
        usos_map = {}
        try:
            from ..core.database import get_db_direct
            async with get_db_direct() as db:
                async with db.execute(
                    "SELECT id, usos FROM sessoes_wa WHERE empresa_id=? AND status='connected'",
                    (empresa_id,),
                ) as cur:
                    for r in await cur.fetchall():
                        try:
                            usos_map[r["id"]] = _json.loads(r["usos"]) if r["usos"] else []
                        except Exception:
                            usos_map[r["id"]] = []
        except Exception as exc:
            logger.debug("[evo] pick_session_uso DB erro: %s", exc)
        match = [sid for sid in conectadas if uso in (usos_map.get(sid) or [])]
        if match:
            return self._rr_pick(match)
        if strict:
            return None
        return self._rr_pick(conectadas)

    def get_qr(self, session_id: str, empresa_id: int) -> Optional[str]:
        """
        Retorna o QR code atual (base64) para exibição no frontend.
        Se não tiver QR e a sessão não estiver conectada, solicita um imediatamente.
        """
        sess = self._sessions.get(self._key(empresa_id, session_id))
        if not sess:
            return None
        # Solicita QR se não tiver e não estiver conectado
        if not sess.qr_data and sess.status != "connected":
            asyncio.create_task(sess.fetch_qr_now())
        return sess.qr_data

    async def _nudge_presence_subscribe(self, inst: str, pn: str) -> None:
        """Best-effort: re-dispara o presence-subscribe do Baileys via Evolution.
        Após restart do app, a Evolution para de emitir PRESENCE_UPDATE (subscribe em
        memória perdido). A Evolution não expõe endpoint público de subscribe, mas
        consultar o contato/numero costuma reativar o subscribe interno do Baileys.
        Throttle 5min por contato."""
        import time as _t
        k = f"{inst}|{pn}"
        now = _t.time()
        if now - _PRESENCE_NUDGE.get(k, 0.0) < 300:
            return
        _PRESENCE_NUDGE[k] = now
        num = phone_for_wa(pn) or pn
        for path, body in (
            (f"chat/whatsappNumbers/{inst}", {"numbers": [num]}),
            (f"chat/fetchProfile/{inst}", {"number": num}),
        ):
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    await client.post(self._url_for_inst(inst, path), json=body, headers=_h())
            except Exception:
                pass

    async def _handle_presence(self, inst: str, data: dict, empresa_id: int) -> None:
        """Repassa presença (digitando/online) pro sistema externo. Evolution v2.3 manda
        só <lid>@lid → resolve PN (campos auxiliares + cache + findContacts da Evolution).
        Descarta se não resolver (não manda LID lixo)."""
        try:
            _remember_lid_pn(data)
            de = _resolve_presence_pn(data)
            if not de:
                _id = str(data.get("id") or "")
                if _id.endswith("@lid"):
                    await self._evo_populate_lid_cache(inst)
                    de = _resolve_presence_pn(data)
            if not de or not de.startswith("55"):
                logger.info("[zapdin-dbg] PRESENCE DESCARTADA (sem PN): id=%s cache=%d",
                            data.get("id"), len(_LID_PN_CACHE))
                return
            logger.info("[zapdin-dbg] PRESENCE resolvida: id=%s -> pn=%s", data.get("id"), de)
            pres = data.get("presences") or {}
            st = ""
            if isinstance(pres, dict):
                for _k, v in pres.items():
                    st = (v or {}).get("lastKnownPresence") or st
            _sp = self._inst_index.get(inst)
            await self._forward_chat(empresa_id, {
                "tipo": "presenca", "de": de, "estado": st,
                "sessao_id": _sp.session_id if _sp else None,
                "numero_conectado": _sp.phone if _sp else None,
            })
        except Exception as exc:
            logger.debug("[evo] _handle_presence erro: %s", exc)

    async def _evo_populate_lid_cache(self, inst: str) -> None:
        """Resolve LID→PN consultando a Evolution (ela mantém o mapping internamente).
        Evolution v2.3 manda PRESENCE_UPDATE só com <lid>@lid, sem PN auxiliar e sem o
        LID aparecer nas mensagens → cache não aprende sozinho. Aqui puxamos os contatos
        e aprendemos todos os pares LID↔PN de uma vez (scan agnóstico de campo). Throttle
        por instância pra não martelar a API."""
        import time as _t
        now = _t.time()
        if now - _LID_FETCH.get(inst, 0.0) < 60:
            return
        _LID_FETCH[inst] = now
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    self._url_for_inst(inst, f"chat/findContacts/{inst}"),
                    json={"where": {}}, headers=_h(),
                )
            if r.status_code not in (200, 201):
                logger.info("[zapdin-dbg] findContacts HTTP %s: %s", r.status_code, r.text[:300])
                return
            data = r.json()
            rows = data if isinstance(data, list) else (data.get("contacts") or data.get("data") or [])
            import json as _j
            learned = 0
            for row in rows:
                blob = _j.dumps(row, default=str)
                pns = _re.findall(r"(55\d{10,11})@s\.whatsapp\.net", blob)
                lids = _re.findall(r"(\d{6,})@lid", blob)
                if pns and lids:
                    for lid in lids:
                        if lid not in _LID_PN_CACHE:
                            _LID_PN_CACHE[lid] = pns[0]; learned += 1
            logger.info("[zapdin-dbg] findContacts: %d contatos, aprendidos=%d, cache=%d",
                        len(rows), learned, len(_LID_PN_CACHE))
            if rows and learned == 0:
                logger.info("[zapdin-dbg] contato sample=%s", _j.dumps(rows[0], default=str)[:400])
        except Exception as exc:
            logger.info("[zapdin-dbg] findContacts erro: %s", exc)

    def get_status(self, empresa_id: int) -> list:
        """Retorna status de todas as sessões desta empresa."""
        prefix = f"{empresa_id}:"
        return [
            {
                "id":            k.split(":", 1)[1],
                "nome":          s.nome,
                "status":        s.status,
                "phone":         s.phone,
                "evolution_url": s.evolution_url,
                "modo":          "local" if s.evolution_url else "servidor",
            }
            for k, s in self._sessions.items()
            if k.startswith(prefix)
        ]

    # ─────────────────────────────────────────────────────────────────────────
    #  Envio de mensagens
    # ─────────────────────────────────────────────────────────────────────────

    def _is_agent_session(self, empresa_id: int, session_id: str) -> bool:
        sess = self._sessions.get(self._key(empresa_id, session_id))
        return bool(sess and _is_agent_mode(sess.evolution_url))

    def _verifier_instance(self) -> Optional[str]:
        """Nome de uma instância Evolution SERVIDOR conectada, pra usar como ÁRBITRO
        do onWhatsApp. A checagem de existência é query de protocolo — independe da
        empresa — então serve pra validar números de postos em modo agente (onde o
        WhatsApp Web dá falso 'não tem WhatsApp' em conta degradada)."""
        for inst, sess in self._inst_index.items():
            try:
                if getattr(sess, "status", "") == "connected" and not _is_agent_mode(sess.evolution_url):
                    return inst
            except Exception:
                continue
        return None

    async def number_exists(self, empresa_id: int, session_id: str, phone: str):
        """Checa se o número tem WhatsApp (Evolution onWhatsApp). Retorna True/False;
        None se não dá pra saber. No modo AGENTE (sem onWhatsApp próprio) usa uma
        instância SERVIDOR conectada como árbitro."""
        if self._is_agent_session(empresa_id, session_id):
            inst = self._verifier_instance()
            if not inst:
                return None  # sem árbitro disponível — não dá pra checar
        else:
            inst = _instance_name(empresa_id, session_id)
        num = phone_for_wa(phone)
        if not num:
            return None
        # Cache TTL: existência quase não muda. Evita marretar o onWhatsApp do árbitro
        # (proteção do número servidor) e corta latência por envio.
        import time as _t
        now = _t.monotonic()
        hit = _NUMEXIST_CACHE.get(num)
        if hit is not None and (now - hit[1]) < _NUMEXIST_TTL:
            return hit[0]
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    self._url_for_inst(inst, f"chat/whatsappNumbers/{inst}"),
                    json={"numbers": [num]}, headers=_h(),
                )
            if r.status_code in (200, 201):
                arr = r.json()
                if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                    val = bool(arr[0].get("exists"))
                    _NUMEXIST_CACHE[num] = (val, now)
                    return val
            return None
        except Exception as exc:
            logger.debug("[evo] number_exists erro: %s", exc)
            return None

    async def get_profile_pic(self, empresa_id: int, session_id: str, number: str) -> Optional[str]:
        """Foto de perfil (profilePicUrl CACHEADA) do contato — SGADesk avatar.
        Fonte primária: findContacts (cacheado, confiável). Fallback: fetchProfilePictureUrl
        (ao vivo, quase sempre null por privacidade). Retorna URL ou None. Modo agente = None
        (findContacts é Evolution-only). Cache TTL 6h (inclui None, evita bater à toa)."""
        if self._is_agent_session(empresa_id, session_id):
            return None
        inst = _instance_name(empresa_id, session_id)
        num = phone_for_wa(number)
        if not num:
            return None
        import time as _t
        ck, now = f"{inst}:{num}", _t.monotonic()
        hit = _PROFILEPIC_CACHE.get(ck)
        if hit is not None and (now - hit[1]) < _PROFILEPIC_TTL:
            return hit[0]
        jid = f"{num}@s.whatsapp.net"
        url = None
        # 1) findContacts (cacheado)
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                r = await client.post(self._url_for_inst(inst, f"chat/findContacts/{inst}"),
                                      json={"where": {"remoteJid": jid}}, headers=_h())
            if r.status_code in (200, 201):
                j = r.json()
                arr = j if isinstance(j, list) else (j.get("data") if isinstance(j, dict) else None)
                if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                    url = arr[0].get("profilePicUrl") or arr[0].get("profilePictureUrl")
                elif isinstance(j, dict):
                    url = j.get("profilePicUrl") or j.get("profilePictureUrl")
        except Exception as exc:
            logger.debug("[evo] findContacts erro: %s", exc)
        # 2) fallback ao vivo
        if not url:
            try:
                async with httpx.AsyncClient(timeout=12.0) as client:
                    r = await client.post(self._url_for_inst(inst, f"chat/fetchProfilePictureUrl/{inst}"),
                                          json={"number": num}, headers=_h())
                if r.status_code in (200, 201):
                    j = r.json()
                    url = (j.get("profilePictureUrl") or j.get("profilePicUrl")
                           or (j.get("data") or {}).get("profilePictureUrl") if isinstance(j, dict) else None)
            except Exception as exc:
                logger.debug("[evo] fetchProfilePictureUrl erro: %s", exc)
        _PROFILEPIC_CACHE[ck] = (url or None, now)
        return url or None

    def _note_agent_send(self, inst: str, ok: bool, err: str = "") -> None:
        """Conta envios sem resposta do agente. 3 seguidos (com a sessão ainda
        'connected') = zumbi parcial → força re-QR."""
        sess = self._inst_index.get(inst)
        if not sess:
            return
        if ok:
            sess._send_fail_streak = 0
            return
        e = err or ""
        if "Timeout" in e or "não respondeu" in e or "agent:" in e:
            sess._send_fail_streak = getattr(sess, "_send_fail_streak", 0) + 1
            # REGRA: NUNCA deslogar o cliente automaticamente. Antes 3 timeouts disparavam
            # _force_agent_reauth → delete_instance (limpa perfil = LOGOUT). Removido.
            # Agora só ALERTA um humano; quem decide reescanear é pessoa, não o sistema.
            if sess._send_fail_streak == 3 and sess.status == "connected":
                logger.warning("[evo] [%s] 3 envios sem resposta — sessão pode estar travada. "
                               "ALERTA (não desloga automático).", sess.session_id)
                try:
                    from . import telegram_service
                    asyncio.create_task(telegram_service.notify_send_failure(
                        sess.nome, "—", "WhatsApp possivelmente travado (envios sem resposta) — verificar painel"))
                except Exception:
                    pass

    async def _force_agent_reauth(self, sess) -> None:
        """Zumbi parcial: agente reporta connected mas não envia (página WA travada).
        Manda delete_instance (logout + limpa perfil no agente) → QR novo aparece
        sozinho, sem limpeza manual. Throttle de 10min evita loop."""
        import time as _t
        now = _t.time()
        if now - getattr(sess, "_last_reauth", 0.0) < 600:
            return
        sess._last_reauth = now
        sess._send_fail_streak = 0
        inst = _instance_name(sess.empresa_id, sess.session_id)
        logger.warning("[evo] [%s] zumbi parcial (3 envios sem resposta) → forçando re-QR", sess.session_id)
        sess.status = "disconnected"
        sess.phone = None
        await sess._persist_status()
        try:
            from . import agent_bridge as _ab
            await _ab.send_command(_sio, sess.empresa_id, "delete_instance", {"instance": inst}, timeout=30.0)
        except Exception as exc:
            logger.debug("[evo] force_reauth delete_instance erro: %s", exc)
        try:
            asyncio.create_task(sess.fetch_qr_now())   # já busca o QR novo
        except Exception:
            pass
        try:
            from . import telegram_service
            asyncio.create_task(telegram_service.notify_send_failure(
                sess.nome, "—", "WhatsApp travado — re-QR forçado, reescanear no painel"))
        except Exception:
            pass

    async def send_text(
        self, session_id: str, empresa_id: int, phone: str, message: str,
        composing_delay: float = 0.0,
    ) -> Tuple[bool, Optional[str]]:
        """Envia mensagem de texto para um número."""
        inst   = _instance_name(empresa_id, session_id)
        number = phone_for_wa(phone) or phone.strip().lstrip("+").replace(" ", "")
        # Status de entrega do último envio (lido pelo queue_worker). 'sent'|'delivered'|'read'
        self._last_send_status = None
        self._last_wa_msg_id = None   # id da msg no WhatsApp (Evolution) p/ casar o ACK

        # Modo agente: roteia comando via WebSocket /agent
        if self._is_agent_session(empresa_id, session_id):
            from . import agent_bridge as _ab
            payload_agent = {
                "instance": inst,
                "number":   number,
                "text":     message,
                "delay_ms": int(composing_delay * 1000) if composing_delay > 0 else 0,
            }
            try:
                # 90s: o agente pode levar ~30s só abrindo o chat + achando o
                # composer. Default 30s estourava antes e mascarava o erro real.
                resp = await _ab.send_command(_sio, empresa_id, "send_text", payload_agent, timeout=45.0)
                if resp.get("ok"):
                    # Agente reporta o tiquinho lido na tela (sent/delivered/read)
                    self._last_send_status = resp.get("status") or "sent"
                    self._note_agent_send(inst, True)
                    try:
                        from . import telegram_service
                        telegram_service.record_sent("text")
                    except Exception:
                        pass
                    return True, None
                _err = str(resp.get("error") or "agent error")
                self._note_agent_send(inst, False, _err)
                return False, _err
            except Exception as exc:
                _err = f"agent: {exc}"
                self._note_agent_send(inst, False, _err)
                return False, _err

        try:
            payload: dict = {"number": number, "text": message}
            if composing_delay > 0:
                payload["delay"] = int(composing_delay * 1000)  # ms — Evolution API simula "digitando..."
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.post(
                    self._url_for_inst(inst, f"message/sendText/{inst}"),
                    json=payload,
                    headers=_h(),
                )
            if r.status_code in (200, 201):
                self._last_send_status = "sent"  # delivered/read vêm depois via webhook MESSAGES_UPDATE
                try:
                    _j = r.json()
                    self._last_wa_msg_id = ((_j.get("key") or {}).get("id")) or None
                except Exception:
                    self._last_wa_msg_id = None
                try:
                    from . import telegram_service
                    telegram_service.record_sent("text")
                except Exception:
                    pass
                return True, None
            err = f"HTTP {r.status_code}: {r.text[:200]}"
            try:
                from . import telegram_service
                telegram_service.record_error()
                sess = self._sessions.get(self._key(empresa_id, session_id))
                nome = sess.nome if sess else session_id
                asyncio.create_task(telegram_service.notify_send_failure(nome, phone, err))
            except Exception:
                pass
            return False, err
        except Exception as exc:
            err = str(exc)
            try:
                from . import telegram_service
                telegram_service.record_error()
            except Exception:
                pass
            return False, err

    async def send_file(
        self,
        session_id: str,
        empresa_id: int,
        phone: str,
        file_path: str,
        filename: str,
        caption: Optional[str] = None,
        composing_delay: float = 0.0,
    ) -> Tuple[bool, Optional[str]]:
        """Envia arquivo (imagem, PDF, áudio, etc.) para um número."""
        inst   = _instance_name(empresa_id, session_id)
        number = phone_for_wa(phone) or phone.strip().lstrip("+").replace(" ", "")
        ext    = os.path.splitext(filename)[1].lower()
        mtype  = _media_type(ext)
        mime   = _mimetype(ext)
        return await self._send_file_b64(inst, number, file_path, filename, mime, mtype, caption, composing_delay)

    async def _send_file_b64(
        self, inst, number, file_path, filename, mime, mtype, caption, composing_delay: float = 0.0
    ) -> Tuple[bool, Optional[str]]:
        """Envia arquivo como data URI base64 (mais confiável que URL pública)."""
        self._last_wa_msg_id = None   # id da msg no WhatsApp p/ casar o ACK (SGADesk)
        try:
            def _read_blocking():
                with open(file_path, "rb") as f:
                    return f.read()
            raw = await asyncio.to_thread(_read_blocking)
            # Evolution API aceita base64 puro — data URI (data:mime;base64,...) não é suportado
            b64 = base64.b64encode(raw).decode()
            payload = {
                "number":    number,
                "mediatype": mtype,
                "mimetype":  mime,
                "caption":   caption or "",
                "media":     b64,
                "fileName":  filename,
            }
            if composing_delay > 0:
                payload["delay"] = int(composing_delay * 1000)  # ms — simula "gravando áudio" / "enviando arquivo"

            # Modo agente: roteia via WS em vez de HTTP direto
            sess_agent = self._inst_index.get(inst)
            if sess_agent and _is_agent_mode(sess_agent.evolution_url):
                from . import agent_bridge as _ab
                payload_agent = {"instance": inst, **payload}
                try:
                    resp = await _ab.send_command(
                        _sio, sess_agent.empresa_id, "send_media", payload_agent, timeout=90.0,
                    )
                    if resp.get("ok"):
                        logger.info("[evo-agent] send_file OK: %s → %s", filename, number)
                        self._last_wa_msg_id = ((resp.get("key") or {}).get("id")) or resp.get("message_id")
                        try:
                            from . import telegram_service
                            telegram_service.record_sent("file")
                        except Exception:
                            pass
                        return True, None
                    return False, str(resp.get("error") or "agent error")
                except Exception as exc:
                    return False, f"agent: {exc}"

            # Áudio: WhatsApp só toca nota de voz se enviada via sendWhatsAppAudio
            # (Evolution converte p/ opus). sendMedia manda como anexo e não toca.
            if mtype == "audio":
                endpoint = f"message/sendWhatsAppAudio/{inst}"
                audio_payload = {"number": number, "audio": b64}
                if composing_delay > 0:
                    audio_payload["delay"] = int(composing_delay * 1000)
                send_payload = audio_payload
            else:
                endpoint = f"message/sendMedia/{inst}"
                send_payload = payload
            async with httpx.AsyncClient(timeout=90.0) as client:
                r = await client.post(
                    self._url_for_inst(inst, endpoint),
                    json=send_payload,
                    headers=_h(),
                )
            if r.status_code in (200, 201):
                logger.info("[evo] send_file OK: %s → %s", filename, number)
                try:
                    self._last_wa_msg_id = ((r.json().get("key") or {}).get("id")) or None
                except Exception:
                    self._last_wa_msg_id = None
                try:
                    from . import telegram_service
                    telegram_service.record_sent("file")
                except Exception:
                    pass
                return True, None
            err = f"HTTP {r.status_code}: {r.text[:200]}"
            try:
                from . import telegram_service
                telegram_service.record_error()
                sess = self._inst_index.get(inst)
                nome = sess.nome if sess else inst
                asyncio.create_task(telegram_service.notify_send_failure(nome, number, err))
            except Exception:
                pass
            return False, err
        except Exception as exc:
            err = str(exc)
            try:
                from . import telegram_service
                telegram_service.record_error()
            except Exception:
                pass
            return False, err

    def schedule_status_check(self, arquivo_id, session_id, empresa_id, phone, table="arquivos"):
        pass   # reservado para uso futuro (Evolution webhook MESSAGES_UPDATE cobriria isso)

    async def _processar_inbound(self, inst: str, data: dict, tenant_id: int = 0) -> None:
        """Inbound de TEXTO → chatbot geral da empresa dona da sessão.
        (Contábil/OCR de mídia foi extraído pro projeto zapdincontabil.)"""
        try:
            key = data.get("key") or {}
            if key.get("fromMe"):
                return
            remote_jid = key.get("remoteJid") or ""
            if "@g.us" in remote_jid:
                return
            msg_type = data.get("messageType") or ""
            msg = data.get("message") or {}
            _MEDIA = {"imageMessage", "documentMessage", "documentWithCaptionMessage", "ptvMessage"}
            if msg_type in _MEDIA:
                return  # mídia não é mais tratada aqui (contábil saiu)
            texto = (
                msg.get("conversation")
                or (msg.get("extendedTextMessage") or {}).get("text")
                or ""
            ).strip()
            if not texto:
                return
            if "@lid" in remote_jid:
                alt = key.get("remoteJidAlt") or ""
                eff = alt or remote_jid
            else:
                eff = remote_jid
            phone_full = eff.split("@")[0]
            # Opt-out automático (PARE/SAIR) — se for comando, trata e NÃO passa pro chatbot
            try:
                from ..services.opt_out_service import handle_inbound as _optout
                if await _optout(tenant_id, phone_full, texto):
                    return
            except Exception as exc:
                logger.debug("[opt-out] inbound erro: %s", exc)
            from ..services.chatbot_service import responder_mensagem
            asyncio.create_task(responder_mensagem(tenant_id, phone_full, texto, inst, ""))
        except Exception as exc:
            logger.error("[chatbot] erro no inbound: %s", exc, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers de tipo de mídia
# ─────────────────────────────────────────────────────────────────────────────

def _media_type(ext: str) -> str:
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        return "image"
    if ext in {".mp4", ".avi", ".mov", ".mkv"}:
        return "video"
    if ext in {".mp3", ".ogg", ".wav", ".m4a", ".opus"}:
        return "audio"
    return "document"


def _mimetype(ext: str) -> str:
    return {
        ".jpg":  "image/jpeg",  ".jpeg": "image/jpeg",  ".png": "image/png",
        ".gif":  "image/gif",   ".webp": "image/webp",
        ".mp4":  "video/mp4",   ".mov":  "video/quicktime",
        ".mp3":  "audio/mpeg",  ".ogg":  "audio/ogg",
        ".wav":  "audio/wav",   ".m4a":  "audio/mp4",   ".opus": "audio/opus",
        ".pdf":  "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".zip":  "application/zip",
    }.get(ext, "application/octet-stream")


# ── Instância global ──────────────────────────────────────────────────────────
evo_manager = EvoManager()
