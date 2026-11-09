"""Crea fuentes .ttf con glifos japoneses para Making History 1 / Gold (locale jp).

El motor de texto del juego (bin/fonts.dll, FreeType antiguo) solo escanea `*.ttf` de sus carpetas de fuentes
y la UI pide familias concretas (Arial, Century Gothic...), sin kana/kanji; las fuentes japonesas de Windows
son `.ttc`. Este script toma cada fuente original de Windows (asi el texto occidental no cambia) y le anade
los glifos japoneses de MS PGothic que usa `locale/jp`. Resultado en making-history/fuentes_jp/; luego hay
que apuntar `strFontDirs` (Options/options.xml) a esa carpeta.

Uso: python fuente_jp.py
"""
import os
from fontTools.merge import Merger
from fontTools.ttLib.scaleUpem import scale_upem
from fontTools.ttLib import TTCollection, TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'fuentes_jp')
WIN = r'C:\Windows\Fonts'
SRC = os.path.join(WIN, 'msgothic.ttc')
# familia -> {estilo: archivo de Windows}
FAMILIES = {
    'Arial': {'Regular': 'arial.ttf', 'Bold': 'arialbd.ttf', 'Italic': 'ariali.ttf', 'BoldItalic': 'arialbi.ttf'},
    'CenturyGothic': {'Regular': 'GOTHIC.TTF', 'Bold': 'GOTHICB.TTF', 'Italic': 'GOTHICI.TTF', 'BoldItalic': 'GOTHICBI.TTF'},
    'BodoniMT': {'Regular': 'BOD_R.TTF', 'Bold': 'BOD_B.TTF', 'Italic': 'BOD_I.TTF', 'BoldItalic': 'BOD_BI.TTF'},
    'CourierNew': {'Regular': 'cour.ttf', 'Bold': 'courbd.ttf', 'Italic': 'couri.ttf', 'BoldItalic': 'courbi.ttf'},
}
DROP = ('GSUB', 'GPOS', 'GDEF', 'BASE', 'JSTF', 'kern', 'EBDT', 'EBLC', 'EBSC', 'gasp', 'hdmx', 'LTSH', 'VDMX',
        'DSIG', 'vhea', 'vmtx', 'meta', 'morx', 'mort', 'fpgm', 'prep', 'cvt ', 'PCLT')


def jp_chars():
    """Caracteres no latinos de los textos japoneses (MH1 y Gold usan el mismo locale/jp)."""
    import gamepaths
    chars = set()
    for g in ('mh1', 'gold'):
        d = os.path.join(gamepaths.path(g), 'system', 'locale', 'jp') if gamepaths.installed(g) else ''
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith('.xml'):
                    chars |= {ord(c) for c in open(os.path.join(d, f), encoding='utf-8', errors='ignore').read()}
    return sorted(c for c in chars if c >= 0x2000)  # el alfabeto latino lo pone la fuente original


def strip(path):
    f = TTFont(path)
    for t in DROP:
        if t in f:
            del f[t]
    return f


def jp_font(upem, chars, path):
    """MS PGothic reducida a `chars`, a la escala de la fuente base y sin tablas que rompan el merge."""
    from fontTools import subset as fts
    f = TTCollection(SRC).fonts[1]  # MS PGothic (proporcional)
    opts = fts.Options()
    opts.notdef_outline = True
    opts.hinting = False
    opts.layout_features = []
    s = fts.Subsetter(opts)
    s.populate(unicodes=chars)
    s.subset(f)
    for t in DROP:
        if t in f:
            del f[t]
    scale_upem(f, upem)
    f.save(path)


def build():
    os.makedirs(OUT, exist_ok=True)
    for old in os.listdir(OUT):
        os.remove(os.path.join(OUT, old))
    chars = jp_chars()
    assert chars, 'no se encontro texto japones (locale/jp)'
    base, jp = os.path.join(OUT, '_base.tmp'), os.path.join(OUT, '_jp.tmp')
    for fam, styles in FAMILIES.items():
        for style, fname in styles.items():
            src = os.path.join(WIN, fname)
            if not os.path.exists(src):
                print('falta', src)
                continue
            b = strip(src)
            b.save(base)
            jp_font(b['head'].unitsPerEm, chars, jp)
            font = Merger().merge([base, jp])  # la primera fuente manda: nombres y glifos latinos originales
            # solo nombres Windows/Unicode BMP/ingles: el FreeType antiguo no lee los de UCS-4 (platEncID 10)
            name = font['name']
            name.names = [r for r in name.names if r.platformID == 3 and r.platEncID == 1 and r.langID == 0x409]
            # U+200A de ancho 0: jp_wrap.py lo mete entre caracteres japoneses para que el juego (iswspace) parta lineas
            sp = font.getBestCmap()[0x20]
            font['hmtx'].metrics['hairsp0'] = (0, 0)
            font['glyf'].glyphs['hairsp0'] = font['glyf'][sp].__class__()
            font.setGlyphOrder(font.getGlyphOrder() + ['hairsp0'])
            font['maxp'].numGlyphs += 1
            for t in font['cmap'].tables:
                if t.isUnicode():
                    t.cmap[0x200A] = 'hairsp0'
            path = os.path.join(OUT, 'jp_%s_%s.ttf' % (fam, style))
            font.save(path)
            assert TTFont(path).getBestCmap().get(chars[-1]), path  # self-check: tiene japones
            print(path)
    os.remove(base)
    os.remove(jp)


if __name__ == '__main__':
    build()
