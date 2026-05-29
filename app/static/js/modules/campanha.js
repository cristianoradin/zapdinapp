// ── Módulo Campanhas DM ──────────────────────────────────────────────────────
// Gerencia contatos, grupos, criação e disparo de campanhas.
// init(page) chamado pelo onPageLoad em app.js.
// Funções críticas expostas globalmente (onclick/onchange inline no HTML).
// Autossuficiente: usa fetch diretamente, sem depender de api() de app.js.

window.campanhaModule = (() => {
  'use strict';

  // ── Helpers internos ─────────────────────────────────────────────────────────

  async function _apiFetch(method, url, body) {
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
    await _apiFetch('DELETE', `/api/campanha/grupos/${_grupoSelecionadoId}/contatos/${contatoId}`);
    _carregarContatosGrupo(_grupoSelecionadoId);
    loadGrupos();
  }

  async function deletarGrupo(id, nome) {
    const ok = await showConfirm({ title: `Excluir grupo "${nome}"?`, body: 'Os contatos não serão excluídos, apenas o grupo.', okLabel: 'Excluir', type: 'danger' });
    if (!ok) return;
    await _apiFetch('DELETE', `/api/campanha/grupos/${id}`);
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
    const res = await _apiFetch(method, path, { nome });
    if (res.ok !== false) {
      document.getElementById('modalGrupoContato').classList.remove('open');
      loadGrupos();
    } else {
      _alert('alertContatos', res.detail || 'Erro ao salvar grupo.', 'error');
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
      const r = await _apiFetch('POST', '/api/campanha/grupos', { nome: novoNome });
      if (r.ok === false) { _alert('alertContatos', r.detail || 'Erro ao criar grupo.', 'error'); return; }
      grupoId = r.id;
    }

    if (!grupoId) { _alert('alertContatos', 'Selecione um grupo ou informe um nome novo.', 'error'); return; }

    const res = await _apiFetch('POST', `/api/campanha/grupos/${grupoId}/contatos`, { contato_ids: ids });
    document.getElementById('modalPickGrupo').classList.remove('open');
    if (res.ok !== false) {
      _alert('alertContatos', `${ids.length} contato(s) adicionado(s) ao grupo com sucesso!`);
      limparSelecaoContatos();
      if (_grupoSelecionadoId === grupoId) _carregarContatosGrupo(grupoId);
      loadGrupos();
    } else {
      _alert('alertContatos', res.detail || 'Erro ao adicionar contatos.', 'error');
    }
  });

  document.getElementById('btnCancelarAddContatos').addEventListener('click', () => {
    document.getElementById('modalAddContatosGrupo').classList.remove('open');
  });

  document.getElementById('btnConfirmarAddContatos').addEventListener('click', async () => {
    const ids = [...document.querySelectorAll('.add-grupo-cb:checked')].map(cb => Number(cb.dataset.id));
    if (!ids.length) { _alert('alertContatos', 'Selecione ao menos um contato.', 'error'); return; }
    const res = await _apiFetch('POST', `/api/campanha/grupos/${_grupoSelecionadoId}/contatos`, { contato_ids: ids });
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
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:2.5rem;color:var(--text-mid)">Nenhum contato cadastrado. Clique em <strong>Novo Contato</strong> ou importe um CSV.</td></tr>';
      document.getElementById('cbSelectAllContatos').checked = false;
      _atualizarActionBar();
      return;
    }
    tbody.innerHTML = lista.map(c => {
      const badge = c.origem === 'erp'
        ? `<span style="background:#dcfce7;color:#15803d;font-size:.68rem;font-weight:700;padding:.15rem .4rem;border-radius:5px;letter-spacing:.03em">ERP</span>`
        : `<span style="background:var(--surface2);color:var(--text-mid);font-size:.68rem;font-weight:600;padding:.15rem .4rem;border-radius:5px">Manual</span>`;
      const gruposPills = c.grupos
        ? c.grupos.split(', ').map(g =>
            `<span style="display:inline-flex;align-items:center;gap:.2rem;background:#f0f7eb;color:#3d7f1f;border:1px solid #d4edba;font-size:.67rem;font-weight:600;padding:.12rem .45rem;border-radius:20px;white-space:nowrap">📁 ${escHtml(g)}</span>`
          ).join(' ')
        : `<span style="color:var(--text-light);font-size:.78rem">—</span>`;
      return `
      <tr>
        <td style="text-align:center"><input type="checkbox" class="cb-contato" data-id="${c.id}" style="width:15px;height:15px;accent-color:var(--accent);cursor:pointer" onchange="_atualizarActionBar()"></td>
        <td style="font-family:monospace;font-size:.85rem">${_fmtPhone(c.phone)}</td>
        <td>${escHtml(c.nome || '—')}</td>
        <td><div style="display:flex;flex-wrap:wrap;gap:.25rem">${gruposPills}</div></td>
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
    if (!raw) { _alert('alertContatos', 'Informe o telefone.', 'error'); return; }
    const phone = _normPhone(raw);
    if (phone.replace(/\D/g,'').length < 12) {
      _alert('alertContatos', 'Número inválido — informe DDD + número (mínimo 10 dígitos).', 'error'); return;
    }
    const res = await _apiFetch('POST', '/api/campanha/contatos', { phone, nome });
    document.getElementById('modalContato').classList.remove('open');
    if (res.ok) { _alert('alertContatos', 'Contato salvo!'); loadContatos(); }
    else _alert('alertContatos', 'Erro ao salvar contato.', 'error');
  });

  async function deletarContato(id) {
    const ok = await showConfirm({ title: 'Excluir contato?', body: 'Esta ação não pode ser desfeita.', okLabel: 'Excluir', type: 'danger' });
    if (!ok) return;
    await _apiFetch('DELETE', `/api/campanha/contatos/${id}`);
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
      _alert('alertContatos', `Importados: ${data.importados} — Erros: ${data.erros}`);
      loadContatos();
    } else _alert('alertContatos', 'Erro ao importar.', 'error');
  });

  // ═══════════════════════════════════════════════════════════════════════════
  //  DISPARO EM MASSA — Nova Campanha
  // ═══════════════════════════════════════════════════════════════════════════

  let _campanhaCriadaId = null;
  let _campImagemDataUrl = null;

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
    _updateCampPreview();
  }

  function initNovaCampanha() {
    // Reset form
    document.getElementById('inpCampNome').value = '';
    document.getElementById('inpCampMensagem').value = '';
    _campanhaCriadaId = null;
    // Reset emoji bank
    document.getElementById('emojiBank').style.display = 'none';
    // Reset scheduling
    _setAgendamento('agora');
    document.getElementById('inpCampData').value = '';
    document.getElementById('inpCampHora').value = '08:00';
    // Set min date to today
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('inpCampData').min = today;
    // Reset image upload
    _campImagemDataUrl = null;
    const inpImg = document.getElementById('inpCampImagem');
    if (inpImg) inpImg.value = '';
    const campEmpty = document.getElementById('campImagemEmpty');
    const campPrev = document.getElementById('campImagemPreview');
    if (campEmpty) campEmpty.style.display = 'flex';
    if (campPrev) campPrev.style.display = 'none';
    _updateCampPreview();
  }

  function _setAgendamento(val) {
    document.querySelectorAll('.agend-card').forEach(c => c.classList.remove('selected'));
    const target = document.querySelector(`.agend-card[data-agend="${val}"]`);
    if (target) target.classList.add('selected');
    const radio = document.querySelector(`input[name="campAgendamento"][value="${val}"]`);
    if (radio) radio.checked = true;
    document.getElementById('secAgendamento').style.display = (val === 'agendar') ? 'block' : 'none';
  }

  function _fmtSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
    return (bytes/(1024*1024)).toFixed(1) + ' MB';
  }

  function _updateCampPreview() {
    const txt = (document.getElementById('inpCampMensagem') || {}).value || '';
    const imgUrl = _campImagemDataUrl;
    const prevImagem = document.getElementById('campPrevImagem');
    const prevImagemImg = document.getElementById('campPrevImagemImg');
    const prevTexto = document.getElementById('campPrevTexto');
    const prevVazio = document.getElementById('campPrevVazio');

    // Image
    if (imgUrl && prevImagem && prevImagemImg) {
      prevImagemImg.src = imgUrl;
      prevImagem.style.display = 'block';
    } else if (prevImagem) {
      prevImagem.style.display = 'none';
    }

    // Text
    if (prevTexto) {
      if (txt) {
        prevTexto.textContent = txt;
        prevTexto.style.color = '#111';
        prevTexto.style.fontStyle = 'normal';
      } else {
        prevTexto.innerHTML = '<span style="color:#aaa;font-style:italic">A mensagem aparecerá aqui…</span>';
      }
    }

    // Vazio placeholder
    if (prevVazio) {
      prevVazio.style.display = (!txt && !imgUrl) ? 'block' : 'none';
    }
  }

  function _removerCampImagem() {
    _campImagemDataUrl = null;
    document.getElementById('inpCampImagem').value = '';
    document.getElementById('campImagemEmpty').style.display = 'flex';
    document.getElementById('campImagemPreview').style.display = 'none';
    _updateCampPreview();
  }

  document.getElementById('inpCampImagem').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      _campImagemDataUrl = ev.target.result;
      document.getElementById('campImagemEmpty').style.display = 'none';
      document.getElementById('campImagemPreview').style.display = 'block';
      document.getElementById('campImagemThumb').src = ev.target.result;
      document.getElementById('campPrevImagemImg').src = ev.target.result;
      document.getElementById('campImagemNome').textContent = file.name + ' (' + (file.size > 1048576 ? (file.size/1048576).toFixed(1)+'MB' : (file.size/1024).toFixed(0)+'KB') + ')';
      _updateCampPreview();
    };
    reader.readAsDataURL(file);
  });

  document.getElementById('inpCampMensagem').addEventListener('input', _updateCampPreview);

  document.getElementById('btnCriarCampanha').addEventListener('click', async () => {
    const nome = document.getElementById('inpCampNome').value.trim();
    const mensagem = document.getElementById('inpCampMensagem').value.trim();
    // tipo automático: file se tiver imagem, text caso contrário
    const tipo = _campImagemDataUrl ? 'file' : 'text';
    if (!nome) { _alert('alertCampanha', 'Informe o nome da campanha.', 'error'); return; }
    if (!mensagem && !_campImagemDataUrl) { _alert('alertCampanha', 'Informe a mensagem ou adicione uma imagem.', 'error'); return; }
    const agendamento = document.querySelector('input[name="campAgendamento"]:checked').value;
    let agendado_em = null;
    if (agendamento === 'agendar') {
      const data = document.getElementById('inpCampData').value;
      const hora = document.getElementById('inpCampHora').value;
      if (!data || !hora) { _alert('alertCampanha', 'Informe data e hora para o agendamento.', 'error'); return; }
      agendado_em = new Date(`${data}T${hora}:00`).toISOString();
    }
    const btnCriar = document.getElementById('btnCriarCampanha');
    btnCriar.disabled = true;
    btnCriar.textContent = 'Criando…';
    const res = await _apiFetch('POST', '/api/campanha', { nome, tipo, mensagem, agendado_em });
    if (!res.ok) {
      _alert('alertCampanha', 'Erro ao criar campanha.', 'error');
      btnCriar.disabled = false;
      btnCriar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> Criar Campanha';
      return;
    }
    _campanhaCriadaId = res.id;
    // Upload da imagem se selecionada
    if (_campImagemDataUrl) {
      try {
        btnCriar.textContent = 'Enviando imagem…';
        const resp = await fetch(_campImagemDataUrl);
        const blob = await resp.blob();
        const ext = (blob.type.split('/')[1] || 'jpg').replace('jpeg','jpg');
        const fd = new FormData();
        fd.append('file', blob, `imagem.${ext}`);
        await fetch(`/api/campanha/${_campanhaCriadaId}/arquivo`, { method: 'POST', body: fd });
      } catch(e) { /* ignora erro de upload silenciosamente */ }
    }
    const msg = agendado_em
      ? `Campanha "${nome}" agendada para ${new Date(agendado_em).toLocaleString('pt-BR')}!`
      : `Campanha "${nome}" criada com sucesso! Vá em Gerenciar Campanhas para iniciar o disparo.`;
    _alert('alertCampanha', msg);
    btnCriar.disabled = false;
    btnCriar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> Criar Campanha';
    setTimeout(() => showPage('dm-historico'), 1500);
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
      _alert('alertHistorico', d.ok ? 'Worker reiniciado com sucesso!' : 'Erro ao reiniciar.', d.ok ? 'success' : 'error');
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
      if (!grupoId) { _alert('alertHistorico', 'Selecione um grupo.', 'error'); return; }
      const opt = document.getElementById('selGrupoId').selectedOptions[0];
      payload = { grupo_id: grupoId };
      descricao = `grupo "${opt.textContent.split('(')[0].trim()}"`;
    } else {
      const ids = [...document.querySelectorAll('.sel-contato-cb:checked')].map(cb => Number(cb.dataset.id));
      if (!ids.length) { _alert('alertHistorico', 'Selecione pelo menos um contato.', 'error'); return; }
      payload = { contato_ids: ids };
      descricao = `${ids.length} contato(s) selecionados`;
    }

    document.getElementById('modalSelecionarContatos').classList.remove('open');
    const res = await _apiFetch('POST', `/api/campanha/${_selCampanhaId}/iniciar`, payload);
    if (res.ok) {
      _alert('alertHistorico', `Disparo iniciado para ${descricao}!`);
      loadCampanhas();
      _startCampRefresh();
    } else {
      _alert('alertHistorico', res.detail || 'Erro ao iniciar campanha.', 'error');
    }
  });

  async function pausarCampanha(id) {
    await _apiFetch('POST', `/api/campanha/${id}/pausar`);
    loadCampanhas();
  }

  async function deletarCampanha(id) {
    const ok = await showConfirm({ title: 'Excluir campanha?', body: 'Remove todos os envios e arquivos desta campanha.', okLabel: 'Excluir', type: 'danger' });
    if (!ok) return;
    await _apiFetch('DELETE', `/api/campanha/${id}`);
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
    await _apiFetch('DELETE', `/api/campanha/${_campModalId}/arquivo/${arqId}`);
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
      // Para o auto-refresh quando não houver campanhas em execução ou pausadas com envios pendentes
      const hasActive = lista.some(c =>
        c.status === 'running' ||
        (c.status === 'paused' && c.enviados < c.total)
      );
      if (!hasActive) {
        clearInterval(_campRefreshTimer);
        _campRefreshTimer = null;
      }
    }, 3000);
  }

  // ── Expõe funções globalmente ─────────────────────────────────────────────
  window.switchContatosTab = switchContatosTab;
  window.abrirPickGrupo = abrirPickGrupo;
  window.limparSelecaoContatos = limparSelecaoContatos;
  window._removerCampImagem = _removerCampImagem;
  window.toggleEmojiBank = toggleEmojiBank;
  window.insertEmoji = insertEmoji;
  window._setAgendamento = _setAgendamento;
  window._setSelModo = _setSelModo;
  window._atualizarActionBar = _atualizarActionBar;
  window.deletarContato = deletarContato;
  window.selecionarGrupo = selecionarGrupo;
  window.deletarGrupo = deletarGrupo;
  window.removerDoGrupo = removerDoGrupo;
  window.iniciarCampanha = iniciarCampanha;
  window.pausarCampanha = pausarCampanha;
  window.deletarCampanha = deletarCampanha;
  window.abrirModalArquivos = abrirModalArquivos;
  window.deletarArqModal = deletarArqModal;
  window.loadDashboardCampanhas = loadDashboardCampanhas;
  window.loadContatos = loadContatos;
  window.initNovaCampanha = initNovaCampanha;
  window.loadCampanhas = loadCampanhas;
  window.loadWorkerStatus = loadWorkerStatus;
  window.loadCampanhasEnviadas = loadCampanhasEnviadas;
  window._destroyCharts = _destroyCharts;
  window.escHtml = escHtml;

  return {
    loadDashboardCampanhas,
    initNovaCampanha,
    loadCampanhas,
    loadWorkerStatus,
    loadCampanhasEnviadas,
    loadContatos,
    _destroyCharts,
  };

})(); // fim módulo campanhas
