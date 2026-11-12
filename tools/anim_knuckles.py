"""Uganda Knuckles with animations: arms on ArmL/ArmR nodes (rotating from the shoulder) and a .kf with Idle / Move / Shoot.

    python tools/anim_knuckles.py <salida_dir>
Writes <salida_dir>/Uganda Knuckles.nif and .kf (does not touch the game).
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
HEIGHT_EXT = 25.0         # largest dimension of the model (.nif units)
ARM_X, ARM_Y = 1.3, (0.9, 2.7)    # en el .obj: |x| > 1.3 y alto entre 0.9 y 2.7 = brazo
SHOULDER = (1.35, 2.1, -0.4)
WRIST = (1.6, 2.03, -0.33)      # pivot of the Hand node: the elbow (rotates the forearm)
ELBOW_DUP = 0.3         # width (in |x| of the .obj) of the elbow zone that is duplicated
FIST = (1.953, 2.248, -0.398)    # pivot of the Fist node: above the glove's fist, where it joins the arm (user's blue dot)
SEAM = (0.85, 1.9)      # |x| of the shoulder zone duplicated in the rigid version (body and arm: covers the crack)
BONES = ['Hull', 'ArmR', 'ArmL', 'HandR', 'HandL', 'FootR', 'FootL', 'FistR', 'FistL']
ANKLE_DUP = 0.0         # without duplicating the ankle: only the shoe moves (user request)
SHOE_TOP = 0.17         # height (in the .obj) the shoe reaches up to
FOOT_Y = 0.36           # below this height (in the .obj) are the shoes
ANKLE = (0.5, 0.15, -0.25)
ARM_SWING = 12          # degrees the arms swing when walking
STEP = 10               # degrees the foot rotates when walking
WADDLE = 7              # degrees of body sway when walking
GUARD = 35              # arm rotation in guard (without skin: smaller so the shoulder does not open)
UNDER = 0.93            # size of the under-skin relative to the outer one
FIST_LIFT = 0.08        # how much the glove is raised (.obj units)
FIST_SWING = 20         # degrees the fist rocks when walking
TWIST = 30              # degrees the body turns when fighting
PUNCH = 1.5             # the forearm moves forward when punching (times REACH): so the fist does not go into the body
REACH = 0.12            # fist forward travel (fraction of HEIGHT_EXT)


def quat(axis, ang):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    s = math.sin(ang / 2)
    return {'w': math.cos(ang / 2), 'x': float(a[0] * s), 'y': float(a[1] * s), 'z': float(a[2] * s)}


def tri_rgb(m):
    """Texture color (at the UV center) of each triangle, or None."""
    img = m.get('image')
    if img is None or m.get('uv') is None:
        return None
    a = np.asarray(img.convert('RGB'), float)
    h, w = a.shape[:2]
    uv = m['uv'][m['tris']].mean(1)
    return a[np.clip((uv[:, 1] % 1) * h, 0, h - 1).astype(int), np.clip((uv[:, 0] % 1) * w, 0, w - 1).astype(int)]


def white_tris(m):
    """Triangles whose texture color (at the center of their UV) is nearly white."""
    img = m.get('image')
    if img is None or m.get('uv') is None:
        return np.zeros(len(m['tris']), bool)
    a = np.asarray(img.convert('RGB'), float)
    h, w = a.shape[:2]
    uv = m['uv'][m['tris']].mean(1)
    px = a[np.clip((uv[:, 1] % 1) * h, 0, h - 1).astype(int), np.clip((uv[:, 0] % 1) * w, 0, w - 1).astype(int)]
    return px.min(1) > 170


def skinned_meshes():
    """One skinned mesh per material: bones Hull (body, still), ArmR and ArmL. The arm weight goes from 0 to 1
    between |x| = 1.0 and 1.6 (shoulder zone) so the mesh stretches instead of opening up."""
    obj = open(os.path.join(SRC, 'ugandan knuckles.obj'), encoding='utf-8', errors='replace').read()
    ms = M.load_obj_meshes(obj, {'ugandan knuckles.mtl': open(os.path.join(SRC, 'ugandan knuckles.mtl'), 'rb').read()})
    extra = []
    for k, m in enumerate(ms):
        x, y = m['pos'][:, 0], m['pos'][:, 1]
        t = np.clip((np.abs(x) - 1.2) / 0.35, 0, 1)
        t = t * t * (3 - 2 * t)
        t *= np.clip(1 - np.maximum(ARM_Y[0] - y, y - ARM_Y[1]) / 0.3, 0, 1)   # only at arm height
        h = ((np.abs(x) > WRIST[0]) & (t > 0.99)).astype(float)     # whole glove on the hand bone (no blending: so it does not stretch)
        J = np.zeros((len(x), 4), int)
        W = np.zeros((len(x), 4))
        J[:, 1] = np.where(x > 0, 1, 2)
        J[:, 2] = np.where(x > 0, 3, 4)
        J[:, 3] = np.where(x > 0, 5, 6)
        W[:, 0] = 1 - t
        W[:, 1] = t * (1 - h)
        W[:, 2] = t * h
        # ankle: the weight moves from the body to the foot gradually (0.12 high), so the shoe bends without tearing
        f = np.clip((FOOT_Y + 0.06 - y) / 0.12, 0, 1)[:, None]
        W = W * (1 - f) + f * np.array([0, 0, 0, 1.0])
        m['name'] = 'Knuckles_%d' % k
        # gloves: rigid piece hanging from the hand bone (with skin they came out spiky in the game)
        hand = W[:, 2] > 0.999
        tri_hand = hand[m['tris']].all(1)
        fist = (np.abs(x) > 1.88)[m['tris']].all(1)
        # only the white part (glove) moves; the red at the arm tip stays still (user request)
        fist &= white_tris(m)
        # elbow: these triangles go on the arm AND on the forearm (duplicated), so the gap is not visible when rotating
        cx = np.abs(x)[m['tris']].mean(1)
        elbow = (cx > WRIST[0] - ELBOW_DUP) & (cx < WRIST[0] + 0.05) & (t[m['tris']].max(1) > 0.05) & ~tri_hand
        for side, sel in (('R', x > 0), ('L', x <= 0)):
            for node, part in (('Hand', ~fist), ('Fist', fist)):
                ts = (tri_hand & part | (elbow if node == 'Hand' else False)) & sel[m['tris']].all(1)
                if ts.any():
                    extra.append({**m, 'name': '%s%s_glove_%d' % (node, side, k), 'tris': m['tris'][ts], 'skin': None})
        # flat caps (double-sided) at the glove opening and the arm tip: the gap is not visible when the glove rotates
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
        # caps at the shoe opening (goes with the foot) and at the leg tip (stays on the body)
        footv = f[:, 0] > 0.5
        for side, sel in (('R', x > 0), ('L', x <= 0)):
            for node, part in (('Foot', footv[m['tris']].all(1)), ('Leg', ~footv[m['tris']].all(1) & (y[m['tris']].min(1) < FOOT_Y + 0.15))):
                tr = m['tris'][part & sel[m['tris']].all(1)]
                if not len(tr):
                    continue
                # seam edge: vertices shared between foot triangles and the rest
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
        # under-skin: slightly smaller copy of the arm zone, fixed to the body; if a gap opens when animating, red shows
        # underneath instead of the interior (user's idea)
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
        # the arm (still) also keeps the start of the forearm: covers the gap when the forearm moves away
        keep = tri_hand & ~fist & (cx < WRIST[0] + ELBOW_DUP)
        m['tris'] = m['tris'][~tri_hand | keep]
        # what remains with hand weight (sleeve cuff) goes to the arm: with skin on the hand it came out spiky
        W[:, 1] += W[:, 2]
        W[:, 2] = 0
        # only bones that move some vertex (a bone without vertices can crash the game);
        # a piece that depends only on the body goes without skin, hanging from Hull
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
    """Without skin: each triangle goes whole to the bone with the most weight on its vertices (Body/ArmR/HandR...)."""
    names = ['Body'] + BONES[1:]
    out = []
    for m in meshes:
        sk = m['skin']
        if sk is None:          # gloves and body-only pieces: already rigid
            out.append(m)
            continue
        bone = np.take_along_axis(sk['J'], np.argmax(sk['W'], 1)[:, None], 1)[:, 0]
        bone = np.array([BONES.index(sk['joints'][b]) for b in bone])     # local skin index -> index in BONES
        tb = np.array([np.bincount(bone[t], minlength=7).argmax() for t in m['tris']])
        # shoulder zone: the triangle goes to the body AND the arm (so a gap does not open when rotating)
        c = m['pos'][m['tris']].mean(1)
        seam = (np.abs(c[:, 0]) > SEAM[0]) & (np.abs(c[:, 0]) < SEAM[1]) & (c[:, 1] > ARM_Y[0]) & (c[:, 1] < ARM_Y[1])
        armside = np.where(c[:, 0] > 0, 1, 2)
        # ankle (sock): the triangle goes to the body AND the foot, so it does not come loose when stepping
        ankle = (np.abs(c[:, 1] - FOOT_Y) < ANKLE_DUP) & (c[:, 1] < ARM_Y[0])
        footside = np.where(c[:, 0] > 0, 5, 6)
        # only the shoe moves: the green sock stays on the body (like the gloves: only the white moves)
        rgb = tri_rgb(m)
        if rgb is not None:
            green = (rgb[:, 1] > rgb[:, 0] + 40) & (rgb[:, 1] > rgb[:, 2] + 40)
            tb = np.where(green & ((tb == 5) | (tb == 6)), 0, tb)
            ankle &= ~green
        # the red leg above the shoe also stays on the body: only what is below the ankle moves
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
        # hand: child of the arm, pivot at the wrist
        wp = np.array([sx * WRIST[0] * scale, WRIST[1] * scale, WRIST[2] * scale, 1.0])
        hb = copy.deepcopy(b)
        hb.update({'Name': nif.set_string('Hand' + nm[3:]), 'Children': [],
                   'Translation': M.set_vec((np.linalg.inv(M.world(t, ai, M.parents(t), {})) @ wp)[:3])})
        hi = t.add(hb)
        t.blocks[ai]['Children'].append(hi)
        # fist: child of the hand, pivot at the wrist (rotates separately so the spikes point at the enemy)
        fp_ = np.array([sx * FIST[0] * scale, FIST[1] * scale, FIST[2] * scale, 1.0])
        fsb = copy.deepcopy(b)
        fsb.update({'Name': nif.set_string('Fist' + nm[3:]), 'Children': [],
                    'Translation': M.set_vec((np.linalg.inv(M.world(t, hi, M.parents(t), {})) @ fp_)[:3])})
        t.blocks[hi]['Children'].append(t.add(fsb))
        # foot: child of the body, pivot at the ankle
        fp = np.array([sx * ANKLE[0] * scale, ANKLE[1] * scale, ANKLE[2] * scale, 1.0])
        fb = copy.deepcopy(b)
        fb.update({'Name': nif.set_string('Foot' + nm[3:]), 'Children': [], 'Translation': M.set_vec((np.linalg.inv(W) @ fp)[:3])})
        t.blocks[hull]['Children'].append(t.add(fb))
    r = M.import_meshes(t, meshes, keep=('__none__',), scale=scale, default_parent='Hull')
    # glove a bit higher (user request): the Fist node, which carries the glove and its cap, is raised
    par2 = M.parents(t)
    for nm in ('FistR', 'FistL'):
        i = M.find_node(t, nm)
        Wp = M.world(t, par2[i], par2, {})
        up = np.linalg.inv(Wp[:3, :3]) @ np.array([0, FIST_LIFT * scale, 0])
        t.blocks[i]['Translation'] = M.set_vec(M.vec(t.blocks[i]['Translation']) + up)
    # the arm nodes are animated by the .kf: they go in the multi-target controller
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
    side = Rh.T @ [1, 0, 0]     # world axis in Hull space (parent of the arms)
    up = Rh.T @ [0, 1, 0]
    rest = {nm: t.blocks[M.find_node(t, nm)] for nm in BONES + ['AnimNull']}
    an = M.find_node(t, 'AnimNull')
    up_an = np.linalg.inv(M.world(t, par[an], par, {})[:3, :3]) @ [0, 1, 0]     # vertical in the space of AnimNull's parent     # rest pose of each node (Hull has rotation and scale)
    front = Rh.T @ [0, 0, 1]
    Rp = M.world(t, par[hull], par, {})[:3, :3]
    hull_front = np.linalg.inv(Rp) @ [0, 0, 1]     # world front in the space of Hull's parent
    # fist push forward (+Z world), in Hull-space units
    fwd = np.linalg.inv(M.world(t, hull, par, {})[:3, :3]) @ np.array([0, 0, REACH * HEIGHT_EXT])

    def qrest(nm, ax, ang):
        """node rest rotation · requested rotation (in parent space) -> quaternion"""
        if np.ndim(ax) == 2:        # rotation already computed (matrix)
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
        """angs: [(time, axis, angle[, push 0-1])] -> interpolator blocks + data."""
        data = {'_type': 'NiTransformData', 'Num Rotation Keys': len(angs), 'Rotation Type': 1,
                'Quaternion Keys': [{'Time': float(k[0]), 'Value': qrest(nm, k[1], k[2])} for k in angs],
                'Translations': {'Num Keys': 0, 'Keys': []}, 'Scales': {'Num Keys': 0, 'Keys': []}}
        if nm.startswith(('Arm', 'Hand')):      # the arms carry position in every sequence (the same in all: otherwise it crashes when switching)
            r0 = M.vec(rest[nm]['Translation'])
            data['Translations'] = {'Num Keys': len(angs), 'Interpolation': 1,
                                    'Keys': [{'Time': float(k[0]), 'Value': M.set_vec(r0 + (k[3] if len(k) > 3 else 0) * (np.linalg.inv(M.rot(rest[par_name[nm]]['Rotation'])) @ fwd if nm.startswith('Hand') else fwd))} for k in angs]}
        q0 = qrest(nm, angs[0][1], angs[0][2])
        interp = {'_type': 'NiTransformInterpolator', 'Transform': {'Translation': rest[nm]['Translation'], 'Rotation': q0, 'Scale': rest[nm]['Scale']}}
        return interp, data
    def aim(hand):
        """forearm rotation (from the elbow) so the fist spikes point forward"""
        hi = M.find_node(t, hand)
        # forearm tip + fist (vertices farthest from the elbow), in hand space
        Wh = np.linalg.inv(M.world(t, hi, par, {}))
        sub = {hi, M.find_node(t, 'Fist' + hand[-1])}
        P = []
        for i in range(len(t.blocks)):
            if par.get(i) in sub and t.blocks[i]['_type'] == 'NiTriShape':
                g = M.geometry(t, t.blocks[t.blocks[i]['Data']])
                q = np.asarray(g[0])[np.unique(np.asarray(g[4]))]     # only the vertices the piece uses
                P.append((np.c_[q, np.ones((len(q), 1))] @ (Wh @ M.world(t, i, par, {})).T)[:, :3])
        P = np.vstack(P)
        d = np.linalg.norm(P, axis=1)
        v = M.rot(rest[hand]['Rotation']) @ P[d >= np.percentile(d, 98)].mean(0)
        u = M.rot(rest[par_name[hand]]['Rotation']).T @ front     # forward (the arms no longer rotate)
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
        """fist rotation (in the space of the already rotated hand H) so the spikes, which face outward at rest, face forward"""
        out = side if hand.endswith('R') else -side
        # in the game what faces outward at rest is the glove opening: the spikes are on the other side
        return rotmin(-out, H.T @ front)

    def rotmin(v, u):
        v, u = v / np.linalg.norm(v), u / np.linalg.norm(u)
        c = np.cross(v, u)
        K = np.array([[0, -c[2], c[1]], [c[2], 0, -c[0]], [-c[1], c[0], 0]])
        return np.eye(3) + K + K @ K / (1 + v @ u)

    def extend(arm, hand):
        """arm rotation so the fist (glove center already aligned) is stretched forward, at shoulder height"""
        hi = M.find_node(t, hand)
        g = np.mean([(M.local(t.blocks[i]) @ np.r_[np.asarray(M.geometry(t, t.blocks[t.blocks[i]['Data']])[0]).mean(0), 1])[:3]
                     for i in range(len(t.blocks)) if par.get(i) == hi and t.blocks[i]['_type'] == 'NiTriShape'], 0)
        h = M.local(t.blocks[hi])
        tip = (h[:3, :3] @ aim(hand) @ np.linalg.inv(h[:3, :3]) @ (h[:3, :3] @ g)) + h[:3, 3]   # glove center in arm space
        return rotmin(M.rot(rest[arm]['Rotation']) @ tip, front)

    deg = math.radians
    n = 16
    seqs = {
        # balanceo suave
        # without skin the arms do not rotate (the shoulder would open): only the gloves move, as the user asked
        # at rest: the model as-is, not animated (user request: the guard left a gap)
        'Idle': (2.0, {}),
        # walking: the gloves swing back and forth; the feet take steps
        # walking only the feet (swinging the forearm opened a gap at the elbow)
        'Move': (1.0, {
                       # the fist rocks back and forth from the wrist (user request), alternating
                       **{nm: [(i * 1.0 / n, side, s * deg(FIST_SWING) * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
                          for nm, s in (('FistR', 1), ('FistL', -1))},
                       **{nm: [(i * 1.0 / n, side, s * deg(STEP) * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
                          for nm, s in (('FootR', -1), ('FootL', 1))}}),
        # fight: the whole body (tank AnimNull node) turns side to side, as if punching; arms still
        # (moving them broke the skinless geometry) and the fist spikes forward
        'Shoot': (1.6, {'AnimNull': [(0.0, up_an, 0.0), (0.3, up_an, deg(TWIST)), (0.6, up_an, deg(TWIST)), (0.8, up_an, 0.0),
                                     (1.1, up_an, deg(-TWIST)), (1.4, up_an, deg(-TWIST)), (1.6, up_an, 0.0)],
                        # the fists rock from the wrist in time with the turn (they do not stay still)
                        **{nm: [(i * 1.6 / n, side, s * deg(FIST_SWING) * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
                           for nm, s in (('FistR', 1), ('FistL', -1))}}),
    }
    # as in the game's .kf files: every sequence controls the same nodes (otherwise the game crashes when switching
    # animation); nodes a sequence does not use stay still in their rest pose
    # Hull is not animated: the game uses it to move the unit (animating it crashed when walking)
    for dur, tracks in seqs.values():
        for nm in BONES[1:]:
            if nm not in tracks:
                tracks[nm] = [(0.0, up, 0.0), (dur, up, 0.0)]
        for nm in list(tracks):
            tracks[nm] = tracks.pop(nm)
    seqs = {k: (d, {nm: tr[nm] for nm in BONES[1:] + [x for x in tr if x not in BONES]}) for k, (d, tr) in seqs.items()}
    # the tank sequences are kept (Tank, AnimNull, Turret, Frame0-4 flashes, text keys): the game
    # expects them when switching animation; only the bone tracks are added, fitted to each one's duration
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
            if reps == 0:           # game Idle: fixed pose (Stop 0)
                keys = [(0.0,) + tuple(keys[0][1:])]
            else:
                f = stop / (dur * reps)
                keys = [((r * dur + kk[0]) * f,) + tuple(kk[1:]) for r in range(reps) for j, kk in enumerate(keys) if r == 0 or j > 0]
            interp, data = track(nm, keys)
            interp['Data'] = k.add(data)
            ii = k.add(interp)
            old = [c for c in sb['Controlled Blocks'] if pal['Value'][c['Node Name Offset']:].split(bytes(1))[0] == nm.encode()]
            if old:         # node the tank already animates (AnimNull): its track is replaced
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
