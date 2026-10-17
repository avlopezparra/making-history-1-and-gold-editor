"""Carpeta del juego con la que trabajan los editores: Making History: The Calm and The Storm (MH1) o Making History Gold.

Los modulos editor_core, scenario_core y file_identify leen sus rutas (GAME, MAPS, SCEN_DIR, SCEN_ROOT...) como
variables del modulo en cada llamada; select() las reescribe todas a la vez. La eleccion se recuerda en
making-history/editor_juego.json.
"""
import json
import os
import re

FOLDERS = {'mh1': 'Making History The Calm and The Storm', 'gold': 'Making History Gold'}


def _steam_libraries():
    """Carpetas «steamapps\\common» donde puede estar el juego: MH_STEAM_COMMON (variable de entorno, una o varias
    separadas por ;), la instalación de Steam (registro de Windows) y todas sus bibliotecas (libraryfolders.vdf)."""
    out = [x for x in os.environ.get('MH_STEAM_COMMON', '').split(';') if x.strip()]
    roots = []
    try:
        import winreg
        for hive, key, val in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                               (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath')):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(winreg.QueryValueEx(k, val)[0])
            except OSError:
                pass
    except ImportError:
        pass
    roots += [r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam']
    for r in roots:
        r = os.path.normpath(r)
        out.append(os.path.join(r, 'steamapps', 'common'))
        try:
            for m in re.finditer(r'"path"\s+"([^"]+)"', open(os.path.join(r, 'steamapps', 'libraryfolders.vdf'), encoding='utf-8', errors='replace').read()):
                out.append(os.path.join(os.path.normpath(m.group(1).replace('\\\\', '\\')), 'steamapps', 'common'))
        except OSError:
            pass
    seen, res = set(), []
    for x in out:
        if os.path.normcase(x) not in seen:
            seen.add(os.path.normcase(x)); res.append(x)
    return res


def _find(key):
    for lib in _steam_libraries():
        p = os.path.join(lib, FOLDERS[key])
        if os.path.isdir(os.path.join(p, 'Modern Europe')):
            return p
    return os.path.join(r'C:\Program Files (x86)\Steam\steamapps\common', FOLDERS[key])   # no instalado


STEAM = os.path.dirname(_find('mh1'))
GAMES = {
    'mh1': {'label': 'Making History: The Calm and The Storm (MH1)', 'short': 'MH1', 'path': _find('mh1')},
    'gold': {'label': 'Making History Gold', 'short': 'Gold', 'path': _find('gold')},
}
HERE = os.path.dirname(os.path.abspath(__file__))
# carpeta de datos (proyectos, respaldos, registros): MH_ROOT si la define el ejecutable MHEditor.exe; si no, making-history/
ROOT = os.path.abspath(os.environ.get('MH_ROOT') or os.path.join(HERE, '..'))
CHOICE = os.path.join(ROOT, 'editor_juego.json')
CURRENT = ['mh1']


def installed(key):
    return os.path.isdir(os.path.join(GAMES[key]['path'], 'Modern Europe', 'system', 'scenarios'))


def path(key=None):
    return GAMES[key or CURRENT[0]]['path']


def scen_root(key=None):
    return os.path.join(path(key), 'Modern Europe', 'system', 'scenarios')


def maps_dir(key=None):
    return os.path.join(path(key), 'Modern Europe', 'system', 'DisplayLibraries', 'Maps')


def defaults_dir(key=None):
    return os.path.join(path(key), 'Modern Europe', 'system', 'ScenarioDefaults')


def backup_root(key=None):
    """Respaldos de los archivos que tocan los editores: backup/ para MH1 (como siempre), backup/gold/ para Gold."""
    key = key or CURRENT[0]
    return os.path.join(ROOT, 'backup') if key == 'mh1' else os.path.join(ROOT, 'backup', key)


def map_backup(key=None):
    return os.path.join(backup_root(key), 'mapa_original')


def project_base(base, key=None):
    """Carpeta del proyecto del editor de mapa: editor_proyecto (MH1) o editor_proyecto_gold."""
    key = key or CURRENT[0]
    return base if key == 'mh1' else base + '_' + key


def detect(game_dir):
    """'mh1', 'gold' o None segun la carpeta (para escenarios sueltos: mira si esta dentro de una instalacion)."""
    p = os.path.abspath(game_dir).lower()
    for k, g in GAMES.items():
        if p.startswith(os.path.abspath(g['path']).lower()):
            return k
    return None


def info():
    return {'current': CURRENT[0],
            'games': [{'key': k, 'label': g['label'], 'short': g['short'], 'path': g['path'], 'installed': installed(k)}
                      for k, g in GAMES.items()]}


def load_choice():
    try:
        k = json.load(open(CHOICE)).get('game')
        if k in GAMES and installed(k):
            return k
    except (OSError, ValueError):
        pass
    return 'mh1'


def select(key, remember=True):
    """Apunta todos los modulos a la carpeta del juego elegido."""
    if key not in GAMES:
        raise ValueError('juego desconocido: %s' % key)
    if not installed(key):
        raise ValueError('no está instalado: %s' % GAMES[key]['path'])
    CURRENT[0] = key
    g = path(key)
    import editor_core
    import file_identify
    import scenario_core
    editor_core.GAME = g
    editor_core.MAPS = maps_dir(key)
    editor_core.MAP_DIR = os.path.join(editor_core.MAPS, 'World')
    editor_core.SCEN_DIR = scen_root(key)
    scenario_core.GAME = g
    scenario_core.SCEN_ROOT = scen_root(key)
    scenario_core.BACKUP_ROOT = backup_root(key)
    file_identify.GAME = g
    import sys
    if 'image_tools' in sys.modules:
        sys.modules['image_tools'].CONTENT_UI = os.path.join(g, 'Modern Europe', 'system', 'UI')
    if remember:
        try:
            json.dump({'game': key}, open(CHOICE, 'w'))
        except OSError:
            pass
    return key
