"""Complete «MH2World2» regionpack from mh2/mh2_mundo.geojson + inheritance changelog to adapt World scenarios.

    python -u mh2_world2_completo.py                 # builds whatever is missing (retries failures) and writes the changelog
    python -u mh2_world2_completo.py --solo-changelog   # does not build: only recomputes the inheritance and the changelog

1) Build: puts into the editor project (making-history/editor_proyecto_MH2World2) all the GeoJSON regions,
   land and sea, not yet present; those the editor rejected before are retried one by one (if it still fails,
   it is retried with a lightened outline). It can be stopped and relaunched: it continues where it left off.
2) Inheritance: compares by area each region of the new map with those of vanilla World (only land with land and sea with sea):
   - mother of an MH2 region = the World region where most of its area falls;
   - heir of a World region = the MH2 region that takes most of its area.
   In the project changelog, each new region gets «equivale» (the World regions it replaces: the editor makes it
   spring from the first and gives it cities, resources, units and population of all of them) and «madre» (whom it is split from when
   added if it replaces none). With that, the editor's «Cambiar de regionpack» adapts a World scenario to MH2World2.
   Regions with the same name in World and MH2 are kept as-is in the scenarios.
Changelog backup: changelog.antes_herencia.json (only the first time). Readable report: mh2/MH2World2_herencia.json.
Writes nothing to the game: the regionpack is installed from the editor («Regionpack» -> MH2World2 -> Instalar).
"""
import argparse, json, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import editor_core, mhmap, changelog_keys, geojson_compare
import mh2_make_world2 as W
from shapely.strtree import STRtree

REPORT = os.path.join(W.ROOT, 'mh2', W.NAME + '_herencia.json')


def build():
    """Build passes until nothing more fits (each pass retries the previous one's failures)."""
    resume = os.path.exists(W.FOLDER)
    prev = None
    for n in range(3):
        print('== construcción, pasada %d ==' % (n + 1), flush=True)
        failed = W.build(argparse.Namespace(resume=resume, retry=True, limit=0))
        resume = True
        if not failed or failed == prev:
            return failed
        prev = failed
    return failed


def heir_map(A, B):
    """{a: b} with b = the region of B sharing the most area with a (same type); without overlap, the closest of the same type."""
    ov = geojson_compare._overlaps(A, B)
    out, pct = {}, {}
    for kind in (False, True):
        names = [n for n, (_, s) in B.items() if s == kind]
        tree = STRtree([B[n][0] for n in names])
        for a, (pa, sa) in A.items():
            if sa != kind:
                continue
            row = ov.get(a) or {}
            if row:
                b = max(row, key=row.get)
                out[a], pct[a] = b, round(100 * row[b] / pa.area, 1) if pa.area else 0
            elif names:
                out[a], pct[a] = names[int(tree.nearest(pa))], 0.0
    return out, pct, ov


def inheritance(P):
    print('== herencia: comparando áreas con World vanilla ==', flush=True)
    bdir = os.path.join(editor_core.MAPS, 'World')
    B = geojson_compare._geoms(mhmap.load_map(os.path.join(bdir, 'xml')), editor_core.load_renames(bdir))
    C = geojson_compare._geoms(P.m, P.renames, P)
    mother, mpct, ov_cb = heir_map(C, B)        # MH2 region -> World region where most of its area falls
    heir, hpct, _ = heir_map(B, C)              # World region -> MH2 region that takes most of its area
    land_c = {n for n, (_, s) in C.items() if not s}
    # a World region whose name is still on the map (land) stays as-is in the scenarios: it is its own heir
    for v, (_, s) in B.items():
        if not s and v in land_c:
            heir[v] = v
    eq = {}
    for v, n in heir.items():
        if not B[v][1] and n != v:
            eq.setdefault(n, []).append(v)
    for n, vs in eq.items():
        vs.sort(key=lambda v: (v != mother.get(n), -(ov_cb.get(n) or {}).get(v, 0)))     # su madre primero (de ella nace)
    madre = {}
    for n in C:
        m = mother.get(n)
        if n in eq:
            madre[n] = eq[n][0]
        elif C[n][1] or m is None:
            madre[n] = m
        else:
            madre[n] = heir.get(m, m)       # the World one may have disappeared: split from whoever inherited it
    return B, C, mother, mpct, heir, hpct, eq, madre


def write_changelog(P, C, eq, madre):
    path = P.changelog_path()
    bak = os.path.join(os.path.dirname(path), 'changelog.antes_herencia.json')
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    cl = [e for e in P.changelog() if 'herencia_world' not in (e.get('operaciones') or [])]     # the one from a previous pass is redone
    seen = set()
    for e in cl:
        for x in e.get('regiones_nuevas', []):
            n = x.get('nombre')
            if n in C:
                x['equivale'] = eq.get(n) or None
                x['madre'] = madre.get(n)
                seen.add(n)
    # map regions the changelog has not recorded: added in a separate entry
    extra = [{'nombre': n, 'texto': n, 'madre': madre.get(n), 'pais': None, 'tipo': 0 if s else 1, 'controlador': None, 'terreno': None,
              'mar': s, 'poblacion': None, 'historicos': None, 'equivale': eq.get(n) or None} for n, (_, s) in C.items() if n not in seen]
    # an old «equivalencias» entry would override the computed one: it is emptied (it can later be edited by hand in the editor)
    for e in cl:
        if 'equivalencias' in e:
            e['equivalencias'] = {}
    cl.append({'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': P.pack, 'instalado': False, 'operaciones': ['herencia_world'],
               'origen': 'mh2_world2_completo', 'nota': 'madre/equivale calculados por área frente a World vanilla',
               'regiones_nuevas': extra})
    changelog_keys.dump(cl, path)
    return path, len(extra)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo-changelog', action='store_true')
    a = ap.parse_args()
    failed = [] if a.solo_changelog else build()
    P = editor_core.Project(W.FOLDER, os.path.join(W.FOLDER, '_respaldo'), pack=W.NAME)
    feats = json.load(open(W.SRC, encoding='utf-8'))['features']
    have = {r.name for r in P.m['regions']}
    missing = [f['properties']['name'] for f in feats if W.new_region.internal_name(W.mh2_plan.pretty(f['properties']['name'])) not in have]
    B, C, mother, mpct, heir, hpct, eq, madre = inheritance(P)
    path, extra = write_changelog(P, C, eq, madre)
    rep = {'regiones_en_el_mapa': len(P.m['regions']), 'contornos_del_geojson': len(feats), 'sin_poner': missing,
           'mh2': {n: {'mar': C[n][1], 'madre_world': mother.get(n), 'pct_area_en_madre': mpct.get(n), 'equivale': eq.get(n), 'madre_changelog': madre.get(n)}
                   for n in sorted(C)},
           'world': {v: {'mar': B[v][1], 'heredera': heir.get(v), 'pct_area_heredada': hpct.get(v)} for v in sorted(B)}}
    json.dump(rep, open(REPORT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    lost = sorted(v for v, (_, s) in B.items() if not s and hpct.get(v, 0) == 0 and heir.get(v) != v)
    print('listo: %d regiones en el mapa de %d contornos | sin poner: %d %s' % (len(P.m['regions']), len(feats), len(missing), missing[:10]))
    print('herencia: %d regiones MH2 sustituyen a regiones de World | %d de World conservan su nombre | %d de World sin solape (van a la más cercana): %s'
          % (len(eq), sum(1 for v, n in heir.items() if n == v), len(lost), lost[:10]))
    print('changelog: %s (%d regiones añadidas al registro)' % (path, extra))
    print('informe: %s' % REPORT)


if __name__ == '__main__':
    main()
