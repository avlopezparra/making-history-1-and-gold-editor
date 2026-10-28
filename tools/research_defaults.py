"""Unidades (y demás producción) que un país puede fabricar desde el inicio.

Un país puede producir una unidad cuando ha completado el proyecto de investigación que la desbloquea
(ResearchProjFactoryOutput > ResearchFactoryOutputAvailableData strFactoryOutputName). Dos sitios lo deciden:
- para todos los países: bCompletedByDefault="true" en el proyecto (sharedDataResearch.xml). En el juego de serie solo
  Militia, PreWarInfantry, MountedInfantry (Cavalry) y Corvettes; «The Modern World» completa 34.
- para un país: ResearchProjectInitRef (strProjectName, eResearchState=RESEARCH_COMPLETED) en su player<País>.xml.
Todo queda en memoria hasta «Guardar».
"""
import xml.etree.ElementTree as ET

import scenario_core as sc
from scenario_core import prop, objs


def _projects(s):
    return [e for e in s.all_prefix('ResearchProj') if s.s.parent.get(e) is not None and s.s.parent[e].get('type') == 'ResearchProjectSet']


def _unit_types(s):
    out = {}
    for f in s.all_prefix('FactoryOutput'):
        if f.get('type') == 'FactoryOutputUnit':
            out[prop(f, 'strName')] = prop(f, 'strUnitType') or prop(f, 'strName')
    kinds = {prop(u, 'strName'): (prop(u, 'eType') or '').replace('UNIT_TYPE_', '').lower() for u in s.all('UnitTemplate')}
    return {k: kinds.get(v, '') for k, v in out.items()}


def info(s, country=None):
    ut = _unit_types(s)
    done = set()
    pd = None
    if country:
        pd = next((p for p in s.all('MEPlayerData') if prop(p, 'strOwner') == country), None)
        if pd is not None:
            done = {prop(r, 'strProjectName') for r in objs(pd) if r.get('type') == 'ResearchProjectInitRef' and prop(r, 'eResearchState') == 'RESEARCH_COMPLETED'}
    rows = []
    for e in _projects(s):
        outs = [prop(x, 'strFactoryOutputName') for x in e.iter('object') if x.get('type') == 'ResearchFactoryOutputAvailableData']
        pre = [prop(x, 'strProjectName') for x in objs(e) if x.get('type') == 'ResearchProjectPreReq']
        rows.append({'id': s.s.eid(e), 'name': prop(e, 'strName'), 'type': e.get('type').replace('ResearchProj', ''),
                     'branch': (prop(e, 'strBranchName') or '').replace('RESEARCH_BRANCH_', '').lower(),
                     'outputs': outs, 'units': [o for o in outs if o in ut], 'unit_kind': next((ut[o] for o in outs if o in ut), ''),
                     'prereq': pre, 'default': prop(e, 'bCompletedByDefault') == 'true', 'country': prop(e, 'strName') in done})
    return {'projects': rows, 'country': country, 'has_player': pd is not None if country else None,
            'countries': sorted(s.countries())}


def set_default(s, on):
    """bCompletedByDefault de todos los proyectos: 'on' = nombres que quedan completados para todos los países."""
    on = set(on)
    n = 0
    for e in _projects(s):
        want = prop(e, 'strName') in on
        cur = prop(e, 'bCompletedByDefault') == 'true'
        if want != cur:
            s.s.set_prop(e, 'bCompletedByDefault', 'true' if want else 'false')
            n += 1
    return ['%d proyecto(s) cambiados: %d completados para todos los países' % (n, len(on))]


def set_country(s, country, on):
    """Proyectos completados al empezar para un país (ResearchProjectInitRef de su player<País>.xml)."""
    st = s.s
    pd = next((p for p in s.all('MEPlayerData') if prop(p, 'strOwner') == country), None)
    if pd is None:
        raise ValueError('no hay datos de jugador (player%s.xml) para %s' % (country, country))
    names = {prop(e, 'strName') for e in _projects(s)}
    on = [x for x in on if x in names]
    refs = [r for r in objs(pd) if r.get('type') == 'ResearchProjectInitRef']
    have = {prop(r, 'strProjectName'): r for r in refs}
    added = removed = 0
    for name, r in have.items():
        if name not in on and prop(r, 'eResearchState') == 'RESEARCH_COMPLETED':
            st.remove(r)
            removed += 1
    kids = list(pd)
    last = max([k for k, c in enumerate(kids) if c.tag == 'object' and c.get('type') == 'ResearchProjectInitRef'] or [-1])
    if last < 0:
        last = max([k for k, c in enumerate(kids) if c.tag == 'property'] or [-1])
    for name in on:
        r = have.get(name)
        if r is not None and r in list(pd):
            if prop(r, 'eResearchState') != 'RESEARCH_COMPLETED':
                st.set_prop(r, 'eResearchState', 'RESEARCH_COMPLETED')
                added += 1
            continue
        new = ET.Element('object', {'type': 'ResearchProjectInitRef', 'name': 'objInitResearchRefs'})
        ET.SubElement(new, 'property', {'name': 'strProjectName', 'value': name})
        ET.SubElement(new, 'property', {'name': 'eResearchState', 'value': 'RESEARCH_COMPLETED'})
        last += 1
        st.attach(new, pd, index=min(last, len(list(pd))))
        added += 1
    return ['%s: %d proyecto(s) añadidos, %d quitados (completados al empezar: %d)' % (country, added, removed, len(on))]
