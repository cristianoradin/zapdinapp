// ── Módulo Arquivos ───────────────────────────────────────────────────────────
// Gestão de arquivos enviados pelo ERP.
// init() chamado pelo onPageLoad em app.js.
// stopTimer() chamado ao navegar para outra página.
// Depende de: nenhuma global de app.js além de fetch nativo.

window.arquivoModule = (() => {
  let _timer = null;
  let _initialized = false;

  function _statusChip(a) {
    const map = {
      queued:    ['badge queue dot', 'Na fila'],
      pending:   ['badge queue dot', 'Pendente'],
      failed:    ['badge fail dot',  'Falhou'],
      sent:      ['badge ok dot',    'Enviado'],
      delivered: ['badge info dot',  'Entregue'],
      read:      ['badge ok dot',    'Visualizado'],
    };
    const [cls, label] = map[a.status] || ['badge dot', a.status];
    return `<span class="${cls}">${label}</span>`;
  }

  function _fmtTs(ts) {
    if (!ts) return '—';
    const d = new Date(ts.replace(' ', 'T'));
    if (isNaN(d)) return ts;
    return `${d.toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit'})} · ${d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'})}`;
  }

  function _digits2(s) {
    s = (s || '?').trim();
    return s.length >= 1 ? s[0].toUpperCase() : '?';
  }

  async function load() {
    const res = await fetch('/api/arquivos');
    if (!res.ok) return;
    const arqs = await res.json();
    const tbody = document.getElementById('tbodyArquivos');

    const counts = { queued: 0, pending: 0, sent: 0, delivered: 0, read: 0, failed: 0 };
    arqs.forEach(a => { if (counts[a.status] !== undefined) counts[a.status]++; });
    const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setEl('arqStNaFila',   counts.queued + counts.pending);
    setEl('arqStEnviado',  counts.sent);
    setEl('arqStEntregue', counts.delivered);
    setEl('arqStVisual',   counts.read);
    setEl('arqStFalhou',   counts.failed);

    if (arqs.length === 0) {
      tbody.innerHTML = `<div class="empty-box">
        <div class="empty-ic">
          <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        </div>
        <div style="font-weight:700;color:var(--primary-deep)">Nenhum arquivo enviado ainda</div>
        <div style="font-size:13px;color:var(--text-2)">Os arquivos enviados pelo ERP aparecerão aqui.</div>
      </div>`;
      return;
    }

    tbody.innerHTML = arqs.map(a => {
      const ts = a.sent_at || a.created_at;
      const dtLabel = _fmtTs(ts);

      const dest = a.destinatario_nome || a.destinatario || '—';
      const tel = a.destinatario || '';

      return `
      <div class="file-card">
        <span class="file-ic">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        </span>
        <div class="file-info">
          <b class="file-name">${a.nome_original || '—'}</b>
          <span class="file-tel">${tel}</span>
        </div>
        <span class="file-dest">
          <span class="avatar-sm">${_digits2(dest)}</span>
          <span style="white-space:nowrap">${dest}</span>
        </span>
        <span class="file-date">
          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
          ${dtLabel}
        </span>
        ${_statusChip(a)}
        <button class="btn ghost sm" style="height:32px">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
          Ver
        </button>
      </div>`;
    }).join('');

    const hasPending = arqs.some(a => ['queued','pending','sent','delivered'].includes(a.status));
    clearTimeout(_timer);
    if (hasPending) _timer = setTimeout(load, 15_000);
  }

  function stopTimer() {
    clearTimeout(_timer);
    _timer = null;
  }

  function _registerEvents() {
    document.getElementById('btnRefreshArquivos').addEventListener('click', load);
  }

  function init() {
    if (!_initialized) {
      _registerEvents();
      _initialized = true;
    }
    load();
  }

  return { init, stopTimer };
})();
