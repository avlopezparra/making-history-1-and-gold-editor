"""Scenario editor functions that work on the map and on shared files.

- mapdata: what the map layers need (owners, culture, terrain, ideology, historic regions,
  alliances, wars and surrendered countries that can be liberated).
- toggle_historic / toggle_alliance: add or remove with one click.
- set_string: visible text of a SID (e.g. renaming a country) in the scenario game/stringTable.xml.
- set_pack: regionpack (map) of the scenario.
- ScenarioDefaults files: game scenarios load their shared data from there; on save you choose
  between replacing the defaults (affects everyone using them) or saving as a new independent scenario.
- ai_summary: how a country's AI reacts (diplomacy, treaties and events with their probability).
"""
import json
import math
import os
import re
import shutil
import xml.etree.ElementTree as ET

import scenario_core as sc
from scenario_core import prop, objs

DEFAULT_SCENARIOS = {
    'mh1': ['Conclusion of the War', 'Steps to a Global War', 'The End of Diplomacy', 'The Limits of Peace',
            'The Politics of Appeasement', 'The World at War', 'Tutorial'],
}
DEFAULT_SCENARIOS['gold'] = DEFAULT_SCENARIOS['mh1'] + ['Blitzkrieg', 'Clash of Continents', 'Rise of the Reich', 'Southern Star']


# ---------------------------------------------------------------------------------------- archivos externos
def shared_refs(scen_dir):
    """[(value, absolute path)] of the fileSharedData in scenario.xml."""
    f = os.path.join(scen_dir, 'scenario.xml')
    if not os.path.exists(f):
        return []
    txt = open(f, encoding='utf-8', errors='replace').read()
    out = []
    for v in re.findall(r'name="fileSharedData" value="([^"]*)"', txt):
        out.append((v, os.path.abspath(os.path.normpath(os.path.join(scen_dir, v.replace('/', os.sep))))))
    return out


def attach_external(s):
    """Adds to the scenario the shared data living outside its folder (ScenarioDefaults)."""
    s.external = []
    for v, path in shared_refs(s.dir):
        if os.path.exists(path) and path not in s.paths and not path.startswith(os.path.abspath(s.dir) + os.sep):
            s.paths.append(path)
            s.s.open(path)
            s.external.append(path)
    return s.external


def users_of(path):
    """Escenarios cuyo scenario.xml referencia el archivo 'path'."""
    out = []
    for name in sc.scenarios():
        if any(os.path.normcase(p) == os.path.normcase(path) for _, p in shared_refs(os.path.join(sc.SCEN_ROOT, name))):
            out.append(name)
    return out


def external_dirty(s):
    st = s.s
    return [p for p in getattr(s, 'external', []) if p in st.dirty]


def producer_template(s, producer_id):
    producer = s.s.get(producer_id)
    if producer.get('type') != 'Producer' or s.s.doc_of.get(producer) not in s.paths:
        raise ValueError('el productor no pertenece a este escenario')
    resource = prop(producer, 'strResource')
    matches = s.all('ProducerTemplate', pred=lambda el: prop(el, 'strResource') == resource)
    if len(matches) != 1:
        raise ValueError('no se ha encontrado una plantilla única para el recurso %s' % resource)
    return producer, matches[0]


def set_producer_template(s, producer_id, values):
    _, template = producer_template(s, producer_id)
    try:
        multiplier = float(values['multiplier'])
        workers_text, maintenance_text = str(values['workers']), str(values['maintenance'])
        if not re.fullmatch(r'\d+', workers_text) or not re.fullmatch(r'\d+', maintenance_text):
            raise ValueError
        workers = int(workers_text)
        maintenance = int(maintenance_text)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError('introduce un multiplicador y costes válidos no negativos')
    if not math.isfinite(multiplier) or not 0 <= multiplier <= 3.4028234e38 or workers > 2147483647 or maintenance > 2147483647:
        raise ValueError('introduce un multiplicador y costes válidos no negativos')
    for key, value in (('fMaxMaximizedOutputMultiplier', format(multiplier, '.9g')),
                       ('nMPUsPerBaseOutput', str(workers)), ('nMaintCostPerBaseOutput', str(maintenance))):
        s.s.set_prop(template, key, value)


def _rekey(st, old, new):
    st.docs[new] = st.docs.pop(old)
    for el in st.docs[new].getroot().iter():
        if st.doc_of.get(el) == old:
            st.doc_of[el] = new
    for coll in (st.dirty, st.restructured):
        if old in coll:
            coll.discard(old)
            coll.add(new)


def save_as_new(s, new_name):
    """Copies the scenario to scenarios/<new_name> with its shared data inside (like a mod) and writes there
    the unsaved changes. The original scenario stays as it was on disk."""
    new_name = new_name.strip()
    if not new_name or re.search(r'[\\/:*?"<>|]', new_name):
        raise ValueError('nombre de carpeta no válido')
    dst = os.path.join(sc.SCEN_ROOT, new_name)
    if os.path.exists(dst):
        raise ValueError('ya existe la carpeta «%s»' % new_name)
    st = s.s
    shutil.copytree(s.dir, dst)
    moved = []
    for p in list(s.paths):
        if p in st.docs and p.startswith(os.path.abspath(s.dir) + os.sep):
            q = os.path.join(dst, os.path.relpath(p, s.dir))
        elif p in getattr(s, 'external', []):
            q = os.path.join(dst, os.path.basename(p))
            shutil.copy2(p, q)
        else:
            continue
        if p in st.dirty:
            _rekey(st, p, q)
            moved.append(q)
            st.open(p)      # the original (unchanged, from disk) remains available for other scenarios
    written = st.save(moved) if moved else {'written': [], 'history': None}
    # scenario.xml of the new one: local shared data and new name
    f = os.path.join(dst, 'scenario.xml')
    raw = open(f, 'rb').read().decode('utf-8')
    raw = re.sub(r'(name="fileSharedData" value=")[^"]*[\\/]([^"\\/]+")', r'\1\2', raw)
    for k in ('strName', 'strDisplayName'):
        raw = re.sub(r'(name="%s" value=")[^"]*(")' % k, lambda m: m.group(1) + new_name + m.group(2), raw, count=1)
    open(f, 'wb').write(raw.encode('utf-8'))
    import scenario_extra
    scenario_extra.ensure_dirs(dst)      # game/ and ui/ with namespace.xml and UICommand*.xml, like ed.exe
    return {'scenario': new_name, 'written': written['written'], 'history': written['history']}


# ---------------------------------------------------------------------------------------- map layers
def _city_region(s):
    out = {}
    for c in s.all('City'):
        out[prop(c, 'strName')] = prop(s.s.parent.get(c), 'strName')
    return out


def mapdata(s):
    st = s.s
    regions = {}
    for r in s.regions(sea=False):
        regions[prop(r, 'strName')] = {'id': st.eid(r), 'owner': prop(r, 'strOwner'), 'controller': prop(r, 'strController'),
                                       'terrain': prop(r, 'strTerrain'), 'culture': prop(r, 'strCulture'),
                                       'colony': prop(r, 'bColony') == 'true'}
    colors = {prop(p, 'strName'): '#' + (prop(p, 'colCountryColor') or '888888').lstrip('#')[:6] for p in s.all('Player')}
    nreg = {}
    for v in regions.values():
        nreg[v['owner']] = nreg.get(v['owner'], 0) + 1
    countries = {}
    for name, c in s.countries().items():
        countries[name] = {'id': st.eid(c), 'gov': prop(c, 'strGovType'), 'capital': prop(c, 'strCapital'),
                           'orig_capital': prop(c, 'strOriginalCapital'), 'regions': nreg.get(name, 0),
                           'color': colors.get(name), 'flag': prop(c, 'strFlagName')}
    historic = {}
    for h in s.all('HistoricCountry'):
        historic.setdefault(prop(h, 'strCountry'), []).extend(prop(k, 'strRegion') for k in objs(h) if prop(k, 'strRegion'))
    alliances = [{'id': st.eid(a), 'name': prop(a, 'strDisplayName') or prop(a, 'strINITAllianceName'),
                  'members': [prop(m, 'strINITCountryName') for m in objs(a) if m.get('type') == 'AllianceMember'],
                  'leader': next((prop(m, 'strINITCountryName') for m in objs(a) if prop(m, 'bOwner') == 'true'), None)}
                 for a in s.all('Alliance')]
    amembers = {a['name']: a['members'] for a in alliances}
    wars = []
    for w in s.all('War'):
        att = [prop(w, 'strINITAttackerCountryName')] + amembers.get(prop(w, 'strINITOffenseAllianceName') or '', [])
        dfn = [prop(w, 'strINITDefenderCountryName')] + amembers.get(prop(w, 'strINITDefenseAllianceName') or '', [])
        wars.append({'id': st.eid(w), 'name': prop(w, 'strDisplayName'), 'attackers': sorted({x for x in att if x}),
                     'defenders': sorted({x for x in dfn if x})})
    opts = s.options()
    cultures = sorted({prop(c, 'strCultureName') for c in s.all('CultureTemplate') if prop(c, 'strCultureName')}
                      | {v['culture'] for v in regions.values() if v['culture']})
    terrains = sorted({v['terrain'] for v in regions.values() if v['terrain']}
                      | {'Plains', 'Hills', 'Mountains', 'Forest', 'Jungle', 'Desert', 'Tundra'})
    govs = sorted(set(opts.get('strGovType', [])) | {c['gov'] for c in countries.values() if c['gov']})
    return {'regions': regions, 'countries': countries, 'historic': historic, 'alliances': alliances, 'wars': wars,
            'cultures': cultures, 'terrains': terrains, 'govs': govs, 'surrendered': surrendered(s, countries, historic)}


def surrendered(s, countries=None, historic=None):
    """Countries without regions on the map and whether they can be liberated in game: they need strCapital and
    strOriginalCapital, and their historic regions must include the region of that city."""
    if countries is None:
        d = mapdata(s)
        return d['surrendered']
    city_reg = _city_region(s)
    out = []
    for name, c in sorted(countries.items()):
        if c['regions']:
            continue
        hist = historic.get(name, [])
        cap = c['capital'] or ''
        reasons = []
        if not cap:
            reasons.append('sin capital (strCapital)')
        if not c['orig_capital']:
            reasons.append('sin capital original (strOriginalCapital)')
        if not hist:
            reasons.append('sin regiones históricas')
        creg = city_reg.get(cap or c['orig_capital'] or '')
        if (cap or c['orig_capital']) and creg is None:
            reasons.append('la ciudad %s no existe' % (cap or c['orig_capital']))
        elif creg and hist and creg not in hist:
            reasons.append('la región de la capital (%s) no está entre sus regiones históricas' % creg)
        out.append({'country': name, 'id': c['id'], 'capital': cap, 'orig_capital': c['orig_capital'],
                    'capital_region': creg, 'historic': hist, 'liberable': not reasons, 'reasons': reasons})
    return out


def toggle_historic(s, country, region):
    """Adds or removes a region from a country's historic ones (creates the HistoricCountry if missing)."""
    st = s.s
    hs = [h for h in s.all('HistoricCountry') if prop(h, 'strCountry') == country]
    for h in hs:
        for k in objs(h):
            if prop(k, 'strRegion') == region:
                st.remove(k)
                return {'added': False, 'note': '%s ya no es región histórica de %s' % (region, country)}
    if hs:
        h = hs[0]
    else:
        lists = [st.parent[x] for x in s.all('HistoricCountry')]
        if not lists:
            raise ValueError('el escenario no tiene lista de países históricos (sharedDataHistoricCountries.xml)')
        par = lists[0]
        h = ET.Element('object', {'type': 'HistoricCountry', 'name': 'objHistoricCountryList'})
        ET.SubElement(h, 'property', {'name': 'strCountry', 'value': country})
        # alphabetical order as in the original file
        sibs = [c for c in par if c.get('type') == 'HistoricCountry']
        after = [c for c in sibs if (prop(c, 'strCountry') or '') > country]
        st.attach(h, par, index=list(par).index(after[0]) if after else None)
    k = ET.Element('object', {'type': 'NameRegionRefPair', 'name': 'objNameRegionRefPairs'})
    ET.SubElement(k, 'property', {'name': 'strRegion', 'value': region})
    st.attach(k, h)
    return {'added': True, 'note': '%s es ahora región histórica de %s' % (region, country)}


def _alliance_name(al):
    return prop(al, 'strDisplayName') or prop(al, 'strINITAllianceName') or '?'


def leave_alliance(s, al, member):
    """Removes a member from an alliance. If it was the leader, passes it to the next; if nobody is left, the alliance disappears (and wars
    that named it stop doing so). Before, empty or leaderless alliances remained in gamestate.xml."""
    st = s.s
    mem = [m for m in objs(al) if m.get('type') == 'AllianceMember']
    leader = prop(member, 'bOwner') == 'true'
    st.remove(member)
    rest = [m for m in mem if m is not member]
    if not rest:
        key = prop(al, 'strINITAllianceName')
        st.remove(al)
        for w in s.all('War'):
            for k in ('strINITOffenseAllianceName', 'strINITDefenseAllianceName'):
                if key and prop(w, k) == key:
                    st.set_prop(w, k, '')
        return ['alianza %s: desaparece (no quedan miembros)' % _alliance_name(al)]
    if leader:
        st.set_prop(rest[0], 'bOwner', 'true')
        st.set_prop(rest[0], 'bPrincipal', 'true')
        return ['alianza %s: ahora la lidera %s' % (_alliance_name(al), prop(rest[0], 'strINITCountryName'))]
    return []


def toggle_alliance(s, alliance_id, country):
    """Adds or removes a country from an alliance; a country can only be in one alliance."""
    st = s.s
    a = st.get(alliance_id)
    notes = []
    for m in objs(a):
        if m.get('type') == 'AllianceMember' and prop(m, 'strINITCountryName') == country:
            if prop(m, 'bOwner') == 'true' and len([x for x in objs(a) if x.get('type') == 'AllianceMember']) > 1:
                raise ValueError('%s lidera la alianza: elige otro líder (bOwner) antes de quitarlo' % country)
            return {'added': False, 'notes': ['%s sale de %s' % (country, _alliance_name(a))] + leave_alliance(s, a, m)}
    for other in list(s.all('Alliance')):
        if other is a:
            continue
        for m in [x for x in objs(other) if x.get('type') == 'AllianceMember' and prop(x, 'strINITCountryName') == country]:
            notes.append('%s sale de %s (solo puede estar en una alianza)' % (country, _alliance_name(other)))
            notes += leave_alliance(s, other, m)
    m = ET.Element('object', {'type': 'AllianceMember', 'name': 'objAllMembers'})
    ET.SubElement(m, 'property', {'name': 'strINITCountryName', 'value': country})
    st.attach(m, a)
    notes.append('%s entra en %s' % (country, prop(a, 'strDisplayName')))
    return {'added': True, 'notes': notes}


# ---------------------------------------------------------------------------------------- regiones nuevas: mar, traspasos y unidades
def add_sea_region(s, name, mother=None, text=None):
    """Registers a new sea region in waterWorld.xml (next to the mother if any)."""
    st = s.s
    seas = {prop(r, 'strName'): r for r in s.regions(sea=True)}
    if name in seas:
        return ['%s: ya existía en el escenario' % name]
    ww = os.path.abspath(s.path('waterWorld.xml'))
    if not seas and ww not in st.docs:
        raise ValueError('el escenario no tiene waterWorld.xml')
    ref = seas.get(mother) or next(iter(seas.values()), None)
    par = st.parent[ref] if ref is not None else st.docs[ww].getroot()     # waterWorld.xml without seas (scenario from scratch)
    new = ET.Element('object', {'type': 'Region', 'name': ref.get('name', '') if ref is not None else ''})
    sid = sc.region_sid(name)
    for k, v in (('strName', name), ('strOwner', ''), ('strController', ''), ('sidName', sid)):
        ET.SubElement(new, 'property', {'name': k, 'value': v})
    st.attach(new, par, path=st.doc_of[ref] if ref is not None else ww, index=list(par).index(ref) + 1 if ref is not None else None)   # par es la raiz <objects>
    notes = ['%s registrada en waterWorld.xml' % name]
    notes += sc.set_region_string(s, sid, text or name)
    s._opts = None
    return notes


def reassign_by_geometry(s, name, geom, sea=False):
    """Everything left inside the new region goes to it: cities and producers (from any region it was
    clipped from) and armies / aircraft (land) or fleets (sea)."""
    from shapely.geometry import Point
    st = s.s
    notes = []
    if geom is None:
        return notes
    inside = lambda e: (lambda xy: xy is not None and geom.buffer(1e-6).covers(Point(xy[0], xy[1])))(sc.parse_vec(prop(e, 'vecPosition')))
    if not sea:
        land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
        new = land.get(name)
        if new is None:
            return notes
        for t in ('City', 'Producer'):
            for c in s.all(t):
                if st.parent.get(c) is not new and inside(c):
                    old = prop(st.parent[c], 'strName')
                    s.update(st.eid(c), {'__region': name})
                    notes.append('%s %s pasa de %s a %s' % ('ciudad' if t == 'City' else 'recurso', prop(c, 'strName'), old, name))
        kinds = ('Army', 'AirForce', 'Fleet')   # fleets docked in a port left inside also move
    else:
        kinds = ('Fleet',)
    land_names = {prop(r, 'strName') for r in s.regions(sea=False)}
    if not sea:
        # docked fleets without position: if their region was left without a port and the port went to the new one, they follow it
        lands = {prop(r, 'strName'): r for r in s.regions(sea=False)}
        has_port = lambda r: r is not None and any(c.get('type') == 'City' and prop(c, 'strPortForRegion') for c in objs(r))
        if has_port(lands.get(name)):
            for g in s.all('Fleet'):
                w = prop(g, 'strRegion')
                if w in lands and w != name and not prop(g, 'vecPosition') and not has_port(lands[w]):
                    st.set_prop(g, 'strRegion', name)
                    notes.append('flota %s (%s) sigue a su puerto: pasa de %s a %s' % (prop(g, 'strName'), prop(g, 'strOwner'), w, name))
    for t in kinds:
        for g in s.all(t):
            if t == 'Fleet' and not sea and prop(g, 'strRegion') not in land_names:
                continue        # a fleet at sea does not move to a land region
            if prop(g, 'strRegion') != name and inside(g):
                notes.append('%s %s (%s) pasa de %s a %s' % ({'Army': 'ejército', 'AirForce': 'aviación', 'Fleet': 'flota'}[t],
                                                             prop(g, 'strName'), prop(g, 'strOwner'), prop(g, 'strRegion'), name))
                st.set_prop(g, 'strRegion', name)
    return notes


def reassign_ports(s, name, geom, geom_of, max_dist=1.5):
    """New sea region (e.g. clipped from another sea one): port cities whose port faces another sea region
    and that are closer to the new one get their port in it (strPortForRegion). geom_of(name) gives the shape of
    a map region."""
    from shapely.geometry import Point
    notes = []
    if geom is None:
        return notes
    cache = {}
    for c in s.all('City'):
        port = prop(c, 'strPortForRegion')
        if not port or port == name:
            continue
        xy = sc.parse_vec(prop(c, 'vecPosition'))
        if xy is None:
            continue
        pt = Point(xy[0], xy[1])
        d_new = geom.distance(pt)
        if d_new > max_dist:
            continue
        if port not in cache:
            cache[port] = geom_of(port)
        g_old = cache[port]
        if g_old is not None and d_new >= g_old.distance(pt):
            continue
        s.s.set_prop(c, 'strPortForRegion', name)
        notes.append('puerto de %s: pasa de %s a %s' % (prop(c, 'strName'), port, name))
    return notes


def unit_conflicts(s, name):
    """Armies and aircraft in the new region that belong to a country other than the region owner."""
    reg = next((r for r in s.regions(sea=False) if prop(r, 'strName') == name), None)
    if reg is None:
        return []
    owner = prop(reg, 'strOwner')
    out = []
    for t in ('Army', 'AirForce', 'Fleet'):
        for g in s.all(t):
            if prop(g, 'strRegion') == name and prop(g, 'strOwner') != owner:
                xy = sc.parse_vec(prop(g, 'vecPosition'))
                out.append({'id': s.s.eid(g), 'kind': t, 'unit': prop(g, 'strName'), 'owner': prop(g, 'strOwner'),
                            'region': name, 'region_owner': owner, 'xy': list(xy[:2]) if xy else None})
    return out


def resolve_unit(s, uid, action, target=None, xy=None):
    """action 'owner': the unit goes to the region owner country; 'move': it moves to region 'target' (center xy)."""
    st = s.s
    g = st.get(uid)
    if action == 'owner':
        reg = next((r for r in s.regions(sea=False) if prop(r, 'strName') == prop(g, 'strRegion')), None)
        new_owner = prop(reg, 'strOwner')
        s.update(uid, {'strOwner': new_owner})
        return '%s pasa a ser de %s' % (prop(g, 'strName'), new_owner)
    if action == 'move':
        st.set_prop(g, 'strRegion', target)
        if xy:
            parts = (prop(g, 'vecPosition') or '').strip('[] ').split(',')
            z = parts[2].strip() if len(parts) > 2 else '0'
            st.set_prop(g, 'vecPosition', '[%r, %r, %s]' % (float(xy[0]), float(xy[1]), z))
        return '%s (%s) se traslada a %s' % (prop(g, 'strName'), prop(g, 'strOwner'), target)
    return '%s se queda donde está' % prop(g, 'strName')


# ---------------------------------------------------------------------------------------- multiple selection
def at_war_from_start(s, a, b):
    """Are a and b on opposite sides of a war that already exists at scenario start (gamestate)?"""
    amembers = {prop(x, 'strName'): [prop(m, 'strINITCountryName') for m in objs(x) if m.get('type') == 'AllianceMember']
                for x in s.all('Alliance')}
    for w in s.all('War'):
        att = {prop(w, 'strINITAttackerCountryName')} | set(amembers.get(prop(w, 'strINITOffenseAllianceName') or '', []))
        dfn = {prop(w, 'strINITDefenderCountryName')} | set(amembers.get(prop(w, 'strINITDefenseAllianceName') or '', []))
        if (a in att and b in dfn) or (a in dfn and b in att):
            return True
    return False


def bulk_regions(s, regions, values):
    """Applies the same values (owner, controller, terrain, culture) to several regions."""
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    notes = []
    own, ctl = values.get('strOwner'), values.get('strController')
    if own and ctl and own != ctl and not at_war_from_start(s, own, ctl):
        raise ValueError('el controlador solo puede ser distinto del propietario si %s y %s están en guerra desde el inicio '
                         'del escenario: crea antes esa guerra (selección múltiple de entidades políticas → Guerra inicial)' % (own, ctl))
    for n in regions:
        r = land.get(n)
        if r is None:
            notes.append('%s: sin datos en el escenario (¿mar?)' % n)
            continue
        vals = {k: v for k, v in values.items() if v and prop(r, k) != v}
        if vals:
            s.update(s.s.eid(r), vals)
            notes.append('%s: %s' % (n, ', '.join('%s=%s' % (k[3:], v) for k, v in vals.items())))
    if own:
        notes += unsurrender(s, own, regions[0] if regions else None)
    return notes


def set_region_population(s, region, population):
    """Inhabitants set by hand for a region (without subtracting them from another)."""
    reg = next((r for r in s.regions(sea=False) if prop(r, 'strName') == region), None)
    if reg is None:
        return []
    s.s.set_prop(reg, 'nPopulation', str(int(population)))
    return ['%s: %s hab. (puestos a mano)' % (region, int(population))]


def set_historic(s, region, countries):
    """Makes the region historic of exactly 'countries' (removed from the other historic countries)."""
    notes = []
    want = set(countries or [])
    have = {prop(h, 'strCountry') for h in s.all('HistoricCountry') if any(prop(k, 'strRegion') == region for k in objs(h))}
    for c in sorted(have - want) + sorted(want - have):
        notes.append(toggle_historic(s, c, region)['note'])
    return notes


def add_to_historic(s, country, regions):
    notes = []
    have = set()
    for h in s.all('HistoricCountry'):
        if prop(h, 'strCountry') == country:
            have |= {prop(k, 'strRegion') for k in objs(h)}
    for r in regions:
        if r not in have:
            notes.append(toggle_historic(s, country, r)['note'])
    return notes


def alliance_add(s, countries, alliance_id=None, new_name=None):
    """Puts several countries in an alliance (existing or new; the first one leads the new one)."""
    st = s.s
    notes = []
    if alliance_id:
        a = st.get(alliance_id)
    else:
        name = (new_name or '').strip()
        if not name:
            raise ValueError('falta el nombre de la alianza nueva')
        same = next((x for x in s.all('Alliance') if name.lower() in ((prop(x, 'strDisplayName') or '').lower(),
                                                                       (prop(x, 'strINITAllianceName') or '').lower())), None)
        if same is not None:      # «alianza nueva» with the name of an existing one: that one is used (before, another identical one was created)
            return alliance_add(s, countries, st.eid(same))
        existing = s.all('Alliance')
        mgr = st.parent[existing[0]] if existing else next(iter(s.all('AllianceManager')), None)
        if mgr is None:
            raise ValueError('el escenario no tiene AllianceManager en gamestate.xml')
        a = ET.Element('object', {'type': 'Alliance', 'name': 'objAllAlliances'})
        ET.SubElement(a, 'property', {'name': 'strDisplayName', 'value': name})
        ET.SubElement(a, 'property', {'name': 'strINITAllianceName', 'value': name})
        idx = list(mgr).index(existing[-1]) + 1 if existing else None
        st.attach(a, mgr, index=idx)
        notes.append('alianza nueva «%s»' % name)
    members = {prop(m, 'strINITCountryName') for m in objs(a) if m.get('type') == 'AllianceMember'}
    for i, c in enumerate(countries):
        if c in members:
            continue
        r = toggle_alliance(s, st.eid(a), c)
        notes += r['notes']
        if not alliance_id and i == 0:   # leader of the new alliance
            m = [x for x in objs(a) if x.get('type') == 'AllianceMember'][-1]
            st.set_prop(m, 'bOwner', 'true')
            st.set_prop(m, 'bPrincipal', 'true')
    return {'notes': notes, 'id': st.eid(a)}


def create_wars(s, attacker, defenders, name=None):
    """Initial wars (gamestate): one per defender, as in the game scenarios."""
    st = s.s
    wars = s.all('War')
    mgr = st.parent[wars[0]] if wars else (st.parent[s.all('Alliance')[0]] if s.all('Alliance') else None)
    if mgr is None:
        raise ValueError('no encuentro dónde van las guerras (AllianceManager de gamestate.xml)')
    notes = []
    for d in defenders:
        if d == attacker:
            continue
        if any(prop(w, 'strINITAttackerCountryName') == attacker and prop(w, 'strINITDefenderCountryName') == d for w in wars):
            notes.append('%s y %s ya están en guerra' % (attacker, d))
            continue
        w = ET.Element('object', {'type': 'War', 'name': 'objAllWars'})
        for k, v in (('strDisplayName', name or '%s - %s War' % (attacker, d)), ('strINITOffenseAllianceName', ''),
                     ('strINITDefenseAllianceName', ''), ('strINITAttackerCountryName', attacker), ('strINITDefenderCountryName', d)):
            ET.SubElement(w, 'property', {'name': k, 'value': v})
        st.attach(w, mgr, index=(list(mgr).index(wars[-1]) + 1) if wars else None)
        wars.append(w)
        notes.append('guerra: %s ataca a %s' % (attacker, d))
    return notes


def create_flows(s, origin, targets, kind='trade'):
    """Trade agreements (objFlows) or aid (objAidFlows) from 'origin' to each destination, in WorldMarket of game.xml."""
    st = s.s
    name = 'objFlows' if kind == 'trade' else 'objAidFlows'
    market = next(iter(s.all('WorldMarket')), None)
    if market is None:
        raise ValueError('el escenario no tiene WorldMarket (game.xml)')
    have = {(prop(f, 'strFromCountry'), prop(f, 'strToCountry')) for f in objs(market) if f.get('name') == name}
    notes = []
    for t in targets:
        if t == origin or (origin, t) in have:
            continue
        f = ET.Element('object', {'type': 'Flow', 'name': name})
        ET.SubElement(f, 'property', {'name': 'strFromCountry', 'value': origin})
        ET.SubElement(f, 'property', {'name': 'strToCountry', 'value': t})
        st.attach(f, market)
        notes.append('%s: %s → %s' % ('comercio' if kind == 'trade' else 'ayuda', origin, t))
    return notes


# ---------------------------------------------------------------------------------------- textos y regionpack
def set_string(s, sid, value):
    """Visible text of a SID in the scenario game/stringTable.xml (creates it if missing)."""
    path = os.path.abspath(os.path.join(s.dir, 'game', 'stringTable.xml'))
    st = s.s
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'w', encoding='utf-8', newline='\r\n').write('<?xml version="1.0" encoding="UTF-8"?>\n<stringTable existence="optional">\n</stringTable>\n')
    root = st.open(path).getroot()
    for e in root.iter('string'):
        if e.get('id') == sid:
            if e.get('value') != value:
                e.set('value', value)
                st.dirty.add(path)
            break
    else:
        e = ET.SubElement(root, 'string', {'id': sid, 'value': value})
        st.parent[e] = root
        st.doc_of[e] = path
        st.dirty.add(path)
        st.restructured.add(path)
    if path not in s.paths:
        s.paths.append(path)
    s.strings[sid] = value
    return path


def set_pack(s, pack):
    """Changes the scenario regionpack (strMapName and fileMapProperties of scenario.xml)."""
    sx = s.all('Scenario', lambda f: f == 'scenario.xml')
    disp = next((o for o in sx[0].iter('object') if o.get('type') == 'ScenarioDisplaySettings'), None) if sx else None
    if disp is None:
        raise ValueError('scenario.xml no tiene ScenarioDisplaySettings')
    s.s.set_prop(disp, 'strMapName', pack)
    s.s.set_prop(disp, 'fileMapProperties', '/../Modern Europe/system/DisplayLibraries/Maps/%s/xml/properties.xml' % pack)
    return ['regionpack: %s' % pack] + fix_sprite_map(s)


def fix_sprite_map(s):
    """strSpriteMapName in scenario.xml must name a file that exists in DisplayLibraries/SpriteMaps (the game only
    has World.xml). If it names another (e.g. the regionpack one, «Tamriel»), the game does not load the map graphics and all
    regions show black («Error loading sprite map»). It is set to «World»."""
    sx = s.all('Scenario', lambda f: f == 'scenario.xml')
    disp = next((o for o in sx[0].iter('object') if o.get('type') == 'ScenarioDisplaySettings'), None) if sx else None
    if disp is None:
        return []
    cur = prop(disp, 'strSpriteMapName')
    if not cur:
        return []
    d = os.path.join(sc.GAME, 'Modern Europe', 'system', 'DisplayLibraries', 'SpriteMaps')
    if os.path.exists(os.path.join(d, cur + '.xml')) or not os.path.isdir(d):
        return []
    s.s.set_prop(disp, 'strSpriteMapName', 'World')
    return ['strSpriteMapName «%s» no existe en DisplayLibraries/SpriteMaps: pasa a «World» (si no, el mapa sale negro)' % cur]


FLAT_CAMERA = 'WorldUnifiedFlat'


def _display(s):
    sx = s.all('Scenario', lambda f: f == 'scenario.xml')
    return next((o for o in sx[0].iter('object') if o.get('type') == 'ScenarioDisplaySettings'), None) if sx else None


def tilt_state(s):
    d = _display(s)
    return (prop(d, 'strCameraSettingsName') or 'WorldUnified') != FLAT_CAMERA if d is not None else True


def set_tilt(s, enable):
    """3D map tilt: WorldUnified (tilts up to 55° when zooming in) or WorldUnifiedFlat (always top-down)."""
    d = _display(s)
    if d is None:
        raise ValueError('scenario.xml no tiene ScenarioDisplaySettings')
    s.s.set_prop(d, 'strCameraSettingsName', 'WorldUnified' if enable else FLAT_CAMERA)
    return ['inclinación 3D %s' % ('activada' if enable else 'desactivada (cámara %s)' % FLAT_CAMERA)]


def ensure_flat_camera():
    """Creates DisplayLibraries/CameraSettings/WorldUnifiedFlat.xml (copy of WorldUnified without elevation) if missing.
    Returns the created path or None."""
    d = os.path.join(sc.GAME, 'Modern Europe', 'system', 'DisplayLibraries', 'CameraSettings')
    src, dst = os.path.join(d, 'WorldUnified.xml'), os.path.join(d, FLAT_CAMERA + '.xml')
    if os.path.exists(dst) or not os.path.exists(src):
        return None
    txt = open(src, encoding='utf-8').read()
    txt = re.sub(r'(name="f(?:Default|Max)Elevation" value=")[^"]*(")', r'\g<1>0.0\2', txt)
    open(dst, 'w', encoding='utf-8', newline='').write(txt)
    return dst


def set_playable(s, countries):
    """List of playable countries from scenarioInfo.xml (objPlayableCountries)."""
    st = s.s
    info = s.all('ScenarioInfo')
    if not info:
        raise ValueError('el escenario no tiene scenarioInfo.xml')
    info = info[0]
    for c in [c for c in objs(info) if c.get('name') == 'objPlayableCountries']:
        st.remove(c)
    for name in countries:
        w = ET.Element('object', {'type': 'WrappedString', 'name': 'objPlayableCountries'})
        ET.SubElement(w, 'property', {'name': 'strString', 'value': name})
        st.attach(w, info)
    return ['%d países jugables' % len(countries)]


# ---------------------------------------------------------------------------------------- IA
DRP_ES = {
    'DRP_EVENT__START_WAR': 'Alguien empieza una guerra', 'DRP_EVENT__MAKE_PEACE': 'Se firma la paz',
    'DRP_EVENT__START_ALLIANCE_WAR': 'Una alianza entra en guerra', 'DRP_EVENT__JOIN_ALLIANCE_WAR': 'Se une a una guerra de alianza',
    'DRP_EVENT__DEFENSE_PACT_RATIFIED': 'Pacto defensivo firmado', 'DRP_EVENT__DEFENSE_PACT_CANCELLED': 'Pacto defensivo roto',
    'DRP_EVENT__NON_AGGRESSION_RATIFIED': 'Pacto de no agresión firmado', 'DRP_EVENT__NON_AGGRESSION_CANCELLED': 'Pacto de no agresión roto',
    'DRP_EVENT__MILITARY_ACCESS_RATIFIED': 'Acceso militar concedido', 'DRP_EVENT__MILITARY_ACCESS_CANCELLED': 'Acceso militar retirado',
    'DRP_EVENT__TERRITORIAL_TRANSFER_PROPOSED': 'Propone ceder territorio', 'DRP_EVENT__UPDATE_FOR_FLOWS': 'Comercio y ayuda (cada turno)',
}


def _args(el):
    out = []
    for al in objs(el):
        if al.get('type') == 'ArgumentList':
            for a in objs(al):
                out.append('%s = %s' % (prop(a, 'strName'), prop(a, 'nValue') if prop(a, 'nValue') is not None else prop(a, 'strValue') or ''))
    return out


def ai_summary(s, country):
    st = s.s
    pd = next((p for p in s.all('MEPlayerData') if prop(p, 'strOwner') == country), None)
    if pd is None:
        raise ValueError('no hay datos de jugador para %s' % country)
    drp_name = prop(pd, 'strDipRelProcListName')
    te_name = prop(pd, 'strAITreatyEvalListName')
    templates = {}
    for p in s.paths:
        for el in st.docs[p].getroot().iter('object'):
            n = prop(el, 'strName')
            if n and (el.get('type') or '').startswith(('DRP', 'TE')):
                templates[(el.get('type')[:2] if el.get('type').startswith('TE') else 'DRP', n)] = el
    out = {'country': country, 'player_id': st.eid(pd), 'reactions_list': drp_name, 'treaties_list': te_name,
           'traits': {k: prop(pd, k) for k in ('eInternationalPosition', 'nAggressiveNature', 'nMilitaryPosture',
                                                'nInternationalInvolvement', 'nPoliticalStability')},
           'reactions': [], 'treaties': [], 'events': []}
    for lst in s.all('DipRelProcessorRefList'):
        if prop(lst, 'strName') == drp_name:
            for r in objs(lst):
                t = templates.get(('DRP', prop(r, 'strName')))
                out['reactions'].append({'event': DRP_ES.get(prop(r, 'eEventType'), prop(r, 'eEventType')), 'name': prop(r, 'strName'),
                                         'id': st.eid(t) if t is not None else st.eid(r), 'args': _args(t) if t is not None else []})
    for lst in s.all('AIEvalRefList'):
        if prop(lst, 'strName') == te_name:
            for r in objs(lst):
                t = templates.get(('TE', prop(r, 'strName')))
                out['treaties'].append({'type': prop(r, 'strType'), 'name': prop(r, 'strName'),
                                        'id': st.eid(t) if t is not None else st.eid(r),
                                        'min': prop(t, 'nMinScore') if t is not None else None,
                                        'args': _args(t) if t is not None else []})
    for ev in s.all('ScriptedEventDef'):
        txt = ET.tostring(ev, encoding='unicode')
        if 'value="%s"' % country not in txt:
            continue
        pct = re.search(r'name="nPercentChance" value="(\d+)"', txt)
        acts = re.findall(r'type="(Act[A-Za-z]+)"', txt)
        out['events'].append({'id': st.eid(ev), 'label': prop(ev, 'strTypeLabel'), 'pct': pct.group(1) if pct else None,
                              'actions': sorted(set(acts)),
                              'date': (re.search(r'GTE (\d\d/\d\d/\d{4})', txt) or [None, None])[1]})
    return out


def move_population(s, name, fractions):
    """Population of a new region: from each source region the given fraction of its inhabitants moves
    (e.g. {'Atacama': 0.35, 'Coquimbo': 0.6}); subtracted from them and added to the new one."""
    st = s.s
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    new = land.get(name)
    if new is None:
        return []
    total, notes = 0, []
    for mother, f in fractions.items():
        r = land.get(mother)
        pop = prop(r, 'nPopulation') if r is not None else None
        if not pop or not pop.isdigit():
            continue
        moved = max(0, min(int(pop), int(round(int(pop) * float(f)))))
        st.set_prop(r, 'nPopulation', str(int(pop) - moved))
        total += moved
        notes.append('población: %s hab. de %s (%.0f %%) pasan a %s; %s queda con %s' % (moved, mother, 100 * float(f), name, mother, int(pop) - moved))
    st.set_prop(new, 'nPopulation', str(total))
    notes.append('%s: %s hab.' % (name, total))
    return notes


def take_population(s, name, amounts):
    """The new region 'name' has sum(amounts) inhabitants (e.g. set by hand or from the GeoJSON), subtracted from each source
    region according to 'amounts' ({mother: inhabitants}; none goes below 0). Before, the hand-set figure was applied without subtracting it from anyone."""
    st = s.s
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    new = land.get(name)
    if new is None:
        return []
    total, notes = 0, []
    for mother, n in amounts.items():
        n = max(0, int(round(n)))
        total += n
        src = land.get(mother)
        pop = prop(src, 'nPopulation') if src is not None else None
        if pop and pop.isdigit():
            st.set_prop(src, 'nPopulation', str(max(0, int(pop) - n)))
            notes.append('población: %s hab. de %s pasan a %s; %s queda con %s' % (n, mother, name, mother, max(0, int(pop) - n)))
    st.set_prop(new, 'nPopulation', str(total))
    notes.append('%s: %s hab. (puestos a mano)' % (name, total))
    return notes


def set_population_from(s, name, mother, amount):
    """Region 'name' gets back exactly 'amount' inhabitants, subtracted from 'mother'."""
    st = s.s
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    new, src = land.get(name), land.get(mother)
    if new is None:
        return []
    st.set_prop(new, 'nPopulation', str(int(amount)))
    if src is not None and (prop(src, 'nPopulation') or '').isdigit():
        st.set_prop(src, 'nPopulation', str(max(0, int(prop(src, 'nPopulation')) - int(amount))))
    return ['población: %s recupera %s hab. (de %s)' % (name, int(amount), mother)]


# ---------------------------------------------------------------------------------------- compatibility with a regionpack
class PackMap:
    """Regions of an installed regionpack: names (with RegionRename), whether they are sea, neighbors and geometry."""
    def __init__(self, pack, folder=None):
        import mhmap
        import editor_core
        import new_region
        self.pack = pack
        self.dir = folder or os.path.join(editor_core.MAPS, pack)
        if not os.path.exists(os.path.join(self.dir, 'xml', 'regions.bin')):
            raise ValueError('no existe el regionpack %s' % pack)
        self.m = mhmap.load_map(os.path.join(self.dir, 'xml'))
        ren = editor_core.load_renames(self.dir)
        self.renames = ren          # {name in regions.bin: name in the scenarios} (RegionRename of map.xml)
        R = self.m['regions']
        self.name = {g.index: ren.get(g.name, g.name) for g in R}
        self.idx = {v: k for k, v in self.name.items()}
        self.sea = {self.name[g.index]: g.u_type == 0 for g in R}
        self.nb = {self.name[g.index]: [self.name[n] for n in g.neighbors if n != g.index] for g in R}
        self._geo = {}
        self._mesh = new_region.mesh_polygon
        p = os.path.join(self.dir, 'changelog.json')
        import changelog_keys
        self.changelog = changelog_keys.load(p)

    def geom(self, name):
        if name not in self._geo:
            i = self.idx.get(name)
            self._geo[name] = self._mesh(self.m, i) if i is not None else None
        return self._geo[name]

    def region_at(self, x, y, sea=False):
        from shapely.geometry import Point
        pt = Point(x, y)
        for n, is_sea in self.sea.items():
            if is_sea == sea:
                g = self.geom(n)
                if g is not None and g.covers(pt):
                    return n
        return None


def pack_mismatch(s, pack):
    """Quick check (names only): map regions missing from the scenario and extra regions."""
    pm = PackMap(pack)
    land = {prop(r, 'strName') for r in s.regions(sea=False)}
    seas = {prop(r, 'strName') for r in s.regions(sea=True)}
    skip = {'BasicRegionLists', 'Historic'}
    missing = sorted(n for n, is_sea in pm.sea.items() if n not in skip and n not in (seas if is_sea else land))
    extra = sorted(n for n in land | seas if n not in pm.sea)
    return missing, extra


def pack_sync_plan(s, pack):
    """What must change for the scenario to match regionpack 'pack':
    'remove': scenario regions the map lacks (their content goes to 'into');
    'add': map regions without data in the scenario (taken from 'mother')."""
    pm = PackMap(pack)
    P = prop
    land = {P(r, 'strName'): r for r in s.regions(sea=False)}
    seas = {P(r, 'strName') for r in s.regions(sea=True)}
    madre = {}
    logs = list(pm.changelog)
    cur = sc.pack_of(s)
    pa = None                                   # map of the scenario's current regionpack (to translate by geometry)
    if cur and cur != pack:
        try:
            pa = PackMap(cur)
            logs += pa.changelog                # the creation of the extra ones is in the current map changelog
        except ValueError:
            pass
    for e in logs:
        for x in e.get('regiones_nuevas', []):
            madre[x['nombre']] = x.get('madre')
    skip = {'BasicRegionLists', 'Historic'}
    eqs = pack_equivalences(pm)
    remove, add = [], []
    import progress
    tick = progress.part(5, 30)
    for k, (n, r) in enumerate(land.items()):
        if k % 25 == 0:
            tick(k, len(land), 'Comparando las regiones del escenario con el mapa')
        if n in pm.sea and not pm.sea[n]:
            continue        # on the map it is sea (e.g. a lake created as land): the land one is removed and the sea one added
        # where it goes: the map region containing most of its cities / its mother in the changelog
        votes = {}
        for c in objs(r):
            xy = sc.parse_vec(P(c, 'vecPosition')) if c.get('type') in ('City', 'Producer') else None
            if xy:
                t = pm.region_at(xy[0], xy[1])
                if t and t in land and t != n:
                    votes[t] = votes.get(t, 0) + 1
        into = None
        ga = pa.geom(n) if pa is not None else None
        if ga is not None:
            # by geometry: the region of the new map (which the scenario already has) overlapping this one most; so two regions
            # of one regionpack that were one in the other (or vice versa) are translated without depending on names or changelogs
            best, area = None, 0.0
            for m in land:
                gm = pm.geom(m) if m != n and m in pm.sea and not pm.sea[m] else None
                if gm is not None:
                    a_ = ga.intersection(gm).area
                    if a_ > area:
                        best, area = m, a_
            into = best
        if into is None:
            into = max(votes, key=votes.get) if votes else None
        if into is None:
            # its mother in some known changelog, if it exists on the map
            into = next((m for m in [madre.get(n)] if m and m in land and m in pm.sea and not pm.sea[m]), None)
        remove.append({'name': n, 'sea': False, 'into': into, 'owner': P(r, 'strOwner'),
                       'cities': [P(c, 'strName') for c in objs(r) if c.get('type') == 'City']})
    for n in seas:
        if n not in pm.sea or not pm.sea[n]:        # nor if on the map it is now land
            remove.append({'name': n, 'sea': True, 'into': None, 'owner': '', 'cities': []})
    for n, is_sea in pm.sea.items():
        if n in skip:
            continue
        if is_sea and n not in seas:
            add.append({'name': n, 'sea': True, 'mother': next((x for x in pm.nb[n] if x in seas), None)})
        elif not is_sea and n not in land:
            m = None
            gn_ = pm.geom(n)
            if pa is not None and gn_ is not None:
                # source region by geometry: the current map one where this area was; if it is already being removed, its content
                # is in the region it goes to (into)
                landing = {x['name']: x['into'] for x in remove if not x['sea']}
                best, area = None, 0.0
                for r_ in land:
                    gr = pa.geom(r_)
                    if gr is not None:
                        a_ = gn_.intersection(gr).area
                        if a_ > area:
                            best, area = r_, a_
                if best is not None:
                    m = landing.get(best, best) if best in landing else best
                    if m not in land or m in landing:
                        m = None
            if m is None:
                m = madre.get(n)
            if not (m and m in land):
                cand = [x for x in pm.nb[n] if x in land]
                g = pm.geom(n)
                m = max(cand, key=lambda x: (g.intersection(pm.geom(x).buffer(1e-4)).length if g is not None and pm.geom(x) is not None else 0)) if cand else None
            if not (m and m in land):
                m = island_source(pm, n, land, eqs)
            add.append({'name': n, 'sea': False, 'mother': m})
    return {'pack': pack, 'remove': remove, 'add': add, 'current_pack': sc.pack_of(s)}


def _add_owned_region(s, pm, name, c):
    """Adds to the scenario a map region that does not come from another: owner/controller, terrain, population (the one set
    by hand or the country average density times its area) and historic countries from the changelog; what is inside goes to it."""
    import scenario_new
    notes0 = scenario_new.prepare_region(s, c) if c.get('nacion') else []
    owner = match_country(s, c['pais'])
    if owner is None:
        return ['AVISO: %s no se ha añadido: el país %s no existe en este escenario' % (name, c['pais'])]
    if owner != c['pais']:
        c = dict(c, pais=owner, controlador=match_country(s, c.get('controlador')) or owner)
    population = c.get('poblacion_manual')
    if population is None:
        ub = {pm.name[g.index]: g.u_b for g in pm.m['regions']}
        regs = [r for r in s.regions(sea=False) if prop(r, 'strOwner') == owner]
        pop = sum(int(prop(r, 'nPopulation')) for r in regs if (prop(r, 'nPopulation') or '').isdigit())
        area = sum(ub.get(prop(r, 'strName'), 0) for r in regs)
        population = int(round(pop / area * ub.get(name, 0))) if area else 0
        if population <= 2:
            population = 1000          # a region with 0-2 inhabitants is not valid (the game treats it as empty)
    notes = notes0 + sc.add_new_region(s, name, owner=owner, terrain=c.get('terreno'), population=population, text=c.get('texto'))
    ctl = c.get('controlador')
    reg = next((r for r in s.regions(sea=False) if prop(r, 'strName') == name), None)
    if reg is not None and ctl and ctl != owner and ctl in s.countries():
        s.update(s.s.eid(reg), {'strController': ctl})
        notes.append('%s: controlador %s' % (name, ctl))
    if c.get('historicos'):          # empty or not chosen: stays as historic of its owner
        notes += set_historic(s, name, c['historicos'])
    notes += reassign_by_geometry(s, name, pm.geom(name))
    notes += _city_and_liberate(s, name, c, pm.geom(name))
    notes += scenario_new.finish_region(s, c, name)
    return notes


def _city_and_liberate(s, region, c, geom):
    """City requested when creating the region (if there is none inside already and one was requested) and, if the owner was surrendered, liberates it."""
    reg = next((r for r in s.regions(sea=False) if prop(r, 'strName') == region), None)
    if reg is None:
        return []
    notes = []
    want = c.get('ciudad') if c else None
    if want and want.get('name') and not any(ci.get('type') == 'City' for ci in objs(reg)):
        x, y = want.get('x'), want.get('y')
        if x in (None, '') or y in (None, ''):
            if geom is None:
                return ['AVISO: no se pudo elegir un punto al azar para la ciudad %s' % want['name']]
            x, y = random_point_in(geom, region)
        try:
            notes += create_city(s, want['name'], float(x), float(y), want.get('ipus', 1), want.get('population', 0),
                                 want.get('display'), want.get('port') or None, region=region)[1]
        except ValueError as e:
            notes.append('AVISO ciudad %s: %s' % (want['name'], e))
    return notes + unsurrender(s, prop(reg, 'strOwner'), region)


def island_source(pm, name, land, eqs=None):
    """Region with data from which to take a land region that has no land neighbors with data (an island surrounded by sea):
    its vanilla equivalent (changelog) if the scenario has it and, otherwise, the nearest land region with data. None if none."""
    eqs = pack_equivalences(pm) if eqs is None else eqs
    m = next((v for v in eqs.get(name) or [] if v in land and v != name), None)
    if m:
        return m
    g = pm.geom(name)
    if g is None:
        return None
    best, d = None, None
    for r in land:
        if r == name or pm.sea.get(r, True):
            continue
        gr = pm.geom(r)
        if gr is None:
            continue
        d_ = g.distance(gr)
        if d is None or d_ < d:
            best, d = r, d_
    return best


def pack_pop_table(pack):
    """Reference population of the regionpack (poblacion.json: {region: {pop, mother}}), or {} if it has none."""
    import editor_core
    f = os.path.join(editor_core.MAPS, pack, 'poblacion.json')
    try:
        return json.load(open(f, encoding='utf-8')).get('regiones') or {}
    except (OSError, ValueError):
        return {}


def pack_equivalences(pm):
    """{regionpack region: [vanilla regions]} according to its changelog (regiones_nuevas.equivale and «equivalencias» entries)."""
    out = {}
    for e in pm.changelog:
        for x in e.get('regiones_nuevas', []):
            if x.get('equivale'):
                out[x['nombre']] = list(x['equivale'])
        for k, v in (e.get('equivalencias') or {}).items():
            if v:
                out[k] = list(v)
            else:
                out.pop(k, None)
    return out


def apply_equivalences(s, pm):
    """World scenario -> regionpack made from scratch: each new region that claims to be equivalent to vanilla regions replaces them:
    it is born from the first (owner, controller, culture) and takes the cities, resources, units and population of all of them."""
    notes = []
    land = {prop(r, 'strName') for r in s.regions(sea=False)}
    made = {x['nombre']: for_scenario(x, s.name) for e in pm.changelog for x in e.get('regiones_nuevas', [])}
    for new, vanilla in pack_equivalences(pm).items():
        have = [v for v in vanilla if v in land and v != new and pm.sea.get(v) is None]
        if new in land or not have or pm.sea.get(new, True):
            continue
        c = made.get(new, {})
        notes += sc.add_new_region(s, new, mother=have[0], fraction=1.0, goes_to_new=lambda x, y: True, text=c.get('texto'),
                                   terrain=c.get('terreno'))
        for v in have[1:] + have[:1]:
            notes += sc.remove_new_region(s, v, new)
            land.discard(v)
        land.add(new)
        notes.append('%s equivale a %s' % (new, ', '.join(have)))
        owner = c.get('pais')
        reg = next((r for r in s.regions(sea=False) if prop(r, 'strName') == new), None)
        if reg is not None and owner and owner in s.countries() and prop(reg, 'strOwner') != owner:
            notes += s.update(s.s.eid(reg), {'strOwner': owner, 'strController': c.get('controlador') or owner})
    return notes


# the same country with different names (vanilla first): when importing GeoJSON or crossing scenarios they count as one
# (also in editor/index.html, natKey)
COUNTRY_EQUIV = [('Salvador', 'El Salvador'), ('Swaziland', 'Eswatini'), ('Burma', 'Myanmar'),
                 ('South Africa', 'Union of South Africa')]


def country_key(t):
    """Key to compare country names: without case, accents, spaces or punctuation, and with the COUNTRY_EQUIV equivalences."""
    import unicodedata
    n = lambda x: re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(x)).encode('ascii', 'ignore').decode('ascii').lower())
    k = n(t)
    for grp in COUNTRY_EQUIV:
        if k in {n(x) for x in grp}:
            return n(grp[0])
    return k


def match_country(s, name):
    """Scenario country matching 'name' even if written differently: «UnitedKingdom» (MH2) = «United Kingdom»,
    ignoring case, accents, hyphens or spaces. None if there is none."""
    if not name:
        return None
    cs = s.countries()
    if name in cs:
        return name
    k = country_key(name)
    return next((c for c in cs if country_key(c) == k), None)


def for_scenario(c, scen):
    """Changelog new region entry with the owner (and controller) it gets in scenario 'scen':
    «pais_por_escenario» overrides «pais» (e.g. the region south of Kaliningrad belongs to Poland in one scenario and to Russia in another)."""
    o = (c.get('pais_por_escenario') or {}).get(scen)
    if not o:
        return c
    c = dict(c)
    c['pais'] = o
    c['controlador'] = (c.get('controlador_por_escenario') or {}).get(scen) or o
    return c


def pack_sync_apply(s, pack, switch=True, pop_mode='area'):
    """Applies pack_sync_plan in memory (still needs saving): removes, adds and, if 'switch', changes the scenario regionpack.
    pop_mode (population of new regions taken from another): 'area' (default) splits the inhabitants the source region
    has now by area; 'ref' splits them by the regionpack reference population (poblacion.json)
    keeping the source region total; 'ref_abs' sets the reference figure as is (subtracted from the source)."""
    import progress
    progress.step(5, 'Comparando el escenario con el regionpack %s' % pack)
    pm = PackMap(pack)
    notes = []
    # regiones renombradas en el regionpack (changelog «renombradas»): se renombran, no se quitan y se vuelven a crear
    have = {prop(r, 'strName') for r in s.regions()}
    # also the map.xml RegionRename entries even if the changelog does not note them (renamed before they were noted): without this the
    # region «Rostov» was removed and «Rostov Oblast» recreated from a neighbor, with that neighbor's owner and population
    rens = [{'de': a, 'a': b} for a, b in getattr(pm, 'renames', {}).items() if a != b]
    for e in pm.changelog:
        rens += e.get('renombradas', [])
    for r in rens:
            if r['de'] in have and r['a'] not in have and r['a'] in pm.sea:
                progress.step(8, 'Renombrando %s a %s' % (r['de'], r['a']))
                notes += rename_region(s, r['de'], r['a'], r.get('texto'))
                have.discard(r['de'])
                have.add(r['a'])
    notes += apply_equivalences(s, pm)
    plan = pack_sync_plan(s, pack)
    pdata = pack_pop_table(pack) if pop_mode in ('ref', 'ref_abs') else {}
    pending = {}      # source region -> new regions still to be taken from it (to split correctly among several)
    for x_ in plan['add']:
        if x_['mother'] and not x_['sea']:
            pending.setdefault(x_['mother'], []).append(x_['name'])
    # what was chosen when creating each region (owner, controller, terrain, population) according to the regionpack changelog
    made = {x['nombre']: for_scenario(x, s.name) for e in pm.changelog for x in e.get('regiones_nuevas', [])}
    import progress
    total = len(plan['remove']) + len(plan['add']) or 1
    for i, x in enumerate(plan['remove']):
        progress.part(30, 98)(i, total, 'Quitando la región %s' % x['name'])
        pop_ = 0
        if not x['sea'] and not x['into']:
            reg_ = next((r for r in s.regions(sea=False) if prop(r, 'strName') == x['name']), None)
            pop_ = int(prop(reg_, 'nPopulation') or 0) if reg_ is not None else 0
        notes += sc.remove_new_region(s, x['name'], x['into'])
        if pop_:
            notes.append('AVISO: %s no tiene región del mapa nuevo adonde ir: se pierden sus %s habitantes' % (x['name'], format(pop_, ',').replace(',', '.')))
        if not x['sea'] and not x['into'] and x['cities']:
            notes.append('AVISO: %s no tenía adónde volver; se pierden %s' % (x['name'], ', '.join(x['cities'])))
    for i, x in enumerate(plan['add']):
        progress.part(30, 98)(len(plan['remove']) + i, total, 'Añadiendo la región %s' % x['name'])
        try:
            if x['sea']:
                notes += add_sea_region(s, x['name'], x['mother'])
                notes += reassign_by_geometry(s, x['name'], pm.geom(x['name']), sea=True)
                notes += reassign_ports(s, x['name'], pm.geom(x['name']), pm.geom)
                continue
            c = made.get(x['name'], {})
            if c and (not c.get('madre') or not x['mother']) and c.get('pais') and (match_country(s, c['pais']) or not x['mother']):     # without a mother in the scenario (e.g. it came from the sea)
                # region created without a source region (e.g. an island in the sea): with the owner, terrain and population from the changelog
                notes += _add_owned_region(s, pm, x['name'], c)
                continue
            if not x['mother']:
                notes.append('AVISO: %s no se ha añadido: no sale de ninguna región con datos y el changelog no dice de qué país es '
                             '(revisa el changelog o créala de nuevo con su propietario)' % x['name'])
                continue
            if pm.geom(x['mother']) is not None and pm.geom(x['name']) is not None and pm.geom(x['mother']).distance(pm.geom(x['name'])) > 1e-3:
                notes.append('%s: sin vecinas de tierra con datos; sus datos salen de %s' % (x['name'], x['mother']))
            gn, gm = pm.geom(x['name']), pm.geom(x['mother'])
            land = {prop(r, 'strName') for r in s.regions(sea=False)}
            pops = {k: v for k, v in (c.get('poblacion') or {}).items() if k in land}
            sib = [n_ for n_ in pending.get(x['mother'], []) if n_ != x['name']]
            pending[x['mother']] = sib
            def _w(n_):      # split weight: reference population or, if missing, area
                g_ = pm.geom(n_)
                return (pdata[n_]['pop'] if n_ in pdata else None), (g_.area if g_ is not None else 0)
            ws = [_w(n_) for n_ in [x['name'], x['mother']] + sib]
            use_ref = bool(pdata) and all(w[0] is not None for w in ws) and sum(w[0] for w in ws) > 0
            if use_ref:
                rest = sum(w[0] for w in ws)
                fr = ws[0][0] / rest if rest else 0
            else:
                rest = sum(w[1] for w in ws)       # its area + that of the source region + that of the ones still missing
                fr = ws[0][1] / rest if rest else 0
            fixed = c.get('fraccion') if not pdata and pop_mode == 'area' else None   # fraction chosen when creating it in the editor
            notes += sc.add_new_region(s, x['name'], mother=x['mother'], fraction=0 if pops else (fixed or fr),
                                       text=c.get('texto'), terrain=c.get('terreno'))
            if pops:
                notes += move_population(s, x['name'], pops)
            elif pop_mode == 'ref_abs' and use_ref:
                notes += set_population_from(s, x['name'], x['mother'], pdata[x['name']]['pop'])
            if c.get('poblacion_manual') is not None and not pops:
                notes += set_region_population(s, x['name'], c['poblacion_manual'])
            if c.get('historicos') is not None:
                notes += set_historic(s, x['name'], c['historicos'])
            vals = {k: v for k, v in (('strOwner', c.get('pais')), ('strController', c.get('controlador') or c.get('pais'))) if v}
            reg = next((r for r in s.regions(sea=False) if prop(r, 'strName') == x['name']), None)
            if reg is not None and vals and any(prop(reg, k) != v for k, v in vals.items()):
                if 'strOwner' in vals:
                    vals = {k: (match_country(s, v) or v) for k, v in vals.items()}
                if vals['strOwner'] in s.countries() if 'strOwner' in vals else True:
                    s.update(s.s.eid(reg), vals)
                else:
                    notes.append('%s: el país %s no existe en este escenario; se queda con el de %s' % (x['name'], vals['strOwner'], x['mother']))
            notes += reassign_by_geometry(s, x['name'], gn)
            notes += _city_and_liberate(s, x['name'], c, gn)
        except ValueError as e:
            notes.append('ERROR %s: %s' % (x['name'], e))
    notes += rehome_transferred(s, pm)
    if switch and sc.pack_of(s) != pack:
        notes += set_pack(s, pack)
    else:
        notes += fix_sprite_map(s)
    return {'notes': notes, 'plan': plan}


def rehome_transferred(s, pm):
    """Changelog transfers (cut / add area between existing regions): cities and resources that were in the region
    the area came from and that now fall inside the region that received it move to the latter. Only the source and
    destination regions named by the changelog are checked; a city that falls in none of them is not touched."""
    from shapely.geometry import Point
    st = s.s
    src, dst = set(), set()
    for e in pm.changelog:
        for t in e.get('traspasos', []):
            if t.get('de') and t.get('a'):
                src.add(t['de'])
                dst.add(t['a'])
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    src &= set(land)
    dst &= set(land)
    notes = []
    if not src or not dst:
        return notes
    geo = {n: pm.geom(n) for n in dst if pm.geom(n) is not None}
    for t in ('City', 'Producer'):
        for c in s.all(t):
            par = st.parent.get(c)
            if par is None or prop(par, 'strName') not in src:
                continue
            xy = sc.parse_vec(prop(c, 'vecPosition'))
            if xy is None:
                continue
            own = pm.geom(prop(par, 'strName'))
            pt = Point(xy[0], xy[1])
            if own is not None and own.buffer(1e-6).covers(pt):
                continue
            for n, g in geo.items():
                if n != prop(par, 'strName') and g.buffer(1e-6).covers(pt):
                    s.update(st.eid(c), {'__region': n})
                    notes.append('%s %s pasa de %s a %s (área traspasada)' % ('ciudad' if t == 'City' else 'recurso', prop(c, 'strName'), prop(par, 'strName'), n))
                    break
    return notes


# ------------------------------------------------------------------ rename a region (with the map.xml RegionRename)
# properties holding region names (not country ones: strOwner, strCountry, strHomelands... are not touched)
REGION_PROPS = {'strRegion', 'strRegions', 'strPortForRegion', 'strRegionList', 'strTargetRegionList', 'strMyRegionNames',
                'strRegionName'}


def rename_region(s, old, new, text=None):
    """Renames a region in the whole scenario (its Region object and all references) and its visible text."""
    st = s.s
    names = {prop(r, 'strName'): r for r in s.regions()}
    if old not in names:
        return ['%s: no está en este escenario' % old]
    if new in names:
        raise ValueError('ya existe una región llamada %s en el escenario' % new)
    reg = names[old]
    st.set_prop(reg, 'strName', new)
    n = 0
    for p in s.paths:
        for el in st.docs[p].getroot().iter('property'):
            if el.get('name') in REGION_PROPS and el.get('value') == old:
                el.set('value', new)
                st.dirty.add(p)
                n += 1
    notes = ['región %s → %s (%d referencias)' % (old, new, n)]
    sid = prop(reg, 'sidName')
    if sid and text:
        notes += sc.set_region_string(s, sid, text)
    return notes


# ------------------------------------------------------------------ create cities, resources and armies
def _land_region_at(s, x, y):
    """(scenario Region, name) containing the point, according to the map of its regionpack."""
    pack = sc.pack_of(s)
    pm = pack_map(pack)
    n = pm.region_at(x, y)
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    if n is None or n not in land:
        raise ValueError('el punto (%.3f, %.3f) no está dentro de ninguna región de tierra del escenario' % (x, y))
    return land[n], n


def _vec(x, y):
    return '[%s, %s, 0]' % (repr(float(x)), repr(float(y)))


_PM = {}


def pack_map(pack):
    """Reusable PackMap (re-read if regions.bin changes): computed shapes stay in memory."""
    import editor_core
    f = os.path.join(editor_core.MAPS, pack, 'xml', 'regions.bin')
    key = (pack, os.path.getmtime(f) if os.path.exists(f) else None)
    if _PM.get(pack, (None,))[0] != key:
        _PM[pack] = (key, PackMap(pack))
    return _PM[pack][1]


def scenario_pack(s):
    """Regionpack used by the scenario (strMapName of scenario.xml); World if not stated."""
    sx = s.all('Scenario', lambda f: f == 'scenario.xml')
    disp = next((o for o in sx[0].iter('object') if o.get('type') == 'ScenarioDisplaySettings'), None) if sx else None
    return (prop(disp, 'strMapName') if disp is not None else None) or 'World'


def region_point(s, region):
    """Random (x, y) inside 'region' in the map of the scenario regionpack."""
    try:
        g = pack_map(scenario_pack(s)).geom(region)
    except ValueError as e:
        raise ValueError('no puedo situar el punto en %s: %s; indica la posición' % (region, e))
    if g is None:
        raise ValueError('la región %s no está en el mapa del regionpack: indica la posición' % region)
    return random_point_in(g, region)


def random_point_in(geom, seed=None):
    """Random point inside a geometry (by rejection; if that fails, a representative point)."""
    import random
    from shapely.geometry import Point
    rnd = random.Random(seed)
    x0, y0, x1, y1 = geom.bounds
    for _ in range(400):
        p = Point(rnd.uniform(x0, x1), rnd.uniform(y0, y1))
        if geom.contains(p):
            return p.x, p.y
    p = geom.representative_point()
    return p.x, p.y


def create_city(s, name, x, y, ipus=1, population=0, display=None, port=None, region=None, owner=None):
    """New city at (x, y): goes inside the region containing the point and belongs to its owner. Its visible name goes to the
    scenario stringTable. 'port': sea region of the port (optional)."""
    st = s.s
    name = (name or '').strip()
    if not name:
        raise ValueError('la ciudad necesita un nombre')
    if any(prop(c, 'strName') == name for c in s.all('City')):
        raise ValueError('ya existe una ciudad llamada %s' % name)
    notes = []
    if region:      # chosen region (land or sea, e.g. a base in Antarctica); the point may fall outside
        reg = next((r for r in s.regions(sea=False) + s.regions(sea=True) if prop(r, 'strName') == region), None)
        if reg is None:
            raise ValueError('no existe la región %s' % region)
        rname = region
        try:
            here = _land_region_at(s, x, y)[1]
        except Exception:
            here = None
        if here != region:
            notes.append('aviso: el punto (%s, %s) queda fuera de %s%s' % (x, y, region, ' (está en %s)' % here if here else ''))
    else:
        reg, rname = _land_region_at(s, x, y)
    owner = owner or prop(reg, 'strOwner')
    if not owner:
        raise ValueError('la región %s no tiene dueño: elige el país de la ciudad' % rname)
    seas = {prop(r, 'strName') for r in s.regions(sea=True)}
    if port and port not in seas:
        raise ValueError('«%s» no es una región de mar del escenario' % port)
    el = ET.Element('object', {'type': 'City', 'name': 'objGOs'})
    for k, v in (('strName', name), ('strOwner', owner), ('vecPosition', _vec(x, y)), ('nDirection', '0'),
                 ('nPopulation', str(int(population or 0))), ('strPortForRegion', port or None), ('strInitialWorkOrder', '')):
        if v is not None:
            ET.SubElement(el, 'property', {'name': k, 'value': v})
    fac = ET.SubElement(el, 'object', {'type': 'Factory', 'name': 'objFactory'})
    ET.SubElement(fac, 'property', {'name': 'nIPUs', 'value': str(int(ipus))})
    st.attach(el, reg)
    notes = ['ciudad %s creada en %s (de %s), %s IPUs' % (name, rname, owner, int(ipus))] + notes
    if display:
        notes += sc.set_region_string(s, 'SID.Game.City.Name.' + re.sub(r'[^A-Za-z0-9]', '', name), display.strip())
    return st.eid(el), notes


def fix_landless(s, country, action, member=None, regions=None):
    """A country with no land counts as surrendered and breaks its alliance's wars. 'regions': its historic regions (with their
    cities) become its own and it stops being surrendered; 'leave': the AllianceMember 'member' is removed."""
    st = s.s
    if action == 'leave':
        el = st.get(member)
        if el is None or el.get('type') != 'AllianceMember':
            raise ValueError('ese miembro de alianza ya no existe')
        st.remove(el)
        return ['%s sale de la alianza' % country]
    if action != 'regions':
        raise ValueError('acción desconocida: %s' % action)
    names = set(regions or ()) or {prop(k, 'strRegion') for h in s.all('HistoricCountry') if prop(h, 'strCountry') == country for k in objs(h)}
    moved = []
    for r in s.regions(sea=False):
        if prop(r, 'strName') in names and prop(r, 'strOwner') != country:
            moved.append('%s (de %s)' % (prop(r, 'strName'), prop(r, 'strOwner')))
            s.update(st.eid(r), {'strOwner': country, 'strController': country})
    if not moved:
        raise ValueError('%s no tiene regiones históricas que se le puedan dar' % country)
    return ['%s recibe %s' % (country, ', '.join(moved))] + unsurrender(s, country)


def unsurrender(s, owner, region=None):
    """If 'owner' was surrendered (bSurrendered) and now has regions: it stops being so and its capital moves to a city in its
    territory (of 'region' if any, otherwise the one with most IPUs). Without a city in its territory it warns that one must be created."""
    st = s.s
    c = s.countries().get(owner)
    if c is None or prop(c, 'bSurrendered') != 'true':
        return []
    own = [r for r in s.regions(sea=False) if prop(r, 'strOwner') == owner]
    if not own:
        return []
    st.set_prop(c, 'bSurrendered', 'false')
    notes = ['%s deja de estar rendido' % owner]
    cities = {prop(ci, 'strName'): (ci, r) for r in own for ci in objs(r) if ci.get('type') == 'City'}
    cap = prop(c, 'strCapital')
    if cap in cities:
        return notes + ['capital %s: ya está en su territorio' % cap]
    if not cities:
        reg = region if region in {prop(r, 'strName') for r in own} else prop(own[0], 'strName')
        return notes + ['AVISO: %s no tiene ninguna ciudad en su territorio (%s): asígnale una región con ciudad o crea una en la región para que sea su capital'
                        % (owner, reg)]

    def ipus(ci):
        f = next((o for o in objs(ci) if o.get('type') == 'Factory'), None)
        v = prop(f, 'nIPUs') if f is not None else '0'
        return int(v) if (v or '').isdigit() else 0
    pool = [n for n, (ci, r) in cities.items() if region and prop(r, 'strName') == region] or list(cities)
    best = max(pool, key=lambda n: ipus(cities[n][0]))
    st.set_prop(c, 'strCapital', best)
    notes.append('capital de %s: %s (%s)' % (owner, best, prop(cities[best][1], 'strName')))
    if not prop(c, 'strOriginalCapital'):
        st.set_prop(c, 'strOriginalCapital', best)
    return notes


def create_producer(s, name, resource, x, y, output=1):
    """New resource (producer) at (x, y), inside the region containing the point."""
    st = s.s
    name = (name or '').strip()
    if not name:
        raise ValueError('el recurso necesita un nombre')
    res = {prop(p, 'strResource') for p in s.all('Producer')}
    if resource not in res:
        raise ValueError('recurso desconocido: %s (hay: %s)' % (resource, ', '.join(sorted(r for r in res if r))))
    reg, rname = _land_region_at(s, x, y)
    owner = prop(reg, 'strOwner')
    el = ET.Element('object', {'type': 'Producer', 'name': 'objGOs'})
    for k, v in (('strName', name), ('strOwner', owner), ('vecPosition', _vec(x, y)), ('strResource', resource), ('nBaseOutputRate', str(int(output)))):
        ET.SubElement(el, 'property', {'name': k, 'value': v})
    st.attach(el, reg)
    return st.eid(el), ['recurso %s (%s, %s) creado en %s (de %s)' % (name, resource, int(output), rname, owner)]


def create_army(s, owner, name, region, units):
    """New army of 'owner' in 'region'. units: [{'type': template, 'n': number}]."""
    st = s.s
    countries = s.countries()
    if owner not in countries:
        raise ValueError('no existe el país %s' % owner)
    name = (name or '').strip()
    if not name:
        raise ValueError('el ejército necesita un nombre')
    regions = {prop(r, 'strName') for r in s.regions()}
    if region not in regions:
        raise ValueError('no existe la región %s' % region)
    templates = {prop(t, 'strName') for t in s.all('UnitTemplate')}
    units = [u for u in units or [] if int(u.get('n') or 0) > 0]
    if not units:
        raise ValueError('el ejército necesita al menos una unidad')
    for u in units:
        if u['type'] not in templates:
            raise ValueError('tipo de unidad desconocido: %s' % u['type'])
    if any(prop(a, 'strName') == name and prop(a, 'strOwner') == owner for a in s.all('Army')):
        raise ValueError('%s ya tiene un ejército llamado %s' % (owner, name))
    el = ET.Element('object', {'type': 'Army', 'name': 'objGOs'})
    for k, v in (('strName', name), ('strOwner', owner), ('strRegion', region)):
        ET.SubElement(el, 'property', {'name': k, 'value': v})
    for u in units:
        o = ET.SubElement(el, 'object', {'type': 'UnitSummary', 'name': 'objUnits'})
        ET.SubElement(o, 'property', {'name': 'strName', 'value': u['type']})
        ET.SubElement(o, 'property', {'name': 'nNumber', 'value': str(int(u['n']))})
    country = countries[owner]
    kids = list(country)
    arm = [k for k, x in enumerate(kids) if x.tag == 'object' and x.get('type') == 'Army']
    st.attach(el, country, index=(arm[-1] + 1) if arm else None)
    return st.eid(el), ['ejército %s de %s creado en %s con %s' % (name, owner, region, ', '.join('%d %s' % (int(u['n']), u['type']) for u in units))]


# ------------------------------------------------------------------ state of relations among several countries
COUNTRY_KEYS = {'strName', 'strCountry', 'strFromCountry', 'strToCountry', 'strINITCountryName', 'strINITAttackerCountryName',
                'strINITDefenderCountryName', 'strOwner', 'strTargetCountry'}


def relations(s, countries):
    """Relations among the chosen countries at scenario start: alliances, wars, trade, aid, agreements (military
    access...), embargoes and the scheduled events that mention them (and those that declare war or depend on one)."""
    cs = set(countries)
    pairs = {}

    def tag(a, b, text):
        if a in cs and b in cs and a != b:
            pairs.setdefault(tuple(sorted((a, b))), []).append(text)
    amembers = {}
    for al in s.all('Alliance'):
        mem = [prop(m, 'strINITCountryName') for m in objs(al) if m.get('type') == 'AllianceMember']
        amembers[prop(al, 'strINITAllianceName')] = mem
        for i, a in enumerate(mem):
            for b in mem[i + 1:]:
                tag(a, b, 'aliados (%s)' % _alliance_name(al))
    for w in s.all('War'):
        att = {prop(w, 'strINITAttackerCountryName')} | set(amembers.get(prop(w, 'strINITOffenseAllianceName') or '', []))
        dfn = {prop(w, 'strINITDefenderCountryName')} | set(amembers.get(prop(w, 'strINITDefenseAllianceName') or '', []))
        for a in att - {None, ''}:
            for b in dfn - {None, ''}:
                tag(a, b, 'en guerra (%s)' % (prop(w, 'strDisplayName') or 'guerra'))
    for f in s.all('Flow'):
        k = f.get('name')
        a, b = prop(f, 'strFromCountry'), prop(f, 'strToCountry')
        if k in ('objFlows', 'objTradeFlows'):
            tag(a, b, 'comercio %s → %s' % (a, b))
        elif k == 'objAidFlows':
            tag(a, b, 'ayuda %s → %s' % (a, b))
    for t in s.all('TreatyAgreement'):
        a, b = prop(t, 'strFromCountry'), prop(t, 'strToCountry')
        tag(a, b, '%s (%s)' % (prop(t, 'strName') or 'acuerdo', (prop(t, 'eTreatyState') or '').replace('TREATY_', '').lower()))
    events = []
    for ev in s.all('ScriptedEventDef'):
        vals = {e.get('value') for e in ev.iter('property') if e.get('name') in COUNTRY_KEYS and e.get('value')}
        hit = sorted(vals & cs)
        if not hit:
            continue
        types = {o.get('type') for o in ev.iter('object')}
        kind = ('declara guerra' if 'ActProposeDeclareWar' in types or 'ActDeclareWar' in types else
                'embargo' if any(e.get('value') == 'TRADE_RELATIONS_EMBARGOED' for e in ev.iter('property')) else
                'depende de una guerra' if 'AccessorIsAtWar' in types or 'AccessorGetAllCountryWars' in types else 'otro')
        label = prop(ev, 'strTypeLabel') or '(sin nombre)'
        events.append({'id': s.s.eid(ev), 'label': label, 'countries': hit, 'kind': kind})
        if kind in ('declara guerra', 'embargo') and len(hit) >= 2:
            tag(hit[0], hit[1], 'evento: %s (%s)' % (label, kind))
    dm = _dip_map(s)
    for (a, b), (_e, v) in dm.items():       # initial relation figure of each pair (0 terrible - 1000 excellent)
        if a in cs and b in cs and a < b:
            w = dm.get((b, a))
            if w is None or _num(w[1]) == _num(v):
                tag(a, b, 'relación inicial %s/1000 (%s)' % (v, sc.dip_label(v)))
            else:
                tag(a, b, '⚠ relación inicial distinta: %s → %s = %s (%s) · %s → %s = %s (%s)' % (a, b, v, sc.dip_label(v), b, a, w[1], sc.dip_label(w[1])))
        elif a in cs and b in cs and a > b and (b, a) not in dm:
            tag(b, a, 'relación inicial %s/1000 (%s)' % (v, sc.dip_label(v)))
    names = sorted(cs)
    for i, x in enumerate(names):            # all combinations (A-B, A-C, B-C...), even without a relation
        for y in names[i + 1:]:
            pairs.setdefault((x, y), [])
    return {'countries': sorted(cs), 'pairs': [{'a': k[0], 'b': k[1], 'tags': v,
                                                 'dip': {'ab': (dm.get((k[0], k[1])) or (None, None))[1], 'ba': (dm.get((k[1], k[0])) or (None, None))[1]}}
                                                for k, v in sorted(pairs.items())],
            'events': sorted(events, key=lambda e: (e['kind'] == 'otro', e['label']))}


def bulk_elements(s, ids, op, field=None, value=None):
    """Acciones en lote sobre ciudades, recursos y unidades: 'delete' o 'set' (ipus, population, output, owner)."""
    st = s.s
    notes = []
    for i in ids:
        el = st.get(i)
        t, name = el.get('type'), prop(el, 'strName') or el.get('type')
        if op == 'delete':
            if t == 'City':
                for c in s.countries().values():
                    for k in ('strCapital', 'strOriginalCapital'):
                        if prop(c, k) == name:
                            notes.append('AVISO: %s era %s de %s' % (name, 'la capital' if k == 'strCapital' else 'la capital original', prop(c, 'strName')))
            st.remove(el)
            notes.append('%s %s eliminado' % (t, name))
        elif field == 'ipus' and t == 'City':
            f = next((o for o in objs(el) if o.get('type') == 'Factory'), None)
            if f is None:
                notes.append('%s: sin fábrica' % name)
                continue
            if not str(value).strip().isdigit():
                raise ValueError('los IPUs deben ser un número entero')
            st.set_prop(f, 'nIPUs', str(int(value)))
            notes.append('%s: %s IPUs' % (name, int(value)))
        elif field == 'population' and t == 'City':
            if not str(value).strip().isdigit():
                raise ValueError('la población debe ser un número entero')
            st.set_prop(el, 'nPopulation', str(int(value)))
            notes.append('%s: %s hab.' % (name, int(value)))
        elif field == 'output' and t == 'Producer':
            if not str(value).strip().isdigit():
                raise ValueError('la producción debe ser un número entero')
            st.set_prop(el, 'nBaseOutputRate', str(int(value)))
            notes.append('%s: producción %s' % (name, int(value)))
        elif field == 'owner' and t in ('Army', 'AirForce', 'Fleet'):
            notes += ['%s: %s' % (name, n) for n in s.update(i, {'strOwner': value})] or ['%s: país %s' % (name, value)]
        else:
            notes.append('%s: no se puede cambiar «%s»' % (name, field))
    s._opts = None
    return notes



# ------------------------------------------------------------------ actions on countries (multiple selection)
def transfer_assets(s, sources, dest, regions=True, units=True):
    """The regions (with their cities and resources) and military units of 'sources' go to 'dest'."""
    countries = s.countries()
    if dest not in countries:
        raise ValueError('no existe el país %s' % dest)
    notes = []
    for src in sources:
        if src == dest or src not in countries:
            continue
        if regions:
            mine = [r for r in s.regions(sea=False) if prop(r, 'strOwner') == src]
            for r in mine:
                s.update(s.s.eid(r), {'strOwner': dest, 'strController': dest})
            if mine:
                notes.append('%s → %s: %d región(es) con sus ciudades y recursos' % (src, dest, len(mine)))
        if units:
            n = 0
            for t in ('Army', 'AirForce', 'Fleet'):
                for g in list(s.all(t)):
                    if prop(g, 'strOwner') == src:
                        s.update(s.s.eid(g), {'strOwner': dest})
                        n += 1
            if n:
                notes.append('%s → %s: %d unidad(es) militar(es)' % (src, dest, n))
    if regions:
        notes += unsurrender(s, dest)
    return notes


def _owned(s, name):
    regs = [r for r in s.regions(sea=False) if prop(r, 'strOwner') == name]
    units = [g for t in ('Army', 'AirForce', 'Fleet') for g in s.all(t) if prop(g, 'strOwner') == name]
    return regs, units


def duplicate_countries(s):
    """[(duplicate, good)]: nations that are the same written differently («UnitedStates» / «United States»). Keeps the one whose
    name is written as in vanilla (no joined words: «South Africa», not «UnionOfSouthAfrica») and, if tied, the one
    with more regions. Also
    «ElSalvador» / «Salvador» and «UnionOfSouthAfrica» / «South Africa» (article or «Union of» in front)."""
    import unicodedata
    norm = lambda t: re.sub(r'^(el|la|the|unionof)(?=[a-z]{4})', '', country_key(t))
    groups = {}
    for c in s.countries():
        groups.setdefault(norm(c), []).append(c)
    out = []
    for g in groups.values():
        if len(g) > 1:
            keep = max(g, key=lambda c: (not re.search(r'[a-z][A-Z]', c), len(_owned(s, c)[0])))   # «UnionOfSouthAfrica» shows like this in the game
            out += [(c, keep) for c in g if c != keep]
    return out


def merge_country(s, dup, keep):
    """Merges nation 'dup' into 'keep' (the same one written differently): its regions, units and historic regions go to 'keep'
    and 'dup' is removed from the scenario."""
    notes = []
    hist = [prop(k, 'strRegion') for h in s.all('HistoricCountry') if prop(h, 'strCountry') == dup for k in objs(h)]
    have = {prop(k, 'strRegion') for h in s.all('HistoricCountry') if prop(h, 'strCountry') == keep for k in objs(h)}
    for r in hist:
        if r and r not in have:
            toggle_historic(s, keep, r); have.add(r)
    play = [w for w in s.all('WrappedString') if w.get('name') == 'objPlayableCountries']
    for w in play:                         # playable countries (scenarioinfo.xml): the duplicate becomes the good one, without repeating
        if prop(w, 'strString') == dup:
            if any(prop(x, 'strString') == keep for x in play):
                s.s.remove(w)
            else:
                s.s.set_prop(w, 'strString', keep)
    for v in s.all('View'):                # map views (game.xml): alias of the duplicate -> the good one, without repeating
        al = [p for p in v if p.tag == 'property' and p.get('name') == 'strAliases']
        for p in al:
            if p.get('value') == dup:
                if any(x.get('value') == keep for x in al):
                    v.remove(p)
                else:
                    p.set('value', keep)
                s.s.touch(v, structural=True)
    cs = s.countries()
    if prop(cs[dup], 'bNonPlayable') == 'false' and prop(cs[keep], 'bNonPlayable') == 'true':
        s.s.set_prop(cs[keep], 'bNonPlayable', 'false')     # if the duplicate was playable, the good one too
    for t in s.all('TriggerCountry'):      # AI triggers of other countries («war if they invade dup») -> the good one
        if prop(t, 'strName') == dup:
            s.s.set_prop(t, 'strName', keep)
    notes += delete_country(s, dup, keep)
    return ['%s fusionado en %s (%d región(es) histórica(s))' % (dup, keep, len(hist))] + notes


def delete_country(s, name, dest=None):
    """Removes a country from the scenario: its regions and units go to 'dest' (required if it has any), it is removed from alliances, wars,
    trade, aid, agreements and historic countries, and its files stop being loaded (country*/player*.xml leave game.xml and
    the player leaves gamestate.xml; the files stay in the folder but the game ignores them)."""
    st = s.s
    countries = s.countries()
    if name not in countries:
        raise ValueError('no existe el país %s' % name)
    regs, units = _owned(s, name)
    notes = []
    if regs or units:
        if not dest or dest == name:
            raise ValueError('%s tiene %d región(es) y %d unidad(es): elige a qué país pasan' % (name, len(regs), len(units)))
        notes += transfer_assets(s, [name], dest)
    # alliances: removed as a member (if it was the leader, passes to another or the alliance disappears)
    for al in list(s.all('Alliance')):
        mem = [m for m in objs(al) if m.get('type') == 'AllianceMember']
        for m in [m for m in mem if prop(m, 'strINITCountryName') == name]:
            notes += leave_alliance(s, al, m)
            if al not in s.all('Alliance'):
                break
    for w in list(s.all('War')):
        if name in (prop(w, 'strINITAttackerCountryName'), prop(w, 'strINITDefenderCountryName')):
            st.remove(w)
            notes.append('guerra %s: quitada' % (prop(w, 'strDisplayName') or '?'))
    for f in list(s.all('Flow')):
        if name in (prop(f, 'strFromCountry'), prop(f, 'strToCountry')):
            st.remove(f)
    for t in list(s.all('TreatyAgreement')):
        if name in (prop(t, 'strFromCountry'), prop(t, 'strToCountry')):
            st.remove(t)
    for h in list(s.all('HistoricCountry')):
        if prop(h, 'strCountry') == name:
            st.remove(h)
    for ev in list(s.all('ScriptedEventDef')):
        if any(o.get('type') == 'PlayerGenNames' and prop(o, 'strName') == name for o in objs(ev)):
            st.remove(ev)
            notes.append('evento %s: quitado (era de %s)' % (prop(ev, 'strTypeLabel'), name))
    # archivos: game.xml deja de cargarlos; el jugador sale de gamestate.xml
    for g in s.all('GO'):
        ff = g.get('fromFile') or ''
        if ff in ('country%s.xml' % name, 'player%s.xml' % name):
            st.remove(g)
    for pl in list(s.all('Player', lambda f: f == 'gamestate.xml')):
        if prop(pl, 'strName') == name:
            st.remove(pl)
    s.paths = [p for p in s.paths if os.path.basename(p) not in ('country%s.xml' % name, 'player%s.xml' % name)]
    s._opts = None
    notes.append('%s eliminado del escenario (sus archivos ya no se cargan)' % name)
    return notes


def make_surrendered(s, name, capital, dest=None):
    """Turns a country into a surrendered nation the player can liberate: no regions, with desired capital in 'capital' and
    that region among its historic regions. If it has regions or units, they go to 'dest' (required)."""
    st = s.s
    countries = s.countries()
    c = countries.get(name)
    if c is None:
        raise ValueError('no existe el país %s' % name)
    cities = _city_region(s)
    if capital not in cities:
        raise ValueError('la ciudad «%s» no existe en el escenario' % capital)
    notes = []
    regs, units = _owned(s, name)
    if regs or units:
        if not dest or dest == name:
            raise ValueError('%s tiene %d región(es) y %d unidad(es): elige a qué país pasan' % (name, len(regs), len(units)))
        notes += transfer_assets(s, [name], dest)
    # the desired capital: cannot belong to this country (it has no regions now); stays as a city of another
    st.set_prop(c, 'bSurrendered', 'true')
    st.set_prop(c, 'strCapital', capital)
    st.set_prop(c, 'strOriginalCapital', capital)
    reg = cities[capital]
    have = set()
    for h in s.all('HistoricCountry'):
        if prop(h, 'strCountry') == name:
            have |= {prop(k, 'strRegion') for k in objs(h)}
    if reg not in have:
        notes.append(toggle_historic(s, name, reg)['note'])
    notes.append('%s es ahora una nación rendida: capital anhelada %s (en %s)' % (name, capital, reg))
    return notes



# ------------------------------------------------------------------ validation of surrendered (liberable) nations
def _best_city_in(s, regions):
    """City (name, region) with most IPUs among the given regions (the one to be desired capital); None if none."""
    st = s.s
    best, score = None, -1
    for c in s.all('City'):
        reg = prop(st.parent.get(c), 'strName')
        if reg not in regions:
            continue
        f = next((o for o in objs(c) if o.get('type') == 'Factory'), None)
        v = prop(f, 'nIPUs') if f is not None else '0'
        sc_ = (int(v) if (v or '').isdigit() else 0) * 10 + (1 if prop(c, 'strPortForRegion') else 0)
        if sc_ > score:
            best, score = (prop(c, 'strName'), reg), sc_
    return best


def surrendered_issues(s):
    """Warnings about surrendered nations (bSurrendered) the player could not liberate: no valid capital, a capital outside
    their historic regions or no historic regions (in that case they do not appear in the game)."""
    out = []
    countries = s.countries()
    for x in surrendered(s):
        name = x['country']
        c = countries.get(name)
        if c is None or prop(c, 'bSurrendered') != 'true' or x['liberable']:
            continue
        hist = set(x['historic'])
        cand = _best_city_in(s, hist) if hist else None
        if not hist:
            msg = ('%s (nación rendida): no aparecerá en el juego como liberable. Le faltan regiones históricas '
                   '(pestaña Historic Countries) y una capital en ellas. Motivos: %s' % (name, '; '.join(x['reasons'])))
        else:
            why = '; '.join(x['reasons'])
            msg = '%s (nación rendida): no se podrá liberar en el juego. %s.' % (name, why[:1].upper() + why[1:])
            if cand is None:
                msg += ' Ninguna de sus regiones históricas tiene una ciudad: crea una (pestaña Cities → ＋ Nueva ciudad).'
        out.append({'level': 'warning', 'msg': msg, 'id': x['id'],
                    'fix': {'kind': 'capital', 'country': name, 'city': cand[0], 'region': cand[1]} if cand else None})
    return out


def auto_capitals(s, only=None):
    """Automatic desired capital for non-liberable surrendered nations: the city with most IPUs in their historic regions."""
    st = s.s
    countries = s.countries()
    notes = []
    for it in surrendered_issues(s):
        fx = it.get('fix')
        if not fx or (only and fx['country'] not in only):
            continue
        c = countries[fx['country']]
        st.set_prop(c, 'strCapital', fx['city'])
        st.set_prop(c, 'strOriginalCapital', fx['city'])
        notes.append('%s: capital anhelada %s (en %s, una de sus regiones históricas)' % (fx['country'], fx['city'], fx['region']))
    if not notes:
        notes.append('no hay naciones rendidas a las que se pueda asignar capital')
    return notes



# ------------------------------------------------------------------ initial diplomatic relations (symmetric)
def _dip_map(s):
    """{(country, towards): (element, value)} of the players' DipRelInitialValue."""
    out = {}
    for e in s.all('DipRelInitialValue'):
        a, b, v = s.owner_of_player(e), prop(e, 'strTargetCountry'), prop(e, 'nValue')
        if a and b:
            out[(a, b)] = (e, v)
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def diplomacy_issues(s):
    """Two countries must have the same relation figure to each other (A->B = B->A) or the game applies different figures.
    Warns about pairs with different values and those defined in one direction only."""
    out = []
    m = _dip_map(s)
    for (a, b), (e, v) in sorted(m.items()):          # outside the range 0 (terrible) - 1000 (excellent)
        x = _num(v)
        if x is None or not (sc.DIP_MIN <= x <= sc.DIP_MAX) or x != int(x):
            out.append({'level': 'error', 'id': s.s.eid(e),
                        'msg': 'Relación diplomática %s → %s = %s: debe ser un entero de %d (pésimas) a %d (excelentes).' % (a, b, v, sc.DIP_MIN, sc.DIP_MAX),
                        'fix': {'kind': 'range', 'id': s.s.eid(e), 'value': str(int(min(sc.DIP_MAX, max(sc.DIP_MIN, round(x))))) if x is not None else '500',
                                'label': 'Ajustar a %s' % (str(int(min(sc.DIP_MAX, max(sc.DIP_MIN, round(x))))) if x is not None else '500')}})
    seen = set()
    for (a, b), (e, v) in sorted(m.items()):
        key = tuple(sorted((a, b)))
        if key in seen or a == b:
            continue
        seen.add(key)
        other = m.get((b, a))
        if other is None:
            if _num(v) == 0:          # no entry equals the default value (0): not a mismatch
                continue
            out.append({'level': 'warning', 'id': s.s.eid(e),
                        'msg': 'Relación diplomática %s → %s = %s, pero %s no define la suya con %s: en el juego las cifras no coinciden.' % (a, b, v, b, a),
                        'fix': {'kind': 'dip', 'a': a, 'b': b, 'use': 'a', 'label': 'Crear %s → %s = %s' % (b, a, v)}})
        elif _num(v) != _num(other[1]):
            out.append({'level': 'error', 'id': s.s.eid(e),
                        'msg': 'Relaciones diplomáticas distintas entre %s y %s: %s → %s = %s pero %s → %s = %s. Deben tener la misma cifra.' % (a, b, a, b, v, b, a, other[1]),
                        'fix': {'kind': 'dip', 'a': a, 'b': b, 'choices': [
                            {'use': 'a', 'label': 'Usar %s' % v}, {'use': 'b', 'label': 'Usar %s' % other[1]},
                            {'use': 'avg', 'label': 'Promedio (%s)' % _fmt_avg(v, other[1])}]}})
    return out


NATION_REFS = ('strOwner', 'strController', 'strTargetCountry', 'strFromCountry', 'strToCountry', 'strCountry', 'strINITCountryName',
               'strINITAttackerCountryName', 'strINITDefenderCountryName')


def duplicate_issues(s):
    """Repeated entries that prevent creating the game: two Players with the same name in gamestate.xml («Found duplicate
    player named …»), the same file loaded twice in game.xml or a repeated alias in a view."""
    out = []
    players = {}
    for p in s.all('Player', lambda f: f == 'gamestate.xml'):
        if prop(p, 'strName'):
            players.setdefault(prop(p, 'strName'), []).append(p)
    for n, ps in sorted(players.items()):
        if len(ps) < 2:
            continue
        own = s.countries().get(n)
        flag = prop(own, 'strFlagName') if own is not None else None
        choices = []
        for k, p in enumerate(ps, 1):
            what = 'bandera %s, color %s, descripción %s' % (prop(p, 'strFlagName') or '—', prop(p, 'colCountryColor') or '—',
                                                         (prop(p, 'sidShortDescription') or '—').split('.')[-1])
            choices.append({'remove': [s.s.eid(x) for x in ps if x is not p], 'label': 'Dejar el n.º %d (%s)' % (k, what),
                            'best': prop(p, 'strFlagName') == flag or (prop(p, 'sidShortDescription') or '').endswith('.' + re.sub(r'[^A-Za-z0-9]', '', n))})
        choices.sort(key=lambda c: not c['best'])
        out.append({'level': 'error', 'id': s.s.eid(ps[0]),
                    'msg': 'gamestate.xml tiene %d jugadores llamados «%s»: el juego no crea la partida («Found duplicate player named %s»). '
                           'Deja uno.' % (len(ps), n, n),
                    'fix': {'kind': 'dupe', 'choices': [{'remove': c['remove'], 'label': c['label']} for c in choices]}})
    pdata = {}
    for p in s.all('MEPlayerData'):
        pdata.setdefault(prop(p, 'strOwner'), []).append(p)
        if prop(p, 'strName') and prop(p, 'strOwner') and prop(p, 'strName') != prop(p, 'strOwner'):
            out.append({'level': 'error', 'id': s.s.eid(p),
                        'msg': '%s: sus datos de jugador se llaman «%s» (deben llamarse como el país; suele venir de copiar una plantilla).'
                               % (prop(p, 'strOwner'), prop(p, 'strName')),
                        'fix': {'kind': 'nation', 'items': [{'id': s.s.eid(p), 'prop': 'strName', 'dip': False}],
                                'choices': [{'value': prop(p, 'strOwner'), 'label': 'Llamarlos %s' % prop(p, 'strOwner')}]}})
    for n, ps in sorted((k, v) for k, v in pdata.items() if k):
        if len(ps) < 2:
            continue
        out.append({'level': 'error', 'id': s.s.eid(ps[0]),
                    'msg': '%s tiene %d datos de jugador (MEPlayerData): el juego no crea la partida («Found duplicate PlayerData»). Deja uno.' % (n, len(ps)),
                    'fix': {'kind': 'dupe', 'choices': [{'remove': [s.s.eid(x) for x in ps if x is not p],
                            'label': 'Dejar el n.º %d (%s, %d elementos dentro)' % (k, prop(p, 'strName') or '—', len(objs(p)))}
                            for k, p in sorted(enumerate(ps, 1), key=lambda kp: -len(objs(kp[1])))]}})
    for v in s.all('View') + s.all('MEGame', lambda f: f == 'game.xml'):
        seen, extra = set(), []
        for p in list(v):
            key = (p.get('name'), p.get('value')) if p.tag == 'property' and p.get('name') == 'strAliases' else \
                ('GO', p.get('fromFile')) if p.tag == 'object' and p.get('fromFile') else None
            if key is None:
                continue
            if key in seen:
                extra.append(p)
            seen.add(key)
        if extra:
            names = ', '.join(sorted({x.get('value') or x.get('fromFile') for x in extra}))
            out.append({'level': 'error', 'id': s.s.eid(v),
                        'msg': 'game.xml repite %s: %s.' % ('archivos cargados' if extra[0].tag == 'object' else 'alias de la vista', names),
                        'fix': {'kind': 'dupe', 'choices': [{'remove_dupes': s.s.eid(v), 'label': 'Quitar los repetidos (%d)' % len(extra)}]}})
    return out


def remove_duplicates(s, remove=None, parent=None):
    """duplicate_issues fix: deletes the chosen Players or the repeated aliases/files of a game.xml object."""
    st = s.s
    n = 0
    for i in remove or []:
        el = st.get(i)
        if el is not None:
            st.remove(el); n += 1
    if parent is not None:
        v = st.get(parent)
        seen = set()
        for p in list(v):
            key = (p.get('name'), p.get('value')) if p.tag == 'property' and p.get('name') == 'strAliases' else \
                ('GO', p.get('fromFile')) if p.tag == 'object' and p.get('fromFile') else None
            if key is None:
                continue
            if key in seen:
                if p.tag == 'object':
                    st.remove(p)
                else:
                    v.remove(p); st.touch(v, structural=True)
                n += 1
            seen.add(key)
    return ['%d entrada(s) repetida(s) quitada(s)' % n]


def unknown_nation_issues(s):
    """References to nations that do not exist in the scenario (e.g. «Cyrpus» for «Cyprus»): the game ignores them or fails.
    Proposes the most similar nation, or deleting the entry if it is a diplomatic relation."""
    import difflib
    names = set(s.countries())
    if not names:
        return []
    found = {}                  # nombre inexistente -> [(objeto, propiedad, archivo)]
    for p in s.paths:
        for obj in s.s.docs[p].getroot().iter('object'):
            if (obj.get('type') or '').startswith(('Act', 'Accessor', 'Rule')):
                continue
            for pr in obj.findall('property'):
                n, v = pr.get('name'), (pr.get('value') or '').strip()
                if n in NATION_REFS and v and v not in names and not v.startswith(('{', '$')):
                    found.setdefault(v, []).append((obj, n, os.path.basename(p)))
    out = []
    for v, refs in sorted(found.items()):
        near = difflib.get_close_matches(v, names, 1, 0.75)
        items = [{'id': s.s.eid(o), 'prop': n, 'dip': o.get('type') == 'DipRelInitialValue'} for o, n, _ in refs]
        choices = []
        if near:
            choices.append({'value': near[0], 'label': 'Cambiar a %s en todas (%d)' % (near[0], len(items))})
        if any(i['dip'] for i in items):
            choices.append({'delete': True, 'label': 'Borrar sus relaciones diplomáticas (%d)' % sum(i['dip'] for i in items)})
        files = sorted({f for _, _, f in refs})
        out.append({'level': 'error' if near else 'warning', 'id': items[0]['id'],
                    'msg': '«%s» aparece %d vez/veces (%s%s) pero esa nación no existe en el escenario%s.' % (
                        v, len(items), ', '.join(files[:4]), '…' if len(files) > 4 else '',
                        ' — ¿error de escritura de %s?' % near[0] if near else ''),
                    'fix': {'kind': 'nation', 'items': items, 'choices': choices} if choices else None})
    return out


def _fmt_avg(x, y):
    a, b = _num(x), _num(y)
    if a is None or b is None:
        return '?'
    r = (a + b) / 2
    return str(int(round(r))) if abs(r - round(r)) < 1e-9 or True else str(r)


def fix_diplomacy(s, items):
    """items: [{'a','b','use': 'a'|'b'|'avg'}]. Makes both directions have the same figure (creates the missing one)."""
    st = s.s
    m = _dip_map(s)
    notes = []
    for it in items:
        a, b, use = it['a'], it['b'], it.get('use', 'a')
        ea, eb = m.get((a, b)), m.get((b, a))
        va, vb = (ea[1] if ea else None), (eb[1] if eb else None)
        if it.get('value') is not None:                    # figure chosen by hand (0 terrible - 1000 excellent)
            sv = str(it['value']).strip()
            if not re.fullmatch(r'\d+', sv) or not (sc.DIP_MIN <= int(sv) <= sc.DIP_MAX):
                raise ValueError('la relación diplomática va de %d (pésimas) a %d (excelentes): «%s» no vale' % (sc.DIP_MIN, sc.DIP_MAX, it['value']))
            val = str(int(sv))
        elif use == 'b' and vb is not None:
            val = vb
        elif use == 'avg' and _num(va) is not None and _num(vb) is not None:
            val = _fmt_avg(va, vb)
        elif use in ('max', 'min') and _num(va) is not None and _num(vb) is not None:
            val = (max if use == 'max' else min)((va, vb), key=_num)
        else:
            val = va if va is not None else vb
        for (x, y, e) in ((a, b, ea), (b, a, eb)):
            if e is not None:
                if e[1] != val:
                    st.set_prop(e[0], 'nValue', str(val))
            else:           # that direction is missing: added to player x
                pd = next((p for p in s.all('MEPlayerData') if prop(p, 'strOwner') == x), None)
                if pd is None:
                    notes.append('AVISO: %s no tiene datos de jugador donde guardar su relación con %s' % (x, y))
                    continue
                el = ET.Element('object', {'type': 'DipRelInitialValue', 'name': 'objDipRelInitialValues'})
                ET.SubElement(el, 'property', {'name': 'strTargetCountry', 'value': y})
                ET.SubElement(el, 'property', {'name': 'nValue', 'value': str(val)})
                # inside its DipRelInitialValueList: loose in MEPlayerData the game does not load player*.xml («Error creating game»)
                lst = next((o for o in objs(pd) if o.get('type') == 'DipRelInitialValueList'), None)
                if lst is None:
                    lst = ET.Element('object', {'type': 'DipRelInitialValueList', 'name': 'objDipRelInitialValueList'})
                    ET.SubElement(lst, 'property', {'name': 'nDefault', 'value': '500'})
                    st.attach(lst, pd)
                st.attach(el, lst)
        notes.append('%s ↔ %s: relación %s' % (a, b, val))
    return notes



# ------------------------------------------------------------------ desired territories (player region lists)
def _player_data(s, country):
    return next((p for p in s.all('MEPlayerData') if prop(p, 'strOwner') == country), None)


def _region_lists(pd):
    """[(NamedParameterBlock, RegionListParameter)] of BasicRegionLists in the player data."""
    out = []
    for blk in objs(pd):
        if blk.get('type') == 'NamedParameterBlock' and prop(blk, 'strName') == 'BasicRegionLists':
            out += [(blk, rl) for rl in objs(blk) if rl.get('type') == 'RegionListParameter']
    return out


def claims(s, country):
    """Player region lists: «Historic» are the desired territories (those the AI wants to recover); the others are
    named lists used by events and the AI (e.g. GermanyDesiredUSSR1940)."""
    pd = _player_data(s, country)
    if pd is None:
        return {'player': False, 'lists': []}
    lists = []
    for _blk, rl in _region_lists(pd):
        lists.append({'name': prop(rl, 'strName'), 'regions': [p.get('value') for p in rl if p.tag == 'property' and p.get('name') == 'strRegions']})
    lists.sort(key=lambda x: (x['name'] != 'Historic', x['name']))
    return {'player': True, 'lists': lists}


def set_claims(s, country, listname, regions):
    """Sets the player list «listname» to exactly these regions (creates it, and the BasicRegionLists block, if needed)."""
    st = s.s
    pd = _player_data(s, country)
    if pd is None:
        raise ValueError('%s no tiene datos de jugador (player%s.xml)' % (country, country))
    known = {prop(r, 'strName') for r in s.regions()}
    bad = [r for r in regions if r not in known]
    if bad:
        raise ValueError('regiones desconocidas: %s' % ', '.join(bad))
    listname = (listname or 'Historic').strip()
    regions = list(dict.fromkeys(regions))
    blk = next((b for b, _rl in _region_lists(pd)), None) or next(
        (b for b in objs(pd) if b.get('type') == 'NamedParameterBlock' and prop(b, 'strName') == 'BasicRegionLists'), None)
    if blk is None:
        blk = ET.Element('object', {'type': 'NamedParameterBlock', 'name': 'objParameterBlocks'})
        ET.SubElement(blk, 'property', {'name': 'strName', 'value': 'BasicRegionLists'})
        st.attach(blk, pd)
    rl = next((x for b, x in _region_lists(pd) if prop(x, 'strName') == listname), None)
    if rl is None:
        rl = ET.Element('object', {'type': 'RegionListParameter', 'name': 'objRegionLists'})
        ET.SubElement(rl, 'property', {'name': 'strName', 'value': listname})
        st.attach(rl, blk)
    for p_ in [p_ for p_ in rl if p_.tag == 'property' and p_.get('name') == 'strRegions']:
        rl.remove(p_)
        st.parent.pop(p_, None)
    for r in regions:
        el = ET.SubElement(rl, 'property', {'name': 'strRegions', 'value': r})
        st.parent[el] = rl
        st.doc_of[el] = st.doc_of[rl]
    st.touch(rl, structural=True)
    return ['%s · %s: %d territorio(s) anhelado(s)' % (country, listname, len(regions))]



AI_TRAITS = ('nInternationalInvolvement', 'nAggressiveNature', 'nMilitaryPosture', 'nMilitaryDoctrine', 'nDomesticPolicy',
             'nSciencePolicy', 'nPoliticalStability')


def ai_traits(s, country):
    pd = _player_data(s, country)
    if pd is None:
        return {'player': False}
    return {'player': True, 'id': s.s.eid(pd), 'traits': {k: prop(pd, k) for k in AI_TRAITS}}


# ---------------------------------------------------------------------------------------- rename a country
# properties whose value is the internal name of a country (in any object); strName only in objects that are the country
COUNTRY_PROPS = {'strOwner', 'strController', 'strTargetCountry', 'strHomelands', 'strFoggees', 'strINITCountryName', 'strFromCountry',
                 'strToCountry', 'strCountry', 'strCountryName', 'strTargetCountries', 'strINITAttackerCountryName', 'strINITDefenderCountryName',
                 'strWinningCountryName', 'strLosingCountryName', 'strWarTriggerCountriesA', 'strWarTriggerCountriesB', 'strWarTriggerCountryA',
                 'strWarTriggerCountryB', 'strOtherCountry', 'strInCountry', 'strPlayer', 'strAliases', 'strController'}
COUNTRY_NAME_TYPES = {'MECountry', 'Player', 'PlayerGenNames', 'TriggerCountry', 'MEPlayerData'}
SID_KINDS = ('Name', 'Possessive', 'Adjective', 'People', 'Alliance')


def _slug(text):
    return re.sub(r'[^A-Za-z0-9]', '', text or '')


def rename_country(s, old, new, code=True, keep_shown=False):
    """Renames a country. code=False: only the name shown in the game (its SID text).
    code=True: also the internal name throughout the scenario (owners, diplomacy, AI, events, alliances, wars, treaties,
    unit models...), its country/player<País>.xml files (renamed on save) and its name SIDs.
    keep_shown=True: the name shown in the game does not change (e.g. «Myanmar» with internal name «Burma» as in vanilla)."""
    st = s.s
    new = (new or '').strip()
    countries = s.countries()
    if old not in countries:
        raise ValueError('no existe el país «%s»' % old)
    if not new:
        raise ValueError('escribe el nombre nuevo')
    notes = []
    c = countries[old]
    pl = next((p for p in s.all('Player', lambda f: f == 'gamestate.xml') if prop(p, 'strName') == old), None)
    sid_old = prop(c, 'sidName') or (prop(pl, 'sidName') if pl is not None else None) or 'SID.Game.Country.Name.' + _slug(old)
    if not code:
        notes += sc.set_region_string(s, sid_old, new)
        return ['%s se verá en el juego como «%s» (el nombre interno sigue siendo %s)' % (old, new, old)] + notes
    if new in countries:
        raise ValueError('ya existe un país «%s»' % new)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .'\-]*", new):
        raise ValueError('nombre interno: letras, números, espacios, puntos, apóstrofos o guiones')
    ext = set(getattr(s, 'external', []))
    n, outside = 0, 0
    q_old = "'%s'" % old
    for p in s.paths:
        for par in st.docs[p].getroot().iter('object'):
            t = par.get('type')
            sp_name = prop(par, 'strName') if t == 'StringParameter' else None
            for e in par:
                if e.tag != 'property':
                    continue
                k, v = e.get('name'), e.get('value')
                hit = (v == old and (k in COUNTRY_PROPS or (k == 'strName' and t in COUNTRY_NAME_TYPES)
                                     or (k == 'strKey' and t == 'MKDNode') or (k == 'strString' and t == 'WrappedString')
                                     or (k == 'strValue' and sp_name in ('CountryAName', 'CountryBName', 'TargetCountryNames'))))
                expr = k in ('expRession', 'expWhere') and v and q_old in v
                if not (hit or expr):
                    continue
                if p in ext:          # shared ScenarioDefaults data: not touched (used by other scenarios)
                    outside += 1
                    continue
                e.set('value', new if hit else v.replace(q_old, "'%s'" % new))
                st.touch(par)
                n += 1
    notes.append('%s → %s: %d referencias cambiadas' % (old, new, n))
    if outside:
        notes.append('AVISO: %d referencias a %s en archivos compartidos de ScenarioDefaults no se cambian (los usan otros escenarios)' % (outside, old))
    # country/player<País>.xml files: renamed (on save the new one is written and the old one deleted) and game.xml loads them
    st.renamed = getattr(st, 'renamed', {})
    for pre in ('country', 'player'):
        op = os.path.abspath(os.path.join(s.dir, '%s%s.xml' % (pre, old)))
        np_ = os.path.abspath(os.path.join(s.dir, '%s%s.xml' % (pre, new)))
        if op in st.docs and op in s.paths:
            _rekey(st, op, np_)
            st.dirty.add(np_)
            st.restructured.add(np_)
            st.renamed[np_] = st.renamed.pop(op, op)
            s.paths = [np_ if x == op else x for x in s.paths]
            for g in s.all('GO'):
                if g.get('fromFile') == '%s%s.xml' % (pre, old):
                    g.set('fromFile', '%s%s.xml' % (pre, new))
                    st.touch(g)
            notes.append('%s%s.xml → %s%s.xml (al guardar)' % (pre, old, pre, new))
    # name SID: the new ones with the text of the old ones (the name becomes the new one)
    for kind in SID_KINDS:
        so, sn = 'SID.Game.Country.%s.%s' % (kind, _slug(old)), 'SID.Game.Country.%s.%s' % (kind, _slug(new))
        txt = s.strings.get(so)
        if txt is None:
            try:
                import scenario_events
                txt = scenario_events._string(s, so)
            except Exception:
                txt = None
        if keep_shown:     # the new SIDs with the same text that was shown
            if txt or kind == 'Name':
                notes += sc.set_region_string(s, sn, txt or old)
            continue
        if txt:            # «Chile's» → «Chilean Republic's»; «Chilean» se queda (no es la palabra entera)
            txt = re.sub(r'(?<![A-Za-z])%s(?![A-Za-z])' % re.escape(old), new, txt)
        notes += sc.set_region_string(s, sn, new if kind == 'Name' or not txt else txt)
    for el in (c, pl):
        if el is not None and prop(el, 'sidName'):
            st.set_prop(el, 'sidName', 'SID.Game.Country.Name.' + _slug(new))
    s._opts = None
    return notes
