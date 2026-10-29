"""Aplica a las texturas del terreno los cambios de cambios.json (de fit_country.py).

  erase    lineas de frontera viejas que quedaron dentro de una region: se borran
  paint    lineas de frontera nuevas: se pintan con el color de las originales
  islands  islas nuevas: tierra arenosa con halo de aguas someras, como Bermudas
  unring   polígonos de regiones isla: se quita el contorno oscuro pegado a la costa (la línea va por el polígono)

Trabaja en todos los tiles afectados (DXT5 en bruto, ver MAPA_FORMATO.md) y sus 4 mipmaps,
recomprimiendo solo los bloques 4x4 que cambian.

Uso:
  python paint_changes.py <cambios.json> <art OperationalTerrain del juego> <salida> [--originals DIR]
  --originals  carpeta con copias originales de tiles ya modificados en el juego (se usan antes que los del juego)
"""
import argparse
import json
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter
from shapely.geometry import shape, box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_texture import (decode, splice, inpaint, tile_name, SIZE, MIPS,  # noqa: E402
                         ERASE_WIDTH, LINE_WIDTH, LINE_BLUR, LINE_COLOR)

TILE_DEG = 15.0
LAND = (222, 204, 160)      # arena, como Bermudas
SHALLOW = (176, 184, 205)   # halo de aguas someras
SEA_LINE_COLOR = (3, 14, 42)  # nucleo medido de las lineas entre zonas de mar
MARGIN = 0.3                # grados alrededor de cada tile para no cortar lineas en los bordes
S = 4                       # supermuestreo para las lineas


def tile_bounds(c, r):
    lon0, lat0 = -180 + c * TILE_DEG, 105 - r * TILE_DEG
    return lon0, lat0


def tiles_for(geoms):
    out = set()
    for g in geoms:
        x0, y0, x1, y1 = g.bounds
        for c in range(int((x0 - MARGIN + 180) // TILE_DEG), int((x1 + MARGIN + 180) // TILE_DEG) + 1):
            for r in range(int((105 - y1 - MARGIN) // TILE_DEG), int((105 - y0 + MARGIN) // TILE_DEG) + 1):
                if 0 <= c < 24 and 0 <= r < 13:
                    out.add((c, r))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('changes'); ap.add_argument('art'); ap.add_argument('out')
    ap.add_argument('--originals', default=None)
    a = ap.parse_args()
    paint_tiles(json.load(open(a.changes)), a.art, a.out, a.originals)


RING = 7          # ancho (px) de la franja exterior de la tierra donde está el contorno oscuro


def _unring(img, polys, to_px):
    """Quita el contorno oscuro (y su resplandor gris) que rodea la costa de las islas dentro de 'polys'."""
    zone = Image.new('L', (SIZE, SIZE), 0)
    dz = ImageDraw.Draw(zone)
    for g in polys:
        for poly in getattr(g, 'geoms', [g]):
            dz.polygon([to_px(*q) for q in poly.exterior.coords], fill=255)
    if not zone.getbbox():
        return img
    rgb = img.convert('RGB')
    px, pz = rgb.load(), zone.load()
    x0, y0, x1, y1 = zone.getbbox()
    seas = [px[x, y] for y in range(y0, y1, 3) for x in range(x0, x1, 3) if pz[x, y] and px[x, y][2] > px[x, y][0] + 60]
    if not seas:
        return img
    sea = tuple(sorted(v[i] for v in seas)[len(seas) // 2] for i in range(3))
    far = lambda v: sum((v[i] - sea[i]) ** 2 for i in range(3)) > 12 ** 2
    blob = Image.new('L', (SIZE, SIZE), 0)
    pb = blob.load()
    for y in range(y0, y1):
        for x in range(x0, x1):
            if pz[x, y] and far(px[x, y]):
                pb[x, y] = 255
    core = blob.filter(ImageFilter.MinFilter(2 * RING + 1))
    pc = core.load()
    out = img.copy()
    po = out.load()
    for y in range(y0, y1):
        for x in range(x0, x1):
            if pb[x, y] and not pc[x, y]:
                v = px[x, y]
                # oscuro o gris azulado: contorno; lo claro (nieve, arena), lo verde y lo pardo (tierra) quedan
                if 0.3 * v[0] + 0.59 * v[1] + 0.11 * v[2] < 150 and not (v[1] > v[2] + 10 or v[0] > v[2] + 30):
                    po[x, y] = sea + (255,)
    return out


def paint_tiles(ch, art, out, originals=None, log=print):
    """Aplica un dict de cambios ({'erase','paint','islands'} en GeoJSON) a los tiles. Devuelve los tiles escritos."""
    class _A:
        pass
    a = _A()
    a.art, a.out, a.originals = art, out, originals
    erase = [shape(g) for g in ch['erase']]
    paint = [shape(g) for g in ch['paint']]
    paint_kind = [g.get('kind', 'land') for g in ch['paint']]
    islands = [shape(g) for g in ch['islands']]
    unring = [shape(g) for g in ch.get('unring', [])]
    os.makedirs(a.out, exist_ok=True)
    random.seed(1)

    def source(name):
        if a.originals and os.path.exists(os.path.join(a.originals, name)):
            return os.path.join(a.originals, name)
        return os.path.join(a.art, name)

    previews = []
    for c, r in tiles_for(erase + paint + islands + unring):
        lon0, lat0 = tile_bounds(c, r)
        tb = box(lon0 - MARGIN, lat0 - TILE_DEG - MARGIN, lon0 + TILE_DEG + MARGIN, lat0 + MARGIN)
        e = [g for g in erase if g.intersects(tb)]
        p = [(g, k) for g, k in zip(paint, paint_kind) if g.intersects(tb)]
        isl = [g for g in islands if g.intersects(tb)]
        ur = [g for g in unring if g.intersects(tb)]
        if not (e or p or isl or ur):
            continue
        to_px = lambda x, y, s=1.0: ((x - lon0) / TILE_DEG * SIZE * s, (lat0 - y) / TILE_DEG * SIZE * s)
        base_bytes = open(source(tile_name(c, r)), 'rb').read()
        orig = decode(base_bytes, SIZE)
        img = orig.copy()

        # 0. contorno oscuro pegado a la costa de islas: dentro del polígono, en la franja exterior de la tierra, lo oscuro pasa a mar
        if ur:
            img = _unring(img, ur, to_px)

        # 1. borrar lineas viejas
        if e:
            mask = Image.new('1', (SIZE, SIZE), 0)
            dm = ImageDraw.Draw(mask)
            for g in e:
                pts = [to_px(*q) for q in g.coords]
                dm.line(pts, fill=1, width=ERASE_WIDTH, joint='curve')
                for x, y in pts:
                    dm.ellipse((x - ERASE_WIDTH / 2, y - ERASE_WIDTH / 2, x + ERASE_WIDTH / 2, y + ERASE_WIDTH / 2), fill=1)
            bb = mask.getbbox()
            if bb:
                bx = (max(0, bb[0] - 4), max(0, bb[1] - 4), min(SIZE, bb[2] + 4), min(SIZE, bb[3] + 4))
                patch, pm = img.crop(bx), mask.crop(bx)
                inpaint(patch, pm)
                soft = pm.convert('L').filter(ImageFilter.GaussianBlur(1))
                patch = Image.composite(patch.filter(ImageFilter.GaussianBlur(1.2)), patch, soft)
                img.paste(patch, bx[:2])

        # 2. islas: halo + tierra con ruido
        if isl:
            lm = Image.new('L', (SIZE * S, SIZE * S), 0)
            dl = ImageDraw.Draw(lm)
            for g in isl:
                for poly in getattr(g, 'geoms', [g]):
                    pts = [to_px(*q, S) for q in poly.exterior.coords]
                    dl.polygon(pts, fill=255)
                    dl.line(pts, fill=255, width=S * 2)  # minimo visible para islas diminutas
            land = lm.resize((SIZE, SIZE), Image.LANCZOS)
            halo = land.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(5))
            halo = halo.point(lambda v: int(min(255, v * 1.6) * 0.75))
            noise = Image.effect_noise((SIZE, SIZE), 22).convert('L')
            shallow = Image.merge('RGB', [Image.new('L', (SIZE, SIZE), v) for v in SHALLOW])
            shallow = Image.blend(shallow, Image.merge('RGB', [noise] * 3), 0.12)
            sand = Image.merge('RGB', [Image.new('L', (SIZE, SIZE), v) for v in LAND])
            sand = Image.blend(sand, Image.merge('RGB', [noise] * 3), 0.15)
            rgb = img.convert('RGB')
            rgb = Image.composite(shallow, rgb, halo)
            rgb = Image.composite(sand, rgb, land)
            img = rgb.convert('RGBA')

        # 3. pintar lineas nuevas
        for kind, color in (('land', LINE_COLOR), ('sea', SEA_LINE_COLOR)):
            pk = [g for g, k in p if k == kind]
            if not pk:
                continue
            lm = Image.new('L', (SIZE * S, SIZE * S), 0)
            dl = ImageDraw.Draw(lm)
            for g in pk:
                dl.line([to_px(*q, S) for q in g.coords], fill=255, width=int(LINE_WIDTH * S), joint='curve')
            lm = lm.resize((SIZE, SIZE), Image.LANCZOS).filter(ImageFilter.GaussianBlur(LINE_BLUR)).point(lambda v: min(255, int(v * 1.2)))
            img = Image.composite(Image.new('RGBA', (SIZE, SIZE), color + (255,)), img, lm)

        new_bytes, n0 = splice(base_bytes, img, orig, SIZE)
        open(os.path.join(a.out, tile_name(c, r)), 'wb').write(new_bytes)
        counts = [n0]
        for k in range(1, MIPS + 1):
            s = SIZE >> k
            mb = open(source(tile_name(c, r, k)), 'rb').read()
            mo = decode(mb, s)
            dn, do = img.resize((s, s), Image.BOX), orig.resize((s, s), Image.BOX)
            mn = mo.copy()
            pn, po, pmn, pd = dn.load(), do.load(), mn.load(), mo.load()
            for y in range(s):
                for x in range(s):
                    if pn[x, y] != po[x, y]:
                        pmn[x, y] = tuple(max(0, min(255, pd[x, y][i] + pn[x, y][i] - po[x, y][i])) for i in range(4))
            nb, n = splice(mb, mn, mo, s)
            open(os.path.join(a.out, tile_name(c, r, k)), 'wb').write(nb)
            counts.append(n)
        log('tile %02d-%02d: borrar %d, pintar %d, islas %d | bloques por nivel %s' % (c, r, len(e), len(p), len(isl), counts))
        previews.append((c, r))
    return previews


if __name__ == '__main__':
    main()
