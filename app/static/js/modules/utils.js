/**
 * modules/utils.js — Utilitários compartilhados entre todos os módulos.
 *
 * Expõe funções globais usadas em toda a SPA:
 *  - api()         → fetch com JSON e redirect 401 automático
 *  - showAlert()   → exibe alerta temporário em um elemento DOM
 *  - escHtml()     → escapa HTML para evitar XSS no innerHTML
 *  - _fmtPhone()   → formata número de telefone para exibição
 *  - _normPhone()  → normaliza número para formato 55DDDNUMERO
 *  - ZD.registry   → registro de onPageLoad por módulo
 */

(function () {
  'use strict';

  // ── API helper ─────────────────────────────────────────────────────────────
  window.api = async function api(method, url, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(url, opts);
    if (res.status === 401) { window.location.href = '/login'; return { ok: false }; }
    try {
      const data = await res.json();
      return { ...data, _status: res.status, ok: res.ok };
    } catch {
      return { ok: res.ok, _status: res.status };
    }
  };

  // ── Alert helper ───────────────────────────────────────────────────────────
  window.showAlert = function showAlert(id, msg, type = 'success') {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = msg;
    el.className = `alert alert-${type}`;
    el.style.display = 'block';
    setTimeout(() => (el.style.display = 'none'), 4000);
  };

  // ── Escape HTML ────────────────────────────────────────────────────────────
  window.escHtml = function escHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };

  // ── Phone helpers ──────────────────────────────────────────────────────────
  window._normPhone = function _normPhone(raw) {
    const d = raw.replace(/\D/g, '');
    if (d.startsWith('55') && d.length >= 12) return d;
    return '55' + d;
  };

  window._fmtPhone = function _fmtPhone(num) {
    const d = String(num).replace(/\D/g, '').replace(/^55/, '');
    if (d.length === 11) return `+55 (${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
    if (d.length === 10) return `+55 (${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
    return `+55 ${d}`;
  };

  // ── Toast notification ────────────────────────────────────────────────────
  // Cria uma notificação temporária no canto inferior direito da tela.
  // Uso: showToast('Mensagem enviada!', 'success')
  //      showToast('Erro ao salvar', 'error')
  //      showToast('Atenção: fila grande', 'warning', 6000)
  window.showToast = function showToast(msg, type = 'success', duration = 4000) {
    let container = document.getElementById('_toastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = '_toastContainer';
      container.style.cssText = [
        'position:fixed', 'bottom:1.25rem', 'right:1.25rem',
        'display:flex', 'flex-direction:column', 'gap:.5rem',
        'z-index:9999', 'pointer-events:none',
      ].join(';');
      document.body.appendChild(container);
    }

    const colors = {
      success: { bg: '#f0fdf4', border: '#22c55e', text: '#15803d', icon: '✅' },
      error:   { bg: '#fef2f2', border: '#ef4444', text: '#b91c1c', icon: '❌' },
      warning: { bg: '#fffbeb', border: '#f59e0b', text: '#92400e', icon: '⚠️' },
      info:    { bg: '#eff6ff', border: '#3b82f6', text: '#1d4ed8', icon: 'ℹ️' },
    };
    const c = colors[type] || colors.info;

    const toast = document.createElement('div');
    toast.style.cssText = [
      `background:${c.bg}`, `border:1px solid ${c.border}`, `color:${c.text}`,
      'border-radius:10px', 'padding:.625rem 1rem',
      'font-size:.85rem', 'font-weight:500',
      'box-shadow:0 4px 12px rgba(0,0,0,.12)',
      'display:flex', 'align-items:center', 'gap:.5rem',
      'pointer-events:auto', 'max-width:320px',
      'opacity:0', 'transform:translateY(8px)',
      'transition:opacity .25s ease,transform .25s ease',
    ].join(';');
    toast.innerHTML = `<span>${c.icon}</span><span>${String(msg)}</span>`;
    container.appendChild(toast);

    // Anima entrada
    requestAnimationFrame(() => {
      toast.style.opacity = '1';
      toast.style.transform = 'translateY(0)';
    });

    // Remove após duração
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(8px)';
      setTimeout(() => toast.remove(), 280);
    }, duration);
  };

  // ── Módulo registry ────────────────────────────────────────────────────────
  // Cada módulo pode registrar um handler de onPageLoad.
  // Uso: ZD.registry.register('minha-pagina', () => minhaFuncao())
  window.ZD = window.ZD || {};
  ZD.registry = {
    _handlers: {},
    register(page, fn) {
      this._handlers[page] = fn;
    },
    dispatch(page) {
      const fn = this._handlers[page];
      if (fn) fn();
    },
  };
})();
