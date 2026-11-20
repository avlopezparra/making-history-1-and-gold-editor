"""Builds the «WorldHOI4» regionpack: HOI4 states + strategic sea regions, in HOI4's own proportions, over HOI4's terrain map.

    python tools/hoi4_geojson.py "<path>/1936.svg"     # first: hoi4/hoi4_states.geojson
    python -u tools/hoi4_make_pack.py [--solo-changelog]

Same route as MH2World2 (mh2_make_world2 / mh2_world2_completo): new empty project (new_pack), background image imported with
terrain_image.import_image, then every GeoJSON outline saved as a new region through Project.save. It can be stopped and relaunched.
Changelog: each region gets «madre»/«equivale» against vanilla World, comparing areas after mapping the HOI4 frame back to
real lon/lat (hoi4_fit.json), so «Adecuar» / «Cambiar de regionpack» can adapt World scenarios.
Writes nothing to the game: install from the region editor or with Project.install.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import shapely
import editor_core, new_pack, terrain_image, mhmap, geojson_compare
import mh2_make_world2 as W
import mh2_world2_completo as WC
import hoi4_geojson as H

NAME = 'WorldHOI4'
W.NAME = NAME
W.FOLDER = os.path.join(W.ROOT, 'editor_proyecto_' + NAME)
W.SRC = os.path.join(H.OUT, 'hoi4_states.geojson')
BG = os.path.join(H.OUT, 'hoi4_terrain.jpg')          # the user's HOI4 terrain map (1483x539, same frame as the SVG)
WC.REPORT = os.path.join(H.OUT, NAME + '_herencia.json')
W.mh2_plan.pretty = lambda s: s                        # GeoJSON names are already readable ("West Papua")


def create():
    if os.path.exists(W.FOLDER):
        return
    world = os.path.join(editor_core.MAPS, 'World')
    err = new_pack.check_name(NAME, editor_core.MAPS, W.FOLDER)
    if err:
        raise SystemExit(err)
    new_pack.create_project(W.FOLDER, NAME, world)
    P = editor_core.Project(W.FOLDER, os.path.join(W.FOLDER, '_respaldo'), pack=NAME)
    from PIL import Image
    w, h = Image.open(BG).size
    tiles = terrain_image.import_image(P, open(BG, 'rb').read(), H.frame_bbox(w, h), log=lambda *x: None)
    print('background: %d tiles' % len(tiles), flush=True)


def real_geoms(P):
    """{name: (geometry in real lon/lat, is_sea)} of the project's regions (HOI4 frame -> SVG -> real)."""
    fitd = json.load(open(os.path.join(H.OUT, 'hoi4_fit.json')))
    C = geojson_compare._geoms(P.m, P.renames, P)
    def back(g):
        svg = shapely.transform(g, lambda c: np.column_stack([(c[:, 0] + 180) / H.K, (H.LAT_TOP - c[:, 1]) / H.K]))
        p = fitd['west'] if svg.centroid.x < fitd['split_x'] else fitd['east']
        return shapely.make_valid(H.to_lonlat(p, svg))
    return {n: (back(g), s) for n, (g, s) in C.items()}


def inheritance(P):
    """mh2_world2_completo.inheritance with the project geometry mapped back to real coordinates first."""
    orig = geojson_compare._geoms
    bdir = os.path.join(editor_core.MAPS, 'World')
    B = orig(mhmap.load_map(os.path.join(bdir, 'xml')), editor_core.load_renames(bdir))
    C = real_geoms(P)
    geojson_compare._geoms = lambda m, *a: C if a and a[-1] is P else B
    try:
        return WC.inheritance(P)
    finally:
        geojson_compare._geoms = orig


def write_projection():
    """proyeccion.json in the project: real lon/lat -> WorldHOI4 coordinates on a 1-degree grid (scenario_layers.Projection);
    «Adecuar» uses it to move World scenarios onto this map. Install copies it into the regionpack."""
    fitd = json.load(open(os.path.join(H.OUT, 'hoi4_fit.json')))
    lons, lats = np.arange(-180, 181, 1.0), np.arange(-90, 91, 1.0)
    X, Y = [], []
    for lat in lats:
        row = [H.real_to_svg(fitd, lon, lat) for lon in lons]
        X.append([round(-180 + x * H.K, 5) for x, _ in row])
        Y.append([round(H.LAT_TOP - y * H.K, 5) for _, y in row])
    json.dump({'from': 'real lon/lat (World and the packs drawn like it)', 'lon0': -180, 'lat0': -90, 'step': 1, 'x': X, 'y': Y},
              open(os.path.join(W.FOLDER, 'proyeccion.json'), 'w'))
    # (a thin-plate correction from same-name regions was tried: worse on held-out regions, 156-163 vs 185 of 274)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo-changelog', action='store_true')
    a = ap.parse_args()
    if not a.solo_changelog:
        create()
        WC.build()
    write_projection()
    P = editor_core.Project(W.FOLDER, os.path.join(W.FOLDER, '_respaldo'), pack=NAME)
    B, C, mother, mpct, heir, hpct, eq, madre = inheritance(P)
    path, extra = WC.write_changelog(P, C, eq, madre)
    feats = json.load(open(W.SRC, encoding='utf-8'))['features']
    have = {r.name for r in P.m['regions']}
    missing = [f['properties']['name'] for f in feats if W.new_region.internal_name(f['properties']['name']) not in have]
    json.dump({'regiones_en_el_mapa': len(P.m['regions']), 'contornos_del_geojson': len(feats), 'sin_poner': missing,
               'hoi4': {n: {'mar': C[n][1], 'madre_world': mother.get(n), 'pct_area_en_madre': mpct.get(n), 'equivale': eq.get(n)} for n in sorted(C)},
               'world': {v: {'mar': B[v][1], 'heredera': heir.get(v), 'pct_area_heredada': hpct.get(v)} for v in sorted(B)}},
              open(WC.REPORT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('listo: %d regiones de %d contornos | sin poner %d %s' % (len(P.m['regions']), len(feats), len(missing), missing[:10]))
    print('herencia: %d regiones sustituyen a regiones de World | changelog %s (+%d)' % (len(eq), path, extra))


if __name__ == '__main__':
    main()
