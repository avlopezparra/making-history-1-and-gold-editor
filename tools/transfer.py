"""Traspaso de trozos de mapa entre regiones respetando las reglas del formato.

apply_transfers(m, transfers, islands, P) recorta las mallas, unifica vertices (float32, sin uniones en T),
regenera los bordes afectados desde las aristas compartidas (con sus banderas) y crea las vecindades nuevas.
Devuelve (erase, paint, new_pairs): lineas a borrar/pintar en la textura como (tipo, LineString) con tipo
'land' (tierra-tierra) o 'sea' (mar-mar); las costas no se pintan.

  transfers: lista de (poligono, region_origen, region_destino)
  islands:   lista de (poligono, region_destino, region_mar) para colocar el ancla de bordes nuevos
  P:         funcion region -> poligono de su malla (con cache)
"""
import math
import os
import struct
import sys
from collections import Counter, defaultdict

from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap  # noqa: E402
from move_border import triangulate, signed_area, MeshBuilder, EPS  # noqa: E402

SEA = 0
TOUCH = 1e-6            # tolerancia para decidir si dos poligonos se tocan
ZONE = 1e-3             # margen alrededor de las piezas movidas
MIN_PIECE = 1e-7        # grados2: piezas menores se ignoran
SNAP = 5e-5             # grados (~5 m): vertices nuevos a menos de esto se funden con uno existente
ON_EDGE = 2e-5          # grados: un vertice a menos de esto de una arista se considera sobre ella



def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def lines(g):
    out = []
    for x in getattr(g, 'geoms', [g]):
        if x.geom_type == 'LineString' and x.length > 1e-9:
            out.append(x)
        elif x.geom_type in ('MultiLineString', 'GeometryCollection'):
            out += lines(x)
    return out


class Snapper:
    """Redondea a float32 y funde puntos nuevos con vertices existentes cercanos (rejilla de SNAP)."""

    def __init__(self):
        self.grid = defaultdict(list)

    def _cell(self, p):
        return int(math.floor(p[0] / SNAP)), int(math.floor(p[1] / SNAP))

    def seed(self, p):
        cx, cy = self._cell(p)
        if p not in self.grid[(cx, cy)]:
            self.grid[(cx, cy)].append(p)

    def __call__(self, p):
        p = (f32(p[0]), f32(p[1]))
        cx, cy = self._cell(p)
        best, bd = None, SNAP
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for q in self.grid.get((cx + dx, cy + dy), ()):
                    d = math.dist(p, q)
                    if d <= bd:
                        best, bd = q, d
        if best is not None:
            return best
        self.grid[(cx, cy)].append(p)
        return p


def tri_edges(t):
    return ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))


def boundary_edges(tris):
    c = Counter()
    for t in tris:
        for a, b in tri_edges(t):
            c[frozenset((a, b))] += 1
    return {e for e, n in c.items() if n == 1}


def split_tjunctions(tris, pool, zone_box, zone_geom=None):
    """Parte los triangulos cuyas aristas de contorno tienen vertices ajenos encima (uniones en T)."""
    pts = list(pool)
    tree = STRtree([Point(p) for p in pts])
    changed = True
    rounds = 0
    while changed and rounds < 6:
        changed = False
        rounds += 1
        bnd = boundary_edges(tris)
        out = []
        for t in tris:
            done = False
            for a, b in tri_edges(t):
                if frozenset((a, b)) not in bnd:
                    continue
                ex0, ex1 = min(a[0], b[0]), max(a[0], b[0])
                ey0, ey1 = min(a[1], b[1]), max(a[1], b[1])
                if ex1 < zone_box[0] or ex0 > zone_box[2] or ey1 < zone_box[1] or ey0 > zone_box[3]:
                    continue
                seg = LineString([a, b])
                if zone_geom is not None and not zone_geom.intersects(seg):
                    continue
                L = seg.length
                on = []
                for i in tree.query(seg.buffer(ON_EDGE)):
                    v = pts[i]
                    if v == a or v == b:
                        continue
                    if seg.distance(tree.geometries[i]) <= ON_EDGE:
                        s = seg.project(tree.geometries[i])
                        if 1e-9 < s < L - 1e-9:
                            on.append((s, v))
                if not on:
                    continue
                c = next(x for x in t if x != a and x != b)
                chain = [a] + [v for _, v in sorted(on)] + [b]
                for p, q in zip(chain, chain[1:]):
                    if p != q:
                        out.append((p, q, c))
                done = True
                changed = True
                break
            if not done:
                out.append(t)
        tris = out
    return tris


def chains(edges):
    """Descompone un conjunto de aristas en polilineas (los anillos cerrados sin repetir el inicio)."""
    adj = defaultdict(list)
    for e in edges:
        a, b = tuple(e)
        adj[a].append(b)
        adj[b].append(a)
    used = set()
    out = []

    def walk(start, nxt):
        path = [start, nxt]
        used.add(frozenset((start, nxt)))
        prev, cur = start, nxt
        while len(adj[cur]) == 2:
            n = adj[cur][0] if adj[cur][1] == prev or frozenset((cur, adj[cur][1])) in used else adj[cur][1]
            e = frozenset((cur, n))
            if e in used:
                break
            used.add(e)
            path.append(n)
            prev, cur = cur, n
        return path

    for v in adj:
        if len(adj[v]) != 2:
            for n in adj[v]:
                if frozenset((v, n)) not in used:
                    out.append(walk(v, n))
    for v in adj:
        for n in adj[v]:
            if frozenset((v, n)) not in used:
                p = walk(v, n)
                if p[-1] == p[0]:
                    p = p[:-1]
                out.append(p)
    return out


def apply_transfers(m, transfers, islands, P, cache=None):
    R = m["regions"]
    # ------------------------------------------------------------ mallas: recorte
    all_tris = [t for s in m['shapes'] for t in s.triangles()]
    # el juego solo dibuja (y deja elegir) triangulos en sentido antihorario (World: 100 %); en un mapa vacío no hay de donde
    # deducirlo y antes salía horario: regiones invisibles e imposibles de seleccionar (Probando3, 2026-10-22)
    winding = not all_tris or sum(signed_area(t) > 0 for t in all_tris) * 2 >= len(all_tris)
    by_src = defaultdict(list)
    for p, s, d in transfers:
        by_src[s].append((p, d))
    work = {}          # indice de shape -> triangulos (tuplas de puntos)
    dest_geom = {}     # region destino -> (malla preparada, malla) tal como estaba antes del traspaso
    incoming = defaultdict(list)
    for src, items in by_src.items():
        if src is None:   # area que sale de la nada (rellenar un hueco o lago)
            for p, d in items:
                if d is not None:
                    incoming[d].extend(tuple(map(tuple, q)) for q in triangulate(p))
            continue
        tree = STRtree([p for p, _ in items])
        for sh in mhmap.region_shapes(m, src):
            res = []
            for t in sh.triangles():
                tp = Polygon(t)
                if tp.area < EPS:
                    # triángulo diminuto: antes se quedaba siempre en su región (un resto de Podelia de 1e-8 grados² dentro de
                    # Polissia no había forma de quitarlo); si cae dentro de lo que se traspasa, se va con ello
                    c = Point(sum(p_[0] for p_ in t) / 3, sum(p_[1] for p_ in t) / 3)
                    hit = next((items[i] for i in tree.query(c.buffer(1e-7)) if items[i][0].buffer(1e-7).contains(c)), None)
                    if hit is None:
                        res.append(tuple(t))
                    elif hit[1] is not None:
                        d = hit[1]
                        if d not in dest_geom:
                            from shapely.prepared import prep
                            dest_geom[d] = (prep(P(d)), P(d))
                        if not dest_geom[d][0].contains(c):      # si el destino ya cubre ese punto, basta con quitarlo del origen
                            incoming[d].append(tuple(map(tuple, t)))
                    continue
                hits = [items[i] for i in tree.query(tp) if items[i][0].intersects(tp)]
                rem = tp
                for p, d in hits:
                    inter = rem.intersection(p)
                    if inter.area > EPS:
                        if d is not None:   # d None: el area se elimina (queda un hueco)
                            # lo que la región destino ya tiene (mallas que se solapan, p. ej. las «formas raras» entre
                            # Podelia y Polissia) no se le vuelve a añadir: duplicaría triángulos y su malla quedaría rota
                            if d not in dest_geom:
                                from shapely.prepared import prep
                                dest_geom[d] = (prep(P(d)), P(d))
                            if dest_geom[d][0].intersects(inter):
                                inter = inter.difference(dest_geom[d][1])
                            if inter.area > EPS:
                                incoming[d].extend(tuple(map(tuple, q)) for q in triangulate(inter))
                        rem = rem.difference(p)
                if rem.equals(tp):
                    res.append(tuple(t))
                elif rem.area > EPS:
                    res.extend(tuple(map(tuple, q)) for q in triangulate(rem))
            work[sh.index] = res
    for d, tris in incoming.items():
        sh = mhmap.region_shapes(m, d)[0]
        work.setdefault(sh.index, [tuple(t) for t in sh.triangles()]).extend(tris)
    affected = (set(by_src) | set(incoming)) - {None}

    # ------------------------------------------------------------ mallas: vertices exactos y sin uniones en T
    zone = unary_union([p for p, _, _ in transfers]).buffer(ZONE)
    zb = zone.bounds
    group = set(affected)
    for r in affected:
        group |= set(R[r].neighbors)
    # regiones que tocan la zona aunque no fueran vecinas (contactos nuevos, p. ej. al rellenar un lago)
    for i, row in enumerate(m['shape_table']):
        if i in group:
            continue
        for sh in m['shapes'][row.first:row.last + 1]:
            xs = [v[0] for v in sh.vertices]
            ys = [v[1] for v in sh.vertices]
            if xs and min(xs) <= zb[2] and max(xs) >= zb[0] and min(ys) <= zb[3] and max(ys) >= zb[1]:
                if P(i).intersects(zone):
                    group.add(i)
                break
    group.discard(None)
    snapper = Snapper()
    for r in group:
        for sh in mhmap.region_shapes(m, r):
            for v in sh.vertices:
                if zb[0] - 1 <= v[0] <= zb[2] + 1 and zb[1] - 1 <= v[1] <= zb[3] + 1:
                    snapper.seed(v[:2])
    for si in list(work):
        fixed = []
        for t in work[si]:
            q = tuple(snapper(p) for p in t)
            if len(set(q)) == 3 and abs(signed_area(q)) > 1e-14:
                fixed.append(q)
        work[si] = fixed
    # vertices de contorno de todas las regiones del grupo, para detectar uniones en T
    def region_tris(r):
        return [t for sh in mhmap.region_shapes(m, r)
                for t in (work[sh.index] if sh.index in work else [tuple(x) for x in sh.triangles()])]
    pool = set()
    for r in group:
        for e in boundary_edges(region_tris(r)):
            for v in e:
                if zb[0] - 0.01 <= v[0] <= zb[2] + 0.01 and zb[1] - 0.01 <= v[1] <= zb[3] + 0.01:
                    pool.add(v)
    zone_box = (zb[0] - 0.01, zb[1] - 0.01, zb[2] + 0.01, zb[3] + 0.01)
    from shapely.prepared import prep
    zone_near = prep(zone.buffer(0.01))   # solo aristas que tocan la zona realmente modificada
    n_split = 0
    for r in sorted(group):
        for sh in mhmap.region_shapes(m, r):
            tris = work[sh.index] if sh.index in work else [tuple(x) for x in sh.triangles()]
            new = split_tjunctions(tris, pool, zone_box, zone_near)
            if new != tris:
                n_split += len(new) - len(tris)
                work[sh.index] = new
                affected.add(r)
    for si, tris in work.items():
        sh = m['shapes'][si]
        mb = MeshBuilder(sh, winding)
        for t in tris:
            mb.add(list(t))
        sh.indices = mb.indices
    print('shapes reconstruidos: %d | triangulos anadidos al partir uniones en T: %d | regiones afectadas: %s' % (
        len(work), n_split, sorted(R[r].name for r in affected)))

    # ------------------------------------------------------------ bordes = aristas compartidas
    bedges = {}
    for r in group | affected:
        bedges[r] = boundary_edges([tuple(map(tuple, t)) for sh in mhmap.region_shapes(m, r) for t in
                                    ([(s[0], s[1], s[2]) for s in sh.triangles()])])
    # se usan los valores tal como quedaran en float32
    def f32e(e):
        return frozenset((f32(p[0]), f32(p[1])) for p in e)
    bedges = {r: {f32e(e) for e in es} for r, es in bedges.items()}
    border_of = {tuple(sorted(b.regions)): b for b in m['borders']}
    pairs = set()
    for r in affected:
        for s in group | affected:
            if s != r:
                pairs.add(tuple(sorted((r, s))))
    erase, paint, new_pairs, gone = [], [], [], []
    for pr in sorted(pairs):
        r, s = pr
        if r not in bedges or s not in bedges:
            continue
        shared = bedges[r] & bedges[s]
        old = border_of.get(pr)
        if not shared:
            if old is not None:
                gone.append(pr)
            continue
        land_land = R[r].u_type != SEA and R[s].u_type != SEA
        sea_sea = R[r].u_type == SEA and R[s].u_type == SEA
        kind = 'land' if land_land else ('sea' if sea_sea else None)  # las costas no se pintan
        old_flag = {}
        for f, pts in (old.segments if old else []):
            for p, q in zip(pts, pts[1:]):
                old_flag[frozenset((p, q))] = f
            if len(pts) > 2:
                old_flag.setdefault(frozenset((pts[-1], pts[0])), f)
        default = 1 if kind is None else 0
        segs = []
        for path in chains(shared):
            cur, flag = [path[0]], None
            closed = len(path) > 2 and frozenset((path[-1], path[0])) in shared
            for p, q in zip(path, path[1:]):
                fl = old_flag.get(frozenset((p, q)), default)
                if flag is not None and fl != flag:
                    segs.append((flag, cur))
                    cur = [p]
                flag = fl
                cur.append(q)
            segs.append((flag if flag is not None else default, cur))
            _ = closed
        segs.sort(key=lambda x: x[0])
        if old is not None:
            if [(f, p) for f, p in old.segments] != segs:
                if kind:
                    o = unary_union([LineString(p) for f, p in old.segments if len(p) > 1])
                    n = unary_union([LineString(p) for f, p in segs if len(p) > 1])
                    er = o.difference(n.buffer(2e-4))
                    erase += [(kind, x) for x in lines(er)]
                    paint += [(kind, x) for x in lines(n.difference(o.buffer(2e-4)))]
                    if not er.is_empty:
                        paint += [(kind, x) for x in lines(n.intersection(er.buffer(0.15)))]
                old.segments = segs
        else:
            pts_all = [q for _, p in segs for q in p]
            if land_land:
                anchor = pts_all[len(pts_all) // 2]
            else:
                land, sea = (r, s) if R[s].u_type == SEA else (s, r)
                isl = [p for p, d, sx in islands if d == land and sx == sea]
                c = unary_union(isl).centroid if isl else LineString(pts_all).centroid
                sc = P(sea).representative_point()
                dx, dy = sc.x - c.x, sc.y - c.y
                k = 0.8 / max((dx * dx + dy * dy) ** 0.5, 1e-9)
                anchor = (c.x + dx * k, c.y + dy * k)
            b = mhmap.Border(len(m['borders']), segs, [(f32(anchor[0]), f32(anchor[1]))], pr)
            m['borders'].append(b)
            border_of[pr] = b
            R[r].neighbors.append(s)
            R[s].neighbors.append(r)
            m['border_table'][r].links.append((s, b.index))
            m['border_table'][s].links.append((r, b.index))
            new_pairs.append(pr)
            if kind:
                paint += [(kind, x) for x in lines(unary_union([LineString(p) for f, p in segs if len(p) > 1]))]
    # vecindades que desaparecen: se quita el borde y se renumeran los posteriores
    for pr in sorted(gone, key=lambda x: -border_of[x].index):
        r, s = pr
        b = border_of.pop(pr)
        k = b.index
        if R[r].u_type == R[s].u_type == SEA or (R[r].u_type != SEA and R[s].u_type != SEA):
            kind = 'sea' if R[r].u_type == SEA else 'land'
            erase += [(kind, LineString(p)) for f, p in b.segments if len(p) > 1]
        del m['borders'][k]
        for i, bb in enumerate(m['borders']):
            bb.index = i
        for row in m['border_table']:
            row.links = [(nb, bi if bi < k else bi - 1) for nb, bi in row.links if bi != k]
        R[r].neighbors.remove(s)
        R[s].neighbors.remove(r)
    if gone:
        print('vecindades eliminadas:', [(R[x].name, R[y].name) for x, y in gone])
    print('vecindades nuevas:', [(R[x].name, R[y].name) for x, y in new_pairs])

    # lo que se borra de la textura es ancho (ERASE_WIDTH): se lleva también trozos de fronteras que siguen existiendo
    # (p. ej. al borrar una región y sumarla a otra). Esas fronteras vivas se repintan donde cae el borrado.
    if erase:
        eu = unary_union([x for _, x in erase]).buffer(0.13)
        have = unary_union([x for _, x in paint]).buffer(1e-4) if paint else None
        for b in m['borders']:
            if len(b.regions) != 2:
                continue
            ra, rb = b.regions
            if (R[ra].u_type == SEA) != (R[rb].u_type == SEA):
                continue                                  # las costas no se pintan
            kind = 'sea' if R[ra].u_type == SEA else 'land'
            for f, pts in b.segments:
                if len(pts) < 2:
                    continue
                ln = LineString(pts)
                if not ln.intersects(eu):
                    continue
                part = ln.intersection(eu)
                if have is not None:
                    part = part.difference(have)
                paint += [(kind, x) for x in lines(part)]

    return erase, paint, new_pairs
