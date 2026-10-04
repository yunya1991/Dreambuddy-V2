---
name: dream-doc-sync-workflow
description: "Orchestrates 7-step doc index sync: change parse → 0-系统文档管理/INDEX update → 2-KNOWLEDGE index update → doc_lint+link_checker validate → doc_coverage → feishu base sync → cognitive record. Invoke when docs are added/deleted/modified, or cognitive record tags contain 'doc-sync'."
version: 1.0.0
created: 2026-09-24
updated: 2026-09-24
license: Internal
status: active
category: orchestration
triggers: [文档同步, 更新索引, 文档索引治理, 同步知识库, doc sync, 更新文档索引]
depends_on: [doc_lint.py, doc_coverage.py, index_generator.py, link_checker.py, index-ops]
provides: [doc-index-sync, knowledge-base-sync, doc-index-governance]
cognitive_links: [VM-1790001702811-24bffe86, VM-1790003285544-0df90409]
---

# Dream Doc Sync Workflow — 文档索引同步工作流 SKILL

> 把"文档变更 → 0-系统文档管理/INDEX.md 更新 → 2-KNOWLEDGE 知识库索引更新 → 校验 → 覆盖率 → 飞书 Base 同步 → 认知闭环"的 7 步文档索引同步流程固化为可复用编排。本 SKILL 是认知系统与文档管理体系之间的桥梁，让认知系统 `record` 的经验能自动驱动文档索引/知识库同步。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-doc-sync-workflow/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/dream-doc-sync-workflow/SKILL.md`（项目级索引发现，本文件）

> **与 `dream-skill-index-governance` 的边界**：后者治理 SKILL 索引，本 SKILL 治理**文档索引**（0-系统文档管理 + 2-KNOWLEDGE）。两者同构但对象不同。

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **文档变更后同步**：新增/删除/修改了项目中的 `.md` 文档，需要更新索引
   - 触发词：「文档同步」「更新文档索引」「同步知识库」「doc sync」
2. **认知事件驱动**：认知系统 `record` 时 `tags` 含 `doc-sync`，自动触发同步
   - **实现方式**：`cognitive_mcp_server.py` 的 `_handle_record` 检测到 `tags` 含 `doc-sync` 时，返回值附带 `triggered_skills: ["dream-doc-sync-workflow"]` 信号，由上层 Agent（TRAE Skill 工具）自动加载并执行本 SKILL
   - **hook 配置**：`TAG_HOOKS = {"doc-sync": "dream-doc-sync-workflow"}`（可扩展）
   - **FAIL-OPEN**：hook 异常不影响 record 主流程，返回空触发列表
3. **定期巡检**：需要全量扫描文档结构，校验索引完整性并补齐缺失条目
   - 触发词：「文档索引治理」「索引巡检」「文档索引审计」
4. **飞书同步**：需要把本地文档索引变更同步到飞书 Base 状态面板

**不触发的场景**：
- 纯代码变更（无文档变更）→ 不调用本 SKILL
- 文档内容小修（不涉及新增/删除文件）→ 可选调用，仅更新版本头即可

---

## 二、7 步标准流程

### 步骤 1：变更解析（确定同步范围）

**输入**：变更信息（来自主动调用或认知 `record` 事件）

**处理**：

1. **主动调用模式**：用户提供变更文档路径列表
2. **认知事件模式**：从认知记忆中检索最近 `tags` 含 `doc-sync` 的记录，解析其 `content` 中的文档路径

**变更类型识别**：

| 类型 | 判定 | 同步动作 |
|------|------|---------|
| `add` | 新文件存在且未在索引中 | 新增索引条目 |
| `delete` | 文件不存在但在索引中 | 移除索引条目 |
| `modify` | 文件存在且已在索引中 | 更新版本/日期/链接 |
| `move` | 旧路径不存在 + 新路径存在 | 旧条目删除 + 新条目新增 |

**输出**：变更清单（YAML）

```yaml
changes:
  - path: <相对项目根的路径>
    type: add|delete|modify|move
    domain: trading|technical|theory|operations|chain|product|external|ai-cognition|doc-management
    old_path: <仅 move 时填>
```

**域判定规则**（用于步骤 3 路由到对应知识库）：

| 路径前缀 | 域 | 知识库 INDEX |
|----------|-----|-------------|
| `0-系统文档管理/` | doc-management | 0-系统文档管理/INDEX.md |
| `2-KNOWLEDGE/1-TRADING/` | trading | 2-KNOWLEDGE/1-TRADING/INDEX.md |
| `2-KNOWLEDGE/2-TECHNICAL/` | technical | 2-KNOWLEDGE/2-TECHNICAL/INDEX.md |
| `2-KNOWLEDGE/3-THEORY/` | theory | 2-KNOWLEDGE/3-THEORY/INDEX.md |
| `2-KNOWLEDGE/4-OPERATIONS/` | operations | 2-KNOWLEDGE/4-OPERATIONS/INDEX.md |
| `2-KNOWLEDGE/8-AI-COGNITION/` | ai-cognition | 2-KNOWLEDGE/8-AI-COGNITION/INDEX.md |
| `2-KNOWLEDGE/wiki/` | wiki | 2-KNOWLEDGE/wiki/index.md（仅更新元数据区） |
| `NN-子系统/docs/` | subsystem | 0-系统文档管理/INDEX.md（L2子系统表） |
| 其他 | uncategorized | 仅更新 0-系统文档管理/INDEX.md |

**Wiki 域特殊约定**：`wiki/index.md` 的页面列表由编译器自动维护，doc-sync **只更新元数据区**，用锚点限定修改范围：

```markdown
<!-- doc-sync-meta-start -->
> 最后同步：YYYY-MM-DD | 页面数：N | 来源：dream-doc-sync-workflow
<!-- doc-sync-meta-end -->
```

doc-sync 仅替换两个锚点之间的内容，不触碰编译器维护的页面列表区。

---

### 步骤 2：更新 0-系统文档管理/INDEX.md

**输入**：变更清单

**处理**：

1. 读取 `0-系统文档管理/INDEX.md`
2. 根据 `domain` 路由到对应章节：
   - `doc-management` → L0 顶层元文档表
   - `subsystem` → L2 子系统文档表（对应 `NN-子系统` 区块）
   - 其他 → 按主题索引表
3. 执行变更：
   - `add`：在对应表格末尾新增一行（文档名 / 路径 / 职责 / 状态）
   - `delete`：从表格中移除对应行
   - `modify`：更新版本号、更新日期、状态字段
   - `move`：删除旧路径行，在新位置新增行
4. 更新文档末尾的「文档覆盖率统计」表（调用 doc_coverage 结果）
5. 更新头部 `更新日期` 为当天

**校验规则**：
- 路径必须是相对 `0-系统文档管理/` 的相对路径
- 新增条目必须包含有效链接（步骤 4 会校验）

**输出**：更新后的 `0-系统文档管理/INDEX.md`

---

### 步骤 3：更新 2-KNOWLEDGE 知识库索引

**输入**：变更清单（`domain` 为 trading/technical/theory/operations/ai-cognition 的条目）

**处理**：

1. 读取对应域的 `INDEX.md`（如 `2-KNOWLEDGE/1-TRADING/INDEX.md`）
2. 执行变更：
   - `add`：在文件列表区新增条目（文件名 + 一句话说明 + 来源 SKILL）
   - `delete`：移除条目
   - `modify`：更新「最后更新」日期
3. 若涉及新增域目录，同步更新 `2-KNOWLEDGE/INDEX.md` 的目录结构段

**知识库文件命名约定**（来源 `2-KNOWLEDGE/INDEX.md` 建设原则）：
- 每个文件解决一个独立问题/概念，可独立引用
- 文件末尾注明 `最后更新：YYYY-MM-DD | 来源：<skill_name>`

**输出**：更新后的各域 `INDEX.md`

---

### 步骤 4：校验（doc_lint + link_checker）

**输入**：已更新的 INDEX.md 文件

**处理**：

```bash
# 1. 文档命名/格式/规范检查
python3 0-系统文档管理/4-工具与自动化/doc_lint.py 0-系统文档管理 2-KNOWLEDGE

# 2. 跨文档链接校验（重点检查新增/修改的链接）
python3 0-系统文档管理/4-工具与自动化/link_checker.py 0-系统文档管理 --summary
python3 0-系统文档管理/4-工具与自动化/link_checker.py 2-KNOWLEDGE --summary
```

**FAIL-OPEN 策略**：
- 校验发现断链 → 记录告警，**不阻塞**后续步骤，但在步骤 7 record 时标记 `doc-sync-warning`
- 校验发现命名违规 → 记录告警，建议修正但不阻塞

**输出**：校验报告（违规数 + 断链数）

---

### 步骤 5：覆盖率统计（doc_coverage）

**输入**：校验通过的索引

**处理**：

```bash
python3 0-系统文档管理/4-工具与自动化/doc_coverage.py --json /tmp/doc_coverage.json
```

**输出**：
- 更新 `0-系统文档管理/INDEX.md` 末尾的覆盖率统计表
- 输出覆盖率 JSON（用于飞书同步）

---

### 步骤 6：飞书 Base 同步（index-ops）

**输入**：覆盖率 JSON + 变更清单

**处理**：

1. 调用 `index-ops` 机制同步飞书 Base「索引清单」
2. 若 `index-ops` 不可用（SKILL 未安装），跳过并记录告警
3. 推送审计摘要到 Trading-Research 群（可选，由 index-ops 内部控制）

**FAIL-OPEN 策略**：
- 飞书同步失败 → 不阻塞，仅在步骤 7 record 时标记 `feishu-sync-failed`
- 下次同步时重试

**输出**：飞书同步结果（success / skipped / failed）

---

### 步骤 7：认知闭环（record）

**输入**：同步结果汇总

**处理**：

调用认知系统 `record` 记录同步结果，形成闭环：

```
record(
  content="[文档同步] 变更 <N> 项 | 0-系统文档管理/INDEX.md 已更新 | 知识库 <域列表> 已更新 | 校验: 违规<V> 断链<B> | 覆盖率 <X%> | 飞书: <success/skipped/failed>",
  quality_level="B",
  tags="doc-sync,文档索引,知识库同步,认知闭环,<域标签>"
)
```

**若有告警**，追加到 content：

```
| WARN: 断链 <N> 个 | WARN: 飞书同步失败
```

**输出**：认知记忆 ID

---

## 三、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | 变更路径列表 / 认知 doc-sync 事件 | 变更清单（YAML） |
| 步骤 2 | 变更清单 | 更新后的 0-系统文档管理/INDEX.md |
| 步骤 3 | 变更清单 | 更新后的 2-KNOWLEDGE/*/INDEX.md |
| 步骤 4 | 更新后的 INDEX 文件 | 校验报告（违规数 + 断链数） |
| 步骤 5 | 校验通过的索引 | 覆盖率 JSON + 更新统计表 |
| 步骤 6 | 覆盖率 JSON + 变更清单 | 飞书同步结果 |
| 步骤 7 | 同步结果汇总 | 认知记忆 ID |

---

## 四、相关 SKILL 与工具

| 类型 | 名称 | 用途 |
|------|------|------|
| 同构 | `dream-skill-index-governance` | SKILL 索引治理（对象不同，模式可复用） |
| 元 | `dream-qwen-eval-collab` | hermes 反思决策树来源 |
| 工具 | `doc_lint.py` | 文档命名/格式/规范检查 |
| 工具 | `doc_coverage.py` | 文档覆盖率统计 |
| 工具 | `index_generator.py` | 目录树生成 |
| 工具 | `link_checker.py` | 跨文档链接校验 |
| 工具 | `index-ops` | 飞书 Base 索引同步（可选依赖） |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 五、hermes 反思决策树

> 引用元 SKILL `dream-qwen-eval-collab` 第五节决策树（来源记忆 `VM-1790001702811-24bffe86`，B 级硬约束）。

```
本次文档同步流程是否值得形成/衍生 SKILL？
├── 是（满足以下任一）：
│   ├── 流程被复用 ≥ 2 次
│   ├── 涉及多步编排（≥ 3 步）
│   ├── 涉及外部工具调用（≥ 1 个 CLI 或飞书 API）
│   └── 用户明确要求「形成 SKILL」
│   → 调用 skill-creator 创建新 SKILL
│   → record 经验，tags 含「SKILL,hermes反思」
│
└── 否（满足以下全部）：
    ├── 一次性文档同步
    ├── 仅单步操作
    └── 无复用价值
    → 仅 record 经验
    → tags 不含「SKILL」
```

---

## 六、认知闭环（recall + record + verify）

**任务开始前**（硬约束，不可跳过）：

```
recall(context="文档同步 索引更新 知识库 <域关键词>", top_k=5, min_quality="C")
```

**任务完成后**（步骤 7）：

```
record(content="[文档同步] <变更摘要> | 校验: 违规<V> 断链<B> | 覆盖率 <X%> | 飞书: <结果>",
       quality_level="B",
       tags="doc-sync,文档索引,知识库同步,认知闭环,<域标签>")
```

---

## 七、FAIL-OPEN 与异常处理

| 异常场景 | 处理策略 |
|----------|---------|
| doc_lint 发现命名违规 | 告警记录，不阻塞，建议修正 |
| link_checker 发现断链 | 告警记录，不阻塞，标记 `doc-sync-warning` |
| doc_coverage 执行失败 | 跳过覆盖率更新，仅更新索引条目 |
| 飞书同步失败 | 不阻塞，标记 `feishu-sync-failed`，下次重试 |
| INDEX.md 格式解析失败 | 回退到手动编辑，record 告警 |
| 认知 record 失败 | 不阻塞同步流程，仅本地日志记录 |

**核心原则**：文档同步永不阻塞交易热路径，所有异常降级为告警。

---

## 八、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-24 | 初始版本，7 步流程 + 双触发模式 + 8 域路由 + FAIL-OPEN |
