# Ingeniería inversa de Making History (MH1 2.0.4)

Análisis estático de `bin\` sin ejecutar nada. REA no tiene motor de desensamblado en Windows (rizin/objdump no corren
y el análisis profundo pide Ghidra 12.1 + JDK 21, no instalados), así que se usó `tools/pe_info.py` (lector PE propio):
exportaciones con nombres C++ (MSVC), importaciones, cadenas y tablas de textos. Textos del editor oficial en
`docs_texto/ed_textos.txt`.

## Arquitectura
| Binario | Qué es |
|---|---|
| `makehist.exe` | Lanzador del juego: carga `program.dll` y `logger.dll` (sin lógica propia, 0 exportaciones). |
| `game.dll` (14 914 funciones exportadas) | Núcleo: `CGame`, `CCountry`, `CRegion`, `CRegionMapData`, `CScenario`, `CAllianceManager`, `CWar`, IA (`CAIData`, `CHLP*`, `CPLP*`), comercio, investigación. |
| `moderneurope.dll` (4 105) | Reglas del paquete «Modern Europe»: unidades (`CUnit`), órdenes, eventos (`CAct…`). |
| `objectcore.dll` (2 725) | Sistema de objetos y XML: espacios de nombres, `fromFile`, definiciones (`gameDefs.xml`). |
| `graphics.dll`, `ui.dll`, `meui.dll` | Mapa 3D (`CRegionMap`, `CRegionMapBorderSet`, `CRegionTriShapes`), interfaz y capas del mapa. |
| `terraintoolkit.dll` + `console.exe` | **Herramientas internas para construir el mapa**: `MakeMap`, `BuildMesh`, `BuildRegionData`, `ExtractRegions`, `ValidateMesh`, `GenerateMiniMap`, `GenerateTerrainImage`, `RasterizePolygons`… con un `MapOptions.xml`. Es lo que usó el estudio para generar `regions.bin`/`borders.brd`/`regions.nts` desde polígonos y capas. |
| `ed.exe` + `EditorStringTable.dll` | Editor oficial (MFC): diálogos `CDlgEdit…` con `ValidateChanges` y 373 textos (reglas de validación). |
| `logger.dll` | Registro: todo va a **`OutputDebugString`** (no escribe archivo). |

## Registro del juego
Los avisos internos («invalid region ID %d for region %s», «Failed to load scenario named %s»…) solo se ven con un
capturador del canal de depuración de Windows. `tools/game_log.py` («Game Log.bat») los guarda en
`logs/juego_<fecha>.log`: abrirlo, lanzar el juego, reproducir el fallo y cerrarlo. Es la forma de saber por qué un
escenario no carga («Error creating local game»).

## Mapa (confirmado por nombres de funciones y mensajes)
- `regions.bin` = `CRegionMapData`: nombre, **tipo de región** (`GetRegionType`; 0 = mar), los dos números iguales son
  **área de tierra** y **área total** (`GetLandArea`/`GetTotalArea`; en el mar la de tierra es 0), centro (`GetLocation`),
  vecinos, y la lista de puntos son las **posiciones de movimiento** (`GetMoveLocation`, generadas con un muestreador
  desde «semillas»: `CMoveLocationSeedSet`). Existe además `IsImpassable` (el indicador siempre 0 del mapa original).
- `regions.nts` = `CRegionTriShapes`: cada región tiene tres mallas: **display** (se dibuja), **picking** y **selection**
  (zona de clic). En 783 regiones son la misma; en las 69 islas la de dibujo es la isla y las otras dos el «halo».
  Tabla: `(región, selección, dibujo, picking)` (selección = picking).
- `borders.brd` = `CRegionMapBorderSet`: bordes por par de regiones.

## Escenarios
- El juego **solo carga los `country*.xml`/`player*.xml` listados en `game.xml`** (`fromFile=`). Los demás se ignoran
  (en The Modern World: Daghestan, Kingdom of Jerusalem, Salvador, Swaziland). Para añadir una nación hay que
  registrarla también en `game.xml`.
- En los escenarios del juego hay flotas atracadas en regiones de tierra con puerto (sin `vecPosition`) y ejércitos en
  regiones de mar (transportados); ambos son válidos.
- Los países rendidos de los escenarios del juego **sí** tienen `strCapital` (aunque el texto de ed.exe diga «Surrendered
  nations must not have a capital»): necesario para poder liberarlos.

## Reglas del editor oficial incorporadas al validador
Guerra con atacante = defensor, entre miembros de la misma alianza, repetida o con un país no registrado en la partida;
unidades con 0 efectivos; países y plantillas de unidad con nombre repetido; archivos de país que `game.xml` no carga.
Con esto los 8 escenarios originales validan **sin errores**.

## Siguiente nivel
Para decompilar funciones concretas (p. ej. `CScenario::LoadMapData`, `CRegionMapData::ReadFromStream`) hace falta
Ghidra 12.1 + un JDK 21 de 64 bits (~600 MB en total) y apuntar `GHIDRA_INSTALL_DIR`; REA lo usa automáticamente.
