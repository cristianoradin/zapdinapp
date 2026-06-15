"""
app/services/contabil_service.py — Regra de negócio do módulo contábil.

Concentra a lógica de boas-vindas via WhatsApp:
  - _enviar_boas_vindas: tenta enviar na hora; sem sessão WA, enfileira
  - _entregar_boas_vindas: envio real via wa_manager + atualização de estado
  - processar_boasvindas_pendentes: chamado pelo queue_worker para reentrega

Todo o SQL fica em app/repositories/contabil_repository.py.
"""
from __future__ import annotations

import logging

from ..repositories import ContabilRepository

logger = logging.getLogger(__name__)

_MSG_BOAS_VINDAS = (
    "👋 *Olá, {nome}!*\n\n"
    "Seu cadastro no nosso escritório de contabilidade foi realizado com sucesso! ✅\n\n"
    "*Como enviar seus documentos:*\n"
    "📄 Envie suas *Notas Fiscais* (imagens ou PDF) diretamente aqui neste chat.\n"
    "📊 Aceitamos NF-e, NF-Ce e CT-e.\n\n"
    "Nossa equipe irá processar seus documentos e mantê-lo informado. 🚀\n\n"
    "_Dúvidas? Responda esta mensagem._"
)


async def _enviar_boas_vindas(empresa_id: int, telefone: str, nome: str, db) -> None:
    """Envia mensagem de boas-vindas via WhatsApp. Se não houver sessão ativa,
    grava em contabil_wa_pendentes para o worker reenviar depois."""
    try:
        from ..main import wa_manager
        repo = ContabilRepository(db)
        sessoes = list(wa_manager._sessions.values())
        # Prefere sessão conectada; qualquer sessão como fallback
        sessao = next((s for s in sessoes if getattr(s, "status", "") == "connected"), None) \
                 or (sessoes[0] if sessoes else None)
        if not sessao:
            # Sem sessão WA: enfileirar para reenvio futuro (tenant herdado da empresa)
            _tid = await repo.get_tenant_da_empresa(empresa_id)
            await repo.enfileirar_boas_vindas(_tid, empresa_id, telefone, nome)
            logger.info(
                "[contabil] Sem sessão WA — boas-vindas para %s enfileiradas (%s)",
                nome, telefone,
            )
            return

        await _entregar_boas_vindas(empresa_id, telefone, nome, db, wa_manager, sessao)

    except Exception as e:
        logger.error("[contabil] Erro ao enviar boas-vindas: %s", e)


async def _entregar_boas_vindas(empresa_id: int, telefone: str, nome: str, db, wa_manager, sessao) -> None:
    """Faz o envio real via wa_manager (compatível com Playwright e Evolution)."""
    phone_wa = "55" + telefone if not telefone.startswith("55") else telefone
    msg = _MSG_BOAS_VINDAS.format(nome=nome)
    # Usa wa_manager.send_text que funciona para ambos os backends
    ok, err = await wa_manager.send_text(sessao.session_id, sessao.empresa_id, phone_wa, msg)
    if not ok:
        raise RuntimeError(f"Falha ao enviar WA: {err}")

    repo = ContabilRepository(db)
    await repo.marcar_boas_vindas_enviadas(empresa_id)
    # Resolve tenant_id pela empresa
    _tid = await repo.get_tenant_da_empresa(empresa_id)
    await repo.add_evento(
        _tid, "boas_vindas", f"Mensagem de boas-vindas enviada para {nome}",
        empresa_id=empresa_id,
    )
    logger.info("[contabil] Boas-vindas enviadas para %s (%s)", nome, telefone)


async def processar_boasvindas_pendentes(wa_manager, get_db_direct) -> int:
    """Chamado pelo queue_worker. Processa até 5 pendentes por rodada.
    Retorna quantos foram enviados com sucesso."""
    sessoes = list(wa_manager._sessions.values())
    if not sessoes:
        return 0  # ainda sem sessão, não faz nada

    # Prefere sessão conectada
    sessao = next((s for s in sessoes if getattr(s, "status", "") == "connected"), sessoes[0])
    enviados = 0

    async with get_db_direct() as db:
        repo = ContabilRepository(db)
        pendentes = await repo.listar_pendentes(limit=5)

        for row in pendentes:
            pid, empresa_id, telefone, nome, tentativas = (
                row["id"], row["empresa_id"], row["telefone"],
                row["nome"], row["tentativas"],
            )
            try:
                await _entregar_boas_vindas(empresa_id, telefone, nome, db, wa_manager, sessao)
                await repo.marcar_enviado(pid)
                enviados += 1
            except Exception as exc:
                novas_tentativas = tentativas + 1
                novo_status = "falha" if novas_tentativas >= 3 else "pendente"
                await repo.registrar_falha_tentativa(pid, novas_tentativas, novo_status)
                logger.warning(
                    "[contabil] Falha ao entregar boas-vindas pendente id=%s (tentativa %s): %s",
                    pid, novas_tentativas, exc,
                )

    return enviados
