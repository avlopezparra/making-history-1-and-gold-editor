"""Escenario desde cero sobre un regionpack nuevo (pocas regiones) y naciones nuevas con su capital.

Diseño (ver EDITOR.md, «Naciones y escenario desde cero»): el escenario nuevo toma de una plantilla (por defecto «Clash of Continents»,
el escenario del juego con pocas naciones; si no está, el que tenga menos países) solo lo que no depende del mapa: sharedData*.xml,
game/, ui/ y scenarioDefs. Todo lo demás se genera aquí vacío: scenario.xml, scenarioInfo.xml, game.xml, gamestate.xml, treaties.xml,
waterWorld.xml (sin mares) y sharedDataHistoricCountries.xml (sin países históricos). Las naciones se añaden después, cada una con
country<Nombre>.xml + player<Nombre>.xml, su Player en gamestate.xml y su entrada en game.xml / scenarioInfo.xml.
Sin imágenes: no se crean Button.tga, ButtonOver.tga, Title.tga ni banderas (se prescinde de ellas).
"""
import os
import re
import shutil
from xml.sax.saxutils import quoteattr

import scenario_core as sc
from scenario_core import prop, objs

BAD_FILE = re.compile(r'[\\/:*?"<>|]')
HEAD = '<?xml version="1.0" encoding="UTF-8"?>\r\n<objects name="Object Load" version="0.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\r\n'
RESOURCES = (('Armaments', 'Arms'), ('Coal', 'Coal'), ('Food', 'Food'), ('Consumer', 'Goods'), ('Metals', 'Metals'), ('Oil', 'Oil'))
RESEARCH = ('MotorizedInfantry', 'EarlyTanks', 'LightTanks', 'MechanizedInfantry', 'PreWarFighters', 'LightBombers')
MIN_POP = 2      # «población mayor que 2»: la capital y la nación suman más de MIN_POP habitantes


def _slug(t):
    return re.sub(r'[^A-Za-z0-9]', '', t)


def _p(k, v, ind='\t\t'):
    return '%s<property name=%s value=%s/>\r\n' % (ind, quoteattr(k), quoteattr(str(v)))


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)


def pick_template(root=None):
    root = root or sc.SCEN_ROOT
    if os.path.isdir(os.path.join(root, 'Clash of Continents')):
        return 'Clash of Continents'
    best = None
    for n in sc.scenarios():
        k = sum(1 for f in os.listdir(os.path.join(root, n)) if f.startswith('country')) - (1000 if os.path.exists(os.path.join(root, n, 'sharedData.xml')) else 0)
        if best is None or k < best[0]:
            best = (k, n)
    if best is None:
        raise ValueError('no hay ningún escenario de plantilla')
    return best[1]


def check_name(name, root=None):
    root = root or sc.SCEN_ROOT
    name = (name or '').strip()
    if not name or BAD_FILE.search(name):
        raise ValueError('el escenario necesita un nombre válido (sin \\ / : * ? " < > |)')
    if os.path.isdir(root) and any(d.lower() == name.lower() for d in os.listdir(root)):
        raise ValueError('ya existe el escenario %s' % name)
    return name


def create_scenario(name, pack, template=None, display=None, description=None, year=1936, month=1, day=1, turns=480):
    """Crea la carpeta del escenario vacío (sin naciones ni regiones) que usa el regionpack 'pack'. No toca el mapa."""
    root = sc.SCEN_ROOT
    name = check_name(name, root)
    tpl = template or pick_template(root)
    src = os.path.join(root, tpl)
    if not os.path.isfile(os.path.join(src, 'scenario.xml')):
        raise ValueError('la plantilla %s no existe o no tiene scenario.xml' % tpl)
    dst = os.path.join(root, name)
    try:
        os.makedirs(dst)
        for f in sorted(os.listdir(src)):      # datos compartidos que tenga la plantilla (los demás los pone el juego)
            if f.startswith('sharedData') and f.endswith('.xml') and f != 'sharedDataHistoricCountries.xml':
                shutil.copy2(os.path.join(src, f), dst)
        for d in ('game', 'ui'):
            if os.path.isdir(os.path.join(src, d)):
                shutil.copytree(os.path.join(src, d), os.path.join(dst, d), ignore=shutil.ignore_patterns('countries', 'stringTable.xml'))
        if os.path.exists(os.path.join(dst, 'game', 'namespace.xml')):
            _write(os.path.join(dst, 'game', 'stringTable.xml'), '<?xml version="1.0" encoding="UTF-8"?>\r\n<stringTable existence="optional">\r\n</stringTable>\r\n')
        # scenario.xml: el de la plantilla con nombre, descripción, fechas y regionpack propios
        t = open(os.path.join(src, 'scenario.xml'), encoding='utf-8', errors='replace', newline='').read()
        disp = display or name
        desc = description or ''
        sub = lambda k, v, t: re.sub(r'(name="%s" value=")[^"]*(")' % k, lambda m: m.group(1) + quoteattr(v)[1:-1] + m.group(2), t, count=1)
        for k, v in (('strName', name), ('strDisplayName', disp), ('strDescription', desc), ('strVersion', '1.0'),
                     ('nStartYear', str(year)), ('nStartMonth', str(month)), ('nStartDay', str(day)),
                     ('dateStart', '%02d/%02d/%s' % (month, day, year)), ('nScenarioDuration', str(turns)),
                     ('strMapName', pack),          # strSpriteMapName se deja el de la plantilla (World): no hay sprite map por regionpack
                     ('fileMapProperties', '/../Modern Europe/system/DisplayLibraries/Maps/%s/xml/properties.xml' % pack)):
            t = sub(k, v, t)
        _write(os.path.join(dst, 'scenario.xml'), t)
        _write(os.path.join(dst, 'scenarioInfo.xml'), HEAD + '\t<object type="ScenarioInfo" name="">\r\n' +
               _p('strName', name) + _p('strDisplayName', disp) + _p('strDescription', desc) + _p('strVersion', '1.0') +
               _p('eScenarioType', 'USER_CREATED') + _p('nStartYear', year) + _p('nStartMonth', month) + _p('nStartDay', day) +
               _p('dateStart', '%02d/%02d/%s' % (month, day, year)) + _p('nScenarioNumber', 1) + _p('fileScenario', 'scenario.xml') +
               '\t</object>\r\n</objects>\r\n')
        _write(os.path.join(dst, 'game.xml'), HEAD + '\t<object type="MEGame" name="">\r\n' + _p('strScenario', name) +
               _p('strContentPack', 'Modern Europe') + '\t\t<object type="GameState" name="objGameState" fromFile="gamestate.xml">\r\n\t\t</object>\r\n'
               '\t\t<object type="WorldMarket" name="objGOs">\r\n\t\t</object>\r\n'
               '\t\t<object type="GO" name="objGOs" fromFile="treaties.xml">\r\n\t\t</object>\r\n'
               '\t\t<object type="GO" name="objGOs" fromFile="waterWorld.xml">\r\n\t\t</object>\r\n'
               '\t\t<object type="View" name="objViews">\r\n\t\t\t<property name="strName" value="minor"/>\r\n\t\t</object>\r\n\t</object>\r\n</objects>\r\n')
        _write(os.path.join(dst, 'gamestate.xml'), HEAD + '\t<object type="GameState" name="">\r\n'
               '\t\t<object type="AllianceManager" name="objAllianceManager">\r\n\t\t</object>\r\n\t</object>\r\n</objects>\r\n')
        _write(os.path.join(dst, 'treaties.xml'), HEAD + '\t<object type="TreatyList" name="">\r\n\t</object>\r\n</objects>\r\n')
        _write(os.path.join(dst, 'waterWorld.xml'), HEAD + '</objects>\r\n')
        _write(os.path.join(dst, 'sharedDataHistoricCountries.xml'), HEAD + '\t<object type="MESharedData" name="">\r\n'
               '\t\t<object type="HistoricCountryTable" name="objHistoricCountryTable">\r\n\t\t</object>\r\n\t</object>\r\n</objects>\r\n')
    except Exception:
        shutil.rmtree(dst, ignore_errors=True)
        raise
    return name


# ---------------------------------------------------------------------------------------- naciones
def name_taken(s, name):
    """Por qué no se puede usar 'name' para una nación nueva (None si está libre): ya hay país, jugador en gamestate.xml,
    entrada en game.xml o archivos con ese nombre (p. ej. una nación a medio crear con otro editor). Dos jugadores con el
    mismo nombre impiden crear la partida («Found duplicate player named …»)."""
    if name in s.countries():
        return 'ya existe la nación %s' % name
    if any(prop(p, 'strName') == name for p in s.all('Player', lambda f: f == 'gamestate.xml')):
        return 'ya hay un jugador «%s» en gamestate.xml (¿creado con otro editor?): ábrelo en la pestaña Colores o bórralo antes' % name
    for f in ('country%s.xml' % name, 'player%s.xml' % name):
        if os.path.exists(s.path(f)):
            return 'ya existe el archivo %s en la carpeta del escenario' % f
    return None


def validate_nation(spec, existing=(), need_capital=True):
    """Reglas de una nación nueva: nombre libre, capital con nombre y habitantes de la capital y de la nación > MIN_POP."""
    n = (spec.get('name') or '').strip()
    if not n or BAD_FILE.search(n):
        raise ValueError('la nación nueva «%s» necesita un nombre válido (sin \\ / : * ? " < > |)' % n)
    if n in existing:
        raise ValueError('ya existe la nación %s' % n)
    if not need_capital:
        col = spec.get('color')
        if col and not re.fullmatch(r'#[0-9A-Fa-f]{6}', col):
            raise ValueError('%s: el color debe ser #RRGGBB' % n)
        return n
    cap = spec.get('capital') or {}
    if not (cap.get('name') or '').strip():
        raise ValueError('%s: toda nación necesita una ciudad capital (nombre)' % n)
    if cap.get('existing'):         # capital = una ciudad que ya cae dentro de la región (se comprueba al registrarla)
        cp = MIN_POP + 1
    else:
        try:
            cp = int(cap.get('population'))
        except (TypeError, ValueError):
            raise ValueError('%s: indica la población de la capital' % n)
    if cp <= MIN_POP:
        raise ValueError('%s: la capital %s debe tener más de %d habitantes' % (n, cap['name'], MIN_POP))
    col = spec.get('color')
    if col and not re.fullmatch(r'#[0-9A-Fa-f]{6}', col):
        raise ValueError('%s: el color debe ser #RRGGBB' % n)
    return n


def free_color(used):
    import colorsys
    used = {u[:7].upper() for u in used if u}
    for i in range(1, 400):
        r, g, b = (int(x * 255) for x in colorsys.hsv_to_rgb(((i * 47) % 360) / 360.0, 0.55, 0.85))
        c = '#%02X%02X%02X' % (r, g, b)
        if c not in used:
            return c
    return '#808080'


def create_nation(s, spec, need_capital=True):
    """Nación nueva sin regiones en el escenario 's' (Scenario abierto): country/player.xml, game.xml, gamestate.xml,
    scenarioInfo.xml y textos. La capital se fija cuando se crea su ciudad (set_capital). No guarda."""
    import xml.etree.ElementTree as ET
    st = s.s
    name = validate_nation(spec, s.countries(), need_capital)
    why = name_taken(s, name)
    if why:
        raise ValueError(why)
    slug = _slug(name)
    playable = spec.get('playable', True)
    cult = spec.get('culture') or 'English'
    fc, fp = 'country%s.xml' % name, 'player%s.xml' % name
    for f in (fc, fp):
        if os.path.exists(s.path(f)):
            raise ValueError('ya existe el archivo %s en la carpeta del escenario' % f)
    c = HEAD + '\t<object type="MECountry" name="">\r\n'
    for k, v in (('strName', name), ('strGovType', spec.get('gov') or 'Democratic'), ('sidName', 'SID.Game.Country.Name.' + slug),
                 ('sidPossessive', 'SID.Game.Country.Possessive.' + slug), ('sidAdjective', 'SID.Game.Country.Adjective.' + slug),
                 ('sidPeople', 'SID.Game.Country.People.' + slug), ('sidAllianceName', 'SID.Game.Country.Alliance.' + slug),
                 ('strHomelands', name), ('eCountryType', 'COUNTRYTYPE_PLAYABLE' if playable else 'COUNTRYTYPE_NON_FEATURED'),
                 ('bNonPlayable', 'false' if playable else 'true'), ('strFlagName', spec.get('flag') or name), ('nTransportCredits', 25),
                 ('n64GovernmentWealth', 2000000000)):
        c += _p(k, v)
    for r, sid in RESOURCES:
        c += '\t\t<object type="Resource" name="objResources">\r\n' + _p('strName', r, '\t\t\t') + _p('sidDisplayName', 'SID.Game.Resource.Name.' + sid, '\t\t\t') + \
            _p('nAmount', 2000, '\t\t\t') + '\t\t</object>\r\n'
    c += '\t\t<object type="WarList" name="objWarList">\r\n\t\t</object>\r\n\t\t<object type="CultureSet" name="objCultureSet">\r\n' \
         '\t\t\t<object type="Culture" name="objCultures">\r\n' + _p('strCultureName', cult, '\t\t\t\t') + '\t\t\t</object>\r\n\t\t</object>\r\n\t</object>\r\n</objects>\r\n'
    _write(s.path(fc), c)
    pl = HEAD + '\t<object type="MEPlayerData" name="">\r\n'
    for k, v in (('strName', name), ('strOwner', name), ('strFoggees', name), ('strHLPDefLists', 'Default'), ('strDipRelProcListName', 'Neutral'),
                 ('strAITreatyEvalListName', 'Neutral_Isolationist'), ('eInternationalPosition', 'PLAYER_INTERNATIONAL_POSITION__NEUTRAL'),
                 ('nInternationalInvolvement', 1), ('nAggressiveNature', 1), ('nMilitaryPosture', 1), ('nMilitaryDoctrine', 1),
                 ('nDomesticPolicy', 1), ('nSciencePolicy', 1), ('nPoliticalStability', 21)):
        if k == 'strHLPDefLists' and playable:
            pl += _p(k, 'Default') + _p(k, 'Playable') + _p('strPLPDefLists', 'Playable')
            continue
        pl += _p(k, v)
    # cada escenario tiene su árbol: solo los proyectos que existen, más sus requisitos (si falta uno no se crea la partida)
    tree = sc.research_tree(s.dir)
    done = [r for r in RESEARCH if not tree or r in tree]
    for r in done + sc.missing_prereqs(tree, done):
        pl +='\t\t<object type="ResearchProjectInitRef" name="objInitResearchRefs">\r\n' + _p('strProjectName', r, '\t\t\t') + \
            _p('eResearchState', 'RESEARCH_COMPLETED', '\t\t\t') + '\t\t</object>\r\n'
    pl += '\t</object>\r\n</objects>\r\n'
    _write(s.path(fp), pl)
    for f in (fc, fp):
        p = os.path.abspath(s.path(f))
        st.open(p)
        s.paths.append(p)
        st.dirty.add(p)
        st.restructured.add(p)
    # game.xml
    gx = next(g for g in s.all('MEGame', lambda f: f == 'game.xml'))
    for f in (fc, fp):
        e = ET.Element('object', {'type': 'GO', 'name': 'objGOs', 'fromFile': f})
        view = next((v for v in objs(gx) if v.get('type') == 'View'), None)
        st.attach(e, gx, index=list(gx).index(view) if view is not None else None)
    for v in s.all('View'):
        e = ET.Element('property', {'name': 'strAliases', 'value': name})
        v.append(e)
        st.parent[e], st.doc_of[e] = v, st.doc_of[v]
        st.touch(v, structural=True)
    # gamestate.xml: Player
    gs = next(g for g in s.all('GameState', lambda f: f == 'gamestate.xml'))
    used = [prop(p, 'colCountryColor') for p in s.all('Player')]
    col = (spec.get('color') or free_color(used)).upper()
    pe = ET.Element('object', {'type': 'Player', 'name': 'objPlayers'})
    for k, v in (('strName', name), ('sidName', 'SID.Game.Country.Name.' + slug),
                 ('sidShortDescription', 'SID.Game.Country.Description.%s.%s' % (_slug(s.name), slug)),
                 ('bNonPlayable', 'false' if playable else 'true'), ('colCountryColor', col + 'FF'), ('strFlagName', spec.get('flag') or name)):
        ET.SubElement(pe, 'property', {'name': k, 'value': v})
    am = next((o for o in objs(gs) if o.get('type') == 'AllianceManager'), None)
    st.attach(pe, gs, index=list(gs).index(am) if am is not None else None)
    # scenarioInfo.xml: lista de naciones jugables
    if playable:
        info = next(iter(s.all('ScenarioInfo')), None)
        if info is not None:
            w = ET.Element('object', {'type': 'WrappedString', 'name': 'objPlayableCountries'})
            ET.SubElement(w, 'property', {'name': 'strString', 'value': name})
            st.attach(w, info)
    notes = ['nación %s creada (country/player.xml, game.xml, gamestate.xml%s), color %s' % (name, ', scenarioInfo.xml' if playable else '', col)]
    notes += sc.set_region_string(s, 'SID.Game.Country.Name.' + slug, name)
    for k in ('Possessive', 'Adjective', 'People', 'Alliance'):
        notes += sc.set_region_string(s, 'SID.Game.Country.%s.%s' % (k, slug), name)
    # el texto tiene que existir aunque esté vacío: un sidShortDescription sin texto impide cargar la partida
    notes += sc.set_region_string(s, 'SID.Game.Country.Description.%s.%s' % (_slug(s.name), slug), spec.get('description') or '')
    # imágenes de la nación: marcador de posición liso
    s._opts = None
    return notes


def add_historic(s, nation, regions):
    """HistoricCountry de la nación con sus regiones (lo usa el juego para liberar naciones)."""
    import xml.etree.ElementTree as ET
    st = s.s
    h = next((h for h in s.all('HistoricCountry') if prop(h, 'strCountry') == nation), None)
    if h is None:
        tab = next(iter(s.all('HistoricCountryTable')), None)
        if tab is None:
            return ['AVISO: sharedDataHistoricCountries.xml no está en el escenario: sin país histórico para %s' % nation]
        h = ET.Element('object', {'type': 'HistoricCountry', 'name': 'objHistoricCountryList'})
        ET.SubElement(h, 'property', {'name': 'strCountry', 'value': nation})
        st.attach(h, tab)
    have = {prop(k, 'strRegion') for k in objs(h)}
    for r in regions:
        if r not in have:
            pair = ET.Element('object', {'type': 'NameRegionRefPair', 'name': 'objNameRegionRefPairs'})
            ET.SubElement(pair, 'property', {'name': 'strRegion', 'value': r})
            st.attach(pair, h)
    return []


def set_capital(s, nation, city):
    st = s.s
    c = s.countries()[nation]
    st.set_prop(c, 'strCapital', city)
    st.set_prop(c, 'strOriginalCapital', city)
    return ['capital de %s: %s' % (nation, city)]


def check_nations(s, names=None):
    """Errores de las naciones con territorio: sin capital propia o con habitantes <= MIN_POP (capital o total)."""
    out = []
    cities = {}
    for r in s.regions(sea=False):
        for c in objs(r):
            if c.get('type') == 'City':
                cities[prop(c, 'strName')] = c
    for n, c in s.countries().items():
        if names and n not in names:
            continue
        regs = [r for r in objs(c) if r.get('type') == 'Region']
        if not regs:
            continue
        cap = prop(c, 'strCapital')
        city = cities.get(cap)
        if not cap or city is None or prop(city, 'strOwner') != n:
            out.append('%s: no tiene una ciudad capital propia' % n)
            continue
        cp = prop(city, 'nPopulation') or '0'
        if not cp.isdigit() or int(cp) <= MIN_POP:
            out.append('%s: la capital %s debe tener más de %d habitantes' % (n, cap, MIN_POP))
        tot = sum(int(prop(r, 'nPopulation') or 0) for r in regs if (prop(r, 'nPopulation') or '').isdigit())
        if tot <= MIN_POP:
            out.append('%s: la población total (%d) debe ser mayor que %d' % (n, tot, MIN_POP))
    return out


# ---------------------------------------------------------------------------------------- enganche con las regiones nuevas
def prepare_region(s, c):
    """Antes de registrar una región nueva ('c' = entrada de regiones_nuevas): si trae una nación nueva que aún no existe en
    el escenario, la crea. La capital de la nación es la ciudad que se crea en esta región."""
    nat = c.get('nacion')
    if not nat:
        return []
    notes = []
    if nat['name'] not in s.countries():
        notes += create_nation(s, nat)
    cap = nat.get('capital') or {}
    if cap.get('existing'):
        c['pais'], c['controlador'] = nat['name'], nat['name']
        return notes
    c['ciudad'] = {'name': cap['name'].strip(), 'ipus': cap.get('ipus', 1), 'population': int(cap['population']),
                   'x': cap.get('x'), 'y': cap.get('y'), 'display': cap.get('display'), 'port': cap.get('port')}
    c['pais'] = nat['name']
    c['controlador'] = nat['name']
    return notes


def finish_region(s, c, region):
    """Tras crear la región y su ciudad: fija la capital de la nación y la hace país histórico con esta región."""
    nat = c.get('nacion')
    if not nat:
        return []
    cap = nat['capital']['name'].strip()
    cities = {prop(ci, 'strName') for r in s.regions(sea=False) if prop(r, 'strName') == region for ci in objs(r) if ci.get('type') == 'City'}
    notes = []
    if cap in cities:
        notes += set_capital(s, nat['name'], cap)
    else:
        notes.append('ERROR: la capital %s de %s no se pudo crear en %s' % (cap, nat['name'], region))
    notes += add_historic(s, nat['name'], [region])
    return notes
