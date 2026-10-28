# Scenario XML (`Modern Europe\system\scenarios\<scenario>\`)
- `scenario.xml`: dates (dateStart, dateEnd, nScenarioDuration, nTurnDuration, nStartYear), list of sharedData files,
  `strMapName` + `fileMapProperties` = regionpack. `strMapName` must be a folder in DisplayLibraries/Maps with `xml/map.xml`.
- `scenarioInfo.xml`: ScenarioInfo (name, description, playable countries).
- `game.xml`: `<object type="GO" fromFile=...>` for every country*.xml / player*.xml / treaties.xml / waterWorld.xml;
  WorldMarket with Flow (objAidFlows, objTradeFlows) and ResourceTrade. A country file not listed here is not loaded.
- `gamestate.xml`: `Player` (strName, colCountryColor, bNonPlayable, sidName...), Alliance/AllianceMember,
  War (attacker/defender countries and alliances). **One Player per name.**
- `treaties.xml`: Treaty / TreatyAgreement + MilAccessTerm (military access).
- `country<X>.xml`: MECountry (government, capital, eCountryType, bSurrendered, nTransportCredits, CultureSet) containing
  `Region` (strOwner, strController, terrain, culture, population, infrastructure, fortification, agriculture)
  > `City` (vecPosition, strPortForRegion, strInitialWorkOrder, Factory nIPUs/nTechLevel) and `Producer` (resource, output);
  Army / AirForce / Fleet (strRegion, vecPosition, UnitSummary strName/nNumber).
  **Every Region block lives in its owner's country file** — changing owner = moving the block (with cities/producers).
- `player<X>.xml`: MEPlayerData — AI personality (nAggressiveNature...), `DipRelInitialValueList > DipRelInitialValue`
  (initial relations 0–1000; keep A→B = B→A), `ResearchProjectInitRef`, `BasicRegionLists` (`Historic` = coveted regions), MEAIData.
- `waterWorld.xml`: the sea regions (274 in World).
- ScenarioDefaults: sharedDataUnitTemplates.xml, sharedDataFactories.xml, sharedDataResearch.xml, sharedData.xml, sharedDataEvents.xml.

## Validity rules (break them → the game won't create the match)
- `eCountryType` only `COUNTRYTYPE_PLAYABLE | _FEATURED | _NON_FEATURED` (MINOR/MAJOR are invalid).
- Every `sid*` of a Player (e.g. sidShortDescription) must exist in a stringTable, even with empty text.
- `DipRelInitialValue` only inside `DipRelInitialValueList`, never loose in MEPlayerData.
- `ResearchProjectInitRef RESEARCH_COMPLETED`: every prerequisite must be completed too or have `bCompletedByDefault=true`.
- No war with attacker = defender, between members of one alliance, duplicated, or with an unregistered country;
  no units with 0 strength; no duplicate country or unit-template names.
