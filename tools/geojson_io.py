"""Exportar e importar un escenario como GeoJSON (coordenadas del juego = longitud/latitud).

Capas (una FeatureCollection por archivo, cada objeto lleva "mh_type" para poder reimportarlo):
  regiones_tierra.geojson   land_region   regiones_mar.geojson  sea_region (MultiPolygon de la malla del regionpack)
  borders.geojson           border (líneas entre regiones vecinas)
  ciudades.geojson          city
  minerales.geojson         producer (o recursos_<Recurso>.geojson, uno por recurso)
  unidades.geojson          army / air_force / fleet
  changelog_comparado.json  regiones del mapa frente a World;  naciones.json  dueño y población por región

Importar: ciudades, productores y unidades se emparejan por nombre (y dueño); se mueven a la región que contiene
el punto, se actualizan sus propiedades y los que no existen se crean. Los objetos sin "mh_type" se devuelven para que el
usuario elija qué son. Las regiones actualizan dueño, controlador, terreno, cultura y población por nombre; una región que
no existe en el mapa se debe crear en el editor de mapa (Importar GeoJSON como región nueva).
"""
import copy
import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

import scenario_core as sc
from transfer import SEA
from scenario_core import prop, objs

TYPES = {'land_region': 'Región de tierra', 'sea_region': 'Región de mar', 'city': 'Ciudad', 'producer': 'Productor de recursos',
         'army': 'Ejército', 'air_force': 'Fuerza aérea', 'fleet': 'Flota'}
XML_TYPE = {'city': 'City', 'producer': 'Producer', 'army': 'Army', 'air_force': 'AirForce', 'fleet': 'Fleet'}
SKIP = {'vecPosition'}


def _pos(e):
    m = [float(x) for x in (prop(e, 'vecPosition') or '').strip('[]').split(',') if x.strip()]
    return m if len(m) >= 2 else None


def _props(e):
    return {p.get('name'): p.get('value') for p in e if p.tag == 'property' and p.get('name') not in SKIP}


def _fc(features):
    return {'type': 'FeatureCollection', 'features': features}


ALL_FILES = ('regiones_tierra', 'regiones_mar', 'borders', 'ciudades', 'unidades', 'minerales', 'changelog', 'naciones')
NEEDS_SCEN = {'ciudades', 'unidades', 'minerales', 'naciones'}
ALIAS = {'strOwner': 'owner', 'strController': 'controller', 'strTerrain': 'terrain', 'strCulture': 'culture', 'nPopulation': 'population'}


def _region_features(s, project, sea, colors=False):
    P = prop
    data = {P(r, 'strName'): r for r in s.regions()} if s is not None else {}
    if colors:
        import terrain_colors
        terr = terrain_colors.terrain_of(project, s)
    out = []
    for g in project.m['regions']:
        if (g.u_type == SEA) != sea:
            continue
        main = project.outline(g.index)[0]
        if not main:
            continue
        name = project.rname(g.index)
        r = data.get(name)
        props = {'mh_type': 'sea_region' if sea else 'land_region', 'name': name, 'map_name': g.name,
                 'center': [g.cx, g.cy], 'neighbors': sorted({project.rname(n) for n in g.neighbors if n != g.index})}
        if r is not None:
            for k, v in _props(r).items():
                if k == 'strName':
                    continue
                props[k] = v
                if k in ALIAS:
                    props[ALIAS[k]] = int(v) if k == 'nPopulation' and str(v).isdigit() else v
        if colors:     # tipo de terreno y su color (mar en celeste); los huecos sin región van en blanco en la leyenda
            props['terrain'] = terr.get(name)
            props['color'] = terrain_colors.color_of(terr.get(name))
        out.append({'type': 'Feature', 'geometry': {'type': 'MultiPolygon', 'coordinates': main}, 'properties': props})
    return out


def export(s, project, sel=None, minerals_split=False, base='World', lang='es', scen_name=None, colors=False):
    """{nombre de archivo: FeatureCollection o dict}. sel: conjunto de ALL_FILES a incluir (por defecto, todo lo posible; sin
    escenario (s=None) se omiten los que lo necesitan)."""
    import geojson_compare as gc
    P = prop
    sel = set(sel) if sel is not None else set(ALL_FILES)
    if s is None:
        sel -= NEEDS_SCEN
    out = {}
    if 'regiones_tierra' in sel:
        out['regiones_tierra.geojson'] = _fc(_region_features(s, project, False, colors))
    if 'regiones_mar' in sel:
        out['regiones_mar.geojson'] = _fc(_region_features(s, project, True, colors))
    if colors:
        import terrain_colors
        out['leyenda_terreno.json'] = terrain_colors.legend()
    if 'borders' in sel:
        out['borders.geojson'] = gc.borders(project)
    if 'changelog' in sel:
        out['changelog_comparado.json'] = gc.compare_with_base(project, base, lang)
    if s is None:
        return out
    st = s.s

    def point(e, t, extra=None):
        xy = _pos(e)
        if not xy:
            return None
        p = {'mh_type': t, 'name': P(e, 'strName')}
        p.update(_props(e))
        if 'strOwner' in p:
            p['owner'] = p['strOwner']
        p.update(extra or {})
        return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': xy[:2]}, 'properties': p}
    if 'ciudades' in sel:
        cities = [point(c, 'city', {'region': P(st.parent.get(c), 'strName'),
                                    'factory_ipus': next((P(f, 'nIPUs') for f in objs(c) if f.get('type') == 'Factory'), None)})
                  for c in s.all('City')]
        out['ciudades.geojson'] = _fc([f for f in cities if f])
    if 'minerales' in sel:
        by_res = {}
        for p in s.all('Producer'):
            f = point(p, 'producer', {'region': P(st.parent.get(p), 'strName')})
            if f:
                by_res.setdefault(P(p, 'strResource') or 'Otro', []).append(f)
        if minerals_split:
            for res, fs in sorted(by_res.items()):
                out['recursos_%s.geojson' % re.sub(r'[^A-Za-z0-9]+', '_', res)] = _fc(fs)
        else:
            out['minerales.geojson'] = _fc([f for res in sorted(by_res) for f in by_res[res]])
    if 'unidades' in sel:
        fs = []
        for xml_t, t in (('Army', 'army'), ('AirForce', 'air_force'), ('Fleet', 'fleet')):
            for e in s.all(xml_t):
                units = [{'unit': P(u, 'strName'), 'number': P(u, 'nNumber')} for u in objs(e) if u.get('type') == 'UnitSummary']
                f = point(e, t, {'units': units})
                if f:
                    fs.append(f)
        out['unidades.geojson'] = _fc(fs)
    if 'naciones' in sel:
        out['naciones.json'] = gc.nations(s, project, scen_name or '', lang)
    return out


def export_zip(s, project, sel=None, minerals_split=False, base='World', lang='es', scen_name=None, colors=False):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, fc in export(s, project, sel, minerals_split, base, lang, scen_name, colors).items():
            z.writestr(name, json.dumps(fc, ensure_ascii=False, indent=1 if name.endswith('.json') else None))
    return buf.getvalue()


# ---------------------------------------------------------------------------------------- importar
class RegionIndex:
    def __init__(self, project):
        self.names, geoms = [], []
        for g in project.m['regions']:
            main = project.outline(g.index)[0]
            if main:
                try:
                    geoms.append(shape({'type': 'MultiPolygon', 'coordinates': main}).buffer(0))
                    self.names.append((project.rname(g.index), g.u_type == SEA))
                except Exception:
                    pass
        self.geoms = geoms
        self.tree = STRtree(geoms)

    def at(self, x, y, sea=None):
        pt = Point(x, y)
        for i in self.tree.query(pt):
            name, is_sea = self.names[int(i)]
            if (sea is None or is_sea == sea) and self.geoms[int(i)].covers(pt):
                return name
        return None


def _set_pos(st, e, xy):
    old = _pos(e) or [0, 0, 0]
    z = old[2] if len(old) > 2 else 0
    st.set_prop(e, 'vecPosition', '[%s, %s, %s]' % (repr(float(xy[0])), repr(float(xy[1])), z))


def _apply_props(s, e, props, allowed):
    vals = {}
    for k, v in props.items():
        if k in allowed and v is not None and not isinstance(v, (dict, list)):
            vals[k] = str(v).lower() if isinstance(v, bool) else str(v)
    return s.update(s.s.eid(e), vals) if vals else []


DUP_DIST = {'city': 0.08, 'producer': 0.10, 'army': 0.20, 'air_force': 0.20, 'fleet': 0.20}     # grados (≈ 9 – 22 km)
OWNER_KEYS = ('strOwner', 'owner', 'country', 'pais', 'país')


def _analyze(s, idx, feats, types, land, owners):
    """Por cada punto del GeoJSON: tipo, nombre, posición, región donde cae y dueño. Dueño de ciudades y recursos: el de la región;
    de ejércitos y aviación: el del GeoJSON o, si no lo dice, el de la región de tierra donde llegan; de flotas: el del GeoJSON o el
    que elija el usuario (owners). Devuelve ({indice: info}, [flotas sin dueño])."""
    P = prop
    info, need = {}, []
    for i, f in enumerate(feats):
        p = f.get('properties') or {}
        t = p.get('mh_type') or types.get(i)
        g = f.get('geometry') or {}
        if t not in ('city', 'producer', 'army', 'air_force', 'fleet') or g.get('type') != 'Point':
            continue
        x, y = g['coordinates'][:2]
        sea = t == 'fleet'
        reg = idx.at(x, y, sea=sea)
        given = next((str(p[k]) for k in OWNER_KEYS if p.get(k)), None)
        if t in ('city', 'producer'):
            owner = P(land[reg], 'strOwner') if reg in land else None
        elif t in ('army', 'air_force'):
            owner = given or (P(land[reg], 'strOwner') if reg in land else None)
        else:
            owner = given or owners.get(i)
        info[i] = {'type': t, 'name': p.get('name') or p.get('strName') or '', 'x': x, 'y': y, 'region': reg, 'owner': owner,
                   'resource': p.get('strResource'), 'units': p.get('units')}
        if t == 'fleet' and not owner and reg:
            need.append({'index': i, 'name': info[i]['name'], 'region': reg})
    return info, need


def _comp(units):
    return sorted((str(u.get('unit') or u.get('strName')), str(u.get('number') or u.get('nNumber') or 1)) for u in units or []
                  if isinstance(u, dict))


def _duplicates(s, info):
    """Puntos que parecen repetir algo que ya existe en el escenario (o a otro punto del mismo archivo): mismo tipo, muy cerca
    (ciudades y recursos: otro nombre a menos de ~9 km; unidades: del mismo país, cerca o en la misma región y con la misma
    composición). Un objeto con el mismo nombre no cuenta: ese se actualiza."""
    P = prop
    st = s.s
    pool = {'city': [], 'producer': [], 'army': [], 'air_force': [], 'fleet': []}
    for t, xml_t in (('city', 'City'), ('producer', 'Producer'), ('army', 'Army'), ('air_force', 'AirForce'), ('fleet', 'Fleet')):
        for e in s.all(xml_t):
            xy = _pos(e)
            comp = _comp([{'unit': P(u, 'strName'), 'number': P(u, 'nNumber')} for u in objs(e) if u.get('type') == 'UnitSummary'])
            where = P(st.parent.get(e), 'strName') if t in ('city', 'producer') else P(e, 'strRegion')
            pool[t].append({'name': P(e, 'strName') or '', 'xy': xy, 'owner': P(e, 'strOwner'), 'region': where,
                            'resource': P(e, 'strResource'), 'comp': comp, 'from': 'escenario', 'el': e})
    out = []
    for i in sorted(info):
        a = info[i]
        t = a['type']
        for b in pool[t]:
            same_name = b['name'] and b['name'] == a['name'] and (t in ('city', 'producer') or b['owner'] == a['owner'])
            if same_name:
                continue
            if t == 'producer' and b['resource'] != a['resource']:
                continue
            if t in ('army', 'air_force', 'fleet') and b['owner'] != a['owner']:
                continue
            d = ((a['x'] - b['xy'][0]) ** 2 + (a['y'] - b['xy'][1]) ** 2) ** 0.5 if b['xy'] else None
            near = d is not None and d <= DUP_DIST[t]
            same_set = t in ('army', 'air_force', 'fleet') and b['region'] == a['region'] and a['units'] and b['comp'] == _comp(a['units'])
            if near or same_set:
                out.append({'index': i, 'type': t, 'name': a['name'], 'region': a['region'], 'owner': a['owner'],
                            'near': {'name': b['name'], 'region': b['region'], 'owner': b['owner'], 'distance': None if d is None else round(d, 4),
                                     'from': b['from']}, 'replaceable': True, '_el': b['el']})
                break
        else:
            for j in sorted(info):                      # repetido dentro del mismo archivo (se compara con los anteriores)
                if j >= i:
                    break
                b = info[j]
                if b['type'] != t or (b['name'] and b['name'] == a['name']) or (t == 'producer' and b['resource'] != a['resource']):
                    continue
                if t in ('army', 'air_force', 'fleet') and b['owner'] != a['owner']:
                    continue
                d = ((a['x'] - b['x']) ** 2 + (a['y'] - b['y']) ** 2) ** 0.5
                if d <= DUP_DIST[t]:
                    out.append({'index': i, 'type': t, 'name': a['name'], 'region': a['region'], 'owner': a['owner'],
                                'near': {'name': b['name'], 'region': b['region'], 'owner': b['owner'], 'distance': round(d, 4), 'from': 'el mismo archivo (#%d)' % j}, 'replaceable': False})
                    break
    return out


def import_fc(s, project, fc, types=None, index=None, opts=None):
    """fc: FeatureCollection. types: {indice de feature: mh_type} para los que no lo traen.
    opts: {'owners': {indice: país} (flotas sin país en el GeoJSON), 'dup': 'ask' | 'import' | 'skip', 'decisions': {indice: 'import'|'skip'}}.
    Devuelve {'needs_type': [...]}, {'needs_owner': [...]}, {'duplicates': [...]} si hace falta una decisión del usuario
    (no se cambia nada hasta tenerlas), o {'notes': [...], 'counts': {...}}."""
    opts = opts or {}
    types = {int(k): v for k, v in (types or {}).items()}
    feats = fc.get('features') or []
    missing = []
    for i, f in enumerate(feats):
        t = (f.get('properties') or {}).get('mh_type') or types.get(i)
        if t not in TYPES:
            missing.append({'index': i, 'geometry': (f.get('geometry') or {}).get('type'),
                            'properties': {k: v for k, v in list((f.get('properties') or {}).items())[:8]}})
    if missing:
        return {'needs_type': missing, 'types': TYPES}
    st = s.s
    P = prop
    idx = index or RegionIndex(project)
    land = {P(r, 'strName'): r for r in s.regions(sea=False)}
    countries = s.countries()
    owners = {int(k): v for k, v in (opts.get('owners') or {}).items()}
    info, need = _analyze(s, idx, feats, types, land, owners)
    if need:
        return {'needs_owner': need, 'countries': sorted(countries)}
    skip, decisions = set(), {int(k): v for k, v in (opts.get('decisions') or {}).items()}
    dups = _duplicates(s, info)
    mode = opts.get('dup') or 'ask'
    replace = {}                  # indice -> objeto existente que se sustituye por el del GeoJSON
    if dups and mode == 'skip':
        skip = {d['index'] for d in dups}
    elif dups and mode == 'replace':
        replace = {d['index']: d['_el'] for d in dups if d['replaceable']}
    elif dups and mode == 'ask':
        if any(d['index'] not in decisions for d in dups):
            return {'duplicates': [{k: v for k, v in d.items() if k != '_el'} for d in dups]}
        skip = {d['index'] for d in dups if decisions.get(d['index']) == 'skip'}
        replace = {d['index']: d['_el'] for d in dups if decisions.get(d['index']) == 'replace' and d['replaceable']}
    notes, counts = [], {}
    if skip:
        notes.append('%d posible(s) duplicado(s) no importado(s): %s' % (len(skip), ', '.join(sorted({info[i]['name'] or '(sin nombre)' for i in skip}))))
    if replace:
        notes.append('%d duplicado(s) reemplazado(s): %s' % (len(replace), ', '.join(sorted({info[i]['name'] or '(sin nombre)' for i in replace}))))
    templates = {t: (s.all(x) or [None])[0] for t, x in XML_TYPE.items()}
    for i, f in enumerate(feats):
        p = dict(f.get('properties') or {})
        t = p.get('mh_type') or types[i]
        geom = f.get('geometry') or {}
        name = p.get('name') or p.get('strName')
        if i in skip:
            continue
        counts[t] = counts.get(t, 0) + 1
        if t in ('land_region', 'sea_region'):
            r = land.get(name) if t == 'land_region' else next((x for x in s.regions(sea=True) if P(x, 'strName') == name), None)
            if r is None:
                notes.append('región «%s»: no existe en el escenario; créala en el editor de mapa (importar GeoJSON como región)' % name)
                continue
            notes += ['%s: %s' % (name, n) for n in _apply_props(s, r, p, {'strOwner', 'strController', 'strTerrain', 'strCulture',
                                                                         'nPopulation', 'nTransInfrastructure', 'nFortification', 'nAgriculture'})]
            continue
        if geom.get('type') != 'Point':
            notes.append('%s «%s»: se esperaba un punto' % (TYPES[t], name))
            continue
        x, y = geom['coordinates'][:2]
        xml_t = XML_TYPE[t]
        if t in ('city', 'producer'):
            reg_name = idx.at(x, y, sea=False)
            if reg_name not in land:
                notes.append('%s «%s»: el punto no cae en una región de tierra con datos' % (TYPES[t], name))
                continue
            cands = [replace[i]] if i in replace else                 [e for e in s.all(xml_t) if P(e, 'strName') == name and (t == 'city' or P(e, 'strResource') == p.get('strResource'))]
            if cands:
                e = cands[0]
                if i in replace and name:
                    st.set_prop(e, 'strName', name)
                if P(st.parent[e], 'strName') != reg_name:
                    s.update(st.eid(e), {'__region': reg_name})
                    notes.append('%s se mueve a %s' % (name, reg_name))
            else:
                tpl = templates[t]
                if tpl is None:
                    notes.append('%s «%s»: no hay ninguno en el escenario para usar de modelo' % (TYPES[t], name))
                    continue
                e = copy.deepcopy(tpl)
                for c in [c for c in e if c.tag == 'object' and c.get('type') != 'Factory']:
                    e.remove(c)
                reg = land[reg_name]
                st.attach(e, reg)
                st.set_prop(e, 'strName', name or ('Nueva ciudad' if t == 'city' else 'Nuevo productor'))
                for k in ('strOwner', 'strController'):
                    st.set_prop(e, k, P(reg, k))
                for q in [q for q in e if q.tag == 'property' and q.get('name') in ('sidName', 'strPortForRegion')]:
                    e.remove(q)
                notes.append('creado %s «%s» en %s' % (TYPES[t].lower(), name, reg_name))
            _set_pos(st, e, (x, y))
            allowed = {'strOwner', 'strController', 'strPortForRegion', 'strInitialWorkOrder', 'nDirection'} if t == 'city' else \
                {'strResource', 'nBaseOutputRate', 'strOwner', 'strController'}
            notes += ['%s: %s' % (name, n) for n in _apply_props(s, e, p, allowed)]
            if t == 'city' and p.get('factory_ipus') not in (None, ''):
                fct = next((c for c in objs(e) if c.get('type') == 'Factory'), None)
                if fct is not None:
                    st.set_prop(fct, 'nIPUs', str(p['factory_ipus']))
            continue
        # unidades
        sea = t == 'fleet'
        reg_name = idx.at(x, y, sea=sea)
        owner = (info.get(i) or {}).get('owner') or p.get('strOwner')
        if not reg_name:
            notes.append('%s «%s»: el punto no cae en una región de %s' % (TYPES[t], name, 'mar' if sea else 'tierra'))
            continue
        if owner not in countries:
            notes.append('%s «%s»: el país «%s» no existe' % (TYPES[t], name, owner))
            continue
        cands = [replace[i]] if i in replace else [e for e in s.all(xml_t) if P(e, 'strName') == name and P(e, 'strOwner') == owner]
        if cands:
            e = cands[0]
            if i in replace and name:
                st.set_prop(e, 'strName', name)
        else:
            tpl = templates[t]
            e = copy.deepcopy(tpl) if tpl is not None else ET.Element('object', {'type': xml_t, 'name': 'objGOs'})
            for c in [c for c in e if c.tag == 'object']:
                e.remove(c)
            dst = countries[owner]
            st.attach(e, dst, path=st.doc_of[dst])
            st.set_prop(e, 'strName', name or xml_t)
            st.set_prop(e, 'strOwner', owner)
            notes.append('creado %s «%s» (%s) en %s' % (TYPES[t].lower(), name, owner, reg_name))
        st.set_prop(e, 'strRegion', reg_name)
        _set_pos(st, e, (x, y))
        if isinstance(p.get('units'), list):
            for c in [c for c in e if c.tag == 'object' and c.get('type') == 'UnitSummary']:
                st.remove(c)
            for u in p['units']:
                us = ET.Element('object', {'type': 'UnitSummary', 'name': 'objUnits'})
                ET.SubElement(us, 'property', {'name': 'strName', 'value': str(u.get('unit') or u.get('strName'))})
                ET.SubElement(us, 'property', {'name': 'nNumber', 'value': str(u.get('number') or u.get('nNumber') or 1)})
                st.attach(us, e)
    s._opts = None
    return {'notes': notes, 'counts': counts}
