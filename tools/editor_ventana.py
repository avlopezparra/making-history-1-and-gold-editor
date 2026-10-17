"""Abre los editores en su propia ventana (sin barras del navegador), como una aplicación de escritorio.

Arranca el servidor local si no está en marcha y abre la interfaz en modo aplicación (--app) de un navegador
Chromium instalado (Edge, Chrome o Brave). Si no hay ninguno, usa el navegador normal.
Uso: pythonw editor_ventana.py [mapa|escenarios|imagenes]
"""
import os
import socket
import subprocess
import sys
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
PAGES = {'mapa': '/', 'escenarios': '/escenario', 'imagenes': '/imagenes'}
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
        for _ in range(120):          # el servidor tarda unos segundos en cargar el mapa
            if server_up():
                break
            time.sleep(0.5)
    url = 'http://localhost:%d%s' % (PORT, page)
    exe = next((os.path.expandvars(b) for b in BROWSERS if os.path.exists(os.path.expandvars(b))), None)
    if exe:
        # perfil propio: la ventana recuerda su tamaño y no mezcla pestañas con el navegador habitual
        profile = os.path.join(HERE, '..', '_ventana_perfil')
        subprocess.Popen([exe, '--app=' + url, '--user-data-dir=' + os.path.abspath(profile), '--window-size=1500,950'])
    else:
        webbrowser.open(url)


if __name__ == '__main__':
    main()
