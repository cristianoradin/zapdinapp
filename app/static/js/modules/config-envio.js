/**
 * modules/config-envio.js — Página Configurações de Envio: delays, horário, spintax.
 * Registra: ZD.registry.register('config-envio', carregarConfigEnvio)
 */
(function () {
  'use strict';

  // ── Configurações de Envio ───────────────────────────────────────────────────

  async function carregarConfigEnvio() {
    const res = await fetch('/api/config');
    const cfg = res.ok ? await res.json() : {};
    const toNum = (v, def) => isNaN(parseFloat(v)) ? def : parseFloat(v);
    document.getElementById('waCfgDelayMin').value    = toNum(cfg.wa_delay_min,   5);
    document.getElementById('waCfgDelayMax').value    = toNum(cfg.wa_delay_max,  15);
    document.getElementById('waCfgDailyLimit').value  = toNum(cfg.wa_daily_limit, 0);
    document.getElementById('waCfgHoraInicio').value  = cfg.wa_hora_inicio || '08:00';
    document.getElementById('waCfgHoraFim').value     = cfg.wa_hora_fim    || '18:00';
    document.getElementById('waCfgHoraAtivo').checked = !!(cfg.wa_hora_inicio && cfg.wa_hora_fim);
    document.getElementById('waCfgSpintax').checked    = cfg.wa_spintax    !== '0';
    document.getElementById('waCfgComposing').checked  = cfg.wa_composing  !== '0';
    // Disjuntor + aquecimento (anti-ban)
    const setIf = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    setIf('waCfgMaxMin',      toNum(cfg.wa_max_per_min,  12));
    setIf('waCfgMaxHora',     toNum(cfg.wa_max_per_hour, 250));
    setIf('waCfgCooldownMin', Math.round(toNum(cfg.wa_cooldown_secs, 300) / 60));
    setIf('waCfgWarmup',      toNum(cfg.wa_warmup_msgs,  20));
    _carregarDispatchStatus();
    const alertEl = document.getElementById('waCfgAlert');
    const spinBox = document.getElementById('spinPreviewBox');
    if (alertEl) alertEl.style.display = 'none';
    if (spinBox) spinBox.classList.remove('visible');
  }

  async function _carregarDispatchStatus() {
    const box = document.getElementById('dispatchStatusBox');
    if (!box) return;
    try {
      const r = await fetch('/api/config/dispatch-status');
      const d = r.ok ? await r.json() : {};
      const ss = d.sessoes || [];
      if (!ss.length) { box.innerHTML = '<span style="color:var(--text-3)">Nenhuma sessão WhatsApp para monitorar.</span>'; return; }
      box.innerHTML = ss.map(s => {
        let tag, cor;
        if (s.cooldown_secs_left > 0) { tag = `⏸️ pausado (${s.cooldown_secs_left}s)`; cor = 'var(--red)'; }
        else if (s.warmup_left > 0)   { tag = `🔥 aquecendo (faltam ${s.warmup_left})`; cor = 'var(--amber,#b45309)'; }
        else                          { tag = '✅ normal'; cor = 'var(--primary-deep,green)'; }
        const nome = s.nome || s.sessao_id?.slice(0, 8) || '?';
        return `<div style="display:flex;gap:10px;align-items:center;padding:3px 0">
          <b>${nome}</b>
          <span style="color:${cor}">${tag}</span>
          <span style="color:var(--text-3)">· ${s.per_min || 0}/min · ${s.per_hour || 0}/h${s.fail_streak ? ' · '+s.fail_streak+' falhas' : ''}</span>
        </div>`;
      }).join('');
    } catch (e) { box.textContent = ''; }
  }
  window._carregarDispatchStatus = _carregarDispatchStatus;

  function _waCfgAlert(type, msg) {
    const el = document.getElementById('waCfgAlert');
    if (!el) return;
    el.style.display = 'block';
    const ok = type === 'ok';
    el.style.background = ok ? 'var(--primary-soft)' : 'var(--red-soft)';
    el.style.border     = ok ? '1px solid color-mix(in srgb,var(--primary) 35%,transparent)' : '1px solid color-mix(in srgb,var(--red) 30%,transparent)';
    el.style.color      = ok ? 'var(--primary-deep)' : 'var(--red)';
    el.textContent = msg;
  }

  // ── Spintax preview ──────────────────────────────────────────────────────────

  function _processSpintax(text) {
    const pattern = /\{([^{}]+)\}/g;
    let result = text, prev = '';
    for (let i = 0; i < 10 && result !== prev; i++) {
      prev = result;
      result = result.replace(pattern, (_, opts) => {
        const choices = opts.split('|');
        return choices[Math.floor(Math.random() * choices.length)];
      });
    }
    return result;
  }

  window.previewSpintax = function previewSpintax() {
    const input = document.getElementById('spinTestInput')?.value.trim() || '';
    const box   = document.getElementById('spinPreviewBox');
    if (!input || !box) return;
    box.textContent = _processSpintax(input);
    box.classList.add('visible');
  };

  // ── Documentação ERP / PDV ───────────────────────────────────────────────────

  window.abrirDocErpBrowser = async function abrirDocErpBrowser() {
    try {
      const r = await fetch('/api/docs/abrir-erp');
      const data = await r.json();
      if (!data.ok) await window.showInfo('Não foi possível abrir o documento: ' + (data.error || 'erro'), { type: 'warning' });
    } catch (e) { await window.showInfo('Erro ao abrir o documento: ' + e.message, { type: 'danger', title: 'Erro' }); }
  };

  window.baixarDocErp = function baixarDocErp() {
    const a = document.createElement('a');
    a.href = '/api/docs/erp'; a.download = 'ZapDin-Integracao-ERP.html';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  };

  window.abrirDocPdvBrowser = async function abrirDocPdvBrowser() {
    try {
      const r = await fetch('/api/docs/abrir-pdv');
      const data = await r.json();
      if (!data.ok) await window.showInfo('Não foi possível abrir o documento: ' + (data.error || 'erro'), { type: 'warning' });
    } catch (e) { await window.showInfo('Erro ao abrir o documento: ' + e.message, { type: 'danger', title: 'Erro' }); }
  };

  window.baixarDocPdv = function baixarDocPdv() {
    const a = document.createElement('a');
    a.href = '/api/docs/pdv'; a.download = 'ZapDin-PDV-Integracao-ERP.html';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  };

  // ── Inicialização ───────────────────────────────────────────────────────────

  window.addEventListener('load', () => {
    // Listener do botão salvar
    const btn = document.getElementById('btnSalvarWACfg');
    if (btn) btn.addEventListener('click', async () => {
      const min    = parseFloat(document.getElementById('waCfgDelayMin').value)   || 5;
      const max    = parseFloat(document.getElementById('waCfgDelayMax').value)   || 15;
      const limit  = parseInt(document.getElementById('waCfgDailyLimit').value)   || 0;
      const inicio = document.getElementById('waCfgHoraInicio').value;
      const fim    = document.getElementById('waCfgHoraFim').value;
      const horaOn = document.getElementById('waCfgHoraAtivo').checked;
      const spintax   = document.getElementById('waCfgSpintax').checked   ? '1' : '0';
      const composing = document.getElementById('waCfgComposing').checked ? '1' : '0';

      if (min >= max) { _waCfgAlert('error', 'O delay mínimo deve ser menor que o máximo.'); return; }

      const maxMin   = parseInt(document.getElementById('waCfgMaxMin')?.value)   || 12;
      const maxHora  = parseInt(document.getElementById('waCfgMaxHora')?.value)  || 250;
      const coolMin  = parseInt(document.getElementById('waCfgCooldownMin')?.value) || 5;
      const warmup   = parseInt(document.getElementById('waCfgWarmup')?.value);

      const payload = {
        wa_delay_min:   String(min), wa_delay_max:   String(max),
        wa_daily_limit: String(limit),
        wa_hora_inicio: horaOn ? inicio : '', wa_hora_fim: horaOn ? fim : '',
        wa_spintax: spintax, wa_composing: composing,
        wa_max_per_min: String(maxMin), wa_max_per_hour: String(maxHora),
        wa_cooldown_secs: String(coolMin * 60),
        wa_warmup_msgs: String(isNaN(warmup) ? 20 : warmup),
      };
      const res = await api('POST', '/api/config', payload);
      if (res && res.ok) { _waCfgAlert('ok', '✅ Configurações salvas com sucesso!'); _carregarDispatchStatus(); }
      else _waCfgAlert('error', 'Erro ao salvar configurações.');
    });

    if (window.ZD && ZD.registry) ZD.registry.register('config-envio', carregarConfigEnvio);
  });

})();
