"""Political parties mod for Making History I / Gold scenarios (no exe patch: plain scenario XML).

Each listed country gets parties with a popularity share (%), a leader and an ideology (the game's government type).
Shares live in the country object itself: game/scenarioDefs.xml declares PPCountry (an MECountry with integer
properties nPP1..nPP6 = shares, nPPGov = governing party, counters), the country file switches to that type and
every rule is a scripted event in its own file sharedDataParties.xml (so it can be regenerated or removed):
  - erosion of the governing party, recovery when it is very low, extra erosion when it loses regions;
  - poll window every POLL turns; elections on real dates while the country is Democratic;
  - an opposition party that overtakes the government: the player may hand it power (and its ideology) or resist;
  - coups in non-democracies when an opposition party is very strong;
  - ideology change -> relations up with countries of the new ideology, down with the rest (party countries);
  - foreign interference: funding a foreign party or backing a coup; if discovered, relations drop and the
    victim may declare war.
Usage: python political_parties.py <scenario folder> <data.json> [--remove] [--only A,B] [--no-spy]
       python political_parties.py --check <data.json>     (builds the events in memory, writes nothing)
"""
import json
import os
import re
import sys

MAXP = 6
POLL = 30            # turns between poll windows
EROSION = 4          # % chance per turn and rival that the government loses 1 point to that rival
RECOVER = 3          # % chance per turn and rival that a weak government (< 25 %) wins 1 point back
WAR_LOSS = 6         # % chance per turn and rival while the country has lost original regions
SURGE = 20           # % chance per turn of the «overtaken» window while a party leads by 5+ points
COUP = 8             # % chance per turn of a coup in a non-democracy when a party has 45 %+
OFFER = 1            # % chance per turn and country pair of an interference opportunity
DISCOVER = 10        # % chance per turn that an operation is discovered
QUIET_END = 8        # % chance per turn that a funding operation ends unnoticed
COUP_OK = 15         # % chance per turn that a backed coup succeeds
FUND_COST, COUP_COST = 2000, 6000
REL_SAME, REL_OTHER, REL_SPY = 150, -100, -300
EVENTS_FILE = 'sharedDataParties.xml'
DEFS_MARK = ('<!-- political parties (political_parties.py) -->', '<!-- /political parties -->')
PROPS = ['nPP%d' % i for i in range(1, MAXP + 1)] + ['nPPGov', 'nPPPoll', 'nPPElect', 'nPPShift', 'nPPSpyBy', 'nPPSpyLvl', 'nPPSpyParty']
GOV_ES = {'Democratic': 'democracia', 'Communist': 'comunismo', 'Authoritarian': 'autoritarismo', 'Fascist': 'fascismo'}


def x(v):
    return str(v).replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')


def w(s):
    return re.sub(r'\W', '', s, flags=re.ASCII)


def lit(s):
    """Text as a string literal inside a game expression (no single quotes inside)."""
    return "'%s'" % s.replace("'", '’')


def V(c):
    return '{Object:Single:PPCountry}scratch.objPP%s' % w(c)


def P(name, value):
    return '<property name="%s" value="%s"/>' % (name, x(value))


def rule(e):
    return '<object type="RuleDefExpression" name="objRules">%s</object>' % P('expRession', e)


def acc(c):
    return '<object type="AccessorGetCountry" name="objAccessors">%s%s</object>' % (P('pathOutput', V(c)), P('strCountry', c))


def cset(countries, rules=(), label='Parties'):
    """Condition set: the countries exist, are not surrendered and the rules hold (their variables stay for the effects)."""
    inner = ''.join(acc(c) for c in countries)
    inner += ''.join(rule('exists(%s)' % V(c)) + rule('!%s.bSurrendered' % V(c)) for c in countries)
    inner += ''.join(rule(r) for r in rules)
    return ('<object type="AccessorRuleSet" name="objConditions">%s%s%s</object>'
            % (P('strDebugLabel', label), P('pathPlayer', '{Object:Single:Player}scratch.objPlayer'), inner))


def rand(pct):
    if pct >= 100:
        return ''
    return ('<object type="AccessorRuleSet" name="objConditions">%s%s'
            '<object type="AccessorGetRandomNumberSimple" name="objAccessors">%s%s%s</object>%s</object>'
            % (P('strDebugLabel', 'Random %d percent' % pct), P('pathPlayer', '{Object:Single:Player}scratch.objPlayer'),
               P('pathOutput', '{int:Single}scratch.nRandomRoll'), P('nMinValue', 1), P('nMaxValue', 100),
               rule('{int:Single}scratch.nRandomRoll LTE %d' % pct)))


def date_set(rules):
    return ('<object type="AccessorRuleSet" name="objConditions">%s%s'
            '<object type="AccessorGetCurrentDate" name="objAccessors">%s</object>%s</object>'
            % (P('strDebugLabel', 'Date'), P('pathPlayer', '{Object:Single:Player}scratch.objPlayer'),
               P('pathOutput', '{Date:Single}scratch.dateGameDate'), ''.join(rule(r) for r in rules)))


# ------------------------------------------------------------------------------------------------ actions
def inc(c, prop, d):
    return ('<object type="ActIncrementProperty" name="objActions"><property name="nGOID" inheritFrom="%s.nGameObject"/>%s%s</object>'
            % (V(c), P('strPropName', prop), P('nDelta', d))) if d else ''


def setp(c, prop, val):
    return ('<object type="ActAlterProperty" name="objActions"><property name="nGOID" inheritFrom="%s.nGameObject"/>%s%s</object>'
            % (V(c), P('strPropName', prop), P('strNewValue', val)))


def shift(c, frm, to, d=1):
    return inc(c, 'nPP%d' % frm, -d) + inc(c, 'nPP%d' % to, d)


def boost(c, n, j, d):
    """Party j gains (n-1)*d points, every other party loses d (the total stays 100)."""
    return ''.join(inc(c, 'nPP%d' % k, (n - 1) * d if k == j else -d) for k in range(1, n + 1))


def setgov(c, ideology):
    return '<object type="ActSetCountryGov" name="objActions">%s%s</object>' % (P('strCountry', c), P('strGovType', ideology))


def dip(a, b, n):
    return ('<object type="ActIncDipRelations" name="objActions"><property name="nSourceCountryID" inheritFrom="%s.nCountryID"/>'
            '<property name="nTargetCountryID" inheritFrom="%s.nCountryID"/>%s</object>' % (V(a), V(b), P('nAmount', n)))


def treasury(c, n):
    return '<object type="ActIncTreasury" name="objActions">%s%s</object>' % (P('strCountry', c), P('nIncrement', n))


def war(a, b):
    return '<object type="ActProposeDeclareWar" name="objActions">%s%s%s</object>' % (P('strPlayer', a), P('strFromCountry', a), P('strToCountry', b))


def effects(name, acts):
    return ('<object type="CustomEffectDefActions" name="%s">%s%s</object>' % (name, P('strLabel', 'Parties'), acts)) if acts else ''


# ------------------------------------------------------------------------------------------------ events
class Out:
    def __init__(self):
        self.parts, self.n = [], 0

    def label(self, base):
        self.n += 1
        return 'PP_%s_%d' % (w(base)[:40], self.n)

    def event(self, base, owner, conds, acts):
        """Effect-only event: re-evaluated every turn, fires whenever its conditions hold."""
        lab = self.label(base)
        self.parts.append('<object type="ScriptedEventDef" name="objScriptedEventDefs">%s%s'
                          '<object type="PlayerGenNames" name="objPlayerGen">%s</object>'
                          '<object type="TriggerEvalRandomChance" name="objTriggerEval">%s%s</object>%s</object>'
                          % (P('strTypeLabel', lab), P('pathPlayer', '{Object:Single:Player}scratch.objPlayer'), P('strName', owner),
                             P('nPercentChance', 100), conds, effects('objEffects', acts)))
        return lab

    def window(self, base, owner, conds, countries, title, desc, choices, ai=0, ai_pct=100, acts=''):
        """Event + window. desc is a game expression (dynamic text); choices = [(title, actions)]; acts run at once."""
        lab = self.event(base, owner, conds, acts)
        dec = lab + '_Decision'

        def arg(t, d):
            return ('<object type="ArgumentList" name="objArgLists">%s'
                    '<object type="ArgumentElementString" name="objArgElements">%s%s</object>'
                    '<object type="ArgumentElementString" name="objArgElements">%s<property name="strValue" computeFrom="%s"/></object>'
                    '<object type="ArgumentElementString" name="objArgElements">%s%s</object></object>'
                    % (P('strName', 'Display Data'), P('strName', 'strTitle'), P('strValue', t), P('strName', 'strDesc'), x(d),
                       P('strName', 'strEffect'), P('strValue', '')))
        labels, ch = [], []
        for i, (t, a) in enumerate(choices):
            labels.append('Choice%d' % (i + 1))
            ch.append('<object type="PlayerDecisionChoiceDefCustom" name="objChoiceDefs">%s%s%s</object>'
                      % (P('strLabel', labels[-1]), arg(t, lit('')), effects('objChoiceEffects', a)))
        self.parts.append('<object type="PlayerDecisionTrigPlayEvent" name="objPlayerDecisionTriggers">%s%s%s%s%s'
                          '<object type="TriggerEvalRandomChance" name="objEvalRule">%s'
                          '<object type="AccessorRuleSet" name="objConditions">%s%s%s</object></object>'
                          '<object type="PlayerGenNames" name="objPlayerGen">%s</object></object>'
                          % (P('pathPlayer', '{Object:Single:Player}scratch.objPlayer'), P('strTypeLabel', dec + '_PlayEvent'),
                             P('strTypeToTrigger', dec), P('otPlayEventType', 'PlayEventNewScriptedEvent'),
                             P('pathPlayEvent', '{Object:Single:PlayEventNewScriptedEvent}scratch.objScriptEvent'), P('nPercentChance', 100),
                             P('strDebugLabel', 'Scripted Event is ' + lab), P('pathPlayer', '{Object:Single:Player}scratch.objPlayer'),
                             rule("{Object:Single:PlayEventNewScriptedEvent}scratch.objScriptEvent.strTypeLabel == '%s'" % lab), P('strName', owner)))
        self.parts.append('<object type="PlayerDecisionDef" name="objPlayerDecisionDefs">%s%s%s%s%s%s%s%s</object>'
                          % (P('pathPlayer', '{Object:Single:Player}scratch.objPlayer'), P('strTypeLabel', dec),
                             P('strDefaultChoice', labels[ai]), P('nDefaultChoicePercent', ai_pct), P('strDefaultChoicePlayer', labels[0]),
                             cset(countries, label='Countries exist'), ''.join(ch), arg(title, desc)))


def poll_text(c, d):
    """Expression: every party with its leader and current share, and who governs."""
    ps = d['parties']
    rows = [lit('%s (%s): ' % (p[0], p[1])) + ' + cast(String, %s.nPP%d) + %s' % (V(c), i + 1, lit('%  ·  ')) for i, p in enumerate(ps)]
    gov = ''.join('if(%s.nPPGov == %d, %s, ' % (V(c), i + 1, lit(p[0])) for i, p in enumerate(ps)) + lit('?') + ')' * len(ps)
    return ' + '.join(rows) + ' + %s + %s' % (lit('Gobierna: '), gov)


def beats(c, n, k):
    """Party k has the most votes (ties go to the lower index)."""
    return ['%s.nPP%d %s %s.nPP%d' % (V(c), k, 'GT' if j < k else 'GTE', V(c), j) for j in range(1, n + 1) if j != k]


def build(data, only=None, spy=True):
    out = Out()
    cs = data['countries']
    names = [c for c in cs if not only or c in only]
    idx = {c: i + 1 for i, c in enumerate(cs)}
    for c in names:
        d = cs[c]
        ps = d['parties']
        n = len(ps)
        gv = lambda k: '%s.nPPGov == %d' % (V(c), k)
        pp = lambda k: '%s.nPP%d' % (V(c), k)
        for k in range(1, n + 1):
            for j in range(1, n + 1):
                if j == k:
                    continue
                out.event('Erosion' + c, c, cset([c], [gv(k), pp(k) + ' GT 3']) + rand(EROSION), shift(c, k, j))
                out.event('Recover' + c, c, cset([c], [gv(k), pp(k) + ' LT 25', pp(j) + ' GT 3']) + rand(RECOVER), shift(c, j, k))
                out.event('WarLoss' + c, c, cset([c], [gv(k), pp(k) + ' GT 3', V(c) + '.nNumOriginalRegionsLost GT 0']) + rand(WAR_LOSS),
                          shift(c, k, j))
                out.event('Floor' + c, c, cset([c], [pp(k) + ' LT 0', pp(j) + ' GT 5']), shift(c, j, k))
                pj, lj, ij = ps[j - 1][:3]
                ik = ps[k - 1][2]
                # an opposition party overtakes the government: hand it power (the player decides) or resist
                hand = setp(c, 'nPPGov', j) + (setgov(c, ij) + setp(c, 'nPPShift', 3) if ij != ik else '')
                out.window('Surge' + c, c, cset([c], [gv(k), '%s GTE %s + 5' % (pp(j), pp(k)), pp(j) + ' GTE 30']) + rand(SURGE), [c],
                           '%s supera al gobierno' % pj,
                           lit('%s, liderado por %s, ya tiene más apoyo que el partido de gobierno.' % (pj, lj)),
                           [('Ceder el gobierno a %s (%s%s)' % (pj, lj, ', ' + GOV_ES.get(ij, ij) if ij != ik else ''), hand),
                            ('Aferrarse al poder (el descontento crece)', shift(c, k, j, 2))], ai=0, ai_pct=60)
                if ij != ik:
                    out.window('Coup' + c, c, cset([c], [gv(k), "%s.strGovType != 'Democratic'" % V(c), pp(j) + ' GTE 45']) + rand(COUP), [c],
                               'Golpe de Estado: %s toma el poder' % pj,
                               lit('%s, liderado por %s, derroca al gobierno e impone el %s.' % (pj, lj, GOV_ES.get(ij, ij))),
                               [('Entendido', '')], acts=setp(c, 'nPPGov', j) + setgov(c, ij) + setp(c, 'nPPShift', 3))
        out.event('PollTick' + c, c, cset([c]), inc(c, 'nPPPoll', 1))
        out.window('Poll' + c, c, cset([c], ['%s.nPPPoll GTE %d' % (V(c), POLL)]), [c], 'Encuesta de intención de voto',
                   poll_text(c, d), [('Entendido', '')], acts=setp(c, 'nPPPoll', 0))
        # elections on real dates while Democratic (a missed date is skipped once the next one arrives)
        el = d.get('elections') or []
        for m, day in enumerate(el):
            when = ['{Date:Single}scratch.dateGameDate GTE %s' % day] + (['{Date:Single}scratch.dateGameDate LT %s' % el[m + 1]] if m + 1 < len(el) else [])
            for k in range(1, n + 1):
                pk, lk, ik = ps[k - 1][:3]
                acts = setp(c, 'nPPElect', m + 1) + setp(c, 'nPPGov', k) + (setgov(c, ik) + setp(c, 'nPPShift', 3) if ik != 'Democratic' else '')
                out.window('Election' + c, c, cset([c], ["%s.strGovType == 'Democratic'" % V(c), '%s.nPPElect LT %d' % (V(c), m + 1)] + beats(c, n, k))
                           + date_set(when), [c], 'Elecciones: gana %s' % pk,
                           lit('%s, liderado por %s, gana las elecciones y forma gobierno.' % (pk, lk)),
                           [('Entendido', '')], acts=acts)
        # ideology change -> relations with the other party countries
        out.event('ShiftTick' + c, c, cset([c], ['%s.nPPShift GT 0' % V(c)]), inc(c, 'nPPShift', -1))
        for o in cs:
            if o == c:
                continue
            for same in (True, False):
                r = REL_SAME if same else REL_OTHER
                out.event('Realign' + c, c, cset([c, o], ['%s.nPPShift == 2' % V(c), '%s.strGovType %s %s.strGovType' % (V(c), '==' if same else '!=', V(o))]),
                          dip(c, o, r) + dip(o, c, r))
    if spy:
        for a in names:
            for t in cs[a].get('targets') or []:
                if t == a or t not in names:
                    continue
                d = cs[t]
                ps = d['parties']
                n = len(ps)
                lvl = '%s.nPPSpyLvl' % V(t)
                opp = [k for k in sorted(range(1, n + 1), key=lambda k: -ps[k - 1][3]) if k != d['gov']]
                ch = [('Financiar a %s (%s)' % tuple(ps[j - 1][:2]),
                       treasury(a, -FUND_COST) + boost(t, n, j, 1) + setp(t, 'nPPSpyBy', idx[a]) + setp(t, 'nPPSpyLvl', 1)) for j in opp[:2]]
                ch += [('Apoyar un golpe de %s' % ps[j - 1][0],
                        treasury(a, -COUP_COST) + setp(t, 'nPPSpyBy', idx[a]) + setp(t, 'nPPSpyLvl', 3) + setp(t, 'nPPSpyParty', j)) for j in opp[:1]]
                ch.append(('No intervenir', ''))
                out.window('Offer%sIn%s' % (a, t), a, cset([a, t], [lvl + ' == 0']) + rand(OFFER), [a, t],
                           'Oportunidad de injerencia en %s' % t,
                           lit('Contactos en %s ofrecen influir en su política interior. Si se descubre, las relaciones se hundirán y podría haber guerra. ' % t)
                           + ' + ' + poll_text(t, d), ch, ai=len(ch) - 1, ai_pct=92)
                caught = setp(t, 'nPPSpyLvl', 0) + setp(t, 'nPPSpyBy', 0) + dip(t, a, REL_SPY) + dip(a, t, REL_SPY)
                out.window('Caught%sIn%s' % (a, t), t, cset([a, t], ['%s.nPPSpyBy == %d' % (V(t), idx[a]), lvl + ' GTE 1']) + rand(DISCOVER),
                           [a, t], 'Injerencia de %s descubierta' % a,
                           lit('Nuestros servicios descubren que %s financia a la oposición o prepara un golpe.' % a),
                           [('Protesta diplomática', ''), ('Declarar la guerra a %s' % a, war(t, a))], ai=0, ai_pct=85, acts=caught)
        for t in names:
            d = cs[t]
            ps = d['parties']
            n = len(ps)
            lvl = '%s.nPPSpyLvl' % V(t)
            out.event('SpyEnd' + t, t, cset([t], [lvl + ' == 1']) + rand(QUIET_END), setp(t, 'nPPSpyLvl', 0) + setp(t, 'nPPSpyBy', 0))
            for j in range(1, n + 1):
                pj, lj, ij = ps[j - 1][:3]
                out.window('ForeignCoup' + t, t, cset([t], [lvl + ' == 3', '%s.nPPSpyParty == %d' % (V(t), j)]) + rand(COUP_OK), [t],
                           'Golpe de Estado: %s toma el poder' % pj,
                           lit('Con apoyo extranjero, %s (%s) derroca al gobierno.' % (pj, lj)), [('Entendido', '')],
                           acts=setp(t, 'nPPGov', j) + setgov(t, ij) + setp(t, 'nPPShift', 3) + setp(t, 'nPPSpyLvl', 0) + setp(t, 'nPPSpyBy', 0) + boost(t, n, j, 3))
    return out


# ------------------------------------------------------------------------------------------------ files
def _read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def _write(p, s):
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(s)


def validate(data):
    for c, d in data['countries'].items():
        ps = d['parties']
        if not 2 <= len(ps) <= MAXP:
            raise ValueError('%s: entre 2 y %d partidos' % (c, MAXP))
        if not 1 <= d['gov'] <= len(ps):
            raise ValueError('%s: partido de gobierno fuera de rango' % c)
        for day in d.get('elections') or []:
            if not re.fullmatch(r'\d\d/\d\d/\d{4}', day):
                raise ValueError('%s: fecha no válida %s (MM/DD/AAAA)' % (c, day))


def apply(scen, data, remove=False, only=None, spy=True):
    """Writes (or removes) the mod in a scenario folder. Returns a list of notes."""
    validate(data)
    notes = []
    defs = os.path.join(scen, 'game', 'scenarioDefs.xml')
    s = re.sub(r'\s*%s.*?%s' % (re.escape(DEFS_MARK[0]), re.escape(DEFS_MARK[1])), '', _read(defs), flags=re.S)
    if not remove:
        block = ('\t%s\n\t<objectDef type="PPCountry" superType="MECountry">\n%s\t</objectDef>\n\t%s\n'
                 % (DEFS_MARK[0], ''.join('\t\t<propertyDef name="%s" type="int" default="0"/>\n' % p for p in PROPS), DEFS_MARK[1]))
        s = s.replace('</objectDefs>', block + '</objectDefs>')
    _write(defs, s)
    cs = data['countries']
    for f in os.listdir(scen):
        if f.startswith('country') and f.endswith('.xml'):
            p = os.path.join(scen, f)
            s = _read(p)
            if 'PPCountry' in s:
                s = re.sub(r'\n?[ \t]*<property name="nPP\w*" value="[^"]*" ?/>', '', s)
                _write(p, s.replace('<object type="PPCountry"', '<object type="MECountry"', 1))
    if not remove:
        for c, d in cs.items():
            if only and c not in only:
                continue
            p = os.path.join(scen, 'country%s.xml' % c)
            s = _read(p) if os.path.isfile(p) else ''
            if '<object type="MECountry" name="">' not in s:
                notes.append('se omite «%s» (no existe o no es MECountry)' % c)
                continue
            tot = sum(q[3] for q in d['parties'])
            pct = [round(q[3] * 100 / tot) for q in d['parties']]
            pct[0] += 100 - sum(pct)
            vals = [('nPP%d' % (i + 1), v) for i, v in enumerate(pct)] + [('nPPGov', d['gov'])]
            add = ''.join('\n\t\t<property name="%s" value="%d" />' % kv for kv in vals)
            _write(p, s.replace('<object type="MECountry" name="">', '<object type="PPCountry" name="">' + add, 1))
    scen_xml = os.path.join(scen, 'scenario.xml')
    s = re.sub(r'\s*<object type="SharedDataFileRef" name="objSharedDataFileRefs">(?:(?!</object>).)*?%s.*?</object>' % re.escape(EVENTS_FILE),
               '', _read(scen_xml), flags=re.S)
    ev = os.path.join(scen, EVENTS_FILE)
    if remove:
        if os.path.isfile(ev):
            os.remove(ev)
        _write(scen_xml, s)
        return notes + ['mod de partidos quitado']
    ids = [int(i) for i in re.findall(r'nFileRefID" value="(\d+)"', s)]
    ref = ('\n\t\t<object type="SharedDataFileRef" name="objSharedDataFileRefs">\n\t\t\t<property name="nFileRefID" value="%d" />\n'
           '\t\t\t<property name="bScenario" value="true" />\n\t\t\t<property name="strFileLoadName" value="Shared Data - Parties" />\n'
           '\t\t\t<property name="fileSharedData" value="%s" />\n\t\t</object>' % (max(ids or [0]) + 1, EVENTS_FILE))
    end = s.index('</object>', s.rfind('fileSharedData')) + len('</object>')
    _write(scen_xml, s[:end] + ref + s[end:])
    out = build(data, only, spy)
    _write(ev, '<?xml version="1.0" encoding="UTF-8"?>\n<objects name="Object Load" version="0.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
               '<object type="MESharedData" name="">\n%s\n</object>\n</objects>\n' % '\n'.join(out.parts))
    return notes + ['%d países con partidos, %d objetos de evento' % (len(only or cs), len(out.parts))]


if __name__ == '__main__':
    a = sys.argv[1:]
    only = a[a.index('--only') + 1].split(',') if '--only' in a else None
    pos = [f for f in a if not f.startswith('--') and (not only or f != a[a.index('--only') + 1])]
    if '--check' in a:
        import xml.etree.ElementTree as ET
        with open(pos[0], encoding='utf-8') as f:
            data = json.load(f)
        validate(data)
        out = build(data, only, '--no-spy' not in a)
        ET.fromstring('<x>%s</x>' % ''.join(out.parts))      # self-check: well-formed XML
        print('OK: %d objetos, %.1f MB' % (len(out.parts), len('\n'.join(out.parts)) / 1e6))
        sys.exit(0)
    with open(pos[1], encoding='utf-8') as f:
        data = json.load(f)
    for line in apply(pos[0], data, '--remove' in a, only, '--no-spy' not in a):
        print(line)
