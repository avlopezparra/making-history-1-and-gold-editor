"""Nucleo del editor de regiones: proyecto de trabajo, contornos, guardado como traspasos, historial e instalacion.

El proyecto es una carpeta con:
  xml/        regions.bin, borders.brd, regions.nts (estado de trabajo)
  tiles/      texturas OperationalTerrain que el proyecto ha modificado
  history/    instantaneas antes de cada guardado (para deshacer)
Se crea copiando el estado actual del juego. Nada toca el juego hasta "instalar".
"""
import json
import os
import shutil
import struct
import threading
import time

from shapely import make_valid
from shapely.geometry import shape, Polygon, MultiPolygon, mapping
from shapely.ops import unary_union
from shapely.validation import explain_validity

import mhmap
import outlines
from move_border import signed_area
from transfer import apply_transfers, SEA
import new_region
from paint_changes import paint_tiles
from fix_texture import decode, tile_name, SIZE

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Making History The Calm and The Storm"
MAPS = os.path.join(GAME, r"Modern Europe\system\DisplayLibraries\Maps")
MAP_DIR = os.path.join(MAPS, "World")   # compatibilidad; cada proyecto usa self.map_dir
SCEN_DIR = os.path.join(GAME, r"Modern Europe\system\scenarios")
XML_FILES = ('regions.bin', 'borders.brd', 'regions.nts')
MIN_AREA = 1e-10
SLIVER = 1e-3        # grados2: un trozo tan pequeno, junto a otros mucho mayores, es un roce del borde, no un recorte


def drop_slivers(pieces):
    """Quita los trozos diminutos que salen al rozar el borde de una region vecina (rompen la malla al traspasarlos)."""
    big = max((p.area for p, _ in pieces), default=0)
    return [(p, s) for p, s in pieces if p.area >= SLIVER or p.area >= 0.02 * big]


def load_renames(map_dir):
    """{nombre en regions.bin: nombre en los escenarios} segun los RegionRename de map.xml (se aplican a la vez)."""
    import xml.etree.ElementTree as ET
    out = {}
    f = os.path.join(map_dir, 'xml', 'map.xml')
    if os.path.exists(f):
        for o in ET.parse(f).getroot().iter('object'):
            if o.get('type') == 'RegionRename':
                pr = {p.get('name'): p.get('value') for p in o.findall('property')}
                if pr.get('strOldRegionName') and pr.get('strNewRegionName'):
                    out[pr['strOldRegionName']] = pr['strNewRegionName']
    return out


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def polys_of(g):
    return [p for p in getattr(g, 'geoms', [g]) if p.geom_type == 'Polygon' and p.area > MIN_AREA]


_SESSION_PROJECTS = set()     # proyectos ya abiertos en esta sesion (su historial de instantaneas es de esta sesion)


class Project:
    def __init__(self, folder, backup_dir, pack=None):
        self.dir = folder
        os.makedirs(folder, exist_ok=True)
        pf = os.path.join(folder, 'pack.json')
        meta = json.load(open(pf)) if os.path.exists(pf) else {}
        self.pack = pack or meta.get('pack') or 'World'      # regionpack que edita este proyecto (el de su carpeta)
        if meta.get('pack') and pack and meta['pack'] != pack:
            print('AVISO: %s decía regionpack %s; se usa %s (el de la carpeta)' % (pf, meta['pack'], pack))
            meta['decided'] = False
        self.decided = meta.get('decided', False)              # ya se pregunto donde instalar
        self.map_dir = os.path.join(MAPS, self.pack)
        self.backup_dir = os.path.join(backup_dir, self.pack) if self.pack != 'World' else backup_dir
        self.xml = os.path.join(folder, 'xml')
        self.tiles = os.path.join(folder, 'tiles')
        self.history = os.path.join(folder, 'history')
        self.lock = threading.RLock()
        if not os.path.exists(os.path.join(self.xml, 'regions.bin')):
            os.makedirs(self.xml, exist_ok=True)
            for f in XML_FILES:
                shutil.copy2(os.path.join(self.map_dir, 'xml', f), os.path.join(self.xml, f))
        os.makedirs(self.tiles, exist_ok=True)
        os.makedirs(self.history, exist_ok=True)
        # «Volver / Rehacer» solo dentro de la sesion: al abrir el proyecto por primera vez se borran las instantaneas
        # de sesiones anteriores (lo que queda de ellas esta en el changelog)
        key = os.path.normcase(os.path.abspath(folder))
        if key not in _SESSION_PROJECTS:
            _SESSION_PROJECTS.add(key)
            for d in os.listdir(self.history):
                if d.isdigit() or d == 'rehacer':
                    shutil.rmtree(os.path.join(self.history, d), ignore_errors=True)
        self.reload()

    # ------------------------------------------------------------------ estado
    def installed_state(self):
        """Compara la copia del proyecto con el regionpack instalado en el juego.
        'same': iguales; 'pending': cambios del proyecto sin instalar; 'changed': el del juego cambió fuera del editor."""
        import filecmp
        files = list(XML_FILES) + (['map.xml'] if os.path.exists(os.path.join(self.xml, 'map.xml')) else [])
        same = all(filecmp.cmp(os.path.join(self.xml, f), os.path.join(self.map_dir, 'xml', f), shallow=False) for f in files)
        if same:
            return 'same'
        return 'pending' if any(not e.get('instalado') for e in self.changelog()) else 'changed'

    def prune_changelog(self, log=print):
        """Quita del changelog las regiones nuevas que ya no existen en el mapa (p. ej. si se puso encima un regionpack
        virgen y quedó el changelog.json viejo): el changelog debe describir el mapa tal como es."""
        cl = self.changelog()
        if not cl:
            return []
        names = {self.rname(g.index) for g in self.m['regions']} | {g.name for g in self.m['regions']}
        gone = []
        for e in cl:
            keep = [x for x in e.get('regiones_nuevas', []) if x.get('nombre') in names]
            gone += [x.get('nombre') for x in e.get('regiones_nuevas', []) if x.get('nombre') not in names]
            e['regiones_nuevas'] = keep
        if gone:
            g = set(gone)
            for e in cl:   # traspasos y vecindades de esas regiones tampoco describen ya el mapa
                e['traspasos'] = [t for t in e.get('traspasos', []) if t.get('de') not in g and t.get('a') not in g]
                e['vecindades_nuevas'] = [v for v in e.get('vecindades_nuevas', []) if not g & set(v)]
            cl = [e for e in cl if e.get('regiones_nuevas') or e.get('regiones_eliminadas') or e.get('traspasos')
                  or e.get('centros') or e.get('vecindades_nuevas') or e.get('renombradas')]
            json.dump(cl, open(self.changelog_path(), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            log('changelog: quitadas regiones que no están en el mapa: %s' % ', '.join(gone))
        return gone

    # ------------------------------------------------------------------ revisar el changelog contra World
    def review_changelog(self, base='World'):
        """Compara el mapa del proyecto con el regionpack 'base' (World) y con el changelog. Filas:
        'ok': región nueva en el mapa y en el changelog; 'missing': en el mapa pero no en el changelog (se propone su madre);
        'stale': en el changelog pero no en el mapa. 'deleted': regiones de 'base' que el mapa ya no tiene."""
        if base == self.pack:
            raise ValueError('el regionpack es el mismo que la base (%s)' % base)
        bdir = os.path.join(MAPS, base)
        bm = mhmap.load_map(os.path.join(bdir, 'xml'))
        bren = load_renames(bdir)
        bidx = {bren.get(g.name, g.name): g.index for g in bm['regions']}
        R = self.m['regions']
        cur = {self.rname(g.index): g for g in R}
        logged = {}
        for e in self.changelog():
            for x in e.get('regiones_nuevas', []):
                logged[x['nombre']] = (e.get('fecha'), x)
        rows = []
        for n, g in cur.items():
            if n in bidx:
                continue
            sea = g.u_type == SEA
            if n in logged:
                x = logged[n][1]
                rows.append({'name': n, 'status': 'ok', 'sea': sea, 'mother': x.get('madre'), 'owner': x.get('pais'), 'date': logged[n][0]})
                continue
            # madre propuesta: la vecina (que existe en la base) cuya forma en la base más se solapa con la región nueva
            gn = new_region.mesh_polygon(self.m, g.index)
            best, area = None, 0.0
            for nb in g.neighbors:
                m = self.rname(nb)
                if nb == g.index or m not in bidx or (R[nb].u_type == SEA) != sea:
                    continue
                gb = new_region.mesh_polygon(bm, bidx[m])
                a = gn.intersection(gb).area if gn is not None and gb is not None else 0.0
                if a > area:
                    best, area = m, a
            rows.append({'name': n, 'status': 'missing', 'sea': sea, 'mother': best, 'u_type': g.u_type})
        for n, (fecha, x) in logged.items():
            if n not in cur:
                rows.append({'name': n, 'status': 'stale', 'sea': bool(x.get('mar')), 'mother': x.get('madre'), 'date': fecha})
        deleted = sorted(n for n in bidx if n not in cur)
        return {'base': base, 'pack': self.pack, 'rows': sorted(rows, key=lambda r: (r['status'] != 'stale', r['name'])), 'deleted': deleted}

    def apply_review(self, keep, add, base='World'):
        """Deja en el changelog solo las regiones nuevas de 'keep' y anota las de 'add' (regiones del mapa que faltaban).
        Si el proyecto coincide con el regionpack instalado, el changelog del juego se actualiza igual."""
        with self.lock:
            rev = self.review_changelog(base)
            rows = {r['name']: r for r in rev['rows']}
            keep = set(keep or [])
            cl = self.changelog()
            gone = set()
            for e in cl:
                for x in e.get('regiones_nuevas', []):
                    if x['nombre'] not in keep:
                        gone.add(x['nombre'])
                e['regiones_nuevas'] = [x for x in e.get('regiones_nuevas', []) if x['nombre'] in keep]
                e['traspasos'] = [t for t in e.get('traspasos', []) if t.get('de') not in gone and t.get('a') not in gone]
                e['vecindades_nuevas'] = [v for v in e.get('vecindades_nuevas', []) if not gone & set(v)]
            cl = [e for e in cl if e.get('regiones_nuevas') or e.get('regiones_eliminadas') or e.get('traspasos')
                  or e.get('centros') or e.get('vecindades_nuevas') or e.get('renombradas')]
            news = []
            for n in add or []:
                r = rows.get(n)
                if not r or r['status'] != 'missing':
                    continue
                news.append({'nombre': n, 'texto': n, 'madre': r['mother'], 'pais': None, 'tipo': r.get('u_type'),
                             'controlador': None, 'terreno': None, 'mar': r['sea'], 'poblacion': None, 'historicos': None})
            same = self.installed_state() == 'same'
            if news:
                cl.append({'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': self.pack, 'instalado': same,
                           'operaciones': ['revision_changelog'], 'regiones_nuevas': news})
            json.dump(cl, open(self.changelog_path(), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            if same:
                shutil.copy2(self.changelog_path(), os.path.join(self.map_dir, 'changelog.json'))
            return {'removed': sorted(gone), 'added': [x['nombre'] for x in news], 'game_updated': same}

    def rename_region(self, old, new, text=None):
        """Cambia el nombre (en los escenarios) de una región: RegionRename en la copia del proyecto de map.xml
        (se instala con «Instalar») y una entrada «renombradas» en el changelog para adecuar otros escenarios."""
        import re
        with self.lock:
            new = (new or '').strip()
            if not re.match(r"^[A-Za-z0-9 .'()-]+$", new):
                raise ValueError('nombre no válido: usa letras sin acentos, números, espacios, puntos, guiones o apóstrofos')
            names = {self.rname(g.index) for g in self.m['regions']}
            if old not in names:
                raise ValueError('no existe la región %s' % old)
            if new in names:
                raise ValueError('ya existe una región llamada %s' % new)
            raw = {v: k for k, v in self.renames.items()}.get(old, old)    # nombre en regions.bin
            mp = os.path.join(self.xml, 'map.xml')
            if not os.path.exists(mp):
                shutil.copy2(os.path.join(self.map_dir, 'xml', 'map.xml'), mp)
            t = open(mp, encoding='utf-8', errors='replace').read()
            nl = '\r\n' if '\r\n' in t else '\n'
            obj = re.compile(r'[ \t]*<object type="RegionRename"[^>]*>\s*<property name="strOldRegionName" value="'
                             + re.escape(raw) + r'"/>\s*<property name="strNewRegionName" value="[^"]*"/>\s*</object>[ \t]*\r?\n?')
            block = ('\t\t<object type="RegionRename" name="objRenames">' + nl
                     + '\t\t\t<property name="strOldRegionName" value="' + raw + '"/>' + nl
                     + '\t\t\t<property name="strNewRegionName" value="' + new + '"/>' + nl + '\t\t</object>' + nl)
            m = obj.search(t)
            if m:
                t = t[:m.start()] + ('' if new == raw else block) + t[m.end():]
            elif new != raw:
                last = list(re.finditer(r'<object type="RegionRename"[^>]*>.*?</object>[ \t]*\r?\n?', t, flags=re.S))
                if not last:
                    raise ValueError('map.xml no tiene lista de RegionRename donde añadirlo')
                t = t[:last[-1].end()] + block + t[last[-1].end():]
            open(mp, 'w', encoding='utf-8', newline='').write(t)
            cl = self.changelog()
            for e in cl:
                for x in e.get('regiones_nuevas', []):
                    if x.get('nombre') == old:
                        x['nombre'] = new
            cl.append({'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': self.pack, 'instalado': False,
                       'operaciones': ['renombrar'], 'renombradas': [{'de': old, 'a': new, 'texto': text or new, 'interno': raw}]})
            json.dump(cl, open(self.changelog_path(), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            self.reload()
            return {'raw': raw}

    def load_installed(self):
        """Vuelve a copiar en el proyecto el regionpack del juego (con su changelog); borra «Volver / Rehacer»."""
        with self.lock:
            for f in XML_FILES:
                shutil.copy2(os.path.join(self.map_dir, 'xml', f), os.path.join(self.xml, f))
            if os.path.exists(os.path.join(self.xml, 'map.xml')):
                os.remove(os.path.join(self.xml, 'map.xml'))      # vuelve a usar el map.xml del juego
            src = os.path.join(self.map_dir, 'changelog.json')
            if os.path.exists(src):
                shutil.copy2(src, self.changelog_path())
            elif os.path.exists(self.changelog_path()):
                os.remove(self.changelog_path())
            for d in os.listdir(self.history):
                if d.isdigit() or d == 'rehacer':
                    shutil.rmtree(os.path.join(self.history, d), ignore_errors=True)
            self.reload()
            self.prune_changelog()

    def reload(self):
        with self.lock:
            self.m = mhmap.load_map(self.xml)
            # map.xml: la copia del proyecto (si se ha renombrado alguna región y aún no se instaló) o la del juego
            self.renames = load_renames(self.dir if os.path.exists(os.path.join(self.xml, 'map.xml')) else self.map_dir)
            self.outline_cache = {}
            self.bbox = []
            for row in self.m['shape_table']:
                xs, ys = [], []
                for sh in self.m['shapes'][row.first:row.last + 1]:
                    xs += [v[0] for v in sh.vertices]
                    ys += [v[1] for v in sh.vertices]
                self.bbox.append((min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0))

    def outline(self, r):
        if r not in self.outline_cache:
            main, detail = outlines.region_polygons(self.m, r)
            g = shape({'type': 'MultiPolygon', 'coordinates': main}) if main else None
            ok = g is not None and g.is_valid
            self.outline_cache[r] = (main, detail, ok, '' if ok else (explain_validity(g) if g is not None else 'vacia'))
        return self.outline_cache[r]

    def precompute(self):
        for r in range(len(self.m['regions'])):
            with self.lock:
                self.outline(r)

    def rname(self, r):
        """Nombre de la region tal como lo usan los escenarios (con los RegionRename de map.xml)."""
        n = self.m['regions'][r].name
        return self.renames.get(n, n)

    def meta(self):
        R = self.m['regions']
        return [{'index': g.index, 'name': self.rname(g.index), 'mapName': g.name, 'type': g.u_type, 'sea': g.u_type == SEA,
                 'bbox': self.bbox[g.index], 'center': [g.cx, g.cy]} for g in R]

    def features(self, x0, y0, x1, y1, limit=1500):
        R = self.m['regions']
        out = []
        with self.lock:
            for g in R:
                b = self.bbox[g.index]
                if b[2] < x0 or b[0] > x1 or b[3] < y0 or b[1] > y1:
                    continue
                main, detail, ok, why = self.outline(g.index)
                out.append({'type': 'Feature', 'id': g.index,
                            'properties': {'index': g.index, 'name': self.rname(g.index), 'mapName': g.name, 'type': g.u_type, 'sea': g.u_type == SEA,
                                           'center': [g.cx, g.cy], 'neighbors': [self.rname(n) for n in g.neighbors if n != g.index],
                                           'detail': detail, 'editable': ok, 'invalid': why},
                            'geometry': {'type': 'MultiPolygon', 'coordinates': main}})
                if len(out) >= limit:
                    break
        return out

    # ------------------------------------------------------------------ texturas
    def tile_path(self, name):
        p = os.path.join(self.tiles, name)
        return p if os.path.exists(p) else os.path.join(self.map_dir, 'art', 'OperationalTerrain', name)

    def tile_image(self, c, r, level):
        size = SIZE >> level
        data = open(self.tile_path(tile_name(c, r, level)), 'rb').read()
        return decode(data, size).convert('RGB')

    # ------------------------------------------------------------------ guardar
    def save(self, payload, log=print):
        """payload: {modified: {idx: coords MultiPolygon}, assigns: [{polygon, region, fill}], centers: {idx: [x, y]},
        topo: bool, paint: bool}"""
        import progress
        with self.lock:
            t0 = time.time()
            progress.step(2, 'Calculando los cambios del mapa')
            m = self.m
            R = m['regions']
            cache = {}

            def P(r):
                if r not in cache:
                    cache[r] = unary_union([Polygon(t) for s in mhmap.region_shapes(m, r) for t in s.triangles()
                                            if abs(signed_area(t)) > 0])
                return cache[r]

            def owners(geom, exclude=()):
                """Regiones (no excluidas) cuya malla toca la geometria, por bbox y luego exacto."""
                gx0, gy0, gx1, gy1 = geom.bounds
                res = []
                for i, b in enumerate(self.bbox):
                    if i in exclude or b[2] < gx0 or b[0] > gx1 or b[3] < gy0 or b[1] > gy1:
                        continue
                    if P(i).intersects(geom):
                        res.append(i)
                return res

            report = {'errors': [], 'warnings': [], 'transfers': []}
            created = []   # regiones nuevas: {index, name, mother, owner, u_type}
            new_polys = {}
            for k, coords in (payload.get('modified') or {}).items():
                r = int(k)
                g = shape({'type': 'MultiPolygon', 'coordinates': coords})
                if not g.is_valid:
                    report['errors'].append('%s: poligono invalido (%s)' % (R[r].name, explain_validity(g)))
                    continue
                new_polys[r] = g
            if report['errors']:
                return report

            transfers = []
            taken = {}   # region origen -> area ya traspasada

            def add(piece, src, dst):
                for p in polys_of(piece):
                    transfers.append((p, src, dst))
                    if src is not None:
                        taken[src] = unary_union([taken[src], p]) if src in taken else p

            # 1. areas ganadas: se quitan a quien las tenga; lo que no tiene dueno sale de la nada
            for r, g in new_polys.items():
                gained = g.difference(P(r))
                if gained.area <= MIN_AREA:
                    continue
                rest = gained
                for s in owners(gained, exclude={r}):
                    part = gained.intersection(P(s))
                    if s in new_polys:
                        part = part.difference(new_polys[s])   # solo lo que s realmente suelta
                    if part.area > MIN_AREA:
                        add(part, s, r)
                        rest = rest.difference(P(s))
                if rest.area > MIN_AREA:
                    add(rest, None, r)
            # 2. areas perdidas que nadie gano: hueco
            for r, g in new_polys.items():
                lost = P(r).difference(g)
                if r in taken:
                    lost = lost.difference(taken[r])
                if lost.area > MIN_AREA:
                    if payload.get('topo', True):
                        report['warnings'].append('%s suelta %.6f grados2 que ninguna region gana: queda como hueco' % (R[r].name, lost.area))
                    add(lost, r, None)
            # 3. operaciones de area: asignar / pintar (dan el area a 'region'), recortar (la quita), rellenar (hueco)
            for asg in payload.get('assigns') or []:
                kind = asg.get('kind', 'assign')
                if kind == 'new_region':
                    self._plan_new_region(asg, created, add, owners, P, report)
                    continue
                if kind == 'delete_region':
                    d = int(asg['region'])
                    into = asg.get('into')
                    into = int(into) if into is not None else None
                    if into is not None and (R[into].u_type == SEA) != (R[d].u_type == SEA) and R[d].u_type == SEA:
                        report['errors'].append('%s es mar: solo puede pasar a otra región de mar o quedar vacía' % R[d].name)
                        continue
                    add(P(d), d, into)
                    report.setdefault('deleted', []).append({'index': d, 'name': self.rname(d), 'raw': R[d].name,
                                                             'into': self.rname(into) if into is not None else None,
                                                             'sea': R[d].u_type == SEA})
                    continue
                r = asg.get('region')
                r = int(r) if r is not None else None
                if kind == 'fill_point':
                    x, y = asg['point']
                    win = Polygon([(x - 3, y - 3), (x + 3, y - 3), (x + 3, y + 3), (x - 3, y + 3)])
                    empty = win.difference(unary_union([P(s) for s in owners(win)] or [Polygon()]))
                    from shapely.geometry import Point
                    hole = [p for p in polys_of(empty) if p.buffer(1e-9).contains(Point(x, y))]
                    if not hole:
                        report['warnings'].append('no hay ningun hueco en %.3f, %.3f' % (x, y))
                        continue
                    if hole[0].exterior.intersects(win.exterior):
                        report['warnings'].append('el hueco en %.3f, %.3f es demasiado grande o no esta cerrado' % (x, y))
                        continue
                    add(hole[0], None, r)
                    continue
                geom = shape(asg['polygon'])
                if kind == 'stroke':
                    geom = geom.buffer(float(asg.get('radius', 0.1)), quad_segs=4)
                poly = make_valid(geom)
                if kind == 'cut':
                    # lo recortado de 'from' pasa a 'into' (una vecina, de tierra o mar) o queda como hueco
                    src = int(asg['from'])
                    into = asg.get('into')
                    into = int(into) if into is not None else None
                    if into == src:
                        into = None
                    add(poly.intersection(P(src)), src, into)
                    continue
                for s in owners(poly, exclude={r}):
                    if asg.get('land_only') and R[s].u_type == SEA:
                        continue
                    add(poly.intersection(P(s)), s, r)
                if asg.get('fill'):
                    rest = poly.difference(unary_union([P(s) for s in owners(poly)] or [Polygon()]))
                    add(rest, None, r)

            centers = {int(k): v for k, v in (payload.get('centers') or {}).items()}
            if report['errors']:
                self.reload()
                return report
            if not transfers and not centers:
                report['warnings'].append('no hay cambios que guardar')
                return report
            progress.step(25, 'Copia para «Volver»')
            self.snapshot(log, keep_redo=True)
            self._pending_snapshot = True
            for p, s, d in transfers:
                report['transfers'].append({'from': R[s].name if s is not None else '(hueco)',
                                            'to': R[d].name if d is not None else '(hueco)', 'area': p.area})
            new_pairs = []
            changes = {'erase': [], 'paint': [], 'islands': []}
            touched = sorted({x for _, s, d in transfers for x in (s, d) if x is not None})
            old_k = {r: new_region.cos_area(m, r) for r in touched}
            was_valid = {r: self._mesh_valid(m, r) for r in touched}
            progress.step(35, 'Traspasando áreas entre regiones')
            if transfers:
                erase, paint, new_pairs = apply_transfers(m, transfers, [], P, cache)
                changes = {'erase': [dict(mapping(x), kind=k) for k, x in erase],
                           'paint': [dict(mapping(x), kind=k) for k, x in paint], 'islands': []}
            # areas (u_a/u_b), centro y puntos de las regiones cuya malla cambio
            created_idx = {c['index'] for c in created}
            ratio = {c['index']: (R[c['mother_index']].u_a / R[c['mother_index']].u_b
                                  if c['mother_index'] is not None and R[c['mother_index']].u_b else 1.0) for c in created}
            scale = {c['index']: R[c['mother_index']].u_b / old_k[c['mother_index']]
                     for c in created if c['mother_index'] is not None and old_k.get(c['mother_index'])}
            progress.step(50, 'Recalculando áreas, centros y vecinos')
            new_region.refresh_derived(m, touched, old_k, created_idx, ratio, scale)
            for c in created:
                k_new = new_region.cos_area(m, c['index'])
                if k_new <= 0:
                    raise SystemExit('la region nueva %s quedo sin area' % c['name'])
                c['area'] = round(k_new, 6)
                if c['mother_index'] is not None:
                    k_m = new_region.cos_area(m, c['mother_index'])
                    c['fraccion'] = round(k_new / (k_new + k_m), 6) if k_new + k_m > 0 else 0
                c['neighbors'] = [R[n].name for n in R[c['index']].neighbors if n != c['index']]
            for r, (x, y) in centers.items():
                R[r].cx, R[r].cy = f32(x), f32(y)
            progress.step(55, 'Comprobando la malla')
            self._guard(m, created, was_valid, report)      # aborta (sin escribir) si el resultado no es el esperado
            progress.step(60, 'Escribiendo regions.bin, regions.nts y borders.brd')
            mhmap.save_map(m, self.xml)
            self._pending_snapshot = False
            if os.path.isdir(self._redo_dir()):
                shutil.rmtree(self._redo_dir())        # un guardado nuevo invalida lo que se podia rehacer
            if payload.get('paint', True) and (changes['erase'] or changes['paint']):
                progress.step(65, 'Pintando el terreno')
                tiles = paint_tiles(changes, os.path.join(self.map_dir, 'art', 'OperationalTerrain'), self.tiles,
                                    originals=self.tiles, log=log)
                report['tiles'] = ['%02d-%02d' % t for t in tiles]
            json.dump(changes, open(os.path.join(self.dir, 'ultimo_cambio.json'), 'w'))
            report['new_regions'] = [{k: v for k, v in c.items() if k != 'mother_index'} for c in created]
            progress.step(70, 'Comprobando el mapa')
            self.log_change(report, new_pairs, centers, R, payload)
            self.reload()
            report['new_pairs'] = [[R[a].name, R[b].name] for a, b in new_pairs]
            if report.get('deleted'):
                self._finish_deletions(report['deleted'], log)
            report['check'] = self.check()
            report['seconds'] = round(time.time() - t0, 1)
            return report

    def cut_preview(self, polygon, sea=False):
        """Regiones de las que saldría la región nueva: [{name, taken, total, pct}] (de mayor a menor)."""
        from shapely.strtree import STRtree
        with self.lock:
            poly = make_valid(shape(polygon))
            R = self.m['regions']
            out = []
            for g in R:
                if (g.u_type == SEA) != bool(sea):
                    continue
                b = self.bbox[g.index] if g.index < len(self.bbox) else None
                x0, y0, x1, y1 = poly.bounds
                if b and (b[2] < x0 or b[0] > x1 or b[3] < y0 or b[1] > y1):
                    continue
                geo = self.region_geom(self.rname(g.index))
                if geo is None:
                    continue
                part = poly.intersection(geo).area
                if part > MIN_AREA:
                    out.append((part, g.index, geo.area))
            pieces = drop_slivers([(type('A', (), {'area': a})(), (i, t)) for a, i, t in out])
            res = [{'name': self.rname(i), 'taken': round(p.area, 6), 'total': round(t, 6), 'pct': round(p.area / t, 4) if t else 0}
                   for p, (i, t) in pieces]
            return sorted(res, key=lambda x: -x['taken'])

    def _plan_new_region(self, asg, created, add, owners, P, report):
        """Crea (vacia) la region nueva y planifica los traspasos que le dan su area.
        asg: {polygon, name, from (region madre: subdividir) o None (dibujada sobre el mar), owner, u_type, fill}"""
        R = self.m['regions']
        text = ' '.join((asg.get('name') or '').split())
        name = new_region.internal_name(text)   # nombre interno en ASCII (como todas las del mapa); el texto va al SID
        taken_names = {g.name for g in R} | set(self.renames.values()) | {c['name'] for c in created}
        if not name:
            report['errors'].append('la región nueva necesita un nombre')
            return
        if name in taken_names:
            report['errors'].append('ya existe una región llamada %s en este regionpack. Búscala en el mapa: si le faltan datos '
                                    'en el escenario usa «Registrar en el escenario» en su panel; si está mal hecha, '
                                    'bórrala con «Eliminar región» (modo Editar forma) y dibújala de nuevo' % name)
            return
        poly = make_valid(shape(asg['polygon']))
        mother = asg.get('from')
        mother = int(mother) if mother is not None else None
        pieces = []
        mothers_area = {}
        if asg.get('sea'):
            # region MARITIMA nueva: se recorta de las regiones de mar que toca (la madre es la de mas area)
            water = [(poly.intersection(P(s)), s) for s in owners(poly) if R[s].u_type == SEA]
            water = drop_slivers([(p, s) for p, s in water if p.area > MIN_AREA])
            if asg.get('fill'):      # huecos (p. ej. un río cortado antes de la tierra) pasan a ser mar de la región nueva
                rest = poly.difference(unary_union([P(s) for s in owners(poly)] or [Polygon()]))
                water += [(p, None) for p in polys_of(rest)]
            if not water:
                report['errors'].append('%s: para una región marítima dibuja sobre el mar' % name)
                return
            for p, s in water:
                if s is not None and p.area >= P(s).area * 0.999:
                    report['errors'].append('%s: el polígono cubre toda %s' % (name, R[s].name))
                    return
            pieces = water
            mothers_area = {self.rname(s): round(p.area, 6) for p, s in water if s is not None}
            mother = max([w for w in water if w[1] is not None] or [(None, None)], key=lambda x: x[0].area if x[0] is not None else 0)[1]
            u_type = SEA
        elif asg.get('cut_all'):
            # Dibujar/Cortar (como Pax Historia): se recorta de todas las regiones de tierra que toca;
            # la madre es la que aporta más área (de ella hereda dueño, terreno y cultura en los escenarios)
            land = [(poly.intersection(P(s)), s) for s in owners(poly) if R[s].u_type != SEA]
            land = drop_slivers([(p, s) for p, s in land if p.area > MIN_AREA])
            if land:
                for p, s in land:
                    if p.area >= P(s).area * 0.999:
                        report['errors'].append('%s: el polígono cubre toda %s (bórrala o renómbrala en vez de recortarla)' % (name, R[s].name))
                        return
                pieces = land
                mothers_area = {self.rname(s): round(p.area, 6) for p, s in land}
                mother = max(land, key=lambda x: x[0].area)[1]
                u_type = int(asg.get('u_type') or R[mother].u_type)
                if asg.get('fill'):
                    rest = poly.difference(unary_union([P(s) for s in owners(poly)] or [Polygon()]))
                    if rest.area > MIN_AREA:
                        pieces.append((rest, None))
        if pieces:
            pass
        elif mother is not None:
            if R[mother].u_type == SEA:
                report['errors'].append('%s es mar: para crear una región en el mar dibuja sobre él con «Dibujar»' % R[mother].name)
                return
            part = poly.intersection(P(mother))
            if part.area <= MIN_AREA:
                report['errors'].append('%s: el polígono no toca %s' % (name, R[mother].name))
                return
            if part.area >= P(mother).area * 0.999:
                report['errors'].append('%s: el polígono cubre toda %s (para cambiarle el nombre usa RegionRename de map.xml)' % (name, R[mother].name))
                return
            pieces.append((part, mother))
            u_type = int(asg.get('u_type') or R[mother].u_type)
        else:
            for s in owners(poly):
                if R[s].u_type == SEA:
                    pieces.append((poly.intersection(P(s)), s))
            u_type = int(asg.get('u_type') or 1)
            if asg.get('fill'):
                rest = poly.difference(unary_union([P(s) for s in owners(poly)] or [Polygon()]))
                if rest.area > MIN_AREA:
                    pieces.append((rest, None))
            if not any(p.area > MIN_AREA for p, _ in pieces):
                report['errors'].append('%s: el polígono no cubre mar' % name)
                return
        if u_type == SEA and not asg.get('sea'):
            u_type = 1
        if not asg.get('sea') and not 1 <= u_type <= 4:
            report['errors'].append('%s: tipo de terreno %s no válido (1..4)' % (name, u_type))
            return
        expected = sum(p.area for p, _ in pieces)
        idx = new_region.create_region(self.m, name, u_type)
        created.append({'index': idx, 'name': name, 'text': text, 'mother': R[mother].name if mother is not None else None,
                        'mother_index': mother, 'owner': asg.get('owner'), 'controller': asg.get('controller'), 'u_type': u_type,
                        'terrain': asg.get('terrain'), 'sea': bool(asg.get('sea')),
                        'pop_fractions': asg.get('pop_fractions'), 'expected_area': round(expected, 6),
                        'historic': asg.get('historic'), 'population': asg.get('population'), 'city': asg.get('city'),
                        'mothers': mothers_area})
        for p, s in pieces:
            add(p, s, idx)

    def region_geom(self, name):
        """Poligono de la malla de una region por su nombre en los escenarios."""
        inv = {v: k for k, v in self.renames.items()}
        nm = inv.get(name, name)
        for g in self.m['regions']:
            if g.name == nm:
                return new_region.mesh_polygon(self.m, g.index)
        return None

    def check(self):
        """Reglas del formato sobre todo el mapa del proyecto."""
        m = self.m
        zero = sum(1 for b in m['borders'] for f, p in b.segments for i in range(1, len(p)) if p[i - 1] == p[i])
        return {'pasos_cero': zero, 'bordes': len(m['borders'])}

    # ------------------------------------------------------------------ escenarios (propietarios y colores)
    def scenarios(self):
        d = SCEN_DIR
        return sorted(x for x in os.listdir(d) if os.path.exists(os.path.join(d, x, 'gamestate.xml')))

    def scenario_info(self, name):
        import re
        d = os.path.join(SCEN_DIR, name)
        prop = lambda block, k: (re.search(r'name="%s" value="([^"]*)"' % k, block) or [None, None])[1]
        regions = {}
        for f in os.listdir(d):
            if f.startswith('country') and f.endswith('.xml'):
                txt = open(os.path.join(d, f), encoding='utf-8', errors='replace').read()
                for blk in re.split(r'<object type="Region"', txt)[1:]:
                    head = blk.split('<object type=')[0]
                    nm = prop(head, 'strName')
                    if nm:
                        pop = prop(head, 'nPopulation')
                        regions[nm] = {'owner': prop(head, 'strOwner'), 'controller': prop(head, 'strController'),
                                       'terrain': prop(head, 'strTerrain'), 'population': int(pop) if pop and pop.isdigit() else None}
        colors = {}
        gs = open(os.path.join(d, 'gamestate.xml'), encoding='utf-8', errors='replace').read()
        for blk in re.split(r'<object type="Player"', gs)[1:]:
            head = blk.split('</object>')[0]
            nm, col = prop(head, 'strName'), prop(head, 'colCountryColor')
            if nm and col:
                colors[nm] = '#' + col.lstrip('#')[:6]
        return {'regions': regions, 'colors': colors}

    # ------------------------------------------------------------------ historial
    def _mesh_valid(self, m, r):
        """El contorno de la region r es un poligono valido (sin aristas que crucen el mapa)."""
        try:
            main, _ = outlines.region_polygons(m, r)
            return bool(main) and shape({'type': 'MultiPolygon', 'coordinates': main}).is_valid
        except Exception:
            return False

    def _guard(self, m, created, was_valid, report):
        """Antes de escribir el mapa: ninguna region que era valida queda rota, y cada region nueva tiene
        (casi) el area que se dibujo. Si no, se descarta todo y se explica por qué."""
        R = m['regions']
        problems = []
        gone = {d['index'] for d in report.get('deleted', [])}     # las que se eliminan quedan vacías a propósito
        for r, ok in was_valid.items():
            if ok and r < len(R) and r not in gone and not self._mesh_valid(m, r):
                problems.append('la malla de %s quedaría rota (contorno inválido)' % self.rname(r))
        for c in created:
            exp = c.get('expected_area') or 0
            got = new_region.mesh_polygon(m, c['index'])
            got = got.area if got is not None else 0
            if exp and got < 0.7 * exp:
                problems.append('%s saldría con %.3f grados² en vez de los %.3f dibujados' % (c['name'], got, exp))
            if not self._mesh_valid(m, c['index']):
                problems.append('la región nueva %s tendría un contorno inválido' % c['name'])
        if problems:
            raise SystemExit('No se guardó nada: ' + '; '.join(problems) +
                             '. Prueba a dibujar el polígono un poco más separado de las fronteras vecinas o con menos nodos.')

    def _drop_pending_snapshot(self):
        if getattr(self, '_pending_snapshot', False):
            snaps = sorted(d for d in os.listdir(self.history) if d.isdigit())
            if snaps:
                shutil.rmtree(os.path.join(self.history, snaps[-1]), ignore_errors=True)
        self._pending_snapshot = False

    def _copy_state(self, d):
        """Copia el estado actual del proyecto (binarios, tiles, changelog) a la carpeta d."""
        os.makedirs(os.path.join(d, 'xml'))
        os.makedirs(os.path.join(d, 'tiles'))
        for f in XML_FILES:
            shutil.copy2(os.path.join(self.xml, f), os.path.join(d, 'xml', f))
        for f in os.listdir(self.tiles):
            shutil.copy2(os.path.join(self.tiles, f), os.path.join(d, 'tiles', f))
        if os.path.exists(self.changelog_path()):
            shutil.copy2(self.changelog_path(), os.path.join(d, 'changelog.json'))

    def _load_state(self, d):
        for f in XML_FILES:
            shutil.copy2(os.path.join(d, 'xml', f), os.path.join(self.xml, f))
        shutil.rmtree(self.tiles)
        shutil.copytree(os.path.join(d, 'tiles'), self.tiles)
        if os.path.exists(os.path.join(d, 'changelog.json')):
            shutil.copy2(os.path.join(d, 'changelog.json'), self.changelog_path())
        elif os.path.exists(self.changelog_path()):
            os.remove(self.changelog_path())

    def _redo_dir(self):
        return os.path.join(self.history, 'rehacer')

    def snapshot(self, log=print, keep_redo=False):
        n = len([d for d in os.listdir(self.history) if d.isdigit()]) + 1
        d = os.path.join(self.history, '%03d' % n)
        self._copy_state(d)
        if not keep_redo and os.path.isdir(self._redo_dir()):
            shutil.rmtree(self._redo_dir())        # un guardado nuevo invalida lo que se podia rehacer
        log('instantanea %s' % d)

    def can_redo(self):
        d = self._redo_dir()
        return os.path.isdir(d) and any(x.isdigit() for x in os.listdir(d))

    def redo(self, log=print):
        """Rehace el último guardado deshecho con «Volver»."""
        with self.lock:
            d = self._redo_dir()
            snaps = sorted(x for x in os.listdir(d) if x.isdigit()) if os.path.isdir(d) else []
            if not snaps:
                return {'ok': False, 'msg': 'no hay nada que rehacer'}
            src = os.path.join(d, snaps[-1])
            before = {g.name for g in self.m['regions']}
            self.snapshot(log, keep_redo=True)
            self._load_state(src)
            shutil.rmtree(src)
            self.reload()
            added = [g.name for g in self.m['regions'] if g.name not in before]
            news = [x for e in self.changelog() for x in e.get('regiones_nuevas', []) if x.get('nombre') in added]
            return {'ok': True, 'msg': 'rehecho el guardado %s' % snaps[-1], 'added_regions': news}

    def undo(self):
        with self.lock:
            snaps = sorted(d for d in os.listdir(self.history) if d.isdigit())
            if not snaps:
                return {'ok': False, 'msg': 'no hay nada que deshacer'}
            d = os.path.join(self.history, snaps[-1])
            before = {g.name: g.index for g in self.m['regions']}
            # el estado actual se guarda para poder «Rehacer»
            rd = self._redo_dir()
            os.makedirs(rd, exist_ok=True)
            self._copy_state(os.path.join(rd, '%03d' % (len([x for x in os.listdir(rd) if x.isdigit()]) + 1)))
            # el changelog vuelve al estado de la instantanea (se quitan las entradas de ese guardado)
            log_before = self.changelog()
            self._load_state(d)
            shutil.rmtree(d)
            self.reload()
            after = {g.name for g in self.m['regions']}
            gone = [n for n in before if n not in after]
            info = {x['nombre']: x for e in log_before for x in e.get('regiones_nuevas', [])}
            deleted = {x['nombre']: x for e in log_before for x in e.get('regiones_eliminadas', [])}
            back = [g.name for g in self.m['regions'] if g.name not in before]
            return {'ok': True, 'msg': 'restaurada la instantanea %s' % snaps[-1],
                    'removed_regions': [{'nombre': n, 'madre': info.get(n, {}).get('madre'), 'poblacion': info.get(n, {}).get('poblacion'),
                                         'madres': list((info.get(n, {}).get('madres') or {}).keys())} for n in gone],
                    'restored_regions': [{'nombre': self.rname(next(g.index for g in self.m['regions'] if g.name == n)),
                                          'madre': (deleted.get(n) or {}).get('absorbida_por'), 'mar': (deleted.get(n) or {}).get('mar'),
                                          'poblacion_por_escenario': (deleted.get(n) or {}).get('poblacion_por_escenario')}
                                         for n in back]}

    # ------------------------------------------------------------------ changelog del regionpack
    def changelog_path(self):
        return os.path.join(self.dir, 'changelog.json')

    def note_deleted_population(self, pops):
        """Anota en el último guardado la población que tenía cada región borrada en cada escenario (para deshacer exacto)."""
        if not pops:
            return
        cl = self.changelog()
        if cl:
            for x in cl[-1].get('regiones_eliminadas', []):
                if x['nombre'] in pops:
                    x['poblacion_por_escenario'] = pops[x['nombre']]
            json.dump(cl, open(self.changelog_path(), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    def _finish_deletions(self, deleted, log=print):
        """Quita del mapa las regiones ya vaciadas y actualiza el changelog: la creación de una región borrada
        desaparece y el último guardado anota qué se borró y adónde fue su área."""
        m = self.m
        for d in sorted(deleted, key=lambda x: -x['index']):
            idx = next((g.index for g in m['regions'] if g.name == d['raw']), None)
            if idx is None:
                continue
            for sh in mhmap.region_shapes(m, idx):      # restos diminutos que no se pudieron traspasar
                sh.vertices, sh.indices = [], []
            new_region.delete_region(m, idx)
            log('region borrada: %s (area a %s)' % (d['name'], d['into'] or 'hueco'))
        mhmap.save_map(m, self.xml)
        cl = self.changelog()
        names = {d['name'] for d in deleted}
        for e in cl:
            e['regiones_nuevas'] = [x for x in e.get('regiones_nuevas', []) if x.get('nombre') not in names]
        if cl:
            cl[-1]['regiones_eliminadas'] = [{'nombre': d['name'], 'absorbida_por': d['into'], 'mar': d['sea']} for d in deleted]
            cl[-1]['operaciones'] = sorted(set(cl[-1].get('operaciones', [])) | {'delete_region'})
        json.dump(cl, open(self.changelog_path(), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        self.reload()

    def changelog(self):
        p = self.changelog_path()
        return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else []

    def log_change(self, report, new_pairs, centers, R, payload):
        """Una entrada por guardado, por nombre de region: sirve para aplicar el cambio a otros escenarios."""
        agg = {}
        for t in report['transfers']:
            k = (t['from'], t['to'])
            agg[k] = agg.get(k, 0) + t['area']
        entry = {'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': self.pack, 'instalado': False,
                 'traspasos': [{'de': a, 'a': b, 'area': round(v, 8)} for (a, b), v in agg.items()],
                 'vecindades_nuevas': [[R[a].name, R[b].name] for a, b in new_pairs],
                 'centros': {R[r].name: list(xy) for r, xy in centers.items()},
                 'operaciones': sorted({op.get('kind', 'assign') for op in payload.get('assigns') or []} |
                                       ({'nodos'} if payload.get('modified') else set())),
                 'regiones_nuevas': [{'nombre': c['name'], 'texto': c.get('text') or c['name'], 'madre': c['mother'], 'pais': c.get('owner'), 'tipo': c['u_type'],
                                      'controlador': c.get('controller'), 'madres': c.get('mothers'),
                                      'terreno': c.get('terrain'), 'mar': c.get('sea'),
                                      'poblacion': c.get('pop_fractions'), 'historicos': c.get('historic'),
                                      'poblacion_manual': c.get('population'), 'ciudad': c.get('city'),
                                      'fraccion': c.get('fraccion'), 'area': c.get('area')} for c in report.get('new_regions', [])]}
        log = self.changelog()
        log.append(entry)
        json.dump(log, open(self.changelog_path(), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # ------------------------------------------------------------------ regionpacks
    @staticmethod
    def packs():
        return sorted(d for d in os.listdir(MAPS) if os.path.exists(os.path.join(MAPS, d, 'xml', 'regions.bin')))

    @staticmethod
    def pack_users():
        """{regionpack: [escenarios que lo usan]} segun strMapName de cada scenario.xml."""
        import re
        out = {}
        for s in sorted(os.listdir(SCEN_DIR)):
            f = os.path.join(SCEN_DIR, s, 'scenario.xml')
            if os.path.exists(f):
                m = re.search(r'name="strMapName" value="([^"]*)"', open(f, encoding='utf-8', errors='replace').read())
                if m:
                    out.setdefault(m.group(1), []).append(s)
        return out

    def save_meta(self):
        json.dump({'pack': self.pack, 'decided': self.decided}, open(os.path.join(self.dir, 'pack.json'), 'w'))

    @staticmethod
    def set_scenario_pack(scenario, pack, backup_root):
        """Cambia strMapName y fileMapProperties de un escenario (con copia del scenario.xml original)."""
        import re
        f = os.path.join(SCEN_DIR, scenario, 'scenario.xml')
        in_game = os.path.normcase(os.path.abspath(f)).startswith(os.path.normcase(os.path.abspath(GAME)) + os.sep)
        rel = os.path.relpath(f, GAME if in_game else os.path.dirname(os.path.abspath(SCEN_DIR)))   # nunca sale del respaldo
        if os.environ.get('MH_RESPALDOS') == '1':
            bak = os.path.join(backup_root, 'archivos_originales', rel)
            if not os.path.exists(bak):
                os.makedirs(os.path.dirname(bak), exist_ok=True)
                shutil.copy2(f, bak)
            hist = os.path.join(backup_root, 'historial', time.strftime('%Y%m%d-%H%M%S'), rel)
            os.makedirs(os.path.dirname(hist), exist_ok=True)
            shutil.copy2(f, hist)
        t = open(f, encoding='utf-8', newline='').read()
        t = re.sub(r'(name="strMapName" value=")[^"]*(")', lambda m: m.group(1) + pack + m.group(2), t)
        t = re.sub(r'(name="fileMapProperties" value="[^"]*/Maps/)[^/"]*(/)', lambda m: m.group(1) + pack + m.group(2), t)
        open(f, 'w', encoding='utf-8', newline='').write(t)

    @staticmethod
    def copy_pack(src_pack, new_name, scenarios=(), backup_root=None, project_src=None, project_dst=None):
        """Copia de seguridad de un regionpack del juego con otro nombre (geometría, texturas, map.xml, changelog).
        Los 'scenarios' indicados pasan a usar la copia (se reescribe su scenario.xml, con respaldo). Si se pasan
        project_src/project_dst, también se copia el proyecto del editor para seguir editando la copia."""
        import re
        if not new_name or not re.match(r'^[A-Za-z0-9_-]+$', new_name):
            raise ValueError('nombre de regionpack no válido (solo letras, números, - y _)')
        src, dst = os.path.join(MAPS, src_pack), os.path.join(MAPS, new_name)
        if not os.path.isdir(src):
            raise ValueError('no existe el regionpack %s' % src_pack)
        if os.path.exists(dst):
            raise ValueError('ya existe un regionpack llamado %s' % new_name)
        shutil.copytree(src, dst)
        notes = ['regionpack %s copiado como %s' % (src_pack, new_name)]
        switched = []
        for sc_name in scenarios:
            Project.set_scenario_pack(sc_name, new_name, backup_root)
            switched.append(sc_name)
        if switched:
            notes.append('usan %s: %s' % (new_name, ', '.join(switched)))
        if project_src and project_dst and os.path.isdir(project_src):
            if os.path.exists(project_dst):
                shutil.move(project_dst, project_dst + '_anterior_' + time.strftime('%Y%m%d-%H%M%S'))
            shutil.copytree(project_src, project_dst, ignore=shutil.ignore_patterns('history'))
            json.dump({'pack': new_name, 'decided': True}, open(os.path.join(project_dst, 'pack.json'), 'w'))
            notes.append('proyecto del editor copiado (con los cambios sin instalar)')
        return {'ok': True, 'pack': new_name, 'escenarios': switched, 'notes': notes}

    # ------------------------------------------------------------------ instalar
    def install(self, target='same', new_name=None, scenarios=(), backup_root=None):
        """target 'same': al regionpack del proyecto. 'new': copia el regionpack con otro nombre y lo instala ahi;
        los 'scenarios' indicados pasan a usar el regionpack nuevo."""
        import re
        with self.lock:
            dest = self.map_dir
            if target == 'new':
                if not new_name or not re.match(r'^[A-Za-z0-9_-]+$', new_name):
                    return {'ok': False, 'msg': 'nombre de regionpack no válido (solo letras, números, - y _)'}
                dest = os.path.join(MAPS, new_name)
                if os.path.exists(dest):
                    return {'ok': False, 'msg': 'ya existe un regionpack llamado %s' % new_name}
                shutil.copytree(self.map_dir, dest)
            done = []
            pairs = [(os.path.join(self.xml, f), os.path.join(dest, 'xml', f), os.path.join(self.backup_dir, f)) for f in XML_FILES]
            if os.path.exists(os.path.join(self.xml, 'map.xml')):     # nombres de regiones cambiados (RegionRename)
                pairs.append((os.path.join(self.xml, 'map.xml'), os.path.join(dest, 'xml', 'map.xml'), os.path.join(self.backup_dir, 'map.xml')))
            pairs += [(os.path.join(self.tiles, f), os.path.join(dest, 'art', 'OperationalTerrain', f),
                       os.path.join(self.backup_dir, 'OperationalTerrain', f)) for f in os.listdir(self.tiles)]
            for src, dst, bak in pairs:
                if target == 'same' and os.environ.get('MH_RESPALDOS') == '1':
                    os.makedirs(os.path.dirname(bak), exist_ok=True)
                    if not os.path.exists(bak):
                        shutil.copy2(dst, bak)   # respaldo del original del juego, solo la primera vez
                shutil.copy2(src, dst)
                done.append(os.path.basename(dst))
            # el changelog viaja dentro del regionpack
            self.prune_changelog()
            log = self.changelog()
            for e in log:
                e['instalado'] = True
            json.dump(log, open(self.changelog_path(), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            json.dump(log, open(os.path.join(dest, 'changelog.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            switched = []
            if target == 'new':
                for s in scenarios:
                    self.set_scenario_pack(s, new_name, backup_root)
                    switched.append(s)
                # el regionpack nuevo tiene su PROPIO proyecto (<base>_<nuevo>) con este trabajo; este proyecto
                # vuelve a ser el del regionpack original tal como está en el juego (antes se «rebautizaba» y
                # quedaban dos proyectos para el mismo regionpack)
                base = self.dir if self.pack == 'World' else self.dir[:-len('_' + self.pack)]
                sibling = base + '_' + new_name
                if os.path.exists(sibling):
                    shutil.move(sibling, sibling + '_anterior_' + time.strftime('%Y%m%d-%H%M%S'))
                shutil.copytree(self.dir, sibling)
                json.dump({'pack': new_name, 'decided': True}, open(os.path.join(sibling, 'pack.json'), 'w'))
                root_backup = self.backup_dir if self.pack == 'World' else os.path.dirname(self.backup_dir)
                orig = self.pack
                for sub in ('xml', 'tiles', 'history'):
                    shutil.rmtree(os.path.join(self.dir, sub), ignore_errors=True)
                if os.path.exists(self.changelog_path()):
                    os.remove(self.changelog_path())
                json.dump({'pack': orig, 'decided': False}, open(os.path.join(self.dir, 'pack.json'), 'w'))
                self.__init__(self.dir, root_backup, orig)
                return {'ok': True, 'files': done, 'regionpack': os.path.basename(dest), 'escenarios': switched, 'nuevo_proyecto': sibling}
            self.decided = True
            self.save_meta()
            return {'ok': True, 'files': done, 'regionpack': os.path.basename(dest), 'escenarios': switched}
