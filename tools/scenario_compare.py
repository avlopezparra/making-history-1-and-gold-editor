"""Comparador de escenarios: diferencias entre dos escenarios (también Gold ↔ MH1) y traspaso de elementos.

El escenario «origen» se abre en un almacén aparte, solo para leer. El «destino» es el escenario abierto en el editor:
lo traspasado queda en memoria hasta que el usuario pulsa Guardar.
"""
import copy
import os
import re

import gamepaths
import scenario_core as sc
import scenario_layers
from scenario_core import prop, objs, norm

NEAR = 0.25          # grados: dos ciudades a menos de esto se tratan como la misma (≈ 25 km)
FORCES = ('Army', 'Fleet', 'AirForce')
EVENT_TYPES = ('ScriptedEventDef', 'PlayerDecisionDef', 'PlayerDecisionTrigPlayEvent', 'DecisionPointDef', 'WarPlan')
_SOURCES = {}        # carpeta -> Scenario (almacén propio, solo lectura)


def sources():
    """Escenarios que se pueden usar como origen: los del juego actual y los del otro juego si está instalado."""
    out = []
    seen = set()
    roots = [(gamepaths.CURRENT[0], sc.SCEN_ROOT)]
    for g in gamepaths.info()['games']:
        if g['installed'] and g['key'] != gamepaths.CURRENT[0]:
            roots.append((g['key'], gamepaths.scen_root(g['key'])))
    for key, root in roots:
        if not root or not os.path.isdir(root):
            continue
        for n in sorted(os.listdir(root)):
            d = os.path.abspath(os.path.join(root, n))
            if os.path.exists(os.path.join(d, 'gamestate.xml')) and os.path.normcase(d) not in seen:
                seen.add(os.path.normcase(d))
                out.append({'game': key, 'short': gamepaths.GAMES[key]['short'], 'name': n, 'dir': d})
    return out


def open_source(d):
    d = os.path.abspath(d)
    if not os.path.exists(os.path.join(d, 'gamestate.xml')):
        raise ValueError('no es un escenario: %s' % d)
    if d not in _SOURCES:
        s = sc.Scenario(d, store=sc.Store())          # nombre absoluto: os.path.join(SCEN_ROOT, d) == d
        scenario_layers.attach_external(s)
        _SOURCES[d] = s
    return _SOURCES[d]


def forget_source(d=None):
    if d is None:
        _SOURCES.clear()
    else:
        _SOURCES.pop(os.path.abspath(d), None)


def _xy(el):
    v = sc.parse_vec(prop(el, 'vecPosition'))
    return (v[0], v[1]) if v else None


def _ipus(c):
    f = next((o for o in objs(c) if o.get('type') == 'Factory'), None)
    return prop(f, 'nIPUs') if f is not None else None


def _units(g):
    return {prop(u, 'strName'): prop(u, 'nNumber') for u in objs(g) if u.get('type') == 'UnitSummary'}


def _city_key(s, c):
    return '%s|%s' % (prop(s.s.parent.get(c), 'strName'), prop(c, 'strName'))


def _force_key(g, k):
    return '%s|%s|%s|%d' % (g.get('type'), prop(g, 'strOwner'), prop(g, 'strName'), k)


def _event_key(e):
    return '%s|%s' % (e.get('type'), prop(e, 'strTypeLabel') or prop(e, 'strName') or '')


def _forces(s):
    out = []
    for t in FORCES:
        for k, g in enumerate(s.all(t)):
            out.append((_force_key(g, k), g))
    return out


def _match_city(tgt_cities, c, xy):
    """Ciudad del destino que es «la misma»: por nombre o por cercanía."""
    n = norm(prop(c, 'strName'))
    for t in tgt_cities:
        if norm(prop(t, 'strName')) == n:
            return t, 'nombre'
    if xy:
        best = None
        for t in tgt_cities:
            p = _xy(t)
            if p and abs(p[0] - xy[0]) < NEAR and abs(p[1] - xy[1]) < NEAR:
                d = (p[0] - xy[0]) ** 2 + (p[1] - xy[1]) ** 2
                if best is None or d < best[0]:
                    best = (d, t)
        if best:
            return best[1], 'cercanía'
    return None, None


# ---------------------------------------------------------------------------------------- diferencias
def diff(tgt, src):
    P = prop
    out = {'target': tgt.name, 'source': src.name}
    tc, scn = tgt.countries(), src.countries()
    has_land = lambda c: any(o.get('type') == 'Region' for o in objs(c))
    out['nations'] = {'only_source': sorted(set(scn) - set(tc)), 'only_target': sorted(set(tc) - set(scn)),
                      'both': len(set(tc) & set(scn)),
                      'land_diff': sorted(n for n in set(tc) & set(scn) if has_land(tc[n]) != has_land(scn[n]))}
    # ciudades
    tcities = tgt.all('City')
    treg = {P(r, 'strName') for r in tgt.regions()}
    cities = []
    for c in src.all('City'):
        xy = _xy(c)
        m, how = _match_city(tcities, c, xy)
        reg = P(src.s.parent.get(c), 'strName')
        sid = P(c, 'sidName')
        row = {'key': _city_key(src, c), 'name': P(c, 'strName'), 'region': reg, 'owner': P(c, 'strOwner'),
               'ipus': _ipus(c), 'pos': list(xy) if xy else None, 'text': src.strings.get(sid) if sid else None,
               'region_ok': reg in treg}
        if m is None:
            row['status'] = 'nueva'
        else:
            row.update(match=P(m, 'strName'), how=how, t_owner=P(m, 'strOwner'), t_ipus=_ipus(m))
            row['status'] = 'igual' if (row['ipus'], row['owner']) == (row['t_ipus'], row['t_owner']) else 'distinta'
        cities.append(row)
    out['cities'] = cities
    out['cities_only_target'] = sorted(P(c, 'strName') for c in tcities
                                       if _match_city(src.all('City'), c, _xy(c))[0] is None)
    # fuerzas militares
    templates = {P(t, 'strName') for t in tgt.all('UnitTemplate')}
    tforces = {}
    for _, g in _forces(tgt):
        tforces.setdefault((g.get('type'), P(g, 'strOwner'), P(g, 'strName')), g)
    forces = []
    for key, g in _forces(src):
        u = _units(g)
        m = tforces.get((g.get('type'), P(g, 'strOwner'), P(g, 'strName')))
        row = {'key': key, 'kind': g.get('type'), 'name': P(g, 'strName'), 'owner': P(g, 'strOwner'), 'region': P(g, 'strRegion'),
               'units': u, 'owner_ok': P(g, 'strOwner') in tc, 'region_ok': P(g, 'strRegion') in treg,
               'unknown': sorted(x for x in u if templates and x not in templates)}
        if m is None:
            row['status'] = 'nueva'
        else:
            row['status'] = 'igual' if (_units(m), P(m, 'strRegion')) == (u, row['region']) else 'distinta'
            row['t_region'], row['t_units'] = P(m, 'strRegion'), _units(m)
        forces.append(row)
    out['forces'] = forces
    # eventos
    tev = {_event_key(e) for e in tgt.all_types(EVENT_TYPES)}
    out['events'] = [{'key': _event_key(e), 'type': e.get('type'), 'label': P(e, 'strTypeLabel') or P(e, 'strName') or '',
                      'file': os.path.basename(src.s.doc_of[e]), 'status': 'igual' if _event_key(e) in tev else 'nueva'}
                     for e in src.all_types(EVENT_TYPES)]
    out['events_only_target'] = sorted(k for k in tev - {_event_key(e) for e in src.all_types(EVENT_TYPES)})
    # regiones y dueños
    tl = {P(r, 'strName'): r for r in tgt.regions(sea=False)}
    sl = {P(r, 'strName'): r for r in src.regions(sea=False)}
    regions = []
    for n in sorted(set(tl) & set(sl)):
        a, b = tl[n], sl[n]
        if (P(a, 'strOwner'), P(a, 'strController')) != (P(b, 'strOwner'), P(b, 'strController')):
            regions.append({'key': n, 'region': n, 'owner': P(b, 'strOwner'), 'controller': P(b, 'strController'),
                            't_owner': P(a, 'strOwner'), 't_controller': P(a, 'strController'),
                            'ok': P(b, 'strOwner') in tc and P(b, 'strController') in tc})
    out['regions'] = regions
    out['regions_only_source'] = sorted(set(sl) - set(tl))
    out['regions_only_target'] = sorted(set(tl) - set(sl))
    # diplomacia (relaciones iniciales) entre países de los dos
    tm, sm = scenario_layers._dip_map(tgt), scenario_layers._dip_map(src)
    dip = []
    for (a, b), (_, v) in sorted(sm.items()):
        if a in tc and b in tc and a < b:
            tv = tm.get((a, b), (None, None))[1]
            if tv != v:
                dip.append({'key': '%s|%s' % (a, b), 'a': a, 'b': b, 'value': v, 't_value': tv})
    out['diplomacy'] = dip
    # alianzas y guerras (solo informativo)
    names = lambda s, t, k: sorted({P(e, k) or '' for e in s.all(t)})
    out['alliances'] = {'only_source': sorted(set(names(src, 'Alliance', 'strDisplayName')) - set(names(tgt, 'Alliance', 'strDisplayName'))),
                        'only_target': sorted(set(names(tgt, 'Alliance', 'strDisplayName')) - set(names(src, 'Alliance', 'strDisplayName')))}
    war = lambda s: {'%s → %s' % (P(w, 'strINITAttackerCountryName'), P(w, 'strINITDefenderCountryName')) for w in s.all('War')}
    out['wars'] = {'only_source': sorted(war(src) - war(tgt)), 'only_target': sorted(war(tgt) - war(src))}
    return out


# ---------------------------------------------------------------------------------------- traspaso
def _copy_strings(tgt, src, el, notes):
    """Textos SID del elemento: si el destino no los tiene, se copian a su game/stringTable.xml."""
    n = 0
    for p in el.iter('property'):
        v = p.get('value') or ''
        if v.startswith('SID.') and v not in tgt.strings and src.strings.get(v) is not None:
            sc.set_region_string(tgt, v, src.strings[v])
            n += 1
    return n


def transfer(tgt, src, items):
    """items: {'cities': [claves], 'forces': [...], 'events': [...], 'regions': [...], 'diplomacy': [...]}. En memoria."""
    P = prop
    st = tgt.s
    notes, skipped = [], []
    nstr = 0
    countries = tgt.countries()
    # ciudades: dentro de la región del mismo nombre (o la que contiene el punto) y del dueño de esa región
    want = set(items.get('cities') or [])
    if want:
        land = {P(r, 'strName'): r for r in tgt.regions(sea=False)}
        seas = {P(r, 'strName') for r in tgt.regions(sea=True)}
        n = 0
        for c in src.all('City'):
            if _city_key(src, c) not in want:
                continue
            name = P(c, 'strName')
            xy = _xy(c)
            m, how = _match_city(tgt.all('City'), c, xy)
            if m is not None:
                skipped.append('ciudad %s: ya existe en el destino (%s, por %s)' % (name, P(m, 'strName'), how))
                continue
            reg = land.get(P(src.s.parent.get(c), 'strName'))
            if reg is None and xy:
                try:
                    reg = scenario_layers._land_region_at(tgt, *xy)[0]
                except Exception:
                    reg = None
            if reg is None:
                skipped.append('ciudad %s: su región %s no existe en el destino' % (name, P(src.s.parent.get(c), 'strName')))
                continue
            el = copy.deepcopy(c)
            for k in ('strOwner', 'strController'):
                st_val = P(reg, k)
                for p in el:
                    if p.tag == 'property' and p.get('name') == k:
                        p.set('value', st_val)
            port = P(el, 'strPortForRegion')
            if port and port not in seas:
                for p in list(el):
                    if p.tag == 'property' and p.get('name') == 'strPortForRegion':
                        el.remove(p)
                notes.append('aviso: ciudad %s sin puerto (el mar %s no existe en el destino)' % (name, port))
            kids = list(reg)
            last = [i for i, x in enumerate(kids) if x.tag == 'object' and x.get('type') == 'City']
            st.attach(el, reg, path=st.doc_of[reg], index=(last[-1] + 1) if last else None)
            nstr += _copy_strings(tgt, src, el, notes)
            n += 1
        if n:
            notes.append('%d ciudad(es) copiadas al destino' % n)
    # fuerzas militares: al archivo del país dueño, sin unidades de plantillas desconocidas
    want = set(items.get('forces') or [])
    if want:
        templates = {P(t, 'strName') for t in tgt.all('UnitTemplate')}
        regions = {P(r, 'strName') for r in tgt.regions()}
        have = {(g.get('type'), P(g, 'strOwner'), P(g, 'strName')) for _, g in _forces(tgt)}
        n = 0
        for key, g in _forces(src):
            if key not in want:
                continue
            t, owner, name = g.get('type'), P(g, 'strOwner'), P(g, 'strName')
            if (t, owner, name) in have:
                skipped.append('%s %s de %s: ya existe con ese nombre' % (t, name, owner))
                continue
            if owner not in countries:
                skipped.append('%s %s: no existe el país %s en el destino' % (t, name, owner))
                continue
            if P(g, 'strRegion') not in regions:
                skipped.append('%s %s de %s: no existe la región %s en el destino' % (t, name, owner, P(g, 'strRegion')))
                continue
            el = copy.deepcopy(g)
            if templates:
                bad = [u for u in objs(el) if u.get('type') == 'UnitSummary' and P(u, 'strName') not in templates]
                for u in bad:
                    el.remove(u)
                if bad:
                    notes.append('aviso: %s %s sin %s (plantilla desconocida en el destino)' % (t, name, ', '.join(P(u, 'strName') for u in bad)))
                if not any(u.get('type') == 'UnitSummary' for u in objs(el)):
                    skipped.append('%s %s de %s: ninguna de sus unidades existe en el destino' % (t, name, owner))
                    continue
            kids = list(countries[owner])
            same = [i for i, x in enumerate(kids) if x.tag == 'object' and x.get('type') in FORCES]
            st.attach(el, countries[owner], path=st.doc_of[countries[owner]], index=(same[-1] + 1) if same else None)
            have.add((t, owner, name))
            nstr += _copy_strings(tgt, src, el, notes)
            n += 1
        if n:
            notes.append('%d fuerza(s) militar(es) copiadas' % n)
    # eventos: al sharedDataEvents.xml del destino
    want = set(items.get('events') or [])
    if want:
        have = {_event_key(e) for e in tgt.all_types(EVENT_TYPES)}
        path, extra = sc._events_doc(tgt)
        notes += extra
        root = st.docs[path].getroot()
        shared = next((o for o in root.iter('object') if o.get('type') == 'MESharedData'), root)
        n = 0
        for e in src.all_types(EVENT_TYPES):
            k = _event_key(e)
            if k not in want:
                continue
            if k in have:
                skipped.append('evento %s: ya existe' % k.split('|', 1)[1])
                continue
            el = copy.deepcopy(e)
            st.attach(el, shared, path=path)
            have.add(k)
            nstr += _copy_strings(tgt, src, el, notes)
            n += 1
        if n:
            notes.append('%d evento(s) copiados a sharedDataEvents.xml' % n)
    # dueño / controlador de regiones (mueve la región al archivo del país, como en el editor)
    want = set(items.get('regions') or [])
    if want:
        tl = {P(r, 'strName'): r for r in tgt.regions(sea=False)}
        sl = {P(r, 'strName'): r for r in src.regions(sea=False)}
        n = 0
        for name in sorted(want):
            a, b = tl.get(name), sl.get(name)
            if a is None or b is None:
                continue
            o, c = P(b, 'strOwner'), P(b, 'strController')
            if o not in countries or c not in countries:
                skipped.append('región %s: no existe %s en el destino' % (name, o if o not in countries else c))
                continue
            tgt.update(st.eid(a), {'strOwner': o, 'strController': c})
            n += 1
        if n:
            notes.append('%d región(es) con el dueño/controlador del origen' % n)
    # diplomacia: misma cifra en los dos sentidos
    want = set(items.get('diplomacy') or [])
    if want:
        sm = scenario_layers._dip_map(src)
        its = []
        for k in sorted(want):
            a, b = k.split('|', 1)
            v = sm.get((a, b), (None, None))[1]
            if v is not None and a in countries and b in countries and re.fullmatch(r'\d+', v or ''):
                its.append({'a': a, 'b': b, 'value': v})
        if its:
            scenario_layers.fix_diplomacy(tgt, its)
            notes.append('%d relación(es) diplomáticas copiadas' % len(its))
    if nstr:
        notes.append('%d texto(s) copiados a game/stringTable.xml' % nstr)
    tgt._opts = None
    return {'notes': notes, 'skipped': skipped}
