"""Repairs a regionpack whose land regions ended up as sea (u_type 0) and, optionally, meshes with an invalid outline.

Usage (with the editor CLOSED; works on the PROJECT folder, not on the game; then «Instalar» in the editor):
    python fix_region_types.py editor_proyecto_Probando3 [--mar REGEX] [--terreno N] [--solo-ver] [--mallas]

All sea regions whose name does NOT match --mar (default: Sea|Aguas|Ocean|Gulf|Bay|Strait|Channel|Lake|River|Mar |Golfo|Estrecho)
become land with the given terrain (1 plains by default). It always turns clockwise triangles counterclockwise
(the game neither draws them nor lets those regions be selected) and sets the coast flag of land-land and sea-sea borders to 0. With --mallas regions with an invalid outline are re-saved with sanitizing.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import editor_core  # noqa: E402
from shapely.geometry import shape, mapping  # noqa: E402
from shapely.validation import explain_validity  # noqa: E402

DEFAULT_SEA = r'Sea|Aguas|Ocean|Gulf|Bay|Strait|Channel|Lake|River|^Mar |Golfo|Estrecho|Bahía|Canal'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('proyecto')
    ap.add_argument('--mar', default=DEFAULT_SEA, help='regex de los nombres que SÍ son mar')
    ap.add_argument('--terreno', type=int, default=1)
    ap.add_argument('--solo-ver', action='store_true')
    ap.add_argument('--mallas', action='store_true', help='re-guardar con saneado las regiones de contorno inválido')
    a = ap.parse_args()
    folder = os.path.abspath(a.proyecto)
    pack = os.path.basename(folder).split('editor_proyecto_', 1)[-1] if 'editor_proyecto_' in folder else None
    P = editor_core.Project(folder, os.path.join(os.path.dirname(folder), 'backup', 'mapa_original'), pack)
    sea_re = re.compile(a.mar, re.I)
    names = [P.rname(g.index) for g in P.m['regions'] if g.u_type == 0 and not sea_re.search(P.rname(g.index))]
    print('regiones de mar que parecen tierra (%d): %s' % (len(names), ', '.join(names)))
    if a.solo_ver:
        return
    if names:
        r = P.convert_region_type(names, 'land', a.terreno)
        print('convertidas a tierra:', len(r['done']), r['skipped'] or '')
    import mhmap
    import new_region
    fix = new_region.normalize_map(P.m)       # counterclockwise triangles (otherwise the game neither draws them nor lets them be selected) and coasts
    print('triángulos girados a antihorario: %d; tramos de costa corregidos: %d' % (fix['triangulos'], fix['costas']))
    if fix['triangulos'] or fix['costas']:
        mhmap.save_map(P.m, P.xml)
        P.reload()
    if a.mallas:
        bad = []
        for g in P.m['regions']:
            main = P.outline(g.index)[0]
            geo = shape({'type': 'MultiPolygon', 'coordinates': main}) if main else None
            if geo is not None and not geo.is_valid:
                bad.append((g.index, P.rname(g.index), explain_validity(geo)))
        print('contornos inválidos:', [(n, w[:40]) for _, n, w in bad])
        for idx, n, _ in bad:
            geo = shape({'type': 'MultiPolygon', 'coordinates': P.outline(idx)[0]})
            clean = P._clean_geom(geo, 1)
            rep = P.save({'modified': {str(idx): mapping(clean)['coordinates']}, 'paint': False, 'topo': True})
            print(n, '->', rep.get('errors') or 'ok', rep.get('warnings') or '')


if __name__ == '__main__':
    main()
