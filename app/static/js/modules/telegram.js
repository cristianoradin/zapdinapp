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

  // Cada destino: { numero, avaliacao, falha }
  let _destinos = [];
  let _avalAtiva = false;   // avaliação ligada? (gate do alerta de avaliação)

  function _alertaRenderTelefones() {
    const box = document.getElementById('alertaCriticoTelefonesList');
    if (!box) return;
    if (!_destinos.length) {
      box.innerHTML = '<div style="font-size:12.5px;color:var(--text-3);padding:6px 0">Nenhum telefone adicionado ainda.</div>';
      return;
    }
    box.innerHTML = _destinos.map((d, i) => `
      <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;background:var(--surface-2,#f6f7f9);border:1px solid var(--border);border-radius:10px;padding:8px 12px">
        <span style="font-weight:700;font-size:14px;min-width:120px">+55 ${d.numero}</span>
        <label style="display:inline-flex;align-items:center;gap:6px;font-size:13px;cursor:pointer;user-select:none">
          <input type="checkbox" ${d.avaliacao ? 'checked' : ''} onchange="alertaToggleFlag(${i},'avaliacao',this.checked)"> Avaliação
        </label>
        <label style="display:inline-flex;align-items:center;gap:6px;font-size:13px;cursor:pointer;user-select:none">
          <input type="checkbox" ${d.falha ? 'checked' : ''} onchange="alertaToggleFlag(${i},'falha',this.checked)"> Falha de envio
        </label>
        <span style="flex:1"></span>
        <span style="cursor:pointer;font-weight:800;color:var(--red);line-height:1" onclick="alertaRemoveTelefone(${i})" title="Remover">✕</span>
      </div>`).join('');
  }

  function alertaAddTelefone() {
    const inp = document.getElementById('alertaCriticoTelefone');
    if (!inp) return;
    const t = (inp.value || '').replace(/\D/g, '');
    if (t.length < 10) { return; }
    if (!_destinos.some(d => d.numero === t)) {
      _destinos.push({ numero: t, avaliacao: true, falha: true });  // por padrão recebe os dois
    }
    inp.value = '';
    _alertaRenderTelefones();
    _alertaSetSalvo(false);
  }

  function alertaRemoveTelefone(i) {
    _destinos.splice(i, 1);
    _alertaRenderTelefones();
    _alertaSetSalvo(false);
  }

  function alertaToggleFlag(i, flag, val) {
    if (_destinos[i]) _destinos[i][flag] = !!val;
    _alertaSetSalvo(false);
  }

  function _syncAlertaToggleState() {
    const aviso = document.getElementById('alertaCriticoAvisoAval');
    if (!aviso) return;
    if (!_avalAtiva) {
      aviso.style.display = 'block';
      aviso.textContent = 'A Avaliação está desligada (em "Configurar Mensagem"). O alerta de Avaliação só dispara com ela ligada. O alerta de Falha de envio funciona independente disso.';
    } else {
      aviso.style.display = 'none';
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
      const msg   = document.getElementById('alertaCriticoMensagem');
      const fMsg  = document.getElementById('alertaFalhaMensagem');
      _destinos = Array.isArray(cfg.destinos) ? cfg.destinos.map(d => ({
        numero: String(d.numero || ''), avaliacao: !!d.avaliacao, falha: !!d.falha,
      })).filter(d => d.numero) : [];
      _alertaRenderTelefones();
      if (msg)  msg.value  = cfg.mensagem || _ALERTA_DEFAULT_MSG;
      if (fMsg) fMsg.value   = cfg.falha_mensagem || _FALHA_DEFAULT_MSG;
      _syncAlertaToggleState();
      _alertaSetSalvo(true);
      const _onchange = () => _alertaSetSalvo(false);
      if (msg)  msg.addEventListener('input', _onchange);
      if (fMsg) fMsg.addEventListener('input', _onchange);
    } catch(e) {}
  }

  async function salvarAlertaCritico() {
    const resEl = document.getElementById('alertaCriticoResult');
    const msg   = document.getElementById('alertaCriticoMensagem')?.value || '';
    const falhaMsg   = document.getElementById('alertaFalhaMensagem')?.value || '';

    // Número digitado mas não adicionado também conta (recebe os dois por padrão)
    const pend = document.getElementById('alertaCriticoTelefone')?.value?.replace(/\D/g,'') || '';
    if (pend.length >= 10 && !_destinos.some(d => d.numero === pend)) {
      _destinos.push({ numero: pend, avaliacao: true, falha: true });
    }
    const destinos = _destinos.slice();

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

    const algumAtivo = destinos.some(d => d.avaliacao || d.falha);
    if (destinos.length && !algumAtivo) {
      show('error', 'Marque ao menos um tipo (Avaliação ou Falha) em algum número.'); return;
    }

    const res = await api('POST', '/api/config/alerta-critico', {
      destinos, mensagem: msg, falha_mensagem: falhaMsg,
    });
    if (res && res.ok) { _destinos = destinos; _alertaRenderTelefones(); _alertaSetSalvo(true); }
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

  return { init, salvarAlertaCritico, alertaAddTelefone, alertaRemoveTelefone, alertaToggleFlag };
})();

// ── Globais para chamadas inline no HTML ─────────────────────────────────────
window.salvarAlertaCritico  = () => telegramModule.salvarAlertaCritico();
window.alertaAddTelefone    = () => telegramModule.alertaAddTelefone();
window.alertaRemoveTelefone = (i) => telegramModule.alertaRemoveTelefone(i);
window.alertaToggleFlag     = (i, f, v) => telegramModule.alertaToggleFlag(i, f, v);
