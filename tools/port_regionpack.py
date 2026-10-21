"""Copia un regionpack de un juego a otro (MH1 -> Gold o al reves), con las texturas del juego de destino.

  xml\\   regions.bin, borders.brd, regions.nts y map.xml del regionpack de origen (el mapa es el mismo formato);
         properties.xml del World de destino si el del origen es el de serie (Gold tiene bordes algo distintos).
  art\\   las texturas del World de destino; los tiles de OperationalTerrain que el regionpack cambio respecto al
         World original del juego de origen se trasladan con port_tiles (tabla de color origen -> destino).

Original de cada tile en el origen: backup/<juego>/mapa_original/OperationalTerrain si el editor lo toco
(p. ej. Chile Fixes instalado en World), si no el de World.

Uso: python port_regionpack.py WorldModern --de mh1 --a gold
"""
import argparse
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gamepaths  # noqa: E402
import port_tiles  # noqa: E402

BINARIES = ('regions.bin', 'borders.brd', 'regions.nts', 'map.xml')


def same(a, b):
    return os.path.exists(a) and os.path.exists(b) and open(a, 'rb').read() == open(b, 'rb').read()


def port_pack(pack, src, dst, out_name=None, log=print):
    sp = os.path.join(gamepaths.maps_dir(src), pack)
    sw = os.path.join(gamepaths.maps_dir(src), 'World')
    dw = os.path.join(gamepaths.maps_dir(dst), 'World')
    out = os.path.join(gamepaths.maps_dir(dst), out_name or pack)
    if not os.path.isdir(sp):
        raise ValueError('no existe el regionpack %s en %s' % (pack, gamepaths.GAMES[src]['short']))
    if os.path.exists(out):
        raise ValueError('ya existe %s (no se sobrescribe)' % out)
    orig = os.path.join(gamepaths.map_backup(src), 'OperationalTerrain')
    ot = lambda d: os.path.join(d, 'art', 'OperationalTerrain')
    vanilla = lambda n: os.path.join(orig, n) if os.path.exists(os.path.join(orig, n)) else os.path.join(ot(sw), n)
    changed = [n for n in sorted(os.listdir(ot(sp))) if port_tiles.NAME.match(n) and not same(os.path.join(ot(sp), n), vanilla(n))]
    log('%s: %d texturas cambiadas respecto al World original de %s' % (pack, len(changed), gamepaths.GAMES[src]['short']))
    shutil.copytree(os.path.join(dw, 'art'), os.path.join(out, 'art'))
    os.makedirs(os.path.join(out, 'xml'))
    for f in BINARIES:
        shutil.copy2(os.path.join(sp, 'xml', f), os.path.join(out, 'xml', f))
    pf = 'properties.xml'
    use_dst = same(os.path.join(sp, 'xml', pf), os.path.join(sw, 'xml', pf))
    shutil.copy2(os.path.join(dw if use_dst else sp, 'xml', pf), os.path.join(out, 'xml', pf))
    if os.path.exists(os.path.join(sp, 'changelog.json')):
        shutil.copy2(os.path.join(sp, 'changelog.json'), os.path.join(out, 'changelog.json'))
    if changed:
        with tempfile.TemporaryDirectory() as tmp:
            o, m = os.path.join(tmp, 'orig'), os.path.join(tmp, 'mod')
            os.makedirs(o)
            os.makedirs(m)
            for n in changed:
                shutil.copy2(vanilla(n), os.path.join(o, n))
                shutil.copy2(os.path.join(ot(sp), n), os.path.join(m, n))
            port_tiles.port(o, m, ot(dw), ot(out), log=lambda *a: None)
    log('creado %s (properties.xml de %s)' % (out, gamepaths.GAMES[dst if use_dst else src]['short']))
    return {'regionpack': out, 'texturas_trasladadas': len(changed)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pack')
    ap.add_argument('--de', dest='src', required=True, choices=sorted(gamepaths.GAMES))
    ap.add_argument('--a', dest='dst', required=True, choices=sorted(gamepaths.GAMES))
    ap.add_argument('--nombre')
    a = ap.parse_args()
    print(port_pack(a.pack, a.src, a.dst, a.nombre))
