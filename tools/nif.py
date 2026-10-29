"""Lector/escritor NIF (Gamebryo/NetImmerse) guiado por data/nif.xml (NifTools, licencia BSD).

Making History usa NIF 10.1.0.0 / 10.2.0.0. Lee cada bloque a un dict {campo: valor} siguiendo nif.xml y lo vuelve a
escribir igual (ida y vuelta byte a byte), así que se puede cambiar un campo y guardar.
    n = Nif.load(ruta); n.blocks[i]['_type']; n.save(ruta2)
"""
import os
import re
import struct
import xml.etree.ElementTree as ET

XML = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'nif.xml')


def ver_int(s):
    p = [int(x) for x in s.split('.')]
    while len(p) < 4:
        p.append(0)
    return (p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]


def _num(s):
    s = s.strip()
    if re.fullmatch(r'\d+(\.\d+){3}', s):
        return ver_int(s)
    return int(s, 0)


class Spec:
    def __init__(self, path=XML):
        root = ET.parse(path).getroot()
        self.basic, self.enum, self.compound, self.niobject = {}, {}, {}, {}
        for e in root:
            if e.tag == 'basic':
                self.basic[e.get('name')] = e
            elif e.tag in ('enum', 'bitflags'):
                self.enum[e.get('name')] = e.get('storage')
            elif e.tag == 'compound':
                self.compound[e.get('name')] = e
            elif e.tag == 'niobject':
                self.niobject[e.get('name')] = e
        self._fields = {}
        self._expr = {}

    def fields(self, name):
        """Campos de un niobject con los de sus padres primero."""
        if name not in self._fields:
            if name == 'NiObject' and name not in self.niobject:   # raíz implícita en nif.xml
                return []
            e = self.niobject[name] if name in self.niobject else self.compound[name]
            par = e.get('inherit')
            out = (self.fields(par) if par else []) + [a for a in e if a.tag == 'add']
            self._fields[name] = out
        return self._fields[name]

    def is_a(self, t, base):
        while t:
            if t == base:
                return True
            t = self.niobject[t].get('inherit') if t in self.niobject else None
        return False

    _TOK = re.compile(r'\s*(?:(\d+\.\d+\.\d+\.\d+)|(0x[0-9a-fA-F]+)|(\d+)|(&&|\|\||==|!=|<=|>=|[<>!&|()+\-*/])|'
                      r'([A-Za-z_#][\w #\\]*[\w#]|[A-Za-z_]))')

    def compile(self, s):
        """Expresión de nif.xml -> código Python que usa L('nombre')."""
        if s in self._expr:
            return self._expr[s]
        out, pos = [], 0
        while pos < len(s):
            m = self._TOK.match(s, pos)
            if not m:
                if s[pos:].strip() == '':
                    break
                raise ValueError('expresión: %r' % s)
            pos = m.end()
            v, h, n, op, ident = m.groups()
            if v:
                out.append(str(ver_int(v)))
            elif h or n:
                out.append(str(int(h or n, 0)))
            elif op:
                out.append({'&&': ' and ', '||': ' or ', '!': ' not ', '/': '//'}.get(op, op))
            else:
                out.append('L(%r)' % ident.strip())
        code = compile(''.join(out).strip(), s, 'eval')
        self._expr[s] = code
        return code


SPEC = None


def spec():
    global SPEC
    if SPEC is None:
        SPEC = Spec()
    return SPEC


class _IO:
    def __init__(self, data=None):
        self.d = data
        self.p = 0
        self.out = [] if data is None else None
        self.ver = 0
        self.pad = 0
        self.user = 0
        self.user2 = 0
        self.block_type = None

    # --- primitivos
    def fmt(self, f, v=None):
        if self.out is None:
            r = struct.unpack_from('<' + f, self.d, self.p)[0]
            self.p += struct.calcsize(f)
            return r
        self.out.append(struct.pack('<' + f, v))
        return v

    def raw(self, n, v=None):
        if self.out is None:
            r = self.d[self.p:self.p + n]
            if len(r) != n:
                raise EOFError('fin de archivo')
            self.p += n
            return r
        self.out.append(bytes(v))
        return v

    def line(self, v=None):
        if self.out is None:
            i = self.d.index(b'\n', self.p)
            r = self.d[self.p:i]
            self.p = i + 1
            return r
        self.out.append(bytes(v) + b'\n')
        return v


_BASIC = {'byte': 'B', 'uint': 'I', 'ulittle32': 'I', 'ushort': 'H', 'int': 'i', 'short': 'h', 'BlockTypeIndex': 'H',
          'char': 'B', 'FileVersion': 'I', 'Flags': 'H', 'float': 'f', 'hfloat': 'e', 'Ptr': 'i', 'Ref': 'i',
          'StringOffset': 'I', 'StringIndex': 'I', 'uint64': 'Q', 'int64': 'q', 'sbyte': 'b'}
_STOR = {'uint': 'I', 'ushort': 'H', 'byte': 'B', 'int': 'i', 'short': 'h'}


class Walker:
    """Lee (io.out is None) o escribe un valor según nif.xml."""

    def __init__(self, io):
        self.io = io
        self.sp = spec()

    def basic(self, t, v=None):
        io = self.io
        if t == 'bool':
            return io.fmt('B' if io.ver >= 0x04010001 else 'I', v)
        if t in ('HeaderString', 'LineString'):
            return io.line(v)
        if t in _BASIC:
            return io.fmt(_BASIC[t], v)
        if t in self.sp.enum:
            return io.fmt(_STOR[self.sp.enum[t]], v)
        raise KeyError('tipo básico desconocido: %s' % t)

    def value(self, t, v, scope, template, arg):
        if t == 'TEMPLATE':
            t = template
        if t in self.sp.compound:
            return self.struct(t, v, scope, template, arg)
        return self.basic(t, v)

    def evaluate(self, expr, scope, arg):
        sp = self.sp
        io = self.io

        def L(name):
            if name in ('ARG', '#ARG#'):
                return arg or 0
            for s in reversed(scope):
                if name in s:
                    x = s[name]
                    return x
            if name == 'Version':
                return io.ver
            if name == 'User Version':
                return io.user
            if name == 'User Version 2':
                return io.user2
            if name in sp.niobject:
                return 1 if (io.block_type and sp.is_a(io.block_type, name)) else 0
            return 0
        return eval(sp.compile(expr), {'L': L})

    def present(self, a, scope, arg):
        io = self.io
        g = a.get
        if g('ver1') and io.ver < ver_int(g('ver1')):
            return False
        if g('ver2') and io.ver > ver_int(g('ver2')):
            return False
        if g('ver') and io.ver != ver_int(g('ver')):
            return False
        if g('userver') and io.user != _num(g('userver')):
            return False
        if g('userver2') and io.user2 != _num(g('userver2')):
            return False
        for k in ('vercond', 'cond'):
            if g(k) and not self.evaluate(g(k), scope, arg):
                return False
        return True

    def struct(self, t, v, scope, template=None, arg=None):
        reading = self.io.out is None
        cur = {} if reading else v
        scope = scope + [cur]
        if not reading:      # contadores = longitud real de las listas
            for a in self.sp.fields(t):
                a1, a2, val = a.get('arr1'), a.get('arr2'), cur.get(a.get('name'))
                if a1 in cur and isinstance(val, (list, bytes)) and isinstance(cur[a1], int) and self.present(a, scope, arg)                         and (val or not a.get('cond')):
                    cur[a1] = len(val)
                    if a2 in cur and isinstance(cur[a2], list) and len(cur[a2]) == len(val):
                        cur[a2] = [len(r) for r in val]
        for a in self.sp.fields(t):
            if not self.present(a, scope, arg):
                continue
            name = a.get('name')
            ft = a.get('type')
            ftemp = a.get('template')
            if ftemp in (None, 'TEMPLATE'):
                ftemp = template
            farg = a.get('arg')
            if farg is not None:
                farg = self.evaluate(farg, scope, arg) if not farg.lstrip('-').isdigit() else int(farg)
            val = None if reading else cur[name]
            a1 = a.get('arr1')
            if a1:
                n1 = self.evaluate(a1, scope, arg)
                a2 = a.get('arr2')
                if a2:
                    n2 = self.evaluate(a2, scope, arg)
                    rows = []
                    for i in range(n1):
                        k = n2[i] if isinstance(n2, list) else n2
                        rows.append(self.array(ft, k, None if reading else val[i], scope, ftemp, farg))
                    val = rows
                else:
                    val = self.array(ft, n1, val, scope, ftemp, farg)
            else:
                val = self.value(ft, val, scope, ftemp, farg)
            if reading:
                cur[name] = val
        return cur

    def array(self, t, n, v, scope, template, arg):
        if t in ('byte', 'char'):
            return self.io.raw(n, v)
        if t in _BASIC and t not in ('Ptr', 'Ref') or t in ('Ptr', 'Ref'):
            f = _BASIC[t]
            if self.io.out is None:
                r = list(struct.unpack_from('<%d%s' % (n, f), self.io.d, self.io.p))
                self.io.p += struct.calcsize('<%d%s' % (n, f))
                return r
            self.io.out.append(struct.pack('<%d%s' % (n, f), *v))
            return v
        return [self.value(t, None if v is None else v[i], scope, template, arg) for i in range(n)]


class RefVisitor(Walker):
    """Recorre un bloque ya leído y llama cb(contenedor, clave) por cada Ref/Ptr."""

    def __init__(self, io, cb):
        super().__init__(io)
        self.cb = cb

    def walk(self, t, v, scope, template=None, arg=None):
        scope = scope + [v]
        for a in self.sp.fields(t):
            if not self.present(a, scope, arg):
                continue
            name, ft = a.get('name'), a.get('type')
            ftemp = a.get('template')
            if ftemp in (None, 'TEMPLATE'):
                ftemp = template
            if ft == 'TEMPLATE':
                ft = template
            farg = a.get('arg')
            if farg is not None:
                farg = self.evaluate(farg, scope, arg) if not farg.lstrip('-').isdigit() else int(farg)
            val = v[name]
            if ft in ('Ref', 'Ptr'):
                if isinstance(val, list):
                    for i in range(len(val)):
                        self.cb(val, i)
                else:
                    self.cb(v, name)
            elif ft in self.sp.compound:
                items = val if a.get('arr1') else [val]
                if a.get('arr2'):
                    items = [x for row in val for x in row]
                for x in items:
                    self.walk(ft, x, scope, ftemp, farg)


def _s(x):
    return x.decode('latin-1') if isinstance(x, (bytes, bytearray)) else x


class Nif:
    def __init__(self):
        self.header = {}
        self.blocks = []
        self.footer = {}
        self.ver = 0

    @property
    def types(self):
        return [b['_type'] for b in self.blocks]

    @classmethod
    def load(cls, path):
        return cls.parse(open(path, 'rb').read())

    @classmethod
    def parse(cls, data):
        n = cls()
        io = _IO(data)
        m = re.search(rb'Version (\d+\.\d+\.\d+\.\d+)', data[:80])
        io.ver = ver_int(m.group(1).decode())
        w = Walker(io)
        n.header = w.struct('Header', None, [])
        io.ver = n.header.get('Version', io.ver)
        io.user = n.header.get('User Version', 0)
        io.user2 = n.header.get('User Version 2', 0)
        n.ver = io.ver
        names = [_s(x['Value']) for x in n.header.get('Block Types', [])]
        for i in range(n.header['Num Blocks']):
            t = names[n.header['Block Type Index'][i] & 0x7FFF]
            io.block_type = t
            if 0x0A000100 <= io.ver <= 0x0A01006A:   # 10.0.1.0-10.1.0.106: uint 0 antes de cada bloque
                n.pad = io.fmt('I')
            b = w.struct(t, None, [])
            b['_type'] = t
            n.blocks.append(b)
        io.block_type = None
        n.footer = w.struct('Footer', None, [])
        n._io = io
        if io.p != len(data):
            raise ValueError('sobran %d bytes al final' % (len(data) - io.p))
        return n

    def to_bytes(self):
        io = _IO()
        io.ver = self.ver
        io.user = self.header.get('User Version', 0)
        io.user2 = self.header.get('User Version 2', 0)
        w = Walker(io)
        names = [_s(x['Value']) for x in self.header['Block Types']]
        self.header['Num Blocks'] = len(self.blocks)
        self.header['Block Type Index'] = [names.index(b['_type']) for b in self.blocks]
        w.struct('Header', self.header, [])
        for b in self.blocks:
            io.block_type = b['_type']
            if 0x0A000100 <= io.ver <= 0x0A01006A:
                io.fmt('I', getattr(self, 'pad', 0))
            w.struct(b['_type'], b, [])
        io.block_type = None
        w.struct('Footer', self.footer, [])
        return b''.join(io.out)

    def save(self, path):
        data = self.to_bytes()
        with open(path, 'wb') as f:
            f.write(data)

    def visit_refs(self, cb):
        """cb(indice_bloque, contenedor, clave) por cada referencia."""
        io = _IO(b'')
        io.ver, io.user, io.user2 = self.ver, self.header.get('User Version', 0), self.header.get('User Version 2', 0)
        for i, b in enumerate(self.blocks):
            io.block_type = b['_type']
            RefVisitor(io, lambda c, k, i=i: cb(i, c, k)).walk(b['_type'], b, [])
        for k in range(len(self.footer.get('Roots', []))):
            cb(-1, self.footer['Roots'], k)

    def compact(self):
        """Quita los bloques a los que no llega nada desde las raíces y renumera las referencias."""
        refs = {}
        self.visit_refs(lambda i, c, k: refs.setdefault(i, []).append(c[k]))
        seen, todo = set(), [r for r in self.footer['Roots'] if r >= 0]
        while todo:
            i = todo.pop()
            if i in seen or i >= len(self.blocks):
                continue
            seen.add(i)
            todo += [r for r in refs.get(i, []) if r >= 0]
        keep = sorted(seen)
        new = {old: n for n, old in enumerate(keep)}

        def fix(i, c, k):
            if c[k] >= 0:
                c[k] = new.get(c[k], -1)
        self.visit_refs(fix)
        self.blocks = [self.blocks[i] for i in keep]
        used = []
        for b in self.blocks:
            if b['_type'] not in used:
                used.append(b['_type'])
        self.header['Block Types'] = [{'Length': len(t), 'Value': t.encode('latin-1')} for t in used]
        self.header['Num Block Types'] = len(used)

    def add(self, block):
        self.add_type(block['_type'])
        self.blocks.append(block)
        return len(self.blocks) - 1

    def add_type(self, t):
        names = [_s(x['Value']) for x in self.header['Block Types']]
        if t not in names:
            self.header['Block Types'].append({'Length': len(t), 'Value': t.encode('latin-1')})
            self.header['Num Block Types'] = len(self.header['Block Types'])


def string(v):
    """Valor de un campo string/FilePath de 10.x -> str."""
    if isinstance(v, dict):
        v = v.get('String', v)
        if isinstance(v, dict):
            v = v.get('Value', b'')
    return _s(v)


def set_string(v):
    b = v.encode('latin-1')
    return {'String': {'Length': len(b), 'Value': b}}
