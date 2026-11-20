"""Runs the game's own command line (CLI) inside an already running game process, from outside, without a console.

The graphical game (makehist.exe) carries the same CLI as bin/console.exe (cli.dll), but no console to type into.
We put a small stub in the game's memory and hook it into the game's main loop (an import slot the main loop calls
every frame), so everything runs on the game's own thread:
  - a mailbox: Python writes a command line there; the stub feeds it to the CLI with CCli::cliProcessChar (any
    character, line breaks and accents included) and runs it with CCli::RxChar('\\r');
  - the CLI's output: a fake CLogger callback registered with CLogger::RegisterPrintfCallback copies every printed
    string into a ring buffer that Python reads.
Like mh_console.enable_dev_mode, 'action' needs CObjectManager::ms_eSystemMode == 1: the stub sets it only while
our own command runs and puts the old value back. No game file is touched; detach() restores the hooked slot (the
stub's memory stays, since the logger keeps a pointer to the callback; attaching again reuses it).

Same interface as mh_console.Console for the parts ai_player.Bot uses: cmd(line, timeout) -> output text.
"""
import ctypes
import ctypes.wintypes as w
import os
import struct
import time

from mh_console import JMP, JNE, JZ, assemble, export_rva, import_slot, vtable_slot

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.OpenProcess.restype = w.HANDLE
k32.VirtualAllocEx.restype = ctypes.c_void_p
psapi = ctypes.WinDLL('psapi', use_last_error=True)

RING = 0x40000                      # output ring buffer, in UTF-16 units (power of two; turns log a lot)
LOG_MAX = 5 * 1024 * 1024             # a log file over this starts again (disk space)
# block layout (offsets from the allocation)
F_GETINST, F_PROCCHAR, F_RXCHAR, F_REGISTER, F_ORIG, P_SYSMODE = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14
CMD_STATE, CB_STATE, OUT_POS, SAVED_MODE, SCRATCH = 0x18, 0x1C, 0x20, 0x24, 0x28
CB_OBJ, CB_VTBL = 0x30, 0x38
F_REGLOG, P_FILTER, SAVED_FILTER = 0x50, 0x54, 0x58
NEWLINE = ''                  # stands for a line break while the line is typed (cliProcessChar drops '\n')
CMD_BUF, CMD_MAX = 0x100, 0x7FF
HOOK, WRITE, RET4 = 0x1100, 0x1300, 0x1400
OUT_BUF = 0x2000
SIZE = OUT_BUF + 2 * RING
MAGIC = b'MHGameCLI3'               # at 0x80: lets a later attach recognise our block


def find_pid(exe='makehist.exe'):
    """(process id, bin folder) of the running game, or (None, None)."""
    pids, need = (w.DWORD * 4096)(), w.DWORD()
    psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(need))
    name = ctypes.create_unicode_buffer(260)
    for pid in pids[:need.value // 4]:
        h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            n = w.DWORD(260)
            ok = k32.QueryFullProcessImageNameW(w.HANDLE(h), 0, name, ctypes.byref(n))
            k32.CloseHandle(w.HANDLE(h))
            if ok and os.path.basename(name.value).lower() == exe:
                return pid, os.path.dirname(name.value)
    return None, None


def hook_code(D):
    """Machine code of the per-frame stub and of the logger callback, for a block at address D."""
    A = lambda off: struct.pack('<I', D + off)
    hook = assemble([
        b'\x60\x9c',                                         # pushad ; pushfd
        b'\x83\x3d' + A(CB_STATE) + b'\x01', (JNE, 'cmd'),   # cmp [cb_state], 1 ; jne cmd
        b'\x68' + A(CB_OBJ),                                 # push &callback
        b'\xff\x15' + A(F_REGISTER), b'\x83\xc4\x04',        # call [RegisterPrintfCallback] ; add esp, 4
        b'\x6a\x09', b'\x6a\x23', b'\x68' + A(CB_OBJ),       # push 9 (max level) ; push 23h (all types) ; push &cb
        b'\xff\x15' + A(F_REGLOG), b'\x83\xc4\x0c',          # call [RegisterLogCallback] ; add esp, 0Ch
        b'\xc7\x05' + A(CB_STATE) + b'\x02\x00\x00\x00',     # mov [cb_state], 2
        ('label', 'cmd'),
        b'\x83\x3d' + A(CMD_STATE) + b'\x01', (JZ, 'body'),   # cmp [cmd_state], 1 ; je body
        ('near', 'done'),                                    # jmp done
        ('label', 'body'),
        b'\xa1' + A(P_SYSMODE),                              # mov eax, [&ms_eSystemMode]
        b'\x8b\x08', b'\x89\x0d' + A(SAVED_MODE),            # mov ecx, [eax] ; mov [saved], ecx
        b'\xc7\x00\x01\x00\x00\x00',                         # mov dword [eax], 1     (dev mode on)
        b'\xa1' + A(P_FILTER),                               # mov eax, [&ms_nFilterLevel]
        b'\x8b\x08', b'\x89\x0d' + A(SAVED_FILTER),          # mov ecx, [eax] ; mov [saved filter], ecx
        b'\xc7\x00\x09\x00\x00\x00',                         # mov dword [eax], 9     (CLI answers get logged)
        b'\xff\x15' + A(F_GETINST),                          # call [CCli::GetInstance]
        b'\x85\xc0', (JZ, 'finish'),                         # test eax, eax ; jz finish
        b'\x8b\xd8',                                         # mov ebx, eax           (the CLI)
        b'\xbe' + A(CMD_BUF),                                # mov esi, cmd buffer
        ('label', 'next'),
        b'\x0f\xb7\x06', b'\x85\xc0', (JZ, 'enter'),         # movzx eax, word [esi] ; test ; jz enter
        b'\x68' + A(SCRATCH), b'\x50', b'\x8b\xcb',          # push &scratch ; push eax ; mov ecx, ebx
        b'\xff\x15' + A(F_PROCCHAR),                         # call [cliProcessChar]  (thiscall, ret 8)
        b'\x46\x46', (JMP, 'next'),                          # inc esi x2 ; jmp next
        ('label', 'enter'),
        b'\x8d\x7b\x24', b'\x8b\x8b\x24\x10\x00\x00',        # lea edi, [ebx+24h] (line) ; mov ecx, [ebx+1024h] (length)
        ('label', 'scan'),
        b'\x85\xc9', (JZ, 'run'),                            # test ecx, ecx ; jz run
        b'\x66\x81\x3f\x00\xe0', (JNE, 'skip'),              # cmp word [edi], 0E000h ; jne skip
        b'\x66\xc7\x07\x0a\x00',                             # mov word [edi], 0Ah    (the real line break)
        ('label', 'skip'),
        b'\x47\x47\x49', (JMP, 'scan'),                      # inc edi x2 ; dec ecx ; jmp scan
        ('label', 'run'),
        b'\x6a\x0d', b'\x8b\xcb', b'\xff\x15' + A(F_RXCHAR),  # push 0Dh ; mov ecx, ebx ; call [RxChar]
        ('label', 'finish'),
        b'\xa1' + A(P_SYSMODE),                              # mov eax, [&ms_eSystemMode]
        b'\x8b\x0d' + A(SAVED_MODE), b'\x89\x08',            # mov ecx, [saved] ; mov [eax], ecx
        b'\xa1' + A(P_FILTER),                               # mov eax, [&ms_nFilterLevel]
        b'\x8b\x0d' + A(SAVED_FILTER), b'\x89\x08',          # mov ecx, [saved filter] ; mov [eax], ecx
        b'\xc7\x05' + A(CMD_STATE) + b'\x02\x00\x00\x00',    # mov [cmd_state], 2
        ('label', 'done'),
        b'\x9d\x61',                                         # popfd ; popad
        b'\xff\x25' + A(F_ORIG)])                            # jmp [original]
    write = assemble([
        b'\x56\x57',                                         # push esi ; push edi
        b'\x8b\x74\x24\x0c',                                 # mov esi, [esp+0Ch]     (the string)
        b'\x8b\x3d' + A(OUT_POS),                            # mov edi, [out_pos]
        b'\x85\xf6', (JZ, 'end'),                            # test esi, esi ; jz end
        ('label', 'next'),
        b'\x0f\xb7\x06', b'\x85\xc0', (JZ, 'end'),           # movzx eax, word [esi] ; test ; jz end
        b'\x8b\xd7', b'\x81\xe2' + struct.pack('<I', RING - 1),   # mov edx, edi ; and edx, RING-1
        b'\x66\x89\x84\x12' + A(OUT_BUF),                    # mov [OUT_BUF + edx*2], ax
        b'\x47\x46\x46', (JMP, 'next'),                      # inc edi ; inc esi x2 ; jmp next
        ('label', 'end'),
        b'\x89\x3d' + A(OUT_POS),                            # mov [out_pos], edi
        b'\x5f\x5e', b'\xc2\x04\x00'])                       # pop edi ; pop esi ; ret 4
    return hook, write


class GameCLI:
    def __init__(self, pid, bin_dir, hook=None, log_path=None):
        """pid: the game process; bin_dir: its bin folder (to read the DLLs' exports);
        hook: a slot the game's main loop calls through every frame: (module, imported dll, function name prefix)
        for an import, or ('vtable', dll, class, method). Default: program.dll's import of
        CUserInterface::KeepRunning, which CWindowsProgram::KeepRunning jumps through on every pass of WinMain's
        loop (WinMain itself keeps its own imports in registers, so patching makehist.exe's would not be seen).
        A game in the background with exclusive fullscreen runs no frames: commands wait until it is back."""
        self.pid, self.bin = pid, bin_dir
        self.hook = hook or ('program.dll', 'ui.dll', b'?KeepRunning@CUserInterface@')
        h = k32.OpenProcess(0x043A, False, pid)       # VM_OPERATION|VM_READ|VM_WRITE|CREATE_THREAD|QUERY_INFO
        if not h:
            raise OSError('OpenProcess failed (%d)' % ctypes.get_last_error())
        self.h = w.HANDLE(h)
        self._out = open(log_path, 'a', encoding='utf-8', errors='replace') if log_path else None
        self._attach()

    # --- memory helpers ----------------------------------------------------------------------------------
    def _base(self, dll):
        mods, need = (ctypes.c_void_p * 1024)(), w.DWORD()
        psapi.EnumProcessModulesEx(self.h, mods, ctypes.sizeof(mods), ctypes.byref(need), 0x01)
        name = ctypes.create_unicode_buffer(260)
        for m in mods[:need.value // ctypes.sizeof(ctypes.c_void_p)]:
            psapi.GetModuleBaseNameW(self.h, ctypes.c_void_p(m), name, 260)
            if name.value.lower() == dll:
                return m
        raise OSError('%s not loaded in the game' % dll)

    def _write(self, addr, data):
        n = ctypes.c_size_t()
        if not k32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(n)):
            raise OSError('WriteProcessMemory failed (%d)' % ctypes.get_last_error())

    def _read(self, addr, size):
        buf, n = ctypes.create_string_buffer(size), ctypes.c_size_t()
        if not k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n)):
            raise OSError('ReadProcessMemory failed (%d)' % ctypes.get_last_error())
        return buf.raw[:n.value]

    def _u32(self, addr):
        return struct.unpack('<I', self._read(addr, 4))[0]

    def _set_slot(self, slot, value):
        old = w.DWORD()
        k32.VirtualProtectEx(self.h, ctypes.c_void_p(slot), 4, 0x04, ctypes.byref(old))
        self._write(slot, struct.pack('<I', value))
        k32.VirtualProtectEx(self.h, ctypes.c_void_p(slot), 4, old, ctypes.byref(old))

    # --- installing the stub -----------------------------------------------------------------------------
    def _attach(self):
        if self.hook[0] == 'vtable':
            _, dll, cls, method = self.hook
            vt, i = vtable_slot(os.path.join(self.bin, dll), cls, method)
            self.slot = self._base(dll) + vt + 4 * i
        else:
            mod, dll, name = self.hook
            self.slot = self._base(mod) + import_slot(os.path.join(self.bin, mod), dll, name)
        cur = self._u32(self.slot)
        try:
            if self._read(cur - HOOK + 0x80, len(MAGIC)) == MAGIC:      # attached earlier: reuse that block
                self.D = cur - HOOK
                self._pos = self._u32(self.D + OUT_POS)
                return
        except OSError:
            pass
        j = os.path.join
        cli, lg = j(self.bin, 'cli.dll'), j(self.bin, 'logger.dll')
        cb, lb, ob = self._base('cli.dll'), self._base('logger.dll'), self._base('objectcore.dll')
        D = self.D = k32.VirtualAllocEx(self.h, None, SIZE, 0x3000, 0x40)    # MEM_COMMIT|RESERVE, RWX
        if not D:
            raise OSError('VirtualAllocEx failed (%d)' % ctypes.get_last_error())
        self._write(D, struct.pack('<6I', cb + export_rva(cli, b'?GetInstance@CCli@'),
                                   cb + export_rva(cli, b'?cliProcessChar@CCli@'),
                                   cb + export_rva(cli, b'?RxChar@CCli@'),
                                   lb + export_rva(lg, b'?RegisterPrintfCallback@CLogger@'),
                                   cur, ob + export_rva(j(self.bin, 'objectcore.dll'), b'?ms_eSystemMode@CObjectManager@')))
        self._write(D + F_REGLOG, struct.pack('<2I', lb + export_rva(lg, b'?RegisterLogCallback@CLogger@'),
                                              lb + export_rva(lg, b'?ms_nFilterLevel@CLogger@')))
        self._write(D + 0x80, MAGIC)
        # fake CLoggerCallback: vtable with our WriteString in its slot, a harmless 'ret 4' in the others
        _, ws = vtable_slot(lg, b'CLoggerCallback@CLogger', b'WriteString')
        vt = [D + RET4] * 4
        vt[ws] = D + WRITE
        self._write(D + CB_OBJ, struct.pack('<I', D + CB_VTBL))
        self._write(D + CB_VTBL, struct.pack('<4I', *vt))
        hook, write = hook_code(D)
        self._write(D + HOOK, hook)
        self._write(D + WRITE, write)
        self._write(D + RET4, b'\xc2\x04\x00')
        self._write(D + CB_STATE, struct.pack('<I', 1))             # register the callback on the first frame
        self._pos = 0
        self._set_slot(self.slot, D + HOOK)       # runs from the next frame (a game in the background has none)

    # --- using it ---------------------------------------------------------------------------------------
    def poll_output(self):
        """Text printed by the game since the last call (CLI answers and log lines)."""
        end = self._u32(self.D + OUT_POS)
        n = min((end - self._pos) & 0xFFFFFFFF, RING - 1)     # older text was overwritten
        if not n:
            return ''
        raw = self._read(self.D + OUT_BUF, 2 * RING)
        s = (end - n) & (RING - 1)
        text = (raw[2 * s:] + raw[:2 * s])[:2 * n].decode('utf-16-le', 'replace')   # ring rotated to 'start'
        self._pos = end
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        if self._out:
            if self._out.tell() > LOG_MAX:      # keep the disk in check: start the file again (newest output only)
                self._out.seek(0)
                self._out.truncate()
            self._out.write(text)
            self._out.flush()
        return text

    def cmd(self, line, timeout=30.0, delay=None):
        """Runs one command line in the game (on its own thread, at the next frame) and returns what it printed,
        shaped like mh_console.Console.cmd (echoed command, output, prompt). 'timeout' is ignored: a game with
        no frames (in the background, in exclusive fullscreen) is waited for; a closed game raises OSError."""
        line = line.replace('\t', ' ').replace('\r\n', '\n').replace('\n', NEWLINE)[:CMD_MAX]
        while self._u32(self.D + CMD_STATE) == 1:           # a previous command still waits for its frame
            time.sleep(0.02)
        self.poll_output()
        self._write(self.D + CMD_BUF, (line + '\0').encode('utf-16-le'))
        self._write(self.D + CMD_STATE, struct.pack('<I', 1))
        while self._u32(self.D + CMD_STATE) != 2:
            time.sleep(0.02)
        time.sleep(0.05)
        return line.replace(NEWLINE, '\n') + '\n' + self.poll_output() + '\n>'

    def detach(self):
        """Lets go of the game process but leaves the hook in place: the stub only reads our mailbox each frame,
        and the next attach (a restart, a reconnect) finds and reuses this block through the slot (MAGIC).
        Restoring the slot every time made each later attach build a new block and register one more logger
        callback in the game (a crash at objectcore+0x40c6 followed such churn); unhook() does it, on a real exit
        only."""
        if getattr(self, '_closed', False):
            return
        self._closed = True
        if self._out:
            self._out.close()
        k32.CloseHandle(self.h)

    def unhook(self):
        """Gives the game back its original main-loop call (the stub memory stays: the logger keeps a pointer to
        our callback, and a frame may be running the stub right now), then lets go of the process."""
        try:
            self._set_slot(self.slot, self._u32(self.D + F_ORIG))
        finally:
            self.detach()

    close = detach


if __name__ == '__main__':
    hk, wr = hook_code(0x10000000)       # self-check of the assembler: both stubs end where they should
    assert hk.endswith(b'\x9d\x61\xff\x25' + struct.pack('<I', 0x10000000 + F_ORIG)) and wr.endswith(b'\xc2\x04\x00')
    print('assembled %d + %d bytes; game:' % (len(hk), len(wr)), find_pid())
