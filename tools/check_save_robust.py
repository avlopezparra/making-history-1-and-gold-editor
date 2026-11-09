"""Comprobaciones del guardado del mapa: los errores de GEOS no salen crudos ni dejan nada a medias, las regiones nuevas que
se pisan no rompen la malla, y la página nunca borra los cambios pendientes si el guardado falla.
Uso: python check_save_robust.py <carpeta de un proyecto del editor>   (trabaja sobre una copia temporal; no toca el proyecto)"""
import hashlib, json, os, re, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import editor_core as ec, mhmap
from shapely.errors import GEOSException
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union

src = sys.argv[1]
tmp = tempfile.mkdtemp(prefix='mh_check_')
quiet = lambda *a: None


def fresh():
    d = os.path.join(tmp, 'proyecto')
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    shutil.copytree(os.path.join(src, 'xml'), os.path.join(d, 'xml'))
    shutil.copy(os.path.join(src, 'pack.json'), d)
    return ec.Project(d, os.path.join(tmp, 'respaldo'), json.load(open(os.path.join(src, 'pack.json')))['pack'])


def digest(p):
    return [hashlib.md5(open(os.path.join(p.xml, f), 'rb').read()).hexdigest() for f in ('regions.bin', 'regions.nts', 'borders.brd')]


def G(p, r):
    return unary_union([Polygon(t) for s in mhmap.region_shapes(p.m, r) for t in s.triangles() if Polygon(t).area > 0] or [Polygon()])


def new_op(name, poly, **kw):
    return dict({'kind': 'new_region', 'polygon': mapping(poly), 'name': name, 'newName': name, 'u_type': 1, 'from': None,
                 'cut_all': False, 'fill': True, 'owner': None}, **kw)


try:
    p = fresh()
    land = max((g.index for g in p.m['regions'] if g.u_type != ec.SEA), key=lambda r: G(p, r).area)
    # 1. región nueva que rodea a otra y roza sus bordes (colección polígono + línea contra una malla aún vacía): antes, GEOSException
    try:
        p.save({'modified': {}, 'assigns': [new_op('ChkA', G(p, land).buffer(0.03))], 'topo': True}, quiet)
    except SystemExit:
        pass                      # un rechazo explicado vale; lo que no vale es la excepción cruda de GEOS
    # 2. si GEOS falla de verdad, sale un mensaje claro (SystemExit) y el mapa del proyecto queda byte a byte como estaba
    p = fresh()
    before = digest(p)
    real = ec.Project._save_once

    def boom(self, payload, log=print):
        raise GEOSException('AssertionFailedException: Should never reach here')
    ec.Project._save_once = boom
    try:
        p.save({'modified': {}, 'assigns': [new_op('ChkB', G(p, land).buffer(-0.01))], 'topo': True}, quiet)
        raise AssertionError('un fallo de GEOS no puede dar un guardado correcto')
    except SystemExit as e:
        assert 'AssertionFailed' not in str(e) and 'siguen pendientes' in str(e), e
    finally:
        ec.Project._save_once = real
    assert digest(p) == before, 'un guardado fallido cambió el mapa del proyecto'
    # 3. dos regiones nuevas que se pisan en un mismo guardado: mallas sanas y sin solaparse (se la queda la primera)
    p = fresh()
    g = G(p, land)
    x0, y0, x1, y1 = g.bounds
    half = lambda a, b: Polygon([(a, y0 - 1), (b, y0 - 1), (b, y1 + 1), (a, y1 + 1)]).intersection(g.buffer(-0.02))
    mid, ov = (x0 + x1) / 2, (x1 - x0) * 0.05
    rep = p.save({'modified': {}, 'assigns': [new_op('ChkC', half(x0 - 1, mid + ov), cut_all=True, fill=False),
                                              new_op('ChkD', half(mid - ov, x1 + 1), cut_all=True, fill=False)], 'topo': True}, quiet)
    assert not rep['errors'], rep['errors']
    p.reload()
    n = {p.rname(r.index): r.index for r in p.m['regions']}
    assert G(p, n['ChkC']).intersection(G(p, n['ChkD'])).area < 1e-9, 'las regiones nuevas se solapan'
    assert p._mesh_valid(p.m, n['ChkC']) and p._mesh_valid(p.m, n['ChkD'])
    # 3b. varias regiones nuevas que entre todas cubren una vieja entera: se guarda y la vieja se elimina (antes: «la malla quedaría rota»)
    p = fresh()
    g, old = G(p, land), p.rname(land)
    x0, y0, x1, y1 = g.bounds
    w = (x1 - x0) / 4
    rep = p.save({'modified': {}, 'assigns': [new_op('ChkT%d' % i, Polygon([(x0 + i * w - 0.01, y0 - 1), (x0 + (i + 1) * w + 0.01, y0 - 1), (x0 + (i + 1) * w + 0.01, y1 + 1),
                                                                             (x0 + i * w - 0.01, y1 + 1)]).intersection(g), cut_all=True, fill=False)
                                              for i in range(4)], 'topo': True, 'paint': False}, quiet)
    assert not rep['errors'] and [d['name'] for d in rep.get('deleted', [])] == [old], (rep['errors'], rep.get('deleted'))
    p.reload()
    n = {p.rname(r.index): r.index for r in p.m['regions']}
    assert old not in n and all(p._mesh_valid(p.m, n['ChkT%d' % i]) for i in range(4))
    # 4. la página: save() avisa siempre y solo borra los cambios pendientes cuando el servidor guardó
    page = open(os.path.join(HERE, 'editor', 'index.html'), encoding='utf-8').read()
    wrap = page[page.index('async function save() {'):page.index('async function saveRun() {')]
    run = page[page.index('async function saveRun() {'):]
    run = run[:re.search(r'\n(async )?function ', run).start()]     # solo el cuerpo de saveRun
    assert 'catch (e)' in wrap and 'alert(' in wrap and re.search(r'finally \{[^}]*updatePending\(\)', wrap), 'save() puede fallar en silencio'
    assert re.search(r'if \(saveRun\.saved\) \{[^}]*clearEdits\(\)', wrap) and wrap.count('clearEdits()') == 1
    assert run.count('clearEdits()') == 1 and re.search(r'if \(!r\.errors \|\| !r\.errors\.length\) \{[^}]*clearEdits\(\)', run), \
        'saveRun() borra los cambios pendientes fuera de la rama de éxito'
    print('OK: guardado robusto (GEOS, regiones nuevas que se pisan, cambios pendientes)')
finally:
    shutil.rmtree(tmp, ignore_errors=True)
