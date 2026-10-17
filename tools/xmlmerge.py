"""Fusion a tres bandas de XML del juego (objetos <object> con <property>).

  base    el archivo por defecto del juego de origen (p. ej. ScenarioDefaults de MH1)
  ours    la copia del escenario (con los cambios propios del autor)
  theirs  el archivo por defecto del juego de destino (p. ej. ScenarioDefaults de Gold)

Resultado = theirs + los cambios del escenario respecto a base: valores cambiados, objetos anadidos (unidades
propias...) y objetos quitados. Lo que el escenario no toco adopta el valor del destino.

Identidad de un objeto: tipo + atributo name + la primera propiedad clave (strName, strKey...) + n.o de aparicion.
Propiedades repetidas (strCapabilities, strTemplateNames...) se tratan como listas ordenadas.
Conflictos (escenario y destino cambian lo mismo de forma distinta): gana el escenario en valores; si los dos
anaden un objeto con la misma clave, gana el destino (es una unidad de serie del juego de destino).
"""
import copy
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter

KEYS = ('strName', 'strKey', 'strProjectName', 'strUpgradeName', 'strListName', 'strTypeLabel', 'strType',
        'eUnitCategory', 'nLevel', 'strCultureName', 'strTemplateName', 'strFactoryName', 'strSpriteName', 'strLabel')


def parse(path):
    return ET.parse(path, ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))


def is_obj(c):
    return c.tag == 'object'


def is_prop(c):
    return c.tag == 'property'


def pval(p):
    """Valor completo de una propiedad (value, inheritFrom, computeFrom...)."""
    return tuple(sorted((k, v) for k, v in p.attrib.items() if k != 'name'))


def okey(o):
    for c in o:
        if is_prop(c) and c.get('name') in KEYS:
            return (o.get('type'), o.get('name'), c.get('name'), c.get('value'))
    return (o.get('type'), o.get('name'))


def keyed(children):
    """[(clave con n.o de aparicion, objeto)]"""
    seen = Counter()
    out = []
    for c in children:
        if is_obj(c):
            k = okey(c)
            seen[k] += 1
            out.append((k + (seen[k],), c))
    return out


def canon(el):
    if el is None:
        return None
    return (el.tag, tuple(sorted(el.attrib.items())),
            tuple(canon(c) for c in el if c.tag in ('object', 'property')))


def props(el):
    d = {}
    for c in el:
        if is_prop(c):
            d.setdefault(c.get('name'), []).append(pval(c))
    return d


def merge_list(b, o, t):
    """Lista ordenada: la del destino, quitando lo que el escenario quito y anadiendo lo que anadio."""
    removed = Counter(b) - Counter(o)
    added = Counter(o) - Counter(b)
    res = []
    rem = Counter(removed)
    for x in t:
        if rem[x] > 0:
            rem[x] -= 1
            continue
        res.append(x)
    for i, x in enumerate(o):
        if added[x] <= 0:
            continue
        added[x] -= 1
        prev = next((o[j] for j in range(i - 1, -1, -1) if o[j] in res), None)
        res.insert(res.index(prev) + 1 if prev is not None else 0, x)
    return res


class Merger:
    def __init__(self):
        self.notes = []
        self.stats = Counter()
        self.added = []          # objetos nuevos del destino (para escalar sus valores como el escenario)

    def merge(self, b, o, t, path=()):
        """Elemento fusionado (nuevo). b puede ser None (anadido a la vez en escenario y destino)."""
        path = list(path)
        cb, co, ct = canon(b), canon(o), canon(t)
        if co == cb:
            return copy.deepcopy(t)
        if ct == cb or ct == co:
            return copy.deepcopy(o)
        res = ET.Element(t.tag, dict(t.attrib))
        res.text, res.tail = t.text, t.tail
        # ---- propiedades
        pb, po, pt = (props(b) if b is not None else {}), props(o), props(t)
        newp = {}
        for name in list(pt) + [n for n in po if n not in pt]:
            vb, vo, vt = pb.get(name, []), po.get(name, []), pt.get(name, [])
            if b is None:
                newp[name] = vt or vo
            elif vo == vb:
                newp[name] = vt
            elif vt == vb or vt == vo:
                newp[name] = vo
            elif not vo:
                newp[name] = vt      # el escenario no trae la propiedad (p. ej. guardado por una version anterior)
            elif len(vb) <= 1 and len(vo) <= 1 and len(vt) <= 1:
                newp[name] = vo
                self.stats['conflictos'] += 1
                self.notes.append('conflicto en %s · %s: se mantiene el valor del escenario %s (origen %s, destino %s)' % (
                    '/'.join(path), name, _v(vo), _v(vb), _v(vt)))
            else:
                newp[name] = merge_list(vb, vo, vt)
        # ---- objetos hijos: orden del destino, con los del escenario insertados tras su predecesor
        tkeys = dict(keyed(list(t)))
        bkeys = dict(keyed(list(b))) if b is not None else {}
        okeys = keyed(list(o))
        odict = dict(okeys)
        children = []
        for k, tc in keyed(list(t)):
            if k in odict:
                children.append((k, self.merge(bkeys.get(k), odict[k], tc, path + [self._name(k)])))
            elif k in bkeys:     # el escenario lo quito
                if canon(bkeys[k]) == canon(tc):
                    self.stats['quitados'] += 1
                    self.notes.append('quitado (el escenario no lo tiene): %s' % self._lab(path, k))
                    continue
                children.append((k, copy.deepcopy(tc)))
                self.notes.append('el escenario quitó %s, pero el destino lo cambió: se conserva' % self._lab(path, k))
            else:                # nuevo en el destino
                self.stats['nuevos_destino'] += 1
                if not path or len(path) < 3:
                    self.notes.append('nuevo del destino: %s' % self._lab(path, k))
                nc = copy.deepcopy(tc)
                self.added.append(nc)
                children.append((k, nc))
        ck = [k for k, _ in children]
        for i, (k, oc) in enumerate(okeys):
            if k in tkeys:
                continue
            if k in bkeys:       # el destino lo quito
                if canon(bkeys[k]) == canon(oc):
                    continue
                self.notes.append('el destino no tiene %s (cambiado en el escenario): se conserva' % self._lab(path, k))
            else:
                self.stats['propios'] += 1
                self.notes.append('objeto propio del escenario conservado: %s' % self._lab(path, k))
            prev = next((okeys[j][0] for j in range(i - 1, -1, -1) if okeys[j][0] in ck), None)
            pos = ck.index(prev) + 1 if prev is not None else 0
            children.insert(pos, (k, copy.deepcopy(oc)))
            ck.insert(pos, k)
        # ---- emision: se recorre el destino (conserva comentarios); las propiedades de un nombre van juntas
        # en el sitio de la primera; cada objeto del destino se emite precedido de los propios que van antes
        emitted = set()
        last_prop = -1
        queue = list(children)
        tk_of = {id(c): k for k, c in keyed(list(t))}
        for c in t:
            if is_prop(c):
                name = c.get('name')
                if name not in emitted:
                    emitted.add(name)
                    for v in newp.get(name, []):
                        res.append(_mkprop(name, v, c.tail))
                    last_prop = len(res) - 1
            elif is_obj(c):
                k = tk_of[id(c)]
                if any(qk == k for qk, _ in queue):
                    while queue:
                        qk, qc = queue.pop(0)
                        res.append(qc)
                        if qk == k:
                            break
            else:
                res.append(copy.deepcopy(c))
        for n in newp:
            if n not in emitted:
                for v in newp[n]:
                    last_prop += 1
                    res.insert(last_prop, _mkprop(n, v, '\n'))
        for _, qc in queue:
            res.append(qc)
        self.stats['fusionados'] += 1
        return res

    @staticmethod
    def _name(k):
        return str(k[3]) if len(k) > 4 else (k[1] or k[0])

    def _lab(self, path, k):
        return '/'.join([p for p in path if p] + ['%s %s' % (k[0], self._name(k))])


def ratios(b, o, out=None):
    """{(tipo de objeto, propiedad): [valor escenario / valor origen]} de los objetos que existen en los dos."""
    out = {} if out is None else out
    if b is None or o is None:
        return out
    pb, po = props(b), props(o)
    for n, vb in pb.items():
        vo = po.get(n)
        if len(vb) == 1 and vo and len(vo) == 1:
            a, c = dict(vb[0]).get('value'), dict(vo[0]).get('value')
            if a and c and re.fullmatch(r'\d+', a) and re.fullmatch(r'\d+', c) and int(a) > 0:
                out.setdefault((b.get('type'), n), []).append(int(c) / int(a))
    od = dict(keyed(list(o)))
    for k, bc in keyed(list(b)):
        if k in od:
            ratios(bc, od[k], out)
    return out


def scale_added(m, b, o, min_samples=5, agree=0.8):
    """Si el escenario multiplica una propiedad por el mismo factor en casi todos los objetos de un tipo (p. ej.
    nMaintenanceCost de las unidades / 10), aplica ese factor a los objetos nuevos del destino de ese tipo."""
    factors = {}
    for (typ, n), rs in ratios(b, o).items():
        if len(rs) < min_samples:
            continue
        med = sorted(rs)[len(rs) // 2]
        if abs(med - 1) < 0.01:
            continue
        same = sum(1 for r in rs if abs(r - med) <= 0.01 * med)
        if same >= agree * len(rs):
            factors[(typ, n)] = med
    done = Counter()
    for el in m.added:
        for x in el.iter('object'):
            for p in x:
                f = factors.get((x.get('type'), p.get('name'))) if p.tag == 'property' else None
                if f and re.fullmatch(r'\d+', p.get('value') or ''):
                    p.set('value', str(int(round(int(p.get('value')) * f))))
                    done[(x.get('type'), p.get('name'), round(f, 4))] += 1
    for (typ, n, f), c in done.items():
        m.notes.append('escalado como en el escenario: %s · %s × %g en %d objetos nuevos del destino' % (typ, n, f, c))
        m.stats['escalados'] += c
    return factors


def _v(v):
    return '|'.join(dict(x).get('value', str(dict(x))) for x in v) or '—'


def _mkprop(name, v, tail):
    p = ET.Element('property', dict([('name', name)] + list(v)))
    p.tail = tail
    return p


def merge_files(base_path, ours_path, theirs_path):
    """(arbol fusionado, notas, estadisticas)."""
    o, t = parse(ours_path), parse(theirs_path)
    b = parse(base_path).getroot() if base_path and os.path.exists(base_path) else None
    m = Merger()
    root = m.merge(b, o.getroot(), t.getroot())
    scale_added(m, b, o.getroot())
    return ET.ElementTree(root), m.notes, m.stats


def write(tree, path, like=None):
    """Escribe con tabuladores y la cabecera del juego (la etiqueta raiz y CRLF como en el archivo 'like')."""
    ET.indent(tree, space='\t')
    data = ET.tostring(tree.getroot(), encoding='unicode').replace(' />', '/>')   # como los XML del juego
    if like:
        raw = open(like, 'rb').read()
        m_old = re.search(r'<objects?\b[^>]*>', raw.decode('utf-8', 'replace'))
        m_new = re.match(r'<[^>]*>', data)
        if m_old and m_new and m_old.group(0).split()[0] == m_new.group(0).split()[0].rstrip('>'):
            data = m_old.group(0) + data[m_new.end():]
        crlf = b'\r\n' in raw[:4000]
    else:
        crlf = True
    data = '<?xml version="1.0" encoding="UTF-8"?>\n' + data + '\n'
    if crlf:
        data = data.replace('\r\n', '\n').replace('\n', '\r\n')
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(data)
