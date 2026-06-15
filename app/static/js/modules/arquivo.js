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
        <button class="btn ghost sm" style="height:32px" onclick="arquivoModule.view(${a.id})">
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

  function _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function _renderBody(meta) {
    const body = document.getElementById('arqViewBody');
    const dl = document.getElementById('arqViewDownload');
    const hasFile = meta.has_file;
    const caption = meta.caption || '';

    let html = '';
    if (caption) {
      html += `<div class="arq-msg">${_esc(caption).replace(/\n/g,'<br>')}</div>`;
    }

    if (hasFile) {
      dl.style.display = '';
      dl.href = `/api/arquivos/${meta.id}/download`;
      dl.download = meta.nome_original || 'arquivo';
      const mime = meta.mime || '';
      const url = `/api/arquivos/${meta.id}/download`;
      if (mime.startsWith('image/')) {
        html += `<img src="${url}" alt="${_esc(meta.nome_original)}" style="max-width:100%;border-radius:8px;display:block;margin:0 auto">`;
      } else if (mime === 'application/pdf') {
        html += `<iframe src="${url}" style="width:100%;height:70vh;border:0;border-radius:8px"></iframe>`;
      } else if (mime.startsWith('text/')) {
        html += `<iframe src="${url}" style="width:100%;height:50vh;border:1px solid var(--border);border-radius:8px;background:#fff"></iframe>`;
      } else {
        html += `<div class="arq-fallback">
          <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          <div><b>${_esc(meta.nome_original || 'arquivo')}</b></div>
          <div style="font-size:13px;color:var(--text-3)">Preview indisponível para este tipo (${_esc(mime)}). Use o botão Baixar.</div>
        </div>`;
      }
    } else {
      dl.style.display = 'none';
      if (!caption) {
        html += `<div class="arq-fallback" style="color:var(--text-3)">Envio sem conteúdo registrado.</div>`;
      }
    }
    body.innerHTML = html;
  }

  async function view(id) {
    const modal = document.getElementById('arqViewModal');
    const meta = document.getElementById('arqViewMeta');
    const body = document.getElementById('arqViewBody');
    const title = document.getElementById('arqViewTitle');
    modal.style.display = 'flex';
    title.textContent = 'Carregando…';
    meta.innerHTML = '';
    body.innerHTML = '<div style="color:var(--text-3);text-align:center;padding:2rem">Carregando…</div>';
    try {
      const res = await fetch(`/api/arquivos/${id}`);
      if (!res.ok) {
        body.innerHTML = `<div class="arq-fallback" style="color:var(--red)">Erro ${res.status}: ${await res.text()}</div>`;
        return;
      }
      const m = await res.json();
      title.textContent = m.has_file
        ? (m.nome_original || `Envio #${m.id}`)
        : `Mensagem enviada — ${m.destinatario || ''}`;
      const items = [
        ['Destinatário', `${_esc(m.nome_destinatario || '—')} <span style="color:var(--text-3)">${_esc(m.destinatario || '')}</span>`],
        ['Status', _statusChip(m)],
        ['Criado', _fmtTs(m.created_at)],
      ];
      if (m.sent_at)      items.push(['Enviado', _fmtTs(m.sent_at)]);
      if (m.delivered_at) items.push(['Entregue', _fmtTs(m.delivered_at)]);
      if (m.read_at)      items.push(['Visualizado', _fmtTs(m.read_at)]);
      if (m.has_file && m.tamanho) items.push(['Tamanho', `${(m.tamanho/1024).toFixed(1)} KB`]);
      meta.innerHTML = items.map(([k,v]) => `<div><span class="k">${k}:</span> <span class="v">${v}</span></div>`).join('');
      _renderBody(m);
    } catch (e) {
      body.innerHTML = `<div class="arq-fallback" style="color:var(--red)">Falha ao carregar: ${_esc(e.message)}</div>`;
    }
  }

  function closeView() {
    const modal = document.getElementById('arqViewModal');
    if (modal) modal.style.display = 'none';
    const body = document.getElementById('arqViewBody');
    if (body) body.innerHTML = '';
  }

  function init() {
    if (!_initialized) {
      _registerEvents();
      _initialized = true;
    }
    load();
  }

  return { init, stopTimer, view, closeView };
})();
