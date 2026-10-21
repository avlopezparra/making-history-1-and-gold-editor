# AGENTS.md — guide for AI coding agents (Claude Code, Codex, …)

This repository is a fan-made editor for **Making History 1 (MH1)** and **Making History Gold**: a local Python web server
plus HTML pages, also packaged as `MHEditor.exe` (pywebview + PyInstaller).

## Layout
| Path | What |
|---|---|
| `tools/editor_server.py` | HTTP server and every `/api/...` route (map editor, scenario editor, images) |
| `tools/editor_core.py` | regionpack project: regions, topology, save/install, changelog |
| `tools/scenario_core.py` | scenario store (XML files of a scenario), tabs, options, validation, save |
| `tools/scenario_layers.py` | map layers, bulk actions, diplomacy/capital validators, cities/armies creation |
| `tools/scenario_events.py` | events, decisions and AI rules in plain words; event templates; AI goals/war plans; terrain types; bomber ranges |
| `tools/scenario_create.py` | "＋ New" objects: nations, fleets, air forces, ideologies, alliances, wars, … |
| `tools/geojson_io.py`, `tools/terrain_*.py` | GeoJSON import/export, terrain colours and images |
| `tools/gamepaths.py` | where the game is installed (Steam libraries, Muzzy Lane installer, `MH_GAME_*`) |
| `tools/editor/index.html` | region (map) editor page — served at `/` |
| `tools/editor/escenario.html` | scenario editor page — served at `/scenario` (old `/escenario` still works) |
| `tools/editor/imagenes.html` | image editor — `/images` |
| `tools/editor/i18n.js`, `i18n_en.json` | UI translation: source strings are Spanish, English comes from the JSON |
| `MAPA_FORMATO.md`, `ESCENARIOS_NOTAS.md`, `GOLD_NOTAS.md` | reverse-engineered formats (regions.bin, borders.brd, scenario XML) |

## Run and test
```
pip install -r requirements.txt
python tools/editor_server.py --no-abrir --puerto 8765
```
**Never test against the real game files.** Copy scenarios to a scratch folder and start a second server on it:
```
python tools/editor_server.py --proyecto <scratch>/proyecto --respaldo <scratch>/respaldo --escenarios <scratch>/escen --no-abrir --puerto 8768
```
Quick checks after editing: `python -c "import ast; ast.parse(open(F, encoding='utf-8').read())"` for Python, and extract the
`<script>` blocks of a page into a file and run `node -e "new Function(src)"` for JavaScript.

## Rules the maintainer cares about
- The editor writes to the game folder **only** on an explicit **Save** / **Install**; everything else stays in memory or in the project folder.
- Every UI string exists in **Spanish and English**: write Spanish in the page and add the English to `i18n_en.json`.
- Don't "repair" user data unasked; make the editor stop producing the problem instead.
- Backups are the changelog plus undo/redo; don't add other backup copies.
- `python tools/build_exe.py` builds `MHEditor.exe` (refuses while MHEditor is running); `python tools/exportar_github.py <out>` makes the public repo folder.

Bugs: alopezcl@protonmail.com · Discord: https://discord.com/invite/gFJyCjWEnr
