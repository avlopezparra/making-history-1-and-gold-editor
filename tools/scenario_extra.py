"""Extras del editor de escenarios sacados de la comparación con ed.exe (docs_texto/editor_oficial/COMPARACION.md):
campos opcionales que faltan en la ficha, recursos de un flujo comercial o de ayuda, carpetas game/ y ui/ del
escenario y aviso de datos compartidos."""
import os
import shutil
import xml.etree.ElementTree as ET

from scenario_core import prop, objs

# campos que ed.exe edita aunque el archivo no los traiga (se muestran vacíos; solo se escriben si se rellenan)
OPTIONAL = {
    'MECountry': ['strCapital', 'strOriginalCapital', 'eCountryType', 'bSurrendered', 'bNonPlayable', 'strHomelands',
                  'nTransportCredits', 'n64GovernmentWealth', 'bColonialPower', 'bIsScored', 'bCanPlay'],
    'Region': ['nPopulation', 'strController', 'strCulture', 'strTerrain', 'nAgriculture', 'nFortification', 'nTransInfrastructure'],
    'Producer': ['strResource', 'nBaseOutputRate'],
    'Alliance': ['strDisplayName'],
    'Flow': ['strFromCountry', 'strToCountry'],
}
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'editor', 'plantilla_escenario')
# lo que ed.exe crea en cada escenario (CEdScenDirGameDefs / CEdScenDirUIDefs::InitDir)
SCEN_FILES = [os.path.join('game', 'namespace.xml'), os.path.join('game', 'scenarioDefs.xml'),
              os.path.join('ui', 'namespace.xml'), os.path.join('ui', 'UICommandFile.xml'), os.path.join('ui', 'UIPreLoopCommandFile.xml')]


def missing_props(el, have, labels):
    """Filas vacías para la ficha con los campos opcionales del tipo que el archivo no tiene."""
    out = []
    for n in OPTIONAL.get(el.get('type'), []):
        if n in have:
            continue
        # los booleanos van como texto: un desplegable true/false escribiría un valor sin que el usuario lo elija
        out.append({'name': n, 'key': n, 'value': '', 'inherit': None, 'label': labels.get(n, n), 'text': None, 'missing': True,
                    'kind': 'number' if n[:1] == 'n' else 'text'})
    return out


def is_shared(path):
    """Datos compartidos (sharedData*.xml o ScenarioDefaults): cambiarlos afecta a todo el escenario o a varios."""
    b = os.path.basename(path or '')
    return b.startswith('sharedData') or 'ScenarioDefaults' in (path or '')


def flow_resource(st, flow, resource, amount):
    """Añade, cambia (misma materia) o quita (cantidad vacía o 0) un ResourceTrade del flujo."""
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
    """Crea los archivos de game/ y ui/ que faltan (copias de la plantilla del editor). Devuelve los creados."""
    made = []
    for rel in SCEN_FILES:
        dst, src = os.path.join(scen_dir, rel), os.path.join(TEMPLATE, rel)
        if not os.path.exists(dst) and os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            made.append(rel.replace(os.sep, '/'))
    stt = os.path.join(scen_dir, 'game', 'stringTable.xml')     # game/namespace.xml la nombra: sin ella el juego no carga los textos
    if os.path.exists(os.path.join(scen_dir, 'game', 'namespace.xml')) and not os.path.exists(stt):
        with open(stt, 'w', encoding='utf-8', newline='') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\r\n<stringTable existence="optional">\r\n</stringTable>\r\n')
        made.append('game/stringTable.xml')
    return made
