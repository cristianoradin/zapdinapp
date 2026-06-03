// ── IA Central ──────────────────────────────────────────────────────────────
// Motor de IA conversacional: Universe canvas, typewriter, histórico, charts.
// iaCentral exposto globalmente como window.iaCentral.
// Autossuficiente: usa fetch() diretamente.

// ── IA Central ───────────────────────────────────────────────────────────────

const iaCentral = (() => {
  let _historico = [];  // [{role, content}]
  let _sending = false;
  let _chartCount = 0;
  let _initialized = false;
  let _universeCleanup = null;

  function _escH(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  /* ── Universe Engine ─────────────────────────────────────────────────── */
  function _startUniverse() {
    const canvas = document.getElementById('iaUniverse');
    if (!canvas || canvas._running) return;
    canvas._running = true;

    const ctx = canvas.getContext('2d');
    let W = 0, H = 0, animId = null;
    const ro = new ResizeObserver(() => _resize());

    function _resize() {
      const pg = canvas.parentElement;
      W = canvas.width  = pg ? pg.offsetWidth  : window.innerWidth;
      H = canvas.height = pg ? pg.offsetHeight : window.innerHeight;
    }
    ro.observe(canvas.parentElement);
    _resize();

    /* helpers */
    const _r = () => Math.random();
    const _rng = (a, b) => a + _r() * (b - a);
    const _hex = (hex, a) => {
      const n = parseInt(hex.replace('#',''), 16);
      return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`;
    };

    /* ── Stars ── */
    function _makeStars(n) {
      return Array.from({length: n}, () => ({
        x: _r(), y: _r(),
        r: _rng(0.3, 1.8),
        base: _rng(0.2, 0.9),
        tph: _r() * Math.PI * 2,
        tsp: _rng(0.006, 0.025),
        dx: (_r() - .5) * 0.00012,
        dy: (_r() - .5) * 0.00012,
        col: ['#ffffff','#c8e8ff','#ffd8a0','#adf8ff','#d4ffb4'][Math.floor(_r()*5)],
      }));
    }
    const stars = _makeStars(320);

    /* ── Nebulas ── */
    const nebulas = [
      { nx:.12, ny:.18, nr:.45, col:'var(--primary-deep)', a:.09, sp:.00018, ph:0.0  },
      { nx:.82, ny:.72, nr:.4,  col:'#1a4fd6', a:.08, sp:.00013, ph:2.1  },
      { nx:.48, ny:.42, nr:.35, col:'#6d28d9', a:.06, sp:.00025, ph:4.3  },
      { nx:.15, ny:.82, nr:.3,  col:'#0891b2', a:.07, sp:.00016, ph:1.5  },
      { nx:.7,  ny:.12, nr:.35, col:'#7cdc44', a:.05, sp:.0002,  ph:3.7  },
      { nx:.9,  ny:.45, nr:.28, col:'#4f46e5', a:.05, sp:.0003,  ph:5.1  },
      { nx:.35, ny:.88, nr:.32, col:'#0f766e', a:.06, sp:.00022, ph:0.8  },
    ];

    /* ── Neural particles ── */
    function _makeParticles(n) {
      return Array.from({length: n}, () => ({
        x: _r(), y: _r(),
        dx: (_r()-.5) * .0008,
        dy: (_r()-.5) * .0008,
        r: _rng(.8, 2.5),
        a: _rng(.25, .7),
        col: ['#7cdc44','#3b82f6','#06b6d4','#a78bfa','#ffffff'][Math.floor(_r()*5)],
        pulse: 0, pulseDir: 1,
      }));
    }
    const parts = _makeParticles(55);

    /* ── Shooting stars ── */
    const shoots = [];
    let shootTimer = 0;

    /* ── Pulse rings ── */
    const pulses = [];
    let pulseTimer = 0;

    /* ── Warp (periodic) ── */
    let warpTimer = 0, warpActive = false, warpAlpha = 0;
    const warpLines = [];

    /* ── Data streams (vertical) ── */
    const streams = Array.from({length: 12}, () => ({
      x: _r(),
      y: _r() * -.5,
      speed: _rng(.0006, .0018),
      len: _rng(.08, .25),
      a: _rng(.05, .18),
      col: ['#7cdc44','#3b82f6','#06b6d4'][Math.floor(_r()*3)],
    }));

    let t = 0;

    function _frame() {
      t++;
      ctx.clearRect(0, 0, W, H);

      /* BG */
      ctx.fillStyle = '#060a11';
      ctx.fillRect(0, 0, W, H);

      /* Nebulas */
      nebulas.forEach(n => {
        n.ph += n.sp * 60;
        const sc  = 1 + Math.sin(n.ph) * .14;
        const gx  = n.nx * W + Math.sin(n.ph * .7) * W * .05;
        const gy  = n.ny * H + Math.cos(n.ph * .53) * H * .05;
        const rad = Math.max(W, H) * n.nr * sc;
        const g   = ctx.createRadialGradient(gx, gy, 0, gx, gy, rad);
        g.addColorStop(0, _hex(n.col, n.a + Math.sin(n.ph) * .025));
        g.addColorStop(.5, _hex(n.col, n.a * .3));
        g.addColorStop(1, 'transparent');
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);
      });

      /* Stars */
      stars.forEach(s => {
        s.tph += s.tsp;
        s.x = (s.x + s.dx + 1) % 1;
        s.y = (s.y + s.dy + 1) % 1;
        const a = s.base * (.4 + .6 * Math.abs(Math.sin(s.tph)));
        const sx = s.x * W, sy = s.y * H;
        ctx.save();
        ctx.globalAlpha = a;
        if (s.r > 1.2) { ctx.shadowBlur = 5; ctx.shadowColor = s.col; }
        ctx.fillStyle = s.col;
        ctx.beginPath();
        ctx.arc(sx, sy, s.r, 0, Math.PI*2);
        ctx.fill();
        ctx.restore();
      });

      /* Data streams */
      streams.forEach(s => {
        s.y += s.speed;
        if (s.y > 1.2) { s.y = _rng(-.4, 0); s.x = _r(); }
        const sx = s.x * W, sy = s.y * H, slen = s.len * H;
        ctx.save();
        const g = ctx.createLinearGradient(sx, sy, sx, sy + slen);
        g.addColorStop(0, 'transparent');
        g.addColorStop(.4, _hex(s.col, s.a));
        g.addColorStop(1, 'transparent');
        ctx.strokeStyle = g;
        ctx.lineWidth = .8;
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        ctx.lineTo(sx, sy + slen);
        ctx.stroke();
        ctx.restore();
      });

      /* Neural connections */
      const CDIST = 0.2; // fraction of screen
      for (let i = 0; i < parts.length; i++) {
        for (let j = i+1; j < parts.length; j++) {
          const dx = (parts[i].x - parts[j].x) * W;
          const dy = (parts[i].y - parts[j].y) * H;
          const d  = Math.sqrt(dx*dx + dy*dy);
          const md = CDIST * Math.min(W, H);
          if (d < md) {
            ctx.save();
            ctx.globalAlpha = (1 - d/md) * .12;
            ctx.strokeStyle = '#7cdc44';
            ctx.lineWidth = .6;
            ctx.beginPath();
            ctx.moveTo(parts[i].x*W, parts[i].y*H);
            ctx.lineTo(parts[j].x*W, parts[j].y*H);
            ctx.stroke();
            ctx.restore();
          }
        }
      }

      /* Particles */
      parts.forEach(p => {
        p.x = (p.x + p.dx + 1) % 1;
        p.y = (p.y + p.dy + 1) % 1;
        p.pulse += .03 * p.pulseDir;
        if (p.pulse > 1 || p.pulse < 0) p.pulseDir *= -1;
        ctx.save();
        ctx.globalAlpha = p.a * (.6 + .4 * p.pulse);
        ctx.shadowBlur = 8 + p.pulse * 8;
        ctx.shadowColor = p.col;
        ctx.fillStyle = p.col;
        ctx.beginPath();
        ctx.arc(p.x*W, p.y*H, p.r, 0, Math.PI*2);
        ctx.fill();
        ctx.restore();
      });

      /* Pulse rings */
      pulseTimer++;
      if (pulseTimer > 180 + Math.random() * 240) {
        pulseTimer = 0;
        const pc = parts[Math.floor(_r() * parts.length)];
        pulses.push({ x: pc.x*W, y: pc.y*H, rr: 0, a: .6, col: pc.col });
      }
      for (let i = pulses.length-1; i >= 0; i--) {
        const p = pulses[i];
        p.rr += 2.5; p.a -= .006;
        if (p.a <= 0) { pulses.splice(i,1); continue; }
        ctx.save();
        ctx.globalAlpha = p.a;
        ctx.strokeStyle = p.col;
        ctx.lineWidth = 1;
        ctx.shadowBlur = 8; ctx.shadowColor = p.col;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.rr, 0, Math.PI*2);
        ctx.stroke();
        ctx.restore();
      }

      /* Shooting stars */
      shootTimer++;
      if (shootTimer > 140 + Math.random() * 300) {
        shootTimer = 0;
        shoots.push({
          x: _rng(.1, .9) * W, y: _rng(0, .4) * H,
          vx: _rng(5,10), vy: _rng(2,5), life: 0,
          col: ['#ffffff','#c8e8ff','#7cdc44'][Math.floor(_r()*3)],
        });
      }
      for (let i = shoots.length-1; i >= 0; i--) {
        const s = shoots[i];
        s.x += s.vx; s.y += s.vy; s.life++;
        const a = Math.max(0, 1 - s.life/35);
        if (a <= 0 || s.x > W || s.y > H) { shoots.splice(i,1); continue; }
        ctx.save();
        ctx.globalAlpha = a;
        const g = ctx.createLinearGradient(s.x - s.vx*8, s.y - s.vy*8, s.x, s.y);
        g.addColorStop(0, 'transparent');
        g.addColorStop(1, s.col);
        ctx.strokeStyle = g;
        ctx.lineWidth = 1.5;
        ctx.shadowBlur = 6; ctx.shadowColor = s.col;
        ctx.beginPath();
        ctx.moveTo(s.x - s.vx*8, s.y - s.vy*8);
        ctx.lineTo(s.x, s.y);
        ctx.stroke();
        ctx.restore();
      }

      /* Warp burst (every ~600 frames) */
      warpTimer++;
      if (!warpActive && warpTimer > 600 + Math.random() * 400) {
        warpTimer = 0; warpActive = true; warpAlpha = 0;
        warpLines.length = 0;
        const cx = W/2, cy = H/2;
        for (let i = 0; i < 60; i++) {
          const ang = _r() * Math.PI * 2;
          const len = _rng(.15, .55) * Math.max(W,H);
          warpLines.push({ ang, len, a: _rng(.2,.7),
            col: ['#ffffff','#7cdc44','#3b82f6'][Math.floor(_r()*3)] });
        }
      }
      if (warpActive) {
        warpAlpha = warpAlpha < .3 ? warpAlpha + .015 : warpAlpha - .012;
        if (warpAlpha < 0) { warpAlpha = 0; warpActive = false; }
        const cx = W/2, cy = H/2;
        warpLines.forEach(l => {
          ctx.save();
          ctx.globalAlpha = warpAlpha * l.a;
          ctx.strokeStyle = l.col;
          ctx.lineWidth = .7;
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.lineTo(cx + Math.cos(l.ang)*l.len*warpAlpha*4,
                     cy + Math.sin(l.ang)*l.len*warpAlpha*4);
          ctx.stroke();
          ctx.restore();
        });
      }

      animId = requestAnimationFrame(_frame);
    }

    _frame();

    _universeCleanup = () => {
      cancelAnimationFrame(animId);
      ro.disconnect();
      canvas._running = false;
    };
  }

  function _addMsg(role, content, chartData) {
    const msgsEl = document.getElementById('iaMsgs');
    if (!msgsEl) return;

    if (role === 'user') {
      msgsEl.insertAdjacentHTML('beforeend', `
        <div class="ia-msg-user">
          <div class="ia-bubble">${_escH(content)}</div>
        </div>`);
      msgsEl.scrollTop = msgsEl.scrollHeight;
    } else {
      // Cria bolha vazia com cursor piscando
      const msgId = 'iaMsg' + Date.now();
      msgsEl.insertAdjacentHTML('beforeend', `
        <div class="ia-msg-ia" id="${msgId}">
          <div class="ia-mini-avatar">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a8 8 0 0 1 8 8v1a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4v-1a8 8 0 0 1 8-8z"/><circle cx="9" cy="10" r="1" fill="#fff"/><circle cx="15" cy="10" r="1" fill="#fff"/></svg>
          </div>
          <div class="ia-bubble" id="${msgId}-bubble"><span class="ia-cursor"></span></div>
        </div>`);
      msgsEl.scrollTop = msgsEl.scrollHeight;

      // Typewriter effect
      const bubbleEl = document.getElementById(msgId + '-bubble');
      const chars = content.split('');
      let idx = 0;
      // Velocidade adaptativa: textos longos são mais rápidos
      const speed = content.length > 300 ? 8 : content.length > 100 ? 14 : 22;

      function _type() {
        if (!bubbleEl) return;
        if (idx < chars.length) {
          // Acumula texto renderizado e re-parseia formatação
          const partial = _escH(content.slice(0, idx + 1))
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\n/g, '<br>');
          bubbleEl.innerHTML = partial + '<span class="ia-cursor"></span>';
          idx++;
          msgsEl.scrollTop = msgsEl.scrollHeight;
          setTimeout(_type, speed);
        } else {
          // Finaliza sem cursor
          const full = _escH(content)
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\n/g, '<br>');
          bubbleEl.innerHTML = full;

          // Renderiza gráfico após texto completo
          if (chartData) {
            _chartCount++;
            const cid = 'iaChart' + _chartCount;
            msgsEl.insertAdjacentHTML('beforeend', `
              <div class="ia-chart-wrap">
                <canvas id="${cid}"></canvas>
              </div>`);
            setTimeout(() => {
              const ctx = document.getElementById(cid);
              if (ctx && window.Chart) new Chart(ctx, chartData);
              msgsEl.scrollTop = msgsEl.scrollHeight;
            }, 80);
          }
        }
      }
      setTimeout(_type, 60);
    }
  }

  function _setLoading(on) {
    _sending = on;
    const ld = document.getElementById('iaLoading');
    const btn = document.querySelector('.ia-send-btn');
    const ta = document.getElementById('iaInput');
    if (ld) ld.style.display = on ? 'flex' : 'none';
    if (btn) btn.disabled = on;
    if (ta) ta.disabled = on;
  }

  async function enviar(texto) {
    if (_sending) return;
    const ta = document.getElementById('iaInput');
    const msg = (texto || ta?.value || '').trim();
    if (!msg) return;
    if (ta) { ta.value = ''; ta.style.height = 'auto'; }

    _addMsg('user', msg);
    _historico.push({ role: 'user', content: msg });
    _setLoading(true);

    try {
      const res = await fetch('/api/ia-central/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mensagem: msg, historico: _historico.slice(-12) }),
      });

      if (res.status === 401) { window.location.href = '/login'; return; }

      const data = await res.json();

      if (!res.ok) {
        const errMsg = data.detail || 'Erro desconhecido';
        const msgsEl = document.getElementById('iaMsgs');
        if (msgsEl) msgsEl.insertAdjacentHTML('beforeend',
          `<div class="ia-erro">⚠️ ${_escH(errMsg)}</div>`);
        return;
      }

      const resposta = data.resposta || '';
      _addMsg('ia', resposta, data.chart || null);
      _historico.push({ role: 'assistant', content: resposta });

      // Limita histórico a 40 entradas
      if (_historico.length > 40) _historico = _historico.slice(-40);

    } catch(e) {
      console.error('[ia-central]', e);
      const msgsEl = document.getElementById('iaMsgs');
      if (msgsEl) msgsEl.insertAdjacentHTML('beforeend',
        `<div class="ia-erro">⚠️ Falha de conexão. Tente novamente.</div>`);
    } finally {
      _setLoading(false);
      document.getElementById('iaMsgs')?.scrollTo(0, 999999);
    }
  }

  function sugerir(texto) { enviar(texto); }

  function limpar() {
    _historico = [];
    _chartCount = 0;
    _initialized = false;
    const msgsEl = document.getElementById('iaMsgs');
    if (msgsEl) msgsEl.innerHTML = '';
    init();
  }

  function init() {
    const msgsEl = document.getElementById('iaMsgs');
    if (!msgsEl) return;
    // _startUniverse desativado — tema claro substituiu canvas escuro
    if (_initialized) return;
    _initialized = true;
    _addMsg('ia', 'Olá! Sou a IA Central do ZapDin. Posso responder perguntas sobre envios, campanhas, chatbot, sessões WhatsApp e muito mais. Como posso ajudar?');
  }

  return { enviar, sugerir, limpar, init };
})();
window.iaCentral = iaCentral;
