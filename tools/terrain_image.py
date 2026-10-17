"""Imagen de fondo (terreno) del regionpack: exportar a PNG/JPG e importar desde una imagen.

El terreno son 24 x 13 tiles OperationalTerrain-CC-RR.tga (DXT5 en bruto, 1024 px = 15 grados, mipmaps -01..-04).
La columna CC empieza en -180 de longitud; la fila RR en 105 de latitud hacia el sur (hasta -90).

- export_image: une los tiles (del proyecto si están modificados, si no del regionpack) en una sola imagen
  equirectangular de la zona pedida, al nivel de detalle elegido (0 = 1024 px por tile ... 4 = 64 px).
- import_image: la imagen cubre la zona bbox (lon0, lat0, lon1, lat1); se escala a la resolución del juego,
  se pega en cada tile afectado (lo que queda fuera de la imagen conserva el terreno actual), se conserva el
  canal alfa original y se recomprimen el tile y sus 4 mipmaps en la carpeta tiles/ del proyecto.
  Nada llega al juego hasta «Instalar».
"""
import io
import json
import os

from PIL import Image, ImageFilter

from fix_texture import decode, encode_blocks, tile_name, SIZE, MIPS, TILE_DEG

COLS, ROWS = 24, 13
LON0, LAT0 = -180.0, 105.0
WORLD = (-180.0, -90.0, 180.0, 105.0)
Image.MAX_IMAGE_PIXELS = None


def _tiles(bbox):
    x0, y0, x1, y1 = bbox
    c0 = max(0, int((x0 - LON0) // TILE_DEG)); c1 = min(COLS - 1, int((x1 - LON0 - 1e-9) // TILE_DEG))
    r0 = max(0, int((LAT0 - y1) // TILE_DEG)); r1 = min(ROWS - 1, int((LAT0 - y0 - 1e-9) // TILE_DEG))
    return c0, c1, r0, r1


def snap(bbox):
    """bbox ajustado a los bordes de los tiles."""
    c0, c1, r0, r1 = _tiles(bbox)
    return (LON0 + c0 * TILE_DEG, LAT0 - (r1 + 1) * TILE_DEG, LON0 + (c1 + 1) * TILE_DEG, LAT0 - r0 * TILE_DEG)


def export_image(project, bbox=None, level=2, fmt='png'):
    bbox = snap(bbox or WORLD)
    c0, c1, r0, r1 = _tiles(bbox)
    s = SIZE >> level
    out = Image.new('RGB', ((c1 - c0 + 1) * s, (r1 - r0 + 1) * s))
    for c in range(c0, c1 + 1):
        for r in range(r0, r1 + 1):
            out.paste(project.tile_image(c, r, level), ((c - c0) * s, (r - r0) * s))
    b = io.BytesIO()
    if fmt == 'jpg':
        out.save(b, 'JPEG', quality=92)
    else:
        out.save(b, 'PNG', optimize=False, compress_level=3)
    return b.getvalue(), bbox, out.size


def _tile_rgba(project, c, r):
    data = open(project.tile_path(tile_name(c, r)), 'rb').read()
    return decode(data, SIZE)


def import_image(project, data, bbox, log=print):
    """data: bytes de la imagen. bbox: zona que cubre. Devuelve la lista de tiles escritos."""
    img = Image.open(io.BytesIO(data)).convert('RGB')
    x0, y0, x1, y1 = bbox
    if not (x1 > x0 and y1 > y0):
        raise ValueError('zona no válida')
    ppd = SIZE / TILE_DEG                      # pixeles por grado a resolucion completa
    W, H = int(round((x1 - x0) * ppd)), int(round((y1 - y0) * ppd))
    if W * H > 24576 * 13312:
        raise ValueError('zona demasiado grande')
    big = img.resize((W, H), Image.LANCZOS) if img.size != (W, H) else img
    c0, c1, r0, r1 = _tiles(bbox)
    written = []
    os.makedirs(project.tiles, exist_ok=True)
    for c in range(c0, c1 + 1):
        for r in range(r0, r1 + 1):
            tx0, ty1 = LON0 + c * TILE_DEG, LAT0 - r * TILE_DEG          # esquina superior izquierda del tile
            # parte de la imagen que cae en este tile (en pixeles del tile y de la imagen)
            ix0 = max(tx0, x0); ix1 = min(tx0 + TILE_DEG, x1)
            iy1 = min(ty1, y1); iy0 = max(ty1 - TILE_DEG, y0)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            px0, py0 = int(round((ix0 - tx0) * ppd)), int(round((ty1 - iy1) * ppd))
            px1, py1 = int(round((ix1 - tx0) * ppd)), int(round((ty1 - iy0) * ppd))
            sx0, sy0 = int(round((ix0 - x0) * ppd)), int(round((y1 - iy1) * ppd))
            piece = big.crop((sx0, sy0, sx0 + (px1 - px0), sy0 + (py1 - py0)))
            base = _tile_rgba(project, c, r)
            alpha = base.getchannel('A')
            rgb = base.convert('RGB')
            rgb.paste(piece, (px0, py0))
            tile = rgb.copy()
            tile.putalpha(alpha)
            for lv in range(MIPS + 1):
                s = SIZE >> lv
                im = tile if lv == 0 else tile.resize((s, s), Image.LANCZOS)
                blob = encode_blocks(im)
                if len(blob) != s * s:
                    raise ValueError('codificación DXT5 inesperada (%d bytes para %d px)' % (len(blob), s))
                with open(os.path.join(project.tiles, tile_name(c, r, lv)), 'wb') as f:
                    f.write(blob)
            written.append('%02d-%02d' % (c, r))
            log('fondo: tile %02d-%02d' % (c, r))
    return written


# ------------------------------------------------------------------ exportar fondo y límites por separado
def borders_layer(project, bbox, level):
    """Imagen RGBA transparente con las fronteras entre regiones (borders.brd) en la zona y tamaño de la exportación."""
    from PIL import ImageDraw
    x0, y0, x1, y1 = bbox
    s = SIZE >> level
    ppd = s / TILE_DEG
    W, H = int(round((x1 - x0) * ppd)), int(round((y1 - y0) * ppd))
    SS = 2                                                  # supermuestreo para suavizar las líneas
    img = Image.new('L', (W * SS, H * SS), 0)
    d = ImageDraw.Draw(img)
    width = max(1, int(round(SS * max(1.0, 2.5 * s / SIZE * 1.0 + 0.5))))
    for b in project.m['borders']:
        for _flag, pts in b.segments:
            px = [((x - x0) * ppd * SS, (y1 - y) * ppd * SS) for x, y in pts]
            if len(px) >= 2 and not (max(p[0] for p in px) < 0 or min(p[0] for p in px) > W * SS
                                     or max(p[1] for p in px) < 0 or min(p[1] for p in px) > H * SS):
                d.line(px, fill=255, width=width, joint='curve')
    mask = img.resize((W, H), Image.LANCZOS)
    out = Image.new('RGBA', (W, H), (20, 20, 20, 0))
    out.putalpha(mask)
    return out, mask


def export_with_terrain(project, bbox=None, level=2, fmt='png', scen=None, separate=False):
    """.zip con la imagen de fondo y otra con el color del tipo de terreno de cada región (mar en celeste, huecos en blanco) y la leyenda;
    con 'separate' además el fondo sin fronteras y las fronteras por separado."""
    import zipfile
    import terrain_colors
    if separate:
        base, bb, size = export_separate(project, bbox, level, fmt)
        src = zipfile.ZipFile(io.BytesIO(base))
        files = {n: src.read(n) for n in src.namelist()}
    else:
        data, bb, size = export_image(project, bbox, level, fmt)
        files = {'fondo_con_limites.' + ('jpg' if fmt == 'jpg' else 'png'): data}
    img = terrain_colors.terrain_layer(project, bb, level, scen)
    b = io.BytesIO()
    img.save(b, 'PNG', compress_level=3)
    files['terreno_por_tipo.png'] = b.getvalue()
    files['leyenda_terreno.json'] = json.dumps(terrain_colors.legend(), ensure_ascii=False, indent=1).encode('utf-8')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue(), bb, size


def export_separate(project, bbox=None, level=2, fmt='png'):
    """.zip con tres imágenes alineadas: fondo.png (terreno sin las fronteras pintadas), limites.png (solo las fronteras,
    transparente) y fondo_con_limites.png (tal como lo ve el juego). El fondo se obtiene rellenando las fronteras con el
    terreno vecino más cercano."""
    import zipfile
    import numpy as np
    data, bb, size = export_image(project, bbox, level, 'png')
    full = Image.open(io.BytesIO(data)).convert('RGB')
    lim, mask = borders_layer(project, bb, level)
    dil = lambda im, n: im.filter(ImageFilter.MaxFilter(3)) if n <= 1 else dil(im.filter(ImageFilter.MaxFilter(3)), n - 1)
    line = np.asarray(dil(mask.resize(full.size).point(lambda v: 255 if v > 20 else 0), 1 + (2 >> level))) > 0
    arr = np.asarray(full).astype('float32')
    # solo se rellenan los píxeles de la línea que son realmente de frontera pintada (más oscuros que su entorno):
    # las costas también son fronteras en borders.brd pero no están pintadas en la textura
    lum = full.convert('L')
    local = np.asarray(lum.filter(ImageFilter.MedianFilter(5 if level < 2 else 3))).astype('float32')
    m = line & (np.asarray(lum).astype('float32') < local - 14)
    m = (np.asarray(dil(Image.fromarray((m * 255).astype('uint8')), 1)) > 0) & line
    unknown = m.copy()
    for _ in range(10):                                   # relleno con la media de los vecinos ya conocidos, hacia dentro
        if not unknown.any():
            break
        known = (~unknown).astype('float32')
        kp, ap = np.pad(known, 1), np.pad(arr * known[..., None], ((1, 1), (1, 1), (0, 0)))
        h, w = known.shape
        wsum = sum(kp[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] for dy in (-1, 0, 1) for dx in (-1, 0, 1))
        asum = sum(ap[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] for dy in (-1, 0, 1) for dx in (-1, 0, 1))
        new = unknown & (wsum > 0)
        arr[new] = asum[new] / wsum[new][:, None]
        unknown &= ~new
    fondo = Image.fromarray(arr.clip(0, 255).astype('uint8'))
    ext, kw = ('jpg', {'quality': 92}) if fmt == 'jpg' else ('png', {'compress_level': 3})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        def put(name, im, rgba=False):
            b = io.BytesIO()
            if rgba or ext == 'png':
                im.save(b, 'PNG', compress_level=3)
                z.writestr(name + '.png', b.getvalue())
            else:
                im.convert('RGB').save(b, 'JPEG', **kw)
                z.writestr(name + '.jpg', b.getvalue())
        put('fondo', fondo)
        put('limites', lim, rgba=True)
        put('fondo_con_limites', full)
        z.writestr('LEEME.txt',
                   'Zona (oeste, sur, este, norte): %s\nTamaño: %dx%d px\n\n'
                   'fondo: terreno sin las fronteras pintadas (se rellenan con el terreno vecino).\n'
                   'limites: solo las fronteras entre regiones, en PNG transparente (mismo tamaño y zona).\n'
                   'fondo_con_limites: la imagen tal como la ve el juego.\n\n'
                   'Para importar: «Importar imagen…» con fondo (o con fondo_con_limites); las fronteras se vuelven a pintar\n'
                   'con «Repintar fronteras en la textura al guardar».\n' % (', '.join('%g' % v for v in bb), size[0], size[1]))
    return buf.getvalue(), bb, size
