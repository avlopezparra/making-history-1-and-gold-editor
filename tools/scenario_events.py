"""Eventos, decisiones e IA de un escenario explicados en palabras y plantillas para crearlos.

- describe(s, el): un ScriptedEventDef / PlayerDecisionDef / PlayerDecisionTrigPlayEvent / DecisionPointDef en palabras:
  quién lo recibe, cuándo se dispara, condiciones, ventana (título, texto, elecciones) y efectos; enlaces a la cadena
  evento → disparador → decisión.
- short(s, el): resumen de una línea para la lista de la pestaña Eventos.
- create_template(s, kind, p): eventos nuevos (guerra, embargo, ideología, recursos, unidades, cultura, decisión con
  elecciones, estado aliado de la misma ideología). Los efectos de una sola vez van en una decisión (como los mods: el
  evento se repite hasta que se responde; la IA elige sola y el jugador ve la ventana).
- set_when / remove_chain: cambiar la fecha o el turno de un evento; quitar un evento con su disparador y su decisión.
- ai_rules / ai_rule_*: lo que hace la IA de un país (player<País>.xml) en palabras: a quién ayuda si le atacan,
  a quién quiere conquistar, planes de guerra con su condición «si A y B están en guerra», presión diplomática y
  los embargos y reacciones por evento.
- terrains / terrain_create / terrain_delete: tipos de terreno (TerrainType de sharedData + texto del stringTable).

Formato analizado en ESCENARIOS_NOTAS.md («Eventos, decisiones e IA»).
"""
import copy
import os
import re
import xml.etree.ElementTree as ET

import scenario_core as sc
from scenario_core import prop, objs

EVENT_TYPES = ('ScriptedEventDef', 'PlayerDecisionDef', 'PlayerDecisionTrigPlayEvent', 'DecisionPointDef')
KIND_ES = {'ScriptedEventDef': 'Evento', 'PlayerDecisionDef': 'Decisión (ventana)', 'PlayerDecisionTrigPlayEvent': 'Disparador de decisión',
           'DecisionPointDef': 'Punto de decisión'}
TRADE_ES = {'TRADE_RELATIONS_EMBARGOED': 'embargo', 'TRADE_RELATIONS_SANCTIONED': 'sanciones', 'TRADE_RELATIONS_FAVORED': 'trato favorable',
            'TRADE_RELATIONS_NEUTRAL': 'comercio normal'}
OPS = {'GTE': '≥', 'GT': '>', 'LTE': '≤', 'LT': '<', '==': '=', '!=': '≠'}
VAR = r'\{[^}]*\}scratch\.(\w+)((?:\.\w+)*)'
PLAYER = 'el país que recibe el evento'


# ---------------------------------------------------------------------------------------- variables (accesores)
def _ctx(el):
    """Qué es cada variable scratch.X del evento: país, región, guerra entre dos, fecha… (de sus accesores)."""
    ctx = {}
    for a in el.iter('object'):
        t = a.get('type') or ''
        if not t.startswith('Accessor') or t == 'AccessorRuleSet':
            continue
        out = re.match(VAR, prop(a, 'pathOutput') or '')
        if not out:
            continue
        v = out.group(1)
        P = {p.get('name'): (p.get('value'), p.get('inheritFrom')) for p in a if p.tag == 'property'}
        ref = lambda n: _ref(P.get(n, (None, None)), ctx)
        if t == 'AccessorGetCountry':
            ctx[v] = ('country', ref('strCountry'))
        elif t == 'AccessorGetRegion':
            ctx[v] = ('region', ref('strName'))
        elif t == 'AccessorIsAtWar':
            ctx[v] = ('war', ref('nCountryID'), ref('nEnemyCountryID'))
        elif t == 'AccessorIsAllied':
            ctx[v] = ('allied', ref('nCountryID'), ref('nAllyID'))
        elif t == 'AccessorGetAllCountryWars':
            ctx[v] = ('wars', ref('nCountryID'))
        elif t == 'AccessorGetCurrentDate':
            ctx[v] = ('date',)
        elif t == 'AccessorGetCurrentTurn':
            ctx[v] = ('turn',)
        elif t == 'AccessorGetRandomNumberSimple':
            ctx[v] = ('rand', P.get('nMinValue', (None,))[0], P.get('nMaxValue', (None,))[0])
        elif t in ('AccessorGetCountryRank', 'AccessorGetTeamRank'):
            ctx[v] = ('rank', ref('nCountryID') if 'nCountryID' in P else ref('nTeamID'))
        elif t == 'AccessorGetCountryAllies':
            ctx[v] = ('allies', None)
        elif t == 'AccessorGetCountryIndependenceCandidates':
            ctx[v] = ('candidates', ref('nCountryID'))
        elif t == 'AccessorGetCurrentWar':
            ctx[v] = ('curwar', ref('strCountry'), ref('strOtherCountry'))
        elif t == 'AccessorHasMilitaryAccess':
            ctx[v] = ('access', ref('strCountry'), ref('strInCountry'))
        else:
            ctx[v] = ('other', t.replace('Accessor', ''))
    return ctx


def _ref(pair, ctx):
    """Valor legible de una propiedad: el valor escrito o, si se hereda de una variable, lo que esa variable es."""
    val, inh = pair if isinstance(pair, tuple) else (pair, None)
    if val is not None:
        return val
    if not inh:
        return '?'
    return _name(inh, ctx)


def _name(path, ctx):
    if 'objPlayer.objCountry' in path or path.endswith('objPlayer'):
        return PLAYER
    m = re.search(VAR, path)
    if not m:
        return path
    v = m.group(1)
    k = ctx.get(v)
    if k and k[0] in ('country', 'region'):
        return k[1]
    if k and k[0] == 'candidates':
        return 'un país liberable'
    if v == 'objCandidateCountry':
        return 'el país liberable'
    return (re.sub(r'^(obj|b|n|str|date)', '', v) or v) + re.sub(r'\.(n|str|b|obj)(?=[A-Z])', '.', m.group(2) or '')


def rule_text(expr, ctx):
    e = (expr or '').strip()
    neg = e.startswith('!')
    body = e[1:].strip() if neg else e
    no = 'no ' if neg else ''
    nm = lambda v, a='': _name('{x}scratch.' + v + a, ctx)
    m = re.fullmatch(r'exists\(\s*' + VAR + r'\s*\)', body)
    if m:
        return '%s %sexiste' % (nm(m.group(1)), no)
    m = re.fullmatch(VAR, body)
    if m:
        v, attr = m.group(1), m.group(2)
        if attr == '.bSurrendered':
            return '%s %sestá rendido (sin territorio)' % (nm(v), no)
        k = ctx.get(v)
        if k and k[0] == 'war':
            return '%s %sestá en guerra con %s' % (k[1], no, k[2])
        if k and k[0] == 'allied':
            return '%s %sestá aliado con %s' % (k[1], no, k[2])
        if k and k[0] == 'access':
            return '%s %stiene acceso militar en %s' % (k[1], no, k[2])
        return '%s%s' % ('NO: ' if neg else '', re.sub(r'^b', '', v))
    m = re.fullmatch(VAR + r'\s*(==|!=)\s*' + VAR, body)
    if m and m.group(2) in ('.nOwnerID', '.nControllerID') and m.group(5) == '.nCountryID':
        verb = 'posee' if m.group(2) == '.nOwnerID' else 'controla'
        yes = (m.group(3) == '==') != neg
        return '%s %s%s %s' % (nm(m.group(4)), '' if yes else 'no ', verb, nm(m.group(1)))
    if m and m.group(2) == '.nCountryID' and m.group(5).endswith('.nCountryID'):
        return '%s %s %s' % (nm(m.group(1)), 'es' if (m.group(3) == '==') != neg else 'no es', nm(m.group(4), m.group(5)))
    m = re.fullmatch(VAR + r"\s*(==|!=)\s*'([^']*)'", body)
    if m:
        v, attr, op, val = m.groups()
        eq = (op == '==') != neg
        if attr == '.strGovType':
            return '%s %stiene gobierno %s' % (nm(v), '' if eq else 'no ', val)
        if v == 'objScriptEvent' and attr == '.strTypeLabel':
            return 'se dispara el evento «%s»' % val
        if attr == '.strTypeLabel':
            return 'se ha respondido la decisión «%s»' % val
        if attr == '.strChoiceSelected':
            return 'la elección es «%s»' % val
        if attr == '.strPlayer':
            return 'quien responde %s %s' % ('es' if eq else 'no es', val)
        if attr == '.strTreatyDefType':
            return 'el tratado %s %s' % ('es' if eq else 'no es', val)
        return '%s%s %s %s' % (nm(v), attr, OPS.get(op, op), val)
    m = re.fullmatch(VAR + r'\s*(GTE|GT|LTE|LT|==|!=)\s*([^{\s]\S*)', body)
    if m:
        v, attr, op, val = m.groups()
        k = ctx.get(v) or ()
        if k[:1] == ('date',):
            return {'GTE': 'desde el %s', 'GT': 'después del %s', 'LT': 'antes del %s', 'LTE': 'hasta el %s', '==': 'el día %s'}.get(op, 'fecha ' + op + ' %s') % val
        if k[:1] == ('turn',):
            return {'==': 'en el turno %s', 'GTE': 'desde el turno %s', 'GT': 'después del turno %s', 'LT': 'antes del turno %s', 'LTE': 'hasta el turno %s'}.get(op, 'turno ' + op + ' %s') % val
        if k[:1] == ('rand',):
            try:
                pct = round(100.0 * (int(val) - int(k[1]) + (1 if op in ('LTE', 'GTE') else 0)) / (int(k[2]) - int(k[1]) + 1))
                return 'azar: %d %% de probabilidad' % (pct if op in ('LTE', 'LT') else 100 - pct)
            except (TypeError, ValueError):
                pass
            return 'número al azar %s %s' % (OPS.get(op, op), val)
        if k[:1] == ('rank',):
            return 'puesto de %s en la clasificación %s %s' % (k[1], OPS.get(op, op), val)
        return '%s %s %s' % (re.sub(r'^(n|str)', '', v) + attr, OPS.get(op, op), val)
    m = re.fullmatch(r'sizeOf\(\s*' + VAR + r'\s*\)\s*(GTE|GT|LTE|LT|==|!=)\s*(\d+)', body)
    if m:
        v, _a, op, val = m.groups()
        k = ctx.get(v) or ()
        if k[:1] == ('wars',):
            if (op, val) in (('LTE', '0'), ('==', '0'), ('LT', '1')):
                return '%s no está en ninguna guerra' % k[1]
            if (op, val) in (('GTE', '1'), ('GT', '0')):
                return '%s está en alguna guerra' % k[1]
            return 'número de guerras de %s %s %s' % (k[1], OPS.get(op, op), val)
        if k[:1] == ('candidates',):
            return '%s tiene países que puede liberar' % k[1] if (op, val) in (('GTE', '1'), ('GT', '0')) else 'países liberables %s %s' % (OPS.get(op, op), val)
        return 'cantidad de %s %s %s' % (re.sub(r'^obj', '', v), OPS.get(op, op), val)
    return re.sub(VAR, lambda x: _name(x.group(0), ctx), e)


# ---------------------------------------------------------------------------------------- acciones
def action_text(a, ctx):
    t = a.get('type') or ''
    P = {p.get('name'): (p.get('value'), p.get('inheritFrom') or p.get('computeFrom')) for p in a if p.tag == 'property'}
    g = lambda n: _ref(P.get(n, (None, None)), ctx) if n in P else None
    who = g('strFromCountry') or (PLAYER if 'strPlayer' in P or t.startswith('ActPropose') else None)
    if t == 'ActProposeDeclareWar':
        return '%s declara la guerra a %s' % (who or PLAYER, g('strToCountry'))
    if t == 'ActSetTradeRelations':
        rel = TRADE_ES.get(g('eTradeRelations') or 'TRADE_RELATIONS_NEUTRAL', g('eTradeRelations'))
        return '%s pone %s a %s' % (PLAYER, rel, g('strCountry'))
    if t == 'ActSetCountryFlagName':
        return '%s cambia su bandera a %s' % (g('strCountryName'), g('strFlagName'))
    if t == 'ActSetCountryGov':
        return '%s cambia su ideología a %s' % (g('strCountry'), g('strGovType'))
    if t == 'ActIncResourceStock':
        n = g('nIncrement') or '0'
        return '%s %s %s de %s' % (g('strCountry'), 'pierde' if n.startswith('-') else 'recibe', n.lstrip('-'), g('strResource'))
    if t == 'ActGrantIndependence':
        return '%s concede la independencia a %s (aparece o se libera %s)' % (g('strFromCountry'), g('strToCountry'), g('strToCountry'))
    if t == 'ActCountrySurrender':
        return '%s se rinde ante %s (anexión)' % (g('strLosingCountryName'), g('strWinningCountryName'))
    if t == 'ActDevCreateUnits':
        return '%s recibe %s × %s en %s («%s»)' % (g('strCountryName'), g('nNumUnits'), g('strUnitTemplate'), g('strRegionName'), g('strUnitName') or '')
    if t in ('ActTransferRegionOwnership', 'ActTransferRegionControl'):
        return 'la región %s pasa %s %s' % (g('nRegionID'), 'a ser de' if t.endswith('Ownership') else 'a estar controlada por',
                                            g('nNewCountryID'))
    if t == 'ActIncDipRelations':
        return 'relación de %s con %s %s %s' % (g('nSourceCountryID'), g('nTargetCountryID'), '−' if (g('nAmount') or '').startswith('-') else '+', (g('nAmount') or '').lstrip('-'))
    if t == 'ActDevCompleteResearchProject':
        return '%s completa la investigación %s' % (g('strCountry'), g('strProjectName'))
    if t in ('ActIncResearchProjectPoints', 'ActDecResearchProjectPoints'):
        return '%s %s %s puntos a la investigación %s' % (g('strCountry'), 'suma' if t.startswith('ActInc') else 'resta', g('nAmount'), g('strProjectName'))
    if t == 'ActSetNewCapital':
        return '%s traslada su capital a %s (%s)' % (g('strCountry'), g('strCity'), g('strRegion'))
    if t == 'ActSetCountryInternationalPosition':
        return '%s pasa a posición %s' % (g('nCountryID'), (g('ePosition') or '').replace('PLAYER_INTERNATIONAL_POSITION__', ''))
    if t == 'ActSetCountryAggressiveNature':
        return 'agresividad de %s = %s' % (g('nCountryID'), g('nAggression'))
    if t == 'ActProposeDefensePact':
        return '%s propone un pacto defensivo a %s' % (who or PLAYER, g('strToCountry'))
    if t == 'ActFormMilitaryAccess':
        return '%s da acceso militar a %s' % (who or PLAYER, g('strToCountry'))
    if t in ('ActAcceptTreaty', 'ActRejectTreaty'):
        return '%s el tratado propuesto' % ('acepta' if 'Accept' in t else 'rechaza')
    if t in ('ActJoinAllianceWar', 'ActRejectAllianceWar'):
        return '%s a la guerra de su alianza' % ('se une' if 'Join' in t else 'no se une')
    if t == 'ActIncRegionPop':
        return 'la población de %s cambia en %s' % (g('strRegion'), g('nIncrement'))
    if t == 'ActSetRegionController':
        return '%s pasa a estar controlada por %s' % (g('strRegion'), g('strController'))
    if t in ('ActAlterProperty', 'ActAlterPropertyImmed') and g('strPropName') == 'strCulture':
        return 'la región %s pasa a cultura %s (experimental)' % (g('nGOID'), g('strNewValue'))
    if t == 'ActActionRepeater':
        inner = [action_text(c, ctx) for c in objs(a)]
        return 'para cada uno de «%s»: %s' % (_name(g('pathManyObjects') or '', ctx), '; '.join(inner))
    if t in ('ActProposeSeparatePeaceConcessions', 'ActProposeAlliancePeaceConcessions', 'ActFormSeparatePeaceConcessions', 'ActFormAlliancePeaceConcessions'):
        return 'propone o firma la paz (%s)' % t.replace('Act', '')
    if t == 'ActDynProposeTreatyDef':
        return 'propone un tratado' + (' a %s' % g('strToCountry') if 'strToCountry' in P else '')
    vals = ', '.join('%s=%s' % (k, _ref(v, ctx)) for k, v in P.items())
    return '%s (%s)' % (t.replace('Act', ''), vals)


def _effects(holder, ctx, name):
    out = []
    for ce in objs(holder):
        if ce.get('name') == name and ce.get('type') == 'CustomEffectDefActions':
            out.append({'label': prop(ce, 'strLabel') or '', 'actions': [action_text(a, ctx) for a in objs(ce) if (a.get('type') or '').startswith('Act')]})
    return out


def _conditions(holder, ctx):
    out = []
    for rs in objs(holder):
        if rs.get('type') == 'AccessorRuleSet':
            rules = [rule_text(prop(r, 'expRession'), ctx) for r in rs.iter('object') if r.get('type') == 'RuleDefExpression']
            out.append({'label': prop(rs, 'strDebugLabel') or '', 'rules': _merge_exists(rules)})
    return out


def _merge_exists(rules):
    """«X existe» + «X está rendido» = «X no existe (rendido)»; «X existe» + «X no está rendido» = «X existe»."""
    out = []
    for r in rules:
        m = re.fullmatch(r'(.+?) (no )?está rendido \(sin territorio\)', r)
        if m and out and out[-1] == '%s existe' % m.group(1):
            out[-1] = '%s existe' % m.group(1) if m.group(2) else '%s no existe (rendido, sin territorio)' % m.group(1)
            continue
        out.append(r)
    return out


def _who(el):
    gen = next((g for g in objs(el) if g.get('name') == 'objPlayerGen'), None)
    if gen is None:
        return ''
    if gen.get('type') == 'PlayerGenAll':
        return 'todos los países'
    names = [p.get('value') for p in gen if p.tag == 'property' and p.get('name') == 'strName']
    return ', '.join(names) or gen.get('type')


def _texts(s, holder):
    """Título, descripción y efecto mostrados (ArgumentList «Display Data»): texto, id del elemento y si se puede editar."""
    out = {}
    for al in objs(holder):
        if al.get('type') != 'ArgumentList' or prop(al, 'strName') != 'Display Data':
            continue
        for a in objs(al):
            n = prop(a, 'strName')
            node = next((p for p in a if p.tag == 'property' and p.get('name') == 'strValue'), None)
            if node is None:
                out[n] = {'id': s.s.eid(a), 'text': '', 'editable': True}
            elif node.get('value') is not None:
                out[n] = {'id': s.s.eid(a), 'text': node.get('value'), 'editable': True}
            else:
                cf = node.get('computeFrom') or node.get('inheritFrom') or ''
                sid = re.search(r'F?SID\.[\w.]+', cf)
                txt = _string(s, sid.group(0)) if sid else None
                out[n] = {'id': s.s.eid(a), 'text': txt or cf, 'editable': False, 'sid': sid.group(0) if sid else None}
    return out


_FEEDBACK = {}


def _string(s, sid):
    if sid in s.strings:
        return s.strings[sid]
    if not _FEEDBACK:
        for f in ('stringTableFeedback.xml', 'stringTableGame.xml'):
            p = os.path.join(sc.GAME, 'system', 'locale', 'en', f)
            if os.path.exists(p):
                try:
                    for x in ET.parse(p).getroot():
                        if x.get('id'):
                            _FEEDBACK[x.get('id')] = x.get('value')
                except ET.ParseError:
                    pass
    return _FEEDBACK.get(sid)


def _trigger(el, ctx):
    te = next((t for t in objs(el) if t.get('name') in ('objTriggerEval', 'objEvalRule')), None)
    if te is None:
        return '', None
    t = te.get('type')
    if t == 'TriggerEvalRandomChance':
        pct = prop(te, 'nPercentChance') or '100'
        txt = 'cada turno en que se cumplan las condiciones' + ('' if pct == '100' else ', con %s %% de probabilidad' % pct)
    elif t == 'TriggerEvalUntilTurn':
        txt = 'se comprueba hasta el turno %s' % prop(te, 'nTurn')
    elif t == 'TriggerEvalUntilAnsweredPlayerDecision':
        txt = 'cada turno hasta que se responda la decisión «%s»' % prop(te, 'strDecisionType')
    elif t == 'TriggerEvalUntilAnsweredPlayerDecisionThisTurn':
        txt = 'hasta que se responda «%s» (se reinicia cada turno)' % prop(te, 'strDecisionType')
    else:
        txt = t
    return txt, te


def _index(s):
    idx = {}
    for el in s.all_types(EVENT_TYPES):
        lab = prop(el, 'strTypeLabel')
        if lab:
            idx.setdefault((el.get('type'), lab), el)
    return idx


def _fires_on(el):
    """Etiqueta del evento que dispara un PlayerDecisionTrigPlayEvent (condición strTypeLabel == '...')."""
    for r in el.iter('object'):
        if r.get('type') == 'RuleDefExpression':
            m = re.search(r"objScriptEvent\.strTypeLabel == '([^']*)'", prop(r, 'expRession') or '')
            if m:
                return m.group(1)
    return None


def describe(s, el):
    t = el.get('type')
    ctx = _ctx(el)
    st = s.s
    lab = prop(el, 'strTypeLabel') or ''
    d = {'id': st.eid(el), 'type': t, 'kind': KIND_ES.get(t, t), 'label': lab, 'who': _who(el), 'file': os.path.basename(st.doc_of.get(el, '')),
         'trigger': '', 'conditions': [], 'effects': [], 'choices': [], 'links': [], 'when': when(el)}
    d['class'], d['class_expl'], d['generic'] = event_class(s, el)
    trig_txt, te = _trigger(el, ctx)
    d['trigger'] = trig_txt
    d['conditions'] = _conditions(te if te is not None else el, ctx)
    if t in ('PlayerDecisionDef', 'DecisionPointDef') and te is not None:
        d['conditions'] = _conditions(el, ctx) + d['conditions']
    d['effects'] = _effects(el, ctx, 'objEffects')
    if t == 'PlayerDecisionDef':
        tx = _texts(s, el)
        d['title'], d['desc'] = tx.get('strTitle'), tx.get('strDesc')
        ai, ai_pct, pl = prop(el, 'strDefaultChoice'), prop(el, 'nDefaultChoicePercent'), prop(el, 'strDefaultChoicePlayer')
        d['ai'] = {'choice': ai, 'pct': ai_pct, 'player': pl}
        for ch in objs(el):
            if ch.get('type') != 'PlayerDecisionChoiceDefCustom':
                continue
            ctxt = _texts(s, ch)
            cl = prop(ch, 'strLabel')
            d['choices'].append({'id': st.eid(ch), 'label': cl, 'title': ctxt.get('strTitle'), 'desc': ctxt.get('strDesc'),
                                 'effects': _effects(ch, ctx, 'objChoiceEffects'), 'ai': cl == ai, 'player_default': cl == pl})
    idx = _index(s)
    link = lambda e, rel: d['links'].append({'id': st.eid(e), 'label': prop(e, 'strTypeLabel'), 'kind': KIND_ES.get(e.get('type')), 'rel': rel})
    if t == 'ScriptedEventDef':
        if te is not None and prop(te, 'strDecisionType'):
            dec = idx.get(('PlayerDecisionDef', prop(te, 'strDecisionType')))
            if dec is not None:
                link(dec, 'se repite hasta que se responda')
                d['outcome'] = _outcome(s, dec)
        for (k, l), e in idx.items():
            if k == 'PlayerDecisionTrigPlayEvent' and _fires_on(e) == lab:
                link(e, 'lo escucha')
                dec = idx.get(('PlayerDecisionDef', prop(e, 'strTypeToTrigger')))
                if dec is not None and not any(x['id'] == st.eid(dec) for x in d['links']):
                    link(dec, 'abre la ventana')
                    d.setdefault('outcome', _outcome(s, dec))
    elif t == 'PlayerDecisionTrigPlayEvent':
        src = _fires_on(el)
        ev = idx.get(('ScriptedEventDef', src)) if src else None
        if ev is not None:
            link(ev, 'se activa con')
        if not src:
            d['trigger'] = 'cuando ocurre: %s' % (prop(el, 'otPlayEventType') or '').replace('PlayEvent', '')
        dec = idx.get(('PlayerDecisionDef', prop(el, 'strTypeToTrigger')))
        if dec is not None:
            link(dec, 'abre la ventana')
    elif t == 'PlayerDecisionDef':
        for (k, l), e in idx.items():
            if k == 'PlayerDecisionTrigPlayEvent' and prop(e, 'strTypeToTrigger') == lab:
                link(e, 'la abre')
                src = _fires_on(e)
                if src and ('ScriptedEventDef', src) in idx:
                    link(idx[('ScriptedEventDef', src)], 'evento de origen')
    if d.get('outcome') and d['who'] and ',' not in d['who'] and d['who'] != 'todos los países':
        d['outcome'] = [x.replace(PLAYER, d['who']) for x in d['outcome']]
    return d


def _outcome(s, dec):
    """Lo que pasa al responder la ventana de un evento: [«botón»: efectos (IA)]."""
    ctx = _ctx(dec)
    ai = prop(dec, 'strDefaultChoice')
    out = []
    for ch in objs(dec):
        if ch.get('type') == 'PlayerDecisionChoiceDefCustom':
            t = (_texts(s, ch).get('strTitle') or {}).get('text') or prop(ch, 'strLabel')
            acts = [action_text(a, ctx) for e in objs(ch) if e.get('name') == 'objChoiceEffects' for a in objs(e) if (a.get('type') or '').startswith('Act')]
            out.append('«%s»: %s%s' % (t, '; '.join(acts) or 'nada', ' (la IA elige esta, %s %%)' % (prop(dec, 'nDefaultChoicePercent') or '100') if prop(ch, 'strLabel') == ai else ''))
    return out


def short(s, el):
    """Una línea para la lista: qué hace (los efectos o, si no tiene, el título de su ventana)."""
    t = el.get('type')
    ctx = None
    acts = []
    for a in el.iter('object'):
        if (a.get('type') or '').startswith('Act') and a.get('type') != 'ActActionRepeater':
            ctx = ctx if ctx is not None else _ctx(el)
            acts.append(action_text(a, ctx))
            if len(acts) >= 2:
                break
    if t == 'PlayerDecisionDef':
        tx = _texts(s, el).get('strTitle')
        if tx and tx['text']:
            return '«%s»%s' % (tx['text'][:60], (': ' + acts[0]) if acts else '')
    if t == 'PlayerDecisionTrigPlayEvent':
        return '→ %s' % prop(el, 'strTypeToTrigger')
    if not acts and t == 'ScriptedEventDef':       # sus efectos están en la ventana que abre
        te = next((x for x in objs(el) if x.get('name') == 'objTriggerEval'), None)
        dec = _decisions(s).get(prop(te, 'strDecisionType')) if te is not None else None
        if dec is not None:
            return 'ventana: ' + short(s, dec)
    return '; '.join(acts)


def _decisions(s):
    """Decisiones por etiqueta (se recalcula como mucho cada 3 s: la lista de la pestaña pide una por fila)."""
    import time
    c = getattr(s, '_dec_cache', None)
    if c is None or time.time() - c[0] > 3:
        c = (time.time(), {prop(e, 'strTypeLabel'): e for e in s.all_types(('PlayerDecisionDef',))})
        s._dec_cache = c
    return c[1]


# ---------------------------------------------------------------------------------------- clase de evento
# (patrón de la etiqueta, clase, explicación) — los GENERIC_/Generic_/SCRIPTEDEVENT_ vienen del juego (ScenarioDefaults)
EVENT_CLASSES = [
    (r'Lost_Homeland_Crisis', 'Crisis por perder la patria', 'el país pierde regiones de su patria: ventana de crisis (rendirse, seguir luchando…)'),
    (r'Restore_Original_Capital', 'Recuperar la capital original', 'el país reconquista su capital original: decide si la vuelve a hacer capital'),
    (r'CityNuked', 'Ciudad atacada con bomba atómica', 'respuesta de la IA cuando bombardean una de sus ciudades con una bomba atómica'),
    (r'LiberateCountryDecision', 'Estado aliado de la misma ideología', 'al conquistar la capital histórica de un país liberable, crearlo como aliado con la misma ideología'),
    (r'(Axis|Allies|Allied|Central)Eligibility', 'Unirse a un bando', 'un país decide si entra en el Eje, los Aliados o las Potencias Centrales'),
    (r'NearDefeat', 'País al borde de la derrota', 'el país está casi derrotado: rendición, paz separada o seguir'),
    (r'Liberation', 'Liberación de un país', 'un país liberado (o por liberar) vuelve a existir'),
    (r'Formable', 'Formar un país', 'un país que reúne ciertas regiones puede formar otro mayor'),
    (r'Puppet', 'Estado títere', 'crear un estado títere en territorio conquistado'),
    (r'Coup|Revolt|Revolution', 'Golpe o revuelta', 'cambio de gobierno o levantamiento interno'),
    (r'Research_?Breakthrough', 'Avance en investigación', 'puntos extra de investigación'),
    (r'ResearchSetback', 'Retraso en investigación', 'se pierden puntos de investigación'),
    (r'ProducerExpand', 'Ampliación de producción', 'una mina, pozo o granja produce más'),
    (r'WorkerMorale', 'Moral de los trabajadores', 'sube o baja la producción de las fábricas'),
    (r'TreatyProposed', 'Respuesta a un tratado', 'la IA responde a un tratado propuesto (alianza, paz, comercio, acceso…)'),
    (r'JoinAllianceWar', 'Unirse a la guerra de la alianza', 'un miembro de una alianza decide si entra en la guerra de sus aliados'),
    (r'ALERT_PathInvasion', 'Aviso de paso de tropas', 'tropas extranjeras quieren cruzar su territorio'),
    (r'PartisanUprising', 'Levantamiento partisano', 'aparecen partisanos en regiones ocupadas'),
    (r'^\d{4}$', 'Tecnología por año', 'al llegar la fecha todos completan la investigación de ese año'),
]
EFFECT_CLASSES = [('ActProposeDeclareWar', 'Declaración de guerra'), ('ActSetTradeRelations', 'Embargo / comercio'), ('ActSetCountryGov', 'Cambio de ideología'),
                  ('ActGrantIndependence', 'Crear o liberar un país'), ('ActCountrySurrender', 'Anexión'), ('ActIncResourceStock', 'Ayuda de recursos'),
                  ('ActTransferRegion', 'Cesión de regiones'), ('ActDevCreateUnits', 'Unidades nuevas'), ('ActAlterProperty', 'Cambio de cultura'),
                  ('ActIncDipRelations', 'Relaciones diplomáticas'), ('ActDevCompleteResearchProject', 'Investigación'), ('ActProposeDefensePact', 'Pacto defensivo')]


def is_generic(label):
    return bool(re.match(r'(GENERIC|Generic|SCRIPTEDEVENT)_', label or ''))


def event_class(s, el):
    """(clase, explicación, genérico): qué tipo de evento es, por su etiqueta o, si no se reconoce, por lo que hace."""
    lab = prop(el, 'strTypeLabel') or ''
    gen = is_generic(lab)
    for pat, name, expl in EVENT_CLASSES:
        if re.search(pat, lab):
            return name, expl, gen
    target = el
    if el.get('type') == 'ScriptedEventDef':
        te = next((x for x in objs(el) if x.get('name') == 'objTriggerEval'), None)
        dec = _decisions(s).get(prop(te, 'strDecisionType')) if te is not None else None
        target = dec if dec is not None else el
    elif el.get('type') == 'PlayerDecisionTrigPlayEvent':
        dec = _decisions(s).get(prop(el, 'strTypeToTrigger'))
        target = dec if dec is not None else el
    types = {a.get('type') for a in target.iter('object')}
    for t, name in EFFECT_CLASSES:
        if any((x or '').startswith(t) for x in types):
            return name, '', gen
    return 'Otro', '', gen


# ---------------------------------------------------------------------------------------- fecha / turno
def when(el):
    out = {}
    for r in el.iter('object'):
        if r.get('type') == 'RuleDefExpression':
            e = prop(r, 'expRession') or ''
            m = re.search(r'dateGameDate (GTE|GT|==) (\d\d/\d\d/\d{4})', e)
            if m:
                out['date'] = m.group(2)
            m = re.search(r'nGameTurn (==|GTE) (\d+)', e)
            if m:
                out['turn'] = int(m.group(2))
    return out


def set_when(s, i, date=None, turn=None):
    """Cambia la fecha (MM/DD/AAAA) o el turno de un evento (y de los de su cadena); convierte un embargo de turno en
    uno de fecha futura y al revés."""
    st = s.s
    el = st.get(i)
    if date and not re.fullmatch(r'\d\d/\d\d/\d{4}', date):
        raise ValueError('fecha no válida (MM/DD/AAAA)')
    chain = [el] + [st.get(x['id']) for x in describe(s, el)['links']]
    n = 0
    for e in chain:
        for rs in [r for r in e.iter('object') if r.get('type') == 'AccessorRuleSet']:
            rules = [r for r in objs(rs) if r.get('type') == 'RuleDefExpression']
            for r in rules:
                ex = prop(r, 'expRession') or ''
                if re.search(r'dateGameDate (GTE|GT|==) \d', ex) or re.search(r'nGameTurn (==|GTE) \d', ex):
                    acc = next((a for a in objs(rs) if a.get('type') in ('AccessorGetCurrentDate', 'AccessorGetCurrentTurn')), None)
                    if date:
                        if acc is not None and acc.get('type') != 'AccessorGetCurrentDate':
                            acc.set('type', 'AccessorGetCurrentDate')
                            st.set_prop(acc, 'pathOutput', '{Date:Single}scratch.dateGameDate')
                        st.set_prop(r, 'expRession', '{Date:Single}scratch.dateGameDate GTE %s' % date)
                        st.set_prop(rs, 'strDebugLabel', 'Date is %s or later' % date)
                    else:
                        if acc is not None and acc.get('type') != 'AccessorGetCurrentTurn':
                            acc.set('type', 'AccessorGetCurrentTurn')
                            st.set_prop(acc, 'pathOutput', '{int:Single}scratch.nGameTurn')
                        op = '==' if '==' in ex else 'GTE'
                        st.set_prop(r, 'expRession', '{int:Single}scratch.nGameTurn %s %d' % (op, int(turn)))
                        st.set_prop(rs, 'strDebugLabel', 'Turn is %d%s' % (int(turn), '' if op == '==' else ' or later'))
                    st.touch(rs)
                    n += 1
        te = next((t for t in objs(e) if t.get('type') == 'TriggerEvalUntilTurn'), None)
        if te is not None:
            if date:          # «hasta el turno N» con una fecha no tiene sentido: pasa a repetirse cada turno (con su condición)
                te.set('type', 'TriggerEvalRandomChance')
                for p in [p for p in te if p.tag == 'property' and p.get('name') == 'nTurn']:
                    te.remove(p)
                st.set_prop(te, 'nPercentChance', '100')
                st.touch(te, structural=True)
            else:
                st.set_prop(te, 'nTurn', str(int(turn) + 1))
    if not n:
        raise ValueError('este evento no tiene una condición de fecha o de turno que cambiar')
    return ['%s: ahora %s' % (prop(el, 'strTypeLabel'), ('desde el %s' % date) if date else ('en el turno %d' % int(turn)))]


def remove_chain(s, i):
    """Quita un evento y su cadena (disparador y decisión) si no los usa otro evento."""
    st = s.s
    el = st.get(i)
    d = describe(s, el)
    gone = [el] + [st.get(x['id']) for x in d['links']]
    notes = []
    for e in gone:
        if st.parent.get(e) is not None:
            st.remove(e)
            notes.append('quitado %s «%s»' % (KIND_ES.get(e.get('type'), e.get('type')), prop(e, 'strTypeLabel')))
    return notes


# ---------------------------------------------------------------------------------------- plantillas
def _x(v):
    return (str(v) if v is not None else '').replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')


def _w(x):
    return re.sub(r'\W', '', x or '')


def _country_set(label, names):
    """Condición «estos países existen y no están rendidos» (y deja sus variables para los efectos)."""
    acc, rules = [], []
    for n in names:
        v = 'objCountry' + _w(n)
        acc.append('<object type="AccessorGetCountry" name="objAccessors"><property name="pathOutput" value="{Object:Single:Country}scratch.%s"/>'
                   '<property name="strCountry" value="%s"/></object>' % (v, _x(n)))
        rules.append('<object type="RuleDefExpression" name="objRules"><property name="expRession" value="exists({Object:Single:Country}scratch.%s)"/></object>' % v)
        rules.append('<object type="RuleDefExpression" name="objRules"><property name="expRession" value="!{Object:Single:Country}scratch.%s.bSurrendered"/></object>' % v)
    return _set(label, ''.join(acc) + ''.join(rules))


def _set(label, inner):
    return ('<object type="AccessorRuleSet" name="objConditions"><property name="strDebugLabel" value="%s"/>'
            '<property name="pathPlayer" value="{Object:Single:Player}scratch.objPlayer"/>%s</object>' % (_x(label), inner))


def _when_set(w):
    if w.get('date'):
        if not re.fullmatch(r'\d\d/\d\d/\d{4}', w['date']):
            raise ValueError('fecha no válida (MM/DD/AAAA)')
        return _set('Date is %s or later' % w['date'],
                    '<object type="AccessorGetCurrentDate" name="objAccessors"><property name="pathOutput" value="{Date:Single}scratch.dateGameDate"/></object>'
                    '<object type="RuleDefExpression" name="objRules"><property name="expRession" value="{Date:Single}scratch.dateGameDate GTE %s"/></object>' % w['date'])
    if w.get('turn'):
        return _set('Turn is %d or later' % int(w['turn']),
                    '<object type="AccessorGetCurrentTurn" name="objAccessors"><property name="pathOutput" value="{int:Single}scratch.nGameTurn"/></object>'
                    '<object type="RuleDefExpression" name="objRules"><property name="expRession" value="{int:Single}scratch.nGameTurn GTE %d"/></object>' % int(w['turn']))
    return ''


def _chance_set(pct):
    pct = int(pct or 100)
    if pct >= 100:
        return ''
    return _set('Random %d percent' % pct,
                '<object type="AccessorGetRandomNumberSimple" name="objAccessors"><property name="pathOutput" value="{int:Single}scratch.nRandomRoll"/>'
                '<property name="nMinValue" value="1"/><property name="nMaxValue" value="100"/></object>'
                '<object type="RuleDefExpression" name="objRules"><property name="expRession" value="{int:Single}scratch.nRandomRoll LTE %d"/></object>' % pct)


def _not_at_war_set(a, b):
    va, vb = 'objCountry' + _w(a), 'objCountry' + _w(b)
    return _set('%s and %s are not at war' % (a, b),
                '<object type="AccessorGetCountry" name="objAccessors"><property name="pathOutput" value="{Object:Single:Country}scratch.%s"/><property name="strCountry" value="%s"/></object>'
                '<object type="AccessorGetCountry" name="objAccessors"><property name="pathOutput" value="{Object:Single:Country}scratch.%s"/><property name="strCountry" value="%s"/></object>'
                '<object type="AccessorIsAtWar" name="objAccessors"><property name="pathOutput" value="{bool:Single}scratch.b%s%sWar"/>'
                '<property name="nCountryID" inheritFrom="{Object:Single:Country}scratch.%s.nCountryID"/><property name="nEnemyCountryID" inheritFrom="{Object:Single:Country}scratch.%s.nCountryID"/></object>'
                '<object type="RuleDefExpression" name="objRules"><property name="expRession" value="!{bool:Single}scratch.b%s%sWar"/></object>'
                % (va, _x(a), vb, _x(b), _w(a), _w(b), va, vb, _w(a), _w(b)))


def _action(spec, owner):
    """(xml de la acción, países que deben existir, regiones que necesita, condiciones extra)."""
    k = spec.get('type')
    g = lambda n, d=None: (spec.get(n) if spec.get(n) not in (None, '') else d)
    if k == 'war':
        a, b = g('from', owner), g('to')
        return ('<object type="ActProposeDeclareWar" name="objActions"><property name="strFromCountry" value="%s"/><property name="strToCountry" value="%s"/></object>' % (_x(a), _x(b)),
                [a, b], [], [_not_at_war_set(a, b)], '%s declares war on %s' % (a, b))
    if k in ('embargo', 'lift'):
        rel = 'TRADE_RELATIONS_EMBARGOED' if k == 'embargo' else 'TRADE_RELATIONS_NEUTRAL'
        return ('<object type="ActSetTradeRelations" name="objActions"><property name="strCountry" value="%s"/><property name="eTradeRelations" value="%s"/></object>' % (_x(g('to')), rel),
                [g('to')], [], [], '%s %s %s' % (owner, 'embargoes' if k == 'embargo' else 'resumes trade with', g('to')))
    if k == 'gov':
        if not g('gov'):
            raise ValueError('elige la ideología')
        return ('<object type="ActSetCountryGov" name="objActions"><property name="strCountry" value="%s"/><property name="strGovType" value="%s"/></object>' % (_x(g('country', owner)), _x(g('gov'))),
                [g('country', owner)], [], [], '%s becomes %s' % (g('country', owner), g('gov')))
    if k == 'resource':
        n = int(g('amount', 0))
        xml = '<object type="ActIncResourceStock" name="objActions"><property name="strCountry" value="%s"/><property name="strResource" value="%s"/><property name="nIncrement" value="%d"/></object>' % (_x(g('country', owner)), _x(g('resource')), n)
        must = [g('country', owner)]
        if g('from'):
            xml += '<object type="ActIncResourceStock" name="objActions"><property name="strCountry" value="%s"/><property name="strResource" value="%s"/><property name="nIncrement" value="%d"/></object>' % (_x(g('from')), _x(g('resource')), -n)
            must.append(g('from'))
        return xml, must, [], [], '%s receives %d %s%s' % (g('country', owner), n, g('resource'), (' from %s' % g('from')) if g('from') else '')
    if k == 'independence':
        return ('<object type="ActGrantIndependence" name="objActions"><property name="strFromCountry" value="%s"/><property name="strToCountry" value="%s"/></object>' % (_x(g('from', owner)), _x(g('to'))),
                [g('from', owner)], [], [], '%s grants independence to %s' % (g('from', owner), g('to')))
    if k == 'annex':
        return ('<object type="ActCountrySurrender" name="objActions"><property name="strLosingCountryName" value="%s"/><property name="strWinningCountryName" value="%s"/></object>' % (_x(g('loser')), _x(g('winner', owner))),
                [g('loser'), g('winner', owner)], [], [], '%s annexes %s' % (g('winner', owner), g('loser')))
    if k == 'units':
        return ('<object type="ActDevCreateUnits" name="objActions"><property name="strCountryName" value="%s"/><property name="strUnitTemplate" value="%s"/>'
                '<property name="strRegionName" value="%s"/><property name="strUnitName" value="%s"/><property name="nNumUnits" value="%d"/></object>'
                % (_x(g('country', owner)), _x(g('template')), _x(g('region')), _x(g('name', 'New Army')), int(g('n', 1))),
                [g('country', owner)], [], [], '%s raises %s %s' % (g('country', owner), g('n', 1), g('template')))
    if k == 'flag':
        if not g('flag'):
            raise ValueError('elige la bandera')
        return ('<object type="ActSetCountryFlagName" name="objActions"><property name="strCountryName" value="%s"/><property name="strFlagName" value="%s"/></object>' % (_x(g('country', owner)), _x(g('flag'))),
                [g('country', owner)], [], [], '%s changes its flag' % g('country', owner))
    if k == 'dip':
        a, b = g('a', owner), g('b')
        return ('<object type="ActIncDipRelations" name="objActions"><property name="nSourceCountryID" inheritFrom="{Object:Single:Country}scratch.objCountry%s.nCountryID"/>'
                '<property name="nTargetCountryID" inheritFrom="{Object:Single:Country}scratch.objCountry%s.nCountryID"/><property name="nAmount" value="%d"/></object>' % (_w(a), _w(b), int(g('amount', 100))),
                [a, b], [], [], 'Relations %s - %s change' % (a, b))
    if k == 'culture':
        regs = [r for r in (spec.get('regions') or []) if r]
        xml = ''.join('<object type="ActAlterProperty" name="objActions"><property name="nGOID" inheritFrom="{Object:Single:Region}scratch.objRegion%s.nGameObject"/>'
                      '<property name="strPropName" value="strCulture"/><property name="strNewValue" value="%s"/></object>' % (_w(r), _x(g('culture'))) for r in regs)
        return xml, [], regs, [], '%s now have %s culture' % (', '.join(regs), g('culture'))
    if k == 'none':
        return '', [], [], [], ''
    raise ValueError('efecto desconocido: %s' % k)


def event_add(s, i, what, spec, choice=None):
    """Añade a un evento existente un efecto (al evento o a una de sus elecciones) o una condición.
    what: 'effect' | 'condition'. spec (efecto): como en las plantillas ({'type': 'war', 'to': …}).
    spec (condición): {'type': 'exists', 'countries': [...]} | {'type': 'when', 'date'|'turn'} | {'type': 'chance', 'pct'}
    | {'type': 'notwar', 'a', 'b'}. Devuelve notas."""
    st = s.s
    el = st.get(i)
    if el is None:
        raise ValueError('ese evento ya no existe')
    _t, te = _trigger(el, _ctx(el))
    cond_holder = te if te is not None else el            # donde están sus condiciones (y las variables de los países)
    have = {prop(a, 'pathOutput') for a in cond_holder.iter('object') if a.get('type') == 'AccessorGetCountry'}
    owner = (_who(el) or '').split(',')[0].strip() or None
    if owner not in s.countries():                        # «todos los países» u otro texto: sin país propio
        owner = None
    xmls, notes = [], []
    if what == 'effect':
        xml, must, regs, extra, txt = _action(spec, owner)
        if not xml:
            raise ValueError('ese efecto no hace nada')
        need = [c for c in dict.fromkeys(x for x in must if x) if '{Object:Single:Country}scratch.objCountry' + _w(c) not in have]
        if need:                                          # los efectos usan las variables de los países: se leen en las condiciones
            xmls.append(_country_set('%s exist' % ', '.join(need), need))
        if regs:
            xmls.append(_region_set(regs))
        xmls += [x for x in extra if x]
        if choice is not None:
            holder = st.get(choice)
            name = 'objChoiceEffects'
        else:
            holder, name = el, 'objEffects'
        ce = next((c for c in objs(holder) if c.get('type') == 'CustomEffectDefActions' and c.get('name') == name), None)
        if ce is None:
            ce = ET.Element('object', {'type': 'CustomEffectDefActions', 'name': name})
            ET.SubElement(ce, 'property', {'name': 'strLabel', 'value': (prop(holder, 'strLabel') or prop(el, 'strTypeLabel') or 'Effect') + ' Effects'})
            st.attach(ce, holder)
        for a in ET.fromstring('<x>%s</x>' % xml):
            st.attach(a, ce)
        notes.append('efecto añadido: %s' % txt)
    elif what == 'condition':
        k = spec.get('type')
        if k == 'exists':
            cs = [c for c in spec.get('countries') or [] if c]
            if not cs:
                raise ValueError('elige al menos un país')
            xmls.append(_country_set('%s exist' % ', '.join(cs), cs))
            notes.append('condición: existen %s' % ', '.join(cs))
        elif k == 'when':
            w = _when_set({'date': spec.get('date'), 'turn': spec.get('turn')})
            if not w:
                raise ValueError('pon una fecha MM/DD/AAAA o un turno')
            xmls.append(w)
            notes.append('condición: desde %s' % (spec.get('date') or 'el turno %s' % spec.get('turn')))
        elif k == 'chance':
            c = _chance_set(spec.get('pct'))
            if not c:
                raise ValueError('la probabilidad debe ser menor que 100 %')
            xmls.append(c)
            notes.append('condición: %s %% de probabilidad por turno' % spec.get('pct'))
        elif k == 'notwar':
            if not spec.get('a') or not spec.get('b') or spec['a'] == spec['b']:
                raise ValueError('elige dos países distintos')
            xmls.append(_not_at_war_set(spec['a'], spec['b']))
            notes.append('condición: %s y %s no están en guerra' % (spec['a'], spec['b']))
        else:
            raise ValueError('condición desconocida: %s' % k)
    else:
        raise ValueError('¿efecto o condición?')
    kids = list(cond_holder)
    for x in xmls:                                        # las condiciones van junto a las demás (antes de los efectos)
        rs = ET.fromstring(x)
        last = [n for n, c in enumerate(kids) if c.tag == 'object' and c.get('name') == 'objConditions']
        st.attach(rs, cond_holder, index=(last[-1] + 1) if last else None)
        kids = list(cond_holder)
    return notes


def _region_set(regs):
    if not regs:
        return ''
    inner = ''.join('<object type="AccessorGetRegion" name="objAccessors"><property name="pathOutput" value="{Object:Single:Region}scratch.objRegion%s"/>'
                    '<property name="strName" value="%s"/></object>' % (_w(r), _x(r)) for r in regs)
    inner += ''.join('<object type="RuleDefExpression" name="objRules"><property name="expRession" value="exists({Object:Single:Region}scratch.objRegion%s)"/></object>' % _w(r) for r in regs)
    return _set('Regions exist', inner)


def _arg_list(title, desc, effect=None):
    el = lambda n, v: ('<object type="ArgumentElementString" name="objArgElements"><property name="strName" value="%s"/>%s</object>'
                       % (n, '<property name="strValue" value="%s"/>' % _x(v) if v is not None else ''))
    return ('<object type="ArgumentList" name="objArgLists"><property name="strName" value="Display Data"/>%s%s%s</object>'
            % (el('strTitle', title), el('strDesc', desc), el('strEffect', effect) if effect is not None else ''))


def create_decision(s, owner, title, text, choices, when=None, pct=100, ai_choice=0, ai_pct=100, label=None, extra_conditions=None):
    """Evento con ventana (como los mods): ScriptedEventDef (se repite hasta que se responda) + disparador + decisión.
    choices: [{'title', 'desc', 'effects': [spec, …]}]; la IA elige 'ai_choice' con 'ai_pct' %."""
    countries = s.countries()
    if owner not in countries:
        raise ValueError('no existe el país «%s»' % owner)
    if not choices:
        raise ValueError('la decisión necesita al menos una elección')
    when = when or {}
    st = s.s
    path, notes = sc._events_doc(s)
    shared = next(o for o in st.docs[path].getroot().iter('object') if o.get('type') == 'MESharedData')
    used = {prop(e, 'strTypeLabel') for e in s.all_types(EVENT_TYPES)}
    base = label or 'MOD_%s_%s' % (_w(owner), _w(title)[:40] or 'Event')
    lab, k = base, 2
    while lab in used or lab + '_Decision' in used:
        lab, k = '%s_%d' % (base, k), k + 1
    dec = lab + '_Decision'
    must, regs, extra, ch_xml = [owner], [], list(extra_conditions or []), []
    labels = []
    for n, ch in enumerate(choices):
        acts, effs = [], []
        for spec in ch.get('effects') or []:
            xml, m, r, ex, eff = _action(spec, owner)
            for c in m:
                if c and c not in countries:
                    raise ValueError('no existe el país «%s»' % c)
                if not c:
                    raise ValueError('falta un país en el efecto «%s»' % spec.get('type'))
            acts.append(xml)
            effs.append(eff)
            must += [c for c in m if c and c in countries and c not in must]
            regs += [x for x in r if x not in regs]
            extra += [x for x in ex if x not in extra]
        cl = 'Choice%d_%s' % (n + 1, _w(ch.get('title'))[:30] or 'OK')
        while cl in labels:
            cl += 'x'
        labels.append(cl)
        eff_xml = ('<object type="CustomEffectDefActions" name="objChoiceEffects"><property name="strLabel" value="%s"/>%s</object>'
                   % (_x('; '.join(e for e in effs if e) or ch.get('title') or 'OK'), ''.join(acts))) if any(acts) else ''
        ch_xml.append('<object type="PlayerDecisionChoiceDefCustom" name="objChoiceDefs"><property name="strLabel" value="%s"/>%s%s</object>'
                      % (cl, _arg_list(ch.get('title') or 'OK', ch.get('desc') or '', ''), eff_xml))
    land = {prop(r, 'strName') for r in s.regions(sea=False)}
    for r in regs:
        if r not in land:
            raise ValueError('no existe la región «%s»' % r)
    exist = _country_set('Countries exist', must) + _region_set(regs)
    conds = _when_set(when) + _chance_set(pct) + exist + ''.join(extra)
    ai_i = max(0, min(len(labels) - 1, int(ai_choice or 0)))
    ev = ('<object type="ScriptedEventDef" name="objScriptedEventDefs"><property name="strTypeLabel" value="%s"/>'
          '<property name="pathPlayer" value="{Object:Single:Player}scratch.objPlayer"/>'
          '<object type="PlayerGenNames" name="objPlayerGen"><property name="strName" value="%s"/></object>'
          '<object type="TriggerEvalUntilAnsweredPlayerDecision" name="objTriggerEval"><property name="strDecisionType" value="%s"/>%s</object>'
          '<object type="ArgumentList" name="objArgLists"><property name="strName" value="Display Data"/></object></object>' % (_x(lab), _x(owner), _x(dec), conds))
    trig = ('<object type="PlayerDecisionTrigPlayEvent" name="objPlayerDecisionTriggers"><property name="pathPlayer" value="{Object:Single:Player}scratch.objPlayer"/>'
            '<property name="strTypeLabel" value="%s_PlayEvent"/><property name="strTypeToTrigger" value="%s"/>'
            '<property name="otPlayEventType" value="PlayEventNewScriptedEvent"/><property name="pathPlayEvent" value="{Object:Single:PlayEventNewScriptedEvent}scratch.objScriptEvent"/>'
            '<object type="TriggerEvalRandomChance" name="objEvalRule"><property name="nPercentChance" value="100"/>%s</object>'
            '<object type="PlayerGenNames" name="objPlayerGen"><property name="strName" value="%s"/></object></object>'
            % (_x(dec), _x(dec), _set('Scripted Event is %s' % lab, '<object type="RuleDefExpression" name="objRules"><property name="expRession" '
                                       'value="{Object:Single:PlayEventNewScriptedEvent}scratch.objScriptEvent.strTypeLabel == \'%s\'"/></object>' % _x(lab)), _x(owner)))
    pdef = ('<object type="PlayerDecisionDef" name="objPlayerDecisionDefs"><property name="pathPlayer" value="{Object:Single:Player}scratch.objPlayer"/>'
            '<property name="strTypeLabel" value="%s"/><property name="strDefaultChoice" value="%s"/><property name="nDefaultChoicePercent" value="%d"/>'
            '<property name="strDefaultChoicePlayer" value="%s"/>%s%s%s</object>'
            % (_x(dec), labels[ai_i], max(0, min(100, int(ai_pct))), labels[0], exist, ''.join(ch_xml), _arg_list(title or lab, text or '')))
    ids = []
    for xml in (ev, trig, pdef):
        e = ET.fromstring(xml)
        st.attach(e, shared, path=path)
        ids.append(st.eid(e))
    s._dec_cache = None
    notes.append('evento «%s» añadido (con su ventana «%s»)' % (lab, title or lab))
    return ids[0], notes


TEMPLATE_KINDS = ('war', 'embargo', 'gov', 'resource', 'units', 'culture', 'independence', 'decision', 'liberate')


def create_template(s, kind, p):
    """Plantillas de la pestaña Eventos; p = datos del formulario. Devuelve (id, notas)."""
    owner = p.get('owner')
    w = {'date': p.get('date') or None, 'turn': int(p['turn']) if str(p.get('turn') or '').strip() else None}
    pct = int(p.get('pct') or 100)
    if kind == 'liberate':
        return create_liberate(s, p.get('gov'))
    if kind == 'decision':
        return create_decision(s, owner, p.get('title'), p.get('text'), p.get('choices') or [], w, pct, p.get('ai_choice', 0), p.get('ai_pct', 100))
    spec = dict(p.get('effect') or {})
    spec['type'] = {'resource': 'resource', 'culture': 'culture'}.get(kind, kind)
    if kind == 'gov':
        owner = owner or spec.get('country')
        spec.setdefault('country', owner)
    xml, _m, _r, _e, eff = _action(spec, owner)
    title = p.get('title') or eff
    if p.get('ask'):        # el jugador humano de ese país elige en una ventana; la IA hace el efecto con ai_pct %
        yes = p.get('yes') or {'war': 'Declare war', 'embargo': 'Declare the embargo'}.get(kind, 'Accept')
        no = p.get('no') or {'war': 'Not now', 'embargo': 'Keep trading'}.get(kind, 'Refuse')
        return create_decision(s, owner, title, p.get('text') or '', [{'title': yes, 'desc': '', 'effects': [spec]}, {'title': no, 'desc': '', 'effects': []}],
                               w, pct, 0, int(p['ai_pct']) if str(p.get('ai_pct', '')).strip() != '' else 100)
    return create_decision(s, owner, title, p.get('text') or '', [{'title': 'OK', 'desc': '', 'effects': [spec]}], w, pct)


def _govs(s):
    return {prop(g, 'strName') for g in s.all('GovTypeTemplate')} | {prop(c, 'strGovType') for c in s.countries().values()}


def create_liberate(s, gov):
    """«Crear un estado aliado de la misma ideología» al conquistar la capital histórica de un país liberable, para una
    ideología que no lo tiene: copia la decisión GENERIC_Democratic… del escenario (los textos sirven, usan @GovType@)."""
    if not gov:
        raise ValueError('elige la ideología')
    if gov not in _govs(s):
        raise ValueError('no existe la ideología «%s» en el escenario' % gov)
    idx = _index(s)
    lab = 'GENERIC_%sLiberateCountryDecision' % _w(gov)
    if ('PlayerDecisionDef', lab) in idx:
        raise ValueError('la ideología %s ya tiene su decisión de crear un estado aliado (%s)' % (gov, lab))
    src = 'GENERIC_DemocraticLiberateCountryDecision'
    src_d = idx.get(('PlayerDecisionDef', src))
    src_t = next((e for (k, l), e in idx.items() if k == 'PlayerDecisionTrigPlayEvent' and prop(e, 'strTypeToTrigger') == src), None)
    if src_d is None or src_t is None:      # algunos mods la quitan: se copia de ScenarioDefaults (solo se lee)
        for f in (os.path.join(os.path.dirname(sc.SCEN_ROOT), 'ScenarioDefaults', 'sharedData.xml'),
                  os.path.join(sc.GAME, 'Modern Europe', 'system', 'ScenarioDefaults', 'sharedData.xml')):
            if os.path.exists(f):
                for e in ET.parse(f).getroot().iter('object'):
                    if e.get('type') == 'PlayerDecisionDef' and prop(e, 'strTypeLabel') == src and src_d is None:
                        src_d = e
                    if e.get('type') == 'PlayerDecisionTrigPlayEvent' and prop(e, 'strTypeToTrigger') == src and src_t is None:
                        src_t = e
                break
    if src_d is None or src_t is None:
        raise ValueError('no se encuentra la decisión %s (ni en el escenario ni en ScenarioDefaults) para copiarla' % src)
    st = s.s
    path, notes = sc._events_doc(s)
    shared = next(o for o in st.docs[path].getroot().iter('object') if o.get('type') == 'MESharedData')
    ids = []
    for src in (src_t, src_d):
        new = copy.deepcopy(src)
        for p in new.iter('property'):
            for att in ('value',):
                v = p.get(att)
                if v and p.get('name') in ('strTypeLabel', 'strTypeToTrigger'):
                    p.set(att, v.replace('GENERIC_Democratic', 'GENERIC_' + _w(gov)))
                elif v and p.get('name') == 'expRession' and "strGovType == 'Democratic'" in v:
                    p.set(att, v.replace("'Democratic'", "'%s'" % gov))
                elif v == 'Player is Democratic Gov Type':
                    p.set(att, 'Player is %s Gov Type' % gov)
        st.attach(new, shared, path=path)
        ids.append(st.eid(new))
    notes.append('decisión «%s» añadida: un país %s que conquiste la capital histórica de un país liberable podrá crearlo como aliado %s' % (lab, gov, gov))
    return ids[1], notes


# ---------------------------------------------------------------------------------------- IA (player<País>.xml)
GOAL_ES = {
    'HGoalHelpCountryWinWar': 'Si {B} ataca a {A}, {me} ayuda a {A} (dinero, armas y, si puede, entra en la guerra)',
    'HGoalConquerCountry': '{A} quiere conquistar {B}',
    'HGoalLiberateCountry': '{A} quiere liberar {B}',
    'HGoalMaintainIndepend': '{A} quiere mantener su independencia frente a {B}',
    'HGoalOverpowerCountry': '{A} quiere ser militarmente más fuerte que {B}',
    'HGoalWeakenCountry': '{A} quiere debilitar a {B}',
    'HGoalAcquireRegions': '{A} quiere conseguir las regiones de la lista «{RegionList}»',
    'HGoalProtectRegions': '{A} quiere proteger las regiones de la lista «{RegionList}»',
    'HGoalKeepRegions': '{A} quiere conservar las regiones de la lista «{RegionList}»',
    'HGoalLiberateRegions': '{A} quiere liberar las regiones de la lista «{RegionList}»',
    'HGoalFormAlliance': '{A} quiere aliarse con {TargetCountryNames}',
    'HGoalAvoidWar': '{A} quiere evitar la guerra con {TargetCountryNames}',
    'HGoalTurnOneUnitOrder': 'en el primer turno, la unidad {UnitName} recibe la orden {UnitOrder} ({ObjectiveName})',
}
GOAL_EXPL = {
    'HGoalHelpCountryWinWar': 'Support this country through financial aid, arms trades, and, possibly, your intervention in its war.',
    'HGoalConquerCountry': 'Conquer this country.',
}


def _pd(s, country):
    pd = next((p for p in s.all('MEPlayerData') if prop(p, 'strOwner') == country), None)
    if pd is None:
        raise ValueError('no hay datos de jugador (player%s.xml) para %s' % (country, country))
    return pd


def _blocks(pd):
    out = {}
    for b in objs(pd):
        if b.get('name') == 'objParameterBlocks' and prop(b, 'strName'):
            out[prop(b, 'strName')] = b
    return out


def _block_vals(b):
    vals = {}
    if b is None:
        return vals
    for x in objs(b):
        n = prop(x, 'strName')
        if x.get('type') == 'StringParameter':
            vals[n] = prop(x, 'strValue')
        else:
            vs = [p.get('value') for p in x if p.tag == 'property' and p.get('name') not in ('strName',)]
            vals[n] = ', '.join(v for v in vs if v)
    return vals


def _multi(el, name):
    return [p.get('value') for p in el if p.tag == 'property' and p.get('name') == name and p.get('value')]


def _set_multi(st, el, name, values):
    for p in [p for p in el if p.tag == 'property' and p.get('name') == name]:
        el.remove(p)
    kids = list(el)
    idx = max([k for k, c in enumerate(kids) if c.tag == 'property'] or [-1]) + 1
    for v in values:
        n = ET.Element('property', {'name': name, 'value': v})
        el.insert(idx, n)
        idx += 1
        st.parent[n] = el
        st.doc_of[n] = st.doc_of[el]
    st.touch(el, structural=True)


def _op_text(me, op):
    tg = _multi(op, 'strTargetCountries')
    rl = prop(op, 'strTargetRegionList')
    a, b = _multi(op, 'strWarTriggerCountriesA'), _multi(op, 'strWarTriggerCountriesB')
    t = '%s ataca a %s' % (me, ', '.join(tg) or '?') if tg else '%s ataca las regiones de «%s»' % (me, rl or '?')
    if tg and rl:
        t += ' (regiones de «%s»)' % rl
    if a or b:
        t += ' cuando %s esté en guerra con %s' % (' o '.join(a) or '?', ' o '.join(b) or '?')
    if prop(op, 'dateTrigger'):
        t += ', desde el %s' % prop(op, 'dateTrigger')
    if prop(op, 'dateExpires'):
        t += ' hasta el %s' % prop(op, 'dateExpires')
    pre = _multi(op, 'strPrereqOperations')
    if pre:
        t += ', después de la operación %s' % ', '.join(pre)
    if prop(op, 'bSuppressesAggression') == 'true':
        t += ' (mientras tanto no busca otras guerras)'
    return t


def ai_rules(s, country):
    st = s.s
    pd = _pd(s, country)
    blocks = _blocks(pd)
    out = {'country': country, 'player_id': st.eid(pd), 'goals': [], 'warplans': [], 'allegiance': [], 'events': [],
           'triggers': [dict(t, text=_trigger_text(country, t)) for t in triggers(s, country)]}
    for g in objs(pd):
        if g.get('type') != 'HistoricalGoalRef':
            continue
        t = prop(g, 'otGoalType') or ''
        vals = _block_vals(blocks.get(prop(g, 'strTargetBlockName')))
        txt = GOAL_ES.get(t, t.replace('HGoal', '') + ' {A} {B}')
        rep = {'me': country, 'A': vals.get('CountryAName') or country, 'B': vals.get('CountryBName') or '?'}
        rep.update({k: v for k, v in vals.items() if k not in ('CountryAName', 'CountryBName')})
        txt = re.sub(r'\{(\w+)\}', lambda m: rep.get(m.group(1), '?'), txt)
        if prop(g, 'bActive') == 'false':
            txt += ' (desactivada)'
        out['goals'].append({'id': st.eid(g), 'type': t, 'text': txt, 'a': vals.get('CountryAName'), 'b': vals.get('CountryBName'),
                             'editable': t in ('HGoalHelpCountryWinWar', 'HGoalConquerCountry', 'HGoalOverpowerCountry', 'HGoalLiberateCountry')})
    ai = next((x for x in objs(pd) if x.get('type') == 'MEAIData'), None)
    if ai is not None:
        for wp in objs(ai):
            if wp.get('type') == 'WarPlan':
                ops = [{'id': st.eid(op), 'text': _op_text(country, op), 'name': prop(op, 'strName'), 'targets': _multi(op, 'strTargetCountries'),
                        'region_list': prop(op, 'strTargetRegionList') or '', 'trig_a': _multi(op, 'strWarTriggerCountriesA'),
                        'trig_b': _multi(op, 'strWarTriggerCountriesB'), 'date': prop(op, 'dateTrigger') or '', 'expires': prop(op, 'dateExpires') or ''}
                       for op in objs(wp) if op.get('type') == 'WarPlanOperation']
                out['warplans'].append({'id': st.eid(wp), 'name': prop(wp, 'strName'), 'weight': prop(wp, 'nWeight'), 'ops': ops})
            elif wp.get('type') == 'ForceAllegiancePlan':
                tg = _multi(wp, 'strTargetCountries')
                txt = 'Cuando %s esté en guerra con %s, %s presiona a %s para que se unan a su bando (%s–%s tratados cada %s–%s turnos%s)' % (
                    prop(wp, 'strWarTriggerCountryA'), prop(wp, 'strWarTriggerCountryB'), country, ', '.join(tg),
                    prop(wp, 'nMinTreatyCount'), prop(wp, 'nMaxTreatyCount'), prop(wp, 'nMinTreatyInterval'), prop(wp, 'nMaxTreatyInterval'),
                    ('; %s %% de declararles la guerra si no' % prop(wp, 'nDeclareWarPct')) if prop(wp, 'nDeclareWarPct') not in (None, '0') else '')
                out['allegiance'].append({'id': st.eid(wp), 'text': txt})
    # eventos de este país con embargo, guerra o intervención
    for ev in s.all('ScriptedEventDef'):
        if country not in _who(ev).split(', '):
            continue
        d = describe(s, ev)
        acts = [a for e in d['effects'] for a in e['actions']]
        for l in d['links']:
            if l['kind'] == KIND_ES['PlayerDecisionDef']:
                dd = describe(s, st.get(l['id']))
                for c in dd['choices']:
                    acts += [a for e in c['effects'] for a in e['actions']]
        acts = [a.replace(PLAYER, country) for a in acts]
        kind = 'embargo' if any(' pone embargo' in a for a in acts) else 'guerra' if any('declara la guerra' in a for a in acts) else None
        if kind:
            cond = [r for c in d['conditions'] for r in c['rules'] if 'en guerra con' in r and not r.startswith(country)]
            out['events'].append({'id': d['id'], 'label': d['label'], 'kind': kind, 'actions': acts, 'when': d['when'], 'conditions': cond,
                                  'text': ('Si ' + ' y '.join(cond) + ': ' if cond else '') + '; '.join(acts) +
                                          (' (desde el %s)' % d['when']['date'] if d['when'].get('date') else ' (turno %s)' % d['when']['turn'] if d['when'].get('turn') else '')})
    return out


def _next_goal_num(pd):
    nums = [int(m.group(1)) for b in objs(pd) for m in [re.search(r'(\d+)$', prop(b, 'strName') or '')] if m]
    return max(nums or [0]) + 1


def _insert_after_last(st, pd, el, pred):
    kids = list(pd)
    idx = max([k for k, c in enumerate(kids) if c.tag == 'object' and pred(c)] or [-1])
    if idx < 0:
        idx = max([k for k, c in enumerate(kids) if c.tag == 'property'] or [-1])
    st.attach(el, pd, index=idx + 1)


def ai_goal_set(s, country, gtype, a, b, gid=None):
    """Añade (o cambia) una meta de la IA con dos países (p. ej. HGoalHelpCountryWinWar: si B ataca a A, ayuda a A)."""
    st = s.s
    countries = s.countries()
    for c in (a, b):
        if c not in countries:
            raise ValueError('no existe el país «%s»' % c)
    pd = _pd(s, country)
    if gid:
        g = st.get(gid)
        blk = _blocks(pd).get(prop(g, 'strTargetBlockName'))
        if blk is None:
            raise ValueError('la meta no tiene su bloque de países')
        for x in objs(blk):
            if prop(x, 'strName') == 'CountryAName':
                st.set_prop(x, 'strValue', a)
            if prop(x, 'strName') == 'CountryBName':
                st.set_prop(x, 'strValue', b)
        return st.eid(g), ['meta de %s cambiada: A = %s, B = %s' % (country, a, b)]
    n = _next_goal_num(pd)
    g = ET.fromstring('<object type="HistoricalGoalRef" name="objHistoricGoalRefs"><property name="strName" value="Title%d"/>'
                      '<property name="strDescription" value=""/><property name="strExplanation" value="%s"/><property name="bActive" value="true"/>'
                      '<property name="bAIOnly" value="true"/><property name="otGoalType" value="%s"/><property name="strTargetBlockName" value="GoalRefTarget%d"/>'
                      '<property name="strHistoricBlockName" value="GoalRefHistory%d"/><property name="nMaxDelay" value="0"/></object>'
                      % (n, _x(GOAL_EXPL.get(gtype, '')), _x(gtype), n, n))
    tb = ET.fromstring('<object type="HistoricalGoalTargetBlock" name="objParameterBlocks"><property name="strName" value="GoalRefTarget%d"/>'
                       '<object type="StringParameter" name="objStrings"><property name="strName" value="CountryAName"/><property name="strValue" value="%s"/></object>'
                       '<object type="StringParameter" name="objStrings"><property name="strName" value="CountryBName"/><property name="strValue" value="%s"/></object></object>'
                       % (n, _x(a), _x(b)))
    hb = ET.fromstring('<object type="HistoricalGoalComparisonBlock" name="objParameterBlocks"><property name="strName" value="GoalRefHistory%d"/></object>' % n)
    _insert_after_last(st, pd, g, lambda c: c.get('type') == 'HistoricalGoalRef')
    _insert_after_last(st, pd, tb, lambda c: c.get('name') == 'objParameterBlocks')
    _insert_after_last(st, pd, hb, lambda c: c.get('name') == 'objParameterBlocks')
    txt = GOAL_ES.get(gtype, gtype).format(me=country, A=a, B=b)
    return st.eid(g), ['IA de %s: %s' % (country, txt)]


def ai_operation_set(s, country, data, oid=None):
    """Plan de guerra de la IA: atacar a unos países (o una lista de regiones) desde una fecha, o cuando A y B estén en guerra."""
    st = s.s
    countries = s.countries()
    targets = [x for x in data.get('targets') or [] if x]
    ta, tb = [x for x in data.get('trig_a') or [] if x], [x for x in data.get('trig_b') or [] if x]
    for c in targets + ta + tb:
        if c not in countries:
            raise ValueError('no existe el país «%s»' % c)
    if not targets and not data.get('region_list'):
        raise ValueError('elige a quién ataca (países o una lista de regiones)')
    for k in ('date', 'expires'):
        if data.get(k) and not re.fullmatch(r'\d\d/\d\d/\d{4}', data[k]):
            raise ValueError('fecha no válida (MM/DD/AAAA)')
    pd = _pd(s, country)
    if oid:
        op = st.get(oid)
    else:
        ai = next((x for x in objs(pd) if x.get('type') == 'MEAIData'), None)
        if ai is None:
            ai = ET.Element('object', {'type': 'MEAIData', 'name': 'objAIData'})
            _insert_after_last(st, pd, ai, lambda c: c.get('type') == 'HistoricalGoalRef')
        used = {prop(w, 'strName') for w in objs(ai)}
        name = 'Editor_' + _w('_'.join(targets) or data.get('region_list'))[:40]
        while name in used:
            name += '2'
        wp = ET.fromstring('<object type="WarPlan" name="objWarPlans"><property name="strName" value="%s"/><property name="nWeight" value="100"/>'
                           '<object type="WarPlanOperation" name="objOperations"><property name="strName" value="%s"/></object></object>' % (_x(name), _x(name)))
        st.attach(wp, ai)
        op = objs(wp)[0]
    _set_multi(st, op, 'strTargetCountries', targets)
    st.set_prop(op, 'strTargetRegionList', data.get('region_list') or '')
    _set_multi(st, op, 'strWarTriggerCountriesA', ta)
    _set_multi(st, op, 'strWarTriggerCountriesB', tb)
    for k, n in (('date', 'dateTrigger'), ('expires', 'dateExpires')):
        if data.get(k):
            st.set_prop(op, n, data[k])
        else:
            for p in [p for p in op if p.tag == 'property' and p.get('name') == n]:
                op.remove(p)
                st.touch(op, structural=True)
    if not prop(op, 'strTargetRegionList'):
        for p in [p for p in op if p.tag == 'property' and p.get('name') == 'strTargetRegionList']:
            op.remove(p)
    # orden habitual del archivo: nombre, objetivos, lista, requisitos, disparadores, fechas
    order = ['strName', 'strTargetCountries', 'strTargetRegionList', 'strPrereqOperations', 'strWarTriggerCountriesA', 'strWarTriggerCountriesB',
             'dateTrigger', 'dateExpires', 'bSuppressesAggression']
    ps = [p for p in op if p.tag == 'property']
    for p in ps:
        op.remove(p)
    ps.sort(key=lambda p: order.index(p.get('name')) if p.get('name') in order else 99)
    for k, p in enumerate(ps):
        op.insert(k, p)
    st.touch(op, structural=True)
    return st.eid(op), ['IA de %s: %s' % (country, _op_text(country, op))]


def ai_rule_delete(s, i):
    st = s.s
    el = st.get(i)
    t = el.get('type')
    notes = []
    if t == 'HistoricalGoalRef':
        pd = st.parent[el]
        tb, hb = prop(el, 'strTargetBlockName'), prop(el, 'strHistoricBlockName')
        st.remove(el)
        others = {prop(g, 'strTargetBlockName') for g in objs(pd)} | {prop(g, 'strHistoricBlockName') for g in objs(pd)}
        for b in objs(pd):
            if b.get('name') == 'objParameterBlocks' and prop(b, 'strName') in (tb, hb) and prop(b, 'strName') not in others:
                st.remove(b)
        notes.append('meta quitada')
    elif t == 'WarPlanOperation':
        wp = st.parent[el]
        st.remove(el)
        if not any(o.get('type') == 'WarPlanOperation' for o in objs(wp)):
            st.remove(wp)
        notes.append('operación de guerra quitada')
    elif t in ('WarPlan', 'ForceAllegiancePlan'):
        st.remove(el)
        notes.append('plan quitado')
    elif t == 'TriggerCountry':
        st.remove(el)
        notes.append('reacción quitada')
    elif t in EVENT_TYPES:
        notes += remove_chain(s, i)
    else:
        raise ValueError('no se puede quitar un %s desde aquí' % t)
    return notes


# ---------------------------------------------------------------------------------------- reacciones por país (country<País>.xml)
# TriggerCountry de MECountry: si el país 'strName' es invadido (COUNTRY_TRIGGER_INVASION, opcionalmente en las regiones de
# strRegionList) o entra en guerra (COUNTRY_TRIGGER_WAR), este país declara la guerra o un embargo al agresor según su
# sensibilidad (0–100: cuanto más alta, más probable). Es lo que usan los escenarios del juego y los mods para «intervenir».
def triggers(s, country):
    c = s.countries().get(country)
    if c is None:
        raise ValueError('no existe el país «%s»' % country)
    return [{'id': s.s.eid(t), 'country': prop(t, 'strName'), 'type': 'invasion' if prop(t, 'eTriggerType') == 'COUNTRY_TRIGGER_INVASION' else 'war',
             'war': prop(t, 'nWarSensitivity') or '0', 'embargo': prop(t, 'nEmbargoSensitivity') or '0', 'region_list': prop(t, 'strRegionList') or '',
             'active': prop(t, 'bActive') != 'false'} for t in objs(c) if t.get('type') == 'TriggerCountry']


def _trigger_text(me, t):
    who = '%s es invadido%s' % (t['country'], ' en las regiones de «%s»' % t['region_list'] if t['region_list'] else '') if t['type'] == 'invasion' \
        else '%s entra en guerra' % t['country']
    return 'Si %s, %s reacciona contra el agresor: guerra %s/100, embargo %s/100%s' % (who, me, t['war'], t['embargo'], '' if t['active'] else ' (desactivada)')


def trigger_set(s, country, data, tid=None):
    st = s.s
    countries = s.countries()
    c = countries.get(country)
    if c is None or data.get('country') not in countries:
        raise ValueError('elige un país que exista')
    if data.get('country') == country:
        raise ValueError('el país no puede reaccionar a sí mismo')
    vals = {}
    for k in ('war', 'embargo'):
        v = int(data.get(k) or 0)
        if not 0 <= v <= 100:
            raise ValueError('la sensibilidad va de 0 a 100')
        vals[k] = str(v)
    if tid:
        t = st.get(tid)
    else:
        t = ET.Element('object', {'type': 'TriggerCountry', 'name': 'objTriggerCountries'})
        _insert_after_last(st, c, t, lambda x: x.get('type') in ('TriggerCountry', 'Region', 'Army', 'AirForce', 'Fleet'))
    st.set_prop(t, 'strName', data['country'])
    st.set_prop(t, 'eTriggerType', 'COUNTRY_TRIGGER_INVASION' if data.get('type') == 'invasion' else 'COUNTRY_TRIGGER_WAR')
    st.set_prop(t, 'nWarSensitivity', vals['war'])
    st.set_prop(t, 'nEmbargoSensitivity', vals['embargo'])
    if 'region_list' not in data:
        pass                                     # se conserva la lista de regiones que tuviera
    elif data.get('region_list'):
        st.set_prop(t, 'strRegionList', data['region_list'])
    else:
        for p in [p for p in t if p.tag == 'property' and p.get('name') == 'strRegionList']:
            t.remove(p)
            st.touch(t, structural=True)
    x = triggers(s, country)
    return st.eid(t), ['%s: %s' % (country, _trigger_text(country, next(y for y in x if y['id'] == st.eid(t))))]


# ---------------------------------------------------------------------------------------- culturas (CultureTemplate)
def cultures(s):
    used = {}
    for r in s.regions(sea=False):
        k = prop(r, 'strCulture')
        used[k] = used.get(k, 0) + 1
    nat = {}
    for c in s.countries().values():
        for cs in objs(c):
            if cs.get('type') == 'CultureSet':
                for k in objs(cs):
                    nat.setdefault(prop(k, 'strCultureName'), []).append(prop(c, 'strName'))
    return [{'id': s.s.eid(t), 'name': prop(t, 'strCultureName'), 'display': _string(s, prop(t, 'sidDisplayName') or '') or '',
             'regions': used.get(prop(t, 'strCultureName'), 0), 'nations': sorted(nat.get(prop(t, 'strCultureName'), [])),
             'file': os.path.basename(s.s.doc_of[t]), 'shared': s.s.doc_of[t] in getattr(s, 'external', [])} for t in s.all('CultureTemplate')]


def culture_create(s, name, display=None):
    st = s.s
    name = (name or '').strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 '\-]*", name):
        raise ValueError('nombre interno: letras, números, espacios o guiones (p. ej. Patagonian)')
    sets = s.all('CultureTemplateSet')
    if not sets:
        raise ValueError('el escenario no tiene CultureTemplateSet (sharedDataCultureTemplates.xml)')
    if any(prop(t, 'strCultureName') == name for t in s.all('CultureTemplate')):
        raise ValueError('ya existe la cultura %s' % name)
    sid = 'SID.Game.CultureTemplate.Name.' + re.sub(r'[^A-Za-z0-9]', '', name)
    t = ET.fromstring('<object type="CultureTemplate" name="objCultureTemplates"><property name="strCultureName" value="%s"/>'
                      '<property name="sidDisplayName" value="%s"/></object>' % (_x(name), sid))
    st.attach(t, sets[0])
    notes = ['cultura %s creada en %s' % (name, os.path.basename(st.doc_of[t]))]
    notes += sc.set_region_string(s, sid, display or name)
    s._opts = None
    return st.eid(t), notes


def culture_delete(s, cid, to=None):
    st = s.s
    t = st.get(cid)
    name = prop(t, 'strCultureName')
    regs = [r for r in s.regions(sea=False) if prop(r, 'strCulture') == name]
    names = {prop(x, 'strCultureName') for x in s.all('CultureTemplate')}
    if regs and (not to or to not in names or to == name):
        raise ValueError('%d regiones tienen la cultura %s: elige a cuál pasan' % (len(regs), name))
    for r in regs:
        st.set_prop(r, 'strCulture', to)
    n = 0
    for c in s.countries().values():           # también en el conjunto de culturas de cada nación
        for cs in objs(c):
            if cs.get('type') == 'CultureSet':
                for k in objs(cs):
                    if prop(k, 'strCultureName') == name:
                        if to and not any(prop(x, 'strCultureName') == to for x in objs(cs)):
                            st.set_prop(k, 'strCultureName', to)
                        else:
                            st.remove(k)
                        n += 1
    st.remove(t)
    s._opts = None
    return ['cultura %s quitada' % name] + (['%d regiones pasan a %s' % (len(regs), to)] if regs else []) + (['%d naciones la tenían' % n] if n else [])


# ---------------------------------------------------------------------------------------- tipos de terreno
SEASONS = ('Spring', 'Summer', 'Fall', 'Winter')
TERRAIN_FIELDS = ('nFoodProductionPenaltyPct', 'nMoveSpeedPenaltyPct', 'nCombatDefenderResistBonus')
BUILTIN_TERRAINS = ('Plains', 'Water')


def terrains(s):
    used = {}
    for r in s.regions():
        t = prop(r, 'strTerrain')
        used[t] = used.get(t, 0) + 1
    out = []
    for t in s.all('TerrainType'):
        name = prop(t, 'strTerrain')
        base = next((x for x in objs(t) if x.get('type') == 'TerrainBaseData'), None)
        seas = {prop(x, 'strSeason'): {f: prop(x, f) or '0' for f in TERRAIN_FIELDS} for x in objs(t) if x.get('type') == 'TerrainSeasonData'}
        out.append({'id': s.s.eid(t), 'name': name, 'display': _string(s, prop(t, 'sidDisplayName') or '') or '',
                    'upgrade_penalty': prop(t, 'nRegionUpgradePenalty') or '0',
                    'base': {f: prop(base, f) or '0' for f in TERRAIN_FIELDS} if base is not None else {},
                    'seasons': seas, 'regions': used.get(name, 0), 'file': os.path.basename(s.s.doc_of[t]),
                    'shared': s.s.doc_of[t] in getattr(s, 'external', [])})
    return out


def terrain_save(s, data, tid=None):
    """Crea un tipo de terreno (copia de 'base') o cambia uno: penalizaciones por estación, nombre visible."""
    st = s.s
    name = re.sub(r'\s', '', data.get('terrain') or '')
    if not tid and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
        raise ValueError('nombre interno: letras y números sin espacios (p. ej. Swamp)')
    types = {prop(t, 'strTerrain'): t for t in s.all('TerrainType')}
    notes = []
    if tid:
        t = st.get(tid)
        name = prop(t, 'strTerrain')
    else:
        if name in types:
            raise ValueError('ya existe el terreno %s' % name)
        src = types.get(data.get('copy_from') or 'Plains') or next(iter(types.values()), None)
        if src is None:
            raise ValueError('el escenario no tiene tipos de terreno que copiar')
        t = copy.deepcopy(src)
        par = st.parent[src]
        last = max(i for i, c in enumerate(par) if c.tag == 'object' and c.get('type') == 'TerrainType')
        st.attach(t, par, index=last + 1)
        st.set_prop(t, 'strTerrain', name)
        st.set_prop(t, 'sidDisplayName', 'SID.Game.TerrainType.Name.' + name)
        notes.append('terreno %s creado (copia de %s) en %s' % (name, prop(src, 'strTerrain'), os.path.basename(st.doc_of[t])))
    if data.get('upgrade_penalty') not in (None, ''):
        st.set_prop(t, 'nRegionUpgradePenalty', str(int(data['upgrade_penalty'])))
    base = next((x for x in objs(t) if x.get('type') == 'TerrainBaseData'), None)
    for f, v in (data.get('base') or {}).items():
        if base is not None and f in TERRAIN_FIELDS and str(v).strip() != '':
            st.set_prop(base, f, str(int(v)))
    for season, vals in (data.get('seasons') or {}).items():
        sd = next((x for x in objs(t) if x.get('type') == 'TerrainSeasonData' and prop(x, 'strSeason') == season), None)
        if sd is None and season in SEASONS:
            sd = ET.Element('object', {'type': 'TerrainSeasonData', 'name': 'objTerrainSeasonDatas'})
            ET.SubElement(sd, 'property', {'name': 'strSeason', 'value': season})
            st.attach(sd, t)
        for f, v in vals.items():
            if sd is not None and f in TERRAIN_FIELDS and str(v).strip() != '':
                st.set_prop(sd, f, str(int(v)))
    if data.get('display'):
        notes += sc.set_region_string(s, prop(t, 'sidDisplayName'), data['display'])
    s._opts = None
    return st.eid(t), notes or ['terreno %s cambiado' % name]


def terrain_delete(s, tid, to=None):
    st = s.s
    t = st.get(tid)
    name = prop(t, 'strTerrain')
    if name in BUILTIN_TERRAINS:
        raise ValueError('%s lo usa el juego por defecto: no se puede quitar' % name)
    regs = [r for r in s.regions() if prop(r, 'strTerrain') == name]
    names = {prop(x, 'strTerrain') for x in s.all('TerrainType')}
    if regs and (not to or to not in names or to == name):
        raise ValueError('%d regiones usan %s: elige a qué terreno pasan' % (len(regs), name))
    for r in regs:
        st.set_prop(r, 'strTerrain', to)
    st.remove(t)
    s._opts = None
    return ['terreno %s quitado' % name] + (['%d regiones pasan a %s' % (len(regs), to)] if regs else [])


# color de cada terreno en el modo de mapa «Terreno»: MapOverlayColorMapping de DisplayLibraries/MapViews/UnifiedMapViews.xml.
# Es un archivo de todo el juego (no del escenario). En Gold ese modo de mapa está activo; en MH1 viene comentado.
def _mapviews_path():
    return os.path.abspath(os.path.join(sc.GAME, 'Modern Europe', 'system', 'DisplayLibraries', 'MapViews', 'UnifiedMapViews.xml'))


def _terrain_colormap(st):
    path = _mapviews_path()
    if not os.path.exists(path):
        return path, None
    root = st.open(path).getroot()
    for v in root.iter('object'):
        if v.get('type') == 'MapView' and prop(v, 'strName') == 'Terrain':
            cm = next((o for o in v.iter('object') if o.get('type') == 'MapOverlayColorMap'), None)
            return path, cm
    return path, None


def terrain_colors(s):
    path, cm = _terrain_colormap(s.s)
    if cm is None:
        return {'active': False, 'file': path, 'colors': {},
                'note': 'Este juego no tiene el modo de mapa «Terreno» (en MH1 está comentado en UnifiedMapViews.xml): el color no se usa.'}
    return {'active': True, 'file': path, 'colors': {prop(m, 'strValue'): prop(m, 'colColor') for m in objs(cm) if m.get('type') == 'MapOverlayColorMapping'},
            'note': 'Color del modo de mapa «Terreno»: está en %s y vale para todo el juego, no solo para este escenario.' % os.path.relpath(path, sc.GAME)}


def terrain_color_set(s, terrain, color):
    """Cambia (o añade) el color de un terreno en UnifiedMapViews.xml y lo guarda en el juego (botón explícito)."""
    st = s.s
    if not re.fullmatch(r'#[0-9A-Fa-f]{8}', color or ''):
        raise ValueError('color no válido: #RRGGBBAA')
    path, cm = _terrain_colormap(st)
    if cm is None:
        raise ValueError('este juego no tiene el modo de mapa «Terreno»: el color no se usa')
    m = next((m for m in objs(cm) if m.get('type') == 'MapOverlayColorMapping' and prop(m, 'strValue') == terrain), None)
    if m is None:
        m = ET.fromstring('<object type="MapOverlayColorMapping" name="objMappings"><property name="strValue" value="%s"/>'
                          '<property name="strDisplayName" value="%s"/><property name="colColor" value="%s"/><property name="fTransparency" value="0.45"/></object>'
                          % (_x(terrain), _x(terrain), color.upper()))
        st.attach(m, cm)
    else:
        st.set_prop(m, 'colColor', color.upper())
    r = st.save([path])
    return ['color de %s = %s guardado en %s (todo el juego)' % (terrain, color.upper(), ', '.join(r['written']) or 'sin cambios')]


# ---------------------------------------------------------------------------------------- unidades en el mapa
# Army / AirForce / Fleet: strRegion (región donde empiezan), vecPosition opcional ([lon, lat, 0]; sin ella el juego las pone
# en su región) y nDirection (VisibleGO: grados, 0 = norte, 90 = este; por defecto 225). Una flota en puerto tiene strRegion =
# la región de tierra y strCity = la ciudad con puerto (strPortForRegion) de su dueño.
UNIT_TYPES = ('Army', 'AirForce', 'Fleet')


def _port_cities(s, owner):
    out = []
    for r in s.regions(sea=False):
        for c in objs(r):
            if c.get('type') == 'City' and prop(c, 'strPortForRegion') and prop(c, 'strOwner') == owner:
                xy = sc.parse_vec(prop(c, 'vecPosition'))
                out.append({'city': prop(c, 'strName'), 'region': prop(r, 'strName'), 'sea': prop(c, 'strPortForRegion'), 'x': xy[0] if xy else None, 'y': xy[1] if xy else None})
    return sorted(out, key=lambda x: x['city'] or '')


def fleet_ports(s, i):
    el = s.s.get(i)
    return _port_cities(s, prop(el, 'strOwner'))


def move_unit(s, i, x=None, y=None, port=None):
    """Mueve un ejército, fuerza aérea o flota a un punto (cambia su región si cae en otra) o mete una flota en un puerto."""
    import scenario_layers as sl
    st = s.s
    el = st.get(i)
    t = el.get('type')
    if t not in UNIT_TYPES:
        raise ValueError('solo se pueden mover ejércitos, fuerzas aéreas y flotas')
    owner, old = prop(el, 'strOwner'), prop(el, 'strRegion')
    name = prop(el, 'strName') or t
    if port:
        if t != 'Fleet':
            raise ValueError('solo las flotas entran en un puerto')
        pc = next((p for p in _port_cities(s, owner) if p['city'] == port), None)
        if pc is None:
            raise ValueError('%s no es una ciudad con puerto de %s' % (port, owner))
        st.set_prop(el, 'strRegion', pc['region'])
        st.set_prop(el, 'strCity', pc['city'])
        if pc['x'] is not None:
            st.set_prop(el, 'vecPosition', sl._vec(pc['x'], pc['y']))
        return ['%s pasa al puerto de %s (%s, mar %s)' % (name, pc['city'], pc['region'], pc['sea'])]
    x, y = float(x), float(y)
    land = None
    try:
        land = sl._land_region_at(s, x, y)[1]
    except ValueError:
        pass
    sea = None
    if land is None:
        try:
            sea = sl.pack_map(sl.scenario_pack(s)).region_at(x, y, sea=True)
        except Exception:
            sea = None
        if sea not in {prop(r, 'strName') for r in s.regions(sea=True)}:
            sea = None
    notes = []
    if t == 'Fleet':
        if land:                     # en tierra: solo en un puerto de su dueño en esa región (el más cercano al punto)
            ports = [p for p in _port_cities(s, owner) if p['region'] == land]
            if not ports:
                raise ValueError('%s no tiene puerto en %s: una flota en tierra debe estar en una ciudad con puerto de su dueño' % (owner, land))
            pc = min(ports, key=lambda p: ((p['x'] or 0) - x) ** 2 + ((p['y'] or 0) - y) ** 2)
            return move_unit(s, i, port=pc['city'])
        if not sea:
            raise ValueError('el punto no está en ninguna región de mar del escenario')
        st.set_prop(el, 'strRegion', sea)
        for p in [p for p in el if p.tag == 'property' and p.get('name') == 'strCity']:
            el.remove(p)
            st.touch(el, structural=True)
            notes.append('sale del puerto')
        region = sea
    else:
        if not land:
            raise ValueError('%s: %s debe estar en una región de tierra' % (name, 'un ejército' if t == 'Army' else 'una fuerza aérea'))
        region = land
        st.set_prop(el, 'strRegion', land)
    st.set_prop(el, 'vecPosition', sl._vec(x, y))
    notes.insert(0, '%s → %.4f, %.4f%s' % (name, x, y, ' (región %s → %s)' % (old, region) if region != old else ''))
    return notes


def set_direction(s, i, deg):
    """Orientación (nDirection, grados: 0 norte, 90 este, 180 sur, 270 oeste) de una ciudad o unidad."""
    st = s.s
    el = st.get(i)
    if el.get('type') not in UNIT_TYPES + ('City',):
        raise ValueError('solo ciudades y unidades tienen orientación')
    d = int(round(float(deg))) % 360
    st.set_prop(el, 'nDirection', str(d))
    return ['%s: orientación %d°' % (prop(el, 'strName') or el.get('type'), d)]


# ---------------------------------------------------------------------------------------- alcance aéreo
def air_ranges(s):
    """Fuerzas aéreas con unidades que bombardean (bombarderos o con % de impacto a estructuras/tierra) y su alcance (millas)."""
    tpl = {}
    for u in s.all('UnitTemplate'):
        if prop(u, 'eType') == 'UNIT_TYPE_AIR_FORCE':
            tpl[prop(u, 'strName')] = {'range': int(prop(u, 'nRange') or 0), 'cat': prop(u, 'eUnitCategory') or '',
                                       'bomb': prop(u, 'eUnitCategory') == 'UNIT_CATEGORY_BOMBER' or int(prop(u, 'nStructureHitPercent') or 0) > 0}
    out = []
    for af in s.all('AirForce'):
        best, kinds = 0, []
        for us in objs(af):
            t = tpl.get(prop(us, 'strName'))
            if t and t['bomb']:
                best = max(best, t['range'])
                kinds.append(prop(us, 'strName'))
        if best:
            out.append({'id': s.s.eid(af), 'range': best, 'units': kinds})
    return out
