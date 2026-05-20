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
      if (!res.ok) return null;
      const d = await res.json();
      return d.qr || null;
    } catch { return null; }
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
      if (qr) _setQrImg(id, qr);
    }, 4000);
  }

  // ── Render de sessão ───────────────────────────────────────────────────────

  function _renderSessao(s) {
    const label = STATUS_LABEL[s.status] || s.status;
    const chip  = STATUS_CHIP[s.status] || 'chip-gray';
    return `
      <div class="sessao-card status-${s.status}" id="card-${s.id}">
        <div class="sessao-header">
          <span class="sessao-nome">${s.nome}</span>
          <div class="sessao-actions">
            <span class="chip ${chip}">${label}</span>
            ${s.status !== 'connected'
              ? `<button class="btn btn-ghost btn-sm" onclick="toggleQR('${s.id}')">Mostrar QR</button>`
              : `<button class="btn btn-ghost btn-sm" onclick="toggleQR('${s.id}')">Ver info</button>
                 <button class="btn btn-primary btn-sm" onclick="abrirModalTeste('${s.id}','${s.nome.replace(/'/g,"\\'")}')">Testar Envio</button>`}
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
          ${s.phone ? `<div class="sessao-phone-badge">📱 ${_formatPhone(s.phone)}</div>` : '<span style="color:var(--text-mid);font-size:.78rem">Número não identificado</span>'}
        </div>` : `
        <div class="qr-area" id="qrarea-${s.id}">
          <div class="phone-mockup">
            <div class="phone-notch">
              <div class="phone-camera"></div>
              <div class="phone-speaker"></div>
            </div>
            <div class="phone-screen" id="qrbox-${s.id}">
              <div class="phone-screen-header">
                <svg class="phone-wa-icon" viewBox="0 0 24 24" fill="#fff"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51a12.8 12.8 0 0 0-.57-.01c-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0 0 12.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 0 0 5.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 0 0-3.48-8.413z"/></svg>
                <span>WhatsApp Web</span>
              </div>
              <div class="phone-qr-wrap" id="qrimg-${s.id}">
                <div style="display:flex;flex-direction:column;align-items:center;gap:8px;padding:16px 0">
                  <div class="qr-spinner"></div>
                  <span style="font-size:.62rem;color:#888">Aguardando QR…</span>
                </div>
              </div>
              <div class="phone-qr-label">Aponte a câmera para<br>escanear o código</div>
            </div>
            <div class="phone-home"></div>
          </div>
          <div class="qr-instrucoes">
            <strong>Como conectar:</strong>
            <ol>
              <li>Abra o <strong>WhatsApp</strong> no celular</li>
              <li>Toque em <strong>⋮ Menu</strong></li>
              <li>Vá em <strong>Aparelhos conectados</strong></li>
              <li>Toque em <strong>Conectar aparelho</strong></li>
              <li>Aponte a câmera para o QR ao lado</li>
            </ol>
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
      cont.innerHTML = `<div style="text-align:center;padding:2rem 1rem;background:linear-gradient(135deg,#f0f7eb,#e8f5e0);border:1px dashed var(--accent-mid);border-radius:10px;margin-bottom:1rem">
        <div style="width:52px;height:52px;background:var(--accent-soft);border-radius:14px;display:flex;align-items:center;justify-content:center;margin:0 auto .75rem;border:1px solid var(--accent-mid)">
          <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#2d6a0a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
        </div>
        <div style="font-weight:600;color:var(--accent);margin-bottom:.25rem">Nenhum número conectado</div>
        <div style="color:var(--text-mid);font-size:.84rem">Digite um nome abaixo e clique em <strong style="color:var(--accent)">Adicionar</strong> para começar.</div>
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
    const ok = await (typeof window.showConfirm === 'function'
      ? window.showConfirm({
          title: 'Remover sessão WhatsApp?',
          body: 'A sessão será desconectada e os dados do QR serão apagados. Você precisará escanear um novo código para reconectar.',
          okLabel: 'Sim, remover',
          type: 'danger',
          icon: '📱',
        })
      : Promise.resolve(window.confirm('Remover sessão WhatsApp?\nA sessão será desconectada e os dados do QR serão apagados.')));
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

  function abrirModalTeste(sessaoId, sessaoNome) {
    _modalSessaoId = sessaoId;
    document.getElementById('modalTesteTitulo').textContent = `Testar Envio — ${sessaoNome}`;
    document.getElementById('modalTesteResult').className = 'modal-result';
    document.getElementById('modalTesteResult').textContent = '';
    document.getElementById('modalOverlay').classList.add('open');
    _switchTab('texto');
  }

  function fecharModalTeste() {
    document.getElementById('modalOverlay').classList.remove('open');
    _modalSessaoId = null;
  }

  // ── Registro de eventos (executado uma única vez) ─────────────────────────

  function _registerEvents() {
    // Adicionar sessão
    document.getElementById('btnAddSessao').addEventListener('click', async () => {
      const nome = document.getElementById('inputNovaSessao').value.trim();
      if (!nome) { _alert('alertWA', 'Digite um nome para a sessão.', 'error'); return; }
      const btn = document.getElementById('btnAddSessao');
      btn.disabled = true;
      btn.textContent = 'Criando…';
      try {
        const res = await _post('/api/sessoes', { nome });
        if (res && (res.ok || res.id)) {
          document.getElementById('inputNovaSessao').value = '';
          _alert('alertWA', `Sessão "${nome}" criada! Escaneie o QR Code abaixo.`);
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

    // Modal — enviar texto
    document.getElementById('btnEnviarTexto').addEventListener('click', async () => {
      const phone = '55' + document.getElementById('testePhone').value.trim().replace(/\D/g, '');
      const msg   = document.getElementById('testeMsg').value.trim();
      if (phone.length < 12 || !msg) { _setModalResult('error', 'Preencha o número (DDD + número) e a mensagem.'); return; }
      const res = await _post(`/api/sessoes/${_modalSessaoId}/send-text`, { phone, message: msg });
      if (res && res.ok) _setModalResult('ok', 'Mensagem enviada com sucesso!');
      else _setModalResult('error', (res && (res.detail || res.error)) || 'Erro ao enviar mensagem.');
    });

    // Modal — enviar arquivo
    document.getElementById('btnEnviarArquivo').addEventListener('click', async () => {
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

// ── Globais para onclick inline no HTML gerado dinamicamente ─────────────────
window.toggleQR        = (id)         => whatsappModule.toggleQR(id);
window.deleteSessao    = (id)         => whatsappModule.deleteSessao(id);
window.abrirModalTeste = (id, nome)   => whatsappModule.abrirModalTeste(id, nome);
window.fecharModalTeste = ()          => whatsappModule.fecharModalTeste();
