/* SIIHAPI · FX Layer (tilt 3D + reveal on scroll + count-up) */
(function(){
  'use strict';
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function setupReveal(){
    // Reveal-on-scroll SOLO en la landing (no en el dashboard, para no ocultar
    // tarjetas ni KPIs). El dashboard usa una entrada suave global (ver base.html).
    const targets = document.querySelectorAll(
      '.land-hero .land-badge, .land-hero h1, .land-hero p, .mission-card, .role-card, .land-stats, .land-footer, .auth-card'
    );
    targets.forEach(el => el.classList.add('fx-reveal'));
    if(!('IntersectionObserver' in window) || reduce){
      targets.forEach(el => el.classList.add('fx-in'));
      return;
    }
    const io = new IntersectionObserver((entries)=>{
      entries.forEach(e=>{
        if(e.isIntersecting){ e.target.classList.add('fx-in'); io.unobserve(e.target); }
      });
    }, {threshold:0.02, rootMargin:'0px 0px 0px 0px'});
    targets.forEach(el => io.observe(el));

    // Revelar de inmediato lo que YA esta visible al cargar (evita que el
    // contenido del dashboard quede tenue dentro de .main-content con scroll).
    const revelarVisibles = () => {
      const vh = window.innerHeight || document.documentElement.clientHeight || 800;
      targets.forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.top < vh && r.bottom > 0) { el.classList.add('fx-in'); io.unobserve(el); }
      });
    };
    revelarVisibles();
    requestAnimationFrame(revelarVisibles);
    // Respaldo de seguridad: si por cualquier motivo el observer no dispara,
    // garantizamos que TODO sea visible (nunca queda contenido oculto).
    setTimeout(() => targets.forEach(el => el.classList.add('fx-in')), 700);
  }

  function setupTilt(){
    if(reduce) return;
    const targets = document.querySelectorAll('.role-card, .kpi, .card, .auth-card');
    targets.forEach(el=>{
      el.setAttribute('data-tilt','');
      let rect = null, raf = null;
      el.addEventListener('mouseenter', ()=>{ rect = el.getBoundingClientRect(); });
      el.addEventListener('mousemove', (e)=>{
        if(!rect) rect = el.getBoundingClientRect();
        const x = (e.clientX - rect.left) / rect.width;
        const y = (e.clientY - rect.top) / rect.height;
        el.style.setProperty('--mx', (x*100).toFixed(1)+'%');
        el.style.setProperty('--my', (y*100).toFixed(1)+'%');
        const rx = (0.5 - y) * 6;
        const ry = (x - 0.5) * 8;
        if(raf) cancelAnimationFrame(raf);
        raf = requestAnimationFrame(()=>{
          el.style.transform = `perspective(1100px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg) translateZ(0)`;
        });
      });
      el.addEventListener('mouseleave', ()=>{
        rect = null;
        if(raf) cancelAnimationFrame(raf);
        el.style.transform = '';
        el.style.setProperty('--mx','50%'); el.style.setProperty('--my','0%');
      });
    });
  }

  function setupCountUp(){
    if(reduce) return;
    const els = document.querySelectorAll('.kpi-val, .stat-val');
    els.forEach(el=>{
      const raw = (el.textContent || '').trim();
      const sufijo = /%$/.test(raw) ? '%' : '';
      const n = parseFloat(raw.replace(/[^0-9.\-]/g,''));
      if(!isFinite(n) || n === 0) return;
      function animar(start){
        return function step(now){
          const t = Math.min(1, (now - start) / 1100);
          const val = Math.round(n * (0.5 - Math.cos(Math.PI * t) / 2)); // easeInOut
          el.textContent = val + sufijo;
          if(t < 1) requestAnimationFrame(step);
          else el.textContent = raw; // restaurar texto exacto original
        };
      }
      if('IntersectionObserver' in window){
        const io = new IntersectionObserver((entries)=>{
          entries.forEach(e=>{
            if(e.isIntersecting){ requestAnimationFrame(animar(performance.now())); io.disconnect(); }
          });
        }, {threshold:0.1});
        io.observe(el);
        // respaldo: si no dispara, animar igual
        setTimeout(()=>{ requestAnimationFrame(animar(performance.now())); }, 800);
      } else {
        requestAnimationFrame(animar(performance.now()));
      }
    });
  }

  function init(){
    try { setupReveal(); } catch(e){}
    try { setupTilt(); } catch(e){}
    try { setupCountUp(); } catch(e){}
  }
  if(document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
