// Scenario editor extras taken from ed.exe (docs_texto/editor_oficial/COMPARACION.md):
// «Editar» button in the error list, shared-data warning and trade/aid flow resources.
(() => {
  // error list: each problem with an object gets «Editar», which opens its sheet (like ed.exe's Edit button)
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

  // surrendered nation receiving a region without a city: stops being surrendered but has no capital; ask at that moment
  const NOCITY = /AVISO: (.+?) no tiene ninguna ciudad en su territorio \((.+?)\)/;
  let asking = false;
  const askedFor = new Set();      // once per country and region (the warning could come back in other responses and repeat the question)
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
    const isPost = String((a[1] && a[1].method) || 'GET').toUpperCase() === 'POST';     // only actions (change owner, transfer…), not reads
    if (isPost && String(a[0]).startsWith('/api/scen/') && (res.headers.get('content-type') || '').includes('json'))
      res.clone().text().then(t => {
        const m = NOCITY.exec(t); if (!m) return;
        const owner = JSON.parse('"' + m[1] + '"'), region = JSON.parse('"' + m[2] + '"'), k = owner + '|' + region;
        if (askedFor.has(k)) return; askedFor.add(k);
        setTimeout(() => ask(owner, region), 300);
      }).catch(() => {});
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
