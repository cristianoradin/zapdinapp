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
      success: { bg: 'var(--primary-soft)', border: '#22c55e', text: '#15803d', icon: '✅' },
      error:   { bg: 'var(--red-bg)', border: 'var(--red)', text: 'var(--red)', icon: '❌' },
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

  // ── Catálogo de erros (técnico → linguagem do usuário) ──────────────────────
  // Fonte única usada por dashboard, campanha, arquivos, etc.
  // Cada entrada: regex no texto do erro (minúsculo) → {icon, titulo, descricao, acao}.
  // Ordem importa: do mais específico pro mais genérico.
  const _CATALOGO_ERROS = [
    {
      re: /n[ãa]o est[áa] no whats|numero inv[áa]lid|n[úu]mero inv[áa]lid|invalid number|composer n[ãa]o encontrad|n[ãa]o (foi )?encontrad.*(whats|chat)|exists.*false|not.*on whatsapp|chat n[ãa]o abriu/,
      icon: '🚫', titulo: 'Número não tem WhatsApp',
      descricao: 'Este número não possui conta no WhatsApp (ou foi digitado errado).',
      acao: 'Confira o número no cadastro do contato — DDD certo, sem dígitos a mais/menos.',
    },
    {
      re: /bloque|blocked|spam|report/,
      icon: '⛔', titulo: 'Cliente pode ter bloqueado',
      descricao: 'O WhatsApp recusou a entrega — possível bloqueio pelo destinatário.',
      acao: 'Confirme com o cliente por outro canal. Evite reenviar várias vezes.',
    },
    {
      re: /banid|ban|suspens|forbidden|403|conta desconectada pelo whatsapp/,
      icon: '🚷', titulo: 'Número de envio com restrição',
      descricao: 'O WhatsApp que envia pode estar com bloqueio/suspensão temporária.',
      acao: 'Reduza o volume de envios e aguarde. Se persistir, troque o número de envio.',
    },
    {
      re: /agent:|agente.*(off|desconect|n[ãa]o conect)/,
      icon: '🖥️', titulo: 'Agente do posto offline',
      descricao: 'O programa agente no computador do posto não está conectado.',
      acao: 'Verifique se o computador do posto está ligado e com internet. Reenvia sozinho ao reconectar.',
    },
    {
      re: /n[ãa]o est[áa] conectad|sem sess[ãa]o|desconect|qr|logged.?out|connection (closed|update)|reconect/,
      icon: '📴', titulo: 'WhatsApp desconectado',
      descricao: 'A sessão do WhatsApp caiu (ou precisa ler o QR de novo).',
      acao: 'Abra a tela de WhatsApp e reconecte (leia o QR Code se pedir).',
    },
    {
      re: /limite di[áa]rio|daily limit|limite atingid/,
      icon: '⏳', titulo: 'Limite diário atingido',
      descricao: 'O número já enviou o máximo de mensagens configurado para hoje.',
      acao: 'Aguarde o próximo dia ou aumente o limite em Configurações de Envio.',
    },
    {
      re: /hor[áa]rio|fora de hor|business hour/,
      icon: '🕐', titulo: 'Fora do horário de envio',
      descricao: 'O envio foi bloqueado pela janela de horário configurada.',
      acao: 'Ajuste o horário em Configurações de Envio ou aguarde a janela permitida.',
    },
    {
      re: /muito grand|too large|file size|payload|413|mídia|midia.*(grand|inv[áa]lid)|formato/,
      icon: '📎', titulo: 'Arquivo grande ou inválido',
      descricao: 'O arquivo é grande demais ou de um tipo não aceito pelo WhatsApp.',
      acao: 'Reduza o tamanho ou use um formato comum (PDF, JPG, PNG, MP3).',
    },
    {
      re: /timeout|tempo esgotad|timed out|n[ãa]o respond/,
      icon: '⌛', titulo: 'Demorou demais (timeout)',
      descricao: 'O envio não respondeu a tempo — geralmente internet lenta ou WhatsApp travado.',
      acao: 'Tente reenviar. Se repetir, reinicie a conexão do WhatsApp.',
    },
    {
      re: /http \d|internal server|evolution|50[0-9]|502|bad gateway|connection error|conex[ãa]o/,
      icon: '🛠️', titulo: 'Falha temporária no servidor',
      descricao: 'Erro temporário no serviço de envio do WhatsApp.',
      acao: 'Aguarde alguns minutos e reenvie. Se persistir, avise o suporte.',
    },
  ];

  // Traduz um texto de erro técnico num objeto amigável.
  // Retorna {icon, titulo, descricao, acao, tecnico}.
  window.traduzirErro = function traduzirErro(erro) {
    const tecnico = (erro || '').toString().trim();
    const e = tecnico.toLowerCase();
    if (!e) {
      return { icon: '❔', titulo: 'Motivo não registrado',
               descricao: 'Não há detalhe do erro registrado.',
               acao: 'Tente reenviar.', tecnico: '' };
    }
    for (const item of _CATALOGO_ERROS) {
      if (item.re.test(e)) return { ...item, re: undefined, tecnico };
    }
    return { icon: '⚠️', titulo: 'Falha no envio',
             descricao: 'Não foi possível enviar a mensagem.',
             acao: 'Tente reenviar. Se persistir, avise o suporte.', tecnico };
  };

  // Monta o HTML padrão do bloco de erro (usado nos modais).
  window.erroBoxHtml = function erroBoxHtml(erro) {
    const m = window.traduzirErro(erro);
    return `
      <div style="padding:.7rem .9rem;border:1px solid var(--border);border-left:3px solid #e11d48;border-radius:8px;background:rgba(225,29,72,.05)">
        <div style="font-weight:700;font-size:.86rem;color:#be123c">${m.icon} ${m.titulo}</div>
        <div style="font-size:.8rem;color:var(--text-2,#555);margin-top:.25rem">${window.escHtml(m.descricao)}</div>
        ${m.acao ? `<div style="font-size:.78rem;color:var(--text-2,#555);margin-top:.3rem">👉 <b>O que fazer:</b> ${window.escHtml(m.acao)}</div>` : ''}
        ${m.tecnico ? `<details style="margin-top:.45rem"><summary style="font-size:.72rem;color:var(--text-3,#999);cursor:pointer">Detalhe técnico</summary><div style="font-size:.72rem;color:var(--text-3,#999);font-family:monospace;word-break:break-word;margin-top:.25rem">${window.escHtml(m.tecnico)}</div></details>` : ''}
      </div>`;
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
