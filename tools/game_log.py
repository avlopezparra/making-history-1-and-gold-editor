"""Registro del juego: captura los mensajes de depuración de Making History mientras se juega.

El juego (logger.dll) escribe sus avisos y errores con OutputDebugString —p. ej. «invalid region ID %d for region %s»,
«Failed to load scenario named %s»—, que normalmente nadie ve. Este programa escucha ese canal de Windows
(DBWIN_BUFFER) y los guarda en making-history/logs/juego_<fecha>.log. Sirve para saber por qué un escenario no carga.

Uso: dejarlo abierto (python game_log.py, o «Registro del juego.bat»), abrir el juego, reproducir el problema y cerrar
con Ctrl+C. Solo escucha; no toca el juego. Solo puede haber un oyente a la vez (DebugView, otro game_log…).
"""
import ctypes
import ctypes.wintypes as w
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(os.environ.get('MH_ROOT') or os.path.join(HERE, '..'), 'logs')
GAME_EXES = {'makehist.exe', 'ed.exe', 'console.exe'}

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateEventW.restype = w.HANDLE
k32.CreateFileMappingW.restype = w.HANDLE
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.OpenProcess.restype = w.HANDLE
psapi = ctypes.WinDLL('psapi')


def process_name(pid, cache={}):
    if pid not in cache:
        name = '?'
        h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            buf = ctypes.create_unicode_buffer(260)
            size = w.DWORD(260)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value).lower()
            k32.CloseHandle(h)
        cache[pid] = name
    return cache[pid]


def main(all_processes=False):
    ready = k32.CreateEventW(None, False, False, 'DBWIN_BUFFER_READY')
    data = k32.CreateEventW(None, False, False, 'DBWIN_DATA_READY')
    if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS: puede haber otro oyente (DebugView...)
        print('Aviso: ya existe el canal; si hay otro capturador abierto (DebugView), ciérralo.')
    mapping = k32.CreateFileMappingW(w.HANDLE(-1), None, 0x04, 0, 4096, 'DBWIN_BUFFER')
    view = k32.MapViewOfFile(mapping, 0x0004, 0, 0, 4096)
    if not (ready and data and mapping and view):
        sys.exit('No se pudo abrir el canal de depuración (error %d)' % ctypes.get_last_error())
    os.makedirs(LOGS, exist_ok=True)
    path = os.path.join(LOGS, 'juego_%s.log' % datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    print('Escuchando los mensajes del juego… (Ctrl+C para terminar)\nSe guardan en', os.path.abspath(path))
    n = 0
    with open(path, 'w', encoding='utf-8') as out:
        try:
            while True:
                k32.SetEvent(ready)
                if k32.WaitForSingleObject(data, 500) != 0:
                    continue
                pid = ctypes.c_uint32.from_address(view).value
                msg = ctypes.string_at(view + 4).decode('mbcs', 'replace').rstrip('\r\n')
                name = process_name(pid)
                if not all_processes and name not in GAME_EXES:
                    continue
                line = '%s [%s %d] %s' % (datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3], name, pid, msg)
                out.write(line + '\n')
                out.flush()
                n += 1
                low = msg.lower()
                if any(t in low for t in ('error', 'invalid', 'failed', 'missing', 'could not', 'unable')):
                    print(line)
        except KeyboardInterrupt:
            pass
    print('\n%d mensajes guardados en %s' % (n, os.path.abspath(path)))


if __name__ == '__main__':
    main('--todos' in sys.argv)
