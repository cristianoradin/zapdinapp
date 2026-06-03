  // ── Loading overlay ──────────────────────────────────────────────────────────
  let _loadingTimer = null;

  function showLoading(msg) {
    const overlay = document.getElementById('globalLoadingOverlay');
    const msgEl   = document.getElementById('globalLoadingMsg');
    if (!overlay) return;
    if (msgEl) msgEl.textContent = msg || 'Aguarde…';
    overlay.classList.add('visible');
    overlay.removeAttribute('aria-hidden');
  }

  function hideLoading() {
    const overlay = document.getElementById('globalLoadingOverlay');
    if (!overlay) return;
    overlay.classList.remove('visible');
    overlay.setAttribute('aria-hidden', 'true');
  }

  // Expõe globalmente para uso em outros módulos
  window.showLoading = showLoading;
  window.hideLoading = hideLoading;

  // ── Page lazy loader ────────────────────────────────────────────────────────
  const APP_BUILD = '__BUILD__';
  const _loadedPages = new Set();

  async function _loadPage(page) {
    const id = 'page-' + page;
    if (_loadedPages.has(page) || document.getElementById(id)) {
      _loadedPages.add(page);
      return;
    }
    try {
      const r = await fetch(`/static/pages/${page}.html?v=${APP_BUILD}`);
      if (r.ok) {
        const html = await r.text();
        document.querySelector('.content').insertAdjacentHTML('beforeend', html);
        _loadedPages.add(page);
      } else {
        console.warn(`[pages] ${page} not found (${r.status})`);
      }
    } catch (e) {
      console.error(`[pages] Failed to load ${page}:`, e);
    }
  }
  window._loadPage = _loadPage;

  // ── Nav ──────────────────────────────────────────────────────────────────────
  // Nomes devem bater exatamente com os itens do menu lateral
  const pages = {
    home:             'Home',
    dashboard:        'Gestão de Envios',
    home:             'Home',
    dashboard:        'Gestão de Envios',
    arquivo:          'Gestão de Arquivos',
    avaliacoes:       'Gestão de Avaliação',
    mensagem:         'Configurar Mensagem',
    'config-envio':   'Configurações de Envio',
    whatsapp:         'Conectar WhatsApp',
    teste:            'Teste de Envio',
    token:            'Token API',
    docs:             'Documentações',
    telegram:         'Telegram',
    'dm-dashboard':   'Campanhas',
    'dm-contatos':    'Contatos',
    'dm-campanha':    'Criar Campanhas',
    'dm-historico':   'Gerenciar Campanhas',
    'dm-enviadas':    'Campanhas Enviadas',
    'ctb-dashboard':  'Gestão de Documentos',
    'ctb-empresas':   'Cadastro de Empresas',
    'ctb-arquivos':   'Arquivados',
    'sistema':        'Sistema',
    'chatbot':        'Chatbot',
    'ia-central':     'IA Central',
  };
  function _setTopbarPage(p) {
    const label = pages[p] || p;
    // Barra de título compartilhada (nova)
    const bar = document.getElementById('pageTitleText');
    if (bar) bar.textContent = label;
    const titleBar = bar?.closest('.page-title-bar');
    if (titleBar) titleBar.classList.remove('hidden');
    // Legados — null-safe
    const title = document.getElementById('pageTitle');
    if (title) title.textContent = label;
    const el = document.getElementById('pageIcon');
    if (el) el.style.display = 'none';
    // Título da aba do browser
    document.title = 'ZapDin — ' + label;
  }

  // ── Nav toggle ───────────────────────────────────────────────────────────────
  const btnToggleNav = document.getElementById('btnToggleNav');
  if (btnToggleNav) {
    btnToggleNav.addEventListener('click', () => {
      document.getElementById('appRoot')?.classList.toggle('nav-collapsed');
    });
  }

  async function navigate(page) {
    // Só mostra loading se a página ainda não foi carregada (primeiro acesso)
    const isFirstLoad = !_loadedPages.has(page) && !document.getElementById('page-' + page);
    if (isFirstLoad) {
      const label = pages[page] || page;
      showLoading('Carregando ' + label + '…');
    }
    try {
      await _loadPage(page);
    } finally {
      if (isFirstLoad) hideLoading();
    }
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelectorAll('.page').forEach(pg => pg.classList.remove('active'));
    // Marca nav-item normal
    let navItem = document.querySelector(`.nav-item[data-page="${page}"]`);
    // Para sub-páginas (dm-*, ctb-*), destaca o item pai visível do grupo
    if (navItem && navItem.style.display === 'none') {
      // Sub-page: encontra o pai do grupo (primeiro item visível do grupo Campanhas/Contábil)
      const parentMap = {
        'dm-contatos': 'dm-dashboard', 'dm-campanha': 'dm-dashboard',
        'dm-historico': 'dm-dashboard', 'dm-enviadas': 'dm-dashboard',
        'ctb-dashboard': 'ctb-empresas', 'ctb-arquivos': 'ctb-empresas',
      };
      const parentPage = parentMap[page];
      if (parentPage) {
        const parentItem = document.querySelector(`.nav-item[data-page="${parentPage}"]`);
        if (parentItem) navItem = parentItem;
      }
    }
    if (navItem) navItem.classList.add('active');
    // Marca botão IA no topbar quando página ia-central está ativa
    const topbarIaBtn = document.getElementById('topbarIaBtn');
    if (topbarIaBtn) topbarIaBtn.classList.toggle('active', page === 'ia-central');
    const pageEl = document.getElementById('page-' + page);
    if (pageEl) pageEl.classList.add('active');
    _setTopbarPage(page);
    onPageLoad(page);

    // ── Scroll reset ─────────────────────────────────────────────────────────
    // Feito APÓS a transição de páginas (display:none→block recalcula layout),
    // não antes — assim o browser não reposiciona o scroll durante o swap.
    // requestAnimationFrame garante execução depois do próximo paint.
    const _scrollReset = () => {
      const c = document.querySelector('.content');
      if (c) c.scrollTop = 0;
      window.scrollTo({ top: 0, behavior: 'instant' });
    };
    _scrollReset();
    requestAnimationFrame(_scrollReset);
  }

  document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => navigate(item.dataset.page));
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
        pill.classList.add('wa-on'); pill.classList.remove('wa-off');
        txt.textContent = connected === 1 ? '1 número ativo' : `${connected} números ativos`;
        if (banner) banner.classList.remove('visible');
      } else {
        pill.classList.remove('wa-on'); pill.classList.add('wa-off');
        txt.textContent = 'Sem conexão WA';
        if (banner) banner.classList.add('visible');
      }
    } catch { /* silencioso */ }
  }

  // Expõe para módulos externos (ex: whatsapp.js) atualizarem o topbar na hora
  window._updateTopbarStatus = _updateTopbarStatus;

  // ── Status da IA (providers ativos) ─────────────────────────────────────────
  async function _updateAiStatus() {
    const pill = document.getElementById('topbarAiPill');
    const txt  = document.getElementById('topbarAiText');
    if (!pill || !txt) return;
    try {
      const keysRes = await fetch('/api/config/ai-keys');
      if (!keysRes.ok) throw new Error('no keys');
      const keys = await keysRes.json();
      const nomes = { openai: 'OpenAI', gemini: 'Gemini', anthropic: 'Claude', groq: 'Groq' };
      // Providers com chave configurada (uso é configuração interna, não afeta disponibilidade)
      const ativos = ['openai','gemini','anthropic','groq'].filter(
        p => keys[p]?.configurado
      );
      if (ativos.length === 0) {
        pill.classList.remove('active');
        txt.textContent = 'IA sem chave';
      } else {
        pill.classList.add('active');
        txt.textContent = ativos.map(p => nomes[p] || p).join(' + ') + ' ativo';
      }
    } catch {
      pill.classList.remove('active');
      txt.textContent = 'IA —';
    }
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
        // sidebarClientBadge removido — info de licença agora apenas no chip flutuante
      }

      // ── Permissões de menus ──────────────────────────────────────────────────
      // data.menus: null = todos permitidos; array = só esses menus visíveis
      const allowedMenus = Array.isArray(data.menus) ? data.menus : null;
      if (allowedMenus !== null) {
        let firstAllowed = null;

        // 1ª passagem: determina firstAllowed ANTES de esconder qualquer item.
        // (Sem isso, 'home' — primeiro item — sempre encontrava firstAllowed=null
        //  e o redirecionamento nunca disparava.)
        for (const item of document.querySelectorAll('.nav-item[data-page]')) {
          if (allowedMenus.includes(item.dataset.page)) { firstAllowed = item.dataset.page; break; }
        }

        // 2ª passagem: aplica visibilidade
        document.querySelectorAll('.nav-item[data-page]').forEach(item => {
          item.style.display = allowedMenus.includes(item.dataset.page) ? '' : 'none';
        });

        // Ocultar section labels da sidebar que ficaram sem itens visíveis
        document.querySelectorAll('.nav-group-label').forEach(section => {
          let next = section.nextElementSibling;
          let hasVisible = false;
          while (next && !next.classList.contains('nav-group-label')) {
            if (next.classList.contains('nav-item') && next.style.display !== 'none') hasVisible = true;
            next = next.nextElementSibling;
          }
          section.style.display = hasVisible ? '' : 'none';
        });

        // 3ª passagem: redireciona se a página atual não está nas permitidas
        // (feito APÓS o loop para que firstAllowed já esteja calculado)
        const currentPage = document.querySelector('.nav-item.active[data-page]')?.dataset.page;
        if (currentPage && !allowedMenus.includes(currentPage) && firstAllowed) {
          navigate(firstAllowed);
        }

        // ── Sub-menus internos (chatbot e sistema) ─────────────────────────────
        // Chaves compostas: "chatbot:conversas", "sistema:token-ia", etc.
        // Se não há chaves compostas para o módulo → todos os sub-menus visíveis.
        const _mainMenuKeys = allowedMenus.filter(k => !k.includes(':'));

        // Chatbot sub-menus
        if (_mainMenuKeys.includes('chatbot')) {
          const cbSubs = allowedMenus.filter(k => k.startsWith('chatbot:')).map(k => k.split(':')[1]);
          if (cbSubs.length > 0) {
            // Restrição explícita: oculta os não listados
            ['conversas','personalidade','boasvindas','faq','aprendizado','memoria'].forEach(key => {
              const el = document.getElementById('cbMenu-' + key);
              if (el) el.style.display = cbSubs.includes(key) ? '' : 'none';
            });
            // Se o painel ativo ficou oculto, ativa o primeiro visível
            const cbActive = document.querySelector('#page-chatbot .sys-menu-item.active');
            if (cbActive && cbActive.style.display === 'none') {
              const firstCb = document.querySelector('#page-chatbot .sys-menu-item:not([style*="none"])');
              if (firstCb) firstCb.click();
            }
          }
        }

        // Sistema sub-menus
        if (_mainMenuKeys.includes('sistema')) {
          const sysSubs = allowedMenus.filter(k => k.startsWith('sistema:')).map(k => k.split(':')[1]);
          if (sysSubs.length > 0) {
            ['token-ia','usuarios','token','dominio','docs','log'].forEach(key => {
              const el = document.querySelector(`#page-sistema .sys-menu-item[data-panel="${key}"]`);
              if (el) el.style.display = sysSubs.includes(key) ? '' : 'none';
            });
            // Oculta sidebar-section labels que ficaram sem itens
            document.querySelectorAll('#page-sistema .sys-sidebar-section').forEach(section => {
              let next = section.nextElementSibling;
              let hasVisible = false;
              while (next && !next.classList.contains('sys-sidebar-section')) {
                if (next.classList.contains('sys-menu-item') && next.style.display !== 'none') hasVisible = true;
                next = next.nextElementSibling;
              }
              section.style.display = hasVisible ? '' : 'none';
            });
          }
        }
      }
    } catch { window.location.href = '/login'; }
  }

  document.getElementById('btnLogout').addEventListener('click', async () => {
    // Redireciona SEMPRE, mesmo se o servidor não responder (logout client-side garantido)
    try { await fetch('/api/logout', { method: 'POST' }); }
    catch (e) { /* servidor offline — sai mesmo assim */ }
    finally { window.location.href = '/login'; }
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
      btnCancel.style.display = '';
      iconEl.textContent     = icon || _icons[type] || '❓';
      iconWrap.className     = 'confirm-icon-wrap ' + type;
      btnOk.className        = 'confirm-btn confirm-btn-ok ' + type;
      overlay.classList.add('open');
      setTimeout(() => btnCancel.focus(), 50);
      return new Promise(res => { _resolve = res; });
    };

    // Single-button modal (substitui alert() nativo)
    window.showInfo = function(body = '', { title = 'Aviso', okLabel = 'OK', type = 'info', icon = null } = {}) {
      titleEl.textContent    = title;
      bodyEl.textContent     = body;
      btnOk.textContent      = okLabel;
      btnCancel.style.display = 'none';
      iconEl.textContent     = icon || _icons[type] || 'ℹ️';
      iconWrap.className     = 'confirm-icon-wrap ' + type;
      btnOk.className        = 'confirm-btn confirm-btn-ok ' + type;
      overlay.classList.add('open');
      setTimeout(() => btnOk.focus(), 50);
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
  // Expõe api e showAlert globalmente para módulos externos (token.js, telegram.js, etc.)
  window.api = api;

  function showAlert(id, msg, type = 'success') {
    const el = document.getElementById(id);
    el.textContent = msg;
    el.className = `alert alert-${type}`;
    el.style.display = 'block';
    setTimeout(() => el.style.display = 'none', 4000);
  }
  window.showAlert = showAlert;

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
          <div style="width:48px;height:48px;background:var(--primary-soft);border-radius:12px;display:flex;align-items:center;justify-content:center;margin:0 auto .75rem">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--primary-deep)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </div>
          <div style="color:var(--text);font-size:.9rem;font-weight:600;margin-bottom:.3rem">Nenhuma mensagem enviada ainda</div>
          <div style="color:var(--text-2);font-size:.8rem;margin-bottom:1rem">Configure e envie sua primeira mensagem para começar.</div>
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
          <td style="color:var(--text-2);font-size:.8rem">${r.created_at}</td>
        </tr>`).join('');
    } catch(e) { console.error(e); }
  }

  // Mensagem → mensagemModule (js/modules/mensagem.js)

  // WhatsApp Sessions → whatsappModule em js/modules/whatsapp.js

  // WhatsApp Sessions → whatsappModule (removido)


  // Token API + PDV → tokenModule em js/modules/token.js

  // Arquivos → arquivoModule em js/modules/arquivo.js

  // ── Page loader ───────────────────────────────────────────────────────────────
  function onPageLoad(page) {
    if (page === 'home') initHome();
    if (page !== 'whatsapp') whatsappModule.stop();
    if (page !== 'arquivo') arquivoModule.stopTimer();
    if (page !== 'teste' && typeof _pararTestePoll === 'function') _pararTestePoll();
    if (page === 'dashboard') {
      // Módulo dashboard.js (modules/) tem prioridade; loadStats() como fallback legado
      if (window.ZD && ZD.registry._handlers['dashboard']) ZD.registry.dispatch('dashboard');
      else loadStats();
    }
    else if (page === 'mensagem') mensagemModule.init();
    else if (window.ZD && ZD.registry._handlers[page]) ZD.registry.dispatch(page);
    else if (page === 'whatsapp') { whatsappModule.init(); window.initTesteEnvio && window.initTesteEnvio(); }
    else if (page === 'token') tokenModule.init();
    else if (page === 'arquivo') arquivoModule.init();
    else if (page === 'teste') loadTeste();
    else if (page === 'telegram') telegramModule.init();
    else if (page === 'dm-dashboard') window.loadDashboardCampanhas && window.loadDashboardCampanhas();
    else if (page === 'dm-contatos') window.loadContatos && window.loadContatos();
    else if (page === 'dm-campanha') window.initNovaCampanha && window.initNovaCampanha();
    else if (page === 'dm-historico') { window.loadCampanhas && window.loadCampanhas(); window.loadWorkerStatus && window.loadWorkerStatus(); }
    else if (page === 'dm-enviadas') window.loadCampanhasEnviadas && window.loadCampanhasEnviadas();
    else if (page === 'ctb-dashboard') { if (window.ctbDashboard) ctbDashboard.reload(); }
    else if (page === 'ctb-empresas')  { if (window.ctbEmpresas)  ctbEmpresas.carregar(); }
    else if (page === 'ctb-arquivos')  { if (window.ctbArquivos)  ctbArquivos.carregar(); }
    else if (page === 'ia-central') { iaCentral.init(); }
  }

  // Telegram → telegramModule em js/modules/telegram.js

  // ── Init ──────────────────────────────────────────────────────────────────────
  checkAuth().then(async () => {
    await _loadPage('home');
    initHome();
    _updateTopbarStatus();
    _updateAiStatus();
    setInterval(loadStats, 30_000);
    setInterval(_updateTopbarStatus, 30_000);
    setInterval(_updateAiStatus, 60_000); // checa IA a cada 60s
  });

  // Modal Teste de Envio → whatsappModule

  // ── Teste de Envio (página) ───────────────────────────────────────────────────
  var _testePoller = null;

  function _pararTestePoll() {
    if (_testePoller) { clearInterval(_testePoller); _testePoller = null; }
  }

  function _testeResult(elId, type, msg) {
    const el = document.getElementById(elId);
    el.style.display = 'block';
    el.style.background = type === 'ok' ? 'var(--primary-soft)' : type === 'loading' ? 'var(--surface-2)' : 'var(--red-soft)';
    el.style.border = `1px solid ${type === 'ok' ? 'color-mix(in srgb,var(--primary) 35%,transparent)' : type === 'loading' ? 'var(--border)' : 'color-mix(in srgb,var(--red) 30%,transparent)'}`;
    el.style.color = type === 'ok' ? 'var(--primary-deep)' : type === 'loading' ? 'var(--text-2)' : 'var(--red)';
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
      alertEl.style.border = '1px solid color-mix(in srgb,var(--red) 30%,transparent)';
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

  // Teste de Envio integrado em Configurar Mensagem → mensagemModule

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


  // ═══════════════════════════════════════════════════════════════════════════
  //  AVALIAÇÕES
  // ═══════════════════════════════════════════════════════════════════════════






  // Helper showPage (para navegação programática)
  async function showPage(p) {
    await _loadPage(p);
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
