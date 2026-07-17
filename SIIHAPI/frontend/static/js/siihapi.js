/* SIIHAPI · App helpers globales */
(function(){
  'use strict';

  // ── Toast UI ──
  function ensureWrap(){
    let w = document.getElementById('toastWrap');
    if(!w){ w = document.createElement('div'); w.id='toastWrap'; w.className='toast-wrap'; document.body.appendChild(w); }
    return w;
  }
  function toast(msg, kind){
    kind = kind || 'info';
    const ic = { success:'✅', error:'❌', warn:'⚠️', info:'ℹ️' }[kind] || 'ℹ️';
    const t = document.createElement('div');
    t.className = 'toast ' + kind;
    t.innerHTML = '<div class="toast-ico">'+ic+'</div><div class="toast-txt">'+String(msg).replace(/</g,'&lt;')+'</div>';
    ensureWrap().appendChild(t);
    setTimeout(()=>{ t.style.opacity='0'; t.style.transform='translateX(50px)'; setTimeout(()=>t.remove(),400); }, 3500);
  }
  window.toast = toast;

  // ── API client ──
  const API = {
    base: '',
    token: null,
    setToken(t){ this.token = t; localStorage.setItem('siihapi_token', t || ''); },
    getToken(){ return this.token || localStorage.getItem('siihapi_token'); },
    async request(method, path, body){
      const headers = { 'Content-Type':'application/json', 'Accept':'application/json' };
      const token = this.getToken();
      if(token) headers['Authorization'] = 'Bearer ' + token;
      const opts = { method, headers };
      if(body) opts.body = JSON.stringify(body);
      try{
        const r = await fetch(this.base + path, opts);
        const data = await r.json().catch(()=>({}));
        if(!r.ok) data._status = r.status;
        return data;
      }catch(err){ return { success:false, error:'Sin conexión al servidor' }; }
    },
    get(path){ return this.request('GET', path); },
    post(path, body){ return this.request('POST', path, body); },
  };
  window.API = API;

  // ── Auto-cierre toasts al cargar ──
  document.addEventListener('DOMContentLoaded', ()=>{
    setTimeout(()=> document.querySelectorAll('.toast').forEach(t=>{
      t.style.opacity='0'; setTimeout(()=>t.remove(),400);
    }), 4000);
  });
})();
