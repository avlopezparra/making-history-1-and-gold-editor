// Idioma de los editores (español / inglés). Traduce los textos de la interfaz al vuelo:
// textos fijos, títulos (tooltips), placeholders y lo que se va añadiendo a la página (MutationObserver).
// Los textos que no estén en el diccionario se quedan en español.
(() => {
  const EN = {
    'Editor de escenarios': 'Scenario editor', 'Editor de escenarios · Making History': 'Scenario editor · Making History',
    'Editor de regiones · Making History': 'Region editor · Making History', 'Imágenes del escenario · Making History': 'Scenario images · Making History',
    'Editor de escenarios (como ed.exe)': 'Scenario editor (like ed.exe)', 'Editor de escenarios ↗': 'Scenario editor ↗', 'Editor de mapa ↗': 'Map editor ↗',
    'Abrir escenario…': 'Open scenario…', 'Abrir archivo…': 'Open file…', 'Abrir archivo': 'Open file', 'Guardar escenario': 'Save scenario',
    'Revertir': 'Revert', 'Validar': 'Validate', 'Validación': 'Validation', 'Nueva guerra…': 'New war…', 'Convertir…': 'Convert…', 'Convertir': 'Convert',
    'Convertir escenario': 'Convert scenario', 'Inclinar mapa 3D': 'Tilt 3D map', 'Partisans': 'Partisans', 'regionpack': 'regionpack',
    'Editar objeto': 'Edit object', 'Mapa': 'Map', 'Filtrar…': 'Filter…', 'Aplicar': 'Apply', 'Revertir objeto': 'Revert object',
    'Duplicar': 'Duplicate', 'Quitar': 'Remove', 'Abrir': 'Open', 'Cerrar': 'Close', 'Cancelar': 'Cancel', 'Aceptar': 'OK', 'Guardar': 'Save',
    'Contenido': 'Contents', 'Ubicación (región)': 'Location (region)', '↳ texto visible': '↳ visible text', '(sin texto)': '(no text)',
    'todo guardado': 'all saved', 'Capa': 'Layer', 'clic modifica': 'click edits', 'Ciudades': 'Cities', 'Recursos': 'Resources',
    'Ejércitos': 'Armies', 'Aviación': 'Air forces', 'Flotas': 'Fleets', 'Propiedad (nación)': 'Ownership (nation)',
    'Regiones históricas': 'Historic regions', 'Etnia (cultura)': 'Ethnicity (culture)', 'Tipo de región (terreno)': 'Region type (terrain)',
    'Ideología (gobierno)': 'Ideology (government)', 'Colonias': 'Colonies', 'Marcar como colonia': 'Mark as colony', 'Quitar colonia': 'Remove colony', 'Bandos': 'Sides', 'Alianzas': 'Alliances', 'Guerras': 'Wars', '(solo ver)': '(view only)',
    '(todas las guerras)': '(all wars)', 'Nueva guerra por fecha': 'New war by date', 'Atacante': 'Attacker', 'Objetivo': 'Target',
    'Fecha (MM/DD/AAAA)': 'Date (MM/DD/YYYY)', 'Probabilidad por turno (%)': 'Chance per turn (%)', 'Crear evento': 'Create event',
    'Destino': 'Target game', 'Carpeta nueva (en scenarios del destino)': 'New folder (in the target scenarios)', 'Qué fusionar': 'What to merge',
    'Colores': 'Colors', 'Infraestructura (TransportationLevel)': 'Infrastructure (TransportationLevel)', 'Investigación nueva': 'New research',
    'Evento de partisanos de MH1': 'MH1 partisan event', 'Guardar: archivos compartidos por defecto': 'Save: shared default files',
    'Sustituir los defaults': 'Replace the defaults', 'Guardar como escenario nuevo': 'Save as a new scenario',
    'Nombre de la carpeta nueva': 'New folder name', 'Surrendered': 'Surrendered', 'Países jugables (menú de inicio)': 'Playable countries (start menu)',
    'Aplicar países jugables': 'Apply playable countries', 'Filtrar países…': 'Filter countries…',
    'Editar regiones históricas en el mapa': 'Edit historic regions on the map', 'Asignarle regiones en el mapa': 'Assign regions on the map',
    'Nombre visible': 'Display name', 'Descripción': 'Description', 'Versión': 'Version', 'Tipo de escenario': 'Scenario type',
    'Año de inicio': 'Start year', 'Mes de inicio': 'Start month', 'Día de inicio': 'Start day', 'Año de fin': 'End year', 'Mes de fin': 'End month',
    'Día de fin': 'End day', 'Fecha de inicio': 'Start date', 'Fecha de fin': 'End date', 'Comparación histórica (texto al final)': 'Historical comparison (end text)',
    'Orden en la lista de escenarios': 'Order in the scenario list', 'Duración del turno': 'Turn length', 'Duración (turnos)': 'Length (turns)',
    'Propietario': 'Owner', 'Controlador': 'Controller', 'Nombre': 'Name', 'Tipo': 'Type', 'Capital': 'Capital', 'Gobierno': 'Government',
    'Ubicación': 'Location', 'Recurso': 'Resource', 'Miembros': 'Members', 'Defensor': 'Defender', 'Exportador': 'Exporter', 'Importador': 'Importer',
    'De': 'From', 'A': 'To', 'Estado': 'State', 'Posición': 'Position', 'Agresividad': 'Aggressiveness', 'Color': 'Color', 'No jugable': 'Not playable',
    'Con': 'With', 'Valor': 'Value', 'Regiones': 'Regions', 'Archivo': 'File', 'Unidades': 'Units', 'Nivel': 'Level', 'Coste': 'Cost',
    'Mantenimiento': 'Maintenance', 'Rama': 'Branch', 'Objeto': 'Object', 'Liberable': 'Liberable', 'Históricas': 'Historic', 'País': 'Country',
    'Evento': 'Event', 'Desde': 'From', '% por turno': '% per turn', 'Acciones': 'Actions',
    // editor de regiones
    'Modo': 'Mode', 'Ver / propiedad': 'View / ownership', 'Editar forma': 'Edit shape', 'Propiedad': 'Ownership', 'Seleccionar': 'Select',
    'Pintar propiedad': 'Paint ownership', 'Edición': 'Editing', 'Área': 'Area', 'Historial': 'History', 'Mover': 'Move', 'Insertar': 'Insert',
    'Borrar': 'Delete', 'Dibujar': 'Draw', 'Recortar': 'Cut', 'Rellenar': 'Fill', 'Pintar': 'Paint', 'Nueva región': 'New region',
    'Deshacer': 'Undo', 'Rehacer': 'Redo', 'Descartar': 'Discard', 'Instalar': 'Install', 'Escenario': 'Scenario', 'Escenarios': 'Scenarios',
    'Colorear': 'Color', 'por región': 'by region', 'por país': 'by country', 'Juego': 'Game', 'Regionpack': 'Regionpack', 'Centro': 'Center',
    'Opciones': 'Options', 'Topología': 'Topology', 'Cambios sin guardar': 'Unsaved changes', 'Informe': 'Report', 'Buscar región…': 'Search region…',
    'Acerca el mapa y haz clic en una región.': 'Zoom in and click a region.', 'Changelog del regionpack': 'Regionpack changelog',
    'Registrar': 'Register', '(elige escenario)': '(choose a scenario)', 'Solo tierra (no quitar mar)': 'Land only (keep the sea)',
    'Rellenar huecos al dibujar/pintar': 'Fill holes when drawing/painting', 'Repintar fronteras en la textura al guardar': 'Repaint borders on the texture when saving',
    'Todos los vértices (modificar sin seleccionar)': 'All vertices (edit without selecting)', '¿Dónde guardar los cambios del mapa?': 'Where to save the map changes?',
    'Solo se pregunta una vez por proyecto.': 'Asked only once per project.', 'En un regionpack nuevo (copia del actual):': 'In a new regionpack (copy of the current one):',
    'Escenarios que pasarán a usar el regionpack nuevo:': 'Scenarios that will use the new regionpack:', 'Crear una región nueva': 'Create a new region',
    'Añadir el área a una región existente:': 'Add the area to an existing region:', 'Terreno del mapa': 'Map terrain',
    // imagenes
    'Imágenes del escenario': 'Scenario images', 'Título y botones': 'Title and buttons', 'Banderas y escarapelas': 'Flags and roundels',
    'Iconos de unidades y productos': 'Unit and product icons', 'Vista previa': 'Preview', 'Bandera': 'Flag', 'Escarapela / emblema': 'Roundel / emblem',
    'Foto del líder': 'Leader photo', 'Descargar PNG': 'Download PNG', 'Escribir en el escenario…': 'Write to scenario…', 'Escribir archivos…': 'Write files…',
    'Escribir…': 'Write…', 'Imagen': 'Image', 'Fondo': 'Background', 'Zoom': 'Zoom', 'Capas': 'Layers', '+ Imagen': '+ Image', '+ Texto': '+ Text', '+ Relleno': '+ Fill',
    'Volver': 'Back', 'Medida': 'Size', 'Margen': 'Margin', 'Ajuste': 'Fit', 'Forma': 'Shape', 'Círculo': 'Circle', 'Cuadrado': 'Square', 'Escudo': 'Shield',
  };
  const PATTERNS = [
    [/^(\d+) de (\d+)$/, '$1 of $2'], [/^(\d+) archivo\(s\) sin guardar$/, '$1 unsaved file(s)'], [/Falta «Guardar»\.?/g, 'Remember to «Save».'],
    [/^(\d+) regiones históricas de (.+)\. Clic: añadir \/ quitar\.$/, '$1 historic regions of $2. Click: add / remove.'],
    [/^(\d+) regiones con cultura (.+)\. Clic: .*$/, '$1 regions with culture $2. Click: assign it to the region.'],
    [/^(\d+) regiones con terreno (.+)\. Clic: .*$/, '$1 regions with terrain $2. Click: assign it to the region.'],
    [/^(\d+) regiones · zoom (\d+)$/, '$1 regions · zoom $2'], [/^Cargando regiones…$/, 'Loading regions…'], [/^Cargando…$/, 'Loading…'],
    [/^Comportamiento de la IA de (.+)$/, 'AI behaviour of $1'],
    [/^(\d+) regiones · (\d+) históricas(:.*)?$/, (m, a, b, c) => `${a} regions · ${b} historic${c || ''}`],
    [/^Posición (\S*) · agresividad (\S*) · postura militar (\S*) · implicación internacional (\S*)$/,
      'Position $1 · aggressiveness $2 · military posture $3 · international involvement $4'],
    [/^(\d+) regiones (con cultura|con terreno|de países con gobierno)$/, (m, n, w) =>
      n + ' regions ' + { 'con cultura': 'with culture', 'con terreno': 'with terrain', 'de países con gobierno': 'of countries with government' }[w]],
    [/^(\d+) seleccionad[ao]s$/, '$1 selected'], [/^Capa: (.*)$/, (m, x) => 'Layer: ' + (EN[x] || x)],
    [/^(\S+) · TGA (\d+) bits · (RLE|sin comprimir) · origen (arriba|abajo)(?: · zona visible (\S+) en (\(.+\)))?$/, (m, sz, b, c, o, vz, at) =>
      `${sz} · TGA ${b} bits · ${c === 'RLE' ? 'RLE' : 'uncompressed'} · origin ${o === 'arriba' ? 'top' : 'bottom'}` + (vz ? ` · visible area ${vz} at ${at}` : '')], [/^Vecinos: (.*)$/, 'Neighbours: $1'],
    [/^(.+?)( \(controla (.+?)\))?( · .*?)?( · ([\d.]+) hab\.)$/, (m, a, c, ctl, ter, p, n) =>
      a + (c ? ` (controlled by ${ctl})` : '') + (ter || '') + ` · ${n.replace(/\./g, ',')} inh.`], [/^Ver «(.+)» en el mapa( ↗)?$/, 'Show «$1» on the map$2'],
    [/^mín\. (.*)$/, 'min. $1'], [/^no: (.+)$/, (m, r) => 'no: ' + tr(r)],
    [/^Eventos con fecha y probabilidad \((\d+)\)$/, 'Dated events and their chance ($1)'],
  ];
  const lang = () => { try { return localStorage.getItem('mh-lang') || 'es'; } catch (e) { return 'es'; } };
  // diccionario completo (i18n_en.json, generado con tools/i18n_extract.py): textos de la interfaz y mensajes del servidor
  let PHRASE_RE = null, PHRASES = {};
  if (lang() === 'en') {
    try {
      const x = new XMLHttpRequest(); x.open('GET', '/i18n_en.json', false); x.send();
      if (x.status === 200) {
        const ext = JSON.parse(x.responseText);
        for (const [k, v] of Object.entries(ext)) if (v && !(k in EN)) EN[k] = v;
        // frases (tres o más palabras) que se sustituyen también dentro de textos con datos variables;
        // con menos palabras saldrían mezclas («vuelve a the region»)
        const keys = Object.keys(ext).filter(k => ext[k] && k.trim().split(/\s+/).length >= 3).sort((a, b) => b.length - a.length);
        keys.forEach(k => { PHRASES[k] = ext[k]; });
        const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        // límite de palabra solo donde la frase empieza/termina en letra o número («(texto)» o «texto:» también encajan)
        const W = /[\p{L}\p{N}]/u;
        const bound = k => (W.test(k[0]) ? '(?<![\\p{L}\\p{N}])' : '') + escRe(k) + (W.test(k[k.length - 1]) ? '(?![\\p{L}\\p{N}])' : '');
        if (keys.length) PHRASE_RE = new RegExp(keys.map(bound).join('|'), 'gu');
      }
    } catch (e) {}
  }
  const tr = s => {
    if (!s) return s;
    let t = s.trim(); if (!t) return s;
    if (/\s\s|\n/.test(t)) { s = s.replace(/\s+/g, ' '); t = s.trim(); }   // textos partidos en varias líneas en el HTML
    if (EN[t]) return s.replace(t, EN[t]);
    const m = t.match(/^(.+?)( [▲▼+↗]|[.:…]+)$/);   // cabeceras ordenables, campos añadibles, enlaces, punto final
    if (m && EN[m[1]]) return s.replace(t, EN[m[1]] + m[2]);
    for (const [re, to] of PATTERNS) if (re.test(t)) return s.replace(t, t.replace(re, to));
    // palabras sueltas sin ambigüedad que quedan entre trozos ya traducidos («. Clic: …»)
    const words = x => x.replace(/(?<![\p{L}])Clic(?![\p{L}])/gu, 'Click');
    if (PHRASE_RE) { const r = s.replace(PHRASE_RE, k => PHRASES[k] || k); if (r !== s) return words(r); }
    return words(s);
  };
  window.mhTr = s => (lang() === 'en' ? tr(s) : s);   // para textos que se ponen sin pasar por el DOM observado
  if (lang() === 'en') {   // ventanas del navegador (confirmar / avisos / preguntar)
    const c = window.confirm.bind(window), a = window.alert.bind(window), p = window.prompt.bind(window);
    window.confirm = m => c(tr(String(m ?? '')));
    window.alert = m => a(tr(String(m ?? '')));
    window.prompt = (m, d) => p(tr(String(m ?? '')), d);
  }
  function walk(root) {
    if (lang() !== 'en') return;
    const it = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let n = root;
    while (n) {
      if (n.nodeType === 3) { const p = n.parentNode; if (p && !/^(SCRIPT|STYLE|TEXTAREA)$/.test(p.nodeName)) { const v = tr(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v; } }
      else if (n.nodeType === 1) {
        for (const a of ['title', 'placeholder']) { const v = n.getAttribute && n.getAttribute(a); if (v) { const w = tr(v); if (w !== v) n.setAttribute(a, w); } }
        if (n.nodeName === 'OPTION') { const v = tr(n.textContent); if (v !== n.textContent) n.textContent = v; }
      }
      n = it.nextNode();
    }
  }
  // ---- modo oscuro: por defecto el del sistema; si el usuario lo cambia, se recuerda (mh-theme = light | dark).
  // Las reglas @media (prefers-color-scheme: dark) de la página pasan a un <style> propio que se activa o no sin recargar
  // (recargar el editor de escenarios descarta lo no guardado).
  const DARKQ = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  let darkStyle = null;
  const themePref = () => { try { return localStorage.getItem('mh-theme'); } catch (e) { return null; } };
  const isDark = () => (themePref() || (DARKQ && DARKQ.matches ? 'dark' : 'light')) === 'dark';
  function captureDark() {
    if (darkStyle) return;
    let css = '';
    for (const sh of [...document.styleSheets]) {
      let rules; try { rules = sh.cssRules; } catch (e) { continue; }
      for (let i = rules.length - 1; i >= 0; i--) {
        const r = rules[i];
        if (r.media && /prefers-color-scheme:\s*dark/.test(r.media.mediaText)) { css = [...r.cssRules].map(x => x.cssText).join('\n') + '\n' + css; sh.deleteRule(i); }
      }
    }
    darkStyle = document.createElement('style'); darkStyle.id = 'mhDarkTheme'; darkStyle.textContent = css;
    document.head.appendChild(darkStyle);
  }
  function applyTheme() {
    captureDark();
    const d = isDark(); darkStyle.disabled = !d;
    document.documentElement.style.colorScheme = d ? 'dark' : 'light';
    document.documentElement.dataset.theme = d ? 'dark' : 'light';
    for (const b of document.querySelectorAll('.mhThemeBtn')) { b.textContent = d ? '☀' : '☾'; b.title = lang() === 'en' ? (d ? 'Light mode' : 'Dark mode') : (d ? 'Modo claro' : 'Modo oscuro'); }
  }
  window.MH_APPLY_THEME = applyTheme;
  if (DARKQ && DARKQ.addEventListener) DARKQ.addEventListener('change', () => { if (!themePref()) applyTheme(); });
  function themeToggle(after) {
    const b = document.createElement('button'); b.type = 'button'; b.className = 'mhThemeBtn';
    b.style.cssText = 'margin-left:6px;min-width:30px;font-size:15px;line-height:1;cursor:pointer';
    b.onclick = () => {
      try { localStorage.setItem('mh-theme', isDark() ? 'light' : 'dark'); } catch (e) {}
      applyTheme();
      for (const f of document.querySelectorAll('iframe')) { try { f.contentWindow.MH_APPLY_THEME && f.contentWindow.MH_APPLY_THEME(); } catch (e) {} }
      try { if (parent !== window && parent.MH_APPLY_THEME) parent.MH_APPLY_THEME(); } catch (e) {}
    };
    after.after(b); applyTheme();
  }
  try { applyTheme(); } catch (e) {}      // en cuanto se carga (las hojas de estilo del <head> ya están)
  function selector() {
    const sel = document.createElement('select');
    sel.title = 'Idioma del editor / Editor language';
    sel.innerHTML = '<option value="es">Español</option><option value="en">English</option>';
    sel.value = lang();
    sel.onchange = async () => {
      try { localStorage.setItem('mh-lang', sel.value); } catch (e) {}
      try { await fetch('/api/lang', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lang: sel.value }) }); } catch (e) {}
      location.reload();
    };
    const bar = document.getElementById('bar');
    const langSlot = document.getElementById('langSlot');     // sitio propio de la página (editor de regiones: a la derecha de Créditos y Fondo)
    if (langSlot) langSlot.appendChild(sel); else if (bar) { sel.style.marginLeft = 'auto'; bar.appendChild(sel); }
    if (bar) {
      const slot = document.getElementById('creditsSlot');
      (slot || bar).appendChild(credits());
      // editor de regiones (#creditsSlot): Discord, debajo GameBanana y debajo Actualizaciones; en el de escenarios, en fila: GameBanana · Discord · Actualizaciones
      const box = document.createElement('span');
      box.style.cssText = slot ? 'display:flex;flex-direction:column;gap:2px;margin-left:6px' : 'display:inline-flex;gap:6px;align-items:center';
      if (slot) box.append(discord(), hub(), updBtn()); else box.append(hub(), discord(), updBtn());
      (slot || bar).appendChild(box);
      if (slot) {     // los tres apilados no más altos que el botón «Ver / propiedad» de la barra
        const fit = () => {
          const ref = document.getElementById('viewBtn') || document.querySelector('.tool'); if (!ref || !ref.offsetHeight) return;
          box.style.height = ref.offsetHeight + 'px'; box.style.gap = '1px';
          for (const a of box.children) Object.assign(a.style, { flex: '1 1 0', minHeight: '0', display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: '0 8px', fontSize: '10px', lineHeight: '1', borderRadius: '4px', overflow: 'hidden' });
        };
        requestAnimationFrame(fit); [300, 1000, 3000].forEach(t => setTimeout(fit, t)); window.addEventListener('resize', fit);
      }
      themeToggle(sel);
      setTimeout(() => checkUpdates(false), 1500);
    }   // #creditsSlot: sitio propio de la página (p. ej. junto a Topología)
    else { Object.assign(sel.style, { position: 'fixed', right: '8px', bottom: '8px', zIndex: 9999 }); document.body.appendChild(sel); }
  }
  // créditos, Discord (novedades y actualizaciones) y dónde avisar de errores
  const VERSION = '3.2';
  const DISCORD = 'https://discord.com/invite/gFJyCjWEnr', BUGS = 'alopezcl@protonmail.com',
    UPDATES = 'https://github.com/avlopezparra/making-history-1-and-gold-editor/releases/', HUB = 'https://gamebanana.com/games/6530';
  // botón «Join Discord» aparte, en el morado de Discord
  const pill = (txt, bg, fg) => { const a = document.createElement('a'); a.textContent = txt;
    a.style.cssText = `background:${bg};color:${fg};border-radius:6px;padding:3px 9px;font:600 11px system-ui,sans-serif;text-decoration:none;white-space:nowrap;cursor:pointer;text-align:center`; return a; };
  function hub() {      // GameBanana, en amarillo
    const en = lang() === 'en', a = pill('GameBanana Hub', '#FFD43B', '#1d1d1f');
    a.href = HUB; a.target = '_blank'; a.rel = 'noopener'; a.title = en ? 'Upload and download regionpacks and scenarios' : 'Sube y descarga regionpacks y escenarios'; return a;
  }
  function updBtn() {
    const en = lang() === 'en', a = pill(en ? 'Check for updates' : 'Buscar actualización', '#2f6f3e', '#fff');
    a.href = '#'; a.onclick = e => { e.preventDefault(); checkUpdates(true); }; return a;
  }
  // actualizaciones: última versión publicada en GitHub; aviso una vez por versión («no volver a mostrar»)
  const newer = (a, b) => { const p = x => String(x).replace(/^v/i, '').split('.').map(n => parseInt(n, 10) || 0);
    const x = p(a), y = p(b); for (let i = 0; i < Math.max(x.length, y.length); i++) { if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); } return false; };
  async function checkUpdates(manual) {
    const en = lang() === 'en';
    if (!manual) { try { const last = +localStorage.getItem('mh-upd-checked') || 0; if (Date.now() - last < 864e5) return; localStorage.setItem('mh-upd-checked', Date.now()); } catch (e) {} }
    let rel;
    try { rel = await (await fetch('https://api.github.com/repos/avlopezparra/making-history-1-and-gold-editor/releases/latest')).json(); } catch (e) { rel = null; }
    const tag = rel && rel.tag_name;
    if (!tag) { if (manual) alert(en ? 'Could not check for updates (no connection or no releases yet).' : 'No se pudo buscar actualizaciones (sin conexión o aún no hay versiones publicadas).'); return; }
    if (!newer(tag, VERSION)) { if (manual) alert((en ? 'You have the latest version (' : 'Tienes la última versión (') + VERSION + ').'); return; }
    let skip = ''; try { skip = localStorage.getItem('mh-upd-skip') || ''; } catch (e) {}
    if (!manual && skip === tag) return;
    let d = document.getElementById('mhUpd');
    if (!d) { d = document.createElement('dialog'); d.id = 'mhUpd'; d.style.cssText = 'border:1px solid #888;border-radius:10px;max-width:420px;font:14px system-ui,sans-serif;background:var(--panel,#fff);color:var(--ink,#111)'; document.body.appendChild(d); }
    d.innerHTML = `<h3 style="margin-top:0">${en ? 'New version available' : 'Hay una versión nueva'}: ${tag}</h3>
      <p>${en ? 'You have' : 'Tienes la'} ${VERSION}. <a href="${UPDATES}" target="_blank" rel="noopener">${en ? 'Download it on GitHub' : 'Descárgala en GitHub'}</a></p>
      <label><input type="checkbox" id="mhUpdSkip"> ${en ? "Don't show again for this version" : 'No volver a mostrar para esta versión'}</label>
      <form method="dialog" style="text-align:right;margin-top:10px"><button>${en ? 'Close' : 'Cerrar'}</button></form>`;
    d.onclose = () => { if (d.querySelector('#mhUpdSkip').checked) try { localStorage.setItem('mh-upd-skip', tag); } catch (e) {} };
    d.showModal();
  }
  function discord() {
    const en = lang() === 'en', a = document.createElement('a');
    a.href = DISCORD; a.target = '_blank'; a.rel = 'noopener'; a.textContent = en ? 'Join Discord' : 'Únete al Discord';
    a.title = en ? 'Community, news and updates' : 'Comunidad, novedades y actualizaciones';
    a.style.cssText = 'background:#5865F2;color:#fff;border-radius:6px;padding:4px 10px;font:600 12px system-ui,sans-serif;text-decoration:none;align-self:stretch;text-align:center;white-space:nowrap';
    return a;
  }
  function credits() {
    const en = lang() === 'en', b = document.createElement('button');
    b.type = 'button'; b.textContent = en ? 'Credits / contact' : 'Créditos / contacto'; b.title = en ? 'Credits, updates and Discord' : 'Créditos, actualizaciones y Discord';
    b.onclick = () => {
      let d = document.getElementById('mhCredits');
      if (!d) {
        d = document.createElement('dialog'); d.id = 'mhCredits';
        d.style.cssText = 'border:1px solid #888;border-radius:10px;max-width:420px;font:14px system-ui,sans-serif;background:var(--panel,#fff);color:var(--ink,#111)';
        d.innerHTML = `<h3 style="margin-top:0">Making History Editor ${VERSION}</h3>
          <p style="margin-top:-6px;opacity:.75">${en ? 'Version ' : 'Versión '}${VERSION}</p>
          <p>${en ? 'Made by' : 'Hecho por'} <b>Alejandro Víctor López Parra</b> @avlopezparra, 2026</p>
          <p><a href="${UPDATES}" target="_blank" rel="noopener">${en ? 'Check for updates' : 'Buscar actualizaciones'}</a> · <a href="${DISCORD}" target="_blank" rel="noopener">${en ? 'Join the Discord' : 'Únete al Discord'}</a></p>
          <p><a href="${HUB}" target="_blank" rel="noopener">${en ? 'GameBanana hub of the game' : 'Hub del juego en GameBanana'}</a> · ${en ? 'upload your regionpacks and scenarios' : 'sube tus regionpacks y escenarios'}</p>
          <p>${en ? 'Report bugs to' : 'Informa de errores a'} <a href="mailto:${BUGS}">${BUGS}</a></p>
          <p>${en ? 'Support the editor:' : 'Apoya el editor:'} <a href="https://paypal.me/alopcl" target="_blank" rel="noopener">${en ? 'Donate' : 'Donar'}</a></p>
          <form method="dialog" style="text-align:right"><button>${en ? 'Close' : 'Cerrar'}</button></form>`;
        document.body.appendChild(d);
      }
      d.showModal();
    };
    return b;
  }
  function start() {
    document.documentElement.lang = lang();
    selector();
    if (lang() !== 'en') return;
    document.title = tr(document.title);
    walk(document.body);
    new MutationObserver(ms => { for (const m of ms) { if (m.type === 'characterData') walk(m.target); else m.addedNodes.forEach(x => walk(x)); } })
      .observe(document.body, { childList: true, subtree: true, characterData: true });
  }
  window.MH_LANG = lang; window.MH_TR = tr;
  // dentro de MHEditor.exe: el programa necesita saber si hay cambios sin guardar para avisar al cerrar
  setInterval(() => { try { if (window.pywebview && window.pywebview.api) window.pywebview.api.set_dirty(!!(window.mhDirty && window.mhDirty())); } catch (e) {} }, 1000);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
