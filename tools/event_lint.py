"""Strict checker for a scenario's scripted events and AI parameter blocks (MH1/Gold).
Rules come from bugs found in real games (2026-11): dated wars re-declared every turn, peace with no war, regions
transferred during a battle, debug actions, missing AI parameter blocks and region lists.

    python event_lint.py "<scenario name>" [--prefix MOD_] [--gold]
    from event_lint import issues; issues(scenario) -> [{'level', 'msg', 'id'}]   (what «Validar» shows)

Messages are Spanish UI text: each one is «<label or file>: <fixed sentence>[ <data>]»; the fixed sentences are in i18n_en.json.
"""
import re
import sys

import scenario_core as C
import scenario_events as EV

P, objs = C.prop, C.objs
ONE_SHOT = {'ActProposeDeclareWar', 'ActTransferRegionOwnership', 'ActTransferRegionControl', 'ActSetCountryGov', 'ActGrantIndependence',
            'ActCountrySurrender', 'ActFormSeparatePeaceConcessions', 'ActFormAlliancePeaceConcessions', 'ActDevCreateUnits',
            'ActIncResourceStock', 'ActIncDipRelations'}
REPEAT_BAD = {'ActProposeDeclareWar', 'ActTransferRegionOwnership', 'ActTransferRegionControl', 'ActSetCountryGov', 'ActGrantIndependence',
              'ActCountrySurrender', 'ActFormSeparatePeaceConcessions', 'ActFormAlliancePeaceConcessions'}   # repeating units/aid can be on purpose
PEACE = {'ActFormSeparatePeaceConcessions', 'ActFormAlliancePeaceConcessions', 'ActDevMakePeace'}
TRANSFER = {'ActTransferRegionOwnership', 'ActTransferRegionControl'}
BUILTIN_VARS = ('scratch.objPlayer', 'scratch.objScriptEvent', 'scratch.bDPInterrupt')   # filled by the game
VAR = re.compile(r'\{[^}]*\}scratch\.\w+')
DATE = re.compile(r'dateGameDate GTE (\S+)')
COUNTRY_PROPS = ('strCountry', 'strFromCountry', 'strToCountry', 'strOtherCountry', 'strLosingCountryName', 'strWinningCountryName', 'strCountryName')

# fixed sentences (translation keys in i18n_en.json)
M_DUP = 'la etiqueta del evento está repetida'
M_VAR = 'usa una variable que ningún accesorio rellena:'
M_COUNTRY = 'nombra un país que no existe:'
M_REGION = 'nombra una región que no existe:'
M_TO = 'va dirigido a un país que no existe:'
M_DEV = 'usa una acción de depuración que ningún escenario del juego usa (para la paz: ActFormSeparatePeaceConcessions):'
M_DATE = 'fecha que no está en formato MM/DD/AAAA:'
M_TRIG = 'el disparador abre una decisión que no existe:'
M_LISTEN = 'el disparador escucha un evento que no existe:'
M_ORPHAN = 'la decisión nunca se abre (ningún disparador apunta a ella)'
M_NODEF = 'la decisión no tiene opción por defecto: la IA puede no responderla nunca'
M_NOTRIG = 'el evento no tiene activador (objTriggerEval)'
M_WAITS = 'el evento espera una decisión que no existe:'
M_REPEAT = ('el activador TriggerEvalRandomChance se evalúa cada turno: estos efectos se repetirán mientras se cumplan las condiciones '
            '(p. ej. la guerra se vuelve a declarar después de la paz). Usa una decisión (TriggerEvalUntilAnsweredPlayerDecision):')
M_ALL = 'PlayerGenAll en una decisión: todos los países reciben la ventana (solo sirve para noticias sin efectos)'
M_ORDER = 'traspasa regiones antes de firmar la paz: con una batalla en la región el turno puede bloquearse. Haz primero la paz'
M_PEACE = 'firma la paz sin comprobar que la guerra sigue (AccessorIsAtWar): una paz sin guerra rompe el juego'
M_OWNER = 'traspasa regiones sin comprobar quién las posee o controla (puede darle una región a su propio dueño)'
M_WAR = 'declara la guerra sin comprobar que no estén ya en guerra'
M_EXISTS = 'usa un país sin comprobar que existe (exists):'
M_TYPE = 'usa un tipo de objeto que no existe en el juego:'
M_FIELD = 'pone un campo que ese tipo no tiene (el juego lo ignora o falla):'
M_BLOCK = 'una meta de la IA apunta a un bloque de parámetros que no existe:'
M_RLIST = 'usa una lista de regiones que no está definida:'
M_RLREG = 'una lista de regiones nombra una región que no existe:'
M_TRIGRL = 'la reacción a un país usa una lista de regiones que no está en su archivo player:'
M_TRIGC = 'reacción a un país que no existe:'
M_WARALLY = ('la guerra inicial arrastra a toda una alianza: todos sus miembros empiezan en guerra y la IA de otras alianzas '
             'puede entrar y escalar a una guerra mundial. Deja la alianza vacía si es una guerra entre dos países:')
M_NOPLAYER = ('la propuesta de tratado no dice qué jugador la hace (strPlayer): el juego no puede crear el tratado, la decisión queda '
              'sin responder y el turno se bloquea. Pon strPlayer = el país que declara la guerra o pide la paz:')
M_ALLYWAR = ('la guerra del evento toca a un miembro de una alianza: toda la alianza vota si entra (los jugadores humanos deben '
             'responder antes de terminar el turno) y la IA puede escalarla a una guerra entre alianzas:')
M_ALTER = ('el evento cambia una propiedad de un objeto (nombre visible, cultura…): el juego rechaza esa acción en un evento '
           '(«Can\'t find player while executing ActAlterProperty»), así que la elección no se ejecuta, la ventana no se cierra '
           'y el turno queda trabado. Quita la acción:')
M_ZERO = 'TriggerEvalRandomChance con 0 %: el juego compara rand()%100 <= 0, así que igual dispara el 1 % de los turnos'
M_AIPCT = ('la IA casi nunca elige la opción por defecto: nDefaultChoicePercent falta o es bajo (la IA tira rand()%100 '
           'contra ese porcentaje). Pon 100 para que siempre la elija:')
M_WARNOALLY = 'la guerra inicial nombra una alianza que no existe:'
M_WARLONE = ('el juego borra esta guerra al cargar: un país de la guerra está en una alianza y la guerra no la nombra. '
             'Pon esa alianza en su bando (atacante o defensor):')


def _vars(el):
    out = set()
    for p in el.iter('property'):
        for a in ('value', 'inheritFrom'):
            out |= set(VAR.findall(p.get(a) or ''))
    return out


def _defined(el):
    return {VAR.match(p.get('value')).group(0) for p in el.iter('property')
            if p.get('name') in ('pathOutput', 'pathSingleObject', 'pathManyObjects') and p.get('value') and VAR.match(p.get('value'))}


def _default_labels():
    """Event labels that come from the game's ScenarioDefaults (generic events every scenario loads)."""
    import glob
    import os
    out = set()
    for d in (os.path.join(C.GAME, 'Modern Europe', 'system', 'ScenarioDefaults'), os.path.join(C.GAME, 'system', 'ScenarioDefaults')):
        for f in glob.glob(os.path.join(d, '*.xml')):
            try:
                out |= set(re.findall(r'(?:strTypeLabel|strTypeToTrigger)" value="([^"]+)"', open(f, encoding='utf-8', errors='replace').read()))
            except OSError:
                pass
    return out


def _texts(el):
    return ' '.join((p.get('value') or '') for p in el.iter('property'))


def lint(s, prefix=''):
    """Events whose label starts with prefix: [(level, label, msg, element)]."""
    out = []
    countries = set(s.countries())
    regions = {P(r, 'strName') for r in s.regions()}
    evs = list(s.all_types(EV.EVENT_TYPES))
    by_label = {}
    for e in evs:
        by_label.setdefault(P(e, 'strTypeLabel'), []).append(e)
    defaults = _default_labels()
    decisions = {P(e, 'strTypeLabel') for e in evs if e.get('type') == 'PlayerDecisionDef'} | defaults
    triggered = {P(e, 'strTypeToTrigger') for e in evs if e.get('type') == 'PlayerDecisionTrigPlayEvent'} | defaults
    scripted = {P(e, 'strTypeLabel') for e in evs if e.get('type') == 'ScriptedEventDef'} | defaults
    triggers_of = {}
    for e in evs:
        if e.get('type') == 'PlayerDecisionTrigPlayEvent':
            triggers_of.setdefault(P(e, 'strTypeToTrigger'), []).append(e)

    for e in evs:
        lab = P(e, 'strTypeLabel') or ''
        if not lab.startswith(prefix):
            continue
        add = lambda lv, msg: out.append((lv, lab, msg, e))
        t = e.get('type')
        txt = _texts(e)
        if len([x for x in by_label.get(lab, []) if x.get('type') == t]) > 1:
            add('error', M_DUP)
        # a decision's conditions usually live in its scripted event (label without «_Decision»): check the chain as a whole
        pair = [x for x in by_label.get(lab[:-len('_Decision')], []) if x.get('type') == 'ScriptedEventDef'] if lab.endswith('_Decision') else []
        chain_txt = txt + ' '.join(_texts(x) for x in pair)
        chain_war = any(o.get('type') == 'AccessorIsAtWar' for x in [e] + pair for o in x.iter('object'))
        # variables flow along the chain: scripted event -> trigger -> decision
        chain = [e] + pair + triggers_of.get(lab, [])
        if t == 'PlayerDecisionTrigPlayEvent':
            m = re.search(r"strTypeLabel == '([^']+)'", txt)
            chain += [x for x in by_label.get(m.group(1), [])] if m else []
        known = set().union(*[_defined(x) for x in chain])
        for v in sorted(_vars(e) - known):
            if not v.endswith(BUILTIN_VARS) and ':PlayEvent' not in v:
                add('error', '%s %s' % (M_VAR, v))
        for p in e.iter('property'):
            if p.get('value') and p.get('name') in COUNTRY_PROPS and p.get('value') not in countries:
                add('error', '%s %s' % (M_COUNTRY, p.get('value')))
        for o in e.iter('object'):
            ot = o.get('type') or ''
            if ot == 'AccessorGetRegion' and P(o, 'strName') and P(o, 'strName') not in regions:
                add('error', '%s %s' % (M_REGION, P(o, 'strName')))
            if ot == 'PlayerGenNames' and P(o, 'strName') not in countries:
                add('error', '%s %s' % (M_TO, P(o, 'strName')))
            if ot.startswith('ActDev') and ot != 'ActDevCreateUnits':
                add('error', '%s %s' % (M_DEV, ot))
        for d in DATE.findall(txt):
            if not re.fullmatch(r'\d\d/\d\d/\d{4}', d):
                add('error', '%s %s' % (M_DATE, d))
        if t == 'PlayerDecisionTrigPlayEvent':
            if P(e, 'strTypeToTrigger') not in decisions:
                add('error', '%s %s' % (M_TRIG, P(e, 'strTypeToTrigger')))
            m = re.search(r"strTypeLabel == '([^']+)'", txt)
            # PlayEventPlayerDecisionAnswered listens to a decision being answered, not to a scripted event
            heard = decisions if P(e, 'otPlayEventType') == 'PlayEventPlayerDecisionAnswered' else scripted
            if m and m.group(1) not in heard:
                add('error', '%s %s' % (M_LISTEN, m.group(1)))
        if t == 'PlayerDecisionDef':
            if lab not in triggered:
                add('error', M_ORPHAN)
            if not P(e, 'strDefaultChoice'):
                add('warning', M_NODEF)
        if t == 'ScriptedEventDef':
            te = next((o for o in objs(e) if o.get('name') == 'objTriggerEval'), None)
            tt = te.get('type') if te is not None else None
            if tt is None:
                add('error', M_NOTRIG)
            if tt == 'TriggerEvalUntilAnsweredPlayerDecision' and P(te, 'strDecisionType') not in decisions:
                add('error', '%s %s' % (M_WAITS, P(te, 'strDecisionType')))
            acts = {o.get('type') for o in e.iter('object') if (o.get('type') or '').startswith('Act')}
            if tt == 'TriggerEvalRandomChance' and acts & REPEAT_BAD:
                add('error', '%s %s' % (M_REPEAT, ', '.join(sorted(acts & REPEAT_BAD))))
            gen = next((o for o in objs(e) if o.get('name') == 'objPlayerGen'), None)
            if gen is not None and gen.get('type') == 'PlayerGenAll' and tt == 'TriggerEvalUntilAnsweredPlayerDecision':
                add('warning', M_ALL)
        for ce in [o for o in e.iter('object') if o.get('type') == 'CustomEffectDefActions']:
            seq = [o.get('type') for o in objs(ce)]
            pi = [i for i, x in enumerate(seq) if x in PEACE]
            ti = [i for i, x in enumerate(seq) if x in TRANSFER]
            if pi and ti and min(ti) < min(pi):
                add('error', M_ORDER)
            if pi and not chain_war:
                add('error', M_PEACE)
            if ti and 'nOwnerID' not in chain_txt and 'nControllerID' not in chain_txt:
                add('warning', M_OWNER)
            if 'ActProposeDeclareWar' in seq and not chain_war:
                add('warning', M_WAR)
        if t != 'PlayerDecisionTrigPlayEvent':
            for v in sorted(set(re.findall(r'scratch\.objCountry(\w+)\.nCountryID', txt))):
                if v != 'Player' and 'exists({Object:Single:Country}scratch.objCountry%s)' % v not in txt:
                    add('warning', '%s %s' % (M_EXISTS, v))
    return out


def _game_defs():
    """{objectDef type: (superType, {property/embedded names})} from the game's *Defs.xml files."""
    import glob
    import os
    import xml.etree.ElementTree as ET
    defs = {}
    roots = [os.path.join(C.GAME, 'system', 'game'), os.path.join(C.GAME, 'Modern Europe', 'system', 'game')]
    for f in [f for r in roots for f in glob.glob(os.path.join(r, '*.xml'))]:
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        for d in root.iter('objectDef'):
            names = {p.get('name') for p in d if p.tag in ('propertyDef', 'object')}
            old = defs.get(d.get('type'))
            defs[d.get('type')] = (d.get('superType') or (old[0] if old else None), names | (old[1] if old else set()))
    return defs


def _props_of(defs, t):
    out, seen = set(), set()
    while t in defs and t not in seen:
        seen.add(t)
        out |= defs[t][1]
        t = defs[t][0]
    return out


def _is_a(defs, t, base):
    seen = set()
    while t in defs and t not in seen:
        if t == base:
            return True
        seen.add(t)
        t = defs[t][0]
    return t == base


def lint_types(s, prefix=''):
    """Every object in the events is a real game type, and every field it sets exists on that type."""
    out = []
    defs = _game_defs()
    if not defs:
        return out
    for e in s.all_types(EV.EVENT_TYPES):
        lab = P(e, 'strTypeLabel') or ''
        if not lab.startswith(prefix):
            continue
        for o in [e] + list(e.iter('object')):
            t = o.get('type')
            if t not in defs:
                out.append(('error', lab, '%s %s' % (M_TYPE, t), e))
                continue
            allowed = _props_of(defs, t)
            if _is_a(defs, t, 'ActProposeTreatyDef') and not any(c.get('name') == 'strPlayer' for c in o):
                out.append(('error', lab, '%s %s' % (M_NOPLAYER, t), e))   # «unable to find player for treaty», turn 40 lock
            if t == 'ActSetTradeRelations' and not any(c.get('name') == 'strPlayer' for c in o):
                out.append(('error', lab, 'embargo sin strPlayer (quién embarga): «Couldn\'t find ID of player country», la decisión '
                            'falla y el turno puede trabarse. Pon strPlayer = el país que embarga: %s' % t, e))
            if t in ('ActAlterProperty', 'ActAlterPropertyImmed', 'ActIncrementProperty'):
                out.append(('error', lab, '%s %s.%s' % (M_ALTER, t, P(o, 'strPropName')), e))   # 1121 Malvinas popup stuck
            for c in o:
                n = c.get('name')
                if n and allowed and n not in allowed:
                    out.append(('error', lab, '%s %s.%s' % (M_FIELD, t, n), e))
    return out


def lint_players(s):
    """AI goals and region lists in country*/player*.xml («Failed to get param block», «Couldn't find region list»)."""
    out = []
    st = s.s
    countries = s.countries()
    regions = {P(r, 'strName') for r in s.regions()}
    pdata = {}
    for p in s.paths:
        b = p.replace('\\', '/').split('/')[-1]
        if b.startswith('player') and b.endswith('.xml'):
            pdata[b[6:-4]] = st.docs[p].getroot()
    for c, root in pdata.items():
        f = 'player%s.xml' % c
        blocks = {P(b, 'strName') for b in root.iter('object') if b.get('name') == 'objParameterBlocks'}
        rlists = {P(r, 'strName') for r in root.iter('object') if r.get('type') == 'RegionListParameter'}
        for g in [g for g in root.iter('object') if g.get('type') == 'HistoricalGoalRef' and P(g, 'bActive') != 'false']:
            for k in ('strTargetBlockName', 'strHistoricBlockName'):
                if P(g, k) and P(g, k) not in blocks:
                    out.append(('error', f, '%s %s (%s)' % (M_BLOCK, P(g, k), P(g, 'strName')), g))
        for sp in [x for x in root.iter('object') if x.get('type') == 'StringParameter']:
            n, v = P(sp, 'strName'), P(sp, 'strValue')
            if n == 'RegionList' and v and v not in rlists:
                out.append(('error', f, '%s %s' % (M_RLIST, v), sp))
            if n and n.startswith('Country') and n.endswith('Name') and v and v not in countries:
                out.append(('error', f, '%s %s' % (M_COUNTRY, v), sp))
        for r in [x for x in root.iter('object') if x.get('type') == 'RegionListParameter']:
            for p in r:
                if p.get('name') == 'strRegions' and p.get('value') not in regions:
                    out.append(('error', f, '%s %s (%s)' % (M_RLREG, p.get('value'), P(r, 'strName')), r))
    for c, cel in countries.items():
        have = {P(r, 'strName') for r in pdata[c].iter('object') if r.get('type') == 'RegionListParameter'} if c in pdata else set()
        for tcn in [x for x in cel.iter('object') if x.get('type') == 'TriggerCountry']:
            rl = P(tcn, 'strRegionList')
            if rl and rl not in have:
                out.append(('error', 'country%s.xml' % c, '%s %s (%s)' % (M_TRIGRL, rl, P(tcn, 'strName')), tcn))
            if P(tcn, 'strName') not in countries:
                out.append(('error', 'country%s.xml' % c, '%s %s' % (M_TRIGC, P(tcn, 'strName')), tcn))
    return out


def lint_wars(s):
    """Starting wars (gamestate War) tied to an alliance: in 1117 «Syrian Civil War» with the Axis of Resistance as attacker
    put every Axis member at war with HTS on turn 1, and NATO and the CSTO joined in by turn 7."""
    out = []
    allies = {}
    for a in [a for a in s.all_types(('Alliance', 'AllianceManager'))]:
        allies[P(a, 'strINITAllianceName')] = 1 + sum(1 for m in a.iter('object') if m.get('type') == 'AllianceMember')
    member = _alliances(s)
    for w in s.all('War'):
        for k, ck in (('strINITOffenseAllianceName', 'strINITAttackerCountryName'), ('strINITDefenseAllianceName', 'strINITDefenderCountryName')):
            a, c = P(w, k), P(w, ck)
            own = member.get(c)
            if own and a != own:     # the engine deletes the war on load («had alliance facade … lone country»)
                out.append(('error', P(w, 'strDisplayName'), '%s %s (%s)' % (M_WARLONE, c, own), w))
            elif not a:
                continue
            elif a not in allies:
                out.append(('error', P(w, 'strDisplayName'), '%s %s' % (M_WARNOALLY, a), w))
            elif a != own:
                out.append(('warning', P(w, 'strDisplayName'), '%s %s (%d)' % (M_WARALLY, a, allies[a]), w))
    return out


def _alliances(s):
    """{country: alliance name} from the starting alliances in gamestate."""
    out = {}
    for a in s.all_types(('Alliance', 'AllianceManager')):
        n = P(a, 'strINITAllianceName')
        for c in [P(a, 'strINITCountryName')] + [P(m, 'strINITCountryName') for m in a.iter('object') if m.get('type') == 'AllianceMember']:
            if c:
                out[c] = n
    return out


def lint_ai(s, prefix=''):
    """How the engine runs events for the AI (MH1 decomp, see MH1-EVENTOS-INFORME.md)."""
    out = []
    ally = _alliances(s)
    for e in s.all_types(EV.EVENT_TYPES):
        lab = P(e, 'strTypeLabel') or ''
        if not lab.startswith(prefix):
            continue
        if e.get('type') == 'PlayerDecisionDef' and P(e, 'strDefaultChoice'):
            pct = P(e, 'nDefaultChoicePercent')
            if not pct or int(pct) < 50:
                out.append(('warning', lab, '%s %s' % (M_AIPCT, pct or '0'), e))
        for o in e.iter('object'):
            if o.get('type') == 'TriggerEvalRandomChance' and (P(o, 'nPercentChance') or '0') == '0':
                out.append(('warning', lab, M_ZERO, e))
            if o.get('type') == 'ActProposeDeclareWar':
                hit = ['%s (%s)' % (c, ally[c]) for c in (P(o, 'strFromCountry'), P(o, 'strToCountry')) if c in ally]
                if hit:
                    out.append(('warning', lab, '%s %s' % (M_ALLYWAR, ', '.join(hit)), e))
    return out


def issues(s, prefix=''):
    """All checks in the editor's validation format."""
    st = s.s
    return [{'level': lv, 'msg': '%s: %s' % (lab, msg), 'id': st.eid(el)}
            for lv, lab, msg, el in lint(s, prefix) + lint_types(s, prefix) + lint_players(s) + lint_wars(s) + lint_ai(s, prefix)]


if __name__ == '__main__':
    import gamepaths
    gamepaths.select('mh2' if '--gold' in sys.argv else 'mh1')
    import editor_server as E
    pre = sys.argv[sys.argv.index('--prefix') + 1] if '--prefix' in sys.argv else ''
    args = [a for a in sys.argv[1:] if not a.startswith('--') and a != pre]
    res = issues(E.scenario(args[0]), pre)
    for i in res:
        print('%-7s %s' % (i['level'].upper(), i['msg']))
    print('%d errors, %d warnings' % (sum(1 for i in res if i['level'] == 'error'), sum(1 for i in res if i['level'] != 'error')))
    sys.exit(1 if any(i['level'] == 'error' for i in res) else 0)
