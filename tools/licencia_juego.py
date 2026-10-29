"""Error «Invalid License Key» de Making History 1 / Gold (guía de Steam 645617172).

El juego (32 bits, sin admin) lee el registro con la virtualización de UAC: los valores de
HKCU\\Software\\Classes\\VirtualStore\\MACHINE\\SOFTWARE\\WOW6432Node\\Muzzy Lane Software\\<clave>
ganan sobre HKLM. Si ahí quedó una «License Key» (o un CustomerID) viejo o vacío, el juego no ve la clave buena
que Steam escribe en HKLM y dice «Invalid License Key». La guía borra toda la carpeta; aquí solo se borran esos
valores (el Locale que escribe idioma_juego.py se conserva) y antes se exporta la clave a un .reg de respaldo.

Arreglo permanente (permanente()): con un solo permiso de administrador da a los usuarios permiso de escritura en
HKLM\\...\\Muzzy Lane Software, pasa a HKLM lo que el juego veía en VirtualStore (sin la licencia vieja) y borra la copia.
Como el juego ya puede escribir en HKLM, Windows deja de virtualizar y no vuelve a aparecer una licencia tapada.

Uso:  python licencia_juego.py            -> comprueba
      python licencia_juego.py fix        -> corrige (con respaldo en making-history/backup_licencia_<juego>_<fecha>.reg)
      python licencia_juego.py permanente -> arreglo permanente (pide admin; respaldo de HKLM y VirtualStore en .reg)
"""
import os
import subprocess
import sys
import time
import winreg

import gamepaths
from idioma_juego import KEYS, BASE, VSTORE

LIC = ('license key', 'customerid')   # valores de licencia; los demás (Locale, carpetas) no tocan la licencia


def _values(root, sub):
    try:
        with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as k:
            out, i = {}, 0
            while True:
                try:
                    n, v, _ = winreg.EnumValue(k, i)
                except OSError:
                    return out
                out[n] = v
                i += 1
    except OSError:
        return None


def check():
    """[{game, key, values: [nombres que tapan la licencia de HKLM]}] (sin mostrar la clave)."""
    res = []
    for game, name in KEYS.items():
        vs = _values(winreg.HKEY_CURRENT_USER, VSTORE + '\\' + name) or {}
        lm = {n.lower(): v for n, v in (_values(winreg.HKEY_LOCAL_MACHINE, BASE + '\\' + name) or {}).items()}
        bad = [n for n, v in vs.items() if n.lower() in LIC and lm.get(n.lower()) != v]
        if bad:
            res.append({'game': game, 'key': name, 'values': bad, 'installed': gamepaths.installed(game)})
    return res


def fix():
    """Respalda la clave virtualizada y borra solo los valores de licencia que tapan HKLM. -> {fixed, backups}"""
    fixed, backups = [], []
    for p in check():
        sub = VSTORE + '\\' + p['key']
        bak = os.path.join(gamepaths.ROOT, 'backup_licencia_%s_%s.reg' % (p['game'], time.strftime('%Y%m%d_%H%M%S')))
        r = subprocess.run(['reg', 'export', 'HKCU\\' + sub, bak, '/y'], capture_output=True)
        if r.returncode or not os.path.exists(bak):
            raise OSError('no se pudo respaldar %s; no se ha borrado nada' % p['key'])
        backups.append(bak)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub, 0, winreg.KEY_SET_VALUE) as k:
            for n in p['values']:
                winreg.DeleteValue(k, n)
        fixed.append(p)
    return {'fixed': fixed, 'backups': backups}


def writable():
    """True si el usuario ya escribe en HKLM (arreglo permanente hecho: no hay virtualización)."""
    try:
        winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, BASE, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY).Close()
        return True
    except OSError:
        return False


PS = r'''$ErrorActionPreference = 'Stop'
$LM = '%(lm)s'; $VS = '%(vs)s'; $BAK = '%(bak)s'
reg export ($LM -replace ':', '') "$BAK`_hklm.reg" /y | Out-Null
if (Test-Path $VS) { reg export ($VS -replace ':', '') "$BAK`_virtualstore.reg" /y | Out-Null }
if (-not (Test-Path $LM)) { New-Item $LM -Force | Out-Null }
if (Test-Path $VS) {
  foreach ($k in Get-ChildItem $VS) {
    $dst = Join-Path $LM $k.PSChildName
    if (-not (Test-Path $dst)) { New-Item $dst -Force | Out-Null }
    foreach ($n in $k.GetValueNames()) {
      if ('license key', 'customerid' -notcontains $n.ToLower()) { Set-ItemProperty $dst -Name $n -Value $k.GetValue($n) }
    }
  }
}
$acl = Get-Acl $LM
$acl.AddAccessRule((New-Object System.Security.AccessControl.RegistryAccessRule((New-Object System.Security.Principal.SecurityIdentifier('%(who)s')), 'SetValue,CreateSubKey,ReadKey', 'ContainerInherit', 'None', 'Allow')))
Set-Acl $LM $acl
if (Test-Path $VS) { Remove-Item $VS -Recurse -Force }
'''


def script(lm='HKLM:\\' + BASE, vs='HKCU:\\' + VSTORE, who='S-1-5-32-545'):
    """Texto del .ps1 del arreglo permanente (who: SID de Usuarios); las rutas se cambian en las pruebas."""
    bak = os.path.join(gamepaths.ROOT, 'backup_licencia_' + time.strftime('%Y%m%d_%H%M%S'))
    return PS % {'lm': lm, 'vs': vs, 'bak': bak, 'who': who}


def permanente():
    """Lanza el .ps1 con permiso de administrador (Windows lo pregunta). -> {script}"""
    ps = os.path.join(gamepaths.ROOT, 'arreglo_licencia.ps1')
    open(ps, 'w', encoding='utf-8-sig').write(script())
    subprocess.Popen(['powershell', '-NoProfile', '-Command',
                      "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%s\"'" % ps])
    return {'script': ps}


if __name__ == '__main__':
    a = sys.argv[1:]
    print(fix() if a == ['fix'] else permanente() if a == ['permanente'] else
          (check() or 'sin problemas de licencia en VirtualStore', 'permanente: %s' % writable()))
