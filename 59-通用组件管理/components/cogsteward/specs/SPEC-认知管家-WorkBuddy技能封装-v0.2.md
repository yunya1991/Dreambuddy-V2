# SPEC — 认知管家（CogSteward）WorkBuddy 技能封装

> **版本**: v0.2（M0 评审修订版）
> **日期**: 2026-11-19
> **状态**: 待复审（M1–M8 已关闭，见 §16）
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
| 路由阈值 | `high=0.80 / low=0.50` | `high=0.70 / low=0.45` |
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

> v0.1 的「四路互斥」已在评审中被否决（M1）。v0.2 改为：**主载体唯一，归属可以多个**。

### 5.1 分流模型

| 概念 | 定义 | 约束 |
|---|---|---|
| 主载体 `primary` | 该内容的第一读者最先需要的那一个载体 | 唯一，取值 `skill / doc / memory / session` |
| 从属引用 `attachments[]` | 同一内容在其他载体的登记关系 | 0..N，只记录关系与指针，不复制正文 |
| 关系类型 `edge` | `references / implements / documented_by / derived_from / supersedes` | 固定枚举，禁止自由文本 |

示例：一份「发布检查清单」→ `primary=skill`，`attachments=[{route:doc, edge:documented_by}]`。两部分都不丢。

### 5.2 判定树

```
新信息进入
├─ P1 可复用性：是否包含可重复执行的流程？
│   ├─ 是 且 历史同指纹任务 runs ≥ 2 ──▶ primary=skill
│   ├─ 是 且 次数不足/未知 ──────────▶ 候选 skill，requires_user_confirm=true
│   └─ 否 → 继续
├─ P2 稳定性：是否描述工作区的稳定事实？
│   ├─ 是 ──▶ primary=doc
│   └─ 否 → 继续
├─ P3 经验性：是否是取舍 / 坑 / 结论？
│   ├─ 是 ──▶ primary=memory（须过 §5.4 准入）
│   │        └─ 准入结果 unknown → state=pending，不写入检索
│   └─ 否 → 继续
└─ 默认 ──▶ primary=session（TTL 见 §5.7）
```

**重叠处理**：多项同时命中时，按「可复用性 > 稳定性 > 经验性」定 `primary`，其余命中项写入 `attachments[]` 并保留命中理由。**不允许因为选了主载体而丢弃其他归属。**

**优先级理由**：可复用流程的读者是"未来的执行者"，稳定性事实的读者是"当下的协作者"，经验结论的读者是"踩坑的人"。前者对上下文效率影响最大，因此排第一。

### 5.3 判据的可观测性（M2）

**系统不声称能预测"将来会重复"，只报告历史事实。**

- `runs` 表记录每次路由：`(intent_signature, route, created_at, outcome)`
- `intent_signature` = 归一化任务指纹：`hash(动词 + 对象 + 约束)`，同义动词归一
- 判定 P1 时查询**近 90 天**内同指纹的 `runs` 次数，并把实际计数写入 `evidence`
- 计数 `< 2` 或指纹首次出现 → `requires_user_confirm=true`，由用户确认一次；确认后写入 `intent_confirms` 表，后续同指纹直接复用
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
- 判定不确定时一律记为 `unknown`，进入 `pending` 状态，**不写入检索索引**，24 小时后由 `cm triage` 复核；
- 禁止用 LLM 自评「我能推导」作为唯一证据。

### 5.5 路由输出契约（M4）

```json
{
  "schema_version": "1.0",
  "id": "rt-20261119-0001",
  "idempotency_key": "sha256:...",
  "primary": "skill",
  "attachments": [
    {"route": "doc", "edge": "documented_by", "target": {"path": "docs/checklist.md"}}
  ],
  "confidence": 0.82,
  "alternatives": [{"route": "doc", "confidence": 0.61}],
  "evidence": [{"kind": "run_count", "value": 3}, {"kind": "file", "value": "docs/release.md"}],
  "admission": {
    "passed": true,
    "checks": {"A1": {"result": "not_derivable"}, "A2": {"result": "none"}}
  },
  "requires_user_confirm": false,
  "target": {"path": "skills/release-check", "template": "skill-basic"},
  "next_action": "create_skill",
  "reasons": ["P1: 步骤稳定且近90天同指纹执行3次"]
}
```

**阈值表**：

| 条件 | 行为 |
|---|---|
| `confidence ≥ high` 且 `requires_user_confirm=false` 且 `admission.passed=true` | 直接执行 `next_action` |
| `low ≤ confidence < high`，或 `requires_user_confirm=true` | 输出建议，`next_action=ask_user`，等待确认 |
| `confidence < low` | 不写入，仅返回 `alternatives` |
| `admission` 含 `unknown` | 写入 `pending`，不进入检索 |

`high/low` 取值见 §3 双版本表。同一 `idempotency_key` 重复调用只允许产生一次写入（见 §12 V10）。

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
| 工作区入口索引 | 600 | 一级模块名 + 一句话，不做二级展开 |
| 命中文档片段 | 900 | Top-K=3，按段落切分 |
| 命中技能（名称 + 触发条件） | 300 | 不展开正文 |
| 相关记忆 | 200 | ≤3 条，需过相关性阈值 |

- token 计数使用 `cl100k_base` 近似；对不同模型偏差按 ±10% 处理，实际按 1800 设计配额，留 10% 余量
- 超预算时裁剪顺序：记忆 → 技能 → 文档片段（入口索引不裁）

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
│   │   ├── router.py         # 主载体 + 从属引用判定
│   │   ├── admission.py      # 准入四问（含 pending）
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
│   └── schema.md             # 数据表说明
└── assets/
    ├── templates/            # SPEC / ADR / INDEX / SKILL / 会议纪要
    ├── fixtures/             # 自检用样例工作区
    └── golden/               # 路由黄金集与标注规范
```

**约束**：
- 仅使用 Python 标准库（`sqlite3`、`json`、`hashlib`、`pathlib`、`argparse`）
- 不使用网络请求；语义检索为可选扩展，缺失时自动降级为 FTS5
- `SKILL.md` 采用渐进披露：正文只给流程，细则全部指向 `references/`

---

## 8. 数据与状态

状态全部在用户工作区 `.cm/` 内，可随仓库一起备份，默认不存正文副本：

```
.cm/
├── config.yaml     # 模式、预算、阈值、忽略规则
├── index.db        # SQLite（WAL）
├── traces/         # 路由与体检记录（jsonl，仅路径/哈希/理由）
└── cache/
```

**隐私约束（评审 m7）**：`traces/` 默认只记录路径、哈希、路由结果与理由，**不记录正文**；如需记录摘要，上限 200 字且可在 `config.yaml` 关闭。

### 8.1 表结构（MVP）

```sql
docs(id, path, title, doc_type, module, tags, sha256, size, mtime, indexed_at, status)
skills(name, path, version, triggers_json, depends_on_json, provides_json,
       sha256, indexed_at, status)
edges(src, dst, kind)                 -- references | implements | documented_by | derived_from | supersedes
runs(id, intent_signature, route, confidence, outcome, created_at)
intent_confirms(intent_signature, confirmed_at, ttl_days)
sessions(id, content_ref, created_at, expires_at, triaged_at)
pending(id, kind, payload_ref, created_at, review_count, state)
```

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
低置信/待定 → cm triage          # 批量确认
任务结束 → cm record --json       # 仅记录通过准入的内容
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

> v0.1 的 V4 为自建小样本自评，已作废（M6）。v0.2 全部标准要求：**固定 fixture + 固定环境 + 可重复执行 + 双标注**。

| # | 标准 | 判定方式（可复现） |
|---|---|---|
| V1 | 首次体验 ≤ 30 秒 | 1000 文件 fixture，冷启动执行 `init+scan+doctor`，3 次取中位数；增量场景单独测 ≤ 5 秒 |
| V2 | 1000 文件索引 ≤ 3 秒 | 1000 个 1–50KB 文本文件；4 核 8G 基线机型；冷启动；3 次中位数 |
| V3 | 断链检测召回 100%、误报 0 | fixture = 30 条断链 + 200 条正常链接；分别计数 |
| V4 | 路由质量达标 | ≥100 条黄金集，四类各 ≥20；**双人独立标注**，分歧由第三人裁定；报告 primary 的 precision ≥ 0.85、recall ≥ 0.80、F1 ≥ 0.82；另报多归属认领率（attachments 正确率 ≥ 0.70） |
| V5 | 上下文包 ≤ 2000 tokens | `cl100k_base` 计数；抽 20 个任务，90% 落在 1800–2000 区间 |
| V6 | 零第三方依赖 | 干净 venv（仅标准库）运行全部命令；AST 扫描 import 白名单，0 命中 |
| V7 | 双版本切换不改内核 | 仅改 `modes/*.yaml`；Dev ≥100 条、Office ≥80 条黄金集各自达标 |
| V8 | 无内部私有数据 | 敏感词扫描（内部模块名、绝对路径、`VM-` 前缀等）0 命中 |
| V9 | 异常路径不崩溃 | 12 例：空工作区 / 只读目录 / >10MB 文件 / 非 UTF-8 / 符号链接环 / 空格与中文文件名 / 大小写不敏感路径 / 权限拒绝 / 数据库损坏 / 并发写 / 磁盘空间不足 / 中断恢复；全部返回明确错误码 |
| V10 | 路由幂等 | 同一输入重复调用 5 次：`id` 不同但 `idempotency_key` 相同，实际写入 1 次 |
| V11 | 用户价值成立 | 3 个真实工作区试用 ≥7 天；「重复摸索次数」下降 ≥30%，或用户主观评分 ≥4/5 |

**V11 是上架前的必要条件**：未通过不得进入 M4。

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

> M1 退出条件已按评审调整：先把首次体验做闭环，路由引擎后移到 M2。

| 阶段 | 产出 | 退出条件 |
|---|---|---|
| M0 | SPEC v0.2 + 评审复审 + 竞品矩阵核对 + 3 工作区前测 | M1–M8 关闭，V11 预演完成 |
| M1 | 体验闭环：`cm init` / `cm scan` / `cm doctor` | V1 / V6 / V8 通过；报告可读性评审通过 |
| M2 | 路由与打包：`cm route` / `cm triage` / `cm pack` | V4 / V5 / V10 通过 |
| M3 | 治理：`cm index` / `cm skill lint` | V2 / V3 / V9 通过 |
| M4 | 双版本 + 上架包 | V7 / V11 通过，提交平台审核 |
| M5 | 记忆层 Pro | 另行 SPEC |

---

## 15. 开放问题

1. 平台是否允许 Skill 携带多文件 Python 包与 SQLite 写入？若限制只读沙箱，需要改为「输出补丁 + 用户确认执行」。
2. 加密与云端执行的具体接入方式与限制。
3. Dev / Office 是否作为两个独立商品上架，还是一个商品内置模式切换。
4. 是否提供云端多工作区同步（涉及用户数据上传合规）。
5. 黄金集的双标注由谁执行（内部两人 / 外部试用者），成本归属。

---

## 16. 评审修订记录（M0 → v0.2）

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

---

## 17. 参考

- [WorkBuddy 技能文档](https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)
- [WorkBuddy 技能开发结构](https://open.workbuddy.cn/docs/skill)
- [WorkBuddy 技能变现内测（二手报道）](https://www.cnblogs.com/behavioursblogs/articles/23433792)
- [Mem0 / Zep / Letta 对比](https://plur.ai/blog/mem0-vs-letta-vs-zep/)
