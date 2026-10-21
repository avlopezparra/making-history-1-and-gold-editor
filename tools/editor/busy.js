// Barra de carga con porcentaje («Now loading… 45 %»): se ve mientras el servidor aplica cambios (peticiones que no son
// GET) y mientras la página redibuja lo cambiado (window.mhBusy(promesa, texto)). El porcentaje es el real cuando el
// servidor lo informa (GET /api/progress: guardar el mapa, registrar en escenarios, adecuar…) y, si no, una estimación
// por tiempo. Aparece tras 250 ms para no parpadear en lo rápido.
(() => {
  const EN = () => { try { return localStorage.getItem('mh-lang') === 'en'; } catch (e) { return false; } };
  const T = s => (window.mhTr ? window.mhTr(s) : s);
  const f0 = window.fetch.bind(window);
  let n = 0, timer = null, poll = null, bar = null, t0 = 0, shown = 0, local = '', server = null, serverCalls = 0;
  const css = `#mhBusy{position:fixed;left:0;right:0;top:0;z-index:100000;pointer-events:none;display:none;text-align:center}
    #mhBusy .track{height:6px;background:rgba(127,127,127,.25)}
    #mhBusy .fill{height:100%;width:0;background:#f97316;transition:width .25s ease}
    #mhBusy .txt{display:inline-block;margin:6px 10px;padding:4px 12px;border-radius:12px;font:12px system-ui,sans-serif;
      background:#f97316;color:#fff;box-shadow:0 1px 4px rgba(0,0,0,.3);max-width:80vw;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    #mhBusy .pct{font-weight:700;margin-left:6px}`;
  function el() {
    if (bar) return bar;
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    bar = document.createElement('div'); bar.id = 'mhBusy';
    bar.innerHTML = '<div class="track"><div class="fill"></div></div><span class="txt"><span class="lbl"></span><span class="pct"></span></span>';
    document.body.appendChild(bar); return bar;
  }
  function render() {
    const t = (Date.now() - t0) / 1000;
    let pct = 95 * (1 - Math.exp(-t / 4)), label = local;   // estimación si el servidor no informa
    if (server && server.active && server.real) { pct = server.pct; if (server.label) label = T(server.label); }
    shown = Math.max(shown, Math.min(99, Math.round(pct)));
    const b = el();
    b.querySelector('.fill').style.width = shown + '%';
    b.querySelector('.lbl').textContent = (EN() ? 'Now loading… ' : 'Cargando… ') + (label || '');   // sin texto propio: solo «Cargando…» (muchas peticiones no cambian nada)
    b.querySelector('.pct').textContent = shown + ' %';
  }
  async function ask() {
    if (!serverCalls) return;
    try { server = await (await f0('/api/progress')).json(); } catch (e) { server = null; }
    if (n) render();
  }
  function start(text, isServer) {
    if (text) local = T(text);
    if (isServer) serverCalls++;
    if (n++ === 0) {
      t0 = Date.now(); shown = 0; server = null;
      timer = setTimeout(() => { el().style.display = 'block'; render(); poll = setInterval(() => { render(); ask(); }, 300); }, 250);
    } else if (bar && bar.style.display === 'block') render();
  }
  function stop(isServer) {
    if (isServer) serverCalls = Math.max(0, serverCalls - 1);
    if (--n > 0) return;
    n = 0; clearTimeout(timer); clearInterval(poll); local = '';
    if (bar && bar.style.display === 'block') {   // llega al 100 % y se va
      shown = 100; bar.querySelector('.fill').style.width = '100%'; bar.querySelector('.pct').textContent = '100 %';
      setTimeout(() => { if (!n) bar.style.display = 'none'; }, 300);
    }
  }
  const run = async (p, text, isServer) => { start(text, isServer); try { return await (typeof p === 'function' ? p() : p); } finally { stop(isServer); } };
  window.mhBusy = (p, text) => run(p, text, false);
  window.fetch = (url, opt) => {
    const m = ((opt && opt.method) || 'GET').toUpperCase();
    if (m === 'GET' || String(url).includes('/api/lang')) return f0(url, opt);
    return run(f0(url, opt), '', true);
  };
  // en MHEditor.exe (pywebview) los enlaces a otro editor se abren en la misma ventana, no en el navegador del sistema
  document.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('a[target="_blank"]');
    if (!a || !window.pywebview || e.defaultPrevented) return;
    let u; try { u = new URL(a.href, location.href); } catch (x) { return; }
    if (u.origin !== location.origin) return;
    e.preventDefault(); location.href = u.href;
  }, true);
})();
