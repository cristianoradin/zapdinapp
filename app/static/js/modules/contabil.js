/**
 * app/static/js/modules/contabil.js
 * Módulo Contábil — Gestão de Documentos, Cadastro de Empresas, Gestão de Arquivos.
 *
 * Expõe três namespaces globais:
 *   ctbDashboard  — Gestão de Documentos (cards + tabela + feed)
 *   ctbEmpresas   — Cadastro de Empresas (form + lista)
 *   ctbArquivos   — Gestão de Arquivos (por empresa + docs + upload)
 *   ctbManual     — Modal de entrada manual de NF
 */

// ── Helpers ────────────────────────────────────────────────────────────────────

function _ctbFmt(dt) {
  if (!dt) return '—';
  const d = new Date(dt);
  return d.toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', year:'2-digit',
    hour:'2-digit', minute:'2-digit' });
}

function _ctbFmtDate(dt) {
  if (!dt) return '—';
  const d = new Date(dt);
  return d.toLocaleDateString('pt-BR');
}

function _ctbFmtBRL(v) {
  if (v == null) return '—';
  return Number(v).toLocaleString('pt-BR', { style:'currency', currency:'BRL' });
}

function _ctbAlert(id, msg, type='error') {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.className = `alert alert-${type === 'error' ? 'error' : 'success'}`;
  el.style.display = 'block';
  if (type !== 'error') setTimeout(() => { el.style.display = 'none'; }, 4000);
}

function _ctbStatusChip(status) {
  const labels = {
    recebido: 'Recebido',
    ocr_pendente: 'OCR Pendente',
    ocr_erro: 'Erro OCR',
    revisao_manual: 'Revisão Manual',
    aprovado: 'Aprovado',
  };
  return `<span class="ctb-status ${status}">${labels[status] || status}</span>`;
}

function _ctbRegimeLabel(r) {
  const map = {
    simples_nacional: 'Simples Nacional',
    lucro_presumido: 'Lucro Presumido',
    lucro_real: 'Lucro Real',
    mei: 'MEI',
    isento: 'Isento',
    outro: 'Outro',
  };
  return map[r] || r || '—';
}

// Ícone SVG — edit
const _icoEdit = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`;
const _icoTrash = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>`;
const _icoEye   = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
const _icoCheck = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
const _icoRefresh = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`;
const _icoDocs  = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`;

function _btnAct(onclick, icon, title, cls='') {
  return `<button class="btn-icon-act ${cls}" onclick="${onclick}" title="${title}">${icon}</button>`;
}

// ── Feed ──────────────────────────────────────────────────────────────────────

async function _renderFeed() {
  try {
    const res = await fetch('/api/contabil/feed?limit=30');
    if (!res.ok) return;
    const items = await res.json();
    const list = document.getElementById('ctbFeedList');
    if (!list) return;
    if (!items.length) {
      list.innerHTML = '<div class="ctb-feed-empty">Sem atividade recente</div>';
      return;
    }
    list.innerHTML = items.map(i => `
      <div class="ctb-feed-item">
        <span class="ctb-feed-dot ${i.tipo}"></span>
        <span class="ctb-feed-text">
          ${i.empresa_nome ? `<strong>${i.empresa_nome}</strong> — ` : ''}${i.descricao}
        </span>
        <span class="ctb-feed-time">${_ctbFmt(i.criado_em)}</span>
      </div>
    `).join('');
  } catch (e) {
    console.error('[ctb] feed error', e);
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// ctbDashboard — Gestão de Documentos
// ══════════════════════════════════════════════════════════════════════════════

window.ctbDashboard = (() => {
  let _allDocs = [];

  async function reload() {
    try {
      const res = await fetch('/api/contabil/dashboard');
      if (!res.ok) throw new Error(res.statusText);
      const d = await res.json();

      const el = id => document.getElementById(id);
      el('ctbDocsHoje').textContent  = d.docs_hoje ?? '0';
      el('ctbPendencias').textContent = d.pendencias ?? '0';
      el('ctbTaxaOcr').textContent   = (d.taxa_ocr ?? 0) + '%';

      _allDocs = d.documentos || [];
      _renderDocs(_allDocs);
      await _renderFeed();
    } catch (e) {
      console.error('[ctb] dashboard reload error', e);
    }
  }

  function filtrar() {
    const status = document.getElementById('ctbFiltroStatus')?.value || '';
    const filtered = status ? _allDocs.filter(d => d.status === status) : _allDocs;
    _renderDocs(filtered);
  }

  function _renderDocs(docs) {
    const tbody = document.getElementById('ctbDocsTbody');
    if (!tbody) return;
    if (!docs.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="ctb-table-empty">Nenhum documento encontrado</td></tr>';
      return;
    }
    tbody.innerHTML = docs.map(d => `
      <tr>
        <td><strong>${d.empresa_nome || '—'}</strong></td>
        <td style="color:var(--text-mid);font-size:.78rem">${d.arquivo_nome || '—'}</td>
        <td style="font-size:.78rem;color:var(--text-mid)">${_ctbFmt(d.created_at)}</td>
        <td>${_ctbStatusChip(d.status)}</td>
        <td style="text-align:right;white-space:nowrap">
          <div style="display:inline-flex;gap:.25rem">
            ${_btnAct(`ctbManual.abrir(${d.id})`, _icoEdit, 'Revisar / Editar')}
            ${d.status !== 'aprovado'
              ? _btnAct(`ctbDashboard.aprovar(${d.id})`, _icoCheck, 'Aprovar', 'success')
              : ''}
            ${d.status === 'ocr_erro'
              ? _btnAct(`ctbDashboard.reprocessar(${d.id})`, _icoRefresh, 'Re-processar OCR')
              : ''}
          </div>
        </td>
      </tr>
    `).join('');
  }

  async function aprovar(docId) {
    const res = await fetch(`/api/contabil/documentos/${docId}/aprovar`, { method:'PUT' });
    if (res.ok) { await reload(); }
    else _ctbAlert('alertCtbDashboard', 'Erro ao aprovar documento.');
  }

  async function reprocessar(docId) {
    const res = await fetch(`/api/contabil/documentos/${docId}/reprocessar`, { method:'PUT' });
    if (res.ok) {
      _ctbAlert('alertCtbDashboard', 'Reprocessamento iniciado!', 'success');
      setTimeout(reload, 2000);
    } else _ctbAlert('alertCtbDashboard', 'Erro ao reprocessar.');
  }

  return { reload, filtrar, aprovar, reprocessar };
})();


// ══════════════════════════════════════════════════════════════════════════════
// ctbEmpresas — Cadastro de Empresas
// ══════════════════════════════════════════════════════════════════════════════

window.ctbEmpresas = (() => {
  let _all = [];

  async function carregar() {
    try {
      const res = await fetch('/api/contabil/empresas');
      if (!res.ok) return;
      _all = await res.json();
      _renderLista(_all);
    } catch (e) {
      console.error('[ctb] empresas load error', e);
    }
  }

  function buscar(q) {
    const ql = q.toLowerCase();
    const filtered = q
      ? _all.filter(e => e.nome.toLowerCase().includes(ql)
          || (e.cnpj || '').includes(ql)
          || (e.telefone || '').includes(ql))
      : _all;
    _renderLista(filtered);
  }

  function _renderLista(lista) {
    const el = document.getElementById('ctbEmpLista');
    if (!el) return;
    if (!lista.length) {
      el.innerHTML = `
        <div style="text-align:center;padding:3rem 1rem;color:var(--text-mid)">
          <div style="width:56px;height:56px;border-radius:16px;background:var(--accent-soft);
            border:1.5px solid var(--accent-mid);display:flex;align-items:center;
            justify-content:center;margin:0 auto 1rem">
            <svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 24 24"
              fill="none" stroke="var(--accent)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>
            </svg>
          </div>
          <div style="font-size:.95rem;font-weight:600;color:var(--text);margin-bottom:.35rem">Nenhuma empresa cadastrada</div>
          <div style="font-size:.8rem;margin-bottom:1.25rem">Cadastre a primeira empresa para começar a receber documentos fiscais via WhatsApp.</div>
          <button class="btn btn-primary btn-sm" onclick="ctbEmpresas.novaEmpresa()">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            Cadastrar Primeira Empresa
          </button>
        </div>`;
      return;
    }
    el.innerHTML = lista.map(e => {
      const initials = e.nome.split(' ').slice(0,2).map(w=>w[0]).join('').toUpperCase();
      const tel = e.telefone ? `+55 ${e.telefone}` : '';
      return `
      <div class="ctb-emp-row">
        <div class="ctb-emp-avatar">${initials}</div>
        <div class="ctb-emp-info">
          <div class="ctb-emp-nome">${e.nome}</div>
          <div class="ctb-emp-meta">
            ${e.cnpj ? `<span>${e.cnpj}</span><span class="ctb-meta-dot">·</span>` : ''}
            <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:2px"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/></svg>
            ${tel}
            <span class="ctb-meta-dot">·</span>
            <span class="ctb-regime-chip">${_ctbRegimeLabel(e.regime_tributario)}</span>
            ${e.cidade ? `<span class="ctb-meta-dot">·</span><span>${e.cidade}${e.uf?' / '+e.uf:''}</span>` : ''}
          </div>
        </div>
        <div class="ctb-emp-actions">
          ${_btnAct(`ctbEmpresas.editar(${e.id})`, _icoEdit, 'Editar empresa')}
          ${_btnAct(`ctbEmpresas.excluir(${e.id}, '${e.nome.replace(/'/g,"\\'")}')`, _icoTrash, 'Excluir empresa', 'danger')}
        </div>
      </div>`;
    }).join('');
  }

  function _abrirModalEmpresa() {
    const m = document.getElementById('modalCtbEmpresa');
    if (m) m.classList.add('open');
  }

  function fecharModal() {
    const m = document.getElementById('modalCtbEmpresa');
    if (m) m.classList.remove('open');
  }

  function novaEmpresa() {
    document.getElementById('ctbEmpId').value = '';
    document.getElementById('ctbEmpFormTitulo').textContent = 'Nova Empresa';
    const btn = document.getElementById('btnCtbSalvarEmpresa');
    if (btn) { btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg> Salvar e Enviar Boas-Vindas'; }
    ['ctbEmpNome','ctbEmpCnpj','ctbEmpIe','ctbEmpCpf','ctbEmpRg',
     'ctbEmpEndereco','ctbEmpCidade','ctbEmpUf','ctbEmpTelefone','ctbEmpEmail']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    document.getElementById('ctbEmpRegime').value = 'simples_nacional';
    const al = document.getElementById('alertCtbEmpForm');
    if (al) al.style.display = 'none';
    _abrirModalEmpresa();
  }

  async function editar(id) {
    try {
      const res = await fetch(`/api/contabil/empresas/${id}`);
      if (!res.ok) return;
      const e = await res.json();
      document.getElementById('ctbEmpId').value = e.id;
      document.getElementById('ctbEmpNome').value = e.nome || '';
      document.getElementById('ctbEmpCnpj').value = e.cnpj || '';
      document.getElementById('ctbEmpIe').value   = e.ie || '';
      document.getElementById('ctbEmpCpf').value  = e.cpf || '';
      document.getElementById('ctbEmpRg').value   = e.rg || '';
      document.getElementById('ctbEmpEndereco').value = e.endereco || '';
      document.getElementById('ctbEmpCidade').value   = e.cidade || '';
      document.getElementById('ctbEmpUf').value   = e.uf || '';
      document.getElementById('ctbEmpTelefone').value = e.telefone || '';
      document.getElementById('ctbEmpEmail').value    = e.email || '';
      document.getElementById('ctbEmpRegime').value   = e.regime_tributario || 'simples_nacional';
      document.getElementById('ctbEmpFormTitulo').textContent = 'Editar Empresa';
      const btn = document.getElementById('btnCtbSalvarEmpresa');
      if (btn) { btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg> Salvar Alterações'; }
      const al = document.getElementById('alertCtbEmpForm');
      if (al) al.style.display = 'none';
      _abrirModalEmpresa();
    } catch (e) {
      console.error('[ctb] editar empresa', e);
    }
  }

  async function salvar() {
    const id = document.getElementById('ctbEmpId').value;
    const nome = document.getElementById('ctbEmpNome').value.trim();
    const telefone = document.getElementById('ctbEmpTelefone').value.trim().replace(/\D/g, '');
    if (!nome) { _ctbAlert('alertCtbEmpForm', 'Nome é obrigatório.'); return; }
    if (!telefone) { _ctbAlert('alertCtbEmpForm', 'Telefone é obrigatório.'); return; }

    const body = {
      nome,
      cnpj:    document.getElementById('ctbEmpCnpj').value.trim() || null,
      ie:      document.getElementById('ctbEmpIe').value.trim() || null,
      cpf:     document.getElementById('ctbEmpCpf').value.trim() || null,
      rg:      document.getElementById('ctbEmpRg').value.trim() || null,
      endereco: document.getElementById('ctbEmpEndereco').value.trim() || null,
      cidade:  document.getElementById('ctbEmpCidade').value.trim() || null,
      uf:      document.getElementById('ctbEmpUf').value.trim().toUpperCase() || null,
      telefone,
      email:   document.getElementById('ctbEmpEmail').value.trim() || null,
      regime_tributario: document.getElementById('ctbEmpRegime').value,
    };

    const url   = id ? `/api/contabil/empresas/${id}` : '/api/contabil/empresas';
    const method = id ? 'PUT' : 'POST';

    const res = await fetch(url, {
      method, headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (res.ok) {
      fecharModal();
      _ctbAlert('alertCtbEmpLista',
        id ? 'Empresa atualizada com sucesso!' : 'Empresa cadastrada! Boas-vindas enviadas via WhatsApp.',
        'success');
      await carregar();
    } else {
      const d = await res.json().catch(() => ({}));
      _ctbAlert('alertCtbEmpForm', d.detail || 'Erro ao salvar empresa.');
    }
  }

  async function excluir(id, nome) {
    if (!confirm(`Excluir "${nome}"? Esta ação também remove todos os documentos.`)) return;
    const res = await fetch(`/api/contabil/empresas/${id}`, { method: 'DELETE' });
    if (res.ok || res.status === 204) {
      _ctbAlert('alertCtbEmpLista', `Empresa "${nome}" excluída.`, 'success');
      await carregar();
    } else {
      _ctbAlert('alertCtbEmpLista', 'Erro ao excluir empresa.');
    }
  }

  return { carregar, buscar, novaEmpresa, fecharModal, editar, salvar, excluir };
})();


// ══════════════════════════════════════════════════════════════════════════════
// ctbArquivos — Gestão de Arquivos
// ══════════════════════════════════════════════════════════════════════════════

window.ctbArquivos = (() => {
  let _empresaId = null;
  let _allEmp = [];
  let _allDocs = [];

  async function carregar() {
    try {
      const res = await fetch('/api/contabil/empresas');
      if (!res.ok) return;
      _allEmp = await res.json();
      _renderEmpGrid(_allEmp);
    } catch (e) { console.error('[ctb] arquivos load', e); }
  }

  function buscar(q) {
    const ql = q.toLowerCase();
    _renderEmpGrid(q ? _allEmp.filter(e => e.nome.toLowerCase().includes(ql)) : _allEmp);
  }

  function _renderEmpGrid(lista) {
    const el = document.getElementById('ctbArqEmpGrid');
    if (!el) return;
    if (!lista.length) {
      el.innerHTML = '<div class="ctb-table-empty">Nenhuma empresa encontrada</div>';
      return;
    }
    el.innerHTML = lista.map(e => {
      const initials = e.nome.split(' ').slice(0,2).map(w=>w[0]).join('').toUpperCase();
      const total = (e.docs_total || e.total_docs || 0);
      const pend  = (e.docs_pendentes || e.pendentes || 0);
      const ok    = (e.docs_aprovados || e.aprovados || 0);
      const err   = (e.docs_erro || e.erros || 0);
      return `<div class="ctb-arq-card" onclick="ctbArquivos.abrirEmpresa(${e.id}, '${e.nome.replace(/'/g,"\\'")}')">
      <div class="ctb-arq-card-header">
        <div class="ctb-arq-card-avatar">${initials}</div>
        <div>
          <div class="ctb-arq-card-name">${e.nome}</div>
          <div class="ctb-arq-card-cnpj">${e.cnpj || e.regime_tributario || ''}</div>
        </div>
      </div>
      <div class="ctb-arq-card-stats">
        <span class="ctb-arq-stat-pill total">${total} doc${total!==1?'s':''}</span>
        ${pend  ? `<span class="ctb-arq-stat-pill pending">${pend} pendente${pend!==1?'s':''}</span>` : ''}
        ${ok    ? `<span class="ctb-arq-stat-pill ok">${ok} aprovado${ok!==1?'s':''}</span>` : ''}
        ${err   ? `<span class="ctb-arq-stat-pill err">${err} erro${err!==1?'s':''}</span>` : ''}
      </div>
    </div>`;
    }).join('');
  }

  async function abrirEmpresa(id, nome) {
    _empresaId = id;
    document.getElementById('ctbArqEmpNome').textContent = nome;
    document.getElementById('ctbArqDocPanel').style.display = 'block';
    document.getElementById('ctbUploadInput').dataset.empresaId = id;
    await _carregarDocs();
    document.getElementById('ctbArqDocPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function fecharPanel() {
    document.getElementById('ctbArqDocPanel').style.display = 'none';
    _empresaId = null;
  }

  async function _carregarDocs() {
    if (!_empresaId) return;
    try {
      const status = document.getElementById('ctbArqFiltroStatus')?.value || '';
      let url = `/api/contabil/documentos?empresa_id=${_empresaId}`;
      if (status) url += `&status=${status}`;
      const res = await fetch(url);
      if (!res.ok) return;
      _allDocs = await res.json();
      _renderDocs(_allDocs);
    } catch (e) { console.error('[ctb] docs load', e); }
  }

  function filtrarDocs() { _carregarDocs(); }

  function _renderDocs(docs) {
    const tbody = document.getElementById('ctbArqDocTbody');
    if (!tbody) return;
    if (!docs.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="ctb-table-empty">Nenhum documento encontrado</td></tr>';
      return;
    }
    tbody.innerHTML = docs.map(d => `
      <tr>
        <td style="font-size:.78rem;color:var(--text-mid)">${d.arquivo_nome || '—'}</td>
        <td style="font-size:.8rem">${d.emitente_nome || '—'}</td>
        <td style="font-family:monospace;font-size:.72rem;color:var(--text-mid)">
          ${d.numero_nf ? `NF ${d.numero_nf}` : '—'}
        </td>
        <td style="font-weight:600">${_ctbFmtBRL(d.valor_total)}</td>
        <td style="font-size:.78rem">${d.data_emissao ? _ctbFmtDate(d.data_emissao) : '—'}</td>
        <td>${_ctbStatusChip(d.status)}</td>
        <td style="text-align:right;white-space:nowrap">
          <div style="display:inline-flex;gap:.25rem">
            ${_btnAct(`ctbManual.abrir(${d.id})`, _icoEdit,
              d.status === 'ocr_erro' || d.status === 'revisao_manual' ? 'Editar / Revisar' : 'Ver detalhes')}
            ${d.status !== 'aprovado'
              ? _btnAct(`ctbArquivos.aprovar(${d.id})`, _icoCheck, 'Aprovar', 'success')
              : ''}
            ${d.status === 'ocr_erro'
              ? _btnAct(`ctbArquivos.reprocessar(${d.id})`, _icoRefresh, 'Re-processar OCR')
              : ''}
          </div>
        </td>
      </tr>
    `).join('');
  }

  async function uploadDoc(input) {
    const file = input.files[0];
    if (!file) return;
    const empresaId = input.dataset.empresaId || _empresaId;
    if (!empresaId) { _ctbAlert('alertCtbArqDocs', 'Selecione uma empresa primeiro.'); return; }

    const fd = new FormData();
    fd.append('arquivo', file);

    _ctbAlert('alertCtbArqDocs', 'Enviando e iniciando extração OCR…', 'success');
    const res = await fetch(`/api/contabil/documentos/upload?empresa_id=${empresaId}`, {
      method: 'POST', body: fd,
    });
    input.value = '';
    if (res.ok) {
      _ctbAlert('alertCtbArqDocs', 'Documento enviado! OCR iniciado em background.', 'success');
      setTimeout(_carregarDocs, 1500);
    } else {
      const d = await res.json().catch(() => ({}));
      _ctbAlert('alertCtbArqDocs', d.detail || 'Erro ao enviar documento.');
    }
  }

  async function aprovar(docId) {
    const res = await fetch(`/api/contabil/documentos/${docId}/aprovar`, { method: 'PUT' });
    if (res.ok) await _carregarDocs();
    else _ctbAlert('alertCtbArqDocs', 'Erro ao aprovar.');
  }

  async function reprocessar(docId) {
    const res = await fetch(`/api/contabil/documentos/${docId}/reprocessar`, { method: 'PUT' });
    if (res.ok) {
      _ctbAlert('alertCtbArqDocs', 'OCR re-iniciado!', 'success');
      setTimeout(_carregarDocs, 2000);
    } else _ctbAlert('alertCtbArqDocs', 'Erro ao reprocessar.');
  }

  return { carregar, buscar, abrirEmpresa, fecharPanel, filtrarDocs, uploadDoc, aprovar, reprocessar };
})();


// ══════════════════════════════════════════════════════════════════════════════
// ctbManual — Modal de revisão / entrada manual
// ══════════════════════════════════════════════════════════════════════════════

window.ctbManual = (() => {

  async function abrir(docId) {
    document.getElementById('ctbManualDocId').value = docId;
    document.getElementById('alertCtbManual').style.display = 'none';
    _limparForm();

    try {
      const res = await fetch(`/api/contabil/documentos/${docId}`);
      if (!res.ok) return;
      const d = await res.json();

      // Arquivo preview
      const wrap = document.getElementById('ctbManualArquivoWrap');
      if (d.arquivo_path && d.arquivo_mime) {
        const url = `/api/contabil/documentos/${docId}/arquivo`;
        if (d.arquivo_mime.startsWith('image/')) {
          wrap.innerHTML = `<img src="${url}" style="max-width:100%;max-height:280px;border-radius:8px;object-fit:contain" alt="NF">`;
        } else {
          wrap.innerHTML = `<a href="${url}" target="_blank" class="btn btn-ghost btn-sm">
            📄 Abrir arquivo (${d.arquivo_nome || 'documento'})
          </a>`;
        }
      } else {
        wrap.innerHTML = `<span style="color:var(--text-light);font-size:.8rem">Arquivo não disponível</span>`;
      }

      // Popula a partir dos dados OCR ou manual
      const src = d.dados_manual || d.dados_ocr || {};
      const emit = src.emitente || {};
      const dest = src.destinatario || {};
      const totais = src.totais || {};

      _set('ctbManualTipo',       d.tipo || src.tipo || 'nfe');
      _set('ctbManualNumero',     d.numero_nf || src.numero_nf || '');
      _set('ctbManualSerie',      src.serie || '');
      _set('ctbManualDataEmissao', d.data_emissao ? d.data_emissao.slice(0,10) : (src.data_emissao || ''));
      _set('ctbManualNatureza',   src.natureza_operacao || '');
      _set('ctbManualChave',      d.chave_acesso || src.chave_acesso || '');
      _set('ctbManualValorTotal', d.valor_total || totais.valor_total_nf || '');
      _set('ctbManualEmitNome',   d.emitente_nome || emit.nome || '');
      _set('ctbManualEmitCnpj',   d.emitente_cnpj || emit.cnpj || '');
      _set('ctbManualDestNome',   d.destinatario_nome || dest.nome || '');
      _set('ctbManualDestDoc',    d.destinatario_cnpj || dest.cnpj || dest.cpf || '');
      _set('ctbManualObs',        src.observacoes || '');

    } catch (e) {
      console.error('[ctb] abrir manual', e);
    }

    openModal('modalCtbManual');
  }

  function _set(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val ?? '';
  }

  function _limparForm() {
    ['ctbManualTipo','ctbManualNumero','ctbManualSerie','ctbManualDataEmissao',
     'ctbManualNatureza','ctbManualChave','ctbManualValorTotal',
     'ctbManualEmitNome','ctbManualEmitCnpj','ctbManualDestNome','ctbManualDestDoc','ctbManualObs']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  }

  function _coletarDados() {
    return {
      tipo:              document.getElementById('ctbManualTipo').value,
      numero_nf:         document.getElementById('ctbManualNumero').value.trim() || null,
      serie:             document.getElementById('ctbManualSerie').value.trim() || null,
      data_emissao:      document.getElementById('ctbManualDataEmissao').value || null,
      natureza_operacao: document.getElementById('ctbManualNatureza').value.trim() || null,
      chave_acesso:      document.getElementById('ctbManualChave').value.trim() || null,
      valor_total:       parseFloat(document.getElementById('ctbManualValorTotal').value) || null,
      emitente_nome:     document.getElementById('ctbManualEmitNome').value.trim() || null,
      emitente_cnpj:     document.getElementById('ctbManualEmitCnpj').value.trim().replace(/\D/g,'') || null,
      destinatario_nome: document.getElementById('ctbManualDestNome').value.trim() || null,
      destinatario_cnpj: document.getElementById('ctbManualDestDoc').value.trim().replace(/\D/g,'') || null,
      observacoes:       document.getElementById('ctbManualObs').value.trim() || null,
    };
  }

  async function salvar() {
    const docId = document.getElementById('ctbManualDocId').value;
    const body = _coletarDados();
    const res = await fetch(`/api/contabil/documentos/${docId}/manual`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      closeModal('modalCtbManual');
      ctbDashboard.reload();
      ctbArquivos.filtrarDocs?.();
    } else {
      _ctbAlert('alertCtbManual', 'Erro ao salvar revisão.');
    }
  }

  async function aprovar() {
    const docId = document.getElementById('ctbManualDocId').value;
    // Salva primeiro, depois aprova
    const body = _coletarDados();
    await fetch(`/api/contabil/documentos/${docId}/manual`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const res = await fetch(`/api/contabil/documentos/${docId}/aprovar`, { method: 'PUT' });
    if (res.ok) {
      closeModal('modalCtbManual');
      ctbDashboard.reload();
    } else {
      _ctbAlert('alertCtbManual', 'Erro ao aprovar documento.');
    }
  }

  return { abrir, salvar, aprovar };
})();


// ══════════════════════════════════════════════════════════════════════════════
// Integração com o sistema de páginas (onPageLoad)
// ══════════════════════════════════════════════════════════════════════════════

(function _hookContabil() {
  // Aguarda o onPageLoad global estar disponível
  const _origOnPageLoad = window.onPageLoad;
  window.onPageLoad = function(page) {
    if (typeof _origOnPageLoad === 'function') _origOnPageLoad(page);
    switch (page) {
      case 'ctb-dashboard': ctbDashboard.reload(); break;
      case 'ctb-empresas':  ctbEmpresas.carregar(); break;
      case 'ctb-arquivos':  ctbArquivos.carregar(); break;
    }
  };
})();
