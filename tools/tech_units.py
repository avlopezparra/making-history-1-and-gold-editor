"""Tecnologías según las tropas: si un país tiene unidades cuya investigación no completó (p. ej. ModernTank sin ModernTanks),
se marca esa investigación —y sus requisitos— como completada en su MEPlayerData (ResearchProjectInitRef).

Enlace unidad → investigación, sacado de los datos del propio escenario (MH1 y Gold):
UnitTemplate.strName == FactoryOutputUnit.strUnitType → FactoryOutputUnit.strName → el ResearchProj* cuyo
ResearchFactoryOutputAvailableData.strFactoryOutputName lo nombra. Una salida con bAvailableByDefault=true no necesita nada.
Requisitos: ResearchProjectPreReq.strProjectName (en cadena). Nada se escribe hasta «Guardar»; undo() deshace el último apply().
"""
import xml.etree.ElementTree as ET

from scenario_core import prop, objs

GROUPS = ('Army', 'AirForce', 'Fleet')
DONE = 'RESEARCH_COMPLETED'
_last = []          # [(elemento, estado anterior o None si se creó)] del último apply()


def _links(s):
    """({plantilla: [proyectos que la desbloquean]}, {proyecto: [requisitos]})."""
    out_of = {}
    for fo in s.all('FactoryOutputUnit'):
        if prop(fo, 'bAvailableByDefault') != 'true' and prop(fo, 'strUnitType'):
            out_of.setdefault(prop(fo, 'strName'), []).append(prop(fo, 'strUnitType'))
    unlock, pre = {}, {}
    for p in s.all_prefix('ResearchProj'):
        n = prop(p, 'strName')
        pre[n] = [prop(k, 'strProjectName') for k in objs(p) if k.get('type') == 'ResearchProjectPreReq' and prop(k, 'strProjectName')]
        for k in objs(p):
            if k.get('type') == 'ResearchFactoryOutputAvailableData':
                for t in out_of.get(prop(k, 'strFactoryOutputName'), []):
                    unlock.setdefault(t, []).append(n)
    return unlock, pre


def _player(s, country):
    return next((p for p in s.all('MEPlayerData') if prop(p, 'strOwner') == country), None)


def _done(pd):
    return {prop(o, 'strProjectName') for o in (pd.iter('object') if pd is not None else ())
            if o.get('type') == 'ResearchProjectInitRef' and prop(o, 'eResearchState') == DONE}


def _closure(p, pre, have):
    """p y todos sus requisitos que aún faltan, requisitos primero."""
    out, seen = [], set()

    def walk(x):
        if x in seen or x in have:
            return
        seen.add(x)
        for q in pre.get(x, []):
            walk(q)
        out.append(x)
    walk(p)
    return out


def plan(s, countries):
    """[{'country', 'units': [plantillas sin tecnología], 'techs': [investigaciones a añadir, requisitos primero]}]."""
    unlock, pre = _links(s)
    units = {}
    for t in GROUPS:
        for g in s.all(t):
            for u in objs(g):
                if u.get('type') == 'UnitSummary':
                    units.setdefault(prop(g, 'strOwner'), set()).add(prop(u, 'strName'))
    res = []
    for c in countries:
        pd = _player(s, c)
        if pd is None:
            continue
        have = _done(pd)
        missing, techs = [], []
        for t in sorted(units.get(c, ())):
            cands = unlock.get(t)
            if not cands or any(p in have for p in cands):
                continue
            best = min((_closure(p, pre, have | set(techs)) for p in cands), key=len)   # the option that adds the fewest techs
            missing.append(t)
            techs += [x for x in best if x not in techs]
        if missing:
            res.append({'country': c, 'units': missing, 'techs': techs})
    return res


def apply(s, items):
    """Marca las investigaciones como completadas (en memoria; falta «Guardar»)."""
    st = s.s
    changed = []
    for it in items:
        pd = _player(s, it['country'])
        if pd is None:
            continue
        refs = {prop(o, 'strProjectName'): o for o in objs(pd) if o.get('type') == 'ResearchProjectInitRef'}
        for t in it['techs']:
            o = refs.get(t)
            if o is not None:
                if prop(o, 'eResearchState') != DONE:
                    changed.append((o, prop(o, 'eResearchState')))
                    st.set_prop(o, 'eResearchState', DONE)
                continue
            o = ET.Element('object', {'type': 'ResearchProjectInitRef', 'name': 'objInitResearchRefs'})
            ET.SubElement(o, 'property', {'name': 'strProjectName', 'value': t})
            ET.SubElement(o, 'property', {'name': 'eResearchState', 'value': DONE})
            last = [k for k, x in enumerate(list(pd)) if x.get('type') == 'ResearchProjectInitRef']
            st.attach(o, pd, index=(last[-1] + 1) if last else None)
            refs[t] = o
            changed.append((o, None))
    _last[:] = changed
    return ['%d investigaciones completadas en %d países' % (len(changed), len({it['country'] for it in items}))]


def undo(s):
    st = s.s
    for o, old in reversed(_last):
        if old is None:
            if o in st.parent:
                st.remove(o)
        else:
            st.set_prop(o, 'eResearchState', old)
    n = len(_last)
    _last[:] = []
    return ['%d cambios de investigación deshechos' % n]


def issues(s):
    """Para el validador: un aviso por país con unidades sin su tecnología, con el botón que la añade."""
    landed = {prop(r, 'strOwner') for r in s.regions(sea=False)}
    return [{'level': 'aviso', 'id': None,
             'msg': 'País %s: tiene unidades %s sin la tecnología %s' % (it['country'], ', '.join(it['units']), ', '.join(it['techs'])),
             'fix': {'kind': 'techunits', 'country': it['country'], 'label': 'Añadir esas tecnologías'}}
            for it in plan(s, sorted(c for c in s.countries() if c in landed))]
