"""Unidades e investigaciones sin imagen válida y su arreglo con el arte por defecto del juego.

Plantilla de unidad: entrada en ui/UnitTemplateIconTable.xml (clave strTemplate, 4 medidas) cuyo archivo exista.
Investigación: entrada strIconName en la librería Research_Project_Icon de ui/MediaPack.xml cuyo archivo exista.
Sin escenario ui/ propio se usan las tablas de Modern Europe/system/UI. El «por defecto» es la imagen de la unidad
base de la misma familia (ImprovedMotorizedInfantry -> MotorizedInfantry) o, si no hay, un dibujo del juego por
palabras clave (artillería, bombardero, submarino...)."""
import os
import re
import shutil
import time

from scenario_core import GAME

UI = os.path.join(GAME, 'Modern Europe', 'system', 'UI')
SIZES = ('6464', '4646', '3636', '2626')
UNIT_DIR = '/../Modern Europe/system/ui/art/2D/global/unit-template-icons/'
RES_DIR = '/../Modern Europe/system/ui/art/2D/MediaPack/Research/'
PREFIX = re.compile(r'^(Early|Improved|Advanced|Modern|Basic|PreWar)')
# familia sin nombre base propio: candidatas por nivel (Early, Improved, Advanced, Modern)
ALIAS = {'Infantry': (('PreWarInfantry',), ('SmallArmsInfantry', 'ImprovedSmallArms'), ('AdvancedWeaponsInfantry', 'AdvancedWeapons'),
                      ('AdvancedWeaponsInfantry', 'AdvancedWeapons')),
         'Tank': (('LightTank', 'LightTanks'), ('MediumTank', 'MediumTanks'), ('AdvancedTank', 'AdvancedTanks'), ('AdvancedTank', 'AdvancedTanks')),
         'Fighters': (('PreWarFighters',), ('ImprovedFighters',), ('AdvancedFighters',), ('AdvancedFighters',)),
         'Bombers': (('LightBombers',), ('MediumBombers',), ('HeavyBombers',), ('HeavyBombers',))}
TIERS = ('Early', 'Improved', 'Advanced', 'Modern')
# (palabras del nombre, icono de unidad, dibujo de investigación): la primera que encaje
KEYWORDS = [
    (('intercontinental', 'iam', 'icbm'), 'ICBM.tga', 'icbm.tga'),
    (('missile', 'iram', 'rocketlab'), 'ballistic-missile.tga', 'balistic-missiles.tga'),
    (('selfpropelled',), 'Self-Propelled.tga', 'self-propelled-artillery.tga'),
    (('rocketartillery',), 'Rocket-Artillery.tga', 'rocket-artillery.tga'),
    (('88mm',), 'Heavy-Artillery.tga', '88mm-gun.tga'),
    (('40mm',), 'Light-Artillery.tga', '40mm-gun.tga'),
    (('artillery',), 'Field-Artillery.tga', 'field-artillery.tga'),
    (('mechan',), 'Mechanized.tga', 'mechonized.tga'),
    (('motor',), 'Motorized.tga', 'motorized.tga'),
    (('cavalry', 'lancer', 'mounted'), 'Cavalry.tga', 'mounted.tga'),
    (('assault',), 'advanced-infantry.tga', 'advanced-weapons.tga'),
    (('partisan', 'militia', 'conscript'), 'conscript-infantry.tga', 'militia-infantry.tga'),
    (('infantry',), 'basic-infantry.tga', 'pre-war-infantry.tga'),
    (('proto', 'earlytank'), 'Early-Tank.tga', 'early-tank.tga'),
    (('heavytank',), 'Heavy-Tank.tga', 'heavy-tank.tga'),
    (('tank',), 'Medium-Tank.tga', 'medium-tank.tga'),
    (('atomicbomber',), 'atomic-bomber.tga', 'strategic-bomber.tga'),
    (('strategicbomber',), 'strategic-bomber.tga', 'strategic-bomber.tga'),
    (('heavybomber',), 'Heavy-Bomber.tga', 'heavy-bomber.tga'),
    (('lightbomber', 'attack'), 'Light-Bomber.tga', 'light-bomber.tga'),
    (('bomber',), 'Medium-Bomber.tga', 'medium-bomber.tga'),
    (('jet',), 'Jet-Fighter.tga', 'jet-fighter.tga'),
    (('carrierfighter',), 'Improved-Carrier-Fighter-Default.tga', 'improved-carrier-fighter.tga'),
    (('fighter',), 'Improved-Fighter.tga', 'improved-fighter.tga'),
    (('submarine',), 'basic-submarine.tga', 'basic-submarine.tga'),
    (('carrier', 'tender'), 'light-carrier.tga', 'light-carrier.tga'),
    (('battlecruiser',), 'battle-cruiser.tga', 'battle-cruiser.tga'),
    (('heavycruiser',), 'heavy-cruiser.tga', 'heavy-cruiser.tga'),
    (('cruiser',), 'light-cruiser.tga', 'cruiser.tga'),
    (('battleship',), 'basic-battleship.tga', 'battleship.tga'),
    (('destroyer',), 'destroyer.tga', 'destroyer.tga'),
    (('corvette',), 'corvette.tga', 'corvette-destroyer.tga'),
    (('radar',), None, 'advanced-radar.tga'),
    (('sonar',), None, 'advanced-sonar.tga'),
    (('transport',), 'transport-default.tga', None),
]


def _read(p):
    with open(p, 'rb') as f:
        return f.read().decode('utf-8', 'replace')


def _exists(scen, path):
    """El juego busca primero en <escenario>/ui y luego en el contenido."""
    p = path.replace('\\', '/')
    if p.startswith('/../'):
        rel = p[4:]
        low = rel.lower()
        cands = [os.path.join(GAME, rel)]
        if low.startswith('modern europe/system/ui/'):
            cands.insert(0, os.path.join(scen, 'ui', rel[len('modern europe/system/ui/'):]))
    else:
        cands = [os.path.normpath(os.path.join(scen, 'ui', p.lstrip('/')))]
    return any(os.path.isfile(c) for c in cands)


def _tables(scen):
    own = os.path.join(scen, 'ui', 'UnitTemplateIconTable.xml'), os.path.join(scen, 'ui', 'MediaPack.xml')
    van = os.path.join(UI, 'UnitTemplateIconTable.xml'), os.path.join(UI, 'MediaPack.xml')
    return [o if os.path.exists(o) else v for o, v in zip(own, van)], van


def _unit_entries(text):
    """{plantilla: {medida: ruta}}"""
    out = {}
    for m in re.finditer(r'strTemplate" value="([^"]*)"(.*?)</object>\s*</object>', text, re.S):
        out[m.group(1)] = dict(re.findall(r'fileIcon(\d{4})" value="([^"]*)"', m.group(2)))
    return out


def _research_lib(text):
    i = text.find('"Research_Project_Icon"')
    if i < 0:
        return {}, -1
    seg, out, end = text[i:], {}, -1
    for m in re.finditer(r'\s*(?:<!--.*?-->\s*)*<object type="MediaFile"[^>]*>\s*<property name="strName" value="([^"]*)"/>\s*'
                         r'<property name="filePath" value="([^"]*)"/>\s*</object>', seg, re.S):
        if end >= 0 and m.start() != end - i:
            break
        out[m.group(1)] = m.group(2)
        end = i + m.end()
    return out, end


def _templates(scen):
    names = []
    for f in sorted(os.listdir(scen)):
        if f.startswith('sharedData') and f.endswith('.xml'):
            names += re.findall(r'type="UnitTemplate" name="[^"]*">\s*<property name="strName" value="([^"]*)"', _read(os.path.join(scen, f)))
    return list(dict.fromkeys(names))


def _research_icons(scen):
    f = os.path.join(scen, 'sharedDataResearch.xml')
    if not os.path.exists(f):
        f = os.path.join(GAME, 'Modern Europe', 'system', 'ScenarioDefaults', 'sharedDataResearch.xml')
    return list(dict.fromkeys(re.findall(r'strIconName" value="([^"]*)"', _read(f)))) if os.path.exists(f) else []


def _bases(name, research):
    b = re.sub(r'\d+$', '', PREFIX.sub('', name))
    a = ALIAS.get(b) or ALIAS.get(b + 's') or ALIAS.get(b.rstrip('s'))
    out = []
    if a:
        t = next((i for i, x in enumerate(TIERS) if name.startswith(x)), 1)
        for i in [t] + [j for j in range(len(a)) if j != t]:
            for x in a[i]:
                out += [x, x + 's', x.rstrip('s')]
    out += [b, b + 's', b.rstrip('s')]
    return [x for x in out if x and x != name]


def _keyword(name, research):
    low = re.sub(r'[^a-z0-9]', '', name.lower())
    for words, unit, res in KEYWORDS:
        if any(w in low for w in words):
            return res if research else unit
    return None


def analyze(scen):
    """Lista de problemas: {'kind': 'unit'|'research', 'key', 'reason', 'default': (fuente, rutas) o None}."""
    (ut, mp), (vut, vmp) = _tables(scen)
    units, vunits = _unit_entries(_read(ut)), _unit_entries(_read(vut))
    res, _ = _research_lib(_read(mp))
    vres, _ = _research_lib(_read(vmp))
    ok_u = lambda e: e and all(_exists(scen, e[s]) for s in SIZES if s in e) and '6464' in e
    out = []
    for t in _templates(scen):
        e = units.get(t)
        if ok_u(e):
            continue
        d = None
        for b in _bases(t, False):
            for src in (units, vunits):
                if ok_u(src.get(b)):
                    d = (b, {s: src[b].get(s, src[b]['6464']) for s in SIZES})
                    break
            if d:
                break
        if not d:
            k = _keyword(t, False)
            if k and _exists(scen, UNIT_DIR + '6464/' + k):
                d = (k, {s: UNIT_DIR + s + '/' + (k if _exists(scen, UNIT_DIR + s + '/' + k) else k) for s in SIZES})
        out.append({'kind': 'unit', 'key': t, 'reason': 'sin entrada' if e is None else 'archivo que no existe', 'default': d})
    for r in _research_icons(scen):
        p = res.get(r)
        if p and _exists(scen, p):
            continue
        d = None
        for b in _bases(r, True):
            for src in (res, vres):
                if src.get(b) and _exists(scen, src[b]) and not src[b].endswith('invisible.tga'):
                    d = (b, src[b])
                    break
            if d:
                break
        if not d:
            k = _keyword(r, True)
            if k and _exists(scen, RES_DIR + k):
                d = (k, RES_DIR + k)
        out.append({'kind': 'research', 'key': r, 'reason': 'sin entrada' if p is None else 'archivo que no existe', 'default': d})
    return out


def _unit_block(key, paths, indent='\t\t'):
    i = indent
    rows = ''.join('%s\t\t<property name="fileIcon%s" value="%s"/>\n' % (i, s, paths[s]) for s in SIZES)
    return ('%s<object type="UnitTemplateIcon" name="objUnitTemplateIcons">\n%s\t<property name="strTemplate" value="%s"/>\n'
            '%s\t<object type="UnitTemplateFactoryOutputIconPaths" name="objIconPaths">\n%s%s\t</object>\n%s</object>\n') % (i, i, key, i, rows, i, i)


def fix(scen, keys=None, backup_dir=None, writer=None, log=print):
    """Aplica el arte por defecto a los problemas de analyze (todos o los de 'keys': [(kind, key)]).
    Escribe ui/UnitTemplateIconTable.xml y ui/MediaPack.xml del escenario (los crea copiando los del juego si
    faltan). backup_dir: carpeta donde copiar antes los originales; writer({ruta: bytes}) escribe en su lugar. Devuelve la lista de cambios."""
    probs = [p for p in analyze(scen) if p['default'] and (keys is None or (p['kind'], p['key']) in keys)]
    if not probs:
        return []
    (ut, mp), _ = _tables(scen)
    dst = {'unit': os.path.join(scen, 'ui', 'UnitTemplateIconTable.xml'), 'research': os.path.join(scen, 'ui', 'MediaPack.xml')}
    src = {'unit': ut, 'research': mp}
    done, files = [], {}
    for kind in ('unit', 'research'):
        mine = [p for p in probs if p['kind'] == kind]
        if not mine:
            continue
        raw = open(src[kind], 'rb').read()
        crlf = b'\r\n' in raw[:4000]
        text = raw.decode('utf-8').replace('\r\n', '\n')
        add = ''
        for p in mine:
            b, paths = p['default']
            if kind == 'unit':
                m = re.search(r'(<object type="UnitTemplateIcon"[^>]*>\s*<property name="strTemplate" value="%s"/>.*?</object>\s*</object>)' % re.escape(p['key']), text, re.S)
                if m:
                    blk = m.group(1)
                    for s in SIZES:
                        blk, n = re.subn(r'(fileIcon%s" value=")[^"]*' % s, lambda q: q.group(1) + paths[s], blk)
                        if not n:
                            blk = blk.replace('</object>', '\t<property name="fileIcon%s" value="%s"/>\n\t\t\t</object>' % (s, paths[s]), 1)
                    text = text[:m.start(1)] + blk + text[m.end(1):]
                else:
                    add += '\t<!-- %s: por defecto (%s) -->\n' % (p['key'], b) + _unit_block(p['key'], paths)
            else:
                lib, _ = _research_lib(text)
                if p['key'] in lib:
                    text = re.sub(r'(<property name="strName" value="%s"/>\s*<property name="filePath" value=")[^"]*' % re.escape(p['key']),
                                  lambda q: q.group(1) + paths, text, count=1)
                else:
                    add += ('\n\t\t\t<!-- %s: por defecto (%s) -->\n\t\t\t<object type="MediaFile" name="objFiles">\n'
                            '\t\t\t\t<property name="strName" value="%s"/>\n\t\t\t\t<property name="filePath" value="%s"/>\n\t\t\t</object>'
                            % (p['key'], b, p['key'], paths))
            done.append({'kind': kind, 'key': p['key'], 'reason': p['reason'], 'source': b,
                         'file': paths['6464'] if kind == 'unit' else paths})
        if add:
            if kind == 'unit':
                k = text.rfind('</object>', 0, text.rfind('</objects>'))
                text = text[:k] + add + text[k:]
            else:
                _, end = _research_lib(text)
                text = text[:end] + add + text[end:]
        files[dst[kind]] = (text.replace('\n', '\r\n') if crlf else text).encode('utf-8')
        log('%s: %d cambios' % (os.path.basename(dst[kind]), len(mine)))
    if writer:
        writer(files)
        return done
    for path, data in files.items():
        if backup_dir and os.path.exists(path):
            os.makedirs(backup_dir, exist_ok=True)
            shutil.copy2(path, os.path.join(backup_dir, os.path.basename(path)))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
    return done


def issues(scen):
    """Avisos para el validador del editor de escenarios, con el arreglo «Usar la imagen por defecto»."""
    out = []
    for p in analyze(scen):
        what = 'Unidad' if p['kind'] == 'unit' else 'Investigación'
        msg = '%s %s sin imagen válida (%s)' % (what, p['key'], p['reason'])
        fix_ = None
        if p['default']:
            msg += '; por defecto: %s' % p['default'][0]
            fix_ = {'kind': 'icon', 'items': [[p['kind'], p['key']]], 'label': 'Usar la imagen por defecto'}
        out.append({'level': 'aviso', 'id': None, 'msg': msg, 'fix': fix_})
    return out


if __name__ == '__main__':
    import sys
    s = sys.argv[1]
    for p in analyze(s):
        print(p['kind'], p['key'], '|', p['reason'], '->', p['default'] and p['default'][0])
    if '--fix' in sys.argv:
        bk = os.path.join(s, 'ui', '_respaldo_iconos_' + time.strftime('%Y%m%d-%H%M%S'))
        for d in fix(s, backup_dir=bk):
            print('FIX', d)
