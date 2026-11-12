"""Finds the Spanish texts the user would see untranslated with the editor in English and those missing from editor/i18n_en.json.

Usage: python i18n_extract.py            -> JSON {text: ""} with the entries missing from i18n_en.json (to fill in)
     python i18n_extract.py --informe  -> list by file and line of the texts that would appear in Spanish
     python i18n_extract.py --check    -> like --informe, and exits with code 1 if any remain
     python i18n_extract.py --todos    -> JSON with all texts found (translated or not)

Looks at the pages and scripts in tools/editor and the Python modules loaded by editor_server.py. Each text is run through a
copy of i18n.js's translation (exact text, patterns, phrases with {} holes and chunks of three or more words); if any
Spanish chunk remains, it needs translating:
- fixed text -> exact entry;
- text with data (${...}, %s, {nombre}, 'a' + x + 'b' in Python) -> phrase with «{}» holes if some chunk has fewer than
  three words (short chunks are not substituted inside texts with data), or the chunks if all are long.
In JavaScript, 'texto ' + x is not seen whole: it is flagged «concatenado» to turn it into `texto ${x}`.
"""
import ast
import glob
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EDITOR = os.path.join(HERE, 'editor')
SKIP_WEB = {'i18n.js', 'ai_chat.js'}            # the dictionary itself; the AI chat is not published yet
SKIP_PY = {'i18n_extract.py', 'ai_chat.py', 'scenario_i18n.py'}
DICT = os.path.join(EDITOR, 'i18n_en.json')
I18N_JS = os.path.join(EDITOR, 'i18n.js')
HOLE = '\x00'                                   # sitio de un dato dentro de un texto

SPANISH = re.compile(r'[áéíóúñ¿¡«»]|\b(el|la|los|las|de|del|que|en|un|una|con|por|para|sin|al|se|no|es|región|regiones|'
                     r'país|países|escenario|mapa|guardar|nueva|nuevo|elige|falta|clic|ninguna|ningún|todas|todos|'
                     r'aplicar|quitar|borrar|crear|abrir|cerrar|cambiar|archivo|archivos|ciudades|unidades|ejército|'
                     r'población|mar|tierra|hueco|vecina|vecinas|dueño|propietario|controlador|recortar|dibujar|'
                     r'refrescar|exportar|importar|instalar|validar|revertir|editar|elegir|copiar|pegar|deshacer|rehacer|cancelar|aceptar|buscar|mostrar|ocultar|'
                     r'sí|y|o|ya|más|menos|cada|solo|también|aquí|hay|tiene|puede|pasa|pasan|queda)\b', re.I)
JUNK = re.compile(r'^[#/]|[\w-]=|</?(button|div|span|b|a|i|input|select|option|label|td|tr|th|table|br|p|code|h3|dialog|header|small|script|object|property)\b|-->|<!--|'
                  r'^[a-z]+(-[a-z]+)+$|^\S*\w\[\S*$|^\S+\.(html|bin|json|xml|nif|tga|dds|txt|nuevo|geojson)$|%[YHMS]|SELECT \?|\$ErrorActionPreference')   # routes, selectors, html, strftime dates, code
ENGLISH = re.compile(r'\b(the|to|of|and|is|are|with|from|this|that|has|have|will|be|its|it|for|on|file|files|found|write|copy|not)\b', re.I)
SP_WORDS = re.compile(r'[áéíóúñ¿¡]|\b(el|la|los|las|de|del|que|en|un|una|con|por|para|sin|al|se|es|y|o|ya|más|hay|tiene|puede)\b', re.I)
IGNORE = {'El Salvador', 'corea del norte', 'corea del sur', 'No owner', 'rusia', 'polonia', 'terrestre', 'tipo', 'p. ej. Aysén'}   # + GeoJSON property aliases     # data (country names, the game's «No owner» value), not interface texts
SPLIT = re.compile(HOLE + r'|\$\{[^}]*\}|%[-0-9.]*[sdfr]|%\([a-z_]+\)[sdf]|\{[a-z_0-9]*(?:![rs])?(?::[^{}]*)?\}')
STRIP = ' \t\n:;,.·|—-–()[]→?!¿¡«»'


def _vocab():
    """Words that only appear on the Spanish side of the dictionary («errores», «avisos»…): extend SPANISH."""
    try:
        d = json.load(open(DICT, encoding='utf-8'))
    except (OSError, ValueError):
        return set()
    words = lambda xs: {w.lower() for x in xs for w in re.findall(r'[^\W\d_]{4,}', x)}
    return words(d) - words(v for v in d.values() if v)


VOCAB = _vocab()


def is_spanish(part):
    return bool(SPANISH.search(part)) or any(w.lower() in VOCAB for w in re.findall(r'[^\W\d_]{4,}', part))


def pieces(text):
    """Fixed Spanish chunks of a text (without the data)."""
    text = html.unescape(text)      # el navegador ve «<nombre>», no «&lt;nombre&gt;»
    for part in SPLIT.split(text):
        part = part.strip(STRIP)
        if JUNK.search(part):
            continue
        if len(part) >= 3 and is_spanish(part) and not re.fullmatch(r'[\W\d_]+', part):
            yield part


def norm(text):
    """As i18n.js sees it: HTML entities resolved, consecutive spaces into one (line breaks kept), data as HOLE."""
    t = re.sub(r'\s*\n\s*', NL, re.sub(r'[^\S\n]+', ' ', SPLIT.sub(HOLE, html.unescape(text)))).strip().replace('%%', '%')   # '… %d %%' % x -> «… 5 %»
    while HOLE + HOLE in t:
        t = t.replace(HOLE + HOLE, HOLE)
    return t


# ---------------------------------------------------------------- cadenas de HTML/JS
BS, NL = chr(92), chr(10)


def js_literals(js):
    """[(text, position, concatenated)] of JS strings ('..', "..", `..` with HOLE where ${...} goes), without comments."""
    out, n = [], len(js)

    def plus_near(a, b):            # «'texto' + x» o «x + 'texto'»
        i = a - 1
        while i >= 0 and js[i] in ' \t\r\n':
            i -= 1
        j = b
        while j < n and js[j] in ' \t\r\n':
            j += 1
        return (i >= 0 and js[i] == '+' and (i == 0 or js[i - 1] != '+')) or (j < n and js[j] == '+' and (j + 1 >= n or js[j + 1] not in '+='))

    def read_quoted(i, q):
        buf = []
        while i < n and js[i] != q:
            if js[i] == BS and i + 1 < n:
                buf.append({'n': NL}.get(js[i + 1], js[i + 1]))
                i += 2
                continue
            buf.append(js[i])
            i += 1
        return ''.join(buf), i + 1

    def read_template(i):
        buf = []
        while i < n:
            c = js[i]
            if c == BS and i + 1 < n:
                buf.append({'n': NL}.get(js[i + 1], js[i + 1]))
                i += 2
            elif c == '`':
                return ''.join(buf), i + 1
            elif c == '$' and i + 1 < n and js[i + 1] == '{':
                buf.append(HOLE)
                i = read_code(i + 2, '}')
            else:
                buf.append(c)
                i += 1
        return ''.join(buf), i

    def read_code(i, end=None):
        depth = 0
        while i < n:
            c = js[i]
            if end and c == end and depth == 0:
                return i + 1
            if c in '{([':
                depth += 1
            elif c in '})]':
                depth -= 1
            if c == '/' and i + 1 < n and js[i + 1] == '/':
                j = js.find(NL, i)
                i = n if j < 0 else j
                continue
            if c == '/' and i + 1 < n and js[i + 1] == '*':
                j = js.find('*/', i + 2)
                i = n if j < 0 else j + 2
                continue
            if c in ("'", '"', '`'):
                t, j = read_quoted(i + 1, c) if c != '`' else read_template(i + 1)
                out.append((t, i, plus_near(i, j), j))
                i = j
                continue
            i += 1
        return i

    read_code(0)
    return out


REGEX_LIT = re.compile(r'(?<=[(,=:\[!&|?{};])\s*/(?![/*])(?:\\.|\[(?:\\.|[^\]])*\]|[^/\n\\])+/[gimsuy]*')


def js_texts(body):
    """Texts reaching the page from a JS string: text nodes between tags and title/placeholder."""
    out = re.findall(r'(?:title|placeholder)="([^"]*)"', body)
    if '<' in body or '="' in body:
        body = re.sub(r'"[^"]*"|\b[a-z-]+=', ' ', body)
    return out + re.split(r'<[^>]*>|^[^<]*>|<[^>]*$', body)


def bilingual(js, lits):
    """Spans of the first argument of L(es, en) (imagenes.html, escenario_imagenes.js): the Spanish carries its English alongside."""
    ends, spans = {i: j for _t, i, _c, j in lits}, []
    for m in re.finditer(r'(?<![\w.$])L\(', js):
        i, depth = m.end(), 0
        while i < len(js):
            if i in ends:
                i = ends[i]
                continue
            c = js[i]
            if c in '([{':
                depth += 1
            elif c in ')]}':
                if depth == 0:
                    break
                depth -= 1
            elif c == ',' and depth == 0:
                spans.append((m.end(), i))
                break
            i += 1
    return spans


def from_js(js, base_line=1):
    """[(text, line, concatenated)]"""
    js = REGEX_LIT.sub(lambda m: ' 0 ' + NL * m.group(0).count(NL), js)    # /[&<>"]/g… would confuse the reader (lines intact)
    lits = js_literals(js)
    skip = bilingual(js, lits)
    res = []
    for body, pos, cat, _end in lits:
        if any(a <= pos < b for a, b in skip):
            continue
        line = base_line + js.count(NL, 0, pos)
        res += [(t, line, cat) for t in js_texts(body)]
    return res


def from_html(src):
    res = []
    line = lambda pos: src.count(NL, 0, pos) + 1
    for m in re.finditer(r'<script\b[^>]*>(.*?)</script>', src, flags=re.S):
        res += from_js(m.group(1), line(m.start(1)))
    body = re.sub(r'<script\b[^>]*>.*?</script>|<style>.*?</style>', lambda m: NL * m.group(0).count(NL), src, flags=re.S)
    for m in re.finditer(r'>([^<>]+)<', body):
        res.append((m.group(1), line(m.start(1)), False))
    for m in re.finditer(r'(?:title|placeholder)="([^"]+)"', body):
        res.append((m.group(1), line(m.start(1)), False))
    return res


# ---------------------------------------------------------------- Python
def from_py(src):
    """[(text, line, False)] of a module's strings: constants, f-strings and 'a' + x + 'b' (without docstrings, print(),
    argparse, regular expressions, comparisons or dict keys)."""
    tree = ast.parse(src)
    skip, res = set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, (ast.Constant, ast.JoinedStr)):
            skip.add(id(node.value))
        elif isinstance(node, ast.Call):
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if name in ('print', 'add_argument', 'ArgumentParser', 'compile', 'match', 'search', 'sub', 'findall', 'fullmatch', 'finditer'):
                for a in list(node.args) + [k.value for k in node.keywords]:
                    skip.update(id(x) for x in ast.walk(a))
        elif isinstance(node, ast.Compare):
            skip.update(id(x) for x in [node.left] + node.comparators if isinstance(x, ast.Constant))
        elif isinstance(node, ast.Subscript):
            skip.update(id(x) for x in ast.walk(node.slice))
        elif isinstance(node, ast.Dict):
            skip.update(id(k) for k in node.keys if k is not None)

    def flat(e):                                                      # 'a' + x + 'b' -> 'a' HOLE 'b'
        if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Add):
            return flat(e.left) + flat(e.right)
        if isinstance(e, ast.Constant) and isinstance(e.value, str):
            return [e.value]
        if isinstance(e, ast.JoinedStr):
            return [v.value if isinstance(v, ast.Constant) else HOLE for v in e.values]
        return [HOLE]

    done = set()
    for node in ast.walk(tree):
        if id(node) in skip or id(node) in done:
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            parts = flat(node)
            if any(p != HOLE for p in parts):
                done.update(id(x) for x in ast.walk(node))
                res.append((''.join(parts), node.lineno, False))
        elif isinstance(node, ast.JoinedStr):
            done.update(id(x) for x in ast.walk(node))
            res.append((''.join(v.value if isinstance(v, ast.Constant) else HOLE for v in node.values), node.lineno, False))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            res.append((node.value, node.lineno, False))
    return res


def server_modules():
    """tools/ modules loaded by editor_server.py (and those they load)."""
    seen, todo = set(), ['editor_server']
    while todo:
        m = todo.pop()
        p = os.path.join(HERE, m + '.py')
        if m in seen or not os.path.exists(p):
            continue
        seen.add(m)
        for n in ast.walk(ast.parse(open(p, encoding='utf-8').read())):
            if isinstance(n, ast.Import):
                todo += [a.name.split('.')[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                todo.append(n.module.split('.')[0])
            elif isinstance(n, ast.Call) and getattr(n.func, 'id', '') == '__import__' and n.args and isinstance(n.args[0], ast.Constant):
                todo.append(n.args[0].value)
    return sorted(os.path.join(HERE, m + '.py') for m in seen if m + '.py' not in SKIP_PY)


# ---------------------------------------------------------------- copy of i18n.js's translation (tr)
JS_STR = r"'((?:\\.|[^'\\])*)'"


def _unjs(s):
    return re.sub(r'\\(.)', lambda m: {'n': '\n'}.get(m.group(1), m.group(1)), s)


class Translator:
    def __init__(self):
        self.have = json.load(open(DICT, encoding='utf-8')) if os.path.exists(DICT) else {}
        js = open(I18N_JS, encoding='utf-8').read()
        en = js[js.index('const EN = {'):js.index('const PATTERNS')]
        self.exact = {_unjs(k): _unjs(v) for k, v in re.findall(JS_STR + r'\s*:\s*' + JS_STR, en)}
        for k, v in self.have.items():
            if v and '{}' not in k:
                self.exact.setdefault(k, v)
        self.patterns = []
        pat = js[js.index('const PATTERNS'):js.index('const lang = ')]
        for m in re.finditer(r'\[/(\^(?:\\.|[^/\\])*?)/[gimsuy]*,', pat):
            try:
                self.patterns.append(re.compile(m.group(1)))
            except re.error:
                pass
        shapes = sorted((k for k, v in self.have.items() if v and '{}' in k),
                        key=lambda k: (k.startswith('{}') + k.endswith('{}'), -len(k.replace('{}', ''))))
        self.shapes = [(re.compile('^' + re.escape(k).replace(re.escape('{}'), '(.*?)') + '$', re.S), self.have[k],
                        len(k.replace('{}', '')) if k.startswith('{}') and k.endswith('{}') else 0) for k in shapes]
        keys = sorted((k for k, v in self.have.items() if v and '{}' not in k and len(k.split()) >= 3), key=len, reverse=True)
        bound = lambda k: (r'(?<![^\W_])' if re.match(r'\w', k[0]) else '') + re.escape(k) + (r'(?![^\W_])' if re.match(r'\w', k[-1]) else '')
        self.phrase_re = re.compile('|'.join(bound(k) for k in keys)) if keys else None

    def whole(self, t, depth, shapes=True):
        if t in self.exact:
            return self.exact[t]
        m = re.match(r'^(.+?)( [▲▼+↗]|[.:…]+)$', t)
        if m and m.group(1) in self.exact:
            return self.exact[m.group(1)] + m.group(2)
        b = re.match(r'^([•·→–—-] )(.+)$', t)
        if b:
            q = self.whole(b.group(2), depth, shapes)
            if q is not None:
                return b.group(1) + q
        if any(p.search(t) for p in self.patterns):
            return '<patrón>'
        for rx, en, loose in (self.shapes if shapes else []):
            m = rx.match(t)
            if m and loose and (loose < len(t) / 4 or (self.phrase_re and len(''.join(self.phrase_re.findall(t))) > loose)):     # as in i18n.js
                continue
            if m:
                g = [self.tr(x, depth + 1) for x in m.groups()]
                it = iter(g)
                return re.sub(r'\{(\d*)\}', lambda q: g[int(q.group(1)) - 1] if q.group(1) else next(it, ''), en)
        return None

    def phrases(self, t):
        return self.phrase_re.sub(lambda q: self.have.get(q.group(0)) or q.group(0), t) if self.phrase_re else t

    def tr(self, s, depth=0):
        t = ' '.join(s.split())
        if not t or depth > 6:
            return t
        multi = bool(re.search(r'[.?!…]\s|\n', s))          # several sentences or lines: each on its own (before phrases with holes)
        r = self.whole(t, depth, not multi)
        if r is None and multi:
            out, buf, hit = [], [], False         # consecutive sentences without their own translation: joined for the loose sentences (like i18n.js)
            for p in sentences(s):
                g = self.whole(p, depth)
                if g is None:
                    buf.append(p)
                    continue
                if buf:
                    out.append(self.phrases(' '.join(buf)))
                    buf = []
                out.append(g)
                hit = True
            if buf:
                out.append(self.phrases(' '.join(buf)))
            r = ' '.join(out) if hit else self.whole(t, depth)
        if r is None:
            r = self.phrases(t)
        r = re.sub(r'Falta «Guardar»\.?', 'Remember to «Save».', re.sub(r'(?<!\w)Clic(?!\w)', 'Click', r))     # words() de i18n.js
        return re.sub(r'\(controla ([^()]+)\)', r'(controlled by \1)', re.sub(r'\(desde ([^()]+)\)', r'(from \1)', r))


def sentences(t):
    """Sentences of a text, as i18n.js splits them when the whole text has no translation."""
    return [' '.join(p.split()) for p in re.split(r'\s*\n\s*|(?<=[.?!…])\s+', t) if p.strip()]


def scan():
    """[(file, line, text with {}, chunks still in Spanish, concatenated)]"""
    T = Translator()
    try:
        sys.path.insert(0, HERE)
        import scenario_i18n                # scenario_events.py texts are already translated by the server (scenario_i18n.L)
        server_en = scenario_i18n._en
        # chunks scenario_events composes phrases with («a ser de» -> «la región {} pasa a ser de {}»): fine if they are in one of those phrases
        server_src = [es for es, _en in scenario_i18n.SHAPES + scenario_i18n.PHRASES]
    except Exception:
        server_en, server_src = (lambda s: s), []
    files = [f for f in sorted(glob.glob(os.path.join(EDITOR, '*.html')) + glob.glob(os.path.join(EDITOR, '*.js')))
             if os.path.basename(f) not in SKIP_WEB] + server_modules()
    out, seen = [], set()
    for f in files:
        src = open(f, encoding='utf-8').read()
        items = from_html(src) if f.endswith('.html') else from_js(src) if f.endswith('.js') else from_py(src)
        for text, line, cat in items:
            t = norm(text)
            sp = [x for p in pieces(t) for x in (q.strip(STRIP) for q in sentences(p)) if len(x) >= 3 and is_spanish(x)]   # per phrase
            if not sp or t in IGNORE or JUNK.search(t) or (ENGLISH.search(t) and not SP_WORDS.search(t)):    # English branch already written
                continue
            if t.startswith('Zona (oeste'):
                continue        # LEEME.txt inside the background image zip (a file, not a notice)
            if ' ' not in t and ('_' in t or re.search(r'\.[\w*]{2,4}$', t) or re.fullmatch(r'[a-z]+(-\x00)+', t) or (f.endswith('.py') and re.fullmatch(r'[a-z0-9{}\-]+', t))):
                continue        # nombres de archivo y claves de datos («regiones_nuevas», «fondo_{}.png», 'madre' en Python)
            sample = t.replace(HOLE, '⟨⟩')         # a data value that does not stick to the neighboring words
            left = still_spanish(sp, T.tr(server_en(sample) if f.endswith('scenario_events.py') else sample))
            if f.endswith('scenario_events.py'):
                left = [p for p in left if not any(p in es for es in server_src)]
            key = (os.path.basename(f), t)
            if not left or key in seen:
                continue
            seen.add(key)
            out.append((os.path.relpath(f, HERE), line, t.replace(HOLE, '{}'), left, cat))
    return out, T


SMALL = {'el', 'la', 'los', 'las', 'de', 'del', 'que', 'en', 'un', 'una', 'con', 'por', 'para', 'sin', 'al', 'se', 'es', 'y', 'ya', 'su', 'sus'}


def spanish_run(text):
    """Two or more consecutive Spanish words (what remains of a half-translated sentence)."""
    run = 0
    for w in re.findall(r'[^\W\d_]+', text):
        run = run + 1 if (w.lower() in SMALL or w.lower() in VOCAB) else 0
        if run >= 2:
            return True
    return False


def still_spanish(sp, got):
    """Spanish chunks that remain as-is (as whole words) in the translation, or with consecutive Spanish words."""
    left = [p for p in sp if re.search((r'(?<!\w)' if re.match(r'\w', p) else '') + re.escape(p) + (r'(?!\w)' if re.search(r'\w$', p) else ''), got)]
    return left or ([p for p in sp if spanish_run(p)] if spanish_run(got) else [])


def entries(found, T):
    """Entries missing from i18n_en.json for what was found."""
    want = {}
    for _f, _l, t, _left, _cat in found:
        whole_t = ' '.join(t.split())
        for s in (sentences(t) if '{}' in t or T.tr(whole_t) != whole_t else [whole_t]):    # one entry per phrase; fixed text with nothing translated, whole
            sp = still_spanish([' '.join(p.split()) for p in pieces(s)], T.tr(s.replace('{}', '⟨⟩')))
            if not sp:
                continue
            # all Spanish chunks of the phrase long (3 words or more): they work as loose phrases; otherwise the phrase with holes
            if '{}' in s and all(len([w for w in p.split() if re.search(r'[^\W\d_]', w)]) >= 3 for p in pieces(s)):   # as i18n.js counts
                want.update((p, '') for p in sp)
            else:
                want[s] = ''
    return want


def main():
    found, T = scan()
    if '--todos' in sys.argv:
        json.dump({t: T.have.get(t, '') for _f, _l, t, _p, _c in found}, sys.stdout, ensure_ascii=False, indent=0)
    elif '--informe' in sys.argv or '--check' in sys.argv:
        by = {}
        for f, l, t, _left, cat in found:
            by.setdefault(f, []).append((l, t, cat))
        for f in sorted(by):
            print('== %s (%d)' % (f, len(by[f])))
            for l, t, cat in sorted(by[f]):
                print('  %5d%s %s' % (l, ' [concatenado]' if cat else '', ' '.join(t.split())[:160]))
        print('// %d textos que saldrían en español' % len(found), file=sys.stderr)
        # the other languages (i18n_ru.json…) have the same keys as English
        en = json.load(open(DICT, encoding='utf-8'))
        other = 0
        for p in sorted(glob.glob(os.path.join(EDITOR, 'i18n_*.json'))):
            if os.path.abspath(p) != os.path.abspath(DICT):
                tr = json.load(open(p, encoding='utf-8'))
                miss = [k for k in en if en[k] and not tr.get(k)]
                other += len(miss)
                print('// %s: %d textos sin traducir%s' % (os.path.basename(p), len(miss), (': ' + ' | '.join(m[:60] for m in miss[:5])) if miss else ''), file=sys.stderr)
        if '--check' in sys.argv and (found or other):
            sys.exit(1)
    else:
        want = entries(found, T)
        json.dump(want, sys.stdout, ensure_ascii=False, indent=0)
        print('\n// %d textos sin traducir -> %d entradas para i18n_en.json' % (len(found), len(want)), file=sys.stderr)


if __name__ == '__main__':
    main()
