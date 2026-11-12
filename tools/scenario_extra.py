"""Scenario editor extras derived from the comparison with ed.exe (docs_texto/editor_oficial/COMPARACION.md):
optional fields missing from the form, resources of a trade or aid flow, the scenario's game/ and ui/
folders and a shared-data warning."""
import os
import shutil
import xml.etree.ElementTree as ET

from scenario_core import prop, objs

# fields ed.exe edits even if the file lacks them (shown empty; only written if filled in)
OPTIONAL = {
    'MECountry': ['strCapital', 'strOriginalCapital', 'eCountryType', 'bSurrendered', 'bNonPlayable', 'strHomelands',
                  'nTransportCredits', 'n64GovernmentWealth', 'bColonialPower', 'bIsScored', 'bCanPlay'],
    'Region': ['nPopulation', 'strController', 'strCulture', 'strTerrain', 'nAgriculture', 'nFortification', 'nTransInfrastructure'],
    'Producer': ['strResource', 'nBaseOutputRate'],
    'Alliance': ['strDisplayName'],
    'Flow': ['strFromCountry', 'strToCountry'],
}
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'editor', 'plantilla_escenario')
CHILDREN = {
    'Army': [('UnitSummary', 'objUnits')], 'AirForce': [('UnitSummary', 'objUnits')],
    'Fleet': [('UnitSummary', 'objUnits')],
    'FactoryOutputUnit': [('ResourceAmountPair', 'objResourcesRequired')],
    'FactoryOutputFactory': [('ResourceAmountPair', 'objResourcesRequired')],
    'FactoryOutputResource': [('ResourceAmountPair', 'objResourcesRequired')],
    'ResearchProjNoOp': [('ResearchProjectPreReq', 'objPreReqs')],
    'ResearchProjFactoryOutput': [('ResearchProjectPreReq', 'objPreReqs'),
        ('ResearchFactoryOutputAvailableData', 'objAvailableFactoryOutputs'),
        ('ResearchFactoryOutputUnavailableData', 'objUnavailableFactoryOutputs')],
    'ResearchProjUpgradeDataTemplateRef': [('ResearchProjectPreReq', 'objPreReqs')],
    'ResearchProjUpgradeUnits': [('ResearchProjectPreReq', 'objPreReqs'), ('ResearchUnitUpgrade', 'objUpgrades')],
}
CHILD_PROPS = {
    'UnitSummary': {'strName': '', 'nNumber': '1'},
    'ResourceAmountPair': {'strResource': '', 'nAmount': '0'},
    'ResearchProjectPreReq': {'strProjectName': ''},
    'ResearchFactoryOutputAvailableData': {'strFactoryOutputName': '', 'bMayAlreadyBeAvailable': 'false'},
    'ResearchFactoryOutputUnavailableData': {'strFactoryOutputName': '', 'strReplacementFactoryOutputName': '', 'bMayAlreadyBeUnavailable': 'false'},
    'ResearchUnitUpgrade': {'strUpgradeName': ''},
}


def add_child(scenario, parent_id, kind):
    st = scenario.s
    parent = st.get(parent_id)
    if st.doc_of.get(parent) not in scenario.paths:
        raise ValueError('objeto fuera del escenario')
    name = next((name for typ, name in CHILDREN.get(parent.get('type'), []) if typ == kind), None)
    if name is None:
        raise ValueError('tipo de contenido no permitido')
    child = ET.Element('object', {'type': kind, 'name': name})
    for key, value in CHILD_PROPS[kind].items():
        ET.SubElement(child, 'property', {'name': key, 'value': value})
    st.attach(child, parent)
    return st.eid(child)
# what ed.exe creates in each scenario (CEdScenDirGameDefs / CEdScenDirUIDefs::InitDir)
SCEN_FILES = [os.path.join('game', 'namespace.xml'), os.path.join('game', 'scenarioDefs.xml'),
              os.path.join('ui', 'namespace.xml'), os.path.join('ui', 'UICommandFile.xml'), os.path.join('ui', 'UIPreLoopCommandFile.xml')]


def missing_props(el, have, labels):
    """Empty rows for the form with the type's optional fields the file lacks."""
    out = []
    for n in OPTIONAL.get(el.get('type'), []):
        if n in have:
            continue
        # booleans go as text: a true/false dropdown would write a value without the user choosing it
        out.append({'name': n, 'key': n, 'value': '', 'inherit': None, 'label': labels.get(n, n), 'text': None, 'missing': True,
                    'kind': 'number' if n[:1] == 'n' else 'text'})
    return out


def is_shared(path):
    """Shared data (sharedData*.xml or ScenarioDefaults): changing them affects the whole scenario or several."""
    b = os.path.basename(path or '')
    return b.startswith('sharedData') or 'ScenarioDefaults' in (path or '')


def flow_resource(st, flow, resource, amount):
    """Adds, changes (same commodity) or removes (empty or 0 amount) a ResourceTrade of the flow."""
    if flow.get('type') != 'Flow':
        raise ValueError('no es un flujo comercial o de ayuda')
    resource = (resource or '').strip()
    if not resource:
        raise ValueError('elige el recurso')
    amount = str(amount if amount is not None else '').strip()
    if amount and not amount.isdigit():
        raise ValueError('la cantidad debe ser un entero mayor o igual que 0')
    cur = next((o for o in objs(flow) if o.get('type') == 'ResourceTrade' and prop(o, 'strResource') == resource), None)
    if not amount or amount == '0':
        if cur is not None:
            st.remove(cur)
            return ['%s quitado del flujo' % resource]
        return []
    if cur is not None:
        st.set_prop(cur, 'nAmount', amount)
        return ['%s: %s' % (resource, amount)]
    t = ET.Element('object', {'type': 'ResourceTrade', 'name': 'objResourceTrades'})
    ET.SubElement(t, 'property', {'name': 'strResource', 'value': resource})
    ET.SubElement(t, 'property', {'name': 'nAmount', 'value': amount})
    st.attach(t, flow)
    return ['%s añadido al flujo (%s)' % (resource, amount)]


def ensure_dirs(scen_dir):
    """Creates the missing game/ and ui/ files (copies of the editor template). Returns those created."""
    made = []
    for rel in SCEN_FILES:
        dst, src = os.path.join(scen_dir, rel), os.path.join(TEMPLATE, rel)
        if not os.path.exists(dst) and os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            made.append(rel.replace(os.sep, '/'))
    stt = os.path.join(scen_dir, 'game', 'stringTable.xml')     # game/namespace.xml names it: without it the game does not load the texts
    if os.path.exists(os.path.join(scen_dir, 'game', 'namespace.xml')) and not os.path.exists(stt):
        with open(stt, 'w', encoding='utf-8', newline='') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\r\n<stringTable existence="optional">\r\n</stringTable>\r\n')
        made.append('game/stringTable.xml')
    return made
