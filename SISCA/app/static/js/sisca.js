/* SISCA · sisca.js — Interactividad principal */
'use strict';

// ── Toast System ──────────────────────────────────────────
function showToast(msg, type='info', duration=4000){
  const icons = {success:'✅', error:'❌', info:'ℹ️', warn:'⚠️'};
  let wrap = document.getElementById('toastWrap');
  if(!wrap){
    wrap = document.createElement('div');
    wrap.id='toastWrap';
    wrap.className='toast-wrap';
    document.body.appendChild(wrap);
  }
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<span class="toast-ico">${icons[type]||'ℹ️'}</span><div class="toast-txt">${msg}</div>`;
  wrap.appendChild(t);
  setTimeout(()=>{
    t.style.opacity='0';
    t.style.transform='translateX(110%)';
    t.style.transition='.3s';
    setTimeout(()=>t.remove(), 300);
  }, duration);
}

// ── Modal ─────────────────────────────────────────────────
function openModal(html){
  document.getElementById('modalBox').innerHTML = html;
  document.getElementById('modalBg').classList.add('open');
}
function closeModal(){
  document.getElementById('modalBg')?.classList.remove('open');
}

// ── Sidebar Toggle ────────────────────────────────────────
function toggleSidebar(){
  document.getElementById('sidebar')?.classList.toggle('open');
}

// ── Page Tabs ─────────────────────────────────────────────
function showPage(id){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.sb-item').forEach(i=>i.classList.remove('active'));
  const page = document.getElementById(id);
  if(page) page.classList.add('active');
  document.querySelectorAll(`[data-page="${id}"]`).forEach(el=>el.classList.add('active'));
  localStorage.setItem('sisca_page', id);
}
function initPages(){
  const saved = localStorage.getItem('sisca_page');
  const first = document.querySelector('.page');
  if(saved && document.getElementById(saved)){ showPage(saved); }
  else if(first){ showPage(first.id); }
}

// ── QR Timer ─────────────────────────────────────────────
function startQRTimer(seconds, onExpire){
  const el = document.getElementById('qrTimer');
  if(!el) return;
  let t = seconds;
  const interval = setInterval(()=>{
    t--;
    const m = Math.floor(t/60), s = t%60;
    if(el) el.textContent = `${m}:${s.toString().padStart(2,'0')}`;
    const pct = t/seconds*100;
    const bar = document.getElementById('qrTimerBar');
    if(bar){
      bar.style.width = pct+'%';
      if(pct<30) bar.className='prog-fill danger';
      else if(pct<60) bar.className='prog-fill warn';
    }
    if(t<=0){ clearInterval(interval); if(onExpire) onExpire(); }
  }, 1000);
  return interval;
}

// ── Attendance Count Poll (Docente) ──────────────────────
function pollAttendance(sesionId, interval=5000){
  setInterval(async()=>{
    try{
      const r = await fetch(`/asistencia/sesion/${sesionId}/count`);
      if(r.ok){
        const d = await r.json();
        const el = document.getElementById('contadorAsist');
        if(el && d.total !== undefined) el.textContent = d.total;
      }
    }catch(e){}
  }, interval);
}

// ── Student Active Session Poll ───────────────────────────
function pollSesionActiva(interval=20000){
  const banner = document.getElementById('sesion-activa-banner');
  setInterval(async()=>{
    try{
      const r = await fetch('/estudiante/sesion-activa/poll');
      if(!r.ok) return;
      const d = await r.json();
      if(d.activa && !banner){
        showToast('📡 ¡Tu docente inició una sesión! Recargando…','info');
        setTimeout(()=>location.reload(), 2000);
      } else if(!d.activa && banner){
        showToast('La sesión de clase ha finalizado.','warn');
        setTimeout(()=>location.reload(), 3000);
      }
    }catch(e){}
  }, interval);
}

// ── Copy to clipboard ─────────────────────────────────────
function copyToClipboard(text, msg='Copiado'){
  navigator.clipboard.writeText(text)
    .then(()=>showToast(msg,'success'))
    .catch(()=>{
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position='fixed';
      ta.style.opacity='0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      showToast(msg,'success');
    });
}

// ── Search Filter ─────────────────────────────────────────
function filterTable(inputId, tableId){
  const input = document.getElementById(inputId);
  if(!input) return;
  input.addEventListener('input', function(){
    const q = this.value.toLowerCase();
    document.querySelectorAll(`#${tableId} tbody tr`).forEach(row=>{
      row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });
}

// ── Confirm helper ────────────────────────────────────────
function confirmAction(msg, callback){
  if(confirm(msg)) callback();
}

// ── PWA Offline Banner ────────────────────────────────────
window.addEventListener('online',  ()=>showToast('Conexión restaurada', 'success'));
window.addEventListener('offline', ()=>showToast('Sin conexión · Modo Offline activo', 'warn', 10000));

// ── Init ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', ()=>{
  initPages();
  // Cerrar sidebar al hacer click fuera en móvil
  document.addEventListener('click', e=>{
    const sb  = document.getElementById('sidebar');
    const btn = document.querySelector('.sidebar-toggle');
    if(sb && sb.classList.contains('open') && !sb.contains(e.target) && e.target!==btn){
      sb.classList.remove('open');
    }
  });
  // Activar polling de sesión en panel estudiante (solo fuera del dashboard para no duplicar)
  if(document.body.dataset.rol === 'ESTUDIANTE' && !document.getElementById('formRegistroAsistencia')){
    pollSesionActiva(20000);
  }
});
