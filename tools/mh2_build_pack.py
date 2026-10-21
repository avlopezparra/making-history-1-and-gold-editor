"""Construye el regionpack «WorldMH2»: el mapa de MH1 Gold con sus regiones subdivididas segun las de Making History II.

    python -u mh2_build_pack.py [--resume] [--finish] [--limit N] [--only NOMBRE ...] [--water]

Trabaja SOLO en copias (mh2/_build); no toca el juego (las texturas del juego se leen por un enlace de solo lectura).
Resultado en mh2/WorldMH2/ (xml, texturas cambiadas, changelog.json, poblacion.json).
Para ponerlo en el juego: python mh2_install.py (o «Instalar → crear regionpack nuevo» del editor).
Si se interrumpe, --resume sigue por donde iba (salta las regiones madre ya subdivididas).
"""
import argparse, json, os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import editor_core, mh2_plan
from shapely.geometry import mapping

ROOT = mh2_plan.ROOT
OUT = os.path.join(ROOT, 'mh2', 'WorldMH2')
BUILD = os.path.join(ROOT, 'mh2', '_build')
PACK = 'WorldMH2'


def live_mesh(P, i):
    """(contorno, vertices) de la region i en la malla actual del proyecto."""
    import shapely, new_region, mhmap
    G = new_region.mesh_polygon(P.m, i)
    V = shapely.MultiPoint(sorted({tuple(v[:2]) for sh in mhmap.region_shapes(P.m, i) for v in sh.vertices}))
    return G, V


def nst_shapes(name):
    """Union de la malla de cada nodo de un .nst del mapa de MH2 -> {nombre: geometria}."""
    import mh2_regions
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    base = os.path.dirname(mh2_regions.NST)
    out = {}
    for k, v in mh2_regions.parse(os.path.join(base, name)).items():
        verts, idx = v
        tris = [Polygon([verts[idx[i]], verts[idx[i + 1]], verts[idx[i + 2]]]) for i in range(0, len(idx), 3)]
        out[k] = unary_union([t if t.is_valid else t.buffer(0) for t in tris if t.area > 0]).buffer(0)
    return out


def safe_save(P, payload):
    """P.save que no revienta: devuelve (informe, errores). Si el editor rechaza el cambio no queda nada a medias."""
    try:
        rep = P.save(payload, log=lambda *x: None)
        return rep, rep.get('errors') or []
    except SystemExit as e:
        P._drop_pending_snapshot()
        P.reload()
        return {}, [str(e)[:160]]


def add_water(P, a):
    """DecorativeLakes.nst -> huecos vacios en la tierra; Rivers.nst -> regiones maritimas nuevas.
    Por lotes pequenos (cada uno: primero se cortan los huecos de la tierra y luego se crean las regiones de mar sobre ellos)."""
    import new_region
    from shapely.geometry import MultiPolygon
    from shapely.ops import unary_union
    from shapely.strtree import STRtree
    lakes, rivers = nst_shapes('DecorativeLakes.nst'), nst_shapes('Rivers.nst')
    t0 = time.time()
    done = {x['nombre'] for e in P.changelog() for x in e.get('regiones_nuevas', [])}
    taken = {r.name for r in P.m['regions']}
    # los rios se hacen disjuntos entre si (de mayor a menor) para que cada hueco lo tome un solo rio
    items, seen = [], None
    for k, W in sorted(rivers.items(), key=lambda kv: -kv[1].area):
        g = W if seen is None else W.difference(seen)
        seen = W if seen is None else unary_union([seen, W])
        parts = [p for p in getattr(g, 'geoms', [g]) if p.geom_type == 'Polygon' and p.area > 1e-7]
        if parts:
            items.append((k.replace('_', ' ') + (' (river)' if k.replace('_', ' ') in taken else ''), MultiPolygon(parts)))
    # lagos: cada poligono suelto, agrupados por casillas de 10 grados (zonas de guardado pequenas = rapido); rios: de uno en uno
    cells = {}
    for k, W in lakes.items():
        for q in getattr(W, 'geoms', [W]):
            if q.geom_type == 'Polygon' and q.area > 1e-7:
                c = q.centroid
                cells.setdefault((int(c.x // 10), int(c.y // 10)), []).append((k, q))
    batches = [('lago', g, False) for g in cells.values()]
    batches += [('rio', items[b:b + 1], True) for b in range(len(items))]
    land = {r.index: new_region.mesh_polygon(P.m, r.index) for r in P.m['regions'] if r.u_type != 0}
    print('mallas de tierra listas: %.0f s' % (time.time() - t0), flush=True)
    for n, (kind, group, make_sea) in enumerate(batches):
        if make_sea and all(nm in done for nm, _ in group):
            continue
        ids = list(land)
        tree = STRtree([land[i] for i in ids])
        cuts = {}
        for nm, W in group:
            for j in tree.query(W):
                part = W.intersection(land[ids[j]])
                if part.area > 1e-7:
                    cuts[ids[j]] = part if ids[j] not in cuts else unary_union([cuts[ids[j]], part])
        if cuts:
            def cut_asg(d):
                return [{'kind': 'cut', 'polygon': mapping(g), 'from': i, 'into': None} for i, g in d.items()]
            rep, err = safe_save(P, {'assigns': cut_asg(cuts), 'paint': True})
            if err and len(cuts) > 1:      # se prueba region por region y se salta la que el editor rechaza
                bad = 0
                for i, g in cuts.items():
                    rep, e1 = safe_save(P, {'assigns': cut_asg({i: g}), 'paint': True})
                    bad += bool(e1)
                    if e1:
                        print('   no se pudo recortar %s: %s' % (P.m['regions'][i].name, e1[0][:90]), flush=True)
                err = ['%d regiones sin recortar' % bad] if bad else []
            elif err:
                print('   no se pudo recortar: %s' % err[0][:90], flush=True)
            for i in cuts:      # solo cambian las regiones recortadas
                land[i] = new_region.mesh_polygon(P.m, i)
            print('%s lote %d/%d: %d regiones recortadas, errores %s | %.0f s' % (kind, n, len(batches), len(cuts), err, time.time() - t0), flush=True)
        if make_sea:
            asg = [{'kind': 'new_region', 'polygon': mapping(W), 'name': nm, 'from': None, 'sea': True, 'fill': True, 'u_type': 0}
                   for nm, W in group if nm not in done]
            rep, err = safe_save(P, {'assigns': asg, 'paint': True})
            print('   rio %s: %d nuevas, errores %s | %.0f s' % (group[0][0], len(rep.get('new_regions') or []), err, time.time() - t0), flush=True)
        shutil.rmtree(P.history, ignore_errors=True)
        os.makedirs(P.history, exist_ok=True)


def reference_population(P, m2props, mother_of):
    """Habitantes de MH2 que caen en cada region de tierra del mapa nuevo (por area): {region: {pop, mh2, owner, culture, mother}}."""
    import new_region
    from shapely.strtree import STRtree
    R = P.m['regions']
    land = {r.index: new_region.mesh_polygon(P.m, r.index) for r in R if r.u_type != 0}
    m2 = mh2_plan.mh2_land()
    keys = list(m2)
    geo = [m2[k][0].simplify(1e-3) for k in keys]
    tree = STRtree(geo)
    inside, total = {}, {}
    for i, g in land.items():
        if g is None or g.is_empty:
            continue
        for j in tree.query(g):
            a = g.intersection(geo[j]).area
            if a > 1e-9:
                inside.setdefault(i, {})[keys[j]] = a
                total[keys[j]] = total.get(keys[j], 0) + a
    out = {}
    for i, d in inside.items():
        name = R[i].name
        pop = sum((m2props[k].get('population') or 0) * a / total[k] for k, a in d.items())
        best = max(d, key=d.get)
        out[name] = {'pop': int(round(pop)), 'mh2': best, 'owner': m2props[best].get('owner'),
                     'culture': m2props[best].get('culture'), 'mother': mother_of.get(name)}
    return out


def main():
    import faulthandler
    faulthandler.dump_traceback_later(420, repeat=True, file=open(os.path.join(os.environ.get('TEMP', '.'), 'mh2_trace.txt'), 'w'))
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--only', nargs='*', default=[])
    ap.add_argument('--water', action='store_true', help='con --limit: tambien lagos y rios')
    ap.add_argument('--resume', action='store_true', help='sigue el trabajo de mh2/_build (salta las regiones madre ya subdivididas)')
    ap.add_argument('--retry', action='store_true', help='con --resume: vuelve a intentar las madres que ya fallaron')
    ap.add_argument('--no-water', action='store_true', help='no hacer lagos ni rios en esta pasada (se pueden hacer despues con --resume --finish)')
    ap.add_argument('--finish', action='store_true', help='no subdivide mas: solo lagos/rios y la salida')
    a = ap.parse_args()
    maps = os.path.join(BUILD, 'Maps')
    pk = os.path.join(maps, PACK)
    link = os.path.join(pk, 'art', 'OperationalTerrain')
    if not a.resume:
        if os.path.exists(link):
            try:
                os.rmdir(link)      # quita el enlace sin tocar el juego
            except OSError:
                pass          # era una carpeta real (copia de una version anterior): rmtree de abajo la borra
        shutil.rmtree(BUILD, ignore_errors=True)
        os.makedirs(os.path.join(pk, 'xml'))
        for f in editor_core.XML_FILES:
            shutil.copy2(os.path.join(mh2_plan.ORIG, f), os.path.join(pk, 'xml', f))
        for f in ('map.xml', 'properties.xml'):
            shutil.copy2(os.path.join(editor_core.MAPS, 'World', 'xml', f), os.path.join(pk, 'xml', f))
        os.makedirs(os.path.join(BUILD, 'proj', 'tiles'))
        for f in os.listdir(os.path.join(mh2_plan.ORIG, 'OperationalTerrain')):
            shutil.copy2(os.path.join(mh2_plan.ORIG, 'OperationalTerrain', f), os.path.join(BUILD, 'proj', 'tiles', f))
    # texturas: las del juego (solo lectura, por enlace) salvo las 40 que el mapa de Chile cambio, que se toman de las originales
    if not os.path.exists(link):
        os.makedirs(os.path.join(pk, 'art'), exist_ok=True)
        subprocess.check_call(['cmd', '/c', 'mklink', '/J', link, os.path.join(editor_core.MAPS, 'World', 'art', 'OperationalTerrain')],
                              stdout=subprocess.DEVNULL)
    editor_core.MAPS = maps
    P = editor_core.Project(os.path.join(BUILD, 'proj'), os.path.join(BUILD, 'bk'), pack=PACK)
    pl = mh2_plan.Planner(a.only or None)
    pl.taken |= {r.name for r in P.m['regions']}
    log0 = P.changelog()
    done_m = {x['madre'] for e in log0 for x in e.get('regiones_nuevas', []) if x.get('madre')}
    water_done = False       # add_water se puede repetir: no vuelve a hacer lo que ya esta
    t0 = time.time()
    failed, tot_new = [], 0
    ff = os.path.join(BUILD, 'fallos.json')
    prev_failed = [] if a.retry or not os.path.exists(ff) else json.load(open(ff, encoding='utf-8-sig'))
    todo = [(i, v) for i, v in pl.m1.items() if v[0] not in done_m and v[0] not in prev_failed]
    if a.limit:
        todo = todo[:a.limit]
    if a.finish:
        todo = []
    for n, (i, (rname, G)) in enumerate(todo):
        done = False
        parts, err = None, []
        for level in range(len(mh2_plan.LADDER)):
            try:
                parts = pl.plan(i, level, live_mesh(P, i))
            except Exception as ex:      # geometria rara (TopologyException): se prueba con mas simplificacion
                print('   plan %s nivel %d: %s' % (rname, level, str(ex)[:80]), flush=True)
                parts = [True]
                continue
            if not parts:
                break
            pcs = pl.names(rname, parts)
            Gl = live_mesh(P, i)[0]
            assigns = [{'kind': 'new_region', 'polygon': mapping(mh2_plan.extend(Gl, pc['geom'])), 'name': pc['name'], 'from': i,
                        'cut_all': False, 'fill': False} for pc in pcs[1:]]
            try:
                rep = P.save({'assigns': assigns, 'paint': True}, log=lambda *x: None)
                err = rep.get('errors') or []
            except SystemExit as e:
                P._drop_pending_snapshot()
                P.reload()
                err = [str(e)[:200]]
            if not err:
                pl.commit(pcs)
                tot_new += len(pcs) - 1
                done = True
                break
            P.reload()
        shutil.rmtree(P.history, ignore_errors=True)
        os.makedirs(P.history, exist_ok=True)
        if parts and not done:
            failed.append(rname)
            json.dump(sorted(set(failed) | set(prev_failed)), open(ff, 'w'))
            print('   FALLO %s: %s' % (rname, err[0] if err else ''), flush=True)
        if n % 10 == 0:
            print('%d/%d %s | %d regiones nuevas | %.0f s' % (n, len(todo), rname, tot_new, time.time() - t0), flush=True)
    failed = sorted(set(failed) | set(prev_failed))
    json.dump(failed, open(ff, 'w'))
    if (not a.limit or a.water) and not water_done and not a.no_water:
        add_water(P, a)
    # changelog: sin dueno ni fraccion, para que el editor reparta lo que haya en cada escenario
    log = P.changelog()
    mother_of = {}
    for e in log:
        e['regionpack'] = PACK
        e['instalado'] = True
        for x in e.get('regiones_nuevas', []):
            x['fraccion'] = None
            x['poblacion'] = None
            x['pais'] = None
            if x.get('madre') and not x.get('mar'):
                mother_of[x['nombre']] = x['madre']
    props = {x['properties']['name']: x['properties'] for x in json.load(open(mh2_plan.GEOJSON, encoding='utf-8'))['features']}
    pops = reference_population(P, props, mother_of)
    os.makedirs(os.path.join(OUT, 'xml'), exist_ok=True)
    for f in editor_core.XML_FILES:
        shutil.copy2(os.path.join(P.xml, f), os.path.join(OUT, 'xml', f))
    for f in ('map.xml', 'properties.xml'):
        shutil.copy2(os.path.join(pk, 'xml', f), os.path.join(OUT, 'xml', f))
    shutil.rmtree(os.path.join(OUT, 'art'), ignore_errors=True)
    td = os.path.join(OUT, 'art', 'OperationalTerrain')
    os.makedirs(td)
    for f in os.listdir(P.tiles):
        shutil.copy2(os.path.join(P.tiles, f), os.path.join(td, f))
    if os.path.exists(ff):
        shutil.copy2(ff, os.path.join(OUT, 'fallos.json'))
    json.dump(log, open(os.path.join(OUT, 'changelog.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump({'fuente': 'Making History II', 'regiones': pops}, open(os.path.join(OUT, 'poblacion.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    os.rmdir(link)      # quita el enlace a las texturas del juego (no borra nada)
    print('regiones nuevas en esta pasada:', tot_new, '| total en el mapa:', len(P.m['regions']), '| madres que no se pudieron subdividir:', failed)


if __name__ == '__main__':
    main()
