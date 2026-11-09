"""Lectura de XML que tolera lo que el juego tolera: archivos de mods editados a mano con bytes ANSI en un archivo «UTF-8», caracteres
de control, «&» sueltos o «--» dentro de un comentario. ElementTree se negaba («not well-formed (invalid token): line 6, column 2») y el
editor no dejaba guardar un regionpack o un escenario que en el juego funciona. Si ni así se puede leer, el error dice qué archivo y dónde."""
import os
import re
import xml.etree.ElementTree as ET


def _builder(comments):
    return ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)) if comments else ET.XMLParser()


def clean(raw):
    """Texto XML saneado a partir de los bytes del archivo."""
    try:
        t = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        t = raw.decode('cp1252', errors='replace')          # ANSI de Windows, lo habitual en archivos tocados con el Bloc de notas
    t = t[t.find('<'):] if '<' in t else t                    # basura antes de la primera etiqueta
    t = re.sub(r'^<\?xml[^>]*\?>', '', t)                     # la declaración (y su encoding, que ya no vale para un str)
    t = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', t)
    t = re.sub(r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)', '&amp;', t)
    return re.sub(r'<!--(.*?)-->', lambda m: '<!--' + re.sub(r'-{2,}', lambda d: '- ' * len(d.group()), m.group(1)).rstrip('-') + '-->', t, flags=re.S)


def parse(path, comments=False):
    """ElementTree del archivo; como ET.parse, pero saneando el texto si hace falta. ValueError (con archivo y línea) si no hay manera."""
    try:
        return ET.parse(path, _builder(comments))
    except ET.ParseError as first:
        with open(path, 'rb') as f:
            raw = f.read()
        try:
            return ET.ElementTree(ET.fromstring(clean(raw), _builder(comments)))
        except ET.ParseError:
            line, col = first.position
            raise ValueError('%s: XML mal formado en la línea %d, columna %d (%s). Ábrelo con un editor de texto y corrige esa línea.'
                             % (os.path.basename(path), line, col + 1, first)) from None


if __name__ == '__main__':      # autocomprobación: python xml_tolerant.py
    import tempfile
    bad = [b'\xef\xbb\xbf<?xml version="1.0" encoding="utf-8"?>\n<a>\n<!-- caf\xe9 -- raro --->\n<b v="Tom & Jerry"/>\x01\n</a>',
           b'junk<a><b v="x"/></a>']
    for raw in bad:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xml') as f:
            f.write(raw)
        try:
            assert parse(f.name, comments=True).getroot().find('b') is not None
        finally:
            os.unlink(f.name)
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xml') as f:
        f.write(b'<a>\n<b></a>')
    try:
        parse(f.name)
        raise AssertionError('broken XML must raise ValueError')
    except ValueError as e:
        assert os.path.basename(f.name) in str(e) and 'línea' in str(e), e
    finally:
        os.unlink(f.name)
    print('OK xml_tolerant')
