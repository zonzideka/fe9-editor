# FE9 Mod 项目交接文档

写给下一个 session 的 Claude。读完这份文档你就能接上上一轮的工作。

---

## 0. 用户偏好

- 中文交流，简洁，无 markdown 标题/项目符号在普通对话里（写文档则正常用）
- 不要客套话
- 不确定的事先问，不要 assume
- 重要操作（写盘 / 改大量文件 / 推送公开仓库）先 dry-run + 让用户确认
- macOS Apple Silicon

## 1. 项目全景

两个独立但互补的工具，已发布到 GitHub：

| 仓库 | 作用 | 持久性 | Latest |
|---|---|---|---|
| https://github.com/zonzideka/fe9-editor | ROM 文件编辑（GCM 内 FE8Data.bin） | 永久；所有新存档 | v0.3.0 |
| https://github.com/zonzideka/fe9-modifier-macos | Dolphin 进程内存运行时编辑 | 仅当前会话；读档恢复 | v1.4-macOS.1 |

GitHub 用户：`zonzideka`（瓜子 / zonzideka@gmail.com）。`gh` CLI 已登录。

### 1.1 fe9-editor（ROM 文件编辑器）

PyQt6 + Python 3.14。本地路径 `/Users/muha/Desktop/fe9-mod/`。

**6 个 tab**：
1. 职业表 / JobData (115)
2. 角色表 / PersonData (340)
3. 物品表 / ItemData (189)
4. 等级支援 / RelianceData (41)
5. 固定支援 / KiznaData (36)
6. 属性奖励 / DivineData (9)

**核心文件**：
- `fe9_editor.py` — PyQt6 主入口
- `fe9_model.py` — FE9Data 数据模型（GCM 读写、字段访问）
- `fe9_tool.py` — GCM/FST + LZ77
- `translations.json` — 三语翻译表（109 jobs / 342 persons / 8 affinities / 97 skills / 200 items / 34 traits / 7 effects）
- `caps_config.py` — 用户首轮 mod 规则示例（HP=80 给指定 promoted）
- `fe9_dump_classes.py` / `fe9_patch_caps.py` — CLI

**重要约束**：FE8Data.bin 文件头有**指针重定位表**（@0x1C76C，6586 个 4 字节 entry）。引擎加载时只重定位列在表里的字段。原本为 null 的字段不在表里 → 写入新指针引擎不重定位 → 当成低地址解引用 → 崩游戏。编辑器的 `is_pointer_field_safe()` 自动检测，"原本为空"的指针槽位锁定不可编辑（浅灰底色 + 工具提示）。

**默认 GCM**：编辑器中 `DEFAULT_GCM = ''`（用户手动 File→Open）。开发时常用 `/Volumes/RayCue/Dolphin/NGC-火焰之纹章～苍炎之轨迹--中文版.gcm`。

### 1.2 fe9-modifier-macos（运行时修改器）

源自一份原 Windows 版 Python + PySide6 + dolphin-memory-engine 项目（`/Users/muha/Desktop/fe9-mod/PoR-Final`），我们做了 macOS 移植 + 新增物品模板编辑。

**7 个 tab**：状态 / 能力 / 技能 / 装备 / 支援 / 其他 / **物品模板**（v1.3 新增；v1.4 加 6 trait + 2 effect 下拉）

**关键文件**：
- `src/PoR.py` — 主入口（hook → QApplication）
- `src/parameter/data_setting.py` — 内存偏移表（0x802AF... + 0x807D6A14 等）
- `src/parameter/enum_data.py` — 1994 行的 PID / JID / IID / SID enum + CN 翻译
- `src/interface/item_template.py` — 我们新加的物品模板 tab
- `src/widget/customize.py` — Customize 基类（上次给加了 PySide6 6.x 兼容）
- `src/widget/bool_check.py` — `Qt.CheckState` 枚举兼容修正
- `PoR-macos.spec` — PyInstaller spec for .app
- `entitlements.plist` — `com.apple.security.cs.debugger` 等
- `MACOS-SETUP.md` — Dolphin 重签流程

**Dolphin 必须重签**：原版 Dolphin 没 `com.apple.security.get-task-allow`，`task_for_pid` 失败。流程：
```bash
mkdir -p ~/Applications
cp -R /Applications/Dolphin.app ~/Applications/Dolphin.app
xattr -cr ~/Applications/Dolphin.app
codesign --force --sign - --entitlements <plist> ~/Applications/Dolphin.app
```
之后必须用 `~/Applications/Dolphin.app`（不是 `/Applications/Dolphin.app`）。

## 2. 关键技术发现

### 2.1 FE8Data.bin 文件结构（fe9-editor 用）

| Section | File offset | 内容 |
|---|---|---|
| 文件头 | 0x00-0x1F | total_size + ptr_table_rel + ptr_count + section_count + 0-padding |
| PersonData | 0x002C | 340 entries × 0x54 字节 |
| JobData | 0x6FC0 | 115 entries × 0x64 字节 |
| ItemData | 0x9CB0 | 189 entries × 0x60 字节 |
| SkillData | 0xE394 | 一堆 SID_* sub-section |
| DivineData | 0xF4AC | 9 affinities × 12 字节 |
| KiznaData | 0x145BC | 36 fixed-support × 12 字节 |
| BattleSkyData | 0x12D70 | 天气背景指针 |
| RelianceData | 0x12DBC | 41 个 level support entries（变长） |
| 字符串区 | 0x16928 - | SJIS / ASCII 字符串 |
| Pointer Reloc Table | 0x1C76C | 6586 × 4 字节 offset，引擎加载时按此修正所有指针 |
| Section Table | 0x22E54 | 111 sections × 8 字节 (data_off, name_off) |
| Section Names | 0x231CC - 0x236FF | section 名字字符串 |

**ItemData entry layout (0x60 字节)**:
- +0x00..+0x14: 6 个指针（IID/MIID/desc/type/subtype/rank）
- +0x18..+0x2C: 6 个 trait 指针
- +0x30..+0x34: 2 个 effect 指针
- +0x38..+0x3C: 2 个 anim 指针
- +0x40..+0x4A: 单价 / 耐久 / Mt / Hit / Wt / Crit / 最小最大射程 / 图标 / WEXP
- +0x4B..+0x54: 10 字节 stat bonus（HP/Str/Mag/Skl/Spd/Lck/Def/Res/Mov/Con）
- +0x55..+0x5C: 8 字节 signed 成长加成
- +0x5D..+0x5F: 3 字节 trailing

### 2.2 FE8Data.bin 在 RAM 中的位置（fe9-modifier-macos 用）

**关键发现**：FE8Data.bin 在 GameCube RAM 中加载到 **0x807CCD60**（每次 Dolphin 启动游戏时似乎稳定，但**不保证**永远）。

由此推导：
- ItemData 在 RAM = `0x807CCD60 + 0x9CB0 = 0x807D6A10`（count word），entry 0 在 `0x807D6A14`，stride 96
- 同理 JobData / PersonData 也可推导（但 modifier 还没用到）

**找法**：搜索 RAM 中 `IID_IRONSWORD` 字符串 + Iron Sword 数据指纹 `0a 2e 05 5a 07 00 01 01`，反推 entry 起点。

**重要**：上一轮测试发现 RAM 地址**可能在某些情况下漂移**（一次读到 `0x83CD2910` 而不是预期 `0x807E30A5`）— 后续验证发现是 transient 异常（Dolphin 还在 boot 中），重读就对了。**但要警惕**：v1.3/v1.4 的 hardcoded 地址有可能在不同 Dolphin 版本 / 游戏版本下失效。**长期方案**：modifier 启动时动态扫描 IID_IRONSWORD 指纹，自动定位。

### 2.3 PersonData 内存中的运行时单位表（modifier 主要用）

不同于 ROM 中的 PersonData 模板，运行时单位状态在 `0x802AF5E4`（modifier 的 `DataSetting.SLOT`），stride 0x280（640 字节）/单位，最多 0x9F = 159 个槽。这套地址在 modifier 的 `data_setting.py` 完整列出（150+ 字段）。

### 2.4 macOS 跨进程内存读权限

`task_for_pid` 需要：调用方有 `com.apple.security.cs.debugger` AND 目标方有 `com.apple.security.get-task-allow`。production-signed 的 Dolphin 没有第二项，所以必须自己重签一份放在 `~/Applications/`。

我们的 modifier .app 通过 `codesign --entitlements entitlements.plist` 加 `cs.debugger`。

### 2.5 PySide6 6.11 vs 6.1.2 兼容问题

原 modifier 项目用 PySide6 6.1.2，新装的 6.11 有两处 break：
1. **Cooperative MRO**：`super().__init__()` 在 QWidget 子类的 init 中会自动调用，导致 `Customize.__init__()` 在 C++ 部件未初始化时被触发 → `setMinimumHeight(30)` 崩。修复：在 Customize 里加 `kwargs` 检测，只在 explicit 调用时跑 setup（见 `customize.py`）。
2. **Qt.CheckState 枚举**：`checkState()` 不再返回 int，改返回 `Qt.CheckState` 枚举。`bool_check.py` 加了 `_state_int()` 转换。

## 3. 翻译数据来源

`translations.json`（fe9-editor）现在的 CN 名以 modifier 项目里的 `resource/QM/zh.ts` 为准（v0.3.0 已对齐 620 条）。zh.ts 是社区主流汉化补丁的译名，权威。

**特殊：affinity `telius` = 地（Earth）**，不是主角标记或 bug。这是引擎的内部别名。Ike 等 19 个角色都是地属性。

## 4. 用户最新提出的新需求（next session 起手）

> "现在正常了，通过物品模板修改的内容下一次读档会被复原？那是不是应该考虑在编辑器中加入运行时的修改并固化到镜像文件中？"

**用户意图（最可能的解读）**：希望在 fe9-editor 里加一种"运行时同步 + 持久化"的工作模式 — 读取**当前 Dolphin 进程内存**中的状态（角色现有数值、物品已被怎么改），按用户想要的部分**固化（写回）到 GCM 文件**，使下次读档 / 新游戏自动带这些改动。

**两种合理的实现路径**：

### 路径 A：Modifier-side persist（推荐起步）

在 fe9-modifier-macos 加一个"导出到 ROM"按钮：
1. 用户在 Dolphin 里改了一堆物品模板 / 角色技能
2. 点"导出"
3. 修改器读取 RAM 里的当前状态，diff 出与 vanilla 的不同
4. 写回**用户指定的 GCM 文件**对应的 FE8Data.bin 字段
5. 用户用这份新 GCM 玩，改动永久生效

**优势**：直接落到 GCM，在 fe9-editor 里也能看到（两个工具数据兼容）。
**实现要点**：
- 需要 GCM 路径输入（用户提供）
- diff 逻辑：扫 RAM 的 ItemData / PersonData 模板段 vs ROM
- 写回时仍受**指针重定位表**限制（不能给原 null 字段添新指针）
- UI：File 菜单加 "导出当前修改到 GCM..."

### 路径 B：Editor-side import-from-runtime

在 fe9-editor 加 "Import from Dolphin" 菜单：
1. 用户在 Dolphin 里改了状态
2. 在 fe9-editor 里点 Import
3. 编辑器扫 Dolphin RAM，把所有 ItemData / JobData / PersonData / RelianceData / KiznaData / DivineData 的当前值同步到内存模型
4. 用户审核 diff（编辑器现有的 diff dialog 已支持）
5. 用户点 Save 写入 GCM

**优势**：复用 fe9-editor 现有 UI、diff 预览、安全检查。两个工具职责更清晰（modifier 改实时状态、editor 改 ROM）。
**实现要点**：
- 需要 dolphin-memory-engine 依赖（可选，仅 import 功能用）
- 扫描逻辑：动态找 FE8Data.bin RAM 基址（IRON SWORD 指纹法）
- 同步范围：仅模板段（ItemData/JobData/PersonData/RelianceData/KiznaData/DivineData）；运行时单位状态（角色当前 HP 等）不同步因为不该入 ROM

**我倾向**先做路径 B（在 editor 加 import）。理由：
- editor 已有完善的 diff/save 流程，直接复用
- 用户可以在 editor 里用现有工具检查 / 撤销 / 部分接受
- 修改器保持"只改运行时"的简单职责
- 不强制依赖 dolphin-memory-engine（可选 import；用户没装 Dolphin 也能用 editor）

但这是猜测，**新 session 起手第一件事是问用户具体想法**：
- 路径 A 还是 B？
- 同步范围（仅 ItemData，还是全部 6 张表）？
- UI 进入点（菜单项 / 按钮 / 命令行）？

## 5. 已完成 / 不要重复的事

- ✅ ROM 编辑器全部 6 表完整支持（含特性/特效下拉、武器熟练度可编辑、UnsafePointerEdit 检测）
- ✅ 译名对齐到 zh.ts（620 条）
- ✅ macOS .app 打包（fe9-editor v0.3.0、modifier v1.4-macOS.1，都有 release 二进制）
- ✅ 截图自动生成（`take_screenshots.py`）
- ✅ Modifier macOS 移植（PySide6 6.x 兼容、entitlements、Dolphin 重签流程）
- ✅ 物品模板 + 6 trait + 2 effect 编辑（modifier）

## 6. 已知未解决问题

1. **RAM 地址漂移风险**：modifier 用了 hardcoded `ITEM_BASE = 0x807D6A14`，未来若 Dolphin 版本 / 游戏版本变化可能失效。建议改成动态扫描（启动时找 IID_IRONSWORD 指纹反推）。低优先（当前用户的环境稳定）。

2. **存档(.gci) 直接编辑**：FE9 存档格式无公开文档，社区无现成工具。之前讨论过觉得 RE 投资回报比低，搁置。modifier 走运行时内存路线绕开了。

3. **角色技能"添加新技能到原本空槽"**：ROM 编辑器锁定不让做（重定位表问题）。modifier 在运行时可以做（已有 SID 位图 tab）。如果要 ROM 持久化，还是受制于重定位表 — 需要扩 reloc table 才行（之前评估为高风险，搁置）。

## 7. 工作环境快速恢复

```bash
cd /Users/muha/Desktop/fe9-mod          # 主项目（fe9-editor）
.venv/bin/python fe9_editor.py          # 起 editor（dev）

cd /Users/muha/Desktop/fe9-mod/PoR-Final # modifier
.venv/bin/python src/PoR.py             # 起 modifier（dev，需 Dolphin 已 hook）
```

启动 Dolphin（带 FE9）：
```bash
GCM='/Volumes/RayCue/Dolphin/NGC-火焰之纹章～苍炎之轨迹--中文版.gcm'
open ~/Applications/Dolphin.app --args -e "$GCM" -b
sleep 8  # 等 boot
```

测试 hook：
```bash
.venv/bin/python -c "
import dolphin_memory_engine as dme
dme.hook()
print('Hooked:', dme.is_hooked(), 'Status:', dme.get_status())
"
```

打包 modifier：
```bash
cd /Users/muha/Desktop/fe9-mod/PoR-Final
rm -rf release build dist
.venv/bin/python release.py src/PoR.py
.venv/bin/pyinstaller PoR-macos.spec --noconfirm
codesign --force --deep --sign - --entitlements entitlements.plist "dist/苍炎修改器.app"
```

打包 editor：
```bash
cd /Users/muha/Desktop/fe9-mod
rm -rf build dist "FE9 编辑器.spec"
.venv/bin/pyinstaller --windowed --name "FE9 编辑器" --add-data "translations.json:." --noconfirm fe9_editor.py
```

## 8. 风险 / 安全 checklist

- 写 `/Volumes/RayCue/Dolphin/...gcm` 时**永远先验证 .bak hash**（fe9-editor 已自动）
- 操作 `~/Applications/Dolphin.app` 签名前**复制原版**，不修改 `/Applications/Dolphin.app`
- 推送公开仓库前**先 dry-run 看 diff**，确认无个人路径 / API key
- gh release create 中文文件名会被剥离 → 用 ASCII 名字（`fe9-editor-v0.3.0-macOS.zip`）

---

新 session 起手建议第一句问：「上一轮提到的'运行时修改持久化'功能，倾向路径 A（modifier 导出到 GCM）还是路径 B（editor 从 Dolphin import）？还是别的方案？」
