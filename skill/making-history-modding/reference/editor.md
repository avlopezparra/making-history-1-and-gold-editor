# MHEditor 2.4 (region, scenario and image editor)
- Run `MHEditor.exe`, or from source: `pip install -r requirements.txt` then `python tools/editor_server.py`
  → `http://localhost:8765` (regions), `/scenario` (scenario editor), `/images`. MH1 / Gold selector at the top.
- Test against copies: `python tools/editor_server.py --proyecto <tmp>/proyecto --respaldo <tmp>/respaldo --escenarios <tmp>/escen --no-abrir --puerto 8768`.
- Nothing is written to the game until **Save** / **Install**. Backups = changelog + undo/redo.

## Region editor
- **View / ownership** mode: map coloured by owner; click a region → Owner/Controller; "Paint ownership"; **Save scenario**.
- **Edit shape** mode: move nodes, draw, cut (asks where the cut piece goes), merge, create, rename, delete regions; add/subtract area from a GeoJSON.
- Regionpack selector, "+ New" (empty fictional world), "Save as…" (copy a pack), **Install** (to the current or a new pack, choosing scenarios).
- Indicator next to Scenario: "✓ matches the map" or "⚠ missing N / extra M" with **Adapt**.
- GeoJSON import/export (land, sea, borders, cities, units, resources, changelog comparison, nations).
- File → **Validate**: broken meshes, empty regions, duplicate names, wrong sea u_flag, ownerless regions, scenario/map mismatches.
- Background image: export/import terrain tiles (rescaled, DXT5 + mipmaps).

## Scenario editor (like ed.exe)
- Open a scenario; tabs: Global Data, Nations, Land/Sea Regions, Cities, Producers, Armies, Air Forces, Navies, Alliances, Wars,
  Trade/Aid Flows, Military Access, Players/AI, Colors, Diplomacy, Historic Countries, Events, Unit Models, Infrastructure,
  Unit Templates, Factory Outputs, Research Projects; Map panel beside the object form.
- **Apply** = in memory; **Save scenario** writes the XML (originals kept in backup); **Revert**.
- Changing a region's owner moves its block between country files. "＋ New" creates nations, fleets, alliances, wars, access,
  diplomacy, events (war by date, embargo, ally protection) and copies of units / factory outputs / research.
- **Validate** checks owners, files, regions vs map, ports, fleets, capitals, duplicates, diplomacy symmetry;
  "🩺 The game won't load it…" records and reads the game log.
- Flags/icons for new nations go in `UI/art/2D/countries/<Name>` (copy them by hand).
