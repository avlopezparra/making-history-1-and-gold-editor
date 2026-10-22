"""Regionpack «MH2World2» completo desde mh2/mh2_mundo.geojson + changelog de herencia para adaptar escenarios de World.

    python -u mh2_world2_completo.py                 # construye lo que falte (reintenta los fallos) y escribe el changelog
    python -u mh2_world2_completo.py --solo-changelog   # no construye: solo recalcula la herencia y el changelog

1) Construcción: pone en el proyecto del editor (making-history/editor_proyecto_MH2World2) todas las regiones del GeoJSON,
   de tierra y de mar, que aún no estén; las que el editor rechazó antes se vuelven a intentar una a una (si sigue fallando,
   se reintenta con el contorno aligerado). Se puede cortar y volver a lanzar: sigue por donde iba.
2) Herencia: compara por área cada región del mapa nuevo con las de World vanilla (solo tierra con tierra y mar con mar):
   - madre de una región MH2 = la región de World donde cae la mayor parte de su área;
   - heredera de una región de World = la región MH2 que se queda con la mayor parte de su área.
   En el changelog del proyecto, cada región nueva recibe «equivale» (las regiones de World a las que sustituye: el editor la
   hace nacer de la primera y le pasa ciudades, recursos, unidades y población de todas) y «madre» (de quién se reparte al
   añadirla si no sustituye a ninguna). Con eso, «Cambiar de regionpack» del editor adapta un escenario de World a MH2World2.
   Las regiones con el mismo nombre en World y en MH2 se conservan tal cual en los escenarios.
Copia de seguridad del changelog: changelog.antes_herencia.json (solo la primera vez). Informe legible: mh2/MH2World2_herencia.json.
No escribe nada en el juego: el regionpack se instala desde el editor («Regionpack» -> MH2World2 -> Instalar).
"""
import argparse, json, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import editor_core, mhmap, changelog_keys, geojson_compare
import mh2_make_world2 as W
from shapely.strtree import STRtree

REPORT = os.path.join(W.ROOT, 'mh2', W.NAME + '_herencia.json')


def build():
    """Pasadas de construcción hasta que no entre nada más (cada pasada reintenta los fallos de la anterior)."""
    resume = os.path.exists(W.FOLDER)
    prev = None
    for n in range(3):
        print('== construcción, pasada %d ==' % (n + 1), flush=True)
        failed = W.build(argparse.Namespace(resume=resume, retry=True, limit=0))
        resume = True
        if not failed or failed == prev:
            return failed
        prev = failed
    return failed


def heir_map(A, B):
    """{a: b} con b = la región de B que más área comparte con a (mismo tipo); sin solape, la más cercana del mismo tipo."""
    ov = geojson_compare._overlaps(A, B)
    out, pct = {}, {}
    for kind in (False, True):
        names = [n for n, (_, s) in B.items() if s == kind]
        tree = STRtree([B[n][0] for n in names])
        for a, (pa, sa) in A.items():
            if sa != kind:
                continue
            row = ov.get(a) or {}
            if row:
                b = max(row, key=row.get)
                out[a], pct[a] = b, round(100 * row[b] / pa.area, 1) if pa.area else 0
            elif names:
                out[a], pct[a] = names[int(tree.nearest(pa))], 0.0
    return out, pct, ov


def inheritance(P):
    print('== herencia: comparando áreas con World vanilla ==', flush=True)
    bdir = os.path.join(editor_core.MAPS, 'World')
    B = geojson_compare._geoms(mhmap.load_map(os.path.join(bdir, 'xml')), editor_core.load_renames(bdir))
    C = geojson_compare._geoms(P.m, P.renames, P)
    mother, mpct, ov_cb = heir_map(C, B)        # región MH2 -> región de World donde cae la mayor parte de su área
    heir, hpct, _ = heir_map(B, C)              # región de World -> región MH2 que se queda con la mayor parte de su área
    land_c = {n for n, (_, s) in C.items() if not s}
    # una región de World cuyo nombre sigue en el mapa (de tierra) se queda tal cual en los escenarios: es su propia heredera
    for v, (_, s) in B.items():
        if not s and v in land_c:
            heir[v] = v
    eq = {}
    for v, n in heir.items():
        if not B[v][1] and n != v:
            eq.setdefault(n, []).append(v)
    for n, vs in eq.items():
        vs.sort(key=lambda v: (v != mother.get(n), -(ov_cb.get(n) or {}).get(v, 0)))     # su madre primero (de ella nace)
    madre = {}
    for n in C:
        m = mother.get(n)
        if n in eq:
            madre[n] = eq[n][0]
        elif C[n][1] or m is None:
            madre[n] = m
        else:
            madre[n] = heir.get(m, m)       # la de World puede haber desaparecido: se reparte de quien la heredó
    return B, C, mother, mpct, heir, hpct, eq, madre


def write_changelog(P, C, eq, madre):
    path = P.changelog_path()
    bak = os.path.join(os.path.dirname(path), 'changelog.antes_herencia.json')
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    cl = [e for e in P.changelog() if 'herencia_world' not in (e.get('operaciones') or [])]     # la de una pasada anterior se rehace
    seen = set()
    for e in cl:
        for x in e.get('regiones_nuevas', []):
            n = x.get('nombre')
            if n in C:
                x['equivale'] = eq.get(n) or None
                x['madre'] = madre.get(n)
                seen.add(n)
    # regiones del mapa que el changelog no tiene anotadas: se añaden en una entrada aparte
    extra = [{'nombre': n, 'texto': n, 'madre': madre.get(n), 'pais': None, 'tipo': 0 if s else 1, 'controlador': None, 'terreno': None,
              'mar': s, 'poblacion': None, 'historicos': None, 'equivale': eq.get(n) or None} for n, (_, s) in C.items() if n not in seen]
    # una entrada «equivalencias» antigua mandaría sobre lo calculado: se vacía (luego se puede editar a mano en el editor)
    for e in cl:
        if 'equivalencias' in e:
            e['equivalencias'] = {}
    cl.append({'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'regionpack': P.pack, 'instalado': False, 'operaciones': ['herencia_world'],
               'origen': 'mh2_world2_completo', 'nota': 'madre/equivale calculados por área frente a World vanilla',
               'regiones_nuevas': extra})
    changelog_keys.dump(cl, path)
    return path, len(extra)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo-changelog', action='store_true')
    a = ap.parse_args()
    failed = [] if a.solo_changelog else build()
    P = editor_core.Project(W.FOLDER, os.path.join(W.FOLDER, '_respaldo'), pack=W.NAME)
    feats = json.load(open(W.SRC, encoding='utf-8'))['features']
    have = {r.name for r in P.m['regions']}
    missing = [f['properties']['name'] for f in feats if W.new_region.internal_name(W.mh2_plan.pretty(f['properties']['name'])) not in have]
    B, C, mother, mpct, heir, hpct, eq, madre = inheritance(P)
    path, extra = write_changelog(P, C, eq, madre)
    rep = {'regiones_en_el_mapa': len(P.m['regions']), 'contornos_del_geojson': len(feats), 'sin_poner': missing,
           'mh2': {n: {'mar': C[n][1], 'madre_world': mother.get(n), 'pct_area_en_madre': mpct.get(n), 'equivale': eq.get(n), 'madre_changelog': madre.get(n)}
                   for n in sorted(C)},
           'world': {v: {'mar': B[v][1], 'heredera': heir.get(v), 'pct_area_heredada': hpct.get(v)} for v in sorted(B)}}
    json.dump(rep, open(REPORT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    lost = sorted(v for v, (_, s) in B.items() if not s and hpct.get(v, 0) == 0 and heir.get(v) != v)
    print('listo: %d regiones en el mapa de %d contornos | sin poner: %d %s' % (len(P.m['regions']), len(feats), len(missing), missing[:10]))
    print('herencia: %d regiones MH2 sustituyen a regiones de World | %d de World conservan su nombre | %d de World sin solape (van a la más cercana): %s'
          % (len(eq), sum(1 for v, n in heir.items() if n == v), len(lost), lost[:10]))
    print('changelog: %s (%d regiones añadidas al registro)' % (path, extra))
    print('informe: %s' % REPORT)


if __name__ == '__main__':
    main()
