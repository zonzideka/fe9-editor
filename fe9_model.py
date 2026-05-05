#!/usr/bin/env python3
"""FE9 data model: load FE8Data.bin from GCM, edit in-memory, save back in-place.

Wraps fe9_tool.GCM. All edits go through this object so dirty-state tracking
and diff computation are centralized.
"""
import struct, os, hashlib, json
from fe9_tool import GCM

# JobData section
JOB_TBL = 0x6FC0
JOB_ENTRY = 0x64

# Pointer fields (4-byte BE, relative to file 0x20)
JOB_F_JID         = 0x00
JOB_F_MJID        = 0x04
JOB_F_DESC        = 0x08
JOB_F_PROMO       = 0x0C
JOB_F_DEF_WEAPON  = 0x10
JOB_F_WEAPON_LV   = 0x14
JOB_F_SKILL1      = 0x18
JOB_F_SKILL2      = 0x1C
JOB_F_SKILL3      = 0x20
JOB_F_SKILL4      = 0x24
JOB_F_SKILL5      = 0x28
JOB_F_RACE        = 0x2C
JOB_F_MISC        = 0x30
JOB_F_RESERVED    = 0x34
JOB_F_ANIM        = 0x38

# Byte fields
JOB_F_CON           = 0x3C
JOB_F_WEIGHT        = 0x3D
JOB_F_MOV           = 0x3E
JOB_F_FLAG3F        = 0x3F  # unknown
JOB_F_SKILL_CAP     = 0x40
# 0x41-0x43 unknown

JOB_BASES   = 0x44   # 8 bytes
JOB_CAPS    = 0x4C   # 8 bytes
JOB_GROWTHS = 0x54   # 8 bytes
JOB_LAGUZ   = 0x5C   # 8 bytes (laguz strike data)

# Weapon proficiency labels: each weapon-level block is 9 bytes (ASCII rank chars).
# Block ordering observed empirically: Sword/Lance/Axe/Bow/Fire/Wind/Thunder/Staff/Light
WEAPON_TYPES_CN = ['剑', '枪', '斧', '弓', '火', '风', '雷', '杖', '光']

# RelianceData (support / 支援) section — 41 entries, variable size:
#   per entry: 4-byte main PID ptr + 4-byte slot count + N × 8-byte slot
#   per slot: 4-byte partner PID ptr + 3 bonus bytes (C/B/A) + 1 padding byte
RELIANCE_TBL = 0x12DBC

# KiznaData (絆 / 固定支援) section — 36 entries × 12 bytes:
#   4-byte PID A ptr + 4-byte PID B ptr + 1-byte bonus type + 1-byte bonus value + 2-byte padding
#   type 0x01 = 必杀加成 (crit bonus, value = +5 or +10), type 0x02 = 对话型 (story/dialogue, no combat bonus)
KIZNA_TBL = 0x145BC
KIZNA_ENTRY = 12

# ItemData section
ITEM_TBL = 0x9CB0
ITEM_ENTRY = 0x60   # 96 bytes per entry
ITEM_F_IID         = 0x00
ITEM_F_MIID        = 0x04
ITEM_F_DESC        = 0x08
ITEM_F_TYPE        = 0x0C   # ptr to weapon type str (sword/lance/axe/bow/fire/wind/thunder/light/staff/item)
ITEM_F_SUBTYPE     = 0x10
ITEM_F_RANK        = 0x14   # ptr to rank string ('E'/'D'/'C'/'B'/'A'/'S')
ITEM_F_TRAIT1      = 0x18
ITEM_F_TRAIT2      = 0x1C
ITEM_F_TRAIT3      = 0x20
ITEM_F_TRAIT4      = 0x24
ITEM_F_TRAIT5      = 0x28
ITEM_F_TRAIT6      = 0x2C
ITEM_F_EFFECT1     = 0x30
ITEM_F_EFFECT2     = 0x34
ITEM_F_ANIM1       = 0x38
ITEM_F_ANIM2       = 0x3C
# Stat bytes
ITEM_F_PAD40       = 0x40   # always 0
ITEM_F_COSTPER     = 0x41   # cost per remaining use (gold)
ITEM_F_USES        = 0x42   # max uses
ITEM_F_MT          = 0x43   # might / 攻击
ITEM_F_HIT         = 0x44   # hit / 命中
ITEM_F_WT          = 0x45   # weight / 重量
ITEM_F_CRIT        = 0x46   # crit / 必杀
ITEM_F_RANGE_MIN   = 0x47
ITEM_F_RANGE_MAX   = 0x48
ITEM_F_ICON        = 0x49   # icon ID
ITEM_F_WEXP        = 0x4A   # weapon exp gained per use
# 0x4B-0x54: 10 stat bonuses (HP/Str/Mag/Skl/Spd/Lck/Def/Res/Mov/Con) — most items zero
# 0x55-0x5F: 11 bytes uncertain (likely growth bonuses or AI weights — many items non-zero)
ITEM_BONUSES       = 0x4B   # 10 bytes equip bonuses
ITEM_GROWTH        = 0x55   # 8 bytes signed growth bonuses (HP/Str/Mag/Skl/Spd/Lck/Def/Res)
# 0x5D-0x5F: 3 trailing bytes

# PersonData section (entry size 0x54 / 84 bytes)
PERSON_TBL = 0x2C
PERSON_ENTRY = 0x54
PERSON_F_PID         = 0x00
PERSON_F_MPID        = 0x04
# +0x08: 4 bytes padding (always 0)
PERSON_F_PORTRAIT    = 0x0C    # FID portrait pointer
PERSON_F_CLASS       = 0x10    # starting class JID pointer
PERSON_F_AFFINITY    = 0x14    # AID affinity pointer
PERSON_F_WEAPON_LV   = 0x18    # weapon-level pointer
PERSON_F_SKILL1      = 0x1C
PERSON_F_SKILL2      = 0x20
PERSON_F_SKILL3      = 0x24
PERSON_F_ANIM_UNPRO  = 0x28    # unpromoted animation pointer
PERSON_F_ANIM_PRO    = 0x2C    # promoted animation pointer
# 0x30-0x33: unknown 4 bytes
PERSON_F_LAGUZ_GAUGE = 0x34    # starting laguz transform gauge (0..20)
# 0x35: unknown
PERSON_LEVEL         = 0x36    # 1 byte
PERSON_F_BUILD       = 0x37    # build / 体格
PERSON_F_WEIGHT      = 0x38    # weight
PERSON_BASES         = 0x39    # 8 bytes SIGNED s8 (offsets relative to class bases)
PERSON_GROWTHS       = 0x41    # 8 bytes unsigned (% growth rates)
# 0x49-0x53: 11 bytes unknown (likely AI flags, gender, mounted bits, etc)

# English stat keys -> Chinese display labels (UI uses these)
STAT_KEYS = ['HP', 'Str', 'Mag', 'Skl', 'Spd', 'Lck', 'Def', 'Res']
STAT_CN   = ['生命', '力量', '魔力', '技术', '速度', '幸运', '防御', '魔防']

# Translation file (CN/JP/EN names)
_TRANS = None


class UnsafePointerEdit(Exception):
    """Raised when attempting to write a non-null pointer to a field NOT in the engine's
    relocation table — would crash the game on load."""
    def __init__(self, field_offset, msg=''):
        self.field_offset = field_offset
        super().__init__(msg or f'unsafe pointer field at 0x{field_offset:X}')

def load_translations():
    global _TRANS
    if _TRANS is None:
        # PyInstaller bundles resources in sys._MEIPASS; otherwise alongside script
        import sys as _sys
        base = getattr(_sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, 'translations.json')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                _TRANS = json.load(f)
        else:
            _TRANS = {'jobs': {}, 'persons': {}}
    return _TRANS


class FE9Data:
    def __init__(self, gcm_path):
        self.gcm_path = gcm_path
        self.gcm = GCM(gcm_path)
        info = self.gcm.find_file('FE8Data.bin')
        if not info:
            raise RuntimeError('FE8Data.bin not found in GCM')
        _, _, self.fe8_offset, self.fe8_size = info
        with open(gcm_path, 'rb') as f:
            f.seek(self.fe8_offset)
            self.original_data = f.read(self.fe8_size)
        self.data = bytearray(self.original_data)
        self.job_count = struct.unpack('>I', self.data[JOB_TBL:JOB_TBL+4])[0]
        self.person_count = struct.unpack('>I', self.data[PERSON_TBL:PERSON_TBL+4])[0]
        self.item_count = struct.unpack('>I', self.data[ITEM_TBL:ITEM_TBL+4])[0]
        self.reliance_count = struct.unpack('>I', self.data[RELIANCE_TBL:RELIANCE_TBL+4])[0]
        self.kizna_count = struct.unpack('>I', self.data[KIZNA_TBL:KIZNA_TBL+4])[0]
        self.translations = load_translations()
        # Pointer relocation table — used to validate which pointer fields are safe to edit.
        # Only fields registered here get relocated by the engine at load time. Writing a
        # non-null pointer to an unregistered field crashes the game.
        ptr_table_rel = struct.unpack('>I', self.data[0x04:0x08])[0]
        ptr_count     = struct.unpack('>I', self.data[0x08:0x0C])[0]
        ptr_table_abs = ptr_table_rel + 0x20
        self._reloc_offsets = set()
        for i in range(ptr_count):
            e = struct.unpack('>I', self.data[ptr_table_abs + 4*i : ptr_table_abs + 4*i + 4])[0]
            self._reloc_offsets.add(e)

    def is_pointer_field_safe(self, abs_field_offset):
        """Return True if writing a non-null pointer at this absolute file offset is safe
        (i.e., the engine will relocate it at load time). Always safe to write 0."""
        return (abs_field_offset - 0x20) in self._reloc_offsets

    def is_person_skill_safe(self, person_idx, slot_idx):
        return self.is_pointer_field_safe(self.person_offset(person_idx) + PERSON_F_SKILL1 + 4*slot_idx)

    def is_job_skill_safe(self, job_idx, slot_idx):
        return self.is_pointer_field_safe(self.job_offset(job_idx) + JOB_F_SKILL1 + 4*slot_idx)

    def is_item_trait_safe(self, item_idx, slot_idx):
        return self.is_pointer_field_safe(self.item_offset(item_idx) + ITEM_F_TRAIT1 + 4*slot_idx)

    def is_item_effect_safe(self, item_idx, slot_idx):
        return self.is_pointer_field_safe(self.item_offset(item_idx) + ITEM_F_EFFECT1 + 4*slot_idx)

    # --- string helpers ---
    def get_string(self, ptr):
        if ptr == 0:
            return ''
        off = ptr + 0x20
        if off >= len(self.data):
            return f'<bad 0x{ptr:X}>'
        try:
            end = self.data.index(b'\x00', off)
        except ValueError:
            return f'<bad 0x{ptr:X}>'
        return self.data[off:end].decode('shift_jis', errors='replace')

    def _ptr(self, off):
        return struct.unpack('>I', self.data[off:off+4])[0]

    # --- jobs ---
    def job_offset(self, idx):
        return JOB_TBL + 4 + idx * JOB_ENTRY

    def get_job(self, idx):
        eo = self.job_offset(idx)
        jid = self.get_string(self._ptr(eo + JOB_F_JID))
        tr = self.translations.get('jobs', {}).get(jid, {})
        return {
            'idx': idx,
            'offset': eo,
            'jid': jid,
            'cn': tr.get('cn', ''),
            'jp': tr.get('jp', ''),
            'en': tr.get('en', ''),
            'mjid': self.get_string(self._ptr(eo + JOB_F_MJID)),
            'desc_id': self.get_string(self._ptr(eo + JOB_F_DESC)),
            'promo_jid': self.get_string(self._ptr(eo + JOB_F_PROMO)),
            'def_weapon': self.get_string(self._ptr(eo + JOB_F_DEF_WEAPON)),
            'weapon_lv_ref': self.get_string(self._ptr(eo + JOB_F_WEAPON_LV)),
            'skills': [self.get_string(self._ptr(eo + JOB_F_SKILL1 + 4*i)) for i in range(5)],
            'race': self.get_string(self._ptr(eo + JOB_F_RACE)),
            'anim': self.get_string(self._ptr(eo + JOB_F_ANIM)),
            'con':           self.data[eo + JOB_F_CON],
            'weight':        self.data[eo + JOB_F_WEIGHT],
            'mov':           self.data[eo + JOB_F_MOV],
            'skill_cap':     self.data[eo + JOB_F_SKILL_CAP],
            'bases':   list(self.data[eo+JOB_BASES:eo+JOB_BASES+8]),
            'caps':    list(self.data[eo+JOB_CAPS:eo+JOB_CAPS+8]),
            'growths': list(self.data[eo+JOB_GROWTHS:eo+JOB_GROWTHS+8]),
            'laguz':   list(self.data[eo+JOB_LAGUZ:eo+JOB_LAGUZ+8]),
        }

    # Map of editable byte fields by group name
    JOB_GROUP_OFFSETS = {
        'caps': JOB_CAPS, 'bases': JOB_BASES, 'growths': JOB_GROWTHS, 'laguz': JOB_LAGUZ,
    }
    JOB_SCALAR_OFFSETS = {
        'con': JOB_F_CON, 'weight': JOB_F_WEIGHT, 'mov': JOB_F_MOV, 'skill_cap': JOB_F_SKILL_CAP,
    }

    def set_job_stat(self, idx, group, stat_idx, value):
        eo = self.job_offset(idx)
        v = max(0, min(255, int(value)))
        if group in self.JOB_GROUP_OFFSETS:
            self.data[eo + self.JOB_GROUP_OFFSETS[group] + stat_idx] = v
        elif group in self.JOB_SCALAR_OFFSETS:
            self.data[eo + self.JOB_SCALAR_OFFSETS[group]] = v
        else:
            raise ValueError(f'unknown job group {group}')

    def original_job_stat(self, idx, group, stat_idx=0):
        eo = self.job_offset(idx)
        if group in self.JOB_GROUP_OFFSETS:
            return self.original_data[eo + self.JOB_GROUP_OFFSETS[group] + stat_idx]
        if group in self.JOB_SCALAR_OFFSETS:
            return self.original_data[eo + self.JOB_SCALAR_OFFSETS[group]]
        raise ValueError(f'unknown job group {group}')

    def set_job_skill(self, job_idx, slot_idx, sid_name):
        """Write the pointer for the chosen SID into class's skill slot (0..4)."""
        if slot_idx not in (0, 1, 2, 3, 4):
            raise ValueError(f'job skill slot must be 0..4, got {slot_idx}')
        relptr = self.sid_to_relptr(sid_name) if sid_name else 0
        eo = self.job_offset(job_idx)
        field_off = eo + JOB_F_SKILL1 + 4*slot_idx
        if relptr != 0 and not self.is_pointer_field_safe(field_off):
            raise UnsafePointerEdit(field_off, '该职业的此技能槽原本为空，引擎重定位表未登记此字段，写入新指针会让游戏崩溃。')
        self.data[field_off:field_off+4] = struct.pack('>I', relptr)

    def original_job_skill(self, job_idx, slot_idx):
        eo = self.job_offset(job_idx)
        import struct as _s
        ptr = _s.unpack('>I', self.original_data[eo+JOB_F_SKILL1+4*slot_idx:eo+JOB_F_SKILL1+4*slot_idx+4])[0]
        return self.get_string(ptr) if ptr else ''

    # --- persons ---
    def person_offset(self, idx):
        return PERSON_TBL + 4 + idx * PERSON_ENTRY

    @staticmethod
    def _s8(b):
        """Convert unsigned byte (0..255) to signed s8 (-128..127)."""
        return b if b < 128 else b - 256

    def _scan_string_inventory(self):
        """One-time scan: build pointer->name maps for SIDs, affinities, item traits, item effects.
        Used for dropdown editors."""
        if hasattr(self, '_sid_offsets'):
            return
        data = bytes(self.data)
        # SIDs
        self._sid_offsets = {}
        pos = 0
        while True:
            p = data.find(b'SID_', pos)
            if p < 0: break
            end = data.index(b'\x00', p)
            s = data[p:end]
            if all(0x20 <= b < 0x7F for b in s) and len(s) <= 60:
                name = s.decode('ascii')
                if name not in self._sid_offsets:
                    self._sid_offsets[name] = p
            pos = end + 1
        # Affinity strings — collect from in-use pointers in PersonData
        self._affinity_offsets = {}
        for i in range(self.person_count):
            eo = self.person_offset(i)
            ptr = self._ptr(eo + PERSON_F_AFFINITY)
            if ptr == 0:
                self._affinity_offsets[''] = 0
                continue
            s = self.get_string(ptr)
            if s and s not in self._affinity_offsets:
                self._affinity_offsets[s] = ptr + 0x20
        # Item trait + effect strings — collect from in-use pointers in ItemData
        self._item_trait_offsets = {}
        self._item_effect_offsets = {}
        for i in range(self.item_count):
            eo = self.item_offset(i)
            for slot in range(6):
                ptr = self._ptr(eo + ITEM_F_TRAIT1 + 4*slot)
                if ptr:
                    s = self.get_string(ptr)
                    if s and s not in self._item_trait_offsets:
                        self._item_trait_offsets[s] = ptr + 0x20
            for slot in range(2):
                ptr = self._ptr(eo + ITEM_F_EFFECT1 + 4*slot)
                if ptr:
                    s = self.get_string(ptr)
                    if s and s not in self._item_effect_offsets:
                        self._item_effect_offsets[s] = ptr + 0x20

    def all_skill_sids(self):
        """Sorted list of all SID names found in the file."""
        self._scan_string_inventory()
        return sorted(self._sid_offsets.keys())

    def all_affinity_names(self):
        """List of affinity name strings in their canonical order."""
        self._scan_string_inventory()
        order = ['', 'fire', 'water', 'wind', 'thunder', 'dark', 'light', 'heaven', 'telius']
        return [a for a in order if a in self._affinity_offsets]

    def sid_to_relptr(self, sid_name):
        """Return the relative pointer value (file_offset - 0x20) to write into a skill field.
        None or '' means clear (write 0)."""
        if not sid_name:
            return 0
        self._scan_string_inventory()
        off = self._sid_offsets.get(sid_name)
        if off is None:
            raise KeyError(f'unknown SID {sid_name!r}')
        return off - 0x20

    def skill_cn(self, sid_name):
        return self.translations.get('skills', {}).get(sid_name, '') if sid_name else ''

    def affinity_cn(self, name):
        return self.translations.get('affinities', {}).get(name, '') if name is not None else ''

    def item_trait_cn(self, name):
        return self.translations.get('item_traits', {}).get(name, '') if name else ''

    def item_effect_cn(self, name):
        return self.translations.get('item_effects', {}).get(name, '') if name else ''

    def all_item_traits(self):
        self._scan_string_inventory()
        return sorted(self._item_trait_offsets.keys())

    def all_item_effects(self):
        self._scan_string_inventory()
        return sorted(self._item_effect_offsets.keys())

    def trait_to_relptr(self, name):
        if not name: return 0
        self._scan_string_inventory()
        off = self._item_trait_offsets.get(name)
        if off is None: raise KeyError(f'unknown trait {name!r}')
        return off - 0x20

    def effect_to_relptr(self, name):
        if not name: return 0
        self._scan_string_inventory()
        off = self._item_effect_offsets.get(name)
        if off is None: raise KeyError(f'unknown effect {name!r}')
        return off - 0x20

    def set_item_trait(self, item_idx, slot_idx, name):
        if slot_idx not in (0, 1, 2, 3, 4, 5):
            raise ValueError(f'item trait slot must be 0..5, got {slot_idx}')
        relptr = self.trait_to_relptr(name) if name else 0
        eo = self.item_offset(item_idx)
        field_off = eo + ITEM_F_TRAIT1 + 4*slot_idx
        if relptr != 0 and not self.is_pointer_field_safe(field_off):
            raise UnsafePointerEdit(field_off, '该物品的此特性槽原本为空，引擎重定位表未登记此字段，写入新指针会让游戏崩溃。')
        self.data[field_off:field_off+4] = struct.pack('>I', relptr)

    def set_item_effect(self, item_idx, slot_idx, name):
        if slot_idx not in (0, 1):
            raise ValueError(f'item effect slot must be 0..1, got {slot_idx}')
        relptr = self.effect_to_relptr(name) if name else 0
        eo = self.item_offset(item_idx)
        field_off = eo + ITEM_F_EFFECT1 + 4*slot_idx
        if relptr != 0 and not self.is_pointer_field_safe(field_off):
            raise UnsafePointerEdit(field_off, '该物品的此特效槽原本为空，引擎重定位表未登记此字段，写入新指针会让游戏崩溃。')
        self.data[field_off:field_off+4] = struct.pack('>I', relptr)

    def original_item_trait(self, item_idx, slot_idx):
        eo = self.item_offset(item_idx)
        ptr = struct.unpack('>I', self.original_data[eo+ITEM_F_TRAIT1+4*slot_idx:eo+ITEM_F_TRAIT1+4*slot_idx+4])[0]
        return self.get_string(ptr) if ptr else ''

    def original_item_effect(self, item_idx, slot_idx):
        eo = self.item_offset(item_idx)
        ptr = struct.unpack('>I', self.original_data[eo+ITEM_F_EFFECT1+4*slot_idx:eo+ITEM_F_EFFECT1+4*slot_idx+4])[0]
        return self.get_string(ptr) if ptr else ''

    # --- RelianceData (supports / 支援) ---
    def _build_reliance_index(self):
        """Compute byte offsets of each support entry (variable size)."""
        if hasattr(self, '_reliance_offsets'):
            return
        offsets = []
        pos = RELIANCE_TBL + 4
        for i in range(self.reliance_count):
            offsets.append(pos)
            count = struct.unpack('>I', self.data[pos+4:pos+8])[0]
            pos += 8 + 8 * count
        self._reliance_offsets = offsets

    def reliance_offset(self, idx):
        self._build_reliance_index()
        return self._reliance_offsets[idx]

    def get_reliance(self, idx):
        eo = self.reliance_offset(idx)
        main_ptr = self._ptr(eo)
        count = struct.unpack('>I', self.data[eo+4:eo+8])[0]
        slots = []
        for s in range(count):
            sp = eo + 8 + s * 8
            partner_ptr = self._ptr(sp)
            bonus = list(self.data[sp+4:sp+8])  # 3 bonus bytes + 1 padding
            slots.append({
                'partner_pid': self.get_string(partner_ptr),
                'partner_ptr': partner_ptr,
                'bonus_c': bonus[0],
                'bonus_b': bonus[1],
                'bonus_a': bonus[2],
                'pad':     bonus[3],
                'slot_field_off': sp,    # absolute offset of partner ptr (for safety check)
            })
        return {
            'idx': idx,
            'offset': eo,
            'main_pid': self.get_string(main_ptr),
            'main_ptr': main_ptr,
            'count': count,
            'slots': slots,
        }

    def _build_pid_index(self):
        if hasattr(self, '_pid_offsets'):
            return
        self._pid_offsets = {}
        for i in range(self.person_count):
            eo = self.person_offset(i)
            ptr = self._ptr(eo + PERSON_F_PID)
            if ptr == 0: continue
            name = self.get_string(ptr)
            if name and name not in self._pid_offsets:
                self._pid_offsets[name] = ptr + 0x20

    def pid_to_relptr(self, pid_name):
        """Look up a PID's relative pointer value. '' / None → 0."""
        if not pid_name:
            return 0
        self._build_pid_index()
        off = self._pid_offsets.get(pid_name)
        if off is None:
            raise KeyError(f'unknown PID {pid_name!r}')
        return off - 0x20

    def all_pids(self):
        self._build_pid_index()
        return sorted(self._pid_offsets.keys())

    def set_reliance_partner(self, entry_idx, slot_idx, pid_name):
        """Change a support slot's partner PID. Pass '' or None to clear."""
        eo = self.reliance_offset(entry_idx)
        count = struct.unpack('>I', self.data[eo+4:eo+8])[0]
        if not (0 <= slot_idx < count):
            raise IndexError(f'slot {slot_idx} out of range (count={count})')
        sp = eo + 8 + slot_idx * 8
        relptr = self.pid_to_relptr(pid_name) if pid_name else 0
        if relptr != 0 and not self.is_pointer_field_safe(sp):
            raise UnsafePointerEdit(sp, '该支援槽原本为空且未在引擎重定位表中登记，写入新指针会让游戏崩溃。')
        self.data[sp:sp+4] = struct.pack('>I', relptr)

    def set_reliance_bonus(self, entry_idx, slot_idx, level, value):
        """Set bonus byte for a slot. level in {'C','B','A'}."""
        eo = self.reliance_offset(entry_idx)
        sp = eo + 8 + slot_idx * 8
        off_in_slot = {'C': 4, 'B': 5, 'A': 6}[level]
        v = max(0, min(255, int(value)))
        self.data[sp + off_in_slot] = v

    def original_reliance(self, idx):
        """Build the original (unmodified) version of an entry."""
        # Use the same offset (entry layout doesn't change since count is preserved)
        eo = self.reliance_offset(idx)
        main_ptr = struct.unpack('>I', self.original_data[eo:eo+4])[0]
        count = struct.unpack('>I', self.original_data[eo+4:eo+8])[0]
        slots = []
        for s in range(count):
            sp = eo + 8 + s * 8
            partner_ptr = struct.unpack('>I', self.original_data[sp:sp+4])[0]
            bonus = list(self.original_data[sp+4:sp+8])
            slots.append({
                'partner_pid': self.get_string(partner_ptr),
                'bonus_c': bonus[0], 'bonus_b': bonus[1], 'bonus_a': bonus[2],
            })
        return {'main_pid': self.get_string(main_ptr), 'count': count, 'slots': slots}

    # --- KiznaData (固定支援) ---
    def kizna_offset(self, idx):
        return KIZNA_TBL + 4 + idx * KIZNA_ENTRY

    def get_kizna(self, idx):
        eo = self.kizna_offset(idx)
        pa = self._ptr(eo)
        pb = self._ptr(eo + 4)
        return {
            'idx': idx,
            'offset': eo,
            'pid_a': self.get_string(pa),
            'pid_b': self.get_string(pb),
            'pid_a_ptr': pa,
            'pid_b_ptr': pb,
            'bonus_type':  self.data[eo + 8],
            'bonus_value': self.data[eo + 9],
            'pad':  list(self.data[eo+10:eo+12]),
        }

    def set_kizna_partner(self, idx, which, pid_name):
        """which = 'a' or 'b'."""
        eo = self.kizna_offset(idx)
        field_off = eo + (0 if which == 'a' else 4)
        relptr = self.pid_to_relptr(pid_name) if pid_name else 0
        if relptr != 0 and not self.is_pointer_field_safe(field_off):
            raise UnsafePointerEdit(field_off, '该固定支援条目的此 PID 字段未在引擎重定位表中登记，写入新指针会让游戏崩溃。')
        self.data[field_off:field_off+4] = struct.pack('>I', relptr)

    def set_kizna_field(self, idx, field, value):
        """field = 'type' or 'value' (1-byte each)."""
        eo = self.kizna_offset(idx)
        off = eo + (8 if field == 'type' else 9)
        self.data[off] = max(0, min(255, int(value)))

    def original_kizna(self, idx):
        eo = self.kizna_offset(idx)
        pa = struct.unpack('>I', self.original_data[eo:eo+4])[0]
        pb = struct.unpack('>I', self.original_data[eo+4:eo+8])[0]
        return {
            'pid_a': self.get_string(pa),
            'pid_b': self.get_string(pb),
            'bonus_type':  self.original_data[eo + 8],
            'bonus_value': self.original_data[eo + 9],
        }

    def get_weapon_levels(self, ptr):
        """Decode the 9-byte weapon-level block at the given relative pointer.
        Returns a list of 9 single-char rank strings; '-' = none, E/D/C/B/A/S = ranks, '*' = special."""
        if ptr == 0:
            return ['-'] * 9
        abs_pos = ptr + 0x20
        if abs_pos + 9 > len(self.data):
            return ['?'] * 9
        out = []
        for b in self.data[abs_pos:abs_pos+9]:
            if b == 0x2D: out.append('-')
            elif 0x20 <= b < 0x7F: out.append(chr(b))
            else: out.append('?')
        return out

    def get_person_weapon_levels(self, idx):
        eo = self.person_offset(idx)
        ptr = self._ptr(eo + PERSON_F_WEAPON_LV)
        return self.get_weapon_levels(ptr)

    def get_job_weapon_levels(self, idx):
        eo = self.job_offset(idx)
        ptr = self._ptr(eo + JOB_F_WEAPON_LV)
        return self.get_weapon_levels(ptr)

    def set_job_weapon_level(self, job_idx, slot_idx, rank_char):
        """Write rank char ('-'/'E'/'D'/'C'/'B'/'A'/'S'/'*') at slot_idx in the class's weapon block.
        WARNING: weapon-level blocks may be shared across multiple JobData/PersonData entries —
        editing affects all sharers. Caller is responsible for warning the user."""
        eo = self.job_offset(job_idx)
        ptr = self._ptr(eo + JOB_F_WEAPON_LV)
        if ptr == 0:
            raise RuntimeError(f'class {job_idx} has null weapon-level pointer')
        abs_pos = ptr + 0x20
        if abs_pos + slot_idx >= len(self.data):
            raise RuntimeError('weapon-level position out of range')
        c = (rank_char or '-')[:1]
        self.data[abs_pos + slot_idx] = ord(c)

    def original_job_weapon_level(self, job_idx, slot_idx):
        eo = self.job_offset(job_idx)
        ptr = self._ptr(eo + JOB_F_WEAPON_LV)
        if ptr == 0: return '-'
        abs_pos = ptr + 0x20
        if abs_pos + slot_idx >= len(self.original_data): return '?'
        b = self.original_data[abs_pos + slot_idx]
        if b == 0x2D: return '-'
        if 0x20 <= b < 0x7F: return chr(b)
        return '?'

    def weapon_block_sharers(self, ptr):
        """Return list of (kind, idx, name) sharing the given weapon-level block pointer.
        kind = 'job' or 'person'."""
        sharers = []
        for i in range(self.job_count):
            eo = self.job_offset(i)
            if self._ptr(eo + JOB_F_WEAPON_LV) == ptr:
                sharers.append(('job', i, self.get_string(self._ptr(eo + JOB_F_JID))))
        for i in range(self.person_count):
            eo = self.person_offset(i)
            if self._ptr(eo + PERSON_F_WEAPON_LV) == ptr:
                sharers.append(('person', i, self.get_string(self._ptr(eo + PERSON_F_PID))))
        return sharers

    # --- items ---
    def item_offset(self, idx):
        return ITEM_TBL + 4 + idx * ITEM_ENTRY

    def get_item(self, idx):
        eo = self.item_offset(idx)
        iid = self.get_string(self._ptr(eo + ITEM_F_IID))
        cn = self.translations.get('items', {}).get(iid, '')
        miid = self.get_string(self._ptr(eo + ITEM_F_MIID))
        return {
            'idx': idx,
            'offset': eo,
            'iid': iid,
            'cn': cn,
            'miid': miid,
            'desc_id': self.get_string(self._ptr(eo + ITEM_F_DESC)),
            'type':    self.get_string(self._ptr(eo + ITEM_F_TYPE)),
            'subtype': self.get_string(self._ptr(eo + ITEM_F_SUBTYPE)),
            'rank':    self.get_string(self._ptr(eo + ITEM_F_RANK)),
            'traits': [self.get_string(self._ptr(eo + ITEM_F_TRAIT1 + 4*i)) for i in range(6)],
            'effects':[self.get_string(self._ptr(eo + ITEM_F_EFFECT1 + 4*i)) for i in range(2)],
            'anims':  [self.get_string(self._ptr(eo + ITEM_F_ANIM1 + 4*i)) for i in range(2)],
            'cost_per':  self.data[eo + ITEM_F_COSTPER],
            'uses':      self.data[eo + ITEM_F_USES],
            'mt':        self.data[eo + ITEM_F_MT],
            'hit':       self.data[eo + ITEM_F_HIT],
            'wt':        self.data[eo + ITEM_F_WT],
            'crit':      self.data[eo + ITEM_F_CRIT],
            'range_min': self.data[eo + ITEM_F_RANGE_MIN],
            'range_max': self.data[eo + ITEM_F_RANGE_MAX],
            'icon':      self.data[eo + ITEM_F_ICON],
            'wexp':      self.data[eo + ITEM_F_WEXP],
            'bonuses': list(self.data[eo+ITEM_BONUSES:eo+ITEM_BONUSES+10]),     # HP/Str/Mag/Skl/Spd/Lck/Def/Res/Mov/Con
            'growth':  [self._s8(b) for b in self.data[eo+ITEM_GROWTH:eo+ITEM_GROWTH+8]],  # signed
        }

    ITEM_SCALAR_OFFSETS = {
        'cost_per': ITEM_F_COSTPER, 'uses': ITEM_F_USES, 'mt': ITEM_F_MT,
        'hit': ITEM_F_HIT, 'wt': ITEM_F_WT, 'crit': ITEM_F_CRIT,
        'range_min': ITEM_F_RANGE_MIN, 'range_max': ITEM_F_RANGE_MAX,
        'icon': ITEM_F_ICON, 'wexp': ITEM_F_WEXP,
    }
    ITEM_GROUP_OFFSETS = {
        'bonuses': ITEM_BONUSES, 'growth': ITEM_GROWTH,
    }
    ITEM_SIGNED_GROUPS = {'growth'}

    def set_item_stat(self, idx, group, stat_idx, value):
        eo = self.item_offset(idx)
        v = int(value)
        if group in self.ITEM_SIGNED_GROUPS:
            v = max(-128, min(127, v)) & 0xFF
        else:
            v = max(0, min(255, v))
        if group in self.ITEM_GROUP_OFFSETS:
            self.data[eo + self.ITEM_GROUP_OFFSETS[group] + stat_idx] = v
        elif group in self.ITEM_SCALAR_OFFSETS:
            self.data[eo + self.ITEM_SCALAR_OFFSETS[group]] = v
        else:
            raise ValueError(f'unknown item group {group}')

    def original_item_stat(self, idx, group, stat_idx=0):
        eo = self.item_offset(idx)
        if group in self.ITEM_GROUP_OFFSETS:
            raw = self.original_data[eo + self.ITEM_GROUP_OFFSETS[group] + stat_idx]
            return self._s8(raw) if group in self.ITEM_SIGNED_GROUPS else raw
        if group in self.ITEM_SCALAR_OFFSETS:
            return self.original_data[eo + self.ITEM_SCALAR_OFFSETS[group]]
        raise ValueError(f'unknown item group {group}')

    def get_person(self, idx):
        eo = self.person_offset(idx)
        pid = self.get_string(self._ptr(eo + PERSON_F_PID))
        tr = self.translations.get('persons', {}).get(pid, {})
        raw_bases = self.data[eo+PERSON_BASES:eo+PERSON_BASES+8]
        return {
            'idx': idx,
            'offset': eo,
            'pid': pid,
            'cn': tr.get('cn', ''),
            'jp': tr.get('jp', ''),
            'en': tr.get('en', ''),
            'mpid':           self.get_string(self._ptr(eo + PERSON_F_MPID)),
            'portrait':       self.get_string(self._ptr(eo + PERSON_F_PORTRAIT)),
            'class_jid':      self.get_string(self._ptr(eo + PERSON_F_CLASS)),
            'affinity':       self.get_string(self._ptr(eo + PERSON_F_AFFINITY)),
            'skills':        [self.get_string(self._ptr(eo + PERSON_F_SKILL1 + 4*i)) for i in range(3)],
            'anim_unpro':     self.get_string(self._ptr(eo + PERSON_F_ANIM_UNPRO)),
            'anim_pro':       self.get_string(self._ptr(eo + PERSON_F_ANIM_PRO)),
            'laguz_gauge':    self.data[eo + PERSON_F_LAGUZ_GAUGE],
            'level':          self.data[eo + PERSON_LEVEL],
            'build':          self._s8(self.data[eo + PERSON_F_BUILD]),    # signed s8 offset
            'weight':         self._s8(self.data[eo + PERSON_F_WEIGHT]),   # signed s8 offset
            'bases':         [self._s8(b) for b in raw_bases],
            'growths':   list(self.data[eo+PERSON_GROWTHS:eo+PERSON_GROWTHS+8]),
        }

    def set_person_skill(self, person_idx, slot_idx, sid_name):
        """Write the pointer for the chosen SID into person's skill slot (0..2).
        Pass sid_name='' or None to clear the slot (write 0).
        Raises UnsafePointerEdit if writing non-null to an unregistered field."""
        if slot_idx not in (0, 1, 2):
            raise ValueError(f'skill slot must be 0/1/2, got {slot_idx}')
        relptr = self.sid_to_relptr(sid_name) if sid_name else 0
        eo = self.person_offset(person_idx)
        field_off = eo + PERSON_F_SKILL1 + 4*slot_idx
        if relptr != 0 and not self.is_pointer_field_safe(field_off):
            raise UnsafePointerEdit(field_off, '该角色的此技能槽原本为空，引擎重定位表未登记此字段，写入新指针会让游戏崩溃。')
        self.data[field_off:field_off+4] = struct.pack('>I', relptr)

    def original_person_skill(self, person_idx, slot_idx):
        eo = self.person_offset(person_idx)
        import struct as _s
        ptr = _s.unpack('>I', self.original_data[eo+PERSON_F_SKILL1+4*slot_idx:eo+PERSON_F_SKILL1+4*slot_idx+4])[0]
        return self.get_string(ptr) if ptr else ''

    def find_job_by_jid(self, jid):
        """Return idx of first job with given JID, or None."""
        for i in range(self.job_count):
            eo = self.job_offset(i)
            ptr = self._ptr(eo + JOB_F_JID)
            if self.get_string(ptr) == jid:
                return i
        return None

    def is_promoted_class(self, idx):
        """Heuristic: a class is 'promoted' if its bases sum > its promotion target's bases sum.
        For Laguz, where transformed forms have similar bases, the higher-stat side wins.
        Special / non-combat / unique boss classes (no valid promo) return False here too."""
        eo = self.job_offset(idx)
        promo_ptr = self._ptr(eo + JOB_F_PROMO)
        promo_jid = self.get_string(promo_ptr) if promo_ptr else ''
        if not promo_jid:
            return False
        target_idx = self.find_job_by_jid(promo_jid)
        if target_idx is None or target_idx == idx:
            return False
        # Compare bases sum (use original_data for stability)
        my_bases   = self.original_data[eo+JOB_BASES:eo+JOB_BASES+8]
        t_eo = self.job_offset(target_idx)
        t_bases = self.original_data[t_eo+JOB_BASES:t_eo+JOB_BASES+8]
        return sum(my_bases) > sum(t_bases)

    PERSON_GROUP_OFFSETS = {'bases': PERSON_BASES, 'growths': PERSON_GROWTHS}
    PERSON_SCALAR_OFFSETS = {
        'level': PERSON_LEVEL, 'build': PERSON_F_BUILD, 'weight': PERSON_F_WEIGHT,
        'laguz_gauge': PERSON_F_LAGUZ_GAUGE,
    }
    PERSON_SIGNED_GROUPS = {'bases'}              # interpret as signed s8
    PERSON_SIGNED_SCALARS = {'build', 'weight'}    # signed s8 offsets vs class default

    def set_person_stat(self, idx, group, stat_idx, value):
        eo = self.person_offset(idx)
        v = int(value)
        if group in self.PERSON_SIGNED_GROUPS or group in self.PERSON_SIGNED_SCALARS:
            v = max(-128, min(127, v)) & 0xFF
        else:
            v = max(0, min(255, v))
        if group in self.PERSON_GROUP_OFFSETS:
            self.data[eo + self.PERSON_GROUP_OFFSETS[group] + stat_idx] = v
        elif group in self.PERSON_SCALAR_OFFSETS:
            self.data[eo + self.PERSON_SCALAR_OFFSETS[group]] = v
        else:
            raise ValueError(f'unknown person group {group}')

    def original_person_stat(self, idx, group, stat_idx=0):
        eo = self.person_offset(idx)
        if group in self.PERSON_GROUP_OFFSETS:
            raw = self.original_data[eo + self.PERSON_GROUP_OFFSETS[group] + stat_idx]
            return self._s8(raw) if group in self.PERSON_SIGNED_GROUPS else raw
        if group in self.PERSON_SCALAR_OFFSETS:
            raw = self.original_data[eo + self.PERSON_SCALAR_OFFSETS[group]]
            return self._s8(raw) if group in self.PERSON_SIGNED_SCALARS else raw
        raise ValueError(f'unknown person group {group}')

    # --- dirty / diff ---
    def is_dirty(self):
        return self.data != self.original_data

    def diff_byte_count(self):
        return sum(1 for a, b in zip(self.data, self.original_data) if a != b)

    def revert_all(self):
        self.data = bytearray(self.original_data)

    # --- save ---
    def gcm_sha256(self):
        h = hashlib.sha256()
        with open(self.gcm_path, 'rb') as f:
            while True:
                buf = f.read(1 << 20)
                if not buf:
                    break
                h.update(buf)
        return h.hexdigest()

    def save(self):
        if len(self.data) != self.fe8_size:
            raise RuntimeError(f'FE8Data size changed: {self.fe8_size} -> {len(self.data)}')
        size_before = os.path.getsize(self.gcm_path)
        with open(self.gcm_path, 'r+b') as f:
            f.seek(self.fe8_offset)
            f.write(bytes(self.data))
        size_after = os.path.getsize(self.gcm_path)
        if size_before != size_after:
            raise RuntimeError(f'GCM size changed: {size_before} -> {size_after}')
        self.original_data = bytes(self.data)

    def apply_caps_config(self):
        """Apply rules from caps_config.derive_new_caps to all promoted classes."""
        from caps_config import derive_new_caps
        applied = 0
        for i in range(self.job_count):
            eo = self.job_offset(i)
            cur = tuple(self.data[eo+JOB_CAPS:eo+JOB_CAPS+8])
            new = derive_new_caps(i, cur)
            if new is None:
                continue
            for s in range(8):
                self.data[eo + JOB_CAPS + s] = new[s]
            if new != cur:
                applied += 1
        return applied
