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

DOCS = ['AGENTS.md', 'EDITOR.md', 'MAPA_FORMATO.md', 'REVERSING_NOTAS.md', 'ESCENARIOS_NOTAS.md', 'GOLD_NOTAS.md', 'CHANGELOG_3.0.md', 'CHANGELOG_3.1.md', 'CHANGELOG_3.3.md', 'CHANGELOG_3.4.md', 'CHANGELOG_3.5.md', 'CHANGELOG_3.6.md', 'tools/MH2_NST_FORMATO.md']
LAUNCHERS = ['Region Editor.bat', 'Scenario Editor.bat', 'Editor (window).bat', 'Scenario Editor (window).bat', 'Game Log.bat']
SKIP_PY = {'probe2.py', 'probe_regions.py', 'ai_chat.py', 'release_jp.py'}  # pruebas y herramientas locales de publicación

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
      - name: Zip (MHEditor.<version>.zip + skill)
        shell: powershell
        run: |
          $v = [regex]::Match((Get-Content tools/editor/i18n.js -Raw), "const VERSION = '([^']+)'").Groups[1].Value
          if (-not $v) { throw 'VERSION not found in tools/editor/i18n.js' }
          Copy-Item skill/making-history-modding/SKILL.md MHEditor/Making_History_1_and_Gold_Editing_Skill.md
          Copy-Item tools/data/NIFSKOPE-LICENSE.md MHEditor/NIFSKOPE-LICENSE.md
          Compress-Archive -Path MHEditor -DestinationPath "MHEditor.$v.zip"
      - uses: actions/upload-artifact@v4
        with:
          name: MHEditor
          path: MHEditor.*.zip
      - uses: softprops/action-gh-release@v2
        if: startsWith(github.ref, 'refs/tags/')
        with:
          files: MHEditor.*.zip
          body_path: CHANGELOG_3.6.md
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
        for n in os.listdir(OUT):                       # conserva .git y la licencia del repositorio
            if n not in ('.git', 'LICENSE'):
                shutil.rmtree(os.path.join(OUT, n)) if os.path.isdir(os.path.join(OUT, n)) else os.remove(os.path.join(OUT, n))
    n = 0
    for f in sorted(os.listdir(HERE)):
        if f.endswith('.py') and f not in SKIP_PY:
            os.makedirs(os.path.join(OUT, 'tools'), exist_ok=True)
            shutil.copy2(os.path.join(HERE, f), os.path.join(OUT, 'tools', f)); n += 1
    shutil.copytree(os.path.join(HERE, 'editor'), os.path.join(OUT, 'tools', 'editor'), ignore=shutil.ignore_patterns('__pycache__', 'ai_chat.js'))
    shutil.copytree(os.path.join(HERE, 'data'), os.path.join(OUT, 'tools', 'data'))
    shutil.copytree(os.path.join(ROOT, 'skill'), os.path.join(OUT, 'skill'))   # skill de Claude Code
    for f in DOCS + LAUNCHERS:
        if os.path.exists(os.path.join(ROOT, f)):
            os.makedirs(os.path.dirname(os.path.join(OUT, f)) or OUT, exist_ok=True)
            shutil.copy2(os.path.join(ROOT, f), os.path.join(OUT, f)); n += 1
    shutil.copy2(os.path.join(ROOT, 'README_github.md'), os.path.join(OUT, 'README.md'))
    put('requirements.txt', REQ)
    put('.gitignore', GITIGNORE)
    put('compilar_exe.bat', COMPILAR)
    put('.github/workflows/build.yml', WORKFLOW)
    print('Listo: %s  (%d archivos de código y documentos)' % (OUT, n))
    print('Siguiente: cd "%s" && git init && git add . && git commit -m "Primera versión" && git branch -M main' % OUT)
    print('           git remote add origin https://github.com/avlopezparra/making-history-1-and-gold-editor.git && git push -u origin main')


if __name__ == '__main__':
    main()
