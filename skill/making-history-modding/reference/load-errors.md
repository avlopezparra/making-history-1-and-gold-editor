# Load errors ("Error creating game" / "Error creating local game")
Start logging with `Game Log.bat` (or the editor's "The game won't load it…" dialog), load the scenario, then run
`python tools/game_log_report.py [file.log]`: it lists each load attempt, the stage that failed and the grouped errors.

| Symptom / log message | Cause | Fix |
|---|---|---|
| Region not part of the map; scenario regions missing or extra | Scenario regions ≠ regionpack regions (map edited, region renamed, wrong pack) | **Adapt** the scenario to its pack (adds/removes regions), or fix `RegionRename`; Validate lists missing/extra |
| `Found player named "X" but there wasn't a PlayerData named that` → `failed on InitGameValidateCountries` | player*.xml discarded: usually a loose `DipRelInitialValue` (`objDipRelInitialValues is not defined in type MEPlayerData`), or the file isn't registered in game.xml | Move DipRelInitialValue into `DipRelInitialValueList`; register the player file in game.xml |
| Duplicate player: two `Player` with one name in gamestate.xml, or duplicated alias/file in game.xml | Nation created or copied twice | Keep one Player and one GO entry per nation (Validate lets you pick which) |
| `"COUNTRYTYPE_MINOR" is not valid … eCountryType` | Invalid enum | PLAYABLE / FEATURED / NON_FEATURED |
| `"SID.…" is not valid … sidShortDescription` | Missing string | Add the SID to `<scenario>\game\stringTable.xml` (empty text is fine) |
| `projects which didn't ever have their pre-reqs met: X` → research state fails | Completed project with an uncompleted prerequisite | Complete the prereqs or set bCompletedByDefault |
| `Error loading area map data for map W` → `Couldn't find area map` | strMapName points to a missing pack | Point the scenario to an existing pack and Adapt |
| Sea region red, game closes when clicked | Sea with u_flag 0 | u_flag = 1 on every sea |
| Region invisible / unselectable | Clockwise triangles in regions.nts | Make triangles CCW (editor Install normalises) |
| Border lines shooting to (0,0) | Zero-length steps / non-shared edges in borders.brd | Regenerate borders from shared mesh edges |

Saving any scenario in the editor runs `Store.fix_load_errors` for the known XML cases.
