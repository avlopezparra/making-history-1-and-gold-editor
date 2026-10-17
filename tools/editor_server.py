"""Servidor local del editor de regiones de Making History.

Uso:  python editor_server.py [--proyecto CARPETA] [--puerto 8765]
Luego abrir http://localhost:8765 en el navegador.
"""
import argparse
import io
import json
import os
import sys
import threading
import traceback
import webbrowser
from collections import OrderedDict
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.environ.get('MH_ROOT') or os.path.join(HERE, '..'))   # datos (en el .exe, junto a él)
sys.path.insert(0, HERE)
import editor_core  # noqa: E402
import gamepaths  # noqa: E402
import progress  # noqa: E402

PROJECT = None
TILE_CACHE = OrderedDict()
TILE_LOCK = threading.Lock()
LOG = []


def log(msg):
    print(msg)
    LOG.append(str(msg))
    del LOG[:-200]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype='application/json; charset=utf-8', cache=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'max-age=3600' if cache else 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ('/', '/index.html'):
                return self.send(200, open(os.path.join(HERE, 'editor', 'index.html'), 'rb').read(), 'text/html; charset=utf-8')
            if u.path == '/api/meta':
                return self.send(200, {'regions': PROJECT.meta(), 'project': os.path.abspath(PROJECT.dir),
                                       'history': len([d for d in os.listdir(PROJECT.history) if d.isdigit()]),
                                       'can_redo': PROJECT.can_redo()})
            if u.path == '/api/regions':
                x0, y0, x1, y1 = map(float, q['bbox'][0].split(','))
                return self.send(200, {'type': 'FeatureCollection', 'features': PROJECT.features(x0, y0, x1, y1)})
            if u.path == '/api/pack/info':
                return self.send(200, {'pack': PROJECT.pack, 'decided': PROJECT.decided, 'packs': editor_core.Project.packs(),
                                       'users': editor_core.Project.pack_users()})
            if u.path == '/api/scenarios':
                return self.send(200, PROJECT.scenarios())
            if u.path == '/api/changelog/review':
                try:
                    return self.send(200, PROJECT.review_changelog(q.get('base', ['World'])[0]))
                except (ValueError, OSError) as e:
                    return self.send(200, {'error': str(e)})
            if u.path == '/api/changelog':
                return self.send(200, {'pack': PROJECT.pack, 'entries': PROJECT.changelog(), 'scenarios': PROJECT.scenarios(),
                                       'users': scenario_core.scenarios_using(PROJECT.pack)})
            if u.path == '/api/countries':
                return self.send(200, scenario_countries(q['scenario'][0]) if q.get('scenario') else [])
            if u.path == '/api/scenario':
                name = q['name'][0]
                if name in SCEN:   # escenario abierto en el editor: propietarios y colores con los cambios sin guardar
                    return self.send(200, live_scenario_info(SCEN[name]))
                return self.send(200, PROJECT.scenario_info(name))
            if u.path == '/api/log':
                return self.send(200, LOG[-50:])
            if u.path == '/api/game':
                return self.send(200, gamepaths.info())
            if u.path in ('/escenario', '/escenario.html'):
                return self.send(200, open(os.path.join(HERE, 'editor', 'escenario.html'), 'rb').read(), 'text/html; charset=utf-8')
            if u.path == '/api/scen/geojson_export':
                import geojson_io
                sel = [x for x in q['files'][0].split(',') if x in geojson_io.ALL_FILES] if q.get('files') else None
                name = q['name'][0] if q.get('name') and q['name'][0] else None
                with SCEN_LOCK:
                    data = geojson_io.export_zip(scenario(name) if name else None, PROJECT, sel, q.get('split', ['0'])[0] == '1',
                                                 q.get('base', ['World'])[0], q.get('lang', ['es'])[0], name, q.get('colors', ['0'])[0] == '1')
                return self.send(200, data, 'application/zip')
            if u.path.startswith('/api/scen/') or u.path.startswith('/api/files/'):
                return self.send(200, scen_get(u.path, {k: v[0] for k, v in q.items()}))
            if u.path == '/i18n_en.json':
                return self.send(200, open(os.path.join(HERE, 'editor', 'i18n_en.json'), 'rb').read(), 'application/json; charset=utf-8')
            if u.path == '/api/progress':
                return self.send(200, progress.get())
            if u.path in ('/i18n.js', '/busy.js'):
                return self.send(200, open(os.path.join(HERE, 'editor', u.path[1:]), 'rb').read(), 'text/javascript; charset=utf-8')
            if u.path == '/escenario_imagenes.js':
                return self.send(200, open(os.path.join(HERE, 'editor', 'escenario_imagenes.js'), 'rb').read(), 'text/javascript; charset=utf-8')
            if u.path in ('/imagenes', '/imagenes.html'):
                return self.send(200, open(os.path.join(HERE, 'editor', 'imagenes.html'), 'rb').read(), 'text/html; charset=utf-8')
            if u.path.startswith('/api/img/'):
                return img_get(self, u.path, {k: v[0] for k, v in q.items()})
            if u.path == '/api/terrain/export':
                import terrain_image
                bbox = [float(x) for x in q['bbox'][0].split(',')] if q.get('bbox') else None
                fmt = q.get('fmt', ['png'])[0]
                if q.get('terrain', ['0'])[0] == '1':      # además, una imagen con el color del tipo de terreno de cada región
                    with SCEN_LOCK:
                        sn = q.get('scenario', [''])[0]
                        data, bb, size = terrain_image.export_with_terrain(PROJECT, bbox, int(q.get('level', ['2'])[0]), fmt,
                                                                           scenario(sn) if sn else None, q.get('separate', ['0'])[0] == '1')
                    return self.send(200, data, 'application/zip')
                if q.get('separate', ['0'])[0] == '1':     # fondo, límites y fondo con límites en imágenes separadas (.zip)
                    data, bb, size = terrain_image.export_separate(PROJECT, bbox, int(q.get('level', ['2'])[0]), fmt)
                    return self.send(200, data, 'application/zip')
                data, bb, size = terrain_image.export_image(PROJECT, bbox, int(q.get('level', ['2'])[0]), fmt)
                return self.send(200, data, 'image/jpeg' if fmt == 'jpg' else 'image/png')
            if u.path == '/api/terrain/snap':
                import terrain_image
                bb = terrain_image.snap([float(x) for x in q['bbox'][0].split(',')])
                return self.send(200, {'bbox': bb})
            if u.path == '/api/preview':
                return self.send(200, preview(q['rel'][0]), 'image/png')
            if u.path.startswith('/tile/'):
                _, _, c, r, lv = u.path.split('/')
                c, r, lv = int(c), int(r), int(lv.split('.')[0])
                key = (c, r, lv, PROJECT_VERSION[0])
                with TILE_LOCK:
                    data = TILE_CACHE.get(key)
                if data is None:
                    img = PROJECT.tile_image(c, r, lv)
                    b = io.BytesIO()
                    img.save(b, 'JPEG', quality=88)
                    data = b.getvalue()
                    with TILE_LOCK:
                        TILE_CACHE[key] = data
                        while len(TILE_CACHE) > 400:
                            TILE_CACHE.popitem(last=False)
                return self.send(200, data, 'image/jpeg', cache=True)
            return self.send(404, {'error': 'no encontrado'})
        except Exception as e:
            traceback.print_exc()
            return self.send(500, {'error': str(e)})

    def do_POST(self):
        # avance de la acción para la barra de carga de la página (GET /api/progress)
        progress.begin()
        try:
            return self._post()
        finally:
            progress.end()

    def _post(self):
        u = urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        payload = json.loads(self.rfile.read(n) or b'{}')
        try:
            if u.path == '/api/regions/merge':
                # unificar regiones (selección múltiple): las demás se eliminan y su área, ciudades, población y unidades
                # pasan a 'into'; es un guardado del mapa como cualquier otro (y se registra en los escenarios)
                idx = {PROJECT.rname(g.index): g.index for g in PROJECT.m['regions']}
                into, names = payload.get('into'), [n for n in payload.get('regions') or [] if n != payload.get('into')]
                delete = bool(payload.get('delete'))
                if (into is None and not delete) or (into is not None and into not in idx) or not names or any(n not in idx for n in names):
                    return self.send(200, {'errors': ['regiones desconocidas para unificar o eliminar'], 'warnings': [], 'transfers': []})
                sea = lambda n: PROJECT.m['regions'][idx[n]].u_type == editor_core.SEA
                if into is not None and any(sea(n) and not sea(into) for n in names):
                    return self.send(200, {'errors': ['una región de mar solo puede pasar a otra región de mar o quedar vacía'], 'warnings': [], 'transfers': []})
                payload = {'modified': {}, 'assigns': [{'kind': 'delete_region', 'region': idx[n], 'into': idx[into] if into is not None else None} for n in names],
                           'centers': {}, 'topo': True, 'paint': True, 'register': True}
                u = u._replace(path='/api/save')
            if u.path == '/api/save':
                try:
                    rep = PROJECT.save(payload, log=log)
                except SystemExit as e:   # errores controlados del proceso de traspaso: no queda nada a medias
                    PROJECT._drop_pending_snapshot()
                    PROJECT.reload()
                    rep = {'errors': [str(e)], 'warnings': [], 'transfers': []}
                PROJECT_VERSION[0] += 1
                if rep.get('new_regions') and not rep.get('errors') and payload.get('register', True):
                    news = [{'nombre': c['name'], 'texto': c.get('text'), 'madre': c['mother'], 'pais': c.get('owner'), 'tipo': c['u_type'],
                             'fraccion': c.get('fraccion'), 'controlador': c.get('controller'), 'terreno': c.get('terrain'),
                             'mar': c.get('sea'), 'poblacion': c.get('pop_fractions'), 'historicos': c.get('historic'),
                             'poblacion_manual': c.get('population'), 'ciudad': c.get('city')} for c in rep['new_regions']]
                    rep['scenarios'] = register_regions(news, scenario_core.scenarios_using(PROJECT.pack), pf=progress.part(75, 99))
                    rep['conflicts'] = register_regions.conflicts
                    # el escenario abierto en el editor usa otro regionpack: la página pregunta si pasarlo a este
                    op = payload.get('scenario')
                    if op and op not in rep['scenarios'] and op in scenario_core.scenarios():
                        rep['open_other_pack'] = {'name': op, 'pack': scenario_core.pack_of(scenario(op))}
                if rep.get('deleted') and not rep.get('errors') and payload.get('register', True):
                    dele = delete_from_scenarios(rep['deleted'], scenario_core.scenarios_using(PROJECT.pack), pf=progress.part(75, 99))
                    PROJECT.note_deleted_population(delete_from_scenarios.pops)
                    rep.setdefault('scenarios', {})
                    for k, v in dele.items():
                        rep['scenarios'].setdefault(k, []).extend(v)
                return self.send(200, rep)
            if u.path == '/api/undo':
                rep = PROJECT.undo()
                PROJECT_VERSION[0] += 1
                if rep.get('removed_regions'):
                    rep['scenarios'] = unregister_regions(rep['removed_regions'], scenario_core.scenarios_using(PROJECT.pack))
                if rep.get('restored_regions'):
                    # deshacer un borrado: la region vuelve a los escenarios (desde la que la habia absorbido)
                    news = []
                    for x in rep['restored_regions']:
                        g_n, g_m = PROJECT.region_geom(x['nombre']), PROJECT.region_geom(x['madre']) if x.get('madre') else None
                        fr = g_n.area / (g_n.area + g_m.area) if g_n is not None and g_m is not None else 0
                        news.append({'nombre': x['nombre'], 'madre': x.get('madre'), 'mar': x.get('mar'), 'fraccion': fr,
                                     'pob_por_escenario': x.get('poblacion_por_escenario')})
                    rep.setdefault('scenarios', {}).update(register_regions(news, scenario_core.scenarios_using(PROJECT.pack)))
                return self.send(200, rep)
            if u.path == '/api/register_region':
                # region que existe en el mapa pero no en el escenario abierto (p. ej. si falló su registro)
                x = {'nombre': payload['name'], 'madre': payload.get('mother'), 'pais': payload.get('owner'),
                     'controlador': payload.get('controller'), 'terreno': payload.get('terrain'),
                     'poblacion': {payload['mother']: float(payload.get('pop_pct') or 0) / 100} if payload.get('mother') else None}
                out = register_regions([x], [payload['scenario']])
                return self.send(200, {'scenarios': out, 'conflicts': register_regions.conflicts})
            if u.path == '/api/cut_preview':
                return self.send(200, {'mothers': PROJECT.cut_preview(payload['polygon'], payload.get('sea'))})
            if u.path == '/api/redo':
                rep = PROJECT.redo(log=log)
                PROJECT_VERSION[0] += 1
                if rep.get('added_regions'):
                    rep['scenarios'] = register_regions(rep['added_regions'], scenario_core.scenarios_using(PROJECT.pack))
                return self.send(200, rep)
            if u.path == '/api/changelog/apply':
                news = [x for e in PROJECT.changelog() for x in e.get('regiones_nuevas', [])]
                if not news:
                    return self.send(200, {'scenarios': {}, 'msg': 'el changelog no tiene regiones nuevas'})
                return self.send(200, {'scenarios': register_regions(news, [payload['scenario']], check_pack=True)})
            if u.path == '/api/install':
                rep = PROJECT.install(payload.get('target', 'same'), payload.get('name'), payload.get('scenarios') or [],
                                      backup_root=scenario_core.BACKUP_ROOT)
                if rep.get('ok') and payload.get('apply_scenarios'):
                    # los escenarios elegidos al instalar pasan a usar el regionpack con sus regiones adecuadas, y se guardan
                    rep['scenarios'] = adapt_scenarios(payload['apply_scenarios'], rep['regionpack'], payload.get('pop_mode') or 'area')
                if rep.get('ok'):
                    rep['incompatibles'] = pack_incompatibles(rep['regionpack'])
                if rep.get('ok') and rep.get('nuevo_proyecto'):
                    select_pack(rep['regionpack'])      # se sigue editando el regionpack nuevo, en su propio proyecto
                    PROJECT_VERSION[0] += 1
                return self.send(200, rep)
            if u.path == '/api/region/rename':
                # nombre de una región: map.xml del proyecto (se instala con «Instalar») y los escenarios que usan el regionpack
                old, new, text = payload['region'], payload['new_name'].strip(), (payload.get('text') or '').strip() or None
                try:
                    PROJECT.rename_region(old, new, text)
                except (ValueError, OSError) as e:
                    return self.send(200, {'error': str(e)})
                PROJECT_VERSION[0] += 1
                out = {}
                names = scenario_core.scenarios_using(PROJECT.pack)
                with SCEN_LOCK:
                    for k, name in enumerate(names):
                        progress.part(10, 99)(k, len(names), 'Renombrando %s en «%s»' % (old, name))
                        try:
                            sc_ = scenario(name)
                            st = scenario_core.STORE
                            if any(x in st.dirty for x in sc_.paths):
                                out[name] = ['no se ha tocado: tiene cambios sin guardar en el editor de escenarios']
                                continue
                            notes = scenario_layers.rename_region(sc_, old, new, text)
                            res = st.save([x for x in sc_.paths if x in st.dirty])
                            if res['written']:
                                notes.append('guardado: %s' % ', '.join(os.path.basename(w) for w in res['written']))
                            out[name] = notes
                        except Exception as e:
                            traceback.print_exc()
                            out[name] = ['ERROR: %s' % e]
                log('región %s renombrada a %s' % (old, new))
                return self.send(200, {'ok': True, 'scenarios': out})
            if u.path == '/api/changelog/review':
                try:
                    r = PROJECT.apply_review(payload.get('keep'), payload.get('add'), payload.get('base', 'World'))
                except (ValueError, OSError) as e:
                    return self.send(200, {'error': str(e)})
                log('changelog revisado: quitadas %s; añadidas %s' % (', '.join(r['removed']) or '-', ', '.join(r['added']) or '-'))
                return self.send(200, r)
            if u.path == '/api/refresh':
                # Refrescar: el escenario se relee del disco aparte (/api/scen/reload); aquí, el regionpack del juego
                state = PROJECT.installed_state()
                if payload.get('load_installed') and state != 'same':
                    PROJECT.load_installed()
                    with TILE_LOCK:
                        TILE_CACHE.clear()
                    PROJECT_VERSION[0] += 1
                    threading.Thread(target=PROJECT.precompute, daemon=True).start()
                    log('regionpack %s recargado desde el juego' % PROJECT.pack)
                    return self.send(200, {'state': 'same', 'loaded': True})
                return self.send(200, {'state': state, 'pack': PROJECT.pack})
            if u.path == '/api/game/select':
                try:
                    return self.send(200, select_game(payload['game']))
                except ValueError as e:
                    return self.send(200, {'error': str(e)})
            if u.path == '/api/scen/convert':
                try:
                    return self.send(200, convert_scenario_api(payload))
                except (ValueError, KeyError, OSError) as e:
                    return self.send(200, {'error': str(e)})
            if u.path == '/api/geojson/analyze':
                # contornos que se van a importar como regiones: ¿existen ya? ¿de qué regiones sale su área?
                import geojson_compare
                return self.send(200, {'shapes': geojson_compare.analyze_shapes(PROJECT, payload.get('shapes') or [])})
            if u.path == '/api/lang':
                lang = 'en' if payload.get('lang') == 'en' else 'es'
                json.dump({'lang': lang}, open(os.path.join(ROOT, 'idioma.json'), 'w'))
                return self.send(200, {'lang': lang})
            if u.path == '/api/terrain/import':
                # imagen de fondo -> tiles DXT5 del proyecto (llega al juego con «Instalar»)
                import base64
                import terrain_image
                try:
                    data = base64.b64decode(payload['image'].split(',')[-1])
                    with PROJECT.lock:
                        tiles = terrain_image.import_image(PROJECT, data, [float(x) for x in payload['bbox']], log=log)
                except (ValueError, KeyError, OSError) as e:
                    return self.send(200, {'error': str(e)})
                PROJECT_VERSION[0] += 1
                return self.send(200, {'tiles': tiles})
            if u.path == '/api/pack/copy':
                # copia de seguridad del regionpack (y, si se pide, los escenarios elegidos pasan a usarla)
                with SCEN_LOCK:
                    busy = [n for n in payload.get('scenarios') or [] if n in SCEN and
                            any(x in scenario_core.STORE.dirty and os.path.basename(x) == 'scenario.xml' for x in SCEN[n].paths)]
                    if busy:
                        return self.send(200, {'error': 'scenario.xml con cambios sin guardar en el editor de escenarios: %s' % ', '.join(busy)})
                    try:
                        rep = editor_core.Project.copy_pack(PROJECT.pack, payload.get('name', '').strip(), payload.get('scenarios') or [],
                                                            scenario_core.BACKUP_ROOT,
                                                            PROJECT.dir if payload.get('project') else None,
                                                            project_dir(payload.get('name', '').strip()) if payload.get('project') else None)
                    except (ValueError, OSError) as e:
                        return self.send(200, {'error': str(e)})
                    for n in rep['escenarios']:      # el escenario se vuelve a leer del disco con su regionpack nuevo
                        if n in SCEN:
                            scenario_core.STORE.revert([x for x in SCEN[n].paths if os.path.basename(x) == 'scenario.xml'])
                            SCEN.pop(n, None)
                return self.send(200, rep)
            if u.path == '/api/pack/select':
                select_pack(payload['pack'])
                PROJECT_VERSION[0] += 1
                return self.send(200, {'ok': True, 'pack': PROJECT.pack})
            if u.path.startswith('/api/img/'):
                try:
                    return self.send(200, img_post(u.path, payload))
                except (ValueError, KeyError, OSError) as e:
                    return self.send(200, {'error': str(e)})
            if u.path.startswith('/api/scen/') or u.path.startswith('/api/files/'):
                try:
                    return self.send(200, scen_post(u.path, payload))
                except (ValueError, KeyError) as e:
                    return self.send(200, {'error': str(e)})
            return self.send(404, {'error': 'no encontrado'})
        except Exception as e:
            traceback.print_exc()
            PROJECT.reload()
            return self.send(500, {'errors': ['error interno: %s' % e], 'warnings': [], 'transfers': []})


PROJECT_VERSION = [0]

# ------------------------------------------------------------------ escenarios y archivos
import scenario_core  # noqa: E402
import scenario_layers  # noqa: E402
import scenario_create  # noqa: E402
import file_identify  # noqa: E402

SCEN = {}
SCEN_LOCK = threading.RLock()
DOCVIEW = None


def scenario(name):
    with SCEN_LOCK:
        if name not in SCEN:
            SCEN[name] = scenario_core.Scenario(name)
            scenario_layers.attach_external(SCEN[name])   # datos compartidos de ScenarioDefaults
        return SCEN[name]


def view_for(i):
    """El escenario al que pertenece un objeto (con sus reglas) o la vista generica."""
    global DOCVIEW
    path = scenario_core.STORE.doc_of.get(scenario_core.STORE.get(i), '')
    for s in SCEN.values():
        if path in s.paths:
            return s
    if DOCVIEW is None:
        DOCVIEW = scenario_core.DocView()
    return DOCVIEW


def live_scenario_info(s):
    P = scenario_core.prop
    with SCEN_LOCK:
        regions = {}
        for r in s.regions(sea=False):
            pop = P(r, 'nPopulation')
            regions[P(r, 'strName')] = {'owner': P(r, 'strOwner'), 'controller': P(r, 'strController'), 'terrain': P(r, 'strTerrain'),
                                       'population': int(pop) if pop and pop.isdigit() else None}
        colors = {P(p, 'strName'): '#' + (P(p, 'colCountryColor') or '#888888').lstrip('#')[:6] for p in s.all('Player')}
        return {'regions': regions, 'colors': colors}


def scenario_countries(name):
    d = os.path.join(scenario_core.SCEN_ROOT, name)
    return sorted(f[7:-4] for f in os.listdir(d) if f.startswith('country') and f.endswith('.xml')) if os.path.isdir(d) else []


def register_regions(news, names, check_pack=False, pf=None):
    """Registra regiones nuevas del mapa (entradas 'regiones_nuevas' del changelog) en los escenarios 'names'
    y los guarda (con copia de seguridad). Devuelve {escenario: notas}."""
    from shapely.geometry import Point
    import new_region
    out = {}
    register_regions.conflicts = []
    R = PROJECT.m['regions']
    ub = {PROJECT.rname(g.index): g.u_b for g in R}
    with SCEN_LOCK:
        for i, name in enumerate(names):
            (pf or progress.part(5, 99))(i, len(names), 'Registrando las regiones nuevas en «%s»' % name)
            notes = []
            try:
                s = scenario(name)
                st = scenario_core.STORE
                if any(x in st.dirty for x in s.paths):
                    out[name] = ['no se ha tocado: el escenario tiene cambios sin guardar en el editor de escenarios '
                                 '(guárdalos o reviértelos y usa «Aplicar changelog»)']
                    continue
                pk = scenario_core.pack_of(s)
                if check_pack and pk != PROJECT.pack:
                    notes.append('AVISO: este escenario usa el regionpack «%s», no «%s»: las regiones nuevas no existirán '
                                 'en su mapa hasta que use «%s»' % (pk, PROJECT.pack, PROJECT.pack))
                K = len(news) * 6 + 1     # pasos por escenario, para la barra de avance (cada acción con su texto)
                sp = lambda k, label: (pf or progress.part(5, 99))(i + k / float(K), len(names), '%s · %s' % (name, label))
                for j, x in enumerate(news):
                    nm, mother = x['nombre'], x.get('madre')
                    sp(j * 6, '%s: creando la región' % nm)
                    g_new = PROJECT.region_geom(nm)
                    terrain = x.get('terreno') or (new_region.TERRAIN_OF_TYPE.get(x.get('tipo')) if not mother else None)
                    try:
                        if x.get('mar'):
                            # region de mar nueva: waterWorld.xml y las flotas que quedan dentro
                            notes += scenario_layers.add_sea_region(s, nm, mother, x.get('texto'))
                            notes += scenario_layers.reassign_by_geometry(s, nm, g_new, sea=True)
                            continue
                        if mother:
                            g_m = PROJECT.region_geom(mother)
                            goes = None
                            if g_new is not None and g_m is not None:
                                goes = (lambda gn, gm: lambda px, py: gn.distance(Point(px, py)) < gm.distance(Point(px, py)))(g_new, g_m)
                            pops = x.get('poblacion')   # {region de origen: fraccion de sus habitantes} elegida en el dialogo
                            notes += scenario_core.add_new_region(s, nm, mother=mother, fraction=0 if (pops or (x.get('pob_por_escenario') or {}).get(name) is not None) else (x.get('fraccion') or 0),
                                                                  goes_to_new=goes, text=x.get('texto'), terrain=terrain)
                            sp(j * 6 + 2, '%s: repartiendo la población' % nm)
                            if pops:
                                notes += scenario_layers.move_population(s, nm, pops)
                            exact = (x.get('pob_por_escenario') or {}).get(name)
                            if exact is not None:
                                notes += scenario_layers.set_population_from(s, nm, mother, exact)
                            # dueño / controlador elegidos al crearla (si no, hereda los de la madre)
                            sp(j * 6 + 3, '%s: asignando propietario y controlador' % nm)
                            vals = {k: v for k, v in (('strOwner', x.get('pais')), ('strController', x.get('controlador') or x.get('pais'))) if v}
                            reg = next((r for r in s.regions(sea=False) if scenario_core.prop(r, 'strName') == nm), None)
                            if reg is not None and vals and any(scenario_core.prop(reg, k) != v for k, v in vals.items()):
                                if vals.get('strOwner') and vals['strOwner'] not in s.countries():
                                    notes.append('%s: el país %s no existe en este escenario; se queda con el de %s' % (nm, vals['strOwner'], mother))
                                else:
                                    notes += ['%s: %s' % (nm, n) for n in s.update(st.eid(reg), vals)]
                                    notes.append('%s: propietario %s, controlador %s' % (nm, vals.get('strOwner', '-'), vals.get('strController', '-')))
                        else:
                            owner = x.get('pais')
                            if not owner:
                                notes.append('%s: sin país asignado, no se registra' % nm)
                                continue
                            # poblacion: densidad media de las regiones del pais por el area de la nueva
                            P = scenario_core.prop
                            regs = [r for r in s.regions(sea=False) if P(r, 'strOwner') == owner]
                            pop = sum(int(P(r, 'nPopulation') or 0) for r in regs if (P(r, 'nPopulation') or '').isdigit())
                            area = sum(ub.get(P(r, 'strName'), 0) for r in regs)
                            population = int(round(pop / area * ub.get(nm, 0))) if area else 0
                            if x.get('poblacion_manual') is not None:      # habitantes puestos a mano al crearla
                                population = int(x['poblacion_manual'])
                            notes += scenario_core.add_new_region(s, nm, owner=owner, terrain=terrain, population=population,
                                                                  text=x.get('texto'))
                        if mother and x.get('poblacion_manual') is not None and not x.get('poblacion'):
                            notes += scenario_layers.set_region_population(s, nm, x['poblacion_manual'])
                        notes += scenario_layers._city_and_liberate(s, nm, x, g_new)    # ciudad pedida + país rendido → liberado
                        # países históricos elegidos al crearla (si no se eligieron, los de la madre)
                        if x.get('historicos') is not None:
                            sp(j * 6 + 4, '%s: asignando los países históricos' % nm)
                            notes += scenario_layers.set_historic(s, nm, x['historicos'])
                        # ciudades, recursos y unidades dentro de la region nueva (de todas las regiones recortadas)
                        sp(j * 6 + 5, '%s: pasando ciudades, recursos y unidades' % nm)
                        notes += scenario_layers.reassign_by_geometry(s, nm, g_new)
                        for c in scenario_layers.unit_conflicts(s, nm):
                            c['scenario'] = name
                            c['nearest'] = nearest_region_of(s, c['owner'], c['xy'], exclude=nm, port=c['kind'] == 'Fleet')
                            register_regions.conflicts.append(c)
                            notes.append('AVISO: %s %s es de %s y queda en %s (de %s): elige qué hacer' % (
                                {'Army': 'el ejército', 'AirForce': 'la aviación', 'Fleet': 'la flota'}[c['kind']], c['unit'], c['owner'], nm, c['region_owner']))
                    except ValueError as e:
                        notes.append('ERROR: %s' % e)
                sp(K - 1, 'guardando los archivos del escenario')
                res = st.save([p for p in s.paths if p in st.dirty])
                if res['written']:
                    notes.append('guardado: %s' % ', '.join(os.path.basename(w) for w in res['written']))
            except Exception as e:
                traceback.print_exc()
                notes.append('ERROR: %s' % e)
            out[name] = notes
    return out


def delete_from_scenarios(deleted, names, pf=None):
    """Quita de los escenarios las regiones borradas del mapa. Si su área pasó a una región de tierra, sus ciudades,
    recursos, población y unidades pasan a ella; si no, las unidades van a la región más cercana de su país."""
    P = scenario_core.prop
    out = {}
    delete_from_scenarios.pops = {}
    with SCEN_LOCK:
        for k, name in enumerate(names):
            (pf or progress.part(5, 99))(k, len(names), 'Quitando las regiones borradas de «%s»' % name)
            notes = []
            try:
                s = scenario(name)
                st = scenario_core.STORE
                if any(x in st.dirty for x in s.paths):
                    out[name] = ['no se ha tocado: tiene cambios sin guardar en el editor de escenarios']
                    continue
                land = {P(r, 'strName'): r for r in s.regions(sea=False)}
                for d in deleted:
                    nm, into = d['name'], d.get('into')
                    if d.get('sea'):
                        for g in s.all('Fleet'):
                            if P(g, 'strRegion') == nm:
                                if into:
                                    st.set_prop(g, 'strRegion', into)
                                notes.append('flota %s (%s) pasa a %s' % (P(g, 'strName'), P(g, 'strOwner'), into or '¿?'))
                        notes += scenario_core.remove_new_region(s, nm, into)
                        continue
                    if nm not in land:
                        notes.append('%s: no estaba en el escenario' % nm)
                        continue
                    pop_ = P(land[nm], 'nPopulation')
                    if pop_ and pop_.isdigit():
                        delete_from_scenarios.pops.setdefault(nm, {})[name] = int(pop_)
                    if into in land:
                        notes += scenario_core.remove_new_region(s, nm, into)
                        notes.append('%s se incorpora a %s (ciudades, recursos, población y unidades)' % (nm, into))
                    else:
                        for t in ('Army', 'AirForce', 'Fleet'):
                            for g in s.all(t):
                                if P(g, 'strRegion') == nm:
                                    near = nearest_region_of(s, P(g, 'strOwner'), scenario_core.parse_vec(P(g, 'vecPosition')), exclude=nm, port=t == 'Fleet')
                                    if near:
                                        st.set_prop(g, 'strRegion', near['name'])
                                        notes.append('%s %s (%s) se traslada a %s' % (t, P(g, 'strName'), P(g, 'strOwner'), near['name']))
                        lost = [P(c, 'strName') for c in scenario_core.objs(land[nm]) if c.get('type') in ('City', 'Producer')]
                        notes += scenario_core.remove_new_region(s, nm, None)
                        if lost:
                            notes.append('AVISO: se pierden con %s: %s' % (nm, ', '.join(lost)))
                res = st.save([p for p in s.paths if p in st.dirty])
                if res['written']:
                    notes.append('guardado: %s' % ', '.join(os.path.basename(w) for w in res['written']))
            except Exception as e:
                traceback.print_exc()
                notes.append('ERROR: %s' % e)
            out[name] = notes
    return out


def adapt_scenarios(names, pack, pop_mode='area'):
    """Pasa los escenarios al regionpack 'pack' añadiendo y quitando las regiones necesarias, y los guarda.
    Los que tienen cambios sin guardar en el editor de escenarios no se tocan."""
    out = {}
    with SCEN_LOCK:
        for k, name in enumerate(names):
            progress.part(60, 99)(k, len(names), 'Adecuando «%s» al regionpack %s' % (name, pack))
            try:
                s = scenario(name)
                st = scenario_core.STORE
                if any(x in st.dirty for x in s.paths):
                    out[name] = ['no se ha tocado: tiene cambios sin guardar en el editor de escenarios']
                    continue
                notes = scenario_layers.pack_sync_apply(s, pack, True, pop_mode)['notes']
                res = st.save([x for x in s.paths if x in st.dirty])
                if res['written']:
                    notes.append('guardado: %s' % ', '.join(os.path.basename(w) for w in res['written']))
                out[name] = notes
            except Exception as e:
                traceback.print_exc()
                out[name] = ['ERROR: %s' % e]
    return out


def pack_incompatibles(pack):
    """{escenario: {'faltan': [...], 'sobran': [...]}} de los escenarios que usan 'pack' y no cuadran con su mapa."""
    out = {}
    with SCEN_LOCK:
        for name in scenario_core.scenarios_using(pack):
            try:
                plan = scenario_layers.pack_sync_plan(scenario(name), pack)
            except Exception as e:
                out[name] = {'error': str(e)}
                continue
            if plan['add'] or plan['remove']:
                out[name] = {'faltan': [x['name'] for x in plan['add']], 'sobran': [x['name'] for x in plan['remove']]}
    return out


def nearest_region_of(s, country, xy, exclude=None, port=False):
    """Región de tierra de 'country' más cercana al punto xy: {name, xy (centro)} o None."""
    from shapely.geometry import Point
    if not xy:
        return None
    P = scenario_core.prop
    centers = {PROJECT.rname(g.index): (g.cx, g.cy) for g in PROJECT.m['regions']}
    best = None
    for r in s.regions(sea=False):
        n = P(r, 'strName')
        if P(r, 'strOwner') != country or n == exclude:
            continue
        if port and not any(c.get('type') == 'City' and P(c, 'strPortForRegion') for c in scenario_core.objs(r)):
            continue        # una flota solo puede atracar en una region con puerto
        g = PROJECT.region_geom(n)
        if g is None:
            continue
        d = g.distance(Point(*xy))
        if best is None or d < best[0]:
            best = (d, n)
    return {'name': best[1], 'xy': list(centers.get(best[1], xy))} if best else None


def unregister_regions(removed, names):
    out = {}
    with SCEN_LOCK:
        for k, name in enumerate(names):
            progress.part(5, 99)(k, len(names), 'Quitando las regiones deshechas de «%s»' % name)
            try:
                s = scenario(name)
                st = scenario_core.STORE
                if any(x in st.dirty for x in s.paths):
                    out[name] = ['no se ha tocado: tiene cambios sin guardar en el editor de escenarios']
                    continue
                notes = []
                for x in removed:
                    notes += scenario_core.remove_new_region(s, x['nombre'], x.get('madre'), x.get('poblacion'))
                    # ciudades, recursos y unidades vuelven a la region de origen donde estan (si salio de varias)
                    for m in x.get('madres') or []:
                        if m != x.get('madre'):
                            notes += scenario_layers.reassign_by_geometry(s, m, PROJECT.region_geom(m))
                st.save([p for p in s.paths if p in st.dirty])
                out[name] = notes
            except Exception as e:
                traceback.print_exc()
                out[name] = ['ERROR: %s' % e]
    return out


def map_info():
    """Regiones del mapa del proyecto: {nombre: es_mar} y vecinos por nombre (para validar)."""
    R = PROJECT.m['regions']
    nm = PROJECT.rname
    names = {nm(g.index): g.u_type == 0 for g in R}
    adj = {nm(g.index): {nm(n) for n in g.neighbors} for g in R}
    return names, adj


def scen_get(path, q):
    with SCEN_LOCK:
        if path == '/api/scen/list':
            return {'scenarios': scenario_core.scenarios(), 'loaded': sorted(SCEN)}
        if path == '/api/scen/tabs':
            s = scenario(q['name'])
            info = {}
            sx = s.all('Scenario', lambda f: f == 'scenario.xml')
            if sx:
                disp = next((o for o in sx[0].iter('object') if o.get('type') == 'ScenarioDisplaySettings'), None)
                info['regionpack'] = scenario_core.prop(disp, 'strMapName') if disp is not None else None
            info['partisans'] = scenario_core.partisans_state(s)
            info['packs'] = editor_core.Project.packs()
            info['tilt'] = scenario_layers.tilt_state(s)
            info['external'] = [os.path.basename(x) for x in getattr(s, 'external', [])]
            return {'tabs': [{'key': k, 'label': l} for k, l, _, _ in s.tabs()], 'info': info,
                    'dirty': sorted(os.path.basename(p) for p in scenario_core.STORE.dirty)}
        if path == '/api/scen/tab':
            return scenario(q['name']).tab_rows(q['tab'])
        if path == '/api/scen/options':
            return scenario(q['name']).options()
        if path == '/api/scen/obj':
            return view_for(q['id']).detail(q['id'])
        if path == '/api/scen/pack_sync':
            r = scenario_layers.pack_sync_plan(scenario(q['name']), q['pack'])
            r['poblacion_ref'] = bool(scenario_layers.pack_pop_table(q['pack']))
            return r
        if path == '/api/scen/historic_of':
            # para el diálogo de región nueva: países históricos posibles y los que ya incluyen las regiones de origen
            s = scenario(q['name'])
            P = scenario_core.prop
            src = set(x for x in (q.get('regions') or '').split('|') if x)
            hist = {}
            for h in s.all('HistoricCountry'):
                hist.setdefault(P(h, 'strCountry'), set()).update(P(k, 'strRegion') for k in scenario_core.objs(h))
            return {'all': sorted(set(hist) | set(s.countries())), 'with': sorted(c for c, rs in hist.items() if rs & src)}
        if path == '/api/scen/traits':
            return scenario_layers.ai_traits(scenario(q['name']), q['country'])
        if path == '/api/scen/claims':
            return scenario_layers.claims(scenario(q['name']), q['country'])
        if path == '/api/scen/find_region':
            sc_ = scenario(q['name'])
            r = next((x for x in sc_.regions() if scenario_core.prop(x, 'strName') == q['region']), None)
            return {'id': scenario_core.STORE.eid(r)} if r is not None else {}
        if path == '/api/scen/relations':
            return scenario_layers.relations(scenario(q['name']), [x for x in (q.get('countries') or '').split('|') if x])
        if path == '/api/scen/pack_check':
            # comprobación rápida para el indicador del editor de regiones: ¿cuadra el escenario con este regionpack?
            s = scenario(q['name'])
            missing, extra = scenario_layers.pack_mismatch(s, q['pack'])
            return {'uses': scenario_core.pack_of(s), 'pack': q['pack'], 'missing': missing, 'extra': extra,
                    'poblacion_ref': bool(scenario_layers.pack_pop_table(q['pack']))}
        if path == '/api/scen/mapdata':
            return scenario_layers.mapdata(scenario(q['name']))
        if path == '/api/scen/points':
            # ciudades y productores por su vecPosition; ejercitos, aviacion y flotas en el centro de su region
            s = scenario(q['name'])
            P = scenario_core.prop
            centers = {PROJECT.rname(g.index): (g.cx, g.cy) for g in PROJECT.m['regions']}
            pts = []

            def pos(e):
                m = [float(x) for x in (P(e, 'vecPosition') or '').strip('[]').split(',')[:2] if x.strip()]
                return m if len(m) == 2 else None
            for e in s.all('City'):
                xy = pos(e)
                if xy:
                    pts.append({'id': scenario_core.STORE.eid(e), 'kind': 'city', 'x': xy[0], 'y': xy[1], 'label': P(e, 'strName'),
                                'owner': P(e, 'strOwner')})
            for e in s.all('Producer'):
                xy = pos(e)
                if xy:
                    pts.append({'id': scenario_core.STORE.eid(e), 'kind': 'producer', 'res': P(e, 'strResource'), 'x': xy[0], 'y': xy[1],
                                'label': '%s (%s)' % (P(e, 'strName') or '', P(e, 'strResource')), 'owner': P(e, 'strOwner')})
            off = {'Army': (0, -0.25), 'AirForce': (0.3, 0.15), 'Fleet': (0, 0)}
            for t, kind in (('Army', 'army'), ('AirForce', 'air'), ('Fleet', 'fleet')):
                for e in s.all(t):
                    xy = pos(e)   # las unidades tienen vecPosition; si no, el centro de su region
                    c = (xy[0] - off[t][0], xy[1] - off[t][1]) if xy else centers.get(P(e, 'strRegion'))
                    if c:
                        n = sum(int(P(u, 'nNumber')) if (P(u, 'nNumber') or '').isdigit() else 1 for u in scenario_core.objs(e))
                        pts.append({'id': scenario_core.STORE.eid(e), 'kind': kind, 'x': c[0] + off[t][0], 'y': c[1] + off[t][1],
                                    'label': '%s · %s (%d)' % (P(e, 'strOwner'), P(e, 'strName') or t, n), 'owner': P(e, 'strOwner')})
            return {'points': pts}
        if path == '/api/scen/ai':
            return scenario_layers.ai_summary(scenario(q['name']), q['country'])
        if path == '/api/scen/validate':
            names, adj = map_info()
            sc_ = scenario(q['name'])
            return {'issues': sc_.validate(names, adj) + scenario_layers.surrendered_issues(sc_) + scenario_layers.diplomacy_issues(sc_)}
        if path == '/api/files/list':
            return file_identify.list_dir(q.get('rel', ''))
        if path == '/api/files/identify':
            return file_identify.identify(file_identify.resolve(q['rel']))
        if path == '/api/files/tree':
            if q.get('id'):
                el = scenario_core.STORE.get(q['id'])
            else:
                el = scenario_core.STORE.open(file_identify.resolve(q['rel'])).getroot()
            if el.tag != 'object':
                return {'id': None, 'type': el.tag, 'label': os.path.basename(q.get('rel', '')), 'children':
                        [scenario_core.STORE.tree(c, 0) for c in scenario_core.objs(el)]}
            return scenario_core.STORE.tree(el, 1)
    raise KeyError(path)


def scen_post(path, p):
    with SCEN_LOCK:
        st = scenario_core.STORE
        if path == '/api/scen/update':
            v = view_for(p['id'])
            notes = v.update(p['id'], dict(p.get('values') or {}), p.get('move_children', True))
            return {'notes': notes, 'detail': v.detail(p['id'])}
        if path == '/api/scen/duplicate':
            new = st.duplicate(st.get(p['id']))
            return {'id': st.eid(new), 'detail': view_for(st.eid(new)).detail(st.eid(new))}
        if path == '/api/scen/remove':
            el = st.get(p['id'])
            par = st.parent.get(el)
            st.remove(el)
            return {'ok': True, 'parent': st.eid(par) if par is not None and par.tag == 'object' else None}
        if path == '/api/scen/set_owner':
            # cambiar dueno/controlador de una region desde el mapa (sin tocar su forma)
            s = scenario(p['name'])
            reg = next((r for r in s.regions(sea=False) if scenario_core.prop(r, 'strName') == p['region']), None)
            if reg is None:
                raise ValueError('la región «%s» no tiene datos en el escenario (¿es de mar?)' % p['region'])
            values = {}
            if p.get('owner'):
                values['strOwner'] = p['owner']
            if p.get('controller'):
                values['strController'] = p['controller']
            notes = s.update(st.eid(reg), values)
            if p.get('owner'):     # un país rendido que recibe una región deja de estarlo y su capital pasa a una ciudad de ella
                notes += scenario_layers.unsurrender(s, p['owner'], p['region'])
            return {'notes': notes, 'dirty': sorted(os.path.basename(x) for x in st.dirty if x in s.paths)}
        if path == '/api/scen/dirty':
            s = scenario(p['name'])
            return {'dirty': sorted(os.path.basename(x) for x in st.dirty if x in s.paths)}
        if path == '/api/scen/partisans':
            s = scenario(p['name'])
            return {'notes': scenario_core.set_partisans(s, bool(p['enable'])), 'partisans': scenario_core.partisans_state(s),
                    'dirty': sorted(os.path.basename(x) for x in st.dirty)}
        if path == '/api/scen/war_event':
            s = scenario(p['name'])
            i, notes = scenario_core.create_war_event(s, p['attacker'], p['target'], p['date'], p.get('pct', 80))
            return {'id': i, 'notes': notes, 'detail': s.detail(i)}
        if path == '/api/scen/historic_toggle':
            s = scenario(p['name'])
            r = scenario_layers.toggle_historic(s, p['country'], p['region'])
            r['dirty'] = sorted(os.path.basename(x) for x in st.dirty if x in s.paths)
            return r
        if path == '/api/scen/alliance_toggle':
            s = scenario(p['name'])
            r = scenario_layers.toggle_alliance(s, p['alliance'], p['country'])
            r['dirty'] = sorted(os.path.basename(x) for x in st.dirty if x in s.paths)
            return r
        if path == '/api/scen/set_string':
            s = scenario(p['name'])
            scenario_layers.set_string(s, p['sid'], p['value'])
            return {'dirty': sorted(os.path.basename(x) for x in st.dirty if x in s.paths)}
        if path == '/api/scen/geojson_import':
            import geojson_io
            s = scenario(p['name'])
            r = geojson_io.import_fc(s, PROJECT, p['geojson'], p.get('types'), opts=p.get('opts'))
            r['dirty'] = sorted(os.path.basename(x) for x in st.dirty if x in s.paths)
            return r
        if path == '/api/scen/bulk':
            # acciones de selección múltiple (regiones o países)
            s = scenario(p['name'])
            a, L_ = p['action'], scenario_layers
            if a == 'regions':
                notes = L_.bulk_regions(s, p['regions'], p.get('values') or {})
            elif a == 'historic':
                notes = L_.add_to_historic(s, p['country'], p['regions'])
            elif a == 'alliance':
                notes = L_.alliance_add(s, p['countries'], p.get('alliance'), p.get('new_name'))['notes']
            elif a == 'war':
                notes = L_.create_wars(s, p['attacker'], p['defenders'], p.get('war_name'))
            elif a == 'war_event':
                notes = []
                for d in p['defenders']:
                    if d != p['attacker']:
                        notes += scenario_core.create_war_event(s, p['attacker'], d, p['date'], p.get('pct', 80))[1]
            elif a in ('trade', 'aid'):
                notes = L_.create_flows(s, p['origin'], p['targets'], a)
            elif a == 'elements':
                notes = L_.bulk_elements(s, p['ids'], p['op'], p.get('field'), p.get('value'))
            elif a == 'dip':
                notes = L_.fix_diplomacy(s, [{'a': x['a'], 'b': x['b'], 'value': x['value']} for x in p['pairs']])
            elif a == 'country_transfer':
                notes = L_.transfer_assets(s, p['from'], p['to'], bool(p.get('regions', True)), bool(p.get('units', True)))
            elif a == 'country_delete':
                notes = []
                for n in p['countries']:
                    notes += L_.delete_country(s, n, p.get('to'))
            elif a == 'country_surrender':
                notes = L_.make_surrendered(s, p['country'], p['capital'], p.get('to'))
            elif a == 'protect':
                notes = scenario_core.create_protection_event(s, p['protector'], p['protected'], p['aggressor'], p.get('reaction', 'war'), p.get('pct', 30))[1]
            elif a == 'embargo':
                notes = []
                for t in p['targets']:
                    if t != p['origin']:
                        notes += scenario_core.create_embargo_event(s, p['origin'], t, p.get('turn', 1))[1]
            else:
                raise ValueError('acción desconocida: %s' % a)
            return {'notes': notes, 'dirty': sorted(os.path.basename(x) for x in st.dirty if x in s.paths)}
        if path == '/api/scen/resolve_units':
            # unidades de otro país que quedaron en una región nueva: cambiar de país o trasladar
            out = []
            touched = set()
            for it in p['items']:
                s = scenario(it['scenario'])
                out.append(scenario_layers.resolve_unit(s, it['id'], it['action'], it.get('target'), it.get('xy')))
                touched.add(it['scenario'])
            for n in touched:
                s = scenario(n)
                st.save([x for x in s.paths if x in st.dirty])
            return {'notes': out}
        if path == '/api/scen/discard_all':
            # la pagina se ha (re)cargado: lo no guardado se descarta y todo se vuelve a leer de los archivos guardados
            names = sorted(SCEN)
            dirty = sorted({os.path.basename(x) for x in st.dirty})
            st.revert()
            SCEN.clear()
            return {'discarded': dirty, 'scenarios': names}
        if path == '/api/scen/reload':
            # Refrescar: releer el escenario del disco (descarta lo que hay en memoria) y comprobar su regionpack
            name = p['name']
            if name in SCEN:
                dirty = sorted(os.path.basename(x) for x in st.dirty if x in SCEN[name].paths)
                if dirty and not p.get('force'):
                    return {'needs_confirm': True, 'dirty': dirty}
                st.revert([x for x in SCEN[name].paths if x in st.docs])
                SCEN.pop(name, None)
            s = scenario(name)
            pack = scenario_core.pack_of(s)
            out = {'pack': pack, 'dirty': []}
            try:
                plan = scenario_layers.pack_sync_plan(s, pack)
                out['missing'] = [x['name'] for x in plan['add']]
                out['poblacion_ref'] = bool(scenario_layers.pack_pop_table(pack))
                out['extra'] = [x['name'] for x in plan['remove']]
            except ValueError as e:
                out['pack_error'] = str(e)
            iss = s.validate()
            out['errors'] = sum(1 for i in iss if i['level'] == 'error')
            out['warnings'] = len(iss) - out['errors']
            return out
        if path == '/api/scen/pack_sync':
            s = scenario(p['name'])
            r = scenario_layers.pack_sync_apply(s, p['pack'], bool(p.get('switch', True)), p.get('pop_mode') or 'area')
            r['dirty'] = sorted(os.path.basename(x) for x in st.dirty if x in s.paths)
            return r
        if path == '/api/scen/create':
            # objeto nuevo: ciudad, recurso (productor) o ejército (como «Add» de ed.exe)
            s = scenario(p['name'])
            L_, k, SC_ = scenario_layers, p['kind'], scenario_create
            if k == 'city':
                eid, notes = L_.create_city(s, p['obj_name'], float(p['x']), float(p['y']), p.get('ipus', 1), p.get('population', 0),
                                            p.get('display'), p.get('port') or None)
            elif k == 'producer':
                eid, notes = L_.create_producer(s, p['obj_name'], p['resource'], float(p['x']), float(p['y']), p.get('output', 1))
            elif k == 'army':
                eid, notes = L_.create_army(s, p['owner'], p['obj_name'], p['region'], p.get('units') or [])
            elif k == 'country':
                eid, notes = SC_.create_country(s, p['obj_name'], p.get('template') or None, p.get('color') or None, p.get('ctype') or 'Minor',
                                                p.get('gov') or None, p.get('flag') or None, p.get('capital') or None, p.get('regions') or [],
                                                p.get('description'))
            elif k == 'fleet':
                eid, notes = SC_.create_fleet(s, p['owner'], p['obj_name'], p['region'], p.get('units') or [], p.get('city') or None)
            elif k == 'alliance':
                eid, notes = SC_.create_alliance(s, p['obj_name'], p['leader'], p.get('members') or [])
            elif k == 'war':
                eid, notes = None, SC_.create_war(s, p.get('attackers') or [], p.get('defenders') or [], p.get('obj_name') or None,
                                                  p.get('off_alliance') or None, p.get('def_alliance') or None)
            elif k == 'access':
                eid, notes = SC_.create_access(s, p['a'], p['b'], bool(p.get('land', True)), bool(p.get('air', True)), bool(p.get('sea', True)),
                                               p.get('date') or None)
            elif k == 'copy':
                eid, notes = SC_.copy_template(s, p['what'], p['source'], p['obj_name'], p.get('display') or None, bool(p.get('bundle', True)))
            else:
                raise ValueError('tipo de objeto desconocido: %s' % k)
            return {'id': eid, 'notes': notes, 'dirty': sorted(os.path.basename(x) for x in st.dirty if x in s.paths)}
        if path == '/api/scen/fix_diplomacy':
            s = scenario(p['name'])
            notes = scenario_layers.fix_diplomacy(s, p['items'])
            return {'notes': notes, 'dirty': sorted(os.path.basename(x) for x in st.dirty if x in s.paths)}
        if path == '/api/scen/claims_set':
            s = scenario(p['name'])
            notes = scenario_layers.set_claims(s, p['country'], p.get('list'), p.get('regions') or [])
            return {'notes': notes, 'dirty': sorted(os.path.basename(x) for x in st.dirty if x in s.paths)}
        if path == '/api/scen/fix_capitals':
            s = scenario(p['name'])
            notes = scenario_layers.auto_capitals(s, p.get('countries'))
            return {'notes': notes, 'dirty': sorted(os.path.basename(x) for x in st.dirty if x in s.paths)}
        if path == '/api/scen/create_info':
            # listas para el diálogo de «Añadir»: recursos, plantillas de unidad, países, regiones de mar y tierra
            s = scenario(p['name'])
            P = scenario_core.prop
            return {'resources': sorted({P(x, 'strResource') for x in s.all('Producer') if P(x, 'strResource')}),
                    'units': sorted(P(t, 'strName') for t in s.all('UnitTemplate')),
                    'countries': sorted(s.countries()), 'land': sorted(P(r, 'strName') for r in s.regions(sea=False)),
                    'sea': sorted(P(r, 'strName') for r in s.regions(sea=True)),
                    'navy': sorted(P(t, 'strName') for t in s.all('UnitTemplate') if P(t, 'eType') == 'UNIT_TYPE_NAVY'),
                    'alliances': sorted(({'id': P(a, 'strINITAllianceName'), 'name': P(a, 'strDisplayName')} for a in s.all('Alliance')), key=lambda x: x['name'] or ''),
                    'govs': sorted({P(c, 'strGovType') for c in s.countries().values() if P(c, 'strGovType')}),
                    'outputs': sorted(P(e, 'strName') for e in s.all_prefix('FactoryOutput')),
                    'research': sorted(P(e, 'strName') for e in s.all_prefix('ResearchProj') if scenario_core.STORE.parent[e].get('type') == 'ResearchProjectSet'),
                    'templates': sorted(n for n in s.countries() if not scenario_layers._owned(s, n)[0] and not scenario_layers._owned(s, n)[1]),
                    'cities': sorted(({'name': P(c, 'strName'), 'region': P(scenario_core.STORE.parent.get(c), 'strName'), 'owner': P(c, 'strOwner')} for c in s.all('City')), key=lambda x: x['name'])}
        if path == '/api/scen/move_point':
            # mover una ciudad o recurso a otro punto del mapa (si cae en otra región, pasa a ella con su dueño)
            s = scenario(p['name'])
            el, x, y = st.get(p['id']), float(p['x']), float(p['y'])
            if el.get('type') not in ('City', 'Producer'):
                raise ValueError('solo se pueden mover ciudades y recursos')
            reg, rname = scenario_layers._land_region_at(s, x, y)
            st.set_prop(el, 'vecPosition', scenario_layers._vec(x, y))
            notes = ['%s %s → %.4f, %.4f' % (el.get('type'), scenario_core.prop(el, 'strName'), x, y)]
            if st.parent[el] is not reg:
                notes += s.update(p['id'], {'__region': rname})
            return {'notes': notes, 'dirty': sorted(os.path.basename(z) for z in st.dirty if z in s.paths)}
        if path == '/api/scen/region_at':
            s = scenario(p['name'])
            try:
                reg, n = scenario_layers._land_region_at(s, float(p['x']), float(p['y']))
                return {'region': n, 'owner': scenario_core.prop(reg, 'strOwner')}
            except ValueError as e:
                return {'error': str(e)}
        if path == '/api/scen/tilt':
            s = scenario(p['name'])
            notes = scenario_layers.set_tilt(s, bool(p['enable']))
            return {'notes': notes, 'dirty': sorted(os.path.basename(x) for x in st.dirty if x in s.paths)}
        if path == '/api/scen/playable':
            s = scenario(p['name'])
            notes = scenario_layers.set_playable(s, p['countries'])
            return {'notes': notes, 'dirty': sorted(os.path.basename(x) for x in st.dirty if x in s.paths)}
        if path == '/api/scen/set_pack':
            # cambiar de regionpack también adecua las regiones: si no coinciden con su mapa, el juego no carga el escenario
            s = scenario(p['name'])
            if p.get('only_switch'):
                notes = scenario_layers.set_pack(s, p['pack'])
            else:
                notes = scenario_layers.pack_sync_apply(s, p['pack'], True, p.get('pop_mode') or 'area')['notes']
            return {'notes': notes, 'dirty': sorted(os.path.basename(x) for x in st.dirty if x in s.paths)}
        if path == '/api/scen/save' and p.get('name'):
            s = scenario(p['name'])
            ext = scenario_layers.external_dirty(s)
            if ext and not p.get('mode'):
                # datos compartidos de ScenarioDefaults: que el usuario elija
                return {'needs_choice': True, 'defaults': [
                    {'file': os.path.basename(x), 'users': scenario_layers.users_of(x)} for x in ext]}
            if not p.get('ignore_pack'):
                # no guardar sin avisar un escenario cuyas regiones no cuadran con su regionpack (el juego no lo cargaría)
                pack = scenario_core.pack_of(s)
                try:
                    missing, extra = scenario_layers.pack_mismatch(s, pack)
                except ValueError:
                    missing, extra = [], []
                if missing or extra:
                    return {'needs_fit': True, 'pack': pack, 'missing': missing, 'extra': extra}
            if p.get('mode') == 'new':
                r = scenario_layers.save_as_new(s, p['new_name'])
                st.revert([x for x in s.paths if x in st.dirty])
                SCEN.pop(p['name'], None)
                return r
            r = st.save([x for x in s.paths if x in st.dirty])
            in_game = os.path.normcase(os.path.abspath(scenario_core.SCEN_ROOT)).startswith(os.path.normcase(os.path.abspath(scenario_core.GAME)))
            if not scenario_layers.tilt_state(s) and in_game:
                cam = scenario_layers.ensure_flat_camera()   # camara sin inclinacion (archivo nuevo, no toca WorldUnified)
                if cam:
                    r['written'].append(os.path.relpath(cam, scenario_core.GAME))
            return r
        if path == '/api/scen/save':
            paths = None
            if p.get('name'):
                paths = [x for x in scenario(p['name']).paths if x in st.dirty]
            if p.get('rel'):
                paths = [file_identify.resolve(p['rel'])]
            return st.save(paths)
        if path == '/api/scen/revert':
            if p.get('name') in SCEN:
                st.revert([x for x in SCEN[p['name']].paths if x in st.dirty])
                del SCEN[p['name']]
            else:
                st.revert()
            return {'ok': True}
    raise KeyError(path)


# ------------------------------------------------------------------ imagenes (titulo, banderas, iconos)
import image_tools  # noqa: E402

IMG_LOCK = threading.Lock()


def img_get(h, path, q):
    try:
        if path == '/api/img/scenarios':
            return h.send(200, {'scenarios': scenario_core.scenarios()})
        if path == '/api/img/titles':
            return h.send(200, {'files': image_tools.title_info(q['scen'])})
        if path == '/api/img/raw':
            return h.send(200, image_tools.png_bytes(image_tools.resolve_rel(q['rel']), int(q.get('max', 0)) or None), 'image/png')
        if path == '/api/img/countries':
            return h.send(200, image_tools.countries(q['scen']))
        if path == '/api/img/country':
            return h.send(200, {'files': image_tools.country_files(q['scen'], q['name'])})
        if path == '/api/img/icons':
            return h.send(200, image_tools.icons_info(q['scen']))
        if path == '/api/img/flag':     # bandera pequena de un pais (iconos de la pestana Nations)
            png = image_tools.flag_png(q.get('scen') or q['scenario'], q['country'])
            if png is None:
                return h.send(404, {'error': 'sin bandera'})
            return h.send(200, png, 'image/png')
    except (ValueError, KeyError, OSError) as e:
        return h.send(200, {'error': str(e)})
    return h.send(404, {'error': 'no encontrado'})


def img_post(path, p):
    with IMG_LOCK:
        if path == '/api/img/title/write':
            rep = image_tools.write_title(p['scen'], p['file'], p['png'])
        elif path == '/api/img/flag/preview':
            return image_tools.flag_preview(p)
        elif path == '/api/img/flag/write':
            rep = image_tools.flag_write(p)
        elif path == '/api/img/icon/preview':
            return image_tools.icon_preview(p)
        elif path == '/api/img/icon/write':
            rep = image_tools.icon_write(p)
        else:
            raise KeyError(path)
        log('imagenes: %d archivos escritos (copia en %s)' % (len(rep['written']), rep['backup']))
        return rep


def preview(rel):
    from fix_texture import decode
    path = file_identify.resolve(rel)
    info = file_identify.identify(path)
    if info.get('tile'):
        c, r, lv = info['tile']
        img = decode(open(path, 'rb').read(), 1024 >> lv)
    else:
        from PIL import Image
        img = Image.open(path)
    img = img.convert('RGBA')
    if max(img.size) > 1024:
        img.thumbnail((1024, 1024))
    b = io.BytesIO()
    img.save(b, 'PNG')
    return b.getvalue()


ARGS = None


def project_dir(pack):
    base = gamepaths.project_base(os.path.abspath(ARGS.proyecto))
    return base if pack == 'World' else base + '_' + pack


def map_backup_dir():
    # MH1: --respaldo (backup/mapa_original); Gold: backup/gold/mapa_original
    return ARGS.respaldo if gamepaths.CURRENT[0] == 'mh1' else gamepaths.map_backup()


def select_game(key):
    """Cambia la carpeta del juego (MH1 o Gold) de los dos editores."""
    global PROJECT, DOCVIEW
    with SCEN_LOCK:
        if scenario_core.STORE.dirty:
            raise ValueError('hay cambios sin guardar en el editor de escenarios (%s): guárdalos o revértelos antes de cambiar de juego'
                             % ', '.join(sorted(os.path.basename(p) for p in scenario_core.STORE.dirty)))
        if key == gamepaths.CURRENT[0] and PROJECT is not None:
            return {'ok': True, 'game': key}
        # un servidor de pruebas (--escenarios) no cambia el juego que recuerda el editor del usuario
        gamepaths.select(key, remember=not ARGS.escenarios)
        if ARGS.escenarios:
            scenario_core.SCEN_ROOT = os.path.abspath(ARGS.escenarios)
            scenario_core.BACKUP_ROOT = os.path.join(scenario_core.SCEN_ROOT, '_respaldo')
            editor_core.SCEN_DIR = scenario_core.SCEN_ROOT
        SCEN.clear()
        DOCVIEW = None
        scenario_core.STORE = scenario_core.Store()
        with TILE_LOCK:
            TILE_CACHE.clear()
        pack = PROJECT.pack if PROJECT is not None else ARGS.pack
        PROJECT = None
        packs = editor_core.Project.packs()
        select_pack(pack if pack in packs else 'World')
        PROJECT_VERSION[0] += 1
        log('juego: %s (%s)' % (gamepaths.GAMES[key]['label'], gamepaths.path(key)))
        return {'ok': True, 'game': key, 'pack': PROJECT.pack}


def convert_scenario_api(p):
    """Convierte un escenario del juego actual (o de una carpeta) al otro juego, en una copia."""
    import convert_scenario
    src = p.get('dir') or os.path.join(scenario_core.SCEN_ROOT, p['name'])
    if not os.path.isdir(src):
        raise ValueError('no existe el escenario %s' % src)
    src_game = p.get('from') or gamepaths.detect(src) or gamepaths.CURRENT[0]
    dst_game = p.get('to') or ('gold' if src_game == 'mh1' else 'mh1')
    out = p.get('out') or None
    if out and not os.path.isabs(out):
        out = os.path.join(gamepaths.scen_root(dst_game), out)
    rep = convert_scenario.convert(src, dst_game, out, src_game, colors=bool(p.get('colors')), infra=p.get('infra', 'auto'),
                                   units_only=bool(p.get('units_only')), complete_new=p.get('complete_new', True),
                                   remove_partisan_event=p.get('remove_partisan_event', True), log=log)
    rep['resumen'] = convert_scenario.summary(rep)
    return rep


def select_pack(pack):
    global PROJECT
    if pack not in editor_core.Project.packs():
        raise ValueError('no existe el regionpack %s' % pack)
    if PROJECT is not None and PROJECT.pack == pack:
        return
    PROJECT = editor_core.Project(project_dir(pack), map_backup_dir(), pack)
    threading.Thread(target=PROJECT.precompute, daemon=True).start()
    try:   # se recuerda para abrir el mismo regionpack la próxima vez (no en las pruebas con --escenarios)
        if ARGS is not None and ARGS.escenarios:
            raise OSError
        json.dump({'pack': pack}, open(os.path.join(ROOT, 'ultimo_regionpack.json'), 'w'))
    except OSError:
        pass


def main():
    global PROJECT, ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument('--proyecto', default=os.path.join(ROOT, 'editor_proyecto'))
    ap.add_argument('--respaldo', default=os.path.join(ROOT, 'backup', 'mapa_original'))
    ap.add_argument('--puerto', type=int, default=8765)
    ap.add_argument('--no-abrir', action='store_true')
    ap.add_argument('--pack', default=None, help='regionpack inicial (por defecto, el último usado)')
    ap.add_argument('--escenarios', default=None, help='(pruebas) carpeta con copias de escenarios en vez de la del juego')
    ap.add_argument('--juego', choices=sorted(gamepaths.GAMES), default=None,
                    help='mh1 o gold (por defecto, el último elegido en la interfaz)')
    a = ap.parse_args()
    ARGS = a
    # un solo servidor por puerto: en Windows varios pueden compartirlo y uno viejo responderia con codigo antiguo
    import socket
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(('127.0.0.1', a.puerto)) == 0:
            url = 'http://localhost:%d' % a.puerto
            print('Ya hay un editor abierto en %s: se usa ese (ciérralo antes si quieres reiniciarlo).' % url)
            if not a.no_abrir:
                webbrowser.open(url)
            return
    ThreadingHTTPServer.allow_reuse_address = False
    gamepaths.select(a.juego or gamepaths.load_choice(), remember=bool(a.juego))
    if a.escenarios:
        scenario_core.SCEN_ROOT = os.path.abspath(a.escenarios)
        scenario_core.BACKUP_ROOT = os.path.join(scenario_core.SCEN_ROOT, '_respaldo')
        editor_core.SCEN_DIR = scenario_core.SCEN_ROOT
    if not a.pack:
        try:
            a.pack = json.load(open(os.path.join(ROOT, 'ultimo_regionpack.json')))['pack']
        except (OSError, ValueError, KeyError):
            a.pack = 'World'
        if a.pack not in editor_core.Project.packs():
            a.pack = 'World'
    select_pack(a.pack)
    srv = ThreadingHTTPServer(('127.0.0.1', a.puerto), Handler)
    url = 'http://localhost:%d' % a.puerto
    print('Editor de regiones en %s  (juego: %s; proyecto: %s)' % (url, gamepaths.GAMES[gamepaths.CURRENT[0]]['short'],
                                                                 os.path.abspath(PROJECT.dir)))
    if not a.no_abrir:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == '__main__':
    main()
