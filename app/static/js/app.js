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
    'ctb-arquivos':   'Gestão de Arquivos',
    'sistema':        'Sistema',
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

  // ── Conector visual + cantos côncavos ────────────────────────────────────────
  function _updateNavConnector(navItem) {
    // ─ Conector: faixa vertical que tapa qualquer gap entre sidebar e conteúdo
    let connector = document.getElementById('nav-connector');
    if (!connector) {
      connector = document.createElement('div');
      connector.id = 'nav-connector';
      document.body.appendChild(connector);
    }

    // ─ Cantos côncavos superiror e inferior (position:fixed → imune a overflow)
    let concTop = document.getElementById('nav-concave-top');
    if (!concTop) {
      concTop = document.createElement('div');
      concTop.id = 'nav-concave-top';
      document.body.appendChild(concTop);
    }
    let concBot = document.getElementById('nav-concave-bot');
    if (!concBot) {
      concBot = document.createElement('div');
      concBot.id = 'nav-concave-bot';
      document.body.appendChild(concBot);
    }

    if (!navItem) {
      connector.style.display = 'none';
      concTop.style.display   = 'none';
      concBot.style.display   = 'none';
      return;
    }

    const rect    = navItem.getBoundingClientRect();
    const sbW     = parseFloat(getComputedStyle(document.documentElement)
                      .getPropertyValue('--sidebar-w')) || 224;

    // Conector: cobre 1-2 px de gap na borda direita da sidebar
    connector.style.cssText = `
      position: fixed;
      left: ${sbW - 2}px;
      top: ${rect.top}px;
      height: ${rect.height}px;
      width: 4px;
      background: var(--bg);
      z-index: 101;
      pointer-events: none;
      display: block;
    `;

    // Canto côncavo superior: 14×14 acima do item, alinhado à borda direita da sidebar
    concTop.style.cssText = `
      position: fixed;
      left: ${sbW - 14}px;
      top: ${rect.top - 14}px;
      width: 14px;
      height: 14px;
      z-index: 101;
      pointer-events: none;
      display: block;
    `;

    // Canto côncavo inferior
    concBot.style.cssText = `
      position: fixed;
      left: ${sbW - 14}px;
      top: ${rect.bottom}px;
      width: 14px;
      height: 14px;
      z-index: 101;
      pointer-events: none;
      display: block;
    `;
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
    const navItem = document.querySelector(`.nav-item[data-page="${page}"]`);
    if (navItem) navItem.classList.add('active');
    // Marca botão IA no topbar quando página ia-central está ativa
    const topbarIaBtn = document.getElementById('topbarIaBtn');
    if (topbarIaBtn) topbarIaBtn.classList.toggle('active', page === 'ia-central');
    const pageEl = document.getElementById('page-' + page);
    if (pageEl) pageEl.classList.add('active');
    _setTopbarPage(page);
    onPageLoad(page);
    // Atualiza conector visual
    _updateNavConnector(navItem || null);

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
        document.querySelectorAll('.sidebar-section').forEach(section => {
          let next = section.nextElementSibling;
          let hasVisible = false;
          while (next && !next.classList.contains('sidebar-section')) {
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
    if (page !== 'teste') _pararTestePoll();
    if (page === 'dashboard') {
      // Módulo dashboard.js (modules/) tem prioridade; loadStats() como fallback legado
      if (window.ZD && ZD.registry._handlers['dashboard']) ZD.registry.dispatch('dashboard');
      else loadStats();
    }
    else if (page === 'mensagem') mensagemModule.init();
    else if (page === 'config-envio') carregarConfigEnvio();
    else if (page === 'whatsapp') whatsappModule.init();
    else if (page === 'token') tokenModule.init();
    else if (page === 'arquivo') arquivoModule.init();
    else if (page === 'teste') loadTeste();
    else if (page === 'telegram') telegramModule.init();
    else if (page === 'sistema') loadSistema();
    else if (page === 'dm-dashboard') loadDashboardCampanhas();
    else if (page === 'dm-contatos') loadContatos();
    else if (page === 'dm-campanha') initNovaCampanha();
    else if (page === 'dm-historico') { loadCampanhas(); loadWorkerStatus(); }
    else if (page === 'dm-enviadas') loadCampanhasEnviadas();
    else if (page === 'avaliacoes') loadAvaliacoes();
    else if (page === 'ctb-dashboard') { if (window.ctbDashboard) ctbDashboard.reload(); }
    else if (page === 'ctb-empresas')  { if (window.ctbEmpresas)  ctbEmpresas.carregar(); }
    else if (page === 'ctb-arquivos')  { if (window.ctbArquivos)  ctbArquivos.carregar(); }
    else if (page === 'chatbot') { chatbot.carregarConversas(); }
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

  // Campanhas DM → campanha.js (js/modules/campanha.js)

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

  // ── Sistema ───────────────────────────────────────────────────────────────────

  async function loadSistema() {
    try {
      const r = await fetch('/api/auth/me');
      if (r.ok) {
        const d = await r.json();
        const el = document.getElementById('sysUserAtual');
        if (el) el.value = d.username || '';
      }
    } catch {}
    await _aiCarregarTodos();
  }

  // ── AI Multi-provider ────────────────────────────────────────────────────────

  async function _aiCarregarTodos() {
    try {
      const r = await fetch('/api/config/ai-keys');
      if (!r.ok) return;
      const d = await r.json();

      // Carrega cada card
      for (const p of ['openai', 'gemini', 'anthropic', 'groq']) {
        const info = d[p] || {};
        const inp  = document.getElementById('aiKey-' + p);
        if (!inp) continue;
        if (info.configurado) {
          inp.value = info.preview || '';
          inp.setAttribute('data-preview', '1');
          _aiSetStatus(p, 'ok', 'Configurada');
        } else {
          inp.value = '';
          inp.setAttribute('data-preview', '0');
          _aiSetStatus(p, 'err', 'Não configurada');
        }
        // Restaura pills de uso
        const uso = info.uso || {};
        // Se chave configurada mas nenhum uso ativo, liga OCR por padrão
        const ocrAtivo  = uso.ocr  === true || (info.configurado && !uso.ocr && !uso.chat);
        const chatAtivo = uso.chat === true;
        _aiSetUsoPill(p, 'ocr',  ocrAtivo);
        _aiSetUsoPill(p, 'chat', chatAtivo);
      }
    } catch {}
  }

  function _aiSetUsoPill(provider, uso, active) {
    const el = document.getElementById('aiUso-' + provider + '-' + uso);
    if (!el) return;
    if (active) el.classList.add('on');
    else        el.classList.remove('on');
  }

  function aiToggleUso(provider, uso) {
    const el = document.getElementById('aiUso-' + provider + '-' + uso);
    if (!el) return;
    el.classList.toggle('on');
  }

  function _aiSetStatus(provider, type, text) {
    const pill = document.getElementById('aiStatus-' + provider);
    const txt  = document.getElementById('aiStatusTxt-' + provider);
    if (!pill || !txt) return;
    pill.className = 'ai-card-status ' + (type === 'ok' ? 'ok' : 'err');
    txt.textContent = text;
  }

  function _aiShowAlert(provider, msg, type) {
    const el = document.getElementById('aiAlert-' + provider);
    if (!el) return;
    el.style.display = 'block';
    el.className = 'ai-card-alert ' + (type === 'err' ? 'err' : 'ok');
    el.textContent = msg;
    setTimeout(() => { el.style.display = 'none'; }, 3500);
  }


  function aiToggleKey(provider) {
    const inp = document.getElementById('aiKey-' + provider);
    if (!inp) return;
    if (inp.getAttribute('data-preview') === '1') {
      inp.value = '';
      inp.setAttribute('data-preview', '0');
      inp.type = 'text';
      inp.focus();
      return;
    }
    inp.type = inp.type === 'password' ? 'text' : 'password';
  }

  async function aiSalvar(provider) {
    const inp = document.getElementById('aiKey-' + provider);
    const key = inp ? inp.value.trim() : '';
    if (!key) { _aiShowAlert(provider, 'Digite a chave.', 'err'); return; }
    const r = await api('POST', '/api/config/ai-key', { provider, key });
    if (r.ok) {
      // Salva também as preferências de uso
      const ocr  = document.getElementById('aiUso-' + provider + '-ocr')?.classList.contains('on')  || false;
      const chat = document.getElementById('aiUso-' + provider + '-chat')?.classList.contains('on') || false;
      await api('POST', '/api/config/ai-uso', { provider, ocr, chat });
      _aiShowAlert(provider, '✓ Chave salva!', 'ok');
      inp.value = key.slice(0, 8) + '...' + key.slice(-4);
      inp.setAttribute('data-preview', '1');
      inp.type = 'password';
      _aiSetStatus(provider, 'ok', 'Configurada');
    } else {
      _aiShowAlert(provider, r.detail || 'Erro ao salvar.', 'err');
    }
  }

  async function aiSalvarUso(provider) {
    const ocr  = document.getElementById('aiUso-' + provider + '-ocr')?.classList.contains('on')  || false;
    const chat = document.getElementById('aiUso-' + provider + '-chat')?.classList.contains('on') || false;
    await api('POST', '/api/config/ai-uso', { provider, ocr, chat });
    _aiShowAlert(provider, '✓ Preferência salva!', 'ok');
  }

  async function aiTestar(provider) {
    _aiSetStatus(provider, '', '⏳ Testando…');
    try {
      const r = await fetch('/api/contabil/ai-status?provider=' + provider);
      if (r.ok) {
        const d = await r.json();
        if (d.ativa) _aiSetStatus(provider, 'ok', 'Conexão OK');
        else _aiSetStatus(provider, 'err', d.motivo || 'Falha');
      } else {
        _aiSetStatus(provider, 'err', 'Erro');
      }
    } catch { _aiSetStatus(provider, 'err', 'Sem resposta'); }
  }

  // ── Chatbot ───────────────────────────────────────────────────────────────────

  function chatbotNav(el, panel) {
    document.querySelectorAll('[id^="cbMenu-"]').forEach(i => i.classList.remove('active'));
    document.querySelectorAll('[id^="cb-panel-"]').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
    const target = document.getElementById('cb-panel-' + panel);
    if (target) target.classList.add('active');
    // Carrega dados do painel ao abrir
    if (panel === 'conversas')   chatbot.carregarConversas();
    if (panel === 'personalidade') chatbot.carregarConfig();
    if (panel === 'boasvindas') chatbot.carregarBoasVindas();
    if (panel === 'faq')         chatbot.carregarFaq();
    if (panel === 'aprendizado') chatbot.carregarAprendizado();
    if (panel === 'memoria') chatbot.carregarMemoria();
  }

  const chatbot = (() => {
    let _phoneAtual       = null;
    let _nomeAtual        = null;
    let _chatbotAtivoAtual = true;
    let _conversasCache   = [];
    let _filtroAprendizado = 'todos';

    // ── Alert helper ─────────────────────────────────────────────────────────
    function _alert(id, msg, tipo) {
      const el = document.getElementById(id);
      if (!el) return;
      el.style.display = 'block';
      el.style.background  = tipo === 'ok' ? '#f0fdf4' : '#fef2f2';
      el.style.color       = tipo === 'ok' ? '#3d7f1f' : '#ef4444';
      el.style.border      = tipo === 'ok' ? '1px solid #bbf7d0' : '1px solid #fecaca';
      el.textContent = msg;
      setTimeout(() => { el.style.display = 'none'; }, 3200);
    }

    // ── Config / Personalidade ────────────────────────────────────────────────
    async function carregarConfig() {
      try {
        const r = await fetch('/api/chatbot/config');
        if (!r.ok) return;
        const d = await r.json();
        const ck = document.getElementById('chatbotAtivo');
        const pr = document.getElementById('chatbotPrompt');
        if (ck) ck.checked = !!d.ativo;
        if (pr) pr.value = d.system_prompt || '';
      } catch {}
    }

    async function salvarConfig() {
      const ativo  = document.getElementById('chatbotAtivo')?.checked ?? true;
      const prompt = document.getElementById('chatbotPrompt')?.value.trim() ?? '';
      try {
        const r = await api('POST', '/api/chatbot/config', { ativo, system_prompt: prompt });
        _alert('chatbotConfigAlert', r.ok ? '✓ Salvo!' : 'Erro ao salvar.', r.ok ? 'ok' : 'err');
      } catch { _alert('chatbotConfigAlert', 'Erro ao salvar.', 'err'); }
    }

    // ── Boas-vindas ───────────────────────────────────────────────────────────
    async function carregarBoasVindas() {
      try {
        const r = await fetch('/api/chatbot/config');
        if (!r.ok) return;
        const d = await r.json();
        const ck  = document.getElementById('chatbotBoasVindasAtivo');
        const txt = document.getElementById('chatbotBoasVindasMsg');
        if (ck)  ck.checked  = !!d.boas_vindas_ativo;
        if (txt) txt.value   = d.boas_vindas_msg || '';
        _atualizarPreview();
      } catch {}
    }

    function _atualizarPreview() {
      const txt = document.getElementById('chatbotBoasVindasMsg')?.value || '';
      const prev = document.getElementById('chatbotBoasVindasPreview');
      if (prev) prev.textContent = txt.replace('{nome}', 'João Silva');
    }

    async function salvarBoasVindas() {
      const ativo = document.getElementById('chatbotBoasVindasAtivo')?.checked ?? false;
      const msg   = document.getElementById('chatbotBoasVindasMsg')?.value.trim() ?? '';
      try {
        const r = await api('POST', '/api/chatbot/boas-vindas', { ativo, msg });
        _alert('chatbotBoasVindasAlert', r.ok ? '✓ Salvo!' : 'Erro ao salvar.', r.ok ? 'ok' : 'err');
      } catch { _alert('chatbotBoasVindasAlert', 'Erro ao salvar.', 'err'); }
    }

    // ── FAQ ───────────────────────────────────────────────────────────────────
    async function carregarFaq() {
      const el = document.getElementById('faqLista');
      if (!el) return;
      try {
        const r = await fetch('/api/chatbot/faq');
        if (!r.ok) { el.innerHTML = '<div style="color:#ef4444;font-size:.8rem">Erro ao carregar.</div>'; return; }
        const lista = await r.json();
        if (!lista.length) {
          el.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-muted);font-size:.82rem">Nenhuma pergunta cadastrada ainda</div>';
          return;
        }
        el.innerHTML = lista.map(f => `
          <div style="border:1px solid var(--border);border-radius:10px;padding:.8rem 1rem;background:var(--surface2)">
            <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:.5rem">
              <div style="flex:1;min-width:0">
                <div style="font-size:.8rem;font-weight:600;color:var(--text);margin-bottom:.3rem">❓ ${f.pergunta}</div>
                <div style="font-size:.78rem;color:var(--text-muted);line-height:1.5">💬 ${f.resposta}</div>
              </div>
              <button onclick="chatbot.removerFaq(${f.id})" style="background:none;border:none;cursor:pointer;color:#9ca3af;padding:.2rem;flex-shrink:0" title="Remover">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
              </button>
            </div>
          </div>`).join('');
      } catch { el.innerHTML = '<div style="color:#ef4444;font-size:.8rem">Erro ao carregar.</div>'; }
    }

    async function adicionarFaq() {
      const pergunta = document.getElementById('faqPergunta')?.value.trim();
      const resposta = document.getElementById('faqResposta')?.value.trim();
      if (!pergunta || !resposta) { _alert('faqAlert', 'Preencha pergunta e resposta.', 'err'); return; }
      const r = await api('POST', '/api/chatbot/faq', { pergunta, resposta });
      if (r.ok) {
        document.getElementById('faqPergunta').value = '';
        document.getElementById('faqResposta').value = '';
        _alert('faqAlert', '✓ Pergunta adicionada!', 'ok');
        await carregarFaq();
      } else {
        _alert('faqAlert', 'Erro ao adicionar.', 'err');
      }
    }

    async function removerFaq(id) {
      if (!confirm('Remover esta pergunta?')) return;
      await api('DELETE', '/api/chatbot/faq/' + id);
      await carregarFaq();
    }

    // ── Aprendizado ───────────────────────────────────────────────────────────
    async function carregarAprendizado() {
      const el = document.getElementById('aprendizadoLista');
      if (!el) return;
      el.innerHTML = '<div style="text-align:center;padding:1.5rem;color:var(--text-muted)">Carregando…</div>';
      try {
        const url = '/api/chatbot/aprendizado' + (_filtroAprendizado !== 'todos' ? '?filtro=' + _filtroAprendizado : '');
        const r = await fetch(url);
        if (!r.ok) { el.innerHTML = '<div style="color:#ef4444;font-size:.8rem">Erro ao carregar.</div>'; return; }
        const lista = await r.json();
        if (!lista.length) {
          el.innerHTML = '<div style="text-align:center;padding:2.5rem;color:var(--text-muted);font-size:.82rem">Nenhum item para revisar</div>';
          return;
        }
        el.innerHTML = lista.map(item => {
          const aprovado = item.aprovado === true;
          const rejeitado = item.aprovado === false;
          const badge = aprovado
            ? '<span style="background:#f0fdf4;color:#3d7f1f;border:1px solid #bbf7d0;border-radius:20px;font-size:.65rem;font-weight:700;padding:.15rem .5rem">✅ Aprovado</span>'
            : rejeitado
            ? '<span style="background:#fef2f2;color:#ef4444;border:1px solid #fecaca;border-radius:20px;font-size:.65rem;font-weight:700;padding:.15rem .5rem">👎 Rejeitado</span>'
            : '<span style="background:#fffbeb;color:#d97706;border:1px solid #fde68a;border-radius:20px;font-size:.65rem;font-weight:700;padding:.15rem .5rem">⏳ Pendente</span>';
          return `<div style="border:1px solid var(--border);border-radius:10px;padding:.85rem 1rem;background:var(--surface2)">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.5rem">
              <div style="font-size:.72rem;color:var(--text-muted)">${item.phone} · ${item.created_at ? new Date(item.created_at).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : ''}</div>
              ${badge}
            </div>
            <div style="margin-bottom:.3rem"><span style="font-size:.72rem;font-weight:700;color:#6b7280">Cliente:</span> <span style="font-size:.8rem;color:var(--text)">${item.pergunta}</span></div>
            <div style="margin-bottom:.65rem"><span style="font-size:.72rem;font-weight:700;color:#8b5cf6">Bot:</span> <span style="font-size:.8rem;color:var(--text)">${item.resposta}</span></div>
            <div style="display:flex;gap:.4rem;flex-wrap:wrap">
              ${!aprovado ? `<button class="btn btn-sm" onclick="chatbot.avaliarAprendizado(${item.id},true)" style="background:#f0fdf4;color:#3d7f1f;border:1px solid #bbf7d0;font-size:.72rem">👍 Aprovar</button>` : ''}
              ${!rejeitado ? `<button class="btn btn-sm" onclick="chatbot.avaliarAprendizado(${item.id},false)" style="background:#fef2f2;color:#ef4444;border:1px solid #fecaca;font-size:.72rem">👎 Rejeitar</button>` : ''}
              <button class="btn btn-ghost btn-sm" onclick="chatbot.removerAprendizado(${item.id})" style="font-size:.72rem">🗑 Remover</button>
            </div>
          </div>`;
        }).join('');
      } catch { el.innerHTML = '<div style="color:#ef4444;font-size:.8rem">Erro ao carregar.</div>'; }
    }

    function filtrarAprendizado(filtro) {
      _filtroAprendizado = filtro;
      // Atualiza botões de filtro
      ['todos','aprovados','pendentes'].forEach(f => {
        const btn = document.getElementById('aprendFiltro' + f.charAt(0).toUpperCase() + f.slice(1));
        if (!btn) return;
        if (f === filtro) { btn.style.background = 'var(--accent)'; btn.style.color = '#fff'; btn.style.border = 'none'; }
        else { btn.style.background = 'transparent'; btn.style.color = 'var(--text-mid)'; btn.style.border = '1px solid var(--border)'; }
      });
      carregarAprendizado();
    }

    async function avaliarAprendizado(id, aprovado) {
      await api('PATCH', '/api/chatbot/aprendizado/' + id, { aprovado });
      await carregarAprendizado();
    }

    async function removerAprendizado(id) {
      await api('DELETE', '/api/chatbot/aprendizado/' + id);
      await carregarAprendizado();
    }

    // ── Helpers de avatar ─────────────────────────────────────────────────────
    function _initials(nome) {
      if (!nome) return '?';
      const parts = nome.trim().split(/\s+/);
      if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
      return parts[0].slice(0, 2).toUpperCase();
    }

    // ── Conversas — lista ─────────────────────────────────────────────────────
    async function carregarConversas() {
      const el = document.getElementById('chatbotConversasList');
      if (!el) return;
      // Event delegation — registra UMA vez no container
      if (!el._cbDelegated) {
        el._cbDelegated = true;
        el.addEventListener('click', function(ev) {
          const card = ev.target.closest('.cb-wa-contact');
          if (!card) return;
          const phone = card.dataset.phone;
          const nome  = card.dataset.nome  || '';
          const ativo = card.dataset.ativo !== '0';
          abrirConversa(phone, nome, ativo);
        });
      }
      el.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-mid);font-size:.8rem">Carregando…</div>';
      try {
        const r = await fetch('/api/chatbot/conversas');
        if (!r.ok) throw new Error('status ' + r.status);
        _conversasCache = await r.json();
        _renderContatos(_conversasCache);
      } catch(e) {
        el.innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:2.5rem 1rem;gap:.75rem;text-align:center">
        <div style="width:44px;height:44px;border-radius:50%;background:#fef2f2;display:flex;align-items:center;justify-content:center">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        </div>
        <div>
          <div style="font-size:.82rem;font-weight:600;color:#dc2626;margin-bottom:.2rem">Erro ao carregar</div>
          <div style="font-size:.72rem;color:var(--text-mid)">Verifique sua conexão</div>
        </div>
        <button onclick="chatbot.carregarConversas()" style="display:inline-flex;align-items:center;gap:.35rem;padding:.4rem .9rem;border-radius:20px;border:1px solid #fecaca;background:#fef2f2;color:#dc2626;font-size:.75rem;cursor:pointer;font-weight:600">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          Tentar novamente
        </button>
      </div>`;
        console.error('[chatbot] carregarConversas:', e);
      }
    }

    function _renderContatos(lista) {
      const el = document.getElementById('chatbotConversasList');
      if (!el) return;
      if (!lista.length) {
        el.innerHTML = '<div style="text-align:center;padding:3rem 1rem;color:var(--text-mid);font-size:.8rem">Nenhuma conversa ainda</div>';
        return;
      }
      el.innerHTML = lista.map(c => {
        const dt  = c.ultima_msg ? new Date(c.ultima_msg).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
        const nm  = c.nome || c.phone || '';
        const ini = _initials(nm);
        const pausado = c.chatbot_ativo === false;
        const isAtivo = c.phone === _phoneAtual;
        return `<div class="cb-wa-contact${isAtivo ? ' active' : ''}" id="cbContact-${CSS.escape(c.phone)}"
            data-phone="${c.phone.replace(/"/g,'&quot;')}" data-nome="${nm.replace(/"/g,'&quot;')}" data-ativo="${c.chatbot_ativo ? '1' : '0'}">
          <div class="cb-wa-avatar" style="${pausado ? 'background:linear-gradient(135deg,#9ca3af,#6b7280)' : ''}">${ini}</div>
          <div class="cb-wa-contact-info">
            <div class="cb-wa-contact-name">${nm}</div>
            <div class="cb-wa-contact-preview">${c.ultima_preview || '...'}</div>
          </div>
          <div class="cb-wa-contact-meta">
            <div class="cb-wa-contact-time">${dt}</div>
            ${pausado ? '<div class="cb-wa-paused-badge">⏸ Pausado</div>' : ''}
          </div>
        </div>`;
      }).join('');
    }

    function filtrarContatos(q) {
      if (!q.trim()) { _renderContatos(_conversasCache); return; }
      const ql = q.toLowerCase();
      _renderContatos(_conversasCache.filter(c =>
        (c.nome || '').toLowerCase().includes(ql) ||
        (c.phone || '').includes(ql)
      ));
    }

    // ── Conversas — abrir ─────────────────────────────────────────────────────
    async function abrirConversa(phone, nome, chatbotAtivo = true) {
      _phoneAtual        = phone;
      _nomeAtual         = nome;
      _chatbotAtivoAtual = chatbotAtivo;

      // Destaca na lista
      document.querySelectorAll('.cb-wa-contact').forEach(el => el.classList.remove('active'));
      const item = document.getElementById('cbContact-' + CSS.escape(phone));
      if (item) item.classList.add('active');

      // Atualiza header
      const header  = document.getElementById('cbChatHeader');
      const vazio   = document.getElementById('cbChatVazio');
      const msgsEl  = document.getElementById('cbChatMsgs');
      const inputEl = document.getElementById('cbChatInput');
      if (!header) return;

      document.getElementById('cbChatNome').textContent  = nome || phone;
      document.getElementById('cbChatPhone').textContent = phone;
      document.getElementById('cbChatAvatar').textContent = _initials(nome || phone);

      _updatePausarToggle();

      header.style.display  = 'flex';
      vazio.style.display   = 'none';
      msgsEl.style.display  = 'flex';
      inputEl.style.display = 'flex';
      msgsEl.innerHTML = '<div style="text-align:center;padding:1.5rem;color:var(--text-mid);font-size:.8rem">Carregando…</div>';

      try {
        const r = await fetch('/api/chatbot/historico/' + encodeURIComponent(phone));
        if (!r.ok) throw new Error('status ' + r.status);
        const msgs = await r.json();
        if (!msgs.length) {
          msgsEl.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-mid);font-size:.8rem">Sem mensagens nesta conversa</div>';
          return;
        }
        msgsEl.innerHTML = msgs.map(m => {
          const isBot = m.role === 'assistant';
          const dt = m.created_at ? new Date(m.created_at).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '';
          return `<div class="cb-bubble-wrap-${isBot ? 'bot' : 'user'}">
            <div class="cb-bubble cb-bubble-${isBot ? 'bot' : 'user'}">
              <span class="cb-bubble-label ${isBot ? 'bot' : 'user'}">${isBot ? '🤖 Bot' : '👤 Cliente'}</span>
              ${_escHtml(m.conteudo)}
              <span class="cb-bubble-time">${dt}</span>
            </div>
          </div>`;
        }).join('');
        msgsEl.scrollTop = msgsEl.scrollHeight;
      } catch(e) {
        msgsEl.innerHTML = '<div style="text-align:center;padding:1rem;color:#ef4444;font-size:.8rem">Erro ao carregar histórico.</div>';
        console.error('[chatbot] abrirConversa:', e);
      }
    }

    function _escHtml(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    }

    function _updatePausarToggle() {
      const btn   = document.getElementById('cbPausarToggle');
      const label = document.getElementById('cbPausarLabel');
      if (!btn) return;
      if (_chatbotAtivoAtual) {
        btn.classList.remove('pausado');
        if (label) label.textContent = 'Bot ativo';
      } else {
        btn.classList.add('pausado');
        if (label) label.textContent = 'Bot pausado';
      }
    }

    async function toggleChatbotAtivo() {
      if (!_phoneAtual) return;
      _chatbotAtivoAtual = !_chatbotAtivoAtual;
      _updatePausarToggle();
      // Atualiza badge na lista
      const item = document.getElementById('cbContact-' + CSS.escape(_phoneAtual));
      if (item) {
        const badge = item.querySelector('.cb-wa-paused-badge');
        if (_chatbotAtivoAtual && badge) badge.remove();
        else if (!_chatbotAtivoAtual && !badge) {
          const meta = item.querySelector('.cb-wa-contact-meta');
          if (meta) meta.insertAdjacentHTML('beforeend','<div class="cb-wa-paused-badge">⏸ Pausado</div>');
        }
        const av = item.querySelector('.cb-wa-avatar');
        if (av) av.style.background = _chatbotAtivoAtual ? '' : 'linear-gradient(135deg,#9ca3af,#6b7280)';
      }
      // Também atualiza cache
      const cached = _conversasCache.find(c => c.phone === _phoneAtual);
      if (cached) cached.chatbot_ativo = _chatbotAtivoAtual;
      try {
        const phoneLocal = _phoneAtual.replace('@s.whatsapp.net','').replace('@lid','').replace(/^55/,'');
        await api('PATCH', '/api/chatbot/contato/' + encodeURIComponent(phoneLocal) + '/chatbot-ativo',
          { chatbot_ativo: _chatbotAtivoAtual });
      } catch(e) { console.error('[chatbot] toggleChatbotAtivo:', e); }
    }

    // ── Envio manual ──────────────────────────────────────────────────────────
    async function enviarMensagem() {
      if (!_phoneAtual) return;
      const ta = document.getElementById('cbMsgTexto');
      const texto = (ta?.value || '').trim();
      if (!texto) return;

      const msgsEl = document.getElementById('cbChatMsgs');
      const agora  = new Date().toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});

      // Limpa campo antes de aguardar resposta
      ta.value = '';
      ta.style.height = 'auto';

      try {
        const res = await api('POST', '/api/chatbot/enviar', { phone: _phoneAtual, mensagem: texto });
        if (!res.ok || res._status >= 400) {
          // Mostra erro sem adicionar bolha fantasma
          msgsEl.insertAdjacentHTML('beforeend', `
            <div style="text-align:center;padding:.5rem 1rem">
              <span style="font-size:.75rem;color:#ef4444;background:#fef2f2;padding:.25rem .7rem;border-radius:20px">
                ⚠️ Falha ao enviar: ${res.detail || 'erro desconhecido'}
              </span>
            </div>`);
          msgsEl.scrollTop = msgsEl.scrollHeight;
          // Restaura o texto no campo para o usuário tentar novamente
          ta.value = texto;
          return;
        }
        // Adiciona bolha apenas se o envio foi confirmado
        msgsEl.insertAdjacentHTML('beforeend', `
          <div class="cb-bubble-wrap-bot">
            <div class="cb-bubble cb-bubble-bot">
              <span class="cb-bubble-label bot">🖊 Manual</span>
              ${_escHtml(texto)}
              <span class="cb-bubble-time">${agora}</span>
            </div>
          </div>`);
        msgsEl.scrollTop = msgsEl.scrollHeight;
      } catch(e) {
        console.error('[chatbot] enviarMensagem:', e);
        ta.value = texto; // restaura texto
      }
    }

    async function limparHistorico() {
      if (!_phoneAtual) return;
      if (!confirm('Apagar todo o histórico de ' + (_nomeAtual || _phoneAtual) + '?')) return;
      await api('DELETE', `/api/chatbot/historico/${encodeURIComponent(_phoneAtual)}`);
      // Reseta painel
      document.getElementById('cbChatHeader').style.display  = 'none';
      document.getElementById('cbChatMsgs').style.display    = 'none';
      document.getElementById('cbChatInput').style.display   = 'none';
      document.getElementById('cbChatVazio').style.display   = 'flex';
      _phoneAtual = null;
      await carregarConversas();
    }

    // Adiciona listener para preview de boas-vindas em tempo real
    document.addEventListener('input', e => {
      if (e.target && e.target.id === 'chatbotBoasVindasMsg') _atualizarPreview();
    });

    // ── Memória IA ────────────────────────────────────────────────────────────
    let _memoriaFiltro = '';

    async function carregarMemoria() {
      // Carrega stats
      const stats = await api('GET', '/api/chatbot/memoria-ia/stats');
      const statsEl = document.getElementById('memoriaIaStats');
      if (statsEl && stats._status === 200) {
        statsEl.innerHTML = `
          <span class="mem-stat-chip" style="background:#f0fdf4;color:#166534">✅ ${stats.aprovadas} aprovadas</span>
          <span class="mem-stat-chip" style="background:#fefce8;color:#854d0e">⏳ ${stats.pendentes} pendentes</span>
          <span class="mem-stat-chip" style="background:#fef2f2;color:#991b1b">❌ ${stats.rejeitadas} rejeitadas</span>
          <span class="mem-stat-chip" style="background:#f5f3ff;color:#5b21b6">🔄 ${stats.total_usos} usos totais</span>`;
      }
      // Carrega config (memoria_ia_ativa)
      const cfg = await api('GET', '/api/chatbot/config');
      const chk = document.getElementById('memoriaIaAtiva');
      if (chk && cfg) chk.checked = cfg.memoria_ia_ativa !== false;
      // Carrega lista
      await _renderMemoria(_memoriaFiltro);
    }

    async function _renderMemoria(filtro) {
      const el = document.getElementById('memoriaIaLista');
      if (!el) return;
      el.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-mid);font-size:.8rem">Carregando…</div>';
      const url = '/api/chatbot/memoria-ia' + (filtro ? '?filtro=' + filtro : '');
      const r = await api('GET', url);
      if (!r || r._status >= 400 || !Array.isArray(r)) {
        el.innerHTML = '<div style="text-align:center;padding:2rem;color:#ef4444;font-size:.8rem">Erro ao carregar</div>';
        return;
      }
      if (!r.length) {
        el.innerHTML = '<div style="text-align:center;padding:3rem 1rem;color:var(--text-mid);font-size:.8rem">' +
          (filtro ? 'Nenhuma entrada ' + filtro : 'Nenhuma entrada ainda — a IA vai alimentar esta base automaticamente') + '</div>';
        return;
      }
      el.innerHTML = r.map(m => {
        const vars = (() => { try { return JSON.parse(m.variacoes || '[]'); } catch { return []; } })();
        const statusBadge = m.aprovado === true ? '<span class="mem-badge mem-badge-aprovado">✅ Aprovada</span>'
          : m.aprovado === false ? '<span class="mem-badge mem-badge-rejeitado">❌ Rejeitada</span>'
          : '<span class="mem-badge mem-badge-pendente">⏳ Pendente</span>';
        const fonteBadge = `<span class="mem-badge mem-badge-${m.fonte || 'ia'}">${m.fonte === 'manual' ? '✏️ Manual' : '🤖 IA'}</span>`;
        return `<div class="mem-card" id="mem-card-${m.id}">
          <div class="mem-card-header">
            <span class="mem-intencao">${_escHtml(m.intencao)}</span>
            ${statusBadge} ${fonteBadge}
            <span style="margin-left:auto;font-size:.68rem;color:var(--text-light)">${m.usos} uso${m.usos !== 1 ? 's' : ''}</span>
          </div>
          <div class="mem-confianca-bar"><div class="mem-confianca-fill" style="width:${m.confianca || 0}%"></div></div>
          ${vars.length ? `<div class="mem-variacoes">📌 ${vars.slice(0,4).map(v => _escHtml(v)).join(' &nbsp;·&nbsp; ')}</div>` : ''}
          <div class="mem-resposta">${_escHtml(m.resposta_ideal)}</div>
          <div class="mem-actions">
            ${m.aprovado !== true  ? `<button class="btn btn-sm" style="background:#dcfce7;color:#166534;border:none" onclick="chatbot.aprovarMemoria(${m.id},true)">✅ Aprovar</button>` : ''}
            ${m.aprovado !== false ? `<button class="btn btn-sm" style="background:#fee2e2;color:#991b1b;border:none" onclick="chatbot.aprovarMemoria(${m.id},false)">❌ Rejeitar</button>` : ''}
            <button class="btn btn-sm btn-ghost" onclick="chatbot.editarMemoria(${m.id})">✏️ Editar</button>
            <button class="btn btn-sm btn-ghost" style="color:#ef4444" onclick="chatbot.deletarMemoria(${m.id})">🗑</button>
          </div>
        </div>`;
      }).join('');
    }

    async function filtrarMemoria(btn, filtro) {
      _memoriaFiltro = filtro;
      document.querySelectorAll('.mem-filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      await _renderMemoria(filtro);
    }

    async function aprovarMemoria(id, aprovado) {
      await api('PATCH', `/api/chatbot/memoria-ia/${id}/aprovar`, { aprovado });
      await carregarMemoria();
    }

    async function deletarMemoria(id) {
      if (!confirm('Apagar esta entrada da memória?')) return;
      await api('DELETE', `/api/chatbot/memoria-ia/${id}`);
      await carregarMemoria();
    }

    function editarMemoria(id) {
      const card = document.getElementById('mem-card-' + id);
      if (!card) return;
      const intencaoEl  = card.querySelector('.mem-intencao');
      const respostaEl  = card.querySelector('.mem-resposta');
      const actionsEl   = card.querySelector('.mem-actions');
      const intAtual    = intencaoEl.textContent.trim();
      const respAtual   = respostaEl.textContent.trim();
      actionsEl.innerHTML = `
        <div style="width:100%;display:flex;flex-direction:column;gap:.5rem">
          <input id="memEditInt-${id}" value="${intAtual.replace(/"/g,'&quot;')}" placeholder="Intenção"
            style="padding:.4rem .65rem;border:1px solid var(--border);border-radius:7px;font-size:.8rem;font-family:monospace;width:100%">
          <textarea id="memEditResp-${id}" rows="4"
            style="padding:.4rem .65rem;border:1px solid var(--border);border-radius:7px;font-size:.8rem;resize:vertical;width:100%;font-family:inherit">${respAtual}</textarea>
          <div style="display:flex;gap:.4rem">
            <button class="btn btn-sm btn-primary" onclick="chatbot._salvarEdicaoMemoria(${id})">Salvar</button>
            <button class="btn btn-sm btn-ghost" onclick="chatbot.carregarMemoria()">Cancelar</button>
          </div>
        </div>`;
    }

    async function _salvarEdicaoMemoria(id) {
      const intVal  = document.getElementById('memEditInt-'  + id)?.value.trim() || '';
      const respVal = document.getElementById('memEditResp-' + id)?.value.trim() || '';
      if (!intVal || !respVal) return;
      await api('PATCH', `/api/chatbot/memoria-ia/${id}`, {
        intencao: intVal, variacoes: '[]', resposta_ideal: respVal, aprovado: null
      });
      await carregarMemoria();
    }

    async function abrirNovaMemoria() {
      const el = document.getElementById('memoriaIaLista');
      if (!el) return;
      const formHtml = `<div class="mem-card" style="border-color:var(--accent)">
        <div style="font-size:.82rem;font-weight:700;color:var(--text);margin-bottom:.75rem">Nova entrada manual</div>
        <div style="display:flex;flex-direction:column;gap:.5rem">
          <input id="memNovaInt" placeholder="Intenção (ex: consulta_preco)"
            style="padding:.4rem .65rem;border:1px solid var(--border);border-radius:7px;font-size:.8rem;font-family:monospace">
          <textarea id="memNovaResp" rows="3" placeholder="Resposta ideal para esta intenção"
            style="padding:.4rem .65rem;border:1px solid var(--border);border-radius:7px;font-size:.8rem;resize:vertical;font-family:inherit"></textarea>
          <div style="display:flex;gap:.4rem">
            <button class="btn btn-sm btn-primary" onclick="chatbot._salvarNovaMemoria()">Salvar</button>
            <button class="btn btn-sm btn-ghost" onclick="chatbot.carregarMemoria()">Cancelar</button>
          </div>
        </div>
      </div>`;
      el.insertAdjacentHTML('afterbegin', formHtml);
      document.getElementById('memNovaInt')?.focus();
    }

    async function _salvarNovaMemoria() {
      const intVal  = document.getElementById('memNovaInt')?.value.trim() || '';
      const respVal = document.getElementById('memNovaResp')?.value.trim() || '';
      if (!intVal || !respVal) return;
      await api('POST', '/api/chatbot/memoria-ia', {
        intencao: intVal, variacoes: '[]', resposta_ideal: respVal, aprovado: true
      });
      await carregarMemoria();
    }

    async function toggleMemoriaIaAtiva(ativo) {
      await api('POST', '/api/chatbot/config/memoria-ia-ativa', { memoria_ia_ativa: ativo });
    }

    return {
      carregarConfig, salvarConfig,
      carregarBoasVindas, salvarBoasVindas,
      carregarFaq, adicionarFaq, removerFaq,
      carregarAprendizado, filtrarAprendizado, avaliarAprendizado, removerAprendizado,
      carregarConversas, filtrarContatos, abrirConversa,
      toggleChatbotAtivo, enviarMensagem, limparHistorico,
      carregarMemoria, filtrarMemoria, aprovarMemoria, deletarMemoria,
      editarMemoria, _salvarEdicaoMemoria, abrirNovaMemoria, _salvarNovaMemoria,
      toggleMemoriaIaAtiva,
    };
  })();
  window.chatbot = chatbot;


  // ── Sistema — navegação interna ───────────────────────────────────────────────

  function sysNav(el, panel) {
    // Move painéis avulsos para dentro do sys-content na primeira chamada
    const sysContent = document.querySelector('#page-sistema .sys-content');
    const target = document.getElementById('sys-panel-' + panel);
    if (target && sysContent && !sysContent.contains(target)) {
      sysContent.appendChild(target);
    }
    document.querySelectorAll('.sys-menu-item').forEach(i => i.classList.remove('active'));
    document.querySelectorAll('.sys-panel').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
    if (target) target.classList.add('active');
    if (panel === 'dominio' && window.dominio) dominio.carregar();
    if (panel === 'log' && window.syslog) syslog.carregar(true);
    if (panel === 'token' && window.tokenModule) tokenModule.init();
    // Dispara evento para módulos externos (ex: usuarios.js)
    document.dispatchEvent(new CustomEvent('sys-panel-activated', { detail: panel }));
  }

  // ── Usuário ──────────────────────────────────────────────────────────────────

  async function salvarUsuario() {
    const senhaAtual  = document.getElementById('sysUserSenhaAtual')?.value.trim() || '';
    const novoUser    = document.getElementById('sysUserNovo')?.value.trim() || '';
    const senhaNova   = document.getElementById('sysUserSenhaNova')?.value.trim() || '';
    const senhaConf   = document.getElementById('sysUserSenhaConf')?.value.trim() || '';

    if (!senhaAtual) { showAlert('alertSysUsuario', 'Informe a senha atual.', 'error'); return; }
    if (senhaNova && senhaNova !== senhaConf) { showAlert('alertSysUsuario', 'As senhas novas não coincidem.', 'error'); return; }

    const r = await api('PUT', '/api/auth/usuario', {
      senha_atual: senhaAtual,
      novo_username: novoUser,
      nova_senha: senhaNova,
      confirmar_senha: senhaConf,
    });

    if (r.ok) {
      showAlert('alertSysUsuario', 'Usuário atualizado com sucesso!');
      if (r.username) {
        const el = document.getElementById('sysUserAtual');
        if (el) el.value = r.username;
      }
      document.getElementById('sysUserNovo').value = '';
      document.getElementById('sysUserSenhaAtual').value = '';
      document.getElementById('sysUserSenhaNova').value = '';
      document.getElementById('sysUserSenhaConf').value = '';
    } else {
      showAlert('alertSysUsuario', r.detail || 'Erro ao salvar.', 'error');
    }
  }

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
    _updateNavConnector(navItem || null);
  }
