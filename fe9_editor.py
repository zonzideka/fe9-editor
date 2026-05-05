#!/usr/bin/env python3
"""FE9 编辑器 — PyQt6 GUI for editing FE8Data.bin (JobData / PersonData) inside the GCM."""
import sys, os, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QBrush, QAction, QIntValidator, QKeySequence, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QHBoxLayout, QWidget, QFileDialog, QMessageBox, QHeaderView,
    QLabel, QStyledItemDelegate, QLineEdit, QDialog, QTextEdit, QAbstractItemView,
    QDialogButtonBox, QStatusBar, QSplitter, QCheckBox, QComboBox
)

from fe9_model import FE9Data, STAT_KEYS, STAT_CN, WEAPON_TYPES_CN, UnsafePointerEdit

DEFAULT_GCM = ''   # set to a path to auto-load on startup; empty = require manual File→Open

# Color scheme
MOD_BG     = QColor(255, 240, 130)   # 修改未保存
RO_BG      = QColor(245, 245, 245)   # 只读
LOCKED_BG  = QColor(225, 225, 225)   # 锁定 (不可写非 null — 引擎会崩)
TINT_CAPS  = QColor(255, 248, 248)
TINT_BASES = QColor(248, 255, 248)
TINT_GROWTHS = QColor(248, 248, 255)
TINT_LAGUZ = QColor(255, 252, 245)
TINT_SCALAR = QColor(252, 252, 244)


def make_item(text='', editable=True, bg=None, mono=False, ro_bg=False):
    it = QTableWidgetItem(str(text))
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if ro_bg and bg is None:
        bg = RO_BG
    if bg is not None:
        it.setBackground(QBrush(bg))
    if mono:
        it.setFont(QFont('Menlo, Monaco, monospace'))
    return it


class IntDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setValidator(QIntValidator(0, 255, parent))
        ed.setMaxLength(3)
        return ed


class SignedIntDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setValidator(QIntValidator(-128, 127, parent))
        ed.setMaxLength(4)
        return ed


class RankComboDelegate(QStyledItemDelegate):
    """Dropdown for weapon-rank cells: -/E/D/C/B/A/S/*."""
    OPTIONS = ['-', 'E', 'D', 'C', 'B', 'A', 'S', '*']

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        for r in self.OPTIONS:
            cb.addItem(r)
        return cb

    def setEditorData(self, editor, index):
        cur = index.data(Qt.ItemDataRole.DisplayRole) or '-'
        i = self.OPTIONS.index(cur) if cur in self.OPTIONS else 0
        editor.setCurrentIndex(i)

    def setModelData(self, editor, model, index):
        rank = editor.currentText()
        model.setData(index, rank, Qt.ItemDataRole.DisplayRole)


class NamedComboDelegate(QStyledItemDelegate):
    """Generic dropdown delegate. Stores key in UserRole, displays CN-or-key text.
    Subclasses override `_load_options()` and `_lookup_cn(key)`."""
    def __init__(self, fe9_model, parent=None):
        super().__init__(parent)
        self.fe9_model = fe9_model
        self._options = self._load_options()  # list of (key, display)

    def _load_options(self):
        return [('', '— 无 —')]

    def _lookup_cn(self, key):
        return ''

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        for key, disp in self._options:
            cb.addItem(disp, key)
        cb.setMaxVisibleItems(20)
        return cb

    def setEditorData(self, editor, index):
        cur = index.data(Qt.ItemDataRole.UserRole) or ''
        for i in range(editor.count()):
            if editor.itemData(i) == cur:
                editor.setCurrentIndex(i)
                return
        editor.setCurrentIndex(0)

    def setModelData(self, editor, model, index):
        key = editor.currentData() or ''
        cn = self._lookup_cn(key) if key else ''
        display = cn if cn else (key if key else '—')
        model.setData(index, display, Qt.ItemDataRole.DisplayRole)
        model.setData(index, key, Qt.ItemDataRole.UserRole)


class PidComboDelegate(NamedComboDelegate):
    """Dropdown for PID slot cells (used in support pairs)."""
    def _load_options(self):
        named = []
        for pid in self.fe9_model.all_pids():
            tr = self.fe9_model.translations.get('persons', {}).get(pid, {})
            cn = tr.get('cn', '')
            named.append((pid, f'{cn}  [{pid}]' if cn else pid))
        named.sort(key=lambda x: x[1])
        return [('', '— 无 —')] + named

    def _lookup_cn(self, key):
        if not key: return ''
        tr = self.fe9_model.translations.get('persons', {}).get(key, {})
        return f'{tr.get("cn","")}  [{key}]' if tr.get('cn') else key


class SkillComboDelegate(NamedComboDelegate):
    """Dropdown for SID skill cells."""
    def _load_options(self):
        named = [(sid, self.fe9_model.skill_cn(sid) or sid)
                 for sid in self.fe9_model.all_skill_sids()]
        named.sort(key=lambda x: x[1])
        return [('', '— 无 —')] + named
    def _lookup_cn(self, key):
        return self.fe9_model.skill_cn(key)


class TraitComboDelegate(NamedComboDelegate):
    """Dropdown for item trait cells."""
    def _load_options(self):
        named = [(t, self.fe9_model.item_trait_cn(t) or t)
                 for t in self.fe9_model.all_item_traits()]
        named.sort(key=lambda x: x[1])
        return [('', '— 无 —')] + named
    def _lookup_cn(self, key):
        return self.fe9_model.item_trait_cn(key)


class EffectComboDelegate(NamedComboDelegate):
    """Dropdown for item effect cells."""
    def _load_options(self):
        named = [(e, self.fe9_model.item_effect_cn(e) or e)
                 for e in self.fe9_model.all_item_effects()]
        named.sort(key=lambda x: x[1])
        return [('', '— 无 —')] + named
    def _lookup_cn(self, key):
        return self.fe9_model.item_effect_cn(key)


class FrozenTablePair(QWidget):
    """Two QTableWidgets in a QSplitter: left side frozen name cols, right side scrollable.
    User can drag the splitter handle to resize panels, and resize individual columns.
    Vertical scrolling and row selection are synced between the two tables.
    """
    def __init__(self, n_rows, frozen_headers, scroll_headers, parent=None):
        super().__init__(parent)
        self.n_rows = n_rows
        self.frozen_headers = frozen_headers
        self.scroll_headers = scroll_headers

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)

        self.left = QTableWidget(n_rows, len(frozen_headers))
        self.right = QTableWidget(n_rows, len(scroll_headers))

        for tbl in (self.left, self.right):
            tbl.setAlternatingRowColors(True)
            tbl.verticalHeader().setVisible(False)
            tbl.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.SelectedClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
            tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self.left.setHorizontalHeaderLabels(frozen_headers)
        self.right.setHorizontalHeaderLabels(scroll_headers)
        self.right.setItemDelegate(IntDelegate())

        # Left: allow horizontal scroll if content too wide; vertical scroll OFF (synced from right)
        self.left.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.left.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.right.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.right.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Sync vertical scroll
        self.right.verticalScrollBar().valueChanged.connect(self.left.verticalScrollBar().setValue)
        self.left.verticalScrollBar().valueChanged.connect(self.right.verticalScrollBar().setValue)
        # Sync selection
        self.left.itemSelectionChanged.connect(self._sync_selection_from_left)
        self.right.itemSelectionChanged.connect(self._sync_selection_from_right)

        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.right)
        # Default split ratio: 350px frozen, rest for scrollable
        self.splitter.setSizes([350, 1150])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter)

        self._syncing = False

    def _sync_selection_from_left(self):
        if self._syncing: return
        self._syncing = True
        rows = set(idx.row() for idx in self.left.selectedIndexes())
        self.right.clearSelection()
        for r in rows:
            self.right.selectRow(r)
        self._syncing = False

    def _sync_selection_from_right(self):
        if self._syncing: return
        self._syncing = True
        rows = set(idx.row() for idx in self.right.selectedIndexes())
        self.left.clearSelection()
        for r in rows:
            self.left.selectRow(r)
        self._syncing = False

    def set_row_visible(self, row, visible):
        self.left.setRowHidden(row, not visible)
        self.right.setRowHidden(row, not visible)

    def set_left_col_visible(self, col, visible):
        self.left.setColumnHidden(col, not visible)

    def configure_columns(self):
        # Left columns: user-resizable (Interactive). Set sensible defaults.
        # Right columns: also Interactive, with a reasonable default sized to content.
        self.left.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.right.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # Auto-size to content first to get sensible widths, then leave Interactive
        self.left.resizeColumnsToContents()
        self.right.resizeColumnsToContents()


class JobTab(QWidget):
    FROZEN_HEADERS = ['#', 'JID', '中文', '日文', 'English']
    # Scroll columns layout:
    # 5 promo/scalar: 转职目标, 移动, 体格, 重量, 技能格
    # 5 skills: 技能1..技能5
    # 8 caps: 上·HP, 上·力, 上·魔, 上·技, 上·速, 上·幸, 上·防, 上·魔防
    # 8 bases: 基·...
    # 8 growths: 成·...
    # 8 laguz: 兽·...
    SCROLL_HEADERS = (
        ['转职目标', '移动', '体格', '重量', '技能格']
        + [f'技能{i+1}' for i in range(5)]
        + [f'熟·{w}' for w in WEAPON_TYPES_CN]
        + [f'上·{s}' for s in STAT_CN]
        + [f'基·{s}' for s in STAT_CN]
        + [f'成·{s}' for s in STAT_CN]
        + [f'兽·{s}' for s in STAT_CN]
    )
    # Column ranges
    COL_PROMO = 0
    COL_MOV = 1
    COL_CON = 2
    COL_WEIGHT = 3
    COL_SKILL_CAP = 4
    COL_SKILLS = (5, 10)
    COL_WEAPONS = (10, 19)
    COL_CAPS = (19, 27)
    COL_BASES = (27, 35)
    COL_GROWTHS = (35, 43)
    COL_LAGUZ = (43, 51)

    def __init__(self, model: FE9Data, on_change):
        super().__init__()
        self.model = model
        self.on_change = on_change

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Top bar: language toggles + filter
        topbar = QHBoxLayout()
        topbar.addWidget(QLabel('显示列:'))
        self.cb_jid = QCheckBox('JID'); self.cb_jid.setChecked(True)
        self.cb_cn  = QCheckBox('中文'); self.cb_cn.setChecked(True)
        self.cb_jp  = QCheckBox('日文'); self.cb_jp.setChecked(True)
        self.cb_en  = QCheckBox('English'); self.cb_en.setChecked(True)
        for cb in (self.cb_jid, self.cb_cn, self.cb_jp, self.cb_en):
            cb.toggled.connect(self.apply_col_visibility)
            topbar.addWidget(cb)
        topbar.addSpacing(20)
        topbar.addWidget(QLabel('筛选:'))
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText('JID / 中文 / 日文 / English / 后缀如 /F')
        self.filter_box.textChanged.connect(self.apply_filter)
        topbar.addWidget(self.filter_box, 1)
        layout.addLayout(topbar)

        # Table
        self.pair = FrozenTablePair(model.job_count, self.FROZEN_HEADERS, self.SCROLL_HEADERS)
        layout.addWidget(self.pair)

        self._suppress = False
        self.populate()
        self.pair.right.itemChanged.connect(self.on_item_changed)
        self.pair.configure_columns()

    def apply_col_visibility(self):
        # Frozen header layout: # | JID | 中文 | 日文 | English  (cols 0..4)
        self.pair.set_left_col_visible(1, self.cb_jid.isChecked())
        self.pair.set_left_col_visible(2, self.cb_cn.isChecked())
        self.pair.set_left_col_visible(3, self.cb_jp.isChecked())
        self.pair.set_left_col_visible(4, self.cb_en.isChecked())

    def _scalar_meta(self, col):
        """For scroll col, return ('group', stat_idx) or None for read-only."""
        if col == self.COL_PROMO:
            return None
        if col == self.COL_MOV: return ('mov', 0)
        if col == self.COL_CON: return ('con', 0)
        if col == self.COL_WEIGHT: return ('weight', 0)
        if col == self.COL_SKILL_CAP: return ('skill_cap', 0)
        if self.COL_SKILLS[0] <= col < self.COL_SKILLS[1]:
            return None
        if self.COL_WEAPONS[0] <= col < self.COL_WEAPONS[1]:
            return None  # weapon levels are read-only (shared blocks; editing risky)
        if self.COL_CAPS[0] <= col < self.COL_CAPS[1]:
            return ('caps', col - self.COL_CAPS[0])
        if self.COL_BASES[0] <= col < self.COL_BASES[1]:
            return ('bases', col - self.COL_BASES[0])
        if self.COL_GROWTHS[0] <= col < self.COL_GROWTHS[1]:
            return ('growths', col - self.COL_GROWTHS[0])
        if self.COL_LAGUZ[0] <= col < self.COL_LAGUZ[1]:
            return ('laguz', col - self.COL_LAGUZ[0])
        return None

    def _section_bg(self, col):
        if col in (self.COL_PROMO,): return RO_BG
        if col in (self.COL_MOV, self.COL_CON, self.COL_WEIGHT, self.COL_SKILL_CAP): return TINT_SCALAR
        if self.COL_SKILLS[0] <= col < self.COL_SKILLS[1]: return RO_BG
        if self.COL_WEAPONS[0] <= col < self.COL_WEAPONS[1]: return RO_BG
        if self.COL_CAPS[0] <= col < self.COL_CAPS[1]: return TINT_CAPS
        if self.COL_BASES[0] <= col < self.COL_BASES[1]: return TINT_BASES
        if self.COL_GROWTHS[0] <= col < self.COL_GROWTHS[1]: return TINT_GROWTHS
        if self.COL_LAGUZ[0] <= col < self.COL_LAGUZ[1]: return TINT_LAGUZ
        return None

    def populate(self):
        self._suppress = True
        # Delegates: kept on self to prevent GC
        self._delegate_int   = IntDelegate(self.pair.right)
        self._delegate_skill = SkillComboDelegate(self.model, self.pair.right)
        self._delegate_rank  = RankComboDelegate(self.pair.right)
        self.pair.right.setItemDelegate(self._delegate_int)
        for col in range(self.COL_SKILLS[0], self.COL_SKILLS[1]):
            self.pair.right.setItemDelegateForColumn(col, self._delegate_skill)
        for col in range(self.COL_WEAPONS[0], self.COL_WEAPONS[1]):
            self.pair.right.setItemDelegateForColumn(col, self._delegate_rank)

        for i in range(self.model.job_count):
            j = self.model.get_job(i)
            # Frozen
            self.pair.left.setItem(i, 0, make_item(i, editable=False, ro_bg=True))
            self.pair.left.setItem(i, 1, make_item(j['jid'], editable=False, mono=True, ro_bg=True))
            self.pair.left.setItem(i, 2, make_item(j['cn'], editable=False, ro_bg=True))
            self.pair.left.setItem(i, 3, make_item(j['jp'], editable=False, ro_bg=True))
            self.pair.left.setItem(i, 4, make_item(j['en'], editable=False, ro_bg=True))
            # Scrollable
            if self.model.is_promoted_class(i):
                promo_disp = '—'
            else:
                tr = self.model.translations.get('jobs', {}).get(j['promo_jid'], {})
                promo_disp = tr.get('cn') or j['promo_jid'] or '—'
            self.pair.right.setItem(i, self.COL_PROMO, make_item(promo_disp, editable=False, mono=True, bg=RO_BG))
            # Scalar bytes
            self._set_scalar(i, self.COL_MOV, j['mov'], 'mov')
            self._set_scalar(i, self.COL_CON, j['con'], 'con')
            self._set_scalar(i, self.COL_WEIGHT, j['weight'], 'weight')
            self._set_scalar(i, self.COL_SKILL_CAP, j['skill_cap'], 'skill_cap')
            # Skills — editable via dropdown if slot is in reloc table; locked otherwise
            for s in range(5):
                col = self.COL_SKILLS[0] + s
                sid = j['skills'][s] or ''
                cn = self.model.skill_cn(sid)
                display = cn if cn else (sid if sid else '—')
                safe = self.model.is_job_skill_safe(i, s)
                item = make_item(display, editable=safe, mono=True)
                item.setData(Qt.ItemDataRole.UserRole, sid)
                orig_sid = self.model.original_job_skill(i, s) or ''
                if sid != orig_sid:
                    bg = MOD_BG
                else:
                    bg = RO_BG if safe else LOCKED_BG
                item.setBackground(QBrush(bg))
                if not safe:
                    item.setToolTip('原本为空的技能槽 — 引擎重定位表未登记此字段，写入会让游戏崩溃。')
                self.pair.right.setItem(i, col, item)
            # Weapon levels — editable via rank dropdown (note: blocks may be shared)
            wlevels = self.model.get_job_weapon_levels(i)
            for s in range(9):
                col = self.COL_WEAPONS[0] + s
                rank = wlevels[s]
                orig = self.model.original_job_weapon_level(i, s)
                bg = MOD_BG if rank != orig else RO_BG
                self.pair.right.setItem(i, col, make_item(rank, editable=True, mono=True, bg=bg))
            # Stat groups
            for s in range(8):
                self._set_stat(i, self.COL_CAPS[0]+s, j['caps'][s], 'caps', s)
            for s in range(8):
                self._set_stat(i, self.COL_BASES[0]+s, j['bases'][s], 'bases', s)
            for s in range(8):
                self._set_stat(i, self.COL_GROWTHS[0]+s, j['growths'][s], 'growths', s)
            for s in range(8):
                self._set_stat(i, self.COL_LAGUZ[0]+s, j['laguz'][s], 'laguz', s)
        self._suppress = False

    def _set_scalar(self, row, col, value, group):
        orig = self.model.original_job_stat(row, group)
        bg = MOD_BG if value != orig else self._section_bg(col)
        self.pair.right.setItem(row, col, make_item(value, bg=bg))

    def _set_stat(self, row, col, value, group, stat_idx):
        orig = self.model.original_job_stat(row, group, stat_idx)
        bg = MOD_BG if value != orig else self._section_bg(col)
        self.pair.right.setItem(row, col, make_item(value, bg=bg))

    def on_item_changed(self, item):
        if self._suppress: return
        col = item.column()
        row = item.row()
        # Skill column?
        if self.COL_SKILLS[0] <= col < self.COL_SKILLS[1]:
            slot = col - self.COL_SKILLS[0]
            sid = item.data(Qt.ItemDataRole.UserRole) or ''
            try:
                self.model.set_job_skill(row, slot, sid)
            except UnsafePointerEdit as e:
                QMessageBox.warning(self, '不安全的指针修改', str(e))
                # Revert cell
                self._suppress = True
                orig_sid = self.model.original_job_skill(row, slot) or ''
                cn = self.model.skill_cn(orig_sid)
                item.setText(cn or orig_sid or '—')
                item.setData(Qt.ItemDataRole.UserRole, orig_sid)
                self._suppress = False
                return
            except KeyError:
                return
            orig_sid = self.model.original_job_skill(row, slot) or ''
            modified = sid != orig_sid
            item.setBackground(QBrush(MOD_BG if modified else RO_BG))
            self.on_change()
            return
        # Weapon-level rank column?
        if self.COL_WEAPONS[0] <= col < self.COL_WEAPONS[1]:
            slot = col - self.COL_WEAPONS[0]
            rank = (item.text() or '-')[:1]
            if rank not in ['-', 'E', 'D', 'C', 'B', 'A', 'S', '*']:
                return
            # First-edit warning: weapon-level blocks are shared
            if not getattr(self, '_warned_shared_blocks', False):
                import struct
                from fe9_model import JOB_F_WEAPON_LV
                eo = self.model.job_offset(row)
                ptr = struct.unpack('>I', self.model.data[eo+JOB_F_WEAPON_LV:eo+JOB_F_WEAPON_LV+4])[0]
                sharers = self.model.weapon_block_sharers(ptr)
                others = [s for s in sharers if not (s[0] == 'job' and s[1] == row)]
                if others:
                    names = ', '.join(f'{kind} {name}' for kind, _, name in others[:8])
                    if len(others) > 8: names += f' ... 共 {len(others)} 项'
                    res = QMessageBox.warning(
                        self, '武器熟练度块共享',
                        f'此熟练度块被以下条目共享，修改将同时影响它们：\n\n{names}\n\n'
                        f'继续修改? (本警告本次会话只显示一次)',
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Cancel
                    )
                    if res != QMessageBox.StandardButton.Yes:
                        # Revert the cell display
                        orig = self.model.original_job_weapon_level(row, slot)
                        self._suppress = True
                        item.setText(orig)
                        item.setBackground(QBrush(RO_BG))
                        self._suppress = False
                        return
                self._warned_shared_blocks = True
            try:
                self.model.set_job_weapon_level(row, slot, rank)
            except RuntimeError:
                return
            orig = self.model.original_job_weapon_level(row, slot)
            item.setBackground(QBrush(MOD_BG if rank != orig else RO_BG))
            self.on_change()
            return
        meta = self._scalar_meta(col)
        if meta is None: return
        group, s = meta
        try:
            value = int(item.text())
        except ValueError:
            return
        self.model.set_job_stat(row, group, s, value)
        orig = self.model.original_job_stat(row, group, s)
        item.setBackground(QBrush(MOD_BG if value != orig else self._section_bg(col)))
        self.on_change()

    def apply_filter(self, text):
        text = text.strip().lower()
        for i in range(self.model.job_count):
            j = self.model.get_job(i)
            haystack = ' '.join([j['jid'], j['cn'], j['jp'], j['en']]).lower()
            visible = (not text) or (text in haystack)
            self.pair.set_row_visible(i, visible)


class PersonTab(QWidget):
    FROZEN_HEADERS = ['#', 'PID', '中文', '日文', 'English']
    # Right side columns:
    #   0: 头像  1: 初始职业  2: 属性
    #   3-5: 技能1/2/3
    #   6: 等级  7: 体格  8: 重量  9: 兽化槽
    #   10-17: 基·HP..基·魔防 (signed s8)
    #   18-25: 成·HP..成·魔防 (unsigned %)
    SCROLL_HEADERS = (
        ['头像', '初始职业', '属性']
        + [f'技能{i+1}' for i in range(3)]
        + ['等级', '体格', '重量', '兽化槽']
        + [f'熟·{w}' for w in WEAPON_TYPES_CN]
        + [f'基·{s}' for s in STAT_CN]
        + [f'成·{s}' for s in STAT_CN]
    )
    COL_PORTRAIT = 0
    COL_CLASS = 1
    COL_AFFINITY = 2
    COL_SKILLS = (3, 6)
    COL_LV = 6
    COL_BUILD = 7
    COL_WEIGHT = 8
    COL_LAGUZ = 9
    COL_WEAPONS = (10, 19)
    COL_BASES = (19, 27)
    COL_GROWTHS = (27, 35)

    def __init__(self, model: FE9Data, on_change):
        super().__init__()
        self.model = model
        self.on_change = on_change

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        topbar = QHBoxLayout()
        topbar.addWidget(QLabel('显示列:'))
        self.cb_pid = QCheckBox('PID'); self.cb_pid.setChecked(True)
        self.cb_cn  = QCheckBox('中文'); self.cb_cn.setChecked(True)
        self.cb_jp  = QCheckBox('日文'); self.cb_jp.setChecked(True)
        self.cb_en  = QCheckBox('English'); self.cb_en.setChecked(True)
        for cb in (self.cb_pid, self.cb_cn, self.cb_jp, self.cb_en):
            cb.toggled.connect(self.apply_col_visibility)
            topbar.addWidget(cb)
        topbar.addSpacing(20)
        topbar.addWidget(QLabel('筛选:'))
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText('PID / 中文 / 日文 / English')
        self.filter_box.textChanged.connect(self.apply_filter)
        topbar.addWidget(self.filter_box, 1)
        layout.addLayout(topbar)

        self.pair = FrozenTablePair(model.person_count, self.FROZEN_HEADERS, self.SCROLL_HEADERS)
        layout.addWidget(self.pair)

        self._suppress = False
        self.populate()
        self.pair.right.itemChanged.connect(self.on_item_changed)
        self.pair.configure_columns()

    def apply_col_visibility(self):
        self.pair.set_left_col_visible(1, self.cb_pid.isChecked())
        self.pair.set_left_col_visible(2, self.cb_cn.isChecked())
        self.pair.set_left_col_visible(3, self.cb_jp.isChecked())
        self.pair.set_left_col_visible(4, self.cb_en.isChecked())

    def _scalar_meta(self, col):
        if col == self.COL_LV: return ('level', 0)
        if col == self.COL_BUILD: return ('build', 0)
        if col == self.COL_WEIGHT: return ('weight', 0)
        if col == self.COL_LAGUZ: return ('laguz_gauge', 0)
        if self.COL_WEAPONS[0] <= col < self.COL_WEAPONS[1]:
            return None  # weapon levels are read-only
        if self.COL_BASES[0] <= col < self.COL_BASES[1]:
            return ('bases', col - self.COL_BASES[0])
        if self.COL_GROWTHS[0] <= col < self.COL_GROWTHS[1]:
            return ('growths', col - self.COL_GROWTHS[0])
        return None

    def _section_bg(self, col):
        if col in (self.COL_PORTRAIT, self.COL_CLASS, self.COL_AFFINITY): return RO_BG
        if self.COL_SKILLS[0] <= col < self.COL_SKILLS[1]: return RO_BG
        if col in (self.COL_LV, self.COL_BUILD, self.COL_WEIGHT, self.COL_LAGUZ): return TINT_SCALAR
        if self.COL_WEAPONS[0] <= col < self.COL_WEAPONS[1]: return RO_BG
        if self.COL_BASES[0] <= col < self.COL_BASES[1]: return TINT_BASES
        if self.COL_GROWTHS[0] <= col < self.COL_GROWTHS[1]: return TINT_GROWTHS
        return None

    def populate(self):
        self._suppress = True
        # Delegates: keep as instance attrs so PyQt doesn't garbage-collect them
        self._delegate_int    = IntDelegate(self.pair.right)
        self._delegate_signed = SignedIntDelegate(self.pair.right)
        self._delegate_skill  = SkillComboDelegate(self.model, self.pair.right)
        self.pair.right.setItemDelegate(self._delegate_int)
        # Signed delegate for bases AND build/weight columns
        for col in range(self.COL_BASES[0], self.COL_BASES[1]):
            self.pair.right.setItemDelegateForColumn(col, self._delegate_signed)
        self.pair.right.setItemDelegateForColumn(self.COL_BUILD, self._delegate_signed)
        self.pair.right.setItemDelegateForColumn(self.COL_WEIGHT, self._delegate_signed)
        # Combo dropdown delegate for skill columns
        for col in range(self.COL_SKILLS[0], self.COL_SKILLS[1]):
            self.pair.right.setItemDelegateForColumn(col, self._delegate_skill)

        for i in range(self.model.person_count):
            p = self.model.get_person(i)
            # Frozen left
            self.pair.left.setItem(i, 0, make_item(i, editable=False, ro_bg=True))
            self.pair.left.setItem(i, 1, make_item(p['pid'], editable=False, mono=True, ro_bg=True))
            self.pair.left.setItem(i, 2, make_item(p['cn'], editable=False, ro_bg=True))
            self.pair.left.setItem(i, 3, make_item(p['jp'], editable=False, ro_bg=True))
            self.pair.left.setItem(i, 4, make_item(p['en'], editable=False, ro_bg=True))

            # Read-only string columns
            self.pair.right.setItem(i, self.COL_PORTRAIT, make_item(p['portrait'] or '—', editable=False, mono=True, bg=RO_BG))
            cls_tr = self.model.translations.get('jobs', {}).get(p['class_jid'], {})
            cls_disp = cls_tr.get('cn') or p['class_jid'] or '—'
            self.pair.right.setItem(i, self.COL_CLASS, make_item(cls_disp, editable=False, mono=True, bg=RO_BG))
            # Affinity: show CN translation
            aff = p['affinity']
            aff_cn = self.model.affinity_cn(aff)
            aff_disp = aff_cn or aff or '—'
            self.pair.right.setItem(i, self.COL_AFFINITY, make_item(aff_disp, editable=False, bg=RO_BG))

            # Skills (editable via dropdown if slot in reloc table; locked otherwise)
            for s in range(3):
                col = self.COL_SKILLS[0] + s
                sid = p['skills'][s]
                cn = self.model.skill_cn(sid)
                display = cn if cn else (sid if sid else '—')
                safe = self.model.is_person_skill_safe(i, s)
                item = make_item(display, editable=safe, mono=True)
                item.setData(Qt.ItemDataRole.UserRole, sid)
                orig_sid = self.model.original_person_skill(i, s) or ''
                if (sid or '') != orig_sid:
                    bg = MOD_BG
                else:
                    bg = RO_BG if safe else LOCKED_BG
                item.setBackground(QBrush(bg))
                if not safe:
                    item.setToolTip('原本为空的技能槽 — 引擎重定位表未登记此字段，写入会让游戏崩溃。')
                self.pair.right.setItem(i, col, item)

            # Editable scalars
            self._set_scalar(i, self.COL_LV, p['level'], 'level')
            self._set_scalar(i, self.COL_BUILD, p['build'], 'build')
            self._set_scalar(i, self.COL_WEIGHT, p['weight'], 'weight')
            self._set_scalar(i, self.COL_LAGUZ, p['laguz_gauge'], 'laguz_gauge')

            # Weapon levels (read-only)
            wlevels = self.model.get_person_weapon_levels(i)
            for s in range(9):
                col = self.COL_WEAPONS[0] + s
                self.pair.right.setItem(i, col, make_item(wlevels[s], editable=False, mono=True, bg=RO_BG))

            # Bases (signed) and growths
            for s in range(8):
                self._set_stat(i, self.COL_BASES[0]+s, p['bases'][s], 'bases', s)
            for s in range(8):
                self._set_stat(i, self.COL_GROWTHS[0]+s, p['growths'][s], 'growths', s)
        self._suppress = False

    def _set_scalar(self, row, col, value, group):
        orig = self.model.original_person_stat(row, group)
        bg = MOD_BG if value != orig else self._section_bg(col)
        self.pair.right.setItem(row, col, make_item(value, bg=bg))

    def _set_stat(self, row, col, value, group, stat_idx):
        orig = self.model.original_person_stat(row, group, stat_idx)
        bg = MOD_BG if value != orig else self._section_bg(col)
        self.pair.right.setItem(row, col, make_item(value, bg=bg))

    def on_item_changed(self, item):
        if self._suppress: return
        col = item.column()
        row = item.row()
        # Skill column?
        if self.COL_SKILLS[0] <= col < self.COL_SKILLS[1]:
            slot = col - self.COL_SKILLS[0]
            sid = item.data(Qt.ItemDataRole.UserRole) or ''
            try:
                self.model.set_person_skill(row, slot, sid)
            except UnsafePointerEdit as e:
                QMessageBox.warning(self, '不安全的指针修改', str(e))
                self._suppress = True
                orig_sid = self.model.original_person_skill(row, slot) or ''
                cn = self.model.skill_cn(orig_sid)
                item.setText(cn or orig_sid or '—')
                item.setData(Qt.ItemDataRole.UserRole, orig_sid)
                self._suppress = False
                return
            except KeyError:
                return
            orig_sid = self.model.original_person_skill(row, slot) or ''
            modified = sid != orig_sid
            item.setBackground(QBrush(MOD_BG if modified else RO_BG))
            self.on_change()
            return
        # Other (scalar / stat group) columns
        meta = self._scalar_meta(col)
        if meta is None: return
        group, s = meta
        try:
            value = int(item.text())
        except ValueError:
            return
        self.model.set_person_stat(row, group, s, value)
        orig = self.model.original_person_stat(row, group, s)
        item.setBackground(QBrush(MOD_BG if value != orig else self._section_bg(col)))
        self.on_change()

    def apply_filter(self, text):
        text = text.strip().lower()
        for i in range(self.model.person_count):
            p = self.model.get_person(i)
            haystack = ' '.join([p['pid'], p['cn'], p['jp'], p['en']]).lower()
            visible = (not text) or (text in haystack)
            self.pair.set_row_visible(i, visible)


class ItemTab(QWidget):
    FROZEN_HEADERS = ['#', 'IID', '中文', 'MIID', '类型']
    SCROLL_HEADERS = (
        ['等级', '单价g', '耐久', '攻击', '命中', '重量', '必杀', '最小射程', '最大射程', '武器经验']
        + [f'特性{i+1}' for i in range(6)]
        + [f'特效{i+1}' for i in range(2)]
        + [f'加·{s}' for s in STAT_CN]
        + [f'成·{s}' for s in STAT_CN]
    )
    COL_RANK      = 0
    COL_COST      = 1
    COL_USES      = 2
    COL_MT        = 3
    COL_HIT       = 4
    COL_WT        = 5
    COL_CRIT      = 6
    COL_RANGE_MIN = 7
    COL_RANGE_MAX = 8
    COL_WEXP      = 9
    COL_TRAITS    = (10, 16)
    COL_EFFECTS   = (16, 18)
    COL_BONUSES   = (18, 26)
    COL_GROWTH    = (26, 34)

    SCALAR_MAP = {
        COL_COST: 'cost_per', COL_USES: 'uses', COL_MT: 'mt', COL_HIT: 'hit',
        COL_WT: 'wt', COL_CRIT: 'crit', COL_RANGE_MIN: 'range_min',
        COL_RANGE_MAX: 'range_max', COL_WEXP: 'wexp',
    }

    def __init__(self, model: FE9Data, on_change):
        super().__init__()
        self.model = model
        self.on_change = on_change
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        topbar = QHBoxLayout()
        topbar.addWidget(QLabel('显示列:'))
        self.cb_iid  = QCheckBox('IID');  self.cb_iid.setChecked(True)
        self.cb_cn   = QCheckBox('中文'); self.cb_cn.setChecked(True)
        self.cb_miid = QCheckBox('MIID'); self.cb_miid.setChecked(False)
        self.cb_type = QCheckBox('类型'); self.cb_type.setChecked(True)
        for cb in (self.cb_iid, self.cb_cn, self.cb_miid, self.cb_type):
            cb.toggled.connect(self.apply_col_visibility)
            topbar.addWidget(cb)
        topbar.addSpacing(20)
        topbar.addWidget(QLabel('筛选:'))
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText('IID / 中文 / 类型 (sword/lance/.../staff/item)')
        self.filter_box.textChanged.connect(self.apply_filter)
        topbar.addWidget(self.filter_box, 1)
        layout.addLayout(topbar)

        self.pair = FrozenTablePair(model.item_count, self.FROZEN_HEADERS, self.SCROLL_HEADERS)
        layout.addWidget(self.pair)

        self._suppress = False
        self.populate()
        self.pair.right.itemChanged.connect(self.on_item_changed)
        self.pair.configure_columns()

    def apply_col_visibility(self):
        self.pair.set_left_col_visible(1, self.cb_iid.isChecked())
        self.pair.set_left_col_visible(2, self.cb_cn.isChecked())
        self.pair.set_left_col_visible(3, self.cb_miid.isChecked())
        self.pair.set_left_col_visible(4, self.cb_type.isChecked())

    def _scalar_meta(self, col):
        if col in self.SCALAR_MAP:
            return (self.SCALAR_MAP[col], 0)
        if self.COL_BONUSES[0] <= col < self.COL_BONUSES[1]:
            return ('bonuses', col - self.COL_BONUSES[0])
        if self.COL_GROWTH[0] <= col < self.COL_GROWTH[1]:
            return ('growth', col - self.COL_GROWTH[0])
        return None

    def _section_bg(self, col):
        if col == self.COL_RANK: return RO_BG
        if col in self.SCALAR_MAP: return TINT_SCALAR
        if self.COL_TRAITS[0] <= col < self.COL_TRAITS[1]: return RO_BG
        if self.COL_EFFECTS[0] <= col < self.COL_EFFECTS[1]: return RO_BG
        if self.COL_BONUSES[0] <= col < self.COL_BONUSES[1]: return TINT_BASES
        if self.COL_GROWTH[0] <= col < self.COL_GROWTH[1]: return TINT_GROWTHS
        return None

    def populate(self):
        self._suppress = True
        self._delegate_int = IntDelegate(self.pair.right)
        self._delegate_signed = SignedIntDelegate(self.pair.right)
        self._delegate_trait = TraitComboDelegate(self.model, self.pair.right)
        self._delegate_effect = EffectComboDelegate(self.model, self.pair.right)
        self.pair.right.setItemDelegate(self._delegate_int)
        for col in range(self.COL_TRAITS[0], self.COL_TRAITS[1]):
            self.pair.right.setItemDelegateForColumn(col, self._delegate_trait)
        for col in range(self.COL_EFFECTS[0], self.COL_EFFECTS[1]):
            self.pair.right.setItemDelegateForColumn(col, self._delegate_effect)
        for col in range(self.COL_GROWTH[0], self.COL_GROWTH[1]):
            self.pair.right.setItemDelegateForColumn(col, self._delegate_signed)

        for i in range(self.model.item_count):
            it = self.model.get_item(i)
            self.pair.left.setItem(i, 0, make_item(i, editable=False, ro_bg=True))
            self.pair.left.setItem(i, 1, make_item(it['iid'], editable=False, mono=True, ro_bg=True))
            self.pair.left.setItem(i, 2, make_item(it['cn'], editable=False, ro_bg=True))
            self.pair.left.setItem(i, 3, make_item(it['miid'], editable=False, mono=True, ro_bg=True))
            self.pair.left.setItem(i, 4, make_item(it['type'] or '—', editable=False, mono=True, ro_bg=True))

            self.pair.right.setItem(i, self.COL_RANK, make_item(it['rank'] or '—', editable=False, mono=True, bg=RO_BG))
            self._set_scalar(i, self.COL_COST,      it['cost_per'], 'cost_per')
            self._set_scalar(i, self.COL_USES,      it['uses'],     'uses')
            self._set_scalar(i, self.COL_MT,        it['mt'],       'mt')
            self._set_scalar(i, self.COL_HIT,       it['hit'],      'hit')
            self._set_scalar(i, self.COL_WT,        it['wt'],       'wt')
            self._set_scalar(i, self.COL_CRIT,      it['crit'],     'crit')
            self._set_scalar(i, self.COL_RANGE_MIN, it['range_min'],'range_min')
            self._set_scalar(i, self.COL_RANGE_MAX, it['range_max'],'range_max')
            self._set_scalar(i, self.COL_WEXP,      it['wexp'],     'wexp')

            for s in range(6):
                col = self.COL_TRAITS[0] + s
                v = it['traits'][s] or ''
                cn = self.model.item_trait_cn(v)
                disp = cn or v or '—'
                safe = self.model.is_item_trait_safe(i, s)
                item = make_item(disp, editable=safe)
                item.setData(Qt.ItemDataRole.UserRole, v)
                orig = self.model.original_item_trait(i, s) or ''
                if v != orig:
                    bg = MOD_BG
                else:
                    bg = RO_BG if safe else LOCKED_BG
                item.setBackground(QBrush(bg))
                if not safe:
                    item.setToolTip('原本为空的特性槽 — 引擎重定位表未登记此字段，写入会让游戏崩溃。')
                self.pair.right.setItem(i, col, item)
            for s in range(2):
                col = self.COL_EFFECTS[0] + s
                v = it['effects'][s] or ''
                cn = self.model.item_effect_cn(v)
                disp = cn or v or '—'
                safe = self.model.is_item_effect_safe(i, s)
                item = make_item(disp, editable=safe)
                item.setData(Qt.ItemDataRole.UserRole, v)
                orig = self.model.original_item_effect(i, s) or ''
                if v != orig:
                    bg = MOD_BG
                else:
                    bg = RO_BG if safe else LOCKED_BG
                item.setBackground(QBrush(bg))
                if not safe:
                    item.setToolTip('原本为空的特效槽 — 引擎重定位表未登记此字段，写入会让游戏崩溃。')
                self.pair.right.setItem(i, col, item)
            for s in range(8):
                self._set_stat(i, self.COL_BONUSES[0]+s, it['bonuses'][s], 'bonuses', s)
            for s in range(8):
                self._set_stat(i, self.COL_GROWTH[0]+s, it['growth'][s], 'growth', s)
        self._suppress = False

    def _set_scalar(self, row, col, value, group):
        orig = self.model.original_item_stat(row, group)
        bg = MOD_BG if value != orig else self._section_bg(col)
        self.pair.right.setItem(row, col, make_item(value, bg=bg))

    def _set_stat(self, row, col, value, group, stat_idx):
        orig = self.model.original_item_stat(row, group, stat_idx)
        bg = MOD_BG if value != orig else self._section_bg(col)
        self.pair.right.setItem(row, col, make_item(value, bg=bg))

    def on_item_changed(self, item):
        if self._suppress: return
        col = item.column()
        row = item.row()
        # Trait column?
        if self.COL_TRAITS[0] <= col < self.COL_TRAITS[1]:
            slot = col - self.COL_TRAITS[0]
            name = item.data(Qt.ItemDataRole.UserRole) or ''
            try:
                self.model.set_item_trait(row, slot, name)
            except UnsafePointerEdit as e:
                QMessageBox.warning(self, '不安全的指针修改', str(e))
                self._suppress = True
                orig = self.model.original_item_trait(row, slot) or ''
                cn = self.model.item_trait_cn(orig)
                item.setText(cn or orig or '—')
                item.setData(Qt.ItemDataRole.UserRole, orig)
                self._suppress = False
                return
            except KeyError:
                return
            orig = self.model.original_item_trait(row, slot) or ''
            item.setBackground(QBrush(MOD_BG if name != orig else RO_BG))
            self.on_change()
            return
        # Effect column?
        if self.COL_EFFECTS[0] <= col < self.COL_EFFECTS[1]:
            slot = col - self.COL_EFFECTS[0]
            name = item.data(Qt.ItemDataRole.UserRole) or ''
            try:
                self.model.set_item_effect(row, slot, name)
            except UnsafePointerEdit as e:
                QMessageBox.warning(self, '不安全的指针修改', str(e))
                self._suppress = True
                orig = self.model.original_item_effect(row, slot) or ''
                cn = self.model.item_effect_cn(orig)
                item.setText(cn or orig or '—')
                item.setData(Qt.ItemDataRole.UserRole, orig)
                self._suppress = False
                return
            except KeyError:
                return
            orig = self.model.original_item_effect(row, slot) or ''
            item.setBackground(QBrush(MOD_BG if name != orig else RO_BG))
            self.on_change()
            return
        meta = self._scalar_meta(col)
        if meta is None: return
        group, s = meta
        try:
            value = int(item.text())
        except ValueError:
            return
        self.model.set_item_stat(row, group, s, value)
        orig = self.model.original_item_stat(row, group, s)
        item.setBackground(QBrush(MOD_BG if value != orig else self._section_bg(col)))
        self.on_change()

    def apply_filter(self, text):
        text = text.strip().lower()
        for i in range(self.model.item_count):
            it = self.model.get_item(i)
            haystack = ' '.join([it['iid'], it['cn'], it['miid'], it['type']]).lower()
            visible = (not text) or (text in haystack)
            self.pair.set_row_visible(i, visible)


class RelianceTab(QWidget):
    """Support data: flat row-per-pair view."""
    FROZEN_HEADERS = ['#', '主角 PID', '主角 中文', '槽']
    SCROLL_HEADERS = ['伙伴', 'C 奖励', 'B 奖励', 'A 奖励']
    COL_PARTNER = 0
    COL_C = 1
    COL_B = 2
    COL_A = 3

    def __init__(self, model: FE9Data, on_change):
        super().__init__()
        self.model = model
        self.on_change = on_change

        # Build flat (entry_idx, slot_idx) row map
        self._rows = []   # list of (entry_idx, slot_idx)
        for i in range(model.reliance_count):
            r = model.get_reliance(i)
            for s in range(r['count']):
                self._rows.append((i, s))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        topbar = QHBoxLayout()
        topbar.addWidget(QLabel('筛选 (主角/伙伴 中文/PID):'))
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText('如 IKE / 艾克 / TIAMAT')
        self.filter_box.textChanged.connect(self.apply_filter)
        topbar.addWidget(self.filter_box, 1)
        layout.addLayout(topbar)

        self.pair = FrozenTablePair(len(self._rows), self.FROZEN_HEADERS, self.SCROLL_HEADERS)
        layout.addWidget(self.pair)

        self._suppress = False
        self.populate()
        self.pair.right.itemChanged.connect(self.on_item_changed)
        self.pair.configure_columns()

    def _scalar_meta(self, col):
        if col == self.COL_C: return 'C'
        if col == self.COL_B: return 'B'
        if col == self.COL_A: return 'A'
        return None

    def _section_bg(self, col):
        if col == self.COL_PARTNER: return RO_BG
        return TINT_SCALAR

    def populate(self):
        self._suppress = True
        self._delegate_int = IntDelegate(self.pair.right)
        self._delegate_pid = PidComboDelegate(self.model, self.pair.right)
        self.pair.right.setItemDelegate(self._delegate_int)
        self.pair.right.setItemDelegateForColumn(self.COL_PARTNER, self._delegate_pid)

        for row, (ei, si) in enumerate(self._rows):
            r = self.model.get_reliance(ei)
            slot = r['slots'][si]
            main_cn = self.model.translations.get('persons', {}).get(r['main_pid'], {}).get('cn', '')
            partner_pid = slot['partner_pid']
            partner_cn = self.model.translations.get('persons', {}).get(partner_pid, {}).get('cn', '')

            self.pair.left.setItem(row, 0, make_item(ei, editable=False, ro_bg=True))
            self.pair.left.setItem(row, 1, make_item(r['main_pid'], editable=False, mono=True, ro_bg=True))
            self.pair.left.setItem(row, 2, make_item(main_cn, editable=False, ro_bg=True))
            self.pair.left.setItem(row, 3, make_item(si, editable=False, ro_bg=True))

            # Partner combo
            partner_disp = f'{partner_cn}  [{partner_pid}]' if partner_cn else (partner_pid or '—')
            safe = self.model.is_pointer_field_safe(slot['slot_field_off'])
            item = make_item(partner_disp, editable=safe)
            item.setData(Qt.ItemDataRole.UserRole, partner_pid)
            orig_partner = self.model.original_reliance(ei)['slots'][si]['partner_pid']
            if partner_pid != orig_partner:
                bg = MOD_BG
            else:
                bg = RO_BG if safe else LOCKED_BG
            item.setBackground(QBrush(bg))
            if not safe:
                item.setToolTip('原本为空的伙伴槽 — 引擎重定位表未登记此字段，写入会让游戏崩溃。')
            self.pair.right.setItem(row, self.COL_PARTNER, item)

            # Bonus cells
            for col, key in [(self.COL_C, 'bonus_c'), (self.COL_B, 'bonus_b'), (self.COL_A, 'bonus_a')]:
                v = slot[key]
                level = {self.COL_C: 'C', self.COL_B: 'B', self.COL_A: 'A'}[col]
                orig_b = self.model.original_reliance(ei)['slots'][si]
                orig_v = orig_b['bonus_' + level.lower()]
                bg = MOD_BG if v != orig_v else TINT_SCALAR
                self.pair.right.setItem(row, col, make_item(v, bg=bg))
        self._suppress = False

    def on_item_changed(self, item):
        if self._suppress: return
        col = item.column()
        row = item.row()
        ei, si = self._rows[row]
        # Partner column?
        if col == self.COL_PARTNER:
            new_pid = item.data(Qt.ItemDataRole.UserRole) or ''
            try:
                self.model.set_reliance_partner(ei, si, new_pid)
            except UnsafePointerEdit as e:
                QMessageBox.warning(self, '不安全的指针修改', str(e))
                self._suppress = True
                orig_partner = self.model.original_reliance(ei)['slots'][si]['partner_pid']
                tr = self.model.translations.get('persons', {}).get(orig_partner, {})
                cn = tr.get('cn', '')
                disp = f'{cn}  [{orig_partner}]' if cn else (orig_partner or '—')
                item.setText(disp)
                item.setData(Qt.ItemDataRole.UserRole, orig_partner)
                self._suppress = False
                return
            except KeyError:
                return
            orig_partner = self.model.original_reliance(ei)['slots'][si]['partner_pid']
            item.setBackground(QBrush(MOD_BG if new_pid != orig_partner else RO_BG))
            self.on_change()
            return
        # Bonus column
        level = self._scalar_meta(col)
        if level is None: return
        try:
            value = int(item.text())
        except ValueError:
            return
        self.model.set_reliance_bonus(ei, si, level, value)
        orig_v = self.model.original_reliance(ei)['slots'][si]['bonus_' + level.lower()]
        item.setBackground(QBrush(MOD_BG if value != orig_v else TINT_SCALAR))
        self.on_change()

    def apply_filter(self, text):
        text = text.strip().lower()
        for row, (ei, si) in enumerate(self._rows):
            r = self.model.get_reliance(ei)
            partner_pid = r['slots'][si]['partner_pid']
            main_cn = self.model.translations.get('persons', {}).get(r['main_pid'], {}).get('cn', '')
            partner_cn = self.model.translations.get('persons', {}).get(partner_pid, {}).get('cn', '')
            haystack = ' '.join([r['main_pid'], main_cn, partner_pid, partner_cn]).lower()
            visible = (not text) or (text in haystack)
            self.pair.set_row_visible(row, visible)


class DivineTab(QWidget):
    """Affinity bonus table — 9 affinities × (atk, def, hit, avo) bytes.
    Each byte stored as 2× the in-game display value (e.g. byte 5 = +2.5)."""
    HEADERS = ['#', '内部名', '中文', '攻击', '防御', '命中', '回避']
    COL_NAME = 1
    COL_CN   = 2
    COL_ATK  = 3
    COL_DEF  = 4
    COL_HIT  = 5
    COL_AVO  = 6
    SCALAR_MAP = {COL_ATK: 'atk', COL_DEF: 'def', COL_HIT: 'hit', COL_AVO: 'avo'}

    def __init__(self, model: FE9Data, on_change):
        super().__init__()
        self.model = model
        self.on_change = on_change
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        info = QLabel('每条 affinity 每升一级支援，两边角色都获得这里所列的奖励。'
                      '存储值 = 实际显示数值 × 2 (例如 5 表示 +2.5)。'
                      '游戏 8 个属性 + "none" 占位。')
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget(model.divine_count, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setItemDelegate(IntDelegate())
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.SelectedClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        layout.addWidget(self.table)

        self._suppress = False
        self.populate()
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def populate(self):
        self._suppress = True
        for i in range(self.model.divine_count):
            div = self.model.get_divine(i)
            orig = self.model.original_divine(i)
            cn = self.model.affinity_cn(div['name'])
            self.table.setItem(i, 0, make_item(i, editable=False, ro_bg=True))
            self.table.setItem(i, self.COL_NAME, make_item(div['name'], editable=False, mono=True, ro_bg=True))
            self.table.setItem(i, self.COL_CN, make_item(cn, editable=False, ro_bg=True))
            for col, key in self.SCALAR_MAP.items():
                v = div[key]
                ov = orig[key]
                disp = f'{v}  (+{v/2:.1f})'
                item = make_item(disp, editable=True)
                item.setData(Qt.ItemDataRole.UserRole, v)
                item.setBackground(QBrush(MOD_BG if v != ov else TINT_SCALAR))
                self.table.setItem(i, col, item)
        self._suppress = False

    def on_item_changed(self, item):
        if self._suppress: return
        col = item.column()
        if col not in self.SCALAR_MAP:
            return
        # Parse value: accept either integer ("5") or "5  (+2.5)"
        text = item.text().strip()
        try:
            value = int(text.split()[0]) if text else 0
        except ValueError:
            return
        row = item.row()
        field = self.SCALAR_MAP[col]
        self.model.set_divine_field(row, field, value)
        orig = self.model.original_divine(row)
        ov = orig[field]
        # Update display to canonical "X  (+X.X)" form (and bg)
        self._suppress = True
        item.setText(f'{value}  (+{value/2:.1f})')
        item.setData(Qt.ItemDataRole.UserRole, value)
        item.setBackground(QBrush(MOD_BG if value != ov else TINT_SCALAR))
        self._suppress = False
        self.on_change()


class KiznaTypeDelegate(NamedComboDelegate):
    """Dropdown for fixed-support type byte (1=必杀加成, 2=对话型)."""
    def _load_options(self):
        return [(1, '必杀加成 (1)'), (2, '对话型 (2)')]
    def _lookup_cn(self, key):
        return {1: '必杀加成', 2: '对话型'}.get(key, '')


class KiznaTab(QWidget):
    """Fixed support / 絆 / KiznaData — 36 entries × 12 bytes."""
    FROZEN_HEADERS = ['#', '角色 A', '角色 A 中文', '角色 B', '角色 B 中文']
    SCROLL_HEADERS = ['类型', '数值', '说明']
    COL_TYPE  = 0
    COL_VALUE = 1
    COL_DESC  = 2

    def __init__(self, model: FE9Data, on_change):
        super().__init__()
        self.model = model
        self.on_change = on_change

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        topbar = QHBoxLayout()
        topbar.addWidget(QLabel('筛选 (角色 PID/中文):'))
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText('如 IKE / 艾克 / GREIL')
        self.filter_box.textChanged.connect(self.apply_filter)
        topbar.addWidget(self.filter_box, 1)
        layout.addLayout(topbar)

        self.pair = FrozenTablePair(model.kizna_count, self.FROZEN_HEADERS, self.SCROLL_HEADERS)
        layout.addWidget(self.pair)

        self._suppress = False
        self.populate()
        self.pair.right.itemChanged.connect(self.on_item_changed)
        self.pair.left.itemChanged.connect(self.on_left_item_changed)
        self.pair.configure_columns()

    def populate(self):
        self._suppress = True
        self._delegate_int  = IntDelegate(self.pair.right)
        self._delegate_pid  = PidComboDelegate(self.model, self.pair.left)
        self._delegate_type = KiznaTypeDelegate(self.model, self.pair.right)
        self.pair.left.setItemDelegateForColumn(1, self._delegate_pid)
        self.pair.left.setItemDelegateForColumn(3, self._delegate_pid)
        self.pair.right.setItemDelegate(self._delegate_int)
        self.pair.right.setItemDelegateForColumn(self.COL_TYPE, self._delegate_type)

        for i in range(self.model.kizna_count):
            k = self.model.get_kizna(i)
            orig = self.model.original_kizna(i)
            cn_a = self.model.translations.get('persons', {}).get(k['pid_a'], {}).get('cn', '')
            cn_b = self.model.translations.get('persons', {}).get(k['pid_b'], {}).get('cn', '')

            self.pair.left.setItem(i, 0, make_item(i, editable=False, ro_bg=True))

            # PID A — editable dropdown
            disp_a = f'{cn_a}  [{k["pid_a"]}]' if cn_a else (k['pid_a'] or '—')
            safe_a = self.model.is_pointer_field_safe(k['offset'])
            ia = make_item(disp_a, editable=safe_a, mono=True)
            ia.setData(Qt.ItemDataRole.UserRole, k['pid_a'])
            ia.setBackground(QBrush(MOD_BG if k['pid_a'] != orig['pid_a'] else (RO_BG if safe_a else LOCKED_BG)))
            self.pair.left.setItem(i, 1, ia)
            self.pair.left.setItem(i, 2, make_item(cn_a, editable=False, ro_bg=True))

            disp_b = f'{cn_b}  [{k["pid_b"]}]' if cn_b else (k['pid_b'] or '—')
            safe_b = self.model.is_pointer_field_safe(k['offset'] + 4)
            ib = make_item(disp_b, editable=safe_b, mono=True)
            ib.setData(Qt.ItemDataRole.UserRole, k['pid_b'])
            ib.setBackground(QBrush(MOD_BG if k['pid_b'] != orig['pid_b'] else (RO_BG if safe_b else LOCKED_BG)))
            self.pair.left.setItem(i, 3, ib)
            self.pair.left.setItem(i, 4, make_item(cn_b, editable=False, ro_bg=True))

            # Right: type / value / desc
            t_disp = '必杀加成 (1)' if k['bonus_type'] == 1 else ('对话型 (2)' if k['bonus_type'] == 2 else f'未知 ({k["bonus_type"]})')
            t_item = make_item(t_disp, editable=True)
            t_item.setData(Qt.ItemDataRole.UserRole, k['bonus_type'])
            t_item.setBackground(QBrush(MOD_BG if k['bonus_type'] != orig['bonus_type'] else TINT_SCALAR))
            self.pair.right.setItem(i, self.COL_TYPE, t_item)

            v_item = make_item(k['bonus_value'], editable=True)
            v_item.setBackground(QBrush(MOD_BG if k['bonus_value'] != orig['bonus_value'] else TINT_SCALAR))
            self.pair.right.setItem(i, self.COL_VALUE, v_item)

            # Description (read-only, derived)
            desc = ''
            if k['bonus_type'] == 1: desc = f'必杀 +{k["bonus_value"]}'
            elif k['bonus_type'] == 2: desc = '对话/家族关系（无战斗加成）'
            self.pair.right.setItem(i, self.COL_DESC, make_item(desc, editable=False, bg=RO_BG))
        self._suppress = False

    def on_left_item_changed(self, item):
        if self._suppress: return
        col = item.column()
        if col not in (1, 3): return
        row = item.row()
        which = 'a' if col == 1 else 'b'
        new_pid = item.data(Qt.ItemDataRole.UserRole) or ''
        try:
            self.model.set_kizna_partner(row, which, new_pid)
        except UnsafePointerEdit as e:
            QMessageBox.warning(self, '不安全的指针修改', str(e))
            self._suppress = True
            orig = self.model.original_kizna(row)
            orig_pid = orig['pid_a' if which == 'a' else 'pid_b']
            tr = self.model.translations.get('persons', {}).get(orig_pid, {})
            cn = tr.get('cn', '')
            disp = f'{cn}  [{orig_pid}]' if cn else (orig_pid or '—')
            item.setText(disp)
            item.setData(Qt.ItemDataRole.UserRole, orig_pid)
            self._suppress = False
            return
        except KeyError:
            return
        orig = self.model.original_kizna(row)
        orig_pid = orig['pid_a' if which == 'a' else 'pid_b']
        item.setBackground(QBrush(MOD_BG if new_pid != orig_pid else RO_BG))
        # Update CN display column
        self._suppress = True
        cn = self.model.translations.get('persons', {}).get(new_pid, {}).get('cn', '')
        cn_col = 2 if col == 1 else 4
        cn_cell = self.pair.left.item(row, cn_col)
        if cn_cell: cn_cell.setText(cn)
        self._suppress = False
        self.on_change()

    def on_item_changed(self, item):
        if self._suppress: return
        col = item.column()
        row = item.row()
        if col == self.COL_TYPE:
            new_t = item.data(Qt.ItemDataRole.UserRole)
            if new_t is None:
                # Try to parse "必杀加成 (1)" or "对话型 (2)"
                try:
                    new_t = int(item.text().split('(')[1].rstrip(')').strip())
                except: return
            self.model.set_kizna_field(row, 'type', new_t)
            orig = self.model.original_kizna(row)
            item.setBackground(QBrush(MOD_BG if new_t != orig['bonus_type'] else TINT_SCALAR))
            # Update description
            self._suppress = True
            v = self.model.get_kizna(row)['bonus_value']
            desc = f'必杀 +{v}' if new_t == 1 else ('对话/家族关系（无战斗加成）' if new_t == 2 else '')
            d_cell = self.pair.right.item(row, self.COL_DESC)
            if d_cell: d_cell.setText(desc)
            self._suppress = False
            self.on_change()
            return
        if col == self.COL_VALUE:
            try:
                value = int(item.text())
            except ValueError:
                return
            self.model.set_kizna_field(row, 'value', value)
            orig = self.model.original_kizna(row)
            item.setBackground(QBrush(MOD_BG if value != orig['bonus_value'] else TINT_SCALAR))
            # Update description
            self._suppress = True
            t = self.model.get_kizna(row)['bonus_type']
            desc = f'必杀 +{value}' if t == 1 else ('对话/家族关系（无战斗加成）' if t == 2 else '')
            d_cell = self.pair.right.item(row, self.COL_DESC)
            if d_cell: d_cell.setText(desc)
            self._suppress = False
            self.on_change()
            return

    def apply_filter(self, text):
        text = text.strip().lower()
        for i in range(self.model.kizna_count):
            k = self.model.get_kizna(i)
            cn_a = self.model.translations.get('persons', {}).get(k['pid_a'], {}).get('cn', '')
            cn_b = self.model.translations.get('persons', {}).get(k['pid_b'], {}).get('cn', '')
            haystack = ' '.join([k['pid_a'], cn_a, k['pid_b'], cn_b]).lower()
            visible = (not text) or (text in haystack)
            self.pair.set_row_visible(i, visible)


class DiffDialog(QDialog):
    def __init__(self, model: FE9Data, parent=None):
        super().__init__(parent)
        self.setWindowTitle('保存预览—确认改动')
        self.resize(900, 600)
        layout = QVBoxLayout(self)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont('Menlo, Monaco, monospace'))
        text.setText(self._build(model))
        layout.addWidget(text)

        info = QLabel()
        try:
            cur_hash = model.gcm_sha256()
            size = os.path.getsize(model.gcm_path)
            info.setText(f'GCM 大小: {size} 字节  |  当前 sha256: {cur_hash[:16]}…')
        except Exception as e:
            info.setText(f'(无法计算 hash: {e})')
        layout.addWidget(info)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText('写入 GCM')
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _build(self, model: FE9Data):
        out = []
        out.append(f'GCM: {model.gcm_path}')
        out.append(f'FE8Data.bin 偏移 0x{model.fe8_offset:X}, 大小 {model.fe8_size}')
        out.append(f'差异字节数: {model.diff_byte_count()}')
        out.append('')
        out.append('=== JobData 改动 ===')
        out.append(f'{"#":>3}  {"JID":<28} {"中文":<14} 字段              改前 → 改后')
        for i in range(model.job_count):
            j = model.get_job(i)
            scalar_groups = ['mov', 'con', 'weight', 'skill_cap']
            scalar_labels = {'mov': '移动', 'con': '体格', 'weight': '重量', 'skill_cap': '技能格'}
            for g in scalar_groups:
                cur = j[g]
                orig = model.original_job_stat(i, g)
                if cur != orig:
                    out.append(f'{i:>3}  {j["jid"]:<28} {j["cn"]:<14} {scalar_labels[g]:<16}  {orig:>3} → {cur:>3}')
            for g, label_map in [('caps', '上限'), ('bases', '基础'), ('growths', '成长'), ('laguz', '兽化')]:
                for s in range(8):
                    cur = j[g][s]
                    orig = model.original_job_stat(i, g, s)
                    if cur != orig:
                        out.append(f'{i:>3}  {j["jid"]:<28} {j["cn"]:<14} {label_map}·{STAT_CN[s]:<10}  {orig:>3} → {cur:>3}')
            # Skill slot diffs
            for s in range(5):
                cur = j['skills'][s] or ''
                orig = model.original_job_skill(i, s) or ''
                if cur != orig:
                    out.append(f'{i:>3}  {j["jid"]:<28} {j["cn"]:<14} 技能{s+1:<13}  {orig or "—"} → {cur or "—"}')
            # Weapon-level diffs
            cur_w = model.get_job_weapon_levels(i)
            for s in range(9):
                from fe9_model import WEAPON_TYPES_CN
                orig_w = model.original_job_weapon_level(i, s)
                if cur_w[s] != orig_w:
                    out.append(f'{i:>3}  {j["jid"]:<28} {j["cn"]:<14} 熟练·{WEAPON_TYPES_CN[s]:<11}  {orig_w} → {cur_w[s]}')
        out.append('')
        out.append('=== PersonData 改动 ===')
        out.append(f'{"#":>3}  {"PID":<28} {"中文":<14} 字段              改前 → 改后')
        scalar_labels = {'level': '等级', 'build': '体格', 'weight': '重量', 'laguz_gauge': '兽化槽'}
        for i in range(model.person_count):
            p = model.get_person(i)
            for g in ('level', 'build', 'weight', 'laguz_gauge'):
                cur = p[g if g != 'laguz_gauge' else 'laguz_gauge']
                orig = model.original_person_stat(i, g)
                if cur != orig:
                    out.append(f'{i:>3}  {p["pid"]:<28} {p["cn"]:<14} {scalar_labels[g]:<16}  {orig:>3} → {cur:>3}')
            for g, label_map in [('bases', '基础(±)'), ('growths', '成长')]:
                for s in range(8):
                    cur = p[g][s]
                    orig = model.original_person_stat(i, g, s)
                    if cur != orig:
                        out.append(f'{i:>3}  {p["pid"]:<28} {p["cn"]:<14} {label_map}·{STAT_CN[s]:<10}  {orig:>+4} → {cur:>+4}' if g == 'bases' else f'{i:>3}  {p["pid"]:<28} {p["cn"]:<14} {label_map}·{STAT_CN[s]:<10}  {orig:>3} → {cur:>3}')
            # Person skill slot diffs
            for s in range(3):
                cur = p['skills'][s] or ''
                orig = model.original_person_skill(i, s) or ''
                if cur != orig:
                    out.append(f'{i:>3}  {p["pid"]:<28} {p["cn"]:<14} 技能{s+1:<13}  {orig or "—"} → {cur or "—"}')
        out.append('')
        out.append('=== ItemData 改动 ===')
        out.append(f'{"#":>3}  {"IID":<28} {"中文":<10} 字段              改前 → 改后')
        item_scalar_labels = {
            'cost_per': '单价g', 'uses': '耐久', 'mt': '攻击', 'hit': '命中',
            'wt': '重量', 'crit': '必杀', 'range_min': '最小射程', 'range_max': '最大射程',
            'wexp': '武器经验',
        }
        for i in range(model.item_count):
            it = model.get_item(i)
            for g, label in item_scalar_labels.items():
                cur = it[g]
                orig = model.original_item_stat(i, g)
                if cur != orig:
                    out.append(f'{i:>3}  {it["iid"]:<28} {it["cn"]:<10} {label:<16}  {orig:>3} → {cur:>3}')
            for g, label_map in [('bonuses', '加成'), ('growth', '成长')]:
                for s in range(8):
                    cur = it[g][s]
                    orig = model.original_item_stat(i, g, s)
                    if cur != orig:
                        if g == 'growth':
                            out.append(f'{i:>3}  {it["iid"]:<28} {it["cn"]:<10} {label_map}·{STAT_CN[s]:<10}  {orig:>+4} → {cur:>+4}')
                        else:
                            out.append(f'{i:>3}  {it["iid"]:<28} {it["cn"]:<10} {label_map}·{STAT_CN[s]:<10}  {orig:>3} → {cur:>3}')
            # Trait diffs
            for s in range(6):
                cur = it['traits'][s] or ''
                orig = model.original_item_trait(i, s) or ''
                if cur != orig:
                    cur_d = model.item_trait_cn(cur) or cur or '—'
                    orig_d = model.item_trait_cn(orig) or orig or '—'
                    out.append(f'{i:>3}  {it["iid"]:<28} {it["cn"]:<10} 特性{s+1:<13}  {orig_d} → {cur_d}')
            for s in range(2):
                cur = it['effects'][s] or ''
                orig = model.original_item_effect(i, s) or ''
                if cur != orig:
                    cur_d = model.item_effect_cn(cur) or cur or '—'
                    orig_d = model.item_effect_cn(orig) or orig or '—'
                    out.append(f'{i:>3}  {it["iid"]:<28} {it["cn"]:<10} 特效{s+1:<13}  {orig_d} → {cur_d}')
        out.append('')
        out.append('=== RelianceData (支援) 改动 ===')
        out.append(f'{"#":>3}  {"主角":<22} {"槽":>3}  字段           改前 → 改后')
        for i in range(model.reliance_count):
            cur = model.get_reliance(i)
            orig = model.original_reliance(i)
            for si in range(cur['count']):
                cur_s = cur['slots'][si]
                orig_s = orig['slots'][si]
                if cur_s['partner_pid'] != orig_s['partner_pid']:
                    out.append(f'{i:>3}  {cur["main_pid"]:<22} {si:>3}  伙伴            {orig_s["partner_pid"] or "—"} → {cur_s["partner_pid"] or "—"}')
                for L in ('c', 'b', 'a'):
                    if cur_s[f'bonus_{L}'] != orig_s[f'bonus_{L}']:
                        out.append(f'{i:>3}  {cur["main_pid"]:<22} {si:>3}  {L.upper()} 奖励          {orig_s[f"bonus_{L}"]:>3} → {cur_s[f"bonus_{L}"]:>3}')
        out.append('')
        out.append('=== KiznaData (固定支援) 改动 ===')
        out.append(f'{"#":>3}  {"角色 A":<22} {"角色 B":<22}  字段        改前 → 改后')
        for i in range(model.kizna_count):
            k = model.get_kizna(i)
            o = model.original_kizna(i)
            if k['pid_a'] != o['pid_a']:
                out.append(f'{i:>3}  {o["pid_a"]:<22} {o["pid_b"]:<22}  角色 A      {o["pid_a"] or "—"} → {k["pid_a"] or "—"}')
            if k['pid_b'] != o['pid_b']:
                out.append(f'{i:>3}  {k["pid_a"]:<22} {o["pid_b"]:<22}  角色 B      {o["pid_b"] or "—"} → {k["pid_b"] or "—"}')
            if k['bonus_type'] != o['bonus_type']:
                out.append(f'{i:>3}  {k["pid_a"]:<22} {k["pid_b"]:<22}  类型        {o["bonus_type"]} → {k["bonus_type"]}')
            if k['bonus_value'] != o['bonus_value']:
                out.append(f'{i:>3}  {k["pid_a"]:<22} {k["pid_b"]:<22}  数值        {o["bonus_value"]} → {k["bonus_value"]}')
        out.append('')
        out.append('=== DivineData (属性奖励) 改动 ===')
        for i in range(model.divine_count):
            d = model.get_divine(i)
            o = model.original_divine(i)
            cn = model.affinity_cn(d['name'])
            for f in ('atk', 'def', 'hit', 'avo'):
                if d[f] != o[f]:
                    out.append(f'{i:>3}  {cn or d["name"]:<6} {f:>4}  {o[f]} (+{o[f]/2:.1f}) → {d[f]} (+{d[f]/2:.1f})')
        return '\n'.join(out)


class MainWindow(QMainWindow):
    def __init__(self, gcm_path=None):
        super().__init__()
        self.setWindowTitle('FE9 编辑器 — 苍炎之轨迹')
        self.resize(1500, 850)
        self.model: FE9Data | None = None
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.setStatusBar(QStatusBar())
        self.status_label = QLabel('未载入文件')
        self.statusBar().addPermanentWidget(self.status_label, 1)
        self._build_menu()
        if gcm_path and os.path.exists(gcm_path):
            self.load_gcm(gcm_path)

    def _build_menu(self):
        m = self.menuBar()

        f = m.addMenu('文件(&F)')
        a = QAction('打开 GCM…', self); a.setShortcut(QKeySequence.StandardKey.Open)
        a.triggered.connect(self.act_open); f.addAction(a)
        a = QAction('从磁盘重新载入', self)
        a.triggered.connect(self.act_reload); f.addAction(a)
        f.addSeparator()
        a = QAction('保存（写入 GCM）', self); a.setShortcut(QKeySequence.StandardKey.Save)
        a.triggered.connect(self.act_save); f.addAction(a)
        a = QAction('撤销所有未保存修改', self)
        a.triggered.connect(self.act_revert); f.addAction(a)
        f.addSeparator()
        a = QAction('退出', self); a.setShortcut(QKeySequence.StandardKey.Quit)
        a.triggered.connect(self.close); f.addAction(a)

        t = m.addMenu('工具(&T)')
        a = QAction('应用 caps_config 规则…', self)
        a.triggered.connect(self.act_apply_caps_config); t.addAction(a)

        h = m.addMenu('帮助(&H)')
        a = QAction('关于', self); a.triggered.connect(self.act_about); h.addAction(a)

    def act_about(self):
        QMessageBox.about(self, '关于',
            '<b>FE9 编辑器</b><br>'
            '苍炎之轨迹 ROM 数据修改工具<br><br>'
            '编辑 FE8Data.bin 中的 JobData (115 职业)、PersonData (340 角色)、ItemData (189 物品)。<br>'
            'In-place 写回 GCM，文件大小不变。<br><br>'
            '<b>注意</b>: 武器熟练度块可能被多个职业/角色共享 —<br>'
            '修改职业的熟练度可能同时影响绑定到该块的角色。<br>'
            'PersonData 角色的熟练度只读 (源自所属职业的块)。<br><br>'
            '基于 PyQt6 + 公开 FE9 modding 资料构建。'
        )

    def act_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '打开 FE9 GCM',
            os.path.dirname(DEFAULT_GCM) if os.path.exists(os.path.dirname(DEFAULT_GCM)) else '/',
            'GameCube ROM (*.gcm *.iso);;所有文件 (*)'
        )
        if path:
            self.load_gcm(path)

    def load_gcm(self, path):
        try:
            self.model = FE9Data(path)
        except Exception as e:
            QMessageBox.critical(self, '载入失败', str(e))
            return
        self.tabs.clear()
        self.job_tab = JobTab(self.model, self.update_status)
        self.person_tab = PersonTab(self.model, self.update_status)
        self.item_tab = ItemTab(self.model, self.update_status)
        self.reliance_tab = RelianceTab(self.model, self.update_status)
        self.tabs.addTab(self.job_tab, f'职业表 / JobData ({self.model.job_count})')
        self.tabs.addTab(self.person_tab, f'角色表 / PersonData ({self.model.person_count})')
        self.tabs.addTab(self.item_tab, f'物品表 / ItemData ({self.model.item_count})')
        self.kizna_tab = KiznaTab(self.model, self.update_status)
        self.divine_tab = DivineTab(self.model, self.update_status)
        self.tabs.addTab(self.reliance_tab, f'等级支援 / RelianceData ({self.model.reliance_count})')
        self.tabs.addTab(self.kizna_tab, f'固定支援 / KiznaData ({self.model.kizna_count})')
        self.tabs.addTab(self.divine_tab, f'属性奖励 / DivineData ({self.model.divine_count})')
        self.update_status()

    def update_status(self):
        if not self.model:
            self.status_label.setText('未载入文件')
            return
        diff = self.model.diff_byte_count()
        sz = os.path.getsize(self.model.gcm_path)
        path = self.model.gcm_path
        if diff:
            self.status_label.setText(f'{path}  |  {sz} 字节  |  已修改 {diff} 字节（未保存）')
        else:
            self.status_label.setText(f'{path}  |  {sz} 字节  |  无未保存修改')

    def act_save(self):
        if not self.model: return
        if not self.model.is_dirty():
            QMessageBox.information(self, '保存', '没有要保存的修改。')
            return
        dlg = DiffDialog(self.model, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        bak = self.model.gcm_path + '.bak'
        if os.path.exists(bak):
            try:
                with open(bak, 'rb') as f: bh = hashlib.sha256(f.read()).hexdigest()
                ch = self.model.gcm_sha256()
                if bh != ch:
                    res = QMessageBox.question(
                        self, '备份不一致',
                        '.bak 文件 hash 与当前 GCM 不一致，可能 GCM 已被修改过。\n是否仍然继续保存?',
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )
                    if res != QMessageBox.StandardButton.Yes: return
            except Exception:
                pass
        try:
            self.model.save()
        except Exception as e:
            QMessageBox.critical(self, '保存失败', str(e))
            return
        self.job_tab.populate()
        self.person_tab.populate()
        self.update_status()
        QMessageBox.information(self, '已保存', '改动已写入 GCM。')

    def act_reload(self):
        if not self.model: return
        if self.model.is_dirty():
            res = QMessageBox.question(
                self, '丢弃修改?',
                '从磁盘重新载入将丢弃所有未保存修改，是否继续?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if res != QMessageBox.StandardButton.Yes: return
        self.load_gcm(self.model.gcm_path)

    def act_revert(self):
        if not self.model or not self.model.is_dirty(): return
        res = QMessageBox.question(
            self, '撤销所有修改',
            f'撤销内存中所有 {self.model.diff_byte_count()} 字节的未保存修改?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if res != QMessageBox.StandardButton.Yes: return
        self.model.revert_all()
        self.job_tab.populate()
        self.person_tab.populate()
        self.update_status()

    def act_apply_caps_config(self):
        if not self.model: return
        res = QMessageBox.warning(
            self, '应用 caps_config 规则',
            'caps_config 规则是<b>累加式</b>："6 项主属性 +10" 是基于当前值再加 10。\n\n'
            '重复应用会叠加（再 +10 = +20），所以仅在新载入未修改的 GCM 时使用。\n\n'
            '继续应用规则? (改动写入内存，需 Save 才会写到 GCM。)',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )
        if res != QMessageBox.StandardButton.Yes: return
        try:
            n = self.model.apply_caps_config()
        except Exception as e:
            QMessageBox.critical(self, '应用失败', str(e)); return
        self.job_tab.populate()
        self.update_status()
        QMessageBox.information(self, '规则已应用',
            f'已对 {n} 个职业应用 caps_config 规则。\n黄色单元格为改动。Save 才会写到 GCM。')


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('FE9 编辑器')
    win = MainWindow(DEFAULT_GCM if os.path.exists(DEFAULT_GCM) else None)
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
