"""New regionpack from scratch (fictional world): editor project with no regions and the background in sea color.

An «empty» map = a map with ZERO regions (valid regions.bin/borders.brd/regions.nts with 0 elements): areas
without a region are holes, and the world is built with the normal tools (draw over the hole or the sea,
import GeoJSON as new regions, add/subtract area). Until there is at least one region it cannot be installed.

The regionpack is first built as a PROJECT (editor_proyecto_<nombre>, `base/` folder with what in a regionpack
does not depend on regions: map.xml without region entries, properties.xml, empty MiniMap.tga, StrategicTerrain.nif and the
312 OperationalTerrain tiles in sea color, which are hard links to 5 files). Nothing is written to the game until
«Instalar», which creates the new folder in DisplayLibraries/Maps (editor_core.Project.install).
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
SEA_RGBA = (8, 48, 164, 255)       # World tiles' sea color (median of OperationalTerrain-15-10)
SUGGESTED = [(6144, 3328), (3072, 1664), (1536, 832)]     # same proportion as World (360 x 195 degrees)


def check_name(name, maps_dir, project_dir=None):
    """Error message (or None) for a new regionpack's name."""
    if not name or not NAME_RE.match(name):
        return 'nombre no válido (solo letras, números, - y _)'
    low = name.lower()
    if os.path.isdir(maps_dir) and any(d.lower() == low for d in os.listdir(maps_dir)):
        return 'regionpack ya existente: %s' % name
    if project_dir and os.path.exists(project_dir):
        return 'proyecto del editor ya existente para el regionpack: %s' % name
    return None


def sea_color(world_dir):
    """World's sea color (median of an ocean tile); if it cannot be read, the constant."""
    try:
        import numpy as np
        from fix_texture import decode
        f = os.path.join(world_dir, 'art', 'OperationalTerrain', tile_name(15, 10, MIPS))
        a = np.asarray(decode(open(f, 'rb').read(), SIZE >> MIPS)).reshape(-1, 4)
        return tuple(int(v) for v in np.median(a, axis=0))
    except Exception:
        return SEA_RGBA


def blank_blobs(rgba):
    """DXT5 bytes of the plain tile and its 4 mipmaps."""
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
    """map.xml without the entries citing regions (RegionRename, CanalRegions, Connected/Disconnected/FoggingLinked...)."""
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
    """Creates <base>/{xml,art} with what a new regionpack takes from World that does not depend on its regions."""
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
    """Project folder (no Project yet): pack.json, xml with the empty map and base/."""
    os.makedirs(os.path.join(folder, 'xml'), exist_ok=True)
    write_empty_map(os.path.join(folder, 'xml'))
    json.dump({'pack': name, 'decided': False, 'nuevo': True, 'base': None}, open(os.path.join(folder, 'pack.json'), 'w'))
    # the changelog records that it does NOT come from World (region equivalences are noted in it later)
    import time
    import changelog_keys
    changelog_keys.dump([{'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': name, 'instalado': False, 'operaciones': ['regionpack_nuevo'],
                'origen': 'desde_cero', 'base': None, 'nota': 'Regionpack creado desde cero: no procede de World',
                'traspasos': [], 'vecindades_nuevas': [], 'centros': {}, 'regiones_nuevas': []}],
              os.path.join(folder, 'changelog.json'))
    return build_base(os.path.join(folder, 'base'), world_dir, rgba)


def pending_packs(project_base):
    """{regionpack: project folder} of the new regionpacks not yet installed (sibling projects of project_base)."""
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
    """Initial fill of an empty map: 'sea' = a world-sized sea region («World Ocean»), 'land' = a land region
    («World Land»; trimmed with Dibujar/Cortar, which also creates sea), 'empty' = nothing. The background is untouched (stays as is)."""
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
    """«Guardar regionpack como…» of a new regionpack not yet installed: duplicates its project (map, map.xml, tiles, changelog)
    under another name; the original is untouched. (Installed ones use Project.copy_pack.)"""
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
