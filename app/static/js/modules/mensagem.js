// ── Módulo Configurar Mensagem ────────────────────────────────────────────────
// Gerencia template de mensagem, avaliação e teste de envio da página mensagem.
// init() chamado pelo onPageLoad em app.js.
// salvarAvaliacaoCfg() exposta globalmente (usada em onchange inline no HTML).
// Autossuficiente: usa fetch diretamente, sem depender de api() de app.js.

window.mensagemModule = (() => {
  let _initialized = false;
  let _clientName = '';
  let _linkDemoAvaliacao = '';

  // ── Helpers internos ─────────────────────────────────────────────────────────

  async function _fetch(method, url, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(url, opts);
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

  // ── Mensagem template ────────────────────────────────────────────────────────

  // ── Status "template salvo / não salvo" ──────────────────────────────────────
  function _setTemplateStatus(saved) {
    const el   = document.getElementById('templateSaveStatus');
    const icon = document.getElementById('templateSaveStatusIcon');
    const txt  = document.getElementById('templateSaveStatusText');
    if (!el) return;
    if (saved) {
      el.style.cssText   = 'display:flex;align-items:center;gap:.45rem;font-size:.8rem;font-weight:600;padding:.5rem .75rem;border-radius:8px;margin-top:.5rem;background:#f0fdf4;border:1px solid #86efac;color:#15803d';
      icon.innerHTML     = '<polyline points="20 6 9 17 4 12"/>';
      icon.setAttribute('viewBox','0 0 24 24');
      txt.textContent    = '✅ Template salvo com sucesso';
    } else {
      el.style.cssText   = 'display:flex;align-items:center;gap:.45rem;font-size:.8rem;font-weight:600;padding:.5rem .75rem;border-radius:8px;margin-top:.5rem;background:#fffbeb;border:1px solid #fde68a;color:#92400e';
      icon.innerHTML     = '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>';
      txt.textContent    = 'Template não salvo — clique em Salvar Template';
    }
  }

  async function loadMensagem() {
    const res = await fetch('/api/config');
    if (!res.ok) return;
    const cfg = await res.json();

    _clientName = cfg.client_name || '';
    document.getElementById('clientNameDisplay').textContent = _clientName || '(não configurado)';

    // Remove cabeçalho fixo embutido (retrocompatibilidade)
    let tmpl = cfg.mensagem_padrao || '';
    const prefixo = '🏪 *' + _clientName + '*\n\n';
    if (_clientName && tmpl.startsWith(prefixo)) {
      tmpl = tmpl.slice(prefixo.length);
    }
    document.getElementById('inputMensagem').value = tmpl;
    updatePreview(tmpl);
    atualizarPreviewTeste();

    // Se já tem template salvo no servidor, mostra como "salvo"
    _setTemplateStatus(!!tmpl);
  }

  function updatePreview(tmpl) {
    const produtosEx = '• Gasolina Comum (x30) — R$ 5,99\n• Óleo Motor 5W30 (x1) — R$ 42,00';
    const header = _clientName ? '🏪 *' + _clientName + '*\n\n' : '';
    const full = header + tmpl;
    let preview = full
      .replace(/{nome}/g, 'João Silva')
      .replace(/{telefone}/g, '5511999990000')
      .replace(/{data}/g, '14/05/2026')
      .replace(/{produtos}/g, produtosEx)
      .replace(/{valor_total_itens}/g, 'R$ 221,70')
      .replace(/{valor_total}/g, 'R$ 221,70')
      .replace(/{valor}/g, 'R$ 221,70')
      .replace(/{vendedor}/g, 'Maria Santos');
    const avalAtivo = document.getElementById('toggleAvaliacao')?.checked;
    if (avalAtivo) {
      const linkFull = _linkDemoAvaliacao || `${location.origin}/avaliacao?t=DEMO`;
      const linkCurto = (() => {
        try { const u = new URL(linkFull); return u.hostname + '/avaliacao'; } catch { return 'avaliacao'; }
      })();
      preview += `\n\n⭐ Avalie nosso atendimento:\n🔗 ${linkCurto}`;
    }
    document.getElementById('previewMensagem').textContent = preview || 'Digite o template ao lado para ver o preview aqui…';
    const wrap = document.querySelector('.wa-preview-wrap-inner');
    if (wrap) wrap.scrollTop = wrap.scrollHeight;
  }

  // ── Avaliação config ─────────────────────────────────────────────────────────

  async function loadAvaliacaoCfg() {
    try {
      const res = await fetch('/api/config');
      const cfg = res.ok ? await res.json() : {};
      const ativo = cfg.avaliacao_ativa === '1' || cfg.avaliacao_ativa === true;
      document.getElementById('toggleAvaliacao').checked = ativo;
      document.getElementById('avaliacaoPreviewWrap').style.display = ativo ? '' : 'none';
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
    await _fetch('POST', '/api/config', { avaliacao_ativa: ativo ? '1' : '0' });
    updatePreview(document.getElementById('inputMensagem')?.value || '');
    if (ativo) {
      const res = await fetch('/api/config');
      const cfg = res.ok ? await res.json() : {};
      const empresaId = cfg.empresa_id || '';
      document.getElementById('avaliacaoPreviewIframe').src = '/avaliacao/preview' + (empresaId ? '?empresa_id=' + empresaId : '');
    }
  }

  // ── Teste de envio (integrado na página mensagem) ─────────────────────────

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
      alertEl.style.cssText = 'display:flex;align-items:center;gap:.5rem;font-size:.82rem;font-weight:600;padding:.5rem .75rem;border-radius:8px;margin-bottom:1rem;background:#fffbeb;border:1px solid #fde68a;color:#92400e';
      alertEl.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>' +
        '<span>Nenhuma sessão WhatsApp conectada — <a href="#" onclick="navigate(\'whatsapp\');return false;" style="color:inherit;text-decoration:underline;font-weight:700">Conectar WhatsApp</a></span>';
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
      .replace(/{valor}/g, 'R$ 221,70')
      .replace(/{vendedor}/g, 'Maria Santos');
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

  // ── Registro de eventos (executado uma única vez) ─────────────────────────

  function _registerEvents() {
    // Live preview ao digitar no textarea
    document.getElementById('inputMensagem').addEventListener('input', e => {
      updatePreview(e.target.value);
      atualizarPreviewTeste();
    });

    // Clique nas var-tags: insere variável na posição do cursor
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

    // Salvar mensagem
    document.getElementById('btnSalvarMensagem').addEventListener('click', async () => {
      const corpo = document.getElementById('inputMensagem').value;
      const header = _clientName ? '🏪 *' + _clientName + '*\n\n' : '';
      const val = header + corpo;
      const res = await _fetch('POST', '/api/config', { mensagem_padrao: val });
      if (res && res.ok) {
        _alert('alertMensagem', 'Mensagem salva com sucesso!');
        _setTemplateStatus(true);
      } else {
        _alert('alertMensagem', 'Erro ao salvar', 'error');
      }
    });

    // Quando o usuário editar o textarea, volta ao estado "não salvo"
    document.getElementById('inputMensagem').addEventListener('input', () => {
      _setTemplateStatus(false);
    });

    // Enviar teste de mensagem
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
      const res = await _fetch('POST', `/api/sessoes/${sessaoId}/send-text`, { phone, message });
      if (res && res.ok) show('ok','✅ Mensagem enviada com sucesso!');
      else show('error','❌ ' + (res?.detail || 'Erro ao enviar mensagem.'));
    });

    // Preview de teste ao mudar checkbox avaliação
    const cbAval = document.getElementById('testeMsgIncluirAval');
    if (cbAval) cbAval.addEventListener('change', atualizarPreviewTeste);

    // Quando avaliação é ligada/desligada, sincroniza estado do alerta crítico
    const toggleAval = document.getElementById('toggleAvaliacao');
    if (toggleAval) toggleAval.addEventListener('change', _syncAlertaToggleState);

    // Preview de teste ao digitar número de telefone
    const phoneEl = document.getElementById('testeMsgPhone');
    if (phoneEl) phoneEl.addEventListener('input', atualizarPreviewTeste);
  }

  // ── Alerta Crítico de Avaliação ───────────────────────────────────────────────

  const _ALERTA_DEFAULT_MSG =
    '🚨 *Avaliação Negativa Recebida!*\n\n' +
    '👤 *Cliente:* {nome}\n' +
    '📞 *Telefone:* {telefone}\n' +
    '⭐ *Nota:* {nota} estrela(s)\n' +
    '👨‍💼 *Vendedor:* {vendedor}\n' +
    '💬 *Comentário:* {comentario}\n' +
    '📅 *Data:* {data}\n\n' +
    '⚠️ Entre em contato com o cliente para resolver a situação!';

  function _avaliacaoAtiva() {
    return document.getElementById('toggleAvaliacao')?.checked === true;
  }

  function _syncAlertaToggleState() {
    const chk     = document.getElementById('alertaCriticoAtivo');
    const aviso   = document.getElementById('alertaCriticoAvisoAval');
    if (!chk) return;
    if (!_avaliacaoAtiva()) {
      chk.checked  = false;
      chk.disabled = true;
      if (aviso) aviso.style.display = 'flex';
    } else {
      chk.disabled = false;
      if (aviso) aviso.style.display = 'none';
    }
  }

  function _alertaSetSalvo(salvo) {
    const resEl = document.getElementById('alertaCriticoResult');
    if (!resEl) return;
    if (salvo) {
      resEl.style.cssText = 'display:flex;align-items:center;gap:.45rem;font-size:.8rem;font-weight:600;padding:.5rem .75rem;border-radius:8px;background:#f0fdf4;border:1px solid #86efac;color:#15803d';
      resEl.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><polyline points="20 6 9 17 4 12"/></svg>Configuração salva com sucesso`;
    } else {
      resEl.style.display = 'none';
    }
  }

  async function loadAlertaCritico() {
    try {
      const res = await fetch('/api/config/alerta-critico');
      if (!res.ok) return;
      const cfg = await res.json();
      const chk = document.getElementById('alertaCriticoAtivo');
      const tel = document.getElementById('alertaCriticoTelefone');
      const msg = document.getElementById('alertaCriticoMensagem');
      if (tel) tel.value = cfg.telefone || '';
      if (msg) msg.value = cfg.mensagem || _ALERTA_DEFAULT_MSG;
      if (chk && _avaliacaoAtiva()) chk.checked = !!cfg.ativo;
      _syncAlertaToggleState();
      // Mostra "salvo" ao carregar se já houver config no banco
      _alertaSetSalvo(true);
      // Ao editar qualquer campo, volta ao estado "não salvo"
      const _onchange = () => _alertaSetSalvo(false);
      if (tel) tel.addEventListener('input', _onchange);
      if (msg) msg.addEventListener('input', _onchange);
      if (chk) chk.addEventListener('change', _onchange);
    } catch(e) {}
  }

  async function salvarAlertaCritico() {
    const btn   = document.getElementById('btnSalvarAlertaCritico');
    const resEl = document.getElementById('alertaCriticoResult');
    const ativo = document.getElementById('alertaCriticoAtivo')?.checked || false;
    const tel   = document.getElementById('alertaCriticoTelefone')?.value?.trim().replace(/\D/g,'') || '';
    const msg   = document.getElementById('alertaCriticoMensagem')?.value || '';

    const show = (type, txt) => {
      if (type === 'ok') {
        resEl.style.cssText = 'display:flex;align-items:center;gap:.45rem;font-size:.8rem;font-weight:600;padding:.5rem .75rem;border-radius:8px;background:#f0fdf4;border:1px solid #86efac;color:#15803d';
        resEl.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><polyline points="20 6 9 17 4 12"/></svg>${txt}`;
      } else {
        resEl.style.cssText = 'display:flex;align-items:center;gap:.45rem;font-size:.8rem;font-weight:600;padding:.5rem .75rem;border-radius:8px;background:#fef2f2;border:1px solid #fca5a5;color:#991b1b';
        resEl.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>${txt}`;
        setTimeout(() => { resEl.style.display = 'none'; }, 5000);
      }
    };

    if (ativo && tel.length < 10) { show('error', 'Informe o telefone de destino com DDD (ex: 11999998888).'); return; }

    if (btn) { btn.disabled = true; btn.textContent = 'Salvando…'; }
    try {
      const res = await _fetch('POST', '/api/config/alerta-critico', { ativo, telefone: tel, mensagem: msg });
      if (res && res.ok) _alertaSetSalvo(true);
      else show('error', 'Erro ao salvar configuração.');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg> Salvar Configuração';
      }
    }
  }

  // Insere variável no textarea do alerta na posição do cursor
  function insertAlertaVar(v) {
    const ta = document.getElementById('alertaCriticoMensagem');
    if (!ta) return;
    const s = ta.selectionStart, e = ta.selectionEnd;
    ta.value = ta.value.slice(0, s) + v + ta.value.slice(e);
    ta.selectionStart = ta.selectionEnd = s + v.length;
    ta.focus();
  }

  // ── Ponto de entrada ─────────────────────────────────────────────────────────

  function init() {
    if (!_initialized) {
      _registerEvents();
      _initialized = true;
    }
    // Carrega avaliação e link demo em paralelo, depois carrega mensagem e teste
    Promise.all([loadAvaliacaoCfg(), _carregarLinkDemo()]).then(() => {
      loadMensagem();
      loadTesteMensagem();
      loadAlertaCritico();
    });
  }

  return { init, salvarAvaliacaoCfg, salvarAlertaCritico, insertAlertaVar };
})();

// ── Globais para chamadas inline no HTML ─────────────────────────────────────
window.salvarAvaliacaoCfg  = () => mensagemModule.salvarAvaliacaoCfg();
window.salvarAlertaCritico = () => mensagemModule.salvarAlertaCritico();
window.insertAlertaVar     = (v) => mensagemModule.insertAlertaVar(v);
