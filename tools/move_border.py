"""Pasa a otra region el territorio de una region que queda al oeste (o este) de una linea KML.

Uso:
  python move_border.py <carpeta xml del mapa> <archivo.kml> "<nombre de la linea>" \
         <region origen> <region destino> <west|east> <carpeta salida>

Ejemplo (Campo de Hielo Sur):
  python move_border.py ".../Maps/World/xml" hielo.kml "Traza en base a los hitos de 1898" \
         Patagonia Magallanes west ../mapa_mod

Que cambia:
  regions.nts  los triangulos de la region origen que cruzan la linea se recortan; la parte del lado
               indicado pasa a la malla de la region destino. El resto de la malla no cambia.
  borders.brd  el borde entre ambas regiones se rehace en el tramo afectado.
  regions.bin  sin cambios (centro, vecinos y puntos de la region siguen valiendo para un ajuste pequeno).
Requiere que las dos regiones ya sean vecinas y que el trozo movido solo toque a la region destino.
"""
import os
import sys
import xml.etree.ElementTree as ET

import shapely
from shapely.geometry import LineString, Polygon, MultiLineString
from shapely.ops import linemerge, unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap  # noqa: E402

KML = '{http://www.opengis.net/kml/2.2}'
EPS = 1e-9


def kml_line(path, name_prefix):
    for pm in ET.parse(path).iter(KML + 'Placemark'):
        name = (pm.findtext(KML + 'name') or '').strip()
        if name.startswith(name_prefix):
            c = pm.find('.//' + KML + 'LineString/' + KML + 'coordinates')
            if c is not None:
                return name, [tuple(map(float, p.split(',')[:2])) for p in c.text.split()]
    raise SystemExit('no encuentro la linea "%s" en el KML' % name_prefix)


def side_polygon(line, side):
    """Poligono que cubre el lado 'west'/'east' de la linea, entre su latitud inicial y final."""
    far = (min(p[0] for p in line) - 5) if side == 'west' else (max(p[0] for p in line) + 5)
    ring = list(line) + [(far, line[-1][1]), (far, line[0][1])]
    poly = Polygon(ring)
    return poly if poly.is_valid else poly.buffer(0)


def signed_area(tri):
    (x1, y1), (x2, y2), (x3, y3) = tri
    return (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)


def triangulate(geom):
    """Triangulos (lista de 3 puntos) que cubren exactamente un (Multi)Polygon."""
    out = []
    for poly in getattr(geom, 'geoms', [geom]):
        if poly.geom_type != 'Polygon' or poly.area < EPS:
            continue
        for t in shapely.constrained_delaunay_triangles(poly).geoms:
            if t.area > EPS:
                out.append(list(t.exterior.coords)[:3])
    return out


class MeshBuilder:
    """Anade triangulos a un shape conservando sus vertices originales."""

    def __init__(self, shape, winding):
        self.shape = shape
        self.winding = winding
        self.lookup = {v[:2]: i for i, v in enumerate(shape.vertices)}
        self.indices = []

    def vid(self, p):
        p = (p[0], p[1])
        if p not in self.lookup:
            self.lookup[p] = len(self.shape.vertices)
            self.shape.vertices.append((p[0], p[1], 0.0, 0.0, 0.0, 1.0))
        return self.lookup[p]

    def add(self, tri):
        if (signed_area(tri) > 0) != self.winding:
            tri = [tri[0], tri[2], tri[1]]
        self.indices += [self.vid(p) for p in tri]


def main(src, kml_path, line_name, from_name, to_name, side, out):
    m = mhmap.load_map(src)
    R = m['regions']
    by = {g.name: g for g in R}
    a, b = by[from_name], by[to_name]
    if b.index not in a.neighbors:
        raise SystemExit('%s y %s no son vecinas' % (from_name, to_name))
    (sa,), (sb,) = mhmap.region_shapes(m, a.index), mhmap.region_shapes(m, b.index)

    name, line = kml_line(kml_path, line_name)
    cut = side_polygon(line, side)
    print('linea: %s (%d puntos)' % (name, len(line)))

    tris_a = sa.triangles()
    winding = sum(signed_area(t) > 0 for t in tris_a) * 2 > len(tris_a)
    poly_a_old = unary_union([Polygon(t) for t in tris_a if abs(signed_area(t)) > 0])

    keep, moved, n_split = [], [], 0
    for t in tris_a:
        tp = Polygon(t)
        if tp.area < EPS or not tp.intersects(cut) or tp.intersection(cut).area < EPS:
            keep.append(t)
        elif cut.contains(tp):
            moved.append(t)
        else:
            n_split += 1
            keep += triangulate(tp.difference(cut))
            moved += triangulate(tp.intersection(cut))
    moved_area = unary_union([Polygon(t) for t in moved])
    print('triangulos de %s: %d -> %d (recortados %d) | pasan a %s: %d triangulos, %.4f grados2' % (
        from_name, len(tris_a), len(keep), n_split, to_name, len(moved), moved_area.area))
    if not moved:
        raise SystemExit('la linea no deja territorio de %s del lado %s' % (from_name, side))

    # el trozo movido no puede tocar a otros vecinos de la region origen
    for n in a.neighbors:
        if n in (a.index, b.index):
            continue
        other = unary_union([Polygon(t) for s in mhmap.region_shapes(m, n) for t in s.triangles() if abs(signed_area(t)) > 0])
        d = other.distance(moved_area)
        if d < 1e-6:
            raise SystemExit('el trozo movido toca a %s; no se hace el cambio' % R[n].name)

    # mallas: origen = triangulos conservados; destino = los suyos + los movidos
    mb_a = MeshBuilder(sa, winding)
    for t in keep:
        mb_a.add(t)
    sa.indices = mb_a.indices
    mb_b = MeshBuilder(sb, winding)
    mb_b.indices = list(sb.indices)
    for t in moved:
        mb_b.add(t)
    sb.indices = mb_b.indices

    # borde entre ambas regiones: tramos fuera del corte + el contorno del corte dentro de la region
    # origen (la linea KML y los cierres en sus extremos)
    border = next(x for x in m['borders'] if set(x.regions) == {a.index, b.index})
    new_line = cut.boundary.intersection(poly_a_old)
    segs = []
    for flag, pts in border.segments:
        ls = LineString(pts) if len(pts) > 1 else None
        if ls is None or not ls.intersects(cut):
            segs.append((flag, pts))
            continue
        rest = ls.difference(cut)
        merged = linemerge(unary_union([shapely.snap(rest, new_line, 1e-6), shapely.snap(new_line, rest, 1e-6)]))
        parts = merged.geoms if isinstance(merged, MultiLineString) else [merged]
        for p in parts:
            coords = [(x, y) for x, y in p.coords]
            if len(coords) > 1:
                segs.append((flag, coords))
    print('borde %d: %d tramos -> %d tramos' % (border.index, len(border.segments), len(segs)))
    border.segments = segs

    mhmap.save_map(m, out)
    check = mhmap.load_map(out)  # se relee para validar el resultado
    print('guardado en %s y releido: %d regiones, %d bordes, %d shapes' % (
        out, len(check['regions']), len(check['borders']), len(check['shapes'])))


if __name__ == '__main__':
    if len(sys.argv) != 8:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
