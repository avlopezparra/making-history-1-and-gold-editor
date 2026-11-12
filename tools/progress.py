"""Progress of the server's current action, for the editors' loading bar (GET /api/progress).

begin() when starting a request that changes something, step(pct, text) at its stages and end() when done.
part(a, b) gives a step function for a sub-task spanning a % to b % (e.g. one scenario of several).
"""
import threading
import time

_LOCK = threading.Lock()
STATE = {'active': False, 'pct': 0, 'label': '', 'since': 0.0, 'real': False}
_DEPTH = [0]   # concurrent requests: progress resets only when the first starts and ends with the last


def begin(label=''):
    with _LOCK:
        if _DEPTH[0] == 0:
            STATE.update(active=True, pct=0, label=label, since=time.time(), real=False)
        _DEPTH[0] += 1


def step(pct, label=None):
    """Real progress (0-100); never goes back within the same action."""
    with _LOCK:
        STATE['pct'] = max(STATE['pct'], min(100, int(pct)))
        STATE['real'] = True
        if label:
            STATE['label'] = label


def part(a, b):
    """step(i, n, text) that maps sub-task i of n between a % and b %."""
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
