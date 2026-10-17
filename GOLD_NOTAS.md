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

Pendiente (sesión «Soporte para Making History Gold»): detalle de las definiciones del motor, unidades nuevas,
colores, costes de infraestructura, conversor de escenarios MH1↔Gold, exportar a Gold desde el editor e identificar
escenarios MH1/Gold con los iconos de GameBanana (Gold: https://images.gamebanana.com/img/ico/ModCategory/5e933a6fd0cd2.png,
MH1: https://images.gamebanana.com/img/ico/ModCategory/5e933e39235bc.png).
