"""Game folder the editors work with: Making History: The Calm and The Storm (MH1) or Making History Gold.

The editor_core, scenario_core and file_identify modules read their paths (GAME, MAPS, SCEN_DIR, SCEN_ROOT...) as
module variables on each call; select() rewrites them all at once. The choice is remembered in
making-history/editor_juego.json.
"""
import json
import os
import re

FOLDERS = {'mh1': 'Making History The Calm and The Storm', 'gold': 'Making History Gold'}


def _steam_libraries():
    """«steamapps\\common» folders where the game may be: MH_STEAM_COMMON (environment variable, one or several
    separated by ;), the Steam install (Windows registry) and all its libraries (libraryfolders.vdf)."""
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


# non-Steam installs (Muzzy Lane installer): MH_GAME_<MH1|GOLD> in the environment or the usual folders
RETAIL = {'mh1': ['Making History 1.0', 'Making History', 'Making History The Calm and The Storm'], 'gold': ['Making History Gold']}


def _retail(key):
    out = [os.environ.get('MH_GAME_' + key.upper(), '')]
    for pf in (os.environ.get('ProgramFiles(x86)') or r'C:\Program Files (x86)', os.environ.get('ProgramFiles') or r'C:\Program Files'):
        out += [os.path.join(pf, 'Muzzy Lane Software', f) for f in RETAIL[key]] + [os.path.join(pf, 'Muzzy Lane', f) for f in RETAIL[key]]
    return [x for x in out if x]


REG_KEYS = {'mh1': 'Making History 2.0', 'gold': 'Making History Gold'}


def _registry(key):
    """Install folders the game itself recorded: its Options/Output Files folders sit inside the install
    (Gold, also without Steam); MH1 retail points them to ProgramData, which is then skipped by the caller."""
    out = []
    try:
        import winreg
    except ImportError:
        return out
    sub = r'Muzzy Lane Software' + '\\' + REG_KEYS[key]
    for hive, base in ((winreg.HKEY_CURRENT_USER, r'Software'), (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node'),
                       (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE'),
                       (winreg.HKEY_CURRENT_USER, r'Software\Classes\VirtualStore\MACHINE\SOFTWARE\WOW6432Node')):
        try:
            with winreg.OpenKey(hive, base + '\\' + sub) as k:
                for v in ('InstallPath', 'InstallDir', 'Path', 'OptionsDirectory', 'OutputFilesDirectory', 'PlayerProfilesDirectory'):
                    try:
                        p = os.path.normpath(winreg.QueryValueEx(k, v)[0].rstrip('\\/'))
                    except OSError:
                        continue
                    out += [p, os.path.dirname(p)]
        except OSError:
            pass
    return out


def _drives():
    import string
    return [d + ':\\' for d in string.ascii_uppercase if os.path.isdir(d + ':\\')]


def _drive_scan(key):
    """Usual places on every drive (external disks included), with and without Steam."""
    names = list(dict.fromkeys([FOLDERS[key]] + RETAIL[key]))
    out = []
    for d in _drives():
        for lib in ('SteamLibrary', 'Steam', r'Program Files (x86)\Steam', r'Program Files\Steam', r'Games\Steam', r'Games\SteamLibrary'):
            out.append(os.path.join(d, lib, 'steamapps', 'common', FOLDERS[key]))
        for parent in ('', 'Games', 'Juegos', r'Program Files (x86)', 'Program Files', r'Program Files (x86)\Muzzy Lane Software',
                       r'Program Files\Muzzy Lane Software', 'Muzzy Lane Software', r'Games\Muzzy Lane Software'):
            out += [os.path.join(d, parent, n) for n in names]
    return out


def _ok(p):
    return bool(p) and os.path.isdir(os.path.join(p, 'Modern Europe', 'system', 'scenarios'))


def _find(key):
    """The chosen folder (editor_juego.json), MH_GAME_*, Steam libraries, the game's registry entries, the Muzzy Lane
    installer folders and, last, the usual folders on every drive."""
    cands = [_saved_paths().get(key)] + [os.environ.get('MH_GAME_' + key.upper(), '')]
    cands += [os.path.join(lib, FOLDERS[key]) for lib in _steam_libraries()] + _registry(key) + _retail(key)
    for p in cands:
        if _ok(p):
            return os.path.normpath(p)
    for p in _drive_scan(key):
        if _ok(p):
            return os.path.normpath(p)
    return os.path.join(r'C:\Program Files (x86)\Steam\steamapps\common', FOLDERS[key])   # not installed


HERE = os.path.dirname(os.path.abspath(__file__))
# data folder (projects, backups, logs): MH_ROOT if the MHEditor.exe executable defines it; otherwise making-history/
ROOT = os.path.abspath(os.environ.get('MH_ROOT') or os.path.join(HERE, '..'))
CHOICE = os.path.join(ROOT, 'editor_juego.json')


def _choice_file():
    try:
        d = json.load(open(CHOICE))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _saved_paths():
    return _choice_file().get('paths') or {}


def _save_choice(**kw):
    d = _choice_file()
    d.update(kw)
    try:
        json.dump(d, open(CHOICE, 'w'))
    except OSError:
        pass


STEAM = os.path.dirname(_find('mh1'))
GAMES = {
    'mh1': {'label': 'Making History: The Calm and The Storm (MH1)', 'short': 'MH1', 'path': _find('mh1')},
    'gold': {'label': 'Making History Gold', 'short': 'Gold', 'path': _find('gold')},
}
CURRENT = ['mh1']


def sww_path():
    """Making History: The Second World War (MH2 engine, not an editor target, so not in GAMES): MH_GAME_SWW or the
    Steam libraries."""
    for p in [os.environ.get('MH_GAME_SWW', '')] + [os.path.join(lib, 'Making History SWW') for lib in _steam_libraries()]:
        if p and os.path.isfile(os.path.join(p, 'MHSWW.exe')):
            return os.path.normpath(p)
    return None


def set_path(key, folder):
    """The user points to the game folder by hand (e.g. on an external disk). Accepts the install folder or its
    «Modern Europe» subfolder; remembered in editor_juego.json."""
    if key not in GAMES:
        raise ValueError('juego desconocido: %s' % key)
    p = os.path.normpath((folder or '').strip().strip('"'))
    if os.path.basename(p).lower() == 'modern europe':
        p = os.path.dirname(p)
    if not _ok(p):
        raise ValueError('esa carpeta no tiene Modern Europe\\system\\scenarios: %s' % p)
    GAMES[key]['path'] = p
    _save_choice(paths={**_saved_paths(), key: p})
    return info()


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
    """Backups of the files the editors touch: backup/ for MH1 (as always), backup/gold/ for Gold."""
    key = key or CURRENT[0]
    return os.path.join(ROOT, 'backup') if key == 'mh1' else os.path.join(ROOT, 'backup', key)


def map_backup(key=None):
    return os.path.join(backup_root(key), 'mapa_original')


def project_base(base, key=None):
    """Map editor project folder: editor_proyecto (MH1) or editor_proyecto_gold."""
    key = key or CURRENT[0]
    return base if key == 'mh1' else base + '_' + key


def detect(game_dir):
    """'mh1', 'gold' or None depending on the folder (for loose scenarios: checks whether it is inside an install)."""
    p = os.path.abspath(game_dir).lower()
    for k, g in GAMES.items():
        if p.startswith(os.path.abspath(g['path']).lower()):
            return k
    return None


GOLD_ONLY_UNITS = ('MotorizedInfantry2', 'MotorizedInfantry3', 'MechanizedInfantry2', 'MechanizedInfantry3',
                   'EarlyBombers', 'EarlyCruiser', 'EarlySubmarine')


def scenario_game(scen_dir):
    """Is the scenario MH1 or Gold? Looks at its content before the folder it is installed in.

    Criteria, in order:
      1. Its own sharedDataUnitTemplates.xml: Gold if its units have nLandDefenseHitPercent (a property only
         the Gold engine reads) or it has Gold-exclusive units (MotorizedInfantry2/3, MechanizedInfantry2/3,
         EarlyBombers, EarlyCruiser, EarlySubmarine); MH1 if it has neither.
      2. Without its own file, uses the default templates of the game it is in: it belongs to that game.
    Returns {'game', 'installed_in', 'mismatch', 'reasons'}; mismatch = installed in the other game (needs converting)."""
    import re
    inst = detect(scen_dir)
    reasons = []
    game = None
    f = os.path.join(scen_dir, 'sharedDataUnitTemplates.xml')
    if os.path.exists(f):
        t = open(f, encoding='utf-8', errors='replace').read()
        names = set(re.findall(r'name="strName" value="([^"]*)"', t))
        gold_units = [u for u in GOLD_ONLY_UNITS if u in names]
        if 'nLandDefenseHitPercent' in t:
            reasons.append('sus unidades tienen nLandDefenseHitPercent (defensa terrestre de Gold)')
        if gold_units:
            reasons.append('trae unidades de Gold: ' + ', '.join(gold_units))
        game = 'gold' if reasons else 'mh1'
        if not reasons:
            reasons.append('sus plantillas de unidades no tienen nada de Gold (ni defensa terrestre ni unidades nuevas)')
    else:
        game = inst
        if inst:
            reasons.append('usa las plantillas de unidades por defecto de %s' % GAMES[inst]['short'])
    return {'game': game, 'installed_in': inst, 'mismatch': bool(game and inst and game != inst), 'reasons': reasons}


def info():
    return {'current': CURRENT[0],
            'games': [{'key': k, 'label': g['label'], 'short': g['short'], 'path': g['path'], 'installed': installed(k)}
                      for k, g in GAMES.items()]}


def load_choice():
    k = _choice_file().get('game')
    if k in GAMES and installed(k):
        return k
    return 'mh1'


def select(key, remember=True):
    """Points all modules to the chosen game's folder."""
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
        _save_choice(game=key)      # keeps the folders chosen by hand
    return key
