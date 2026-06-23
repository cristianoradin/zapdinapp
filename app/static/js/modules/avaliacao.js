/**
 * modules/avaliacao.js — Módulo de Gestão de Avaliações.
 *
 * Responsável pela tela "Gestão de Avaliação":
 *  - Dashboard com KPIs, distribuição e ranking de vendedores
 *  - Tabela paginada de avaliações com filtros
 *  - Alerta de baixas notas
 *
 * Depende de: modules/utils.js (escHtml, _fmtPhone)
 * Registra: ZD.registry.register('avaliacoes', loadAvaliacoes)
 */

(function () {
  'use strict';

  // ── Estado do módulo ────────────────────────────────────────────────────────
  let _dias        = 30;
  let _page        = 1;
  let _filtroNota  = 'todas';
  let _data        = { dash: null, lista: [] };

  const _corNota = { 1: 'var(--red)', 2: '#f97316', 3: '#eab308', 4: '#84cc16', 5: '#22c55e' };
  const _bgNota  = { 1: '#fff5f5', 2: '#fff7ed', 3: '#fefce8', 4: '#f7fee7', 5: 'var(--primary-soft)' };

  // ── Helpers privados ────────────────────────────────────────────────────────
  function _starHtml(nota) {
    let s = '<span style="display:inline-flex;gap:1px;align-items:center">';
    for (let i = 1; i <= 5; i++)
      s += `<svg width="14" height="14" viewBox="0 0 24 24" fill="${i <= nota ? 'var(--star)' : 'var(--surface-3)'}"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;
    s += '</span>';
    return s;
  }

  function _renderDashVazio() {
    ['avalKpiEnviadas','avalKpiRespondidas','avalKpiTaxa','avalKpiMedia'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = '—';
    });
    const dist = document.getElementById('avalDistribuicao');
    if (dist) dist.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-2)">Sem dados para o período</div>';
    const rank = document.getElementById('avalRanking');
    if (rank) rank.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-2)">Sem dados</div>';
  }

  async function _loadDash() {
    try {
      const r = await fetch(`/api/avaliacoes/dashboard?dias=${_dias}`);
      if (!r.ok) { _renderDashVazio(); return; }
      const d = await r.json();
      _data.dash = d;

      // KPIs
      document.getElementById('avalKpiEnviadas').textContent    = d.total_enviadas   ?? '—';
      document.getElementById('avalKpiRespondidas').textContent = d.total_respondidas ?? '—';
      const taxa = d.total_enviadas > 0 ? Math.round((d.total_respondidas / d.total_enviadas) * 100) : 0;
      document.getElementById('avalKpiTaxa').textContent  = (d.taxa_resposta ?? taxa) + '%';
      document.getElementById('avalKpiMedia').textContent = typeof d.media_geral === 'number' ? d.media_geral.toFixed(1) : '—';

      // Alerta baixas notas
      const ruins     = Array.isArray(d.baixas) ? d.baixas : [];
      const alertaDiv = document.getElementById('avalAlertaBaixas');
      if (alertaDiv) {
        if (ruins.length > 0) {
          document.getElementById('avalAlertaTexto').textContent =
            `⚠️ ${ruins.length} avaliação${ruins.length > 1 ? 'ões' : ''} com nota baixa nos últimos ${_dias} dias`;
          document.getElementById('avalAlertaLista').innerHTML = ruins.map(a => `
            <div style="display:flex;align-items:center;gap:.75rem;background:#fff;border:1px solid color-mix(in srgb,var(--red) 30%,transparent);border-radius:8px;padding:.5rem .875rem;border-left:3px solid var(--red)">
              <div style="width:32px;height:32px;border-radius:50%;background:var(--red-bg);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.8rem;color:var(--red);flex-shrink:0">${(a.nome||'?').charAt(0).toUpperCase()}</div>
              <div style="flex:1;min-width:0">
                <div style="font-weight:600;font-size:.84rem">${escHtml(a.nome||'—')}</div>
                <div style="font-size:.75rem;color:var(--text-2)">${a.telefone||''}</div>
              </div>
              <div>${_starHtml(a.nota)}</div>
              <div style="font-size:.75rem;color:var(--text-2);white-space:nowrap">${a.data||''}</div>
            </div>`).join('');
          alertaDiv.style.display = '';
        } else {
          alertaDiv.style.display = 'none';
        }
      }

      // Distribuição por nota — .dist-row pattern (prototype)
      const dist      = d.distribuicao || {};
      const totalResp = d.total_respondidas || 1;
      const notaLabels = { 5: 'Excelente', 4: 'Bom', 3: 'Regular', 2: 'Ruim', 1: 'Péssimo' };
      function _starsRow(n) {
        let h = '';
        for (let i = 1; i <= 5; i++) {
          h += `<svg width="13" height="13" viewBox="0 0 24 24" fill="${i<=n?'var(--star)':'var(--surface-3)'}" style="flex:none"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;
        }
        return `<span style="display:inline-flex;gap:1px">${h}</span>`;
      }
      document.getElementById('avalDistribuicao').innerHTML = [5, 4, 3, 2, 1].map(n => {
        const qtd = dist[n] || 0;
        const pct = totalResp > 0 ? Math.round((qtd / totalResp) * 100) : 0;
        return `
          <div class="dist-row">
            <div class="lab">${_starsRow(n)} ${notaLabels[n]}</div>
            <div class="bar"><i style="width:${pct}%"></i></div>
            <div class="val">${pct}%</div>
          </div>`;
      }).join('');

      // Ranking vendedores — .rank-row pattern (prototype)
      const ranking = Array.isArray(d.ranking_vendedores) ? d.ranking_vendedores : [];
      const rankEl  = document.getElementById('avalRanking');
      if (!ranking.length) {
        rankEl.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-3)">Sem dados</div>';
      } else {
        rankEl.innerHTML = ranking.map((v, i) => {
          const rnClass = i === 0 ? 'g1' : i === 1 ? 'g2' : i === 2 ? 'g3' : 'gx';
          const media   = typeof v.media === 'number' ? v.media.toFixed(1) : '—';
          return `
            <div class="rank-row">
              <span class="rn ${rnClass}">${i + 1}</span>
              <span style="font-weight:650;flex:1">${escHtml(v.vendedor || '—')}</span>
              <span style="color:var(--text-3);font-size:12.5px;margin-right:12px">${v.total} aval.</span>
              <span style="display:flex;align-items:center;gap:5px;font-weight:800">
                ${media}
                <svg width="15" height="15" viewBox="0 0 24 24" fill="var(--star)"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
              </span>
            </div>`;
        }).join('');
      }
    } catch {
      _renderDashVazio();
    }
  }

  async function _loadLista() {
    try {
      const r = await fetch(`/api/avaliacoes?dias=${_dias}`);
      _data.lista = r.ok ? await r.json() : [];
    } catch {
      _data.lista = [];
    }
    _page = 1;
    _renderTabela();
  }

  function _renderRow(aval, idx) {
    const nota          = aval.nota || 0;
    const inicial       = (aval.nome || '?').charAt(0).toUpperCase();
    const avBg          = ['#1fa855', '#2f80ed', '#7b61ff'][idx % 3];
    const temComentario = aval.comentario && aval.comentario.trim().length > 0;
    const comentarioHtml = temComentario
      ? `<div style="font-size:12.5px;color:var(--text-3);font-style:italic;margin-top:2px">"${escHtml(aval.comentario)}"</div>` : '';
    return `
      <tr>
        <td>
          <span style="display:inline-flex;align-items:center;gap:11px">
            <span class="avatar-sm" style="background:${avBg}">${inicial}</span>
            <span>
              <b>${escHtml(aval.nome||'—')}</b>
              ${temComentario ? '<span title="Tem comentário" style="margin-left:6px">💬</span>' : ''}
              ${comentarioHtml}
            </span>
          </span>
        </td>
        <td class="mono">${_fmtPhone(aval.telefone||'')}</td>
        <td>${escHtml(aval.vendedor||'—')}</td>
        <td style="text-align:center">${_starHtml(nota)}</td>
        <td class="mono" style="text-align:right">${aval.data||'—'}</td>
      </tr>`;
  }

  function _renderTabela() {
    const PER_PAGE = 20;
    let lista = _data.lista || [];
    if (_filtroNota === 'otimas')    lista = lista.filter(a => (a.nota||0) >= 4);
    else if (_filtroNota === 'regulares') lista = lista.filter(a => (a.nota||0) === 3);
    else if (_filtroNota === 'ruins')    lista = lista.filter(a => (a.nota||0) <= 2);

    const total      = lista.length;
    const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
    if (_page > totalPages) _page = totalPages;
    const slice = lista.slice((_page - 1) * PER_PAGE, _page * PER_PAGE);

    const tbody = document.getElementById('avalTbody');
    tbody.innerHTML = slice.length
      ? slice.map(_renderRow).join('')
      : `<tr><td colspan="5" style="text-align:center;padding:2.5rem;color:var(--text-2)">Nenhuma avaliação encontrada.</td></tr>`;

    const infoEl = document.getElementById('avalPageInfo');
    if (infoEl) infoEl.textContent = total > 0
      ? `Exibindo ${(_page-1)*PER_PAGE+1}–${Math.min(_page*PER_PAGE, total)} de ${total}` : 'Nenhum resultado';
    const btnAnt = document.getElementById('avalBtnAnterior');
    const btnPro = document.getElementById('avalBtnProximo');
    if (btnAnt) btnAnt.disabled = _page <= 1;
    if (btnPro) btnPro.disabled = _page >= totalPages;
  }

  // ── Resumo diário automático ─────────────────────────────────────────────────
  async function _loadResumoConfig() {
    try {
      const r = await fetch('/api/avaliacao/resumo-config');
      if (!r.ok) return;
      const c = await r.json();
      const at = document.getElementById('resumoAtivo');
      const ho = document.getElementById('resumoHora');
      const pe = document.getElementById('resumoPeriodo');
      if (at) at.checked = !!c.ativo;
      if (ho) ho.value = c.hora || '08:00';
      if (pe) pe.value = c.periodo || 'ontem';
    } catch (_) { /* best-effort */ }
  }

  function _resumoMsg(txt, cor) {
    const el = document.getElementById('resumoMsg');
    if (el) { el.textContent = txt; el.style.color = cor || 'var(--text-2)'; }
  }

  window.salvarResumoConfig = async function () {
    const ativo   = document.getElementById('resumoAtivo')?.checked || false;
    const hora    = document.getElementById('resumoHora')?.value || '08:00';
    const periodo = document.getElementById('resumoPeriodo')?.value || 'ontem';
    _resumoMsg('Salvando…');
    try {
      const r = await fetch('/api/avaliacao/resumo-config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ativo, hora, periodo }),
      });
      if (r.ok) _resumoMsg('✅ Configuração salva.', 'var(--primary-deep)');
      else _resumoMsg('❌ Erro ao salvar.', 'var(--red)');
    } catch (e) { _resumoMsg('❌ ' + e.message, 'var(--red)'); }
  };

  window.testarResumo = async function () {
    _resumoMsg('Enviando resumo de teste…');
    try {
      const r = await fetch('/api/avaliacao/resumo-config/test', { method: 'POST' });
      const d = await r.json().catch(() => ({}));
      if (d.ok) _resumoMsg('✅ Resumo enviado! Confira o WhatsApp.', 'var(--primary-deep)');
      else _resumoMsg('⚠️ ' + (d.detail || 'Nada enviado.'), 'var(--red)');
    } catch (e) { _resumoMsg('❌ ' + e.message, 'var(--red)'); }
  };

  // ── API pública (chamada pelo HTML via onclick) ──────────────────────────────
  window.loadAvaliacoes = async function () {
    await Promise.all([_loadDash(), _loadLista(), _loadResumoConfig()]);
  };

  window.setAvalDias = function (dias) {
    _dias = dias;
    [7, 30, 90].forEach(d => {
      const btn = document.getElementById('avalBtn' + d);
      if (!btn) return;
      btn.classList.toggle('on', d === dias);
    });
    loadAvaliacoes();
  };

  window.setAvalFiltro = function (filtro) {
    _filtroNota = filtro;
    _page       = 1;
    ['todas','otimas','regulares','ruins'].forEach(f => {
      const btn = document.getElementById('avalFiltro' + f.charAt(0).toUpperCase() + f.slice(1));
      if (!btn) return;
      btn.classList.toggle('on', f === filtro);
    });
    _renderTabela();
  };

  window.avalMudarPagina = function (delta) {
    _page += delta;
    _renderTabela();
  };

  // ── Registro no page router ─────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    if (window.ZD && ZD.registry) {
      ZD.registry.register('avaliacoes', loadAvaliacoes);
    }
  });
})();
