"""Mete U+200A (espacio finisimo, ancho 0 en fuentes_jp) entre caracteres japoneses de locale/jp.

El motor de texto (fonts.dll) solo parte lineas en caracteres iswspace; el japones no tiene espacios y las
descripciones largas se salian de la caja. U+200A es iswspace y en nuestras fuentes no ocupa ancho.
Respeta el kinsoku basico: no corta antes de 、。」）ー etc. ni despues de 「（.
Uso: python jp_wrap.py <carpeta_jp_origen> <carpeta_destino>
"""
import os
import re
import sys

HS = ' '
CJK = re.compile(r'[　-ヿ㐀-鿿＀-￯]')
NO_BEFORE = set('、。，．・：；？！ー」』）】〕〉》ゝゞヽヾぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ…‥')
NO_AFTER = set('「『（【〔〈《')


def wrap(text):
    text = text.replace(HS, '')  # idempotente
    out = []
    for i, c in enumerate(text):
        out.append(c)
        n = text[i + 1] if i + 1 < len(text) else ''
        if n and CJK.match(c) and CJK.match(n) and n not in NO_BEFORE and c not in NO_AFTER:
            out.append(HS)
    return ''.join(out)


def wrap_xml(xml):
    # solo dentro de value="..." (nunca ids ni etiquetas)
    return re.sub(r'(value=")([^"]*)(")', lambda m: m.group(1) + wrap(m.group(2)) + m.group(3), xml)


def wrap_dir(src, dst):
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(src):
        if f.endswith('.xml'):
            t = open(os.path.join(src, f), encoding='utf-8').read()
            open(os.path.join(dst, f), 'w', encoding='utf-8', newline='').write(wrap_xml(t))


assert wrap('世界は「平和」。') == '世' + HS + '界' + HS + 'は' + HS + '「平' + HS + '和」。'
assert wrap('abc 19世紀') == 'abc 19世' + HS + '紀' == wrap(wrap('abc 19世紀'))

if __name__ == '__main__':
    wrap_dir(*sys.argv[1:3])
