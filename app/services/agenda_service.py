"""
app/services/agenda_service.py — Agenda via WhatsApp.

Funcionalidades:
  1. processar_comando_agenda() — intercepta mensagens do número-dono e responde
     com consultas (hoje/semana) ou cria agendamento via NL + IA.
  2. _enviar_alertas_agenda() — chamado pelo reporter; envia alerta 1h antes.

Este módulo é completamente isolado. Se qualquer erro ocorrer, o chatbot normal
continua sem ser afetado (try/except no ponto de integração).
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Normalização de número ────────────────────────────────────────────────────

def _normalizar_phone(phone: str) -> str:
    """Remove prefixos internacionais e espaços. Retorna só dígitos locais."""
    p = phone.split("@")[0].strip().replace(" ", "").replace("-", "")
    if p.startswith("+"):
        p = p[1:]
    if p.startswith("55") and len(p) >= 12:
        p = p[2:]
    return p


# ── Helpers de formatação ─────────────────────────────────────────────────────

def _fmt_compromisso(c: dict) -> str:
    hora = c.get("hora_inicio") or ""
    fim  = c.get("hora_fim") or ""
    if hora and fim:
        hora_txt = f"{hora} → {fim}"
    elif hora:
        hora_txt = hora
    else:
        hora_txt = "Horário não definido"

    link = (c.get("link") or "").strip()
    desc = (c.get("descricao") or "").strip()

    linha = f"• *{c['titulo']}* — {hora_txt}"
    if desc:
        linha += f"\n  📝 {desc}"
    if link:
        linha += f"\n  🔗 {link}"
    return linha


# ── Consulta de agenda ────────────────────────────────────────────────────────

async def _consultar_agenda(empresa_id: int, periodo: str, db) -> list[dict]:
    """Retorna compromissos para 'hoje' ou 'semana'."""
    hoje = date.today()
    if periodo == "hoje":
        inicio = hoje
        fim    = hoje
    else:  # semana
        inicio = hoje
        fim    = hoje + timedelta(days=6)

    async with db.execute(
        "SELECT titulo, data, hora_inicio, hora_fim, descricao, link "
        "FROM agenda_compromissos "
        "WHERE empresa_id=$1 AND data BETWEEN $2 AND $3 "
        "ORDER BY data, hora_inicio",
        (empresa_id, inicio, fim),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Responder via WA ──────────────────────────────────────────────────────────

async def _wa_send(instance: str, phone: str, texto: str) -> None:
    """Envia mensagem WA via Evolution API."""
    try:
        from .evolution_service import evo_manager
        await evo_manager.send_text(instance, phone, texto)
    except Exception as exc:
        logger.warning("[agenda] Falha ao enviar WA: %s", exc)


# ── Parsing de agendamento via IA ─────────────────────────────────────────────

_PARSE_SYSTEM = """Você é um extrator de dados de agenda. O usuário enviará uma mensagem em português
pedindo para agendar um compromisso. Extraia as informações e responda SOMENTE com um JSON válido,
sem markdown, sem explicações. Formato:
{
  "titulo": "string",
  "data": "YYYY-MM-DD",
  "hora_inicio": "HH:MM ou null",
  "hora_fim": "HH:MM ou null",
  "descricao": "string ou null",
  "link": "URL ou null"
}
Regras:
- data: se o usuário disser "amanhã", calcule a partir de hoje ({hoje}).
- Se não houver link, retorne null.
- Se não houver hora, retorne null.
- Sempre responda APENAS com o JSON, sem mais texto."""


async def _parse_agendamento_ia(texto: str) -> Optional[dict]:
    """Usa IA para extrair dados de agendamento de linguagem natural."""
    from .chatbot_service import _chat_providers, _call_ia

    providers = _chat_providers()
    if not providers:
        return None

    hoje_str = date.today().isoformat()
    system = _PARSE_SYSTEM.replace("{hoje}", hoje_str)

    for provider in providers:
        try:
            resposta = await _call_ia(
                provider=provider,
                system=system,
                historico=[{"role": "user", "content": texto}],
                max_tokens=300,
            )
            if resposta:
                # Extrai JSON mesmo que venha com texto extra
                match = re.search(r'\{.*\}', resposta, re.DOTALL)
                if match:
                    data = _json.loads(match.group())
                    return data
        except Exception as exc:
            logger.debug("[agenda] Falha IA parse %s: %s", provider, exc)
            continue
    return None


# ── Criar compromisso via IA ──────────────────────────────────────────────────

async def _criar_via_ia(empresa_id: int, usuario_id: int, texto: str, db) -> Optional[dict]:
    """Parseia texto com IA e insere compromisso no banco."""
    dados = await _parse_agendamento_ia(texto)
    if not dados or not dados.get("titulo") or not dados.get("data"):
        return None

    # Valida data
    try:
        data_obj = date.fromisoformat(dados["data"])
    except Exception:
        return None

    await db.execute(
        "INSERT INTO agenda_compromissos"
        "(empresa_id, usuario_id, data, hora_inicio, hora_fim, titulo, descricao, link, cor) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)",
        (
            empresa_id,
            usuario_id,
            data_obj,
            dados.get("hora_inicio"),
            dados.get("hora_fim"),
            dados["titulo"],
            dados.get("descricao") or "",
            dados.get("link") or "",
            "#3d7f1f",
        ),
    )
    await db.commit()
    return dados


# ── Ponto de entrada principal (chamado pelo chatbot_service) ─────────────────

async def processar_comando_agenda(
    empresa_id: int,
    phone_local: str,
    texto: str,
    instance: str,
    usuario_id: int,
) -> bool:
    """
    Verifica se a mensagem é do número-dono configurado e tenta processar
    como comando de agenda.

    Retorna True se o comando foi tratado (chatbot normal NÃO deve processar).
    Retorna False em qualquer outro caso (chatbot continua normalmente).
    """
    from ..core.database import get_db_direct

    try:
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT value FROM config WHERE empresa_id=$1 AND key='agenda_alerta'",
                (empresa_id,),
            ) as cur:
                row = await cur.fetchone()

        if not row:
            return False

        try:
            cfg = _json.loads(row["value"] or "{}")
        except Exception:
            return False

        if not cfg.get("ativo"):
            return False

        numero_dono = _normalizar_phone(cfg.get("numero_dono") or "")
        if not numero_dono:
            return False

        phone_norm = _normalizar_phone(phone_local)
        if phone_norm != numero_dono:
            return False  # não é o dono — chatbot normal continua

        # ── É o dono — processa comando ───────────────────────────────────────
        t = texto.lower().strip()

        # Ajuda / menu
        if re.search(r'\bagenda\b|\bajuda\b|\bhelp\b|\bo que\b|\bmenu\b', t) and len(t) < 30:
            resp = (
                "📅 *Agenda ZapDin*\n\n"
                "Comandos disponíveis:\n"
                "• *agenda hoje* — compromissos de hoje\n"
                "• *agenda semana* — próximos 7 dias\n"
                "• *agendar [descrição]* — criar compromisso\n\n"
                "_Exemplo: agendar reunião com sócios dia 25/05 às 14h — link: meet.google.com/xxx_"
            )
            await _wa_send(instance, phone_local, resp)
            return True

        # Consulta hoje
        if re.search(r'\bhoje\b|\btoday\b', t):
            async with get_db_direct() as db:
                compromissos = await _consultar_agenda(empresa_id, "hoje", db)
            hoje = date.today()
            if not compromissos:
                resp = f"📅 Nenhum compromisso para hoje ({hoje.strftime('%d/%m/%Y')})."
            else:
                linhas = [f"📅 *Compromissos de hoje ({hoje.strftime('%d/%m/%Y')}):*\n"]
                linhas += [_fmt_compromisso(c) for c in compromissos]
                resp = "\n".join(linhas)
            await _wa_send(instance, phone_local, resp)
            return True

        # Consulta semana
        if re.search(r'\bsemana\b|\bweek\b|\bpr[oó]ximos\b', t):
            async with get_db_direct() as db:
                compromissos = await _consultar_agenda(empresa_id, "semana", db)
            if not compromissos:
                resp = "📅 Nenhum compromisso nos próximos 7 dias."
            else:
                # Agrupa por data
                por_data: dict[str, list] = {}
                for c in compromissos:
                    k = str(c["data"])
                    por_data.setdefault(k, []).append(c)
                linhas = ["📅 *Compromissos da semana:*\n"]
                for data_str, lista in sorted(por_data.items()):
                    d = date.fromisoformat(data_str)
                    linhas.append(f"*{d.strftime('%d/%m — %A').replace('Monday','Segunda').replace('Tuesday','Terça').replace('Wednesday','Quarta').replace('Thursday','Quinta').replace('Friday','Sexta').replace('Saturday','Sábado').replace('Sunday','Domingo')}*")
                    linhas += [_fmt_compromisso(c) for c in lista]
                    linhas.append("")
                resp = "\n".join(linhas).strip()
            await _wa_send(instance, phone_local, resp)
            return True

        # Criar agendamento
        if re.search(r'\bagendar\b|\bmarcar\b|\badicion[ae]r compromisso\b|\bcriar compromisso\b|\bnovo compromisso\b', t):
            async with get_db_direct() as db:
                dados = await _criar_via_ia(empresa_id, usuario_id, texto, db)
            if dados:
                hora_txt = dados.get("hora_inicio") or "Sem horário"
                link_txt = f"\n🔗 {dados['link']}" if dados.get("link") else ""
                resp = (
                    f"✅ *Compromisso agendado!*\n\n"
                    f"📌 *{dados['titulo']}*\n"
                    f"📅 {date.fromisoformat(dados['data']).strftime('%d/%m/%Y')}\n"
                    f"🕐 {hora_txt}"
                    f"{link_txt}\n\n"
                    f"⏰ Você receberá um alerta 1 hora antes."
                )
            else:
                resp = (
                    "❌ Não consegui entender o agendamento. Tente:\n"
                    "_agendar reunião com sócios dia 25/05 às 14h_"
                )
            await _wa_send(instance, phone_local, resp)
            return True

    except Exception as exc:
        logger.warning("[agenda] Erro ao processar comando (chatbot continua): %s", exc)

    return False  # não reconhecido — chatbot normal continua


# ── Worker de alertas (chamado pelo reporter) ─────────────────────────────────

async def enviar_alertas_agenda() -> None:
    """
    Envia alertas WA 1 hora antes de cada compromisso com hora definida.
    Roda a cada ~1 minuto via reporter._loop().
    Marca alerta_enviado_em para não reenviar.
    """
    try:
        from ..core.database import get_db_direct
        from .evolution_service import evo_manager
    except ImportError:
        return

    try:
        import json as _j

        async with get_db_direct() as db:
            # Compromissos cuja janela de alerta (1h antes) está nos próximos 2 min
            async with db.execute(
                """
                SELECT ac.id, ac.empresa_id, ac.titulo, ac.hora_inicio,
                       ac.hora_fim, ac.descricao, ac.link, ac.data,
                       c.value AS cfg_json
                FROM agenda_compromissos ac
                LEFT JOIN config c
                       ON c.empresa_id = ac.empresa_id
                      AND c.key = 'agenda_alerta'
                WHERE ac.alerta_enviado_em IS NULL
                  AND ac.hora_inicio IS NOT NULL
                  AND ac.hora_inicio <> ''
                  AND (ac.data::text || ' ' || ac.hora_inicio)::timestamp - INTERVAL '1 hour'
                      BETWEEN (NOW() AT TIME ZONE 'America/Sao_Paulo') - INTERVAL '2 minutes'
                          AND (NOW() AT TIME ZONE 'America/Sao_Paulo')
                ORDER BY ac.data, ac.hora_inicio
                LIMIT 20
                """
            ) as cur:
                pendentes = await cur.fetchall()

        if not pendentes:
            return

        for row in pendentes:
            empresa_id = row["empresa_id"]
            try:
                cfg = _j.loads(row["cfg_json"] or "{}")
            except Exception:
                cfg = {}

            if not cfg.get("ativo"):
                # Alerta desativado — marca para não verificar de novo
                async with get_db_direct() as db:
                    await db.execute(
                        "UPDATE agenda_compromissos SET alerta_enviado_em = NOW() WHERE id = $1",
                        (row["id"],),
                    )
                    await db.commit()
                continue

            numero_alerta = _normalizar_phone(cfg.get("numero_alerta") or "")
            if not numero_alerta:
                continue

            # Verifica sessão WA disponível
            sessoes = evo_manager.get_status(empresa_id)
            conectadas = [s for s in sessoes if s["status"] == "connected"]
            if not conectadas:
                logger.debug("[agenda-alerta] empresa %s sem sessão WA conectada — pulando", empresa_id)
                continue

            instance = conectadas[0]["instance"]
            template = cfg.get("mensagem", "")

            hora  = row["hora_inicio"] or ""
            desc  = (row["descricao"] or "").strip() or "—"
            link  = (row["link"] or "").strip() or "—"
            msg   = template.format(
                titulo=row["titulo"],
                hora=hora,
                descricao=desc,
                link=link,
            )

            try:
                await evo_manager.send_text(instance, numero_alerta, msg)
                logger.info("[agenda-alerta] Alerta enviado — empresa=%s compromisso=%s",
                            empresa_id, row["id"])
            except Exception as exc:
                logger.warning("[agenda-alerta] Falha ao enviar alerta %s: %s", row["id"], exc)
                continue

            # Marca como enviado
            async with get_db_direct() as db:
                await db.execute(
                    "UPDATE agenda_compromissos SET alerta_enviado_em = NOW() WHERE id = $1",
                    (row["id"],),
                )
                await db.commit()

    except Exception as exc:
        logger.warning("[agenda-alerta] Erro no worker: %s", exc)
