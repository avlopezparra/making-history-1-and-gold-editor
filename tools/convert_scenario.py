"""Convierte un escenario de Making History entre MH1 (The Calm and The Storm) y Gold, en una copia.

Sigue la guia de janito (https://steamcommunity.com/sharedfiles/filedetails/?id=2134617379) y la amplia:

1. Datos compartidos (sharedData*.xml) y tablas de sprites (DisplayLibraries\\MKD*.xml) del escenario: fusion a tres
   bandas (xmlmerge) entre el archivo por defecto del juego de origen, la copia del escenario y el del destino.
   Resultado: lo del destino (unidades nuevas de Gold, sus investigaciones, producción y sprites, valores de Gold)
   + lo que el autor cambio en su escenario (unidades propias, costes, eventos quitados...).
   Con «solo_unidades» se fusionan unicamente sharedDataUnitTemplates.xml y sharedDataUnitTemplateSprites.xml
   (lo que dice la guia) y las tablas de sprites.
2. Investigacion inicial de cada jugador: si un pais tiene completado un proyecto que en el destino requiere otro
   proyecto nuevo (LightBombers -> EarlyBombers), se marca tambien el nuevo; opcionalmente, los nuevos cuyos
   requisitos ya estan completos (MotorizedInfantry2/3, MechanizedInfantry2/3). Se quitan los proyectos que el
   destino no tiene.
3. Unidades de plantillas que no existen en el destino (de Gold a MH1): se cambian por la equivalente.
4. Partisans: Gold los trae de serie; el evento de MH1 (sharedDataPartisans.xml) se desregistra al pasar a Gold.
5. Colores (opcional): los de Gold son menos saturados. Tabla color a color sacada de los escenarios que existen
   en los dos juegos; si un color no esta en la tabla, aproximacion lineal ajustada a esos pares.
6. Infraestructura (opcional, «auto»): TransportationLevel nCost y nMaintenanceCost / 10 en sharedData.xml si el
   escenario tiene mucha mas poblacion que los del juego y los costes no estan ya rebajados.

Uso: python convert_scenario.py "<carpeta escenario>" --a gold [--salida <carpeta>] [--colores] [--infra auto|si|no]
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gamepaths  # noqa: E402
import xmlmerge  # noqa: E402

UNITS_ONLY = ('sharedDataUnitTemplates.xml', 'sharedDataUnitTemplateSprites.xml')
# plantilla sin equivalente en el destino -> la mas parecida (de Gold a MH1)
FALLBACK = {'MotorizedInfantry2': 'MotorizedInfantry', 'MotorizedInfantry3': 'MotorizedInfantry',
            'MechanizedInfantry2': 'MechanizedInfantry', 'MechanizedInfantry3': 'MechanizedInfantry',
            'EarlyBombers': 'LightBombers', 'EarlyCruiser': 'BattleCruiser', 'EarlySubmarine': 'ElectricDieselSubmarine',
            'Partisans': 'Militia'}
# escenarios oficiales: referencia de colores (los que estan en los dos juegos) y de poblacion (los del juego de destino);
# no se usan los del usuario, que pueden ser conversiones hechas con esta misma herramienta
OFFICIAL_BOTH = ('Conclusion of the War', 'Steps to a Global War', 'The End of Diplomacy', 'The Limits of Peace',
                 'The Politics of Appeasement', 'The World at War', 'Tutorial')
OFFICIAL = {'mh1': OFFICIAL_BOTH, 'gold': OFFICIAL_BOTH + ('Blitzkrieg', 'Clash of Continents', 'Rise of the Reich', 'Southern Star')}
IMAGE_EXT = {'.tga', '.bmp', '.png', '.dds', '.jpg', '.jpeg', '.pdn', '.db'}
POP_FACTOR = 1.5      # «mucha poblacion»: mas de 1,5 veces la del escenario mas poblado del juego de destino


def sys_dir(game):
    return os.path.join(gamepaths.path(game), 'Modern Europe', 'system')


def default_for(rel, game):
    """Archivo por defecto del juego que corresponde a un archivo del escenario (o None)."""
    parts = rel.replace('\\', '/').split('/')
    if len(parts) == 1 and parts[0].lower().startswith('shareddata'):
        return os.path.join(sys_dir(game), 'ScenarioDefaults', parts[0])
    if len(parts) == 2 and parts[0] == 'DisplayLibraries' and parts[1].startswith('MKD'):
        return os.path.join(sys_dir(game), 'DisplayLibraries', 'SpriteMaps', parts[1])
    if len(parts) == 2 and parts[0] == 'game' and parts[1] == 'scenarioDefs.xml':
        return os.path.join(sys_dir(game), 'ScenarioDefaults', 'game', parts[1])
    return None


def read(p):
    return open(p, encoding='utf-8', errors='replace', newline='').read()


def write_text(p, t):
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(t)


# ------------------------------------------------------------------------------------------ investigacion
def research_graph(path):
    """{proyecto: [requisitos]}"""
    g = {}
    for o in ET.parse(path).getroot().iter('object'):
        t = o.get('type', '')
        if t.startswith('ResearchProj') and t != 'ResearchProjectPreReq':
            nm = next((c.get('value') for c in o if c.tag == 'property' and c.get('name') == 'strName'), None)
            if nm:
                g[nm] = [c.get('value') for q in o if q.get('type') == 'ResearchProjectPreReq'
                         for c in q if c.get('name') == 'strProjectName']
    return g


def ancestors(g, names):
    out, stack = set(), list(names)
    while stack:
        for p in g.get(stack.pop(), []):
            if p not in out:
                out.add(p)
                stack.append(p)
    return out


REF_RE = re.compile(r'([ \t]*)<object type="ResearchProjectInitRef"[^>]*>\s*?(?:(?!</object>).)*?</object>[ \t]*\r?\n?', re.S)


def fix_player_research(path, g_dst, g_src, complete_new):
    """Anade los proyectos nuevos implicados y quita los que no existen. Devuelve (anadidos, quitados)."""
    t = read(path)
    blocks = list(REF_RE.finditer(t))
    if not blocks and not complete_new:
        return [], []
    state = {}
    for m in blocks:
        nm = re.search(r'name="strProjectName" value="([^"]*)"', m.group(0))
        st = re.search(r'name="eResearchState" value="([^"]*)"', m.group(0))
        if nm:
            state[nm.group(1)] = st.group(1) if st else ''
    done = {k for k, v in state.items() if v == 'RESEARCH_COMPLETED'}
    removed = [k for k in state if k not in g_dst]
    new_projects = [p for p in g_dst if p not in g_src]
    implied = ancestors(g_dst, done) | done
    add = [p for p in new_projects if p in implied and p not in state]
    if complete_new:
        changed = True
        while changed:
            changed = False
            for p in new_projects:
                if p not in implied and g_dst[p] and all(q in implied for q in g_dst[p]):
                    implied.add(p)
                    add.append(p)
                    changed = True
    add = [p for p in dict.fromkeys(add) if p not in state]
    if not add and not removed:
        return [], []
    nl = '\r\n' if '\r\n' in t[:4000] else '\n'
    for m in reversed(blocks):
        nm = re.search(r'name="strProjectName" value="([^"]*)"', m.group(0))
        if nm and nm.group(1) in removed:
            t = t[:m.start()] + t[m.end():]
    if add:
        blocks = list(REF_RE.finditer(t))
        if blocks:
            ind = blocks[-1].group(1)
            pos = blocks[-1].end()
        else:   # sin investigacion: tras la apertura del objeto raiz del jugador
            m = re.search(r'<object type="MEPlayerData"[^>]*>\r?\n', t) or re.search(r'<object [^>]*>\r?\n', t)
            ind, pos = '\t\t', m.end()
        ins = ''.join('%s<object type="ResearchProjectInitRef" name="objInitResearchRefs">%s%s\t<property name="strProjectName" '
                      'value="%s"/>%s%s\t<property name="eResearchState" value="RESEARCH_COMPLETED"/>%s%s</object>%s'
                      % (ind, nl, ind, p, nl, ind, nl, ind, nl) for p in add)
        t = t[:pos] + ins + t[pos:]
    write_text(path, t)
    return add, removed


# ------------------------------------------------------------------------------------------ colores
def gamestate_colors(scen_dir):
    f = os.path.join(scen_dir, 'gamestate.xml')
    out = {}
    if not os.path.exists(f):
        return out
    for blk in re.split(r'<object type="Player"', read(f))[1:]:
        h = blk.split('</object>')[0]
        n = re.search(r'name="strName" value="([^"]*)"', h)
        c = re.search(r'name="colCountryColor" value="([^"]*)"', h)
        if n and c:
            out[n.group(1)] = c.group(1).upper()
    return out


def color_model(src, dst, exclude=()):
    """(tabla color->color, matriz 4x3 RGB lineal) a partir de los escenarios que existen en los dos juegos."""
    import numpy as np
    pairs = Counter()
    rs, rd = gamepaths.scen_root(src), gamepaths.scen_root(dst)
    for s in OFFICIAL_BOTH:
        if os.path.isdir(os.path.join(rs, s)) and s not in exclude:
            a, b = gamestate_colors(os.path.join(rs, s)), gamestate_colors(os.path.join(rd, s))
            for k in a:
                if k in b:
                    pairs[(a[k], b[k])] += 1
    table = {}
    for (a, b), n in pairs.most_common():
        table.setdefault(a, b)
    rgb = lambda h: [int(h.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
    X = np.array([rgb(a) + [1] for a in table], float)
    Y = np.array([rgb(b) for b in table.values()], float)
    W = np.linalg.lstsq(X, Y, rcond=None)[0] if len(X) >= 4 else None
    return table, W


def map_color(c, table, W):
    c = c.upper()
    if c in table:
        return table[c], 'tabla'
    if W is None:
        return c, None
    h = c.lstrip('#')
    v = [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [1]
    out = [max(0, min(255, int(round(sum(v[j] * W[j][i] for j in range(4)))))) for i in range(3)]
    return '#%02X%02X%02X%s' % (out[0], out[1], out[2], h[6:8] or 'FF'), 'aprox'


def convert_colors(scen_dir, src, dst, exclude=()):
    table, W = color_model(src, dst, exclude)
    f = os.path.join(scen_dir, 'gamestate.xml')
    t = read(f)
    how = Counter()

    def sub(m):
        new, k = map_color(m.group(2), table, W)
        how[k] += 1
        return m.group(1) + new + m.group(3)
    t = re.sub(r'(name="colCountryColor" value=")(#[0-9A-Fa-f]{6,8})(")', sub, t)
    write_text(f, t)
    return dict(how)


# ------------------------------------------------------------------------------------------ poblacion / infraestructura
def total_population(scen_dir):
    tot = 0
    for f in os.listdir(scen_dir):
        if f.startswith('country') and f.endswith('.xml'):
            tot += sum(int(x) for x in re.findall(r'name="nPopulation" value="(\d+)"', read(os.path.join(scen_dir, f))))
    return tot


def transport_levels(path):
    t = read(path)
    out = {}
    for blk in re.split(r'<object type="TransportationLevel"', t)[1:]:
        h = blk.split('</object>')[0]
        lv = re.search(r'name="nLevel" value="(\d+)"', h)
        if lv:
            out[int(lv.group(1))] = {k: int(v) for k, v in re.findall(r'name="(nCost|nMaintenanceCost)" value="(\d+)"', h)}
    return out


def reduce_infra(path, factor=10):
    t = read(path)

    def blk(m):
        return re.sub(r'(name="(?:nCost|nMaintenanceCost)" value=")(\d+)(")',
                      lambda x: x.group(1) + str(int(x.group(2)) // factor) + x.group(3), m.group(0))
    t = re.sub(r'<object type="TransportationLevel".*?</object>', blk, t, flags=re.S)
    write_text(path, t)


# ------------------------------------------------------------------------------------------ conversion
def scenario_files(scen_dir):
    for root, _, files in os.walk(scen_dir):
        for f in files:
            yield os.path.relpath(os.path.join(root, f), scen_dir)


def registered_files(scen_dir):
    sx = os.path.join(scen_dir, 'scenario.xml')
    return re.findall(r'name="fileSharedData" value="([^"]*)"', read(sx)) if os.path.exists(sx) else []


def convert(src_dir, dst_game, out_dir=None, src_game=None, colors=False, infra='auto', units_only=False,
            complete_new=True, remove_partisan_event=True, skip_images=False, log=print):
    src_dir = os.path.abspath(src_dir)
    src_game = src_game or gamepaths.detect(src_dir)
    if src_game is None:
        raise ValueError('no sé de qué juego es el escenario: indica el origen (mh1 o gold)')
    if src_game == dst_game:
        raise ValueError('el escenario ya es de %s' % gamepaths.GAMES[dst_game]['short'])
    for g in (src_game, dst_game):
        if not gamepaths.installed(g):
            raise ValueError('no está instalado %s (%s)' % (gamepaths.GAMES[g]['label'], gamepaths.path(g)))
    name = os.path.basename(src_dir.rstrip('\\/'))
    out_dir = os.path.abspath(out_dir or os.path.join(gamepaths.scen_root(dst_game), name))
    if os.path.exists(out_dir):
        raise ValueError('ya existe %s: elige otra carpeta de salida (no se sobrescribe nada)' % out_dir)
    rep = {'origen': src_dir, 'salida': out_dir, 'de': src_game, 'a': dst_game, 'fecha': time.strftime('%Y-%m-%d %H:%M:%S'),
           'archivos': [], 'notas': [], 'investigacion': {}, 'unidades_cambiadas': {}, 'colores': None, 'infraestructura': None}
    skipped = Counter()

    def ignore(d, names):
        # sin imagenes: no se copian las de las subcarpetas (ui/: banderas, retratos...), solo las del raiz
        # (Title.tga, Button.tga... que usa el menu de escenarios)
        if not skip_images or os.path.abspath(d) == src_dir:
            return []
        out = [n for n in names if os.path.splitext(n)[1].lower() in IMAGE_EXT and os.path.isfile(os.path.join(d, n))]
        for n in out:
            skipped['n'] += 1
            skipped['bytes'] += os.path.getsize(os.path.join(d, n))
        return out
    shutil.copytree(src_dir, out_dir, ignore=ignore)
    if skip_images:
        rep['notas'].append('sin imágenes: se omitieron %d imágenes de las subcarpetas (%.0f MB); el juego usará las suyas por defecto'
                            % (skipped['n'], skipped['bytes'] / 1e6))
    log('copiado a %s' % out_dir)

    # 1. datos compartidos y sprites
    for rel in sorted(scenario_files(out_dir)):
        base, theirs = default_for(rel, src_game), default_for(rel, dst_game)
        if not theirs or not os.path.exists(theirs):
            continue
        if units_only and rel.replace('\\', '/').split('/')[0] != 'DisplayLibraries' and os.path.basename(rel) not in UNITS_ONLY:
            continue
        ours = os.path.join(out_dir, rel)
        cb = xmlmerge.canon(xmlmerge.parse(base).getroot()) if base and os.path.exists(base) else None
        ct = xmlmerge.canon(xmlmerge.parse(theirs).getroot())
        if cb == ct:
            continue       # el archivo por defecto es igual en los dos juegos
        co = xmlmerge.canon(xmlmerge.parse(ours).getroot())
        if co == ct:
            continue       # el escenario ya tiene lo del destino
        if co == cb:
            shutil.copy2(theirs, ours)
            rep['archivos'].append({'archivo': rel, 'accion': 'copiado del destino (el escenario no lo había cambiado)'})
            continue
        tree, notes, stats = xmlmerge.merge_files(base, ours, theirs)
        xmlmerge.write(tree, ours, like=ours)
        rep['archivos'].append({'archivo': rel, 'accion': 'fusionado', 'estadisticas': dict(stats), 'notas': notes})
        log('fusionado %s %s' % (rel, dict(stats)))

    # 2. investigacion de los jugadores
    def research_file(game_or_dir):
        p = os.path.join(game_or_dir, 'sharedDataResearch.xml')
        return p if os.path.exists(p) else None
    r_dst = research_file(out_dir) or os.path.join(sys_dir(dst_game), 'ScenarioDefaults', 'sharedDataResearch.xml')
    r_src = research_file(src_dir) or os.path.join(sys_dir(src_game), 'ScenarioDefaults', 'sharedDataResearch.xml')
    g_dst, g_src = research_graph(r_dst), research_graph(r_src)
    tot_add, tot_rem = Counter(), Counter()
    for f in sorted(os.listdir(out_dir)):
        if f.startswith('player') and f.endswith('.xml'):
            add, rem = fix_player_research(os.path.join(out_dir, f), g_dst, g_src, complete_new)
            tot_add.update(add)
            tot_rem.update(rem)
    rep['investigacion'] = {'anadidos': dict(tot_add), 'quitados': dict(tot_rem)}

    # 3. plantillas de unidades que no existen en el destino
    tf = os.path.join(out_dir, 'sharedDataUnitTemplates.xml')
    if not os.path.exists(tf):
        tf = os.path.join(sys_dir(dst_game), 'ScenarioDefaults', 'sharedDataUnitTemplates.xml')
    templates = {c.get('value') for o in ET.parse(tf).getroot().iter('object') if o.get('type') == 'UnitTemplate'
                 for c in o if c.get('name') == 'strName'}
    changed = Counter()
    for f in os.listdir(out_dir):
        if f.startswith('country') and f.endswith('.xml'):
            p = os.path.join(out_dir, f)
            t = read(p)

            def sub(m):
                blk = m.group(0)
                nm = re.search(r'name="strName" value="([^"]*)"', blk)
                if nm and nm.group(1) not in templates and FALLBACK.get(nm.group(1)) in templates:
                    changed['%s -> %s' % (nm.group(1), FALLBACK[nm.group(1)])] += 1
                    return blk.replace(nm.group(0), 'name="strName" value="%s"' % FALLBACK[nm.group(1)])
                return blk
            t2 = re.sub(r'<object type="UnitSummary".*?</object>', sub, t, flags=re.S)
            if t2 != t:
                write_text(p, t2)
            missing = {x for x in re.findall(r'<object type="UnitSummary"[^>]*>\s*<property name="strName" value="([^"]*)"', t2)
                       if x not in templates}
            for x in missing:
                rep['notas'].append('%s usa la plantilla %s, que no existe en el destino' % (f, x))
    rep['unidades_cambiadas'] = dict(changed)

    # 4. partisans
    sx = os.path.join(out_dir, 'scenario.xml')
    if dst_game == 'gold' and remove_partisan_event and 'sharedDataPartisans.xml' in registered_files(out_dir):
        t = read(sx)
        t2 = re.sub(r'[ \t]*<object type="SharedDataFileRef"[^>]*>(?:(?!</object>).)*?value="sharedDataPartisans\.xml"'
                    r'(?:(?!</object>).)*?</object>[ \t]*\r?\n', '', t, flags=re.S)
        if t2 != t:
            write_text(sx, t2)
            rep['notas'].append('Partisans: Gold los trae de serie (CombatSystemParams); se quitó del scenario.xml el evento de '
                                'MH1 sharedDataPartisans.xml (el archivo se conserva)')
    if dst_game == 'mh1' and not os.path.exists(os.path.join(out_dir, 'sharedDataPartisans.xml')):
        rep['notas'].append('MH1 no tiene partisanos de serie: se pueden activar con el interruptor «Partisans» del editor')

    # 5. colores
    if colors:
        rep['colores'] = convert_colors(out_dir, src_game, dst_game, exclude={name, os.path.basename(out_dir)})

    # 6. infraestructura
    sd = os.path.join(out_dir, 'sharedData.xml')
    pop = total_population(out_dir)
    ref = max([total_population(os.path.join(gamepaths.scen_root(dst_game), s)) for s in OFFICIAL[dst_game]
               if os.path.isdir(os.path.join(gamepaths.scen_root(dst_game), s)) and s != name] or [0])
    info = {'poblacion': pop, 'poblacion_max_juego': ref, 'aplicada': False}
    if os.path.exists(sd):
        cur = transport_levels(sd)
        dflt = transport_levels(os.path.join(sys_dir(dst_game), 'ScenarioDefaults', 'sharedData.xml'))
        already = any(cur.get(lv, {}).get('nMaintenanceCost', 0) * 2 <= d.get('nMaintenanceCost', 0)
                      for lv, d in dflt.items() if d.get('nMaintenanceCost'))
        info.update(antes=cur, ya_rebajados=already)
        do = infra == 'si' or (infra == 'auto' and ref and pop > POP_FACTOR * ref and not already)
        if do:
            reduce_infra(sd)
            info['aplicada'] = True
            info['despues'] = transport_levels(sd)
        elif infra == 'auto':
            info['motivo'] = ('los costes ya están rebajados respecto a %s' % gamepaths.GAMES[dst_game]['short']) if already else \
                             'la población no es mucho mayor que la de los escenarios del juego'
    rep['infraestructura'] = info

    # regionpack
    m = re.search(r'name="strMapName" value="([^"]*)"', read(sx)) if os.path.exists(sx) else None
    if m and not os.path.isdir(os.path.join(gamepaths.maps_dir(dst_game), m.group(1))):
        rep['notas'].append('el regionpack %s no existe en %s: hay que copiarlo (con las texturas de ese juego)'
                            % (m.group(1), gamepaths.GAMES[dst_game]['short']))

    # informe (fuera de la carpeta del escenario)
    d = os.path.join(gamepaths.ROOT, 'backup', 'conversiones')
    os.makedirs(d, exist_ok=True)
    rp = os.path.join(d, '%s - %s a %s - %s.json' % (name, src_game, dst_game, time.strftime('%Y%m%d-%H%M%S')))
    json.dump(rep, open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    rep['informe'] = rp
    return rep


def summary(rep):
    lines = ['%s -> %s' % (rep['origen'], rep['salida'])]
    for a in rep['archivos']:
        lines.append('  %s: %s %s' % (a['archivo'], a['accion'], a.get('estadisticas', '')))
    lines.append('  investigación añadida: %s' % rep['investigacion'].get('anadidos'))
    if rep['investigacion'].get('quitados'):
        lines.append('  investigación quitada: %s' % rep['investigacion']['quitados'])
    if rep['unidades_cambiadas']:
        lines.append('  unidades cambiadas: %s' % rep['unidades_cambiadas'])
    if rep['colores']:
        lines.append('  colores: %s' % rep['colores'])
    i = rep['infraestructura']
    lines.append('  infraestructura: %s (población %s, máx. del juego %s%s)' % (
        'rebajada /10' if i.get('aplicada') else 'sin cambios', i.get('poblacion'), i.get('poblacion_max_juego'),
        ', ' + i['motivo'] if i.get('motivo') else ''))
    for n in rep['notas']:
        lines.append('  nota: ' + n)
    lines.append('  informe: %s' % rep.get('informe'))
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('escenario')
    ap.add_argument('--a', dest='dst', required=True, choices=sorted(gamepaths.GAMES))
    ap.add_argument('--de', dest='src', choices=sorted(gamepaths.GAMES))
    ap.add_argument('--salida')
    ap.add_argument('--colores', action='store_true')
    ap.add_argument('--infra', default='auto', choices=('auto', 'si', 'no'))
    ap.add_argument('--solo-unidades', action='store_true')
    ap.add_argument('--no-completar-nuevas', action='store_true')
    ap.add_argument('--mantener-evento-partisanos', action='store_true')
    ap.add_argument('--sin-imagenes', action='store_true', help='no copiar las imagenes de las subcarpetas (ui/...)')
    a = ap.parse_args()
    rep = convert(a.escenario, a.dst, a.salida, a.src, a.colores, a.infra, a.solo_unidades, not a.no_completar_nuevas,
                  not a.mantener_evento_partisanos, a.sin_imagenes)
    print(summary(rep))


if __name__ == '__main__':
    main()
