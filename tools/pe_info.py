"""Lector mínimo de ejecutables PE (Windows) sin dependencias: exportaciones, importaciones y cadenas.

Sirve para entender los binarios del juego (makehist.exe, game.dll, ed.exe…): las DLL de C++ exportan sus funciones
con el nombre decorado de MSVC (?Metodo@Clase@@…), que revela clases y métodos, y las cadenas muestran mensajes,
nombres de propiedades XML y rutas. No ejecuta nada.

Uso: python pe_info.py <archivo> [exports|imports|strings] [filtro]
"""
import re
import struct
import sys


class PE:
    def __init__(self, path):
        self.path = path
        self.d = open(path, 'rb').read()
        d = self.d
        if d[:2] != b'MZ':
            raise ValueError('no es un ejecutable PE')
        pe = struct.unpack_from('<I', d, 0x3C)[0]
        if d[pe:pe + 4] != b'PE\0\0':
            raise ValueError('cabecera PE no encontrada')
        self.machine, nsec, self.timestamp, _, _, opt_size, self.chars = struct.unpack_from('<HHIIIHH', d, pe + 4)
        opt = pe + 24
        magic = struct.unpack_from('<H', d, opt)[0]
        self.pe32plus = magic == 0x20B
        self.image_base = struct.unpack_from('<Q' if self.pe32plus else '<I', d, opt + (24 if self.pe32plus else 28))[0]
        dd = opt + (112 if self.pe32plus else 96)
        self.dirs = [struct.unpack_from('<II', d, dd + 8 * i) for i in range(16)]
        self.sections = []
        s0 = opt + opt_size
        for i in range(nsec):
            name, vsize, va, rsize, raw = struct.unpack_from('<8sIIII', d, s0 + 40 * i)
            self.sections.append((name.rstrip(b'\0').decode('latin1'), va, vsize, raw, rsize))

    def off(self, rva):
        for _, va, vs, raw, rs in self.sections:
            if va <= rva < va + max(vs, rs):
                return rva - va + raw
        return None

    def cstr(self, rva):
        o = self.off(rva)
        e = self.d.index(b'\0', o)
        return self.d[o:e].decode('latin1')

    def exports(self):
        rva, size = self.dirs[0]
        if not rva:
            return []
        o = self.off(rva)
        _, _, _, _, name_rva, base, nfun, nnames, af, an, ao = struct.unpack_from('<IIHHIIIIIII', self.d, o)
        funcs = struct.unpack_from('<%dI' % nfun, self.d, self.off(af)) if nfun else ()
        names = struct.unpack_from('<%dI' % nnames, self.d, self.off(an)) if nnames else ()
        ords = struct.unpack_from('<%dH' % nnames, self.d, self.off(ao)) if nnames else ()
        out = []
        for n, k in zip(names, ords):
            out.append((self.cstr(n), self.image_base + funcs[k]))
        return out

    def imports(self):
        rva, _ = self.dirs[1]
        out = {}
        if not rva:
            return out
        o = self.off(rva)
        while True:
            oft, _, _, name, ft = struct.unpack_from('<IIIII', self.d, o)
            if not name:
                break
            dll = self.cstr(name)
            thunk = self.off(oft or ft)
            lst = []
            while True:
                v = struct.unpack_from('<I', self.d, thunk)[0]
                if not v:
                    break
                lst.append('#%d' % (v & 0xFFFF) if v & 0x80000000 else self.cstr(v + 2))
                thunk += 4
            out[dll] = lst
            o += 20
        return out

    def strings(self, minlen=5):
        res = []
        for m in re.finditer(rb'[\x20-\x7e]{%d,}' % minlen, self.d):
            res.append(m.group().decode('latin1'))
        for m in re.finditer(rb'(?:[\x20-\x7e]\x00){%d,}' % minlen, self.d):
            res.append(m.group().decode('utf-16le'))
        return res


def string_table(pe):
    """{id: texto} de los recursos RT_STRING (tipo 6): bloques de 16 cadenas UTF-16 con su longitud delante."""
    rva, _ = pe.dirs[2]
    if not rva:
        return {}
    base = pe.off(rva)
    d = pe.d

    def entries(o):
        _, _, _, _, nn, ni = struct.unpack_from('<IIHHHH', d, o)
        for k in range(nn + ni):
            name, off = struct.unpack_from('<II', d, o + 16 + 8 * k)
            yield name, off

    out = {}
    for tid, toff in entries(base):
        if tid != 6 or not toff & 0x80000000:
            continue
        for bid, boff in entries(base + (toff & 0x7FFFFFFF)):
            for _, loff in entries(base + (boff & 0x7FFFFFFF)):
                drva, dsize = struct.unpack_from('<II', d, base + loff)[:2]
                o, end, i = pe.off(drva), pe.off(drva) + dsize, 0
                while o < end and i < 16:
                    n = struct.unpack_from('<H', d, o)[0]
                    if n:
                        out[(bid - 1) * 16 + i] = d[o + 2:o + 2 + 2 * n].decode('utf-16le')
                    o += 2 + 2 * n
                    i += 1
    return out


def demangle(name):
    """Demangle sencillo de MSVC para leer clase::metodo (no reconstruye tipos)."""
    if not name.startswith('?'):
        return name
    m = re.match(r'\?(\?[0-9A-Z_]|[^@]+)@((?:[^@]+@)*)@', name)
    if not m:
        return name
    meth, scope = m.group(1), m.group(2).rstrip('@').split('@')
    special = {'?0': '(constructor)', '?1': '(destructor)', '?4': 'operator=', '?_7': '(vftable)'}
    meth = special.get(meth, meth)
    return '::'.join(reversed([s for s in scope if s])) + '::' + meth


if __name__ == '__main__':
    p = PE(sys.argv[1])
    what = sys.argv[2] if len(sys.argv) > 2 else 'exports'
    flt = re.compile(sys.argv[3], re.I) if len(sys.argv) > 3 else None
    if what == 'exports':
        for n, a in p.exports():
            t = demangle(n)
            if not flt or flt.search(t):
                print('%08x  %s' % (a, t))
    elif what == 'imports':
        for dll, fs in p.imports().items():
            print(dll, len(fs))
            for f in fs:
                if not flt or flt.search(f):
                    print('   ', demangle(f))
    elif what == 'stringtable':
        for k, v in sorted(string_table(p).items()):
            if not flt or flt.search(v):
                print('%5d  %s' % (k, v.replace(chr(10), ' | ')))
    else:
        for s in p.strings():
            if not flt or flt.search(s):
                print(s)
