"""«Vanilla» copy of World as reference (what the unmodified game looks like), even if the user changed World.

The backup/vanilla_World/ folder (xml/ with the three original binaries, map.xml and properties.xml) is assembled from backup/mapa_original
(which the editor fills with the original of everything it touches) plus World's «default game file» files; the original
textures of the touched tiles are in backup/mapa_original/OperationalTerrain and the rest, untouched, in World/art.
It is read-only: the editor never modifies it."""
import os
import shutil

BINARIES = ('regions.bin', 'borders.brd', 'regions.nts')


def ensure(orig_dir, world_dir, dest):
    """Creates (or completes) the reference folder; returns its path or None if there are no originals."""
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
    """Original texture of a tile: the backup if the editor touched it; otherwise World's (untouched)."""
    p = os.path.join(orig_dir, 'OperationalTerrain', name)
    return p if os.path.exists(p) else os.path.join(world_dir, 'art', 'OperationalTerrain', name)
