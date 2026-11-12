"""Export and import regions between scenarios (several at once), with their cities and resources and, if requested, their units.

Package (dict, saved as .json): {'kind': 'mh-regions', 'scenario', 'regions': [xml of each Region with its City/Producer],
'units': [xml of each Army/AirForce/Fleet whose strRegion is one of them]}.
When importing into another scenario:
- the region must exist in it (the map defines it): it gets the source region's data (owner, controller, population,
  culture, terrain, infrastructure…) and moves to its new owner's file;
- source countries that do not exist in the target are assigned to an existing one (mapping);
- cities, resources and units are not duplicated: if an equal one exists (same name; resource: same name and type;
  unit: same type, name and region) it is updated instead of adding another.
Everything stays in memory until «Guardar».
"""
import copy
import xml.etree.ElementTree as ET

import scenario_core as sc
from scenario_core import prop, objs

UNIT_TYPES = ('Army', 'AirForce', 'Fleet')
KEEP = ('strName',)          # region properties that are not copied


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
    """What would happen on import: regions that exist or not in the target, missing countries and duplicates."""
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
    """Imports the package into scenario 's' (in memory). mapping: {source country: target country} for the missing ones."""
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
        # region data (owner and controller translated); the owner change moves it to its country's file
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
                if old is not None:          # already there: replaced (not duplicated)
                    idx = list(t).index(old)
                    st.remove(old)
                    st.attach(new, t, index=idx)
                    n_upd += 1
                else:
                    st.attach(new, t)
                    n_add += 1
    n_u_add = n_u_upd = 0
    if units:
        # same unit = same type, name and region (even if its owner changes on import): replaced, not duplicated
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
                st.attach(new, owner, index=idx if same else None)      # in its owner's file
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
