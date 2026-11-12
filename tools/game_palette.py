"""Terrain palette of each game for the editor map.

Gold's OperationalTerrain textures are MH1's with another color (duller sea and terrain; see port_tiles).
If the open scenario is from one game and the editor works with the other's folder (e.g. a Gold scenario copied
into MH1), the textures are shown with the scenario game's palette: a color table learned from some World tiles
of both games (the same pixels in both), computed once and kept in memory.
"""
import os
import threading

import numpy as np
from PIL import Image

import gamepaths
from fix_texture import decode
from port_tiles import ColorMap

# unmodded World tiles with sea, coast, desert, jungle, mountain and snow (the table comes from pixels equal in both)
SAMPLE = ('03-03', '08-05', '10-06', '12-03', '12-07', '13-05', '16-04', '19-04', '20-08', '07-11')
LEVEL = 2          # 256 px mipmap: enough for the table and fast to read
_MAPS = {}
_LOCK = threading.Lock()


def _pixels(game, names):
    d = os.path.join(gamepaths.maps_dir(game), 'World', 'art', 'OperationalTerrain')
    out = []
    for n in names:
        p = os.path.join(d, 'OperationalTerrain-%s-%02d.tga' % (n, LEVEL))
        out.append(np.asarray(decode(open(p, 'rb').read(), 1024 >> LEVEL)).astype(np.int32)[..., :3].reshape(-1, 3))
    return np.concatenate(out)


def color_map(src, dst):
    """ColorMap from 'src' palette to 'dst' palette (or None if either game is missing)."""
    key = (src, dst)
    with _LOCK:
        if key not in _MAPS:
            _MAPS[key] = None
            if gamepaths.installed(src) and gamepaths.installed(dst):
                d = os.path.join(gamepaths.maps_dir(src), 'World', 'art', 'OperationalTerrain')
                names = [n for n in SAMPLE if os.path.exists(os.path.join(d, 'OperationalTerrain-%s-%02d.tga' % (n, LEVEL)))]
                if names:
                    _MAPS[key] = ColorMap(_pixels(src, names), _pixels(dst, names))
        return _MAPS[key]


def recolor(img, src, dst):
    """Image (PIL) with 'src' terrain colors converted to the 'dst' palette."""
    cm = color_map(src, dst) if src != dst else None
    if cm is None:
        return img
    a = np.asarray(img.convert('RGB')).astype(np.int32)
    out = cm(a.reshape(-1, 3)).reshape(a.shape)
    return Image.fromarray(out, 'RGB')
