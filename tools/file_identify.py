"""Identifica cualquier archivo del juego y dice como abrirlo.

identify(ruta) -> {kind, title, description, editor, facts, scenario?}
  editor: 'escenario' (pestanas de ed.exe), 'arbol' (XML generico), 'regiones' (editor del mapa),
          'imagen' (vista previa), 'info' (solo informacion)
"""
import os
import re
import struct
import xml.etree.ElementTree as ET
from collections import Counter

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Making History The Calm and The Storm"

XML_KINDS = [
    # (patron del nombre, tipo raiz o None, titulo, descripcion)
    (r'^country(.+)\.xml$', 'MECountry', 'País: {0}', 'Gobierno, capital, regiones con sus ciudades y productores, ejércitos, fuerzas aéreas y flotas.'),
    (r'^player(.+)\.xml$', 'MEPlayerData', 'Jugador e IA: {0}', 'Comportamiento de la IA, diplomacia inicial e investigación ya completada.'),
    (r'^gamestate\.xml$', None, 'Estado inicial de la partida', 'Jugadores (colores, jugables), alianzas y guerras.'),
    (r'^game\.xml$', None, 'Índice de la partida', 'Lista de archivos que se cargan y mercado mundial (flujos de comercio y ayuda).'),
    (r'^treaties\.xml$', None, 'Tratados', 'Accesos militares entre países.'),
    (r'^waterWorld\.xml$', None, 'Regiones de mar', 'Datos de escenario de las zonas marítimas.'),
    (r'^scenario\.xml$', None, 'Definición del escenario', 'Fechas, duración y archivos de datos compartidos que usa.'),
    (r'^scenarioInfo\.xml$', None, 'Ficha del escenario', 'Nombre, descripción y países jugables que muestra el menú.'),
    (r'^sharedDataEvents\.xml$', None, 'Eventos con guion', 'Eventos programados (fecha, condiciones y efectos).'),
    (r'^sharedDataUnitTemplates\.xml$', None, 'Plantillas de unidades', 'Estadísticas de cada tipo de unidad y categorías.'),
    (r'^sharedDataFactories\.xml$', None, 'Producción', 'Lo que pueden fabricar las ciudades y parámetros económicos.'),
    (r'^sharedDataResearch\.xml$', None, 'Investigación', 'Proyectos de investigación, requisitos y efectos.'),
    (r'^sharedData.*\.xml$', 'MESharedData', 'Datos compartidos', 'Reglas y tablas compartidas por el escenario.'),
    (r'^stringTable.*\.xml$', None, 'Tabla de textos', 'Traducciones: identificador SID → texto visible.'),
    (r'^map\.xml$', None, 'Configuración del mapa', 'Archivos del mapa (regions.bin, borders.brd, regions.nts), límites y renombres de regiones.'),
    (r'^properties\.xml$', None, 'Propiedades del mapa', 'Colores y efectos visuales del mapa.'),
    (r'^MKDTable.*\.xml$', None, 'Tabla de sprites', 'Qué modelo o icono usa cada país o unidad.'),
    (r'^contentPack\.xml$', None, 'Paquete de contenido', 'DLLs y tablas que carga la campaña.'),
    (r'^encyclopedia\.xml$', None, 'Enciclopedia', 'Capítulos y entradas de la enciclopedia del juego.'),
    (r'^UI.*\.xml$', None, 'Interfaz', 'Definición de una pantalla o panel de la interfaz.'),
    (r'^.*Defs\.xml$', None, 'Definiciones de objetos', 'Tipos de objeto del motor y sus propiedades (objectDefs).'),
]


def facts_xml(root):
    types = Counter(o.get('type') for o in root.iter('object'))
    strings = sum(1 for _ in root.iter('string'))
    defs = sum(1 for _ in root.iter('objectDef'))
    f = []
    if types:
        f.append('Objetos: ' + ', '.join('%s ×%d' % kv for kv in types.most_common(8)))
    if strings:
        f.append('%d textos' % strings)
    if defs:
        f.append('%d definiciones de tipo' % defs)
    return f, types


def scenario_of(path):
    parts = os.path.normpath(path).split(os.sep)
    if 'scenarios' in parts:
        i = parts.index('scenarios')
        if i + 1 < len(parts) and os.path.exists(os.sep.join(parts[:i + 2] + ['gamestate.xml'])):
            return parts[i + 1]
    return None


def identify(path):
    path = os.path.abspath(path)
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    size = os.path.getsize(path)
    out = {'path': path, 'name': name, 'size': size, 'kind': 'desconocido', 'title': name, 'description': '',
           'editor': 'info', 'facts': [], 'scenario': scenario_of(path)}
    if ext == '.xml':
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as e:
            out.update(kind='xml', title='XML con errores', description=str(e))
            return out
        facts, types = facts_xml(root)
        out['facts'] = facts
        first = next(iter(root.iter('object')), None)
        rtype = first.get('type') if first is not None else root.tag
        out.update(kind='xml', title='XML (%s)' % rtype, description='Archivo de objetos del motor.', editor='arbol')
        for pat, need, title, desc in XML_KINDS:
            m = re.match(pat, name, re.I)
            if m and (need is None or rtype == need):
                out.update(title=title.format(*(m.groups() or [''])), description=desc)
                break
        if out['scenario'] and os.path.dirname(path).endswith(out['scenario']):
            out['editor'] = 'escenario'
            out['facts'].insert(0, 'Escenario: %s' % out['scenario'])
        return out
    if name in ('regions.bin', 'borders.brd', 'regions.nts'):
        n = struct.unpack('<I', open(path, 'rb').read(4))[0]
        desc = {'regions.bin': '%d regiones: nombre, centro, vecinos y contorno.' % n,
                'borders.brd': '%d fronteras (polilíneas) y la tabla región → bordes.' % n,
                'regions.nts': '%d piezas de malla (triángulos) que dibujan las regiones.' % n}[name]
        out.update(kind='mapa', title='Binario del mapa: %s' % name, description=desc, editor='regiones')
        return out
    if ext == '.tga':
        m = re.match(r'OperationalTerrain-(\d+)-(\d+)(?:-(\d+))?\.tga$', name)
        if m:
            c, r, lv = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
            lon0, lat0 = -180 + 15 * c, 105 - 15 * r
            out.update(kind='textura', editor='imagen', title='Textura del terreno %02d-%02d%s' % (c, r, ' (mipmap %d)' % lv if lv else ''),
                       description='DXT5 en bruto de %d×%d px. Cubre longitud %d…%d y latitud %d…%d. Las fronteras están pintadas aquí.'
                                   % (1024 >> lv, 1024 >> lv, lon0, lon0 + 15, lat0 - 15, lat0),
                       tile=[c, r, lv])
            return out
        out.update(kind='imagen', editor='imagen', title='Imagen TGA', description='Imagen (icono, bandera, interfaz…).')
        return out
    if ext in ('.bmp', '.png', '.jpg', '.gif', '.cur'):
        out.update(kind='imagen', editor='imagen', title='Imagen %s' % ext[1:].upper())
        return out
    if ext in ('.nif', '.kf'):
        head = open(path, 'rb').read(64).split(b'\n')[0].decode('latin1', 'replace')
        out.update(kind='modelo', title='Modelo Gamebryo' if ext == '.nif' else 'Animación Gamebryo',
                   description='Se abre con NifSkope (nifskope.com).', facts=[head])
        return out
    if ext == '.py':
        out.update(kind='script', title='Script de Python 2.2', description='Código que el juego ejecuta (acciones y comportamientos).')
        return out
    if ext in ('.dll', '.exe', '.pyd'):
        out.update(kind='binario', title='Programa / librería de Windows', description='Código nativo (32 bits, VC++ 2003). Se analiza con REA/Ghidra.')
        return out
    if ext == '.wav':
        out.update(kind='audio', title='Sonido WAV')
        return out
    if ext in ('.db',):
        out.update(kind='datos', title='Base de datos de miniaturas de Windows (Thumbs.db)', description='No la usa el juego.')
        return out
    return out


def list_dir(rel):
    base = os.path.abspath(os.path.join(GAME, rel))
    if not base.startswith(os.path.abspath(GAME)):
        raise ValueError('fuera de la carpeta del juego')
    entries = []
    for e in sorted(os.scandir(base), key=lambda e: (not e.is_dir(), e.name.lower())):
        entries.append({'name': e.name, 'dir': e.is_dir(), 'size': None if e.is_dir() else e.stat().st_size,
                        'rel': os.path.relpath(e.path, GAME)})
    return {'rel': os.path.relpath(base, GAME), 'entries': entries}


def resolve(rel):
    p = os.path.abspath(os.path.join(GAME, rel))
    if not p.startswith(os.path.abspath(GAME)) or not os.path.isfile(p):
        raise ValueError('archivo no válido')
    return p
