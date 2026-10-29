# Estructura de un escenario (para el futuro editor de escenarios tipo ed.exe)
Carpeta: Modern Europe\system\scenarios\<escenario>\
- scenario.xml: fechas (dateStart, dateEnd, nScenarioDuration, nTurnDuration, nStartYear) y lista de sharedData.
- scenarioInfo.xml: ScenarioInfo (nombre, descripcion, paises jugables).
- game.xml: GO fromFile -> cada countryX.xml / playerX.xml / treaties.xml / waterWorld.xml; WorldMarket con Flow (objAidFlows; Trade Flows = objTradeFlows, vacio en TMW) y ResourceTrade.
- gamestate.xml: Player (strName, colCountryColor, bNonPlayable...), Alliance/AllianceMember, War (atacante/defensor por pais y alianza).
- treaties.xml: Treaty + MilAccessTerm (accesos militares).
- eCountryType solo admite COUNTRYTYPE_PLAYABLE / _FEATURED / _NON_FEATURED (MINOR o MAJOR = «Error creating game»). Todo sid* de un Player
  (p. ej. sidShortDescription) debe existir en un stringTable aunque su texto esté vacío; si no, la partida tampoco se crea.
- DipRelInitialValue solo vale dentro de MEPlayerData > DipRelInitialValueList; suelto en MEPlayerData el juego descarta el player*.xml
  («there wasn't a PlayerData named that», InitGameValidateCountries). strMapName debe ser una carpeta de DisplayLibraries/Maps con xml/map.xml.
- ResearchProjectInitRef RESEARCH_COMPLETED: cada requisito (ResearchProjectPreReq, sharedDataResearch.xml) debe estar también
  completado o tener bCompletedByDefault=true; si no, «pre-reqs never met» → InitGameOld falla. Los árboles cambian entre escenarios.
- countryX.xml: MECountry (gobierno, capital, eCountryType, bSurrendered, nTransportCredits, CultureSet) con
  Region (strOwner, strController, terreno, cultura, poblacion, infraestructura, fortificacion, agricultura)
  > City (vecPosition, strPortForRegion, strInitialWorkOrder, Factory nIPUs/nTechLevel) y Producer (recurso, produccion);
  Army/AirForce/Fleet (strRegion, vecPosition, UnitSummary strName/nNumber).
  REGLA: en los 8 escenarios las 4.625 regiones estan en el archivo de su propietario -> cambiar dueno = mover el bloque.
- playerX.xml: MEPlayerData (IA: nAggressiveNature..., diplomacia inicial DipRelInitialValue, investigacion ResearchProjectInitRef).
- waterWorld.xml: 274 regiones de mar.
- sharedDataUnitTemplates.xml (UnitTemplate x47), sharedDataFactories.xml (FactoryOutput*), sharedDataResearch.xml (ResearchProj*).
- Textos SID: system\locale\<idioma>\stringTableGame.xml y <escenario>\game\stringTable.xml.

# Eventos, decisiones e IA (análisis de DH Axis Diplomacy, TMW Reloaded, Deadlock, 1836 ACU, World Aflame; MH1. Gold no trae estos mods)
Definiciones del motor: `system/game/actionDefs.xml` (+ `Modern Europe/system/game/actionDefs.xml`), `brainDefs.xml`, `goalDefs.xml`, `gameDefs.xml`.

## Cadena de un evento con ventana en el juego
1. **ScriptedEventDef** (`strTypeLabel`): quién (`PlayerGenNames strName=País` o `PlayerGenAll`), disparador `objTriggerEval`:
   `TriggerEvalRandomChance nPercentChance` (cada turno), `TriggerEvalUntilTurn nTurn`, `TriggerEvalUntilAnsweredPlayerDecision strDecisionType`
   (se repite hasta que se responde esa decisión). Dentro, condiciones `AccessorRuleSet` (todas deben cumplirse) = accesores
   (`AccessorGetCountry`, `AccessorGetRegion`, `AccessorIsAtWar`, `AccessorIsAllied`, `AccessorGetAllCountryWars`, `AccessorGetCurrentDate/Turn`…)
   + `RuleDefExpression expRession` (`exists(...)`, `!...bSurrendered`, `region.nOwnerID == country.nCountryID`, `dateGameDate GTE MM/DD/AAAA`, `sizeOf(wars) LTE 0`).
   Efectos opcionales `CustomEffectDefActions objEffects` (sin ventana).
2. **PlayerDecisionTrigPlayEvent**: `otPlayEventType` (PlayEventNewScriptedEvent, PlayEventConqueredRegion…) + condición
   `scratch.objScriptEvent.strTypeLabel == '<evento>'` → `strTypeToTrigger` = decisión.
3. **PlayerDecisionDef** = la ventana: `ArgumentList "Display Data"` con `strTitle`/`strDesc` (texto literal o `computeFrom=getString(SID…)`);
   elecciones `PlayerDecisionChoiceDefCustom strLabel` con su `strTitle`/`strDesc`/`strEffect` y sus `CustomEffectDefActions objChoiceEffects`.
   `strDefaultChoice` + `nDefaultChoicePercent` = lo que elige la IA; `strDefaultChoicePlayer` = defecto del humano. Noticias con solo «OK» = una elección.
- Totales en los 5 mods: 457 ScriptedEventDef, 486 triggers, 458 decisiones, 917 elecciones, 85 DecisionPointDef.

## Acciones (efectos) útiles — todas existen en el motor
| Acción | Propiedades | Uso |
|---|---|---|
| ActProposeDeclareWar | strFromCountry, strToCountry | declarar guerra |
| ActSetTradeRelations | strCountry, eTradeRelations (NEUTRAL/FAVORED/SANCTIONED/EMBARGOED) | embargo; lo ejecuta el jugador del evento (PlayerGenNames). Ningún mod lo usa: probar en el juego |
| ActSetCountryGov | strCountry, strGovType | cambiar ideología |
| ActIncResourceStock | strCountry, strResource, nIncrement | ayuda de recursos (también ActAddAidFlow/ActAddToAidFlow con ResourceTrade) |
| ActGrantIndependence | strFromCountry, strToCountry | crear/liberar país (formables de DH) |
| ActCountrySurrender | strLosingCountryName, strWinningCountryName | anexión |
| ActTransferRegionOwnership / Control | nRegionID, nNewCountryID (inheritFrom accesores) | ceder regiones |
| ActDevCreateUnits | strCountryName, strUnitTemplate, strRegionName, strUnitName, nNumUnits | crear unidades |
| ActIncDipRelations | nSourceCountryID, nTargetCountryID, nAmount | relaciones |
| ActDevCompleteResearchProject, ActIncResearchProjectPoints | strCountry, strProjectName(, nAmount) | investigación |
| ActSetNewCapital, ActSetCountryInternationalPosition, ActSetCountryAggressiveNature, ActIncRegionPop, ActSetRegionController | — | varios |
- **Cultura étnica**: no hay acción específica. Posible (sin probar): `ActAlterProperty nGOID inheritFrom region.nGameObject, strPropName=strCulture, strNewValue=<cultura>`.
- **Estado aliado de la misma ideología**: `PlayerDecisionTrigPlayEvent GENERIC_<Gov>LiberateCountryDecision_PlayEvent` (PlayEventConqueredRegion,
  condición `strGovType == 'Democratic'`) + `PlayerDecisionDef GENERIC_<Gov>LiberateCountryDecision` (ActGrantIndependence; «Liberate Data»
  pasa strGovType del jugador). Solo existen Democratic/Communist/Fascist (ScenarioDefaults/sharedData.xml): para una ideología nueva hay que
  clonar ambos objetos cambiando 'Democratic' por la nueva (los textos SID.Feedback.GENERIC_Democratic… sirven, usan @GovType@).

## IA en player<País>.xml («si invaden a X, Y interviene»)
- `HistoricalGoalRef otGoalType=HGoalHelpCountryWinWar` + `HistoricalGoalTargetBlock` (CountryAName, CountryBName): «si B ataca a A, el dueño ayuda a A
  (dinero, armas y quizá intervención)». Ej. TMWR `playerUnited States.xml` Title36: A=Israel, B=Iran. Otros: HGoalConquerCountry (A,B),
  HGoalAcquireRegions (A, RegionList), HGoalOverpowerCountry, HGoalFormAlliance (TargetCountryNames), HGoalAvoidWar, HGoalProtect/KeepRegions.
- `MEAIData > WarPlan > WarPlanOperation`: strTargetCountries / strTargetRegionList, dateTrigger, dateExpires, strPrereqOperations,
  **strWarTriggerCountriesA/B** = solo ataca cuando A y B están en guerra (TWAW: Japón ataca a la URSS si Alemania–URSS en guerra).
- `MEAIData > ForceAllegiancePlan`: cuando strWarTriggerCountryA/B en guerra, presiona a strTargetCountries (nMin/MaxTreaty*, nDeclareWarPct).

## Embargo al empezar
- ed.exe tiene un perfil «TradeRelationsProfile» (dataProfiles.xml): objetos `TradePolicyRelations` (strOwner, strTargetCountry, strRelations)
  en objGOs del MECountry. Ningún escenario lo usa; sin probar. Lo fiable: evento en el turno 1 (create_embargo_event).

## Partidas guardadas (.mlc) — ingeniería inversa (tools/savegame.py)
Carpeta: `C:\ProgramData\Muzzy Lane Software\Output Files\Saves\<jugador>\*.mlc` (solo se leen, nunca se modifican).
- Cabecera fija de 0xA28 bytes: u32 versión (5) @0, u32 turno @4 y @8, u64 hora real en ms Unix @0x10; textos UTF-16LE de 512 bytes:
  nombre @0x18, perfil (`MOD_<jugador>`) @0x218, paquete (`Modern Europe`) @0x418, escenario @0x618, fecha de guardado @0x818; u32 @0xA18 ≈ tamaño comprimido.
- Desde 0xA28: un único bloque zlib (MW turno 19: 1,9 MB → 16,6 MB) con los objetos de la partida en binario.
- Objeto: `<marca u32 (2 ó 6)> <tipo u32> <id u32> <nº propiedades u32>`, luego cada propiedad `<id u32> <0 u32> <-1 i32> <valor>`
  (id creciente; el valor no lleva longitud: int/float 4 bytes, bool 1, vector 3×float32, texto `u32 n + n×UTF-16`).
  Tras las propiedades: `<nº hijos u32>` y por hijo `<ranura u32> <índice | -1> <objeto>`.
- Tipos vistos en MH1 2.x (se detectan por contenido, no se dan por fijos): 166 ciudad, 167 fábrica, 126 región,
  176 productor, 7 país, 44/45/46 ejército/flota/fuerza aérea, 17 pila de unidades, 15 unidad suelta.
- Ciudad: p1 nombre, p2 dueño, p3 controlador, p8 índice de su región, p14 posición, p15 región del mapa; su fábrica: p0 IPUs actuales, p2 nivel tecnológico.
- Región: p0 índice, p1 nombre, p2/p3 dueño/controlador, p14 nº de región del mapa, p16 terreno (`Water` = mar), p22 población.
- Fuerza: p1 nombre, p2 dueño, p14 posición, p15 región del mapa (-1 = en puerto: se toma la de la ciudad más cercana).
  Pila de unidades (hijos): p0 plantilla, p12 número de unidades.
- Un país «sigue existiendo» si es dueño de alguna región de tierra.

## En el editor (tools/scenario_events.py)
- Pestaña **Eventos**: cada evento, decisión y disparador explicado en palabras (quién, cuándo, condiciones, ventana, elecciones, efectos,
  cadena evento → disparador → ventana); se editan los textos de la ventana y de los botones, la elección de la IA y la fecha/turno.
  «＋ Nuevo evento»: decisión con elecciones, ideología, ayuda de recursos, embargo, guerra (una vez), crear/liberar país, unidades,
  estado aliado de la misma ideología, cultura (experimental), guerra por fecha y protección de un aliado.
  Los efectos de una sola vez se generan como los mods: ScriptedEventDef con TriggerEvalUntilAnsweredPlayerDecision + PlayerDecisionTrigPlayEvent
  + PlayerDecisionDef (la IA elige `strDefaultChoice` con `nDefaultChoicePercent`). TriggerEvalRandomChance se evalúa cada turno (repite el efecto).
  La probabilidad por turno se hace con AccessorGetRandomNumberSimple 1–100.
- **Jugador / IA**: metas (HGoalHelpCountryWinWar…), planes de guerra (con «solo cuando A esté en guerra con B»), presión diplomática y
  embargos/guerras por evento, con añadir, cambiar y quitar. sharedDataEvents.xml nuevo solo se escribe al «Guardar».
- **Tipos de terreno**: TerrainType vive en el sharedData.xml del escenario (o en ScenarioDefaults para los escenarios del juego).
  Las 8 de serie: Plains, Hills, Forest, Mountains, Jungle, Tundra, Desert, Water. MountainWarfare/JungleWarfare (gameDefs) usan los nombres Mountains y Jungle.
- **Alcance de bombarderos**: `nRange` de UnitTemplate (millas, «distancia que un avión puede alejarse de su base»); se dibuja el círculo
  del mayor alcance de los bombarderos (eUnitCategory BOMBER o nStructureHitPercent > 0) de cada fuerza aérea.

## Reacciones por país: TriggerCountry (country<País>.xml)
- `MECountry > TriggerCountry` (objTriggerCountries): `strName` = país vigilado, `eTriggerType` = COUNTRY_TRIGGER_INVASION (si lo invaden;
  opcional `strRegionList` = solo esas regiones) o COUNTRY_TRIGGER_WAR (si entra en guerra), `nWarSensitivity` y `nEmbargoSensitivity`
  (0–100, «threshold for declaring war / embargoing, higher is more likely»), `bActive`. Es el «si invaden a X, declarar guerra o embargo»:
  TMWR tiene 62 países con ellos (p. ej. United States: Canada invadido → guerra 90 / embargo 90). En el editor: Jugador / IA › «Reacciona si…».

## Clases de eventos (pestaña Eventos)
- Genéricos del juego (etiqueta GENERIC_/Generic_/SCRIPTEDEVENT_, vienen de ScenarioDefaults): crisis por perder la patria
  (GENERIC__Lost_Homeland_Crisis), recuperar la capital original (GENERIC__Restore_Original_Capital), ciudad con bomba atómica,
  estado aliado de la misma ideología (<Gov>LiberateCountryDecision), unirse a un bando (…AxisEligibility / AlliesEligibility /
  CentralEligibility), país al borde de la derrota (…NearDefeat), golpe/revuelta (YugoslaviaCoup…), avance/retraso de investigación,
  ampliación de producción, moral de los trabajadores, respuestas a tratados (Generic_TreatyProposed_*), unirse a la guerra de la alianza,
  aviso de paso de tropas, levantamiento partisano. Los demás son propios del escenario (DH_, TMWR_, TLOP_…) y se clasifican por su
  etiqueta (Liberation, Formable, Puppet…) o por sus efectos.

## Color de los terrenos («biomas»)
- TerrainType no tiene color. El color del modo de mapa «Terreno» está en `Modern Europe/system/DisplayLibraries/MapViews/UnifiedMapViews.xml`
  (MapView «Terrain» > MapOverlayColorMap > MapOverlayColorMapping strValue/colColor/fTransparency): **archivo de todo el juego**, no del escenario.
  En Gold ese modo de mapa está activo; en MH1 viene comentado (no hay modo «Terreno», el color no se usa).
  scenario.xml solo elige el conjunto con `strMapViewsName` («UnifiedMapViews» o vacío). Un escenario podría usar un conjunto propio con
  otro nombre en esa carpeta (sin probar). El editor muestra el color en la ficha del terreno y lo guarda en el juego solo con el botón explícito.

## Culturas y tratados
- Culturas: `CultureTemplateSet > CultureTemplate` (strCultureName, sidDisplayName) en sharedDataCultureTemplates.xml; cada región usa una
  (`strCulture`) y cada nación tiene su `CultureSet > Culture`. Pestaña «Culturas (etnias)» para crear y quitar.
- Acceso militar en treaties.xml: dos formatos, `Treaty` corto (TMW, mods) y `TreatyAgreement` con nombre y fechas; ambos con dos MilAccessTerm.
  El editor crea el que ya use el escenario.
- Tipos cerrados: las propiedades `e…` son Enum del juego (defEnum de system/game/namespace.xml); el editor las muestra como desplegable.
- Partida y regionpack (2026-10-22): al cargar, el juego valida las regiones por nombre («InitGameValidateRegions - Got Region
  named "Odesa" that isn't part of the map») y la partida guarda además el número de cada región del mapa (p14 de la región, p15 de
  ciudades y fuerzas). Al quitar Odesa de WorldModern, las 7 regiones siguientes bajaron un número (Halab 896→895...). Por eso
  NO se adapta el .mlc: habría que quitar objetos y renumerar referencias en todo el binario sin esquema completo. En su lugar,
  «Partida guardada → escenario» compara la partida con el regionpack (savegame.pack_report), traduce las regiones quitadas por
  el changelog (absorbida_por) y adecua el escenario nuevo al regionpack (pack_sync_apply). Hay que empezar ahí una partida nueva.
- Sin suma de control: @0xA18 = tamaño del bloque zlib + 16, @0xA24 = 0x1AFC01 fijo en todas las partidas; zlib lleva su propio
  adler32. Reescribir el .mlc es posible en forma, pero quitar una región no: en TMWR_Russia_Mar 20 2024 el número de Odesa (890)
  aparece como valor de propiedad 155 veces en ~12 tipos de objeto sin identificar (listas de vecinos, rutas, IA…), y además
  dentro de listas sin cabecera; habría que renumerar 891-897 igual, sin poder distinguirlos de otros enteros. Solo un
  renombrado (mismo número de regiones y mismo orden) sería viable cambiando los textos.

## Posición y orientación de ciudades y unidades
- VisibleGO (gameDefs.xml): `vecPosition` [lon, lat, altura] (por defecto altura 100 = «ponla en su región») y `nDirection`
  (grados: 0 norte, 90 este, 180 sur, 270 oeste; por defecto 225, ciudades 180). Las ciudades de los escenarios del juego tienen
  nDirection 0; TMW/TMWR/1836 usan otros valores. Algunos mods (World Aflame, DH) también lo ponen en ejércitos, aviación y flotas.
  No comprobado en el juego cómo se ve el giro de las unidades.
- MovableGO: `strRegion` (región de inicio) y `strCity` (ciudad de inicio: flota en puerto). Flota en puerto = strRegion región de
  tierra + strCity ciudad con `strPortForRegion` del mismo dueño.
- Editor: «Mover y girar ciudades, recursos y unidades» (arrastrar; clic en la ciudad o unidad y clic derecho = mira hacia ahí,
  como en ed.exe), y en la ficha: 📍 mover a un punto, orientación y «Meter en puerto» para flotas.

## Reglas del editor oficial (decompilado de ed.exe, ver docs_texto/editor_oficial/04 y COMPARACION.md)
- Duración `nScenarioDuration` 1–99.999; fechas no negativas.
- HP, velocidad y `nBaseOutputRate` ≥ 1; % de impacto y resistencia 0–100; el resto de números ≥ 0; nombres/descripciones no vacíos.
- Nación activa: debe tener capital, existente y propia. Rendida: sin regiones poseídas ni controladas, pero CON capital (capital anhelada en sus regiones históricas): sin ella no se puede liberar. ed.exe la marca como error (47/42), pero en el juego hace falta.
- Guerra: atacante ≠ defensor, ninguno rendido, no en la misma alianza, no ya en guerra; ambos registrados en el juego.
- Composición de ejército/flota/aire: plantilla existente y `nNumber` > 0. Tecnología conocida: prerrequisitos presentes.
- Flujos (`WorldMarket/objFlows`, `objAidFlows`) y tratados (`treaties.xml`): países y recursos deben existir.
- ed.exe no guarda nada si hay un solo error; al cargar no valida.
- Carpetas creadas al guardar: `game/namespace.xml` (vacío con scenarioDefs/stringTable), `ui/UICommandFile.xml`, `ui/UIPreLoopCommandFile.xml`.
- `scenarioInfo.xml` y `treaties.xml` escriben `/>` sin espacio previo.
