"""Vista previa antes/despues de una zona (lon/lat) a partir de los tiles DXT5.
Uso: python preview_tiles.py <dir tiles nuevos> <dir art juego> <dir originales> salida.png lon0 lat0 lon1 lat1 [escala]"""
import os, sys
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_texture import decode, tile_name, SIZE

def mosaic(dirs, lon0, lat0, lon1, lat1):
    ppd = SIZE / 15.0
    W, H = int((lon1 - lon0) * ppd), int((lat0 - lat1) * ppd)
    out = Image.new('RGB', (W, H))
    for c in range(int((lon0 + 180) // 15), int((lon1 + 180) // 15) + 1):
        for r in range(int((105 - lat0) // 15), int((105 - lat1) // 15) + 1):
            name = tile_name(c, r)
            path = next(os.path.join(d, name) for d in dirs if os.path.exists(os.path.join(d, name)))
            t = decode(open(path, 'rb').read(), SIZE).convert('RGB')
            tx, ty = (-180 + 15 * c - lon0) * ppd, (lat0 - (105 - 15 * r)) * ppd
            out.paste(t, (int(round(tx)), int(round(ty))))
    return out

if __name__ == '__main__':
    new, art, orig, dst = sys.argv[1:5]
    lon0, lat0, lon1, lat1 = map(float, sys.argv[5:9])
    k = float(sys.argv[9]) if len(sys.argv) > 9 else 1
    a = mosaic([orig, art], lon0, lat0, lon1, lat1)
    b = mosaic([new, orig, art], lon0, lat0, lon1, lat1)
    if k != 1:
        a = a.resize((int(a.width * k), int(a.height * k)), Image.LANCZOS); b = b.resize(a.size, Image.LANCZOS)
    o = Image.new('RGB', (a.width * 2 + 12, a.height), (255, 255, 255)); o.paste(a, (0, 0)); o.paste(b, (a.width + 12, 0))
    ImageDraw.Draw(o).text((8, 8), 'ANTES', fill=(255, 0, 0)); ImageDraw.Draw(o).text((a.width + 20, 8), 'DESPUES', fill=(255, 0, 0))
    o.save(dst); print(dst, o.size)
