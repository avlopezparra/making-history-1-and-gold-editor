"""Colores por tipo de terreno para exportar el mapa (imagen y GeoJSON).

Cada región de tierra lleva el color de su terreno (el del escenario si se indica uno; si no, el que codifica el propio mapa:
1 llanura, 2 colinas, 3 montañas, 4 desierto); el mar va en celeste y lo que no es ninguna región (los huecos, «empty») en blanco.
"""
from PIL import Image, ImageDraw

from fix_texture import SIZE, TILE_DEG

TERRAIN_COLORS = {'Plains': '#a3e635', 'Hills': '#ca8a04', 'Mountains': '#78716c', 'Forest': '#15803d', 'Jungle': '#065f46',
                  'Desert': '#fcd34d', 'Tundra': '#d1d5db'}
SEA_COLOR = '#87ceeb'          # celeste
EMPTY_COLOR = '#ffffff'        # sin región (hueco): blanco
BY_TYPE = {1: 'Plains', 2: 'Hills', 3: 'Mountains', 4: 'Desert'}


def terrain_of(project, scen=None):
    """{nombre de región: terreno o 'Sea'} (con el terreno del escenario si se pasa)."""
    from transfer import SEA
    import scenario_core as sc
    sct = {}
    if scen is not None:
        sct = {sc.prop(r, 'strName'): sc.prop(r, 'strTerrain') for r in scen.regions(sea=False)}
    out = {}
    for g in project.m['regions']:
        name = project.rname(g.index)
        out[name] = 'Sea' if g.u_type == SEA else (sct.get(name) or BY_TYPE.get(g.u_type, 'Plains'))
    return out


def color_of(terrain):
    return SEA_COLOR if terrain == 'Sea' else TERRAIN_COLORS.get(terrain, TERRAIN_COLORS['Plains'])


def legend():
    return {'vacio': EMPTY_COLOR, 'mar': SEA_COLOR, 'terrenos': dict(TERRAIN_COLORS),
            'nota': 'Cada región lleva el color de su terreno; el mar va en celeste y lo que no es ninguna región (hueco) en blanco.'}


def _area(ring):
    return abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1] for i in range(len(ring)))) / 2


def terrain_layer(project, bbox, level, scen=None):
    """Imagen RGB de la zona (mismo tamaño y zona que la exportación del fondo) con cada región del color de su terreno."""
    x0, y0, x1, y1 = bbox
    s = SIZE >> level
    ppd = s / TILE_DEG
    W, H = int(round((x1 - x0) * ppd)), int(round((y1 - y0) * ppd))
    img = Image.new('RGB', (W, H), EMPTY_COLOR)
    d = ImageDraw.Draw(img)
    terr = terrain_of(project, scen)
    items = []
    for g in project.m['regions']:
        main = project.outline(g.index)[0]
        if not main:
            continue
        items.append((sum(_area(p[0]) for p in main), project.rname(g.index), main))
    items.sort(key=lambda t: -t[0])                  # las grandes primero: las pequeñas se pintan encima de sus huecos
    px = lambda ring: [((x - x0) * ppd, (y1 - y) * ppd) for x, y in ring]
    for _a, name, main in items:
        col = color_of(terr.get(name))
        for poly in main:
            xs = [p[0] for p in poly[0]]
            ys = [p[1] for p in poly[0]]
            if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
                continue
            d.polygon(px(poly[0]), fill=col)
            for hole in poly[1:]:
                d.polygon(px(hole), fill=EMPTY_COLOR)
    return img
