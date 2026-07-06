# 产物投递管理 SKILL v7.3

> **SKILL 类型**：执行型 + 验证型（AI 读取后按指令操作）
> **调用方式**：自动化任务 Prompt 中写 "读取 artifact-alignment-manager SKILL 并按执行协议操作"
> **触发词**：产物投递、投递验证、归档检查、delivery check、frontmatter检查、前端同步、产物中心、时间戳检查、ts规范、排序问题、产物排序
> **最高原则**：以本SKILL为产物投递的最高规范，所有自动化任务必须遵循

---

## 一、核心职责

**本 SKILL 整合了产物投递执行和验证功能：**

| 功能 | 说明 |
|:-----|:-----|
| **投递执行** | 调用 `sync_artifact.py` 自动同步到前端产物中心 |
| **投递验证** | 检查 frontmatter 完整性、index.json 状态、前端可见性 |
| **时间戳规范化** | 统一收口，所有时间戳必须通过本 SKILL 规范化 |
| **双通道保证** | 秘书邮箱 + 前端产物中心，缺一不可 |

---

## 二、投递双通道

A0-A9 产物有**两个投递目标**：

| 通道 | 路径 | 用途 |
|------|------|------|
| 秘书邮箱 | `~/.workbuddy/skills/boss-secretary/reports/trading/` | 报告归档、邮件分发 |
| 前端产物中心 | `~/.workbuddy/artifacts/{category}/` | localhost:3456 展示 |

> **⚠️ 每次投递必须同时写入两个通道！缺一不可。**

---

## 三、时间戳规范（统一收口）

### 3.1 为什么需要统一收口

不同系统生成时间戳格式不一致会导致：
- 前端日期显示错误（如 `2026-05-06` 被解析为 `08:00`）
- 筛选和排序逻辑混乱
- AAM 成为唯一时间戳规范来源

### 3.2 规范格式

| 格式 | 示例 | 用途 |
|------|------|------|
| **标准格式** | `2026-05-06T17:54:15+08:00` | frontmatter `date` 字段 |
| **纯日期格式** | `2026-05-06` | 仅日期无时间的场景 |
| **紧凑格式** | `20260506_175415` | 文件名中的时间戳 |

**规范要点**：
- ✅ 使用北京时间（UTC+8）
- ✅ 标准格式必须包含时区 `+08:00`
- ✅ 纯日期格式用于无时间部分的场景
- ❌ 禁止使用模糊格式（如 `05-06`、`今天`）
- ❌ 禁止使用 UTC 而不转换

### 3.3 工具函数

**Python 调用**：
```python
from sync_artifact import normalize_timestamp, validate_timestamp_format

# 生成当前时间的规范格式
ts_iso = normalize_timestamp()  # "2026-05-06T17:54:15+08:00"
ts_date = normalize_timestamp(output_format="date_only")  # "2026-05-06"
ts_compact = normalize_timestamp(output_format="compact")  # "20260506_175415"

# 验证并规范化
is_valid, normalized, msg = validate_timestamp_format("2026-05-06T10:00:00")
```

**CLI 调用**：
```bash
# 验证单个时间戳
python3 ~/.workbuddy/scripts/sync_artifact.py --check-ts "2026-05-06"

# 批量规范化 index.json
python3 ~/.workbuddy/scripts/sync_artifact.py --normalize-index ~/.workbuddy/artifacts/trading/index.json
```

### 3.4 AI 生成产物时的强制要求

**所有 AI 生成的产物，frontmatter 的 `date` 字段必须使用规范格式：**

```yaml
---
title: "A1 深度调研 2026-05-06"
date: "2026-05-06T17:54:15+08:00"  # 必须！使用规范格式
---
```

**正确示范**：
```yaml
date: "2026-05-06T17:54:15+08:00"  # ✅ 标准格式
date: "2026-05-06"                 # ✅ 纯日期
```

**错误示范**：
```yaml
date: "2026-05-06 17:54:15"        # ❌ 空格分隔，无时区
date: "17:54:15"                   # ❌ 只有时间
date: "今天"                       # ❌ 模糊格式
date: "2026/05/06"                 # ❌ 斜杠分隔
date: "2026-5-6T10:00:00"          # ❌ 月/日补零缺失
date: "2026-05-06T10:00:00Z"      # ❌ UTC时区未转换
date: "May 6, 2026"                # ❌ 英文格式
date: "1715068455"                 # ❌ Unix时间戳
```

### 3.5 严格规范检查（强制执行）

**🔴 P0 检查项（必须通过，否则禁止投递）**：

| 检查项 | 检查规则 | 检查命令 |
|--------|----------|----------|
| frontmatter date 字段存在 | 必须存在，不能为空 | `grep -E "^date:" <file>` |
| frontmatter date 格式正确 | 必须匹配 `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}$` | 见下方命令 |
| 无时区必须转换 | UTC时间必须转换为 +08:00 | 手动转换或用工具 |
| 月/日必须补零 | `05` 而非 `5` | 正则验证 |

**🔴 P0 规范检查正则**：
```bash
# 检查 frontmatter date 字段格式（严格）
grep -A1 "^date:" <file> | grep -v "^date:" | grep -v "^---" | while read ts; do
  if ! echo "$ts" | grep -qE '^\s*"?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}"?\s*$'; then
    echo "🔴 P0违规: $ts"
    exit 1
  fi
done
```

**🟡 P1 检查项（警告，不阻止但需修复）**：

| 检查项 | 检查规则 | 建议 |
|--------|----------|------|
| index.json date 一致性 | 必须与 frontmatter date 完全一致 | 重新 sync |
| 文件名时间戳格式 | 建议使用 `YYYYMMDD_HHMMSS` | 统一格式 |
| 历史产物时间戳 | 批量检测旧文件 | 逐步修复 |

### 3.6 违规处理

| 违规等级 | 判定条件 | 处理方式 |
|----------|----------|----------|
| 🔴 P0 致命 | frontmatter date 缺失/格式错误 | **禁止投递**，必须修复后重试 |
| 🟡 P1 警告 | index.json 与 frontmatter 不一致 | 修复后重新 sync |
| 🟢 P2 建议 | 文件名时间戳格式不统一 | 记录，下次注意 |

**P0 违规示例**：
```yaml
# ❌ P0 致命违规（禁止投递）
---
title: "A1 调研报告"
date: ""                    # 缺失
---

# ❌ P0 致命违规（禁止投递）
date: "2026-5-7"            # 格式错误

# ✅ P0 合规
date: "2026-05-07T15:53:28+08:00"
```

### 3.7 批量时间戳验证脚本

**验证所有产物的时间戳格式**：
```bash
#!/bin/bash
# validate_all_timestamps.sh - 批量验证时间戳
ERRORS=0
for f in ~/.workbuddy/artifacts/*/*.md; do
  ts=$(grep -m1 "^date:" "$f" | sed 's/^date:.*"\(.*\)".*/\1/')
  if ! echo "$ts" | grep -qE '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}$'; then
    echo "🔴 $f: $ts"
    ERRORS=$((ERRORS+1))
  fi
done
echo "共 $ERRORS 个时间戳违规"
```

**验证 index.json 完整性**：
```bash
#!/bin/bash
# validate_index_json.sh - 验证index.json
ERRORS=0
for idx in ~/.workbuddy/artifacts/*/index.json; do
  while IFS= read -r item; do
    date=$(echo "$item" | python3 -c "import sys,json; print(json.load(sys.stdin).get('date',''))")
    if ! echo "$date" | grep -qE '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}$'; then
      echo "🔴 index违规: $date"
      ERRORS=$((ERRORS+1))
    fi
  done < <(cat "$idx" | python3 -c "import sys,json; [print(json.dumps(i)) for i in json.load(sys.stdin)]")
done
echo "index.json 共 $ERRORS 个时间戳违规"
```

---

## 四、SKILL 执行协议（AI 必读）

### 4.1 何时调用此 SKILL

当自动化任务 **生成新产物（报告/日志/审计文件）** 时，必须调用此 SKILL 完成投递。

### 4.2 调用后执行流程

```
[AI 生成产物] → [时间戳规范检查 P0] → [生成规范时间戳] → [读取本 SKILL] → [执行投递] → [验证检查] → [返回结果]
```

**⚠️ 前置必须项**：
- **投递前必须先执行 P0 时间戳检查**
- 检查 frontmatter `date` 字段格式是否合规
- 不合规时 **禁止投递**，必须修复后重试
- **必须使用 `normalize_timestamp()` 生成规范时间戳**
- 同步失败时 **必须告警**，不允许静默失败
- 规则变更 **只需改此 SKILL**，所有调用方自动生效

---

## 五、Frontmatter 规范

### 5.1 A系列产物 Frontmatter 模板

```yaml
---
title: "A1 深度调研 YYYY-MM-DD HH:MM"
department: trading
chain_phase: A1           # 必须！A0-A9
date: "YYYY-MM-DDTHH:MM:SS+08:00"  # 必须！使用规范格式
type: research_report
status: completed
tags: "a1 research 调研"
by_a_phase: A1             # 必须！前端统计用
---
```

### 5.2 A系列类型映射

| chain_phase | type | department | 前端标签 |
|-------------|------|------------|---------|
| A0 | contradiction_theory | governance | a0, 矛盾论 |
| A1 | research_report | trading | a1, 调研 |
| A2 | first_principles | trading | a2, 第一性原理 |
| A3 | strategy | trading | a3, 推演 |
| A4 | validation_report | trading | a4, 验证 |
| A5 | execution_report | trading | a5, 执行 |
| A6 | intelligence_brief | trading | a6, 情报 |
| A7 | practice_theory | governance | a7, 实践论 |
| A8 | verification_report | governance | a8, 自检 |
| A9 | exit_decision | trading | a9, 离场 |
| dream | dream_journal | dream | dream, 做梦 |

---

## 六、产物投递执行模板（AI 按此操作）

### 6.1 完整投递流程

```
步骤1：P0 时间戳规范检查（前置，必须通过）
   ↓
步骤2：生成规范时间戳（使用 normalize_timestamp()）
   ↓
步骤3：确定文件名和所属部门
   ↓
步骤4：保存到对应部门子目录
   ↓
步骤5：调用 sync_artifact.py 同步到前端（自动化）
   ↓
步骤6：验证（frontmatter + index.json + 前端可见性）
   ↓
步骤7：返回结果给调用方
```

### 6.2 时间戳生成代码模板

```python
from sync_artifact import normalize_timestamp

# 在生成产物时
current_time = normalize_timestamp()  # "2026-05-06T17:54:15+08:00"

# frontmatter 中使用
frontmatter = f'''---
title: "A1 深度调研 {current_time[:10]}"
date: "{current_time}"
...
'''
```

### 6.3 步骤2-3：文件保存

**秘书目录根路径**：
```
~/.workbuddy/skills/boss-secretary/reports/
```

**部门投递映射表**（按文件名自动匹配）：

| 文件名模式 | 目标目录 | 部门 |
|:-----------|:---------|:-----|
| `a[0-9]_*`, `exit_check_*` | reports/trading/ | 📊 交易部 |
| `dream_journal_*`, `dream_insight_*`, `dream_gate_audit_*`, `dream_research_agenda_*`, `dream_brainstorm_*`, `oneirology_*` | reports/oneirology/ | 🌙 做梦部 |
| `audit_*`, `gate_audit_*` | reports/audit/ | 🔧 支撑部 |
| 其他 | reports/secretary/ | 🏛️ 秘书部 |

> **⚠️ 做梦部产物类型说明**：
> - `dream_journal_*` — 梦境日志（每日17:00自动执行）
> - `dream_insight_*` — 做梦洞察摘要
> - `dream_gate_audit_*` — 做梦部门禁审计报告
> - `dream_research_agenda_*` — 做梦部研究议程
> - `dream_brainstorm_*` — 做梦部头脑风暴
> - `oneirology_*` — 其他做梦部产物

### 6.4 步骤4：调用 sync_artifact.py 同步

**命令模板**：
```bash
# 方式1：同步单个新文件（自动分类）
python3 ~/.workbuddy/scripts/sync_artifact.py --source <文件路径>

# 方式2：批量同步所有秘书邮箱产物
python3 ~/.workbuddy/scripts/sync_artifact.py --mailbox
```

**执行后检查**：
- ✅ 输出包含 `"✅ 已复制"` 和 `"✅ 已添加索引"`
- ❌ 输出包含 `"❌"` 则同步失败，必须告警

### 6.5 步骤5：自动验证

```bash
# 验证前端可见性（文件名校验）
curl -s -o /dev/null -w "%{http_code}" http://localhost:3456/feed/trading/<文件名>

# 期望返回: 200
```

**验证通过标准**：
- ✅ sync_artifact.py 输出成功
- ✅ 前端详情页返回 200
- ✅ frontmatter 包含 chain_phase 和 tags

---

## 七、常见投递错误及修复

### 错误 1：投递到废弃目录

| 症状 | 根因 | 修复 |
|------|------|------|
| A1/A2/A3 产物不显示 | 投递到 `reports/research/` | 迁移到 `trading/` |
| A6 产物不显示 | 投递到 `reports/` 根目录 | 迁移到 `trading/` |

### 错误 2：Frontmatter 缺陷

| 症状 | 根因 | 修复 |
|------|------|------|
| 产物存在但A阶段过滤不中 | 缺 `chain_phase` 字段 | 补全 chain_phase |
| 产物完全不可见 | 无 frontmatter | 添加完整 YAML frontmatter |

### 错误 3：时间戳格式错误

| 症状 | 根因 | 修复 |
|------|------|------|
| 日期显示为"今天 08:00" | 纯日期被 JS 错误解析 | 使用 `normalize_timestamp()` |
| 时区显示不一致 | 缺少 `+08:00` | 使用标准格式 `YYYY-MM-DDTHH:MM:SS+08:00` |

### 错误 4：只输出到对话不落盘

| 阶段 | 症状 | 修复 |
|------|------|------|
| A9 | 25次运行仅JSON日志，无.md报告 | 同时生成 .md 报告 |

### 错误 5：index.json 手动写入导致排序混乱 ⚠️ P0 禁止

| 症状 | 根因 | 修复 |
|------|------|------|
| 最新产物未排在首位 | 手动写入纯日期格式 | **禁止手动写入 index.json，必须用 sync_artifact.py** |
| 同日产物排序混乱 | frontmatter 与 index.json date 不一致 | index.json 必须从 frontmatter 同步 |

**⚠️ P0 强制规范**：
- ❌ **禁止直接编辑 `index.json` 的 `date` 字段**
- ❌ **禁止使用纯日期格式 `2026-05-07` 写入 index.json**
- ✅ 必须调用 `sync_artifact.py --source <文件>` 自动同步
- ✅ 必须确保 frontmatter 的 `date` 字段是标准格式 `YYYY-MM-DDTHH:MM:SS+08:00`

### 错误 6：index.json 排序混乱（新产物未排在首位）⚠️ P0 修复

| 症状 | 根因 | 修复 |
|------|------|------|
| A2/A3/A9 最新产物未排在首位 | sync_artifact.py 使用 `append()` 而非排序 | **已修复：sync_artifact.py v5.3+ 在保存前自动按时间降序排序** |
| 老产物排在前面 | 同步时新条目添加到末尾 | 调用 `python3 sync_artifact.py --normalize-index <index.json>` 重新排序 |

**✅ 修复方案（v5.3+ 已内置）**：

`sync_artifact.py` 在同步时会自动按时间戳降序排序：
```python
# 保存索引前按时间戳降序排序（最新的在最前）
artifacts.sort(key=lambda x: x.get('date', ''), reverse=True)
save_index(category_dir, artifacts)
```

**手动修复已存在的排序问题**：
```bash
# 1. 规范化所有纯日期格式条目（从文件名提取时间）
python3 ~/.workbuddy/scripts/sync_artifact.py --normalize-index ~/.workbuddy/artifacts/trading/index.json

# 2. 验证排序是否正确（最新在前）
python3 -c "
import json
with open('~/.workbuddy/artifacts/trading/index.json') as f:
    data = json.load(f)
sorted_data = sorted(data, key=lambda x: x.get('date', ''), reverse=True)
for i, item in enumerate(sorted_data[:5]):
    print(f'{i+1}. [{item.get(\"chain_phase\")}] {item.get(\"date\")} - {item.get(\"title\", \"\")[:40]}')
"
```

**验证命令**：
```bash
# 检查 index.json 所有 date 字段格式
cat ~/.workbuddy/artifacts/trading/index.json | python3 -c "
import json,sys
data = json.load(sys.stdin)
for item in data:
    date = item.get('date','')
    if 'T' not in date:
        print(f'⚠️  {item.get(\"chain_phase\")}: {date}')
"
# 期望：无输出（所有 date 都是标准格式）
```

---

## 八、sync_artifact.py 命令速查

| 操作 | 命令 |
|:-----|:-----|
| 同步单个文件（自动分类） | `python3 ~/.workbuddy/scripts/sync_artifact.py --source <路径>` |
| 批量同步所有秘书邮箱产物 | `python3 ~/.workbuddy/scripts/sync_artifact.py --mailbox` |
| 验证同步状态 | `python3 ~/.workbuddy/scripts/sync_artifact.py --verify <目录>` |
| 验证单个时间戳格式 | `python3 ~/.workbuddy/scripts/sync_artifact.py --check-ts "<时间戳>"` |
| 批量规范化 index.json | `python3 ~/.workbuddy/scripts/sync_artifact.py --normalize-index <文件>` |
| 批量检查所有产物时间戳 | `bash ~/.workbuddy/skills/artifact-alignment-manager/validate_all_timestamps.sh` |
| 批量检查 index.json 时间戳 | `bash ~/.workbuddy/skills/artifact-alignment-manager/validate_index_json.sh` |

---

## 九、前端产物目录结构

```
~/.workbuddy/artifacts/
├── trading/index.json         # A0-A9系列
├── trading/a[0-9]_*.md
├── trading/exit_check_*.md
├── oneirology/index.json     # 做梦部
├── audit/index.json          # 支撑部
└── secretary/index.json      # 秘书部
```

---

## 十、自动化任务 Prompt 模板

```markdown
# <任务名称> - <执行频率>

## 执行步骤

### 1. 数据采集/处理
<具体执行步骤>

### 2. 时间戳规范检查（P0 前置）
```bash
# 检查产物 frontmatter date 格式
ts=$(grep -m1 "^date:" <生成文件> | sed 's/^date:.*"\(.*\)".*/\1/')
if ! echo "$ts" | grep -qE '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}$'; then
  echo "🔴 P0违规: 时间戳格式错误，禁止投递"
  exit 1
fi
```

### 3. 生成规范时间戳
```python
from sync_artifact import normalize_timestamp
current_time = normalize_timestamp()  # "2026-05-06T17:54:15+08:00"
```

### 4. 生成报告
- 文件名格式：`<类型>_<名称>_<YYYYMMDD_HHMMSS>.md`
- frontmatter 必须包含 chain_phase, tags, by_a_phase
- **date 字段必须使用 `current_time`**

### 4. 产物投递（必须执行）
读取 `artifact-alignment-manager` SKILL 并按执行协议操作：
1. 保存文件到 `reports/<部门>/`
2. 调用 `sync_artifact.py --source <文件路径>`
3. 验证同步结果
4. 返回投递状态

### 5. 输出摘要
输出3-5句话摘要，包含：
- 报告核心结论
- 产物投递状态（成功/失败）
```

---

## 十一、版本历史

| 版本 | 日期 | 变更 |
|:-----|:-----|:-----|
| v7.4 | 2026-05-08 | **扩展做梦部产物类型**：增加dream_gate_audit_、dream_research_agenda_、dream_brainstorm_等梦境部门产物分类 |
| v7.3 | 2026-05-07 | 新增"错误6：index.json排序混乱"章节，修复新产物未排在首位问题；sync_artifact.py v5.3内置自动排序 |
| v7.2 | 2026-05-07 | 新增"严格时间戳规范检查"章节：P0/P1/P2违规等级、强制正则检查、批量验证脚本、违规处理流程 |
| v7.1 | 2026-05-07 | 新增"错误5：index.json手动写入禁止规范"(P0)，禁止直接编辑index.json的date字段 |
| v7.0 | 2026-05-06 | 新增时间戳规范化规范，作为统一收口 |
| v6.0 | 2026-05-06 | 合并 `artifact-delivery-validator`，整合执行+验证功能 |
| v5.0 | 2026-05-05 | 新增公司架构与部门职责章节 |
| v4.0 | 2026-05-05 | 重构为执行型 SKILL |
| v3.0 | 2026-05-05 | 新增 governance/、文件名模式匹配 |
| v1.0 | 2026-05-05 | 初版建立 |
