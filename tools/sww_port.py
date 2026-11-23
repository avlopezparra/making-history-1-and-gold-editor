"""Port the MH1 regionpack WorldHOI4 to Making History: The Second World War (SWW) and fit an SWW scenario onto it.

SWW runs on the Making History II engine: a map is a Locust module ('mh2 map') and a scenario a 'game' module that imports
it. This builds one mod folder (<out>/<mod>) with:
  modules/mh2 map/world hoi4/   map.xml (MapRegions, MapEdges), regions.xml, models.xml, models/*.dae, textures/minimap.png
  modules/game/<scenario>/      copy of an SWW scenario (default Building for War, 1936) with every region reference
                                moved to the WorldHOI4 regions (by overlap / by position)
  mod_playable.xml              what the game's mod menu lists
WorldHOI4 is drawn in its own frame; proyeccion.json (real lon/lat -> map) is inverted so the regions sit on real lon/lat,
like SWW's terrain tiles and the scenario's city/airbase positions. Terrain tiles are the vanilla world map ones.
Reads only; writes only under --out. Install = copy <out>/<mod> to <SWW>/content/mods (see --install).
"""
import argparse, json, os, pickle, re, shutil, sys, unicodedata
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import Polygon, MultiPolygon, Point, box
from shapely.ops import unary_union, nearest_points
import mhmap, export_map, mh2_regions, gamepaths

SWW = gamepaths.sww_path()
if not SWW:
    raise SystemExit('Making History: The Second World War no está instalado (o define MH_GAME_SWW)')
MODS = os.path.join(SWW, 'content', 'Making History SWW', 'modules')
VMAP = os.path.join(MODS, 'mh2 map', 'world map')
MAP_MODULE = 'world hoi4'
Z = 0.27                      # height SWW uses for every position on the map
STEP = 0.35                   # spacing of SWW's unit slots (vecPositions)


# ------------------------------------------------------------------------------------------------ geometry helpers
def valid(g):
    g = g if g.is_valid else g.buffer(0)
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    return unary_union([p for p in getattr(g, 'geoms', []) if isinstance(p, (Polygon, MultiPolygon))])


def wrap180(g):
    """SWW meshes run past 180E; folds that part back to -180.. so both maps compare in one frame."""
    if g.is_empty or g.bounds[2] <= 180:
        return g
    east = g.intersection(box(180, -90, 540, 90))
    return valid(unary_union([g.intersection(box(-180, -90, 180, 90)), shapely.affinity.translate(east, -360)]))


def ident(name):
    """Region name -> Locust identifier (ASCII CamelCase), as SWW's strName ('BayOfBangkok')."""
    a = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return ''.join(w[:1].upper() + w[1:] for w in re.split(r'[^A-Za-z0-9]+', a) if w) or 'Region'


class Inverse:
    """Map coordinates of a pack drawn in its own frame -> real lon/lat, inverting proyeccion.json
    (x depends only on lon and y on lat per lon column, both monotonic, so 1-D interpolation is exact)."""
    def __init__(self, d):
        self.X, self.Y = np.asarray(d['x'], float), np.asarray(d['y'], float)
        self.lon0, self.lat0, self.step = d['lon0'], d['lat0'], d['step']
        assert np.ptp(self.X, axis=0).max() < 1e-6, 'proyeccion.json: x depends on latitude'
        assert (np.diff(self.X[0]) > 0).all() and (np.diff(self.Y, axis=0) > 0).all(), 'proyeccion.json not monotonic'
        self.lons = self.lon0 + self.step * np.arange(self.X.shape[1])
        self.lats = self.lat0 + self.step * np.arange(self.Y.shape[0])

    def __call__(self, c):
        c = np.asarray(c, float).reshape(-1, 2)
        lon = np.clip(np.interp(c[:, 0], self.X[0], self.lons), -180, 180)
        f = np.clip((lon - self.lon0) / self.step, 0, len(self.lons) - 1 - 1e-9)
        j = f.astype(int)
        t = f - j
        lat = np.empty(len(c))
        for jj in np.unique(j):
            k = j == jj
            a = np.interp(c[k, 1], self.Y[:, jj], self.lats)
            b = np.interp(c[k, 1], self.Y[:, jj + 1], self.lats)
            lat[k] = a * (1 - t[k]) + b * t[k]
        return np.column_stack([lon, lat])


# ------------------------------------------------------------------------------------------------ inputs
def load_pack(folder):
    """WorldHOI4 regions in real lon/lat: name, sea, polygon, mesh (vertices, triangle indices), neighbours."""
    inv = Inverse(json.load(open(os.path.join(folder, 'proyeccion.json'), encoding='utf-8')))
    m = mhmap.load_map(os.path.join(folder, 'xml'))
    out, used = [], set()
    for g in m['regions']:
        polys = [valid(Polygon(p[0], p[1:])) for p in export_map.region_polygons(m, g.index) if len(p[0]) > 3]
        poly = valid(shapely.transform(unary_union(polys), inv)) if polys else Polygon()
        verts, idx = [], []
        for s in mhmap.region_shapes(m, g.index):
            base = len(verts)
            verts += [tuple(v) for v in inv([v[:2] for v in s.vertices])]
            idx += [base + i for i in s.indices]
        sid = ident(g.name)
        while sid in used:
            sid += 'X'
        used.add(sid)
        out.append({'i': g.index, 'name': g.name, 'id': sid, 'sea': g.u_type == export_map.SEA, 'poly': poly,
                    'verts': verts, 'tris': idx, 'nbs': sorted(set(g.neighbors) - {g.index})})
    return out


def load_vanilla():
    """SWW world map regions: id -> {poly, terrain, size}."""
    ref = lambda n: open(os.path.join(VMAP, n), encoding='utf-8').read()
    node = dict(re.findall(r'name="(ModelTmplRegion[^"]+)"\s*>\s*<property name="tmplFile"[^>]*>\s*'
                           r'<property name="strNodeName" value="([^"]+)Node"', ref('models.xml')))
    models = defaultdict(list)
    for blk in re.findall(r'<object type="gs_tbg.MapRegion".*?</object>', ref('map.xml'), re.S):
        rid = re.search(r'refRegion" value="([^"]+)', blk).group(1)
        models[rid] += [node[t] for t in re.findall(r'tmplDisplayModel" value="([^"]+)', blk) if t in node]
    mesh = mh2_regions.parse(os.path.join(VMAP, 'models', 'Regions.nst'))
    regs = {}
    for blk in re.findall(r'<object type="gs_tbg.Region".*?</object>', ref('regions.xml'), re.S):
        rid = re.search(r'strName" value="([^"]+)', blk).group(1)
        tris = []
        for n in models.get(rid, []):
            v, ix = mesh.get(n) or (None, None)
            if v and ix:
                tris += [Polygon([v[ix[k]], v[ix[k + 1]], v[ix[k + 2]]]) for k in range(0, len(ix), 3)]
        tris = [t for t in tris if t.area > 1e-12]
        regs[rid] = {'poly': wrap180(valid(unary_union(tris))) if tris else Polygon(),
                     'terrain': re.search(r'tmplTerrain" value="([^"]+)', blk).group(1),
                     'size': int(re.search(r'nRegionSize" value="(\d+)', blk).group(1))}
    return regs


# ------------------------------------------------------------------------------------------------ matching
def seaish(r):
    return r['terrain'] in ('sd.Ocean', 'sd.Lake')


def match(pack, van):
    """old2new: every SWW region -> the WorldHOI4 region it overlaps most (same kind first);
    primary: every WorldHOI4 region -> the SWW region that overlaps it most (same kind first), or the nearest one."""
    tree = shapely.STRtree([p['poly'] for p in pack])
    ov = defaultdict(dict)                         # ov[new index][old id] = shared area
    old2new = {}
    for oid, o in van.items():
        if o['poly'].is_empty:
            continue
        best = {}
        for k in tree.query(o['poly']):
            a = pack[k]['poly'].intersection(o['poly']).area
            if a > 0:
                ov[k][oid] = a
                best[k] = a
        same = {k: a for k, a in best.items() if pack[k]['sea'] == seaish(o)}
        cand = same or best or {int(tree.nearest(o['poly'].representative_point())): 1}
        old2new[oid] = max(cand, key=cand.get)
    land = [oid for oid, o in van.items() if not seaish(o) and not o['poly'].is_empty]
    sea = [oid for oid, o in van.items() if seaish(o) and not o['poly'].is_empty]
    ltree, stree = shapely.STRtree([van[i]['poly'] for i in land]), shapely.STRtree([van[i]['poly'] for i in sea])
    primary = {}
    for k, p in enumerate(pack):
        same = {o: a for o, a in ov[k].items() if seaish(van[o]) == p['sea']}
        if same:
            primary[k] = max(same, key=same.get)
        elif not p['poly'].is_empty:
            ids, t = (sea, stree) if p['sea'] else (land, ltree)
            primary[k] = ids[int(t.nearest(p['poly'].representative_point()))]
    return old2new, primary, ov


def lattice(poly, n):
    """Up to n of SWW's diamond-lattice slots inside poly, closest to its representative point first."""
    c = poly.representative_point()
    inner = poly.buffer(-STEP / 4)
    inner = inner if inner.area > 0 else poly
    x0, y0, x1, y1 = poly.bounds
    pts = []
    for i in range(int((x0 - c.x) / STEP) - 1, int((x1 - c.x) / STEP) + 2):
        for j in range(int((y0 - c.y) / STEP) - 1, int((y1 - c.y) / STEP) + 2):
            if (i + j) % 2 == 0:
                q = Point(c.x + i * STEP, c.y + j * STEP)
                if inner.contains(q):
                    pts.append(q)
    pts.sort(key=lambda q: q.distance(c))
    return [(q.x, q.y) for q in pts[:n]] or [(c.x, c.y)]


def inside(poly, xy):
    """xy if it lies in poly, else the nearest point a little inside it."""
    p = Point(xy)
    if poly.is_empty or poly.contains(p):
        return xy
    inner = poly.buffer(-0.05)
    q = nearest_points(inner if inner.area > 0 else poly, p)[0]
    return (q.x, q.y)


def vec(xy):
    return '[%.6f, %.6f, %s]' % (xy[0], xy[1], Z)


# ------------------------------------------------------------------------------------------------ map module
DAE = '''<?xml version="1.0"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
    <asset><up_axis>Z_UP</up_axis></asset>
    <library_materials><material id="LineColorID" name="LineColor"><instance_effect url="#LineColor-effect"/></material></library_materials>
    <library_effects><effect id="LineColor-effect" name="LineColor-effect"><profile_COMMON><technique sid="COMMON"><phong>
        <emission><color>0 0 0 0</color></emission><ambient><color>0 0 0 1</color></ambient><diffuse><color>0 0 0 1</color></diffuse>
        <specular><color>0 0 0 1</color></specular><shininess><float>0</float></shininess><reflectivity><float>0</float></reflectivity>
        <transparent><color>0 0 0 1</color></transparent><transparency><float>1</float></transparency>
    </phong></technique></profile_COMMON></effect></library_effects>
    <library_geometries><geometry id="region" name="region"><mesh>
        <source id="region-positions" name="positions"><float_array id="region-positions-array" count="%(nf)d">%(pos)s</float_array>
            <technique_common><accessor count="%(nv)d" offset="0" source="#region-positions-array" stride="3">
                <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
        <source id="region-normals" name="normals"><float_array id="region-normals-array" count="3">0 0 1</float_array>
            <technique_common><accessor count="1" offset="0" source="#region-normals-array" stride="3">
                <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
        <vertices id="region-vertices"><input semantic="POSITION" source="#region-positions"/></vertices>
        <triangles count="%(nt)d" material="matRegion"><input offset="0" semantic="VERTEX" source="#region-vertices"/>
            <input offset="1" semantic="NORMAL" source="#region-normals"/><p>%(tri)s</p></triangles>
        <lines material="matLine" count="%(nl)d"><input offset="0" semantic="VERTEX" source="#region-vertices"/><p>%(lin)s</p></lines>
    </mesh></geometry></library_geometries>
    <library_visual_scenes><visual_scene id="VisualSceneNode" name="untitled"><node id="root" name="root">
        <instance_geometry url="#region"></instance_geometry>
        <instance_geometry url="#region"><bind_material><technique_common>
            <instance_material symbol="matLine" target="#LineColorID"/></technique_common></bind_material></instance_geometry>
    </node></visual_scene></library_visual_scenes>
    <scene><instance_visual_scene url="#VisualSceneNode"/></scene>
</COLLADA>
'''


def dae(p):
    """One region as COLLADA like SWW's grid map: the MH1 triangle mesh plus its outline as lines (the border)."""
    v, t = p['verts'], p['tris']
    key = [(round(x, 5), round(y, 5)) for x, y in v]
    cnt = defaultdict(int)
    for k in range(0, len(t), 3):
        a, b, c = t[k:k + 3]
        for e in ((a, b), (b, c), (c, a)):
            cnt[frozenset((key[e[0]], key[e[1]]))] += 1
    lines = []
    for k in range(0, len(t), 3):
        a, b, c = t[k:k + 3]
        for e in ((a, b), (b, c), (c, a)):
            if key[e[0]] != key[e[1]] and cnt[frozenset((key[e[0]], key[e[1]]))] == 1:
                lines += e
    return DAE % {'nf': 3 * len(v), 'nv': len(v), 'pos': ' '.join('%.5f %.5f 0' % xy for xy in v),
                  'nt': len(t) // 3, 'tri': ' '.join('%d 0' % i for i in t),
                  'nl': len(lines) // 2, 'lin': ' '.join(map(str, lines))}


LOCUST = '<?xml version="1.0" encoding="UTF-8"?>\n<locust xmlns="http://www.muzzylane.com/ml/schema/2009/04/locust">\n%s\n</locust>\n'
MAP_LMD = '''<?xml version="1.0" encoding="UTF-8"?>
<locustModule
	xmlns="http://www.muzzylane.com/ml/schema/2009/04/locust"
	type="mh2 map"
	name="%s"
	locustVersion="2.11"
>
	<import module="mlcore" default="true"/>
	<import module="lib:mlgame" as="mlgame"/>
	<import module="lib:mlevent" as="mlevent"/>
	<import module="lib:media" as="mlmedia"/>
	<import module="lib:media collada" as="collada"/>
	<import module="game system:turn based game" as="gs_tbg"/>
	<import module="mh2 data:shared_wwi" as="sd"/>

	<include>
		map.xml
		regions.xml
		models.xml
		textures.xml
	</include>
</locustModule>
'''


def esc(s):
    return s.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;')


def write_map(pack, van, primary, dest, minimap, pack_dir, tiles_rel):
    os.makedirs(os.path.join(dest, 'models'), exist_ok=True)
    os.makedirs(os.path.join(dest, 'textures'), exist_ok=True)
    open(os.path.join(dest, 'module.lmd'), 'w', encoding='utf-8').write(MAP_LMD % MAP_MODULE)
    regs, mregs, models, edges = [], [], [], []
    for k, p in enumerate(pack):
        open(os.path.join(dest, 'models', p['id'] + '.dae'), 'w', encoding='utf-8').write(dae(p))
        old = van.get(primary.get(k)) or {'terrain': 'sd.Ocean' if p['sea'] else 'sd.Plains', 'size': 4, 'poly': p['poly']}
        terrain = old['terrain'] if seaish(old) == p['sea'] else ('sd.Ocean' if p['sea'] else 'sd.Plains')
        size = max(1, min(40, round(old['size'] * (p['poly'].area / old['poly'].area) ** 0.5))) if old['poly'].area else old['size']
        slots = lattice(p['poly'], max(4, min(30, size + 2))) if not p['poly'].is_empty else [(0, 0)]
        regs.append('\t\t<object type="gs_tbg.Region" name="objRegions">\n\t\t\t<property name="strName" value="%s"/>\n'
                    '\t\t\t<property name="strDisplayName" value="%s"/>\n\t\t\t<property name="tmplTerrain" value="%s"/>\n'
                    '\t\t\t<property name="nRegionSize" value="%d" />\n%s\t\t</object>'
                    % (p['id'], esc(p['name']), terrain, size,
                       ''.join('\t\t\t<property name="vecPositions" value="%s" />\n' % vec(s) for s in slots)))
        models.append('\t<template type="collada.ColladaFileTemplate" name="tmplColladaFile%s">\n'
                      '\t\t<property name="fileSource" value="models/%s.dae" />\n\t</template>\n'
                      '\t<template type="collada.ModelTemplateCollada" name="ModelTmplRegion%s">\n'
                      '\t\t<property name="tmplFile" value="tmplColladaFile%s"/>\n\t</template>' % ((p['id'],) * 4))
        c = p['poly'].representative_point() if not p['poly'].is_empty else Point(0, 0)
        mregs.append('\t\t<object type="gs_tbg.MapRegion" name="objMapRegions">\n\t\t\t<property name="refRegion" value="%s"/>\n'
                     '\t\t\t<property name="tmplDisplayModel" value="ModelTmplRegion%s"/>\n'
                     '\t\t\t<property name="vecCenter" value="[%.6f, %.6f, 0.0]"/>\n\t\t</object>' % (p['id'], p['id'], c.x, c.y))
        for n in p['nbs']:
            if n > k:
                edges.append('\t\t<object type="gs_tbg.MapEdge" name="objMapEdges">\n\t\t\t<property name="refRegionA" value="%s"/>\n'
                             '\t\t\t<property name="refRegionB" value="%s"/>\n\t\t\t<property name="nWeight" value="1" />\n\t\t</object>'
                             % (p['id'], pack[n]['id']))
    t = tiles_rel.rstrip('/') + '/'
    head = '''	<template type="gs_tbg.TileDirsTemplate" name="tileDirs">
		<property name="fileModelsDir" value="%stiles"/>
		<property name="fileTextures" value="%sTileCombinedTextures.dat"/>
		<property name="eTileTextureFormat" value="RGB"/>
		<property name="fileCompressedTextures" value="%sTileCombinedTextures_DXT1.dat"/>
		<property name="eCompressedTileTextureFormat" value="DXT1"/>
	</template>
	<object type="gs_tbg.GameSysMap" name="MapGameSystem">
		<property name="vecMin" value="[-180.0, -90.0, 0.0]" />
		<property name="vecMax" value="[180.0, 90, 0.0]" />
		<property name="bWrapX" value="true"/>
		<property name="fWeightScale" value="100"/>
		<property name="nNumTileRows" value="12"/>
		<property name="nNumTileCols" value="24"/>
		<property name="nMaxTileDimension" value="1024"/>
		<property name="nNumTileLevels" value="5"/>
		<property name="tmplTileDirs" value="tileDirs"/>
		<property name="fSeaLevel" value="0.25"/>
		<property name="fLandLevel" value="0.27"/>
		<property name="fTerrainDetailMultiplierX" value="200.0"/>
		<property name="fTerrainDetailMultiplierY" value="100.0"/>
		<property name="tmplImgMiniMap" value="ImgMiniMap"/>
''' % (t, t, t)
    w = lambda n, s: open(os.path.join(dest, n), 'w', encoding='utf-8').write(s)
    w('map.xml', LOCUST % (head + '\n'.join(mregs + edges) + '\n\t</object>'))
    w('regions.xml', LOCUST % ('\t<object type="gs_tbg.GameSysRegion" name="RegionGameSystem">\n' + '\n'.join(regs) + '\n\t</object>'))
    w('models.xml', LOCUST % '\n'.join(models))
    w('textures.xml', open(os.path.join(VMAP, 'textures.xml'), encoding='utf-8').read().replace('textures/minimap.dds', 'textures/minimap.png'))
    minimap_png(minimap, pack_dir, os.path.join(dest, 'textures', 'minimap.png'))


def minimap_png(tga, pack_dir, out, w=512, h=256):
    """MH1 minimap (map frame -180..180 x -90..90) resampled to real lon/lat like SWW's minimap."""
    from PIL import Image
    import scenario_layers
    proj = scenario_layers.Projection.load(pack_dir)
    im = np.asarray(Image.open(tga).convert('RGB'))
    H, W = im.shape[:2]
    lon, lat = np.meshgrid(-180 + (np.arange(w) + .5) * 360 / w, 90 - (np.arange(h) + .5) * 180 / h)
    xy = proj.coords(np.column_stack([lon.ravel(), lat.ravel()]))
    px = np.clip(((xy[:, 0] + 180) / 360 * W).astype(int), 0, W - 1)
    py = np.clip(((90 - xy[:, 1]) / 180 * H).astype(int), 0, H - 1)
    Image.fromarray(im[py, px].reshape(h, w, 3)).save(out)


# ------------------------------------------------------------------------------------------------ scenario
REGION_PROP = re.compile(r'(<property name="(ref\w*Region\w*)" value=")([^"]+)(")')
REGION_REF = re.compile(r'gs_tbg\.Region::([A-Za-z0-9_]+)')
LIST_PROPS = ('refRegions', 'refJoiningRegions')


def remap_text(s, rename, stats):
    """Every region reference -> the new region; duplicated list entries inside one object are dropped."""
    def prop(m):
        v = rename.get(m.group(3))
        if v is None:
            stats['unknown'].add(m.group(3))
            return m.group(0)
        stats['refs'] += 1
        return m.group(1) + v + m.group(4)
    s = REGION_REF.sub(lambda m: 'gs_tbg.Region::' + rename.get(m.group(1), m.group(1)), REGION_PROP.sub(prop, s))
    out, seen = [], set()
    for line in s.split('\n'):
        if '<object' in line or '</object>' in line:
            seen = set()
        m = REGION_PROP.search(line)
        if m and m.group(2) in LIST_PROPS:
            if (m.group(2), m.group(3)) in seen:
                stats['dups'] += 1
                continue
            seen.add((m.group(2), m.group(3)))
        out.append(line)
    return '\n'.join(out)


OBJ = re.compile(r'(?m)^([ \t]*)<object type="gs_tbg.Region" name="objRegions">.*?\n\1</object>[ \t]*\n', re.S)  # own indent: skips nested objects
RES = re.compile(r'[ \t]*<object type="[^"]*" name="objResourceCapacities">.*?</object>[ \t]*\n', re.S)


def set_vec(obj, name, xy):
    return re.sub(r'(<property name="%s" value=")[^"]*(")' % name, lambda m: m.group(1) + vec(xy) + m.group(2), obj)


def build_regions_xml(s, pack, van, primary, ov, old2new, coastal):
    """GameSysRegion.xml rebuilt: one object per new region, copied from its primary SWW region; population spread by
    area, resources summed from the SWW regions it absorbs, positions kept inside the new outline."""
    found = list(OBJ.finditer(s))
    objs = {re.search(r'strName" value="([^"]+)', m.group(0)).group(1): m.group(0) for m in found}
    pop = defaultdict(float)
    for oid, o in objs.items():
        m = re.search(r'nPopulation" value="(\d+)', o)
        if m and oid in van and van[oid]['poly'].area:
            for k in ov:
                if oid in ov[k]:
                    pop[k] += int(m.group(1)) * ov[k][oid] / van[oid]['poly'].area
    res = defaultdict(dict)
    rtype = 'gs_tbg.ResourceCapacity'
    for oid, o in objs.items():
        for r in RES.findall(o):
            rtype = re.search(r'type="([^"]+)', r).group(1)
            t = re.search(r'tmplResource" value="([^"]+)', r).group(1)
            g = lambda n: int((re.search(n + r'" value="(-?\d+)', r) or [0, '0'])[1])
            acc = res[old2new.get(oid)].setdefault(t, [0, 0, 0])
            acc[0] += g('nBaseProduction'); acc[1] += g('nMaxProduction'); acc[2] = max(acc[2], g('nProspectingChance'))
    out = []
    for k, p in enumerate(pack):
        o = objs.get(primary.get(k)) or ('        <object type="gs_tbg.Region" name="objRegions">\n'
                                         '            <property name="strName" value="X"/>\n        </object>\n')
        o = re.sub(r'(strName" value=")[^"]+', lambda m: m.group(1) + p['id'], o, count=1)
        if not p['sea']:
            o = re.sub(r'(nPopulation" value=")\d+', lambda m: m.group(1) + str(int(pop[k])), o)
            for n in ('vecAirbaseLocation', 'vecPos'):
                m = re.search(r'%s" value="\[([-\d.e]+), ([-\d.e]+)' % n, o)
                if m:
                    o = set_vec(o, n, inside(p['poly'], (float(m.group(1)), float(m.group(2)))))
            o = RES.sub('', o)
            if res.get(k):
                ind = re.match(r'[ \t]*', o).group(0)
                block = ''.join('%s    <object type="%s" name="objResourceCapacities">\n'
                                '%s        <property name="tmplResource" value="%s"/>\n'
                                '%s        <property name="nBaseProduction" value="%d"/>\n'
                                '%s        <property name="nMaxProduction" value="%d"/>\n'
                                '%s        <property name="nProspectingChance" value="%d"/>\n%s    </object>\n'
                                % (ind, rtype, ind, t, ind, a, ind, b, ind, c, ind) for t, (a, b, c) in sorted(res[k].items()))
                cut = o.rstrip().rfind('\n') + 1
                o = o[:cut] + block + o[cut:]
            if k in coastal:
                if 'vecCoastalPos' in o:
                    o = set_vec(o, 'vecCoastalPos', coastal[k])
            else:
                o = re.sub(r'[ \t]*<property name="(vecCoastalPos|nCoastalRotation|nCoastalDefenseLevel)"[^>]*>[ \t]*\n', '', o)
        out.append(o)
    return s[:found[0].start()] + ''.join(out) + s[found[-1].end():]


def coastal_points(pack):
    """Land region -> a point just inside its coast (shared edge with a sea neighbour)."""
    out = {}
    for k, p in enumerate(pack):
        if p['sea'] or p['poly'].is_empty:
            continue
        seas = unary_union([pack[n]['poly'] for n in p['nbs'] if pack[n]['sea']])
        if seas.is_empty:
            continue
        edge = p['poly'].boundary.intersection(seas.buffer(0.02))
        q = edge.representative_point() if not edge.is_empty else nearest_points(p['poly'].boundary, seas)[0]
        out[k] = inside(p['poly'], (q.x, q.y))
    return out


def fix_cities(s, pack, stats):
    """Cities: region by position (moved inside if the coast differs); sea region = a neighbouring sea."""
    idx = {p['id']: k for k, p in enumerate(pack)}
    land = [k for k, p in enumerate(pack) if not p['sea'] and not p['poly'].is_empty]
    tree = shapely.STRtree([pack[k]['poly'] for k in land])

    def city(m):
        c = m.group(0)
        pm = re.search(r'vecPosition" value="\[([-\d.e]+), ([-\d.e]+)', c)
        if not pm or 'name="refRegion"' not in c:
            return c
        xy = (float(pm.group(1)), float(pm.group(2)))
        hit = [land[i] for i in tree.query(Point(xy)) if pack[land[i]]['poly'].contains(Point(xy))]
        p = pack[hit[0] if hit else land[int(tree.nearest(Point(xy)))]]
        new = inside(p['poly'], xy)
        stats['cities'] += 1
        stats['moved'] += new != xy
        c = re.sub(r'(name="refRegion" value=")[^"]+', lambda m: m.group(1) + p['id'], c, count=1)
        c = set_vec(c, 'vecPosition', new)
        sm = re.search(r'name="refSeaRegion" value="([^"]+)', c)
        if sm:
            seas = [n for n in p['nbs'] if pack[n]['sea']]
            if not seas:
                c = re.sub(r'[ \t]*<property name="refSeaRegion"[^>]*>[ \t]*\n', '', c)
                stats['lost_port'] += 1
            else:
                want = idx.get(sm.group(1))
                n = want if want in seas else min(seas, key=lambda n: pack[n]['poly'].distance(Point(new)))
                c = re.sub(r'(name="refSeaRegion" value=")[^"]+', lambda m: m.group(1) + pack[n]['id'], c)
        return c
    return re.sub(r'(?m)^([ \t]*)<object type="gs_tbg.City" name="objCities">.*?\n\1</object>', city, s, flags=re.S)


def write_scenario(src, dest, name, pack, van, old2new, primary, ov):
    """Copy of an SWW scenario module on the new map: imports the map module, regions rebuilt, references moved."""
    rename = {oid: pack[k]['id'] for oid, k in old2new.items()}
    rename.update({p['id']: p['id'] for p in pack})
    stats = {'refs': 0, 'dups': 0, 'unknown': set(), 'cities': 0, 'moved': 0, 'lost_port': 0}
    os.makedirs(dest, exist_ok=True)
    for f in os.listdir(src):
        if not f.endswith(('.xml', '.lmd')):
            shutil.copy2(os.path.join(src, f), dest)
            continue
        s = open(os.path.join(src, f), encoding='utf-8').read()
        if f == 'module.lmd':
            s = re.sub(r'(<locustModule[^>]*?\sname=")[^"]+', lambda m: m.group(1) + esc(name), s, count=1)
            s = s.replace('module="mh2 map:world map"', 'module="mh2 map:%s"' % MAP_MODULE)
        else:
            if f == 'GameSysRegion.xml':
                s = build_regions_xml(s, pack, van, primary, ov, old2new, coastal_points(pack))
            elif f == 'GameSysCity.xml':
                s = fix_cities(s, pack, stats)
            s = remap_text(s, rename, stats)
        open(os.path.join(dest, f), 'w', encoding='utf-8').write(s)
    return stats


def metadata(title, desc):
    """metadata.dat as the launcher reads it (layout of a Workshop mod's file): u32 version 1, u64 PublishedFileId,
    u64 owner SteamID, u32 1, title, description, u32 0, preview path, u32 0, u32 0 (strings = u32 length + bytes).
    Local mod: no Workshop id, no owner."""
    import struct
    s = lambda t: struct.pack('<I', len(t.encode('utf-8'))) + t.encode('utf-8')
    return struct.pack('<IQQI', 1, 0, 0, 1) + s(title) + s(desc) + struct.pack('<I', 0) + s('') + struct.pack('<II', 0, 0)


PLAYABLE = '''<?xml version="1.0" encoding="UTF-8"?>
<mod product="Making History SWW" release="1.0.61127.29" type="mod" name="%(name)s">
	<parameters>game:%(name)s|minimal:client|game ui:Making History SWW UI</parameters>
	<layer name="Bin"/>
	<layer name="Making History SWW"/>
	<layer name="Locust"/>
	<layer name="EDTK"/>
	<name locale="en">%(name)s</name>
	<description locale="en">%(desc)s</description>
</mod>
'''


# ------------------------------------------------------------------------------------------------ checks
def check(mod, pack, known):
    """SWW checks: XML parses, every model file exists, every region reference resolves, every region has a shape."""
    import xml.etree.ElementTree as ET
    errors, warnings = [], []
    ids = {p['id'] for p in pack}
    for root, _, files in os.walk(mod):
        for f in files:
            if f.endswith(('.xml', '.lmd')):
                try:
                    ET.parse(os.path.join(root, f))
                except ET.ParseError as e:
                    errors.append('%s: XML mal formado (%s)' % (os.path.relpath(os.path.join(root, f), mod), e))
    mdir = os.path.join(mod, 'modules', 'mh2 map', MAP_MODULE)
    for f in re.findall(r'fileSource" value="([^"]+)', open(os.path.join(mdir, 'models.xml'), encoding='utf-8').read()):
        if not os.path.exists(os.path.join(mdir, f)):
            errors.append('falta el modelo ' + f)
    for p in pack:
        if p['poly'].is_empty or not p['tris']:
            errors.append('región sin forma: ' + p['name'])
        if not p['nbs']:
            warnings.append('región sin vecinos: ' + p['name'])
    gdir = os.path.join(mod, 'modules', 'game')
    for g in os.listdir(gdir):
        for f in os.listdir(os.path.join(gdir, g)):
            s = open(os.path.join(gdir, g, f), encoding='utf-8').read()
            bad = {m.group(3) for m in REGION_PROP.finditer(s) if m.group(3) not in ids}
            bad |= {v for v in REGION_REF.findall(s) if v not in ids}
            vanilla = {v for v in bad if v not in known}      # already dangling in the SWW scenario itself
            if vanilla:
                warnings.append('%s/%s: el escenario de SWW ya apunta a regiones que no existen en su mapa (falso positivo '
                                'de vanilla): %s' % (g, f, ', '.join(sorted(vanilla))))
            bad -= vanilla
            if bad:
                errors.append('%s/%s: regiones que no existen: %s' % (g, f, ', '.join(sorted(bad)[:10])))
    return errors, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--pack', default=os.path.join(gamepaths.GAMES['mh1']['path'], 'Modern Europe', 'system',
                                                   'DisplayLibraries', 'Maps', 'WorldHOI4'))
    ap.add_argument('--scenario', default='Building for War', help='SWW scenario module to fit onto the map')
    ap.add_argument('--name', default='The Politics of Appeasement HOI4', help='new scenario (and mod) name')
    ap.add_argument('--out', default=r'D:\Claude\sww_hoi4\out')
    ap.add_argument('--reuse', action='store_true', help='reuse geometry and matching of the last run (_geometry.pkl)')
    ap.add_argument('--install', action='store_true', help='copy the mod to <SWW>/content/mods (refuses to overwrite)')
    a = ap.parse_args()
    mod = os.path.join(a.out, a.name)
    if os.path.exists(mod):
        shutil.rmtree(mod)                          # our own build output under --out, never a game folder
    cache = os.path.join(a.out, '_geometry.pkl')
    if a.reuse:
        pack, van, old2new, primary, ov = pickle.load(open(cache, 'rb'))
    else:
        print('WorldHOI4...', flush=True)
        pack = load_pack(a.pack)
        print('SWW world map...', flush=True)
        van = load_vanilla()
        old2new, primary, ov = match(pack, van)
        pickle.dump((pack, van, old2new, primary, ov), open(cache, 'wb'))
    print('WorldHOI4 %d regiones (%d mar); SWW %d regiones' % (len(pack), sum(p['sea'] for p in pack), len(van)), flush=True)
    # the map module sits in <SWW>/content/mods/<mod>/modules/mh2 map/<map>; terrain tiles stay in the vanilla world map
    write_map(pack, van, primary, os.path.join(mod, 'modules', 'mh2 map', MAP_MODULE),
              os.path.join(a.pack, 'art', 'MiniMap.tga'), a.pack,
              '../../../../../Making History SWW/modules/mh2 map/world map')
    stats = write_scenario(os.path.join(MODS, 'game', a.scenario), os.path.join(mod, 'modules', 'game', a.name), a.name,
                           pack, van, old2new, primary, ov)
    desc = '%s on the WorldHOI4 map (%d regions), ported from Making History: The Calm and The Storm.' % (a.scenario, len(pack))
    open(os.path.join(mod, 'mod_playable.xml'), 'w', encoding='utf-8').write(PLAYABLE % {'name': esc(a.name), 'desc': esc(desc)})
    open(os.path.join(mod, 'metadata.dat'), 'wb').write(metadata(a.name, desc))
    shutil.copy2(os.path.join(SWW, 'DefaultModPreview.jpg'), os.path.join(mod, 'Preview.jpg'))
    print('referencias movidas %(refs)d, duplicadas quitadas %(dups)d, ciudades %(cities)d (movidas dentro de su región '
          '%(moved)d, sin puerto %(lost_port)d)' % stats)
    if stats['unknown']:
        print('  referencias desconocidas:', sorted(stats['unknown'])[:20])
    errors, warnings = check(mod, pack, set(van))
    print('errores %d, avisos %d' % (len(errors), len(warnings)))
    for e in errors[:40]:
        print('  ERROR', e)
    for w in warnings[:20]:
        print('  aviso', w)
    if a.install and not errors:
        dst = os.path.join(SWW, 'content', 'mods', a.name)     # the launcher's default mod folder (HKCU Mod Directory)
        if os.path.exists(dst):
            raise SystemExit('ya existe ' + dst)
        shutil.copytree(mod, dst)
        print('instalado en', dst)


if __name__ == '__main__':
    main()
