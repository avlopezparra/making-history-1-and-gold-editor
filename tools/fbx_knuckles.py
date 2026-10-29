"""Knuckles del .fbx (esqueleto humanoide con piel + animación de puñetazo de Mixamo) -> .nif/.kf de Making History.

    python tools/fbx_knuckles.py <ruta .zip o carpeta con source/*.fbx y textures/> [salida_dir]

Usa como plantilla el tanque del juego (sus secuencias Idle/Move/Shoot se conservan y se añaden las pistas de los
huesos, como en anim_knuckles.py). La piel se escribe como la infantería del juego: particiones de 4 huesos en tiras.
Escribe <salida_dir>/Knuckles FBX.nif y .kf (no toca el juego).
"""
import copy
import io
import math
import os
import sys
import zipfile

import numpy as np
from PIL import Image

import fbx_read
import nif
import nif_mesh as M
import anim_knuckles as AK

NAME = 'Knuckles FBX'
TICKS = 46186158000         # unidades de tiempo FBX por segundo
HEIGHT_EXT = 25.0           # alto del modelo en unidades del .nif (como el otro Knuckles)
WALK_LEG = 25               # grados que se adelanta la pierna al caminar
WALK_KNEE = 30              # grados que dobla la rodilla
WALK_ARM = 20               # grados que balancean los brazos


def euler(r):
    """Lcl Rotation de FBX (grados, orden XYZ) -> matriz 3x3."""
    x, y, z = np.radians(r)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def props70(node):
    p = node.find('Properties70')
    return {c.props[0]: c.props[4:] for c in (p.children if p else [])}


def local_of(pr):
    T = np.eye(4)
    T[:3, 3] = pr.get('Lcl Translation', [0, 0, 0])
    T[:3, :3] = euler(pr.get('Lcl Rotation', [0, 0, 0])) * np.array(pr.get('Lcl Scaling', [1, 1, 1]))[None, :]
    return T


class Fbx:
    def __init__(self, path):
        r = fbx_read.load(path)
        o = r.find('Objects')
        self.objs = {c.props[0]: c for c in o.children}
        self.parent = {}
        self.links = []
        for c in r.find('Connections').children:
            self.links.append(c.props)
            if c.props[0] == 'OO':
                self.parent.setdefault(c.props[1], c.props[2])
        self.models = {k: v for k, v in self.objs.items() if v.name == 'Model'}
        self.mname = {k: v.props[1].split('\x00')[0] for k, v in self.models.items()}
        self.props = {k: props70(v) for k, v in self.models.items()}

    def children_of(self, oid, kind=None):
        return [a[1] for a in self.links if a[0] in ('OO', 'OP') and a[2] == oid and (kind is None or self.objs.get(a[1]) is not None and self.objs[a[1]].name == kind)]

    def global_rest(self, k):
        m = local_of(self.props[k])
        p = self.parent.get(k, 0)
        return (self.global_rest(p) @ m) if p in self.models else m


def mesh_data(f, files):
    """Malla 'Body' en el espacio del mundo FBX, con piel (índices de huesos = ids de modelos FBX)."""
    body = next(k for k, v in f.models.items() if v.props[2] == 'Mesh')
    geo = next(f.objs[c] for c in f.children_of(body, 'Geometry'))
    V = geo.find('Vertices').props[0].reshape(-1, 3)
    PVI = geo.find('PolygonVertexIndex').props[0]
    le_uv = geo.find('LayerElementUV')
    UV = le_uv.find('UV').props[0].reshape(-1, 2)
    UVI = le_uv.find('UVIndex').props[0]
    mats = geo.find('LayerElementMaterial').find('Materials').props[0]
    G = f.global_rest(body)
    Vw = (np.c_[V, np.ones(len(V))] @ G.T)[:, :3]
    # piel: clusters (uno por hueso) -> 4 pesos mayores por vértice
    skin = next(f.objs[c] for c in f.children_of(geo.props[0], 'Deformer') if f.objs[c].props[2] == 'Skin')
    infl = [[] for _ in range(len(V))]
    bones = []
    for c in f.children_of(skin.props[0], 'Deformer'):
        cl = f.objs[c]
        bone = next(x for x in f.children_of(c) if x in f.models)
        bi = len(bones)
        bones.append(bone)
        idx = cl.find('Indexes')
        if idx is None:
            continue
        for v, w in zip(idx.props[0], cl.find('Weights').props[0]):
            infl[v].append((w, bi))
    # materiales -> textura
    mat_ids = [c for c in f.children_of(body, 'Material')]
    tex_of = []
    for mid in mat_ids:
        img = None
        for t in f.children_of(mid, 'Texture'):
            for vid in f.children_of(t, 'Video'):
                fn = os.path.basename(str(props70(f.objs[vid]).get('Path', [''])[0] or f.objs[vid].find('RelativeFilename').props[0]).replace('\\', '/'))
                if fn in files:
                    img = Image.open(io.BytesIO(files[fn])).convert('RGBA')
        tex_of.append(img)
    # polígonos -> triángulos por material, con vértices por esquina (uv distinta)
    out = {}
    poly, corner0, pi = [], 0, 0
    for i, v in enumerate(PVI):
        poly.append((~v if v < 0 else v, i))
        if v < 0:
            mt = int(mats[pi]) if len(mats) > 1 else int(mats[0])
            d = out.setdefault(mt, {'corners': {}, 'pos': [], 'uv': [], 'vid': [], 'tris': []})
            ids = []
            for vi, ci in poly:
                key = (vi, int(UVI[ci]))
                if key not in d['corners']:
                    d['corners'][key] = len(d['pos'])
                    d['pos'].append(Vw[vi])
                    u = UV[UVI[ci]]
                    d['uv'].append([u[0], 1 - u[1]])
                    d['vid'].append(vi)
                ids.append(d['corners'][key])
            for k in range(1, len(ids) - 1):
                d['tris'].append((ids[0], ids[k], ids[k + 1]))
            poly, pi = [], pi + 1
    meshes = []
    for mt, d in sorted(out.items()):
        n = len(d['pos'])
        J = np.zeros((n, 4), int)
        W = np.zeros((n, 4))
        for j, vi in enumerate(d['vid']):
            top = sorted(infl[vi], reverse=True)[:4]
            s = sum(w for w, _ in top) or 1.0
            for k, (w, b) in enumerate(top):
                J[j, k], W[j, k] = b, w / s
        meshes.append({'name': 'Knuckles_%d' % mt, 'parent_names': [], 'world': np.eye(4), 'pos': np.array(d['pos'], float), 'nor': None,
                       'uv': np.array(d['uv'], float), 'tris': np.array(d['tris'], np.uint32), 'image': tex_of[mt] if mt < len(tex_of) else None,
                       'skin': {'J': J, 'W': W, 'bones': bones}})
    return meshes, bones, body


def curves(f):
    """{(modelo, 'R'|'T'): (tiempos s, valores Nx3)} de la única animación."""
    res = {}
    for cid, cn in f.objs.items():
        if cn.name != 'AnimationCurveNode':
            continue
        kind = cn.props[1].split('\x00')[0]
        tgt = next((a[2] for a in f.links if a[0] == 'OP' and a[1] == cid), None)
        if tgt not in f.models:
            continue
        chans = {}
        for a in f.links:
            if a[0] == 'OP' and a[2] == cid and f.objs.get(a[1]) is not None and f.objs[a[1]].name == 'AnimationCurve':
                c = f.objs[a[1]]
                chans[a[3][-1]] = (c.find('KeyTime').props[0] / TICKS, c.find('KeyValueFloat').props[0].astype(float))
        if not chans:
            continue
        ts = np.unique(np.concatenate([v[0] for v in chans.values()]))
        dflt = props70(cn)
        vals = np.stack([np.interp(ts, *chans[a]) if a in chans else np.full(len(ts), float(dflt.get('d|' + a, [0])[0]))
                         for a in 'XYZ'], 1)
        res[(tgt, kind)] = (ts, vals)
    return res


def build(src, out_dir):
    if src.lower().endswith('.zip'):
        z = zipfile.ZipFile(src)
        files = {os.path.basename(k): z.read(k) for k in z.namelist() if not k.endswith('/')}
    else:
        files = {fn: open(os.path.join(dp, fn), 'rb').read() for dp, _, fns in os.walk(src) for fn in fns}
    fbx_name = next(k for k in files if k.lower().endswith('.fbx'))
    tmp = os.path.join(out_dir, '_tmp.fbx')
    os.makedirs(out_dir, exist_ok=True)
    open(tmp, 'wb').write(files[fbx_name])
    f = Fbx(tmp)
    os.remove(tmp)
    meshes, bones, body = mesh_data(f, files)
    limbs = [k for k, v in f.models.items() if v.props[2] in ('LimbNode', 'Null') and k != body]

    t = nif.Nif.load(AK.TEMPLATE + '.nif')
    par = M.parents(t)
    hull = M.find_node(t, 'Hull')
    Wh = M.world(t, hull, par, {})
    # escala y ejes: el FBX es Y arriba como el juego; se escala para que mida HEIGHT_EXT y los pies queden en el suelo
    allp = np.vstack([m['pos'] for m in meshes])
    ext = (allp.max(0) - allp.min(0))
    sc = HEIGHT_EXT / ext.max()
    conv = np.diag([sc, sc, sc, 1.0])
    conv[:3, 3] = -sc * np.array([(allp[:, 0].max() + allp[:, 0].min()) / 2, allp[:, 1].min(), (allp[:, 2].max() + allp[:, 2].min()) / 2])
    ground = M.world(t, M.find_node(t, 'Tank NonAccum'), par, {})
    conv = ground @ conv        # en el espacio del mundo NIF, sobre el suelo de la unidad
    # nodos: raíz FBX (conv) colgada de Hull, y cada hueso con su transformación local FBX
    proto = next(b for b in t.blocks if b['_type'] == 'NiNode' and M.name(b) == 'Parts')

    def mknode(name, mat, parent):
        R = mat[:3, :3]
        s = float(np.cbrt(abs(np.linalg.det(R))))
        b = copy.deepcopy(proto)
        b.update({'Name': nif.set_string(name), 'Controller': -1, 'Children': [], 'Translation': M.set_vec(mat[:3, 3]),
                  'Rotation': M.set_rot(R / s), 'Scale': s})
        i = t.add(b)
        t.blocks[parent]['Children'].append(i)
        return i
    kroot = mknode('KnucklesRoot', np.linalg.inv(Wh) @ conv, hull)
    node_of = {}

    def add_tree(k, parent):
        node_of[k] = mknode(f.mname[k], local_of(f.props[k]), parent)
        for c in [c for c in limbs if f.parent.get(c) == k]:
            add_tree(c, node_of[k])
    for k in limbs:
        if f.parent.get(k, 0) not in f.models:
            add_tree(k, kroot)
    # malla: posiciones al mundo NIF; los huesos se buscan por nombre
    for m in meshes:
        m['pos'] = (np.c_[m['pos'], np.ones(len(m['pos']))] @ conv.T)[:, :3]
        sk = m['skin']
        m['skin'] = {'joints': [f.mname[b] for b in sk['bones']], 'ibm': [np.eye(4)] * len(sk['bones']),
                     'joint_world': [np.eye(4)] * len(sk['bones']), 'J': sk['J'], 'W': sk['W']}
    for b in t.blocks:     # se quitan las mallas del tanque
        pass
    r = M.import_meshes(t, meshes, keep=('__none__',), scale=1.0, default_parent='Hull')
    anim_nodes = [f.mname[k] for k in limbs]
    for b in t.blocks:
        if b['_type'] == 'NiMultiTargetTransformController':
            for nm in anim_nodes:
                i = M.find_node(t, nm)
                if i not in b['Extra Targets']:
                    b['Extra Targets'].append(i)
            b['Num Extra Targets'] = len(b['Extra Targets'])
    path = os.path.join(out_dir, NAME + '.nif')
    t.save(path)
    nif.Nif.load(path)
    return t, f, limbs, r


def build_kf(t, f, limbs, out_dir):
    cv = curves(f)
    k = nif.Nif.load(AK.TEMPLATE + '.kf')
    par = M.parents(t)

    def quat(R):
        w = math.sqrt(max(0.0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
        if w < 1e-4:
            # giro de ~180°: por el eje mayor
            i = int(np.argmax(np.diag(R)))
            q = np.zeros(4)
            q[i + 1] = math.sqrt(max(0.0, 1 + 2 * R[i, i] - np.trace(R))) / 2
            j, l = (i + 1) % 3, (i + 2) % 3
            q[0] = (R[l, j] - R[j, l]) / (4 * q[i + 1])
            q[j + 1] = (R[j, i] + R[i, j]) / (4 * q[i + 1])
            q[l + 1] = (R[l, i] + R[i, l]) / (4 * q[i + 1])
            return {'w': q[0], 'x': q[1], 'y': q[2], 'z': q[3]}
        return {'w': w, 'x': (R[2, 1] - R[1, 2]) / (4 * w), 'y': (R[0, 2] - R[2, 0]) / (4 * w), 'z': (R[1, 0] - R[0, 1]) / (4 * w)}

    def unit(R):
        return R / np.cbrt(abs(np.linalg.det(R)))

    names = {kk: f.mname[kk] for kk in limbs}
    rest = {kk: local_of(f.props[kk]) for kk in limbs}

    def rot_axis(kk, axis_world, ang):
        """giro local que equivale a girar 'ang' alrededor de un eje dado en el espacio del padre"""
        a = np.asarray(axis_world, float) / np.linalg.norm(axis_world)
        K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
        return (np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K) @ unit(rest[kk][:3, :3])

    by_name = {v: kk for kk, v in names.items()}

    def side_axis(nm):
        """eje izquierda-derecha del personaje expresado en el espacio del padre del hueso"""
        kk = by_name[nm]
        i = M.find_node(t, nm)
        Rp = M.world(t, par[i], par, {})[:3, :3]
        Rk = M.world(t, M.find_node(t, 'KnucklesRoot'), par, {})[:3, :3]
        return np.linalg.inv(Rp) @ Rk @ np.array([1.0, 0, 0])

    # pistas: {nombre: [(t, R3x3, T3 o None)]}
    seqs = {}
    # Shoot: la animación del FBX (puñetazo), en bucle
    dur = max(v[0].max() for v in cv.values())
    sh = {}
    for kk in limbs:
        ts = np.linspace(0, dur, max(2, int(dur * 15) + 1))
        R0 = rest[kk]
        keys = []
        for tt in ts:
            if (kk, 'R') in cv:
                c = cv[(kk, 'R')]
                e = [np.interp(tt, c[0], c[1][:, a]) for a in range(3)]
                R = euler(e)
            else:
                R = unit(R0[:3, :3])
            T = None
            if (kk, 'T') in cv:
                c = cv[(kk, 'T')]
                T = np.array([np.interp(tt, c[0], c[1][:, a]) for a in range(3)])
            keys.append((tt, R, T))
        sh[names[kk]] = keys
    seqs['Shoot'] = (dur, sh)
    # Move: piernas y brazos alternados (procedural)
    n = 16
    mv = {}
    for nm, sgn in (('Upper leg.L', 1), ('Upper leg.R', -1), ('Upper arm.L', -1), ('Upper arm.R', 1), ('Lower leg.L', 1), ('Lower leg.R', 1)):
        if nm not in by_name:
            continue
        kk = by_name[nm]
        ax = side_axis(nm)
        keys = []
        for i in range(n + 1):
            ph = 2 * math.pi * i / n
            if nm.startswith('Lower leg'):
                s = 0.5 * (1 + math.sin(ph if nm.endswith('L') else ph + math.pi))
                ang = math.radians(WALK_KNEE) * s
            else:
                ang = sgn * math.radians(WALK_LEG if 'leg' in nm else WALK_ARM) * math.sin(ph)
            keys.append((i / n, rot_axis(kk, ax, ang), None))
        mv[nm] = keys
    seqs['Move'] = (1.0, mv)
    seqs['Idle'] = (2.0, {})
    # todas las secuencias controlan los mismos nodos; translación solo donde alguna la trae (la cadera), igual en todas
    has_T = {nm for _, tr in seqs.values() for nm, keys in tr.items() if any(x[2] is not None for x in keys)}
    for sname, (d, tr) in seqs.items():
        for kk in limbs:
            nm = names[kk]
            if nm not in tr:
                tr[nm] = [(0.0, unit(rest[kk][:3, :3]), None), (d, unit(rest[kk][:3, :3]), None)]

    for si, sb in enumerate(k.blocks):
        if sb['_type'] != 'NiControllerSequence' or nif.string(sb['Name']) not in seqs:
            continue
        d, tracks = seqs[nif.string(sb['Name'])]
        stop = sb['Stop Time']
        reps = max(1, round(stop / d)) if stop > 0 else 0
        pal = k.blocks[sb['String Palette']]['Palette']['Palette']

        def off(txt):
            v = pal['Value']
            i = v.find(txt.encode() + bytes(1))
            if i < 0 or (i and v[i - 1] != 0):
                i = len(v)
                pal['Value'] = v + txt.encode() + bytes(1)
                pal['Length'] = len(pal['Value'])
                k.blocks[sb['String Palette']]['Palette']['Length'] = pal['Length']
            return i
        for nm, keys in tracks.items():
            kk = by_name[nm]
            if reps == 0:
                keys = [(0.0,) + tuple(keys[0][1:])]
            else:
                fct = stop / (d * reps)
                keys = [((r * d + x[0]) * fct,) + tuple(x[1:]) for r in range(reps) for j, x in enumerate(keys) if r == 0 or j > 0]
            r0 = rest[kk]
            data = {'_type': 'NiTransformData', 'Num Rotation Keys': len(keys), 'Rotation Type': 1,
                    'Quaternion Keys': [{'Time': float(x[0]), 'Value': quat(x[1])} for x in keys],
                    'Translations': {'Num Keys': 0, 'Keys': []}, 'Scales': {'Num Keys': 0, 'Keys': []}}
            if nm in has_T:
                data['Translations'] = {'Num Keys': len(keys), 'Interpolation': 1,
                                        'Keys': [{'Time': float(x[0]), 'Value': M.set_vec(x[2] if x[2] is not None else r0[:3, 3])} for x in keys]}
            interp = {'_type': 'NiTransformInterpolator', 'Transform': {'Translation': M.set_vec(r0[:3, 3]), 'Rotation': quat(keys[0][1]),
                                                                       'Scale': float(np.cbrt(abs(np.linalg.det(r0[:3, :3]))))}}
            interp['Data'] = k.add(data)
            ii = k.add(interp)
            sb['Controlled Blocks'].append({'Interpolator': ii, 'Controller': -1, 'String Palette': sb['String Palette'],
                                            'Node Name Offset': off(nm), 'Property Type Offset': 0xFFFFFFFF,
                                            'Controller Type Offset': off('NiTransformController'),
                                            'Controller ID Offset': 0xFFFFFFFF, 'Interpolator ID Offset': 0xFFFFFFFF})
        sb['Num Controlled Blocks'] = len(sb['Controlled Blocks'])
    used = []
    for b in k.blocks:
        if b['_type'] not in used:
            used.append(b['_type'])
    k.header['Block Types'] = [{'Length': len(x), 'Value': x.encode()} for x in used]
    k.header['Num Block Types'] = len(used)
    path = os.path.join(out_dir, NAME + '.kf')
    k.save(path)
    nif.Nif.load(path)


if __name__ == '__main__':
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(AK.HERE, '..', 'Para modelos 3D', 'Knuckles FBX')
    t, f, limbs, r = build(src, out)
    print('nif:', r['added'], 'mallas;', len(limbs), 'huesos')
    build_kf(t, f, limbs, out)
    print('kf ok ->', os.path.abspath(out))
