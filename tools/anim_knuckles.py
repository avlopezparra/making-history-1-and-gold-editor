"""Uganda Knuckles con animaciones: brazos en nodos ArmL/ArmR (giran desde el hombro) y un .kf con Idle / Move / Shoot.

    python tools/anim_knuckles.py <salida_dir>
Escribe <salida_dir>/Uganda Knuckles.nif y .kf (no toca el juego).
"""
import copy
import math
import os
import sys

import numpy as np

import nif
import nif_mesh as M

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'Para modelos 3D', 'Ugandan Knuckles')
GAME3D = os.path.join(r'C:\Program Files (x86)\Steam\steamapps\common\Making History The Calm and The Storm\Modern Europe\system\ui\art\3D')
TEMPLATE = os.path.join(GAME3D, 'Armored', 'USSR', 'Medium-Tank-USSR')
HEIGHT_EXT = 25.0         # mayor medida del modelo (unidades del .nif)
ARM_X, ARM_Y = 1.3, (0.9, 2.7)    # en el .obj: |x| > 1.3 y alto entre 0.9 y 2.7 = brazo
SHOULDER = (1.35, 2.1, -0.4)
WRIST = (1.6, 2.03, -0.33)      # pivote del nodo Hand: el codo (gira el antebrazo)
ELBOW_DUP = 0.3         # ancho (en |x| del .obj) de la zona del codo que se duplica
FIST = (1.953, 2.248, -0.398)    # pivote del nodo Fist: arriba del puño del guante, donde se une con el brazo (punto azul del usuario)
SEAM = (0.85, 1.9)      # |x| de la zona del hombro que se duplica en la versión rígida (cuerpo y brazo: tapa la grieta)
BONES = ['Hull', 'ArmR', 'ArmL', 'HandR', 'HandL', 'FootR', 'FootL', 'FistR', 'FistL']
ANKLE_DUP = 0.0         # sin duplicar el tobillo: solo se mueve el zapato (pedido del usuario)
SHOE_TOP = 0.17         # alto (en el .obj) hasta donde llega el zapato
FOOT_Y = 0.36           # bajo esta altura (en el .obj) son los zapatos
ANKLE = (0.5, 0.15, -0.25)
ARM_SWING = 12          # grados que balancean los brazos al caminar
STEP = 10               # grados que gira el pie al caminar
WADDLE = 7              # grados de contoneo del cuerpo al caminar
GUARD = 35              # giro del brazo en guardia (sin piel: más chico para que no se abra el hombro)
UNDER = 0.93            # tamaño de la piel de abajo respecto de la de fuera
FIST_LIFT = 0.08        # cuánto se sube el guante (unidades del .obj)
FIST_SWING = 20         # grados que se mece el puño al caminar
TWIST = 30              # grados que gira el cuerpo al pelear
PUNCH = 1.5             # el antebrazo avanza al golpear (veces REACH): así el puño no se mete en el cuerpo
REACH = 0.12            # avance del puño (fracción de HEIGHT_EXT)


def quat(axis, ang):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    s = math.sin(ang / 2)
    return {'w': math.cos(ang / 2), 'x': float(a[0] * s), 'y': float(a[1] * s), 'z': float(a[2] * s)}


def tri_rgb(m):
    """Color de textura (en el centro de la UV) de cada triángulo, o None."""
    img = m.get('image')
    if img is None or m.get('uv') is None:
        return None
    a = np.asarray(img.convert('RGB'), float)
    h, w = a.shape[:2]
    uv = m['uv'][m['tris']].mean(1)
    return a[np.clip((uv[:, 1] % 1) * h, 0, h - 1).astype(int), np.clip((uv[:, 0] % 1) * w, 0, w - 1).astype(int)]


def white_tris(m):
    """Triángulos cuyo color de textura (en el centro de su UV) es casi blanco."""
    img = m.get('image')
    if img is None or m.get('uv') is None:
        return np.zeros(len(m['tris']), bool)
    a = np.asarray(img.convert('RGB'), float)
    h, w = a.shape[:2]
    uv = m['uv'][m['tris']].mean(1)
    px = a[np.clip((uv[:, 1] % 1) * h, 0, h - 1).astype(int), np.clip((uv[:, 0] % 1) * w, 0, w - 1).astype(int)]
    return px.min(1) > 170


def skinned_meshes():
    """Una malla con piel por material: huesos Hull (cuerpo, quieto), ArmR y ArmL. El peso del brazo sube de 0 a 1
    entre |x| = 1.0 y 1.6 (zona del hombro) para que la malla se estire en vez de abrirse."""
    obj = open(os.path.join(SRC, 'ugandan knuckles.obj'), encoding='utf-8', errors='replace').read()
    ms = M.load_obj_meshes(obj, {'ugandan knuckles.mtl': open(os.path.join(SRC, 'ugandan knuckles.mtl'), 'rb').read()})
    extra = []
    for k, m in enumerate(ms):
        x, y = m['pos'][:, 0], m['pos'][:, 1]
        t = np.clip((np.abs(x) - 1.2) / 0.35, 0, 1)
        t = t * t * (3 - 2 * t)
        t *= np.clip(1 - np.maximum(ARM_Y[0] - y, y - ARM_Y[1]) / 0.3, 0, 1)   # solo a la altura de los brazos
        h = ((np.abs(x) > WRIST[0]) & (t > 0.99)).astype(float)     # guante entero en el hueso de la mano (sin mezcla: así no se estira)
        J = np.zeros((len(x), 4), int)
        W = np.zeros((len(x), 4))
        J[:, 1] = np.where(x > 0, 1, 2)
        J[:, 2] = np.where(x > 0, 3, 4)
        J[:, 3] = np.where(x > 0, 5, 6)
        W[:, 0] = 1 - t
        W[:, 1] = t * (1 - h)
        W[:, 2] = t * h
        # tobillo: el peso pasa del cuerpo al pie poco a poco (0.12 de alto), así el zapato se dobla sin cortarse
        f = np.clip((FOOT_Y + 0.06 - y) / 0.12, 0, 1)[:, None]
        W = W * (1 - f) + f * np.array([0, 0, 0, 1.0])
        m['name'] = 'Knuckles_%d' % k
        # guantes: pieza rígida colgada del hueso de la mano (con piel salían con puntas en el juego)
        hand = W[:, 2] > 0.999
        tri_hand = hand[m['tris']].all(1)
        fist = (np.abs(x) > 1.88)[m['tris']].all(1)
        # solo la parte blanca (guante) se mueve; lo rojo de la punta del brazo queda quieto (pedido del usuario)
        fist &= white_tris(m)
        # codo: estos triángulos van en el brazo Y en el antebrazo (duplicados), así al girar no se ve el hueco
        cx = np.abs(x)[m['tris']].mean(1)
        elbow = (cx > WRIST[0] - ELBOW_DUP) & (cx < WRIST[0] + 0.05) & (t[m['tris']].max(1) > 0.05) & ~tri_hand
        for side, sel in (('R', x > 0), ('L', x <= 0)):
            for node, part in (('Hand', ~fist), ('Fist', fist)):
                ts = (tri_hand & part | (elbow if node == 'Hand' else False)) & sel[m['tris']].all(1)
                if ts.any():
                    extra.append({**m, 'name': '%s%s_glove_%d' % (node, side, k), 'tris': m['tris'][ts], 'skin': None})
        # tapas planas (doble cara) en la boca del guante y en la punta del brazo: al girar el guante no se ve el hueco
        for side, sel in (('R', x > 0), ('L', x <= 0)):
            for node, part in (('Fist', fist), ('Arm', ~fist & (t[m['tris']].max(1) > 0.05))):
                tr = m['tris'][part & sel[m['tris']].all(1)]
                if not len(tr):
                    continue
                vs = np.unique(tr)
                ring = vs[np.abs(np.abs(x[vs]) - 1.9) < 0.06]
                if len(ring) < 3:
                    continue
                P = m['pos'][ring]
                c = P.mean(0)
                _, _, Vt = np.linalg.svd(P - c)
                e1, e2 = Vt[0], Vt[1]
                ring = ring[np.argsort(np.arctan2((P - c) @ e2, (P - c) @ e1))]
                ci = len(m['pos'])
                pos = np.vstack([m['pos'], c])
                uv = np.vstack([m['uv'], m['uv'][ring].mean(0)]) if m.get('uv') is not None else None
                nor = np.vstack([m['nor'], Vt[2]]) if m.get('nor') is not None else None
                fan = [(ci, int(ring[i]), int(ring[(i + 1) % len(ring)])) for i in range(len(ring))]
                fan += [(a, c_, b) for a, b, c_ in fan]
                extra.append({**m, 'pos': pos, 'uv': uv, 'nor': nor, 'name': '%s%s_cap_%d' % (node, side, k),
                              'tris': np.array(fan, np.uint32), 'skin': None})
        # tapas en la boca del zapato (va con el pie) y en la punta de la pierna (queda en el cuerpo)
        footv = f[:, 0] > 0.5
        for side, sel in (('R', x > 0), ('L', x <= 0)):
            for node, part in (('Foot', footv[m['tris']].all(1)), ('Leg', ~footv[m['tris']].all(1) & (y[m['tris']].min(1) < FOOT_Y + 0.15))):
                tr = m['tris'][part & sel[m['tris']].all(1)]
                if not len(tr):
                    continue
                # borde de unión: vértices compartidos entre triángulos del pie y del resto
                ft = footv[m['tris']].all(1)
                vf = np.unique(m['tris'][ft & sel[m['tris']].all(1)])
                vo = np.unique(m['tris'][~ft & sel[m['tris']].all(1)])
                key = lambda v: map(tuple, np.round(m['pos'][v], 4))
                shared = set(key(vf)) & set(key(vo))
                edge = np.array([v for v, kk in zip(vf if node == 'Foot' else vo, key(vf if node == 'Foot' else vo)) if kk in shared], int)
                if len(edge) < 3:
                    continue
                P = m['pos'][edge]
                c0 = P.mean(0)
                ang = np.arctan2(P[:, 2] - c0[2], P[:, 0] - c0[0])
                edge = edge[np.argsort(ang)]
                ci = len(m['pos'])
                pos = np.vstack([m['pos'], c0])
                uv = np.vstack([m['uv'], m['uv'][edge].mean(0)]) if m.get('uv') is not None else None
                nor = np.vstack([m['nor'], [0, 1, 0]]) if m.get('nor') is not None else None
                fan = [(ci, int(edge[i]), int(edge[(i + 1) % len(edge)])) for i in range(len(edge))]
                fan += [(a, c_, b) for a, b, c_ in fan]
                extra.append({**m, 'pos': pos, 'uv': uv, 'nor': nor, 'name': '%s%s_cap_%d' % (node, side, k),
                              'tris': np.array(fan, np.uint32), 'skin': None})
        # piel de abajo: copia algo más chica de la zona del brazo, fija al cuerpo; si al animar se abre un hueco se ve
        # rojo debajo en vez del interior (idea del usuario)
        under = (t[m['tris']].max(1) > 0.05) & ~fist
        if under.any():
            pos = m['pos'].copy()
            a = np.array([SHOULDER[0], SHOULDER[1], SHOULDER[2]])
            b_ = np.array([FIST[0], FIST[1], FIST[2]])
            for sgn in (1, -1):
                sel_v = (x * sgn > 0)
                a2, b2 = a * [sgn, 1, 1], b_ * [sgn, 1, 1]
                d = (b2 - a2) / np.linalg.norm(b2 - a2)
                q = pos[sel_v] - a2
                axis_pt = a2 + np.outer(np.clip(q @ d, 0, np.linalg.norm(b2 - a2)), d)
                pos[sel_v] = axis_pt + UNDER * (pos[sel_v] - axis_pt)
            extra.append({**m, 'pos': pos, 'name': 'Under_%d' % k, 'tris': m['tris'][under], 'skin': None})
        # el brazo (quieto) también conserva el principio del antebrazo: tapa el hueco cuando el antebrazo se aleja
        keep = tri_hand & ~fist & (cx < WRIST[0] + ELBOW_DUP)
        m['tris'] = m['tris'][~tri_hand | keep]
        # lo que queda con peso de mano (puño de la manga) va al brazo: con piel en la mano salían puntas
        W[:, 1] += W[:, 2]
        W[:, 2] = 0
        # solo los huesos que mueven algún vértice (un hueso sin vértices puede cerrar el juego);
        # una pieza que solo depende del cuerpo va sin piel, colgada de Hull
        used = sorted({int(j) for j in J[W > 0]})
        if used == [0]:
            m['skin'] = None
            continue
        remap = {b: i for i, b in enumerate(used)}
        J = np.vectorize(lambda b: remap.get(int(b), 0))(J)
        W = np.where(np.isin(np.arange(J.shape[1])[None, :].repeat(len(J), 0), range(J.shape[1])), W, 0)
        m['skin'] = {'joints': [BONES[b] for b in used], 'ibm': [np.eye(4)] * len(used), 'joint_world': [np.eye(4)] * len(used), 'J': J, 'W': W}
    return [m for m in ms if len(m['tris'])] + extra


def rigid(meshes):
    """Sin piel: cada triángulo va entero al hueso que más pesa en sus vértices (Body/ArmR/HandR...)."""
    names = ['Body'] + BONES[1:]
    out = []
    for m in meshes:
        sk = m['skin']
        if sk is None:          # guantes y piezas solo del cuerpo: ya son rígidas
            out.append(m)
            continue
        bone = np.take_along_axis(sk['J'], np.argmax(sk['W'], 1)[:, None], 1)[:, 0]
        bone = np.array([BONES.index(sk['joints'][b]) for b in bone])     # índice local de la piel -> índice en BONES
        tb = np.array([np.bincount(bone[t], minlength=7).argmax() for t in m['tris']])
        # zona del hombro: el triángulo va al cuerpo Y al brazo (así al girar no se abre un hueco)
        c = m['pos'][m['tris']].mean(1)
        seam = (np.abs(c[:, 0]) > SEAM[0]) & (np.abs(c[:, 0]) < SEAM[1]) & (c[:, 1] > ARM_Y[0]) & (c[:, 1] < ARM_Y[1])
        armside = np.where(c[:, 0] > 0, 1, 2)
        # tobillo (calcetín): el triángulo va al cuerpo Y al pie, así al dar el paso no se desprende
        ankle = (np.abs(c[:, 1] - FOOT_Y) < ANKLE_DUP) & (c[:, 1] < ARM_Y[0])
        footside = np.where(c[:, 0] > 0, 5, 6)
        # solo el zapato se mueve: el calcetín verde queda en el cuerpo (como los guantes: solo se mueve lo blanco)
        rgb = tri_rgb(m)
        if rgb is not None:
            green = (rgb[:, 1] > rgb[:, 0] + 40) & (rgb[:, 1] > rgb[:, 2] + 40)
            tb = np.where(green & ((tb == 5) | (tb == 6)), 0, tb)
            ankle &= ~green
        # la pierna roja sobre el zapato también queda en el cuerpo: solo se mueve lo que está bajo el tobillo
        tb = np.where(((tb == 5) | (tb == 6)) & (c[:, 1] > SHOE_TOP), 0, tb)
        for b in range(7):
            sel = (tb == b) | (seam & (b == 0)) | (seam & (armside == b)) | (ankle & (b == 0)) | (ankle & (footside == b))
            if sel.any():
                out.append({**m, 'skin': None, 'name': '%s_%s' % (names[b], m['name']), 'tris': m['tris'][sel]})
    return out


def build_nif(out_dir):
    meshes = skinned_meshes()
    if RIGID:
        meshes = rigid(meshes)
    allp = np.vstack([m['pos'] for m in meshes])
    scale = HEIGHT_EXT / (allp.max(0) - allp.min(0)).max()
    t = nif.Nif.load(TEMPLATE + '.nif')
    par = M.parents(t)
    hull = M.find_node(t, 'Hull')
    W = M.world(t, hull, par, {})
    proto = next(b for b in t.blocks if b['_type'] == 'NiNode' and M.name(b) == 'Parts')
    for nm, sx in (('ArmR', 1), ('ArmL', -1)):
        p = np.array([sx * SHOULDER[0] * scale, SHOULDER[1] * scale, SHOULDER[2] * scale, 1.0])
        loc = np.linalg.inv(W) @ p
        b = copy.deepcopy(proto)
        b.update({'Name': nif.set_string(nm), 'Controller': -1, 'Children': [], 'Translation': M.set_vec(loc[:3]),
                  'Rotation': M.set_rot(np.eye(3)), 'Scale': 1.0})
        ai = t.add(b)
        t.blocks[hull]['Children'].append(ai)
        # mano: hija del brazo, con el pivote en la muñeca
        wp = np.array([sx * WRIST[0] * scale, WRIST[1] * scale, WRIST[2] * scale, 1.0])
        hb = copy.deepcopy(b)
        hb.update({'Name': nif.set_string('Hand' + nm[3:]), 'Children': [],
                   'Translation': M.set_vec((np.linalg.inv(M.world(t, ai, M.parents(t), {})) @ wp)[:3])})
        hi = t.add(hb)
        t.blocks[ai]['Children'].append(hi)
        # puño: hijo de la mano, con el pivote en la muñeca (gira aparte para que las púas apunten al enemigo)
        fp_ = np.array([sx * FIST[0] * scale, FIST[1] * scale, FIST[2] * scale, 1.0])
        fsb = copy.deepcopy(b)
        fsb.update({'Name': nif.set_string('Fist' + nm[3:]), 'Children': [],
                    'Translation': M.set_vec((np.linalg.inv(M.world(t, hi, M.parents(t), {})) @ fp_)[:3])})
        t.blocks[hi]['Children'].append(t.add(fsb))
        # pie: hijo del cuerpo, con el pivote en el tobillo
        fp = np.array([sx * ANKLE[0] * scale, ANKLE[1] * scale, ANKLE[2] * scale, 1.0])
        fb = copy.deepcopy(b)
        fb.update({'Name': nif.set_string('Foot' + nm[3:]), 'Children': [], 'Translation': M.set_vec((np.linalg.inv(W) @ fp)[:3])})
        t.blocks[hull]['Children'].append(t.add(fb))
    r = M.import_meshes(t, meshes, keep=('__none__',), scale=scale, default_parent='Hull')
    # guante un poco más arriba (pedido del usuario): se sube el nodo Fist, que lleva el guante y su tapa
    par2 = M.parents(t)
    for nm in ('FistR', 'FistL'):
        i = M.find_node(t, nm)
        Wp = M.world(t, par2[i], par2, {})
        up = np.linalg.inv(Wp[:3, :3]) @ np.array([0, FIST_LIFT * scale, 0])
        t.blocks[i]['Translation'] = M.set_vec(M.vec(t.blocks[i]['Translation']) + up)
    # los nodos de los brazos los anima el .kf: van en el controlador de varios objetivos
    for b in t.blocks:
        if b['_type'] == 'NiMultiTargetTransformController':
            for nm in BONES[1:]:
                i = M.find_node(t, nm)
                if i not in b['Extra Targets']:
                    b['Extra Targets'].append(i)
    t.save(os.path.join(out_dir, 'Uganda Knuckles.nif'))
    return t, r


def build_kf(t, out_dir):
    k = nif.Nif.load(TEMPLATE + '.kf')
    seq_proto = next(b for b in k.blocks if b['_type'] == 'NiControllerSequence')
    par = M.parents(t)
    hull = M.find_node(t, 'Hull')
    Rh = M.world(t, hull, par, {})[:3, :3]
    Rh = Rh / np.cbrt(np.linalg.det(Rh))
    side = Rh.T @ [1, 0, 0]     # eje del mundo en el espacio de Hull (padre de los brazos)
    up = Rh.T @ [0, 1, 0]
    rest = {nm: t.blocks[M.find_node(t, nm)] for nm in BONES + ['AnimNull']}
    an = M.find_node(t, 'AnimNull')
    up_an = np.linalg.inv(M.world(t, par[an], par, {})[:3, :3]) @ [0, 1, 0]     # vertical en el espacio del padre de AnimNull     # pose de reposo de cada nodo (Hull tiene giro y escala)
    front = Rh.T @ [0, 0, 1]
    Rp = M.world(t, par[hull], par, {})[:3, :3]
    hull_front = np.linalg.inv(Rp) @ [0, 0, 1]     # frente del mundo en el espacio del padre de Hull
    # empuje del puño hacia el frente (+Z del mundo), en unidades del espacio de Hull
    fwd = np.linalg.inv(M.world(t, hull, par, {})[:3, :3]) @ np.array([0, 0, REACH * HEIGHT_EXT])

    def qrest(nm, ax, ang):
        """giro de reposo del nodo · giro pedido (en el espacio del padre) -> cuaternión"""
        if np.ndim(ax) == 2:        # giro ya calculado (matriz)
            Rm = np.asarray(ax) @ M.rot(rest[nm]['Rotation'])
        else:
            a = np.asarray(ax, float) / np.linalg.norm(ax)
            K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
            Rm = (np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K) @ M.rot(rest[nm]['Rotation'])
        w = math.sqrt(max(0.0, 1 + Rm[0, 0] + Rm[1, 1] + Rm[2, 2])) / 2
        if w < 1e-4 and np.ndim(ax) != 2:
            return quat(ax, ang)
        return {'w': w, 'x': (Rm[2, 1] - Rm[1, 2]) / (4 * w), 'y': (Rm[0, 2] - Rm[2, 0]) / (4 * w), 'z': (Rm[1, 0] - Rm[0, 1]) / (4 * w)}

    par_name = {'HandR': 'ArmR', 'HandL': 'ArmL'}

    def track(nm, angs):
        """angs: [(tiempo, eje, ángulo[, empuje 0-1])] -> bloques interpolador + datos."""
        data = {'_type': 'NiTransformData', 'Num Rotation Keys': len(angs), 'Rotation Type': 1,
                'Quaternion Keys': [{'Time': float(k[0]), 'Value': qrest(nm, k[1], k[2])} for k in angs],
                'Translations': {'Num Keys': 0, 'Keys': []}, 'Scales': {'Num Keys': 0, 'Keys': []}}
        if nm.startswith(('Arm', 'Hand')):      # los brazos llevan posición en todas las secuencias (igual en todas: si no, se cierra al cambiar)
            r0 = M.vec(rest[nm]['Translation'])
            data['Translations'] = {'Num Keys': len(angs), 'Interpolation': 1,
                                    'Keys': [{'Time': float(k[0]), 'Value': M.set_vec(r0 + (k[3] if len(k) > 3 else 0) * (np.linalg.inv(M.rot(rest[par_name[nm]]['Rotation'])) @ fwd if nm.startswith('Hand') else fwd))} for k in angs]}
        q0 = qrest(nm, angs[0][1], angs[0][2])
        interp = {'_type': 'NiTransformInterpolator', 'Transform': {'Translation': rest[nm]['Translation'], 'Rotation': q0, 'Scale': rest[nm]['Scale']}}
        return interp, data
    def aim(hand):
        """giro del antebrazo (desde el codo) para que las púas del puño apunten al frente"""
        hi = M.find_node(t, hand)
        # punta del antebrazo + puño (vértices más lejos del codo), en el espacio de la mano
        Wh = np.linalg.inv(M.world(t, hi, par, {}))
        sub = {hi, M.find_node(t, 'Fist' + hand[-1])}
        P = []
        for i in range(len(t.blocks)):
            if par.get(i) in sub and t.blocks[i]['_type'] == 'NiTriShape':
                g = M.geometry(t, t.blocks[t.blocks[i]['Data']])
                q = np.asarray(g[0])[np.unique(np.asarray(g[4]))]     # solo los vértices que usa la pieza
                P.append((np.c_[q, np.ones((len(q), 1))] @ (Wh @ M.world(t, i, par, {})).T)[:, :3])
        P = np.vstack(P)
        d = np.linalg.norm(P, axis=1)
        v = M.rot(rest[hand]['Rotation']) @ P[d >= np.percentile(d, 98)].mean(0)
        u = M.rot(rest[par_name[hand]]['Rotation']).T @ front     # al frente (los brazos ya no giran)
        v, u = v / np.linalg.norm(v), u / np.linalg.norm(u)
        c = np.cross(v, u)
        K = np.array([[0, -c[2], c[1]], [c[2], 0, -c[0]], [-c[1], c[0], 0]])
        return np.eye(3) + K + K @ K / (1 + v @ u)
    def half(hand, f=0.5):
        """el giro de aim() a medias (guardia)"""
        R = aim(hand)
        ang = math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2)))
        if ang < 1e-6:
            return np.eye(3)
        ax = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * math.sin(ang))
        K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
        a = ang * f
        return np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * K @ K

    def fist(hand, H):
        """giro del puño (en el espacio de la mano ya girada H) para que las púas, que en reposo miran hacia fuera, miren al frente"""
        out = side if hand.endswith('R') else -side
        # en el juego lo que mira hacia fuera en reposo es la abertura del guante: las púas están al otro lado
        return rotmin(-out, H.T @ front)

    def rotmin(v, u):
        v, u = v / np.linalg.norm(v), u / np.linalg.norm(u)
        c = np.cross(v, u)
        K = np.array([[0, -c[2], c[1]], [c[2], 0, -c[0]], [-c[1], c[0], 0]])
        return np.eye(3) + K + K @ K / (1 + v @ u)

    def extend(arm, hand):
        """giro del brazo para que el puño (centro del guante ya alineado) quede estirado al frente, a la altura del hombro"""
        hi = M.find_node(t, hand)
        g = np.mean([(M.local(t.blocks[i]) @ np.r_[np.asarray(M.geometry(t, t.blocks[t.blocks[i]['Data']])[0]).mean(0), 1])[:3]
                     for i in range(len(t.blocks)) if par.get(i) == hi and t.blocks[i]['_type'] == 'NiTriShape'], 0)
        h = M.local(t.blocks[hi])
        tip = (h[:3, :3] @ aim(hand) @ np.linalg.inv(h[:3, :3]) @ (h[:3, :3] @ g)) + h[:3, 3]   # centro del guante en el espacio del brazo
        return rotmin(M.rot(rest[arm]['Rotation']) @ tip, front)

    deg = math.radians
    n = 16
    seqs = {
        # balanceo suave
        # sin piel los brazos no giran (se abriría el hombro): solo se mueven los guantes, como pidió el usuario
        # en reposo: el modelo tal cual, sin animar (pedido del usuario: la guardia dejaba un hueco)
        'Idle': (2.0, {}),
        # al caminar: los guantes se balancean adelante y atrás; los pies dan pasos
        # al caminar solo los pies (balancear el antebrazo abría un hueco en el codo)
        'Move': (1.0, {
                       # el puño se mece adelante y atrás desde la muñeca (pedido del usuario), alternado
                       **{nm: [(i * 1.0 / n, side, s * deg(FIST_SWING) * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
                          for nm, s in (('FistR', 1), ('FistL', -1))},
                       **{nm: [(i * 1.0 / n, side, s * deg(STEP) * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
                          for nm, s in (('FootR', -1), ('FootL', 1))}}),
        # pelea: gira todo el cuerpo (nodo AnimNull del tanque) a un lado y al otro, como golpeando; los brazos quietos
        # (moverlos rompía la geometría sin piel) y las púas de los puños al frente
        'Shoot': (1.6, {'AnimNull': [(0.0, up_an, 0.0), (0.3, up_an, deg(TWIST)), (0.6, up_an, deg(TWIST)), (0.8, up_an, 0.0),
                                     (1.1, up_an, deg(-TWIST)), (1.4, up_an, deg(-TWIST)), (1.6, up_an, 0.0)],
                        # los puños se mecen desde la muñeca al ritmo del giro (no quedan quietos)
                        **{nm: [(i * 1.6 / n, side, s * deg(FIST_SWING) * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
                           for nm, s in (('FistR', 1), ('FistL', -1))}}),
    }
    # como en los .kf del juego: todas las secuencias controlan los mismos nodos (si no, el juego se cierra al cambiar
    # de animación); los que una secuencia no usa quedan quietos en su pose de reposo
    # Hull no se anima: el juego lo usa para mover la unidad (animarlo lo cerraba al caminar)
    for dur, tracks in seqs.values():
        for nm in BONES[1:]:
            if nm not in tracks:
                tracks[nm] = [(0.0, up, 0.0), (dur, up, 0.0)]
        for nm in list(tracks):
            tracks[nm] = tracks.pop(nm)
    seqs = {k: (d, {nm: tr[nm] for nm in BONES[1:] + [x for x in tr if x not in BONES]}) for k, (d, tr) in seqs.items()}
    # se conservan las secuencias del tanque (Tank, AnimNull, Turret, destellos Frame0-4, text keys): el juego las
    # espera al cambiar de animación; solo se añaden las pistas de los huesos, ajustadas a la duración de cada una
    for si, sb in enumerate(k.blocks):
        if sb['_type'] != 'NiControllerSequence' or nif.string(sb['Name']) not in seqs:
            continue
        dur, tracks = seqs[nif.string(sb['Name'])]
        stop = sb['Stop Time']
        reps = max(1, round(stop / dur)) if dur and stop > 0 else 0
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
            if reps == 0:           # Idle del juego: pose fija (Stop 0)
                keys = [(0.0,) + tuple(keys[0][1:])]
            else:
                f = stop / (dur * reps)
                keys = [((r * dur + kk[0]) * f,) + tuple(kk[1:]) for r in range(reps) for j, kk in enumerate(keys) if r == 0 or j > 0]
            interp, data = track(nm, keys)
            interp['Data'] = k.add(data)
            ii = k.add(interp)
            old = [c for c in sb['Controlled Blocks'] if pal['Value'][c['Node Name Offset']:].split(bytes(1))[0] == nm.encode()]
            if old:         # nodo que el tanque ya anima (AnimNull): se reemplaza su pista
                old[0]['Interpolator'] = ii
                continue
            sb['Controlled Blocks'].append({'Interpolator': ii, 'Controller': -1, 'String Palette': sb['String Palette'],
                                            'Node Name Offset': off(nm), 'Property Type Offset': 0xFFFFFFFF,
                                            'Controller Type Offset': off('NiTransformController'),
                                            'Controller ID Offset': 0xFFFFFFFF, 'Interpolator ID Offset': 0xFFFFFFFF})
        sb['Num Controlled Blocks'] = len(sb['Controlled Blocks'])
    k.footer['Roots'] = [i for i, b in enumerate(k.blocks) if b['_type'] == 'NiControllerSequence']
    k.footer['Num Roots'] = len(k.footer['Roots'])
    used = []
    for b in k.blocks:
        if b['_type'] not in used:
            used.append(b['_type'])
    k.header['Block Types'] = [{'Length': len(x), 'Value': x.encode()} for x in used]
    k.header['Num Block Types'] = len(used)
    path = os.path.join(out_dir, 'Uganda Knuckles.kf')
    k.save(path)
    nif.Nif.load(path)
    return [b['_type'] for b in k.blocks]


RIGID = '--rigido' in sys.argv

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    out = args[0] if args else SRC
    t, r = build_nif(out)
    print('nif:', r['added'], 'mallas;', [p for p in r['placed'] if 'Arm' in p][:4])
    print('kf:', build_kf(t, out))
