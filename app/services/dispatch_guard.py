"""
dispatch_guard — Disjuntor (circuit breaker) + aquecimento (ramp-up) por sessão WhatsApp.

OBJETIVO: NUNCA deixar o WhatsApp deslogar o número por rajada/volume. Não dá pra
impedir o logout pelo lado deles — mas dá pra o NOSSO sistema se auto-frear ANTES
de chegar no limite perigoso. Troca a falha catastrófica (número cai → QR manual)
por uma leve e automática (envio pausa X min → retoma sozinho; mensagem fica na fila).

Dois mecanismos, por sessao_id:

1. DISJUNTOR (breaker): teto de msgs/min e msgs/hora. Estourou → cooldown (pausa a
   sessão por N segundos). Também trip por falhas seguidas (número parou de aceitar).
   Enquanto em cooldown, check() nega → o worker pula a sessão (item continua na fila).

2. AQUECIMENTO (ramp-up): após período "frio" (sem envio por X min = reconexão ou
   pós-cooldown), as primeiras mensagens saem DEVAGAR e vão acelerando até o ritmo
   normal. Número recém-reconectado é o mais sensível ao anti-spam — começar lento
   evita o gatilho.

Tudo em memória (por processo). Reset no restart é seguro (recomeça conservador).
Limites configuráveis por empresa via tabela config (wa_max_per_min, etc.).
"""
import logging
import random
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

# Defaults conservadores (margem de segurança — WhatsApp não publica os limites reais).
DEFAULTS = {
    "max_per_min": 12,       # teto de envios por minuto por número
    "max_per_hour": 250,     # teto por hora por número
    "cooldown_secs": 300,    # pausa ao estourar teto (5 min)
    "warmup_msgs": 20,       # nº de msgs em ritmo lento após ficar "frio"
    "idle_reset_secs": 600,  # sem envio por 10 min = frio → reinicia aquecimento
    "fail_trip": 5,          # nº de falhas seguidas que dispara cooldown
}

# Estado por sessao_id
_state: dict = defaultdict(lambda: {
    "sends": deque(),         # timestamps de envios OK (janela de 1h)
    "cooldown_until": 0.0,
    "warmup_left": 0,         # quantas msgs ainda no ritmo de aquecimento
    "last_send": 0.0,
    "fail_streak": 0,
    "warned": False,          # evita spam de log/alerta de cooldown
})


def caps_from_cfg(cfg: dict) -> dict:
    """Lê os limites da config da empresa, com fallback nos defaults."""
    def _i(key, dflt):
        try:
            v = int(float(cfg.get(key, dflt)))
            return v if v > 0 else dflt
        except (TypeError, ValueError):
            return dflt
    return {
        "max_per_min":   _i("wa_max_per_min",   DEFAULTS["max_per_min"]),
        "max_per_hour":  _i("wa_max_per_hour",  DEFAULTS["max_per_hour"]),
        "cooldown_secs": _i("wa_cooldown_secs", DEFAULTS["cooldown_secs"]),
        "warmup_msgs":   _i("wa_warmup_msgs",   DEFAULTS["warmup_msgs"]),
        "idle_reset_secs": _i("wa_idle_reset_secs", DEFAULTS["idle_reset_secs"]),
        "fail_trip":     _i("wa_fail_trip",     DEFAULTS["fail_trip"]),
    }


def _prune(st: dict, now: float) -> None:
    while st["sends"] and now - st["sends"][0] > 3600:
        st["sends"].popleft()


def check(sessao_id: str, caps: dict):
    """Pode enviar AGORA? Retorna (allowed, reason, retry_after_secs).
    Se estourar o teto, ARMA o cooldown e nega."""
    now = time.time()
    st = _state[sessao_id]
    if now < st["cooldown_until"]:
        return False, "cooldown", st["cooldown_until"] - now
    _prune(st, now)
    last_min = sum(1 for t in st["sends"] if now - t <= 60)
    last_hour = len(st["sends"])
    if last_min >= caps["max_per_min"] or last_hour >= caps["max_per_hour"]:
        st["cooldown_until"] = now + caps["cooldown_secs"]
        reason = f"teto atingido ({last_min}/min, {last_hour}/h) → pausa {caps['cooldown_secs']}s"
        return False, reason, caps["cooldown_secs"]
    return True, "", 0.0


def delay_for(sessao_id: str, base_min: float, base_max: float, caps: dict) -> float:
    """Delay antes do próximo envio. Em aquecimento, bem maior; depois, ritmo normal."""
    now = time.time()
    st = _state[sessao_id]
    # Frio = nunca enviou (1ª vez) OU ocioso há muito tempo (reconexão / pós-cooldown)
    # → reinicia aquecimento. Número recém-conectado é o mais sensível ao anti-spam.
    if st["last_send"] == 0.0 or now - st["last_send"] > caps["idle_reset_secs"]:
        st["warmup_left"] = caps["warmup_msgs"]
        ocioso = (now - st["last_send"]) if st["last_send"] else -1
        logger.info("[guard] sessão %s fria (ocioso %.0fs) → aquecimento %s msgs",
                    sessao_id, ocioso, caps["warmup_msgs"])
    left = st["warmup_left"]
    if left > 0:
        # Quanto mais perto do início do aquecimento, mais devagar.
        done = caps["warmup_msgs"] - left
        if done < 5:
            return random.uniform(10.0, 15.0)
        if done < 10:
            return random.uniform(7.0, 10.0)
        return random.uniform(5.0, 7.0)
    return random.uniform(base_min, base_max)


def record_send(sessao_id: str, ok: bool, caps: dict) -> None:
    """Registra o resultado de um envio (alimenta janela de taxa + aquecimento + falhas)."""
    now = time.time()
    st = _state[sessao_id]
    st["last_send"] = now
    st["warned"] = False
    if ok:
        st["sends"].append(now)
        if st["warmup_left"] > 0:
            st["warmup_left"] -= 1
        st["fail_streak"] = 0
    else:
        st["fail_streak"] += 1
        if st["fail_streak"] >= caps["fail_trip"] and now >= st["cooldown_until"]:
            st["cooldown_until"] = now + caps["cooldown_secs"]
            logger.warning("[guard] sessão %s: %s falhas seguidas → pausa %ss (protege número)",
                           sessao_id, st["fail_streak"], caps["cooldown_secs"])


def note_blocked(sessao_id: str, reason: str, retry_after: float, empresa_id: int) -> None:
    """Loga (1x por trip) que a sessão foi pausada + alerta Telegram throttled."""
    st = _state[sessao_id]
    if st["warned"]:
        return
    st["warned"] = True
    logger.info("[guard] empresa=%s sessão %s PAUSADA: %s (retoma em ~%.0fs)",
                empresa_id, sessao_id, reason, retry_after)
    try:
        import asyncio
        from . import telegram_service
        asyncio.create_task(telegram_service.notify_dispatch_paused(empresa_id, reason, int(retry_after)))
    except Exception:
        pass


def status(sessao_id: str) -> dict:
    """Snapshot pro portal/diagnóstico."""
    now = time.time()
    st = _state[sessao_id]
    _prune(st, now)
    return {
        "per_min": sum(1 for t in st["sends"] if now - t <= 60),
        "per_hour": len(st["sends"]),
        "warmup_left": st["warmup_left"],
        "cooldown_secs_left": max(0, round(st["cooldown_until"] - now)),
        "fail_streak": st["fail_streak"],
    }
