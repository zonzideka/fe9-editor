#!/usr/bin/env python3
"""FE9 GCM modding toolkit.
   - Parse GameCube .gcm, find system.cmp via FST
   - LZ77 (Nintendo Type 0x10) decompress / compress
   - Extract / inject system.cmp
"""
import struct
import sys
import os

# ---------- LZ77 Type 0x10 (Nintendo standard) ----------

def lz77_decompress(data: bytes) -> bytes:
    if data[0] != 0x10:
        raise ValueError(f"Not LZ77 type 0x10 (magic byte = 0x{data[0]:02x})")
    decompressed_size = data[1] | (data[2] << 8) | (data[3] << 16)
    out = bytearray()
    i = 4
    while len(out) < decompressed_size:
        flags = data[i]
        i += 1
        for bit in range(8):
            if len(out) >= decompressed_size:
                break
            if flags & (0x80 >> bit):
                # Back-reference: 2 bytes, big-endian
                hi = data[i]; lo = data[i+1]; i += 2
                length = ((hi >> 4) & 0xF) + 3
                offset = (((hi & 0xF) << 8) | lo) + 1
                pos = len(out) - offset
                for _ in range(length):
                    out.append(out[pos])
                    pos += 1
            else:
                out.append(data[i]); i += 1
    return bytes(out)


def lz77_compress(data: bytes) -> bytes:
    """Greedy LZ77 Type 0x10 compressor. Output is valid but not optimal."""
    n = len(data)
    out = bytearray()
    out.append(0x10)
    out.append(n & 0xFF)
    out.append((n >> 8) & 0xFF)
    out.append((n >> 16) & 0xFF)

    i = 0
    while i < n:
        flags_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break
            # Find longest match in window [max(0,i-4096), i)
            window_start = max(0, i - 4096)
            best_len = 0
            best_off = 0
            max_len = min(18, n - i)
            if max_len >= 3:
                # Search backward from i-1
                for off in range(1, i - window_start + 1):
                    src = i - off
                    # Match length
                    L = 0
                    while L < max_len and data[src + L] == data[i + L]:
                        L += 1
                        # Allow overlap (RLE) - src+L can exceed i
                        if src + L >= n:
                            break
                    if L > best_len:
                        best_len = L
                        best_off = off
                        if L == max_len:
                            break
            if best_len >= 3:
                flags |= (0x80 >> bit)
                hi = ((best_len - 3) << 4) | (((best_off - 1) >> 8) & 0xF)
                lo = (best_off - 1) & 0xFF
                out.append(hi); out.append(lo)
                i += best_len
            else:
                out.append(data[i])
                i += 1
        out[flags_pos] = flags
    return bytes(out)


# ---------- GameCube GCM/FST ----------

class GCM:
    def __init__(self, path: str):
        self.path = path
        with open(path, 'rb') as f:
            f.seek(0)
            self.header = f.read(0x440)
            game_id = self.header[0:6].decode('ascii', errors='replace')
            self.game_id = game_id
            # Disc header offsets per GC spec
            self.dol_offset = struct.unpack('>I', self.header[0x420:0x424])[0]
            self.fst_offset = struct.unpack('>I', self.header[0x424:0x428])[0]
            self.fst_size   = struct.unpack('>I', self.header[0x428:0x42C])[0]
            self.fst_max    = struct.unpack('>I', self.header[0x42C:0x430])[0]

            # Read FST
            f.seek(self.fst_offset)
            self.fst = f.read(self.fst_size)

        # Parse FST root
        # Each entry is 12 bytes; root entry is at offset 0
        # Root: type|name_offset (4) | parent_offset (4) | num_entries (4)
        root_type_name = struct.unpack('>I', self.fst[0:4])[0]
        root_num = struct.unpack('>I', self.fst[8:12])[0]
        self.num_entries = root_num
        # String table starts after entries
        self.string_table_off = root_num * 12

    def name_of(self, idx):
        entry = self.fst[idx*12:(idx+1)*12]
        type_name = struct.unpack('>I', entry[0:4])[0]
        name_off = type_name & 0x00FFFFFF
        # Read null-terminated string from string table
        s = self.string_table_off + name_off
        end = s
        while self.fst[end] != 0:
            end += 1
        return self.fst[s:end].decode('ascii', errors='replace')

    def is_dir(self, idx):
        return (self.fst[idx*12] & 0x01) != 0

    def find_file(self, name: str):
        """Return (entry_index, offset_in_fst, file_offset, file_size) or None."""
        for i in range(1, self.num_entries):
            if self.is_dir(i):
                continue
            if self.name_of(i) == name:
                entry = self.fst[i*12:(i+1)*12]
                file_off = struct.unpack('>I', entry[4:8])[0]
                file_size = struct.unpack('>I', entry[8:12])[0]
                return (i, i*12, file_off, file_size)
        return None

    def list_files(self, prefix=''):
        """Walk FST and yield (path, file_offset, file_size). Simple flat dir handling."""
        # Build directory parent stack via num_entries pattern
        results = []
        # Stack of (end_index, path_prefix)
        stack = [(self.num_entries, '')]
        i = 1
        while i < self.num_entries:
            # Pop finished dirs
            while stack and i >= stack[-1][0]:
                stack.pop()
            entry = self.fst[i*12:(i+1)*12]
            type_name = struct.unpack('>I', entry[0:4])[0]
            is_dir = (entry[0] & 0x01) != 0
            name_off = type_name & 0x00FFFFFF
            s = self.string_table_off + name_off
            e = s
            while self.fst[e] != 0:
                e += 1
            name = self.fst[s:e].decode('ascii', errors='replace')
            current_path = stack[-1][1] + '/' + name if stack else '/' + name
            if is_dir:
                next_idx = struct.unpack('>I', entry[8:12])[0]
                stack.append((next_idx, current_path))
            else:
                file_off = struct.unpack('>I', entry[4:8])[0]
                file_size = struct.unpack('>I', entry[8:12])[0]
                results.append((current_path, file_off, file_size))
            i += 1
        return results

    def read_file(self, name: str):
        info = self.find_file(name)
        if not info:
            return None
        idx, fst_pos, off, size = info
        with open(self.path, 'rb') as f:
            f.seek(off)
            return f.read(size)


def cmd_info(gcm_path):
    g = GCM(gcm_path)
    print(f"Game ID: {g.game_id}")
    print(f"FST offset: 0x{g.fst_offset:X}, size: 0x{g.fst_size:X}, max: 0x{g.fst_max:X}")
    print(f"FST entries: {g.num_entries}")
    files = g.list_files()
    print(f"Total files: {len(files)}")
    print("\nLooking for system.cmp:")
    info = g.find_file('system.cmp')
    if info:
        idx, fst_pos, off, size = info
        print(f"  FOUND. FST index={idx}, file offset=0x{off:X}, size=0x{size:X} ({size} bytes)")
    else:
        print("  NOT FOUND at top level. Searching all files...")
        for path, foff, fsize in files:
            if path.endswith('cmp') or path.endswith('CMP'):
                print(f"  {path}  off=0x{foff:X}  size=0x{fsize:X}")


def cmd_extract(gcm_path, out_path):
    g = GCM(gcm_path)
    info = g.find_file('system.cmp')
    if not info:
        # Search all files
        for path, foff, fsize in g.list_files():
            if path.endswith('system.cmp'):
                with open(gcm_path, 'rb') as f:
                    f.seek(foff)
                    data = f.read(fsize)
                with open(out_path, 'wb') as f:
                    f.write(data)
                print(f"Extracted {path} -> {out_path} ({fsize} bytes)")
                return
        print("system.cmp not found")
        return
    idx, fst_pos, off, size = info
    with open(gcm_path, 'rb') as f:
        f.seek(off)
        data = f.read(size)
    with open(out_path, 'wb') as f:
        f.write(data)
    print(f"Extracted system.cmp ({size} bytes) -> {out_path}")
    print(f"  source offset in GCM: 0x{off:X}")


def cmd_decompress(in_path, out_path):
    with open(in_path, 'rb') as f:
        data = f.read()
    out = lz77_decompress(data)
    with open(out_path, 'wb') as f:
        f.write(out)
    print(f"Decompressed {len(data)} -> {len(out)} bytes")
    print(f"First 16 bytes: {out[:16].hex(' ')}")


def cmd_compress(in_path, out_path):
    with open(in_path, 'rb') as f:
        data = f.read()
    out = lz77_compress(data)
    with open(out_path, 'wb') as f:
        f.write(out)
    print(f"Compressed {len(data)} -> {len(out)} bytes")
    # Verify roundtrip
    rt = lz77_decompress(out)
    if rt == data:
        print("Roundtrip verified OK")
    else:
        print(f"ROUNDTRIP FAILED: rt size={len(rt)}, orig size={len(data)}")


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'help'
    if cmd == 'info':
        cmd_info(sys.argv[2])
    elif cmd == 'extract':
        cmd_extract(sys.argv[2], sys.argv[3])
    elif cmd == 'decompress':
        cmd_decompress(sys.argv[2], sys.argv[3])
    elif cmd == 'compress':
        cmd_compress(sys.argv[2], sys.argv[3])
    else:
        print("Usage:")
        print("  fe9_tool.py info <gcm>")
        print("  fe9_tool.py extract <gcm> <system.cmp>")
        print("  fe9_tool.py decompress <system.cmp> <out.bin>")
        print("  fe9_tool.py compress <in.bin> <system.cmp>")
