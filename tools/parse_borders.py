"""Parser de borders.brd (Making History). Hipotesis:
  u32 nBordes; por borde: u32 region, u8 flag, u32 nPuntos, (f32 x, f32 y)[nPuntos]
Uso: python -I parse_borders.py borders.brd regions.csv"""
import struct, sys, collections, csv
d = open(sys.argv[1], 'rb').read()
names = [r['name'] for r in csv.DictReader(open(sys.argv[2], encoding='utf-8'))]
n, = struct.unpack_from('<I', d, 0); o = 4
recs = []
for i in range(n):
    reg, flag, npts = struct.unpack_from('<IBI', d, o); o += 9
    pts = struct.unpack_from('<%df' % (2*npts), d, o); o += 8*npts
    recs.append((reg, flag, npts, pts[:2]))
print('bordes', n, '| end', o, 'of', len(d))
print('flags', collections.Counter(r[1] for r in recs))
print('max region idx', max(r[0] for r in recs))
for r in recs[:6]: print(names[r[0]] if r[0] < len(names) else r[0], r[1], r[2], [round(x,2) for x in r[3]])
