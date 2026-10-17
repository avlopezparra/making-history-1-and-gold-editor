"""Ajusta las fronteras terrestres de un pais del juego a un poligono GeoJSON y anade sus islas de ultramar.

La costa del juego NO se toca: solo se mueven trozos de tierra entre las regiones del pais y las
regiones terrestres vecinas, y se anaden las islas que en el juego son mar.

Uso:
  python fit_country.py <xml mapa ORIGINAL> <pais.geojson|.map> <salida> \
        --regions Magallanes Coquimbo Atacama --island Coquimbo --island-south Magallanes:-52

  --regions       regiones del juego que forman el pais
  --island        region que recibe las islas de ultramar
  --island-south  REGION:LAT  las islas al sur de LAT van a REGION
Escribe en <salida>: regions.bin, borders.brd, regions.nts y cambios.json (lineas e islas para la textura).

Reglas que imita del mapa original (comprobadas):
  - cada borde es exactamente la cadena de aristas que comparten las mallas de sus dos regiones;
  - las mallas vecinas comparten los vertices bit a bit (sin uniones en T) y no hay pasos de longitud 0;
  - un anillo cerrado (isla) se guarda sin repetir el primer punto.
"""
import argparse
import json
import math
import os
import struct
import sys
from collections import Counter, defaultdict

from shapely import make_valid
from shapely.geometry import shape, Polygon, LineString, Point, mapping
from shapely.ops import unary_union
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap  # noqa: E402
from transfer import apply_transfers, SEA, TOUCH, MIN_PIECE  # noqa: E402
from move_border import triangulate, signed_area, MeshBuilder, EPS  # noqa: E402

ISLAND_MIN_AREA = 1e-4  # grados2 (~1 km2): Sala y Gomez queda fuera
ISLAND_MIN_DIST = 0.5   # grados desde la costa del juego para considerar una isla "de ultramar"
ISLAND_SIMPLIFY = 0.002


def load_country(path):
    j = json.load(open(path, encoding='utf-8'))
    data = j.get('data', j)
    feats = data['features'] if data.get('type') == 'FeatureCollection' else [data]
    return make_valid(unary_union([shape(f['geometry']) for f in feats]))


def polys(g):
    return [p for p in getattr(g, 'geoms', [g]) if p.geom_type == 'Polygon' and p.area > MIN_PIECE]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('country'); ap.add_argument('out')
    ap.add_argument('--regions', nargs='+', required=True)
    ap.add_argument('--island', required=True)
    ap.add_argument('--island-south', default=None)
    a = ap.parse_args()

    m = mhmap.load_map(a.src)
    R = m['regions']
    by = {g.name: g for g in R}
    country = load_country(a.country)
    C = [by[n].index for n in a.regions]
    old_borders = {tuple(sorted(b.regions)): [(f, list(p)) for f, p in b.segments] for b in m['borders']}

    cache = {}

    def P(r):
        if r not in cache:
            cache[r] = unary_union([Polygon(t) for s in mhmap.region_shapes(m, r) for t in s.triangles()
                                    if abs(signed_area(t)) > 0])
        return cache[r]

    def touch_len(piece, r):
        return piece.boundary.intersection(P(r).buffer(TOUCH)).length

    cand = {n for c in C for n in R[c].neighbors if R[n].u_type != SEA and n not in C}
    N = [n for n in cand if P(n).intersects(country)]
    print('pais:', [R[c].name for c in C], '| vecinos terrestres:', [R[n].name for n in N])

    def adds_new_coast(p, src, dst):
        """True si la pieza toca un mar con el que la region destino no tenia costa."""
        for s in R[src].neighbors:
            if R[s].u_type == SEA and s not in R[dst].neighbors and touch_len(p, s) > 1e-6:
                return True
        return False

    # ------------------------------------------------------------ piezas de tierra a mover
    transfers = []  # (pieza, origen, destino)
    skipped_coast = 0
    for n in N:
        for p in polys(P(n).intersection(country)):
            t = {c: touch_len(p, c) for c in C}
            dst = max(t, key=t.get) if max(t.values()) > 0 else min(C, key=lambda c: P(c).distance(p))
            if adds_new_coast(p, n, dst):
                skipped_coast += 1
                continue
            transfers.append((p, n, dst))
    kept_coast = 0
    for c in C:
        for p in polys(P(c).difference(country)):
            t = {n: touch_len(p, n) for n in N}
            if t and max(t.values()) > 1e-5:
                dst = max(t, key=t.get)
                if adds_new_coast(p, c, dst):
                    skipped_coast += 1
                    continue
                transfers.append((p, c, dst))
            else:
                kept_coast += 1
    print('tierra: %d piezas, %.3f grados2 | diferencias de costa ignoradas: %d | piezas costeras no movidas: %d' % (
        len(transfers), sum(p.area for p, _, _ in transfers), kept_coast, skipped_coast))
    for s in sorted({(R[x].name, R[y].name) for _, x, y in transfers}):
        print('   %s -> %s: %.4f' % (s[0], s[1], sum(p.area for p, x, y in transfers if (R[x].name, R[y].name) == s)))

    # ------------------------------------------------------------ islas de ultramar
    land_c = unary_union([P(c) for c in C])
    south = None
    if a.island_south:
        name, lat = a.island_south.split(':')
        south = (by[name].index, float(lat))
    sea_idx = [g.index for g in R if g.u_type == SEA]
    sea_tris = [(Polygon(t), s) for s in sea_idx for sh in mhmap.region_shapes(m, s) for t in sh.triangles()
                if abs(signed_area(t)) > 0]
    sea_tree = STRtree([t for t, _ in sea_tris])
    islands = []
    for p in polys(country):
        if p.area < ISLAND_MIN_AREA or p.distance(land_c) < ISLAND_MIN_DIST:
            continue
        p = p.simplify(ISLAND_SIMPLIFY, preserve_topology=True)
        rp = p.representative_point()
        sea = next(sea_tris[i][1] for i in sea_tree.query(rp) if sea_tris[i][0].covers(rp))
        dst = south[0] if south and rp.y < south[1] else by[a.island].index
        islands.append((p, dst, sea))
        transfers.append((p, sea, dst))
        print('isla %.2f,%.2f (%.4f grados2, %d puntos): %s -> %s' % (
            rp.x, rp.y, p.area, len(p.exterior.coords) - 1, R[sea].name, R[dst].name))

    erase, paint, new_pairs = apply_transfers(m, transfers, islands, P, cache)
    mhmap.save_map(m, a.out)
    mhmap.load_map(a.out)  # relectura de control
    json.dump({
        'erase': [dict(mapping(x), kind=k) for k, x in erase],
        'paint': [dict(mapping(x), kind=k) for k, x in paint],
        'islands': [mapping(p) for p, _, _ in islands],
    }, open(os.path.join(a.out, 'cambios.json'), 'w'))
    print('guardado en %s | lineas a borrar %d, a pintar %d, islas %d' % (a.out, len(erase), len(paint), len(islands)))


if __name__ == '__main__':
    main()
