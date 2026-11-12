"""Diagnostic log MHEditor.log (next to the data / the .exe) for the user to send when something fails.

One line per event: startup, each /api request (method, route, status, duration and a short summary of the content: names,
regions, how many items; never whole geometries), each exception with its traceback and what the pages send (JavaScript
errors, error notices and the user's steps). Rotates at ~2 MB and keeps 1 previous. Keys, tokens and AI settings are masked.
"""
import json
import logging
import logging.handlers
import os
import platform
import re
import sys
import time
import traceback

MAX_BYTES, BACKUPS = 2 * 1024 * 1024, 1
LOGGER = logging.getLogger('mheditor.diag')
PATH = [None]
SECRET_KEY = re.compile(r'key|token|secret|password|passwd|auth|cookie', re.I)
SECRET_VAL = re.compile(r'(sk-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,}|(?:key|token|secret|password)\s*[=:]\s*\S+)', re.I)
SKIP_PATHS = ('/api/tile', '/api/progress', '/api/log')          # very frequent and uninteresting (map tiles, progress bar)


def start(root, info):
    """Opens the log (once) and records startup."""
    if PATH[0]:
        return PATH[0]
    PATH[0] = os.path.join(root, 'MHEditor.log')
    try:
        os.makedirs(root, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(PATH[0], maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding='utf-8', delay=True)
    except OSError:
        PATH[0] = None
        return None
    h.setFormatter(logging.Formatter('%(asctime)s %(levelname)-5s %(message)s'))
    LOGGER.addHandler(h)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    LOGGER.disabled = os.path.exists(PATH[0] + '.off')      # «Guardar registro» desmarcado: no se escribe nada
    LOGGER.info('==== START %s', json.dumps(redact(info), ensure_ascii=False, default=str))
    LOGGER.info('python %s · %s · exe=%s', sys.version.split()[0], platform.platform(), bool(getattr(sys, 'frozen', False)))
    orig = traceback.print_exc

    def print_exc(*a, **k):        # exceptions the server already catches (traceback.print_exc) also go to the log
        orig(*a, **k)
        LOGGER.error('exception\n%s', redact(traceback.format_exc()))
    traceback.print_exc = print_exc
    return PATH[0]


def enabled():
    return bool(PATH[0]) and not LOGGER.disabled


def set_enabled(on):
    """Enables/disables the log; remembered via the MHEditor.log.off file."""
    if not PATH[0]:
        return False
    off = PATH[0] + '.off'
    if on:
        if os.path.exists(off):
            os.remove(off)
        LOGGER.disabled = False
        LOGGER.info('log enabled')
    else:
        LOGGER.info('log disabled')
        LOGGER.disabled = True
        open(off, 'w').close()
    return enabled()


def redact(x):
    """Copy without secrets: fields with a secret name -> '***'; key-looking texts -> '***'."""
    if isinstance(x, dict):
        return {k: ('***' if SECRET_KEY.search(str(k)) else redact(v)) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [redact(v) for v in x]
    if isinstance(x, str):
        return SECRET_VAL.sub('***', x)
    return x


def summary(payload, depth=0):
    """Short summary of a request: short texts and numbers as-is; long lists and geometries as «[N]» / «<Polygon>»."""
    if isinstance(payload, dict):
        if 'coordinates' in payload or payload.get('type') in ('FeatureCollection', 'Feature', 'Polygon', 'MultiPolygon', 'LineString'):
            return '<%s>' % payload.get('type', 'geometry')
        if depth > 2:
            return '{%d}' % len(payload)
        return {k: ('***' if SECRET_KEY.search(str(k)) else summary(v, depth + 1)) for k, v in list(payload.items())[:25]}
    if isinstance(payload, list):
        if len(payload) <= 6 and depth <= 2 and not any(isinstance(v, list) for v in payload):
            return [summary(v, depth + 1) for v in payload]
        return '[%d]' % len(payload)
    if isinstance(payload, str):
        s = SECRET_VAL.sub('***', payload)
        return s if len(s) <= 80 else s[:60] + '…(%d)' % len(s)
    return payload


def request(method, path, status, t0, payload=None, error=None):
    if not PATH[0] or any(path.startswith(p) for p in SKIP_PATHS):
        return
    path = re.sub(r'([?&][^=&]*(?:key|token)[^=&]*=)[^&]*', r'\1***', path, flags=re.I)
    line = '%s %s -> %s (%.0f ms)' % (method, path, status, (time.time() - t0) * 1000)
    if payload not in (None, {}):
        line += ' ' + json.dumps(summary(payload), ensure_ascii=False, default=str)[:600]
    if error:
        line += ' ERROR: ' + json.dumps(redact(error), ensure_ascii=False, default=str)[:800]
    (LOGGER.warning if error or (status or 0) >= 400 else LOGGER.info)(line)


def client(entries):
    """What the page sends (POST /api/log): [{page, level, action, msg, stack, ts}]."""
    for e in (entries if isinstance(entries, list) else [entries])[:50]:
        if not isinstance(e, dict):
            continue
        lvl = str(e.get('level') or 'info').lower()
        msg = 'page %s %s [%s] %s' % (str(e.get('page') or '?')[:40], lvl, str(e.get('action') or '')[:60], str(e.get('msg') or '')[:1500])
        if e.get('stack'):
            msg += '\n' + str(e['stack'])[:3000]
        if e.get('ts'):
            msg += ' (t=%s)' % str(e['ts'])[:30]
        (LOGGER.error if lvl == 'error' else LOGGER.warning if lvl in ('warn', 'warning') else LOGGER.info)(redact(msg))


def read(tail=400_000):
    """The log (previous and current) for «Copiar log»."""
    out = ''
    for p in ([PATH[0] + '.1', PATH[0]] if PATH[0] else []):
        if os.path.exists(p):
            with open(p, encoding='utf-8', errors='replace') as f:
                out += f.read()
    return out[-tail:]


if __name__ == '__main__':          # quick test: python diag_log.py <carpeta>
    import tempfile
    d = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
    start(d, {'version': 'test', 'api_key': 'sk-abcdefghijkl'})
    request('POST', '/api/save', 200, time.time(), {'geom': {'type': 'Polygon', 'coordinates': [[0, 0]]}, 'regions': list(range(50)),
                                                     'name': 'Taurida', 'key': 'secret1'}, error=['x failed'])
    client([{'page': 'map', 'level': 'error', 'msg': 'TypeError token=abc123', 'action': 'cut'}])
    try:
        1 / 0
    except ZeroDivisionError:
        traceback.print_exc()
    txt = read()
    assert 'sk-abc' not in txt and 'secret1' not in txt and 'abc123' not in txt and 'ZeroDivisionError' in txt and '[50]' in txt, txt
    set_enabled(False); LOGGER.info('HIDDEN'); assert 'HIDDEN' not in read() and not enabled()
    set_enabled(True); assert enabled() and not os.path.exists(PATH[0] + '.off')
    print('ok', PATH[0])
