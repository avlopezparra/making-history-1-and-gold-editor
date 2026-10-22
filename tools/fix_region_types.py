"""Repara un regionpack cuyas regiones de tierra quedaron como mar (u_type 0) y, opcionalmente, mallas con contorno inválido.

Uso (con el editor CERRADO; trabaja sobre la carpeta del PROYECTO, no sobre el juego; luego «Instalar» en el editor):
    python fix_region_types.py editor_proyecto_Probando3 [--mar REGEX] [--terreno N] [--solo-ver] [--mallas]

Todas las regiones de mar cuyo nombre NO coincida con --mar (por defecto: Sea|Aguas|Ocean|Gulf|Bay|Strait|Channel|Lake|River|Mar |Golfo|Estrecho)
pasan a tierra con el terreno indicado (1 llanura por defecto). Siempre gira a antihorario los triángulos en sentido
horario (el juego no los dibuja ni deja elegir esas regiones) y pone a 0 el flag de costa de los bordes tierra-tierra y mar-mar. Con --mallas se vuelven a guardar con saneado las regiones cuyo contorno es inválido.
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
    fix = new_region.normalize_map(P.m)       # triángulos antihorarios (si no, el juego no los dibuja ni deja elegir) y costas
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
