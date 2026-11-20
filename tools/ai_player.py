"""AI player for Making History I / Gold multiplayer games.

Runs the game's own headless core (bin/console.exe, driven by mh_console.py), joins a hosted LAN/IP game as one
nation, then reads the chat and game state and lets an LLM (provider settings shared with the editor's AI chat,
ai_chat.py) talk and act for that nation.

Usage:  python ai_player.py [--config FILE]       (settings: see DEFAULTS; the file is created on first run)
"""
import argparse
import ctypes
import datetime
import json
import os
import re
import socket
import struct
import sys
import threading
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gamepaths            # noqa: E402
from mh_console import Console  # noqa: E402

DEFAULTS = {
    'game': 'mh1',                 # mh1 | gold
    'host': '',                    # IP of the computer hosting the game ('' = this computer)
    'game_name': '',               # hosted game to join ('' = the first one found)
    'country': 'Chile',            # nation (player name) the AI takes
    'name': 'AI',                  # name shown as the player's owner and in the chat: 'Chile(AI):'
    'personality': 'Un estadista pragmático y cordial que defiende los intereses de su nación.',
    'goals': 'Sobrevivir, prosperar y mantener buenas relaciones con los demás jugadores humanos.',
    'language': 'es',
    'poll_seconds': 5,
    'auto_end_turn': True,         # end our turn every turn (the game waits for every player)
    'autopilot': True,             # research, production, new units and popups run locally, like a CPU nation
    'license_key_gold': '',        # a second key the user owns, per game (keys don't work across games):
    'license_key_mh1': '',         # one key = one player in a game
}
# outside the project folder (it can hold a license key): next to the editor's AI provider settings
CONFIG = os.path.join(os.path.expanduser('~'), '.mheditor', 'ai_player.json')
LOGS = os.path.join(gamepaths.ROOT, 'logs')

PROP = re.compile(r'Property: \d{3} (.*)$')   # then fixed columns: name 23, type 16, subtype 17, value
REF = re.compile(r'\[(\d+) => Object: (-?\d+)\]')


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


class Bot:
    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        game = gamepaths.GAMES[cfg['game']]['path']
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        self.con = Console(game, os.path.join(LOGS, 'ai_console_%s.log' % stamp))
        # one command at a time on the console: the turn watcher thread (run) slips in between the others
        lock, cmd = threading.RLock(), self.con.cmd

        def locked(*a, **k):
            with lock:
                return cmd(*a, **k)
        self.con.cmd, self.lock = locked, lock

    # --- reading objects through the CLI -------------------------------------------------------------------
    def show(self, oid):
        """Properties of one object: {name: value text}, and {name: [object ids]} for lists."""
        out = self.con.cmd('show object %d' % oid)
        props, refs, cur = {}, {}, None
        m = re.search(r'Object: ID: \d+ .*?Checkpoint: \d+\s+(\S+)', out, re.S)   # header may wrap
        if m:
            props['__type'] = m.group(1)
        for line in out.splitlines():
            m = PROP.search(line)
            if m:
                rest = m.group(1)                  # the console strips trailing blanks, so slice, don't pad
                cur = rest[:23].strip()
                props[cur] = rest[56:].strip()
                continue
            m = REF.search(line)
            if m and cur:
                refs.setdefault(cur, []).append(int(m.group(2)))
            elif cur and line.strip() and not line.startswith(('LOG:', '>')):   # value spanning several lines
                props[cur] = (props[cur] + '\n' + line).strip()
        return props, refs

    def refs(self, oid, prop):
        """Every object id in a list property ('show object' prints only the first 5 of each list)."""
        return [int(m.group(2)) for m in REF.finditer(self.con.cmd('dump property %d %s' % (oid, prop)))]

    def obj_id(self, value):
        m = re.match(r'Object: (-?\d+)', value)
        return int(m.group(1)) if m else -1

    # --- joining ------------------------------------------------------------------------------------------
    def join(self):
        c, cfg = self.con, self.cfg
        if not c.wait_ready():
            raise RuntimeError('console.exe did not start')
        c.enable_dev_mode()
        key = cfg.get('license_key_' + cfg['game']) or cfg.get('license_key')   # 'license_key': older configs
        if key:
            if not c.set_license_key(key):
                raise RuntimeError('could not find the installed license key in console.exe to replace it')
            self.log('license_key', {'replaced': True})
        c.skip_parse('CActAddChat')      # its CLI parser crashes; see Console.skip_parse
        c.use_own_namespace()            # actions must resolve in our namespace when the normal game hosts
        c.set_chat_name(cfg['name'])     # chat lines read 'Country(name):'
        c.enable_dispatch()              # 'action ActPauseGame <id>' sends object <id> (treaties...)
        c.cmd('action logging on')    # prints "Avatar ..., <country>, playing game N ... received <Action>"
        # 'init network' alone opens a session of our own; joining needs the host's address ('' = this computer)
        host = cfg['host'] or socket.gethostbyname(socket.gethostname())
        out = c.cmd('init network %s' % host)
        me = re.search(r'Session ID for this Driver: (\d+)', out) or c.wait_for(r'Session ID for this Driver: (\d+)')
        if not me:
            raise RuntimeError('could not connect to the game host at %s (is a multiplayer game open there?)' % host)
        my_session = int(me.group(1))
        # the CDriver object (75 in MH1): listed in the object store (object 0)
        driver = next((o for o in self.show(0)[1].get('objAllObjects', []) if self.show(o)[0].get('__type') == 'Driver'),
                      None)
        if driver is None:
            raise RuntimeError('could not find the game driver object')
        hosts, gi, asked = {}, None, set()   # hosts: DriverState id -> session (several games can be hosted)
        for _ in range(45):   # wait for the hosts' DriverStates, then their GameInfos, to replicate
            _, refs = self.show(driver)
            for d in refs.get('objDriverStates', []):
                p, _ = self.show(d)
                if p.get('nSessionID') and int(p['nSessionID']) != my_session and int(p.get('nNumHostedGames') or 0):
                    hosts[d] = int(p['nSessionID'])
            for d, s in hosts.items():
                if d not in asked:
                    c.cmd('request DOs %d objGameInfos' % d)
                    asked.add(d)
                for g in self.show(d)[1].get('objGameInfos', []):
                    p, _ = self.show(g)
                    if not cfg['game_name'] or p.get('strName') == cfg['game_name']:
                        gi, info, session = g, p, s
            if gi:
                break
            time.sleep(2)
        if not hosts:
            raise RuntimeError('no hosted game found at %s' % (cfg['host'] or 'this computer'))
        if not gi:
            raise RuntimeError('game %r not found on the host' % cfg['game_name'])
        self.log('game', {'name': info.get('strName'), 'scenario': info.get('strScenario'), 'session': session})
        self.scenario = info.get('strScenario')
        c.cmd('addref scenario "%s" "%s"' % (info.get('strContentPack') or 'Modern Europe', info['strScenario']),
              timeout=180)
        c.cmd('request DOs %d objScenario %d' % (gi, session))
        c.cmd('request DOs %d objGameState %d' % (gi, session))
        for _ in range(60):
            p, _ = self.show(gi)
            if self.obj_id(p.get('objGameState', '')) > 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('the host did not send the game state')
        c.cmd('action ActJoinGame %s "%s" "%s" %d false' % (info['nGameID'], cfg['country'], cfg['name'], session))
        if not c.wait_for(r'Avatar\s+\d+,\s+%s, playing game' % re.escape(cfg['country']), timeout=300):
            raise RuntimeError('join was not confirmed (is %s free and playable?)' % cfg['country'])
        self.session, self.game_id, self.driver = session, int(info['nGameID']), driver
        self.log('joined', {'country': cfg['country']})
        # scenario actions (declare war, forces...) live in the scenario's namespace: make 'action' use it
        for _ in range(30):
            m = re.search(r'NS: (\d+)', self.con.cmd('show object %d' % self._data())) if self.player() > 0 else None
            if m:
                c.set_action_namespace(int(m.group(1)))
                c.set_create_namespace(int(m.group(1)))
                self.log('namespace', {'ns': int(m.group(1))})
                break
            time.sleep(2)
        self.client = True      # objects created here crash console.exe (replicated storage): see send_action
        c.cmd('action ActReadyToStartGame')   # like pressing 'ready' in the lobby, so the host can start

    # --- chat ---------------------------------------------------------------------------------------------
    def player(self):
        """Our Player object id; cached once known (it doesn't change during a game, and every read costs ~1 s)."""
        if getattr(self, '_pid', -1) > 0:
            return self._pid
        avatar = self.obj_id(self.show(self.driver)[0].get('objMyAvatar', ''))
        pid = self.obj_id(self.show(avatar)[0].get('objPlayer', '')) if avatar > 0 else -1
        if pid > 0 and self.show(pid)[0].get('objGameState', 'Object: -1') != 'Object: -1':
            self._pid = pid
        return pid

    def chats(self):
        """{chat object id: [(speaker, text), ...]} for the chats our player is part of (Player.objChat). Each line
        of a chat's strBigChat reads 'Country(owner name):text'."""
        out, pid = {}, self.player()
        if pid < 0:              # state not readable right now (e.g. while the game starts): try next round
            return out
        mine = self.refs(pid, 'objChat')
        # also every chat in the game (ChatList) that lists our country, e.g. a general chat with all players
        cl = self.obj_id(self.fixed(pid).get('objChatList', ''))
        for oid in self.refs(cl, 'objGOs') if cl > 0 else []:
            member = self.__dict__.setdefault('_member', {})
            if oid not in member:      # membership is read once per chat (each check costs several CLI calls)
                member[oid] = self.cfg['country'] in [
                    self.show(w)[0].get('strString') for w in self.refs(oid, 'objPlayers')]
            if oid not in mine and member[oid]:
                mine.append(oid)
                self.__dict__.setdefault('general', set()).add(oid)      # shared chat: answer only when @mentioned
        for oid in mine:
            lines, p = [], self.show(oid)[0]
            if p.get('__type') == 'Chat' and 'strBigChat' not in p:
                # console.exe drops the whole property line once the chat text passes ~4 KB: the chat goes silent
                self.trim_chat(oid, p, [])
                p = self.show(oid)[0]
            elif len(p.get('strBigChat') or '') > self.CHAT_KEEP_CHARS:
                self.trim_chat(oid, p, (p['strBigChat']).splitlines())
                p = self.show(oid)[0]
            for line in (p.get('strBigChat') or '').splitlines():
                m = re.match(r'([^():]+)\(([^)]*)\):(.*)', line)
                if m:
                    lines.append((m.group(1).strip(), m.group(3).strip()))
                elif lines:
                    lines[-1] = (lines[-1][0], lines[-1][1] + ' ' + line.strip())
            out[oid] = lines
        return out

    CHAT_KEEP_CHARS = 2500      # well under the ~4 KB console.exe still prints

    def trim_chat(self, oid, props, old_lines):
        """Replaces a chat's text with one line so the console can keep printing it, and resets our 'seen' mark.
        A long chat is trimmed only once every line was read; an unreadable one (old_lines empty) gets a note.
        shortcut: keeps a single line because a newline can't be typed into the console's 'set property'."""
        seen = getattr(self, 'seen', None)
        if old_lines and (seen is None or seen.get(oid, 0) < len(old_lines)):
            return      # unread lines: trim on a later round
        keep = old_lines[-1] if old_lines else (
            '%s(AI):(historial del chat recortado; si me escribiste algo, repitelo)' % self.cfg['country'])
        try:
            self.send_action('ActAlterPropertyImmed', {'nGOID': int(props['nGameObject']), 'strPropName': 'strBigChat',
                                                       'bAppend': False, 'strNewValue': keep.replace('"', "'")})
        except Exception as e:
            self.log('chat_trim_error', {'chat': oid, 'error': str(e)[:200]})
            return
        if seen is not None:
            seen[oid] = 1
        self.log('progress', {'text': 'Chat %d recortado' % oid})

    def open_chat(self, *countries):
        """Starts a chat with these countries (ActAddChat creates one with only us, ActAddPlayerToChat adds each)."""
        before = set(self.chats())
        self.con.cmd('action ActAddChat x')       # its CLI parser is skipped (see Console.skip_parse)
        for _ in range(20):
            new = [o for o in self.chats() if o not in before]
            if new:
                gid = int(self.show(new[0])[0].get('nGameObject') or -1)
                for country in countries:
                    self.con.cmd('action ActAddPlayerToChat %d "%s"' % (gid, country))
                return new[0]
            time.sleep(1)
        return None

    def say(self, chat_oid, text):
        """Appends a line to a chat, as the chat window does (ActAddToChat on the chat's strBigChat). Takes the
        chat's local object id; ActAddPlayerToChat takes its GOID (nGameObject) instead."""
        # the game's command line drops every non-ASCII key: 'preocupación' would arrive as 'preocupacin'
        text = unicodedata.normalize('NFKD', text.replace('ñ', 'n').replace('Ñ', 'N'))
        text = ''.join(ch for ch in text if ord(ch) < 128 and ch != '"')
        text = ' '.join(text.split())[:400] or '...'      # also turns line breaks into spaces
        self.con.cmd('action ActAddToChat %d strBigChat "%s"' % (chat_oid, text))

    BUSY_REPLY = 'El mensaje de %s viene en camino.'      # %s = our own nation

    def addressed(self, oid, text):
        """True if a chat line is for us: any private chat; the general chat only in chatty mode or when it names
        us ('@Greece', 'Greece', 'Grecia')."""
        if oid not in getattr(self, 'general', set()) or getattr(self, 'chatty', False) or EVERYONE.search(text):
            return True
        import unicodedata
        flat = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if unicodedata.category(c) != 'Mn')
        me = self.cfg['country']
        names = {me.lower()} | {k for k, v in self.ALIASES.items() if v == me}
        return any(re.search(r'(?<!\w)@?' + re.escape(n).replace(r'\ ', r'\s*') + r'(?!\w)', flat) for n in names)

    def ack_while_busy(self, progress=''):
        """While the bot is busy with a long local read (no LLM involved), acknowledges each new message at once
        so nobody waits in silence; the LLM answers them properly afterwards."""
        seen, acked = getattr(self, 'seen', None), self.__dict__.setdefault('_acked', {})
        if seen is None:
            return
        for oid, lines in self.chats().items():
            start = max(seen.get(oid, 0), acked.get(oid, 0))
            waiting = any(w != self.cfg['country'] and self.addressed(oid, t) for w, t in lines[start:])
            acked[oid] = len(lines)
            if waiting:
                self.say(oid, (self.cfg.get('busy_reply') or self.BUSY_REPLY).replace('%s', self.cfg['country']))
                acked[oid] += 1      # our own line
                self.log('progress', {'text': 'Aviso automatico: mensaje en camino. %s' % progress})

    # --- game state ---------------------------------------------------------------------------------------
    def players(self):
        """{country: (taken by, player object id)} for the human-held nations of the game (other than ours)."""
        pid = self.player()
        if pid < 0:
            return {}
        out, self.all_players = {}, {}      # all_players: country -> player object id (see run: chat speakers)
        # GameState.objTakenPlayers: only the taken nations (humans, and great powers marked 'AI Control')
        for oid in self.refs(self.obj_id(self.fixed(pid).get('objGameState', '')), 'objTakenPlayers'):
            q = self.show(oid)[0]
            self.all_players[q.get('strName')] = oid
            if q.get('strTakenBy') not in (None, '', 'AI Control') and q.get('strName') != self.cfg['country']:
                out[q['strName']] = (q['strTakenBy'], oid)
        return out

    def others_done(self, humans):
        """True when every other human player has ended the turn: we end ours with the last of them."""
        return all(self.show(oid)[0].get('bTurnEnded') == 'true' for _, oid in humans.values())

    def turn_ended(self):
        pid = self.player()
        return pid < 0 or self.show(pid)[0].get('bTurnEnded') == 'true'

    def maybe_end_turn(self, humans):
        """Local rule, not the LLM's: we end our turn as soon as every other human player has ended theirs."""
        if not self.cfg.get('auto_end_turn', True):
            return
        with getattr(self, 'lock', threading.RLock()):      # the watcher thread and the main loop both call this
            self._maybe_end_turn(humans)

    def _maybe_end_turn(self, humans):
        state = (self.turn_ended(), self.others_done(humans))
        if state != self.__dict__.get('_turn_state'):      # on change only: shows stale values if a turn stalls
            self._turn_state = state
            self.log('turn_state', {'we_ended': state[0], 'others_ended': state[1]})
        if state[0] or not state[1]:
            return
        if self.cfg.get('autopilot', True):      # play the turn (research, production) before ending it
            turn = self.show(self.obj_id(self.show(self._data())[0].get('objGameState', '')))[0].get('nCurrentTurn')
            waiting = self.__dict__.setdefault('_turn_wait', {}).setdefault(turn, time.time())
            if turn != getattr(self, '_autopilot_turn', None) and time.time() - waiting < 300:
                return
        self.con.cmd('action ActEndTurn')
        self.__dict__.pop('_improved', None)      # improve_relations: once per country and turn
        self.log('end_turn', {})
        self.new_turn = True      # /parlanchin: run() comments on the new turn in the general chat

    # --- sending actions ---------------------------------------------------------------------------------
    def cli(self, act, *args):
        """'action <Act> <args>': most actions take 'property value' pairs on the game's command line."""
        q = lambda v: '"%s"' % v if isinstance(v, str) and (' ' in v or not v) else str(v)
        if act.startswith(('ActPropose', 'ActForm')) and 'strPlayer' not in args[::2] and len(args) % 2 == 0:
            # treaty actions without strPlayer leave an unanswerable decision that freezes the end of turn
            args = tuple(args) + ('strPlayer', self.cfg['country'])
        out = self.con.cmd('action %s %s' % (act, ' '.join(q(x) for x in args)), timeout=60)
        if 'Unable to parse action type' in out and len(args) % 2 == 0:
            # joined to another host, the CLI only knows the core actions (Console.use_own_namespace); the
            # scenario's own (ActPropose*, ActInc*Size) are built in our player's data and dispatched instead
            return self.send_action(act, dict(zip(args[::2], args[1::2])))
        self.log('sent', {'action': act, 'args': list(args)})
        if 'Usage:' in out or 'Invalid arguments' in out or 'Bad property' in out:
            raise RuntimeError('%s rejected: %s' % (act, out.strip().splitlines()[-2:]))
        return out

    def _new_child(self, dest, prop, def_name):
        """Creates a default 'def_name' object in dest.prop with the CLI and returns its object id."""
        before = set(self.refs(dest, prop))
        self.con.cmd('create %d %s %s' % (dest, prop, def_name))
        out = self.con.cmd('dump property %d %s' % (dest, prop))
        new = [int(m.group(2)) for m in REF.finditer(out) if int(m.group(2)) not in before]
        one = re.search(r'Object: (\d+)\s*$', out, re.M)      # a single embedded object, not a list
        return new[-1] if new else int(one.group(1)) if one else -1

    def _set(self, oid, values):
        for k, v in values.items():
            v = 'true' if v is True else 'false' if v is False else str(v)
            self.con.cmd('set property %d %s %s' % (oid, k, v if v and ' ' not in v else '"%s"' % v))

    def send_action(self, def_name, values, children=()):
        """For actions the command line can't build (child objects, or no CLI parser): builds the object with
        'create' / 'set property' in our avatar's own scratch list (objAvatarActions: local, unlike the host's
        replicated player data, where 'create' crashes a joined console.exe; Console.set_create_namespace lets it
        hold the scenario's types), adds children [(list property, def, {values})], and sends it the way the
        game's CmdCreateAction does (see Console.enable_dispatch)."""
        avatar = self.obj_id(self.show(self.driver)[0].get('objMyAvatar', ''))
        oid = self._new_child(avatar, 'objAvatarActions', def_name) if avatar > 0 else -1
        if oid < 0:
            raise RuntimeError('could not create %s' % def_name)
        self._set(oid, dict(values, strPlayer=self.cfg['country']))
        for prop, child, vals in children:
            c = self._new_child(oid, prop, child)
            if c < 0:
                raise RuntimeError('could not create %s' % child)
            self._set(c, vals)
        out = self.con.cmd('action ActPauseGame %d' % oid)   # dispatcher: sends object 'oid' (no pause)
        self.log('sent', {'action': def_name, 'values': values, 'children': [list(c) for c in children]})
        return out

    # --- diplomacy ----------------------------------------------------------------------------------------
    def game_obj(self):
        """Our local MEGame object (the 'show ...' reports take it); the player works where it is missing."""
        games = self.refs(self.driver, 'objGames')
        return games[0] if games else self.player()

    def country_ids(self):
        """{country name: nCountryID} from our View's Country objects (two short reads per nation, a few minutes
        in all: run() does it once in a quiet moment)."""
        while self.country_ids_step(50):
            pass
        return self._country_ids

    def country_ids_step(self, n=8):
        """Reads the ids of the next n nations; False when all are known (run() calls it in quiet moments)."""
        if getattr(self, '_ids_todo', None) is None:
            view = self.obj_id(self.fixed(self.player()).get('objView', ''))
            self._ids_todo, self._ids_partial = self.refs(view, 'objCountries'), {}
        for c in self._ids_todo[:n]:
            nm = re.search(r'strName\s+String\s+(.+)', self.con.cmd('dump property %d strName' % c))
            i = re.search(r'nCountryID\s+int\s+(-?\d+)', self.con.cmd('dump property %d nCountryID' % c))
            if nm and i:
                self._ids_partial[nm.group(1).strip()] = int(i.group(1))
                self.__dict__.setdefault('_country_oids', {})[nm.group(1).strip()] = c      # move_troops
        self._ids_todo = self._ids_todo[n:]
        if not self._ids_todo:
            self._country_ids = self._ids_partial
        return bool(self._ids_todo)

    def country_id(self, name=None):
        name = self.country_name(name or self.cfg['country'])
        known = getattr(self, '_country_ids', None) or {}
        if name in known:
            return known[name]
        if name == self.cfg['country']:      # ours: one read of our Country object, kept
            if getattr(self, '_my_id', None) is None:
                c = self.obj_id(self.show(self.player())[0].get('objCountry', ''))
                self._my_id = int(self.show(c)[0].get('nCountryID', -1)) if c > 0 else None
            if self._my_id is not None and self._my_id >= 0:
                return self._my_id
        out = self.con.cmd('show diplomatic relations %d "%s"' % (self.game_obj(), name))   # works when we host
        m = re.search(r'for country .+? \((\d+)\)', out)
        if m:
            return int(m.group(1))
        if not known:
            raise RuntimeError('todavía leyendo los países; inténtalo en un momento')
        return -1

    def proposals(self):
        """Treaties proposed to or by us that are waiting for an answer: [{id, type, from, to, ...}]."""
        pid = self.player()
        if pid < 0:
            return []
        tl = self.obj_id(self.fixed(pid).get('objTreatyList', ''))
        out, me = [], self.cfg['country']
        for oid in self.refs(tl, 'objProposedTreaties') if tl > 0 else []:
            p, refs = self.show(oid)
            if me not in (p.get('strFromCountry'), p.get('strToCountry')):
                continue
            t = {'id': p.get('nTreatyID'), 'tipo': p.get('strTreatyDefType'), 'de': p.get('strFromCountry'),
                 'para': p.get('strToCountry')}
            for k in ('nMoney', 'bRequest', 'bDemand', 'nWarID'):
                if p.get(k) not in (None, '', '0', 'false'):
                    t[k] = p[k]
            for lst in ('objResources', 'objResourcesOffered', 'objResourcesRequested'):
                items = [self.show(r)[0] for r in refs.get(lst, [])]
                if items:
                    t[lst] = {i.get('strResource'): i.get('nAmount') for i in items}
            out.append(t)
        return out

    def answer(self, treaty_id, accept):
        return self.cli('ActAcceptTreaty' if accept else 'ActRejectTreaty', 'nTreatyID', int(treaty_id))

    # the game's own proposal actions (actionDefs.xml): each one carries its treaty
    TREATIES = {'guerra': 'ActProposeDeclareWar', 'alianza': 'ActProposeDefensePact',
                'no_agresion': 'ActProposeNonAggression', 'acceso_militar': 'ActProposeMilitaryAccess',
                'paz': 'ActProposeSeparatePeaceEndWar', 'comercio': 'ActProposeTradeDeal', 'ayuda': 'ActProposeAid'}

    def region_id(self, name, country=None):
        """nRegionID of a region of ours (or of 'country'), by name, from that country's Region objects (cached)."""
        owner = self.country_name(country or self.cfg['country'])
        cache = self.__dict__.setdefault('_regions', {})
        if owner not in cache:
            c = (self.obj_id(self.fixed(self.player()).get('objCountry', '')) if owner == self.cfg['country']
                 else self.__dict__.get('_country_oids', {}).get(owner, -1))
            if c < 0:
                raise RuntimeError('todavia no conozco los objetos de %s; intentalo en un momento' % owner)
            cache[owner] = {p.get('strName', '').lower(): int(p.get('nRegionID', -1))
                            for p in (self.show(r)[0] for r in self.refs(c, 'objRegions'))}
        key = name.strip().lower()
        if key in cache[owner]:
            return cache[owner][key]
        import difflib
        m = difflib.get_close_matches(key, list(cache[owner]), n=1, cutoff=0.7)
        if not m:
            raise RuntimeError('%s no tiene la region %s' % (owner, name))
        return cache[owner][m[0]]

    def propose(self, kind, country, offer=None, request=None, money=0, war_id=None):
        """Proposes a treaty to 'country' (declaring war is one too: it takes effect at once).
        offer / request: {resource: amount} for trade and aid; money: aid in money."""
        if kind == 'romper_alianza':      # the alliance window's 'Break'
            return self.cli('ActCancelDefensePact', 'strCountry', country)
        if kind == 'territorio':          # offer / request: region names (ours / theirs)
            refs = [('objRegionsOffered', 'RegionRef', {'nRegionID': self.region_id(r)}) for r in offer or []]
            refs += [('objRegionsRequested', 'RegionRef', {'nRegionID': self.region_id(r, country)})
                     for r in request or []]
            if not refs:
                raise RuntimeError('ninguna region que transferir')
            return self.send_action('ActProposeTerritorialTransfer', {'strToCountry': country, 'bDemand': False}, refs)
        act = self.TREATIES[kind]
        if kind == 'paz':
            return self.cli(act, 'strToCountry', country, 'nSourceCountryID', self.country_id(),
                            'nWarID', int(war_id if war_id is not None else -1))
        if kind not in ('comercio', 'ayuda'):
            return self.cli(act, 'strToCountry', country)
        pair = lambda prop, res: [(prop, 'ResourceAmountPair', {'strResource': k, 'nAmount': int(v)})
                                  for k, v in (res or {}).items() if int(v) > 0]
        # one resource per list and treaty: the lists are keyed by strResource, which 'create' can't set before the
        # object is stored, so a second pair lands on the same (empty) key and replaces the first (tested offline)
        import itertools
        if kind == 'comercio':
            gives, gets = pair('objResourcesOffered', offer), pair('objResourcesRequested', request)
            if not gives and not gets:
                raise RuntimeError('ningún recurso que comerciar')
            return [self.send_action(act, {'strToCountry': country}, [k for k in kids if k])
                    for kids in itertools.zip_longest(gives, gets)][-1]
        kids = pair('objResources', offer or request) or [None]
        return [self.send_action(act, {'strToCountry': country, 'nMoney': int(money or 0) if i == 0 else 0,
                                       'bRequest': bool(request and not offer)}, [k] if k else [])
                for i, k in enumerate(kids)][-1]

    def embargo(self, country, on=True):
        return self.cli('ActSetTradeRelations', country, 'TRADE_RELATIONS_EMBARGOED' if on else 'TRADE_RELATIONS_NEUTRAL')

    RELATIONS_STEP = 25      # per country and turn: a goodwill gesture, not a way to rewrite diplomacy

    def improve_relations(self, country, worsen=False):
        """ActIncDipRelations (what scenario events use; it has no command-line parser), both ways."""
        done = self.__dict__.setdefault('_improved', set())     # cleared when we end the turn
        if country in done:
            raise RuntimeError('relations with %s were already improved this turn' % country)
        me, them = self.country_id(), self.country_id(country)
        if me < 0 or them < 0:
            raise RuntimeError('unknown country %s' % country)
        for a, b in ((me, them), (them, me)):
            self.send_action('ActIncDipRelations', {'nSourceCountryID': a, 'nTargetCountryID': b,
                                                    'nAmount': -self.RELATIONS_STEP if worsen else self.RELATIONS_STEP})
        done.add(country)

    def tone_relations(self, country, step):
        """+-step both ways between us and 'country' (ActIncDipRelations), kept within the game's 0-1000."""
        import sp_chat
        me = self.cfg['country']
        for a, b in ((me, country), (country, me)):
            try:
                aid, cur = sp_chat.relation(self, a, b)
                bid = self.country_id(b)
                delta = max(-cur, min(1000 - cur, step))
            except Exception:      # relation not readable (e.g. joined game): the plain step
                aid, bid, delta = self.country_id(a), self.country_id(b), step
            if delta and aid >= 0 and bid >= 0:
                self.send_action('ActIncDipRelations', {'nSourceCountryID': aid, 'nTargetCountryID': bid, 'nAmount': delta})
        self.log('tone', {'with': country, 'step': step})

    FORCES = {'ejercito': 'ActIncArmySize', 'aviacion': 'ActIncAirForceSize', 'armada': 'ActIncNavySize'}

    def build_forces(self, branch, amount):
        """Raises the desired size of a branch; the game then spends production (armaments) on new units."""
        return self.cli(self.FORCES[branch], 'nTargetSize', max(1, min(int(amount), 10)))

    GOVS = ('Democratic', 'Authoritarian', 'Fascist', 'Communist', 'Despotist')

    def set_government(self, gov):
        return self.cli('ActSetCountryGov', self.cfg['country'], gov)

    def gov_type(self, country):
        """A nation's government type (strGovType of its Country object; others' once country_ids_step knows them)."""
        c = (self.obj_id(self.show(self.player())[0].get('objCountry', '')) if country == self.cfg['country']
             else self.__dict__.get('_country_oids', {}).get(country, -1))
        if c < 0:
            raise RuntimeError('todavía leyendo los países; inténtalo en un momento')
        return self.show(c)[0].get('strGovType')

    def as_nation(self, country, fn):
        """sp_chat's helpers act 'as' a nation: in multiplayer the bot only plays its own."""
        if country != self.cfg['country']:
            raise RuntimeError('solo puedo actuar como %s' % self.cfg['country'])
        return fn()

    def nations(self):
        """Every nation of the scenario (sp_chat's helpers take this from either bot)."""
        self.country_name('')
        return self._nations

    # --- popups, research, production ---------------------------------------------------------------------
    def _data(self):
        return self.obj_id(self.fixed(self.player()).get('objData', ''))

    def popups(self):
        """Open decision points (the game's accept / reject popups) other than treaty offers, which proposals()
        covers: [{id, titulo, tipo, opciones}]. Each one is read once (fixed)."""
        out = []
        for d in self.refs(self._data(), 'objDecisionPoints'):
            if d in self.__dict__.setdefault('_dp_done', set()):
                continue
            p = self.show(d)[0]
            if p.get('eDecisionState') != 'DECISION_OPEN':
                self._dp_done.add(d)
                continue
            label = self.fixed(self.obj_id(p.get('objDPRef', ''))).get('strTypeLabel', '')
            if label.startswith('Generic_TreatyProposed_SingleTo'):      # offers to us: proposals() has them
                self._dp_done.add(d)
                continue
            pop = {'id': p.get('nDPID'), 'titulo': p.get('strTitle'), 'tipo': label,
                   'opciones': [self.fixed(c).get('strKey') for c in self.refs(d, 'objDisplayChoices')]}
            if label.startswith('Generic_TreatyProposed'):
                # a vote in our alliance (e.g. another nation proposes a new member): it holds up the turn
                tl = self.obj_id(self.fixed(self.player()).get('objTreatyList', ''))
                pop['tratados_propuestos'] = [
                    {k: q.get(k) for k in ('nTreatyID', 'strTreatyDefType', 'strFromCountry', 'strToCountry')}
                    for q in (self.show(t)[0] for t in (self.refs(tl, 'objProposedTreaties') if tl > 0 else []))
                    if q.get('eTreatyState') == 'TREATY_PROPOSED']
            out.append(pop)
        return out

    def answer_popup(self, dp_id, choice):
        """ActSelectDPChoice, as the popup window sends it. The game checks the id of the notice at the head of
        our feedback queue (the one the UI would be showing), so we pass that one."""
        fm = self.obj_id(self.show(self._data())[0].get('objFeedbackRefManager', ''))
        queue = self.obj_id(self.show(fm)[0].get('objRefQueue', ''))
        head = next((q for q in (self.show(r)[0] for r in self.refs(queue, 'objRefs')) if q.get('bHandled') != 'true'),
                    {})
        return self.send_action('ActSelectDPChoice', {'nDPID': int(dp_id), 'strChoiceKey': choice,
                                                      'nFeedbackRefID': int(head.get('nID', -1))})

    def research_options(self):
        """Research projects we can start (read once; the list only shrinks when we start one)."""
        if getattr(self, '_research', None) is None:
            gov = self.obj_id(self.show(self._data())[0].get('objGovData', ''))
            rs = self.obj_id(self.show(gov)[0].get('objResearchState', ''))
            self._research = [q.get('strProjectName') for q in (self.show(o)[0] for o in
                              self.refs(rs, 'objResearchProjectStates')) if q.get('eResearchState') == 'RESEARCH_AVAILABLE']
        return self._research

    def research(self, project):
        out = self.cli('ActStartResearchProject', self.cfg['country'], project)
        if getattr(self, '_research', None) and project in self._research:
            self._research.remove(project)
        return out

    OUTPUTS = ('Armaments', 'Consumer', 'Industrial', 'Advanced', 'TransportCredits')

    def production(self, research_percent, rest='Armaments'):
        """Local planner: cities (biggest factories first) produce ResearchPoints up to that share of our IPUs
        (never more than research can use), the rest 'rest'. Sends a work order only where it changes."""
        cities = self._cities()
        gov = self.obj_id(self.show(self._data())[0].get('objGovData', ''))
        needed = int(self.show(self.obj_id(self.show(gov)[0].get('objResearchState', '')))[0].get('nNeededIPUs') or 0)
        total = sum(c[0] for c in cities)
        target = min(total * max(0, min(int(research_percent), 100)) // 100, needed or total)
        changed, got = 0, 0
        for ipus, goid, order, _ in sorted(cities, reverse=True):
            want = 'ResearchPoints' if got < target and ipus > 0 else rest
            got += ipus if want == 'ResearchPoints' else 0
            if want != order:
                self.cli('ActSetWorkOrder', want, int(goid))
                changed += 1
        return 'investigación %d de %d IPUs; %d ciudades cambiadas' % (got, total, changed)

    # --- autopilot: the CPU AI's routine for our nation, done locally (no LLM) -----------------------------
    # The game's own CPU mode can't be switched on for a joined player (ActToggleAI only re-enables AI
    # processing; bAIControlled is set only inside game.dll), so we imitate its planning modules here:
    # PMManageResearch, PMManageProduction / PMEconomic, PMBuildUnits, and the default answer of popups.
    UNIT_MIX = ('Infantry Division', 'Armored Division', 'Mounted Infantry Division', 'Fighter Squadron')
    POPUP_HOLD_SECONDS = 60      # alliance votes wait this long for the LLM before the default answer goes

    def _defs(self):
        """Read once from the game's XML (ScenarioDefaults + the scenario's own files): each popup's default answer
        for players who don't answer (strDefaultChoicePlayer), research costs, and unit outputs
        {name: (category, tech level, IPUs)}."""
        if getattr(self, '_game_defs', None) is None:
            base = os.path.join(gamepaths.GAMES[self.cfg['game']]['path'], 'Modern Europe')
            roots = [os.path.join(base, 'system', 'ScenarioDefaults')] + [
                os.path.join(base, w, 'scenarios', self.scenario) for w in ('system', 'user') if getattr(self, 'scenario', '')]
            token = re.compile(r'<object type="(\w+)"|<property name="(\w+)" value="([^"]*)"')
            dp, cost, units = {}, {}, {}
            for root in roots:
                for d, _, files in os.walk(root):
                    for f in files:
                        if not f.lower().endswith('.xml'):
                            continue
                        cur = {}
                        with open(os.path.join(d, f), encoding='utf-8', errors='replace') as fh:
                            text = fh.read()
                        for m in token.finditer(text):      # an object's own properties come before its children
                            if m.group(1):
                                cur = {'type': m.group(1)}
                                continue
                            cur[m.group(2)] = v = m.group(3)
                            t, k = cur.get('type', ''), m.group(2)
                            if t == 'DecisionPointDef' and k == 'strDefaultChoicePlayer' and 'strTypeLabel' in cur:
                                dp[cur['strTypeLabel']] = v
                            elif t.startswith('ResearchProj') and k == 'nResearchPoints' and v.isdigit():
                                cost[cur.get('strName')] = int(v)
                            elif t == 'FactoryOutputUnit' and k == 'eDisplayFlags':
                                units[cur.get('strName')] = (cur.get('strDisplayCategory'), int(cur.get('nTechLevel') or 0),
                                                             int(cur.get('nIPUsRequired') or 0))
            self._game_defs = {'popups': dp, 'research': cost, 'units': units}
        return self._game_defs

    def popup_default(self, label, options):
        """What the game itself picks for a player who doesn't answer; else a cautious choice."""
        d = self._defs()['popups'].get(label)
        return d if d in options else next((o for o in ('Reject', 'Continue', 'OK') if o in options),
                                           options[0] if options else None)

    def autopilot_popups(self):
        """Answers open popups (ours and the alliance votes that hold up the turn) with the default answer.
        Treaty votes and offers wait POPUP_HOLD_SECONDS first: run() shows them to the LLM, which may decide."""
        done, now = [], time.time()
        seen = self.__dict__.setdefault('_dp_seen', {})
        answered = self.__dict__.setdefault('_dp_answered', set())
        for d in self.refs(self._data(), 'objDecisionPoints'):
            if d in self.__dict__.get('_dp_done', ()) or d in answered:
                continue
            p = self.show(d)[0]
            if p.get('eDecisionState') != 'DECISION_OPEN':
                continue
            label = self.fixed(self.obj_id(p.get('objDPRef', ''))).get('strTypeLabel', '')
            if label.startswith('Generic_TreatyProposed') and now - seen.setdefault(d, now) < self.POPUP_HOLD_SECONDS:
                continue
            choice = self.popup_default(label, [self.fixed(c).get('strKey') for c in self.refs(d, 'objDisplayChoices')])
            if choice:
                self.answer_popup(p.get('nDPID'), choice)
                answered.add(d)
                done.append('%s=%s' % (label, choice))
        return done

    def autopilot_turn(self, at_war=None):
        """Once per turn: keep a research project going, plan the cities' work orders (research, new units,
        consumer goods, armaments) and so grow the forces. '' when this turn is already done."""
        gs = self.obj_id(self.show(self._data())[0].get('objGameState', ''))
        turn = self.show(gs)[0].get('nCurrentTurn')
        if turn is None or turn == getattr(self, '_autopilot_turn', None):
            return ''
        self._autopilot_turn = turn      # set first: a failing step is logged once, not retried every round
        if at_war is None:
            try:
                at_war = bool(self.war_sides()[1])
            except Exception:      # country ids still loading (joined game): plan as in peace
                at_war = False
        return 'turno %s: %s' % (turn, '; '.join(x for x in (self._auto_research(), self._auto_production(at_war)) if x))

    def _auto_research(self):
        """PMManageResearch: one project at a time, the cheapest available (steady progress up the tree)."""
        gov = self.obj_id(self.show(self._data())[0].get('objGovData', ''))
        rs = self.obj_id(self.show(gov)[0].get('objResearchState', ''))
        if int(self.show(rs)[0].get('nNeededIPUs') or 0) > 0:      # a project is in progress: one cheap read
            return ''
        states = [self.show(o)[0] for o in self.refs(rs, 'objResearchProjectStates')]
        self.__dict__.pop('_can_build', None)      # a project just ended: new units may be available
        avail = [q.get('strProjectName') for q in states if q.get('eResearchState') == 'RESEARCH_AVAILABLE']
        if not avail:
            return ''
        cost = self._defs()['research']
        pick = min(avail, key=lambda n: cost.get(n, 10 ** 9))
        self.research(pick)
        self._research = [n for n in avail if n != pick]
        return 'investiga %s' % pick

    def _cities(self):
        """[(IPUs, city GOID, current work order, factory tech level)] of our cities."""
        country = self.obj_id(self.fixed(self.player()).get('objCountry', ''))
        known = self.__dict__.setdefault('_city_factory', {})      # city object -> (GOID, factory object)
        out = []
        for c in self.refs(country, 'objCities'):
            if c not in known:
                p = self.show(c)[0]
                known[c] = (p.get('nGameObject'), self.obj_id(p.get('objFactory', '')))
            goid, fac = known[c]
            f = self.show(fac)[0]
            order = self.show(self.obj_id(f.get('objWorkOrder', '')))[0].get('strFactoryOutputName') or ''
            out.append((int(f.get('nIPUs') or 0), goid, order, int(f.get('nTechLevel') or 0)))
        return out

    def _auto_production(self, at_war):
        """PMManageProduction + PMBuildUnits: share our IPUs between research (what the project needs, at most
        25% / 10% at war), new units (10% in peace if armaments cover upkeep; 20% at war, 10% if they don't) and
        the rest consumer goods up to what they lack (demand less a fifth of the stock above one turn), then
        armaments. Cities keep their order while its share lasts; only the others are switched."""
        country = self.obj_id(self.fixed(self.player()).get('objCountry', ''))
        res = {q.get('strName'): q for q in (self.show(r)[0] for r in self.refs(country, 'objResources'))}

        def lack(name):
            dem, stock = int(res.get(name, {}).get('nDemand') or 0), int(res.get(name, {}).get('nAmount') or 0)
            return max(0, dem - max(0, stock - dem) // 5)
        gov = self.obj_id(self.show(self._data())[0].get('objGovData', ''))
        needed = int(self.show(self.obj_id(self.show(gov)[0].get('objResearchState', '')))[0].get('nNeededIPUs') or 0)
        if getattr(self, '_can_build', None) is None:      # changes only when research ends (_auto_research)
            tab = self.obj_id(self.show(gov)[0].get('objAvailableFactoryOut', ''))
            self._can_build = {self.show(o)[0].get('strOutputName') for o in self.refs(tab, 'objFactoryOutputs')}
        can = self._can_build
        defs = self._defs()['units']
        # the best unit of each kind a factory of that tech level can build (the game refuses the others)
        best = lambda tech: [n for n in (max((n for n in can if defs.get(n, ('',))[0] == cat and defs[n][1] <= tech),
                                             key=lambda n: defs[n][1:], default=None) for cat in self.UNIT_MIX) if n]
        cities = sorted((c for c in self._cities() if c[0] > 0), reverse=True)
        total = sum(c[0] for c in cities)
        arms = res.get('Armaments', {})
        covered = int(arms.get('nAmount') or 0) >= int(arms.get('nDemand') or 0)
        unit_pct = (20 if covered else 10) if at_war else 10 if covered else 0
        share = {'ResearchPoints': min(needed, total * (10 if at_war else 25) // 100),
                 'unit': total * unit_pct // 100 if best(max([c[3] for c in cities] or [0])) else 0}
        rest = total - sum(share.values())
        # goods first: a goods shortage costs IPUs (nGoodsPenalty) and revenue; the rest arms the upkeep
        share['Consumer'] = min(rest, lack('Consumer')) if lack('Armaments') else rest
        share['Armaments'] = rest - share['Consumer']
        kind = lambda order: 'unit' if order in defs else order if order in share else None
        todo = []
        for ipus, goid, order, tech in cities:      # keep what already fits (no lost start-up costs or unit progress)
            k = kind(order)
            if k is None:                     # factories, upgrades... chosen by someone else: leave them
                continue
            if share[k] > 0:
                share[k] -= ipus
            else:
                todo.append((ipus, goid, order, tech))
        changed, built = 0, []
        for ipus, goid, order, tech in todo:
            refused = self.__dict__.setdefault('_refused', set())      # (city, unit) the game turned down
            units = [n for n in best(tech) if (goid, n) not in refused]
            k = max((k for k in share if units or k != 'unit'), key=share.get)
            share[k] -= ipus
            for want in (units[len(built) % len(units):] + units[:len(built) % len(units)] if k == 'unit' else [k]):
                if want == order:
                    break
                if 'Failed to set factory output' not in self.cli('ActSetWorkOrder', want, int(goid)):
                    changed += 1
                    built += [want] if k == 'unit' else []
                    break
                refused.add((goid, want))      # e.g. a colony or a too-small factory: try the next kind
        return '%d ciudades cambiadas%s' % (changed, ' (unidades: %s)' % ', '.join(built) if built else '')

    def report(self, what, country=None):
        """Read-only views from the game's own console commands, as text for the LLM."""
        g = self.game_obj()
        me, country = self.cfg['country'], country or self.cfg['country']
        cmds = {'alianzas': 'show alliances %d all 1' % g, 'guerras': 'show wars %d all' % g,
                'relaciones': 'show diplomatic relations %d "%s"' % (g, country),
                'militar': 'show country MPU info %d "%s"' % (g, country),
                'militar_mundo': 'show world military MPU info %d' % g,
                'comercio': 'show trade relations %d "%s" "%s"' % (self.player(), me, country)}
        out = self.con.cmd(cmds[what], timeout=60)
        lines = [re.sub(r'^LOG:\s+\S+( - Info)? - \d+::\s?', '', l) for l in out.splitlines()[1:]]
        text = '\n'.join(l.rstrip() for l in lines if l.strip() and not l.startswith('>'))
        text = re.sub(r' *\((?:AID|OID|CAID|CID)[: ]+-?\d+\)', '', text)   # internal ids mean nothing to the LLM
        return re.sub(r' {3,}', '  ', text)[:6000]

    def _alliances(self):
        """(AllianceManager id, current alliance ids, current war ids), read from GameState like the game's UI."""
        gs = self.obj_id(self.fixed(self.player()).get('objGameState', ''))
        am = self.obj_id(self.show(gs)[0].get('objAllianceManager', '')) if gs > 0 else -1
        if am < 0:
            raise RuntimeError('alliance manager not readable yet')
        return am, self.refs(am, 'objCurrentAlliances'), self.refs(am, 'objCurrentWars')

    def fixed(self, oid):
        """show() for objects whose fields we use don't change (alliance members, wars, their sides): read once."""
        cache = self.__dict__.setdefault('_fixed', {})
        if oid not in cache:
            cache[oid] = self.show(oid)[0]
        return cache[oid]

    ALIASES = {'turquia': 'Turkey', 'turkiye': 'Turkey', 'alemania': 'Germany', 'reino unido': 'United Kingdom',
               'gran bretana': 'United Kingdom', 'inglaterra': 'United Kingdom', 'estados unidos': 'United States',
               'eeuu': 'United States', 'usa': 'United States', 'francia': 'France', 'italia': 'Italy',
               'grecia': 'Greece', 'rusia': 'USSR', 'urss': 'USSR', 'union sovietica': 'USSR', 'japon': 'Japan',
               'espana': 'Spain', 'rumania': 'Romania', 'hungria': 'Hungary', 'polonia': 'Poland', 'egipto': 'Egypt',
               'iran': 'Persia', 'brasil': 'Brazil', 'suecia': 'Sweden', 'suiza': 'Switzerland',
               'paises bajos': 'Netherlands', 'holanda': 'Netherlands', 'belgica': 'Belgium', 'mexico': 'Mexico',
               'finlandia': 'Finland', 'noruega': 'Norway', 'dinamarca': 'Denmark', 'checoslovaquia': 'Czechoslovakia',
               'canada': 'Canada', 'irak': 'Iraq', 'arabia saudita': 'Saudi Arabia', 'arabia saudi': 'Saudi Arabia',
               'siria': 'Syria', 'corea': 'Korea', 'tailandia': 'Siam', 'sudafrica': 'South Africa',
               'nueva zelanda': 'New Zealand', 'yugoslavia': 'Yugoslavia', 'peru': 'Peru', 'china': 'China'}

    def country_name(self, name):
        """The game's name for a country the model wrote ('Turquía', 'Türkiye' -> 'Turkey'): the scenario's
        player<Country>.xml files list every nation; Spanish names via ALIASES, then the closest match."""
        import difflib
        if getattr(self, '_nations', None) is None:
            base = os.path.join(gamepaths.GAMES[self.cfg['game']]['path'], 'Modern Europe')
            self._nations = set()
            for where in ('system', 'user'):
                d = os.path.join(base, where, 'scenarios', getattr(self, 'scenario', '') or '')
                if os.path.isdir(d):
                    self._nations |= {f[6:-4] for f in os.listdir(d) if f.startswith('player') and f.endswith('.xml')}
        name = (name or '').strip()
        if name in self._nations or not self._nations:
            return name
        key = ''.join(ch for ch in unicodedata.normalize('NFKD', name.lower()) if ord(ch) < 128).strip()
        for k in (key, key.split(' ')[0]):      # 'turquia el' (a word too many from the chat) -> 'turquia'
            if self.ALIASES.get(k) in self._nations:
                return self.ALIASES[k]
        flat = {squash(n): n for n in self._nations}      # 'UnitedStates', 'united_states', 'ReinoUnido'
        flat.update({squash(k): v for k, v in self.ALIASES.items() if v in self._nations})
        if squash(key) in flat:
            return flat[squash(key)]
        low = {n.lower(): n for n in self._nations}
        m = difflib.get_close_matches(key, list(low), n=1, cutoff=0.6)
        return low[m[0]] if m else name

    def historic_regions(self):
        """Regions our nation claims ('Historic' list in the scenario's player<Country>.xml, read from disk once)."""
        if getattr(self, '_historic', None) is None:
            self._historic = []
            base = os.path.join(gamepaths.GAMES[self.cfg['game']]['path'], 'Modern Europe')
            for where in ('user', 'system'):
                f = os.path.join(base, where, 'scenarios', getattr(self, 'scenario', '') or '', 'player%s.xml' % self.cfg['country'])
                if os.path.isfile(f):
                    text = open(f, encoding='utf-8', errors='replace').read()
                    m = re.search(r'value="Historic"/>(.*?)</object>', text, re.S)
                    self._historic = re.findall(r'strRegions" value="([^"]+)"', m.group(1)) if m else []
                    break
        return self._historic

    # --- troop movement ----------------------------------------------------------------------------------
    def land_map(self):
        """(region names by nRegionID, land adjacency {id: set of ids}) of the scenario's map: regions.bin (the
        game's nRegionID is its index, checked in Gold) plus map.xml's Connected/DisconnectedRegions. Read once."""
        if getattr(self, '_land', None) is None:
            import mhmap
            from xml.sax.saxutils import unescape
            me, name = os.path.join(gamepaths.GAMES[self.cfg['game']]['path'], 'Modern Europe'), 'World'
            for where in ('user', 'system'):
                f = os.path.join(me, where, 'scenarios', getattr(self, 'scenario', '') or '', 'scenario.xml')
                if os.path.isfile(f):
                    m = re.search(r'strMapName" value="([^"]+)"', open(f, encoding='utf-8', errors='replace').read())
                    name = m.group(1) if m else name
                    break
            xml = os.path.join(me, 'system', 'DisplayLibraries', 'Maps', name, 'xml')
            regions = mhmap.read_regions_bin(open(os.path.join(xml, 'regions.bin'), 'rb').read())
            land = {r.index for r in regions if r.u_flag != 1}      # 1 = sea
            adj = {i: {n for n in regions[i].neighbors if n in land} for i in land}
            idx = {r.name: r.index for r in regions}
            text = open(os.path.join(xml, 'map.xml'), encoding='utf-8', errors='replace').read()
            for kind, a, b in re.findall(r'type="(Connected|Disconnected)Regions"[^>]*>\s*<property name="strRegionNameA" '
                                         r'value="([^"]*)"\s*/>\s*<property name="strRegionNameB" value="([^"]*)"', text):
                a, b = idx.get(unescape(a)), idx.get(unescape(b))
                if a in adj and b in adj:
                    op = set.add if kind == 'Connected' else set.discard
                    op(adj[a], b)
                    op(adj[b], a)
            # land + sea: armies cross water with sea transport (TransportCredits); the game routes the sea legs
            self._sea_adj = {r.index: set(r.neighbors) | adj.get(r.index, set()) for r in regions}
            self._land = [r.name for r in regions], adj
        return self._land

    def country_regions(self, name):
        """nRegionIDs a nation holds now (its Country object, once country_ids_step has found it in a quiet
        moment), else the ones it starts with (the scenario's country<Name>.xml: instant; finding the object on
        demand reads every nation's name, ~5 min)."""
        c = self.__dict__.get('_country_oids', {}).get(name, -1)
        if c > 0:
            return {int(self.fixed(r).get('nRegionID') or -1) for r in self.refs(c, 'objRegions')}
        names = self.land_map()[0]
        for where in ('user', 'system'):
            f = os.path.join(gamepaths.GAMES[self.cfg['game']]['path'], 'Modern Europe', where, 'scenarios',
                             getattr(self, 'scenario', '') or '', 'country%s.xml' % name)
            if os.path.isfile(f):
                held = set(re.findall(r'<object type="Region" name="objGOs">\s*<property name="strName" value="([^"]+)"',
                                      open(f, encoding='utf-8', errors='replace').read()))
                return {i for i, n in enumerate(names) if n in held}
        return set()

    def region_owners(self):
        """{nRegionID: owner} from the scenario's country<Name>.xml files, read once.
        shortcut: starting owners, not conquests; read Region.strOwner live if wars move borders a lot."""
        if getattr(self, '_owners', None) is None:
            idx = {n: i for i, n in enumerate(self.land_map()[0])}
            self._owners = {}
            for where in ('system', 'user'):      # user overrides system
                d = os.path.join(gamepaths.GAMES[self.cfg['game']]['path'], 'Modern Europe', where, 'scenarios',
                                 getattr(self, 'scenario', '') or '')
                for f in os.listdir(d) if os.path.isdir(d) else []:
                    if f.startswith('country') and f.endswith('.xml'):
                        text = open(os.path.join(d, f), encoding='utf-8', errors='replace').read()
                        for r in re.findall(r'<object type="Region" name="objGOs">\s*<property name="strName" '
                                            r'value="([^"]+)"', text):
                            if r in idx:
                                self._owners[idx[r]] = f[7:-4]
        return self._owners

    def war_sides(self):
        """(allies, enemies) as nCountryID strings: nations in our alliances and nations at war with us, from
        GameState like briefing() (war sides are a country or a whole alliance)."""
        me, (_, als, wars) = str(self.country_id()), self._alliances()
        members, allies = {}, set()
        for a in als:
            ids = {self.fixed(m).get('nCountryID') for m in self.refs(a, 'objCurrentMembers')}
            members[self.show(a)[0].get('nAllianceID')] = ids
            allies |= ids if me in ids else set()
        side = lambda ref: (lambda q: members.get(q['nAllianceID'], set()) if 'nAllianceID' in q
                            else {q.get('nCountryID')})(self.fixed(self.obj_id(ref or '')))
        enemies = set()
        for w in wars:
            p = self.fixed(w)
            att = side(p.get('objAttackerCountry')) | side(p.get('objOffense'))
            dfn = side(p.get('objDefenderCountry')) | side(p.get('objDefense'))
            enemies |= dfn if me in att else att if me in dfn else set()
        return allies - {me}, enemies

    def move_troops(self, target, amount=0, declare_war=False):
        """Local planner for 'send N armies to <region or country>': the target region nearest to our armies by
        land (BFS on the map), then the N armies nearest to it, each with an ActMove. The game draws the route
        itself from the one destination waypoint (tested offline). amount 0 = every army. A sea region as the
        target moves FLEETS instead (nearest by sea)."""
        names, adj = self.land_map()
        low = {n.lower(): i for i, n in enumerate(names)}
        if (target or '').strip().lower() in low:
            goals = {low[target.strip().lower()]}
        else:
            goals = self.country_regions(self.country_name(target))
        if not goals & set(self._sea_adj):
            raise RuntimeError('no conozco la región o el país %s' % target)
        naval = goals <= set(self._sea_adj) - set(adj)      # a sea: fleets go there
        # like a player: only into our own, allied or enemy (at war) land; otherwise the model decides on war
        owners = set() if naval else {self.region_owners().get(g) for g in goals} - {None, self.cfg['country']}
        allies, enemies = self.war_sides() if owners else (set(), set())
        closed = sorted(o for o in owners if str(self.country_id(o)) not in allies | enemies)
        for o in closed if declare_war else []:      # the bot already decided: declare, then march
            self.propose('guerra', o)
        if closed and not declare_war:
            return ('PREGUNTA: no estás en guerra con %s, así que tus tropas no pueden entrar. ¿Quieres declararle la '
                    'guerra? Decídelo tú: si sí, llama otra vez move_troops con declare_war=true; si no, explícalo '
                    'en el chat a quien lo pidió.' % ', '.join(closed))
        armies = []      # (unit object, GOID, name, region)
        for u in self.refs(self._data(), 'objUnits'):
            p = self.show(u)[0]
            if p.get('__type') == ('Fleet' if naval else 'Army') and int(p.get('nRegionID') or -1) in self._sea_adj:
                armies.append((u, int(p['nGameObject']), p.get('strName'), int(p['nRegionID'])))
        # armies by land if any can, else across the sea (transport); fleets by sea
        for by_sea, graph in ((False, self._sea_adj),) if naval else ((False, adj), (True, self._sea_adj)):
            routed = [a[:3] + (bfs(graph, a[3]),) for a in armies]
            reach = [(a[3][g], g) for a in routed for g in goals if g in a[3]]
            if reach:
                break
        armies = routed
        if not reach:
            raise RuntimeError(('ninguna flota llega a %s' if naval else
                                'ningún ejército llega a %s (ni por tierra ni por mar)') % target)
        goal = min(reach)[1]
        armies = sorted((a for a in armies if goal in a[3]), key=lambda a: a[3][goal])[:max(0, int(amount or 0)) or None]
        out = []
        for u, goid, name, dist in armies:
            if dist[goal] == 0:
                out.append('%s ya está en %s' % (name, names[goal]))
                continue
            self.send_action('ActMove', {'nGOID': goid, 'nRegionID': goal},
                             [('objExpectedIncidentsList', 'PathIncidentList', {})])      # NULL list: ignored
            ok = self.obj_id(self.show(u)[0].get('objOrder', '')) > 0
            out.append('%s -> %s (%d regiones%s)%s' % (name, names[goal], dist[goal], ', por mar' if by_sea else '',
                                                       '' if ok else ' RECHAZADO'))
        if by_sea and any(o.endswith('RECHAZADO') for o in out):
            c = self.obj_id(self.show(self.player())[0].get('objCountry', ''))
            out.append('cruzar el mar usa transporte marítimo: tienes %s créditos de transporte (las ciudades los '
                       'fabrican con la orden TransportCredits)' % self.show(c)[0].get('nTransportCredits', '?'))
        return '; '.join(out)

    def diplo_key(self):
        """Cheap fingerprint of alliances (and their members), wars and our treaties: run() re-analyses only when
        it changes."""
        _, als, wars = self._alliances()
        tl = self.obj_id(self.fixed(self.player()).get('objTreatyList', ''))
        return (tuple(als), tuple(tuple(self.refs(a, 'objCurrentMembers')) for a in als), tuple(wars),
                tuple(self.refs(tl, 'objTreaties')) if tl > 0 else ())

    def briefing(self):
        """The bot's picture of the world, built locally from the game objects when the game starts and rebuilt
        only when diplo_key() changes: (text for the prompt, fingerprint)."""
        key = self.diplo_key()
        _, als, wars = self._alliances()
        names = self.__dict__.setdefault('_country_names', {})      # nCountryID -> name
        for oid in self.all_players.values() if hasattr(self, 'all_players') else []:
            if oid in self.__dict__.setdefault('_named', set()):
                continue
            self._named.add(oid)
            c = self.obj_id(self.show(oid)[0].get('objCountry', ''))
            if c > 0:
                p = self.show(c)[0]
                names[p.get('nCountryID')] = p.get('strName')
        alliance_names, lines = {}, []
        for a in als:
            p = self.show(a)[0]
            alliance_names[p.get('nAllianceID')] = p.get('strDisplayName')
            leader, members = [], []      # bOwner first (founder, e.g. Germany for the Axis), then bPrincipal
            for m in self.refs(a, 'objCurrentMembers'):
                q = self.fixed(m)
                n = q.get('strINITCountryName') or names.get(q.get('nCountryID')) or 'pais %s' % q.get('nCountryID')
                names.setdefault(q.get('nCountryID'), n)
                members.append(n)
                leader.append((q.get('bOwner') != 'true', q.get('bPrincipal') != 'true', n))
            self.__dict__.setdefault('alliances', {})[a] = {'name': p.get('strDisplayName'), 'members': members,
                                                             'leader': min(leader)[2] if leader else '?'}
            if self.cfg['country'] in members:
                self.allies = set(members) - {self.cfg['country']}
            lines.append('%s: líder %s; miembros: %s' % (p.get('strDisplayName'), min(leader)[2] if leader else '?',
                                                         ', '.join(members)))
        war_lines, enemies = [], set()
        for w in wars:
            p = self.fixed(w)
            side = lambda ref: (lambda q: 'alianza %s' % alliance_names.get(q.get('nAllianceID'), q.get('nAllianceID'))
                                if 'nAllianceID' in q else names.get(q.get('nCountryID'), 'pais %s' % q.get('nCountryID')))(
                self.fixed(self.obj_id(p.get(ref, ''))))
            att, off, dfn, de = (side('objAttackerCountry'), side('objOffense'), side('objDefenderCountry'),
                                 side('objDefense'))
            war_lines.append('Guerra %s "%s": %s (%s) contra %s (%s)' % (p.get('nWarID'), p.get('strDisplayName'),
                                                                     att, off, dfn, de))
            mine = {self.cfg['country']} | {'alianza ' + al['name'] for al in self.__dict__.get('alliances', {}).values()
                                            if self.cfg['country'] in al['members']}
            if {att, off} & mine:
                enemies.add(dfn)
            elif {dfn, de} & mine:
                enemies.add(att)
        self.enemies = sorted(enemies)
        parts = [('Alianzas', '\n'.join(lines) or 'ninguna'), ('Guerras (el número sirve para proponer la paz)',
                                                              '\n'.join(war_lines) or 'ninguna')]
        if self.historic_regions():
            parts.append(('Tus regiones históricas (las reclamas como tuyas)', ', '.join(self.historic_regions())))
        data = self.obj_id(self.fixed(self.player()).get('objData', ''))
        if data > 0:      # our own forces: number of units and manpower left for new ones
            gov = self.obj_id(self.show(data)[0].get('objGovData', ''))
            parts.append(('Tus fuerzas', 'Unidades: %d; reclutas disponibles: %s' % (
                self.__dict__.update(unit_count=len(self.refs(data, 'objUnits'))) or self.unit_count, self.show(gov)[0].get('nManpowerAvailable', '?') if gov > 0 else '?')))
        if getattr(self, '_research', None) is not None:      # read in a quiet moment (run), ~1 min
            parts.append(('Investigación disponible (research)', ', '.join(self._research) or 'ninguna'))
        for title, what in (('Tus relaciones diplomáticas (0-1000; las neutrales, 500, no se listan)', 'relaciones'),
                            ('Poder militar mundial (ejército, aviación, armada, total)', 'militar_mundo')):
            text = self.report(what)      # works when we host; a joined console.exe has no Game object for it
            if 'is not a' not in text and 'Usage' not in text:
                parts.append((title, re.sub(r'(?m)^.*\s(500|0\s+0\s+0\s+0)$\n?', '', text)[:3000]))
        return '\n\n'.join('## %s\n%s' % p for p in parts), key


SYSTEM = """Eres el jefe de estado de {country} en una partida multijugador de Making History ({game}), \
un juego de estrategia sobre la primera mitad del siglo XX.
Personalidad: {personality}
Objetivos: {goals}
Hablas en el chat del juego como un dirigente de tu país: mensajes breves (1-3 frases), en el idioma '{language}' \
salvo que te escriban en otro. Sé coherente con lo que dijiste antes y no prometas acciones que no puedes hacer.
Puedes: hablar (say, open_chat); consultar detalles (look); responder propuestas (answer_proposal); proponer \
tratados: guerra, paz, alianza, no agresión, acceso militar, comercio y ayuda (propose); declarar o levantar un \
embargo (embargo); hacer un gesto para mejorar las relaciones con un país, una vez por turno y país \
(improve_relations, o empeorarlas); reforzar tu ejército, aviación o armada (build_forces); cambiar el régimen de tu país \
(set_government, solo por un motivo de peso); investigar (research) y repartir la producción de \
tus ciudades entre investigación y armamento u otros bienes (production); mover ejércitos hacia una región o un \
país (move_troops); responder los avisos del juego (answer_popup).
Tus herramientas se aplican en el juego al instante. Nunca anuncies ni prometas una acción (guerra, paz, alianza, \
comercio, ayuda, embargo, tropas, régimen) sin llamar en esta misma respuesta a la herramienta que la ejecuta; no \
la dejes «para el próximo turno». Si te piden algo razonable y aceptas, actúa ya. Da todas tus respuestas y \
acciones juntas en una sola respuesta.
Toma la iniciativa: cuando cambie la situación (una guerra nueva, una alianza, una amenaza), coméntalo en el chat general o escribe a un jugador humano; de vez en cuando expresa tu deseo de recuperar tus regiones históricas. Como haría un jugador, ofrece por tu \
cuenta comercio (propose comercio: das lo que te sobra a cambio de lo que te falta) a quien convenga, y ayuda \
(propose ayuda) a tus aliados en guerra; si te falta algo, pídelo (ayuda con request). Si estás en guerra o un \
aliado te pide tropas, pasa la producción a armamento (production con rest Armaments y poca investigación) y \
refuerza tus fuerzas (build_forces). Si recibes ayuda (aid) o te ceden territorio, agradécelo en el chat y mejora las relaciones con ese país (improve_relations).
En las herramientas usa los nombres de países del juego, en inglés (Turkey, Germany, United Kingdom), aunque en el chat hables en español.
Alianzas: cada alianza indica su líder. Si estás en una alianza, la opinión de su líder \
pesa más que la de los demás: si el líder te pide declarar una guerra o mandar tropas (reforzar tus fuerzas, dar \
acceso militar), en general obedece, salvo que sea claramente suicida para tu país.
Responde en el mismo chat donde te escribieron (puede ser el chat general con todos los jugadores o uno privado); \
si hay mensajes nuevos en varios chats, responde en cada uno con su propio 'say'. Si no hay nada que hacer ni \
responder, no llames a ninguna herramienta."""

TOOLS = [
    {'name': 'say', 'description': 'Escribe un mensaje en un chat existente.',
     'parameters': {'type': 'object', 'properties': {
         'chat': {'type': 'integer', 'description': 'número del chat (como aparece en la lista)'},
         'text': {'type': 'string', 'description': 'el mensaje'},
         'tone': {'type': 'string', 'enum': ['positive', 'neutral', 'negative'],
                  'description': 'cómo juzga tu nación el último mensaje del jugador al que respondes: positivo sube '
                                 'la relación 5 puntos, negativo la baja 5 (gestos mayores: improve_relations)'}},
         'required': ['chat', 'text']}},
    {'name': 'open_chat', 'description': 'Abre un chat nuevo con otro jugador humano y le escribe.',
     'parameters': {'type': 'object', 'properties': {
         'country': {'type': 'string', 'description': 'país del jugador'},
         'text': {'type': 'string', 'description': 'primer mensaje'}}, 'required': ['country', 'text']}},
    {'name': 'look', 'description': 'Consulta detalles del juego (solo lectura) que no estén en la situación del '
                                    'mundo: alianzas, guerras (con su número, para proponer la paz), relaciones '
                                    '(diplomáticas de un país con los demás), militar (poder militar de un país), '
                                    'militar_mundo, comercio (entre tu país y otro).',
     'parameters': {'type': 'object', 'properties': {
         'what': {'type': 'string', 'enum': ['alianzas', 'guerras', 'relaciones', 'militar', 'militar_mundo',
                                             'comercio']},
         'country': {'type': 'string', 'description': 'país (por defecto el tuyo)'}}, 'required': ['what']}},
    {'name': 'answer_proposal', 'description': 'Acepta o rechaza una propuesta diplomática recibida (ver la lista '
                                               '«Propuestas pendientes»).',
     'parameters': {'type': 'object', 'properties': {
         'id': {'type': 'integer', 'description': 'id de la propuesta'},
         'accept': {'type': 'boolean'},
         'relations': {'type': 'integer', 'description': 'solo si aceptas una alianza: la relación que queda con el '
                       'otro país (mínimo 500 de 1000; más alta si lo estimas). Nunca la baja.'}},
         'required': ['id', 'accept']}},
    {'name': 'propose', 'description': 'Propone un tratado a otro país: guerra (declara la guerra), alianza (pacto de '
                                       'defensa; si el país ya está en otra alianza, propónla a su líder y ambas '
                                       'alianzas se unen), romper_alianza (sales de la alianza con ese país), no_agresion, acceso_militar, paz (necesita war_id: el número de la '
                                       'guerra en look guerras), comercio (offer/request de recursos), ayuda (offer '
                                       'de recursos y/o money, o request para pedirla), territorio (offer: '
                                       'regiones tuyas que cedes, request: regiones suyas que pides, p. ej. '
                                       '"Falklands, Bolivia"). '
                                       'Recursos: Food, Coal, Metals, Oil, Consumer, Armaments.',
     'parameters': {'type': 'object', 'properties': {
         'kind': {'type': 'string', 'enum': ['guerra', 'alianza', 'romper_alianza', 'no_agresion', 'acceso_militar',
                                             'paz', 'comercio', 'ayuda', 'territorio']},
         'country': {'type': 'string'},
         'offer': {'type': 'string', 'description': 'recursos que das, p. ej. "Oil:100, Food:50"'},
         'request': {'type': 'string', 'description': 'recursos que pides, p. ej. "Oil:100, Food:50"'},
         'money': {'type': 'integer'},
         'war_id': {'type': 'integer'}}, 'required': ['kind', 'country']}},
    {'name': 'embargo', 'description': 'Declara (on=true) o levanta (on=false) un embargo comercial a un país.',
     'parameters': {'type': 'object', 'properties': {
         'country': {'type': 'string'}, 'on': {'type': 'boolean'}}, 'required': ['country', 'on']}},
    {'name': 'improve_relations', 'description': 'Gesto diplomático que mejora un poco las relaciones con un país, o '
                                                 'las empeora con worsen=true (una vez por turno y país).',
     'parameters': {'type': 'object', 'properties': {'country': {'type': 'string'}, 'worsen': {'type': 'boolean'}},
                    'required': ['country']}},
    {'name': 'build_forces', 'description': 'Aumenta el tamaño deseado de una rama militar en 1-10 unidades; el '
                                            'juego gasta armamento y producción en construirlas.',
     'parameters': {'type': 'object', 'properties': {
         'branch': {'type': 'string', 'enum': ['ejercito', 'aviacion', 'armada']},
         'amount': {'type': 'integer'}}, 'required': ['branch', 'amount']}},
    {'name': 'move_troops', 'description': 'Mueve ejércitos por tierra hacia una región o hacia un país (a su región '
                                           'más cercana); el juego traza la ruta. amount = cuántos ejércitos (los más '
                                           'cercanos; 0 = todos).',
     'parameters': {'type': 'object', 'properties': {
         'target': {'type': 'string', 'description': 'región o país de destino, p. ej. "Thrace" o "Turkey"'},
         'amount': {'type': 'integer'},
         'declare_war': {'type': 'boolean', 'description': 'solo se puede entrar en tierra propia, aliada o de un '
                                                           'país en guerra contigo: true = declarar la guerra al '
                                                           'dueño si hace falta (decídelo tú)'}},
         'required': ['target']}},
    {'name': 'answer_popup', 'description': 'Responde un aviso del juego (lista «Avisos pendientes») con una de sus '
                                            'opciones.',
     'parameters': {'type': 'object', 'properties': {'id': {'type': 'integer'}, 'choice': {'type': 'string'}},
                    'required': ['id', 'choice']}},
    {'name': 'research', 'description': 'Empieza un proyecto de investigación (de la lista «Investigación disponible»).',
     'parameters': {'type': 'object', 'properties': {'project': {'type': 'string'}}, 'required': ['project']}},
    {'name': 'production', 'description': 'Reparte la producción de tus ciudades: research_percent (0-100) de tus '
                                          'IPUs a investigación (lo que la investigación pueda usar) y el resto a rest.',
     'parameters': {'type': 'object', 'properties': {
         'research_percent': {'type': 'integer'},
         'rest': {'type': 'string', 'enum': list(Bot.OUTPUTS)}}, 'required': ['research_percent']}},
    {'name': 'set_government', 'description': 'Cambia el régimen de tu país.',
     'parameters': {'type': 'object', 'properties': {
         'government': {'type': 'string', 'enum': list(Bot.GOVS)}}, 'required': ['government']}},
]


def _res(text):
    """'Oil:100, Food:50' -> {'Oil': 100, 'Food': 50} (Gemini tool schemas can't take free-form maps)."""
    if isinstance(text, dict):
        return text
    out = {}
    for part in (text or '').split(','):
        name, _, n = part.partition(':')
        if name.strip() and n.strip().lstrip('-').isdigit():
            out[name.strip()] = int(n)
    return out


assert _res('Oil:100, Food: 50') == {'Oil': 100, 'Food': 50}


def squash(name):
    """A nation name without case, accents, spaces or underscores: 'Reino_Unido' == 'ReinoUnido' == 'reino unido'."""
    return ''.join(c for c in unicodedata.normalize('NFKD', name.lower()) if c.isalnum() and ord(c) < 128)


assert squash('Reino_Unido') == squash('ReinoUnido') == squash('reino unido') == 'reinounido'
assert squash('UnitedStates') == squash('United States') and squash('Túnez') == 'tunez'


def bfs(adj, start):
    """{region: steps from start} over the adjacency map."""
    dist, todo = {start: 0}, [start]
    for r in todo:
        for n in adj.get(r, ()):
            if n not in dist:
                dist[n] = dist[r] + 1
                todo.append(n)
    return dist


assert bfs({1: {2}, 2: {1, 3}, 3: {2}, 4: set()}, 1) == {1: 0, 2: 1, 3: 2}


def act(bot, c, chats, order, humans):
    """Carries out one tool call; returns the text the LLM gets back (for look) or None."""
    a = dict(c.get('args') or {})
    if a.get('country'):
        a['country'] = bot.country_name(a['country'])      # the model may write 'Turquía' for the game's 'Turkey'
    n = c['name']
    if n == 'say' and 0 <= int(a.get('chat', -1)) < len(order):
        if a.get('text', '').lstrip().lower().startswith(LLM_BLOCKED):      # player-only commands, never the bot's
            bot.log('ignored_call', c)
            return 'ese comando es solo para los jugadores'
        oid = order[int(a['chat'])]
        bot.say(oid, a.get('text', ''))
        if a.get('tone') in ('positive', 'negative'):      # the tone of the exchange nudges relations, once per message
            lines = chats.get(oid, [])
            i, who = next(((i, w) for i, (w, _) in reversed(list(enumerate(lines))) if w != bot.cfg['country']), (-1, ''))
            if who and (oid, i) not in bot.__dict__.setdefault('_toned', set()):
                bot._toned.add((oid, i))
                bot.tone_relations(bot.country_name(who), 5 if a['tone'] == 'positive' else -5)
    elif n == 'open_chat' and a.get('country') in humans:
        oid = bot.open_chat(a['country'])
        if oid:
            bot.say(oid, a.get('text', ''))
    elif n == 'look':
        return bot.report(a.get('what', 'alianzas'), a.get('country'))
    elif n == 'answer_proposal':
        t = next((p for p in bot.proposals() if str(p['id']) == str(a['id'])), {})
        bot.answer(a['id'], bool(a.get('accept')))
        if a.get('accept') and 'DefensePact' in (t.get('tipo') or '') and t.get('de'):
            import sp_chat      # an accepted alliance: relations at least 500 of 1000 both ways, never lowered
            try:
                want = max(sp_chat.ALLIANCE_FLOOR, min(1000, int(a.get('relations') or 0)))
            except (TypeError, ValueError):
                want = sp_chat.ALLIANCE_FLOOR
            bot.log('did', {'alliance_floor': sp_chat.set_pair(bot, bot.cfg['country'], t['de'], want, floor=True)})
    elif n == 'propose' and a.get('kind') == 'territorio':
        names = lambda v: [x.strip() for x in (v if isinstance(v, list) else str(v or '').split(',')) if x.strip()]
        bot.propose('territorio', a['country'], names(a.get('offer')), names(a.get('request')))
    elif n == 'propose' and (a.get('kind') in bot.TREATIES or a.get('kind') == 'romper_alianza'):
        try:
            ally = a['kind'] == 'guerra' and str(bot.country_id(a['country'])) in bot.war_sides()[0]
        except Exception:      # country ids still loading: the game itself refuses a war on an ally
            ally = False
        if ally:
            bot.propose('romper_alianza', a['country'])      # an ally: the alliance is broken first
        bot.propose(a['kind'], a['country'], _res(a.get('offer')), _res(a.get('request')), a.get('money') or 0, a.get('war_id'))
    elif n == 'embargo' and a.get('country'):
        bot.embargo(a['country'], a.get('on', True) is not False)
    elif n == 'improve_relations' and a.get('country'):
        bot.improve_relations(a['country'], bool(a.get('worsen')))
    elif n == 'build_forces' and a.get('branch') in bot.FORCES:
        bot.build_forces(a['branch'], a.get('amount') or 1)
    elif n == 'move_troops' and a.get('target'):
        res = bot.move_troops(a['target'], a.get('amount') or 0, bool(a.get('declare_war')))
        bot.log('did', dict(c, result=res))
        return res
    elif n == 'answer_popup' and a.get('choice'):
        bot.answer_popup(a['id'], a['choice'])
    elif n == 'research' and a.get('project'):
        bot.research(a['project'])
    elif n == 'production':
        res = bot.production(a.get('research_percent') or 0, a.get('rest') if a.get('rest') in bot.OUTPUTS else 'Armaments')
        bot.log('did', dict(c, result=res))
        return res
    elif n == 'set_government' and a.get('government') in bot.GOVS:
        bot.set_government(a['government'])
    else:
        bot.log('ignored_call', c)
        return 'acción no válida'
    bot.log('did', c)
    return 'hecho'


WAR_SAID = re.compile(r'(?:declar\w*|abrir\w*|iniciar\w*|empez\w*|entra\w*)\s+(?:la\s+|una\s+|en\s+)?'
                      r'(?:guerra|campa[nñ]a)\s+(?:a|contra|con)\s+([A-ZÁÉÍÓÚÜ][\wáéíóúüñ]+(?:\s+[A-Z][\w]+)?)', re.I)
MOBILIZE_SAID = re.compile(r'moviliz\w*|reforz\w*\s+(?:el\s+|nuestro\s+)?ej[eé]rcito|levant\w*\s+tropas', re.I)
MOVE_SAID = re.compile(r'(?:moviliz|envi|mand|desplaz|mov|llev)\w*\s+(?:\w+\s+){0,3}?(?:tropas|ej[eé]rcitos?|fuerzas|'
                       r'divisiones)\s+(?:\w+\s+){0,2}?(?:hacia|a|contra|en)\s+(?:la\s+frontera\s+(?:con|de)\s+)?(?:el\s+|la\s+)?'
                       r'([A-ZÁÉÍÓÚÜ][\wáéíóúüñ]+(?:\s+[A-Z][\w]+)?)', re.I)
NEGATED = re.compile(r'(?:^|[^\w])(?:no|nunca|jam[aá]s)\W+(?:\w+\W+){0,3}$', re.I)


def commitments(text):
    """Actions the bot announced in its own chat line ('declaramos la guerra a Turquía', 'movilizaremos las
    tropas'): [(tool name, args)]. The code carries them out when the model forgot the tool call."""
    out = []
    for m in WAR_SAID.finditer(text or ''):
        if not NEGATED.search(text[:m.start()]):
            out.append(('propose', {'kind': 'guerra', 'country': m.group(1)}))
    m = MOBILIZE_SAID.search(text or '')
    if m and not NEGATED.search(text[:m.start()]):
        out.append(('build_forces', {'branch': 'ejercito', 'amount': 3}))
    for m in MOVE_SAID.finditer(text or ''):
        if not NEGATED.search(text[:m.start()]):
            out.append(('move_troops', {'target': m.group(1)}))
    return out


assert commitments('Entendido. Declaramos la guerra a Turquía y movilizaremos tropas.') == [
    ('propose', {'kind': 'guerra', 'country': 'Turquía'}), ('build_forces', {'branch': 'ejercito', 'amount': 3})]
assert commitments('Movilizaremos nuestras tropas hacia Turquía.') == [
    ('build_forces', {'branch': 'ejercito', 'amount': 3}), ('move_troops', {'target': 'Turquía'})]
assert commitments('Enviaremos dos ejércitos a la frontera con Bulgaria.') == [('move_troops', {'target': 'Bulgaria'})]
assert commitments('No declararemos la guerra a Turquía.') == []
assert commitments('Saludos desde Atenas.') == []


HELP = ('Comandos: /declare war <yo> <pais> | /peace <yo> <pais> <n guerra> | /alliance join <yo> <pais> | '
        '/alliance leave <yo> |/nonaggression <yo> <pais> | /access <yo> <pais> | /embargo <yo> <pais> | '
        '/unembargo <yo> <pais> | /relations <yo> <pais> +25|-25 | /trade <yo> <pais> give Oil:50 get Food:50 | '
        '/aid <yo> <pais> Armaments:20 money:5 | /research <yo> <proyecto> | /production <yo> research 30 rest '
        'Armaments | /build <yo> army|air|navy 5 | /government <yo> <regimen> | '
        '/transfer territory <mi region> <pais que la recibe> | /request territory <su region> <pais dueno> | '
        '/troops move <yo> <region|pais|mar> [n] (a un mar van las flotas) | /proposals | /accept <id|pais> | /reject <id|pais> | '
        '/chat @pais [@pais ...] (o /chat pais) | /order <yo> <orden> | /relations improve|reset <pais> <pais> | '
        '/relations set <pais> <pais> <0-1000> | /merge <yo> <pais> | /ideology align <pais que cambia> <pais modelo> | '
        '/status | /yesman on|off | /parlanchin (/chatty) on|off | /advisor military|economy|diplomacy [pregunta] | '
        '/summit @pais @pais ... | /editor <frase> (solo con /yesman on). '
        'Nombres de varias palabras con comillas o _ (United_Kingdom).')


EVERYONE = re.compile(r'@everyone\b', re.I)      # a chat line that calls every nation (each decides to answer)
LLM_BLOCKED = ('/yesman', '/order', '/orden', '/chat', '/help', '/ayuda', '/parlanchin', '/chatty', '/advisor',
               '/summit', '/editor')


def chat_command(bot, who, text):
    """Runs a '/command' typed in the chat, locally (no LLM); returns the reply line, or None if it isn't one.
    Game-changing commands obey only allies (same alliance), or anyone with /yesman on."""
    import shlex
    try:
        words = [w.replace('_', ' ') for w in shlex.split(text.strip())]
    except ValueError:
        words = text.strip().replace('_', ' ').split()
    if not words or not words[0].startswith('/'):
        return None
    cmd, args = words[0][1:].lower(), words[1:]
    me = bot.cfg['country']
    if cmd == 'help':
        return HELP
    if cmd == 'advisor':      # '/advisor military|economy|diplomacy [question]': from our world picture, no moves
        return advisor(bot, who, args)
    if cmd == 'editor':       # '/editor <phrase>': with /yesman on, the phrase becomes our own commands
        return editor(bot, who, ' '.join(args))
    if cmd == 'chat' or cmd == 'summit':      # '/chat @Colombia @Venezuela': a new chat with us and those nations
        names = [bot.country_name(a.lstrip('@')) for a in args if a.strip('@')]
        if not names:
            return 'Uso: /chat @Pais [@Pais ...] (varias palabras con _: @Reino_Unido).'
        return ('Abrí un chat nuevo con %s.' % ', '.join(names) if bot.open_chat(*names)
                else 'No pude abrir el chat con %s.' % ', '.join(names))
    if cmd in ('parlanchin', 'chatty') and args and args[0].lower() in ('on', 'off'):
        bot.chatty = args[0].lower() == 'on'
        return ('Modo parlanchin activado: hablare en el chat general cada turno y respondere a todo.'
                if bot.chatty else 'Modo parlanchin desactivado: en el chat general solo respondo si me mencionan con @.')
    if cmd == 'yesman' and args and args[0].lower() in ('on', 'off'):
        bot.yesman = args[0].lower() == 'on'
        return 'Modo yesman %s.' % ('activado: hare todo lo que me pidan' if bot.yesman else 'desactivado')
    if cmd == 'status':
        al = next((a for a in getattr(bot, 'alliances', {}).values() if me in a['members']), None)
        return '%s: alianza %s; unidades %s; en guerra con: %s.' % (
            me, '%s (lider %s)' % (al['name'], al['leader']) if al else 'ninguna',
            getattr(bot, 'unit_count', '?'), ', '.join(getattr(bot, 'enemies', [])) or 'nadie')
    if cmd == 'proposals':      # pending treaties with their ids, for /accept and /reject
        ps = bot.proposals()
        return ('Propuestas pendientes: ' + '; '.join('#%s %s de %s a %s' % (p['id'], p['tipo'], p['de'], p['para'])
                                                      for p in ps)) if ps else 'No hay propuestas pendientes.'
    if cmd in ('accept', 'reject'):
        if not getattr(bot, 'yesman', False) and who not in getattr(bot, 'allies', set()):
            return 'Solo acepto ordenes de mis aliados (o con /yesman on).'
        ps = [p for p in bot.proposals() if p['para'] == me]
        key = ' '.join(args)
        if key.isdigit():
            ps = [p for p in ps if str(p['id']) == key]
        elif key:
            ps = [p for p in ps if p['de'] == bot.country_name(key)]
        if len(ps) != 1:
            return ('Hay varias; indica el id: ' if ps else 'No encuentro esa propuesta. ') + \
                '; '.join('#%s %s de %s' % (p['id'], p['tipo'], p['de']) for p in ps)
        bot.answer(ps[0]['id'], cmd == 'accept')
        return 'Hecho: %s #%s (%s de %s).' % ('aceptada' if cmd == 'accept' else 'rechazada', ps[0]['id'],
                                              ps[0]['tipo'], ps[0]['de'])
    sub = args[0].lower() if args else ''
    if (cmd == 'relations' and sub in ('improve', 'reset', 'set')) or (cmd == 'ideology' and sub == 'align'):
        # the same commands as single player (sp_chat): any two nations, so allies only (or /yesman on)
        if not getattr(bot, 'yesman', False) and who not in getattr(bot, 'allies', set()):
            return 'Solo acepto ordenes de mis aliados (o con /yesman on).'
        import sp_chat
        rest = ' '.join('"%s"' % w for w in args[1:])
        if cmd == 'relations':
            return sp_chat.set_relations(bot, sub, rest)
        if len(args) != 3:
            return 'Uso: /ideology align <país que cambia> <país modelo> (p. ej. /ideology align Francia Alemania).'
        a, b = bot.country_name(args[1]), bot.country_name(args[2])
        ga, gb = bot.gov_type(a), bot.gov_type(b)
        if ga == gb:
            return '%s ya tiene la misma ideología que %s (%s).' % (a, b, sp_chat.GOV_ES.get(gb, gb))
        bot.cli('ActSetCountryGov', a, gb)
        now = bot.gov_type(a)
        return ('%s adopta la ideología de %s: %s (antes %s).' % (a, b, sp_chat.GOV_ES.get(gb, gb), sp_chat.GOV_ES.get(ga, ga))
                if now == gb else 'El juego no aplicó el cambio: %s sigue con %s.' % (a, sp_chat.GOV_ES.get(now, now)))
    if cmd == 'merge':      # '/merge <yo> <pais>': we offer every region of ours to that nation (sp_chat.annex)
        if len(args) != 2 or bot.country_name(args[0]) != me:
            return 'Uso: /merge %s <pais al que se une> (solo puedo unir mi propia nación).' % me
        import sp_chat      # without /yesman: relations of at least sp_chat.MERGE_MIN both ways
        return sp_chat.annex(bot, me, bot.country_name(args[1]), forced=getattr(bot, 'yesman', False))
    if cmd == 'troops' and args and args[0].lower() == 'move':
        cmd, args = 'troops_move', args[1:]
    if cmd == 'alliance' and args and args[0].lower() in ('leave', 'join'):
        # '/alliance leave Venezuela': the bot's nation leaves its alliance; '/alliance join <yo> <pais>' joins one
        cmd, args = ('leave_alliance' if args[0].lower() == 'leave' else 'alliance'), args[1:]
    elif cmd in ('declare', 'leave', 'transfer', 'request') and args and args[0].lower() in ('war', 'alliance',
                                                                                            'territory'):
        cmd, args = cmd + '_' + args[0].lower(), args[1:]
    known = {'declare_war', 'peace', 'alliance', 'leave_alliance', 'nonaggression', 'access', 'embargo',
             'unembargo', 'relations', 'trade', 'aid', 'research', 'production', 'build', 'government',
             'transfer_territory', 'request_territory', 'troops_move'}
    if cmd not in known:
        return 'Comando desconocido. Escribe /help.'
    if cmd.endswith('_territory'):      # '/transfer territory Falklands Argentina': the region names the owner
        args = [me] + args
    if not args or bot.country_name(args[0]) != me:
        return 'Solo puedo actuar como %s: el primer pais del comando debe ser %s.' % (me, me)
    if not getattr(bot, 'yesman', False) and who not in getattr(bot, 'allies', set()):
        return 'Solo acepto ordenes de mis aliados (o con /yesman on).'
    a = args[1:]
    target = bot.country_name(a[0]) if a else ''
    res = lambda items: {k: int(v) for k, _, v in (x.partition(':') for x in items) if v.strip().lstrip('-').isdigit()}
    if cmd == 'declare_war':
        bot.propose('guerra', target)
    elif cmd == 'peace':
        bot.propose('paz', target, war_id=int(a[1]) if len(a) > 1 and a[1].isdigit() else None)
    elif cmd == 'alliance':
        bot.propose('alianza', target)
    elif cmd == 'leave_alliance':
        # breaking the pact with a member takes us out of the alliance: its leader, else any ally
        al = next((x for x in getattr(bot, 'alliances', {}).values() if me in x['members']), None)
        target = target or (al['leader'] if al and al['leader'] != me else
                            next(iter(sorted(getattr(bot, 'allies', set()))), ''))
        if not target:
            return '%s no esta en ninguna alianza.' % me
        bot.propose('romper_alianza', target)
        target = 'de %s' % (al['name'] if al else 'la alianza')
    elif cmd == 'nonaggression':
        bot.propose('no_agresion', target)
    elif cmd == 'access':
        bot.propose('acceso_militar', target)
    elif cmd in ('embargo', 'unembargo'):
        bot.embargo(target, cmd == 'embargo')
    elif cmd == 'relations':
        bot.improve_relations(target, worsen=len(a) > 1 and a[1].startswith('-'))
    elif cmd == 'trade':
        low = [x.lower() for x in a]
        give = a[low.index('give') + 1:low.index('get') if 'get' in low else None] if 'give' in low else []
        get = a[low.index('get') + 1:] if 'get' in low else []
        bot.propose('comercio', target, res(give), res(get))
    elif cmd == 'aid':
        goods = res(a[1:])
        bot.propose('ayuda', target, {k: v for k, v in goods.items() if k.lower() != 'money'}, None,
                    goods.get('money') or goods.get('Money') or 0)
    elif cmd == 'research':
        bot.research(' '.join(a).replace(' ', ''))
        target = ' '.join(a)
    elif cmd == 'production':
        low = [x.lower() for x in a]
        pct = int(a[low.index('research') + 1]) if 'research' in low else 0
        rest = a[low.index('rest') + 1] if 'rest' in low else 'Armaments'
        return 'Hecho: ' + bot.production(pct, rest if rest in bot.OUTPUTS else 'Armaments')
    elif cmd == 'build':
        branch = {'army': 'ejercito', 'air': 'aviacion', 'navy': 'armada'}.get((a[0] if a else '').lower())
        if not branch:
            return 'Uso: /build <yo> army|air|navy <cantidad>'
        bot.build_forces(branch, int(a[1]) if len(a) > 1 and a[1].isdigit() else 3)
    elif cmd in ('transfer_territory', 'request_territory'):
        if len(a) < 2:
            return 'Uso: /%s territory <region> <pais>' % cmd.split('_')[0]
        target = bot.country_name(a[-1])
        region = ' '.join(a[:-1])
        if cmd == 'transfer_territory':
            bot.propose('territorio', target, [region], [])
        else:
            bot.propose('territorio', target, [], [region])
        target = '%s -> %s' % (region, target) if cmd == 'transfer_territory' else '%s <- %s' % (region, target)
    elif cmd == 'troops_move':      # '/troops move Argentina Falklands 2': destination may be a region or a country
        if not a:
            return 'Uso: /troops move <yo> <region|pais|mar> [n unidades] (a un mar van las flotas)'
        n = int(a[-1]) if len(a) > 1 and a[-1].isdigit() else 0
        res = bot.move_troops(' '.join(a[:-1] if n else a), n)
        if res.startswith('PREGUNTA'):      # not at war with the owner: a command doesn't declare war on its own
            return 'No estamos en guerra con %s: mis tropas no pueden entrar.' % res.split(' con ', 1)[1].split(',')[0]
        return 'Hecho: ' + res
    elif cmd == 'government':
        gov = next((g for g in bot.GOVS if a and g.lower() == a[0].lower()), None)
        if not gov:
            return 'Regimenes: ' + ', '.join(bot.GOVS)
        bot.set_government(gov)
    return 'Hecho: %s %s.' % (cmd.replace('_', ' '), target)


assert chat_command(type('B', (), {'cfg': {'country': 'Greece'}})(), 'x', 'hola') is None

ADVISORS = {'military': 'militar', 'economy': 'económico', 'diplomacy': 'diplomático'}
SAY_TEXT = {'name': 'say', 'description': 'El texto que se escribe en el chat.',
            'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}


def advisor(bot, who, args):
    """'/advisor ...' in multiplayer: our leader advises the asker from the world picture (briefing), no moves."""
    import ai_chat
    if not args or args[0].lower() not in ADVISORS:
        return 'Uso: /advisor military|economy|diplomacy [pregunta]'
    r = ai_chat.chat('Eres el asesor %s de %s en Making History. Con los datos reales de la situación del mundo, '
                     'responde en 2-4 frases concretas con cifras y una recomendación; no inventes datos ni hagas '
                     'jugadas. Responde con say, en %s.' % (ADVISORS[args[0].lower()], who, bot.cfg['language']),
                     [{'role': 'user', 'text': 'Situación del mundo:\n%s\n\nPregunta de %s: %s' % (
                         getattr(bot, 'world', '') or '(todavía sin analizar)', who,
                         ' '.join(args[1:]) or 'situación general y qué hacer ahora')}], [SAY_TEXT])
    return next(((c.get('args') or {}).get('text') for c in r.get('calls') or [] if c['name'] == 'say'), None) \
        or (r.get('text') or '').strip() or 'El asesor no respondió.'


EDITOR_MAX = 8


def editor(bot, who, phrase):
    """'/editor <phrase>' (only with /yesman on): one LLM request turns it into at most EDITOR_MAX of our own
    chat commands (this bot acts only as its nation, plus /relations set and /ideology align), run here."""
    import ai_chat
    if not getattr(bot, 'yesman', False):
        return '/editor solo funciona con /yesman on.'
    if not phrase.strip():
        return 'Uso: /editor <frase>'
    tool = {'name': 'command', 'description': 'Un comando del chat. ' + HELP.replace('<yo>', bot.cfg['country']),
            'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}, 'required': ['command']}}
    r = ai_chat.chat('Eres el director de juego de Making History. Convierte la frase en como mucho %d comandos del '
                     'chat que existen (actúas como %s; para otras naciones solo /relations set y /ideology align). '
                     'No inventes mecánicas.' % (EDITOR_MAX, bot.cfg['country']),
                     [{'role': 'user', 'text': 'Situación:\n%s\n\nFrase: %s' % (
                         (getattr(bot, 'world', '') or '')[:3000], phrase)}], [tool])
    cmds = [(c.get('args') or {}).get('command', '').strip() for c in r.get('calls') or [] if c['name'] == 'command']
    out = []
    for c in cmds[:EDITOR_MAX]:
        if c.startswith('/') and c.split()[0].lower() not in LLM_BLOCKED:
            try:
                out.append('%s -> %s' % (c, chat_command(bot, who, c)))
            except Exception as e:
                out.append('%s -> error: %s' % (c, str(e)[:100]))
    return 'Editor: ' + (' | '.join(out) or 'ninguna jugada posible.')


def think(bot, chats, new, humans, events=''):
    """One LLM request per event (Open Historia's request-saving mode): the world snapshot goes in the prompt and
    the model answers with every say / action at once. Look-ups (extra rounds) only with 'unlimited_requests'."""
    import ai_chat
    cfg = bot.cfg
    # identical on every call, so providers can cache it
    system = SYSTEM.format(country=cfg['country'], game='Gold' if cfg['game'] == 'gold' else 'MH1',
                           personality=cfg['personality'], goals=cfg['goals'], language=cfg['language'])
    if getattr(bot, 'yesman', False) or getattr(bot, 'ordered', False):      # '/yesman on' or an '/order'
        system += ('\nMODO YESMAN ACTIVO: haz el 100% de lo que te pidan los jugadores humanos, sin discutir, y '
                   'ejecútalo con las herramientas en esta misma respuesta.')
    everyone = bool(new) and all(EVERYONE.search(t) for _, _, t in new)      # only '@everyone' lines: may stay silent
    if any(EVERYONE.search(t) for _, _, t in new):
        system += ('\n@everyone llama a todas las naciones: contesta a ese mensaje solo si a tu nación le interesa de '
                   'verdad el tema (sus intereses, vecinos, guerras, regiones históricas); si no, no digas nada.')
    unlimited = cfg.get('unlimited_requests', False)
    # only the tools that apply now: a weak model picks an answer tool when nothing is pending
    skip = {'look'} if not unlimited else set()
    skip |= {'answer_proposal'} if 'Propuestas pendientes' not in events else set()
    skip |= {'answer_popup'} if 'Avisos pendientes' not in events else set()
    tools = [t for t in TOOLS if t['name'] not in skip]
    order = list(chats)
    keep = cfg.get('chat_lines', 12)
    view = '\n\n'.join('Chat %d:\n%s' % (i, '\n'.join('%s: %s' % l for l in chats[oid][-keep:]))
                       for i, oid in enumerate(order))
    prompt = ('Situación del mundo (se rehace solo cuando cambian alianzas, guerras o tratados):\n%s\n\n'
              'Jugadores humanos: %s\n\n%s\n\nMensajes nuevos:\n%s%s') % (
        getattr(bot, 'world', '') or '(todavía sin analizar)',
        ', '.join('%s (%s)' % (k, v[0]) for k, v in humans.items()) or 'ninguno todavía',
        view or '(sin chats)', '\n'.join('[chat %d] %s: %s' % (order.index(oid), who, text)
                                         for oid, who, text in new) or '(ninguno)', events)
    bot.log('llm_in', {'prompt': prompt})
    msgs = [{'role': 'user', 'text': prompt}]
    for _ in range(3 if unlimited else 2):
        bot.maybe_end_turn(humans)            # never let the LLM hold up the turn
        bot.log('progress', {'text': 'Pensando la respuesta (unos segundos)...'})
        r = ai_chat.chat(system, msgs, tools)
        bot.log('llm_out', {'text': r.get('text'), 'calls': r.get('calls'), 'model': r.get('model')})
        # replies first (people are waiting), then the game actions
        calls = sorted(r.get('calls') or [], key=lambda c: c['name'] not in ('say', 'open_chat'))
        results = []
        for c in calls:
            try:
                res = act(bot, c, chats, order, humans)
            except Exception as e:            # repair, don't retry: report it and go on
                res = 'error: %s' % str(e)[:200]
                bot.log('act_error', {'call': c, 'error': res})
            results.append({'id': c.get('id'), 'name': c['name'], 'content': res or 'hecho'})
        # what it said, it does: announced wars / mobilization become actions if the model forgot the tool
        said = ' '.join((c.get('args') or {}).get('text', '') for c in calls if c['name'] in ('say', 'open_chat'))
        done = {(c['name'], bot.country_name((c.get('args') or {}).get('country', '')) if c['name'] == 'propose' else '')
                for c in calls}
        for name, args in commitments(said):
            key = (name, bot.country_name(args['country']) if name == 'propose' else '')
            if key not in done:
                done.add(key)
                try:
                    act(bot, {'id': 'said', 'name': name, 'args': args}, chats, order, humans)
                    bot.log('commitment', {'action': name, 'args': args})
                except Exception as e:
                    bot.log('act_error', {'call': {'name': name, 'args': args}, 'error': str(e)[:200]})
        bot.maybe_end_turn(humans)
        if new and not everyone and not any(c['name'] in ('say', 'open_chat') for c in calls) and not msgs[-1].get('nudged'):
            # someone wrote and the model gave no reply: one more request, the only retry we allow
            msgs += [{'role': 'assistant', 'text': r.get('text') or '', 'calls': calls, 'raw': r.get('raw')},
                     {'role': 'user', 'results': results}] if calls else []
            msgs.append({'role': 'user', 'text': 'Responde en el chat con say al mensaje nuevo (y actúa si '
                                                 'corresponde, en la misma respuesta).', 'nudged': True})
            continue
        if not any(c['name'] == 'look' for c in calls) and not any(
                str(x['content']).startswith('PREGUNTA') for x in results):      # move_troops: declare war?
            return
        msgs += [{'role': 'assistant', 'text': r.get('text') or '', 'calls': calls, 'raw': r.get('raw')},
                 {'role': 'user', 'results': results}]


def run(bot, steps=None):
    """Main loop: new chat lines from others, proposals or a changed diplomatic situation -> LLM -> chat and
    actions; ends our turn with the last human player. 'steps' limits the number of rounds (tests)."""
    cfg, seen, humans, refreshed = bot.cfg, bot.__dict__.setdefault('seen', {}), {}, 0

    def turn_watcher():
        """Ends our turn as soon as the last human ends theirs, whatever the main loop is busy with (a long
        analysis, an LLM call): the game must never wait for the bot."""
        while bot.con.proc.poll() is None:
            if getattr(bot, 'humans', None) is not None:
                try:
                    with bot.lock:
                        bot.maybe_end_turn(bot.humans)
                except Exception as e:
                    bot.log('turn_error', {'error': str(e)[:200]})
            time.sleep(cfg.get('turn_check_seconds', 5))
    world_state = {'key': None, 'events': '', 'checked': 0}

    def check_world():
        """Rebuilds the world picture when diplo_key() changes; the event text waits in world_state for the main
        loop. Slow (minutes in a big scenario), so it runs in its own thread and never delays chat or commands."""
        world_state['checked'] = time.time()
        key = world_state['key']
        if key is None:
            bot.log('progress', {'text': 'Analizando la situacion del mundo (en segundo plano)...'})
        try:
            new_key = bot.diplo_key()
            if new_key == key:
                return
            world, new_key = bot.briefing()
        except Exception as e:      # state not readable right now (e.g. while the game starts)
            bot.log('briefing_error', {'error': str(e)[:300]})
            return
        world_state['events'] += ('\n\nLa partida empieza: analiza la situación del mundo y decide tu estrategia; '
                                  'actúa si hace falta.' if key is None else '\n\nCambió la situación diplomática '
                                  '(alianzas, guerras o tratados): revisa la situación del mundo y decide si debes actuar.')
        bot.world, world_state['key'] = world, new_key
        bot.log('briefing', {'first': key is None})

    def world_watcher():
        while bot.con.proc.poll() is None:
            check_world()
            time.sleep(cfg.get('world_check_seconds', 60))
    if steps is None:
        threading.Thread(target=turn_watcher, daemon=True).start()
        threading.Thread(target=world_watcher, daemon=True).start()
    answered = bot.__dict__.setdefault('answered', set())   # proposals already shown to the LLM
    answered_dp = set()                                     # popups already shown to the LLM
    for oid, lines in bot.chats().items():                  # what was said before we joined is not news
        seen.setdefault(oid, len(lines))
    bot.seen = seen                                         # ack_while_busy compares against it
    while bot.con.proc.poll() is None and steps != 0:
        steps = None if steps is None else steps - 1
        if time.time() - refreshed > cfg.get('players_refresh_seconds', 60):     # cheap: only the taken nations
            humans, refreshed = bot.players(), time.time()
            bot.humans = humans
        bot.maybe_end_turn(humans)
        chats = bot.chats()
        new = []
        for oid, lines in chats.items():
            new += [(oid, who, text) for who, text in lines[seen.get(oid, 0):] if who != cfg['country']]
            seen[oid] = len(lines)
        orders = []
        for oid, who, text in list(new):      # '/commands' run locally, no LLM (see chat_command)
            m = re.match(r'\s*/(?:order|orden)\s+(.+)$', text, re.I | re.S)
            if m:      # '/order Italia declara la guerra a Grecia': obeyed only by the bot of the nation named first
                words = m.group(1).replace('_', ' ').split()
                import sp_chat      # exact names or Spanish aliases only ('Reino Unido' takes two words)
                n = next((n for n in (1, 2, 3) if sp_chat.exact_nations(bot, [' '.join(words[:n])]) == [cfg['country']]), 0)
                new.remove((oid, who, text))
                if n and words[n:]:
                    orders.append((oid, who, 'ORDEN DIRECTA de %s, que cumples ya con tus herramientas (jugada + say): %s'
                                   % (who, ' '.join(words[n:]))))
                continue
            if text.strip().startswith('/'):
                try:
                    reply = chat_command(bot, who, text)
                except Exception as e:
                    reply = 'No pude: %s' % str(e)[:150]
                if reply:
                    bot.say(oid, reply)
                    bot.log('command', {'from': who, 'text': text, 'reply': reply})
                    new.remove((oid, who, text))
        new = [(oid, who, text) for oid, who, text in new if bot.addressed(oid, text)] + orders   # general: when named
        bot.ordered = bool(orders)      # think(): one request as with /yesman on
        for _, who, _ in new:      # whoever writes in the chat is a human player (no full rescan needed)
            if who not in humans and who in getattr(bot, 'all_players', {}):
                humans[who] = (who, bot.all_players[who])
        if steps is not None and not new and time.time() - world_state['checked'] > cfg.get('world_check_seconds', 60):
            check_world()      # tests: no threads
        events, world_state['events'] = world_state['events'], ''
        key = world_state['key']
        auto = cfg.get('autopilot', True)
        if auto:      # the nation runs itself like a CPU one; the LLM only sees chat and diplomacy
            for step in (bot.autopilot_turn, bot.autopilot_popups):
                try:
                    done = step()
                    if done:
                        bot.log('autopilot', {'done': done})
                except Exception as e:
                    bot.log('autopilot_error', {'step': step.__name__, 'error': str(e)[:300]})
        pops = [d for d in bot.popups() if d['id'] not in answered_dp
                and (not auto or d['tipo'].startswith('Generic_TreatyProposed'))]   # the rest: autopilot_popups
        if pops:
            events += '\n\nAvisos pendientes (responde con answer_popup):\n' + '\n'.join(
                json.dumps(d, ensure_ascii=False) for d in pops)
            answered_dp.update(d['id'] for d in pops)
        if getattr(bot, 'chatty', False) and getattr(bot, 'new_turn', False) and getattr(bot, 'general', None):
            bot.new_turn = False      # one unprompted remark per turn, in the general chat
            general = sorted(bot.general)[0]
            if general in chats:
                events += ('\n\nModo parlanchín: empieza un turno nuevo. Escribe en el chat %d (el general) un comentario '
                           'breve y con personalidad sobre la situación (guerras, alianzas, tus regiones históricas, '
                           'tus planes).' % list(chats).index(general))
        props = [t for t in bot.proposals() if t['para'] == cfg['country'] and t['id'] not in answered]
        if props:
            events += '\n\nPropuestas pendientes (responde con answer_proposal):\n' + '\n'.join(
                json.dumps(t, ensure_ascii=False) for t in props)
            answered.update(t['id'] for t in props)
        if new or events:
            bot.log('chat_in', {'lines': [[w, t] for _, w, t in new], 'proposals': props})
            for oid in dict.fromkeys(o for o, _, t in new if not EVERYONE.search(t)):      # local, instant: nobody waits for the LLM in silence
                bot.say(oid, (cfg.get('busy_reply') or bot.BUSY_REPLY).replace('%s', cfg['country']))
            try:
                think(bot, chats, new, humans, events)
            except Exception as e:      # the provider can fail (quota, network): keep playing
                bot.log('llm_error', {'error': str(e)[:300]})
            seen.update({oid: len(lines) for oid, lines in bot.chats().items()})   # our own replies are not news
        bot.maybe_end_turn(humans)
        if not new and not events and key is not None and getattr(bot, '_country_ids', None) is None:
            try:      # quiet moment: a few nation ids per round (improve_relations needs them)
                bot.country_ids_step()
            except Exception as e:
                bot.log('ids_error', {'error': str(e)[:200]})
        elif not new and not events and key is not None and getattr(bot, '_research', None) is None:
            try:      # quiet moment: read the research list once; it reaches the LLM with the next world picture
                bot.research_options()
                bot.world = bot.world + '\n\n## Investigación disponible (research)\n' + (', '.join(bot._research) or 'ninguna')
            except Exception as e:
                bot.log('research_error', {'error': str(e)[:200]})
        time.sleep(cfg['poll_seconds'])
    if bot.con.proc.poll() is not None:
        bot.log('exit', {'code': bot.con.proc.returncode})


def supervise():
    """Run from a console window (AI Player.bat): driving console.exe means detaching from our own console, which
    would take this window away. So the bot runs as a console-less child and this window shows its output; closing
    the window (or Ctrl+C) stops the child and with it console.exe (both in kill-on-close jobs)."""
    import subprocess
    from mh_console import k32
    out = os.path.join(LOGS, 'ai_player_output.txt')
    env = dict(os.environ, AI_PLAYER_CHILD='1', PYTHONIOENCODING='utf-8')
    with open(out, 'w', encoding='utf-8') as f:
        child = subprocess.Popen([sys.executable, os.path.abspath(__file__)] + sys.argv[1:], env=env, stdout=f,
                                 stderr=subprocess.STDOUT, creationflags=0x00000008)   # DETACHED_PROCESS
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    job = k32.CreateJobObjectW(None, None)
    info = (ctypes.c_byte * 144)()
    struct.pack_into('<I', info, 16, 0x2000)                    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(ctypes.c_void_p(job), 9, info, ctypes.sizeof(info))
    k32.AssignProcessToJobObject(ctypes.c_void_p(job), ctypes.c_void_p(int(child._handle)))
    print('Buscando la partida en el lobby... (deja abierta esta ventana; cerrarla saca al bot)', flush=True)
    pos = 0
    try:
        while True:
            with open(out, encoding='utf-8', errors='replace') as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            if chunk:
                print(chunk, end='', flush=True)
            if child.poll() is not None and not chunk:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        child.kill()
    print('\n[AI player stopped, code %s]' % child.returncode)


def notice(kind, d):
    """What the launcher window shows for a log event (the game itself doesn't always show joins); None = quiet."""
    if kind == 'game':
        return 'Partida encontrada: %s (%s). Uniendose...' % (d.get('name'), d.get('scenario'))
    if kind == 'joined':
        return '*** EL BOT SE UNIO COMO %s. Ya puedes iniciar la partida. ***' % str(d.get('country')).upper()
    if kind == 'chat_in':
        lines = ['  %s: %s' % (w, t) for w, t in d.get('lines', [])]
        lines += ['  propuesta %s de %s: %s' % (p.get('id'), p.get('de'), p.get('tipo')) for p in d.get('proposals', [])]
        return 'Recibido:\n' + '\n'.join(lines)
    if kind == 'did':
        a = d.get('args') or {}
        return 'Bot -> %s %s' % (d.get('name'), a.get('text') or json.dumps(a, ensure_ascii=False))
    if kind == 'progress':
        return d.get('text')
    if kind == 'briefing':
        return 'Situacion del mundo analizada.' if d.get('first') else 'Cambio la situacion diplomatica: reanalizado.'
    if kind == 'end_turn':
        return 'Turno terminado.'
    if kind in ('llm_error', 'act_error', 'exit'):
        return 'ERROR %s: %s' % (kind, str(d.get('error') or d)[:300])
    if kind in ('llm_in', 'llm_out', 'sent', 'ignored_call'):
        return None
    return '%s %s' % (kind, json.dumps(d, ensure_ascii=False))


assert 'SE UNIO COMO CHILE' in notice('joined', {'country': 'Chile'})


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--config', default=CONFIG)
    args = ap.parse_args()
    cfg = load_config(args.config)
    os.makedirs(LOGS, exist_ok=True)
    if os.environ.get('AI_PLAYER_CHILD') != '1' and ctypes.windll.kernel32.GetConsoleWindow():
        return supervise()
    trace = open(os.path.join(LOGS, 'ai_player_%s.jsonl' % datetime.datetime.now().strftime('%Y%m%d-%H%M%S')),
                 'a', encoding='utf-8')

    def log(kind, data):
        rec = {'t': datetime.datetime.now().isoformat(timespec='seconds'), 'kind': kind, **data}
        trace.write(json.dumps(rec, ensure_ascii=False) + '\n')
        trace.flush()
        msg = notice(kind, data)
        if msg:
            print('[%s] %s' % (rec['t'][11:], msg), flush=True)

    bot = Bot(cfg, log)
    try:
        bot.join()
        run(bot)
    finally:
        bot.con.close()


if __name__ == '__main__':
    main()
