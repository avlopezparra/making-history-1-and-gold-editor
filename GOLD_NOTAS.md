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


## Cambio de idioma (MH1 / Gold) — causa y arreglo

**Causa**: los `.reg` escriben en `HKLM\SOFTWARE\WOW6432Node\Muzzy Lane Software\<Making History 2.0 | Making History Gold>` (valor `locale`/`Locale`, `en`/`esp`/`ru`/`de`). Pero existe una copia en `HKCU\Software\Classes\VirtualStore\MACHINE\SOFTWARE\WOW6432Node\Muzzy Lane Software\<misma clave>` con `Locale=en`. El juego (32 bits, sin admin) lee a traves de la virtualizacion de registro y la copia de VirtualStore gana sobre HKLM, asi que cambiar HKLM ya no tiene efecto (HKLM MH1 = `esp`, Gold = `de`, el juego sigue en `en`; los logs muestran `locale/en/...`).
Los `.reg` dejaron de funcionar porque la clave VirtualStore se creo despues (al guardar el juego algun valor sin admin) y la sombrea.

**Arreglo**: cambiar `Locale` en VirtualStore (HKCU, no requiere admin), o borrar el valor `Locale` de VirtualStore para que se use HKLM.
- MH1: `reg add "HKCU\Software\Classes\VirtualStore\MACHINE\SOFTWARE\WOW6432Node\Muzzy Lane Software\Making History 2.0" /v Locale /t REG_SZ /d esp /f`
- Gold: igual con `Making History Gold` y `/d de|en|ru|esp`.
Idiomas disponibles: carpetas en `system\locale` (en, esp, ru).

### Actualizacion (pruebas)
El arreglo de VirtualStore **no funciono**: con VirtualStore=esp (y HKLM=esp) el log sigue en `locale/en`; con un valor centinela `zz` tambien `en` (el juego no lee esas claves, o cae a `en`). Se restauro VirtualStore a `en` (backup: `backup_virtualstore_MH1.reg`).
Pistas: no hay cadena `locale` ni ruta de registro en `bin\*.dll/exe` (salvo MFC/apatch genericas). Steam guarda idioma por juego en `appmanifest_*.acf` / `localconfig.vdf`: MH1 = `english`, Gold = `german`, MH2 = `english`. Hipotesis pendiente: el idioma sale del idioma de Steam del juego (Propiedades > Idioma) o de otro mecanismo; falta probar y/o trazar el acceso a registro (Procmon).

### Traza Procmon (MH1, 2026-10-22)
`makehist.exe` lee `HKCU\Software\Classes\VirtualStore\MACHINE\SOFTWARE\WOW6432Node\Muzzy Lane Software\Making History 2.0\Locale` (primero prueba `HKCU\Software\Muzzy Lane Software\Making History 2.0`, que no existe; HKLM ni se consulta porque VirtualStore ya tiene el valor). Aun con `Locale=esp` ahi (y sin que nadie lo reescriba), el log sigue en `locale/en`, y `locale\esp` esta completo. Conclusion: el valor del registro se lee pero otra cosa lo anula (idioma de Steam del juego = `english`, u otra comprobacion interna). Pendiente: probar idioma de Steam para MH1 / analizar game.dll con rea. Procmon en `tools_ext/procmon` (Procmon64.exe, firmado por Microsoft).

### Hallazgos del analisis (rea/capstone/Procmon)
- `program.dll` (CProgram::Init) lee `Locale` con CMLRegistryValue (HKLM→VirtualStore), lo valida con `CObjectManager::LocaleExists` (siempre true) y lo pasa a `CObjectManager::Init(locale)` (objectcore.dll). `utility.dll` acepta ru/de/fr/ita/esp/en. Tambien existe override por ini (`SharedConfig` en la clave del registro; no existe aqui).
- Procmon: el juego leyo `Locale=en` de VirtualStore mientras mi consola ya mostraba `esp` => **mis `reg add` desde la herramienta sandbox no llegaron al registro real** (vista virtualizada). Hay que escribir fuera del sandbox / con el `.reg` doble clic del usuario. Pendiente verificar con el juego.

### CAUSA REAL de que mis cambios no tuvieran efecto (importante para el editor)
Procmon mostro que el `reg.exe` lanzado desde la herramienta de Claude escribe en `\REGISTRY\WC\Silo...` (contenedor de la app), no en el registro real: el juego seguia leyendo `Locale=en`. Solo vale escribir desde un proceso fuera del contenedor (doble clic en un `.reg`, o `Start-Process ... -Verb RunAs`). Escritura elevada hecha el 2026-10-22 13:2x: VirtualStore MH1 `Locale=esp`; pendiente confirmar con el juego. Para el editor: escribir `HKCU\Software\Classes\VirtualStore\MACHINE\SOFTWARE\WOW6432Node\Muzzy Lane Software\<Making History 2.0|Making History Gold>\Locale` (y de paso HKLM si hay admin).

## RESUELTO — cambio de idioma MH1/Gold (2026-10-22)
- **Causa**: el juego lee `Locale` de `HKCU\Software\Classes\VirtualStore\MACHINE\SOFTWARE\WOW6432Node\Muzzy Lane Software\<Making History 2.0 | Making History Gold>` (la copia virtualizada gana sobre HKLM). Los `.reg` del juego escriben en HKLM, por eso ya no surten efecto desde que existe la copia en VirtualStore (con `Locale=en`).
- **Arreglo verificado**: poner `Locale=esp` en esa clave de VirtualStore (doble clic en `Idioma MH1 - Espanol (VirtualStore).reg`); log `juego_20261022-132644.log` => `locale/esp/...`.
- **Herramienta**: `python tools/idioma_juego.py` (lista), `python tools/idioma_juego.py mh1 esp` / `gold de`. Ejecutar en una terminal NORMAL del usuario: el `reg`/python lanzado desde la app de Claude escribe en un registro privado (`\REGISTRY\WC\Silo...`) y no tiene efecto, ni siquiera elevado.
- Valores validos: carpetas de `system\locale` (MH1: en, esp, ru; Gold: de, en, jp, ru). Gold (clave `Making History Gold`) no se probo con el juego.
- Falta (opcional): boton en el editor que llame a `idioma_juego.cambiar`.

## Conversor MH1 → Gold: arreglos (28/10/2026)
- Investigación: si un proyecto es `bCompletedByDefault`, sus requisitos nuevos de Gold (EarlyBombers/EarlyCruisers/EarlySubmarines)
  también deben serlo, o ningún país inicia («didn't ever have their pre-reqs met»). `fix_default_prereqs`.
- `UnitUpgrade.nLandHitBonusPct` (MH1) → `nLandAttackHitBonusPct` + `nLandDefenseHitBonusPct` (Gold, mismo valor). `fix_unit_upgrades`.
- Opción «Regionpack (mapa)» en el diálogo de conversión (usa `port_regionpack.py`). Copiar a mano un regionpack de MH1 a Gold
  falla en `InitGameValidateRegions`.
- Probado en el juego: «Deadlock - The Great War» convertido a Gold carga y funciona.

## Japones (Gold, locale jp) — texto invisible
- Los `stringTable*.xml` de `locale\jp` estan bien (UTF-8, kana/kanji reales).
- Causa probable: `bin\fonts.dll` (FreeType) solo escanea `*.ttf` (log: `Looking for fonts using string "C:\WINDOWS\Fonts\*.ttf"`) y la UI pide Arial / Century Gothic (`strFontFace`), sin glifos CJK; las fuentes japonesas de Windows son `.ttc` (msgothic, YuGoth) y nunca se cargan. La version japonesa original seguramente traia/configuraba otra fuente.
- Arreglo propuesto: `tools/fuente_jp.py` genera `fuentes_jp/*.ttf` (MS Gothic renombrada como Arial, Century Gothic, Bodoni MT, Courier New) y se anade a `Making History Gold\Options\options.xml` dentro de `SystemOptions`: `<property name="strFontDirs" value="...\fuentes_jp"/>` (+ quiza `C:\WINDOWS\Fonts`). PENDIENTE de probar.
