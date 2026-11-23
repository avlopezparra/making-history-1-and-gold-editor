"""New MH1 scenario from Hearts of Iron IV (the game or a mod that keeps HOI4's default map) on the WorldHOI4 regionpack.

WorldHOI4 is drawn in HOI4's own frame: a pixel (px, py) of map/provinces.bmp (5632x2048) is the point
(px * 360 / 5632 - 180, 80 - py * 360 / 5632). So each HOI4 province falls on the WorldHOI4 regions under its pixels.

What is read (mod files replace the game's at the same path; a mod with its own map/provinces.bmp is refused):
- history/states: owner (and the dated changes up to the chosen start date), manpower -> population, victory points -> cities,
  factories -> IPUs, resources (oil -> Oil; steel, aluminium, tungsten, chromium -> Metals; HOI4 has no coal), naval bases -> ports.
- history/countries: capital and ruling party (government); common/countries: colour; localisation: names; gfx/flags: flags.
Units, research, focuses and diplomacy are not converted (MH1 has no equivalent for most of them).
"""
import os
import re
from collections import Counter, defaultdict

import scenario_core as sc
from scenario_core import prop, objs

PACK = 'WorldHOI4'
APP = '394360'
W, H = 5632, 2048
K = 360.0 / W
GOV = {'democratic': 'Democratic', 'fascism': 'Fascist', 'communism': 'Communist', 'neutrality': 'Authoritarian'}
RES = {'oil': 'Oil', 'steel': 'Metals', 'aluminium': 'Metals', 'tungsten': 'Metals', 'chromium': 'Metals'}
# MH1's own names for the countries its shared-data events name (HOI4's localisation says «German Reich», «Kingdom of Hungary»...)
MH1_NAMES = {'GER': 'Germany', 'SOV': 'USSR', 'HUN': 'Hungary', 'ROM': 'Romania', 'IRQ': 'Iraq', 'JAP': 'Japan', 'GRE': 'Greece',
             'AFG': 'Afghanistan', 'SIA': 'Siam', 'URG': 'Uruguay', 'PHI': 'Philippines', 'MON': 'Mongolia', 'OMA': 'Oman',
             'KUW': 'Kuwait', 'JOR': 'Jordan', 'INS': 'Indonesia', 'PAL': 'Palestine'}
MIN_VP = 3          # victory points worth a city; every region with any victory point still gets its biggest one


# ------------------------------------------------------------------------------------------------ Paradox script
def parse(text):
    """Paradox script -> list of (key, value); value is a str or a nested list. 'a = { 1 2 3 }' gives a list of ('', '1')..."""
    text = re.sub(r'#[^\n]*', '', text)
    toks = re.findall(r'"[^"]*"|[{}=<>]|[^\s{}=<>"]+', text)
    pos = 0

    def block():
        nonlocal pos
        out = []
        while pos < len(toks):
            t = toks[pos]
            if t == '}':
                pos += 1
                return out
            pos += 1
            if pos < len(toks) and toks[pos] in ('=', '<', '>'):
                pos += 1
                if pos < len(toks) and toks[pos] in ('rgb', 'hsv', 'RGB', 'HSV'):
                    pos += 1
                if pos < len(toks) and toks[pos] == '{':
                    pos += 1
                    out.append((t.strip('"'), block()))
                elif pos < len(toks):
                    out.append((t.strip('"'), toks[pos].strip('"')))
                    pos += 1
            elif t == '{':
                out.append(('', block()))
            else:
                out.append(('', t.strip('"')))
        return out
    return block()


def get(blk, key, default=None):
    for k, v in blk:
        if k == key:
            return v
    return default


def getall(blk, key):
    return [v for k, v in blk if k == key]


def _date(s):
    m = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:\.\d+)?', s or '')
    return tuple(int(x) for x in m.groups()) if m else None


# ------------------------------------------------------------------------------------------------ sources
def _game_dirs():
    import gamepaths
    return [os.path.join(c, 'Hearts of Iron IV') for c in gamepaths._steam_libraries()
            if os.path.isfile(os.path.join(c, 'Hearts of Iron IV', 'map', 'provinces.bmp'))]


def _descriptor(path):
    try:
        b = parse(open(path, encoding='utf-8-sig', errors='replace').read())
    except OSError:
        return {}
    return {'name': get(b, 'name'), 'path': get(b, 'path'), 'replace': [v for k, v in b if k == 'replace_path']}


def sources():
    """[{'id', 'name', 'game', 'mod', 'dates'}]: the game and every mod (Workshop or local) that keeps HOI4's default map."""
    out = []
    for g in _game_dirs():
        out.append({'id': 'game:' + g, 'name': 'Hearts of Iron IV', 'game': g, 'mod': None})
        mods = []
        ws = os.path.join(os.path.dirname(os.path.dirname(g)), 'workshop', 'content', APP)
        if os.path.isdir(ws):
            for item in sorted(os.listdir(ws)):
                d = os.path.join(ws, item)
                mods.append((d, _descriptor(os.path.join(d, 'descriptor.mod')).get('name') or item))
        docs = os.path.join(os.path.expanduser('~'), 'Documents', 'Paradox Interactive', 'Hearts of Iron IV', 'mod')
        if os.path.isdir(docs):
            for f in sorted(os.listdir(docs)):
                if f.endswith('.mod'):
                    dsc = _descriptor(os.path.join(docs, f))
                    p = dsc.get('path')
                    if p and not os.path.isabs(p):
                        p = os.path.join(os.path.dirname(docs), p)
                    if p and os.path.isdir(p):
                        mods.append((p, dsc.get('name') or f[:-4]))
        for d, name in mods:
            if os.path.isfile(os.path.join(d, 'map', 'provinces.bmp')) or os.path.isfile(os.path.join(d, 'map', 'definition.csv')):
                continue            # its own map: the states would not match WorldHOI4
            if not os.path.isdir(os.path.join(d, 'history', 'states')) and not os.path.isdir(os.path.join(d, 'history', 'countries')):
                continue            # changes nothing this importer reads
            out.append({'id': 'mod:' + d, 'name': name, 'game': g, 'mod': d})
    for x in out:
        x['dates'] = Files(x['game'], x['mod']).bookmarks()
    return out


def check_source(sid):
    """The source the page asks for must be one of the listed ones (no arbitrary paths)."""
    for x in sources():
        if x['id'] == sid:
            return x
    raise ValueError('no se encuentra Hearts of Iron IV ni ese mod (%s)' % sid)


class Files:
    """HOI4 files with the mod on top: a mod file replaces the game's file at the same path; replace_path folders hide the game's."""
    def __init__(self, game, mod=None):
        self.game, self.mod = game, mod
        self.replace = set()
        if mod:
            d = _descriptor(os.path.join(mod, 'descriptor.mod'))
            self.replace = {os.path.normcase(os.path.normpath(r)) for r in d.get('replace', [])}

    def folder(self, rel):
        """{file name: full path} of a folder, the mod's version winning."""
        out = {}
        if os.path.normcase(os.path.normpath(rel)) not in self.replace:
            d = os.path.join(self.game, rel)
            if os.path.isdir(d):
                out.update({f: os.path.join(d, f) for f in os.listdir(d)})
        if self.mod:
            d = os.path.join(self.mod, rel)
            if os.path.isdir(d):
                out.update({f: os.path.join(d, f) for f in os.listdir(d)})
        return out

    def file(self, rel):
        if self.mod and os.path.isfile(os.path.join(self.mod, rel)):
            return os.path.join(self.mod, rel)
        p = os.path.join(self.game, rel)
        return p if os.path.isfile(p) else None

    def read(self, path):
        return parse(open(path, encoding='utf-8-sig', errors='replace').read())

    def bookmarks(self):
        dates = set()
        for f, p in self.folder(os.path.join('common', 'bookmarks')).items():
            if f.endswith('.txt'):
                for m in re.finditer(r'\bdate\s*=\s*(\d+\.\d+\.\d+)', open(p, encoding='utf-8-sig', errors='replace').read()):
                    dates.add(m.group(1))
        return sorted(dates, key=_date) or ['1936.1.1']

    def localisation(self):
        loc = {}
        for sub in ('english', os.path.join('english', 'replace')):
            for f, p in sorted(self.folder(os.path.join('localisation', sub)).items()):
                if f.endswith('.yml'):
                    for m in re.finditer(r'^\s*([A-Za-z0-9_.\-]+):\d*\s*"(.*)"\s*$', open(p, encoding='utf-8-sig', errors='replace').read(), re.M):
                        loc[m.group(1)] = m.group(2)
        return loc


# ------------------------------------------------------------------------------------------------ reading HOI4
def read(src, start):
    """Everything the scenario needs from HOI4 at date 'start' ('1936.1.1')."""
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    F = Files(src['game'], src['mod'])
    when = _date(start)
    if not when:
        raise ValueError('fecha no válida: %s (formato año.mes.día, p. ej. 1936.1.1)' % start)
    loc = F.localisation()
    img = np.asarray(Image.open(F.file(os.path.join('map', 'provinces.bmp'))).convert('RGB')).astype(np.int32)
    if img.shape[:2] != (H, W):
        raise ValueError('el mapa de HOI4 de esta fuente no mide %dx%d: no encaja con WorldHOI4' % (W, H))
    key = (img[..., 0] << 16) | (img[..., 1] << 8) | img[..., 2]
    col, coastal = {}, {}
    for line in open(F.file(os.path.join('map', 'definition.csv')), encoding='latin1'):
        x = line.strip().split(';')
        if len(x) > 5 and x[0].isdigit():
            pid = int(x[0])
            col[(int(x[1]) << 16) | (int(x[2]) << 8) | int(x[3])] = pid
            coastal[pid] = x[5] == 'true'
    u, inv = np.unique(key, return_inverse=True)
    ids = np.array([col.get(int(v), 0) for v in u], np.int32)[inv].reshape(key.shape)
    del img, key
    flat = ids.ravel()
    n = int(ids.max()) + 1
    cnt = np.bincount(flat, minlength=n)
    sx = np.bincount(flat, weights=np.tile(np.arange(W, dtype=np.float64), H), minlength=n)
    sy = np.bincount(flat, weights=np.repeat(np.arange(H, dtype=np.float64), W), minlength=n)
    centroid = {p: ((sx[p] / cnt[p] + 0.5) * K - 180, 80 - (sy[p] / cnt[p] + 0.5) * K) for p in range(1, n) if cnt[p]}

    states = {}
    for f, p in F.folder(os.path.join('history', 'states')).items():
        if not f.endswith('.txt'):
            continue
        for k, st in F.read(p):
            if k != 'state' or not isinstance(st, list):
                continue
            sid = int(get(st, 'id', 0) or 0)
            hist = get(st, 'history', []) or []
            owner, ctl = get(hist, 'owner'), get(hist, 'controller')
            vps = {}

            def vp(block):
                for v in getall(block, 'victory_points'):
                    nums = [x for _, x in v] if isinstance(v, list) else []
                    for i in range(0, len(nums) - 1, 2):
                        try:
                            vps[int(nums[i])] = float(nums[i + 1])
                        except ValueError:
                            pass
            vp(hist)
            bld = get(hist, 'buildings', []) or []
            for dk, blk in sorted(((dk, blk) for dk, blk in hist if _date(dk) and isinstance(blk, list)), key=lambda kv: _date(kv[0])):
                if _date(dk) > when:
                    continue
                owner = get(blk, 'owner', owner)
                ctl = get(blk, 'controller', ctl)
                vp(blk)
            fac = sum(float(get(bld, b, 0) or 0) for b in ('industrial_complex', 'arms_factory', 'dockyard'))
            naval = {int(k_) for k_, v in bld if k_.isdigit() and isinstance(v, list) and get(v, 'naval_base')}
            res = {k_: float(v) for k_, v in (get(st, 'resources', []) or []) if k_ in RES}
            provs = [int(x) for _, x in (get(st, 'provinces', []) or []) if str(x).isdigit()]
            raw = get(st, 'name', 'STATE_%d' % sid)
            states[sid] = {'id': sid, 'name': loc.get(raw, raw), 'owner': owner, 'ctl': ctl or owner,
                           'pop': int(float(get(st, 'manpower', 0) or 0)), 'vps': vps, 'factories': fac, 'naval': naval, 'res': res,
                           'provs': provs, 'impassable': get(st, 'impassable') == 'yes'}

    tags = {}
    for f, p in F.folder(os.path.join('common', 'country_tags')).items():
        if f.endswith('.txt'):
            for k, v in F.read(p):
                if re.fullmatch(r'[A-Z0-9]{3}', k) and isinstance(v, str):
                    tags[k] = v
    hist_files = {f[:3]: p for f, p in F.folder(os.path.join('history', 'countries')).items() if f.endswith('.txt')}
    nations = {}
    for tag in {s['owner'] for s in states.values() if s['owner']} | {s['ctl'] for s in states.values() if s['ctl']}:
        cap, party = None, None
        if tag in hist_files:
            h = F.read(hist_files[tag])
            cap = get(h, 'capital')
            party = get(get(h, 'set_politics', []) or [], 'ruling_party')
            for dk, blk in sorted(((dk, blk) for dk, blk in h if _date(dk) and isinstance(blk, list)), key=lambda kv: _date(kv[0])):
                if _date(dk) <= when:
                    cap = get(blk, 'capital', cap)
                    party = get(get(blk, 'set_politics', []) or [], 'ruling_party', party)
        color = None
        cf = F.file(os.path.join('common', tags[tag])) if tags.get(tag) else None
        if cf:
            c = get(F.read(cf), 'color')
            nums = []
            for _, x in (c if isinstance(c, list) else []):
                try:
                    nums.append(float(x))
                except ValueError:
                    pass
            if len(nums) >= 3:
                if max(nums[:3]) <= 1.0:        # hsv { h s v }
                    import colorsys
                    nums = [v * 255 for v in colorsys.hsv_to_rgb(*nums[:3])]
                color = '#%02x%02x%02x' % tuple(int(max(0, min(255, v))) for v in nums[:3])
        flag = None
        for fn in ('%s_%s.tga' % (tag, party), '%s.tga' % tag):
            flag = F.file(os.path.join('gfx', 'flags', fn))
            if flag:
                break
        nations[tag] = {'tag': tag, 'name': loc.get('%s_%s' % (tag, party)) or loc.get(tag) or tag, 'gov': GOV.get(party, 'Authoritarian'),
                        'color': color, 'capital': int(cap) if str(cap or '').isdigit() else None, 'flag': flag}
    return {'states': states, 'nations': nations, 'centroid': centroid, 'coastal': coastal, 'ids': ids, 'loc': loc, 'date': when}


# ------------------------------------------------------------------------------------------------ building the scenario
def _region_states(pm, land, data):
    """{region: [(state id, pixels)]} biggest first: which HOI4 states lie under each WorldHOI4 land region."""
    import numpy as np
    from PIL import Image, ImageDraw
    state_of = np.zeros(int(data['ids'].max()) + 1, np.int32)
    for s in data['states'].values():
        for p in s['provs']:
            if p < len(state_of):
                state_of[p] = s['id']
    S = state_of[data['ids']]
    canvas = Image.new('I', (W, H), 0)
    d = ImageDraw.Draw(canvas)
    for i, n in enumerate(land, 1):
        g = pm.geom(n)
        for poly in (getattr(g, 'geoms', [g]) if g is not None else []):
            if poly.geom_type == 'Polygon':
                d.polygon([((x + 180) / K, (80 - y) / K) for x, y in poly.exterior.coords], fill=i)
    R = np.asarray(canvas, np.int32)
    m = (R > 0) & (S > 0)
    pairs = Counter(zip(R[m].tolist(), S[m].tolist()))
    out = defaultdict(list)
    for (r, s), c in pairs.items():
        out[land[r - 1]].append((s, c))
    return {r: sorted(v, key=lambda x: -x[1]) for r, v in out.items()}


def convert(src, start, name, template=None, display=None, open_scenario=None, progress=None):
    """Creates scenario 'name' on WorldHOI4 from HOI4 source 'src' (from sources()) at date 'start' and saves it.
    Returns {'name', 'notes', 'warnings'}. On an error halfway the half-made folder is removed."""
    import shutil
    import editor_core
    import scenario_new
    import scenario_layers as L
    if not os.path.exists(os.path.join(editor_core.MAPS, PACK, 'xml', 'regions.bin')):
        raise ValueError('instala primero el regionpack WorldHOI4: el importador de HOI4 lo necesita (está dibujado con el mapa de HOI4)')
    pm = L.pack_map(PACK)
    tick = progress or (lambda pct, msg: None)
    tick(2, 'Leyendo Hearts of Iron IV')
    data = read(src, start)
    y, mo, d = data['date']
    name = scenario_new.create_scenario(name, PACK, template, display or name,
                                        'Importado de Hearts of Iron IV (%s, %d-%02d-%02d)' % (src['name'], y, mo, d), y, mo, d)
    try:
        notes, warns = ['escenario %s creado (%02d/%02d/%d, regionpack %s)' % (name, d, mo, y, PACK)], []
        s = (open_scenario or sc.Scenario)(name)
        _build(s, data, pm, notes, warns, tick)
        _fix_event_regions(s, pm, notes)
        tick(97, 'Guardando')
        s.s.save(scenario=s)
    except Exception:
        shutil.rmtree(os.path.join(sc.SCEN_ROOT, name), ignore_errors=True)
        raise
    return {'name': name, 'notes': notes, 'warnings': warns}


def _fix_event_regions(s, pm, notes):
    """The template's events name World regions (Muscovy, Lazio Umbria...): each one -> the WorldHOI4 land region under its centre."""
    import editor_core
    import scenario_events as E
    import scenario_layers as L
    from shapely.geometry import Point
    prj = L.Projection.load(os.path.join(editor_core.MAPS, PACK))
    if prj is None or not os.path.exists(os.path.join(editor_core.MAPS, 'World', 'xml', 'regions.bin')):
        return
    world = L.pack_map('World')
    have = {prop(r, 'strName') for r in s.regions()}
    land = [n for n, sea in pm.sea.items() if not sea and n in have and pm.geom(n) is not None]
    done = {}
    for ev, o, n, r in E._event_region_refs(s):
        if r in have or world.geom(r) is None:
            continue
        if r not in done:
            c = world.geom(r).representative_point()
            pt = Point(*prj.point(c.x, c.y))
            done[r] = min(land, key=lambda x: pm.geom(x).distance(pt))
        E.fix_event_region(s, s.s.eid(o), n, r, 'replace', done[r])
    if done:
        notes.append('regiones de los eventos cambiadas por las de WorldHOI4: %s' % ', '.join('%s → %s' % kv for kv in sorted(done.items())))


def _safe(n):
    return re.sub(r'[\\/:*?"<>|]', '', n or '').strip()


def pick_cities(cands, owner):
    """Victory points -> cities without duplicates: biggest first; one name once; one city per spot (0.25 degrees) in a region;
    small ones (< MIN_VP) only when they are the biggest of their region. cands: (vp, state, province, name, x, y, region)."""
    cands = sorted(cands, key=lambda c: -c[0])
    best_in = {}
    for c in cands:
        best_in.setdefault(c[6], c)
    keep, names, spots = [], set(), defaultdict(list)
    for c in cands:
        val, sid, pv, nm, x, y, r = c
        if r not in owner or (val < MIN_VP and best_in[r] is not c):
            continue
        if nm.lower() in names or any(abs(x - a) < 0.25 and abs(y - b) < 0.25 for a, b in spots[r]):
            continue
        names.add(nm.lower())
        spots[r].append((x, y))
        keep.append(c)
    return keep


def _build(s, data, pm, notes, warns, tick):
    import scenario_new
    import scenario_layers as L
    from shapely.geometry import Point
    S, N = data['states'], data['nations']
    skip = {'BasicRegionLists', 'Historic'}
    land = [n for n, sea in pm.sea.items() if not sea and n not in skip]
    seas = [n for n, sea in pm.sea.items() if sea and n not in skip]
    tick(10, 'Situando los estados de HOI4 en las regiones')
    rs = _region_states(pm, land, data)
    owner = {}          # the state covering most of the region (impassable wasteland only when nothing else)
    for r, lst in rs.items():
        ok = [(sid, c) for sid, c in lst if S[sid]['owner'] and not S[sid]['impassable']] or [(sid, c) for sid, c in lst if S[sid]['owner']]
        if ok:
            owner[r] = (S[ok[0][0]]['owner'], S[ok[0][0]]['ctl'] or S[ok[0][0]]['owner'])
    for _ in range(3):              # regions under no state (tiny islands, gaps): their neighbours' owner
        for r in land:
            if r not in owner:
                c = Counter(owner[x][0] for x in pm.nb.get(r, []) if x in owner)
                if c:
                    o = c.most_common(1)[0][0]
                    owner[r] = (o, o)
    for r in land:          # islands too small for HOI4's pixels and with no owned neighbour: the nearest owned region's owner
        g = pm.geom(r)
        if r not in owner and g is not None and owner:
            near = min((x for x in owner if pm.geom(x) is not None), key=lambda x: g.distance(pm.geom(x)))
            owner[r] = (owner[near][0], owner[near][0])
    present =sorted({o for o, _ in owner.values()} | {c for _, c in owner.values()}, key=lambda t: N.get(t, {}).get('name', t))
    nat, used = {}, set()
    for t in present:
        n = MH1_NAMES.get(t) or _safe(N.get(t, {}).get('name')) or t
        while n.lower() in used:
            n += ' (%s)' % t
        used.add(n.lower())
        nat[t] = n

    tick(20, 'Creando las naciones')
    for t in present:
        v = N.get(t, {})
        scenario_new.create_nation(s, {'name': nat[t], 'color': v.get('color'), 'gov': v.get('gov', 'Authoritarian'), 'playable': True},
                                   need_capital=False)
    notes.append('%d naciones' % len(present))

    tick(30, 'Creando las regiones')
    share = defaultdict(int)        # each state's manpower is shared among its regions by the pixels each one holds
    for r, lst in rs.items():
        for sid, c in lst:
            share[sid] += c
    total = 0
    for r in land:
        if r not in owner:
            warns.append('AVISO: %s no está bajo ningún estado de HOI4 ni tiene vecinas con dueño: no se ha creado' % r)
            continue
        pop = max(sum(S[sid]['pop'] * c // max(1, share[sid]) for sid, c in rs.get(r, [])), 1000)   # 0-2 inhabitants: the game takes it as empty
        o, ctl = owner[r]
        sc.add_new_region(s, r, owner=nat[o], terrain='Plains', population=pop)
        if ctl != o:
            reg = next(x for x in s.countries()[nat[o]] if x.tag == 'object' and x.get('type') == 'Region' and prop(x, 'strName') == r)
            s.update(s.s.eid(reg), {'strController': nat[ctl]})
        total += pop
    for n in seas:
        L.add_sea_region(s, n)
    notes.append('%d regiones de tierra y %d de mar; %s habitantes' % (len(owner), len(seas), format(total, ',').replace(',', '.')))

    tick(50, 'Creando las ciudades (puntos de victoria)')
    geo = {r: pm.geom(r) for r in land}

    def region_at(x, y):
        p = Point(x, y)
        for r, g in geo.items():
            if g is not None and g.bounds[0] <= x <= g.bounds[2] and g.bounds[1] <= y <= g.bounds[3] and g.contains(p):
                return r
        return None
    cands = []
    for st in S.values():
        for pv, val in st['vps'].items():
            nm = _safe(data['loc'].get('VICTORY_POINTS_%d' % pv))
            if pv in data['centroid'] and nm:
                x, y = data['centroid'][pv]
                r = region_at(x, y)
                if r:
                    cands.append((val, st['id'], pv, nm, x, y, r))
    keep = pick_cities(cands, owner)
    weight = defaultdict(float)
    for c in keep:
        weight[c[1]] += c[0]
    regpop = {prop(r, 'strName'): int(prop(r, 'nPopulation') or 0) for r in s.regions(sea=False)}
    ncity = Counter(c[6] for c in keep)
    made, city_of_state = 0, defaultdict(list)
    for val, sid, pv, nm, x, y, r in keep:
        st = S[sid]
        ipus = max(1, int(round(2 * st['factories'] * val / max(1.0, weight[sid]))))
        port = None
        if pv in st['naval'] or (data['coastal'].get(pv) and val >= 10):
            port = next((z for z in pm.nb.get(r, []) if pm.sea.get(z)), None)
        try:
            L.create_city(s, nm, x, y, ipus, max(1000, regpop.get(r, 0) // (10 * ncity[r])), nm, port, region=r)
            made += 1
            city_of_state[sid].append((val, nm, owner[r][0]))
        except ValueError as e:
            warns.append('AVISO ciudad %s: %s' % (nm, e))
    notes.append('%d ciudades (de %d puntos de victoria, sin repetir nombre ni sitio)' % (made, len(cands)))
    for t in present:
        c = sorted((x for x in city_of_state.get(N.get(t, {}).get('capital'), []) if x[2] == t), reverse=True)    # in its own land, the biggest
        if c:
            scenario_new.set_capital(s, nat[t], c[0][1])
            continue
        own = [ci for r in s.regions(sea=False) if prop(r, 'strOwner') == nat[t] for ci in objs(r) if ci.get('type') == 'City']
        if own:         # its capital state has no city here: its first city
            scenario_new.set_capital(s, nat[t], prop(own[0], 'strName'))
            continue
        # no city at all (its victory points fell on other regions or were repeated names): one in its biggest region
        regs = [r for r in land if owner.get(r, (None,))[0] == t and geo.get(r) is not None]
        if not regs:
            continue
        r = max(regs, key=lambda r: geo[r].area)
        p = geo[r].representative_point()
        nm = _safe(r)
        while nm.lower() in {prop(c, 'strName').lower() for c in s.all('City')}:
            nm += ' City'
        try:
            L.create_city(s, nm, p.x, p.y, 1, max(1000, regpop.get(r, 0) // 10), nm, None, region=r)
            scenario_new.set_capital(s, nat[t], nm)
            made += 1
        except ValueError as e:
            warns.append('AVISO capital de %s: %s' % (nat[t], e))

    tick(70, 'Creando los recursos')
    prods, none = 0, 0
    for st in S.values():
        if not st['res']:
            continue
        regs = [r for r, lst in rs.items() if r in owner and any(sid == st['id'] for sid, _ in lst)]
        if not regs:
            none += 1
            continue
        r = max(regs, key=lambda r: dict(rs[r]).get(st['id'], 0))
        by_kind = defaultdict(float)
        for k, v in st['res'].items():
            by_kind[RES[k]] += v
        for kind, amount in by_kind.items():
            x, y = L.random_point_in(geo[r], seed=r + kind)
            try:
                L.create_producer(s, '%s %s' % (st['name'], kind), kind, x, y, max(1, int(round(amount / 4))))
                prods += 1
            except ValueError as e:
                warns.append('AVISO recurso %s de %s: %s' % (kind, st['name'], e))
    notes.append('%d recursos (petróleo; acero, aluminio, tungsteno y cromo como metales; HOI4 no tiene carbón)' % prods)
    if none:
        warns.append('%d estados con recursos no caen en ninguna región del mapa' % none)

    tick(88, 'Banderas')
    flags = 0
    for t in present:
        f = N.get(t, {}).get('flag')
        if f:
            try:
                flags += _flag(s, nat[t], f)
            except Exception as e:      # an unreadable image must not stop the import
                warns.append('AVISO bandera de %s: %s' % (nat[t], e))
    notes.append('banderas de HOI4 para %d de %d naciones' % (flags, len(present)))
    notes.append('no se importan unidades, investigación, focos nacionales ni diplomacia de HOI4')
    warns += ['AVISO naciones: %s' % x for x in scenario_new.check_nations(s)]


def _flag(s, name, path):
    from PIL import Image
    import image_tools as T
    out = os.path.join(T.countries_dir(s.name), T.safe_name(name))
    files = T.flag_set(Image.open(path).convert('RGBA'), only='flag')
    T.write_files({os.path.join(out, k): T.encode(im, k, T.FLAG_FMT.get(k, T.DEFAULT_FMT)) for k, im in files.items()}, 'bandera-' + T.safe_name(name))
    return 1


if __name__ == '__main__':      # self-check of the parts that need no game files
    b = parse('state={ id=1 name="STATE_1" # c\n history={ owner = FRA victory_points = { 3838 1 } 1939.1.1 = { owner = GER } } }')
    st = get(b, 'state')
    assert get(st, 'id') == '1' and get(get(st, 'history'), 'owner') == 'FRA'
    assert get(get(get(st, 'history'), '1939.1.1'), 'owner') == 'GER'
    assert _date('1936.1.1.12') == (1936, 1, 1)
    own = {'A': 1, 'B': 1}
    c = [(10, 1, 1, 'Paris', 2.0, 48.0, 'A'), (5, 1, 2, 'Paris', 3.0, 47.0, 'A'), (1, 1, 3, 'Lyon', 2.1, 48.1, 'A'),
         (1, 2, 4, 'Brest', 9.0, 9.0, 'B'), (2, 2, 5, 'Nantes', 5.0, 5.0, 'B')]
    k = pick_cities(c, own)
    assert [x[3] for x in k] == ['Paris', 'Nantes'], k
    print('ok')
