"""Paleta del terreno de cada juego para el mapa del editor.

Las texturas OperationalTerrain de Gold son las de MH1 con otro color (mar y terreno mas apagados; ver port_tiles).
Si el escenario abierto es de un juego y el editor trabaja con la carpeta del otro (p. ej. un escenario de Gold copiado
en MH1), las texturas se muestran con la paleta del juego del escenario: tabla de color aprendida de unos tiles de World
de los dos juegos (los mismos pixeles en ambos), calculada una vez y guardada en memoria.
"""
import os
import threading

import numpy as np
from PIL import Image

import gamepaths
from fix_texture import decode
from port_tiles import ColorMap

# tiles de World sin mods con mar, costa, desierto, selva, montana y nieve (la tabla sale de pixeles iguales en ambos)
SAMPLE = ('03-03', '08-05', '10-06', '12-03', '12-07', '13-05', '16-04', '19-04', '20-08', '07-11')
LEVEL = 2          # mipmap de 256 px: suficiente para la tabla y rapido de leer
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
    """ColorMap de la paleta de 'src' a la de 'dst' (o None si falta alguno de los dos juegos)."""
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
    """Imagen (PIL) con los colores del terreno de 'src' pasados a la paleta de 'dst'."""
    cm = color_map(src, dst) if src != dst else None
    if cm is None:
        return img
    a = np.asarray(img.convert('RGB')).astype(np.int32)
    out = cm(a.reshape(-1, 3)).reshape(a.shape)
    return Image.fromarray(out, 'RGB')
