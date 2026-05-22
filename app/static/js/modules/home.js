// ── Home Dashboard ──────────────────────────────────────────────────────────
// Widgets da home: relógio, clima, calendário, post-its, recados, initHome.
// Autossuficiente: sem dependência de api() de app.js.

// ═══════════════════════════════════════════════════════════
// HOME DASHBOARD
// ═══════════════════════════════════════════════════════════

// ── Relógio ──────────────────────────────────────────────────
let _homeClockInterval = null;
const _DIAS_PT = ['Domingo','Segunda-feira','Terça-feira','Quarta-feira','Quinta-feira','Sexta-feira','Sábado'];
const _MESES_PT = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];

function _homeTick() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2,'0');
  const mm = String(now.getMinutes()).padStart(2,'0');
  const ss = String(now.getSeconds()).padStart(2,'0');
  const el = document.getElementById('home-time');
  if (el) el.textContent = `${hh}:${mm}`;
  const elDate = document.getElementById('home-date');
  if (elDate) elDate.textContent = `${String(now.getDate()).padStart(2,'0')}/${String(now.getMonth()+1).padStart(2,'0')}/${now.getFullYear()}`;
  const elDay = document.getElementById('home-day');
  if (elDay) elDay.textContent = _DIAS_PT[now.getDay()];
}

function homeToggleClimaConfig() {
  const cfg = document.getElementById('home-clima-config');
  if (!cfg) return;
  cfg.style.display = cfg.style.display === 'none' ? 'flex' : 'none';
}

// ── Clima ─────────────────────────────────────────────────────
const _CLIMA_ICONS = {
  0:'☀️', 1:'🌤️', 2:'⛅', 3:'☁️', 45:'🌫️', 48:'🌫️',
  51:'🌦️', 53:'🌦️', 55:'🌦️', 61:'🌧️', 63:'🌧️', 65:'🌧️',
  71:'🌨️', 73:'🌨️', 75:'🌨️', 80:'🌦️', 81:'🌦️', 82:'⛈️',
  95:'⛈️', 96:'⛈️', 99:'⛈️'
};

async function homeCarregarClima() {
  try {
    const r = await fetch('/api/home/clima');
    const d = await r.json();
    if (!r.ok) return;
    document.getElementById('home-clima-city').textContent = (d.cidade||'--').toUpperCase();
    document.getElementById('home-clima-temp').textContent = `${Math.round(d.temperatura)}°`;
    document.getElementById('home-clima-desc').textContent = d.descricao_clima || '--';
    document.getElementById('home-clima-icon').textContent = _CLIMA_ICONS[d.codigo_clima] || '🌤️';
    document.getElementById('home-clima-umid').textContent = `${d.umidade}%`;
    document.getElementById('home-clima-vento').textContent = `${Math.round(d.vento)}km/h`;
    // Previsão 3 dias compacta
    const fc = document.getElementById('home-clima-forecast');
    if (fc && d.previsao) {
      const dias = ['Hoje','Amanhã','Depois'];
      fc.innerHTML = d.previsao.slice(0,3).map((p,i) => `
        <div class="hd-wf-day">
          <div class="hd-wf-label">${dias[i]}</div>
          <div class="hd-wf-icon">${_CLIMA_ICONS[p.codigo] || '🌤️'}</div>
          <div class="hd-wf-max">${Math.round(p.max)}°</div>
          <div class="hd-wf-min">${Math.round(p.min)}°</div>
        </div>`).join('');
    }
    // Preenche inputs de config
    if (d.cidade) document.getElementById('home-clima-cidade-input').value = d.cidade;
    if (d.uf) document.getElementById('home-clima-uf-input').value = d.uf;
  } catch(e) { console.log('[home] clima error', e); }
}

async function homeSalvarCidade() {
  const cidade = document.getElementById('home-clima-cidade-input').value.trim();
  const uf = document.getElementById('home-clima-uf-input').value.trim();
  if (!cidade) return;
  await fetch('/api/home/cidade', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({cidade, uf})});
  homeCarregarClima();
}

// ── KPIs ──────────────────────────────────────────────────────
async function homeCarregarKPIs() {
  try {
    const [statsRes, waRes] = await Promise.all([
      fetch('/api/stats'),
      fetch('/api/sessoes/live-status'),
    ]);
    if (statsRes.ok) {
      const s = await statsRes.json();
      const hoje = document.getElementById('hd-kpi-hoje-val');
      const total = document.getElementById('hd-kpi-total-val');
      const fila  = document.getElementById('hd-kpi-fila-val');
      if (hoje)  hoje.textContent  = (s.hoje  ?? s.today ?? '--');
      if (total) total.textContent = (s.total_mensagens ?? '--');
      if (fila)  fila.textContent  = (s.total_queued ?? '--');
    }
    if (waRes.ok) {
      const sessoes = await waRes.json();
      const connected = sessoes.filter(s => s.status === 'connected').length;
      const waEl = document.getElementById('hd-kpi-wa-val');
      if (waEl) waEl.textContent = connected;
    }
  } catch(e) {}
}

// ── Calendário ────────────────────────────────────────────────
let _calAno = new Date().getFullYear();
let _calMes = new Date().getMonth(); // 0-11
let _agendaDados = {}; // {data_str: [compromissos]}
let _agendaDataSel = null;

function homeCalNav(delta) {
  _calMes += delta;
  if (_calMes < 0) { _calMes = 11; _calAno--; }
  if (_calMes > 11) { _calMes = 0; _calAno++; }
  homeRenderCal();
  homeCarregarAgenda();
}

function homeRenderCal() {
  const label = document.getElementById('home-cal-month');
  const mesesCurtos = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
  if (label) label.textContent = `${mesesCurtos[_calMes]} ${_calAno}`;
  const container = document.getElementById('home-cal-days');
  if (!container) return;
  const hoje = new Date();
  const primeiroDia = new Date(_calAno, _calMes, 1).getDay();
  const diasNoMes = new Date(_calAno, _calMes + 1, 0).getDate();
  const diasMesAnterior = new Date(_calAno, _calMes, 0).getDate();
  let html = '';
  for (let i = primeiroDia - 1; i >= 0; i--)
    html += `<div class="home-cal-day other-month">${diasMesAnterior - i}</div>`;
  for (let d = 1; d <= diasNoMes; d++) {
    const dataStr = `${_calAno}-${String(_calMes+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    const isToday = d === hoje.getDate() && _calMes === hoje.getMonth() && _calAno === hoje.getFullYear();
    const hasEv = _agendaDados[dataStr] && _agendaDados[dataStr].length > 0;
    html += `<div class="home-cal-day${isToday?' today':''}${hasEv?' has-event':''}" onclick="homeAbrirAgenda('${dataStr}')">${d}</div>`;
  }
  const total = primeiroDia + diasNoMes;
  const restante = total % 7 === 0 ? 0 : 7 - (total % 7);
  for (let i = 1; i <= restante; i++)
    html += `<div class="home-cal-day other-month">${i}</div>`;
  container.innerHTML = html;
  // Próximos eventos
  _renderNextEvents();
}

function _renderNextEvents() {
  const el = document.getElementById('hd-next-events');
  if (!el) return;
  const hoje = new Date();
  const eventos = [];
  Object.entries(_agendaDados).forEach(([data, lista]) => {
    const d = new Date(data + 'T12:00:00');
    if (d >= new Date(hoje.getFullYear(), hoje.getMonth(), hoje.getDate()))
      lista.forEach(ev => eventos.push({...ev, _data: data, _d: d}));
  });
  eventos.sort((a,b) => a._d - b._d || (a.hora_inicio||'').localeCompare(b.hora_inicio||''));
  if (!eventos.length) {
    el.innerHTML = '<div class="hd-next-empty">Nenhum compromisso próximo</div>'; return;
  }
  el.innerHTML = eventos.slice(0,5).map(ev => {
    const [ano,mes,dia] = ev._data.split('-');
    const eHoje = ev._data === `${hoje.getFullYear()}-${String(hoje.getMonth()+1).padStart(2,'0')}-${String(hoje.getDate()).padStart(2,'0')}`;
    const label = eHoje ? 'Hoje' : `${dia}/${mes}`;
    return `<div class="hd-next-event" onclick="homeAbrirAgenda('${ev._data}')">
      <div class="hd-nev-dot" style="background:${ev.cor||'#3d7f1f'}"></div>
      <div class="hd-nev-body">
        <div class="hd-nev-titulo">${ev.titulo}</div>
        <div class="hd-nev-hora">${label}${ev.hora_inicio ? ' · '+ev.hora_inicio : ''}</div>
      </div>
    </div>`;
  }).join('');
}

async function homeCarregarAgenda() {
  const mes = `${_calAno}-${String(_calMes+1).padStart(2,'0')}`;
  try {
    const r = await fetch(`/api/home/agenda?mes=${mes}`);
    const lista = await r.json();
    _agendaDados = {};
    lista.forEach(c => {
      const d = (c.data || '').split('T')[0];
      if (!_agendaDados[d]) _agendaDados[d] = [];
      _agendaDados[d].push(c);
    });
    homeRenderCal();
  } catch(e) {}
}

function homeAbrirAgenda(dataStr) {
  _agendaDataSel = dataStr;
  const [ano, mes, dia] = dataStr.split('-');
  document.getElementById('home-agenda-data-label').textContent = `${dia}/${mes}/${ano}`;
  homeRenderAgendaLista();
  homeLimparAgendaForm();
  document.getElementById('home-agenda-overlay').classList.add('open');
}

function homeFecharAgenda(event, force) {
  if (!force && event && event.target !== document.getElementById('home-agenda-overlay')) return;
  document.getElementById('home-agenda-overlay').classList.remove('open');
  _agendaDataSel = null;
}

function homeRenderAgendaLista() {
  const lista = _agendaDados[_agendaDataSel] || [];
  const el = document.getElementById('home-agenda-lista');
  if (!el) return;
  if (!lista.length) { el.innerHTML = '<div class="home-empty" style="padding:.8rem 0">Nenhum compromisso neste dia</div>'; return; }
  el.innerHTML = lista.map(c => `
    <div class="home-agenda-item" onclick="homeEditarAgenda(${c.id})">
      <div class="home-agenda-cor" style="background:${c.cor||'#3d7f1f'}"></div>
      <div class="home-agenda-item-body">
        <div class="home-agenda-item-titulo">${c.titulo}</div>
        <div class="home-agenda-item-hora">${c.hora_inicio||''} ${c.hora_fim ? '→ '+c.hora_fim : ''}</div>
      </div>
      <button class="home-agenda-item-del" onclick="event.stopPropagation();homeDeletarAgenda(${c.id})">✕</button>
    </div>`).join('');
}

function homeEditarAgenda(id) {
  const lista = _agendaDados[_agendaDataSel] || [];
  const c = lista.find(x => x.id == id);
  if (!c) return;
  document.getElementById('home-agenda-id').value = c.id;
  document.getElementById('home-agenda-titulo').value = c.titulo;
  document.getElementById('home-agenda-inicio').value = c.hora_inicio || '';
  document.getElementById('home-agenda-fim').value = c.hora_fim || '';
  document.getElementById('home-agenda-desc').value = c.descricao || '';
  const linkEl = document.getElementById('home-agenda-link');
  if (linkEl) linkEl.value = c.link || '';
  const radio = document.querySelector(`input[name="agenda-cor"][value="${c.cor||'#3d7f1f'}"]`);
  if (radio) radio.checked = true;
}

function homeLimparAgendaForm() {
  document.getElementById('home-agenda-id').value = '';
  document.getElementById('home-agenda-titulo').value = '';
  document.getElementById('home-agenda-inicio').value = '';
  document.getElementById('home-agenda-fim').value = '';
  document.getElementById('home-agenda-desc').value = '';
  const linkEl = document.getElementById('home-agenda-link');
  if (linkEl) linkEl.value = '';
  const r = document.querySelector('input[name="agenda-cor"][value="#3d7f1f"]');
  if (r) r.checked = true;
}

async function homeSalvarAgenda() {
  const id = document.getElementById('home-agenda-id').value;
  const titulo = document.getElementById('home-agenda-titulo').value.trim();
  if (!titulo) return alert('Informe o título');
  const linkEl = document.getElementById('home-agenda-link');
  const body = {
    data: _agendaDataSel,
    hora_inicio: document.getElementById('home-agenda-inicio').value || null,
    hora_fim: document.getElementById('home-agenda-fim').value || null,
    titulo,
    descricao: document.getElementById('home-agenda-desc').value || null,
    cor: (document.querySelector('input[name="agenda-cor"]:checked') || {}).value || '#3d7f1f',
    link: (linkEl ? linkEl.value.trim() : '') || null
  };
  const url = id ? `/api/home/agenda/${id}` : '/api/home/agenda';
  const method = id ? 'PUT' : 'POST';
  const r = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  if (r.ok) { await homeCarregarAgenda(); homeRenderAgendaLista(); homeLimparAgendaForm(); }
}

async function homeDeletarAgenda(id) {
  if (!confirm('Excluir compromisso?')) return;
  await fetch(`/api/home/agenda/${id}`, {method:'DELETE'});
  await homeCarregarAgenda();
  homeRenderAgendaLista();
}

// ── Post-its ──────────────────────────────────────────────────
let _postits = [];

async function homeCarregarPostits() {
  try {
    const r = await fetch('/api/home/postits');
    _postits = await r.json();
    homeRenderPostits();
  } catch(e) {}
}

function homeRenderPostits() {
  const grid = document.getElementById('home-postits-grid');
  if (!grid) return;
  let html = _postits.map(p => `
    <div class="home-postit" style="background:${p.cor}" onclick="homeAbrirPostit(${p.id})">
      <div class="home-postit-titulo">${p.titulo || 'Sem título'}</div>
      <div class="home-postit-conteudo">${p.conteudo || ''}</div>
    </div>`).join('');
  html += `<div class="home-postit home-postit-novo" onclick="homeNovoPostit()">+</div>`;
  grid.innerHTML = html;
}

function homeNovoPostit() {
  document.getElementById('home-postit-id').value = '';
  document.getElementById('home-postit-titulo').value = '';
  document.getElementById('home-postit-conteudo').value = '';
  const r = document.querySelector('input[name="postit-cor"][value="#fef08a"]');
  if (r) r.checked = true;
  document.getElementById('home-postit-del-btn').style.display = 'none';
  document.getElementById('home-postit-overlay').classList.add('open');
}

function homeAbrirPostit(id) {
  const p = _postits.find(x => x.id == id);
  if (!p) return;
  document.getElementById('home-postit-id').value = p.id;
  document.getElementById('home-postit-titulo').value = p.titulo || '';
  document.getElementById('home-postit-conteudo').value = p.conteudo || '';
  const radio = document.querySelector(`input[name="postit-cor"][value="${p.cor}"]`);
  if (radio) radio.checked = true;
  document.getElementById('home-postit-del-btn').style.display = '';
  document.getElementById('home-postit-overlay').classList.add('open');
}

function homeFecharPostit(event, force) {
  if (!force && event && event.target !== document.getElementById('home-postit-overlay')) return;
  document.getElementById('home-postit-overlay').classList.remove('open');
}

async function homeSalvarPostit() {
  const id = document.getElementById('home-postit-id').value;
  const body = {
    titulo: document.getElementById('home-postit-titulo').value,
    conteudo: document.getElementById('home-postit-conteudo').value,
    cor: (document.querySelector('input[name="postit-cor"]:checked') || {}).value || '#fef08a'
  };
  const url = id ? `/api/home/postits/${id}` : '/api/home/postits';
  const method = id ? 'PUT' : 'POST';
  await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  homeFecharPostit(null, true);
  homeCarregarPostits();
}

async function homeDeletarPostit() {
  const id = document.getElementById('home-postit-id').value;
  if (!id || !confirm('Excluir anotação?')) return;
  await fetch(`/api/home/postits/${id}`, {method:'DELETE'});
  homeFecharPostit(null, true);
  homeCarregarPostits();
}

// ── Alerta de Agenda WA ───────────────────────────────────────
function homeToggleAgendaAlertaCfg() {
  const panel = document.getElementById('home-agenda-alerta-cfg');
  if (!panel) return;
  const open = panel.style.display !== 'none';
  panel.style.display = open ? 'none' : 'block';
}

let _agendaAlertaDebounce = null;

async function homeCarregarAgendaAlerta() {
  try {
    const r = await fetch('/api/config/agenda-alerta');
    if (!r.ok) return;
    const d = await r.json();
    const chk = document.getElementById('agendaAlertaAtivo');
    if (chk) chk.checked = !!d.ativo;
    const numEl = document.getElementById('agendaAlertaNumero');
    if (numEl) numEl.value = d.numero_alerta || '';
    const donoEl = document.getElementById('agendaAlertaDono');
    if (donoEl) donoEl.value = d.numero_dono || '';
    const msgEl = document.getElementById('agendaAlertaMensagem');
    if (msgEl) msgEl.value = d.mensagem || '';
  } catch(e) { console.log('[home] agenda-alerta error', e); }
}

async function homeSalvarAgendaAlerta() {
  const ativo = (document.getElementById('agendaAlertaAtivo') || {}).checked || false;
  const numero_alerta = (document.getElementById('agendaAlertaNumero') || {}).value || '';
  const numero_dono = (document.getElementById('agendaAlertaDono') || {}).value || '';
  const mensagem = (document.getElementById('agendaAlertaMensagem') || {}).value || '';
  try {
    await fetch('/api/config/agenda-alerta', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ativo, numero_alerta, numero_dono, mensagem })
    });
  } catch(e) { console.log('[home] salvar agenda-alerta error', e); }
}

function homeSalvarAgendaAlertaDebounce() {
  clearTimeout(_agendaAlertaDebounce);
  _agendaAlertaDebounce = setTimeout(homeSalvarAgendaAlerta, 1200);
}

// ── Recados ───────────────────────────────────────────────────
async function homeCarregarRecados() {
  try {
    const r = await fetch('/api/home/recados');
    const lista = await r.json();
    const badge = document.getElementById('home-recados-badge');
    if (badge) badge.textContent = lista.length;
    const el = document.getElementById('home-recados-list');
    if (!el) return;
    if (!lista.length) {
      el.innerHTML = `<div class="hd-empty">
        <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:.25;margin-bottom:.4rem"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
        Nenhum aviso no momento
      </div>`;
      return;
    }
    el.innerHTML = lista.map(rec => `
      <div class="hd-recado-item" style="border-left-color:${rec.cor||'#3d7f1f'}">
        <div class="hd-recado-titulo">${rec.titulo}</div>
        <div class="hd-recado-conteudo">${rec.conteudo}</div>
        <div class="hd-recado-data">📅 ${new Date(rec.created_at).toLocaleDateString('pt-BR')}</div>
      </div>`).join('');
  } catch(e) {}
}

// ── Init Home ─────────────────────────────────────────────────
function initHome() {
  if (_homeClockInterval) clearInterval(_homeClockInterval);
  _homeTick();
  _homeClockInterval = setInterval(_homeTick, 1000);
  _calAno = new Date().getFullYear();
  _calMes = new Date().getMonth();
  homeRenderCal();
  homeCarregarAgenda();
  homeCarregarClima();
  homeCarregarPostits();
  homeCarregarRecados();
  homeCarregarKPIs();
  homeCarregarAgendaAlerta();
}

// Inicializa conector visual no item já ativo ao carregar
window.addEventListener('load', () => {
  const activeItem = document.querySelector('.nav-item.active');
  if (activeItem) _updateNavConnector(activeItem);
});
