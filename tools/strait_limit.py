"""Fija el limite oriental del estrecho de Magallanes: recta Punta Dungeness - Cabo del Espiritu Santo.

Los extremos son los vertices exactos donde se juntan Patagonia, Magallanes y Argentine Sea a cada lado
de la boca (donde la frontera terrestre chileno-argentina toca la costa). Todo el mar de Argentine Sea al
oeste de esa recta pasa a Strait of Magellan. Si despues Patagonia tocara el estrecho, se avisa.

Uso: python strait_limit.py <xml mapa> <salida>
Escribe regions.bin, borders.brd, regions.nts y cambios.json (lineas para paint_changes.py).
"""
import json
import math
import os
import sys

from shapely.geometry import Polygon, LineString, mapping
from shapely.ops import unary_union, split

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap  # noqa: E402
from move_border import signed_area  # noqa: E402
from transfer import apply_transfers, boundary_edges  # noqa: E402

LAND_A, LAND_B, OUTER, INNER = 'Patagonia', 'Magallanes', 'Argentine Sea', 'Strait of Magellan'
NORTH_APPROX = (-68.43, -52.39)   # Punta Dungeness
SOUTH_APPROX = (-68.61, -52.66)   # Cabo del Espiritu Santo
INSIDE = (-69.0, -52.5)           # un punto de agua dentro del estrecho
BAND = 0.012                      # grados (~1,3 km) de costa argentina que pasa a Chile


def main(src, out):
    m = mhmap.load_map(src)
    R = m['regions']
    by = {g.name: g.index for g in R}
    cache = {}

    def P(r):
        if r not in cache:
            cache[r] = unary_union([Polygon(t) for s in mhmap.region_shapes(m, r) for t in s.triangles()
                                    if abs(signed_area(t)) > 0])
        return cache[r]

    def bverts(r):
        tris = [tuple(map(tuple, t)) for s in mhmap.region_shapes(m, r) for t in s.triangles()]
        return {v for e in boundary_edges(tris) for v in e}

    triple = bverts(by[LAND_A]) & bverts(by[LAND_B]) & bverts(by[OUTER])
    j1 = min(triple, key=lambda v: math.dist(v, NORTH_APPROX))
    j2 = min(triple, key=lambda v: math.dist(v, SOUTH_APPROX))
    print('Dungeness: %.4f, %.4f (a %.3f grados del aproximado)' % (j1[0], j1[1], math.dist(j1, NORTH_APPROX)))
    print('Espiritu Santo: %.4f, %.4f (a %.3f grados del aproximado)' % (j2[0], j2[1], math.dist(j2, SOUTH_APPROX)))

    # recta prolongada un poco hacia tierra para que corte el mar de lado a lado
    dx, dy = j2[0] - j1[0], j2[1] - j1[1]
    L = math.hypot(dx, dy)
    ext = 0.05 / L
    cutter = LineString([(j1[0] - dx * ext, j1[1] - dy * ext), (j2[0] + dx * ext, j2[1] + dy * ext)])
    outer = P(by[OUTER])
    pieces = [p for p in split(outer, cutter).geoms if p.area > 1e-9]
    # pieza(s) del lado del estrecho (mismo lado que INSIDE) que tocan Strait of Magellan
    side = lambda p: (p.representative_point().x - j1[0]) * dy - (p.representative_point().y - j1[1]) * dx
    moved = [p for p in pieces if side(p) * ((INSIDE[0] - j1[0]) * dy - (INSIDE[1] - j1[1]) * dx) > 0
             and p.intersects(P(by[INNER]).buffer(1e-6))]
    if not moved:
        raise SystemExit('no encuentro el mar de %s dentro del estrecho' % OUTER)
    area = sum(p.area for p in moved)
    print('%s -> %s: %d pieza(s), %.4f grados2' % (OUTER, INNER, len(moved), area))
    transfers = [(p, by[OUTER], by[INNER]) for p in moved]

    # la costa argentina que da a ese mar pasa a Chile (franja de BAND grados), para que Argentina no toque el estrecho
    water = unary_union(moved)
    coast = P(by[LAND_A]).boundary.intersection(water.buffer(1e-6))
    coast_lines = [g for g in getattr(coast, 'geoms', [coast]) if g.geom_type in ('LineString', 'MultiLineString') and g.length > 1e-6]
    if coast_lines:
        band = unary_union([g.buffer(BAND, cap_style=2) for g in coast_lines]).intersection(P(by[LAND_A]))
        band_polys = [p for p in getattr(band, 'geoms', [band]) if p.geom_type == 'Polygon' and p.area > 1e-9]
        print('costa de %s sobre el estrecho: %.4f grados -> franja de %.5f grados2 pasa a %s' % (
            LAND_A, sum(g.length for g in coast_lines), sum(p.area for p in band_polys), LAND_B))
        transfers += [(p, by[LAND_A], by[LAND_B]) for p in band_polys]

    erase, paint, new_pairs = apply_transfers(m, transfers, [], P, cache)
    print('vecindades nuevas:', [(R[x].name, R[y].name) for x, y in new_pairs])
    for land in (LAND_A,):
        if by[INNER] in R[by[land]].neighbors:
            print('AVISO: %s toca %s' % (land, INNER))
        else:
            print('%s no toca %s' % (land, INNER))
    mhmap.save_map(m, out)
    mhmap.load_map(out)
    json.dump({
        'erase': [dict(mapping(x), kind=k) for k, x in erase],
        'paint': [dict(mapping(x), kind=k) for k, x in paint],
        'islands': [],
    }, open(os.path.join(out, 'cambios.json'), 'w'))
    print('guardado en %s | lineas a borrar %d, a pintar %d' % (out, len(erase), len(paint)))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
