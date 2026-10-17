"""Avance de la acción en curso del servidor, para la barra de carga de los editores (GET /api/progress).

begin() al empezar una petición que cambia algo, step(pct, texto) en sus etapas y end() al terminar.
part(a, b) da una función step para una sub-tarea que ocupa del a % al b % (p. ej. un escenario de varios).
"""
import threading
import time

_LOCK = threading.Lock()
STATE = {'active': False, 'pct': 0, 'label': '', 'since': 0.0, 'real': False}
_DEPTH = [0]   # peticiones a la vez: el avance se reinicia solo al empezar la primera y acaba con la última


def begin(label=''):
    with _LOCK:
        if _DEPTH[0] == 0:
            STATE.update(active=True, pct=0, label=label, since=time.time(), real=False)
        _DEPTH[0] += 1


def step(pct, label=None):
    """Avance real (0-100); nunca retrocede dentro de la misma acción."""
    with _LOCK:
        STATE['pct'] = max(STATE['pct'], min(100, int(pct)))
        STATE['real'] = True
        if label:
            STATE['label'] = label


def part(a, b):
    """step(i, n, texto) que reparte la sub-tarea i de n entre a % y b %."""
    def f(i, n, label=None):
        step(a + (b - a) * (i / float(n) if n else 1), label)
    return f


def end():
    with _LOCK:
        _DEPTH[0] = max(0, _DEPTH[0] - 1)
        if _DEPTH[0] == 0:
            STATE.update(active=False, pct=100)


def get():
    with _LOCK:
        d = dict(STATE)
    d['seconds'] = round(time.time() - d['since'], 1) if d['active'] else 0
    return d
