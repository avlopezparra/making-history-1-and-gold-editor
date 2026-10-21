"""Crea el regionpack nuevo «MH2World2» desde mh2/mh2_mundo.geojson (mapa vacio + una region nueva por contorno).

    python -u mh2_make_world2.py [--resume] [--limit N]

Deja el proyecto del editor en making-history/editor_proyecto_MH2World2 (regionpack nuevo aun sin instalar: en el editor de
regiones aparece en «Regionpack» y se instala con Instalar). No escribe nada en el juego. Si se corta, --resume sigue por donde iba.
Las regiones que el editor rechaza (contorno invalido) se reintentan con el contorno aligerado; las que aun asi fallan van a
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
GRID = 1e-4          # grados: los contornos se redondean a esta rejilla (vertices vecinos identicos; el editor funde a menos de 5e-5)
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
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    world = os.path.join(editor_core.MAPS, 'World')
    if not a.resume:
        if os.path.exists(FOLDER):
            raise SystemExit('ya existe %s (usa --resume o borra la carpeta)' % FOLDER)
        new_pack.create_project(FOLDER, NAME, world)
    P = editor_core.Project(FOLDER, os.path.join(FOLDER, '_respaldo'), pack=NAME)
    P.snapshot = lambda *x, **k: None       # sin instantaneas de «Volver» (solo cuestan tiempo y disco en una construccion por lotes)
    done = {r.name for r in P.m['regions']}           # ya en el mapa (nombre interno)
    ff = os.path.join(ROOT, 'mh2', NAME + '_fallos.json')
    prev_failed = json.load(open(ff)) if a.resume and os.path.exists(ff) else []
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
        except SystemExit as e:
            P._drop_pending_snapshot()
            P.reload()
            err = [str(e)[:160]]
        shutil.rmtree(P.history, ignore_errors=True)      # sin instantaneas de «Volver»: llenan el disco (GB)
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
            """Guarda el grupo; si el editor lo rechaza, lo parte en dos; una region sola se reintenta aligerada."""
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


if __name__ == '__main__':
    main()
