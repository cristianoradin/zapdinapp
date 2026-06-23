// ── Módulo WhatsApp Sessions ──────────────────────────────────────────────────
// Gerencia sessões WhatsApp, QR codes e modal de teste de envio.
// init() e stop() chamados pelo onPageLoad em app.js.
// toggleQR, abrirModalTeste, fecharModalTeste, deleteSessao expostos globalmente
// (usados em onclick inline no HTML gerado dinamicamente).
// Autossuficiente: usa fetch diretamente, sem depender de api() de app.js.

window.whatsappModule = (() => {
  let _initialized = false;

  // ── Constantes de status ────────────────────────────────────────────────────

  const STATUS_LABEL = {
    connected: 'Conectado', qr: 'Aguardando QR',
    connecting: 'Conectando…', disconnected: 'Desconectado', error: 'Erro',
  };
  const STATUS_CHIP = {
    connected: 'chip-green', qr: 'chip-yellow',
    connecting: 'chip-yellow', disconnected: 'chip-gray', error: 'chip-red',
  };

  // ── Estado interno ──────────────────────────────────────────────────────────

  let _waRefresh = null;
  let _waRefreshInterval = 5000;
  const _qrPollers = {};
  let _modalSessaoId = null;

  // ── Helpers internos ─────────────────────────────────────────────────────────

  async function _post(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
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

  function _formatPhone(phone) {
    if (!phone) return '';
    const d = phone.replace(/\D/g, '');
    if (d.startsWith('55') && d.length >= 12) {
      const ddd = d.slice(2, 4);
      const num = d.slice(4);
      if (num.length === 9) return `+55 (${ddd}) ${num.slice(0,5)}-${num.slice(5)}`;
      if (num.length === 8) return `+55 (${ddd}) ${num.slice(0,4)}-${num.slice(4)}`;
    }
    return phone;
  }

  // ── QR Code ────────────────────────────────────────────────────────────────

  function _stopQrPoller(id) {
    if (_qrPollers[id]) { clearInterval(_qrPollers[id]); delete _qrPollers[id]; }
  }

  async function _fetchQR(id) {
    try {
      const res = await fetch('/api/sessoes/qr/' + id);
      if (res.status === 409) {
        // 409 = WhatsApp já conectado — pega phone + atualiza lista
        await _refreshPhone(id);
        return 'CONNECTED';
      }
      if (!res.ok) return null;
      const d = await res.json();
      return d.qr || null;
    } catch { return null; }
  }

  async function _refreshPhone(id) {
    try {
      const r = await fetch('/api/sessoes/refresh-phone/' + id, { method: 'POST' });
      if (r.ok) {
        const d = await r.json();
        if (d.phone) {
          // Recarrega lista pra mostrar número
          if (typeof loadSessoes === 'function') loadSessoes();
        }
      }
    } catch { /* silent */ }
  }

  function _setQrImg(id, qrDataUrl) {
    const wrap = document.getElementById('qrimg-' + id);
    if (!wrap) return;
    wrap.innerHTML = `<img src="${qrDataUrl}" alt="QR Code WhatsApp" style="width:148px;height:148px;object-fit:contain" />`;
  }

  function _startQrPoller(id) {
    _stopQrPoller(id);
    _qrPollers[id] = setInterval(async () => {
      const qr = await _fetchQR(id);
      if (qr === 'CONNECTED') {
        // WA logado — para polling QR + atualiza UI
        _stopQrPoller(id);
        return;
      }
      if (qr) _setQrImg(id, qr);
    }, 4000);
  }

  // ── Render de sessão ───────────────────────────────────────────────────────

  function _renderSessao(s) {
    const label = STATUS_LABEL[s.status] || s.status;
    const chip  = STATUS_CHIP[s.status] || 'chip-gray';
    const isAgente = (s.evolution_url || '').toLowerCase().startsWith('agent://');
    const isLocal  = !isAgente && (!!s.evolution_url || s.modo === 'local');
    let modoBadge;
    if (isAgente) {
      modoBadge = `<span title="Roteado via WebSocket persistente para o agente local — atravessa NAT" style="display:inline-flex;align-items:center;gap:.25rem;font-size:.7rem;font-weight:600;padding:.15rem .5rem;border-radius:10px;background:#dbeafe;color:#1e40af;margin-left:.5rem">🛰️ Agente</span>`;
    } else if (isLocal) {
      modoBadge = `<span title="Evolution roda na máquina do cliente — anti-ban por IP próprio${s.evolution_url ? ': ' + s.evolution_url : ''}" style="display:inline-flex;align-items:center;gap:.25rem;font-size:.7rem;font-weight:600;padding:.15rem .5rem;border-radius:10px;background:#e0f2fe;color:#075985;margin-left:.5rem">🏠 Local</span>`;
    } else {
      modoBadge = `<span title="Evolution roda no servidor (modo padrão)" style="display:inline-flex;align-items:center;gap:.25rem;font-size:.7rem;font-weight:600;padding:.15rem .5rem;border-radius:10px;background:#f3f4f6;color:#374151;margin-left:.5rem">🌐 Servidor</span>`;
    }
    return `
      <div class="sessao-card status-${s.status}" id="card-${s.id}">
        <div class="sessao-header">
          <span class="sessao-nome">${s.nome}${modoBadge}</span>
          <div class="sessao-actions">
            <span class="chip ${chip}">${label}</span>
            ${s.status !== 'connected'
              ? `<button class="btn btn-ghost btn-sm" onclick="toggleQR('${s.id}')">Mostrar QR</button>`
              : `<button class="btn btn-ghost btn-sm" onclick="toggleQR('${s.id}')">Ver info</button>
                 <button class="btn btn-primary btn-sm" onclick="abrirModalTeste('${s.id}','${s.nome.replace(/'/g,"\\'")}')">Testar Envio</button>`}
            <button class="btn btn-ghost btn-sm" onclick="sessaoAbrirUsos('${s.id}')" title="Configurar propósito desta sessão" style="display:inline-flex;align-items:center;gap:.3rem">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              Propósito
            </button>
            <button class="btn btn-danger-outline btn-sm" onclick="deleteSessao('${s.id}')" style="display:inline-flex;align-items:center;gap:.3rem">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
              Remover
            </button>
          </div>
        </div>
        <div class="sessao-meta">ID: ${s.id}${s.phone ? ' · ' + _formatPhone(s.phone) : ''}</div>

        ${s.status === 'connected' ? `
        <div class="qr-connected-msg visible" id="conn-${s.id}">
          <div class="qr-connected-icon">✅</div>
          <p>WhatsApp conectado e pronto para enviar mensagens!</p>
          ${s.phone ? `<div class="sessao-phone-badge">📱 ${_formatPhone(s.phone)}</div>` : '<span style="color:var(--text-2);font-size:.78rem">Número não identificado</span>'}
        </div>` : `
        <div class="qr-area qr-area-clean" id="qrarea-${s.id}">
          <div class="qr-card" id="qrbox-${s.id}">
            <div class="qr-img-wrap" id="qrimg-${s.id}">
              <div class="qr-loading">
                <div class="qr-spinner"></div>
                <span>Aguardando QR…</span>
              </div>
            </div>
            <div class="qr-steps">
              <span>1. Abra o WhatsApp no celular</span>
              <span>2. <b>⋮ Menu → Aparelhos conectados</b></span>
              <span>3. Conectar aparelho e escanear o QR</span>
            </div>
          </div>
        </div>`}
      </div>`;
  }

  // ── Carregar sessões ───────────────────────────────────────────────────────

  async function loadSessoes() {
    const res = await fetch('/api/sessoes/live-status');
    if (!res.ok) return;
    const sessoes = await res.json();
    // Atualiza o indicador do topo imediatamente (não espera o intervalo de 30s)
    window._updateTopbarStatus?.();
    const cont = document.getElementById('listaSessoes');
    if (!cont) return;
    if (sessoes.length === 0) {
      cont.innerHTML = `<div class="empty-box">
        <div class="empty-ic">
          <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
        </div>
        <div style="font-weight:700;color:var(--primary-deep)">Nenhum número conectado</div>
        <div style="font-size:13px;color:var(--text-2)">Digite um nome abaixo e clique em <b>Adicionar</b> para começar.</div>
      </div>`;
      return;
    }
    const abertos = new Set(
      Array.from(document.querySelectorAll('.qr-area.visible'))
           .map(el => el.id.replace('qrarea-', ''))
    );
    Object.keys(_qrPollers).forEach(_stopQrPoller);
    cont.innerHTML = sessoes.map(_renderSessao).join('');
    sessoes.forEach(s => {
      if (s.status === 'connected') return;
      const area = document.getElementById('qrarea-' + s.id);
      if (!area) return;
      if (abertos.has(s.id) || s.status === 'qr') {
        area.classList.add('visible');
        _startQrPoller(s.id);
        _fetchQR(s.id).then(qr => { if (qr) _setQrImg(s.id, qr); });
      }
    });
  }

  // ── Toggle QR ─────────────────────────────────────────────────────────────

  async function toggleQR(id) {
    const area = document.getElementById('qrarea-' + id);
    if (!area) return;
    if (area.classList.contains('visible')) {
      area.classList.remove('visible');
      _stopQrPoller(id);
    } else {
      area.classList.add('visible');
      _startQrPoller(id);
      const qr = await _fetchQR(id);
      if (qr) _setQrImg(id, qr);
    }
  }

  // ── Remover sessão ─────────────────────────────────────────────────────────

  async function deleteSessao(id) {
    const ok = await window.showConfirm({
      title: 'Remover sessão WhatsApp?',
      body: 'A sessão será desconectada e os dados do QR serão apagados. Você precisará escanear um novo código para reconectar.',
      okLabel: 'Sim, remover',
      type: 'danger',
      icon: '📱',
    });
    if (!ok) return;
    _stopQrPoller(id);
    await fetch('/api/sessoes/' + id, { method: 'DELETE' });
    loadSessoes();
  }

  // ── Refresh adaptativo ─────────────────────────────────────────────────────

  async function _refreshWAAdaptive() {
    await loadSessoes();
    const cont = document.getElementById('listaSessoes');
    const hasPending = cont && cont.querySelector('.chip-yellow, .chip-red, .chip-gray');
    const next = hasPending ? 2000 : 5000;
    if (next !== _waRefreshInterval) {
      _waRefreshInterval = next;
      _iniciarRefreshWA();
    }
  }

  function _iniciarRefreshWA() {
    _pararRefreshWA();
    _waRefresh = setInterval(_refreshWAAdaptive, _waRefreshInterval);
  }

  function _pararRefreshWA() {
    if (_waRefresh) { clearInterval(_waRefresh); _waRefresh = null; }
    Object.keys(_qrPollers).forEach(_stopQrPoller);
  }

  // ── Modal Teste de Envio ───────────────────────────────────────────────────

  function _setModalResult(type, msg) {
    const el = document.getElementById('modalTesteResult');
    if (!el) return;
    el.className = 'modal-result ' + (type === 'ok' ? 'ok' : 'err');
    el.textContent = msg;
  }

  function _switchTab(tab) {
    document.querySelectorAll('.modal-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('.modal-panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + tab));
  }

  async function abrirModalTeste(sessaoId, sessaoNome) {
    _modalSessaoId = sessaoId;
    const overlay = document.getElementById('testeEnvioOverlay');
    if (!overlay) return;
    const tit = document.getElementById('testeEnvioTitulo');
    if (tit) tit.textContent = `Teste de Envio — ${sessaoNome}`;
    // Reset result
    const resEl = document.getElementById('testeMsgResult');
    if (resEl) { resEl.style.display = 'none'; resEl.textContent = ''; }
    overlay.classList.add('open');
    // Inicializa bind + dropdown + preview (idempotente)
    if (typeof window.initTesteEnvio === 'function') {
      await window.initTesteEnvio();
    }
    // Pre-seleciona sessão clicada
    const sel = document.getElementById('testeMsgSessao');
    if (sel) {
      const opt = Array.from(sel.options).find(o => o.value === sessaoId);
      if (opt) sel.value = sessaoId;
    }
  }

  function fecharModalTeste() {
    const overlay = document.getElementById('testeEnvioOverlay');
    if (overlay) overlay.classList.remove('open');
    _modalSessaoId = null;
  }

  // ── Registro de eventos (executado uma única vez) ─────────────────────────

  async function _applyModosPermitidos() {
    // Busca modos permitidos pra empresa logada + esconde radios não permitidos
    try {
      const r = await fetch('/api/sessoes/modos-permitidos');
      if (!r.ok) return;
      const d = await r.json();
      const allowed = new Set(d.modos || ['servidor', 'local', 'agente']);
      document.querySelectorAll('input[name="sessaoModo"]').forEach(inp => {
        const lbl = inp.closest('label.adv-radio');
        if (!lbl) return;
        if (!allowed.has(inp.value)) {
          lbl.style.display = 'none';
        } else {
          lbl.style.display = '';
        }
      });
      // Se modo atual checked foi escondido, marca primeiro permitido
      const checked = document.querySelector('input[name="sessaoModo"]:checked');
      if (checked && !allowed.has(checked.value)) {
        const firstAllowed = document.querySelector('input[name="sessaoModo"]:not([style*="display: none"])')
                          || [...document.querySelectorAll('input[name="sessaoModo"]')].find(i => allowed.has(i.value));
        if (firstAllowed) {
          firstAllowed.checked = true;
          firstAllowed.dispatchEvent(new Event('change', { bubbles: true }));
        }
      }
    } catch { /* silent */ }
  }

  function _registerEvents() {
    // Toggle Local/Agente/Servidor — mostra/esconde inputs auxiliares
    const MODO_LBL = {
      servidor: '🌐 Servidor (padrão)',
      local:    '🏠 Local no cliente (LAN)',
      agente:   '🛰️ ZapDinAgent (ponte WhatsApp local)',
    };
    _applyModosPermitidos();
    document.querySelectorAll('input[name="sessaoModo"]').forEach(r => {
      r.addEventListener('change', () => {
        const wrap   = document.getElementById('sessaoUrlWrap');
        const agWrap = document.getElementById('sessaoAgenteWrap');
        const badge  = document.getElementById('sessaoModoBadge');
        const det    = document.getElementById('sessaoModoDetails');
        const checked = document.querySelector('input[name="sessaoModo"]:checked');
        const v = checked ? checked.value : 'servidor';
        // Atualiza highlight visual: class .on no label pai do radio checked
        document.querySelectorAll('label.adv-radio').forEach(l => l.classList.remove('on'));
        if (checked) {
          const lbl = checked.closest('label.adv-radio');
          if (lbl) lbl.classList.add('on');
        }
        if (wrap)   wrap.style.display   = (v === 'local')  ? 'block' : 'none';
        if (agWrap) agWrap.style.display = (v === 'agente') ? 'block' : 'none';
        if (badge)  badge.textContent    = MODO_LBL[v] || MODO_LBL.servidor;
        // Modo não-padrão → mantém aberto pra o operador ver o que escolheu
        if (det && v !== 'servidor') det.open = true;
      });
    });

    // Adicionar sessão
    document.getElementById('btnAddSessao').addEventListener('click', async () => {
      const nome = document.getElementById('inputNovaSessao').value.trim();
      if (!nome) { _alert('alertWA', 'Digite um nome para a sessão.', 'error'); return; }
      const modo = (document.querySelector('input[name="sessaoModo"]:checked') || {}).value || 'servidor';
      let evolution_url = null;
      if (modo === 'local') {
        evolution_url = (document.getElementById('inputSessaoUrl').value || '').trim();
        if (!evolution_url) { _alert('alertWA', 'Informe a URL da Evolution local do cliente.', 'error'); return; }
        if (!/^https?:\/\//i.test(evolution_url)) {
          _alert('alertWA', 'URL inválida. Use http:// ou https://', 'error'); return;
        }
      } else if (modo === 'agente') {
        evolution_url = 'agent://';
      }
      const btn = document.getElementById('btnAddSessao');
      btn.disabled = true;
      btn.textContent = 'Criando…';
      try {
        const payload = { nome };
        if (evolution_url) payload.evolution_url = evolution_url;
        const res = await _post('/api/sessoes', payload);
        if (res && (res.ok || res.id)) {
          document.getElementById('inputNovaSessao').value = '';
          const _u = document.getElementById('inputSessaoUrl'); if (_u) _u.value = '';
          const _srv = document.querySelector('input[name="sessaoModo"][value="servidor"]');
          if (_srv) {
            _srv.checked = true;
            document.getElementById('sessaoUrlWrap').style.display = 'none';
            const _ag = document.getElementById('sessaoAgenteWrap'); if (_ag) _ag.style.display = 'none';
            // Mantém details aberto pra próxima sessão (usuário precisa ver opções)
            const _det = document.getElementById('sessaoModoDetails'); if (_det) _det.open = true;
            const _bd = document.getElementById('sessaoModoBadge'); if (_bd) _bd.textContent = '🌐 Servidor (padrão)';
          }
          const _modoLbl = !evolution_url ? '🌐 servidor'
                          : (evolution_url.toLowerCase().startsWith('agent://') ? '🛰️ agente' : '🏠 local');
          _alert('alertWA', `Sessão "${nome}" criada (${_modoLbl}). Escaneie o QR Code abaixo.`);
          await loadSessoes();
          const id = res.id;
          if (id) {
            const area = document.getElementById('qrarea-' + id);
            if (area) {
              area.classList.add('visible');
              _startQrPoller(id);
              _fetchQR(id).then(qr => { if (qr) _setQrImg(id, qr); });
            }
          }
        } else {
          _alert('alertWA', (res && res.detail) || 'Erro ao criar sessão. Tente novamente.', 'error');
        }
      } catch(e) {
        _alert('alertWA', 'Erro de conexão ao criar sessão.', 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = '+ Adicionar';
      }
    });

    // Modal — tabs
    document.querySelectorAll('.modal-tab').forEach(b =>
      b.addEventListener('click', () => _switchTab(b.dataset.tab))
    );

    // Modal — fechar
    const closebtn = document.getElementById('modalClosebtn');
    if (closebtn) closebtn.addEventListener('click', fecharModalTeste);
    const overlay = document.getElementById('modalOverlay');
    if (overlay) overlay.addEventListener('click', e => { if (e.target === e.currentTarget) fecharModalTeste(); });

    // Modal — enviar texto (guarded — modal may not be in DOM)
    const _btnEnvTexto = document.getElementById('btnEnviarTexto');
    if (_btnEnvTexto) _btnEnvTexto.addEventListener('click', async () => {
      const phone = '55' + document.getElementById('testePhone').value.trim().replace(/\D/g, '');
      const msg   = document.getElementById('testeMsg').value.trim();
      if (phone.length < 12 || !msg) { _setModalResult('error', 'Preencha o número (DDD + número) e a mensagem.'); return; }
      const res = await _post(`/api/sessoes/${_modalSessaoId}/send-text`, { phone, message: msg });
      if (res && res.ok) _setModalResult('ok', 'Mensagem enviada para a fila — chega em instantes.');
      else _setModalResult('error', (res && (res.detail || res.error)) || 'Erro ao enviar mensagem.');
    });

    // Modal — enviar arquivo
    const _btnEnvArq = document.getElementById('btnEnviarArquivo');
    if (_btnEnvArq) _btnEnvArq.addEventListener('click', async () => {
      const phone     = '55' + document.getElementById('testePhoneArq').value.trim().replace(/\D/g, '');
      const caption   = document.getElementById('testeCaption').value.trim();
      const fileInput = document.getElementById('testeFile');
      if (phone.length < 12 || !fileInput.files.length) {
        _setModalResult('error', 'Preencha o número (DDD + número) e selecione um arquivo.');
        return;
      }
      const form = new FormData();
      form.append('phone', phone);
      form.append('caption', caption);
      form.append('file', fileInput.files[0]);
      _setModalResult('ok', 'Enviando…');
      const r = await fetch(`/api/sessoes/${_modalSessaoId}/send-file`, { method: 'POST', body: form });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) _setModalResult('ok', 'Arquivo enviado com sucesso!');
      else _setModalResult('error', d.detail || d.error || 'Erro ao enviar arquivo.');
    });
  }

  // ── Ponto de entrada ─────────────────────────────────────────────────────────

  function init() {
    if (!_initialized) {
      _registerEvents();
      _initialized = true;
    }
    loadSessoes();
    _iniciarRefreshWA();
  }

  function stop() {
    _pararRefreshWA();
  }

  return { init, stop, toggleQR, deleteSessao, abrirModalTeste, fecharModalTeste };
})();


// Testa comunicação com agente (botão "Testar comunicação" na criação de sessão modo Agente)
window.testarAgent = async function () {
  const btn = document.getElementById('btnTestarAgent');
  const out = document.getElementById('testarAgentStatus');
  if (!out) return;
  out.style.color = 'var(--text-3)';
  out.textContent = 'Testando…';
  if (btn) btn.disabled = true;
  try {
    const r = await fetch('/api/agents/ping');
    const d = await r.json();
    if (!d.connected) {
      out.style.color = 'var(--red)';
      out.textContent = '❌ ' + (d.error || 'Agent não conectado');
      return;
    }
    if (d.error) {
      out.style.color = 'var(--amber)';
      out.textContent = `⚠️ v${d.version} conectado, mas comando falhou: ${d.error}`;
      return;
    }
    out.style.color = 'var(--primary-deep)';
    const lat = d.latency_ms != null ? `${d.latency_ms}ms` : '?';
    const last = d.last_seen_sec != null ? `${d.last_seen_sec}s atrás` : '?';
    const stateLabel = {
      open: 'WhatsApp já conectado',
      connecting: 'aguardando QR',
      loading: 'WhatsApp Web carregando',
      close: 'desconectado',
    }[d.state] || d.state || '?';
    out.textContent = `✅ Agent v${d.version} • ${lat} • último heartbeat ${last} • ${stateLabel}`;
  } catch (e) {
    out.style.color = 'var(--red)';
    out.textContent = '❌ Erro de rede: ' + (e.message || e);
  } finally {
    if (btn) btn.disabled = false;
  }
};

// ── Globais para onclick inline no HTML gerado dinamicamente ─────────────────
window.toggleQR        = (id)         => whatsappModule.toggleQR(id);
window.deleteSessao    = (id)         => whatsappModule.deleteSessao(id);
window.abrirModalTeste = (id, nome)   => whatsappModule.abrirModalTeste(id, nome);
window.fecharModalTeste = ()          => whatsappModule.fecharModalTeste();
window.fecharTesteEnvio = ()          => whatsappModule.fecharModalTeste();
