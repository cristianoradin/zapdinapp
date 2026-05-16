  // ── Nav ──────────────────────────────────────────────────────────────────────
  const pages = {
    dashboard: 'Gestão de Envios',
    mensagem: 'Configurar Mensagem',
    'config-envio': 'Configurações de Envio',
    whatsapp: 'Conectar WhatsApp',
    teste: 'Teste de Envio',
    token: 'Token API',
    arquivo: 'Envio de Arquivo',
    docs: 'Documentações',
    telegram: 'Telegram',
    'dm-dashboard': 'Campanhas',
    'dm-contatos': 'Contatos',
    'dm-campanha': 'Enviar Campanhas',
    'dm-historico': 'Gerenciar Campanhas',
    'dm-enviadas': 'Campanhas Enviadas',
    'avaliacoes': 'Gestão de Avaliação',
  };
  function _setTopbarPage(p) {
    document.getElementById('pageTitle').textContent = pages[p] || p;
    const el = document.getElementById('pageIcon');
    if (el) el.style.display = 'none';
  }

  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      const p = item.dataset.page;
      document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
      document.querySelectorAll('.page').forEach(pg => pg.classList.remove('active'));
      item.classList.add('active');
      document.getElementById('page-' + p).classList.add('active');
      _setTopbarPage(p);
      onPageLoad(p);
    });
  });

  // ── Topbar status pill ────────────────────────────────────────────────────────
  async function _updateTopbarStatus() {
    try {
      const res = await fetch('/api/sessoes/live-status');
      if (!res.ok) return;
      const sessoes = await res.json();
      const connected = sessoes.filter(s => s.status === 'connected').length;
      const pill = document.getElementById('topbarStatusPill');
      const txt  = document.getElementById('topbarStatusText');
      const banner = document.getElementById('waBanner');
      if (connected > 0) {
        pill.classList.add('active');
        txt.textContent = connected === 1 ? '1 número ativo' : `${connected} números ativos`;
        if (banner) banner.classList.remove('visible');
      } else {
        pill.classList.remove('active');
        txt.textContent = 'Sem conexão WA';
        if (banner) banner.classList.add('visible');
      }
    } catch { /* silencioso */ }
  }

  // ── Auth check + permissões de menus ─────────────────────────────────────────
  async function checkAuth() {
    try {
      const res = await fetch('/api/auth/me');
      if (res.status === 401) { window.location.href = '/login'; return; }
      const data = await res.json();

      // Usuário logado
      const name = data.username || '?';
      document.getElementById('userBadge').textContent = name;
      const av = document.getElementById('userAvatar');
      if (av) {
        if (data.avatar_url) {
          av.innerHTML = `<img src="${data.avatar_url}" alt="${name}"
            style="width:100%;height:100%;object-fit:cover;border-radius:50%">`;
        } else {
          av.textContent = name.charAt(0).toUpperCase();
        }
      }

      // Nome e CNPJ da empresa logada
      const clientName = data.empresa || data.client_name || '';
      const clientCnpj = data.cnpj || '';
      if (clientName) {
        const chip = document.getElementById('topbarClient');
        const chipName = document.getElementById('topbarClientName');
        const chipCnpj = document.getElementById('topbarClientCnpj');
        if (chip && chipName) {
          chipName.textContent = clientName;
          if (chipCnpj && clientCnpj) {
            const d = clientCnpj.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5');
            chipCnpj.textContent = d;
          }
          chip.style.display = 'flex';
        }
        const sbBadge = document.getElementById('sidebarClientBadge');
        const sbName  = document.getElementById('sidebarClientName');
        if (sbBadge && sbName) { sbName.textContent = clientName; sbBadge.style.display = 'flex'; }
      }

      // ── Permissões de menus ──────────────────────────────────────────────────
      // data.menus: null = todos permitidos; array = só esses menus visíveis
      const allowedMenus = Array.isArray(data.menus) ? data.menus : null;
      if (allowedMenus !== null) {
        let firstAllowed = null;
        document.querySelectorAll('.nav-item[data-page]').forEach(item => {
          const page = item.dataset.page;
          if (allowedMenus.includes(page)) {
            item.style.display = '';
            if (!firstAllowed) firstAllowed = page;
          } else {
            item.style.display = 'none';
            // Se a página atual for bloqueada, navegar para a primeira permitida
            if (item.classList.contains('active') && firstAllowed) {
              document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
              document.querySelectorAll('.page').forEach(pg => pg.classList.remove('active'));
              const targetItem = document.querySelector(`.nav-item[data-page="${firstAllowed}"]`);
              if (targetItem) targetItem.classList.add('active');
              const targetPage = document.getElementById('page-' + firstAllowed);
              if (targetPage) targetPage.classList.add('active');
              _setTopbarPage(firstAllowed);
              onPageLoad(firstAllowed);
            }
          }
        });
        // Ocultar section labels da sidebar que ficaram sem itens visíveis
        document.querySelectorAll('.sidebar-section').forEach(section => {
          let next = section.nextElementSibling;
          let hasVisible = false;
          while (next && !next.classList.contains('sidebar-section')) {
            if (next.classList.contains('nav-item') && next.style.display !== 'none') hasVisible = true;
            next = next.nextElementSibling;
          }
          section.style.display = hasVisible ? '' : 'none';
        });
      }
    } catch { window.location.href = '/login'; }
  }

  document.getElementById('btnLogout').addEventListener('click', async () => {
    await fetch('/api/logout', { method: 'POST' });
    window.location.href = '/login';
  });

  // ── Confirm dialog (substitui confirm() nativo) ───────────────────────────────
  // Uso: const ok = await showConfirm({ title, body, okLabel, type })
  // type: 'danger' (vermelho) | 'warning' (âmbar) | 'info' (verde)
  (function _initConfirm() {
    const overlay    = document.getElementById('confirmOverlay');
    const iconWrap   = document.getElementById('confirmIconWrap');
    const iconEl     = document.getElementById('confirmIcon');
    const titleEl    = document.getElementById('confirmTitle');
    const bodyEl     = document.getElementById('confirmBody');
    const btnCancel  = document.getElementById('confirmBtnCancel');
    const btnOk      = document.getElementById('confirmBtnOk');

    let _resolve = null;

    const _icons = { danger: '🗑️', warning: '⚠️', info: 'ℹ️' };

    function _close(result) {
      overlay.classList.remove('open');
      if (_resolve) { _resolve(result); _resolve = null; }
    }

    btnCancel.addEventListener('click', () => _close(false));
    btnOk.addEventListener('click',     () => _close(true));
    overlay.addEventListener('click', e => { if (e.target === overlay) _close(false); });
    document.addEventListener('keydown', e => {
      if (!overlay.classList.contains('open')) return;
      if (e.key === 'Escape') _close(false);
      if (e.key === 'Enter')  { e.preventDefault(); _close(true); }
    });

    window.showConfirm = function({ title = 'Confirmar', body = '', okLabel = 'Confirmar', cancelLabel = 'Cancelar', type = 'danger', icon = null } = {}) {
      titleEl.textContent    = title;
      bodyEl.textContent     = body;
      btnOk.textContent      = okLabel;
      btnCancel.textContent  = cancelLabel;
      iconEl.textContent     = icon || _icons[type] || '❓';
      iconWrap.className     = 'confirm-icon-wrap ' + type;
      btnOk.className        = 'confirm-btn confirm-btn-ok ' + type;
      overlay.classList.add('open');
      setTimeout(() => btnCancel.focus(), 50);
      return new Promise(res => { _resolve = res; });
    };
  })();

  // ── API helpers ───────────────────────────────────────────────────────────────
  async function api(method, url, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(url, opts);
    if (res.status === 401) { window.location.href = '/login'; return { ok: false }; }
    try {
      const data = await res.json();
      return { ...data, _status: res.status, ok: res.ok };
    } catch {
      return { ok: res.ok, _status: res.status };
    }
  }

  function showAlert(id, msg, type = 'success') {
    const el = document.getElementById(id);
    el.textContent = msg;
    el.className = `alert alert-${type}`;
    el.style.display = 'block';
    setTimeout(() => el.style.display = 'none', 4000);
  }

  // ── Dashboard ────────────────────────────────────────────────────────────────
  async function loadStats() {
    try {
      const res = await fetch('/api/stats');
      if (res.status === 401) { window.location.href = '/login'; return; }
      const d = await res.json();
      document.getElementById('statHoje').textContent = d.hoje ?? 0;
      document.getElementById('statEnviadas').textContent = d.enviadas ?? 0;
      document.getElementById('statFalhas').textContent = d.falhas ?? 0;
      document.getElementById('statSessoes').textContent = d.sessoes_ativas ?? 0;

      // Fix 12: Queue health check — alerta se fila está parada
      try {
        const qh = await fetch('/api/stats/queue-health');
        if (qh.ok) {
          const qd = await qh.json();
          const banner = document.getElementById('queueStuckBanner');
          if (qd.stuck_alert && qd.total_queued > 0) {
            document.getElementById('queueStuckMsg').textContent =
              `Há ${qd.total_queued} mensagem(ns) aguardando há ${qd.stuck_minutes} minutos. Verifique o WhatsApp${!qd.wa_connected ? ' (desconectado)' : ''} e o worker.`;
            banner.style.display = 'flex';
          } else if (!qd.stuck_alert) {
            banner.style.display = 'none';
          }
        }
      } catch(e) { /* queue-health é best-effort */ }
      const tbody = document.getElementById('tbodyRecentes');
      if (!d.recentes || d.recentes.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;padding:3rem 1rem">
          <div style="width:48px;height:48px;background:var(--accent-soft);border-radius:12px;display:flex;align-items:center;justify-content:center;margin:0 auto .75rem">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </div>
          <div style="color:var(--text);font-size:.9rem;font-weight:600;margin-bottom:.3rem">Nenhuma mensagem enviada ainda</div>
          <div style="color:var(--text-mid);font-size:.8rem;margin-bottom:1rem">Configure e envie sua primeira mensagem para começar.</div>
          <button class="btn btn-primary btn-sm" onclick="showPage('mensagem')" style="display:inline-flex;align-items:center;gap:.4rem">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            Configurar mensagem
          </button>
        </td></tr>`;
        return;
      }
      tbody.innerHTML = d.recentes.map(r => `
        <tr>
          <td>${r.destinatario}</td>
          <td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.mensagem || '—'}</td>
          <td><span class="chip ${r.status === 'sent' ? 'chip-green' : r.status === 'failed' ? 'chip-red' : 'chip-yellow'}">${r.status}</span></td>
          <td style="color:var(--text-mid);font-size:.8rem">${r.created_at}</td>
        </tr>`).join('');
    } catch(e) { console.error(e); }
  }

  // ── Mensagem ─────────────────────────────────────────────────────────────────
  let _clientName = '';

  async function loadMensagem() {
    const res = await fetch('/api/config');
    if (!res.ok) return;
    const cfg = await res.json();

    // Nome da empresa da licença (bloqueado)
    _clientName = cfg.client_name || '';
    document.getElementById('clientNameDisplay').textContent = _clientName || '(não configurado)';

    // Template salvo — remove cabeçalho fixo se estava embutido (retrocompatibilidade)
    let tmpl = cfg.mensagem_padrao || '';
    const prefixo = '🏪 *' + _clientName + '*\n\n';
    if (_clientName && tmpl.startsWith(prefixo)) {
      tmpl = tmpl.slice(prefixo.length);
    }
    document.getElementById('inputMensagem').value = tmpl;
    updatePreview(tmpl);
    atualizarPreviewTeste();
  }

  function updatePreview(tmpl) {
    const produtosEx = '• Gasolina Comum (x30) — R$ 5,99\n• Óleo Motor 5W30 (x1) — R$ 42,00';
    const header = _clientName ? '🏪 *' + _clientName + '*\n\n' : '';
    const full = header + tmpl;
    const preview = full
      .replace(/{nome}/g, 'João Silva')
      .replace(/{telefone}/g, '5511999990000')
      .replace(/{data}/g, '14/05/2026')
      .replace(/{produtos}/g, produtosEx)
      .replace(/{valor_total_itens}/g, 'R$ 221,70')
      .replace(/{valor_total}/g, 'R$ 221,70')
      .replace(/{valor}/g, 'R$ 221,70');
    document.getElementById('previewMensagem').textContent = preview || 'Digite o template ao lado para ver o preview aqui…';
  }

  document.getElementById('inputMensagem').addEventListener('input', e => { updatePreview(e.target.value); atualizarPreviewTeste(); });

  // Clique nas var-tags: insere a variável na posição do cursor no textarea
  document.querySelectorAll('.var-tag[data-var]').forEach(tag => {
    tag.addEventListener('click', () => {
      const ta = document.getElementById('inputMensagem');
      const v  = tag.dataset.var;
      const start = ta.selectionStart;
      const end   = ta.selectionEnd;
      ta.value = ta.value.slice(0, start) + v + ta.value.slice(end);
      ta.selectionStart = ta.selectionEnd = start + v.length;
      ta.focus();
      updatePreview(ta.value);
    });
  });

  // ── Avaliação config ─────────────────────────────────────────────────────────
  async function loadAvaliacaoCfg() {
    try {
      const res = await fetch('/api/config');
      const cfg = res.ok ? await res.json() : {};
      const ativo = cfg.avaliacao_ativa === '1' || cfg.avaliacao_ativa === true;
      document.getElementById('toggleAvaliacao').checked = ativo;
      document.getElementById('avaliacaoPreviewWrap').style.display = ativo ? '' : 'none';
      // Sincroniza o toggle do teste com a config de avaliação
      const cbTeste = document.getElementById('testeMsgIncluirAval');
      if (cbTeste) { cbTeste.checked = ativo; atualizarPreviewTeste(); }
      if (ativo) {
        const iframe = document.getElementById('avaliacaoPreviewIframe');
        const empresaId = cfg.empresa_id || '';
        iframe.src = '/avaliacao/preview' + (empresaId ? '?empresa_id=' + empresaId : '');
      }
    } catch(e) {}
  }

  async function salvarAvaliacaoCfg() {
    const ativo = document.getElementById('toggleAvaliacao').checked;
    document.getElementById('avaliacaoPreviewWrap').style.display = ativo ? '' : 'none';
    await api('POST', '/api/config', { avaliacao_ativa: ativo ? '1' : '0' });
    if (ativo) {
      const res = await fetch('/api/config');
      const cfg = res.ok ? await res.json() : {};
      const empresaId = cfg.empresa_id || '';
      document.getElementById('avaliacaoPreviewIframe').src = '/avaliacao/preview' + (empresaId ? '?empresa_id=' + empresaId : '');
    }
  }

  document.getElementById('btnSalvarMensagem').addEventListener('click', async () => {
    const corpo = document.getElementById('inputMensagem').value;
    // Sempre salva com o cabeçalho fixo embutido no início
    const header = _clientName ? '🏪 *' + _clientName + '*\n\n' : '';
    const val = header + corpo;
    const res = await api('POST', '/api/config', { mensagem_padrao: val });
    if (res.ok) showAlert('alertMensagem', 'Mensagem salva com sucesso!');
    else showAlert('alertMensagem', 'Erro ao salvar', 'error');
  });

  // ── WhatsApp Sessions ─────────────────────────────────────────────────────────
  const STATUS_LABEL = {
    connected: 'Conectado', qr: 'Aguardando QR',
    connecting: 'Conectando…', disconnected: 'Desconectado', error: 'Erro',
  };
  const STATUS_CHIP = {
    connected: 'chip-green', qr: 'chip-yellow',
    connecting: 'chip-yellow', disconnected: 'chip-gray', error: 'chip-red',
  };

  let _waRefresh = null;
  const _qrPollers = {};   // sessao_id → intervalId

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

  function _formatPhone(phone) {
    if (!phone) return '';
    const d = phone.replace(/\D/g, '');
    // Número brasileiro: 55 + DDD (2 dígitos) + número (8 ou 9 dígitos)
    if (d.startsWith('55') && d.length >= 12) {
      const ddd = d.slice(2, 4);
      const num = d.slice(4);
      if (num.length === 9) return `+55 (${ddd}) ${num.slice(0,5)}-${num.slice(5)}`;
      if (num.length === 8) return `+55 (${ddd}) ${num.slice(0,4)}-${num.slice(4)}`;
    }
    return phone;
  }

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

  async function loadSessoes() {
    const res = await fetch('/api/sessoes/live-status');
    if (!res.ok) return;
    const sessoes = await res.json();
    const cont = document.getElementById('listaSessoes');
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
    // Salva quais QR-areas estavam abertas ANTES de re-renderizar
    const abertos = new Set(
      Array.from(document.querySelectorAll('.qr-area.visible'))
           .map(el => el.id.replace('qrarea-', ''))
    );
    Object.keys(_qrPollers).forEach(_stopQrPoller);
    cont.innerHTML = sessoes.map(_renderSessao).join('');
    // Reabre QRs que estavam visíveis + abre automaticamente sessões em estado qr
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

  async function toggleQR(id) {
    const area = document.getElementById('qrarea-' + id);
    if (!area) return;
    if (area.classList.contains('visible')) {
      area.classList.remove('visible');
      _stopQrPoller(id);
    } else {
      area.classList.add('visible');
      _startQrPoller(id);
      // Carrega imediatamente
      const qr = await _fetchQR(id);
      if (qr) _setQrImg(id, qr);
    }
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

  // Auto-refresh do status das sessões — 2s se há sessão pendente, 5s se tudo conectado
  let _waRefreshInterval = 5000;
  async function _refreshWAAdaptive() {
    await loadSessoes();
    const cont = document.getElementById('listaSessoes');
    const hasPending = cont && cont.querySelector('.chip-yellow, .chip-red, .chip-gray');
    const next = hasPending ? 2000 : 5000;
    if (next !== _waRefreshInterval) {
      _waRefreshInterval = next;
      _iniciarRefreshWA();  // reinicia com novo intervalo
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

  document.getElementById('btnAddSessao').addEventListener('click', async () => {
    const nome = document.getElementById('inputNovaSessao').value.trim();
    if (!nome) {
      showAlert('alertWA', 'Digite um nome para a sessão.', 'error');
      return;
    }
    const btn = document.getElementById('btnAddSessao');
    btn.disabled = true;
    btn.textContent = 'Criando…';
    try {
      const res = await api('POST', '/api/sessoes', { nome });
      if (res.ok) {
        document.getElementById('inputNovaSessao').value = '';
        showAlert('alertWA', `Sessão "${nome}" criada! Escaneie o QR Code abaixo.`);
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
        showAlert('alertWA', res.detail || 'Erro ao criar sessão. Tente novamente.', 'error');
      }
    } catch (e) {
      showAlert('alertWA', 'Erro de conexão ao criar sessão.', 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = '+ Adicionar';
    }
  });

  async function deleteSessao(id) {
    const ok = await showConfirm({
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

  // ── Token API ─────────────────────────────────────────────────────────────────
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

  async function revogarPdvToken(id) {
    const ok = await showConfirm({
      title: 'Revogar token PDV?',
      body: 'O PDV que usa este token ficará desconectado do App.',
      okLabel: 'Revogar', type: 'warning', icon: '⚠',
    });
    if (!ok) return;
    await api('DELETE', `/api/pdv/tokens/${id}`);
    loadPdvTokens();
  }

  function copiarPdvToken() {
    const val = document.getElementById('pdvTokenValor').textContent;
    if (!val) return;
    navigator.clipboard.writeText(val).then(() => {
      showAlert('alertPdvToken', 'Token copiado!');
    });
  }

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

  // ── Token ERP ────────────────────────────────────────────────────────────────

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

  document.getElementById('btnRefreshArquivos').addEventListener('click', loadArquivos);

  // ── Arquivos ──────────────────────────────────────────────────────────────────
  let _arquivosRefreshTimer = null;

  function _arquivoStatusChip(a) {
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

  async function loadArquivos() {
    const res = await fetch('/api/arquivos');
    if (!res.ok) return;
    const arqs = await res.json();
    const tbody = document.getElementById('tbodyArquivos');

    // Populate mini-stat counters
    const counts = { queued: 0, pending: 0, sent: 0, delivered: 0, read: 0, failed: 0 };
    arqs.forEach(a => { if (counts[a.status] !== undefined) counts[a.status]++; });
    const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setEl('arqStNaFila',  counts.queued + counts.pending);
    setEl('arqStEnviado', counts.sent);
    setEl('arqStEntregue', counts.delivered);
    setEl('arqStVisual',  counts.read);
    setEl('arqStFalhou',  counts.failed);

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

      // File type icon
      const ext = (a.nome_original || '').split('.').pop().toLowerCase();
      const _svgPDF = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15h6M9 11h3"/></svg>`;
      const _svgIMG = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`;
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
        <td>
          <span style="font-size:.8rem;font-family:monospace;background:var(--surface2);padding:.2rem .5rem;border-radius:5px;color:var(--text-mid)">${a.destinatario || '—'}</span>
        </td>
        <td>${dtLabel}</td>
        <td>
          ${_arquivoStatusChip(a)}
          ${detail ? `<div style="font-size:.68rem;margin-top:.3rem;line-height:1.6">${detail}</div>` : ''}
        </td>
      </tr>`;
    }).join('');

    const hasPending = arqs.some(a => ['queued','pending','sent','delivered'].includes(a.status));
    clearTimeout(_arquivosRefreshTimer);
    if (hasPending) _arquivosRefreshTimer = setTimeout(loadArquivos, 15_000);
  }

  // ── Page loader ───────────────────────────────────────────────────────────────
  function onPageLoad(page) {
    if (page !== 'whatsapp') _pararRefreshWA();
    if (page !== 'arquivo') { clearTimeout(_arquivosRefreshTimer); _arquivosRefreshTimer = null; }
    if (page !== 'teste') _pararTestePoll();
    if (page === 'dashboard') loadStats();
    else if (page === 'mensagem') { loadMensagem(); loadAvaliacaoCfg(); loadTesteMensagem(); }
    else if (page === 'config-envio') carregarConfigEnvio();
    else if (page === 'whatsapp') { loadSessoes(); _iniciarRefreshWA(); }
    else if (page === 'token') { loadToken(); loadPdvTokens(); }
    else if (page === 'arquivo') loadArquivos();
    else if (page === 'teste') loadTeste();
    else if (page === 'telegram') loadTelegram();
    else if (page === 'dm-dashboard') loadDashboardCampanhas();
    else if (page === 'dm-contatos') loadContatos();
    else if (page === 'dm-campanha') initNovaCampanha();
    else if (page === 'dm-historico') { loadCampanhas(); loadWorkerStatus(); }
    else if (page === 'dm-enviadas') loadCampanhasEnviadas();
    else if (page === 'avaliacoes') loadAvaliacoes();
  }

  // ── Telegram ──────────────────────────────────────────────────────────────────
  async function loadTelegram() {
    const res = await fetch('/api/telegram/config');
    if (!res.ok) return;
    const d = await res.json();
    document.getElementById('tgBotToken').value = d.bot_token || '';
    document.getElementById('tgChatId').value   = d.chat_id   || '';
    _setTgStatus(d.configured ? 'ok' : null, d.configured ? 'Telegram configurado e ativo' : '');
  }

  function _setTgStatus(type, msg) {
    const el = document.getElementById('tgStatus');
    if (!type) { el.style.display = 'none'; return; }
    el.style.display = 'block';
    const s = getComputedStyle(document.documentElement);
    el.style.background = type === 'ok' ? s.getPropertyValue('--accent-soft').trim() : s.getPropertyValue('--red-soft').trim();
    el.style.color      = type === 'ok' ? s.getPropertyValue('--accent').trim()      : s.getPropertyValue('--red').trim();
    el.style.border     = type === 'ok' ? '1px solid ' + s.getPropertyValue('--accent-mid').trim() : '1px solid #fecaca';
    el.textContent = msg;
  }

  document.getElementById('btnSalvarTelegram').addEventListener('click', async () => {
    const token = document.getElementById('tgBotToken').value.trim();
    const chatId = document.getElementById('tgChatId').value.trim();
    if (!token || !chatId) { showAlert('alertTelegram', 'Preencha o Bot Token e o Chat ID.', 'error'); return; }
    const res = await api('POST', '/api/telegram/config', { bot_token: token, chat_id: chatId });
    if (res.ok) { showAlert('alertTelegram', 'Configuração salva!'); _setTgStatus('ok', 'Telegram configurado e ativo'); }
    else showAlert('alertTelegram', 'Erro ao salvar', 'error');
  });

  document.getElementById('btnTestarTelegram').addEventListener('click', async () => {
    _setTgStatus(null, '');
    const res = await api('POST', '/api/telegram/test');
    if (res.ok) _setTgStatus('ok', '✅ Mensagem de teste enviada com sucesso!');
    else _setTgStatus('err', '❌ ' + (res.detail || 'Falha ao enviar. Verifique o token e chat_id.'));
  });

  document.getElementById('btnRelatorioParcial').addEventListener('click', async () => {
    const res = await api('POST', '/api/telegram/report-now');
    if (res.ok) _setTgStatus('ok', 'Relatório enviado com sucesso!');
    else _setTgStatus('err', '❌ ' + (res.detail || 'Erro ao enviar relatório.'));
  });

  // ── Init ──────────────────────────────────────────────────────────────────────
  checkAuth().then(() => {
    loadStats();
    _updateTopbarStatus();
    setInterval(loadStats, 30_000);
    setInterval(_updateTopbarStatus, 30_000);
  });

  // ── Modal Teste de Envio ──────────────────────────────────────────────────────
  let _modalSessaoId = null;

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

  function _switchTab(tab) {
    document.querySelectorAll('.modal-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('.modal-panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + tab));
  }

  document.querySelectorAll('.modal-tab').forEach(b => b.addEventListener('click', () => _switchTab(b.dataset.tab)));
  document.getElementById('modalClosebtn').addEventListener('click', fecharModalTeste);
  document.getElementById('modalOverlay').addEventListener('click', e => { if (e.target === e.currentTarget) fecharModalTeste(); });

  document.getElementById('btnEnviarTexto').addEventListener('click', async () => {
    const phone = '55' + document.getElementById('testePhone').value.trim().replace(/\D/g, '');
    const msg   = document.getElementById('testeMsg').value.trim();
    if (phone.length < 12 || !msg) { _setModalResult('error', 'Preencha o número (DDD + número) e a mensagem.'); return; }
    const res = await api('POST', `/api/sessoes/${_modalSessaoId}/send-text`, { phone, message: msg });
    if (res.ok) _setModalResult('ok', 'Mensagem enviada com sucesso!');
    else _setModalResult('error', res.detail || res.error || 'Erro ao enviar mensagem.');
  });

  document.getElementById('btnEnviarArquivo').addEventListener('click', async () => {
    const phone   = '55' + document.getElementById('testePhoneArq').value.trim().replace(/\D/g, '');
    const caption = document.getElementById('testeCaption').value.trim();
    const fileInput = document.getElementById('testeFile');
    if (phone.length < 12 || !fileInput.files.length) { _setModalResult('error', 'Preencha o número (DDD + número) e selecione um arquivo.'); return; }

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

  function _setModalResult(type, msg) {
    const el = document.getElementById('modalTesteResult');
    el.className = 'modal-result ' + (type === 'ok' ? 'ok' : 'err');
    el.textContent = msg;
  }

  // ── Teste de Envio (página) ───────────────────────────────────────────────────
  let _testePoller = null;

  function _pararTestePoll() {
    if (_testePoller) { clearInterval(_testePoller); _testePoller = null; }
  }

  function _testeResult(elId, type, msg) {
    const el = document.getElementById(elId);
    el.style.display = 'block';
    el.style.background = type === 'ok' ? 'var(--accent-soft)' : type === 'loading' ? 'var(--surface2)' : 'var(--red-soft)';
    el.style.border = `1px solid ${type === 'ok' ? 'var(--accent-mid)' : type === 'loading' ? 'var(--border)' : '#fecaca'}`;
    el.style.color = type === 'ok' ? 'var(--accent)' : type === 'loading' ? 'var(--text-mid)' : 'var(--red)';
    el.textContent = msg;
  }

  async function _refreshTeste() {
    const res = await fetch('/api/sessoes/live-status');
    if (!res.ok) return;
    const sessoes = await res.json();
    const sel = document.getElementById('testeSelectSessao');
    const alertEl = document.getElementById('testeAlertSessao');
    if (!sel) return; // página pode ter sido trocada
    const connected = sessoes.filter(s => s.status === 'connected');
    const prevId = sel.value;

    if (connected.length === 0) {
      sel.innerHTML = '<option value="">Nenhuma sessão conectada</option>';
      alertEl.style.display = 'block';
      alertEl.style.background = 'var(--red-soft)';
      alertEl.style.border = '1px solid #fecaca';
      alertEl.style.color = 'var(--red)';
      alertEl.textContent = 'Nenhuma sessão WhatsApp conectada. Vá em Conectar WhatsApp para escanear o QR Code.';
    } else {
      sel.innerHTML = connected.map(s =>
        `<option value="${s.id}"${s.id === prevId ? ' selected' : ''}>${s.nome}${s.phone ? ' — ' + s.phone : ''}</option>`
      ).join('');
      alertEl.style.display = 'none';
    }
  }

  async function loadTeste() {
    _pararTestePoll();
    await _refreshTeste();
    _testePoller = setInterval(_refreshTeste, 8000);
  }

  // ── Teste de Envio integrado em Configurar Mensagem ───────────────────────
  let _linkDemoAvaliacao = '';

  async function _carregarLinkDemo() {
    try {
      const r = await fetch('/api/avaliacao/link-demo');
      if (r.ok) { const d = await r.json(); _linkDemoAvaliacao = d.link || ''; }
    } catch(e) {}
  }

  async function _refreshTesteMensagem() {
    const res = await fetch('/api/sessoes/live-status');
    if (!res.ok) return;
    const sessoes = await res.json();
    const sel = document.getElementById('testeMsgSessao');
    const alertEl = document.getElementById('testeMsgAlertSessao');
    if (!sel) return;
    const connected = sessoes.filter(s => s.status === 'connected');
    const prevId = sel.value;
    if (connected.length === 0) {
      sel.innerHTML = '<option value="">Nenhuma sessão conectada</option>';
      alertEl.style.cssText = 'display:block;background:var(--red-soft);border:1px solid #fecaca;color:var(--red)';
      alertEl.textContent = 'Nenhuma sessão WhatsApp conectada. Vá em Conectar WhatsApp para escanear o QR Code.';
    } else {
      sel.innerHTML = connected.map(s =>
        `<option value="${s.id}"${s.id === prevId ? ' selected' : ''}>${s.nome}${s.phone ? ' — ' + s.phone : ''}</option>`
      ).join('');
      alertEl.style.display = 'none';
    }
  }

  function _buildTesteMsg() {
    const produtosEx = '• Gasolina Comum (x30) — R$ 5,99\n• Óleo Motor 5W30 (x1) — R$ 42,00';
    const phoneEx = '55' + (document.getElementById('testeMsgPhone')?.value.replace(/\D/g,'') || '11999998888');
    const header = _clientName ? '🏪 *' + _clientName + '*\n\n' : '';
    const tmpl = document.getElementById('inputMensagem')?.value || '';
    let msg = (header + tmpl)
      .replace(/{nome}/g, 'João Silva')
      .replace(/{telefone}/g, phoneEx)
      .replace(/{data}/g, new Date().toLocaleDateString('pt-BR'))
      .replace(/{produtos}/g, produtosEx)
      .replace(/{valor_total_itens}/g, 'R$ 179,70')
      .replace(/{valor_total}/g, 'R$ 221,70')
      .replace(/{valor}/g, 'R$ 221,70');
    const inclAval = document.getElementById('testeMsgIncluirAval')?.checked;
    if (inclAval) {
      const link = _linkDemoAvaliacao || `${location.origin}/avaliacao?t=DEMO`;
      msg += `\n\n⭐ Avalie nosso atendimento:\n${link}`;
    }
    return msg;
  }

  function atualizarPreviewTeste() {
    const el = document.getElementById('testeMsgPreview');
    if (el) el.textContent = _buildTesteMsg() || 'Configure o template ao lado…';
  }

  async function loadTesteMensagem() {
    await Promise.all([_refreshTesteMensagem(), _carregarLinkDemo()]);
    atualizarPreviewTeste();
  }

  document.getElementById('btnEnviarTesteMensagem').addEventListener('click', async () => {
    const sessaoId = document.getElementById('testeMsgSessao').value;
    const phoneRaw = document.getElementById('testeMsgPhone').value.trim().replace(/\D/g,'');
    const phone = '55' + phoneRaw;
    const resEl = document.getElementById('testeMsgResult');
    const show = (type, msg) => {
      resEl.style.cssText = `display:block;border:1px solid ${type==='ok'?'var(--accent-mid)':type==='loading'?'var(--border)':'#fecaca'};` +
        `background:${type==='ok'?'var(--accent-soft)':type==='loading'?'var(--surface2)':'var(--red-soft)'};` +
        `color:${type==='ok'?'var(--accent)':type==='loading'?'var(--text-mid)':'var(--red)'}`;
      resEl.textContent = msg;
    };
    if (!sessaoId) { show('error','Selecione uma sessão conectada.'); return; }
    if (phone.length < 12) { show('error','Informe o número com DDD (ex: 11999998888).'); return; }
    const message = _buildTesteMsg();
    show('loading','Enviando mensagem de teste…');
    const res = await api('POST', `/api/sessoes/${sessaoId}/send-text`, { phone, message });
    if (res && res.ok) show('ok','✅ Mensagem enviada com sucesso!');
    else show('error','❌ ' + (res?.detail || 'Erro ao enviar mensagem.'));
  });

  document.getElementById('btnTestePgTexto').addEventListener('click', async () => {
    const sessaoId = document.getElementById('testeSelectSessao').value;
    const phone    = '55' + document.getElementById('testePgPhone').value.trim().replace(/\D/g, '');
    const msg      = document.getElementById('testePgMsg').value.trim();
    const resEl    = 'testePgTextoResult';

    if (!sessaoId) { _testeResult(resEl, 'error', 'Selecione uma sessão conectada.'); return; }
    if (phone.length < 12) { _testeResult(resEl, 'error', 'Informe o número com DDD (ex: 11999998888).'); return; }
    if (!msg) { _testeResult(resEl, 'error', 'Digite a mensagem.'); return; }

    _testeResult(resEl, 'loading', 'Enviando mensagem…');
    const res = await api('POST', `/api/sessoes/${sessaoId}/send-text`, { phone, message: msg });
    if (res && res.ok) _testeResult(resEl, 'ok', '✅ Mensagem enviada com sucesso!');
    else _testeResult(resEl, 'error', '❌ ' + (res?.detail || 'Erro ao enviar mensagem.'));
  });

  document.getElementById('btnTestePgArquivo').addEventListener('click', async () => {
    const sessaoId  = document.getElementById('testeSelectSessao').value;
    const phone     = '55' + document.getElementById('testePgPhoneArq').value.trim().replace(/\D/g, '');
    const caption   = document.getElementById('testePgCaption').value.trim();
    const fileInput = document.getElementById('testePgFile');
    const resEl     = 'testePgArqResult';

    if (!sessaoId) { _testeResult(resEl, 'error', 'Selecione uma sessão conectada.'); return; }
    if (phone.length < 12) { _testeResult(resEl, 'error', 'Informe o número com DDD (ex: 11999998888).'); return; }
    if (!fileInput.files.length) { _testeResult(resEl, 'error', 'Selecione um arquivo.'); return; }

    const form = new FormData();
    form.append('phone', phone);
    form.append('caption', caption);
    form.append('file', fileInput.files[0]);

    _testeResult(resEl, 'loading', 'Enviando arquivo…');
    const r = await fetch(`/api/sessoes/${sessaoId}/send-file`, { method: 'POST', body: form });
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.ok) _testeResult(resEl, 'ok', '✅ Arquivo enviado com sucesso!');
    else _testeResult(resEl, 'error', '❌ ' + (d.detail || d.error || 'Erro ao enviar arquivo.'));
  });

  // ── Configurações de Envio ────────────────────────────────────────────────────
  async function carregarConfigEnvio() {
    const res = await fetch('/api/config');
    const cfg = res.ok ? await res.json() : {};
    const toNum = (v, def) => isNaN(parseFloat(v)) ? def : parseFloat(v);
    document.getElementById('waCfgDelayMin').value    = toNum(cfg.wa_delay_min,   5);
    document.getElementById('waCfgDelayMax').value    = toNum(cfg.wa_delay_max,  15);
    document.getElementById('waCfgDailyLimit').value  = toNum(cfg.wa_daily_limit, 0);
    document.getElementById('waCfgHoraInicio').value  = cfg.wa_hora_inicio || '08:00';
    document.getElementById('waCfgHoraFim').value     = cfg.wa_hora_fim    || '18:00';
    document.getElementById('waCfgHoraAtivo').checked = !!(cfg.wa_hora_inicio && cfg.wa_hora_fim);
    document.getElementById('waCfgSpintax').checked   = cfg.wa_spintax !== '0';
    document.getElementById('waCfgAlert').style.display = 'none';
    document.getElementById('spinPreviewBox').classList.remove('visible');
  }

  document.getElementById('btnSalvarWACfg').addEventListener('click', async () => {
    const min    = parseFloat(document.getElementById('waCfgDelayMin').value)  || 5;
    const max    = parseFloat(document.getElementById('waCfgDelayMax').value)  || 15;
    const limit  = parseInt(document.getElementById('waCfgDailyLimit').value)  || 0;
    const inicio = document.getElementById('waCfgHoraInicio').value;
    const fim    = document.getElementById('waCfgHoraFim').value;
    const horaOn = document.getElementById('waCfgHoraAtivo').checked;
    const spintax = document.getElementById('waCfgSpintax').checked ? '1' : '0';

    if (min >= max) {
      _waCfgAlert('error', 'O delay mínimo deve ser menor que o máximo.');
      return;
    }

    const payload = {
      wa_delay_min:   String(min),
      wa_delay_max:   String(max),
      wa_daily_limit: String(limit),
      wa_hora_inicio: horaOn ? inicio : '',
      wa_hora_fim:    horaOn ? fim    : '',
      wa_spintax:     spintax,
    };

    const res = await api('POST', '/api/config', payload);
    if (res && res.ok) {
      _waCfgAlert('ok', '✅ Configurações salvas com sucesso!');
    } else {
      _waCfgAlert('error', 'Erro ao salvar configurações.');
    }
  });

  function _waCfgAlert(type, msg) {
    const el = document.getElementById('waCfgAlert');
    el.style.display = 'block';
    const ok = type === 'ok';
    el.style.background = ok ? 'var(--accent-soft)' : 'var(--red-soft)';
    el.style.border     = ok ? '1px solid var(--accent-mid)' : '1px solid #fecaca';
    el.style.color      = ok ? 'var(--accent)' : 'var(--red)';
    el.textContent = msg;
  }

  // ── Spintax preview (client-side) ────────────────────────────────────────────
  function _processSpintax(text) {
    const pattern = /\{([^{}]+)\}/g;
    let result = text, prev = '';
    for (let i = 0; i < 10 && result !== prev; i++) {
      prev = result;
      result = result.replace(pattern, (_, opts) => {
        const choices = opts.split('|');
        return choices[Math.floor(Math.random() * choices.length)];
      });
    }
    return result;
  }

  function previewSpintax() {
    const input = document.getElementById('spinTestInput').value.trim();
    const box   = document.getElementById('spinPreviewBox');
    if (!input) return;
    box.textContent = _processSpintax(input);
    box.classList.add('visible');
  }

  // ── Documentação ERP ─────────────────────────────────────────────────────────
  async function abrirDocErpBrowser() {
    /**
     * Abre o documento de integração ERP no browser padrão do SO.
     * Funciona dentro do kiosk (pywebview) pois é o servidor que chama os.startfile / open.
     * Após abrir, o usuário usa Ctrl+P → Salvar como PDF no browser nativo.
     */
    try {
      const r = await fetch('/api/docs/abrir-erp');
      const data = await r.json();
      if (!data.ok) {
        alert('Não foi possível abrir o documento: ' + (data.error || 'erro desconhecido'));
      }
    } catch (e) {
      alert('Erro ao abrir o documento: ' + e.message);
    }
  }

  function baixarDocErp() {
    const a = document.createElement('a');
    a.href = '/api/docs/erp';
    a.download = 'ZapDin-Integracao-ERP.html';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function abrirDocPdvBrowser() {
    try {
      const r = await fetch('/api/docs/abrir-pdv');
      const data = await r.json();
      if (!data.ok) alert('Não foi possível abrir o documento: ' + (data.error || 'erro desconhecido'));
    } catch (e) {
      alert('Erro ao abrir o documento: ' + e.message);
    }
  }

  function baixarDocPdv() {
    const a = document.createElement('a');
    a.href = '/api/docs/pdv';
    a.download = 'ZapDin-PDV-Integracao-ERP.html';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  //  DISPARO EM MASSA — Contatos
  // ═══════════════════════════════════════════════════════════════════════════

  let _contatosData = [];

  // ── Abas Contatos / Grupos ────────────────────────────────────────────────
  function switchContatosTab(tab) {
    const isContatos = tab === 'contatos';
    document.getElementById('tabPanelContatos').style.display  = isContatos ? '' : 'none';
    document.getElementById('tabPanelGrupos').style.display    = isContatos ? 'none' : '';
    document.getElementById('tabBtnContatos').style.borderBottomColor = isContatos ? 'var(--accent)' : 'transparent';
    document.getElementById('tabBtnContatos').style.color      = isContatos ? 'var(--accent)' : 'var(--text-mid)';
    document.getElementById('tabBtnGrupos').style.borderBottomColor   = isContatos ? 'transparent' : 'var(--accent)';
    document.getElementById('tabBtnGrupos').style.color        = isContatos ? 'var(--text-mid)' : 'var(--accent)';
    if (!isContatos) loadGrupos();
  }

  // ── Grupos ────────────────────────────────────────────────────────────────
  let _gruposData = [];
  let _grupoSelecionadoId = null;
  let _allContatosParaGrupo = [];

  async function loadGrupos() {
    const res = await fetch('/api/campanha/grupos');
    if (!res.ok) return;
    _gruposData = await res.json();
    const div = document.getElementById('listaGrupos');
    if (!_gruposData.length) {
      div.innerHTML = '<div style="text-align:center;padding:2.5rem;color:var(--text-mid)">Nenhum grupo criado. Clique em <strong>Novo Grupo</strong> para começar.</div>';
      return;
    }
    div.innerHTML = `<table><thead><tr><th>Nome</th><th style="width:100px;text-align:center">Contatos</th><th style="width:120px;text-align:right">Ações</th></tr></thead><tbody>
      ${_gruposData.map(g => `
        <tr>
          <td><span style="font-weight:600;cursor:pointer;color:var(--accent)" onclick="selecionarGrupo(${g.id},'${escHtml(g.nome)}')">${escHtml(g.nome)}</span></td>
          <td style="text-align:center"><span class="chip chip-green" style="font-size:.72rem">${g.total}</span></td>
          <td style="text-align:right;white-space:nowrap">
            <button class="btn btn-ghost btn-sm" onclick="selecionarGrupo(${g.id},'${escHtml(g.nome)}')">Gerenciar</button>
            <button class="btn btn-ghost btn-sm btn-icon" onclick="deletarGrupo(${g.id},'${escHtml(g.nome)}')"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg></button>
          </td>
        </tr>`).join('')}
    </tbody></table>`;
  }

  async function selecionarGrupo(id, nome) {
    _grupoSelecionadoId = id;
    document.getElementById('grupoSelecionadoNome').textContent = nome;
    document.getElementById('cardGrupoContatos').style.display = '';
    await _carregarContatosGrupo(id);
  }

  async function _carregarContatosGrupo(id) {
    const div = document.getElementById('tbodyGrupoContatos');
    div.innerHTML = '<div style="text-align:center;padding:1.5rem;color:var(--text-mid)">Carregando…</div>';
    const res = await fetch(`/api/campanha/grupos/${id}/contatos`);
    const lista = res.ok ? await res.json() : [];
    if (!lista.length) {
      div.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-mid)">Nenhum contato neste grupo. Clique em <strong>Adicionar Contatos</strong>.</div>';
      return;
    }
    div.innerHTML = `<table><thead><tr><th>Telefone</th><th>Nome</th><th style="width:60px;text-align:center">Remover</th></tr></thead><tbody>
      ${lista.map(c => `
        <tr>
          <td style="font-family:monospace;font-size:.85rem">${_fmtPhone(c.phone)}</td>
          <td>${escHtml(c.nome || '—')}</td>
          <td style="text-align:center">
            <button class="btn btn-ghost btn-sm btn-icon" onclick="removerDoGrupo(${c.id})"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
          </td>
        </tr>`).join('')}
    </tbody></table>`;
  }

  async function removerDoGrupo(contatoId) {
    await api('DELETE', `/api/campanha/grupos/${_grupoSelecionadoId}/contatos/${contatoId}`);
    _carregarContatosGrupo(_grupoSelecionadoId);
    loadGrupos();
  }

  async function deletarGrupo(id, nome) {
    const ok = await showConfirm({ title: `Excluir grupo "${nome}"?`, body: 'Os contatos não serão excluídos, apenas o grupo.', okLabel: 'Excluir', type: 'danger' });
    if (!ok) return;
    await api('DELETE', `/api/campanha/grupos/${id}`);
    if (_grupoSelecionadoId === id) {
      _grupoSelecionadoId = null;
      document.getElementById('cardGrupoContatos').style.display = 'none';
    }
    loadGrupos();
  }

  // ── Novo Grupo ───────────────────────────────────────────────────────────
  let _editGrupoId = null;
  document.getElementById('btnNovoGrupo').addEventListener('click', () => {
    _editGrupoId = null;
    document.getElementById('modalGrupoContatoTitulo').textContent = 'Novo Grupo';
    document.getElementById('inpGrupoNome').value = '';
    document.getElementById('modalGrupoContato').classList.add('open');
  });
  document.getElementById('btnCancelarGrupo').addEventListener('click', () => {
    document.getElementById('modalGrupoContato').classList.remove('open');
  });
  document.getElementById('btnSalvarGrupo').addEventListener('click', async () => {
    const nome = document.getElementById('inpGrupoNome').value.trim();
    if (!nome) return;
    const method = _editGrupoId ? 'PUT' : 'POST';
    const path = _editGrupoId ? `/api/campanha/grupos/${_editGrupoId}` : '/api/campanha/grupos';
    const res = await api(method, path, { nome });
    if (res.ok !== false) {
      document.getElementById('modalGrupoContato').classList.remove('open');
      loadGrupos();
    } else {
      showAlert('alertContatos', res.detail || 'Erro ao salvar grupo.', 'error');
    }
  });

  // ── Adicionar contatos ao grupo ──────────────────────────────────────────
  document.getElementById('btnAddContatosGrupo').addEventListener('click', async () => {
    const div = document.getElementById('listaAddContatos');
    div.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--text-mid)">Carregando…</div>';
    document.getElementById('searchAddContatos').value = '';
    document.getElementById('modalAddContatosGrupo').classList.add('open');
    const r1 = await fetch('/api/campanha/contatos');
    const todos = r1.ok ? await r1.json() : [];
    const r2 = await fetch(`/api/campanha/grupos/${_grupoSelecionadoId}/contatos`);
    const noGrupo = r2.ok ? await r2.json() : [];
    const noGrupoIds = new Set(noGrupo.map(c => c.id));
    _allContatosParaGrupo = todos.filter(c => !noGrupoIds.has(c.id) && c.ativo !== false);
    _renderAddContatos(_allContatosParaGrupo);
  });

  function _renderAddContatos(lista) {
    const div = document.getElementById('listaAddContatos');
    if (!lista.length) {
      div.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--text-mid)">Todos os contatos já estão no grupo.</div>';
      return;
    }
    div.innerHTML = lista.map(c => `
      <label style="display:flex;align-items:center;gap:.625rem;padding:.4rem .5rem;border-radius:6px;cursor:pointer" onmouseover="this.style.background='var(--surface)'" onmouseout="this.style.background=''">
        <input type="checkbox" class="add-grupo-cb" data-id="${c.id}" style="width:15px;height:15px;accent-color:var(--accent);cursor:pointer;flex-shrink:0" />
        <span style="font-weight:500;font-size:.875rem;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(c.nome || '—')}</span>
        <span style="font-size:.78rem;color:var(--text-mid);flex-shrink:0">${_fmtPhone(c.phone)}</span>
      </label>`).join('');
  }

  document.getElementById('searchAddContatos').addEventListener('input', function() {
    const q = this.value.toLowerCase();
    _renderAddContatos(_allContatosParaGrupo.filter(c =>
      (c.nome || '').toLowerCase().includes(q) || String(c.phone).includes(q)
    ));
  });

  // ── Pick Grupo (seleção múltipla na tabela de contatos) ─────────────────────
  async function abrirPickGrupo() {
    const ids = [...document.querySelectorAll('.cb-contato:checked')].map(cb => Number(cb.dataset.id));
    if (!ids.length) return;
    // Carrega grupos
    const r = await fetch('/api/campanha/grupos');
    const grupos = r.ok ? await r.json() : [];
    const sel = document.getElementById('selPickGrupo');
    sel.innerHTML = grupos.length
      ? '<option value="">— Selecione um grupo —</option>' + grupos.map(g => `<option value="${g.id}">${escHtml(g.nome)} (${g.total} contatos)</option>`).join('')
      : '<option value="">Nenhum grupo criado</option>';
    document.getElementById('inpPickGrupoNovo').value = '';
    document.getElementById('modalPickGrupoDesc').textContent = `${ids.length} contato(s) selecionado(s)`;
    document.getElementById('modalPickGrupo').classList.add('open');
  }

  document.getElementById('btnCancelarPickGrupo').addEventListener('click', () => {
    document.getElementById('modalPickGrupo').classList.remove('open');
  });

  document.getElementById('btnConfirmarPickGrupo').addEventListener('click', async () => {
    const ids = [...document.querySelectorAll('.cb-contato:checked')].map(cb => Number(cb.dataset.id));
    if (!ids.length) { document.getElementById('modalPickGrupo').classList.remove('open'); return; }

    let grupoId = Number(document.getElementById('selPickGrupo').value);
    const novoNome = document.getElementById('inpPickGrupoNovo').value.trim();

    // Se preencheu nome novo, cria o grupo primeiro
    if (novoNome) {
      const r = await api('POST', '/api/campanha/grupos', { nome: novoNome });
      if (r.ok === false) { showAlert('alertContatos', r.detail || 'Erro ao criar grupo.', 'error'); return; }
      grupoId = r.id;
    }

    if (!grupoId) { showAlert('alertContatos', 'Selecione um grupo ou informe um nome novo.', 'error'); return; }

    const res = await api('POST', `/api/campanha/grupos/${grupoId}/contatos`, { contato_ids: ids });
    document.getElementById('modalPickGrupo').classList.remove('open');
    if (res.ok !== false) {
      showAlert('alertContatos', `${ids.length} contato(s) adicionado(s) ao grupo com sucesso!`);
      limparSelecaoContatos();
      if (_grupoSelecionadoId === grupoId) _carregarContatosGrupo(grupoId);
      loadGrupos();
    } else {
      showAlert('alertContatos', res.detail || 'Erro ao adicionar contatos.', 'error');
    }
  });

  document.getElementById('btnCancelarAddContatos').addEventListener('click', () => {
    document.getElementById('modalAddContatosGrupo').classList.remove('open');
  });

  document.getElementById('btnConfirmarAddContatos').addEventListener('click', async () => {
    const ids = [...document.querySelectorAll('.add-grupo-cb:checked')].map(cb => Number(cb.dataset.id));
    if (!ids.length) { showAlert('alertContatos', 'Selecione ao menos um contato.', 'error'); return; }
    const res = await api('POST', `/api/campanha/grupos/${_grupoSelecionadoId}/contatos`, { contato_ids: ids });
    document.getElementById('modalAddContatosGrupo').classList.remove('open');
    if (res.ok !== false) {
      _carregarContatosGrupo(_grupoSelecionadoId);
      loadGrupos();
    }
  });

  async function loadContatos() {
    const q = document.getElementById('searchContatos').value || '';
    const res = await fetch('/api/campanha/contatos?q=' + encodeURIComponent(q));
    if (!res.ok) return;
    _contatosData = await res.json();
    renderContatos(_contatosData);
  }

  function renderContatos(lista) {
    const tbody = document.getElementById('tbodyContatos');
    if (!lista.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:2.5rem;color:var(--text-mid)">Nenhum contato cadastrado. Clique em <strong>Novo Contato</strong> ou importe um CSV.</td></tr>';
      document.getElementById('cbSelectAllContatos').checked = false;
      _atualizarActionBar();
      return;
    }
    tbody.innerHTML = lista.map(c => {
      const badge = c.origem === 'erp'
        ? `<span style="background:#dcfce7;color:#15803d;font-size:.68rem;font-weight:700;padding:.15rem .4rem;border-radius:5px;letter-spacing:.03em">ERP</span>`
        : `<span style="background:var(--surface2);color:var(--text-mid);font-size:.68rem;font-weight:600;padding:.15rem .4rem;border-radius:5px">Manual</span>`;
      return `
      <tr>
        <td style="text-align:center"><input type="checkbox" class="cb-contato" data-id="${c.id}" style="width:15px;height:15px;accent-color:var(--accent);cursor:pointer" onchange="_atualizarActionBar()"></td>
        <td style="font-family:monospace;font-size:.85rem">${_fmtPhone(c.phone)}</td>
        <td>${escHtml(c.nome || '—')}</td>
        <td style="text-align:center">${badge}</td>
        <td style="text-align:center">
          <button class="btn btn-ghost btn-sm btn-icon" onclick="deletarContato(${c.id})" title="Excluir" style="color:var(--red)">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
          </button>
        </td>
      </tr>`;
    }).join('');
    document.getElementById('cbSelectAllContatos').checked = false;
    _atualizarActionBar();
  }

  function _atualizarActionBar() {
    const checked = document.querySelectorAll('.cb-contato:checked');
    const bar = document.getElementById('contatosActionBar');
    bar.style.display = checked.length ? 'flex' : 'none';
    document.getElementById('contatosSelCount').textContent = checked.length;
    // Sync select-all state
    const all = document.querySelectorAll('.cb-contato');
    document.getElementById('cbSelectAllContatos').indeterminate = checked.length > 0 && checked.length < all.length;
    document.getElementById('cbSelectAllContatos').checked = all.length > 0 && checked.length === all.length;
  }

  function limparSelecaoContatos() {
    document.querySelectorAll('.cb-contato').forEach(cb => cb.checked = false);
    document.getElementById('cbSelectAllContatos').checked = false;
    _atualizarActionBar();
  }

  document.getElementById('cbSelectAllContatos').addEventListener('change', function() {
    document.querySelectorAll('.cb-contato').forEach(cb => cb.checked = this.checked);
    _atualizarActionBar();
  });

  // ── Helpers de telefone ───────────────────────────────────────────────────────
  // Garante que o número começa com 55 (adiciona se necessário)
  function _normPhone(raw) {
    const d = raw.replace(/\D/g, '');
    if (d.startsWith('55') && d.length >= 12) return d;
    return '55' + d;
  }
  // Formata para exibição: +55 (11) 9 9999-0000
  function _fmtPhone(num) {
    const d = String(num).replace(/\D/g, '').replace(/^55/, '');
    if (d.length === 11) return `+55 (${d.slice(0,2)}) ${d.slice(2,7)}-${d.slice(7)}`;
    if (d.length === 10) return `+55 (${d.slice(0,2)}) ${d.slice(2,6)}-${d.slice(6)}`;
    return `+55 ${d}`;
  }

  document.getElementById('searchContatos').addEventListener('input', () => loadContatos());

  // Modal novo contato
  document.getElementById('btnNovoContato').addEventListener('click', () => {
    document.getElementById('inpContatoPhone').value = '';
    document.getElementById('inpContatoNome').value = '';
    document.getElementById('modalContato').classList.add('open');
    setTimeout(() => document.getElementById('inpContatoPhone').focus(), 100);
  });
  document.getElementById('btnCancelarContato').addEventListener('click', () => {
    document.getElementById('modalContato').classList.remove('open');
  });
  document.getElementById('btnSalvarContato').addEventListener('click', async () => {
    const raw  = document.getElementById('inpContatoPhone').value.trim();
    const nome = document.getElementById('inpContatoNome').value.trim();
    if (!raw) { showAlert('alertContatos', 'Informe o telefone.', 'error'); return; }
    const phone = _normPhone(raw);
    if (phone.replace(/\D/g,'').length < 12) {
      showAlert('alertContatos', 'Número inválido — informe DDD + número (mínimo 10 dígitos).', 'error'); return;
    }
    const res = await api('POST', '/api/campanha/contatos', { phone, nome });
    document.getElementById('modalContato').classList.remove('open');
    if (res.ok) { showAlert('alertContatos', 'Contato salvo!'); loadContatos(); }
    else showAlert('alertContatos', 'Erro ao salvar contato.', 'error');
  });

  async function deletarContato(id) {
    const ok = await showConfirm({ title: 'Excluir contato?', body: 'Esta ação não pode ser desfeita.', okLabel: 'Excluir', type: 'danger' });
    if (!ok) return;
    await api('DELETE', `/api/campanha/contatos/${id}`);
    loadContatos();
  }

  // Importar CSV — adiciona 55 automaticamente se não tiver
  document.getElementById('btnImportarCsv').addEventListener('click', () => {
    document.getElementById('csvInput').click();
  });
  document.getElementById('csvInput').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    // Normaliza o CSV antes de enviar: garante prefixo 55
    const text = await file.text();
    const normalized = text.split('\n').map(line => {
      const parts = line.trim().split(',');
      if (!parts[0]) return line;
      parts[0] = _normPhone(parts[0].trim());
      return parts.join(',');
    }).join('\n');
    const fd = new FormData();
    fd.append('file', new Blob([normalized], { type: 'text/csv' }), file.name);
    const res = await fetch('/api/campanha/contatos/importar', { method: 'POST', body: fd });
    const data = await res.json();
    e.target.value = '';
    if (data.ok) {
      showAlert('alertContatos', `Importados: ${data.importados} — Erros: ${data.erros}`);
      loadContatos();
    } else showAlert('alertContatos', 'Erro ao importar.', 'error');
  });

  // ═══════════════════════════════════════════════════════════════════════════
  //  DISPARO EM MASSA — Nova Campanha
  // ═══════════════════════════════════════════════════════════════════════════

  let _campanhaCriadaId = null;
  let _campanhaCriadaArquivos = [];

  function _setTipoEnvio(value) {
    document.querySelectorAll('.tipo-envio-card:not(.agend-card)').forEach(card => {
      const isSelected = card.dataset.value === value;
      card.classList.toggle('selected', isSelected);
      card.querySelector('input[type="radio"]').checked = isSelected;
    });
    document.getElementById('secCampArquivos').style.display = value === 'file' ? 'block' : 'none';
  }

  function toggleEmojiBank() {
    const bank = document.getElementById('emojiBank');
    bank.style.display = bank.style.display === 'none' ? 'block' : 'none';
  }

  function insertEmoji(emoji) {
    const ta = document.getElementById('inpCampMensagem');
    if (!ta) return;
    const start = ta.selectionStart;
    const end   = ta.selectionEnd;
    ta.value = ta.value.slice(0, start) + emoji + ta.value.slice(end);
    ta.selectionStart = ta.selectionEnd = start + emoji.length;
    ta.focus();
  }

  function initNovaCampanha() {
    // Reset form
    document.getElementById('inpCampNome').value = '';
    document.getElementById('inpCampMensagem').value = '';
    _setTipoEnvio('text');
    document.getElementById('listaCampArquivos').innerHTML = '';
    _campanhaCriadaId = null;
    _campanhaCriadaArquivos = [];
    const btnArq = document.getElementById('btnAddCampArquivo');
    btnArq.disabled = true; btnArq.style.opacity = '0.45'; btnArq.style.cursor = 'not-allowed';
    // Reset emoji bank
    document.getElementById('emojiBank').style.display = 'none';
    // Reset scheduling
    _setAgendamento('agora');
    document.getElementById('inpCampData').value = '';
    document.getElementById('inpCampHora').value = '08:00';
    // Set min date to today
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('inpCampData').min = today;
  }

  document.querySelectorAll('.tipo-envio-card:not(.agend-card)').forEach(card => {
    card.addEventListener('click', () => {
      _setTipoEnvio(card.dataset.value);
    });
  });

  function _setAgendamento(val) {
    document.querySelectorAll('.agend-card').forEach(c => c.classList.remove('selected'));
    const target = document.querySelector(`.agend-card[data-agend="${val}"]`);
    if (target) target.classList.add('selected');
    const radio = document.querySelector(`input[name="campAgendamento"][value="${val}"]`);
    if (radio) radio.checked = true;
    document.getElementById('secAgendamento').style.display = (val === 'agendar') ? 'block' : 'none';
  }

  document.getElementById('btnAddCampArquivo').addEventListener('click', () => {
    document.getElementById('inpCampArquivo').click();
  });

  document.getElementById('inpCampArquivo').addEventListener('change', async (e) => {
    if (!_campanhaCriadaId) {
      showAlert('alertCampanha', 'Crie a campanha primeiro antes de adicionar arquivos.', 'error');
      e.target.value = '';
      return;
    }
    for (const file of e.target.files) {
      try {
        const fd = new FormData();
        fd.append('file', file);
        showAlert('alertCampanha', `Enviando "${file.name}"…`);
        const previewUrl = URL.createObjectURL(file);
        const res = await fetch(`/api/campanha/${_campanhaCriadaId}/arquivo`, { method: 'POST', body: fd });
        if (!res.ok) {
          const txt = await res.text();
          showAlert('alertCampanha', `Erro ao enviar "${file.name}": HTTP ${res.status} — ${txt.slice(0,100)}`, 'error');
          URL.revokeObjectURL(previewUrl);
          continue;
        }
        const data = await res.json();
        if (data.ok) {
          _campanhaCriadaArquivos.push({ ...data, previewUrl, fileType: file.type, fileSize: file.size });
          showAlert('alertCampanha', `Arquivo "${file.name}" adicionado com sucesso!`);
        } else {
          showAlert('alertCampanha', `Falha ao adicionar "${file.name}".`, 'error');
          URL.revokeObjectURL(previewUrl);
        }
      } catch (err) {
        showAlert('alertCampanha', `Erro: ${err.message}`, 'error');
      }
    }
    e.target.value = '';
    renderCampArquivos(_campanhaCriadaArquivos);
  });

  function _fmtSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
    return (bytes/(1024*1024)).toFixed(1) + ' MB';
  }

  function renderCampArquivos(lista) {
    const div = document.getElementById('listaCampArquivos');
    if (!lista.length) { div.innerHTML = ''; return; }
    div.innerHTML = lista.map((a, i) => {
      const isImg = a.fileType && a.fileType.startsWith('image/');
      const isPdf = a.nome_original && a.nome_original.toLowerCase().endsWith('.pdf');
      const nome = escHtml(a.nome_original || '');
      const size = _fmtSize(a.fileSize);

      let preview = '';
      if (isImg && a.previewUrl) {
        preview = `<img src="${a.previewUrl}" style="width:64px;height:64px;object-fit:cover;border-radius:6px;border:1px solid var(--border-soft);flex-shrink:0" />`;
      } else if (isPdf) {
        preview = `<div style="width:64px;height:64px;background:#fee2e2;border-radius:6px;border:1px solid #fca5a5;display:flex;flex-direction:column;align-items:center;justify-content:center;flex-shrink:0">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
          <span style="font-size:.6rem;font-weight:700;color:#dc2626;margin-top:2px">PDF</span>
        </div>`;
      } else {
        preview = `<div style="width:64px;height:64px;background:var(--accent-soft);border-radius:6px;border:1px solid var(--border-soft);display:flex;align-items:center;justify-content:center;flex-shrink:0">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
        </div>`;
      }

      return `<div style="display:flex;align-items:center;gap:.75rem;padding:.625rem;background:var(--surface);border:1px solid var(--border-soft);border-radius:10px">
        ${preview}
        <div style="flex:1;min-width:0">
          <div style="font-weight:600;font-size:.85rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${nome}</div>
          ${size ? `<div style="font-size:.75rem;color:var(--text-mid);margin-top:2px">${size}</div>` : ''}
          <span class="chip chip-green" style="font-size:.7rem;margin-top:4px">✓ Adicionado</span>
        </div>
        ${a.previewUrl && isImg ? `<a href="${a.previewUrl}" target="_blank" style="font-size:.75rem;color:var(--accent);white-space:nowrap">Ver</a>` : ''}
      </div>`;
    }).join('');
  }

  document.getElementById('btnCriarCampanha').addEventListener('click', async () => {
    const nome = document.getElementById('inpCampNome').value.trim();
    const mensagem = document.getElementById('inpCampMensagem').value.trim();
    const tipo = document.querySelector('input[name="campTipo"]:checked').value;
    if (!nome) { showAlert('alertCampanha', 'Informe o nome da campanha.', 'error'); return; }
    if (tipo === 'text' && !mensagem) { showAlert('alertCampanha', 'Informe a mensagem.', 'error'); return; }
    const agendamento = document.querySelector('input[name="campAgendamento"]:checked').value;
    let agendado_em = null;
    if (agendamento === 'agendar') {
      const data = document.getElementById('inpCampData').value;
      const hora = document.getElementById('inpCampHora').value;
      if (!data || !hora) { showAlert('alertCampanha', 'Informe data e hora para o agendamento.', 'error'); return; }
      agendado_em = new Date(`${data}T${hora}:00`).toISOString();
    }
    const res = await api('POST', '/api/campanha', { nome, tipo, mensagem, agendado_em });
    if (!res.ok) { showAlert('alertCampanha', 'Erro ao criar campanha.', 'error'); return; }
    _campanhaCriadaId = res.id;
    if (tipo === 'file') {
      const btn = document.getElementById('btnAddCampArquivo');
      btn.disabled = false;
      btn.style.opacity = '1';
      btn.style.cursor = 'pointer';
      showAlert('alertCampanha', `Campanha "${nome}" criada! Agora clique em "Selecionar arquivo" para adicionar o(s) arquivo(s).`);
    } else {
      const msg = agendado_em
        ? `Campanha "${nome}" agendada para ${new Date(agendado_em).toLocaleString('pt-BR')}!`
        : `Campanha "${nome}" criada! Vá em Gerenciar Campanhas para iniciar o disparo.`;
      showAlert('alertCampanha', msg);
      setTimeout(() => showPage('dm-historico'), 1500);
    }
  });

  // ═══════════════════════════════════════════════════════════════════════════
  //  DISPARO EM MASSA — Campanhas (Histórico)
  // ═══════════════════════════════════════════════════════════════════════════

  let _campModalId = null;

  async function loadCampanhas() {
    const res = await fetch('/api/campanha');
    if (!res.ok) return;
    const lista = await res.json();
    renderCampanhas(lista);
  }

  // ══════════════════════════════════════════════════════════════════════════
  //  DASHBOARD CAMPANHAS
  // ══════════════════════════════════════════════════════════════════════════

  let _dashCharts = {}; // armazena instâncias Chart.js para destruir antes de recriar

  function _destroyCharts() {
    Object.values(_dashCharts).forEach(c => { try { c.destroy(); } catch(_) {} });
    _dashCharts = {};
  }

  async function loadDashboardCampanhas() {
    _destroyCharts();

    // Popula select de campanhas (uma única vez)
    const sel = document.getElementById('dashCampanhaSelect');
    if (sel && sel.options.length <= 1) {
      try {
        const r = await fetch('/api/campanha');
        if (r.ok) {
          const lista = await r.json();
          lista.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = c.nome;
            sel.appendChild(opt);
          });
        }
      } catch(_) {}
    }

    const campId = document.getElementById('dashCampanhaSelect')?.value || '';
    const dias   = document.getElementById('dashDiasSelect')?.value || '30';
    const qs     = new URLSearchParams({ dias });
    if (campId) qs.set('campanha_id', campId);

    let data;
    try {
      const res = await fetch('/api/campanha/dashboard?' + qs);
      if (!res.ok) return;
      data = await res.json();
    } catch(e) { return; }

    const r = data.resumo || {};

    // ── KPI Cards ───────────────────────────────────────────────────────────
    document.getElementById('dval-enviados').textContent  = (r.total_enviados || 0).toLocaleString('pt-BR');
    document.getElementById('dsub-enviados').textContent  = `de ${(r.total_mensagens||0).toLocaleString('pt-BR')} mensagens`;
    document.getElementById('dval-falhas').textContent    = (r.total_falhas || 0).toLocaleString('pt-BR');
    const taxaFalha = r.total_mensagens > 0 ? ((r.total_falhas / r.total_mensagens) * 100).toFixed(1) : '0.0';
    document.getElementById('dsub-falhas').textContent    = taxaFalha + '% das mensagens';
    document.getElementById('dval-taxa').textContent      = (r.taxa_sucesso || 0).toFixed(1) + '%';
    document.getElementById('dsub-taxa').textContent      = r.na_fila > 0 ? r.na_fila + ' na fila' : 'entregues com sucesso';
    document.getElementById('dval-campanhas').textContent = r.total_campanhas || 0;
    document.getElementById('dsub-campanhas').textContent = 'campanhas no período';
    document.getElementById('dval-contatos').textContent  = (r.contatos_unicos || 0).toLocaleString('pt-BR');
    document.getElementById('dsub-contatos').textContent  = 'números alcançados';
    const durFmt = r.duracao_media_min != null
      ? (r.duracao_media_min < 60 ? Math.round(r.duracao_media_min) + ' min' : (r.duracao_media_min/60).toFixed(1) + ' h')
      : '—';
    document.getElementById('dval-duracao').textContent   = durFmt;
    document.getElementById('dsub-duracao').textContent   = 'por campanha concluída';

    // Cores do design system
    const GREEN  = '#3d7f1f';
    const RED    = '#dc2626';
    const BLUE   = '#3b82f6';
    const YELLOW = '#f59e0b';
    const GRAY   = '#e5e7eb';
    const PURPLE = '#8b5cf6';

    const fontDef = { family: "'Inter','Segoe UI',system-ui,sans-serif", size: 11 };

    // ── Donut: distribuição por status ──────────────────────────────────────
    const ctxDonut = document.getElementById('chartDonut')?.getContext('2d');
    if (ctxDonut) {
      const env = r.total_enviados || 0;
      const fal = r.total_falhas   || 0;
      const fil = r.na_fila        || 0;
      _dashCharts.donut = new Chart(ctxDonut, {
        type: 'doughnut',
        data: {
          labels: ['Enviados', 'Falhas', 'Na fila'],
          datasets: [{ data: [env, fal, fil], backgroundColor: [GREEN, RED, YELLOW],
            borderWidth: 2, borderColor: '#fff', hoverOffset: 6 }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          cutout: '68%',
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: ctx => ` ${ctx.label}: ${ctx.raw.toLocaleString('pt-BR')} (${ctx.raw > 0 ? ((ctx.raw/(env+fal+fil))*100).toFixed(1) : 0}%)`
              }
            }
          }
        }
      });
      const leg = document.getElementById('dashDonutLegend');
      if (leg) {
        const items = [['Enviados', GREEN, env], ['Falhas', RED, fal], ['Na fila', YELLOW, fil]];
        leg.innerHTML = items.map(([lbl, clr, val]) =>
          `<span style="display:inline-flex;align-items:center;gap:.3rem">
            <span style="width:10px;height:10px;border-radius:50%;background:${clr};flex-shrink:0"></span>
            <span>${lbl}: <strong>${val.toLocaleString('pt-BR')}</strong></span>
          </span>`
        ).join('');
      }
    }

    // ── Bar: envios por hora ─────────────────────────────────────────────────
    const ctxHora = document.getElementById('chartHora')?.getContext('2d');
    if (ctxHora && data.por_hora) {
      const labels = data.por_hora.map(h => h.hora + 'h');
      const vals   = data.por_hora.map(h => h.enviados);
      const maxVal = Math.max(...vals, 1);
      _dashCharts.hora = new Chart(ctxHora, {
        type: 'bar',
        data: {
          labels,
          datasets: [{ label: 'Enviados', data: vals,
            backgroundColor: vals.map(v => v === maxVal ? PURPLE : 'rgba(139,92,246,.35)'),
            borderRadius: 4, borderSkipped: false }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false },
            tooltip: { callbacks: { label: ctx => ` ${ctx.raw.toLocaleString('pt-BR')} enviados` } }
          },
          scales: {
            x: { grid: { display: false }, ticks: { font: fontDef, maxRotation: 0 } },
            y: { grid: { color: '#f3f4f6' }, ticks: { font: fontDef },
                 beginAtZero: true }
          }
        }
      });
    }

    // ── Line: envios por dia ─────────────────────────────────────────────────
    const ctxDia = document.getElementById('chartDia')?.getContext('2d');
    if (ctxDia && data.por_dia) {
      const labels = data.por_dia.map(d => {
        const dt = new Date(d.dia + 'T12:00:00');
        return dt.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
      });
      const vals = data.por_dia.map(d => d.enviados);
      _dashCharts.dia = new Chart(ctxDia, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: 'Enviados', data: vals,
            borderColor: GREEN, backgroundColor: 'rgba(61,127,31,.12)',
            borderWidth: 2.5, pointRadius: vals.length <= 14 ? 4 : 2,
            pointBackgroundColor: GREEN, fill: true, tension: .35
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false },
            tooltip: { callbacks: { label: ctx => ` ${ctx.raw.toLocaleString('pt-BR')} enviados` } }
          },
          scales: {
            x: { grid: { display: false }, ticks: { font: fontDef, maxTicksLimit: 15 } },
            y: { grid: { color: '#f3f4f6' }, ticks: { font: fontDef }, beginAtZero: true }
          }
        }
      });
    }

    // ── Ranking campanhas (tabela com mini barra) ────────────────────────────
    const rankDiv = document.getElementById('dashRankingCampanhas');
    if (rankDiv && data.campanhas) {
      const sorted = [...data.campanhas].sort((a, b) => b.enviados - a.enviados);
      const maxEnv = Math.max(...sorted.map(c => c.total || 0), 1);
      const medals = ['gold', 'silver', 'bronze'];
      const statusEmoji = { done: '✅', running: '🟢', paused: '⏸', draft: '📝', scheduled: '⏰' };
      rankDiv.innerHTML = sorted.slice(0, 8).map((c, i) => {
        const pct = maxEnv > 0 ? Math.round(c.total / maxEnv * 100) : 0;
        const succPct = c.total > 0 ? Math.round(c.enviados / c.total * 100) : 0;
        const em = statusEmoji[c.status] || '—';
        return `<div class="rank-row">
          <div class="rank-num ${medals[i] || ''}"><span>${i+1}</span></div>
          <div class="rank-bar-wrap">
            <div class="rank-name" title="${escHtml(c.nome)}">${em} ${escHtml(c.nome)}</div>
            <div class="rank-bar-bg">
              <div class="rank-bar-fill" style="width:${pct}%;background:${succPct>=90?GREEN:succPct>=70?YELLOW:RED}"></div>
            </div>
          </div>
          <div class="rank-stat">
            <div style="color:${GREEN};font-size:.8rem">${c.enviados.toLocaleString('pt-BR')}</div>
            <div style="font-size:.68rem;font-weight:400">${succPct}% ok</div>
          </div>
        </div>`;
      }).join('') || '<div style="text-align:center;padding:2rem;color:var(--text-mid)">Nenhuma campanha ainda.</div>';
    }

    // ── Top contatos ─────────────────────────────────────────────────────────
    const topDiv = document.getElementById('dashTopContatos');
    if (topDiv && data.top_contatos) {
      const maxE = Math.max(...data.top_contatos.map(c => c.enviados), 1);
      topDiv.innerHTML = data.top_contatos.slice(0, 8).map((c, i) => {
        const pct  = Math.round(c.enviados / maxE * 100);
        const nome = c.nome || _fmtPhone(c.phone);
        return `<div class="rank-row">
          <div class="rank-num ${['gold','silver','bronze'][i]||''}">${i+1}</div>
          <div class="rank-bar-wrap">
            <div class="rank-name" title="${escHtml(nome)}">${escHtml(nome)}</div>
            <div class="rank-bar-bg">
              <div class="rank-bar-fill" style="width:${pct}%;background:#ec4899"></div>
            </div>
          </div>
          <div class="rank-stat">
            <div style="color:#ec4899;font-size:.8rem">${c.enviados} env.</div>
            <div style="font-size:.68rem;font-weight:400">${c.total_campanhas} camp.</div>
          </div>
        </div>`;
      }).join('') || '<div style="text-align:center;padding:2rem;color:var(--text-mid)">Nenhum dado ainda.</div>';
    }

    // ── Barras horizontais campanhas: enviados vs falhas ─────────────────────
    const ctxBar = document.getElementById('chartBarCampanhas')?.getContext('2d');
    if (ctxBar && data.campanhas && data.campanhas.length) {
      const top = data.campanhas.slice(0, 10);
      const labels = top.map(c => c.nome.length > 20 ? c.nome.slice(0, 18) + '…' : c.nome);
      _dashCharts.bar = new Chart(ctxBar, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            { label: 'Enviados', data: top.map(c => c.enviados),
              backgroundColor: 'rgba(61,127,31,.8)', borderRadius: 4 },
            { label: 'Falhas',   data: top.map(c => c.erros),
              backgroundColor: 'rgba(220,38,38,.7)',  borderRadius: 4 }
          ]
        },
        options: {
          indexAxis: 'y',
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: 'top', labels: { font: fontDef, boxWidth: 12, padding: 10 } },
            tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label}: ${ctx.raw.toLocaleString('pt-BR')}` } }
          },
          scales: {
            x: { grid: { color: '#f3f4f6' }, ticks: { font: fontDef }, stacked: false },
            y: { grid: { display: false }, ticks: { font: fontDef } }
          }
        }
      });
    }
  }

  async function loadCampanhasEnviadas() {
    const div = document.getElementById('listaCampanhasEnviadas');
    if (!div) return;
    div.innerHTML = '<div style="text-align:center;padding:3rem;color:var(--text-mid)">Carregando…</div>';
    try {
      const res = await fetch('/api/campanha?status=done');
      if (!res.ok) { div.innerHTML = '<div style="text-align:center;padding:3rem;color:var(--text-mid)">Erro ao carregar.</div>'; return; }
      const lista = await res.json();
      if (!lista.length) {
        div.innerHTML = '<div style="text-align:center;padding:3rem;color:var(--text-mid)">Nenhuma campanha concluída ainda.</div>';
        return;
      }
      div.innerHTML = lista.map(c => {
        const dt       = c.created_at ? new Date(c.created_at).toLocaleDateString('pt-BR') : '—';
        const doneAt   = c.done_at ? new Date(c.done_at).toLocaleString('pt-BR') : '—';
        const tipoChip = c.tipo === 'file'
          ? '<span class="chip chip-purple" style="font-size:.72rem">📎 Arquivo</span>'
          : '<span class="chip chip-blue" style="font-size:.72rem">💬 Texto</span>';
        const msg = c.mensagem
          ? `<div style="margin-top:.5rem;font-size:.8rem;color:var(--text-mid);font-style:italic">"${escHtml(c.mensagem.substring(0,100))}${c.mensagem.length>100?'…':''}"</div>`
          : '';
        const pct = c.total > 0 ? Math.round((c.enviados / c.total) * 100) : 0;
        return `
        <div style="background:var(--surface);border:1px solid var(--border);border-left:4px solid #22c55e;border-radius:var(--radius);padding:1.25rem 1.5rem;margin-bottom:.75rem;box-shadow:var(--shadow-sm)">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap">
            <div style="flex:1;min-width:0">
              <div style="display:flex;align-items:center;gap:.625rem;flex-wrap:wrap;margin-bottom:.3rem">
                <span style="font-weight:700;font-size:.9375rem">${escHtml(c.nome)}</span>
                ${tipoChip}
                <span class="chip chip-blue" style="font-size:.72rem">✅ Concluída</span>
              </div>
              <div style="font-size:.78rem;color:var(--text-mid)">
                Criada em ${dt} &nbsp;·&nbsp; Concluída em ${doneAt}
                &nbsp;·&nbsp; Total: <strong>${c.total}</strong>
                &nbsp;·&nbsp; Enviados: <strong style="color:var(--accent)">${c.enviados}</strong>
                &nbsp;·&nbsp; Erros: <strong style="color:var(--red)">${c.erros}</strong>
              </div>
              ${msg}
            </div>
            <div style="display:flex;gap:.4rem;flex-shrink:0">
              <button class="btn btn-ghost btn-sm" onclick="deletarCampanha(${c.id})" style="color:var(--red);border-color:#fecaca;display:inline-flex;align-items:center;gap:.3rem" title="Excluir">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>Excluir
              </button>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:.75rem;margin-top:.875rem">
            <div style="flex:1;height:7px;background:var(--border);border-radius:4px;overflow:hidden">
              <div style="height:100%;width:${pct}%;background:#22c55e;border-radius:4px"></div>
            </div>
            <span style="font-size:.78rem;color:var(--text-mid);white-space:nowrap;font-weight:600;min-width:80px;text-align:right">${c.enviados}/${c.total} (${pct}%)</span>
          </div>
        </div>`;
      }).join('');
    } catch(e) {
      div.innerHTML = '<div style="text-align:center;padding:3rem;color:var(--text-mid)">Erro ao carregar campanhas enviadas.</div>';
    }
  }

  // ── Worker status widget ──────────────────────────────────────────────────────

  async function loadWorkerStatus() {
    try {
      const r = await fetch('/api/campanha/queue/status');
      if (!r.ok) return;
      const d = await r.json();
      const w = d.worker || {};
      const dot = document.getElementById('workerDot');
      const lbl = document.getElementById('workerLabel');
      const det = document.getElementById('workerDetail');

      if (w.running) {
        dot.style.background = '#22c55e';
        lbl.textContent = 'Worker ativo — processando fila';
        const ago = w.last_processed_seconds_ago;
        det.textContent = ago !== null
          ? (ago < 5 ? 'Último envio há menos de 5s' : `Último envio há ${ago}s`)
          : 'Aguardando itens na fila…';
      } else {
        dot.style.background = '#ef4444';
        lbl.textContent = 'Worker parado — clique em Reiniciar';
        det.textContent = w.last_error || 'Nenhuma atividade registrada';
      }

      // Fila counters (queued)
      const mq = d.mensagens || {};
      const aq = d.arquivos || {};
      const eq = d.campanha_envios || {};
      const fmt = obj => {
        const q = obj.queued || 0;
        const f = obj.failed || 0;
        let s = q > 0 ? `<span style="color:var(--accent);font-weight:700">${q} fila</span>` : '0';
        if (f > 0) s += ` <span style="color:var(--red);font-size:.7rem">${f} erro</span>`;
        return s;
      };
      document.getElementById('wsqMsg').innerHTML = fmt(mq);
      document.getElementById('wsqArq').innerHTML = fmt(aq);
      document.getElementById('wsqEnv').innerHTML = fmt(eq);
    } catch {}
  }

  document.getElementById('btnRestartWorker').addEventListener('click', async () => {
    const btn = document.getElementById('btnRestartWorker');
    btn.disabled = true;
    btn.textContent = 'Reiniciando…';
    try {
      const r = await fetch('/api/campanha/queue/restart', { method: 'POST' });
      const d = await r.json();
      showAlert('alertHistorico', d.ok ? 'Worker reiniciado com sucesso!' : 'Erro ao reiniciar.', d.ok ? 'success' : 'error');
      setTimeout(loadWorkerStatus, 800);
    } finally {
      btn.disabled = false;
      btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> Reiniciar Worker`;
    }
  });

  function _progBar(env, total) {
    const pct = total > 0 ? Math.round((env / total) * 100) : 0;
    const barColor = pct === 100 ? '#22c55e' : 'var(--accent)';
    return `
      <div style="display:flex;align-items:center;gap:.75rem;margin-top:.875rem">
        <div style="flex:1;height:7px;background:var(--border);border-radius:4px;overflow:hidden">
          <div style="height:100%;width:${pct}%;background:${barColor};border-radius:4px;transition:width .5s ease"></div>
        </div>
        <span style="font-size:.78rem;color:var(--text-mid);white-space:nowrap;font-weight:600;min-width:80px;text-align:right">${env}/${total} (${pct}%)</span>
      </div>`;
  }

  const _chipClass  = { draft:'chip-gray', scheduled:'chip-purple', running:'chip-green', paused:'chip-yellow', done:'chip-blue' };
  const _statusLabel = { draft:'Rascunho', scheduled:'⏰ Agendada', running:'Disparando', paused:'Pausada', done:'Concluída' };

  function renderCampanhas(lista) {
    const div = document.getElementById('listaCampanhas');
    if (!lista.length) {
      div.innerHTML = '<div style="text-align:center;padding:3rem;color:var(--text-mid)">Nenhuma campanha criada. <a href="#" onclick="showPage(\'dm-campanha\');return false" style="color:var(--accent);font-weight:600">Criar primeira campanha →</a></div>';
      return;
    }
    div.innerHTML = lista.map(c => {
      const chip = _chipClass[c.status] || 'chip-gray';
      const lbl  = _statusLabel[c.status] || c.status;
      const tipoChip = c.tipo === 'file'
        ? '<span class="chip chip-purple" style="font-size:.72rem">📎 Arquivo</span>'
        : '<span class="chip chip-blue" style="font-size:.72rem">💬 Texto</span>';
      const dt = c.created_at ? new Date(c.created_at).toLocaleDateString('pt-BR') : '—';
      const msg = c.mensagem ? `<div style="margin-top:.5rem;font-size:.8rem;color:var(--text-mid);font-style:italic">"${escHtml(c.mensagem.substring(0,80))}${c.mensagem.length>80?'…':''}"</div>` : '';
      const agendadoInfo = c.agendado_em && c.status === 'scheduled'
        ? `<div style="margin-top:.4rem;font-size:.78rem;color:#7c3aed;display:flex;align-items:center;gap:.3rem">
             <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
             Agendada para ${new Date(c.agendado_em).toLocaleString('pt-BR')}
           </div>`
        : '';
      return `
      <div data-camp-id="${c.id}" data-camp-nome="${escHtml(c.nome)}" style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:1.25rem 1.5rem;margin-bottom:.75rem;box-shadow:var(--shadow-sm)">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;flex-wrap:wrap">
          <div style="flex:1;min-width:0">
            <div style="display:flex;align-items:center;gap:.625rem;flex-wrap:wrap;margin-bottom:.3rem">
              <span style="font-weight:700;font-size:.9375rem;letter-spacing:-.01em">${escHtml(c.nome)}</span>
              ${tipoChip}
              <span class="chip ${chip}" style="font-size:.72rem">${lbl}</span>
            </div>
            <div style="font-size:.78rem;color:var(--text-mid)">Criada em ${dt} &nbsp;·&nbsp; Total: <strong>${c.total}</strong> &nbsp;·&nbsp; Enviados: <strong style="color:var(--accent)">${c.enviados}</strong> &nbsp;·&nbsp; Erros: <strong style="color:var(--red)">${c.erros}</strong></div>
            ${msg}
            ${agendadoInfo}
          </div>
          <div style="display:flex;gap:.4rem;flex-wrap:wrap;align-items:center;flex-shrink:0">
            ${c.tipo === 'file' ? `<button class="btn btn-ghost btn-sm" onclick="abrirModalArquivos(${c.id},'${escHtml(c.nome)}')" style="display:inline-flex;align-items:center;gap:.3rem"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>Arquivos</button>` : ''}
            ${c.status === 'draft' || c.status === 'scheduled' || c.status === 'done' || c.status === 'paused' ? `<button class="btn btn-primary btn-sm" onclick="iniciarCampanha(${c.id})" style="display:inline-flex;align-items:center;gap:.3rem"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>Iniciar</button>` : ''}
            ${c.status === 'running' ? `<button class="btn btn-ghost btn-sm" onclick="pausarCampanha(${c.id})" style="border-color:#f59e0b;color:#b45309;display:inline-flex;align-items:center;gap:.3rem"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>Pausar</button>` : ''}
            <button class="btn btn-ghost btn-sm" onclick="deletarCampanha(${c.id})" style="color:var(--red);border-color:#fecaca;display:inline-flex;align-items:center;gap:.3rem" title="Excluir campanha"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>Excluir</button>
          </div>
        </div>
        ${_progBar(c.enviados, c.total)}
      </div>`;
    }).join('');
  }

  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── Modal seleção de contatos ─────────────────────────────────────────────────

  let _selCampanhaId = null;
  let _selContatosAll = [];   // todos os contatos carregados
  let _selModo = 'todos';     // 'todos' | 'grupo' | 'individual'

  function _setSelModo(modo) {
    _selModo = modo;
    document.getElementById('selPainelTodos').style.display      = modo === 'todos'      ? '' : 'none';
    document.getElementById('selPainelGrupo').style.display      = modo === 'grupo'      ? '' : 'none';
    document.getElementById('selPainelIndividual').style.display  = modo === 'individual' ? '' : 'none';
    ['Todos','Grupo','Individual'].forEach(m => {
      const btn = document.getElementById('selModo' + m);
      btn.className = 'btn btn-sm ' + (_selModo === m.toLowerCase() ? 'btn-primary' : 'btn-ghost');
    });
    if (modo === 'grupo') _carregarGruposSelect();
    if (modo === 'individual') _carregarSelContatos();
  }

  async function _carregarGruposSelect() {
    const sel = document.getElementById('selGrupoId');
    sel.innerHTML = '<option value="">Carregando…</option>';
    const r = await fetch('/api/campanha/grupos');
    const grupos = r.ok ? await r.json() : [];
    if (!grupos.length) {
      sel.innerHTML = '<option value="">Nenhum grupo cadastrado</option>';
      return;
    }
    sel.innerHTML = '<option value="">— Selecione um grupo —</option>' +
      grupos.map(g => `<option value="${g.id}">${escHtml(g.nome)} (${g.total} contatos)</option>`).join('');
  }

  async function iniciarCampanha(id) {
    _selCampanhaId = id;
    const campEl = document.querySelector(`[data-camp-id="${id}"]`);
    const campNome = campEl ? campEl.dataset.campNome : '';
    document.getElementById('modalSelContatosCampNome').textContent =
      campNome ? `Campanha: "${campNome}"` : 'Escolha os destinatários desta campanha.';

    // Reset ao modo "todos"
    _setSelModo('todos');

    document.getElementById('modalSelecionarContatos').classList.add('open');
  }

  async function _carregarSelContatos() {
    const div = document.getElementById('listaSelContatos');
    div.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--text-mid)">Carregando…</div>';
    try {
      const r = await fetch('/api/campanha/contatos');
      const lista = await r.json();
      _selContatosAll = Array.isArray(lista) ? lista.filter(c => c.ativo !== false) : [];
    } catch {
      _selContatosAll = [];
    }
    _renderSelContatos(_selContatosAll);
  }

  function _renderSelContatos(lista) {
    const div = document.getElementById('listaSelContatos');
    const countEl = document.getElementById('selContatosCount');
    const totalEl = document.getElementById('selContatosTotal');
    totalEl.textContent = lista.length;

    if (!lista.length) {
      div.innerHTML = '<div style="text-align:center;padding:1rem;color:var(--text-mid)">Nenhum contato encontrado.</div>';
      countEl.textContent = '0';
      return;
    }

    div.innerHTML = lista.map(c => `
      <label style="display:flex;align-items:center;gap:.625rem;padding:.4rem .5rem;border-radius:6px;cursor:pointer;transition:background .15s" onmouseover="this.style.background='var(--surface)'" onmouseout="this.style.background=''">
        <input type="checkbox" class="sel-contato-cb" data-id="${c.id}" checked
          style="width:15px;height:15px;accent-color:var(--accent);cursor:pointer;flex-shrink:0"
          onchange="document.getElementById('selContatosCount').textContent=document.querySelectorAll('.sel-contato-cb:checked').length" />
        <span style="font-weight:500;font-size:.875rem;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
          ${escHtml(c.nome || '—')}
        </span>
        <span style="font-size:.78rem;color:var(--text-mid);flex-shrink:0">${_fmtPhone(c.phone)}</span>
      </label>
    `).join('');

    // Atualiza contador (todos marcados por padrão)
    countEl.textContent = lista.length;
  }

  // Filtrar conforme busca
  document.getElementById('searchSelContatos').addEventListener('input', function () {
    const q = this.value.toLowerCase();
    const filtrado = _selContatosAll.filter(c =>
      (c.nome || '').toLowerCase().includes(q) || String(c.phone).includes(q)
    );
    _renderSelContatos(filtrado);
  });

  document.getElementById('btnSelecionarTodos').addEventListener('click', () => {
    document.querySelectorAll('.sel-contato-cb').forEach(cb => { cb.checked = true; });
    document.getElementById('selContatosCount').textContent =
      document.querySelectorAll('.sel-contato-cb').length;
  });

  document.getElementById('btnDesmarcarTodos').addEventListener('click', () => {
    document.querySelectorAll('.sel-contato-cb').forEach(cb => { cb.checked = false; });
    document.getElementById('selContatosCount').textContent = '0';
  });

  document.getElementById('btnCancelarSelContatos').addEventListener('click', () => {
    document.getElementById('modalSelecionarContatos').classList.remove('open');
  });

  document.getElementById('btnConfirmarIniciar').addEventListener('click', async () => {
    let payload = {};
    let descricao = '';

    if (_selModo === 'todos') {
      payload = {};
      descricao = 'todos os contatos ativos';
    } else if (_selModo === 'grupo') {
      const grupoId = parseInt(document.getElementById('selGrupoId').value);
      if (!grupoId) { showAlert('alertHistorico', 'Selecione um grupo.', 'error'); return; }
      const opt = document.getElementById('selGrupoId').selectedOptions[0];
      payload = { grupo_id: grupoId };
      descricao = `grupo "${opt.textContent.split('(')[0].trim()}"`;
    } else {
      const ids = [...document.querySelectorAll('.sel-contato-cb:checked')].map(cb => Number(cb.dataset.id));
      if (!ids.length) { showAlert('alertHistorico', 'Selecione pelo menos um contato.', 'error'); return; }
      payload = { contato_ids: ids };
      descricao = `${ids.length} contato(s) selecionados`;
    }

    document.getElementById('modalSelecionarContatos').classList.remove('open');
    const res = await api('POST', `/api/campanha/${_selCampanhaId}/iniciar`, payload);
    if (res.ok) {
      showAlert('alertHistorico', `Disparo iniciado para ${descricao}!`);
      loadCampanhas();
      _startCampRefresh();
    } else {
      showAlert('alertHistorico', res.detail || 'Erro ao iniciar campanha.', 'error');
    }
  });

  async function pausarCampanha(id) {
    await api('POST', `/api/campanha/${id}/pausar`);
    loadCampanhas();
  }

  async function deletarCampanha(id) {
    const ok = await showConfirm({ title: 'Excluir campanha?', body: 'Remove todos os envios e arquivos desta campanha.', okLabel: 'Excluir', type: 'danger' });
    if (!ok) return;
    await api('DELETE', `/api/campanha/${id}`);
    const activePage = document.querySelector('.page.active');
    if (activePage && activePage.id === 'page-dm-enviadas') {
      loadCampanhasEnviadas();
    } else {
      loadCampanhas();
    }
  }

  // ── Modal arquivos da campanha ────────────────────────────────────────────────

  async function abrirModalArquivos(id, nome) {
    _campModalId = id;
    document.getElementById('modalCampArqNome').textContent = nome;
    document.getElementById('modalCampArq').classList.add('open');
    await recarregarModalArquivos();
  }

  async function recarregarModalArquivos() {
    const res = await fetch(`/api/campanha/${_campModalId}/arquivos`);
    const lista = await res.json();
    const div = document.getElementById('modalCampArqLista');
    if (!lista.length) {
      div.innerHTML = '<div style="text-align:center;color:var(--text-mid);padding:1rem;font-size:.875rem">Nenhum arquivo adicionado.</div>';
      return;
    }
    div.innerHTML = lista.map(a => `
      <div style="display:flex;align-items:center;gap:.625rem;padding:.5rem .75rem;background:var(--surface2);border:1px solid var(--border-soft);border-radius:8px;font-size:.85rem">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
        <span style="flex:1;font-weight:500">${escHtml(a.nome_original)}</span>
        <button class="btn btn-ghost btn-sm" onclick="deletarArqModal(${a.id})" style="color:var(--red);border-color:#fecaca;padding:.2rem .5rem" title="Remover">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
        </button>
      </div>
    `).join('');
  }

  document.getElementById('btnModalAddArq').addEventListener('click', () => {
    document.getElementById('inpModalCampArquivo').click();
  });

  document.getElementById('inpModalCampArquivo').addEventListener('change', async (e) => {
    for (const file of e.target.files) {
      const fd = new FormData();
      fd.append('file', file);
      await fetch(`/api/campanha/${_campModalId}/arquivo`, { method: 'POST', body: fd });
    }
    e.target.value = '';
    recarregarModalArquivos();
  });

  async function deletarArqModal(arqId) {
    await api('DELETE', `/api/campanha/${_campModalId}/arquivo/${arqId}`);
    recarregarModalArquivos();
  }

  document.getElementById('btnFecharModalArq').addEventListener('click', () => {
    document.getElementById('modalCampArq').classList.remove('open');
    loadCampanhas();
  });

  // ── Auto-refresh campanhas em execução ────────────────────────────────────────
  let _campRefreshTimer = null;
  function _startCampRefresh() {
    if (_campRefreshTimer) clearInterval(_campRefreshTimer);
    _campRefreshTimer = setInterval(async () => {
      const page = document.querySelector('.page.active');
      if (!page || page.id !== 'page-dm-historico') {
        clearInterval(_campRefreshTimer);
        _campRefreshTimer = null;
        return;
      }
      const res = await fetch('/api/campanha');
      if (!res.ok) return;
      const lista = await res.json();
      renderCampanhas(lista);
      loadWorkerStatus();
      // Para o auto-refresh quando não houver mais campanhas em execução
      const hasRunning = lista.some(c => c.status === 'running');
      if (!hasRunning) {
        clearInterval(_campRefreshTimer);
        _campRefreshTimer = null;
      }
    }, 3000);
  }

  // ── Versão do app no rodapé da sidebar ───────────────────────────────────────
  (async () => {
    try {
      const r = await fetch('/api/stats/version');
      if (r.ok) {
        const d = await r.json();
        const el = document.getElementById('app-version');
        if (el) el.textContent = 'v' + d.versao;
      }
    } catch (_) {}
  })();

  // ═══════════════════════════════════════════════════════════════════════════
  //  AVALIAÇÕES
  // ═══════════════════════════════════════════════════════════════════════════

  let _avalDias = 30;
  let _avalPage = 1;
  let _avalFiltroNota = 'todas';
  let _avalData = { dash: null, lista: [] };

  const _avalCorNota = { 1: '#dc2626', 2: '#f97316', 3: '#eab308', 4: '#84cc16', 5: '#22c55e' };
  const _avalBgNota  = { 1: '#fff5f5', 2: '#fff7ed', 3: '#fefce8', 4: '#f7fee7', 5: '#f0fdf4' };

  function _starHtml(nota) {
    let s = '';
    for (let i = 1; i <= 5; i++) {
      s += `<span style="color:${i <= nota ? _avalCorNota[nota] : '#d1d5db'};font-size:.95rem">★</span>`;
    }
    return s;
  }

  async function loadAvaliacoes() {
    await Promise.all([_loadAvalDash(), _loadAvalLista()]);
  }

  async function _loadAvalDash() {
    try {
      const r = await fetch(`/api/avaliacoes/dashboard?dias=${_avalDias}`);
      if (!r.ok) { _renderAvalDashVazio(); return; }
      const d = await r.json();
      _avalData.dash = d;

      // KPIs
      document.getElementById('avalKpiEnviadas').textContent   = d.total_enviadas   ?? '—';
      document.getElementById('avalKpiRespondidas').textContent = d.total_respondidas ?? '—';
      const taxa = d.total_enviadas > 0 ? Math.round((d.total_respondidas / d.total_enviadas) * 100) : 0;
      document.getElementById('avalKpiTaxa').textContent = (d.taxa_resposta ?? taxa) + '%';
      const media = typeof d.media_geral === 'number' ? d.media_geral.toFixed(1) : '—';
      document.getElementById('avalKpiMedia').textContent = media;

      // Alerta de baixas notas
      const ruins = Array.isArray(d.baixas) ? d.baixas : [];
      const alertaDiv = document.getElementById('avalAlertaBaixas');
      if (ruins.length > 0) {
        document.getElementById('avalAlertaTexto').textContent =
          `⚠️ ${ruins.length} avaliação${ruins.length > 1 ? 'ões' : ''} com nota baixa nos últimos ${_avalDias} dias`;
        document.getElementById('avalAlertaLista').innerHTML = ruins.map(a => `
          <div style="display:flex;align-items:center;gap:.75rem;background:#fff;border:1px solid #fecaca;border-radius:8px;padding:.5rem .875rem;border-left:3px solid #dc2626">
            <div style="width:32px;height:32px;border-radius:50%;background:#fee2e2;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.8rem;color:#b91c1c;flex-shrink:0">${(a.nome||'?').charAt(0).toUpperCase()}</div>
            <div style="flex:1;min-width:0">
              <div style="font-weight:600;font-size:.84rem">${escHtml(a.nome||'—')}</div>
              <div style="font-size:.75rem;color:var(--text-mid)">${a.telefone||''}</div>
            </div>
            <div>${_starHtml(a.nota)}</div>
            <div style="font-size:.75rem;color:var(--text-mid);white-space:nowrap">${a.data||''}</div>
          </div>`).join('');
        alertaDiv.style.display = '';
      } else {
        alertaDiv.style.display = 'none';
      }

      // Distribuição por nota
      const dist = d.distribuicao || {};
      const totalResp = d.total_respondidas || 1;
      const notaLabels = { 5: '⭐⭐⭐⭐⭐ Excelente', 4: '⭐⭐⭐⭐ Bom', 3: '⭐⭐⭐ Regular', 2: '⭐⭐ Ruim', 1: '⭐ Péssimo' };
      const notaCores = { 5: '#22c55e', 4: '#84cc16', 3: '#eab308', 2: '#f97316', 1: '#ef4444' };
      document.getElementById('avalDistribuicao').innerHTML = [5,4,3,2,1].map(n => {
        const qtd = dist[n] || 0;
        const pct = totalResp > 0 ? Math.round((qtd / totalResp) * 100) : 0;
        return `
          <div style="display:flex;align-items:center;gap:.625rem">
            <div style="white-space:nowrap;font-size:.78rem;font-weight:600;color:var(--text-mid);min-width:140px">${notaLabels[n]}</div>
            <div style="flex:1;height:10px;background:var(--border);border-radius:5px;overflow:hidden">
              <div style="height:100%;width:${pct}%;background:${notaCores[n]};border-radius:5px;transition:width .7s ease"></div>
            </div>
            <div style="font-size:.75rem;font-weight:700;color:var(--text-mid);white-space:nowrap;min-width:55px;text-align:right">${qtd} (${pct}%)</div>
          </div>`;
      }).join('');

      // Ranking vendedores
      const ranking = Array.isArray(d.ranking_vendedores) ? d.ranking_vendedores : [];
      if (!ranking.length) {
        document.getElementById('avalRanking').innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-mid)">Sem dados</div>';
      } else {
        const melhorMedia = ranking[0].media || 5;
        document.getElementById('avalRanking').innerHTML = ranking.map((v, i) => {
          const pct = melhorMedia > 0 ? Math.round((v.media / melhorMedia) * 100) : 0;
          const barColor = i === 0 ? '#22c55e' : i === ranking.length - 1 && ranking.length > 1 ? '#ef4444' : 'var(--accent)';
          const numClass = i === 0 ? 'rank-num gold' : i === 1 ? 'rank-num silver' : i === 2 ? 'rank-num bronze' : 'rank-num';
          return `
            <div class="rank-row">
              <div class="${numClass}">${i+1}</div>
              <div class="rank-bar-wrap">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.2rem">
                  <span class="rank-name" style="max-width:140px">${escHtml(v.vendedor||'—')}</span>
                  <span style="font-size:.7rem;color:var(--text-mid)">${v.total} aval.</span>
                </div>
                <div class="rank-bar-bg">
                  <div class="rank-bar-fill" style="width:${pct}%;background:${barColor}"></div>
                </div>
              </div>
              <div class="rank-stat">${typeof v.media === 'number' ? v.media.toFixed(1) : '—'} ★</div>
            </div>`;
        }).join('');
      }
    } catch (e) {
      _renderAvalDashVazio();
    }
  }

  function _renderAvalDashVazio() {
    ['avalKpiEnviadas','avalKpiRespondidas','avalKpiTaxa','avalKpiMedia'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = '—';
    });
    document.getElementById('avalDistribuicao').innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-mid)">Sem dados para o período</div>';
    document.getElementById('avalRanking').innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-mid)">Sem dados para o período</div>';
  }

  async function _loadAvalLista() {
    try {
      const r = await fetch(`/api/avaliacoes?dias=${_avalDias}`);
      if (!r.ok) { _avalData.lista = []; }
      else { _avalData.lista = await r.json(); }
    } catch { _avalData.lista = []; }
    _avalPage = 1;
    _renderAvalTabela();
  }

  function _renderAvalRow(aval) {
    const nota = aval.nota || 0;
    const borderColor = _avalCorNota[nota] || '#e4e6ea';
    const bgColor     = _avalBgNota[nota]  || '#fff';
    const inicial = (aval.nome || '?').charAt(0).toUpperCase();
    const temComentario = aval.comentario && aval.comentario.trim().length > 0;
    const comentarioHtml = temComentario
      ? `<div style="font-size:.78rem;color:var(--text-mid);font-style:italic;margin-top:.2rem">"${escHtml(aval.comentario)}"</div>`
      : '';
    return `
      <tr style="border-left:3px solid ${borderColor};background:${bgColor}">
        <td>
          <div style="display:flex;align-items:center;gap:.625rem">
            <div style="width:32px;height:32px;border-radius:50%;background:${borderColor}22;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.8rem;color:${borderColor};flex-shrink:0">${inicial}</div>
            <div>
              <div style="font-weight:600;font-size:.875rem;display:flex;align-items:center;gap:.35rem">
                ${escHtml(aval.nome||'—')}
                ${temComentario ? '<span title="Tem comentário" style="font-size:.75rem">💬</span>' : ''}
              </div>
              ${comentarioHtml}
            </div>
          </div>
        </td>
        <td style="font-family:monospace;font-size:.84rem;color:var(--text-mid)">${_fmtPhone(aval.telefone||'')}</td>
        <td style="font-size:.84rem">${escHtml(aval.vendedor||'—')}</td>
        <td style="text-align:center">${_starHtml(nota)}</td>
        <td style="font-size:.8rem;color:var(--text-mid);white-space:nowrap">${aval.data||'—'}</td>
      </tr>`;
  }

  function _renderAvalTabela() {
    const PER_PAGE = 20;
    let lista = _avalData.lista || [];

    // Filtro
    if (_avalFiltroNota === 'otimas')   lista = lista.filter(a => (a.nota||0) >= 4);
    else if (_avalFiltroNota === 'regulares') lista = lista.filter(a => (a.nota||0) === 3);
    else if (_avalFiltroNota === 'ruins')     lista = lista.filter(a => (a.nota||0) <= 2);

    const total = lista.length;
    const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
    if (_avalPage > totalPages) _avalPage = totalPages;

    const slice = lista.slice((_avalPage - 1) * PER_PAGE, _avalPage * PER_PAGE);

    const tbody = document.getElementById('avalTbody');
    if (!slice.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:2.5rem;color:var(--text-mid)">Nenhuma avaliação encontrada.</td></tr>`;
    } else {
      tbody.innerHTML = slice.map(_renderAvalRow).join('');
    }

    // Paginação
    const infoEl = document.getElementById('avalPageInfo');
    if (infoEl) infoEl.textContent = total > 0
      ? `Exibindo ${(_avalPage-1)*PER_PAGE+1}–${Math.min(_avalPage*PER_PAGE, total)} de ${total}`
      : 'Nenhum resultado';
    const btnAnt = document.getElementById('avalBtnAnterior');
    const btnPro = document.getElementById('avalBtnProximo');
    if (btnAnt) btnAnt.disabled = _avalPage <= 1;
    if (btnPro) btnPro.disabled = _avalPage >= totalPages;
  }

  function setAvalDias(dias) {
    _avalDias = dias;
    // Atualiza visual dos botões
    [7,30,90].forEach(d => {
      const btn = document.getElementById('avalBtn'+d);
      if (btn) {
        if (d === dias) {
          btn.style.background = 'var(--accent)';
          btn.style.color = '#fff';
        } else {
          btn.style.background = 'transparent';
          btn.style.color = 'var(--text-mid)';
        }
      }
    });
    loadAvaliacoes();
  }

  function setAvalFiltro(filtro) {
    _avalFiltroNota = filtro;
    _avalPage = 1;
    // Visual dos botões de filtro
    ['todas','otimas','regulares','ruins'].forEach(f => {
      const btn = document.getElementById('avalFiltro' + f.charAt(0).toUpperCase() + f.slice(1));
      if (!btn) return;
      if (f === filtro) {
        btn.className = 'btn btn-sm btn-primary';
        btn.style.borderRadius = '16px';
        btn.style.fontSize = '.78rem';
        btn.style.padding = '.3rem .85rem';
      } else {
        btn.className = 'btn btn-sm btn-ghost';
        btn.style.borderRadius = '16px';
        btn.style.fontSize = '.78rem';
        btn.style.padding = '.3rem .85rem';
      }
    });
    _renderAvalTabela();
  }

  function avalMudarPagina(delta) {
    _avalPage += delta;
    _renderAvalTabela();
  }

  // Helper showPage (para navegação programática)
  function showPage(p) {
    // Destrói gráficos do dashboard ao sair da página
    if (typeof _destroyCharts === 'function' && p !== 'dm-dashboard') _destroyCharts();
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelectorAll('.page').forEach(pg => pg.classList.remove('active'));
    const navItem = document.querySelector(`.nav-item[data-page="${p}"]`);
    if (navItem) navItem.classList.add('active');
    const pageEl = document.getElementById('page-' + p);
    if (pageEl) pageEl.classList.add('active');
    _setTopbarPage(p);
    onPageLoad(p);
  }
