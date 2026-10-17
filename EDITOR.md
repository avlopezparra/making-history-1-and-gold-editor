# Editor de regiones de Making History

Edita las regiones del mapa del mundo (formas, fronteras, centros) en el navegador, y guarda en los
binarios del juego (`regions.bin`, `borders.brd`, `regions.nts`) y en las texturas del terreno,
respetando las reglas del formato.

## Abrir
Doble clic en **`Editor de regiones.bat`**. Se abre `http://localhost:8765`.
La primera vez crea el proyecto `editor_proyecto/` copiando el mapa actual del juego.
Necesita Python con `shapely` y `pillow` (`python -m pip install --user shapely pillow`).

Al arrancar, el servidor calcula los contornos de las 852 regiones en segundo plano (unos 20 s).

## Modos
- **Ver / propiedad** (por defecto): el mapa coloreado por país (elige solo el primer escenario que usa el regionpack), sin nodos.
  Clic en una región: panel con **Propietario / Controlador** y «Aplicar». **Pintar propiedad**: elige un país y haz clic en regiones.
  **Guardar escenario** escribe esos cambios en los XML del escenario (con copia de seguridad). No cambia la forma de nada.
- **Editar forma**: hay que activarlo (pide confirmación); muestra los grupos Edición, Área e Historial de abajo.
- **Imagen de fondo** (grupo Fondo): exporta el terreno de una zona (o todo el mundo) a PNG/JPG al detalle elegido, e importa
  una imagen para una zona (o los límites de un GeoJSON, p. ej. un mundo nuevo): se escala a la resolución del juego, conserva
  el canal alfa y se recomprime cada tile con sus mipmaps en el proyecto. Llega al juego con «Instalar».

## Herramientas (modo Editar forma)
| Grupo | Herramienta | Qué hace |
|---|---|---|
| Edición | **Modificar** | Arrastra los nodos de cualquier región (con «Todos los vértices», activado por defecto, no hace falta seleccionar). Con Topología, el nodo compartido se mueve en las dos regiones: una gana y la otra pierde, sin huecos. Arrastrar desde un borde crea un nodo. **Alt+clic o clic derecho** borra un nodo. |
| | **Insertar** | Clic junto a un lado: añade un nodo. |
| | **Borrar** | Clic en un nodo: lo quita. |
| | **Centro** | Arrastra el punto amarillo (centro de la región en `regions.bin`). |
| Área | **Dibujar** | Clics para un polígono; doble clic, Intro o clic en el primer punto para terminar. El área pasa a la región seleccionada. |
| | **Recortar** | Polígono sobre la región seleccionada; al terminar pregunta qué hacer con esa parte: **unirla a una región vecina** de tierra o de mar, o **dejarla como hueco**. |
| | **Crear región** (Dibujar/Cortar) | Para **crear una región nueva**. Como Pax Historia, sin seleccionar: clic en un borde y mueve el cursor, la línea sigue el borde hasta el nodo más cercano; clic lo ancla; clics dentro añaden nodos; Enter o clic en el primer punto termina. «Recortar» quita el área a las regiones de tierra que toca (la madre es la que aporta más área); sin recortar solo toma mar y huecos. Al terminar, una ventana pide: **terrestre o marítima**, **nombre**, **tipo de región** (Plains, Hills, Mountains, Forest, Jungle, Desert, Tundra) y **propietario / controlador** (por defecto los de la región recortada). Al «Guardar» se crea en el regionpack (proyecto) y se registra en los escenarios que lo usan: tierra en el country*.xml del dueño, mar en waterWorld.xml; las **ciudades, recursos, ejércitos y aviación** (o flotas, si es de mar) que quedan dentro pasan a la región nueva. La ventana también trae una tabla de **población**: por cada región de origen, el % de su área que se recorta y, por defecto, ese mismo % de sus habitantes (editable en % o en número); la región nueva suma lo de todas y a cada origen se le resta lo suyo (en los demás escenarios se aplica el mismo %). «Volver» devuelve a cada región exactamente lo que dio. Si queda dentro una unidad de otro país, una ventana deja elegir: pasarla al país de la región, **trasladarla a la región más cercana de su país** o dejarla. Barra flotante con ↶/↷ (Ctrl+Z / Retroceso y Ctrl+Y / Ctrl+Shift+Z) para quitar o reponer puntos, Terminar y Cancelar (Esc). |
| | **Eliminar región…** | Botón en el panel de la región (modo Editar forma). Su área pasa a una región vecina de tierra, al mar vecino o queda vacía; al guardar desaparece del regionpack (se renumeran las regiones), **se quita su creación del changelog** y se anota el borrado. En los escenarios, sus ciudades, recursos, población y unidades pasan a la región que la absorbe (si no hay, las unidades van a la región más cercana de su país). «Volver» la recupera con su población exacta. |
| | **Rellenar** | Clic dentro de un hueco o lago: pasa a la región seleccionada (si el punto ya está en una región, avisa). |
| | Ajuste | Al dibujar, un clic cerca de un nodo se pega a él; dos clics sobre la misma frontera la siguen nodo a nodo. |
| Historial | **Deshacer / Rehacer** | Ediciones sin guardar (Ctrl+Z / Ctrl+Y). |
| | **Topología** | Activada (por defecto): un nodo compartido se mueve en todas sus regiones, sin huecos ni solapes. Desactivada: solo cambia una región; lo que suelta queda como hueco. |
| Ver | Escenario / Colorear | Propietario, terreno y población de cada región según el escenario; colorear por región o por país. |
| Archivo | **Guardar** | Aplica los cambios al proyecto (no al juego). |
| | Descartar | Tira lo no guardado. |
| | **Volver / Rehacer** | Volver restaura el estado anterior al último guardado (una instantánea por guardado); **Rehacer** recupera lo deshecho (y vuelve a registrar sus regiones nuevas en los escenarios). Un guardado nuevo vacía lo que se podía rehacer. |
| | **Copia** | Copia de seguridad del regionpack instalado con otro nombre (geometría, texturas, map.xml, changelog). Puedes marcar qué escenarios pasan a usar la copia (se cambia `strMapName` y `fileMapProperties` de su scenario.xml, con respaldo) y copiar también el proyecto del editor para seguir editándola. |
| | **Instalar** | Copia el proyecto al juego. La primera vez que toca un archivo guarda el original en `backup/mapa_original/`. |

Panel de la región: **Avanzado** (desplegable) muestra su geometría en GeoJSON, editable; «Aplicar», **Exportar GeoJSON** e
**Importar GeoJSON…** (Polygon/MultiPolygon, Feature o FeatureCollection). Cambiar la geometría solo funciona en «Editar forma».

Opciones del panel: *Rellenar huecos al dibujar/pintar*, *Solo tierra* (al dar área a una región de tierra no
quita mar), *Repintar fronteras en la textura*, *Todos los vértices* (ver y arrastrar nodos de todas las regiones
sin seleccionar). Nodos cian = uniones de tres o más regiones.

## Protecciones al guardar
- Antes de escribir nada comprueba que ninguna región vecina queda con la malla rota y que la región nueva tiene (casi) el área
  dibujada; si no, **no guarda** y explica el motivo (no queda nada a medias, ni instantánea).
- Los trozos diminutos que salen al rozar el borde de una región vecina se ignoran (eran los que rompían la malla de Bolivia).
- Si el nombre ya existe en el regionpack, el error indica qué hacer. Una región que está en el mapa pero no en el escenario
  (p. ej. si falló su registro) muestra en su panel **Registrar en el escenario…**: elige de qué región sale, dueño, tipo y % de
  población, y la registra moviendo ciudades, recursos y unidades que quedan dentro.
- El mapa de referencia limpio (`backup/mapa_original`) es idéntico al `World` de Making History Gold.

## Qué hace al guardar
1. Compara cada región editada con su forma anterior: lo que gana se le quita a quien lo tenía (o sale de un
   hueco); lo que pierde lo gana otra región o queda como hueco.
2. Recorta y retriangula solo los triángulos afectados (`tools/transfer.py`), unifica vértices (float32,
   sin uniones en T) y regenera los bordes como cadenas de aristas compartidas, con vecindades nuevas o eliminadas.
3. Repinta en `OperationalTerrain` las fronteras tierra–tierra y mar–mar que cambiaron.
4. Comprueba que no hay pasos de longitud cero.

## Límites
- Las costas se pueden mover, pero la textura no cambia tierra por agua: solo se repintan las líneas de frontera.
- Las regiones que cruzan el antimeridiano (Aleutianas) no se pueden editar.
- El mapa es común a todos los escenarios.

## Archivos
- `tools/editor_server.py`: servidor local. `tools/editor_core.py`: proyecto, guardado, historial, instalación.
- `tools/editor/index.html`: interfaz (Leaflet 1.9.4).
- `tools/outlines.py`: contornos exactos de las regiones desde la malla.
- Proyecto: `editor_proyecto/` (`xml/`, `tiles/`, `history/`).

## Regionpacks
- Un **regionpack** es la carpeta `Modern Europe\system\DisplayLibraries\Maps\<nombre>` (geometría `xml\` + texturas `art\`).
  Cada escenario elige el suyo en `scenario.xml` (`strMapName` y `fileMapProperties`). Hoy: `World` y `WorldPublicPanamaCanalAndSuez`.
- El editor de mapa trabaja sobre **un proyecto por regionpack** (`editor_proyecto` para World, `editor_proyecto_<nombre>` para los demás);
  se cambia con el selector «Regionpack».
- La primera vez que se pulsa **Instalar** pregunta: guardar en el regionpack actual, o **crear uno nuevo** copiando el actual
  con otro nombre, y qué escenarios pasan a usarlo (se reescribe su `scenario.xml`, con copia del original).
- Cada guardado se anota en `changelog.json` (traspasos entre regiones por nombre, vecindades nuevas, centros movidos…);
  al instalar se copia dentro del regionpack, para poder aplicar esos cambios a otros escenarios.
- `map.xml` del regionpack tiene `RegionRename` (los escenarios usan esos nombres: p. ej. Maghreb → Northern Algeria),
  `CanalRegions`, `ConnectedRegions`, `DisconnectedRegions` y `FoggingLinkedRegions`. Los nombres renombrados ya se usan en el editor.

## Mapa y escenario a la vez (para que el juego cargue)
Las regiones de un escenario tienen que coincidir con las del mapa de su regionpack; si falta o sobra una, el juego da
«Error creating local game».
- Junto al selector «Escenario» del editor de regiones hay un indicador: **✓ coincide con el mapa**, o **⚠ usa otro regionpack /
  faltan N / sobran M** con el botón **«Adecuar»** (pasa el escenario a este regionpack, añade y quita regiones; luego «Guardar escenario»).
- Al **guardar** una región nueva, si el escenario abierto usa otro regionpack, pregunta si pasarlo a este y adecuarlo.
- Al **Instalar**, pregunta qué escenarios usarán el regionpack: los marcados se adecuan y se guardan.
- Cambiar el regionpack de un escenario (Global Data o el selector del editor de escenarios) también adecua sus regiones,
  y «Guardar escenario» avisa si el escenario no coincide con su mapa.
- «Adecuar» usa lo que se eligió al crear cada región (changelog del regionpack): dueño, controlador, terreno, población y
  **países históricos** (en el diálogo de región nueva se marcan uno o varios; por defecto, los de la región de origen).
- **Recortar** pregunta qué hacer con lo recortado: unirlo a una vecina de tierra o de mar, dejarlo vacío o crear una región nueva.
- **⟳ Refrescar** relee del disco el escenario y, si el regionpack del juego cambió fuera del editor, ofrece cargarlo.
- **Traducir un escenario de un regionpack modificado a otro**: «Adecuar» (o cambiar el regionpack del escenario) compara
  las formas de los dos mapas: lo que sobra va a la región del mapa nuevo con la que más se solapa y lo que falta sale de la
  región donde estaba esa área. Sirve entre dos regionpacks modificados, sin depender de nombres ni de changelogs.
- **Crear región**: a la derecha, «Importar GeoJSON» crea una o varias regiones a partir de contornos (nombre, país, tipo y habitantes
  precargados de las propiedades `name`, `owner`, `population`, `mh_type`). Se puede crear una ciudad en la región; si el país estaba
  rendido deja de estarlo y su capital pasa a una ciudad de la región (si no hay ninguna, avisa de que hay que crearla).
- **Ciudades, recursos y ejércitos** (editor de escenarios, pestañas Cities / Producers / Armies → «＋ Nueva…»): coordenadas a mano,
  «📍 En el mapa» o arrastrando el punto (casilla «Mover ciudades y recursos arrastrando»). En el editor de regiones, «Elementos del escenario» los muestra.
- **＋ Nuevo en las demás pestañas** (editor de escenarios, como «Add» de ed.exe; cada diálogo valida y al final lista lo escrito; falta «Guardar»):
  - *Nations*: país nuevo = `country<Nombre>.xml` + `player<Nombre>.xml` copiando una nación pequeña sin regiones (por defecto Tibet), registrados con
    `<object type="GO" fromFile>` en game.xml (y en la vista «minor»), su `Player` en gamestate.xml (color, jugable, `sidName`), descripción opcional,
    regiones/capital opcionales (toma las culturas de las regiones y deja de estar rendido). La bandera/iconos van en `UI/art/2D/countries/<Nombre>`
    (el editor no escribe en la carpeta del juego: avisa para copiarlos a mano). Relaciones: las demás naciones lo ven con 500 (`nDefault`).
  - *Navies*: flota (dueño, nombre, mar o región con puerto del mismo dueño, solo unidades navales). *Alliances*: nombre, líder, miembros.
    *Wars*: atacantes × defensores, con alianzas opcionales. *Trade / Aid*: de → a (varios). *Military Access*: `TreatyAgreement` ratificado con sus
    dos `MilAccessTerm` (tierra/aire/mar) en treaties.xml. *Diplomacy*: relación 0–1000 escrita en los dos player*.xml.
  - *Events*: guerra por fecha, embargo y protección de un aliado (sharedDataEvents.xml).
  - *Units / Factory Outputs / Research*: copia una plantilla con otro nombre (identificador sin espacios; texto visible propio en el stringTable del
    escenario). Con «copiarlos también», una unidad copia además su `FactoryOutputUnit`, su proyecto de investigación y añade el nombre a los sprites
    (`strTemplateNames`). Estos datos viven en ScenarioDefaults: al guardar el editor pregunta como siempre (sustituir defaults / escenario nuevo).
  Código: `scenario_create.py` (+ rutas `/api/scen/create` kinds `country|fleet|alliance|war|access|copy`, `/api/scen/bulk` y `create_info`).
- **GeoJSON (editor de regiones, botón «GeoJSON» de Archivo)**: un diálogo con dos pestañas.
  - *Exportar* (.zip, casillas para elegir): `regiones_tierra.geojson` y `regiones_mar.geojson` (separados; nombre, vecinas y, con escenario
    elegido en «Ver», `owner`/`controller`/`terrain`/`culture`/`population`), `borders.geojson` (opcional), `ciudades.geojson`,
    `unidades.geojson` (ejército, aviación, flotas, con su lista de unidades y dueño), `minerales.geojson` (o uno por recurso),
    `changelog_comparado.json` y `naciones.json`. Lo que necesita escenario se desactiva si no hay uno elegido.
    `changelog_comparado.json` compara el mapa abierto con la base elegida (por defecto World) **por geometría**: regiones nuevas (de qué
    regiones de la base salen y con qué % de su área), eliminadas (a dónde fue su área), divididas, fusionadas y modificadas; lee también
    los changelogs en inglés (`new_regions`…) y las claves del archivo salen en el idioma del editor. `naciones.json`: por región, quién
    la posee, quién la controla y su población, y por nación sus regiones.
  - *Importar* (varios archivos a la vez): los contornos (Polygon/MultiPolygon) de tierra y de mar se pueden importar por separado y se
    pregunta **una vez por importación** (a) la población: por el % del área que toman de las regiones de origen (por defecto) o la del
    GeoJSON, y (b) la nación dueña: la de la provincia que pierde más área (p. ej. la región 1 de Argentina se divide en 1, 2 y 3 → 2 y 3
    son argentinas) o la del GeoJSON. Si el contorno trae nombre y nación no se pregunta región a región (casilla); los contornos cuyo
    nombre ya existe se omiten. Los puntos (ciudades, minerales, ejércitos, aviación, flotas) se importan al escenario elegido con la misma
    interfaz que el editor de escenarios: tipo de los objetos sin `mh_type`, país de las flotas sin dueño y duplicados (importar todos /
    no importar / decidir uno a uno), con la opción **Reemplazar el existente** (actualiza nombre, posición y datos del objeto ya
    existente en vez de crear otro; no disponible si el duplicado está en el mismo archivo). Falta «Guardar escenario».
- **Importar puntos de un GeoJSON**: ciudades, recursos y ejércitos van a la región donde caen; las flotas sin país preguntan; los
  posibles duplicados (cerca de otro del mismo tipo) se pueden importar igual, decidir uno a uno o no importar.
- **Selección múltiple** (botón «Múltiple» del editor de regiones → mapa del editor de escenarios): regiones (incorporar a un país,
  unificar, tipo, cultura, históricas; el controlador distinto del propietario solo si están en guerra desde el inicio) y países
  (alianza, guerra, evento de guerra, comercio, ayuda, embargo) con el estado de sus relaciones y los eventos que los mencionan.
- **Países (Selección múltiple → Entidades políticas)**: ver las relaciones de todas las parejas (A–B, A–C, B–C…), pasar sus regiones y/o
  unidades a otro país, eliminar países (se quitan de alianzas, guerras, comercio, acuerdos y de `game.xml`; no probado en el juego),
  convertirlos en nación rendida con capital anhelada y una condición de protección («si el agresor ataca al protegido, el protector le declara
  la guerra o le embarga» con probabilidad por turno; es un evento de `sharedDataEvents.xml`).
- **Validador**: avisa de naciones rendidas que no se podrían liberar (sin capital válida o sin regiones históricas; asigna la capital
  automáticamente según sus regiones históricas) y de relaciones diplomáticas iniciales con cifras distintas entre dos países (A→B ≠ B→A; las iguala).
- **Naciones**: «Territorios anhelados» (regiones que la IA quiere recuperar; lista `Historic` de `BasicRegionLists` en su `player*.xml`, más otras listas
  con nombre; se editan con chips o en el mapa con la capa «Territorios anhelados») y «Personalidad de la IA» (implicación internacional, agresividad,
  postura y doctrina militar, política interior y científica, estabilidad). Al cambiar una relación diplomática A→B se cambia también B→A en el archivo del otro país.
- **Avanzado → sumar / restar área con un GeoJSON**: en el panel de una región, «＋ Sumar área desde GeoJSON…» le añade el área de los contornos
  (se la quita a las regiones que la ocupaban) y «－ Restar área…» se la quita, preguntando si queda vacía, pasa a otra región (de tierra o mar) o se crea una región nueva.
- **Editor de escenarios, pestaña Mapa**: el mapa y, a su derecha, la ficha del objeto (ciudad, región, unidad…), así se edita sin perder el sitio del mapa;
  al elegir un objeto en la lista, el mapa va a ese punto.
- **Editor de regiones**: «Capas» (ciudades, minerales, unidades militares) es una caja translúcida abajo a la izquierda del mapa; «Múltiple» desactiva «Seleccionar» y «Pintar propiedad».
- Los campos «Perfil diplomático», «Perfil de tratados» y «Posición internacional» son desplegables con todas las opciones; con dos o más países en la selección múltiple se
  cambia su relación diplomática (se escribe en los player*.xml de los dos).
- **Colores de terreno**: la exportación de la imagen de fondo puede añadir `terreno_por_tipo.png` (cada región del color de su terreno: llanura, colinas, montañas,
  bosque, selva, desierto, tundra; mar en celeste; huecos sin región en blanco) y `leyenda_terreno.json`; el GeoJSON de regiones puede llevar las propiedades `terrain` y `color`.
- **Doble clic** en una región del mapa de escenarios abre su ficha; un clic en una ciudad, mineral o unidad abre la suya.
- **Fondo del terreno**: «Exportar» puede dar un .zip con fondo (sin fronteras), límites transparentes y el fondo con límites.
- Mientras el servidor trabaja se ve una barra «Cargando… 45 %» con la acción en curso (crear la región, pasar ciudades
  y unidades, países históricos, guardar archivos…).

# Editor de escenarios (equivalente a ed.exe)
Abrir con **`Editor de escenarios.bat`** (o `http://localhost:8765/escenario` con el servidor en marcha).

- **Abrir escenario** (como File › Open de ed.exe). Muestra su regionpack.
- Pestañas: Global Data, Nations, Land Regions, Sea Regions, Cities, Producers, Armies, Air Forces, Navies, Alliances, Wars,
  Trade Flows, Aid Flows, Military Access, Players / AI, Colors, **Diplomacy**, **Historic Countries**, **Events**,
  **Unit Models (land/air)**, **Infrastructure**, Unit Templates (con `nRange` de misiles y bombarderos), Factory Outputs,
  Research Projects.
- A la derecha, **Editar objeto** (todos los campos, con sugerencias: países, regiones, mares, modelos 3D…, y el texto real de
  los SID) o **Mapa** (coloreado por país propietario, con los cambios sin guardar).
- **Aplicar** cambia en memoria; **Guardar escenario** escribe los XML (copia del original en `backup/archivos_originales`
  y del estado anterior en `backup/historial/<fecha>`). **Revertir** descarta lo no guardado.
- Reglas que aplica: una región vive en el archivo de su propietario (cambiar el dueño **mueve el bloque** con sus ciudades y
  productores); mover una ciudad/productor de región (campo «Ubicación») también la mueve de archivo; las propiedades repetidas
  (p. ej. varias `strCapabilities`) se editan por separado.
- **Duplicar / Quitar** cualquier objeto o hijo (ciudades, unidades de un ejército, miembros de una alianza…).
- **Validar**: dueños y controladores existentes, región en el archivo correcto, regiones que existen en el mapa (con renombres),
  puertos que son mar y vecinos, flotas en el mar o atracadas en una región con ciudad-puerto (así vienen muchas en los escenarios del juego), capitales, unidades que existen, alianzas y guerras.
- **Partisans**: interruptor que registra o quita `sharedDataPartisans.xml` en `scenario.xml` (lo copia si falta).
- **Nueva guerra…**: crea un evento «X declara la guerra a Y desde la fecha F con P % por turno» en `sharedDataEvents.xml`
  (lo crea y registra si no existe).
- **Abrir archivo…**: explorador de la carpeta del juego; identifica cada archivo (país, jugador, estado de partida, tratados,
  datos compartidos, tabla de textos, binario del mapa, textura del terreno con su zona, modelo Gamebryo, script, DLL…) y lo
  abre en el editor que corresponde o como **árbol editable** (cualquier XML).
- **Regionpack**: selector en la barra; cambia `strMapName` y `fileMapProperties` del escenario (falta «Guardar»).
- **Escenarios del juego** (Conclusion of the War, Steps to a Global War, The End of Diplomacy, The Limits of Peace,
  The Politics of Appeasement, The World at War, Tutorial; en Gold también Blitzkrieg, Clash of Continents, Rise of the Reich,
  Southern Star) cargan sus datos compartidos de `ScenarioDefaults`. El editor los carga y, si cambias alguno, al guardar
  pregunta: **sustituir los defaults** (afecta a la lista de escenarios que los usan) o **guardar como escenario nuevo**
  (copia la carpeta y los datos compartidos dentro, como un mod; el original no se toca).
- Clic en una fila de cualquier lista abre su ficha (cambia a «Editar objeto» si estaba el mapa). Los campos `sid…` tienen
  debajo **texto visible** editable (p. ej. renombrar un país): se escribe en `game/stringTable.xml` del escenario.
- **Global Data › Regionpack**: en la ficha del escenario se escribe o elige el regionpack; comprueba al momento si las regiones coinciden con su mapa (avisa de que si no, el juego no cargará el escenario) y el botón **Adecuar según el changelog** quita y añade las regiones necesarias.
- **Global Data**: todos los campos de `scenarioInfo.xml` y `scenario.xml` (los que faltan aparecen con «+» y se añaden al darles
  valor; descripciones en cuadro grande) y la lista de **países jugables** del menú de inicio.
- **Surrendered**: países sin regiones y si se pueden **liberar** en la partida (necesitan `strCapital`, `strOriginalCapital`
  y que sus regiones históricas incluyan la región de esa capital); el motivo si no. También en la ficha de cada país.
- **Players / AI**: en la ficha del jugador, comportamiento de la IA: eventos con fecha y % por turno, reacciones diplomáticas
  (cuánto cambia la relación cuando alguien empieza una guerra, firma la paz, un pacto…) y tratados (puntuación mínima).
- **Mapa** con capas (como «Region Paint» de MH2): a la izquierda la lista de valores con su color, en el mapa todas las regiones
  coloreadas por su valor y el elegido resaltado; con «clic modifica», un clic en una región:
  Propiedad (nación) → pasa a esa nación · Regiones históricas → añade / quita (verde, resto oscurecido) · Etnia (cultura) ·
  Tipo de región (terreno) · Ideología (gobierno del país dueño) · Alianzas → su país entra o sale (solo una alianza por país) ·
  Guerras (solo ver: agresores en rojo, defensores en verde). Casillas para ver **ciudades, recursos, ejércitos, aviación y
  flotas** como puntos; clic en un punto abre su ficha.
- **Múltiple** (barra del mapa): clic en varias regiones o, con «Entidades políticas», en el territorio de varios países (azul).
  Regiones: incorporarlas a un país (propietario y controlador), cambiar tipo de región o cultura, añadirlas a las históricas de un país.
  Países: añadirlos a una alianza existente o nueva (el primero la lidera), guerra inicial (el atacante elegido contra el resto, en
  gamestate.xml) o por fecha (evento con % por turno), y tratados de comercio o ayuda (Flows de game.xml) del elegido hacia el resto.
- Con un país abierto (pestaña Nations), al pasar a «Mapa» la capa Propiedad ya está en ese país: clic en una región la incorpora.
- **Inclinar mapa 3D**: desactivado, el escenario usa la cámara `WorldUnifiedFlat` (copia de `WorldUnified` sin elevación en la
  vista operacional; se crea en `DisplayLibraries\CameraSettings` al guardar, sin tocar la original).
- **Exportar GeoJSON** (zip; ahora igual que en el editor de regiones, con `regiones_tierra`, `regiones_mar`, `borders`, `ciudades`, `unidades`,
  `minerales`, `changelog_comparado.json` y `naciones.json`); cada objeto lleva `mh_type`. **Importar GeoJSON…**: ciudades, productores y unidades
  se emparejan por nombre (y dueño), se mueven a la región que contiene el punto y se crean si no existen; si un objeto no trae
  `mh_type` pregunta qué es. Las regiones actualizan sus datos por nombre (la geometría nueva se crea en el editor de mapa).
- **Compatibilidad con el mapa…**: compara el escenario con un regionpack. Quita las regiones que el mapa no tiene (su contenido vuelve a la región de la que salieron, según las ciudades y el changelog) y añade las del mapa que le faltan (desde su vecina, con población proporcional al área). Elegir un regionpack sin regiones añadidas (p. ej. «Worldold») devuelve el escenario a la configuración original. Un escenario que no cuadra con su mapa **no carga en el juego**.
- Al **Instalar** un regionpack, el editor de mapa avisa de los escenarios que lo usan y no cuadran con él; al guardar una región nueva, avisa si algún escenario se saltó por tener cambios sin guardar.
- **Idioma**: selector Español / English en la barra de los tres editores (`tools/editor/i18n.js`). Las traducciones están en
  `tools/editor/i18n_en.json` (textos fijos y mensajes del servidor) y en `i18n.js` (patrones para textos con datos, p. ej.
  «12 regiones · 3 históricas»). Tras añadir textos nuevos: `python tools/i18n_extract.py` lista los que faltan por traducir.
- **Recargar / salir**: al recargar, los editores descartan lo no guardado y leen los archivos guardados. Si hay cambios sin
  guardar, el navegador avisa antes de salir (con su propio texto); MHEditor.exe pregunta «¿Desea salir sin guardar los cambios?»
  (o «Leave without saving the changes?» en inglés).
- Pruebas sin tocar el juego: `python editor_server.py --escenarios <carpeta con copias de escenarios> --puerto 8766`.

# Registro del juego
**`Registro del juego.bat`** captura los mensajes internos del juego (los escribe con `OutputDebugString`, no en un archivo):
déjalo abierto, abre el juego, reproduce el problema y ciérralo con Ctrl+C. Quedan en `logs/juego_<fecha>.log` y muestran,
por ejemplo, qué región o archivo hace que un escenario no cargue. Detalles en `REVERSING_NOTAS.md`.

# Abrir como programa (ventana propia)
**`Editor (ventana).bat`** y **`Editor de escenarios (ventana).bat`** arrancan el servidor sin consola (si no está en marcha)
y abren el editor en una ventana propia, sin barras del navegador (modo aplicación de Edge, Chrome o Brave; en este PC, Brave).
La ventana usa su propio perfil (`_ventana_perfil/`).

# MHEditor.exe (programa de escritorio)
**`MHEditor\MHEditor.exe`**: los tres editores en una ventana nativa de Windows (WebView2), con menú *Editores* (Mapa,
Escenarios, Imágenes, Recargar) y *Ayuda › Carpeta de datos*. No necesita Python ni navegador: lleva todo dentro
(carpeta de 71 MB; se puede crear un acceso directo al .exe). Usa los mismos datos que los .bat (la carpeta `making-history`:
proyectos, respaldos, registros); si ya hay un editor abierto en el puerto 8765, se conecta a él.
- El .exe contiene una **copia del código**: después de cambiar el editor hay que reconstruirlo con
  `python tools/build_exe.py` (≈1 minuto; requiere `python -m pip install --user pywebview pyinstaller`).
- Archivos: `tools/mheditor_app.py` (arranque y ventana), `tools/build_exe.py` (empaquetado), `_build/` (temporales).
- Copiado a otra carpeta sin `making-history`, guarda sus datos en `Documentos\MHEditor`.

# Respaldos
Por defecto el editor **no copia archivos**: lo que se puede deshacer queda en el **changelog** del regionpack y en
**Deshacer/Rehacer** y **Volver/Rehacer** de la sesión. Las instantáneas del mapa (`history/` de cada proyecto) son solo de la
sesión: se borran la primera vez que se abre el proyecto en una sesión nueva. Para volver a guardar copias de cada archivo
(originales del juego y versión anterior a cada guardado, en `backup/`), arrancar con la variable de entorno `MH_RESPALDOS=1`.
- **Refrescar** (barra del editor de escenarios y Global Data › Regionpack): relee del disco el escenario y su regionpack
  (descartando lo no guardado, tras confirmar) y dice si las regiones coinciden y cuántos errores tiene la validación.
