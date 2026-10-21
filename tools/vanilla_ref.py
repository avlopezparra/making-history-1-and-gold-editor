"""Copia «vanilla» de World como referencia (cómo es el juego sin modificar), aunque el usuario haya cambiado World.

La carpeta backup/vanilla_World/ (xml/ con los tres binarios originales, map.xml y properties.xml) se arma desde backup/mapa_original
(que el editor llena con el original de todo lo que toca) más los archivos «default game file» de World; las texturas
originales de los tiles tocados están en backup/mapa_original/OperationalTerrain y el resto, sin tocar, en World/art.
Es solo lectura: el editor nunca la modifica."""
import os
import shutil

BINARIES = ('regions.bin', 'borders.brd', 'regions.nts')


def ensure(orig_dir, world_dir, dest):
    """Crea (o completa) la carpeta de referencia; devuelve su ruta o None si no hay originales."""
    xml = os.path.join(dest, 'xml')
    if not all(os.path.exists(os.path.join(orig_dir, b)) for b in BINARIES):
        return None
    os.makedirs(xml, exist_ok=True)
    for b in BINARIES:
        if not os.path.exists(os.path.join(xml, b)):
            shutil.copy2(os.path.join(orig_dir, b), os.path.join(xml, b))
    wx = os.path.join(world_dir, 'xml')
    for target, cands in (('map.xml', ('map (default game file).xml', 'map.xml')), ('properties.xml', ('properties.xml',))):
        if not os.path.exists(os.path.join(xml, target)):
            for c in cands:
                if os.path.exists(os.path.join(wx, c)):
                    shutil.copy2(os.path.join(wx, c), os.path.join(xml, target))
                    break
    return dest


def tile_path(name, orig_dir, world_dir):
    """Textura original de un tile: la copia de seguridad si el editor la tocó; si no, la de World (sin tocar)."""
    p = os.path.join(orig_dir, 'OperationalTerrain', name)
    return p if os.path.exists(p) else os.path.join(world_dir, 'art', 'OperationalTerrain', name)
