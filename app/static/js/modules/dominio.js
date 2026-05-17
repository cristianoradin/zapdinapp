/**
 * dominio.js — Integração com o sistema Domínio (Thomson Reuters)
 * Módulo de configuração e log de envios
 */
(function () {
  'use strict';

  const API = '/api/dominio';

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function _setStatus(type, msg) {
    const dot  = document.getElementById('dominio-status-dot');
    const text = document.getElementById('dominio-status-text');
    if (!dot || !text) return;
    const colors = { ok: '#22c55e', error: '#ef4444', warn: '#f59e0b', idle: '#e5e7eb' };
    dot.style.background = colors[type] || colors.idle;
    text.textContent = msg;
    text.style.color = type === 'error' ? 'var(--red)' : 'var(--text-muted)';
  }

  function _alert(msg, type) {
    const el = document.getElementById('dominio-alert');
    if (!el) return;
    el.style.display = 'block';
    el.className = 'alert alert-' + (type || 'info');
    el.textContent = msg;
    if (type !== 'error') setTimeout(() => { el.style.display = 'none'; }, 4000);
  }

  // ── Máscara CNPJ ────────────────────────────────────────────────────────────

  function maskCnpj(input) {
    let v = input.value.replace(/\D/g, '').slice(0, 14);
    if (v.length > 12) v = v.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5');
    else if (v.length > 8) v = v.replace(/^(\d{2})(\d{3})(\d{3})(\d{0,4})/, '$1.$2.$3/$4');
    else if (v.length > 5) v = v.replace(/^(\d{2})(\d{3})(\d{0,3})/, '$1.$2.$3');
    else if (v.length > 2) v = v.replace(/^(\d{2})(\d{0,3})/, '$1.$2');
    input.value = v;
  }

  function toggleToken() {
    const inp = document.getElementById('dominio-api-token');
    if (!inp) return;
    inp.type = inp.type === 'password' ? 'text' : 'password';
  }

  // ── Carregar configuração ────────────────────────────────────────────────────

  async function carregar() {
    _setStatus('idle', 'Carregando configuração…');
    try {
      const res = await fetch(API + '/config');
      if (!res.ok) { _setStatus('error', 'Erro ao carregar configuração'); return; }
      const d = await res.json();

      _set('dominio-cnpj-origem',      d.cnpj_origem      || '');
      _set('dominio-nome-origem',      d.nome_origem      || '');
      _set('dominio-api-url',          d.api_url          || 'https://api.dominio.com.br/v1');
      _set('dominio-api-token',        d.api_token        || '');
      _set('dominio-cnpj-escritorio',  d.cnpj_escritorio  || '');
      _chk('dominio-tipo-nfe',   d.tipos ? d.tipos.includes('nfe')  : true);
      _chk('dominio-tipo-cte',   d.tipos ? d.tipos.includes('cte')  : false);
      _chk('dominio-tipo-nfse',  d.tipos ? d.tipos.includes('nfse') : false);
      _chk('dominio-tipo-cfe',   d.tipos ? d.tipos.includes('cfe')  : false);
      _chk('dominio-auto-envio', !!d.auto_envio);

      if (d.api_token) {
        _setStatus('ok', 'Integração configurada — clique em "Testar Conexão" para verificar');
      } else {
        _setStatus('warn', 'Token não configurado — preencha as credenciais abaixo');
      }

      await carregarLog();
    } catch (e) {
      _setStatus('error', 'Falha ao carregar: ' + e.message);
    }
  }

  function _set(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val;
  }

  function _chk(id, val) {
    const el = document.getElementById(id);
    if (el) el.checked = val;
  }

  function _get(id) {
    const el = document.getElementById(id);
    return el ? el.value.trim() : '';
  }

  function _getChk(id) {
    const el = document.getElementById(id);
    return el ? el.checked : false;
  }

  // ── Salvar configuração ──────────────────────────────────────────────────────

  async function salvar() {
    const token = _get('dominio-api-token');
    const url   = _get('dominio-api-url');
    if (!url) { _alert('Informe a URL base da API.', 'error'); return; }

    const tipos = [];
    if (_getChk('dominio-tipo-nfe'))  tipos.push('nfe');
    if (_getChk('dominio-tipo-cte'))  tipos.push('cte');
    if (_getChk('dominio-tipo-nfse')) tipos.push('nfse');
    if (_getChk('dominio-tipo-cfe'))  tipos.push('cfe');

    const payload = {
      cnpj_origem:     _get('dominio-cnpj-origem'),
      nome_origem:     _get('dominio-nome-origem'),
      api_url:         url,
      api_token:       token,
      cnpj_escritorio: _get('dominio-cnpj-escritorio'),
      tipos,
      auto_envio:      _getChk('dominio-auto-envio'),
    };

    try {
      const res = await fetch(API + '/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _alert(err.detail || 'Erro ao salvar configuração.', 'error');
        return;
      }
      _alert('Configuração salva com sucesso!', 'success');
      if (token) _setStatus('ok', 'Integração configurada');
    } catch (e) {
      _alert('Erro de conexão: ' + e.message, 'error');
    }
  }

  // ── Testar conexão ───────────────────────────────────────────────────────────

  async function testar() {
    const btn = document.getElementById('btnDominioTestar');
    if (btn) { btn.disabled = true; btn.textContent = 'Testando…'; }
    _setStatus('idle', 'Testando conexão com Domínio…');

    try {
      const res = await fetch(API + '/testar', { method: 'POST' });
      const d   = await res.json().catch(() => ({}));
      if (res.ok && d.ok) {
        _setStatus('ok', 'Conexão OK — ' + (d.mensagem || 'API respondeu com sucesso'));
        _alert('Conexão com Domínio bem-sucedida!', 'success');
      } else {
        _setStatus('error', 'Falha: ' + (d.detail || d.mensagem || 'Sem resposta da API'));
        _alert('Falha na conexão: ' + (d.detail || d.mensagem || 'Verifique token e URL'), 'error');
      }
    } catch (e) {
      _setStatus('error', 'Erro de rede: ' + e.message);
      _alert('Erro de rede ao testar: ' + e.message, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg> Testar Conexão`;
      }
    }
  }

  // ── Log de envios ────────────────────────────────────────────────────────────

  async function carregarLog() {
    const tbody = document.getElementById('dominioLogBody');
    if (!tbody) return;
    try {
      const res = await fetch(API + '/log?limit=50');
      if (!res.ok) return;
      const logs = await res.json();
      if (!logs.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="table-empty">Nenhum envio registrado</td></tr>';
        return;
      }
      const statusLabel = {
        sent:    '<span style="color:#22c55e;font-weight:600">✓ Enviado</span>',
        error:   '<span style="color:#ef4444;font-weight:600">✗ Erro</span>',
        pending: '<span style="color:#f59e0b">⌛ Pendente</span>',
      };
      tbody.innerHTML = logs.map(l => `<tr>
        <td style="white-space:nowrap;font-size:.8rem">${_fmtDate(l.created_at)}</td>
        <td style="font-size:.82rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(l.chave_nfe || '')}">
          ${esc(l.chave_nfe ? l.chave_nfe.slice(0, 24) + '…' : l.nome_arquivo || '—')}
        </td>
        <td><span style="font-size:.78rem;text-transform:uppercase;font-weight:600;color:var(--accent)">${esc(l.tipo_doc || '—')}</span></td>
        <td>${statusLabel[l.status] || esc(l.status)}</td>
        <td style="font-size:.78rem;color:var(--text-muted)">${esc(l.resposta || '—')}</td>
      </tr>`).join('');
    } catch (_) {
      // silencia
    }
  }

  function _fmtDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  }

  function esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Exposição pública ────────────────────────────────────────────────────────

  window.dominio = { carregar, salvar, testar, carregarLog, maskCnpj, toggleToken };
})();
