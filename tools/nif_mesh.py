"""Mallas, texturas y huesos de un NIF de Making History; exportar a glTF (.glb) / OBJ e importar desde glTF / OBJ.

Convenciones del juego (modelos de unidades):
- Jerarquía SceneNode > <Unidad> > <Unidad> NonAccum > AnimNull > (Turret, Parts...). Los .kf animan nodos por nombre.
- La forma «NationLogo» lleva la textura <País>-Decal.tga: el juego la cambia por la insignia del país.
- Texturas incrustadas (NiPixelData RGB/RGBA sin compresión) o externas (Use External = 1, junto al .nif).
- Y hacia arriba, como glTF. En el .glb todo cuelga de un nodo raíz «MH_Zup» (identidad).
"""
import io
import json
import math
import os
import struct

import numpy as np

import nif as N

ZUP = np.eye(4)   # los modelos de MH ya tienen Y arriba (igual que glTF)


# ---------------------------------------------------------------- transformaciones
def rot(m):
    # NIF guarda la matriz traspuesta respecto a la de columna (v' = R·v): se comprobó con la piel de la infantería
    return np.array([[m['m11'], m['m21'], m['m31']], [m['m12'], m['m22'], m['m32']], [m['m13'], m['m23'], m['m33']]], float)


def set_rot(r):
    return {'m11': float(r[0, 0]), 'm21': float(r[0, 1]), 'm31': float(r[0, 2]), 'm12': float(r[1, 0]), 'm22': float(r[1, 1]),
            'm32': float(r[1, 2]), 'm13': float(r[2, 0]), 'm23': float(r[2, 1]), 'm33': float(r[2, 2])}


def vec(v):
    return np.array([v['x'], v['y'], v['z']], float)


def set_vec(v):
    return {'x': float(v[0]), 'y': float(v[1]), 'z': float(v[2])}


def trs(t, r, s):
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def local(b):
    return trs(vec(b['Translation']), rot(b['Rotation']), b['Scale'])


def niTransform(x):
    return trs(vec(x['Translation']), rot(x['Rotation']), x['Scale'])


def split(m):
    """matriz 4x4 -> (t, R, s) con escala uniforme (la de NIF)."""
    t = m[:3, 3].copy()
    a = m[:3, :3]
    s = float(np.cbrt(abs(np.linalg.det(a)))) or 1.0
    return t, a / s, s


def name(b):
    return N.string(b.get('Name', '')) if 'Name' in b else ''


# ---------------------------------------------------------------- lectura
def parents(n):
    par = {}
    for i, b in enumerate(n.blocks):
        for c in b.get('Children', []) if b['_type'] == 'NiNode' or 'Children' in b else []:
            if c >= 0:
                par[c] = i
    return par


def world(n, i, par, cache):
    if i not in cache:
        m = local(n.blocks[i])
        cache[i] = world(n, par[i], par, cache) @ m if i in par else m
    return cache[i]


def texture_image(n, src_index, nif_dir=None):
    """NiSourceTexture -> (PIL.Image RGBA, nombre de archivo)."""
    from PIL import Image
    st = n.blocks[src_index]
    fname = N.string(st.get('File Name', ''))
    if st.get('Use External') == 0 and st.get('Pixel Data', -1) >= 0:
        pd = n.blocks[st['Pixel Data']]
        mm = pd['Mipmaps'][0]
        w, h, bpp = mm['Width'], mm['Height'], pd['Bytes Per Pixel']
        raw = pd['Pixel Data'][mm['Offset']:mm['Offset'] + w * h * bpp]
        return Image.frombytes('RGB' if bpp == 3 else 'RGBA', (w, h), bytes(raw)).convert('RGBA'), fname
    if nif_dir:
        base = os.path.basename(fname.replace('\\', '/'))
        cand = [base, os.path.splitext(base)[0] + '.dds', os.path.splitext(base)[0] + '.tga']
        have = {f.lower(): f for f in os.listdir(nif_dir)} if os.path.isdir(nif_dir) else {}
        for c in cand:
            if c.lower() in have:
                try:
                    return Image.open(os.path.join(nif_dir, have[c.lower()])).convert('RGBA'), fname
                except OSError:
                    pass
    return None, fname


def shape_texture(n, b):
    for p in b.get('Properties', []):
        if p >= 0 and n.blocks[p]['_type'] == 'NiTexturingProperty' and n.blocks[p].get('Has Base Texture'):
            return n.blocks[p]['Base Texture']['Source']
    return -1


def geometry(n, d):
    """NiTriShapeData / NiTriStripsData -> (pos Nx3, normales|None, uv|None, colores|None, tris Mx3)."""
    pos = np.array([[v['x'], v['y'], v['z']] for v in d.get('Vertices', [])], np.float32).reshape(-1, 3)
    nor = np.array([[v['x'], v['y'], v['z']] for v in d['Normals']], np.float32) if d.get('Has Normals') and d.get('Normals') else None
    uv = np.array([[t['u'], t['v']] for t in d['UV Sets'][0]], np.float32) if d.get('UV Sets') and d['UV Sets'][0] else None
    col = np.array([[c['r'], c['g'], c['b'], c['a']] for c in d['Vertex Colors']], np.float32) if d.get('Has Vertex Colors') and d.get('Vertex Colors') else None
    if d['_type'] == 'NiTriShapeData':
        tris = np.array([[t['v1'], t['v2'], t['v3']] for t in d.get('Triangles', [])], np.uint32).reshape(-1, 3)
    else:
        out = []
        for strip in d.get('Points', []):
            for k in range(len(strip) - 2):
                a, b, c = strip[k], strip[k + 1], strip[k + 2]
                if a == b or b == c or a == c:
                    continue
                out.append((a, b, c) if k % 2 == 0 else (a, c, b))
        tris = np.array(out, np.uint32).reshape(-1, 3)
    return pos, nor, uv, col, tris


def scene(n, nif_dir=None):
    """Resumen de la escena para el visor / exportadores."""
    par = parents(n)
    cache = {}
    nodes, shapes, textures, texmap = [], [], [], {}
    for i, b in enumerate(n.blocks):
        t = b['_type']
        if t == 'NiNode':
            nodes.append({'id': i, 'name': name(b), 'parent': par.get(i, -1), 'local': local(b).tolist(), 'world': world(n, i, par, cache).tolist(),
                          'children': [c for c in b.get('Children', []) if c >= 0], 'hidden': bool(b.get('Flags', 0) & 1)})
        elif t in ('NiTriShape', 'NiTriStrips') and b.get('Data', -1) >= 0:
            src = shape_texture(n, b)
            if src >= 0 and src not in texmap:
                img, fn = texture_image(n, src, nif_dir)
                texmap[src] = len(textures)
                textures.append({'block': src, 'file': fn, 'image': img, 'embedded': n.blocks[src].get('Use External') == 0})
            pos, nor, uv, col, tris = geometry(n, n.blocks[b['Data']])
            skin = None
            si = b.get('Skin Instance', -1)
            if si >= 0:
                skin = skin_info(n, si, len(pos))
            hid, j = bool(b.get('Flags', 0) & 1), i
            while not hid and j in par:
                j = par[j]
                hid = bool(n.blocks[j].get('Flags', 0) & 1)
            shapes.append({'id': i, 'name': name(b), 'parent': par.get(i, -1), 'local': local(b), 'world': world(n, i, par, cache),
                           'pos': pos, 'nor': nor, 'uv': uv, 'col': col, 'tris': tris, 'tex': texmap.get(src, -1),
                           'hidden': hid, 'skin': skin, 'data': b['Data']})
    return {'nodes': nodes, 'shapes': shapes, 'textures': textures}


def skin_info(n, si, nverts):
    inst = n.blocks[si]
    data = n.blocks[inst['Data']]
    bones = inst['Bones']
    W = np.zeros((nverts, len(bones)), np.float32)
    for j, bd in enumerate(data['Bone List']):
        for vw in bd.get('Vertex Weights', []):
            if vw['Index'] < nverts:
                W[vw['Index'], j] = vw['Weight']
    return {'bones': bones, 'root': inst['Skeleton Root'], 'skin_t': niTransform(data['Skin Transform']),
            'bone_t': [niTransform(bd['Skin Transform']) for bd in data['Bone List']], 'weights': W}


# ---------------------------------------------------------------- exportar glTF (.glb)
class _Buf:
    def __init__(self):
        self.data = bytearray()
        self.views, self.accs = [], []

    def add(self, arr, comp, typ, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        while len(self.data) % 4:
            self.data.append(0)
        off = len(self.data)
        self.data += arr.tobytes()
        v = {'buffer': 0, 'byteOffset': off, 'byteLength': arr.nbytes}
        if target:
            v['target'] = target
        self.views.append(v)
        a = {'bufferView': len(self.views) - 1, 'componentType': comp, 'count': int(arr.shape[0]), 'type': typ}
        if minmax:
            a['min'] = arr.min(0).tolist()
            a['max'] = arr.max(0).tolist()
        self.accs.append(a)
        return len(self.accs) - 1

    def blob(self, b):
        while len(self.data) % 4:
            self.data.append(0)
        off = len(self.data)
        self.data += b
        self.views.append({'buffer': 0, 'byteOffset': off, 'byteLength': len(b)})
        return len(self.views) - 1


def _png(img):
    f = io.BytesIO()
    img.save(f, 'PNG')
    return f.getvalue()


def _mat_list(m):
    return [float(x) for x in np.asarray(m).T.reshape(-1)]   # glTF: columna a columna


def export_glb(n, nif_dir=None, hidden=False):
    sc = scene(n, nif_dir)
    buf = _Buf()
    images, textures, materials = [], [], []
    for t in sc['textures']:
        if t['image'] is None:
            materials.append({'name': os.path.basename(t['file']) or 'sin textura', 'pbrMetallicRoughness': {'metallicFactor': 0, 'roughnessFactor': 1}})
            continue
        images.append({'bufferView': buf.blob(_png(t['image'])), 'mimeType': 'image/png', 'name': t['file']})
        textures.append({'source': len(images) - 1})
        materials.append({'name': os.path.basename(t['file']), 'pbrMetallicRoughness': {'baseColorTexture': {'index': len(textures) - 1}, 'metallicFactor': 0,
                                                                                         'roughnessFactor': 1},
                          'alphaMode': 'MASK' if t['image'].mode == 'RGBA' and t['image'].getextrema()[3][0] < 255 else 'OPAQUE',
                          'extras': {'mh_file': t['file'], 'mh_embedded': t['embedded']}})
    default_mat = None
    gnodes, gmeshes, skins = [], [], []
    idx = {}
    for nd in sc['nodes']:
        idx[nd['id']] = len(gnodes)
        gnodes.append({'name': nd['name'], 'matrix': _mat_list(nd['local'])})
    for sh in sc['shapes']:
        if sh['hidden'] and not hidden:
            continue
        if not len(sh['tris']):
            continue
        attrs = {'POSITION': buf.add(sh['pos'].astype(np.float32), 5126, 'VEC3', 34962, True)}
        if sh['nor'] is not None and len(sh['nor']) == len(sh['pos']):
            nn = sh['nor'] / np.maximum(np.linalg.norm(sh['nor'], axis=1, keepdims=True), 1e-8)
            attrs['NORMAL'] = buf.add(nn.astype(np.float32), 5126, 'VEC3', 34962)
        if sh['uv'] is not None and len(sh['uv']) == len(sh['pos']):
            attrs['TEXCOORD_0'] = buf.add(sh['uv'].astype(np.float32), 5126, 'VEC2', 34962)
        if sh['col'] is not None and len(sh['col']) == len(sh['pos']):
            attrs['COLOR_0'] = buf.add(np.clip(sh['col'], 0, 1).astype(np.float32), 5126, 'VEC4', 34962)
        node = {'name': sh['name'], 'matrix': _mat_list(sh['local'])}
        if sh['skin']:
            sk = sh['skin']
            W = sk['weights']
            order = np.argsort(-W, axis=1)[:, :4]
            J = order.astype(np.uint16)
            WW = np.take_along_axis(W, order, 1)
            if WW.shape[1] < 4:
                J = np.pad(J, ((0, 0), (0, 4 - J.shape[1])))
                WW = np.pad(WW, ((0, 0), (0, 4 - WW.shape[1])))
            s = WW.sum(1, keepdims=True)
            WW = np.where(s > 0, WW / np.maximum(s, 1e-8), np.array([1, 0, 0, 0], np.float32))
            attrs['JOINTS_0'] = buf.add(J, 5123, 'VEC4', 34962)
            attrs['WEIGHTS_0'] = buf.add(WW.astype(np.float32), 5126, 'VEC4', 34962)
            # glTF ignora la transformación del nodo de una malla con piel: inverseBind = BoneT * SkinT
            ibm = np.array([np.asarray(bt @ sk['skin_t']).T for bt in sk['bone_t']], np.float32).reshape(-1, 16)
            skins.append({'joints': [idx[b] for b in sk['bones'] if b in idx], 'inverseBindMatrices': buf.add(ibm, 5126, 'MAT4'),
                          'skeleton': idx.get(sk['root'], 0)})
            node['skin'] = len(skins) - 1
        prim = {'attributes': attrs, 'indices': buf.add(sh['tris'].astype(np.uint32).reshape(-1), 5125, 'SCALAR', 34963)}
        if sh['tex'] >= 0:
            prim['material'] = sh['tex']
        else:
            if default_mat is None:
                materials.append({'name': 'gris', 'pbrMetallicRoughness': {'baseColorFactor': [0.6, 0.6, 0.6, 1], 'metallicFactor': 0}})
                default_mat = len(materials) - 1
            prim['material'] = default_mat
        gmeshes.append({'name': sh['name'], 'primitives': [prim]})
        node['mesh'] = len(gmeshes) - 1
        idx[sh['id']] = len(gnodes)
        gnodes.append(node)
        sh['_g'] = len(gnodes) - 1
    # hijos
    for nd in sc['nodes']:
        kids = [idx[c] for c in nd['children'] if c in idx]
        if kids:
            gnodes[idx[nd['id']]]['children'] = kids
    roots = [idx[nd['id']] for nd in sc['nodes'] if nd['parent'] < 0]
    roots += [sh['_g'] for sh in sc['shapes'] if '_g' in sh and sh['parent'] < 0]
    gnodes.append({'name': 'MH_Zup', 'matrix': _mat_list(ZUP), 'children': roots})
    doc = {'asset': {'version': '2.0', 'generator': 'Making History kit (nif_mesh.py)'}, 'scene': 0, 'scenes': [{'nodes': [len(gnodes) - 1]}],
           'nodes': gnodes, 'meshes': gmeshes, 'materials': materials, 'buffers': [{'byteLength': len(buf.data)}],
           'bufferViews': buf.views, 'accessors': buf.accs}
    if images:
        doc['images'], doc['textures'], doc['samplers'] = images, textures, [{}]
        for t in textures:
            t['sampler'] = 0
    if skins:
        doc['skins'] = skins
    js = json.dumps(doc, separators=(',', ':')).encode()
    js += b' ' * (-len(js) % 4)
    bin_ = bytes(buf.data) + b'\0' * (-len(buf.data) % 4)
    return (struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_)) + struct.pack('<II', len(js), 0x4E4F534A) + js
            + struct.pack('<II', len(bin_), 0x004E4942) + bin_)


def export_obj(n, nif_dir=None, base='modelo'):
    """OBJ + MTL + PNG (posiciones en el mundo, Y arriba). Devuelve {nombre_archivo: bytes}."""
    sc = scene(n, nif_dir)
    out_obj, out_mtl, files = ['mtllib %s.mtl' % base], [], {}
    for k, t in enumerate(sc['textures']):
        out_mtl.append('newmtl tex%d\nKd 1 1 1' % k)
        if t['image'] is not None:
            fn = '%s_tex%d.png' % (base, k)
            files[fn] = _png(t['image'])
            out_mtl.append('map_Kd %s' % fn)
    off = 1
    for sh in sc['shapes']:
        if sh['hidden'] or not len(sh['tris']):
            continue
        m = ZUP @ sh['world']
        p = (np.c_[sh['pos'], np.ones(len(sh['pos']))] @ m.T)[:, :3]
        out_obj.append('o %s' % (sh['name'] or 'shape%d' % sh['id']))
        out_obj += ['v %.6f %.6f %.6f' % tuple(v) for v in p]
        if sh['uv'] is not None:
            out_obj += ['vt %.6f %.6f' % (u, 1 - v) for u, v in sh['uv']]
        if sh['nor'] is not None:
            nn = sh['nor'] @ m[:3, :3].T
            nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-8)
            out_obj += ['vn %.5f %.5f %.5f' % tuple(v) for v in nn]
        if sh['tex'] >= 0:
            out_obj.append('usemtl tex%d' % sh['tex'])
        for a, b, c in sh['tris'] + off:
            f = lambda i: '%d/%s/%s' % (i, i if sh['uv'] is not None else '', i if sh['nor'] is not None else '')
            out_obj.append('f %s %s %s' % (f(a), f(b), f(c)))
        off += len(sh['pos'])
    files[base + '.obj'] = '\n'.join(out_obj).encode()
    files[base + '.mtl'] = '\n'.join(out_mtl).encode()
    return files


# ---------------------------------------------------------------- texturas
def _pixel_block(img, like=None):
    img = img.convert('RGBA')
    w, h = img.size
    alpha = img.getextrema()[3][0] < 255
    raw = img.tobytes() if alpha else img.convert('RGB').tobytes()
    b = dict(like) if like else {}
    b.update({'_type': 'NiPixelData', 'Pixel Format': 1 if alpha else 0, 'Red Mask': 0xFF, 'Green Mask': 0xFF00, 'Blue Mask': 0xFF0000,
              'Alpha Mask': 0xFF000000 if alpha else 0, 'Bits Per Pixel': 32 if alpha else 24, 'Old Fast Compare': b'\0' * 8 if not like else like['Old Fast Compare'],
              'Tiling': 0, 'Palette': -1, 'Num Mipmaps': 1, 'Bytes Per Pixel': 4 if alpha else 3,
              'Mipmaps': [{'Width': w, 'Height': h, 'Offset': 0}], 'Num Pixels': len(raw), 'Pixel Data': raw})
    # firma del formato tal como la escriben los .nif del juego (con otra, el juego lee mal los colores)
    b['Old Fast Compare'] = b'\x81\x08\x82 \x00\x08\x10\x18' if alpha else b'`\x08\x82\x00\x00\x08\x10\x00'
    return b


def _pow2(img, maxsize=1024):
    from PIL import Image
    w, h = img.size
    p = lambda x: min(maxsize, 1 << max(2, round(math.log2(max(4, x)))))
    if (p(w), p(h)) != (w, h):
        img = img.resize((p(w), p(h)), Image.LANCZOS)
    return img


def set_texture(n, src_index, img, embed=True, file_name=None):
    """Cambia la imagen de un NiSourceTexture. embed=True: la incrusta (NiPixelData); si no, apunta a file_name externo."""
    st = n.blocks[src_index]
    if file_name:
        st['File Name'] = N.set_string(file_name)
    if embed:
        img = _pow2(img)
        old = st.get('Pixel Data', -1) if st.get('Use External') == 0 else -1
        if old >= 0:
            n.blocks[old].clear()
            n.blocks[old].update(_pixel_block(img, None))
        else:
            st['Use External'] = 0
            st.pop('Unknown Link', None)
            st['Pixel Data'] = n.add(_pixel_block(img))
            st.setdefault('Direct Render', 0)
    else:
        st['Use External'] = 1
        st['Unknown Link'] = -1
        st.pop('Pixel Data', None)


def textures_list(n, nif_dir=None):
    out = []
    for i, b in enumerate(n.blocks):
        if b['_type'] == 'NiSourceTexture':
            img, fn = texture_image(n, i, nif_dir)
            out.append({'block': i, 'file': fn, 'embedded': b.get('Use External') == 0, 'size': list(img.size) if img else None,
                        'decal': 'decal' in fn.lower()})
    return out


# ---------------------------------------------------------------- importar
def read_glb(data):
    """glTF binario (.glb) o JSON (.gltf con buffers data:) -> (doc, bin)."""
    if data[:4] == b'glTF':
        ln, = struct.unpack_from('<I', data, 12)
        doc = json.loads(data[20:20 + ln])
        p = 20 + ln
        bin_ = b''
        if p < len(data):
            bl, = struct.unpack_from('<I', data, p)
            bin_ = data[p + 8:p + 8 + bl]
        return doc, bin_
    doc = json.loads(data)
    import base64
    uri = doc['buffers'][0].get('uri', '')
    if not uri.startswith('data:'):
        raise ValueError('el .gltf usa un .bin aparte: expórtalo como .glb (binario)')
    return doc, base64.b64decode(uri.split(',', 1)[1])


def _acc(doc, bin_, i):
    a = doc['accessors'][i]
    v = doc['bufferViews'][a['bufferView']]
    dt = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8, 5122: np.int16, 5120: np.int8}[a['componentType']]
    k = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[a['type']]
    stride = v.get('byteStride', 0)
    off = v.get('byteOffset', 0) + a.get('byteOffset', 0)
    item = np.dtype(dt).itemsize * k
    if stride and stride != item:
        rows = [np.frombuffer(bin_, dt, k, off + j * stride) for j in range(a['count'])]
        arr = np.array(rows)
    else:
        arr = np.frombuffer(bin_, dt, a['count'] * k, off).reshape(a['count'], k)
    if a.get('normalized'):
        arr = arr.astype(np.float32) / np.iinfo(dt).max
    return arr


def _gltf_local(nd):
    if 'matrix' in nd:
        return np.array(nd['matrix'], float).reshape(4, 4).T
    t = np.array(nd.get('translation', [0, 0, 0]), float)
    x, y, z, w = nd.get('rotation', [0, 0, 0, 1])
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * np.array(nd.get('scale', [1, 1, 1]), float)
    m[:3, 3] = t
    return m


def load_gltf_meshes(data):
    """-> lista de {name, parent_names, world(Z-arriba), pos, nor, uv, tris, image, skin:{joints:[nombres], ibm, J, W}}"""
    from PIL import Image
    doc, bin_ = read_glb(data)
    nodes = doc.get('nodes', [])
    par = {}
    for i, nd in enumerate(nodes):
        for c in nd.get('children', []):
            par[c] = i
    wcache = {}

    def gworld(i):
        if i not in wcache:
            m = _gltf_local(nodes[i])
            wcache[i] = gworld(par[i]) @ m if i in par else m
        return wcache[i]
    to_z = np.linalg.inv(ZUP)
    imgs = {}

    def image(mat_i):
        if mat_i is None:
            return None
        if mat_i in imgs:
            return imgs[mat_i]
        mat = doc['materials'][mat_i]
        im = None
        bct = mat.get('pbrMetallicRoughness', {}).get('baseColorTexture')
        if bct is not None:
            src = doc['images'][doc['textures'][bct['index']]['source']]
            if 'bufferView' in src:
                v = doc['bufferViews'][src['bufferView']]
                im = Image.open(io.BytesIO(bin_[v.get('byteOffset', 0):v.get('byteOffset', 0) + v['byteLength']])).convert('RGBA')
            elif src.get('uri', '').startswith('data:'):
                import base64
                im = Image.open(io.BytesIO(base64.b64decode(src['uri'].split(',', 1)[1]))).convert('RGBA')
        if im is None:
            f = mat.get('pbrMetallicRoughness', {}).get('baseColorFactor', [0.7, 0.7, 0.7, 1])
            im = Image.new('RGBA', (8, 8), tuple(int(255 * x) for x in f))
        imgs[mat_i] = im
        return im
    out = []
    for i, nd in enumerate(nodes):
        if 'mesh' not in nd:
            continue
        chain, j = [], i
        while j in par:
            j = par[j]
            chain.append(nodes[j].get('name', ''))
        wm = to_z @ gworld(i)
        for k, prim in enumerate(doc['meshes'][nd['mesh']]['primitives']):
            if prim.get('mode', 4) != 4:
                continue
            at = prim['attributes']
            pos = _acc(doc, bin_, at['POSITION']).astype(float)
            tris = (_acc(doc, bin_, prim['indices']).reshape(-1, 3) if 'indices' in prim else np.arange(len(pos)).reshape(-1, 3)).astype(np.uint32)
            m = {'name': nd.get('name', 'mesh%d' % i) + ('' if k == 0 else '_%d' % k), 'parent_names': chain, 'world': wm,
                 'pos': pos, 'nor': _acc(doc, bin_, at['NORMAL']).astype(float) if 'NORMAL' in at else None,
                 'uv': _acc(doc, bin_, at['TEXCOORD_0']).astype(float) if 'TEXCOORD_0' in at else None, 'tris': tris,
                 'image': image(prim.get('material')), 'skin': None}
            if 'skin' in nd and 'JOINTS_0' in at:
                sk = doc['skins'][nd['skin']]
                ibm = _acc(doc, bin_, sk['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1) if 'inverseBindMatrices' in sk \
                    else np.array([np.eye(4)] * len(sk['joints']))
                jw = [to_z @ gworld(j) for j in sk['joints']]
                m['skin'] = {'joints': [nodes[j].get('name', 'joint%d' % j) for j in sk['joints']], 'ibm': ibm, 'joint_world': jw,
                             'J': _acc(doc, bin_, at['JOINTS_0']).astype(int), 'W': _acc(doc, bin_, at['WEIGHTS_0']).astype(float)}
            out.append(m)
    return out


def load_obj_meshes(text, files=None):
    """OBJ (Y arriba) -> mallas como load_gltf_meshes. files: {nombre: bytes} para .mtl y texturas."""
    from PIL import Image
    files = files or {}
    V, VT, VN = [], [], []
    groups = {}
    order = []
    cur = 'obj'
    mtl_of = {}
    kd_of = {}
    mtl_cur = None
    mtllib = None
    for line in text.splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == 'v':
            V.append([float(x) for x in p[1:4]])
        elif p[0] == 'vt':
            VT.append([float(x) for x in p[1:3]])
        elif p[0] == 'vn':
            VN.append([float(x) for x in p[1:4]])
        elif p[0] in ('o', 'g'):
            cur = ' '.join(p[1:]) or cur
        elif p[0] == 'usemtl':
            mtl_cur = ' '.join(p[1:])
        elif p[0] == 'mtllib':
            mtllib = ' '.join(p[1:])
        elif p[0] == 'f':
            key = (cur, mtl_cur)
            if key not in groups:
                groups[key] = []
                order.append(key)
            idx = []
            for c in p[1:]:
                s = (c.split('/') + ['', ''])[:3]
                fix = lambda x, L: (int(x) - 1 if int(x) > 0 else len(L) + int(x)) if x else -1
                idx.append((fix(s[0], V), fix(s[1], VT), fix(s[2], VN)))
            for k in range(1, len(idx) - 1):
                groups[key].append((idx[0], idx[k], idx[k + 1]))
    if mtllib and mtllib in files:
        m = None
        for line in files[mtllib].decode('utf-8', 'replace').splitlines():
            p = line.split()
            if p and p[0] == 'newmtl':
                m = ' '.join(p[1:])
            elif p and p[0] == 'map_Kd' and m:
                mtl_of[m] = os.path.basename(' '.join(p[1:]).replace('\\', '/'))
            elif p and p[0] == 'Kd' and m and m not in kd_of:
                kd_of[m] = tuple(int(255 * min(1.0, max(0.0, float(x)))) for x in p[1:4])
    solid = {}
    to_z = np.linalg.inv(ZUP)
    V, VT, VN = np.array(V or [[0, 0, 0]]), np.array(VT or [[0, 0]]), np.array(VN or [[0, 0, 1]])
    out = []
    for key in order:
        corners = {}
        pos, uv, nor, tris = [], [], [], []
        for tri in groups[key]:
            t = []
            for c in tri:
                if c not in corners:
                    corners[c] = len(pos)
                    pos.append(V[c[0]])
                    uv.append(VT[c[1]] * [1, -1] + [0, 1] if c[1] >= 0 else [0, 0])
                    nor.append(VN[c[2]] if c[2] >= 0 else [0, 0, 1])
                t.append(corners[c])
            tris.append(t)
        img = None
        tf = mtl_of.get(key[1])
        if tf and tf in files:
            img = Image.open(io.BytesIO(files[tf])).convert('RGBA')
        elif key[1] in kd_of:      # material sin textura: color liso
            img = solid.setdefault(kd_of[key[1]], Image.new('RGBA', (8, 8), kd_of[key[1]] + (255,)))
        out.append({'name': key[0], 'parent_names': [], 'world': to_z, 'pos': np.array(pos, float), 'nor': np.array(nor, float),
                    'uv': np.array(uv, float), 'tris': np.array(tris, np.uint32), 'image': img, 'skin': None})
    return out


def _empty_net(nm):
    return {'Name': N.set_string(nm), 'Num Extra Data List': 0, 'Extra Data List': [], 'Controller': -1}


def _shape_data(pos, nor, uv):
    c = pos.mean(0) if len(pos) else np.zeros(3)
    return {'_type': 'NiTriShapeData', 'Group ID': 0, 'Num Vertices': len(pos), 'Keep Flags': 0, 'Compress Flags': 0, 'Has Vertices': 1,
            'Vertices': [set_vec(v) for v in pos], 'Vector Flags': 1 if uv is not None else 0, 'Has Normals': 1 if nor is not None else 0,
            'Normals': [set_vec(v) for v in nor] if nor is not None else [], 'Center': set_vec(c),
            'Radius': float(np.linalg.norm(pos - c, axis=1).max()) if len(pos) else 0.0, 'Has Vertex Colors': 0, 'Vertex Colors': [],
            'UV Sets': [[{'u': float(a), 'v': float(b)} for a, b in uv]] if uv is not None else [], 'Consistency Flags': 0x4000,
            'Additional Data': -1, 'Num Triangles': 0, 'Num Triangle Points': 0, 'Has Triangles': 1, 'Triangles': [],
            'Num Match Groups': 0, 'Match Groups': []}


def _fill_tris(d, tris):
    d['Triangles'] = [{'v1': int(a), 'v2': int(b), 'v3': int(c)} for a, b, c in tris]
    d['Num Triangles'] = len(tris)
    d['Num Triangle Points'] = 3 * len(tris)


def find_node(n, nm):
    for i, b in enumerate(n.blocks):
        if b['_type'] == 'NiNode' and name(b).lower() == nm.lower():
            return i
    return -1


def shapes_under(n, i):
    out, todo = [], [i]
    while todo:
        j = todo.pop()
        b = n.blocks[j]
        if b['_type'] in ('NiTriShape', 'NiTriStrips'):
            out.append(j)
        todo += [c for c in b.get('Children', []) if c >= 0]
    return out


KEEP_DEFAULT = ('NationLogo', 'Frame', 'Wake', 'Shadow')


def import_meshes(n, meshes, keep=KEEP_DEFAULT, default_parent=None, scale=1.0, target_size=None, fit=False):
    """Sustituye la geometría de la plantilla n por meshes (de load_gltf_meshes / load_obj_meshes).

    - Las formas de la plantilla cuyo nombre empieza por algo de keep se conservan (insignia, fogonazos...).
    - Cada malla va bajo el NiNode de la plantilla con el mismo nombre que ella o que un antepasado suyo en glTF
      (p. ej. «Turret» para que gire con la animación); si no hay, bajo default_parent (por defecto «Parts» o «AnimNull»).
    - Las mallas con piel se atan a los nodos con el nombre de sus joints (huesos). Faltantes -> error.
    - target_size: si se da, escala todo para que la mayor dimensión mida eso (en unidades del nodo padre del mundo).
    """
    par = parents(n)
    cache = {}
    # forma plantilla para copiar propiedades (material, alpha, etc.)
    tmpl = None
    for i, b in enumerate(n.blocks):
        if b['_type'] in ('NiTriShape', 'NiTriStrips') and not name(b).startswith(tuple(keep)):
            tmpl = b
            break
    if default_parent is None:
        for cand in ('Hull', 'Parts', 'AnimNull'):
            if find_node(n, cand) >= 0:
                default_parent = cand
                break
        else:
            default_parent = name(n.blocks[0])
    dp = find_node(n, default_parent) if find_node(n, default_parent) >= 0 else 0
    if fit and not target_size:     # mismo tamaño que el modelo de la plantilla
        pts = []
        for i, b in enumerate(n.blocks):
            if b['_type'] in ('NiTriShape', 'NiTriStrips') and not name(b).startswith(tuple(keep)) and b.get('Data', -1) >= 0 and not b.get('Flags', 0) & 1:
                pos = geometry(n, n.blocks[b['Data']])[0]
                if len(pos):
                    pts.append((np.c_[pos, np.ones(len(pos))] @ world(n, i, par, cache).T)[:, :3])
        if pts:
            allt = np.vstack(pts)
            new = np.vstack([(np.c_[m['pos'], np.ones(len(m['pos']))] @ m['world'].T)[:, :3] for m in meshes if len(m['pos'])])
            scale = float((allt.max(0) - allt.min(0)).max() / max((new.max(0) - new.min(0)).max(), 1e-9))
    # quitar las formas viejas
    removed = 0
    for i, b in enumerate(n.blocks):
        if 'Children' in b:
            kids = []
            for c in b['Children']:
                if c >= 0 and n.blocks[c]['_type'] in ('NiTriShape', 'NiTriStrips') and not name(n.blocks[c]).startswith(tuple(keep)):
                    removed += 1
                    continue
                kids.append(c)
            b['Children'] = kids
    if target_size:
        allp = np.vstack([(np.c_[m['pos'], np.ones(len(m['pos']))] @ m['world'].T)[:, :3] for m in meshes if not m['skin']] or [np.zeros((1, 3))])
        ext = (allp.max(0) - allp.min(0)).max()
        pw = world(n, dp, par, cache)
        unit = float(np.cbrt(abs(np.linalg.det(pw[:3, :3]))))
        scale = target_size / max(ext, 1e-9)    # S se aplica en el espacio del mundo
    props_common = [p for p in (tmpl or {}).get('Properties', []) if p >= 0 and n.blocks[p]['_type'] != 'NiTexturingProperty']
    tex_tmpl = None
    for p in (tmpl or {}).get('Properties', []):
        if p >= 0 and n.blocks[p]['_type'] == 'NiTexturingProperty':
            tex_tmpl = n.blocks[p]
    texcache = {}
    notes = []
    kept = {name(b) for b in n.blocks if b['_type'] in ('NiTriShape', 'NiTriStrips') and name(b).startswith(tuple(keep))}
    for m in meshes:
        if not len(m['tris']):
            continue
        if m['name'] in kept:      # ya está en la plantilla (insignia, fogonazos...)
            notes.append('%s: se conserva la de la plantilla' % m['name'])
            continue
        target = dp
        for nm in [m['name']] + m['parent_names']:
            j = find_node(n, nm)
            if j < 0:     # «Turret_cupula» -> nodo «Turret» (OBJ no guarda jerarquía)
                j = next((i for i, b in enumerate(n.blocks) if b['_type'] == 'NiNode' and len(name(b)) > 2
                          and nm.lower().startswith(name(b).lower() + '_')), -1)
            if j >= 0:
                target = j
                break
        S = np.diag([scale, scale, scale, 1.0])
        if m['skin']:
            sk = m['skin']
            bones = [find_node(n, j) for j in sk['joints']]
            miss = [j for j, b in zip(sk['joints'], bones) if b < 0]
            if miss:
                raise ValueError('huesos sin nodo con ese nombre en la plantilla: %s' % ', '.join(miss[:8]))
            # como en los .nif del juego: la malla con piel cuelga de «<Unidad> NonAccum» (dentro del árbol que anima el juego)
            root = next((i for i, b in enumerate(n.blocks) if b['_type'] == 'NiNode' and name(b).endswith('NonAccum')), 0)
            target = root
            # pose del glTF: v = Σ w · JointWorld · IBM · v ; luego al espacio de la raíz NIF
            M = [np.linalg.inv(world(n, root, par, cache)) @ S @ jw @ ib for jw, ib in zip(sk['joint_world'], sk['ibm'])]
            P = np.c_[m['pos'], np.ones(len(m['pos']))]
            pos = np.zeros((len(P), 3))
            nor = np.zeros((len(P), 3)) if m['nor'] is not None else None
            for k in range(sk['J'].shape[1]):
                w = sk['W'][:, k:k + 1]
                for jb in np.unique(sk['J'][:, k]):
                    sel = sk['J'][:, k] == jb
                    pos[sel] += w[sel] * (P[sel] @ M[jb].T)[:, :3]
                    if nor is not None:
                        nor[sel] += w[sel] * (m['nor'][sel] @ M[jb][:3, :3].T)
            if nor is not None:
                nor /= np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-8)
            m['_bone_t'] = [np.linalg.inv(world(n, b, par, cache)) @ world(n, root, par, cache) for b in bones]
        else:
            pw = world(n, target, par, cache)
            mm = np.linalg.inv(pw) @ S @ m['world']
            pos = (np.c_[m['pos'], np.ones(len(m['pos']))] @ mm.T)[:, :3]
            nor = None
            if m['nor'] is not None:
                nor = m['nor'] @ np.linalg.inv(mm[:3, :3])
                nor /= np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-8)
        d = _shape_data(pos, nor, m['uv'])
        _fill_tris(d, m['tris'])
        di = n.add(d)
        props = list(props_common)
        if m['image'] is not None:
            key = id(m['image'])
            if key not in texcache:
                src = {'_type': 'NiSourceTexture', **_empty_net(''), 'Use External': 0, 'File Name': N.set_string((m['name'] or 'tex') + '.tga'),
                       'Format Prefs': {'Pixel Layout': 6, 'Use Mipmaps': 1, 'Alpha Format': 3}, 'Is Static': 1, 'Direct Render': 0}
                src['Pixel Data'] = n.add(_pixel_block(_pow2(m['image'])))
                si = n.add(src)
                tp = {'_type': 'NiTexturingProperty', **_empty_net(''), 'Apply Mode': 2, 'Texture Count': 7, 'Has Base Texture': 1,
                      'Base Texture': {'Source': si, 'Clamp Mode': 3, 'Filter Mode': 2, 'UV Set': 0, 'PS2 L': 0, 'PS2 K': -115, 'Has Texture Transform': 0},
                      'Has Dark Texture': 0, 'Has Detail Texture': 0, 'Has Gloss Texture': 0, 'Has Glow Texture': 0, 'Has Bump Map Texture': 0,
                      'Has Decal 0 Texture': 0, 'Num Shader Textures': 0, 'Shader Textures': []}
                if tex_tmpl:
                    tp = {**{k: v for k, v in tex_tmpl.items() if k not in ('Base Texture',)}, 'Base Texture': {**tex_tmpl['Base Texture'], 'Source': si}}
                    tp['Base Texture'].pop('Translation', None)
                texcache[key] = n.add(tp)
            props.insert(0, texcache[key])
        shape = {'_type': 'NiTriShape', **_empty_net(m['name']), 'Flags': 14, 'Translation': set_vec([0, 0, 0]), 'Rotation': set_rot(np.eye(3)), 'Scale': 1.0,
                 'Num Properties': len(props), 'Properties': props, 'Collision Object': -1, 'Data': di, 'Skin Instance': -1, 'Material Data': {'Has Shader': 0}}
        if tmpl:
            shape['Flags'] = tmpl.get('Flags', 14)
            for k in tmpl:
                if k not in shape and k != '_type':
                    shape[k] = tmpl[k]
        if m['skin']:
            shape['Skin Instance'] = _make_skin(n, m, bones, len(pos), root, S)
        si_ = n.add(shape)
        n.blocks[target]['Children'].append(si_)
        notes.append('%s -> %s' % (m['name'], name(n.blocks[target])))
    n.compact()
    return {'removed': removed, 'added': sum('->' in x for x in notes), 'placed': notes, 'scale': scale}


def _make_skin(n, m, bones, nverts, root, S):
    sk = m['skin']
    J, W = sk['J'], sk['W']
    blist = []
    for b_i, bt in enumerate(m['_bone_t']):
        t, r, s = split(bt)
        vw = [{'Index': int(v), 'Weight': float(W[v, k])} for v in range(nverts) for k in range(J.shape[1]) if J[v, k] == b_i and W[v, k] > 0]
        blist.append({'Skin Transform': {'Rotation': set_rot(r), 'Translation': set_vec(t), 'Scale': s}, 'Bounding Sphere Offset': set_vec([0, 0, 0]),
                      'Bounding Sphere Radius': 1000.0, 'Num Vertices': len(vw), 'Vertex Weights': vw})
    data = {'_type': 'NiSkinData', 'Skin Transform': {'Rotation': set_rot(np.eye(3)), 'Translation': set_vec([0, 0, 0]), 'Scale': 1.0},
            'Num Bones': len(bones), 'Skin Partition': -1, 'Has Vertex Weights': 1, 'Bone List': blist}
    di = n.add(data)
    # con la partición vacía el juego carga pero no dibuja la malla: hay que escribirla (como la infantería del juego)
    part = n.add(_partition(m['tris'], J, W, nverts))
    if n.ver <= 0x0A010000:
        data['Skin Partition'] = part
    inst = {'_type': 'NiSkinInstance', 'Data': di, 'Skeleton Root': root, 'Num Bones': len(bones), 'Bones': bones}
    if n.ver >= 0x0A010065:
        inst['Skin Partition'] = part
    return n.add(inst)


def _strip(tris):
    """Triángulos sueltos -> una tira con triángulos degenerados de unión; cada triángulo empieza en posición par
    (mismo sentido de giro)."""
    s = []
    for a, b, c in tris:
        if not s:
            s = [a, b, c]
            continue
        last = s[-1]
        s += [last]
        if (len(s) + 1) % 2:        # la segunda 'a' debe caer en posición par
            s += [last]
        s += [a, a, b, c]
    return s


def _partition(tris, J, W, nverts, max_bones=4):
    """NiSkinPartition: grupos de triángulos con <= 4 huesos cada uno."""
    def vb(v):
        return {int(J[v, k]) for k in range(J.shape[1]) if W[v, k] > 0} or {int(J[v, 0])}
    parts = []
    for t in tris:
        need = set().union(*(vb(int(v)) for v in t))
        for p in parts:
            if len(p['bones'] | need) <= max_bones:
                p['bones'] |= need
                p['tris'].append(t)
                break
        else:
            parts.append({'bones': set(need), 'tris': [t]})
    allb = sorted({int(j) for j in np.unique(J)})
    blocks = []
    for p in parts:
        bones = sorted(p['bones'])
        # como el juego: siempre 4 huesos por partición (se rellena con otros huesos de la piel, con peso 0)
        for b in allb:
            if len(bones) >= max_bones:
                break
            if b not in bones:
                bones.append(b)
        vmap = []
        loc = {}
        for t in p['tris']:
            for v in t:
                if int(v) not in loc:
                    loc[int(v)] = len(vmap)
                    vmap.append(int(v))
        # como en los .nif del juego: un peso por hueso de la partición, en su orden, y Bone Indices = 0, 1, 2...
        nb = len(bones)
        wts, idx = [], []
        for v in vmap:
            w = [0.0] * nb
            for k in range(J.shape[1]):
                if W[v, k] > 0 and int(J[v, k]) in bones:
                    w[bones.index(int(J[v, k]))] += float(W[v, k])
            s_ = sum(w) or 1.0
            wts.append([x / s_ for x in w] + [0.0] * (4 - nb))      # siempre 4 pesos por vértice (Gamebryo)
            idx.append(bytes(range(nb)) + bytes(4 - nb))
        strip = _strip([(loc[int(a)], loc[int(b)], loc[int(c)]) for a, b, c in p['tris']])
        # como el juego: una sola tira por partición (las particiones con lista de triángulos cerraban el juego en d3d9)
        blocks.append({'Num Vertices': len(vmap), 'Num Triangles': len(strip) - 2, 'Num Bones': len(bones), 'Num Strips': 1, 'Num Weights Per Vertex': 4,
                       'Bones': bones, 'Has Vertex Map': 1, 'Vertex Map': vmap, 'Has Vertex Weights': 1, 'Vertex Weights': wts, 'Strip Lengths': [len(strip)],
                       'Has Faces': 1, 'Strips': [strip], 'Has Bone Indices': 1, 'Bone Indices': idx})
    return {'_type': 'NiSkinPartition', 'Num Skin Partition Blocks': len(blocks), 'Skin Partition Blocks': blocks}


# ---------------------------------------------------------------- importar desde otro NIF y acomodar insignia / fogonazo
def material_color(n, b):
    """Color difuso (sRGB 0-255) del NiMaterialProperty de una forma, o None."""
    for p in b.get('Properties', []):
        if p >= 0 and n.blocks[p]['_type'] == 'NiMaterialProperty':
            c = n.blocks[p].get('Diffuse Color') or n.blocks[p].get('Ambient Color')
            if c:
                return tuple(int(255 * min(1.0, max(0.0, c[k])) ** (1 / 2.2)) for k in 'rgb')
    return None


# ejes de origen -> MH (Y arriba, frente +Z): «zup_y» = Z arriba y frente +Y (Blender)
AXES = {'mh': np.eye(4), 'zup_y': np.array([[-1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], float)}


def load_nif_meshes(n, nif_dir=None, axes='mh'):
    """Formas de otro NIF -> mallas para import_meshes (sin piel). Sin textura: una de color liso con su material."""
    from PIL import Image
    sc = scene(n, nif_dir)
    A = AXES[axes] if isinstance(axes, str) else axes
    out, solid = [], {}
    for sh in sc['shapes']:
        if sh['hidden'] or not len(sh['tris']):
            continue
        img = sc['textures'][sh['tex']]['image'] if sh['tex'] >= 0 else None
        if img is None:
            col = material_color(n, n.blocks[sh['id']]) or (150, 150, 150)
            if col not in solid:
                solid[col] = Image.new('RGBA', (8, 8), col + (255,))
            img = solid[col]
        out.append({'name': sh['name'], 'parent_names': [], 'world': A @ sh['world'], 'pos': sh['pos'].astype(float),
                    'nor': None if sh['nor'] is None else sh['nor'].astype(float), 'uv': sh['uv'] if sh['uv'] is not None else np.zeros((len(sh['pos']), 2)),
                    'tris': sh['tris'], 'image': img, 'skin': None})
    return out


def fit_attachments(n, turret='Turret'):
    """Tras importar: pone la insignia (NationLogo) sobre el techo de la torreta nueva y el fogonazo (Firing) en la boca del cañón."""
    par = parents(n)
    cache = {}
    ti = find_node(n, turret)
    if ti < 0:
        return []
    inv = np.linalg.inv(world(n, ti, par, cache))
    pts = []
    for s in shapes_under(n, ti):
        b = n.blocks[s]
        if name(b).startswith(KEEP_DEFAULT) or b.get('Data', -1) < 0:
            continue
        pos = geometry(n, n.blocks[b['Data']])[0]
        pts.append((np.c_[pos, np.ones(len(pos))] @ (inv @ world(n, s, par, cache)).T)[:, :3])
    if not pts:
        return []
    P = np.vstack(pts)
    notes = []
    # techo: los puntos más altos cerca del centro (sin el cañón, que sale hacia +Z)
    zc = np.median(P[:, 2])
    body = P[np.abs(P[:, 2] - zc) < (P[:, 2].max() - P[:, 2].min()) * 0.3]
    top = np.percentile(body[:, 1], 98) if len(body) else P[:, 1].max()
    cx, cz = np.median(body[:, 0]), np.median(body[:, 2])
    for i, b in enumerate(n.blocks):
        if b['_type'] in ('NiTriShape', 'NiTriStrips') and name(b) == 'NationLogo' and par.get(i) is not None:
            # posición del logo en el espacio de la torreta
            m = np.linalg.inv(world(n, ti, par, cache)) @ world(n, i, par, cache)
            pos = geometry(n, n.blocks[b['Data']])[0]
            lp = (np.c_[pos, np.ones(len(pos))] @ m.T)[:, :3]
            d = np.array([cx - lp[:, 0].mean(), top + 0.02 * (P[:, 1].max() - P[:, 1].min()) - lp[:, 1].min(), cz - lp[:, 2].mean()])
            pl = np.linalg.inv(world(n, par[i], par, cache)) @ world(n, ti, par, cache)
            b['Translation'] = set_vec(vec(b['Translation']) + pl[:3, :3] @ d)
            notes.append('NationLogo sobre la torreta (alto %.1f)' % top)
    fi = find_node(n, 'Firing')
    if fi >= 0 and par.get(fi) is not None:
        front = P[P[:, 2] > np.percentile(P[:, 2], 99.5)]
        tip = np.array([front[:, 0].mean(), front[:, 1].mean(), P[:, 2].max()])
        pl = np.linalg.inv(world(n, par[fi], par, cache)) @ world(n, ti, par, cache)
        n.blocks[fi]['Translation'] = set_vec((pl @ np.r_[tip, 1])[:3])
        notes.append('Firing en la boca del cañón')
    return notes
