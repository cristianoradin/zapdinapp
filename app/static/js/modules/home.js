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
  if (!titulo) { agwaToast('⚠️ Informe o título do compromisso'); return; }
  if (!_agendaDataSel) { agwaToast('⚠️ Selecione uma data no calendário'); return; }
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
  try {
    const r = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    if (r.ok) {
      agwaToast('✓ Compromisso salvo');
      await homeCarregarAgenda();
      homeRenderAgendaLista();
      homeLimparAgendaForm();
    } else {
      const err = await r.json().catch(() => ({}));
      agwaToast('❌ Erro ao salvar: ' + (err.detail || r.status));
      console.error('[agenda] save error', r.status, err);
    }
  } catch(e) {
    agwaToast('❌ Erro de conexão ao salvar');
    console.error('[agenda] fetch error', e);
  }
}

async function homeDeletarAgenda(id) {
  const ok = await showConfirm({ title: 'Excluir compromisso?', body: 'Esta ação não pode ser desfeita.', okLabel: 'Excluir', type: 'danger', icon: '🗑️' });
  if (!ok) return;
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
  if (!id) return;
  const ok = await showConfirm({ title: 'Excluir anotação?', body: 'Esta ação não pode ser desfeita.', okLabel: 'Excluir', type: 'danger', icon: '🗑️' });
  if (!ok) return;
  await fetch(`/api/home/postits/${id}`, {method:'DELETE'});
  homeFecharPostit(null, true);
  homeCarregarPostits();
}

// ── Agenda WA Config Modal ────────────────────────────────────
let _agendaAlertaDebounce = null;
let _agwaUsuarios = [];

function homeAbrirAgendaWaCfg() {
  document.getElementById('agwa-overlay').classList.add('open');
  homeCarregarAgendaAlerta();
  agwaCarregarUsuarios();
}

function homeFecharAgendaWaCfg(event, force) {
  if (!force && event && event.target !== document.getElementById('agwa-overlay')) return;
  document.getElementById('agwa-overlay').classList.remove('open');
}

async function homeCarregarAgendaAlerta() {
  try {
    const r = await fetch('/api/config/agenda-alerta');
    if (!r.ok) return;
    const d = await r.json();
    const chk = document.getElementById('agendaAlertaAtivo');
    if (chk) chk.checked = !!d.ativo;
    const msgEl = document.getElementById('agendaAlertaMensagem');
    if (msgEl) msgEl.value = d.mensagem || '';
  } catch(e) { console.log('[home] agenda-alerta error', e); }
}

async function homeSalvarAgendaAlerta() {
  const ativo    = (document.getElementById('agendaAlertaAtivo') || {}).checked || false;
  const mensagem = (document.getElementById('agendaAlertaMensagem') || {}).value || '';
  try {
    await fetch('/api/config/agenda-alerta', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ativo, mensagem })
    });
    agwaToast('Configurações salvas ✓');
  } catch(e) { console.log('[home] salvar agenda-alerta error', e); }
}

function homeSalvarAgendaAlertaDebounce() {
  clearTimeout(_agendaAlertaDebounce);
  _agendaAlertaDebounce = setTimeout(homeSalvarAgendaAlerta, 1500);
}

// ── CRUD Usuários WA ──────────────────────────────────────────
function agwaToast(msg) {
  let t = document.getElementById('agwa-toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'agwa-toast';
    t.style.cssText = 'position:fixed;bottom:1.5rem;right:1.5rem;background:#1a1d23;color:#fff;padding:.55rem 1.1rem;border-radius:10px;font-size:.8rem;font-weight:600;z-index:2000;opacity:0;transition:opacity .2s';
    document.body.appendChild(t);
  }
  t.textContent = msg; t.style.opacity = '1';
  setTimeout(() => t.style.opacity = '0', 2200);
}

function agwaIniciais(nome) {
  const parts = (nome || '?').trim().split(/\s+/);
  return parts.length >= 2 ? parts[0][0] + parts[1][0] : parts[0].slice(0,2);
}

async function agwaCarregarUsuarios() {
  try {
    const r = await fetch('/api/config/agenda-wa-usuarios');
    _agwaUsuarios = r.ok ? await r.json() : [];
    agwaRenderUsuarios();
  } catch(e) { _agwaUsuarios = []; agwaRenderUsuarios(); }
}

function agwaRenderUsuarios() {
  const el = document.getElementById('agwa-usuarios-lista');
  if (!el) return;
  if (!_agwaUsuarios.length) {
    el.innerHTML = `<div style="text-align:center;padding:1.2rem 0;color:var(--text-muted);font-size:.82rem">
      <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:.25;display:block;margin:0 auto .4rem"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>
      Nenhum usuário cadastrado
    </div>`;
    return;
  }
  el.innerHTML = _agwaUsuarios.map(u => {
    const ini     = agwaIniciais(u.nome).toUpperCase();
    const nomeEsc = u.nome.replace(/'/g, '&#39;');
    const atv  = u.ativo ? '<span class="agwa-badge agwa-badge-green">Ativo</span>' : '<span class="agwa-badge agwa-badge-gray">Inativo</span>';
    const bell = u.recebe_alertas ? '<span class="agwa-badge agwa-badge-bell">🔔</span>' : '';
    const digestInfo = u.morning_digest_hora
      ? `<span class="agwa-badge agwa-badge-digest">☀️ ${u.morning_digest_hora}</span>` : '';
    const ants = (u.alert_antecedencias || [60]);
    const antsInfo = ants.length ? `<span class="agwa-badge agwa-badge-ant">⏰ ${ants.join(', ')}min</span>` : '';
    return `
    <div class="agwa-user-card" id="agwa-card-${u.id}">
      <div class="agwa-user-avatar">${ini}</div>
      <div class="agwa-user-info">
        <div class="agwa-user-nome">${u.nome}</div>
        <div class="agwa-user-phone">📱 ${u.phone}</div>
        <div class="agwa-user-config-badges">${digestInfo}${antsInfo}</div>
      </div>
      <div class="agwa-user-badges">${atv}${bell}</div>
      <div class="agwa-user-actions">
        <button class="agwa-act-btn cfg" title="Configurar alertas" onclick="agwaAbrirConfig(${u.id})">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </button>
        <button class="agwa-act-btn edit" title="Editar" onclick="agwaEditarUsuario(${u.id})">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </button>
        <button class="agwa-act-btn del" title="Remover" onclick="agwaDeletarUsuario(${u.id},'${nomeEsc}')">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>
        </button>
      </div>
    </div>`;
  }).join('');
}

async function agwaAdicionarUsuario() {
  const nome  = (document.getElementById('agwa-add-nome') || {}).value?.trim() || '';
  const phone = (document.getElementById('agwa-add-phone') || {}).value?.trim() || '';
  const ativo = document.getElementById('agwa-add-ativo')?.checked ?? true;
  const recebe_alertas = document.getElementById('agwa-add-alertas')?.checked ?? true;
  if (!nome || !phone) return agwaToast('Preencha nome e telefone');
  try {
    const r = await fetch('/api/config/agenda-wa-usuarios', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({nome, phone, ativo, recebe_alertas})
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      return agwaToast(err.detail || 'Erro ao adicionar');
    }
    document.getElementById('agwa-add-nome').value  = '';
    document.getElementById('agwa-add-phone').value = '';
    document.getElementById('agwa-add-ativo').checked   = true;
    document.getElementById('agwa-add-alertas').checked = true;
    await agwaCarregarUsuarios();
    agwaToast(nome + ' adicionado ✓');
  } catch(e) { agwaToast('Erro de conexão'); }
}

function agwaEditarUsuario(id) {
  const u = _agwaUsuarios.find(x => x.id === id);
  if (!u) return;
  const card = document.getElementById('agwa-card-' + id);
  if (!card) return;
  card.outerHTML = `
    <div class="agwa-edit-form" id="agwa-edit-${id}">
      <div style="display:flex;gap:.5rem">
        <div class="agwa-field" style="flex:1;margin:0"><label>Nome</label>
          <input id="agwa-e-nome-${id}" value="${u.nome.replace(/"/g,'&quot;')}" type="text"></div>
        <div class="agwa-field" style="flex:1;margin:0"><label>WhatsApp</label>
          <input id="agwa-e-phone-${id}" value="${u.phone}" type="text"></div>
      </div>
      <div class="agwa-add-checks">
        <label><input type="checkbox" id="agwa-e-ativo-${id}" ${u.ativo?'checked':''}> Ativo</label>
        <label><input type="checkbox" id="agwa-e-alertas-${id}" ${u.recebe_alertas?'checked':''}> Alertas</label>
      </div>
      <div style="display:flex;gap:.4rem;justify-content:flex-end">
        <button onclick="agwaCarregarUsuarios()" style="background:#e5e7eb;color:var(--text);border:none;border-radius:7px;padding:.4rem .8rem;font-size:.78rem;cursor:pointer">Cancelar</button>
        <button onclick="agwaSalvarEdicao(${id})" class="agwa-btn-add">Salvar</button>
      </div>
    </div>`;
}

async function agwaSalvarEdicao(id) {
  const nome  = document.getElementById('agwa-e-nome-' + id)?.value?.trim() || '';
  const phone = document.getElementById('agwa-e-phone-' + id)?.value?.trim() || '';
  const ativo = document.getElementById('agwa-e-ativo-' + id)?.checked ?? true;
  const recebe_alertas = document.getElementById('agwa-e-alertas-' + id)?.checked ?? true;
  if (!nome || !phone) return agwaToast('Preencha nome e telefone');
  try {
    const r = await fetch(`/api/config/agenda-wa-usuarios/${id}`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({nome, phone, ativo, recebe_alertas})
    });
    if (!r.ok) return agwaToast('Erro ao salvar');
    await agwaCarregarUsuarios();
    agwaToast('Alterações salvas ✓');
  } catch(e) { agwaToast('Erro de conexão'); }
}

async function agwaDeletarUsuario(id, nome) {
  const ok = await showConfirm({ title: 'Remover usuário?', body: `"${nome}" será removido da Agenda via WhatsApp.`, okLabel: 'Remover', cancelLabel: 'Cancelar', type: 'danger', icon: '👤' });
  if (!ok) return;
  try {
    await fetch(`/api/config/agenda-wa-usuarios/${id}`, {method:'DELETE'});
    await agwaCarregarUsuarios();
    agwaToast(nome + ' removido');
  } catch(e) { agwaToast('Erro ao remover'); }
}

// ── Config avançada por usuário (alertas + resumo diário) ──────────────────
let _agwaCfgUsuarioId = null;

function agwaAbrirConfig(id) {
  const u = _agwaUsuarios.find(x => x.id === id);
  if (!u) return;
  _agwaCfgUsuarioId = id;

  // Preencher campos
  const digestEl = document.getElementById('agwa-cfg-digest-hora');
  if (digestEl) digestEl.value = u.morning_digest_hora || '';

  const ants = u.alert_antecedencias || [60];
  const antsEl = document.getElementById('agwa-cfg-antecedencias');
  if (antsEl) {
    // Checkboxes pré-definidas
    ['15','30','60','120'].forEach(v => {
      const chk = document.getElementById('agwa-cfg-ant-' + v);
      if (chk) chk.checked = ants.includes(parseInt(v));
    });
    // Campo custom
    const custom = ants.filter(x => ![15,30,60,120].includes(x));
    const customEl = document.getElementById('agwa-cfg-ant-custom');
    if (customEl) customEl.value = custom.join(', ');
  }

  document.getElementById('agwa-cfg-nome').textContent = u.nome;
  document.getElementById('agwa-cfg-overlay').classList.add('open');
}

function agwaFecharConfig(event, force) {
  if (!force && event && event.target !== document.getElementById('agwa-cfg-overlay')) return;
  document.getElementById('agwa-cfg-overlay').classList.remove('open');
  _agwaCfgUsuarioId = null;
}

async function agwaSalvarConfig() {
  if (!_agwaCfgUsuarioId) return;
  const digestHora = (document.getElementById('agwa-cfg-digest-hora')?.value || '').trim() || null;

  // Coletar antecedências: checkboxes + custom
  const ants = new Set();
  ['15','30','60','120'].forEach(v => {
    if (document.getElementById('agwa-cfg-ant-' + v)?.checked) ants.add(parseInt(v));
  });
  const customVal = document.getElementById('agwa-cfg-ant-custom')?.value || '';
  customVal.split(/[,\s]+/).forEach(v => {
    const n = parseInt(v);
    if (n > 0 && n <= 1440) ants.add(n);
  });

  const antecedencias = [...ants].sort((a, b) => b - a);
  if (!antecedencias.length) antecedencias.push(60);

  try {
    const r = await fetch(`/api/config/agenda-wa-usuarios/${_agwaCfgUsuarioId}/config`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ morning_digest_hora: digestHora, alert_antecedencias: antecedencias })
    });
    if (!r.ok) return agwaToast('Erro ao salvar configuração');
    await agwaCarregarUsuarios();
    agwaFecharConfig(null, true);
    agwaToast('Configuração salva ✓');
  } catch(e) { agwaToast('Erro de conexão'); }
}

// ── Config propósito da sessão WA ──────────────────────────────────────────
let _sessaoUsoId = null;
const _USOS_LABELS = {
  chatbot:   { label: 'Chatbot IA',         icon: '🤖' },
  campanhas: { label: 'Envio de Campanhas', icon: '📢' },
  arquivos:  { label: 'Gestão de Arquivos', icon: '📎' },
  agenda:    { label: 'Agenda WA',          icon: '📅' },
  pdv:       { label: 'PDV / Avaliação',    icon: '⭐' },
};

const _SESSAO_USOS_KEYS = ['chatbot','campanhas','arquivos','agenda','pdv'];

async function sessaoAbrirUsos(sessaoId) {
  _sessaoUsoId = sessaoId;
  const overlay = document.getElementById('sessao-usos-overlay');
  if (!overlay) { console.error('[sessao] overlay não encontrado'); return; }

  // Defaults: tudo marcado
  _SESSAO_USOS_KEYS.forEach(k => {
    const chk = document.getElementById('sessao-uso-' + k);
    if (chk) chk.checked = true;
  });

  try {
    const r = await fetch(`/api/config/sessao-usos/${sessaoId}`);
    if (r.ok) {
      const d = await r.json();
      const usos = d.usos || _SESSAO_USOS_KEYS;
      _SESSAO_USOS_KEYS.forEach(k => {
        const chk = document.getElementById('sessao-uso-' + k);
        if (chk) chk.checked = usos.includes(k);
      });
    }
  } catch(e) { console.warn('[sessao] fetch usos:', e); }

  overlay.classList.add('open');
}

function sessaoFecharUsos(event, force) {
  const overlay = document.getElementById('sessao-usos-overlay');
  if (!overlay) return;
  if (!force && event && event.target !== overlay) return;
  overlay.classList.remove('open');
  _sessaoUsoId = null;
}

async function sessaoSalvarUsos() {
  if (!_sessaoUsoId) return;
  const usos = _SESSAO_USOS_KEYS.filter(k => document.getElementById('sessao-uso-' + k)?.checked);
  try {
    const r = await fetch(`/api/config/sessao-usos/${_sessaoUsoId}`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ usos })
    });
    if (!r.ok) return agwaToast('Erro ao salvar');
    sessaoFecharUsos(null, true);
    agwaToast('Propósito da sessão salvo ✓');
  } catch(e) { agwaToast('Erro de conexão'); }
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
}

// Inicializa conector visual no item já ativo ao carregar
window.addEventListener('load', () => {
  const activeItem = document.querySelector('.nav-item.active');
  if (activeItem) _updateNavConnector(activeItem);
});
