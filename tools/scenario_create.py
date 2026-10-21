"""Creación de objetos nuevos en un escenario (como «Add» de ed.exe): naciones, flotas, alianzas, guerras, acuerdos de acceso militar y
copias de plantillas (unidades, producción, investigación). Ciudades, recursos y ejércitos están en scenario_layers.py.

Todas las funciones devuelven (id, notas) o una lista de notas, y lanzan ValueError con el motivo si algo no cuadra.
"""
import copy
import os
import re
import xml.etree.ElementTree as ET

import scenario_core as sc
import scenario_layers as L
from scenario_core import prop, objs

BAD_FILE = re.compile(r'[\\/:*?"<>|]')


def _slug(text):
    return re.sub(r'[^A-Za-z0-9]', '', text)


def _write_new(s, path, root):
    """Escribe un archivo XML nuevo del escenario (vacío de formato: se reindenta al guardar), lo abre y lo da por modificado."""
    st = s.s
    body = ET.tostring(root, encoding='unicode')
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\r\n' + body + '\r\n')
    st.open(path)
    if path not in s.paths:
        s.paths.append(path)
    st.dirty.add(path)
    st.restructured.add(path)
    s._opts = None


def _insert_after(st, el, after, parent):
    kids = list(parent)
    st.attach(el, parent, index=(kids.index(after) + 1) if after is not None and after in kids else None)


# ---------------------------------------------------------------------------------------- 1. nación nueva
def create_country(s, name, template=None, color=None, ctype='Minor', gov=None, flag=None, capital=None, regions=None, description=None,
                   new_capital=None):
    """País nuevo: country<Nombre>.xml + player<Nombre>.xml copiando una nación pequeña (sin regiones ni unidades) como plantilla,
    registrados en game.xml, y su Player en gamestate.xml. 'regions' (opcional) le pasa esas regiones; 'capital' es una ciudad suya
    (o, si no tiene regiones, la ciudad anhelada de una nación rendida liberable)."""
    st = s.s
    name = (name or '').strip()
    if not name or BAD_FILE.search(name):
        raise ValueError('el país necesita un nombre válido (sin \\ / : * ? " < > |)')
    countries = s.countries()
    import scenario_new
    why = scenario_new.name_taken(s, name)
    if why:
        raise ValueError(why)
    fc, fp = 'country%s.xml' % name, 'player%s.xml' % name
    from_template = bool(template)       # sin plantilla: nación nueva con los valores por defecto (como al crearla desde una región)
    if from_template and template not in countries:
        raise ValueError('no existe el país de plantilla %s' % template)
    if color and not re.fullmatch(r'#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?', color):
        raise ValueError('el color debe ser #RRGGBB')
    if ctype not in ('Minor', 'Major', 'Playable'):
        raise ValueError('tipo de nación desconocido: %s' % ctype)
    regions = [r for r in (regions or []) if r]
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    for r in regions:
        if r not in land:
            raise ValueError('no existe la región %s' % r)
    cities = {prop(c, 'strName'): c for c in s.all('City')}
    if capital and capital not in cities:
        raise ValueError('la ciudad «%s» no existe en el escenario' % capital)
    if new_capital:                 # capital nueva: se crea al final, en una de sus regiones (o en otra, si es una nación rendida)
        nc = (new_capital.get('name') or '').strip()
        if not nc:
            raise ValueError('la capital nueva necesita un nombre')
        if nc in cities:
            raise ValueError('ya existe una ciudad llamada %s' % nc)
        if (new_capital.get('region') or (regions[0] if regions else None)) not in land:
            raise ValueError('elige la región de la capital nueva')
    gt = {prop(c, 'strGovType') for c in countries.values() if prop(c, 'strGovType')} | {prop(g, 'strName') for g in s.all('GovTypeTemplate')}
    if gov and gov not in gt:
        raise ValueError('gobierno desconocido: %s (hay: %s)' % (gov, ', '.join(sorted(gt))))
    notes = []

    if not from_template:
        cult = [prop(land[r], 'strCulture') for r in regions if prop(land[r], 'strCulture')]
        notes += scenario_new.create_nation(s, {'name': name, 'color': (color or '')[:7] or None, 'gov': gov or None, 'flag': flag or None,
                                                 'playable': ctype == 'Playable', 'description': description or '',
                                                 'culture': cult[0] if cult else None}, need_capital=False)
        if ctype == 'Major':
            st.set_prop(s.countries()[name], 'eCountryType', 'COUNTRYTYPE_FEATURED')
    else:
        # ---- country<Nombre>.xml
        tc = countries[template]
        croot = ET.Element('objects', {'name': 'Object Load', 'version': '0.1'})
        c = ET.SubElement(croot, 'object', {'type': 'MECountry', 'name': ''})
        for p in tc:
            if p.tag == 'property':
                c.append(copy.deepcopy(p))
        for k in objs(tc):
            if k.get('type') == 'CultureSet':
                c.append(copy.deepcopy(k))
        pv = lambda k, v: _setp(c, k, v)
        pv('strName', name)
        pv('strHomelands', name)
        for k in ('Name', 'Possessive', 'Adjective', 'People', 'Alliance'):     # textos propios, no los de la plantilla
            key = 'sidAllianceName' if k == 'Alliance' else 'sid' + k
            if prop(c, key) is not None or k == 'Name':
                pv(key, 'SID.Game.Country.%s.%s' % (k, _slug(name)))
        pv('strFlagName', flag or name)
        if gov:
            pv('strGovType', gov)
        pv('bNonPlayable', 'false' if ctype == 'Playable' else 'true')
        pv('eCountryType', {'Minor': None, 'Major': 'COUNTRYTYPE_FEATURED', 'Playable': 'COUNTRYTYPE_PLAYABLE'}[ctype])
        pv('strCapital', None)
        pv('strOriginalCapital', None)
        pv('bSurrendered', 'true')
        cpath = os.path.abspath(s.path(fc))
        _write_new(s, cpath, croot)

        # ---- player<Nombre>.xml
        tp = next((p for p in s.all('MEPlayerData') if prop(p, 'strOwner') == template), None)
        proot = ET.Element('objects', {'name': 'Object Load', 'version': '0.1'})
        if tp is not None:
            pd = ET.SubElement(proot, 'object', {'type': 'MEPlayerData', 'name': ''})
            for p in tp:
                if p.tag == 'property':
                    pd.append(copy.deepcopy(p))
            for k in objs(tp):
                if k.get('type') == 'MEAIData':
                    pd.append(ET.Element('object', {'type': 'MEAIData', 'name': 'objAIData'}))
                elif k.get('type') == 'DipRelInitialValueList':
                    dl = ET.SubElement(pd, 'object', {'type': 'DipRelInitialValueList', 'name': 'objDipRelInitialValueList'})
                    ET.SubElement(dl, 'property', {'name': 'nDefault', 'value': prop(k, 'nDefault') or '500'})
            _setp(pd, 'strOwner', name)
            _setp(pd, 'strName', name)          # el de la plantilla haría dos PlayerData con su nombre
            _setp(pd, 'strFoggees', name)
        else:
            notes.append('AVISO: la plantilla %s no tiene datos de jugador: %s queda sin ellos' % (template, name))
        _write_new(s, os.path.abspath(s.path(fp)), proot)

        # ---- game.xml: los dos archivos se cargan (solo cuentan los que figuran aquí)
        last = [g for g in s.all('GO') if (g.get('fromFile') or '').startswith(('country', 'player'))]
        if not last:
            raise ValueError('game.xml no carga ningún country*/player*.xml: no sé dónde registrar el país')
        host = st.parent[last[-1]]
        ref_c = ET.Element('object', {'type': 'GO', 'name': 'objGOs', 'fromFile': fc})
        ref_p = ET.Element('object', {'type': 'GO', 'name': 'objGOs', 'fromFile': fp})
        _insert_after(st, ref_c, last[-1], host)
        _insert_after(st, ref_p, ref_c, host)
        for v in s.all('View'):         # vistas de países (p. ej. «minor»): entra donde estaba la plantilla
            al = [p for p in v if p.tag == 'property' and p.get('name') == 'strAliases']
            t = next((p for p in al if p.get('value') == template), None)
            if t is not None and not any(p.get('value') == name for p in al):
                e = ET.Element('property', {'name': 'strAliases', 'value': name})
                v.insert(list(v).index(t) + 1, e)
                st.parent[e], st.doc_of[e] = v, st.doc_of[v]
                st.touch(v, structural=True)
        # ---- gamestate.xml: el Player (color y si es jugable)
        players = [p for p in s.all('Player', lambda f: f == 'gamestate.xml') if prop(p, 'strName')]
        if players:
            tpl = next((p for p in players if prop(p, 'strName') == template), players[-1])
            np_ = copy.deepcopy(tpl)
            _setp(np_, 'strName', name)
            _setp(np_, 'bNonPlayable', 'false' if ctype == 'Playable' else 'true')
            _setp(np_, 'sidName', 'SID.Game.Country.Name.' + _slug(name))
            _setp(np_, 'sidShortDescription', 'SID.Game.Country.Description.%s.%s' % (_slug(s.name), _slug(name)))   # nunca la de la plantilla
            _setp(np_, 'strFlagName', flag or name)
            col = (color or _free_color(players)).upper()
            _setp(np_, 'colCountryColor', col + 'FF' if len(col) == 7 else col)
            _insert_after(st, np_, players[-1], st.parent[players[-1]])
        else:
            notes.append('AVISO: gamestate.xml no tiene jugadores: falta añadir el Player de %s' % name)
        s._opts = None
        notes.append('país %s creado (country%s.xml + player%s.xml, plantilla %s), registrado en game.xml y gamestate.xml' % (name, name, name, template))
        # ---- texto de la nación (nombre y descripción en el escenario)
        notes += sc.set_region_string(s, 'SID.Game.Country.Name.' + _slug(name), name)
        for k in ('Possessive', 'Adjective', 'People', 'Alliance'):
            notes += sc.set_region_string(s, 'SID.Game.Country.%s.%s' % (k, _slug(name)), name)
        # el texto tiene que existir aunque esté vacío: un sidShortDescription sin texto impide cargar la partida
        notes += sc.set_region_string(s, 'SID.Game.Country.Description.%s.%s' % (_slug(s.name), _slug(name)), (description or '').strip())
    # ---- territorio y capital
    new = s.countries()[name]
    if template is None and not from_template:
        template = '(nación nueva)'
    for r in regions:
        notes += s.update(st.eid(land[r]), {'strOwner': name, 'strController': name})
    if regions:
        cult = list(dict.fromkeys(prop(land[r], 'strCulture') for r in regions if prop(land[r], 'strCulture')))
        cset = next((k for k in objs(new) if k.get('type') == 'CultureSet'), None)
        if cult and cset is not None:       # culturas de las regiones recibidas (si no, la nación no las gobierna bien)
            for k in objs(cset):
                st.remove(k)
            for cu in cult:
                e = ET.Element('object', {'type': 'Culture', 'name': 'objCultures'})
                ET.SubElement(e, 'property', {'name': 'strCultureName', 'value': cu})
                st.attach(e, cset)
            notes.append('culturas: %s' % ', '.join(cult))
        notes += L.unsurrender(s, name, regions[0])
        if new_capital:
            capital = _new_capital(s, name, new_capital, regions[0], notes)
            cities = {prop(c, 'strName'): c for c in s.all('City')}
        if capital:
            if prop(st.parent.get(cities[capital]), 'strOwner') != name:
                raise ValueError('la capital %s no está en una región de %s' % (capital, name))
            st.set_prop(new, 'strCapital', capital)
            st.set_prop(new, 'strOriginalCapital', capital)
            notes.append('capital: %s' % capital)
    elif new_capital:              # sin regiones: la capital nueva va en otra región y la nación queda rendida, liberable allí
        notes += L.make_surrendered(s, name, _new_capital(s, name, new_capital, None, notes))
    elif capital:
        notes += L.make_surrendered(s, name, capital)
    else:
        notes.append('%s es una nación sin regiones ni capital: dale territorio (pestaña Land Regions) o conviértela en rendida con capital' % name)
    notes.append('Bandera e iconos: faltan en UI/art/2D/countries/%s (copia ahí los de otro país; el editor no escribe en la carpeta del juego)' % name)
    return st.eid(new), notes


def _new_capital(s, name, spec, default_region, notes):
    """Crea la ciudad capital nueva (en un punto al azar de su región si no se dan coordenadas) y devuelve su nombre."""
    region = spec.get('region') or default_region
    x, y = spec.get('x'), spec.get('y')
    if x in (None, '') or y in (None, ''):
        x, y = L.region_point(s, region)
    _, n = L.create_city(s, spec['name'].strip(), float(x), float(y), spec.get('ipus', 5), spec.get('population', 100000),
                         (spec.get('display') or spec['name']).strip(), spec.get('port') or None, region=region)
    notes += n
    return spec['name'].strip()


def _has_assets(s, name):
    return bool(L._owned(s, name)[0] or L._owned(s, name)[1])


def _setp(el, key, value):
    """Fija (o quita si value es None) una propiedad de un elemento todavía sin indexar."""
    for p in [p for p in el if p.tag == 'property' and p.get('name') == key]:
        el.remove(p)
    if value is None:
        return
    props = [i for i, c in enumerate(el) if c.tag == 'property']
    el.insert(props[-1] + 1 if props else 0, ET.Element('property', {'name': key, 'value': value}))


def _free_color(players):
    used = {(prop(p, 'colCountryColor') or '')[:7].upper() for p in players}
    for i in range(1, 400):
        h = (i * 47) % 360
        r, g, b = _hsv(h / 360.0, 0.55, 0.85)
        c = '#%02X%02X%02X' % (r, g, b)
        if c not in used:
            return c
    return '#808080'


def _hsv(h, sat, v):
    import colorsys
    return tuple(int(x * 255) for x in colorsys.hsv_to_rgb(h, sat, v))


# ---------------------------------------------------------------------------------------- 2. flota nueva
def create_fleet(s, owner, name, region, units, city=None):
    """Flota de 'owner' en una región de mar, o en puerto: región de tierra con una ciudad con puerto del mismo dueño (se pone strCity)."""
    st = s.s
    countries = s.countries()
    if owner not in countries:
        raise ValueError('no existe el país %s' % owner)
    name = (name or '').strip()
    if not name:
        raise ValueError('la flota necesita un nombre')
    if any(prop(f, 'strName') == name and prop(f, 'strOwner') == owner for f in s.all('Fleet')):
        raise ValueError('%s ya tiene una flota llamada %s' % (owner, name))
    seas = {prop(r, 'strName') for r in s.regions(sea=True)}
    land = {prop(r, 'strName'): r for r in s.regions(sea=False)}
    if region not in seas and region not in land:
        raise ValueError('no existe la región %s' % region)
    templates = {prop(t, 'strName'): (prop(t, 'eType') or '') for t in s.all('UnitTemplate')}
    units = [u for u in units or [] if int(u.get('n') or 0) > 0]
    if not units:
        raise ValueError('la flota necesita al menos una unidad')
    for u in units:
        if u['type'] not in templates:
            raise ValueError('tipo de unidad desconocido: %s' % u['type'])
        if templates[u['type']] != 'UNIT_TYPE_NAVY':
            raise ValueError('«%s» no es una unidad naval' % u['type'])
    port = None
    if region in land:
        if prop(land[region], 'strOwner') != owner:
            raise ValueError('una flota en puerto debe estar en una región de %s (%s es de %s)' % (owner, region, prop(land[region], 'strOwner')))
        ports = [c for c in objs(land[region]) if c.get('type') == 'City' and prop(c, 'strPortForRegion')]
        if city:
            ports = [c for c in ports if prop(c, 'strName') == city]
        if not ports:
            raise ValueError('%s no tiene ninguna ciudad con puerto%s' % (region, ' llamada ' + city if city else ''))
        port = prop(ports[0], 'strName')
    el = ET.Element('object', {'type': 'Fleet', 'name': 'objGOs'})
    for k, v in (('strName', name), ('strOwner', owner), ('strRegion', region), ('strCity', port)):
        if v:
            ET.SubElement(el, 'property', {'name': k, 'value': v})
    for u in units:
        o = ET.SubElement(el, 'object', {'type': 'UnitSummary', 'name': 'objUnits'})
        ET.SubElement(o, 'property', {'name': 'strName', 'value': u['type']})
        ET.SubElement(o, 'property', {'name': 'nNumber', 'value': str(int(u['n']))})
    country = countries[owner]
    kids = list(country)
    fl = [k for k, x in enumerate(kids) if x.tag == 'object' and x.get('type') == 'Fleet']
    anyu = [k for k, x in enumerate(kids) if x.tag == 'object' and x.get('type') in ('Army', 'AirForce', 'Fleet')]
    st.attach(el, country, index=(fl[-1] + 1) if fl else ((anyu[-1] + 1) if anyu else None))
    return st.eid(el), ['flota %s de %s creada en %s%s con %s' % (name, owner, region, ' (puerto de %s)' % port if port else '',
                                                                   ', '.join('%d %s' % (int(u['n']), u['type']) for u in units))]


def create_airforce(s, owner, name, region, units):
    """Fuerza aérea de 'owner' en una región de tierra o de mar. Solo unidades aéreas (UNIT_TYPE_AIR_FORCE)."""
    st = s.s
    countries = s.countries()
    if owner not in countries:
        raise ValueError('no existe el país %s' % owner)
    name = (name or '').strip()
    if not name:
        raise ValueError('la fuerza aérea necesita un nombre')
    if any(prop(a, 'strName') == name and prop(a, 'strOwner') == owner for a in s.all('AirForce')):
        raise ValueError('%s ya tiene una fuerza aérea llamada %s' % (owner, name))
    regions = {prop(r, 'strName') for r in s.regions()}
    if region not in regions:
        raise ValueError('no existe la región %s' % region)
    templates = {prop(t, 'strName'): (prop(t, 'eType') or '') for t in s.all('UnitTemplate')}
    units = [u for u in units or [] if int(u.get('n') or 0) > 0]
    if not units:
        raise ValueError('la fuerza aérea necesita al menos una unidad')
    for u in units:
        if u['type'] not in templates:
            raise ValueError('tipo de unidad desconocido: %s' % u['type'])
        if templates[u['type']] != 'UNIT_TYPE_AIR_FORCE':
            raise ValueError('«%s» no es una unidad aérea' % u['type'])
    el = ET.Element('object', {'type': 'AirForce', 'name': 'objGOs'})
    for k, v in (('strName', name), ('strOwner', owner), ('strRegion', region)):
        ET.SubElement(el, 'property', {'name': k, 'value': v})
    for u in units:
        o = ET.SubElement(el, 'object', {'type': 'UnitSummary', 'name': 'objUnits'})
        ET.SubElement(o, 'property', {'name': 'strName', 'value': u['type']})
        ET.SubElement(o, 'property', {'name': 'nNumber', 'value': str(int(u['n']))})
    country = countries[owner]
    kids = list(country)
    air = [k for k, x in enumerate(kids) if x.tag == 'object' and x.get('type') == 'AirForce']
    anyu = [k for k, x in enumerate(kids) if x.tag == 'object' and x.get('type') in ('Army', 'AirForce', 'Fleet')]
    st.attach(el, country, index=(air[-1] + 1) if air else ((anyu[-1] + 1) if anyu else None))
    return st.eid(el), ['fuerza aérea %s de %s creada en %s con %s' % (name, owner, region, ', '.join('%d %s' % (int(u['n']), u['type']) for u in units))]


# ---------------------------------------------------------------------------------------- ideología nueva
def create_govtype(s, name, display=None, color=None, icon=None, base=None):
    """Ideología (tipo de gobierno) nueva: copia de la plantilla 'base' (todas sus propiedades y reglas) con otro nombre,
    color e icono. El nombre visible va al stringTable del escenario (SID.Game.GovTypeTemplate.Name.<nombre>)."""
    import copy
    st = s.s
    name = re.sub(r'[^A-Za-z0-9_]', '', (name or '').strip())
    if not name:
        raise ValueError('la ideología necesita un nombre interno (letras y números)')
    govs = s.all('GovTypeTemplate')
    if any(prop(g, 'strName') == name for g in govs):
        raise ValueError('ya existe la ideología %s' % name)
    src = next((g for g in govs if prop(g, 'strName') == base), None) or (govs[0] if govs else None)
    if src is None:
        raise ValueError('el escenario no define ideologías (GovTypeTemplate) que copiar')
    el = copy.deepcopy(src)
    sid = 'SID.Game.GovTypeTemplate.Name.' + name
    if color and not re.match(r'^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$', color):
        raise ValueError('color no válido: %s (usa #RRGGBB)' % color)
    for k, v in (('strName', name), ('sidDisplayName', sid), ('strIconName', icon or prop(src, 'strIconName') or name),
                 ('colColor', ((color + 'FF') if color and len(color) == 7 else color) or prop(src, 'colColor'))):
        p = next((x for x in el.findall('property') if x.get('name') == k), None)
        if p is None:
            p = ET.SubElement(el, 'property', {'name': k})
        p.set('value', v)
    parent = st.parent[src]
    st.attach(el, parent, index=list(parent).index(src) + 1 + sum(1 for g in govs if st.parent[g] is parent and list(parent).index(g) > list(parent).index(src)))
    s._opts = None              # el desplegable de Gobierno ya la incluye
    notes = ['ideología %s creada (copia de %s)' % (name, prop(src, 'strName'))]
    notes += sc.set_region_string(s, sid, (display or name).strip())
    if not icon:
        notes.append('usa el icono de %s; para uno propio pon su nombre en strIconName' % prop(src, 'strIconName'))
    return st.eid(el), notes


# ---------------------------------------------------------------------------------------- 3. alianza nueva
def create_alliance(s, name, leader, members):
    name = (name or '').strip()
    if not name:
        raise ValueError('la alianza necesita un nombre')
    if any(name.lower() in (prop(a, 'strDisplayName', '').lower(), prop(a, 'strINITAllianceName', '').lower()) for a in s.all('Alliance')):
        raise ValueError('ya existe una alianza llamada %s' % name)
    countries = s.countries()
    members = [m for m in dict.fromkeys(members or []) if m != leader]
    if leader not in countries:
        raise ValueError('el líder %s no existe' % leader)
    for m in members:
        if m not in countries:
            raise ValueError('no existe el país %s' % m)
    r = L.alliance_add(s, [leader] + members, None, name)
    return r['id'], r['notes'] or ['alianza %s creada' % name]


# ---------------------------------------------------------------------------------------- 4. guerra (con alianzas opcionales)
def create_war(s, attackers, defenders, name=None, off_alliance=None, def_alliance=None):
    """Una guerra inicial por cada pareja atacante–defensor; las alianzas (opcionales) se anotan en cada una."""
    countries = s.countries()
    attackers = list(dict.fromkeys(attackers or []))
    defenders = list(dict.fromkeys(defenders or []))
    if not attackers or not defenders:
        raise ValueError('hacen falta al menos un atacante y un defensor')
    for c in attackers + defenders:
        if c not in countries:
            raise ValueError('no existe el país %s' % c)
    if set(attackers) & set(defenders):
        raise ValueError('un país no puede estar en los dos bandos: %s' % ', '.join(sorted(set(attackers) & set(defenders))))
    ids = {prop(a, 'strINITAllianceName') for a in s.all('Alliance')}
    for a in (off_alliance, def_alliance):
        if a and a not in ids:
            raise ValueError('no existe la alianza «%s» (hay: %s)' % (a, ', '.join(sorted(i for i in ids if i))))
    notes = []
    for a in attackers:
        notes += L.create_wars(s, a, defenders, name)
    if off_alliance or def_alliance:
        keys = {(a, d) for a in attackers for d in defenders}
        for w in s.all('War'):
            if (prop(w, 'strINITAttackerCountryName'), prop(w, 'strINITDefenderCountryName')) in keys:
                s.s.set_prop(w, 'strINITOffenseAllianceName', off_alliance or prop(w, 'strINITOffenseAllianceName') or '')
                s.s.set_prop(w, 'strINITDefenseAllianceName', def_alliance or prop(w, 'strINITDefenseAllianceName') or '')
        notes.append('alianzas de la guerra: ataca «%s», defiende «%s»' % (off_alliance or '—', def_alliance or '—'))
    return notes


# ---------------------------------------------------------------------------------------- 6. acceso militar
def create_access(s, a, b, land=True, air=True, sea=True, date=None):
    """Acuerdo de acceso militar a–b (TreatyAgreement ratificado con sus dos MilAccessTerm) en treaties.xml."""
    st = s.s
    countries = s.countries()
    for c in (a, b):
        if c not in countries:
            raise ValueError('no existe el país %s' % c)
    if a == b:
        raise ValueError('elige dos países distintos')
    if not (land or air or sea):
        raise ValueError('marca al menos tierra, aire o mar')
    for t in s.all('TreatyAgreement') + s.all('Treaty', lambda f: f == 'treaties.xml'):
        if {prop(t, 'strFromCountry'), prop(t, 'strToCountry')} == {a, b} and any(o.get('type') == 'MilAccessTerm' for o in objs(t)):
            raise ValueError('%s y %s ya tienen un acuerdo de acceso militar' % (a, b))
    lst = next(iter(s.all('TreatyList')), None)
    if lst is None:
        raise ValueError('el escenario no tiene treaties.xml con una TreatyList')
    if date is None:
        sx = s.all('Scenario', lambda f: f == 'scenario.xml')
        g = lambda k, d: prop(sx[0], k, d) if sx else d
        date = '%02d/%02d/%s' % (int(g('nStartMonth', '1') or 1), int(g('nStartDay', '1') or 1), g('nStartYear', '1936'))
    if not re.fullmatch(r'\d{2}/\d{2}/\d{4}', date):
        raise ValueError('fecha no válida (MM/DD/AAAA)')
    # mismo formato que los acuerdos que ya tiene el escenario: «Treaty» corto (TMW, mods) o «TreatyAgreement» con nombre y fechas
    short = bool(s.all('Treaty', lambda f: f == 'treaties.xml')) and not s.all('TreatyAgreement')
    t = ET.Element('object', {'type': 'Treaty' if short else 'TreatyAgreement', 'name': 'objGOs'})
    props = (('strToCountry', b), ('strFromCountry', a), ('eTreatyState', 'TREATY_RATIFIED')) if short else \
        (('strName', '%s-%s Military Access Agreement' % (a, b)), ('strToCountry', b), ('strFromCountry', a),
         ('eTreatyState', 'TREATY_RATIFIED'), ('strDateProposed', date), ('strDateRatified', date))
    for k, v in props:
        ET.SubElement(t, 'property', {'name': k, 'value': v})
    for to_term in ('true', 'false'):
        m = ET.SubElement(t, 'object', {'type': 'MilAccessTerm', 'name': 'objGOs'})
        for k, v in (('bToTerm', to_term), ('strFromCountry', a), ('strToCountry', b), ('bLand', str(bool(land)).lower()),
                     ('bAir', str(bool(air)).lower()), ('bSea', str(bool(sea)).lower())):
            ET.SubElement(m, 'property', {'name': k, 'value': v})
    st.attach(t, lst)
    dom = ', '.join(n for n, f in (('tierra', land), ('aire', air), ('mar', sea)) if f)
    return st.eid(t), ['acceso militar %s ↔ %s (%s) desde %s' % (a, b, dom, date)]


# ---------------------------------------------------------------------------------------- 9. copias de plantillas
def _find_named(s, kind, name):
    if kind == 'units':
        return [e for e in s.all('UnitTemplate') if prop(e, 'strName') == name]
    pick = (lambda e: True)
    if kind == 'outputs':
        return [e for e in s.all_prefix('FactoryOutput') if prop(e, 'strName') == name]
    return [e for e in s.all_prefix('ResearchProj') if prop(e, 'strName') == name and s.s.parent[e].get('type') == 'ResearchProjectSet']


def _clone_after(s, src, new_name, sid_prefix, display):
    """Copia 'src' justo detrás, con strName nuevo y, si tiene sidDisplayName, un SID propio con el texto 'display'."""
    st = s.s
    new = copy.deepcopy(src)
    for p in new:
        if p.tag == 'property' and p.get('name') == 'strName':
            p.set('value', new_name)
    notes = []
    for p in new:
        if p.tag == 'property' and p.get('name') == 'sidDisplayName':
            sid = '%s%s' % (sid_prefix, _slug(new_name))
            p.set('value', sid)
            notes += sc.set_region_string(s, sid, display or new_name)
    par = st.parent[src]
    st.attach(new, par, index=list(par).index(src) + 1)
    return new, notes


def copy_template(s, kind, source, new_name, display=None, bundle=True):
    """kind: 'units' (UnitTemplate), 'outputs' (FactoryOutput*), 'research' (ResearchProj*). Copia 'source' con otro nombre.
    Con bundle, una unidad se copia junto a su producción (FactoryOutputUnit), su proyecto de investigación y sus sprites."""
    st = s.s
    new_name = (new_name or '').strip()
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', new_name):
        raise ValueError('el nombre debe ser un identificador (letras, números y _, sin espacios): «%s»' % new_name)
    if kind not in ('units', 'outputs', 'research'):
        raise ValueError('tipo desconocido: %s' % kind)
    src = _find_named(s, kind, source)
    if not src:
        raise ValueError('no existe «%s»' % source)
    if _find_named(s, kind, new_name):
        raise ValueError('ya existe «%s»' % new_name)
    src = src[0]
    notes = []
    if kind == 'units':
        new, n = _clone_after(s, src, new_name, 'SID.Game.UnitTemplate.Name.', display)
        notes += n + ['unidad %s copiada de %s' % (new_name, source)]
        if bundle:
            for out in [o for o in s.all_prefix('FactoryOutput') if o.get('type') == 'FactoryOutputUnit' and prop(o, 'strUnitType') == source]:
                if _find_named(s, 'outputs', new_name):
                    break
                o2, n = _clone_after(s, out, new_name, 'SID.Game.FactoryOutput.Name.', display)
                st.set_prop(o2, 'strUnitType', new_name)
                notes += n + ['producción %s (construye %s)' % (new_name, new_name)]
                oname = prop(out, 'strName')
                for rp in [r for r in _find_named_research_for(s, oname)]:
                    if _find_named(s, 'research', new_name):
                        break
                    r2, n = _clone_after(s, rp, new_name, 'SID.Game.ResearchProject.Name.', display)
                    for a in r2.iter('object'):
                        if a.get('type') == 'ResearchFactoryOutputAvailableData' and prop(a, 'strFactoryOutputName') == oname:
                            st.set_prop(a, 'strFactoryOutputName', new_name)
                    notes += n + ['investigación %s (desbloquea la producción %s)' % (new_name, new_name)]
            cnt = 0
            for p in list(s.paths):
                for e in list(st.docs[p].getroot().iter('property')):
                    if e.get('name') == 'strTemplateNames' and e.get('value') == source:
                        host = st.parent[e]
                        ne = ET.Element('property', {'name': 'strTemplateNames', 'value': new_name})
                        host.insert(list(host).index(e) + 1, ne)
                        st.parent[ne], st.doc_of[ne] = host, st.doc_of[host]
                        st.touch(host, structural=True)
                        cnt += 1
            if cnt:
                notes.append('sprites: %s usa los de %s (%d sitios)' % (new_name, source, cnt))
    elif kind == 'outputs':
        pre = 'SID.Game.FactoryOutput.Name.'
        new, n = _clone_after(s, src, new_name, pre, display)
        notes += n + ['producción %s copiada de %s' % (new_name, source)]
        if src.get('type') == 'FactoryOutputUnit':
            notes.append('AVISO: sigue construyendo la unidad «%s»: cambia strUnitType por tu unidad nueva' % prop(src, 'strUnitType'))
    else:
        new, n = _clone_after(s, src, new_name, 'SID.Game.ResearchProject.Name.', display)
        notes += n + ['investigación %s copiada de %s' % (new_name, source)]
        notes.append('AVISO: desbloquea lo mismo que %s: edita su producción (strFactoryOutputName) si es otra' % source)
    s._opts = None
    return st.eid(new), notes


def _find_named_research_for(s, output_name):
    out = []
    for r in s.all_prefix('ResearchProj'):
        if s.s.parent[r].get('type') != 'ResearchProjectSet':
            continue
        if any(a.get('type') == 'ResearchFactoryOutputAvailableData' and prop(a, 'strFactoryOutputName') == output_name for a in r.iter('object')):
            out.append(r)
    return out
