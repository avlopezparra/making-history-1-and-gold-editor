"""Prueba de ida y vuelta: leer -> escribir -> comparar bytes con el original.

Uso: python -I roundtrip.py <carpeta xml del mapa>
No escribe nada en la carpeta del juego: compara en memoria.
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mhmap  # noqa: E402


def main(folder):
    m = mhmap.load_map(folder)
    out = mhmap.encode_map(m)
    ok = True
    for name in mhmap.FILES:
        orig = open(os.path.join(folder, name), 'rb').read()
        new = out[name]
        same = orig == new
        ok &= same
        first_diff = next((i for i, (a, b) in enumerate(zip(orig, new)) if a != b), None)
        print('%-12s %10d bytes  %s  sha256 %s%s' % (
            name, len(orig), 'IDENTICO' if same else 'DISTINTO',
            hashlib.sha256(new).hexdigest()[:16],
            '' if same else '  (tam. nuevo %d, primera diferencia en %s)' % (len(new), first_diff)))

    # comprobaciones de coherencia entre los tres archivos
    regions, borders, st = m['regions'], m['borders'], m['shape_table']
    assert len(regions) == len(m['border_table']) == len(st), 'numero de regiones distinto entre archivos'
    pairs_bin = {tuple(sorted((g.index, n))) for g in regions for n in g.neighbors}
    pairs_brd = {b.regions for b in borders}
    print('regiones %d | bordes %d | shapes %d | vecindades bin=%d brd=%d coinciden=%s' % (
        len(regions), len(borders), len(m['shapes']), len(pairs_bin), len(pairs_brd), pairs_bin == pairs_brd))
    covered = sorted(i for t in st for i in range(t.first, t.last + 1))
    print('shapes cubiertos por la tabla: %d, sin repetir: %s' % (len(covered), covered == list(range(len(m['shapes'])))))
    print('RESULTADO:', 'OK' if ok else 'FALLO')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
