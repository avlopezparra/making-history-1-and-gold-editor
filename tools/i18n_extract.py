"""Extrae los textos en español de la interfaz (HTML/JS) y de los mensajes del servidor (Python) que aún no tienen
traducción en editor/i18n_en.json. Uso: python i18n_extract.py [--todos]  -> imprime JSON {texto: ""} de los que faltan.

Los textos con datos variables se cortan por los marcadores (%s, %d, ${...}) y se traducen los trozos fijos.
"""
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = [os.path.join(HERE, 'editor', f) for f in ('index.html', 'escenario.html', 'imagenes.html', 'escenario_imagenes.js')]
PY = ['editor_server.py', 'editor_core.py', 'scenario_core.py', 'scenario_layers.py', 'geojson_io.py', 'geojson_compare.py', 'terrain_image.py',
      'image_tools.py', 'image_assets.py', 'convert_scenario.py', 'file_identify.py', 'new_region.py', 'new_pack.py', 'scenario_new.py', 'transfer.py', 'paint_changes.py']
DICT = os.path.join(HERE, 'editor', 'i18n_en.json')

SPANISH = re.compile(r'[áéíóúñ¿¡«»]|\b(el|la|los|las|de|del|que|en|un|una|con|por|para|sin|al|se|no|es|región|regiones|'
                     r'país|países|escenario|mapa|guardar|nueva|nuevo|elige|falta|clic|ninguna|ningún|todas|todos|'
                     r'aplicar|quitar|borrar|crear|abrir|cerrar|cambiar|archivo|archivos|ciudades|unidades|ejército|'
                     r'población|mar|tierra|hueco|vecina|vecinas|dueño|propietario|controlador|recortar|dibujar|'
                     r'refrescar|exportar|importar|instalar|validar|revertir|editar|elegir|copiar|pegar|deshacer|rehacer|cancelar|aceptar|buscar|mostrar|ocultar|'
                     r'sí|y|o|ya|más|menos|cada|solo|también|aquí|hay|tiene|puede|pasa|pasan|queda)\b', re.I)
JUNK = re.compile(r'^[#/]|[\w-]=|</?(button|div|span|b|a|i|input|select|option|label|td|tr|th|table|br|p|code|h3|dialog|header|small)\b|-->|^[a-z]+(-[a-z]+)+$')   # rutas, selectores, atributos, html, nombres-con-guiones
SPLIT = re.compile(r'\$\{[^}]*\}|%[-0-9.]*[sdfr]|\{[a-z_0-9]*\}')


def pieces(text):
    text = html.unescape(text)      # el navegador ve «<nombre>», no «&lt;nombre&gt;»
    for part in SPLIT.split(text):
        part = part.strip(' \t\n:;,.·|—-–()[]→')
        if JUNK.search(part):
            continue
        if len(part) >= 3 and SPANISH.search(part) and not re.fullmatch(r'[\W\d_]+', part):
            yield part


def from_html(src):
    out = set()
    body = re.sub(r'<script\b[^>]*>.*?</script>|<style>.*?</style>', ' ', src, flags=re.S)
    for t in re.findall(r'>([^<>]+)<', body):
        out.update(pieces(' '.join(t.split())))
    for t in re.findall(r'(?:title|placeholder)="([^"]+)"', body):
        out.update(pieces(t))
    for js in re.findall(r'<script\b[^>]*>(.*?)</script>', src, flags=re.S):
        out |= from_js(js)
    return out


BS, NL = chr(92), chr(10)


def js_literals(js):
    """Trozos de texto fijo de las cadenas JS ('..', "..", y `..` sin lo que va dentro de ${...}), sin comentarios."""
    out, i, n = [], 0, len(js)
    stack = []                      # para plantillas anidadas: profundidad de llaves dentro de ${...}

    def read_quoted(i, q):
        buf = []
        while i < n and js[i] != q:
            if js[i] == BS and i + 1 < n:
                buf.append({'n': ' '}.get(js[i + 1], js[i + 1]))
                i += 2
                continue
            buf.append(js[i])
            i += 1
        return ''.join(buf), i + 1

    def read_template(i):
        buf, parts = [], []
        while i < n:
            c = js[i]
            if c == BS and i + 1 < n:
                buf.append({'n': ' '}.get(js[i + 1], js[i + 1]))
                i += 2
            elif c == '`':
                parts.append(''.join(buf))
                return parts, i + 1
            elif c == '$' and i + 1 < n and js[i + 1] == '{':
                parts.append(''.join(buf))
                buf = []
                i, inner = read_code(i + 2, '}')
                parts.extend(inner)
            else:
                buf.append(c)
                i += 1
        parts.append(''.join(buf))
        return parts, i

    def read_code(i, end=None):
        found, depth = [], 0
        while i < n:
            c = js[i]
            if end and c == end and depth == 0:
                return i + 1, found
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
            if c in ("'", '"'):
                t, i = read_quoted(i + 1, c)
                found.append(t)
                continue
            if c == '`':
                parts, i = read_template(i + 1)
                found.extend(parts)
                continue
            i += 1
        return i, found

    return read_code(0)[1]


REGEX_LIT = re.compile(r'(?<=[(,=:\[!&|?{};])\s*/(?![/*])(?:\\.|\[(?:\\.|[^\]])*\]|[^/\n\\])+/[gimsuy]*')


def from_js(js):
    out = set()
    js = REGEX_LIT.sub(' 0 ', js)          # expresiones regulares (/[&<>"]/g…) despistarían al lector de cadenas
    for body in js_literals(js):
        # HTML dentro de cadenas JS: cada texto entre etiquetas es un nodo aparte; title/placeholder también se traducen
        for t in re.findall(r'(?:title|placeholder)="([^"]+)"', body):
            out.update(pieces(t))
        if '<' in body or '="' in body:
            for q in re.findall(r'"([^"]*)"', body):       # valores de atributos (title, etc.) partidos por ${...}
                if ' ' in q:
                    out.update(pieces(q))
            body = re.sub(r'"[^"]*"|\b[a-z-]+=', ' ', body)
        for chunk in re.split(r'<[^>]*>|^[^<]*>|<[^>]*$', body):
            out.update(pieces(' '.join(chunk.split())))
        if '>' in body or '"' in body:   # trozos de atributos/etiquetas partidos por ${...}
            for chunk in re.split(r'["<>]', body):
                if ' ' in chunk.strip() and '=' not in chunk:
                    out.update(pieces(' '.join(chunk.split())))
    return out


def from_py(src):
    out = set()
    # solo cadenas que llegan al usuario: avisos, errores, notas e informes
    for m in re.finditer(r"""(?:append|raise\s+\w+|SystemExit|notes\s*\+?=|'msg'|'error'|'note'|errors\]\.append|warnings\]\.append|"""
                         r"""report\(|return\s*\[|notes\.append|ValueError)\s*\(?\s*\[?\s*(['"])((?:\\.|(?!\1).)*)\1""", src):
        out.update(pieces(m.group(2)))
    for m in re.finditer(r"""(['"])((?:\\.|(?!\1).){8,})\1\s*%""", src):    # 'texto %s' % (...)
        out.update(pieces(m.group(2)))
    return out


def main():
    found = set()
    for f in WEB:
        if os.path.exists(f):
            src = open(f, encoding='utf-8').read()
            found |= from_js(src) if f.endswith('.js') else from_html(src)
    for f in PY:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            found |= from_py(open(p, encoding='utf-8').read())
    import ast
    for f in ('scenario_core.py', 'scenario_layers.py'):
        tree = ast.parse(open(os.path.join(HERE, f), encoding='utf-8').read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'LABELS' or getattr(t, 'id', '').endswith('_ES') for t in node.targets) and isinstance(node.value, ast.Dict):
                for v in node.value.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        found.add(v.value)
    have = json.load(open(DICT, encoding='utf-8')) if os.path.exists(DICT) else {}
    missing = sorted(t for t in found if '--todos' in sys.argv or not have.get(t))
    json.dump({t: have.get(t, '') for t in missing}, sys.stdout, ensure_ascii=False, indent=0)
    print('\n// %d textos, %d sin traducir' % (len(found), len([t for t in found if not have.get(t)])), file=sys.stderr)


if __name__ == '__main__':
    main()
