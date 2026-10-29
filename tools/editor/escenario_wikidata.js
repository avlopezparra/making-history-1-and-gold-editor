// Wikidata en el editor de escenarios (se carga al final de escenario.html; envuelve renderObj):
// - Ciudad: QID a mano o búsqueda por nombre; muestra coordenadas (P625), población del año más cercano al del escenario
//   (solo si está a 20 años o menos; si no, enlace a worldcitypop.com) y el país de entonces (P17). Aplica solo al confirmar.
// - País (también provincias reales, p. ej. Cataluña Q5705, y estados rendidos): capital, ciudades principales, población
//   y bandera de Commons (P41), que se puede importar con la herramienta de banderas.
// - La asociación nombre -> QID se anota en el changelog del regionpack (entrada «wikidata», por escenario).
// Rutas /api/wikidata/* de editor_server.py (wikidata.py). Sin conexión usa la caché o avisa.
(() => {
  'use strict';
  const post = (u, b) => fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(r => r.json());
  const t = x => (window.mhTr ? window.mhTr(x) : x);
  const lang = () => (window.MH_LANG ? window.MH_LANG() : 'es');
  const WD = { links: null, scen: null };
  const fmt = n => (n == null ? '—' : Number(n).toLocaleString());

  async function links() {
    if (WD.scen !== S.scen || !WD.links) {
      const r = await post('/api/wikidata/links', { scen: S.scen }); WD.links = r.links || {}; WD.year = r.year; WD.scen = S.scen;
    }
    return WD.links;
  }
  const offlineNote = r => `<div class="note err">${esc(t('Sin conexión con Wikidata: se usan los datos guardados si los hay.'))} <span class="muted">${esc(r.error || '')}</span></div>`;

  function dialog() {
    let dl = document.getElementById('wdDlg');
    if (dl) return dl;
    dl = document.createElement('dialog'); dl.id = 'wdDlg'; dl.style.cssText = 'width:min(640px,94vw)';
    dl.innerHTML = `<header><b id="wdTitle">Wikidata</b><button class="btn small" style="margin-left:auto" id="wdClose">Cerrar</button></header>
      <div class="body"><div class="row"><input id="wdQ" placeholder="Nombre o ID (p. ej. Q11194)" style="flex:1;min-width:200px"><button class="btn small" id="wdGo">Buscar</button>
      <span class="muted" id="wdWait"></span></div><div id="wdList"></div><div id="wdData"></div></div>`;
    document.body.appendChild(dl);
    dl.querySelector('#wdClose').onclick = () => dl.close();
    return dl;
  }

  async function open(d, kind) {
    const dl = dialog(), q = s => dl.querySelector(s), L = await links(), key = kind + ':' + d.label;
    q('#wdTitle').textContent = 'Wikidata · ' + d.label; q('#wdList').innerHTML = q('#wdData').innerHTML = '';
    q('#wdQ').value = (L[key] && L[key].id) || d.label;
    const wait = x => { q('#wdWait').textContent = x ? t(x) : ''; };
    const show = async id => {
      wait('consultando…');
      const e = await post('/api/wikidata/entity', { scen: S.scen, id, kind, lang: lang() }); wait('');
      if (e.offline) return void (q('#wdData').innerHTML = offlineNote(e));
      if (e.error) return void (q('#wdData').innerHTML = `<div class="note err">${esc(e.error)}</div>`);
      q('#wdList').innerHTML = '';
      render(d, kind, e, q);
    };
    q('#wdGo').onclick = async () => {
      const v = q('#wdQ').value.trim(); if (!v) return;
      if (/^Q\d+$/i.test(v)) return show(v);
      wait('buscando…');
      const r = await post('/api/wikidata/search', { q: v, kind, lang: lang() }); wait('');
      if (r.offline) return void (q('#wdList').innerHTML = offlineNote(r));
      q('#wdList').innerHTML = (r.hits || []).map(h => `<div class="row"><button class="btn small" data-wd="${esc(h.id)}">${esc(h.id)}</button><b>${esc(h.label)}</b> <span class="muted">${esc(h.description)}</span></div>`).join('')
        || `<div class="muted">${esc(t('Sin resultados'))}</div>`;
      q('#wdList').querySelectorAll('[data-wd]').forEach(b => b.onclick = () => show(b.dataset.wd));
    };
    q('#wdQ').onkeydown = e => { if (e.key === 'Enter') q('#wdGo').click(); };
    dl.showModal();
    if (L[key]) show(L[key].id);
  }

  function popHtml(p, label) {
    if (p.value != null) return `<label>${esc(t('Población'))}</label><div><label><input type="checkbox" id="wdPop" checked> <b>${fmt(p.value)}</b> (${p.year})</label></div>`;
    return `<label>${esc(t('Población'))}</label><div><span class="muted">${esc(t('Wikidata no tiene un dato a 20 años o menos del escenario'))}${p.year ? ` (${esc(t('el más cercano'))}: ${fmt(p.all.find(x => x[0] === p.year)[1])}, ${p.year})` : ''}.</span>
      <a href="${esc(p.alt)}" target="_blank" rel="noopener">worldcitypop.com</a> <span class="muted">(${esc(t('consúltalo allí y escríbelo a mano'))}: ${esc(label)})</span></div>`;
  }

  function render(d, kind, e, q) {
    const prop = n => (d.props.find(p => p.name === n) || {}).value;
    let h = `<div class="sec"><h3><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.id)}</a> · ${esc(e.label)}</h3><div class="muted">${esc(e.description)} · ${esc(t('año del escenario'))}: ${e.year}</div>`;
    if (!e.exists) h += `<div class="note">${esc(t('No existía en ese año'))} (${e.inception ?? '?'}–${e.dissolved ?? ''}).</div>`;
    h += '<div class="grid">';
    if (kind === 'city') {
      if (e.coords) h += `<label>${esc(t('Coordenadas'))}</label><div><label><input type="checkbox" id="wdPos" checked> ${e.coords.lon}, ${e.coords.lat}</label> <span class="muted">(${esc(t('ahora'))}: ${esc(prop('vecPosition') || '—')})</span></div>`;
      h += popHtml(e.population, e.label);
      if (e.population.value != null) h += `<label></label><div class="muted">${esc(t('ahora'))}: ${fmt(prop('nPopulation'))}</div>`;
      h += `<label>${esc(t('País en ese año'))}</label><div>${e.country.map(c => esc(c.label)).join(', ') || '—'} <span class="muted">(${esc(t('solo informativo: el dueño lo da la región'))})</span></div>`;
    } else {
      h += `<label>${esc(t('Capital'))}</label><div>${e.capital.map(c => esc(c.label)).join(', ') || '—'}</div>`;
      if (e.located_in.length || e.country.length) h += `<label>${esc(t('Pertenece a'))}</label><div>${e.country.concat(e.located_in).map(c => esc(c.label)).join(', ')}</div>`;
      h += popHtml(e.population, e.label).replace(/<input[^>]*id="wdPop"[^>]*>/, '');      // del país: solo informativo
      h += `<label>${esc(t('Ciudades principales'))}</label><div>${e.cities_error ? `<span class="muted">${esc(e.cities_error)}</span>`
        : (e.cities || []).map(c => `${esc(c.label)} <span class="muted">${fmt(c.pop_now)}</span>`).join(' · ') || '—'}</div>`;
      if (e.flag) h += `<label>${esc(t('Bandera'))}</label><div><img src="${esc(e.flag.png.replace('width=512', 'width=96'))}" alt="" style="height:32px;vertical-align:middle;border:1px solid var(--line,#888)">
        <a href="${esc(e.flag.page)}" target="_blank" rel="noopener">${esc(e.flag.file)}</a> <button class="btn small" id="wdFlag">Importar bandera…</button></div>`;
      if (e.roundel) h += `<label>${esc(t('Escarapela (roundel)'))}</label><div><img src="${esc(e.roundel.png.replace('width=512', 'width=64'))}" alt="" style="height:32px;vertical-align:middle">
        <a href="${esc(e.roundel.page)}" target="_blank" rel="noopener">${esc(e.roundel.file)}</a> <span class="muted">(${esc(e.roundel.air_force.label)})</span> <button class="btn small" id="wdDecal">Importar escarapela…</button></div>`;
      h += `<label>${esc(t('Estado rendido'))}</label><div><label><input type="checkbox" id="wdSur"> ${esc(t('marcarlo como rendido (surrendered) en la asociación'))}</label></div>`;
    }
    h += `</div><div class="row" style="margin-top:8px"><button class="btn primary" id="wdApply">Aplicar</button><button class="btn" id="wdLinkOnly">Solo asociar</button><button class="btn" id="wdUnlink">Quitar asociación</button><span class="muted" id="wdMsg"></span></div></div>`;
    q('#wdData').innerHTML = h;
    const key = kind + ':' + d.label;
    if (q('#wdSur') && WD.links[key]) q('#wdSur').checked = !!WD.links[key].surrendered;
    const link = async id => {
      const r = await post('/api/wikidata/link', { scen: S.scen, kind, name: d.label, id, label: e.label, surrendered: q('#wdSur') && q('#wdSur').checked });
      if (r.error) throw new Error(r.error); WD.links = r.links;
    };
    const msg = x => { q('#wdMsg').textContent = t(x); };
    q('#wdLinkOnly').onclick = async () => { await link(e.id); msg('Asociación guardada en el changelog.'); };
    q('#wdUnlink').onclick = async () => { await link(''); msg('Asociación quitada.'); };
    const imp = (which, img) => () => {      // abre la herramienta de banderas (escenario_imagenes.js) con la URL de Commons
      const b = document.querySelector(`#right [data-mh=${which}]`); if (!b) return msg('Este país no tiene sección de bandera.');
      q('#wdData').closest('dialog').close(); b.click();
      const u = document.querySelector('#mhUrl'); if (u) { u.value = img.png; document.querySelector('#mhUrlGo').click(); }
    };
    if (q('#wdFlag')) q('#wdFlag').onclick = imp('flag', e.flag);
    if (q('#wdDecal')) q('#wdDecal').onclick = imp('decal', e.roundel);
    q('#wdApply').onclick = async () => {
      const values = {}, ch = [];
      if (kind === 'city' && q('#wdPos') && q('#wdPos').checked) { values.vecPosition = `[${e.coords.lon.toFixed(4)}, ${e.coords.lat.toFixed(4)}, 0]`; ch.push(t('Coordenadas') + ' ' + values.vecPosition); }
      if (kind === 'city' && q('#wdPop') && q('#wdPop').checked) { values.nPopulation = String(e.population.value); ch.push(t('Población') + ' ' + fmt(e.population.value)); }
      if (!confirm(`${d.label} ← ${e.id}\n\n${ch.join('\n') || t('(solo la asociación)')}\n\n${t('Se anota en el changelog del regionpack; el escenario cambia al «Guardar».')}`)) return;
      await link(e.id);
      if (Object.keys(values).length) {
        const r = await api('/api/scen/update', { id: d.id, values });
        if (r.error) return msg(r.error);
        setDirty(r.dirty || (r.detail && r.detail.dirty));
      }
      q('#wdData').closest('dialog').close();
      await openObj(d.id); note(t('Datos de Wikidata aplicados. Falta «Guardar».'));
    };
  }

  const _renderObj = renderObj;
  renderObj = function (d) {
    const r = _renderObj.apply(this, arguments);
    try {
      if (!S.scen || !d || (d.type !== 'City' && d.type !== 'MECountry')) return r;
      const kind = d.type === 'City' ? 'city' : 'country';
      const sec = document.createElement('div'); sec.className = 'sec';
      sec.innerHTML = `<h3>Wikidata</h3><div class="row"><button class="btn small" id="wdOpen">Wikidata…</button><span class="muted" id="wdCur"></span></div>`;
      document.getElementById('right').appendChild(sec);
      sec.querySelector('#wdOpen').onclick = () => open(d, kind);
      links().then(L => { const x = L[kind + ':' + d.label]; if (x) sec.querySelector('#wdCur').textContent = `${x.id} · ${x.label}${x.surrendered ? ' · surrendered' : ''}`; }).catch(() => {});
    } catch (e) { console.error(e); }
    return r;
  };
})();
