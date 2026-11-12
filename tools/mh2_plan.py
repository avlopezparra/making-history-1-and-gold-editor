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
SNAP, SIMPLIFY = 5e-4, 5e-4   # degrees: MH2 lines are snapped to the MH1 mesh vertices and lightened
OPEN = 0.02                 # degrees: appendages thinner than this are removed (they break the mesh outline)      # a piece counts if it covers >=3 % of R and >=0.01 degrees2


VERTS = {}      # region index -> MultiPoint with ALL the vertices of its mesh


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
    """Coordinates rounded to float32 (like the map's): avoids 1e-10 slivers next to existing edges."""
    import numpy as np
    return shapely.transform(g, lambda c: c.astype(np.float32).astype(np.float64))


def _polys(g):
    """Only the polygonal part (shapely cuts sometimes leave loose lines in a GeometryCollection)."""
    ps = [x for x in getattr(g, 'geoms', [g]) if x.geom_type == 'Polygon' and not x.is_empty]
    for x in getattr(g, 'geoms', []):
        if x.geom_type == 'MultiPolygon':
            ps += list(x.geoms)
    return unary_union(ps) if ps else Polygon()


def cluster_snap(G, geoms, tol=1.5e-4, V=None):
    """Merges the vertices of the pieces that are less than 'tol' from each other or from a vertex of G (the editor merges those
    less than 5e-5 apart and, if the split line has vertices that close, it zigzags and the mesh comes out broken)."""
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
    """pieces: [(key, geom)] (disjoint, inside G). Distributes the rest of G among them by dilation."""
    if V is not None:       # new lines do not pass within 1e-4 of a mesh vertex (the editor merges at 5e-5 and leaves gaps)
        pieces = [(k, _polys(shapely.make_valid(shapely.snap(g, V, VSNAP)))) for k, g in pieces]
    Gin = G.buffer(-ERODE, quad_segs=2)       # split lines do not run glued to the mother's outline (1e-6 noise = broken edges)
    pieces = [(k, _polys(g.intersection(Gin))) for k, g in pieces]
    pieces = sorted([(k, g) for k, g in pieces if g.area > 1e-4], key=lambda kv: -kv[1].area)
    seen, clean = None, []
    for k, g in pieces:         # MH2 polygons overlap a bit: each piece keeps what no larger one has
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
        geoms[0] = _polys(unary_union([geoms[0], rem]))      # distant parts (loose islands) go to the largest
    # exact topology: node all borders together and distribute the faces, so neighboring pieces share vertices
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
    if len(keep) > 1:     # split lines are all lightened at once, without touching the mother region's outline
        simp = shapely.coverage_simplify([geoms[i] for i in keep], covtol or COVTOL, simplify_boundary=False)
        for i, g in zip(keep, simp):
            geoms[i] = _polys(g)
    geoms = cluster_snap(G, geoms, V=V)
    return [(pieces[i][0], geoms[i]) for i in keep if geoms[i] is not None and geoms[i].area > 0]


ERODE = 4e-4
VSNAP = 1.2e-4
COVTOL = 3e-4    # degrees: tolerance when lightening the split lines between pieces
EXT = 0.01     # degrees: the polygon handed to the editor is extended outside the mother region (the editor clips it with its mesh)


def extend(G, g, d=EXT):
    """g + a strip of d degrees outside G: so the piece edge matches the mother's mesh EXACTLY
    (the editor does polygon ∩ mesh) and no 1e-10 slivers remain next to its edges."""
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
        """Parts [(MH2 key, geometry)] of MH1 region i (largest first) or [] if it is not subdivided."""
        snap, simp, opn, cov = LADDER[level]
        rname, G = self.m1[i]
        V = VERTS.get(i)
        if live is not None:       # project's current mesh (already subdivided neighbors have added vertices to it)
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
        """[{key, name, geom, mother}] with unique names (the first keeps the mother's)."""
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

