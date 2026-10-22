# Formato del mapa de Making History: The Calm and The Storm

Carpeta: `Modern Europe\system\DisplayLibraries\Maps\World\xml\`
Todos los binarios son little-endian; las coordenadas son float32 en grados (x = longitud, y = latitud).
`map.xml` declara los tres archivos (`fileRegionData`, `fileTriShapeGroup`, `fileBorders`) y los límites del mundo (-180..180, -90..105, `bWrapX`).

Estado: **lectura y escritura verificadas**. `tools/roundtrip.py` lee los tres archivos, los vuelve a
escribir y los compara: **los tres salen idénticos byte a byte**.

Herramientas (`tools/`):
- `mhmap.py`: librería lector/escritor (`load_map`, `save_map`, `encode_map`, `region_shapes`).
- `roundtrip.py <carpeta xml>`: prueba de ida y vuelta + coherencia entre archivos. No escribe nada.
- `export_map.py <carpeta xml> <salida>`: `regions.geojson`, `borders.geojson`, `mapa_mundo.png`, `mapa_europa.png`.
- `parse_regions.py`: exporta `regions.csv` (nombre, tipo, centro, vecinos).

Resultados en `mapa/`. Los GeoJSON se abren en QGIS o geojson.io.

## regions.bin — lógica de regiones (251 KB)

```
u32 nRegiones                       (852)
por región:
  u32 tipo    (0 = mar: 274; 1..4 = tierra: 210 / 191 / 42 / 135)   CRegionMapData::GetRegionType
  u32 a, u32 b                      área de tierra y área total (GetLandArea / GetTotalArea; en el mar a = 0)
  u32 len, char[len] nombre
  u32 0, f32 centroX, f32 centroY, u32 0
  u32 nVecinos, u32 vecino[nVecinos] índice de región
  u32 nPuntos, (f32 x, f32 y)[nPuntos]  posiciones de movimiento (GetMoveLocation): rejilla de ~0.113° dentro de la región
```
- Adyacencias simétricas en el 100% de los casos (0 asimétricas).
- 69 regiones (islas o regiones en varios trozos) se listan a sí mismas como vecinas; no tienen borde.
- Ej.: Crimea (34.13, 45.17) → Kherson, Eastern Black Sea, Western Black Sea, Sea of Azov.
- El índice de región (0..851) es el que usan `borders.brd` y los vecinos.

## borders.brd — líneas de frontera (1.1 MB)

```
u32 nBordes                         (2405)
por borde:
  u32 nTramos
  por tramo: u8 flag (0/1), u32 nPuntos, (f32 x, f32 y)[nPuntos]
  u32 m (=1), (f32 x, f32 y)[m]     punto de referencia
sección final (región → bordes):
  u32 nRegiones (852)
  por región: u32 índice, u32 ?, u32 k, (u32 vecino, u32 índiceBorde)[k]
```
- Cada par de regiones vecinas tiene exactamente un borde; los 2405 se usan.
- Flag: 1 = línea de costa (solo en bordes tierra–mar); 0 = el resto.
- **Reglas que el juego necesita** (comprobadas en el original; romperlas produce líneas que salen
  disparadas hacia (0,0) y contornos de selección cortados):
  - cada borde es **exactamente** la cadena de aristas que comparten las mallas de sus dos regiones;
  - todos sus puntos son vértices de la malla, **bit a bit**, y las mallas vecinas no tienen uniones en T;
  - no hay pasos de longitud cero (dos puntos seguidos iguales);
  - un anillo cerrado (isla) se guarda sin repetir el primer punto.
  `tools/check_map.py <original> <nuevo> [regiones]` comprueba todo esto.

## regions.nts — malla 3D de las regiones (12.4 MB)

Según `CRegionTriShapes` (ver REVERSING_NOTAS.md), cada región tiene tres mallas: **display** (la que se dibuja), **picking** y
**selection** (zona de clic). Tabla final `(región, selección, dibujo, picking)`: en las islas la de dibujo es la isla y las otras
dos el halo.


```
u32 nShapes                         (921)
por shape:
  u32 0xD00D1337 (magic), u32 0, u32 nVert
  vértice: f32 x, f32 y, f32 z(0), f32 nx(0), f32 ny(0), f32 nz(1)   (24 bytes)
  u32 nIndices, u32 indice[nIndices]   (lista de triángulos)
sección final (región → shapes):
  u32 nRegiones (852)
  por región: u32 región, u32 last (copia), u32 first, u32 last   → shapes first..last
```
- Los 921 shapes quedan cubiertos por la tabla, sin repetir. 69 regiones tienen más de un shape.
- La malla repite vértices en la misma posición: al calcular contornos hay que unir por coordenada.
- Total: 343.267 vértices, 340.784 triángulos.

## Texturas del terreno (art\OperationalTerrain)
- `OperationalTerrain-CC-RR.tga`: **DXT5 (BC3) en bruto, sin cabecera**, pese a la extensión.
  1024×1024 (1 MB) y mipmaps `-01`..`-04` (512 → 64). Alfa siempre 255.
- 24 columnas × 13 filas de 15°: columna CC desde -180° de longitud, fila RR desde +105° de latitud hacia el sur.
- **Las fronteras están pintadas en estas texturas** (línea gris oscura ~(47,46,45), unos 4 px a 1024).
  Al mover un borde hay que repintarlas: `tools/fix_texture.py` borra la línea vieja, pinta la nueva
  y recomprime solo los bloques 4×4 que cambian (tile y mipmaps).
- Pillow las lee con `Image.frombytes('RGBA', (n, n), data, 'bcn', 3)` y las escribe guardando como DDS `DXT5`.

## Otros
- `art\`: `MiniMap.tga`, `StrategicTerrain.nif` (vista estratégica, sin revisar).
- `map.xml` ya permite **renombrar** regiones sin tocar binarios (`RegionRename`).

## Qué haría falta para modificar fronteras
1. ~~Escritor de los tres formatos con prueba de ida y vuelta~~ **hecho**.
2. Mover un borde entre dos regiones existentes: cambiar el contorno en `regions.bin`, la polilínea en `borders.brd` y re-triangular el shape en `regions.nts`. El número de regiones no cambia.
3. Crear regiones nuevas: además, añadir índice, vecinos y bordes, y el objeto `Region` en cada escenario.

## Cambios aplicados al juego

### Campo de Hielo Sur → Chile
- Herramienta: `tools/move_border.py` con `hielo_sur.kml`, línea "Traza en base a los hitos de 1898".
- Patagonia → Magallanes, lado oeste de la línea: 744 triángulos, unos 0,22 grados² (≈ 1.700 km²).
- Cambian `regions.nts` (shapes 360 y 369), `borders.brd` (borde 699, incluido el cierre horizontal
  al norte del cerro Huemul) y la textura `OperationalTerrain-07-10` con sus 4 mipmaps
  (178 bloques de 65.536 en el tile). `regions.bin` no cambia.
- Comprobado: sin solapamiento, área total igual, la frontera cubre todo el borde común de las dos mallas.
- Probado en el juego (primera versión): el color y la selección cambian. Quedaba la línea vieja pintada en la textura.
- Imágenes: `mapa/hielo_sur_antes_despues.png`, `mapa_mod/OperationalTerrain/preview_textura.png`.
- Originales en `backup/mapa_original/`. Para deshacer, copiar los tres binarios a
  `...\Maps\World\xml\` y los 5 `.tga` de `backup/mapa_original/OperationalTerrain/` a
  `...\Maps\World\art\OperationalTerrain\`.
- El mapa es común a todos los escenarios: el cambio se ve en todos.

### Frontera de Chile según Wikimedia Commons (sustituye al cambio del Campo de Hielo Sur)
- Fuente: `datos/chile.map.json` = [Data:Chile.map](https://commons.wikimedia.org/wiki/Data:Chile.map) (CC0, dataset geo-countries / Natural Earth).
- Herramientas: `tools/fit_country.py` (mallas, bordes, vecindades, islas) y `tools/paint_changes.py` (texturas).
  Se parte del mapa ORIGINAL (`backup/mapa_original`), no del cambio anterior.
  ```
  python fit_country.py ../backup/mapa_original ../datos/chile.map.json ../mapa_chile2 --regions Magallanes Coquimbo Atacama --island Coquimbo --island-south Magallanes:-52
  python paint_changes.py ../mapa_chile2/cambios.json "<art>/OperationalTerrain" ../mapa_chile2/OperationalTerrain --originals ../backup/mapa_original/OperationalTerrain
  python -I check_map.py ../backup/mapa_original ../mapa_chile2 Magallanes Coquimbo Atacama
  ```
- Costa del juego intacta: solo se mueven trozos que tocan a un vecino terrestre (427 piezas, 1,18 grados²);
  1.203 diferencias de costa se ignoran. No se mueven trozos costeros que darían a una región costa sobre un
  mar que antes no tocaba (Arica: la frontera llega recta al mar en el punto original).
- Vecinos ajustados: Patagonia, Cuyo, Andean Northwest, Bolivia, Southern Peru.
- Islas añadidas (eran mar): Rapa Nui (Gomez Ridge), Juan Fernández ×2 (Chile Rise), Desventuradas ×2
  (Nazca Ridge) → Coquimbo; Diego Ramírez (Drake Passage) → Magallanes. Sala y Gómez no (< 1 km²).
- Vecindades nuevas (bordes 2405–2407): Coquimbo–Nazca Ridge, Coquimbo–Chile Rise, Coquimbo–Gomez Ridge.
- Versión 1 (`mapa_chile/`) tenía bordes fragmentados con 109 pasos de longitud cero → líneas hacia (0,0)
  y contornos cortados en el juego. Versión 2 (`mapa_chile2/`, instalada) regenera los bordes desde las
  aristas compartidas de mallas con vértices exactos y sin uniones en T: 0 pasos de longitud cero,
  37 bordes cambiados, todos idénticos a sus aristas compartidas.
- Comprobado: área total igual, solapamiento máximo 2,5e-9 grados².
- Texturas: tiles 04-08, 06-08, 06-09 (islas), 07-08, 07-09, 07-10 (fronteras) y sus mipmaps.
  Línea: núcleo (26,18,10), 3 px + difuminado 1 px (medido sobre las originales); borrado de 13 px.
- Originales de todo lo tocado: `backup/mapa_original/` (3 binarios) y `backup/mapa_original/OperationalTerrain/` (30 tga).
- Vistas: `mapa_chile2/prev_norte.png`, `prev_sur.png`, `prev_arica.png`; `mapa_chile/prev_pascua.png`.
- Probado en el juego (versión 1): islas seleccionables (Pascua → Coquimbo, Diego Ramírez → Magallanes) y
  vecindades navales funcionan. Versión 2 pendiente de probar.

### Límite oriental del estrecho de Magallanes (sobre la versión 2 de Chile)
- Pasos (cada uno con su `paint_changes.py` encadenando `--originals` del paso anterior):
  1. `tools/straighten_meridian.py ../mapa_chile2 ../mapa_chile2b Magallanes Patagonia -52.63`: el meridiano
     68°36' de Tierra del Fuego (-68.6064) sigue recto hasta la costa (antes hacía un gancho al oeste).
  2. `tools/strait_limit.py ../mapa_chile2b ../mapa_chile3`.
- Recta entre los vértices exactos donde se juntan Patagonia, Magallanes y Argentine Sea:
  Punta Dungeness (-68.4185, -52.3704) y Cabo del Espíritu Santo, donde el meridiano toca la costa (-68.6064, -52.6530).
- Argentine Sea al oeste de la recta → Strait of Magellan (0,339 grados²; antes llegaba hasta la Primera Angostura).
- Franja de 0,012° de costa de Patagonia sobre esas aguas → Magallanes (0,001 grados²), para que Argentina
  no toque el estrecho.
- Vecindad eliminada: Magallanes–Argentine Sea (el borde se quita y los posteriores se renumeran; total 2.407).
- Textura 07-10: borrada la línea de la Primera Angostura, pintada la recta (líneas de mar: núcleo (3,14,42)).
- `tools/transfer.py`: el proceso común (recorte, vértices exactos, uniones en T, bordes, vecindades nuevas
  y eliminadas) que usan `fit_country.py` y `strait_limit.py`.

## Paquete del mod
- `mods/Chile Fixes/` y `mods/Chile Fixes 1.0.zip` (12,4 MB, 69 archivos): `mod/` (33 archivos instalados),
  `originales/` (los mismos 33 sin modificar), `LEEME.txt`, `instalar.bat`, `desinstalar.bat`.
- Corresponde al estado instalado = `mapa_chile3` + texturas de `mapa_chile3/OperationalTerrain` y anteriores.

### `u_flag` de regions.bin (corregido)
No es «siempre 0»: **1 en todas las regiones de mar**, 2 en algunas islas y 0 en el resto de la tierra (World original: 274 mares con 1; 69 tierras con 2; ninguna tierra con 1). Una región de mar con 0 sale **roja** en el juego y lo **cierra** al hacer clic (caso Caspian Sea en WorldModern, 2026-10-21). El editor escribe ahora 1 en todo mar y nunca 1 en tierra (`mhmap.write_regions_bin`, `new_region.create_region`).

### Sentido de los triángulos de regions.nts
Todos los triángulos del World original están en **sentido antihorario** (con la normal (0,0,1)). Con triángulos horarios el juego no dibuja la región ni deja seleccionarla
(caso Probando3, 2026-10-22). `new_region.normalize_map` lo corrige; Instalar lo aplica siempre.
