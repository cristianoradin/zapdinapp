// ── Módulo Telegram ───────────────────────────────────────────────────────────
// Registra eventos e lógica da página Telegram.
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
    el.style.border     = type === 'ok' ? '1px solid ' + s.getPropertyValue('--accent-mid').trim() : '1px solid #fecaca';
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

  function init() {
    if (!_initialized) {
      _registerEvents();
      _initialized = true;
    }
    load();
  }

  return { init };
})();
