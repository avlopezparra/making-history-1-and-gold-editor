# Making History Gold frente a MH1 (primer vistazo, 15/10/2026)

Carpeta: `C:\Program Files (x86)\Steam\steamapps\common\Making History Gold` (misma estructura que MH1).

- **Programas**: las 30 DLL/EXE de `bin\` son distintas (otra compilación del motor).
- **Definiciones del motor** distintas: `system\game\accessorDefs.xml`, `actionDefs.xml`, `gameDefs.xml`, `playEventDefs.xml`;
  `Modern Europe\system\game\actionDefs.xml`, `dataProfiles.xml`, `ModernEuropeDefs.xml` (comparar qué tipos/propiedades añade Gold).
- **Mapa World**: `regions.bin`, `borders.brd` y `regions.nts` son **idénticos byte a byte al MH1 original**
  (`backup/mapa_original`); `map.xml` igual salvo espacios. `tools/roundtrip.py` lo lee y reescribe idéntico.
  → los binarios de Chile Fixes valen para Gold.
- **Texturas del terreno**: las 30 que toca Chile Fixes son **distintas** en Gold (otro arte). Para Gold hay que
  repintar las fronteras con `paint_changes.py` sobre las texturas de Gold, no copiar las de MH1.
- **Escenarios**: Gold trae los 7 de MH1 (con 13–20 archivos cambiados cada uno) y 4 nuevos: Blitzkrieg,
  Clash of Continents, Rise of the Reich, Southern Star. No trae The Modern World (es del usuario).
- **ScenarioDefaults** distintos: sharedData.xml, sharedDataFactories.xml, sharedDataResearch.xml,
  sharedDataUnitTemplates.xml, sharedDataUnitTemplateSprites.xml, scenarioDefs.xml; solo en Gold: namespace.xml,
  sharedDataROTR.xml.
- **SpriteMaps** (DisplayLibraries) distintos: MKDKeySet, MKDTable, MKDTableCountryAliasesAir, MKDTableTemplateAliases*.
- Interfaz: cambios en `system\ui\art\2D`, `Modern Europe\system\UI\Lobbies` y 68 archivos nuevos en `Modern Europe\system\UI\art`.
- Gold no trae `system\locale\esp` (solo inglés).

## Hecho (21/10/2026)
- **Texturas**: las de Gold son las de MH1 con otro color, píxel a píxel (tabla de color con error medio < 1/255).
  `tools/port_tiles.py` traslada cambios de texturas de MH1 a Gold; `tools/port_regionpack.py` copia un regionpack
  (binarios de MH1 + texturas de Gold con los cambios trasladados). `tools/game_palette.py`: el editor de mapa muestra
  las texturas con la paleta del juego del escenario abierto (`/tile/...?pal=gold`).
- **Unidades**: Gold añade `nLandDefenseHitPercent` a todas las de tierra y cambia golpes/velocidades; unidades nuevas con
  sus `ResearchProjFactoryOutput` y `FactoryOutputUnit`; `LightBombers`/`BattleCruisers`/`ElectricDieselSubmarines`
  pasan a requerir `EarlyBombers`/`EarlyCruisers`/`EarlySubmarines`. Partisans de serie (`CombatSystemParams`
  `nBasePartisanPercent`, `strPartisanUnitType`). Las tablas MKD de sprites del escenario (`DisplayLibraries\`) también cambian.
- **Economía**: Gold rebalancea `sharedData.xml` (TransportationLevel nCost 1M fijo, mantenimiento la mitad, nSteps 5–25…),
  `sharedDataFactories.xml` y puntos de investigación.
- **Colores**: los 91 colores de MH1 de los escenarios oficiales tienen cada uno su color de Gold (tabla); para otros, ajuste lineal.
- **Conversor** `tools/convert_scenario.py` (botón «Exportar a Gold…/MH1…» del editor de escenarios): fusión a tres bandas
  (`tools/xmlmerge.py`) de los sharedData*.xml y MKD*.xml, escalado de las unidades nuevas como el escenario (p. ej. ÷10),
  investigación inicial, partisanos, colores, infraestructura (auto), y «sin imágenes» (no copia `ui\`).
- **Detección MH1/Gold** (`gamepaths.scenario_game`): por el contenido de su sharedDataUnitTemplates.xml (nLandDefenseHitPercent
  o unidades exclusivas de Gold); sin archivo propio, el juego donde está. Iconos de GameBanana en `tools/editor/icon_*.png`.
- **The Modern World** convertido en `Making History Gold\...\scenarios\The Modern World` (sin imágenes, 18 MB) con el regionpack
  `WorldModern` trasladado a Gold. Validación: los mismos avisos que el original de MH1. Falta probarlo en el juego.
- **Chile Fixes 1.2**: `mod_gold` / `originales_gold` e instalador para los dos juegos.
