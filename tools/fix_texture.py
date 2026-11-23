"""Repaints the border drawn on the terrain textures after moving a border.

The game has the borders painted in OperationalTerrain-CC-RR.tga (raw DXT5, no header;
1024x1024 and mipmaps -01..-04 from 512 to 64). Each tile covers 15x15 degrees: column CC from -180
longitude, row RR from +105 latitude southward.

This script:
  1. erases the old line in the stretch that moved from one region to another (fill from the edges),
  2. paints the new line (the KML line inside the source region) with the original's color,
  3. recompresses ONLY the 4x4 blocks that change, in the tile and its 4 mipmaps.

Usage:
  python fix_texture.py <xml mapa ORIGINAL> <carpeta art del juego> <archivo.kml> "<linea>" \
         <region origen> <region destino> <west|east> <carpeta salida>
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from shapely.geometry import LineString, Polygon
from shapely.ops import linemerge, unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap  # noqa: E402
from move_border import kml_line, side_polygon, signed_area  # noqa: E402

TILE_DEG = 15.0
SIZE = 1024
MIPS = 4
ERASE_WIDTH = 13     # px at 1024: the original line darkens up to +-4 px from its center
LINE_WIDTH = 3.0     # px a 1024, antes de difuminar
LINE_BLUR = 1.0      # perfil medido en el original: centro ~23, +-1 ~33, +-2 ~57, +-3 ~77, fondo ~95
LINE_COLOR = (26, 18, 10)  # measured core of the original lines


def tile_name(c, r, mip=0):
    return 'OperationalTerrain-%02d-%02d%s.tga' % (c, r, '-%02d' % mip if mip else '')


def write_mips(c, r, img, read, out_dir):
    """Rebuilds the tile's -01..-04 mipmaps from its finished level 0 (BOX reduction, like the game's). From afar the
    game uses these levels: if they were touched up separately (adding the difference), leftovers of erased lines remained when zooming out.
    read(name) -> current bytes of the mipmap. The whole level is recompressed (the compressor always gives the same: repeating it changes
    nothing) and it is only written if it changes. Returns the differing 4x4 blocks per level."""
    counts = []
    for k in range(1, MIPS + 1):
        s = SIZE >> k
        mb = read(tile_name(c, r, k))
        nb = encode_blocks(img.resize((s, s), Image.BOX))
        n = sum(1 for i in range(0, len(nb), 16) if nb[i:i + 16] != mb[i:i + 16])
        if n or not os.path.exists(os.path.join(out_dir, tile_name(c, r, k))):
            with open(os.path.join(out_dir, tile_name(c, r, k)), 'wb') as f:
                f.write(nb)
        counts.append(n)
    return counts


def decode(data, size):
    return Image.frombytes('RGBA', (size, size), data, 'bcn', 3)


def _to565(c):
    c = np.clip(np.rint(c), 0, 255).astype(np.int32)
    return ((c[..., 0] * 31 + 127) // 255 << 11) | ((c[..., 1] * 63 + 127) // 255 << 5) | ((c[..., 2] * 31 + 127) // 255)


def _from565(v):
    return np.stack([(v >> 11 & 31) * 255 / 31, (v >> 5 & 63) * 255 / 63, (v & 31) * 255 / 31], -1)


_W = np.array([1.0, 0.0, 2 / 3, 1 / 3])                  # weight of c0 for BC1 index codes 0..3


def _palette(c0, c1):
    p0, p1 = _from565(c0), _from565(c1)
    return _W[None, :, None] * p0[:, None] + (1 - _W[None, :, None]) * p1[:, None]


def _fit(px, e0, e1):
    c0, c1 = _to565(e0), _to565(e1)
    pal = _palette(c0, c1)
    d = ((px[:, :, None, :] - pal[:, None]) ** 2).sum(-1)
    idx = d.argmin(-1)
    return c0, c1, idx, np.take_along_axis(d, idx[..., None], -1).sum((1, 2))


def _color_blocks(px):
    """BC1 colour part (4-colour mode) of N blocks of 16 RGB pixels: PCA endpoints, then one least-squares refit.
    Pillow's DXT encoder painted mixed land/sea blocks in the land colour: coasts looked pixelated in the mipmaps."""
    mean = px.mean(1, keepdims=True)
    d = px - mean
    cov = np.einsum('nki,nkj->nij', d, d)
    axis = np.ones((len(px), 3))
    for _ in range(8):                                   # power iteration: main axis of each block's colours
        axis = np.einsum('nij,nj->ni', cov, axis)
        axis /= np.maximum(np.linalg.norm(axis, axis=1, keepdims=True), 1e-9)
    t = np.einsum('nki,ni->nk', d, axis)
    e0 = mean[:, 0] + axis * t.max(1, keepdims=True)
    e1 = mean[:, 0] + axis * t.min(1, keepdims=True)
    c0, c1, idx, err = _fit(px, e0, e1)
    a = _W[idx]                                          # least squares: px ~ a*e0 + (1-a)*e1
    b = 1 - a
    aa, bb, ab = (a * a).sum(1), (b * b).sum(1), (a * b).sum(1)
    det = aa * bb - ab * ab
    ok = (np.abs(det) > 1e-6)[:, None]
    ax, bx = np.einsum('nk,nki->ni', a, px), np.einsum('nk,nki->ni', b, px)
    sd = np.where(ok, det[:, None], 1)
    r0, r1 = (bb[:, None] * ax - ab[:, None] * bx) / sd, (aa[:, None] * bx - ab[:, None] * ax) / sd
    n0, n1, nidx, nerr = _fit(px, np.where(ok, r0, e0), np.where(ok, r1, e1))
    better = nerr < err
    c0, c1, idx = np.where(better, n0, c0), np.where(better, n1, c1), np.where(better[:, None], nidx, idx)
    swap = c0 < c1                                       # 4-colour mode needs c0 > c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    idx = np.where(swap[:, None], np.array([1, 0, 3, 2])[idx], idx)
    idx = np.where((c0 == c1)[:, None], 0, idx)
    bits = (idx.astype(np.uint32) << (2 * np.arange(16, dtype=np.uint32))).sum(1, dtype=np.uint32)
    return c0.astype(np.uint16), c1.astype(np.uint16), bits


def _alpha_blocks(al):
    """BC3 alpha part of N blocks of 16 alphas (8-level mode: a0 > a1)."""
    a0, a1 = np.rint(al.max(1)), np.rint(al.min(1))
    wt = np.array([7, 0, 6, 5, 4, 3, 2, 1]) / 7          # weight of a0 for codes 0..7
    lv = wt[None] * a0[:, None] + (1 - wt[None]) * a1[:, None]
    idx = np.abs(al[:, :, None] - lv[:, None]).argmin(-1)
    idx = np.where((a0 == a1)[:, None], 0, idx)
    bits = (idx.astype(np.uint64) << (3 * np.arange(16, dtype=np.uint64))).sum(1, dtype=np.uint64)
    return a0.astype(np.uint8), a1.astype(np.uint8), bits


def encode_blocks(img):
    """Headerless DXT5 (BC3) bytes of an RGBA image whose sides are multiples of 4, blocks in row order."""
    a = np.asarray(img.convert('RGBA'), dtype=np.float64)
    h, w = a.shape[:2]
    blk = a.reshape(h // 4, 4, w // 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 4)
    out = np.zeros((len(blk), 16), np.uint8)
    for s in range(0, len(blk), 16384):                  # chunks: bounded memory on 1024 px tiles
        b = blk[s:s + 16384]
        a0, a1, ab = _alpha_blocks(b[..., 3])
        c0, c1, cb = _color_blocks(b[..., :3])
        o = out[s:s + 16384]
        o[:, 0], o[:, 1] = a0, a1
        o[:, 2:8] = ab.astype('<u8')[:, None].view(np.uint8)[:, :6]
        o[:, 8:10] = c0.astype('<u2')[:, None].view(np.uint8)
        o[:, 10:12] = c1.astype('<u2')[:, None].view(np.uint8)
        o[:, 12:16] = cb.astype('<u4')[:, None].view(np.uint8)
    return out.tobytes()


def splice(orig_bytes, new_img, old_img, size):
    """Recompresses the 4x4 blocks whose content changed and inserts them into the original bytes."""
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
    """Layered fill from the edge of the hole (mean of known neighbors)."""
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

    # 2. paint the new line (x4 supersampling for smoothing)
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

    # 3. mipmaps: original + (reduce(new) - reduce(original)), only where it changes
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
