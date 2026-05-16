/**
 * modules/dashboard.js — Módulo da tela "Gestão de Envios" (dashboard principal).
 *
 * Responsável por:
 *  - KPIs: hoje, enviadas, falhas, sessões ativas
 *  - Banner de fila presa (queue-health)
 *  - Tabela de mensagens recentes (últimas 20)
 *
 * Depende de: modules/utils.js (escHtml, api, ZD.registry)
 * Registra: ZD.registry.register('dashboard', loadDashboard)
 */

(function () {
  'use strict';

  // ── Helpers privados ────────────────────────────────────────────────────────

  function _setKpi(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value ?? '—';
  }

  function _statusChip(status) {
    const map = {
      sent:    { cls: 'chip-green',  label: 'Enviada' },
      failed:  { cls: 'chip-red',    label: 'Falhou' },
      error:   { cls: 'chip-red',    label: 'Erro' },
      queued:  { cls: 'chip-yellow', label: 'Na fila' },
      pending: { cls: 'chip-yellow', label: 'Pendente' },
    };
    const { cls, label } = map[status] || { cls: 'chip-yellow', label: status };
    return `<span class="chip ${cls}">${label}</span>`;
  }

  function _renderVazio() {
    return `
      <tr>
        <td colspan="4" style="text-align:center;padding:3rem 1rem">
          <div style="width:48px;height:48px;background:var(--accent-soft);border-radius:12px;
                      display:flex;align-items:center;justify-content:center;margin:0 auto .75rem">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"
                 fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
          </div>
          <div style="color:var(--text);font-size:.9rem;font-weight:600;margin-bottom:.3rem">
            Nenhuma mensagem enviada ainda
          </div>
          <div style="color:var(--text-mid);font-size:.8rem;margin-bottom:1rem">
            Configure e envie sua primeira mensagem para começar.
          </div>
          <button class="btn btn-primary btn-sm"
                  onclick="showPage('mensagem')"
                  style="display:inline-flex;align-items:center;gap:.4rem">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
                 fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            Configurar mensagem
          </button>
        </td>
      </tr>`;
  }

  function _renderRow(r) {
    return `
      <tr>
        <td style="font-family:monospace;font-size:.84rem">${escHtml(r.destinatario || '—')}</td>
        <td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
          ${escHtml(r.mensagem || '—')}
        </td>
        <td>${_statusChip(r.status)}</td>
        <td style="color:var(--text-mid);font-size:.8rem;white-space:nowrap">${r.created_at || '—'}</td>
      </tr>`;
  }

  async function _checkQueueHealth() {
    try {
      const r = await fetch('/api/stats/queue-health');
      if (!r.ok) return;
      const qd = await r.json();
      const banner = document.getElementById('queueStuckBanner');
      if (!banner) return;

      if (qd.stuck_alert && qd.total_queued > 0) {
        const msg = document.getElementById('queueStuckMsg');
        if (msg) msg.textContent =
          `Há ${qd.total_queued} mensagem(ns) aguardando há ${qd.stuck_minutes} minutos. ` +
          `Verifique o WhatsApp${!qd.wa_connected ? ' (desconectado)' : ''} e o worker.`;
        banner.style.display = 'flex';
      } else {
        banner.style.display = 'none';
      }
    } catch (_) { /* best-effort */ }
  }

  // ── API pública ─────────────────────────────────────────────────────────────

  window.loadDashboard = async function () {
    // Estado de carregamento nos KPIs
    ['statHoje', 'statEnviadas', 'statFalhas', 'statSessoes'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = '…';
    });

    try {
      const res = await fetch('/api/stats');
      if (res.status === 401) { window.location.href = '/login'; return; }
      if (!res.ok) throw new Error('stats error');
      const d = await res.json();

      _setKpi('statHoje',     d.hoje);
      _setKpi('statEnviadas', d.enviadas);
      _setKpi('statFalhas',   d.falhas);
      _setKpi('statSessoes',  d.sessoes_ativas);

      await _checkQueueHealth();

      const tbody = document.getElementById('tbodyRecentes');
      if (!tbody) return;
      if (!d.recentes || d.recentes.length === 0) {
        tbody.innerHTML = _renderVazio();
      } else {
        tbody.innerHTML = d.recentes.map(_renderRow).join('');
      }
    } catch (_) {
      ['statHoje', 'statEnviadas', 'statFalhas', 'statSessoes'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = '—';
      });
      if (typeof showToast === 'function') showToast('Erro ao carregar dashboard', 'error');
    }
  };

  // ── Registro no page router ─────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    if (window.ZD && ZD.registry) {
      ZD.registry.register('dashboard', loadDashboard);
    }
  });
})();
