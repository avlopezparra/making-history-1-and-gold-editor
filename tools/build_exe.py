"""Builds MHEditor.exe (folder making-history/MHEditor/) with PyInstaller.

Usage: python build_exe.py      (requires: python -m pip install --user pywebview pyinstaller)
The executable uses the parent folder (making-history) as its data folder, so projects, backups and logs
are the same as with the .bat files.
"""
import glob
import os
import shutil
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
WORK = os.path.join(ROOT, '_build')


def make_icon(path):
    """Simple icon: a globe with «MH»."""
    sizes = [256, 128, 64, 48, 32, 16]
    img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 248, 248), fill=(23, 54, 98), outline=(212, 175, 55), width=10)
    for k in (-60, 0, 60):
        d.arc((70 + k // 2, 18, 186 - k // 2, 238), 0, 360, fill=(212, 175, 55), width=4)
    d.line((18, 128, 238, 128), fill=(212, 175, 55), width=4)
    try:
        font = ImageFont.truetype('arialbd.ttf', 92)
    except OSError:
        font = ImageFont.load_default()
    d.text((128, 128), 'MH', fill=(255, 255, 255), font=font, anchor='mm', stroke_width=5, stroke_fill=(23, 54, 98))
    img.save(path, sizes=[(s, s) for s in sizes])


def main():
    import PyInstaller.__main__
    os.makedirs(WORK, exist_ok=True)
    ico = os.path.join(WORK, 'mheditor.ico')
    # with MHEditor open, PyInstaller would half-delete its folder (files in use) and leave it broken
    import subprocess
    running = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq MHEditor.exe', '/NH'], capture_output=True).stdout.decode('latin-1', 'replace')
    if 'MHEditor.exe' in running:
        raise SystemExit('MHEditor está abierto: ciérralo y vuelve a compilar (no se ha tocado nada).')
    make_icon(ico)
    # modules the server imports inside functions (PyInstaller does not see them by itself)
    hidden = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(HERE, '*.py'))
              if os.path.basename(p) not in ('build_exe.py', 'mheditor_app.py', 'editor_ventana.py', 'exportar_github.py')]
    args = [os.path.join(HERE, 'mheditor_app.py'), '--name', 'MHEditor', '--onedir', '--windowed', '--noconfirm',
            '--icon', ico, '--distpath', ROOT, '--workpath', os.path.join(WORK, 'work'), '--specpath', WORK,
            '--paths', HERE, '--add-data', os.path.join(HERE, 'editor') + os.pathsep + 'editor',
            '--add-data', os.path.join(HERE, 'data') + os.pathsep + 'data',   # nif.xml (lector de modelos 3D)
            # the AI chat reads the routes from the server code (ai_chat.routes)
            '--add-data', os.path.join(HERE, 'editor_server.py') + os.pathsep + '.',
            '--collect-submodules', 'webview', '--collect-data', 'webview']
    for h in hidden:
        args += ['--hidden-import', h]
    PyInstaller.__main__.run(args)
    # the intermediate exe in _build\work does not work alone (lacks _internal): deleted so it is not opened by mistake
    import shutil
    shutil.rmtree(os.path.join(WORK, 'work'), ignore_errors=True)
    print('\nListo:', os.path.join(ROOT, 'MHEditor', 'MHEditor.exe'))


if __name__ == '__main__':
    main()
