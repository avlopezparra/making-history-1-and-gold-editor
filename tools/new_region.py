"""New regions in the map binaries and data derived from the geometry.

What is known of the regions.bin fields (comparing the 852 original regions):
  u_type   base terrain class of the map: 0 sea, 1 plains/forest, 2 hills, 3 mountain, 4 desert/steppe
           (matches the most frequent strTerrain of each class in the scenarios; the scenario may change it).
  u_a      LAND area of the region; 0 at sea; smaller than u_b on islands and clipped coasts.
  u_b      TOTAL mesh area: u_b = 4767.13 * sum(triangle_area_degrees2 * cos(latitude)) (~ square miles).
  points   up to 30 points inside the region on a grid around the center (the first is the center),
           sorted by distance; step 0.108..1.73 degrees depending on size.
borders.brd final table: u_x = region index. regions.nts final table: u_last = last.

create_region() adds the empty region (shape without triangles, without neighbors or borders) at the end of the three files;
the area comes later with transfer.apply_transfers(), which creates its borders and neighborships.
refresh_derived() recomputes areas, center and points of the regions whose mesh changed.
"""
import math
import os
import sys

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap  # noqa: E402
from transfer import f32, SEA  # noqa: E402

AREA_K = 4767.13          # u_b / (degrees2 * cos lat), median of the original map (~ square miles)
GRID = 0.21575            # paso base de la rejilla de puntos (en grados)
MAX_POINTS = 30
TERRAIN_OF_TYPE = {1: 'Plains', 2: 'Hills', 3: 'Mountains', 4: 'Desert'}
TYPE_OF_TERRAIN = {'Plains': 1, 'Forest': 1, 'Tundra': 1, 'Hills': 2, 'Jungle': 2, 'Mountains': 3, 'Desert': 4}


def internal_name(text):
    """Internal region name: ASCII without accents (no original region uses other characters)."""
    import re
    import unicodedata
    s = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode('ascii')
    return ' '.join(re.sub(r"[^A-Za-z0-9 .'()-]", ' ', s).split())


def create_region(m, name, u_type):
    """Adds an empty region at the end; returns its index."""
    R = m['regions']
    idx = len(R)
    si = len(m['shapes'])
    raw = name.encode('latin1')
    m['shapes'].append(mhmap.Shape(si, 0, [], []))
    m['shape_table'].append(mhmap.ShapeIndexRow(idx, si, si, si))
    m['border_table'].append(mhmap.BorderIndexRow(idx, idx, []))
    R.append(mhmap.Region(idx, raw, int(u_type), 0, 0, 1 if int(u_type) == 0 else 0, 0.0, 0.0, 0, [], []))   # u_flag 1 = mar
    return idx


def mesh_polygon(m, r):
    tris = [t for s in mhmap.region_shapes(m, r) for t in s.triangles()]
    return unary_union([Polygon(t) for t in tris if len(set(t)) == 3 and Polygon(t).area > 0])


def cos_area(m, r):
    """Sum of area_degrees2 * cos(latitude) of the region's triangles."""
    k = 0.0
    for s in mhmap.region_shapes(m, r):
        for t in s.triangles():
            a = abs((t[1][0] - t[0][0]) * (t[2][1] - t[0][1]) - (t[2][0] - t[0][0]) * (t[1][1] - t[0][1])) / 2
            k += a * math.cos(math.radians((t[0][1] + t[1][1] + t[2][1]) / 3))
    return k


def grid_points(poly, center):
    """Center + grid points inside the polygon (up to 30, from closest to the center to farthest)."""
    inner = poly.buffer(-1e-4)
    if inner.is_empty:
        inner = poly
    cx, cy = center
    best = []
    for mult in (0.5, 1, 2, 4, 8):
        s = GRID * mult
        x0, y0, x1, y1 = poly.bounds
        nx0, nx1 = int(math.floor((x0 - cx) / s)), int(math.ceil((x1 - cx) / s))
        ny0, ny1 = int(math.floor((y0 - cy) / s)), int(math.ceil((y1 - cy) / s))
        if (nx1 - nx0) * (ny1 - ny0) > 40000:
            continue
        pts = [(cx + i * s, cy + j * s) for i in range(nx0, nx1 + 1) for j in range(ny0, ny1 + 1) if (i, j) != (0, 0)]
        pts = [p for p in pts if inner.contains(Point(p))]
        best = pts
        if len(pts) <= 3 * MAX_POINTS:
            break
    best.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    return [(f32(cx), f32(cy))] + [(f32(x), f32(y)) for x, y in best[:MAX_POINTS - 1]]


def pick_center(poly, old=None):
    """The previous center if still inside; otherwise the centroid of the largest piece (or an interior point)."""
    if old is not None and poly.buffer(-1e-4).contains(Point(old)):
        return old
    pieces = list(getattr(poly, 'geoms', [poly]))
    big = max(pieces, key=lambda p: p.area)
    c = big.centroid
    if not big.buffer(-1e-4).contains(c):
        c = big.buffer(-1e-4).representative_point() if not big.buffer(-1e-4).is_empty else big.representative_point()
    return (c.x, c.y)


def refresh_derived(m, regions, old_k=None, new_regions=(), land_ratio=None, scale_of=None):
    """Recomputes u_a/u_b, center and points of 'regions' after their mesh changes.
    old_k: {region: cos_area before the change} to keep each region's own scale.
    land_ratio: {new region: u_a/u_b} (default 1 on land); scale_of: {new region: its mother's u_b/cos_area scale}."""
    R = m['regions']
    out = {}
    for r in regions:
        g = R[r]
        k = cos_area(m, r)
        if k <= 0:
            continue
        ok = (old_k or {}).get(r)
        scale = g.u_b / ok if ok and g.u_b else (scale_of or {}).get(r, AREA_K)
        ratio = (g.u_a / g.u_b) if g.u_b else (0.0 if g.u_type == SEA else (land_ratio or {}).get(r, 1.0))
        g.u_b = max(1, int(round(k * scale)))
        g.u_a = 0 if g.u_type == SEA else max(1, int(round(g.u_b * ratio)))
        poly = mesh_polygon(m, r)
        if poly.is_empty:
            continue
        inside = poly.buffer(1e-6)
        old_c = None if r in new_regions else (g.cx, g.cy)
        all_in = old_c is not None and all(inside.contains(Point(p)) for p in g.points) and inside.contains(Point(old_c))
        if not all_in:
            c = pick_center(poly, old_c)
            g.cx, g.cy = f32(c[0]), f32(c[1])
            g.points = grid_points(poly, (g.cx, g.cy))
        out[r] = poly
    return out


def delete_region(m, r):
    """Removes region r from the map; it must no longer have area (its triangles were transferred before) or borders.
    Renumbers the following regions, shapes, tables and borders."""
    R = m['regions']
    if any(s.indices for s in mhmap.region_shapes(m, r)):
        raise ValueError('%s todavia tiene area: traspasala antes de borrarla' % R[r].name)
    row = m['shape_table'][r]
    first, last = row.first, row.last
    n = last - first + 1
    # shapes de la region
    del m['shapes'][first:last + 1]
    for i, s in enumerate(m['shapes']):
        s.index = i
    del m['shape_table'][r]
    for t in m['shape_table']:
        if t.region > r:
            t.region -= 1
        if t.first > last:
            t.first -= n
            t.last -= n
            t.u_last -= n
    # tabla de bordes: fila de r fuera; indices de region posteriores bajan uno
    del m['border_table'][r]
    dead = set()
    for t in m['border_table']:
        keep = []
        for nb, bi in t.links:
            if nb == r:
                dead.add(bi)
                continue
            keep.append((nb - 1 if nb > r else nb, bi))
        t.links = keep
        if t.region > r:
            t.region -= 1
        if t.u_x > r:
            t.u_x -= 1
    # borders serving only r (there should be none): removed and the rest renumbered
    if dead:
        alive = [b for b in m['borders'] if b.index not in dead]
        remap = {b.index: i for i, b in enumerate(alive)}
        for i, b in enumerate(alive):
            b.index = i
        m['borders'] = alive
        for t in m['border_table']:
            t.links = [(nb, remap[bi]) for nb, bi in t.links if bi in remap]
    for b in m['borders']:
        if b.regions:
            b.regions = tuple(sorted(x - 1 if x > r else x for x in b.regions))
    # regiones
    del R[r]
    for i, g in enumerate(R):
        g.index = i
        g.neighbors = [x - 1 if x > r else x for x in g.neighbors if x != r]
    return n


def normalize_map(m):
    """Rules the game needs that a map made from scratch (or with regions that changed from sea to land) could break:
    counterclockwise triangles (clockwise ones the game neither draws nor lets the region be selected) and coast flag 0 on
    land-land and sea-sea borders (as in World). Returns {'triangulos': n flipped, 'costas': n stretches fixed}."""
    flipped = 0
    for s in m['shapes']:
        ix, v = s.indices, s.vertices
        for k in range(0, len(ix) - 2, 3):
            a, b, c = v[ix[k]], v[ix[k + 1]], v[ix[k + 2]]
            if (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]) < 0:
                ix[k + 1], ix[k + 2] = ix[k + 2], ix[k + 1]
                flipped += 1
    R = m['regions']
    coast = 0
    for b in m['borders']:
        if len(b.regions) != 2:
            continue
        if (R[b.regions[0]].u_type == SEA) != (R[b.regions[1]].u_type == SEA):
            continue           # land-sea: in World they may be 0, 1 or mixed; left alone
        want = 0               # tierra-tierra y mar-mar: siempre 0 en World
        segs = []
        for f, pts in b.segments:
            if f != want:
                coast += 1
            segs.append((want, pts))
        b.segments = segs
    return {'triangulos': flipped, 'costas': coast}

