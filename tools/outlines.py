"""Contornos exactos de las regiones a partir de su malla (para el editor).

region_polygons(m, r) -> lista de poligonos [[anillo exterior], [hueco], ...] con los vertices EXACTOS de la
malla (incluidos los que comparte con sus vecinas), en el formato de coordenadas de GeoJSON MultiPolygon.
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
    """Anillos cerrados (sin repetir el primer punto) del contorno de un shape."""
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
                # vertice de pinzamiento: la salida que gira mas a la izquierda respecto de la llegada
                ang_in = math.atan2(prev[1] - cur[1], prev[0] - cur[0])
                n = min(nxts, key=lambda q: (ang_in - math.atan2(q[1] - cur[1], q[0] - cur[0])) % (2 * math.pi) or 2 * math.pi)
            nxts.remove(n)
            if not nxts:
                del out[cur]
            if n == start:
                break
            if n in pos:   # el anillo se toca a si mismo: el lazo se separa como anillo propio
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
        # el exterior mas pequeno que contiene al hueco
        for i, s in enumerate(shp):
            if s.buffer(1e-9).contains(Polygon(h).representative_point()) or s.contains(p):
                polys[i].append(h)
                break
    return polys


def region_polygons(m, r):
    """MultiPolygon editable de la region. En las regiones-isla (isla + halo superpuestos) es el halo;
    los shapes cubiertos por otro shape de la misma region se devuelven aparte como detalle."""
    shapes = mhmap.region_shapes(m, r)
    per = [_polygons(shape_rings(sh)) for sh in shapes]
    main, detail = [], []
    if len(per) > 1:
        geo = [unary_union([Polygon(p[0], p[1:]) for p in ps]) if ps else None for ps in per]
        for i, ps in enumerate(per):
            covered = geo[i] is not None and any(j != i and geo[j] is not None and geo[j].buffer(1e-7).covers(geo[i])
                                                 for j in range(len(per)))
            (detail if covered else main).extend(ps)
    else:
        main = per[0] if per else []
    fmt = lambda polys: [[[list(q) for q in ring + ring[:1]] for ring in poly] for poly in polys]
    return fmt(main), fmt(detail)
