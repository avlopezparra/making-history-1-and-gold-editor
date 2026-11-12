"""Region editor core: working project, outlines, saving as transfers, history and installation.

The project is a folder with:
  xml/        regions.bin, borders.brd, regions.nts (working state)
  tiles/      OperationalTerrain textures the project has modified
  history/    snapshots before each save (for undo)
It is created by copying the current game state. Nothing touches the game until "install".
"""
import json
import os
import re
import shutil
import struct
import threading
import time

from shapely import make_valid
from shapely.errors import GEOSException
from shapely.geometry import shape, Polygon, MultiPolygon, mapping
from shapely.ops import unary_union
from shapely.validation import explain_validity

import mhmap
import outlines
from move_border import signed_area
import changelog_keys
from transfer import apply_transfers, SEA
import new_region
from paint_changes import paint_tiles
from fix_texture import decode, tile_name, SIZE

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Making History The Calm and The Storm"
MAPS = os.path.join(GAME, r"Modern Europe\system\DisplayLibraries\Maps")
MAP_DIR = os.path.join(MAPS, "World")   # compatibility; each project uses self.map_dir
SCEN_DIR = os.path.join(GAME, r"Modern Europe\system\scenarios")
XML_FILES = ('regions.bin', 'borders.brd', 'regions.nts')
SAVE_HISTORY = True     # «Historial»: copy of each save in history/ for «Volver»; set by the server (opciones.json)
MIN_AREA = 1e-10
SLIVER = 1e-3        # degrees2: a piece this small, next to much larger ones, is a border graze, not a cut


class _DryOK(Exception):
    """_save_once with '_dry': the mesh would come out sound (nothing is written)."""


def _where(x, y):
    return '(lon %.2f, lat %.2f)' % (x, y)


def drop_slivers(pieces):
    """Removes the tiny pieces left by grazing the border of a neighbouring region (they break the mesh when transferred)."""
    big = max((p.area for p, _ in pieces), default=0)
    return [(p, s) for p, s in pieces if p.area >= SLIVER or p.area >= 0.02 * big]


def load_renames(map_dir):
    """{name in regions.bin: name in the scenarios} according to the RegionRename entries of map.xml (applied together)."""
    import xml_tolerant      # a hand-edited map.xml that the game accepts must not prevent opening or saving the regionpack
    out = {}
    f = os.path.join(map_dir, 'xml', 'map.xml')
    if os.path.exists(f):
        for o in xml_tolerant.parse(f).getroot().iter('object'):
            if o.get('type') == 'RegionRename':
                pr = {p.get('name'): p.get('value') for p in o.findall('property')}
                if pr.get('strOldRegionName') and pr.get('strNewRegionName'):
                    out[pr['strOldRegionName']] = pr['strNewRegionName']
    return out


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def polys_of(g):
    if g.geom_type == 'Polygon':
        return [g] if g.area > MIN_AREA else []
    return [polygon for part in getattr(g, 'geoms', []) for polygon in polys_of(part)]


def geometry_audit(before, after, visual=False, gap_width=0.001):
    """Compare actual polygon coverage, overlap and shared boundaries in degrees."""
    ids = sorted(before)
    from shapely.strtree import STRtree
    # only the polygonal part: a union/difference can leave polygon + loose line (GeometryCollection), whose .boundary is None
    polygonal = lambda g: g if g.geom_type in ('Polygon', 'MultiPolygon') else unary_union(polys_of(g))
    before = {k: polygonal(v) for k, v in before.items()}
    after = {k: polygonal(v) for k, v in after.items()}
    footprints = [before[ident].union(after[ident]) for ident in ids]
    tree = STRtree(footprints)
    rows, borders = [], []
    overlap_before = overlap_after = 0.0
    def boundary(geom):
        return Polygon().boundary if geom.is_empty else geom.boundary
    def border_parts(geometry):
        from shapely.ops import linemerge
        if geometry.is_empty or geometry.length == 0:
            return 0
        if geometry.geom_type == 'LineString':
            return 1
        lines = [part for part in geometry.geoms if part.geom_type == 'LineString' and part.length > 0]
        if not lines:
            return 0
        merged = linemerge(lines)
        return 1 if merged.geom_type == 'LineString' else len(merged.geoms)
    for pos, ident in enumerate(ids):
        old, new = before[ident], after[ident]
        rows.append({'index': ident, 'gained': new.difference(old).area, 'lost': old.difference(new).area,
                     'empty': new.is_empty or new.area <= MIN_AREA,
                     'parts_before': len(polys_of(old)), 'parts_after': len(polys_of(new))})
        if visual:
            new_parts = polys_of(new)
            part_tree = STRtree(new_parts)
            preserved = split = removed = 0
            for part in polys_of(old):
                matches = [new_parts[int(i)] for i in part_tree.query(part)
                           if part.intersection(new_parts[int(i)]).area > MIN_AREA]
                preserved += any(part.equals(candidate) for candidate in matches)
                split += len(matches) > 1
                removed += not matches
            rows[-1].update(preserved_parts=preserved, split_parts=split, removed_parts=removed)
        for other_pos in sorted(int(value) for value in tree.query(footprints[pos]) if int(value) > pos):
            other = ids[other_pos]
            old_pair, new_pair = before[other], after[other]
            overlap_before += old.intersection(old_pair).area
            overlap_after += new.intersection(new_pair).area
            old_border = boundary(old).intersection(boundary(old_pair))
            new_border = boundary(new).intersection(boundary(new_pair))
            old_length, new_length = old_border.length, new_border.length
            if old_length or new_length:
                borders.append({'regions': [ident, other], 'before': old_length, 'after': new_length,
                                'parts_before': border_parts(old_border), 'parts_after': border_parts(new_border)})
    old_union, new_union = unary_union(list(before.values())), unary_union(list(after.values()))
    result = {'regions': rows, 'borders': borders, 'overlap_before': overlap_before, 'overlap_after': overlap_after,
              'coverage_gained': new_union.difference(old_union).area, 'coverage_lost': old_union.difference(new_union).area}
    if visual:
        import shapely
        features = {key: [] for key in ('before', 'after', 'gained', 'lost', 'defects')}
        for row in rows:
            ident = row['index']
            if row['gained'] <= MIN_AREA and row['lost'] <= MIN_AREA:
                continue
            for key, geom in (('before', before[ident]), ('after', after[ident]),
                              ('gained', after[ident].difference(before[ident])), ('lost', before[ident].difference(after[ident]))):
                if not geom.is_empty:
                    features[key].append({'type': 'Feature', 'properties': {'index': ident}, 'geometry': mapping(geom)})
        if hasattr(shapely, 'coverage_invalid_edges') and shapely.geos_version >= (3, 12, 0):
            defects = shapely.coverage_invalid_edges(list(before.values()), gap_width=gap_width)
            result['diagnostic_method'] = 'coverage'
        else:
            defects = []
            for pos, ident in enumerate(ids):
                for other_pos in tree.query(footprints[pos].buffer(gap_width)):
                    other = ids[int(other_pos)]
                    if int(other_pos) > pos:
                        defects.append(boundary(before[ident]).intersection(boundary(before[other]).buffer(gap_width)))
            result['diagnostic_method'] = 'proximity'
        for geom in defects:
            if not geom.is_empty:
                features['defects'].append({'type': 'Feature', 'properties': {}, 'geometry': mapping(geom)})
        result['layers'] = {key: {'type': 'FeatureCollection', 'features': value} for key, value in features.items()}
    return result


_SESSION_PROJECTS = set()     # projects already opened in this session (their snapshot history is from this session)


class Project:
    def __init__(self, folder, backup_dir, pack=None):
        self.dir = folder
        os.makedirs(folder, exist_ok=True)
        pf = os.path.join(folder, 'pack.json')
        meta = json.load(open(pf)) if os.path.exists(pf) else {}
        self.pack = pack or meta.get('pack') or 'World'      # regionpack this project edits (the one of its folder)
        if meta.get('pack') and pack and meta['pack'] != pack:
            print('AVISO: %s decía regionpack %s; se usa %s (el de la carpeta)' % (pf, meta['pack'], pack))
            meta['decided'] = False
        self.decided = meta.get('decided', False)              # already asked where to install
        # new regionpack from scratch (new_pack.py): does not exist in the game yet; what it takes from World lives in <project>/base
        self.virtual = bool(meta.get('nuevo')) and not os.path.isdir(os.path.join(MAPS, self.pack))
        self.base = os.path.join(folder, 'base')
        self.map_dir = self.base if self.virtual else os.path.join(MAPS, self.pack)
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
        # «Volver / Rehacer» only within the session: when the project is first opened, snapshots
        # from previous sessions are deleted (what remains of them is in the changelog)
        key = os.path.normcase(os.path.abspath(folder))
        if key not in _SESSION_PROJECTS:
            _SESSION_PROJECTS.add(key)
            for d in os.listdir(self.history):
                if d.isdigit() or d == 'rehacer':
                    shutil.rmtree(os.path.join(self.history, d), ignore_errors=True)
        self.reload()

    # ------------------------------------------------------------------ estado
    def installed_state(self):
        """Compares the project copy with the regionpack installed in the game.
        'same': equal; 'pending': project changes not installed; 'changed': the game's one changed outside the editor."""
        import filecmp
        if self.virtual:
            return 'pending'
        files = list(XML_FILES) + (['map.xml'] if os.path.exists(os.path.join(self.xml, 'map.xml')) else [])
        same = all(filecmp.cmp(os.path.join(self.xml, f), os.path.join(self.map_dir, 'xml', f), shallow=False) for f in files)
        if same:
            return 'same'
        return 'pending' if any(not e.get('instalado') for e in self.changelog()) else 'changed'

    def prune_changelog(self, log=print):
        """Removes from the changelog the new regions that no longer exist in the map (e.g. if a pristine regionpack was put on top
        and the old changelog.json remained): the changelog must describe the map as it is."""
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
            for e in cl:   # transfers and adjacencies of those regions no longer describe the map either
                e['traspasos'] = [t for t in e.get('traspasos', []) if t.get('de') not in g and t.get('a') not in g]
                e['vecindades_nuevas'] = [v for v in e.get('vecindades_nuevas', []) if not g & set(v)]
            cl = [e for e in cl if e.get('regiones_nuevas') or e.get('regiones_eliminadas') or e.get('traspasos')
                  or e.get('centros') or e.get('vecindades_nuevas') or e.get('renombradas') or e.get('canales') or e.get('tipos')]
            changelog_keys.dump(cl, self.changelog_path())
            log('changelog: quitadas regiones que no están en el mapa: %s' % ', '.join(gone))
        return gone

    # ------------------------------------------------------------------ revisar el changelog contra World
    def review_changelog(self, base='World'):
        """Compares the project map with the 'base' regionpack (World) and with the changelog. Rows:
        'ok': new region in the map and in the changelog; 'missing': in the map but not in the changelog (its mother is proposed);
        'stale': in the changelog but not in the map. 'deleted': 'base' regions the map no longer has."""
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
            # proposed mother: the neighbour (existing in the base) whose base shape overlaps the new region most
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
        for n, (date, x) in logged.items():
            if n not in cur:
                rows.append({'name': n, 'status': 'stale', 'sea': bool(x.get('mar')), 'mother': x.get('madre'), 'date': date})
        deleted = sorted(n for n in bidx if n not in cur)
        return {'base': base, 'pack': self.pack, 'rows': sorted(rows, key=lambda r: (r['status'] != 'stale', r['name'])), 'deleted': deleted}

    def apply_review(self, keep, add, base='World'):
        """Keeps in the changelog only the new regions in 'keep' and records those in 'add' (map regions that were missing).
        If the project matches the installed regionpack, the game's changelog is updated too."""
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
                  or e.get('centros') or e.get('vecindades_nuevas') or e.get('renombradas') or e.get('canales') or e.get('tipos')]
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
            changelog_keys.dump(cl, self.changelog_path())
            if same:
                shutil.copy2(self.changelog_path(), os.path.join(self.map_dir, 'changelog.json'))
            return {'removed': sorted(gone), 'added': [x['nombre'] for x in news], 'game_updated': same}

    def rename_region(self, old, new, text=None):
        """Changes the name (in the scenarios) of a region: RegionRename in the project copy of map.xml
        (installed with «Instalar») and a «renombradas» entry in the changelog to adapt other scenarios."""
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
                if last:
                    t = t[:last[-1].end()] + block + t[last[-1].end():]
                else:        # new regionpack: no entries yet; goes inside the AreaMap, before its closing tag
                    k = t.rfind('</object>')
                    if k < 0:
                        raise ValueError('map.xml no tiene un AreaMap donde añadirlo')
                    t = t[:k].rstrip(' \t') + block + '\t' + t[k:]
            open(mp, 'w', encoding='utf-8', newline='').write(t)
            cl = self.changelog()
            for e in cl:
                for x in e.get('regiones_nuevas', []):
                    if x.get('nombre') == old:
                        x['nombre'] = new
            cl.append({'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': self.pack, 'instalado': False,
                       'operaciones': ['renombrar'], 'renombradas': [{'de': old, 'a': new, 'texto': text or new, 'interno': raw}]})
            changelog_keys.dump(cl, self.changelog_path())
            self.reload()
            return {'raw': raw}

    # ------------------------------------------------------------------ navigation of sea regions (canals)
    # map.xml: <object type="CanalRegions"> (strCanalRegionName = sea, strCanalZoneRegionName = owned region linked to the canal)
    # closes navigation of that sea region; <object type="FoggingLinkedRegions"> (strRegionNameLinkedTo / LinkedFrom) in case it
    # only links the fog and leaves navigation free (this is how the WorldPublicPanamaCanalAndSuez regionpack does it).
    _CANAL_RE = re.compile(r'[ \t]*<object type="CanalRegions"[^>]*>\s*<property name="strCanalRegionName" value="([^"]*)"\s*/>\s*'
                           r'<property name="strCanalZoneRegionName" value="([^"]*)"\s*/>\s*</object>[ \t]*\r?\n?')
    _FOG_RE = re.compile(r'[ \t]*<object type="FoggingLinkedRegions"[^>]*>\s*<property name="strRegionNameLinkedTo" value="([^"]*)"\s*/>\s*'
                         r'<property name="strRegionNameLinkedFrom" value="([^"]*)"\s*/>\s*</object>[ \t]*\r?\n?')

    def _map_xml_text(self):
        mp = os.path.join(self.xml, 'map.xml')
        if not os.path.exists(mp):
            mp = os.path.join(self.map_dir, 'xml', 'map.xml')
        return open(mp, encoding='utf-8', errors='replace', newline='').read()

    def canal_info(self, name):
        """{'state': 'cerrada' | 'libre', 'zone': linked region or None, 'fog': [fog-linked regions]} of a sea region."""
        from xml.sax.saxutils import unescape
        t = self._map_xml_text()
        for m in self._CANAL_RE.finditer(t):
            if unescape(m.group(1)) == name:
                return {'state': 'cerrada', 'zone': unescape(m.group(2)), 'fog': []}
        fog = []
        for m in self._FOG_RE.finditer(t):
            a, b = unescape(m.group(1)), unescape(m.group(2))
            if a == name:
                fog.append(b)
            elif b == name:
                fog.append(a)
        return {'state': 'libre', 'zone': None, 'fog': fog}

    def set_canal(self, name, closed, zone=None):
        """Sea region with free or closed navigation (canal). Closed: 'zone' is the region linked to the canal (the country's).
        Written to the project copy of map.xml (installed with «Instalar») and recorded in the changelog."""
        from xml.sax.saxutils import escape, unescape
        with self.lock:
            names = {self.rname(g.index): g for g in self.m['regions']}
            if name not in names:
                raise ValueError('no existe la región %s' % name)
            if names[name].u_type != SEA:
                raise ValueError('%s no es una región de mar' % name)
            zone = (zone or '').strip() or None
            if closed:
                if not zone:
                    raise ValueError('elige la región ligada al canal (la zona del canal)')
                if zone == name or zone not in names:
                    raise ValueError('la zona del canal debe ser otra región del mapa')
            mp = os.path.join(self.xml, 'map.xml')
            if not os.path.exists(mp):
                shutil.copy2(os.path.join(self.map_dir, 'xml', 'map.xml'), mp)
            t = open(mp, encoding='utf-8', errors='replace', newline='').read()
            nl = '\r\n' if '\r\n' in t else '\n'
            old = self.canal_info(name)
            t = self._CANAL_RE.sub(lambda m: '' if unescape(m.group(1)) == name else m.group(0), t)
            link = zone or old['zone'] or (old['fog'][0] if old['fog'] else None)
            if closed:         # la niebla enlazada de la pareja pasa a ser el canal
                t = self._FOG_RE.sub(lambda m: '' if (unescape(m.group(1)), unescape(m.group(2))) == (name, zone) else m.group(0), t)
                block = ('\t\t<object type="CanalRegions" name="objCanalRegions">' + nl
                         + '\t\t\t<property name="strCanalRegionName" value="' + escape(name, {'"': '&quot;'}) + '"/>' + nl
                         + '\t\t\t<property name="strCanalZoneRegionName" value="' + escape(zone, {'"': '&quot;'}) + '"/>' + nl
                         + '\t\t</object>' + nl)
            else:              # free: no CanalRegions; the fog link with its zone is kept (as in WorldPublicPanamaCanalAndSuez)
                have = {(unescape(m.group(1)), unescape(m.group(2))) for m in self._FOG_RE.finditer(t)}
                block = ''
                if old['state'] == 'cerrada' and link and (name, link) not in have:
                    block = ('\t\t<object type="FoggingLinkedRegions" name="objFoggingLinkedRegions">' + nl
                             + '\t\t\t<property name="strRegionNameLinkedTo" value="' + escape(name, {'"': '&quot;'}) + '"/>' + nl
                             + '\t\t\t<property name="strRegionNameLinkedFrom" value="' + escape(link, {'"': '&quot;'}) + '"/>' + nl
                             + '\t\t</object>' + nl)
            if block:
                kind = 'CanalRegions' if closed else 'FoggingLinkedRegions'
                last = list(re.finditer(r'<object type="%s"[^>]*>.*?</object>[ \t]*\r?\n?' % kind, t, flags=re.S))
                if last:
                    t = t[:last[-1].end()] + block + t[last[-1].end():]
                else:
                    k = t.rfind('</object>')
                    if k < 0:
                        raise ValueError('map.xml no tiene un AreaMap donde añadirlo')
                    t = t[:k].rstrip(' \t') + block + '\t' + t[k:]
            open(mp, 'w', encoding='utf-8', newline='').write(t)
            cl = self.changelog()
            cl.append({'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': self.pack, 'instalado': False,
                       'operaciones': ['canal'], 'regiones_nuevas': [],
                       'canales': [{'region': name, 'cerrada': bool(closed), 'zona': zone if closed else None}]})
            changelog_keys.dump(cl, self.changelog_path())
            self.reload()
            return self.canal_info(name)

    # ------------------------------------------------------------------ map.xml: vinculos entre regiones
    # ConnectedRegions (A, B): joined even if not neighbours (straits, ferries); DisconnectedRegions: neighbours but no passage;
    # FoggingLinkedRegions: linked fog. New regions do NOT appear in map.xml just by existing (only in regions.bin), but a
    # region taken from another does not inherit its mother's links: here they are copied to the project's map.xml.
    _LINK_RE = re.compile(r'[ \t]*<object type="(ConnectedRegions|DisconnectedRegions|FoggingLinkedRegions)"[^>]*>\s*'
                          r'<property name="(\w+)" value="([^"]*)"\s*/>\s*<property name="(\w+)" value="([^"]*)"\s*/>\s*</object>[ \t]*\r?\n?')

    def inherit_links(self, created):
        """Copies to each new region the map.xml links of its mother (or mothers): Disconnected and Fogging if the new one neighbours
        the other region; Connected if it is within 1.5 degrees of it. Returns the added lines (for the report)."""
        from xml.sax.saxutils import escape, unescape
        news = [c for c in created if c.get('mothers') or c.get('mother')]
        if not news:
            return []
        t = self._map_xml_text()
        nl = '\r\n' if '\r\n' in t else '\n'
        links = [(m.group(1), unescape(m.group(3)), unescape(m.group(5)), m.group(2), m.group(4)) for m in self._LINK_RE.finditer(t)]
        if not links:
            return []
        have = {(k, a, b) for k, a, b, _, _ in links} | {(k, b, a) for k, a, b, _, _ in links}
        idx = {self.rname(g.index): g.index for g in self.m['regions']}
        add, notes = [], []
        for c in news:
            mothers = set(c.get('mothers') or ()) | ({c['mother']} if c.get('mother') else set())
            mothers = {self.rname(g.index) for g in self.m['regions'] if g.name in mothers or self.rname(g.index) in mothers}
            new = c['name']
            if new not in idx:
                continue
            ni = idx[new]
            nbs = {self.rname(n) for n in self.m['regions'][ni].neighbors}
            poly = None
            for kind, a, b, pa, pb in links:
                for mo, other in ((a, b), (b, a)):
                    if mo not in mothers or other == new or other not in idx or (kind, new, other) in have:
                        continue
                    ok = other in nbs
                    if kind == 'ConnectedRegions' and not ok:
                        poly = poly or new_region.mesh_polygon(self.m, ni)
                        ok = poly is not None and not poly.is_empty and poly.distance(new_region.mesh_polygon(self.m, idx[other])) < 1.5
                    if ok:
                        add.append((kind, new, other, pa, pb))
                        have |= {(kind, new, other), (kind, other, new)}
                        notes.append('%s: %s ↔ %s (de %s)' % (kind, new, other, mo))
        if not add:
            return []
        mp = os.path.join(self.xml, 'map.xml')
        if not os.path.exists(mp):
            shutil.copy2(os.path.join(self.map_dir, 'xml', 'map.xml'), mp)
        t = open(mp, encoding='utf-8', errors='replace', newline='').read()
        q = {'"': '&quot;'}
        block = ''.join('\t\t<object type="%s" name="obj%s">%s\t\t\t<property name="%s" value="%s"/>%s\t\t\t<property name="%s" value="%s"/>%s\t\t</object>%s'
                        % (k, k, nl, pa, escape(a, q), nl, pb, escape(b, q), nl, nl) for k, a, b, pa, pb in add)
        k = t.rfind('</object>')
        t = t[:k].rstrip(' \t') + block + '\t' + t[k:]
        open(mp, 'w', encoding='utf-8', newline='').write(t)
        self.reload()
        return notes

    # ------------------------------------------------------------------ vecindades forzadas (map.xml)
    # ConnectedRegions: adjacent even if they don't touch (islands, shores of a lake); DisconnectedRegions: not adjacent even if they touch
    LINK_KINDS = ('ConnectedRegions', 'DisconnectedRegions')

    def region_links(self, name=None):
        """Forced adjacencies of map.xml, of region 'name' or all: [{kind, a, b}]."""
        from xml.sax.saxutils import unescape
        out = [{'kind': m.group(1), 'a': unescape(m.group(3)), 'b': unescape(m.group(5))}
               for m in self._LINK_RE.finditer(self._map_xml_text()) if m.group(1) in self.LINK_KINDS]
        return [x for x in out if name is None or name in (x['a'], x['b'])]

    def set_region_link(self, a, b, kind='ConnectedRegions', on=True):
        """Creates (on) or removes in the project's map.xml the forced adjacency between a and b. Reaches the game with «Instalar»."""
        from xml.sax.saxutils import escape, unescape
        with self.lock:
            names = {self.rname(g.index) for g in self.m['regions']}
            if kind not in self.LINK_KINDS:
                raise ValueError('tipo de vínculo desconocido: %s' % kind)
            if a == b or a not in names or b not in names:
                raise ValueError('hacen falta dos regiones distintas de este regionpack')
            mp = os.path.join(self.xml, 'map.xml')
            if not os.path.exists(mp):
                shutil.copy2(os.path.join(self.map_dir, 'xml', 'map.xml'), mp)
            t = open(mp, encoding='utf-8', errors='replace', newline='').read()
            nl = '\r\n' if '\r\n' in t else '\n'
            same = lambda m: m.group(1) == kind and {unescape(m.group(3)), unescape(m.group(5))} == {a, b}
            had = any(same(m) for m in self._LINK_RE.finditer(t))
            if had == bool(on):
                return {'changed': False}
            t = self._LINK_RE.sub(lambda m: '' if same(m) else m.group(0), t)
            if on:
                q = {'"': '&quot;'}
                block = ('\t\t<object type="%s" name="obj%s">%s\t\t\t<property name="strRegionNameA" value="%s"/>%s\t\t\t<property name="strRegionNameB" value="%s"/>%s\t\t</object>%s'
                         % (kind, kind, nl, escape(a, q), nl, escape(b, q), nl, nl))
                last = [m for m in self._LINK_RE.finditer(t) if m.group(1) == kind]
                if last:                 # next to those of its type
                    t = t[:last[-1].end()] + block + t[last[-1].end():]
                else:
                    k = t.rfind('</object>')
                    if k < 0:
                        raise ValueError('map.xml no tiene un AreaMap donde añadirlo')
                    t = t[:k].rstrip(' \t') + block + '\t' + t[k:]
            open(mp, 'w', encoding='utf-8', newline='').write(t)
            cl = self.changelog()        # uninstalled change: «Instalar» takes it to the game
            cl.append({'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': self.pack, 'instalado': False,
                       'operaciones': ['vinculo'], 'vinculos': [{'tipo': kind, 'a': a, 'b': b, 'accion': 'añadir' if on else 'quitar'}]})
            changelog_keys.dump(cl, self.changelog_path())
            self.reload()
            return {'changed': True}

    def near_unlinked(self, names, max_deg=0.15):
        """Land regions within max_deg of any of 'names' that are not their neighbours and are separated from them only by a gap without
        a region (a lake, a deleted river): ConnectedRegions candidates. [{a, b, km}] for the page to offer after saving."""
        from shapely.geometry import LineString
        from shapely.ops import nearest_points
        R = self.m['regions']
        idx = {g.name: g.index for g in R}
        linked = {frozenset((x['a'], x['b'])) for x in self.region_links()}
        mesh = {}

        def M(i):
            if i not in mesh:
                mesh[i] = new_region.mesh_polygon(self.m, i)
            return mesh[i]
        out, seen = [], set()
        for nm in list(dict.fromkeys(names))[:40]:      # shortcut: 40 regions per save; the rest, by hand in the region panel
            r = idx.get(nm)
            if r is None or R[r].u_type == SEA or not self.bbox[r] or M(r) is None:
                continue
            b = self.bbox[r]
            for g in R:
                o, bb = g.index, self.bbox[g.index]
                pair = frozenset((self.rname(r), self.rname(o)))
                if (o == r or g.u_type == SEA or o in R[r].neighbors or pair in linked or pair in seen or not bb
                        or bb[2] < b[0] - max_deg or bb[0] > b[2] + max_deg or bb[3] < b[1] - max_deg or bb[1] > b[3] + max_deg or M(o) is None):
                    continue
                d = M(r).distance(M(o))
                if not 0 < d < max_deg:
                    continue
                way = LineString(nearest_points(M(r), M(o)))
                wb = way.bounds
                if any(i not in (r, o) and bx and not (bx[2] < wb[0] or bx[0] > wb[2] or bx[3] < wb[1] or bx[1] > wb[3])
                       and M(i) is not None and M(i).intersects(way) for i, bx in enumerate(self.bbox)):
                    continue             # there is another region (or sea) in between: it's not just a gap
                seen.add(pair)
                out.append({'a': self.rname(r), 'b': self.rname(o), 'km': round(d * 111)})
        return out

    # ------------------------------------------------------------------ tipo de region: mar <-> tierra
    def convert_region_type(self, names, to, terrain=1):
        """Switches regions between sea and land (e.g. imported land left as sea: in the game a sea region cannot be
        selected and has no owner). to: 'land' (terrain 1..4: plains, hills, mountain, desert) or 'sea'.
        Land: u_type = terrain and u_a = u_b (all its area is land); sea: u_type 0 and u_a 0. The mesh and borders don't change."""
        with self.lock:
            R = self.m['regions']
            by = {self.rname(g.index): g for g in R}
            terrain = int(terrain or 1)
            if to not in ('land', 'sea'):
                raise ValueError("el tipo debe ser 'land' o 'sea'")
            if to == 'land' and not 1 <= terrain <= 4:
                raise ValueError('terreno no válido (1..4)')
            done, skipped = [], []
            for n in names:
                g = by.get(n)
                if g is None:
                    skipped.append('%s: no existe' % n)
                    continue
                if to == 'land':
                    g.u_type, g.u_a = terrain, (g.u_b or g.u_a)
                else:
                    g.u_type, g.u_a = SEA, 0
                done.append(n)
            if not done:
                return {'done': [], 'skipped': skipped}
            self.snapshot(print, keep_redo=True)
            self._pending_snapshot = True
            mhmap.save_map(self.m, self.xml)
            self._pending_snapshot = False
            cl = self.changelog()
            for e in cl:
                for x in e.get('regiones_nuevas', []):
                    if x.get('nombre') in done:
                        x['mar'] = to == 'sea'
                        x['tipo'] = SEA if to == 'sea' else terrain
            cl.append({'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': self.pack, 'instalado': False, 'operaciones': ['tipo_region'],
                       'regiones_nuevas': [], 'tipos': [{'region': n, 'mar': to == 'sea', 'terreno': None if to == 'sea' else terrain} for n in done]})
            json.dump(cl, open(self.changelog_path(), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            self.reload()
            return {'done': done, 'skipped': skipped}

    def load_installed(self):
        """Copies the game's regionpack (with its changelog) into the project again; clears «Volver / Rehacer»."""
        if self.virtual:
            raise ValueError('el regionpack %s todavía no está instalado en el juego' % self.pack)
        with self.lock:
            for f in XML_FILES:
                shutil.copy2(os.path.join(self.map_dir, 'xml', f), os.path.join(self.xml, f))
            if os.path.exists(os.path.join(self.xml, 'map.xml')):
                os.remove(os.path.join(self.xml, 'map.xml'))      # uses the game's map.xml again
            src = os.path.join(self.map_dir, 'changelog.json')
            if os.path.exists(src):
                shutil.copy2(src, self.changelog_path())
            elif os.path.exists(self.changelog_path()):
                os.remove(self.changelog_path())
            for d in os.listdir(self.history):
                if d.isdigit() or d == 'rehacer':
                    shutil.rmtree(os.path.join(self.history, d), ignore_errors=True)
            # the background too: the project's tiles were from the previous map and covered those of the newly loaded regionpack
            # (the old borders showed in the background and a later «Instalar» would have taken them to the game)
            stale = self.drop_stale_tiles(everything=True)
            self.reload()
            self.prune_changelog()
            return stale

    def drop_stale_tiles(self, everything=False, dry=False):
        """Removes from the project's tiles/ the background tiles covering those of the installed regionpack: all (when loading the game's
        regionpack) or those differing from the game's. With dry it only counts them (the page asks: they may be uninstalled painted background)."""
        import filecmp
        if self.virtual:
            return 0
        art, n = os.path.join(self.map_dir, 'art', 'OperationalTerrain'), 0
        for f in os.listdir(self.tiles):
            p, g = os.path.join(self.tiles, f), os.path.join(art, f)
            if os.path.isfile(p) and (everything or (os.path.exists(g) and not filecmp.cmp(p, g, shallow=False))):
                if not dry:
                    os.remove(p)
                n += 1
        return n

    def reload(self):
        with self.lock:
            self.m = mhmap.load_map(self.xml)
            # map.xml: the project copy (if a region was renamed and not yet installed) or the game's
            self.renames = load_renames(self.dir if os.path.exists(os.path.join(self.xml, 'map.xml')) else self.map_dir)
            self.outline_cache = {}
            self._seam_cache = {}
            self._geom_cache = {}
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
            # ring tracing can come out valid but wrong (after splitting T-junctions it joins vertices that do not touch:
            # Wilno after subtracting Lithuania came out with 5.4 degrees² of 9.7 and an edge of 3.5°): if it doesn't match the mesh area,
            # the union of the triangles is used
            if ok and len(mhmap.region_shapes(self.m, r)) == 1 and abs(g.area - self._tri_area(self.m, r)) > 0.005 * max(g.area, 1e-9):
                ok = False         # (island regions, with halo and detail in two shapes, are not compared)
            if not ok and self._mesh_ok(self.m, r):
                # invalid ring tracing (pinches) with a sound mesh: the union of its triangles is drawn and edited
                u = new_region.mesh_polygon(self.m, r)
                polys = [q for q in getattr(u, 'geoms', [u]) if q.geom_type == 'Polygon' and q.area > MIN_AREA]
                main = [[[list(c) for c in q.exterior.coords]] + [[list(c) for c in h.coords] for h in q.interiors] for q in polys]
                g = shape({'type': 'MultiPolygon', 'coordinates': main}) if main else None
                ok = g is not None and g.is_valid
            self.outline_cache[r] = (main, detail, ok, '' if ok else (explain_validity(g) if g is not None else 'vacia'))
        return self.outline_cache[r]

    def precompute(self):
        for r in range(len(self.m['regions'])):
            with self.lock:
                self.outline(r)

    def rname(self, r):
        """Name of the region as used by the scenarios (with the RegionRename entries of map.xml)."""
        n = self.m['regions'][r].name
        return self.renames.get(n, n)

    def meta(self):
        with self.lock:          # reload() changes map and bbox together: without the lock, a save in progress raised IndexError
            R = self.m['regions']
            return [{'index': g.index, 'name': self.rname(g.index), 'mapName': g.name, 'type': g.u_type, 'sea': g.u_type == SEA,
                     'bbox': self.bbox[g.index], 'center': [g.cx, g.cy]} for g in R]

    @staticmethod
    def _merge_seams(main, eps=5e-5):
        """Pieces of a region separated by ~2 m slivers (rounding leftovers of repeated transfers): the map draws them as a line
        crossing the region (not visible in the game). For drawing, pieces that almost touch are merged into one; the rest stays the same."""
        if len(main) < 2:
            return main
        try:
            polys = [Polygon(pl[0], pl[1:]) for pl in main]
            grown = [q.buffer(eps, join_style=2) for q in polys]
            u = unary_union(grown)
            groups = [g for g in getattr(u, 'geoms', [u]) if g.geom_type == 'Polygon']
            if len(groups) == len(polys):
                return main
            out = []
            for g in groups:
                inside = [i for i, q in enumerate(polys) if g.intersects(q)]
                if len(inside) == 1:
                    out.append(main[inside[0]])
                    continue
                m = g.buffer(-eps, join_style=2)
                for q in getattr(m, 'geoms', [m]):
                    if q.geom_type == 'Polygon' and q.area > 0:
                        out.append([[list(c) for c in q.exterior.coords]] + [[list(c) for c in h.coords] for h in q.interiors])
            return out
        except Exception:
            return main

    def features(self, x0, y0, x1, y1, limit=1500):
        R = self.m['regions']
        out = []
        with self.lock:
            for g in R:
                b = self.bbox[g.index]
                if b[2] < x0 or b[0] > x1 or b[3] < y0 or b[1] > y1:
                    continue
                main, detail, ok, why = self.outline(g.index)
                sc_ = self._seam_cache
                if g.index not in sc_:
                    sc_[g.index] = self._merge_seams(main)          # only for drawing
                main = sc_[g.index]
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
    # sanitizing levels for save polygons when the resulting mesh would be broken (invalid outline)
    CLEAN_LEVELS = 4

    @staticmethod
    def _clean_geom(g, level):
        """Sanitized polygon: 1 = valid and without degenerate pieces; 2 = 1e-5 degree grid; 3 = simplified (1e-4);
        4 = rounded (buffer +-2e-4, removes spikes and slivers under ~20 m)."""
        import shapely
        g = make_valid(g)
        g = unary_union([x for x in getattr(g, 'geoms', [g]) if x.geom_type in ('Polygon', 'MultiPolygon')] or [Polygon()])
        g = g.buffer(0)
        if level == 2:
            g = make_valid(shapely.set_precision(g, 1e-5))
        elif level == 3:
            g = make_valid(g.simplify(1e-4, preserve_topology=True))
        elif level >= 4:
            g = g.buffer(2e-4, join_style=2).buffer(-2e-4, join_style=2)
        polys = [x for x in getattr(g, 'geoms', [g]) if x.geom_type == 'Polygon' and x.area > MIN_AREA]
        return MultiPolygon(polys) if polys else MultiPolygon()

    def _clean_payload(self, payload, level):
        pl = json.loads(json.dumps(payload))
        for k, coords in list((pl.get('modified') or {}).items()):
            g = self._clean_geom(shape({'type': 'MultiPolygon', 'coordinates': coords}), level)
            if not g.is_empty:
                pl['modified'][k] = mapping(g)['coordinates']
        for asg in pl.get('assigns') or []:
            poly = asg.get('polygon')
            if poly and poly.get('type') in ('Polygon', 'MultiPolygon') and asg.get('kind') != 'stroke':
                g = self._clean_geom(shape(poly), level)
                if not g.is_empty:
                    asg['polygon'] = mapping(g)
        return pl

    def save(self, payload, log=print):
        """Saves; if the resulting mesh would be broken (invalid outline) it retries sanitizing the polygons step by step
        (valid -> grid -> simplified -> rounded) instead of refusing. The report notes the level used."""
        last = None
        payload = self._effective_modified(payload)
        asg_ok = any(a.get('kind', 'assign') == 'assign' and a.get('polygon') for a in payload.get('assigns') or [])
        if payload.get('fix') == 'drop_bad' and (payload.get('modified') or asg_ok):
            return self._save_dropping_bad(payload, log)
        for level in range(self.CLEAN_LEVELS + 1):
            pl = payload if level == 0 else self._clean_payload(payload, level)
            try:
                rep = self._save_once(pl, log)
            except (SystemExit, GEOSException) as e:
                if isinstance(e, GEOSException):     # GEOS could not handle the geometry as is: retry sanitized, the raw error never comes out
                    log('GEOS: %s' % e)
                    e = SystemExit('No se guardó nada: la geometría de los cambios no se pudo calcular, ni saneándola (contorno inválido). '
                                   'Los cambios siguen pendientes: revisa el último polígono dibujado (que no se cruce consigo mismo) o guarda las operaciones por partes.')
                elif 'quedaría rota' not in str(e) and 'contorno inválido' not in str(e) and 'saldría con' not in str(e):
                    raise
                self._drop_pending_snapshot()
                self.reload()
                last = e
                log('malla rota con el poligono tal cual: se reintenta saneado (nivel %d)' % (level + 1))
                continue
            if level:
                rep.setdefault('warnings', []).append('El contorno se ajustó automáticamente (nivel %d de %d: %s) para que la malla no se rompiera'
                                                       % (level, self.CLEAN_LEVELS, ('válido', 'rejilla de 1e-5°', 'simplificado', 'redondeado')[level - 1]))
            return rep
        if payload.get('modified') or asg_ok:      # the page offers it as a button (resends with fix='drop_bad')
            raise SystemExit(str(last) + ' Solución: guardar sin las partes del cambio que rompen la malla (el editor las busca y dice cuáles quita).')
        raise last

    def _save_dropping_bad(self, payload, log=print):
        """The fix the editor proposes when a shape change breaks the mesh: tries its parts (gained and lost) from
        largest to smallest, without writing, and saves only those that keep it sound. The report says what was removed and where."""
        mod = payload.get('modified') or {}
        asgs = payload.get('assigns') or []
        with self.lock:
            mesh = {k: new_region.mesh_polygon(self.m, int(k)) for k in mod}
            parts = []
            for k, coords in mod.items():
                g = make_valid(shape({'type': 'MultiPolygon', 'coordinates': coords}))
                parts += [(k, 1, p) for p in polys_of(g.difference(mesh[k]))] + [(k, -1, p) for p in polys_of(mesh[k].difference(g))]
            for i, a in enumerate(asgs):     # «Añadir área» (GeoJSON, assign): each part of its polygon
                if a.get('kind', 'assign') == 'assign' and a.get('polygon'):
                    parts += [(i, 0, p) for p in polys_of(make_valid(shape(a['polygon'])))]
        parts.sort(key=lambda x: -x[2].area)
        tried, skipped = parts[:12], parts[12:]      # shortcut: ~3 s per try, only the 12 largest; if needed, raise the cap

        def build(sel):
            out = {}
            for k in mod:
                add = unary_union([p for kk, s, p in sel if kk == k and s > 0] or [Polygon()])
                sub = unary_union([p for kk, s, p in sel if kk == k and s < 0] or [Polygon()])
                polys = polys_of(make_valid(mesh[k].union(add).difference(sub)))
                if polys:
                    out[k] = mapping(MultiPolygon(polys))['coordinates']
            na = []
            for i, a in enumerate(asgs):
                if a.get('kind', 'assign') == 'assign' and a.get('polygon'):
                    ps = [p for kk, s, p in sel if kk == i and s == 0]
                    if ps:
                        na.append(dict(a, polygon=mapping(MultiPolygon(ps))))
                else:
                    na.append(a)
            return dict(payload, modified=out, assigns=na, fix=None)

        kept = []
        for part in tried:
            try:
                self._save_once(dict(build(kept + [part]), _dry=True), lambda *a: None)
            except _DryOK:
                kept.append(part)
            except SystemExit:
                pass
            finally:
                self._drop_pending_snapshot()
                self.reload()
        if not kept:
            raise SystemExit('No se guardó nada: ninguna parte del cambio, ni siquiera sola, deja la malla sana. Descarta el cambio y añádelo por partes más pequeñas.')
        rep = self._save_once(build(kept), log)
        for k, s, p in tried + skipped:
            if (k, s, p) not in kept:
                c = p.representative_point()
                rep.setdefault('warnings', []).append('%s: se quitó del cambio una parte de %.4f grados² cerca de %s para que la malla no se rompiera'
                                                       % (self.rname(int(asgs[k]['region'] if s == 0 else k)), p.area, _where(c.x, c.y)))
        return rep

    def _effective_modified(self, payload):
        """Edited shapes ('modified') arrive over the outline the page draws (features: pieces with slivers merged,
        traced outline), which is not exactly the mesh (e.g. Ubangi Shari: 146 pieces of difference). Only what the user
        changed (gained and lost relative to the drawing) is applied to the mesh; otherwise every sliver and rounding became a transfer."""
        mod = payload.get('modified') or {}
        if not mod:
            return payload
        out = {}
        with self.lock:
            for k, coords in mod.items():
                out[k] = coords
                try:
                    r = int(k)
                    g = shape({'type': 'MultiPolygon', 'coordinates': coords})
                    if not g.is_valid:
                        continue          # _save_once explains why it's not valid
                    main = self.outline(r)[0]
                    if not main:
                        continue
                    drawn = make_valid(shape({'type': 'MultiPolygon', 'coordinates': self._merge_seams(main)}))
                    mesh = new_region.mesh_polygon(self.m, r)
                    # without the rounding slivers (e.g. a Mauritius GeoJSON repeating its outline with other decimals: strips
                    # of 1e-4 degrees² along the border that, stuck to the mesh, crossed its outline and the save was refused)
                    ch = drop_slivers([(p, 1) for p in polys_of(g.difference(drawn))] + [(p, -1) for p in polys_of(drawn.difference(g))])
                    eff = make_valid(mesh.union(unary_union([p for p, s in ch if s > 0] or [Polygon()]))
                                     .difference(unary_union([p for p, s in ch if s < 0] or [Polygon()])))
                    polys = polys_of(eff)
                    if polys:
                        out[k] = mapping(MultiPolygon(polys))['coordinates']
                except Exception:
                    pass                  # geometry GEOS can't subtract: used as is (as before)
        return dict(payload, modified=out)

    def _save_once(self, payload, log=print):
        """payload: {modified: {idx: coords MultiPolygon}, assigns: [{polygon, region, fill}], centers: {idx: [x, y]},
        topo: bool, paint: bool}"""
        import progress
        with self.lock:
            t0 = time.time()
            progress.step(2, 'Calculando los cambios del mapa')
            self._geom_cache = {}
            m = self.m
            R = m['regions']
            cache = {}

            def P(r):
                if r not in cache:
                    cache[r] = unary_union([Polygon(t) for s in mhmap.region_shapes(m, r) for t in s.triangles()
                                            if abs(signed_area(t)) > 0] or [Polygon()])      # empty: POLYGON EMPTY, not a collection
                return cache[r]

            def owners(geom, exclude=()):
                """Regions (not excluded) whose mesh touches the geometry, by bbox and then exactly."""
                gx0, gy0, gx1, gy1 = geom.bounds
                res = []
                for i, b in enumerate(self.bbox):
                    if i in exclude or b[2] < gx0 or b[0] > gx1 or b[3] < gy0 or b[1] > gy1:
                        continue
                    if P(i).intersects(geom):
                        res.append(i)
                return res

            report = {'errors': [], 'warnings': [], 'transfers': []}
            # region indices that no longer exist (the map changed underneath: another window, «Volver»…): before, IndexError as «internal error»
            ids = [a.get(k) for a in payload.get('assigns') or [] for k in ('region', 'from', 'into')] + list(payload.get('modified') or {})
            gone = sorted({str(v) for v in ids if v is not None and not (str(v).isdigit() and int(v) < len(R))})
            if gone:
                report['errors'].append('El mapa cambió desde que se hicieron estos cambios (la región nº %s ya no existe). Recarga el mapa y repítelos.' % ', '.join(gone))
                return report
            created = []   # regiones nuevas: {index, name, mother, owner, u_type}
            new_polys = {}
            for k, coords in (payload.get('modified') or {}).items():
                r = int(k)
                g = shape({'type': 'MultiPolygon', 'coordinates': coords})
                if not g.is_valid:
                    reason = explain_validity(g)
                    if payload.get('fix') == 'repair_invalid':
                        raw_repair = make_valid(g)
                        repaired = unary_union(polys_of(raw_repair))
                        if not repaired.is_empty and repaired.is_valid and repaired.area > MIN_AREA:
                            g = repaired
                            report['warnings'].append('%s: contorno reparado (%s)' % (R[r].name, reason))
                        else:
                            report['errors'].append('%s: poligono invalido (%s)' % (R[r].name, reason))
                            continue
                    else:
                        raw_repair = make_valid(g)
                        repaired = unary_union(polys_of(raw_repair))
                        if repaired.is_valid and not repaired.is_empty:
                            report.setdefault('repaired_regions', {})[str(r)] = mapping(repaired if repaired.geom_type == 'MultiPolygon' else MultiPolygon([repaired]))['coordinates']
                        neighbors = set(owners(P(r).union(repaired))) | {r}
                        before = {i: P(i) for i in neighbors}
                        after = dict(before); after[r] = repaired
                        audit = geometry_audit(before, after, visual=True)
                        def collapsed_parts(geom):
                            if geom.geom_type in ('Point', 'LineString', 'LinearRing'):
                                return [] if geom.is_empty else [geom]
                            return [part for child in getattr(geom, 'geoms', []) for part in collapsed_parts(child)]
                        collapsed = collapsed_parts(raw_repair)
                        audit['collapsed_parts'] = len(collapsed)
                        audit['layers']['collapsed'] = {'type': 'FeatureCollection', 'features': [
                            {'type': 'Feature', 'properties': {}, 'geometry': mapping(part)} for part in collapsed]}
                        report.setdefault('repair_audits', {})[str(r)] = audit
                        report.setdefault('invalid_regions', []).append(self.rname(r))
                        report['errors'].append('%s: poligono invalido (%s)' % (R[r].name, reason))
                        continue
                new_polys[r] = g
            if report['errors']:
                return report

            transfers = []
            taken = {}   # source region -> area already transferred

            def add(piece, src, dst):
                # only the polygonal part: a piece that also grazes a border arrives as a collection (polygon + line) and GEOS can't
                # intersect it with a still-empty region («Unable to determine overlay result geometry dimension» when saving new regions)
                piece = unary_union(polys_of(piece) or [Polygon()])
                if dst is not None and src is not None and not piece.is_empty:
                    # what the target ALREADY has (overlapping meshes, e.g. an island drawn over its sea): not added
                    # again (it would duplicate triangles and break its mesh, e.g. cutting sea towards Mauritius); only removed from the source
                    dup = piece.intersection(P(dst))
                    if dup.area > MIN_AREA:
                        add(dup, src, None)
                        piece = piece.difference(P(dst))
                for p in polys_of(piece):
                    if p.area < 1e-8:      # ~100 m² crumbs an outline leaves when grazing borders: they only create «pinches» in the mesh
                        continue
                    transfers.append((p, src, dst))
                    if src is not None:
                        taken[src] = unary_union([taken[src], p]) if src in taken else p

            for r in new_polys:
                if R[r].u_type != SEA:
                    new_polys[r] = self._snap(new_polys[r], owners, P, r)[0]
            # 1. gained areas: taken from whoever has them; what has no owner comes out of nothing
            for r, g in new_polys.items():
                gained = g.difference(P(r))
                if gained.area <= MIN_AREA:
                    continue
                rest = gained
                for s in owners(gained, exclude={r}):
                    part = gained.intersection(P(s))
                    if s in new_polys:
                        part = part.difference(new_polys[s])   # only what s actually gives up
                    if part.area > MIN_AREA:
                        add(part, s, r)
                        rest = rest.difference(P(s))
                if rest.area > MIN_AREA:
                    add(rest, None, r)
            # 2. lost areas nobody gained: gap
            for r, g in new_polys.items():
                lost = P(r).difference(g)
                if r in taken:
                    lost = lost.difference(taken[r])
                if lost.area > MIN_AREA:
                    if payload.get('topo', True):
                        report['warnings'].append('%s suelta %.6f grados2 que ninguna region gana: queda como hueco' % (R[r].name, lost.area))
                    add(lost, r, None)
            self._claimed = Polygon()
            self._deleting = {int(x['region']) for x in payload.get('assigns') or [] if x.get('kind') == 'delete_region'}   # se borran en este guardado
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
                    # (a sea, lake or river can also become a land region: its fleets and ports go to the neighbouring sea)
                    # what a new region of this same save already took (GeoJSON «Reemplazar») is not transferred again
                    add(P(d).difference(taken[d]) if d in taken else P(d), d, into)
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
                    # what was cut from 'from' goes to 'into' (a neighbour, land or sea) or remains as a gap
                    into = asg.get('into')
                    into = int(into) if into is not None else None
                    def current_area(src):
                        outgoing = taken.get(src, Polygon())
                        incoming = [q for q, _, dst in transfers if dst == src]
                        return unary_union([P(src).difference(outgoing)] + incoming)

                    def cut_source(src):
                        # Also redirect what a previous cut gained, keeping its real source.
                        prior = list(transfers)
                        transfers.clear()
                        for q, origin, dst in prior:
                            if dst != src:
                                transfers.append((q, origin, dst))
                                continue
                            for part in polys_of(q.difference(poly)):
                                transfers.append((part, origin, dst))
                            for part in polys_of(q.intersection(poly)):
                                if origin == into:
                                    if origin in taken:
                                        taken[origin] = taken[origin].difference(part)
                                else:
                                    transfers.append((part, origin, into))
                        piece = poly.intersection(P(src)).difference(taken.get(src, Polygon()))
                        if asg.get('keep_tiny'):
                            for part in polys_of(piece):
                                transfers.append((part, src, into))
                                taken[src] = unary_union([taken.get(src, Polygon()), part])
                        else:
                            add(piece, src, into)

                    if asg.get('cut_all'):
                        sources = set(owners(poly, exclude={into}))
                        sources.update(dst for q, _, dst in transfers if dst is not None and dst != into and q.intersects(poly))
                        for src in sorted(sources):
                            area = current_area(src)
                            piece = poly.intersection(area)
                            if piece.area > MIN_AREA and area.difference(piece).area <= MIN_AREA:
                                report['errors'].append('%s: el polígono cubre toda la región' % R[src].name)
                                continue
                            cut_source(src)
                        continue
                    if asg.get('from') is None:
                        # cut over a gap without region (selected on the map): that part of the gap goes to 'into'
                        empty = poly.difference(unary_union([P(s) for s in owners(poly)] or [Polygon()]))
                        if into is not None and empty.area > MIN_AREA:
                            add(empty, None, into)
                        else:
                            report['warnings'].append('el recorte no toca ningún hueco (o falta la región de destino)')
                        continue
                    src = int(asg['from'])
                    if into == src:
                        continue
                    area = current_area(src)      # (before: «la malla quedaría rota», which did not say why)
                    if not asg.get('keep_tiny') and area.area > MIN_AREA and area.difference(poly).area <= 0.001 * area.area:
                        report['errors'].append('%s: el polígono cubre toda la región' % R[src].name)
                        continue
                    cut_source(src)
                    continue
                for s in owners(poly, exclude={r}):
                    if asg.get('land_only') and R[s].u_type == SEA:
                        continue
                    if asg.get('same_type_only') and (R[s].u_type == SEA) != (R[r].u_type == SEA):
                        continue          # «puede quitar área del tipo contrario» checkbox unchecked: land only from land, sea only from sea
                    part = poly.intersection(P(s))
                    if kind == 'assign' and part.area < max(1e-6, 1e-4 * poly.area):
                        # grazes of an imported outline with a neighbour's border (millimetre pieces): not transferred,
                        # they left «pinches» that broke the mesh (e.g. adding Abkhazia from a GeoJSON touched Rostov and Kuban)
                        if part.area > MIN_AREA:
                            report['warnings'].append('ignorados %.1e grados² que el contorno tocaba de %s (roce con el borde)' % (part.area, R[s].name))
                        continue
                    if kind == 'assign':
                        # strips under ~100 m wide along a border (the GeoJSON repeats the outline with other decimals,
                        # e.g. «Añadir área» to Mauritius): stuck to the mesh they crossed its outline and the save was refused
                        thin = [q for q in polys_of(part) if q.buffer(-self.SNAP / 2, join_style=2).is_empty]
                        if thin:
                            part = part.difference(unary_union(thin))
                            if part.area <= MIN_AREA:
                                continue
                    add(part, s, r)
                if asg.get('fill'):
                    rest = poly.difference(unary_union([P(s) for s in owners(poly)] or [Polygon()]))
                    add(rest, None, r)

            # regions the NEW ones of this save took entirely between them (provinces redrawn over the old ones):
            # they are deleted and theirs goes to the new one that took the most area. Before, they were left with an empty mesh and the save was refused
            # («la malla de X quedaría rota») even though no single new region covered it.
            cidx = {c['index']: c['name'] for c in created}
            done = {d['index'] for d in report.get('deleted', [])}
            for s in sorted(taken):
                if s in cidx or s in done or s in self._deleting or P(s).area <= 0:
                    continue
                left = P(s).difference(taken[s])
                got = {}
                for q_, src, dst in transfers:
                    if src == s and dst in cidx:
                        got[dst] = got.get(dst, 0) + q_.area
                if not got or left.area > 0.001 * P(s).area:
                    continue
                into = max(got, key=got.get)
                for q_ in polys_of(left):          # the remaining crumbs too, so it does not keep existing with 100 m²
                    transfers.append((q_, s, into))
                report.setdefault('deleted', []).append({'index': s, 'name': self.rname(s), 'raw': R[s].name, 'into': cidx[into],
                                                         'sea': R[s].u_type == SEA})
                report['warnings'].append('%s queda entera dentro de las regiones nuevas: se elimina y lo suyo pasa a %s' % (self.rname(s), cidx[into]))
            centers = {int(k): v for k, v in (payload.get('centers') or {}).items()}
            if report['errors']:
                self.reload()
                return report
            if not transfers and not centers:
                if created:      # create_region already added it to self.m: without reloading it stayed empty and was written in the next save
                    self.reload()
                    report['errors'] += ['%s: la región nueva quedaría sin área (el polígono solo toca migas de otras regiones)' % c['name']
                                         for c in created]
                    return report
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
            gap_only = bool(payload.get('assigns')) and not payload.get('modified') and all(a.get('repair_gap') for a in payload['assigns'])
            gap_before = None
            if gap_only:
                affected = set(touched) | set(owners(unary_union([P(r) for r in touched]).buffer(self.SNAP)))
                gap_before = {r: P(r) for r in affected}
            progress.step(35, 'Traspasando áreas entre regiones')
            if transfers:
                erase, paint, new_pairs = apply_transfers(m, transfers, [], P, cache)
                changes = {'erase': [dict(mapping(x), kind=k) for k, x in erase],
                           'paint': [dict(mapping(x), kind=k) for k, x in paint], 'islands': []}
            # areas (u_a/u_b), center and points of the regions whose mesh changed
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
            self._guard(m, created, was_valid, report)      # aborts (without writing) if the result is not the expected one
            if gap_before:
                audit = geometry_audit(gap_before, {r: new_region.mesh_polygon(m, r) for r in gap_before})
                report['geometry_audit'] = audit
                tolerance = max(1e-7, sum(shape(a['polygon']).area for a in payload['assigns']) * 0.01)
                if (any(row['empty'] for row in audit['regions']) or audit['coverage_lost'] > tolerance or
                        audit['overlap_after'] > audit['overlap_before'] + tolerance):
                    self._drop_pending_snapshot()
                    self.reload()
                    raise SystemExit('Cerrar huecos crearía una región vacía, un hueco nuevo o un solapamiento. Revisa las operaciones pendientes.')
            if payload.get('_dry'):
                raise _DryOK()
            progress.step(60, 'Escribiendo regions.bin, regions.nts y borders.brd')
            mhmap.save_map(m, self.xml)
            self._geom_cache = {}
            self._pending_snapshot = False
            # the map is already written: from here nothing may leave the save half done (changelog first; the rest, with a warning)
            report['new_regions'] = [{k: v for k, v in c.items() if k != 'mother_index'} for c in created]
            self.log_change(report, new_pairs, centers, R, payload)
            # land regions created or changed by the user in this save (by name: indices change if one is deleted)
            mine = [c['name'] for c in created if not c.get('sea')] + [R[r].name for r in list(new_polys) + [
                int(a['region']) for a in payload.get('assigns') or [] if a.get('kind', 'assign') in ('assign', 'stroke') and a.get('region') is not None]
                if r < len(R) and R[r].u_type != SEA]

            def later(label, f):
                try:
                    return f()
                except Exception as e:
                    report.setdefault('warnings', []).append('%s: %s' % (label, e))
            later('no se pudo vaciar «Rehacer»', lambda: shutil.rmtree(self._redo_dir()) if os.path.isdir(self._redo_dir()) else None)
            if payload.get('paint', True) and (changes['erase'] or changes['paint']):
                progress.step(65, 'Pintando el terreno')
                tiles = later('no se pudo pintar el fondo (usa «Redibujar fronteras»)', lambda: paint_tiles(
                    changes, os.path.join(self.map_dir, 'art', 'OperationalTerrain'), self.tiles, originals=self.tiles, log=log))
                report['tiles'] = ['%02d-%02d' % t for t in tiles or []]
            later('no se pudo escribir ultimo_cambio.json', lambda: json.dump(changes, open(os.path.join(self.dir, 'ultimo_cambio.json'), 'w')))
            progress.step(70, 'Comprobando el mapa')
            self.reload()
            # new islands: their land and coast in the background (otherwise the game shows only sea)
            isl = [c['name'] for c in created if not c.get('sea') and self.is_island(c['name'])]
            if isl and payload.get('paint', True):
                try:
                    report['islands_painted'] = self.paint_islands(isl, log=log)
                except Exception as e:      # the background must not prevent saving the map
                    report.setdefault('warnings', []).append('no se pudo pintar en el fondo %s: %s' % (', '.join(isl), e))
            report['map_xml'] = later('no se copiaron los vínculos de map.xml', lambda: self.inherit_links(created)) or []
            report['new_pairs'] = [[R[a].name, R[b].name] for a, b in new_pairs]
            if report.get('deleted'):
                later('no se terminaron de quitar las regiones borradas', lambda: self._finish_deletions(report['deleted'], log))
            report['check'] = later('no se pudo comprobar el mapa', self.check)
            if mine and not any(a.get('repair_gap') for a in payload.get('assigns') or []):      # (cerrar huecos no vuelve a preguntar)
                progress.step(72, 'Buscando huecos con las vecinas')
                report['gaps_left'] = later('no se pudieron buscar huecos con las vecinas', lambda: self.gaps_left(mine))
                report['near_pairs'] = later('no se pudieron buscar regiones separadas por un hueco', lambda: self.near_unlinked(mine)) or []
            report['seconds'] = round(time.time() - t0, 1)
            return report

    def gaps_left(self, names):
        """Small gaps left between the regions 'names' (newly created or changed) and their neighbours: in the game they are background
        dots and half-drawn borders (Iraq–Iran in WorldModern, Benin). {indices, names, count, area} for the page to offer closing them."""
        idx = {g.name: g.index for g in self.m['regions']}
        ids = [idx[nm] for nm in dict.fromkeys(names) if nm in idx]
        gaps = self.gaps_around(ids)
        hit = sorted({x['into'] for x in gaps})
        return {'indices': ids, 'names': [self.rname(i) for i in hit], 'count': len(gaps), 'area': round(sum(x['area'] for x in gaps), 8)} if gaps else None

    def gaps_around(self, indices):
        """Small gaps between each region of 'indices' and another region (not open notches), without repeating those shared by two of them."""
        # by groups of nearby regions (one pass per group: one at a time, 20 new regions took a minute and a half)
        groups = []
        for r in indices:
            b = self.bbox[r] if r < len(self.bbox) else None
            if not b:
                continue
            for g in groups:
                if not (b[2] < g[0][0] - 1 or b[0] > g[0][2] + 1 or b[3] < g[0][1] - 1 or b[1] > g[0][3] + 1):
                    g[0] = (min(b[0], g[0][0]), min(b[1], g[0][1]), max(b[2], g[0][2]), max(b[3], g[0][3]))
                    g[1].add(r)
                    break
            else:
                groups.append([b, {r}])
        out, seen = [], []
        for _b, members in groups:
            for x in self.small_gaps(0.05, 0.1, among=members):
                g = shape(x['polygon'])
                if x['n_touch'] >= 2 and not any(g.intersects(s) and g.intersection(s).area > 1e-12 for s in seen):
                    seen.append(g)
                    out.append(x)
        return out

    def cut_preview(self, polygon, sea=False):
        """Regions the new region would come from: [{name, taken, total, pct}] (largest first)."""
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

    SNAP = 1e-3     # grados (~100 m)

    def _snap(self, poly, owners, P, r=None):
        """Fits a new or edited polygon to the neighbouring borders: slivers WITHOUT region narrower than ~2·SNAP between
        it and a neighbour go to it, and new overlaps thinner than SNAP stay with the neighbour. Otherwise, a GeoJSON that did not
        fit left background dots along the border (Iraq–Iran in WorldModern). Returns (polygon, slivers)."""
        t = self.SNAP
        win = poly.buffer(4 * t, join_style=2)
        near = [s for s in owners(win) if s != r]
        if not near:
            return poly, []
        U = unary_union([P(s).intersection(win) for s in near])
        both = unary_union([poly, U, P(r) if r is not None else Polygon()])
        closed = both.buffer(t, join_style=2).buffer(-t, join_style=2).intersection(poly.buffer(2 * t, join_style=2))
        slits = [q for q in polys_of(closed.difference(both)) if q.distance(poly) < 1e-9 and q.distance(U) < 1e-9]
        new = poly.difference(P(r)) if r is not None else poly
        thin = [q for q in polys_of(new.intersection(U)) if q.buffer(-t / 2, join_style=2).is_empty]
        out = poly
        if thin:
            out = out.difference(unary_union(thin))
        if slits:
            out = out.union(unary_union(slits))
        return (make_valid(out) if thin or slits else poly), slits

    def _plan_new_region(self, asg, created, add, owners, P, report):
        """Creates the new region (empty) and plans the transfers that give it its area.
        asg: {polygon, name, from (mother region: subdivide) or None (drawn over the sea), owner, u_type, fill}"""
        R = self.m['regions']
        text = ' '.join((asg.get('name') or '').split())
        name = new_region.internal_name(text)   # internal name in ASCII (like all those of the map); the text goes to the SID
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
        # what another new region of this same save already took is not given twice (several regions drawn slightly overlapping
        # before saving were left with overlapping meshes): the first one keeps it
        if not self._claimed.is_empty:
            poly = make_valid(poly.difference(self._claimed))
            if poly.area <= MIN_AREA:
                report['errors'].append('%s: otra región nueva de este mismo guardado ya ocupa todo su polígono (están dibujadas una encima de otra)' % name)
                return
        self._claimed = unary_union([self._claimed, poly])
        slits = []
        if not asg.get('sea'):
            poly, slits = self._snap(poly, owners, P)
        mother = asg.get('from')
        mother = int(mother) if mother is not None else None
        pieces = []
        mothers_area = {}
        if asg.get('sea'):
            # new SEA region: cut from the sea regions it touches (the mother is the one with most area); with 'take_all'
            # (cut tool) also from land ones; gaps become sea (as long as there is nothing else
            # underneath, or with «rellenar huecos»); a sea left entirely inside the polygon is absorbed and deleted
            under = owners(poly)
            take = {int(x) for x in asg.get('take_from') or []}
            water = [(poly.intersection(P(s)), s) for s in under if s in take or R[s].u_type == SEA]
            water = drop_slivers([(p, s) for p, s in water if p.area > MIN_AREA])
            if asg.get('fill') or not water:      # gaps (e.g. a river cut before the land, or an empty map) become sea
                rest = poly.difference(unary_union([P(s) for s in under] or [Polygon()]))
                water += [(p, None) for p in polys_of(rest)]
            if not water:
                report['errors'].append('%s: el polígono no cubre mar ni huecos' % name)
                return
            for p, s in water:
                if s is not None and p.area >= P(s).area * 0.999:
                    if R[s].u_type != SEA:
                        report['errors'].append('%s: el polígono cubre toda %s (bórrala o renómbrala en vez de recortarla)' % (name, R[s].name))
                        return
                    report.setdefault('deleted', []).append({'index': s, 'name': self.rname(s), 'raw': R[s].name, 'into': name, 'sea': True})
            pieces = water
            sea_w = [w for w in water if w[1] is not None and R[w[1]].u_type == SEA]
            mothers_area = {self.rname(s): round(p.area, 6) for p, s in sea_w}
            mother = max(sea_w, key=lambda x: x[0].area)[1] if sea_w else None
            u_type = SEA
        elif asg.get('cut_all'):
            # Draw/Cut (like Pax Historia): cut from all the land regions it touches;
            # the mother is the one contributing most area (it inherits owner, terrain and culture in the scenarios from it)
            land = [(poly.intersection(P(s)), s) for s in owners(poly) if R[s].u_type != SEA]
            land = drop_slivers([(p, s) for p, s in land if p.area > MIN_AREA])
            # the part falling in the SEA also goes to the new region (before only land was taken), unless asked otherwise
            water = [] if asg.get('same_type_only') else [(poly.intersection(P(s)), s) for s in owners(poly) if R[s].u_type == SEA]
            water = [(p, s) for p, s in water if p.area > 1e-8 and p.area < P(s).area * 0.999]
            if land:
                for p, s in land:
                    if p.area >= P(s).area * 0.999 and s not in self._deleting:
                        report['errors'].append('%s: el polígono cubre toda %s (bórrala o renómbrala en vez de recortarla)' % (name, R[s].name))
                        return
                pieces = land + water
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
            if part.area >= P(mother).area * 0.999 and mother not in self._deleting:
                report['errors'].append('%s: el polígono cubre toda %s (para cambiarle el nombre usa RegionRename de map.xml)' % (name, R[mother].name))
                return
            pieces.append((part, mother))
            u_type = int(asg.get('u_type') or R[mother].u_type)
        else:
            under = owners(poly)
            for s in under:
                if R[s].u_type == SEA and not asg.get('same_type_only'):     # new land over the sea: takes the sea from it (unless not allowed)
                    pieces.append((poly.intersection(P(s)), s))
            u_type = int(asg.get('u_type') or 1)
            if asg.get('fill') or not any(p.area > MIN_AREA for p, _ in pieces):     # over gaps (e.g. an empty map) too
                rest = poly.difference(unary_union([P(s) for s in under] or [Polygon()]))
                if rest.area > MIN_AREA:
                    pieces.append((rest, None))
            if not any(p.area > MIN_AREA for p, _ in pieces) and asg.get('same_type_only'):
                # island (only sea underneath) with «solo regiones de su tipo»: has nowhere else to come from; takes the sea
                pieces = [(poly.intersection(P(s)), s) for s in under if R[s].u_type == SEA]
            if not any(p.area > MIN_AREA for p, _ in pieces):
                report['errors'].append('%s: el polígono no cubre mar ni huecos' % name)
                return
            for p, s in pieces:         # a sea left entirely inside the new region is absorbed and deleted
                if s is not None and p.area >= P(s).area * 0.999:
                    report.setdefault('deleted', []).append({'index': s, 'name': self.rname(s), 'raw': R[s].name, 'into': name, 'sea': True})
        if u_type == SEA and not asg.get('sea'):
            u_type = 1
        if not asg.get('sea') and not 1 <= u_type <= 4:
            report['errors'].append('%s: tipo de terreno %s no válido (1..4)' % (name, u_type))
            return
        if slits and not asg.get('fill'):       # with «rellenar huecos» they are already in the pieces
            pieces += [(q, None) for q in slits]
        expected = sum(p.area for p, _ in pieces)
        idx = new_region.create_region(self.m, name, u_type)
        # mother with the scenarios' name (RegionRename of map.xml): with the regions.bin one it was not found when registering it
        created.append({'index': idx, 'name': name, 'text': text, 'mother': self.rname(mother) if mother is not None else None,
                        'mother_index': mother, 'owner': asg.get('owner'), 'controller': asg.get('controller'), 'u_type': u_type,
                        'terrain': asg.get('terrain'), 'sea': bool(asg.get('sea')),
                        'pop_fractions': asg.get('pop_fractions'), 'expected_area': round(expected, 6),
                        'historic': asg.get('historic'), 'population': asg.get('population'), 'city': asg.get('city'),
                        'nation': asg.get('nation'), 'equivalent': asg.get('equivalent'), 'mothers': mothers_area})
        got = Polygon()     # pieces without overlapping each other (a river or sea passing under the land gave the same piece twice
        for p, s in pieces:  # and the new mesh came out with duplicated triangles: «tendría un contorno inválido»)
            dup = p.intersection(got) if not got.is_empty else Polygon()
            if dup.area > MIN_AREA:
                if s is not None:
                    add(dup, s, None)
                p = p.difference(got)
            add(p, s, idx)
            got = unary_union([got] + polys_of(p))

    def split_by_proximity(self, r):
        """Splits region r (e.g. a river, lake or narrow sea to be deleted) among its LAND neighbours by
        proximity: each point goes to the nearest neighbour (Voronoi diagram with points of their borders). [{polygon, into, into_name}]"""
        with self.lock:
            R = self.m['regions']
            geo = self.region_geom(self.rname(r))
            if geo is None or geo.is_empty:
                return []
            return self._split_near(geo, [n for n in set(R[r].neighbors) if n != r and R[n].u_type != SEA])

    def split_gap_by_proximity(self, polygon, neighbors):
        """Same as split_by_proximity for a gap without region (e.g. a deleted river): among the regions surrounding it."""
        with self.lock:
            return self._split_near(make_valid(shape(polygon)), [int(n) for n in neighbors])

    def _split_near(self, geo, nbrs):
        from shapely.geometry import MultiPoint, mapping as _mp
        from shapely.ops import voronoi_diagram
        near = geo.buffer(0.3)
        pts, owner = [], []
        for n in nbrs:
            g = self.region_geom(self.rname(n))
            if g is None:
                continue
            edge = g.boundary.intersection(near)
            if edge.is_empty:
                continue
            for seg in getattr(edge, 'geoms', [edge]):
                if not hasattr(seg, 'interpolate') or seg.length <= 0:
                    continue
                k = max(2, min(200, int(seg.length / 0.02)))
                for i in range(k + 1):
                    pts.append(seg.interpolate(seg.length * i / k)); owner.append(n)
        if not pts:
            return []
        env = geo.envelope.buffer(1)
        try:
            cells = voronoi_diagram(MultiPoint(pts), envelope=env)
        except GEOSException:
            # almost coincident points (two neighbours sharing a border): GEOS fails with «side location conflict»; retry on a
            # 1e-6° grid and, if that fails too, the whole gap goes to the neighbour with the most border next to it
            from shapely.geometry import Point
            grid = {}
            for q, o in zip(pts, owner):
                grid.setdefault((round(q.x, 6), round(q.y, 6)), o)
            pts, owner = [Point(k) for k in grid], list(grid.values())
            try:
                cells = voronoi_diagram(MultiPoint(pts), envelope=env)
            except GEOSException:
                best = max(set(owner), key=owner.count)
                return [{'polygon': _mp(geo.buffer(1e-7)), 'into': best, 'into_name': self.rname(best), 'area': round(geo.area, 6)}]
        from shapely.strtree import STRtree
        tree = STRtree(pts)
        by = {}
        for c in getattr(cells, 'geoms', [cells]):
            hit = [int(j) for j in tree.query(c) if c.covers(pts[int(j)])]
            if not hit:
                continue
            part = c.intersection(geo)
            if not part.is_empty:
                by.setdefault(owner[hit[0]], []).append(part)
        out = []
        for n, parts in by.items():
            u = unary_union(parts)
            if u.area > MIN_AREA:
                out.append({'polygon': _mp(u.buffer(1e-7)), 'into': n, 'into_name': self.rname(n), 'area': round(u.area, 6)})
        return out

    def preview_gap_repair(self, gaps):
        """Plan selected gap assignments without changing meshes or files."""
        if not gaps:
            return None
        with self.lock:
            patch = unary_union([shape(gap['polygon']) for gap in gaps])
            bounds = patch.bounds
            ids = {int(gap['into']) for gap in gaps}
            ids.update(i for i, b in enumerate(self.bbox) if b and not
                       (b[2] < bounds[0] or b[0] > bounds[2] or b[3] < bounds[1] or b[1] > bounds[3]))
            before = {i: self.region_geom(self.rname(i)) for i in ids}
            after = dict(before)
            for gap in gaps:
                piece, target = shape(gap['polygon']), int(gap['into'])
                for i in ids:
                    if i != target and after[i].intersects(piece):
                        after[i] = after[i].difference(piece)
                after[target] = after[target].union(piece)
            audit = geometry_audit(before, after, visual=True)
            audit['names'] = {str(i): self.rname(i) for i in ids}
            return audit

    def small_gaps(self, max_area=0.05, eps=0.03, pair=None, region=None, max_width=None, among=None):
        """Small gaps (without region) between regions: closed holes and narrow slivers under max_area degrees².
        Each with the region (land if any) it shares most border with. pair=(a, b): only those touching both."""
        from shapely.geometry import mapping as _mp, Polygon as _Poly
        with self.lock:
            R = self.m['regions']
            idx = [g.index for g in R]
            among = {i for i in among or () if i < len(R) and self.bbox[i]}
            if among:                            # around several regions at once (those of a save): a single pass
                bs = [self.bbox[i] for i in among]
                wb = (min(b[0] for b in bs) - eps * 4, min(b[1] for b in bs) - eps * 4, max(b[2] for b in bs) + eps * 4, max(b[3] for b in bs) + eps * 4)
                idx = [i for i in idx if self.bbox[i] and not (self.bbox[i][2] < wb[0] or self.bbox[i][0] > wb[2]
                                                               or self.bbox[i][3] < wb[1] or self.bbox[i][1] > wb[3])]
            if region is not None and not pair:
                pair = (region, region)          # only around this region (with any neighbour, also the sea it almost touches)
            if pair:
                a, b = pair
                win = (self.region_geom(self.rname(a)).union(self.region_geom(self.rname(b)))).envelope.buffer(eps * 4)
                wb = win.bounds
                idx = [i for i in idx if self.bbox[i] and not (self.bbox[i][2] < wb[0] or self.bbox[i][0] > wb[2]
                                                               or self.bbox[i][3] < wb[1] or self.bbox[i][1] > wb[3])]
            geos = {i: self.region_geom(self.rname(i)) for i in idx}
            geos = {i: g for i, g in geos.items() if g is not None and not g.is_empty}
            u = unary_union(list(geos.values()))
            holes = []
            for part in getattr(u, 'geoms', [u]):
                if part.geom_type == 'Polygon':
                    holes += [_Poly(h).difference(u) for h in part.interiors]     # without what is inside (a region entirely surrounded by the sliver)
            slits = u.buffer(eps, join_style=2).buffer(-eps, join_style=2).difference(u)
            # also SEA slivers between two land regions (e.g. a filler sea sneaking between imported provinces
            # that didn't fit): they are given to the land so they become contiguous
            land_u = unary_union([g for i, g in geos.items() if R[i].u_type != SEA] or [_Poly()])
            sea_slits = land_u.buffer(eps, join_style=2).buffer(-eps, join_style=2).difference(land_u) if not land_u.is_empty else _Poly()
            gaps = unary_union(holes + ([slits] if not slits.is_empty else []) + ([sea_slits] if not sea_slits.is_empty else []))
            from shapely.strtree import STRtree
            keys = list(geos)
            tree = STRtree([geos[i] for i in keys])
            out = []
            meshes = {}
            for gp in getattr(gaps, 'geoms', [gaps]):
                if gp.geom_type != 'Polygon' or gp.area <= MIN_AREA or gp.area > max_area:
                    continue
                if max_width and 2 * gp.area / max(gp.length, 1e-12) >= max_width:     # mean width: only slivers
                    continue
                ring = gp.buffer(1e-5)
                touch = []
                for j in tree.query(ring):
                    i = keys[int(j)]
                    a_ = geos[i].intersection(ring).area
                    if a_ > 0:
                        touch.append((i, a_, R[i].u_type == SEA))
                if not touch:
                    continue
                if pair and not ({pair[0], pair[1]} <= {t[0] for t in touch}):
                    continue
                if among and not among & {t[0] for t in touch}:
                    continue
                # real gap: no mesh underneath. The traced outline is not exactly the mesh, and what is only missing in the outline
                # (or crumbs under ~100 m²) is not visible in the game nor can be «closed»: it was listed forever
                for i, _a, _s in touch:
                    if i not in meshes:
                        meshes[i] = new_region.mesh_polygon(self.m, i)
                if gp.difference(unary_union([meshes[i] for i, _a, _s in touch if meshes[i] is not None])).area < 1e-8:
                    continue
                landt = [t for t in touch if not t[2]]
                best = max(landt or touch, key=lambda t: t[1])
                # with 'region': for it, except slivers between TWO OTHER regions that only graze it with the tip (giving them left it a
                # metres-wide thread along a foreign border and the sliver remained): those go to whoever shares most border
                own = max([t for t in touch if t[0] == region or t[0] in among] or [(None, 0)], key=lambda t: t[1])
                best = own[0] if own[1] >= 0.25 * best[1] and own[1] > 0 else best[0]
                out.append({'polygon': _mp(gp), 'into': best, 'into_name': self.rname(best), 'area': round(gp.area, 8),
                            'land': [t[0] for t in sorted(landt, key=lambda t: -t[1])], 'n_touch': len(touch)})
            return out

    def validate(self):
        """Everything that would prevent saving or cause problems, at once: broken meshes, empty regions, repeated names,
        seas with wrong u_flag, new regions without owner or mother. [{level, region, msg}]"""
        out = []
        with self.lock:
            R = self.m['regions']
            seen = {}
            for g in R:
                n = self.rname(g.index)
                seen.setdefault(n.lower(), []).append(n)
                tris = [t for x in mhmap.region_shapes(self.m, g.index) for t in x.triangles() if len(set(t)) == 3]
                if not tris:
                    out.append({'level': 'error', 'region': n, 'msg': 'región sin área (malla vacía)'})
                    continue
                main, detail, ok, why = self.outline(g.index)
                if not ok and not self._mesh_ok(self.m, g.index):
                    out.append({'level': 'error', 'region': n, 'msg': 'malla rota (triángulos solapados o contorno inválido: %s)' % why})
                if g.u_type == SEA and g.u_flag != 1:
                    out.append({'level': 'error', 'region': n, 'msg': 'región de mar con u_flag %s (debe ser 1: sale roja en el juego)' % g.u_flag})
            for k, v in seen.items():
                if len(v) > 1:
                    out.append({'level': 'error', 'region': v[0], 'msg': 'nombre repetido %d veces' % len(v)})
        # slivers without region between two land regions (a GeoJSON that did not fit): in the game, background dots on the border
        pairs = {}
        for x in self.small_gaps(max_area=0.05, eps=self.SNAP, max_width=self.SNAP):
            g = shape(x['polygon'])
            if len(x['land']) >= 2:
                k = tuple(sorted(x['land'][:2]))
                pairs[k] = (pairs.get(k, (0, 0))[0] + 1, pairs.get(k, (0, 0))[1] + g.area)
        for (a, b), (n, ar) in sorted(pairs.items(), key=lambda kv: -kv[1][1]):
            out.append({'level': 'aviso', 'region': self.rname(a), 'fix': {'gaps_pair': [a, b]},
                        'msg': '%d rendija(s) sin región en la frontera con %s (%.6f grados²): en el juego se ven como puntos del fondo' % (n, self.rname(b), ar)})
        for x in self.new_regions_info():
            if x.get('ownerless'):
                out.append({'level': 'aviso', 'region': x['name'], 'msg': 'región nueva sin dueño ni región de origen: al adecuar un escenario hay que elegirle país'})
        return out

    def crumbs(self, r, max_deg2=0.05, max_ratio=0.02):
        """Loose pieces of region r (tiny exclaves, two-node strips, leftovers of imperfect geometry): all its parts
        except the main one measuring under max_deg2 degrees² or max_ratio of the region. For each, the neighbour (of any
        type) it shares most border with: [{polygon, area, into, into_name}]."""
        from shapely.geometry import mapping as _mp
        with self.lock:
            geo = new_region.mesh_polygon(self.m, r)
            parts = sorted(polys_of(geo), key=lambda q: -q.area)
            if len(parts) < 2:
                return []
            total = sum(q.area for q in parts)
            out = []
            for q in parts[1:]:
                if q.area > max_deg2 and q.area > max_ratio * total:
                    continue
                ring = q.buffer(1e-6)
                best, bl = None, 0.0
                b0 = q.bounds
                for g in self.m['regions']:
                    if g.index == r:
                        continue
                    bb = self.bbox[g.index] if g.index < len(self.bbox) else None
                    if bb and (bb[2] < b0[0] - 1e-3 or bb[0] > b0[2] + 1e-3 or bb[3] < b0[1] - 1e-3 or bb[1] > b0[3] + 1e-3):
                        continue
                    hg = self.region_geom(self.rname(g.index))
                    if hg is None:
                        continue
                    n = hg.intersection(ring).area
                    if n > bl:
                        best, bl = g.index, n
                out.append({'polygon': _mp(q.buffer(1e-7)), 'area': round(q.area, 9), 'into': best,
                            'into_name': self.rname(best) if best is not None else None})
            return out

    def gap_at(self, x, y, half=4.0):
        """Gap (area without region) containing the point: {polygon, area, neighbors:[{index, name, sea, shared}]}. Used to
        select the gap and join it to a region or create a new region there. If it is not closed (empty map) returns an error."""
        from shapely.geometry import Point, box
        with self.lock:
            win = box(x - half, y - half, x + half, y + half)
            geos = []
            for g in self.m['regions']:
                b = self.bbox[g.index] if g.index < len(self.bbox) else None
                if b and (b[2] < win.bounds[0] or b[0] > win.bounds[2] or b[3] < win.bounds[1] or b[1] > win.bounds[3]):
                    continue
                geo = self.region_geom(self.rname(g.index))
                if geo is not None and not geo.is_empty:
                    geos.append((g, geo))
            empty = win.difference(unary_union([geo for _, geo in geos]) if geos else Polygon())
            pt = Point(x, y)
            hole = [p for p in polys_of(empty) if p.buffer(1e-9).contains(pt)]
            if not hole:
                return {'error': 'no hay ningún hueco en este punto'}
            h = hole[0]
            opened = h.exterior.intersects(win.exterior)      # not closed (continues outside the window): only the part inside the window is selected
            nb = []
            ring = h.buffer(1e-6)
            for g, geo in geos:
                sh = geo.intersection(ring).area
                if sh > 0:
                    nb.append({'index': g.index, 'name': self.rname(g.index), 'sea': g.u_type == SEA, 'shared': round(sh, 10)})
            return {'polygon': mapping(h), 'open': bool(opened), 'area': round(h.area, 6), 'neighbors': sorted(nb, key=lambda n: -n['shared'])}

    def region_geom(self, name):
        """Polygon of a region's mesh by its name in the scenarios."""
        gc = getattr(self, '_geom_cache', None)
        if gc is not None and name in gc:
            return gc[name]
        inv = {v: k for k, v in self.renames.items()}
        nm = inv.get(name, name)
        for g in self.m['regions']:
            if g.name == nm:
                poly = new_region.mesh_polygon(self.m, g.index)
                if gc is not None:
                    gc[name] = poly       # emptied in reload(); the map changes only on save or undo (which reload)
                return poly
        return None

    # ------------------------------------------------------------------ islas en el fondo
    ISLAND_MAX_AREA = 0.3     # degrees²: a larger polygon is a sea halo around the island, not the island

    def is_island(self, name):
        """Land region without land neighbours."""
        inv = {v: k for k, v in self.renames.items()}
        g = next((x for x in self.m['regions'] if x.name == inv.get(name, name)), None)
        R = self.m['regions']
        return g is not None and g.u_type != SEA and not any(R[n].u_type != SEA for n in g.neighbors if n != g.index)

    def _painted_land(self, geom):
        """Land already visible in the background inside 'geom' (non-blue pixels), as a polygon; None if there is none."""
        from shapely.geometry import box as _box
        ppd = SIZE / 15.0
        x0, y0, x1, y1 = geom.bounds
        cells = []
        for c in range(int((x0 + 180) // 15), int((x1 + 180) // 15) + 1):
            for r in range(int((105 - y1) // 15), int((105 - y0) // 15) + 1):
                if not (0 <= c < 24 and 0 <= r < 13):
                    continue
                im = decode(open(self.tile_path(tile_name(c, r)), 'rb').read(), SIZE).convert('RGB')
                lon0, lat0 = -180 + c * 15, 105 - r * 15
                px0, px1 = max(0, int((x0 - lon0) * ppd)), min(SIZE, int((x1 - lon0) * ppd) + 1)
                py0, py1 = max(0, int((lat0 - y1) * ppd)), min(SIZE, int((lat0 - y0) * ppd) + 1)
                pix = im.load()
                for py in range(py0, py1):
                    for px in range(px0, px1):
                        p = pix[px, py]
                        if p[0] + p[1] > p[2] * 1.2 and p[0] + p[1] > 60:
                            cells.append(_box(lon0 + px / ppd, lat0 - (py + 1) / ppd, lon0 + (px + 1) / ppd, lat0 - py / ppd))
        land = unary_union(cells).intersection(geom) if cells else None
        return land if land is not None and not land.is_empty else None

    def paint_islands(self, names, land=None, log=print):
        """Paints in the background (project tiles/; reaches the game on «Instalar») the islands 'names': sand with a light water halo, without
        coastline (the region line comes from its polygon), like Cape Verde in the game. The land shape: 'land' ({region: geometry}, e.g. from a GeoJSON);
        otherwise, the region polygon if small (it is the island); otherwise, skipped.
        Returns {'painted': {region: how}, 'skipped': {region: why}, 'tiles': [...]}."""
        land = land or {}
        ch = {'erase': [], 'paint': [], 'islands': []}
        done, skipped = {}, {}
        with self.lock:
            for n in names:
                g = self.region_geom(n)
                if g is None:
                    skipped[n] = 'no existe en el mapa'; continue
                shp = land.get(n)
                how = 'forma dada'
                if shp is None and g.area <= self.ISLAND_MAX_AREA:
                    shp, how = g, 'su polígono'
                if shp is None:
                    skipped[n] = 'su polígono es grande (%.2f grados²): da la forma de la isla con un GeoJSON o dibujando su contorno' % g.area
                    continue
                # only the land: never a line stuck to the coast (like the game's Cape Verde or Canaries, the region
                # line is that of its polygon, in borders.brd)
                ch['islands'].append(mapping(shp))
                done[n] = how
            tiles = paint_tiles(ch, os.path.join(self.map_dir, 'art', 'OperationalTerrain'), self.tiles, originals=self.tiles, log=log) if done else []
        ol = self.outline_islands(list(done), log=log)      # the region line, by its polygon
        tiles = sorted(set('%02d-%02d' % t for t in tiles) | set(ol['tiles']))
        return {'painted': done, 'skipped': skipped, 'tiles': tiles}

    def outline_islands(self, names, log=print):
        """Islands like the game's Cape Verde or Canaries: the dark outline stuck to the coast is removed from the background and the region
        line is painted by its polygon (borders.brd). In the project's tiles/; to the game with «Instalar»."""
        ch = {'erase': [], 'paint': [], 'islands': [], 'unring': []}
        done = []
        with self.lock:
            for n in names:
                g = self.region_geom(n)
                if g is None:
                    continue
                ch['unring'].append(mapping(g))
                for poly in getattr(g, 'geoms', [g]):
                    ch['paint'].append(dict(mapping(poly.exterior), kind='sea'))
                done.append(n)
            tiles = paint_tiles(ch, os.path.join(self.map_dir, 'art', 'OperationalTerrain'), self.tiles, originals=self.tiles, log=log) if done else []
        return {'outlined': done, 'tiles': ['%02d-%02d' % t for t in tiles]}

    def redraw_borders(self, region=None, log=print):
        """«Redibujar fronteras»: repaints in the background (project tiles/) the lines of all borders according to
        borders.brd: land-land, sea-sea and the polygon of islands (not their coast). Can be undone with «Volver»."""
        ch = {'erase': [], 'paint': [], 'islands': []}
        with self.lock:
            R = self.m['regions']
            if region is not None and not 0 <= region < len(R):
                raise ValueError('la región %s ya no existe (recarga el mapa)' % region)
            for b in self.m['borders']:
                if region is not None and region not in b.regions:     # only the chosen region and its borders with the neighbours
                    continue
                if len(b.regions) != 2:          # border without a row in the neighbour table: its type is unknown
                    continue
                a, c = (R[i].u_type == SEA for i in b.regions)
                if a != c:        # coast: only that of islands (their polygon, like Cape Verde); that of continents is already in the background
                    land = next(R[i] for i in b.regions if R[i].u_type != SEA)
                    if not self.is_island(self.rname(land.index)):
                        continue
                    a = True
                for f, p in b.segments:
                    if len(p) > 1:
                        ch['paint'].append({'type': 'LineString', 'coordinates': [list(q) for q in p], 'kind': 'sea' if a else 'land'})
            if region is not None and R[region].u_type != SEA and self.is_island(self.rname(region)):
                g = self.region_geom(self.rname(region))
                if g is not None and not g.is_empty:
                    ch['unring'] = [mapping(g)]      # island: no outline stuck to the coast
            self.snapshot(log)       # can be undone with «Volver» (no separate copies of the tiles)
            tiles = paint_tiles(ch, os.path.join(self.map_dir, 'art', 'OperationalTerrain'), self.tiles, originals=self.tiles, log=log)
        return {'tiles': ['%02d-%02d' % t for t in tiles], 'lines': len(ch['paint'])}

    def install_tiles(self, tiles):
        """Copies to the game only those background tiles (and their mipmaps) from the project's tiles/: a background change without touching the map."""
        dst = os.path.join(self.map_dir, 'art', 'OperationalTerrain')
        out = []
        for t in tiles:
            c, r = (int(x) for x in t.split('-'))
            for lv in range(5):
                f = tile_name(c, r, lv)
                if os.path.exists(os.path.join(self.tiles, f)):
                    shutil.copy2(os.path.join(self.tiles, f), os.path.join(dst, f))
                    out.append(f)
        return out

    def check(self):
        """Format rules over the project's whole map."""
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
                                       'terrain': prop(head, 'strTerrain'), 'culture': prop(head, 'strCulture'), 'population': int(pop) if pop and pop.isdigit() else None,
                                       'sid': prop(head, 'sidName')}
        # name shown in the game (scenario stringTable) to show on hover if it differs from the internal one
        st_path = os.path.join(d, 'game', 'stringTable.xml')
        if os.path.exists(st_path):
            texts = dict(re.findall(r'<string id="([^"]+)" value="([^"]*)"', open(st_path, encoding='utf-8', errors='replace').read()))
            for v in regions.values():
                if v.get('sid') in texts:
                    v['text'] = texts[v['sid']]
        colors = {}
        gs = open(os.path.join(d, 'gamestate.xml'), encoding='utf-8', errors='replace').read()
        for blk in re.split(r'<object type="Player"', gs)[1:]:
            head = blk.split('</object>')[0]
            nm, col = prop(head, 'strName'), prop(head, 'colCountryColor')
            if nm and col:
                colors[nm] = '#' + col.lstrip('#')[:6]
        return {'regions': regions, 'colors': colors}

    # ------------------------------------------------------------------ historial
    @staticmethod
    def _mesh_ok(m, r):
        """r's mesh is sound even if its traced outline is not: the union of its triangles is valid and they don't overlap
        (the sum of their areas equals that of the union). Ring tracing fails with vertices where the border touches itself
        («pinches»), which the game accepts; before, that blocked the save (e.g. adding area to Abkhazia)."""
        try:
            tris = [Polygon(t) for x in mhmap.region_shapes(m, r) for t in x.triangles() if len(set(t)) == 3]
            tris = [t for t in tris if t.area > 0]
            if not tris:
                return False
            u = unary_union(tris)
            tot = sum(t.area for t in tris)
            return u.is_valid and abs(u.area - tot) <= 1e-4 * tot + 1e-9      # tiny rounding overlaps (e.g. 7e-5 degrees² in Turov, of 9.2) are not a broken mesh
        except Exception:
            return False

    @staticmethod
    def _tri_area(m, r):
        """Sum of the areas (degrees²) of the triangles of r's mesh."""
        return sum(abs((t[1][0] - t[0][0]) * (t[2][1] - t[0][1]) - (t[2][0] - t[0][0]) * (t[1][1] - t[0][1])) / 2
                   for s in mhmap.region_shapes(m, r) for t in s.triangles())

    def _mesh_valid(self, m, r):
        """The outline of region r is a valid polygon (without edges crossing the map), or at least its mesh is sound."""
        try:
            main, _ = outlines.region_polygons(m, r)
            g = shape({'type': 'MultiPolygon', 'coordinates': main}) if main else None
            if g is not None and g.is_valid and (len(mhmap.region_shapes(m, r)) != 1 or abs(g.area - self._tri_area(m, r)) <= 0.005 * max(g.area, 1e-9)):
                return True
        except Exception:
            pass
        return self._mesh_ok(m, r)

    @staticmethod
    def _broken_where(m, r):
        """' near (lon, lat)': the point where r's outline stops being valid (or '' if GEOS doesn't say)."""
        try:
            main, _ = outlines.region_polygons(m, r)
            hit = re.search(r'\[(-?[\d.e-]+) (-?[\d.e-]+)\]', explain_validity(shape({'type': 'MultiPolygon', 'coordinates': main})))
            return ' cerca de %s' % _where(float(hit.group(1)), float(hit.group(2))) if hit else ''
        except Exception:
            return ''

    def _guard(self, m, created, was_valid, report):
        """Before writing the map: no region that was valid becomes broken, and each new region has
        (almost) the area that was drawn. Otherwise, everything is discarded and the reason explained."""
        R = m['regions']
        problems = []
        gone = {d['index'] for d in report.get('deleted', [])}     # those being deleted are left empty on purpose
        for r, ok in was_valid.items():
            if ok and r < len(R) and r not in gone and not self._mesh_valid(m, r):
                problems.append('la malla de %s quedaría rota (contorno inválido)' % self.rname(r) + self._broken_where(m, r))
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
        """Copies the current project state (binaries, tiles, changelog) to folder d."""
        os.makedirs(os.path.join(d, 'xml'))
        os.makedirs(os.path.join(d, 'tiles'))
        for f in XML_FILES:
            shutil.copy2(os.path.join(self.xml, f), os.path.join(d, 'xml', f))
        # the background weighs hundreds of MB and almost never changes between two saves: a tile equal to the previous snapshot's is linked
        # to it (snapshots are never modified; the live tile is, in place, so it is never linked). Without this, each
        # «Guardar» copied the whole background and a long session filled the disk (20 GB on a tester's machine)
        snaps = sorted(x for x in os.listdir(self.history) if x.isdigit() and os.path.join(self.history, x) != d)
        prev = os.path.join(self.history, snaps[-1], 'tiles') if snaps else None
        for f in os.listdir(self.tiles):
            src, dst = os.path.join(self.tiles, f), os.path.join(d, 'tiles', f)
            try:
                a, b = os.stat(src), os.stat(os.path.join(prev, f))
                if (a.st_size, a.st_mtime_ns) == (b.st_size, b.st_mtime_ns):    # copy2 keeps the date: equal = untouched
                    os.link(os.path.join(prev, f), dst)
                    continue
            except (OSError, TypeError):      # no previous snapshot, new tile or disk without links (FAT): copied
                pass
            shutil.copy2(src, dst)
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

    def clear_history(self):
        for d in os.listdir(self.history):
            if d.isdigit() or d == 'rehacer':
                shutil.rmtree(os.path.join(self.history, d), ignore_errors=True)

    def snapshot(self, log=print, keep_redo=False):
        if not SAVE_HISTORY:          # option off: «Volver» is not available and nothing is copied (nor is the old one kept)
            self.clear_history()
            return
        n =len([d for d in os.listdir(self.history) if d.isdigit()]) + 1
        d = os.path.join(self.history, '%03d' % n)
        self._copy_state(d)
        if not keep_redo and os.path.isdir(self._redo_dir()):
            shutil.rmtree(self._redo_dir())        # a new save invalidates what could be redone
        log('instantanea %s' % d)

    def can_redo(self):
        d = self._redo_dir()
        return os.path.isdir(d) and any(x.isdigit() for x in os.listdir(d))

    def redo(self, log=print):
        """Redoes the last save undone with «Volver»."""
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
            # the current state is saved to be able to «Rehacer»
            rd = self._redo_dir()
            os.makedirs(rd, exist_ok=True)
            self._copy_state(os.path.join(rd, '%03d' % (len([x for x in os.listdir(rd) if x.isdigit()]) + 1)))
            # the changelog returns to the snapshot state (that save's entries are removed)
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

    # ------------------------------------------------------------------ regionpack changelog
    def changelog_path(self):
        return os.path.join(self.dir, 'changelog.json')

    def note_deleted_population(self, pops):
        """Records in the last save the population each deleted region had in each scenario (for exact undo)."""
        if not pops:
            return
        cl = self.changelog()
        if cl:
            for x in cl[-1].get('regiones_eliminadas', []):
                if x['nombre'] in pops:
                    x['poblacion_por_escenario'] = pops[x['nombre']]
            changelog_keys.dump(cl, self.changelog_path())

    def _finish_deletions(self, deleted, log=print):
        """Removes the already emptied regions from the map and updates the changelog: the creation of a deleted region
        disappears and the last save records what was deleted and where its area went."""
        m = self.m
        for d in sorted(deleted, key=lambda x: -x['index']):
            idx = next((g.index for g in m['regions'] if g.name == d['raw']), None)
            if idx is None:
                continue
            for sh in mhmap.region_shapes(m, idx):      # tiny leftovers that couldn't be transferred
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
        changelog_keys.dump(cl, self.changelog_path())
        self.reload()

    def changelog(self):
        p = self.changelog_path()
        return changelog_keys.load(p)

    def equivalences(self):
        """{regionpack region: [vanilla game (World) regions it equals]}: those set when creating it (regiones_nuevas.equivale)
        and those edited later (changelog «equivalencias» entry; this one prevails)."""
        out = {}
        for e in self.changelog():
            for x in e.get('regiones_nuevas', []):
                if x.get('equivale'):
                    out[x['nombre']] = list(x['equivale'])
            for k, v in (e.get('equivalencias') or {}).items():
                if v:
                    out[k] = list(v)
                else:
                    out.pop(k, None)
        return out

    def new_regions_info(self, scenario=None, have=()):
        """New land regions of the changelog: [{name, mother, owner, owner_here, ownerless}]. 'owner_here' is the
        scenario's own owner (pais_por_escenario); 'ownerless' = have no owner nor mother to inherit it from (the scenario
        would be unusable: they cannot be added). 'have' = regions the scenario already has (skipped)."""
        out = {}
        sea = {g.name for g in self.m['regions'] if g.u_type == SEA} | {self.rname(g.index) for g in self.m['regions'] if g.u_type == SEA}
        for e in self.changelog():
            for x in e.get('regiones_nuevas', []):
                if x.get('mar') or x['nombre'] in have:
                    continue
                here = (x.get('pais_por_escenario') or {}).get(scenario)
                mother = x.get('madre') if x.get('madre') not in sea else None      # a sea mother gives it no country
                out[x['nombre']] = {'name': x['nombre'], 'mother': mother, 'owner': x.get('pais'), 'owner_here': here,
                                    'ownerless': not (mother or x.get('pais') or here)}
        gone = {d['nombre'] for e in self.changelog() for d in e.get('regiones_eliminadas', [])}
        return [v for k, v in out.items() if k not in gone]

    def set_owner_for_scenario(self, region, scenario, owner):
        """Owner of a new region in a specific scenario (pais_por_escenario of the changelog; empty = remove it)."""
        cl = self.changelog()
        hit = False
        for e in cl:
            for x in e.get('regiones_nuevas', []):
                if x['nombre'] == region:
                    m = dict(x.get('pais_por_escenario') or {})
                    if owner:
                        m[scenario] = owner
                    else:
                        m.pop(scenario, None)
                    x['pais_por_escenario'] = m or None
                    hit = True
        if not hit:
            if not owner:
                return
            # map region the changelog doesn't know (e.g. imported from a GeoJSON): recorded with this scenario's owner
            if not any(self.rname(g.index) == region for g in self.m['regions']):
                raise ValueError('%s no es una región de este regionpack' % region)
            cl.append({'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': self.pack, 'instalado': False, 'operaciones': ['propietario'],
                       'regiones_nuevas': [{'nombre': region, 'texto': region, 'madre': None, 'pais': None, 'tipo': None, 'controlador': None,
                                            'terreno': None, 'mar': False, 'poblacion': None, 'historicos': None, 'pais_por_escenario': {scenario: owner}}]})
        changelog_keys.dump(cl, self.changelog_path())
        if not self.virtual and self.installed_state() == 'same':
            shutil.copy2(self.changelog_path(), os.path.join(self.map_dir, 'changelog.json'))

    def set_equivalence(self, region, names):
        """Records (or removes, with an empty list) which vanilla game regions 'region' equals; goes in the regionpack changelog."""
        names = [n.strip() for n in names if n and n.strip()]
        cl = self.changelog()
        ent = next((e for e in cl if 'equivalencias' in e), None)
        if ent is None:
            ent = {'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': self.pack, 'instalado': False, 'operaciones': ['equivalencias'],
                   'equivalencias': {}, 'regiones_nuevas': []}
            cl.append(ent)
        ent['equivalencias'][region] = names
        ent['fecha'] = time.strftime('%Y-%m-%d %H:%M:%S')
        changelog_keys.dump(cl, self.changelog_path())
        if not self.virtual and self.installed_state() == 'same':
            shutil.copy2(self.changelog_path(), os.path.join(self.map_dir, 'changelog.json'))
        return names

    def log_change(self, report, new_pairs, centers, R, payload):
        """One entry per save, by region name: used to apply the change to other scenarios."""
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
                                      'poblacion_manual': c.get('population'), 'ciudad': c.get('city'), 'nacion': c.get('nation'), 'equivale': c.get('equivalent'),
                                      'fraccion': c.get('fraccion'), 'area': c.get('area')} for c in report.get('new_regions', [])]}
        log = self.changelog()
        log.append(entry)
        changelog_keys.dump(log, self.changelog_path())

    # ------------------------------------------------------------------ regionpacks
    @staticmethod
    def packs():
        return sorted(d for d in os.listdir(MAPS) if os.path.exists(os.path.join(MAPS, d, 'xml', 'regions.bin')))

    @staticmethod
    def pack_users():
        """{regionpack: [scenarios using it]} according to strMapName of each scenario.xml."""
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
        meta = {'pack': self.pack, 'decided': self.decided}
        if self.virtual:
            meta['nuevo'] = True
        json.dump(meta, open(os.path.join(self.dir, 'pack.json'), 'w'))

    @staticmethod
    def set_scenario_pack(scenario, pack, backup_root):
        """Changes strMapName and fileMapProperties of a scenario (with a copy of the original scenario.xml)."""
        import re
        f = os.path.join(SCEN_DIR, scenario, 'scenario.xml')
        in_game = os.path.normcase(os.path.abspath(f)).startswith(os.path.normcase(os.path.abspath(GAME)) + os.sep)
        rel = os.path.relpath(f, GAME if in_game else os.path.dirname(os.path.abspath(SCEN_DIR)))   # never comes from the backup
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
        """Backup of a game regionpack under another name (geometry, textures, map.xml, changelog).
        The given 'scenarios' switch to the copy (their scenario.xml is rewritten, with backup). If
        project_src/project_dst are passed, the editor project is also copied to keep editing the copy."""
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
        """target 'same': to the project's regionpack. 'new': copies the regionpack under another name and installs there;
        the given 'scenarios' switch to the new regionpack."""
        import re
        with self.lock:
            fix = new_region.normalize_map(self.m)       # counterclockwise triangles and coasts: otherwise the game neither draws nor lets you pick regions
            if fix['triangulos'] or fix['costas']:
                mhmap.save_map(self.m, self.xml)
                print('instalar: corregidos %d triángulos en sentido horario y %d tramos de costa' % (fix['triangulos'], fix['costas']))
            dest = self.map_dir
            if self.virtual:
                # new regionpack from scratch: its folder is created in the game (an existing one is never overwritten) with the base
                # (map.xml, properties.xml, MiniMap, sea-coloured tiles) and on top the project content (map and modified tiles)
                if not self.m['regions']:
                    return {'ok': False, 'msg': 'el regionpack no tiene ninguna región: crea al menos una antes de instalarlo'}
                dest = os.path.join(MAPS, self.pack)
                if os.path.exists(dest):
                    return {'ok': False, 'msg': 'regionpack ya existente: %s' % self.pack}
                target, scenarios = 'same', ()
                shutil.copytree(self.base, dest, ignore=shutil.ignore_patterns('_mar'))
            elif target == 'new':
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
            if os.path.exists(os.path.join(self.dir, 'art', 'MiniMap.tga')):     # minimapa importado en «Imagen de fondo»
                pairs.append((os.path.join(self.dir, 'art', 'MiniMap.tga'), os.path.join(dest, 'art', 'MiniMap.tga'), os.path.join(self.backup_dir, 'MiniMap.tga')))
            pairs += [(os.path.join(self.tiles, f), os.path.join(dest, 'art', 'OperationalTerrain', f),
                       os.path.join(self.backup_dir, 'OperationalTerrain', f)) for f in os.listdir(self.tiles)]
            for src, dst, bak in pairs:
                if target == 'same' and not self.virtual and os.environ.get('MH_RESPALDOS') == '1':
                    os.makedirs(os.path.dirname(bak), exist_ok=True)
                    if not os.path.exists(bak):
                        shutil.copy2(dst, bak)   # backup of the game's original, only the first time
                shutil.copy2(src, dst)
                done.append(os.path.basename(dst))
            # the changelog travels inside the regionpack
            self.prune_changelog()
            log = self.changelog()
            for e in log:
                e['instalado'] = True
            changelog_keys.dump(log, self.changelog_path())
            changelog_keys.dump(log, os.path.join(dest, 'changelog.json'))
            switched = []
            if target == 'new':
                for s in scenarios:
                    self.set_scenario_pack(s, new_name, backup_root)
                    switched.append(s)
                # the new regionpack has its OWN project (<base>_<nuevo>) with this work; this project
                # becomes again that of the original regionpack as it is in the game (before it was «renamed» and
                # two projects were left for the same regionpack)
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
            if self.virtual:            # already exists in the game: the project becomes a normal one
                self.virtual = False
                self.map_dir = dest
                shutil.rmtree(self.base, ignore_errors=True)
            self.decided = True
            self.save_meta()
            return {'ok': True, 'files': done, 'regionpack': os.path.basename(dest), 'escenarios': switched}
