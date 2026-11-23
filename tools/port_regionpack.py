"""Copies a regionpack from one game to another (MH1 -> Gold or vice versa), with the target game's textures.

  xml\\   regions.bin, borders.brd, regions.nts and map.xml of the source regionpack (the map is the same format);
         properties.xml of the target World if the source one is stock (Gold has slightly different borders).
  art\\   the target World's textures; the OperationalTerrain tiles the regionpack changed relative to the
         original World of the source game are carried over with port_tiles (source -> target color table).

Original of each tile in the source: backup/<juego>/mapa_original/OperationalTerrain if the editor touched it
(e.g. Chile Fixes installed in World), otherwise World's.

Usage: python port_regionpack.py WorldModern --de mh1 --a gold
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


def _block_share(a, b):
    """Share of 16-byte DXT5 blocks that differ between two textures of the same size."""
    x, y = open(a, 'rb').read(), open(b, 'rb').read()
    if len(x) != len(y):
        return 1.0
    import numpy as np
    bx, by = (np.frombuffer(v, np.uint8)[:len(v) // 16 * 16].reshape(-1, 16) for v in (x, y))
    return float((bx != by).any(1).mean()) if len(bx) else 0.0


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
    for f in ('changelog.json', 'proyeccion.json'):      # proyeccion.json: «Adecuar» needs it to project positions
        if os.path.exists(os.path.join(sp, f)):
            shutil.copy2(os.path.join(sp, f), os.path.join(out, f))
    mm = os.path.join('art', 'MiniMap.tga')
    if os.path.exists(os.path.join(sp, mm)) and not same(os.path.join(sp, mm), os.path.join(sw, mm)):
        shutil.copy2(os.path.join(sp, mm), os.path.join(out, mm))     # the pack's own minimap (same format in both games)
    # a texture that is the pack's own background (almost every block differs from vanilla) is copied as is: the colour
    # model of port_tiles is for retouches painted on the vanilla terrain (and with a whole new world it runs out of memory)
    own = [n for n in changed if _block_share(os.path.join(ot(sp), n), vanilla(n)) > 0.9]
    for n in own:
        shutil.copy2(os.path.join(ot(sp), n), os.path.join(ot(out), n))
    changed = [n for n in changed if n not in set(own)]
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
    return {'regionpack': out, 'texturas_trasladadas': len(changed), 'texturas_copiadas': len(own)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pack')
    ap.add_argument('--de', dest='src', required=True, choices=sorted(gamepaths.GAMES))
    ap.add_argument('--a', dest='dst', required=True, choices=sorted(gamepaths.GAMES))
    ap.add_argument('--nombre')
    a = ap.parse_args()
    print(port_pack(a.pack, a.src, a.dst, a.nombre))
