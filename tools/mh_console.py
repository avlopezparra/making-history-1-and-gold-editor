"""Drives the game's headless core (bin/console.exe) through its built-in command line (CLI).

console.exe reads keys with _kbhit/_getch, so piping stdin does nothing: commands are typed into its own
console with WriteConsoleInputW. Its stdout is fully buffered when redirected (nothing shows until exit), so the
output is read from the console's screen buffer instead and mirrored into a log file.
Works for MH1 and Gold (same console.exe/cli.dll). Used by ai_player.py.
"""
import ctypes
import ctypes.wintypes as w
import os
import re
import struct
import subprocess
import time

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateFileW.restype = w.HANDLE
k32.OpenProcess.restype = w.HANDLE


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [('bKeyDown', w.BOOL), ('wRepeatCount', w.WORD), ('wVirtualKeyCode', w.WORD),
                ('wVirtualScanCode', w.WORD), ('UnicodeChar', w.WCHAR), ('dwControlKeyState', w.DWORD)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [('EventType', w.WORD), ('_pad', w.WORD), ('Event', KEY_EVENT_RECORD)]


class CSBI(ctypes.Structure):
    _fields_ = [('dwSize', w._COORD), ('dwCursorPosition', w._COORD), ('wAttributes', w.WORD),
                ('srWindow', w.SMALL_RECT), ('dwMaximumWindowSize', w._COORD)]


ROWS, COLS = 9000, 200


# RVA of the objectcore.dll export ?ms_eSystemMode@CObjectManager@@ (identical in MH1 and Gold 2.0.4 builds)
SYSTEM_MODE_RVA = 0x13c9f0


def _pe(path):
    """(file bytes, PE header offset, rva -> file offset) for a 32-bit DLL of the game."""
    with open(path, 'rb') as f:
        pe = f.read()
    peo = struct.unpack_from('<I', pe, 0x3C)[0]
    nsec, optsize = struct.unpack_from('<H', pe, peo + 6)[0], struct.unpack_from('<H', pe, peo + 20)[0]
    sections = [struct.unpack_from('<8sIIII', pe, peo + 24 + optsize + 40 * i) for i in range(nsec)]

    def off(rva):
        for _, vsize, va, rawsize, raw in sections:
            if va <= rva < va + max(vsize, rawsize):
                return rva - va + raw
        raise ValueError('RVA %#x outside the sections' % rva)
    return pe, peo, off


def export_rva(path, name_prefix):
    """RVA of the first export of 'path' whose name starts with name_prefix."""
    pe, peo, off = _pe(path)
    d = off(struct.unpack_from('<I', pe, peo + 24 + 96)[0])    # data directory 0 (exports)
    nnames, funcs, names, ords = struct.unpack_from('<IIII', pe, d + 24)
    for i in range(nnames):
        o = off(struct.unpack_from('<I', pe, off(names) + 4 * i)[0])
        if pe[o:pe.index(b'\0', o)].startswith(name_prefix):
            return struct.unpack_from('<I', pe, off(funcs) + 4 * struct.unpack_from('<H', pe, off(ords) + 2 * i)[0])[0]
    raise ValueError('%s not exported by %s' % (name_prefix, path))


def vtable_slot(path, cls, method):
    """(vtable RVA, slot index) of cls::method in the module at 'path', from its exported vftable and method."""
    pe, _, off = _pe(path)
    vt, fn = export_rva(path, b'??_7%s@@6B@' % cls), export_rva(path, b'?%s@%s@' % (method, cls))
    base = struct.unpack_from('<I', pe, struct.unpack_from('<I', pe, 0x3C)[0] + 24 + 28)[0]   # ImageBase
    for i in range(64):
        if struct.unpack_from('<I', pe, off(vt) + 4 * i)[0] - base == fn:
            return vt, i
    raise ValueError('%s::%s not in its vtable' % (cls, method))


def import_slot(path, dll, name_prefix):
    """RVA of the import address table entry through which the module at 'path' calls 'dll'!name (first name that
    starts with name_prefix). Finds the same slot in MH1's and Gold's game.dll without hard-coding it."""
    pe, peo, off = _pe(path)
    d = off(struct.unpack_from('<I', pe, peo + 24 + 104)[0])   # data directory 1 (imports), PE32 optional header
    while True:
        names, _, _, dname, first = struct.unpack_from('<IIIII', pe, d)
        if not first:
            break
        if pe[off(dname):pe.index(b'\0', off(dname))].decode().lower() == dll:
            i = 0
            while True:
                thunk = struct.unpack_from('<I', pe, off(names or first) + 4 * i)[0]
                if not thunk:
                    break
                if not thunk & 0x80000000:
                    o = off(thunk) + 2
                    if pe[o:pe.index(b'\0', o)].startswith(name_prefix):
                        return first + 4 * i
                i += 1
        d += 20
    raise ValueError('%s!%s not imported by %s' % (dll, name_prefix, path))


JB, JL, JZ, JNZ, JNE, JMP = 0x72, 0x7C, 0x74, 0x75, 0x75, 0xEB


def assemble(parts):
    """Joins x86 code pieces: bytes as they are, ('label', name) marks a position, (opcode, name) is a short jump
    to it and ('near', name) a 'jmp rel32'. Saves counting jump distances by hand."""
    labels, size = {}, 0
    for p in parts:
        if isinstance(p, tuple) and p[0] == 'label':
            labels[p[1]] = size
        else:
            size += (5 if p[0] == 'near' else 2) if isinstance(p, tuple) else len(p)
    out = b''
    for p in parts:
        if isinstance(p, tuple) and p[0] == 'label':
            continue
        if isinstance(p, tuple) and p[0] == 'near':
            out += b'\xe9' + struct.pack('<i', labels[p[1]] - (len(out) + 5))
        elif isinstance(p, tuple):
            d = labels[p[1]] - (len(out) + 2)
            assert -128 <= d <= 127, 'jump to %s too far' % p[1]
            out += bytes([p[0], d & 0xFF])
        else:
            out += p
    return out


assert assemble([(JMP, 'a'), b'\x90', ('label', 'a')]) == b'\xeb\x01\x90'
assert assemble([('near', 'a'), b'\x90', ('label', 'a')]) == b'\xe9\x01\x00\x00\x00\x90'


def steam_dir(game):
    """Folder holding Steam.dll (program.dll imports it; makehist.exe finds it through Steam)."""
    p = os.path.abspath(game)
    for _ in range(5):
        p = os.path.dirname(p)
        if os.path.isfile(os.path.join(p, 'Steam.dll')):
            return p
    return r'C:\Program Files (x86)\Steam'


DISPATCH_MAGIC = b'MHDispatch1'      # in enable_dispatch's block: a later call finds it and installs nothing


class Console:
    def __init__(self, game, out_path):
        self.game, self.out_path = game, out_path
        env = dict(os.environ)
        env['PATH'] = steam_dir(game) + ';' + os.path.join(game, 'bin') + ';' + env.get('PATH', '')
        self._out = open(out_path, 'w', encoding='utf-8', errors='replace')
        si = subprocess.STARTUPINFO()
        si.dwFlags, si.wShowWindow = 1, 7          # STARTF_USESHOWWINDOW, SW_SHOWMINNOACTIVE: never takes focus
        self.proc = subprocess.Popen([os.path.join(game, 'bin', 'console.exe')], cwd=os.path.join(game, 'bin'),
                                     env=env, startupinfo=si, creationflags=subprocess.CREATE_NEW_CONSOLE)
        # a job that kills console.exe when we exit, so closing the bot's window never leaves it running
        k32.CreateJobObjectW.restype = w.HANDLE
        self._job = k32.CreateJobObjectW(None, None)
        info = (ctypes.c_byte * 144)()                          # JOBOBJECT_EXTENDED_LIMIT_INFORMATION (x64)
        struct.pack_into('<I', info, 16, 0x2000)                # LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(w.HANDLE(self._job), 9, info, ctypes.sizeof(info))
        k32.AssignProcessToJobObject(w.HANDLE(self._job), w.HANDLE(int(self.proc._handle)))
        self._pos = 0
        self._text = ''
        time.sleep(1)
        with self._attached():
            k32.SetConsoleScreenBufferSize(self._h('CONOUT$'), w._COORD(COLS, ROWS))

    def _h(self, name):
        return k32.CreateFileW(name, 0xC0000000, 3, None, 3, 0, None)

    class _Att:
        def __init__(self, proc):
            self.proc = proc

        def __enter__(self):
            k32.FreeConsole()
            for _ in range(20):
                if k32.AttachConsole(self.proc.pid):
                    return
                if self.proc.poll() is not None:
                    raise RuntimeError('console.exe exited (code %s)' % self.proc.returncode)
                time.sleep(0.2)
            raise OSError('AttachConsole failed (%d)' % ctypes.get_last_error())

        def __exit__(self, *a):
            k32.FreeConsole()

    def _attached(self):
        return self._Att(self.proc)

    def poll_output(self):
        """Reads the rows printed since the last call from the screen buffer, appends them to the log and returns
        them. When the buffer is half full it is wiped and the cursor sent home, so it never scrolls."""
        with self._attached():
            h = self._h('CONOUT$')
            info = CSBI()
            k32.GetConsoleScreenBufferInfo(h, ctypes.byref(info))
            cols = info.dwSize.X        # the resize may be refused; use the real width
            end = info.dwCursorPosition.Y * cols + info.dwCursorPosition.X
            new = ''
            if end < self._pos:      # the screen was cleared or reset (it happens when the game starts)
                self._pos = 0
            if end > self._pos:      # linear offset in the buffer, so the half-written prompt row is read too
                n = end - self._pos
                buf = ctypes.create_unicode_buffer(n + 1)
                got = w.DWORD()
                k32.ReadConsoleOutputCharacterW(h, buf, n, w._COORD(self._pos % cols, self._pos // cols),
                                                ctypes.byref(got))
                raw, out = buf.value[:got.value], []
                first = cols - self._pos % cols          # chars left on the first row
                cuts = [0] + list(range(first, len(raw), cols)) + [len(raw)]
                for i in range(len(cuts) - 1):
                    row = raw[cuts[i]:cuts[i + 1]]
                    # a row filled to the last column wrapped onto the next one: no line break there
                    full = cuts[i + 1] - cuts[i] == (first if i == 0 else cols) and row[-1:] not in ('', ' ')
                    out.append(row if full else row.rstrip() + '\n')
                new = ''.join(out)
                if new.endswith('\n') and end % cols:   # the cursor's own row is still being written
                    new = new[:-1]
                self._pos = end
            if info.dwCursorPosition.Y > info.dwSize.Y // 2:
                got = w.DWORD()
                k32.FillConsoleOutputCharacterW(h, ctypes.c_wchar(' '), info.dwSize.Y * cols, w._COORD(0, 0), ctypes.byref(got))
                k32.SetConsoleCursorPosition(h, w._COORD(0, 0))
                self._pos = 0
            k32.CloseHandle(h)
        if new:
            # the CD key travels in ActJoinGame (strKey) and the host logs it: never keep it in our logs
            self._out.write(re.sub(r'\b[0-9A-F]{4}(?:-[0-9A-F]{4}){4,}\b', '<key>', new))
            self._out.flush()
            self._text += new
        return new

    def wait_ready(self, timeout=90):
        """The core prints its prompt '>' once the CLI is up."""
        t = time.time()
        while time.time() - t < timeout:
            self.poll_output()
            if '>' in self._text:
                return True
            if self.proc.poll() is not None:
                raise RuntimeError('console.exe exited (%s)' % self.proc.returncode)
            time.sleep(1)
        return False

    def send(self, line, delay=0.02):
        """Types one command line + Enter into console.exe's own console (does not touch the focused window)."""
        with self._attached():
            h = self._h('CONIN$')
            n = w.DWORD()
            for ch in line + '\r':
                for down in (1, 0):
                    r = INPUT_RECORD(EventType=1)
                    r.Event = KEY_EVENT_RECORD(down, 1, 0x0D if ch == '\r' else 0, 0, ch, 0)
                    k32.WriteConsoleInputW(h, ctypes.byref(r), 1, ctypes.byref(n))
                time.sleep(delay)   # the CLI autocompletes; typing too fast garbles commands
            k32.CloseHandle(h)

    def _open(self):
        h = k32.OpenProcess(0x043A, False, self.proc.pid)   # VM_OPERATION|VM_READ|VM_WRITE|CREATE_THREAD|QUERY_INFO
        if not h:
            raise OSError('OpenProcess failed (%d)' % ctypes.get_last_error())
        return w.HANDLE(h)

    def _module_base(self, h, dll):
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        mods, need = (ctypes.c_void_p * 1024)(), w.DWORD()
        psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 0x01)   # 32-bit modules
        name = ctypes.create_unicode_buffer(260)
        for m in mods[:need.value // ctypes.sizeof(ctypes.c_void_p)]:
            psapi.GetModuleBaseNameW(h, ctypes.c_void_p(m), name, 260)
            if name.value.lower() == dll:
                return m
        raise OSError('%s not loaded yet' % dll)

    def _write(self, h, addr, data):
        n = ctypes.c_size_t()
        if not k32.WriteProcessMemory(h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(n)):
            raise OSError('WriteProcessMemory failed (%d)' % ctypes.get_last_error())

    def enable_dev_mode(self):
        """Release builds disable the CLI 'action' command: it requires CObjectManager::ms_eSystemMode == 1
        (objectcore.dll export, SYSTEM_MODE_RVA; checked by game.dll before running it). We set it in
        our own console.exe only; no game file and no other game process is touched."""
        h = self._open()
        try:
            self._write(h, self._module_base(h, 'objectcore.dll') + SYSTEM_MODE_RVA, struct.pack('<i', 1))
            return True
        finally:
            k32.CloseHandle(h)

    def set_license_key(self, key):
        """Makes this console.exe present another license key, one the user owns, when it joins a game (the game
        allows one player per key, so a second player needs a second key). Only our own process changes; the
        registry and the user's game keep their key.

        On joining, CActJoinGame::PreProcess calls CLicenseKey::LoadKeyFromRegistry (0 = loaded, 3 = invalid).
        We point game.dll's import of that function at a small stub that calls CLicenseKey::SetKeyString with the
        configured key instead, so the game's own validation still decides (and the host checks it again in
        CGame::AddSessionKey)."""
        digits = re.sub(r'[\s-]', '', key).upper()
        if not re.fullmatch(r'[0-9A-F]{32}', digits):
            raise ValueError('a license key has 32 hexadecimal digits')
        key = '-'.join(digits[i:i + 4] for i in range(0, 32, 4))   # the only form the game accepts: 8 groups of 4
        game_dll = os.path.join(self.game, 'bin', 'game.dll')
        load_slot = import_slot(game_dll, 'licensing.dll', b'?LoadKeyFromRegistry@CLicenseKey@')
        set_slot = import_slot(game_dll, 'licensing.dll', b'?SetKeyString@CLicenseKey@')
        h = self._open()
        try:
            gbase = self._module_base(h, 'game.dll')
            k32.VirtualAllocEx.restype = ctypes.c_void_p
            mem = k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)   # MEM_COMMIT|RESERVE, PAGE_EXECUTE_READWRITE
            if not mem:
                raise OSError('VirtualAllocEx failed (%d)' % ctypes.get_last_error())
            text, sstr, stub = mem + 0x40, mem, mem + 0x100
            self._write(h, text, (key + '\0').encode('utf-16-le'))
            # MSVC 7.1 std::basic_string<unsigned short>: allocator(4) | buffer or pointer(16) | size | capacity
            self._write(h, sstr, struct.pack('<II12xII', 0, text, len(key), len(key)))
            code = (b'\x68' + struct.pack('<I', sstr) +                 # push &key   (thiscall: ecx = this)
                    b'\xff\x74\x24\x08' +                              # push dword [esp+8]   (product id)
                    b'\xff\x15' + struct.pack('<I', gbase + set_slot) +  # call [SetKeyString]
                    b'\x84\xc0' +                                      # test al, al
                    b'\xb8\x00\x00\x00\x00' +                          # mov eax, 0   (LoadResult: loaded)
                    b'\x75\x05' +                                      # jnz done
                    b'\xb8\x03\x00\x00\x00' +                          # mov eax, 3   (LoadResult: invalid key)
                    b'\xc2\x04\x00')                                   # done: ret 4
            self._write(h, stub, code)
            slot, old = gbase + load_slot, w.DWORD()
            k32.VirtualProtectEx(h, ctypes.c_void_p(slot), 4, 0x04, ctypes.byref(old))
            self._write(h, slot, struct.pack('<I', stub))
            k32.VirtualProtectEx(h, ctypes.c_void_p(slot), 4, old, ctypes.byref(old))
            return True
        finally:
            k32.CloseHandle(h)

    def skip_parse(self, cls):
        """Makes 'action <Act>' skip cls::ParseCommandLine in our console.exe (it then just returns true). Needed for
        ActAddChat, whose CLI parser is a debug path that dereferences a property missing in release builds and
        crashes; the action itself works like the chat window's (the game fills in game, player and session)."""
        dll = os.path.join(self.game, 'bin', 'game.dll')
        vt, i = vtable_slot(dll, cls.encode(), b'ParseCommandLine')
        h = self._open()
        try:
            k32.VirtualAllocEx.restype = ctypes.c_void_p
            stub = k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)
            self._write(h, stub, bytes.fromhex('b001c20800'))          # mov al, 1 ; ret 8
            slot, old = self._module_base(h, 'game.dll') + vt + 4 * i, w.DWORD()
            k32.VirtualProtectEx(h, ctypes.c_void_p(slot), 4, 0x04, ctypes.byref(old))
            self._write(h, slot, struct.pack('<I', stub))
            k32.VirtualProtectEx(h, ctypes.c_void_p(slot), 4, old, ctypes.byref(old))
        finally:
            k32.CloseHandle(h)

    def set_chat_name(self, name):
        """The chat window sends ActAddToChat with strMyName (shown as 'Country(name):'); the CLI parser leaves it
        empty. We wrap CActAlterProperty::ParseCommandLine (ActAddToChat's class) in our console.exe: after the
        original parser succeeds, the stub sets the action's 'strMyName' property, if it has one, to 'name'."""
        name = ''.join(ch for ch in name if 32 <= ord(ch) < 128)[:20] or 'AI'
        dll = os.path.join(self.game, 'bin', 'game.dll')
        oc = os.path.join(self.game, 'bin', 'objectcore.dll')
        vt, i = vtable_slot(dll, b'CActAlterProperty', b'ParseCommandLine')
        get_prop = export_rva(oc, b'?GetProperty@CMLObject@@QAEPAVCProperty@@ABV?$basic_string@G')
        set_str = export_rva(oc, b'?SetValue@?$CPropTyped@V?$basic_string@G')
        h = self._open()
        try:
            gbase, obase = self._module_base(h, 'game.dll'), self._module_base(h, 'objectcore.dll')
            slot = gbase + vt + 4 * i
            orig, n = ctypes.c_uint32(), ctypes.c_size_t()
            k32.ReadProcessMemory(h, ctypes.c_void_p(slot), ctypes.byref(orig), 4, ctypes.byref(n))
            k32.VirtualAllocEx.restype = ctypes.c_void_p
            mem = k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)

            def wstring(at, text, buf_at):
                """MSVC 7.1 basic_string<unsigned short>: short strings live inside, longer ones in buf_at."""
                raw = (text + '\0').encode('utf-16-le')
                if len(text) < 8:
                    self._write(h, at, struct.pack('<I', 0) + raw.ljust(16, b'\0') + struct.pack('<II', len(text), 7))
                else:
                    self._write(h, buf_at, raw)
                    self._write(h, at, struct.pack('<II12xII', 0, buf_at, len(text), len(text)))
            wstring(mem, 'strMyName', mem + 0x40)
            wstring(mem + 0x80, name, mem + 0xC0)
            ptrs = mem + 0x100                                   # [orig parse, GetProperty, SetValue]
            self._write(h, ptrs, struct.pack('<III', orig.value, obase + get_prop, obase + set_str))
            stub = mem + 0x200
            P = lambda k: struct.pack('<I', ptrs + 4 * k)
            code = (b'\x53' +                                  # push ebx
                    b'\x8b\xd9' +                              # mov ebx, ecx          (this)
                    b'\xff\x74\x24\x0c' +                      # push [esp+0Ch]        (argv)
                    b'\xff\x74\x24\x0c' +                      # push [esp+0Ch]        (argc)
                    b'\x8b\xcb' +                              # mov ecx, ebx
                    b'\xff\x15' + P(0) +                       # call [orig ParseCommandLine]
                    b'\x84\xc0' +                              # test al, al
                    b'\x74\x20' +                              # jz done
                    b'\x68' + struct.pack('<I', mem) +         # push &"strMyName"
                    b'\x8b\xcb' +                              # mov ecx, ebx
                    b'\xff\x15' + P(1) +                       # call [CMLObject::GetProperty(name)]
                    b'\x85\xc0' +                              # test eax, eax
                    b'\x74\x0d' +                              # jz ok                 (no such property)
                    b'\x68' + struct.pack('<I', mem + 0x80) +  # push &name
                    b'\x8b\xc8' +                              # mov ecx, eax
                    b'\xff\x15' + P(2) +                       # call [CPropTyped<wstring>::SetValue]
                    b'\xb0\x01' +                              # ok: mov al, 1
                    b'\x5b' +                                  # done: pop ebx
                    b'\xc2\x08\x00')                           # ret 8
            self._write(h, stub, code)
            old = w.DWORD()
            k32.VirtualProtectEx(h, ctypes.c_void_p(slot), 4, 0x04, ctypes.byref(old))
            self._write(h, slot, struct.pack('<I', stub))
            k32.VirtualProtectEx(h, ctypes.c_void_p(slot), 4, old, ctypes.byref(old))
        finally:
            k32.CloseHandle(h)

    def enable_dispatch(self):
        """Lets us send any action object we build with the CLI ('create' / 'set property'), the way the game's
        CmdCreateAction does: DuplicateObject + CAvatar::AcceptAction. We take over ActPauseGame's
        ParseCommandLine in our console.exe: 'action ActPauseGame <object id> [avatar id]' then sends that object
        instead (and returns false, so no pause is ever sent). The game takes the acting player from the avatar
        that accepts the action, so with an avatar id (a CPU nation's, in a game we host) the action is that
        nation's; without one it is ours (CDriver::GetMyAvatar)."""
        b = os.path.join(self.game, 'bin')
        g, oc, crt = (os.path.join(b, x) for x in ('game.dll', 'objectcore.dll', 'msvcr71.dll'))
        vt, i = vtable_slot(g, b'CActPauseGame', b'ParseCommandLine')
        h = self._open()
        try:
            gb, ob, cb = (self._module_base(h, x) for x in ('game.dll', 'objectcore.dll', 'msvcr71.dll'))
            fn = [cb + export_rva(crt, b'_wtoi'),
                  ob + export_rva(oc, b'?GetObjectW@CObjectManager@'),
                  ob + export_rva(oc, b'?DuplicateObject@CMLObject@'),
                  gb + export_rva(g, b'?GetMyAvatar@CDriver@'),
                  gb + export_rva(g, b'?AcceptAction@CAvatar@'),
                  ob + export_rva(oc, b'?Release@CMLObject@')]
            om, drv = ob + export_rva(oc, b'?ms_lpObjInstance@CObjectManager@'), gb + export_rva(g, b'?ms_lpObjInstance@CDriver@')
            slot = gb + vt + 4 * i
            cur, mark, n = ctypes.c_uint32(), ctypes.create_string_buffer(len(DISPATCH_MAGIC)), ctypes.c_size_t()
            if k32.ReadProcessMemory(h, ctypes.c_void_p(slot), ctypes.byref(cur), 4, ctypes.byref(n)) and \
                    k32.ReadProcessMemory(h, ctypes.c_void_p(cur.value - 0x40 + 0x20), mark, len(DISPATCH_MAGIC),
                                          ctypes.byref(n)) and mark.raw == DISPATCH_MAGIC:
                return      # installed earlier in this game process: never twice (a reconnect or a restart)
            k32.VirtualAllocEx.restype = ctypes.c_void_p
            mem = k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)
            self._write(h, mem, struct.pack('<6I', *fn))
            self._write(h, mem + 0x20, DISPATCH_MAGIC)      # after the 6 function pointers, before the code (0x40)
            call = lambda k: b'\xff\x15' + struct.pack('<I', mem + 4 * k)   # call [fn k]

            def arg_object(n):        # eax = the object whose id is argv[n] (std::wstring argv[], 1Ch each)
                return [b'\x8b\x44\x24\x14',                  # mov eax, [esp+14h]     argv
                        b'\x83\xc0' + bytes([0x1c * n]),      # add eax, 1Ch*n         argv[n] (argv[0] = action name)
                        b'\x8d\x48\x04',                      # lea ecx, [eax+4]       short string: inline buffer
                        b'\x83\x78\x18\x08', (JB, 'short%d' % n),   # cmp dword [eax+18h], 8 (capacity) ; jb
                        b'\x8b\x48\x04',                      # mov ecx, [eax+4]       long string: pointer
                        ('label', 'short%d' % n),
                        b'\x51', call(0), b'\x83\xc4\x04',    # push ecx ; call [_wtoi] ; add esp, 4
                        b'\x50',                              # push eax               object id
                        b'\x8b\x0d' + struct.pack('<I', om),  # mov ecx, [CObjectManager::ms_lpObjInstance]
                        call(1)]                              # call [GetObjectW]
            code = assemble([
                b'\x53\x56\x57',                              # push ebx ; push esi ; push edi
                b'\x33\xff',                                  # xor edi, edi           avatar: none yet
                b'\x83\x7c\x24\x10\x03', (JL, 'action')] +    # cmp dword [esp+10h], 3 (argc) ; jl action
                arg_object(2) + [b'\x8b\xf8',                 # mov edi, eax           the given avatar
                ('label', 'action')] +
                arg_object(1) + [
                b'\x85\xc0', (JZ, 'fail'),                    # test eax, eax ; jz fail
                b'\x8b\xc8', call(2),                         # mov ecx, eax ; call [DuplicateObject]
                b'\x85\xc0', (JZ, 'fail'),                    # test eax, eax ; jz fail
                b'\x8b\xf0',                                  # mov esi, eax
                b'\x85\xff', (JNZ, 'send'),                   # test edi, edi ; jnz send
                b'\x8b\x0d' + struct.pack('<I', drv),         # mov ecx, [CDriver::ms_lpObjInstance]
                call(3), b'\x8b\xf8',                         # call [GetMyAvatar] ; mov edi, eax
                ('label', 'send'),
                b'\x85\xff', (JZ, 'release'),                 # test edi, edi ; jz release
                b'\x56', b'\x8b\xcf', call(4),                # push esi ; mov ecx, edi ; call [AcceptAction]
                ('label', 'release'),
                b'\x8b\xce', call(5),                         # mov ecx, esi ; call [Release]
                ('label', 'fail'),
                b'\x32\xc0',                                  # xor al, al
                b'\x5f\x5e\x5b', b'\xc2\x08\x00'])            # pop edi ; pop esi ; pop ebx ; ret 8
            self._write(h, mem + 0x40, code)
            old = w.DWORD()
            k32.VirtualProtectEx(h, ctypes.c_void_p(slot), 4, 0x04, ctypes.byref(old))
            self._write(h, slot, struct.pack('<I', mem + 0x40))
            k32.VirtualProtectEx(h, ctypes.c_void_p(slot), 4, old, ctypes.byref(old))
        finally:
            k32.CloseHandle(h)

    def use_own_namespace(self):
        """The CLI 'action' command looks the action type up in the namespace number the game object carries, which
        comes from the host. When the normal game hosts, that number means something else in our console.exe and
        every action fails ('Unable to parse action type'). We make it use our avatar's own namespace (game/, where
        all actions are defined) by turning the 'jne' that picks the game's namespace into two NOPs."""
        dll = os.path.join(self.game, 'bin', 'game.dll')
        pe, peo, _ = _pe(dll)
        m = re.search(rb'\x83\x78\x1c\xff\x75\x0a\x8b\xcd\xff\x15....\xeb\x07\x8b\xce\xe8', pe, re.S)
        if not m:
            raise OSError('namespace choice not found in game.dll')
        nsec, optsize = struct.unpack_from('<H', pe, peo + 6)[0], struct.unpack_from('<H', pe, peo + 20)[0]
        rva = None
        for i in range(nsec):
            _, vsize, va, rawsize, raw = struct.unpack_from('<8sIIII', pe, peo + 24 + optsize + 40 * i)
            if raw <= m.start() < raw + rawsize:
                rva = m.start() - raw + va + 4                      # the 'jne' (75 0a)
        h = self._open()
        try:
            addr, old = self._module_base(h, 'game.dll') + rva, w.DWORD()
            k32.VirtualProtectEx(h, ctypes.c_void_p(addr), 2, 0x40, ctypes.byref(old))
            self._write(h, addr, b'\x90\x90')
            k32.VirtualProtectEx(h, ctypes.c_void_p(addr), 2, old, ctypes.byref(old))
        finally:
            k32.CloseHandle(h)

    def set_action_namespace(self, ns):
        """After use_own_namespace, 'action' resolves types in our driver's namespace (game/), which doesn't hold
        the scenario's own actions (ActProposeDeclareWar, ActIncArmySize...). Once the scenario is loaded we make it
        use namespace 'ns' (the scenario's, which inherits game/ and core/): the 'mov ecx, ebp; call
        [GetNameSpaceID]' on that path becomes 'mov eax, ns' + NOPs."""
        dll = os.path.join(self.game, 'bin', 'game.dll')
        pe, peo, _ = _pe(dll)
        m = re.search(rb'\x83\x78\x1c\xff(?:\x75\x0a|\x90\x90)\x8b\xcd\xff\x15....\xeb\x07\x8b\xce\xe8', pe, re.S)
        if not m:
            raise OSError('namespace choice not found in game.dll')
        nsec, optsize = struct.unpack_from('<H', pe, peo + 6)[0], struct.unpack_from('<H', pe, peo + 20)[0]
        rva = None
        for i in range(nsec):
            _, vsize, va, rawsize, raw = struct.unpack_from('<8sIIII', pe, peo + 24 + optsize + 40 * i)
            if raw <= m.start() < raw + rawsize:
                rva = m.start() - raw + va + 6                      # 'mov ecx, ebp; call [GetNameSpaceID]'
        h = self._open()
        try:
            addr, old = self._module_base(h, 'game.dll') + rva, w.DWORD()
            k32.VirtualProtectEx(h, ctypes.c_void_p(addr), 8, 0x40, ctypes.byref(old))
            self._write(h, addr, b'\xb8' + struct.pack('<I', int(ns)) + b'\x90\x90\x90')
            k32.VirtualProtectEx(h, ctypes.c_void_p(addr), 8, old, ctypes.byref(old))
        finally:
            k32.CloseHandle(h)

    def set_create_namespace(self, ns):
        """'create <dest> <prop> <type>' looks the type up in the destination object's namespace. Our avatar's
        (game/) lacks the scenario's types (ActProposeTradeDeal, ResourceAmountPair...), and building them in the
        host's replicated player data crashes a joined console.exe. So CmdCreateObject gets namespace 'ns' instead:
        'movsx eax, byte [edi+4]' before GetTypeID becomes 'push ns; pop eax; nop'."""
        dll = os.path.join(self.game, 'bin', 'objectcore.dll')
        pe, peo, _ = _pe(dll)
        m = re.search(rb'\x0f\xbe\x47\x04\x8b\x4c\x24\x14\x50\x55\xe8', pe)
        if not m:
            raise OSError('CmdCreateObject namespace not found in objectcore.dll')
        nsec, optsize = struct.unpack_from('<H', pe, peo + 6)[0], struct.unpack_from('<H', pe, peo + 20)[0]
        rva = None
        for i in range(nsec):
            _, vsize, va, rawsize, raw = struct.unpack_from('<8sIIII', pe, peo + 24 + optsize + 40 * i)
            if raw <= m.start() < raw + rawsize:
                rva = m.start() - raw + va
        h = self._open()
        try:
            addr, old = self._module_base(h, 'objectcore.dll') + rva, w.DWORD()
            k32.VirtualProtectEx(h, ctypes.c_void_p(addr), 4, 0x40, ctypes.byref(old))
            self._write(h, addr, b'\x6a' + struct.pack('<b', int(ns)) + b'\x58\x90')
            k32.VirtualProtectEx(h, ctypes.c_void_p(addr), 4, old, ctypes.byref(old))
        finally:
            k32.CloseHandle(h)

    def cmd(self, line, timeout=30.0, delay=0.04):
        """Sends a command and returns its output: everything printed until the CLI shows its prompt again."""
        self.poll_output()
        start = len(self._text)
        self.send(line, delay)
        t = time.time()
        while time.time() - t < timeout:
            time.sleep(0.3)
            self.poll_output()
            out = self._text[start:]
            nl = out.find('\n')               # skip the echoed command line itself
            if nl >= 0 and '\n>' in out[nl:]:   # the next prompt starts a line
                return out
            if self.proc.poll() is not None:
                raise RuntimeError('console.exe exited (%s)' % self.proc.returncode)
        return self._text[start:]

    def wait_for(self, pattern, timeout=60.0):
        """Waits until 'pattern' (regex) appears in output printed from now on; returns the match or None."""
        import re
        self.poll_output()
        start = len(self._text)
        t = time.time()
        while time.time() - t < timeout:
            m = re.search(pattern, self._text[start:])
            if m:
                return m
            if self.proc.poll() is not None:
                raise RuntimeError('console.exe exited (%s)' % self.proc.returncode)
            time.sleep(0.5)
            self.poll_output()
        return None

    def close(self):
        if self.proc.poll() is None:
            try:
                self.send('quit')
                self.proc.wait(15)
            except Exception:
                self.proc.kill()
        self._out.close()
