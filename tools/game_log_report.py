"""Lee un registro del juego (logs/juego_<fecha>.log, de game_log.py) y dice por qué no se creó la partida.

Cada intento de cargar un escenario empieza cuando el juego añade sus «filename substitution» (…/scenarios/<X>/ui/…) y acaba
en «Created game» (bien) o «Error creating game» (mal). De los intentos fallidos se sacan los mensajes de nivel 1 (errores)
y, si se reconocen, una explicación y qué hacer. Solo lee; no toca nada.
"""
import glob
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(os.environ.get('MH_ROOT') or os.path.join(HERE, '..'), 'logs')

START = re.compile(r'Adding filename substitution "\.\./system/ui/sounds/" -> "\.\./Modern Europe/system/scenarios/([^/]+)/')
NOISE = ('CPropStringID::SetFromString', 'Found no StringID', 'MusicPlayList', 'PlayListLobbies', 'CSoundPack', 'Failed to load texture',
         'that has no game state', 'Listener already built', 'Found second font', 'Initializing program')
# (patrón, explicación, qué hacer) — de los casos ya resueltos (EDITOR.md, «Mapa y escenario a la vez»)
KNOWN = [
    (r'is not valid for a property of type "Enum".*named "eCountryType"',
     'eCountryType con un valor que el juego no tiene (válidos: COUNTRYTYPE_PLAYABLE, _FEATURED, _NON_FEATURED).',
     'Guardar el escenario en el editor lo corrige solo; Validar lo marca.'),
    (r'is not valid for a property of type "StringID"',
     'Un texto (SID) que no existe en ningún stringTable.',
     'Guardar el escenario en el editor crea el texto que falta (sidShortDescription); en otros casos créalo en game/stringTable.xml.'),
    (r'Property "objDipRelInitialValues" is not defined in type "MEPlayerData"',
     'Relaciones diplomáticas fuera de su DipRelInitialValueList: el juego descarta el player*.xml entero.',
     'Guardar el escenario en el editor las mueve a su lista.'),
    (r'is not defined in type',
     'Un objeto o propiedad en un sitio donde el juego no lo admite: descarta el archivo.',
     'Mira el archivo indicado y compáralo con uno del juego.'),
    (r"wasn't a PlayerData named",
     'El país está en gamestate.xml pero su player*.xml no se cargó (falta en game.xml o tiene un error más arriba).',
     'Corrige primero los errores de ese player*.xml.'),
    (r'pre-reqs met|ResearchState|research state|Project \w+ \d+ ResearchProj',
     'Investigaciones completadas al empezar sin sus requisitos (ResearchProjectPreReq sin completar ni bCompletedByDefault).',
     'Guardar el escenario en el editor completa los requisitos que faltan.'),
    (r"Error loading (?:area|scenario) map data for map|Couldn't find area map|primary document entity could not be opened",
     'El regionpack del escenario (strMapName) no está instalado en DisplayLibraries/Maps.',
     'Instala el regionpack o pasa el escenario a otro (Global Data o «Adecuar»).'),
    (r'invalid region ID',
     'Una región del escenario no existe en el mapa de su regionpack.',
     'Usa «Adecuar» en el editor de regiones para que el escenario coincida con el mapa.'),
    (r'Failed to load scenario named',
     'El juego no pudo leer el escenario.',
     'Revisa los errores de archivo anteriores.'),
]
# nombres que se juntan en la lista de un mismo fallo
ITEMS = [r'player named "([^"]+)"', r'for country \d+ (.+?) in \d+', r'Project (\w+) \d+ ResearchProj', r'for map (\w+)']
SKIP = r'InitGame failed|AddGame|CreateGame|failed to execute|InitGameValidation - failed|InitGameOld - Failed'


def latest():
    files = sorted(glob.glob(os.path.join(LOGS, 'juego_*.log')), key=os.path.getmtime)
    return files[-1] if files else None


def _explain(msg):
    for pat, why, todo in KNOWN:
        if re.search(pat, msg):
            return why, todo
    return None, None


def analyze(path=None):
    """{file, attempts: [{scenario, result 'ok'|'error'|None, stage, problems: [{msg, why, todo, files, items, count}]}]}"""
    path = path or latest()
    if not path or not os.path.exists(path):
        return {'file': None, 'attempts': []}
    attempts, cur = [], None

    def new(name):
        a = {'scenario': name, 'result': None, 'problems': [], 'stage': None}
        attempts.append(a)
        return a
    for line in open(path, encoding='utf-8', errors='replace'):
        line = line.rstrip('\n')
        m = START.search(line)
        if m:
            if cur is None or cur['result'] or cur['scenario'] != m.group(1):
                cur = new(m.group(1))
            continue
        if cur is not None and not cur['result']:
            if 'Created game with object ID' in line:
                cur['result'] = 'ok'
                continue
            if 'Error creating game' in line:
                cur['result'] = 'error'
                continue
        msg = line.split('LOG:', 1)[-1].strip()
        lvl = re.match(r'[\w ]+ - (?:Info - )?(\d)::(.*)', msg)
        if not lvl or lvl.group(1) != '1' or any(n in msg for n in NOISE):
            continue
        if cur is None or cur['result']:
            if 'Finished running game loop' in msg or 'failed to execute' in msg:
                continue
            cur = new(None)                # intento sin carpeta ui/: el registro no da el nombre del escenario
        text = lvl.group(2)
        st = re.search(r'failed on (\w+)', text)
        if st and not cur['stage']:
            cur['stage'] = st.group(1)
        if re.search(SKIP, text):
            continue
        fm = re.match(r'(?:Fatal )?Error in file (.+?): (.*)', text)
        f, body = (os.path.basename(fm.group(1)), fm.group(2)) if fm else (None, text)
        why, todo = _explain(text)
        items = [x.group(1) for r in ITEMS for x in [re.search(r, text)] if x]
        key = why or body
        same = next((p for p in cur['problems'] if p['key'] == key), None)
        if same is None:
            same = {'key': key, 'msg': body, 'files': [], 'items': [], 'count': 0, 'why': why, 'todo': todo}
            cur['problems'].append(same)
        same['count'] += 1
        for x, lst in [(f, same['files'])] + [(i, same['items']) for i in items]:
            if x and x not in lst and len(lst) < 60:
                lst.append(x)
    for a in attempts:
        if a['result'] == 'ok':
            a['problems'] = []         # cargó: lo demás son avisos que el juego tolera
        for p in a['problems']:
            p.pop('key')
        a['problems'].sort(key=lambda p: p['why'] is None)
    return {'file': os.path.basename(path), 'attempts': [a for a in attempts if a['result']]}


if __name__ == '__main__':
    import json
    import sys
    print(json.dumps(analyze(sys.argv[1] if len(sys.argv) > 1 else None), ensure_ascii=False, indent=1))
