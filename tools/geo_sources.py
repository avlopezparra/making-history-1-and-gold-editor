"""Other outline sources for «Importar GeoJSON»: OpenStreetMap relations (by id) and KML / KMZ files.

Everything comes out as a FeatureCollection of MultiPolygon (valid, parts merged, no altitude), just like a hand-picked .geojson.
Nothing is written to disk: the page receives the outlines and follows the usual path.

    python geo_sources.py        -> self-test (ids, KML, in-memory KMZ); no network
    python geo_sources.py 51477  -> downloads that relation and says which source it came from
"""
import base64
import binascii
import io
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib
from urllib.parse import urlparse

from shapely import force_2d, get_num_coordinates, make_valid
from shapely.geometry import LineString, mapping, shape
from shapely.ops import polygonize, unary_union

UA = 'MHEditor/3.6 (Making History editor)'      # generic: never the user's email or keys
HOSTS = ('polygons.openstreetmap.fr', 'nominatim.openstreetmap.org', 'overpass-api.de')
MAX_NET = 80 << 20       # largest response accepted (the outline of a huge country is tens of MB)
MAX_KML = 60 << 20       # KML, or the .kml inside an already decompressed KMZ
TIMEOUT = 30


class Limited(Exception):
    pass


def _parts(g):
    """Loose polygons from any geometry (nested collections included; points and lines dropped)."""
    if hasattr(g, 'geoms'):
        return [q for p in g.geoms for q in _parts(p)]
    return [g] if g.geom_type == 'Polygon' and not g.is_empty else []


def _norm(g):
    """Shapely geometry -> valid GeoJSON MultiPolygon, without altitude and with parts merged (None if no area remains)."""
    # part by part: make_valid on a whole MultiPolygon leaves a hole where two parts overlap (shapes merged in Google Earth)
    polys = [q for p in _parts(force_2d(g)) for q in _parts(make_valid(p))]
    polys = _parts(unary_union(polys)) if polys else []
    return {'type': 'MultiPolygon', 'coordinates': [mapping(p)['coordinates'] for p in polys]} if polys else None


def _verts(geom):
    return int(get_num_coordinates(shape(geom)))


def normalize(geoms, tol=0):
    """Common step for every imported outline (GeoJSON, KML, OSM): one valid MultiPolygon per geometry (Polygon, MultiPolygon
    or GeometryCollection: the combination is a single shape), without altitude, parts merged and, with tol > 0 (degrees), fewer vertices
    preserving topology. Returns (geometries, vertices before, vertices after); None where there is no polygon."""
    out, before = [], 0
    for g in geoms:
        try:
            s = shape(g)
            before += int(get_num_coordinates(s))
            n = _norm(s.simplify(min(tol, 1.0), preserve_topology=True)) if tol and tol > 0 else None
            out.append(n or _norm(s))
        except Exception:
            out.append(None)
    return out, before, sum(_verts(g) for g in out if g)


# ------------------------------------------------------------------ OpenStreetMap
def osm_ids(text):
    """'51477', 'r51477', 'relation/51477' or the openstreetmap.org URL (several with commas or spaces) -> [51477, ...]."""
    ids = []
    for tok in re.split(r'[\s,;]+', str(text or '').strip()):
        if not tok:
            continue
        m = re.fullmatch(r'(?:(?:https?://)?(?:www\.)?openstreetmap\.org/)?(?:relation/|r)?(\d{1,12})(?:[/?#].*)?', tok, re.I)
        if not m:
            raise ValueError('«%s» no es un id de relación de OpenStreetMap (vale un número, r12345, relation/12345 o su dirección de openstreetmap.org)' % tok[:60])
        if int(m.group(1)) not in ids:
            ids.append(int(m.group(1)))
    if not ids:
        raise ValueError('escribe el id de una relación de OpenStreetMap')
    if len(ids) > 20:
        raise ValueError('demasiadas relaciones a la vez (máximo 20)')
    return ids


class _OnlyOurHosts(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urlparse(newurl)
        if u.scheme != 'https' or u.hostname not in HOSTS:
            raise urllib.error.HTTPError(newurl, code, 'redirección a otro sitio', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url, data=None):
    """Response text, or None if the site says it does not have it (400/404). Raises Limited (429/509) or OSError (no network)."""
    assert urlparse(url).scheme == 'https' and urlparse(url).hostname in HOSTS, url
    req = urllib.request.Request(url, data, {'User-Agent': UA, 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(_OnlyOurHosts).open(req, timeout=TIMEOUT) as r:
            body = r.read(MAX_NET + 1)
    except urllib.error.HTTPError as e:
        if e.code in (429, 509):
            raise Limited()
        if e.code in (400, 404):
            return None
        raise OSError('HTTP %d' % e.code)
    except socket.timeout:
        raise OSError('tardó más de %d s' % TIMEOUT)
    if len(body) > MAX_NET:
        raise OSError('respuesta demasiado grande')
    return body.decode('utf-8', 'replace')


def _json(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def _name(tags, lang):
    tags = tags or {}
    return tags.get('name:' + lang) or tags.get('name') or tags.get('name:%s' % 'en') or ''


def _from_polygons(rid):
    j = _json(_get('https://polygons.openstreetmap.fr/get_geojson.py?id=%d&params=0' % rid))
    return _norm(shape(j)) if isinstance(j, dict) and j.get('type') else None


def _nominatim(rid, polygon):
    j = _json(_get('https://nominatim.openstreetmap.org/lookup?osm_ids=R%d&format=geojson&namedetails=1&polygon_geojson=%d' % (rid, polygon)))
    if not isinstance(j, dict):
        raise OSError('respuesta no válida')
    return (j.get('features') or [{}])[0]             # {} = Nominatim answers it does not have it


def _from_overpass(rid):
    """(geometry | None, tags | None): tags None = the relation does not exist."""
    q = '[out:json][timeout:25];relation(%d);out geom;' % rid
    j = _json(_get('https://%s/api/interpreter' % HOSTS[2], ('data=' + urllib.request.quote(q)).encode()))
    if j is None:
        raise OSError('respuesta no válida')
    els = j.get('elements') or []
    if not els:
        return None, None
    tags = els[0].get('tags') or {}
    if tags.get('type') not in ('multipolygon', 'boundary'):       # a route closing a loop is not an area
        return None, tags
    lines = {True: [], False: []}
    for m in els[0].get('members') or []:
        pts = [(p['lon'], p['lat']) for p in m.get('geometry') or [] if p]
        if m.get('type') == 'way' and len(pts) >= 2:
            lines[m.get('role') == 'inner'].append(LineString(pts))
    area = lambda ls: unary_union(list(polygonize(unary_union(ls)))) if ls else None
    outer, inner = area(lines[False]), area(lines[True])
    if outer is None or outer.is_empty:
        return None, tags
    return _norm(outer.difference(inner) if inner is not None else outer), tags


def fetch_osm(text, lang='es'):
    """Outlines of the requested relations: {'features', 'errors' (one sentence per failed relation), 'sources' {id: site}}."""
    lang = 'en' if lang == 'en' else 'es'
    feats, errors, sources = [], [], {}
    for k, rid in enumerate(osm_ids(text)):
        if k:
            time.sleep(1)                 # Nominatim asks for no more than one query per second
        st = {}                           # 'limited', 'net' (motivo), 'found', 'line', 'missing', 'empty'

        def attempt(fn):
            try:
                return fn()
            except Limited:
                st['limited'] = True
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                st['net'] = str(getattr(e, 'reason', e))
            return None
        name, src = '', 'polygons.openstreetmap.fr'
        geom = attempt(lambda: _from_polygons(rid))
        f = attempt(lambda: _nominatim(rid, 0 if geom else 1))          # with the outline already at hand, only for the name
        st['empty'] = f == {}
        if f:
            st['found'] = True
            pr = f.get('properties') or {}
            name = _name(pr.get('namedetails') or {'name': pr.get('name')}, lang)
            if not geom and f.get('geometry'):
                if 'Polygon' in f['geometry']['type']:
                    geom, src = attempt(lambda: _norm(shape(f['geometry']))), 'nominatim.openstreetmap.org'
                else:
                    st['line'] = True
        if not geom:
            r = attempt(lambda: _from_overpass(rid))
            if r:
                geom, tags = r
                src = 'overpass-api.de'
                if tags is None:
                    st['missing'] = True
                else:
                    st['found'] = True
                    name = name or _name(tags, lang)
                    st['line'] = st.get('line') or not geom
        if geom:
            sources[rid] = src
            feats.append({'type': 'Feature', 'properties': {'name': name or 'OSM %d' % rid, 'osm_relation': rid}, 'geometry': geom})
        elif st.get('line'):
            errors.append('la relación %d no es un área (es una ruta, una línea o un punto): no tiene contorno que importar' % rid)
        elif st.get('missing') and not st.get('found'):
            errors.append('la relación %d no existe en OpenStreetMap' % rid)
        elif st.get('limited'):
            errors.append('OpenStreetMap ha limitado las consultas (demasiadas seguidas): espera un minuto y vuelve a intentarlo')
        elif st.get('empty') and not geom:
            errors.append('no se encontró ningún contorno para la relación %d: no existe o no es un área (Overpass no respondió para confirmarlo)' % rid)
        else:
            errors.append('sin conexión con OpenStreetMap (%s): revisa internet y vuelve a intentarlo' % st.get('net', 'sin respuesta'))
    return {'type': 'FeatureCollection', 'features': feats, 'errors': errors, 'sources': sources}


# ------------------------------------------------------------------ KML / KMZ
def _tag(e):
    return e.tag.rsplit('}', 1)[-1] if isinstance(e.tag, str) else ''      # without namespace: works for KML 2.0-2.2 and gx:


def _ring(e):
    """<LinearRing> (or whatever carries <coordinates>) -> [[lon, lat], ...] closed, without altitude; None if it is less than a triangle."""
    c = next((x for x in e.iter() if _tag(x) == 'coordinates'), None)
    pts = [[float(a), float(b)] for a, b in re.findall(r'(-?\d[\d.eE+-]*)\s*,\s*(-?\d[\d.eE+-]*)(?:,-?[\d.eE+-]*)?', (c.text if c is not None else '') or '')]
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts if len(pts) >= 4 else None


def _kml_polys(e, polys, skipped, pts=None):
    for c in e:
        t = _tag(c)
        if t == 'Point' and pts is not None:       # pin (city, unit…): only if points are requested
            m = re.search(r'(-?\d[\d.eE+-]*)\s*,\s*(-?\d[\d.eE+-]*)', next((x.text or '' for x in c.iter() if _tag(x) == 'coordinates'), ''))
            if m:
                pts.append([float(m.group(1)), float(m.group(2))])
                continue
        if t == 'Polygon':
            outer = next((_ring(x) for x in c if _tag(x) == 'outerBoundaryIs'), None)
            if outer:
                polys.append([outer] + [r for x in c if _tag(x) == 'innerBoundaryIs' for r in (_ring(l) for l in x if _tag(l) == 'LinearRing') if r])
        elif t == 'LinearRing':
            r = _ring(c)
            if r:
                polys.append([r])
        elif t in ('Point', 'LineString', 'Track', 'MultiTrack', 'Model'):
            skipped[0] += 1
        elif t == 'MultiGeometry':
            _kml_polys(c, polys, skipped, pts)


def kml_fc(data, points=False):
    """KML or KMZ (bytes) -> FeatureCollection with one MultiPolygon per Placemark; 'skipped' = points and lines not imported.
    points=True: pins too, as Point with the Placemark name (cities, units… in the importers that use them)."""
    if data[:2] == b'PK':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                kmls = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith('.kml')]
                pick = next((i for i in kmls if i.filename.lower() == 'doc.kml'), kmls[0] if kmls else None)
                if pick is None:
                    raise ValueError('el KMZ no lleva ningún archivo .kml dentro')
                with z.open(pick) as f:        # only that file, in memory and capped: the size the zip declares may lie
                    data = f.read(MAX_KML + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error) as e:     # also broken or truncated data
            raise ValueError('KMZ no válido: %s' % e)
    if len(data) > MAX_KML:
        raise ValueError('el KML es demasiado grande (más de %d MB)' % (MAX_KML >> 20))
    root_at = re.search(rb'<[A-Za-z_]', data)
    # a KML carries no DTD (no entity bombs); only before the root: an HTML description may carry <!DOCTYPE html>
    if b'<!DOCTYPE' in data[:root_at.start() if root_at else len(data)]:
        raise ValueError('KML no válido: lleva una declaración DOCTYPE')
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError('KML no válido: %s' % e)
    feats, skipped = [], [0]
    for pm in root.iter():
        if _tag(pm) != 'Placemark':
            continue
        polys, pts = [], ([] if points else None)
        _kml_polys(pm, polys, skipped, pts)
        try:
            geom = _norm(shape({'type': 'MultiPolygon', 'coordinates': polys})) if polys else None
        except Exception:
            geom = None
        name = (next((x.text for x in pm if _tag(x) == 'name' and x.text), '') or '').strip()
        if geom:
            feats.append({'type': 'Feature', 'properties': {'name': name} if name else {}, 'geometry': geom})
        for p in pts or []:
            feats.append({'type': 'Feature', 'properties': {'name': name} if name else {}, 'geometry': {'type': 'Point', 'coordinates': p}})
    return {'type': 'FeatureCollection', 'features': feats, 'skipped': skipped[0]}


def api(path, p):
    if path == '/api/geojson/osm':
        return fetch_osm(p.get('ids'), p.get('lang'))
    if path == '/api/geojson/kml':
        try:
            return kml_fc(base64.b64decode(str(p.get('data') or '').split(',')[-1]), bool(p.get('points')))
        except (TypeError, binascii.Error):
            raise ValueError('KML no válido')
    gs, a, b = normalize(p.get('geoms') or [], float(p.get('tol') or 0))
    return {'geoms': gs, 'before': a, 'after': b}


def _selfcheck():
    assert osm_ids('51477') == [51477]
    assert osm_ids(' r51477, relation/62422  https://www.openstreetmap.org/relation/1473947#map=6/51/10 51477') == [51477, 62422, 1473947]
    assert osm_ids('openstreetmap.org/relation/7?x=1') == [7]
    for bad in ('', 'way/12', 'abc', '12abc', 'https://evil.example/relation/5', '51477&x=http://a', '-5'):
        try:
            osm_ids(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    kml = '''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2"><Document><name>doc</name>
<Folder><name>f1</name><Folder>
 <Placemark><name> Isle </name><Polygon><outerBoundaryIs><LinearRing><coordinates>
   0,0,100 4,0,100 4,4,100 0,4,100 0,0,100</coordinates></LinearRing></outerBoundaryIs>
   <innerBoundaryIs><LinearRing><coordinates>1,1,0 2,1,0 2,2,0 1,2,0 1,1,0</coordinates></LinearRing></innerBoundaryIs></Polygon></Placemark>
 <Placemark><name>Dos</name><MultiGeometry><Point><coordinates>9,9,0</coordinates></Point>
   <Polygon><outerBoundaryIs><LinearRing><coordinates>10,0 12,0 12,2 10,2</coordinates></LinearRing></outerBoundaryIs></Polygon>
   <MultiGeometry><Polygon><outerBoundaryIs><LinearRing><coordinates>11,1 13,1 13,3 11,3 11,1</coordinates></LinearRing></outerBoundaryIs></Polygon></MultiGeometry>
 </MultiGeometry></Placemark>
 <Placemark><name>Ring</name><LinearRing><coordinates>20,0,0 21,0,0 21,1,0 20,0,0</coordinates></LinearRing></Placemark>
 <Placemark><name>Lazo</name><Polygon><outerBoundaryIs><LinearRing><coordinates>30,0 32,2 32,0 30,2 30,0</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Folder></Folder>
<Placemark><name>Ruta</name><LineString><coordinates>0,0,0 1,1,0</coordinates></LineString></Placemark>
<Placemark><name>Pin</name><Point><coordinates>5,5,0</coordinates></Point></Placemark>
<Placemark><name>Vuelo</name><gx:Track><gx:coord>1 2 3</gx:coord></gx:Track></Placemark>
</Document></kml>'''.encode()
    fc = kml_fc(kml)
    by = {f['properties']['name']: shape(f['geometry']) for f in fc['features']}
    assert list(by) == ['Isle', 'Dos', 'Ring', 'Lazo'], list(by)
    assert fc['skipped'] == 4, fc['skipped']
    assert abs(by['Isle'].area - 15) < 1e-9                       # 16 menos el hueco
    assert abs(by['Dos'].area - 7) < 1e-9 and len(by['Dos'].geoms) == 1     # two overlapping parts, merged (and the first one closed itself)
    assert by['Lazo'].is_valid and len(by['Lazo'].geoms) == 2     # lazo en ocho, reparado
    assert all(len(pt) == 2 for f in fc['features'] for p in f['geometry']['coordinates'] for r in p for pt in r)   # no altitude
    withpts = kml_fc(kml, points=True)                              # pins as Point: «Pin» and the one in «Dos»
    assert sorted(f['properties']['name'] for f in withpts['features'] if f['geometry']['type'] == 'Point') == ['Dos', 'Pin']
    assert withpts['skipped'] == 2 and next(f for f in withpts['features'] if f['properties']['name'] == 'Pin')['geometry']['coordinates'] == [5.0, 5.0]
    old = kml.replace(b'http://www.opengis.net/kml/2.2', b'http://earth.google.com/kml/2.0')
    assert len(kml_fc(old)['features']) == 4 and len(kml_fc(kml.replace(b' xmlns="http://www.opengis.net/kml/2.2"', b''))['features']) == 4
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('../../fuera.kml', b'<kml><Placemark><name>trampa</name></Placemark></kml>')
        z.writestr('files/icon.png', b'x')
        z.writestr('doc.kml', kml)
    assert len(kml_fc(buf.getvalue())['features']) == 4            # doc.kml aunque no sea el primero; nada se extrae a disco
    global MAX_KML
    keep, MAX_KML = MAX_KML, 1000
    try:
        bomb = io.BytesIO()
        with zipfile.ZipFile(bomb, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('doc.kml', b'<kml>' + b' ' * 5000000 + b'</kml>')
        for data in (bomb.getvalue(), b'<kml>' + b' ' * 2000 + b'</kml>'):
            try:
                kml_fc(data)
                raise AssertionError('uncapped')
            except ValueError:
                pass
    finally:
        MAX_KML = keep
    html = kml.replace(b'<name> Isle </name>', b'<name> Isle </name><description><![CDATA[<!DOCTYPE html><p>x</p>]]></description>')
    assert len(kml_fc(html)['features']) == 4                       # HTML in a description is not a DTD
    cut = io.BytesIO()
    with zipfile.ZipFile(cut, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('doc.kml', kml * 50)
    broken = bytearray(cut.getvalue())
    broken[60:80] = b'\xff' * 20                                    # datos comprimidos estropeados
    for data in (b'PK\x03\x04roto', bytes(broken), b'<kml><a></kml>', b'<!DOCTYPE x [<!ENTITY a "b">]><kml/>'):
        try:
            kml_fc(data)
            raise AssertionError(data)
        except ValueError:
            pass
    sq = {'type': 'MultiPolygon', 'coordinates': [[[[0, 0], [1, 0.001], [2, 0], [2, 2], [0, 2], [0, 0]]]]}
    assert normalize([sq], 0.01)[1:] == (6, 5) and normalize([sq])[1:] == (6, 6)
    two = {'type': 'MultiPolygon', 'coordinates': [[[[10, 0], [12, 0], [12, 2], [10, 2], [10, 0]]], [[[11, 1], [13, 1], [13, 3], [11, 3], [11, 1]]]]}
    assert abs(shape(normalize([two])[0][0]).area - 7) < 1e-9      # GeoJSON with overlapping parts: no hole in the overlap
    # Google Earth -> GeoJSON: a feature with GeometryCollection (nested, with altitude, points and lines mixed) = a single shape
    pol = lambda x: {'type': 'Polygon', 'coordinates': [[[x, 0, 0], [x + 2, 0, 0], [x + 2, 2, 0], [x, 2, 0], [x, 0, 0]]]}
    gc = {'type': 'GeometryCollection', 'geometries': [pol(0), pol(1), {'type': 'Point', 'coordinates': [9, 9, 0]}, {'type': 'LineString', 'coordinates': [[0, 0, 0], [1, 1, 0]]},
                                                       {'type': 'GeometryCollection', 'geometries': [pol(10)]}]}
    out, a, b = normalize([gc, {'type': 'Point', 'coordinates': [1, 2]}])
    assert out[1] is None and out[0]['type'] == 'MultiPolygon' and len(out[0]['coordinates']) == 2 and abs(shape(out[0]).area - 10) < 1e-9
    assert all(len(pt) == 2 for p in out[0]['coordinates'] for r in p for pt in r)
    print('geo_sources: ok')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        r = fetch_osm(' '.join(sys.argv[1:]))
        for f in r['features']:
            print(f['properties'], r['sources'][f['properties']['osm_relation']], _verts(f['geometry']), 'vértices')
        print(r['errors'])
    else:
        _selfcheck()
