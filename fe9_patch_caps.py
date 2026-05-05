#!/usr/bin/env python3
"""FE9 promoted-class caps patcher.

Reads FE8Data.bin from inside the GCM, applies caps_config.derive_new_caps to
each JobData entry, and (with --apply) writes the modified FE8Data.bin back
in-place at its original GCM offset.

GCM size is unchanged because FE8Data.bin size is unchanged (only edits 8 bytes
per modified class entry).

Default mode is dry-run: prints diff table only.
"""
import sys, os, struct, hashlib, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fe9_tool import GCM
from caps_config import (
    PROMOTED_HUMAN, PROMOTED_LAGUZ, EXCEPTION_60, HP80_INDICES, SKIP_INDICES,
    derive_new_caps,
)

import sys as _sys
GCM_PATH = _sys.argv[1] if len(_sys.argv) > 1 and not _sys.argv[1].startswith('--') else None
BAK_PATH = (GCM_PATH + '.bak') if GCM_PATH else None
if not GCM_PATH:
    print('Usage: fe9_patch_caps.py <path/to/game.gcm> [--apply]')
    print('Default: dry-run; pass --apply to write to GCM in-place.')
    _sys.exit(1)
JOBDATA_OFF = 0x6FC0
ENTRY_SIZE = 0x64
CAPS_OFF = 0x4C
STAT_LABELS = ['HP', 'Str', 'Mag', 'Skl', 'Spd', 'Lck', 'Def', 'Res']

def cstr(data, off):
    end = data.index(b'\x00', off)
    return data[off:end].decode('shift_jis', errors='replace')

def load_fe8data():
    g = GCM(GCM_PATH)
    info = g.find_file('FE8Data.bin')
    if not info:
        raise RuntimeError('FE8Data.bin not found in GCM')
    idx, fst_pos, off, size = info
    with open(GCM_PATH, 'rb') as f:
        f.seek(off)
        data = f.read(size)
    return data, off, size

def main():
    apply_mode = '--apply' in sys.argv

    print(f'Reading GCM: {GCM_PATH}')
    data, gcm_off, gcm_size = load_fe8data()
    print(f'  FE8Data.bin: GCM offset 0x{gcm_off:X}, size {gcm_size}')

    n = struct.unpack('>I', data[JOBDATA_OFF:JOBDATA_OFF+4])[0]
    print(f'  JobData count: {n}')
    print()

    # Group entries
    groups = {
        'HP=80 (5 user-listed)': sorted([i for i in HP80_INDICES]),
        'Promoted human (other)': sorted([i for i in PROMOTED_HUMAN if i not in HP80_INDICES]),
        'Valkyrie/Queen exception': sorted(EXCEPTION_60.keys()),
        'Promoted Laguz (transformed)': sorted(PROMOTED_LAGUZ.keys()),
        'SKIP (bases / non-combat / Ashnard)': sorted(SKIP_INDICES),
    }

    new_data = bytearray(data)
    changes = 0

    for group_name, indices in groups.items():
        if not indices:
            continue
        print('=' * 96)
        print(f'  {group_name}  ({len(indices)} entries)')
        print('=' * 96)
        if 'SKIP' in group_name:
            jids = []
            for i in indices:
                eo = JOBDATA_OFF + 4 + i * ENTRY_SIZE
                jid_ptr = struct.unpack('>I', data[eo:eo+4])[0]
                jids.append(f'{i}:{cstr(data, jid_ptr+0x20)}')
            # print compact
            for i in range(0, len(jids), 4):
                print('  ' + '  '.join(f'{j:<22}' for j in jids[i:i+4]))
            print()
            continue
        print(f'{"idx":>3} {"JID":<28} {"BEFORE":<28} {"AFTER":<28} {"DELTA":<28}')
        for i in indices:
            eo = JOBDATA_OFF + 4 + i * ENTRY_SIZE
            jid_ptr = struct.unpack('>I', data[eo:eo+4])[0]
            jid = cstr(data, jid_ptr + 0x20)
            cur = tuple(data[eo+CAPS_OFF:eo+CAPS_OFF+8])
            new = derive_new_caps(i, cur)
            if new is None:
                continue
            before_s = ' '.join(f'{c:>2}' for c in cur)
            after_s = ' '.join(f'{c:>2}' for c in new)
            delta_s = ' '.join(('+' + str(n-c)) if n != c else ' .' for c, n in zip(cur, new))
            print(f'{i:>3} {jid:<28} {before_s} | {after_s} | {delta_s}')
            for j in range(8):
                new_data[eo+CAPS_OFF+j] = new[j]
            if list(cur) != list(new):
                changes += 1
        print()

    print('=' * 96)
    print(f'TOTAL: {changes} entries to modify')
    if data == bytes(new_data):
        print('  (no actual byte changes)')
    else:
        # Count differing bytes
        diff_bytes = sum(1 for a,b in zip(data, new_data) if a != b)
        print(f'  bytes differing: {diff_bytes}')
    print()

    if not apply_mode:
        print('DRY-RUN. Use --apply to write to GCM.')
        return 0

    # Verify backup matches current GCM (safety)
    print('Safety checks before write:')
    print(f'  Backup exists: {os.path.exists(BAK_PATH)}')
    if os.path.exists(BAK_PATH):
        with open(BAK_PATH, 'rb') as f: bak_hash = hashlib.sha256(f.read()).hexdigest()
        with open(GCM_PATH, 'rb') as f: cur_hash = hashlib.sha256(f.read()).hexdigest()
        print(f'  Current GCM sha256: {cur_hash}')
        print(f'  Backup     sha256: {bak_hash}')
        if cur_hash != bak_hash:
            print('  WARNING: backup does NOT match current GCM. Aborting.')
            return 1
    else:
        print('  No backup found. Aborting.')
        return 1

    print(f'  GCM total size: {os.path.getsize(GCM_PATH)} bytes')
    print(f'  Will write {len(new_data)} bytes at GCM offset 0x{gcm_off:X}')
    if len(new_data) != gcm_size:
        print(f'  ERROR: data size changed ({gcm_size} -> {len(new_data)}). Aborting.')
        return 1

    with open(GCM_PATH, 'r+b') as f:
        f.seek(gcm_off)
        f.write(bytes(new_data))
    new_total = os.path.getsize(GCM_PATH)
    print(f'\nWrote. New GCM size: {new_total} bytes')
    if new_total != 1459978240:
        print(f'  ERROR: GCM size changed!')
        return 1
    with open(GCM_PATH, 'rb') as f: new_hash = hashlib.sha256(f.read()).hexdigest()
    print(f'  New GCM sha256: {new_hash}')
    print(f'  Backup  sha256: {bak_hash}')
    print(f'  (should differ — they {"DIFFER" if new_hash != bak_hash else "MATCH (BUG!)"})')
    return 0

if __name__ == '__main__':
    sys.exit(main())
