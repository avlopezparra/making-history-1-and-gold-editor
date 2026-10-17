"""Parser de regions.bin (Making History: The Calm and The Storm).

Formato (little-endian):
  cabecera: u32 nRegiones
  por region:
    u32 tipo (1 / 2), u32 a, u32 b   (a == b en lo visto; posible area)
    u32 len, char[len] nombre
    u32 flag (0), f32 centroX (longitud), f32 centroY (latitud), u32 (0)
    u32 nVecinos, u32[nVecinos] indices de regiones vecinas
    u32 nPuntos, (f32 x, f32 y)[nPuntos] contorno

Uso: python -I parse_regions.py regions.bin [salida.csv]
"""
import struct, sys, collections
d = open(sys.argv[1], 'rb').read()
n, = struct.unpack_from('<I', d, 0)
o = 4
recs = []
for i in range(n):
    typ, a, b = struct.unpack_from('<3I', d, o); o += 12
    ln, = struct.unpack_from('<I', d, o); o += 4
    name = d[o:o+ln].decode('latin1'); o += ln
    flag, cx, cy, z, nn = struct.unpack_from('<I2f2I', d, o); o += 20
    nbrs = struct.unpack_from('<%dI' % nn, d, o); o += 4*nn
    npts, = struct.unpack_from('<I', d, o); o += 4
    pts = struct.unpack_from('<%df' % (2*npts), d, o); o += 8*npts
    recs.append(dict(i=i, name=name, cx=cx, cy=cy, nbrs=nbrs, npts=npts, typ=typ, a=a, b=b))
print('header', n, '| parsed', len(recs), '| end', o, 'of', len(d))
print('tipos', collections.Counter(r['typ'] for r in recs))
asym = sum(1 for r in recs for j in r['nbrs'] if r['i'] not in recs[j]['nbrs'])
print('vecindades no simetricas:', asym)
by = {r['name']: r for r in recs}
for nm in ('Corsica', 'Crimea', 'Kiev', 'Moscow'):
    if nm in by:
        r = by[nm]; print(nm, r['typ'], round(r['cx'],2), round(r['cy'],2), '->', [recs[j]['name'] for j in r['nbrs']])
if len(sys.argv) > 2:
    with open(sys.argv[2], 'w', encoding='utf-8') as f:
        f.write('index,name,type,center_lon,center_lat,points,a,neighbors\n')
        for r in recs:
            f.write('%d,"%s",%d,%.4f,%.4f,%d,%d,"%s"\n' % (r['i'], r['name'], r['typ'], r['cx'], r['cy'], r['npts'], r['a'], '; '.join(recs[j]['name'] for j in r['nbrs'])))
    print('CSV ->', sys.argv[2])
