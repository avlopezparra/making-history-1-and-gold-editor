// Imágenes en el editor de escenarios (se carga al final de escenario.html; envuelve renderList y renderObj):
// - Naciones: bandera junto a cada país (también en la capa «Propiedad» del mapa) y marcas «sin bandera» / «sin color»;
//   en el país, bandera y escarapela (exportar / importar, también desde una URL) y la portada y el retrato del líder.
// - Global Data › Scenario: Title.tga (desde imagen o desde el nombre), Button.tga y ButtonOver.tga (brillo +8 automático).
// - Ideologías, terrenos, productores (recurso), unidades, productos e investigación: sus iconos en todas las medidas;
//   si el escenario no tiene versión propia se muestra la del juego y al importar se crea la propia.
// - Botón «Iconos e interfaz»: catálogo de todos los tipos de icono y explorador de las imágenes de la UI del juego.
// Rutas /api/img/* de editor_server.py (image_tools.py, image_assets.py). Escribe solo tras confirmar.
(() => {
  'use strict';
  const IMG = { scen: null, icons: null, nations: null, bust: Date.now() };
  const ICON_TABS = { units: 'unit', outputs: 'output', research: 'research' };
  const FLIPPED = new Set(['3DFlag.tga', 'decal.tga']);       // el juego los guarda invertidos verticalmente
  const enc = encodeURIComponent;
  const kebab = s => String(s).replace(/([a-z0-9])([A-Z])/g, '$1-$2').replace(/([A-Z])([A-Z][a-z])/g, '$1-$2').replace(/[^A-Za-z0-9-]+/g, '-').replace(/^-|-$/g, '').toLowerCase();
  const readFile = f => new Promise((ok, ko) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = ko; r.readAsDataURL(f); });
  const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(r => r.json());
  const getJ = u => fetch(u).then(r => r.json());
  const fname = rel => String(rel || '').split(/[\\/]/).pop();
  const t = x => (window.mhTr ? window.mhTr(x) : x);      // textos con datos: se traducen por trozos

  const st = document.createElement('style');
  st.textContent = `img.mhico { width:20px; height:14px; object-fit:contain; vertical-align:-2px; margin-right:6px; image-rendering:auto; }
    img.mhico.sq { width:22px; height:22px; vertical-align:-6px; background:#e7e2d6; border-radius:3px; }
    .mhbad { font-size:10.5px; padding:0 5px; margin-left:6px; border-radius:8px; border:1px solid var(--err); color:var(--err); white-space:nowrap; }
    .mhchk { background-color:#f2f2f2; background-image:linear-gradient(45deg,#d9d9d9 25%,transparent 25%,transparent 75%,#d9d9d9 75%),linear-gradient(45deg,#d9d9d9 25%,transparent 25%,transparent 75%,#d9d9d9 75%); background-size:12px 12px; background-position:0 0,6px 6px; }
    .mhflip { transform:scaleY(-1); }
    .mhimgs { display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; margin:6px 0; }
    .mhimgs figure { margin:0; text-align:center; font-size:11.5px; color:var(--muted); max-width:100%; }
    .mhimgs img { display:block; image-rendering:pixelated; border:1px solid var(--line); max-width:100%; margin:0 auto 2px; }
    .mhown { color:var(--ok); } .mhdef { color:var(--muted); } .mhmiss { color:var(--err); }
    #mhImgDlg .cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:8px; margin-top:8px; }
    #mhImgDlg .card { border:1px solid var(--line); border-radius:6px; padding:4px 6px; font-size:12px; word-break:break-all; }
    #mhImgDlg .card img { image-rendering:pixelated; display:block; margin-top:3px; max-width:100%; }
    #mhCatDlg { width:min(1100px, 96vw); }
    #mhCatDlg .cols { display:grid; grid-template-columns:minmax(220px, 300px) 1fr; gap:12px; min-height:60vh; }
    #mhCatDlg .lst { overflow:auto; max-height:68vh; border:1px solid var(--line); border-radius:6px; padding:4px; }
    #mhCatDlg .lst h4 { margin:8px 4px 2px; font-size:12.5px; color:var(--muted); }
    #mhCatDlg .lst div.it { display:flex; gap:6px; align-items:center; padding:2px 4px; border-radius:4px; cursor:pointer; font-size:13px; }
    #mhCatDlg .lst div.it:hover, #mhCatDlg .lst div.it.on { background:var(--sel); }
    #mhCatDlg .lst div.it img { width:22px; height:22px; object-fit:contain; background:#e7e2d6; border-radius:3px; }`;
  document.head.appendChild(st);

  async function icons() {
    if (!S.scen) return null;
    if (IMG.scen !== S.scen || !IMG.icons) { IMG.scen = S.scen; IMG.icons = await getJ('/api/img/icons?scen=' + enc(S.scen)).catch(() => null); }
    return IMG.icons;
  }
  async function nations() {
    if (!S.scen) return null;
    if (IMG.nscen !== S.scen || !IMG.nations) { IMG.nscen = S.scen; IMG.nations = await getJ('/api/img/nations?scen=' + enc(S.scen)).catch(() => null); }
    return IMG.nations;
  }
  const iconOf = (kind, name) => { const d = IMG.icons && IMG.icons[kind]; return d ? d.items.find(x => x.name === name) : null; };
  const rawUrl = rel => `/api/img/raw?rel=${enc(rel)}&max=256&t=${IMG.bust}`;
  const flagUrl = c => `/api/img/flag?scen=${enc(S.scen)}&country=${enc(c)}&t=${IMG.bust}`;
  const dlLink = (href, file, label) => `<a class="btn" href="${href}" download="${esc(file)}">${esc(label)}</a>`;
  const exportUrl = (kind, name, group) => `/api/img/asset/export?scen=${enc(S.scen)}&kind=${kind}&name=${enc(name)}${group ? '&group=' + group : ''}&t=${Date.now()}`;
  function refreshAll() { IMG.bust = Date.now(); IMG.icons = IMG.nations = null; if (S.obj) renderObj(S.obj); document.querySelectorAll('#list img.mhico, #list .mhbad').forEach(i => i.remove()); decorate(); }

  // ---------------------------------------------------------------- iconos y marcas en la lista
  function addImg(td, src, sq) {
    const img = document.createElement('img'); img.className = 'mhico' + (sq ? ' sq' : ''); img.alt = ''; img.src = src;
    img.onerror = () => { if (!img.dataset.retry) { img.dataset.retry = 1; setTimeout(() => { img.src = src + '&r=1'; }, 400); } else img.remove(); };   // un fallo puntual no lo borra
    td.prepend(img);
  }
  async function decorate() {
    if (!S.scen) return;
    const layer = S.mode === 'layer' && ['owner', 'historic'].includes((document.getElementById('layer') || {}).value);
    const tab = S.tab, kind = S.mode === 'tab' ? ICON_TABS[tab] : null;
    const isNations = (S.mode === 'tab' && tab === 'nations') || layer;
    if (!isNations && !kind) return;
    if (kind) await icons();
    const ns = isNations ? await nations() : null;
    document.querySelectorAll('#list tbody tr[data-id]').forEach(tr => {
      const row = S.rows.find(r => String(r.id) === tr.dataset.id); const td = tr.firstElementChild;
      if (!row || !td || td.querySelector('img.mhico, .mhbad')) return;
      const name = row.cols[0];
      if (isNations) {
        const s = ns && ns[name];
        if (!s || s.flag) addImg(td, flagUrl(name), false);
        const bad = [];
        if (s && !s.flag) bad.push('sin bandera');
        if (!s || !s.color) bad.push('sin color');
        if (bad.length) { const b = document.createElement('span'); b.className = 'mhbad'; b.textContent = bad.join(' · ');
          b.title = !s ? 'No tiene Player en gamestate.xml (sin color ni bandera asignada)' : 'Falta: ' + bad.join(', '); td.appendChild(b); }
      } else { const it = iconOf(kind, name); if (it && it.rel) addImg(td, rawUrl(it.rel) + '&crop=1', true); }
    });
  }
  const _renderList = renderList;
  renderList = function () { const r = _renderList.apply(this, arguments); decorate(); return r; };

  // ---------------------------------------------------------------- diálogo de importación (archivo o URL)
  function dialog() {
    let dl = document.getElementById('mhImgDlg');
    if (dl) return dl;
    dl = document.createElement('dialog'); dl.id = 'mhImgDlg';
    dl.innerHTML = `<header><b id="mhTitle"></b><span class="muted" id="mhSub"></span><button class="btn small" style="margin-left:auto" id="mhClose">Cerrar</button></header>
      <div class="body"><div class="row"><input type="file" id="mhFile" accept="image/*"></div>
      <div class="row"><input id="mhUrl" type="url" placeholder="…o pega la URL de una imagen (PNG, JPG)" style="flex:1;min-width:220px"><button class="btn small" id="mhUrlGo">Desde URL</button></div>
      <div class="grid" id="mhOpts"></div>
      <div class="row" style="margin-top:6px"><button class="btn" id="mhPrev" disabled>Vista previa</button><button class="btn primary" id="mhWrite" disabled>Escribir…</button>
      <span class="muted" id="mhWait"></span></div><div id="mhNote"></div><div class="cards" id="mhCards"></div></div>`;
    document.body.appendChild(dl);
    dl.querySelector('#mhClose').onclick = () => dl.close();
    return dl;
  }
  // cfg: {title, sub, opts(html), previewUrl, writeUrl, body(img, q), extra(), confirm(n), done(), allowNoImage}
  function openImport(cfg) {
    const dl = dialog(), q = s => dl.querySelector(s);
    let img = null, last = null;
    q('#mhTitle').textContent = cfg.title; q('#mhSub').textContent = cfg.sub || '';
    q('#mhOpts').innerHTML = cfg.opts || ''; q('#mhCards').innerHTML = ''; q('#mhNote').innerHTML = ''; q('#mhFile').value = ''; q('#mhUrl').value = '';
    q('#mhPrev').disabled = !cfg.allowNoImage; q('#mhWrite').disabled = true;
    const note = (t, err) => { q('#mhNote').innerHTML = `<div class="note ${err ? 'err' : ''}" style="white-space:pre-wrap">${esc(t)}</div>`; };
    const got = data => { img = data; q('#mhPrev').disabled = !img && !cfg.allowNoImage; q('#mhWrite').disabled = true; if (img) q('#mhPrev').click(); };
    q('#mhFile').onchange = async () => { const f = q('#mhFile').files[0]; got(f ? await readFile(f) : null); };
    q('#mhUrlGo').onclick = async () => {
      const url = q('#mhUrl').value.trim(); if (!url) return;
      q('#mhWait').textContent = 'descargando…';
      const r = await post('/api/img/fetch', { url }).catch(e => ({ error: String(e) })); q('#mhWait').textContent = '';
      if (r.error) return note(r.error, true);
      q('#mhFile').value = ''; got(r.img);
    };
    q('#mhOpts').onchange = q('#mhOpts').oninput = () => { q('#mhWrite').disabled = true; };
    q('#mhPrev').onclick = async () => {
      q('#mhWait').textContent = 'generando…';
      const r = await post(cfg.previewUrl, cfg.body(img, q)).catch(e => ({ error: String(e) })); q('#mhWait').textContent = '';
      if (r.error) return note(r.error, true);
      last = r; q('#mhNote').innerHTML = '';
      q('#mhCards').innerHTML = r.files.map(f => { const k = Math.max(1, Math.min(3, Math.floor(140 / f.w))), flip = FLIPPED.has(f.file);
        return `<div class="card"><b>${esc(f.file)}</b><div class="muted">${f.w}×${f.h} · ${esc(f.fmt)}${flip ? ' · se muestra al derecho (el archivo va invertido)' : ''}</div>
          <img class="mhchk${flip ? ' mhflip' : ''}" src="${f.png}" style="width:${f.w * k}px"></div>`; }).join('');
      q('#mhWrite').disabled = false;
    };
    q('#mhWrite').onclick = async () => {
      if (!last || !confirm(cfg.confirm(last.files.length))) return;
      q('#mhWait').textContent = 'escribiendo…';
      const r = await post(cfg.writeUrl, Object.assign(cfg.body(img, q), cfg.extra())).catch(e => ({ error: String(e) }));
      q('#mhWait').textContent = '';
      if (r.error) return note(r.error, true);
      note(`${t('Escritos')}: ${r.written.length}${r.notes && r.notes.length ? '\n' + r.notes.map(t).join('\n') : ''}`);
      q('#mhWrite').disabled = true; IMG.bust = Date.now(); IMG.icons = IMG.nations = null; cfg.done && cfg.done();
    };
    dl.showModal();
  }
  const confirmText = (n, where) => `¿Escribir ${n} archivo(s) en ${where} de «${S.scen}»?\n\nLos archivos del juego (carpeta de contenido) no se tocan: se crea o reemplaza la versión propia del escenario.`;

  // ---------------------------------------------------------------- país: bandera y escarapela
  const FIT_OPTS = `<label>Proporción</label><select id="mhFit">
      <option value="centro">recortar al centro (hasta 2:1)</option>
      <option value="bordes">estirar las columnas de los extremos hasta rellenar</option>
      <option value="izquierda">pegada a la izquierda; rellenar desde la columna derecha (p. ej. Chile)</option>
      <option value="estirar">deformar hasta 2:1</option></select>
    <label>Huecos cuadrados</label><select id="mhCrop"><option value="estirar">estirar la bandera (como la mayoría)</option><option value="asta">recortar desde el asta</option><option value="centro">recortar al centro</option></select>`;
  async function flagSection(d, host) {
    const name = d.label;
    const r = await getJ(`/api/img/country?scen=${enc(S.scen)}&name=${enc(name)}&resolve=1`).catch(() => ({ files: [] }));
    if (!S.obj || S.obj.id !== d.id) return;
    const folder = r.folder || name, files = {}; (r.files || []).forEach(f => files[f.file] = f);
    const show = [['flag-256-128.bmp', 'bandera', 128], ['decal-64-64.tga', 'escarapela', 64], ['flag-16-16.tga', '16×16', 32], ['3DFlag.tga', '3D (se guarda invertida)', 64]];
    const figs = show.filter(([f]) => files[f]).map(([f, lab, w]) =>
      `<figure><img class="mhchk${FLIPPED.has(f) ? ' mhflip' : ''}" src="${rawUrl(files[f].rel)}" style="width:${w}px">${esc(lab)}</figure>`).join('');
    const sec = document.createElement('div'); sec.className = 'sec';
    sec.innerHTML = `<h3>Bandera y escarapela</h3><div class="muted"><span>Carpeta</span> <code>ui/art/2D/countries/${esc(folder)}/</code> (strFlagName) · <b>${Object.keys(files).length}</b> <span>imágenes</span></div>
      ${figs ? `<div class="mhimgs">${figs}</div>` : '<div class="note err">Este país no tiene carpeta de banderas: el juego mostrará huecos. Importa una bandera.</div>'}
      <div class="row"><button class="btn" data-mh="flag">Importar bandera…</button><button class="btn" data-mh="decal">Importar escarapela…</button>
      ${files['flag-256-128.bmp'] ? dlLink(rawUrl(files['flag-256-128.bmp'].rel).replace('&max=256', ''), folder + ' - bandera.png', 'Exportar bandera') : ''}
      ${files['decal-64-64.tga'] ? dlLink(rawUrl(files['decal-64-64.tga'].rel), folder + ' - escarapela.png', 'Exportar escarapela') : ''}</div>`;
    host.appendChild(sec);
    sec.querySelector('[data-mh=flag]').onclick = () => openImport({
      title: 'Importar bandera · ' + name, sub: ` → ${folder}/ (13 archivos; la escarapela no cambia)`, opts: FIT_OPTS,
      previewUrl: '/api/img/flag/preview', writeUrl: '/api/img/flag/write',
      body: (img, q) => ({ flag: img, only: 'flag', fit: q('#mhFit').value, crop: q('#mhCrop').value }),
      extra: () => ({ scen: S.scen, country: folder }),
      confirm: n => confirmText(n, `ui\\art\\2D\\countries\\${folder}\\`), done: refreshAll,
    });
    sec.querySelector('[data-mh=decal]').onclick = () => openImport({
      title: 'Importar escarapela · ' + name, sub: ` → ${folder}/ (decal, decal-64-64, -bw, -bw-over, decal-42-42, 1919DecalWShadow)`,
      opts: `<label>Fondo</label><label style="color:inherit"><input type="checkbox" id="mhBg" checked> quitar el fondo liso (si la imagen no tiene transparencia)</label>`,
      previewUrl: '/api/img/flag/preview', writeUrl: '/api/img/flag/write',
      body: (img, q) => ({ decal: img, only: 'decal', removebg: q('#mhBg').checked }),
      extra: () => ({ scen: S.scen, country: folder }),
      confirm: n => confirmText(n, `ui\\art\\2D\\countries\\${folder}\\`), done: refreshAll,
    });
  }

  // ---------------------------------------------------------------- cualquier imagen con sus variantes
  // kind: nation | scenario | ideology | resource | terrain | production | uniticon | ui
  async function assetSection(host, kind, name, opts = {}) {
    const inf = await getJ(`/api/img/asset?scen=${enc(S.scen)}&kind=${kind}&name=${enc(name)}`).catch(e => ({ error: String(e) }));
    if (opts.guard && !opts.guard()) return;
    const sec = document.createElement('div'); sec.className = 'sec';
    if (inf.error) { sec.innerHTML = `<h3>${esc(opts.title || 'Imagen')}</h3><div class="note err">${esc(inf.error)}</div>`; host.appendChild(sec); return; }
    let h = `<h3>${esc(opts.title || inf.label)}${kind === 'scenario' ? '' : ` · <span class="muted">${esc(name)}</span>`}</h3>`;
    if (opts.note) h += `<div class="muted">${esc(opts.note)}</div>`;
    if (inf.reference) h += '<div class="note">No hay imágenes para esta clave ni en el escenario ni en el juego: al importar se crean con las medidas de las de referencia.</div>';
    for (const g of inf.groups) {
      const vs = g.variants, own = vs.filter(v => v.own).length, any = vs.some(v => v.src);
      const status = own === vs.length && own ? '<span class="mhown">versión propia del escenario</span>'
        : own ? `<span class="mhown"><b>${own}/${vs.length}</b> <span>propias</span></span>` : any ? '<span class="mhdef">sin versión propia en el escenario: se muestra la del juego</span>'
          : '<span class="mhmiss">sin imagen</span>';
      h += `<div style="margin-top:6px"><b style="font-size:13px">${esc(g.title)}</b> · ${status}${g.note ? `<div class="muted">${esc(g.note)}</div>` : ''}<div class="mhimgs">` +
        vs.map(v => { const k = v.w ? Math.max(0.25, Math.min(2, 96 / Math.max(v.w, v.h))) : 1;
          return `<figure title="${esc(v.rel)}">${v.src ? `<img class="mhchk" src="${rawUrl(v.src).replace('&max=256', '&max=512')}" style="width:${Math.round(v.w * k)}px">` : `<div class="mhchk" style="width:48px;height:48px;border:1px dashed var(--line)"></div>`}
            ${esc(v.file)}${v.w ? ` <span class="muted">${v.w}×${v.h}</span>` : ''}<br>${v.own ? '<span class="mhown">propia</span>' : v.src ? '<span class="mhdef">del juego</span>' : v.generic ? '<span class="mhdef">usa la genérica</span>' : '<span class="mhmiss">falta</span>'}</figure>`; }).join('') +
        `</div><div class="row">${any ? dlLink(exportUrl(kind, name, g.key), `${kind}-${name || S.scen}-${g.key}.png`, 'Exportar') : ''}<button class="btn" data-g="${g.key}">Importar…</button></div></div>`;
    }
    sec.innerHTML = h; host.appendChild(sec);
    sec.querySelectorAll('[data-g]').forEach(b => b.onclick = () => importAsset(inf, kind, name, b.dataset.g, opts));
  }
  function importAsset(inf, kind, name, group, opts) {
    const g = inf.groups.find(x => x.key === group);
    let extraOpts = `<label>Fondo</label><label style="color:inherit"><input type="checkbox" id="mhBg"> quitar el fondo liso (iconos)</label>`;
    let body = (img, q) => ({ img, kind, name, group, removebg: q('#mhBg').checked });
    let allowNoImage = false;
    if (kind === 'scenario' && group === 'title') {
      allowNoImage = true;
      extraOpts = `<label>O desde el nombre</label><input id="mhText" value="${esc(inf.display_name || S.scen)}">
        <label>Fuente</label><select id="mhFont"><option value="georgiab.ttf">Georgia negrita</option><option value="timesbd.ttf">Times negrita</option><option value="impact.ttf">Impact</option><option value="arialbd.ttf">Arial negrita</option><option value="trebucbd.ttf">Trebuchet negrita</option></select>
        <label>Color</label><input id="mhColor" type="color" value="#ffffff">
        <label>Usar</label><select id="mhSrc"><option value="text">el nombre (texto)</option><option value="img">la imagen elegida</option></select>`;
      body = (img, q) => { const useText = q('#mhSrc').value === 'text' || !img;
        return { img, kind, name, group, text: useText ? q('#mhText').value : '', font: q('#mhFont').value, color: q('#mhColor').value }; };
    }
    if (kind === 'scenario' && group === 'button') {
      extraOpts += `<label>Cursor encima</label><label style="color:inherit"><input type="checkbox" id="mhOver" checked> generar ButtonOver.tga con brillo +<input id="mhBright" type="number" value="8" min="1" max="50" style="width:50px"></label>`;
      body = (img, q) => ({ img, kind, name, group, removebg: q('#mhBg').checked, auto_over: q('#mhOver').checked, bright: +q('#mhBright').value || 8 });
    }
    openImport({
      title: `Importar · ${g ? g.title : group}`, sub: ` · ${name || S.scen}`, opts: extraOpts, allowNoImage,
      previewUrl: '/api/img/asset/preview', writeUrl: '/api/img/asset/write', body,
      extra: () => ({ scen: S.scen }),
      confirm: n => confirmText(n, kind === 'scenario' ? 'la carpeta' : 'ui\\art\\'),
      done: () => { opts.done ? opts.done() : refreshAll(); },
    });
  }

  // ---------------------------------------------------------------- unidad / producto / investigación: icono de tabla
  const kindOf = t => t === 'UnitTemplate' ? 'unit' : /^FactoryOutput/.test(t) ? 'output' : /^ResearchProj(?!ect)/.test(t) ? 'research' : null;
  async function iconSection(d, kind, host) {
    await icons();
    if (!S.obj || S.obj.id !== d.id) return;
    const prop = n => (d.props.find(p => p.name === n) || {}).value;
    const name = prop('strName') || d.label;
    const it = iconOf(kind, name);
    const key = kind === 'research' ? (prop('strIconName') || name) : name;
    const cur = it && it.file ? fname(it.file).replace(/\.tga$/i, '') : '';
    const where = kind === 'research' ? 'MediaPack.xml (Research_Project_Icon) · imagen grande de investigación'
      : kind === 'unit' ? 'UnitTemplateIconTable.xml · 4 medidas (64, 46, 36, 26)' : 'FactoryOutputIconTable.xml · 4 medidas (64, 46, 36, 26)';
    const own = it && it.rel && !it.rel.startsWith('@ui/') && !it.via;
    const sec = document.createElement('div'); sec.className = 'sec';
    sec.innerHTML = `<h3>Icono</h3><div class="muted">${esc(where)}${kind === 'research' ? ` · strIconName «${esc(key)}»` : ''}</div>
      ${it && it.rel ? `<div class="mhimgs"><figure><img class="mhchk" src="${rawUrl(it.rel)}" style="width:${kind === 'research' ? 128 : 64}px">${esc(fname(it.rel))}<br>${own ? '<span class="mhown">propia</span>' : it.via ? '<span class="mhdef">la de la unidad</span>' : '<span class="mhdef">del juego: sin versión propia en el escenario</span>'}</figure></div>`
        : `<div class="note err">${it && it.registered ? 'Registrado pero falta el archivo.' : 'Sin icono: el juego usará uno genérico o un hueco.'}</div>`}
      <div class="row">${it && it.rel ? dlLink(rawUrl(it.rel).replace('&max=256', ''), (cur || kebab(key)) + '.png', 'Exportar') : ''}<button class="btn" data-mh="icon">Importar…</button>
      ${kind === 'unit' ? '<button class="btn" data-mh="research">Imagen de investigación…</button>' : ''}</div>`;
    host.appendChild(sec);
    const open = (k, title) => openImport({
      title, sub: ` · ${S.scen}`,
      opts: `<label>Archivo</label><input id="mhBase" value="${esc(cur && own ? cur : kebab(key))}">
        <label>Fondo</label><label style="color:inherit"><input type="checkbox" id="mhBg"> quitar el fondo liso</label>` +
        (k === 'research' ? `<label>Medida</label><select id="mhSize"><option>256x256</option><option>128x256</option><option>512x256</option></select>`
          : `<label>Margen (px)</label><input id="mhPad" type="number" value="2" min="0" max="20">`) +
        `<label>Registrar</label><label style="color:inherit"><input type="checkbox" id="mhReg" checked> añadir o actualizar la entrada «${esc(k === 'research' ? key : name)}» en la tabla</label>`,
      previewUrl: '/api/img/icon/preview', writeUrl: '/api/img/icon/write',
      body: (img, q) => ({ img, kind: k, filebase: q('#mhBase').value, removebg: q('#mhBg').checked, pad: q('#mhPad') ? +q('#mhPad').value : 0,
        research_size: q('#mhSize') ? q('#mhSize').value : '256x256', register: q('#mhReg').checked }),
      extra: () => ({ scen: S.scen, name: k === 'research' ? key : name }),
      confirm: n => confirmText(n, 'ui\\art\\2D\\'), done: refreshAll,
    });
    sec.querySelector('[data-mh=icon]').onclick = () => open(kind, `Importar icono · ${name}`);
    const rb = sec.querySelector('[data-mh=research]');
    if (rb) rb.onclick = () => open('research', 'Imagen de investigación · ' + name);
  }

  // ---------------------------------------------------------------- tarjetas
  const _renderObj = renderObj;
  renderObj = function (d) {
    const r = _renderObj.apply(this, arguments);
    try {
      if (!S.scen || !d) return r;
      const host = document.getElementById('right'), guard = () => S.obj && S.obj.id === d.id;
      const prop = n => (d.props.find(p => p.name === n) || {}).value;
      if (d.type === 'MECountry') flagSection(d, host).then(() => guard() && assetSection(host, 'nation', d.label, { title: 'Portada y retrato del líder', guard }));
      else if (d.type === 'Scenario') assetSection(host, 'scenario', '', { title: 'Título y botones del escenario', guard,
        note: 'Title.tga, Button.tga y ButtonOver.tga de la carpeta del escenario (lista de escenarios del juego).' });
      else if (d.type === 'GovTypeTemplate') assetSection(host, 'ideology', prop('strIconName') || d.label, { title: 'Iconos de la ideología', guard });
      else if (d.type === 'TerrainType' && prop('strTerrain')) assetSection(host, 'terrain', prop('strTerrain'), { title: 'Imágenes del terreno', guard });
      else if (d.type === 'Producer' && prop('strResource')) assetSection(host, 'resource', prop('strResource'), { title: 'Iconos del recurso', guard,
        note: 'Compartidos por todos los productores de este recurso.' });
      const k = kindOf(d.type);
      if (k) iconSection(d, k, host).then(() => {
        if (!guard()) return;
        const ic = prop('strIconName');
        if (ic && k === 'unit') { const n = ((IMG.icons || {}).unit || { items: [] }).items.filter(x => x.icon === ic).length;
          assetSection(host, 'uniticon', ic, { title: 'Icono en la ventana de unidades', guard, note: `strIconName «${ic}» · ${t('unidades que lo comparten')}: ${n}` }); }
        if (ic && k === 'output') assetSection(host, 'production', ic, { title: 'Icono en el panel de industria', guard, note: `strIconName «${ic}» · ${t('compartido por los productos con ese icono')}` });
      });
    } catch (e) { console.error(e); }
    return r;
  };

  // ---------------------------------------------------------------- catálogo de iconos e interfaz
  function catDialog() {
    let dl = document.getElementById('mhCatDlg');
    if (dl) return dl;
    dl = document.createElement('dialog'); dl.id = 'mhCatDlg';
    dl.innerHTML = `<header><b>Iconos e interfaz</b><span class="muted" id="mhCatScen"></span>
      <button class="btn small" data-ct="icons">Iconos del juego</button><button class="btn small" data-ct="ui">Interfaz (UI)</button>
      <button class="btn small" style="margin-left:auto" id="mhCatClose">Cerrar</button></header>
      <div class="body"><div class="cols"><div class="lst" id="mhCatList"></div><div id="mhCatPanel"><p class="muted">Elige un elemento de la izquierda.</p></div></div></div>`;
    document.body.appendChild(dl);
    dl.querySelector('#mhCatClose').onclick = () => dl.close();
    dl.querySelectorAll('[data-ct]').forEach(b => b.onclick = () => (b.dataset.ct === 'icons' ? catIcons() : catUI('')));
    return dl;
  }
  async function showAsset(kind, name, title, el) {
    document.querySelectorAll('#mhCatList .it').forEach(x => x.classList.toggle('on', x === el));
    const p = document.getElementById('mhCatPanel'); p.innerHTML = '';
    await assetSection(p, kind, name, { title, done: () => showAsset(kind, name, title, el) });
  }
  async function catIcons() {
    const L = document.getElementById('mhCatList'); L.innerHTML = '<p class="muted">Cargando…</p>';
    const r = await getJ('/api/img/catalog?scen=' + enc(S.scen));
    L.innerHTML = '<h4>Escenario</h4><div class="it" data-k="scenario" data-n="">Título y botones</div>' + r.groups.map(g => `<h4>${esc(g.title)}</h4>` + g.items.map(i =>
      `<div class="it" data-k="${g.kind}" data-n="${esc(i.name)}">${i.thumb ? `<img src="${rawUrl(i.thumb)}&crop=1">` : '<img alt="">'}<span>${esc(i.name)}</span>
        <span class="muted" style="margin-left:auto">${i.own ? `<span class="mhown"><b>${i.own}/${i.n}</b> <span>propias</span></span>` : i.n ? `<b>${i.n}</b> <span>del juego</span>` : '<span>sin imagen</span>'}</span></div>`).join('')).join('') +
      '<p class="muted" style="margin:8px 4px">Banderas y portadas: en cada nación. Unidades, productos e investigación (tablas de iconos): en sus pestañas.</p>';
    L.querySelectorAll('.it').forEach(el => el.onclick = () => showAsset(el.dataset.k, el.dataset.n, el.dataset.k === 'scenario' ? 'Título y botones del escenario' : null, el));
  }
  async function catUI(rel) {
    const L = document.getElementById('mhCatList'); L.innerHTML = '<p class="muted">Cargando…</p>';
    const [r, own] = await Promise.all([getJ(`/api/img/ui/list?scen=${enc(S.scen)}&rel=${enc(rel)}`), rel ? null : getJ('/api/img/ui/own?scen=' + enc(S.scen))]);
    const up = r.rel.includes('/') && r.rel !== 'art/2D' ? r.rel.split('/').slice(0, -1).join('/') : null;
    L.innerHTML = (own ? `<h4>Personalizadas en este escenario (${own.files.length})</h4>` + own.files.map(f =>
      `<div class="it" data-f="${esc(f.rel)}"><img src="${rawUrl(S.scen + '/ui/' + f.rel)}&crop=1"><span title="${esc(f.rel)}">${esc(f.rel.replace(/^art\/2D\//, ''))}</span>${f.default ? '' : '<span class="muted" style="margin-left:auto">nueva</span>'}</div>`).join('') : '') +
      `<h4>${esc(r.rel)}</h4>` + (up ? `<div class="it" data-d="${esc(up)}">⬑ ..</div>` : '') +
      r.dirs.map(d => `<div class="it" data-d="${esc(r.rel + '/' + d.name)}">📁 <span>${esc(d.name)}</span>${d.own ? `<span class="mhown" style="margin-left:auto">${d.own} propias</span>` : ''}</div>`).join('') +
      r.files.map(f => `<div class="it" data-f="${esc(r.rel + '/' + f.name)}"><span>${esc(f.name)}</span><span style="margin-left:auto">${f.own ? '<span class="mhown">propia</span>' : '<span class="muted">del juego</span>'}</span></div>`).join('');
    L.querySelectorAll('[data-d]').forEach(el => el.onclick = () => catUI(el.dataset.d));
    L.querySelectorAll('[data-f]').forEach(el => el.onclick = () => showAsset('ui', el.dataset.f, fname(el.dataset.f), el));
  }
  function addToolbarButton() {
    const bar = document.getElementById('bar'); if (!bar || document.getElementById('mhCatBtn')) return;
    const b = document.createElement('button'); b.id = 'mhCatBtn'; b.type = 'button'; b.textContent = '🖼 Iconos e interfaz';
    b.title = 'Todos los iconos del juego (ideologías, recursos, terrenos, producción, unidades) y las imágenes de la interfaz, con exportar / importar';
    b.onclick = () => { if (!S.scen) return alert('Abre primero un escenario.'); const dl = catDialog(); dl.querySelector('#mhCatScen').textContent = ' · ' + S.scen; dl.showModal(); catIcons(); };
    const ref = document.getElementById('openfile'); ref && ref.parentNode === bar ? ref.after(b) : bar.appendChild(b);
  }
  addToolbarButton();
})();
