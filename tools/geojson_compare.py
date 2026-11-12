"""Derived data for the region editor's GeoJSON: comparison of the map with the World regionpack, nations per region,
borders and analysis of outlines about to be imported.

The regionpack changelog may be in Spanish (regiones_nuevas…) or English (new_regions…): both forms are read.
"""
import os

from shapely import make_valid
from shapely.geometry import shape, MultiPolygon
from shapely.strtree import STRtree

import editor_core
import mhmap
import outlines
from transfer import SEA
from scenario_core import prop

MIN_PCT = 0.01        # area fractions below this are not mentioned
PART_PCT = 0.05       # a part counts as a «piece» of a split / merge from this percentage on

# Spanish key -> English key (the JSON comes out in the editor language; the changelog is read in either)
ALIASES = {
    'regiones_nuevas': ['new_regions'], 'regiones_eliminadas': ['removed_regions', 'deleted_regions'], 'traspasos': ['transfers'],
    'vecindades_nuevas': ['new_neighbors', 'new_neighbours'], 'centros': ['centers'], 'renombradas': ['renamed', 'renamed_regions'],
    'operaciones': ['operations'], 'fecha': ['date'], 'nombre': ['name'], 'texto': ['text'], 'madre': ['mother', 'parent'],
    'pais': ['owner', 'country'], 'tipo': ['type'], 'controlador': ['controller'], 'terreno': ['terrain'], 'mar': ['sea'],
    'poblacion': ['population'], 'historicos': ['historic'], 'fraccion': ['fraction'], 'area': ['area'], 'madres': ['mothers'],
    'de': ['from'], 'a': ['to'], 'instalado': ['installed'], 'regionpack': ['regionpack'],
}
KEYS_EN = {
    'base': 'base', 'regionpack': 'regionpack', 'resumen': 'summary', 'regiones_nuevas': 'new_regions', 'regiones_eliminadas': 'removed_regions',
    'regiones_modificadas': 'modified_regions', 'regiones_divididas': 'split_regions', 'regiones_fusionadas': 'merged_regions',
    'sin_cambios': 'unchanged', 'nombre': 'name', 'tipo': 'kind', 'procede_de': 'comes_from', 'region': 'region', 'porcentaje_del_area': 'percent_of_area',
    'area_grados2': 'area_deg2', 'repartida_en': 'now_in', 'partes': 'parts', 'pierde_area_hacia': 'loses_area_to', 'gana_area_desde': 'gains_area_from',
    'registrado_en_changelog': 'in_changelog', 'madre': 'mother', 'pais': 'owner', 'fecha': 'date', 'tierra': 'land', 'mar': 'sea',
    'nueva': 'new', 'eliminada': 'removed', 'modificada': 'modified', 'dividida': 'split', 'fusion': 'merge', 'mezcla': 'mixed',
    'estado': 'status', 'porcentaje_conservado': 'percent_kept', 'entradas_changelog': 'changelog_entries',
    'regiones': 'regions', 'naciones': 'nations', 'escenario': 'scenario', 'propietario': 'owner', 'controlador': 'controller',
    'poblacion': 'population', 'poblacion_total': 'total_population', 'controladas': 'controlled',
    'regiones_propias': 'own_regions', 'regiones_controladas': 'controlled_regions',
}


def tr_keys(x, lang):
    if lang != 'en':
        return x
    if isinstance(x, dict):
        return {KEYS_EN.get(k, k): tr_keys(v, lang) for k, v in x.items()}
    if isinstance(x, list):
        return [tr_keys(v, lang) for v in x]
    if isinstance(x, str):
        return KEYS_EN.get(x, x) if x in ('tierra', 'mar', 'nueva', 'eliminada', 'modificada', 'dividida', 'fusion', 'mezcla') else x
    return x


def norm_entry(e):
    """A changelog entry with Spanish keys, whatever it comes in (Spanish or English), nested ones too."""
    inv = {en: es for es, ens in ALIASES.items() for en in ens}

    def conv(x):
        if isinstance(x, dict):
            return {inv.get(k, k): conv(v) for k, v in x.items()}
        if isinstance(x, list):
            return [conv(v) for v in x]
        return x
    return conv(e)


def _project_geoms(project):
    """{name: (polygon, is_sea)} of the project, with outlines cached (cleared on map reload)."""
    with project.lock:
        c = project.outline_cache.get('_geoms')
        if c is None:
            c = project.outline_cache['_geoms'] = _geoms(project.m, project.renames, project)
        return c


def _geoms(m, renames, project=None):
    """{name: (polygon, is_sea)} of map m (main outline of each region)."""
    out = {}
    for g in m['regions']:
        main, _ = project.outline(g.index)[:2] if project is not None else outlines.region_polygons(m, g.index)
        if not main:
            continue
        try:
            poly = make_valid(shape({'type': 'MultiPolygon', 'coordinates': main}))
        except Exception:
            continue
        if poly.is_empty:
            continue
        out[renames.get(g.name, g.name)] = (poly, g.u_type == SEA)
    return out


def _overlaps(A, B):
    """{a: {b: common area}} between two dicts of {name: (polygon, sea)} (only regions of the same type are compared)."""
    names = list(B)
    tree = STRtree([B[n][0] for n in names])
    out = {}
    for a, (pa, sa) in A.items():
        row = {}
        for i in tree.query(pa):
            b = names[int(i)]
            pb, sb = B[b]
            if sa != sb:
                continue
            try:
                ar = pa.intersection(pb).area
            except Exception:
                ar = 0.0
            if ar > 1e-9:
                row[b] = ar
        out[a] = row
    return out


def compare_with_base(project, base='World', lang='es'):
    """Regions of the open map against the base regionpack: new (which base regions they come from and with what % of area),
    deleted (where their area went), split, merged and modified."""
    bdir = os.path.join(editor_core.MAPS, base)
    bm = mhmap.load_map(os.path.join(bdir, 'xml'))
    B = _geoms(bm, editor_core.load_renames(bdir))
    C = _project_geoms(project)
    ov_cb = _overlaps(C, B)            # {actual: {base: area}}
    ov_bc = {}
    for c, row in ov_cb.items():
        for b, ar in row.items():
            ov_bc.setdefault(b, {})[c] = ar
    logged = {}
    for e in project.changelog():
        e = norm_entry(e)
        for x in e.get('regiones_nuevas', []):
            logged[x.get('nombre')] = {'madre': x.get('madre'), 'pais': x.get('pais'), 'fecha': e.get('fecha')}

    def pct_list(row, total, skip=None):
        xs = [{'region': n, 'porcentaje_del_area': round(100 * ar / total, 2)} for n, ar in row.items() if n != skip and total and ar / total >= MIN_PCT]
        return sorted(xs, key=lambda d: -d['porcentaje_del_area'])

    new, modified, unchanged = [], [], []
    for c, (pc, sea) in C.items():
        row, total = ov_cb.get(c, {}), pc.area
        kind = 'mar' if sea else 'tierra'
        if c in B:
            same = row.get(c, 0.0)
            keep = same / total if total else 0
            keep_b = same / B[c][0].area if B[c][0].area else 0
            if keep >= 0.98 and keep_b >= 0.98:
                unchanged.append(c)
                continue
            modified.append({'nombre': c, 'tipo': kind, 'porcentaje_conservado': round(100 * keep_b, 2),
                             'gana_area_desde': pct_list(row, total, skip=c),
                             'pierde_area_hacia': [x for x in pct_list(ov_bc.get(c, {}), B[c][0].area, skip=c)]})
            continue
        src = pct_list(row, total)
        big = [s for s in src if s['porcentaje_del_area'] >= 100 * PART_PCT]
        item = {'nombre': c, 'tipo': kind, 'estado': 'mezcla' if len(big) > 1 else 'nueva', 'area_grados2': round(total, 6), 'procede_de': src}
        if c in logged:
            item['registrado_en_changelog'] = logged[c]
        new.append(item)
    removed = []
    for b, (pb, sea) in B.items():
        if b in C:
            continue
        dest = pct_list(ov_bc.get(b, {}), pb.area)
        removed.append({'nombre': b, 'tipo': 'mar' if sea else 'tierra', 'repartida_en': dest})
    # splits: base region whose area is spread among several current regions (its own counts if it still exists)
    splits = []
    for b, row in ov_bc.items():
        parts = [d for d in pct_list(row, B[b][0].area) if d['porcentaje_del_area'] >= 100 * PART_PCT]
        if len(parts) > 1:
            splits.append({'nombre': b, 'tipo': 'mar' if B[b][1] else 'tierra', 'partes': parts})
    merges = []
    for it in new:
        big = [s for s in it['procede_de'] if s['porcentaje_del_area'] >= 100 * PART_PCT]
        if len(big) > 1:
            merges.append({'nombre': it['nombre'], 'partes': big})
    for it in modified:      # an existing one that absorbed a good part of another
        big = [s for s in it['gana_area_desde'] if s['porcentaje_del_area'] >= 100 * PART_PCT]
        if big:
            merges.append({'nombre': it['nombre'], 'partes': big})
    stale = sorted(n for n in logged if n not in C)
    out = {'base': base, 'regionpack': project.pack,
           'resumen': {'regiones_nuevas': len(new), 'regiones_eliminadas': len(removed), 'regiones_modificadas': len(modified),
                       'regiones_divididas': len(splits), 'regiones_fusionadas': len(merges), 'sin_cambios': len(unchanged)},
           'regiones_nuevas': sorted(new, key=lambda d: d['nombre']), 'regiones_eliminadas': sorted(removed, key=lambda d: d['nombre']),
           'regiones_divididas': sorted(splits, key=lambda d: d['nombre']), 'regiones_fusionadas': sorted(merges, key=lambda d: d['nombre']),
           'regiones_modificadas': sorted(modified, key=lambda d: d['nombre'])}
    if stale:
        out['entradas_changelog'] = {'sin_region_en_el_mapa': stale}
    return tr_keys(out, lang)


def nations(s, project, scen_name, lang='es'):
    """For each region: the nation that owns it, the one that controls it and its population; and per nation its regions."""
    P = prop
    regs, by_nation = {}, {}
    data = {P(r, 'strName'): r for r in s.regions()}
    for g in project.m['regions']:
        n = project.rname(g.index)
        r = data.get(n)
        if r is None:
            regs[n] = {'tipo': 'mar' if g.u_type == SEA else 'tierra', 'propietario': None, 'controlador': None, 'poblacion': None}
            continue
        pop = P(r, 'nPopulation')
        pop = int(pop) if pop and str(pop).isdigit() else None
        o, c = P(r, 'strOwner'), P(r, 'strController')
        regs[n] = {'tipo': 'mar' if g.u_type == SEA else 'tierra', 'propietario': o, 'controlador': c, 'poblacion': pop}
        if o:
            d = by_nation.setdefault(o, {'regiones_propias': [], 'regiones_controladas': [], 'poblacion_total': 0})
            d['regiones_propias'].append(n)
            d['poblacion_total'] += pop or 0
        if c and c != o:
            by_nation.setdefault(c, {'regiones_propias': [], 'regiones_controladas': [], 'poblacion_total': 0})['regiones_controladas'].append(n)
    out = {'escenario': scen_name, 'regiones': regs, 'naciones': dict(sorted(by_nation.items()))}
    return tr_keys(out, lang)


def borders(project):
    """Borders between neighboring regions: one line per pair (a, b); 'coast' if one is sea and the other land."""
    polys = {}
    for g in project.m['regions']:
        main, _ = project.outline(g.index)[:2]
        if main:
            try:
                polys[g.index] = shape({'type': 'MultiPolygon', 'coordinates': main}).buffer(0)
            except Exception:
                pass
    feats, seen = [], set()
    for g in project.m['regions']:
        for n in g.neighbors:
            key = tuple(sorted((g.index, n)))
            if n == g.index or key in seen or g.index not in polys or n not in polys:
                continue
            seen.add(key)
            try:
                line = polys[g.index].boundary.intersection(polys[n].boundary)
            except Exception:
                continue
            if line.is_empty or line.length <= 0:
                continue
            lines = [x for x in getattr(line, 'geoms', [line]) if x.geom_type in ('LineString', 'MultiLineString')]
            if not lines:
                continue
            a, b = project.m['regions'][key[0]], project.m['regions'][key[1]]
            kind = 'coast' if (a.u_type == SEA) != (b.u_type == SEA) else 'sea' if a.u_type == SEA else 'land'
            from shapely.geometry import mapping
            from shapely.ops import linemerge
            geom = linemerge(lines) if len(lines) > 1 else lines[0]
            feats.append({'type': 'Feature', 'geometry': mapping(geom),
                          'properties': {'mh_type': 'border', 'a': project.rname(key[0]), 'b': project.rname(key[1]), 'kind': kind}})
    return {'type': 'FeatureCollection', 'features': feats}


def _project_centers(project):
    """{name: (lon, lat, is_sea)}: center of each map region, cached per map (cleared on reload)."""
    C = _project_geoms(project)
    with project.lock:
        c = project.outline_cache.get('_centers')
        if c is None:
            c = project.outline_cache['_centers'] = {n: (g.centroid.x, g.centroid.y, sea) for n, (g, sea) in C.items()}
        return c


def _km(a, b):
    """Distancia aproximada en km entre dos puntos (lon, lat)."""
    import math
    dx = (a[0] - b[0]) * math.cos(math.radians((a[1] + b[1]) / 2))
    return round(math.hypot(dx, a[1] - b[1]) * 111.2, 1)


def nearest_center(project, poly, sea=None):
    """Map region whose center is closest to the center of 'poly' (same type if 'sea' is given): {region, km, sea}."""
    P = _project_centers(project)
    c = poly.centroid
    best = min(((n, v) for n, v in P.items() if sea is None or v[2] == sea), key=lambda nv: _km((c.x, c.y), nv[1][:2]), default=None)
    return {'region': best[0], 'km': _km((c.x, c.y), best[1][:2]), 'sea': best[1][2]} if best else None


def analyze_shapes(project, shapes):
    """For each outline to import ({geometry, props}): whether a region with that name already exists and how similar it is
    (iou), which map regions its area comes from (percentage of the outline and of the source region) and the map region with
    the closest center ('nearest': {region, km, sea, pct_source})."""
    C = _project_geoms(project)
    names = list(C)
    tree = STRtree([C[n][0] for n in names])
    out = []
    for sh in shapes:
        try:
            poly = make_valid(shape(sh['geometry']))
        except Exception:
            out.append({'error': True})
            continue
        name = ((sh.get('props') or {}).get('name') or (sh.get('props') or {}).get('strName') or '').strip()
        src = []
        for i in tree.query(poly):
            n = names[int(i)]
            ar = poly.intersection(C[n][0]).area
            if ar > 1e-9:
                src.append({'region': n, 'sea': C[n][1], 'pct_new': round(ar / poly.area, 4) if poly.area else 0,
                            'pct_source': round(ar / C[n][0].area, 4) if C[n][0].area else 0})
        src.sort(key=lambda d: -d['pct_new'])
        iou = None
        if name in C:
            u = poly.union(C[name][0]).area
            iou = round(poly.intersection(C[name][0]).area / u, 4) if u else 0
        # the most similar map region: the closest center (of the same type as the one giving most area); «Mauritius 2» -> Mauritius
        near = nearest_center(project, poly, src[0]['sea'] if src else None)
        if near:
            near['pct_source'] = next((x['pct_source'] for x in src if x['region'] == near['region']), 0)
        out.append({'name': name, 'exists': name in C, 'iou': iou, 'sources': src, 'nearest': near})
    return out


SLIVER_AREA = 1e-8     # degrees²: what the save ignores (editor_core: crumbs); a smaller exclave would never be transferred
SLIVER_THIN = 0.01     # area / perimeter²: below this it is a strip (the drawn edge grazing the border), not an exclave


def exclaves(project, polygon, max_pct=0.05, sources=None):
    """Loose pieces (exclaves) a new outline would cut off in the land regions it really comes from
    ('sources': names; None = all it touches): parts of a region left separated from its main body and smaller
    than max_pct of it. Slivers (smaller than what the save transfers, or thin strips left by an edge drawn over the
    border) are not asked about: they go in 'cleaned' (the outline with them inside), so no loose crumbs remain.
    For each exclave: the neighbor it shares the most border with (best) and how much it shares with the new outline (touch_new).
    'merged' is the outline with the slivers and all exclaves included."""
    from shapely.geometry import mapping
    from shapely.ops import unary_union
    C = _project_geoms(project)
    names = list(C)
    tree = STRtree([C[n][0] for n in names])
    poly = make_valid(shape(polygon))
    only = set(sources) if sources is not None else None
    eps = 1e-6
    items, slivers = [], []
    for i in tree.query(poly):
        r = names[int(i)]
        gr, sea = C[r]
        if sea or (only is not None and r not in only) or not gr.intersects(poly):
            continue
        rem = gr.difference(poly)
        parts = sorted([p for p in getattr(rem, 'geoms', [rem]) if p.geom_type == 'Polygon' and p.area > 1e-12], key=lambda p: -p.area)
        if len(parts) < 2:
            continue
        orig = [p for p in getattr(gr, 'geoms', [gr]) if p.geom_type == 'Polygon']
        for q in parts[1:]:
            if q.area > max_pct * gr.area:
                continue
            if any(abs(q.area - o.area) <= 1e-6 * o.area and q.intersects(o) for o in orig):
                continue          # it was already a separate part (island, deliberate enclave): not produced by this cut
            if q.area < SLIVER_AREA or q.area / max(q.length ** 2, 1e-30) < SLIVER_THIN:
                slivers.append(q)
                continue
            ring = q.buffer(eps)
            best, bl = None, 0.0
            for j in tree.query(ring):
                n = names[int(j)]
                if n == r or C[n][1]:
                    continue
                ln = q.boundary.intersection(C[n][0].buffer(eps)).length
                if ln > bl:
                    best, bl = n, ln
            items.append({'region': r, 'area': round(q.area, 6), 'polygon': mapping(q), 'best': best, 'best_len': round(bl, 6),
                          'touch_new': round(q.boundary.intersection(poly.buffer(eps)).length, 6)})
    cleaned = unary_union([poly] + slivers).buffer(0) if slivers else poly
    merged = unary_union([cleaned] + [shape(x['polygon']) for x in items]).buffer(0) if items else cleaned
    by_name = {project.rname(g.index): g.index for g in project.m['regions']}
    for x in items:
        x['best_index'] = by_name.get(x['best'])
    return {'items': items, 'merged': mapping(merged), 'cleaned': mapping(cleaned), 'slivers': len(slivers)}
