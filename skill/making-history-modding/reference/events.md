# Events, decisions, AI
Defs: `system/game/actionDefs.xml` (+ the Modern Europe copy), `brainDefs.xml`, `goalDefs.xml`, `gameDefs.xml`.
Events usually live in ScenarioDefaults `sharedDataEvents.xml` or a sharedData file listed in scenario.xml.

## Event with a popup
1. **ScriptedEventDef** (`strTypeLabel`): who (`PlayerGenNames strName=X` or `PlayerGenAll`), trigger `objTriggerEval`:
   `TriggerEvalRandomChance nPercentChance` (per turn), `TriggerEvalUntilTurn nTurn`,
   `TriggerEvalUntilAnsweredPlayerDecision strDecisionType`. Conditions: `AccessorRuleSet` (all must hold) with accessors
   (`AccessorGetCountry`, `AccessorGetRegion`, `AccessorIsAtWar`, `AccessorIsAllied`, `AccessorGetCurrentDate/Turn`…) +
   `RuleDefExpression expRession` (`exists(...)`, `!x.bSurrendered`, `region.nOwnerID == country.nCountryID`,
   `dateGameDate GTE MM/DD/YYYY`, `sizeOf(wars) LTE 0`). Optional silent effects: `CustomEffectDefActions objEffects`.
2. **PlayerDecisionTrigPlayEvent**: `otPlayEventType` (PlayEventNewScriptedEvent, PlayEventConqueredRegion…) + condition
   `scratch.objScriptEvent.strTypeLabel == '<event>'` → `strTypeToTrigger` = the decision.
3. **PlayerDecisionDef** = the window: `ArgumentList "Display Data"` strTitle/strDesc (literal or `computeFrom=getString(SID…)`);
   choices `PlayerDecisionChoiceDefCustom strLabel` with strTitle/strDesc/strEffect and `objChoiceEffects`.
   `strDefaultChoice` + `nDefaultChoicePercent` = AI choice; `strDefaultChoicePlayer` = human default. News = a single "OK" choice.

## Useful actions
| Action | Properties |
|---|---|
| ActProposeDeclareWar | strFromCountry, strToCountry |
| ActSetTradeRelations | strCountry, eTradeRelations (NEUTRAL/FAVORED/SANCTIONED/EMBARGOED) |
| ActSetCountryGov | strCountry, strGovType |
| ActIncResourceStock | strCountry, strResource, nIncrement |
| ActGrantIndependence | strFromCountry, strToCountry |
| ActCountrySurrender | strLosingCountryName, strWinningCountryName |
| ActTransferRegionOwnership / Control | nRegionID, nNewCountryID |
| ActDevCreateUnits | strCountryName, strUnitTemplate, strRegionName, strUnitName, nNumUnits |
| ActIncDipRelations | nSourceCountryID, nTargetCountryID, nAmount |
| ActDevCompleteResearchProject / ActIncResearchProjectPoints | strCountry, strProjectName(, nAmount) |
| ActSetNewCapital, ActSetRegionController, ActIncRegionPop, ActSetCountryAggressiveNature | — |

Per-country reactions: `TriggerCountry` in country*.xml. A starting embargo is most reliable as a turn-1 event.
Liberation into a same-ideology state: `GENERIC_<Gov>LiberateCountryDecision(_PlayEvent)` exist only for Democratic/Communist/Fascist; clone both for a new ideology.

## AI (player<X>.xml)
- `HistoricalGoalRef otGoalType=HGoalHelpCountryWinWar` + `HistoricalGoalTargetBlock` (CountryAName, CountryBName): if B attacks A, the owner helps A.
  Others: HGoalConquerCountry, HGoalAcquireRegions, HGoalOverpowerCountry, HGoalFormAlliance, HGoalAvoidWar, HGoalProtect/KeepRegions.
- `MEAIData > WarPlan > WarPlanOperation`: strTargetCountries / strTargetRegionList, dateTrigger, dateExpires, strPrereqOperations,
  **strWarTriggerCountriesA/B** (attack only when A and B are at war). `ForceAllegiancePlan` pressures target countries.
