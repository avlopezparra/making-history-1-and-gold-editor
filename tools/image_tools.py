"""Herramientas de imagen para escenarios de Making History (pagina /imagenes del editor).

- Lectura/escritura TGA exacta (tipo 2 sin comprimir o 10 RLE, 24/32 bits, orientacion abajo/arriba).
- Titulo y botones del escenario (Title.tga, Button.tga, ButtonOver.tga).
- Juego completo de banderas de un pais (ui/art/2D/countries/<Pais>/) a partir de una bandera y,
  opcionalmente, una escarapela/emblema y la foto del lider.
- Iconos de unidades (UnitTemplateIconTable), productos de fabrica (FactoryOutputIconTable) e imagen
  de investigacion (MediaPack.xml, Research_Project_Icon), en las 4 medidas del juego.

Medidas tomadas de los 293 paises de The Modern World (ver EDITOR.md, seccion Imagenes).
"""
import base64
import io
import os
import re
import shutil
import struct
import time

from PIL import Image, ImageDraw, ImageFilter

import scenario_core

def content_ui():
    """Carpeta UI del contenido del juego elegido (MH1 o Gold)."""
    return os.path.join(scenario_core.GAME, 'Modern Europe', 'system', 'UI')


# ------------------------------------------------------------------------------------------- TGA
def tga_format(path):
    """Formato de un TGA: tipo (2 sin comprimir, 10 RLE), bits, descriptor, medidas."""
    h = open(path, 'rb').read(18)
    w, hh, bpp, desc = struct.unpack('<HHBB', h[12:18])
    return {'type': h[2], 'bpp': bpp, 'desc': desc, 'w': w, 'h': hh, 'idlen': h[0]}


def _rle_row(row, px):
    """Codifica una fila (bytes) en paquetes RLE de TGA."""
    n = len(row) // px
    out = bytearray()
    i = 0
    while i < n:
        j = i + 1
        while j < n and j - i < 128 and row[j * px:(j + 1) * px] == row[i * px:(i + 1) * px]:
            j += 1
        if j - i > 1:
            out.append(0x80 | (j - i - 1))
            out += row[i * px:(i + 1) * px]
            i = j
            continue
        j = i + 1    # paquete literal hasta la proxima repeticion
        while j < n and j - i < 128 and not (j + 1 < n and row[j * px:(j + 1) * px] == row[(j + 1) * px:(j + 2) * px]):
            j += 1
        out.append(j - i - 1)
        out += row[i * px:j * px]
        i = j
    return bytes(out)


def tga_bytes(img, fmt):
    """Imagen PIL -> bytes TGA con el formato dado (type 2/10, bpp 24/32, desc orientacion+alfa)."""
    bpp = fmt.get('bpp', 32)
    rle = fmt.get('type', 10) in (10, 11)
    top = bool(fmt.get('desc', 8) & 0x20)
    mode = 'RGBA' if bpp == 32 else 'RGB'
    img = img.convert(mode)
    raw = img.tobytes('raw', 'BGRA' if bpp == 32 else 'BGR')
    px = bpp // 8
    w, h = img.size
    rows = [raw[y * w * px:(y + 1) * w * px] for y in range(h)]
    if not top:
        rows.reverse()
    desc = (8 if bpp == 32 else 0) | (0x20 if top else 0)
    head = struct.pack('<BBBHHBHHHHBB', 0, 0, 10 if rle else 2, 0, 0, 0, 0, 0, w, h, bpp, desc)
    body = b''.join(_rle_row(r, px) for r in rows) if rle else b''.join(rows)
    return head + body


def encode(img, name, fmt=None):
    """Bytes del archivo segun su extension (tga con formato, bmp 24 bits, png)."""
    ext = name.lower().rsplit('.', 1)[-1]
    if ext == 'tga':
        return tga_bytes(img, fmt or {'type': 10, 'bpp': 32, 'desc': 8})
    b = io.BytesIO()
    if ext == 'bmp':
        img.convert('RGB').save(b, 'BMP')
    else:
        img.save(b, 'PNG')
    return b.getvalue()


def from_data_url(s):
    if not s:
        return None
    if s.startswith('data:'):
        s = s.split(',', 1)[1]
    im = Image.open(io.BytesIO(base64.b64decode(s)))
    im.load()
    return im


def to_data_url(img):
    b = io.BytesIO()
    img.save(b, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode('ascii')


def png_bytes(path, maxside=None, crop=False):
    img = Image.open(path).convert('RGBA')
    if crop:    # miniatura: sin el margen transparente
        bb = img.getchannel('A').point(lambda v: 255 if v > 16 else 0).getbbox()
        if bb:
            img = img.crop(bb)
    if maxside and max(img.size) > maxside:
        img.thumbnail((maxside, maxside))
    b = io.BytesIO()
    img.save(b, 'PNG')
    return b.getvalue()


# ------------------------------------------------------------------------------------ rutas y copias
def scen_dir(scen):
    d = os.path.abspath(os.path.join(scenario_core.SCEN_ROOT, scen))
    if not d.startswith(os.path.abspath(scenario_core.SCEN_ROOT)) or not os.path.isdir(d):
        raise ValueError('escenario no valido: %s' % scen)
    return d


def safe_name(s):
    s = (s or '').strip()
    if not s or re.search(r'[\\/:*?"<>|]', s) or s in ('.', '..'):
        raise ValueError('nombre no valido: %r' % s)
    return s


def resolve_rel(rel):
    """Ruta relativa a la carpeta de escenarios -> absoluta (o carpeta de contenido si empieza por @ui/)."""
    if rel.startswith('@ui/'):
        base = content_ui()
        rel = rel[4:]
    else:
        base = scenario_core.SCEN_ROOT
    p = os.path.abspath(os.path.join(base, rel))
    if not p.startswith(os.path.abspath(base)) or not os.path.isfile(p):
        raise ValueError('archivo no valido')
    return p


def write_files(files, label):
    """Escribe {ruta_absoluta: bytes}. Antes guarda el original (solo la primera vez) y la version previa."""
    stamp = time.strftime('%Y%m%d-%H%M%S')
    root = os.path.abspath(scenario_core.SCEN_ROOT)
    done = []
    for path, data in files.items():
        rel = os.path.relpath(path, root)
        if not scenario_core.BACKUPS:
            pass
        elif os.path.exists(path):
            orig = os.path.join(scenario_core.BACKUP_ROOT, 'imagenes_originales', rel)
            if not os.path.exists(orig):
                os.makedirs(os.path.dirname(orig), exist_ok=True)
                shutil.copy2(path, orig)
            hist = os.path.join(scenario_core.BACKUP_ROOT, 'historial', stamp + '-' + label, rel)
            os.makedirs(os.path.dirname(hist), exist_ok=True)
            shutil.copy2(path, hist)
        else:
            new = os.path.join(scenario_core.BACKUP_ROOT, 'historial', stamp + '-' + label, 'nuevos.txt')
            os.makedirs(os.path.dirname(new), exist_ok=True)
            with open(new, 'a', encoding='utf-8') as f:
                f.write(rel + '\n')     # archivos que no existian: para poder quitarlos a mano
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
        done.append(rel)
    return {'written': done, 'backup': None if not scenario_core.BACKUPS else os.path.abspath(os.path.join(scenario_core.BACKUP_ROOT, 'historial', stamp + '-' + label))}


# ------------------------------------------------------------------------------- titulo y botones
TITLE_FILES = ('Title.tga', 'Button.tga', 'ButtonOver.tga')


def title_info(scen):
    d = scen_dir(scen)
    out = []
    for f in TITLE_FILES:
        p = os.path.join(d, f)
        if os.path.exists(p):
            fmt = tga_format(p)
            a = Image.open(p).convert('RGBA').getchannel('A')
            fmt['visible'] = a.point(lambda v: 255 if v > 8 else 0).getbbox()
            out.append({'file': f, 'rel': os.path.relpath(p, scenario_core.SCEN_ROOT), 'fmt': fmt})
    return out


def write_title(scen, f, data_url):
    if f not in TITLE_FILES:
        raise ValueError('archivo no permitido')
    p = os.path.join(scen_dir(scen), f)
    fmt = tga_format(p) if os.path.exists(p) else {'type': 10, 'bpp': 32, 'desc': 8,
                                                     'w': 1024 if f == 'Title.tga' else 512, 'h': 64 if f == 'Title.tga' else 128}
    img = from_data_url(data_url).convert('RGBA')
    if img.size != (fmt['w'], fmt['h']):
        img = img.resize((fmt['w'], fmt['h']), Image.LANCZOS)
    rep = write_files({p: tga_bytes(img, fmt)}, 'titulo')
    rep['fmt'] = fmt
    return rep


# ------------------------------------------------------------------------------------- banderas
# (nombre, tamano del lienzo, rectangulo de la bandera, sombra) medido en los paises de The Modern World
FLAG_RECTS = [
    ('262-134-flag-shadow.tga', (512, 256), (3, 3, 259, 131), True),
    ('flag-68-34-shadow.tga', (128, 64), (4, 4, 72, 38), True),
    ('flag-68-34.tga', (128, 64), (0, 0, 68, 34), False),
    ('flag-48h-64w.tga', (64, 64), (4, 5, 60, 45), True),
    ('diplomatic-flag.tga', (32, 32), (4, 4, 28, 28), True),
    ('diplomatic-flag-over.tga', (32, 32), (4, 4, 28, 28), False),
    ('flag-16-16.tga', (16, 16), (2, 2, 14, 14), True),
    ('flag-19-19.tga', (32, 32), (2, 2, 17, 17), True),
    ('multichat_flag.png', (16, 16), (0, 0, 15, 15), False),
]
FLAG_FULL = [   # bandera entera estirada al lienzo
    ('flag-256-128.bmp', (256, 128)),
    ('big-flag.bmp', (128, 64)),
]
FLAG_ORDER = ['3DFlag.tga', 'big-flag.bmp', 'flag-256-128.bmp', 'multichat_flag.bmp', 'multichat_flag.png',
              '262-134-flag-shadow.tga', 'flag-68-34.tga', 'flag-68-34-shadow.tga', 'flag-48h-64w.tga',
              'diplomatic-flag.tga', 'diplomatic-flag-over.tga', 'flag-16-16.tga', 'flag-19-19.tga',
              'decal.tga', 'decal-64-64.tga', 'decal-64-64-bw.tga', 'decal-64-64-bw-over.tga', 'decal-42-42.tga',
              '1919DecalWShadow.tga', 'leader-lobby.tga']
# formato del 3DFlag: 24 bits sin alfa; leader-lobby: sin comprimir; el resto RLE 32 bits
FLAG_FMT = {'3DFlag.tga': {'type': 10, 'bpp': 24, 'desc': 0}, 'leader-lobby.tga': {'type': 2, 'bpp': 32, 'desc': 8}}
DEFAULT_FMT = {'type': 10, 'bpp': 32, 'desc': 8}

_SHADOWS = {}


def shadow_alpha(name, size, rect):
    """Alfa de la sombra: la mas frecuente entre los paises existentes (o una generada si no hay)."""
    key = name
    if key in _SHADOWS:
        return _SHADOWS[key]
    from collections import Counter
    cnt = Counter()
    for scen in ('The Modern World',) + tuple(scenario_core.scenarios()):
        base = os.path.join(scenario_core.SCEN_ROOT, scen, 'ui', 'art', '2D', 'countries')
        if not os.path.isdir(base):
            continue
        for c in sorted(os.listdir(base))[:120]:
            p = os.path.join(base, c, name)
            try:
                im = Image.open(p).convert('RGBA')
            except Exception:
                continue
            if im.size == size:
                cnt[im.getchannel('A').tobytes()] += 1
        if cnt:
            break
    if cnt:
        a = Image.frombytes('L', size, cnt.most_common(1)[0][0])
    else:   # sin ejemplos: sombra difusa de 3-4 px
        a = Image.new('L', size, 0)
        x0, y0, x1, y1 = rect
        ImageDraw.Draw(a).rectangle((x0 + 1, y0 + 1, x1 + 1, y1 + 1), fill=150)
        a = a.filter(ImageFilter.GaussianBlur(2))
    _SHADOWS[key] = a
    return a


def remove_background(img, tol=28):
    """Quita el fondo uniforme (color de las esquinas) de una imagen sin transparencia."""
    img = img.convert('RGBA')
    px = img.load()
    w, h = img.size
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    if any(c[3] < 250 for c in corners):
        return img      # ya tiene transparencia
    bg = max(set(corners), key=corners.count)
    from collections import deque
    seen = bytearray(w * h)
    q = deque((x, y) for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)))
    near = lambda c: max(abs(c[0] - bg[0]), abs(c[1] - bg[1]), abs(c[2] - bg[2])) <= tol
    while q:
        x, y = q.popleft()
        if x < 0 or y < 0 or x >= w or y >= h or seen[y * w + x]:
            continue
        seen[y * w + x] = 1
        if not near(px[x, y]):
            continue
        px[x, y] = (0, 0, 0, 0)
        q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return img


def shape_mask(shape, size):
    """Mascara de la escarapela generada: escudo, circulo, cuadrado."""
    s = size * 4
    m = Image.new('L', (s, s), 0)
    d = ImageDraw.Draw(m)
    if shape == 'circulo':
        d.ellipse((0, 0, s - 1, s - 1), fill=255)
    elif shape == 'cuadrado':
        d.rectangle((0, 0, s - 1, s - 1), fill=255)
    else:   # escudo: borde superior recto, lados rectos y punta abajo
        top = s * 0.04
        d.polygon([(0, top), (s - 1, top), (s - 1, s * 0.55), (s * 0.5, s - 1), (0, s * 0.55)], fill=255)
        d.ellipse((0, s * 0.18, s - 1, s * 0.98), fill=255)
        d.rectangle((0, top, s - 1, s * 0.58), fill=255)
    return m.resize((size, size), Image.LANCZOS)


def fit(img, size, pad=0):
    """Encaja img (RGBA) en un cuadrado size x size manteniendo proporcion, centrada."""
    img = img.convert('RGBA')
    bb = img.getchannel('A').getbbox()
    if bb:
        img = img.crop(bb)
    box = size - 2 * pad
    k = min(box / img.width, box / img.height)
    im = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
    out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    out.alpha_composite(im, ((size - im.width) // 2, (size - im.height) // 2))
    return out


def gray(img, a=1.0, b=0.0):
    r, g, bl, al = img.convert('RGBA').split()
    l = Image.merge('RGB', (r, g, bl)).convert('L').point(lambda v: max(0, min(255, round(v * a + b))))
    return Image.merge('RGBA', (l, l, l, al))


FLAG_FITS = ('centro', 'bordes', 'izquierda', 'estirar')


def fit_flag(img, mode='centro', aspect=2.0):
    """Lleva una bandera de otra proporcion a la del juego (2:1).
    centro: recorta al centro · bordes: estira la primera y la ultima columna (o fila) de pixeles hasta rellenar ·
    izquierda: la bandera pegada a la izquierda y se rellena repitiendo su ultima columna (banderas tipo Chile) ·
    estirar: deforma la imagen hasta 2:1."""
    w, h = img.size
    if mode == 'estirar' or abs(w / h - aspect) < 0.01:
        return img
    if mode == 'centro':
        if w / h > aspect:
            cw = round(h * aspect)
            return img.crop(((w - cw) // 2, 0, (w - cw) // 2 + cw, h))
        ch = round(w / aspect)
        return img.crop((0, (h - ch) // 2, w, (h - ch) // 2 + ch))
    if w / h < aspect:          # falta ancho
        W = round(h * aspect)
        out = Image.new(img.mode, (W, h))
        x0 = 0 if mode == 'izquierda' else (W - w) // 2
        out.paste(img, (x0, 0))
        right = img.crop((w - 1, 0, w, h))
        if x0 > 0:
            out.paste(img.crop((0, 0, 1, h)).resize((x0, h)), (0, 0))
        if W - x0 - w > 0:
            out.paste(right.resize((W - x0 - w, h)), (x0 + w, 0))
        return out
    H = round(w / aspect)       # falta alto: se estiran la fila de arriba y la de abajo
    out = Image.new(img.mode, (w, H))
    y0 = 0 if mode == 'izquierda' else (H - h) // 2
    out.paste(img, (0, y0))
    if y0 > 0:
        out.paste(img.crop((0, 0, w, 1)).resize((w, y0)), (0, 0))
    if H - y0 - h > 0:
        out.paste(img.crop((0, h - 1, w, h)).resize((w, H - y0 - h)), (0, y0 + h))
    return out


def flag_set(flag, decal=None, shape='escudo', removebg=True, leader=None, crop='estirar', only=None, fit_mode='centro'):
    """Genera {archivo: imagen} con todos los archivos de la carpeta de un pais.

    crop: como entra la bandera en los huecos casi cuadrados (diplomatic, flag-16/19, 48h-64w, multichat):
    'estirar' (lo mas comun en el juego), 'asta' (recorte desde el lado del asta) o 'centro'.
    only: None (todo), 'flag' (sin escarapelas ni lider) o 'decal' (solo escarapelas; flag puede faltar).
    fit_mode: como pasar la bandera a 2:1 (fit_flag)."""
    if only == 'decal':
        if decal is None:
            raise ValueError('falta la imagen de la escarapela')
        return {k: v for k, v in decal_set(decal, removebg).items()}
    flag = flag.convert('RGBA')
    bg = Image.new('RGBA', flag.size, (255, 255, 255, 255))
    bg.alpha_composite(flag)
    flag = fit_flag(bg.convert('RGB'), fit_mode or 'centro')        # las banderas son opacas
    big = flag.resize((512, 256), Image.LANCZOS) if flag.width < 512 else flag.resize((flag.width, flag.width // 2), Image.LANCZOS)
    rs = lambda w, h: big.resize((w, h), Image.LANCZOS)

    def rs_box(w, h):
        if crop == 'estirar' or w / h >= big.width / big.height:
            return rs(w, h)
        cw = round(big.height * w / h)
        x0 = 0 if crop == 'asta' else (big.width - cw) // 2
        return big.crop((x0, 0, x0 + cw, big.height)).resize((w, h), Image.LANCZOS)
    out = {}
    out['3DFlag.tga'] = rs(128, 64).transpose(Image.FLIP_TOP_BOTTOM)    # el juego la lee al reves
    for name, size in FLAG_FULL:
        out[name] = rs(*size)
    for name, size, rect, shadow in FLAG_RECTS:
        x0, y0, x1, y1 = rect
        im = Image.new('RGBA', size, (0, 0, 0, 0))
        if shadow:
            im.putalpha(shadow_alpha(name, size, rect))
        im.paste(rs_box(x1 - x0, y1 - y0).convert('RGBA'), (x0, y0))
        out[name] = im
    mc = Image.new('RGB', (32, 32), (255, 255, 255))     # bandera de 15x15 arriba a la izquierda, fondo blanco
    mc.paste(rs_box(15, 15), (0, 0))
    out['multichat_flag.bmp'] = mc
    if only == 'flag':
        return {k: out[k] for k in FLAG_ORDER if k in out}
    # escarapela / emblema 60x60 dentro de 64x64
    if decal is not None:
        out.update(decal_set(decal, removebg))
    else:
        d60 = rs(60, 60).convert('RGBA')
        d60.putalpha(shape_mask(shape, 60))
        out.update(decal_files(d60))
    if leader is not None:
        out['leader-lobby.tga'] = leader_lobby(leader, big, removebg)
    return {k: out[k] for k in FLAG_ORDER if k in out}


def decal_set(decal, removebg=True):
    d = remove_background(decal) if removebg else decal.convert('RGBA')
    return decal_files(fit(d, 60))


def decal_files(d60):
    """Los 6 archivos de escarapela a partir de la escarapela de 60x60."""
    out = {}
    dec = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    dec.alpha_composite(d60, (2, 2))
    out['decal-64-64.tga'] = dec
    out['decal.tga'] = dec.transpose(Image.FLIP_TOP_BOTTOM)
    out['decal-64-64-bw.tga'] = gray(dec)
    out['decal-64-64-bw-over.tga'] = gray(dec, 0.85, 40)
    d42 = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d42.alpha_composite(d60.resize((40, 40), Image.LANCZOS), (1, 1))
    out['decal-42-42.tga'] = d42
    d19 = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    d19.alpha_composite(d60.resize((19, 19), Image.LANCZOS), (4, 4))
    out['1919DecalWShadow.tga'] = d19
    return out


def leader_lobby(photo, flag, removebg=True):
    """Retrato 272x304 en (1,1) de un lienzo 512x512: la bandera de fondo y la foto delante."""
    W, H = 272, 304
    card = Image.new('RGBA', (W, H), (40, 34, 30, 255))
    card.alpha_composite(flag.resize((W, W // 2), Image.LANCZOS).convert('RGBA'), (0, 20))
    p = photo.convert('RGBA')
    if p.getchannel('A').getextrema()[0] < 250 or removebg:
        p = remove_background(p) if removebg else p
        k = min(W / p.width, (H - 30) / p.height)
        p = p.resize((max(1, round(p.width * k)), max(1, round(p.height * k))), Image.LANCZOS)
        card.alpha_composite(p, ((W - p.width) // 2, H - p.height))
    else:   # foto opaca: recortar para llenar
        k = max(W / p.width, H / p.height)
        p = p.resize((round(p.width * k), round(p.height * k)), Image.LANCZOS)
        card = p.crop(((p.width - W) // 2, 0, (p.width - W) // 2 + W, H))
    out = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
    out.paste(card, (1, 1))
    return out


def countries_dir(scen):
    return os.path.join(scen_dir(scen), 'ui', 'art', '2D', 'countries')


def countries(scen):
    d = countries_dir(scen)
    names = sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x))) if os.path.isdir(d) else []
    players = sorted(f[6:-4] for f in os.listdir(scen_dir(scen)) if f.startswith('player') and f.endswith('.xml'))
    return {'folders': names, 'players': players}


def country_files(scen, name):
    d = os.path.join(countries_dir(scen), safe_name(name))
    out = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if f.lower().endswith(('.tga', '.bmp', '.png')):
                try:
                    im = Image.open(p)
                    out.append({'file': f, 'w': im.width, 'h': im.height, 'mode': im.mode,
                                'rel': os.path.relpath(p, scenario_core.SCEN_ROOT)})
                except Exception:
                    pass
    return out


_FLAGNAMES = {}


def flag_folder(scen, country):
    """Carpeta de banderas de un pais: strFlagName de su Player en gamestate.xml (o el nombre del pais)."""
    gs = os.path.join(scen_dir(scen), 'gamestate.xml')
    key = (gs, os.path.getmtime(gs) if os.path.exists(gs) else 0)
    if key not in _FLAGNAMES:
        m = {}
        if os.path.exists(gs):
            x = open(gs, encoding='utf-8', errors='replace').read()
            for b in re.finditer(r'<object type="Player"[^>]*>(.*?)(?=<object type="Player"|</objects>)', x, re.S):
                n = re.search(r'name="strName" value="([^"]*)"', b.group(1))
                f = re.search(r'name="strFlagName" value="([^"]*)"', b.group(1))
                if n and f:
                    m[n.group(1)] = f.group(1)
        _FLAGNAMES.clear()
        _FLAGNAMES[key] = m
    return _FLAGNAMES[key].get(country) or country


def flag_png(scen, name, files=('flag-16-16.tga', 'flag-19-19.tga', 'diplomatic-flag.tga', 'flag-68-34.tga')):
    """PNG de la bandera pequena de un pais (o None si no tiene carpeta)."""
    d = os.path.join(countries_dir(scen), safe_name(flag_folder(scen, name)))
    for f in files:
        p = os.path.join(d, f)
        if os.path.exists(p):
            img = Image.open(p).convert('RGBA')
            bb = img.getchannel('A').point(lambda v: 255 if v > 200 else 0).getbbox()   # sin la sombra
            if bb:
                img = img.crop(bb)
            b = io.BytesIO()
            img.save(b, 'PNG')
            return b.getvalue()
    return None


def fmt_label(name):
    if not name.lower().endswith('.tga'):
        return name.rsplit('.', 1)[-1].upper() + (' 24 bits' if name.endswith('.bmp') else '')
    f = FLAG_FMT.get(name, DEFAULT_FMT)
    return 'TGA %d bits %s%s' % (f['bpp'], 'RLE' if f['type'] == 10 else 'sin comprimir',
                                  ', invertida' if name in ('3DFlag.tga', 'decal.tga') else '')


def flag_inputs(p):
    flag = from_data_url(p.get('flag'))
    if flag is None and p.get('only') != 'decal':
        raise ValueError('falta la imagen de la bandera')
    return flag_set(flag, from_data_url(p.get('decal')), p.get('shape', 'escudo'), bool(p.get('removebg', True)),
                    from_data_url(p.get('leader')), p.get('crop', 'estirar'), p.get('only'), p.get('fit', 'centro'))


def flag_preview(p):
    return {'files': [{'file': k, 'w': v.width, 'h': v.height, 'fmt': fmt_label(k), 'png': to_data_url(v)}
                      for k, v in flag_inputs(p).items()]}


def flag_write(p):
    scen = p['scen']
    name = safe_name(p['country'])
    d = os.path.join(countries_dir(scen), name)
    files = {}
    for k, v in flag_inputs(p).items():
        files[os.path.join(d, k)] = encode(v, k, FLAG_FMT.get(k, DEFAULT_FMT))
    rep = write_files(files, 'bandera-' + name)
    rep['folder'] = os.path.relpath(d, scenario_core.SCEN_ROOT)
    return rep


# ---------------------------------------------------------------------------- iconos y productos
ICON_SIZES = [('6464', 64, 64), ('4646', 46, 64), ('3636', 36, 64), ('2626', 26, 32)]   # carpeta, icono, lienzo
RESEARCH_SIZES = {'256x256': (256, 256), '128x256': (128, 256), '512x256': (512, 256)}
TABLES = {'unit': ('UnitTemplateIconTable.xml', 'UnitTemplateIcon', 'objUnitTemplateIcons', 'strTemplate'),
          'output': ('FactoryOutputIconTable.xml', 'FactoryOutputIcon', 'objFactoryOutputIcons', 'strName')}


def kebab(name):
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', '-', name)
    return re.sub(r'[^A-Za-z0-9-]+', '-', s).strip('-').lower()


def icon_set(img, removebg=False, pad=0):
    img = remove_background(img) if removebg else img.convert('RGBA')
    out = {}
    for folder, n, canvas in ICON_SIZES:
        c = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
        c.alpha_composite(fit(img, n, round(pad * n / 64)), (0, 0))     # arriba a la izquierda, como los originales
        out[folder] = c
    return out


def research_image(img, size, removebg=False):
    w, h = RESEARCH_SIZES.get(size, (256, 256))
    img = remove_background(img) if removebg else img.convert('RGBA')
    k = min(w / img.width, h / img.height)
    im = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    out.alpha_composite(im, ((w - im.width) // 2, (h - im.height) // 2))
    return out


def _xml_objects(path, typ):
    """[(strName, strIconName)] de los objetos del tipo dado en un XML (lectura sencilla)."""
    if not os.path.exists(path):
        return []
    x = open(path, encoding='utf-8', errors='replace').read()
    res = []
    for m in re.finditer(r'<object type="%s"[^>]*>(.*?)(?=<object type="(?:%s)"|</objects>)' % (typ, typ), x, re.S):
        body = m.group(1)
        n = re.search(r'name="strName" value="([^"]*)"', body)
        ic = re.search(r'name="strIconName" value="([^"]*)"', body)
        if n:
            res.append((n.group(1), ic.group(1) if ic else ''))
    return res


def _table_entries(path, kind):
    _, typ, _, key = TABLES[kind]
    if not os.path.exists(path):
        return {}
    x = open(path, encoding='utf-8', errors='replace').read()
    res = {}
    for m in re.finditer(r'<object type="%s"[^>]*>\s*<property name="%s" value="([^"]*)"/>(.*?)</object>\s*</object>' % (typ, key), x, re.S):
        f = re.search(r'name="fileIcon6464" value="([^"]*)"', m.group(2))
        res[m.group(1)] = f.group(1) if f else ''
    return res


def icon_path_to_rel(scen, v):
    """Valor fileIcon6464 de la tabla -> ruta del archivo (escenario primero, contenido despues)."""
    if not v:
        return None
    v = v.replace('\\', '/')
    m = re.search(r'ui/art/(.*)$', v, re.I)
    if not m:
        return None
    tail = m.group(1)
    p = os.path.join(scen_dir(scen), 'ui', 'art', tail)
    if os.path.exists(p):
        return os.path.relpath(p, scenario_core.SCEN_ROOT)
    p = os.path.join(content_ui(), 'art', tail)
    if os.path.exists(p):
        return '@ui/art/' + tail
    return None


def research_entries(scen):
    """{strName: filePath} de la biblioteca Research_Project_Icon (MediaPack del escenario o del juego)."""
    for mp in (os.path.join(scen_dir(scen), 'ui', 'MediaPack.xml'), os.path.join(content_ui(), 'MediaPack.xml')):
        if os.path.exists(mp):
            x = open(mp, encoding='utf-8', errors='replace').read()
            lib = re.search(r'<object type="MediaLibrary"[^>]*>\s*<property name="strName" value="Research_Project_Icon"/>', x)
            if not lib:
                continue
            seg = x[lib.start():_matching_close(x, lib.start())]
            return {m.group(1): m.group(2) for m in re.finditer(
                r'<property name="strName" value="([^"]*)"/>\s*<property name="filePath" value="([^"]*)"/>', seg)}, os.path.basename(os.path.dirname(mp))
    return {}, None


def icons_info(scen):
    d = scen_dir(scen)
    units = _xml_objects(os.path.join(d, 'sharedDataUnitTemplates.xml'), 'UnitTemplate')
    outs = _xml_objects(os.path.join(d, 'sharedDataFactories.xml'), 'FactoryOutput\\w*')
    res = {}
    for kind, items in (('unit', units), ('output', outs)):
        table = os.path.join(d, 'ui', TABLES[kind][0])
        local = os.path.exists(table)
        ent = _table_entries(table if local else os.path.join(content_ui(), TABLES[kind][0]), kind)
        res[kind] = {'table_in_scenario': local,
                     'items': [{'name': n, 'icon': ic, 'registered': n in ent, 'file': ent.get(n),
                                'rel': icon_path_to_rel(scen, ent.get(n))} for n, ic in items]}
    units_by = {x['name']: x for x in res['unit']['items']}
    for x in res['output']['items']:    # los productos que son unidades usan el icono de su UnitTemplate
        u = units_by.get(x['name'])
        if not x['registered'] and u and u['rel']:
            x['rel'], x['via'] = u['rel'], 'unit'
    rese, where = research_entries(scen)
    projs = _xml_objects(os.path.join(d, 'sharedDataResearch.xml'), 'ResearchProj(?!ect)\\w*')
    res['research'] = {'table_in_scenario': where == 'ui',
                       'items': [{'name': n, 'icon': ic or n, 'registered': (ic or n) in rese, 'file': rese.get(ic or n),
                                  'rel': icon_path_to_rel(scen, rese.get(ic or n))} for n, ic in projs]}
    return res


def _insert_entry(path, kind, name, filebase, label):
    """Anade (o actualiza) la entrada de iconos en la tabla del escenario. Devuelve el texto nuevo."""
    _, typ, objname, key = TABLES[kind]
    x = open(path, 'rb').read().decode('utf-8')
    nl = '\r\n' if '\r\n' in x[:4000] else '\n'
    vals = {'fileIcon' + f: '../../../ui/art/2D\\global\\unit-template-icons\\%s\\%s.tga' % (f, filebase) for f, _, _ in ICON_SIZES}
    pat = re.compile(r'(<object type="%s"[^>]*>\s*<property name="%s" value="%s"/>)(.*?)(</object>\s*</object>)'
                     % (typ, key, re.escape(name)), re.S)
    m = pat.search(x)
    if m:
        body = m.group(2)
        for k, v in vals.items():
            body = re.sub(r'(name="%s" value=")[^"]*(")' % k, lambda mm: mm.group(1) + v + mm.group(2), body)
        return x[:m.start(2)] + body + x[m.end(2):], 'actualizada'
    block = (nl + '\t<!-- %s (editor de imagenes) -->' % label + nl +
             '\t\t<object type="%s" name="%s">' % (typ, objname) + nl +
             '\t\t\t<property name="%s" value="%s"/>' % (key, name) + nl +
             '\t\t\t<object type="UnitTemplateFactoryOutputIconPaths" name="objIconPaths">' + nl +
             ''.join('\t\t\t\t<property name="%s" value="%s"/>' % (k, v) + nl for k, v in vals.items()) +
             '\t\t\t</object>' + nl + '\t\t</object>' + nl)
    m = list(re.finditer(r'</object>\s*</objects>', x))
    if not m:
        raise ValueError('no se reconoce la estructura de %s' % os.path.basename(path))
    i = m[-1].start()
    return x[:i].rstrip() + nl + block + '\t' + x[i:], 'nueva'


def _matching_close(x, start):
    """Indice del </object> que cierra el <object> que empieza en start."""
    depth = 0
    for m in re.finditer(r'<object\b[^>]*?(/?)>|</object>', x[start:]):
        if m.group(0).startswith('</'):
            depth -= 1
            if depth == 0:
                return start + m.start()
        elif not m.group(1):
            depth += 1
    raise ValueError('XML sin cerrar')


def _insert_research(path, name, filebase):
    x = open(path, 'rb').read().decode('utf-8')
    nl = '\r\n' if '\r\n' in x[:4000] else '\n'
    fp = '/../Modern Europe/system/ui/art/2D/MediaPack/Research/%s.tga' % filebase
    lib = re.search(r'<object type="MediaLibrary"[^>]*>\s*<property name="strName" value="Research_Project_Icon"/>', x)
    if not lib:
        raise ValueError('MediaPack.xml sin la biblioteca Research_Project_Icon')
    end = _matching_close(x, lib.start())
    seg = x[lib.start():end]
    m = re.search(r'(<object type="MediaFile" name="objFiles">\s*<property name="strName" value="%s"/>\s*'
                  r'<property name="filePath" value=")[^"]*(")' % re.escape(name), seg)
    if m:
        seg = seg[:m.start()] + m.group(1) + fp + m.group(2) + seg[m.end():]
        return x[:lib.start()] + seg + x[end:], 'actualizada'
    block = ('\t\t\t<object type="MediaFile" name="objFiles">' + nl +
             '\t\t\t\t<property name="strName" value="%s"/>' % name + nl +
             '\t\t\t\t<property name="filePath" value="%s"/>' % fp + nl + '\t\t\t</object>' + nl + '\t\t')
    return x[:lib.start()] + seg.rstrip() + nl + block + x[end:], 'nueva'


def research_write(p, name):
    """Imagen de investigacion de un proyecto (name = su strIconName) y su entrada en ui/MediaPack.xml."""
    scen = p['scen']
    d = scen_dir(scen)
    filebase = kebab(p.get('filebase') or name)
    img = from_data_url(p.get('img'))
    r = research_image(img, p.get('research_size', '256x256'), bool(p.get('removebg')))
    files = {os.path.join(d, 'ui', 'art', '2D', 'MediaPack', 'Research', filebase + '.tga'): tga_bytes(r, {'type': 2, 'bpp': 32, 'desc': 8})}
    notes = []
    if p.get('register', True):
        mp = os.path.join(d, 'ui', 'MediaPack.xml')
        if not os.path.exists(mp):
            src = os.path.join(content_ui(), 'MediaPack.xml')
            os.makedirs(os.path.dirname(mp), exist_ok=True)
            shutil.copy2(src, mp)
            notes.append('MediaPack.xml no existia en el escenario: se copio la del juego')
        new, how = _insert_research(mp, name, filebase)
        files[mp] = new.encode('utf-8')
        notes.append('MediaPack.xml: imagen de investigacion %s (%s)' % (name, how))
    rep = write_files(files, 'investigacion-' + name)
    rep['notes'] = notes
    rep['filebase'] = filebase
    return rep


def icon_preview(p):
    img = from_data_url(p.get('img'))
    if img is None:
        raise ValueError('falta la imagen')
    s = icon_set(img, bool(p.get('removebg')), int(p.get('pad') or 0))
    out = [{'file': '%s/%s.tga' % (k, p.get('filebase') or 'icono'), 'w': v.width, 'h': v.height,
            'fmt': 'TGA 32 bits sin comprimir', 'png': to_data_url(v)} for k, v in s.items()] if p.get('kind') != 'research' else []
    if p.get('research') or p.get('kind') == 'research':
        r = research_image(img, p.get('research_size', '256x256'), bool(p.get('removebg')))
        out.append({'file': 'MediaPack/Research/%s.tga' % (p.get('filebase') or 'icono'), 'w': r.width, 'h': r.height,
                    'fmt': 'TGA 32 bits sin comprimir', 'png': to_data_url(r)})
    return {'files': out}


def icon_write(p):
    scen, kind, name = p['scen'], p['kind'], p['name'].strip()
    if (kind not in TABLES and kind != 'research') or not re.match(r'^[A-Za-z0-9_]+$', name):
        raise ValueError('tipo o nombre no valido')
    if kind == 'research':
        return research_write(p, name)
    filebase = kebab(p.get('filebase') or name)
    img = from_data_url(p.get('img'))
    d = scen_dir(scen)
    fmt = {'type': 2, 'bpp': 32, 'desc': 8}
    files = {}
    for folder, im in icon_set(img, bool(p.get('removebg')), int(p.get('pad') or 0)).items():
        files[os.path.join(d, 'ui', 'art', '2D', 'global', 'unit-template-icons', folder, filebase + '.tga')] = tga_bytes(im, fmt)
    if p.get('research'):
        r = research_image(img, p.get('research_size', '256x256'), bool(p.get('removebg')))
        files[os.path.join(d, 'ui', 'art', '2D', 'MediaPack', 'Research', filebase + '.tga')] = tga_bytes(r, fmt)
    notes = []
    if p.get('register', True):
        table = os.path.join(d, 'ui', TABLES[kind][0])
        if not os.path.exists(table):
            src = os.path.join(content_ui(), TABLES[kind][0])
            text = open(src, 'rb').read().decode('utf-8')
            notes.append('%s no existia en el escenario: se copio la del juego' % TABLES[kind][0])
            tmp = table + '.nuevo'
            os.makedirs(os.path.dirname(table), exist_ok=True)
            open(tmp, 'wb').write(text.encode('utf-8'))
            new, how = _insert_entry(tmp, kind, name, filebase, name)
            os.remove(tmp)
        else:
            new, how = _insert_entry(table, kind, name, filebase, name)
        files[table] = new.encode('utf-8')
        notes.append('%s: entrada %s para %s' % (TABLES[kind][0], how, name))
        if p.get('research'):
            mp = os.path.join(d, 'ui', 'MediaPack.xml')
            if os.path.exists(mp):
                new, how = _insert_research(mp, name, filebase)
                files[mp] = new.encode('utf-8')
                notes.append('MediaPack.xml: imagen de investigacion %s (%s)' % (name, how))
            else:
                notes.append('el escenario no tiene ui/MediaPack.xml: la imagen de investigacion no se registro')
    rep = write_files(files, 'icono-' + name)
    rep['notes'] = notes
    rep['filebase'] = filebase
    return rep


def fetch_url(url, limit=15 * 1024 * 1024):
    """Descarga una imagen de una URL (http/https) que da el usuario y la devuelve como data URL."""
    import urllib.request
    from urllib.parse import urlparse
    u = urlparse((url or '').strip())
    if u.scheme not in ('http', 'https') or not u.netloc:
        raise ValueError('la URL debe empezar por http:// o https://')
    req = urllib.request.Request(url.strip(), headers={'User-Agent': 'Mozilla/5.0 (MH Editor)'})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError('la imagen pesa demasiado (más de 15 MB)')
    if data[:5] == b'<?xml' or b'<svg' in data[:1000]:
        raise ValueError('es un SVG: descárgalo como PNG (por ejemplo, la versión «PNG» de Wikimedia Commons)')
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise ValueError('lo descargado no es una imagen (PNG, JPG, GIF, BMP, TGA, WebP)')
    return {'img': to_data_url(im.convert('RGBA')), 'w': im.width, 'h': im.height}


def nation_status(scen):
    """{nacion: {'color': bool, 'flag': bool, 'folder': strFlagName}} de los Player de gamestate.xml."""
    gs = os.path.join(scen_dir(scen), 'gamestate.xml')
    out = {}
    if not os.path.exists(gs):
        return out
    x = open(gs, encoding='utf-8', errors='replace').read()
    base = countries_dir(scen)
    for b in re.finditer(r'<object type="Player"[^>]*>(.*?)(?=<object type="Player"|</objects>)', x, re.S):
        body = b.group(1)
        n = re.search(r'name="strName" value="([^"]*)"', body)
        if not n:
            continue
        f = re.search(r'name="strFlagName" value="([^"]*)"', body)
        c = re.search(r'name="colCountryColor" value="([^"]*)"', body)
        folder = f.group(1) if f else n.group(1)
        d = os.path.join(base, folder)
        out[n.group(1)] = {'color': bool(c and c.group(1).strip()), 'folder': folder,
                           'flag': os.path.isfile(os.path.join(d, 'flag-16-16.tga')) or os.path.isfile(os.path.join(d, 'flag-19-19.tga'))}
    return out
