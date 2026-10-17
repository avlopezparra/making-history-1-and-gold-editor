"""MHEditor: los editores de Making History como programa de escritorio (ventana nativa WebView2).

Arranca el servidor de los editores dentro del mismo proceso (o usa uno que ya esté en marcha) y lo muestra en una
ventana de Windows con menú para cambiar entre el editor de mapa, el de escenarios y el de imágenes.
Empaquetado con PyInstaller como MHEditor.exe (ver build_exe.py).

Datos (proyectos, respaldos, registros): la carpeta making-history (MH_ROOT). Con el .exe se busca junto a él o en la
carpeta superior; si no hay, se usa Documentos\\MHEditor.
"""
import os
import socket
import sys
import threading
import time

PORT = int(os.environ.get('MH_PORT') or 8765)   # MH_PORT: otro puerto (pruebas)
TITLE = 'Making History 1 & Gold Editor'


def data_root():
    if os.environ.get('MH_ROOT'):
        return os.environ['MH_ROOT']
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        for cand in (exe_dir, os.path.dirname(exe_dir)):
            if any(os.path.exists(os.path.join(cand, x)) for x in ('editor_proyecto', 'backup', 'ultimo_regionpack.json')):
                return cand
        d = os.path.join(os.path.expanduser('~'), 'Documents', 'MHEditor')
        os.makedirs(d, exist_ok=True)
        return d
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


def server_up(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(('127.0.0.1', port)) == 0


def run_server(port):
    import editor_server
    sys.argv = ['editor_server', '--no-abrir', '--puerto', str(port)]
    editor_server.main()


TEXTS = {
    'es': {'editors': 'Editores', 'map': 'Mapa (regiones)', 'scen': 'Escenarios', 'img': 'Imágenes', 'reload': 'Recargar',
           'help': 'Ayuda', 'data': 'Carpeta de datos', 'ask': '¿Desea salir sin guardar los cambios?'},
    'en': {'editors': 'Editors', 'map': 'Map (regions)', 'scen': 'Scenarios', 'img': 'Images', 'reload': 'Reload',
           'help': 'Help', 'data': 'Data folder', 'ask': 'Leave without saving the changes?'},
}


class Api:
    """Llamado desde la pagina (pywebview.api): estado de «cambios sin guardar»."""
    dirty = False

    def set_dirty(self, value):
        Api.dirty = bool(value)


def ask(text):
    """Cuadro de dialogo nativo de Windows Si/No (sirve desde cualquier hilo)."""
    import ctypes
    return ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x04 | 0x30 | 0x1000) == 6   # MB_YESNO|ICONWARNING|SYSTEMMODAL


def lang():
    import json
    try:
        return json.load(open(os.path.join(os.environ['MH_ROOT'], 'idioma.json')))['lang']
    except (OSError, ValueError, KeyError):
        return 'es'


def main():
    os.environ['MH_ROOT'] = data_root()
    import webview
    if not server_up(PORT):
        threading.Thread(target=run_server, args=(PORT,), daemon=True).start()
        for _ in range(240):          # cargar el mapa tarda unos segundos
            if server_up(PORT):
                break
            time.sleep(0.25)
    base = 'http://localhost:%d' % PORT
    webview.settings['ALLOW_DOWNLOADS'] = True        # exportar GeoJSON, imágenes de fondo, PNG…
    win = webview.create_window(TITLE, base + '/', width=1500, height=950, min_size=(900, 600), text_select=True, js_api=Api())
    T = TEXTS[lang()]

    def leave_ok():
        # con cambios sin guardar se pregunta; si se acepta, la pagina no vuelve a preguntar (beforeunload)
        if not Api.dirty:
            return True
        if ask(T['ask']):
            Api.dirty = False
            win.evaluate_js('window.mhSkipUnload = true')
            return True
        return False

    def go(path):
        return lambda: leave_ok() and win.load_url(base + path)

    def on_closing():
        return None if leave_ok() else False      # False cancela el cierre

    win.events.closing += on_closing
    from webview.menu import Menu, MenuAction, MenuSeparator
    menu = [
        Menu(T['editors'], [
            MenuAction(T['map'], go('/')),
            MenuAction(T['scen'], go('/escenario')),
            MenuAction(T['img'], go('/imagenes')),
            MenuSeparator(),
            MenuAction(T['reload'], lambda: leave_ok() and win.evaluate_js('location.reload()')),
        ]),
        Menu(T['help'], [
            MenuAction(T['data'], lambda: os.startfile(os.environ['MH_ROOT'])),
        ]),
    ]
    webview.start(gui='edgechromium', menu=menu, private_mode=False,
                  storage_path=os.path.join(os.environ['MH_ROOT'], '_ventana_perfil'))


if __name__ == '__main__':
    main()
