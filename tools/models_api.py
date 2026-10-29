"""API del visor/editor de modelos 3D (página /modelos).

Escribir en el escenario solo con una acción explícita del usuario («Guardar en el escenario»): el .nif nuevo va a
scenarios/<Esc>/ui/art/3D/Custom/<Sprite>.nif (más su .kf) y el Sprite del SpriteLib del escenario pasa a apuntar a
«/../Modern Europe/system/ui/art/3D/Custom/<Sprite>.nif» (el juego busca esa ruta primero en el escenario). El cambio
del SpriteLib queda en memoria hasta «Guardar» del editor de escenarios. Si ya existía el .nif, se respalda antes.
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
    roots = [os.path.normcase(os.path.abspath(sc.GAME)), os.path.normcase(os.path.abspath(sc.SCEN_ROOT)),
             os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')))]
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
    """Sprites de unidades del escenario con su .nif y origen."""
    r = sprite_scale.sprites(scen)
    rows = [x for x in r['sprites'] if x['file'] != 'World.xml']
    own = {x['name'] for x in rows if x['where'] == 'scenario'}
    rows = [x for x in rows if x['where'] == 'scenario' or x['name'] not in own]   # el SpriteLib del escenario manda
    return {'models': [{k: x[k] for k in ('id', 'name', 'kind', 'where', 'model', 'model_label', 'own_tex', 'nif')} for x in rows]}


def kf_for(path):
    """.kf junto al .nif; si el .nif es del escenario y no lo trae, el del juego en la misma ruta."""
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


def tex_png(path, block):
    n = load(path)
    img, _ = M.texture_image(n, int(block), os.path.dirname(path))
    if img is None:
        raise ValueError('textura no disponible')
    b = io.BytesIO()
    img.save(b, 'PNG')
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
    """Guarda n como Custom/<Sprite>.nif en el escenario (con .kf) y apunta el Sprite ahí (en memoria)."""
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
    N.Nif.parse(data)       # comprobación: se vuelve a leer
    with open(dst, 'wb') as f:
        f.write(data)
    notes.append('escrito %s' % os.path.relpath(dst, sc.SCEN_ROOT))
    # .kf (animaciones Attack/Move/Idle) copiado al lado y AnimationData apuntando a él
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
    """p: {path, block, png, sprite_id?, embed?}. Sin sprite_id solo devuelve el .glb de vista previa."""
    path = _allowed(p['path'])
    n = N.Nif.load(path)
    img = _img(p['png'])
    M.set_texture(n, int(p['block']), img, embed=p.get('embed', True))
    n.compact()
    if not p.get('sprite_id'):
        return {'glb': base64.b64encode(M.export_glb(n, os.path.dirname(path))).decode()}
    return {'notes': _write_to_scenario(s, p['sprite_id'], n, path)}


def import_model(s, p):
    """p: {template(path .nif), file(b64), ext('glb'|'gltf'|'obj'|'zip'), keep[], target_size?, sprite_id?}"""
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
    """Guarda solo los SpriteLib*.xml del escenario cambiados por el visor (con respaldo, como «Guardar»)."""
    st = sc.STORE
    paths = [p for p in s.paths if p in st.dirty and os.path.basename(p).startswith('SpriteLib')]
    if not paths:
        return ['no hay cambios de SpriteLib sin guardar']
    r = st.save(paths)
    return ['guardado: %s' % ', '.join(os.path.basename(x) for x in r['written'])]


# ---------------------------------------------------------------- validación de unidades de tierra
# Cada plantilla de tierra necesita una entrada en tres tablas de DisplayLibraries: sin la de UnitTemplatesLand
# (y Combat) sale con un modelo genérico; sin la de UnitTemplatesLandDecals sale sin la base con la bandera (decal).
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
    """Avisos: plantillas de tierra del escenario sin entrada en las tablas de modelo/decal, o que apuntan a un Sprite inexistente."""
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
    # las plantillas del juego base ya traen sus entradas (tanques y vehículos llevan la bandera en su propio .nif):
    # solo se revisan las plantillas nuevas del escenario
    base = _xml_values(os.path.join(sc.GAME, 'Modern Europe', 'system', 'DisplayLibraries', 'SpriteMaps', LAND_TABLES[0][0]), 'strKey') or set()
    new = sorted(t for t in templates if t not in base)
    out = []
    for fname, what in LAND_TABLES:
        p = _display_file(scen_dir, fname)
        keys = p and _xml_values(p, 'strKey')
        if keys is None:
            continue
        miss = [t for t in new  # el decal lo pide la infantería (sus modelos no traen NationLogo); los vehículos lo llevan en su .nif
                if t not in keys and ('Decals' not in fname or templates[t] == 'UNIT_CATEGORY_INFANTRY')]
        if miss:
            out.append({'level': 'aviso', 'id': None, 'fix': None, 'templates': miss, 'table': fname,
                        'msg': '%d unidad(es) sin %s: falta su entrada en %s/%s (SpriteRefName%s): %s'
                               % (len(miss), what, 'DisplayLibraries' if p.startswith(scen_dir) else 'DisplayLibraries del juego',
                                  fname, ' «Infantry Base»' if 'Decals' in fname else ' al Sprite de su modelo', ', '.join(miss))})
    return out
