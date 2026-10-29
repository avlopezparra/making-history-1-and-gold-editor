"""Himnos nacionales (globales, como el mod «More Anthems»).

El juego reproduce al entrar a la partida la lista 'PlayListAnthem' + nombre del país del jugador
(UI2DEnterGame.xml). Esa lista y su pista se declaran en Modern Europe/system/UI/SoundPack.xml
(MusicPlayListData + MusicTrackData) y el audio es un WAV PCM 16 bits 44,1 kHz estéreo en UI/sounds.
No dependen del escenario: valen para todos (salvo un escenario con su propio ui/SoundPack.xml).

Los audios importados quedan en ROOT/himnos (preparados); solo se escriben en el juego con install().
"""
import json
import os
import re
import shutil
import subprocess
import time

import gamepaths

STAGE = os.path.join(gamepaths.ROOT, 'himnos')
MANIFEST = os.path.join(STAGE, 'himnos.json')


def ui_dir(key=None):
    return os.path.join(gamepaths.path(key), 'Modern Europe', 'system', 'UI')


def track_name(country):
    return 'Anthem' + re.sub(r'[^A-Za-z0-9]', '', country)


def wav_rel(country):
    return 'sounds/anthem_%s.wav' % re.sub(r'[^a-z0-9 _-]', '', country.lower()).strip()


def _manifest():
    try:
        return json.load(open(MANIFEST, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save_manifest(m):
    os.makedirs(STAGE, exist_ok=True)
    json.dump(m, open(MANIFEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def game_anthems(ui=None):
    """{país: archivo wav} de las listas PlayListAnthem<país> del SoundPack.xml del juego."""
    ui = ui or ui_dir()
    txt = open(os.path.join(ui, 'SoundPack.xml'), encoding='latin-1').read()
    tracks = dict(re.findall(r'<object type="MusicTrackData"[^>]*>\s*<property name="strName" value="([^"]*)"/>\s*'
                             r'<property name="fileName" value="([^"]*)"/>', txt))
    out = {}
    for country, tr in re.findall(r'<property name="strName" value="PlayListAnthem([^"]*)"/>\s*'
                                  r'<property name="strTrackNames" value="([^"]*)"/>', txt):
        f = tracks.get(tr)
        out[country] = {'file': f, 'exists': bool(f) and os.path.isfile(os.path.join(ui, f))}
    return out


def status(ui=None):
    return {'game': game_anthems(ui), 'staged': _manifest()}


def ffmpeg():
    exe = shutil.which('ffmpeg')
    if exe:
        return exe
    base = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WinGet', 'Packages')
    for dp, _, fs in os.walk(base) if os.path.isdir(base) else []:
        if 'ffmpeg.exe' in fs:
            return os.path.join(dp, 'ffmpeg.exe')
    raise ValueError('falta ffmpeg para convertir el audio (instálalo: winget install ffmpeg)')


def import_audio(country, data, ext='mp3', max_sec=180):
    """Convierte el audio (bytes de cualquier formato) al WAV del juego y lo deja preparado."""
    country = (country or '').strip()
    if not country or '"' in country or '<' in country:
        raise ValueError('nombre de país no válido')
    os.makedirs(STAGE, exist_ok=True)
    src = os.path.join(STAGE, '_entrada.' + re.sub(r'[^a-z0-9]', '', ext.lower())[:5])
    open(src, 'wb').write(data)
    dst = os.path.join(STAGE, os.path.basename(wav_rel(country)))
    r = subprocess.run([ffmpeg(), '-y', '-v', 'error', '-i', src, '-t', str(max_sec), '-vn',
                        '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2', dst], capture_output=True, text=True)
    os.remove(src)
    if r.returncode or not os.path.isfile(dst):
        raise ValueError('ffmpeg no pudo convertir el audio: ' + (r.stderr or '').strip()[-300:])
    m = _manifest()
    m[country] = {'file': os.path.basename(dst), 'size': os.path.getsize(dst)}
    _save_manifest(m)
    return {'ok': True, 'country': country, 'size': m[country]['size'],
            'replaces': country in game_anthems()}


def remove_staged(country):
    m = _manifest()
    e = m.pop(country, None)
    if e:
        try:
            os.remove(os.path.join(STAGE, e['file']))
        except OSError:
            pass
    _save_manifest(m)
    return {'ok': True}


def _add_entries(txt, country, nl):
    tr, pl = track_name(country), 'PlayListAnthem' + country
    track = ('\t\t<object type="MusicTrackData" name="objMusicTracks">%s\t\t\t<property name="strName" value="%s"/>%s'
             '\t\t\t<property name="fileName" value="%s"/>%s\t\t\t<property name="fVolume" value="1.0"/>%s\t\t</object>%s'
             % (nl, tr, nl, wav_rel(country), nl, nl, nl))
    plist = ('\t\t<object type="MusicPlayListData" name="objPlayLists">%s\t\t\t<property name="strName" value="%s"/>%s'
             '\t\t\t<property name="strTrackNames" value="%s"/>%s\t\t</object>%s' % (nl, pl, nl, tr, nl, nl))
    # pista: se reemplaza su archivo si ya existe; si no, va antes de «<!-- Play Lists -->»
    pat = r'(<property name="strName" value="%s"/>\s*<property name="fileName" value=")[^"]*(")' % re.escape(tr)
    if re.search(pat, txt):
        txt = re.sub(pat, lambda mo: mo.group(1) + wav_rel(country) + mo.group(2), txt)
    else:
        i = txt.find('<!-- Play Lists -->')
        if i < 0:
            i = txt.find('<object type="MusicPlayListData"')
        i = txt.rfind('\n', 0, i) + 1
        txt = txt[:i] + track + txt[i:]
    pat = r'(<property name="strName" value="%s"/>\s*<property name="strTrackNames" value=")[^"]*(")' % re.escape(pl)
    if re.search(pat, txt):
        txt = re.sub(pat, lambda mo: mo.group(1) + tr + mo.group(2), txt)
    else:
        i = txt.rfind('</objectDef>')
        i = txt.rfind('\n', 0, i) + 1
        txt = txt[:i] + plist + txt[i:]
    return txt


def install(ui=None, backup=None):
    """Copia los himnos preparados al juego (UI/sounds) y los declara en UI/SoundPack.xml, con respaldo previo."""
    ui = ui or ui_dir()
    m = _manifest()
    if not m:
        return {'ok': False, 'error': 'no hay himnos preparados'}
    bdir = os.path.join(backup or os.path.join(gamepaths.backup_root(), 'himnos'), time.strftime('%Y%m%d_%H%M%S'))
    os.makedirs(os.path.join(bdir, 'sounds'), exist_ok=True)
    sp = os.path.join(ui, 'SoundPack.xml')
    shutil.copy2(sp, os.path.join(bdir, 'SoundPack.xml'))
    raw = open(sp, 'rb').read().decode('latin-1')
    nl = '\r\n' if '\r\n' in raw else '\n'
    written = []
    for country, e in m.items():
        dst = os.path.join(ui, *wav_rel(country).split('/'))
        if os.path.isfile(dst):
            shutil.copy2(dst, os.path.join(bdir, 'sounds', os.path.basename(dst)))
        shutil.copy2(os.path.join(STAGE, e['file']), dst)
        raw = _add_entries(raw, country, nl)
        written.append(country)
    open(sp, 'wb').write(raw.encode('latin-1'))
    for country in written:      # ya instalados: dejan de estar preparados
        remove_staged(country)
    return {'ok': True, 'installed': written, 'backup': bdir}
