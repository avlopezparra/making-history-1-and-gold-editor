"""Plan: subdivide the MH1 (Gold) land regions following the MH2 regions (see MH2_REGIONPACK.md).

For every MH1 land region R the pieces Râˆ©M (M = MH2 land region) bigger than a threshold become sub-regions; the
biggest piece stays as R (the "mother", keeps the MH1 name), the rest become new regions named like the MH2 region.
Leftover land (coast mismatch, slivers, small pieces) is absorbed by the nearest piece (iterative dilation), so
the pieces of R tile R exactly. Seas are left untouched.
"""
import json, os, pickle, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap
import shapely
from shapely.geometry import shape, Polygon, mapping
from shapely.ops import unary_union
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ORIG = os.path.join(ROOT, 'backup', 'mapa_original')
GEOJSON = os.path.join(ROOT, 'mh2', 'mh2_regions.geojson')
MIN_FRAC, MIN_AREA = 0.03, 0.01
SNAP, SIMPLIFY = 5e-4, 5e-4   # grados: las lineas de MH2 se ajustan a los vertices de la malla de MH1 y se aligeran
OPEN = 0.02                 # grados: se quitan los apendices mas finos que esto (rompen el contorno de la malla)      # una pieza cuenta si cubre >=3 % de R y >=0,01 grados2


VERTS = {}      # indice de region -> MultiPoint con TODOS los vertices de su malla


def pretty(name):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', name)


def mh1_land(orig=ORIG):
    from shapely.strtree import STRtree  # noqa
    m = mhmap.load_map(orig)
    out = {}
    for r in m['regions']:
        if r.u_type == 0:
            continue
        tris = [Polygon(t) for s in mhmap.region_shapes(m, r.index) for t in s.triangles()]
        out[r.index] = (r.name.decode('latin1') if isinstance(r.name, bytes) else r.name, unary_union([p for p in tris if p.area > 0]))
        VERTS[r.index] = shapely.MultiPoint(sorted({tuple(v[:2]) for sh in mhmap.region_shapes(m, r.index) for v in sh.vertices}))
    return out


def mh2_land():
    out = {}
    for x in json.load(open(GEOJSON, encoding='utf-8'))['features']:
        p = x['properties']
        if p['mh_type'] == 'land_region':
            out[p['name']] = (shape(x['geometry']).buffer(0), p)
    return out


def r32(g):
    """Coordenadas redondeadas a float32 (como las del mapa): evita astillas de 1e-10 junto a las aristas existentes."""
    import numpy as np
    return shapely.transform(g, lambda c: c.astype(np.float32).astype(np.float64))


def _polys(g):
    """Solo la parte poligonal (los cortes de shapely a veces dejan lineas sueltas en una GeometryCollection)."""
    ps = [x for x in getattr(g, 'geoms', [g]) if x.geom_type == 'Polygon' and not x.is_empty]
    for x in getattr(g, 'geoms', []):
        if x.geom_type == 'MultiPolygon':
            ps += list(x.geoms)
    return unary_union(ps) if ps else Polygon()


def cluster_snap(G, geoms, tol=1.5e-4, V=None):
    """Funde los vertices de las piezas que quedan a menos de 'tol' unos de otros o de un vertice de G (el editor funde los que
    estan a menos de 5e-5 y, si la linea de division tiene vertices tan juntos, queda en zigzag y la malla sale rota)."""
    import numpy as np
    from scipy.spatial import cKDTree
    def verts(g):
        out = []
        for p in getattr(g, 'geoms', [g]):
            if p.geom_type != 'Polygon':
                continue
            out += list(p.exterior.coords) + [c for r in p.interiors for c in r.coords]
        return out
    gv = {tuple(c) for c in verts(G)} | ({tuple(p.coords[0]) for p in V.geoms} if V is not None else set())
    allv = list(gv | {tuple(c) for g in geoms if g is not None for c in verts(g)})
    pts = np.array(allv)
    tree = cKDTree(pts)
    parent = list(range(len(allv)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in tree.query_pairs(tol):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    rep = {}
    for i, v in enumerate(allv):
        rep.setdefault(find(i), []).append(v)
    mapto = {}
    for members in rep.values():
        if len(members) == 1:
            continue
        keep = next((v for v in members if v in gv), members[0])
        for v in members:
            mapto[v] = keep
    if not mapto:
        return geoms
    def fix(g):
        if g is None:
            return None
        def poly(p):
            ext = [mapto.get(tuple(c), tuple(c)) for c in p.exterior.coords]
            ints = [[mapto.get(tuple(c), tuple(c)) for c in r.coords] for r in p.interiors]
            q = Polygon(ext, ints)
            return q
        ps = [poly(p) for p in getattr(g, 'geoms', [g]) if p.geom_type == 'Polygon']
        return _polys(shapely.make_valid(unary_union([q.buffer(0) for q in ps])))
    return [fix(g) for g in geoms]


def split_region(G, pieces, covtol=None, V=None):
    """pieces: [(key, geom)] (disjuntas, dentro de G). Reparte el resto de G entre ellas por dilatacion."""
    if V is not None:       # las lineas nuevas no pasan a menos de 1e-4 de un vertice de la malla (el editor funde a 5e-5 y deja huecos)
        pieces = [(k, _polys(shapely.make_valid(shapely.snap(g, V, VSNAP)))) for k, g in pieces]
    Gin = G.buffer(-ERODE, quad_segs=2)       # las lineas de division no corren pegadas al contorno de la madre (ruido de 1e-6 = bordes rotos)
    pieces = [(k, _polys(g.intersection(Gin))) for k, g in pieces]
    pieces = sorted([(k, g) for k, g in pieces if g.area > 1e-4], key=lambda kv: -kv[1].area)
    seen, clean = None, []
    for k, g in pieces:         # los poligonos de MH2 se solapan un poco: cada trozo se queda con lo que no tiene uno mayor
        g = g if seen is None else g.difference(seen)
        g = unary_union([x for x in getattr(g, 'geoms', [g]) if x.geom_type == 'Polygon' and x.area > 1e-3])
        if g.area > 0:
            clean.append((k, g))
            seen = g if seen is None else unary_union([seen, g])
    pieces = clean
    geoms = [g for _, g in pieces]
    rem = G.difference(unary_union(geoms))
    eps = 2e-4
    while rem.area > 1e-9 and eps < 0.6:
        for i in range(len(geoms)):
            if rem.is_empty:
                break
            grow = geoms[i].buffer(eps, quad_segs=2).intersection(rem)
            if grow.area > 1e-12:
                geoms[i] = _polys(unary_union([geoms[i], _polys(grow)]))
                rem = _polys(rem.difference(grow))
        eps *= 2
    if rem.area > 1e-12:
        geoms[0] = _polys(unary_union([geoms[0], rem]))      # lo lejano (islas sueltas) se queda con la mayor
    # topologia exacta: nodar todas las fronteras juntas y repartir las caras, para que las piezas vecinas compartan vertices
    from shapely.ops import polygonize
    faces = list(polygonize(unary_union([g.boundary for g in geoms] + [G.boundary])))
    bucket = [[] for _ in geoms]
    for f in faces:
        rp = f.representative_point()
        if not G.buffer(1e-9).contains(rp):
            continue
        j = next((i for i, g in enumerate(geoms) if g.buffer(1e-9).contains(rp)), None)
        if j is None:
            j = max(range(len(geoms)), key=lambda i: geoms[i].intersection(f).area)
        bucket[j].append(f)
    geoms = [_polys(unary_union([_polys(shapely.make_valid(r32(f))) for f in b])) if b else None for b in bucket]
    keep = [i for i, g in enumerate(geoms) if g is not None and g.area > 0]
    if len(keep) > 1:     # las lineas de division se aligeran todas a la vez, sin tocar el contorno de la region madre
        simp = shapely.coverage_simplify([geoms[i] for i in keep], covtol or COVTOL, simplify_boundary=False)
        for i, g in zip(keep, simp):
            geoms[i] = _polys(g)
    geoms = cluster_snap(G, geoms, V=V)
    return [(pieces[i][0], geoms[i]) for i in keep if geoms[i] is not None and geoms[i].area > 0]


ERODE = 4e-4
VSNAP = 1.2e-4
COVTOL = 3e-4    # grados: tolerancia al aligerar las lineas de division entre piezas
EXT = 0.01     # grados: el poligono que se entrega al editor se alarga hacia fuera de la region madre (el editor lo recorta con su malla)


def extend(G, g, d=EXT):
    """g + una franja de d grados por fuera de G: asi el borde de la pieza coincide EXACTAMENTE con la malla de la madre
    (el editor hace poligono ∩ malla) y no quedan astillas de 1e-10 junto a sus aristas."""
    out = _polys(g.buffer(d, quad_segs=2)).difference(G.buffer(1e-7))
    return _polys(unary_union([g, _polys(out)]))


LADDER = [(5e-4, 5e-4, 0.02, 3e-4), (1e-3, 1e-3, 0.04, 1e-3), (3e-3, 3e-3, 0.07, 3e-3), (1e-2, 1e-2, 0.12, 1e-2), (3e-2, 3e-2, 0.2, 3e-2)]     # (snap, simplify, open, coverage_simplify)


class Planner:
    def __init__(self, only=None):
        self.m1, self.m2 = mh1_land(), mh2_land()
        if only:
            self.m1 = {i: v for i, v in self.m1.items() if v[0] in only}
        self.keys = list(self.m2)
        self.tree = STRtree([self.m2[k][0] for k in self.keys])
        self.taken = {r.name for r in mhmap.load_map(ORIG)['regions']}
        self.simple = {}

    def plan(self, i, level=0, live=None):
        """Partes [(clave MH2, geometria)] de la region i de MH1 (la mayor primero) o [] si no se subdivide."""
        snap, simp, opn, cov = LADDER[level]
        rname, G = self.m1[i]
        V = VERTS.get(i)
        if live is not None:       # malla actual del proyecto (los vecinos ya subdivididos le han anadido vertices)
            G, V = live
        ps = []
        for j in self.tree.query(G):
            k = self.keys[j]
            sk = (k, simp)
            if sk not in self.simple:
                self.simple[sk] = self.m2[k][0].simplify(simp)
            g = G.intersection(shapely.make_valid(shapely.snap(self.simple[sk], G, snap)))
            if g.area >= max(MIN_FRAC * G.area, MIN_AREA):
                g = G.intersection(g.buffer(-opn, quad_segs=2).buffer(opn, quad_segs=2))
                g = unary_union([x for x in getattr(g, 'geoms', [g]) if x.geom_type == 'Polygon' and x.area > 1e-3])
            if g.area >= max(MIN_FRAC * G.area, MIN_AREA):
                ps.append((k, g))
        if len(ps) < 2:
            return []
        parts = split_region(G, ps, cov, V)
        return parts if len(parts) >= 2 else []

    def names(self, mother_name, parts):
        """[{key, name, geom, mother}] con nombres unicos (el primero conserva el de la madre)."""
        out = []
        for n, (k, g) in enumerate(parts):
            if n == 0:
                out.append({'key': k, 'name': mother_name, 'geom': g, 'mother': True}); continue
            nm = pretty(k)
            if nm in self.taken:
                nm = '%s (%s)' % (pretty(k), 'MH2' if nm == mother_name else mother_name)
            base, c = nm, 2
            while nm in self.taken:
                nm = '%s %d' % (base, c); c += 1
            out.append({'key': k, 'name': nm, 'geom': g, 'mother': False})
        return out

    def commit(self, pcs):
        for pc in pcs:
            self.taken.add(pc['name'])


def build(only=None):
    pl = Planner(only)
    out = []
    t0 = __import__('time').time()
    for i, (rname, G) in pl.m1.items():
        print(i, rname, round(__import__('time').time() - t0), flush=True)
        parts = pl.plan(i)
        if parts:
            pcs = pl.names(rname, parts)
            pl.commit(pcs)
            out.append({'mother': i, 'mother_name': rname, 'parts': pcs})
    return out, pl.m2, {}


if __name__ == '__main__':
    out, m2, a = build(sys.argv[2:] or None)
    n = sum(len(e['parts']) - 1 for e in out)
    print(len(out), 'regiones madre,', n, 'regiones nuevas')
    pickle.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else 'plan.pkl', 'wb'))

