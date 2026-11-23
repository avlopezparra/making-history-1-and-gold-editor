"""Reader for the unit / city models of Making History: The Great War and The Second World War (.nst, «NEST» v2).

Format (reverse engineered, little-endian; see NST_UNIDADES.md):
  'NEST', u32 2, u32 ntypes, ntypes x (8-byte type hash, u32 version), u32 k, (k+1) x u32 (roots / clip objects),
  then the objects one after another: 8-byte type hash + body. Objects are numbered in order (0, 1, ...) and refer to
  each other by that number (u32). Strings are u32 length + bytes, no terminator.
The scene is a Maya export through COLLADA: nodes with a COLLADA-style transform stack (translate, rotatePivot, rotateZ/Y/X,
rotatePivotInverse, scalePivot, scale, scalePivotInverse) stored as a binary tree, meshes with interleaved vertices,
effects that name a texture of unit_models/shared/textures, and animation clips (Move, Idle, Attack...) whose channels
animate one element of a node's stack (e.g. «rotateX» of «German_DreadnoughtBattleship_Ship») with Bezier keys.
"""
import os
import re
import struct

import numpy as np

T_NODE = bytes.fromhex('16bedfa4e2060000')
T_XFORM = bytes.fromhex('65b2116d6896a91f')      # u8, ref -> root of the stack
T_PAIR = bytes.fromhex('d1467f535633be29')       # u32 0, ref a, ref b: a then b
T_ROTATE = bytes.fromhex('4404abf8b1306029')     # name, axis xyz, angle (degrees)
T_SCALE = bytes.fromhex('ba45070ec814a728')      # name, xyz
T_TRANSLATE = bytes.fromhex('96ec86d5480a1dbc')  # name, xyz (pivots and their inverses too)
T_GEOM = bytes.fromhex('2cffb3f1bcf518af')       # u32 n, n refs (submeshes), u32
T_VERTS = bytes.fromhex('e010d8e953d91d71')
T_MATBIND = bytes.fromhex('81f4fdfeba0819af')    # ref effect, u32
T_EFFECT = bytes.fromhex('3bd3e7dee579c59a')     # name, refs (-1 = none)
T_TEXNAME = bytes.fromhex('d87fe64d5ecf2bf5')    # 'ModelTextures', file name
T_TEXLINKS = {bytes.fromhex(h) for h in ('0fe386e1f67dd21e', '17b48228bbbe4009', '52ab5433164181b8')}  # effect -> ... -> T_TEXNAME
T_CLIP = bytes.fromhex('65bdb7c5bd48b229')       # name, f start, f end, u32 n, n refs (channels)
T_SKIN = bytes.fromhex('cb752f1b53883719')       # see Nst.geometry


class Nst:
    def __init__(self, path):
        self.path = path
        d = self.data = open(path, 'rb').read()
        if d[:4] != b'NEST':
            raise ValueError('%s: no es un archivo NEST' % path)
        n = struct.unpack_from('<I', d, 8)[0]
        self.types = [d[12 + i * 12:20 + i * 12] for i in range(n)]
        o = 12 + n * 12
        k = struct.unpack_from('<I', d, o)[0]
        self.roots = struct.unpack_from('<%dI' % (k + 1), d, o + 4)
        o += 4 + 4 * (k + 1)
        # objects: split at every type hash (8 random bytes: a false match inside data is practically impossible)
        pat = re.compile(b'|'.join(re.escape(h) for h in self.types))
        marks = [m.start() for m in pat.finditer(d, o)]
        if not marks or marks[0] != o:
            raise ValueError('%s: estructura NEST inesperada' % path)
        self.objs = [(d[a:a + 8], a + 8, b) for a, b in zip(marks, marks[1:] + [len(d)])]

    def type(self, i):
        return self.objs[i][0]

    def body(self, i):
        t, a, b = self.objs[i]
        return self.data[a:b]

    @staticmethod
    def _str(b, o):
        n = struct.unpack_from('<I', b, o)[0]
        return b[o + 4:o + 4 + n].decode('latin-1'), o + 4 + n

    def node(self, i):
        """{'name', 'bind', 'comps': [refs: transform, geometry, material...], 'children': [refs]}"""
        b = self.body(i)
        nm, o = self._str(b, 0)
        bind, o = self._str(b, o)
        nc = struct.unpack_from('<I', b, o)[0]
        comps = list(struct.unpack_from('<%dI' % nc, b, o + 4))
        o += 4 + 4 * nc
        nk = struct.unpack_from('<I', b, o)[0] if o + 4 <= len(b) else 0
        kids = list(struct.unpack_from('<%dI' % nk, b, o + 4)) if nk and o + 4 + 4 * nk <= len(b) else []
        return {'name': nm, 'bind': bind, 'comps': comps, 'children': kids}

    def stack(self, i):
        """Transform stack of a T_XFORM object -> [(kind, element name, values)] in order."""
        out = []

        def walk(j):
            t, b = self.type(j), self.body(j)
            if t == T_XFORM:
                walk(struct.unpack_from('<I', b, 1)[0])
            elif t == T_PAIR:
                _, a, c = struct.unpack_from('<3I', b)
                walk(a)
                walk(c)
            elif t in (T_ROTATE, T_SCALE, T_TRANSLATE):
                nm, o = self._str(b, 0)
                out.append(({T_ROTATE: 'rotate', T_SCALE: 'scale', T_TRANSLATE: 'translate'}[t], nm,
                            list(struct.unpack_from('<%df' % ((len(b) - o) // 4), b, o))))
        walk(i)
        return out

    def geometry(self, i):
        """T_GEOM -> [(vertices dict, tris)] (one per submesh). Skinned submeshes add V['skin'] =
        {'nodes': [joint node object numbers], 'ibm': [4x4 inverse bind], 'J': palette indices, 'W': weights}."""
        b = self.body(i)
        n = struct.unpack_from('<I', b)[0]     # u32 n, n submeshes, u32 m, m skins
        m = struct.unpack_from('<I', b, 4 + 4 * n)[0]
        out = []
        for s in struct.unpack_from('<%dI' % n, b, 4) + struct.unpack_from('<%dI' % m, b, 8 + 4 * n):
            skin = None
            if self.type(s) == T_SKIN:
                # skin: u32 1, u32 1, u32 nb, nb x joint, ref skinned mesh, ref bind-shape vertices
                # joint (T_JOINT): u32 0, node object number, ref bind; bind (T_BIND): u32 bone id, sid, 3x4 inverse bind (columns), 3x4
                # skinned mesh (T_SKINMESH): u32, ref vertices, ref index group, u32 nb, nb x bind
                sb = self.body(s)
                nb = struct.unpack_from('<I', sb, 8)[0]
                joints = struct.unpack_from('<%dI' % nb, sb, 12)
                mesh = struct.unpack_from('<I', sb, 12 + 4 * nb)[0]
                nodes, ibm = [], []
                for j in joints:
                    _, node, bref = struct.unpack_from('<3I', self.body(j))
                    bb = self.body(bref)
                    o = self._str(bb, 4)[1]
                    c = np.array(struct.unpack_from('<12f', bb, o), float).reshape(4, 3).T
                    nodes.append(node)
                    ibm.append(np.vstack([c, [0, 0, 0, 1]]))
                skin = {'nodes': nodes, 'ibm': ibm}
                s = mesh
                _, vref, gref = struct.unpack_from('<3I', self.body(s))
            else:
                vref, gref = struct.unpack_from('<2I', self.body(s))
            V = self.vertices(vref)
            if skin:
                for sem, _, comps, _, size, off in V['attrs']:
                    if sem in (5, 6) and size == 16:
                        a = V['raw'][:, off:off + 16].copy().view('<f4').reshape(-1, 4).astype(float)
                        skin['W' if sem == 5 else 'J'] = a
                skin['J'] = skin['J'].round().astype(int)
                V['skin'] = skin
            tris = []
            gb = self.body(gref)
            for p in struct.unpack_from('<%dI' % struct.unpack_from('<I', gb)[0], gb, 4):
                kind, iref = struct.unpack_from('<2I', self.body(p))
                ib = self.body(iref)
                cnt, size = struct.unpack_from('<2I', ib)
                idx = np.frombuffer(ib, '<u2' if size == 2 else '<u4', cnt, 8).astype(np.uint32)
                tris.append(idx[:cnt // 3 * 3].reshape(-1, 3))
            out.append((V, np.vstack(tris) if tris else np.zeros((0, 3), np.uint32)))
        return out

    def vertices(self, i):
        """T_VERTS -> {'pos', 'nor', 'uv', 'raw', 'attrs'}. Layout: u32 0, u32 stride, u32 nattr, nattr x (semantic, 0, comps, 0,
        bytes, offset), ..., u32 nverts, nverts x stride bytes (end of the object). Semantic 3 = position, 2 = normal,
        0 = texcoord."""
        b = self.body(i)
        _, stride, na = struct.unpack_from('<3I', b)
        attrs = [struct.unpack_from('<6I', b, 12 + 24 * k) for k in range(na)]
        nv = (len(b) - 4) // stride
        while nv > 0 and struct.unpack_from('<I', b, len(b) - 4 - nv * stride)[0] != nv:
            nv -= 1
        raw = np.frombuffer(b, np.uint8, nv * stride, len(b) - nv * stride).reshape(nv, stride)
        out = {'raw': raw, 'attrs': attrs, 'stride': stride, 'pos': None, 'nor': None, 'uv': None}
        for sem, _, comps, _, size, off in attrs:
            key = {3: 'pos', 2: 'nor', 0: 'uv'}.get(sem)
            if key and out[key] is None and size == 4 * comps:
                out[key] = raw[:, off:off + size].copy().view('<f4').reshape(nv, comps).astype(float)
        return out

    def texture(self, i, seen=None):
        """First texture file name reachable from a material binding / effect."""
        seen = seen if seen is not None else set()
        if i in seen or not 0 <= i < len(self.objs):
            return None
        seen.add(i)
        t, b = self.type(i), self.body(i)
        if t == T_TEXNAME:
            _, o = self._str(b, 0)
            return self._str(b, o)[0]
        if t == T_EFFECT:
            b = b[self._str(b, 0)[1]:]
        elif t != T_MATBIND and t not in T_TEXLINKS:
            return None
        for r in struct.unpack_from('<%dI' % (len(b) // 4), b):
            tx = self.texture(r, seen) if r != i else None
            if tx:
                return tx
        return None

    def clips(self):
        """[{'name', 'start', 'end', 'channels': [{'node', 'element', 'nkeys', 'dim', 'interp', 'values'}]}]"""
        out = []
        for i, (t, _, _) in enumerate(self.objs):
            if t != T_CLIP:
                continue
            bd = self.body(i)
            nm, o = self._str(bd, 0)
            st, en, n = struct.unpack_from('<2fI', bd, o)
            chans = []
            for c in struct.unpack_from('<%dI' % n, bd, o + 12):
                sref, tref = struct.unpack_from('<2I', self.body(c))
                node, o2 = self._str(self.body(tref), 0)
                # target: node name -> 'CSGData_LocalTransform' -> element name ('rotateX'...) -> component
                # (0 = all values, 1 = the angle of a rotate, 2 / 3 / 4 = X / Y / Z of a translate)
                try:
                    r2 = struct.unpack_from('<I', self.body(tref), o2)[0]
                    r3 = struct.unpack_from('<I', self.body(r2), self._str(self.body(r2), 0)[1])[0]
                    elem, o4 = self._str(self.body(r3), 0)
                    comp = struct.unpack_from('<I', self.body(struct.unpack_from('<I', self.body(r3), o4)[0]))[0]
                except struct.error:
                    elem, comp = None, None     # other targets (visibility...)
                sb = self.body(sref)
                # sampler: u32 nkeys, u32 dim, u32 interp (2 linear: time, values; 3 Bezier: + in and out tangents)
                nk, dim, interp = struct.unpack_from('<3I', sb)
                chans.append({'node': node, 'element': elem, 'component': comp, 'nkeys': nk, 'dim': dim, 'interp': interp,
                              'values': np.frombuffer(sb, '<f4', (len(sb) - 12) // 4, 12)})
            out.append({'name': nm, 'start': st, 'end': en, 'channels': chans})
        return out


def matrix(stack):
    """COLLADA-style stack -> 4x4 (column vectors, elements applied in the listed order)."""
    m = np.eye(4)
    for kind, _, v in stack:
        x = np.eye(4)
        if kind == 'translate':
            x[:3, 3] = v[:3]
        elif kind == 'scale':
            x[0, 0], x[1, 1], x[2, 2] = v[:3]
        else:
            ax = np.array(v[:3], float)
            ax /= max(np.linalg.norm(ax), 1e-12)
            a = np.radians(v[3])
            K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
            x[:3, :3] = np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K
        m = m @ x
    return m


def scene(path, textures_dir=None):
    """-> {'nodes': {name: world 4x4}, 'meshes': [mesh dicts as nif_mesh.import_meshes wants], 'clips': [...], 'nst': Nst}.
    Mesh dicts also carry 'texture' (file name); 'image' (PIL RGBA) is loaded when textures_dir is given."""
    f = Nst(path)
    meshes, worlds, stacks, parents = [], {}, {}, {}

    def walk(i, parent_world, chain):
        nd = f.node(i)
        local = np.eye(4)
        geo = mat = None
        for c in nd['comps']:
            t = f.type(c)
            if t == T_XFORM:
                st = f.stack(c)
                stacks[nd['name']] = st
                local = local @ matrix(st)
            elif t == T_GEOM:
                geo = c
            elif t == T_MATBIND:
                mat = c
        w = parent_world @ local
        worlds[nd['name']] = w
        parents[nd['name']] = chain[-1] if chain else None
        if geo is not None:
            tex = f.texture(mat) if mat is not None else None
            base = nd['name'].split('|instance_geometry')[0]
            for k, (V, tris) in enumerate(f.geometry(geo)):
                if V['pos'] is None or not len(tris):
                    continue
                sk = V.get('skin')
                meshes.append({'name': base + ('' if k == 0 else '_%d' % k), 'parent_names': chain[::-1], 'world': w,
                               'pos': V['pos'], 'nor': V['nor'], 'uv': V['uv'], 'tris': tris, 'texture': tex,
                               'skin': sk and {'joints': [f.node(j)['name'] for j in sk['nodes']], 'ibm': sk['ibm'],
                                               'J': sk['J'], 'W': sk['W']},
                               'image': None, '_verts': V})
        for c in nd['children']:
            if c < len(f.objs) and f.type(c) == T_NODE:
                walk(c, w, chain + [nd['name']])
    walk(0, np.eye(4), [])
    for m in meshes:    # rest pose of the joints (they are walked after or before the mesh: fill in at the end)
        if m['skin']:
            m['skin']['joint_world'] = [worlds[j] for j in m['skin']['joints']]
    if textures_dir:
        from PIL import Image
        cache = {}
        for m in meshes:
            t = m['texture']
            if t and t not in cache:
                p = next((os.path.join(textures_dir, t + e) for e in ('.dds', '.tga', '.png', '')
                          if os.path.isfile(os.path.join(textures_dir, t + e))), None)
                cache[t] = Image.open(p).convert('RGBA') if p else None
            m['image'] = cache.get(t)
    return {'nodes': worlds, 'stacks': stacks, 'parents': parents, 'meshes': meshes, 'clips': f.clips(), 'nst': f}


if __name__ == '__main__':
    import sys
    s = scene(sys.argv[1])
    for m in s['meshes']:
        P = (np.c_[m['pos'], np.ones(len(m['pos']))] @ m['world'].T)[:, :3]
        print('%-58s v=%5d t=%5d stride=%d tex=%-18s min=%s max=%s' % (m['name'][:58], len(m['pos']), len(m['tris']), m['_verts']['stride'],
              m['texture'], P.min(0).round(2), P.max(0).round(2)))
    for c in s['clips']:
        print('clip', c['name'], round(c['start'], 2), round(c['end'], 2), len(c['channels']),
              sorted({(str(x['element']), x['dim'], x['interp']) for x in c['channels']})[:6])
