"""Prepara una carpeta limpia para subir el editor a GitHub: solo el código y la documentación propia.

Uso:  python tools/exportar_github.py [carpeta_de_salida]      (por defecto ..\\making-history-github)

NO incluye nada del juego ni del trabajo del usuario: ni mapas (regions.bin…), ni copias de escenarios, ni proyectos
(editor_proyecto*), ni respaldos, ni capturas, ni los textos de las guías oficiales (docs_texto), ni el .exe compilado
(el .exe va en «Releases», no en el repositorio). Genera además README.md, requirements.txt, .gitignore, un flujo de
GitHub Actions que compila MHEditor.exe y lo adjunta a cada release, y un script local para compilarlo.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), 'making-history-github')

DOCS = ['AGENTS.md', 'EDITOR.md', 'MAPA_FORMATO.md', 'REVERSING_NOTAS.md', 'ESCENARIOS_NOTAS.md', 'GOLD_NOTAS.md', 'tools/MH2_NST_FORMATO.md']
LAUNCHERS = ['Region Editor.bat', 'Scenario Editor.bat', 'Editor (window).bat', 'Scenario Editor (window).bat', 'Game Log.bat']
SKIP_PY = {'probe2.py', 'probe_regions.py'}          # pruebas sueltas de ingeniería inversa

README = """# Making History 1 & Gold Editor 2.2

Map (regionpack), scenario and image editor for **Making History: The Calm and The Storm (MH1)** and **Making History Gold**.

> Fan project, not affiliated with Muzzy Lane. It ships no game files: you need the game installed (Steam, or the
> Muzzy Lane installer in `C:\\Program Files (x86)\\Muzzy Lane Software\\...`; the editor finds it on its own).

- **Download / updates:** [Releases](https://github.com/avlopezparra/making-history-1-and-gold-editor/releases/)
- **Community:** [Discord](https://discord.com/invite/gFJyCjWEnr)
- **Report bugs:** alopezcl@protonmail.com (or open an issue)

Made by Alejandro Víctor López Parra (@avlopezparra), 2026. **Version 2.2**.

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

Environment variables: `MH_ROOT` (where projects and logs are kept), `MH_STEAM_COMMON` (a `steamapps\\common` folder in another Steam
library), `MH_GAME_MH1` / `MH_GAME_GOLD` (game folder of a non-Steam install), `MH_PORT` (port of the `.exe`).

**Troubleshooting**
- *"An editor is already open..."*: a server already uses that port; open it in the browser or close it first.
- *Game not found*: check the folder contains `Modern Europe`, or set `MH_GAME_MH1` / `MH_GAME_GOLD` / `MH_STEAM_COMMON`.
- *Old page after updating*: restart the server and reload with `Ctrl+F5`.
- **Back up** your game and scenarios before you start.

## Build MHEditor.exe
```
compilar_exe.bat          (or:  pip install -r requirements.txt  &&  python tools/build_exe.py)
```
The result goes to `MHEditor\\` (exe + `_internal`); zip that whole folder as `MHEditor.zip`. Pushing a `v*` tag runs
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
"""

REQ = """# Making History 1 & Gold Editor
pywebview>=6.0
pyinstaller>=6.10
shapely>=2.0
numpy>=1.26
Pillow>=10.0
"""

GITIGNORE = """__pycache__/
*.pyc
# compilación y datos de trabajo (nunca al repositorio)
_build/
MHEditor/
*.zip
editor_proyecto*/
_proyecto_ui*/
backup/
mapa*/
mods/
logs/
history/
tiles/
idioma.json
ultimo_regionpack.json
editor_juego.json
# archivos del juego y capturas
*.bin
*.brd
*.nts
*.tga
"""

COMPILAR = """@echo off
rem Compila MHEditor.exe (carpeta MHEditor\\). Requiere Python 3.12 o superior.
cd /d "%~dp0"
python -m pip install -r requirements.txt
python tools\\build_exe.py
pause
"""

WORKFLOW = """name: Compilar MHEditor.exe
on:
  push:
    tags: ['v*']
  workflow_dispatch:
permissions:
  contents: write
jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install -r requirements.txt
      - run: python tools/build_exe.py
      - run: Compress-Archive -Path MHEditor -DestinationPath MHEditor.zip
        shell: powershell
      - uses: actions/upload-artifact@v4
        with:
          name: MHEditor
          path: MHEditor.zip
      - uses: softprops/action-gh-release@v2
        if: startsWith(github.ref, 'refs/tags/')
        with:
          files: MHEditor.zip
          generate_release_notes: true
"""


def put(rel, text):
    p = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8', newline='\n' if not rel.endswith('.bat') else '\r\n') as f:
        f.write(text)


def main():
    if os.path.exists(OUT):
        if os.listdir(OUT) and not os.path.exists(os.path.join(OUT, '.git')) and not os.path.exists(os.path.join(OUT, 'compilar_exe.bat')):
            raise SystemExit('la carpeta de salida ya existe y no está vacía: %s' % OUT)
        for n in os.listdir(OUT):                       # se conserva .git si ya hay un repositorio
            if n != '.git':
                shutil.rmtree(os.path.join(OUT, n)) if os.path.isdir(os.path.join(OUT, n)) else os.remove(os.path.join(OUT, n))
    n = 0
    for f in sorted(os.listdir(HERE)):
        if f.endswith('.py') and f not in SKIP_PY:
            os.makedirs(os.path.join(OUT, 'tools'), exist_ok=True)
            shutil.copy2(os.path.join(HERE, f), os.path.join(OUT, 'tools', f)); n += 1
    shutil.copytree(os.path.join(HERE, 'editor'), os.path.join(OUT, 'tools', 'editor'), ignore=shutil.ignore_patterns('__pycache__'))
    for f in DOCS + LAUNCHERS:
        if os.path.exists(os.path.join(ROOT, f)):
            os.makedirs(os.path.dirname(os.path.join(OUT, f)) or OUT, exist_ok=True)
            shutil.copy2(os.path.join(ROOT, f), os.path.join(OUT, f)); n += 1
    put('README.md', README)
    put('requirements.txt', REQ)
    put('.gitignore', GITIGNORE)
    put('compilar_exe.bat', COMPILAR)
    put('.github/workflows/build.yml', WORKFLOW)
    print('Listo: %s  (%d archivos de código y documentos)' % (OUT, n))
    print('Siguiente: cd "%s" && git init && git add . && git commit -m "Primera versión" && git branch -M main' % OUT)
    print('           git remote add origin https://github.com/avlopezparra/making-history-1-and-gold-editor.git && git push -u origin main')


if __name__ == '__main__':
    main()
