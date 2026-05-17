(function () {
  'use strict';
  const API = '/api/syslog';
  let _state = { nivel: '', modulo: '', busca: '', offset: 0, limit: 100, total: 0, autoRefresh: null };

  const NIVEL_BADGE = {
    info:     '<span style="background:#f0f9ff;color:#0369a1;border:1px solid #bae6fd;padding:1px 7px;border-radius:20px;font-size:.72rem;font-weight:700">INFO</span>',
    warn:     '<span style="background:#fffbeb;color:#b45309;border:1px solid #fde68a;padding:1px 7px;border-radius:20px;font-size:.72rem;font-weight:700">WARN</span>',
    error:    '<span style="background:#fef2f2;color:#dc2626;border:1px solid #fecaca;padding:1px 7px;border-radius:20px;font-size:.72rem;font-weight:700">ERRO</span>',
    critical: '<span style="background:#4c0519;color:#fecdd3;border:1px solid #9f1239;padding:1px 7px;border-radius:20px;font-size:.72rem;font-weight:700">CRÍTICO</span>',
  };
  const MODULO_BADGE = {
    whatsapp:  '#dcfce7', ia: '#f0f9ff', erp: '#fdf4ff',
    campanhas: '#fff7ed', auth: '#f1f5f9', monitor: '#fefce8',
    sistema:   '#f8fafc', chatbot: '#ecfdf5', dominio: '#eff6ff',
    worker:    '#fdf4ff',
  };

  function _fmtDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }
  function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  async function carregar(reset) {
    if (reset) _state.offset = 0;
    const params = new URLSearchParams({
      limit: _state.limit, offset: _state.offset,
      nivel: _state.nivel, modulo: _state.modulo, busca: _state.busca,
    });
    const tbody = document.getElementById('syslogBody');
    const counter = document.getElementById('syslogCounter');
    if (!tbody) return;
    try {
      const res = await fetch(API + '?' + params);
      if (!res.ok) return;
      const d = await res.json();
      _state.total = d.total;
      if (counter) counter.textContent = `${d.total.toLocaleString()} eventos`;
      _renderRows(tbody, d.logs);
      _renderPager();
    } catch(e) {
      if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="table-empty">Erro ao carregar logs</td></tr>';
    }
  }

  function _renderRows(tbody, logs) {
    if (!logs.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="table-empty" style="padding:2rem">Nenhum evento encontrado</td></tr>';
      return;
    }
    tbody.innerHTML = logs.map(l => {
      const bg = MODULO_BADGE[l.modulo] || '#f8fafc';
      const det = l.detalhe ? `<details style="margin-top:.3rem"><summary style="font-size:.75rem;color:var(--text-muted);cursor:pointer">Ver detalhe</summary><pre style="font-size:.72rem;background:var(--bg);padding:.4rem .6rem;border-radius:6px;margin-top:.3rem;white-space:pre-wrap;word-break:break-all">${esc(l.detalhe)}</pre></details>` : '';
      return `<tr>
        <td style="white-space:nowrap;font-size:.78rem;color:var(--text-muted)">${_fmtDate(l.created_at)}</td>
        <td>${NIVEL_BADGE[l.nivel] || esc(l.nivel)}</td>
        <td><span style="background:${bg};padding:2px 8px;border-radius:12px;font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em">${esc(l.modulo)}</span></td>
        <td style="font-size:.8rem;font-family:monospace;color:var(--text-muted)">${esc(l.acao)}</td>
        <td style="font-size:.83rem">${esc(l.mensagem)}${det}</td>
        <td style="font-size:.75rem;color:var(--text-muted)">${l.empresa_id || '—'}</td>
      </tr>`;
    }).join('');
  }

  function _renderPager() {
    const el = document.getElementById('syslogPager');
    if (!el) return;
    const totalPag = Math.ceil(_state.total / _state.limit);
    const curPag = Math.floor(_state.offset / _state.limit) + 1;
    if (totalPag <= 1) { el.innerHTML = ''; return; }
    el.innerHTML = `
      <button class="btn btn-sm" onclick="syslog.pagPrev()" ${_state.offset === 0 ? 'disabled' : ''}>← Anterior</button>
      <span style="font-size:.82rem;color:var(--text-muted)">Página ${curPag} de ${totalPag}</span>
      <button class="btn btn-sm" onclick="syslog.pagNext()" ${_state.offset + _state.limit >= _state.total ? 'disabled' : ''}>Próxima →</button>
    `;
  }

  function pagNext() { if (_state.offset + _state.limit < _state.total) { _state.offset += _state.limit; carregar(); } }
  function pagPrev() { if (_state.offset > 0) { _state.offset = Math.max(0, _state.offset - _state.limit); carregar(); } }

  function setFiltro(key, val) { _state[key] = val; carregar(true); }

  function toggleAutoRefresh(btn) {
    if (_state.autoRefresh) {
      clearInterval(_state.autoRefresh);
      _state.autoRefresh = null;
      if (btn) btn.textContent = '▶ Auto-refresh';
    } else {
      _state.autoRefresh = setInterval(() => carregar(), 10000);
      if (btn) btn.textContent = '⏸ Auto-refresh ON';
      carregar();
    }
  }

  async function exportar() {
    const params = new URLSearchParams({ nivel: _state.nivel, modulo: _state.modulo, busca: _state.busca });
    window.open(API + '/export?' + params, '_blank');
  }

  async function limpar() {
    if (!confirm('Apagar logs com mais de 30 dias?')) return;
    const res = await fetch(API + '?dias=30', { method: 'DELETE' });
    const d = await res.json().catch(() => ({}));
    alert(`${d.deleted || 0} registros removidos.`);
    carregar(true);
  }

  async function testar() {
    await fetch(API + '/teste', { method: 'POST' });
    carregar(true);
  }

  window.syslog = { carregar, setFiltro, pagNext, pagPrev, toggleAutoRefresh, exportar, limpar, testar };
})();
