/**
 * usuarios.js — Gerenciamento de usuários do ZapDin
 * Tela: Sistema → Usuários
 */

(function () {
  'use strict';

  // ── Estado ────────────────────────────────────────────────────────────────────
  let _usuariosPendente = null; // { id, username } aguardando ação no modal
  let _senhaAlvoId = null;
  let _senhaAlvoNome = null;

  // ── Helpers de UI ─────────────────────────────────────────────────────────────
  function _msg(id, txt, ok) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = txt;
    el.style.color = ok ? 'var(--primary-deep)' : 'var(--red)';
  }

  function _fmtData(iso) {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleDateString('pt-BR', {
        day: '2-digit', month: '2-digit', year: 'numeric'
      });
    } catch {
      return iso;
    }
  }

  // ── Listar usuários ───────────────────────────────────────────────────────────
  async function usrCarregar() {
    const loading = document.getElementById('usrListaLoading');
    const table   = document.getElementById('usrListaTable');
    const empty   = document.getElementById('usrListaEmpty');
    const tbody   = document.getElementById('usrListaTbody');
    if (!tbody) return;

    if (loading) loading.style.display = 'block';
    if (table)  table.style.display   = 'none';
    if (empty)  empty.style.display   = 'none';

    try {
      const res  = await fetch('/api/auth/usuarios');
      const data = await res.json();

      if (loading) loading.style.display = 'none';

      if (!Array.isArray(data) || data.length === 0) {
        if (empty) empty.style.display = 'block';
        return;
      }

      tbody.innerHTML = data.map(u => `
        <tr style="border-bottom:1px solid var(--border)">
          <td style="padding:.6rem .75rem;font-size:.88rem;font-weight:500">
            <span style="display:inline-flex;align-items:center;gap:.4rem">
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
              </svg>
              ${_esc(u.username)}
            </span>
            ${u.email ? `<div style="font-size:.74rem;color:var(--text-3);margin-top:2px;padding-left:21px">${_esc(u.email)}</div>` : ''}
          </td>
          <td style="padding:.6rem .75rem;font-size:.82rem;color:var(--text-3)">${_fmtData(u.created_at)}</td>
          <td style="padding:.6rem .75rem;text-align:right">
            <div style="display:flex;gap:.5rem;justify-content:flex-end">
              <button class="btn btn-sm btn-ghost" onclick="usrAbrirSenha(${u.id}, '${_esc(u.username)}')">Alterar senha</button>
              <button class="btn btn-sm" style="background:var(--red-bg);color:var(--red);border:none"
                onclick="usrAbrirDel(${u.id}, '${_esc(u.username)}')">Remover</button>
            </div>
          </td>
        </tr>
      `).join('');

      if (table) table.style.display = 'table';
    } catch (e) {
      if (loading) { loading.textContent = 'Erro ao carregar usuários.'; loading.style.color = 'var(--red)'; }
    }
  }

  function _esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // ── Criar usuário ─────────────────────────────────────────────────────────────
  async function usrCriar() {
    const email     = (document.getElementById('usrNovoEmail')?.value || '').trim().toLowerCase();
    const username  = (document.getElementById('usrNovoUsername')?.value || '').trim().toLowerCase();
    const senha     = document.getElementById('usrNovoSenha')?.value || '';   // opcional
    const sendEmail = document.getElementById('usrNovoSendEmail')?.checked ?? true;
    const msgEl     = 'usrCriarMsg';

    if (!email || !email.includes('@')) { _msg(msgEl, 'Informe um e-mail válido.', false); return; }
    if (!username) { _msg(msgEl, 'Informe o nome de usuário.', false); return; }
    if (senha && senha.length < 6) { _msg(msgEl, 'Senha muito curta (mínimo 6 caracteres) ou deixe vazio.', false); return; }

    _msg(msgEl, 'Salvando…', true);
    try {
      const payload = { username, email, send_welcome_email: sendEmail };
      if (senha) payload.password = senha;
      const res = await fetch('/api/auth/usuarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        _msg(msgEl, data.detail || 'Erro ao criar usuário.', false);
        return;
      }
      let msg = `Usuário "${username}" criado!`;
      if (data.auto_password && data.temp_password) {
        msg += data.email_status === 'sent'
          ? ` E-mail enviado para ${email}.`
          : ` Senha temporária: ${data.temp_password} (e-mail não enviado: ${data.email_status}).`;
      } else if (data.email_status === 'sent') {
        msg += ` E-mail de boas-vindas enviado.`;
      }
      _msg(msgEl, msg, true);
      document.getElementById('usrNovoEmail').value    = '';
      document.getElementById('usrNovoUsername').value = '';
      document.getElementById('usrNovoSenha').value    = '';
      await usrCarregar();
    } catch {
      _msg(msgEl, 'Erro de conexão.', false);
    }
  }

  // ── Modal: Alterar senha ──────────────────────────────────────────────────────
  function usrAbrirSenha(id, nome) {
    _senhaAlvoId   = id;
    _senhaAlvoNome = nome;
    const el = document.getElementById('usrModalSenhaNome');
    if (el) el.textContent = nome;
    const nova = document.getElementById('usrModalSenhaNova');
    const conf = document.getElementById('usrModalSenhaConf');
    if (nova) nova.value = '';
    if (conf) conf.value = '';
    _msg('usrModalSenhaMsg', '', true);
    const modal = document.getElementById('usrModalSenha');
    if (modal) modal.style.display = 'flex';
  }

  function usrModalSenhaFechar() {
    const modal = document.getElementById('usrModalSenha');
    if (modal) modal.style.display = 'none';
    _senhaAlvoId = null;
    _senhaAlvoNome = null;
  }

  async function usrSalvarSenha() {
    if (!_senhaAlvoId) return;
    const nova = document.getElementById('usrModalSenhaNova')?.value || '';
    const conf = document.getElementById('usrModalSenhaConf')?.value || '';

    if (nova.length < 6) { _msg('usrModalSenhaMsg', 'Senha muito curta (mínimo 6 caracteres).', false); return; }
    if (nova !== conf)   { _msg('usrModalSenhaMsg', 'As senhas não coincidem.', false); return; }

    _msg('usrModalSenhaMsg', 'Salvando…', true);
    try {
      const res = await fetch(`/api/auth/usuarios/${_senhaAlvoId}/senha`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: nova }),
      });
      if (!res.ok) {
        const data = await res.json();
        _msg('usrModalSenhaMsg', data.detail || 'Erro ao alterar senha.', false);
        return;
      }
      usrModalSenhaFechar();
    } catch {
      _msg('usrModalSenhaMsg', 'Erro de conexão.', false);
    }
  }

  // ── Modal: Confirmar exclusão ─────────────────────────────────────────────────
  function usrAbrirDel(id, nome) {
    _usuariosPendente = { id, username: nome };
    const el = document.getElementById('usrModalDelNome');
    if (el) el.textContent = nome;
    const modal = document.getElementById('usrModalDel');
    if (modal) modal.style.display = 'flex';
  }

  function usrModalDelFechar() {
    const modal = document.getElementById('usrModalDel');
    if (modal) modal.style.display = 'none';
    _usuariosPendente = null;
  }

  async function usrConfirmarDel() {
    if (!_usuariosPendente) return;
    const { id } = _usuariosPendente;
    usrModalDelFechar();
    try {
      await fetch(`/api/auth/usuarios/${id}`, { method: 'DELETE' });
      await usrCarregar();
    } catch {
      // silently ignore — table will refresh on next load
    }
  }

  // ── Inicialização ─────────────────────────────────────────────────────────────
  // Carrega lista quando o painel de usuários é exibido
  document.addEventListener('sys-panel-activated', function (e) {
    if (e.detail === 'usuarios') usrCarregar();
  });

  // Fechar modais clicando no backdrop
  ['usrModalSenha', 'usrModalDel'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('click', function (e) {
        if (e.target === el) {
          id === 'usrModalSenha' ? usrModalSenhaFechar() : usrModalDelFechar();
        }
      });
    }
  });

  // ── Exports globais ───────────────────────────────────────────────────────────
  window.usrCarregar        = usrCarregar;
  window.usrCriar           = usrCriar;
  window.usrAbrirSenha      = usrAbrirSenha;
  window.usrModalSenhaFechar = usrModalSenhaFechar;
  window.usrSalvarSenha     = usrSalvarSenha;
  window.usrAbrirDel        = usrAbrirDel;
  window.usrModalDelFechar  = usrModalDelFechar;
  window.usrConfirmarDel    = usrConfirmarDel;
})();
