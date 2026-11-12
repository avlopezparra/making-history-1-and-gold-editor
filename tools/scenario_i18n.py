"""Texts the server generates for events, AI, terrains and cultures (scenario_events.py) in the editor language.

The code produces Spanish sentences with data (countries, regions, dates…). If the editor is in English (idioma.json,
written by the page's language selector), L() turns them into English before sending them:
- SHAPES: whole sentence with {} holes (the data are translated in turn: «el país que recibe el evento», lists «a; b»);
- PHRASES: fixed chunks substituted inside composite texts (war plans, diplomatic pressure…).
A new sentence in scenario_events.py needs its entry here.
"""
import json
import os
import re
import time

import gamepaths

SHAPES = [
    # ---- nombres y fragmentos
    ('el país que recibe el evento', 'the country receiving the event'), ('un país liberable', 'a liberable country'),
    ('el país liberable', 'the liberable country'), ('todos los países', 'all countries'), ('nada', 'nothing'),
    ('Evento', 'Event'), ('Decisión (ventana)', 'Decision (window)'), ('Disparador de decisión', 'Decision trigger'), ('Punto de decisión', 'Decision point'),
    # ---- condiciones
    ('{} no existe (rendido, sin territorio)', '{} does not exist (surrendered, no territory)'),
    ('{} existe', '{} exists'), ('{} no existe', '{} does not exist'),
    ('{} está rendido (sin territorio)', '{} has surrendered (no territory)'), ('{} no está rendido (sin territorio)', '{} has not surrendered'),
    ('{} no está en ninguna guerra', '{} is not in any war'), ('{} está en alguna guerra', '{} is in some war'),
    ('{} no está en guerra con {}', '{} is not at war with {}'), ('{} está en guerra con {}', '{} is at war with {}'),
    ('{} no está aliado con {}', '{} is not allied with {}'), ('{} está aliado con {}', '{} is allied with {}'),
    ('{} no tiene acceso militar en {}', '{} has no military access in {}'), ('{} tiene acceso militar en {}', '{} has military access in {}'),
    ('{} no posee {}', '{} does not own {}'), ('{} posee {}', '{} owns {}'),
    ('{} no controla {}', '{} does not control {}'), ('{} controla {}', '{} controls {}'),
    ('{} no tiene gobierno {}', '{} does not have a {} government'), ('{} tiene gobierno {}', '{} has a {} government'),
    ('se dispara el evento «{}»', 'the event «{}» fires'), ('se ha respondido la decisión «{}»', 'the decision «{}» has been answered'),
    ('la elección es «{}»', 'the choice is «{}»'), ('quien responde no es {}', 'the one answering is not {}'), ('quien responde es {}', 'the one answering is {}'),
    ('el tratado no es {}', 'the treaty is not {}'), ('el tratado es {}', 'the treaty is {}'),
    ('desde el turno {}', 'from turn {}'), ('después del turno {}', 'after turn {}'), ('antes del turno {}', 'before turn {}'),
    ('hasta el turno {}', 'until turn {}'), ('en el turno {}', 'on turn {}'),
    ('desde el {}', 'from {}'), ('después del {}', 'after {}'), ('antes del {}', 'before {}'), ('hasta el {}', 'until {}'), ('el día {}', 'on {}'),
    ('azar: {} % de probabilidad', 'random: {} % chance'), ('número al azar {} {}', 'random number {} {}'),
    ('puesto de {} en la clasificación {} {}', 'rank of {} {} {}'), ('número de guerras de {} {} {}', 'number of wars of {} {} {}'),
    ('{} tiene países que puede liberar', '{} has countries it can liberate'), ('países liberables {} {}', 'liberable countries {} {}'),
    ('cantidad de {} {} {}', 'number of {} {} {}'), ('NO: {}', 'NOT: {}'),
    ('{} no es {}', '{} is not {}'), ('{} es {}', '{} is {}'),
    # ---- efectos
    ('{} declara la guerra a {}', '{} declares war on {}'), ('{} pone embargo a {}', '{} embargoes {}'),
    ('{} pone sanciones a {}', '{} sanctions {}'), ('{} pone trato favorable a {}', '{} gives favoured trade to {}'),
    ('{} pone comercio normal a {}', '{} restores normal trade with {}'),
    ('{} cambia su ideología a {}', '{} changes its ideology to {}'),
    ('{} recibe {} × {} en {} («{}»)', '{} receives {} × {} in {} («{}»)'),
    ('{} pierde {} de {}', '{} loses {} {}'), ('{} recibe {} de {}', '{} receives {} {}'),
    ('{} concede la independencia a {} (aparece o se libera {})', '{} grants independence to {} ({} appears or is liberated)'),
    ('{} se rinde ante {} (anexión)', '{} surrenders to {} (annexation)'),
    ('la región {} pasa a ser de {}', 'region {} becomes owned by {}'), ('la región {} pasa a estar controlada por {}', 'region {} becomes controlled by {}'),
    ('relación de {} con {} + {}', 'relations of {} with {} + {}'), ('relación de {} con {} − {}', 'relations of {} with {} − {}'),
    ('{} completa la investigación {}', '{} completes the research {}'),
    ('{} suma {} puntos a la investigación {}', '{} adds {} points to the research {}'),
    ('{} resta {} puntos a la investigación {}', '{} removes {} points from the research {}'),
    ('{} traslada su capital a {} ({})', '{} moves its capital to {} ({})'), ('{} pasa a posición {}', '{} switches to position {}'),
    ('agresividad de {} = {}', 'aggressiveness of {} = {}'), ('{} propone un pacto defensivo a {}', '{} proposes a defensive pact to {}'),
    ('{} da acceso militar a {}', '{} grants military access to {}'),
    ('acepta el tratado propuesto', 'accepts the proposed treaty'), ('rechaza el tratado propuesto', 'rejects the proposed treaty'),
    ('se une a la guerra de su alianza', 'joins its alliance\'s war'), ('no se une a la guerra de su alianza', 'does not join its alliance\'s war'),
    ('la población de {} cambia en {}', 'the population of {} changes by {}'), ('{} pasa a estar controlada por {}', '{} becomes controlled by {}'),
    ('la región {} pasa a cultura {} (experimental)', 'region {} switches to culture {} (experimental)'),
    ('para cada uno de «{}»: {}', 'for each of «{}»: {}'), ('propone o firma la paz ({})', 'proposes or signs peace ({})'),
    ('propone un tratado a {}', 'proposes a treaty to {}'), ('propone un tratado', 'proposes a treaty'),
    # ---- disparadores, cadena, ventanas
    ('cada turno en que se cumplan las condiciones, con {} % de probabilidad', 'every turn the conditions are met, with {} % chance'),
    ('cada turno en que se cumplan las condiciones', 'every turn the conditions are met'),
    ('se comprueba hasta el turno {}', 'checked until turn {}'),
    ('cada turno hasta que se responda la decisión «{}»', 'every turn until the decision «{}» is answered'),
    ('hasta que se responda «{}» (se reinicia cada turno)', 'until «{}» is answered (resets every turn)'), ('cuando ocurre: {}', 'when it happens: {}'),
    ('se repite hasta que se responda', 'repeats until answered'), ('lo escucha', 'listens to it'), ('abre la ventana', 'opens the window'),
    ('se activa con', 'is fired by'), ('la abre', 'opens it'), ('evento de origen', 'source event'),
    ('«{}»: {} (la IA elige esta, {} %)', '«{}»: {} (the AI picks this one, {} %)'), ('ventana: {}', 'window: {}'), ('«{}»: {}', '«{}»: {}'),
    ('{} · del escenario', '{} · scenario-specific'),
    # ---- clases de evento
    ('Crisis por perder la patria', 'Crisis from losing the homeland'),
    ('el país pierde regiones de su patria: ventana de crisis (rendirse, seguir luchando…)', 'the country loses homeland regions: crisis window (surrender, keep fighting…)'),
    ('Recuperar la capital original', 'Restore the original capital'),
    ('el país reconquista su capital original: decide si la vuelve a hacer capital', 'the country retakes its original capital: decides whether to make it the capital again'),
    ('Ciudad atacada con bomba atómica', 'City hit by an atomic bomb'),
    ('respuesta de la IA cuando bombardean una de sus ciudades con una bomba atómica', 'AI response when one of its cities is hit by an atomic bomb'),
    ('Estado aliado de la misma ideología', 'Allied state of the same ideology'),
    ('al conquistar la capital histórica de un país liberable, crearlo como aliado con la misma ideología', 'when conquering the historic capital of a liberable country, create it as an ally with the same ideology'),
    ('Unirse a un bando', 'Join a side'), ('un país decide si entra en el Eje, los Aliados o las Potencias Centrales', 'a country decides whether to join the Axis, the Allies or the Central Powers'),
    ('País al borde de la derrota', 'Country near defeat'), ('el país está casi derrotado: rendición, paz separada o seguir', 'the country is almost defeated: surrender, separate peace or continue'),
    ('Liberación de un país', 'Liberation of a country'), ('un país liberado (o por liberar) vuelve a existir', 'a liberated (or to-be-liberated) country exists again'),
    ('Formar un país', 'Form a country'), ('un país que reúne ciertas regiones puede formar otro mayor', 'a country that gathers certain regions can form a bigger one'),
    ('Estado títere', 'Puppet state'), ('crear un estado títere en territorio conquistado', 'create a puppet state on conquered territory'),
    ('Golpe o revuelta', 'Coup or revolt'), ('cambio de gobierno o levantamiento interno', 'change of government or internal uprising'),
    ('Avance en investigación', 'Research breakthrough'), ('puntos extra de investigación', 'extra research points'),
    ('Retraso en investigación', 'Research setback'), ('se pierden puntos de investigación', 'research points are lost'),
    ('Ampliación de producción', 'Production expansion'), ('una mina, pozo o granja produce más', 'a mine, well or farm produces more'),
    ('Moral de los trabajadores', 'Worker morale'), ('sube o baja la producción de las fábricas', 'factory production goes up or down'),
    ('Respuesta a un tratado', 'Treaty response'), ('la IA responde a un tratado propuesto (alianza, paz, comercio, acceso…)', 'the AI answers a proposed treaty (alliance, peace, trade, access…)'),
    ('Unirse a la guerra de la alianza', "Join the alliance's war"), ('un miembro de una alianza decide si entra en la guerra de sus aliados', "an alliance member decides whether to join its allies' war"),
    ('Aviso de paso de tropas', 'Troop passage warning'), ('tropas extranjeras quieren cruzar su territorio', 'foreign troops want to cross its territory'),
    ('Levantamiento partisano', 'Partisan uprising'), ('aparecen partisanos en regiones ocupadas', 'partisans appear in occupied regions'),
    ('Tecnología por año', 'Technology by year'), ('al llegar la fecha todos completan la investigación de ese año', 'when the date arrives everyone completes that year\'s research'),
    ('Declaración de guerra', 'Declaration of war'), ('Embargo / comercio', 'Embargo / trade'), ('Cambio de ideología', 'Ideology change'),
    ('Crear o liberar un país', 'Create or liberate a country'), ('Anexión', 'Annexation'), ('Ayuda de recursos', 'Resource aid'),
    ('Cesión de regiones', 'Region transfer'), ('Unidades nuevas', 'New units'), ('Cambio de cultura', 'Culture change'),
    ('Relaciones diplomáticas', 'Diplomatic relations'), ('Investigación', 'Research'), ('Pacto defensivo', 'Defensive pact'), ('Otro', 'Other'),
    # ---- IA
    ('Si {} ataca a {}, {} ayuda a {} (dinero, armas y, si puede, entra en la guerra)', 'If {} attacks {}, {} helps {} (money, arms and, if it can, joins the war)'),
    ('{} quiere conquistar {}', '{} wants to conquer {}'), ('{} quiere liberar {}', '{} wants to liberate {}'),
    ('{} quiere mantener su independencia frente a {}', '{} wants to keep its independence from {}'),
    ('{} quiere ser militarmente más fuerte que {}', '{} wants to be militarily stronger than {}'), ('{} quiere debilitar a {}', '{} wants to weaken {}'),
    ('{} quiere conseguir las regiones de la lista «{}»', '{} wants the regions of list «{}»'),
    ('{} quiere proteger las regiones de la lista «{}»', '{} wants to protect the regions of list «{}»'),
    ('{} quiere conservar las regiones de la lista «{}»', '{} wants to keep the regions of list «{}»'),
    ('{} quiere liberar las regiones de la lista «{}»', '{} wants to liberate the regions of list «{}»'),
    ('{} quiere aliarse con {}', '{} wants to ally with {}'), ('{} quiere evitar la guerra con {}', '{} wants to avoid war with {}'),
    ('en el primer turno, la unidad {} recibe la orden {} ({})', 'on the first turn, unit {} gets the order {} ({})'),
    ('{} (desactivada)', '{} (disabled)'),
    ('Si {} es invadido en las regiones de «{}», {} reacciona contra el agresor: guerra {}/100, embargo {}/100', 'If {} is invaded in the regions of «{}», {} reacts against the aggressor: war {}/100, embargo {}/100'),
    ('Si {} es invadido, {} reacciona contra el agresor: guerra {}/100, embargo {}/100', 'If {} is invaded, {} reacts against the aggressor: war {}/100, embargo {}/100'),
    ('Si {} entra en guerra, {} reacciona contra el agresor: guerra {}/100, embargo {}/100', 'If {} goes to war, {} reacts against the aggressor: war {}/100, embargo {}/100'),
    ('IA de {}: {}', 'AI of {}: {}'), ('meta de {} cambiada: A = {}, B = {}', 'goal of {} changed: A = {}, B = {}'),
    ('meta quitada', 'goal removed'), ('operación de guerra quitada', 'war operation removed'), ('plan quitado', 'plan removed'), ('reacción quitada', 'reaction removed'),
    # ---- notas y errores
    ('creado sharedDataEvents.xml y registrado en scenario.xml', 'created sharedDataEvents.xml and registered it in scenario.xml'),
    ('evento «{}» añadido (con su ventana «{}»)', 'event «{}» added (with its window «{}»)'), ('quitado {} «{}»', 'removed {} «{}»'),
    ('{}: ahora desde el {}', '{}: now from {}'), ('{}: ahora en el turno {}', '{}: now on turn {}'),
    ('decisión «{}» añadida: un país {} que conquiste la capital histórica de un país liberable podrá crearlo como aliado {}',
     'decision «{}» added: a {} country that conquers the historic capital of a liberable country can create it as a {} ally'),
    ('terreno {} creado (copia de {}) en {}', 'terrain {} created (copy of {}) in {}'), ('terreno {} cambiado', 'terrain {} changed'),
    ('terreno {} quitado', 'terrain {} removed'), ('{} regiones pasan a {}', '{} regions move to {}'),
    ('cultura {} creada en {}', 'culture {} created in {}'), ('cultura {} quitada', 'culture {} removed'), ('{} naciones la tenían', '{} nations had it'),
    ('texto {} = {}', 'text {} = {}'), ('creado game/stringTable.xml', 'created game/stringTable.xml'),
    ('registrado stringTable.xml en game/namespace.xml', 'registered stringTable.xml in game/namespace.xml'),
    ('color de {} = {} guardado en {} (todo el juego)', 'colour of {} = {} saved in {} (whole game)'),
    ('Este juego no tiene el modo de mapa «Terreno» (en MH1 está comentado en UnifiedMapViews.xml): el color no se usa.',
     'This game has no «Terrain» map mode (in MH1 it is commented out in UnifiedMapViews.xml): the colour is not used.'),
    ('Color del modo de mapa «Terreno»: está en {} y vale para todo el juego, no solo para este escenario.',
     'Colour of the «Terrain» map mode: it is in {} and applies to the whole game, not only to this scenario.'),
    ('no existe el país «{}»', 'the country «{}» does not exist'), ('no existe la región «{}»', 'the region «{}» does not exist'),
    ('fecha no válida (MM/DD/AAAA)', 'invalid date (MM/DD/YYYY)'), ('elige la ideología', 'choose the ideology'),
    ('no existe la ideología «{}» en el escenario', 'the ideology «{}» does not exist in the scenario'),
    ('la decisión necesita al menos una elección', 'the decision needs at least one choice'), ('falta un país en el efecto «{}»', 'a country is missing in the effect «{}»'),
    ('efecto desconocido: {}', 'unknown effect: {}'), ('elige un país que exista', 'choose an existing country'),
    ('el país no puede reaccionar a sí mismo', 'a country cannot react to itself'), ('la sensibilidad va de 0 a 100', 'the sensitivity goes from 0 to 100'),
    ('ya existe la cultura {}', 'the culture {} already exists'), ('ya existe el terreno {}', 'the terrain {} already exists'),
    ('{} regiones usan {}: elige a qué terreno pasan', '{} regions use {}: choose which terrain they move to'),
    ('{} regiones tienen la cultura {}: elige a cuál pasan', '{} regions have the culture {}: choose which one they move to'),
    ('{} lo usa el juego por defecto: no se puede quitar', '{} is used by the game by default: it cannot be removed'),
    ('nombre interno: letras y números sin espacios (p. ej. Swamp)', 'internal name: letters and digits without spaces (e.g. Swamp)'),
    ('nombre interno: letras, números, espacios o guiones (p. ej. Patagonian)', 'internal name: letters, digits, spaces or hyphens (e.g. Patagonian)'),
    ('color no válido: #RRGGBBAA', 'invalid colour: #RRGGBBAA'), ('este juego no tiene el modo de mapa «Terreno»: el color no se usa', 'this game has no «Terrain» map mode: the colour is not used'),
    ('elige a quién ataca (países o una lista de regiones)', 'choose whom it attacks (countries or a region list)'),
    ('este evento no tiene una condición de fecha o de turno que cambiar', 'this event has no date or turn condition to change'),
    ('la ideología {} ya tiene su decisión de crear un estado aliado ({})', 'the ideology {} already has its decision to create an allied state ({})'),
    ('no se encuentra la decisión {} (ni en el escenario ni en ScenarioDefaults) para copiarla', 'the decision {} was not found (neither in the scenario nor in ScenarioDefaults) to copy it'),
    ('no hay datos de jugador (player{}.xml) para {}', 'there is no player data (player{}.xml) for {}'), ('la meta no tiene su bloque de países', 'the goal has no country block'),
    ('no se puede quitar un {} desde aquí', 'a {} cannot be removed from here'),
    ('ese objeto del evento ya no existe', 'that event object no longer exists'),
    ('no se encuentra la condición o acción que usa {}', 'cannot find the condition or action that uses {}'),
    ('{}: quitadas {} condiciones o acciones que usaban {}', '{}: removed {} conditions or actions that used {}'),
    ('esa condición ya no existe', 'that condition no longer exists'),
    ('quitada la condición «{}»', 'removed the condition «{}»'),
    ('Cambiar por {} (la absorbió)', 'Change to {} (absorbed this region)'),
    ('Cambiar por {} (salió de ella)', 'Change to {} (split off from this region)'),
    ('Cambiar por {}', 'Change to {}'),
    ('el escenario no tiene CultureTemplateSet (sharedDataCultureTemplates.xml)', 'the scenario has no CultureTemplateSet (sharedDataCultureTemplates.xml)'),
    ('el escenario no tiene tipos de terreno que copiar', 'the scenario has no terrain types to copy'),
    ('{} y {} ya tienen un acuerdo de acceso militar', '{} and {} already have a military access agreement'),
    ('{} pasa al puerto de {} ({}, mar {})', '{} moves into the port of {} ({}, sea {})'), ('sale del puerto', 'leaves port'),
    ('{} → {}, {} (región {} → {})', '{} → {}, {} (region {} → {})'), ('{}: orientación {}°', '{}: heading {}°'),
    ('solo se pueden mover ejércitos, fuerzas aéreas y flotas', 'only armies, air forces and fleets can be moved'),
    ('solo se pueden mover ciudades, recursos y unidades', 'only cities, resources and units can be moved'),
    ('solo las flotas entran en un puerto', 'only fleets can enter a port'), ('{} no es una ciudad con puerto de {}', '{} is not a port city of {}'),
    ('{} no tiene puerto en {}: una flota en tierra debe estar en una ciudad con puerto de su dueño',
     '{} has no port in {}: a fleet on land must be in a port city of its owner'),
    ('el punto no está en ninguna región de mar del escenario', 'the point is not in any sea region of the scenario'),
    ('{}: un ejército debe estar en una región de tierra', '{}: an army must be in a land region'),
    ('{}: una fuerza aérea debe estar en una región de tierra', '{}: an air force must be in a land region'),
    ('solo ciudades y unidades tienen orientación', 'only cities and units have a heading'),
    ('Si {}: {}', 'If {}: {}'), ('{}: {}', '{}: {}'),
    # ---- effects (first version of each in action_text) and event_add / move_unit warnings
    ('{} propone un pacto de defensa a {}', '{} proposes a defence pact to {}'), ('{} obtiene acceso militar de {}', '{} gets military access from {}'),
    ('cancela el pacto de defensa con {}', 'cancels the defence pact with {}'), ('{} cambia su postura internacional a {}', '{} changes its international stance to {}'),
    ('{} cambia su agresividad a {}', '{} changes its aggressiveness to {}'),
    ('la producción de {} sube {}', 'the production of {} goes up {}'), ('la producción de {} baja {}', 'the production of {} goes down {}'),
    ('{} gana {} IPU', '{} gains {} IPU'), ('{} pierde {} IPU', '{} loses {} IPU'),
    ('{} gana {} puntos en {}', '{} gains {} points in {}'), ('{} pierde {} puntos en {}', '{} loses {} points in {}'),
    ('{} (región {} → {})', '{} (region {} → {})'),
    ('ese efecto no hace nada', 'that effect does nothing'), ('efecto añadido: {}', 'effect added: {}'),
    ('elige al menos un país', 'choose at least one country'), ('elige el país', 'choose the country'),
    ('condición: existen {}', 'condition: {} exist'), ('condición: desde {}', 'condition: from {}'), ('el turno {}', 'turn {}'),
    ('la probabilidad debe ser menor que 100 %', 'the chance must be less than 100 %'),
    ('condición: {} % de probabilidad por turno', 'condition: {} % chance per turn'),
    ('condición: {} y {} no están en guerra', 'condition: {} and {} are not at war'),
    ('condición: {} está en guerra con la alianza de {}', 'condition: {} is at war with the alliance of {}'),
    ('condición desconocida: {}', 'unknown condition: {}'),
    ('elige la región (o el país del que sale una al azar)', 'choose the region (or the country a random one comes from)'),
    ('escribe el proyecto de investigación', 'type the research project'),
    ('elige la región y el texto', 'choose the region and the text'), ('elige la región y la ciudad', 'choose the region and the city'),
    ('elige la postura o la agresividad', 'choose the stance or the aggressiveness'), ('ese evento ya no existe', 'that event no longer exists'),
    ('pon una fecha MM/DD/AAAA o un turno', 'enter a date MM/DD/YYYY or a turn'),
    ('decisión «{}» añadida: un país {} que conquiste la capital histórica de un país liberable podrá crearlo como aliado {}',
     'decision «{}» added: a {} country that conquers the historic capital of a liberable country can create it as an ally {}'),
]
# fixed chunks inside composite sentences (war plans, diplomatic pressure, event lists)
PHRASES = [
    (' ataca las regiones de ', ' attacks the regions of '), (' ataca a ', ' attacks '), (' (regiones de ', ' (regions of '),
    (' cuando ', ' when '), (' esté en guerra con ', ' is at war with '), (', desde el ', ', from '), (' hasta el ', ' until '),
    (', después de la operación ', ', after the operation '), (' (mientras tanto no busca otras guerras)', ' (meanwhile it seeks no other wars)'),
    ('Cuando ', 'When '), (' presiona a ', ' presses '), (' para que se unan a su bando (', ' to join its side ('), (' tratados cada ', ' treaties every '),
    (' turnos', ' turns'), (' % de declararles la guerra si no', ' % of declaring war on them otherwise'),
    (' (desde el ', ' (from '), (' (turno ', ' (turn '), (' pone embargo a ', ' embargoes '), (' declara la guerra a ', ' declares war on '),
    (' está en guerra con ', ' is at war with '), (' (desactivada)', ' (disabled)'), ('el país que recibe el evento', 'the country receiving the event'),
    ('un país liberable', 'a liberable country'),     ('el país liberable', 'the liberable country'), (' o ', ' or '), (' y ', ' and '),
    ('Cambiar por otra región…', 'Change to another region…'), ('Quitar esa condición o acción', 'Remove that condition or action'),
    ('Quitar esa condición', 'Remove that condition'),
]


def _rx(shape):
    return re.compile('^' + re.escape(shape).replace(re.escape('{}'), '(.+?)') + '$', re.S)


# the most specific (more fixed text) first: «{} es {}» must not swallow «Si {} es invadido, …»
# (and those starting and ending with fixed text before those with a hole at one end: «{} propone … a {}» must not swallow ««…»: … (la IA elige esta, …)»)
_SHAPES = [(_rx(es), en) for es, en in sorted(SHAPES, key=lambda x: (x[0].startswith('{}') + x[0].endswith('{}'), -len(x[0].replace('{}', ''))))]
_LANG = [0.0, 'es']


def lang():
    """Editor language (idioma.json is written by the page's language selector); re-read if it changes."""
    f = os.path.join(gamepaths.ROOT, 'idioma.json')
    try:
        m = os.path.getmtime(f)
        if m != _LANG[0]:
            _LANG[0], _LANG[1] = m, json.load(open(f, encoding='utf-8')).get('lang', 'es')
    except (OSError, ValueError):
        pass
    return _LANG[1]


NOUNS = [('el país que recibe el evento', 'the country receiving the event'), ('un país liberable', 'a liberable country'),
         ('el país liberable', 'the liberable country')]
# sentences containing one of those names («… de un país liberable, …»): tried before replacing the names
_NOUN_SHAPES = [(_rx(es), en) for es, en in SHAPES if any(n in es for n, _x in NOUNS)]


def _en(s, depth=0):
    if not s or depth > 6:
        return s
    for rx, en in _NOUN_SHAPES:
        m = rx.match(s)
        if m:
            return en.format(*[_en(g, depth + 1) for g in m.groups()])
    for es, en in NOUNS:            # before the sentences: «el país que recibe el evento posee Il de France» is not «{} recibe {} de {}»
        s = s.replace(es, en)
    if '; ' in s and not s.startswith('«'):      # effect lists: each one separately
        return '; '.join(_en(x, depth + 1) for x in s.split('; '))
    m = re.match(r'^«(.*?)»: (.*?)( \(la IA elige esta, (\S+) %\))?$', s, re.S)      # «botón»: effects (and the one the AI picks)
    if m and '; ' in m.group(2):
        return '«%s»: %s%s' % (m.group(1), _en(m.group(2), depth + 1), ' (the AI picks this one, %s %%)' % m.group(4) if m.group(3) else '')
    for rx, en in _SHAPES:
        m = rx.match(s)
        if m:
            return en.format(*[_en(g, depth + 1) for g in m.groups()])
    if '; ' in s:
        return '; '.join(_en(x, depth + 1) for x in s.split('; '))
    for es, en in PHRASES:
        s = s.replace(es, en)
    return s


def L(x, force=None):
    """Translates the texts of a result (dict/list/str) into the editor language. The keys 'label', 'text' of the
    player texts (title, buttons), 'id' and similar are left alone."""
    if (force or lang()) != 'en':
        return x
    return _walk(x)


KEEP = {'label', 'id', 'file', 'type', 'name', 'country', 'a', 'b', 'targets', 'trig_a', 'trig_b', 'date', 'expires', 'region_list', 'sid',
        'units', 'nations', 'display', 'title', 'desc', 'ai', 'when', 'colors', 'dirty'}
KEEP_DEEP = {'title', 'desc', 'ai', 'when', 'colors', 'dirty', 'nations', 'units', 'targets', 'trig_a', 'trig_b'}   # player texts and data


def _walk(x, key=None):
    if key in KEEP_DEEP:
        return x
    if isinstance(x, str):
        return x if key in KEEP else _en(x)
    if isinstance(x, list):
        return [_walk(v, key) for v in x]
    if isinstance(x, dict):
        return {k: (v if k in KEEP and not isinstance(v, (dict, list)) else _walk(v, k)) for k, v in x.items()}
    return x


def L_msg(s):
    """Loose error or warning message: only known whole sentences (other modules have their own texts)."""
    if lang() != 'en' or not s:
        return s
    for rx, en in _SHAPES:
        m = rx.match(s)
        if m and len(rx.pattern.replace('(.+?)', '').replace('\\', '')) >= 14:      # nothing generic like «{} es {}»
            return en.format(*[_en(g) for g in m.groups()])
    return s
