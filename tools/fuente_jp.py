"""Crea fuentes .ttf con glifos japoneses para Making History (Gold, locale jp).

El motor de texto del juego (bin/fonts.dll, FreeType) solo escanea `*.ttf` en sus carpetas de fuentes
y la UI pide familias concretas (Arial, Century Gothic...). Ninguna tiene kana/kanji y las fuentes japonesas
de Windows son `.ttc`, que el juego no busca: por eso el texto japones sale vacio.
Este script extrae MS Gothic de msgothic.ttc y la guarda como .ttf renombrada a cada familia pedida,
en making-history/fuentes_jp/. Luego hay que apuntar `strFontDirs` (Options/options.xml) a esa carpeta.

Uso: python fuente_jp.py
"""
import os
from fontTools.ttLib import TTCollection

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'fuentes_jp')
SRC = r'C:\Windows\Fonts\msgothic.ttc'
FAMILIES = ['Arial', 'Century Gothic', 'Bodoni MT', 'Courier New']
STYLES = ['Regular', 'Bold', 'Italic', 'Bold Italic']


def build():
    os.makedirs(OUT, exist_ok=True)
    for fam in FAMILIES:
        for style in STYLES:
            font = TTCollection(SRC).fonts[0]
            # sin bitmaps incrustados: FreeType los da en 1 bit y el juego espera grises (salen barras/cuadros)
            for t in ('EBDT', 'EBLC', 'EBSC', 'gasp'):
                if t in font:
                    del font[t]
            name = font['name']
            full = fam if style == 'Regular' else '%s %s' % (fam, style)
            for rec in list(name.names):
                if rec.nameID in (1, 16):
                    rec.string = fam
                elif rec.nameID in (2, 17):
                    rec.string = style
                elif rec.nameID in (3, 4):
                    rec.string = full
                elif rec.nameID == 6:
                    rec.string = full.replace(' ', '')
            bold, italic = 'Bold' in style, 'Italic' in style
            font['OS/2'].fsSelection = (0x20 if bold else 0) | (0x01 if italic else 0) | (0x40 if style == 'Regular' else 0)
            font['head'].macStyle = (1 if bold else 0) | (2 if italic else 0)
            path = os.path.join(OUT, 'jp_%s_%s.ttf' % (fam.replace(' ', ''), style.replace(' ', '')))
            font.save(path)
            print(path)


if __name__ == '__main__':
    build()
