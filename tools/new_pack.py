"""Regionpack nuevo desde cero (mundo ficticio): proyecto del editor sin regiones y con el fondo en color mar.

Un mapa «vacío» = un mapa con CERO regiones (regions.bin/borders.brd/regions.nts válidos con 0 elementos): las zonas
sin región son huecos, y el mundo se construye con las herramientas normales (dibujar sobre el hueco o el mar,
importar GeoJSON como regiones nuevas, sumar/restar área). Hasta que no haya al menos una región no se puede instalar.

El regionpack se construye primero como PROYECTO (editor_proyecto_<nombre>, carpeta `base/` con lo que en un regionpack
no depende de las regiones: map.xml sin entradas de regiones, properties.xml, MiniMap.tga vacío, StrategicTerrain.nif y los
312 tiles de OperationalTerrain en color mar, que son enlaces duros a 5 archivos). En el juego no se escribe nada hasta
«Instalar», que crea la carpeta nueva en DisplayLibraries/Maps (editor_core.Project.install).
"""
import json
import os
import re
import shutil

import mhmap
from fix_texture import encode_blocks, tile_name, SIZE, MIPS
import terrain_image
from terrain_image import COLS, ROWS, WORLD

NAME_RE = re.compile(r'^[A-Za-z0-9_-]+$')
SEA_RGBA = (8, 48, 164, 255)       # color del mar de los tiles de World (mediana de OperationalTerrain-15-10)
SUGGESTED = [(6144, 3328), (3072, 1664), (1536, 832)]     # misma proporción que World (360 x 195 grados)


def check_name(name, maps_dir, project_dir=None):
    """Mensaje de error (o None) para el nombre de un regionpack nuevo."""
    if not name or not NAME_RE.match(name):
        return 'nombre no válido (solo letras, números, - y _)'
    low = name.lower()
    if os.path.isdir(maps_dir) and any(d.lower() == low for d in os.listdir(maps_dir)):
        return 'regionpack ya existente: %s' % name
    if project_dir and os.path.exists(project_dir):
        return 'proyecto del editor ya existente para el regionpack: %s' % name
    return None


def sea_color(world_dir):
    """Color del mar de World (mediana de un tile de océano); si no se puede leer, la constante."""
    try:
        import numpy as np
        from fix_texture import decode
        f = os.path.join(world_dir, 'art', 'OperationalTerrain', tile_name(15, 10, MIPS))
        a = np.asarray(decode(open(f, 'rb').read(), SIZE >> MIPS)).reshape(-1, 4)
        return tuple(int(v) for v in np.median(a, axis=0))
    except Exception:
        return SEA_RGBA


def blank_blobs(rgba):
    """Bytes DXT5 del tile liso y de sus 4 mipmaps."""
    from PIL import Image
    out = []
    for lv in range(MIPS + 1):
        s = SIZE >> lv
        blob = encode_blocks(Image.new('RGBA', (s, s), rgba))
        if len(blob) != s * s:
            raise ValueError('codificación DXT5 inesperada (%d bytes para %d px)' % (len(blob), s))
        out.append(blob)
    return out


def strip_map_xml(text):
    """map.xml sin las entradas que citan regiones (RegionRename, CanalRegions, Connected/Disconnected/FoggingLinked...)."""
    i = text.find('<object type="AreaMap"')
    j = text.find('<object ', i + 10) if i >= 0 else -1
    if j < 0:
        return text
    nl = '\r\n' if '\r\n' in text else '\n'
    head = text[:j].rstrip(' \t\r\n')
    return head + nl + '\t</object>' + nl + '</objects>' + nl


def empty_minimap(world_tga):
    d = open(world_tga, 'rb').read()
    w, h = 256, 128
    return d[:18] + bytes((255, 255, 255, 0)) * (w * h) + d[18 + w * h * 4:]


def write_empty_map(xml_dir):
    mhmap.save_map({'regions': [], 'borders': [], 'border_table': [], 'shapes': [], 'shape_table': []}, xml_dir)


def link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def build_base(base, world_dir, rgba=None):
    """Crea <base>/{xml,art} con lo que un regionpack nuevo toma de World y no depende de sus regiones."""
    rgba = rgba or sea_color(world_dir)
    xml, art = os.path.join(base, 'xml'), os.path.join(base, 'art')
    ter = os.path.join(art, 'OperationalTerrain')
    os.makedirs(xml, exist_ok=True)
    os.makedirs(ter, exist_ok=True)
    t = open(os.path.join(world_dir, 'xml', 'map.xml'), encoding='utf-8', errors='replace', newline='').read()
    open(os.path.join(xml, 'map.xml'), 'w', encoding='utf-8', newline='').write(strip_map_xml(t))
    shutil.copy2(os.path.join(world_dir, 'xml', 'properties.xml'), os.path.join(xml, 'properties.xml'))
    open(os.path.join(art, 'MiniMap.tga'), 'wb').write(empty_minimap(os.path.join(world_dir, 'art', 'MiniMap.tga')))
    nif = os.path.join(world_dir, 'art', 'StrategicTerrain.nif')
    if os.path.exists(nif):
        shutil.copy2(nif, art)
    blank = os.path.join(base, '_mar')
    os.makedirs(blank, exist_ok=True)
    blobs = blank_blobs(rgba)
    for lv, b in enumerate(blobs):
        open(os.path.join(blank, 'mar-%d.bin' % lv), 'wb').write(b)
    for c in range(COLS):
        for r in range(ROWS):
            for lv in range(MIPS + 1):
                dst = os.path.join(ter, tile_name(c, r, lv))
                if not os.path.exists(dst):
                    link_or_copy(os.path.join(blank, 'mar-%d.bin' % lv), dst)
    return rgba


def create_project(folder, name, world_dir, rgba=None):
    """Carpeta del proyecto (sin Project aún): pack.json, xml con el mapa vacío y base/."""
    os.makedirs(os.path.join(folder, 'xml'), exist_ok=True)
    write_empty_map(os.path.join(folder, 'xml'))
    json.dump({'pack': name, 'decided': False, 'nuevo': True, 'base': None}, open(os.path.join(folder, 'pack.json'), 'w'))
    # el changelog deja constancia de que NO procede de World (las equivalencias de regiones se anotan luego en él)
    import time
    import changelog_keys
    changelog_keys.dump([{'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': name, 'instalado': False, 'operaciones': ['regionpack_nuevo'],
                'origen': 'desde_cero', 'base': None, 'nota': 'Regionpack creado desde cero: no procede de World',
                'traspasos': [], 'vecindades_nuevas': [], 'centros': {}, 'regiones_nuevas': []}],
              os.path.join(folder, 'changelog.json'))
    return build_base(os.path.join(folder, 'base'), world_dir, rgba)


def pending_packs(project_base):
    """{regionpack: carpeta del proyecto} de los regionpacks nuevos todavía sin instalar (proyectos hermanos de project_base)."""
    parent, prefix = os.path.split(os.path.abspath(project_base))
    prefix += '_'
    out = {}
    if os.path.isdir(parent):
        for d in os.listdir(parent):
            pf = os.path.join(parent, d, 'pack.json')
            if d.startswith(prefix) and os.path.exists(pf):
                try:
                    meta = json.load(open(pf))
                except (OSError, ValueError):
                    continue
                if meta.get('nuevo') and meta.get('pack') == d[len(prefix):]:
                    out[meta['pack']] = os.path.join(parent, d)
    return out


def fill_world(project, mode):
    """Relleno inicial de un mapa vacío: 'sea' = una región de mar del tamaño del mundo («World Ocean»), 'land' = una región de tierra
    («World Land»; se va recortando con Dibujar/Cortar, que también crea mar), 'empty' = nada. El fondo no se toca (queda como esté)."""
    if mode not in ('sea', 'land'):
        return
    x0, y0, x1, y1 = WORLD
    poly = {'type': 'Polygon', 'coordinates': [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}
    asg = {'kind': 'new_region', 'polygon': poly, 'fill': True, 'u_type': 1,
           'name': 'World Ocean' if mode == 'sea' else 'World Land'}
    if mode == 'sea':
        asg['sea'] = True
    rep = project.save({'assigns': [asg], 'paint': False, 'topo': True})
    if rep.get('errors'):
        raise ValueError('; '.join(rep['errors']))


def save_as(project, new_name, new_folder, world_dir, rgba=None):
    """«Guardar regionpack como…» de un regionpack nuevo aún sin instalar: duplica su proyecto (mapa, map.xml, tiles, changelog)
    con otro nombre; el original no se toca. (Los ya instalados usan Project.copy_pack.)"""
    shutil.copytree(project.dir, new_folder, ignore=shutil.ignore_patterns('base', 'history', 'ultimo_cambio.json'))
    json.dump({'pack': new_name, 'decided': False, 'nuevo': True}, open(os.path.join(new_folder, 'pack.json'), 'w'))
    build_base(os.path.join(new_folder, 'base'), world_dir, rgba)
    cl = os.path.join(new_folder, 'changelog.json')
    if os.path.exists(cl):
        import changelog_keys
        data = changelog_keys.load(cl)
        for e in data:
            e['regionpack'] = new_name
        changelog_keys.dump(data, cl)
