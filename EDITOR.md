# Editor de regiones de Making History

Edita las regiones del mapa del mundo (formas, fronteras, centros) en el navegador, y guarda en los
binarios del juego (`regions.bin`, `borders.brd`, `regions.nts`) y en las texturas del terreno,
respetando las reglas del formato.

## Abrir
Doble clic en **`Region Editor.bat`**. Se abre `http://localhost:8765`.
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

### Crear un regionpack desde cero (mundo ficticio)
Botón **«+ Nuevo»** junto al selector «Regionpack» (`tools/new_pack.py`).
- **Mapa vacío = mapa con 0 regiones**: `regions.bin`, `borders.brd` y `regions.nts` válidos pero sin elementos (se comprobó que
  `mhmap.load_map/save_map`, `Project`, `/api/regions`, guardar y la instalación funcionan así). Las zonas sin región son **huecos**.
  Se construye con las herramientas de siempre: dibujar una región sobre el hueco o el mar (con «Rellenar huecos»), importar GeoJSON como regiones
  nuevas, sumar/restar área. Una región de mar se dibuja igual con «mar» (el hueco pasa a ser mar de la región nueva).
- **Nombre**: letras, números, `-` y `_`; no puede existir en `DisplayLibraries/Maps` ni como proyecto (sin distinguir mayúsculas).
- **Fondo**: sin imagen, todos los tiles quedan del **color del mar de World** (mediana de `OperationalTerrain-15-10`, RGB 8,48,164): se genera
  un solo tile DXT5 + 4 mipmaps y los 312 tiles son enlaces duros a esos 5 archivos (casi no ocupa disco). O bien se **importa una imagen**
  (proporción de World: 360° × 195°, ≈ 1,846 : 1; p. ej. 6144×3328, 3072×1664 o 1536×832 px) sobre todo el mundo o sobre una zona propia
  (p. ej. los límites de un GeoJSON). El editor avisa si la imagen se estirará. Se puede importar o cambiar más tarde con «Imagen de fondo».
- **Se crea como proyecto**: `editor_proyecto_<nombre>` (con `pack.json` `nuevo: true`), con una carpeta `base/` con lo que no depende de las regiones:
  `xml/map.xml` (World sin `RegionRename`, `CanalRegions`, `ConnectedRegions`, `DisconnectedRegions` ni `FoggingLinkedRegions`),
  `xml/properties.xml`, `art/MiniMap.tga` vacío (transparente), `art/StrategicTerrain.nif` y los tiles de `art/OperationalTerrain`.
  **No se escribe nada en el juego.** «Renombrar región» añade `RegionRename` al `map.xml` aunque no hubiera ninguno.
- **Instalar** (hace falta ≥ 1 región) crea la carpeta nueva `DisplayLibraries/Maps/<nombre>` (nunca pisa una existente) con `base/` + el mapa y
  los tiles modificados del proyecto + `changelog.json`, y el proyecto pasa a ser uno normal. Reutiliza la lógica de «Instalar» como regionpack nuevo
  (`Project.install`). No hay escenarios que lo usen todavía: crea uno o adapta uno existente con «Compatibilidad con el mapa».
- Mientras no esté instalado, «Copia» y «Refrescar desde el juego» no aplican. Los proyectos sin instalar aparecen en el selector de regionpacks.

### Naciones y escenario desde cero (`tools/scenario_new.py`)
Para construir un mundo ficticio hay que ir dando las regiones a naciones nuevas dentro de un escenario. Referencia de escenario con pocas
naciones: **«Clash of Continents»** (6 jugables + «Unoccupied», una región de 20 M hab., una ciudad, un productor de carbón y otro de metales cada una).
- **Nación nueva al crear una región** (dibujar o importar GeoJSON): en el diálogo, «Propietario» ofrece **➕ Nación nueva…** (y, ya creadas en esa
  sesión, «<nombre> (nueva)» para darles más regiones). Se piden nombre, color, cultura, jugable, **capital** (nombre, habitantes, IPUs, posición
  opcional; la ciudad se crea en esa región) y habitantes de la región. Un `owner` del GeoJSON que no existe en el escenario preselecciona «Nación nueva» con ese nombre.
  Al «Guardar» se crean `country<N>.xml` + `player<N>.xml`, su Player en `gamestate.xml`, `game.xml`, `scenarioInfo.xml` (jugables), textos, el país
  histórico (`sharedDataHistoricCountries.xml`) y la **capital** (`strCapital`/`strOriginalCapital`). Se anota en el changelog (`nacion`), así que «Adecuar» también las crea.
- **Reglas** (`MIN_POP = 2`): toda nación con territorio tiene **ciudad capital propia** y **más de 2 habitantes** (la capital, la región y el total). Se comprueba
  en el cliente, en el servidor **antes de guardar el mapa**, y en la validación del escenario (avisos).
- **Al crear un regionpack con «+ Nuevo»** el editor pregunta si crear también un escenario nuevo (vacío) con ese regionpack (nombre propuesto = el del regionpack; Cancelar = no) y lo deja abierto en «Ver».
  Si se dice que no, pregunta si usar **las naciones de un escenario existente**: el diálogo de región nueva ofrece entonces sus países como propietarios (también se cambia ahí,
  en «Escenario»). Ese escenario no se toca ahora; pasa al regionpack nuevo al «Instalar» / «Adecuar», que crea las regiones con el propietario, ciudad y población elegidos (changelog).
- **Changelog de un regionpack de cero**: su primera entrada es `regionpack_nuevo` con `origen: desde_cero`, `base: null` y la nota «no procede de World» (también `base: null` en `pack.json`).
- **Equivalencias con el juego vanilla**: la región seleccionada tiene la casilla **«Equivale a región del juego vanilla:»** (y el diálogo de región nueva igual), con una o varias regiones de World
  (p. ej. Cuyo, Patagonia). Se guarda en el changelog (`regiones_nuevas.equivale` al crearla; entrada `equivalencias` al editarla después, que manda; API `/api/region/equivalence`).
  Al **Adecuar** (o al instalar con un escenario de World marcado) `apply_equivalences` hace que la región nueva sustituya a esas: nace de la primera (dueño, controlador, cultura) y se queda con las
  ciudades, recursos, unidades y población de todas, que se quitan; si el changelog trae `pais`, ese pasa a ser su dueño. Lo que no tenga equivalencia sigue el «Adecuar» de siempre. Probado con regiones reales de un escenario (suma la población); no probado con un «Adecuar» completo sobre un regionpack instalado.
- **Escenario de cero**: si ningún escenario usa el regionpack, el diálogo pide «Escenario nuevo» (nombre) y al guardar se crea **vacío**
  (`create_scenario`; también `POST /api/scen/new_scratch {name, pack}`). Toma de la plantilla (Clash of Continents si existe, si no el escenario con
  menos países) solo `sharedData*.xml` (los que tenga), `game/` y `ui/`. **Archivos mínimos**: `scenario.xml`, `scenarioInfo.xml`, `game.xml`, `gamestate.xml`,
  `treaties.xml` (vacío), `waterWorld.xml` (sin mares), `sharedDataHistoricCountries.xml` (vacío) + `country/player<Nación>.xml` por nación. Sin guerras, alianzas, unidades
  ni «Unoccupied». **Sin imágenes**: no se crean `Button.tga`, `ButtonOver.tga`, `Title.tga` ni banderas.
- **Validación**: mientras el regionpack no esté instalado, el indicador del escenario muestra «regionpack sin instalar». Tras «Instalar», «Compatibilidad con el mapa» /
  «Adecuar» compara regiones del escenario y del mapa como siempre. **No probado en el juego**: el escenario se probó en el editor y con ficheros, no cargándolo en Making History.

### Navegación de las regiones de mar (canales)
Al seleccionar una región de **mar** el panel muestra «Navegación»: **libre** o **cerrada, ligada a un país (canal)**. En `map.xml` una región de mar
con entrada `CanalRegions` (`strCanalRegionName` = el mar, `strCanalZoneRegionName` = la región del país ligada al canal, p. ej. Panama Canal → Canal Zone)
tiene la navegación cerrada; `FoggingLinkedRegions` (`strRegionNameLinkedTo` / `LinkedFrom`) solo enlaza la niebla y deja la navegación libre
(así lo usa `WorldPublicPanamaCanalAndSuez`, que cambia las dos entradas de canal por enlaces de niebla). Elegir «cerrada» pide la zona (región vecina);
«libre» quita la entrada `CanalRegions` y conserva el enlace de niebla con la zona. Se escribe en la copia del proyecto de `map.xml`
(llega al juego con **Instalar**), se anota en el changelog (`canales`) y no afecta a «Adecuar». API: `GET/POST /api/region/canal`.

### Regiones de mar, huecos y mapas vacíos (cómo se crean)
- Al crear un regionpack desde cero se elige el **relleno inicial**: *todo mar* (una región «World Ocean» del tamaño del mundo, de la que se recorta la tierra),
  *vacío* (0 regiones; se dibuja sobre los huecos) o *todo tierra* («World Land»; se recorta mar y regiones). El fondo sigue en color mar hasta importar una imagen.
- **Región nueva sobre huecos**: dibujar (tierra o mar) sobre un hueco ya no exige «Rellenar huecos»: si debajo no hay nada más, el hueco se convierte en la región.
- **Región marítima nueva**: se recorta de las regiones de mar que toca y de los huecos. Un mar que queda **entero** dentro del polígono (polígono gigante) se absorbe:
  su área pasa a la región nueva y la antigua se elimina (flotas y escenarios como en «Eliminar región»). Una región de mar no pide país, terreno, población ni ciudad.
- **Recortar → «Convertir esa parte en una región marítima nueva»**: la parte recortada de la región elegida (de tierra o de mar) pasa a ser una región de mar nueva (solo pide nombre).
  En «Región nueva» (Dibujar/Cortar) con «Marítima» y «Cortar» marcado se recorta también de las regiones de tierra que toca. Las ciudades que quedaran dentro de un recorte
  a mar no se trasladan: revisa los escenarios.
- **Guardar como…** (antes «Copia»): duplica el regionpack con otro nombre sin tocar el original. En uno instalado copia la carpeta del juego (y el proyecto); en uno nuevo aún sin
  instalar duplica solo el proyecto (el juego no se toca).
- **map.xml y regiones nuevas**: las regiones nuevas no figuran en `map.xml` (viven en `regions.bin`; solo `RegionRename`, `CanalRegions`, `ConnectedRegions`, `DisconnectedRegions` y
  `FoggingLinkedRegions` van ahí). Pero una región sacada de otra **no heredaba** los vínculos de su madre. Ahora, al guardar, se copian al `map.xml` del proyecto: `DisconnectedRegions` y
  `FoggingLinkedRegions` si la nueva es vecina de la otra región, `ConnectedRegions` si queda a menos de 1,5° de ella; el informe lista lo añadido. Llega al juego con «Instalar».

### Malla rota al guardar: saneado automático
Antes, si el polígono dejaba una malla con contorno inválido (p. ej. al añadir área sobre varias provincias vecinas), el guardado se rechazaba («the mesh of X would be broken»).
`Project.save` ahora reintenta saneando los polígonos por niveles: 1 válido (`make_valid`), 2 rejilla de 1e-5°, 3 simplificado (1e-4°), 4 redondeado (±2e-4°); el informe avisa del nivel usado.
Con un fuzz sobre World (polígonos que amplían una región sobre su vecina, con ruido de 1e-7 a 1e-5°) fallaba ~10 %; con el saneado, 0 de 25 (los casos rotos se resolvían en el nivel 3).

### Tierra que quedó como mar (regiones imposibles de tocar)
Síntoma (Probando3, regionpack importado de un GeoJSON): en el juego y en el editor no se pueden seleccionar las regiones. Causa: 75 regiones de tierra tenían `u_type` 0
(mar) y `u_a` 0 en `regions.bin`; en el juego las regiones de mar no se seleccionan ni tienen dueño. Arreglo: en el panel de una región, **«Convertir en región de tierra…»** (o de mar)
cambia solo el tipo (`Project.convert_region_type`, `POST /api/region/convert`; la malla y las fronteras no cambian; queda en el changelog como `tipos`). Para muchas a la vez, con el editor CERRADO:
`python tools/fix_region_types.py editor_proyecto_<nombre>` (`--solo-ver` para ver la lista; `--mar REGEX` para los nombres que sí son mar; `--terreno N`); trabaja sobre el proyecto, no sobre el juego, y luego se pulsa «Instalar».

### Adecuar: regiones sin país
Al «Adecuar» un escenario, las regiones de tierra que no salen de otra con datos (p. ej. importadas de un GeoJSON, o creadas sobre el mar) no se podían añadir y el escenario no terminaba de cuadrar
(«no se ha añadido: no sale de ninguna región con datos…»). Ahora «Adecuar» abre el diálogo «Países de las regiones nuevas» con **todas** esas regiones (también las que el changelog no conocía
o cuya madre es un mar), con un selector «Asignar todas las que no tienen país a…» y uno por región; el país se guarda en el changelog solo para ese escenario (`pais_por_escenario`). Una región con
0-2 habitantes se crea con 1000 (más de 2).

### Regiones invisibles en el juego (mapa hecho desde cero)
Síntoma (Probando3): el escenario reconoce las regiones pero en el juego no se ven ni se pueden elegir (solo trozos de frontera). Causa: **todos los triángulos de `regions.nts`
estaban en sentido horario**; el juego solo dibuja y deja elegir los antihorarios (World y WorldModern: 100 % antihorarios). Al crear la primera región en un mapa vacío el
editor no tenía triángulos de los que deducir el sentido y elegía horario. Corregido (`transfer.apply_transfers`: antihorario por defecto). `new_region.normalize_map` gira los
triángulos horarios y pone a 0 el flag de costa en bordes tierra-tierra y mar-mar; se aplica en **Instalar** y en `tools/fix_region_types.py`.

### Mallas que se solapan («formas raras»)
Podelia y Polissia (WorldModern) se solapaban 0,0009 grados² en sus mallas. Al recortar esa zona de Podelia hacia Polissia, el traspaso le añadía a Polissia triángulos
que ya tenía, su malla quedaba con solapes y el guardado se rechazaba («la malla de Polissia quedaría rota»), incluso con el saneado automático. Ahora
`transfer.apply_transfers` resta a cada trozo lo que la región destino ya cubre antes de añadírselo.

### Contorno dibujado equivocado tras restar área (Wilno / Lituania)
Al restar a Wilno el área de `lt.json` y dársela a Aukstaitija, la malla quedaba bien (Wilno −0,22 grados², Aukstaitija +0,22) pero el trazado de anillos del contorno
salía válido y **equivocado** (5,4 de 9,7 grados², una arista recta de 3,5° hasta Bialystok): el editor dibujaba y dejaba editar esa forma rota, y editarla la habría
guardado. Ahora `Project.outline` compara el área del contorno con la de los triángulos y, si no cuadran (>0,5 %), dibuja la unión de los triángulos; el control del
guardado (`_mesh_valid`) hace la misma comparación. En WorldModern solo cambia Wilno.

## Mapa y escenario a la vez (para que el juego cargue)
Las regiones de un escenario tienen que coincidir con las del mapa de su regionpack; si falta o sobra una, el juego da
«Error creating local game».
- **Valores que el juego rechaza** (caso WorldModern, 21/10/2026: el mapa estaba bien y la partida no se creaba): `Game Log.bat`
  mostraba `"COUNTRYTYPE_MINOR" is not valid ... eCountryType` y `"SID.Game.Country.Description.<Escenario>.Qatar" is not valid ...
  sidShortDescription`. Las naciones creadas al hacer regiones nuevas (Qatar, Bahrain, South Sudan, Tajikistan) llevaban un
  `eCountryType` inexistente y un `sidShortDescription` sin texto en `game/stringTable.xml`. Válidos: `COUNTRYTYPE_PLAYABLE`,
  `COUNTRYTYPE_FEATURED`, `COUNTRYTYPE_NON_FEATURED` (`system/game/namespace.xml`). El editor ya no los produce
  (`scenario_new.create_nation`, `scenario_create`); **al guardar cualquier escenario** (editor de regiones al crear regiones
  e Instalar, o editor de escenarios) se corrigen solos (`Store.fix_load_errors`: tipo → `NON_FEATURED`/`FEATURED`, texto
  vacío creado; la lista va en `fixed` de la respuesta), y **Validar** los marca como error con su botón de arreglo
  (`Scenario.load_errors`). Si un escenario no carga y el mapa está bien, lo primero es `Game Log.bat`.
- **«🩺 El juego no lo carga…»** (diálogo Validación del editor de escenarios): «Empezar a registrar» abre `Game Log.bat` en su
  ventana (se termina con Ctrl+C o cerrándola; en `MHEditor.exe`, sin Python, escucha el propio editor hasta «Terminar el registro»).
  «Leer el último registro» analiza el `logs/juego_*.log` más reciente (`tools/game_log_report.py`): cada intento de cargar un
  escenario, si cargó o no, la etapa que falló y los errores agrupados con su explicación y qué hacer (los casos de arriba).
  Rutas: `/api/gamelog/start|stop|status|report`. Desde la consola: `python tools/game_log_report.py [archivo.log]`.
- Otros dos casos del mismo día, también comprobados con el log:
  - The Modern World Reloaded: `Property "objDipRelInitialValues" is not defined in type "MEPlayerData"` y luego `Found player named
    "X" but there wasn't a PlayerData named that` → `failed on InitGameValidateCountries`. El arreglo automático de diplomacia
    («Crear B → A») ponía el `DipRelInitialValue` suelto en `MEPlayerData` en vez de dentro de su `DipRelInitialValueList`; el juego
    descarta el player*.xml entero. Corregido en `scenario_layers` y, al guardar, `fix_load_errors` los mete en su lista.
  - Reloaded, después: `Had the following projects which didn't ever have their pre-reqs met: MechanizedInfantry` →
    `Failed to initialize country research state`. Las naciones nuevas copiaban una lista fija de investigaciones; en Reloaded
    MechanizedInfantry pide EarlyMechanizedInfantry, que no viene completada por defecto. Un requisito vale si está
    completado en el player*.xml o tiene `bCompletedByDefault`. `create_nation` usa ahora el árbol del escenario
    (`research_tree` / `missing_prereqs`) y al guardar se completan los requisitos que falten.
  - Darkest Hour Axis Diplomacy: `Error loading area map data for map WorldChile` → `Couldn't find area map`: su `strMapName`
    apunta a un regionpack que ya no existe (WorldChile se renombró a WorldModern). Validar lo marca; se arregla pasando el
    escenario al regionpack nuevo («Adecuar» / regionpack en Global Data).
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
  - *Detección automática* al importar contornos: nación (propiedades `owner`, `country`, `nation`, `admin`, `name_0`, `pais`, `sovereignt`…,
    sin importar mayúsculas ni acentos, con alias como «Estados Unidos» = United States), tipo de región (`mh_type`; propiedades `type`,
    `kind`, `featurecla`, `natural`, `ocean`, `sea`, `water`, `land`…; si no hay pistas, si el contorno cae sobre todo en regiones de mar)
    y terreno (`terrain`, `biome`, `relief`, `landcover`…: llanura, colinas, montañas, bosque, selva, desierto, tundra, en español o inglés).
    Lo detectado sale en una tabla (tipo, nación y terreno) que se puede corregir antes de importar.
  - *Reemplazar las regiones existentes*: borra antes las regiones existentes (todas las del tipo que se importa, o solo las que los
    contornos cubren en un 50 % o más), con confirmación y recuento. Son operaciones «eliminar región» (área vacía, quitadas de los
    escenarios) en el mismo guardado que las regiones nuevas —que toman su área—, así que se deshace de una vez con «Volver». Las regiones
    cuyo nombre coincide con un contorno no se borran (ese contorno se omite). La población «por área» se calcula sobre las regiones
    que había antes de borrar.
  - *Más opciones al importar contornos*: **solo naciones** (las asigna a las regiones existentes: la del mismo nombre o la que más área
    comparte); **naciones nuevas** (las que menciona el GeoJSON y no están en el escenario se crean con una ciudad al azar dentro de la región,
    «<país> City» / «Ciudad de <país>»); **dejar sin nación** (se asignan después en «Regiones sin nación…», con nación por región y marcas
    para asignar varias a la vez; al instalar se avisa si quedan regiones sin nación); **población**: la del GeoJSON y, si falta, una
    inventada según el área (nunca 0), editable en el diálogo de cada región; **tipo mixto** (tierra y mar en un archivo: por `mh_type` u
    otras propiedades, o se sugiere mar si el nombre dice Lake/Sea/Ocean/River/Mar/Lago/Océano/Río; se corrige en la tabla); si solo hay mar
    se ocultan nación y población; **rellenar huecos** (por defecto no; sí si no hay nada debajo); **exclaves** que deja el recorte (trozos
    sueltos de menos del 5 % de la región): los absorben las vecinas (por defecto), se incluyen en la forma importada o se dejan;
    **capa de referencia** para dibujar a mano («Mantener como referencia» o «Solo como referencia»). Con un solo contorno se abre el
    diálogo de la región. Al exportar, casilla para colorear las regiones con los colores de las naciones (`fill`, `stroke`).
    Pendiente: elegir «mar abierto / canal» al importar mares (los canales `CanalRegions` aún no se escriben desde el editor).
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
Abrir con **`Scenario Editor.bat`** (o `http://localhost:8765/scenario` con el servidor en marcha).

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
**`Game Log.bat`** captura los mensajes internos del juego (los escribe con `OutputDebugString`, no en un archivo):
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

## Novedades (instrucciones 4)
- **Editor de escenarios:** pestañas en español (en inglés con el selector de idioma); pestaña **Ideologías** con «＋ Nuevo» (copia las reglas de otra ideología y cambia nombre, color e icono; el nombre visible va a `game/stringTable.xml`); el campo Gobierno de una nación despliega todas las ideologías del escenario.
- **Fuerzas aéreas:** «＋ Nuevo» en la pestaña Fuerzas aéreas (solo unidades aéreas). Al crear un ejército solo salen unidades terrestres.
- **Ciudades:** se pueden vincular a una región (también de mar, p. ej. bases en la Antártida) y a un país; si el punto queda fuera de la región se avisa pero se permite.
- **Mapa:** primer clic en una región la resalta en blanco, el segundo abre su ficha; al pasar el cursor se ve «Región | País». Clic en una nación o región de la lista: se encuadra en el mapa.
- **Validador:** igualar todas las relaciones diplomáticas con la cifra más alta, la más baja o el promedio; avisa de nombres de nación que no existen (p. ej. «Cyrpus» → Cyprus) y los corrige; botón **Arreglar todo** para lo que tiene arreglo automático (no borra nada).
- **Recordar dónde quedó uno:** el editor de escenarios reabre el último escenario, pestaña y objeto; el de regiones, la vista del mapa por regionpack.
- **Editor de regiones:** Esc o clic en el vacío deseleccionan; tras guardar se vuelve a elegir la región por nombre (antes, al borrar una región quedaba elegida otra); «Avanzado» desplegado por defecto.
- **＋ Nuevo escenario** junto al selector de escenario; botón **Créditos** (actualizaciones, Discord y correo para errores).
- Lanzadores en inglés (`Region Editor.bat`, `Scenario Editor.bat`, `Game Log.bat`…) y dirección `http://localhost:8765/scenario` (la antigua `/escenario` sigue valiendo). El juego también se busca en `C:\Program Files (x86)\Muzzy Lane Software\…` o en `MH_GAME_MH1` / `MH_GAME_GOLD`.

## Recorte, changelog y fondo (instrucciones 4, segunda parte)
- **Recortar** (`askCutTarget`): las vecinas de tierra salen con su país (el del escenario abierto) y ordenadas por cercanía al último punto dibujado del recorte; nueva opción **«Anexar a otro territorio (no contiguo)»** con todas las regiones de tierra (el traspaso del mapa ya admitía cualquier región; la malla se valida igual al guardar).
- **Población al sacar una región**: casilla **«No quitar población a la región de origen»** (todas las fracciones a 0; la región nueva usa los habitantes que se pongan o la densidad media). La tabla de población ya solo lista las regiones realmente cortadas (`/api/cut_preview`).
- **«Equivale a región vanilla» por defecto** (`defaultEquivalence`): la región de la que se corta si existe en World y es del mismo tipo (tierra/mar); si no, las equivalencias que ya tenga esa región; si no, se sugiere (placeholder) una vecina vanilla del mismo tipo. Varias regiones nuevas pueden equivaler a la misma. `/api/vanilla/regions?full=1` devuelve `{name, sea}`; ahora lee la **copia vanilla** (ver abajo).
- **Ciudades y recursos en traspasos**: al «Adecuar» (`pack_sync_apply`) `rehome_transferred` mueve las ciudades/recursos que quedaron fuera de su región a la que recibió el área según los `traspasos` del changelog (solo entre regiones que el changelog nombra). Las regiones nuevas ya movían ciudades y unidades dentro de su forma (`reassign_by_geometry`). Probado con un escenario de prueba y geometrías simuladas; **no** probado con un «Adecuar» completo sobre un regionpack instalado.
- **Exclaves al sacar una región a mano** (`exclaveStep`, **opcional**: casilla «Tratar los exclaves que deje este recorte», desactivada por defecto; en la importación la opción por defecto es «dejarlos como están»). Solo cuenta los trozos que genera el propio recorte; las partes que la región ya tenía aparte (islas, enclaves deliberados como los de Armenia/Azerbaiyán) no se tocan. Si el recorte deja trozos sueltos, se ofrece incluirlos en la forma nueva o que las vecinas los absorban (reutiliza `/api/geojson/exclaves` de la importación).
- **Dueño de regiones nuevas sin región de origen** (p. ej. creadas desde el mar): al instalar/«Adecuar», `askOwners` lista las que no tienen dueño y permite elegir el país por escenario (`/api/changelog/owners`, `/api/changelog/owner`); sin país no se pueden añadir y el escenario no cargaría, por eso avisa antes. Se guarda como `owner_by_scenario` (`pais_por_escenario`) en la región nueva del changelog y **manda sobre `owner`** en ese escenario (`for_scenario`): una región al sur de Kaliningrado puede ser de Polonia en un escenario y de Rusia en otro. La casilla «Mostrar también las que ya tienen país» permite fijar el dueño propio de cualquier región nueva.
- **Elegir escenarios al instalar/adecuar**: «Seleccionar todo» / «Ninguno».
- **Changelog en inglés** (`tools/changelog_keys.py`): `changelog.json` se escribe con claves en inglés (`date`, `transfers {from,to}`, `new_regions {name, mother, owner, …}`, `deleted_regions`, `equivalences`, `renamed`, `channels`, `centers`, `new_adjacencies`, `operations`…) y se lee **en inglés o en español** (los antiguos se convierten al leer y se reescriben en inglés al guardar). El código interno y la API del editor siguen usando las claves españolas (`to_internal` al leer, `to_file` al escribir). Los nombres de región (claves de `centers`, `equivalences`, `population_fractions`) no se traducen.
- **Repintado del fondo al borrar/incorporar regiones** (`transfer.apply_transfers`): el borrado de líneas viejas es ancho y se llevaba trozos de fronteras que siguen existiendo; ahora esas fronteras vivas se repintan donde cae el borrado. Probado borrando una región en una copia del proyecto (fronteras continuas en el tile).
- **Restaurar fondo** (botón «Restaurar fondo», `background_restore.py`, `/api/background/restore`): recupera del World original los píxeles de los tiles ya modificados que no tienen frontera (ni en el mapa actual ni en el original) y que no cambiaron de tierra a mar; conserva líneas, costas e islas nuevas. Se puede acotar a la parte visible y se deshace con «Volver». Probado en copia (3 tiles, 79–90 % de la imagen restaurada, sin cortar líneas).
- **Copia «vanilla» de World** (`vanilla_ref.py`): `backup/vanilla_World/` (xml originales de `backup/mapa_original` + `map (default game file).xml`); las texturas originales salen de `backup/mapa_original/OperationalTerrain` y, si el editor no tocó ese tile, de `World/art`. Es la referencia para equivalencias y para «Restaurar fondo»; nunca se escribe. `PackMap(pack, folder)` admite una carpeta cualquiera.

### Pendiente de estos puntos (no hecho)
- (15) Registrar/preguntar ciudades de regiones nuevas al «Adecuar» sin duplicar por nombre o cercanía (hoy: `ciudad` del changelog + `_city_and_liberate`, que solo crea si no hay ya una dentro).
- (21) Comparar regionpacks usando World como tercero vía changelog (existe `geojson_compare.py` de otra sesión; no se ha conectado).
- (22) Conversor de colores del fondo MH1 → Gold (faltan datos de cómo difieren los colores).
- (3) Los exclaves de **sumar/restar área** («Avanzado») no pasan por `exclaveStep` (sí «Nueva región» y la importación).
- **Selección múltiple:** el mar elegido se ve (azul); «Exportar GeoJSON» exporta solo las regiones elegidas con sus ciudades, recursos y unidades; tras unificar o eliminar desde el editor de escenarios, «Instalar mapa…» abre el editor de regiones con la instalación ya pedida.
- **Nación nueva desde una región nueva:** la cultura por defecto es la de la región de la que sale.
- **Nueva nación (2.0):** por defecto se crea con los valores de una nación nueva (la plantilla es opcional); la bandera toma el nombre del país; la capital puede ser una **ciudad nueva** (nombre interno y visible, región, población, IPUs) o una existente. No deja crear una nación cuyo nombre ya tenga un jugador en `gamestate.xml` (dos «Player» con el mismo nombre impiden crear la partida: «Found duplicate player named …»).
- **Validar** detecta jugadores repetidos en `gamestate.xml` y alias o archivos repetidos en `game.xml`, y deja elegir cuál conservar.
- **Adecuar** (Compatibilidad con el mapa) pasa a mar una región que el escenario tenía como tierra y el mapa como mar (y al revés).
- **Ciudades:** sin coordenadas se colocan en un punto al azar de su región (antes: «could not convert string to float»); casilla «Es la capital de su país»; el nombre visible copia el interno salvo que se cambie. En su ficha, la región puede ser también de mar y se puede **mover el punto** dentro de la región.
- Botón **▦ Seleccionar regiones** en la barra del editor de escenarios. Versión **2.0** (reemplaza a la 1.0).

## Región de mar, huecos y arreglos (tanda 5)
- **Seleccionar un hueco** (zona sin región): en «Ver / propiedad», un clic en el vacío lo resalta (`/api/gap`, `Project.gap_at`) y el panel ofrece **«Crear una región nueva aquí…»** (abre el diálogo de región nueva con la forma del hueco; elige tierra o mar) o **«Unirlo a:»** una región vecina (operación `fill_point`). Si el hueco no está cerrado (mapa vacío) no se puede seleccionar: ahí se dibuja la región con «Nueva región».
- **Equivalencia vanilla de una región de mar**: el panel de una región de mar también tiene «Equivale a región del juego vanilla» (lista `vanillaSeaList`), y el diálogo de región nueva ofrece solo las del tipo elegido. Una región de mar solo equivale a regiones de mar y una de tierra a las de tierra (`eqOfKind` en el cliente; `/api/region/equivalence` lo rechaza con error). El **Adecuar** de escenarios (`apply_equivalences`) hoy solo aplica las equivalencias de tierra: la de mar queda en el changelog pero no mueve flotas (módulo de escenarios, no tocado aquí).
- **Recortar → región marítima**: la opción «Crear una región MARÍTIMA nueva con esa parte» ya estaba en el diálogo de recorte; se comprobó de punta a punta (recorte de Donetska → región de mar nueva, registrada en waterWorld.xml) y se rotuló mejor.
- **Créditos** junto a Topología: `#creditsSlot` en index.html (`i18n.js` `credits()` lo usa si existe; si no, va al final de la barra como antes). Siempre visible (su grupo no se oculta en la vista «Ver»).
- **«Restaurar fondo»** es un botón con icono en el grupo Archivo. Tarda (carga el mapa original y las mallas): ~35 s para 4 tiles. Se acelera calculando la caja de cada región sin fundir sus triángulos.
- **Capa naranja de regiones nuevas** (`NEW`): al cambiar de regionpack se vacía y se redibuja con el changelog del nuevo (antes quedaban las del anterior).
- **Línea falsa que cruza una región** (Rostov Oblast de WorldModern): su malla tiene 3 trozos separados por rendijas de ~2 m (restos de redondeo de traspasos repetidos); cada trozo se dibujaba con su contorno y se veía una línea (en el juego no existe). `Project._merge_seams` funde para dibujar los trozos que casi se tocan (5e-5°); la malla no se toca. Comprobado en el navegador sobre una copia: la línea desaparece.
- **Regionpack vacío + escenario (Ameba)**: el regionpack nuevo aún no está en el juego, así que «Pasar el escenario a este regionpack» fallaba (no existe el regionpack). Ahora, al guardar con un escenario abierto que usa otro regionpack, si el regionpack es nuevo avisa de que hay que instalarlo, y al **instalar un regionpack nuevo** se piden los escenarios que lo usarán (antes se instalaba sin ellos y no quedaban adecuados). Reproducido con el flujo completo en una copia (crear regionpack vacío, región con nación nueva, instalar con escenario). Si queda una región ya guardada en el mapa pero sin instalar (como «Ameba»), basta «Instalar» y marcar el escenario; no hay que volver a dibujarla.
- **Región de mar que acabó como tierra (Caspian Sea)**: en el mapa y en el changelog de WorldModern es de mar; en el escenario «The Modern World Reloaded» quedó como región de tierra de Azerbaiyán. No se pudo reproducir la causa; el arreglo de fondo está en `pack_sync_plan` (otra sesión): una región de tierra del escenario cuyo nombre es de mar en el mapa se quita y se añade como mar (y al revés).

### Prueba de punta a punta de un regionpack desde cero (copia, sin tocar el juego)
Hecha sobre copias (servidor de prueba, Maps y escenarios en una carpeta temporal): crear regionpack con relleno «vacío», «mar» y «tierra»; región de mar y de tierra (con nación nueva) sobre el vacío; unir un hueco al mar; recortar tierra a una región marítima nueva; recortar a un mar no contiguo; isla de tierra sobre el mar; instalar con un escenario y validarlo (editor de escenarios, «Validar»).
- **Funciona:** los tres rellenos; región de mar y de tierra en mapa vacío (el diálogo pregunta Terrestre/Marítima); seleccionar un hueco con clic y unirlo a una región (también un hueco abierto, que se recorta a 8°×8°); crear región desde un hueco; recorte → región marítima nueva (registrada en waterWorld.xml); recorte a un mar no contiguo; tierra sobre mar con nación nueva y escenario nuevo; instalar un regionpack nuevo con escenario; el validador da 0 problemas en los escenarios resultantes.
- **Arreglado en la prueba:** al «Adecuar», el dueño por escenario del changelog (`owner_by_scenario`) solo se usaba al registrar al guardar, no en `pack_sync_apply`; ahora se usa también ahí (una región sin región de origen, p. ej. «World Land» de un regionpack con relleno de tierra, queda en el escenario con el país elegido en vez de omitirse con un aviso).
- **Limitaciones:** un hueco abierto solo se selecciona por trozos de 8°×8°; el dueño de una región sin madre hay que elegirlo (el diálogo «Países de las regiones nuevas» lo pide al instalar/adecuar; por API directa se omite con aviso y el escenario queda sin la región). Dibujar polígonos con clics reales en el panel del navegador de pruebas fue poco fiable (el panel cambia de tamaño); los diálogos y botones sí se probaron con clics reales, y los contornos se pasaron por código.

## Cambios 5
- **Eventos: «＋ Añadir al evento»** en su ficha: un efecto (al evento o a una de sus elecciones: guerra, embargo, ideología, recursos, independencia, anexión, unidades, relaciones, cultura) o una condición (países que existen, desde una fecha/turno, probabilidad por turno, dos países sin guerra). Si el efecto usa países que el evento no lee, se añade la condición «existen» con sus variables (`scenario_events.event_add`, `/api/scen/event_add`).
- **Color de la nación** en su ficha (está en `gamestate.xml`): muestra y selector visual (#RRGGBBAA).
- Al salir de **Países históricos** se quita su capa verde del mapa.
- **Ciudades:** sección **Puerto** (casilla «Es un puerto» + mar: los vecinos de su región primero, o uno lejano). Al arrastrar una ciudad a otra región pregunta si pasa a depender de ella o sigue en la suya; se puede soltar sobre el mar; el clic final del arrastre ya no elige región. Las ciudades **sí tienen población propia** (`nPopulation`, aparte de la de la región; p. ej. Kabul 80 000 en The World at War).
- Botones **📁 Escenario** y **📁 Regionpack** (abren la carpeta en el Explorador; también 📁 junto al regionpack en el editor de regiones).
- El mapa del regionpack queda en memoria (`scenario_layers.pack_map`): situar o mover ciudades tarda ~12 s la primera vez y <1 s después.

### Recortar una región de mar (p. ej. Caspian Sea)
- Recortar → «Crear una región MARÍTIMA nueva con esa parte» funciona también cuando lo recortado es de mar: probado partiendo el Caspian Sea de WorldModern en «North Caspian» y «South Caspian» sobre una copia de «The Modern World Reloaded».
- **Puertos:** al registrar una región de mar nueva (al guardar o al «Adecuar»/«Aplicar changelog»), las ciudades portuarias cuyo puerto da a otra región de mar y que quedan más cerca de la nueva (a menos de 1,5°) pasan a tener su puerto en ella (`scenario_layers.reassign_ports`): Astrakhan → North Caspian, Rasht → South Caspian; Baku y las demás siguen en Caspian Sea. Las flotas que quedan dentro del mar nuevo pasan a él como antes.
- **«Aplicar changelog» ya no toca las regiones que el escenario ya tiene**: antes volvía a repartir su población y a cambiarles el dueño (p. ej. North Macedonia volvía a Serbia, Northern Cyprus a Turquía). Ahora solo registra las que faltan.
- Al guardar ya no salen errores de capitales de **todas** las naciones del escenario: solo se revisan las naciones nuevas.
- Los diálogos (recortar, región nueva, etc.) siguen al pulsar Aceptar aunque el evento «close» del navegador tarde (`waitDialog`).

# Imágenes del escenario (`/imagenes` y editor de escenarios)
Página **`/imagenes`** (menú *Imágenes* de MHEditor) con tres herramientas; código en `tools/image_tools.py`.
Todo se escribe solo tras confirmar; con `MH_RESPALDOS=1` se copia antes lo que existía (`backup/imagenes_originales`, `backup/historial`).
- **Título y botones**: `Title.tga` (1024×64), `Button.tga` / `ButtonOver.tga` (512×128, zona visible ≈286×118). Capas
  (imagen, texto con contorno/sombra, relleno), mover arrastrando, escala con la rueda, opacidad. Se exporta con el mismo
  formato que el original (TGA 32 bits, RLE o no, origen abajo); la escritura TGA es exacta (ida y vuelta píxel a píxel).
- **Banderas y escarapelas**: desde una bandera (y opcional escarapela y foto del líder) genera los 20 archivos de
  `ui/art/2D/countries/<strFlagName>/`, medidos en los 293 países de The Modern World:
  | Archivo | Lienzo | Contenido |
  |---|---|---|
  | 3DFlag.tga | 128×64, 24 bits | bandera **invertida verticalmente** |
  | big-flag.bmp / flag-256-128.bmp | 128×64 / 256×128 | bandera entera (BMP 24 bits) |
  | 262-134-flag-shadow.tga | 512×256 | bandera 256×128 en (3,3) + sombra negra |
  | flag-68-34.tga / -shadow | 128×64 | 68×34 en (0,0) / en (4,4) + sombra |
  | flag-48h-64w.tga | 64×64 | 56×40 en (4,5) + sombra |
  | diplomatic-flag.tga / -over | 32×32 | 24×24 en (4,4), con / sin sombra |
  | flag-16-16.tga / flag-19-19.tga | 16×16 / 32×32 | 12×12 en (2,2) / 15×15 en (2,2), con sombra |
  | multichat_flag.png / .bmp | 16×16 / 32×32 | 15×15 en (0,0) (el .bmp sobre blanco) |
  | decal-64-64.tga | 64×64 | escarapela 60×60 en (2,2); **decal.tga** = la misma invertida |
  | decal-64-64-bw / -bw-over | 64×64 | gris (luminancia) / gris aclarado (0,85·g+40) |
  | decal-42-42.tga / 1919DecalWShadow.tga | 64×64 / 32×32 | escarapela 40×40 en (1,1) / 19×19 en (4,4) |
  | leader-lobby.tga | 512×512 sin comprimir | retrato 272×304 en (1,1): bandera de fondo y la foto |
  Las sombras usan el alfa más frecuente de los países existentes. Sin escarapela, se recorta la bandera con forma de
  escudo, círculo o cuadrado. En los huecos cuadrados la bandera se estira (como la mayoría) o se recorta (asta/centro).
- **Iconos de unidades y productos**: 4 medidas en `ui/art/2D/global/unit-template-icons/{6464,4646,3636,2626}` del
  escenario (icono de 64/46/36/26 px arriba a la izquierda en un lienzo de 64 o 32, TGA 32 bits sin comprimir), registrados
  en `ui/UnitTemplateIconTable.xml` (por `strTemplate` = strName de la unidad) o `ui/FactoryOutputIconTable.xml` (por
  `strName`; los productos-unidad usan el icono de su UnitTemplate). La imagen de investigación (256×256, 128×256 o
  512×256) va en `ui/art/2D/MediaPack/Research/` y se registra en `ui/MediaPack.xml`, biblioteca `Research_Project_Icon`,
  por el `strIconName` del proyecto. Las rutas se escriben como las del escenario (`../../../ui/art/2D\global\…` y
  `/../Modern Europe/system/ui/art/…`): el juego busca primero en el `ui/` del escenario y luego en el del contenido.
  Si el escenario no tiene su tabla, se copia la del juego. Los iconos del juego (carpeta de contenido) no se tocan.

**En el editor de escenarios** (`tools/editor/escenario_imagenes.js`, cargado al final de `escenario.html`):
- *Naciones*: bandera pequeña junto a cada país; al abrir un país, sección **Bandera y escarapela** con las imágenes
  actuales y **Importar bandera…** (13 archivos de bandera) / **Importar escarapela…** (6 archivos decal), con vista previa.
- *Unit Templates*, *Factory Outputs*, *Research Projects*: icono junto a cada entrada; al abrir una, sección **Icono**
  con **Reemplazar/Importar icono…** (y en unidades, **Imagen de investigación…**).
- Rutas: `/api/img/flag?scen=&country=` (PNG de la bandera, carpeta según `strFlagName` de gamestate.xml),
  `/api/img/icons?scen=` (unidades, productos e investigación con su archivo), `/api/img/raw?rel=&crop=1`,
  `/api/img/flag/preview|write` (`only`: `flag` o `decal`), `/api/img/icon/preview|write` (`kind`: unit, output, research).

## Imágenes en las fichas del editor de escenarios (tanda 2)
Código: `tools/image_assets.py` (recursos gráficos con todas sus variantes) y `tools/editor/escenario_imagenes.js`.
Cada imagen se muestra con su estado: **propia** (en `<escenario>/ui/…`), **del juego** (sin versión propia: se ve la de
`Modern Europe/system/UI/…`) o **falta**. «Exportar» descarga la variante más grande en PNG; «Importar…» (archivo o URL)
genera **todas** las variantes imitando cada original: mismo lienzo, misma zona ocupada (con sus bordes suaves) y mismo
formato. Se escribe solo tras confirmar y nunca en la carpeta de contenido del juego.
| Ficha / sitio | Imágenes |
|---|---|
| Nación | bandera (13 archivos) y escarapela (6) con exportar/importar; **portada** `UI2DPolicyArea/Domestic/national-info-bg-<strflagname>.tga` (256×256, imagen 254×158; sin ella el juego usa `national-info-bg.tga`) y **retrato del lobby** `countries/<strFlagName>/leader-lobby.tga` |
| Global Data › Scenario | `Title.tga` desde una imagen **o desde el nombre** (texto con contorno y sombra), `Button.tga` y `ButtonOver.tga` (generado con **brillo +8**, ≈ +20 de 255, como los del juego; o una imagen propia) |
| Ideologías | `icons/government-type-icon/<strIconName>-icon*.tga`, `UI2DSpecialFeedback/liberation-<x>.tga`, `UI2DPolicyArea/EndTurn/notification-end-turn-liberate-<x>.tga` |
| Terrenos | `Terrain/<strTerrain>.tga`, `-small.tga`, `UI2DRegion/top-image-<x>.bmp` |
| Productores | iconos del recurso: `resources/<x>*.tga` (7 medidas), `UI2DPopUpResourceProducer/resourceproducer_*_<x>`, `global/<x>.tga` |
| Unit Templates | tabla de iconos (4 medidas) + `UI2DPopUpMilitaryUnits/unit-icons/<strIconName>.tga` (compartido por las unidades con ese strIconName) |
| Factory Outputs | tabla de iconos + `UI2DSlideoutIndustrialProduction/<strIconName>.tga` |
| Research Projects | imagen grande (MediaPack, Research_Project_Icon) |
| Botón **Iconos e interfaz** | catálogo de todos los tipos (con cuántas variantes son propias) y explorador de `UI/art` del juego: lista de lo que el escenario ya personaliza (The Modern World: 94 imágenes) y cualquier imagen de la UI para exportarla o reemplazarla |
- Rutas sacadas de los `computeFrom` de los XML de la UI del juego. Que el juego tome primero la versión de `<escenario>/ui/` es lo
  que hace The Modern World con su interfaz y sus iconos; no está probado en el juego para cada una de estas rutas.
- Clave nueva sin ninguna imagen (p. ej. una ideología inventada): se crean con las medidas de una de referencia (democratic, coal, plains, infantry).
- **Banderas de otra proporción** (opción *Proporción*): recortar al centro (por defecto), estirar las columnas de los extremos,
  pegada a la izquierda rellenando con la columna derecha (tipo Chile) o deformar. **Desde URL**: el servidor la descarga (PNG/JPG…; no SVG).
- Las vistas previas muestran `3DFlag.tga` y `decal.tga` al derecho (los archivos van invertidos, como en el juego).
- **Lista de naciones**: bandera junto a cada nación también en la vista Mapa (capa Propiedad/Históricas; antes desaparecían porque
  esa vista cambia la lista) y marcas **sin bandera** / **sin color** (`/api/img/nations`).

## Instrucciones 6 (editor de regiones)
- **Sumar área desde GeoJSON (Abjasia)**: fallaba en los 5 niveles de saneado. Causa: el contorno importado rozaba a Rostov y Kuban en trozos de ~1e-7 grados²; al traspasarlos quedaban «pellizcos» (el borde de la región se toca a sí mismo en un punto) y el trazado de anillos daba un contorno inválido aunque la malla (los triángulos) estaba bien. Ahora: (1) en «Sumar área» / «Dibujar →» los roces menores de 1e-6 grados² o del 0,01 % del contorno no se traspasan (se avisa); (2) una región cuyo trazado falla pero cuya malla es sana (triángulos sin solaparse) ya no bloquea el guardado y se dibuja/edita con la unión de sus triángulos (`_mesh_ok`). Probado en una copia de WorldModern: Circassia → Abjasia 0,28 grados² al primer intento.
- **Los fallos al guardar siempre se ven**: si el servidor no responde, responde algo que no es un informe, o el guardado no se hace, sale un aviso además del informe. Cualquier error de un botón (excepción de JavaScript) se escribe en el informe («Error del editor: …»).
- **«Instalar» un regionpack nuevo (desde cero) no hacía nada**: el botón usaba una función de traducción que no existía en ese punto y fallaba en silencio. Arreglado (causa de «Probando3»); ahora además salen marcados los escenarios que ya nombran ese regionpack. Probado con una copia de Probando3: se instala y el escenario queda con World Ocean y Landia (el validador solo da avisos de plantilla: France, Germany… nombradas en sharedData).
- **«Restaurar fondo»**: además de recuperar el fondo, repinta encima todas las fronteras actuales de los tiles que toca, así quedan continuas aunque un borrado anterior se hubiera comido trozos (p. ej. tras quitar exclaves a mano en India). Y el mapa vuelve a pedir las texturas al terminar (antes seguía mostrando las de antes hasta mover el mapa, y parecía que no había hecho nada). Probado en la copia: desaparece la cicatriz vertical del antiguo «EastBo» (este de Bolivia) y la frontera de United Provinces vuelve a estar entera.
- **«Adecuar»** sigue disponible aunque el escenario ya cuadre con el mapa (vuelve a aplicar el changelog: dueños por escenario, equivalencias…).
- **📁 (carpeta del regionpack)**: con un regionpack aún sin instalar abre la carpeta de su proyecto; la ruta queda escrita en el informe. Si falla, se dice por qué (si el editor abierto es de una versión anterior, hay que cerrarlo y abrirlo de nuevo).
- **Importar GeoJSON**: nombres repetidos dentro del archivo (p. ej. 17 «Aguas interregionales») pasan a «Nombre 2», «Nombre 3»…; los nombres de nación del GeoJSON con caracteres no válidos en un nombre de archivo («Morrowind / territorio…») se limpian («Morrowind - territorio…»), y si aun así hay uno inválido el error dice cuál.
- Escenario **sin** `Title.tga`, `Button.tga` o `ButtonOver.tga`: «Exportar plantilla» descarga la de un escenario del juego
  (The World at War…; si no hay, una transparente de 1024×64 o 512×128) para editarla e importarla; al importar se escribe con su formato.

## Instrucciones 7 (editor de regiones)
- **Mapa negro en el juego (Tamriel, Probando3)**: los escenarios creados desde cero ponían `strSpriteMapName` = nombre del regionpack en scenario.xml; el juego busca `DisplayLibraries/SpriteMaps/<nombre>.xml`, solo existe `World.xml`, falla «Error loading sprite map» y todas las regiones salen negras. Ya no se cambia (queda el de la plantilla, World), y «Adecuar» lo corrige en los escenarios que ya lo tienen mal (`fix_sprite_map`). **Para arreglar Tamriel y Probando3: elegir el escenario en «Ver», pulsar «Adecuar» y «Guardar escenario».**
- **belarus.geojson → Wilno** fallaba («la malla de Turov quedaría rota»): no era el filtro de roces; tras el traspaso Turov tenía un solape de redondeo de 7e-5 grados² (de 9,2) que la comprobación de malla sana rechazaba. La tolerancia pasa a 1e-4 relativo. Probado en copia de WorldModern: se guarda.
- **Resaltar las regiones nuevas**: casilla en Opciones (se recuerda en el navegador).
- **Renombrar región…**: pregunta si cambiar solo el nombre que se ve en el juego (stringTable de cada escenario; el interno sigue igual) o también el interno (RegionRename en map.xml).
- **Cultura de una nación nueva**: el campo ofrece en una lista las culturas del escenario (se puede escribir una nueva).
- **Recortar la región seleccionada**: la tabla de población solo saca habitantes de esa región, aunque el dibujo toque otras.
- **Tamriel «no se puede modificar»**: no se reprodujo: en una copia del proyecto Tamriel todas las regiones son editables (una tenía el contorno trazado inválido, ya arreglado con la unión de triángulos). Ese proyecto tiene 33 regiones («Glenumbra 2»…, sobre «World Land»), no las 104 del GeoJSON: se hizo con una versión anterior (relleno de tierra, nombres duplicados y naciones con «/»). Recomendado rehacerlo con relleno vacío según los pasos de «Instrucciones 6».
- **Regiones «Nombre 2» de Tamriel**: venían de elegir dos veces el mismo GeoJSON (p. ej. `tamriel_regiones.geojson` y `tamriel_regiones (1).geojson`): la segunda copia de cada contorno se renombraba «X 2» y le quitaba el área a la primera. Ahora un contorno con el mismo nombre y la misma forma (área ±1 %) se omite y se avisa; solo se numeran los que comparten nombre con forma distinta (p. ej. las 17 «Aguas interregionales»). El regionpack y el escenario Tamriel del usuario ya cuadran entre sí (33 regiones «X 2» en los dos). A sus escenarios Tamriel y Probando3 se les corrigió `strSpriteMapName` (→ World; copia de los scenario.xml anteriores en el scratchpad de la sesión).
- **Turov (belarus.geojson)**: el arreglo de la tolerancia está en `tools/editor_core.py` desde el 22-10 08:01; el `MHEditor.zip` de `release/` es de las 07:58 y no lo lleva: hay que regenerar el exe (`python tools/build_exe.py`) o usar `Region Editor.bat`.

## Instrucciones 8 (editor de regiones)
- **Dueño cambiado sin motivo (Rostov → Donetsk-Luhansk; antes Syria/Palmyra)**: «Adecuar» solo aplicaba los renombres anotados en el changelog. Un RegionRename de map.xml sin anotar (Rostov → Rostov Oblast) hacía que la región se quitara y se volviera a crear desde la vecina con más frontera (Donetska), con su dueño y su población. Ahora también se aplican los RegionRename de map.xml (`PackMap.renames`).
- **Guardar / Instalar con escenarios con cambios sin guardar**: antes se saltaba el registro de la región nueva en ese escenario (y quedaba sin cuadrar con el mapa). Ahora se pregunta si guardarlos antes (`savePendingScen`).
- **Tierra importada como mar** (Probando3: las regiones de Tamriel salieron todas de mar): la detección «el contorno cae sobre el mar del mapa» contaba el «World Ocean» de relleno que cubre todo el mundo; ya no lo cuenta, y el tipo que da el GeoJSON (preset) manda sobre el «solo sobre mar». Probado: tierra → tierra, mar → mar.
- **Limpiar trozos sueltos…** (panel de la región): encuentra exclaves diminutos, tiras de dos nodos y restos de geometría imperfecta y los pasa a la vecina con más borde (se aplica al Guardar). Probado en copia: Polissia 8 trozos, Forecaucasia 2 (incluido uno de 7e-9 grados²).
- **Restar lt.json de Wilno / malla de Polissia**: las migas de menos de 1e-8 grados² que deja un contorno al rozar fronteras ya no se traspasan (creaban pellizcos). Probado: se guarda.
- **Importar**: por defecto los exclaves los absorben las vecinas.
- Casilla **Regiones nuevas** (naranja) a la derecha de «Controlador». Al pasar el cursor se ve el nombre del juego si no es el interno (texto del stringTable o RegionRename). **Renombrar** pregunta además si cambiar el código SID. Más mensajes del servidor traducidos al inglés.
- Pendiente: tras «Dibujar», ofrecer las mismas opciones que tras «Recortar»; convertir zonas vacías en tierra o mar ya se puede seleccionando el hueco («Crear una región nueva aquí…» con tipo tierra/mar).
