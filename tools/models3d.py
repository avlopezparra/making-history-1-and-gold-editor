"""Modelos 3D de las unidades (NIF Gamebryo 10.2.0.0).

Los SpriteLib*.xml apuntan siempre a «/../Modern Europe/system/ui/art/3D/...», pero el juego busca antes la misma ruta
dentro de la carpeta del escenario (scenarios/<Esc>/ui/art/3D/...). Si el escenario trae el .nif, el modelo es suyo; si
solo trae texturas (.dds/.tga con el nombre que pide el .nif), es el modelo del juego con textura propia.
"""
import os
import re

import scenario_core as sc

_TEX = re.compile(rb'[\w\-. ]+\.(?:dds|tga|bmp)', re.I)
_CACHE = {}


def rel_path(file_name):
    """«/../Modern Europe/system/ui/art/3D/X.nif» -> «ui/art/3D/X.nif» (relativa a system/ o al escenario)."""
    f = file_name.replace('\\', '/')
    i = f.lower().find('/system/')
    if i >= 0:
        f = f[i + len('/system/'):]
        if f.lower().startswith('scenarios/'):   # ruta explícita a un escenario
            return None
    return f.lstrip('/')


def nif_textures(path):
    """Nombres de textura que pide el .nif (cadenas NiSourceTexture)."""
    try:
        st = os.stat(path)
    except OSError:
        return []
    key = (path, st.st_mtime)
    if key not in _CACHE:
        data = open(path, 'rb').read()
        _CACHE[key] = sorted({m.decode('latin-1').strip() for m in _TEX.findall(data)})
    return _CACHE[key]


def model_status(file_name, scen_dir=None):
    """{'model': 'scenario'|'game'|'missing', 'textures': [..propias..], 'nif': ruta usada}"""
    rel = rel_path(file_name)
    game_sys = os.path.join(sc.GAME, 'Modern Europe', 'system')
    if rel is None:     # ruta absoluta a un escenario
        p = os.path.normpath(os.path.join(game_sys, file_name.replace('\\', '/').split('/system/', 1)[1]))
        return {'model': 'scenario' if os.path.exists(p) else 'missing', 'textures': [], 'nif': p}
    own = os.path.join(scen_dir, rel) if scen_dir else None
    if own and os.path.exists(own):
        return {'model': 'scenario', 'textures': [], 'nif': own}
    gp = os.path.join(game_sys, rel)
    if not os.path.exists(gp):
        return {'model': 'missing', 'textures': [], 'nif': gp}
    tex = []
    if scen_dir:
        d = os.path.join(scen_dir, os.path.dirname(rel))
        if os.path.isdir(d):
            have = {f.lower() for f in os.listdir(d)}
            tex = [t for t in nif_textures(gp) if t.lower() in have]
    return {'model': 'game', 'textures': tex, 'nif': gp}


def label(st):
    if st['model'] == 'scenario':
        return 'modelo propio'
    if st['model'] == 'missing':
        return 'falta el .nif'
    return 'textura propia' if st['textures'] else 'juego'
