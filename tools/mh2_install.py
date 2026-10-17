"""Instala el regionpack WorldMH2 (mh2/WorldMH2) en el juego: copia World -> WorldMH2 y encima pone el mapa nuevo.

    python mh2_install.py            # solo si el juego esta cerrado; no toca World ni ningun escenario
Despues, en el editor de escenarios: Global Data › Regionpack (o «Adecuar» en el de regiones) con WorldMH2, y elige como repartir
la poblacion. Para quitarlo: borrar la carpeta Maps\WorldMH2.
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
