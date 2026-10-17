"""Lector y escritor de los binarios del mapa de Making History: The Calm and The Storm.

    regions.bin  - regiones: nombre, centro, vecinos, contorno
    borders.brd  - polilineas de frontera + indice region -> (vecino, borde)
    regions.nts  - malla de triangulos que se dibuja + indice region -> shapes

Todo es little-endian. Los campos cuyo significado no se conoce se conservan tal cual
(nombres "u*") para que leer y volver a escribir produzca exactamente los mismos bytes.
Las coordenadas son float32 en grados: x = longitud, y = latitud.

Uso como libreria:
    m = load_map(carpeta_xml)          # dict con 'regions', 'borders', 'nts'
    save_map(m, carpeta_salida)
"""
import os
import struct
from dataclasses import dataclass, field


class Reader:
    def __init__(self, data):
        self.d = data
        self.o = 0

    def unpack(self, fmt):
        v = struct.unpack_from('<' + fmt, self.d, self.o)
        self.o += struct.calcsize('<' + fmt)
        return v

    def u32(self):
        return self.unpack('I')[0]

    def u8(self):
        return self.unpack('B')[0]

    def floats(self, n):
        return list(self.unpack('%df' % n)) if n else []

    def u32s(self, n):
        return list(self.unpack('%dI' % n)) if n else []

    def raw(self, n):
        b = self.d[self.o:self.o + n]
        self.o += n
        return b

    def done(self):
        if self.o != len(self.d):
            raise ValueError('quedan %d bytes sin leer (offset %d de %d)' % (len(self.d) - self.o, self.o, len(self.d)))


class Writer:
    def __init__(self):
        self.parts = []

    def pack(self, fmt, *v):
        self.parts.append(struct.pack('<' + fmt, *v))

    def u32(self, v):
        self.pack('I', v)

    def u8(self, v):
        self.pack('B', v)

    def floats(self, vals):
        if vals:
            self.pack('%df' % len(vals), *vals)

    def u32s(self, vals):
        if vals:
            self.pack('%dI' % len(vals), *vals)

    def raw(self, b):
        self.parts.append(b)

    def bytes(self):
        return b''.join(self.parts)


def pairs(flat):
    return list(zip(flat[0::2], flat[1::2]))


def flatten(pts):
    return [c for p in pts for c in p]


# ---------------------------------------------------------------- regions.bin

@dataclass
class Region:
    index: int
    name_raw: bytes
    u_type: int          # 0..4, significado sin confirmar
    u_a: int             # a == b en todo el mapa original
    u_b: int
    u_flag: int          # siempre 0
    cx: float
    cy: float
    u_z: int             # siempre 0
    neighbors: list      # indices de region
    points: list         # [(x, y), ...]

    @property
    def name(self):
        return self.name_raw.decode('latin1')


def read_regions_bin(data):
    r = Reader(data)
    regions = []
    for i in range(r.u32()):
        u_type, u_a, u_b = r.unpack('3I')
        name_raw = r.raw(r.u32())
        u_flag, cx, cy, u_z = r.unpack('I2fI')
        neighbors = r.u32s(r.u32())
        points = pairs(r.floats(2 * r.u32()))
        regions.append(Region(i, name_raw, u_type, u_a, u_b, u_flag, cx, cy, u_z, neighbors, points))
    r.done()
    return regions


def write_regions_bin(regions):
    w = Writer()
    w.u32(len(regions))
    for g in regions:
        w.pack('3I', g.u_type, g.u_a, g.u_b)
        w.u32(len(g.name_raw))
        w.raw(g.name_raw)
        w.pack('I2fI', g.u_flag, g.cx, g.cy, g.u_z)
        w.u32(len(g.neighbors))
        w.u32s(g.neighbors)
        w.u32(len(g.points))
        w.floats(flatten(g.points))
    return w.bytes()


# ---------------------------------------------------------------- borders.brd

@dataclass
class Border:
    index: int
    segments: list       # [(flag, [(x, y), ...]), ...]
    anchors: list        # [(x, y), ...] (siempre 1 punto en el original)
    regions: tuple = ()  # (regionA, regionB), deducido de la tabla final


@dataclass
class BorderIndexRow:
    region: int
    u_x: int
    links: list          # [(vecino, indice_borde), ...]


def read_borders_brd(data):
    r = Reader(data)
    borders = []
    for i in range(r.u32()):
        segments = []
        for _ in range(r.u32()):
            flag = r.u8()
            segments.append((flag, pairs(r.floats(2 * r.u32()))))
        anchors = pairs(r.floats(2 * r.u32()))
        borders.append(Border(i, segments, anchors))
    table = []
    for _ in range(r.u32()):
        region, u_x, k = r.unpack('3I')
        table.append(BorderIndexRow(region, u_x, pairs(r.u32s(2 * k))))
    r.done()
    for row in table:
        for nb, bi in row.links:
            borders[bi].regions = tuple(sorted((row.region, nb)))
    return borders, table


def write_borders_brd(borders, table):
    w = Writer()
    w.u32(len(borders))
    for b in borders:
        w.u32(len(b.segments))
        for flag, pts in b.segments:
            w.u8(flag)
            w.u32(len(pts))
            w.floats(flatten(pts))
        w.u32(len(b.anchors))
        w.floats(flatten(b.anchors))
    w.u32(len(table))
    for row in table:
        w.pack('3I', row.region, row.u_x, len(row.links))
        w.u32s(flatten(row.links))
    return w.bytes()


# ---------------------------------------------------------------- regions.nts

NTS_MAGIC = 0xD00D1337


@dataclass
class Shape:
    index: int
    u_zero: int
    vertices: list       # [(x, y, z, nx, ny, nz), ...]
    indices: list        # lista de triangulos (3 por triangulo)

    def triangles(self):
        v = self.vertices
        ix = self.indices
        return [(v[ix[k]][:2], v[ix[k + 1]][:2], v[ix[k + 2]][:2]) for k in range(0, len(ix), 3)]


@dataclass
class ShapeIndexRow:
    region: int
    u_last: int          # igual a 'last' en el original
    first: int
    last: int


def read_regions_nts(data):
    r = Reader(data)
    shapes = []
    for i in range(r.u32()):
        magic, u_zero, nv = r.unpack('3I')
        if magic != NTS_MAGIC:
            raise ValueError('shape %d: magic %#x' % (i, magic))
        flat = r.floats(6 * nv)
        vertices = [tuple(flat[k:k + 6]) for k in range(0, len(flat), 6)]
        indices = r.u32s(r.u32())
        shapes.append(Shape(i, u_zero, vertices, indices))
    table = [ShapeIndexRow(*r.unpack('4I')) for _ in range(r.u32())]
    r.done()
    return shapes, table


def write_regions_nts(shapes, table):
    w = Writer()
    w.u32(len(shapes))
    for s in shapes:
        w.pack('3I', NTS_MAGIC, s.u_zero, len(s.vertices))
        w.floats([c for v in s.vertices for c in v])
        w.u32(len(s.indices))
        w.u32s(s.indices)
    w.u32(len(table))
    for t in table:
        w.pack('4I', t.region, t.u_last, t.first, t.last)
    return w.bytes()


# ---------------------------------------------------------------- conjunto

FILES = ('regions.bin', 'borders.brd', 'regions.nts')


def load_map(folder):
    rd = lambda n: open(os.path.join(folder, n), 'rb').read()
    borders, border_table = read_borders_brd(rd('borders.brd'))
    shapes, shape_table = read_regions_nts(rd('regions.nts'))
    return {
        'regions': read_regions_bin(rd('regions.bin')),
        'borders': borders, 'border_table': border_table,
        'shapes': shapes, 'shape_table': shape_table,
    }


def encode_map(m):
    return {
        'regions.bin': write_regions_bin(m['regions']),
        'borders.brd': write_borders_brd(m['borders'], m['border_table']),
        'regions.nts': write_regions_nts(m['shapes'], m['shape_table']),
    }


def save_map(m, folder):
    os.makedirs(folder, exist_ok=True)
    for name, data in encode_map(m).items():
        with open(os.path.join(folder, name), 'wb') as f:
            f.write(data)


def region_shapes(m, region_index):
    """Shapes de la malla que pertenecen a una region."""
    t = m['shape_table'][region_index]
    return m['shapes'][t.first:t.last + 1]
