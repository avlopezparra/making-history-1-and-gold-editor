"""HOI4 states (MapChart SVG) -> GeoJSON in MH1 lon/lat, ready for hoi4_make_pack.py.

    python hoi4_geojson.py "<path>/1936.svg"

The MapChart HOI4 map is drawn in HOI4's own projection, so the SVG -> lon/lat transform is fitted against
vanilla World's land (lon = a*x + b, y = cubic(lat)), maximizing land overlap on a 0.5 degree grid.
Output (hoi4/): hoi4_states.geojson (land_region, one per state id), hoi4_fit.json (transform + overlap score).
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union
import shapely

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'hoi4')
TOK = re.compile(r'[A-Za-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
NARGS = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4, 'Q': 4, 'T': 2, 'A': 7, 'Z': 0}


def _bez(pts, steps):
    for k in range(1, steps + 1):
        t = k / steps
        if len(pts) == 3:
            (x0, y0), (x1, y1), (x2, y2) = pts
            yield ((1-t)**2*x0 + 2*(1-t)*t*x1 + t*t*x2, (1-t)**2*y0 + 2*(1-t)*t*y1 + t*t*y2)
        else:
            (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pts
            a, b, c, e = (1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3
            yield (a*x0 + b*x1 + c*x2 + e*x3, a*y0 + b*y1 + c*y2 + e*y3)


def _split_arc_flags(args):
    """Arc argument text -> same numbers, with the two flags of each 7-tuple as separate tokens."""
    out, pos, k = [], 0, 0
    num = re.compile(r'[\s,]*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)')
    flag = re.compile(r'[\s,]*([01])')
    while True:
        m = (flag if k % 7 in (3, 4) else num).match(args, pos)
        if not m:
            break
        out.append(m.group(1)); pos = m.end(); k += 1
    return ' ' + ' '.join(out) + args[pos:]


def path_rings(d, steps=4):
    """SVG path data -> list of rings (lists of (x, y)); curves sampled, arcs taken as straight lines."""
    # shortcut: arcs become chords; MapChart only uses tiny ones (<1 px), upgrade if a source has big arcs
    # arc flags may be packed ("a.5.5 0 01.3.2"): split them into single digits before tokenizing
    d = re.sub(r'([Aa])([^A-Za-z]*)', lambda m: m.group(1) + _split_arc_flags(m.group(2)), d)
    toks = TOK.findall(d)
    rings, ring, i, cmd = [], [], 0, None
    x = y = sx = sy = 0.0
    lc = None
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]; i += 1
            if cmd in 'Zz':
                if len(ring) > 2:
                    rings.append(ring)
                ring, x, y, lc = [], sx, sy, None
                continue
        U, rel = cmd.upper(), cmd.islower()
        n = NARGS[U]
        v = [float(t) for t in toks[i:i + n]]; i += n
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if U == 'M':
            if len(ring) > 2:
                rings.append(ring)
            x, y = ox + v[0], oy + v[1]; sx, sy = x, y; ring = [(x, y)]
            cmd = 'l' if rel else 'L'; lc = None
        elif U in 'LTA':
            nx, ny = ox + v[-2], oy + v[-1]
            if U == 'T':
                c = (2*x - lc[0], 2*y - lc[1]) if lc else (x, y)
                ring += list(_bez([(x, y), c, (nx, ny)], steps)); lc = c
            else:
                ring.append((nx, ny)); lc = None
            x, y = nx, ny
        elif U == 'H':
            x = ox + v[0]; ring.append((x, y)); lc = None
        elif U == 'V':
            y = oy + v[0]; ring.append((x, y)); lc = None
        elif U == 'C':
            p1, p2, p3 = (ox+v[0], oy+v[1]), (ox+v[2], oy+v[3]), (ox+v[4], oy+v[5])
            ring += list(_bez([(x, y), p1, p2, p3], steps)); lc = p2; x, y = p3
        elif U == 'S':
            p1 = (2*x - lc[0], 2*y - lc[1]) if lc else (x, y)
            p2, p3 = (ox+v[0], oy+v[1]), (ox+v[2], oy+v[3])
            ring += list(_bez([(x, y), p1, p2, p3], steps)); lc = p2; x, y = p3
        elif U == 'Q':
            p1, p2 = (ox+v[0], oy+v[1]), (ox+v[2], oy+v[3])
            ring += list(_bez([(x, y), p1, p2], steps)); lc = p1; x, y = p2
    if len(ring) > 2:
        rings.append(ring)
    return rings


def path_geom(d):
    """Rings -> polygon with even-odd fill (subpaths inside others are holes)."""
    g = None
    for r in path_rings(d):
        p = shapely.make_valid(Polygon(r))
        if p.area <= 0:
            continue
        g = p if g is None else g.symmetric_difference(p)
    if g is None:
        return None
    ps = [q for q in shapely.get_parts(shapely.get_parts(g)) if q.geom_type == 'Polygon' and q.area > 0]
    return unary_union(ps) if ps else None


def read_svg(path):
    s = open(path, encoding='utf-8').read()
    s = s[s.index('id="map"'):]
    out = {}
    for pid, d in re.findall(r'<path id="([^"]+)"[^>]*?\sd="([^"]+)"', s):
        if pid.startswith('pattern'):
            continue
        g = path_geom(d)
        if g is not None and not g.is_empty:
            out[pid] = g if pid not in out else unary_union([out[pid], g])
    return out


def world_land():
    import editor_core, mhmap
    m = mhmap.load_map(os.path.join(editor_core.MAPS, 'World', 'xml'))
    tris = [Polygon(t) for r in m['regions'] if r.u_type != 0
            for s in mhmap.region_shapes(m, r.index) for t in s.triangles()]
    return unary_union([t for t in tris if t.area > 0])


def fit(svg_land, land, lon_range=(-180, 180), starts=None):
    """Fit x = (lon - b)/a, y = c0 + c1*lat + c2*lat^2 + c3*lat^3 so SVG land matches World land (IoU on a grid
    restricted to lon_range)."""
    from scipy.optimize import minimize
    L, T = np.meshgrid(np.arange(lon_range[0] + 0.25, lon_range[1], 0.5), np.arange(-59.75, 84, 0.5))
    target = shapely.contains_xy(land, L, T)
    # SVG land rasterized once at 4 px per SVG unit; each evaluation is then a plain array lookup
    from PIL import Image, ImageDraw
    k = 4
    W, H = int(1400.16 * k) + 1, 600 * k + 1
    img = Image.new('1', (W, H), 0)
    dr = ImageDraw.Draw(img)
    for poly in getattr(svg_land, 'geoms', [svg_land]):
        dr.polygon([(x * k, y * k) for x, y in poly.exterior.coords], fill=1)
        for h in poly.interiors:
            dr.polygon([(x * k, y * k) for x, y in h.coords], fill=0)
    R = np.array(img, dtype=bool)
    def score(p):
        a, b, c0, c1, c2, c3 = p
        X = np.round((L - b) / a * k).astype(int)
        Y = np.round((c0 + c1*T + c2*T**2 + c3*T**3) * k).astype(int)
        ok = (X >= 0) & (X < W) & (Y >= 0) & (Y < H)
        got = np.zeros_like(target)
        got[ok] = R[Y[ok], X[ok]]
        return -(got & target).sum() / max(1, (got | target).sum())
    best = None
    for p0 in starts or [[360 / 1400.16, -180, c0, c1, 0, 0] for c0, c1 in ((330, -3.6), (300, -3.2), (350, -4.0))]:
        r = minimize(score, np.array(p0, dtype=float), method='Nelder-Mead',
                     options={'maxiter': 4000, 'xatol': 1e-7, 'fatol': 1e-7})
        if best is None or r.fun < best.fun:
            best = r
    return best.x, -best.fun


def to_lonlat(p, geom):
    a, b, c0, c1, c2, c3 = p
    lats = np.linspace(-90, 90, 18001)
    ys = c0 + c1*lats + c2*lats**2 + c3*lats**3
    o = np.argsort(ys)
    return shapely.transform(geom, lambda c: np.column_stack([a * c[:, 0] + b, np.interp(c[:, 1], ys[o], lats[o])]))


SPLIT_X = 600          # SVG x between the Americas (+Greenland) and Europe/Africa


def polygonal(g):
    ps = [q for q in shapely.get_parts(shapely.get_parts(shapely.make_valid(g))) if q.geom_type == 'Polygon' and q.area > 0]
    return unary_union(ps)


# HOI4 state names that are a region of the other type in vanilla World (World seas): renamed so scenario adaptation by name
# never turns a sea into land or the other way round
RENAME = {'Panama Canal': 'Panama Canal Zone', 'Mekong Delta': 'Mekong Delta Region'}


def pretty(pid):
    import unicodedata
    n = re.sub(r'\s+', ' ', pid.replace('_', ' ')).strip()
    key = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode()      # "Panamá Canal" -> "Panama Canal"
    return RENAME.get(key, n)


def fit_real(states):
    """SVG -> real lon/lat transforms (only used to compare with World for the changelog); cached in hoi4_fit.json."""
    path = os.path.join(OUT, 'hoi4_fit.json')
    if os.path.exists(path):
        return json.load(open(path))
    land = world_land()
    # HOI4 moves the Americas relative to the Old World: one transform per side of the Atlantic (split at SVG x)
    west = {k: g for k, g in states.items() if g.centroid.x < SPLIT_X}
    east = {k: g for k, g in states.items() if k not in west}
    pe, ie = fit(unary_union(list(east.values())), land, (-30, 180))
    pw, iw = fit(unary_union(list(west.values())), land, (-180, -20), starts=[list(pe)])
    d = {'east': list(pe), 'west': list(pw), 'iou_east': ie, 'iou_west': iw, 'split_x': SPLIT_X,
         'model': 'x=(lon-b)/a, y=c0+c1*lat+c2*lat^2+c3*lat^3'}
    json.dump(d, open(path, 'w'), indent=1)
    return d


def real_to_svg(fitd, lon, lat):
    a, b, c0, c1, c2, c3 = fitd['east'] if lon > -30 else fitd['west']
    return (lon - b) / a, c0 + c1*lat + c2*lat**2 + c3*lat**3


# The pack keeps HOI4's proportions: SVG units map linearly to MH1 degrees (same scale on both axes).
K = 360 / 1400.16
LAT_TOP = 80.0
FRAME = (0.0, 0.0, 1400.16, 510.0)        # SVG area covered by the HOI4 map (land spans y 0..509.3)
BG_FIT = (0.9458, 0.0058, 0.9461, 0.8939)  # background image 2 (1483x539) px -> SVG: x*sx+ox, y*sy+oy (IoU 0.91)


def to_frame(geom):
    return shapely.transform(geom, lambda c: np.column_stack([-180 + c[:, 0] * K, LAT_TOP - c[:, 1] * K]))


def frame_bbox(img_w, img_h):
    """MH1 bbox (lon0, lat0, lon1, lat1) covered by the background image."""
    sx, ox, sy, oy = BG_FIT
    return (-180 + ox * K, LAT_TOP - (img_h * sy + oy) * K, -180 + (img_w * sx + ox) * K, LAT_TOP - oy * K)


# HOI4 strategic sea regions (names as in the game), seeds at real lon/lat; cells = Voronoi of the seeds in each water body.
# shortcut: HOI4's real sea borders are not in the SVG, so seas are Voronoi cells of these seeds; redraw by hand if exact borders matter.
SEAS = [
    ('Hudson Bay', -85, 59), ('Labrador Sea', -55, 57), ('Baffin Bay', -65, 72), ('Denmark Strait', -28, 66),
    ('Norwegian Sea', 3, 68), ('Barents Sea', 40, 73), ('White Sea', 38, 65.5), ('Kara Sea', 70, 74),
    ('North Sea', 3, 56), ('English Channel', -2, 50), ('Western Approaches', -14, 50), ('Baltic Sea', 18, 56.5),
    ('Gulf of Bothnia', 20, 62.5), ('Gulf of Finland', 26, 59.8), ('Bay of Biscay', -5, 45.5), ('Iberian Coast', -14, 40),
    ('African Coast', -16, 29), ('Mid Atlantic Ridge', -32, 52), ('North Atlantic', -40, 58), ('Mid Atlantic', -40, 40),
    ('Mid Atlantic Gap', -30, 30), ('Sargasso Sea', -60, 30), ('East Coast', -70, 38), ('Grand Banks', -50, 45),
    ('Gulf of Mexico', -90, 25), ('Caribbean Sea', -75, 15), ('Demerara Plain', -45, 12), ('Cap Verde Plain', -28, 15),
    ('Gulf of Guinea', 3, 0), ('Central Atlantic', -25, 0), ('Brazilian Coast', -33, -12), ('South Central Atlantic', -15, -18),
    ('Argentine Basin', -55, -46), ('South Atlantic', -25, -40), ('South Georgia Sea', -40, -52), ('Cape of Africa', 15, -38),
    ('Atlantic-Indian Ridge', 0, -50), ('Western Mediterranean', 4, 39), ('Tyrrhenian Sea', 12, 40), ('Central Mediterranean', 17, 35),
    ('Adriatic Sea', 16, 43), ('Aegean Sea', 25, 38), ('Eastern Mediterranean', 30, 33.5), ('Black Sea', 34, 43),
    ('Caspian Sea', 50.5, 42), ('Red Sea', 38, 20), ('Persian Gulf', 51, 27), ('Gulf of Aden', 48, 12.5),
    ('Arabian Sea', 63, 17), ('East African Coast', 45, -5), ('Mozambique Channel', 40, -18), ('West Indian Ocean', 65, -5),
    ('East Indian Ocean', 85, -5), ('Bay of Bengal', 88, 15), ('Andaman Sea', 96, 10), ('South West Indian Ocean', 55, -35),
    ('South Indian Ocean', 75, -45), ('South East Indian Ocean', 95, -35), ('Far Eastern Indian Ocean', 105, -20),
    ('Great Australian Bight', 130, -38), ('Timor Sea', 125, -12), ('Java Sea', 110, -5), ('Strait of Malacca', 99, 4),
    ('South China Sea', 113, 12), ('Gulf of Siam', 102, 10), ('Philippine Sea', 130, 15), ('East China Sea', 125, 28),
    ('Yellow Sea', 123, 36), ('Sea of Japan', 135, 40), ('Coast of Japan', 145, 33), ('Sea of Okhotsk', 150, 55),
    ('Bering Sea', 178, 58), ('Celebes Sea', 122, 3), ('Banda Sea', 127, -6), ('Arafura Sea', 135, -9),
    ('Bismarck Sea', 150, -3), ('Solomon Sea', 158, -9), ('Coral Sea', 155, -17), ('Tasman Sea', 160, -38),
    ('Mariana Region', 145, 18), ('Micronesian Gap', 160, 8), ('Eastern Micronesia', 172, 8), ('West Emperor Chain', 165, 35),
    ('North Emperor Chain', 170, 48), ('Western North Pacific', 155, 25), ('Fiji Basin', 175, -20), ('South West Pacific', 178, -42),
    ('Gulf of Alaska', -145, 55), ('North East Pacific', -140, 40), ('Central North Pacific', -170, 38), ('Hawaii Ridge', -160, 22),
    ('Central Pacific', -145, 10), ('Line Islands', -158, 0), ('Western Polynesia', -170, -15), ('Eastern Polynesia', -140, -15),
    ('South Pacific', -130, -40), ('Western Seaboard', -127, 40), ('Mexican Coast', -110, 18), ('Central American Coast', -92, 8),
    ('Galapagos Sea', -100, -3), ('Peruvian Coast', -82, -12), ('Chilean Coast', -78, -35), ('South East Pacific', -105, -30),
    ('Drake Passage', -68, -56), ('Beaufort Sea', -140, 72), ('Chukchi Sea', -170, 70), ('Arctic Archipelago', -95, 74),
    ('Laptev Sea', 125, 76), ('East Siberian Sea', 160, 72),
]
# enclosed water bodies: named after the closest of these (real lon/lat), else 'Lake N'
LAKES = [('Caspian Sea', 50.5, 42), ('Aral Sea', 60, 45), ('Lake Superior', -87.5, 47.7), ('Lake Michigan', -87, 44),
         ('Lake Huron', -82.4, 44.8), ('Lake Erie', -81, 42.2), ('Lake Ontario', -77.8, 43.6), ('Lake Winnipeg', -97.5, 52.5),
         ('Great Bear Lake', -121, 66), ('Great Slave Lake', -114, 61.5), ('Lake Baikal', 108, 53.5), ('Lake Balkhash', 74.5, 46.5),
         ('Lake Ladoga', 31.5, 61), ('Lake Onega', 35.5, 61.7), ('Lake Victoria', 33, -1), ('Lake Tanganyika', 29.5, -6),
         ('Lake Malawi', 34.5, -12), ('Lake Chad', 14, 13), ('Lake Vanern', 13.2, 58.9), ('Lake Titicaca', -69.4, -15.8),
         ('Lake Nicaragua', -85.4, 11.5), ('Issyk-Kul', 77.3, 42.4), ('Lake Athabasca', -109, 59.3), ('Reindeer Lake', -102.3, 57.2)]
LAKE_MIN = 3.0       # SVG px^2: enclosed holes smaller than this are gaps between states, filled into the land
LAKE_KEEP = 0.8 / K**2   # SVG px^2 (= 0.8 square degrees in the pack): smaller enclosed lakes are given to the land around them


def clean_states(states):
    """Disjoint states covering the closed land: overlaps cut (larger state first), slivers/tiny holes -> nearest state."""
    from shapely.strtree import STRtree
    U = unary_union(list(states.values()))
    C = U.buffer(0.15, join_style='mitre').buffer(-0.15, join_style='mitre')
    # fill enclosed holes smaller than LAKE_MIN (gaps between states); bigger ones are lakes
    parts = []
    for p in shapely.get_parts(C):
        keep = [h for h in p.interiors if Polygon(h).area >= LAKE_MIN]
        parts.append(Polygon(p.exterior, keep))
    C = unary_union(parts)
    shapely.prepare(C)
    order = sorted(states, key=lambda k: -states[k].area)
    raw = [states[k] for k in order]
    rtree = STRtree(raw)
    out = {}
    for i, k in enumerate(order):
        g = raw[i].intersection(C)
        prev = [raw[j] for j in rtree.query(raw[i]) if j < i]         # larger states already placed win overlaps
        if prev:
            g = g.difference(unary_union(prev))
        out[k] = polygonal(g)
    rest = [q for q in shapely.get_parts(polygonal(C.difference(unary_union(list(out.values()))))) if q.area > 1e-9]
    keys = [k for k in out if not out[k].is_empty]
    tree = STRtree([out[k] for k in keys])
    add = {}
    for q in rest:
        add.setdefault(keys[int(tree.nearest(q.representative_point()))], []).append(q)
    for k, qs in add.items():
        out[k] = polygonal(unary_union([out[k]] + qs))
    return {k: g for k, g in out.items() if not g.is_empty}, C


def seas(C, fitd, taken):
    """Water inside FRAME split into the SEAS cells; enclosed lakes without a seed get 'Lake N'."""
    from shapely.geometry import box, MultiPoint, Point
    from shapely.ops import voronoi_diagram
    water = polygonal(box(*FRAME).difference(C))
    seeds = []
    for name, lon, lat in SEAS:
        x, y = real_to_svg(fitd, lon, lat)
        p = Point(min(max(x, 0.5), FRAME[2] - 0.5), min(max(y, 0.5), FRAME[3] - 0.5))
        if not water.contains(p):            # seed fell on land: nearest water point
            from shapely.ops import nearest_points
            p = nearest_points(water, p)[0]
        seeds.append((name + (' Sea Zone' if name in taken else ''), p))
    lakes = [(n, Point(*real_to_svg(fitd, lon, lat))) for n, lon, lat in LAKES]
    out, nlake, small = {}, 0, []
    for comp in sorted(shapely.get_parts(water), key=lambda g: -g.area):
        inside = [(n, p) for n, p in seeds if comp.buffer(1e-6).contains(p)]
        if not inside:
            if comp.area < LAKE_KEEP:
                small.append(comp)
                continue
            n, p = min(lakes, key=lambda np_: comp.distance(np_[1]))
            if comp.distance(p) > 3 / K or n in out:        # no known lake within ~3 degrees (or already used)
                nlake += 1
                n = 'Lake %d' % nlake
            out.setdefault(n, []).append(comp)
            continue
        if len(inside) == 1:
            out.setdefault(inside[0][0], []).append(comp)
            continue
        cells = voronoi_diagram(MultiPoint([p for _, p in inside]), envelope=box(*FRAME).buffer(50))
        for cell in shapely.get_parts(cells):
            n = next(n for n, p in inside if cell.buffer(1e-9).contains(p))
            out.setdefault(n, []).append(comp.intersection(cell))
    res = {n: polygonal(unary_union(gs)) for n, gs in out.items()}
    # pieces of a cell cut off from its seed go to the neighbouring sea sharing the longest border
    seed_of = dict(seeds)
    for n in list(res):
        parts = list(shapely.get_parts(res[n]))
        if len(parts) < 2 or n not in seed_of:
            continue
        main = max(parts, key=lambda q: (q.buffer(1e-6).contains(seed_of[n]), q.area))
        for q in parts:
            if q is main:
                continue
            best = max((m for m in res if m != n), key=lambda m: q.buffer(1e-6).intersection(res[m]).area)
            if q.buffer(1e-6).intersection(res[best]).area > 0:
                res[best] = polygonal(unary_union([res[best], q]))
                res[n] = polygonal(res[n].difference(q))
    return {n: g for n, g in res.items() if not g.is_empty}, small


def give_to_land(clean, pieces):
    """Each piece joins the state sharing the longest border with it (nearest if none touches)."""
    from shapely.strtree import STRtree
    keys = list(clean)
    tree = STRtree([clean[k] for k in keys])
    add = {}
    for q in pieces:
        near = [keys[i] for i in tree.query(q.buffer(0.05))]
        k = max(near, key=lambda k: q.buffer(0.05).intersection(clean[k]).area) if near else keys[int(tree.nearest(q))]
        add.setdefault(k, []).append(q)
    for k, qs in add.items():
        clean[k] = polygonal(unary_union([clean[k]] + qs))


def snapped(g, grid=1e-4):
    """Valid polygonal geometry on the editor's 1e-4 degree grid (mh2_make_world2.prep snaps again; it must not fail)."""
    g = polygonal(g)
    for tries in range(3):
        try:
            return polygonal(shapely.set_precision(g, grid))
        except shapely.errors.GEOSException:
            g = polygonal(g.buffer(0))
    return polygonal(shapely.set_precision(g.buffer(grid).buffer(-grid), grid))


def main():
    os.makedirs(OUT, exist_ok=True)
    states = read_svg(sys.argv[1])
    print('%d states read' % len(states), flush=True)
    fitd = fit_real(states)
    clean, C = clean_states(states)
    print('%d clean states' % len(clean), flush=True)
    names = {pretty(k) for k in clean}
    sea, small = seas(C, fitd, names)
    give_to_land(clean, small)
    print('%d sea regions (%d named lakes / %d unnamed), %d small lakes given to land' % (
        len(sea), sum(1 for n in sea if n in dict((l[0], 1) for l in LAKES)), sum(1 for n in sea if re.match(r'Lake \d+$', n)), len(small)), flush=True)
    feats = [{'type': 'Feature', 'properties': {'name': pretty(pid), 'hoi4_id': pid, 'mh_type': 'land_region'},
              'geometry': mapping(snapped(to_frame(g)))} for pid, g in clean.items()]
    feats += [{'type': 'Feature', 'properties': {'name': n, 'mh_type': 'sea_region'}, 'geometry': mapping(snapped(to_frame(g)))}
              for n, g in sea.items()]
    json.dump({'type': 'FeatureCollection', 'features': feats}, open(os.path.join(OUT, 'hoi4_states.geojson'), 'w', encoding='utf-8'))
    print('%d features -> %s | background bbox for image 2: %s' % (len(feats), os.path.join(OUT, 'hoi4_states.geojson'),
                                                                 [round(v, 4) for v in frame_bbox(1483, 539)]))


if __name__ == '__main__':
    assert len(path_rings('M0 0h10v10h-10z')[0]) == 4      # self-check of the path parser
    assert abs(path_geom('M0 0h10v10h-10zM2 2h2v2h-2z').area - 96) < 1e-9
    main()
