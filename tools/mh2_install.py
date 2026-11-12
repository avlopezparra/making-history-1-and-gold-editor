r"""Installs the WorldMH2 regionpack (mh2/WorldMH2) in the game: copies World -> WorldMH2 and puts the new map on top.

    python mh2_install.py            # only if the game is closed; does not touch World or any scenario
Then, in the scenario editor: Global Data › Regionpack (or «Adecuar» in the region editor) with WorldMH2, and choose how to distribute
the population. To remove it: delete the Maps\WorldMH2 folder.
"""
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import editor_core

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mh2', 'WorldMH2')


def main():
    dst = os.path.join(editor_core.MAPS, 'WorldMH2')
    if os.path.exists(dst):
        raise SystemExit('ya existe %s (borrala a mano si quieres reinstalar)' % dst)
    if not os.path.exists(os.path.join(SRC, 'xml', 'regions.bin')):
        raise SystemExit('falta %s: ejecuta antes mh2_build_pack.py' % SRC)
    shutil.copytree(os.path.join(editor_core.MAPS, 'World'), dst)
    for root, _, files in os.walk(SRC):
        rel = os.path.relpath(root, SRC)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(dst, rel, f))
    print('instalado en', dst)


if __name__ == '__main__':
    main()
