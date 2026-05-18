// ── Módulo Token API ──────────────────────────────────────────────────────────
// Gerencia Token ERP e Tokens PDV.
// init() chamado pelo onPageLoad em app.js.
// revogarPdvToken() e copiarPdvToken() expostos globalmente (usados em onclick inline).
// Depende de: api(), showAlert(), showConfirm() — globais em app.js.

window.tokenModule = (() => {
  let _initialized = false;

  // ── PDV Tokens ──────────────────────────────────────────────────────────────

  async function loadPdvTokens() {
    const el = document.getElementById('pdvTokensList');
    if (!el) return;
    const res = await api('GET', '/api/pdv/tokens');
    if (!res || res.detail) {
      el.innerHTML = '<div style="color:#dc2626;font-size:.82rem">Erro ao carregar tokens.</div>';
      return;
    }
    const tokens = Array.isArray(res) ? res : [];
    if (!tokens.length) {
      el.innerHTML = '<div style="text-align:center;color:var(--text-mid);font-size:.85rem;padding:1rem">Nenhum token gerado ainda.</div>';
      return;
    }
    el.innerHTML = tokens.map(t => `
      <div style="display:flex;align-items:center;gap:.6rem;padding:.55rem .1rem;border-bottom:1px solid var(--border)">
        <div style="flex:1;min-width:0">
          <div style="font-weight:600;font-size:.88rem">${t.nome}</div>
          <div style="font-size:.74rem;color:var(--text-mid)">
            Token: <code style="background:var(--surface2);padding:.1rem .3rem;border-radius:4px">${t.token_preview}</code>
            ${t.ultimo_uso ? `· Último uso: ${new Date(t.ultimo_uso).toLocaleString('pt-BR')}` : '· Nunca usado'}
          </div>
        </div>
        <span style="padding:.2rem .55rem;border-radius:10px;font-size:.72rem;font-weight:700;background:${t.ativo ? '#dcfce7' : '#f1f5f9'};color:${t.ativo ? '#15803d' : '#475569'}">${t.ativo ? 'Ativo' : 'Revogado'}</span>
        ${t.ativo ? `<button onclick="revogarPdvToken(${t.id})" class="btn btn-ghost btn-sm" style="color:#dc2626;padding:.25rem .5rem" title="Revogar">🗑</button>` : ''}
      </div>`).join('');
  }

  // ── Token ERP ────────────────────────────────────────────────────────────────

  function _renderErpStatus(s) {
    const hasCall  = !!s.timestamp;
    const statusEl = document.getElementById('erpStatStatus');
    const cardEl   = statusEl ? statusEl.closest('.erp-stat-card') : null;

    if (!hasCall) {
      statusEl.textContent = '⭕ Aguardando';
      if (cardEl) { cardEl.className = 'erp-stat-card erp-sc-gray'; }
    } else if (s.status === 'ok') {
      statusEl.innerHTML = 'Conectado';
      if (cardEl) { cardEl.className = 'erp-stat-card erp-sc-green'; }
    } else {
      statusEl.innerHTML = 'Erro';
      if (cardEl) { cardEl.className = 'erp-stat-card erp-sc-red'; cardEl.style.cssText += ';background:linear-gradient(135deg,#fff5f5,#fee2e2);border-color:#fecaca'; }
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
    document.getElementById('btnGerarPdvToken').addEventListener('click', async () => {
      const nome = document.getElementById('inputPdvNome').value.trim();
      if (!nome) {
        showAlert('alertPdvToken', 'Informe o nome do caixa antes de gerar.', 'error');
        return;
      }
      const res = await api('POST', '/api/pdv/tokens', { nome });
      if (res && res.token) {
        document.getElementById('pdvTokenValor').textContent = res.token;
        document.getElementById('pdvTokenEnvLine').textContent = `ZAPDIN_PDV_TOKEN=${res.token}`;
        document.getElementById('pdvTokenGerado').style.display = 'block';
        document.getElementById('inputPdvNome').value = '';
        loadPdvTokens();
      } else {
        showAlert('alertPdvToken', 'Erro ao gerar token.', 'error');
      }
    });

    document.getElementById('btnGerarToken').addEventListener('click', async () => {
      const ok = await showConfirm({
        title: 'Gerar novo token API?',
        body: 'O token atual será invalidado imediatamente. Todas as integrações com o ERP precisarão ser atualizadas com o novo token.',
        okLabel: 'Sim, gerar novo',
        type: 'warning',
        icon: '⚠',
      });
      if (!ok) return;
      const res = await api('POST', '/api/erp/gerar-token');
      if (res.ok) {
        document.getElementById('inputToken').value = res.token;
        showAlert('alertToken', 'Novo token gerado e salvo com sucesso!');
      } else {
        showAlert('alertToken', 'Erro ao gerar token', 'error');
      }
    });

    document.getElementById('btnCopiarToken').addEventListener('click', () => {
      const val = document.getElementById('inputToken').value;
      if (!val) return;
      navigator.clipboard.writeText(val).then(() => {
        const btn = document.getElementById('btnCopiarToken');
        btn.textContent = '✅ Copiado!';
        setTimeout(() => { btn.textContent = '📋 Copiar'; }, 2000);
      });
    });

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
  const ok = await showConfirm({
    title: 'Revogar token PDV?',
    body: 'O PDV que usa este token ficará desconectado do App.',
    okLabel: 'Revogar', type: 'warning', icon: '⚠',
  });
  if (!ok) return;
  await api('DELETE', `/api/pdv/tokens/${id}`);
  tokenModule.init();
};

window.copiarPdvToken = function() {
  const val = document.getElementById('pdvTokenValor').textContent;
  if (!val) return;
  navigator.clipboard.writeText(val).then(() => {
    showAlert('alertPdvToken', 'Token copiado!');
  });
};
