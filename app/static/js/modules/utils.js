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
