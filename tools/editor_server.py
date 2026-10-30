"""Servidor local del editor de regiones de Making History.

Uso:  python editor_server.py [--proyecto CARPETA] [--puerto 8765]
Luego abrir http://localhost:8765 en el navegador.
"""
import argparse
import io
import json
import os
import re
import shutil
import sys
import threading
import time
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
import new_pack  # noqa: E402
import anthems  # noqa: E402
try:
    import ai_chat  # noqa: E402   (chat de IA: aún no se publica)
except ImportError:
    ai_chat = None
import changelog_keys  # noqa: E402

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
            if u.path.startswith('/api/wikidata/'):
                return self.send(200, wikidata_api(u.path, {k: v[0] for k, v in q.items()}))
            if u.path == '/api/meta':
                return self.send(200, {'regions': PROJECT.meta(), 'project': os.path.abspath(PROJECT.dir),
                                       'history': len([d for d in os.listdir(PROJECT.history) if d.isdigit()]),
                                       'can_redo': PROJECT.can_redo()})
            if u.path == '/api/region_at':
                # región bajo un punto (para que un clic seleccione aunque esa región no esté cargada en el mapa del navegador)
                from shapely.geometry import Point, shape
                x, y = float(q['x'][0]), float(q['y'][0])
                pt, hit = Point(x, y), None
                for f in PROJECT.features(x, y, x, y, limit=100000):
                    try:
                        if shape(f['geometry']).buffer(0).contains(pt) and (hit is None or hit['properties']['sea']):
                            hit = f
                    except Exception:
                        pass
                return self.send(200, {'feature': hit})
            if u.path == '/api/regions':
                x0, y0, x1, y1 = map(float, q['bbox'][0].split(','))
                return self.send(200, {'type': 'FeatureCollection', 'features': PROJECT.features(x0, y0, x1, y1)})
            if u.path == '/api/pack/not_loadable':
                return self.send(200, uninstalled_in_scenarios(q['pack'][0] if q.get('pack') else PROJECT.pack))
            if u.path == '/api/pack/info':
                return self.send(200, {'pack': PROJECT.pack, 'decided': PROJECT.decided, 'packs': all_packs(),
                                       'nuevos': sorted(new_pack.pending_packs(project_dir('World'))), 'virtual': PROJECT.virtual,
                                       'users': editor_core.Project.pack_users(), 'from_world': pack_from_world()})
            if u.path == '/api/vanilla/regions':       # regiones de tierra del juego vanilla (World): para «Equivale a región del juego vanilla»
                try:
                    pm = scenario_layers.PackMap('World', vanilla_folder())    # el World sin modificar (copia de referencia), no el que haya editado el usuario
                    if (q.get('full') or [''])[0]:      # todas, con su tipo (para sugerir una equivalencia del mismo tipo)
                        return self.send(200, sorted(({'name': pm.name[g.index], 'sea': bool(pm.sea[pm.name[g.index]])} for g in pm.m['regions']),
                                                     key=lambda x: x['name']))
                    return self.send(200, sorted(pm.name[g.index] for g in pm.m['regions'] if not pm.sea[pm.name[g.index]]))
                except (ValueError, OSError, KeyError, TypeError):
                    return self.send(200, [])
            if u.path == '/api/region/equivalence':
                return self.send(200, PROJECT.equivalences().get((q.get('region') or [''])[0]) or [])
            if u.path == '/api/pack/new_check':
                name = (q.get('name') or [''])[0].strip()
                return self.send(200, {'error': new_pack.check_name(name, editor_core.MAPS, project_dir(name) if name else None)})
            if u.path == '/api/pack/new_info':
                world = os.path.join(editor_core.MAPS, 'World')
                return self.send(200, {'world': list(new_pack.WORLD), 'sizes': new_pack.SUGGESTED,
                                       'sea': '#%02x%02x%02x' % new_pack.sea_color(world)[:3], 'have_world': os.path.isdir(world)})
            if u.path == '/api/scenarios':
                return self.send(200, PROJECT.scenarios())
            if u.path == '/api/changelog/review':
                try:
                    return self.send(200, PROJECT.review_changelog(q.get('base', ['World'])[0]))
                except (ValueError, OSError) as e:
                    return self.send(200, {'error': str(e)})
            if u.path == '/api/changelog/owners':     # regiones nuevas y su dueño en un escenario (para asignar los que faltan al «Adecuar»)
                sc_ = (q.get('scenario') or [''])[0]
                try:
                    s_ = scenario(sc_)
                    have = {scenario_core.prop(r, 'strName') for r in s_.regions(sea=False)}
                    regs = PROJECT.new_regions_info(sc_, have)
                    known = {r['name'] for r in regs}
                    try:      # tierra del mapa que el changelog no conoce y no sale de ninguna región con datos: sin dueño no se puede añadir
                        for x in scenario_layers.pack_sync_plan(s_, PROJECT.pack)['add']:
                            if not x['sea'] and not x['mother'] and x['name'] not in known and x['name'] not in have:
                                regs.append({'name': x['name'], 'mother': None, 'owner': None, 'owner_here': None, 'ownerless': True})
                    except (ValueError, OSError, KeyError):
                        pass
                    return self.send(200, {'regions': regs, 'countries': sorted(s_.countries())})
                except (ValueError, OSError, KeyError) as e:
                    return self.send(200, {'error': str(e), 'regions': [], 'countries': []})
            if u.path == '/api/changelog':
                return self.send(200, {'pack': PROJECT.pack, 'entries': PROJECT.changelog(), 'scenarios': PROJECT.scenarios(),
                                       'users': scenario_core.scenarios_using(PROJECT.pack)})
            if u.path == '/api/region/canal':
                return self.send(200, PROJECT.canal_info((q.get('name') or [''])[0]))
            if u.path == '/api/countries':
                if q.get('scenario') and q['scenario'][0] in SCEN:      # escenario abierto: incluye las naciones creadas sin guardar
                    with SCEN_LOCK:
                        return self.send(200, sorted(SCEN[q['scenario'][0]].countries()))
                return self.send(200, scenario_countries(q['scenario'][0]) if q.get('scenario') else [])
            if u.path == '/api/scenario':
                name = q['name'][0]
                if name in SCEN:   # escenario abierto en el editor: propietarios y colores con los cambios sin guardar
                    info = live_scenario_info(SCEN[name])
                else:
                    info = PROJECT.scenario_info(name)
                if isinstance(info, dict) and 'error' not in info:
                    info['game'] = gamepaths.scenario_game(os.path.join(scenario_core.SCEN_ROOT, name))
                return self.send(200, info)
            if u.path == '/api/log':
                return self.send(200, LOG[-50:])
            if u.path == '/api/game':
                return self.send(200, gamepaths.info())
            if u.path == '/api/game/license':   # «Invalid License Key»: licencia vieja en VirtualStore que tapa la de HKLM
                import licencia_juego
                return self.send(200, {'issues': licencia_juego.check(), 'permanent': licencia_juego.writable()})
            if u.path == '/api/xconvert/check':
                return self.send(200, xconvert_check(q.get('scen', [''])[0], q.get('pack', [''])[0]))
            if u.path in ('/icon_mh1.png', '/icon_gold.png'):   # iconos de GameBanana de MH1 y Gold
                return self.send(200, open(os.path.join(HERE, 'editor', u.path[1:]), 'rb').read(), 'image/png', cache=True)
            if u.path in ('/scenario', '/scenario.html', '/escenario', '/escenario.html'):   # /escenario: enlaces antiguos
                return self.send(200, open(os.path.join(HERE, 'editor', 'escenario.html'), 'rb').read(), 'text/html; charset=utf-8')
            if u.path == '/api/regions/export_json':
                # «Exportar a otro regionpack»: las regiones elegidas (con dueño, tipo y terreno del escenario) y, si se pide, sus
                # ciudades, unidades y minerales, en un solo FeatureCollection que el importador de GeoJSON del otro regionpack lee
                import geojson_io
                name = q['name'][0] if q.get('name') and q['name'][0] else None
                only = {x for x in q['regions'][0].split('|') if x} if q.get('regions') else set()
                files = ['regiones_tierra', 'regiones_mar'] + (['ciudades', 'unidades', 'minerales'] if q.get('points', ['0'])[0] == '1' and name else [])
                keep = lambda f: any((f.get('properties') or {}).get(k) in only for k in ('name', 'region', 'strName', 'strRegion'))
                feats = []
                with SCEN_LOCK:
                    for fn, fc in geojson_io.export(scenario(name) if name else None, PROJECT, files, False, 'World', 'es', name).items():
                        if isinstance(fc, dict) and isinstance(fc.get('features'), list):
                            feats += [f for f in fc['features'] if keep(f)]
                return self.send(200, {'type': 'FeatureCollection', 'features': feats})
            if u.path == '/api/scen/geojson_export':
                import geojson_io
                sel = [x for x in q['files'][0].split(',') if x in geojson_io.ALL_FILES] if q.get('files') else None
                name = q['name'][0] if q.get('name') and q['name'][0] else None
                with SCEN_LOCK:
                    data = geojson_io.export_zip(scenario(name) if name else None, PROJECT, sel, q.get('split', ['0'])[0] == '1',
                                                 q.get('base', ['World'])[0], q.get('lang', ['es'])[0], name, q.get('colors', ['0'])[0] == '1', q.get('ncolors', ['0'])[0] == '1',
                                                 [x for x in q['regions'][0].split('|') if x] if q.get('regions') else None)
                return self.send(200, data, 'application/zip')
            if u.path.startswith('/api/scen/') or u.path.startswith('/api/files/'):
                return self.send(200, scen_get(u.path, {k: v[0] for k, v in q.items()}))
            if u.path == '/i18n_en.json':
                return self.send(200, open(os.path.join(HERE, 'editor', 'i18n_en.json'), 'rb').read(), 'application/json; charset=utf-8')
            if u.path == '/api/progress':
                return self.send(200, progress.get())
            if u.path == '/ai_chat.js':
                return self.send(200, open(os.path.join(HERE, 'editor', 'ai_chat.js'), 'rb').read(), 'text/javascript; charset=utf-8')
            if u.path == '/api/ai/config':     # chat de IA: proveedores (sin claves)
                return self.send(200, ai_chat.public())
            if u.path == '/api/ai/routes':
                return self.send(200, {'routes': ai_chat.routes(q.get('filter', [''])[0])})
            if u.path == '/api/ai/route_src':
                return self.send(200, {'source': ai_chat.route_source(q['path'][0], q.get('method', [''])[0])})
            if u.path in ('/i18n.js', '/busy.js', '/escenario_extra.js'):
                return self.send(200, open(os.path.join(HERE, 'editor', u.path[1:]), 'rb').read(), 'text/javascript; charset=utf-8')
            if u.path == '/escenario_wikidata.js':
                return self.send(200, open(os.path.join(HERE, 'editor', 'escenario_wikidata.js'), 'rb').read(), 'text/javascript; charset=utf-8')
            if u.path == '/escenario_imagenes.js':
                return self.send(200, open(os.path.join(HERE, 'editor', 'escenario_imagenes.js'), 'rb').read(), 'text/javascript; charset=utf-8')
            if u.path in ('/compare', '/compare.html', '/comparar', '/comparar.html'):
                return self.send(200, open(os.path.join(HERE, 'editor', 'comparar.html'), 'rb').read(), 'text/html; charset=utf-8')
            if u.path.startswith('/api/gamelog/'):
                return self.send(200, gamelog_api(u.path, {k: v[0] for k, v in q.items()}))
            if u.path.startswith('/api/cmp/') or u.path.startswith('/api/save/'):
                try:
                    return self.send(200, cmp_get(u.path, {k: v[0] for k, v in q.items()}))
                except (ValueError, KeyError, OSError) as e:
                    return self.send(200, {'error': str(e)})
            if u.path in ('/models', '/models.html', '/modelos', '/modelos.html'):
                return self.send(200, open(os.path.join(HERE, 'editor', 'modelos.html'), 'rb').read(), 'text/html; charset=utf-8')
            if u.path.startswith('/api/model/'):
                import models_api
                g = {k: v[0] for k, v in q.items()}
                try:
                    if u.path == '/api/model/list':
                        return self.send(200, models_api.models(scenario(g['name'])))
                    if u.path == '/api/model/check':
                        return self.send(200, {'issues': models_api.land_display_issues(scenario(g['name']).dir)})
                    if u.path == '/api/model/info':
                        return self.send(200, models_api.info(g['path']))
                    if u.path == '/api/model/glb':
                        return self.send(200, models_api.glb(g['path']), 'model/gltf-binary')
                    if u.path == '/api/model/tex':
                        return self.send(200, models_api.tex_png(g['path'], g['block']), 'image/png')
                    if u.path == '/api/model/obj':
                        return self.send(200, models_api.obj_zip(g['path']), 'application/zip')
                except (ValueError, KeyError, OSError) as e:
                    return self.send(200, {'error': str(e)})
            if u.path in ('/images', '/images.html', '/imagenes', '/imagenes.html'):
                return self.send(200, open(os.path.join(HERE, 'editor', 'imagenes.html'), 'rb').read(), 'text/html; charset=utf-8')
            if u.path == '/api/anthems':      # himnos: globales (UI/SoundPack.xml), no del escenario
                try:
                    return self.send(200, anthems.status())
                except OSError as e:
                    return self.send(200, {'error': str(e)})
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
                # pal: paleta del juego del escenario abierto (si es del otro juego, se recolorean las texturas)
                pal = q.get('pal', [''])[0]
                pal = pal if pal in gamepaths.GAMES and pal != gamepaths.CURRENT[0] else ''
                key = (c, r, lv, PROJECT_VERSION[0], gamepaths.CURRENT[0], pal)
                with TILE_LOCK:
                    data = TILE_CACHE.get(key)
                if data is None:
                    img = PROJECT.tile_image(c, r, lv)
                    if pal:
                        import game_palette
                        img = game_palette.recolor(img, gamepaths.CURRENT[0], pal)
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
            if u.path.startswith('/api/ai/'):
                return self.send(200, ai_post(u.path, payload))
            if u.path.startswith('/api/wikidata/'):
                return self.send(200, wikidata_api(u.path, payload))
            if u.path == '/api/regions/merge':
                # unificar regiones (selección múltiple): las demás se eliminan y su área, ciudades, población y unidades
                # pasan a 'into'; es un guardado del mapa como cualquier otro (y se registra en los escenarios)
                idx = {PROJECT.rname(g.index): g.index for g in PROJECT.m['regions']}
                into, names = payload.get('into'), [n for n in payload.get('regions') or [] if n != payload.get('into')]
                delete = bool(payload.get('delete'))
                if (into is None and not delete) or (into is not None and into not in idx) or not names or any(n not in idx for n in names):
                    return self.send(200, {'errors': ['regiones desconocidas para unificar o eliminar'], 'warnings': [], 'transfers': []})
                sea = lambda n: PROJECT.m['regions'][idx[n]].u_type == editor_core.SEA
                payload = {'modified': {}, 'assigns': [{'kind': 'delete_region', 'region': idx[n], 'into': idx[into] if into is not None else None} for n in names],
                           'centers': {}, 'topo': True, 'paint': True, 'register': True}
                u = u._replace(path='/api/save')
            if u.path == '/api/save':
                try:     # escenario nuevo y naciones nuevas: se comprueba todo antes de tocar el mapa
                    ns = payload.get('new_scenario')
                    if ns:
                        scenario_new.check_name(ns.get('name'))
                    seen = set()
                    for a in payload.get('assigns') or []:
                        nat = a.get('nation')
                        if nat:
                            if nat['name'] in seen:
                                continue
                            seen.add(nat['name'])
                            scenario_new.validate_nation(nat)
                            if not isinstance(a.get('population'), (int, float)) or a['population'] <= scenario_new.MIN_POP:
                                raise ValueError('%s: la región tiene que tener más de %d habitantes' % (nat['name'], scenario_new.MIN_POP))
                except (ValueError, KeyError) as e:
                    return self.send(200, {'errors': [str(e)], 'warnings': [], 'transfers': []})
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
                             'poblacion_manual': c.get('population'), 'ciudad': c.get('city'), 'nacion': c.get('nation')} for c in rep['new_regions']]
                    ns = payload.get('new_scenario')
                    if ns:
                        try:
                            rep['new_scenario'] = scenario_new.create_scenario(ns['name'], PROJECT.pack, ns.get('template') or None,
                                                                               ns.get('display') or None, ns.get('description') or None)
                        except (ValueError, OSError) as e:
                            rep.setdefault('warnings', []).append('escenario nuevo «%s» no creado: %s' % (ns.get('name'), e))
                    register_regions.force = set(payload.get('force_scenarios') or [])
                    rep['scenarios'] = register_regions(news, scenario_core.scenarios_using(PROJECT.pack), pf=progress.part(75, 99))
                    register_regions.force = set()
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
                if rep.get('scenarios') and not rep.get('errors'):
                    keep_game_loadable(rep)       # mapa del juego al día con lo registrado (si no, la página ofrece «Instalar»)
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
                if rep.get('scenarios'):
                    keep_game_loadable(rep)
                return self.send(200, rep)
            if u.path == '/api/register_region':
                # region que existe en el mapa pero no en el escenario abierto (p. ej. si falló su registro)
                x = {'nombre': payload['name'], 'madre': payload.get('mother'), 'pais': payload.get('owner'),
                     'controlador': payload.get('controller'), 'terreno': payload.get('terrain'),
                     'poblacion_manual': payload.get('population'), 'texto': payload.get('text'),
                     'poblacion': {payload['mother']: float(payload.get('pop_pct') or 0) / 100} if payload.get('mother') else None}
                # habitantes puestos a mano al crearla (changelog): mandan sobre el % de la madre del diálogo (antes se perdían)
                if x['poblacion_manual'] is None:
                    try:
                        made = [c for e in PROJECT.changelog() for c in e.get('regiones_nuevas', []) if c.get('nombre') == payload['name']]
                    except Exception:
                        made = []
                    if made and made[-1].get('poblacion_manual') is not None:
                        x['poblacion_manual'], x['poblacion'] = made[-1]['poblacion_manual'], None
                register_regions.force = set(payload.get('force_scenarios') or [])
                out = register_regions([x], [payload['scenario']])
                register_regions.force = set()
                rep = {'scenarios': out, 'conflicts': register_regions.conflicts}
                keep_game_loadable(rep)
                return self.send(200, rep)
            if u.path == '/api/geojson/create_nations':
                # naciones que menciona un GeoJSON y no están en el escenario: se crean (sin guardar) y quedan rendidas hasta recibir su región
                out = []
                with SCEN_LOCK:
                    s = scenario(payload['scenario'])
                    for n in payload.get('names') or []:
                        try:
                            scenario_create.create_country(s, n)
                            out.append({'name': n, 'ok': True})
                        except ValueError as e:
                            out.append({'name': n, 'ok': False, 'error': str(e)})
                    dirty = sorted(os.path.basename(x) for x in scenario_core.STORE.dirty if x in s.paths)
                return self.send(200, {'nations': out, 'dirty': dirty})
            if u.path == '/api/geojson/exclaves':
                import geojson_compare
                return self.send(200, geojson_compare.exclaves(PROJECT, payload['polygon'], float(payload.get('max_pct') or 0.05)))
            if u.path == '/api/background/restore':
                # restaura el fondo desde el World original donde no hay frontera dibujada (ver background_restore.py); se puede deshacer con «Volver»
                ref = vanilla_folder()
                if not ref:
                    return self.send(200, {'error': 'no hay copia del mapa original (backup/mapa_original): se crea la primera vez que el editor instala un cambio'})
                bb = payload.get('bbox')
                with PROJECT.lock:
                    PROJECT.snapshot(log)
                    try:
                        import background_restore, mhmap, vanilla_ref
                        orig = gamepaths.map_backup()
                        world = os.path.join(editor_core.MAPS, 'World')
                        done = background_restore.restore(PROJECT.m, mhmap.load_map(os.path.join(ref, 'xml')), PROJECT.tiles,
                                                          lambda n: vanilla_ref.tile_path(n, orig, world), bb, log)
                        lines = background_restore.repaint_tiles(PROJECT.m, PROJECT.tiles, only_bbox=bb, log=log) \
                            if payload.get('lines') else []          # opción «Dibujar las líneas de las regiones»
                    except Exception as e:
                        traceback.print_exc()
                        return self.send(200, {'error': 'no se pudo restaurar el fondo: %s' % e})
                    if not done and not lines:     # nada que restaurar: sin copia para «Volver»
                        snaps = sorted(d for d in os.listdir(PROJECT.history) if d.isdigit())
                        if snaps:
                            shutil.rmtree(os.path.join(PROJECT.history, snaps[-1]), ignore_errors=True)
                with TILE_LOCK:
                    TILE_CACHE.clear()
                PROJECT_VERSION[0] += 1
                return self.send(200, {'ok': True, 'tiles': done, 'lines': lines})
            if u.path == '/api/region/crumbs':      # trozos sueltos / exclaves diminutos de una región (para pasarlos a la vecina)
                return self.send(200, {'crumbs': PROJECT.crumbs(int(payload['region']))})
            if u.path == '/api/geojson/close_gaps':     # importación: cerrar rendijas/huecos pequeños entre los contornos
                gs, n = __import__('geojson_io').close_gaps(payload['geoms'], float(payload.get('max_area') or 0.05))
                return self.send(200, {'geoms': gs, 'closed': n})
            if u.path == '/api/equivalence/auto':
                # equivalencias con el World vanilla calculadas por solape de áreas (regiones del mismo tipo): una región vanilla
                # equivale a la región nueva que tiene la mayor parte de su área; si una región nueva no recibe ninguna entera,
                # equivale a la vanilla que más área le aporta. Se escriben en el changelog (base: World).
                from shapely.strtree import STRtree
                vm = scenario_layers.PackMap('World', vanilla_folder())
                vnames = [n for n in vm.name.values() if n not in ('BasicRegionLists', 'Historic')]
                vgeo = [(n, vm.geom(n), vm.sea[n]) for n in vnames]
                vgeo = [x for x in vgeo if x[1] is not None and not x[1].is_empty]
                mine = {PROJECT.rname(g.index): (PROJECT.region_geom(PROJECT.rname(g.index)), g.u_type == 0) for g in PROJECT.m['regions']}
                mine = {k: v for k, v in mine.items() if v[0] is not None and not v[0].is_empty}
                only_missing = bool(payload.get('only_missing', True))
                have = PROJECT.equivalences()
                tree = STRtree([g for _, g, _ in vgeo])
                best_new = {}           # región vanilla -> (región nueva con más de su área, fracción)
                share = {}              # región nueva -> [(vanilla, área común)]
                for n, (g, sea) in mine.items():
                    for i in tree.query(g):
                        vn, vg, vs = vgeo[int(i)]
                        if vs != sea:
                            continue
                        a = g.intersection(vg).area
                        if a <= 0:
                            continue
                        share.setdefault(n, []).append((vn, a))
                        f = a / vg.area if vg.area else 0
                        if f > best_new.get(vn, (None, 0))[1]:
                            best_new[vn] = (n, f)
                res = {}
                vg_by = {vn: vg for vn, vg, _ in vgeo}
                same_name_elsewhere = []
                for n in mine:
                    if n in vnames and not payload.get('include_same_name'):
                        # se llama como una región de World: equivale a sí misma SOLO si está en el mismo sitio (Piedmont de
                        # EE. UU. no es el Piamonte de Italia): se comprueba por solape de áreas, no por el nombre
                        g0, v0 = mine[n][0], vg_by.get(n)
                        ov = g0.intersection(v0).area / min(g0.area, v0.area) if v0 is not None and g0.area and v0.area else 0
                        if ov >= 0.3:
                            continue
                        same_name_elsewhere.append(n)
                    if only_missing and have.get(n):
                        continue
                    eq = sorted(vn for vn, (bn, f) in best_new.items() if bn == n and f >= 0.5)
                    if not eq and share.get(n):
                        eq = [max(share[n], key=lambda x: x[1])[0]]
                    if eq:
                        res[n] = eq
                if payload.get('write'):
                    for n, eq in res.items():
                        PROJECT.set_equivalence(n, eq)
                return self.send(200, {'equivalences': res, 'written': bool(payload.get('write')), 'base': 'World',
                                       'same_name_elsewhere': same_name_elsewhere})
            if u.path == '/api/gap/split_proximity':        # repartir un hueco entre las regiones que lo rodean por cercanía
                return self.send(200, {'pieces': PROJECT.split_gap_by_proximity(payload['polygon'], payload.get('neighbors') or [])})
            if u.path == '/api/region/split_proximity':     # repartir una región (agua) entre sus vecinas de tierra por cercanía
                return self.send(200, {'pieces': PROJECT.split_by_proximity(int(payload['region']))})
            if u.path == '/api/gaps/small':                   # huecos pequeños entre regiones (todo el regionpack o un par)
                pr = payload.get('pair')
                rg = payload.get('region')
                return self.send(200, {'gaps': PROJECT.small_gaps(float(payload.get('max_area') or 0.05), float(payload.get('eps') or 0.03),
                                                                   tuple(int(x) for x in pr) if pr else None,
                                                                   int(rg) if rg is not None else None)})
            if u.path == '/api/validate':                     # todo lo que bloquearía el guardado, de una vez
                iss = PROJECT.validate()
                for name in scenario_core.scenarios_using(PROJECT.pack):
                    try:
                        miss, extra = scenario_layers.pack_mismatch(scenario(name), PROJECT.pack)
                        if miss:
                            iss.append({'level': 'aviso', 'region': '', 'msg': '%s: le faltan %d región(es) del mapa (%s) - usa «Adecuar»' % (name, len(miss), ', '.join(miss[:10]))})
                        if extra:
                            iss.append({'level': 'aviso', 'region': '', 'msg': '%s: le sobran %d región(es) (%s) - usa «Adecuar»' % (name, len(extra), ', '.join(extra[:10]))})
                    except Exception as e:
                        iss.append({'level': 'aviso', 'region': '', 'msg': '%s: %s' % (name, e)})
                return self.send(200, {'issues': iss, 'pack': PROJECT.pack})
            if u.path == '/api/gap':
                return self.send(200, PROJECT.gap_at(float(payload['x']), float(payload['y'])))
            if u.path == '/api/cut_preview':
                return self.send(200, {'mothers': PROJECT.cut_preview(payload['polygon'], payload.get('sea'))})
            if u.path == '/api/redo':
                rep = PROJECT.redo(log=log)
                PROJECT_VERSION[0] += 1
                if rep.get('added_regions'):
                    rep['scenarios'] = register_regions(rep['added_regions'], scenario_core.scenarios_using(PROJECT.pack))
                    keep_game_loadable(rep)
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
            if u.path == '/api/changelog/owner':
                try:
                    PROJECT.set_owner_for_scenario(payload['region'], payload['scenario'], payload.get('owner'))
                except (ValueError, OSError) as e:
                    return self.send(200, {'error': str(e)})
                return self.send(200, {'ok': True})
            if u.path == '/api/region/equivalence':
                # una región de mar solo equivale a regiones de mar vanilla y una de tierra a las de tierra
                try:
                    vt = {x['name']: bool(x['sea']) for x in json.loads(json.dumps(scenario_layers_vanilla_types()))}
                except Exception:
                    vt = {}
                mine = next((g.u_type == 0 for g in PROJECT.m['regions'] if PROJECT.rname(g.index) == payload['region']), None)
                bad = [n for n in (payload.get('vanilla') or []) if mine is not None and n in vt and vt[n] != mine]
                if bad:
                    return self.send(200, {'error': '%s es de %s: no puede equivaler a %s (%s)' % (payload['region'], 'mar' if mine else 'tierra', ', '.join(bad), 'de tierra' if mine else 'de mar')})
                return self.send(200, {'equivale': PROJECT.set_equivalence(payload['region'], payload.get('vanilla') or [])})
            if u.path == '/api/region/paint_island':
                # «Pintar la isla en el fondo»: tierra y costa de islas en tiles/ del proyecto; con un GeoJSON, su forma real
                # (rasgos con «name» = región; uno solo sin nombre vale para la primera región)
                from shapely.geometry import shape as _shape
                from shapely.ops import unary_union as _uu
                regs = payload.get('regions') or []
                land = {}
                for f in ((payload.get('geojson') or {}).get('features') or []):
                    nm = (f.get('properties') or {}).get('name') or (regs[0] if regs else None)
                    if nm and f.get('geometry'):
                        land[nm] = _uu([land[nm], _shape(f['geometry'])]) if nm in land else _shape(f['geometry']).buffer(0)
                try:
                    return self.send(200, PROJECT.paint_islands(regs or list(land), land))
                except (ValueError, OSError) as e:
                    return self.send(200, {'error': str(e)})
            if u.path == '/api/redraw_borders':
                # «Redibujar fronteras»: líneas de todas las fronteras en tiles/ del proyecto (el juego, solo al Instalar)
                try:
                    r = payload.get('region')
                    return self.send(200, PROJECT.redraw_borders(None if r is None else int(r)))
                except (ValueError, OSError) as e:
                    return self.send(200, {'error': str(e)})
            if u.path == '/api/install_tiles':
                # instalar solo el fondo: copia al juego esos tiles del proyecto (sin tocar regions.bin, borders.brd ni escenarios)
                return self.send(200, {'copied': PROJECT.install_tiles(payload.get('tiles') or [])})
            if u.path == '/api/region/convert':
                # mar <-> tierra (tierra importada que quedó como mar): solo el tipo; la malla no cambia
                try:
                    out = PROJECT.convert_region_type(payload.get('regions') or [], payload.get('to'), payload.get('terrain') or 1)
                except (ValueError, OSError) as e:
                    return self.send(200, {'error': str(e)})
                PROJECT_VERSION[0] += 1
                log('tipo de región -> %s: %s' % (payload.get('to'), ', '.join(out['done'])))
                if payload.get('to') == 'sea' and payload.get('scenarios') and out['done']:
                    # también en los escenarios: deja de ser región de tierra (lo de dentro vuelve a la vecina más cercana) y pasa a waterWorld.xml
                    sc_out = {}
                    with SCEN_LOCK:
                        for name in scenario_core.scenarios_using(PROJECT.pack):
                            notes = []
                            try:
                                s_ = scenario(name)
                                st = scenario_core.STORE
                                if any(x in st.dirty for x in s_.paths):
                                    sc_out[name] = ['no se ha tocado: tiene cambios sin guardar en el editor de escenarios']
                                    continue
                                land = {scenario_core.prop(r, 'strName') for r in s_.regions(sea=False)}
                                seas = {scenario_core.prop(r, 'strName') for r in s_.regions(sea=True)}
                                for n in out['done']:
                                    g = PROJECT.region_geom(n)
                                    if n in land:
                                        near = None
                                        if g is not None:
                                            ds = [(g.distance(PROJECT.region_geom(m)), m) for m in land if m != n and PROJECT.region_geom(m) is not None]
                                            near = min(ds)[1] if ds else None
                                        notes += scenario_core.remove_new_region(s_, n, near)
                                    if n not in seas:
                                        notes += scenario_layers.add_sea_region(s_, n)
                                        notes += scenario_layers.reassign_by_geometry(s_, n, g, sea=True)
                                res = st.save([x for x in s_.paths if x in st.dirty])
                                if res['written']:
                                    notes.append('guardado: %s' % ', '.join(os.path.basename(w) for w in res['written']))
                            except Exception as e:
                                traceback.print_exc()
                                notes.append('ERROR: %s' % e)
                            sc_out[name] = notes
                    out['scenarios'] = sc_out
                return self.send(200, dict(out, ok=True))
            if u.path == '/api/region/canal':
                # región de mar de navegación libre o cerrada (canal): map.xml del proyecto, se instala con «Instalar»
                try:
                    info = PROJECT.set_canal(payload['region'], bool(payload.get('closed')), payload.get('zone'))
                except (ValueError, OSError) as e:
                    return self.send(200, {'error': str(e)})
                log('canal %s: %s' % (payload['region'], 'cerrada (zona %s)' % info['zone'] if info['state'] == 'cerrada' else 'libre'))
                return self.send(200, {'ok': True, 'canal': info})
            if u.path == '/api/region/rename':
                # nombre de una región: map.xml del proyecto (se instala con «Instalar») y los escenarios que usan el regionpack
                old, new, text = payload['region'], payload['new_name'].strip(), (payload.get('text') or '').strip() or None
                if new == old:
                    # solo el nombre visible (stringTable de cada escenario); el interno y map.xml no cambian
                    if not text:
                        return self.send(200, {'error': 'falta el nombre visible'})
                    out = {}
                    with SCEN_LOCK:
                        for name in scenario_core.scenarios_using(PROJECT.pack):
                            try:
                                sc_ = scenario(name)
                                st = scenario_core.STORE
                                if any(x in st.dirty for x in sc_.paths):
                                    out[name] = ['no se ha tocado: tiene cambios sin guardar en el editor de escenarios']
                                    continue
                                reg = next((r for r in sc_.regions() if scenario_core.prop(r, 'strName') == old), None)
                                sid = scenario_core.prop(reg, 'sidName') if reg is not None else None
                                if reg is not None and payload.get('change_sid'):
                                    # también el código del texto (sidName): SID.Game.Region.Name.<texto sin espacios ni acentos>
                                    nsid = scenario_core.region_sid(text)
                                    if nsid != sid:
                                        st.set_prop(reg, 'sidName', nsid)
                                        sid = nsid
                                notes = scenario_core.set_region_string(sc_, sid, text) if sid else ['%s: no está en este escenario' % old]
                                res = st.save([x for x in sc_.paths if x in st.dirty])
                                if res['written']:
                                    notes.append('guardado: %s' % ', '.join(os.path.basename(w) for w in res['written']))
                                out[name] = notes
                            except Exception as e:
                                traceback.print_exc()
                                out[name] = ['ERROR: %s' % e]
                    return self.send(200, {'ok': True, 'scenarios': out, 'only_text': True})
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
                with TILE_LOCK:              # el fondo también se vuelve a leer (si no, quedaban tiles de otro regionpack)
                    TILE_CACHE.clear()
                PROJECT_VERSION[0] += 1
                if payload.get('load_installed') and state != 'same' and not PROJECT.virtual:
                    PROJECT.load_installed()
                    with TILE_LOCK:
                        TILE_CACHE.clear()
                    PROJECT_VERSION[0] += 1
                    threading.Thread(target=PROJECT.precompute, daemon=True).start()
                    log('regionpack %s recargado desde el juego' % PROJECT.pack)
                    return self.send(200, {'state': 'same', 'loaded': True})
                return self.send(200, {'state': state, 'pack': PROJECT.pack})
            if u.path == '/api/game/license_permanent':   # permiso de escritura en HKLM (pide admin): sin VirtualStore no vuelve a pasar
                import licencia_juego
                return self.send(200, licencia_juego.permanente())
            if u.path == '/api/game/license_fix':   # borra solo esos valores, con respaldo .reg en making-history
                import licencia_juego
                return self.send(200, licencia_juego.fix())
            if u.path == '/api/game/select':
                try:
                    return self.send(200, select_game(payload['game']))
                except ValueError as e:
                    return self.send(200, {'error': str(e)})
            if u.path == '/api/xconvert':
                try:
                    return self.send(200, xconvert_api(payload))
                except (ValueError, KeyError, OSError) as e:
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
            if u.path == '/api/minimap/import':
                # minimapa del regionpack (art/MiniMap.tga): se guarda en el proyecto al tamaño del original y llega al juego con «Instalar»
                import base64, io
                from PIL import Image
                try:
                    im = Image.open(io.BytesIO(base64.b64decode(payload['image'].split(',')[-1]))).convert('RGBA')
                except Exception as e:
                    return self.send(200, {'error': 'imagen no válida: %s' % e})
                size = (256, 128)
                for ref in (os.path.join(PROJECT.dir, 'art', 'MiniMap.tga'), os.path.join(PROJECT.map_dir, 'art', 'MiniMap.tga')):
                    try:
                        size = Image.open(ref).size
                        break
                    except Exception:
                        pass
                os.makedirs(os.path.join(PROJECT.dir, 'art'), exist_ok=True)
                out = os.path.join(PROJECT.dir, 'art', 'MiniMap.tga')
                im.resize(size, Image.LANCZOS).save(out, format='TGA')
                log('minimapa importado: %s (%dx%d)' % (out, size[0], size[1]))
                return self.send(200, {'ok': True, 'size': list(size)})
            if u.path == '/api/terrain/import':
                # imagen de fondo -> tiles DXT5 del proyecto (llega al juego con «Instalar»)
                import base64
                import terrain_image
                try:
                    data = base64.b64decode(payload['image'].split(',')[-1])
                    with PROJECT.lock:
                        tiles = terrain_image.import_image(PROJECT, data, [float(x) for x in payload['bbox']], log=log)
                        if payload.get('lines') and tiles:       # opción «Dibujar las líneas de las regiones»
                            import background_restore
                            background_restore.repaint_tiles(PROJECT.m, PROJECT.tiles, set(tiles), log=log)
                except (ValueError, KeyError, OSError) as e:
                    return self.send(200, {'error': str(e)})
                with TILE_LOCK:
                    TILE_CACHE.clear()
                PROJECT_VERSION[0] += 1
                return self.send(200, {'tiles': tiles, 'lines': bool(payload.get('lines'))})
            if u.path == '/api/pack/copy':
                # copia de seguridad del regionpack (y, si se pide, los escenarios elegidos pasan a usarla)
                if PROJECT.virtual:        # regionpack nuevo sin instalar: «Guardar como…» duplica el proyecto
                    nm = (payload.get('name') or '').strip()
                    err = new_pack.check_name(nm, editor_core.MAPS, project_dir(nm) if nm else None)
                    if err:
                        return self.send(200, {'error': err})
                    with SCEN_LOCK, PROJECT.lock:
                        new_pack.save_as(PROJECT, nm, project_dir(nm), os.path.join(editor_core.MAPS, 'World'))
                    return self.send(200, {'ok': True, 'pack': nm, 'escenarios': [],
                                           'notes': ['Guardado como regionpack nuevo (solo proyecto; nada se escribió en el juego): %s' % nm]})
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
            if u.path == '/api/pack/new':
                # regionpack nuevo desde cero: proyecto sin regiones y fondo en color mar (o la imagen dada); nada va al juego
                import base64
                name = (payload.get('name') or '').strip()
                err = new_pack.check_name(name, editor_core.MAPS, project_dir(name) if name else None)
                world = os.path.join(editor_core.MAPS, 'World')
                if not err and not os.path.isdir(world):
                    err = 'no se encuentra el regionpack World del juego'
                if err:
                    return self.send(200, {'error': err})
                bbox = [float(x) for x in payload.get('bbox') or new_pack.WORLD]
                if payload.get('image') and not (bbox[2] > bbox[0] and bbox[3] > bbox[1]):
                    return self.send(200, {'error': 'zona no válida'})
                folder = project_dir(name)
                with SCEN_LOCK:
                    try:
                        new_pack.create_project(folder, name, world)
                        select_pack(name)
                        new_pack.fill_world(PROJECT, payload.get('fill') or 'empty')
                        tiles = []
                        if payload.get('image'):
                            data = base64.b64decode(payload['image'].split(',')[-1])
                            with PROJECT.lock:
                                tiles = new_pack.terrain_image.import_image(PROJECT, data, bbox, log=log)
                    except Exception as e:
                        traceback.print_exc()
                        if os.path.isdir(folder) and not PROJECT.pack == name:
                            shutil.rmtree(folder, ignore_errors=True)
                        return self.send(200, {'error': str(e)})
                PROJECT_VERSION[0] += 1
                log('regionpack nuevo «%s» (proyecto %s; fondo %s)' % (name, folder, 'imagen' if tiles else 'color mar'))
                return self.send(200, {'ok': True, 'pack': name, 'tiles': len(tiles)})
            if u.path == '/api/pack/select':
                select_pack(payload['pack'])
                PROJECT_VERSION[0] += 1
                return self.send(200, {'ok': True, 'pack': PROJECT.pack})
            if u.path.startswith('/api/anthems/'):
                import base64
                try:
                    if u.path == '/api/anthems/import':
                        return self.send(200, anthems.import_audio(payload.get('country'), base64.b64decode(payload['data']), payload.get('ext') or 'mp3'))
                    if u.path == '/api/anthems/remove':
                        return self.send(200, anthems.remove_staged(payload.get('country')))
                    if u.path == '/api/anthems/install':      # único paso que escribe en el juego
                        rep = anthems.install()
                        if rep.get('ok'):
                            log('himnos instalados: %s (copia en %s)' % (', '.join(rep['installed']), rep['backup']))
                        return self.send(200, rep)
                except (ValueError, KeyError, OSError) as e:
                    return self.send(200, {'error': str(e)})
            if u.path.startswith('/api/img/'):
                try:
                    return self.send(200, img_post(u.path, payload))
                except (ValueError, KeyError, OSError) as e:
                    return self.send(200, {'error': str(e)})
            if u.path.startswith('/api/gamelog/'):
                return self.send(200, gamelog_api(u.path, payload))
            if u.path.startswith('/api/cmp/') or u.path.startswith('/api/save/'):
                try:
                    return self.send(200, cmp_post(u.path, payload))
                except (ValueError, KeyError, OSError) as e:
                    return self.send(200, {'error': str(e)})
            if u.path.startswith('/api/scen/') or u.path.startswith('/api/files/'):
                try:
                    return self.send(200, scen_post(u.path, payload))
                except (ValueError, KeyError) as e:
                    return self.send(200, {'error': scenario_i18n.L_msg(str(e))})
            return self.send(404, {'error': 'no encontrado'})
        except Exception as e:
            traceback.print_exc()
            PROJECT.reload()
            return self.send(500, {'errors': ['error interno: %s' % e], 'warnings': [], 'transfers': []})


PROJECT_VERSION = [0]

# ------------------------------------------------------------------ escenarios y archivos
import scenario_core  # noqa: E402
import scenario_layers  # noqa: E402
import icon_defaults  # noqa: E402
import scenario_create  # noqa: E402
import scenario_extra  # noqa: E402
import scenario_new  # noqa: E402
import scenario_events  # noqa: E402
import scenario_i18n  # noqa: E402
import sprite_scale  # noqa: E402
import region_transfer  # noqa: E402
import research_defaults  # noqa: E402
import file_identify  # noqa: E402

SCEN = {}
SCEN_LOCK = threading.RLock()
DOCVIEW = None


def scenario_layers_vanilla_types():
    """[{name, sea}] de las regiones del World vanilla."""
    pm = scenario_layers.PackMap('World', vanilla_folder())
    return [{'name': pm.name[g.index], 'sea': bool(pm.sea[pm.name[g.index]])} for g in pm.m['regions']]


def pack_from_world():
    """False si el regionpack se hizo desde cero (no procede de World: pack.json «base: null» o changelog «origen: desde_cero»)."""
    try:
        pj = json.load(open(os.path.join(PROJECT.dir, 'pack.json'), encoding='utf-8'))
        if 'base' in pj and pj['base'] is None:
            return False
    except (OSError, ValueError):
        pass
    try:
        if any(e.get('origen') == 'desde_cero' for e in PROJECT.changelog()):
            return False
    except Exception:
        pass
    # un fondo propio (p. ej. TamrielDemo): sus tiles del juego no se parecen a los de World. Antes se daba por «de World» y
    # «Restaurar fondo» pegaba la Tierra encima donde no había frontera
    try:
        import filecmp
        world = os.path.join(editor_core.MAPS, 'World', 'art', 'OperationalTerrain')
        mine = os.path.join(PROJECT.map_dir, 'art', 'OperationalTerrain')
        if PROJECT.pack != 'World' and os.path.isdir(world) and os.path.isdir(mine):
            names = ['OperationalTerrain-%02d-%02d-04.tga' % (c, r) for c in range(0, 24, 3) for r in range(1, 12, 2)]
            names = [n for n in names if os.path.exists(os.path.join(world, n)) and os.path.exists(os.path.join(mine, n))]
            same = sum(filecmp.cmp(os.path.join(world, n), os.path.join(mine, n), shallow=False) for n in names)
            if names and same < len(names) // 2:
                return False
    except Exception:
        pass
    return True


def vanilla_folder():
    """Carpeta de la copia «vanilla» de World (referencia: cómo es el juego sin cambios), creada la primera vez; None si no hay originales."""
    import vanilla_ref
    try:
        return vanilla_ref.ensure(gamepaths.map_backup(), os.path.join(editor_core.MAPS, 'World'),
                                  os.path.join(gamepaths.backup_root(), 'vanilla_World'))
    except OSError:
        return None


def scen_pack_project(s):
    """Proyecto (changelog) del regionpack que usa el escenario; el abierto si es el mismo."""
    sx = s.all('Scenario', lambda f: f == 'scenario.xml')
    disp = next((o for o in sx[0].iter('object') if o.get('type') == 'ScenarioDisplaySettings'), None) if sx else None
    pack = (scenario_core.prop(disp, 'strMapName') if disp is not None else None) or 'World'
    if PROJECT is not None and PROJECT.pack == pack:
        return PROJECT
    return editor_core.Project(project_dir(pack), map_backup_dir(), pack)


def scen_year(s):
    for o in s.all('ScenarioInfo') + s.all('Scenario'):
        y = scenario_core.prop(o, 'nStartYear')
        if y and str(y).isdigit():
            return int(y)
    return 1936


def wikidata_api(path, p):
    """Wikidata (solo lectura) y asociación país/ciudad del escenario -> QID, anotada en el changelog del regionpack."""
    import wikidata
    try:
        s = scenario(p['scen']) if p.get('scen') else None
        year = int(p.get('year') or (scen_year(s) if s else 1936))
        lang = p.get('lang') or 'es'
        if path == '/api/wikidata/search':
            return {'hits': wikidata.search(p['q'], p.get('kind', 'city'), lang)}
        if path == '/api/wikidata/entity':
            e = wikidata.entity(p['id'], year, lang)
            if p.get('kind') == 'country':
                try:
                    e['cities'] = wikidata.major_cities(e['id'], year, lang)
                except wikidata.Offline as x:
                    e['cities_error'] = str(x)
                e['roundel'] = wikidata.roundel(e['id'], year, lang)
            return e
        if path == '/api/wikidata/links':
            pr = scen_pack_project(s)
            return {'links': next((e.get('wikidata', {}) for e in pr.changelog() if 'wikidata' in e), {}).get(p['scen'], {}), 'year': year}
        if path == '/api/wikidata/link':      # {scen, kind: city|country, name, id ('' = quitar)}
            pr = scen_pack_project(s)
            cl = pr.changelog()
            if os.path.exists(pr.changelog_path()):
                shutil.copy2(pr.changelog_path(), pr.changelog_path() + '.bak')       # respaldo antes de escribir
            ent = next((e for e in cl if 'wikidata' in e), None)
            if ent is None:
                ent = {'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': pr.pack, 'instalado': False, 'operaciones': ['wikidata'], 'wikidata': {}}
                cl.append(ent)
            sc = ent['wikidata'].setdefault(p['scen'], {})
            key = '%s:%s' % (p['kind'], p['name'])
            if p.get('id'):
                sc[key] = {'id': p['id'].upper(), 'label': p.get('label', ''), **({'surrendered': True} if p.get('surrendered') else {})}
            else:
                sc.pop(key, None)
            ent['fecha'] = time.strftime('%Y-%m-%d %H:%M:%S')
            changelog_keys.dump(cl, pr.changelog_path())
            return {'links': sc, 'changelog': pr.changelog_path()}
        raise KeyError(path)
    except wikidata.Offline as x:
        return {'offline': True, 'error': str(x)}
    except (ValueError, KeyError) as x:
        return {'error': str(x)}


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
                                        'culture': P(r, 'strCulture'),
                                        # nombre que muestra el juego (texto de sidName), para la etiqueta al pasar el cursor
                                        'text': (getattr(s, 'strings', None) or {}).get(P(r, 'sidName') or '') or None,
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
                forced = name in (getattr(register_regions, 'force', None) or ())
                if any(x in st.dirty for x in s.paths) and not forced:
                    out[name] = ['no se ha tocado: el escenario tiene cambios sin guardar en el editor de escenarios '
                                 '(guárdalos o reviértelos y usa «Aplicar changelog»)']
                    continue
                pk = scenario_core.pack_of(s)
                if check_pack and pk != PROJECT.pack:
                    notes.append('AVISO: este escenario usa el regionpack «%s», no «%s»: las regiones nuevas no existirán '
                                 'en su mapa hasta que use «%s»' % (pk, PROJECT.pack, PROJECT.pack))
                K = len(news) * 6 + 1     # pasos por escenario, para la barra de avance (cada acción con su texto)
                sp = lambda k, label: (pf or progress.part(5, 99))(i + k / float(K), len(names), '%s · %s' % (name, label))
                have_regions = {scenario_core.prop(r, 'strName') for r in s.regions()}
                for j, x in enumerate(news):
                    x = scenario_layers.for_scenario(x, name)     # dueño propio de este escenario, si el changelog lo trae
                    nm, mother = x['nombre'], x.get('madre')
                    if nm in have_regions:          # ya está en el escenario: no se vuelve a repartir población ni a cambiar de dueño
                        notes.append('%s: ya existía en el escenario; no se toca' % nm)
                        continue
                    sp(j * 6, '%s: creando la región' % nm)
                    if x.get('nacion'):         # nación nueva (con su capital) que recibe esta región
                        notes += scenario_new.prepare_region(s, x)
                    g_new = PROJECT.region_geom(nm)
                    terrain = x.get('terreno') or (new_region.TERRAIN_OF_TYPE.get(x.get('tipo')) if not mother else None)
                    try:
                        if x.get('mar'):
                            # region de mar nueva: waterWorld.xml y las flotas que quedan dentro
                            notes += scenario_layers.add_sea_region(s, nm, mother, x.get('texto'))
                            notes += scenario_layers.reassign_by_geometry(s, nm, g_new, sea=True)
                            notes += scenario_layers.reassign_ports(s, nm, g_new, PROJECT.region_geom)   # ciudades portuarias más cerca del mar nuevo
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
                        notes += scenario_new.finish_region(s, x, nm)                   # capital y país histórico de la nación nueva
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
                new_nats = {x['nacion']['name'] for x in news if x.get('nacion')}
                bad = scenario_new.check_nations(s, new_nats) if new_nats else []      # solo las naciones nuevas (un conjunto vacío las revisaba todas)
                notes += ['ERROR: ' + b for b in bad]
                sp(K - 1, 'guardando los archivos del escenario')
                if forced:      # «Registrar igualmente»: tenía cambios sin guardar; todo queda en memoria para «Guardar escenario»
                    notes.append('registrada sin guardar (el escenario tenía cambios sin guardar): falta «Guardar escenario»')
                else:
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
                        sea_into = into
                        if into and into in land:
                            # mar/lago/río que pasa a una región de TIERRA: las flotas y los puertos van al mar vecino de esa región
                            gi = next((g for g in PROJECT.m['regions'] if PROJECT.rname(g.index) == into), None)
                            seas_now = {P(r, 'strName') for r in s.regions(sea=True)} - {nm}
                            sea_into = next((PROJECT.rname(n) for n in (gi.neighbors if gi is not None else [])
                                             if PROJECT.m['regions'][n].u_type == editor_core.SEA and PROJECT.rname(n) in seas_now), None)
                            for c in s.all('City'):
                                if P(c, 'strPortForRegion') == nm:
                                    st.set_prop(c, 'strPortForRegion', sea_into or '')
                                    notes.append('puerto de %s: %s' % (P(c, 'strName'), sea_into or 'sin puerto (no queda mar vecino)'))
                        for g in s.all('Fleet'):
                            if P(g, 'strRegion') == nm:
                                if sea_into:
                                    st.set_prop(g, 'strRegion', sea_into)
                                notes.append('flota %s (%s) pasa a %s' % (P(g, 'strName'), P(g, 'strOwner'), sea_into or '¿?'))
                        notes += scenario_core.remove_new_region(s, nm, sea_into)
                        if into and into in land:
                            notes.append('%s (agua) pasa a ser parte de %s' % (nm, into))
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


def uninstalled_in_scenarios(pack):
    """{escenario: [regiones]} de los escenarios que usan 'pack' y tienen regiones que el mapa INSTALADO no tiene (p. ej. regiones
    nuevas registradas al guardar pero sin «Instalar»): el juego no los carga. Se mira lo que hay en disco, que es lo que lee el juego."""
    try:
        inst = set(scenario_layers.PackMap(pack).sea)
    except ValueError:
        return {}              # regionpack sin instalar: ya se avisa aparte
    rx = re.compile(r'<object type="(?:Sea)?Region"[^>]*>\s*<property name="strName" value="([^"]*)"')
    out = {}
    for name in scenario_core.scenarios_using(pack):
        d = os.path.join(scenario_core.SCEN_ROOT, name)
        bad = set()
        for f in os.listdir(d):
            if f.endswith('.xml'):
                bad |= {n for n in rx.findall(open(os.path.join(d, f), encoding='utf-8', errors='replace').read()) if n not in inst}
        bad -= {'BasicRegionLists', 'Historic'}
        if bad:
            out[name] = sorted(bad)
    return out


def keep_game_loadable(rep):
    """Tras registrar regiones nuevas (o quitarlas) en los escenarios del juego: si alguno queda con regiones que el mapa instalado
    no tiene, se instala ya el mapa (si no, el juego no carga esos escenarios) y se adecuan los demás escenarios del regionpack a
    los que les falten. Así una región nueva (p. ej. una isla) nunca deja escenarios a medias entre «Guardar» e «Instalar»."""
    if PROJECT.virtual:
        return
    bad = uninstalled_in_scenarios(PROJECT.pack)
    if not bad:
        return
    r = PROJECT.install('same', None, [], backup_root=scenario_core.BACKUP_ROOT)
    if not r.get('ok'):
        rep['not_loadable'] = bad
        rep.setdefault('warnings', []).append('no se pudo instalar el mapa: %s; esos escenarios no cargarán hasta «Instalar»' % r.get('msg'))
        return
    inc = pack_incompatibles(PROJECT.pack)
    fix = [n for n, v in inc.items() if v.get('faltan') or v.get('sobran')]
    rep['auto_install'] = {'regionpack': PROJECT.pack, 'scenarios': sorted(bad), 'adapted': adapt_scenarios(fix, PROJECT.pack) if fix else {}}
    left = uninstalled_in_scenarios(PROJECT.pack)
    if left:
        rep['not_loadable'] = left


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
            names = scenario_core.scenarios()
            return {'scenarios': names, 'loaded': sorted(SCEN),
                    'games': {n: gamepaths.scenario_game(os.path.join(scenario_core.SCEN_ROOT, n))['game'] for n in names}}
        if path == '/api/scen/tabs':
            s = scenario(q['name'])
            info = {'game': gamepaths.scenario_game(s.dir)}
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
            r = scenario(q['name']).tab_rows(q['tab'])
            return scenario_i18n.L(r) if q['tab'] == 'events' else r      # columnas «Clase», «Tipo», «Qué hace» en el idioma del editor
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
            try:
                missing, extra = scenario_layers.pack_mismatch(s, q['pack'])
            except ValueError as e:         # regionpack nuevo todavía sin instalar (solo existe como proyecto)
                return {'error': str(e), 'not_installed': True, 'pack': q['pack']}
            # regiones ya guardadas en el proyecto (y registradas en el escenario) que el mapa del juego aún no tiene: no «sobran»,
            # falta «Instalar»; mientras tanto el juego no carga el escenario («... that isn't part of the map»)
            pending = []
            if q['pack'] == PROJECT.pack:
                proj = {PROJECT.rname(g.index) for g in PROJECT.m['regions']}
                pending = [n for n in extra if n in proj]
                extra = [n for n in extra if n not in proj]
                missing = [n for n in missing if n in proj]
            return {'uses': scenario_core.pack_of(s), 'pack': q['pack'], 'missing': missing, 'extra': extra, 'pending': pending,
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
                                'owner': P(e, 'strOwner'), 'dir': P(e, 'nDirection')})
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
                                    'label': '%s · %s (%d)' % (P(e, 'strOwner'), P(e, 'strName') or t, n), 'owner': P(e, 'strOwner'),
                                    'dir': P(e, 'nDirection'), 'placed': bool(xy)})
            return {'points': pts}
        if path == '/api/scen/event_info':
            return scenario_i18n.L(scenario_events.describe(view_for(q['id']), scenario_core.STORE.get(q['id'])))
        if path == '/api/scen/ai_rules':
            return scenario_i18n.L(scenario_events.ai_rules(scenario(q['name']), q['country']))
        if path == '/api/scen/terrains':
            return {'terrains': scenario_events.terrains(scenario(q['name']))}
        if path == '/api/scen/region_export':
            # paquete de regiones (con ciudades y recursos; unidades si units=1) para importarlas en otro escenario
            return region_transfer.export_regions(scenario(q['name']), [x for x in q.get('regions', '').split('|') if x], q.get('units') == '1')
        if path == '/api/scen/start_research':
            return research_defaults.info(scenario(q['name']), q.get('country') or None)
        if path == '/api/scen/sprites':
            return sprite_scale.sprites(scenario(q['name']) if q.get('name') else None)
        if path == '/api/scen/fleet_ports':
            return {'ports': scenario_events.fleet_ports(view_for(q['id']), int(q['id']))}
        if path == '/api/scen/air_ranges':
            return {'ranges': scenario_events.air_ranges(scenario(q['name']))}
        if path == '/api/scen/terrain_colors':
            return scenario_i18n.L(scenario_events.terrain_colors(scenario(q['name'])))
        if path == '/api/scen/cultures':
            return {'cultures': scenario_events.cultures(scenario(q['name']))}
        if path == '/api/scen/ai':
            return scenario_layers.ai_summary(scenario(q['name']), q['country'])
        if path == '/api/scen/validate':
            import models_api
            names, adj = map_info()
            sc_ = scenario(q['name'])
            return {'issues': sc_.validate(names, adj) + scenario_layers.surrendered_issues(sc_) + scenario_layers.diplomacy_issues(sc_)
                    + scenario_layers.unknown_nation_issues(sc_) + scenario_layers.duplicate_issues(sc_)
                    + icon_defaults.issues(sc_.dir) + models_api.land_display_issues(sc_.dir)}
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
        if path == '/api/scen/fix_dupes':
            s = scenario(p['name'])
            notes = scenario_layers.remove_duplicates(s, p.get('remove'), p.get('remove_dupes'))
            return {'notes': notes, 'dirty': sorted(os.path.basename(x) for x in scenario_core.STORE.dirty if x in s.paths)}
        if path == '/api/scen/fix_nation_refs':
            # referencias a una nación inexistente: cambiarlas por otra o borrar las relaciones diplomáticas
            st, n = scenario_core.STORE, 0
            for it in p['items']:
                el = st.get(it['id'])
                if el is None:
                    continue
                if p.get('delete'):
                    if it.get('dip'):
                        st.remove(el); n += 1
                else:
                    st.set_prop(el, it['prop'], p['value']); n += 1
            s = scenario(p['name'])
            return {'notes': ['%d referencia(s) %s' % (n, 'borradas' if p.get('delete') else 'cambiadas a %s' % p['value'])],
                    'dirty': _dirty_of(s)}
        if path == '/api/scen/delete':
            # borrar un objeto suelto (p. ej. una relación diplomática con una nación que no existe)
            st, el = scenario_core.STORE, scenario_core.STORE.get(p['id'])
            if el is None:
                raise ValueError('ese objeto ya no existe')
            doc = st.doc_of.get(el)
            st.remove(el)
            return {'notes': ['borrado'], 'dirty': sorted(os.path.basename(x) for x in st.dirty if x == doc or doc is None)}
        if path == '/api/scen/update':
            v = view_for(p['id'])
            notes = v.update(p['id'], dict(p.get('values') or {}), p.get('move_children', True))
            return {'notes': notes, 'detail': v.detail(p['id'])}
        if path == '/api/scen/new_from':
            # escenario nuevo copiando uno existente entero (p. ej. «Scenario Template»: todo el mapa de un solo país para repartir)
            src = scenario(p['src'])
            if any(x in st.dirty for x in src.paths):
                raise ValueError('«%s» tiene cambios sin guardar: guárdalo o revierte antes de usarlo como base' % p['src'])
            r = scenario_layers.save_as_new(src, p['name'])
            if p.get('display'):
                f = os.path.join(scenario_core.SCEN_ROOT, r['scenario'], 'scenario.xml')
                raw = open(f, 'rb').read().decode('utf-8')
                raw = re.sub(r'(name="strDisplayName" value=")[^"]*(")', lambda m: m.group(1) + p['display'].replace('"', "'") + m.group(2), raw, count=1)
                open(f, 'wb').write(raw.encode('utf-8'))
            return {'name': r['scenario'], 'pack': scenario_core.pack_of(scenario(r['scenario']))}
        if path == '/api/scen/new_scratch':
            # escenario vacío sobre un regionpack (sin naciones): luego se le añaden naciones al crear regiones
            name = scenario_new.create_scenario(p['name'], p['pack'], p.get('template') or None, p.get('display') or None, p.get('description') or None)
            scenario_extra.ensure_dirs(os.path.join(scenario_core.SCEN_ROOT, name))
            return {'name': name, 'template': p.get('template') or '(plantilla del editor)'}
        if path == '/api/scen/check_nations':
            s = scenario(p['name'])
            return {'errors': scenario_new.check_nations(s)}
        if path == '/api/scen/flow_resource':
            # recurso de un flujo comercial o de ayuda (ResourceTrade): añadir, cambiar o quitar (cantidad 0)
            el = st.get(p['id'])
            notes = scenario_extra.flow_resource(st, el, p.get('resource'), p.get('amount'))
            return {'notes': notes, 'detail': view_for(p['id']).detail(p['id'])}
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
            return {'notes': notes, 'dirty': _dirty_of(s)}
        if path == '/api/scen/dirty':
            s = scenario(p['name'])
            return {'dirty': _dirty_of(s)}
        if path == '/api/scen/partisans':
            s = scenario(p['name'])
            return {'notes': scenario_core.set_partisans(s, bool(p['enable'])), 'partisans': scenario_core.partisans_state(s),
                    'dirty': sorted(os.path.basename(x) for x in st.dirty)}
        if path in ('/api/scen/event_template', '/api/scen/event_when', '/api/scen/event_remove', '/api/scen/ai_rule', '/api/scen/event_add',
                    '/api/scen/terrain', '/api/scen/terrain_delete', '/api/scen/culture', '/api/scen/culture_delete', '/api/scen/terrain_color'):
            # eventos (plantillas, fecha/turno, quitar con su cadena), reglas de la IA, tipos de terreno y culturas
            s = scenario(p['name'])
            E, i = scenario_events, None
            if path == '/api/scen/event_template':
                i, notes = E.create_template(s, p['kind'], p)
            elif path == '/api/scen/event_when':
                notes = E.set_when(s, p['id'], p.get('date') or None, p.get('turn'))
            elif path == '/api/scen/event_remove':
                notes = E.remove_chain(s, p['id'])
            elif path == '/api/scen/event_add':
                notes = E.event_add(s, p['id'], p['what'], p.get('spec') or {}, p.get('choice'))
            elif path == '/api/scen/ai_rule':
                op = p['op']
                if op == 'goal':
                    i, notes = E.ai_goal_set(s, p['country'], p.get('goal_type') or 'HGoalHelpCountryWinWar', p['a'], p['b'], p.get('id'))
                elif op == 'operation':
                    i, notes = E.ai_operation_set(s, p['country'], p, p.get('id'))
                elif op == 'trigger':
                    i, notes = E.trigger_set(s, p['country'], dict(p, country=p.get('target')), p.get('id'))
                elif op == 'delete':
                    notes = E.ai_rule_delete(s, p['id'])
                else:
                    raise ValueError('operación desconocida: %s' % op)
            elif path == '/api/scen/terrain':
                i, notes = E.terrain_save(s, p, p.get('id'))
            elif path == '/api/scen/culture':
                i, notes = E.culture_create(s, p.get('culture'), p.get('display'))
            elif path == '/api/scen/culture_delete':
                notes = E.culture_delete(s, p['id'], p.get('to'))
            elif path == '/api/scen/terrain_color':       # botón explícito: escribe UnifiedMapViews.xml del juego
                notes = E.terrain_color_set(s, p['terrain'], p['color'])
            else:
                notes = E.terrain_delete(s, p['id'], p.get('to'))
            return {'id': i, 'notes': scenario_i18n.L(notes), 'dirty': _dirty_of(s)}
        if path == '/api/scen/war_event':
            s = scenario(p['name'])
            i, notes = scenario_core.create_war_event(s, p['attacker'], p['target'], p['date'], p.get('pct', 80))
            return {'id': i, 'notes': notes, 'detail': s.detail(i)}
        if path == '/api/scen/historic_toggle':
            s = scenario(p['name'])
            r = scenario_layers.toggle_historic(s, p['country'], p['region'])
            r['dirty'] = _dirty_of(s)
            return r
        if path == '/api/scen/alliance_toggle':
            s = scenario(p['name'])
            r = scenario_layers.toggle_alliance(s, p['alliance'], p['country'])
            r['dirty'] = _dirty_of(s)
            return r
        if path == '/api/scen/set_string':
            s = scenario(p['name'])
            scenario_layers.set_string(s, p['sid'], p['value'])
            return {'dirty': _dirty_of(s)}
        if path == '/api/scen/geojson_import':
            import geojson_io
            s = scenario(p['name'])
            r = geojson_io.import_fc(s, PROJECT, p['geojson'], p.get('types'), opts=p.get('opts'))
            r['dirty'] = _dirty_of(s)
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
            return {'notes': notes, 'dirty': _dirty_of(s)}
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
            r['dirty'] = _dirty_of(s)
            return r
        if path == '/api/scen/create':
            # objeto nuevo: ciudad, recurso (productor) o ejército (como «Add» de ed.exe)
            s = scenario(p['name'])
            L_, k, SC_ = scenario_layers, p['kind'], scenario_create
            if k == 'city':
                if str(p.get('x', '')).strip() == '' or str(p.get('y', '')).strip() == '':
                    if not p.get('region'):     # antes: «could not convert string to float: ''»
                        raise ValueError('indica la posición (longitud y latitud) o elige la región de la ciudad')
                    p['x'], p['y'] = L_.region_point(s, p['region'])
                eid, notes = L_.create_city(s, p['obj_name'], float(p['x']), float(p['y']), p.get('ipus', 1), p.get('population', 0),
                                            p.get('display'), p.get('port') or None, p.get('region') or None, p.get('owner') or None)
                if p.get('capital'):            # «Es la capital de su país»
                    own = scenario_core.prop(scenario_core.STORE.get(eid), 'strOwner')
                    c_ = s.countries().get(own)
                    if c_ is not None:
                        scenario_core.STORE.set_prop(c_, 'strCapital', p['obj_name'].strip())
                        if not scenario_core.prop(c_, 'strOriginalCapital'):
                            scenario_core.STORE.set_prop(c_, 'strOriginalCapital', p['obj_name'].strip())
                        notes.append('capital de %s: %s' % (own, p['obj_name'].strip()))
            elif k == 'producer':
                eid, notes = L_.create_producer(s, p['obj_name'], p['resource'], float(p['x']), float(p['y']), p.get('output', 1))
            elif k == 'army':
                eid, notes = L_.create_army(s, p['owner'], p['obj_name'], p['region'], p.get('units') or [])
            elif k == 'country':
                eid, notes = SC_.create_country(s, p['obj_name'], p.get('template') or None, p.get('color') or None, p.get('ctype') or 'Minor',
                                                p.get('gov') or None, p.get('flag') or None, p.get('capital') or None, p.get('regions') or [],
                                                p.get('description'), p.get('new_capital') or None)
            elif k == 'airforce':
                eid, notes = SC_.create_airforce(s, p['owner'], p['obj_name'], p['region'], p.get('units') or [])
            elif k == 'govtype':
                eid, notes = SC_.create_govtype(s, p['obj_name'], p.get('display') or None, p.get('color') or None, p.get('icon') or None,
                                                p.get('base') or None)
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
            return {'id': eid, 'notes': notes, 'dirty': _dirty_of(s)}
        if path == '/api/scen/fix_diplomacy':
            s = scenario(p['name'])
            notes = scenario_layers.fix_diplomacy(s, p['items'])
            return {'notes': notes, 'dirty': _dirty_of(s)}
        if path == '/api/scen/claims_set':
            s = scenario(p['name'])
            notes = scenario_layers.set_claims(s, p['country'], p.get('list'), p.get('regions') or [])
            return {'notes': notes, 'dirty': _dirty_of(s)}
        if path == '/api/scen/fix_icons':
            # unidades / investigaciones sin imagen válida: la imagen por defecto de su familia (escribe ui/ del escenario)
            items = p.get('items')
            done = icon_defaults.fix(scenario(p['name']).dir, [tuple(x) for x in items] if items else None,
                                     writer=lambda f: image_tools.write_files(f, 'iconos-por-defecto'), log=lambda *_: None)
            return {'done': done}
        if path == '/api/scen/fix_capitals':
            s = scenario(p['name'])
            notes = scenario_layers.auto_capitals(s, p.get('countries'))
            return {'notes': notes, 'dirty': _dirty_of(s)}
        if path == '/api/scen/create_info':
            # listas para el diálogo de «Añadir»: recursos, plantillas de unidad, países, regiones de mar y tierra
            s = scenario(p['name'])
            P = scenario_core.prop
            return {'resources': sorted({P(x, 'strResource') for x in s.all('Producer') if P(x, 'strResource')}),
                    'units': sorted(P(t, 'strName') for t in s.all('UnitTemplate')),
                    'countries': sorted(s.countries()), 'land': sorted(P(r, 'strName') for r in s.regions(sea=False)),
                    'sea': sorted(P(r, 'strName') for r in s.regions(sea=True)),
                    'army': sorted(P(t, 'strName') for t in s.all('UnitTemplate') if P(t, 'eType') in ('UNIT_TYPE_ARMY', None, '')),
                    'navy': sorted(P(t, 'strName') for t in s.all('UnitTemplate') if P(t, 'eType') == 'UNIT_TYPE_NAVY'),
                    'air': sorted(P(t, 'strName') for t in s.all('UnitTemplate') if P(t, 'eType') == 'UNIT_TYPE_AIR_FORCE'),
                    'alliances': sorted(({'id': P(a, 'strINITAllianceName'), 'name': P(a, 'strDisplayName')} for a in s.all('Alliance')), key=lambda x: x['name'] or ''),
                    'govs': sorted({P(c, 'strGovType') for c in s.countries().values() if P(c, 'strGovType')}
                                   | {P(g, 'strName') for g in s.all('GovTypeTemplate') if P(g, 'strName')}),
                    'cultures': sorted({P(r, 'strCulture') for r in s.regions(sea=False) if P(r, 'strCulture')}
                                       | {P(c, 'strCultureName') for c in s.all('CultureTemplate') if P(c, 'strCultureName')}),
                    'terrains': sorted({P(t, 'strTerrain') for t in s.all('TerrainType') if P(t, 'strTerrain')}),
                    'outputs': sorted(P(e, 'strName') for e in s.all_prefix('FactoryOutput')),
                    'research': sorted(P(e, 'strName') for e in s.all_prefix('ResearchProj') if scenario_core.STORE.parent[e].get('type') == 'ResearchProjectSet'),
                    'templates': sorted(set(s.countries()) - {P(r, 'strOwner') for r in s.regions(sea=False)}
                                        - {P(g, 'strOwner') for t in ('Army', 'AirForce', 'Fleet') for g in s.all(t)}),
                    'cities': sorted(({'name': P(c, 'strName'), 'region': P(scenario_core.STORE.parent.get(c), 'strName'), 'owner': P(c, 'strOwner')} for c in s.all('City')), key=lambda x: x['name'])}
        if path == '/api/scen/move_point':
            # mover una ciudad o recurso a otro punto del mapa (si cae en otra región, pasa a ella con su dueño)
            s = scenario(p['name'])
            el = st.get(p['id'])
            if el.get('type') in scenario_events.UNIT_TYPES:     # ejércitos, aviación y flotas: cambian de región (o entran en un puerto)
                notes = scenario_events.move_unit(s, p['id'], p.get('x'), p.get('y'), p.get('port'))
                return {'notes': scenario_i18n.L(notes), 'dirty': sorted(os.path.basename(z) for z in st.dirty if z in s.paths)}
            x, y = float(p['x']), float(p['y'])
            if el.get('type') not in ('City', 'Producer'):
                raise ValueError('solo se pueden mover ciudades, recursos y unidades')
            cur = scenario_core.prop(st.parent.get(el), 'strName')
            try:
                rname = scenario_layers._land_region_at(s, x, y)[1]
            except ValueError:          # sobre el mar (o fuera del mapa): región de mar si la hay
                try:
                    rname = scenario_layers.pack_map(scenario_layers.scenario_pack(s)).region_at(x, y, sea=True)
                except Exception:
                    rname = None
            keep = p.get('keep')        # None: preguntar si cambia de región; True: sigue en la suya; False: pasa a la del punto
            if rname and rname != cur and keep is None:
                owner = next((scenario_core.prop(r, 'strOwner') for r in s.regions() if scenario_core.prop(r, 'strName') == rname), '')
                return {'ask': {'from': cur, 'to': rname, 'owner': owner or ''}}
            st.set_prop(el, 'vecPosition', scenario_layers._vec(x, y))
            notes = ['%s %s → %.4f, %.4f' % (el.get('type'), scenario_core.prop(el, 'strName'), x, y)]
            if rname and rname != cur and keep is False:
                notes += s.update(p['id'], {'__region': rname})
            elif rname != cur:
                notes.append('sigue dependiendo de %s (el punto queda fuera de ella)' % cur)
            return {'notes': notes, 'dirty': sorted(os.path.basename(z) for z in st.dirty if z in s.paths)}
        if path in ('/api/scen/model_texture', '/api/scen/model_import', '/api/scen/model_save_links'):
            # visor de modelos: vista previa (sin sprite_id) o guardar el .nif en el escenario (botón explícito) y vincular el Sprite
            import models_api
            s = scenario(p['name'])
            if path.endswith('save_links'):
                return {'notes': models_api.save_spritelib(s), 'dirty': sorted(os.path.basename(z) for z in st.dirty if z in s.paths)}
            r = (models_api.set_texture if path.endswith('texture') else models_api.import_model)(s, p)
            r['dirty'] = sorted(os.path.basename(z) for z in st.dirty if z in s.paths)
            return r
        if path == '/api/scen/sprites':
            # escala 3D (fScale): 'set' en memoria; 'save' escribe los archivos del juego (botón explícito) y lo anota; 'undo' / 'discard'
            op = p.get('op')
            notes = (sprite_scale.set_scales(p.get('values') or {}) if op == 'set' else sprite_scale.save_game() if op == 'save'
                     else sprite_scale.undo_last() if op == 'undo' else sprite_scale.discard() if op == 'discard' else None)
            if notes is None:
                raise ValueError('operación desconocida: %s' % op)
            return {'notes': notes}
        if path == '/api/scen/region_import':
            # importar regiones de otro escenario (src + regions) o de un paquete .json (bundle); dry: solo el plan
            s = scenario(p['name'])
            if p.get('bundle'):
                bundle = p['bundle']
            else:
                if p['src'] == p['name']:
                    raise ValueError('elige otro escenario de origen')
                bundle = region_transfer.export_regions(scenario(p['src']), p.get('regions') or [], bool(p.get('units', True)))
            if p.get('dry'):
                return region_transfer.plan(s, bundle)
            notes = region_transfer.apply(s, bundle, p.get('mapping') or {}, bool(p.get('cities', True)), bool(p.get('units', True)))
            return {'notes': notes, 'dirty': sorted(os.path.basename(z) for z in st.dirty if z in s.paths)}
        if path == '/api/scen/start_research':
            # proyectos completados al empezar (unidades que se pueden fabricar): para todos (country vacío) o para un país
            s = scenario(p['name'])
            notes = research_defaults.set_country(s, p['country'], p.get('on') or []) if p.get('country') else research_defaults.set_default(s, p.get('on') or [])
            return {'notes': notes, 'dirty': sorted(os.path.basename(z) for z in st.dirty if z in s.paths)}
        if path == '/api/scen/rename_country':
            # cambiar el nombre de un país: solo cómo se ve (SID) o también el nombre interno, archivos y referencias
            s = scenario(p['name'])
            notes = scenario_layers.rename_country(s, p['old'], p['new'], bool(p.get('code')), keep_shown=bool(p.get('keep_shown')))
            c = s.countries().get(p['new'] if p.get('code') else p['old'])
            return {'notes': notes, 'id': st.eid(c) if c is not None else None, 'dirty': sorted(os.path.basename(z) for z in st.dirty if z in s.paths)}
        if path == '/api/scen/set_direction':
            # orientación de una ciudad o unidad (nDirection, grados; en ed.exe con clic derecho)
            s = scenario(p['name'])
            notes = scenario_events.set_direction(s, p['id'], p['deg'])
            return {'notes': scenario_i18n.L(notes), 'dirty': sorted(os.path.basename(z) for z in st.dirty if z in s.paths)}
        if path == '/api/scen/open_folder':
            # abrir en el Explorador la carpeta de un escenario o de un regionpack (solo lectura: no cambia nada)
            if p.get('scenario'):
                d = os.path.join(scenario_core.SCEN_ROOT, p['scenario'])
            else:
                d = os.path.join(editor_core.MAPS, p.get('pack') or PROJECT.pack)
                if not os.path.isdir(d) and (p.get('pack') or PROJECT.pack) == PROJECT.pack:
                    d = PROJECT.dir          # regionpack nuevo aún sin instalar: su proyecto del editor
            d = os.path.abspath(d)
            if not os.path.isdir(d):
                raise ValueError('no existe la carpeta %s' % d)
            if not p.get('dry'):
                os.startfile(d)
            return {'notes': ['abierta %s' % d], 'path': d}
        if path == '/api/scen/port_options':
            # mares para el puerto de una ciudad: los vecinos de su región primero (en el mapa del regionpack del escenario)
            s = scenario(p['name'])
            el = st.get(p['id'])
            region = scenario_core.prop(st.parent.get(el), 'strName')
            seas = sorted(scenario_core.prop(r, 'strName') for r in s.regions(sea=True))
            try:
                pm = scenario_layers.pack_map(scenario_layers.scenario_pack(s))
                near = sorted(n for n in pm.nb.get(region, []) if pm.sea.get(n))
            except Exception:
                near = []
            return {'region': region, 'port': scenario_core.prop(el, 'strPortForRegion') or '', 'near': [n for n in near if n in seas],
                    'far': [n for n in seas if n not in near]}
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
            return {'notes': notes, 'dirty': _dirty_of(s)}
        if path == '/api/scen/playable':
            s = scenario(p['name'])
            notes = scenario_layers.set_playable(s, p['countries'])
            return {'notes': notes, 'dirty': _dirty_of(s)}
        if path == '/api/scen/set_pack':
            # cambiar de regionpack también adecua las regiones: si no coinciden con su mapa, el juego no carga el escenario
            s = scenario(p['name'])
            if p.get('only_switch'):
                notes = scenario_layers.set_pack(s, p['pack'])
            else:
                notes = scenario_layers.pack_sync_apply(s, p['pack'], True, p.get('pop_mode') or 'area')['notes']
            return {'notes': notes, 'dirty': _dirty_of(s)}
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


# ------------------------------------------------------------------ comparador de escenarios y partidas guardadas
import scenario_compare  # noqa: E402
import savegame  # noqa: E402

SAVE_CACHE = {}     # (ruta, mtime, escenario) -> SaveData


def _save_for(s, path):
    path = os.path.abspath(path)
    if not path.lower().endswith('.mlc') or not os.path.isfile(path):
        raise ValueError('no es una partida guardada (.mlc): %s' % path)
    k = (path, os.path.getmtime(path), s.name)
    if k not in SAVE_CACHE:
        SAVE_CACHE.clear()
        SAVE_CACHE[k] = savegame.load_for(s, path)
    return SAVE_CACHE[k]


def _dirty_of(s):
    # todo lo que está sin guardar dentro de la carpeta del escenario: también game/stringTable.xml, que no está en s.paths
    # (si no, tras «Adecuar» con solo textos cambiados, «Guardar escenario» quedaba desactivado)
    base = os.path.abspath(s.dir) + os.sep
    return sorted(os.path.relpath(x, s.dir).replace(os.sep, '/') if not x in s.paths else os.path.basename(x)
                  for x in scenario_core.STORE.dirty if x in s.paths or os.path.abspath(x).startswith(base))


# ---------------------------------------------------------------- registro del juego («¿por qué no carga?»)
import game_log_report  # noqa: E402
GAMELOG = {'thread': None, 'stop': None, 'path': None, 'error': None}


def gamelog_api(path, p):
    """start: abre «Game Log.bat» en su ventana (se cierra con Ctrl+C) o, en el .exe (sin Python), escucha aquí mismo hasta stop.
    status / report: el último logs/juego_*.log analizado (game_log_report). Solo escucha y lee; no toca el juego."""
    if path == '/api/gamelog/start':
        bat = os.path.join(ROOT, 'Game Log.bat')
        if not getattr(sys, 'frozen', False) and os.path.exists(bat) and p.get('mode') != 'editor':
            import subprocess
            subprocess.Popen(['cmd', '/c', bat], cwd=ROOT, creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
            return {'mode': 'window'}
        if GAMELOG['thread'] and GAMELOG['thread'].is_alive():
            return {'mode': 'editor', 'path': GAMELOG['path']}
        import game_log
        os.environ.setdefault('MH_ROOT', ROOT)
        game_log.LOGS = os.path.join(ROOT, 'logs')
        GAMELOG.update(stop=threading.Event(), path=None, error=None)

        def run():
            try:
                game_log.main(stop=GAMELOG['stop'], started=lambda x: GAMELOG.update(path=x))
            except BaseException as e:     # sys.exit si el canal está ocupado (otra captura o DebugView)
                GAMELOG['error'] = str(e)
        GAMELOG['thread'] = threading.Thread(target=run, daemon=True)
        GAMELOG['thread'].start()
        return {'mode': 'editor'}
    if path == '/api/gamelog/stop':
        if GAMELOG['stop']:
            GAMELOG['stop'].set()
        if GAMELOG['thread']:
            GAMELOG['thread'].join(2)
        return {'stopped': True, 'path': GAMELOG['path']}
    if path == '/api/gamelog/status':
        return {'running': bool(GAMELOG['thread'] and GAMELOG['thread'].is_alive()), 'error': GAMELOG['error']}
    if path == '/api/gamelog/report':
        game_log_report.LOGS = os.path.join(ROOT, 'logs')
        f = p.get('file')
        r = game_log_report.analyze(os.path.join(game_log_report.LOGS, os.path.basename(f)) if f else None)
        r['running'] = bool(GAMELOG['thread'] and GAMELOG['thread'].is_alive())
        return r
    raise KeyError(path)


def cmp_get(path, q):
    with SCEN_LOCK:
        if path == '/api/cmp/sources':
            return {'sources': scenario_compare.sources(), 'scenarios': scenario_core.scenarios(), 'loaded': sorted(SCEN),
                    'game': gamepaths.CURRENT[0]}
        if path == '/api/save/list':
            return {'root': savegame.SAVES_ROOT, 'saves': savegame.list_saves(), 'scenarios': scenario_core.scenarios()}
    raise KeyError(path)


def cmp_post(path, p):
    with SCEN_LOCK:
        if path == '/api/cmp/diff':
            if p.get('reload'):
                scenario_compare.forget_source(p['source'])
            tgt = scenario(p['target'])
            src = scenario_compare.open_source(p['source'])
            if os.path.normcase(os.path.abspath(src.dir)) == os.path.normcase(os.path.abspath(tgt.dir)):
                raise ValueError('el origen y el destino son el mismo escenario')
            r = scenario_compare.diff(tgt, src)
            r['dirty'] = _dirty_of(tgt)
            return r
        if path == '/api/cmp/transfer':
            tgt = scenario(p['target'])
            src = scenario_compare.open_source(p['source'])
            r = scenario_compare.transfer(tgt, src, p.get('items') or {})
            log('comparador: %s ← %s: %s' % (p['target'], src.name, '; '.join(r['notes']) or 'nada'))
            r['dirty'] = _dirty_of(tgt)
            return r
        if path == '/api/save/plan':
            s = scenario(p['scenario'])
            sv = _save_for(s, p['path'])
            rep = savegame.pack_report(s, sv)
            pl = savegame.plan(s, sv, {'alias': rep['alias']})
            summ = sv.summary()
            summ['forces'] = dict(summ['forces'])
            return {'summary': summ, 'plan': pl, 'pack': rep, 'dirty': _dirty_of(s)}
        if path == '/api/save/create':
            # escenario nuevo (carpeta aparte) desde la partida; el escenario base no se toca
            s = scenario(p['scenario'])
            r = savegame.create_scenario(scenario_core.SCEN_ROOT, s.name, os.path.abspath(p['path']), p['new_name'],
                                         p.get('owners', True), p.get('ipus', True), p.get('forces', True), p.get('adapt', True))
            log('partida → escenario %s (desde %s): %s' % (r['scenario'], s.name, '; '.join(r['notes'])))
            return r
    raise KeyError(path)


# ------------------------------------------------------------------ imagenes (titulo, banderas, iconos)
import image_tools  # noqa: E402
import image_assets  # noqa: E402

IMG_LOCK = threading.Lock()


def img_get(h, path, q):
    try:
        if path == '/api/img/scenarios':
            return h.send(200, {'scenarios': scenario_core.scenarios()})
        if path == '/api/img/titles':
            return h.send(200, {'files': image_tools.title_info(q['scen'])})
        if path == '/api/img/raw':
            return h.send(200, image_tools.png_bytes(image_tools.resolve_rel(q['rel']), int(q.get('max', 0)) or None, bool(q.get('crop'))), 'image/png')
        if path == '/api/img/countries':
            return h.send(200, image_tools.countries(q['scen']))
        if path == '/api/img/country':
            folder = image_tools.flag_folder(q['scen'], q['name']) if q.get('resolve') else q['name']
            return h.send(200, {'files': image_tools.country_files(q['scen'], folder), 'folder': folder})
        if path == '/api/img/icons':
            return h.send(200, image_tools.icons_info(q['scen']))
        if path == '/api/img/flag':     # bandera pequena de un pais (iconos de la pestana Nations)
            png = image_tools.flag_png(q.get('scen') or q['scenario'], q['country'])
            if png is None:
                return h.send(404, {'error': 'sin bandera'})
            return h.send(200, png, 'image/png')
        if path == '/api/img/asset':        # un icono/imagen con todas sus variantes (propia del escenario o del juego)
            return h.send(200, image_assets.info(q['scen'], q['kind'], q.get('name', '')))
        if path == '/api/img/asset/export':
            png, fname = image_assets.export_png(q['scen'], q['kind'], q.get('name', ''), q.get('group'))
            h.send_response(200)
            h.send_header('Content-Type', 'image/png')
            h.send_header('Content-Length', str(len(png)))
            h.send_header('Content-Disposition', 'attachment; filename="%s"' % fname.replace('"', ''))
            h.send_header('Cache-Control', 'no-store')
            h.end_headers()
            h.wfile.write(png)
            return
        if path == '/api/img/nations':      # naciones sin color o sin bandera (marcas de la lista)
            return h.send(200, image_tools.nation_status(q['scen']))
        if path == '/api/img/catalog':
            return h.send(200, {'groups': image_assets.catalog(q['scen'])})
        if path == '/api/img/ui/list':
            return h.send(200, image_assets.ui_list(q['scen'], q.get('rel', '')))
        if path == '/api/img/ui/own':
            return h.send(200, {'files': image_assets.ui_own(q['scen'])})
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
        elif path == '/api/img/fetch':      # bandera/imagen desde una URL que da el usuario
            return image_tools.fetch_url(p.get('url'))
        elif path == '/api/img/lobby/preview':     # retrato del lobby por capas (bandera, monumento, líder)
            return image_tools.lobby_preview(p)
        elif path == '/api/img/lobby/write':
            rep = image_tools.lobby_write(p)
        elif path == '/api/img/asset/preview':
            return image_assets.preview(p)
        elif path == '/api/img/asset/write':
            rep = image_assets.write(p)
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
        packs = all_packs()
        select_pack(pack if pack in packs else 'World')
        PROJECT_VERSION[0] += 1
        log('juego: %s (%s)' % (gamepaths.GAMES[key]['label'], gamepaths.path(key)))
        return {'ok': True, 'game': key, 'pack': PROJECT.pack}


def free_name(folder, name, dst):
    """name si no existe en folder; si no, «name <juego>», «name <juego> 2»..."""
    if not os.path.exists(os.path.join(folder, name)):
        return name
    base = '%s %s' % (name, gamepaths.GAMES[dst]['short'])
    cand, i = base, 2
    while os.path.exists(os.path.join(folder, cand)):
        cand, i = '%s %d' % (base, i), i + 1
    return cand


def xconvert_check(scen, pack):
    """Para el diálogo «Convertir a Gold/MH1» del editor de regiones: destino y nombres libres sugeridos."""
    src = gamepaths.CURRENT[0]
    dst = 'gold' if src == 'mh1' else 'mh1'
    out = {'from': src, 'to': dst, 'to_short': gamepaths.GAMES[dst]['short'], 'installed': gamepaths.installed(dst)}
    if not out['installed']:
        return out
    sr, mr = gamepaths.scen_root(dst), gamepaths.maps_dir(dst)
    out.update(scen_root=sr, maps_dir=mr)
    if scen:
        out['scen'] = {'name': scen, 'exists': os.path.exists(os.path.join(sr, scen)), 'suggest': free_name(sr, scen, dst),
                       'map': __import__('convert_scenario').map_of(os.path.join(scenario_core.SCEN_ROOT, scen))}
    if pack:
        out['pack'] = {'name': pack, 'exists': os.path.exists(os.path.join(mr, pack)), 'suggest': free_name(mr, pack, dst)}
    return out


def xconvert_api(p):
    """Convierte el escenario y/o el regionpack (tal como están instalados) al otro juego. Nunca sobrescribe."""
    import convert_scenario
    import port_regionpack
    src = gamepaths.CURRENT[0]
    dst = 'gold' if src == 'mh1' else 'mh1'
    if not gamepaths.installed(dst):
        raise ValueError('no está instalado %s' % gamepaths.GAMES[dst]['label'])
    res = {'to': dst}
    pack, pack_out = p.get('pack'), (p.get('pack_out') or '').strip() or p.get('pack')
    scen, scen_out = p.get('scen'), (p.get('scen_out') or '').strip() or p.get('scen')
    for n in (pack_out, scen_out):
        if n and (re.search(r'[\\/:*?"<>|]', n) or n.strip('. ') != n):
            raise ValueError('nombre no válido: %s' % n)
    if scen and os.path.exists(os.path.join(gamepaths.scen_root(dst), scen_out)):
        raise ValueError('ya existe el escenario %s en %s (no se sobrescribe)' % (scen_out, gamepaths.GAMES[dst]['short']))
    if pack and os.path.exists(os.path.join(gamepaths.maps_dir(dst), pack_out)):
        raise ValueError('ya existe el regionpack %s en %s (no se sobrescribe)' % (pack_out, gamepaths.GAMES[dst]['short']))
    if pack:
        res['regionpack'] = port_regionpack.port_pack(pack, src, dst, pack_out, log=log)
    if scen:
        rep = convert_scenario.convert(os.path.join(scenario_core.SCEN_ROOT, scen), dst,
                                       os.path.join(gamepaths.scen_root(dst), scen_out), src,
                                       infra=p.get('infra', 'auto'), skip_images=bool(p.get('skip_images')), regionpack='no', log=log)
        old = convert_scenario.map_of(rep['salida'])
        if pack and old == pack and pack_out != pack:
            convert_scenario.retarget_map(rep['salida'], pack, pack_out)
            rep['notas'].append('el escenario usa el regionpack convertido: %s' % pack_out)
        res['resumen'] = convert_scenario.summary(rep)
        res['scen'] = rep['salida']
    return res


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
                                   remove_partisan_event=p.get('remove_partisan_event', True),
                                   skip_images=bool(p.get('skip_images')), regionpack=p.get('regionpack', 'auto'), log=log)
    rep['resumen'] = convert_scenario.summary(rep)
    return rep


def all_packs():
    """Regionpacks del juego y los nuevos aún sin instalar (solo existen como proyecto)."""
    return sorted(set(editor_core.Project.packs()) | set(new_pack.pending_packs(project_dir('World'))))


def select_pack(pack):
    global PROJECT
    if pack not in all_packs():
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


def ai_post(path, p):
    # chat de IA (ai_chat.py): config de claves locales, llamada al proveedor, comprobación de rutas y respaldo
    try:
        if path == '/api/ai/config':
            return ai_chat.save(p)
        if path == '/api/ai/models':
            ms = ai_chat.models(p['provider'], p.get('key'), p.get('base'))
            return {'models': ms, 'best': ai_chat.best_model(p['provider'], ms)}
        if path == '/api/ai/chat':
            return ai_chat.chat(p.get('system') or '', p['messages'], p.get('tools') or [])
        if path == '/api/ai/check':
            return {'error': ai_chat.check_call(p.get('method', 'GET'), p.get('path', '')), 'disk': bool(ai_chat.DISK.match(p.get('path', '')))}
        if path == '/api/ai/backup':
            import scenario_core
            d = ai_chat.backup_scenario(scenario_core.SCEN_ROOT, scenario_core.BACKUP_ROOT, p.get('scenario'))
            if d:
                log('IA: copia de %s en %s' % (p.get('scenario'), d))
            return {'backup': d}
    except Exception as e:
        return {'error': str(e)}
    return {'error': 'ruta IA desconocida'}


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
        if a.pack not in all_packs():
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
