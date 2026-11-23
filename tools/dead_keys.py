"""Lets the running game take accented letters (á é í ó ú ü à â ã ñ..., typed with dead keys ´ ` ^ ¨ ~).

Bug (input.dll, same code in MH1 and Gold): every frame, for each key whose DirectInput state changed (pressed
AND released), the game calls ToUnicodeEx and then does
    n = ToUnicodeEx(...); buf = new WCHAR[n + 1]; copy n chars; buf[n] = 0;
  - A dead key (´ on a Spanish keyboard) makes ToUnicodeEx return -1, so it allocates 0 bytes and writes the 0
    two bytes BEFORE the block: heap corruption, and the game crashes a bit later in some unrelated place (seen in
    NiMain12VC71.dll NiAVObject::CullShow).
  - The key release is translated too, as a second press (the scan code has no 'key up' bit).
  - The window's message loop (TranslateMessage) translates the same keystrokes and shares the thread's pending
    dead key with ToUnicodeEx, so the accent is used up twice: ´ then a gives '´a' instead of 'á'.

Fix, in the game's memory only (no game file is touched; it lasts until the game closes): the call at
CALL_SITE goes to a stub that
  - returns 0 characters for released keys;
  - calls ToUnicodeEx with flag 4 (do not change the keyboard state), so it never disturbs Windows' own state;
  - when MapVirtualKeyEx says the key is a dead key, remembers its accent (the spacing character ToUnicodeEx put in
    the buffer) and returns 0 characters;
  - for the next key that gives a character, composes accent + letter from COMPOSE (´ + a -> á), returns the
    letter as is if it is already composed, or else returns both characters, as Windows does.
"""
import ctypes
import ctypes.wintypes as w
import struct
import sys
import unicodedata

from game_cli import find_pid, k32
from mh_console import JMP, JNE, JZ, assemble

JS, JLE = 0x78, 0x7E
PREF_BASE = 0x10000000
CALL_SITE = 0x10009DFA      # call dword ptr [ToUnicodeEx]  (FF 15 imm32); the caller's loop keeps the VK in ebx
KEY_READ = 0x10009D7A       # mov dl, byte ptr [ebx + keys]  (8A 93 imm32): new pressed state, bit 7
IAT_TOUNICODE = 0x1000D100
IAT_MAPVK = 0x1000D0FC      # MapVirtualKeyExW
# layout of our block
TABLE, PENDING, MARK = 0x400, 0x800, 0x810
MAGIC = b'MHDeadKeys2'

ACCENTS = {'´': '́', '`': '̀', '^': '̂', '¨': '̈', '~': '̃'}
# (accent, result, letter); accent + space gives the accent alone
COMPOSE = [(a, a if b == ' ' else unicodedata.normalize('NFC', b + c), b)
           for a, c in ACCENTS.items() for b in ' aeiouyAEIOUYnN'
           if b == ' ' or len(unicodedata.normalize('NFC', b + c)) == 1]
assert ('´', 'á', 'a') in COMPOSE and ('~', 'ñ', 'n') in COMPOSE and ('´', '´', ' ') in COMPOSE


def stub_code(D, keys, iat_tu, iat_mvk):
    """stdcall ToUnicodeEx(vk, scan, keystate, buf, cch, flags, hkl) replacement at D; ebx = VK in the caller.
    Arguments relative to ebp: vk 8, scan 0Ch, keystate 10h, buf 14h, cch 18h, flags 1Ch, hkl 20h."""
    I = lambda v: struct.pack('<I', v)
    P = D + PENDING
    return assemble([
        b'\xf6\x83' + I(keys) + b'\x80', (JNE, 'pressed'),          # test byte [ebx+keys], 80h
        b'\x33\xc0\xc2\x1c\x00',                                      # released: xor eax, eax; ret 1Ch
        ('label', 'pressed'),
        b'\x55\x8b\xec\x56\x57',                                      # push ebp; mov ebp,esp; push esi; push edi
        b'\xff\x75\x20',                                              # push hkl
        b'\x8b\x45\x1c\x83\xc8\x04\x50',                              # push flags | 4  (keep the keyboard state)
        b'\xff\x75\x18\xff\x75\x14\xff\x75\x10\xff\x75\x0c\xff\x75\x08',  # push cch, buf, keystate, scan, vk
        b'\xff\x15' + I(iat_tu),                                      # call [ToUnicodeEx]
        b'\x8b\xf0',                                                  # mov esi, eax        (n)
        b'\xff\x75\x20\x6a\x02\xff\x75\x08',                          # MapVirtualKeyExW(vk, MAPVK_VK_TO_CHAR, hkl)
        b'\xff\x15' + I(iat_mvk),
        b'\x8b\x7d\x14',                                              # mov edi, buf
        b'\x85\xc0', (JS, 'dead'),                                    # bit 31: dead key
        b'\x85\xf6', (JLE, 'zero'),                                   # no character (shift, ctrl...)
        b'\x0f\xb7\x44\x77\xfe',                                      # movzx eax, word [edi+esi*2-2]  (letter)
        b'\x0f\xb7\x0d' + I(P),                                       # movzx ecx, word [pending]
        b'\x85\xc9', (JZ, 'asis'),
        b'\x66\xc7\x05' + I(P) + b'\x00\x00',                         # pending = 0
        b'\xba' + I(D + TABLE),                                       # mov edx, COMPOSE table
        ('label', 'loop'),
        b'\x66\x83\x3a\x00', (JZ, 'nocomp'),                          # cmp word [edx], 0   (end)
        b'\x66\x3b\x0a', (JNE, 'next'),                               # cmp cx, [edx]       (accent)
        b'\x66\x3b\x42\x02', (JZ, 'one'),                             # cmp ax, [edx+2]     (already composed)
        b'\x66\x3b\x42\x04', (JNE, 'next'),                           # cmp ax, [edx+4]     (letter)
        b'\x66\x8b\x42\x02',                                          # mov ax, [edx+2]
        ('label', 'one'),
        b'\x66\x89\x07',                                              # mov [edi], ax
        b'\xb8\x01\x00\x00\x00', (JMP, 'done'),
        ('label', 'next'),
        b'\x83\xc2\x06', (JMP, 'loop'),
        ('label', 'nocomp'),
        b'\x66\x89\x0f\x66\x89\x47\x02',                              # buf = accent, letter
        b'\xb8\x02\x00\x00\x00', (JMP, 'done'),
        ('label', 'asis'),
        b'\x8b\xc6', (JMP, 'done'),                                   # mov eax, esi
        ('label', 'dead'),
        b'\x66\x8b\x07\x66\xa3' + I(P),                               # pending = buf[0]  (spacing accent)
        ('label', 'zero'),
        b'\x33\xc0',
        ('label', 'done'),
        b'\x5f\x5e\x5d\xc2\x1c\x00',                                  # pop edi; pop esi; pop ebp; ret 1Ch
    ])


def table_bytes():
    return b''.join(struct.pack('<3H', ord(a), ord(r), ord(b)) for a, r, b in COMPOSE) + b'\0' * 6


assert len(stub_code(0x500000, 1, 2, 3)) < TABLE and len(table_bytes()) < PENDING - TABLE


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
    """Patches the game process 'pid'. Returns 'patched', 'updated' (an older version of this patch was there) or
    'already patched'; raises if the code is unknown."""
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
        result = 'patched'
        if cur[0] == 0xE8:
            target = site + 5 + struct.unpack('<i', cur[1:5])[0]
            if read(target + MARK, len(MAGIC)) == MAGIC:
                return 'already patched'
            result = 'updated'
        elif cur != b'\xff\x15' + struct.pack('<I', IAT_TOUNICODE + rel):
            raise OSError('unknown input.dll build: %s at the call site' % cur.hex())
        key_read = read(KEY_READ + rel, 6)
        if key_read[:2] != b'\x8a\x93':
            raise OSError('unknown input.dll build: %s at the key read' % key_read.hex())
        keys = struct.unpack('<I', key_read[2:])[0]
        D = k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)     # MEM_COMMIT|RESERVE, RWX
        if not D:
            raise OSError('VirtualAllocEx failed (%d)' % ctypes.get_last_error())
        write(D, stub_code(D, keys, IAT_TOUNICODE + rel, IAT_MAPVK + rel))
        write(D + TABLE, table_bytes())
        write(D + MARK, MAGIC)
        old = w.DWORD()
        k32.VirtualProtectEx(h, ctypes.c_void_p(site), 6, 0x40, ctypes.byref(old))
        write(site, b'\xe8' + struct.pack('<i', D - (site + 5)) + b'\x90')   # call stub ; nop
        k32.VirtualProtectEx(h, ctypes.c_void_p(site), 6, old, ctypes.byref(old))
        k32.FlushInstructionCache(h, ctypes.c_void_p(site), 6)
        return result
    finally:
        k32.CloseHandle(h)


if __name__ == '__main__':
    pid, _ = find_pid()
    if not pid:
        sys.exit('makehist.exe is not running')
    print(apply(pid))
