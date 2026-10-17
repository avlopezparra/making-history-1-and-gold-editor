"""Exporta el mapa de Making History a GeoJSON y PNG.

Uso: python -I export_map.py <carpeta xml del mapa> <carpeta de salida>

Genera:
  regions.geojson   un poligono por region (contorno de su malla), con nombre, tipo y vecinos
  borders.geojson   las 2405 lineas de frontera, con las dos regiones que separan
  mapa_mundo.png    mapa completo
  mapa_europa.png   recorte de Europa con nombres
Se abre en QGIS, geojson.io o cualquier visor GeoJSON.
"""
import colorsys
import hashlib
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

SEA = 0  # u_type de las zonas de mar


def ring_area(ring):
    return 0.5 * sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))


def point_in_ring(p, ring):
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def shape_rings(shape):
    """Contornos de un shape: aristas que pertenecen a un solo triangulo, encadenadas."""
    # se trabaja con coordenadas redondeadas, no con indices: la malla repite
    # vertices en la misma posicion y por indice saldrian costuras falsas
    ix = shape.indices
    key = [tuple(round(c, 4) for c in v[:2]) for v in shape.vertices]
    count = defaultdict(int)
    directed = []
    for k in range(0, len(ix), 3):
        tri = [key[i] for i in ix[k:k + 3]]
        if len(set(tri)) < 3:
            continue  # triangulo degenerado
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            count[frozenset((a, b))] += 1
            directed.append((a, b))
    nxt = {}
    for a, b in directed:
        if count[frozenset((a, b))] == 1 and a != b:
            nxt.setdefault(a, []).append(b)
    rings = []
    while nxt:
        start = next(iter(nxt))
        ring = [start]
        cur = start
        while True:
            outs = nxt.get(cur)
            if not outs:
                break
            n = outs.pop()
            if not outs:
                del nxt[cur]
            if n == start:
                break
            ring.append(n)
            cur = n
        if len(ring) >= 3:
            rings.append(ring + [ring[0]])
    return rings


def region_polygons(m, region_index):
    """MultiPolygon GeoJSON (lista de poligonos [exterior, huecos...])."""
    outers, holes = [], []
    for s in mhmap.region_shapes(m, region_index):
        for r in shape_rings(s):
            (outers if ring_area(r) > 0 else holes).append(r)
    if not outers and holes:  # winding invertido
        outers, holes = [h[::-1] for h in holes], []
    polys = [[o] for o in outers]
    for h in holes:
        for p in polys:
            if point_in_ring(h[0], p[0]):
                p.append(h)
                break
    return polys


def color_for(name, sea):
    if sea:
        return (176, 205, 228)
    h = int(hashlib.md5(name.encode('latin1')).hexdigest()[:6], 16)
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, 0.62, 0.45)
    return int(r * 255), int(g * 255), int(b * 255)


def render(m, path, lon0, lon1, lat0, lat1, ppd, labels):
    W, H = int((lon1 - lon0) * ppd), int((lat1 - lat0) * ppd)
    img = Image.new('RGB', (W, H), (150, 185, 215))
    dr = ImageDraw.Draw(img)
    px = lambda x, y: ((x - lon0) * ppd, (lat1 - y) * ppd)
    for g in m['regions']:
        col = color_for(g.name, g.u_type == SEA)
        for s in mhmap.region_shapes(m, g.index):
            for tri in s.triangles():
                xs = [p[0] for p in tri]
                if max(xs) < lon0 or min(xs) > lon1:
                    continue
                dr.polygon([px(*p) for p in tri], fill=col)
    for b in m['borders']:
        a, c = (m['regions'][i] for i in b.regions)
        land = SEA not in (a.u_type, c.u_type)
        for _, pts in b.segments:
            if len(pts) > 1:
                dr.line([px(*p) for p in pts], fill=(60, 60, 60) if land else (120, 140, 160),
                        width=2 if land and ppd >= 20 else 1)
    if labels:
        try:
            font = ImageFont.truetype('arial.ttf', max(10, int(ppd * 0.45)))
        except OSError:
            font = ImageFont.load_default()
        for g in m['regions']:
            if lon0 <= g.cx <= lon1 and lat0 <= g.cy <= lat1:
                x, y = px(g.cx, g.cy)
                dr.text((x, y), g.name, fill=(20, 20, 20) if g.u_type != SEA else (40, 70, 110),
                        font=font, anchor='mm', stroke_width=2, stroke_fill=(255, 255, 255))
    img.save(path, optimize=True)
    return W, H


def main(src, out):
    os.makedirs(out, exist_ok=True)
    m = mhmap.load_map(src)
    R = m['regions']

    feats = []
    for g in R:
        feats.append({
            'type': 'Feature',
            'properties': {
                'index': g.index, 'name': g.name, 'type': g.u_type, 'sea': g.u_type == SEA,
                'center': [round(g.cx, 4), round(g.cy, 4)],
                'neighbors': [R[n].name for n in g.neighbors if n != g.index],
            },
            'geometry': {'type': 'MultiPolygon', 'coordinates': region_polygons(m, g.index)},
        })
    with open(os.path.join(out, 'regions.geojson'), 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': feats}, f, ensure_ascii=False)

    bfeats = []
    for b in m['borders']:
        a, c = b.regions
        bfeats.append({
            'type': 'Feature',
            'properties': {'index': b.index, 'region_a': R[a].name, 'region_b': R[c].name},
            'geometry': {'type': 'MultiLineString',
                         'coordinates': [[[round(x, 5), round(y, 5)] for x, y in pts] for _, pts in b.segments]},
        })
    with open(os.path.join(out, 'borders.geojson'), 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': bfeats}, f, ensure_ascii=False)

    print('mundo', render(m, os.path.join(out, 'mapa_mundo.png'), -180, 180, -60, 85, 12, False))
    print('europa', render(m, os.path.join(out, 'mapa_europa.png'), -12, 45, 34, 66, 40, True))
    for n in ('regions.geojson', 'borders.geojson', 'mapa_mundo.png', 'mapa_europa.png'):
        print('%-16s %6.1f MB' % (n, os.path.getsize(os.path.join(out, n)) / 1e6))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
