"""XML reading that tolerates what the game tolerates: hand-edited mod files with ANSI bytes in a «UTF-8» file, control
characters, stray «&» or «--» inside a comment. ElementTree refused («not well-formed (invalid token): line 6, column 2») and the
editor would not save a regionpack or scenario that works in the game. If it still cannot be read, the error says which file and where."""
import os
import re
import xml.etree.ElementTree as ET


def _builder(comments):
    return ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)) if comments else ET.XMLParser()


def clean(raw):
    """Sanitized XML text from the file bytes."""
    try:
        t = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        t = raw.decode('cp1252', errors='replace')          # Windows ANSI, the usual in files touched with Notepad
    t = t[t.find('<'):] if '<' in t else t                    # basura antes de la primera etiqueta
    t = re.sub(r'^<\?xml[^>]*\?>', '', t)                     # the declaration (and its encoding, no longer valid for a str)
    t = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', t)
    t = re.sub(r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)', '&amp;', t)
    return re.sub(r'<!--(.*?)-->', lambda m: '<!--' + re.sub(r'-{2,}', lambda d: '- ' * len(d.group()), m.group(1)).rstrip('-') + '-->', t, flags=re.S)


def parse(path, comments=False):
    """ElementTree of the file; like ET.parse, but sanitizing the text if needed. ValueError (with file and line) if there is no way."""
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


if __name__ == '__main__':      # self-test: python xml_tolerant.py
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
