"""Lets the running game take accented letters (á é í ó ú ü, typed with the dead key ´ or ¨) without crashing.

Bug (input.dll, same code in MH1 and Gold): every frame, for each key whose DirectInput state changed (pressed
AND released), the game calls ToUnicodeEx and then does
    n = ToUnicodeEx(...); buf = new WCHAR[n + 1]; copy n chars; buf[n] = 0;
  - A dead key (´ on a Spanish keyboard) makes ToUnicodeEx return -1, so it allocates 0 bytes and writes the 0
    two bytes BEFORE the block: heap corruption, and the game crashes a bit later in some unrelated place (seen in
    NiMain12VC71.dll NiAVObject::CullShow).
  - The key release is translated too, as a second press (the scan code has no 'key up' bit). Releasing ´ sends
    it again, which ends the pending accent, so the next 'a' comes out as a plain 'a'.

Fix, in the game's memory only (no game file is touched; it lasts until the game closes): the call at
CALL_SITE goes to a small stub instead, which skips released keys (returns 0 characters) and turns -1 into 0.
"""
import ctypes
import ctypes.wintypes as w
import struct
import sys

from game_cli import find_pid, k32

PREF_BASE = 0x10000000
CALL_SITE = 0x10009DFA      # call dword ptr [ToUnicodeEx]  (FF 15 imm32); the caller's loop keeps the VK in ebx
KEY_READ = 0x10009D7A       # mov dl, byte ptr [ebx + keys]  (8A 93 imm32): new pressed state, bit 7
IAT_TOUNICODE = 0x1000D100
RELEASED = b'\x31\xc0\xc2\x1c\x00'                             # xor eax,eax ; ret 1Ch


def stub_code(keys, iat):
    """stdcall ToUnicodeEx replacement (7 arguments); ebx = virtual key in the caller."""
    return (b'\xf6\x83' + struct.pack('<I', keys) + b'\x80' +      # test byte [ebx+keys], 80h
            b'\x74\x2b' +                                          # jz released
            b'\xff\x74\x24\x1c' * 7 +                              # push the 7 arguments again
            b'\xff\x15' + struct.pack('<I', iat) +                 # call [ToUnicodeEx]
            b'\x85\xc0' + b'\x7d\x02' + b'\x31\xc0' +              # test eax,eax ; jge ok ; xor eax,eax
            b'\xc2\x1c\x00' +                                      # ok: ret 1Ch
            RELEASED)


_s = stub_code(0x11111111, 0x22222222)
assert _s[9 + _s[8]:] == RELEASED, 'jz released offset'


def _base(h, dll):
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    mods, need = (ctypes.c_void_p * 1024)(), w.DWORD()
    psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 0x01)
    name = ctypes.create_unicode_buffer(260)
    for m in mods[:need.value // ctypes.sizeof(ctypes.c_void_p)]:
        psapi.GetModuleBaseNameW(h, ctypes.c_void_p(m), name, 260)
        if name.value.lower() == dll:
            return m
    raise OSError('%s not loaded in the game' % dll)


def apply(pid):
    """Patches the game process 'pid'. Returns 'patched' or 'already patched'; raises if the code is unknown."""
    h = k32.OpenProcess(0x0438, False, pid)            # VM_OPERATION|VM_READ|VM_WRITE|QUERY_INFORMATION
    if not h:
        raise OSError('OpenProcess failed (%d)' % ctypes.get_last_error())
    h = w.HANDLE(h)

    def read(a, n):
        buf, got = ctypes.create_string_buffer(n), ctypes.c_size_t()
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(a), buf, n, ctypes.byref(got)):
            raise OSError('ReadProcessMemory failed (%d)' % ctypes.get_last_error())
        return buf.raw

    def write(a, data):
        got = ctypes.c_size_t()
        if not k32.WriteProcessMemory(h, ctypes.c_void_p(a), data, len(data), ctypes.byref(got)):
            raise OSError('WriteProcessMemory failed (%d)' % ctypes.get_last_error())

    try:
        rel = _base(h, 'input.dll') - PREF_BASE
        site, cur = CALL_SITE + rel, read(CALL_SITE + rel, 6)
        if cur[0] == 0xE8:
            return 'already patched'
        if cur != b'\xff\x15' + struct.pack('<I', IAT_TOUNICODE + rel):
            raise OSError('unknown input.dll build: %s at the call site' % cur.hex())
        key_read = read(KEY_READ + rel, 6)
        if key_read[:2] != b'\x8a\x93':
            raise OSError('unknown input.dll build: %s at the key read' % key_read.hex())
        keys = struct.unpack('<I', key_read[2:])[0]
        stub = k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)     # MEM_COMMIT|RESERVE, RWX
        if not stub:
            raise OSError('VirtualAllocEx failed (%d)' % ctypes.get_last_error())
        write(stub, stub_code(keys, IAT_TOUNICODE + rel))
        old = w.DWORD()
        k32.VirtualProtectEx(h, ctypes.c_void_p(site), 6, 0x40, ctypes.byref(old))
        write(site, b'\xe8' + struct.pack('<i', stub - (site + 5)) + b'\x90')   # call stub ; nop
        k32.VirtualProtectEx(h, ctypes.c_void_p(site), 6, old, ctypes.byref(old))
        k32.FlushInstructionCache(h, ctypes.c_void_p(site), 6)
        return 'patched'
    finally:
        k32.CloseHandle(h)


if __name__ == '__main__':
    pid, _ = find_pid()
    if not pid:
        sys.exit('makehist.exe is not running')
    print(apply(pid))
