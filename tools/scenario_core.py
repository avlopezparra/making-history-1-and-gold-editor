"""Editor de escenarios (equivalente a ed.exe) y almacen generico de documentos XML del juego.

Store     documentos XML abiertos (cualquier archivo del juego), con un id por cada <object>,
          edicion de propiedades, duplicar/quitar objetos, guardar con copia de seguridad.
Scenario  un escenario: sus XML, las pestanas de ed.exe, opciones de los campos, validacion y las
          reglas del formato (p. ej. una region vive siempre en el archivo de su propietario).
"""
import copy
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Making History The Calm and The Storm"
SCEN_ROOT = os.path.join(GAME, 'Modern Europe', 'system', 'scenarios')
HERE = os.path.dirname(os.path.abspath(__file__))
# copias de seguridad de archivos (originales y version previa a cada guardado): desactivadas salvo MH_RESPALDOS=1.
# Lo que se puede deshacer queda en el changelog del regionpack y en el deshacer/rehacer de la sesion del editor.
BACKUPS = os.environ.get('MH_RESPALDOS') == '1'
BACKUP_ROOT = os.path.join(os.environ.get('MH_ROOT') or os.path.join(HERE, '..'), 'backup')


_ENUMS = {}


def enum_options():
    """{propiedad: valores} de las propiedades de tipo Enum del juego (propertyDef subType → defEnum de namespace.xml)."""
    if GAME in _ENUMS:
        return _ENUMS[GAME]
    dirs = [os.path.join(GAME, 'system', 'game'), os.path.join(GAME, 'Modern Europe', 'system', 'game')]
    enums, subtype = {}, {}
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith('.xml'):
                continue
            try:
                root = ET.parse(os.path.join(d, f)).getroot()
            except ET.ParseError:
                continue
            for e in root.iter('defEnum'):
                enums[e.get('name')] = [v.get('name') for v in e.iter('value') if v.get('name')]
            for p in root.iter('propertyDef'):
                if p.get('type') == 'Enum' and p.get('subType'):
                    subtype.setdefault(p.get('name'), p.get('subType'))
    _ENUMS[GAME] = {n: enums[t] for n, t in subtype.items() if t in enums}
    return _ENUMS[GAME]


def _ev():
    import scenario_events          # eventos en palabras (importa este módulo: se carga al usarlo)
    return scenario_events


def parse(path):
    return ET.parse(path, ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))


def objs(el):
    return [c for c in el if c.tag == 'object']


def prop(el, name, default=None):
    for p in el:
        if p.tag == 'property' and p.get('name') == name:
            return p.get('value', default)
    return default


# ---------------------------------------------------------------------------------------- etiquetas
LABELS = {
    'strName': 'Nombre', 'strOwner': 'Propietario', 'strController': 'Controlador', 'strTerrain': 'Terreno',
    'strCulture': 'Cultura', 'nPopulation': 'Población', 'nTransInfrastructure': 'Infraestructura (transporte)',
    'nFortification': 'Fortificación', 'nAgriculture': 'Agricultura', 'bColony': 'Colonia',
    'strGovType': 'Gobierno', 'strCapital': 'Capital', 'strOriginalCapital': 'Capital original',
    'eCountryType': 'Tipo de nación', 'bSurrendered': 'Rendida', 'bNonPlayable': 'No jugable',
    'nTransportCredits': 'Reserva de transporte', 'n64GovernmentWealth': 'Tesoro', 'strHomelands': 'Patria',
    'strFlagName': 'Bandera', 'vecPosition': 'Posición [lon, lat, z]', 'nDirection': 'Orientación',
    'strPortForRegion': 'Puerto (mar)', 'strInitialWorkOrder': 'Orden de trabajo inicial',
    'nInitialPercentComplete': '% completado', 'eCityState': 'Estado', 'nIPUs': 'IPUs', 'nTechLevel': 'Nivel tecnológico',
    'strResource': 'Recurso', 'nBaseOutputRate': 'Producción base', 'strRegion': 'Ubicación', 'nNumber': 'Unidades',
    'strDisplayName': 'Nombre visible', 'strINITCountryName': 'País', 'bPrincipal': 'Principal', 'bOwner': 'Dueño',
    'strINITAttackerCountryName': 'Atacante', 'strINITDefenderCountryName': 'Defensor',
    'strINITOffenseAllianceName': 'Alianza atacante', 'strINITDefenseAllianceName': 'Alianza defensora',
    'strFromCountry': 'De', 'strToCountry': 'A', 'eTreatyState': 'Estado del tratado', 'bLand': 'Tierra', 'bAir': 'Aire',
    'bSea': 'Mar', 'bToTerm': 'Sentido', 'nAmount': 'Cantidad', 'colCountryColor': 'Color', 'bAIDisabled': 'IA desactivada',
    'eInternationalPosition': 'Posición internacional', 'nInternationalInvolvement': 'Implicación internacional',
    'nAggressiveNature': 'Agresividad', 'nMilitaryPosture': 'Postura militar', 'nMilitaryDoctrine': 'Doctrina militar',
    'nDomesticPolicy': 'Política interior', 'nSciencePolicy': 'Política científica', 'nPoliticalStability': 'Estabilidad política',
    'strDipRelProcListName': 'Perfil diplomático', 'strAITreatyEvalListName': 'Perfil de tratados',
    'strProjectName': 'Proyecto', 'eResearchState': 'Estado', 'strCultureName': 'Cultura',
    'strTargetCountry': 'País', 'nValue': 'Valor', 'nDefault': 'Valor por defecto',
    'nSpeed': 'Velocidad', 'nHitPoints': 'Puntos de vida', 'nAttackPower': 'Ataque', 'nLandHitPercent': '% impacto tierra',
    'nSeaHitPercent': '% impacto mar', 'nAirHitPercent': '% impacto aire', 'nStructureHitPercent': '% impacto estructuras',
    'nMaintenanceCost': 'Coste de mantenimiento', 'nRequiredMPUs': 'MPUs necesarios', 'eType': 'Tipo', 'eUnitCategory': 'Categoría',
    'strIconName': 'Icono', 'nBuildCost': 'Coste de construcción', 'nIPUsRequired': 'IPUs necesarios', 'bPortOnly': 'Solo puerto',
    'bAvailableByDefault': 'Disponible por defecto', 'strDisplayCategory': 'Categoría visible', 'nCost': 'Coste',
    'nResearchPoints': 'Puntos de investigación', 'nNeededIPUs': 'IPUs necesarios', 'strBranchName': 'Rama',
    'strProgramName': 'Programa', 'bCompletedByDefault': 'Completado por defecto',
    'dateStart': 'Fecha de inicio', 'dateEnd': 'Fecha de fin', 'nScenarioDuration': 'Duración (turnos)',
    'nTurnDuration': 'Duración del turno', 'nStartYear': 'Año de inicio', 'strDescription': 'Descripción', 'strVersion': 'Versión',
    'nStartMonth': 'Mes de inicio', 'nStartDay': 'Día de inicio', 'nEndYear': 'Año de fin', 'nEndMonth': 'Mes de fin', 'nEndDay': 'Día de fin',
    'strHistoricalComparison': 'Comparación histórica (texto al final)', 'nScenarioNumber': 'Orden en la lista de escenarios',
    'eScenarioType': 'Tipo de escenario', 'fileScenario': 'Archivo del escenario', 'fileGame': 'Archivo de partida',
    'strContentPackName': 'Paquete de contenido', 'strGovType': 'Gobierno (ideología)', 'strCulture': 'Cultura (etnia)', 'strTerrain': 'Terreno',
}
COUNTRY_TYPE = {'COUNTRYTYPE_PLAYABLE': 'Playable', 'COUNTRYTYPE_FEATURED': 'Major', 'COUNTRYTYPE_NON_FEATURED': 'Minor'}
# valores que el juego acepta (system/game/namespace.xml); otro valor hace que la partida no se cree («Error creating game»)
COUNTRY_TYPE_FIX = {'COUNTRYTYPE_MINOR': 'COUNTRYTYPE_NON_FEATURED', 'COUNTRYTYPE_MAJOR': 'COUNTRYTYPE_FEATURED'}
FREE_TEXT = re.compile(r'^(strName|sid|vec|str?Description|strDisplayName|strTypeLabel|path|exp)')


# ---------------------------------------------------------------------------------------- almacen
class Store:
    def __init__(self):
        self.docs = {}          # ruta absoluta -> ElementTree
        self.dirty = set()
        self.restructured = set()
        self.parent = {}        # elemento -> padre
        self.doc_of = {}        # elemento -> ruta
        self.ids = {}           # elemento -> id
        self.els = {}           # id -> elemento
        self.next = 1

    def open(self, path):
        path = os.path.abspath(path)
        if path not in self.docs:
            tree = parse(path)
            self.docs[path] = tree
            self._index(tree.getroot(), path)
        return self.docs[path]

    def new_doc(self, path, xml):
        """Documento nuevo que aún no existe en disco (se crea al guardar)."""
        path = os.path.abspath(path)
        tree = ET.ElementTree(ET.fromstring(xml))
        self.docs[path] = tree
        self._index(tree.getroot(), path)
        self.dirty.add(path)
        self.restructured.add(path)
        return tree

    def _index(self, root, path):
        for p in root.iter():
            for c in p:
                self.parent[c] = p
                self.doc_of[c] = path

    def eid(self, el):
        if el not in self.ids:
            self.ids[el] = self.next
            self.els[self.next] = el
            self.next += 1
        return self.ids[el]

    def get(self, i):
        return self.els[int(i)]

    def touch(self, el, structural=False):
        p = self.doc_of[el]
        self.dirty.add(p)
        if structural:
            self.restructured.add(p)

    # ---- propiedades
    def set_prop(self, el, name, value):
        nth = 0
        if '#' in name:
            name, nth = name.split('#')
            nth = int(nth)
        k = -1
        for p in el:
            if p.tag == 'property' and p.get('name') == name:
                k += 1
                if k != nth:
                    continue
                if p.get('value') != value:
                    p.set('value', value)
                    self.touch(el)
                return
        if value in (None, ''):
            return
        new = ET.Element('property', {'name': name, 'value': value})
        props = [i for i, c in enumerate(el) if c.tag == 'property']
        el.insert(props[-1] + 1 if props else 0, new)
        self.parent[new] = el
        self.doc_of[new] = self.doc_of[el]
        self.touch(el, structural=True)

    # ---- estructura
    def detach(self, el):
        par = self.parent[el]
        self.touch(el, structural=True)
        par.remove(el)
        return par

    def attach(self, el, new_parent, path=None, index=None):
        if index is None:
            new_parent.append(el)
        else:
            new_parent.insert(index, el)
        self.parent[el] = new_parent
        path = path or self.doc_of[new_parent]
        for c in el.iter():
            self.doc_of[c] = path
        for p in el.iter():
            for c in p:
                self.parent[c] = p
        self.doc_of[el] = path
        self.touch(el, structural=True)

    def duplicate(self, el):
        par = self.parent[el]
        new = copy.deepcopy(el)
        name = prop(new, 'strName')
        if name is not None:
            for p in new:
                if p.tag == 'property' and p.get('name') == 'strName':
                    p.set('value', name + ' (copia)')
        self.attach(new, par, index=list(par).index(el) + 1)
        return new

    def remove(self, el):
        self.detach(el)

    # ---- guardar
    def fix_load_errors(self, paths):
        """Antes de escribir: corrige lo que haría que el juego no cree la partida («Error creating game»), sea quien sea
        quien lo produjo (editor de regiones al crear naciones, editor de escenarios, archivos a mano):
        eCountryType fuera de PLAYABLE/FEATURED/NON_FEATURED y sidShortDescription de un Player sin texto en ningún
        stringTable (se crea vacío en <escenario>/game/stringTable.xml). Devuelve (rutas a escribir, notas)."""
        paths, notes = list(paths), []
        dirs = {os.path.dirname(p) for p in paths}
        trees = {d: research_tree(d) for d in dirs}
        for path in [p for p in self.docs if os.path.dirname(p) in dirs]:     # todos los cargados del escenario
            for pd in list(self.docs[path].getroot().iter('object')):
                if pd.get('type') != 'MEPlayerData':
                    continue
                # investigaciones completadas cuyos requisitos no lo están: se completan también
                refs = [o for o in pd if o.tag == 'object' and o.get('type') == 'ResearchProjectInitRef']
                miss = missing_prereqs(trees[os.path.dirname(path)], [prop(o, 'strProjectName') for o in refs if prop(o, 'eResearchState') == 'RESEARCH_COMPLETED'])
                if miss:
                    at = list(pd).index(refs[-1]) + 1
                    for q in miss:
                        e = ET.Element('object', {'type': 'ResearchProjectInitRef', 'name': 'objInitResearchRefs'})
                        ET.SubElement(e, 'property', {'name': 'strProjectName', 'value': q})
                        ET.SubElement(e, 'property', {'name': 'eResearchState', 'value': 'RESEARCH_COMPLETED'})
                        pd.insert(at, e)
                        at += 1
                        for x in e.iter():
                            self.doc_of[x] = path
                        self.parent[e] = pd
                    notes.append('%s: investigación completada también %s (requisitos)' % (os.path.basename(path), ', '.join(miss)))
                    self.dirty.add(path)
                    self.restructured.add(path)
                    if path not in paths:
                        paths.append(path)
            for pd in list(self.docs[path].getroot().iter('object')):
                # DipRelInitialValue suelto en MEPlayerData (fuera de su lista): el juego descarta el player*.xml entero
                stray = [o for o in pd if o.tag == 'object' and o.get('type') == 'DipRelInitialValue'] if pd.get('type') == 'MEPlayerData' else []
                if not stray:
                    continue
                lst = next((o for o in pd if o.tag == 'object' and o.get('type') == 'DipRelInitialValueList'), None)
                if lst is None:
                    lst = ET.SubElement(pd, 'object', {'type': 'DipRelInitialValueList', 'name': 'objDipRelInitialValueList'})
                    ET.SubElement(lst, 'property', {'name': 'nDefault', 'value': '500'})
                    self.parent[lst], self.doc_of[lst] = pd, path
                for o in stray:
                    pd.remove(o)
                    lst.append(o)
                    self.parent[o] = lst
                notes.append('%s: %d relaciones diplomáticas movidas a su DipRelInitialValueList' % (os.path.basename(path), len(stray)))
                self.dirty.add(path)
                self.restructured.add(path)
                if path not in paths:
                    paths.append(path)
            for c in self.docs[path].getroot().iter('object'):
                if c.get('type') != 'MECountry':
                    continue
                for p in c.findall('property'):
                    if p.get('name') == 'eCountryType' and p.get('value') not in COUNTRY_TYPE:
                        good = COUNTRY_TYPE_FIX.get(p.get('value'), 'COUNTRYTYPE_NON_FEATURED')
                        notes.append('%s: eCountryType %s → %s' % (os.path.basename(path), p.get('value'), good))
                        p.set('value', good)
                        self.dirty.add(path)
                        if path not in paths:
                            paths.append(path)
        for d in sorted({os.path.dirname(p) for p in paths}):
            gs = os.path.join(d, 'gamestate.xml')
            tp = os.path.join(d, 'game', 'stringTable.xml')
            if gs not in self.docs or not os.path.exists(tp):
                continue
            known = set()
            for f in (os.path.join(GAME, 'system', 'locale', 'en', 'stringTableGame.xml'),
                      os.path.join(GAME, 'system', 'locale', 'en', 'stringTableScenarios.xml')):
                try:
                    known |= {s.get('id') for s in ET.parse(f).getroot().iter('string')}
                except (OSError, ET.ParseError):
                    pass
            table = self.open(tp).getroot()
            known |= {s.get('id') for s in table.iter('string')}
            for pl in self.docs[gs].getroot().iter('object'):
                sid = prop(pl, 'sidShortDescription') if pl.get('type') == 'Player' else None
                if sid and sid not in known:
                    e = ET.Element('string', {'id': sid, 'value': ''})
                    table.append(e)
                    self.parent[e], self.doc_of[e] = table, tp
                    self.dirty.add(tp)
                    self.restructured.add(tp)
                    known.add(sid)
                    notes.append('game/stringTable.xml: texto %s creado (vacío)' % sid)
                    if tp not in paths:
                        paths.append(tp)
        return paths, notes

    def save(self, paths=None, scenario=None):
        written = []
        stamp = time.strftime('%Y%m%d-%H%M%S')
        paths, fixed = self.fix_load_errors([p for p in (paths if paths is not None else self.dirty) if p in self.dirty and p in self.docs])
        for path in sorted(paths):
            if path not in self.dirty:
                continue
            # copias de prueba (--escenarios) fuera del juego: la copia de seguridad cuelga de su carpeta
            in_game = os.path.normcase(path).startswith(os.path.normcase(os.path.abspath(GAME)) + os.sep)
            rel = os.path.relpath(path, GAME if in_game else os.path.dirname(os.path.abspath(SCEN_ROOT)))
            if BACKUPS and os.path.exists(path):
                orig = os.path.join(BACKUP_ROOT, 'archivos_originales', rel)
                if not os.path.exists(orig):
                    os.makedirs(os.path.dirname(orig), exist_ok=True)
                    shutil.copy2(path, orig)       # el original del juego, solo la primera vez
                hist = os.path.join(BACKUP_ROOT, 'historial', stamp, rel)
                os.makedirs(os.path.dirname(hist), exist_ok=True)
                shutil.copy2(path, hist)           # la version anterior a este guardado
            raw = open(path, 'rb').read() if os.path.exists(path) else b'\r\n'     # archivo nuevo: CRLF como los del juego
            crlf = b'\r\n' in raw[:4000]
            tree = self.docs[path]
            if path in self.restructured:
                ET.indent(tree, space='\t')
            data = ET.tostring(tree.getroot(), encoding='unicode')
            # ElementTree descarta las declaraciones xmlns sin usar: se restaura la etiqueta raiz original
            m_old = re.search(r'<objects?\b[^>]*>', raw.decode('utf-8', 'replace'))
            m_new = re.match(r'<[^>]*>', data)
            if m_old and m_new and m_old.group(0).split()[0] == m_new.group(0).split()[0].rstrip('>'):
                data = m_old.group(0) + data[m_new.end():]
            elif not m_old and m_new and data.startswith('<objects ') and 'xmlns:xsi' not in m_new.group(0):
                data = m_new.group(0)[:-1] + ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' + data[m_new.end():]
            data = '<?xml version="1.0" encoding="UTF-8"?>\n' + data + '\n'
            if crlf:
                data = data.replace('\r\n', '\n').replace('\n', '\r\n')
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(data)
            self.dirty.discard(path)
            self.restructured.discard(path)
            written.append(rel)
        return {'written': written, 'history': stamp if written and BACKUPS else None, 'fixed': fixed}

    def revert(self, paths=None):
        for path in list(paths if paths is not None else self.dirty):
            if path in self.docs:
                del self.docs[path]
            self.dirty.discard(path)
            self.restructured.discard(path)
        # se reabre lo descartado bajo demanda; limpiar indices huerfanos
        alive = set(self.docs)
        for d in (self.parent, self.doc_of):
            for k in [k for k, v in self.doc_of.items() if v not in alive]:
                d.pop(k, None)

    # ---- vista generica de un objeto
    def label(self, el):
        n = prop(el, 'strName') or prop(el, 'strDisplayName') or prop(el, 'strINITCountryName') or prop(el, 'strProjectName') \
            or prop(el, 'strCultureName') or prop(el, 'strTargetCountry') or prop(el, 'strTypeLabel') or prop(el, 'strCountry') \
            or prop(el, 'strRegion') or prop(el, 'strKey') or prop(el, 'strSpriteName') or prop(el, 'strString')
        if n is None and prop(el, 'strFromCountry'):
            n = '%s → %s' % (prop(el, 'strFromCountry'), prop(el, 'strToCountry'))
        return n or el.get('name') or ''

    def tree(self, el, depth=1):
        """Resumen de un objeto y sus hijos (para el visor de archivos)."""
        out = {'id': self.eid(el), 'type': el.get('type'), 'name': el.get('name'), 'label': self.label(el),
               'fromFile': el.get('fromFile'),
               'nprops': sum(1 for c in el if c.tag == 'property'), 'nchildren': len(objs(el))}
        if depth > 0:
            out['children'] = [self.tree(c, depth - 1) for c in objs(el)[:2000]]
        return out


STORE = Store()


# ---------------------------------------------------------------------------------------- escenario
DIP_MIN, DIP_MAX = 0, 1000                      # relación diplomática: 0 = pésimas … 1000 = excelentes
_DIP_BANDS = ((200, 'pésimas'), (400, 'malas'), (600, 'regulares'), (800, 'buenas'), (1001, 'excelentes'))


def dip_label(v):
    """Nombre aproximado del tramo de una relación diplomática (cinco tramos iguales entre 0 y 1000)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return '?'
    return next((n for lim, n in _DIP_BANDS if x < lim), 'excelentes') if x >= DIP_MIN else 'pésimas'


class Scenario:
    def __init__(self, name, store=None):
        self.name = name
        self.dir = os.path.join(SCEN_ROOT, name)
        store = self.s = store or STORE          # el almacén actual (al cambiar de juego se crea otro)
        self.paths = [os.path.abspath(os.path.join(self.dir, f)) for f in sorted(os.listdir(self.dir)) if f.endswith('.xml')]
        # como el juego: los country*/player*.xml solo cuentan si game.xml los carga (fromFile=...); los demas se ignoran
        self.unused = []
        gx = os.path.join(self.dir, 'game.xml')
        if os.path.exists(gx):
            used = set(re.findall(r'fromFile="([^"]+)"', open(gx, encoding='utf-8', errors='replace').read()))
            if any(u.startswith('country') for u in used):
                keep = []
                for p in self.paths:
                    f = os.path.basename(p)
                    if f.startswith(('country', 'player')) and f not in used:
                        self.unused.append(f)
                    else:
                        keep.append(p)
                self.paths = keep
        dl = os.path.join(self.dir, 'DisplayLibraries')
        if os.path.isdir(dl):
            self.paths += [os.path.abspath(os.path.join(dl, f)) for f in sorted(os.listdir(dl)) if f.endswith('.xml')]
        for p in self.paths:
            store.open(p)
        self._opts = None
        self.strings = load_strings(self.dir)

    def path(self, f):
        return os.path.join(self.dir, f)

    def all(self, typ, files=None, pred=None):
        res = []
        for p in self.paths:
            f = os.path.basename(p)
            if files and not files(f):
                continue
            for el in self.s.docs[p].getroot().iter('object'):
                if el.get('type') == typ and (pred is None or pred(el)):
                    res.append(el)
        return res

    def countries(self):
        return {prop(e, 'strName'): e for e in self.all('MECountry', lambda f: f.startswith('country'))}

    def regions(self, sea=None):
        land = self.all('Region', lambda f: f.startswith('country'))
        water = self.all('Region', lambda f: f == 'waterWorld.xml')
        return land if sea is False else water if sea is True else land + water

    # ---------------------------------------------------------------- pestanas
    def tabs(self):
        P = prop
        par = lambda e: self.s.parent.get(e)
        ctype = lambda e: COUNTRY_TYPE.get(P(e, 'eCountryType'), 'Minor')
        country_files = lambda f: f.startswith('country')
        T = [
            ('global', 'Global Data', lambda: self.all('Scenario', lambda f: f == 'scenario.xml') + self.all('ScenarioInfo'),
             [('Objeto', lambda e: e.get('type')), ('Nombre', lambda e: P(e, 'strName'))]),
            ('nations', 'Nations', lambda: self.all('MECountry', country_files),
             [('Nombre', lambda e: P(e, 'strName')), ('Tipo', ctype), ('Capital', lambda e: P(e, 'strCapital')), ('Gobierno', lambda e: P(e, 'strGovType'))]),
            ('regions', 'Land Regions', lambda: self.regions(sea=False),
             [('Nombre', lambda e: P(e, 'strName')), ('Propietario', lambda e: P(e, 'strOwner')), ('Controlador', lambda e: P(e, 'strController'))]),
            ('seas', 'Sea Regions', lambda: self.regions(sea=True), [('Nombre', lambda e: P(e, 'strName'))]),
            ('cities', 'Cities', lambda: self.all('City', country_files),
             [('Nombre', lambda e: P(e, 'strName')), ('Ubicación', lambda e: P(par(e), 'strName')), ('Propietario', lambda e: P(e, 'strOwner'))]),
            ('producers', 'Producers', lambda: self.all('Producer', country_files),
             [('Ubicación', lambda e: P(par(e), 'strName')), ('Recurso', lambda e: P(e, 'strResource')), ('Nombre', lambda e: P(e, 'strName'))]),
            ('armies', 'Armies', lambda: self.all('Army', country_files),
             [('Propietario', lambda e: P(e, 'strOwner')), ('Nombre', lambda e: P(e, 'strName')), ('Ubicación', lambda e: P(e, 'strRegion'))]),
            ('airforces', 'Air Forces', lambda: self.all('AirForce', country_files),
             [('Propietario', lambda e: P(e, 'strOwner')), ('Nombre', lambda e: P(e, 'strName')), ('Ubicación', lambda e: P(e, 'strRegion'))]),
            ('navies', 'Navies', lambda: self.all('Fleet', country_files),
             [('Propietario', lambda e: P(e, 'strOwner')), ('Nombre', lambda e: P(e, 'strName')), ('Ubicación', lambda e: P(e, 'strRegion'))]),
            ('govtypes', 'Ideologies', lambda: self.all('GovTypeTemplate'),
             [('Nombre', lambda e: P(e, 'strName')), ('Nombre visible', lambda e: self.strings.get(P(e, 'sidDisplayName') or '') or ''),
              ('Color', lambda e: P(e, 'colColor')), ('Icono', lambda e: P(e, 'strIconName'))]),
            ('cultures', 'Cultures', lambda: self.all('CultureTemplate'),
             [('Cultura', lambda e: P(e, 'strCultureName')), ('Nombre visible', lambda e: _ev()._string(self, P(e, 'sidDisplayName') or '') or ''),
              ('Regiones', lambda e: str(self._culture_count().get(P(e, 'strCultureName'), 0)))]),
            ('alliances', 'Alliances', lambda: self.all('Alliance'),
             [('Nombre', lambda e: P(e, 'strDisplayName')), ('Miembros', lambda e: str(len(objs(e))))]),
            ('wars', 'Wars', lambda: self.all('War'),
             [('Nombre', lambda e: P(e, 'strDisplayName')), ('Atacante', lambda e: P(e, 'strINITAttackerCountryName')), ('Defensor', lambda e: P(e, 'strINITDefenderCountryName'))]),
            ('trade', 'Trade Flows', lambda: self.all('Flow', pred=lambda e: e.get('name') in ('objFlows', 'objTradeFlows')),
             [('Exportador', lambda e: P(e, 'strFromCountry')), ('Importador', lambda e: P(e, 'strToCountry'))]),
            ('aid', 'Aid Flows', lambda: self.all('Flow', pred=lambda e: e.get('name') == 'objAidFlows'),
             [('De', lambda e: P(e, 'strFromCountry')), ('A', lambda e: P(e, 'strToCountry'))]),
            ('access', 'Military Access', lambda: self.all('Treaty', lambda f: f == 'treaties.xml') + self.all('TreatyAgreement', lambda f: f == 'treaties.xml'),
             [('De', lambda e: P(e, 'strFromCountry')), ('A', lambda e: P(e, 'strToCountry')), ('Estado', lambda e: P(e, 'eTreatyState'))]),
            ('players', 'Players / AI', lambda: self.all('MEPlayerData'),
             [('País', lambda e: P(e, 'strOwner')), ('Posición', lambda e: (P(e, 'eInternationalPosition') or '').replace('PLAYER_INTERNATIONAL_POSITION__', '')),
              ('Agresividad', lambda e: P(e, 'nAggressiveNature'))]),
            ('colors', 'Colors', lambda: self.all('Player', lambda f: f == 'gamestate.xml'),
             [('País', lambda e: P(e, 'strName')), ('Color', lambda e: P(e, 'colCountryColor')), ('No jugable', lambda e: P(e, 'bNonPlayable'))]),
            ('diplomacy', 'Diplomacy', lambda: self.all('DipRelInitialValue'),
             [('País', lambda e: self.owner_of_player(e)), ('Con', lambda e: P(e, 'strTargetCountry')), ('Valor (0 pésimas – 1000 excelentes)', lambda e: '%s · %s' % (P(e, 'nValue'), dip_label(P(e, 'nValue'))))]),
            ('historic', 'Historic Countries', lambda: self.all('HistoricCountry'),
             [('País', lambda e: P(e, 'strCountry')), ('Regiones', lambda e: ', '.join(P(k, 'strRegion') or '' for k in objs(e)))]),
            ('events', 'Events', lambda: [e for e in self.all_types(('ScriptedEventDef', 'PlayerDecisionDef', 'PlayerDecisionTrigPlayEvent', 'DecisionPointDef'))],
             [('Clase', lambda e: '%s%s' % (_ev().event_class(self, e)[0], '' if _ev().is_generic(P(e, 'strTypeLabel')) else ' · del escenario')),
              ('Tipo', lambda e: _ev().KIND_ES.get(e.get('type'), e.get('type'))), ('Nombre', lambda e: P(e, 'strTypeLabel') or P(e, 'strName') or ''),
              ('Quién', lambda e: _ev()._who(e)), ('Qué hace', lambda e: _ev().short(self, e)), ('Archivo', lambda e: os.path.basename(self.s.doc_of[e]))]),
            ('terrains', 'Terrain Types', lambda: self.all('TerrainType'),
             [('Terreno', lambda e: P(e, 'strTerrain')), ('Nombre visible', lambda e: _ev()._string(self, P(e, 'sidDisplayName') or '') or ''),
              ('Regiones', lambda e: str(sum(1 for r in self.regions() if P(r, 'strTerrain') == P(e, 'strTerrain')))),
              ('Archivo', lambda e: os.path.basename(self.s.doc_of[e]))]),
            ('models_land', 'Unit Models (land)', lambda: self.model_nodes('MKDTableCountryAliasesLand.xml'),
             [('País', lambda e: P(e, 'strKey') or '(por defecto)'), ('Unidades', lambda e: str(len(objs(e))))]),
            ('models_air', 'Unit Models (air)', lambda: self.model_nodes('MKDTableCountryAliasesAir.xml'),
             [('País', lambda e: P(e, 'strKey') or '(por defecto)'), ('Unidades', lambda e: str(len(objs(e))))]),
            ('infra', 'Infrastructure', lambda: self.all('TransportationLevel'),
             [('Nivel', lambda e: P(e, 'nLevel')), ('Coste', lambda e: P(e, 'nCost')), ('Mantenimiento', lambda e: P(e, 'nMaintenanceCost') or '0'),
              ('Archivo', lambda e: os.path.basename(self.s.doc_of[e]))]),
            ('units', 'Unit Templates', lambda: self.all('UnitTemplate'),
             [('Nombre', lambda e: P(e, 'strName')), ('Tipo', lambda e: (P(e, 'eType') or '').replace('UNIT_TYPE_', ''))]),
            ('outputs', 'Factory Outputs', lambda: [e for e in self.all_prefix('FactoryOutput')],
             [('Nombre', lambda e: P(e, 'strName')), ('Tipo', lambda e: e.get('type'))]),
            ('research', 'Research Projects', lambda: [e for e in self.all_prefix('ResearchProj') if self.s.parent.get(e) is not None
                                                       and self.s.parent[e].get('type') == 'ResearchProjectSet'],
             [('Nombre', lambda e: P(e, 'strName')), ('Rama', lambda e: (P(e, 'strBranchName') or '').replace('RESEARCH_BRANCH_', ''))]),
        ]
        return T

    def _culture_count(self):
        c = getattr(self, '_cc', None)          # la lista de la pestaña lo pide en cada fila: se reutiliza unos segundos
        if c is None or time.time() - c[0] > 3:
            c = self._cc = (time.time(), Counter(prop(r, 'strCulture') for r in self.regions(sea=False)))
        return c[1]

    def all_types(self, types):
        res = []
        for p in self.paths:
            for el in self.s.docs[p].getroot().iter('object'):
                if el.get('type') in types:
                    res.append(el)
        return res

    def owner_of_player(self, el):
        p = self.s.parent.get(el)
        while p is not None and p.tag == 'object' and p.get('type') != 'MEPlayerData':
            p = self.s.parent.get(p)
        return prop(p, 'strOwner') if p is not None else ''

    def model_nodes(self, fname):
        res = []
        for p in self.paths:
            if os.path.basename(p) == fname:
                root = self.s.docs[p].getroot()
                for el in root.iter('object'):
                    if el.get('type') == 'MKDNode' and prop(el, 'strSubNodeKeyName', '').startswith('CountryAlias'):
                        res.append(el)
        return res

    def all_prefix(self, prefix):
        res = []
        for p in self.paths:
            for el in self.s.docs[p].getroot().iter('object'):
                t = el.get('type') or ''
                par = self.s.parent.get(el)
                if t.startswith(prefix) and par is not None and (par.get('type') or '').endswith('Set'):
                    res.append(el)
        return res

    def tab_rows(self, key):
        for k, label, finder, cols in self.tabs():
            if k == key:
                rows = []
                for e in finder():
                    rows.append({'id': self.s.eid(e), 'cols': [c(e) or '' for _, c in cols]})
                return {'key': k, 'label': label, 'columns': [c for c, _ in cols], 'rows': rows}
        raise KeyError(key)

    # ---------------------------------------------------------------- opciones de los campos
    def options(self):
        if self._opts is not None:
            return self._opts
        vals = defaultdict(Counter)
        for p in self.paths:
            for el in self.s.docs[p].getroot().iter('property'):
                n = el.get('name')
                if n and el.get('value') is not None and not FREE_TEXT.match(n) and not n.startswith(('n', 'f')):
                    vals[n][el.get('value')] += 1
        nations = sorted(self.countries())
        land = sorted(prop(e, 'strName') for e in self.regions(sea=False))
        sea = sorted(prop(e, 'strName') for e in self.regions(sea=True))
        units = sorted(prop(e, 'strName') for e in self.all('UnitTemplate'))
        outputs = sorted(prop(e, 'strName') for e in self.all_prefix('FactoryOutput'))
        cities = sorted(prop(e, 'strName') for e in self.all('City'))
        opts = {n: sorted(c) for n, c in vals.items() if len(c) <= 80}
        for n in ('strOwner', 'strController', 'strFromCountry', 'strToCountry', 'strINITCountryName', 'strTargetCountry',
                  'strINITAttackerCountryName', 'strINITDefenderCountryName', 'strHomelands', 'strFlagName'):
            opts[n] = nations
        opts['strRegion'] = land + sea
        opts['strCountry'] = nations
        opts['strSpriteName'] = sorted({e.get('value') for p in self.paths for e in self.s.docs[p].getroot().iter('property')
                                        if e.get('name') == 'strSpriteName' and e.get('value')})
        opts['strPortForRegion'] = sea
        opts['strInitialWorkOrder'] = [''] + outputs
        opts['strCapital'] = opts['strOriginalCapital'] = cities
        opts['strGovType'] = sorted({prop(e, 'strName') for e in self.all('GovTypeTemplate') if prop(e, 'strName')}
                                    | {prop(c, 'strGovType') for c in self.countries().values() if prop(c, 'strGovType')})
        opts['__region'] = land + sea
        opts['__unit'] = units
        opts['bool'] = ['true', 'false']
        # listas completas (no solo las que ya se usan): posición internacional y perfiles diplomático y de tratados
        pos = {'PLAYER_INTERNATIONAL_POSITION__' + x for x in ('EXPANSIONIST', 'NEUTRAL', 'STATUSQUO', 'TUTORIAL')}
        opts['eInternationalPosition'] = sorted(pos | set(opts.get('eInternationalPosition', [])))
        opts['strDipRelProcListName'] = sorted({prop(e, 'strName') for e in self.all('DipRelProcessorRefList') if prop(e, 'strName')}
                                               | set(opts.get('strDipRelProcListName', [])))
        opts['strAITreatyEvalListName'] = sorted({prop(e, 'strName') for e in self.all('AIEvalRefList') if prop(e, 'strName')}
                                                 | set(opts.get('strAITreatyEvalListName', [])))
        # tipos cerrados: todos los valores de cada Enum del juego (namespace.xml), no solo los que ya se usan
        for n, vals in enum_options().items():
            opts[n] = sorted(set(vals) | set(opts.get(n, [])))
        opts['strCulture'] = opts['strCultureName'] = sorted({prop(e, 'strCultureName') for e in self.all('CultureTemplate') if prop(e, 'strCultureName')}
                                                              | {prop(r, 'strCulture') for r in self.regions(sea=False) if prop(r, 'strCulture')})
        opts['strTerrain'] = sorted({prop(e, 'strTerrain') for e in self.all('TerrainType') if prop(e, 'strTerrain')}
                                    | {prop(r, 'strTerrain') for r in self.regions() if prop(r, 'strTerrain')})
        opts['strResource'] = sorted({prop(e, 'strResource') for e in self.all('Producer') if prop(e, 'strResource')} | set(opts.get('strResource', [])))
        self._opts = opts
        return opts

    # ---------------------------------------------------------------- detalle
    def detail(self, i):
        el = self.s.get(i)
        s = self.s
        crumbs = []
        p = s.parent.get(el)
        while p is not None and p.tag == 'object':
            crumbs.insert(0, {'id': s.eid(p), 'label': '%s %s' % (p.get('type'), s.label(p))})
            p = s.parent.get(p)
        props = []
        seen = Counter()
        for c in el:
            if c.tag != 'property':
                continue
            n = c.get('name')
            v = c.get('value')
            key = n if seen[n] == 0 else '%s#%d' % (n, seen[n])
            seen[n] += 1
            props.append({'name': n, 'key': key, 'value': v, 'inherit': c.get('inheritFrom') or c.get('computeFrom'),
                          'label': LABELS.get(n, n), 'text': self.strings.get(v) if v and v.startswith('SID.') else None,
                          'kind': 'bool' if n.startswith('b') and v in ('true', 'false') else
                          'color' if n.startswith('col') else 'number' if re.match(r'^(n|f|n64)[A-Z]', n) else 'text'})
        children = [{'id': s.eid(c), 'type': c.get('type'), 'name': c.get('name'), 'label': s.label(c),
                     'summary': self.child_summary(c)} for c in objs(el)]
        extra = {}
        t = el.get('type')
        if t in ('City', 'Producer'):
            extra['region'] = prop(s.parent.get(el), 'strName')
        if t in ('Region', 'City') and prop(el, 'strName'):
            extra['map'] = prop(el, 'strName') if t == 'Region' else prop(s.parent.get(el), 'strName')
        if t in ('Army', 'AirForce', 'Fleet'):
            extra['map'] = prop(el, 'strRegion')
        return {'id': s.eid(el), 'type': t, 'name': el.get('name'), 'label': s.label(el),
                'file': os.path.relpath(s.doc_of.get(el, ''), GAME), 'crumbs': crumbs, 'props': props,
                'children': children, 'extra': extra, 'dirty': sorted(os.path.basename(p) for p in s.dirty)}

    def child_summary(self, c):
        if c.get('type') == 'UnitSummary':
            return '%s × %s' % (prop(c, 'nNumber'), prop(c, 'strName'))
        if c.get('type') == 'Factory':
            return 'IPUs %s, nivel %s' % (prop(c, 'nIPUs'), prop(c, 'nTechLevel') or '-')
        return ''

    # ---------------------------------------------------------------- edicion con reglas
    def update(self, i, values, move_children=True):
        """values: {propiedad: valor}; '__region' mueve una ciudad/productor a otra region."""
        el = self.s.get(i)
        t = el.get('type')
        notes = []
        old_owner = prop(el, 'strOwner')
        new_region = values.pop('__region', None)
        move_point = values.pop('__movepoint', None)      # '1': llevar también el punto (vecPosition) dentro de la región
        if move_point and not new_region and t in ('City', 'Producer'):
            new_region = prop(self.s.parent.get(el), 'strName')
        if t == 'DipRelInitialValue' and 'nValue' in values:      # antes de cambiar nada: 0 (pésimas) a 1000 (excelentes)
            v = str(values['nValue']).strip()
            if not re.fullmatch(r'-?\d+', v) or not (DIP_MIN <= int(v) <= DIP_MAX):
                raise ValueError('la relación diplomática va de %d (pésimas) a %d (excelentes): «%s» no vale' % (DIP_MIN, DIP_MAX, values['nValue']))
        for n, v in values.items():
            self.s.set_prop(el, n, v)
        # una region / ejercito vive en el archivo de su propietario
        new_owner = prop(el, 'strOwner')
        if t in ('Region', 'Army', 'AirForce', 'Fleet') and new_owner != old_owner and self.s.doc_of[el].endswith('.xml') \
                and os.path.basename(self.s.doc_of[el]).startswith('country'):
            dst = self.countries().get(new_owner)
            if dst is None:
                raise ValueError('no existe el país «%s»' % new_owner)
            self.s.detach(el)
            # antes del primer Army/AirForce/Fleet del destino si es una region (orden habitual del archivo)
            idx = None
            if t == 'Region':
                kids = list(dst)
                firsts = [k for k, c in enumerate(kids) if c.tag == 'object' and c.get('type') in ('Army', 'AirForce', 'Fleet', 'CultureSet', 'WarList')]
                regs = [k for k, c in enumerate(kids) if c.tag == 'object' and c.get('type') == 'Region']
                idx = (regs[-1] + 1) if regs else (firsts[0] if firsts else None)
            self.s.attach(el, dst, path=self.s.doc_of[dst], index=idx)
            notes.append('movida a %s' % os.path.basename(self.s.doc_of[dst]))
            if t == 'Region' and move_children:
                ctrl = prop(el, 'strController')
                for c in el.iter('object'):
                    if c is not el and c.get('type') in ('City', 'Producer'):
                        if prop(c, 'strOwner') == old_owner:
                            self.s.set_prop(c, 'strOwner', new_owner)
                        self.s.set_prop(c, 'strController', ctrl)
                notes.append('ciudades y productores pasan a %s' % new_owner)
        elif t == 'Region' and 'strController' in values and move_children:
            for c in el.iter('object'):
                if c is not el and c.get('type') in ('City', 'Producer'):
                    self.s.set_prop(c, 'strController', values['strController'])
        if new_region and t in ('City', 'Producer'):
            # también de mar: una ciudad puede depender de una región aunque esté lejos (p. ej. bases en la Antártida)
            reg = next((r for r in self.regions(sea=False) + self.regions(sea=True) if prop(r, 'strName') == new_region), None)
            if reg is None:
                raise ValueError('no existe la región «%s»' % new_region)
            if move_point:
                import scenario_layers
                x, y = scenario_layers.region_point(self, new_region)
                self.s.set_prop(el, 'vecPosition', scenario_layers._vec(x, y))
                notes.append('punto movido dentro de %s (%.3f, %.3f)' % (new_region, x, y))
            if reg is not self.s.parent[el]:
                self.s.detach(el)
                self.s.attach(el, reg, path=self.s.doc_of[reg])
                if prop(reg, 'strOwner'):         # una región de mar no tiene dueño: la ciudad conserva el suyo
                    self.s.set_prop(el, 'strOwner', prop(reg, 'strOwner'))
                    self.s.set_prop(el, 'strController', prop(reg, 'strController'))
                notes.append('movida a la región %s (%s)' % (new_region, os.path.basename(self.s.doc_of[reg])))
        # relación diplomática inicial: la cifra de A→B se copia a B→A (en el player*.xml del otro país) para que coincidan
        if t == 'DipRelInitialValue' and 'nValue' in values:
            import scenario_layers
            a, b = self.owner_of_player(el), prop(el, 'strTargetCountry')
            if a and b and a != b:
                notes += scenario_layers.fix_diplomacy(self, [{'a': a, 'b': b, 'use': 'a'}])
        self._opts = None
        return notes

    # ---------------------------------------------------------------- validacion
    def validate(self, map_regions=None, adjacency=None):
        """map_regions: {nombre: es_mar} del mapa; adjacency: {nombre: set(vecinos)}."""
        P = prop
        issues = []
        for f in getattr(self, 'unused', []):
            issues.append(('aviso', '%s no está en game.xml: el juego no lo carga (se ignora)' % f, None))
        countries = self.countries()
        land = {}
        for r in self.regions(sea=False):
            n = P(r, 'strName')
            if n in land:
                issues.append(('error', 'Región repetida: %s' % n, self.s.eid(r)))
            land[n] = r
            f = os.path.basename(self.s.doc_of[r])
            if f != 'country%s.xml' % P(r, 'strOwner'):
                issues.append(('error', 'La región %s es de %s pero está en %s' % (n, P(r, 'strOwner'), f), self.s.eid(r)))
            for k in ('strOwner', 'strController'):
                if P(r, k) not in countries:
                    issues.append(('error', '%s de %s: no existe el país «%s»' % (LABELS[k], n, P(r, k)), self.s.eid(r)))
        sea = {P(r, 'strName') for r in self.regions(sea=True)}
        if map_regions:
            for n, is_sea in map_regions.items():
                if not is_sea and n not in land and n not in ('BasicRegionLists', 'Historic'):
                    issues.append(('aviso', 'La región del mapa %s no tiene datos en el escenario' % n, None))
            for n in land:
                if n not in map_regions:
                    issues.append(('error', 'La región %s no existe en el mapa' % n, self.s.eid(land[n])))
        cities = {}
        for c in self.all('City'):
            n = P(c, 'strName')
            cities.setdefault(n, []).append(c)
            reg = P(self.s.parent[c], 'strName')
            port = P(c, 'strPortForRegion')
            if port:
                if port not in sea:
                    issues.append(('error', 'Ciudad %s: el puerto %s no es una región de mar' % (n, port), self.s.eid(c)))
                elif adjacency and port not in adjacency.get(reg, set()):
                    issues.append(('aviso', 'Ciudad %s: %s no es vecina de %s' % (n, port, reg), self.s.eid(c)))
        for n, cs in cities.items():
            if len(cs) > 1:
                issues.append(('aviso', 'Ciudad repetida: %s (%d)' % (n, len(cs)), self.s.eid(cs[0])))
        for name, c in countries.items():
            if not any(o.get('type') == 'Region' for o in objs(c)):
                continue   # pais que aun no existe en el escenario (puede aparecer durante la partida)
            cap = P(c, 'strCapital')
            if cap and cap not in cities:
                issues.append(('error', 'País %s: la capital %s no existe' % (name, cap), self.s.eid(c)))
            elif cap and P(cities[cap][0], 'strOwner') != name:
                issues.append(('aviso', 'País %s: su capital %s pertenece a %s' % (name, cap, P(cities[cap][0], 'strOwner')), self.s.eid(c)))
        import scenario_new       # cada nación con territorio: capital propia y habitantes > 2
        for m in scenario_new.check_nations(self):
            issues.append(('aviso', m, None))
        units = {norm(P(u, 'strName')) for u in self.all('UnitTemplate')}
        for t in ('Army', 'AirForce', 'Fleet'):
            for g in self.all(t):
                n, where = P(g, 'strName'), P(g, 'strRegion')
                if P(g, 'strOwner') not in countries:
                    issues.append(('error', '%s %s: no existe el país %s' % (t, n, P(g, 'strOwner')), self.s.eid(g)))
                # una flota puede estar en el mar o atracada en una region de tierra con ciudad-puerto
                if t == 'Fleet' and where not in sea:
                    if where not in land:
                        issues.append(('error', 'Flota %s: la región %s no existe' % (n, where), self.s.eid(g)))
                    elif not any(c.get('type') == 'City' and P(c, 'strPortForRegion') for c in objs(land[where])):
                        issues.append(('error', 'Flota %s: está atracada en %s, que no tiene ciudad con puerto' % (n, where), self.s.eid(g)))
                # un ejercito puede estar en el mar (transportado), como en los escenarios del juego
                if t != 'Fleet' and where not in land and where not in sea:
                    issues.append(('error', '%s %s: la región %s no existe' % (t, n, where), self.s.eid(g)))
                for u in objs(g):
                    if units and norm(P(u, 'strName')) not in units:
                        issues.append(('aviso', '%s %s: unidad desconocida %s' % (t, n, P(u, 'strName')), self.s.eid(g)))
        for a in self.all('AllianceMember'):
            if P(a, 'strINITCountryName') not in countries:
                issues.append(('error', 'Alianza: no existe el país %s' % P(a, 'strINITCountryName'), self.s.eid(a)))
        # reglas del editor oficial (ed.exe, EditorStringTable.dll): guerras, unidades y nombres repetidos
        players = {P(p, 'strName') for p in self.all('Player')}
        ally = {}
        for a in self.all('Alliance'):
            for m in objs(a):
                if m.get('type') == 'AllianceMember':
                    ally[P(m, 'strINITCountryName')] = P(a, 'strDisplayName')
        seen_wars = set()
        for w in self.all('War'):
            wn = P(w, 'strDisplayName')
            a, d = P(w, 'strINITAttackerCountryName'), P(w, 'strINITDefenderCountryName')
            for k in ('strINITAttackerCountryName', 'strINITDefenderCountryName'):
                if P(w, k) and P(w, k) not in countries:
                    issues.append(('error', 'Guerra %s: no existe %s' % (wn, P(w, k)), self.s.eid(w)))
                elif P(w, k) and players and P(w, k) not in players:
                    issues.append(('error', 'Guerra %s: %s no está registrado en la partida (gamestate.xml)' % (wn, P(w, k)), self.s.eid(w)))
            if a and a == d:
                issues.append(('error', 'Guerra %s: el atacante también es el defensor' % wn, self.s.eid(w)))
            elif a and d and ally.get(a) and ally.get(a) == ally.get(d):
                issues.append(('error', 'Guerra %s: %s y %s están en la misma alianza (%s)' % (wn, a, d, ally[a]), self.s.eid(w)))
            if a and d and (a, d) in seen_wars:
                issues.append(('error', 'Guerra %s: %s ya está en guerra con %s' % (wn, a, d), self.s.eid(w)))
            seen_wars |= {(a, d), (d, a)}
        for t in ('Army', 'AirForce', 'Fleet'):
            for g in self.all(t):
                for u in objs(g):
                    if u.get('type') == 'UnitSummary' and not (P(u, 'nNumber') or '1').lstrip('-').isdigit() or \
                            u.get('type') == 'UnitSummary' and int(P(u, 'nNumber') or 1) <= 0:
                        issues.append(('error', '%s %s: el número de unidades de %s debe ser mayor que 0' % (t, P(g, 'strName'), P(u, 'strName')), self.s.eid(g)))
        for typ, label in (('MECountry', 'País'), ('UnitTemplate', 'Plantilla de unidad')):
            names = Counter(P(e, 'strName') for e in self.all(typ))
            for n, k in names.items():
                if k > 1:
                    issues.append(('error', '%s repetido: %s (%d veces)' % (label, n, k), None))
        return [{'level': l, 'msg': m, 'id': i} for l, m, i in issues] + self.load_errors()

    def load_errors(self):
        """Valores que el juego rechaza al leer el escenario y que impiden crear la partida («Error creating game»):
        eCountryType fuera de su lista y sidShortDescription de un Player sin texto. Cada uno trae su arreglo."""
        out = []
        for d in self.all('ScenarioDisplaySettings'):
            mp = prop(d, 'strMapName')
            if mp and not os.path.exists(os.path.join(GAME, 'Modern Europe', 'system', 'DisplayLibraries', 'Maps', mp, 'xml', 'map.xml')):
                out.append({'level': 'error', 'id': self.s.eid(d),
                            'msg': 'El regionpack %s no está instalado (falta DisplayLibraries/Maps/%s/xml/map.xml) y la partida no se crea.' % (mp, mp)})
        for pd in self.all('MEPlayerData'):
            n = sum(1 for o in objs(pd) if o.get('type') == 'DipRelInitialValue')
            if n:
                out.append({'level': 'error', 'id': self.s.eid(pd),
                            'msg': 'Jugador %s: %d relaciones diplomáticas fuera de su DipRelInitialValueList; el juego descarta el archivo y la partida no se crea (se corrige al guardar).'
                                   % (prop(pd, 'strOwner') or prop(pd, 'strName'), n)})
        tree = research_tree(self.dir)
        for pd in self.all('MEPlayerData'):
            done = [prop(o, 'strProjectName') for o in objs(pd) if o.get('type') == 'ResearchProjectInitRef' and prop(o, 'eResearchState') == 'RESEARCH_COMPLETED']
            miss = missing_prereqs(tree, done)
            if miss:
                out.append({'level': 'error', 'id': self.s.eid(pd),
                            'msg': 'Jugador %s: investigaciones completadas sin sus requisitos (%s); la partida no se crea (se corrige al guardar).'
                                   % (prop(pd, 'strOwner') or prop(pd, 'strName'), ', '.join(miss))})
        for c in self.all('MECountry'):
            v = prop(c, 'eCountryType')
            if v and v not in COUNTRY_TYPE:
                good = COUNTRY_TYPE_FIX.get(v, 'COUNTRYTYPE_NON_FEATURED')
                out.append({'level': 'error', 'id': self.s.eid(c),
                            'msg': 'País %s: eCountryType = %s no existe en el juego y la partida no se crea (válidos: %s).'
                                   % (prop(c, 'strName'), v, ', '.join(COUNTRY_TYPE)),
                            'fix': {'kind': 'range', 'id': self.s.eid(c), 'prop': 'eCountryType', 'value': good, 'label': 'Cambiar a %s' % good}})
        known = set(self.strings)
        f = os.path.join(GAME, 'system', 'locale', 'en', 'stringTableScenarios.xml')
        if os.path.exists(f):
            try:
                known |= {s.get('id') for s in ET.parse(f).getroot().iter('string')}
            except ET.ParseError:
                pass
        for p in self.all('Player'):
            sid = prop(p, 'sidShortDescription')
            if sid and sid not in known:
                alt = prop(p, 'sidName') if prop(p, 'sidName') in known else None
                out.append({'level': 'error', 'id': self.s.eid(p),
                            'msg': 'Jugador %s: el texto %s no existe y la partida no se crea.' % (prop(p, 'strName'), sid),
                            'fix': {'kind': 'range', 'id': self.s.eid(p), 'prop': 'sidShortDescription', 'value': alt,
                                    'label': 'Usar %s' % alt} if alt else None})
        return out


def norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def load_strings(scen_dir):
    out = {}
    files = [os.path.join(GAME, 'system', 'locale', 'en', 'stringTableGame.xml'), os.path.join(scen_dir, 'game', 'stringTable.xml')]
    for f in files:
        if os.path.exists(f):
            try:
                for s in ET.parse(f).getroot().iter('string'):
                    out[s.get('id')] = s.get('value')
            except ET.ParseError:
                pass
    return out


def research_tree(scen_dir):
    """{proyecto: (bCompletedByDefault, [requisitos])} de sharedDataResearch.xml del escenario (o de ScenarioDefaults)."""
    tree = {}
    for f in (os.path.join(scen_dir, 'sharedDataResearch.xml'),
              os.path.join(GAME, 'Modern Europe', 'system', 'ScenarioDefaults', 'sharedDataResearch.xml')):
        if os.path.exists(f):
            try:
                root = ET.parse(f).getroot()
            except ET.ParseError:
                continue
            for o in root.iter('object'):
                if (o.get('type') or '').startswith('ResearchProj') and prop(o, 'strName'):
                    tree[prop(o, 'strName')] = (prop(o, 'bCompletedByDefault') == 'true',
                                                [prop(q, 'strProjectName') for q in o.findall('object') if q.get('type') == 'ResearchProjectPreReq'])
            break
    return tree


def missing_prereqs(tree, completed):
    """Requisitos (de todos los niveles) que faltan para que el juego pueda completar 'completed' al empezar: los que no
    están completados ni tienen bCompletedByDefault. Con alguno, la partida no se crea («pre-reqs never met»)."""
    have, out, todo = set(completed), [], list(completed)
    while todo:
        for q in tree.get(todo.pop(), (False, []))[1]:
            if q in tree and q not in have and not tree[q][0]:
                have.add(q)
                out.append(q)
                todo.append(q)
    return out


def scenarios():
    return sorted(x for x in os.listdir(SCEN_ROOT) if os.path.exists(os.path.join(SCEN_ROOT, x, 'gamestate.xml')))


class DocView(Scenario):
    """Vista de documentos sueltos (no de escenario): mismo detalle, edicion sin reglas especiales."""
    def __init__(self, store=None):
        store = self.s = store or STORE
        self.name = None
        self.paths = []
        self._opts = {}
        self.strings = load_strings(os.path.join(GAME, '_'))

    def options(self):
        return {'bool': ['true', 'false']}

    def update(self, i, values, move_children=True):
        el = self.s.get(i)
        for n, v in values.items():
            if not n.startswith('__'):
                self.s.set_prop(el, n, v)
        return []


WAR_EVENT = """<object type="ScriptedEventDef" name="objScriptedEventDefs">
	<property name="strTypeLabel" value="{label}"/>
	<property name="pathPlayer" value="{{Object:Single:Player}}scratch.objPlayer"/>
	<object type="PlayerGenNames" name="objPlayerGen"><property name="strName" value="{att}"/></object>
	<object type="TriggerEvalRandomChance" name="objTriggerEval">
		<property name="nPercentChance" value="{pct}"/>
		<object type="AccessorRuleSet" name="objConditions">
			<property name="strDebugLabel" value="Date is {date} or later"/>
			<property name="pathPlayer" value="{{Object:Single:Player}}scratch.objPlayer"/>
			<object type="AccessorGetCurrentDate" name="objAccessors"><property name="pathOutput" value="{{Date:Single}}scratch.dateGameDate"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="{{Date:Single}}scratch.dateGameDate GTE {date}"/></object>
		</object>
		<object type="AccessorRuleSet" name="objConditions">
			<property name="strDebugLabel" value="Both countries exist and are not at war"/>
			<property name="pathPlayer" value="{{Object:Single:Player}}scratch.objPlayer"/>
			<object type="AccessorGetCountry" name="objAccessors"><property name="pathOutput" value="{{Object:Single:Country}}scratch.objCountryAttacker"/><property name="strCountry" value="{att}"/></object>
			<object type="AccessorGetCountry" name="objAccessors"><property name="pathOutput" value="{{Object:Single:Country}}scratch.objCountryTarget"/><property name="strCountry" value="{tgt}"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="exists({{Object:Single:Country}}scratch.objCountryAttacker)"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="exists({{Object:Single:Country}}scratch.objCountryTarget)"/></object>
			<object type="AccessorIsAtWar" name="objAccessors"><property name="pathOutput" value="{{bool:Single}}scratch.bAlreadyAtWar"/><property name="nCountryID" inheritFrom="{{Object:Single:Country}}scratch.objCountryAttacker.nCountryID"/><property name="nEnemyCountryID" inheritFrom="{{Object:Single:Country}}scratch.objCountryTarget.nCountryID"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="!{{bool:Single}}scratch.bAlreadyAtWar"/></object>
		</object>
	</object>
	<object type="CustomEffectDefActions" name="objEffects">
		<property name="strLabel" value="{att} declares war on {tgt}"/>
		<object type="ActProposeDeclareWar" name="objActions"><property name="strFromCountry" value="{att}"/><property name="strToCountry" value="{tgt}"/></object>
	</object>
	<object type="ArgumentList" name="objArgLists"><property name="strName" value="Display Data"/></object>
</object>"""


def create_war_event(scen, attacker, target, date, pct=80):
    """Anade a sharedDataEvents.xml del escenario un evento: 'attacker' declara la guerra a 'target' desde 'date'
    (MM/DD/YYYY) con 'pct' % por turno. Crea el archivo y lo registra en scenario.xml si no existe."""
    countries = scen.countries()
    for c in (attacker, target):
        if c not in countries:
            raise ValueError('no existe el país «%s»' % c)
    if not re.match(r'^\d{2}/\d{2}/\d{4}$', date):
        raise ValueError('fecha no válida (MM/DD/AAAA)')
    st = scen.s
    path, notes = _events_doc(scen)
    root = st.docs[path].getroot()
    shared = next(o for o in root.iter('object') if o.get('type') == 'MESharedData')
    label = 'MOD_%sWarOn%s_%s' % (re.sub(r'\W', '', attacker), re.sub(r'\W', '', target), date.replace('/', ''))
    ev = ET.fromstring(WAR_EVENT.format(label=label, att=attacker, tgt=target, date=date, pct=int(pct)))
    st.attach(ev, shared, path=path)
    notes.append('evento %s añadido' % label)
    return st.eid(ev), notes


def _events_doc(scen):
    """sharedDataEvents.xml del escenario (lo crea y lo registra en scenario.xml si no existe)."""
    st = scen.s
    path = os.path.abspath(os.path.join(scen.dir, 'sharedDataEvents.xml'))
    notes = []
    if path not in scen.paths:
        if os.path.exists(path):
            st.open(path)
        else:       # solo en memoria: el archivo se escribe al «Guardar»
            st.new_doc(path, '<objects name="Object Load" version="0.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                             '<object type="MESharedData" name=""></object></objects>')
        scen.paths.append(path)
        sx = scen.all('Scenario', lambda f: f == 'scenario.xml')[0]
        refs = [o for o in objs(sx) if o.get('type') == 'SharedDataFileRef']
        nid = max(int(prop(o, 'nFileRefID', '0')) for o in refs) + 1 if refs else 1
        ref = ET.fromstring('<object type="SharedDataFileRef" name="objSharedDataFileRefs"><property name="nFileRefID" value="%d"/>'
                            '<property name="bScenario" value="true"/><property name="strFileLoadName" value="Shared Data - Events"/>'
                            '<property name="fileSharedData" value="sharedDataEvents.xml"/></object>' % nid)
        idx = list(sx).index(refs[-1]) + 1 if refs else len(sx)
        st.attach(ref, sx, index=idx)
        notes.append('creado sharedDataEvents.xml y registrado en scenario.xml')
    return path, notes


# embargo comercial al empezar: un evento que se dispara una sola vez (en el turno indicado), como los eventos del juego
EMBARGO_EVENT = """<object type="ScriptedEventDef" name="objScriptedEventDefs">
	<property name="strTypeLabel" value="{label}"/>
	<property name="pathPlayer" value="{{Object:Single:Player}}scratch.objPlayer"/>
	<object type="PlayerGenNames" name="objPlayerGen"><property name="strName" value="{org}"/></object>
	<object type="TriggerEvalUntilTurn" name="objTriggerEval">
		<property name="nTurn" value="{until}"/>
		<object type="AccessorRuleSet" name="objConditions">
			<property name="strDebugLabel" value="Turn is {turn}"/>
			<property name="pathPlayer" value="{{Object:Single:Player}}scratch.objPlayer"/>
			<object type="AccessorGetCurrentTurn" name="objAccessors"><property name="pathOutput" value="{{int:Single}}scratch.nGameTurn"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="{{int:Single}}scratch.nGameTurn == {turn}"/></object>
		</object>
		<object type="AccessorRuleSet" name="objConditions">
			<property name="strDebugLabel" value="Both countries exist"/>
			<property name="pathPlayer" value="{{Object:Single:Player}}scratch.objPlayer"/>
			<object type="AccessorGetCountry" name="objAccessors"><property name="pathOutput" value="{{Object:Single:Country}}scratch.objCountryFrom"/><property name="strCountry" value="{org}"/></object>
			<object type="AccessorGetCountry" name="objAccessors"><property name="pathOutput" value="{{Object:Single:Country}}scratch.objCountryTo"/><property name="strCountry" value="{tgt}"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="exists({{Object:Single:Country}}scratch.objCountryFrom)"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="exists({{Object:Single:Country}}scratch.objCountryTo)"/></object>
		</object>
	</object>
	<object type="CustomEffectDefActions" name="objEffects">
		<property name="strLabel" value="{org} embargoes {tgt}"/>
		<object type="ActSetTradeRelations" name="objActions"><property name="strCountry" value="{tgt}"/><property name="eTradeRelations" value="TRADE_RELATIONS_EMBARGOED"/></object>
	</object>
	<object type="ArgumentList" name="objArgLists"><property name="strName" value="Display Data"/></object>
</object>"""


def create_embargo_event(scen, origin, target, turn=1):
    """Evento: 'origin' embarga el comercio con 'target' en el turno 'turn' (una sola vez; el jugador puede levantarlo)."""
    countries = scen.countries()
    for c in (origin, target):
        if c not in countries:
            raise ValueError('no existe el país «%s»' % c)
    st = scen.s
    path, notes = _events_doc(scen)
    shared = next(o for o in st.docs[path].getroot().iter('object') if o.get('type') == 'MESharedData')
    turn = max(0, int(turn))
    label = 'MOD_%sEmbargo%s_T%d' % (re.sub(r'\W', '', origin), re.sub(r'\W', '', target), turn)
    ev = ET.fromstring(EMBARGO_EVENT.format(label=label, org=origin, tgt=target, turn=turn, until=turn + 1))
    st.attach(ev, shared, path=path)
    notes.append('evento %s añadido (embargo de %s a %s en el turno %d)' % (label, origin, target, turn))
    return st.eid(ev), notes



def partisans_state(scen):
    sx = scen.all('Scenario', lambda f: f == 'scenario.xml')[0]
    return any(o.get('type') == 'SharedDataFileRef' and prop(o, 'fileSharedData') == 'sharedDataPartisans.xml' for o in objs(sx))


def set_partisans(scen, enable):
    """Activa/desactiva los Partisans: registro de sharedDataPartisans.xml en scenario.xml
    (si el escenario no tiene el archivo, se copia de otro que lo tenga)."""
    st = scen.s
    sx = scen.all('Scenario', lambda f: f == 'scenario.xml')[0]
    refs = [o for o in objs(sx) if o.get('type') == 'SharedDataFileRef']
    cur = [o for o in refs if prop(o, 'fileSharedData') == 'sharedDataPartisans.xml']
    if not enable:
        for o in cur:
            st.remove(o)
        return ['Partisans desactivados (el archivo se conserva)'] if cur else ['ya estaban desactivados']
    if cur:
        return ['ya estaban activados']
    notes = []
    dst = os.path.join(scen.dir, 'sharedDataPartisans.xml')
    if not os.path.exists(dst):
        src = next((os.path.join(SCEN_ROOT, x, 'sharedDataPartisans.xml') for x in os.listdir(SCEN_ROOT)
                    if os.path.exists(os.path.join(SCEN_ROOT, x, 'sharedDataPartisans.xml'))), None)
        if src is None:
            raise ValueError('ningún escenario tiene sharedDataPartisans.xml para copiarlo')
        shutil.copy2(src, dst)
        notes.append('copiado sharedDataPartisans.xml desde %s' % os.path.basename(os.path.dirname(src)))
    nid = max(int(prop(o, 'nFileRefID', '0')) for o in refs) + 1 if refs else 1
    ref = ET.fromstring('<object type="SharedDataFileRef" name="objSharedDataFileRefs"><property name="nFileRefID" value="%d"/>'
                        '<property name="bScenario" value="true"/><property name="strFileLoadName" value="Shared Data - Partisans"/>'
                        '<property name="fileSharedData" value="sharedDataPartisans.xml"/></object>' % nid)
    st.attach(ref, sx, index=list(sx).index(refs[-1]) + 1 if refs else len(sx))
    notes.append('Partisans activados (registrado en scenario.xml)')
    return notes



# ---------------------------------------------------------------------------------------- regiones nuevas del mapa
def region_sid(name):
    import unicodedata
    base = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return 'SID.Game.Region.Name.' + re.sub(r'[^A-Za-z0-9]', '', base)


def parse_vec(v):
    try:
        x, y = [float(a) for a in (v or '').strip('[] ').split(',')[:2]]
        return x, y
    except ValueError:
        return None


def pack_of(scen):
    sx = scen.all('Scenario', lambda f: f == 'scenario.xml')
    disp = next((o for o in sx[0].iter('object') if o.get('type') == 'ScenarioDisplaySettings'), None) if sx else None
    return prop(disp, 'strMapName') if disp is not None else None


def scenarios_using(pack):
    """Escenarios (de SCEN_ROOT) cuyo scenario.xml usa el regionpack 'pack'."""
    out = []
    for s in scenarios():
        f = os.path.join(SCEN_ROOT, s, 'scenario.xml')
        m = re.search(r'name="strMapName" value="([^"]*)"', open(f, encoding='utf-8', errors='replace').read())
        if m and m.group(1) == pack:
            out.append(s)
    return out


def _scen_doc(scen, rel, template):
    """Abre (o crea con 'template') un XML auxiliar del escenario y lo incluye en sus rutas."""
    path = os.path.abspath(os.path.join(scen.dir, rel))
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(template)
    scen.s.open(path)
    if path not in scen.paths:
        scen.paths.append(path)
    return path


def _add_child(st, par, el, path):
    par.append(el)
    st.parent[el] = par
    st.doc_of[el] = path
    st.dirty.add(path)
    st.restructured.add(path)


def set_region_string(scen, sid, text):
    """Texto del SID en <escenario>/game/stringTable.xml (lo crea y lo registra en game/namespace.xml si falta)."""
    st = scen.s
    notes = []
    created = not os.path.exists(os.path.join(scen.dir, 'game', 'stringTable.xml'))
    path = _scen_doc(scen, os.path.join('game', 'stringTable.xml'),
                     '<?xml version="1.0" encoding="UTF-8"?>\r\n<stringTable existence="optional">\r\n</stringTable>\r\n')
    root = st.docs[path].getroot()
    cur = next((s for s in root.iter('string') if s.get('id') == sid), None)
    if cur is None:
        _add_child(st, root, ET.Element('string', {'id': sid, 'value': text}), path)
        notes.append('texto %s = %s' % (sid, text))
    elif cur.get('value') != text:
        cur.set('value', text)
        st.dirty.add(path)
    if created:
        notes.append('creado game/stringTable.xml')
    if os.path.exists(os.path.join(scen.dir, 'game', 'namespace.xml')):
        npath = _scen_doc(scen, os.path.join('game', 'namespace.xml'), '')
        nroot = st.docs[npath].getroot()
        if not any(e.get('filename') == 'stringTable.xml' for e in nroot.iter('stringTable')):
            _add_child(st, nroot, ET.Element('stringTable', {'filename': 'stringTable.xml'}), npath)
            notes.append('registrado stringTable.xml en game/namespace.xml')
    scen.strings[sid] = text
    return notes


def _region_refs(scen, name):
    """Referencias por nombre a una region: propiedades strRegions y objetos NameRegionRefPair."""
    props, pairs = [], []
    for p in scen.paths:
        for el in scen.s.docs[p].getroot().iter():
            if el.tag == 'property' and el.get('name') == 'strRegions' and el.get('value') == name:
                props.append(el)
            elif el.tag == 'object' and el.get('type') == 'NameRegionRefPair' and prop(el, 'strRegion') == name:
                pairs.append(el)
    return props, pairs


def add_new_region(scen, name, mother=None, fraction=None, owner=None, terrain=None, goes_to_new=None, population=None, text=None):
    """Registra una region nueva del mapa en el escenario (no guarda).
    mother:  region de la que sale (subdivision): mismo dueno, controlador, terreno, cultura, infraestructura;
             se lleva 'fraction' de la poblacion; ciudades, productores y ejercitos con goes_to_new(x, y) pasan a ella;
             se anade junto a la madre en las listas de regiones (HistoricCountry, strRegions).
    owner:   (sin madre: dibujada en el mar) pais al que se asigna; terreno 'terrain', 'population' habitantes.
    text:    nombre visible (SID en game/stringTable.xml); por defecto 'name'."""
    st = scen.s
    land = {prop(r, 'strName'): r for r in scen.regions(sea=False)}
    if name in land:
        return ['%s: ya existía en el escenario' % name]
    notes = []
    sid = region_sid(name)
    if mother is not None:
        src = land.get(mother)
        if src is None:
            raise ValueError('%s: no existe la región madre %s en el escenario' % (name, mother))
        new = copy.deepcopy(src)
        for c in objs(new):
            new.remove(c)
        par = st.parent[src]
        st.attach(new, par, index=list(par).index(src) + 1)
        st.set_prop(new, 'strName', name)
        st.set_prop(new, 'sidName', sid)
        if terrain:
            st.set_prop(new, 'strTerrain', terrain)
        pop = prop(src, 'nPopulation')
        if pop and pop.isdigit():
            moved = int(round(int(pop) * float(fraction or 0)))
            st.set_prop(new, 'nPopulation', str(moved))
            st.set_prop(src, 'nPopulation', str(int(pop) - moved))
            if fraction:
                notes.append('población: %s hab. pasan a %s (%d %% del área); %s queda con %s' % (
                    moved, name, round(100 * float(fraction or 0)), mother, int(pop) - moved))
        if goes_to_new is not None:
            for c in objs(src):
                if c.get('type') in ('City', 'Producer'):
                    xy = parse_vec(prop(c, 'vecPosition'))
                    if xy and goes_to_new(*xy):
                        st.detach(c)
                        st.attach(c, new)
                        notes.append('%s %s pasa a %s' % ('ciudad' if c.get('type') == 'City' else 'productor', prop(c, 'strName'), name))
            for t in ('Army', 'AirForce'):
                for g in scen.all(t):
                    xy = parse_vec(prop(g, 'vecPosition'))
                    if prop(g, 'strRegion') == mother and xy and goes_to_new(*xy):
                        st.set_prop(g, 'strRegion', name)
                        notes.append('%s %s (%s) pasa a %s' % (t, prop(g, 'strName'), prop(g, 'strOwner'), name))
        props, pairs = _region_refs(scen, mother)
        for p in props:
            par = st.parent[p]
            el = ET.Element('property', {'name': 'strRegions', 'value': name})
            par.insert(list(par).index(p) + 1, el)
            st.parent[el] = par
            st.doc_of[el] = st.doc_of[par]
            st.touch(par, structural=True)
        for p in pairs:
            dup = copy.deepcopy(p)
            for q in dup:
                if q.tag == 'property' and q.get('name') == 'strRegion':
                    q.set('value', name)
            par = st.parent[p]
            st.attach(dup, par, index=list(par).index(p) + 1)
        if props or pairs:
            notes.append('añadida junto a %s en %d listas de regiones (países históricos, IA)' % (mother, len(props) + len(pairs)))
        owner_name = prop(src, 'strOwner')
    else:
        countries = scen.countries()
        if owner not in countries:
            raise ValueError('%s: el país %s no existe en el escenario' % (name, owner))
        c = countries[owner]
        own = [r for r in objs(c) if r.get('type') == 'Region']
        cult = Counter(prop(r, 'strCulture') for r in own if prop(r, 'strCulture')).most_common(1)
        if not cult:
            cult = Counter(prop(r, 'strCulture') for r in land.values() if prop(r, 'strCulture')).most_common(1)
        if not cult:        # escenario desde cero: la primera cultura de la nación
            cs = next((k for k in objs(c) if k.get('type') == 'CultureSet'), None)
            first = next((prop(k, 'strCultureName') for k in objs(cs) if prop(k, 'strCultureName')), None) if cs is not None else None
            cult = [(first, 1)] if first else []
        new = ET.Element('object', {'type': 'Region', 'name': 'objGOs'})
        for k, v in (('strName', name), ('strOwner', owner), ('strController', owner), ('sidName', sid),
                     ('strTerrain', terrain or 'Plains'), ('nPopulation', str(int(population or 0))),
                     ('nTransInfrastructure', '1'), ('nFortification', '0'), ('strCulture', cult[0][0] if cult else '')):
            if v != '':
                ET.SubElement(new, 'property', {'name': k, 'value': v})
        kids = list(c)
        regs = [k for k, x in enumerate(kids) if x.tag == 'object' and x.get('type') == 'Region']
        if regs:
            idx = regs[-1] + 1
        else:
            idx = next((k for k, x in enumerate(kids) if x.tag == 'object'), len(kids))
        st.attach(new, c, path=st.doc_of[c], index=idx)
        notes.append('%s: %s, %s hab.' % (name, terrain or 'Plains', int(population or 0)))
        hc = [h for h in scen.all('HistoricCountry') if prop(h, 'strCountry') == owner]
        for h in hc:
            pair = ET.Element('object', {'type': 'NameRegionRefPair', 'name': 'objNameRegionRefPairs'})
            ET.SubElement(pair, 'property', {'name': 'strRegion', 'value': name})
            st.attach(pair, h)
        if hc:
            notes.append('añadida al país histórico %s' % owner)
        owner_name = owner
    notes.insert(0, '%s registrada en country%s.xml' % (name, owner_name))
    notes += set_region_string(scen, sid, text or name)
    scen._opts = None
    return notes


def remove_new_region(scen, name, mother=None, fractions=None):
    """Deshace add_new_region: ciudades, productores, ejercitos y poblacion vuelven a la madre; se quitan las referencias."""
    st = scen.s
    land = {prop(r, 'strName'): r for r in scen.regions(sea=False)}
    el = land.get(name)
    if el is None:
        sea = next((r for r in scen.regions(sea=True) if prop(r, 'strName') == name), None)
        if sea is None:
            return ['%s: no estaba en el escenario' % name]
        # region de mar: las flotas vuelven a la madre y se quita de waterWorld.xml
        for g in scen.all('Fleet'):
            if prop(g, 'strRegion') == name and mother:
                st.set_prop(g, 'strRegion', mother)
        st.remove(sea)
        return ['%s quitada de waterWorld.xml' % name]
    dst = land.get(mother) if mother else None
    if dst is not None:
        for c in objs(el):
            if c.get('type') in ('City', 'Producer'):
                st.detach(c)
                st.attach(c, dst)
                for k in ('strOwner', 'strController'):   # vuelve con el dueño de la región madre
                    st.set_prop(c, k, prop(dst, k))
        a, b = prop(el, 'nPopulation'), prop(dst, 'nPopulation')
        if fractions:
            # cada region de origen recupera lo que dio: si se llevo la fraccion f, ahora tiene R = P(1-f) -> dio R*f/(1-f)
            for m, f in fractions.items():
                r = land.get(m)
                cur = prop(r, 'nPopulation') if r is not None else None
                if cur and cur.isdigit() and 0 <= float(f) < 1:
                    st.set_prop(r, 'nPopulation', str(int(round(int(cur) / (1 - float(f))))))
        elif a and b and a.isdigit() and b.isdigit():
            st.set_prop(dst, 'nPopulation', str(int(a) + int(b)))
        for t in ('Army', 'AirForce', 'Fleet'):     # tambien las flotas atracadas en sus puertos
            for g in scen.all(t):
                if prop(g, 'strRegion') == name:
                    st.set_prop(g, 'strRegion', mother)
    props, pairs = _region_refs(scen, name)
    for p in props:
        par = st.parent[p]
        par.remove(p)
        st.touch(par, structural=True)
    for p in pairs:
        st.remove(p)
    st.remove(el)
    scen._opts = None
    return ['%s quitada del escenario%s' % (name, ' (todo vuelve a %s)' % mother if dst is not None else '')]



# «si el protegido es atacado por el agresor, el protector actúa»: un evento por turno con probabilidad (guerra o embargo)
PROTECT_EVENT = """<object type="ScriptedEventDef" name="objScriptedEventDefs">
	<property name="strTypeLabel" value="{label}"/>
	<property name="pathPlayer" value="{{Object:Single:Player}}scratch.objPlayer"/>
	<object type="PlayerGenNames" name="objPlayerGen"><property name="strName" value="{prot}"/></object>
	<object type="TriggerEvalRandomChance" name="objTriggerEval">
		<property name="nPercentChance" value="{pct}"/>
		<object type="AccessorRuleSet" name="objConditions">
			<property name="strDebugLabel" value="{agg} is at war with {pro}"/>
			<property name="pathPlayer" value="{{Object:Single:Player}}scratch.objPlayer"/>
			<object type="AccessorGetCountry" name="objAccessors"><property name="pathOutput" value="{{Object:Single:Country}}scratch.objCountryProtector"/><property name="strCountry" value="{prot}"/></object>
			<object type="AccessorGetCountry" name="objAccessors"><property name="pathOutput" value="{{Object:Single:Country}}scratch.objCountryProtected"/><property name="strCountry" value="{pro}"/></object>
			<object type="AccessorGetCountry" name="objAccessors"><property name="pathOutput" value="{{Object:Single:Country}}scratch.objCountryAggressor"/><property name="strCountry" value="{agg}"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="exists({{Object:Single:Country}}scratch.objCountryProtector)"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="exists({{Object:Single:Country}}scratch.objCountryProtected)"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="exists({{Object:Single:Country}}scratch.objCountryAggressor)"/></object>
			<object type="AccessorIsAtWar" name="objAccessors"><property name="pathOutput" value="{{bool:Single}}scratch.bProtectedAtWar"/><property name="nCountryID" inheritFrom="{{Object:Single:Country}}scratch.objCountryProtected.nCountryID"/><property name="nEnemyCountryID" inheritFrom="{{Object:Single:Country}}scratch.objCountryAggressor.nCountryID"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="{{bool:Single}}scratch.bProtectedAtWar"/></object>
{extra}		</object>
	</object>
	<object type="CustomEffectDefActions" name="objEffects">
		<property name="strLabel" value="{effect_label}"/>
{action}
	</object>
	<object type="ArgumentList" name="objArgLists"><property name="strName" value="Display Data"/></object>
</object>"""

PROTECT_NOT_AT_WAR = """			<object type="AccessorIsAtWar" name="objAccessors"><property name="pathOutput" value="{{bool:Single}}scratch.bProtectorAtWar"/><property name="nCountryID" inheritFrom="{{Object:Single:Country}}scratch.objCountryProtector.nCountryID"/><property name="nEnemyCountryID" inheritFrom="{{Object:Single:Country}}scratch.objCountryAggressor.nCountryID"/></object>
			<object type="RuleDefExpression" name="objRules"><property name="expRession" value="!{{bool:Single}}scratch.bProtectorAtWar"/></object>
"""


def create_protection_event(scen, protector, protected, aggressor, action='war', pct=30):
    """Evento: si 'aggressor' está en guerra con 'protected' y 'protector' aún no, cada turno hay un 'pct' % de que
    'protector' le declare la guerra (action 'war') o le embargue (action 'embargo')."""
    countries = scen.countries()
    for c in (protector, protected, aggressor):
        if c not in countries:
            raise ValueError('no existe el país «%s»' % c)
    if len({protector, protected, aggressor}) < 3:
        raise ValueError('protector, protegido y agresor deben ser tres países distintos')
    if action not in ('war', 'embargo'):
        raise ValueError('la reacción es guerra o embargo')
    pct = max(1, min(100, int(pct)))
    if action == 'war':
        act = ('\t\t<object type="ActProposeDeclareWar" name="objActions"><property name="strFromCountry" value="%s"/>'
               '<property name="strToCountry" value="%s"/></object>' % (protector, aggressor))
        extra = PROTECT_NOT_AT_WAR
        eff = '%s declares war on %s (protecting %s)' % (protector, aggressor, protected)
    else:
        act = ('\t\t<object type="ActSetTradeRelations" name="objActions"><property name="strCountry" value="%s"/>'
               '<property name="eTradeRelations" value="TRADE_RELATIONS_EMBARGOED"/></object>' % aggressor)
        extra = ''
        eff = '%s embargoes %s (protecting %s)' % (protector, aggressor, protected)
    st = scen.s
    path, notes = _events_doc(scen)
    shared = next(o for o in st.docs[path].getroot().iter('object') if o.get('type') == 'MESharedData')
    w = lambda x: re.sub(r'\W', '', x)
    label = 'MOD_%sProtects%sFrom%s_%s' % (w(protector), w(protected), w(aggressor), action)
    ev = ET.fromstring(PROTECT_EVENT.format(label=label, prot=protector, pro=protected, agg=aggressor, pct=pct, extra=extra,
                                            effect_label=eff, action=act))
    st.attach(ev, shared, path=path)
    notes.append('evento %s añadido: si %s ataca a %s, %s %s (%d %% por turno)' % (
        label, aggressor, protected, protector, 'le declara la guerra' if action == 'war' else 'le embarga', pct))
    return st.eid(ev), notes
