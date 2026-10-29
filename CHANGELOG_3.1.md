# Making History 1 & Gold Editor 3.1

**Region editor**
- Islands no longer get a coast-hugging line in the background; borders come only from the region geometry (South Georgia fixed in WorldMoreRegions and WorldModern).
- «Redraw borders»: asks for confirmation; can redraw a single region and its affected neighbours.
- «Refresh» also reloads the background image.
- MH2 map background exported as PNG, ready to import.
- Scenario import: discarded duplicate regions are no longer imported; the dialog shows the nearest existing region (by centre) and its distance.
- «Register in scenario» uses exactly the population entered when creating the region.

**Scenario editor**
- Opens with the map view by default.
- Images: flag and roundel in the nation sheet (all versions), nation portrait, Title.tga and Button/ButtonOver (+8 brightness or custom), editable icons (ideology, resources, terrain, production, units, research) and per-scenario UI.
- «♪ Anthems…»: add national anthems to the game (global); shows which countries already have one.
- Wikidata: link cities and countries to a Wikidata ID (manual or by search); imports coordinates, population (within 20 years of the scenario), owner by year, capital and flag from Commons.
- Events: transfer region (fixed or random), alliance conditions, resource output, city IPU bonus/penalty, occupy region, research, capital, defence pacts/military access, stance/aggression.
- Validation from the official editor: wars, capitals and surrendered nations, unit composition, research prerequisites, trade flows, military access, turn limits, city values; warning when saving with errors.
- New fields and editors: nation treasury, transport credits, stockpile and flags; region agriculture, fortification, infrastructure, population, culture and terrain; producers; trade/aid flows; military access treaties; alliance name; UnitTemplate, FactoryOutput and ResearchProject; «Edit» button in the error list.

**3D models**
- New «3D models» editor (also in the Editors menu): view models with texture and bones, export .glb/.obj, change textures, import meshes.
- «3D source» column in the «3D scale» tab.
- Restored the lost «T-34/76» tank mod (Steps to a Global War release).
- Fixed the «nif.xml» error when choosing a model in MHEditor.

**General**
- «Invalid License Key» fix: removes old licences in VirtualStore, with a .reg backup (also as a standalone patch).
