"""Comprobaciones de integridad de un mapa modificado frente al original.
Uso: python -I check_map.py <original> <nuevo> [regiones...]"""
import sys, math, collections, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap

def bedges(m, r):
    c = collections.Counter()
    for s in mhmap.region_shapes(m, r):
        v = [x[:2] for x in s.vertices]; ix = s.indices
        for k in range(0, len(ix), 3):
            t = [v[i] for i in ix[k:k+3]]
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                if a != b: c[frozenset((a, b))] += 1
    return {e for e, n in c.items() if n == 1}

o, m = mhmap.load_map(sys.argv[1]), mhmap.load_map(sys.argv[2])
R = m['regions']
zero = sum(1 for b in m['borders'] for f, p in b.segments for i in range(1, len(p)) if p[i-1] == p[i])
print('pasos de longitud cero:', zero)
old_by_pair = {tuple(sorted(b.regions)): b.segments for b in o['borders']}
new_pairs_set = {tuple(sorted(b.regions)) for b in m['borders']}
changed = [i for i, b in enumerate(m['borders']) if old_by_pair.get(tuple(sorted(b.regions))) != b.segments]
print('bordes cambiados o nuevos:', len(changed), 'de', len(m['borders']),
      '| eliminados:', [tuple(o['regions'][x].name for x in p) for p in old_by_pair if p not in new_pairs_set])
bad = []
cache = {}
for i in changed:
    b = m['borders'][i]; r, s = b.regions
    if r == s: continue
    er = cache.setdefault(r, bedges(m, r)); es = cache.setdefault(s, bedges(m, s))
    shared = er & es
    bed = {frozenset((p[k], p[k+1])) for f, p in b.segments for k in range(len(p)-1)}
    closing = {frozenset((p[-1], p[0])) for f, p in b.segments if len(p) > 2}
    missing = shared - bed - closing
    extra = bed - shared
    if missing or extra: bad.append((R[r].name, R[s].name, len(shared), len(bed), len(missing), len(extra)))
print('bordes que NO son exactamente las aristas compartidas:', len(bad), bad[:8])
names = sys.argv[3:]
by = {g.name: g.index for g in R}
for n in names:
    r = by[n]
    def odd(mm):
        ends = collections.Counter()
        for nb, bi in mm['border_table'][r].links:
            for f, p in mm['borders'][bi].segments:
                if len(p) > 2 and frozenset((p[-1], p[0])) in bedges(mm, r): continue
                ends[p[0]] += 1; ends[p[-1]] += 1
        return sum(1 for v in ends.values() if v % 2)
    verts = {v[:2] for s in mhmap.region_shapes(m, r) for v in s.vertices}
    pts = [q for nb, bi in m['border_table'][r].links for f, p in m['borders'][bi].segments for q in p]
    print('  %-17s extremos sueltos original %3s nuevo %3d | puntos de borde que son vertices %.3f' % (
        n, odd(o) if r < len(o['regions']) and o['regions'][r].name == n else '-', odd(m), sum(q in verts for q in pts) / len(pts)))

# contornos validos (sin grietas ni autointersecciones) en las regiones de los bordes cambiados
try:
    import outlines
    from shapely.geometry import shape
    from shapely.validation import explain_validity
    regs = sorted({x for i in changed for x in m['borders'][i].regions})
    inval = []
    for r in regs:
        g = shape({'type': 'MultiPolygon', 'coordinates': outlines.region_polygons(m, r)[0]})
        if not g.is_valid:
            inval.append((R[r].name, explain_validity(g)))
    print('contornos invalidos en regiones tocadas:', len(inval), inval[:5])
except ImportError:
    pass
