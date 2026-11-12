"""Restores the background image (OperationalTerrain) from the default regionpack where no border is drawn.

Typical case: when deleting or redoing a region, the editor erases the old line and leaves the background «filled» (you can tell there was a line).
If the original background had no line there, it is restored as it was. Left untouched:
  · anything with a border on top in the current map (kept);
  · anything with a border drawn in the original image even if the current map no longer has it (would bring the line back);
  · anything that changed from land to sea or vice versa (new islands with their halo, moved coasts).
Only looks at tiles the project had already modified."""
import os

from PIL import Image, ImageDraw, ImageFilter
from shapely.geometry import LineString, box

import mhmap
import new_region
from fix_texture import decode, splice, tile_name, write_mips, SIZE, MIPS


def _have(tiles_dir, name, ref_tile):
    """The project's file if it exists; otherwise the reference one."""
    p = os.path.join(tiles_dir, name)
    return p if os.path.exists(p) else ref_tile(name)
from paint_changes import TILE_DEG, tile_bounds, SEA_LINE_COLOR, S as SUPER
from fix_texture import LINE_WIDTH, LINE_BLUR, LINE_COLOR

LINE_R = 0.12        # degrees around a border that are respected (erasing widens by ±0.1)
COAST_R = 0.3        # around what changed from land to sea: new coasts and islands with their halo


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
    """Bounding box of a region from its triangle vertices (much cheaper than merging them)."""
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
    """(land, sea) masks at 1024 px of all current borders crossing the tile (coasts are not painted)."""
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
    """Paints the borders (masks at 1024 px) on an image of side 'size' (the tile or a mipmap)."""
    for color, lm in masks:
        mk = lm if size == SIZE else lm.resize((size, size), Image.BOX)
        img = Image.composite(Image.new('RGBA', (size, size), color + (255,)), img, mk)
    return img


def _stale_mips(path):
    """True if the tile's mipmaps have dark strokes its level 0 lacks (old lines only visible from afar).
    Only counts smooth areas of level 0: next to current lines DXT compression gives differences that are not leftovers."""
    import numpy as np
    l0 = decode(open(path, 'rb').read(), SIZE).convert('L')
    n = 0
    for k in range(1, MIPS + 1):
        s = SIZE >> k
        mp = path[:-4] + '-%02d.tga' % k
        if not os.path.exists(mp):
            return False
        sh = l0.resize((s, s), Image.BOX)
        a = np.asarray(sh).astype(int)
        flat = a - np.asarray(sh.filter(ImageFilter.MinFilter(5))).astype(int) < 12
        m = np.asarray(decode(open(mp, 'rb').read(), s).convert('L')).astype(int)
        n += int(((a - m > 25) & flat).sum())
    return n > 20           # original World: 0; WorldModern Iraq-Iran: 41..939; freshly redone: 0..5


def restore(cur_map, ref_map, tiles_dir, ref_tile, only_bbox=None, log=print, repaint=True, map_tile=None):
    """cur_map / ref_map: loaded maps (mhmap) of the project and of the default regionpack. tiles_dir: modified project tiles.
    ref_tile(name) -> path of the original tile. only_bbox (x0, y0, x1, y1) limits the area. Returns [(tile, percent_restored)].
    map_tile(name) -> path of the tile in the map folder: tiles the project lacks but whose mipmaps carry old lines
    (e.g. a regionpack installed before the fix) are copied to the project and fixed too."""
    import shutil
    from shapely.ops import unary_union
    cc, cr = {}, {}
    done = []
    names = set(f for f in os.listdir(tiles_dir) if f.startswith('OperationalTerrain-') and len(f.split('-')) == 3)
    if map_tile:
        for c in range(24):
            for r in range(13):
                fn = tile_name(c, r)
                lon0, lat0 = tile_bounds(c, r)
                if fn in names or (only_bbox and (only_bbox[2] < lon0 or only_bbox[0] > lon0 + TILE_DEG
                                                  or only_bbox[3] < lat0 - TILE_DEG or only_bbox[1] > lat0)):
                    continue
                src = map_tile(fn)
                if os.path.exists(src) and _stale_mips(src):
                    shutil.copyfile(src, os.path.join(tiles_dir, fn))
                    names.add(fn)
    names = sorted(names)
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
        mask = mask.filter(ImageFilter.MinFilter(3))                       # one pixel of margin around the protected area
        frac = sum(1 for v in mask.getdata() if v) / float(SIZE * SIZE)
        cur_path = os.path.join(tiles_dir, fn)
        cur_b, ref_b = open(cur_path, 'rb').read(), open(ref_path, 'rb').read()
        cur, ref = decode(cur_b, SIZE), decode(ref_b, SIZE)
        new = Image.composite(ref, cur, mask)
        masks = _border_masks(cur_map, tb, to_px) if repaint else []
        new = _paint(new, masks, SIZE)       # borders always continuous: the current ones are repainted on top
        nb, n0 = splice(cur_b, new, cur, SIZE)
        if n0:
            open(cur_path, 'wb').write(nb)
        # mipmaps rebuilt from the restored level 0, even if it was already clean: from afar it looks the same as up close
        nm = sum(write_mips(c, r, new, lambda n: open(_have(tiles_dir, n, ref_tile), 'rb').read(), tiles_dir))
        if not n0 and not nm:
            continue
        log('tile %02d-%02d: fondo restaurado (%d bloques, %.0f %% de la imagen; %d bloques de mipmaps)' % (c, r, n0, frac * 100, nm))
        done.append((fn, round(frac * 100, 1)))
    return done


def repaint_tiles(m, tiles_dir, names=None, only_bbox=None, log=print):
    """Draws the map's current borders (land and sea, like the game) on top of the project tiles.
    names: 'CC-RR' tiles to repaint (None = all project tiles, or those in only_bbox). Returns the tiles touched."""
    done = []
    files = sorted(f for f in os.listdir(tiles_dir) if f.startswith('OperationalTerrain-') and len(f.split('-')) == 3)
    for fn in files:
        c, r = (int(x) for x in fn[:-4].split('-')[1:3])
        if names is not None and '%02d-%02d' % (c, r) not in names:
            continue
        lon0, lat0 = tile_bounds(c, r)
        tb = (lon0 - LINE_R, lat0 - TILE_DEG - LINE_R, lon0 + TILE_DEG + LINE_R, lat0 + LINE_R)
        if only_bbox and (only_bbox[2] < tb[0] or only_bbox[0] > tb[2] or only_bbox[3] < tb[1] or only_bbox[1] > tb[3]):
            continue
        to_px = lambda x, y, k=1.0, lon0=lon0, lat0=lat0: ((x - lon0) / TILE_DEG * SIZE * k, (lat0 - y) / TILE_DEG * SIZE * k)
        masks = _border_masks(m, tb, to_px)
        if not masks:
            continue
        p = os.path.join(tiles_dir, tile_name(c, r))
        if not os.path.exists(p):
            continue
        b = open(p, 'rb').read()
        cur = decode(b, SIZE)
        img = _paint(cur, masks, SIZE)
        out, _ = splice(b, img, cur, SIZE)
        open(p, 'wb').write(out)
        write_mips(c, r, img, lambda n: open(os.path.join(tiles_dir, n), 'rb').read(), tiles_dir)    # the mipmaps, from level 0
        log('tile %02d-%02d: líneas de las regiones dibujadas' % (c, r))
        done.append('%02d-%02d' % (c, r))
    return done
