/* =========================================================
   SISCA · FX Layer
   - Tilt 3D al hover en cards / kpis / role-card
   - Reveal-on-scroll (.fx-reveal -> .fx-in)
   - Mouse-light en cards (pinta donde está el cursor)
   Sin dependencias. No toca ninguna lógica de negocio.
   ========================================================= */
(function(){
  'use strict';

  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ──────────────────────────────────────────────
  // 1) Reveal on scroll
  // ──────────────────────────────────────────────
  function setupReveal(){
    const candidates = document.querySelectorAll(
      '.land-hero .land-badge, .land-hero h1, .land-hero p, .mission-card, .role-card, .land-stats, .land-footer, .card, .kpi, .auth-card, .pg-header'
    );
    candidates.forEach(el => el.classList.add('fx-reveal'));

    if(!('IntersectionObserver' in window) || reduce){
      candidates.forEach(el => el.classList.add('fx-in'));
      return;
    }

    const io = new IntersectionObserver((entries)=>{
      entries.forEach(entry=>{
        if(entry.isIntersecting){
          entry.target.classList.add('fx-in');
          io.unobserve(entry.target);
        }
      });
    }, {threshold: 0.08, rootMargin: '0px 0px -40px 0px'});

    candidates.forEach(el => io.observe(el));
  }

  // ──────────────────────────────────────────────
  // 2) Tilt 3D + Mouse Light
  // ──────────────────────────────────────────────
  function setupTilt(){
    if(reduce) return;
    const targets = document.querySelectorAll('.role-card, .kpi, .card, .auth-card');
    targets.forEach(el=>{
      el.setAttribute('data-tilt','');
      let rafId = null;
      let rect = null;

      const onEnter = ()=>{ rect = el.getBoundingClientRect(); };
      const onMove = (e)=>{
        if(!rect) rect = el.getBoundingClientRect();
        const x = (e.clientX - rect.left) / rect.width;
        const y = (e.clientY - rect.top) / rect.height;

        // mouse light (--mx, --my en %)
        el.style.setProperty('--mx', (x*100).toFixed(1) + '%');
        el.style.setProperty('--my', (y*100).toFixed(1) + '%');

        // tilt sutil (máx ±6deg)
        const rx = (0.5 - y) * 6;
        const ry = (x - 0.5) * 8;
        if(rafId) cancelAnimationFrame(rafId);
        rafId = requestAnimationFrame(()=>{
          el.style.transform = `perspective(1100px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg) translateZ(0)`;
        });
      };
      const onLeave = ()=>{
        rect = null;
        if(rafId) cancelAnimationFrame(rafId);
        el.style.transform = '';
        el.style.setProperty('--mx', '50%');
        el.style.setProperty('--my', '0%');
      };

      el.addEventListener('mouseenter', onEnter);
      el.addEventListener('mousemove', onMove);
      el.addEventListener('mouseleave', onLeave);
    });
  }

  // ──────────────────────────────────────────────
  // 3) Botón "shine" — el .btn-primary ya tiene su propio shimmer en CSS,
  //    aquí solo nos aseguramos de animar count-up en KPIs y stats.
  // ──────────────────────────────────────────────
  function setupCountUp(){
    if(reduce) return;
    const els = document.querySelectorAll('.kpi-val, .stat-val');
    els.forEach(el=>{
      const raw = (el.textContent || '').trim();
      const n = parseFloat(raw.replace(/[^0-9.\-]/g,''));
      if(!isFinite(n) || n === 0) return;
      const suffix = raw.replace(/[\d.,\-]/g,'').trim();
      const dur = 1100;
      const start = performance.now();
      const from = 0;
      function step(now){
        const t = Math.min(1, (now - start)/dur);
        const eased = 1 - Math.pow(1-t, 3);
        const v = Math.round(from + (n - from) * eased);
        el.textContent = (suffix ? v + ' ' + suffix : v.toString());
        if(t < 1) requestAnimationFrame(step);
        else el.textContent = raw; // restaurar el formato original (por si tenía decimales/sufijos)
      }
      // Solo animar si está visible
      if('IntersectionObserver' in window){
        const io = new IntersectionObserver((entries)=>{
          entries.forEach(e=>{
            if(e.isIntersecting){
              requestAnimationFrame(step);
              io.disconnect();
            }
          });
        }, {threshold:0.4});
        io.observe(el);
      } else {
        requestAnimationFrame(step);
      }
    });
  }

  function init(){
    try{ setupReveal(); }catch(e){}
    try{ setupTilt(); }catch(e){}
    try{ setupCountUp(); }catch(e){}
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
