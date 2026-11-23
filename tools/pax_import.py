"""New MH1 scenario from a Pax Historia preset: an existing MH1 scenario (cities, population, resources, units, research) with the
preset's political map on top.

Pax Historia has no export: its web app keeps the preset in memory. SNIPPET (pasted in the browser console on the preset's map,
after «Play now») saves it as pax_<preset>.json: title, start date, region names, countries (regions owned, colour, flag) and the id of
its map geometry, which is public at map-geometry.paxhistoria.co (lon/lat polygons, one per Pax region).

Each land region of the base scenario goes to the Pax country covering most of it. Countries the base already has are reused (The German
Reich -> Germany, Kingdom of Italy -> Italy); the rest are created with the Pax colour and flag; base countries left without land are
removed (their units go to whoever took most of their land). Pax has no population, cities, units or diplomacy of its own: those stay as
in the base scenario.
"""
import io
import json
import os
import re
import urllib.request
from collections import Counter, defaultdict

import scenario_core as sc
from scenario_core import prop, objs

GEOMETRY_URL = 'https://map-geometry.paxhistoria.co/%s.json'
# Pax names whose MH1 name is not just the name without «Kingdom of», «Republic of»...
ALIASES = {'german reich': 'Germany', 'russian sfsr': 'USSR', 'soviet union': 'USSR', 'union of soviet socialist republics': 'USSR',
           'united kingdom of great britain': 'United Kingdom', 'united kingdom of great britain and northern ireland': 'United Kingdom',
           'united states of america': 'United States', 'french republic': 'France', 'second polish republic': 'Poland',
           'polish republic': 'Poland', 'empire of japan': 'Japan', 'japanese empire': 'Japan', 'republic of china': 'China',
           'ottoman empire': 'Turkey', 'hellenic republic': 'Greece', 'kingdom of hungary': 'Hungary', 'irish free state': 'Ireland',
           'swiss confederation': 'Switzerland', 'czechoslovak republic': 'Czechoslovakia', 'commonwealth of australia': 'Australia',
           'union of south africa': 'South Africa', 'british raj': 'India'}
PREFIX = re.compile(r'^(the |kingdom of |republic of |empire of |dominion of |commonwealth of |state of |principality of |grand duchy of |'
                    r'federal state of |united states of |sultanate of |emirate of |free state of |duchy of )+')
SNIPPET = (r"""(()=>{const e=[...document.querySelectorAll('*')].find(e=>Object.keys(e).some(k=>k.startsWith('__reactFiber')));"""
           r"""let f=e[Object.keys(e).find(k=>k.startsWith('__reactFiber'))];while(f.return)f=f.return;let p,s=[f];"""
           r"""while(s.length){const x=s.pop();if(x.memoizedProps&&x.memoizedProps.presetData){p=x.memoizedProps.presetData;break}"""
           r"""x.sibling&&s.push(x.sibling);x.child&&s.push(x.child)}if(!p)return alert('Open the preset map (Play now) first');"""
           r"""const r=p.rounds[0]||p.rounds['0'],c={};for(const[k,v]of Object.entries(r.countryDescriptions))c[k]={color:v.color,"""
           r"""regionsOwned:v.regionsOwned||[],flag:v.flag?v.flag.imageURL:null};const o={source:'paxhistoria',presetUID:p.presetUID,"""
           r"""title:p.title,startDate:r.startDate,mapGeometryDocumentID:p.mapGeometryDocumentID,regionData:p.regionData,"""
           r"""countryDescriptions:c};const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(o)],"""
           r"""{type:'application/json'}));a.download='pax_'+p.presetUID+'.json';a.click()})()""")


def norm(n):
    n = re.sub(r'[^a-z0-9 ]', '', (n or '').lower().replace('.', '').replace('-', ' '))
    return re.sub(r'\s+', ' ', n).strip()


def mh1_name(pax, existing):
    """Name of an existing MH1 nation for Pax country 'pax', or None. existing: {norm(name): name}."""
    n = norm(pax)
    for k in (n, norm(ALIASES.get(n, '')), norm(ALIASES.get(re.sub(r'^the ', '', n), '')), PREFIX.sub('', n)):
        if k and k in existing:
            return existing[k]
    return None


def mh1_name_any(mh1, pax_countries):
    """The Pax country whose name matches MH1 nation 'mh1', or None."""
    one = {norm(mh1): mh1}
    return next((pc for pc in pax_countries if mh1_name(pc, one)), None)


def check_preset(data):
    """The JSON the SNIPPET saves (or Pax's own presetData): checked and reduced to what is used."""
    if isinstance(data, (bytes, str)):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError('no es un preset de Pax Historia')
    if 'presetData' in data:
        data = data['presetData']
    cd = data.get('countryDescriptions')
    if cd is None and isinstance(data.get('rounds'), dict) and data['rounds']:
        r = data['rounds'].get('0') or next(iter(data['rounds'].values()))
        cd, data = r.get('countryDescriptions'), dict(data, startDate=r.get('startDate'))
    if not isinstance(cd, dict) or not cd or not str(data.get('mapGeometryDocumentID') or '').strip():
        raise ValueError('no es un preset de Pax Historia (faltan countryDescriptions o mapGeometryDocumentID)')
    d = data.get('startDate') or {}
    try:
        date = (int(d.get('year')), int(d.get('month') or 1), int(d.get('day') or 1))
    except (TypeError, ValueError):
        date = (1936, 1, 1)
    if str(d.get('label', 'AD')).upper() == 'BC' or not 1 <= date[0] <= 9999:
        date = (1936, 1, 1)     # MH1 dates are AD with four digits at most
    gid = re.sub(r'^r2:', '', str(data['mapGeometryDocumentID']).strip())
    if not re.fullmatch(r'[\w./%-]+', gid) or '..' in gid:
        raise ValueError('mapGeometryDocumentID no válido: %s' % gid)
    countries = {}
    for k, v in cd.items():
        fl = v.get('flag')
        countries[str(k)] = {'color': v.get('color'), 'regions': [str(x) for x in (v.get('regionsOwned') or [])],
                             'flag': fl if isinstance(fl, str) else (fl or {}).get('imageURL')}
    return {'title': str(data.get('title') or 'Pax Historia').strip(), 'uid': str(data.get('presetUID') or ''), 'date': date,
            'geometry_id': gid, 'countries': countries}


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': 'MHEditor'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def geometry(gid):
    """{pax region id: shapely geometry in lon/lat} of the land regions (Pax's Ocean/Strait ones are left out)."""
    from shapely.geometry import shape
    g = json.loads(_get(GEOMETRY_URL % gid))['geometry']
    out = {}
    for k, v in g.items():
        if v.get('type') in ('Ocean', 'Strait'):
            continue
        geo = shape(json.loads(v['geometry']) if isinstance(v['geometry'], str) else v['geometry'])
        out[str(k)] = geo if geo.is_valid else geo.buffer(0)
    return out


def owners(regions, pax, owner_of, proj=None):
    """{MH1 region: Pax country covering most of it}. regions: {name: geometry in map coordinates}; pax: {id: lon/lat geometry};
    owner_of: {pax id: country}. A region covered by no owned Pax region takes its nearest one's owner."""
    from shapely.strtree import STRtree
    ids = [k for k in pax if k in owner_of]
    geos = [proj.geom(pax[k]) if proj else pax[k] for k in ids]
    tree = STRtree(geos)
    out = {}
    for r, g in regions.items():
        if g is None or g.is_empty:
            continue
        area = Counter()
        for i in tree.query(g):
            a = g.intersection(geos[i]).area
            if a > 0:
                area[owner_of[ids[i]]] += a
        out[r] = area.most_common(1)[0][0] if area else owner_of[ids[tree.nearest(g.representative_point())]]
    return out


def convert(preset, base, name, display=None, open_scenario=None, progress=None):
    """Creates scenario 'name' as a copy of MH1 scenario 'base' with the political map of Pax Historia preset 'preset' (check_preset) and
    saves it. Returns {'name', 'notes', 'warnings'}. On an error halfway the half-made folder is removed."""
    import shutil
    import scenario_layers as L
    tick = progress or (lambda pct, msg: None)
    opener = open_scenario or sc.Scenario
    tick(2, 'Descargando el mapa de Pax Historia')
    pax = geometry(preset['geometry_id'])
    owner_of = {rid: c for c, v in preset['countries'].items() for rid in v['regions'] if rid in pax}
    if not owner_of:
        raise ValueError('ninguna región del preset tiene dueño en su mapa')
    src = opener(base)
    pack = sc.pack_of(src)
    tick(10, 'Copiando el escenario base')
    name = L.save_as_new(src, name)['scenario']
    try:
        y, mo, d = preset['date']
        _set_props(os.path.join(sc.SCEN_ROOT, name), {
            'strName': name, 'strDisplayName': display or name, 'nStartYear': y, 'nStartMonth': mo, 'nStartDay': d,
            'dateStart': '%02d/%02d/%d' % (mo, d, y),
            'strDescription': 'Importado de Pax Historia: %s (%s), sobre %s' % (preset['title'], preset['uid'], base)})
        s = opener(name)
        notes, warns = ['escenario %s creado a partir de %s (%02d/%02d/%d, regionpack %s)' % (name, base, d, mo, y, pack)], []
        _build(s, preset, pax, owner_of, pack, notes, warns, tick)
        tick(97, 'Guardando')
        s.s.save(scenario=s)
    except Exception:
        shutil.rmtree(os.path.join(sc.SCEN_ROOT, name), ignore_errors=True)
        raise
    return {'name': name, 'notes': notes, 'warnings': warns}


def _set_props(folder, values):
    from xml.sax.saxutils import quoteattr
    for f in ('scenario.xml', 'scenarioInfo.xml'):
        p = os.path.join(folder, f)
        if not os.path.exists(p):
            continue
        t = open(p, encoding='utf-8', errors='replace', newline='').read()
        for k, v in values.items():
            t = re.sub(r'(name="%s" value=")[^"]*(")' % k, lambda m: m.group(1) + quoteattr(str(v))[1:-1] + m.group(2), t, count=1)
        open(p, 'w', encoding='utf-8', newline='').write(t)


def _build(s, preset, pax, owner_of, pack, notes, warns, tick):
    import editor_core
    import scenario_layers as L
    import scenario_new
    pm = L.pack_map(pack)
    proj = L.Projection.load(os.path.join(editor_core.MAPS, pack))
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    tick(20, 'Repartiendo las regiones entre los países de Pax Historia')
    own = owners({n: pm.geom(n) for n in land}, pax, owner_of, proj)
    if not own:
        raise ValueError('el mapa de Pax Historia no cae sobre ninguna región de %s' % pack)
    countries = s.countries()
    existing = {norm(n): n for n in countries}
    before = {n: prop(r, 'strOwner') for n, r in land.items()}

    tick(35, 'Creando las naciones')
    order = sorted(set(own.values()), key=lambda c: -sum(1 for v in own.values() if v == c))     # the biggest first
    mh1 = {}
    for pc in order:                    # 1. same country by name (The German Reich -> Germany)
        n = mh1_name(pc, existing)
        if n and n not in mh1.values():
            mh1[pc] = n
    # 2. base countries no Pax name matched, by shared land, biggest overlap first (British Raj -> India, Imperial State of Iran -> Persia)
    pairs = Counter((o, before[n]) for n, o in own.items() if o not in mh1)
    free = {c for c in countries if c not in mh1.values() and mh1_name_any(c, order) is None}     # order: Pax countries with land
    for (pc, c), _n in pairs.most_common():
        if pc not in mh1 and c in free:
            mh1[pc] = c
            free.discard(c)
    taken = {x.lower() for x in countries}
    for pc in order:                    # 3. new
        if pc in mh1:
            continue
        n = _safe(pc)
        while n.lower() in taken:
            n += ' (Pax)'
        taken.add(n.lower())
        scenario_new.create_nation(s, {'name': n, 'color': _color(preset['countries'][pc].get('color')), 'gov': 'Authoritarian',
                                       'playable': True}, need_capital=False)
        mh1[pc] = n
    new = [n for n in mh1.values() if n not in countries]
    notes.append('%d países de Pax Historia: %d ya estaban en el escenario base y %d nuevos' % (len(mh1), len(mh1) - len(new), len(new)))

    tick(50, 'Cambiando los dueños de las regiones')
    moved = 0
    for n, pc in own.items():
        o = mh1[pc]
        if before[n] != o or prop(land[n], 'strController') != o:
            s.update(s.s.eid(land[n]), {'strOwner': o, 'strController': o})
            moved += 1
    notes.append('%d de %d regiones de tierra cambian de dueño' % (moved, len(land)))

    tick(65, 'Quitando los países sin territorio')
    held = set(mh1.values())
    gone = []
    for c in list(s.countries()):
        if c in held:
            continue
        dest = Counter(mh1[own[n]] for n, o in before.items() if o == c and n in own).most_common(1)
        try:
            L.delete_country(s, c, dest[0][0] if dest else sorted(held)[0])
            gone.append(c)
        except ValueError as e:
            warns.append('AVISO: no se ha podido quitar %s: %s' % (c, e))
    if gone:
        notes.append('%d países del escenario base no tienen territorio en Pax Historia y se han quitado (sus unidades pasan a quien se quedó '
                     'su tierra): %s' % (len(gone), ', '.join(sorted(gone))))

    tick(75, 'Capitales')
    cities = defaultdict(list)          # owner -> [(population, city name)]
    for r in s.regions(sea=False):
        for c in objs(r):
            if c.get('type') == 'City':
                cities[prop(r, 'strOwner')].append((int(prop(c, 'nPopulation') or 0), prop(c, 'strName')))
    countries = s.countries()
    made = 0
    for n in sorted(held):
        cap = prop(countries[n], 'strCapital')
        mine = sorted(cities.get(n, []), reverse=True)
        if cap and any(x[1] == cap for x in mine):
            continue
        if mine:
            scenario_new.set_capital(s, n, mine[0][1])
            continue
        regs = [x for x, o in own.items() if mh1[o] == n and pm.geom(x) is not None]
        if not regs:
            continue
        r = max(regs, key=lambda x: pm.geom(x).area)
        p = pm.geom(r).representative_point()
        nm = r
        while any(prop(c, 'strName') == nm for c in s.all('City')):
            nm += ' City'
        try:
            L.create_city(s, nm, p.x, p.y, 1, max(1000, int(prop(land[r], 'nPopulation') or 0) // 10), nm, None, region=r)
            scenario_new.set_capital(s, n, nm)
            made += 1
        except ValueError as e:
            warns.append('AVISO capital de %s: %s' % (n, e))
    if made:
        notes.append('%d países sin ciudades: se les ha creado una capital en su región más grande' % made)

    tick(85, 'Banderas')
    flags = 0
    for pc, n in mh1.items():
        url = preset['countries'][pc].get('flag') or ''
        if n in new and re.fullmatch(r'https://flags\.paxhistoria\.co/[\w.%()-]+', url):
            try:
                flags += _flag(s, n, _get(url, 30))
            except Exception as e:        # a missing flag is not worth the import: the game shows a default one
                warns.append('AVISO bandera de %s: %s' % (n, e))
    notes.append('banderas de Pax Historia para %d de %d países nuevos' % (flags, len(new)))
    notes.append('de Pax Historia se toman los dueños de las regiones, los países nuevos (color y bandera) y la fecha; la población, ciudades, '
                 'recursos, unidades, investigación y diplomacia son las del escenario base')


def _safe(n):
    n = re.sub(r'\s+', ' ', re.sub(r'[\\/:*?"<>|]', '', (n or '').replace('&', ' and '))).strip() or 'Pax'
    return n.title() if n == n.lower() else n          # Pax names are sometimes all lower case («mexico»)


def _color(c):
    m = re.fullmatch(r'#?([0-9a-fA-F]{6})', (c or '').strip())
    return '#' + m.group(1).upper() if m else None


def _flag(s, name, raw):
    from PIL import Image
    import image_tools as T
    out = os.path.join(T.countries_dir(s.name), T.safe_name(name))
    files = T.flag_set(Image.open(io.BytesIO(raw)).convert('RGBA'), only='flag')
    T.write_files({os.path.join(out, k): T.encode(im, k, T.FLAG_FMT.get(k, T.DEFAULT_FMT)) for k, im in files.items()}, 'bandera-' + T.safe_name(name))
    return 1


if __name__ == '__main__':      # self-check of the parts that need no game files
    ex = {norm(n): n for n in ('Germany', 'USSR', 'Italy', 'United Kingdom', 'Poland', 'France')}
    assert mh1_name('The German Reich', ex) == 'Germany'
    assert mh1_name('Russian S.F.S.R', ex) == 'USSR'
    assert mh1_name('Kingdom of Italy', ex) == 'Italy'
    assert mh1_name('Second Polish Republic', ex) == 'Poland'
    assert mh1_name('French Indochina', ex) is None and mh1_name('Ukrainian S.S.R', ex) is None
    p = check_preset({'title': 'T', 'startDate': {'year': 1934, 'month': 3, 'day': 1}, 'mapGeometryDocumentID': 'r2:map-geometry/a/b',
                      'countryDescriptions': {'A': {'regionsOwned': ['1'], 'color': '#ff0000'}}})
    assert p['date'] == (1934, 3, 1) and p['geometry_id'] == 'map-geometry/a/b' and _color('#ff0000') == '#FF0000'
    from shapely.geometry import box
    o = owners({'R1': box(0, 0, 2, 1), 'R2': box(5, 5, 6, 6)}, {'1': box(0, 0, 1.5, 1), '2': box(1.5, 0, 2, 1)}, {'1': 'A', '2': 'B'})
    assert o == {'R1': 'A', 'R2': 'B'}, o      # R2 is covered by none: the nearest
    assert _safe('jammu & kashmir') == 'Jammu And Kashmir' and _safe('French Morocco') == 'French Morocco'
    print('ok')
