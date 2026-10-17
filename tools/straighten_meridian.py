"""Endereza el final de una frontera que sigue un meridiano: lo prolonga recto hasta la costa.

Toma el meridiano (longitud mas repetida de los puntos casi verticales del borde entre dos regiones) y, entre
la latitud donde termina el tramo recto y la costa, pasa a WEST todo lo que este al oeste del meridiano y a
EAST lo que este al este.

Uso: python straighten_meridian.py <xml mapa> <salida> <region oeste> <region este> <lat aprox del extremo>
Ejemplo (Tierra del Fuego, Cabo del Espiritu Santo):
  python straighten_meridian.py ../mapa_chile2 ../mapa_chile2b Magallanes Patagonia -52.63
"""
import json
import os
import sys
from collections import Counter

from shapely.geometry import Polygon, box, mapping
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap  # noqa: E402
from move_border import signed_area  # noqa: E402
from transfer import apply_transfers  # noqa: E402

WINDOW = 0.3   # grados alrededor del extremo que se consideran
REACH = 0.2    # grados a cada lado del meridiano
UP = 0.05      # grados por encima del final del tramo recto (hasta la costa)


def main(src, out, west_name, east_name, lat_end):
    lat_end = float(lat_end)
    m = mhmap.load_map(src)
    R = m['regions']
    by = {g.name: g.index for g in R}
    W, E = by[west_name], by[east_name]
    cache = {}

    def P(r):
        if r not in cache:
            cache[r] = unary_union([Polygon(t) for s in mhmap.region_shapes(m, r) for t in s.triangles()
                                    if abs(signed_area(t)) > 0])
        return cache[r]

    b = next(x for x in m['borders'] if set(x.regions) == {W, E})
    pts = [p for f, s in b.segments for p in s if abs(p[1] - lat_end) < WINDOW]
    # segmentos casi verticales -> longitud del meridiano
    xs = Counter()
    for f, s in b.segments:
        for p, q in zip(s, s[1:]):
            if abs(p[1] - lat_end) < WINDOW and abs(p[0] - q[0]) < 1e-3 and abs(p[1] - q[1]) > 1e-3:
                xs[round((p[0] + q[0]) / 2, 4)] += abs(p[1] - q[1])
    x0 = max(xs, key=xs.get)
    straight = [p for p in pts if abs(p[0] - x0) < 2e-3]
    top = max(p[1] for p in straight)
    print('meridiano %.4f, tramo recto hasta latitud %.4f' % (x0, top))

    hi = top + UP
    west_box = box(x0 - REACH, top, x0, hi)
    east_box = box(x0, top, x0 + REACH, hi)
    transfers = []
    for g in [P(E).intersection(west_box)]:
        transfers += [(p, E, W) for p in getattr(g, 'geoms', [g]) if p.geom_type == 'Polygon' and p.area > 1e-9]
    for g in [P(W).intersection(east_box)]:
        transfers += [(p, W, E) for p in getattr(g, 'geoms', [g]) if p.geom_type == 'Polygon' and p.area > 1e-9]
    for p, s, d in transfers:
        print('  %s -> %s: %.6f grados2' % (R[s].name, R[d].name, p.area))
    if not transfers:
        raise SystemExit('nada que enderezar')
    erase, paint, new_pairs = apply_transfers(m, transfers, [], P, cache)
    mhmap.save_map(m, out)
    mhmap.load_map(out)
    json.dump({'erase': [dict(mapping(x), kind=k) for k, x in erase],
               'paint': [dict(mapping(x), kind=k) for k, x in paint], 'islands': []},
              open(os.path.join(out, 'cambios.json'), 'w'))
    print('guardado en %s | lineas a borrar %d, a pintar %d' % (out, len(erase), len(paint)))


if __name__ == '__main__':
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
