---
name: making-history-modding
description: Mod Making History 1 (The Calm and The Storm) and Making History Gold - game folders, scenario XML, regions.bin/borders.brd/regions.nts map formats (u_flag), regionpacks and changelogs, events and AI, fixing "Error creating game" load errors, and using the MHEditor region/scenario editor. Use for any Making History / MH Gold modding, scenario, map or event task.
---

# Making History 1 & Gold modding

Engine: Muzzy Lane, data-driven XML plus a few little-endian binaries. MH1 and Gold share the folder layout and the
**World map binaries are byte-identical**; Gold has different engine defs, terrain textures, ScenarioDefaults and 4 extra
scenarios (Blitzkrieg, Clash of Continents, Rise of the Reich, Southern Star).

## Golden rules
- **Never edit the real game folder while testing.** Copy the scenario/regionpack to a scratch folder and work there.
  Write to the game only on an explicit Save / Install the user asked for.
- A scenario's regions must match its regionpack's regions exactly, or the game says *Error creating local game*.
- When a scenario will not load and the map is fine, read the game log first (`reference/load-errors.md`).
- Don't "repair" user data unasked; fix the tool that produced the problem.

## Game folders
| What | Path (under the game install) |
|---|---|
| Install | Steam `steamapps\common\<MH1 or Making History Gold>`, or `Program Files (x86)\Muzzy Lane Software\...`; override with env `MH_GAME_MH1` / `MH_GAME_GOLD` |
| Scenarios | `Modern Europe\system\scenarios\<scenario>\` |
| Scenario defaults | `Modern Europe\system\scenarios\ScenarioDefaults\` (sharedData*.xml) |
| Regionpacks (maps) | `Modern Europe\system\DisplayLibraries\Maps\<pack>\xml\` (map.xml, regions.bin, borders.brd, regions.nts) and `art\` (OperationalTerrain tiles, MiniMap.tga) |
| Engine defs | `system\game\` actionDefs, accessorDefs, gameDefs, namespace, brainDefs, goalDefs (+ `Modern Europe\system\game\`) |
| Strings | `system\locale\<lang>\stringTableGame.xml`, `<scenario>\game\stringTable.xml` (Gold has no `esp` locale) |
| Flags / icons | `Modern Europe\system\UI\art\2D\countries\<Nation>` |

## Reference files (read the one you need)
- `reference/scenario-xml.md` — files of a scenario and their validity rules.
- `reference/map-format.md` — regions.bin (incl. **u_flag**), borders.brd, regions.nts, terrain textures.
- `reference/regionpacks.md` — regionpacks, changelog.json, map.xml renames, equivalence with `World`, Adapt.
- `reference/events.md` — scripted events, decisions, actions, AI goals and war plans.
- `reference/load-errors.md` — log message → cause → fix.
- `reference/editor.md` — using MHEditor (region editor, scenario editor, images).
