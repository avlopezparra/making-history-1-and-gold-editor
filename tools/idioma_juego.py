"""Cambia el idioma de Making History 1 / Gold (lee system/locale/<idioma>).

Uso:  python idioma_juego.py                 -> muestra el idioma actual y los disponibles
      python idioma_juego.py mh1 esp         -> MH1 en espanol
      python idioma_juego.py gold de         -> Gold en aleman

El juego (32 bits, sin admin) lee `Locale` de la copia virtualizada
HKCU\\Software\\Classes\\VirtualStore\\MACHINE\\SOFTWARE\\WOW6432Node\\Muzzy Lane Software\\<clave>,
que gana sobre HKLM (los .reg del juego escriben en HKLM y por eso dejaron de funcionar).
Escribimos ahi y, si se puede (admin), tambien en HKLM. Hay que ejecutarlo desde un proceso normal del usuario
(no desde el contenedor de la app de Claude, cuyo registro es privado). Guarda copia del valor anterior en
making-history/backup_locale_<juego>.txt.
"""
import os
import sys
import winreg

import gamepaths

KEYS = {'mh1': 'Making History 2.0', 'gold': 'Making History Gold'}
BASE = r'SOFTWARE\WOW6432Node\Muzzy Lane Software'
VSTORE = r'Software\Classes\VirtualStore\MACHINE' + '\\' + BASE


def idiomas(game):
    d = os.path.join(gamepaths.path(game), 'system', 'locale')
    return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)))


def _read(root, sub):
    try:
        with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as k:
            return winreg.QueryValueEx(k, 'Locale')[0]
    except OSError:
        return None


def actual(game):
    """Lo que ve el juego: VirtualStore primero, luego HKLM."""
    name = KEYS[game]
    return (_read(winreg.HKEY_CURRENT_USER, VSTORE + '\\' + name)
            or _read(winreg.HKEY_LOCAL_MACHINE, BASE + '\\' + name))


def cambiar(game, lang):
    if lang not in idiomas(game):
        raise ValueError('idioma %r no existe en system/locale (hay: %s)' % (lang, ', '.join(idiomas(game))))
    name = KEYS[game]
    prev = actual(game)
    with open(os.path.join(gamepaths.ROOT, 'backup_locale_%s.txt' % game), 'w') as f:
        f.write(str(prev))
    try:  # con admin o tras el arreglo permanente de licencia_juego.py (sin VirtualStore): basta HKLM
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
        print('anterior:', cambiar(sys.argv[1], sys.argv[2]), '-> nuevo:', sys.argv[2])
    else:
        for g in KEYS:
            if gamepaths.installed(g):
                print(g, 'actual:', actual(g), '| disponibles:', ', '.join(idiomas(g)))
