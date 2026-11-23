"""New MH1 scenario from Europa Universalis IV (history at a start date, 1444.11.11 by default) on the WorldEU4 regionpack.

    python -u eu4_import.py "<scenario name>" [--fecha 1444.11.11] [--eu4 "<EU4 folder>"] [--escenarios <scratch folder>]

WorldEU4 is drawn in EU4's own frame: a pixel (px, py) of map/provinces.bmp (5632x2048) is (px * 360 / 5632 - 180, 80 - py * 360 / 5632),
and every land region is one EU4 province, so each region takes the province under most of its pixels.
What is read:
- history/provinces: owner, controller, capital (-> city name), base tax/production/manpower (development -> population,
  production -> IPUs), trade goods (iron, copper, gold -> Metals; coal -> Coal), cores (-> historic countries), native size.
- history/countries: capital, government (monarchy, theocracy, tribal -> Authoritarian; republic -> Democratic);
  common/countries: colour; localisation: names; gfx/flags: flags; map/positions.txt: city positions.
Land owned by nobody at the start goes to «Uncolonized», a non-playable nation (MH1 has no ownerless land).
Units, diplomacy, religion and culture are not converted (MH1 has no equivalent for most of them).
"""
import argparse, os, re, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shapely.geometry import Point
import scenario_core as sc
from scenario_core import prop
from hoi4_import import parse, get, getall, _date, _safe, _flag

PACK = 'WorldEU4'
W, H = 5632, 2048
K = 360.0 / W
GOV = {'republic': 'Democratic'}            # monarchy, theocracy, tribal, native -> Authoritarian
RES = {'iron': 'Metals', 'copper': 'Metals', 'gold': 'Metals', 'coal': 'Coal'}
POP_PER_DEV = 15000          # 1444: ~25.000 development points ~ 375 million people
POP_PER_NATIVE = 1000
NOBODY = 'Uncolonized'


def localisation(eu4):
    loc = {}
    d = os.path.join(eu4, 'localisation')
    for f in sorted(os.listdir(d)):
        if f.endswith('_l_english.yml'):
            for m in re.finditer(r'^\s*([A-Za-z0-9_.\-]+):\d*\s*"(.*)"\s*$', open(os.path.join(d, f), encoding='utf-8-sig', errors='replace').read(), re.M):
                loc.setdefault(m.group(1), m.group(2))
    return loc


def _read(path):
    return parse(open(path, encoding='latin-1', errors='replace').read())


def _apply_dated(blk, when, keys, state, cores):
    """Applies the dated blocks of a history file up to 'when' on 'state' (keys listed) and on the core set."""
    for dk, b in sorted(((dk, b) for dk, b in blk if _date(dk) and isinstance(b, list)), key=lambda kv: _date(kv[0])):
        if _date(dk) > when:
            break
        for k in keys:
            v = get(b, k)
            if v is not None:
                state[k] = v
        cores |= set(getall(b, 'add_core'))
        cores -= set(getall(b, 'remove_core'))


def read(eu4, start):
    """Provinces, nations and city positions of EU4 at date 'start'."""
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    when = _date(start)
    if not when:
        raise ValueError('fecha no válida: %s (formato año.mes.día, p. ej. 1444.11.11)' % start)
    loc = localisation(eu4)
    img = np.asarray(Image.open(os.path.join(eu4, 'map', 'provinces.bmp')).convert('RGB')).astype(np.int32)
    if img.shape[:2] != (H, W):
        raise ValueError('el mapa de EU4 no mide %dx%d: no encaja con WorldEU4' % (W, H))
    key = (img[..., 0] << 16) | (img[..., 1] << 8) | img[..., 2]
    col = {}
    for line in open(os.path.join(eu4, 'map', 'definition.csv'), encoding='latin-1'):
        x = line.strip().split(';')
        if len(x) > 3 and x[0].isdigit():
            col[(int(x[1]) << 16) | (int(x[2]) << 8) | int(x[3])] = int(x[0])
    u, inv = np.unique(key, return_inverse=True)
    ids = np.array([col.get(int(v), 0) for v in u], np.int32)[inv].reshape(key.shape)
    del img, key
    # city positions: first x y of each province's position block, y counted from the bottom of the map
    pos = {}
    for k, blk in _read(os.path.join(eu4, 'map', 'positions.txt')):
        p = get(blk, 'position') if isinstance(blk, list) and k.isdigit() else None
        if p and len(p) >= 2:
            pos[int(k)] = (float(p[0][1]) * K - 180, 80 - (H - float(p[1][1])) * K)
    provs = {}
    d = os.path.join(eu4, 'history', 'provinces')
    keys = ('owner', 'controller', 'capital', 'base_tax', 'base_production', 'base_manpower', 'trade_goods', 'native_size')
    for f in os.listdir(d):
        m = re.match(r'(\d+)', f)
        if not m or not f.endswith('.txt'):
            continue
        blk = _read(os.path.join(d, f))
        st = {k: get(blk, k) for k in keys}
        cores = set(getall(blk, 'add_core'))
        _apply_dated(blk, when, keys, st, cores)
        num = lambda k: float(st[k]) if re.fullmatch(r'\d+(\.\d+)?', str(st.get(k) or '')) else 0.0
        provs[int(m.group(1))] = {'owner': st['owner'], 'ctl': st['controller'] or st['owner'], 'city': st['capital'],
                                  'dev': num('base_tax') + num('base_production') + num('base_manpower'), 'prod': num('base_production'),
                                  'goods': st['trade_goods'], 'natives': num('native_size'), 'cores': cores}
    tags = {}
    for f in os.listdir(os.path.join(eu4, 'common', 'country_tags')):
        if f.endswith('.txt'):
            for k, v in _read(os.path.join(eu4, 'common', 'country_tags', f)):
                if re.fullmatch(r'[A-Z0-9]{3}', k) and isinstance(v, str):
                    tags[k] = v
    hist = {f[:3]: os.path.join(eu4, 'history', 'countries', f) for f in os.listdir(os.path.join(eu4, 'history', 'countries')) if f.endswith('.txt')}
    nations = {}
    used = {p['owner'] for p in provs.values() if p['owner']} | {p['ctl'] for p in provs.values() if p['ctl']} | \
        {t for p in provs.values() for t in p['cores']}
    for tag in used:
        st = {'capital': None, 'government': None}
        if tag in hist:
            h = _read(hist[tag])
            st = {'capital': get(h, 'capital'), 'government': get(h, 'government')}
            _apply_dated(h, when, ('capital', 'government'), st, set())
        color = None
        if tags.get(tag) and os.path.isfile(os.path.join(eu4, 'common', tags[tag])):
            c = get(_read(os.path.join(eu4, 'common', tags[tag])), 'color')
            nums = [float(x) for _, x in (c if isinstance(c, list) else []) if re.fullmatch(r'\d+(\.\d+)?', x)]
            if len(nums) >= 3:
                color = '#%02x%02x%02x' % tuple(int(max(0, min(255, v))) for v in nums[:3])
        flag = os.path.join(eu4, 'gfx', 'flags', tag + '.tga')
        nations[tag] = {'tag': tag, 'name': loc.get(tag) or tag, 'gov': GOV.get(st['government'], 'Authoritarian'), 'color': color,
                        'capital': int(st['capital']) if str(st['capital'] or '').isdigit() else None,
                        'flag': flag if os.path.isfile(flag) else None}
    return {'provs': provs, 'nations': nations, 'ids': ids, 'pos': pos, 'date': when}


def _region_province(pm, land, ids):
    """{region: EU4 province under most of its pixels}."""
    import numpy as np
    from PIL import Image, ImageDraw
    canvas = Image.new('I', (W, H), 0)
    d = ImageDraw.Draw(canvas)
    for i, n in enumerate(land, 1):
        g = pm.geom(n)
        for poly in (getattr(g, 'geoms', [g]) if g is not None else []):
            if poly.geom_type == 'Polygon':
                d.polygon([((x + 180) / K, (80 - y) / K) for x, y in poly.exterior.coords], fill=i)
    R = np.asarray(canvas, np.int32)
    m = R > 0
    best = {}
    for (r, p), c in Counter(zip(R[m].tolist(), ids[m].tolist())).items():
        if c > best.get(r, (0, 0))[1]:
            best[r] = (p, c)
    return {land[r - 1]: p for r, (p, c) in best.items()}


def convert(eu4, start, name, display=None, progress=None):
    """Creates scenario 'name' on WorldEU4 from EU4's history at 'start' and saves it. On an error the half-made folder is removed."""
    import shutil
    import editor_core
    import scenario_new
    import scenario_layers as L
    if not os.path.exists(os.path.join(editor_core.MAPS, PACK, 'xml', 'regions.bin')):
        raise ValueError('instala primero el regionpack WorldEU4: el importador de EU4 lo necesita (está dibujado con el mapa de EU4)')
    pm = L.pack_map(PACK)
    tick = progress or (lambda pct, msg: print('%3d%% %s' % (pct, msg), flush=True))
    tick(2, 'Leyendo Europa Universalis IV')
    data = read(eu4, start)
    y, mo, d = data['date']
    name = scenario_new.create_scenario(name, PACK, None, display or name,
                                        'Importado de Europa Universalis IV (%d-%02d-%02d)' % (y, mo, d), y, mo, d)
    try:
        notes, warns = ['escenario %s creado (%02d/%02d/%d, regionpack %s)' % (name, d, mo, y, PACK)], []
        s = sc.Scenario(name)
        _build(s, data, pm, notes, warns, tick)
        tick(97, 'Guardando')
        s.s.save(scenario=s)
    except Exception:
        shutil.rmtree(os.path.join(sc.SCEN_ROOT, name), ignore_errors=True)
        raise
    return {'name': name, 'notes': notes, 'warnings': warns}


def _build(s, data, pm, notes, warns, tick):
    import scenario_new
    import scenario_layers as L
    P, N = data['provs'], data['nations']
    skip = {'BasicRegionLists', 'Historic'}
    land = [n for n, sea in pm.sea.items() if not sea and n not in skip]
    seas = [n for n, sea in pm.sea.items() if sea and n not in skip]
    tick(8, 'Situando las provincias de EU4 en las regiones')
    rp = _region_province(pm, land, data['ids'])
    owner = {r: (P[p]['owner'], P[p]['ctl']) for r, p in rp.items() if p in P and P[p]['owner']}
    for r in land:
        owner.setdefault(r, (NOBODY, NOBODY))
    present = sorted(({o for o, _ in owner.values()} | {c for _, c in owner.values()}) - {NOBODY}, key=lambda t: N.get(t, {}).get('name', t))
    nat, used = {NOBODY: NOBODY}, {NOBODY.lower()}
    for t in present:
        n = _safe(N.get(t, {}).get('name')) or t
        while n.lower() in used:
            n += ' (%s)' % t
        used.add(n.lower())
        nat[t] = n

    tick(15, 'Creando las naciones')
    for t in present:
        v = N.get(t, {})
        scenario_new.create_nation(s, {'name': nat[t], 'color': v.get('color'), 'gov': v.get('gov', 'Authoritarian'), 'playable': True},
                                   need_capital=False)
    nobody = any(o == NOBODY for o, _ in owner.values())
    if nobody:
        scenario_new.create_nation(s, {'name': NOBODY, 'color': '#9a9a8a', 'gov': 'Authoritarian', 'playable': False}, need_capital=False)
    notes.append('%d naciones%s' % (len(present), ' (+ %s, no jugable, con la tierra sin dueño)' % NOBODY if nobody else ''))

    tick(30, 'Creando las regiones')
    total, regpop = 0, {}
    for r in land:
        p = P.get(rp.get(r), {})
        o, ctl = owner[r]
        pop = int(p.get('dev', 0) * POP_PER_DEV) if o != NOBODY else int(p.get('natives', 0) * POP_PER_NATIVE)
        pop = max(pop, 1000)            # 0-2 inhabitants: the game takes it as empty
        sc.add_new_region(s, r, owner=nat[o], terrain='Plains', population=pop)
        if ctl != o and ctl in nat:
            reg = next(x for x in s.countries()[nat[o]] if x.tag == 'object' and x.get('type') == 'Region' and prop(x, 'strName') == r)
            s.update(s.s.eid(reg), {'strController': nat[ctl]})
        regpop[r] = pop
        total += pop
    for n in seas:
        L.add_sea_region(s, n)
    notes.append('%d regiones de tierra y %d de mar; %s habitantes' % (len(land), len(seas), format(total, ',').replace(',', '.')))

    tick(50, 'Creando las ciudades')
    names, made, city_in = set(), 0, {}
    for r in land:
        p = P.get(rp.get(r))
        if not p or owner[r][0] == NOBODY or not p.get('city'):
            continue
        nm = _safe(p['city'])
        if nm.lower() in names:
            nm = _safe('%s (%s)' % (nm, r))
        if not nm or nm.lower() in names:
            continue
        g = pm.geom(r)
        x, y = data['pos'].get(rp[r], (None, None))
        if x is None or not g.contains(Point(x, y)):
            q = g.representative_point()
            x, y = q.x, q.y
        port = next((z for z in pm.nb.get(r, []) if pm.sea.get(z)), None)
        try:
            L.create_city(s, nm, x, y, max(1, int(round(p['prod']))), max(1000, regpop[r] // 5), nm, port, region=r)
            names.add(nm.lower())
            city_in[r] = nm
            made += 1
        except ValueError as e:
            warns.append('AVISO ciudad %s: %s' % (nm, e))
    notes.append('%d ciudades (la capital de cada provincia de EU4)' % made)

    tick(65, 'Capitales y países históricos')
    reg_of = {p: r for r, p in rp.items()}
    for t in [*present, NOBODY]:
        regs = [r for r in land if owner[r][0] == t]
        if not regs:
            continue
        home = reg_of.get(N.get(t, {}).get('capital'))
        cap = city_in.get(home) if home and owner[home][0] == t else None
        if not cap:
            cap = next((city_in[r] for r in sorted(regs, key=lambda r: -regpop[r]) if r in city_in), None)
        if not cap:         # no city of its own (Uncolonized, natives without a capital name): one in its biggest region
            r = max(regs, key=lambda r: pm.geom(r).area)
            q = pm.geom(r).representative_point()
            cap = _safe(r)
            while cap.lower() in names:
                cap += ' City'
            try:
                L.create_city(s, cap, q.x, q.y, 1, max(1000, regpop[r] // 5), cap, None, region=r)
                names.add(cap.lower())
            except ValueError as e:
                warns.append('AVISO capital de %s: %s' % (nat[t], e))
                continue
        scenario_new.set_capital(s, nat[t], cap)
    cores = defaultdict(list)
    for r, p in rp.items():
        for t in P.get(p, {}).get('cores', ()):
            if t in nat:
                cores[t].append(r)
    for t, regs in cores.items():
        scenario_new.add_historic(s, nat[t], regs)
    notes.append('países históricos (núcleos de EU4) para %d naciones' % len(cores))

    tick(75, 'Creando los recursos')
    prods = 0
    for r in land:
        p = P.get(rp.get(r))
        kind = RES.get((p or {}).get('goods'))
        if not kind or owner[r][0] == NOBODY:
            continue
        x, y = L.random_point_in(pm.geom(r), seed=r + kind)
        try:
            L.create_producer(s, '%s %s' % (r, kind), kind, x, y, max(1, int(round(p['prod']))))
            prods += 1
        except ValueError as e:
            warns.append('AVISO recurso %s de %s: %s' % (kind, r, e))
    notes.append('%d recursos (hierro, cobre y oro como metales; carbón)' % prods)

    tick(88, 'Banderas')
    flags = 0
    for t in present:
        f = N.get(t, {}).get('flag')
        if f:
            try:
                flags += _flag(s, nat[t], f)
            except Exception as e:      # an unreadable image must not stop the import
                warns.append('AVISO bandera de %s: %s' % (nat[t], e))
    notes.append('banderas de EU4 para %d de %d naciones' % (flags, len(present)))
    notes.append('no se importan unidades, diplomacia, religión ni cultura de EU4')
    warns += ['AVISO naciones: %s' % x for x in scenario_new.check_nations(s)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('nombre')
    ap.add_argument('--fecha', default='1444.11.11')
    ap.add_argument('--eu4', default='D:/SteamLibrary/steamapps/common/Europa Universalis IV')
    ap.add_argument('--escenarios', help="scenario folder (default: the game's); use a scratch copy to test")
    a = ap.parse_args()
    if a.escenarios:
        import editor_core
        sc.SCEN_ROOT = a.escenarios
        editor_core.SCEN_DIR = a.escenarios
    r = convert(a.eu4, a.fecha, a.nombre)
    for n in r['notes']:
        print(n)
    for w in r['warnings'][:40]:
        print(w)
    print('%d avisos' % len(r['warnings']))


if __name__ == '__main__':
    st = {'owner': 'FRA'}
    cores = {'FRA'}
    _apply_dated(parse('1420.1.1 = { controller = ENG add_core = ENG } 1500.1.1 = { owner = SPA }'), (1444, 11, 11), ('owner', 'controller'), st, cores)
    assert st == {'owner': 'FRA', 'controller': 'ENG'} and cores == {'FRA', 'ENG'}, (st, cores)
    main()
