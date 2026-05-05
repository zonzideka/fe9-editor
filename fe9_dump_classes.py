#!/usr/bin/env python3
"""Dump all 115 JobData entries from FE8Data.bin with current caps."""
import struct, sys

DATA_BIN = 'FE8Data.bin'
JOBDATA_OFF = 0x6FC0
ENTRY_SIZE = 0x64
CAPS_OFF_IN_ENTRY = 0x4C
BASES_OFF_IN_ENTRY = 0x44
GROWTHS_OFF_IN_ENTRY = 0x54

# Per Universal-FE-Randomizer FE9Class.java: HP STR MAG SKL SPD LCK DEF RES
STAT_NAMES = ['HP', 'Str', 'Mag', 'Skl', 'Spd', 'Lck', 'Def', 'Res']

def cstr(data, off):
    end = data.index(b'\x00', off)
    return data[off:end].decode('shift_jis', errors='replace')

def main():
    data = open(DATA_BIN, 'rb').read()
    n = struct.unpack('>I', data[JOBDATA_OFF:JOBDATA_OFF+4])[0]
    print(f'JobData @ 0x{JOBDATA_OFF:X}, count = {n}')
    print()
    print(f'{"idx":>3} {"abs_off":>8} {"JID":<32} {"PromoTo":<28} {"caps (HP S M Sk Sp L D R)":<32}')
    print('-' * 110)
    for i in range(n):
        eo = JOBDATA_OFF + 4 + i * ENTRY_SIZE
        jid_ptr = struct.unpack('>I', data[eo:eo+4])[0]
        promo_ptr = struct.unpack('>I', data[eo+0x0C:eo+0x10])[0]
        jid = cstr(data, jid_ptr + 0x20) if jid_ptr else '(null)'
        promo = cstr(data, promo_ptr + 0x20) if promo_ptr else '-'
        caps = list(data[eo+CAPS_OFF_IN_ENTRY:eo+CAPS_OFF_IN_ENTRY+8])
        bases = list(data[eo+BASES_OFF_IN_ENTRY:eo+BASES_OFF_IN_ENTRY+8])
        growths = list(data[eo+GROWTHS_OFF_IN_ENTRY:eo+GROWTHS_OFF_IN_ENTRY+8])
        cap_str = ' '.join(f'{c:>2}' for c in caps)
        print(f'{i:>3} 0x{eo:06X} {jid:<32} {promo:<28} {cap_str}')

if __name__ == '__main__':
    main()
