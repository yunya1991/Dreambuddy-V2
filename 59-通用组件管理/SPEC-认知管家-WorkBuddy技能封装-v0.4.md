# SPEC — 认知管家（CogSteward）WorkBuddy 技能封装

> **版本**: v0.4（三轮复审修订版）
> **日期**: 2026-11-19
> **状态**: M0 待关闭（R7–R9、n1–n10 已处理，见 §16；平台沙箱 spike 待执行）
> **归属**: 59-通用组件管理（对外产品，独立于内部交易域）
> **定位**: 把「技能治理 + 文档治理 + 上下文分流」封装为可分发的 WorkBuddy Skill 商品
> **非目标**: 不打包 `4-MEMORY` / `35-广义认知系统协作模块` / `41-文件索引系统` 的任何现有代码与数据
> **术语约定**: 本文用 **Skill** 指代 WorkBuddy 技能包；`SKILL.md` 作为文件名保留大写。

---

## 0. 一句话

**别人做「记得更多」，我们做「该不该记、该放哪、该调谁」。**

认知管家是一个上下文治理 Skill：把新进来的信息判定出**唯一主载体**（技能 / 文档 / 记忆 / 会话），并把其余归属登记为**从属引用**，再在任务开始前编译出最小上下文包。

---

## 1. 背景与问题

### 1.1 内部能力的真实来源

| 内部资产 | 可提炼的规则 | 是否可直接复用代码 |
|---|---|---|
| `35-广义认知系统协作模块/SPEC-ResidualMemory-Admission.md` | 残差准入、遗忘=检索失败、级联治理 | ❌ 只提炼规则 |
| `4-MEMORY/9-工具与接口/cognitive_mcp_server.py` | 零依赖 JSON-RPC + stdio 壳形态 | ❌ 只借鉴形态 |
| `41-文件索引系统` | 增量索引、意图检索、embedding 桥 | ❌ schema 私有 |
| `0-系统文档管理/4-工具与自动化` | doc_lint / link_checker / doc_coverage | ❌ 路径与仓库强耦合 |
| `dream-skill-index-governance` / `dream-doc-sync-workflow` | 技能索引、触发词冲突、双治理边界 | ❌ 只提炼规则 |

**结论**：对外产品必须**独立重写**一套零依赖实现，内部模块仅作为规则来源与设计参考。直接打包会同时带出私有 schema、绝对路径、交易域语义与 3GB 数据，且违反平台加密/云端执行的防复制取向。

### 1.2 目标用户的两个真实痛点

- **开发者**：仓库越写越大，SPEC / 文档 / 脚本 / 技能四套体系互不认账；AI 每次都要重新摸索；旧结论反复被重写。
- **办公用户**：资料、笔记、模板、待办混在一个网盘里；AI 每次会话都从零开始；同一份内容被复制十几遍。

两者共同点：**不是「存不下」，而是「不知道该放哪、该信哪个、该读哪段」**。

---

## 2. 市场与差异化

### 2.1 赛道定位

| 赛道 | 代表 | 核心主张 | 与本产品的关系 |
|---|---|---|---|
| Agent 记忆层 | Mem0 | 抽取事实 + 向量/图存储，即插即用 | 互补：它负责「记」，我们负责「准入与路由」 |
| Agent 记忆层 | Zep / Graphiti | 时序知识图谱，事实带有效期 | 互补：时序失效≠遗忘治理，且不覆盖文档/技能 |
| Agent 运行时 | Letta | 记忆分层 + 上下文分页 | 互补：绑定其运行时，不可移植 |
| 文档知识库 | Notion / Obsidian / RAG | 存 + 检索 + 链接 | 互补：无自动归类、无索引漂移、无技能层 |
| 技能市场 | WorkBuddy Skill 商店 | 单点工具能力 | 互补：无跨会话的上下文治理层 |

### 2.2 功能级对比矩阵

> 本矩阵是**待复核假设**，不是结论。每格需在 M0 前测中用真实试用或官方文档核对；核对前不得用于营销文案（对应评审 m4）。

| 能力 | Mem0 | Zep | Letta | Obsidian/RAG | 认知管家 |
|---|---|---|---|---|---|
| 写入准入（默认拒绝） | ✗（自动抽取） | ✗ | ✗ | ✗ | ✓ |
| 遗忘治理（移出检索 + 痕迹） | 部分（删除） | 部分（时序失效） | 部分（分页淘汰） | ✗ | ✓（Pro） |
| 同一内容多载体归属 | ✗ | ✗ | ✗ | ✗ | ✓（主载体+从属） |
| 文档 / 技能 / 记忆 / 会话 路由 | ✗ | ✗ | ✗ | ✗ | ✓ |
| 断链 / 孤儿 / 索引漂移检测 | ✗ | ✗ | ✗ | 部分 | ✓ |
| 零依赖本地运行 | ✗ | ✗ | 部分 | 部分 | ✓ |
| 可复核验收（P/R/F1） | 部分 | 部分 | 部分 | ✗ | ✓ |

### 2.3 差异化三条（按可讲清程度排序）

1. **写入门槛（残差准入）**：默认拒绝，答不出「不可再推导」就不写。可量化：噪音写入拒绝率。
2. **多载体归属**：主载体唯一，其余归属登记为从属引用，不丢信息。
3. **可验收**：一次 `doctor` 输出断链、孤儿、索引漂移、技能冲突、会话待分拣五类体检结果。

> 叙事口径：「记忆库越用越胖是缺陷，不是成绩；越用越小、越准才是能力。」
> 注意：这是对手的产品特性，不等于用户痛点。对外文案必须落到可感知价值（少重复提问、少断链），见 §12 V11。

---

## 3. 产品定位与双版本

**产品名**：认知管家（CogSteward）
**工程名**：Cognition Manager
**形态**：WorkBuddy Skill（`SKILL.md` + scripts + references + assets），零外部依赖

| 维度 | Dev 版 | Office 版 |
|---|---|---|
| 用户 | 开发者 / 技术团队 | 个人知识工作者 / 小团队 |
| 工作区 | 代码仓库 | 资料目录 / 网盘同步目录 |
| 文档类型 | SPEC / ADR / README / 接口文档 | 会议纪要 / 方案 / 模板 / 清单 |
| 技能类型 | 流程化脚本、检查器、生成器 | 汇报模板、写作套路、测算流程 |
| 记忆类型 | 踩坑、设计取舍、反模式 | 偏好、结论、常用口径 |
| 路由阈值 | `high=0.80 / low=0.50` | `high=0.80 / low=0.55`（不低于 Dev，见 N8） |
| 默认写入模式 | `plan`（V12 通过后逐工作区开启 `apply`） | `plan`（不建议开启 `apply`） |
| 从属物化默认 | `stub` | `none` |
| 会话 TTL | 7 天 | 14 天 |
| 术语映射 | 文档 / 技能 / 记忆 / 会话 | 资料 / 套路 / 要点 / 本次 |
| 差异化模块 | 断链、孤儿扫描、索引漂移 | 重复内容合并、模板复用 |

**共享**：内核脚本、路由引擎、数据库 schema、doctor 框架。**差异只在模板、词表、阈值。**

---

## 4. 能力边界

**做**：
- 扫描并登记一个工作区内的文档、技能、笔记
- 按判定树给出「主载体 + 从属归属」的判定与理由
- 生成/修正索引、检测断链与孤儿、检测技能触发词冲突
- 输出最小上下文包（`context pack`）供 AI 任务前加载
- 体检报告（免费引流款）

**不做**：
- 不做通用 RAG 检索服务，不托管用户的向量库
- 不上传用户内容（默认全本地；云端仅可选同步索引摘要）
- 不做交易域专用能力
- 不代替用户写业务代码

**「文档」的边界（评审 m6）**：
- 参与索引：文本类（`.md` `.txt` `.yaml` `.json` `.py` `.sh` 等），按扩展名白名单
- 仅登记元数据：二进制（`.pdf` `.png` `.xlsx` `.docx`），记录路径/大小/哈希，不抽取正文
- 正文抽取列为 Pro 能力，默认关闭；`config.yaml` 可显式开启并声明范围

---

## 5. 核心机制：主载体 + 从属引用

> v0.1 的「四路互斥」已在评审中被否决（M1）。v0.2 改为**主载体唯一，归属可以多个**；v0.3 补齐从属引用的物化策略与上限。

### 5.1 分流模型

| 概念 | 定义 | 约束 |
|---|---|---|
| 主载体 `primary` | 该内容的第一读者最先需要的那一个载体 | 唯一，取值 `skill / doc / memory / session` |
| 从属引用 `attachments[]` | 同一内容在其他载体的登记关系 | 0..3 条，超出需用户确认；只记录关系与指针，不复制正文 |
| 关系类型 `edge` | `references / implements / documented_by / derived_from / supersedes` | 固定枚举，禁止自由文本 |
| 物化策略 `materialize` | 从属引用是否要落地成文件 | `none`（只登记）/ `stub`（建标题+指针）/ `full`（生成正文）；**默认 Dev `stub` / Office `none`** |

示例：一份「发布检查清单」→ `primary=skill`，`attachments=[{route:doc, edge:documented_by, materialize:stub}]`。两部分都不丢，文档侧只生成带指针的骨架，不复制正文。

**易混点对照**：
- `attachments` = **同时成立**的归属（清单既是技能又是文档）
- `alternatives` = **互相竞争**的候选（0.82 判为技能，0.61 判为文档，二选一未定）

### 5.2 判定树

```
新信息进入
├─ D1 可复用性：是否包含可重复执行的流程？
│   ├─ 是 且 历史同指纹 executions ≥ 2 ──▶ primary=skill
│   ├─ 是 且 次数不足/未接入执行记录 ────▶ 候选 skill，requires_user_confirm=true
│   └─ 否 → 继续
├─ D2 稳定性：是否描述工作区的稳定事实？
│   ├─ 是 ──▶ primary=doc
│   └─ 否 → 继续
├─ D3 经验性：是否是取舍 / 坑 / 结论？
│   ├─ 是 ──▶ primary=memory（须过 §5.4 准入）
│   │        └─ 准入结果 unknown → state=pending，不写入检索
│   └─ 否 → 继续
└─ 默认 ──▶ primary=session（TTL 见 §5.6）
```

**重叠处理**：多项同时命中时，按「可复用性 > 稳定性 > 经验性」定 `primary`，其余命中项写入 `attachments[]` 并保留命中理由。**不允许因为选了主载体而丢弃其他归属。**

**优先级理由**：可复用流程的读者是"未来的执行者"，稳定性事实的读者是"当下的协作者"，经验结论的读者是"踩坑的人"。前者对上下文效率影响最大，因此排第一。

### 5.3 判据的可观测性（R2 / R6）

**原则：以「执行」为准，不以「路由」为准。** 系统不预测将来是否重复，只统计已发生的执行次数。

- `executions(intent_signature, executed_at, source)` 是唯一计数来源，`source ∈ {record, mark_done}`；**用户确认不属于执行，不得计入**
- `runs` 表只记录路由诊断，**不参与 D1 判定**（修复 v0.2 的循环依赖）
- D1 查询近 90 天同指纹的 `executions` 次数，并把实际计数写入 `evidence`
- 次数 `< 2`，或工作区从未接入执行记录 → `requires_user_confirm=true`，禁止自动判为 skill
- **降级声明**：若用户不启用 `cm mark-done` 也不主动确认，D1 永远不会自动成立。这是可接受的确定性降级，不得用「大概率会重复」替代。
- 用户确认一次后写入 `intent_confirms`，后续同指纹豁免确认，但**不增加执行计数**（确认 ≠ 执行）；确认有效期 90 天，`cm unconfirm` 可撤销
- `intent_signature` 规范见 `references/intent-signature.md`：中文按字 bigram + 英文小写分词、停用词表、50 条动词归一映射、`sha256` 取前 16 位十六进制；每工作区独立 salt，降低短文本字典反推风险
- 禁止在 `reasons` 中出现无数据支撑的「已重复 N 次」表述

### 5.4 准入四问（MEMORY 专用，默认拒绝）

| # | 问题 | 允许的判定结果 | 不通过的处理 |
|---|---|---|---|
| A1 | 模型 + 现有文档 + 一次检索能否推导？ | `derivable_from:[paths]` + 推导结果，或 `not_derivable` | `not_derivable` → 拒写 |
| A2 | 是否已有 SSoT？ | `ssot_path` 或 `none` | 有 SSoT → 只写指针，不复制内容 |
| A3 | 是否有可验证落点（文件/测试/指标）？ | `evidence_ref` 或 `none` | `none` → 降级 `observation`，置信度上限 0.5 |
| A4 | 六个月后是否仍有价值？ | `yes` / `no` / `unknown` | `no` → 不写；`unknown` → TTL ≤ 30 天 |

**A1 的硬约束（M3）**：
- A1 不接受自由文本，只接受 `derivable_from` 或 `not_derivable` 两类结果；
- 判为 `derivable_from` 必须给出真实存在的文件路径，且路径需可被索引校验，否则视为无效判定；
- 判定不确定时一律记为 `unknown`，进入 `pending` 状态，**不写入检索索引**；任意 `cm` 命令启动时扫描到期 `pending` 并提示，由 `cm triage` 批量复核（Skill 无守护进程，不依赖后台定时）；
- 禁止用 LLM 自评「我能推导」作为唯一证据。

### 5.5 路由输出契约（M4 / R1 / R3）

```json
{
  "schema_version": "1.1",
  "id": "rt-20261119-0001",
  "idempotency_key": "sha256:...",
  "apply_mode": "plan",
  "primary": "skill",
  "attachments": [
    {"route": "doc", "edge": "documented_by", "materialize": "stub",
     "target": {"path": "docs/checklist.md"}}
  ],
  "alternatives": [{"route": "doc", "confidence": 0.61}],
  "confidence": 0.82,
  "confidence_parts": {"evidence": 0.9, "consistency": 0.8, "history": 0.6, "conflict": 0.0},
  "evidence": [
    {"kind": "execution_count", "value": 3},
    {"kind": "file", "value": "docs/release.md"}
  ],
  "admission": {
    "passed": true,
    "checks": {"A1": {"result": "not_derivable"}, "A2": {"result": "none"}}
  },
  "requires_user_confirm": false,
  "target": {"path": "skills/release-check", "template": "skill-basic"},
  "next_action": "create_skill",
  "patch": {
    "summary": "新增 SKILL.md + scripts/release.sh",
    "files": [
      {"op": "create", "path": "skills/release-check/SKILL.md", "sha256": "..."},
      {"op": "modify", "path": "docs/checklist.md", "sha256": "..."}
    ]
  },
  "reasons": ["D1: 步骤稳定且近90天同指纹执行3次"]
}
```

**字段规则**：
- `idempotency_key` = `sha256(归一化内容 + primary + target.path)` 取前 32 位；同一 key 重复调用只允许产生一次写入（见 §12 V10）
- `evidence.kind` 固定枚举：`execution_count | file | derivation | user_confirm | route_run`
- `confidence_parts` 为必填，供复核；缺失即视为不可审计，路由结果不得进入 `apply`

### 5.5.1 `confidence` 计算（R3 / R7）

```
confidence = 0.35·evidence + 0.30·consistency + 0.20·history + 0.15·(1 − conflict)
```

| 分量 | 取值规则 |
|---|---|
| `evidence` | 有文件/执行记录 = 1.0；仅用户确认 = 0.6；无证据 = 0.3 |
| `consistency` | 判定树单一命中 = 1.0；多命中但主载体明确（有 attachments 支撑）= 0.8；多命中且主载体未定 = 0.5；无命中仅默认 = 0.2 |
| `history` | `min(executions / 5, 1.0)` |
| `conflict` | **仅**表示「候选互斥且未决」（`alternatives` 非空且接近）= 0.5；attachments 本身不扣分；否则 0 |

**R7 修正**：v0.3 的 `conflict` 把 attachments 也算作冲突，与 `consistency` 重复惩罚多归属场景。v0.4 改为：attachments 只影响 `consistency`（0.8），`conflict` 只反映真正的互斥未决。

**公式 → 阈值 → D1 联调表**（权重按默认值；`high = 0.80`）：

| 场景 | evidence | consistency | conflict | executions=2 | executions=3 | executions=5 | 何时达 high |
|---|---|---|---|---|---|---|---|
| 单一命中 | 1.0 | 1.0 | 0 | 0.88 | 0.92 | 1.00 | 第 2 次 |
| 多归属、主载体明确 | 1.0 | 0.8 | 0 | 0.82 | 0.86 | 0.94 | 第 2 次 |
| 多归属、主载体未定 | 1.0 | 0.5 | 0 | 0.67 | 0.71 | 0.79 | 不自动达 high（应转确认） |
| 候选互斥未决 | 1.0 | 0.5 | 0.5 | 0.595 | 0.635 | 0.715 | 不自动达 high（应转确认） |

结论：**满足 D1 的合法场景（单命中 / 多归属明确）在第 2 次执行即可达 `high`**；未定场景永远不自动执行，符合设计意图。

权重写入 `modes/*.yaml` 可调；每次路由必须落盘 `confidence_parts`。该公式不追求最优，但要求**可解释、可复算**，并由 V13 校准验收。

### 5.5.2 写入安全（R1 / R8）

| 条件 | `plan` 模式（默认，两个版本） | `apply` 模式（逐工作区显式开启） |
|---|---|---|
| `confidence ≥ high` 且 `requires_user_confirm=false` 且 `admission.passed=true` | 输出 patch 摘要与 diff，不落盘 | 落盘（先备份） |
| `low ≤ confidence < high`，或 `requires_user_confirm=true` | 输出建议，`next_action=ask_user` | 同左 |
| `confidence < low` | 不写入，仅返回 `alternatives` | 同左 |
| `admission` 含 `unknown` | 写入 `pending`，不进入检索 | 同左 |

- **默认写入模式：两个版本均为 `plan`**。`apply` 必须通过 `cm config apply=on` 逐工作区显式开启，前置条件是 V12 通过（修复 R8：默认 apply 会让门禁形同虚设）
- `patch.files[]` 必须带 `op ∈ {create, modify, delete}` 与 `sha256`；rollback 依据 op 执行（create→删除、modify→还原、delete→恢复），避免回滚后残留骨架文件
- `apply` 前把受影响文件快照到 `.cm/backup/<run_id>/`，并写入 `manifest.json`；`cm rollback <run_id>` 按 manifest 逆序执行
- 单次 `apply` 最多改动 **10 个文件**；超出强制降级为 `plan`
- 无 `patch` 字段的路由结果禁止 `apply`
- 「观察期」按 **`apply` 候选次数**计（即 confidence ≥ high 的次数），前 20 次强制 `plan`；普通 `route` 调用不计入

### 5.6 SESSION 治理（M5）

- SESSION 不是黑洞：默认 TTL **Dev 7 天 / Office 14 天**
- `cm doctor` 输出「待分拣会话条目数」
- `cm triage` 提供批量分拣：逐条给出建议主载体，用户一次性确认
- 到期未分拣的条目：**丢弃内容，仅保留「存在过」的计数痕迹**（不复制正文），避免二次膨胀
- `pending` 记忆同样由 `cm triage` 复核，超过 3 次复核仍为 `unknown` 则丢弃

### 5.7 最小上下文包

任务开始前只输出预算内内容，**默认上限 2000 tokens**。预算构成与裁剪顺序（评审 m2）：

| 组成 | 上限 | 说明 |
|---|---|---|
| 工作区入口索引 | 540 | 一级模块名 + 一句话，不做二级展开 |
| 命中文档片段 | 810 | Top-K=3；取 FTS5 命中高亮窗口所在段落，向前后各扩 1 段；单段 ≤270 tokens |
| 命中技能（名称 + 触发条件） | 270 | 不展开正文 |
| 相关记忆 | 180 | ≤3 条，需过相关性阈值 |

- token 计数使用 `cl100k_base` 近似；对不同模型偏差按 ±10% 处理，**设计配额合计 1800**（上表各项之和），2000 为硬上限
- 超预算时裁剪顺序：记忆 → 技能 → 文档片段（入口索引不裁）
- Office 工作区若无「模块」概念，入口索引降级为「一级目录 + 一句话」

---

## 6. 能力清单

### 6.1 MVP（文档 + 技能治理）

| 能力 | 命令 | 输出 |
|---|---|---|
| 初始化工作区 | `cm init --mode dev\|office` | `.cm/` + 默认配置 |
| 全量/增量扫描 | `cm scan` | 文件清单 + 哈希 + 分类 |
| 文档索引 | `cm index` | `docs` 表 + 断链 + 孤儿 |
| 技能索引 | `cm skill lint` | 触发词冲突 + 版本缺失 + 依赖断链 |
| 路由判定 | `cm route "<描述>"` | 结构化路由结果（§5.5） |
| 标记执行 | `cm mark-done "<描述>"` | 写入 `executions`，供 D1 计数（确认 ≠ 执行） |
| 回滚 | `cm rollback <run_id>` | 从 `.cm/backup/<run_id>/` 恢复受影响文件 |
| 会话/待定分拣 | `cm triage` | 批量分拣建议 + 确认 |
| 上下文包 | `cm pack "<任务>"` | ≤2000 tokens |
| 体检 | `cm doctor` | 五类指标 + 修复建议 |

### 6.2 Pro（记忆层，后置）

| 能力 | 命令 | 说明 |
|---|---|---|
| 记忆写入 | `cm remember` | 过准入四问，强制 `external_id` + 内容指纹去重 |
| 检索 | `cm recall` | 索引 → 关键词 → 语义三级降级 |
| 遗忘 | `cm forget` | TTL / 降级 / 痕迹池，只移出检索，不物理擦除 |
| 版本与取代 | `cm supersede` | 新结论取代旧结论，保留证据链 |
| 漂移检测 | `cm drift` | 记忆与文档 SSoT 不一致告警 |

---

## 7. 包结构

```
cognition-manager/
├── SKILL.md                  # 薄入口，< 500 行，只写触发条件与流程
├── manifest.yaml             # 版本 / 模式 / 依赖 / 权限
├── scripts/
│   ├── cm_cli.py             # 统一入口，无第三方依赖
│   ├── core/
│   │   ├── store.py          # SQLite + FTS5
│   │   ├── scanner.py        # 文件扫描与分类
│   │   ├── signature.py      # intent_signature 归一化与哈希
│   │   ├── router.py         # 主载体 + 从属引用判定
│   │   ├── admission.py      # 准入四问（含 pending）
│   │   ├── apply.py          # patch / 备份 / 回滚
│   │   ├── triage.py         # 会话/待定批量分拣
│   │   ├── doc_index.py      # 文档索引 / 断链 / 孤儿
│   │   ├── skill_lint.py     # 技能索引与冲突
│   │   └── packer.py         # 最小上下文包
│   └── modes/
│       ├── dev.yaml          # Dev 版阈值与词表
│       └── office.yaml       # Office 版阈值与词表
├── references/
│   ├── routing-matrix.md     # 完整判定矩阵与边界案例
│   ├── admission-rules.md    # 准入规则与反例
│   ├── confidence.md         # confidence 公式与权重（M2 交付）
│   ├── intent-signature.md   # 指纹归一化规范（M2 交付）
│   └── schema.md             # 数据表说明
└── assets/
    ├── templates/            # SPEC / ADR / INDEX / SKILL / 会议纪要
    ├── fixtures/             # 自检用样例工作区
    └── golden/               # 路由黄金集 + labeling-guide.md（M2 交付）
```

**约束**：
- `core` 仅使用 Python 标准库（`sqlite3`、`json`、`hashlib`、`pathlib`、`argparse`），对应 V6
- `extras`（可选安装）：语义检索与正文抽取；未安装时自动降级为 FTS5 与元数据登记，不影响 core 验收
- 不使用网络请求（extras 亦默认关闭）
- `SKILL.md` 采用渐进披露：正文只给流程，细则全部指向 `references/`

---

## 8. 数据与状态

状态全部在用户工作区 `.cm/` 内，可随仓库一起备份，默认不存正文副本：

```
.cm/
├── config.yaml     # 模式、预算、阈值、忽略规则、signature_salt
├── index.db        # SQLite（WAL）
├── traces/         # 路由与体检记录（jsonl，仅路径/哈希/理由）
├── backup/         # apply 前的受影响文件快照（<run_id>/）
└── cache/
```

**隐私约束（评审 m7 / N12）**：`traces/` 默认只记录路径、哈希、路由结果与理由，**不记录正文**；如需记录摘要，上限 200 字且可在 `config.yaml` 关闭。`intent_signature` 使用每工作区独立 `signature_salt`（存 `config.yaml`），降低短文本字典反推风险。

### 8.1 表结构（MVP）

```sql
docs(id, path, title, doc_type, module, tags, sha256, size, mtime, indexed_at, status)
skills(name, path, version, triggers_json, depends_on_json, provides_json,
       sha256, indexed_at, status)
edges(src, dst, kind, created_at)     -- src=引用方，dst=被引用方
                                      -- references | implements | documented_by | derived_from | supersedes
executions(id, intent_signature, executed_at, source)   -- D1 唯一计数来源；source ∈ {record, mark_done}
runs(id, intent_signature, route, confidence, outcome, created_at)  -- 仅诊断
intent_confirms(intent_signature, confirmed_at, expires_at)  -- 默认 90 天
sessions(id, content_ref, created_at, expires_at, triaged_at)
pending(id, kind, payload_ref, created_at, review_count, state)
```

**`edges` 方向约定（N13）**：

| kind | src → dst 含义 |
|---|---|
| `references` | 引用方 → 被引用的文档/技能 |
| `implements` | 技能 → 它实现的规范 |
| `documented_by` | 技能/记忆 → 描述它的文档 |
| `derived_from` | 派生内容 → 来源 |
| `supersedes` | 新内容 → 被取代的旧内容 |

### 8.2 状态机

| 对象 | 状态 |
|---|---|
| doc | `active` → `stale` → `orphan` → `archived` |
| skill | `draft` → `active` → `deprecated` → `archived` |
| memory（Pro） | `observation` → `inferred` → `verified` → `superseded` → `trace_only` |
| pending | `open` → `reviewed` → `accepted` / `dropped` |
| session | `open` → `triaged` / `expired` |

---

## 9. 关键流程

### 9.1 首次使用（体验优先）

```
cm init --mode dev
cm scan
cm doctor            # 立刻给出体检报告与 3 条最高优先级修复建议
```

首次体验必须满足：30 秒内看到一份「能读懂、有结论、有下一步」的报告。路由能力不在首次体验路径上。

### 9.2 日常

```
任务开始 → cm pack "<任务描述>"   # 最小上下文包
产出内容 → cm route "<内容摘要>"  # 主载体 + 从属归属判定
任务结束 → cm record --json       # 仅记录通过准入的内容
重复执行 → cm mark-done "<描述>"  # 写入 executions，供 D1 计数
低置信/待定 → cm triage          # 批量确认
```

### 9.3 周期体检

`cm doctor` 固定输出：

| 指标 | 含义 |
|---|---|
| 断链数 | 索引中指向不存在文件的条目 |
| 孤儿文件 | 存在但未登记的文件 |
| 索引漂移 | 文件哈希与索引不一致 |
| 技能冲突 | 触发词重叠 / 依赖缺失 / 版本冲突 |
| 会话待分拣 | 超过 TTL 50% 仍未分拣的会话条目数 |
| 待定积压 | `pending` 条目数与最老等待时长 |

---

## 10. SKILL.md 设计

### 10.1 Frontmatter

```yaml
name: cognition-manager
description: "上下文治理：判定信息的主载体与从属归属，分流到技能/文档/记忆/会话，并编译最小上下文包。用于工作区混乱、文档断链、技能重复、AI 反复摸索时。"
allowed-tools: Read, Write, Glob, Grep, Bash
```

### 10.2 触发条件（必写清）

- 「这个放哪」「要不要记」「文档太乱」「索引失效」
- 「有哪些技能重复」「触发器冲突」
- 「给我今天这次任务需要的上下文」
- 工作区首次接入

### 10.3 反触发（避免误调用）

- 单纯写代码、单纯查资料 → 不调用
- 单文件小修 → 不调用

---

## 11. 上架与商业化

平台现状（来源等级：**二手报道，需以官方文档复核**，对应评审 m1）：技能变现内测中，支持一次性买断或按月订阅，开发者自主定价（1–9999 元），微信签约结算并收取 1% 通道费，平台提供加密与云端执行以防复制。

| 档位 | 内容 | 建议价格 | 依据 |
|---|---|---|---|
| 免费 | `cm doctor` 体检 + 初始化 | 0 | 引流 |
| 买断 | 完整 MVP（文档 + 技能治理） | Dev 99 / Office 79（待前测验证） | 平台公开案例集中在 19–79 元；129 元缺少能力差证据，已下调 |
| 订阅 | 模板季度更新 + 记忆层 Pro + 多工作区 | 19–29 元/月 | 与同类订阅案例持平 |

**防复制策略**：
- 明文只放流程与模板；判定权重、阈值调优、评分函数以配置形式下发
- 高价值部分（语义检索、漂移检测）设计为可选云端能力，本地仅留调用壳
- 不在包内放任何内部仓库路径、SPEC 原文、交易域术语

---

## 12. 验收标准（可复核）

> v0.1 的 V4 为自建小样本自评，已作废（M6）。v0.3 全部标准要求：**固定 fixture + 固定环境 + 可重复执行 + 双标注 + 一致性门槛**。

| # | 标准 | 判定方式（可复现） |
|---|---|---|
| V1 | 首次体验 ≤ 30 秒 | 1000 文件 fixture，冷启动执行 `init+scan+doctor`，3 次取中位数；增量场景单独测 ≤ 5 秒 |
| V2 | 1000 文件索引 ≤ 3 秒 | 1000 个 1–50KB 文本文件；4 核 8G 基线机型；冷启动；3 次中位数 |
| V3 | 断链检测召回 100%、误报 0 | fixture = 30 条断链 + 200 条正常链接；分别计数 |
| V4 | 路由质量达标 | ≥100 条黄金集，四类各 ≥20；**双人独立标注**，先验一致性 **Cohen's κ ≥ 0.70** 才进入统计，分歧由第三人按 `labeling-guide.md` 裁定；报告 primary 的 precision ≥ 0.85、recall ≥ 0.80、F1 ≥ 0.82；多归属认领率（attachments 正确率）≥ 0.70；**同义表述召回率 ≥ 0.80**（同一意图 5 种说法命中同一 primary） |
| V5 | 上下文包 ≤ 2000 tokens | `cl100k_base` 计数；抽 20 个任务，90% 落在 1800–2000 区间 |
| V6 | core 零第三方依赖 | 干净 venv（仅标准库）运行全部 core 命令；AST 扫描 `core/` 的 import，0 命中；`extras` 不参与本项 |
| V7 | 双版本切换不改内核 | 仅改 `modes/*.yaml`；Dev ≥100 条、Office ≥80 条黄金集各自达标 |
| V8 | 无内部私有数据 | 敏感词扫描（内部模块名、绝对路径、`VM-` 前缀等）0 命中 |
| V9 | 异常路径不崩溃 | 12 例：空工作区 / 只读目录 / >10MB 文件 / 非 UTF-8 / 符号链接环 / 空格与中文文件名 / 大小写不敏感路径 / 权限拒绝 / 数据库损坏 / 并发写 / 磁盘空间不足 / 中断恢复；全部返回明确错误码。沙箱无法构造的项可标 `N/A`，**最多 3 项**且必须写明构造方法 |
| V10 | 路由幂等 | 同一输入重复调用 5 次：`id` 不同但 `idempotency_key` 相同，实际写入 1 次 |
| V11 | 用户价值成立 | 3 个真实工作区试用 ≥7 天；「重复摸索次数」下降 ≥30%，或用户主观评分 ≥4/5 |
| V12 | 自动写入不误伤 | `plan` 模式下人工抽检 **≥200 条**，严重误判 **0 起**且总体误判率 ≤2%，才允许对该工作区开启 `apply`；回滚 fixture 覆盖 create/modify/delete 三类操作，`cm rollback` 后文件哈希 100% 还原 |
| V13 | 置信度校准 | 按 `<low / low–high / ≥high` 三档统计实际精确率，需**单调递增**且高分组 ≥0.90；或期望校准误差 **ECE ≤0.15** |

**顺序要求**：V12 必须在 V11 之前完成（先证明不会误伤，再进入 7 天试用），否则试用期可能处于 `apply` 风险中。

**V11 是上架门槛，V12 是开启自动写入的门槛**：V11 未通过不得进入 M4；V12 未通过只能保持 `plan` 模式。

---

## 13. 风险与红线

| 风险 | 处理 |
|---|---|
| 直接搬内部代码导致隐私与耦合外泄 | 全部重写；内部模块只做规则来源 |
| SKILL.md 过长挤占上下文 | 正文 < 500 行，细则进 references |
| 办公用户不理解「技能/索引」 | Office 版词表映射 + 默认不暴露技术术语；M4 前必须完成前测 |
| 路由把分类不确定性转嫁给用户 | 低置信走 `ask_user`，不自动写入；`triage` 批量处理 |
| 记忆层承诺过高 | 记忆层列为 Pro，MVP 不承诺 |
| 平台加密/云端执行细则未明 | 第一版不依赖平台加密，核心逻辑本地也可降级运行 |
| 与平台内置能力重叠 | 只做「治理与路由」，不碰具体办公工具执行 |
| 竞品结论先行 | §2.2 矩阵标注为待复核，核对前不得用于营销 |

---

## 14. 里程碑

> M1 退出条件：先把首次体验做闭环，路由引擎后移到 M2。M0 只做定性前测，定量试用放在 M4（R5）。

| 阶段 | 产出 | 退出条件 |
|---|---|---|
| M0 | SPEC v0.4 + 三审闭环 + 竞品矩阵核对 + 3 工作区定性前测 + **平台沙箱能力 spike** | R7–R9 关闭；spike 结论明确（能否写 SQLite / 是否需改补丁模式）；产出前测问题清单；不要求 V11 |
| M1 | 体验闭环：`cm init` / `cm scan` / `cm doctor` | V1 / V6 / V8 通过；报告可读性评审通过 |
| M2 | 路由与写入安全：`cm route` / `cm triage` / `cm pack` / `cm mark-done` / `cm rollback` | V4 / V5 / V10 / V12（plan 侧）通过 |
| M3 | 治理：`cm index` / `cm skill lint` | V2 / V3 / V9 通过 |
| M4 | 双版本 + 上架包 + **定量试用** | V7 / V11 通过；V12 决定是否对该工作区开启 `apply`；提交平台审核 |
| M5 | 记忆层 Pro | 另行 SPEC |

---

## 15. 开放问题

1. 平台是否允许 Skill 携带多文件 Python 包与 SQLite 写入？若限制只读沙箱，需要改为「输出补丁 + 用户确认执行」。**已列为 M0 必做 spike，结论出来前 M1 不启动。**
2. 加密与云端执行的具体接入方式与限制。
3. Dev / Office 是否作为两个独立商品上架，还是一个商品内置模式切换。
4. 是否提供云端多工作区同步（涉及用户数据上传合规）。
5. 黄金集的双标注由谁执行（内部两人 / 外部试用者），成本归属。

---

## 16. 评审修订记录（M0 → v0.4）

| 评审 ID | 问题 | v0.2 处理 | 位置 |
|---|---|---|---|
| M1 | 四路互斥导致多归属丢失 | 改为主载体 + 从属引用 + edges | §5.1 / §5.2 / §8.1 |
| M2 | 「重复 ≥2 次」不可观测 | 接 `runs` 表 + `intent_confirms`，只报告历史计数 | §5.3 |
| M3 | A1 无判定主体、无不确定分支 | 只接受两类结果 + 路径校验 + `pending` | §5.4 |
| M4 | 契约字段缺失、阈值未定义 | 补全 schema + 三档阈值 + 幂等键 | §5.5 / §12 V10 |
| M5 | SESSION 无治理 | TTL + doctor 计数 + `cm triage` 批量分拣 | §5.6 / §6.1 / §8.1 |
| M6 | V4 自证、样本不足、指标单一 | ≥100 条双标注 + P/R/F1 + 多归属认领率 | §12 V4 |
| M7 | V2/V3/V5/V6 口径缺失 | 固定 fixture / 机型 / tokenizer / 干净 venv | §12 V2/V3/V5/V6 |
| M8 | 缺异常路径验收 | 新增 V9 十二条例外用例 | §12 V9 |
| m1 | 费率与定价来源 | 标注来源等级，价格下调并待验证 | §11 |
| m2 | token 预算无依据 | 补预算构成与裁剪顺序 | §5.7 |
| m3 | Office 阈值未给数值 | 双版本阈值表给具体值 | §3 / §5.5 |
| m4 | 缺竞品功能级对比 | 新增功能矩阵并标注待复核 | §2.2 |
| m5 | SKILL 写法不统一 | 顶部术语约定 | 头部 |
| m6 | 「文档」边界未定义 | 文本/二进制/抽取策略 | §4 |
| m7 | traces 隐私 | 默认不记正文，可关闭摘要 | §8 |
| m8 | 缺用户价值指标 | 新增 V11，作为上架必要条件 | §12 V11 |

### 第二轮（v0.2 → v0.3）

| 评审 ID | 问题 | v0.3 处理 | 位置 |
|---|---|---|---|
| R1 | 自动执行无 dry-run / 回滚 | 新增 `apply_mode(plan/apply)`、`patch` 字段、备份与 `cm rollback`；Office 默认 `plan`；前 20 次强制 `plan`；单次 ≤10 文件 | §5.5.2 / §6.1 / §8 |
| R2 | `runs` 计数循环依赖 | D1 改查 `executions`（执行事实），`runs` 仅诊断；明确「未接入则永远需确认」的降级声明 | §5.3 / §8.1 |
| R3 | `confidence` 无算法 | 给出四分量线性公式 + 权重可调 + 强制落盘 `confidence_parts` | §5.5.1 |
| R4 | 双标注缺规范与门槛 | 新增 `labeling-guide.md` 交付物 + Cohen's κ ≥ 0.70 + 裁定记录格式 | §7 / §12 V4 |
| R5 | M0 前测与 V11 冲突 | M0 改为定性访谈，定量试用移到 M4 | §14 |
| R6 | `intent_signature` 归一化未定义 | 给出分词/停用词/动词映射/sha256 截断/工作区 salt 规范 | §5.3 / §8 |
| N1 | attachments 物化未定义 | 新增 `materialize: none/stub/full`，默认 `stub` | §5.1 |
| N2 | P/A 编号混用 | 判定树改 D1–D3 | §5.2 |
| N3 | attachments 无上限 | 上限 3 条 | §5.1 |
| N4 | 幂等键构造未定义 | `sha256(归一化内容 + primary + target.path)[:32]` | §5.5 |
| N5 | pending 依赖主动调用 | 任意命令启动时扫描到期 pending | §5.4 |
| N6 | `evidence.kind` 未枚举 | 固定 5 类枚举 | §5.5 |
| N7 | alternatives 与 attachments 易混 | 补对照说明 | §5.1 |
| N8 | Office 阈值反向 | Office 不低于 Dev（0.80/0.55）+ 默认 `plan` | §3 / §5.5.2 |
| N9 | V9 部分用例难构造 | 允许标 `N/A` 并说明构造方法 | §12 V9 |
| N10 | 零依赖与 extras 矛盾 | core/extras 分层，V6 只验 core | §7 / §12 V6 |
| N11 | 缺自动写入错误率 | 新增 V12（plan 抽检误判 ≤5%，rollback 100% 还原） | §12 V12 |
| N12 | 短文本哈希可反推 | 每工作区独立 `signature_salt` | §8 |
| N13 | edges 方向未定义 | 补方向约定表 | §8.1 |
| N14 | 文档选段方式未定义 | FTS5 高亮窗口 ±1 段，单段 ≤300 tokens | §5.7 |
| N15 | Office 无「模块」概念 | 入口索引降级为一级目录 | §5.7 |

### 第三轮（v0.3 → v0.4）

| 评审 ID | 问题 | v0.4 处理 | 位置 |
|---|---|---|---|
| R7 | 公式与 D1/阈值未联调，多归属被双重扣分 | `conflict` 只表示互斥未决，attachments 不再扣分；`consistency` 分三档；新增联调表 | §5.5.1 |
| R8 | 默认 apply 与 V12 门禁冲突 | 两版默认 `plan`；`apply` 逐工作区显式开启，前置 V12 | §3 / §5.5.2 |
| R9 | 缺置信度校准验收 | 新增 V13（三档精确率单调 + 高分组 ≥0.90，或 ECE ≤0.15） | §12 V13 |
| n1 | `route_confirmed` 与「确认≠执行」矛盾 | 枚举改为 `{record, mark_done}` | §5.3 / §8.1 |
| n2 | 回滚不处理新建文件 | `patch.files[]` 带 `op` + `sha256`，按 op 逆向执行 | §5.5 / §5.5.2 |
| n3 | `intent_confirms` 无失效 | 90 天有效期 + `cm unconfirm` | §5.3 / §8.1 |
| n4 | V9 的 N/A 无上限 | 最多 3 项且需写明构造方法 | §12 V9 |
| n5 | 预算合计与 1800 矛盾 | 改为 540/810/270/180，2000 为硬上限 | §5.7 |
| n6 | `stub` 默认制造骨架垃圾 | Office 默认 `none` | §3 / §5.1 |
| n7 | 观察期计数口径不明 | 按 `apply` 候选次数计 | §5.5.2 |
| n8 | 平台沙箱未决却进 M1 | 列为 M0 必做 spike | §14 / §15 |
| n9 | V11/V12 无先后 | 明确 V12 先于 V11 | §12 |
| n10 | 50 条样本判 5% 不可靠 | ≥200 条 + 0 起严重误判 + 回滚三类 op 验证 | §12 V12 |

---

## 17. 参考

- [WorkBuddy 技能文档](https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)
- [WorkBuddy 技能开发结构](https://open.workbuddy.cn/docs/skill)
- [WorkBuddy 技能变现内测（二手报道）](https://www.cnblogs.com/behavioursblogs/articles/23433792)
- [Mem0 / Zep / Letta 对比](https://plur.ai/blog/mem0-vs-letta-vs-zep/)
