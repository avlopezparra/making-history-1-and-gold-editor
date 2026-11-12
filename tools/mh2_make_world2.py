"""Creates the new «MH2World2» regionpack from mh2/mh2_mundo.geojson (empty map + one new region per outline).

    python -u mh2_make_world2.py [--resume [--retry]] [--limit N]

Leaves the editor project in making-history/editor_proyecto_MH2World2 (new regionpack not yet installed: in the region
editor it appears under «Regionpack» and is installed with Instalar). Writes nothing to the game. If cut off, --resume continues where it left off.
Regions the editor rejects (invalid outline) are retried with a lightened outline; those that still fail go to
mh2/MH2World2_fallos.json.
"""
import argparse, json, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import editor_core, new_pack, new_region, mh2_plan
import shapely
from shapely.geometry import shape, mapping, MultiPolygon
from shapely.ops import unary_union

ROOT = mh2_plan.ROOT
NAME = 'MH2World2'
FOLDER = os.path.join(ROOT, 'editor_proyecto_' + NAME)
SRC = os.path.join(ROOT, 'mh2', 'mh2_mundo.geojson')
GRID = 1e-4          # degrees: outlines are rounded to this grid (identical neighboring vertices; the editor merges below 5e-5)
BATCH = 40


def polys(g):
    out = []
    for p in getattr(g, 'geoms', [g]):
        if p.geom_type == 'Polygon' and p.area > 1e-8:
            out.append(p)
        elif p.geom_type in ('MultiPolygon', 'GeometryCollection'):
            out += polys(p)
    return out


def prep(g, simplify=0):
    if simplify:
        g = g.simplify(simplify)
    g = shapely.set_precision(g, GRID)
    ps = polys(shapely.make_valid(g))
    return MultiPolygon(ps) if ps else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--retry', action='store_true', help='con --resume: vuelve a intentar las que ya fallaron')
    ap.add_argument('--limit', type=int, default=0)
    build(ap.parse_args())


def build(a):
    """Builds (or continues building) the regionpack; returns the list of outlines that could not be placed."""
    world = os.path.join(editor_core.MAPS, 'World')
    if not a.resume:
        if os.path.exists(FOLDER):
            raise SystemExit('ya existe %s (usa --resume o borra la carpeta)' % FOLDER)
        new_pack.create_project(FOLDER, NAME, world)
    P = editor_core.Project(FOLDER, os.path.join(FOLDER, '_respaldo'), pack=NAME)
    P.snapshot = lambda *x, **k: None       # without «Volver» snapshots (they only cost time and disk in a batch build)
    done = {r.name for r in P.m['regions']}           # already on the map (internal name)
    ff = os.path.join(ROOT, 'mh2', NAME + '_fallos.json')
    prev_failed = json.load(open(ff)) if a.resume and not getattr(a, 'retry', False) and os.path.exists(ff) else []
    feats = json.load(open(SRC, encoding='utf-8'))['features']
    iname = lambda f: new_region.internal_name(mh2_plan.pretty(f['properties']['name']))
    todo = [f for f in feats if iname(f) not in done and f['properties']['name'] not in prev_failed]
    if a.limit:
        todo = todo[:a.limit]
    cells = {}
    for f in todo:
        c = shape(f['geometry']).centroid
        cells.setdefault((int(c.x // 10), int(c.y // 10)), []).append(f)
    batches = []
    for k in sorted(cells):
        fs = cells[k]
        batches += [fs[i:i + BATCH] for i in range(0, len(fs), BATCH)]

    def asg(f, simp, seen):
        g = prep(shape(f['geometry']), simp)
        if g is None:
            return None, seen
        if seen is not None:
            g = prep(g.difference(seen))
            if g is None:
                return None, seen
        pr = f['properties']
        sea = pr['mh_type'] == 'sea_region'
        d = {'kind': 'new_region', 'polygon': mapping(g), 'name': mh2_plan.pretty(pr['name']), 'from': None, 'fill': True, 'u_type': 0 if sea else 1}
        if sea:
            d['sea'] = True
        return d, (g if seen is None else unary_union([seen, g]))

    def save(items):
        try:
            rep = P.save({'assigns': items, 'paint': True, 'topo': True}, log=lambda *x: None)
            err = rep.get('errors') or []
        except (SystemExit, Exception) as e:       # the editor rejects the change (or fails): undone and counted as a failure
            P._drop_pending_snapshot()
            P.reload()
            err = [str(e)[:160] or type(e).__name__]
        shutil.rmtree(P.history, ignore_errors=True)      # without «Volver» snapshots: they fill the disk (GB)
        os.makedirs(P.history, exist_ok=True)
        return err

    t0, ok, failed = time.time(), 0, list(prev_failed)
    for n, fs in enumerate(batches):
        items, seen = [], None
        for f in fs:
            d, seen = asg(f, 0, seen)
            if d:
                items.append((f, d))
        def attempt(group):
            """Saves the group; if the editor rejects it, splits it in two; a single region is retried lightened."""
            nonlocal ok
            if not group:
                return
            if not save([d for _, d in group]):
                ok += len(group)
                return
            if len(group) > 1:
                h = len(group) // 2
                attempt(group[:h])
                attempt(group[h:])
                return
            f = group[0][0]
            for simp in (5e-4, 2e-3, 8e-3):
                d1, _ = asg(f, simp, None)
                if d1 and not save([d1]):
                    ok += 1
                    return
            failed.append(f['properties']['name'])
        attempt(items)
        shutil.rmtree(P.history, ignore_errors=True)
        os.makedirs(P.history, exist_ok=True)
        json.dump(failed, open(ff, 'w'))
        print('lote %d/%d | %d regiones | %d fallos | %.0f s' % (n + 1, len(batches), ok, len(failed), time.time() - t0), flush=True)
    print('listo: %d regiones, %d fallos, %d en el mapa' % (ok, len(failed), len(P.m['regions'])))
    return failed


if __name__ == '__main__':
    main()
