"""Imagenes del juego editables desde el editor de escenarios: cada «recurso grafico» (icono de ideologia, recurso,
terreno, produccion, unidad, portada de una nacion, titulo y botones del escenario, cualquier imagen de la UI) con
todas sus variantes (medidas), la version propia del escenario si la hay y la del juego si no.

El juego busca las imagenes de la UI primero en <escenario>/ui/ y luego en Modern Europe/system/UI/ (asi personaliza
The Modern World su interfaz). Las rutas salen de los computeFrom de los XML de la UI del juego, p. ej.
  icons/government-type-icon/<GovTypeTemplate.strIconName>-icon.tga, resources/<Resource>_64_64.tga,
  Terrain/<strTerrain>-small.tga, UI2DSlideoutIndustrialProduction/<FactoryOutput.strIconName>.tga,
  UI2DPopUpMilitaryUnits/unit-icons/<UnitTemplate.strIconName>.tga, UI2DPolicyArea/Domestic/national-info-bg-<strFlagName>.tga.
Al importar, cada variante imita a la existente (la del escenario o la del juego): mismo lienzo, misma zona ocupada
(margenes transparentes), mismo formato (TGA RLE o no, 24/32 bits, BMP).
"""
import io
import os
import re

import numpy as np

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

import image_tools as T
import scenario_core

IMG_EXT = ('.tga', '.bmp', '.png')

# tipo -> [(carpeta bajo UI/, patron, 'prefijo' | 'exacto')]; {k} = clave del objeto en minusculas
KINDS = {
    'ideology': {'label': 'Ideología', 'parts': [('art/2D/icons/government-type-icon', '{k}-icon', 'prefijo'),
                                                  ('art/2D/UI2DSpecialFeedback', 'liberation-{k}', 'exacto'),
                                                  ('art/2D/UI2DPolicyArea/EndTurn', 'notification-end-turn-liberate-{k}', 'exacto')]},
    'resource': {'label': 'Recurso', 'parts': [('art/2D/resources', '{k}', 'prefijo'),
                                                ('art/2D/UI2DPopUpResourceProducer', 'resourceproducer_headerbox_backdrop_{k}', 'exacto'),
                                                ('art/2D/UI2DPopUpResourceProducer', 'resourceproducer_body_icon_{k}', 'exacto'),
                                                ('art/2D/global', '{k}', 'exacto')]},
    'terrain': {'label': 'Terreno', 'parts': [('art/2D/Terrain', '{k}', 'prefijo'), ('art/2D/UI2DRegion', 'top-image-{k}', 'exacto')]},
    'production': {'label': 'Producción (panel de industria)', 'parts': [('art/2D/UI2DSlideoutIndustrialProduction', '{k}', 'exacto')]},
    'uniticon': {'label': 'Unidad (ventana de unidades)', 'parts': [('art/2D/UI2DPopUpMilitaryUnits/unit-icons', '{k}', 'exacto')]},
}
# variantes de referencia cuando un objeto nuevo no tiene ninguna imagen (se copian sus medidas y formato)
REFERENCE = {'ideology': 'democratic', 'resource': 'coal', 'terrain': 'plains', 'production': 'infantry', 'uniticon': 'infantry'}


def ui_dirs(scen):
    return [os.path.join(T.scen_dir(scen), 'ui'), T.content_ui()]


def _listdir(d):
    try:
        return os.listdir(d)
    except OSError:
        return []


def _match(stem, pat, mode):
    s = stem.lower()
    return s == pat or (mode == 'prefijo' and s.startswith(pat) and s[len(pat)] in '-_ ')


def template_dir():
    """Plantilla que va con el editor (no depende de ningun escenario instalado)."""
    return T.plantilla_dir()


def _template_rel(rel):
    """Ruta de la plantilla para una imagen: las de un pais usan la carpeta countries/Plantilla."""
    parts = rel.replace('\\', '/').split('/')
    if len(parts) > 4 and parts[:3] == ['art', '2D', 'countries']:
        parts[3] = 'Plantilla'
    return '/'.join(parts[2:]) if parts[:2] == ['art', '2D'] else '/'.join(parts)      # bajo _imagenes/ (sin art/2D)


def _variant(scen, rel):
    """Una variante: ruta bajo UI/, archivo propio del escenario y del juego (con su formato y medidas)."""
    own = os.path.join(T.scen_dir(scen), 'ui', rel)
    dflt = os.path.join(T.content_ui(), rel)
    v = {'rel': rel.replace('\\', '/'), 'file': os.path.basename(rel), 'own': os.path.isfile(own), 'default': os.path.isfile(dflt)}
    td = template_dir()
    trel = _template_rel(v['rel'])
    if not v['own'] and td and os.path.isfile(os.path.join(td, '_imagenes', *trel.split('/'))):
        v['template'] = '@tpl/_imagenes/' + trel   # se imita la plantilla del editor (fuera de ui/: no se copia a escenarios nuevos)
        v['from_template'] = True
    src = own if v['own'] else dflt if v['default'] else None
    if src:
        v['src'] = os.path.relpath(src, scenario_core.SCEN_ROOT) if v['own'] else '@ui/' + v['rel']
        try:
            im = Image.open(src)
            v['w'], v['h'] = im.size
        except Exception:
            v['w'] = v['h'] = None
    return v


def find_variants(scen, kind, key):
    """Archivos de un objeto: union de los del escenario y los del juego (sin distinguir mayusculas)."""
    k = key.lower()
    seen = {}
    for folder, pat, mode in KINDS[kind]['parts']:
        p = pat.replace('{k}', k)
        for base in ui_dirs(scen):
            for f in _listdir(os.path.join(base, folder)):
                stem, ext = os.path.splitext(f)
                if ext.lower() in IMG_EXT and _match(stem, p, mode):
                    seen.setdefault((folder + '/' + f).lower(), folder + '/' + f)
    return [_variant(scen, r) for r in sorted(seen.values(), key=str.lower)]


def reference_variants(scen, kind, key):
    """Para un objeto sin imagenes: las de un objeto de referencia, renombradas (medidas y formato a imitar)."""
    ref = REFERENCE.get(kind)
    out = []
    for v in find_variants(scen, kind, ref) if ref else []:
        f = re.sub(re.escape(ref), key.lower(), v['file'], count=1, flags=re.I)
        rel = v['rel'][:-len(v['file'])] + f
        nv = _variant(scen, rel)
        nv['template'] = v['src']
        out.append(nv)
    return out


# ------------------------------------------------------------------------------------------ grupos
def nation_groups(scen, country):
    flag = T.flag_folder(scen, country)
    rel = 'art/2D/UI2DPolicyArea/Domestic/national-info-bg-%s.tga' % flag.lower()
    v = _variant(scen, rel)
    if not v['own'] and not v['default']:
        v['template'] = '@ui/art/2D/UI2DPolicyArea/Domestic/national-info-bg.tga'
        v['generic'] = True      # el juego usa la portada generica
    lead = _variant(scen, 'art/2D/countries/%s/leader-lobby.tga' % flag)
    if not lead['own'] and not lead['default']:
        lead['synthetic'] = 'leader-lobby'
    return [{'key': 'cover', 'title': 'Portada (política interior)', 'variants': [v],
             'note': 'national-info-bg-<strFlagName>: la imagen de la nación (suele ser el líder) en Política interior.'},
            {'key': 'leader', 'title': 'Retrato del lobby (multijugador)', 'variants': [lead]}]


def scenario_groups(scen):
    d = T.scen_dir(scen)
    out = []
    for f, title in (('Title.tga', 'Título (lista de escenarios)'), ('Button.tga', 'Botón'), ('ButtonOver.tga', 'Botón con el cursor encima')):
        p = os.path.join(d, f)
        v = {'rel': f, 'file': f, 'own': os.path.isfile(p), 'default': False, 'base': 'scen'}
        if v['own']:
            v['src'] = os.path.relpath(p, scenario_core.SCEN_ROOT)
            v['w'], v['h'] = Image.open(p).size
        out.append({'key': f.split('.')[0].lower(), 'title': title, 'variants': [v]})
    return out


def info(scen, kind, name):
    if kind == 'nation':
        return {'kind': kind, 'name': name, 'label': 'Nación', 'groups': nation_groups(scen, name)}
    if kind == 'scenario':
        return {'kind': kind, 'name': scen, 'label': 'Escenario', 'groups': scenario_groups(scen),
                'display_name': scenario_display_name(scen)}
    if kind == 'ui':
        rel = name.replace('\\', '/').lstrip('/')
        if '..' in rel.split('/'):
            raise ValueError('ruta no valida')
        return {'kind': kind, 'name': rel, 'label': 'Interfaz', 'groups': [{'key': 'ui', 'title': rel, 'variants': [_variant(scen, rel)]}]}
    if kind not in KINDS:
        raise ValueError('tipo desconocido: %s' % kind)
    vs = find_variants(scen, kind, name)
    ref = False
    if not vs:
        vs, ref = reference_variants(scen, kind, name), True
    return {'kind': kind, 'name': name, 'label': KINDS[kind]['label'], 'reference': ref,
            'groups': [{'key': 'files', 'title': KINDS[kind]['label'], 'variants': vs}]}


def scenario_display_name(scen):
    p = os.path.join(T.scen_dir(scen), 'scenarioInfo.xml')
    if os.path.exists(p):
        m = re.search(r'name="strDisplayName" value="([^"]*)"', open(p, encoding='utf-8', errors='replace').read())
        if m:
            return m.group(1)
    return scen


# ------------------------------------------------------------------------------------- imitacion
def _template(scen, v):
    """Imagen y formato a imitar para una variante (propia, del juego o de referencia)."""
    src = (v.get('src') if v.get('own') else None) or v.get('template') or v.get('src')   # propia > plantilla del editor > juego
    if src:
        p = T.resolve_rel(src)
        fmt = T.tga_format(p) if p.lower().endswith('.tga') else {}
        return Image.open(p).convert('RGBA'), fmt
    if v.get('synthetic') == 'leader-lobby':
        im = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
        im.paste((40, 34, 30, 255), (1, 1, 273, 305))
        return im, {'type': 2, 'bpp': 32, 'desc': 8}
    raise ValueError('no hay imagen que imitar para %s' % v['file'])


def imitate(tpl, img, removebg=False):
    """La imagen nueva con el lienzo, la zona ocupada y la transparencia de la plantilla."""
    W, H = tpl.size
    a = tpl.getchannel('A')
    img = img.convert('RGBA')
    if a.getextrema()[0] >= 250:                    # plantilla opaca (fondos, bmp): cubrir todo el lienzo
        return _cover(img, W, H)
    bb = a.point(lambda x: 255 if x > 16 else 0).getbbox() or (0, 0, W, H)
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    inner = a.crop(bb)
    out = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    hist = inner.histogram()
    solid = sum(hist[250:]) / max(1, bw * bh)
    if solid >= 0.85 and (bw * bh) > 0.2 * W * H:      # imagen (portada, boton, bandera) casi opaca dentro del lienzo:
        pic = _cover(img, bw, bh)                       # cubre la zona y conserva los bordes suaves del original
        pa = pic.getchannel('A')
        pic.putalpha(Image.fromarray(np.minimum(np.asarray(pa), np.asarray(inner))))
        out.paste(pic, bb[:2])
        return out
    if removebg:
        img = T.remove_background(img)
    ib = img.getchannel('A').point(lambda x: 255 if x > 16 else 0).getbbox()
    if ib:
        img = img.crop(ib)
    k = min(bw / img.width, bh / img.height)
    im = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
    out.alpha_composite(im, (bb[0] + (bw - im.width) // 2, bb[1] + (bh - im.height) // 2))
    return out


def _cover(img, w, h):
    k = max(w / img.width, h / img.height)
    im = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def brighten(img, pct=8):
    """Version «con el cursor encima»: brillo +pct (escala -100..100, como los editores de imagen; +8 = +20 de 255)."""
    r, g, b, a = img.convert('RGBA').split()
    add = round(255 * pct / 100)
    rgb = Image.merge('RGB', (r, g, b)).point(lambda v: min(255, v + add))
    return Image.merge('RGBA', (*rgb.split(), a))


def text_title(text, size=(1024, 64), font='georgiab.ttf', color='#ffffff', outline='#000000'):
    """Title.tga a partir del nombre del escenario: texto con contorno y sombra, alineado a la izquierda."""
    W, H = size
    out = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    fp = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', font)
    px = int(H * 0.72)
    while px > 10:
        try:
            f = ImageFont.truetype(fp, px)
        except OSError:
            f = ImageFont.load_default()
            break
        if f.getbbox(text)[2] <= W - 60:
            break
        px -= 2
    d = ImageDraw.Draw(out)
    bb = d.textbbox((0, 0), text, font=f, stroke_width=2)
    y = (H - (bb[3] - bb[1])) // 2 - bb[1]
    shadow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((32, y + 2), text, font=f, fill=(0, 0, 0, 170), stroke_width=2, stroke_fill=(0, 0, 0, 170))
    out.alpha_composite(shadow)
    d.text((30, y), text, font=f, fill=color, stroke_width=2, stroke_fill=outline)
    return out


# ----------------------------------------------------------------------------------------- escribir
def _target(scen, v):
    if v.get('base') == 'scen':
        return os.path.join(T.scen_dir(scen), v['rel'])
    return os.path.join(T.scen_dir(scen), 'ui', *v['rel'].split('/'))


def build(p):
    """{ruta: (imagen, formato, archivo)} para la importacion pedida (sin escribir)."""
    scen, kind, name = p['scen'], p['kind'], p.get('name') or ''
    inf = info(scen, kind, name)
    img = T.from_data_url(p.get('img'))
    removebg = bool(p.get('removebg'))
    only = p.get('group')
    out = {}
    if kind == 'scenario':
        groups = {g['key']: g for g in inf['groups']}
        if only == 'title':
            v = groups['title']['variants'][0]
            tpl, fmt = _scen_template(scen, v)
            im = text_title(p['text'], tpl.size, p.get('font') or 'georgiab.ttf', p.get('color') or '#ffffff') if p.get('text') else _title_fit(img, tpl.size)
            out[_target(scen, v)] = (im, fmt or T.DEFAULT_FMT, v['file'])
        elif only in ('button', 'buttonover'):
            v = groups[only]['variants'][0]
            tpl, fmt = _scen_template(scen, v)
            im = imitate(tpl, img, removebg)
            out[_target(scen, v)] = (im, fmt or T.DEFAULT_FMT, v['file'])
            if only == 'button' and p.get('auto_over', True):
                vo = groups['buttonover']['variants'][0]
                tpo, fmo = _scen_template(scen, vo)
                out[_target(scen, vo)] = (brighten(im, float(p.get('bright', 8))), fmo or fmt or T.DEFAULT_FMT, vo['file'])
        else:
            raise ValueError('elige título o botón')
        return out
    if img is None:
        raise ValueError('falta la imagen')
    for g in inf['groups']:
        if only and g['key'] != only:
            continue
        for v in g['variants']:
            tpl, fmt = _template(scen, v)
            out[_target(scen, v)] = (imitate(tpl, img, removebg), fmt, v['file'])
    if not out:
        raise ValueError('no hay variantes que escribir')
    return out


DEFAULT_SCENARIOS = ('The World at War', 'Steps to a Global War', 'The Politics of Appeasement', 'The Limits of Peace',
                     'The End of Diplomacy', 'Conclusion of the War', 'Tutorial', 'Blitzkrieg', 'Clash of Continents',
                     'Rise of the Reich', 'Southern Star')


def _scen_template(scen, v):
    if v.get('src'):
        p = T.resolve_rel(v['src'])
        return Image.open(p).convert('RGBA'), T.tga_format(p)
    td = template_dir()                          # escenario sin el archivo: la plantilla del editor, uno del juego u otro
    if td and os.path.isfile(os.path.join(td, v['file'])):
        q = os.path.join(td, v['file'])
        return Image.open(q).convert('RGBA'), T.tga_format(q)
    others = scenario_core.scenarios()
    others = [o for o in others if o in DEFAULT_SCENARIOS] + [o for o in others if o not in DEFAULT_SCENARIOS and o != scen]
    for other in others:
        q = os.path.join(scenario_core.SCEN_ROOT, other, v['file'])
        if os.path.isfile(q):
            return Image.open(q).convert('RGBA'), T.tga_format(q)
    size = (1024, 64) if v['file'] == 'Title.tga' else (512, 128)
    return Image.new('RGBA', size, (0, 0, 0, 0)), dict(T.DEFAULT_FMT)


def _title_fit(img, size):
    W, H = size
    img = img.convert('RGBA')
    k = min(H / img.height, W / img.width)
    im = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
    out = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    out.alpha_composite(im, (0 if im.width > W - 60 else 30, (H - im.height) // 2))
    return out


def _label(name, fmt):
    if name.lower().endswith('.tga'):
        return 'TGA %d bits %s' % (fmt.get('bpp', 32), 'RLE' if fmt.get('type') == 10 else 'sin comprimir')
    return name.rsplit('.', 1)[-1].upper()


def preview(p):
    files = build(p)
    return {'files': [{'file': f, 'path': os.path.relpath(path, scenario_core.SCEN_ROOT), 'w': im.width, 'h': im.height,
                       'fmt': _label(f, fmt), 'png': T.to_data_url(im)} for path, (im, fmt, f) in files.items()]}


def write(p):
    files = build(p)
    data = {path: T.encode(im, f, fmt if f.lower().endswith('.tga') else None) for path, (im, fmt, f) in files.items()}
    rep = T.write_files(data, 'imagen-%s-%s' % (p['kind'], re.sub(r'[^\w-]+', '_', p.get('name') or p['scen'])[:40]))
    return rep


def export_png(scen, kind, name, group=None):
    """PNG de la variante mas grande (para editarla fuera y volver a importarla)."""
    inf = info(scen, kind, name)
    best = None
    for g in inf['groups']:
        if group and g['key'] != group:
            continue
        for v in g['variants']:
            if v.get('src') and (best is None or (v.get('w') or 0) * (v.get('h') or 0) > (best.get('w') or 0) * (best.get('h') or 0)):
                best = v
    if best is None and kind == 'scenario':     # escenario sin Title/Button: plantilla para editar y volver a importar
        g = next((g for g in inf['groups'] if not group or g['key'] == group), None)
        if g is None:
            raise ValueError('no hay imagen que exportar')
        img, _ = _scen_template(scen, g['variants'][0])
        b = io.BytesIO()
        img.save(b, 'PNG')
        return b.getvalue(), os.path.splitext(g['variants'][0]['file'])[0] + ' - plantilla.png'
    if best is None:
        raise ValueError('no hay imagen que exportar')
    b = io.BytesIO()
    src = best['src'] if best.get('own') or not best.get('template') else best['template']
    Image.open(T.resolve_rel(src)).convert('RGBA').save(b, 'PNG')
    return b.getvalue(), os.path.splitext(best['file'])[0] + '.png'


# --------------------------------------------------------------------------------- catalogo
def _props(path, typ, key):
    if not os.path.exists(path):
        return []
    x = open(path, encoding='utf-8', errors='replace').read()
    out = []
    for m in re.finditer(r'<object type="%s"[^>]*>(.*?)(?=<object type="|</object>)' % typ, x, re.S):
        k = re.search(r'name="%s" value="([^"]*)"' % key, m.group(1))
        if k and k.group(1) not in out:
            out.append(k.group(1))
    return out


def catalog(scen):
    """Todos los tipos de imagen del escenario con sus objetos (clave) y si tienen version propia."""
    d = T.scen_dir(scen)
    sd = lambda f: os.path.join(d, f)
    res = []
    resources = sorted(set(_props(sd('sharedDataFactories.xml'), 'FactoryOutputResource', 'strName')) |
                       {r for f in os.listdir(d) if f.startswith('country') for r in _props(sd(f), 'Producer', 'strResource')})
    groups = [
        ('ideology', 'Ideologías (GovTypeTemplate.strIconName)', _props(sd('sharedData.xml'), 'GovTypeTemplate', 'strIconName')),
        ('resource', 'Recursos', resources),
        ('terrain', 'Terrenos (strTerrain)', [t for t in _props(sd('sharedData.xml'), 'TerrainType', 'strTerrain')]),
        ('production', 'Producción: panel de industria (FactoryOutput/FactoryTemplate.strIconName)',
         sorted(set(_props(sd('sharedDataFactories.xml'), r'Factory\w+', 'strIconName')))),
        ('uniticon', 'Unidades: ventana de unidades (UnitTemplate.strIconName)', sorted(set(_props(sd('sharedDataUnitTemplates.xml'), 'UnitTemplate', 'strIconName')))),
    ]
    for kind, title, keys in groups:
        items = []
        for k in keys:
            vs = find_variants(scen, kind, k)
            if not vs and kind == 'resource':
                continue        # productos de tipo recurso sin imagen propia (p. ej. Industrial Food)
            items.append({'name': k, 'n': len(vs), 'own': sum(1 for v in vs if v['own']),
                          'thumb': next((v['src'] for v in sorted(vs, key=lambda v: -(v.get('w') or 0)) if v.get('src')), None)})
        res.append({'kind': kind, 'title': title, 'items': items})
    return res


def ui_list(scen, rel=''):
    """Carpetas e imagenes de la UI (del juego y del escenario), marcando las personalizadas en el escenario."""
    rel = rel.replace('\\', '/').strip('/')
    if '..' in rel.split('/'):
        raise ValueError('ruta no valida')
    rel = rel or 'art/2D'
    dirs, files = {}, {}
    for own, base in ((True, os.path.join(T.scen_dir(scen), 'ui')), (False, T.content_ui())):
        for f in _listdir(os.path.join(base, rel)):
            p = os.path.join(base, rel, f)
            if os.path.isdir(p):
                e = dirs.setdefault(f.lower(), {'name': f, 'own': 0})
                if own:
                    e['own'] += sum(len(fs) for _, _, fs in os.walk(p))
            elif os.path.splitext(f)[1].lower() in IMG_EXT:
                e = files.setdefault(f.lower(), {'name': f, 'own': False, 'default': False})
                e['own' if own else 'default'] = True
    return {'rel': rel, 'dirs': sorted(dirs.values(), key=lambda e: e['name'].lower()),
            'files': sorted(files.values(), key=lambda e: e['name'].lower())}


def ui_own(scen):
    """Imagenes de la UI que el escenario personaliza (su carpeta ui/art), sin las banderas de paises."""
    base = os.path.join(T.scen_dir(scen), 'ui')
    out = []
    for root, ds, fs in os.walk(os.path.join(base, 'art')):
        r = os.path.relpath(root, base).replace('\\', '/')
        if r.startswith('art/2D/countries') or r.startswith('art/3D'):
            continue
        for f in fs:
            if os.path.splitext(f)[1].lower() in IMG_EXT:
                out.append({'rel': r + '/' + f, 'default': os.path.isfile(os.path.join(T.content_ui(), r, f))})
    return sorted(out, key=lambda e: e['rel'].lower())
