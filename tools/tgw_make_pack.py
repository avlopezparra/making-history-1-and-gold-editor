"""Builds the «WorldTGW» regionpack: WorldMoreRegionsMH2 (MH2's map) reshaped into the map of Making History: The Great War /
The Second World War (one shared map), changing only what differs from MH2.

    python -u tools/tgw_make_pack.py "<...>/The Great War/content/Making History TGW" [--step all|rename|new|delete|reshape]

1. a copy of the WorldMoreRegionsMH2 editor project, as a new regionpack (its game files go to <project>/base);
2. new TGW regions that are an MH2 region under another name (same shape) -> renamed (RegionRename: scenarios keep working);
3. the other new TGW regions -> new regions with their TGW outline;
4. MH2 regions TGW does not have -> merged into the TGW region that covers most of them;
5. every region whose outline differs from TGW's -> reshaped to it.
TGW lakes (terrain Lake: no owner in any scenario) stay as MH2 had them (holes or land). Writes nothing to the game: install from
the region editor or with Project.install, in MH1 or Gold. Each step can be run again (it skips what is done).
"""
import argparse, json, os, re, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shapely.geometry import mapping
from shapely.strtree import STRtree
import editor_core, new_region
import mh2_make_world2 as W
import tgw_region_map as T

NAME, BASE_PACK = 'WorldTGW', 'WorldMoreRegionsMH2'
FOLDER = os.path.join(W.ROOT, 'editor_proyecto_' + NAME)
SRC_PROJECT = os.path.join(W.ROOT, 'editor_proyecto_' + BASE_PACK)
REPORT = os.path.join(W.ROOT, 'mh2', NAME + '_informe.json')
SAME = 0.98          # IoU from which a region already has its TGW outline
RENAME = 0.90        # IoU between a new TGW region and a gone MH2 one to count as the same region renamed


def create():
    if os.path.exists(FOLDER):
        return
    shutil.copytree(SRC_PROJECT, FOLDER, ignore=shutil.ignore_patterns('history'))
    shutil.copytree(os.path.join(editor_core.MAPS, BASE_PACK), os.path.join(FOLDER, 'base'))     # read only: the game's copy is not touched
    json.dump({'pack': NAME, 'nuevo': True, 'decided': True}, open(os.path.join(FOLDER, 'pack.json'), 'w'))


def tgw_regions(base):
    """{name: (is_sea, is_lake)} of the TGW map."""
    xml = open(os.path.join(base, 'modules', 'mh2 map', 'world map', 'regions.xml'), encoding='utf-8', errors='replace').read()
    out = {}
    for blk in re.findall(r'<object type="gs_tbg.Region".*?</object>', xml, flags=re.S):
        n, t = re.search(r'strName" value="([^"]+)"', blk).group(1), re.search(r'tmplTerrain" value="sd\.([^"]+)"', blk)
        t = t.group(1) if t else ''
        out[n] = (t in T.SEA_TERRAIN, t == 'Lake')
    return out


def project():
    P = editor_core.Project(FOLDER, os.path.join(FOLDER, '_respaldo'), pack=NAME)
    P.snapshot = lambda *x, **k: None
    return P


def names(P):
    return {T.key(P.rname(i)): i for i in range(len(P.m['regions']))}


def mesh(P, i):
    return new_region.mesh_polygon(P.m, i).buffer(0)


def iou(a, b):
    u = a.union(b).area
    return a.intersection(b).area / u if u else 1.0


def save_once(P, ops):
    try:
        rep = P.save({'assigns': ops, 'paint': True, 'topo': True}, log=lambda *x: None)
        err = rep.get('errors') or []
    except (SystemExit, Exception) as e:
        P._drop_pending_snapshot()
        P.reload()
        err = [str(e)[:160] or type(e).__name__]
    shutil.rmtree(P.history, ignore_errors=True)
    os.makedirs(P.history, exist_ok=True)
    return err


def save(P, items, log):
    """items: [(name, op(simplify) -> operation)]. Saves in batches; on refusal splits the batch and retries single ones lightened.
    Returns the names that could not be saved."""
    failed = []

    def attempt(group):
        if not group or not save_once(P, [d for d in (op(0) for _, op in group) if d]):
            return
        if len(group) > 1:
            attempt(group[:len(group) // 2])
            attempt(group[len(group) // 2:])
            return
        for simp in (5e-4, 2e-3, 8e-3):
            d = group[0][1](simp)
            if d and not save_once(P, [d]):
                return
        failed.append(group[0][0])
    for k in range(0, len(items), 20):
        attempt(items[k:k + 20])
        log('  %d/%d, %d fallos' % (min(k + 20, len(items)), len(items), len(failed)))
    return failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tgw')
    ap.add_argument('--step', default='all', choices=('all', 'rename', 'new', 'delete', 'reshape'))
    a = ap.parse_args()
    log = lambda *x: print(*x, flush=True)
    create()
    tg = tgw_regions(a.tgw)
    shp = T.shapes(a.tgw)
    land = {n for n, (sea, lake) in tg.items() if not lake and shp.get(T.key(n)) is not None}      # «land»: every non-lake region
    tkeys = {T.key(n) for n in tg}
    rep = json.load(open(REPORT, encoding='utf-8')) if os.path.exists(REPORT) else {}
    dump = lambda: json.dump(rep, open(REPORT, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    by_cell = lambda n: (int(shp[T.key(n)].centroid.x // 10), int(shp[T.key(n)].centroid.y // 10))
    P = project()
    t0 = time.time()

    if a.step in ('all', 'rename'):
        idx = names(P)
        gone = [P.rname(i) for k, i in idx.items() if k not in tkeys]
        gm = {g: mesh(P, idx[T.key(g)]) for g in gone}
        tree = STRtree([gm[g] for g in gone])
        done = rep.setdefault('renamed', {})
        for n in sorted(x for x in land if T.key(x) not in idx):
            g = shp[T.key(n)]
            best = max(((iou(g, gm[gone[i]]), gone[i]) for i in tree.query(g)), default=(0, None))
            if best[0] >= RENAME and best[1] not in done:
                P.rename_region(best[1], n, re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', n))
                done[best[1]] = n
        log('renombradas: %d' % len(done))
        dump()

    if a.step in ('all', 'new'):
        idx = names(P)
        todo = sorted((n for n in land if T.key(n) not in idx), key=by_cell)

        def op(n):
            sea = tg[n][0]

            def make(simp):
                g = W.prep(shp[T.key(n)], simp)
                return g and dict({'kind': 'new_region', 'polygon': mapping(g), 'name': n, 'from': None, 'fill': True, 'u_type': 0 if sea else 1},
                                  **({'sea': True} if sea else {'cut_all': True}))     # land: cut it from the land regions it covers
            return make
        log('regiones nuevas: %d' % len(todo))
        rep['new_failed'] = save(P, [(n, op(n)) for n in todo], log)
        dump()

    if a.step in ('all', 'delete'):
        idx = names(P)
        gone = [P.rname(i) for k, i in idx.items() if k not in tkeys]
        lt = [n for n in land if T.key(n) in idx]
        tree = STRtree([shp[T.key(n)] for n in lt])
        into = rep.setdefault('merged', {})
        for g in gone:
            m = mesh(P, idx[T.key(g)])
            sea = P.m['regions'][idx[T.key(g)]].u_type == 0
            near = [(m.intersection(shp[T.key(lt[i])]).area, lt[i]) for i in tree.query(m)]
            c = [x for x in near if tg[x[1]][0] == sea] or near
            into[g] = max(c)[1] if c and max(c)[0] > 0 else None
        log('a fusionar: %d (%d sin destino)' % (len(gone), sum(1 for g in gone if not into[g])))
        pend = [g for g in gone if into[g]]
        for k in range(0, len(pend), 20):
            idx = names(P)          # indices shift after each deletion
            err = save_once(P, [{'kind': 'delete_region', 'region': idx[T.key(g)], 'into': idx[T.key(into[g])]} for g in pend[k:k + 20]])
            if err:
                log('  error fusionando %s: %s' % (pend[k:k + 20], err))
        dump()

    if a.step in ('all', 'reshape'):
        idx = names(P)
        todo = [n for n in sorted(land, key=by_cell) if T.key(n) in idx and iou(mesh(P, idx[T.key(n)]), shp[T.key(n)]) < SAME]

        def op(n):
            def make(simp):
                g = W.prep(shp[T.key(n)], simp)
                return g and {'kind': 'assign', 'polygon': mapping(g), 'region': names(P)[T.key(n)], 'fill': True}
            return make
        log('a reformar: %d' % len(todo))
        rep['reshape'] = todo
        rep['reshape_failed'] = save(P, [(n, op(n)) for n in todo], log)
        dump()
    log('listo en %.0f s; %d regiones' % (time.time() - t0, len(P.m['regions'])))


if __name__ == '__main__':
    main()
