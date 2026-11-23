"""EU4 map (provinces.bmp + area.txt + localisation) -> GeoJSON in EU4's own map frame, ready for eu4_make_pack.py.

    python -u eu4_geojson.py "<path>/MapChart_Map.svg" [--eu4 "<EU4 folder>"] [--out D:/MHData/eu4_work]

Regions = EU4 land provinces (impassable ones too), EU4 sea areas and EU4 lakes (>= LAKE_KEEP; smaller ones go to the land).
The province raster is vectorized as one shared line per pair of neighbours: pixel stairs become segment midpoints and are
simplified (sea-sea borders much more, so they come out straight); faces of the line network take the region under them.
Pack frame: EU4 px -> degrees, 360/5632 per px on both axes, top = 80 (like WorldHOI4).
The MapChart SVG (real-world projection, EU4 provinces) is only used to fit SVG -> EU4 px (thin-plate spline + coast ICP) and
SVG -> real lon/lat: together they give the projection and the inheritance changelog against World.
Output (--out): eu4_states.geojson, eu4_fit.json, warp_grid.npy (SVG -> EU4 px), warp_inv.npy (EU4 px -> SVG).
"""
import argparse, json, os, pickle, re, sys, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, scipy.ndimage as nd, shapely, shapely.affinity
from shapely.geometry import Polygon, LineString, box, mapping
from shapely.ops import unary_union, polygonize, linemerge
from shapely.strtree import STRtree
from scipy.interpolate import RBFInterpolator, RegularGridInterpolator
from PIL import Image, ImageDraw
import hoi4_geojson as H

PXW, PXH = 5632, 2048
K = 360 / PXW            # degrees per EU4 px
LAT_TOP = 80.0
SVG_W, SVG_H = 1200, 680
GSTEP = 2.0              # SVG units between warp grid nodes
GY, GX = np.mgrid[-2:SVG_H + 4:GSTEP, -2:SVG_W + 4:GSTEP]
TOL_SEA = 0.25           # degrees: Douglas-Peucker tolerance of sea-sea borders (straight, not pixel stairs)
TOL_LAND = 0.6           # EU4 px: tolerance of every other border, after the staircase midpoints
LAKE_KEEP = 0.8          # square degrees: smaller EU4 lakes go to the land around them
SEA_PER = 2.5            # sea provinces per sea region (EU4 sea areas are split)
SEA0, LAKE0 = 100000, 200000     # region ids of sea areas and lakes in the raster


def px_to_deg(P):
    return np.column_stack([-180 + P[:, 0] * K, LAT_TOP - P[:, 1] * K])


# ---------------------------------------------------------------- EU4 data
def eu4_data(eu4, out):
    cache = os.path.join(out, 'eu4_data.pkl')
    if os.path.exists(cache):
        return pickle.load(open(cache, 'rb'))
    m = eu4 + '/map/'
    im = np.asarray(Image.open(m + 'provinces.bmp').convert('RGB')).astype(np.int32)
    key = im[..., 0] << 16 | im[..., 1] << 8 | im[..., 2]
    col = {}
    for line in open(m + 'definition.csv', encoding='latin-1').read().splitlines()[1:]:
        p = line.split(';')
        if len(p) > 3 and p[0].isdigit():
            col[int(p[1]) << 16 | int(p[2]) << 8 | int(p[3])] = int(p[0])
    u, inv = np.unique(key, return_inverse=True)
    lab = np.array([col.get(int(c), 0) for c in u], dtype=np.int32)[inv].reshape(key.shape)
    txt = open(m + 'default.map').read()
    ids = lambda k: {int(x) for x in re.findall(r'\d+', re.search(k + r'\s*=\s*\{([^}]*)\}', txt).group(1))}
    a = re.sub(r'#.*', '', open(m + 'area.txt', encoding='latin-1').read())
    a = re.sub(r'color\s*=\s*\{[^}]*\}', '', a)
    areas = {k: [int(x) for x in re.findall(r'\b\d+\b', v)] for k, v in re.findall(r'(\w+)\s*=\s*\{([^{}]*)\}', a)}
    loc = lambda f: dict(re.findall(r'^\s*(\w+):\d*\s*"(.*)"', open(eu4 + '/localisation/' + f, encoding='utf-8-sig').read(), re.M))
    names = {int(k[4:]): v for k, v in loc('prov_names_l_english.yml').items() if k.startswith('PROV') and k[4:].isdigit()}
    d = {'lab': lab, 'sea': ids('sea_starts'), 'lakes': ids('lakes'), 'areas': areas, 'names': names, 'area_names': loc('areas_regions_l_english.yml')}
    pickle.dump(d, open(cache, 'wb'))
    return d


# ---------------------------------------------------------------- warp SVG -> EU4 px
def grid_interp(G):
    RX = RegularGridInterpolator((GY[:, 0], GX[0]), G[..., 0], bounds_error=False, fill_value=None)
    RY = RegularGridInterpolator((GY[:, 0], GX[0]), G[..., 1], bounds_error=False, fill_value=None)
    return lambda P: np.column_stack([RX(P[:, ::-1]), RY(P[:, ::-1])])


def jacobian(G):
    return np.gradient(G[..., 0], axis=1) * np.gradient(G[..., 1], axis=0) - np.gradient(G[..., 0], axis=0) * np.gradient(G[..., 1], axis=1)


def fit_warp(states, D, out):
    path = os.path.join(out, 'warp_grid.npy')
    if os.path.exists(path):
        return np.load(path)
    lab = D['lab']; water = D['sea'] | D['lakes']
    norm = lambda s: re.sub(r'[^a-z]', '', unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower())
    byname = {}
    for i, n in D['names'].items():
        byname.setdefault(norm(n), []).append(i)
    ys, xs = np.mgrid[0:PXH, 0:PXW]
    cnt = np.bincount(lab.ravel()); cx = np.bincount(lab.ravel(), xs.ravel()) / np.maximum(cnt, 1); cy = np.bincount(lab.ravel(), ys.ravel()) / np.maximum(cnt, 1)
    del ys, xs
    keys = list(states)
    Cc = np.array([[states[k].centroid.x, states[k].centroid.y] for k in keys])
    Cr = np.array([[states[k].representative_point().x, states[k].representative_point().y] for k in keys])
    # 1. unique-name pairs, robust TPS
    src, dst = [], []
    for i, k in enumerate(keys):
        c = [j for j in byname.get(norm(k.replace('_', ' ')), []) if j not in water]
        if len(c) == 1:
            src.append(Cc[i]); dst.append((cx[c[0]], cy[c[0]]))
    src, dst = np.array(src), np.array(dst)
    keep = np.ones(len(src), bool)
    for _ in range(6):
        f = RBFInterpolator(src[keep], dst[keep], kernel='thin_plate_spline', smoothing=50.0)
        r = np.hypot(*(f(src) - dst).T); keep = r < max(6, 3 * np.median(r[keep]))
    print('warp: %d name pairs kept of %d' % (keep.sum(), len(src)), flush=True)
    # 2. densify: province under each warped interior point
    for it in range(3):
        P = f(Cr); s2, d2 = list(src[keep]), list(dst[keep])
        for i, (px, py) in enumerate(np.round(P).astype(int)):
            if 0 <= px < PXW and 0 <= py < PXH and lab[py, px] not in water:
                s2.append(Cc[i]); d2.append((cx[lab[py, px]], cy[lab[py, px]]))
        s2, d2 = np.array(s2), np.array(d2)
        k2 = np.ones(len(s2), bool)
        for _ in range(4):
            f = RBFInterpolator(s2[k2], d2[k2], kernel='thin_plate_spline', smoothing=200.0)
            r = np.hypot(*(f(s2) - d2).T); k2 = r < max(5, 2.5 * np.median(r[k2]))
    src, dst = s2[k2], d2[k2]
    print('warp: %d province pairs' % len(src), flush=True)
    # 3. coastline ICP both ways (subsampled each pass: the TPS system stays small, the page file on C: stays put)
    from scipy.spatial import cKDTree
    land = ~np.isin(lab, list(water | {0}))
    coast = land & ~nd.binary_erosion(land)
    _, (iy, ix) = nd.distance_transform_edt(~coast, return_indices=True)
    cyx = np.argwhere(coast)[::6][:, ::-1].astype(float)
    U = unary_union(list(states.values())).buffer(0.3).buffer(-0.3)
    S = np.array([l.interpolate(t).coords[0] for p in getattr(U, 'geoms', [U]) if p.area >= 4
                  for l in [p.exterior] for t in np.arange(0, l.length, 1.5)])
    for it, (thr, sm) in enumerate([(90, 900), (80, 600), (60, 450), (40, 300), (25, 250), (15, 200)]):
        Wp = f(S)
        xi = np.clip(np.round(Wp[:, 0]).astype(int), 0, PXW - 1); yi = np.clip(np.round(Wp[:, 1]).astype(int), 0, PXH - 1)
        T = np.column_stack([ix[yi, xi], iy[yi, xi]]).astype(float)
        dd = np.hypot(*(T - Wp).T); ok = (dd < thr) & (np.arange(len(dd)) % 4 == it % 4)
        dq, jq = cKDTree(Wp).query(cyx)
        ok2 = (dq < thr) & (np.arange(len(dq)) % 8 == it % 8)
        s2 = np.vstack([src, S[ok], S[jq[ok2]]]); d2 = np.vstack([dst, T[ok], cyx[ok2]])
        s2, ui = np.unique(np.round(s2, 2), axis=0, return_index=True)
        f = RBFInterpolator(s2, d2[ui], kernel='thin_plate_spline', smoothing=float(sm))
        print('warp: ICP %d median coast distance %.2f px' % (it, np.median(dd)), flush=True)
    G = np.concatenate([f(np.column_stack([GX.ravel()[i:i + 40000], GY.ravel()[i:i + 40000]]))
                        for i in range(0, GX.size, 40000)]).reshape(GX.shape + (2,))
    # 4. unfold: Laplacian smoothing on folded cells (the Arctic squeeze folds the TPS)
    for it in range(1500):
        bad = jacobian(G) <= 0.05
        bad[0], bad[-1], bad[:, 0], bad[:, -1] = False, False, False, False
        if not bad.any():
            break
        msk = nd.binary_dilation(bad, iterations=2)
        msk[0], msk[-1], msk[:, 0], msk[:, -1] = False, False, False, False
        avg = (np.roll(G, 1, 0) + np.roll(G, -1, 0) + np.roll(G, 1, 1) + np.roll(G, -1, 1)) / 4
        G[msk] = avg[msk]
    print('warp: folded cells left %d (edge rows ignored)' % int((jacobian(G)[1:-1, 1:-1] <= 0).sum()), flush=True)
    np.save(path, G)
    return G


def inverse_grid(G, out):
    """EU4 px -> SVG on a 4 px grid (for the changelog and the projection)."""
    path = os.path.join(out, 'warp_inv.npy')
    if os.path.exists(path):
        return np.load(path)
    from scipy.interpolate import griddata
    iy, ix = np.mgrid[0:PXH + 1:4, 0:PXW + 1:4]
    pts = G.reshape(-1, 2)
    inv = np.stack([griddata(pts, v, (ix, iy), method='linear') for v in (GX.ravel(), GY.ravel())], -1)
    for c in range(2):                                   # outside the SVG's warped hull: nearest
        bad = np.isnan(inv[..., c])
        if bad.any():
            i = nd.distance_transform_edt(bad, return_distances=False, return_indices=True)
            inv[..., c] = inv[..., c][i[0], i[1]]
    np.save(path, inv)
    return inv




def fit_real(states, out):
    path = os.path.join(out, 'eu4_fit.json')
    if os.path.exists(path):
        return json.load(open(path))
    land = H.world_land()
    starts = [[360 / SVG_W, -169, c0, c1, 0, 0] for c0, c1 in ((330, -3.3), (360, -3.6), (390, -4.0))]
    p, iou = H.fit(unary_union(list(states.values())), land, (-180, 180), starts=starts)
    d = {'p': list(p), 'iou': iou, 'model': 'x=(lon-b)/a, y=c0+c1*lat+c2*lat^2+c3*lat^3 (SVG units)'}
    json.dump(d, open(path, 'w'), indent=1)
    return d




# ---------------------------------------------------------------- direct import of provinces.bmp
def prov_names(eu4):
    """PROVn -> English name from every English localisation file (prov_names misses wastelands and some others)."""
    out = {}
    d = eu4 + '/localisation/'
    for fn in sorted(os.listdir(d)):
        if fn.endswith('_l_english.yml'):
            for m in re.finditer(r'^\s*PROV(\d+):\d*\s*"(.*)"', open(d + fn, encoding='utf-8-sig', errors='replace').read(), re.M):
                out.setdefault(int(m.group(1)), m.group(2))
    return out


def sea_geometry(D):
    """D['px'] pixel count, D['cxy'] centroid, D['adj'] neighbours of every sea province (from the raster)."""
    lab = D['lab']
    n = lab.max() + 1
    ys, xs = np.mgrid[0:lab.shape[0], 0:lab.shape[1]]
    cnt = np.bincount(lab.ravel(), minlength=n)
    cx = np.bincount(lab.ravel(), xs.ravel(), minlength=n) / np.maximum(cnt, 1)
    cy = np.bincount(lab.ravel(), ys.ravel(), minlength=n) / np.maximum(cnt, 1)
    del ys, xs
    pairs = np.concatenate([np.stack([lab[:, :-1].ravel(), lab[:, 1:].ravel()], 1), np.stack([lab[:-1].ravel(), lab[1:].ravel()], 1)])
    pairs = np.unique(pairs[pairs[:, 0] != pairs[:, 1]], axis=0)
    adj = {}
    for a, b in pairs:
        adj.setdefault(int(a), set()).add(int(b)); adj.setdefault(int(b), set()).add(int(a))
    D['px'], D['cxy'], D['adj'] = cnt, np.column_stack([cx, cy]), adj


def split_area(v, D):
    """Sea area -> lists of ~SEA_PER contiguous provinces: farthest-point seeds, nearest-seed cells, cut-off bits to a neighbour cell."""
    k = max(1, int(round(len(v) / SEA_PER)))
    if k == 1:
        return [v]
    C = D['cxy'][v]
    seeds = [int(np.argmax(np.hypot(*(C - C.mean(0)).T)))]
    while len(seeds) < k:
        dmin = np.min([np.hypot(*(C - C[s]).T) for s in seeds], 0)
        seeds.append(int(np.argmax(dmin)))
    cell = {p: int(np.argmin([np.hypot(*(C[i] - C[s])) for s in seeds])) for i, p in enumerate(v)}
    for _ in range(3):                                   # contiguity: pieces not holding their seed join a touching cell
        for c in range(k):
            mem = {p for p in v if cell[p] == c}
            if not mem:
                continue
            start = v[seeds[c]] if v[seeds[c]] in mem else next(iter(mem))
            seen, todo = {start}, [start]
            while todo:
                q = todo.pop()
                for r in D['adj'].get(q, ()):
                    if r in mem and r not in seen:
                        seen.add(r); todo.append(r)
            for p in mem - seen:
                nb = [cell[r] for r in D['adj'].get(p, ()) if r in cell and cell[r] != c]
                if nb:
                    cell[p] = max(set(nb), key=nb.count)
    out = {}
    for p in v:
        out.setdefault(cell[p], []).append(p)
    return list(out.values())


def groups(D):
    """Raster of region ids: land province id; sea areas SEA0+i; lakes (connected lake provinces, >= LAKE_KEEP) LAKE0+i.
    Smaller lakes and pixels of sea provinces outside any area take their neighbours' ids. Returns (R, {id: name})."""
    lab = D['lab']
    sea_geometry(D)
    info = {}
    sea_areas = sorted((k, v) for k, v in D['areas'].items() if v and all(x in D['sea'] for x in v))
    lut = np.zeros(lab.max() + 1, np.int64)
    gi = 0
    for k, v in sea_areas:
        aname = D['area_names'].get(k, k.replace('_area', '').replace('_', ' ').title())
        for part in split_area([x for x in v if x < len(lut)], D):
            lut[part] = SEA0 + gi
            big = max(part, key=lambda p: D['px'][p])
            info[SEA0 + gi] = D['names'].get(big, aname) if len(part) < len(v) else aname
            gi += 1
    seaR = lut[lab]
    R = np.where(seaR > 0, seaR, lab).astype(np.int64)
    R[np.isin(lab, list(D['sea'])) & (seaR == 0)] = -1           # sea province outside any area: filled below
    lk = np.isin(lab, list(D['lakes']))
    comp, n = nd.label(lk)
    sizes = nd.sum(np.ones_like(comp), comp, index=np.arange(1, n + 1))
    for c in range(1, n + 1):
        m = comp == c
        if sizes[c - 1] * K * K >= LAKE_KEEP:
            ids_, cnts = np.unique(lab[m], return_counts=True)
            nm = D['names'].get(int(ids_[np.argmax(cnts)]), 'Lake %d' % c)
            info[LAKE0 + c] = nm if re.search(r'\b(Lake|Sea|Lac|Lago)\b', nm) else 'Lake ' + nm
            R[m] = LAKE0 + c
        else:
            R[m] = -1
    i = nd.distance_transform_edt(R == -1, return_distances=False, return_indices=True)
    return R[i[0], i[1]], info


def _runs(diff, a, b):
    """Run-length segments of a boolean edge mask along axis 1, split where the labels on either side change.
    Returns [(start, end, row, label_a, label_b)]."""
    out = []
    for r in np.flatnonzero(diff.any(1)):
        idx = np.flatnonzero(diff[r])
        la, lb = a[r][idx], b[r][idx]
        cut = np.flatnonzero((np.diff(idx) != 1) | (la[1:] != la[:-1]) | (lb[1:] != lb[:-1])) + 1
        st = np.r_[0, cut]; en = np.r_[cut, len(idx)]
        out += [(idx[s], idx[e - 1] + 1, r, la[s], lb[s]) for s, e in zip(st, en)]
    return out


def border_lines(R):
    """{(a, b): [LineString px]} one shared line set per pair of neighbouring ids (-2 = outside the map), merged at degree-2 nodes."""
    P = np.pad(R, 1, constant_values=-2)
    segs = {}
    d = P[:, :-1] != P[:, 1:]                 # vertical edges: between padded columns x and x+1 -> unpadded x = x
    for s, e, x, la, lb in _runs(d.T, P[:, :-1].T, P[:, 1:].T):
        segs.setdefault((min(la, lb), max(la, lb)), []).append(((x, s - 1), (x, e - 1)))
    d = P[:-1, :] != P[1:, :]                 # horizontal edges: between padded rows y and y+1 -> unpadded y = y
    for s, e, y, la, lb in _runs(d, P[:-1, :], P[1:, :]):
        segs.setdefault((min(la, lb), max(la, lb)), []).append(((s - 1, y), (e - 1, y)))
    out = {}
    for k, ss in segs.items():
        m = shapely.line_merge(shapely.multilinestrings(shapely.linestrings(ss)))
        out[k] = [l for l in shapely.get_parts(m) if not l.is_empty]
    return out


def smooth(line, tol):
    """Pixel staircase -> midpoints of its segments (ends kept: they are junctions), then Douglas-Peucker; rings stay closed."""
    c = np.asarray(line.coords)
    if len(c) < 3:
        return line
    closed = np.allclose(c[0], c[-1])
    mid = (c[:-1] + c[1:]) / 2
    pts = np.vstack([mid, mid[:1]]) if closed else np.vstack([c[:1], mid, c[-1:]])
    if len(pts) < 9:
        return LineString(pts)
    return LineString(pts).simplify(tol, preserve_topology=False)


def regions(R, lines):
    """Faces of the smoothed border network -> {id: polygon in degrees}."""
    out_lines = []
    for (a, b), ls in lines.items():
        sea_sea = SEA0 <= a < LAKE0 and SEA0 <= b < LAKE0
        if a == -2:                                             # map frame: unchanged
            out_lines += ls
        else:
            out_lines += [smooth(l, TOL_SEA / K if sea_sea else TOL_LAND) for l in ls]
    print('border lines: %d' % len(out_lines), flush=True)
    net = shapely.union_all(np.array(out_lines, dtype=object))
    faces = np.array(shapely.get_parts(shapely.polygonize(shapely.get_parts(net))))
    print('faces: %d' % len(faces), flush=True)
    rp = shapely.get_coordinates(shapely.point_on_surface(faces))
    owner = R[np.clip(rp[:, 1].astype(int), 0, R.shape[0] - 1), np.clip(rp[:, 0].astype(int), 0, R.shape[1] - 1)]
    order = np.argsort(owner, kind='stable')
    res = {int(owner[g[0]]): shapely.union_all(faces[g]) for g in np.split(order, np.flatnonzero(np.diff(owner[order])) + 1)}
    return {k: H.polygonal(shapely.transform(g, px_to_deg)) for k, g in res.items()}


def names_for(res, info, pnames, D):
    """Unique, readable names: EU4 province names; repeated ones get their area; clashes with seas get ' Region'."""
    import editor_core, mhmap
    wsea = {r.name for r in mhmap.load_map(os.path.join(editor_core.MAPS, 'World', 'xml'))['regions'] if r.u_type == 0}
    prov_area = {p: a for a, v in D['areas'].items() for p in v}
    seas = {info[k] for k in res if k in info}
    raw = {k: re.sub(r'\s+', ' ', pnames.get(k, 'Province %d' % k)).strip() for k in res if k not in info}
    cnt = {}
    for n in raw.values():
        cnt[n] = cnt.get(n, 0) + 1
    out, used = {}, set()
    for k, n in sorted(raw.items()):
        if cnt[n] > 1:
            a = prov_area.get(k)
            n = '%s (%s)' % (n, D['area_names'].get(a, str(k)) if a else str(k))
        if n in seas or n in wsea:
            n += ' Region'
        while n.lower() in used:
            n += ' %d' % k
        used.add(n.lower()); out[k] = n
    for k in res:
        if k in info:
            n = info[k]
            if n.lower() in used:
                n += ' Waters'
            base, i = n, 1
            while n.lower() in used:
                i += 1
                n = '%s %d' % (base, i)
            used.add(n.lower()); out[k] = n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('svg', help='MapChart EU4 SVG: only used to fit the projection (real lon/lat <-> EU4 frame)')
    ap.add_argument('--eu4', default='D:/SteamLibrary/steamapps/common/Europa Universalis IV')
    ap.add_argument('--out', default='D:/MHData/eu4_work')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    D = eu4_data(a.eu4, a.out)
    sp = os.path.join(a.out, 'svg_states.pkl')
    if not os.path.exists(sp):
        pickle.dump(H.read_svg(a.svg), open(sp, 'wb'))
    states = pickle.load(open(sp, 'rb'))
    G = fit_warp(states, D, a.out)
    inverse_grid(G, a.out)
    print('SVG -> real lon/lat fit IoU %.3f' % fit_real(states, a.out)['iou'], flush=True)
    R, info = groups(D)
    res = regions(R, border_lines(R))
    names = names_for(res, info, prov_names(a.eu4), D)
    print('%d land provinces, %d seas, %d lakes' % (sum(1 for k in res if k not in info), sum(1 for k in res if SEA0 <= k < LAKE0),
                                                     sum(1 for k in res if k >= LAKE0)), flush=True)
    feats = [{'type': 'Feature', 'properties': {'name': names[k], 'eu4_id': None if k in info else int(k),
                                                'mh_type': 'sea_region' if k in info else 'land_region'},
              'geometry': mapping(H.snapped(g))} for k, g in res.items() if not g.is_empty]
    json.dump({'type': 'FeatureCollection', 'features': feats}, open(os.path.join(a.out, 'eu4_states.geojson'), 'w', encoding='utf-8'))
    print('%d features -> %s' % (len(feats), os.path.join(a.out, 'eu4_states.geojson')))


if __name__ == '__main__':
    assert np.allclose(px_to_deg(np.array([[0, 0], [PXW, PXH]])), [[-180, 80], [180, 80 - PXH * K]])
    _t = smooth(LineString([(0, 0), (1, 0), (1, 1), (2, 1), (2, 2)]), 0.1)
    assert _t.coords[0] == (0, 0) and _t.coords[-1] == (2, 2)          # staircase ends stay put (they are junctions)
    _r = _runs(np.array([[True, True, False, True]]), np.array([[1, 1, 0, 2]]), np.array([[3, 3, 0, 3]]))
    assert [(s, e) for s, e, *_ in _r] == [(0, 2), (3, 4)]
    main()
