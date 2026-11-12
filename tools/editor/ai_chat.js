// Editors' AI chat (regions and scenarios). The server (ai_chat.py) calls the provider with the local
// keys; tools run here: reads directly, writes only after confirming each action
// (with a scenario backup before the first one), and never Install. The conversation continues when switching editors.
(async () => {
  if (window.top !== window) return;      // the scenario editor's map is the regions one in an iframe: a single chat
  try { if ((await (await fetch('/api/ai/config')).json()).error) return; } catch (e) { return; }
  const KEY = 'mh_ai_chat', PAGE = /model/.test(location.pathname) ? 'modelos' : /imag/.test(location.pathname) ? 'imagenes' : location.pathname.includes('scenario') || location.pathname.includes('escenario') ? 'escenario' : 'regiones';
  const tr = s => (window.mhTr ? mhTr(s) : s);
  const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || { msgs: [] }; } catch (e) { return { msgs: [] }; } };
  const store = st => { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} };
  let st = load(), busy = false;
  const backed = new Set(st.backed || []);
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const j = async (url, body) => (await fetch(url, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {})).json();

  // Concrete actions: the model proposes the whole plan (propose_plan), the user approves it once and the editor
  // runs it without calling the AI again (1–2 requests per order: fits free plans).
  const FILES = {};                      // GeoJSON attached with 📎 (in memory, not in localStorage)
  const scenOf = a => a.scenario || pageS().scen || (document.querySelector('#scen') || {}).value || '';
  const mdy = d => { const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(d || ''); return m ? `${m[2]}/${m[3]}/${m[1]}` : d; };   // the game uses MM/DD/YYYY
  const ACTIONS = {
    create_army: { d: 'Ejército nuevo. args: owner (país), region, name, units [{type: plantilla, n}]',
      run: a => ['/api/scen/create', { name: scenOf(a), kind: 'army', owner: a.owner, obj_name: a.name, region: a.region, units: a.units || [] }] },
    create_fleet: { d: 'Flota nueva. args: owner, region (de mar), name, units [{type, n}], city (puerto, opcional)',
      run: a => ['/api/scen/create', { name: scenOf(a), kind: 'fleet', owner: a.owner, obj_name: a.name, region: a.region, units: a.units || [], city: a.city }] },
    create_airforce: { d: 'Fuerza aérea nueva. args: owner, region, name, units [{type, n}]',
      run: a => ['/api/scen/create', { name: scenOf(a), kind: 'airforce', owner: a.owner, obj_name: a.name, region: a.region, units: a.units || [] }] },
    create_city: { d: 'Ciudad nueva. args: region, name, owner, population, capital (bool)',
      run: a => ['/api/scen/create', { name: scenOf(a), kind: 'city', region: a.region, obj_name: a.name, owner: a.owner, population: a.population || 0, capital: !!a.capital }] },
    create_country: { d: 'País nuevo. args: name, color (#RRGGBB), regions [nombres], capital (ciudad), gov, ctype (Major|Minor)',
      run: a => ['/api/scen/create', { name: scenOf(a), kind: 'country', obj_name: a.name, color: a.color, regions: a.regions || [], capital: a.capital, gov: a.gov, ctype: a.ctype || 'Minor' }] },
    set_owner: { d: 'Cambia el dueño (y opcional controlador) de una región de tierra. args: region, owner, controller',
      run: a => ['/api/scen/set_owner', { name: scenOf(a), region: a.region, owner: a.owner, controller: a.controller }] },
    war_event: { d: 'Evento de guerra en una fecha. args: attacker, defenders [países], date (MM/DD/AAAA), pct',
      run: a => ['/api/scen/bulk', { name: scenOf(a), action: 'war_event', attacker: a.attacker, defenders: a.defenders || [], date: mdy(a.date), pct: a.pct || 80 }] },
    event: { d: 'Evento de plantilla. args: kind (war|embargo|gov|independence|resource|decision), owner, title, text, date (MM/DD/AAAA) o turn, effect {to|country|…}, choices (decision)',
      run: a => ['/api/scen/event_template', { name: scenOf(a), kind: a.kind, owner: a.owner, title: a.title, text: a.text || '', date: mdy(a.date), turn: a.turn, effect: a.effect || {}, choices: a.choices }] },
    import_geojson: { d: 'Importa un GeoJSON adjuntado por el usuario y asigna sus regiones a un país. args: file (nombre del adjunto), country, type (land_region por defecto). Acepta GeoJSON, KML y KMZ',
      run: a => {
        const fc = FILES[a.file];
        if (!fc) throw new Error('no hay ningún adjunto «' + a.file + '»: pide al usuario que lo adjunte con 📎');
        const feats = (fc.features || []).map(f => ({ ...f, properties: { mh_type: a.type || 'land_region', ...(f.properties || {}), ...(a.country ? { strOwner: a.country } : {}) } }));
        return ['/api/scen/geojson_import', { name: scenOf(a), geojson: { type: 'FeatureCollection', features: feats }, opts: { dup: 'import' } }];
      } },
    new_scenario: { d: 'Escenario nuevo copiando otro (crea una carpeta en el juego). args: src, new_name, display',
      run: a => ['/api/scen/new_from', { src: a.src, name: a.new_name, display: a.display }] },
    open_scenario: { d: 'Abre un escenario en el editor de escenarios. args: scenario',
      run: async a => { if (typeof openScenario !== 'function') throw new Error('solo en el editor de escenarios (usa open_editor)'); await openScenario(a.scenario); return 'abierto ' + a.scenario; } },
    save_scenario: { d: 'Guarda el escenario abierto en la carpeta del juego (solo si el usuario lo pide).',
      run: a => ['/api/scen/save', { name: scenOf(a) }] },
    api_call: { d: 'Avanzado: POST a otra ruta /api (búscala con lookup routes y lee route_source antes). args: path, body',
      run: a => [a.path, a.body || {}] },
  };
  const TOOLS = [
    { name: 'lookup', description: 'Consulta datos (no cambia nada). what: scenarios | countries | regions | cities (ciudad y su región) | units | unsaved (archivos del escenario con cambios sin guardar; vacío = todo guardado) | attachments | routes | route_source. filter: texto. path: para route_source.',
      parameters: { type: 'object', properties: { what: { type: 'string', enum: ['scenarios', 'countries', 'regions', 'cities', 'units', 'unsaved', 'attachments', 'routes', 'route_source'] }, filter: { type: 'string' }, path: { type: 'string' }, scenario: { type: 'string' } }, required: ['what'] } },
    { name: 'propose_plan', description: 'Propone TODAS las acciones de la petición de una vez; el usuario las aprueba y el editor las ejecuta en orden. Acciones:\n' +
        Object.entries(ACTIONS).map(([k, v]) => '- ' + k + ': ' + v.d).join('\n'),
      parameters: { type: 'object', properties: { summary: { type: 'string' }, steps: { type: 'array', items: { type: 'object', properties: {
        action: { type: 'string', enum: Object.keys(ACTIONS) }, args: { type: 'object' }, why: { type: 'string' } }, required: ['action', 'args'] } } }, required: ['summary', 'steps'] } },
    { name: 'open_editor', description: 'Pasa a otro editor y sigue la conversación allí. Opcional: escenario a abrir.',
      parameters: { type: 'object', properties: { editor: { type: 'string', enum: ['regiones', 'escenario', 'modelos', 'imagenes'] }, scenario: { type: 'string' } }, required: ['editor'] } },
  ];
  const system = () => `Eres el asistente del kit de modding de Making History (editor de ${PAGE}). Responde en ${({ en: 'inglés', ru: 'ruso' })[window.MH_LANG ? MH_LANG() : 'es'] || 'español'}, breve.
Trabaja así: si te falta un dato (nombre exacto de región, plantilla de unidad…) usa lookup; luego llama UNA vez a propose_plan con todos los pasos. No inventes nombres: usa los del contexto o de lookup.
Los cambios del escenario quedan sin guardar hasta save_scenario (solo si el usuario lo pide). Para saber si está todo guardado mira unsaved_files del estado o usa lookup unsaved; no digas que está guardado sin comprobarlo. Instalar en el juego lo hace siempre el usuario.
Si la petición es de otro editor, usa open_editor. Si ninguna acción sirve, usa api_call con una ruta de lookup routes.`;

  const pageS = () => { try { return S; } catch (e) { return {}; } };   // the page's «const S» is not on window
  const INFO = {};                       // lists of each scenario (countries, regions, units)
  const info = async sc => INFO[sc] || (INFO[sc] = await j('/api/scen/create_info', { name: sc }));
  async function pageState() {
    const S = pageS();
    const r = { editor: PAGE };
    if (PAGE === 'escenario') Object.assign(r, { scenario: S.scen || null, regionpack: S.pack || null });
    else if (PAGE === 'imagenes') {
      const sc = document.querySelector('#scen');
      r.scenario = sc ? sc.value : null;
      try { r.image = T.file ? { file: T.file.name || T.file, layers: (T.layers || []).length } : null; } catch (e) {}
    }
    else if (PAGE === 'modelos') { const M = window.M || {}, sc = document.querySelector('#scen');
      Object.assign(r, { scenario: sc ? sc.value : null, model: M.cur ? { sprite: M.cur.name, sprite_id: M.cur.id, nif: M.cur.nif, kind: M.cur.kind } : null }); }
    else {
      const R = S.selected != null && S.regions && S.regions.get(S.selected);
      r.selected_region = R ? R.props.name : null;
      try { const m = await j('/api/meta'); Object.assign(r, { project: m.project, regions: (m.regions || []).length, unsaved_history: m.history }); } catch (e) {}
      try { r.game = (await j('/api/game')).current; } catch (e) {}
    }
    // initial context: saves the most common queries
    if (r.scenario) try { const i = await info(r.scenario); Object.assign(r, { countries: i.countries, army_units: i.army }); } catch (e) {}
    if (r.scenario) try { r.unsaved_files = (await j('/api/scen/dirty', { name: r.scenario })).dirty || []; } catch (e) {}
    if (Object.keys(FILES).length) r.attachments = Object.keys(FILES);
    return r;
  }
  async function refreshPage() {
    try {
      if (PAGE === 'escenario' && pageS().scen && typeof openScenario === 'function') await openScenario(S.scen);
      else if (PAGE === 'regiones' && typeof reloadAll === 'function') await reloadAll();
      else if (PAGE === 'modelos' && typeof loadList === 'function') await loadList();
    } catch (e) {}
  }

  const cut = (t, n) => (t = String(t), t.length > n ? t.slice(0, n) + '…' : t);
  async function lookup(a) {
    const f = (a.filter || '').toLowerCase(), pick = xs => xs.filter(x => !f || String(x).toLowerCase().includes(f)).slice(0, 300).join(', ') || 'nada';
    if (a.what === 'routes') return (await j('/api/ai/routes?filter=' + encodeURIComponent(a.filter || ''))).routes;
    if (a.what === 'route_source') return (await j('/api/ai/route_src?path=' + encodeURIComponent(a.path || ''))).source;
    if (a.what === 'attachments') return Object.entries(FILES).map(([k, v]) => k + ' (' + (v.features || []).length + ' elementos)').join('\n') || 'ninguno';
    if (a.what === 'scenarios') return pick((await j('/api/scen/list')).scenarios || []);
    const sc = scenOf(a); if (!sc) return 'no hay escenario abierto: indica scenario';
    if (a.what === 'unsaved') { const d = (await j('/api/scen/dirty', { name: sc })).dirty || []; return d.length ? 'sin guardar: ' + d.join(', ') : 'todo guardado'; }
    if (a.what === 'cities') return (await j('/api/ai/cities', { scenario: sc, filter: a.filter || '' })).cities;
    const i = await info(sc);
    return pick({ countries: i.countries, regions: (i.land || []).concat(i.sea || []), units: [].concat(i.army || [], i.navy || [], i.air || []) }[a.what] || []);
  }
  // a plan step → [path, body] (or text if done in the page); error if the response carries one
  async function runStep(s) {
    const act = ACTIONS[s.action]; if (!act) throw new Error('acción desconocida ' + s.action);
    const r = await act.run(s.args || {});
    if (typeof r === 'string') return r;
    const [path, body] = r;
    const chk = await j('/api/ai/check', { method: 'POST', path });
    if (chk.error) throw new Error(chk.error);
    const sc = body.name || body.scenario;
    if (sc && path.startsWith('/api/scen/') && !backed.has(sc)) {
      const b = await j('/api/ai/backup', { scenario: sc });
      if (b.backup) { backed.add(sc); st.backed = [...backed]; addLine('sys', tr('Copia de seguridad: ') + b.backup); }
    }
    const out = await j(path, body);
    st.refresh = true;
    const err = out.error || (out.errors && out.errors.length && out.errors.join('; ')) ||
      (out.needs_type || out.needs_owner || out.duplicates ? 'el GeoJSON necesita decisiones: ' + JSON.stringify(out).slice(0, 300) : '');
    if (err) throw new Error(err);
    return cut(JSON.stringify(out.notes || out), 300);
  }

  async function unknownNames(steps) {
    const bad = [];
    for (const s of steps) {
      const a = s.args || {}, sc = scenOf(a);
      if (!sc || s.action === 'new_scenario' || s.action === 'api_call') continue;
      let i; try { i = await info(sc); } catch (e) { continue; }
      const C = new Set(i.countries || []), R = new Set([].concat(i.land || [], i.sea || [])), U = new Set([].concat(i.army || [], i.navy || [], i.air || []));
      for (const k of ['owner', 'controller', 'country', 'attacker']) if (a[k] && !C.has(a[k]) && !(s.action === 'create_country')) bad.push(a[k]);
      for (const x of a.defenders || []) if (!C.has(x)) bad.push(x);
      if (a.region && !R.has(a.region)) bad.push(a.region);
      for (const u of a.units || []) if (u && u.type && !U.has(u.type)) bad.push(u.type);
    }
    return [...new Set(bad)];
  }
  async function runTool(c) {
    const a = c.args || {};
    if (c.name === 'lookup') return lookup(a);
    if (c.name === 'propose_plan') {
      const steps = a.steps || [];
      const bad = await unknownNames(steps);      // invented names: returned to the model without bothering the user
      if (bad.length) return { content: 'Nombres que no existen en el escenario: ' + bad.join(', ') + '. Búscalos con lookup (una ciudad está dentro de una región: lookup cities) y vuelve a proponer el plan.', failed: true };
      if (!await askPlan(a.summary, steps)) return 'El usuario rechazó el plan.';
      const done = [];
      for (const [k, s] of steps.entries()) {
        try { done.push((k + 1) + '. ' + s.action + ': OK ' + await runStep(s)); }
        catch (e) { done.push((k + 1) + '. ' + s.action + ': ERROR ' + e.message); return { content: done.join('\n') + '\nSe detuvo aquí; los pasos anteriores quedaron aplicados.', failed: true }; }
      }
      return { content: done.join('\n'), failed: false };
    }
    if (c.name === 'open_editor') {
      st.resume = { id: c.id, name: c.name, content: 'Editor «' + a.editor + '» abierto.' };
      if (a.scenario) st.openScen = a.scenario;
      store(st);
      location.href = a.editor === 'escenario' ? '/escenario' : a.editor === 'modelos' ? '/modelos' : a.editor === 'imagenes' ? '/images' : '/';
      return null;      // the page changes; the result is sent when the other one loads
    }
    return 'herramienta desconocida';
  }

  // ---------- interfaz ----------
  const css = `#aiBtn{position:fixed;right:14px;bottom:14px;z-index:2147483000;border-radius:20px;padding:6px 12px;cursor:grab;touch-action:none}
#aiBox{position:fixed;right:14px;bottom:52px;width:min(420px,calc(100vw - 28px));height:min(560px,calc(100vh - 80px));z-index:2147483000;display:none;flex-direction:column;
 background:var(--panel,#1e1e1e);text-align:left;color:var(--fg,#ddd);border:1px solid #666;border-radius:8px;box-shadow:0 4px 18px #0008;font-size:13px}
#aiBox.open{display:flex}#aiLog{flex:1;overflow:auto;padding:8px}#aiLog .m{margin:6px 0;white-space:pre-wrap;word-break:break-word}
#aiLog .user{text-align:right;color:#8cf}#aiLog .sys{color:#999;font-size:11px}#aiLog .tool{color:#aaa;font-size:11px;font-family:monospace}
#aiLog .card{border:1px solid #c90;border-radius:6px;padding:6px;margin:6px 0}#aiLog .card.disk{border-color:#e44}
#aiLog .card pre{max-height:160px;overflow:auto;font-size:11px;margin:4px 0}
#aiHead{display:flex;gap:6px;align-items:center;padding:6px;border-bottom:1px solid #555}#aiHead b{flex:1}
#aiIn{display:flex;gap:4px;padding:6px;border-top:1px solid #555}#aiIn textarea{flex:1;height:48px;resize:none}
#aiCfg{display:none;padding:8px;border-bottom:1px solid #555}#aiCfg.open{display:block}#aiCfg label{display:block;margin:3px 0}#aiCfg input{width:100%}`;
  document.head.insertAdjacentHTML('beforeend', '<style>' + css + '</style>');
  document.body.insertAdjacentHTML('beforeend', `<button id="aiBtn" title="Asistente de IA (arrástralo para moverlo; doble clic: junto al mapa)">🤖 IA</button>
<div id="aiBox"><div id="aiHead"><b>Asistente de IA</b><span id="aiProv" class="muted"></span>
<select id="aiHist" title="Chats guardados" style="max-width:110px"></select><button id="aiSaveChat" title="Guardar este chat">💾</button><button id="aiDelChat" title="Borrar de la lista el chat guardado que está abierto">✖</button><button id="aiCfgBtn" title="Configurar APIs">⚙</button><button id="aiClear" title="Borrar conversación">🗑</button><button id="aiClose">✕</button></div>
<div id="aiCfg"></div><div id="aiLog"></div>
<div id="aiIn"><label id="aiAtt" title="Adjuntar GeoJSON, KML o KMZ" style="cursor:pointer;align-self:center">📎<input type="file" accept=".geojson,.json,.kml,.kmz" multiple hidden></label><textarea id="aiText" placeholder="Pide algo: «crea un ejército de infantería en Madrid para España»…"></textarea><button id="aiSend">Enviar</button></div></div>`);
  const $ = s => document.querySelector(s), log = $('#aiLog');
  function addLine(cls, text) { const d = document.createElement('div'); d.className = 'm ' + cls; d.textContent = text; log.appendChild(d); log.scrollTop = 1e9; return d; }
  function render() {
    log.innerHTML = '';
    for (const m of st.msgs) {
      if (m.text) addLine(m.role === 'user' ? 'user' : 'bot', m.text);
      for (const c of m.calls || []) addLine('tool', '→ ' + c.name + ' ' + JSON.stringify(c.args).slice(0, 200));
      for (const r of m.results || []) addLine('tool', '← ' + String(r.content).slice(0, 160));
    }
  }
  const DISK_ACT = new Set(['new_scenario', 'save_scenario', 'api_call']);
  function askPlan(summary, steps) {
    return new Promise(res => {
      const disk = steps.some(s => DISK_ACT.has(s.action));
      const d = document.createElement('div'); d.className = 'card' + (disk ? ' disk' : '');
      d.innerHTML = `<div><b>${esc(tr('Plan propuesto'))}:</b> ${esc(summary || '')}</div>${disk ? '<div style="color:#e66">' + esc(tr('Algún paso escribe en disco (se hace copia antes).')) + '</div>' : ''}
<ol style="margin:4px 0;padding-left:20px">${steps.map(s => `<li><b>${esc(s.action)}</b>${s.why ? ' — ' + esc(s.why) : ''}<pre>${esc(JSON.stringify(s.args || {}))}</pre></li>`).join('')}</ol>
<button class="ok">${esc(tr('Aplicar'))}</button> <button class="no">${esc(tr('Rechazar'))}</button>`;
      log.appendChild(d); log.scrollTop = 1e9; $('#aiBox').classList.add('open');
      d.querySelector('.ok').onclick = () => { d.querySelectorAll('button').forEach(b => b.remove()); d.insertAdjacentHTML('beforeend', '✔'); res(true); };
      d.querySelector('.no').onclick = () => { d.querySelectorAll('button').forEach(b => b.remove()); d.insertAdjacentHTML('beforeend', '✖'); res(false); };
    });
  }

  async function loop() {
    if (busy) return; busy = true; $('#aiSend').disabled = true;
    const wait = addLine('sys', tr('Pensando…'));
    try {
      for (let step = 0; step < 30; step++) {
        const r = await j('/api/ai/chat', { system: system() + '\nEstado actual: ' + JSON.stringify(await pageState()), messages: st.msgs, tools: TOOLS });
        if (r.error) { addLine('sys', 'ERROR: ' + r.error); break; }
        if (r.notes) addLine('sys', tr('Respaldo: ') + r.notes.join(' | ') + ' → ' + r.provider + ' · ' + r.model);
        const m = { role: 'assistant', text: r.text || '', calls: r.calls || [] };
        if (r.raw) m.raw = r.raw;
        st.msgs.push(m); store(st);
        if (m.text) addLine('bot', m.text);
        log.appendChild(wait);
        if (!m.calls.length) break;
        const results = []; let planOk = false;
        for (const c of m.calls) {
          addLine('tool', '→ ' + c.name + ' ' + JSON.stringify(c.args).slice(0, 200));
          let out;
          try { out = await runTool(c); } catch (e) { out = 'ERROR: ' + e.message; }
          if (out === null) { st.pending = results; store(st); return; }   // cambio de editor
          if (out && typeof out === 'object') { planOk = !out.failed; out = out.content; }
          results.push({ id: c.id, name: c.name, content: String(out) });
          addLine('tool', '← ' + String(out).slice(0, 300));
        }
        st.msgs.push({ role: 'user', results }); store(st);
        if (planOk) {
          const sc = scenOf({}), d = sc ? ((await j('/api/scen/dirty', { name: sc })).dirty || []) : [];
          addLine('bot', d.length ? tr('Hecho. Sin guardar: ') + d.join(', ') + tr(' (pulsa Guardar escenario).') : tr('Hecho. Todo guardado.'));
          break;
        }
      }
      if (st.refresh) { st.refresh = false; store(st); await refreshPage(); }
    } finally { wait.remove(); busy = false; $('#aiSend').disabled = false; }
  }

  async function showCfg() {
    const c = await j('/api/ai/config'), box = $('#aiCfg');
    $('#aiProv').textContent = c.providers[c.active].label + ' · ' + c.providers[c.active].model;
    box.innerHTML = `<label>${esc(tr('Proveedor'))} <select id="aiP">${Object.entries(c.providers).map(([k, p]) => `<option value="${k}"${k === c.active ? ' selected' : ''}>${esc(p.label)}${p.has_key ? '' : ' ' + esc(tr('(sin clave)'))}</option>`).join('')}</select></label>
<label>${esc(tr('Modelo'))} <span style="display:flex;gap:4px"><input id="aiM" list="aiML" style="flex:1" placeholder="${esc(tr('nombre del modelo'))}"><datalist id="aiML"></datalist><button id="aiMR" title="${esc(tr('Buscar los modelos de la API'))}">↻</button></span></label><input id="aiMF" placeholder="${esc(tr('Filtrar modelos…'))}"><span id="aiMS" class="muted" style="font-size:11px"></span><label>URL <input id="aiU"></label>
<label>${esc(tr('Clave API'))} <input id="aiK" type="password" placeholder="${esc(tr('(guardada; vacío = no cambiar)'))}"></label>
<div style="margin:4px 0">${esc(tr('Si falla, probar con:'))} ${Object.entries(c.providers).filter(([k, p]) => k !== 'mock' && p.has_key).map(([k, p]) => `<label style="display:inline"><input type="checkbox" class="aiFb" value="${k}"${c.fallback.includes(k) ? ' checked' : ''}> ${esc(p.label)}</label>`).join(' ')}</div>
<button id="aiSave">${esc(tr('Guardar'))}</button> <span class="muted" style="font-size:11px">${esc(tr('Las claves se guardan solo en este equipo:'))} ${esc(c.file)}</span>`;
    // models offered by the API (with the key from the form or the saved one)
    const listModels = async () => {
      const k = $('#aiP').value, cur = $('#aiM').value || c.providers[k].model;
      $('#aiMS').textContent = tr('Buscando modelos…');
      const r = await j('/api/ai/models', { provider: k, key: $('#aiK').value, base: $('#aiU').value });
      const ms = r.models || []; allModels = ms.slice();
      if (!ms.includes(cur) && cur && !ms.length) ms.push(cur);
      $('#aiML').innerHTML = ms.map(m => `<option value="${esc(m)}">`).join('');
      $('#aiM').value = ms.includes(cur) || !allModels.length ? cur : r.best || ms[0] || '';   // no list (e.g. Yandex): typed by hand
      $('#aiMS').textContent = r.error ? 'ERROR: ' + r.error : ms.length + ' ' + tr('modelos');
    };
    let allModels = [];
    $('#aiMF').oninput = () => {
      const f = $('#aiMF').value.toLowerCase(), cur = $('#aiM').value, ms = allModels.filter(m => m.toLowerCase().includes(f));
      $('#aiML').innerHTML = ms.map(m => `<option value="${esc(m)}">`).join(''); if (ms.length === 1) $('#aiM').value = ms[0];
    };
    const fill = () => { const p = c.providers[$('#aiP').value]; $('#aiM').value = p.model; $('#aiML').innerHTML = ''; $('#aiU').value = p.base; $('#aiK').value = ''; if (p.has_key) listModels(); };
    $('#aiP').onchange = fill; fill();
    $('#aiMR').onclick = listModels; $('#aiK').onchange = listModels;
    $('#aiSave').onclick = async () => {
      const k = $('#aiP').value;
      await j('/api/ai/config', { active: k, providers: { [k]: { model: $('#aiM').value, base: $('#aiU').value, key: $('#aiK').value } },
        fallback: [...document.querySelectorAll('.aiFb:checked')].map(x => x.value) });
      box.classList.remove('open'); showCfg();
    };
  }

  $('#aiAtt input').onchange = async e => {
    for (const f of e.target.files) {
      try {
        if (/\.km[lz]$/i.test(f.name)) {     // KML/KMZ: converted by the server, as in «Importar GeoJSON» of the regions editor
          const data = await new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(f); });
          const r = await j('/api/geojson/kml', { data });
          if (r.error) throw new Error(r.error);
          FILES[f.name] = r;
        } else FILES[f.name] = JSON.parse(await f.text()); addLine('sys', tr('Adjunto: ') + f.name + ' (' + (FILES[f.name].features || []).length + ')'); }
      catch (err) { addLine('sys', 'ERROR ' + f.name + ': ' + err.message); }
    }
    e.target.value = '';
  };
  // movable button (drag); with no saved position it goes to the map's bottom-right corner
  const BKEY = 'mh_ai_btn', btn = $('#aiBtn');
  const place = (x, y) => { x = Math.max(0, Math.min(innerWidth - btn.offsetWidth, x)); y = Math.max(0, Math.min(innerHeight - btn.offsetHeight, y));
    Object.assign(btn.style, { left: x + 'px', top: y + 'px', right: 'auto', bottom: 'auto' }); return [x, y]; };
  const home = () => {
    let p; try { p = JSON.parse(localStorage.getItem(BKEY)); } catch (e) {}
    if (p) return place(p[0], p[1]);
    const m = document.querySelector('#mapframe, .leaflet-container');
    const r = m && m.getBoundingClientRect();
    if (r && r.width > 100) place(r.right - btn.offsetWidth - 12, r.bottom - btn.offsetHeight - 26);
  };
  setTimeout(home, 1500); addEventListener('resize', home);
  let drag = null, moved = false;
  btn.onpointerdown = e => { drag = [e.clientX - btn.offsetLeft, e.clientY - btn.offsetTop]; moved = false; btn.setPointerCapture(e.pointerId); };
  btn.onpointermove = e => { if (!drag) return; if (!moved && Math.hypot(e.clientX - drag[0] - btn.offsetLeft, e.clientY - drag[1] - btn.offsetTop) < 4) return;
    moved = true; place(e.clientX - drag[0], e.clientY - drag[1]); };
  btn.onpointerup = () => { if (drag && moved) try { localStorage.setItem(BKEY, JSON.stringify([btn.offsetLeft, btn.offsetTop])); } catch (e) {} drag = null; };
  btn.ondblclick = () => { try { localStorage.removeItem(BKEY); } catch (e) {} home(); };   // double click: back next to the map
  $('#aiBtn').onclick = () => { if (moved) { moved = false; return; } $('#aiBox').classList.toggle('open'); showCfg(); };
  $('#aiClose').onclick = () => $('#aiBox').classList.remove('open');
  $('#aiCfgBtn').onclick = () => $('#aiCfg').classList.toggle('open');
  // chats saved in this browser: name = date + start of the first request
  const HKEY = 'mh_ai_chats', hist = () => { try { return JSON.parse(localStorage.getItem(HKEY)) || {}; } catch (e) { return {}; } };
  const fillHist = () => { $('#aiHist').innerHTML = `<option value="">${esc(tr('Chats guardados…'))}</option>` +
    Object.keys(hist()).sort().reverse().map(k => `<option>${esc(k)}</option>`).join(''); };
  $('#aiSaveChat').onclick = () => {
    if (!st.msgs.length) return;
    const first = (st.msgs.find(m => m.text && m.role === 'user') || {}).text || '';
    const name = st.chatName || new Date().toISOString().slice(0, 16).replace('T', ' ') + ' · ' + first.slice(0, 40);
    const h = hist(); h[name] = st.msgs; st.chatName = name;
    try { localStorage.setItem(HKEY, JSON.stringify(h)); addLine('sys', tr('Chat guardado: ') + name); } catch (e) { addLine('sys', 'ERROR: ' + e.message); }
    store(st); fillHist();
  };
  $('#aiHist').onchange = () => {
    const k = $('#aiHist').value, h = hist(); if (!k || !h[k]) return;
    st = { msgs: h[k], chatName: k }; store(st); render(); $('#aiHist').value = '';
  };
  // two clicks: the first asks for confirmation on the button itself (confirm() does not show in all embedded browsers)
  $('#aiDelChat').onclick = () => {
    const b = $('#aiDelChat'), k = st.chatName, h = hist();
    if (!k || !h[k]) return addLine('sys', tr('Abre antes un chat guardado para borrarlo.'));
    if (!b.dataset.arm) { b.dataset.arm = '1'; b.textContent = tr('¿Borrar?'); setTimeout(() => { delete b.dataset.arm; b.textContent = '✖'; }, 4000); return; }
    delete b.dataset.arm; b.textContent = '✖';
    delete h[k]; try { localStorage.setItem(HKEY, JSON.stringify(h)); } catch (e) {}
    delete st.chatName; store(st); fillHist(); addLine('sys', tr('Chat borrado de la lista: ') + k);
  };
  fillHist();
  $('#aiClear').onclick = () => { st = { msgs: [] }; backed.clear(); store(st); render(); };
  $('#aiSend').onclick = () => {
    const t = $('#aiText').value.trim(); if (!t || busy) return;
    $('#aiText').value = ''; const last = st.msgs[st.msgs.length - 1];
    if (last && last.role === 'user' && last.results && !last.text) last.text = t; else st.msgs.push({ role: 'user', text: t });
    store(st); addLine('user', t); loop();
  };
  $('#aiText').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#aiSend').onclick(); } };
  render();
  // comes from the other editor: completes the open_editor result and continues
  if (st.resume) {
    const res = (st.pending || []).concat([st.resume]), sc = st.openScen;
    delete st.resume; delete st.pending; delete st.openScen;
    st.msgs.push({ role: 'user', results: res }); store(st);
    $('#aiBox').classList.add('open'); render(); showCfg();
    setTimeout(async () => {
      if (sc && typeof openScenario === 'function') { try { await openScenario(sc); } catch (e) {} }
      else if (sc && PAGE === 'modelos' && typeof loadList === 'function') { const el = document.querySelector('#scen'); if (el) { el.value = sc; try { await loadList(); } catch (e) {} } }
      loop();
    }, 1500);
  }
  window.MH_AI = { tools: TOOLS, runTool, state: () => st };
})();
