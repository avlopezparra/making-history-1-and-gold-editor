"""Wikidata para el editor de escenarios: buscar ciudades/países y leer coordenadas (P625), población (P1082), país (P17),
capital (P36), bandera (P41) según el año del escenario. Solo lectura de la API pública (wbsearchentities, wbgetentities, SPARQL)
con User-Agent propio; las respuestas se guardan en caché para poder trabajar sin conexión."""
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

UA = 'MHModdingKit/3.1 (Making History scenario editor; local tool) Python-urllib'
API = 'https://www.wikidata.org/w/api.php'
SPARQL = 'https://query.wikidata.org/sparql'
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache', 'wikidata')
MAX_GAP = 20          # años: población solo si el dato está a esta distancia del año del escenario
WORLDCITYPOP = 'https://www.worldcitypop.com/data.asp'
SETTLEMENT = 'Q486972'     # asentamiento humano (ciudades, pueblos…)
AIR_FORCE = ('Q2642956', 'Q61883')     # fuerza aérea (y «air force» como rama militar): su logotipo (P154) es la escarapela (roundel)


def commons(file):
    q = urllib.parse.quote(file.replace(' ', '_'))
    return {'file': file, 'page': 'https://commons.wikimedia.org/wiki/File:' + q,
            'png': 'https://commons.wikimedia.org/wiki/Special:FilePath/%s?width=512' % q}


class Offline(Exception):
    pass


def _get(url, ttl=30 * 86400):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + '.json')
    if os.path.exists(f) and time.time() - os.path.getmtime(f) < ttl:
        return json.load(open(f, encoding='utf-8'))
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        if os.path.exists(f):            # sin conexión: lo de la caché aunque sea viejo
            return json.load(open(f, encoding='utf-8'))
        raise Offline('sin conexión con Wikidata (%s)' % e)
    json.dump(data, open(f, 'w', encoding='utf-8'))
    return data


def _api(**kw):
    kw.update(format='json')
    return _get(API + '?' + urllib.parse.urlencode(kw))


def _sparql(q):
    return _get(SPARQL + '?' + urllib.parse.urlencode({'query': q, 'format': 'json'}))['results']['bindings']


def _label(ent, lang):
    ls = ent.get('labels', {})
    for l in (lang, 'en', 'es'):
        if l in ls:
            return ls[l]['value']
    return next(iter(ls.values()), {}).get('value', ent.get('id'))


def labels(ids, lang='es'):
    ids = [i for i in dict.fromkeys(ids) if i]
    out = {}
    for k in range(0, len(ids), 50):
        r = _api(action='wbgetentities', ids='|'.join(ids[k:k + 50]), props='labels', languages=lang + '|en')
        out.update({i: _label(e, lang) for i, e in r.get('entities', {}).items()})
    return out


def search(text, kind='city', lang='es'):
    r = _api(action='wbsearchentities', search=text, language=lang, uselang=lang, type='item', limit=20)
    hits = [{'id': h['id'], 'label': h.get('label', h['id']), 'description': h.get('description', '')} for h in r.get('search', [])]
    if kind == 'city' and hits:      # solo asentamientos (si SPARQL no responde, se muestran todos)
        try:
            vals = ' '.join('wd:' + h['id'] for h in hits)
            ok = {b['i']['value'].rsplit('/', 1)[1] for b in _sparql(
                'SELECT DISTINCT ?i WHERE { VALUES ?i { %s } ?i wdt:P31/wdt:P279* wd:%s }' % (vals, SETTLEMENT))}
            hits = [h for h in hits if h['id'] in ok] or hits
        except Offline:
            pass
    return hits


def _year(t):        # '+1914-06-28T00:00:00Z' -> 1914
    try:
        return int(t.lstrip('+')[:5].rstrip('-')) if not t.startswith('-') else -int(t[1:5])
    except Exception:
        return None


def _q(claim, p):
    v = (claim.get('qualifiers', {}).get(p) or [{}])[0].get('datavalue', {}).get('value')
    return _year(v['time']) if isinstance(v, dict) and 'time' in v else None


def _val(claim):
    return claim.get('mainsnak', {}).get('datavalue', {}).get('value')


def _by_year(claims, year):
    """Valores de una propiedad vigentes en 'year' (P580 inicio / P582 fin); si ninguno tiene fechas, el preferido."""
    live, dated = [], False
    for c in claims:
        a, b = _q(c, 'P580'), _q(c, 'P582')
        dated |= a is not None or b is not None
        if (a is None or a <= year) and (b is None or year < b):
            live.append(c)
    if not dated:
        live = [c for c in claims if c.get('rank') == 'preferred'] or claims
    return [c for c in live if c.get('rank') != 'deprecated']


def population(claims, year):
    pts = []
    for c in claims:
        v, y = _val(c), _q(c, 'P585')
        if v and y is not None:
            pts.append((abs(y - year), y, int(float(v['amount']))))
    pts.sort()
    best = pts[0] if pts else None
    return {'value': best[2] if best and best[0] <= MAX_GAP else None, 'year': best[1] if best else None,
            'gap': best[0] if best else None, 'all': sorted((y, n) for _, y, n in pts),
            'alt': None if best and best[0] <= MAX_GAP else WORLDCITYPOP}


def entity(qid, year, lang='es'):
    qid = qid.strip().upper()
    if not qid.startswith('Q') or not qid[1:].isdigit():
        raise ValueError('ID de Wikidata no válido: %s (p. ej. Q11194)' % qid)
    e = _api(action='wbgetentities', ids=qid, props='labels|descriptions|claims', languages=lang + '|en')['entities'][qid]
    if 'missing' in e:
        raise ValueError('%s no existe en Wikidata' % qid)
    cl = e.get('claims', {})
    out = {'id': qid, 'label': _label(e, lang), 'description': (e.get('descriptions', {}).get(lang) or e.get('descriptions', {}).get('en') or {}).get('value', ''),
           'year': year, 'url': 'https://www.wikidata.org/wiki/' + qid}
    co = [_val(c) for c in cl.get('P625', []) if _val(c)]
    if co:
        out['coords'] = {'lon': round(co[0]['longitude'], 4), 'lat': round(co[0]['latitude'], 4)}
    out['population'] = population(cl.get('P1082', []), year)
    refs = {}
    for p in ('P17', 'P36', 'P131'):
        refs[p] = [_val(c)['id'] for c in _by_year(cl.get(p, []), year) if _val(c)]
    out['inception'] = next((_year(_val(c)['time']) for c in cl.get('P571', []) if _val(c)), None)
    out['dissolved'] = next((_year(_val(c)['time']) for c in cl.get('P576', []) if _val(c)), None)
    out['exists'] = (out['inception'] is None or out['inception'] <= year) and (out['dissolved'] is None or year < out['dissolved'])
    fl = [_val(c) for c in _by_year(cl.get('P41', []), year) if _val(c)]
    if not fl:        # sin P41: el ítem de la bandera (P163, instancia de bandera Q14660/Q186516) y su imagen (P18)
        for fid in [_val(c)['id'] for c in _by_year(cl.get('P163', []), year) if _val(c)][:3]:
            fc = _api(action='wbgetentities', ids=fid, props='claims')['entities'][fid].get('claims', {})
            fl = [_val(c) for c in fc.get('P18', []) if _val(c)]
            if fl:
                break
    if fl:
        out['flag'] = commons(fl[0])
    names = labels(sum(refs.values(), []), lang)
    out['country'] = [{'id': i, 'label': names.get(i, i)} for i in refs['P17']]
    out['capital'] = [{'id': i, 'label': names.get(i, i)} for i in refs['P36']]
    out['located_in'] = [{'id': i, 'label': names.get(i, i)} for i in refs['P131']]
    return out


def major_cities(qid, year, lang='es', limit=12):
    """Ciudades más pobladas del país o de la provincia (P17 o P131) con su población más cercana al año."""
    rows = _sparql('''SELECT ?c ?cLabel ?lat ?lon (MAX(?p) AS ?pop) WHERE {
      { ?c wdt:P17 wd:%s } UNION { ?c wdt:P131 wd:%s }
      ?c wdt:P31/wdt:P279* wd:Q515 ; wdt:P1082 ?p ; p:P625/psv:P625 [ wikibase:geoLatitude ?lat ; wikibase:geoLongitude ?lon ] .
      SERVICE wikibase:label { bd:serviceParam wikibase:language "%s,en". }
    } GROUP BY ?c ?cLabel ?lat ?lon ORDER BY DESC(?pop) LIMIT %d''' % (qid, qid, lang, limit))
    return [{'id': b['c']['value'].rsplit('/', 1)[1], 'label': b['cLabel']['value'], 'pop_now': int(float(b['pop']['value'])),
             'coords': {'lat': round(float(b['lat']['value']), 4), 'lon': round(float(b['lon']['value']), 4)}} for b in rows]


def roundel(qid, year=None, lang='es'):
    """Escarapela (roundel): logotipo P154 de la fuerza aérea (P31 Q2642956) del país (P17). Búsqueda por haswbstatement (sin SPARQL)."""
    ids = []
    for af in AIR_FORCE:
        r = _api(action='query', list='search', srsearch='haswbstatement:P31=%s haswbstatement:P17=%s' % (af, qid), srlimit=10)
        ids += [x['title'] for x in r.get('query', {}).get('search', [])]
    if not ids:
        return None
    ents = _api(action='wbgetentities', ids='|'.join(dict.fromkeys(ids))[:2000], props='labels|claims', languages=lang + '|en')['entities']
    def alive(e):        # primero las que existían en el año del escenario
        c = e.get('claims', {})
        a = next((_year(_val(x)['time']) for x in c.get('P571', []) if _val(x)), None)
        b = next((_year(_val(x)['time']) for x in c.get('P576', []) if _val(x)), None)
        return year is None or ((a is None or a <= year) and (b is None or year < b))
    for i, e in sorted(ents.items(), key=lambda x: not alive(x[1])):
        lg = [_val(c) for c in e.get('claims', {}).get('P154', []) if _val(c)]
        if lg:
            return {**commons(lg[0]), 'air_force': {'id': i, 'label': _label(e, lang)}}
    return None
