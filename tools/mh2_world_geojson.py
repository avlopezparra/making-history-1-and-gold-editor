"""GeoJSON del mundo de MH2 listo para «Importar GeoJSON» del editor: tierra + mar + rios (como mar) y los lagos decorativos como huecos.

    python mh2_world_geojson.py
Salida (mh2/):
  mh2_mundo.geojson           regiones de tierra y de mar (mh_type land_region / sea_region); los rios son sea_region (kind=river);
                              los lagos decorativos NO tienen region: son huecos en la geometria (las regiones no los cubren)
  mh2_lagos_vacios.geojson    los lagos decorativos como formas (mh_type=empty), solo de referencia
Prioridad al solaparse: lago (hueco) > rio (mar) > region.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mh2_regions
from shapely.geometry import Polygon, MultiPolygon, shape, mapping
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'mh2', 'mh2_regions.geojson')


def nst(name):
    base = os.path.dirname(mh2_regions.NST)
    out = {}
    for k, (verts, idx) in mh2_regions.parse(os.path.join(base, name)).items():
        tris = [Polygon([verts[idx[i]], verts[idx[i + 1]], verts[idx[i + 2]]]) for i in range(0, len(idx), 3)]
        out[k] = unary_union([t if t.is_valid else t.buffer(0) for t in tris if t.area > 0]).buffer(0)
    return out


def polys(g):
    ps = []
    for p in getattr(g, 'geoms', [g]):
        if p.geom_type == 'Polygon' and p.area > 1e-9:
            ps.append(p)
        elif p.geom_type in ('MultiPolygon', 'GeometryCollection'):
            ps += polys(p)
    return ps


def multi(g):
    ps = polys(g)
    return MultiPolygon(ps) if ps else None


def main():
    fc = json.load(open(SRC, encoding='utf-8'))
    lakes = nst('DecorativeLakes.nst')
    rivers = nst('Rivers.nst')
    L = unary_union(list(lakes.values()))
    # rios disjuntos entre si (de mayor a menor) y sin los lagos
    rv, seen = {}, None
    for k, g in sorted(rivers.items(), key=lambda kv: -kv[1].area):
        g = g.difference(L)
        if seen is not None:
            g = g.difference(seen)
        seen = g if seen is None else unary_union([seen, g])
        m = multi(g)
        if m:
            rv[k] = m
    R = unary_union(list(rv.values()))
    cut = unary_union([L, R])
    feats, dropped = [], []
    for f in fc['features']:
        g = multi(shape(f['geometry']).difference(cut))
        if g is None:
            dropped.append(f['properties']['name'])
            continue
        feats.append({'type': 'Feature', 'properties': f['properties'], 'geometry': mapping(g)})
    taken = {f['properties']['name'] for f in feats}
    for k, g in rv.items():
        nm = k.replace('_', ' ')
        if nm in taken:
            nm += ' (river)'
        taken.add(nm)
        feats.append({'type': 'Feature', 'properties': {'mh_type': 'sea_region', 'name': nm, 'kind': 'river'}, 'geometry': mapping(g)})
    out = os.path.join(ROOT, 'mh2', 'mh2_mundo.geojson')
    json.dump({'type': 'FeatureCollection', 'features': feats}, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
    lf = [{'type': 'Feature', 'properties': {'mh_type': 'empty', 'name': k, 'kind': 'decorative_lake'}, 'geometry': mapping(multi(g))}
          for k, g in lakes.items() if multi(g)]
    json.dump({'type': 'FeatureCollection', 'features': lf}, open(os.path.join(ROOT, 'mh2', 'mh2_lagos_vacios.geojson'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    n = lambda t: sum(1 for f in feats if f['properties']['mh_type'] == t)
    print('tierra %d, mar %d (de ellas %d rios), lagos %d (huecos), descartadas por quedar vacias: %s' % (
        n('land_region'), n('sea_region'), len(rv), len(lakes), dropped))
    print('lagos: %.2f grados2 de hueco; rios: %.2f grados2' % (L.area, R.area))


if __name__ == '__main__':
    main()
