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
      sent:      { cls: 'badge ok dot',    label: 'Enviada' },
      delivered: { cls: 'badge info dot',  label: 'Entregue' },
      read:      { cls: 'badge ok dot',    label: 'Visualizada' },
      failed:    { cls: 'badge fail dot',  label: 'Falhou' },
      error:     { cls: 'badge fail dot',  label: 'Erro' },
      queued:    { cls: 'badge queue dot', label: 'Na fila' },
      pending:   { cls: 'badge queue dot', label: 'Pendente' },
    };
    const { cls, label } = map[status] || { cls: 'badge queue dot', label: status };
    return `<span class="${cls}">${label}</span>`;
  }


  function _renderVazio() {
    return `
      <tr>
        <td colspan="4">
          <div class="empty-box">
            <div class="empty-ic">
              <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            </div>
            <div style="font-weight:700;color:var(--primary-deep)">Nenhuma mensagem enviada ainda</div>
            <div style="font-size:13px;color:var(--text-2)">Configure e envie sua primeira mensagem para começar.</div>
            <button class="btn sm" style="margin-top:8px" onclick="showPage('mensagem')">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              Configurar mensagem
            </button>
          </div>
        </td>
      </tr>`;
  }

  function _fmtTs(ts) {
    if (!ts) return '—';
    const d = new Date(typeof ts === 'string' ? ts.replace(' ', 'T') : ts);
    if (isNaN(d)) return ts;
    // Fuso local do navegador (cada cliente vê no horário dele)
    return `${d.toLocaleDateString('pt-BR', {day:'2-digit',month:'2-digit',year:'numeric'})} ${d.toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit'})}`;
  }

  function _renderRow(r, i) {
    const empresa = r.empresa || r.client_name || '';
    const msg = (r.mensagem || '—').replace(/^🏪\s*\*[^*]+\*\s*\n+/, '');
    const empresaHtml = empresa
      ? `<span style="font-weight:700">🏢 ${escHtml(empresa)}</span> <span style="color:var(--text-2)">${escHtml(msg)}</span>`
      : `<span style="color:var(--text-2)">${escHtml(msg)}</span>`;
    return `
      <tr onclick="verMsgDash(${i})" style="cursor:pointer" title="Ver mensagem completa">
        <td class="mono">${escHtml(r.destinatario || '—')}</td>
        <td style="max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${empresaHtml}</td>
        <td>${_statusChip(r.status)}</td>
        <td class="mono">${_fmtTs(r.created_at)}</td>
      </tr>`;
  }

  // Mensagens atualmente exibidas (após filtro) — base do índice do onclick
  let _displayedRows = [];

  function _wppToHtml(t) {
    // *bold* → <b>, _italic_ → <i>, preserva quebras e links
    let h = escHtml(t || '');
    h = h.replace(/\*([^*\n]+)\*/g, '<b>$1</b>')
         .replace(/(^|[\s(])_([^_\n]+)_/g, '$1<i>$2</i>')
         .replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener" style="color:var(--accent)">$1</a>')
         .replace(/\n/g, '<br>');
    return h;
  }

  window.verMsgDash = function (i) {
    const r = _displayedRows[i];
    if (!r) return;
    const meta = [
      ['Destinatário', escHtml(r.destinatario || '—')],
      ['Status', _statusChip(r.status)],
      ['Data', _fmtTs(r.created_at)],
    ].map(([k, v]) => `<div style="font-size:.78rem;color:var(--text-2)"><b>${k}:</b> ${v}</div>`).join('');

    // Bloco de motivo da falha (só quando falhou/erro) — usa catálogo central
    let falhaHtml = '';
    if (r.status === 'failed' || r.status === 'error') {
      falhaHtml = `<div style="margin:.6rem 1.2rem">${window.erroBoxHtml(r.erro)}</div>`;
    }
    const ov = document.createElement('div');
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:9999;padding:1rem';
    ov.innerHTML = `
      <div style="background:var(--surface);border-radius:12px;max-width:520px;width:100%;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.3)">
        <div style="padding:1rem 1.2rem;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
          <b style="font-size:.95rem">Mensagem enviada</b>
          <button id="vmClose" style="border:none;background:none;font-size:1.3rem;cursor:pointer;color:var(--text-2);line-height:1">×</button>
        </div>
        <div style="padding:.8rem 1.2rem;display:flex;flex-direction:column;gap:.2rem;border-bottom:1px solid var(--border)">${meta}</div>
        ${falhaHtml}
        <div style="padding:1.2rem;overflow:auto;white-space:pre-wrap;word-break:break-word;font-size:.88rem;line-height:1.5;color:var(--text)">${_wppToHtml(r.mensagem || '—')}</div>
      </div>`;
    const close = () => ov.remove();
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });
    ov.querySelector('#vmClose').addEventListener('click', close);
    document.body.appendChild(ov);
  };

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

  // ── Filtro client-side de mensagens ──────────────────────────────────────
  let _msgRecentesCache = [];
  let _msgFiltro = 'todas';
  function _aplicarFiltro() {
    const tbody = document.getElementById('tbodyRecentes');
    if (!tbody) return;
    let rows = _msgRecentesCache;
    if (_msgFiltro === 'enviadas') rows = rows.filter(r => ['sent','delivered','read'].includes(r.status));
    else if (_msgFiltro === 'entregues') rows = rows.filter(r => ['delivered','read'].includes(r.status));
    else if (_msgFiltro === 'visualizadas') rows = rows.filter(r => r.status === 'read');
    else if (_msgFiltro === 'falhas') rows = rows.filter(r => r.status === 'failed' || r.status === 'error');
    _displayedRows = rows;
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--text-3);padding:1.5rem">Nenhuma mensagem ${_msgFiltro==='enviadas'?'enviada':_msgFiltro==='falhas'?'com falha':''}</td></tr>`;
    } else {
      tbody.innerHTML = rows.map(_renderRow).join('');
    }
  }
  window.filtrarMsgRecentes = function (f, btn) {
    _msgFiltro = f;
    document.querySelectorAll('#dashFiltroMsg button').forEach(b => b.classList.remove('on'));
    if (btn) btn.classList.add('on');
    _aplicarFiltro();
  };

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
      _msgRecentesCache = d.recentes || [];
      if (_msgRecentesCache.length === 0) {
        tbody.innerHTML = _renderVazio();
      } else {
        _aplicarFiltro();
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
