"""Making History saved games (.mlc): reading and conversion into a new version of the scenario.

Format (reverse engineered, see ESCENARIOS_NOTAS.md «Partidas guardadas»):
  fixed 0xA28-byte header (version, turn, time, 512-byte UTF-16 texts) + a zlib block with the game's
  objects serialized in binary: object = <marker u32> <type u32> <id u32> <no. of properties u32>, property =
  <id u32> <0 u32> <-1 i32> <value>. Type/property numbers are those of this engine version: types are
  recognized by their content (city names, unit templates...) and not assumed fixed.

The original saves are never modified: only read.
"""
import os
import re
import shutil
import struct
import zlib
from collections import Counter, defaultdict

SAVES_ROOT = os.path.join(os.environ.get('PROGRAMDATA', r'C:\ProgramData'), 'Muzzy Lane Software', 'Output Files', 'Saves')
HEADER_SIZE = 0xA28
_TEXTS = (('nombre', 0x18), ('perfil', 0x218), ('paquete', 0x418), ('escenario', 0x618), ('guardada', 0x818))

_OBJ = re.compile(rb'(?=([\x02\x06])\x00\x00\x00(..)\x00\x00(....)([\x01-\xff])\x00\x00\x00(.)\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff)', re.S)
_PROP = re.compile(rb'(.)\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff', re.S)


def list_saves(root=None):
    """Saves of all players: [{player, file, path, size, date, scenario, turn}]."""
    root = root or SAVES_ROOT
    out = []
    if not os.path.isdir(root):
        return out
    for dirpath, _, files in os.walk(root):
        for f in files:
            if not f.lower().endswith('.mlc'):
                continue
            p = os.path.join(dirpath, f)
            item = {'player': os.path.relpath(dirpath, root) if dirpath != root else '', 'file': f, 'path': p,
                    'size': os.path.getsize(p), 'mtime': os.path.getmtime(p)}
            try:
                h = read_header(p)
                item.update(scenario=h['escenario'], turn=h['turno'], saved=h['guardada'])
            except (OSError, ValueError):
                item['error'] = 'no se pudo leer la cabecera'
            out.append(item)
    out.sort(key=lambda x: -x['mtime'])
    return out


def read_header(path):
    with open(path, 'rb') as f:
        h = f.read(HEADER_SIZE)
    if len(h) < HEADER_SIZE:
        raise ValueError('archivo demasiado corto')
    ver, turn, turn2 = struct.unpack_from('<III', h, 0)
    ms = struct.unpack_from('<Q', h, 0x10)[0]
    out = {'version': ver, 'turno': turn, 'turno2': turn2, 'hora_ms': ms}
    for k, off in _TEXTS:
        raw = h[off:off + 512]
        n = next((i for i in range(0, 512, 2) if raw[i:i + 2] == b'\0\0'), 512)
        out[k] = raw[:n].decode('utf-16le', 'replace')
    out['tam_comprimido'] = struct.unpack_from('<I', h, 0xA18)[0]
    return out


def read_body(path):
    with open(path, 'rb') as f:
        f.seek(HEADER_SIZE)
        return zlib.decompress(f.read())


class SaveData:
    """Game objects the editor cares about (read by patterns; types are recognized by their content)."""

    def __init__(self, path, cities=(), templates=None, regions=()):
        """cities: scenario city names; templates: {template: eType}; regions: region names."""
        self.path = path
        self.header = read_header(path)
        self.d = read_body(path)
        self._objs = []
        for m in _OBJ.finditer(self.d):
            t = struct.unpack('<H', m.group(2))[0]
            self._objs.append((m.start(), t, m.group(4)[0]))
        self._decode(set(cities), templates or {}, set(regions))

    # ------------------------------------------------------------ bajo nivel
    def props(self, off, n):
        """{property id: value bytes}; the value runs up to the next property's header (the last, 64 bytes)."""
        d = self.d
        p = off + 16
        pid = d[p]
        p += 12
        out = {}
        for i in range(n):
            if i == n - 1:
                out[pid] = d[p:p + 64]
                break
            m = next((mm for mm in _PROP.finditer(d, p, p + 4096) if mm.group(1)[0] > pid), None)
            if m is None:
                out[pid] = d[p:p + 64]
                break
            out[pid] = d[p:m.start()]
            pid, p = m.group(1)[0], m.end()
        return out

    @staticmethod
    def s(b):
        if b is None or len(b) < 4:
            return None
        n = struct.unpack_from('<I', b)[0]
        if 0 < n < 400 and len(b) >= 4 + 2 * n:
            try:
                return b[4:4 + 2 * n].decode('utf-16le')
            except UnicodeDecodeError:
                return None
        return None

    @staticmethod
    def i(b):
        return struct.unpack_from('<i', b)[0] if b is not None and len(b) >= 4 else None

    @staticmethod
    def vec(b):
        return struct.unpack_from('<3f', b) if b is not None and len(b) >= 12 else None

    # ------------------------------------------------------------ interpretation
    def _decode(self, cities, templates, region_names):
        S, I, V = self.s, self.i, self.vec
        named = []          # (off, type, props) of objects with name (p1), owner (p2) and position (p14)
        by_type = defaultdict(list)
        for off, t, n in self._objs:
            by_type[t].append((off, n))
        # regions: p0 internal index, p1 name, p2/p3 owner/controller, p14 map index
        self.regions = {}
        self.map_index = {}
        # cities: type whose p1 matches the most scenario cities
        votes = Counter()
        cache = {}
        for off, t, n in self._objs:
            if n < 3:
                continue
            pr = self.props(off, n)
            cache[off] = pr
            name = S(pr.get(1))
            if name is None:
                continue
            if name in cities and V(pr.get(14)) and len(pr.get(14) or b'') == 12:
                votes[t] += 1
            if name in region_names and len(S(pr.get(16)) or '') >= 3 and len(pr.get(14) or b'') == 4:
                votes[('R', t)] += 1
        self.city_type = max((k for k in votes if not isinstance(k, tuple)), key=lambda k: votes[k], default=None)
        rtypes = {k[1] for k in votes if isinstance(k, tuple) and votes[k] >= 3}
        # unit templates: type (with many properties) whose p0 is a template name
        uvotes = Counter()
        for off, t, n in self._objs:
            if n >= 8 and S(cache.get(off, {}).get(0)) in templates:
                uvotes[t] += 1
        self.unit_type = uvotes.most_common(1)[0][0] if uvotes else None
        self.cities, self.forces = [], []
        self.factory_type = None
        cur_city = None
        cur_force = None
        fac_votes = Counter()
        for off, t, n in self._objs:
            pr = cache.get(off)
            if pr is None:
                continue
            if t in rtypes:
                name = S(pr.get(1))
                if name and len(S(pr.get(16)) or '') >= 3 and len(pr.get(14) or b'') == 4:
                    rec = {'name': name, 'owner': S(pr.get(2)), 'controller': S(pr.get(3)), 'index': I(pr.get(0)),
                           'map': I(pr.get(14)), 'sea': S(pr.get(16)) == 'Water', 'population': I(pr.get(22))}
                    self.regions.setdefault(name, rec)
                    if rec['map'] is not None:
                        self.map_index.setdefault(rec['map'], name)
                cur_city = cur_force = None
                continue
            if t == self.city_type:
                cur_city = {'name': S(pr.get(1)), 'owner': S(pr.get(2)), 'controller': S(pr.get(3)),
                            'pos': V(pr.get(14)), 'map': I(pr.get(15)), 'ipus': None, 'tech': None}
                self.cities.append(cur_city)
                cur_force = None
                continue
            if cur_city is not None and cur_city['ipus'] is None and n <= 6 and S(pr.get(0)) is None and 0 in pr and 1 in pr \
                    and (self.factory_type is None or t == self.factory_type):
                v = I(pr.get(0))
                if v is not None and 0 <= v < 100000:
                    cur_city['ipus'] = v
                    if 2 in pr and len(pr[2]) == 4:
                        cur_city['tech'] = I(pr[2])
                    fac_votes[t] += 1
                    if sum(fac_votes.values()) >= 20 and self.factory_type is None:
                        self.factory_type = fac_votes.most_common(1)[0][0]
                    cur_city = None
                continue
            if t == self.unit_type and cur_force is not None:
                tn = S(pr.get(0))
                k = I(pr.get(12)) if len(pr.get(12) or b'') >= 4 else None
                if tn:
                    cur_force['units'][tn] += k if k and 0 < k < 10000 else 1     # stack: p12 = number of units
                continue
            name, owner, pos = S(pr.get(1)), S(pr.get(2)), pr.get(14)
            if name and owner and pos is not None and len(pos) == 12 and 15 in pr and t != self.city_type and n >= 20:
                cur_force = {'name': name, 'owner': owner, 'pos': V(pos), 'map': I(pr.get(15)), 'type_id': t, 'units': Counter()}
                self.forces.append(cur_force)
                cur_city = None
        # force type: by the templates of its units (UNIT_TYPE_NAVY / UNIT_TYPE_AIR_FORCE / army)
        kind_votes = defaultdict(Counter)
        for f in self.forces:
            for u, k in f['units'].items():
                e = templates.get(u) or ''
                kind_votes[f['type_id']]['Fleet' if 'NAVY' in e else 'AirForce' if 'AIR' in e else 'Army'] += k
        kinds = {t: c.most_common(1)[0][0] for t, c in kind_votes.items() if c}
        self.forces = [f for f in self.forces if f['units'] and f['type_id'] in kinds]
        city_map = [(c['pos'], c['map']) for c in self.cities if c['pos'] and c['map'] in self.map_index]
        for f in self.forces:
            f['kind'] = kinds[f['type_id']]
            f['region'] = self.map_index.get(f['map'])
            if f['region'] is None and f['pos'] and city_map:
                # in port (index -1): the region of the nearest city
                (x, y, _), m = min(city_map, key=lambda c: (c[0][0] - f['pos'][0]) ** 2 + (c[0][1] - f['pos'][1]) ** 2)
                if (x - f['pos'][0]) ** 2 + (y - f['pos'][1]) ** 2 < 1.0:
                    f['region'] = self.map_index[m]
                    f['port'] = True
            f['units'] = dict(f['units'])

    def summary(self):
        owners = Counter(r['owner'] for r in self.regions.values() if not r['sea'] and r['owner'])
        return {'header': self.header, 'regions': len([r for r in self.regions.values() if not r['sea']]),
                'cities': len(self.cities), 'forces': Counter(f['kind'] for f in self.forces),
                'countries_with_land': sorted(owners)}


# ---------------------------------------------------------------------------------------- new scenario
def _scenario_facts(s):
    """What is needed from the scenario to recognize the save."""
    from scenario_core import prop
    cities = [prop(c, 'strName') for c in s.all('City')]
    templates = {prop(t, 'strName'): prop(t, 'eType') or '' for t in s.all('UnitTemplate')}
    if not templates:     # templates in the game's ScenarioDefaults (test copies without that folder)
        import glob
        import scenario_core as sc
        for f in glob.glob(os.path.join(sc.GAME, 'Modern Europe', 'system', 'scenarios', 'ScenarioDefaults', '*.xml')):
            try:
                for t in sc.parse(f).getroot().iter('object'):
                    if t.get('type') == 'UnitTemplate':
                        templates.setdefault(prop(t, 'strName'), prop(t, 'eType') or '')
            except Exception:
                pass
    regions = [prop(r, 'strName') for r in s.regions()]
    return cities, templates, regions


def _pack_names(s):
    """Regions of the scenario's regionpack and those its changelog removed: so they are recognized in old saves."""
    import scenario_core as sc
    import scenario_layers
    try:
        pm = scenario_layers.PackMap(sc.pack_of(s))
    except (ValueError, OSError, TypeError):
        return None, set()
    gone = {n for n, _ in _deleted(pm)}
    return pm, set(pm.idx) | gone


def _deleted(pm):
    """[(removed region, the one that absorbed it)] from the changelog (keys in English or Spanish, depending on the version)."""
    out = []
    for e in pm.changelog:
        for x in e.get('deleted_regions') or e.get('regiones_eliminadas') or []:
            n = x.get('name') or x.get('nombre')
            if n:
                out.append((n, x.get('absorbed_by') or x.get('absorbida_por')))
    return out


def load_for(s, path):
    cities, templates, regions = _scenario_facts(s)
    _, extra = _pack_names(s)
    return SaveData(path, cities, templates, set(regions) | extra)


def pack_report(s, save):
    """Does the save fit the scenario's current regionpack? The game validates by name and also stores the number
    of each map region: if a region was removed or added, the numbers of the following ones change and the save does not load.
    'alias': save region that no longer exists -> region that absorbed it (changelog «delete_region»)."""
    import scenario_core as sc
    pm, _ = _pack_names(s)
    if pm is None:
        return {'pack': sc.pack_of(s), 'status': 'sin_mapa', 'missing': [], 'added': [], 'shifted': [], 'alias': {}}
    absorbed = {n: a for n, a in _deleted(pm) if a}
    skip = {'BasicRegionLists', 'Historic'}
    missing = sorted(n for n in save.regions if n not in pm.idx)
    added = sorted(n for n in pm.idx if n not in save.regions and n not in skip)
    shifted = sorted(n for n, r in save.regions.items() if n in pm.idx and r['map'] is not None and pm.idx[n] != r['map'])
    alias = {}
    for n in missing:
        a, seen = absorbed.get(n), {n}
        while a and a not in pm.idx and a in absorbed and a not in seen:      # absorbed by another that was later removed too
            seen.add(a)
            a = absorbed[a]
        if a and a in pm.idx:
            alias[n] = a
    status = 'ok' if not (missing or added or shifted) else ('nombres' if not shifted and len(missing) == len(added) else 'incompatible')
    return {'pack': pm.pack, 'status': status, 'missing': missing, 'added': added, 'shifted': shifted, 'alias': alias}


def plan(s, save, opts=None):
    """Differences between scenario 's' and the save: [{kind, ...}] (changes nothing)."""
    from scenario_core import prop
    opts = opts or {}
    P = prop
    out = {'owners': [], 'cities': [], 'forces_old': 0, 'forces_new': [], 'gone': [], 'missing_countries': [], 'notes': []}
    countries = s.countries()
    land = {P(r, 'strName'): r for r in s.regions(sea=False)}
    for name, r in sorted(save.regions.items()):
        if r['sea'] or name not in land:
            continue
        e = land[name]
        if (r['owner'], r['controller']) != (P(e, 'strOwner'), P(e, 'strController')):
            ok = r['owner'] in countries and r['controller'] in countries
            out['owners'].append({'region': name, 'from': [P(e, 'strOwner'), P(e, 'strController')],
                                  'to': [r['owner'], r['controller']], 'ok': ok})
            for c in (r['owner'], r['controller']):
                if c not in countries and c not in out['missing_countries']:
                    out['missing_countries'].append(c)
    cities = {P(c, 'strName'): c for c in s.all('City')}
    for c in save.cities:
        e = cities.get(c['name'])
        if e is None or c['ipus'] is None:
            continue
        fac = next((o for o in e if o.tag == 'object' and o.get('type') == 'Factory'), None)
        old = P(fac, 'nIPUs') if fac is not None else None
        if str(c['ipus']) != (old or ''):
            out['cities'].append({'city': c['name'], 'from': old, 'to': c['ipus']})
    out['forces_old'] = sum(len(s.all(t)) for t in ('Army', 'AirForce', 'Fleet'))
    templates = {P(t, 'strName') for t in s.all('UnitTemplate')}
    regions = {P(r, 'strName') for r in s.regions()}
    alias = opts.get('alias') or {}
    for f in save.forces:
        if f['region'] in alias:            # region removed from the regionpack: the one that absorbed it
            f = dict(f, region=alias[f['region']])
        bad = [u for u in f['units'] if u not in templates]
        out['forces_new'].append({'kind': f['kind'], 'name': f['name'], 'owner': f['owner'], 'region': f['region'],
                                  'pos': [round(f['pos'][0], 4), round(f['pos'][1], 4)], 'units': f['units'],
                                  'ok': f['owner'] in countries and f['region'] in regions and not bad,
                                  'why': ('país inexistente ' if f['owner'] not in countries else '') +
                                         ('región desconocida ' if f['region'] not in regions else '') +
                                         ('unidades desconocidas: %s' % ', '.join(bad) if bad else '')})
    owned = {r['owner'] for r in save.regions.values() if not r['sea']}
    out['gone'] = sorted(n for n, c in countries.items() if any(o.get('type') == 'Region' for o in c) and n not in owned)
    return out


def apply(s, save, pl, owners=True, ipus=True, forces=True):
    """Aplica el plan a 's' (en memoria). Devuelve notas."""
    import xml.etree.ElementTree as ET
    import scenario_core as sc
    from scenario_core import prop, objs
    P = prop
    st = s.s
    notes = []
    if owners:
        land = {P(r, 'strName'): r for r in s.regions(sea=False)}
        n = 0
        for o in pl['owners']:
            if not o['ok']:
                continue
            r = land[o['region']]
            s.update(st.eid(r), {'strOwner': o['to'][0], 'strController': o['to'][1]})
            n += 1
        if n:
            notes.append('%d región(es) cambian de dueño o controlador' % n)
        skipped = [o['region'] for o in pl['owners'] if not o['ok']]
        if skipped:
            notes.append('aviso: %d región(es) sin cambiar porque su nuevo dueño no existe en el escenario (%s)'
                         % (len(skipped), ', '.join(pl['missing_countries'])))
    if ipus:
        cities = {P(c, 'strName'): c for c in s.all('City')}
        for c in pl['cities']:
            e = cities[c['city']]
            fac = next((o for o in objs(e) if o.get('type') == 'Factory'), None)
            if fac is None:
                fac = ET.Element('object', {'type': 'Factory', 'name': 'objFactory'})
                st.attach(fac, e)
            st.set_prop(fac, 'nIPUs', str(c['to']))
        if pl['cities']:
            notes.append('%d ciudad(es) con IPUs de la partida' % len(pl['cities']))
    if forces:
        # the scenario's forces are removed and the save's are put in (with their position)
        old = [g for t in ('Army', 'AirForce', 'Fleet') for g in s.all(t)]
        for g in old:
            st.remove(g)
        countries = s.countries()
        seas = {P(r, 'strName') for r in s.regions(sea=True)}
        made = 0
        for f in pl['forces_new']:
            if not f['ok']:
                continue
            region, port = f['region'], None
            if f['kind'] == 'Fleet' and region not in seas:
                # docked fleet: the game expects the region's port city (strCity); if that region has no port,
                # the port nearest its position
                reg = next((r for r in s.regions(sea=False) if P(r, 'strName') == region), None)
                port = next((c for c in objs(reg) if c.get('type') == 'City' and P(c, 'strPortForRegion')), None) if reg is not None else None
                if port is None:
                    ports = [c for c in s.all('City') if P(c, 'strPortForRegion') and sc.parse_vec(P(c, 'vecPosition'))]
                    if ports:
                        x, y = f['pos'][:2]
                        port = min(ports, key=lambda c: (sc.parse_vec(P(c, 'vecPosition'))[0] - x) ** 2 + (sc.parse_vec(P(c, 'vecPosition'))[1] - y) ** 2)
                        region = P(st.parent[port], 'strName')
            el = ET.Element('object', {'type': f['kind'], 'name': 'objGOs'})
            for k, v in (('strName', f['name']), ('strOwner', f['owner']),
                         ('vecPosition', '[%r, %r, 0]' % (float(f['pos'][0]), float(f['pos'][1]))), ('strRegion', region)):
                ET.SubElement(el, 'property', {'name': k, 'value': v})
            if port is not None:
                ET.SubElement(el, 'property', {'name': 'strCity', 'value': P(port, 'strName')})
            for u, k in sorted(f['units'].items()):
                o = ET.SubElement(el, 'object', {'type': 'UnitSummary', 'name': 'objUnits'})
                ET.SubElement(o, 'property', {'name': 'strName', 'value': u})
                ET.SubElement(o, 'property', {'name': 'nNumber', 'value': str(int(k))})
            country = countries[f['owner']]
            kids = list(country)
            same = [i for i, x in enumerate(kids) if x.tag == 'object' and x.get('type') in ('Army', 'AirForce', 'Fleet')]
            st.attach(el, country, index=(same[-1] + 1) if same else None)
            made += 1
        notes.append('%d fuerza(s) del escenario sustituidas por %d de la partida' % (len(old), made))
        bad = [f for f in pl['forces_new'] if not f['ok']]
        if bad:
            notes.append('aviso: %d fuerza(s) de la partida sin pasar (%s)' % (len(bad), '; '.join(
                '%s de %s: %s' % (f['name'], f['owner'], f['why'].strip()) for f in bad[:8])))
    return notes


def create_scenario(scen_root, base, save_path, new_name, owners=True, ipus=True, forces=True, adapt=True):
    """Copies scenario 'base' to <scen_root>/<new_name> and applies the save to it. Only writes the new folder.
    adapt: save regions the regionpack no longer has are translated via the changelog and the new scenario
    is adapted to the regionpack (like «Adecuar»), so the game loads it."""
    import scenario_core as sc
    import scenario_layers
    new_name = (new_name or '').strip()
    if not new_name or re.search(r'[\\/:*?"<>|]', new_name):
        raise ValueError('nombre de carpeta no válido')
    src = os.path.join(scen_root, base)
    dst = os.path.join(scen_root, new_name)
    if not os.path.isdir(src):
        raise ValueError('no existe el escenario %s' % base)
    if os.path.exists(dst):
        raise ValueError('ya existe la carpeta «%s»' % new_name)
    shutil.copytree(src, dst)
    try:
        st = sc.Store()
        s = sc.Scenario(dst, store=st)
        scenario_layers.attach_external(s)
        save = load_for(s, save_path)
        rep = pack_report(s, save) if adapt else {'alias': {}}
        pl = plan(s, save, {'alias': rep['alias']})
        notes = apply(s, save, pl, owners, ipus, forces)
        if rep['alias']:
            notes.append('regiones que ya no están en el regionpack: %s' % ', '.join('%s → %s' % kv for kv in sorted(rep['alias'].items())))
        if adapt and rep.get('pack'):
            missing, extra = scenario_layers.pack_mismatch(s, rep['pack'])
            if missing or extra:
                notes += scenario_layers.pack_sync_apply(s, rep['pack'], True)['notes']
        written = st.save([p for p in s.paths if p in st.dirty])['written']
        f = os.path.join(dst, 'scenario.xml')
        raw = open(f, 'rb').read().decode('utf-8')
        raw = re.sub(r'(name="strName" value=")[^"]*(")', lambda m: m.group(1) + new_name + m.group(2), raw, count=1)
        open(f, 'wb').write(raw.encode('utf-8'))
    except Exception:
        shutil.rmtree(dst, ignore_errors=True)
        raise
    return {'scenario': new_name, 'notes': notes, 'written': len(written)}
