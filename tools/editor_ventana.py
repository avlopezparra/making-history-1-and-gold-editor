"""Opens the editors in their own window (no browser bars), like a desktop application.

Starts the local server if it is not running and opens the interface in app mode (--app) of an installed
Chromium browser (Edge, Chrome or Brave). If there is none, uses the normal browser.
Usage: pythonw editor_ventana.py [mapa|escenarios|imagenes]
"""
import os
import socket
import subprocess
import sys
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
PAGES = {'mapa': '/', 'escenarios': '/scenario', 'imagenes': '/imagenes'}
BROWSERS = [
    r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe',
    r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe',
    r'%ProgramFiles%\Google\Chrome\Application\chrome.exe',
    r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe',
    r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe',
    r'%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe',
    r'%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe',
]


def server_up():
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(('127.0.0.1', PORT)) == 0


def main():
    page = PAGES.get(sys.argv[1] if len(sys.argv) > 1 else 'mapa', '/')
    if not server_up():
        py = sys.executable.replace('python.exe', 'pythonw.exe')
        if not os.path.exists(py):
            py = sys.executable
        subprocess.Popen([py, os.path.join(HERE, 'editor_server.py'), '--no-abrir', '--puerto', str(PORT)],
                         cwd=HERE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(120):          # the server takes a few seconds to load the map
            if server_up():
                break
            time.sleep(0.5)
    url = 'http://localhost:%d%s' % (PORT, page)
    exe = next((os.path.expandvars(b) for b in BROWSERS if os.path.exists(os.path.expandvars(b))), None)
    if exe:
        # own profile: the window remembers its size and does not mix tabs with the usual browser
        profile = os.path.join(HERE, '..', '_ventana_perfil')
        subprocess.Popen([exe, '--app=' + url, '--user-data-dir=' + os.path.abspath(profile), '--window-size=1500,950'])
    else:
        webbrowser.open(url)


if __name__ == '__main__':
    main()
