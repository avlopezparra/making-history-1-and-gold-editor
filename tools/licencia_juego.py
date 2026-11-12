"""«Invalid License Key» error of Making History 1 / Gold (Steam guide 645617172).

The game (32-bit, no admin) reads the registry with UAC virtualization: the values in
HKCU\\Software\\Classes\\VirtualStore\\MACHINE\\SOFTWARE\\WOW6432Node\\Muzzy Lane Software\\<clave>
win over HKLM. If an old or empty «License Key» (or CustomerID) was left there, the game does not see the good key
Steam writes to HKLM and says «Invalid License Key». The guide deletes the whole folder; here only those
values are deleted (the Locale written by idioma_juego.py is kept) and the key is first exported to a backup .reg.

Permanent fix (permanente()): with a single admin prompt it gives users write permission on
HKLM\\...\\Muzzy Lane Software, moves to HKLM what the game saw in VirtualStore (without the old license) and deletes the copy.
Since the game can now write to HKLM, Windows stops virtualizing and a hidden license never shows up again.

Usage:  python licencia_juego.py            -> checks
      python licencia_juego.py fix        -> fixes (with backup in making-history/backup_licencia_<juego>_<fecha>.reg)
      python licencia_juego.py permanente -> permanent fix (asks for admin; backup of HKLM and VirtualStore in .reg)
"""
import os
import subprocess
import sys
import time
import winreg

import gamepaths
from idioma_juego import KEYS, BASE, VSTORE

LIC = ('license key', 'customerid')   # license values; the others (Locale, folders) do not affect the license


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
    """[{game, key, values: [names hiding the HKLM license]}] (without showing the key)."""
    res = []
    for game, name in KEYS.items():
        vs = _values(winreg.HKEY_CURRENT_USER, VSTORE + '\\' + name) or {}
        lm = {n.lower(): v for n, v in (_values(winreg.HKEY_LOCAL_MACHINE, BASE + '\\' + name) or {}).items()}
        bad = [n for n, v in vs.items() if n.lower() in LIC and lm.get(n.lower()) != v]
        if bad:
            res.append({'game': game, 'key': name, 'values': bad, 'installed': gamepaths.installed(game)})
    return res


def fix():
    """Backs up the virtualized key and deletes only the license values hiding HKLM. -> {fixed, backups}"""
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
    """True if the user already writes to HKLM (permanent fix done: no virtualization)."""
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
    """Text of the permanent-fix .ps1 (who: Users SID); the paths are changed in tests."""
    bak = os.path.join(gamepaths.ROOT, 'backup_licencia_' + time.strftime('%Y%m%d_%H%M%S'))
    return PS % {'lm': lm, 'vs': vs, 'bak': bak, 'who': who}


def make_permanent():
    """Runs the .ps1 with admin permission (Windows asks). -> {script}"""
    ps = os.path.join(gamepaths.ROOT, 'arreglo_licencia.ps1')
    open(ps, 'w', encoding='utf-8-sig').write(script())
    subprocess.Popen(['powershell', '-NoProfile', '-Command',
                      "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%s\"'" % ps])
    return {'script': ps}


if __name__ == '__main__':
    a = sys.argv[1:]
    print(fix() if a == ['fix'] else make_permanent() if a == ['permanente'] else
          (check() or 'sin problemas de licencia en VirtualStore', 'permanente: %s' % writable()))
