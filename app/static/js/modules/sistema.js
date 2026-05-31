/**
 * modules/sistema.js — Página Sistema: IA config, usuário, navegação.
 * Extraído de app.js em 2026-05.
 * Registra: ZD.registry.register('sistema', loadSistema)
 */
(function () {
  'use strict';

  // ── Sistema — navegação interna ─────────────────────────────────────────────

  window.sysNav = function sysNav(el, panel) {
    const page = document.getElementById('page-sistema');
    const sysContent = page ? page.querySelector('.sys-content') : null;
    const target = document.getElementById('sys-panel-' + panel);
    if (target && sysContent && !sysContent.contains(target)) {
      sysContent.appendChild(target);
    }
    // Escopa ao #page-sistema — não interfere nos menus/painéis do Chatbot
    const scope = page || document;
    scope.querySelectorAll('.sys-menu-item').forEach(i => i.classList.remove('active'));
    scope.querySelectorAll('.sys-panel').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
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
    }
    if (btn) {
      btn.title = ativo ? 'Desativar esta IA' : 'Ativar esta IA';
      btn.classList.toggle('off', !ativo);
    }
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
  }

  // Registra no ZD.registry
  window.addEventListener('load', () => {
    if (window.ZD && ZD.registry) ZD.registry.register('sistema', loadSistema);
  });

})();
