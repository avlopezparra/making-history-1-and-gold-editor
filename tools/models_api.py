"""API of the 3D model viewer/editor (/modelos page).

Writing to the scenario only on an explicit user action («Guardar en el escenario»): the new .nif goes to
scenarios/<Esc>/ui/art/3D/Custom/<Sprite>.nif (plus its .kf) and the Sprite in the scenario's SpriteLib is pointed to
«/../Modern Europe/system/ui/art/3D/Custom/<Sprite>.nif» (the game looks for that path first in the scenario). The SpriteLib
change stays in memory until the scenario editor's «Guardar». If the .nif already existed, it is backed up first.
"""
import base64
import io
import os
import re
import shutil
import time
import zipfile

import models3d
import nif as N
import nif_mesh as M
import scenario_core as sc
import sprite_scale
from scenario_core import prop

_CACHE = {}


def _allowed(path):
    p = os.path.normcase(os.path.abspath(path))
    # data folder: MH_ROOT (in MHEditor.exe, __file__/.. is the program folder, not the data one: .nif files were rejected)
    data = os.environ.get('MH_ROOT') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    roots = [os.path.normcase(os.path.abspath(sc.GAME)), os.path.normcase(os.path.abspath(sc.SCEN_ROOT)),
             os.path.normcase(os.path.abspath(data))]
    if not any(p.startswith(r + os.sep) for r in roots) or not p.endswith('.nif'):
        raise ValueError('ruta no permitida: %s' % path)
    return os.path.abspath(path)


def load(path):
    path = _allowed(path)
    st = os.stat(path)
    key = (path, st.st_mtime, st.st_size)
    if key not in _CACHE:
        if len(_CACHE) > 8:
            _CACHE.clear()
        _CACHE[key] = N.Nif.load(path)
    return _CACHE[key]


def models(scen):
    """Scenario unit sprites with their .nif and origin."""
    r = sprite_scale.sprites(scen)
    rows = [x for x in r['sprites'] if x['file'] != 'World.xml']
    own = {x['name'] for x in rows if x['where'] == 'scenario'}
    rows = [x for x in rows if x['where'] == 'scenario' or x['name'] not in own]   # the scenario's SpriteLib takes precedence
    return {'models': [{k: x[k] for k in ('id', 'name', 'kind', 'where', 'model', 'model_label', 'own_tex', 'nif')} for x in rows]}


def kf_for(path):
    """.kf next to the .nif; if the .nif is the scenario's and it does not ship one, the game's at the same path."""
    kf = os.path.splitext(path)[0] + '.kf'
    if os.path.exists(kf):
        return kf
    rel = os.path.relpath(kf, sc.SCEN_ROOT)
    if not rel.startswith('..'):
        g = os.path.join(sc.GAME, 'Modern Europe', 'system', rel.split(os.sep, 1)[1])
        if os.path.exists(g):
            return g
    return None


def info(path):
    n = load(path)
    s = M.scene(n, os.path.dirname(path))
    kf = kf_for(path)
    return {'path': path, 'version': '%d.%d.%d.%d' % tuple(n.ver >> k & 255 for k in (24, 16, 8, 0)), 'blocks': len(n.blocks),
            'nodes': [{k: v for k, v in x.items() if k in ('id', 'name', 'parent', 'hidden')} for x in s['nodes']],
            'shapes': [{'id': x['id'], 'name': x['name'], 'parent': x['parent'], 'verts': len(x['pos']), 'tris': len(x['tris']), 'tex': x['tex'],
                        'hidden': x['hidden'], 'skinned': bool(x['skin'])} for x in s['shapes']],
            'textures': M.textures_list(n, os.path.dirname(path)), 'kf': bool(kf),
            'bones': sorted({n.blocks[b].get('Name') and M.name(n.blocks[b]) for x in s['shapes'] if x['skin'] for b in x['skin']['bones']})}


def glb(path):
    return M.export_glb(load(path), os.path.dirname(path))


def tex_png(path, block, fmt='png'):
    n = load(path)
    img, _ = M.texture_image(n, int(block), os.path.dirname(path))
    if img is None:
        raise ValueError('textura no disponible')
    b = io.BytesIO()
    img.save(b, 'TGA' if fmt == 'tga' else 'PNG')
    return b.getvalue()


def obj_zip(path):
    base = os.path.splitext(os.path.basename(path))[0]
    files = M.export_obj(load(path), os.path.dirname(path), base)
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return b.getvalue()


def _img(b64):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(b64.split(',', 1)[-1]))).convert('RGBA')


def _safe(name):
    return re.sub(r'[^\w\- ]+', '_', name).strip() or 'modelo'


def _write_to_scenario(s, sprite_id, n, src_path):
    """Saves n as Custom/<Sprite>.nif in the scenario (with .kf) and points the Sprite there (in memory)."""
    st = sc.STORE
    el = st.get(int(sprite_id))
    if el.get('type') != 'Sprite':
        raise ValueError('no es un Sprite')
    path_xml = st.doc_of.get(el)
    if not path_xml or os.path.normcase(os.path.dirname(os.path.dirname(path_xml))) != os.path.normcase(s.dir) and \
            not os.path.normcase(path_xml).startswith(os.path.normcase(s.dir) + os.sep):
        raise ValueError('el Sprite no es del SpriteLib del escenario: el escenario necesita su propio DisplayLibraries/SpriteLib*.xml')
    nm = _safe(prop(el, 'strName'))
    rel = 'ui/art/3D/Custom/%s.nif' % nm
    dst = os.path.join(s.dir, *rel.split('/'))
    notes = []
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for p in (dst, os.path.splitext(dst)[0] + '.kf'):
        if os.path.exists(p):
            bk = os.path.join(sc.BACKUP_ROOT, 'modelos', stamp, os.path.relpath(p, sc.SCEN_ROOT))
            os.makedirs(os.path.dirname(bk), exist_ok=True)
            shutil.copy2(p, bk)
            notes.append('respaldo: %s' % bk)
    data = n.to_bytes()
    N.Nif.parse(data)       # check: read back
    with open(dst, 'wb') as f:
        f.write(data)
    notes.append('escrito %s' % os.path.relpath(dst, sc.SCEN_ROOT))
    # .kf (Attack/Move/Idle animations) copied alongside and AnimationData pointing to it
    src_kf = kf_for(src_path) or ''
    new_ref = '/../Modern Europe/system/' + rel
    if os.path.exists(src_kf) and os.path.normcase(src_kf) != os.path.normcase(os.path.splitext(dst)[0] + '.kf'):
        shutil.copy2(src_kf, os.path.splitext(dst)[0] + '.kf')
        notes.append('copiado %s.kf' % nm)
    st.set_prop(el, 'fileName', new_ref)
    for a in el.iter('object'):
        if a.get('type') == 'AnimationData' and prop(a, 'fileName'):
            st.set_prop(a, 'fileName', new_ref[:-4] + '.kf')
    notes.append('Sprite «%s» -> %s (falta «Guardar»)' % (prop(el, 'strName'), new_ref))
    return notes


def set_texture(s, p):
    """p: {path, block, png, sprite_id?, embed?}. Without sprite_id it only returns the preview .glb."""
    path = _allowed(p['path'])
    n = N.Nif.load(path)
    img = _img(p['png'])
    M.set_texture(n, int(p['block']), img, embed=p.get('embed', True))
    n.compact()
    if not p.get('sprite_id'):
        return {'glb': base64.b64encode(M.export_glb(n, os.path.dirname(path))).decode()}
    return {'notes': _write_to_scenario(s, p['sprite_id'], n, path)}


def find_blender():
    """blender.exe: MH_BLENDER variable, PATH, or the usual install folders (installer and Steam)."""
    import glob
    cands = [os.environ.get('MH_BLENDER'), shutil.which('blender')]
    for pat in (os.path.join(r'C:\Program Files', 'Blender Foundation', '*', 'blender.exe'),
                os.path.join(r'C:\Program Files (x86)', 'Steam', 'steamapps', 'common', 'Blender', 'blender.exe'),
                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Blender Foundation', '*', 'blender.exe')):
        cands += sorted(glob.glob(pat), reverse=True)   # newest version first
    return next((c for c in cands if c and os.path.isfile(c)), None)


def blend_to_glb(raw):
    """.blend -> .glb with Blender in the background (only Blender reads the .blend format)."""
    import subprocess
    import tempfile
    exe = find_blender()
    if not exe:
        raise ValueError('Para importar .blend hace falta Blender instalado (blender.org o Steam). '
                         'También puedes exportar desde Blender a .glb (Archivo › Exportar › glTF 2.0) e importar ese .glb.')
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, 'in.blend'), os.path.join(d, 'out.glb')
        open(src, 'wb').write(raw)
        r = subprocess.run([exe, '--background', src, '--python-expr',
                            'import bpy,sys; bpy.ops.export_scene.gltf(filepath=sys.argv[-1], export_format="GLB", export_skins=True, export_animations=False)',
                            '--', dst], capture_output=True, text=True, timeout=300,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if not os.path.exists(dst):
            raise ValueError('Blender no pudo convertir el .blend: ' + (r.stderr or r.stdout)[-600:])
        return open(dst, 'rb').read()


def import_model(s, p):
    """p: {template(path .nif), file(b64), ext('glb'|'gltf'|'obj'|'zip'|'nif'|'blend'), keep[], target_size?, sprite_id?}"""
    path = _allowed(p['template'])
    n = N.Nif.load(path)
    raw = base64.b64decode(p['file'].split(',', 1)[-1])
    ext = p.get('ext', 'glb').lower()
    if ext == 'zip':
        z = zipfile.ZipFile(io.BytesIO(raw))
        files = {os.path.basename(k): z.read(k) for k in z.namelist() if not k.endswith('/')}
        g = next((k for k in files if k.lower().endswith(('.glb', '.gltf'))), None)
        o = next((k for k in files if k.lower().endswith('.obj')), None)
        if g:
            meshes = M.load_gltf_meshes(files[g])
        elif o:
            meshes = M.load_obj_meshes(files[o].decode('utf-8', 'replace'), files)
        else:
            raise ValueError('el .zip no tiene .glb, .gltf ni .obj')
    elif ext in ('glb', 'gltf'):
        meshes = M.load_gltf_meshes(raw)
    elif ext == 'blend':
        meshes = M.load_gltf_meshes(blend_to_glb(raw))
    elif ext == 'obj':
        meshes = M.load_obj_meshes(raw.decode('utf-8', 'replace'), {})
    elif ext == 'nif':
        meshes = M.load_nif_meshes(N.Nif.parse(raw), axes=p.get('axes') or 'mh')
    else:
        raise ValueError('formato no soportado: %s' % ext)
    keep = tuple(p.get('keep') or M.KEEP_DEFAULT)
    r = M.import_meshes(n, meshes, keep=keep, target_size=float(p['target_size']) if p.get('target_size') else None, fit=p.get('fit', True),
                        default_parent=p.get('parent') or None)
    r['placed'] += M.fit_attachments(n)
    out = {'result': r}
    if p.get('sprite_id'):
        out['notes'] = _write_to_scenario(s, p['sprite_id'], n, path)
    else:
        out['glb'] = base64.b64encode(M.export_glb(n, os.path.dirname(path))).decode()
    return out


def save_spritelib(s):
    """Saves only the scenario's SpriteLib*.xml changed by the viewer (with backup, like «Guardar»)."""
    st = sc.STORE
    paths = [p for p in s.paths if p in st.dirty and os.path.basename(p).startswith('SpriteLib')]
    if not paths:
        return ['no hay cambios de SpriteLib sin guardar']
    r = st.save(paths)
    return ['guardado: %s' % ', '.join(os.path.basename(x) for x in r['written'])]


# ---------------------------------------------------------------- land unit validation
# Each land template needs an entry in three DisplayLibraries tables: without the UnitTemplatesLand one
# (and Combat) it shows a generic model; without the UnitTemplatesLandDecals one it shows without the flag base (decal).
LAND_TABLES = (('MKDTableUnitTemplatesLand.xml', 'modelo en el mapa'),
               ('MKDTableUnitTemplatesLandCombat.xml', 'modelo en combate'),
               ('MKDTableUnitTemplatesLandDecals.xml', 'decal (base con la bandera)'))


def _xml_values(path, name):
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    return {e.get('value') for e in root.iter('property') if e.get('name') == name and e.get('value')}


def _display_file(scen_dir, fname):
    for d in (os.path.join(scen_dir, 'DisplayLibraries'), os.path.join(sc.GAME, 'Modern Europe', 'system', 'DisplayLibraries', 'SpriteMaps')):
        p = os.path.join(d, fname)
        if os.path.exists(p):
            return p
    return None


def land_display_issues(scen_dir):
    """Warnings: scenario land templates without an entry in the model/decal tables, or pointing to a nonexistent Sprite."""
    import xml.etree.ElementTree as ET
    templates = {}
    for f in os.listdir(scen_dir):
        if f.startswith('sharedData') and f.endswith('.xml'):
            try:
                root = ET.parse(os.path.join(scen_dir, f)).getroot()
            except ET.ParseError:
                continue
            for o in root.iter('object'):
                if o.get('type') == 'UnitTemplate':
                    p = {e.get('name'): e.get('value') for e in o.findall('property')}
                    if p.get('eType') == 'UNIT_TYPE_ARMY' and p.get('strName'):
                        templates[p['strName']] = p.get('eUnitCategory')
    # the base game templates already have their entries (tanks and vehicles carry the flag in their own .nif):
    # only the scenario's new templates are checked
    base = _xml_values(os.path.join(sc.GAME, 'Modern Europe', 'system', 'DisplayLibraries', 'SpriteMaps', LAND_TABLES[0][0]), 'strKey') or set()
    new = sorted(t for t in templates if t not in base)
    out = []
    for fname, what in LAND_TABLES:
        p = _display_file(scen_dir, fname)
        keys = p and _xml_values(p, 'strKey')
        if keys is None:
            continue
        miss = [t for t in new  # the decal is required by infantry (their models lack NationLogo); vehicles carry it in their .nif
                if t not in keys and ('Decals' not in fname or templates[t] == 'UNIT_CATEGORY_INFANTRY')]
        if miss:
            out.append({'level': 'aviso', 'id': None, 'fix': None, 'templates': miss, 'table': fname,
                        'msg': '%d unidad(es) sin %s: falta su entrada en %s/%s (SpriteRefName%s): %s'
                               % (len(miss), what, 'DisplayLibraries' if p.startswith(scen_dir) else 'DisplayLibraries del juego',
                                  fname, ' «Infantry Base»' if 'Decals' in fname else ' al Sprite de su modelo', ', '.join(miss))})
    return out
