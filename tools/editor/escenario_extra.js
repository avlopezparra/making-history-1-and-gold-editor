// Extras del editor de escenarios sacados de ed.exe (docs_texto/editor_oficial/COMPARACION.md):
// botón «Editar» en la lista de errores, aviso de datos compartidos y recursos de los flujos comerciales y de ayuda.
(() => {
  // lista de errores: cada problema con objeto lleva «Editar», que abre su ficha (como el botón Edit de ed.exe)
  const list = document.getElementById('vallist');
  if (list) {
    new MutationObserver(() => {
      list.querySelectorAll('.issue[data-id]').forEach(div => {
        if (!div.dataset.id || div.querySelector('[data-editobj]')) return;
        div.insertAdjacentHTML('beforeend', ` <button class="btn small" data-editobj="${div.dataset.id}">Editar</button>`);
      });
    }).observe(list, { childList: true });
    list.addEventListener('click', e => {
      const b = e.target.closest('[data-editobj]'); if (!b) return;
      valDlg.close(); openObj(+b.dataset.editobj);
    });
  }

  // nación rendida que recibe una región sin ciudad: deja de estar rendida pero no tiene capital; preguntar en el momento
  const NOCITY = /AVISO: (.+?) no tiene ninguna ciudad en su territorio \((.+?)\)/;
  let asking = false;
  const ask = async (owner, region) => {
    if (asking) return; asking = true;
    try {
      const name = prompt(`${owner} ya no está rendido, pero no tiene ninguna ciudad para su capital (sin ella no se puede liberar).\n\n` +
        `Escribe el nombre de una ciudad nueva en ${region} para que sea su capital, o cancela y asígnale una región que tenga ciudad.`);
      if (!name || !name.trim()) return;
      const r = await api('/api/scen/create', { name: S.scen, kind: 'city', obj_name: name.trim(), region, owner, capital: true });
      if (r.error) return alert(r.error);
      const t = await api('/api/scen/tabs?name=' + encodeURIComponent(S.scen)); setDirty(t.dirty);
      alert(`Ciudad ${name.trim()} creada en ${region}: capital de ${owner}. Falta «Guardar».`);
    } finally { asking = false; }
  };
  const realFetch = window.fetch;
  window.fetch = async (...a) => {
    const res = await realFetch(...a);
    if (String(a[0]).startsWith('/api/scen/') && (res.headers.get('content-type') || '').includes('json'))
      res.clone().text().then(t => { const m = NOCITY.exec(t); if (m) setTimeout(() => ask(JSON.parse('"' + m[1] + '"'), JSON.parse('"' + m[2] + '"')), 300); }).catch(() => {});
    return res;
  };

  const base = renderObj;
  renderObj = function (d, note) {
    base(d, note);
    const right = document.getElementById('right');
    if (d.extra && d.extra.shared)
      right.insertAdjacentHTML('afterbegin', `<div class="note err">Datos compartidos (${esc(d.file)}): el cambio afecta a todo el escenario y a los que usen el mismo archivo. Al guardar queda una copia en backup/historial/.</div>`);
    if (d.type !== 'Flow') return;
    const res = (S.opts && S.opts.strResource) || [];
    right.insertAdjacentHTML('beforeend', `<div class="sec"><b>Recursos del flujo</b>
      <div class="hint muted">Cantidad 0 o vacía quita el recurso.</div>
      <div class="row"><select id="frRes">${res.map(r => `<option>${esc(r)}</option>`).join('')}</select>
      <input id="frAmt" type="number" min="0" placeholder="cantidad" style="width:8em">
      <button class="btn small primary" id="frGo">Aplicar</button></div></div>`);
    document.getElementById('frGo').onclick = async () => {
      const r = await api('/api/scen/flow_resource', { id: d.id, resource: document.getElementById('frRes').value, amount: document.getElementById('frAmt').value });
      if (r.error) return alert(r.error);
      setDirty(r.detail.dirty); S.obj = r.detail;
      renderObj(r.detail, { text: (r.notes.join('; ') || 'sin cambios') + '. Falta «Guardar».' });
    };
  };
})();
