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

  const _corNota = { 1: '#dc2626', 2: '#f97316', 3: '#eab308', 4: '#84cc16', 5: '#22c55e' };
  const _bgNota  = { 1: '#fff5f5', 2: '#fff7ed', 3: '#fefce8', 4: '#f7fee7', 5: '#f0fdf4' };

  // ── Helpers privados ────────────────────────────────────────────────────────
  function _starHtml(nota) {
    let s = '';
    for (let i = 1; i <= 5; i++)
      s += `<span style="color:${i <= nota ? _corNota[nota] : '#d1d5db'};font-size:.95rem">★</span>`;
    return s;
  }

  function _renderDashVazio() {
    ['avalKpiEnviadas','avalKpiRespondidas','avalKpiTaxa','avalKpiMedia'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = '—';
    });
    const dist = document.getElementById('avalDistribuicao');
    if (dist) dist.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-mid)">Sem dados para o período</div>';
    const rank = document.getElementById('avalRanking');
    if (rank) rank.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-mid)">Sem dados</div>';
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
            <div style="display:flex;align-items:center;gap:.75rem;background:#fff;border:1px solid #fecaca;border-radius:8px;padding:.5rem .875rem;border-left:3px solid #dc2626">
              <div style="width:32px;height:32px;border-radius:50%;background:#fee2e2;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.8rem;color:#b91c1c;flex-shrink:0">${(a.nome||'?').charAt(0).toUpperCase()}</div>
              <div style="flex:1;min-width:0">
                <div style="font-weight:600;font-size:.84rem">${escHtml(a.nome||'—')}</div>
                <div style="font-size:.75rem;color:var(--text-mid)">${a.telefone||''}</div>
              </div>
              <div>${_starHtml(a.nota)}</div>
              <div style="font-size:.75rem;color:var(--text-mid);white-space:nowrap">${a.data||''}</div>
            </div>`).join('');
          alertaDiv.style.display = '';
        } else {
          alertaDiv.style.display = 'none';
        }
      }

      // Distribuição por nota
      const dist      = d.distribuicao || {};
      const totalResp = d.total_respondidas || 1;
      const notaLabels = { 5: '⭐⭐⭐⭐⭐ Excelente', 4: '⭐⭐⭐⭐ Bom', 3: '⭐⭐⭐ Regular', 2: '⭐⭐ Ruim', 1: '⭐ Péssimo' };
      const notaCores  = { 5: '#22c55e', 4: '#84cc16', 3: '#eab308', 2: '#f97316', 1: '#ef4444' };
      document.getElementById('avalDistribuicao').innerHTML = [5, 4, 3, 2, 1].map(n => {
        const qtd = dist[n] || 0;
        const pct = totalResp > 0 ? Math.round((qtd / totalResp) * 100) : 0;
        return `
          <div style="display:flex;align-items:center;gap:.625rem">
            <div style="white-space:nowrap;font-size:.78rem;font-weight:600;color:var(--text-mid);min-width:140px">${notaLabels[n]}</div>
            <div style="flex:1;height:10px;background:var(--border);border-radius:5px;overflow:hidden">
              <div style="height:100%;width:${pct}%;background:${notaCores[n]};border-radius:5px;transition:width .7s ease"></div>
            </div>
            <div style="font-size:.75rem;font-weight:700;color:var(--text-mid);white-space:nowrap;min-width:55px;text-align:right">${qtd} (${pct}%)</div>
          </div>`;
      }).join('');

      // Ranking vendedores
      const ranking = Array.isArray(d.ranking_vendedores) ? d.ranking_vendedores : [];
      const rankEl  = document.getElementById('avalRanking');
      if (!ranking.length) {
        rankEl.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-mid)">Sem dados</div>';
      } else {
        const melhorMedia = ranking[0].media || 5;
        rankEl.innerHTML = ranking.map((v, i) => {
          const pct      = melhorMedia > 0 ? Math.round((v.media / melhorMedia) * 100) : 0;
          const barColor = i === 0 ? '#22c55e' : i === ranking.length - 1 && ranking.length > 1 ? '#ef4444' : 'var(--accent)';
          const numClass = i === 0 ? 'rank-num gold' : i === 1 ? 'rank-num silver' : i === 2 ? 'rank-num bronze' : 'rank-num';
          return `
            <div class="rank-row">
              <div class="${numClass}">${i + 1}</div>
              <div class="rank-bar-wrap">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.2rem">
                  <span class="rank-name" style="max-width:140px">${escHtml(v.vendedor || '—')}</span>
                  <span style="font-size:.7rem;color:var(--text-mid)">${v.total} aval.</span>
                </div>
                <div class="rank-bar-bg">
                  <div class="rank-bar-fill" style="width:${pct}%;background:${barColor}"></div>
                </div>
              </div>
              <div class="rank-stat">${typeof v.media === 'number' ? v.media.toFixed(1) : '—'} ★</div>
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

  function _renderRow(aval) {
    const nota          = aval.nota || 0;
    const borderColor   = _corNota[nota] || '#e4e6ea';
    const bgColor       = _bgNota[nota]  || '#fff';
    const inicial       = (aval.nome || '?').charAt(0).toUpperCase();
    const temComentario = aval.comentario && aval.comentario.trim().length > 0;
    const comentarioHtml = temComentario
      ? `<div style="font-size:.78rem;color:var(--text-mid);font-style:italic;margin-top:.2rem">"${escHtml(aval.comentario)}"</div>` : '';
    return `
      <tr style="border-left:3px solid ${borderColor};background:${bgColor}">
        <td>
          <div style="display:flex;align-items:center;gap:.625rem">
            <div style="width:32px;height:32px;border-radius:50%;background:${borderColor}22;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.8rem;color:${borderColor};flex-shrink:0">${inicial}</div>
            <div>
              <div style="font-weight:600;font-size:.875rem;display:flex;align-items:center;gap:.35rem">
                ${escHtml(aval.nome||'—')} ${temComentario ? '<span title="Tem comentário" style="font-size:.75rem">💬</span>' : ''}
              </div>
              ${comentarioHtml}
            </div>
          </div>
        </td>
        <td style="font-family:monospace;font-size:.84rem;color:var(--text-mid)">${_fmtPhone(aval.telefone||'')}</td>
        <td style="font-size:.84rem">${escHtml(aval.vendedor||'—')}</td>
        <td style="text-align:center">${_starHtml(nota)}</td>
        <td style="font-size:.8rem;color:var(--text-mid);white-space:nowrap">${aval.data||'—'}</td>
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
      : `<tr><td colspan="5" style="text-align:center;padding:2.5rem;color:var(--text-mid)">Nenhuma avaliação encontrada.</td></tr>`;

    const infoEl = document.getElementById('avalPageInfo');
    if (infoEl) infoEl.textContent = total > 0
      ? `Exibindo ${(_page-1)*PER_PAGE+1}–${Math.min(_page*PER_PAGE, total)} de ${total}` : 'Nenhum resultado';
    const btnAnt = document.getElementById('avalBtnAnterior');
    const btnPro = document.getElementById('avalBtnProximo');
    if (btnAnt) btnAnt.disabled = _page <= 1;
    if (btnPro) btnPro.disabled = _page >= totalPages;
  }

  // ── API pública (chamada pelo HTML via onclick) ──────────────────────────────
  window.loadAvaliacoes = async function () {
    await Promise.all([_loadDash(), _loadLista()]);
  };

  window.setAvalDias = function (dias) {
    _dias = dias;
    [7, 30, 90].forEach(d => {
      const btn = document.getElementById('avalBtn' + d);
      if (!btn) return;
      btn.style.background = d === dias ? 'var(--accent)' : 'transparent';
      btn.style.color      = d === dias ? '#fff'          : 'var(--text-mid)';
    });
    loadAvaliacoes();
  };

  window.setAvalFiltro = function (filtro) {
    _filtroNota = filtro;
    _page       = 1;
    ['todas','otimas','regulares','ruins'].forEach(f => {
      const btn = document.getElementById('avalFiltro' + f.charAt(0).toUpperCase() + f.slice(1));
      if (!btn) return;
      btn.className = f === filtro ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-ghost';
      btn.style.cssText = 'border-radius:16px;font-size:.78rem;padding:.3rem .85rem';
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
