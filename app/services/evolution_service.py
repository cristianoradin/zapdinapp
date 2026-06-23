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
            elif state != "open" and self.status == "connected":
                logger.warning("[evo-agent] [%s] heartbeat detectou queda", self.session_id)
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
                            presence: str = "composing", delay_ms: int = 1500) -> tuple:
        """Envia presença (composing/paused/available) → cliente vê 'digitando…'.
        Separado do envio de mensagem. Só Evolution."""
        sid = self._first_session_id(empresa_id)
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
            url, secret = "", ""
            async with get_db_direct() as db:
                async with db.execute(
                    "SELECT key, value FROM config WHERE empresa_id=? "
                    "AND key IN ('chat_webhook_url', 'chat_webhook_secret')",
                    (empresa_id,),
                ) as cur:
                    rows = await cur.fetchall()
            for r in rows:
                if r["key"] == "chat_webhook_url":
                    url = (r["value"] or "")
                elif r["key"] == "chat_webhook_secret":
                    secret = (r["value"] or "")
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
        payload = {
            "tipo": "midia",
            "de": de,
            "message_id": key.get("id") or "",
            "mime": mime2 or mime,
            "nome_arquivo": fname2 or fname or "arquivo",
            "caption": caption,
            "nome": data.get("pushName") or "",
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
                if not key.get("fromMe") and "@g.us" not in (key.get("remoteJid") or ""):
                    msg = data.get("message") or {}
                    de = (key.get("remoteJid") or "").split("@", 1)[0]
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
                            }))
            except Exception:
                pass

        elif event == "PRESENCE_UPDATE":
            # Cliente digitando/parou → repassa pro sistema externo
            try:
                jid = data.get("id") or data.get("remoteJid") or ""
                pres = data.get("presences") or {}
                st = ""
                if isinstance(pres, dict):
                    for _k, v in pres.items():
                        st = (v or {}).get("lastKnownPresence") or st
                asyncio.create_task(self._forward_chat(sess.empresa_id, {
                    "tipo": "presenca", "de": jid.split("@", 1)[0], "estado": st,
                }))
            except Exception:
                pass

        elif event in ("MESSAGES_UPDATE", "MESSAGE_UPDATE"):
            # ACK de entrega/leitura (modo servidor/Evolution) → atualiza status no banco
            asyncio.create_task(self._on_message_update(data))

    async def _on_message_update(self, data) -> None:
        """Processa ACK de status (DELIVERY_ACK/READ/PLAYED) e atualiza mensagens
        pelo wa_msg_id. Só vale modo servidor (Evolution emite esses eventos)."""
        try:
            from ..core.database import get_db_direct
            items = data if isinstance(data, list) else [data]
            for it in items:
                if not isinstance(it, dict):
                    continue
                key = it.get("key") or {}
                mid = key.get("id") or it.get("keyId") or it.get("id")
                status = (it.get("status") or (it.get("update") or {}).get("status") or "").upper()
                if not mid or not status:
                    continue
                if status in ("READ", "PLAYED"):
                    sql = ("UPDATE mensagens SET status='read', read_at=NOW(), "
                           "delivered_at=COALESCE(delivered_at, NOW()) WHERE wa_msg_id=?")
                elif status in ("DELIVERY_ACK", "DELIVERED"):
                    sql = ("UPDATE mensagens SET delivered_at=COALESCE(delivered_at, NOW()), "
                           "status=CASE WHEN status='read' THEN status ELSE 'delivered' END WHERE wa_msg_id=?")
                else:
                    continue
                async with get_db_direct() as db:
                    await db.execute(sql, (str(mid),))
                    await db.commit()
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

    async def number_exists(self, empresa_id: int, session_id: str, phone: str):
        """Checa se o número tem WhatsApp (Evolution onWhatsApp). Retorna:
        True/False no modo servidor; None se não dá pra saber (agente, erro, sem resposta)."""
        if self._is_agent_session(empresa_id, session_id):
            return None  # agente não tem onWhatsApp — não checa
        inst = _instance_name(empresa_id, session_id)
        num = phone_for_wa(phone)
        if not num:
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    self._url_for_inst(inst, f"chat/whatsappNumbers/{inst}"),
                    json={"numbers": [num]}, headers=_h(),
                )
            if r.status_code in (200, 201):
                arr = r.json()
                if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                    return bool(arr[0].get("exists"))
            return None
        except Exception as exc:
            logger.debug("[evo] number_exists erro: %s", exc)
            return None

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
                resp = await _ab.send_command(_sio, empresa_id, "send_text", payload_agent, timeout=90.0)
                if resp.get("ok"):
                    # Agente reporta o tiquinho lido na tela (sent/delivered/read)
                    self._last_send_status = resp.get("status") or "sent"
                    try:
                        from . import telegram_service
                        telegram_service.record_sent("text")
                    except Exception:
                        pass
                    return True, None
                return False, str(resp.get("error") or "agent error")
            except Exception as exc:
                return False, f"agent: {exc}"

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
