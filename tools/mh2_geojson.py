"""Build MH2 regions GeoJSON from Regions.nst + GameSysRegion.xml."""
import json, re, sys, collections
import xml.etree.ElementTree as ET
from shapely.geometry import Polygon, MultiPolygon, mapping
from shapely.ops import unary_union
import mh2_regions
XML = r'C:/Program Files (x86)/Steam/steamapps/common/Making History II/content/mods/Test/modules/game/Test/GameSysRegion.xml'
OUT = r'C:/Users/janit/Documents/Claude/making-history/mh2/mh2_regions.geojson'

def load_xml():
    ns = '{http://www.muzzylane.com/ml/schema/2009/04/locust}'
    root = ET.parse(XML).getroot()
    regs = {}
    for o in root.iter(ns + 'object'):
        if o.get('type') != 'gs_tbg.Region': continue
        p = {}
        for pr in o.findall(ns + 'property'):
            p.setdefault(pr.get('name'), pr.get('value'))
        regs[p.get('strName')] = p
    return regs

def norm(s): return re.sub(r'[\s_\-\'.]+', '', s).lower()

def main():
    regs = load_xml()
    byn = {norm(k): v for k, v in regs.items()}
    nodes = mh2_regions.parse()
    feats, fail, nv, used = [], [], 0, set()
    for name, (verts, idx) in nodes.items():
        tris = []
        for i in range(0, len(idx), 3):
            t = Polygon([verts[idx[i]], verts[idx[i+1]], verts[idx[i+2]]])
            if t.area > 0: tris.append(t if t.is_valid else t.buffer(0))
        try:
            g = unary_union(tris).buffer(0)
        except Exception as e:
            fail.append((name, str(e))); continue
        if g.is_empty: fail.append((name, 'empty')); continue
        if g.geom_type == 'Polygon': g = MultiPolygon([g])
        if g.bounds[2] > 180:   # el mapa de MH2 continua mas alla de 180E: partir y llevar la parte este a -180..
            from shapely.geometry import box
            from shapely.affinity import translate
            g = unary_union([g.intersection(box(-360, -90, 180, 90)), translate(g.intersection(box(180, -90, 540, 90)), xoff=-360)])
            g = unary_union([p for p in getattr(g, 'geoms', [g]) for p in getattr(p, 'geoms', [p]) if p.geom_type == 'Polygon'])
            if g.geom_type == 'Polygon': g = MultiPolygon([g])
        nv += len(verts)
        r = byn.get(norm(name))
        props = {'mh_type': 'land_region' if r and r.get('nPopulation') else 'sea_region', 'name': (r or {}).get('strName') or name.replace('_', ' ')}
        if r: used.add(r['strName'])
        if r and r.get('nPopulation'):
            props.update(owner=r.get('refOwner'), population=int(r.get('nPopulation') or 0), culture=(r.get('tmplCulture') or '').replace('sd.', ''))
        feats.append({'type': 'Feature', 'properties': props, 'geometry': mapping(g)})
    json.dump({'type': 'FeatureCollection', 'features': feats}, open(OUT, 'w'), ensure_ascii=False)
    c = collections.Counter(f['properties']['mh_type'] for f in feats)
    print(len(nodes), 'nodes', nv, 'vertices', dict(c), 'failed', fail)
    print('xml regions without node:', [k for k in regs if k not in used][:20], len([k for k in regs if k not in used]))
if __name__ == "__main__": main()
