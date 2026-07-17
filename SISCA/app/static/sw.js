/* SISCA · Service Worker — Modo Offline (RF-25, RF-40) */
const CACHE = 'sisca-v1';
const OFFLINE_QUEUE = 'sisca-offline-queue';
const STATIC = [
  '/',
  '/static/css/sisca.css',
  '/static/js/sisca.js',
  '/static/manifest.json',
];

self.addEventListener('install', e=>{
  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(STATIC)));
  self.skipWaiting();
});
self.addEventListener('activate', e=>{
  e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch', e=>{
  if(e.request.method!=='GET'){ e.respondWith(networkOrQueue(e.request)); return; }
  e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).catch(()=>new Response('Offline'))));
});

async function networkOrQueue(req){
  try{ return await fetch(req.clone()); }
  catch(err){
    const body = await req.clone().text();
    const queue = (await getQueue())||[];
    queue.push({url:req.url, method:req.method, body, ts:Date.now()});
    await setQueue(queue);
    return new Response(JSON.stringify({ok:false,queued:true}),{headers:{'Content-Type':'application/json'}});
  }
}

async function syncQueue(){
  const queue = await getQueue()||[];
  const remaining=[];
  for(const item of queue){
    try{
      await fetch(item.url,{method:item.method,body:item.body,headers:{'Content-Type':'application/x-www-form-urlencoded'}});
    }catch(e){ remaining.push(item); }
  }
  await setQueue(remaining);
}

self.addEventListener('sync', e=>{ if(e.tag==='sisca-sync') e.waitUntil(syncQueue()); });

function getQueue(){ return caches.open(OFFLINE_QUEUE).then(c=>c.match('queue').then(r=>r?r.json():[])); }
function setQueue(q){ return caches.open(OFFLINE_QUEUE).then(c=>c.put('queue', new Response(JSON.stringify(q)))); }
