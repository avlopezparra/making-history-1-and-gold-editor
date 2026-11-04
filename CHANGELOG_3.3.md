# Making History 1 & Gold Editor 3.3

**Fixes from the code review**
- New regions cut from a renamed region (RegionRename in map.xml) are registered in the scenarios again; before, they failed with «mother region does not exist».
- Population set by hand or taken from a GeoJSON is now taken from the source region(s); before, the source lost its area share and those inhabitants vanished.
- «Register in scenario» shows the population entered at creation in a new «Or inhabitants by hand» field instead of applying it silently.
- Exclaves: only the regions really being cut are checked; thin border slivers and crumbs are included in the new region automatically; one «absorb» operation per neighbour instead of one per piece. No more hundreds of «exclaves» from a border-following cut.
- The population % of the new-region dialog is corrected when exclaves or slivers are included.
- GeoJSON import: duplicates are detected and discarded with the same rule, so discarded duplicates are no longer imported as «Name 2».
- A new region that would end up with no area is now an error; before, it stayed in memory as an empty region, was written on the next save, and its name could not be reused.
- Editing nodes no longer turns the merged drawing outline (seams closed for display) into dozens of tiny transfers: only what the user changed is applied to the mesh.
- If painting the background or another step fails after the map is written, the save still completes with a warning (changelog and registration included).
- «Redraw borders» and «Restore background» show the real server error; redraw can be undone with «Back» instead of making a separate copy of the tiles.
- Saving the map no longer installs it into the game or adapts other scenarios on its own: the editor asks («Install now» / «Later»), also after Undo, Redo and «Register in scenario».
- Security: the local server only accepts requests from its own pages (localhost Host/Origin plus a per-start token injected into the pages); other websites can no longer send it commands.
- Scenario editor: a country leaving an alliance no longer leaves it empty or leaderless (empty alliances are removed and wars stop naming them); «New alliance» with an existing name reuses it; painting with the alliance layer only adds.
- Relations: members of an alliance at war now show as at war (alliance key fixed).
- MHEditor.exe: no AI-chat errors when the chat is not included; 3D models in the data folder are allowed; the Wikidata cache is kept next to the data so rebuilding does not erase it.
- English UI: every popup, dialog, status line and server message is now translated (messages with data, multi-line alerts, validation, event notes); `python tools/i18n_extract.py --check` lists any Spanish text left.
- Diagnostic log: MHEditor.log next to the editor data (rotates at 2 MB) records startup, every API request (short summary, no geometry), server exceptions with traceback, page errors, error messages and the user's clicks; keys and tokens are masked. «Open log» / «Copy log» in Credits / contact.
- Background: after «Restore background», «Redraw borders» or a save that repaints tiles, the far-zoom levels (mipmaps -01..-04) are rebuilt from the finished full-size tile, so erased border lines no longer linger when zoomed out; restoring also fixes tiles whose mipmaps were already stale, including map tiles the project had not touched yet (e.g. WorldModern around Iraq–Iran).
- Map editor: adding area from a GeoJSON (edited shape or «Add area from GeoJSON…», e.g. Mauritius plus a new island in open sea) saves again: rounding slivers along shared borders are ignored, island-on-halo regions keep a valid outline when another part is added, and when a shape change would still break the mesh the error says where and offers «save without the parts that break the mesh» (the report lists what was dropped and where).
- Map editor: imported or edited land polygons now snap to the neighbouring borders on save (unassigned slits narrower than ~200 m are filled, overlaps thinner than ~100 m stay with the neighbour), so a GeoJSON that doesn't quite fit no longer leaves background specks along the border (e.g. Iraq–Iran in WorldModern); «Validate» lists such slits per border pair with a «Close gaps with neighbour» button.
- Scenario editor: «⚔ Bulk units…» creates armies, air forces and fleets for many countries at once (chosen, all, or playable/major/minor), with custom units, a «base army» per country tier or a random population-scaled one; stacks are spread over the country's regions away from cities and units, fleets go to a sea next to its coast (none for landlocked countries), templates follow the nation's tech, with a preview and «Undo the last creation».

**Release and English-UI follow-up**
- The GitHub export now uses `README_github.md` unchanged, preserving its section structure, and includes `tools/data/nif.xml`, which the executable build needs for 3D models.
- Release builds are named `MHEditor.<version>.zip` and include the Claude editing skill, matching the README download instructions. The NifSkope schema's redistribution license is included in both source and release ZIP.
- Added English translations for the remaining bulk-unit, map-validation, Blender-import and scenario event-fix messages and labels; `python tools/i18n_extract.py --check` now reports zero untranslated UI text.
