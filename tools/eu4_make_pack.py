"""Builds the «WorldEU4» regionpack: EU4 provinces (MapChart SVG warped into EU4's map frame) + EU4 sea areas and lakes.

    python -u tools/eu4_geojson.py "<path>/MapChart_Map.svg"     # first: <work>/eu4_states.geojson
    python -u tools/eu4_make_pack.py [--solo-changelog] [--solo-fondo]

Same route as WorldHOI4 (hoi4_make_pack): new empty project (new_pack), every GeoJSON outline saved as a new region through
Project.save (can be stopped and relaunched), then the background: EU4 summer colormap + heightmap relief + depth-tinted water,
with the coast drawn from the project's land regions (no double coast), imported with terrain_image.import_image; borders
redrawn and minimap made. Changelog: «madre»/«equivale» against vanilla World, comparing areas after mapping the EU4 frame back
to real lon/lat (inverse warp + eu4_fit.json); proyeccion.json lets «Adecuar» move World scenarios onto this map.
The project lives on D: (C: is nearly full). Writes nothing to the game: install from the region editor or with Project.install.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, scipy.ndimage as nd
import shapely
import editor_core, new_pack, terrain_image, mhmap, geojson_compare
import mh2_make_world2 as W
import mh2_world2_completo as WC
import hoi4_geojson as H
import eu4_geojson as E

NAME = 'WorldEU4'
WORK = 'D:/MHData/eu4_work'
EU4 = 'D:/SteamLibrary/steamapps/common/Europa Universalis IV'
W.NAME = NAME
W.FOLDER = 'D:/MHData/editor_proyecto_' + NAME
W.SRC = os.path.join(WORK, 'eu4_states.geojson')
WC.REPORT = os.path.join(WORK, NAME + '_herencia.json')
W.mh2_plan.pretty = lambda s: s
BBOX = (-180.0, E.LAT_TOP - E.PXH * E.K, 180.0, E.LAT_TOP)
UP = 2                                              # background = 2x EU4 px (11264x4096)


def project():
    return editor_core.Project(W.FOLDER, os.path.join(W.FOLDER, '_respaldo'), pack=NAME)


def create():
    if os.path.exists(W.FOLDER):
        return
    err = new_pack.check_name(NAME, editor_core.MAPS, W.FOLDER)
    if err:
        raise SystemExit(err)
    new_pack.create_project(W.FOLDER, NAME, os.path.join(editor_core.MAPS, 'World'))


def background(P):
    """EU4 colormap/heightmap background in row strips (bounded memory), coast = the project's land regions."""
    from PIL import Image, ImageDraw
    Image.MAX_IMAGE_PIXELS = None
    Wd, Hd = E.PXW * UP, E.PXH * UP
    k = Wd / 360.0
    D = E.eu4_data(EU4, WORK)
    sea = np.isin(D['lab'], list(D['sea'] | D['lakes']))
    tris = [t for r in P.m['regions'] if r.u_type != 0
            for s in mhmap.region_shapes(P.m, r.index) for t in s.triangles() if len(set(t)) == 3]
    tri_lat = np.array([[min(p[1] for p in t), max(p[1] for p in t)] for t in tris])
    m = EU4 + '/map/'
    cm = np.asarray(Image.open(m + 'terrain/colormap_summer.dds').convert('RGB')).astype(np.float32)
    hm = np.asarray(Image.open(m + 'heightmap.bmp')).astype(np.float32)
    sea2 = sea[::2, ::2]
    i = nd.distance_transform_edt(nd.binary_dilation(sea2, iterations=1), return_distances=False, return_indices=True)
    cm = cm[i[0], i[1]]                                                    # land colours spread over the sea
    cm = np.where(sea2[..., None], np.stack([nd.gaussian_filter(cm[..., c], 4) for c in range(3)], -1), cm)
    i = nd.distance_transform_edt(sea, return_distances=False, return_indices=True)
    hm_land = np.where(sea, np.maximum(hm[i[0], i[1]], 96), hm)            # no sea cliff inside the regions' land
    hm_land = np.where(sea, nd.gaussian_filter(hm_land, 3), hm_land)
    del i
    deep = np.array([22, 42, 82], np.float32); shallow = np.array([62, 112, 160], np.float32)
    L = np.array([-0.6, -0.6, 0.53]); L /= np.linalg.norm(L)
    flat = L[2]
    out = np.zeros((Hd, Wd, 3), np.uint8)
    STRIP, M = 512, 48

    def up(arr, scale, a, b):
        """Rows a..b of the output (UP x EU4 px) from arr (EU4 px / scale), bicubic."""
        f = scale * UP
        r0, r1 = max(0, a // f - 3), min(arr.shape[0], -(-b // f) + 3)
        img = Image.fromarray(np.clip(arr[r0:r1], 0, 255).astype(np.uint8))
        big = np.asarray(img.resize((Wd, (r1 - r0) * f), Image.BICUBIC)).astype(np.float32)
        return big[a - r0 * f: b - r0 * f]

    for y0 in range(0, Hd, STRIP):
        a, b = max(0, y0 - M), min(Hd, y0 + STRIP + M)
        lat_hi, lat_lo = E.LAT_TOP - a / k, E.LAT_TOP - b / k
        im = Image.new('L', (Wd * 2, (b - a) * 2), 0); dr = ImageDraw.Draw(im)       # coast, 2x supersampled
        for j in np.flatnonzero((tri_lat[:, 1] >= lat_lo) & (tri_lat[:, 0] <= lat_hi)):
            dr.polygon([((x + 180) * k * 2, ((E.LAT_TOP - y) * k - a) * 2) for x, y in tris[j]], fill=255)
        lm = np.asarray(im.resize((Wd, b - a), Image.BOX)).astype(np.float32) / 255
        del im
        land = up(cm, 2, a, b)
        hmu = nd.gaussian_filter(up(hm_land, 1, a, b), 2.6)
        gy, gx = np.gradient(hmu)
        nx, ny = -gx * 0.7, -gy * 0.7
        shade = (nx * L[0] + ny * L[1] + L[2]) / np.sqrt(nx * nx + ny * ny + 1)
        shade = 0.62 + 0.7 * (shade - flat)
        land = 255 * (land / 255) ** 0.8 * 1.18 * np.clip(shade / 0.62, 0.45, 1.6)[..., None]
        t = np.clip((nd.gaussian_filter(up(hm, 1, a, b), 3) - 40) / 55, 0, 1)[..., None] ** 1.5
        water = deep + (shallow - deep) * t
        din = nd.distance_transform_edt(lm > 0.5); dout = nd.distance_transform_edt(lm <= 0.5)
        land *= (1 - 0.15 * np.exp(-din / 2.0))[..., None]
        water = water * (1 + 0.15 * np.exp(-dout / 8.0))[..., None]
        px = land * lm[..., None] + water * (1 - lm[..., None])
        n = min(STRIP, Hd - y0)
        out[y0:y0 + n] = np.clip(px[y0 - a: y0 - a + n], 0, 255).astype(np.uint8)
        print('fondo: filas %d/%d' % (y0 + n, Hd), flush=True)
    img = Image.fromarray(out)
    path = os.path.join(WORK, 'bg_eu4.png')
    img.save(path, compress_level=3)
    img.resize((Wd // 8, Hd // 8), Image.LANCZOS).save(os.path.join(WORK, NAME + '_fondo_preview.png'))
    return path


def install_background(P):
    path = background(P)
    tiles = terrain_image.import_image(P, open(path, 'rb').read(), BBOX, log=lambda *x: None)
    print('fondo: %d tiles' % len(tiles), flush=True)
    P.redraw_borders(log=lambda *x: None)
    terrain_image.make_minimap(P)
    print('fondo: fronteras redibujadas y minimapa hecho', flush=True)


def to_real():
    """Pack degrees -> real lon/lat: EU4 px -> SVG (inverse warp) -> real (eu4_fit.json)."""
    from scipy.interpolate import RegularGridInterpolator
    inv = np.load(os.path.join(WORK, 'warp_inv.npy'))
    ax = (np.arange(inv.shape[0]) * 4.0, np.arange(inv.shape[1]) * 4.0)
    RX = RegularGridInterpolator(ax, inv[..., 0], bounds_error=False, fill_value=None)
    RY = RegularGridInterpolator(ax, inv[..., 1], bounds_error=False, fill_value=None)
    p = json.load(open(os.path.join(WORK, 'eu4_fit.json')))['p']
    def svg(c):
        yx = np.column_stack([(E.LAT_TOP - c[:, 1]) / E.K, (c[:, 0] + 180) / E.K])
        return np.column_stack([RX(yx), RY(yx)])
    return lambda g: shapely.make_valid(H.to_lonlat(p, shapely.transform(g, svg)))


def inheritance(P):
    orig = geojson_compare._geoms
    bdir = os.path.join(editor_core.MAPS, 'World')
    B = orig(mhmap.load_map(os.path.join(bdir, 'xml')), editor_core.load_renames(bdir))
    back = to_real()
    C = {n: (back(g), s) for n, (g, s) in orig(P.m, P.renames, P).items()}
    geojson_compare._geoms = lambda m, *a: C if a and a[-1] is P else B
    try:
        return WC.inheritance(P)
    finally:
        geojson_compare._geoms = orig


def write_projection():
    """proyeccion.json: real lon/lat -> WorldEU4 coordinates on a 1-degree grid (scenario_layers.Projection)."""
    a, b, c0, c1, c2, c3 = json.load(open(os.path.join(WORK, 'eu4_fit.json')))['p']
    f = E.grid_interp(np.load(os.path.join(WORK, 'warp_grid.npy')))
    LO, LA = np.meshgrid(np.arange(-180, 181, 1.0), np.arange(-90, 91, 1.0))
    svg = np.column_stack([((LO - b) / a).ravel(), (c0 + c1 * LA + c2 * LA ** 2 + c3 * LA ** 3).ravel()])
    d = E.px_to_deg(f(svg))
    json.dump({'from': 'real lon/lat (World and the packs drawn like it)', 'lon0': -180, 'lat0': -90, 'step': 1,
               'x': np.round(d[:, 0].reshape(LO.shape), 5).tolist(), 'y': np.round(d[:, 1].reshape(LO.shape), 5).tolist()},
              open(os.path.join(W.FOLDER, 'proyeccion.json'), 'w'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo-changelog', action='store_true')
    ap.add_argument('--solo-fondo', action='store_true')
    a = ap.parse_args()
    if not (a.solo_changelog or a.solo_fondo):
        create()
        WC.build()
    if not a.solo_changelog:
        install_background(project())
    if a.solo_fondo:
        return
    write_projection()
    P = project()
    B, C, mother, mpct, heir, hpct, eq, madre = inheritance(P)
    path, extra = WC.write_changelog(P, C, eq, madre)
    feats = json.load(open(W.SRC, encoding='utf-8'))['features']
    have = {r.name for r in P.m['regions']}
    missing = [f['properties']['name'] for f in feats if W.new_region.internal_name(f['properties']['name']) not in have]
    json.dump({'regiones_en_el_mapa': len(P.m['regions']), 'contornos_del_geojson': len(feats), 'sin_poner': missing,
               'eu4': {n: {'mar': C[n][1], 'madre_world': mother.get(n), 'pct_area_en_madre': mpct.get(n), 'equivale': eq.get(n)} for n in sorted(C)},
               'world': {v: {'mar': B[v][1], 'heredera': heir.get(v), 'pct_area_heredada': hpct.get(v)} for v in sorted(B)}},
              open(WC.REPORT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('listo: %d regiones de %d contornos | sin poner %d %s' % (len(P.m['regions']), len(feats), len(missing), missing[:10]))
    print('herencia: %d regiones sustituyen a regiones de World | changelog %s (+%d)' % (len(eq), path, extra))


if __name__ == '__main__':
    main()
