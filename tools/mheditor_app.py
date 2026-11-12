"""MHEditor: the Making History editors as a desktop program (native WebView2 window).

Starts the editors' server inside the same process (or uses one already running) and shows it in a
Windows window with a menu to switch between the map, scenario and image editors.
Packaged with PyInstaller as MHEditor.exe (see build_exe.py).

Data (projects, backups, logs): the making-history folder (MH_ROOT). With the .exe it is looked for next to it or in the
parent folder; if none, Documentos\\MHEditor is used.
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
    'es': {'editors': 'Editores', 'map': 'Mapa (regiones)', 'scen': 'Escenarios', 'img': 'Imágenes', 'models': 'Modelos 3D', 'reload': 'Recargar',
           'help': 'Ayuda', 'data': 'Carpeta de datos', 'ask': '¿Desea salir sin guardar los cambios?'},
    'en': {'editors': 'Editors', 'map': 'Map (regions)', 'scen': 'Scenarios', 'img': 'Images', 'models': '3D models', 'reload': 'Reload',
           'help': 'Help', 'data': 'Data folder', 'ask': 'Leave without saving the changes?'},
    'ru': {'editors': 'Редакторы', 'map': 'Карта (регионы)', 'scen': 'Сценарии', 'img': 'Изображения', 'models': '3D-модели', 'reload': 'Обновить',
           'help': 'Справка', 'data': 'Папка данных', 'ask': 'Выйти без сохранения изменений?'},
}


class Api:
    """Called from the page (pywebview.api): «unsaved changes» state."""
    dirty = False

    def set_dirty(self, value):
        Api.dirty = bool(value)


def ask(text):
    """Native Windows Yes/No dialog (works from any thread)."""
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
        for _ in range(240):          # loading the map takes a few seconds
            if server_up(PORT):
                break
            time.sleep(0.25)
    base = 'http://localhost:%d' % PORT
    webview.settings['ALLOW_DOWNLOADS'] = True        # export GeoJSON, background images, PNG…
    try:        # own identity in the taskbar: without this Windows may show a cached generic icon
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('avlopezparra.MHEditor')
    except Exception:
        pass
    win = webview.create_window(TITLE, base + '/', width=1500, height=950, min_size=(900, 600), text_select=True, js_api=Api())
    T = TEXTS[lang()]

    def leave_ok():
        # with unsaved changes it asks; if accepted, the page does not ask again (beforeunload)
        if not Api.dirty:
            return True
        if ask(TEXTS.get(lang(), TEXTS['es'])['ask']):
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
            MenuAction(T['scen'], go('/scenario')),
            MenuAction(T['img'], go('/imagenes')),
            MenuAction(T['models'], go('/modelos')),
            MenuSeparator(),
            MenuAction(T['reload'], lambda: leave_ok() and win.evaluate_js('location.reload()')),
        ]),
        Menu(T['help'], [
            MenuAction(T['data'], lambda: os.startfile(os.environ['MH_ROOT'])),
        ]),
    ]
    # window cache (WebView2) capped at 64 MB: without it, it grew to hundreds of MB with the map tiles
    os.environ.setdefault('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', '--disk-cache-size=67108864')
    webview.start(gui='edgechromium', menu=menu, private_mode=False,
                  storage_path=os.path.join(os.environ['MH_ROOT'], '_ventana_perfil'))


if __name__ == '__main__':
    main()
