"""Construye el regionpack «WorldMH2»: el mapa de MH1 Gold con sus regiones subdivididas segun las de Making History II.

    python mh2_build_pack.py [--limit N] [--batch 25]

Trabaja SOLO en copias (mh2/_build); no toca el juego. Resultado en mh2/WorldMH2/ (xml, texturas cambiadas,
changelog.json, poblacion.json). Para ponerlo en el juego: python mh2_install.py (o «Instalar → crear regionpack nuevo» del editor).
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


def add_water(P, a):
    """DecorativeLakes.nst -> huecos vacios en la tierra; Rivers.nst -> regiones maritimas nuevas (dos guardados)."""
    import new_region
    from shapely.ops import unary_union
    R = P.m['regions']
    lakes, rivers = nst_shapes('DecorativeLakes.nst'), nst_shapes('Rivers.nst')
    land = {r.index: new_region.mesh_polygon(P.m, r.index) for r in R if r.u_type != 0}
    cuts = []
    allw = list(lakes.values()) + list(rivers.values())
    for W in allw:
        for i, g in land.items():
            part = W.intersection(g)
            if part.area > 1e-7:
                cuts.append({'kind': 'cut', 'polygon': mapping(part), 'from': i, 'into': None})
    # los cortes de dos rios que se cruzan se solapan: cada region cede cada trozo una sola vez
    uniq = {}
    for c in cuts:
        from shapely.geometry import shape
        g = shape(c['polygon'])
        prev = uniq.get(c['from'])
        uniq[c['from']] = g if prev is None else unary_union([prev, g])
    cuts = [{'kind': 'cut', 'polygon': mapping(g), 'from': i, 'into': None} for i, g in uniq.items()]
    rep = P.save({'assigns': cuts, 'paint': True}, log=lambda *x: None)
    print('lagos y rios: %d regiones recortadas, errores %s' % (len(cuts), rep.get('errors')), flush=True)
    taken = {r.name.decode('latin1') if isinstance(r.name, bytes) else r.name for r in P.m['regions']}
    seen = None
    assigns = []
    for k, W in sorted(rivers.items(), key=lambda kv: -kv[1].area):
        g = W if seen is None else W.difference(seen)
        seen = W if seen is None else unary_union([seen, W])
        parts = [p for p in getattr(g, 'geoms', [g]) if p.geom_type == 'Polygon' and p.area > 1e-7]
        if not parts:
            continue
        nm = k.replace('_', ' ')
        if nm in taken:
            nm += ' (river)'
        taken.add(nm)
        from shapely.geometry import MultiPolygon
        assigns.append({'kind': 'new_region', 'polygon': mapping(MultiPolygon(parts)), 'name': nm, 'from': None, 'sea': True,
                        'fill': True, 'u_type': 0})
    for b in range(0, len(assigns), 30):
        rep = P.save({'assigns': assigns[b:b + 30], 'paint': True}, log=lambda *x: None)
        print('rios lote %d: %d nuevas, errores %s' % (b // 30, len(rep.get('new_regions') or []), rep.get('errors')), flush=True)
        shutil.rmtree(P.history, ignore_errors=True); os.makedirs(P.history, exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--batch', type=int, default=25)
    ap.add_argument('--only', nargs='*', default=[])
    ap.add_argument('--water', action='store_true', help='con --limit: tambien lagos y rios')
    a = ap.parse_args()
    if os.path.exists(os.path.join(BUILD, 'Maps', PACK, 'art', 'OperationalTerrain')):
        try:
            os.rmdir(os.path.join(BUILD, 'Maps', PACK, 'art', 'OperationalTerrain'))      # quita el enlace sin tocar el juego
        except OSError:
            pass          # era una carpeta real (copia de una version anterior): rmtree de abajo la borra
    shutil.rmtree(BUILD, ignore_errors=True)
    maps = os.path.join(BUILD, 'Maps')
    pk = os.path.join(maps, PACK)
    os.makedirs(os.path.join(pk, 'xml'))
    for f in editor_core.XML_FILES:
        shutil.copy2(os.path.join(mh2_plan.ORIG, f), os.path.join(pk, 'xml', f))
    for f in ('map.xml', 'properties.xml'):
        shutil.copy2(os.path.join(editor_core.MAPS, 'World', 'xml', f), os.path.join(pk, 'xml', f))
    # texturas: las del juego (solo lectura, por enlace) salvo las 40 que el mapa de Chile cambio, que se toman de las originales
    os.makedirs(os.path.join(pk, 'art'))
    subprocess.check_call(['cmd', '/c', 'mklink', '/J', os.path.join(pk, 'art', 'OperationalTerrain'),
                           os.path.join(editor_core.MAPS, 'World', 'art', 'OperationalTerrain')], stdout=subprocess.DEVNULL)
    os.makedirs(os.path.join(BUILD, 'proj', 'tiles'))
    for f in os.listdir(os.path.join(mh2_plan.ORIG, 'OperationalTerrain')):
        shutil.copy2(os.path.join(mh2_plan.ORIG, 'OperationalTerrain', f), os.path.join(BUILD, 'proj', 'tiles', f))
    editor_core.MAPS = maps
    P = editor_core.Project(os.path.join(BUILD, 'proj'), os.path.join(BUILD, 'bk'), pack=PACK)
    pl = mh2_plan.Planner(a.only or None)
    m2 = pl.m2
    R = P.m['regions']
    t0 = time.time()
    plan, failed, tot_new = [], [], 0
    todo = list(pl.m1.items())
    if a.limit:
        todo = todo[:a.limit]
    for n, (i, (rname, G)) in enumerate(todo):
        done = False
        for level in range(len(mh2_plan.LADDER)):
            try:
                parts = pl.plan(i, level, live_mesh(P, i))
            except Exception as ex:      # geometria rara (TopologyException): se prueba con mas simplificacion
                print('   plan %s nivel %d: %s' % (rname, level, str(ex)[:80]), flush=True)
                parts, err = [True], ['plan']
                continue
            if not parts:
                break
            pcs = pl.names(rname, parts)
            Gl = live_mesh(P, i)[0]
            assigns = [{'kind': 'new_region', 'polygon': mapping(mh2_plan.extend(Gl, pc['geom'])), 'name': pc['name'], 'from': i, 'cut_all': False, 'fill': False}
                       for pc in pcs[1:]]
            try:
                rep = P.save({'assigns': assigns, 'paint': True}, log=lambda *x: None)
                err = rep.get('errors') or []
            except SystemExit as e:
                P._drop_pending_snapshot(); P.reload()
                err = [str(e)[:200]]
            if not err:
                pl.commit(pcs)
                plan.append({'mother': i, 'mother_name': rname, 'parts': pcs})
                tot_new += len(pcs) - 1
                done = True
                break
            P.reload()
        if parts and not done:
            failed.append(rname)
            print('   FALLO %s: %s' % (rname, err[0] if err else ''), flush=True)
        if n % 10 == 0:
            print('%d/%d %s | %d regiones nuevas | %.0f s' % (n, len(todo), rname, tot_new, time.time() - t0), flush=True)
        if n % 10 == 9:
            shutil.rmtree(P.history, ignore_errors=True); os.makedirs(P.history, exist_ok=True)
    if not a.limit or a.water:
        add_water(P, a)
    # changelog: sin dueno ni fraccion, para que el editor reparta lo que haya en cada escenario
    log = P.changelog()
    for e in log:
        e['regionpack'] = PACK
        e['instalado'] = True
        for x in e.get('regiones_nuevas', []):
            x['fraccion'] = None
            x['poblacion'] = None
            x['pais'] = None
    # poblacion de referencia de MH2 (el editor la ofrece al adecuar un escenario)
    share = {}
    for e in plan:
        for pc in e['parts']:
            share.setdefault(pc['key'], []).append(pc)
    pops = {}
    for k, pcs in share.items():
        tot = sum(p['geom'].area for p in pcs) or 1
        pr = m2[k][1]
        for p in pcs:
            pops[p['name']] = {'pop': int(round((pr.get('population') or 0) * p['geom'].area / tot)),
                               'mh2': k, 'owner': pr.get('owner'), 'culture': pr.get('culture')}
    for e in plan:
        for pc in e['parts']:
            pops[pc['name']]['mother'] = None if pc['mother'] else e['mother_name']
    os.makedirs(os.path.join(OUT, 'xml'), exist_ok=True)
    for f in editor_core.XML_FILES:
        shutil.copy2(os.path.join(P.xml, f), os.path.join(OUT, 'xml', f))
    for f in ('map.xml', 'properties.xml'):
        shutil.copy2(os.path.join(pk, 'xml', f), os.path.join(OUT, 'xml', f))
    td = os.path.join(OUT, 'art', 'OperationalTerrain')
    shutil.rmtree(os.path.join(OUT, 'art'), ignore_errors=True)
    os.makedirs(td)
    for f in os.listdir(P.tiles):
        shutil.copy2(os.path.join(P.tiles, f), os.path.join(td, f))
    json.dump(log, open(os.path.join(OUT, 'changelog.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump({'fuente': 'Making History II', 'regiones': pops}, open(os.path.join(OUT, 'poblacion.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    os.rmdir(os.path.join(pk, 'art', 'OperationalTerrain'))      # quita el enlace a las texturas del juego (no borra nada)
    print('regiones nuevas:', tot_new, '| total en el mapa:', len(P.m['regions']), '| madres que no se pudieron subdividir:', failed)


if __name__ == '__main__':
    main()
