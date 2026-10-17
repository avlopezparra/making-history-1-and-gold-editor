# Estructura de un escenario (para el futuro editor de escenarios tipo ed.exe)
Carpeta: Modern Europe\system\scenarios\<escenario>\
- scenario.xml: fechas (dateStart, dateEnd, nScenarioDuration, nTurnDuration, nStartYear) y lista de sharedData.
- scenarioInfo.xml: ScenarioInfo (nombre, descripcion, paises jugables).
- game.xml: GO fromFile -> cada countryX.xml / playerX.xml / treaties.xml / waterWorld.xml; WorldMarket con Flow (objAidFlows; Trade Flows = objTradeFlows, vacio en TMW) y ResourceTrade.
- gamestate.xml: Player (strName, colCountryColor, bNonPlayable...), Alliance/AllianceMember, War (atacante/defensor por pais y alianza).
- treaties.xml: Treaty + MilAccessTerm (accesos militares).
- countryX.xml: MECountry (gobierno, capital, eCountryType, bSurrendered, nTransportCredits, CultureSet) con
  Region (strOwner, strController, terreno, cultura, poblacion, infraestructura, fortificacion, agricultura)
  > City (vecPosition, strPortForRegion, strInitialWorkOrder, Factory nIPUs/nTechLevel) y Producer (recurso, produccion);
  Army/AirForce/Fleet (strRegion, vecPosition, UnitSummary strName/nNumber).
  REGLA: en los 8 escenarios las 4.625 regiones estan en el archivo de su propietario -> cambiar dueno = mover el bloque.
- playerX.xml: MEPlayerData (IA: nAggressiveNature..., diplomacia inicial DipRelInitialValue, investigacion ResearchProjectInitRef).
- waterWorld.xml: 274 regiones de mar.
- sharedDataUnitTemplates.xml (UnitTemplate x47), sharedDataFactories.xml (FactoryOutput*), sharedDataResearch.xml (ResearchProj*).
- Textos SID: system\locale\<idioma>\stringTableGame.xml y <escenario>\game\stringTable.xml.
