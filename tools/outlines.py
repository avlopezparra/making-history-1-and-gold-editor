"""Exact region outlines from their mesh (for the editor).

region_polygons(m, r) -> list of polygons [[outer ring], [hole], ...] with the EXACT vertices of the
mesh (including those shared with its neighbors), in GeoJSON MultiPolygon coordinate format.
"""
import math
import os
import sys
from collections import defaultdict

from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap  # noqa: E402


def _area2(t):
    (x1, y1), (x2, y2), (x3, y3) = t
    return (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)


def ring_area(ring):
    return 0.5 * sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))


def shape_rings(sh):
    """Closed rings (without repeating the first point) of a shape's outline."""
    count = defaultdict(int)
    directed = []
    if True:
        v = [x[:2] for x in sh.vertices]
        ix = sh.indices
        for k in range(0, len(ix), 3):
            t = [v[i] for i in ix[k:k + 3]]
            if len(set(t)) < 3:
                continue
            a2 = _area2(t)
            if a2 == 0:
                continue
            if a2 < 0:
                t = [t[0], t[2], t[1]]   # todos en sentido antihorario
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                count[frozenset((a, b))] += 1
                directed.append((a, b))
    out = defaultdict(list)
    for a, b in directed:
        if count[frozenset((a, b))] == 1:
            out[a].append(b)
    rings = []
    while out:
        start = next(iter(out))
        ring = [start]
        pos = {start: 0}
        prev, cur = None, start
        while True:
            nxts = out.get(cur)
            if not nxts:
                break
            if len(nxts) == 1 or prev is None:
                n = nxts[0]
            else:
                # pinch vertex: the exit turning furthest left relative to the arrival
                ang_in = math.atan2(prev[1] - cur[1], prev[0] - cur[0])
                n = min(nxts, key=lambda q: (ang_in - math.atan2(q[1] - cur[1], q[0] - cur[0])) % (2 * math.pi) or 2 * math.pi)
            nxts.remove(n)
            if not nxts:
                del out[cur]
            if n == start:
                break
            if n in pos:   # the ring touches itself: the loop is split off as its own ring
                j = pos[n]
                loop = ring[j:]
                if len(loop) >= 3:
                    rings.append(loop)
                for q in loop[1:]:
                    pos.pop(q, None)
                ring = ring[:j + 1]
                prev, cur = ring[-2] if len(ring) > 1 else None, n
                continue
            pos[n] = len(ring)
            ring.append(n)
            prev, cur = cur, n
        if len(ring) >= 3:
            rings.append(ring)
    return rings


def _polygons(rings):
    rings = [x for x in rings if abs(ring_area(x)) > 1e-10]     # bucles de area cero (cadenas de puntos alineados recorridas ida y vuelta)
    outers = [x for x in rings if ring_area(x) > 0]
    holes = [x for x in rings if ring_area(x) < 0]
    polys = [[o] for o in sorted(outers, key=ring_area)]
    shp = [Polygon(o) for o, in polys]
    for h in holes:
        p = Point(h[0])
        # the smallest exterior containing the hole
        for i, s in enumerate(shp):
            if s.buffer(1e-9).contains(Polygon(h).representative_point()) or s.contains(p):
                polys[i].append(h)
                break
    return polys


def region_polygons(m, r):
    """Editable MultiPolygon of the region. In island regions (overlapping island + halo) it is the halo;
    shapes covered by another shape of the same region are returned separately as detail."""
    shapes = mhmap.region_shapes(m, r)
    per = [_polygons(shape_rings(sh)) for sh in shapes]
    main, detail = [], []
    if len(per) > 1:
        geo = [[Polygon(p[0], p[1:]) for p in ps] for ps in per]
        cov = [[g.buffer(1e-7) for g in gs] for gs in geo]
        for i, ps in enumerate(per):
            for k, p in enumerate(ps):      # per polygon: a shape with the island under its halo and another separate island (Mauritius + an imported island)
                g = geo[i][k]
                # detail = covered by a LARGER polygon of another shape; if equal (duplicated mesh) the main one kept is that of the
                # first shape (previously both became detail and the editable outline was reduced to a crumb)
                covered = any(j != i and (q.area > g.area * (1 + 1e-6) or j < i) and c.covers(g)
                              for j in range(len(per)) for q, c in zip(geo[j], cov[j]))
                (detail if covered else main).append(p)
    else:
        main = per[0] if per else []
    fmt = lambda polys: [[[list(q) for q in ring + ring[:1]] for ring in poly] for poly in polys]
    return fmt(main), fmt(detail)
