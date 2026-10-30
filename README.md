# Making History 1 & Gold Editor 3.2

<img width="1672" height="941" alt="297d7030-6196-423d-8a65-2a72f5bccb2a copia" src="https://github.com/user-attachments/assets/64a68a15-553d-413e-b5d8-0cd624c27aed" />


<img width="1672" height="941" alt="297d7030-6196-423d-8a65-2a72f5bccb2a copia" src="https://github.com/user-attachments/assets/64a68a15-553d-413e-b5d8-0cd624c27aed" />


Map (regionpack), scenario and image editor for **Making History: The Calm and The Storm (MH1)** and **Making History Gold**.

This NEW Open Source editor allows the user to modify game regions (provinces) and to create and modify regionpacks that way. A regionpack from scratch can also be created, allowing the creation of a fictional world. The regionpack background image can be modified and exported. This feature is new and hasn't been achieved before.

The editor is compatible with GeoJsons, which are geographical GIS shape files that can be imported and exported, and modified in chartographical external tools.

A scenario editor is also included with features not present in the original editor such as event editing, flag and roundel importer, country color modifier, historical nations modifier, a validator.

An image editor is included for the scenario title and distinctive identity.

A 3D model editor is included (Work in progress).

It is recomendable to also use this editor with a Code AI LLM such as Claude Code and Codex.

> Fan project, not affiliated with Muzzy Lane. It ships no game files: you need the game installed (Steam, or the
> Muzzy Lane installer in `C:\Program Files (x86)\Muzzy Lane Software\...`; the editor finds it on its own).

- **Download / updates:** [Releases](https://github.com/avlopezparra/making-history-1-and-gold-editor/releases/)
- **Community:** [Discord](https://discord.com/invite/gFJyCjWEnr)
- **Report bugs:** alopezcl@protonmail.com (or open an issue)
- **Donations:** [Paypal](https://www.paypal.com/paypalme/alopcl)

Made by Alejandro Víctor López Parra (@avlopezparra), 2026. **Version 3.2**.

## What it does
- **Region editor**: move nodes, draw, cut, merge, create, rename and delete regions; topology-safe shape changes; installs the
  result as a *regionpack*; changelog per regionpack; GeoJSON import/export; shows cities, resources and units.
- **Scenario editor** (like `ed.exe`): all tabs (nations, regions, cities, armies, air forces, fleets, ideologies, alliances, wars,
  diplomacy, events...), clickable map layers, multi-select, create objects, validator with automatic fixes.
- **Adapt**: moves a scenario to another regionpack, adding/removing the regions the game needs to load it.
- **Images**: title, flags, icons, terrain background (with separate background/borders export).
- English and Spanish UI. Documentation (Spanish): [EDITOR.md](EDITOR.md), map format: [MAPA_FORMATO.md](MAPA_FORMATO.md).
  For AI coding agents (Claude Code, Codex...): [AGENTS.md](AGENTS.md).

## Use the program (nothing to install)
Download **MHEditor.zip** from [Releases](https://github.com/avlopezparra/making-history-1-and-gold-editor/releases/), unzip it and run
`MHEditor.exe` (Windows 10/11 64-bit; uses WebView2, already included in Windows 11).

## Run it in the browser (from source)
The editor is a web app that runs **on your own PC** (a small local Python server) and reads/writes your game folder, so it cannot be
hosted online: everyone runs it locally with the game installed.

1. Install **Python 3.12+** from https://www.python.org/downloads/ (tick "Add python.exe to PATH").
2. Download this repository ("Code → Download ZIP") or `git clone` it.
3. Install the dependencies once: `pip install -r requirements.txt`
4. Start it by double-clicking `Region Editor.bat` (or `Scenario Editor.bat`), or run `python tools/editor_server.py`.
5. Open **http://localhost:8765** (map/region editor) and **http://localhost:8765/scenario** (scenario editor).
   `python tools/mheditor_app.py` opens the same thing in its own window.
6. The **MH1 / Gold** selector at the top picks the game. Changes are only written to the game when you press **Save** or **Install**.

| Server option | Purpose |
|---|---|
| `--puerto 8770` | use another port if 8765 is busy |
| `--juego mh1` / `--juego gold` | choose the game at start |
| `--pack World` | regionpack to start with |
| `--no-abrir` | don't open the browser |
| `--escenarios FOLDER` | (testing) work on copies of scenarios instead of the game's |

Environment variables: `MH_ROOT` (where projects and logs are kept), `MH_STEAM_COMMON` (a `steamapps\common` folder in another Steam
library), `MH_GAME_MH1` / `MH_GAME_GOLD` (game folder of a non-Steam install), `MH_PORT` (port of the `.exe`).

## Claude Code skill
[`skill/making-history-modding`](skill/making-history-modding/SKILL.md) teaches Claude Code how to mod MH1 and Gold: game folders,
scenario XML, the map binaries (regions.bin and its `u_flag`), regionpacks and changelogs, events, load errors and this editor.
Install it by copying the folder to `~/.claude/skills/` (Windows: `%USERPROFILE%\.claude\skills\`), so you end up with
`~/.claude/skills/making-history-modding/SKILL.md`; Claude Code picks it up in new sessions.

**Troubleshooting**
- *"An editor is already open..."*: a server already uses that port; open it in the browser or close it first.
- *Game not found*: check the folder contains `Modern Europe`, or set `MH_GAME_MH1` / `MH_GAME_GOLD` / `MH_STEAM_COMMON`.
- *Old page after updating*: restart the server and reload with `Ctrl+F5`.
- **Back up** your game and scenarios before you start.

## Build MHEditor.exe
```
compilar_exe.bat          (or:  pip install -r requirements.txt  &&  python tools/build_exe.py)
```
The result goes to `MHEditor\` (exe + `_internal`); zip that whole folder as `MHEditor.zip`. Pushing a `v*` tag runs
`.github/workflows/build.yml`, which builds it and attaches it to the release.

---

## En español
Editor de mapa (regionpacks), de escenarios y de imágenes para Making History 1 y Gold. Proyecto de fans, sin relación con Muzzy Lane;
no incluye archivos del juego.

- **Descargas y actualizaciones:** [Releases](https://github.com/avlopezparra/making-history-1-and-gold-editor/releases/) ·
  **Discord:** https://discord.com/invite/gFJyCjWEnr · **Errores:** alopezcl@protonmail.com
- **Sin instalar nada:** descarga `MHEditor.zip`, descomprímelo y abre `MHEditor.exe`.
- **Desde el código:** Python 3.12+, `pip install -r requirements.txt`, doble clic en `Region Editor.bat` y abre
  http://localhost:8765 (regiones) o http://localhost:8765/scenario (escenarios).
- El editor **solo escribe en la carpeta del juego al Guardar o Instalar**. Haz una copia de seguridad antes de empezar.
- Documentación completa: [EDITOR.md](EDITOR.md).
