"""Escala de los modelos 3D (fScale) de ciudades, recursos y unidades.

Los Sprite con fScale están en Modern Europe/system/DisplayLibraries/SpriteLibraries/: World.xml (ciudades, recursos,
iconos) y SpriteLibLandUnits / SpriteLibAirUnits / SpriteLibSeaUnits.xml (unidades). Son archivos del juego (valen para
todos los escenarios): los cambios quedan en memoria y solo se escriben con «Guardar en el juego», que anota en
sprite_scales_changelog.json (carpeta de datos del editor) los valores de antes y de después; «Deshacer» vuelve a los de antes.
Si el escenario trae sus propios SpriteLib*.xml en su DisplayLibraries, esos son del escenario y se guardan con «Guardar escenario».
"""
import json
import os
import time

import gamepaths
import scenario_core as sc
from scenario_core import prop

FILES = ('World.xml', 'SpriteLibLandUnits.xml', 'SpriteLibAirUnits.xml', 'SpriteLibSeaUnits.xml')
KIND = {'World.xml': 'ciudades, recursos e iconos', 'SpriteLibLandUnits.xml': 'unidades de tierra', 'SpriteLibAirUnits.xml': 'unidades aéreas',
        'SpriteLibSeaUnits.xml': 'unidades navales'}


def game_dir():
    return os.path.join(sc.GAME, 'Modern Europe', 'system', 'DisplayLibraries', 'SpriteLibraries')


def _log_path():
    return os.path.join(gamepaths.ROOT, 'sprite_scales_changelog.json')


def _paths(s=None):
    out = [(os.path.abspath(os.path.join(game_dir(), f)), 'game') for f in FILES if os.path.exists(os.path.join(game_dir(), f))]
    if s is not None:      # SpriteLib*.xml propios del escenario (DisplayLibraries del escenario)
        out += [(p, 'scenario') for p in s.paths if os.path.basename(p).startswith('SpriteLib') and os.path.basename(p) != 'SpriteLibraries.xml']
    return out


def sprites(s=None):
    st = sc.STORE
    rows = []
    for path, where in _paths(s):
        root = st.open(path).getroot()
        for e in root.iter('object'):
            if e.get('type') == 'Sprite' and prop(e, 'fScale') is not None:
                rows.append({'id': st.eid(e), 'name': prop(e, 'strName') or '', 'scale': prop(e, 'fScale'), 'file': os.path.basename(path),
                             'kind': KIND.get(os.path.basename(path), 'unidades'), 'where': where, 'dirty': path in st.dirty})
    pending = sorted({os.path.basename(p) for p, w in _paths(s) if w == 'game' and p in st.dirty})
    return {'sprites': rows, 'pending': pending, 'can_undo': bool(_read_log()), 'dir': game_dir()}


def set_scales(values):
    """values: {id: fScale}. Solo en memoria."""
    st = sc.STORE
    n = 0
    for i, v in values.items():
        f = float(v)
        if not 0 < f < 100:
            raise ValueError('escala no válida: %s' % v)
        el = st.get(int(i))
        if el.get('type') != 'Sprite':
            raise ValueError('no es un Sprite')
        txt = ('%.6f' % f).rstrip('0').rstrip('.')
        if prop(el, 'fScale') != txt:
            st.set_prop(el, 'fScale', txt)
            n += 1
    return ['%d escala(s) cambiadas (en memoria)' % n]


def _read_log():
    try:
        return json.load(open(_log_path(), encoding='utf-8'))
    except (OSError, ValueError):
        return []


def save_game():
    """Escribe los SpriteLibraries del juego cambiados y anota el cambio (para «Deshacer»)."""
    st = sc.STORE
    paths = [p for p, w in _paths() if p in st.dirty]
    if not paths:
        return ['no hay cambios de escala sin guardar']
    changes = []
    for p in paths:
        on_disk = {}
        tree = sc.parse(p)
        for e in tree.getroot().iter('object'):
            if e.get('type') == 'Sprite' and prop(e, 'fScale') is not None:
                on_disk[prop(e, 'strName')] = prop(e, 'fScale')
        for e in st.docs[p].getroot().iter('object'):
            if e.get('type') == 'Sprite' and prop(e, 'fScale') is not None and on_disk.get(prop(e, 'strName')) not in (None, prop(e, 'fScale')):
                changes.append({'file': os.path.basename(p), 'sprite': prop(e, 'strName'), 'old': on_disk[prop(e, 'strName')], 'new': prop(e, 'fScale')})
    r = st.save(paths)
    log = _read_log()
    log.append({'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'game': gamepaths.CURRENT[0] if gamepaths.CURRENT else '', 'dir': game_dir(), 'changes': changes})
    with open(_log_path(), 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    return ['guardado en el juego: %s (%d escala(s); anotado para deshacer)' % (', '.join(r['written']), len(changes))]


def undo_last():
    """Vuelve a los valores de antes del último «Guardar en el juego» y lo escribe."""
    st = sc.STORE
    log = _read_log()
    if not log:
        raise ValueError('no hay cambios de escala guardados que deshacer')
    last = log[-1]
    if os.path.normcase(last.get('dir', '')) != os.path.normcase(game_dir()):
        raise ValueError('el último cambio es de otro juego (%s): cambia de juego para deshacerlo' % last.get('dir'))
    by_file = {}
    for c in last['changes']:
        by_file.setdefault(c['file'], {})[c['sprite']] = c['old']
    paths = []
    for f, olds in by_file.items():
        p = os.path.abspath(os.path.join(game_dir(), f))
        if p in st.dirty:
            raise ValueError('%s tiene cambios sin guardar: guárdalos o descártalos antes de deshacer' % f)
        st.revert([p])
        root = st.open(p).getroot()
        for e in root.iter('object'):
            if e.get('type') == 'Sprite' and prop(e, 'strName') in olds:
                st.set_prop(e, 'fScale', olds[prop(e, 'strName')])
        paths.append(p)
    st.save(paths)
    log.pop()
    with open(_log_path(), 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    return ['deshecho el cambio del %s (%d escala(s) vuelven a su valor)' % (last['time'], len(last['changes']))]


def discard():
    st = sc.STORE
    paths = [p for p, w in _paths() if p in st.dirty]
    st.revert(paths)
    return ['descartados los cambios de escala sin guardar' if paths else 'no había cambios de escala sin guardar']
