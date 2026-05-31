/**
 * modules/chatbot.js — Módulo Chatbot: conversas, config, FAQ, aprendizado, memória.
 * Registra: ZD.registry.register('chatbot', () => chatbot.carregarConversas())
 */
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

  // 2 primeiros dígitos do número (DDD) — avatar estilo WhatsApp do protótipo
  function _digits2(s) {
    const d = String(s || '').replace(/\D/g, '');
    return d.slice(0, 2) || '?';
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
      const ini = _digits2(nm || c.phone);
      const pausado = c.chatbot_ativo === false;
      const isAtivo = c.phone === _phoneAtual;
      const preview = _escHtml(c.ultima_preview || '...');
      const meta = pausado
        ? '<span class="cbx-pill pausado">Pausado</span>'
        : (c.nao_lidas > 0 ? `<span class="cbx-unread">${c.nao_lidas}</span>` : '');
      return `<div class="cb-wa-contact cbx-conv-row${isAtivo ? ' active' : ''}" id="cbContact-${CSS.escape(c.phone)}"
          data-phone="${c.phone.replace(/"/g,'&quot;')}" data-nome="${nm.replace(/"/g,'&quot;')}" data-ativo="${c.chatbot_ativo ? '1' : '0'}">
        <div class="cbx-avatar${pausado ? ' gray' : ''}">${ini}</div>
        <div class="cbx-row-body">
          <div class="cbx-row-line1">
            <span class="cbx-row-name">${_escHtml(nm)}</span>
            <span class="cbx-row-time">${dt}</span>
          </div>
          <div class="cbx-row-line2">
            <span class="cbx-row-preview">${preview}</span>
            ${meta}
          </div>
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
    document.getElementById('cbChatPhone').textContent = 'online agora';
    document.getElementById('cbChatAvatar').textContent = _digits2(phone || nome);

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
        const hora = m.created_at ? new Date(m.created_at).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'}) : '';
        if (isBot) {
          // Resposta da IA — bolha verde clara, à direita, com selo "IA · Zapdin"
          return `<div class="cbx-brow out"><div class="cbx-bubble ia">
            <span class="cbx-sender">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.5 5L19 8l-4 3.5L16 17l-4-2.5L8 17l1-5.5L5 8l5.5-1z"/></svg>
              IA · Zapdin
            </span>
            <span class="cbx-btext">${_escHtml(m.conteudo)}</span>
            <span class="cbx-meta">${hora}</span>
          </div></div>`;
        }
        // Cliente — bolha branca, à esquerda
        return `<div class="cbx-brow in"><div class="cbx-bubble cliente">
          <span class="cbx-btext">${_escHtml(m.conteudo)}</span>
          <span class="cbx-meta">${hora}</span>
        </div></div>`;
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
    const pill  = document.getElementById('cbChatStatusPill');
    const ptxt  = document.getElementById('cbChatStatusTxt');
    if (!btn) return;
    if (_chatbotAtivoAtual) {
      // IA ativa → botão "Assumir conversa" (warn/amarelo)
      btn.className = 'cbx-btn warn';
      if (label) label.textContent = 'Assumir conversa';
      if (pill)  pill.className = 'cbx-pill ativo';
      if (ptxt)  ptxt.textContent = 'IA ativa';
    } else {
      // IA pausada (humano assumiu) → botão "Retomar IA" (primary/verde)
      btn.className = 'cbx-btn primary';
      if (label) label.textContent = 'Retomar IA';
      if (pill)  pill.className = 'cbx-pill pausado';
      if (ptxt)  ptxt.textContent = 'Pausado';
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




// Registro no ZD.registry
window.addEventListener('load', () => {
  if (window.ZD && ZD.registry) ZD.registry.register('chatbot', () => chatbot.carregarConversas());
});
