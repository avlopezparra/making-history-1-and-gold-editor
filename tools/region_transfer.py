"""Exportar e importar regiones entre escenarios (varias a la vez), con sus ciudades y recursos y, si se pide, sus unidades.

Paquete (dict, se guarda como .json): {'kind': 'mh-regions', 'scenario', 'regions': [xml de cada Region con sus City/Producer],
'units': [xml de cada Army/AirForce/Fleet cuyo strRegion es una de ellas]}.
Al importar en otro escenario:
- la región tiene que existir en él (la define el mapa): se le ponen los datos de la de origen (dueño, controlador, población,
  cultura, terreno, infraestructura…) y pasa al archivo de su nuevo dueño;
- los países de origen que no existen en el destino se asignan a uno existente (mapping);
- ciudades, recursos y unidades no se duplican: si ya hay uno igual (mismo nombre; recurso: mismo nombre y tipo;
  unidad: mismo tipo, nombre y región) se actualiza en vez de añadir otro.
Todo queda en memoria hasta «Guardar».
"""
import copy
import xml.etree.ElementTree as ET

import scenario_core as sc
from scenario_core import prop, objs

UNIT_TYPES = ('Army', 'AirForce', 'Fleet')
KEEP = ('strName',)          # propiedades de la región que no se copian


def export_regions(s, names, units=True):
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    missing = [n for n in names if n not in land]
    if missing:
        raise ValueError('no son regiones de tierra del escenario: %s' % ', '.join(missing[:10]))
    regs = [ET.tostring(land[n], encoding='unicode') for n in names]
    us = [ET.tostring(u, encoding='unicode') for t in UNIT_TYPES for u in s.all(t) if prop(u, 'strRegion') in set(names)] if units else []
    return {'kind': 'mh-regions', 'version': 1, 'scenario': s.name, 'regions': regs, 'units': us}


def _bundle(s_src, names, units):
    return export_regions(s_src, names, units)


def _parse(bundle):
    if not isinstance(bundle, dict) or bundle.get('kind') != 'mh-regions':
        raise ValueError('no es un paquete de regiones del editor (.json exportado con «Exportar regiones»)')
    regs = [ET.fromstring(x) for x in bundle.get('regions') or []]
    us = [ET.fromstring(x) for x in bundle.get('units') or []]
    return regs, us


def _owners(regs, us):
    out = set()
    for r in regs:
        out |= {prop(r, 'strOwner'), prop(r, 'strController')}
        for c in objs(r):
            out |= {prop(c, 'strOwner'), prop(c, 'strController')}
    out |= {prop(u, 'strOwner') for u in us}
    return sorted(x for x in out if x)


def plan(s, bundle):
    """Qué pasaría al importar: regiones que existen o no en el destino, países que faltan y duplicados."""
    regs, us = _parse(bundle)
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    countries = set(s.countries())
    found = [prop(r, 'strName') for r in regs if prop(r, 'strName') in land]
    missing = [prop(r, 'strName') for r in regs if prop(r, 'strName') not in land]
    dups = {'cities': 0, 'producers': 0, 'units': 0}
    for r in regs:
        t = land.get(prop(r, 'strName'))
        if t is None:
            continue
        have = {(c.get('type'), prop(c, 'strName'), prop(c, 'strResource')) for c in objs(t)}
        for c in objs(r):
            if (c.get('type'), prop(c, 'strName'), prop(c, 'strResource')) in have:
                dups['cities' if c.get('type') == 'City' else 'producers'] += 1
    have_u = {(t, prop(u, 'strName'), prop(u, 'strRegion')) for t in UNIT_TYPES for u in s.all(t)}
    dups['units'] = sum(1 for u in us if (u.get('type'), prop(u, 'strName'), prop(u, 'strRegion')) in have_u)
    owners = [{'name': o, 'exists': o in countries} for o in _owners(regs, us)]
    return {'source': bundle.get('scenario'), 'regions': len(regs), 'found': found, 'missing': missing, 'units': len(us),
            'cities': sum(1 for r in regs for c in objs(r) if c.get('type') == 'City'),
            'producers': sum(1 for r in regs for c in objs(r) if c.get('type') == 'Producer'),
            'owners': owners, 'countries': sorted(countries), 'duplicates': dups}


def apply(s, bundle, mapping=None, cities=True, units=True):
    """Importa el paquete en el escenario 's' (en memoria). mapping: {país de origen: país del destino} para los que faltan."""
    st = s.s
    regs, us = _parse(bundle)
    countries = s.countries()
    mapping = dict(mapping or {})
    for o in _owners(regs, us):
        if o not in countries and mapping.get(o) not in countries:
            raise ValueError('el país «%s» no existe en este escenario: elige a qué país pasa' % o)
    M = lambda x: x if x in countries else mapping.get(x, x)
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    notes, n_reg, n_add, n_upd, skipped = [], 0, 0, 0, []
    for r in regs:
        name = prop(r, 'strName')
        t = land.get(name)
        if t is None:
            skipped.append(name)
            continue
        tid = st.eid(t)
        # datos de la región (dueño y controlador traducidos); el cambio de dueño la lleva al archivo de su país
        values = {}
        for p in r:
            if p.tag == 'property' and p.get('name') not in KEEP and p.get('value') is not None:
                v = p.get('value')
                values[p.get('name')] = M(v) if p.get('name') in ('strOwner', 'strController') else v
        s.update(tid, values)
        t = st.get(tid)
        n_reg += 1
        if cities:
            for c in objs(r):
                if c.get('type') not in ('City', 'Producer'):
                    continue
                key = (c.get('type'), prop(c, 'strName'), prop(c, 'strResource'))
                old = next((x for x in objs(t) if (x.get('type'), prop(x, 'strName'), prop(x, 'strResource')) == key), None)
                new = copy.deepcopy(c)
                for p in new.iter('property'):
                    if p.get('name') in ('strOwner', 'strController'):
                        p.set('value', M(p.get('value')))
                if old is not None:          # ya estaba: se reemplaza (no se duplica)
                    idx = list(t).index(old)
                    st.remove(old)
                    st.attach(new, t, index=idx)
                    n_upd += 1
                else:
                    st.attach(new, t)
                    n_add += 1
    n_u_add = n_u_upd = 0
    if units:
        # misma unidad = mismo tipo, nombre y región (aunque cambie de dueño al importarla): se reemplaza, no se duplica
        have = {(u.get('type'), prop(u, 'strName'), prop(u, 'strRegion')): u for t in UNIT_TYPES for u in s.all(t)}
        for u in us:
            if prop(u, 'strRegion') in skipped:
                continue
            new = copy.deepcopy(u)
            for p in new.iter('property'):
                if p.get('name') == 'strOwner':
                    p.set('value', M(p.get('value')))
            key = (new.get('type'), prop(new, 'strName'), prop(new, 'strRegion'))
            old = have.get(key)
            owner = countries.get(prop(new, 'strOwner'))
            if old is not None and owner is not None:
                par = st.parent[old]
                same = par is owner
                idx = list(par).index(old)
                st.remove(old)
                st.attach(new, owner, index=idx if same else None)      # en el archivo de su dueño
                n_u_upd += 1
            elif owner is not None:
                st.attach(new, owner)
                n_u_add += 1
    s._opts = None
    notes.append('%d región(es) importadas de «%s»' % (n_reg, bundle.get('scenario') or '?'))
    if cities:
        notes.append('ciudades y recursos: %d añadidos, %d actualizados (sin duplicar)' % (n_add, n_upd))
    if units:
        notes.append('unidades: %d añadidas, %d actualizadas (sin duplicar)' % (n_u_add, n_u_upd))
    if mapping:
        notes.append('países asignados: %s' % ', '.join('%s → %s' % kv for kv in sorted(mapping.items()) if kv[0] not in countries))
    if skipped:
        notes.append('AVISO: %d región(es) no existen en este escenario (su mapa no las tiene) y no se importan: %s' % (len(skipped), ', '.join(skipped[:15])))
    return notes
