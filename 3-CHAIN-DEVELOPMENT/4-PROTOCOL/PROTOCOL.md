# 接力协议：三链状态管理

> **文件**: `scripts/chain_guard.py`
> **状态文件**: `~/.workbuddy/memory/chain_state.json`
> **用途**: 为三链开发架构提供**物理约束**——让阶段跳转可追溯、可验证、可拦截。

---

## 为什么需要接力协议

三链架构的"人工门禁"在文档层面写得很好，但AI可以选择不遵守。
接力协议提供了一个**轻量物理约束**——通过状态文件实时追踪当前阶段，
让每次跳转留下记录，让非法跳转被拒绝。

---

## 阶段定义

| ID | 阶段 | 链 | 子模式 | 方法论文档 |
|:---|:---|---|:---|:---:|
| d1 | D1 深度调研 | 调研 | **d1-a** / **d1-b** 对抗性子路径（可选） | `1-RESEARCH/D1-investigator.md` |
| d2 | D2 分析诊断 | 调研 | — | `1-RESEARCH/D2-analyst.md` |
| d3 | D3 推演验证 | 调研 | — | `1-RESEARCH/D3-deducer.md` |
| d4 | D4 Spec合成 | 调研 | — | `1-RESEARCH/D4-spec-author.md` |
| z1 | Z1 代码扫描 | 规划 | — | `2-PLANNING/Z1-code-scanner.md` |
| z2 | Z2 范围划分 | 规划 | — | `2-PLANNING/Z2-boundary-divider.md` |
| z3 | Z3 路径设计 | 规划 | — | `2-PLANNING/Z3-path-planner.md` |
| z4 | Z4 验收方案 | 规划 | — | `2-PLANNING/Z4-acceptance-designer.md` |
| e1 | E1 任务执行 | 执行 | — | `3-EXECUTION/E1-task-executor.md` |
| e2 | E2 测试验证 | 执行 | **delegate_task** 独立上下文（默认） | `3-EXECUTION/E2-tester.md` |
| e3 | E3 部署交付 | 执行 | — | `3-EXECUTION/E3-deployer.md` |

### 对抗性子路径说明

D1 调研阶段可能启动两个子调研方向（d1-a / d1-b），当问题有多方争议或设计方案有正反选择时：

```
d1-a: 方案A方向调研（从方案A假设出发收集事实）
d1-b: 方案B方向调研（从方案B假设出发收集事实，与d1-a独立）
d1-synthesis: 分歧点标记（d1-a + d1-b 的事实对比，不下结论）
```

**子路径之间必须做到事实独立收集**——d1-a 收集的事实不应影响 d1-b 的调研方向。
D1 报告同时包含两个方向的事实，然后进入 D2 做矛盾分析。

---

## 接力规则

### 规则1：同链内必须顺序跳转

```
✅ D1 → D2 → D3 → D4（逐步推进）
❌ D1 → D3（跳步，被拒绝）
❌ D2 → D1（回跳，被拒绝）
```

### 规则2：跨链只允许两处跳转

```
✅ D4 → Z1（调研完成→实施规划）
✅ Z4 → E1（规划完成→开始执行）
❌ D1 → Z1（调研没完成就做实施规划）
❌ D2 → E1（没做规划就执行）
```

### 规则3：前置阶段必须完成

```
from_phase 的状态必须是 completed 或 skipped
to_phase 的状态必须是 pending
```

### 规则4：用户指定跳过（Override）

当用户明确说"跳过分析直接做"或"直接选方案A"时，
使用 `chain_override()` 记录跳过的理由。
override会标记被跳过的阶段为 `skipped`，供后续追溯。

### 规则5：对抗性调研触发条件（新增 — 借 Parallax 独立队列）

当 D1 调研发现以下情形时，**必须**启动对抗性调研（d1-a / d1-b 双路径）：

```
触发条件（任一条即启动）:
├── 存在两种以上差异显著的技术方案（如重构 vs 渐进改进）
├── 竞品分析中出现了矛盾结论（方案A好 vs 方案B好，各有依据）
├── 用户需求中存在方向性模糊（"A也可以，B也行"）
├── 代码问题根因有多个可争辩的解释
└── 涉及架构决策（影响范围超过1个模块）

不触发条件（跳过对抗性调研）:
├── 极其简单的问题（改一个变量名、修正拼写错误）
├── 纯文档/配置变更
├── 用户已明确指定了单一方案
└── 技术债务清理（已有明确共识的方向）
```

D1 对抗性调研的产出格式见 `D1-investigator.md § 准则五`。

### 规则6：E2 独立上下文 + 跨链反馈（新增 — 借多Agent验证）

**E2 必须优先使用 delegate_task 实现独立上下文验证。** E2 与 E1 的上下文隔离不是可选项。

```
E2 执行方式选择:
├── ✅ delegate_task 独立子Agent（默认）— 用于包含P0验收用例的复杂任务
├── ✅ 同上下文降级（非理想但可接受）— 仅用于极小改动（1-2行，非逻辑变更）
└── ❌ 禁止在同一上下文对同一段代码既写又验
```

**E2 跨链反馈（新增）:**

E2 发现的问题不仅要阻断 E3 部署，还要反馈到 D 系列：

```
E2 发现问题
    ├── 阻断 E3: blocker → chain_state.approval = blocked
    └── 反馈到 D: 写入 _plan/feedback-e2.md
        ↓
D系列下次触发时先读 feedback-e2.md
    ↓
在 D1 调研 / D2 分析中考虑历史教训
    ↓
避免同样的设计错误反复出现
```

`_plan/feedback-e2.md` 的格式见 `E2-tester.md § 跨链反馈闭环`。

---

## Guard 函数速查

| 函数 | 用途 | 调用时机 | 是否读写文件 |
|:---|---|:---|:---:|
| `chain_init(scope)` | 初始化新任务 | 每次新任务开始时 | 写 ✅ |
| `chain_check(state, from, to)` | 检查跳转合法性 | 每次阶段切换前 | 否 |
| `chain_transition(state, from, to)` | 执行合法跳转 | 用户确认后 | 读+写 ✅ |
| `chain_override(state, from, to, reason)` | 用户指定跳过 | 用户说"跳过"时 | 读+写 ✅ |
| `chain_status()` | 查看当前状态 | 任何时间 | 读 ✅ |
| `chain_approve(phase_id)` | 标记已批准+已完成 | 用户批准后 | 读+写 ✅ |
| `chain_mark_in_progress(phase_id)` | 标记进行中 | 阶段启动时 | 读+写 ✅ |

## 工具函数速查

| 工具 | 用途 | 所属阶段 | 使用方式 |
|:---|---|:---|:---|
| `review_filter.py` | 三级过滤管道（置信度→去重→幻觉） | E2 报告生成 | `python3 scripts/review_filter.py --input raw.json --output filtered.json --stats` |

---

## CLI 用法

```bash
# 初始化
python3 scripts/chain_guard.py init "任务描述"

# 查看状态
python3 scripts/chain_guard.py status

# 检查跳转
python3 scripts/chain_guard.py check d4 z1

# 执行跳转（在用户确认后）
python3 scripts/chain_guard.py transition d4 z1

# 用户指定跳过
python3 scripts/chain_guard.py override d1 d3 "用户说直接推演"

# 标记批准（自动标记为 completed）
python3 scripts/chain_guard.py approve d4

# 标记进行中
python3 scripts/chain_guard.py start e1
```

---

## 状态文件示例

```json
{
  "scope": "三链架构约束方案B实现",
  "current_phase": "d4",
  "phases": [
    {"id": "d1", "status": "completed", "approval": "approved"},
    {"id": "d2", "status": "completed", "approval": "approved"},
    {"id": "d3", "status": "completed", "approval": "approved"},
    {"id": "d4", "status": "in_progress", "approval": "approved"},
    {"id": "z1", "status": "pending", "approval": "pending"}
  ],
  "relay_history": [
    {"trigger": "chain_transition", "from": "d3", "to": "d4", "at": "..."},
    {"trigger": "user_approval", "from": "d4", "to": "d4", "at": "..."}
  ]
}
```

---

## Z系列接力详解

> Z 系列的接力有两层：**Guard 状态层**（链式跳转检查） + **文件层**（独立.md文件传递上下文）。
> Guard 已在 `chain_guard.py` 中支持 Z 系列（与 D/E 系列同为 PHASES_ORDER 成员）。
> 文件层是 P0-2 新增的协议（Z1-Z4 各自产出独立文件，非对话记忆传递）。

### 状态层接力（Guard 自动处理）

Z 系列的 Guard 规则与 D 系列完全相同，无需额外配置：

```
✅ Z1 completed → Z2 pending → 合法跳转
✅ Z2 completed → Z3 pending → 合法跳转
❌ Z1 completed → Z3 pending → 跳步（被拒绝）
❌ Z2 completed → Z1 pending → 回跳（被拒绝）
```

### 文件层接力（需手动操作）

每个 Z 阶段的产出写为独立 .md 文件，下游阶段以此文件为输入：

```
Z1输出 ──→ Z2读取 ──→ Z3读取 ──→ E1读取（执行）
Z1输出 ──→ Z2输出 ──→ Z3输出 ──→ Z4输出 ──→ E2读取（测试）
```

### 文件契约表

| 阶段 | 输出文件 | 主要内容 | 被谁读取 |
|:---|:---|---|:---|
| Z1 | `_plan/z1-scan-report.md` | 模块结构、依赖图、文件清单、配置影响 | Z2, Z3 |
| Z2 | `_plan/z2-boundaries.md` | 阶段划分表、依赖图、回滚点、边界声明 | Z3 |
| Z3 | `_plan/z3-implementation-plan.md` | 前置条件、执行步骤、回滚方案、时间预估 | **E1** |
| Z4 | `_plan/z4-acceptance-plan.md` | 验收策略、测试用例、回归方案、验收清单 | **E2** |
| E2(反馈) | `_plan/feedback-e2.md` | 跨链反馈：E2发现的问题+根因+建议 | **D1, D2** |
| E2(过滤) | `_plan/e2-findings-filtered.json` | 经 review_filter.py 过滤后的有效发现 | **D2** |

### 文件缺失处理

```
如果 Z2 找不到 _plan/z1-scan-report.md:
├── 正常情况: 报错 "缺少Z1产出"，等待
├── 用户 override: 基于对话记忆重建（标注"文件缺失，对话重建"）
└── 用户强制跳过: override + 带上 reason

如果 E1 找不到 _plan/z3-implementation-plan.md:
├── 正常情况: 报错 "缺少Z3计划"，不执行
├── 用户 override: 直接执行（标注"无Z3计划"）
└── 最坏情况: 阻断，等用户决定
```

### 完整 Z 系列接力示例

```bash
# D4 完成 → 跨链到 Z1
python3 chain_guard.py approve d4           # 标记批准（自动 completed）
python3 chain_guard.py transition d4 z1     # 跨链到 Z1

# → 执行 Z1（代码扫描）
# → Z1 写入 _plan/z1-scan-report.md

python3 chain_guard.py approve z1           # 用户确认 Z1 范围
python3 chain_guard.py transition z1 z2     # 跳转 Z2

# → 执行 Z2（范围划分）— 引用 z1-scan-report.md
# → Z2 写入 _plan/z2-boundaries.md

python3 chain_guard.py approve z2
python3 chain_guard.py transition z2 z3

# → 执行 Z3（路径设计）— 引用 z1 + z2
# → Z3 写入 _plan/z3-implementation-plan.md

python3 chain_guard.py approve z3
python3 chain_guard.py transition z3 z4

# → 执行 Z4（验收方案）
# → Z4 写入 _plan/z4-acceptance-plan.md

python3 chain_guard.py approve z4
python3 chain_guard.py transition z4 e1     # 跨链到 E1（开始执行）

# → E1 读取 z3-implementation-plan.md 逐任务执行
# → E2 读取 z4-acceptance-plan.md 执行测试
```

### 快速自检：Z 系列是否完整

```
Z 系列完成 → 自问:
├── _plan/z1-scan-report.md 存在？
├── _plan/z2-boundaries.md 存在？
├── _plan/z3-implementation-plan.md 存在？
├── _plan/z4-acceptance-plan.md 存在？
├── chain_state.json phases z1-z4 全部 completed + approved？
└── 如果全部 ✅ → 可以进入 E 系列
```

---

## 实践原则

1. **Guard 是助手，不是老板** — override 机制保证用户可以随时跳过。但每次跳过留下记录
2. **状态文件是唯一权威来源** — 不要手动修改它。通过 Guard 函数操作
3. **不依赖 Guard 做逻辑判断** — Guard 只回答"是否可以跳转"，不回答"我应该做什么"
4. **不用于 A系列 cron** — 接力协议是为三链开发架构设计的。A系列有自己的状态机
