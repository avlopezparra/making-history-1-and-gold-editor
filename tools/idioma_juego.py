"""Changes the language of Making History 1 / Gold (reads system/locale/<idioma>).

Usage:  python idioma_juego.py                 -> shows the current language and the available ones
      python idioma_juego.py mh1 esp         -> MH1 in Spanish
      python idioma_juego.py gold de         -> Gold in German

The game (32-bit, no admin) reads `Locale` from the virtualized copy
HKCU\\Software\\Classes\\VirtualStore\\MACHINE\\SOFTWARE\\WOW6432Node\\Muzzy Lane Software\\<clave>,
which wins over HKLM (the game's .reg files write to HKLM and that is why they stopped working).
We write there and, if possible (admin), also to HKLM. It must be run from a normal user process
(not from the Claude app container, whose registry is private). Saves a copy of the previous value in
making-history/backup_locale_<juego>.txt.
"""
import os
import sys
import winreg

import gamepaths

KEYS = {'mh1': 'Making History 2.0', 'gold': 'Making History Gold'}
BASE = r'SOFTWARE\WOW6432Node\Muzzy Lane Software'
VSTORE = r'Software\Classes\VirtualStore\MACHINE' + '\\' + BASE


def languages(game):
    d = os.path.join(gamepaths.path(game), 'system', 'locale')
    return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)))


def _read(root, sub):
    try:
        with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as k:
            return winreg.QueryValueEx(k, 'Locale')[0]
    except OSError:
        return None


def current_language(game):
    """What the game sees: VirtualStore first, then HKLM."""
    name = KEYS[game]
    return (_read(winreg.HKEY_CURRENT_USER, VSTORE + '\\' + name)
            or _read(winreg.HKEY_LOCAL_MACHINE, BASE + '\\' + name))


def set_language(game, lang):
    if lang not in languages(game):
        raise ValueError('idioma %r no existe en system/locale (hay: %s)' % (lang, ', '.join(languages(game))))
    name = KEYS[game]
    prev = current_language(game)
    with open(os.path.join(gamepaths.ROOT, 'backup_locale_%s.txt' % game), 'w') as f:
        f.write(str(prev))
    try:  # with admin or after licencia_juego.py's permanent fix (no VirtualStore): HKLM is enough
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, BASE + '\\' + name, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, 'Locale', 0, winreg.REG_SZ, lang)
        if _read(winreg.HKEY_CURRENT_USER, VSTORE + '\\' + name) is None:
            return prev
    except OSError:
        pass
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, VSTORE + '\\' + name, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, 'Locale', 0, winreg.REG_SZ, lang)
    return prev


if __name__ == '__main__':
    if len(sys.argv) == 3:
        print('anterior:', set_language(sys.argv[1], sys.argv[2]), '-> nuevo:', sys.argv[2])
    else:
        for g in KEYS:
            if gamepaths.installed(g):
                print(g, 'actual:', current_language(g), '| disponibles:', ', '.join(languages(g)))
