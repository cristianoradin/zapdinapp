// ── Módulo Token API ──────────────────────────────────────────────────────────
// Gerencia Token ERP e Tokens PDV.
// init() chamado pelo onPageLoad em app.js.
// revogarPdvToken() e copiarPdvToken() expostos globalmente (usados em onclick inline).
// Autossuficiente: usa fetch diretamente, sem depender de api() de app.js.

window.tokenModule = (() => {
  let _initialized = false;

  // ── Helpers internos ─────────────────────────────────────────────────────────

  async function _fetch(method, url, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(url, opts);
    if (res.status === 401) { window.location.href = '/login'; return null; }
    try { return await res.json(); } catch { return null; }
  }

  function _alert(id, msg, type = 'success') {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = msg;
    el.className = `alert alert-${type}`;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 4000);
  }

  // ── PDV Tokens ──────────────────────────────────────────────────────────────

  async function loadPdvTokens() {
    const el = document.getElementById('pdvTokensList');
    if (!el) return;
    const tokens = await _fetch('GET', '/api/pdv/tokens');
    if (!tokens || !Array.isArray(tokens)) {
      el.innerHTML = '<div style="color:var(--red);font-size:13px">Erro ao carregar tokens.</div>';
      return;
    }
    if (!tokens.length) {
      el.innerHTML = '<div style="text-align:center;color:var(--text-3);font-size:13px;padding:1rem">Nenhum token gerado ainda.</div>';
      return;
    }
    el.innerHTML = tokens.map(t => `
      <div style="display:flex;align-items:center;gap:.6rem;padding:.6rem .1rem;border-bottom:1px solid var(--border)">
        <div style="flex:1;min-width:0">
          <div style="font-weight:700;font-size:13.5px;color:var(--text)">${t.nome}</div>
          <div style="font-size:11.5px;color:var(--text-3);margin-top:2px">
            Token: <code class="mono" style="background:var(--surface-2);padding:.1rem .35rem;border-radius:5px;color:var(--text-2)">${t.token_preview}</code>
            ${t.ultimo_uso ? `· Último uso: ${new Date(t.ultimo_uso).toLocaleString('pt-BR')}` : '· Nunca usado'}
          </div>
        </div>
        <span class="badge ${t.ativo ? 'ok' : 'fail'}">${t.ativo ? 'Ativo' : 'Revogado'}</span>
        ${t.ativo ? `<button onclick="revogarPdvToken(${t.id})" class="btn btn-ghost btn-sm" style="color:var(--red);padding:.3rem .55rem" title="Revogar">
          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
        </button>` : ''}
      </div>`).join('');
  }

  // ── Token ERP ────────────────────────────────────────────────────────────────

  function _renderErpStatus(s) {
    const hasCall = !!s.timestamp;
    const statusEl = document.getElementById('erpStatStatus');
    if (statusEl) {
      if (!hasCall) {
        statusEl.innerHTML = '<span class="badge queue">Aguardando</span>';
      } else if (s.status === 'ok') {
        statusEl.innerHTML = '<span class="badge ok">Conectado</span>';
      } else {
        statusEl.innerHTML = '<span class="badge fail">Erro</span>';
      }
    }
    document.getElementById('erpStatTs').textContent       = s.timestamp   || '—';
    document.getElementById('erpStatIp').textContent       = s.ip          || '—';
    document.getElementById('erpStatEndpoint').textContent = s.endpoint    || '—';
    document.getElementById('erpStatTotal').textContent    = s.total_calls != null ? s.total_calls : '—';
  }

  async function loadToken() {
    const [cfgRes, statRes] = await Promise.all([
      fetch('/api/erp/config'),
      fetch('/api/erp/status'),
    ]);
    if (cfgRes.ok) {
      const d = await cfgRes.json();
      document.getElementById('inputToken').value = d.token || '';
    }
    if (statRes.ok) {
      const s = await statRes.json();
      _renderErpStatus(s);
    }
  }

  // ── Eventos ──────────────────────────────────────────────────────────────────

  function _registerEvents() {
    // Gerar token PDV
    document.getElementById('btnGerarPdvToken').addEventListener('click', async () => {
      const nome = document.getElementById('inputPdvNome').value.trim();
      if (!nome) {
        _alert('alertPdvToken', 'Informe o nome do caixa antes de gerar.', 'error');
        return;
      }
      const res = await _fetch('POST', '/api/pdv/tokens', { nome });
      if (res && res.token) {
        document.getElementById('pdvTokenValor').textContent = res.token;
        document.getElementById('pdvTokenEnvLine').textContent = `ZAPDIN_PDV_TOKEN=${res.token}`;
        document.getElementById('pdvTokenGerado').style.display = 'block';
        document.getElementById('inputPdvNome').value = '';
        loadPdvTokens();
      } else {
        _alert('alertPdvToken', 'Erro ao gerar token.', 'error');
      }
    });

    // Gerar token ERP
    document.getElementById('btnGerarToken').addEventListener('click', async () => {
      const ok = await window.showConfirm({
        title: 'Gerar novo token API?',
        body: 'O token atual será invalidado imediatamente. Todas as integrações com o ERP precisarão ser atualizadas com o novo token.',
        okLabel: 'Sim, gerar novo',
        type: 'warning',
        icon: '⚠',
      });
      if (!ok) return;

      const res = await _fetch('POST', '/api/erp/gerar-token');
      if (res && res.token) {
        document.getElementById('inputToken').value = res.token;
        _alert('alertToken', 'Novo token gerado e salvo com sucesso!');
      } else {
        _alert('alertToken', 'Erro ao gerar token. Tente novamente.', 'error');
      }
    });

    // Copiar token ERP
    document.getElementById('btnCopiarToken').addEventListener('click', () => {
      const val = document.getElementById('inputToken').value;
      if (!val) return;
      _copiarTexto(val, document.getElementById('btnCopiarToken'), '📋', '✅ Copiado!');
    });

    // Atualizar status ERP
    document.getElementById('btnAtualizarErpStatus').addEventListener('click', async () => {
      const res = await fetch('/api/erp/status');
      if (res.ok) _renderErpStatus(await res.json());
    });
  }

  function init() {
    if (!_initialized) {
      _registerEvents();
      _initialized = true;
    }
    loadToken();
    loadPdvTokens();
  }

  return { init };
})();

// ── Globais para onclick inline no HTML gerado dinamicamente ─────────────────
window.revogarPdvToken = async function(id) {
  const ok = await window.showConfirm({
    title: 'Revogar token PDV?',
    body: 'O PDV que usa este token ficará desconectado do App.',
    okLabel: 'Revogar', type: 'warning', icon: '⚠',
  });
  if (!ok) return;

  const res = await fetch(`/api/pdv/tokens/${id}`, { method: 'DELETE' });
  if (res.ok) tokenModule.init();
};

function _copiarTexto(texto, btnEl, labelOriginal, labelOk) {
  const ok = () => {
    if (btnEl) {
      btnEl.textContent = labelOk || '✅ Copiado!';
      setTimeout(() => { btnEl.textContent = labelOriginal || '📋'; }, 2000);
    }
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(texto).then(ok).catch(() => _copiarFallback(texto, ok));
  } else {
    _copiarFallback(texto, ok);
  }
}

function _copiarFallback(texto, cb) {
  const ta = document.createElement('textarea');
  ta.value = texto;
  ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px';
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  try { document.execCommand('copy'); if (cb) cb(); } catch(e) {}
  document.body.removeChild(ta);
}

window.copiarPdvToken = function() {
  const val = document.getElementById('pdvTokenValor').textContent;
  if (!val) return;
  _copiarFallback(val, () => {
    const el = document.getElementById('alertPdvToken');
    if (el) {
      el.textContent = 'Token copiado!';
      el.className = 'alert alert-success';
      el.style.display = 'block';
      setTimeout(() => { el.style.display = 'none'; }, 2000);
    }
  });
};
