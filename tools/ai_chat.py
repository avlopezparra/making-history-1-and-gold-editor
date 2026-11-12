"""AI chat for the editors: providers (Anthropic, OpenAI, Gemini, OpenAI-compatible/Ollama, simulated),
local keys and the catalog of server routes the AI can use as tools.

Keys are stored in ~/.mheditor/ai.json (outside the project, the scenarios and the GitHub export).
The browser never receives the keys: only «configured yes/no».
"""
import json
import os
import re
import shutil
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(os.path.expanduser('~'), '.mheditor', 'ai.json')

PROVIDERS = {
    'anthropic': {'label': 'Anthropic Claude', 'model': 'claude-opus-5-5', 'base': 'https://api.anthropic.com'},
    'openai': {'label': 'OpenAI', 'model': 'gpt-5', 'base': 'https://api.openai.com/v1'},
    'gemini': {'label': 'Google Gemini', 'model': 'gemini-3.1-pro-preview', 'base': 'https://generativelanguage.googleapis.com/v1beta'},
    'compat': {'label': 'API personalizada (compatible con OpenAI: URL + clave)', 'model': 'llama3.1', 'base': 'http://localhost:11434/v1', 'keyless': True},
    # same messages as OpenAI (chat/completions + /models); several have a free plan
    'openrouter': {'label': 'OpenRouter', 'model': 'openrouter/auto', 'base': 'https://openrouter.ai/api/v1'},
    'groq': {'label': 'Groq', 'model': 'openai/gpt-oss-120b', 'base': 'https://api.groq.com/openai/v1'},
    'deepseek': {'label': 'DeepSeek', 'model': 'deepseek-chat', 'base': 'https://api.deepseek.com/v1'},
    'mistral': {'label': 'Mistral', 'model': 'mistral-large-latest', 'base': 'https://api.mistral.ai/v1'},
    'cerebras': {'label': 'Cerebras', 'model': 'llama-3.3-70b', 'base': 'https://api.cerebras.ai/v1'},
    'together': {'label': 'Together AI', 'model': 'meta-llama/Llama-3.3-70B-Instruct-Turbo', 'base': 'https://api.together.xyz/v1'},
    # empty model: the newest one the API offers is picked automatically (remember_best)
    'kimi': {'label': 'Kimi (Moonshot)', 'model': '', 'base': 'https://api.moonshot.ai/v1'},
    'glm': {'label': 'GLM (Z.ai / Zhipu)', 'model': '', 'base': 'https://api.z.ai/api/paas/v4'},
    'qwen': {'label': 'Qwen (Alibaba Cloud)', 'model': '', 'base': 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'},
    # GigaChat (Sber, the one behind GigaCode): authorization key → 30-min OAuth token; tools in the old «functions» format
    'qwen-coder': {'label': 'Qwen3-Coder (Alibaba Cloud)', 'model': 'qwen3-coder-plus', 'base': 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'},
    'gigachat': {'label': 'GigaChat (Sber)', 'model': 'GigaChat-2-Max', 'base': 'https://gigachat.devices.sberbank.ru/api/v1', 'auth': 'gigachat', 'legacy_fn': True},
    # Yandex Cloud AI Studio (YandexGPT, Qwen…): modelo «gpt://<id de carpeta>/yandexgpt/latest», clave «Api-Key»
    'yandex': {'label': 'Yandex Cloud (YandexGPT)', 'model': 'gpt://FOLDER_ID/yandexgpt/latest', 'base': 'https://llm.api.cloud.yandex.net/v1', 'auth': 'api-key'},
    'nvidia': {'label': 'NVIDIA NIM', 'model': 'meta/llama-3.3-70b-instruct', 'base': 'https://integrate.api.nvidia.com/v1'},
    'huggingface': {'label': 'Hugging Face', 'model': '', 'base': 'https://router.huggingface.co/v1'},
    'omniroute': {'label': 'OmniRoute (local)', 'model': 'auto', 'base': 'http://localhost:20128/v1', 'keyless': True},
    'lmstudio': {'label': 'LM Studio (local)', 'model': '', 'base': 'http://localhost:1234/v1', 'keyless': True},
    'mock': {'label': 'Simulado (pruebas)', 'model': 'mock', 'base': ''},
}

# routes the AI never calls: they write to the game (Guardar/Instalar are pressed by the user) or delete/revert
BLOCKED = re.compile(r'^/api/(install|install_tiles|undo|redo|refresh|lang|anthems/install|game/|pack/select|'
                     r'scen/(revert|discard_all|reload|delete|open_folder|fix_icons)|save/create|gamelog/|ai/)')
# routes that write to disk (user Save, new scenarios): flagged in red and backed up first
DISK = re.compile(r'^/api/(save$|scen/(save|new_from|new_scratch|model_import|model_texture|model_save_links)|pack/(new|copy)$|anthems/import|minimap/import|terrain/import|img/.*/write)')


def load():
    try:
        return json.load(open(CONF, encoding='utf-8'))
    except Exception:
        return {'active': 'anthropic', 'providers': {}}


# providers that work from Russia and Belarus (Western ones block those regions)
RU_OK = {'gigachat', 'yandex', 'openrouter', 'groq', 'cerebras', 'mistral', 'deepseek', 'qwen', 'qwen-coder', 'kimi', 'glm', 'compat', 'omniroute', 'lmstudio', 'mock'}
# mainland China: only Chinese and local providers, with their China endpoints
CN_OK = {'deepseek', 'qwen', 'qwen-coder', 'kimi', 'glm', 'compat', 'omniroute', 'lmstudio', 'mock'}
CN_BASE = {'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-coder': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
           'kimi': 'https://api.moonshot.cn/v1', 'glm': 'https://open.bigmodel.cn/api/paas/v4'}
REGION = {'RU': (RU_OK, 'gigachat'), 'BY': (RU_OK, 'gigachat'), 'CN': (CN_OK, 'deepseek')}


def pdef(k):
    """Provider defaults, with the China endpoint if the machine is in mainland China."""
    d = PROVIDERS[k]
    return dict(d, base=CN_BASE[k]) if k in CN_BASE and country() == 'CN' else d


def country():
    """Country of the Windows regional settings (2-letter ISO), without querying any external service."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(8)
        if ctypes.windll.kernel32.GetUserDefaultGeoName(buf, 8):
            return buf.value.upper()
    except Exception:
        pass
    import locale
    loc = (locale.getlocale()[0] or '')
    return loc.split('_')[-1][:2].upper() if '_' in loc else ''


def public():
    c = load()
    out = {}
    ok, first = REGION.get(country(), (None, None))
    for k in PROVIDERS:
        if ok and k not in ok:
            continue
        d = pdef(k)
        p = c['providers'].get(k, {})
        out[k] = {'label': d['label'], 'model': p.get('model') or d['model'], 'base': p.get('base') or d['base'],
                  'has_key': bool(p.get('key')) or k == 'mock' or bool(d.get('keyless'))}
    act = c.get('active') if c.get('active') in out else (first or next(iter(out)))
    return {'active': act, 'providers': out, 'file': CONF, 'fallback': c.get('fallback') or []}


def save(p):
    c = load()
    if p.get('active') in PROVIDERS:
        c['active'] = p['active']
    if isinstance(p.get('fallback'), list):       # fallback providers, in order (like OmniRoute «combos»)
        c['fallback'] = [k for k in p['fallback'] if k in PROVIDERS and k != 'mock']
    for k, v in (p.get('providers') or {}).items():
        if k not in PROVIDERS:
            continue
        cur = c['providers'].setdefault(k, {})
        for f in ('model', 'base'):
            if v.get(f) is not None:
                cur[f] = v[f].strip()
        if v.get('key'):                  # empty = leave the stored key alone
            cur['key'] = v['key'].strip()
        if v.get('clear_key'):
            cur.pop('key', None)
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    json.dump(c, open(CONF, 'w', encoding='utf-8'), indent=1)
    return public()


# ---------- catalog of server routes (so the AI knows what exists) ----------

def _routes():
    src = open(os.path.join(HERE, 'editor_server.py'), encoding='utf-8').read().split('\n')
    out, method = [], 'GET'
    for i, ln in enumerate(src):
        if 'def _post' in ln or 'def scen_post' in ln:
            method = 'POST'
        elif 'def do_GET' in ln or 'def scen_get' in ln or re.match(r'def \w+_get\(', ln):
            method = 'GET'
        elif re.match(r'def \w+_post\(', ln):
            method = 'POST'
        for m in re.finditer(r"path == '(/api/[^']+)'", ln):
            note = ''
            for j in (i - 1, i + 1):
                s = src[j].strip() if 0 <= j < len(src) else ''
                if s.startswith('#'):
                    note = s.lstrip('# ')[:140]
                    break
            if '#' in ln and not note:
                note = ln.split('#', 1)[1].strip()[:140]
            out.append({'method': method, 'path': m.group(1), 'line': i + 1, 'note': note})
    return out, src


def routes(filt=''):
    rs, _ = _routes()
    f = filt.lower()
    seen, out = set(), []
    for r in rs:
        k = (r['method'], r['path'])
        if k in seen or BLOCKED.match(r['path']) or (f and f not in r['path'] and f not in r['note'].lower()):
            continue
        seen.add(k)
        out.append('%s %s%s%s' % (r['method'], r['path'], ' [ESCRIBE EN DISCO]' if DISK.match(r['path']) else '',
                                  ' — ' + r['note'] if r['note'] else ''))
    return '\n'.join(out)


def route_source(path, method=''):
    rs, src = _routes()
    hits = [r for r in rs if r['path'] == path and (not method or r['method'] == method.upper())]
    if not hits:
        return 'ruta desconocida: ' + path
    parts = []
    for r in hits[:3]:
        i, end = r['line'] - 1, min(len(src), r['line'] + 40)
        ind = len(src[i]) - len(src[i].lstrip())
        j = i + 1
        while j < end and not (src[j].strip() and len(src[j]) - len(src[j].lstrip()) <= ind):
            j += 1
        parts.append('# %s %s (editor_server.py:%d)\n%s' % (r['method'], path, r['line'], '\n'.join(src[i:j])))
    return '\n\n'.join(parts)


def check_call(method, path):
    if not path.startswith('/api/'):
        return 'solo rutas /api/'
    if BLOCKED.match(path):
        return 'ruta bloqueada para la IA (Guardar/Instalar/borrar los hace el usuario): ' + path
    return None


def backup_scenario(scen_root, backup_root, name):
    """Copies the scenario folder before the AI's first write (once per chat session)."""
    src = os.path.join(scen_root, name)
    if not name or not os.path.isdir(src):
        return None
    dst = os.path.join(backup_root, 'ia', time.strftime('%Y%m%d-%H%M%S'), name)
    shutil.copytree(src, dst)
    return dst


def models(prov, key=None, base=None):
    """Models offered by the provider's API (with the key typed in the form or the stored one)."""
    c = load()
    p = dict(pdef(prov), **{k: v for k, v in c['providers'].get(prov, {}).items() if v})
    key, base = key or p.get('key'), (base or p['base']).rstrip('/')
    if prov == 'mock':
        return ['mock']
    def get(url, h):
        with urllib.request.urlopen(urllib.request.Request(url, headers=dict({'User-Agent': UA}, **h)), timeout=30) as r:
            return json.loads(r.read().decode('utf-8'))
    try:
        if prov == 'anthropic':
            d = get(base + '/v1/models?limit=100', {'x-api-key': key or '', 'anthropic-version': '2023-06-01'})
            return [m['id'] for m in d.get('data', [])]
        if prov == 'gemini':
            out, tok = [], ''
            for _ in range(10):
                d = get('%s/models?pageSize=1000&key=%s%s' % (base, key or '', '&pageToken=' + tok if tok else ''), {})
                out += [m['name'].split('/', 1)[-1] for m in d.get('models', [])
                        if 'generateContent' in (m.get('supportedGenerationMethods') or [])]
                tok = d.get('nextPageToken')
                if not tok:
                    break
            return out
        d = get(base + '/models', _auth(dict(p, key=key)))
        return sorted(m['id'] for m in d.get('data', []))
    except urllib.error.HTTPError as e:
        raise RuntimeError('HTTP %d: %s' % (e.code, e.read().decode('utf-8', 'replace')[:300]))


# ---------- proveedores ----------
# mensajes neutros: {'role':'user'|'assistant', 'text':..., 'calls':[{id,name,args}], 'results':[{id,name,content}]}

def _http(url, body, headers, timeout=180):
    data = json.dumps(body).encode('utf-8')
    for attempt in range(4):
        req = urllib.request.Request(url, data, dict({'Content-Type': 'application/json', 'User-Agent': UA}, **headers))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            msg = e.read().decode('utf-8', 'replace')
            # per-minute limit (free plans): wait as long as the API asks and retry; the daily limit is not retried
            w = re.search(r'retry in ([\d.]+)s|"retryDelay": "(\d+)s"', msg)
            wait = float(w.group(1) or w.group(2)) if w else float(e.headers.get('retry-after') or 0)
            if not wait and e.code in (503, 529):     # saturado: reintentar al poco
                wait = 5 * (attempt + 1)
            if e.code in (429, 529, 503) and attempt < 3 and 0 < wait <= 70 and 'per day' not in msg.lower():
                time.sleep(wait + 1)
                continue
            raise RuntimeError('HTTP %d: %s' % (e.code, msg[:600]))


UA = 'MHEditor/3.1 (+https://github.com/)'   # Cloudflare (Groq…) rechaza «Python-urllib»: «error code: 1010»
COOLDOWN = {}      # provider -> time until which it is not used (quota exhausted, bad key, down)


SKIP_MODEL = re.compile(r'whisper|tts|audio|speech|transcri|embed|guard|safeguard|moderation|orpheus|image|imagen|vision-only|'
                        r'realtime|dall-e|sora|veo|lyria|search|computer-use|aqa|learnlm|gemma|allam|robotics|banana|omni|antigravity|babbage|davinci|instruct|-exp|live', re.I)


def best_model(prov, ms):
    """The newest chat model: highest version and, at equal version, the high tier (pro/opus) before the light one."""
    ms = [m for m in ms if not SKIP_MODEL.search(m)]
    if not ms:
        return None
    if prov == 'anthropic':        # the Anthropic API already returns them newest to oldest
        top = [m for m in ms if 'opus' in m] or ms
        return top[0]
    fam = {'gemini': 'gemini', 'openai': 'gpt', 'mistral': 'mistral'}.get(prov)
    if fam:
        ms = [m for m in ms if fam in m] or ms

    def key(m):
        n = m.split('/')[-1]
        n = re.sub(r'\d{2,4}-\d{2}(-\d{2})?|\d{4,}', '', n)          # fechas (09-2026, 2025-04-14) no son versiones
        n = re.sub(r'\d+(\.\d+)?b\b', '', n)                          # sizes (70b, 120b)
        ver = tuple(float(x) for x in re.findall(r'\d+(?:\.\d+)?', n)[:1]) or (0,)
        tier = 3 if re.search(r'opus|pro\b|-pro|large|120b|405b|max', m) else \
            0 if re.search(r'mini|nano|lite|small|tiny|haiku|\b\d{1,2}b\b', m) else 2
        # code names (gemini-4-argon) are usually tests: known tiers first
        std = bool(re.search(r'pro|flash|opus|sonnet|haiku|large|medium|small|mini|nano|lite|chat|gpt-\d|oss|llama|qwen|deepseek|mistral', m.replace('gemini', '')))   # «gemini» contiene «mini»
        return (std, ver[0], tier, 'preview' not in m and 'latest' not in m, -len(m))
    return max(ms, key=key)


def remember_best(prov):
    """Looks up the newest model in the API and stores it as that provider's model."""
    try:
        m = best_model(prov, models(prov))
    except Exception:
        return None
    if m:
        c = load()
        c['providers'].setdefault(prov, {})['model'] = m
        os.makedirs(os.path.dirname(CONF), exist_ok=True)
        json.dump(c, open(CONF, 'w', encoding='utf-8'), indent=1)
    return m


def chat(system, messages, tools):
    """Calls the active provider; if it fails (quota, key, outage), tries the fallbacks in order."""
    c = load()
    order = [c.get('active') or 'anthropic'] + [k for k in c.get('fallback') or [] if k != c.get('active')]
    ok, first = REGION.get(country(), (None, None))
    if ok:      # same providers as shown (public)
        order = [k for k in order if k in ok] or [first]
    errors, now = [], time.time()
    for i, prov in enumerate(order):
        p = dict(pdef(prov), **{k: v for k, v in c['providers'].get(prov, {}).items() if v})
        if prov != 'mock' and not p.get('keyless') and not p.get('key'):
            errors.append('%s: falta la clave (⚙)' % p['label'])
            continue
        if i > 0 and COOLDOWN.get(prov, 0) > now:      # the chosen one is always tried; paused fallbacks are skipped
            errors.append('%s: en pausa %ds' % (p['label'], COOLDOWN[prov] - now))
            continue
        fn = {'anthropic': _anthropic, 'gemini': _gemini, 'mock': _mock}.get(prov, _openai)
        try:
            if not p.get('model'):
                p['model'] = remember_best(prov)
            try:
                try:
                    r = fn(p, system, messages, tools)
                except RuntimeError as e:     # the model wrote the tool call wrong: a second attempt usually works
                    if 'tool_use_failed' not in str(e) and 'MALFORMED_FUNCTION_CALL' not in str(e):
                        raise
                    r = fn(p, system, messages, tools)
            except RuntimeError as e:
                # the stored model no longer exists (retired): the newest one the API offers is picked and retried
                if not re.search(r'HTTP 404|model_not_found|not found|no longer available|does not exist', str(e), re.I):
                    raise
                new = remember_best(prov)
                if not new or new == p['model']:
                    raise
                errors.append('%s: «%s» ya no existe, uso «%s»' % (p['label'], p['model'], new))
                p['model'] = new
                r = fn(p, system, messages, tools)
        except Exception as e:
            m = str(e)
            # bad key: long pause; quota, overload or local server off: short pause
            COOLDOWN[prov] = now + (600 if re.search(r'HTTP 40[13]', m) else 60)
            errors.append('%s: %s' % (p['label'], m[:300]))
            continue
        r['provider'], r['model'] = prov, p['model']
        if errors:
            r['notes'] = errors
        return r
    raise RuntimeError(' | '.join(errors) or 'sin proveedor')


def _anthropic(p, system, msgs, tools):
    out = []
    for m in msgs:
        if m['role'] == 'user' and m.get('results'):
            out.append({'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': r['id'], 'content': r['content']} for r in m['results']]
                        + ([{'type': 'text', 'text': m['text']}] if m.get('text') else [])})
        elif m['role'] == 'user':
            out.append({'role': 'user', 'content': m['text']})
        else:
            c = ([{'type': 'text', 'text': m['text']}] if m.get('text') else []) + \
                [{'type': 'tool_use', 'id': k['id'], 'name': k['name'], 'input': k['args']} for k in m.get('calls') or []]
            out.append({'role': 'assistant', 'content': c or [{'type': 'text', 'text': '…'}]})
    body = {'model': p['model'], 'max_tokens': 8000, 'system': system, 'messages': out,
            'tools': [{'name': t['name'], 'description': t['description'], 'input_schema': t['parameters']} for t in tools]}
    d = _http(p['base'].rstrip('/') + '/v1/messages', body, {'x-api-key': p['key'], 'anthropic-version': '2023-06-01'})
    return {'text': ''.join(b.get('text', '') for b in d['content'] if b['type'] == 'text'),
            'calls': [{'id': b['id'], 'name': b['name'], 'args': b['input']} for b in d['content'] if b['type'] == 'tool_use']}


GIGA_TOKEN = {}


def _auth(p):
    """Authentication header per provider (Bearer almost always)."""
    key = p.get('key')
    if not key:
        return {}
    if p.get('auth') == 'api-key':
        return {'Authorization': 'Api-Key ' + key}
    if p.get('auth') == 'gigachat':
        t = GIGA_TOKEN.get(key)
        if not t or t[1] < time.time() + 60:
            import uuid
            req = urllib.request.Request('https://ngw.devices.sberbank.ru:9443/api/v2/oauth', b'scope=GIGACHAT_API_PERS',
                                         {'Authorization': 'Basic ' + key, 'RqUID': str(uuid.uuid4()), 'User-Agent': UA,
                                          'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode('utf-8'))
            t = GIGA_TOKEN[key] = (d['access_token'], d['expires_at'] / 1000)
        return {'Authorization': 'Bearer ' + t[0]}
    return {'Authorization': 'Bearer ' + key}


def _openai(p, system, msgs, tools):
    out = [{'role': 'system', 'content': system}]
    for m in msgs:
        if m['role'] == 'user' and m.get('results'):
            if p.get('legacy_fn'):
                out += [{'role': 'function', 'name': r['name'], 'content': json.dumps({'result': r['content']}, ensure_ascii=False)} for r in m['results']]
            else:
                out += [{'role': 'tool', 'tool_call_id': r['id'], 'content': r['content']} for r in m['results']]
            if m.get('text'):
                out.append({'role': 'user', 'content': m['text']})
        elif m['role'] == 'user':
            out.append({'role': 'user', 'content': m['text']})
        else:
            a = {'role': 'assistant', 'content': m.get('text') or ''}
            if m.get('calls') and p.get('legacy_fn'):
                a['function_call'] = {'name': m['calls'][0]['name'], 'arguments': m['calls'][0]['args']}
            elif m.get('calls'):
                a['tool_calls'] = [{'id': k['id'], 'type': 'function', 'function': {'name': k['name'], 'arguments': json.dumps(k['args'])}} for k in m['calls']]
            out.append(a)
    body = {'model': p['model'], 'messages': out}
    if p.get('legacy_fn'):
        body['functions'] = tools
    else:
        body['tools'] = [{'type': 'function', 'function': t} for t in tools]
    d = _http(p['base'].rstrip('/') + '/chat/completions', body, _auth(p))
    msg = d['choices'][0]['message']
    calls = []
    fc = msg.get('function_call')      # old format: one call per response, arguments already as an object
    if fc:
        a = fc.get('arguments') or {}
        calls.append({'id': 'f%d' % len(msgs), 'name': fc['name'], 'args': json.loads(a) if isinstance(a, str) else a})
    for k in msg.get('tool_calls') or []:
        try:
            a = json.loads(k['function'].get('arguments') or '{}')
        except ValueError:
            a = {}
        calls.append({'id': k['id'], 'name': k['function']['name'], 'args': a})
    return {'text': msg.get('content') or '', 'calls': calls}


def _gemini(p, system, msgs, tools):
    out = []
    for m in msgs:
        if m['role'] == 'user' and m.get('results'):
            out.append({'role': 'user', 'parts': [{'functionResponse': {'name': r['name'], 'response': {'content': r['content']}}} for r in m['results']]
                        + ([{'text': m['text']}] if m.get('text') else [])})
        elif m['role'] == 'user':
            out.append({'role': 'user', 'parts': [{'text': m['text']}]})
        else:
            # Gemini 3 requires returning its parts as-is (thoughtSignature) in tool calls
            parts = m.get('raw') or ([{'text': m['text']}] if m.get('text') else []) + [{'functionCall': {'name': k['name'], 'args': k['args']}, 'thoughtSignature': 'skip_thought_signature_validator'} for k in m.get('calls') or []]
            out.append({'role': 'model', 'parts': parts or [{'text': '…'}]})
    body = {'systemInstruction': {'parts': [{'text': system}]}, 'contents': out,
            'tools': [{'functionDeclarations': tools}]}
    d = _http('%s/models/%s:generateContent?key=%s' % (p['base'].rstrip('/'), p['model'], p['key']), body, {})
    parts = d['candidates'][0]['content'].get('parts', [])
    return {'text': ''.join(x.get('text', '') for x in parts if not x.get('thought')), 'raw': parts,
            'calls': [{'id': 'g%d' % i, 'name': x['functionCall']['name'], 'args': x['functionCall'].get('args') or {}}
                      for i, x in enumerate(parts) if 'functionCall' in x]}


def _mock(p, system, msgs, tools):
    """Simulated provider: one lookup and a harmless plan (check the nations of the open scenario)."""
    last = msgs[-1]
    n = sum(1 for m in msgs if m.get('results'))
    if last['role'] == 'user' and not last.get('results'):
        return {'text': '(simulado) Miro los países.', 'calls': [{'id': 'm1', 'name': 'lookup', 'args': {'what': 'countries'}}]}
    if n == 1:
        sc = (re.search(r'"scenario": ?"([^"]+)"', system) or [None, ''])[1]
        return {'text': '', 'calls': [{'id': 'm2', 'name': 'propose_plan', 'args': {'summary': '(simulado) comprobar naciones', 'steps': [
            {'action': 'api_call', 'args': {'path': '/api/scen/check_nations', 'body': {'name': sc}}, 'why': 'prueba sin cambios'}]}}]}
    return {'text': '(simulado) Recibidos %d resultados.' % n, 'calls': []}
