# AGENTS.md — 步进式7步框架

> **每次 session 必须遵守 7Step 步进式流程。**
> 代替旧三链门禁规则（已整合进 Step 2）。

---

## ⭐ 规则 0：Session Start

**每次 session 开始时，必须：**

1. **读笔记本** → `0-NOTEBOOK/NOTEBOOK.md`（步进式面板 + 当前步数）
2. **读步进状态** → 
   ```bash
   python3 scripts/step_controller.py status
   # 🔒 Gate 0 拦截：如果无 .session_gate 文件 → BLOCKED → 必须先 start
   ```
3. **快速门禁检查**（可选，验证 gate 存在）
   ```bash
   python3 scripts/step_controller.py check
   ```
4. **读 AGENTS.md**（本文件）

**如果尚无活跃任务**（步进面板全是 ⬜ 或 Gate 0 BLOCKED）：
- 先 `python3 scripts/step_controller.py start "任务名"` 创建 .session_gate
- 再等待用户输入新需求
- 收到需求后启动步进式框架

**如果有活跃任务**（某步在 ▶️ 状态）：
- 先完成当前步，再处理用户最新需求
- 除非用户明确说"暂停当前任务，做新的"

---

## 🔷 7Step 步进式框架

收到需求后，按以下 7 步顺序执行。**每步完成后必须询问用户下一步。**

### 步进控制器

```bash
python3 scripts/step_controller.py start "任务描述"    # 启动新任务
python3 scripts/step_controller.py status             # 查看进度
python3 scripts/step_controller.py step N "备注"       # 标记第N步完成
python3 scripts/step_controller.py skip N             # 跳过第N步
python3 scripts/step_controller.py jump N             # 跳到第N步
python3 scripts/step_controller.py all                # 标记全部完成
```

---

## 步骤详解

### Step 1 🎯 需求解析

| 内容 | 涉及系统 |
|:---|---|
| 理解用户需求，澄清歧义 | 笔记本系统 |
| 更新笔记本 TODO/待办池 | 笔记本系统 |
| 如需求复杂(3+文件/10+步)，初始化 chain_guard | chain_guard |
| 输出: 需求确认 + 笔记本记录 | — |

**完成后** → `step_controller.py step 1 "需求已澄清"` → **询问用户**

---

### Step 2 🔗 D-Z-E（核心方法论）

| 内容 | 涉及系统 |
|:---|---|
| 理解并应用完整的门禁体系 | 双门禁 |
| **🔒 Session级**: `scripts/step_controller.py start "任务"` → 必须已启动 | 笔记本系统 |
| **🔒 D-Z-E项目级**: `3-CHAIN-DEVELOPMENT/scripts/chain_guard.py init "描述"` → 必须已初始化 | 三链门禁 |
| 按 D→Z→E 顺序执行 | chain_guard |
| `chain_guard check/transition` 管理阶段跳转 | chain_guard |
| `chain_guard override` 处理用户授权跳步 | chain_guard |
| 每阶段完成后自动更新 notebook | 笔记本系统 |

**工具族约束**（D-Z-E 执行期间强制）：
| 阶段 | 可用工具 |
|:---:|---|
| D1（调研） | 只读工具（read_file, search_files, web_search, web_extract） |
| D2（分析） | 可读可写，不可执行（terminal, deploy） |
| D3/E（执行） | 全工具可用 |

**跳步门禁**（最高优先级）：
- 不说不跳，说跳才跳
- 用户沉默/说"好的""嗯""确认" **不算授权**
- 只有"跳过""直接执行""授权跳过"才算

**完成后** → `step_controller.py step 2 "D-Z-E调研完成"` → **询问用户**

---

### Step 3 📚 知识库检索与回补

| 内容 | 涉及系统 |
|:---|---|
| 检索 `2-KNOWLEDGE/` 相关知识 | 知识库 |
| 引用已有知识 | 知识库 |
| 知识不足时联网搜索 | web_search |
| 搜到后必回补（不是白搜） | — |
| 如产生新知识，写入知识库 | 知识库 |

**完成后** → `step_controller.py step 3 "知识库已检索/回补"` → **询问用户**

---

### Step 4 🧠 A系列方法论借鉴

| 内容 | 涉及系统 |
|:---|---|
| 加载相关 dream-* skill（矛盾论/第一性原理等） | A系列 skill |
| 应用方法论框架指导执行 | A系列 skill |
| 引用 A0-A9 分析方法论 | A系列 skill |

**完成后** → `step_controller.py step 4 "方法论已应用"` → **询问用户**

---

### Step 5 🔍 索引系统更新

| 内容 | 涉及系统 |
|:---|---|
| 确保新增/修改文件的 INDEX.md 已更新 | 索引系统 |
| 检查全系统索引引用正确性 | 索引系统 |
| 更新 `0-NOTEBOOK/INDEX.md`（如有需要） | 索引系统 |

**完成后** → `step_controller.py step 5 "索引已更新"` → **询问用户**

---

### Step 6 ✈️ 飞书协作归档

| 内容 | 涉及系统 |
|:---|---|
| 如需用户审批 → 创建飞书审批 | 飞书审批 |
| 如需知识库同步 → 更新飞书Wiki | 飞书知识库 |
| 如需数据记录 → 更新飞书Base | 飞书Base |

**完成后** → `step_controller.py step 6 "飞书已同步"` → **询问用户**

---

### Step 7 🧪 记忆蒸馏

| 内容 | 涉及系统 |
|:---|---|
| 关键信息蒸馏 → 写入 memory | 记忆系统 |
| 新知识追加到 `2-KNOWLEDGE/` | 知识库 |
| 演化日志更新 `3-EVOLUTION/INDEX.md` | 索引系统 |
| 笔记本已完成项归档 | 笔记本系统 |

**完成后** → `step_controller.py step 7 "记忆已蒸馏"` → **输出最终总结**

---

## 标准询问格式（Gate 2 强制执行）

每步完成后，使用以下格式：

```
✅ Step N 完成 — {步骤名}

{简要总结做了什么 + 产出}

下一步：
1️⃣ 继续 Step N+1 — {下一步名称}
2️⃣ 跳过 Step N+1，直接到 Step N+2
3️⃣ 跳到 Step X — {指定步}
4️⃣ 直接执行未完成的全部
5️⃣ 暂停/修改当前步骤 / 其他
```

> **注意**：选项 (c) 和 (d) 需要你明确说出"跳过""直接执行"才算授权。

---

## 项目结构

```
Dreambuddy-V2/
├── 0-NOTEBOOK/       ← 7Step 步进式笔记本
│   ├── NOTEBOOK.md   ← 步进面板 + 进度
│   ├── INDEX.md      ← 目录
│   ├── .step_state.json ← 步进状态文件
│   ├── 0-TODO/       ← 待办池
│   ├── 1-ACTIVE/     ← D-Z-E活跃链
│   ├── 2-DONE/       ← 已完成（日期归档）
│   └── 3-ARCHIVE/    ← 历史归档
├── 2-KNOWLEDGE/      ← 知识库（5域）
├── 3-CHAIN-DEVELOPMENT/ ← 三链架构
├── 4-PROTOCOL/       ← 三链接力协议
├── 6-TRADING/        ← 交易核心
├── scripts/
│   ├── step_controller.py  ← 步进控制器
│   └── notebook_hook.py    ← 笔记本钩子
└── AGENTS.md          ← 本文件
```
