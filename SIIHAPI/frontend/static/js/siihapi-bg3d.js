/* =========================================================
   SIIHAPI · Cinematic Background con Three.js
   Partículas + orbes violeta/cyan/lima
   ========================================================= */
(function(){
  'use strict';
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) return;
  const lowEnd = (navigator.hardwareConcurrency || 4) <= 2 && /Mobi|Android/i.test(navigator.userAgent);
  if (lowEnd) return;

  function loadScript(src){
    return new Promise((resolve, reject)=>{
      const s = document.createElement('script');
      s.src = src; s.async = true; s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  function ensureCanvas(){
    let c = document.getElementById('bg3d');
    if(!c){ c = document.createElement('canvas'); c.id='bg3d'; document.body.prepend(c); }
    return c;
  }
  function init(THREE){
    const canvas = ensureCanvas();
    const scene  = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, window.innerWidth/window.innerHeight, 0.1, 100);
    camera.position.z = 8;
    const renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 0);

    // Partículas con tonos SIIHAPI (violeta tirando a cyan)
    const N = window.innerWidth < 800 ? 700 : 1600;
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(N*3);
    const sp  = new Float32Array(N);
    for(let i=0;i<N;i++){
      pos[i*3]   = (Math.random()-0.5)*30;
      pos[i*3+1] = (Math.random()-0.5)*20;
      pos[i*3+2] = (Math.random()-0.5)*18 - 4;
      sp[i] = 0.0015 + Math.random()*0.004;
    }
    geo.setAttribute('position', new THREE.BufferAttribute(pos,3));
    const mat = new THREE.PointsMaterial({
      color:0x9DC4FF, size:0.035, transparent:true, opacity:0.75,
      depthWrite:false, blending:THREE.AdditiveBlending, sizeAttenuation:true
    });
    const particles = new THREE.Points(geo, mat);
    scene.add(particles);

    // Orbes wireframe con paleta SIIHAPI: violeta, cyan, indigo, lima, rosa
    const orbColors = [0x4D9BFF, 0x22D3EE, 0x6366F1, 0xA3E635, 0x22D3EE, 0x6366F1];
    const orbCount = window.innerWidth < 800 ? 4 : 7;
    const orbs = [];
    for(let i=0;i<orbCount;i++){
      const geom = new THREE.IcosahedronGeometry(0.8 + Math.random()*0.7, 1);
      const mat = new THREE.MeshBasicMaterial({
        color: orbColors[i % orbColors.length],
        wireframe:true, transparent:true, opacity:0.20
      });
      const orb = new THREE.Mesh(geom, mat);
      orb.position.set(
        (Math.random()-0.5)*16,
        (Math.random()-0.5)*10,
        (Math.random()-0.5)*6 - 2
      );
      orb.userData = {
        rotSpeed:(Math.random()-0.5)*0.004,
        floatSpeed:0.0008 + Math.random()*0.0012,
        floatRange:0.3 + Math.random()*0.5,
        baseY:orb.position.y, offset:Math.random()*Math.PI*2
      };
      scene.add(orb);
      orbs.push(orb);
    }

    // Mouse parallax
    const mouse = {x:0, y:0, tx:0, ty:0};
    window.addEventListener('mousemove',(e)=>{
      mouse.tx = (e.clientX / window.innerWidth - 0.5) * 0.6;
      mouse.ty = (e.clientY / window.innerHeight - 0.5) * 0.6;
    }, {passive:true});

    function onResize(){
      camera.aspect = window.innerWidth/window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    }
    window.addEventListener('resize', onResize, {passive:true});

    let last = performance.now();
    let run = true;
    document.addEventListener('visibilitychange', ()=>{ run = !document.hidden; });

    function tick(now){
      requestAnimationFrame(tick);
      if(!run) return;
      const dt = Math.min(50, now-last); last = now;
      const t = now*0.001;

      mouse.x += (mouse.tx - mouse.x) * 0.05;
      mouse.y += (mouse.ty - mouse.y) * 0.05;
      camera.position.x = mouse.x * 1.2;
      camera.position.y = -mouse.y * 0.8;
      camera.lookAt(0,0,0);

      const a = geo.attributes.position.array;
      for(let i=0;i<N;i++){
        a[i*3+2] += sp[i]*dt;
        if(a[i*3+2] > 6){
          a[i*3+2] = -12;
          a[i*3] = (Math.random()-0.5)*30;
          a[i*3+1] = (Math.random()-0.5)*20;
        }
      }
      geo.attributes.position.needsUpdate = true;
      particles.rotation.y += 0.0004;
      for(const o of orbs){
        o.rotation.x += o.userData.rotSpeed;
        o.rotation.y += o.userData.rotSpeed*1.4;
        o.position.y = o.userData.baseY + Math.sin(t*o.userData.floatSpeed*200 + o.userData.offset)*o.userData.floatRange;
      }
      renderer.render(scene, camera);
    }
    requestAnimationFrame(tick);
  }
  function start(){
    if(window.THREE){ init(window.THREE); return; }
    loadScript('https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js')
      .then(()=> init(window.THREE)).catch(()=>{});
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
