"""Single-player diplomatic chat with the CPU nations of Making History I / Gold, answered by an LLM.

With the chat UI mod (sp_chat_mod.py) the player opens a chat in a single-player game and writes; this program,
attached to the running game (game_cli.GameCLI: the game's own CLI, run on its main thread), reads the chats, sends
one LLM request per new message (ai_chat.chat, the editor's provider settings and keys in ~/.mheditor/ai.json) and
writes the answers as the CPU nations. What the leaders agree to is done by local code, through each nation's own
avatar (mh_console.Console.enable_dispatch with an avatar id): the CPU nation proposes the treaty (the player gets
the game's usual proposal), declares war, or improves / worsens relations. The CPU AI keeps running the nations;
the LLM only talks and makes these few deliberate moves.

A nation joins a chat when the player calls it with '@' ('@Francia ...', '@France ...'); every CPU nation in the chat may
answer. No second license: everything happens inside the player's own game process. In a multiplayer game it works
only on the host (the CPU avatars live there): every human's chats are read, each author is answered as themselves,
and the control commands (/order, /yesman, /relations, /ideology) obey only the host.

    python tools/sp_chat.py [--config FILE]        (settings: ~/.mheditor/sp_chat.json, created on first run)

It can start before the game: it waits for makehist.exe and for a game in progress, and goes back to waiting
when the player leaves that game or closes Making History.
"""
import argparse
import collections
import itertools
import collections.abc
import ctypes
import datetime
import json
import queue
import threading
import locale
import os
import re
import sys
import time
import types
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gamepaths                     # noqa: E402
import ai_player                     # noqa: E402
import dead_keys                     # noqa: E402
from ai_player import Bot, _res      # noqa: E402
from game_cli import GameCLI, find_pid   # noqa: E402
import game_cli                      # noqa: E402
from mh_console import Console       # noqa: E402

DEFAULTS = {
    'language': '',                  # '' = the language of Windows on this computer
    'poll_seconds': 1.5,
    'history_lines': 2,              # chat lines sent to the LLM (per-nation memory keeps the rest)
    'fantasy_scenarios': ['Tamriel'],   # scenario name fragments with no real-world history (no real dates)
    'tag': 'CPU',                    # chat lines read 'France(CPU):...'
    'turn_limits': {'alliance': 1, 'territory': 2, 'relations': 3, 'troops': 2, 'war': 1},   # per game turn
    'event_actions': True,           # the actions real scenario events use (ActTransferRegionOwnership,
                                     # ActFormMilitaryAccess, ActFormSeparatePeaceConcessions, ActIncResourceStock,
                                     # ActGrantIndependence): what the chat agreed is applied, no proposal to veto
    'force_actions': False,          # True: developer / event actions apply what the chat agreed at once
                                     # (ActDevFormDefensePact, ActDevMakePeace, ActTransferRegionOwnership,
                                     # ActGrantIndependence); off: the game's normal proposals. The turn-44
                                     # collapse came after three forced alliances: off until proven safe.
    'autonomous': False,             # True: per-turn moves nobody asked for in the chat (demand checks,
                                     # redeployments, unprompted messages, news, popups); off: only what the chat asks
}
CONFIG = os.path.join(os.path.expanduser('~'), '.mheditor', 'sp_chat.json')
LOGS = os.path.join(gamepaths.ROOT, 'logs')
GAME_LOG_LINE = re.compile(r'^[A-Za-z_]\w*::\w+')     # 'CMapObjectSprite::GetToolTipText error - ...'
LINE = re.compile(r'([^():\n]+)\(([^)\n]*)\):(.*)')


def norm(s):
    """'Francia' / 'Turquía' -> 'francia' / 'turquia' (the keys of Bot.ALIASES)."""
    return ''.join(ch for ch in unicodedata.normalize('NFKD', s.lower()) if ord(ch) < 128).strip()


assert norm('Turquía ') == 'turquia'


def windows_language():
    """('es', 'español') for the Windows display language of this computer."""
    lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    code = (locale.windows_locale.get(lcid) or 'en_US').split('_')[0]
    names = {'es': 'español', 'en': 'English', 'pt': 'português', 'fr': 'français', 'de': 'Deutsch',
             'it': 'italiano', 'ru': 'русский', 'ja': '日本語', 'zh': '中文', 'pl': 'polski', 'tr': 'Türkçe'}
    return code, names.get(code, code)


UNIT_READS = 40     # game reads one /troops move may spend looking for armies


class GameSlow(BaseException):
    """The game took too long to answer our commands: SP Chat lets go of it (main() waits and reconnects).
    Not an Exception, so no 'except Exception' on the way swallows it; once raised, no command is sent again on
    that connection (watch_gave_up)."""


SLOW_SECONDS, SLOW_RUN = 30, (4, 10)    # one command over 30 s, or 4 in a row over 10 s, outside end of turn
# (8 s / 3 s disconnected every minute in a 250-nation MH1 game with the window in the background)
GAME_ERROR = re.compile(r'error validating|NULL alliance|unable to find war|Failed to|assert|invalid', re.I)
HARMLESS = re.compile(r'HitPoints|GetToolTipText|animation|texture|factory output|ValidActionForMode|Unknown property|display frame strings|CmdSetProperty|INVALID DATE', re.I)      # ValidAction../Unknown property: send_action rebuilds the action; display frame strings: the popup still shows; CmdSetProperty: one value not applied
OUR_TEXT = re.compile(r'^>?\s*(set property|Set property)|strNewValue|^[^():]+\([^)]*\):')      # our own lines
NEVER_DISABLED = ('ActAlterPropertyImmed',)      # our chat lines: an error is logged, the chat keeps working


def game_errors(out):
    """The lines of a command's output that report a game error (known harmless ones left out)."""
    return [l.strip() for l in (out or '').splitlines()
            if GAME_ERROR.search(l) and not HARMLESS.search(l) and not OUR_TEXT.search(l.strip())]


assert game_errors('ok' + chr(10) + 'CTreatyDefPeace::GetWar unable to find war -1' + chr(10) +
                   'GetToolTipText error ... Army') == ['CTreatyDefPeace::GetWar unable to find war -1']
assert game_errors('Failed to load texture in file flag.tga') == []
assert game_errors('Chat(CPU):I disabled ActIncDipRelations: the game threw an error (invalid action)') == []
assert game_errors('Set property "strNewValue" of object 5 to "error validating"') == []
assert game_errors('CAvatar::ValidActionForMode - invalid action at 3F5E0DC8 passed to Avatar 91') == []


def watch(cli, line, out, took):
    """After every game command: errors in its output within 10 s of one of our actions are pinned on that
    action type (send_action then disables it for the session); slow answers outside end of turn raise
    GameSlow."""
    last = cli.__dict__.get('last_action')
    errs = game_errors(out)
    if errs and last and time.time() - last[1] < 10:
        cli.__dict__.setdefault('error_hits', []).append((last[0], errs[0][:160]))
    if 'bEOTOrAIProcessing' in line or 'bEndOfTurnProcessing' in line:
        return      # the end of turn may hold frames back: never counted
    cli.slow_run = cli.__dict__.get('slow_run', 0) + 1 if took > SLOW_RUN[1] else 0
    if took > SLOW_SECONDS or cli.slow_run >= SLOW_RUN[0]:
        cli.slow_run = 0
        cli.gave_up = 'el juego tardó %.0f s en responder' % took
        raise GameSlow('el juego tardó %.0f s en responder a %s' % (took, line.split(' ')[0] if line else '?'))


_p = type('C', (), {})()
_p.last_action = ('ActFormSeparatePeaceConcessions', time.time())
watch(_p, 'dump property 1 x', 'CTreatyDefPeace::GetWar unable to find war -1', 0.1)
assert _p.error_hits == [('ActFormSeparatePeaceConcessions', 'CTreatyDefPeace::GetWar unable to find war -1')]
try:
    watch(_p, 'dump property 1 x', '', SLOW_SECONDS + 1)
    raise AssertionError('no GameSlow')
except GameSlow:
    assert _p.gave_up
    del _p.gave_up
watch(_p, 'dump property 1 bEOTOrAIProcessing', '', 60)      # end of turn: never slow
for _ in range(SLOW_RUN[0] - 1):
    watch(_p, 'dump property 1 x', '', SLOW_RUN[1] + 1)
try:
    watch(_p, 'dump property 1 x', '', SLOW_RUN[1] + 1)
    raise AssertionError('no GameSlow on 3 slow in a row')
except GameSlow:
    pass


class Refused(RuntimeError):
    """An offer the game would show broken or reject (reported in the chat, never sent)."""


NotOwner = Refused       # a territory deal with a region its side doesn't own
TREATY_KINDS = ('alianza', 'no_agresion', 'acceso_militar', 'paz', 'comercio', 'ayuda', 'territorio')


class Players(collections.abc.Mapping):
    """{nation name: Player id}. Names come from the scenario's player<Country>.xml files (no game reads); each
    Player object is found on first use with small 'dump property strName' reads, only as many as needed (reading
    all ~250 Players at once froze the game for minutes)."""

    def __init__(self, bot):
        self.bot, self.found, self.todo = bot, {}, None
        bot.country_name('')                 # fills bot._nations from the scenario files
        self.names = set(bot._nations) | {getattr(bot, 'host', None)} - {None}
        if not bot._nations:                  # no scenario files: every Player now (the old, slow way)
            while self._next():
                pass
            self.names = set(self.found)

    def _next(self):
        if self.todo is None:
            gs = self.bot.gs()
            self.todo = self.bot.refs(gs, 'objPlayers')
        if not self.todo:
            return False
        p = self.todo.pop(0)
        self.found[self.bot.prop(p, 'strName')] = p
        return True

    def __getitem__(self, name):
        while name in self.names and name not in self.found:
            if not self._next():
                break
        return self.found[name]          # KeyError: not in this game (.get() gives the default)

    def __iter__(self):
        return iter(self.names)

    def __len__(self):
        return len(self.names)

    def __contains__(self, name):
        return name in self.names


class SPBot(Bot):
    """ai_player.Bot reading and acting through GameCLI in the player's own game. 'self.acting' = the CPU nation
    whose avatar sends the next actions (Bot.propose / improve_relations then work for that nation)."""

    def __init__(self, cfg, log, cli, root):
        self.cfg, self.log, self.con, self.root = cfg, log, cli, root
        self.acting = None
        self.yesman = bool(cfg.get('yesman'))
        # the game process's one Driver: found once per connection (a scan of every object, slow), kept on the cli
        # ... and remembered on disk for this game process, so a restart doesn't freeze the game again with that
        # huge 'show object 0'
        if getattr(cli, 'driver', None) is None:
            memo = os.path.join(LOGS, 'sp_chat_driver.json')
            try:
                with open(memo, encoding='utf-8') as f:
                    m = json.load(f)
                if m.get('pid') == cli.pid and self.prop(m['driver'], 'objMyAvatar') is not None:
                    cli.driver = m['driver']
            except (OSError, ValueError, KeyError):
                pass
        if getattr(cli, 'driver', None) is None:
            cli.driver = next(o for o in self.show(0)[1].get('objAllObjects', []) if self.show(o)[0].get('__type') == 'Driver')
            with open(os.path.join(LOGS, 'sp_chat_driver.json'), 'w', encoding='utf-8') as f:
                json.dump({'pid': cli.pid, 'driver': cli.driver}, f)
        self.driver = cli.driver
        if not hasattr(cli, 'count'):      # every game command counted (run() logs the rate); cli.pace > 0 spaces
            raw, cli.count, cli.pace = cli.cmd, 0, 0      # them out so the game keeps drawing (background work)
            cli.raw_cmd = raw          # unwatched: the probe after an emergency stop

            def cmd(*a, **k):
                cli.count += 1
                if cli.pace:
                    time.sleep(cli.pace)
                elif cli.__dict__.get('burst_from') is not None and cli.count - cli.burst_from > BURST_FREE:
                    time.sleep(BURST_PACE)      # past the message's budget: spread the rest out
                if cli.__dict__.get('gave_up'):      # after an emergency stop: nothing more to this game
                    raise GameSlow(cli.gave_up)
                t0 = time.time()
                out = raw(*a, **k)
                watch(cli, a[0] if a else '', out, time.time() - t0)
                return out
            cli.cmd = cmd

    def player(self):
        """The acting CPU nation's Player while it acts (so Bot's research, production, troops... read its own
        data), otherwise the human's."""
        if self.acting:
            return self.nations().get(self.acting, -1)
        return self._me()

    def country_id(self, name=None):
        """nCountryID by name, read with small reads and kept (it never changes in a game); -1 if unknown."""
        name = self.country_name(name or self.cfg['country'])
        cache = self.__dict__.setdefault('_cid', {})
        if name not in cache:
            known = getattr(self, '_country_ids', None) or {}
            if name in known:
                return known[name]
            p = self.nations().get(name)
            c = self.obj_id(self.prop(p, 'objCountry') or '') if p else -1
            v = self.prop(c, 'nCountryID') if c > 0 else None
            if v is None or not v.lstrip('-').isdigit():
                return -1          # not cached: maybe not readable yet
            cache[name] = int(v)
        return cache[name]

    def region_id(self, name, country=None):
        """nRegionID by region name from the scenario's map (its index in regions.bin), with close matches: Bot's
        version reads the owner's Country objects, which we don't have for other nations. The game itself checks
        that the region belongs to whoever gives it."""
        import difflib
        names = self.land_map()[0]
        low = {(n or '').lower(): i for i, n in enumerate(names) if n}
        key = REGION_ALIASES.get(norm(name), name).strip().lower()
        m = [key] if key in low else difflib.get_close_matches(key, list(low), n=1, cutoff=0.7)
        if not m:
            raise RuntimeError('no conozco la región %s' % name)
        return low[m[0]]

    def avatar(self, country):
        """Object id of the avatar that plays 'country' (the CPU AI's own, in the game we host)."""
        cache = self.__dict__.setdefault('_avatars', {})
        if self.__dict__.get('_av_todo') is None:
            self._av_todo = self.refs(self.driver, 'objAvatars')
        while country not in cache and self._av_todo:      # small reads, only until found
            a = self._av_todo.pop(0)
            cache.setdefault(self.prop(a, 'strOwner'), a)
        return cache.get(country, -1)

    def prop(self, oid, name):
        """One property's value ('dump property': a small read; 'show object' prints the whole object)."""
        out, val = self.con.cmd('dump property %d %s' % (oid, name)), None
        for line in out.splitlines():
            m = ai_player.PROP.search(line)
            if m:
                val = m.group(1)[56:].strip() if m.group(1)[:23].strip() == name else val
            elif (val is not None and name == 'strBigChat' and line.strip() and not line.startswith(('LOG:', '>'))
                  and not GAME_LOG_LINE.match(line.strip())):
                # only the chat spans lines; the game's own log lines ('CMapObjectSprite::... error') interleave
                val += '\n' + line.strip()          # a value spanning several lines (the chat text)
        return val

    def cli(self, act, *args):
        if self.acting:          # the CPU nation's own action: built and sent through its avatar
            return self.send_action(act, dict(zip(args[::2], args[1::2])))
        return super().cli(act, *args)

    def send_action(self, def_name, values, children=()):
        """Builds the action in our PlayerData's action list (its namespace holds the scenario's actions; as host
        this is safe) and sends it through the acting nation's avatar, or ours."""
        self.wait_idle()
        self.check_errors()
        if def_name in self.__dict__.get('_disabled', {}):
            raise Refused('Desactivé %s en esta partida: el juego dio error (%s).' % (def_name, self._disabled[def_name]))
        if def_name == 'ActProposeDefensePact' and self.acting and                 str(self.country_id(values.get('strToCountry'))) in self.war_sides()[1]:
            # an alliance offered to a nation it is at war with left the game spinning at 100% CPU
            raise Refused('%s está en guerra con %s: primero la paz (/surrender %s %s o /peace).' % (
                self.acting, values.get('strToCountry'), self.acting, values.get('strToCountry')))
        self.turn_limit(def_name, values)
        self.forget(def_name)
        data = self._data()
        av = self.avatar(self.acting) if self.acting else -1
        if self.acting and av < 0:
            raise RuntimeError('no avatar plays %s' % self.acting)
        vals = dict(values, strPlayer=self.acting or self.cfg['country'])
        # The game runs a COPY of the action (log: object 9595 processed as action 429154), so one scratch object
        # per action type is reused within a message: only the changed values are set (2-3 commands instead of
        # 9-15). Actions with children (treaties with resources / regions) are built fresh each time.
        pool = self.__dict__.setdefault('_pool', {})
        entry = None if children else pool.get((data, def_name))
        if entry is None:
            listed = self.refs(data, 'objActions')
            self.con.cmd('create %d objActions %s' % (data, def_name))
            now = self.refs(data, 'objActions')
            new = [o for o in now if o not in listed]
            if not new:
                raise RuntimeError('could not create %s' % def_name)
            entry = [new[-1], now.index(new[-1]), {}]
            if not children:
                pool[(data, def_name)] = entry
        oid = entry[0]
        changed = {k: v for k, v in vals.items() if k not in entry[2] or entry[2][k] != v}
        if not self._set_checked(oid, changed) and not children:
            # the pooled object is gone (the game empties our action list when a turn ends; its id may now be
            # another object: 'Unknown property ... for object'): a fresh one, once
            return self._fresh_send(pool, data, def_name, values)
        entry[2].update(changed)
        for prop, child, cvals in children:
            c = self._new_child(oid, prop, child)
            if c < 0:
                raise RuntimeError('could not create %s' % child)
            self._set(c, cvals)
        self.con.__dict__['last_action'] = (def_name, time.time())
        out = self.con.cmd('action ActPauseGame %d%s' % (oid, ' %d' % av if av > 0 else ''))
        if self.check_errors(def_name):
            raise Refused('Desactivé %s en esta partida: el juego dio error (%s).' % (def_name, self._disabled[def_name]))
        if children:
            self.con.cmd('remove property %d objActions %d' % (data, entry[1]))     # our scratch copy
        elif 'non-existent' in (out or '') or 'invalid action' in (out or ''):
            return self._fresh_send(pool, data, def_name, values)      # rejected reused object: a fresh one
        self.log('sent', {'action': def_name, 'values': values, 'as': self.acting or self.cfg['country']})
        return out

    def check_errors(self, just_sent=None):
        """Game errors pinned on our action types (watch()): each such type is disabled for this game session,
        logged, and the player told in the chat (error_notes, written by run()). True if just_sent was."""
        hit = False
        for name, err in self.con.__dict__.pop('error_hits', []):
            self.log('game_error', {'action': name, 'error': err})
            if name in NEVER_DISABLED or name in self.__dict__.setdefault('_disabled', {}):
                continue
            self._disabled[name] = err
            self.__dict__.setdefault('error_notes', []).append(
                'Desactivé %s en esta partida: el juego dio error (%s).' % (name, err))
            hit = hit or name == just_sent
        return hit

    def turn_limit(self, def_name, values):
        """At most cfg['turn_limits'] game moves of each kind per game turn (per nation pair for relations,
        alliances and war): past it, Refused ('lo dejamos para el próximo turno')."""
        kind = LIMITED.get(def_name)
        if not kind:
            return
        limit = (self.cfg.get('turn_limits') or {}).get(kind, DEFAULTS['turn_limits'].get(kind))
        who = self.acting or self.cfg['country']
        pair = (values.get('nSourceCountryID'), values.get('nTargetCountryID')) if kind == 'relations' else \
            tuple(sorted((who, values.get('strToCountry') or ''))) if kind in ('alliance', 'war') else ()
        used = self.__dict__.setdefault('_turn_used', {})
        key = (self._turn, kind, pair)
        if used.get(key, 0) >= limit:
            raise Refused('Ya hubo %d %s este turno%s: lo dejamos para el próximo turno.' % (
                limit, LIMIT_ES[kind], ' entre esos países' if pair else ''))
        used[key] = used.get(key, 0) + 1

    def _set_checked(self, oid, values):
        """Bot._set, but False when the game says the object is not what we built ('Unknown property',
        'non-existent')."""
        for k, v in values.items():
            v = 'true' if v is True else 'false' if v is False else str(v)
            out = self.con.cmd('set property %d %s %s' % (oid, k, v if v and ' ' not in v else '"%s"' % v))
            if 'Unknown property' in (out or '') or 'non-existent' in (out or ''):
                return False
        return True

    def _fresh_send(self, pool, data, def_name, values):
        """The pooled object of this type was lost: forget it and send once more with a new object (a second
        failure is an error, never a session-long disable)."""
        pool.pop((data, def_name), None)
        if getattr(self, '_resend', False):
            raise RuntimeError('%s: the game rejected a fresh action object too' % def_name)
        self._resend = True
        try:
            return self.send_action(def_name, values)
        finally:
            self._resend = False

    def flush_actions(self):
        """Removes the reused scratch actions from our action list: each one only if it is still there, at its
        index as listed now (a turn end may have emptied the list), highest index first."""
        pool = self.__dict__.pop('_pool', {})
        for data in {d for d, _ in pool}:
            listed = self.refs(data, 'objActions')
            mine = sorted((listed.index(e[0]) for (d, _), e in pool.items() if d == data and e[0] in listed),
                          reverse=True)
            for idx in mine:
                self.con.cmd('remove property %d objActions %d' % (data, idx))

    def busy(self):
        """True while the turn is ending (the game crashed in objectcore CPropertyPath::Destroy when a CPU action
        was sent during end-of-turn processing)."""
        # small reads only: a 'show object' of GameState walks ~48 MB of objects inside one game frame
        # (run() reads the turn number itself; every action waits here, so two flags are enough)
        if time.time() - getattr(self, '_busy_t', 0) < 5:      # one answer sends several actions: one check
            return self._busy
        self._busy = any(self.prop(self.gs(), k) == 'true' for k in ('bEOTOrAIProcessing', 'bEndOfTurnProcessing'))
        self._busy_t = time.time()
        return self._busy

    def memo(self, key, fn):
        """fn() read once per turn (names, ideologies, relations, wars, pending offers...): every chat message
        used to re-read them for every nation. Our own actions drop what they change (send_action)."""
        cache = self.__dict__.setdefault('_memo', {})
        if key not in cache or cache[key][0] != self._turn:
            cache[key] = (self._turn, fn())
        return cache[key][1]

    def forget(self, def_name):
        """What our action changed is read again: relations after ActIncDipRelations, else wars and offers."""
        drop = ('rel',) if 'DipRelations' in def_name else ('wars', 'pending', 'gov', 'alliances', 'war_list')
        for k in [k for k in self.__dict__.get('_memo', {}) if (k[0] if isinstance(k, tuple) else k) in drop]:
            del self._memo[k]

    def alliance_map(self):
        """{alliance object: (nAllianceID, {member nCountryID}, [member objects])}, read once per turn (dropped
        after our own non-relations actions): member objects and alliance ids are kept for good."""
        def read():
            ids = self.__dict__.setdefault('_al_ids', {})
            out = {}
            for a in self._alliances()[1]:
                if a not in ids:
                    ids[a] = self.prop(a, 'nAllianceID')
                ms = self.refs(a, 'objCurrentMembers')
                out[a] = (ids[a], {self.fixed(m).get('nCountryID') for m in ms}, ms)
            return out
        return self.memo('alliances', read)

    def war_sides(self):
        """Bot.war_sides on the per-turn alliance map (Bot's shows every alliance on every call)."""
        me, amap = str(self.country_id()), self.alliance_map()
        allies = set().union(*([ids for _, ids, _ in amap.values() if me in ids] or [set()]))
        by_id = {aid: ids for aid, ids, _ in amap.values()}
        # each war's sides are read once for good (5 reads per war; a big game has dozens of wars and every
        # alliance / surrender command re-ran them all): only wars new since the last call cost reads
        known = self.__dict__.setdefault('_war_refs', {})

        def ref(r):
            q = self.fixed(self.obj_id(r or ''))
            return ('A', q['nAllianceID']) if 'nAllianceID' in q else ('C', q.get('nCountryID'))

        def ids(refs):
            return set().union(*[by_id.get(v, set()) if k == 'A' else {v} for k, v in refs])
        enemies = set()
        for w in self.memo('war_list', lambda: self._alliances()[2]):
            if w not in known:
                p = self.fixed(w)
                known[w] = ((ref(p.get('objAttackerCountry')), ref(p.get('objOffense'))),
                            (ref(p.get('objDefenderCountry')), ref(p.get('objDefense'))))
            att, dfn = ids(known[w][0]), ids(known[w][1])
            enemies |= dfn if me in att else att if me in dfn else set()
        return allies - {me}, enemies

    def eot(self):
        """The one cheap check run() makes while a turn ends: a single flag."""
        return self.prop(self.gs(), 'bEOTOrAIProcessing') == 'true'

    def gs(self):
        """Our GameState object id (read once, with small reads)."""
        if getattr(self, '_gs', None) is None:
            self._gs = self.obj_id(self.prop(self._me(), 'objGameState') or '')
        return self._gs

    def gsp(self, *names):
        """{name: value} of a few GameState properties ('dump property' each: never the whole object)."""
        return {n: self.prop(self.gs(), n) for n in names}

    def _me(self):
        """Our own Player id, as Bot.player but with small reads (no 'show object' of the Driver)."""
        if getattr(self, '_pid', -1) > 0:
            return self._pid
        av = self.obj_id(self.prop(self.driver, 'objMyAvatar') or '')
        pid = self.obj_id(self.prop(av, 'objPlayer') or '') if av > 0 else -1
        if pid > 0 and self.obj_id(self.prop(pid, 'objGameState') or '') > 0:
            self._pid = pid
        return pid

    def _data(self):
        """The acting nation's (or our) PlayerData id, kept per Player."""
        cache, p = self.__dict__.setdefault('_datas', {}), self.player()
        if p not in cache:
            cache[p] = self.obj_id(self.prop(p, 'objData') or '')
        return cache[p]

    def _alliances(self):
        """As Bot._alliances, without showing GameState (its alliance manager read once)."""
        if getattr(self, '_am', None) is None:
            self._am = self.obj_id(self.prop(self.gs(), 'objAllianceManager') or '')
        if self._am < 0:
            self._am = None
            raise RuntimeError('alliance manager not readable yet')
        return self._am, self.refs(self._am, 'objCurrentAlliances'), self.refs(self._am, 'objCurrentWars')

    def wait_idle(self, limit=300):
        t = time.time()
        while self.busy():
            if time.time() - t > limit:
                raise RuntimeError('the turn is still ending; action not sent')
            time.sleep(3)

    def chat_lines(self, oid):
        text = self.prop(oid, 'strBigChat') or ''
        if text:
            self.__dict__.setdefault('_written', set()).add(oid)      # write() needs no read to know
        lines = parse_chat(self, text)
        self.__dict__.setdefault('_chat_len', {})[oid] = len(lines)      # trim_chat: no read to decide
        return lines

    def members(self, oid):
        return [self.prop(w, 'strString') for w in self.refs(oid, 'objPlayers')]

    def write(self, oid, country, text):
        """A line in the chat as 'country' (the chat window's ActAddToChat would sign it with our own nation).
        'Chat' lines are the code's own notes, in Spanish: translated to the chat language (tr)."""
        if country == 'Chat':
            text = tr(self, text)
        text = ' '.join(text.replace('"', "'").split())[:500] or '...'
        first = oid not in self.__dict__.setdefault('_written', set()) and not (self.prop(oid, 'strBigChat') or '')
        self._written.add(oid)
        gid = self.gid(oid)
        acting, self.acting = self.acting, None
        try:
            self.send_action('ActAlterPropertyImmed', {
                'nGOID': gid, 'strPropName': 'strBigChat', 'bAppend': True,
                'strNewValue': ('' if first else '\n') + '%s(%s):%s' % (country, self.cfg['tag'], text)})
        finally:
            self.acting = acting

    def gid(self, oid):
        """The chat's nGameObject (re-read if a busy frame lost the answer)."""
        cache = self.__dict__.setdefault('_gids', {})
        for _ in range(3):
            v = cache.get(oid) or self.prop(oid, 'nGameObject')
            if v:
                cache[oid] = int(v)
                return int(v)
            time.sleep(0.5)
        raise RuntimeError('could not read chat %d' % oid)

    def add_to_chat(self, oid, country):
        self.wait_idle()
        return self.con.cmd('action ActAddPlayerToChat %d "%s"' % (self.gid(oid), country))

    def nations(self):
        """{name: Player id} of every nation in the game: names from the scenario files, each Player found on
        first use (Players)."""
        if getattr(self, '_players', None) is None:
            self._players = Players(self)
        return self._players

    def in_game(self):
        """Still in the game we started with (back at the menu, or another game loaded: False)."""
        av = self.obj_id(self.prop(self.driver, 'objMyAvatar') or '')
        return av > 0 and self.obj_id(self.prop(av, 'objPlayer') or '') == self._me()

    def humans(self):
        """Nations held by a human (us and, in a multiplayer game we host, the other players): GameState.
        objTakenPlayers with a real strTakenBy (great powers 'AI Control' are CPU). Re-read every 30 s (players
        join and leave)."""
        return ({getattr(self, 'host', None)} | self.__dict__.get('_chat_humans', set()) |
                set(self.__dict__.get('_taken', {}).values())) - {None}

    def check_taken(self):
        """One small step of the multiplayer check (background, one per tick): the next GameState.objTakenPlayers
        entry with a real strTakenBy is a human (the list is re-read after each pass)."""
        if not self.__dict__.get('_taken_todo'):
            gs = self.gs()
            self._taken_todo, self._taken = self.refs(gs, 'objTakenPlayers'), self.__dict__.get('_taken', {})
            return
        p = self._taken_todo.pop(0)
        if self.prop(p, 'strTakenBy') not in (None, '', 'AI Control'):
            self._taken[p] = self.prop(p, 'strName')
        else:
            self._taken.pop(p, None)

    def cpus(self):
        return set(self.nations()) - self.humans()

    def is_host(self):
        """The CPU nations' avatars live only in the hosting game (single player is its own host): on a client
        there is no avatar to act through."""
        cpus = self.cpus()
        cache = self.__dict__.setdefault('_avatars', {})
        if self.__dict__.get('_av_todo') is None:
            self._av_todo = self.refs(self.driver, 'objAvatars')
        while not cpus & set(cache) and self._av_todo:      # small reads, until one CPU avatar shows up
            a = self._av_todo.pop(0)
            cache.setdefault(self.prop(a, 'strOwner'), a)
        return bool(cpus & set(cache))

    def all_chats(self):
        """Chat object ids of every human player (host first), each chat once: a chat shared by several players
        is listed under each of them (deduped by object id and by nGameObject)."""
        gids, out = self.__dict__.setdefault('_chat_gids', {}), []
        if time.time() - self.__dict__.get('_chats_t', 0) > 60:
            self._chats_t, self._chat_lists = time.time(), {}
            self.__dict__['_chat_refresh'] = True       # forget the chats the player removed (below)
        lists = self._chat_lists
        for h in sorted(self.humans(), key=lambda n: n != self.host):
            if h not in lists:
                p = self.nations().get(h)
                lists[h] = self.refs(p, 'objChat') if p else []
            for oid in lists[h]:
                if oid not in gids:
                    try:
                        gids[oid] = self.gid(oid)
                    except RuntimeError:
                        continue            # unreadable this round: next one
                if oid not in out and gids[oid] not in [gids[o] for o in out]:
                    out.append(oid)
        if self.__dict__.pop('_chat_refresh', False):
            if time.time() - self.__dict__.get('_ended_t', 0) > 300:      # a chat ended with its CLOSE button
                self._ended_t = time.time()
                self._ended = {o for o in out if self.prop(o, 'bChatEnded') == 'true'}
            out = [o for o in out if o not in self.__dict__.get('_ended', ())]
            gone = set(gids) - set(out)
            for d in ('_chat_gids', '_gids', '_chat_len', '_chat_text'):
                for o in gone:
                    self.__dict__.get(d, {}).pop(o, None)
            self.__dict__.get('_written', set()).difference_update(gone)
            if self.__dict__.get('_active_chat') in gone:
                self._active_chat = None
            self.closed_chats = gone      # run() drops their seen marks; we never read or write them again
        return out

    def named(self, text, at=False):
        """Nations a message names (game names, Spanish aliases). at=True: only '@France', '@Francia',
        '@Reino Unido' (a chat message joins only the nations it calls with '@'; plain mentions don't)."""
        found, low = [], {n.lower(): n for n in self.nations()}

        def hit(w):
            h = low.get(w.lower()) or self.ALIASES.get(norm(w.lower())) or squashed(self, w)
            return h if h in self.nations() else None
        if at:      # '@' + up to 3 words; the longest that is a nation ('@Reino_Unido' also works)
            for m in re.finditer(r'@([\wÀ-ÿ]+(?:[ _][\wÀ-ÿ]+){0,2})', text):
                s = m.group(1).replace('_', ' ').split()
                h = next((h for h in (hit(' '.join(s[:n])) for n in range(len(s), 0, -1)) if h), None)
                if h and h not in found:
                    found.append(h)
            return found
        words = re.findall(r'[\wÀ-ÿ]+', text)
        for n in range(3, 0, -1):
            for i in range(len(words) - n + 1):
                h = hit(' '.join(words[i:i + n]))
                if h and h not in found:
                    found.append(h)
        return found

    def context(self, cpus, human):
        """What the leaders know: date, scenario, and each CPU nation's standing with the player."""
        gs = self.memo('gs', lambda: self.gsp('dateCurrent', 'nCurrentTurn', 'durSinceStart'))
        if not hasattr(self, '_scenario'):
            sc = self.obj_id(self.prop(self.gs(), 'objScenario') or '')
            self._scenario = (self.prop(sc, 'strDisplayName') or getattr(self, 'scenario', '') or '',
                              (self.prop(sc, 'strDescription') or '')[:700])
        parts = ['Escenario: %s. %s' % self._scenario,
                 'Fecha de hoy en la partida: %s (turno %s; pasaron %s desde el inicio)' % (
                     gs.get('dateCurrent'), gs.get('nCurrentTurn'), gs.get('durSinceStart'))]
        gh = self.memo(('gov', human), lambda: gov_type(self, human))
        parts.append('%s (el jugador): ideología %s' % (human, GOV_ES.get(gh, gh)))
        for c in cpus:
            try:
                parts.append('  %s, %s' % (c, self.military(c, gs.get('nCurrentTurn'))))
            except Exception as e:          # partial reads: talk without it
                self.log('act_error', {'military': c, 'error': str(e)[:200]})
            rel = self.memo(('rel', c), lambda: self.report('relaciones', c))
            m = re.search(r'(?m)^\s*%s\s+(\d+)\s*$' % re.escape(human), rel)
            g = self.memo(('gov', c), lambda: gov_type(self, c))
            parts.append('%s: ideología %s; relación con %s: %s de 1000 (%s)' % (
                c, GOV_ES.get(g, g), human, m.group(1) if m else '?', relation_word(int(m.group(1))) if m else '?'))
            try:
                claims = self.claims(c)
            except Exception:           # no scenario files: talk without it
                claims = []
            if claims:
                parts.append('  %s reclama como regiones históricas (le importan de verdad): %s' % (c, ', '.join(claims)))
            try:
                foes, friends = self.leanings(c)
            except Exception:
                foes, friends = [], []
            if foes or friends:
                parts.append('  %s, por su historia en el escenario: enemistades %s; amistades %s' % (
                    c, ', '.join(foes) or 'ninguna', ', '.join(friends) or 'ninguna'))
            st = game_state(self)
            if st['memory'].get(c):
                parts.append('  Memoria de %s (charlas y promesas anteriores): %s' % (c, ' | '.join(st['memory'][c])))
            dem = [demand_text(d) for d in st['demands'] if d['country'] == c]
            if dem:
                parts.append('  Exigencias pendientes de %s: %s' % (c, '; '.join(dem)))
        for what, fn in (('Guerras en curso', lambda: self.memo('wars', lambda: wars_text(self))),
                         ('Avisos y propuestas de tratado pendientes', lambda: self.memo(
                             ('pending', human, tuple(cpus)),
                             lambda: pending_text(self, [human] + list(cpus))))):
            try:
                text = fn()
            except Exception as e:      # partial reads: talk without it
                self.log('act_error', {what: str(e)[:200]})
                continue
            parts.append('%s: %s' % (what, text or 'ninguna'))
        return '\n'.join(parts)

    def turn(self):
        if getattr(self, '_turn', None) is None:
            self._turn = self.prop(self.gs(), 'nCurrentTurn')
        return int(self._turn or 0)

    def propose(self, kind, country, offer=None, request=None, money=0, war_id=None):
        """Bot.propose, validated first so the game never shows a broken popup (e.g. a non-aggression offer
        between allies showed raw 'SID.UI.DP.NonAggression.Desc'): a territory deal only with regions their side
        owns now; peace only with a real war between them (its nWarID, never -1); pacts (alliance,
        non-aggression, access) neither between allies nor with an enemy. A refusal raises Refused (the chat says
        why) and nothing is sent. Offers to a human are checked to have arrived as a proposed treaty."""
        me = self.acting or self.cfg['country']
        if kind == 'paz':
            war_id = war_between(self, me, country) if war_id in (None, -1, '') else war_id
            if war_id is None:
                raise Refused('%s y %s no están en guerra: no hay paz que proponer.' % (me, country))
        if kind in ('alianza', 'no_agresion', 'acceso_militar'):
            allies, enemies = self.war_sides()
            other = str(self.country_id(country))
            if other in allies:
                raise Refused('%s y %s ya son aliados: ese pacto no hace falta.' % (me, country))
            if other in enemies:
                raise Refused('%s y %s están en guerra: primero la paz.' % (me, country))
        if kind == 'territorio':
            me = self.acting or self.cfg['country']
            for regions, owner in ((offer, me), (request, country)):
                if regions:
                    own = owned_regions(self, owner, {self.region_id(r) for r in regions})
                    bad = [r for r in regions if self.region_id(r) not in own]
                    if bad:
                        raise NotOwner('%s no es dueño de %s: no se propone ese traspaso.' % (owner, ', '.join(bad)))
        to_human = country in self.humans() and kind in TREATY_KINDS
        before = {p['id'] for p in self.proposals()} if to_human else set()
        out = super().propose(kind, country, offer, request, money, war_id)
        if 'error validating' in (out or '').lower():
            raise Refused('El juego rechazó la oferta de %s (%s) por datos no válidos.' % (me, kind))
        if to_human and not any(p['id'] not in before and p['de'] == me for p in self.proposals()):
            raise Refused('La oferta de %s a %s (%s) no llegó como tratado propuesto.' % (me, country, kind))
        return out

    def unit(self, u, region=False):
        """(strType, nRegionID, nGameObject) of a unit with small reads: type and id kept for good, the region
        for the turn (only read when region=True)."""
        fixed = self.__dict__.setdefault('_units', {})
        if u not in fixed:
            fixed[u] = (self.prop(u, 'strType'), self.prop(u, 'nGameObject'))
        where = self.__dict__.setdefault('_unit_regions', {})
        if region and where.get(u, (None,))[0] != self._turn:
            where[u] = (self._turn, int(self.prop(u, 'nRegionID') or -1))
        return fixed[u][0], where.get(u, (None, -1))[1], int(fixed[u][1] or -1)

    def country_regions(self, name):
        """A nation's regions from the scenario files (no game reads; Bot's live version shows every region)."""
        saved = self.__dict__.pop('_country_oids', None)
        try:
            return super().country_regions(name)
        finally:
            if saved is not None:
                self._country_oids = saved

    def move_troops(self, target, amount=0, declare_war=False):
        self.turn_limit('TroopOrder', {})
        return self._move_troops(target, amount, declare_war)

    def _move_troops(self, target, amount=0, declare_war=False):
        """Bot.move_troops, surgical: units are read with small reads (type and id once ever, region once per
        turn), at most UNIT_READS game reads per order, units seen nearest last time first; the armies nearest to
        the target among them get one ActMove each."""
        names, adj = self.land_map()
        low = {n.lower(): i for i, n in enumerate(names)}
        key = (target or '').strip().lower()
        goals = {low[key]} if key in low else self.country_regions(self.country_name(target))
        if not goals & set(adj):
            raise RuntimeError('no conozco la región o el país %s' % target)
        owners = {self.region_owners().get(g) for g in goals} - {None, self.cfg['country']}
        allies, enemies = self.war_sides() if owners else (set(), set())
        closed = sorted(o for o in owners if str(self.country_id(o)) not in allies | enemies)
        for o in closed if declare_war else []:
            self.propose('guerra', o)
        if closed and not declare_war:
            return ('PREGUNTA: no estás en guerra con %s, así que tus tropas no pueden entrar. ¿Quieres declararle la '
                    'guerra? Decídelo tú: si sí, llama otra vez move_troops con declare_war=true; si no, explícalo '
                    'en el chat a quien lo pidió.' % ', '.join(closed))
        near = {}      # land distance to the nearest goal (map only)
        for g in goals & set(adj):
            for r, d in ai_player.bfs(adj, g).items():
                near[r] = min(d, near.get(r, d))
        want = max(1, int(amount or 0) or 3)
        units = self.refs(self._data(), 'objUnits')
        where = self.__dict__.get('_unit_regions', {})
        # read this turn: free, so first; then the rest by where they were last seen (nearest first): the reads go
        # to units not looked at yet, so each new order sees more of the army
        units.sort(key=lambda u: (where.get(u, (None,))[0] != self._turn, near.get(where.get(u, (None, -1))[1], 10 ** 6)))
        start, armies = self.con.count if hasattr(self.con, 'count') else 0, []
        for u in units:
            if hasattr(self.con, 'count') and self.con.count - start >= UNIT_READS:
                break
            kind, reg, goid = self.unit(u, region=self.unit(u)[0] == 'Army')
            if kind == 'Army' and reg in near:
                armies.append((near[reg], reg, goid, u))
        if not armies:
            raise RuntimeError('ningún ejército llega por tierra a %s (miré %d unidades)' % (target, len(units)))
        armies.sort()
        goal = min(goals & set(adj), key=lambda g: ai_player.bfs(adj, armies[0][1]).get(g, 10 ** 6))
        out = []
        for d, reg, goid, u in armies[:want]:
            if reg == goal:
                out.append('ejército %d ya está en %s' % (goid, names[goal]))
                continue
            self.send_action('ActMove', {'nGOID': goid, 'nRegionID': goal},
                             [('objExpectedIncidentsList', 'PathIncidentList', {})])      # NULL list: ignored
            ok = self.obj_id(self.prop(u, 'objOrder') or '') > 0
            out.append('ejército %d -> %s (%d regiones)%s' % (goid, names[goal], d, '' if ok else ' RECHAZADO'))
        return '; '.join(out)

    def as_nation(self, country, fn):
        """fn() with 'our' nation = country (Bot's helpers read self.player() / cfg['country'])."""
        saved = self.cfg['country'], self.acting
        self.cfg['country'], self.acting = country, country
        try:
            return fn()
        finally:
            self.cfg['country'], self.acting = saved

    def military(self, country, turn):
        """Text for the LLM, read once per turn: the nation's AI profile (AI_KNOBS), forces, research and what its
        cities produce."""
        cache = self.__dict__.setdefault('_military', {})
        if cache.get(country, (None,))[0] != turn:
            def read():
                data = {k: self.prop(self._data(), k) for k in list(AI_KNOBS) + ['eInternationalPosition']}
                knobs = ', '.join('%s %s' % (es, data.get(k)) for k, es in AI_KNOBS.items() if data.get(k) is not None)
                pos = (data.get('eInternationalPosition') or '').replace('PLAYER_INTERNATIONAL_POSITION__', '').lower()
                knobs += '; posición internacional: %s' % pos if pos else ''
                forces = ' '.join(self.report('militar', country).split())[:400]
                gov = self.obj_id(self.prop(self._data(), 'objGovData') or '')
                rs = {'nNeededIPUs': self.prop(self.obj_id(self.prop(gov, 'objResearchState') or ''), 'nNeededIPUs')}
                research = 'investigando (faltan %s IPUs)' % rs.get('nNeededIPUs') if int(rs.get('nNeededIPUs') or 0) > 0 \
                    else 'sin investigación en curso'
                # no per-city reads (3 each, ~75 for a big nation): the production mix isn't worth them
                return 'perfil de IA (escala del escenario, ~0-30): %s. Fuerzas: %s. %s' % (knobs, forces, research)
            cache[country] = (turn, self.as_nation(country, read))
        return cache[country][1]

    def set_knobs(self, country, changes):
        """Raises / lowers the nation's AI profile values (the CPU AI reads them: doctrine, posture...) by the given
        deltas, clamped to 0-30. Returns 'Doctrina militar 15→20; ...'."""
        def apply():
            data = self._data()
            cur = {k: self.prop(data, k) for k in changes if k in AI_KNOBS}
            done = []
            for key, delta in changes.items():
                if key in AI_KNOBS and delta and cur.get(key) not in (None, ''):
                    old = int(cur[key])
                    new = max(0, min(30, old + int(delta)))
                    if new != old:
                        self._set(data, {key: new})
                        done.append('%s %d→%d' % (AI_KNOBS[key], old, new))
            return done
        done = self.as_nation(country, apply)
        self.__dict__.get('_military', {}).pop(country, None)
        return done

    def seas_near(self, region):
        """Sea regions touching a land region (regions.bin neighbours with the sea flag), e.g. Falklands ->
        Argentine Sea: so a nation can ask for a fleet in a concrete sea zone. Map lookup as in Bot.land_map."""
        if getattr(self, '_regions', None) is None:
            import mhmap
            me, name = os.path.join(gamepaths.GAMES[self.cfg['game']]['path'], 'Modern Europe'), 'World'
            for where in ('user', 'system'):
                f = os.path.join(me, where, 'scenarios', getattr(self, 'scenario', '') or '', 'scenario.xml')
                if os.path.isfile(f):
                    m = re.search(r'strMapName" value="([^"]+)"', open(f, encoding='utf-8', errors='replace').read())
                    name = m.group(1) if m else name
                    break
            path = os.path.join(me, 'system', 'DisplayLibraries', 'Maps', name, 'xml', 'regions.bin')
            self._regions = mhmap.read_regions_bin(open(path, 'rb').read())
        r = next((x for x in self._regions if x.name == region), None)
        return [self._regions[n].name for n in (r.neighbors if r else ()) if self._regions[n].u_flag == 1]

    def leanings(self, country, n=25):
        """(foes, friends) from player<Country>.xml's starting relations (DipRelInitialValue): the n lowest under
        300 and the n highest over 700 of 1000, as 'Name (value)'."""
        cache = self.__dict__.setdefault('_leanings', {})
        if country not in cache:
            vals = []
            for where in ('user', 'system'):
                f = os.path.join(gamepaths.GAMES[self.cfg['game']]['path'], 'Modern Europe', where, 'scenarios',
                                 getattr(self, 'scenario', '') or '', 'player%s.xml' % country)
                if os.path.isfile(f):
                    text = open(f, encoding='utf-8', errors='replace').read()
                    vals = [(int(v), t) for t, v in re.findall(
                        r'strTargetCountry" value="([^"]+)"/>\s*<property name="nValue" value="(-?\d+)"', text)]
                    break
            vals.sort()
            cache[country] = (['%s (%d)' % (t, v) for v, t in vals if v < 300][:n],
                              ['%s (%d)' % (t, v) for v, t in reversed(vals) if v > 700][:n])
        return cache[country]

    def claims(self, country):
        """['Falklands (United Kingdom)', ...]: Bot.historic_regions for another nation, with each region's owner.
        shortcut: owners at the scenario's start (Bot.region_owners)."""
        cache = self.__dict__.setdefault('_claims', {})
        if country not in cache:
            saved = self.cfg['country'], getattr(self, '_historic', None)
            self.cfg['country'], self._historic = country, None
            try:
                regions = self.historic_regions()
            finally:
                self.cfg['country'], self._historic = saved
            names, owners = self.land_map()[0], self.region_owners()
            idx = {n: i for i, n in enumerate(names)}
            sea = lambda r: '; mar: %s' % ', '.join(self.seas_near(r)) if self.seas_near(r) else ''
            cache[country] = ['%s (%s%s)' % (r, 'suya' if owners.get(idx.get(r)) == country else owners.get(idx.get(r), '?'),
                                             sea(r)) for r in regions]
        return cache[country]


SYSTEM = """Eres los jefes de Estado de las naciones que controla la computadora en una partida de un solo jugador \
de Making History ({game}). El jugador humano dirige {human} y te escribe por el chat diplomático del juego. \
Respondes como el dirigente de cada nación que está en el chat, con su propia voz e intereses.
{era}
Cada respuesta tuya incluye al menos un say: el jugador espera que le contesten.
Cada nación habla como su jefe de Estado o de Gobierno real en la fecha actual de la partida: con su nombre \
cuando venga al caso y con su estilo y carácter conocidos (en un mundo de fantasía, un dirigente inventado y \
coherente).
Como un aliado real, una nación puede exigirle al jugador gestos concretos a cambio de su apoyo o para sentirse \
segura: mover su flota a un mar concreto (usa los nombres de mar del contexto), tropas a una región, ayuda o \
recursos. Hazlo con la herramienta demand (con plazo en turnos): el código lo comprueba y la nación reacciona al \
cumplirse o vencer. El jugador lo hace él mismo.
Si el jugador pide comercio, ayuda o territorio y a la nación no le conviene tal cual, puede contraofertar: \
propose comercio, ayuda o territorio con sus propias condiciones (lo que da y lo que pide), y say explicando la \
contraoferta.
Con remember anota en una frase lo que esa nación debe recordar de esta charla (promesas, acuerdos, ofensas); su \
memoria aparece en la situación.
Escribe SIEMPRE en {language}, aunque los nombres del juego estén en otro idioma. Mensajes breves (1-3 frases), \
coherentes con lo que cada uno dijo antes; no inventes hechos que contradigan la situación.
Herramientas: say (habla una nación del chat), propose (esa nación le propone al jugador un tratado: guerra la \
declara al instante; alianza, no_agresion, acceso_militar, paz, comercio, ayuda), relations (gesto que mejora o \
empeora la relación de esa nación con el jugador). Las naciones siguen jugando con su IA normal; tú hablas y, \
cuando la conversación lo justifique de verdad, haces jugadas. Si la nación acepta varias peticiones de un mensaje, \
haz TODAS las llamadas que correspondan en esta misma respuesta (p. ej. command /troops move y propose comercio); \
nunca prometas con palabras una jugada que no hagas ahora. Haz jugadas solo si responden a lo que el jugador pide o negocia en este mensaje; nunca por iniciativa propia (cada jugada carga la partida). Como mucho 2 jugadas por mensaje. Los países CPU siguen jugando con su IA normal: no gestiones su economía, tropas ni alianzas con terceros salvo que el jugador lo pida. Si la nación acepta un tratado, comercio, ayuda o traspaso de regiones, lo envía ELLA misma con propose en esta respuesta; nunca le pidas al jugador que te mande él la propuesta, porque las propuestas que el jugador envía las contesta la IA del juego y las rechaza. Mandar tropas o ejércitos a un país o región es \
command /troops move <tu país> <país o región destino> (llegan por tierra o por mar); el acceso militar no mueve \
tropas. Mandar la flota a un mar es el mismo command con un mar de destino (/troops move <tu país> <mar>). En los comandos, el primer país es siempre la nación que actúa. Un acuerdo con algo a cambio (da recursos y pide otros) \
es propose comercio con offer y request; ayuda es solo un regalo, sin nada a cambio. Si el jugador pide un tratado (alianza, \
paz, no agresión, acceso militar, comercio, ayuda) y la nación acepta, eso se firma llamando a propose con ese tipo \
desde la nación hacia el jugador: él lo acepta en su ventana. Si lo que pide se resuelve con un comando del chat \
(alianza, paz, comercio, ayuda, relaciones, ideología, etc.), decide como esa nación según sus intereses, su \
relación con el jugador y su ideología: si acepta, llama command con el comando exacto además de say; si no acepta, \
solo say explicando por qué. Sin modo yesman sé exigente, como un estadista real: una alianza solo con relación \
buena o muy estrecha (600 o más) y sin ideologías enfrentadas; con relación mala u hostil rechaza o pide antes \
gestos (comercio, ayuda); un cambio de ideología casi nunca. Si mencionas la relación, dila como «N de 1000». \
Nunca anuncies una jugada sin llamar a \
su herramienta en la misma respuesta. Responde con todas las llamadas juntas. En las herramientas usa los nombres \
de países del juego en inglés."""

ERA = {True: ('Es un mundo de fantasía: no lo compares con la historia real ni uses fechas o hechos del mundo real.'),
       False: ('La partida empezó el {start}: razonas como un dirigente de esa época (lo que se sabía entonces, sin '
               'conocer el futuro), y la fecha actual de la partida es la que se indica en la situación.')}

TONE_STEP = 5      # relation points (of 1000) a friendly / hostile exchange moves, both ways


PEACE_ASKED = re.compile(r'\b(paz|peace|armisticio|armistice|tregua|truce|cese|ceasefire|alto el fuego)\b', re.I)


def war_between(bot, a, b):
    """nWarID of a war with a and b on opposite sides (a side is a country or a whole alliance), else None."""
    ia, ib = str(bot.country_id(a)), str(bot.country_id(b))
    wars = bot.memo('war_list', lambda: bot._alliances()[2])
    members = {aid: ids for aid, ids, _ in bot.alliance_map().values()}
    side = lambda ref: (lambda q: members.get(q['nAllianceID'], set()) if 'nAllianceID' in q
                        else {q.get('nCountryID')})(bot.fixed(bot.obj_id(ref or '')))
    for w in wars:
        p = bot.fixed(w)
        att = side(p.get('objAttackerCountry')) | side(p.get('objOffense'))
        dfn = side(p.get('objDefenderCountry')) | side(p.get('objDefense'))
        if (ia in att and ib in dfn) or (ib in att and ia in dfn):
            return int(p.get('nWarID'))
    return None


def event_peace(bot, a, b):
    """Peace between a and b with the events' ActFormSeparatePeaceConcessions (a ratified separate peace, no
    concessions), sent by a. True if they are no longer at war afterwards."""
    war = war_between(bot, a, b)
    if war is None or not bot.cfg.get('event_actions', True):
        return False
    bot.as_nation(a, lambda: bot.send_action('ActFormSeparatePeaceConcessions', {
        'strToCountry': b, 'nSourceCountryID': bot.country_id(a), 'nWarID': war, 'bCedeConqueredRegions': False,
        'bJoinAlliance': False, 'bMilitaryAccess': False, 'bInstallFriendlyGovernment': False}))
    return war_between(bot, a, b) is None


def stock(bot, country):
    """{resource: amount} a nation holds (its Country's objResources, small reads)."""
    c = bot.obj_id(bot.prop(bot.nations()[country], 'objCountry') or '')
    return {bot.prop(r, 'strName'): int(bot.prop(r, 'nAmount') or 0) for r in bot.refs(c, 'objResources')}


def event_outcome(bot, oid, a, country, target, human, new):
    """What the chat agreed, applied as scenario events do it (event_actions on; False: use the proposal):
    - ayuda / comercio where only the nation gives: ActIncResourceStock, taken from it and given to the target
      (one time; only what it really has);
    - acceso_militar: ActFormMilitaryAccess (a ratified access treaty, what events use);
    - paz, when the player's own message asked for it: ActFormSeparatePeaceConcessions.
    Alliances, non-aggression, trades that take the player's resources and war stay as the game's proposals."""
    if not bot.cfg.get('event_actions', True) or target != human:
        return False
    kind = a.get('kind')
    if kind in ('ayuda', 'comercio') and a.get('offer') and not a.get('request'):
        gift = game_resources(bot, oid, _res(a.get('offer')))
        have = stock(bot, country)
        short = [r for r, n in gift.items() if have.get(r, 0) < n]
        if not gift or short:
            if short:
                raise Refused('%s no tiene bastante %s para darlo.' % (country, ', '.join(short)))
            return False
        for r, n in gift.items():
            for who, inc in ((country, -n), (target, n)):
                bot.send_action('ActIncResourceStock', {'strCountry': who, 'strResource': r, 'nIncrement': inc})
        bot.write(oid, 'Chat', 'Hecho: %s entrega a %s %s.' % (country, target, ', '.join('%s %d' % kv for kv in gift.items())))
        return True
    if kind == 'acceso_militar':
        if str(bot.country_id(target)) in bot.war_sides()[1]:
            raise Refused('%s y %s están en guerra: primero la paz.' % (country, target))
        bot.send_action('ActFormMilitaryAccess', {'strToCountry': target})      # as the nation (acting)
        bot.write(oid, 'Chat', 'Hecho: %s da acceso militar a %s.' % (country, target))
        return True
    if kind == 'paz' and PEACE_ASKED.search(' '.join(new)):
        if event_peace(bot, country, target):
            bot.write(oid, 'Chat', 'Hecho: %s y %s firman la paz.' % (country, target))
            return True
    return False


# game moves limited per game turn (cfg 'turn_limits'); a whole /troops move order counts once ('TroopOrder')
LIMITED = {'TroopOrder': 'troops', 'ActProposeDefensePact': 'alliance', 'ActDevFormDefensePact': 'alliance',
           'ActCancelDefensePact': 'alliance', 'ActProposeTerritorialTransfer': 'territory',
           'ActTransferRegionOwnership': 'territory', 'ActIncDipRelations': 'relations',
           'ActProposeDeclareWar': 'war', 'ActDevStartWar': 'war'}
LIMIT_ES = {'alliance': 'cambio(s) de alianza', 'territory': 'traspaso(s) de territorio', 'relations':
            'cambio(s) de relaciones', 'troops': 'orden(es) de tropas', 'war': 'declaración(es) de guerra'}


def tone_relations(bot, country, human, step):
    """The tone of a say: ActIncDipRelations by 'step' both ways between the nation and the player (no chat line)."""
    a, b = bot.country_id(country), bot.country_id(human)
    if a < 0 or b < 0:
        return
    acting, bot.acting = bot.acting, None
    try:
        for x, y in ((a, b), (b, a)):
            bot.send_action('ActIncDipRelations', {'nSourceCountryID': x, 'nTargetCountryID': y, 'nAmount': step})
    finally:
        bot.acting = acting
    bot.log('did', {'tone': [country, human, step]})


REL_FIELD = {'type': 'integer', 'description': 'solo si acepta una alianza: la relación que queda con el otro país, '
             'de 500 a 800 de 1000 (500 = alianza de conveniencia; 650 = buena; 800 = aliados de verdad, afines, con '
             'historia común). Nunca la baja.'}

TOOLS = [
    {'name': 'say', 'description': 'Una nación del chat le habla al jugador.',
     'parameters': {'type': 'object', 'properties': {
         'country': {'type': 'string', 'description': 'nación que habla (nombre del juego)'},
         'text': {'type': 'string'},
         'tone': {'type': 'string', 'enum': ['positive', 'neutral', 'negative'],
                  'description': 'cómo juzga la nación el mensaje del jugador (positivo / negativo mueve la relación '
                                 '±%d)' % TONE_STEP}}, 'required': ['country', 'text']}},
    {'name': 'propose', 'description': 'La nación propone un tratado al jugador (o a target). guerra = le declara la '
                                       'guerra.',
     'parameters': {'type': 'object', 'properties': {
         'country': {'type': 'string', 'description': 'nación que propone'},
         'target': {'type': 'string', 'description': 'a quién se lo propone (por defecto, al jugador); en guerra es OBLIGATORIO: el país al que se declara'},
         'kind': {'type': 'string', 'enum': ['guerra', 'alianza', 'no_agresion', 'acceso_militar', 'paz',
                                             'comercio', 'ayuda', 'territorio', 'anexion']},
         'offer': {'type': 'string', 'description': 'recursos que da, p. ej. "Oil:100, Food:50"; en territorio, '
                                                    'regiones propias que cede, p. ej. "Trentino, Libya"'},
         'request': {'type': 'string', 'description': 'recursos que pide; en territorio, regiones del otro país que '
                                                      'pide'},
         'money': {'type': 'integer'}, 'war_id': {'type': 'integer'}, 'relations': REL_FIELD},
         'required': ['country', 'kind']}},
    {'name': 'command', 'description': 'Si la nación ACEPTA una petición del jugador que se resuelve con un comando '
                                       'del chat, ejecútalo (una llamada por comando; si no acepta, no lo llames). '
                                       'En los comandos con <yo>, ese país es la nación que acepta. ' +
                                       ai_player.HELP.replace('Comandos: ', 'Comandos del juego: ') +
                                       ' Además: /relations improve|reset|set <país> <país> [0-1000], '
                                       '/ideology align <país que cambia> <país modelo>, /merge <país que se une> '
                                       '<país al que se une> (solo con relación de 900+ ambos lados).',
     'parameters': {'type': 'object', 'properties': {
         'country': {'type': 'string', 'description': 'nación que acepta'},
         'command': {'type': 'string', 'description': 'el comando exacto, con cada país escrito sin espacios como '
                                                      'su nombre interno, p. ej. "/alliance join UnitedStates Germany"'},
         'relations': REL_FIELD},
         'required': ['country', 'command']}},
    {'name': 'ai_profile', 'description': 'Si la nación decide cambiar su rumbo, sube o baja su perfil de IA (lo usa '
                                          'la IA del juego para planificar): deltas enteros, p. ej. doctrine +5 = más '
                                          'peso militar. Para investigación y producción usa command (/research, '
                                          '/production).',
     'parameters': {'type': 'object', 'properties': {
         'country': {'type': 'string'}, 'doctrine': {'type': 'integer'}, 'posture': {'type': 'integer'},
         'aggressive': {'type': 'integer'}, 'involvement': {'type': 'integer'}, 'science': {'type': 'integer'},
         'domestic': {'type': 'integer'}}, 'required': ['country']}},
    {'name': 'relations', 'description': 'Gesto que mejora (o con worsen=true empeora) la relación de la nación con '
                                         'el jugador; una vez por turno y nación.',
     'parameters': {'type': 'object', 'properties': {'country': {'type': 'string'}, 'worsen': {'type': 'boolean'}},
                    'required': ['country']}},
    {'name': 'demand', 'description': 'La nación le exige al jugador un gesto concreto con plazo: fleet = flotas suyas '
                                      'en un mar (region = nombre del mar), troops = ejércitos suyos en una región, '
                                      'aid = que le mande un tratado de ayuda o comercio. Al cumplirse, la nación lo '
                                      'agradece y mejora la relación; si vence, protesta y la empeora (o rompe la '
                                      'alianza si if_failed=break_alliance).',
     'parameters': {'type': 'object', 'properties': {
         'country': {'type': 'string'}, 'kind': {'type': 'string', 'enum': ['fleet', 'troops', 'aid']},
         'region': {'type': 'string', 'description': 'mar o región del juego (fleet / troops)'},
         'amount': {'type': 'integer', 'description': 'número de flotas o ejércitos (por defecto 1)'},
         'turns': {'type': 'integer', 'description': 'plazo en turnos (1-10)'},
         'what': {'type': 'string', 'description': 'en aid: qué pide, p. ej. "Oil:100"'},
         'if_failed': {'type': 'string', 'enum': ['relations', 'break_alliance']}},
         'required': ['country', 'kind', 'turns']}},
    {'name': 'remember', 'description': 'Una frase que la nación recordará en próximas charlas (promesas, acuerdos, '
                                        'ofensas).',
     'parameters': {'type': 'object', 'properties': {'country': {'type': 'string'}, 'note': {'type': 'string'}},
                    'required': ['country', 'note']}},
    {'name': 'surrender', 'description': 'Solo si la nación, en guerra con el jugador (o con victor), acepta de verdad '
                                         'rendirse: sale de su alianza, firma la paz, entra en la alianza del vencedor '
                                         'y le cede regiones (las de regions; si no, las que el vencedor ocupa o '
                                         'reclama). Nunca todo su territorio.',
     'parameters': {'type': 'object', 'properties': {
         'country': {'type': 'string', 'description': 'la nación que se rinde'},
         'victor': {'type': 'string', 'description': 'el vencedor (por defecto, el jugador)'},
         'regions': {'type': 'string', 'description': 'regiones que cede, separadas por comas (opcional)'}},
         'required': ['country']}},
]


def think(bot, oid, human, cpus, lines, new, talk_only=False):
    import ai_chat
    cfg = bot.cfg
    name = bot._scenario[0] if hasattr(bot, '_scenario') else ''
    situation = bot.context(cpus, human)
    try:
        owners = region_owners_named(bot, ' '.join(new))
    except Exception as e:          # no map / scenario files: the chat goes on without it
        bot.log('act_error', {'region_owners': str(e)[:200]})
        owners = []
    if owners:
        situation += ('\nRegiones nombradas y su dueño (para tomar una región, la guerra es contra su dueño): '
                      + '; '.join('%s: %s%s' % (r, o, ' (mar: %s)' % ', '.join(bot.seas_near(r)) if bot.seas_near(r) else '')
                                  for r, o in owners))
    fantasy = any(f.lower() in (name or '').lower() for f in cfg['fantasy_scenarios'])
    gs = bot.gsp('dateCurrent', 'durSinceStart')
    start = gs.get('dateCurrent') if gs.get('durSinceStart', '').startswith('0 ') else '%s (menos %s)' % (
        gs.get('dateCurrent'), gs.get('durSinceStart'))
    system = SYSTEM.format(game=cfg['game_name'], human=human, language=cfg['language_name'],
                           era=ERA[fantasy].format(start=start))
    others = sorted(bot.humans() - {human})
    if others:      # a multiplayer game we host
        system += ('\nEs una partida multijugador: también juegan humanos con %s. Quien escribe ahora es %s; a esa '
                   'nación le contestas, le propones y con ella cambias relaciones.' % (', '.join(others), human))
    if getattr(bot, 'yesman', False):      # '/yesman on' in the chat
        system += ('\nMODO YESMAN ACTIVO: las naciones del chat hacen el 100% de lo que pida el jugador, sin '
                   'discutir, y lo ejecutan con las herramientas en esta misma respuesta (un tratado pedido = '
                   'propose de ese tipo hacia el jugador; una guerra u otro tratado con otro país = propose '
                   'con target). Una orden como «Australia declara guerra a Nueva Zelanda» la cumple la primera '
                   'nación (propose guerra con target la segunda) y solo ella responde con say.')
    keep = cfg.get('history_lines', 2)      # the user: no more than the last 2 messages (memory holds the rest)
    if game_state(bot)['summits'] and bot.gid(oid) in game_state(bot)['summits']:
        system += SUMMIT
    tools = TOOLS
    if talk_only:
        system += ('\nAhora solo conversación: responde con say y no hagas jugadas (ni propose, ni command, ni relations).')
    try:
        situation += '\nRecursos del juego (usa estos nombres exactos): %s' % ', '.join(resource_names(bot))
    except Exception:
        pass
    try:      # where troops / fleets sent to the player can go: its regions and the seas around them
        situation += '\n' + regions_line(bot, human)
    except Exception:
        pass
    prompt = ('Situación:\n%s\n\nNaciones en este chat (las que pueden responder): %s\n\nChat:\n%s\n\n'
              'Mensaje nuevo del jugador (%s):\n%s\n\n(Cada say en %s, aunque la nación hable otro idioma.)') % (
        situation, ', '.join(cpus), '\n'.join('%s: %s' % l for l in lines[-keep:]), human, '\n'.join(new),
        cfg['language_name'])
    bot.log('llm_in', {'prompt': prompt})
    msgs = [{'role': 'user', 'text': prompt}]
    r = ai_chat.chat(system, msgs, tools)
    bot.log('llm_out', {'text': r.get('text'), 'calls': r.get('calls'), 'model': r.get('model')})
    calls = r.get('calls') or []
    if not any(c['name'] == 'say' for c in calls):
        # no say (plain text drifts into the scenario's language, e.g. English): one more request, the only retry
        first = r
        if calls:
            msgs += [{'role': 'assistant', 'text': '', 'calls': calls, 'raw': r.get('raw')},
                     {'role': 'user', 'results': [{'id': c.get('id'), 'name': c['name'], 'content': 'hecho'}
                                                  for c in calls]}]
        elif (r.get('text') or '').strip():
            msgs.append({'role': 'assistant', 'text': r['text']})
        msgs.append({'role': 'user', 'text': ('Tus jugadas ya están hechas; ahora contesta al jugador con la herramienta '
                                              'say, en %s.' if calls else 'Contesta al jugador con la herramienta say, '
                                              'en %s (y haz las jugadas que quieras hacer).') % cfg['language_name']})
        r = ai_chat.chat(system, msgs, tools)
        if not (r.get('calls') or (r.get('text') or '').strip()):
            r = first
        bot.log('llm_out', {'text': r.get('text'), 'calls': r.get('calls'), 'model': r.get('model'), 'retry': True})
        # the first answer's moves stand (they were lost before: Italy's aid); the retry adds the words
        more = r.get('calls') or []
        calls = calls + [c for c in more if c['name'] == 'say'] if calls else more
    if not any(c['name'] == 'say' for c in calls) and (r.get('text') or '').strip() and cpus:
        calls.append({'name': 'say', 'args': {'country': cpus[0], 'text': r['text']}})   # plain-text answer
    # the moves first, then the words: a nation whose move failed must not say it was done
    moves = [c for c in calls if c['name'] != 'say']
    heavy = [m for m in moves if m['name'] not in ('remember', 'surrender')]      # a surrender is one decision
    if len(heavy) > MAX_MOVES and not getattr(bot, 'ordered', False):     # the CPU AI keeps playing; we only nudge
        bot.log('ignored_call', {'too_many_moves': [m['name'] for m in heavy[MAX_MOVES:]]})
        moves = [m for m in moves if m not in heavy[MAX_MOVES:]]
    says = [c for c in calls if c['name'] == 'say']
    notes = []
    write = bot.write

    def noting(o, who, text):     # what the moves wrote (refusals, errors, results) while they ran
        notes.append('%s: %s' % (who, text))
        write(o, who, text)
    for c in itertools.chain(moves, [None], says):     # chain reads 'says' late: a reword replaces it in place
        if c is None:             # moves done: reword the says if any move failed
            bot.__dict__.pop('write', None)
            failed = [n for n in notes if FAILED.search(n)]
            if failed and says:
                says[:] = reword(bot, system, says, failed)
            continue
        if c['name'] != 'say':
            bot.write = noting
        a = dict(c.get('args') or {})
        country = bot.country_name(a.get('country', ''))
        if country not in cpus or (talk_only and c['name'] != 'say'):
            bot.log('ignored_call', c)
            continue
        try:
            if c['name'] == 'say':
                bot.write(oid, country, a.get('text', ''))
                step = {'positive': TONE_STEP, 'negative': -TONE_STEP}.get(a.get('tone'))
                tkey = (bot._turn, country, human)
                if step and tkey not in bot.__dict__.setdefault('_toned', set()) and human in bot.nations():
                    bot._toned.add(tkey)      # the tone moves a relation once per game turn and nation
                    tone_relations(bot, country, human, step)
            elif c['name'] == 'propose' and (a.get('kind') in bot.TREATIES or a.get('kind') in ('territorio', 'anexion')):
                bot.cfg['country'], bot.acting = country, country       # Bot.propose acts for cfg['country']
                if a['kind'] == 'guerra' and not a.get('target'):
                    # no target used to mean 'the player': Argentina declared war on Peru (the player) instead of Chile
                    bot.log('ignored_call', dict(c, reason='war without target'))
                    notes.append('%s: error guerra sin país objetivo; no se declaró' % country)
                    continue
                target = bot.country_name(a['target']) if a.get('target') else human
                if a['kind'] in PACTS and pact_with_ally(bot, oid, c, country, target):
                    continue
                ally = a['kind'] == 'guerra' and str(bot.country_id(target)) in bot.war_sides()[0]
                if ally and getattr(bot, 'ordered', False):
                    # an /order: leave the alliance first (the alliance window's 'Break' with that member), then war
                    bot.propose('romper_alianza', target)
                    bot.write(oid, 'Chat', '%s rompe la alianza con %s para poder declararle la guerra.' % (country, target))
                    ally = False
                if ally:
                    # the game takes a nation that declares war on an ally out of its alliance: never by the LLM
                    msg = ('%s no declara la guerra a %s: son aliados, y el juego la sacaría de la alianza. Si de '
                           'verdad lo quieres: /order %s declara la guerra a %s (sale de la alianza y la declara)'
                           % (country, target, country, target))
                    bot.write(oid, 'Chat', msg)
                    bot.log('ignored_call', dict(c, reason='ally'))
                    continue
                hint = bot.members(oid) + bot.named(' '.join(new)) + [human]
                if a['kind'] == 'alianza':         # a vote of every member: relations, votes and the real result
                    alliance_join(bot, oid, country, target, human, a.get('relations'),
                                  lambda: bot.propose('alianza', target), hint)
                elif a['kind'] == 'anexion':         # the nation offers to join target: all its regions
                    bot.cfg['country'], bot.acting = human, None
                    bot.write(oid, 'Chat', annex(bot, country, target, forced=getattr(bot, 'ordered', False)))
                elif a['kind'] == 'territorio':      # region names, not resource amounts
                    names = lambda v: [r.strip() for r in (v or '').split(',') if r.strip()]
                    # what the nation gives is handed over at once (event action); what it asks for stays a
                    # proposal (the other side decides), as does anything the game didn't move
                    offer = give_regions(bot, oid, names(a.get('offer')), target, country)
                    if offer or names(a.get('request')):
                        bot.propose('territorio', target, offer, names(a.get('request')))
                elif event_outcome(bot, oid, a, country, target, human, new):
                    pass        # applied as the scenario events do it (reported in the chat)
                else:
                    offer, request = (game_resources(bot, oid, _res(a.get(k))) for k in ('offer', 'request'))
                    kind = 'comercio' if a['kind'] == 'ayuda' and offer and request else a['kind']   # something back
                    if kind in ('comercio', 'ayuda') and not (offer or request or a.get('money')):
                        bot.write(oid, 'Chat', '%s: tratado de %s sin recursos válidos; no se envía.' % (country, kind))
                        continue
                    mark = treaty_mark(bot, target) if target != human and kind in PACT_ES else -1
                    bot.propose(kind, target, offer, request, a.get('money') or 0, a.get('war_id'))
                    if target != human:      # a CPU target answered at once: did it agree?
                        check_pact(bot, oid, kind, country, target, mark)
            elif c['name'] == 'ai_profile':
                keys = dict(zip(('doctrine', 'posture', 'aggressive', 'involvement', 'science', 'domestic'), AI_KNOBS))
                done = bot.set_knobs(country, {keys[k]: v for k, v in a.items() if k in keys and isinstance(v, int)})
                if done:
                    bot.write(oid, 'Chat', '%s: %s.' % (country, '; '.join(done)))
            elif c['name'] == 'relations':
                bot.cfg['country'], bot.acting = country, country
                bot.improve_relations(human, bool(a.get('worsen')))
            elif c['name'] == 'demand':
                add_demand(bot, oid, country, human, a)
            elif c['name'] == 'remember':
                remember(bot, country, a.get('note', ''))
            elif c['name'] == 'surrender':
                victor = bot.country_name(a['victor']) if a.get('victor') else human
                bot.write(oid, 'Chat', surrender(bot, oid, country, victor, human, a.get('regions') or ''))
            elif c['name'] == 'command' and ((a.get('command') or '').strip().split()[0].lower() in LLM_BLOCKED + ('/independence',)
                                             or re.match(r'\s*/alliance\s+force', a.get('command') or '', re.I)):      # player-only
                bot.log('ignored_call', c)       # the player's own switches, never the nation's
                continue
            elif c['name'] == 'command' and (a.get('command') or '').strip().startswith('/'):
                # the nation agreed: the same handlers as the player's commands; the result line shows in the chat
                cmd = a['command'].strip()
                if re.match(r'/(nonaggression|access|alliance\s+join)\b', cmd, re.I):
                    other = [n for n in bot.named(cmd) if n != country]
                    asked = bool(other) and other[0] in bot.named(' '.join(new))      # the player asked for it
                    if other and other[0] != human and not getattr(bot, 'ordered', False) and not asked:
                        # a pact with a third nation (e.g. joining NATO) opens votes and popups across the game
                        bot.log('ignored_call', dict(c, reason='third-party pact'))
                        continue
                    if pact_with_ally(bot, oid, c, country, (other or [human])[0]):
                        continue
                cmd = fix_actor(bot, cmd, country, human)
                move = re.match(r'/troops\s+move\s+(\S+)\s+(.+?)(?:\s+(\d+))?$', cmd, re.I)
                if move and not move.group(3):      # no number would send EVERY army (and leave home empty)
                    cmd += ' %d' % DEPLOY_ARMIES
                join = re.match(r'/alliance\s+join\b', cmd, re.I)
                partner = ([n for n in bot.named(cmd) if n != country] or [human])[0] if join else None
                pact = re.match(r'/(peace|trade|nonaggression|access)\b', cmd, re.I)
                pact_kind = {'peace': 'paz', 'trade': 'comercio', 'nonaggression': 'no_agresion',
                             'access': 'acceso_militar'}.get(pact.group(1).lower()) if pact else None
                other = ([n for n in bot.named(cmd) if n != country] or [human])[0]
                mark = treaty_mark(bot, other) if pact_kind and other != human else -1
                if join:      # a vote of every member: relations, votes and the real result
                    reply = alliance_join(bot, oid, country, partner, human, a.get('relations'),
                                          lambda: command(bot, oid, human, cmd, as_country=country),
                                          bot.members(oid) + bot.named(' '.join(new)) + [human])
                else:
                    reply = command(bot, oid, human, cmd, as_country=country)
                if move and not FAILED.search(reply or ''):
                    deploy(bot, country, move.group(2), int(move.group(3) or DEPLOY_ARMIES))
                if pact_kind and other != human and not FAILED.search(reply or ''):
                    check_pact(bot, oid, pact_kind, country, other, mark)
            bot.log('did', c)
        except Exception as e:          # report it and go on: the chat must not stop
            bot.log('act_error', {'call': c, 'error': str(e)[:300]})
            notes.append('%s: error %s' % ((c.get('args') or {}).get('country', ''), str(e)[:150]))
            if isinstance(e, Refused):      # the chat says why nothing was sent
                write(oid, 'Chat', str(e))
        finally:
            bot.cfg['country'], bot.acting = human, None
            bot.__dict__.pop('write', None)


FAILED = re.compile(r'error|no se env|desconocid|solo puedo|ya son aliados|no declara|ningún|no tiene|unknown|'
                    r'not sent|no pude', re.I)


def reword(bot, system, says, failed):
    """One more LLM request, only when a move failed: the nations' say lines rewritten so they don't claim what
    didn't happen. Falls back to the original lines."""
    import ai_chat
    tool = [t for t in TOOLS if t['name'] == 'say']
    text = ('Estas jugadas NO se hicieron o fallaron:\n%s\n\nReescribe estas respuestas para que no afirmen lo que no '
            'pasó (pueden explicar el problema o proponer otra cosa), con la herramienta say, en %s:\n%s') % (
        '\n'.join(failed), bot.cfg['language_name'],
        '\n'.join('%s: %s' % (s['args'].get('country'), s['args'].get('text')) for s in says))
    try:
        r = ai_chat.chat(system, [{'role': 'user', 'text': text}], tool)
        new = [c for c in r.get('calls') or [] if c['name'] == 'say' and (c.get('args') or {}).get('country')]
        bot.log('llm_out', {'calls': new, 'reword': True})
        return new or says
    except Exception as e:
        bot.log('act_error', {'reword': str(e)[:200]})
        return says


PACTS = ('alianza', 'no_agresion', 'acceso_militar')
# PlayerData values the CPU AI plans with (scenario files: player<Country>.xml; seen 1-25)
AI_KNOBS = {'nMilitaryDoctrine': 'doctrina militar', 'nMilitaryPosture': 'postura militar',
            'nAggressiveNature': 'agresividad', 'nInternationalInvolvement': 'implicación internacional',
            'nSciencePolicy': 'política científica', 'nDomesticPolicy': 'política interior'}


def pact_with_ally(bot, oid, call, country, target):
    """True (and a note in the chat) when 'country' and 'target' are already in one alliance: the game shows such
    a non-aggression / access / alliance offer as a broken popup (unresolved SID text, doubled buttons)."""
    saved = bot.cfg['country'], bot.acting
    bot.cfg['country'], bot.acting = country, country        # war_sides / country_id are 'ours' = the acting nation
    try:
        allied = str(bot.country_id(target)) in bot.war_sides()[0]
    finally:
        bot.cfg['country'], bot.acting = saved
    if allied:
        bot.write(oid, 'Chat', '%s y %s ya son aliados: ese pacto no hace falta.' % (country, target))
        bot.log('ignored_call', dict(call, reason='already allies'))
    return allied


LLM_BLOCKED = ('/yesman', '/order', '/orden', '/chat', '/help', '/ayuda', '/parlanchin', '/chatty', '/advisor',
               '/summit', '/editor')

HELP = ('En el chat general, nombra un país y su líder te responde. /chat Francia o /chat @Francia @Italia abre un '
        'chat con esos países (nombres de varias palabras: Reino_Unido); dentro de un chat, @país lo suma. Los países del '
        'chat pueden responder, proponerte tratados o cambiar su relación contigo. Comandos: /order <país> <orden> (p. ej. /order Australia declara guerra a Nueva Zelanda: ese país '
        'obedece), /yesman on | /yesman off (aceptan todo lo que pidas),/relations improve <país> <país> '
        '(a 800), /relations reset <país> <país> (a 500), /relations set <país> <país> <0-1000>, '
        '/advisor military|economy|diplomacy [pregunta] (tu asesor, con tus datos reales), /summit @país @país ... '
        '(cumbre: los líderes hablan entre ellos y pueden cerrar un acuerdo), /editor <frase> (solo con /yesman on y '
        'el anfitrión: la convierte en jugadas del juego, p. ej. /editor dale las Malvinas a Argentina), /merge <país que '
        'se une> <país al que se une> (le cede todas sus regiones; sin yesman hace falta relación 900+), '
        '/surrender <país> <vencedor> [región, ...] (anfitrión: se rinde, sale de su alianza, firma la paz, entra en la '
        'del vencedor y le cede regiones), /alliance force <país> <país> (anfitrión: el primero entra ya en la alianza '
        'del segundo, sin propuesta ni votación), /help.')


CODE = {f: os.path.getmtime(f) for f in (os.path.abspath(__file__), os.path.abspath(ai_player.__file__))}


def check_code():
    if any(os.path.getmtime(f) != t for f, t in CODE.items()):
        print('El código cambió: reiniciando SP Chat...', flush=True)
        raise SystemExit(RESTART)          # 'SP Chat.bat' starts it again (new code, same game)


TYPED = queue.Queue()      # lines typed in the SP Chat window


def read_console():
    """Thread: every line typed in the SP Chat window goes to TYPED (run() writes it in the game chat)."""
    for line in sys.stdin:
        if line.strip():
            TYPED.put(line.strip())


def typed_in(bot, chats, seen):
    """Lines typed in the SP Chat window: written in the chat in use as the host, answered at once, and the
    answers printed in the window too (the game's chat bar often loses focus or the connection)."""
    while chats and not TYPED.empty():
        text = TYPED.get()
        oid = bot._active_chat if getattr(bot, '_active_chat', None) in chats else chats[0]
        bot.write(oid, bot.host, text)
        before = len(bot.chat_lines(oid))
        handle_chat(bot, oid, seen)
        bot._active_chat = oid
        for who, said in bot.chat_lines(oid)[before:]:
            print('%s: %s' % (who, said), flush=True)


def run(bot, steps=None, seen=None):
    """Main loop. steps: number of rounds (tests); seen: {chat id: lines already handled} (default: all so far)."""
    if seen is None:      # the history before we started is not new, except the humans' lines nobody answered yet
        seen = {}
        for oid in bot.all_chats():
            lines = bot.chat_lines(oid)
            done = next((i + 1 for i in range(len(lines) - 1, -1, -1) if lines[i][0] not in bot.humans()), 0)
            seen[oid] = mark(lines[:done])
    bot.log('ready', {'host': bot.host, 'humans': sorted(bot.humans()), 'chats': len(seen)})
    # Every game command runs inside one game frame: idle, few and small reads (the chat texts), the rest spaced
    # out; quick polling only while people are talking.
    t = {'active': 0, 'game': time.time(), 'busy': 0, 'bg': 0, 'rate': time.time(), 'eot': 0, 'rr': 0}
    count = getattr(bot.con, 'count', 0)
    while steps is None or steps > 0:
        if steps is None:
            check_code()
        steps = None if steps is None else steps - 1
        now = time.time()
        try:
            if now - t['eot'] > 12:
                t['eot'] = now
                if bot.eot():    # the turn is ending: one flag every few seconds and no other game command
                    t['busy'], t['eot'] = 0, 0      # then the new turn number is read at once
                    time.sleep(6)
                    continue
            if steps is None and now - t['game'] > 30:
                t['game'] = now
                if not bot.in_game():
                    print('Saliste de la partida. Esperando a que entres en otra...', flush=True)
                    return
            idle = now - t['active'] > 60
            if now - t['busy'] > (60 if idle else 30):       # the turn number (background follows turns)
                t['busy'] = now
                bot._turn = bot.prop(bot.gs(), 'nCurrentTurn') or getattr(bot, '_turn', None)
            # each chat read returns its whole text: only the chat people are talking in, plus one other chat
            # per tick in turn (6 open chats used to cost 6 reads every 1.5 s)
            chats = bot.all_chats()
            active = getattr(bot, '_active_chat', None) if not idle else None
            read = [active] if active in chats else []
            others = [c for c in chats if c not in read]
            if others and now - t['rr'] >= (bot.cfg.get('idle_poll_seconds', 6) if idle else 12):
                t['rr'] = now
                bot._rr = getattr(bot, '_rr', -1) + 1
                read.append(others[bot._rr % len(others)])
            for o in getattr(bot, 'closed_chats', ()):
                seen.pop(o, None)
            notes = bot.__dict__.pop('error_notes', [])
            if notes and chats:
                bot.write(bot._active_chat if getattr(bot, '_active_chat', None) in chats else chats[0], 'Chat',
                          ' '.join(notes))
            typed_in(bot, chats, seen)
            for oid in read:
                if handle_chat(bot, oid, seen):
                    t['active'], bot._active_chat = time.time(), oid
            if now - t['bg'] > bot.cfg.get('background_seconds', 6):
                t['bg'] = now
                bot.con.pace = 0.1
                try:
                    background(bot)
                finally:
                    bot.con.pace = 0
        except OSError:
            raise                          # the game was closed
        except Exception as e:             # a bad read or action: report it, the chat goes on
            bot.log('act_error', {'round': repr(e)[:300]})
        finally:
            if bot.__dict__.get('_pool'):
                bot.flush_actions()        # background's actions too: nothing of ours left in the list
        if now - t['rate'] >= 60 and hasattr(bot.con, 'count'):
            bot.log('cli_rate', {'per_min': round((bot.con.count - count) * 60 / (now - t['rate']))})
            t['rate'], count = now, bot.con.count
        idle = time.time() - t['active'] > 60
        time.sleep(bot.cfg.get('idle_poll_seconds', 6) if idle else max(5, bot.cfg['poll_seconds']))


RELATIONS_GOOD, RELATIONS_RESET = 800, 500     # the game's scale is 0-1000 (500 = neutral start)


def relation_word(v):
    """A plain reading of a 0-1000 relation for the LLM (the game's own state thresholds aren't known)."""
    return ('hostil' if v < 250 else 'mala' if v < 450 else 'neutral' if v < 600 else 'buena' if v < 800
            else 'muy estrecha')


def relation(bot, a, b):
    """(country id of a, a's relation towards b): the game's report of a, read once per turn (memo; our own
    relation actions drop it), and the id from country_id (kept)."""
    out = bot.memo(('rel', a), lambda: bot.report('relaciones', a)) if hasattr(bot, 'memo') else bot.report('relaciones', a)
    val = re.search(r'(?m)^\s*%s\s+(\d+)\s*$' % re.escape(b), out)
    cid = bot.country_id(a)
    if cid < 0:
        raise RuntimeError('no encuentro el país %s' % a)
    return cid, int(val.group(1)) if val else 500      # a neutral relation (500) isn't listed in the report


def exact_nations(bot, words):
    """Game names for the words (exact names or Spanish aliases only: no close matches for a direct edit), or the
    error text for the first unknown one."""
    low, found = {n.lower(): n for n in bot.nations()}, []
    for raw in words:
        hit = low.get(raw.lower()) or bot.ALIASES.get(norm(raw)) or squashed(bot, raw)
        if hit not in bot.nations():
            return 'No conozco el país «%s».' % raw
        found.append(hit)
    return found


def split_args(args):
    import shlex
    try:
        return [w.replace('_', ' ') for w in shlex.split(args)]
    except ValueError:
        return args.split()


GOV_ES = {'Democratic': 'democracia', 'Authoritarian': 'autoritarismo', 'Fascist': 'fascismo',
          'Communist': 'comunismo', 'Despotist': 'despotismo'}


def gov_type(bot, country):
    return bot.prop(bot.obj_id(bot.prop(bot.nations()[country], 'objCountry') or ''), 'strGovType')


MERGE_MIN = 900     # relation (of 1000) both ways needed for a nation to offer to join another


def annex(bot, a, b, forced=False):
    """'a' offers to join 'b': a territorial transfer of all of a's regions, sent by a (the game's own treaty,
    which b accepts or not). Without yesman / an order, only between nations at MERGE_MIN or more both ways."""
    if a == b:
        return 'Indica dos países distintos.'
    if not forced:
        low = min(relation(bot, a, b)[1], relation(bot, b, a)[1])
        if low < MERGE_MIN:
            return '%s no se une a %s: la relación es %d de 1000 (hace falta %d).' % (a, b, low, MERGE_MIN)

    def regions():
        country = bot.obj_id((bot.prop(bot.player(), 'objCountry') or ''))
        return [bot.prop(r, 'strName') for r in bot.refs(country, 'objRegions')]
    names = [n for n in bot.as_nation(a, regions) if n]
    if not names:
        return '%s no tiene regiones que ceder.' % a
    bot.as_nation(a, lambda: bot.propose('territorio', b, names, []))
    return '%s propone unirse a %s: le cede sus %d regiones (%s).' % (a, b, len(names), ', '.join(names[:8]) +
                                                                     (', ...' if len(names) > 8 else ''))


def ideology_align(bot, args):
    """'/ideology align A B': A takes B's current government type, with the game's own ActSetCountryGov sent by A
    (so the game runs its usual effects of a change of regime)."""
    words = split_args(args)
    if len(words) != 2:
        return 'Uso: /ideology align <país que cambia> <país modelo> (p. ej. /ideology align Francia Alemania).'
    found = exact_nations(bot, words)
    if isinstance(found, str):
        return found
    a, b = found
    ga, gb = gov_type(bot, a), gov_type(bot, b)
    if not gb:
        return 'No pude leer la ideología de %s.' % b
    if ga == gb:
        return '%s ya tiene la misma ideología que %s (%s).' % (a, b, GOV_ES.get(gb, gb))
    acting, country = bot.acting, bot.cfg['country']
    bot.acting = bot.cfg['country'] = a
    try:
        bot.send_action('ActSetCountryGov', {'strCountry': a, 'strGovType': gb})
    finally:
        bot.acting, bot.cfg['country'] = acting, country
    now = gov_type(bot, a)
    if now != gb:
        return 'El juego no aplicó el cambio: %s sigue con %s.' % (a, GOV_ES.get(now, now))
    return '%s adopta la ideología de %s: %s (antes %s).' % (a, b, GOV_ES.get(gb, gb), GOV_ES.get(ga, ga))


def set_relations(bot, how, args):
    """'/relations improve|reset|set A B [N]': sets the relation between A and B, both ways, to 800 / 500 / N, with
    the game's ActIncDipRelations (it adds an amount, so the current value is read first)."""
    words = split_args(args)
    want = RELATIONS_GOOD if how == 'improve' else RELATIONS_RESET
    if how == 'set':
        if not words or not words[-1].lstrip('-').isdigit():
            return 'Uso: /relations set <país> <país> <0-1000>'
        want = int(words.pop())
        if not 0 <= want <= 1000:
            return 'El valor debe estar entre 0 y 1000 (500 es neutral).'
    if len(words) != 2:
        return 'Uso: /relations %s <país> <país>%s (nombres de varias palabras con comillas o _).' % (
            how, ' <0-1000>' if how == 'set' else '')
    found = exact_nations(bot, words)
    if isinstance(found, str):
        return found
    a, b = found
    if a == b:
        return 'Indica dos países distintos.'
    return 'Relaciones: %s.' % '; '.join(set_pair(bot, a, b, want))


def set_pair(bot, a, b, want, floor=False):
    """Sets a→b and b→a to 'want' (floor=True: only raises a value below it). Returns the 'X→Y de N a M de 1000'
    lines of the values that changed (all of them when floor is False)."""
    done = []
    (aid, ab), (bid, ba) = relation(bot, a, b), relation(bot, b, a)      # read both first: 2 reports, no re-reads
    for (x, y, xid, yid, cur) in ((a, b, aid, bid, ab), (b, a, bid, aid, ba)):
        if floor and cur >= want:
            continue
        if want != cur:
            bot.send_action('ActIncDipRelations', {'nSourceCountryID': xid, 'nTargetCountryID': yid,
                                                   'nAmount': want - cur})
        now = max(0, min(1000, want))
        done.append('%s→%s de %d a %d de 1000 (%s)' % (x, y, cur, now, relation_word(now)))
    return done


ALLIANCE_FLOOR, ALLIANCE_TOP, VOTE_FLOOR = 500, 800, 750     # relation range (of 1000) set when an alliance is accepted


def alliance_members(bot, name, hint=()):
    """Names of the members of the alliance 'name' belongs to ([] if none). Member ids are named from
    _country_ids, else the member's strINITCountryName, else by asking the game the id of each nation in 'hint'
    (the chat's, the message's): no full scan of every nation."""
    cid = str(bot.country_id(name))
    ids = {str(v): k for k, v in (getattr(bot, '_country_ids', None) or {}).items()}
    for _, member_ids, objs in bot.alliance_map().values():
        if cid not in member_ids:
            continue
        ms = [bot.fixed(m) for m in objs]
        ids[cid] = name
        missing = {m.get('nCountryID') for m in ms} - set(ids)
        for n in hint:
            if not missing:
                break
            i = str(bot.country_id(n))
            if i in missing:
                ids[i] = n
                missing.discard(i)
        nations = bot.nations()
        # a game log line can land in a read value ('CMapObjectSprite::... error'): only real nation names
        out = [n if n in nations else None for n in
               (ids.get(m.get('nCountryID')) or m.get('strINITCountryName') for m in ms)]
        if None in out:
            bot.log('act_error', {'alliance_members': name, 'unnamed': sorted(missing)})
        return [n for n in out if n]
    return []


def answer_votes(bot, members, joiner, tries=2):
    """The alliance vote a join opens: each CPU member's open 'Generic_TreatyProposed' decision point answered
    with its accept choice, as that member (ActSelectDPChoice through its avatar). The CPU AI may already have
    voted; then nothing is open. Returns the members that voted here."""
    voted, cpus = [], bot.cpus()
    for i in range(tries):
        for m in members:
            if m == joiner or m not in cpus or m in voted:
                continue
            for p in bot.as_nation(m, bot.popups):
                yes = next((o for o in p['opciones'] if o and re.search(r'accept|yes|agree|aprob', o, re.I)), None)
                if p['tipo'].startswith('Generic_TreatyProposed') and yes:
                    bot.as_nation(m, lambda: bot.answer_popup(p['id'], yes))
                    voted.append(m)
                    bot.log('did', {'vote': p, 'as': m, 'choice': yes})
        if i < tries - 1:
            time.sleep(1)      # the vote may open a frame later
    return voted


def allied(bot, a, b):
    return str(bot.country_id(b)) in bot.as_nation(a, lambda: bot.war_sides()[0])


def alliance_force(bot, oid, human, a, b):
    """'/alliance force <a> <b>' (host only): a joins b's alliance at once with ActDevFormDefensePact, no
    proposal and no vote, whatever force_actions says. Not when a is already in another alliance (a merge)."""
    if human != bot.host:
        return '/alliance force solo lo puede usar el anfitrión de la partida (%s).' % bot.host
    found = exact_nations(bot, [a.replace('_', ' '), b.replace('_', ' ')])
    if isinstance(found, str):
        return found
    a, b = found
    if a == b:
        return 'Indica dos países distintos.'
    if allied(bot, a, b):
        return '%s y %s ya son aliados.' % (a, b)
    if alliance_members(bot, a):
        return '%s ya está en otra alianza: primero tiene que salir (/alliance leave %s).' % (a, a)
    if force_alliance(bot, a, b, explicit=True):
        return 'Hecho: %s entra en la alianza de %s (forzada, sin votación).' % (a, b)
    return 'El juego no aplicó la alianza forzada de %s con %s.' % (a, b)


def force_alliance(bot, joiner, target, explicit=False):
    """The alliance the chat agreed on, made at once: the game's developer action ActDevFormDefensePact
    (DEVactionDefs.xml, loaded in MH1 and Gold: an ActProposeTreatyDef whose treaty is already TREATY_RATIFIED,
    so no proposal and no vote), sent as the joiner like a scenario event's action. True if they are allied
    afterwards. shortcut: not tried live yet; if the game ignores it, alliance_join falls back to the vote.
    Never when the joiner is already in another alliance: that's an alliance merge, which the game logs as
    'CPlayEventAllianceMerge::GetMergedAlliance - NULL alliance'; only the game's own vote does it."""
    if not (explicit or bot.cfg.get('force_actions')):      # explicit: the host's own /alliance force
        return False
    if alliance_members(bot, joiner):
        bot.log('ignored_call', {'force_alliance': [joiner, target], 'reason': 'joiner already in an alliance'})
        return False
    try:
        bot.as_nation(joiner, lambda: bot.send_action('ActDevFormDefensePact',
                                                      {'strFromCountry': joiner, 'strToCountry': target}))
    except Exception as e:      # e.g. the action can't be created in this game: the usual proposal
        bot.log('act_error', {'force_alliance': [joiner, target], 'error': str(e)[:200]})
        return False
    ok = allied(bot, joiner, target)
    bot.log('did' if ok else 'act_error', {'force_alliance': [joiner, target], 'allied': ok})
    return ok


def alliance_join(bot, oid, joiner, target, human, chosen, send, hint=()):
    """An alliance the chat agreed on, done so the game agrees: joining means a vote of EVERY member of target's
    alliance, so the relations joiner↔each member are raised first (ALLIANCE_FLOOR..ALLIANCE_TOP), the proposal
    is sent (send()), the CPU members' votes are answered with accept, and the result is checked and reported.
    A vote still open (the human's own, or one the game counts at the end of turn) is checked again at the next
    turn (verify_pacts)."""
    members = [m for m in alliance_members(bot, target, hint) if m != joiner] or [target]
    acting, country = bot.acting, bot.cfg['country']
    bot.cfg['country'], bot.acting = human, None
    try:
        for m in members:
            # 500 is only 'neutral': the CPU members vote at once, and voted no at that level
            alliance_floor(bot, oid, joiner, m, max(int(chosen or 0) if str(chosen or 0).isdigit() else 0, VOTE_FLOOR))
    finally:
        bot.cfg['country'], bot.acting = country, acting
    if force_alliance(bot, joiner, target):
        bot.write(oid, 'Chat', 'Hecho: %s entra en la alianza con %s.' % (joiner, ', '.join(members)))
        return 'Hecho: alianza %s - %s.' % (joiner, target)
    out = send()      # the game didn't take the forced pact: the usual proposal and its vote
    if FAILED.search(out or ''):
        return out
    voted = answer_votes(bot, members, joiner)
    if allied(bot, joiner, target):
        bot.write(oid, 'Chat', 'Hecho: %s entra en la alianza con %s.' % (joiner, ', '.join(members)))
    else:
        bot.write(oid, 'Chat', 'Votación de la alianza en curso (miembros: %s%s); confirmaré el resultado en el '
                               'próximo turno.' % (', '.join(members), '; votaron sí: ' + ', '.join(voted) if voted else ''))
        bot.__dict__.setdefault('_pending_pacts', []).append(
            {'kind': 'alianza', 'a': joiner, 'b': target, 'oid': oid, 'turn': bot.turn()})
    return out


def pact_ok(bot, kind, a, b, mark):
    """Whether a pact a proposed to b exists in the game now: peace = no longer at war; the others = a treaty
    between them newer than 'mark' (treaty_mark of b before the proposal)."""
    if kind == 'paz':
        return str(bot.country_id(b)) not in bot.as_nation(a, lambda: bot.war_sides()[1])
    if kind == 'alianza':
        return str(bot.country_id(b)) in bot.as_nation(a, lambda: bot.war_sides()[0])
    return any(int(t.get('nTreatyID') or -1) > mark and {t.get('strFromCountry'), t.get('strToCountry')} == {a, b}
               for t in treaties(bot, b))


PACT_ES = {'paz': 'la paz', 'comercio': 'el comercio', 'no_agresion': 'el pacto de no agresión',
           'acceso_militar': 'el acceso militar', 'alianza': 'la alianza'}


def verify_pacts(bot):
    """At a new turn: the pacts whose vote was still open are checked, and the real result goes to the chat."""
    for p in bot.__dict__.pop('_pending_pacts', []):
        try:
            ok = pact_ok(bot, p['kind'], p['a'], p['b'], p.get('mark', -1))
            bot.write(p['oid'], 'Chat', ('Confirmado: %s entre %s y %s ya rige.' if ok else
                                         'Error: %s entre %s y %s no se formó en el juego.') % (
                PACT_ES.get(p['kind'], p['kind']), p['a'], p['b']))
        except Exception as e:
            bot.log('act_error', {'verify_pact': p, 'error': str(e)[:200]})


def check_pact(bot, oid, kind, a, b, mark):
    """After a CPU-to-CPU peace / trade / pact (the target's AI answers at once): the chat says if the game
    refused it, so chat and game never disagree."""
    if kind in PACT_ES and kind != 'alianza' and not pact_ok(bot, kind, a, b, mark):
        bot.write(oid, 'Chat', 'Error: %s entre %s y %s no aparece en el juego (%s no lo aceptó).' % (
            PACT_ES[kind], a, b, b))


def alliance_floor(bot, oid, a, b, chosen=None):
    """An accepted alliance: the relation a↔b is at least 500 of 1000 (or the higher value the LLM chose), never
    lowered. The change is reported in the chat."""
    try:
        want = max(ALLIANCE_FLOOR, min(ALLIANCE_TOP, int(chosen or 0)))
    except (TypeError, ValueError):
        want = ALLIANCE_FLOOR
    done = set_pair(bot, a, b, want, floor=True)
    if done:
        reply = 'Relaciones: %s.' % '; '.join(done)
        bot.write(oid, 'Chat', reply)
        bot.log('did', {'alliance_floor': [a, b, want], 'reply': reply})


TR_CACHE = {}      # Spanish text -> translation (HELP and the usage lines repeat)


def tr(bot, text):
    """The code's Spanish chat lines (command replies, usage, notes) in the chat language: one small LLM request
    per new text, cached; the original text on any error or when the language is Spanish."""
    lang = (bot.cfg.get('language') or '').strip()
    if not text or not lang or norm(lang).startswith(('es', 'spanish')):
        return text
    if text not in TR_CACHE:
        try:
            calls, plain = llm(bot, 'Translate the user text to %s. Keep country, region and resource names, numbers '
                                    'and /commands exactly as they are. Answer with say, the translation only.' % lang,
                               text, [SAY])
            TR_CACHE[text] = said(calls, plain) or text
        except Exception as e:
            bot.log('act_error', {'translate': str(e)[:200]})
            return text
    return TR_CACHE[text]


def resource_name(raw, names):
    """The game's resource name for what the LLM wrote ('Metal', 'metrals' -> 'Metals'): case, spaces, plural
    's', then the closest match; None if nothing is close."""
    import difflib
    flat = lambda s: norm(s).replace(' ', '').replace('_', '')
    low = {flat(n): n for n in names}
    low.update({k.rstrip('s'): n for k, n in list(low.items())})
    key = flat(raw)
    for k in (key, key.rstrip('s')):
        if k in low:
            return low[k]
    m = difflib.get_close_matches(key, list(low), n=1, cutoff=0.7)
    if m:
        return low[m[0]]
    same = {n for k, n in low.items() if len(key) >= 4 and k[:4] == key[:4]}     # 'Metallurgy' -> 'Metals'
    return same.pop() if len(same) == 1 else None


_RES = ['Metals', 'Food', 'Coal', 'Oil', 'Consumer Goods']
assert [resource_name(r, _RES) for r in ('Metal', 'metrals', 'FOOD', 'coals', 'consumer_goods', 'unobtainium', 'Metallurgy')] == [
    'Metals', 'Metals', 'Food', 'Coal', 'Consumer Goods', None, 'Metals']


def regions_line(bot, country, cap=20):
    """'Regiones de Israel (destino de tropas): Palestine, ...; mares junto a ellas: Eastern Mediterranean, ...' from
    the scenario map. shortcut: owners at the scenario's start (Bot.region_owners), not later conquests."""
    cache = bot.__dict__.setdefault('_regions_line', {})
    if country not in cache:
        names, owners = bot.land_map()[0], bot.region_owners()
        mine = [names[i] for i, o in owners.items() if o == country and names[i]]
        seas = sorted({s for r in mine for s in bot.seas_near(r)})
        cache[country] = ('Regiones de %s (destino de tropas: /troops move <país> <región>): %s; mares junto a ellas '
                          '(destino de flotas: /troops move <país> <mar>): %s' % (country, ', '.join(mine[:cap]) + (' ...' if len(mine) > cap else ''),
                                                       ', '.join(seas[:cap]) or 'ninguno'))
    return cache[country]


def resource_names(bot):
    """The game's resource names, from a Country's objResources (read once)."""
    if not getattr(bot, '_resource_names', None):
        country = bot.obj_id(bot.prop(bot._me(), 'objCountry') or '')
        bot._resource_names = [n for n in (bot.prop(r, 'strName') for r in bot.refs(country, 'objResources')) if n]
    return bot._resource_names


def game_resources(bot, oid, wanted):
    """{LLM name: amount} -> {game name: amount}; unknown names are reported in the chat and left out. The names
    come from a Country's objResources, read once."""
    if not wanted:
        return {}
    resource_names(bot)
    out, unknown = {}, []
    for raw, n in wanted.items():
        name = resource_name(raw, bot._resource_names)
        if name:
            out[name] = out.get(name, 0) + int(n)
        else:
            unknown.append(raw)
    if unknown:
        bot.write(oid, 'Chat', 'Recursos desconocidos: %s (los del juego: %s).' % (
            ', '.join(unknown), ', '.join(bot._resource_names)))
    return out


def nospace_nations(text, nations):
    """Multi-word nation names without spaces, like the game's internal names ('United States' -> 'UnitedStates':
    chat_command splits on spaces; country_name / squashed() resolve them back), longest names first."""
    for n in sorted((n for n in nations if ' ' in n), key=len, reverse=True):
        text = re.sub(r'(?<![\w])%s(?![\w])' % re.escape(n), n.replace(' ', ''), text, flags=re.I)
    return text


assert nospace_nations('/troops move United States Israel', ['United States', 'Israel', 'United Arab Emirates']) \
    == '/troops move UnitedStates Israel'
assert nospace_nations('/aid x "united arab emirates"', ['United States', 'United Arab Emirates']) \
    == '/aid x "UnitedArabEmirates"'


def fix_actor(bot, cmd, country, human):
    """An LLM command whose first nation isn't the one acting ('/aid UnitedStates Ukraine' sent by Ukraine) gets
    the acting nation first; if that leaves it targeting itself, the target becomes the player."""
    words = cmd.split()
    pos = [i for i, w in enumerate(words[1:], 1) if squashed(bot, w.strip('"'))]
    if not pos or squashed(bot, words[pos[0]].strip('"')) == country:
        return cmd
    words[pos[0]] = country.replace(' ', '')
    if len(pos) > 1 and squashed(bot, words[pos[1]].strip('"')) == country:
        words[pos[1]] = human.replace(' ', '')
    return ' '.join(words)


def squashed(bot, raw):
    """The game name for 'UnitedStates', 'united_states', 'ReinoUnido'... (ai_player.squash: no case, accents,
    spaces or underscores), over the nation names and the Spanish aliases; None if none matches."""
    if '_squashed' not in bot.__dict__:
        bot._squashed = {ai_player.squash(k): v for k, v in bot.ALIASES.items()}
        bot._squashed.update({ai_player.squash(n): n for n in bot.nations()})
    hit = bot._squashed.get(ai_player.squash(raw or ''))
    return hit if hit in bot.nations() else None


assert squashed(types.SimpleNamespace(ALIASES={'reino unido': 'United Kingdom'}, nations=lambda: ['United States',
                                      'United Kingdom']), 'ReinoUnido') == 'United Kingdom'
assert squashed(types.SimpleNamespace(ALIASES={}, nations=lambda: ['United States']), 'unitedstates') == 'United States'


def owned_regions(bot, country, want=None):
    """nRegionIDs the nation owns now: its Country's objRegions (small reads, each region object's id kept for
    good). want: the region ids asked about; reading stops once they are all found (a big nation has 100+)."""
    c = bot.obj_id((bot.prop(bot.nations()[country], 'objCountry') or ''))
    ids, out, want = bot.__dict__.setdefault('_region_ids', {}), set(), set(want or ())
    regions = bot.refs(c, 'objRegions')
    for r in sorted(regions, key=lambda r: r not in ids):      # the ones already known first: no reads
        if want and want <= out:
            break
        if r not in ids:
            ids[r] = int(bot.prop(r, 'nRegionID') or -1)
        out.add(ids[r])
    return out


def give_regions(bot, oid, regions, to, frm):
    """Regions of 'frm' handed to 'to' at once with the scenario events' ActTransferRegionOwnership (no proposal
    for the other side's AI to reject); each one checked in the game afterwards and the moves reported. Returns
    the regions not moved (the caller proposes those). A region 'frm' doesn't own is never moved."""
    names, left, done = bot.land_map()[0], [], []
    if not regions or not bot.cfg.get('event_actions', True):
        return list(regions or [])      # the caller proposes them
    own = owned_regions(bot, frm, {bot.region_id(r) for r in regions if r})
    for r in regions:
        try:
            idx = bot.region_id(r)
            if idx not in own:
                left.append(r)
                continue
            acting, bot.acting = bot.acting, None
            try:
                bot.send_action('ActTransferRegionOwnership', {'nRegionID': idx, 'nNewCountryID': bot.country_id(to)})
            finally:
                bot.acting = acting
            (done if idx in owned_regions(bot, to, {idx}) else left).append(names[idx] if idx < len(names) else r)
        except Exception as e:      # unknown region, unreadable owner...: the proposal path
            bot.log('act_error', {'give_region': [r, frm, to], 'error': str(e)[:200]})
            left.append(r)
    if done:
        bot.write(oid, 'Chat', 'Hecho: %s pasa%s de %s a %s.' % (', '.join(done), 'n' if len(done) > 1 else '', frm, to))
    return left


SCAN_CAP = 20     # regions / units one action looks at


def surrender_regions(bot, loser, victor):
    """Default cession of a surrender: the loser's regions the victor occupies (nControllerID) or claims as
    historic. Never all its land (that is /merge)."""
    names, vid = bot.land_map()[0], str(bot.country_id(victor))
    claimed = set(historic(bot, victor)) if victor in bot.nations() else set()
    c = bot.obj_id(bot.prop(bot.nations()[loser], 'objCountry') or '')
    ids = bot.__dict__.setdefault('_region_ids', {})
    out = []
    for r in bot.refs(c, 'objRegions')[:SCAN_CAP]:      # shortcut: a big loser's other regions aren't looked at
        if r not in ids:
            ids[r] = int(bot.prop(r, 'nRegionID') or -1)
        name = names[ids[r]] if 0 <= ids[r] < len(names) else None
        if name and (name in claimed or bot.prop(r, 'nControllerID') == vid):
            out.append(name)
    return out


def surrender(bot, oid, loser, victor, human, regions=''):
    """'loser' surrenders to 'victor' (chat tool, /surrender, /order, /editor), each step checked in the game and
    reported: 1. it leaves its alliance (the alliance window's Break); 2. peace with the victor (the developer
    action ActDevMakePeace, else a peace proposal); 3. it joins the victor's alliance (alliance_join); 4. it cedes
    the regions listed, else those the victor occupies or claims (give_regions). Returns the report line."""
    if str(bot.country_id(victor)) not in bot.as_nation(loser, lambda: bot.war_sides()[1]):
        return '%s no está en guerra con %s: no hay rendición que firmar.' % (loser, victor)
    steps = []
    old = [m for m in alliance_members(bot, loser) if m != loser]
    if old:      # 1. Break with a member takes it out of its alliance
        bot.as_nation(loser, lambda: bot.propose('romper_alianza', old[0]))
        steps.append('sale de su alianza' if not alliance_members(bot, loser) else 'NO pudo salir de su alianza')
    a, b = bot.country_id(loser), bot.country_id(victor)       # 2. peace
    acting, bot.acting = bot.acting, None
    try:
        if not event_peace(bot, loser, victor) and bot.cfg.get('force_actions'):
            bot.send_action('ActDevMakePeace', {'nCountryAID': a, 'nCountryBID': b})
    except Exception as e:
        bot.log('act_error', {'surrender_peace': [loser, victor], 'error': str(e)[:200]})
    finally:
        bot.acting = acting
    if not pact_ok(bot, 'paz', loser, victor, -1):
        bot.as_nation(loser, lambda: bot.propose('paz', victor))
    at_peace = pact_ok(bot, 'paz', loser, victor, -1)
    steps.append('firma la paz con %s' % victor if at_peace else 'la paz con %s queda pendiente' % victor)
    if at_peace and alliance_members(bot, victor):      # 3. into the victor's alliance
        alliance_join(bot, oid, loser, victor, human, None, lambda: bot.as_nation(loser, lambda: bot.propose(
            'alianza', victor)), hint=[human, victor] + old)
        steps.append('entra en la alianza de %s' % victor if allied(bot, loser, victor)
                     else 'su entrada en la alianza de %s está en votación' % victor)
    listed = [r.strip().strip('"') for r in (regions or '').split(',') if r.strip()]
    cede = listed or surrender_regions(bot, loser, victor)      # 4. territory
    if cede:
        left = give_regions(bot, oid, cede, victor, loser)
        steps.append('cede %d región(es)%s' % (len(cede) - len(left), ' (no pasaron: %s)' % ', '.join(left) if left else ''))
    else:
        steps.append('no hay regiones ocupadas ni reclamadas que ceder')
    remember(bot, loser, 'se rindió ante %s' % victor)
    return 'Rendición de %s ante %s: %s.' % (loser, victor, '; '.join(steps))


def independence(bot, oid, frm, new, regions=''):
    """'/independence <from> <new nation> [region, region...]' (/editor, with /yesman on): the scenario events'
    ActGrantIndependence makes 'from' free 'new' (a nation the scenario defines: it gets its own regions), then
    the listed regions of 'from' are handed to it. Checked in the game: the new nation must own regions."""
    if not getattr(bot, 'yesman', False):
        return '/independence solo funciona con /yesman on.'
    if not bot.cfg.get('event_actions', True):
        return '/independence necesita event_actions: true en sp_chat.json.'
    found = exact_nations(bot, [frm.replace('_', ' '), new.replace('_', ' ')])
    if isinstance(found, str):
        return found + ' (la nación nueva tiene que existir en el escenario).'
    frm, new = found
    acting, bot.acting = bot.acting, None
    try:
        bot.send_action('ActGrantIndependence', {'strFromCountry': frm, 'strToCountry': new})
    finally:
        bot.acting = acting
    extra = [r.strip().strip('"') for r in regions.split(',') if r.strip()]
    left = give_regions(bot, oid, extra, new, frm) if extra else []
    try:
        held = len(owned_regions(bot, new))
    except Exception:          # no Player object for it: it does not exist in this game
        held = 0
    if not held:
        return 'El juego no creó %s (¿está definida en el escenario?).' % new
    return 'Hecho: %s se independiza de %s con %d regiones%s.' % (
        new, frm, held, '; no pasaron: %s' % ', '.join(left) if left else '')


def command(bot, oid, human, text, as_country=None):
    """A '/command' from the player: ai_player.chat_command, the same commands as in multiplayer (one source, so
    new ones reach both). '<yo>' is the CPU nation that acts (the first nation the command names; else the first
    CPU nation in this chat); it acts through its own avatar, obeying the player if allied with them or with
    /yesman on, as in multiplayer. The reply is written in the chat as that nation."""
    text = nospace_nations(text, bot.nations())      # '/troops move United States Israel' splits right
    if text.split()[0].lower() in ('/help', '/ayuda'):
        bot.write(oid, 'Chat', HELP + ' ' + ai_player.HELP.replace('<yo>', '<pais CPU>'))
        return
    m = re.match(r'/relations\s+(improve|reset|set)\b(.*)$', text.strip(), re.I)
    if m:
        reply = set_relations(bot, m.group(1).lower(), m.group(2))
        bot.write(oid, 'Chat', reply)
        bot.log('did', {'command': text, 'reply': reply})
        return reply
    m = re.match(r'/transfer\s+territory\s+(.+)\s+(\S+)\s*$', text.strip(), re.I)
    if m and as_country:      # the owner agreed: the region is handed over at once (else the usual proposal)
        to = bot.country_name(m.group(2).replace('_', ' '))
        if not give_regions(bot, oid, [m.group(1).replace('_', ' ').strip('"')], to, as_country):
            bot.log('did', {'command': text, 'as': as_country})
            return 'Hecho: transfer territory.'
    m = re.match(r'/alliance\s+force\s+(\S+)\s+(\S+)\s*$', text.strip(), re.I)
    if m:
        reply = alliance_force(bot, oid, human, m.group(1), m.group(2))
        bot.write(oid, 'Chat', reply)
        bot.log('did', {'command': text, 'reply': reply})
        return reply
    m = re.match(r'/surrender\s+(\S+)\s+(\S+)(.*)$', text.strip(), re.I)
    if m:
        found = exact_nations(bot, [m.group(1).replace('_', ' '), m.group(2).replace('_', ' ')])
        reply = found if isinstance(found, str) else surrender(bot, oid, found[0], found[1], human, m.group(3))
        bot.write(oid, 'Chat', reply)
        bot.log('did', {'command': text, 'reply': reply})
        return reply
    m = re.match(r'/independence\s+(\S+)\s+(\S+)(.*)$', text.strip(), re.I)
    if m:
        reply = independence(bot, oid, m.group(1), m.group(2), m.group(3))
        bot.write(oid, 'Chat', reply)
        bot.log('did', {'command': text, 'reply': reply})
        return reply
    m = re.match(r'/merge\b(.*)$', text.strip(), re.I)
    if m:
        found = exact_nations(bot, split_args(m.group(1)))
        if isinstance(found, str) or len(found) != 2:
            reply = found if isinstance(found, str) else 'Usage: /merge <country that joins> <country it joins>'
        else:
            reply = annex(bot, found[0], found[1], forced=bool(as_country) or getattr(bot, 'yesman', False))
        bot.write(oid, 'Chat', reply)
        bot.log('did', {'command': text, 'reply': reply})
        return reply
    m = re.match(r'/ideology\s+align\b(.*)$', text.strip(), re.I)
    if m:
        reply = ideology_align(bot, m.group(1))
        bot.write(oid, 'Chat', reply)
        bot.log('did', {'command': text, 'reply': reply})
        return reply
    named = [c for c in bot.named(text) if c in bot.cpus()]
    members = [m for m in bot.members(oid) if m in bot.cpus()]
    cpu = as_country or (named or members or [None])[0]
    if cpu is None and text.split()[0].lower() not in ('/yesman', '/parlanchin', '/chatty'):
        bot.write(oid, 'Chat', 'Indica el país CPU que actúa, p. ej. /alliance join Francia Germany.')
        return
    yesman = getattr(bot, 'yesman', False)
    try:
        if cpu:
            bot.cfg['country'], bot.acting = cpu, cpu
            try:
                bot.allies = bot.war_sides()[0]      # its alliance partners: they may give it orders
            except Exception:
                bot.allies = set()
        if as_country:
            bot.yesman = True       # the nation itself agreed (LLM decision): no allies-only check
        reply = ai_player.chat_command(bot, human, text)
    except Exception as e:
        reply = 'Error: %s' % str(e)[:200]
        bot.log('act_error', {'command': text, 'error': reply})
    finally:
        bot.cfg['country'], bot.acting = human, None
        if as_country:
            bot.yesman = yesman
    # kept across restarts (only on /yesman: for a guest's commands bot.yesman is off for the moment)
    if text.split()[0].lower() == '/yesman' and bool(getattr(bot, 'yesman', False)) != bool(bot.cfg.get('yesman')):
        bot.cfg['yesman'] = bool(bot.yesman)
        saved = load_config(CONFIG)
        saved['yesman'] = bot.cfg['yesman']
        with open(CONFIG, 'w', encoding='utf-8') as f:
            json.dump(saved, f, ensure_ascii=False, indent=2)
    bot.write(oid, cpu or 'Chat', tr(bot, reply or 'Comando desconocido. Escribe /help.'))
    bot.log('did', {'command': text, 'as': cpu, 'reply': reply})
    return reply


REGION_ALIASES = {'malvinas': 'Falklands', 'islas malvinas': 'Falklands'}


def region_owners_named(bot, text):
    """[(region, owner)] for the map regions a message names ('Falklands', 'Malvinas'...), so the LLM knows whom
    a conquest is against. shortcut: owners at the scenario's start (Bot.region_owners), not later conquests."""
    names = bot.land_map()[0]
    owners = bot.region_owners()
    low = norm(text.lower())
    found = []
    for i, n in enumerate(names):
        if n and len(n) > 3 and re.search(r'\b%s\b' % re.escape(norm(n.lower())), low) and n not in [f[0] for f in found]:
            found.append((n, owners.get(i, '?')))
    for alias, n in REGION_ALIASES.items():
        if re.search(r'\b%s\b' % alias, low) and n in names and n not in [f[0] for f in found]:
            found.append((n, owners.get(names.index(n), '?')))
    return found[:8]


def new_chat(bot, oid, human, text, summit=False):
    """'/chat @Colombia @Venezuela': opens a new chat window (the game's ActAddChat, sent by the player) with the
    nations called with '@', who greet the player there. summit=True ('/summit'): the leaders also talk to each
    other there (think() adds SUMMIT for that chat)."""
    rest = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ''
    names = [c for c in (bot.named(text, at=True) or bot.named(rest)) if c in bot.cpus()]     # '@Italy' or 'Italy'
    if len(names) < (2 if summit else 1):
        bot.write(oid, 'Chat', 'Uso: /summit @país @país [...], p. ej. /summit @France @Italy.' if summit else
                  'Uso: /chat @país [@país ...], p. ej. /chat @Colombia @Venezuela.')
        return
    # another human's /chat: sent through their avatar (their own chat); with no avatar of theirs here, the
    # host opens it and adds them (shortcut: the host is then in that chat too)
    own = human == bot.host or bot.avatar(human) > 0
    me = bot.nations()[human] if own and human != bot.host else bot.player()
    before = set(bot.refs(me, 'objChat'))
    acting, bot.acting = bot.acting, (None if human == bot.host or not own else human)
    try:
        bot.send_action('ActAddChat', {'bObserverAdd': False})
    finally:
        bot.acting = acting
    for _ in range(20):
        new = [o for o in bot.refs(me, 'objChat') if o not in before]
        if new:
            break
        time.sleep(0.5)
    else:
        bot.write(oid, 'Chat', 'No pude abrir el chat nuevo.')
        return
    for c in names + ([] if own else [human]):
        bot.add_to_chat(new[0], c)
    bot._chats_t = 0          # all_chats(): re-read the chat lists now
    bot.log('did', {'chat': names, 'oid': new[0], 'summit': summit})
    if summit:
        game_state(bot)['summits'].append(bot.gid(new[0]))
        save_state(bot)
    think(bot, new[0], human, names, [], ['(El jugador abre %s con %s: saluda brevemente.)' % (
        'una cumbre' if summit else 'este chat', ', '.join(names))])


def order(bot, oid, human, lines, text):
    """'/order Australia declara guerra a Nueva Zelanda': the first nation named obeys (one LLM request, as with
    /yesman on, which turns words into the right tool) and answers here, without joining the chat."""
    words = text.split()      # the nation that obeys is the one the order starts with ('Reino Unido ...' too)
    nations = next(([c] for n in (1, 2, 3) for c in bot.named(' '.join(words[:n])) if c in bot.cpus()), [])
    if not nations:
        bot.write(oid, 'Chat', 'Uso: /order <país> <orden>, p. ej. /order Australia declara guerra a Nueva Zelanda.')
        return
    yesman, bot.yesman, bot.ordered = getattr(bot, 'yesman', False), True, True
    try:
        # the order as plain words, without the '/order' line (the model read it as an unknown command and refused)
        hist = [l for l in lines if not re.match(r'\s*/(order|orden)\b', l[1], re.I)]
        think(bot, oid, human, nations, hist, ['ORDEN DIRECTA del jugador, que %s cumple ya con sus herramientas '
                                               '(jugada + say): %s' % (nations[0], text)])
    finally:
        bot.yesman, bot.ordered = yesman, False


def parse_chat(bot, text):
    """[(author, text)] of a chat's strBigChat ('France(CPU):...'); a line without a header continues the one
    before. A line from a nation with another tag than ours is a human's (bot._chat_humans)."""
    lines = []
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            lines.append((m.group(1).strip(), m.group(3).strip()))
            if bot is not None and m.group(2).strip() != bot.cfg['tag'] and m.group(1).strip() in bot.nations():
                bot.__dict__.setdefault('_chat_humans', set()).add(m.group(1).strip())
        elif lines:
            lines[-1] = (lines[-1][0], lines[-1][1] + ' ' + line.strip())
    return lines


assert parse_chat(None, 'Peru(Me):hi' + chr(10) + 'there' + chr(10) + 'Chile(CPU):ok') == [('Peru', 'hi there'), ('Chile', 'ok')]


def mark(lines):
    """Where we are in a chat: its last 2 lines (by content: trimming the chat changes the count)."""
    return tuple(lines[-2:]) or None


def unseen(lines, seen_mark):
    """The lines after the last place we read up to (seen_mark from mark()); every line if there is none yet,
    none if the mark is gone (the chat was edited away)."""
    if not seen_mark:
        return lines
    n = len(seen_mark)
    for i in range(len(lines) - n, -1, -1):
        if tuple(lines[i:i + n]) == seen_mark:
            return lines[i + n:]
    return []


_l = [('Peru', 'a'), ('Chile', 'b'), ('Peru', 'a'), ('Chile', 'b'), ('Peru', 'c')]
assert unseen(_l, mark(_l[:4])) == [('Peru', 'c')] and unseen(_l, None) == _l and unseen(_l, (('X', 'y'),)) == []
assert unseen(_l, mark(_l)) == []

CHAT_KEEP, CHAT_TRIM_AT = 4, 8     # a chat longer than CHAT_TRIM_AT lines is cut to its last CHAT_KEEP


def trim_chat(bot, oid, seen):
    """Cuts a long chat to its last CHAT_KEEP lines right after we answered it (every read of strBigChat returns
    the whole text): one ActAlterPropertyImmed with bAppend false, built from a read made just before, so a line
    typed meanwhile is kept unless it lands in that one frame."""
    if getattr(bot, '_chat_len', {}).get(oid, 0) <= CHAT_TRIM_AT:
        return      # short at our last read (our own answer lines aren't counted: a few more is fine)
    text = bot.prop(oid, 'strBigChat') or ''
    raw = text.split(chr(10))
    starts = [i for i, l in enumerate(raw) if LINE.match(l)]
    if len(starts) <= CHAT_TRIM_AT:
        return
    kept = chr(10).join(raw[starts[-CHAT_KEEP]:]).replace('"', "'")
    bot.send_action('ActAlterPropertyImmed', {'nGOID': bot.gid(oid), 'strPropName': 'strBigChat', 'bAppend': False,
                                              'strNewValue': kept})
    seen[oid] = mark(parse_chat(None, kept))
    bot.log('did', {'trim_chat': oid, 'chars': [len(text), len(kept)]})


def by_author(lines, humans):
    """[(author, [text, ...])] for the humans' lines, consecutive lines of one author together, in chat order."""
    out = []
    for w, t in lines:
        if w not in humans:
            continue                     # the CPU nations' answers and our 'Chat' notes
        if out and out[-1][0] == w:
            out[-1][1].append(t)
        else:
            out.append((w, [t]))
    return out


assert by_author([('Italy', 'a'), ('Italy', 'b'), ('France', 'x'), ('Germany', 'c'), ('Italy', 'd')],
                 {'Italy', 'Germany'}) == [('Italy', ['a', 'b']), ('Germany', ['c']), ('Italy', ['d'])]

HOST_ONLY = ('/order', '/orden', '/yesman', '/relations', '/ideology', '/editor', '/merge', '/independence',
             '/surrender')


BURST_FREE = 40     # game commands one player message may send at full speed
BURST_PACE = 0.3    # then this many seconds between commands (a frame or more each: the game keeps responding)


def handle_chat(bot, oid, seen):
    """New lines of any human in this chat: each author is answered in turn (in a multiplayer game we host,
    the other players talk and negotiate with the CPU nations too)."""
    lines = bot.chat_lines(oid)
    groups = by_author(unseen(lines, seen.get(oid)), bot.humans())
    seen[oid] = mark(lines)
    for i, (author, new) in enumerate(groups):
        yesman = getattr(bot, 'yesman', False)
        if author != bot.host:
            bot.yesman = False           # the host's /yesman favours the host only
        bot.cfg['country'] = author      # Bot's helpers act towards cfg['country']
        n0 = bot.con.__dict__['burst_from'] = getattr(bot.con, 'count', 0)
        try:
            answer(bot, oid, author, bot.chat_lines(oid) if i else lines, new, seen)
        finally:
            try:
                trim_chat(bot, oid, seen)
            except Exception as e:      # a long chat stays long: the answer is what matters
                bot.log('act_error', {'trim_chat': oid, 'error': str(e)[:200]})
            bot.flush_actions()
            bot.con.__dict__['burst_from'] = None
            bot.log('burst', {'reads': getattr(bot.con, 'count', 0) - n0, 'by': author,
                              'text': ' | '.join(new)[:80]})
            bot.cfg['country'] = bot.host
            if author != bot.host:
                bot.yesman = yesman
    return bool(groups)


def answer(bot, oid, human, lines, new, seen):
    """'human' (the author of the new lines) gets the commands run and the CPU nations' answers."""
    cmds = [t.strip() for t in new if t.strip().startswith('/')]
    new = [t for t in new if not t.strip().startswith('/')]
    for c in cmds:                       # the multiplayer bot's commands, run locally (no LLM), in any chat
        if human != bot.host and c.split()[0].lower() in HOST_ONLY:
            bot.write(oid, 'Chat', '%s: %s solo lo puede usar el anfitrión de la partida (%s).' % (
                human, c.split()[0], bot.host))
            bot.log('ignored_call', {'command': c, 'by': human, 'reason': 'host only'})
        elif re.match(r'/(chat|summit)\b', c, re.I):
            new_chat(bot, oid, human, c, summit=c.lower().startswith('/summit'))
        elif re.match(r'/advisor\b', c, re.I):
            advisor(bot, oid, human, c)
        elif re.match(r'/editor\b', c, re.I):
            editor(bot, oid, human, c)
        elif re.match(r'/(order|orden)\b', c, re.I):
            order(bot, oid, human, lines, c.split(None, 1)[1] if len(c.split(None, 1)) > 1 else '')
        else:
            command(bot, oid, human, c)
    if not new:
        seen[oid] = mark(bot.chat_lines(oid))
        return
    cpu_set, members = bot.cpus(), bot.members(oid)
    cpus = [m for m in members if m in cpu_set]
    for c in bot.named(' '.join(new), at=True) if cpus else []:     # the general chat: '@' only mentions (/chat opens)
        if c in cpu_set and c not in cpus:
            bot.add_to_chat(oid, c)
            cpus.append(c)
    if not cpus:      # the general chat: nations named in plain words answer, but only talk (no moves)
        # with other humans in the chat only '@país' calls a nation in (a plain mention is their own talk)
        at = any(m in bot.humans() and m != human for m in members)
        talk = [c for c in bot.named(' '.join(new), at=at) if c in cpu_set]
        if talk:
            think(bot, oid, human, talk, lines, new, talk_only=True)
            seen[oid] = mark(bot.chat_lines(oid))
        return              # nobody named: silence (the help is in /help)
    else:
        think(bot, oid, human, cpus, lines, new)
    seen[oid] = mark(bot.chat_lines(oid))      # our own answers are not new


# --- what the game remembers between sessions: pending demands, per-nation memory, summit chats ------------------
STATE = os.path.join(os.path.expanduser('~'), '.mheditor', 'sp_chat_state.json')
MEMORY_LINES = 8          # per nation: the newest notes are kept


def game_state(bot):
    """This game's saved state, keyed by scenario and the player's nation (kept between sessions in STATE).
    shortcut: a saved game loaded at an earlier turn shares it; key it by save name if that confuses players."""
    if getattr(bot, '_state', None) is None:
        try:
            with open(STATE, encoding='utf-8') as f:
                bot._all_state = json.load(f)
        except (OSError, ValueError):
            bot._all_state = {}
        bot._state = bot._all_state.setdefault('%s|%s' % (getattr(bot, 'scenario', ''), bot.host), {})
        for k, v in (('demands', []), ('memory', {}), ('summits', [])):
            bot._state.setdefault(k, v)
    return bot._state


def save_state(bot):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(bot._all_state, f, ensure_ascii=False, indent=1)
    os.replace(STATE + '.tmp', STATE)


def remember(bot, country, note):
    note = ' '.join((note or '').split())[:200]
    if note:
        notes = game_state(bot)['memory'].setdefault(country, [])
        notes.append('T%s: %s' % (bot.turn(), note))
        del notes[:-MEMORY_LINES]
        save_state(bot)


def llm(bot, system, prompt, tools):
    """One LLM request: (calls, plain text)."""
    import ai_chat
    bot.log('llm_in', {'prompt': prompt})
    r = ai_chat.chat(system, [{'role': 'user', 'text': prompt}], tools)
    bot.log('llm_out', {'text': r.get('text'), 'calls': r.get('calls'), 'model': r.get('model')})
    return r.get('calls') or [], (r.get('text') or '').strip()


SAY = {'name': 'say', 'description': 'El texto que se escribe en el chat.',
       'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}


def said(calls, text):
    return next(((c.get('args') or {}).get('text') for c in calls if c['name'] == 'say'), None) or text


def general_chat(bot, human):
    """The human's first chat (the general one)."""
    p = bot.nations().get(human)
    chats = bot.refs(p, 'objChat') if p else []
    return chats[0] if chats else None


# --- 1. demands with follow-up -------------------------------------------------------------------------------
DEMAND_UNITS = {'fleet': 'Fleet', 'troops': 'Army'}      # PlayerData.objUnits types (scenario XML: Fleet, Army)
DEMAND_KINDS = {'fleet': 'flota(s)', 'troops': 'ejército(s)', 'aid': 'ayuda o comercio'}


def demand_text(d):
    return '%s a %s: %s%s antes del turno %d' % (
        d['country'], d['human'], '%d %s en %s' % (d['amount'], DEMAND_KINDS[d['kind']], d['region'])
        if d['kind'] in DEMAND_UNITS else DEMAND_KINDS['aid'] + (' (%s)' % d['what'] if d.get('what') else ''),
        ' (si no, rompe la alianza)' if d.get('if_failed') == 'break_alliance' else '', d['due'])


assert demand_text({'country': 'France', 'human': 'Italy', 'kind': 'fleet', 'amount': 1, 'region': 'Ligurian Sea',
                    'due': 7}) == 'France a Italy: 1 flota(s) en Ligurian Sea antes del turno 7'


def treaty_mark(bot, human):
    """Highest nTreatyID among the human's treaties (an aid demand is met by a newer one)."""
    return max([int(t.get('nTreatyID') or -1) for t in treaties(bot, human)] or [-1])


def treaties(bot, human):
    """The human's treaties in force: [{nTreatyID, strTreatyDefType, strFromCountry, strToCountry...}]."""
    tl = bot.obj_id((bot.prop(bot.nations()[human], 'objTreatyList') or ''))
    return [bot.fixed(t) for t in bot.refs(tl, 'objTreaties')] if tl > 0 else []


def add_demand(bot, oid, country, human, a):
    kind = a.get('kind')
    if kind not in DEMAND_KINDS:
        raise RuntimeError('unknown demand kind %s' % kind)
    turn = bot.turn()
    d = {'country': country, 'human': human, 'kind': kind, 'amount': max(1, int(a.get('amount') or 1)),
         'since': turn, 'due': turn + max(1, min(10, int(a.get('turns') or 3))), 'what': a.get('what') or '',
         'if_failed': 'break_alliance' if a.get('if_failed') == 'break_alliance' else 'relations'}
    if kind in DEMAND_UNITS:
        d['region'] = bot.land_map()[0][bot.region_id(a.get('region') or '')]
    else:
        d['mark'] = treaty_mark(bot, human)
    game_state(bot)['demands'].append(d)
    remember(bot, country, 'exigió ' + demand_text(d))      # also saves the demand
    bot.write(oid, 'Chat', 'Exigencia anotada: %s.' % demand_text(d))


def units_at(bot, human):
    """Counter of (unit type, nRegionID) of the human's units (as Bot.move_troops reads armies)."""
    data = bot.obj_id((bot.prop(bot.nations()[human], 'objData') or ''))
    return collections.Counter((bot.unit(u)[0], bot.unit(u, region=True)[1]) for u in bot.refs(data, 'objUnits'))


def demand_met(d, units, deals):
    """units: units_at() of the human; deals: their treaties."""
    if d['kind'] in DEMAND_UNITS:
        return units[(DEMAND_UNITS[d['kind']], d['region_id'])] >= d['amount']
    return any(int(t.get('nTreatyID') or -1) > d['mark'] and {t.get('strFromCountry'), t.get('strToCountry')} ==
               {d['human'], d['country']} and re.search(r'aid|trade', t.get('strTreatyDefType') or '', re.I)
               for t in deals)


assert demand_met({'kind': 'fleet', 'region_id': 5, 'amount': 2}, collections.Counter({('Fleet', 5): 2}), [])
assert not demand_met({'kind': 'troops', 'region_id': 5, 'amount': 1}, collections.Counter({('Fleet', 5): 2}), [])
assert demand_met({'kind': 'aid', 'mark': 3, 'human': 'Italy', 'country': 'France'}, None,
                  [{'nTreatyID': '4', 'strFromCountry': 'Italy', 'strToCountry': 'France', 'strTreatyDefType': 'AidTreaty'}])
assert not demand_met({'kind': 'aid', 'mark': 4, 'human': 'Italy', 'country': 'France'}, None,
                      [{'nTreatyID': '4', 'strFromCountry': 'Italy', 'strToCountry': 'France', 'strTreatyDefType': 'Aid'}])

DEMAND_RELATIONS = 60     # relation change (of 1000) when a demand is met / fails


def check_demands(bot):
    """At a new turn: each pending demand met (thanks, relations up) or past its deadline (protest, relations down,
    or the alliance broken); the nation then writes to the player about it."""
    st, turn, read = game_state(bot), bot.turn(), {}
    names = bot.land_map()[0]
    done, keep = [], []
    for d in st['demands']:
        if d['human'] not in bot.nations():
            continue
        if d['human'] not in read:
            read[d['human']] = (units_at(bot, d['human']), treaties(bot, d['human']))
        d['region_id'] = names.index(d['region']) if d.get('region') in names else -1
        met = demand_met(d, *read[d['human']])
        (done if met or turn >= d['due'] else keep).append((d, met))
    st['demands'] = [d for d, _ in keep]
    save_state(bot)
    for d, met in done:
        try:
            cur = relation(bot, d['country'], d['human'])[1]
            set_pair(bot, d['country'], d['human'], max(0, min(1000, cur + (DEMAND_RELATIONS if met else -DEMAND_RELATIONS))))
            broke = ''
            if not met and d['if_failed'] == 'break_alliance' and \
                    str(bot.country_id(d['human'])) in bot.as_nation(d['country'], lambda: bot.war_sides()[0]):
                bot.as_nation(d['country'], lambda: bot.propose('romper_alianza', d['human']))
                broke = ' y rompe la alianza'
            remember(bot, d['country'], '%s cumplió: %s' % (d['human'], demand_text(d)) if met else
                     '%s NO cumplió: %s' % (d['human'], demand_text(d)))
            cpu_message(bot, d['country'], d['human'], (
                '%s cumplió lo que exigiste (%s): agradécelo; la relación mejora %d' if met else
                '%s no cumplió lo que exigiste (%s) y venció el plazo: protesta; la relación empeora %d' + broke) % (
                d['human'], demand_text(d), DEMAND_RELATIONS))
        except Exception as e:      # one nation's follow-up must not stop the others
            bot.log('act_error', {'demand': d, 'error': str(e)[:300]})


# --- 2, 3, 10. the turn's events: CPU messages, the newsroom, rare CPU-CPU deals --------------------------------
EVENT_MESSAGES = 3        # CPU-initiated messages per turn at most (one LLM request each)
NEWS = 'News'             # the newsroom's name in the chat
CPU_DEAL_CHANCE = 0.15    # per turn: the newsroom may also make one CPU-CPU deal


def world_snapshot(bot):
    """What the turn's news is made of: wars, alliance members, the humans' treaties, and the regions held by
    the humans and the nations they talked to. Needs bot._country_ids (read a few per round by background()).
    shortcut: conquests only among those nations; read Region owners if news of other fronts is wanted."""
    names = {str(v): k for k, v in bot._country_ids.items()}
    _, als, wars = bot._alliances()
    alliances, al_name = {}, {}
    for a in als:
        p = {k: bot.prop(a, k) for k in ('nAllianceID', 'strDisplayName')}
        al_name[p.get('nAllianceID')] = p.get('strDisplayName')
        alliances[p.get('strDisplayName')] = sorted(names.get(bot.fixed(m).get('nCountryID'), '?')
                                                    for m in bot.refs(a, 'objCurrentMembers'))
    side = lambda ref: names.get(bot.fixed(bot.obj_id(ref or '')).get('nCountryID'), '?')
    war = {w: (side(bot.fixed(w).get('objAttackerCountry')), side(bot.fixed(w).get('objDefenderCountry')))
           for w in wars}
    deals = {(t.get('strTreatyDefType'), t.get('strFromCountry'), t.get('strToCountry'))
             for h in bot.humans() if h in bot.nations() for t in treaties(bot, h)}
    region_names = bot.land_map()[0]
    regions = {}
    for n in bot.humans() | set(game_state(bot)['memory']):
        c = bot.__dict__.get('_country_oids', {}).get(n, -1)
        if c > 0:
            regions[n] = {region_names[i] for i in (int(bot.prop(r, 'nRegionID') or -1)
                                                     for r in bot.refs(c, 'objRegions')) if 0 <= i < len(region_names)}
    return {'wars': war, 'alliances': alliances, 'treaties': deals, 'regions': regions}


def diff_events(old, new):
    """[(text, {nations}, region or None)] between two world_snapshot()s."""
    ev = []
    for w, (a, d) in new['wars'].items():
        if w not in old['wars']:
            ev.append(('%s declara la guerra a %s' % (a, d), {a, d}, None))
    for w, (a, d) in old['wars'].items():
        if w not in new['wars']:
            ev.append(('termina la guerra entre %s y %s' % (a, d), {a, d}, None))
    for al in sorted(set(old['alliances']) | set(new['alliances'])):
        o, n = set(old['alliances'].get(al, ())), set(new['alliances'].get(al, ()))
        ev += [('%s entra en la alianza %s' % (c, al), {c}, None) for c in sorted(n - o)]
        ev += [('%s sale de la alianza %s' % (c, al), {c}, None) for c in sorted(o - n)]
    ev += [('%s y %s firman un tratado (%s)' % (a, b, k), {a, b}, None) for k, a, b in sorted(new['treaties'] - old['treaties'])]
    ev += [('se rompe o vence el tratado %s entre %s y %s' % (k, a, b), {a, b}, None)
           for k, a, b in sorted(old['treaties'] - new['treaties'])]
    gained = {r: n for n, rs in new['regions'].items() for r in rs - old['regions'].get(n, rs)}
    lost = {r: n for n, rs in old['regions'].items() if n in new['regions'] for r in rs - new['regions'][n]}
    for r in sorted(set(gained) | set(lost)):
        w, l = gained.get(r, '?'), lost.get(r, '?')
        ev.append(('%s pasa de %s a %s' % (r, l, w), {w, l} - {'?'}, r))
    return ev


_old = {'wars': {1: ('Germany', 'Poland')}, 'alliances': {'Axis': ['Germany']}, 'treaties': set(),
        'regions': {'Italy': {'Rome'}, 'France': {'Nice', 'Paris'}}}
_new = {'wars': {2: ('Italy', 'France')}, 'alliances': {'Axis': ['Germany', 'Italy']},
        'treaties': {('Trade', 'Italy', 'Spain')}, 'regions': {'Italy': {'Rome', 'Nice'}, 'France': {'Paris'}}}
assert [e[0] for e in diff_events(_old, _new)] == [
    'Italy declara la guerra a France', 'termina la guerra entre Germany y Poland', 'Italy entra en la alianza Axis',
    'Italy y Spain firman un tratado (Trade)', 'Nice pasa de France a Italy']
assert diff_events(_old, _new)[-1][1:] == ({'Italy', 'France'}, 'Nice')
assert diff_events(_new, _new) == []


def wars_text(bot):
    """'Germany (Axis) contra Poland (Allies); ...': the wars in progress with their sides' alliances. Names from
    _country_ids once read, else the scenario's initial ones (strINIT...)."""
    names = {str(v): k for k, v in (getattr(bot, '_country_ids', None) or {}).items()}
    _, als, wars = bot._alliances()
    al_name = {bot.prop(a, 'nAllianceID'): bot.prop(a, 'strDisplayName') for a in als}
    out = []
    for w in wars:
        p = bot.fixed(w)

        def side(country, party, init):
            n = names.get(bot.fixed(bot.obj_id(p.get(country) or '')).get('nCountryID')) or p.get(init) or '?'
            al = al_name.get(bot.fixed(bot.obj_id(p.get(party) or '')).get('nAllianceID'))
            return '%s (%s)' % (n, al) if al else n
        out.append('%s contra %s' % (side('objAttackerCountry', 'objOffense', 'strINITAttackerCountry'),
                                     side('objDefenderCountry', 'objDefense', 'strINITDefenderCountry')))
    return '; '.join(out[:15])


def pending_text(bot, countries):
    """Open popups (title, options) and treaty offers waiting for an answer, of each of these nations."""
    out = []
    for c in countries:
        if c not in bot.nations():
            continue
        pops = bot.as_nation(c, bot.popups)
        offers = bot.as_nation(c, bot.proposals)
        out += ['%s tiene el aviso «%s» (opciones: %s)' % (c, p.get('titulo') or p.get('tipo'), ', '.join(
            o for o in p['opciones'] if o)) for p in pops[:4]]
        out += ['propuesta #%s %s de %s a %s' % (t['id'], t['tipo'], t['de'], t['para'])
                for t in offers[:4] if t['para'] == c]
    return '; '.join(dict.fromkeys(out))


def historic(bot, country):
    return [s.rsplit(' (', 1)[0] for s in bot.claims(country)]


def cpu_message(bot, cpu, human, event):
    """'cpu' writes to 'human' on its own about an event: one LLM request, in their shared chat (else the general
    one)."""
    p = bot.nations().get(human)
    oid = next((o for o in (bot.refs(p, 'objChat') if p else []) if cpu in bot.members(o)), None) or \
        general_chat(bot, human)
    if oid is None:
        return
    think(bot, oid, human, [cpu], bot.chat_lines(oid), [
        '(EVENTO, no es un mensaje del jugador: %s. %s le escribe al jugador por iniciativa propia sobre esto: '
        'un mensaje breve, con su voz y sus intereses.)' % (event, cpu)], talk_only=True)


def event_messages(bot, events):
    """The CPU nations an event touches write to the player: those in an event with a human, and those the
    players talked to (their wars, alliances, treaties, and their historic regions changing hands)."""
    cpus, humans, talked = bot.cpus(), bot.humans(), set(game_state(bot)['memory'])
    sent = []
    for text, nations, region in events:
        hs = sorted(nations & humans)
        writers = [(c, hs[0] if hs else bot.host) for c in sorted(nations & cpus) if hs or c in talked]
        if region:      # a historic region changing hands: the nations that claim it speak up
            claim = sorted(c for c in cpus & (talked | nations) if region in historic(bot, c))
            writers += [(c, hs[0] if hs else bot.host) for c in claim if c not in dict(writers)]
            text += ' (%s la reclama como región histórica)' % ', '.join(claim) if claim else ''
        for c, h in writers:
            if len(sent) < EVENT_MESSAGES and c not in sent:
                sent.append(c)
                cpu_message(bot, c, h, text)


NEWS_TOOLS = [
    {'name': 'news', 'description': 'La línea de prensa del turno.',
     'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}},
    {'name': 'cpu_deal', 'description': 'Una jugada diplomática entre dos naciones de la lista: relations_up / '
                                        'relations_down (gesto), o a le propone a b un pacto (b decide).',
     'parameters': {'type': 'object', 'properties': {
         'a': {'type': 'string'}, 'b': {'type': 'string'},
         'kind': {'type': 'string', 'enum': ['relations_up', 'relations_down', 'no_agresion', 'acceso_militar',
                                             'alianza']}}, 'required': ['a', 'b', 'kind']}}]


def newsroom(bot, events):
    """One short press line in the general chat about the turn's events (one LLM request per turn), and now and
    then (CPU_DEAL_CHANCE) one CPU-CPU deal that the same request picks and the code applies."""
    import random
    cpus = bot.cpus()
    pool = sorted({n for _, ns, _ in events for n in ns} & cpus | set(game_state(bot)['memory']) & cpus)[:12]
    deal = len(pool) >= 2 and random.random() < CPU_DEAL_CHANCE
    oid = general_chat(bot, bot.host)
    if oid is None or not (events or deal):
        return
    gs = bot.gsp('dateCurrent', 'nCurrentTurn')
    system = ('Eres la redacción de un periódico de la época de la partida de Making History (%s). Escribe con news '
              'UNA sola línea de prensa (titular y una frase), en %s, sobre lo más importante del turno; sin inventar '
              'hechos que no estén en la lista.' % (bot.cfg['game_name'], bot.cfg['language_name']))
    if deal:
        system += (' Esta vez decide además, con cpu_deal, una jugada diplomática entre dos naciones de la lista '
                   'que tenga sentido por sus intereses y su historia, y cuéntala en la noticia como anuncio.')
    prompt = 'Fecha: %s (turno %s).\nHechos del turno:\n%s%s' % (
        gs.get('dateCurrent'), gs.get('nCurrentTurn'), '\n'.join('- ' + e[0] for e in events[:20]) or '(turno tranquilo)',
        '\nNaciones para la jugada: %s' % ', '.join(pool) if deal else '')
    calls, text = llm(bot, system, prompt, NEWS_TOOLS if deal else NEWS_TOOLS[:1])
    for c in calls:
        a = c.get('args') or {}
        if c['name'] == 'cpu_deal' and deal:
            deal = False      # one per turn
            x, y = bot.country_name(a.get('a', '')), bot.country_name(a.get('b', ''))
            try:
                if x in cpus and y in cpus and x != y:
                    cpu_deal(bot, oid, x, y, a.get('kind'))
            except Exception as e:
                bot.log('act_error', {'cpu_deal': a, 'error': str(e)[:300]})
    line = next((c['args'].get('text') for c in calls if c['name'] == 'news' and c.get('args')), None) or text
    if line:
        bot.write(oid, NEWS, line)


def cpu_deal(bot, oid, a, b, kind):
    if kind in ('relations_up', 'relations_down'):
        cur = relation(bot, a, b)[1]
        done = set_pair(bot, a, b, max(0, min(1000, cur + (100 if kind == 'relations_up' else -100))))
    elif kind in PACTS:
        if pact_with_ally(bot, oid, {'name': 'cpu_deal'}, a, b):
            return
        bot.as_nation(a, lambda: bot.propose(kind, b))
        done = '%s propone %s a %s' % (a, kind, b)
    else:
        return
    bot.log('did', {'cpu_deal': [a, b, kind], 'done': done})


MAX_MOVES = 2          # game moves per player message (remember / surrender don't count)
DEPLOY_ARMIES, DEPLOY_TURNS = 3, 6     # an LLM troop move without a number; turns a promised deployment is kept


def deploy(bot, country, target, amount):
    """Remembers a promised deployment: the CPU AI recalls the armies next turn, so redeploy() sends them again
    each turn for DEPLOY_TURNS turns."""
    state = game_state(bot)
    state['deployments'] = [d for d in state.get('deployments', []) if (d['country'], d['target']) != (country, target)]
    state['deployments'].append({'country': country, 'target': target, 'amount': amount,
                                 'until': bot.turn() + DEPLOY_TURNS})
    save_state(bot)


def redeploy(bot):
    """At each new turn: the promised armies go back to their destination (one move order per deployment)."""
    state, turn = game_state(bot), bot.turn()
    live = [d for d in state.get('deployments', []) if d['until'] >= turn]
    for d in live:
        try:
            out = bot.as_nation(d['country'], lambda: bot.move_troops(d['target'], d['amount']))
            bot.log('did', {'redeploy': d, 'result': str(out)[:200]})
        except Exception as e:
            bot.log('act_error', {'redeploy': d, 'error': str(e)[:200]})
    if len(live) != len(state.get('deployments', [])):
        state['deployments'] = live
        save_state(bot)


STATE_CAPS = {'demands': 20, 'deployments': 10, 'summits': 10}      # local state: the newest kept


def housekeeping(bot):
    """At each new turn, a few small reads: what SP Chat may leave in the game, counted and logged so growth shows
    (chats, offers waiting, open popups, our action list), our scratch actions removed if any survived, and the
    local state capped. shortcut: the game has no action to close a chat or withdraw an offer, so those are
    only counted."""
    host, data = bot.nations().get(bot.host), bot._me() and bot._data()
    counts = {'chats': len(bot.refs(host, 'objChat')) if host else 0,
              'objActions': len(bot.refs(data, 'objActions')) if data > 0 else 0,
              'open_dps': len(bot.refs(data, 'objDecisionPoints')) if data > 0 else 0}
    tl = bot.obj_id(bot.prop(host, 'objTreatyList') or '') if host else -1
    counts['offers'] = len(bot.refs(tl, 'objProposedTreaties')) if tl > 0 else 0
    if bot.__dict__.get('_pool'):
        bot.flush_actions()
    st = game_state(bot)
    for k, cap in STATE_CAPS.items():
        if len(st.get(k, [])) > cap:
            st[k] = st[k][-cap:]
    save_state(bot)
    bot.log('housekeeping', dict(counts, turn=bot._turn))


def background(bot):
    """Every few seconds (run(), commands spaced out): the new turn's follow-ups (demands, events, news) when the
    turn changed; otherwise ONE small step: the multiplayer humans check (odd ticks) or, in turn, a nation id,
    the first world snapshot, the CPU allies' popups (every 2 min)."""
    turn = getattr(bot, '_turn', None)
    if getattr(bot, '_seen_turn', None) is None:
        bot._seen_turn = turn
    elif turn != bot._seen_turn:
        bot._seen_turn = turn
        verify_pacts(bot)      # the chat's own pacts whose vote was open: their real result (not autonomous)
        try:
            housekeeping(bot)
        except Exception as e:
            bot.log('act_error', {'housekeeping': str(e)[:200]})
        if not bot.cfg.get('autonomous'):      # only what the chat asks for: no per-turn moves of our own
            return
        check_demands(bot)
        redeploy(bot)
        if getattr(bot, '_snap', None):
            old, bot._snap = bot._snap, world_snapshot(bot)
            events = diff_events(old, bot._snap)
            bot.log('events', {'turn': turn, 'events': [e[0] for e in events]})
            for step in (event_messages, newsroom):
                try:
                    step(bot, events)
                except Exception as e:
                    bot.log('act_error', {step.__name__: str(e)[:300]})
        return
    bot._tick = getattr(bot, '_tick', 0) + 1
    if bot._tick % 2 and time.time() > getattr(bot, '_taken_t', 0):
        bot.check_taken()
        if not bot._taken_todo:      # a pass is over: the next one in 10 minutes
            bot._taken_t = time.time() + 600
        return
    if getattr(bot, '_country_ids', None) is None:
        bot.country_ids_step(1)
        return
    if not bot.cfg.get('autonomous'):
        return
    if getattr(bot, '_snap', None) is None and time.time() - getattr(bot, '_snap_t', 0) > 60:
        bot._snap_t = time.time()      # a failing read retries a minute later, not every round
        bot._snap = world_snapshot(bot)
        return
    if time.time() - getattr(bot, '_popups_t', 0) > 120:
        bot._popups_t = time.time()
        cpu_popups(bot)


# --- 9. CPU popups answered in character ------------------------------------------------------------------------
POPUP_TOOL = {'name': 'answer_popup', 'description': 'Responde un aviso con una de sus opciones.',
              'parameters': {'type': 'object', 'properties': {
                  'id': {'type': 'integer'}, 'choice': {'type': 'string'},
                  'text': {'type': 'string', 'description': 'una frase del dirigente explicando su decisión'}},
                  'required': ['id', 'choice']}}


def cpu_popups(bot):
    """Open decision popups (alliance votes...) of the CPU nations allied with the host: one LLM request per
    nation with something open, answered through its avatar (ActSelectDPChoice). The CPU AI usually answers its
    own popups at once, so this acts only where the game leaves one open."""
    names = {str(v): k for k, v in bot._country_ids.items()}
    done = bot.__dict__.setdefault('_cpu_dp', set())
    for c in sorted({names.get(i) for i in bot.war_sides()[0]} & bot.cpus()):
        pops = [p for p in bot.as_nation(c, bot.popups) if p['id'] not in done]
        if not pops:
            continue
        done.update(p['id'] for p in pops)
        calls, _ = llm(bot, 'Eres el dirigente de %s en Making History (%s), aliado de %s. Responde cada aviso con '
                            'answer_popup según tus intereses; text en %s.' % (
                                c, bot.cfg['game_name'], bot.host, bot.cfg['language_name']),
                       'Situación:\n%s\n\nAvisos abiertos:\n%s' % (bot.context([c], bot.host), '\n'.join(
                           json.dumps(p, ensure_ascii=False) for p in pops)), [POPUP_TOOL])
        for call in calls:
            a = call.get('args') or {}
            pop = next((p for p in pops if str(p['id']) == str(a.get('id'))), None)
            if pop and a.get('choice') in pop['opciones']:
                bot.as_nation(c, lambda: bot.answer_popup(pop['id'], a['choice']))
                oid = general_chat(bot, bot.host)
                if oid and a.get('text'):
                    bot.write(oid, c, a['text'])
                bot.log('did', {'popup': pop, 'as': c, 'choice': a['choice']})


# --- 4. /advisor ----------------------------------------------------------------------------------------------
ADVISORS = {'military': 'militar', 'economy': 'económico', 'diplomacy': 'diplomático'}


def advisor_report(bot, human, area):
    """The player's own data for the advisor, read like the CPU nations' (military(), report())."""
    def read():
        parts = ['Fuerzas, investigación y producción: ' + bot.military(human, bot.turn())]
        country = bot.obj_id((bot.prop(bot.player(), 'objCountry') or ''))
        if area != 'diplomacy':
            res = [{k: bot.prop(r, k) for k in ('strName', 'nAmount', 'nDemand')} for r in bot.refs(country, 'objResources')]
            parts.append('Recursos (stock / demanda por turno): ' + ', '.join(
                '%s %s/%s' % (q.get('strName'), q.get('nAmount'), q.get('nDemand')) for q in res))
        try:
            ids = {str(v): k for k, v in (getattr(bot, '_country_ids', None) or {}).items()}
            allies, enemies = bot.war_sides()
            parts.append('Aliados: %s. En guerra con: %s.' % (', '.join(sorted(ids.get(i, i) for i in allies)) or 'nadie',
                                                              ', '.join(sorted(ids.get(i, i) for i in enemies)) or 'nadie'))
        except Exception:
            pass
        if area == 'diplomacy':
            rel = re.sub(r'(?m)^.*\s500$\n?', '', bot.report('relaciones', human))
            parts.append('Relaciones (0-1000; las neutrales no se listan): ' + rel[:2500])
            dem = [demand_text(d) for d in game_state(bot)['demands'] if d['human'] == human]
            parts.append('Exigencias pendientes: ' + ('; '.join(dem) or 'ninguna'))
        return '\n'.join(parts)
    return bot.as_nation(human, read)


def advisor(bot, oid, human, text):
    """'/advisor military|economy|diplomacy [question]': one LLM request with the player's real data; no moves."""
    m = re.match(r'/advisor\s+(\w+)\s*(.*)$', text.strip(), re.I | re.S)
    if not m or m.group(1).lower() not in ADVISORS:
        bot.write(oid, 'Chat', 'Uso: /advisor military|economy|diplomacy [pregunta]')
        return
    area = m.group(1).lower()
    system = ('Eres el asesor %s de %s en Making History (%s). Respondes al jugador con los datos reales de su partida: '
              '2-4 frases concretas, con cifras del informe y una recomendación; no inventes datos y no haces ninguna '
              'jugada. Responde con say, en %s.' % (ADVISORS[area], human, bot.cfg['game_name'], bot.cfg['language_name']))
    prompt = 'Informe:\n%s\n\nPregunta: %s' % (advisor_report(bot, human, area),
                                               m.group(2).strip() or 'situación general y qué hacer ahora')
    calls, plain = llm(bot, system, prompt, [SAY])
    reply = said(calls, plain) or 'El asesor no respondió.'
    bot.write(oid, 'Advisor', reply)
    bot.log('did', {'advisor': area, 'reply': reply})


# --- 8. /summit -----------------------------------------------------------------------------------------------
SUMMIT = ('\nCUMBRE: en este chat hablan varios dirigentes a la vez. En cada ronda cada nación del chat habla una vez '
          '(say), al jugador y también a los otros líderes por su nombre, respondiendo a lo que dijeron; pueden '
          'discrepar. Si llegan a un acuerdo entre varios, ciérrenlo en esta misma respuesta con propose (target = '
          'otra nación del chat o el jugador), una llamada por tratado.')


# --- 11. /editor ----------------------------------------------------------------------------------------------
EDITOR_MAX = 8            # game actions per /editor at most
EDITOR = """Eres el director de juego de una partida de Making History ({game}). Conviertes la frase del jugador \
en jugadas reales del juego, usando SOLO estas herramientas, como mucho {cap} llamadas:
- command con country = la nación CPU que actúa (primer país del comando) y uno de estos comandos: /declare war \
<yo> <pais> | /peace <yo> <pais> | /alliance join <yo> <pais> | /nonaggression <yo> <pais> | /access <yo> <pais> | \
/embargo <yo> <pais> | /trade <yo> <pais> give Oil:50 get Food:50 | /aid <yo> <pais> Armaments:20 money:5 | \
/government <yo> Democratic|Authoritarian|Fascist|Communist|Despotist | /transfer territory <region suya> <pais que \
la recibe> | /build <yo> army|air|navy 5 | /relations set <pais> <pais> <0-1000> | /ideology align <pais que cambia> \
<pais modelo> | /independence <yo> <nación nueva del escenario> [región, región...] (crea o libera una nación: \
<yo> le cede esas regiones suyas) | /surrender <yo> <vencedor> [región, región...] (<yo> se rinde: sale de su alianza, firma la paz, entra en la del vencedor y le cede esas regiones; sin lista, las que ocupa o reclama).
- ai_profile para cambiar el rumbo de una nación CPU.
Las naciones humanas ({humans}) no actúan: si algo es para ellas, que lo haga la otra parte (p. ej. un territorio \
se lo cede su dueño CPU). Una crisis = relaciones bajas, embargos o guerra entre naciones CPU. No inventes mecánicas: \
si algo no se puede con estas herramientas, no lo hagas. Nombres de países y regiones del juego, en inglés."""


def editor(bot, oid, human, text):
    """'/editor <phrase>' (host only, /yesman on): one LLM request turns the phrase into at most EDITOR_MAX of
    the commands that already work, each run as its CPU nation and reported in the chat."""
    phrase = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ''
    if not getattr(bot, 'yesman', False):
        bot.write(oid, 'Chat', '/editor solo funciona con /yesman on.')
        return
    if not phrase:
        bot.write(oid, 'Chat', 'Uso: /editor <frase>, p. ej. /editor dale las Malvinas a Argentina.')
        return
    cpus = bot.cpus()
    named = bot.named(phrase)
    facts = ['%s (%s): ideología %s' % (n, 'humano' if n in bot.humans() else 'CPU', GOV_ES.get(gov_type(bot, n), '?'))
             for n in named[:10]]
    facts += ['región %s: su dueño al empezar es %s' % ro for ro in region_owners_named(bot, phrase)]
    system = EDITOR.format(game=bot.cfg['game_name'], cap=EDITOR_MAX, humans=', '.join(sorted(bot.humans())))
    tools = [t for t in TOOLS if t['name'] in ('command', 'ai_profile')]
    calls, _ = llm(bot, system, 'Datos:\n%s\n\nFrase del jugador: %s' % ('\n'.join(facts) or '-', phrase), tools)
    done = 0
    for c in calls[:EDITOR_MAX]:
        a = c.get('args') or {}
        country, cmd = bot.country_name(a.get('country', '')), (a.get('command') or '').strip()
        try:
            if c['name'] == 'ai_profile' and country in cpus:
                keys = dict(zip(('doctrine', 'posture', 'aggressive', 'involvement', 'science', 'domestic'), AI_KNOBS))
                ch = bot.set_knobs(country, {keys[k]: v for k, v in a.items() if k in keys and isinstance(v, int)})
                bot.write(oid, 'Chat', '%s: %s.' % (country, '; '.join(ch) or 'sin cambios'))
            elif c['name'] == 'command' and cmd.startswith('/') and cmd.split()[0].lower() not in LLM_BLOCKED:
                if re.match(r'/relations\s+set|/ideology\s+align', cmd, re.I):
                    command(bot, oid, human, cmd)
                elif country in cpus:
                    target = next((n for n in bot.named(cmd) if n != country), None)
                    if re.match(r'/declare\s+war', cmd, re.I) and target and \
                            str(bot.country_id(target)) in bot.as_nation(country, lambda: bot.war_sides()[0]):
                        bot.as_nation(country, lambda: bot.propose('romper_alianza', target))     # as /order does
                        bot.write(oid, 'Chat', '%s rompe la alianza con %s.' % (country, target))
                    command(bot, oid, human, cmd, as_country=country)
                else:
                    bot.log('ignored_call', dict(c, reason='editor: not a CPU nation'))
                    continue
            else:
                bot.log('ignored_call', dict(c, reason='editor'))
                continue
            done += 1
        except Exception as e:
            bot.write(oid, 'Chat', 'Editor: no pude hacer %s (%s).' % (cmd or c['name'], str(e)[:120]))
    bot.write(oid, 'Chat', 'Editor: %d jugada(s) aplicadas%s.' % (
        done, '' if len(calls) <= EDITOR_MAX else ' (límite %d; %d descartadas)' % (EDITOR_MAX, len(calls) - EDITOR_MAX)))


def load_config(path):
    cfg = dict(DEFAULTS)
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            cfg.update(json.load(f))
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


def connect(cfg):
    """Waits for Making History to be running and hooks into it: (GameCLI, game folder)."""
    told = False
    while True:
        check_code()
        pid, bin_dir = find_pid()
        if pid:
            root, cli = os.path.dirname(bin_dir), None
            try:
                stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
                cli = GameCLI(pid, bin_dir, log_path=os.path.join(LOGS, 'sp_chat_game_%s.log' % stamp))
                patch = Console.__new__(Console)       # Console's in-memory patches, applied to the game process
                patch.game, patch.proc = root, types.SimpleNamespace(pid=pid)
                patch.enable_dispatch()                # 'action ActPauseGame <id> [avatar]'
                try:                                   # accents typed in the game's chat box no longer crash it
                    print('Tildes en el chat del juego: %s' % dead_keys.apply(pid), flush=True)
                except OSError as e:
                    print('No pude activar las tildes en el chat: %s' % e, flush=True)
                break
            except Exception:       # still starting (its DLLs not loaded yet): try again
                if cli:
                    try:
                        cli.detach()
                    except OSError:
                        pass
        elif not told:
            print('Esperando a que abras Making History (MH1 o Gold)...', flush=True)
            told = True
        time.sleep(3)
    cfg['game'] = 'gold' if os.path.normcase(root) == os.path.normcase(gamepaths.GAMES['gold']['path']) else 'mh1'
    cfg['game_name'] = 'Gold' if cfg['game'] == 'gold' else 'MH1'
    print('Conectado a Making History %s. Entra en una partida (de un jugador, o multijugador como anfitrión).'
          % cfg['game_name'], flush=True)
    return cli, root


def wait_until_quick(cli, log):
    """After an emergency stop: no attaching or detaching (that churn preceded a crash), the same hook. Every 15 s
    one tiny unwatched command is timed; when it answers in under a second, sending resumes. A closed game raises
    OSError (main() then waits for it)."""
    while True:
        time.sleep(15)
        check_code()
        if not find_pid()[0]:
            raise OSError('the game was closed')
        t0 = time.time()
        cli.raw_cmd('dump property 0 objMyAvatar')
        quick = time.time() - t0 < 1
        log('probe', {'quick': quick})
        if quick:
            cli.__dict__.pop('gave_up', None)
            cli.slow_run = 0
            print('El juego responde otra vez: SP Chat sigue.', flush=True)
            return


def set_language(cfg):
    code, name = windows_language()
    cfg['language'], cfg['language_name'] = (cfg['language'], cfg['language']) if cfg['language'] else (code, name)
    if cfg['language'] == 'es':
        cfg['language_name'] += (' neutro, tuteando (tú, nunca vos ni voseo: «propones», «quieres», «gánate»; '
                                 'nunca «proponés», «querés», «ganate»)')


def wait_game(cfg, log, cli, root):
    """Waits until the player is in a game where we can play the CPU nations; returns its SPBot. A closed game
    raises OSError."""
    refused = None
    while True:
        check_code()
        try:
            bot = SPBot(cfg, log, cli, root)
            me = bot.player()
        except (StopIteration, RuntimeError, ValueError):       # menus / loading: nothing to read yet
            me = -1
        if me > 0 and me != refused:
            cfg['country'] = bot.host = bot.prop(me, 'strName')
            # the scenario first: nations() takes the names from its files
            bot.scenario = bot.prop(bot.gs(), 'strScenario')
            why = (None if bot.cpus() and bot.is_host() else
                   'No hay naciones CPU en esta partida: todas las juega un humano.' if not bot.cpus() else
                   'Esta partida no la hospedas tú: las naciones CPU solo se pueden controlar desde el anfitrión. '
                   'SP Chat tiene que correr en el equipo que hospeda la partida multijugador.')
            if not why:
                print('Partida encontrada: juegas con %s. Ya puedes chatear.' % cfg['country'], flush=True)
                return bot
            print(why + ' Esperando a otra partida...', flush=True)
            refused = me
        time.sleep(3)


RESTART = 3      # exit code: 'SP Chat.bat' runs sp_chat again
KEEP_GAME_LOGS = 5              # newest sp_chat_game_*.log kept (each one is capped by game_cli.LOG_MAX)


def prune_logs():
    """Keeps SP Chat's logs small: the newest KEEP_GAME_LOGS game logs, and sp_chat.jsonl started again over
    game_cli.LOG_MAX * 2."""
    games = sorted((f for f in os.listdir(LOGS) if f.startswith('sp_chat_game_') and f.endswith('.log')), reverse=True)
    for f in games[KEEP_GAME_LOGS:]:
        try:
            os.remove(os.path.join(LOGS, f))
        except OSError:            # still open by another copy: next time
            pass
    j = os.path.join(LOGS, 'sp_chat.jsonl')
    if os.path.isfile(j) and os.path.getsize(j) > 2 * game_cli.LOG_MAX:
        open(j, 'w').close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', default=CONFIG)
    a = ap.parse_args()
    cfg = load_config(a.config)
    os.makedirs(LOGS, exist_ok=True)
    prune_logs()
    out = open(os.path.join(LOGS, 'sp_chat.jsonl'), 'a', encoding='utf-8')

    def log(kind, d):
        rec = dict(d, t=datetime.datetime.now().strftime('%H:%M:%S'), kind=kind)
        out.write(json.dumps(rec, ensure_ascii=False) + '\n')
        out.flush()
        if kind in ('ready', 'did', 'act_error', 'ignored_call', 'llm_out'):
            print(kind, json.dumps(d, ensure_ascii=False)[:300], flush=True)
    set_language(cfg)
    threading.Thread(target=read_console, daemon=True).start()
    print('Puedes escribir aquí mensajes y comandos (/order, /chat...): van al chat que estés usando.', flush=True)
    while True:                # game opened, scenario entered, left, another loaded, game closed and reopened...
        cli, root = connect(cfg)
        try:
            while True:
                try:
                    run(wait_game(cfg, log, cli, root))
                except GameSlow as e:      # stop sending at once, keep the hook; resume when it answers quickly
                    print('El juego va lento (%s): SP Chat deja de enviarle órdenes y prueba cada 15 s.' % e, flush=True)
                    log('emergency_pause', {'why': str(e)})
                    wait_until_quick(cli, log)
        except KeyboardInterrupt:      # the only real exit: give the game its main-loop call back
            print('SP Chat se cierra: quito el gancho del juego.', flush=True)
            try:
                cli.unhook()
            except OSError:
                pass
            raise
        except OSError:
            print('Making History se cerró.', flush=True)
        finally:
            try:
                cli.detach()       # lets go of the process; the hook stays for the next start (restart, reconnect)
            except OSError:
                pass             # the game is gone: nothing to give back


if __name__ == '__main__':
    main()
