"""Imports a Making History II scenario into a new MH1 scenario on WorldMoreRegions or WorldMoreRegionsRivers.

Both regionpacks were built from MH2's own map, so every MH2 land region has a region of the same name (the few extra
regions of the regionpack take the owner of their neighbours). From the MH2 scenario it takes, as far as MH1 has an
equivalent: nations (name, colour, government, culture, flag from MH2's flag images), region owner/controller,
population, terrain and culture, historic nations, cities (IPUs from their factories, port, capital), mineral resources
(coal, metals, oil), units (armies, fleets, air forces, with the template scenario's units of the same kind) and the
research those units need. Wars and alliances are copied when the MH2 scenario has them (gs_tbg.War / gs_tbg.Alliance);
trade agreements, diplomatic relation levels and MH2's own research topics have no MH1 equivalent and are left out
(the report says so).

The new scenario is written to the game's scenario folder (like «＋ Nuevo escenario»); nothing else is touched.
MH2 Workshop scenarios are their authors' work: converting them for one's own use is fine, publishing the result needs
their permission.
"""
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

import scenario_core as sc
from scenario_core import prop, objs

PACKS = ('WorldMoreRegions', 'WorldMoreRegionsRivers')
MH2_APP = '46770'
GOVS = ('Democratic', 'Authoritarian', 'Communist', 'Fascist')
TERRAIN = {'Forests': 'Forest', 'Lake': 'Plains', 'Ocean': 'Plains', 'PolarSea': 'Tundra'}     # the rest have the same name
RESOURCES = {'Coal': 'Coal', 'Metals': 'Metals', 'Oil': 'Oil'}
# MH2 city buildings -> MH1 IPUs (an MH1 city has one factory with a number of IPUs)
BUILDING_IPUS = {'CottageFactory': 2, 'MechanizedFactory': 6, 'MunitionsPlant': 4, 'AircraftPlant': 4, 'VehiclePlant': 4, 'Shipyard': 3}
# MH2 culture -> MH1 culture (the same name ignoring case and punctuation is matched without this table)
CULTURE = {'Slavic': 'Russian', 'Arabic': 'Arabian', 'Sinitic': 'Chinese', 'Lusitanic': 'Portuguese', 'Turkic': 'Turkish',
           'IndoIranian': 'Persian', 'Germanic': 'German', 'Francophonie': 'French', 'Latin': 'Italian', 'Hellenic': 'Greek',
           'Yamato': 'Japanese', 'AltaicKorean': 'Korean', 'Magyar': 'Hungarian', 'Finnic': 'Finnish', 'Balt': 'Lithuanian',
           'Balkan': 'Serbian', 'EgyptoArabic': 'Egyptian', 'Amazigh': 'Arab-Berber', 'MalayoIndonesian': 'Indonesian',
           'MalayoPolynesian': 'Filipino', 'PacificIslander': 'Polynesian', 'Tai': 'Thai', 'MonKhmer': 'Cambodian',
           'TibetoBurman': 'Burmese', 'Mongolic': 'Mongolian', 'AfroCaribbean': 'Caribbean', 'Eskimo': 'Greenlandic',
           'Cushitic': 'Somali', 'Nilotic': 'Afro-Arab', 'Saharan': 'Afro-Arab', 'NigerCongo': 'Yoruba', 'Khoisan': 'Bantu',
           'Aramaic': 'Iraqi', 'Algonquin': 'American'}
# keyword of the MH2 unit template -> kind and keywords of the MH1 template to use (most specific first; () = no equivalent)
UNIT_KINDS = [('Carrier', 'navy', ('Carrier',)), ('Submarine', 'navy', ('Submarine',)),
              ('Battlecruiser', 'navy', ('BattleCruiser', 'Battleship')), ('Battleship', 'navy', ('Battleship',)),
              ('Dreadnought', 'navy', ('Battleship',)), ('Cruiser', 'navy', ('Cruiser',)), ('Destroyer', 'navy', ('Destroyer',)),
              ('Frigate', 'navy', ('Destroyer', 'Corvette')), ('Corvette', 'navy', ('Corvette', 'Destroyer')),
              ('Troopship', 'navy', ()), ('Transport', 'navy', ()),
              ('Bomber', 'air', ('Bomber',)), ('Fighter', 'air', ('Fighter',)), ('Plane', 'air', ('Fighter',)), ('AirShip', 'air', ()),
              ('Tank', 'land', ('Tank',)), ('Artillery', 'land', ('Artillery',)), ('Militia', 'land', ('Militia', 'Infantry')),
              ('Mounted', 'land', ('Motorized', 'Mechanized', 'Cavalry')), ('Cavalry', 'land', ('Cavalry', 'Motorized')),
              ('Motorized', 'land', ('Motorized',)), ('Mechanized', 'land', ('Mechanized',)), ('Infantry', 'land', ('Infantry',)),
              ('Marine', 'land', ('Infantry',))]
UNIT_TYPE = {'land': 'UNIT_TYPE_ARMY', 'air': 'UNIT_TYPE_AIR_FORCE', 'navy': 'UNIT_TYPE_NAVY'}


def _key(n):
    return re.sub(r'[^a-z0-9]', '', (n or '').lower())


# ------------------------------------------------------------------------------------------------ finding MH2 scenarios
def mh2_roots():
    """[(source, folder)] holding MH2 scenarios: the game's modules/game and each Workshop item's modules/game."""
    import gamepaths
    out = []
    for common in gamepaths._steam_libraries():
        g = os.path.join(common, 'Making History II', 'content', 'Making History II', 'modules', 'game')
        if os.path.isdir(g):
            out.append(('MH2', g))
        ws = os.path.join(os.path.dirname(common), 'workshop', 'content', MH2_APP)
        if os.path.isdir(ws):
            for item in sorted(os.listdir(ws)):
                g = os.path.join(ws, item, 'modules', 'game')
                if os.path.isdir(g):
                    out.append(('Workshop %s' % item, g))
    return out


def _file(d, base):
    """MH2 scenario file: 'GameSysX.xml' in the official scenarios, 'objGameSysX.xml' in Workshop ones."""
    for f in ('obj' + base, base):
        if os.path.isfile(os.path.join(d, f)):
            return os.path.join(d, f)
    return None


def scenarios():
    """[{'name', 'source', 'path', 'date'}] of the installed MH2 scenarios (folders with regions and nations)."""
    out = []
    for src, root in mh2_roots():
        for n in sorted(os.listdir(root)):
            d = os.path.join(root, n)
            if _file(d, 'GameSysRegion.xml') and _file(d, 'GameSysNation.xml'):
                t = _file(d, 'GameSysTurnBasedGame.xml')
                m = re.search(r'dateCurrentDate" value="([^"]+)"', open(t, encoding='utf-8', errors='replace').read()) if t else None
                out.append({'name': n, 'source': src, 'path': d, 'date': m.group(1) if m else ''})
    return out


def check_source(path):
    """The MH2 scenario the page asks for must be one of the listed ones (no arbitrary paths)."""
    p = os.path.normcase(os.path.abspath(path or ''))
    for x in scenarios():
        if os.path.normcase(os.path.abspath(x['path'])) == p:
            return x['path']
    raise ValueError('no se encuentra el escenario de MH2 %s' % path)


def packs():
    """{'installed': [the usable regionpacks that are installed], 'needed': PACKS}."""
    import editor_core
    return {'installed': [p for p in PACKS if os.path.exists(os.path.join(editor_core.MAPS, p, 'xml', 'regions.bin'))], 'needed': list(PACKS)}


# ------------------------------------------------------------------------------------------------ reading MH2 XML
def _objects(path, typ):
    """[{'type', 'p': {property: [values]}, 'k': [child objects]}] of every object of type 'typ' (namespace-free)."""
    if not path:
        return []
    root = ET.parse(path).getroot()

    def conv(el):
        d = {'type': el.get('type'), 'p': defaultdict(list), 'k': []}
        for c in el:
            tag = c.tag.split('}')[-1]
            if tag == 'property':
                v = c.get('value')
                if v is None and c.get('from'):
                    v = '@' + c.get('from')        # locale reference, e.g. «@locale.SID.City.DisplayName.Aarhus»
                d['p'][c.get('name')].append(v)
            elif tag == 'object':
                d['k'].append(conv(c))
        return d
    return [conv(el) for el in root.iter() if el.tag.split('}')[-1] == 'object' and el.get('type') == typ]


def _p(o, k, default=None):
    v = o['p'].get(k) if o else None
    return v[0] if v else default


def _sd(v):
    return v.split('.', 1)[1] if (v or '').startswith('sd.') else (v or '')


def _display(v, fallback):
    """Literal visible name, or a readable one from a locale reference / internal name («NewYork» -> «New York»)."""
    if v and not v.startswith('@'):
        return v.replace('\t', ' ').strip()
    n = v.rsplit('.', 1)[-1] if v else (fallback or '')
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', n).strip()


def read(d):
    """Everything the converter uses from an MH2 scenario folder."""
    f = lambda b: _file(d, b)
    nations = {}
    for o in _objects(f('GameSysNation.xml'), 'gs_tbg.Nation'):
        n = _p(o, 'strName')
        ideo = _sd(_p(o, 'tmplIdeology'))
        nations[n] = {'display': _display(_p(o, 'strDisplayName'), _sd(_p(o, 'tmplNation')) or n), 'tmpl': _sd(_p(o, 'tmplNation')),
                      'nationality': _sd(_p(o, 'tmplNationality')), 'gov': ideo if ideo in GOVS else 'Authoritarian',
                      'color': (_p(o, 'colColor') or '')[:7]}
    regions = {}
    for o in _objects(f('GameSysRegion.xml'), 'gs_tbg.Region'):
        res = []
        for k in o['k']:
            if k['type'] == 'gs_tbg.ResourceCapacity' and _sd(_p(k, 'tmplResource')) in RESOURCES:
                res.append((_sd(_p(k, 'tmplResource')), int(_p(k, 'nImprovementSlots') or 0),
                            sum(1 for i in k['k'] if i['type'] == 'gs_tbg.ResourceImprovement')))
        regions[_p(o, 'strName')] = {'owner': _p(o, 'refOwner'), 'ctl': _p(o, 'refController'), 'pop': _p(o, 'nPopulation'),
                                    'terrain': _sd(_p(o, 'tmplTerrain')), 'culture': _sd(_p(o, 'tmplCulture')),
                                    'historic': [_sd(x) for x in o['p'].get('tmplHistoricNations', [])], 'resources': res,
                                    'display': _display(_p(o, 'strDisplayName'), _p(o, 'strName'))}
    cities, capitals = [], {}
    for o in _objects(f('GameSysCity.xml'), 'gs_tbg.City'):
        pos = re.findall(r'-?\d+(?:\.\d+)?(?:e-?\d+)?', _p(o, 'vecPosition') or '')
        ipus = sum(BUILDING_IPUS.get(_sd(_p(b, 'tmplCityBuilding')), 1) for b in o['k'] if b['type'] == 'gs_tbg.CityBuilding')
        cities.append({'name': _p(o, 'strName'), 'display': _display(_p(o, 'strDisplayName'), _p(o, 'strName')),
                       'region': _p(o, 'refRegion'), 'sea': _p(o, 'refSeaRegion'),
                       'xy': (float(pos[0]), float(pos[1])) if len(pos) >= 2 else None, 'ipus': max(1, ipus)})
    for o in _objects(f('GameSysCity.xml'), 'gs_tbg.CapitalCityNation'):
        capitals[_p(o, 'refNation')] = _p(o, 'refCapitalCity')
    groups = {}
    for o in _objects(f('GameSysUnit.xml'), 'gs_tbg.UnitGroup'):
        groups[_p(o, 'strName')] = {'name': _p(o, 'strName'), 'display': _display(_p(o, 'strDisplayName'), _p(o, 'strName')),
                                    'owner': _p(o, 'refController'), 'loc': (_p(o, 'refLocation') or '').split('::'), 'units': []}
    unit_group = {}
    for o in _objects(f('GameSysUnit.xml'), 'gs_tbg.Unit'):
        unit_group[_p(o, 'strName')] = _p(o, 'refUnitGroup')
        g = groups.get(_p(o, 'refUnitGroup'))
        if g is not None:
            g['units'].append(_sd(_p(o, 'objUnitTemplate')))
    city_region = {c['name']: c['region'] for c in cities}
    for g in groups.values():      # where it is: a region, a city (its region; 'city' = docked there) or aboard a unit
        kind, ref = (g['loc'] + [''])[:2] if len(g['loc']) > 1 else ('gs_tbg.Region', g['loc'][0])
        for _ in range(3):
            if kind == 'gs_tbg.Unit' and groups.get(unit_group.get(ref)):
                kind, ref = (groups[unit_group[ref]]['loc'] + [''])[:2]
        g['city'] = ref if kind == 'gs_tbg.City' else None
        g['region'] = city_region.get(ref) if kind == 'gs_tbg.City' else (ref if kind == 'gs_tbg.Region' else None)
    rel = f('GameSysNationRelations.xml')
    wars = [(_p(o, 'refAttacker') or _p(o, 'refNationA'), _p(o, 'refDefender') or _p(o, 'refNationB')) for o in _objects(rel, 'gs_tbg.War')]
    alliances = [(_p(o, 'strName') or 'Alliance', o['p'].get('refMembers') or o['p'].get('refNations') or []) for o in _objects(rel, 'gs_tbg.Alliance')]
    t = f('GameSysTurnBasedGame.xml')
    m = re.search(r'dateCurrentDate" value="(\d+)/(\d+)/(\d+)"', open(t, encoding='utf-8', errors='replace').read()) if t else None
    return {'nations': nations, 'regions': regions, 'cities': cities, 'capitals': capitals, 'groups': list(groups.values()),
            'wars': [w for w in wars if all(w)], 'alliances': alliances,
            'trade': len(_objects(f('GameSysTrade.xml'), 'gs_tbg.TradeAgreement')),
            'date': (int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else (2000, 1, 1)}


# ------------------------------------------------------------------------------------------------ building the MH1 scenario
def _safe(n):
    # also without «&»: game.xml holds it as «&amp;» and the editor would not match the file name
    return re.sub(r'\s+', ' ', re.sub(r'[\\/:*?"<>|]+', ' ', (n or '').replace('&', ' and '))).strip()


def _drop_template_events(d):
    """The template scenario's own shared data (its events, decisions...: they name its regions and nations) is not kept:
    only the game's standard shared files stay, in scenario.xml and on disk. Returns the removed files."""
    import scenario_new
    keep = set(scenario_new.BUILTIN_SHARED) | {'sharedDataHistoricCountries.xml', 'sharedDataPartisans.xml'}
    f = os.path.join(d, 'scenario.xml')
    raw = open(f, encoding='utf-8', newline='').read()
    gone = []

    def drop(m):
        n = re.search(r'name="fileSharedData" value="([^"]+)"', m.group(0))
        if n and n.group(1) not in keep:
            gone.append(n.group(1))
            return ''
        return m.group(0)
    raw = re.sub(r'[ \t]*<object type="SharedDataFileRef".*?</object>\r?\n', drop, raw, flags=re.S)
    open(f, 'w', encoding='utf-8', newline='').write(raw)
    for g in set(gone):
        if os.path.isfile(os.path.join(d, g)):
            os.remove(os.path.join(d, g))
    return sorted(set(gone))


def _culture(mh2, known):
    by_key = {_key(c): c for c in known}
    return by_key.get(_key(mh2)) or by_key.get(_key(CULTURE.get(mh2, ''))) if mh2 else None


def _template_usage(template):
    """{template name: units of it in the template scenario's armies, fleets and air forces}."""
    use = Counter()
    d = os.path.join(sc.SCEN_ROOT, template) if template else None
    if d and os.path.isdir(d):
        for f in os.listdir(d):
            if f.startswith('country') and f.endswith('.xml'):
                t = open(os.path.join(d, f), encoding='utf-8', errors='replace').read()
                for m in re.finditer(r'type="UnitSummary"[^>]*>\s*<property name="strName" value="([^"]+)"/>\s*<property name="nNumber" value="(\d+)"', t):
                    use[m.group(1)] += int(m.group(2))
    return use


def _templates(s, use):
    """{kind: [(template, times used in the template scenario)]} in file order."""
    out = {k: [] for k in UNIT_TYPE}
    for t in s.all('UnitTemplate'):
        n, e = prop(t, 'strName'), prop(t, 'eType')
        for k, et in UNIT_TYPE.items():
            if e == et:
                out[k].append((n, use.get(n, 0)))
    return out


def _unit_for(mh2_tmpl, tmpls):
    """(kind, MH1 template) for an MH2 unit template: same kind and keyword; among several, the most used in the scenario
    and, if none is used, the last defined (the most modern). (kind, None) if MH1 has nothing like it."""
    for word, kind, words in UNIT_KINDS:
        if word.lower() in mh2_tmpl.lower():
            order = [n for n, _ in tmpls[kind]]
            for w in words:
                c = [(n, u) for n, u in tmpls[kind] if w.lower() in n.lower()]
                if c:
                    return kind, max(c, key=lambda x: (x[1], order.index(x[0])))[0]
            return kind, None
    return None, None


def convert(src, pack, name, template=None, display=None, open_scenario=None, progress=None):
    """Creates scenario 'name' on regionpack 'pack' from the MH2 scenario folder 'src' and saves it.
    'template': MH1 scenario whose shared data (unit types, research, AI...) the new one copies; None: the editor's own (1936).
    Returns {'name', 'notes', 'warnings'}. On an error halfway the half-made folder is removed."""
    import shutil
    import scenario_new
    import scenario_layers as L
    if pack not in PACKS:
        raise ValueError('el importador de MH2 necesita el regionpack WorldMoreRegions o WorldMoreRegionsRivers (hechos con el mapa de MH2)')
    if pack not in packs()['installed']:
        raise ValueError('instala primero el regionpack %s: el importador de MH2 necesita WorldMoreRegions o WorldMoreRegionsRivers' % pack)
    pm = L.pack_map(pack)
    tick = progress or (lambda pct, msg: None)
    tick(2, 'Leyendo el escenario de MH2')
    data = read(src)
    y, mo, d = data['date']
    name = scenario_new.create_scenario(name, pack, template, display or name,
                                        'Convertido de Making History II (%s)' % os.path.basename(src.rstrip('\\/')), y, mo, d)
    try:
        notes, warns = ['escenario %s creado (%02d/%02d/%d, regionpack %s)' % (name, d, mo, y, pack)], []
        if template:
            gone = _drop_template_events(os.path.join(sc.SCEN_ROOT, name))
            if gone:
                notes.append('de la plantilla %s se copian las unidades, la investigación y la IA, no sus eventos (%s)' % (template, ', '.join(gone)))
        s = (open_scenario or sc.Scenario)(name)
        _build(s, data, pm, notes, warns, tick, _template_usage(template))
        tick(97, 'Guardando')
        s.s.save(scenario=s)
    except Exception:
        shutil.rmtree(os.path.join(sc.SCEN_ROOT, name), ignore_errors=True)
        raise
    return {'name': name, 'notes': notes, 'warnings': warns}


def _owners(land, src, nations, pm):
    """{region: (owner, controller)} (MH2 ids): from MH2; the regionpack's extra regions take their neighbours' owner."""
    owner = {n: (r['owner'], r['ctl'] if r.get('ctl') in nations else r['owner']) for n, r in src.items() if r and r.get('owner') in nations}
    for _ in range(3):
        for n in land:
            if n not in owner:
                c = Counter(owner[x][0] for x in pm.nb.get(n, []) if x in owner)
                if c:
                    o = c.most_common(1)[0][0]
                    owner[n] = (o, o)
    for n in land:          # islands with no owned neighbour: the nearest owned region
        g = pm.geom(n)
        if n not in owner and g is not None and owner:
            near = min((x for x in owner if pm.geom(x) is not None), key=lambda x: g.distance(pm.geom(x)))
            owner[n] = (owner[near][0], owner[near][0])
    return owner


def _build(s, data, pm, notes, warns, tick, use):
    import scenario_new
    import scenario_layers as L
    import scenario_create as C
    import tech_units
    N, R = data['nations'], data['regions']
    skip = {'BasicRegionLists', 'Historic'}
    land = [n for n, sea in pm.sea.items() if not sea and n not in skip]
    seas = [n for n, sea in pm.sea.items() if sea and n not in skip]
    land_set, by_key = set(land), {_key(n): n for n in list(land) + seas}
    mh2_of = {_key(n): n for n in R}
    src = {n: R.get(mh2_of.get(_key(n))) for n in land}
    nat, used = {}, set()          # MH2 id -> MH1 name: its visible name, unique and valid as a file name
    for k, v in sorted(N.items(), key=lambda kv: kv[1]['display']):
        n = _safe(v['display']) or _safe(k)
        while n.lower() in used:
            n += ' (%s)' % k
        used.add(n.lower())
        nat[k] = n
    owner = _owners(land, src, N, pm)
    present = {o for o, _ in owner.values()}
    cult_known = [prop(c, 'strName') for c in s.all('CultureTemplate') if prop(c, 'strName')]
    log = {x['nombre']: x for e in pm.changelog for x in e.get('regiones_nuevas', [])}
    texts = {t['region']: t['texto'] for e in pm.changelog for t in e.get('textos', []) if t.get('region') and t.get('texto')}    # visible names with spaces

    tick(5, 'Creando las naciones')
    for k in sorted(present, key=lambda k: nat[k]):
        v = N[k]
        cults = Counter(_culture(R[r]['culture'], cult_known) for r in R if R[r].get('owner') == k)
        cults.pop(None, None)
        scenario_new.create_nation(s, {'name': nat[k], 'color': v['color'] if re.fullmatch(r'#[0-9A-Fa-f]{6}', v['color'] or '') else None,
                                       'gov': v['gov'], 'playable': True, 'culture': cults.most_common(1)[0][0] if cults else None},
                                   need_capital=False)
    notes.append('%d naciones' % len(present))

    tick(12, 'Creando las regiones')
    total_pop = 0
    for i, n in enumerate(land):
        if i % 50 == 0:
            tick(12 + 38 * i // len(land), 'Creando las regiones (%d de %d)' % (i, len(land)))
        if n not in owner:
            warns.append('AVISO: %s no tiene dueño en MH2 ni vecinas con dueño: no se ha creado' % n)
            continue
        r, c = src.get(n) or {}, log.get(n, {})
        o, ctl = owner[n]
        pop = max(int(r.get('pop') or 0) or int(c.get('poblacion_manual') or 0), 1000)    # 0-2 inhabitants: the game takes it as empty
        sc.add_new_region(s, n, owner=nat[o], terrain=TERRAIN.get(r.get('terrain'), r.get('terrain')) or c.get('terreno') or 'Plains',
                          population=pop, text=texts.get(n) or r.get('display') or sc.spaced_name(n))
        total_pop += pop
        vals = {'strController': nat[ctl]} if ctl != o else {}
        cu = _culture(r.get('culture'), cult_known)
        if cu:
            vals['strCulture'] = cu
        if vals:
            reg = next(x for x in s.countries()[nat[o]] if x.tag == 'object' and x.get('type') == 'Region' and prop(x, 'strName') == n)
            s.update(s.s.eid(reg), vals)
    for n in seas:
        L.add_sea_region(s, n, text=texts.get(n) or sc.spaced_name(n))
    notes.append('%d regiones de tierra y %d de mar; %s habitantes' % (len(land), len(seas), format(total_pop, ',').replace(',', '.')))

    tick(50, 'Países históricos')
    by_tmpl = {v['tmpl']: k for k, v in N.items() if k in present}
    hist = defaultdict(list)
    for n, r in src.items():
        for h in (r or {}).get('historic', []):
            if h in by_tmpl:
                hist[by_tmpl[h]].append(n)
    for k, regs in hist.items():
        scenario_new.add_historic(s, nat[k], regs)

    tick(55, 'Creando las ciudades')
    made, city_name, taken = 0, {}, set()
    regpop = {prop(r, 'strName'): int(prop(r, 'nPopulation') or 0) for r in s.regions(sea=False)}
    ncity = Counter(by_key.get(_key(c['region'])) for c in data['cities'])
    for c in data['cities']:
        n = _safe(c['display']) or c['name']
        city_name[c['name']] = n if n.lower() not in taken else c['name']
        taken.add(city_name[c['name']].lower())
    for c in data['cities']:
        reg = by_key.get(_key(c['region']))
        if reg not in land_set or not c['xy']:
            warns.append('AVISO: ciudad %s sin región de tierra en el mapa (%s): no se ha creado' % (c['name'], c['region']))
            continue
        port = by_key.get(_key(c['sea'])) if c['sea'] else None
        if port and port not in pm.nb.get(reg, []):      # the port's sea must touch the region on this map
            port = next((x for x in pm.nb.get(reg, []) if pm.sea.get(x)), None)
        try:
            # a city's population: a tenth of its region's, shared among its cities (a capital needs more than 2)
            L.create_city(s, city_name[c['name']], c['xy'][0], c['xy'][1], c['ipus'], max(1000, regpop.get(reg, 0) // (10 * ncity[reg])),
                          c['display'], port if port and port not in land_set else None, region=reg)
            made += 1
        except ValueError as e:
            warns.append('AVISO ciudad %s: %s' % (c['name'], e))
    notes.append('%d ciudades' % made)
    cities = {prop(c, 'strName') for c in s.all('City')}
    for k, cap in data['capitals'].items():
        if k in present and city_name.get(cap) in cities:
            scenario_new.set_capital(s, nat[k], city_name[cap])
    for k in present:      # without a capital in MH2: its city with most IPUs
        if not prop(s.countries()[nat[k]], 'strCapital'):
            own = [ci for r in s.regions(sea=False) if prop(r, 'strOwner') == nat[k] for ci in objs(r) if ci.get('type') == 'City']
            if own:
                scenario_new.set_capital(s, nat[k], prop(own[0], 'strName'))

    tick(65, 'Creando los recursos')
    prods = 0
    for n, r in src.items():
        g = pm.geom(n)
        for res, slots, built in (r or {}).get('resources', []):
            if g is None or not (slots or built):
                continue
            x, y = L.random_point_in(g, seed=_key(n + res))
            try:
                L.create_producer(s, '%s %s' % (_display(None, n), res), RESOURCES[res], x, y, 100 * max(1, built) + 25 * slots)
                prods += 1
            except ValueError as e:
                warns.append('AVISO recurso %s de %s: %s' % (res, n, e))
    notes.append('%d recursos (carbón, metales, petróleo)' % prods)

    tick(75, 'Creando las unidades')
    tmpls = _templates(s, use)
    mapped, dropped, made = Counter(), Counter(), 0
    for g in data['groups']:
        reg = by_key.get(_key(g['region']))
        if g['owner'] not in present or reg is None:
            warns.append('AVISO: %s (%s, en %s) no se ha creado: su país o su región no están en el escenario' % (g['name'], g['owner'], g['region']))
            continue
        kinds = defaultdict(Counter)
        for u in g['units']:
            kind, t = _unit_for(u, tmpls)
            if t:
                kinds[kind][t] += 1
                mapped[(u, t)] += 1
            else:
                dropped[u] += 1
        for kind, cnt in kinds.items():
            units = [{'type': t, 'n': n_} for t, n_ in cnt.items()]
            gname = g['display'] if len(kinds) == 1 else '%s (%s)' % (g['display'], {'land': 'ejército', 'air': 'aviación', 'navy': 'flota'}[kind])
            who = nat[g['owner']]
            try:
                if kind == 'land':
                    if reg not in land_set:
                        raise ValueError('un ejército no puede estar en el mar (%s)' % reg)
                    L.create_army(s, who, gname, reg, units)
                elif kind == 'air':
                    C.create_airforce(s, who, gname, reg, units)
                else:
                    at = reg
                    if g.get('city') and city_name.get(g['city']) in cities:
                        C.create_fleet(s, who, gname, reg, units, city=city_name[g['city']])
                        made += 1
                        continue
                    if reg in land_set and not any(ci.get('type') == 'City' and prop(ci, 'strPortForRegion')
                                                   for r_ in s.regions(sea=False) if prop(r_, 'strName') == reg for ci in objs(r_)):
                        at = next((x for x in pm.nb.get(reg, []) if pm.sea.get(x)), reg)     # no port there: the sea next to it
                    C.create_fleet(s, who, gname, at, units)
                made += 1
            except ValueError as e:
                warns.append('AVISO grupo %s: %s' % (gname, e))
    notes.append('%d ejércitos, flotas y fuerzas aéreas; unidades MH2 → MH1: %s' % (made, ', '.join('%s → %s ×%d' % (a, b, n_) for (a, b), n_ in sorted(mapped.items()))))
    if dropped:
        warns.append('unidades de MH2 sin equivalente en MH1 (no se crean): %s' % ', '.join('%s ×%d' % kv for kv in dropped.most_common()))

    tick(85, 'Investigación de las unidades')
    items = tech_units.plan(s, sorted(nat[k] for k in present))
    if items:
        tech_units.apply(s, items)
        notes.append('investigación marcada como completada para poder usar sus unidades: %d países' % len(items))

    tick(88, 'Diplomacia')
    for a, b in data['wars']:
        if a in present and b in present:
            try:
                notes += C.create_war(s, [nat[a]], [nat[b]])
            except ValueError as e:
                warns.append('AVISO guerra %s - %s: %s' % (nat.get(a, a), nat.get(b, b), e))
    for al, members in data['alliances']:
        ms = [nat[m] for m in members if m in present]
        if len(ms) > 1:
            try:
                notes += C.create_alliance(s, al, ms[0], ms[1:])[1]
            except ValueError as e:
                warns.append('AVISO alianza %s: %s' % (al, e))
    if not data['wars'] and not data['alliances']:
        notes.append('el escenario de MH2 no tiene guerras ni alianzas')
    if data['trade']:
        warns.append('%d acuerdos comerciales de MH2 no se copian' % data['trade'])
    notes.append('no se copian los niveles de relación diplomática ni la investigación propia de MH2 (MH1 no tiene equivalentes)')

    tick(90, 'Banderas')
    flags = 0
    for k in present:
        try:
            flags += _flag(s, nat[k], N[k])
        except Exception as e:      # an unreadable image must not stop the conversion
            warns.append('AVISO bandera de %s: %s' % (nat[k], e))
    notes.append('banderas de MH2 para %d de %d naciones' % (flags, len(present)))
    warns += ['AVISO naciones: %s' % x for x in scenario_new.check_nations(s)]


def _mh2_flags():
    import gamepaths
    for common in gamepaths._steam_libraries():
        d = os.path.join(common, 'Making History II', 'content', 'Making History II', 'modules', 'ui lib', 'skin', 'textures', 'art', 'Nation Flags')
        if os.path.isdir(d):
            return d
    return None


def _flag(s, name, v):
    """The nation's flag files from MH2's flag of its nationality and government. 1 if written, 0 if MH2 has none."""
    from PIL import Image
    import image_tools as T
    root, nat = _mh2_flags(), v.get('nationality')
    d = os.path.join(root, nat) if root and nat else None
    if not d or not os.path.isdir(d):
        return 0
    pick = [os.path.join(d, '%s-%s256x128.png' % (nat, g)) for g in (v['gov'],) + GOVS]
    f = next((p for p in pick if os.path.isfile(p)), None) or next((os.path.join(d, x) for x in sorted(os.listdir(d)) if x.endswith('256x128.png')), None)
    if not f:
        return 0
    out = os.path.join(T.countries_dir(s.name), T.safe_name(name))
    files = T.flag_set(Image.open(f), only='flag')
    T.write_files({os.path.join(out, k): T.encode(im, k, T.FLAG_FMT.get(k, T.DEFAULT_FMT)) for k, im in files.items()}, 'bandera-' + T.safe_name(name))
    return 1
