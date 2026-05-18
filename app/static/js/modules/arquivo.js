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
      queued:    ['chip-yellow', '&#x23F3; Na fila'],
      pending:   ['chip-yellow', '&#x23F3; Pendente'],
      failed:    ['chip-red',    '&#x2717; Falhou'],
      sent:      ['chip-gray',   '&#x2713; Enviado'],
      delivered: ['chip-blue',   '&#x2713;&#x2713; Entregue'],
      read:      ['chip-green',  '&#x2713;&#x2713; Visualizado'],
    };
    const [cls, label] = map[a.status] || ['chip-gray', a.status];
    return `<span class="chip ${cls}">${label}</span>`;
  }

  function _fmtTs(ts) {
    if (!ts) return '<span style="color:var(--text-mid)">—</span>';
    const d = new Date(ts.replace(' ', 'T'));
    if (isNaN(d)) return ts;
    return `<span style="font-size:.78rem;color:var(--text-mid)">${d.toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit'})} ${d.toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'})}</span>`;
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
      tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;padding:3rem 1rem">
        <div style="font-size:2rem;margin-bottom:.5rem">📭</div>
        <div style="color:var(--text-mid);font-size:.9rem">Nenhum arquivo enviado ainda.</div>
        <div style="color:var(--text-light);font-size:.8rem;margin-top:.25rem">Os arquivos enviados pelo ERP aparecerão aqui.</div>
      </td></tr>`;
      return;
    }

    tbody.innerHTML = arqs.map(a => {
      const ts = a.sent_at || a.created_at;
      const dtLabel = _fmtTs(ts);
      let detail = '';
      if (a.delivered_at) detail += `<span style="color:#1a7db5">✓✓ ${a.delivered_at.slice(11,16)}</span> `;
      if (a.read_at)       detail += `<span style="color:var(--accent)">✓✓ vis. ${a.read_at.slice(11,16)}</span>`;

      const ext = (a.nome_original || '').split('.').pop().toLowerCase();
      const _svgPDF  = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15h6M9 11h3"/></svg>`;
      const _svgIMG  = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`;
      const _svgFILE = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6b7280" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>`;
      const icon = ext === 'pdf' ? _svgPDF : ['jpg','jpeg','png','gif','webp'].includes(ext) ? _svgIMG : _svgFILE;

      return `
      <tr>
        <td>
          <div style="display:flex;align-items:center;gap:.5rem">
            <span style="display:flex;align-items:center;width:28px;height:28px;background:var(--surface2);border-radius:6px;justify-content:center;flex-shrink:0">${icon}</span>
            <div>
              <div style="font-size:.85rem;font-weight:600;color:var(--text)">${a.nome_original}</div>
              ${a.caption ? `<div style="font-size:.72rem;color:var(--text-mid);margin-top:.1rem">${a.caption}</div>` : ''}
            </div>
          </div>
        </td>
        <td><span style="font-size:.8rem;font-family:monospace;background:var(--surface2);padding:.2rem .5rem;border-radius:5px;color:var(--text-mid)">${a.destinatario || '—'}</span></td>
        <td>${dtLabel}</td>
        <td>
          ${_statusChip(a)}
          ${detail ? `<div style="font-size:.68rem;margin-top:.3rem;line-height:1.6">${detail}</div>` : ''}
        </td>
      </tr>`;
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
