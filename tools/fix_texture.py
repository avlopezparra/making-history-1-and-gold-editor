"""Repinta la frontera dibujada en las texturas del terreno despues de mover un borde.

El juego tiene las fronteras pintadas en OperationalTerrain-CC-RR.tga (DXT5 en bruto, sin cabecera;
1024x1024 y mipmaps -01..-04 de 512 a 64). Cada tile cubre 15x15 grados: columna CC desde -180 de
longitud, fila RR desde +105 de latitud hacia el sur.

Este script:
  1. borra la linea antigua en el tramo que paso de una region a otra (relleno desde los bordes),
  2. pinta la linea nueva (la linea KML dentro de la region origen) con el color de la original,
  3. recomprime SOLO los bloques 4x4 que cambian, en el tile y en sus 4 mipmaps.

Uso:
  python fix_texture.py <xml mapa ORIGINAL> <carpeta art del juego> <archivo.kml> "<linea>" \
         <region origen> <region destino> <west|east> <carpeta salida>
"""
import io
import os
import sys

from PIL import Image, ImageDraw, ImageFilter
from shapely.geometry import LineString, Polygon
from shapely.ops import linemerge, unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap  # noqa: E402
from move_border import kml_line, side_polygon, signed_area  # noqa: E402

TILE_DEG = 15.0
SIZE = 1024
MIPS = 4
ERASE_WIDTH = 13     # px a 1024: la linea original oscurece hasta +-4 px de su centro
LINE_WIDTH = 3.0     # px a 1024, antes de difuminar
LINE_BLUR = 1.0      # perfil medido en el original: centro ~23, +-1 ~33, +-2 ~57, +-3 ~77, fondo ~95
LINE_COLOR = (26, 18, 10)  # nucleo medido de las lineas originales


def tile_name(c, r, mip=0):
    return 'OperationalTerrain-%02d-%02d%s.tga' % (c, r, '-%02d' % mip if mip else '')


def decode(data, size):
    return Image.frombytes('RGBA', (size, size), data, 'bcn', 3)


def encode_blocks(img):
    b = io.BytesIO()
    img.save(b, 'DDS', pixel_format='DXT5')
    return b.getvalue()[128:]


def splice(orig_bytes, new_img, old_img, size):
    """Recomprime los bloques 4x4 cuyo contenido cambio y los inserta en los bytes originales."""
    nb = size // 4
    out = bytearray(orig_bytes)
    changed = []
    for by in range(nb):
        for bx in range(nb):
            box = (bx * 4, by * 4, bx * 4 + 4, by * 4 + 4)
            if new_img.crop(box).tobytes() != old_img.crop(box).tobytes():
                changed.append((bx, by))
    if not changed:
        return bytes(out), 0
    x0 = min(c[0] for c in changed); x1 = max(c[0] for c in changed) + 1
    y0 = min(c[1] for c in changed); y1 = max(c[1] for c in changed) + 1
    region = encode_blocks(new_img.crop((x0 * 4, y0 * 4, x1 * 4, y1 * 4)))
    w = x1 - x0
    for bx, by in changed:
        k = ((by - y0) * w + (bx - x0)) * 16
        o = (by * nb + bx) * 16
        out[o:o + 16] = region[k:k + 16]
    return bytes(out), len(changed)


def inpaint(img, mask):
    """Relleno por capas desde el borde del hueco (media de vecinos conocidos)."""
    px = img.load()
    mk = mask.load()
    w, h = img.size
    todo = {(x, y) for y in range(h) for x in range(w) if mk[x, y]}
    while todo:
        ready = {}
        for x, y in todo:
            acc = [0, 0, 0, 0]
            n = 0
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, y + dy)
                    if (dx or dy) and 0 <= q[0] < w and 0 <= q[1] < h and q not in todo:
                        p = px[q]
                        acc = [a + b for a, b in zip(acc, p)]
                        n += 1
            if n:
                ready[(x, y)] = tuple(int(a / n + 0.5) for a in acc)
        if not ready:
            break
        for q, v in ready.items():
            px[q] = v
        todo -= set(ready)


def lines_of(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == 'LineString':
        return [list(geom.coords)]
    return [list(g.coords) for g in getattr(geom, 'geoms', []) if g.geom_type == 'LineString']


def main(src_xml, art, kml_path, line_name, from_name, to_name, side, out):
    m = mhmap.load_map(src_xml)
    by = {g.name: g for g in m['regions']}
    a, b = by[from_name], by[to_name]
    _, line = kml_line(kml_path, line_name)
    cut = side_polygon(line, side)
    poly_a = unary_union([Polygon(t) for s in mhmap.region_shapes(m, a.index)
                          for t in s.triangles() if abs(signed_area(t)) > 0])
    border = next(x for x in m['borders'] if set(x.regions) == {a.index, b.index})
    old = [p for _, pts in border.segments if len(pts) > 1
           for p in lines_of(LineString(pts).intersection(cut))]
    new = lines_of(linemerge(cut.boundary.intersection(poly_a)))

    lons = [x for l in old + new for x, _ in l]
    lats = [y for l in old + new for _, y in l]
    c, r = int((min(lons) + 180) // TILE_DEG), int((105 - max(lats)) // TILE_DEG)
    c2, r2 = int((max(lons) + 180) // TILE_DEG), int((105 - min(lats)) // TILE_DEG)
    if (c, r) != (c2, r2):
        raise SystemExit('el cambio cruza varios tiles; no soportado todavia')
    lon0, lat0 = -180 + c * TILE_DEG, 105 - r * TILE_DEG
    to_px = lambda x, y, s=1.0: ((x - lon0) / TILE_DEG * SIZE * s, (lat0 - y) / TILE_DEG * SIZE * s)

    base_bytes = open(os.path.join(art, tile_name(c, r)), 'rb').read()
    orig = decode(base_bytes, SIZE)
    img = orig.copy()

    # color de la linea original: lo mas oscuro sobre su trazado
    samples = sorted(orig.getpixel((int(px), int(py))) for l in old for px, py in (to_px(*p) for p in l)
                     if 0 <= px < SIZE and 0 <= py < SIZE)
    dark = sorted(samples, key=lambda p: sum(p[:3]))[:max(1, len(samples) // 4)]
    color = tuple(sum(p[i] for p in dark) // len(dark) for i in range(3))

    # 1. borrar
    mask = Image.new('1', (SIZE, SIZE), 0)
    dm = ImageDraw.Draw(mask)
    for l in old:
        dm.line([to_px(*p) for p in l], fill=1, width=ERASE_WIDTH, joint='curve')
        for p in l:
            x, y = to_px(*p)
            dm.ellipse((x - ERASE_WIDTH / 2, y - ERASE_WIDTH / 2, x + ERASE_WIDTH / 2, y + ERASE_WIDTH / 2), fill=1)
    bb = mask.getbbox()
    pad = 4
    box = (max(0, bb[0] - pad), max(0, bb[1] - pad), min(SIZE, bb[2] + pad), min(SIZE, bb[3] + pad))
    patch, pmask = img.crop(box), mask.crop(box)
    inpaint(patch, pmask)
    patch = Image.composite(patch.filter(ImageFilter.GaussianBlur(1.2)), patch, pmask.convert('L').filter(ImageFilter.GaussianBlur(1)))
    img.paste(patch, box[:2])

    # 2. pintar la linea nueva (supermuestreo x4 para suavizar)
    S = 4
    lm = Image.new('L', (SIZE * S, SIZE * S), 0)
    dl = ImageDraw.Draw(lm)
    for l in new:
        dl.line([to_px(*p, S) for p in l], fill=255, width=int(LINE_WIDTH * S), joint='curve')
    lm = lm.resize((SIZE, SIZE), Image.LANCZOS).filter(ImageFilter.GaussianBlur(LINE_BLUR)).point(lambda v: min(255, int(v * 1.2)))
    img = Image.composite(Image.new('RGBA', (SIZE, SIZE), LINE_COLOR + (255,)), img, lm)

    os.makedirs(out, exist_ok=True)
    new_bytes, n0 = splice(base_bytes, img, orig, SIZE)
    open(os.path.join(out, tile_name(c, r)), 'wb').write(new_bytes)
    print('tile %s: color de linea %s, bloques recomprimidos %d de %d' % (tile_name(c, r), color, n0, (SIZE // 4) ** 2))

    # 3. mipmaps: original + (reducir(nuevo) - reducir(original)), solo donde cambia
    for k in range(1, MIPS + 1):
        s = SIZE >> k
        mb = open(os.path.join(art, tile_name(c, r, k)), 'rb').read()
        mo = decode(mb, s)
        dn, do = img.resize((s, s), Image.BOX), orig.resize((s, s), Image.BOX)
        mn = mo.copy()
        pn, po, pm, pd = dn.load(), do.load(), mn.load(), mo.load()
        for y in range(s):
            for x in range(s):
                if pn[x, y] != po[x, y]:
                    pm[x, y] = tuple(max(0, min(255, pd[x, y][i] + pn[x, y][i] - po[x, y][i])) for i in range(4))
        nb, n = splice(mb, mn, mo, s)
        open(os.path.join(out, tile_name(c, r, k)), 'wb').write(nb)
        print('mip %d (%dx%d): bloques recomprimidos %d' % (k, s, s, n))

    # vista previa antes / despues
    x0, y0 = to_px(min(lons), max(lats))
    x1, y1 = to_px(max(lons), min(lats))
    box = (int(x0) - 80, int(y0) - 60, int(x1) + 80, int(y1) + 60)
    a_img, b_img = orig.crop(box).convert('RGB'), img.crop(box).convert('RGB')
    w, h = a_img.size
    prev = Image.new('RGB', (w * 2 + 10, h), (255, 255, 255))
    prev.paste(a_img, (0, 0))
    prev.paste(b_img, (w + 10, 0))
    prev = prev.resize((prev.width * 3, prev.height * 3), Image.NEAREST)
    prev.save(os.path.join(out, 'preview_textura.png'))
    print('vista previa:', os.path.join(out, 'preview_textura.png'))


if __name__ == '__main__':
    if len(sys.argv) != 9:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
