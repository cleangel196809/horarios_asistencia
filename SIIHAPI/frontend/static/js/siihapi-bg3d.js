/* =========================================================
   INTEGRA-PI · Fondo institucional "plano arquitectónico"
   Retícula de líneas finas + contorno isométrico de campus,
   movimiento lento tipo "documento que respira" (sin partículas
   ni orbes energéticos: uso diario de personal administrativo,
   no landing de producto tech). Fase 3 (2026-09-04).
   ========================================================= */
(function(){
  'use strict';
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function ensureCanvas(){
    var c = document.getElementById('bg3d');
    if(!c){ c = document.createElement('canvas'); c.id='bg3d'; document.body.prepend(c); }
    return c;
  }

  var canvas = ensureCanvas();
  var ctx = canvas.getContext('2d');
  var W = 0, H = 0, DPR = 1;

  function resize(){
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = Math.max(1, W * DPR);
    canvas.height = Math.max(1, H * DPR);
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    layoutCampus();
  }

  // Paleta institucional (coincide con los tokens de siihapi.css)
  var LINE_BLUE = 'rgba(124,185,255,';   // --blue-sky
  var LINE_CYAN = 'rgba(103,232,249,';   // --cyan-soft
  var LINE_GOLD = 'rgba(240,192,48,';    // --gold-lt

  // Parallax muy suave: el plano responde, no reacciona.
  var mouse = { x: 0, y: 0, tx: 0, ty: 0 };
  window.addEventListener('mousemove', function (e) {
    mouse.tx = (e.clientX / W - 0.5) * 14;
    mouse.ty = (e.clientY / H - 0.5) * 8;
  }, { passive: true });

  // --- Contorno isométrico de "campus" (solo aristas, sin relleno) ---
  function isoPoint(x, y, z) {
    return { x: (x - z) * 0.86, y: (x + z) * 0.5 - y };
  }
  function buildingEdges(ox, oy, w, d, h) {
    var pts = [];
    for (var iy = 0; iy <= 1; iy++)
      for (var ix = 0; ix <= 1; ix++)
        for (var iz = 0; iz <= 1; iz++)
          pts.push(isoPoint((ix - 0.5) * w, iy * h, (iz - 0.5) * d));
    var edges = [
      [0, 1], [0, 2], [0, 4], [1, 3], [1, 5], [2, 3],
      [2, 6], [3, 7], [4, 5], [4, 6], [5, 7], [6, 7]
    ];
    return edges.map(function (e) {
      return [
        { x: ox + pts[e[0]].x, y: oy + pts[e[0]].y },
        { x: ox + pts[e[1]].x, y: oy + pts[e[1]].y }
      ];
    });
  }

  var campus = [];
  function layoutCampus() {
    if (!W || !H) return;
    var cx = W * 0.76, cy = H * 0.40;
    campus = [];
    campus = campus.concat(buildingEdges(cx, cy, 160, 120, 140));
    campus = campus.concat(buildingEdges(cx - 195, cy + 78, 105, 95, 92));
    campus = campus.concat(buildingEdges(cx + 160, cy + 46, 92, 82, 72));
  }

  var GRID = 46; // celda de la retícula, en px CSS

  function draw(t) {
    ctx.clearRect(0, 0, W, H);

    // Respiración lenta (documento vivo): ciclo de ~15s, no un parpadeo.
    var breathe = (Math.sin((t / 15000) * Math.PI * 2) + 1) / 2; // 0..1
    var gridOpa = 0.045 + breathe * 0.030;
    var campusOpa = 0.10 + breathe * 0.06;

    var offX = (mouse.x * 0.4) % GRID;
    var offY = (mouse.y * 0.4) % GRID;

    // 1) Retícula fina (plano arquitectónico)
    ctx.lineWidth = 1;
    ctx.strokeStyle = LINE_BLUE + gridOpa.toFixed(3) + ')';
    ctx.beginPath();
    for (var x = -GRID; x <= W + GRID; x += GRID) { ctx.moveTo(x + offX, 0); ctx.lineTo(x + offX, H); }
    for (var y = -GRID; y <= H + GRID; y += GRID) { ctx.moveTo(0, y + offY); ctx.lineTo(W, y + offY); }
    ctx.stroke();

    // Líneas maestras cada 4 celdas, en cian, un poco más marcadas
    ctx.strokeStyle = LINE_CYAN + (gridOpa * 1.5).toFixed(3) + ')';
    ctx.beginPath();
    for (var x2 = -GRID; x2 <= W + GRID; x2 += GRID * 4) { ctx.moveTo(x2 + offX, 0); ctx.lineTo(x2 + offX, H); }
    for (var y2 = -GRID; y2 <= H + GRID; y2 += GRID * 4) { ctx.moveTo(0, y2 + offY); ctx.lineTo(W, y2 + offY); }
    ctx.stroke();

    // 2) Contorno isométrico del campus, en dorado muy sutil
    ctx.lineWidth = 1.2;
    ctx.strokeStyle = LINE_GOLD + campusOpa.toFixed(3) + ')';
    ctx.beginPath();
    var dx = mouse.x * 0.18, dy = mouse.y * 0.12;
    for (var i = 0; i < campus.length; i++) {
      var e = campus[i];
      ctx.moveTo(e[0].x + dx, e[0].y + dy);
      ctx.lineTo(e[1].x + dx, e[1].y + dy);
    }
    ctx.stroke();

    mouse.x += (mouse.tx - mouse.x) * 0.02;
    mouse.y += (mouse.ty - mouse.y) * 0.02;
  }

  window.addEventListener('resize', resize, { passive: true });
  resize();

  if (reduce) { draw(0); return; }

  var run = true;
  document.addEventListener('visibilitychange', function () { run = !document.hidden; });

  function tick(t) {
    requestAnimationFrame(tick);
    if (!run) return;
    draw(t);
  }
  requestAnimationFrame(tick);
})();
