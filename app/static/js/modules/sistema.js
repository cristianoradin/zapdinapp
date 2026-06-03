/**
 * modules/sistema.js — Página Sistema: IA config, usuário, navegação.
 * Extraído de app.js em 2026-05.
 * Registra: ZD.registry.register('sistema', loadSistema)
 */
(function () {
  'use strict';

  // ── Sistema — navegação interna ─────────────────────────────────────────────

  // Navega pra page-sistema e ativa um painel específico (usado pelo topnav fora do sistema)
  window.sysGoTo = async function sysGoTo(panel) {
    if (panel === 'token') {
      window.navigate('token');
      return;
    }
    await window.navigate('sistema');
    // espera DOM carregar e tab existir
    const el = document.querySelector(`#page-sistema .sys-tab[data-panel="${panel}"]`);
    if (el && typeof window.sysNav === 'function') window.sysNav(el, panel);
  };

  window.sysNav = function sysNav(el, panel) {
    const page = document.getElementById('page-sistema');
    const sysContent = page ? page.querySelector('.sys-content') : null;
    const target = document.getElementById('sys-panel-' + panel);
    if (target && sysContent && !sysContent.contains(target)) {
      sysContent.appendChild(target);
    }
    // Escopa ao #page-sistema — não interfere nos menus/painéis do Chatbot
    const scope = page || document;
    scope.querySelectorAll('.sys-menu-item').forEach(i => { i.classList.remove('active'); i.classList.remove('on'); });
    scope.querySelectorAll('.sys-panel').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
    el.classList.add('on');
    if (target) target.classList.add('active');
    if (panel === 'dominio' && window.dominio) dominio.carregar();
    if (panel === 'log' && window.syslog)    syslog.carregar(true);
    if (panel === 'token' && window.tokenModule) tokenModule.init();
    // ── Configurações do Chatbot (movidas pra cá) — dispara loaders ──
    if (window.chatbot) {
      if (panel === 'cb-personalidade') chatbot.carregarConfig();
      if (panel === 'cb-boasvindas')    chatbot.carregarBoasVindas();
      if (panel === 'cb-faq')           chatbot.carregarFaq();
      if (panel === 'cb-aprendizado')   chatbot.carregarAprendizado();
      if (panel === 'cb-memoria')       chatbot.carregarMemoria();
    }
    document.dispatchEvent(new CustomEvent('sys-panel-activated', { detail: panel }));
  };

  // ── Usuário ─────────────────────────────────────────────────────────────────

  window.salvarUsuario = async function salvarUsuario() {
    const senhaAtual = document.getElementById('sysUserSenhaAtual')?.value.trim() || '';
    const novoUser   = document.getElementById('sysUserNovo')?.value.trim()       || '';
    const senhaNova  = document.getElementById('sysUserSenhaNova')?.value.trim()  || '';
    const senhaConf  = document.getElementById('sysUserSenhaConf')?.value.trim()  || '';

    if (!senhaAtual) { showAlert('alertSysUsuario', 'Informe a senha atual.', 'error'); return; }
    if (senhaNova && senhaNova !== senhaConf) {
      showAlert('alertSysUsuario', 'As senhas novas não coincidem.', 'error'); return;
    }
    const r = await api('PUT', '/api/auth/usuario', {
      senha_atual: senhaAtual, novo_username: novoUser,
      nova_senha: senhaNova,  confirmar_senha: senhaConf,
    });
    if (r.ok) {
      showAlert('alertSysUsuario', 'Usuário atualizado com sucesso!');
      if (r.username) {
        const el = document.getElementById('sysUserAtual');
        if (el) el.value = r.username;
      }
      ['sysUserNovo','sysUserSenhaAtual','sysUserSenhaNova','sysUserSenhaConf']
        .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    } else {
      showAlert('alertSysUsuario', r.detail || 'Erro ao salvar.', 'error');
    }
  };

  // ── AI Multi-provider ────────────────────────────────────────────────────────

  async function _aiCarregarTodos() {
    try {
      const r = await fetch('/api/config/ai-keys');
      if (!r.ok) return;
      const d = await r.json();
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
        const uso = info.uso || {};
        const ocrAtivo  = uso.ocr  === true || (info.configurado && !uso.ocr && !uso.chat);
        const chatAtivo = uso.chat === true;
        _aiSetUsoPill(p, 'ocr',  ocrAtivo);
        _aiSetUsoPill(p, 'chat', chatAtivo);
        _aiSetAtivo(p, info.ativo !== false);
      }
    } catch {}
  }

  function _aiSetUsoPill(provider, uso, active) {
    const el = document.getElementById('aiUso-' + provider + '-' + uso);
    if (!el) return;
    if (active) el.classList.add('on'); else el.classList.remove('on');
  }

  window.aiToggleUso = function aiToggleUso(provider, uso) {
    const el = document.getElementById('aiUso-' + provider + '-' + uso);
    if (el) el.classList.toggle('on');
  };

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

  window.aiToggleKey = function aiToggleKey(provider) {
    const inp = document.getElementById('aiKey-' + provider);
    if (!inp) return;
    if (inp.getAttribute('data-preview') === '1') {
      inp.value = ''; inp.setAttribute('data-preview', '0');
      inp.type = 'text'; inp.focus(); return;
    }
    inp.type = inp.type === 'password' ? 'text' : 'password';
  };

  window.aiSalvar = async function aiSalvar(provider) {
    const inp = document.getElementById('aiKey-' + provider);
    const key = inp ? inp.value.trim() : '';
    if (!key) { _aiShowAlert(provider, 'Digite a chave.', 'err'); return; }
    const r = await api('POST', '/api/config/ai-key', { provider, key });
    if (r.ok) {
      const ocr  = document.getElementById('aiUso-' + provider + '-ocr')?.classList.contains('on')  || false;
      const chat = document.getElementById('aiUso-' + provider + '-chat')?.classList.contains('on') || false;
      await api('POST', '/api/config/ai-uso', { provider, ocr, chat });
      _aiShowAlert(provider, '✓ Chave salva!', 'ok');
      inp.value = key.slice(0, 8) + '...' + key.slice(-4);
      inp.setAttribute('data-preview', '1'); inp.type = 'password';
      _aiSetStatus(provider, 'ok', 'Configurada');
    } else {
      _aiShowAlert(provider, r.detail || 'Erro ao salvar.', 'err');
    }
  };

  window.aiSalvarUso = async function aiSalvarUso(provider) {
    const ocr  = document.getElementById('aiUso-' + provider + '-ocr')?.classList.contains('on')  || false;
    const chat = document.getElementById('aiUso-' + provider + '-chat')?.classList.contains('on') || false;
    await api('POST', '/api/config/ai-uso', { provider, ocr, chat });
    _aiShowAlert(provider, '✓ Preferência salva!', 'ok');
  };

  window._aiSetAtivo = function _aiSetAtivo(provider, ativo) {
    const card = document.getElementById('aiCard-' + provider);
    const btn  = document.getElementById('aiToggleAtivo-' + provider);
    if (card) {
      if (ativo) card.classList.remove('ai-card-off'); else card.classList.add('ai-card-off');
      const enableWrap = card.querySelector('.ai-card-enable');
      if (enableWrap) enableWrap.classList.toggle('on', ativo);
      const cb = card.querySelector('.ai-enable-cb');
      if (cb) cb.checked = ativo;
    }
    if (btn) {
      btn.title = ativo ? 'Desativar esta IA' : 'Ativar esta IA';
      btn.classList.toggle('off', !ativo);
    }
  };

  window.aiToggleEnable = function aiToggleEnable(cb) {
    const card = cb.closest('.ai-card');
    if (!card) return;
    const provider = card.id.replace('aiCard-', '');
    window.aiToggleAtivo(provider);
  };

  window.aiToggleAtivo = async function aiToggleAtivo(provider) {
    const card = document.getElementById('aiCard-' + provider);
    const ativo = card ? !card.classList.contains('ai-card-off') : true;
    const novoAtivo = !ativo;
    window._aiSetAtivo(provider, novoAtivo);
    try {
      const r = await api('POST', '/api/config/ai-ativo', { provider, ativo: novoAtivo });
      if (!r.ok) { window._aiSetAtivo(provider, ativo); _aiShowAlert(provider, 'Erro ao salvar.', 'err'); }
      else _aiShowAlert(provider, novoAtivo ? '✓ IA ativada' : '⏸ IA desativada', novoAtivo ? 'ok' : 'err');
    } catch { window._aiSetAtivo(provider, ativo); }
  };

  window.aiTestar = async function aiTestar(provider) {
    _aiSetStatus(provider, '', '⏳ Testando…');
    try {
      const r = await fetch('/api/contabil/ai-status?provider=' + provider);
      if (r.ok) {
        const d = await r.json();
        if (d.ativa) _aiSetStatus(provider, 'ok', 'Conexão OK');
        else _aiSetStatus(provider, 'err', d.motivo || 'Falha');
      } else { _aiSetStatus(provider, 'err', 'Erro'); }
    } catch { _aiSetStatus(provider, 'err', 'Sem resposta'); }
  };

  // ── loadSistema ─────────────────────────────────────────────────────────────

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
    await _iacRefresh();
  }

  // ── Central de IA — master switches + stats ─────────────────────────────

  async function _iacRefresh() {
    try {
      const [cfg, conversas, stats] = await Promise.all([
        fetch('/api/chatbot/config').then(r => r.ok ? r.json() : {}),
        fetch('/api/chatbot/conversas').then(r => r.ok ? r.json() : []),
        fetch('/api/contabil/dashboard').then(r => r.ok ? r.json() : {}),
      ]);

      // Master chatbot toggle
      const cbMaster = document.getElementById('iacChatbotMaster');
      const cbCard   = document.getElementById('iacChatbotCard');
      const cbSub    = document.getElementById('iacChatbotSub');
      const cbActive = !!cfg.ativo;
      if (cbMaster) cbMaster.checked = cbActive;
      if (cbCard) { cbCard.classList.toggle('on', cbActive); cbCard.classList.toggle('off', !cbActive); }
      if (cbSub)  cbSub.textContent = cbActive ? 'Ativo · respondendo automaticamente' : 'Desligado · não responde nenhum contato';

      // Stats chatbot
      const ativos   = (conversas || []).filter(c => c.chatbot_ativo !== false).length;
      const pausados = (conversas || []).filter(c => c.chatbot_ativo === false).length;
      const elA = document.getElementById('iacContatosAtivos');   if (elA) elA.textContent = ativos;
      const elP = document.getElementById('iacContatosPausados'); if (elP) elP.textContent = pausados;

      // Msgs últimas 24h (soma total_msgs)
      const totalMsgs = (conversas || []).reduce((s, c) => s + (c.total_msgs || 0), 0);
      const elM = document.getElementById('iacMsgs24h'); if (elM) elM.textContent = totalMsgs;

      // FAQ count
      try {
        const faq = await fetch('/api/chatbot/faq').then(r => r.ok ? r.json() : []);
        const elF = document.getElementById('iacFaqCount'); if (elF) elF.textContent = (faq || []).length;
      } catch {}

      // Master OCR (config key 'ocr_ativo' — default ON)
      try {
        const gcfg = await fetch('/api/config').then(r => r.ok ? r.json() : {});
        const ocrAtivo = gcfg.ocr_ativo === undefined ? true
                        : (gcfg.ocr_ativo === '1' || gcfg.ocr_ativo === true || gcfg.ocr_ativo === 'true');
        const om = document.getElementById('iacOcrMaster');
        const oc = document.getElementById('iacOcrCard');
        if (om) om.checked = ocrAtivo;
        if (oc) { oc.classList.toggle('on', ocrAtivo); oc.classList.toggle('off', !ocrAtivo); }
      } catch {}

      // OCR stats (dashboard contábil)
      const elD = document.getElementById('iacDocsHoje'); if (elD) elD.textContent = stats.docs_hoje ?? '0';
      const elT = document.getElementById('iacTaxaOcr');  if (elT) elT.textContent = (stats.taxa_ocr ?? 0) + '%';
    } catch (e) {
      console.error('[iac] refresh erro:', e);
    }
  }

  window.iacToggleChatbot = async function iacToggleChatbot(cb) {
    const ativo = !!cb.checked;
    const card = document.getElementById('iacChatbotCard');
    if (card) { card.classList.toggle('on', ativo); card.classList.toggle('off', !ativo); }
    const sub = document.getElementById('iacChatbotSub');
    if (sub) sub.textContent = ativo ? 'Ativo · respondendo automaticamente' : 'Desligado · não responde nenhum contato';
    try {
      // Lê system_prompt atual pra não sobrescrever
      const cur = await fetch('/api/chatbot/config').then(r => r.ok ? r.json() : {});
      await api('POST', '/api/chatbot/config', { ativo, system_prompt: cur.system_prompt || '' });
    } catch {
      cb.checked = !ativo; // rollback
    }
  };

  window.iacToggleOcr = async function iacToggleOcr(cb) {
    const ativo = !!cb.checked;
    const card = document.getElementById('iacOcrCard');
    if (card) { card.classList.toggle('on', ativo); card.classList.toggle('off', !ativo); }
    try {
      await api('POST', '/api/config', { ocr_ativo: ativo ? '1' : '0' });
    } catch {
      cb.checked = !ativo;
    }
  };

  // Refresh ao abrir painel
  document.addEventListener('sys-panel-activated', (e) => {
    if (e.detail === 'token-ia') _iacRefresh();
  });

  // ── Configuração inline: abre painel Chatbot dentro da Central de IA ────
  const _iacTitles = {
    personalidade: 'Personalidade do Bot',
    boasvindas:    'Mensagem de Boas-vindas',
    faq:           'Perguntas & Respostas',
    memoria:       'Memória IA',
    aprendizado:   'Aprendizado',
  };

  window.iacOpenConfig = async function iacOpenConfig(panel) {
    // Garante que chatbot.html foi carregada (cb-panel-X existe no DOM)
    if (typeof window._loadPage === 'function') {
      try { await window._loadPage('chatbot'); } catch {}
    } else if (!document.getElementById('cb-panel-' + panel)) {
      // fallback: força carga via navigate
      const cur = location.pathname;
      await window.navigate('chatbot');
      await new Promise(r => setTimeout(r, 200));
      // não exibe — só carrega no DOM
    }

    const target = document.getElementById('cb-panel-' + panel);
    if (!target) {
      console.warn('[iac] painel não encontrado:', panel);
      return;
    }

    const overview = document.getElementById('iacOverview');
    const slot     = document.getElementById('iacConfigSlot');
    if (!overview || !slot) return;

    // Esconde overview, prepara slot
    overview.style.display = 'none';
    slot.style.display = 'block';
    slot.innerHTML = '';

    // Header: voltar + título
    const head = document.createElement('div');
    head.style.cssText = 'display:flex;align-items:center;gap:.75rem;margin-bottom:14px';
    head.innerHTML = `
      <button class="btn btn-ghost btn-sm" onclick="iacCloseConfig()" style="padding:.4rem .7rem">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 18 9 12 15 6"/></svg>
        Voltar
      </button>
      <h2 style="margin:0;font-size:18px;font-weight:800">${_iacTitles[panel] || panel}</h2>`;
    slot.appendChild(head);

    // Move painel pra slot
    target._iacOrigParent = target.parentElement;
    target._iacOrigNext   = target.nextSibling;
    target.classList.add('active');
    target.style.marginTop = '0';
    slot.appendChild(target);

    // Carrega dados
    if (window.chatbot) {
      if (panel === 'personalidade') chatbot.carregarConfig();
      else if (panel === 'boasvindas') chatbot.carregarBoasVindas();
      else if (panel === 'faq')         chatbot.carregarFaq();
      else if (panel === 'aprendizado') chatbot.carregarAprendizado();
      else if (panel === 'memoria')     chatbot.carregarMemoria();
    }
  };

  window.iacCloseConfig = function iacCloseConfig() {
    const slot     = document.getElementById('iacConfigSlot');
    const overview = document.getElementById('iacOverview');
    if (!slot || !overview) return;

    // Restaura painel pro DOM original
    const panel = slot.querySelector('[id^="cb-panel-"]');
    if (panel && panel._iacOrigParent) {
      panel.classList.remove('active');
      panel.style.marginTop = '';
      panel._iacOrigParent.insertBefore(panel, panel._iacOrigNext || null);
    }

    slot.innerHTML = '';
    slot.style.display = 'none';
    overview.style.display = '';
    _iacRefresh(); // re-puxa stats
  };

  // Registra no ZD.registry
  window.addEventListener('load', () => {
    if (window.ZD && ZD.registry) ZD.registry.register('sistema', loadSistema);
  });

})();
