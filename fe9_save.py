#!/usr/bin/env python3
"""FE9 (Path of Radiance) GameCube save file (.gci) reader / writer.

GCI file layout:
  0x00 - 0x3F: 64-byte GCI header (game code, banner offset, block count, etc.)
  0x40 - end:  raw save data (multiple of 8KB)

FE9 save data layout (per observation of one user's save):
  0x0000 - 0x1FFF: memory card directory / system data
  0x2000 + N*0x4000: 8 save slots, each 16KB (0x4000 bytes)

Each save slot internal layout (offsets from slot start):
  +0x0000 - 0x007F: SJIS banner text "ファイアーエムブレム蒼炎の軌跡 YYYY/MM/DD HH:MM [N周目]"
  +0x0070: SYSF magic (system flags)
  +0x00B8: BMST magic (battle map status)
  +0x02D0: MDST magic (map data?)
  +0x02F4: UNIP magic (unit info pool — character data)
  +0x04C3: SOKO magic (warehouse/storage)
  +0x07E7: FWEP magic (weapon/item inventory)
"""
import struct, os, hashlib

# GCI header offset constants
GCI_HEADER_SIZE = 0x40
GCI_GAMECODE   = 0x00   # 4 bytes
GCI_FILENAME   = 0x08   # 32 bytes

# FE9 save constants (offsets relative to save data start = file +0x40)
SLOT_SIZE      = 0x4000
SLOT_BASE      = 0x2000   # first slot starts here
NUM_SLOTS      = 8

# Sub-block magic offsets within each slot (verified across all slots)
SLOT_BANNER    = 0x0000   # 0x80 bytes SJIS banner
SLOT_SYSF      = 0x0070
SLOT_BMST      = 0x00B8
SLOT_MDST      = 0x02D0
SLOT_UNIP      = 0x02F4
SLOT_SOKO      = 0x04C3
SLOT_FWEP      = 0x07E7

MAGICS = [
    ('SYSF', SLOT_SYSF), ('BMST', SLOT_BMST), ('MDST', SLOT_MDST),
    ('UNIP', SLOT_UNIP), ('SOKO', SLOT_SOKO), ('FWEP', SLOT_FWEP),
]


class FE9Save:
    def __init__(self, gci_path):
        self.gci_path = gci_path
        with open(gci_path, 'rb') as f:
            self.raw = bytearray(f.read())
        self._parse_header()

    def _parse_header(self):
        h = self.raw[:GCI_HEADER_SIZE]
        self.game_code = bytes(h[GCI_GAMECODE:GCI_GAMECODE+4])
        # Filename is 32 bytes null-terminated
        fn = bytes(h[GCI_FILENAME:GCI_FILENAME+32])
        self.filename = fn.split(b'\x00', 1)[0].decode('ascii', errors='replace')
        self.save_data_offset = GCI_HEADER_SIZE
        self.save_data = self.raw[GCI_HEADER_SIZE:]

    def get_slot(self, slot_idx):
        """Return SaveSlot for slot 0..7, or None if slot is empty."""
        if not (0 <= slot_idx < NUM_SLOTS):
            raise ValueError(f'slot_idx must be 0..{NUM_SLOTS-1}')
        slot_off = SLOT_BASE + slot_idx * SLOT_SIZE
        if slot_off + SLOT_SIZE > len(self.save_data):
            return None
        # Verify magic exists
        magic_pos = slot_off + SLOT_SYSF
        if self.save_data[magic_pos:magic_pos+4] != b'SYSF':
            return None
        return SaveSlot(self, slot_idx, slot_off)

    def list_slots(self):
        out = []
        for i in range(NUM_SLOTS):
            s = self.get_slot(i)
            if s:
                out.append(s)
        return out

    def save_back(self, path=None):
        if path is None: path = self.gci_path
        with open(path, 'wb') as f:
            f.write(self.raw)


class SaveSlot:
    def __init__(self, parent: FE9Save, idx: int, slot_off: int):
        self.parent = parent
        self.idx = idx
        self.slot_off = slot_off  # offset into parent.save_data

    def _read(self, rel_off, length):
        a = self.slot_off + rel_off
        return bytes(self.parent.save_data[a:a+length])

    @property
    def banner_text(self):
        b = self._read(SLOT_BANNER, 0x80)
        try:
            end = b.index(b'\x00')
            return b[:end].decode('shift_jis', errors='replace')
        except (ValueError, UnicodeDecodeError):
            return '(decode error)'

    def block_offsets(self):
        """Verified (magic, abs_save_offset) for each sub-block."""
        out = {}
        for magic, rel in MAGICS:
            abs_off = self.slot_off + rel
            if self.parent.save_data[abs_off:abs_off+4] == magic.encode('ascii'):
                out[magic] = abs_off
        return out


def main():
    """CLI: dump save info."""
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
        '~/Library/Application Support/Dolphin/GC/JAP/Card A/01-GFEJ-FIREEMBLEM8J.gci')
    s = FE9Save(path)
    print(f'GCI file: {path}')
    print(f'  Game code: {s.game_code!r}')
    print(f'  Internal filename: {s.filename!r}')
    print(f'  Total size: {len(s.raw)} bytes')
    print(f'  Save data: {len(s.save_data)} bytes')
    print()
    slots = s.list_slots()
    print(f'Slots ({len(slots)}/{NUM_SLOTS}):')
    for slot in slots:
        print(f'  [{slot.idx}] @ save+0x{slot.slot_off:X}')
        print(f'      banner: {slot.banner_text!r}')
        blocks = slot.block_offsets()
        print(f'      sub-blocks: {list(blocks.keys())}')


if __name__ == '__main__':
    main()
