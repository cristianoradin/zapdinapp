// ── Módulo Telegram + Alerta Crítico ──────────────────────────────────────────
// init() é chamado pelo onPageLoad em app.js quando a página é exibida.
// Depende de: api(), showAlert() — ambas globais em app.js.

window.telegramModule = (() => {
  let _initialized = false;

  function _setTgStatus(type, msg) {
    const el = document.getElementById('tgStatus');
    if (!el) return;
    if (!type) { el.style.display = 'none'; return; }
    el.style.display = 'block';
    const s = getComputedStyle(document.documentElement);
    el.style.background = type === 'ok' ? s.getPropertyValue('--accent-soft').trim() : s.getPropertyValue('--red-soft').trim();
    el.style.color      = type === 'ok' ? s.getPropertyValue('--accent').trim()      : s.getPropertyValue('--red').trim();
    el.style.border     = type === 'ok' ? '1px solid ' + s.getPropertyValue('--accent-mid').trim() : '1px solid color-mix(in srgb,var(--red) 30%,transparent)';
    el.textContent = msg;
  }

  async function load() {
    const res = await fetch('/api/telegram/config');
    if (!res.ok) return;
    const d = await res.json();
    document.getElementById('tgBotToken').value = d.bot_token || '';
    document.getElementById('tgChatId').value   = d.chat_id   || '';
    _setTgStatus(d.configured ? 'ok' : null, d.configured ? 'Telegram configurado e ativo' : '');
  }

  function _registerEvents() {
    document.getElementById('btnSalvarTelegram').addEventListener('click', async () => {
      const token  = document.getElementById('tgBotToken').value.trim();
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
  }

  // ── Alerta Crítico (WhatsApp) ───────────────────────────────────────────────

  const _ALERTA_DEFAULT_MSG =
    '🚨 *Avaliação Negativa Recebida!*\n\n' +
    '👤 *Cliente:* {nome}\n' +
    '📞 *Telefone:* {telefone}\n' +
    '⭐ *Nota:* {nota} estrela(s)\n' +
    '👨‍💼 *Vendedor:* {vendedor}\n' +
    '💬 *Comentário:* {comentario}\n' +
    '📅 *Data:* {data}\n\n' +
    '⚠️ Entre em contato com o cliente para resolver a situação!';

  const _FALHA_DEFAULT_MSG =
    '⚠️ *Falha ao enviar mensagem!*\n\n' +
    '📞 *Número:* {numero}\n' +
    '👤 *Nome:* {nome}\n' +
    '❌ *Motivo:* {erro}\n' +
    '📅 *Data:* {data}\n\n' +
    '🔎 Verifique o cadastro deste número (pode estar incorreto ou sem WhatsApp).';

  let _alertaTelefones = [];
  let _avalAtiva = false;   // avaliação ligada? (gate do alerta de avaliação)

  function _alertaRenderTelefones() {
    const box = document.getElementById('alertaCriticoTelefonesList');
    if (!box) return;
    box.innerHTML = _alertaTelefones.map((t, i) =>
      `<span style="display:inline-flex;align-items:center;gap:6px;background:var(--red-bg);border:1px solid #fca5a5;color:var(--red);padding:5px 10px;border-radius:999px;font-size:13px;font-weight:600">`
      + `+55 ${t}`
      + `<span style="cursor:pointer;font-weight:800;line-height:1" onclick="alertaRemoveTelefone(${i})" title="Remover">✕</span></span>`
    ).join('');
  }

  function alertaAddTelefone() {
    const inp = document.getElementById('alertaCriticoTelefone');
    if (!inp) return;
    const t = (inp.value || '').replace(/\D/g, '');
    if (t.length < 10) { return; }
    if (!_alertaTelefones.includes(t)) _alertaTelefones.push(t);
    inp.value = '';
    _alertaRenderTelefones();
    _alertaSetSalvo(false);
  }

  function alertaRemoveTelefone(i) {
    _alertaTelefones.splice(i, 1);
    _alertaRenderTelefones();
    _alertaSetSalvo(false);
  }

  function _syncAlertaToggleState() {
    const chk   = document.getElementById('alertaCriticoAtivo');
    const aviso = document.getElementById('alertaCriticoAvisoAval');
    if (!chk) return;
    if (!_avalAtiva) {
      chk.checked  = false;
      chk.disabled = true;
      if (aviso) {
        aviso.style.display = 'flex';
        aviso.textContent = 'Ative a Avaliação (em "Configurar Mensagem") para usar o alerta de avaliação negativa. O alerta de falha de envio funciona independente disso.';
      }
    } else {
      chk.disabled = false;
      if (aviso) aviso.style.display = 'none';
    }
  }

  function _alertaSetSalvo(salvo) {
    const resEl = document.getElementById('alertaCriticoResult');
    if (!resEl) return;
    if (salvo) {
      resEl.style.cssText = 'display:flex;align-items:center;gap:.45rem;font-size:.8rem;font-weight:600;padding:.5rem .75rem;border-radius:8px;background:var(--primary-soft);border:1px solid #86efac;color:#15803d';
      resEl.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><polyline points="20 6 9 17 4 12"/></svg>Configuração salva com sucesso`;
    } else {
      resEl.style.display = 'none';
    }
  }

  async function loadAlertaCritico() {
    try {
      // Estado da avaliação (gate do alerta de avaliação negativa)
      try {
        const c = await fetch('/api/config').then(r => r.ok ? r.json() : {});
        _avalAtiva = c.avaliacao_ativa === '1' || c.avaliacao_ativa === true;
      } catch { _avalAtiva = false; }

      const res = await fetch('/api/config/alerta-critico');
      if (!res.ok) return;
      const cfg = await res.json();
      const chk   = document.getElementById('alertaCriticoAtivo');
      const msg   = document.getElementById('alertaCriticoMensagem');
      const fChk  = document.getElementById('alertaFalhaAtivo');
      const fMsg  = document.getElementById('alertaFalhaMensagem');
      _alertaTelefones = Array.isArray(cfg.telefones) && cfg.telefones.length
        ? cfg.telefones.slice()
        : (cfg.telefone ? [cfg.telefone] : []);
      _alertaRenderTelefones();
      if (msg)  msg.value  = cfg.mensagem || _ALERTA_DEFAULT_MSG;
      if (chk && _avalAtiva) chk.checked = !!cfg.ativo;
      if (fChk) fChk.checked = !!cfg.falha_ativo;
      if (fMsg) fMsg.value   = cfg.falha_mensagem || _FALHA_DEFAULT_MSG;
      _syncAlertaToggleState();
      _alertaSetSalvo(true);
      const _onchange = () => _alertaSetSalvo(false);
      if (msg)  msg.addEventListener('input', _onchange);
      if (chk)  chk.addEventListener('change', _onchange);
      if (fChk) fChk.addEventListener('change', _onchange);
      if (fMsg) fMsg.addEventListener('input', _onchange);
    } catch(e) {}
  }

  async function salvarAlertaCritico() {
    const resEl = document.getElementById('alertaCriticoResult');
    const ativo = document.getElementById('alertaCriticoAtivo')?.checked || false;
    const msg   = document.getElementById('alertaCriticoMensagem')?.value || '';
    const falhaAtivo = document.getElementById('alertaFalhaAtivo')?.checked || false;
    const falhaMsg   = document.getElementById('alertaFalhaMensagem')?.value || '';

    // Número digitado mas não adicionado também conta
    const pend = document.getElementById('alertaCriticoTelefone')?.value?.replace(/\D/g,'') || '';
    if (pend.length >= 10 && !_alertaTelefones.includes(pend)) _alertaTelefones.push(pend);
    const telefones = _alertaTelefones.slice();

    const show = (type, txt) => {
      if (!resEl) return;
      if (type === 'ok') {
        resEl.style.cssText = 'display:flex;align-items:center;gap:.45rem;font-size:.8rem;font-weight:600;padding:.5rem .75rem;border-radius:8px;background:var(--primary-soft);border:1px solid #86efac;color:#15803d';
        resEl.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><polyline points="20 6 9 17 4 12"/></svg>${txt}`;
      } else {
        resEl.style.cssText = 'display:flex;align-items:center;gap:.45rem;font-size:.8rem;font-weight:600;padding:.5rem .75rem;border-radius:8px;background:var(--red-bg);border:1px solid #fca5a5;color:var(--red)';
        resEl.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>${txt}`;
        setTimeout(() => { resEl.style.display = 'none'; }, 5000);
      }
    };

    if ((ativo || falhaAtivo) && telefones.length === 0) {
      show('error', 'Adicione ao menos um telefone para receber os alertas.'); return;
    }

    const res = await api('POST', '/api/config/alerta-critico', {
      ativo, telefones, mensagem: msg,
      falha_ativo: falhaAtivo, falha_mensagem: falhaMsg,
    });
    if (res && res.ok) { _alertaTelefones = telefones; _alertaRenderTelefones(); _alertaSetSalvo(true); }
    else show('error', 'Erro ao salvar configuração.');
  }

  function init() {
    if (!_initialized) {
      _registerEvents();
      _initialized = true;
    }
    load();
    loadAlertaCritico();
  }

  return { init, salvarAlertaCritico, alertaAddTelefone, alertaRemoveTelefone };
})();

// ── Globais para chamadas inline no HTML ─────────────────────────────────────
window.salvarAlertaCritico  = () => telegramModule.salvarAlertaCritico();
window.alertaAddTelefone    = () => telegramModule.alertaAddTelefone();
window.alertaRemoveTelefone = (i) => telegramModule.alertaRemoveTelefone(i);
