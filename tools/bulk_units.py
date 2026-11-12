"""Bulk creation of units (armies, air forces and fleets) for many countries at once, in the scenario editor.

plan() computes what would be created (country, type, region, position and units) without touching anything; apply() creates it in memory with
the same functions as «Añadir ejército / fuerza aérea / flota»; undo() removes what the last apply() created. The
scenario is only written with «Guardar», as always.
"""
import math
import random

import scenario_core as sc
from scenario_core import prop, objs

KINDS = {'land': ('Army', 'UNIT_TYPE_ARMY'), 'air': ('AirForce', 'UNIT_TYPE_AIR_FORCE'), 'navy': ('Fleet', 'UNIT_TYPE_NAVY')}
# «Ejército base»: units per country type (playable > major > minor)
BASE = {'playable': {'land': 12, 'air': 4, 'navy': 4}, 'major': {'land': 8, 'air': 3, 'navy': 3}, 'minor': {'land': 3, 'air': 1, 'navy': 1}}
CAP = {'land': 40, 'air': 16, 'navy': 16}     # cap of the random base army
MIN_GAP = 0.6                                  # minimum separation (degrees) between stacks, cities and the region's units
_last = []                                     # ids created by the last apply() (for undo)


def tier(c):
    t = prop(c, 'eCountryType')
    if t == 'COUNTRYTYPE_PLAYABLE' or prop(c, 'bNonPlayable') == 'false':
        return 'playable'
    return 'major' if t == 'COUNTRYTYPE_FEATURED' else 'minor'


def targets(s, sel):
    """Countries with territory per sel: {'countries': [...]} and/or {'tiers': ['playable', 'major', 'minor']} (combined with «or»);
    {'all': true} or nothing = all."""
    landed = {prop(r, 'strOwner') for r in s.regions(sea=False)}
    cs = s.countries()
    names, tiers = set(sel.get('countries') or []), set(sel.get('tiers') or [])
    out = []
    for n, c in sorted(cs.items()):
        if n not in landed:
            continue
        if sel.get('all') or (not names and not tiers) or n in names or tier(c) in tiers:
            out.append(n)
    return out


def _allowed(s, country):
    """{kind: [templates]} the country may have: those not depending on research, or whose research is complete."""
    research = {prop(p, 'strName') for p in s.all_prefix('ResearchProj')}
    done = set()
    pd = next((p for p in s.all('MEPlayerData') if prop(p, 'strOwner') == country), None)
    if pd is not None:
        done = {prop(o, 'strProjectName') for o in pd.iter('object')
                if o.get('type') == 'ResearchProjectInitRef' and prop(o, 'eResearchState') == 'RESEARCH_COMPLETED'}

    def gate(n):
        for k in (n, n + 's', n.rstrip('s')):
            if k in research:
                return k
        return None
    out = {k: [] for k in KINDS}
    cost = {}
    for t in s.all('UnitTemplate'):
        n, e = prop(t, 'strName'), prop(t, 'eType')
        g = gate(n)
        for k, (_, et) in KINDS.items():
            if e == et:
                c = prop(t, 'nMaintenanceCost') or ''
                cost.setdefault(k, []).append((int(c) if c.isdigit() else 10 ** 9, n))
                if g is None or g in done:
                    out[k].append(n)
    # many scenarios hand out units without marking the research as done: what the country already has is allowed too,
    # and a country with nothing of a kind may use the cheapest template of that kind
    for k, (t, _) in KINDS.items():
        for g in s.all(t):
            if prop(g, 'strOwner') == country:
                out[k] += [prop(u, 'strName') for u in objs(g) if u.get('type') == 'UnitSummary' and prop(u, 'strName') not in out[k]]
        if not out[k] and cost.get(k):
            out[k].append(min(cost[k])[1])
    return out


def _usage(s):
    use = {}
    for k, (t, _) in KINDS.items():
        for g in s.all(t):
            for u in objs(g):
                if u.get('type') == 'UnitSummary':
                    use[(k, prop(u, 'strName'))] = use.get((k, prop(u, 'strName')), 0) + 1
    return use


def _pick(s, country, kind, allowed, use):
    """Up to two templates for the base army: those the country already uses, otherwise the scenario's most used (allowed)."""
    t = KINDS[kind][0]
    mine = []
    for g in s.all(t):
        if prop(g, 'strOwner') == country:
            mine += [prop(u, 'strName') for u in objs(g) if u.get('type') == 'UnitSummary' and prop(u, 'strName') in allowed]
    pool = list(dict.fromkeys(mine)) or sorted(allowed, key=lambda n: -use.get((kind, n), 0))
    return pool[:2]


def _pop(s, country):
    return sum(int(prop(r, 'nPopulation') or 0) for r in s.regions(sea=False)
               if prop(r, 'strOwner') == country and (prop(r, 'nPopulation') or '').isdigit())


def _split(n, parts):
    parts = max(1, min(parts, n))
    return [n // parts + (1 if i < n % parts else 0) for i in range(parts)]


def _split_units(units, parts):
    """Splits the unit list into 'parts' similar stacks (each type is spread among the stacks)."""
    out = [[] for _ in range(parts)]
    for u in units:
        for i, n in enumerate(_split(int(u['n']), parts)):
            if n:
                out[i].append({'type': u['type'], 'n': n})
    return [x for x in out if x]


def _occupied(s):
    pts = {}
    for t in ('Army', 'AirForce', 'Fleet'):
        for g in s.all(t):
            xy = sc.parse_vec(prop(g, 'vecPosition'))
            if xy:
                pts.setdefault(prop(g, 'strRegion'), []).append(xy[:2])
    for r in s.regions():
        for c in objs(r):
            if c.get('type') == 'City':
                xy = sc.parse_vec(prop(c, 'vecPosition'))
                if xy:
                    pts.setdefault(prop(r, 'strName'), []).append(xy[:2])
    return pts


def _spot(geom, taken, rnd):
    """Point inside the polygon, far from 'taken'; if there is no room, the farthest of those tried."""
    from shapely.geometry import Point
    x0, y0, x1, y1 = geom.bounds
    best, bd = None, -1
    w = min(x1 - x0, y1 - y0)
    inner = geom.buffer(-w * 0.08) if w > 0.5 else geom
    inner = inner if not inner.is_empty else geom
    for _ in range(80):
        p = Point(rnd.uniform(x0, x1), rnd.uniform(y0, y1))
        if not inner.contains(p):
            continue
        d = min((math.hypot(p.x - a, p.y - b) for a, b in taken), default=99)
        if d >= MIN_GAP:
            return (p.x, p.y)
        if d > bd:
            best, bd = (p.x, p.y), d
    if best is None:
        p = geom.representative_point()
        best = (p.x, p.y)
    return best


def plan(s, sel, mode='custom', units=None, seed=None, navy_seas=None, lacking=False):
    """What would be created. mode 'custom': units={'land': [{'type', 'n'}], 'air': [...], 'navy': [...]} for each country;
    'base': BASE by country type; 'random': random mix scaled by population (CAP limits).
    navy_seas: {country: sea region} to choose where its fleet goes. lacking: each branch (land, air, sea) only for
    countries that have no unit of that branch («give forces to those who have none»).
    Returns {'items': [...], 'skipped': [...]}."""
    has = {k: {prop(g, 'strOwner') for g in s.all(t)} for k, (t, _) in KINDS.items()} if lacking else {}
    import scenario_layers as sl
    rnd = random.Random(seed)
    pm = sl.PackMap(sc.pack_of(s))
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    seas = {prop(r, 'strName') for r in s.regions(sea=True)}
    taken = _occupied(s)
    use = _usage(s)
    cs = s.countries()
    countries = targets(s, sel or {})
    pops = {c: _pop(s, c) for c in countries}
    med = sorted(pops.values())[len(pops) // 2] if pops else 1
    items, skipped = [], []
    for c in countries:
        allowed = _allowed(s, c)
        want = {}
        if mode == 'custom':
            for k in KINDS:
                asked = (units or {}).get(k) or []
                want[k] = [u for u in asked if int(u.get('n') or 0) > 0 and u.get('type') in allowed[k]]
                bad = [u['type'] for u in asked if u.get('type') and int(u.get('n') or 0) > 0 and u['type'] not in allowed[k]]
                if bad:
                    skipped.append({'country': c, 'why': 'sin la tecnología para %s' % ', '.join(bad)})
        else:
            b = BASE[tier(cs[c])]
            f = max(0.5, min(3.0, math.sqrt((pops[c] or 1) / (med or 1)))) * rnd.uniform(0.7, 1.3) if mode == 'random' else 1.0
            for k in KINDS:
                n = max(1, min(CAP[k], int(round(b[k] * f))))
                ts = _pick(s, c, k, allowed[k], use)
                if not ts:
                    want[k] = []
                elif mode == 'random' and len(ts) > 1 and n > 1:
                    a = rnd.randint(max(1, n // 3), max(1, n - n // 3))
                    want[k] = [{'type': ts[0], 'n': a}] + ([{'type': ts[1], 'n': n - a}] if n - a > 0 else [])
                else:
                    want[k] = [{'type': ts[0], 'n': n - n // 3}] + ([{'type': ts[1], 'n': n // 3}] if len(ts) > 1 and n // 3 else [])
        for k in has:
            if c in has[k]:
                want[k] = []                # already has that branch
        if lacking and not any(want.values()):
            continue
        mine = sorted((r for r in land.values() if prop(r, 'strOwner') == c),
                      key=lambda r: -int(prop(r, 'nPopulation')) if (prop(r, 'nPopulation') or '').isdigit() else 0)
        names = [prop(r, 'strName') for r in mine if pm.geom(prop(r, 'strName')) is not None]
        if not names:
            skipped.append({'country': c, 'why': 'sus regiones no están en el mapa'})
            continue
        # army: several stacks in different regions (up to 3, or fewer if it has few regions)
        land_total = sum(int(u['n']) for u in want.get('land', []))
        if land_total:
            for i, chunk in enumerate(_split_units(want['land'], min(3, len(names), land_total))):
                reg = names[i % len(names)]
                xy = _spot(pm.geom(reg), taken.setdefault(reg, []), rnd)
                taken[reg].append(xy)
                items.append({'country': c, 'kind': 'land', 'region': reg, 'xy': xy, 'units': chunk})
        if want.get('air'):
            reg = names[1] if len(names) > 1 else names[0]
            xy = _spot(pm.geom(reg), taken.setdefault(reg, []), rnd)
            taken[reg].append(xy)
            items.append({'country': c, 'kind': 'air', 'region': reg, 'xy': xy, 'units': want['air']})
        if want.get('navy'):
            options = []
            for r in names:
                for n in pm.nb.get(r, []):
                    if pm.sea.get(n) and n in seas and n not in options:
                        options.append(n)
            if not options:
                skipped.append({'country': c, 'why': 'sin costa: no se crea flota'})
            else:
                sea = (navy_seas or {}).get(c)
                sea = sea if sea in options else options[0]
                coast = next(r for r in names if sea in pm.nb.get(r, []))
                g = pm.geom(sea)
                near = g.intersection(pm.geom(coast).buffer(1.5))
                xy = _spot(near if not near.is_empty and near.area > 0 else g, taken.setdefault(sea, []), rnd)
                taken[sea].append(xy)
                items.append({'country': c, 'kind': 'navy', 'region': sea, 'xy': xy, 'units': want['navy'], 'seas': options})
    for it in items:
        it['xy'] = [round(it['xy'][0], 4), round(it['xy'][1], 4)]
    return {'items': items, 'skipped': skipped, 'countries': len(countries)}


def apply(s, items):
    """Creates the plan in memory («Guardar» still needed). Returns notes; remembers the ids for undo()."""
    import scenario_layers as sl
    import scenario_create as scr
    st = s.s
    made = []
    label = {'land': 'Army', 'air': 'Air Force', 'navy': 'Fleet'}
    fn = {'land': sl.create_army, 'air': scr.create_airforce, 'navy': scr.create_fleet}
    total = 0
    for it in items:
        t = KINDS[it['kind']][0]
        have = {prop(g, 'strName') for g in s.all(t) if prop(g, 'strOwner') == it['country']}
        k, name = 1, '%s %s' % (it['country'], label[it['kind']])
        while name in have:
            k += 1
            name = '%s %s %d' % (it['country'], label[it['kind']], k)
        eid, _ = fn[it['kind']](s, it['country'], name, it['region'], it['units'])
        st.set_prop(st.get(eid), 'vecPosition', '[%r, %r, 0]' % (float(it['xy'][0]), float(it['xy'][1])))
        made.append(eid)
        total += sum(int(u['n']) for u in it['units'])
    _last[:] = made
    return ['%d grupos creados (%d unidades) en %d países' % (len(made), total, len({it['country'] for it in items}))]


def _referenced(s):
    """Names of groups mentioned by some event or object (e.g. a condition's strValue): those are never removed."""
    groups = [g for t, _ in KINDS.values() for g in s.all(t)]
    names = {prop(g, 'strName') for g in groups}
    own = {id(p) for g in groups for p in g if p.tag == 'property' and p.get('name') == 'strName'}
    return {e.get('value') for doc in s.s.docs.values() for e in doc.getroot().iter('property')
            if e.get('value') in names and id(e) not in own and e.get('name') not in ('strOwner', 'strRegion', 'strCity')}


def _size(g):
    return sum(int(prop(o, 'nNumber') or 0) for o in objs(g) if o.get('type') == 'UnitSummary')


def stacks(s):
    """Groups of the same country and type in the same place: same region, city and position (or no position: then the game
    draws them all at the same point). Each stack is merged into one group: the one an event names or, otherwise, the largest."""
    ref = _referenced(s)
    out = []
    for kind, (t, _) in KINDS.items():
        piles = {}
        for g in s.all(t):
            key = (prop(g, 'strOwner'), prop(g, 'strRegion'), prop(g, 'strCity') or '', (prop(g, 'vecPosition') or '').replace(' ', ''))
            piles.setdefault(key, []).append(g)
        for (owner, region, _c, _p), gs in piles.items():
            gs.sort(key=lambda g: (prop(g, 'strName') not in ref, -_size(g)))
            merge = [g for g in gs[1:] if prop(g, 'strName') not in ref]
            if merge:
                out.append({'kind': kind, 'country': owner, 'region': region, 'keep': s.s.eid(gs[0]), 'keep_name': prop(gs[0], 'strName'),
                            'merge': [s.s.eid(g) for g in merge], 'merge_names': [prop(g, 'strName') for g in merge],
                            'units': sum(_size(g) for g in [gs[0]] + merge)})
    return out


def merge_stacks(s, piles):
    """Merges each stack from stacks() into its group: sums units of the same type and removes the other groups (in memory)."""
    st = s.s
    groups = units = 0
    for p in piles:
        keep = st.get(p['keep'])
        if keep is None:
            continue
        lines = {prop(o, 'strName'): o for o in objs(keep) if o.get('type') == 'UnitSummary'}
        for eid in p['merge']:
            g = st.get(eid)
            if g is None:
                continue
            for o in [o for o in objs(g) if o.get('type') == 'UnitSummary']:
                n, t = int(prop(o, 'nNumber') or 0), prop(o, 'strName')
                units += n
                if t in lines:
                    st.set_prop(lines[t], 'nNumber', str(int(prop(lines[t], 'nNumber') or 0) + n))
                else:
                    st.remove(o)
                    st.attach(o, keep)
                    lines[t] = o
            st.remove(g)
            groups += 1
    return ['%d grupos juntados con el que estaba en el mismo sitio (%d unidades)' % (groups, units)]


def undo(s):
    """Removes what the last apply() created (if still in memory)."""
    st = s.s
    n = 0
    for eid in _last:
        el = st.get(eid)
        if el is not None:
            st.remove(el)
            n += 1
    _last[:] = []
    return ['%d grupos quitados' % n]
