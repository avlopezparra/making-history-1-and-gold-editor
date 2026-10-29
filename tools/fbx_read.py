"""Lector mínimo de FBX binario (Kaydara FBX Binary): árbol de nodos con sus propiedades.

    n = fbx_read.load(path); n.find('Objects').children ...
"""
import struct
import zlib

import numpy as np


class Node:
    def __init__(self, name, props, children):
        self.name, self.props, self.children = name, props, children

    def find(self, name):
        return next((c for c in self.children if c.name == name), None)

    def all(self, name):
        return [c for c in self.children if c.name == name]

    def __repr__(self):
        return 'Node(%s, %d props, %d children)' % (self.name, len(self.props), len(self.children))


_ARR = {'f': ('<f4', 4), 'd': ('<f8', 8), 'l': ('<i8', 8), 'i': ('<i4', 4), 'b': ('<u1', 1)}


def _prop(b, o):
    t = chr(b[o])
    o += 1
    if t == 'Y':
        return struct.unpack_from('<h', b, o)[0], o + 2
    if t == 'C':
        return bool(b[o]), o + 1
    if t == 'I':
        return struct.unpack_from('<i', b, o)[0], o + 4
    if t == 'F':
        return struct.unpack_from('<f', b, o)[0], o + 4
    if t == 'D':
        return struct.unpack_from('<d', b, o)[0], o + 8
    if t == 'L':
        return struct.unpack_from('<q', b, o)[0], o + 8
    if t in _ARR:
        n, enc, ln = struct.unpack_from('<III', b, o)
        o += 12
        raw = b[o:o + ln]
        if enc == 1:
            raw = zlib.decompress(raw)
        dt, _ = _ARR[t]
        return np.frombuffer(raw, dt, n).copy(), o + ln
    if t in 'SR':
        ln = struct.unpack_from('<I', b, o)[0]
        o += 4
        v = b[o:o + ln]
        return (v.decode('utf-8', 'replace') if t == 'S' else v), o + ln
    raise ValueError('tipo de propiedad FBX desconocido %r en %d' % (t, o - 1))


def _node(b, o, wide):
    if wide:
        end, nprops, plen = struct.unpack_from('<QQQ', b, o)
        o += 24
    else:
        end, nprops, plen = struct.unpack_from('<III', b, o)
        o += 12
    nl = b[o]
    name = b[o + 1:o + 1 + nl].decode('ascii', 'replace')
    o += 1 + nl
    if end == 0:
        return None, o
    props = []
    for _ in range(nprops):
        v, o = _prop(b, o)
        props.append(v)
    children = []
    null = 25 if wide else 13
    while o < end - null + 1 and o < end:
        if end - o == null:
            break
        c, o = _node(b, o, wide)
        if c is None:
            break
        children.append(c)
    return Node(name, props, children), end


def load(path):
    b = open(path, 'rb').read()
    if not b.startswith(b'Kaydara FBX Binary'):
        raise ValueError('solo FBX binario')
    ver = struct.unpack_from('<I', b, 23)[0]
    wide = ver >= 7500
    o = 27
    top = []
    while o < len(b):
        c, o2 = _node(b, o, wide)
        if c is None:
            break
        top.append(c)
        o = o2
    root = Node('root', [], top)
    root.version = ver
    return root
