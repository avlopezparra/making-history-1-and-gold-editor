"""Restaura la imagen de fondo (OperationalTerrain) desde el regionpack por defecto donde no hay una frontera dibujada.

Caso típico: al borrar una región o rehacerla, el editor borra la línea vieja y deja el fondo «rellenado» (se nota que había una línea).
Si en el fondo original no había línea ahí, se recupera tal como era. No se toca:
  · lo que tiene una frontera encima en el mapa actual (se conserva);
  · lo que tiene una frontera dibujada en la imagen original aunque el mapa actual ya no la tenga (traería la línea de vuelta);
  · lo que cambió de tierra a mar o al revés (islas nuevas con su halo, costas movidas).
Solo mira los tiles que el proyecto ya había modificado."""
import os

from PIL import Image, ImageDraw, ImageFilter
from shapely.geometry import LineString, box

import mhmap
import new_region
from fix_texture import decode, splice, tile_name, SIZE, MIPS
from paint_changes import TILE_DEG, tile_bounds, SEA_LINE_COLOR, S as SUPER
from fix_texture import LINE_WIDTH, LINE_BLUR, LINE_COLOR

LINE_R = 0.12        # grados alrededor de una frontera que se respetan (el borrado ensancha ±0.1)
COAST_R = 0.3        # alrededor de lo que cambió de tierra a mar: costas e islas nuevas con su halo


def _lines(m, bounds):
    x0, y0, x1, y1 = bounds
    out = []
    for b in m['borders']:
        for f, pts in b.segments:
            if len(pts) > 1:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                if max(xs) >= x0 and min(xs) <= x1 and max(ys) >= y0 and min(ys) <= y1:
                    out.append(pts)
    return out


def _bbox(m, r, cache):
    """Caja de una región a partir de los vértices de sus triángulos (mucho más barato que fundirlos)."""
    k = ('bb', r)
    if k not in cache:
        xs, ys = [], []
        for sh in mhmap.region_shapes(m, r):
            for t in sh.triangles():
                for q in t:
                    xs.append(q[0]); ys.append(q[1])
        cache[k] = (min(xs), min(ys), max(xs), max(ys)) if xs else None
    return cache[k]


def _land(m, bounds, cache):
    x0, y0, x1, y1 = bounds
    out = []
    for g in m['regions']:
        if g.u_type == 0:        # mar
            continue
        bb = _bbox(m, g.index, cache)
        if bb is None or bb[2] < x0 or bb[0] > x1 or bb[3] < y0 or bb[1] > y1:
            continue
        if g.index not in cache:
            try:
                cache[g.index] = new_region.mesh_polygon(m, g.index)
            except Exception:
                cache[g.index] = None
        poly = cache[g.index]
        if poly is not None and not poly.is_empty:
            b = poly.bounds
            if b[2] >= x0 and b[0] <= x1 and b[3] >= y0 and b[1] <= y1:
                out.append(poly)
    return out


def _border_masks(m, bounds, to_px):
    """Máscaras (tierra, mar) a 1024 px de todas las fronteras actuales que pasan por el tile (las costas no se pintan)."""
    R = m['regions']
    x0, y0, x1, y1 = bounds
    out = []
    for kind, color in (('land', LINE_COLOR), ('sea', SEA_LINE_COLOR)):
        lm = Image.new('L', (SIZE * SUPER, SIZE * SUPER), 0)
        dl = ImageDraw.Draw(lm)
        n = 0
        for b in m['borders']:
            if len(b.regions) != 2:
                continue
            ra, rb = b.regions
            sa, sb = R[ra].u_type == 0, R[rb].u_type == 0
            if sa != sb or (kind == 'sea') != sa:
                continue
            for f, pts in b.segments:
                if len(pts) < 2:
                    continue
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
                    continue
                dl.line([to_px(*p, SUPER) for p in pts], fill=255, width=int(LINE_WIDTH * SUPER), joint='curve')
                n += 1
        if n:
            lm = lm.resize((SIZE, SIZE), Image.LANCZOS).filter(ImageFilter.GaussianBlur(LINE_BLUR)).point(lambda v: min(255, int(v * 1.2)))
            out.append((color, lm))
    return out


def _paint(img, masks, size):
    """Pinta las fronteras (máscaras a 1024 px) sobre una imagen de lado 'size' (el tile o un mipmap)."""
    for color, lm in masks:
        mk = lm if size == SIZE else lm.resize((size, size), Image.BOX)
        img = Image.composite(Image.new('RGBA', (size, size), color + (255,)), img, mk)
    return img


def restore(cur_map, ref_map, tiles_dir, ref_tile, only_bbox=None, log=print, repaint=True):
    """cur_map / ref_map: mapas cargados (mhmap) del proyecto y del regionpack por defecto. tiles_dir: tiles modificados del proyecto.
    ref_tile(name) -> ruta del tile original. only_bbox (x0, y0, x1, y1) limita la zona. Devuelve [(tile, porcentaje_restaurado)]."""
    from shapely.ops import unary_union
    cc, cr = {}, {}
    done = []
    names = sorted(f for f in os.listdir(tiles_dir) if f.startswith('OperationalTerrain-') and len(f.split('-')) == 3)
    for fn in names:
        c, r = (int(x) for x in fn[:-4].split('-')[1:3])
        lon0, lat0 = tile_bounds(c, r)
        tb = (lon0 - LINE_R, lat0 - TILE_DEG - LINE_R, lon0 + TILE_DEG + LINE_R, lat0 + LINE_R)
        if only_bbox and (only_bbox[2] < tb[0] or only_bbox[0] > tb[2] or only_bbox[3] < tb[1] or only_bbox[1] > tb[3]):
            continue
        ref_path = ref_tile(fn)
        if not os.path.exists(ref_path):
            continue
        to_px = lambda x, y, k=1.0: ((x - lon0) / TILE_DEG * SIZE * k, (lat0 - y) / TILE_DEG * SIZE * k)
        px_r = LINE_R / TILE_DEG * SIZE
        prot = Image.new('L', (SIZE, SIZE), 0)
        d = ImageDraw.Draw(prot)
        for m in (cur_map, ref_map):
            for pts in _lines(m, tb):
                q = [to_px(*p) for p in pts]
                d.line(q, fill=255, width=int(px_r * 2), joint='curve')
                for x, y in (q[0], q[-1]):
                    d.ellipse((x - px_r, y - px_r, x + px_r, y + px_r), fill=255)
        land_a = unary_union(_land(cur_map, tb, cc) or [box(0, 0, 0, 0)])
        land_b = unary_union(_land(ref_map, tb, cr) or [box(0, 0, 0, 0)])
        diff = land_a.symmetric_difference(land_b).buffer(COAST_R)
        for g in getattr(diff, 'geoms', [diff]):
            if g.is_empty or g.geom_type != 'Polygon':
                continue
            d.polygon([to_px(*p) for p in g.exterior.coords], fill=255)
            for h in g.interiors:
                d.polygon([to_px(*p) for p in h.coords], fill=0)
        mask = prot.point(lambda v: 0 if v else 255)                        # 255 = se restaura
        mask = mask.filter(ImageFilter.MinFilter(3))                       # un píxel de margen alrededor de lo protegido
        frac = sum(1 for v in mask.getdata() if v) / float(SIZE * SIZE)
        cur_path = os.path.join(tiles_dir, fn)
        cur_b, ref_b = open(cur_path, 'rb').read(), open(ref_path, 'rb').read()
        cur, ref = decode(cur_b, SIZE), decode(ref_b, SIZE)
        new = Image.composite(ref, cur, mask)
        masks = _border_masks(cur_map, tb, to_px) if repaint else []
        new = _paint(new, masks, SIZE)       # fronteras siempre continuas: se repintan las actuales encima
        nb, n0 = splice(cur_b, new, cur, SIZE)
        if n0 == 0:
            continue
        open(cur_path, 'wb').write(nb)
        for k in range(1, MIPS + 1):
            s = SIZE >> k
            mn = tile_name(c, r, k)
            cp, rp = os.path.join(tiles_dir, mn), ref_tile(mn)
            if not (os.path.exists(cp) and os.path.exists(rp)):
                continue
            cb, rb = open(cp, 'rb').read(), open(rp, 'rb').read()
            ci, ri = decode(cb, s), decode(rb, s)
            ni = Image.composite(ri, ci, mask.resize((s, s), Image.BILINEAR))
            ni = _paint(ni, masks, s)
            out, _ = splice(cb, ni, ci, s)
            open(cp, 'wb').write(out)
        log('tile %02d-%02d: fondo restaurado (%d bloques, %.0f %% de la imagen)' % (c, r, n0, frac * 100))
        done.append((fn, round(frac * 100, 1)))
    return done
