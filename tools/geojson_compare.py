"""Datos derivados para el GeoJSON del editor de regiones: comparación del mapa con el regionpack World, naciones por región,
fronteras y análisis de contornos que se van a importar.

El changelog del regionpack puede estar en español (regiones_nuevas…) o en inglés (new_regions…): se leen las dos formas.
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

MIN_PCT = 0.01        # fracciones del área por debajo de esto no se citan
PART_PCT = 0.05       # una parte cuenta como «trozo» de una división / fusión a partir de este porcentaje

# clave española -> inglesa (el JSON sale en el idioma del editor; el changelog se lee en cualquiera de los dos)
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
    """Una entrada de changelog con las claves en español, venga como venga (español o inglés), también las de dentro."""
    inv = {en: es for es, ens in ALIASES.items() for en in ens}

    def conv(x):
        if isinstance(x, dict):
            return {inv.get(k, k): conv(v) for k, v in x.items()}
        if isinstance(x, list):
            return [conv(v) for v in x]
        return x
    return conv(e)


def _geoms(m, renames):
    """{nombre: (poligono, es_mar)} del mapa m (contorno principal de cada región)."""
    out = {}
    for g in m['regions']:
        main, _ = outlines.region_polygons(m, g.index)
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
    """{a: {b: área común}} entre dos diccionarios de {nombre: (poligono, mar)} (solo se comparan regiones del mismo tipo)."""
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
    """Regiones del mapa abierto frente al regionpack base: nuevas (de qué regiones de la base salen y con qué % del área),
    eliminadas (a dónde fue su área), divididas, fusionadas y modificadas."""
    bdir = os.path.join(editor_core.MAPS, base)
    bm = mhmap.load_map(os.path.join(bdir, 'xml'))
    B = _geoms(bm, editor_core.load_renames(bdir))
    with project.lock:
        C = _geoms(project.m, project.renames)
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
    # divisiones: región de la base cuya área se reparte entre varias regiones actuales (cuenta la propia si sigue existiendo)
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
    for it in modified:      # una existente que absorbió buena parte de otra
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
    """Por cada región: la nación que la posee, la que la controla y su población; y por nación sus regiones."""
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
    """Fronteras entre regiones vecinas: una línea por pareja (a, b); 'coast' si una es mar y la otra tierra."""
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


def analyze_shapes(project, shapes):
    """Para cada contorno a importar ({geometry, props}): si ya existe una región con ese nombre y cuánto se parece a ella
    (iou), y de qué regiones del mapa sale su área (porcentaje del contorno y de la región de origen)."""
    with project.lock:
        C = _geoms(project.m, project.renames)
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
        out.append({'name': name, 'exists': name in C, 'iou': iou, 'sources': src})
    return out
