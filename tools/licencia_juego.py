"""«Invalid License Key» error of Making History 1 / Gold (Steam guide 645617172).

The game (32-bit, no admin) reads the registry with UAC virtualization: the values in
HKCU\\Software\\Classes\\VirtualStore\\MACHINE\\SOFTWARE\\WOW6432Node\\Muzzy Lane Software\\<clave>
win over HKLM, per key: once the game key exists there (even with only Locale), the game does not see the LicenseKey
Steam writes to HKLM and says «Invalid License Key». Like the guide, fix() deletes that copy, but first exports it to a
backup .reg and, when HKLM is writable, moves its language and folders there.

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

LIC = ('license key', 'licensekey', 'customerid')   # license values; the others (Locale, folders) do not affect the license


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
    """[{game, key, values}]: games whose VirtualStore key hides the HKLM license (without showing the key).
    Virtualization works per key, not per value: once the VirtualStore key exists the game reads only that key,
    so a copy with Locale but no LicenseKey already gives «Invalid License Key»."""
    res = []
    for game, name in KEYS.items():
        vs = _values(winreg.HKEY_CURRENT_USER, VSTORE + '\\' + name)
        if vs is None:
            continue
        vsl = {n.lower(): v for n, v in vs.items()}
        lm = {n.lower(): v for n, v in (_values(winreg.HKEY_LOCAL_MACHINE, BASE + '\\' + name) or {}).items()}
        if any(lm.get(n) and vsl.get(n) != lm[n] for n in LIC):
            res.append({'game': game, 'key': name, 'values': sorted(vs), 'installed': gamepaths.installed(game)})
    return res


def fix():
    """Backs up the virtualized key, moves its non-license values to HKLM when allowed and deletes it. -> {fixed, backups}"""
    fixed, backups = [], []
    for p in check():
        sub = VSTORE + '\\' + p['key']
        bak = os.path.join(gamepaths.ROOT, 'backup_licencia_%s_%s.reg' % (p['game'], time.strftime('%Y%m%d_%H%M%S')))
        r = subprocess.run(['reg', 'export', 'HKCU\\' + sub, bak, '/y'], capture_output=True)
        if r.returncode or not os.path.exists(bak):
            raise OSError('no se pudo respaldar %s; no se ha borrado nada' % p['key'])
        backups.append(bak)
        try:  # keeps language and folders when HKLM is writable (permanent fix done); otherwise they are lost, as in the guide
            with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, BASE + '\\' + p['key'], 0, winreg.KEY_SET_VALUE) as k:
                for n, v in _values(winreg.HKEY_CURRENT_USER, sub).items():
                    if n.lower() not in LIC:
                        winreg.SetValueEx(k, n, 0, winreg.REG_SZ, v)
        except OSError:
            pass
        if subprocess.run(['reg', 'delete', 'HKCU\\' + sub, '/f'], capture_output=True).returncode:
            raise OSError('no se pudo borrar %s (respaldo: %s)' % (p['key'], bak))
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
      if ('license key', 'licensekey', 'customerid' -notcontains $n.ToLower()) { Set-ItemProperty $dst -Name $n -Value $k.GetValue($n) }
    }
  }
}
$acl = Get-Acl $LM
$acl.AddAccessRule((New-Object System.Security.AccessControl.RegistryAccessRule((New-Object System.Security.Principal.SecurityIdentifier('%(who)s')), 'FullControl', 'ContainerInherit', 'None', 'Allow')))
Set-Acl $LM $acl
if (Test-Path $VS) { Remove-Item $VS -Recurse -Force }
$MVS = 'HKLM:\SOFTWARE\Classes\VirtualStore\MACHINE\SOFTWARE\WOW6432Node\Muzzy Lane Software'
if (Test-Path $MVS) { reg export ($MVS -replace ':', '') "$BAK`_virtualstore_machine.reg" /y | Out-Null; Remove-Item $MVS -Recurse -Force }
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
