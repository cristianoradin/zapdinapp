"""
app/services/agenda_service.py — Agenda via WhatsApp (multi-usuário).

Cada usuário cadastrado em `agenda_wa_usuarios` tem seus compromissos isolados.
Identificação: agenda_compromissos.usuario_id = -(agenda_wa_usuarios.id)
  → negativos = criados via WA  → positivos = criados via UI

Funcionalidades:
  1. processar_comando_agenda() — identifica o sender na tabela de usuários WA;
     saúda pelo nome; processa consultas (hoje/semana) e criação via NL + IA.
  2. enviar_alertas_agenda()   — envia alertas 1h antes; por usuário WA ou para
     o numero_alerta legado (compromissos da UI).
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


def _traduz_dia(dia_en: str) -> str:
    return (dia_en
        .replace("Monday",    "Segunda")
        .replace("Tuesday",   "Terça")
        .replace("Wednesday", "Quarta")
        .replace("Thursday",  "Quinta")
        .replace("Friday",    "Sexta")
        .replace("Saturday",  "Sábado")
        .replace("Sunday",    "Domingo"))


# ── Buscar usuário WA ─────────────────────────────────────────────────────────

async def _buscar_wa_usuario(empresa_id: int, phone_norm: str, db) -> Optional[dict]:
    """Retorna dict {id, nome} do usuário WA ativo, ou None."""
    async with db.execute(
        "SELECT id, nome FROM agenda_wa_usuarios "
        "WHERE empresa_id=$1 AND phone=$2 AND ativo=true",
        (empresa_id, phone_norm),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


# ── Consulta de agenda ────────────────────────────────────────────────────────

async def _consultar_agenda(
    empresa_id: int, periodo: str, db, usuario_id: int
) -> list[dict]:
    """Retorna compromissos do usuário para 'hoje' ou 'semana'."""
    hoje = date.today()
    inicio = hoje
    fim    = hoje if periodo == "hoje" else hoje + timedelta(days=6)

    async with db.execute(
        "SELECT titulo, data, hora_inicio, hora_fim, descricao, link "
        "FROM agenda_compromissos "
        "WHERE empresa_id=$1 AND usuario_id=$2 AND data BETWEEN $3 AND $4 "
        "ORDER BY data, hora_inicio",
        (empresa_id, usuario_id, inicio, fim),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Enviar via WA ─────────────────────────────────────────────────────────────

async def _wa_send(instance: str, phone: str, texto: str) -> None:
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
                match = re.search(r'\{.*\}', resposta, re.DOTALL)
                if match:
                    return _json.loads(match.group())
        except Exception as exc:
            logger.debug("[agenda] Falha IA parse %s: %s", provider, exc)
            continue
    return None


# ── Criar compromisso via IA ──────────────────────────────────────────────────

async def _criar_via_ia(
    empresa_id: int, usuario_id: int, texto: str, db
) -> Optional[dict]:
    dados = await _parse_agendamento_ia(texto)
    if not dados or not dados.get("titulo") or not dados.get("data"):
        return None

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


# ── Ponto de entrada principal ────────────────────────────────────────────────

async def processar_comando_agenda(
    empresa_id: int,
    phone_local: str,
    texto: str,
    instance: str,
    usuario_id: int,
) -> bool:
    """
    Identifica o sender na tabela agenda_wa_usuarios.
    Retorna True se o comando foi tratado (chatbot NÃO deve processar).
    Retorna False em qualquer outro caso.
    """
    from ..core.database import get_db_direct

    try:
        # Verifica se o recurso está ativo para a empresa
        async with get_db_direct() as db:
            async with db.execute(
                "SELECT value FROM config WHERE empresa_id=$1 AND key='agenda_alerta'",
                (empresa_id,),
            ) as cur:
                cfg_row = await cur.fetchone()

        cfg: dict = {}
        if cfg_row:
            try:
                cfg = _json.loads(cfg_row["value"] or "{}")
            except Exception:
                pass

        if not cfg.get("ativo"):
            return False

        phone_norm = _normalizar_phone(phone_local)

        # ── Busca usuário na tabela multi-usuário ─────────────────────────────
        async with get_db_direct() as db:
            wa_user = await _buscar_wa_usuario(empresa_id, phone_norm, db)

        # ── Fallback: número-dono legado (instalações antigas sem tabela) ─────
        if not wa_user:
            numero_dono = _normalizar_phone(cfg.get("numero_dono") or "")
            if not numero_dono or phone_norm != numero_dono:
                return False
            nome_usuario  = "você"
            effective_uid = 0  # legado: usuario_id genérico
        else:
            nome_usuario  = (wa_user["nome"] or "você").split()[0]  # primeiro nome
            effective_uid = -(wa_user["id"])  # negativo = identificador WA

        # ── Processa o comando ────────────────────────────────────────────────
        t = texto.lower().strip()

        # Menu / ajuda
        if re.search(r'\bagenda\b|\bajuda\b|\bhelp\b|\bo que\b|\bmenu\b', t) and len(t) < 30:
            resp = (
                f"📅 *Olá, {nome_usuario}! Agenda ZapDin*\n\n"
                "Comandos disponíveis:\n"
                "• *agenda hoje* — seus compromissos de hoje\n"
                "• *agenda semana* — próximos 7 dias\n"
                "• *agendar [descrição]* — criar compromisso\n\n"
                "_Exemplo: agendar reunião com sócios dia 25/05 às 14h_"
            )
            await _wa_send(instance, phone_local, resp)
            return True

        # Consulta hoje
        if re.search(r'\bhoje\b|\btoday\b', t):
            async with get_db_direct() as db:
                compromissos = await _consultar_agenda(empresa_id, "hoje", db, effective_uid)
            hoje = date.today()
            if not compromissos:
                resp = f"📅 Nenhum compromisso para hoje, {nome_usuario} ({hoje.strftime('%d/%m/%Y')})."
            else:
                linhas = [f"📅 *{nome_usuario}, compromissos de hoje ({hoje.strftime('%d/%m/%Y')}):*\n"]
                linhas += [_fmt_compromisso(c) for c in compromissos]
                resp = "\n".join(linhas)
            await _wa_send(instance, phone_local, resp)
            return True

        # Consulta semana
        if re.search(r'\bsemana\b|\bweek\b|\bpr[oó]ximos\b', t):
            async with get_db_direct() as db:
                compromissos = await _consultar_agenda(empresa_id, "semana", db, effective_uid)
            if not compromissos:
                resp = f"📅 Nenhum compromisso nos próximos 7 dias, {nome_usuario}."
            else:
                por_data: dict[str, list] = {}
                for c in compromissos:
                    por_data.setdefault(str(c["data"]), []).append(c)
                linhas = [f"📅 *{nome_usuario}, seus compromissos da semana:*\n"]
                for data_str, lista in sorted(por_data.items()):
                    d = date.fromisoformat(data_str)
                    linhas.append(f"*{_traduz_dia(d.strftime('%A'))}, {d.strftime('%d/%m')}*")
                    linhas += [_fmt_compromisso(c) for c in lista]
                    linhas.append("")
                resp = "\n".join(linhas).strip()
            await _wa_send(instance, phone_local, resp)
            return True

        # Criar agendamento
        if re.search(
            r'\bagendar\b|\bmarcar\b|\badicion[ae]r compromisso\b'
            r'|\bcriar compromisso\b|\bnovo compromisso\b', t
        ):
            async with get_db_direct() as db:
                dados = await _criar_via_ia(empresa_id, effective_uid, texto, db)
            if dados:
                hora_txt = dados.get("hora_inicio") or "Sem horário"
                link_txt = f"\n🔗 {dados['link']}" if dados.get("link") else ""
                resp = (
                    f"✅ *Compromisso agendado, {nome_usuario}!*\n\n"
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

    return False


# ── Worker de alertas ─────────────────────────────────────────────────────────

async def enviar_alertas_agenda() -> None:
    """
    Envia alertas 1h antes de cada compromisso.
    • usuario_id < 0  → compromisso criado via WA → busca phone em agenda_wa_usuarios
    • usuario_id >= 0 → compromisso criado via UI → envia para numero_alerta do config
    """
    try:
        from ..core.database import get_db_direct
        from .evolution_service import evo_manager
    except ImportError:
        return

    try:
        import json as _j

        async with get_db_direct() as db:
            async with db.execute(
                """
                SELECT ac.id, ac.empresa_id, ac.titulo, ac.hora_inicio,
                       ac.hora_fim, ac.descricao, ac.link, ac.data,
                       ac.usuario_id,
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
            usuario_id = row["usuario_id"]

            try:
                cfg = _j.loads(row["cfg_json"] or "{}")
            except Exception:
                cfg = {}

            if not cfg.get("ativo"):
                async with get_db_direct() as db:
                    await db.execute(
                        "UPDATE agenda_compromissos SET alerta_enviado_em = NOW() WHERE id = $1",
                        (row["id"],),
                    )
                    await db.commit()
                continue

            # Determina o número destino
            numero_destino = None
            nome_usuario   = ""
            template       = cfg.get("mensagem", "")

            if usuario_id is not None and usuario_id < 0:
                # Compromisso criado via WA — busca usuário pelo ID negativo
                wa_user_id = -usuario_id
                async with get_db_direct() as db:
                    async with db.execute(
                        "SELECT phone, nome, recebe_alertas "
                        "FROM agenda_wa_usuarios "
                        "WHERE id=$1 AND empresa_id=$2",
                        (wa_user_id, empresa_id),
                    ) as cur:
                        wa_row = await cur.fetchone()
                if wa_row and wa_row["recebe_alertas"]:
                    numero_destino = _normalizar_phone(wa_row["phone"])
                    nome_usuario   = (wa_row["nome"] or "").split()[0]
            else:
                # Compromisso da UI — envia para numero_alerta do config
                numero_destino = _normalizar_phone(cfg.get("numero_alerta") or "")

            if not numero_destino:
                async with get_db_direct() as db:
                    await db.execute(
                        "UPDATE agenda_compromissos SET alerta_enviado_em = NOW() WHERE id = $1",
                        (row["id"],),
                    )
                    await db.commit()
                continue

            # Verifica sessão WA conectada
            sessoes    = evo_manager.get_status(empresa_id)
            conectadas = [s for s in sessoes if s["status"] == "connected"]
            if not conectadas:
                logger.debug("[agenda-alerta] empresa %s sem sessão WA — pulando", empresa_id)
                continue

            instance = conectadas[0]["instance"]
            hora     = row["hora_inicio"] or ""
            desc     = (row["descricao"] or "").strip() or "—"
            link     = (row["link"] or "").strip() or "—"

            try:
                msg = template.format(
                    titulo=row["titulo"],
                    hora=hora,
                    descricao=desc,
                    link=link,
                    nome=nome_usuario,
                )
            except Exception:
                msg = (
                    f"📅 *Lembrete:* {row['titulo']}\n"
                    f"🕐 {hora}\n"
                    f"⏰ Começa em 1 hora!"
                )

            try:
                await evo_manager.send_text(instance, numero_destino, msg)
                logger.info("[agenda-alerta] Alerta — empresa=%s compromisso=%s → %s",
                            empresa_id, row["id"], numero_destino)
            except Exception as exc:
                logger.warning("[agenda-alerta] Falha %s: %s", row["id"], exc)
                continue

            async with get_db_direct() as db:
                await db.execute(
                    "UPDATE agenda_compromissos SET alerta_enviado_em = NOW() WHERE id = $1",
                    (row["id"],),
                )
                await db.commit()

    except Exception as exc:
        logger.warning("[agenda-alerta] Erro no worker: %s", exc)
