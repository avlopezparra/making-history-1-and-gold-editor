"""Extract region meshes from Making History II Regions.nst (see MH2_NST_FORMATO.md)."""
import re, struct, sys
NST = r'C:/Program Files (x86)/Steam/steamapps/common/Making History II/content/Making History II/modules/mh2 map/world map/models/Regions.nst'
VERT = re.compile(rb'(?s)([\x01-\xff]\x00\x00\x00)(.{8}\x00{4}\x00{4}\x00{2}\x80\x3f)')

def parse(path=NST):
    d = open(path, 'rb').read()
    marks = [(m.start(), m.group(1).decode()) for m in re.finditer(rb'([A-Za-z0-9_\-\.\'() ]+)Node\|instance_geometry', d)]
    marks.append((len(d), None))
    out = {}
    for (p, name), (q, _) in zip(marks, marks[1:]):
        name = name  # includes 'Node' suffix stripped below
        seg = d[p:q]
        # vertex block: u32 count, then count*24 bytes (x,y,z=0,nx=0,ny=0,nz=1)
        m = None
        for mm in re.finditer(rb'(?s)(.{4})(.{8}\x00{12}\x00\x00\x80\x3f)', seg):
            n = struct.unpack('<I', mm.group(1))[0]
            if 3 <= n < 100000:
                m = mm; break
        if not m: out[name] = None; continue
        n = struct.unpack('<I', m.group(1))[0]
        vs = m.start() + 4
        verts = [struct.unpack_from('<2f', seg, vs + 24*i) for i in range(n)]
        e = vs + 24*n
        # index block: u32 count, u32 size(=2), uint16 indices
        ok = None
        for off in range(e, min(e+200, len(seg)-8)):
            c, sz = struct.unpack_from('<2I', seg, off)
            if sz == 2 and c % 3 == 0 and 3 <= c and off+8+2*c <= len(seg):
                idx = struct.unpack_from('<%dH' % c, seg, off+8)
                if max(idx) < n: ok = idx; break
        out[name] = (verts, ok)
    return out

if __name__ == '__main__':
    r = parse()
    bad = [k for k, v in r.items() if not v or not v[1]]
    print(len(r), 'nodes; bad', len(bad), bad[:10])
    print(sum(len(v[0]) for v in r.values() if v), 'vertices')
