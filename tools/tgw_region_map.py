"""Builds tools/data/tgw_sww_regions.json: how the regions of Making History: The Great War / The Second World War (one
shared map) fall onto WorldMoreRegions (made from MH2's map). Offline; run again only if the games' map changes.

    python tools/tgw_region_map.py "<...>/The Great War/content/Making History TGW"

'into': TGW region -> WorldMoreRegions region it goes into: the one of the same name (if their shapes touch), else the
        one of the same kind (land / sea) that covers most of it.
'from': WorldMoreRegions land region that no TGW region goes into -> TGW land region covering most of it (gives the owner).
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shapely.geometry import Polygon, box
from shapely.affinity import translate
from shapely.ops import unary_union
from shapely.strtree import STRtree
import mh2_regions
import scenario_layers as L

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'tgw_sww_regions.json')
SEA_TERRAIN = {'Ocean', 'PolarSea', 'Lake'}


def key(n):
    return re.sub(r'[^a-z0-9]', '', n.lower())


def shapes(base):
    """{key(name): geometry} from the game's Regions.nst (lon/lat; the part past 180E moved to the west)."""
    out = {}
    for name, (verts, idx) in mh2_regions.parse(os.path.join(base, 'modules', 'mh2 map', 'world map', 'models', 'Regions.nst')).items():
        tris = [Polygon([verts[idx[i]], verts[idx[i + 1]], verts[idx[i + 2]]]) for i in range(0, len(idx), 3)]
        g = unary_union([t if t.is_valid else t.buffer(0) for t in tris if t.area > 0]).buffer(0)
        if g.bounds[2] > 180:
            g = unary_union([g.intersection(box(-360, -90, 180, 90)), translate(g.intersection(box(180, -90, 540, 90)), xoff=-360)])
        out[key(name)] = g
    return out


def main(base):
    xml = open(os.path.join(base, 'modules', 'mh2 map', 'world map', 'regions.xml'), encoding='utf-8', errors='replace').read()
    tgw = {}
    for blk in re.findall(r'<object type="gs_tbg.Region".*?</object>', xml, flags=re.S):
        n, t = re.search(r'strName" value="([^"]+)"', blk), re.search(r'tmplTerrain" value="sd\.([^"]+)"', blk)
        tgw[n.group(1)] = (t.group(1) if t else '') in SEA_TERRAIN
    shp = shapes(base)
    pm = L.pack_map('WorldMoreRegions')
    wmr = {n: pm.geom(n) for n in pm.sea if pm.geom(n) is not None}
    wkey = {key(n): n for n in wmr}
    trees = {}
    for sea in (False, True):
        names = [n for n in wmr if pm.sea[n] == sea]
        trees[sea] = (names, STRtree([wmr[n] for n in names]))

    def best(g, sea):
        names, tree = trees[sea]
        c = [(g.intersection(wmr[names[i]]).area, names[i]) for i in tree.query(g)]
        return max(c)[1] if c and max(c)[0] > 0 else None
    into = {}
    for n, sea in tgw.items():
        g, same = shp.get(key(n)), wkey.get(key(n))
        if same and g is not None and g.intersects(wmr[same]):
            into[n] = same
        elif g is not None:
            kind = pm.sea[same] if same else sea
            into[n] = best(g, kind) or best(g, not kind) or same     # lakes and islands WMR draws the other way
    hit = set(into.values())
    land = [n for n in tgw if not tgw[n] and shp.get(key(n)) is not None]
    ltree = STRtree([shp[key(n)] for n in land])
    frm = {}
    for w, g in wmr.items():
        if pm.sea[w] or w in hit:
            continue
        c = [(g.intersection(shp[key(land[i])]).area, land[i]) for i in ltree.query(g)]
        if c and max(c)[0] > 0:
            frm[w] = max(c)[1]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({'into': {k: v for k, v in sorted(into.items()) if v and v != k}, 'from': dict(sorted(frm.items()))},
              open(OUT, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(len(tgw), 'TGW regions;', sum(1 for k, v in into.items() if v != k), 'renamed/merged;', len(frm), 'WMR regions take their owner from TGW;',
          'unmapped:', [k for k, v in into.items() if not v])


if __name__ == '__main__':
    main(sys.argv[1])
