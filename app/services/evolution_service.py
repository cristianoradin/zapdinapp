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
import logging
import os
import secrets
import threading
from typing import Dict, List, Optional, Tuple

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0

# Backoff em segundos para tentativas de reconexão: 5, 10, 20, 40, 60, 60, 60...
_RECONNECT_BACKOFF: List[int] = [5, 10, 20, 40, 60, 60, 60]

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
    """URL que a Evolution API vai chamar quando houver eventos."""
    return f"http://127.0.0.1:{settings.port}/api/evo-webhook"


# ─────────────────────────────────────────────────────────────────────────────
#  Sessão local — representa uma instância do WhatsApp
# ─────────────────────────────────────────────────────────────────────────────

class EvoSession:
    def __init__(self, session_id: str, nome: str, empresa_id: int):
        self.session_id  = session_id
        self.nome        = nome
        self.empresa_id  = empresa_id
        self.status      = "disconnected"
        self.qr_data:  Optional[str] = None
        self.phone:    Optional[str] = None

        # True somente quando o usuário removeu o dispositivo no celular.
        # Neste caso NÃO tentamos reconectar — aguardamos novo QR.
        self._logged_out = False

        # Evita múltiplos loops de reconexão simultâneos
        self._reconnecting = False

        self._heartbeat_task:  Optional[asyncio.Task] = None
        self._reconnect_task:  Optional[asyncio.Task] = None

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

            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    # Primeiro verifica se já reconectou sozinho (Baileys faz retry interno)
                    rs = await client.get(_url(f"instance/connectionState/{inst}"), headers=_h())
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
                    r = await client.get(_url(f"instance/connect/{inst}"), headers=_h())

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
                await asyncio.sleep(60)
            elif self._reconnecting:
                # Loop de reconexão já está tratando a situação
                await asyncio.sleep(30)
            else:
                # Desconectado sem reconexão ativa — pode ter perdido o webhook
                # Força tentativa de reconexão se não for logout real
                if not self._logged_out:
                    self._start_reconnect()
                await asyncio.sleep(20)

    async def _check_state(self) -> None:
        """Consulta connectionState na Evolution API e atualiza o status local."""
        inst = _instance_name(self.empresa_id, self.session_id)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(_url(f"instance/connectionState/{inst}"), headers=_h())
        if r.status_code != 200:
            return
        data  = r.json()
        state = (
            data.get("instance", {}).get("state")
            or data.get("state")
            or "close"
        )
        # Só atualiza se mudou — evita log desnecessário
        if state == "open" and self.status != "connected":
            self.on_connection_update("open")
        elif state != "open" and self.status == "connected":
            # Estava conectado, agora não está → webhook perdido → inicia reconexão
            logger.warning("[evo] [%s] Heartbeat detectou queda — webhook perdido?", self.session_id)
            self.on_connection_update(state)

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
        try:
            # Primeiro verifica se já está conectado (evita gerar QR desnecessário)
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                rs = await client.get(_url(f"instance/connectionState/{inst}"), headers=_h())
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
                r = await client.get(_url(f"instance/connect/{inst}"), headers=_h())
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
        async with db.execute("SELECT id, nome, empresa_id FROM sessoes_wa") as cur:
            rows = await cur.fetchall()
        for row in rows:
            await self.add_session(row["id"], row["nome"], row["empresa_id"])

    async def add_session(self, session_id: str, nome: str, empresa_id: int) -> None:
        """
        Registra uma nova sessão WhatsApp.
        Garante que a instância existe na Evolution API, inicia heartbeat
        e tenta estabelecer conexão imediatamente.
        """
        key = self._key(empresa_id, session_id)
        if key in self._sessions:
            return
        inst = _instance_name(empresa_id, session_id)
        await self._ensure_instance(inst)
        sess = EvoSession(session_id, nome, empresa_id)
        self._sessions[key]     = sess
        self._inst_index[inst]  = sess
        sess.start_heartbeat()
        # Verifica estado atual imediatamente (não bloqueia o startup)
        asyncio.create_task(sess.fetch_qr_now())
        logger.info("[evo] Sessão registrada: %s (empresa %s)", session_id, empresa_id)

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
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                await client.delete(_url(f"instance/delete/{inst}"), headers=_h())
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
                or ""
            )
            phone = (
                data.get("wuid")
                or data.get("phone")
                or data.get("number")
                or None
            )

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
            asyncio.create_task(self._processar_mensagem_contabil(inst, data))

    # ─────────────────────────────────────────────────────────────────────────
    #  Provisiona instância + webhook na Evolution API
    # ─────────────────────────────────────────────────────────────────────────

    async def _ensure_instance(self, inst: str) -> bool:
        """
        Garante que a instância existe na Evolution API com webhook configurado.
        Se já existir, apenas atualiza a URL do webhook (caso tenha mudado de porta).
        Se não existir, cria uma nova instância com Baileys + webhook.
        """
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
                            _url(f"webhook/set/{inst}"),
                            json=webhook_cfg,
                            headers=_h(),
                        )
                        logger.info("[evo] Instância %s já existe — webhook atualizado", inst)
                        return True

                # Cria nova instância com webhook já configurado
                r2 = await client.post(
                    _url("instance/create"),
                    json={
                        "instanceName": inst,
                        "qrcode":       True,
                        "integration":  "WHATSAPP-BAILEYS",
                        "webhook":      webhook_cfg,
                    },
                    headers=_h(),
                )
                logger.info("[evo] Criando instância %s → HTTP %s", inst, r2.status_code)
                if r2.status_code in (200, 201):
                    # Configura webhook separadamente (compatibilidade v1/v2)
                    await client.post(
                        _url(f"webhook/set/{inst}"),
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

    def pick_session(self, empresa_id: int) -> Optional[str]:
        """
        Retorna o ID de uma sessão conectada para esta empresa (round-robin).
        Usado pelo worker de envio para balancear entre múltiplas sessões.
        """
        prefix = f"{empresa_id}:"
        connected = [
            k.split(":", 1)[1]
            for k, s in self._sessions.items()
            if k.startswith(prefix) and s.status == "connected"
        ]
        if not connected:
            return None
        idx = self._rr_index % len(connected)
        self._rr_index += 1
        return connected[idx]

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

    def get_status(self, empresa_id: int) -> list:
        """Retorna status de todas as sessões desta empresa."""
        prefix = f"{empresa_id}:"
        return [
            {
                "id":     k.split(":", 1)[1],
                "nome":   s.nome,
                "status": s.status,
                "phone":  s.phone,
            }
            for k, s in self._sessions.items()
            if k.startswith(prefix)
        ]

    # ─────────────────────────────────────────────────────────────────────────
    #  Envio de mensagens
    # ─────────────────────────────────────────────────────────────────────────

    async def send_text(
        self, session_id: str, empresa_id: int, phone: str, message: str
    ) -> Tuple[bool, Optional[str]]:
        """Envia mensagem de texto para um número."""
        inst   = _instance_name(empresa_id, session_id)
        number = phone.strip().lstrip("+").replace(" ", "")
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.post(
                    _url(f"message/sendText/{inst}"),
                    json={"number": number, "text": message},
                    headers=_h(),
                )
            if r.status_code in (200, 201):
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
    ) -> Tuple[bool, Optional[str]]:
        """Envia arquivo (imagem, PDF, áudio, etc.) para um número."""
        inst   = _instance_name(empresa_id, session_id)
        number = phone.strip().lstrip("+").replace(" ", "")
        ext    = os.path.splitext(filename)[1].lower()
        mtype  = _media_type(ext)
        mime   = _mimetype(ext)
        return await self._send_file_b64(inst, number, file_path, filename, mime, mtype, caption)

    async def _send_file_b64(
        self, inst, number, file_path, filename, mime, mtype, caption
    ) -> Tuple[bool, Optional[str]]:
        """Envia arquivo como data URI base64 (mais confiável que URL pública)."""
        try:
            with open(file_path, "rb") as f:
                raw = f.read()
            # Evolution API aceita base64 puro — data URI (data:mime;base64,...) não é suportado
            b64 = base64.b64encode(raw).decode()
            async with httpx.AsyncClient(timeout=90.0) as client:
                r = await client.post(
                    _url(f"message/sendMedia/{inst}"),
                    json={
                        "number":    number,
                        "mediatype": mtype,
                        "mimetype":  mime,
                        "caption":   caption or "",
                        "media":     b64,
                        "fileName":  filename,
                    },
                    headers=_h(),
                )
            if r.status_code in (200, 201):
                logger.info("[evo] send_file OK: %s → %s", filename, number)
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

    def schedule_status_check(self, arquivo_id, session_id, empresa_id, phone):
        pass   # reservado para uso futuro

    async def _processar_mensagem_contabil(self, inst: str, data: dict) -> None:
        """
        Processa MESSAGES_UPSERT: se o remetente for cliente cadastrado em
        empresas_contabil e enviou mídia (imagem ou PDF), baixa e enfileira OCR.
        """
        import uuid as _uuid
        import base64 as _b64
        from pathlib import Path

        try:
            key = data.get("key") or {}
            if key.get("fromMe"):
                return  # ignora mensagens enviadas pelo próprio sistema

            remote_jid = key.get("remoteJid") or ""
            if "@g.us" in remote_jid:
                return  # ignora grupos

            msg_type = data.get("messageType") or ""
            msg      = data.get("message") or {}

            # Tipos de mídia aceitos como documento fiscal
            _MEDIA_TYPES = {
                "imageMessage", "documentMessage",
                "documentWithCaptionMessage", "ptvMessage",
            }

            # Tipos de mensagem de texto simples → chatbot
            _TEXT_TYPES = {"conversation", "extendedTextMessage"}
            _is_text = (
                msg_type in _TEXT_TYPES
                or (msg_type not in _MEDIA_TYPES
                    and not any(k in msg for k in _MEDIA_TYPES))
            )

            if _is_text and msg_type not in _MEDIA_TYPES:
                # Extrai o texto
                _texto = (
                    msg.get("conversation")
                    or (msg.get("extendedTextMessage") or {}).get("text")
                    or ""
                ).strip()
                if not _texto:
                    return
                # Será preenchido após lookup de empresa — tratado abaixo
                _ROTA_CHATBOT = True
            else:
                _ROTA_CHATBOT = False

            # Extrai número do remetente
            # Evolution pode usar @lid (novo formato) ou @s.whatsapp.net (formato padrão)
            # Se for @lid, usa remoteJidAlt que contém o número real
            if "@lid" in remote_jid:
                alt_jid = key.get("remoteJidAlt") or ""
                effective_jid = alt_jid if alt_jid else remote_jid
            else:
                effective_jid = remote_jid

            phone_full  = effective_jid.split("@")[0]   # ex: "5544991099797"
            phone_local = phone_full[2:] if phone_full.startswith("55") else phone_full

            # Busca empresa pelo telefone — tenta 3 variantes de formato
            # WA pode entregar em formato antigo (10 dig) ou novo (11 dig)
            # DB pode ter qualquer um dos dois formatos
            variantes = [phone_local]
            if len(phone_local) == 10:
                # formato antigo (DDD+8) → tenta novo (DDD+9+8)
                variantes.append(phone_local[:2] + "9" + phone_local[2:])
            elif len(phone_local) == 11 and phone_local[2] == "9":
                # formato novo (DDD+9+8) → tenta antigo (DDD+8)
                variantes.append(phone_local[:2] + phone_local[3:])

            from ..core.database import get_db_direct
            async with get_db_direct() as db:
                empresa = None
                for variante in variantes:
                    async with db.execute(
                        "SELECT id, nome FROM empresas_contabil WHERE telefone=? AND ativo=TRUE",
                        (variante,)
                    ) as cur:
                        empresa = await cur.fetchone()
                    if empresa:
                        break

                if not empresa:
                    logger.debug(
                        "[contabil] MESSAGES_UPSERT de %s — não é cliente contábil cadastrado",
                        phone_local
                    )
                    return

                empresa_id   = empresa["id"]
                empresa_nome = empresa["nome"]

                # ── Roteamento: texto → chatbot, mídia → OCR ──────────────────────
                if _ROTA_CHATBOT:
                    from ..services.chatbot_service import responder_mensagem
                    asyncio.create_task(
                        responder_mensagem(empresa_id, phone_full, _texto, inst, empresa_nome)
                    )
                    return

                # ── Download da mídia via Evolution API ──────────────────────────
                # O endpoint espera {"message": {"key": ..., "message": ...}}
                async with httpx.AsyncClient(timeout=60.0) as client:
                    r = await client.post(
                        _url(f"chat/getBase64FromMediaMessage/{inst}"),
                        json={"message": {"key": key, "message": msg}, "convertToMp4": False},
                        headers=_h(),
                    )

                if r.status_code not in (200, 201):
                    logger.warning(
                        "[contabil] Falha ao baixar mídia (HTTP %s) de %s",
                        r.status_code, phone_local
                    )
                    return

                media_resp = r.json()
                b64_data   = media_resp.get("base64") or media_resp.get("data") or ""
                if not b64_data:
                    logger.warning("[contabil] Mídia sem base64 de %s", phone_local)
                    return

                # ── Determina tipo e extensão ─────────────────────────────────────
                if msg_type == "imageMessage":
                    img_msg  = msg.get("imageMessage") or {}
                    mime     = img_msg.get("mimetype") or "image/jpeg"
                    ext      = ".jpg" if "jpeg" in mime else ".png"
                    nome_arq = f"wa_{_uuid.uuid4().hex}{ext}"
                else:
                    doc_msg  = (msg.get("documentMessage")
                                or (msg.get("documentWithCaptionMessage") or {})
                                   .get("message", {}).get("documentMessage") or {})
                    mime     = doc_msg.get("mimetype") or "application/octet-stream"
                    title    = doc_msg.get("title") or doc_msg.get("fileName") or "doc"
                    raw_ext  = os.path.splitext(title)[1]
                    ext      = raw_ext if raw_ext else (".pdf" if "pdf" in mime else ".bin")
                    nome_arq = f"wa_{_uuid.uuid4().hex}{ext}"

                # ── Salva em disco ────────────────────────────────────────────────
                upload_dir = Path("data/contabil_docs")
                upload_dir.mkdir(parents=True, exist_ok=True)
                dest_path  = str(upload_dir / nome_arq)
                with open(dest_path, "wb") as fh:
                    fh.write(_b64.b64decode(b64_data))

                # ── Insere documento_fiscal e enfileira OCR ───────────────────────
                async with db.execute(
                    """INSERT INTO documentos_fiscais
                       (empresa_id, status, origem_wa, arquivo_path, arquivo_mime, arquivo_nome)
                       VALUES (?, 'ocr_pendente', ?, ?, ?, ?)""",
                    (empresa_id, phone_full, dest_path, mime, nome_arq)
                ) as cur:
                    doc_id = cur.lastrowid
                await db.commit()

                await db.execute(
                    "INSERT INTO ocr_jobs(documento_id) VALUES(?) ON CONFLICT DO NOTHING",
                    (doc_id,)
                )
                await db.execute(
                    "INSERT INTO contabil_feed(empresa_id, documento_id, tipo, descricao)"
                    " VALUES(?,?,?,?)",
                    (empresa_id, doc_id, "recebido",
                     f"Documento recebido de {empresa_nome} via WhatsApp")
                )
                await db.commit()

                logger.info(
                    "[contabil] Documento #%s recebido de %s (%s) — OCR enfileirado",
                    doc_id, empresa_nome, phone_local
                )

                # ── Dispara OCR em background ─────────────────────────────────────
                from ..services.ocr_service import extrair_dados_fiscal
                asyncio.create_task(extrair_dados_fiscal(doc_id, dest_path))

        except Exception as exc:
            logger.error("[contabil] Erro ao processar MESSAGES_UPSERT: %s", exc, exc_info=True)


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
