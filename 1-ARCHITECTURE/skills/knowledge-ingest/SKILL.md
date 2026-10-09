---
name: knowledge-ingest
description: "知识沉淀 SKILL: SKILL 执行完成后将产出的知识/案例分类入库 + RAG 向量化 + 认知记录 + 索引更新。Invoke when research-type SKILLs complete, cognitive record tags contain 'knowledge-ingest', or explicit knowledge ingestion needed."
version: 1.0.0
created: 2026-10-08
updated: 2026-10-08
license: Internal
status: active
category: knowledge
triggers: [知识沉淀, 知识入库, knowledge ingest, 调研入库, 知识归档]
depends_on: [build_index.py, cognitive_adapter.py, index_query_adapter.py]
provides: [knowledge-ingestion, rag-indexing, cognitive-knowledge-bridge]
cognitive_links: []
---

## Autonomy Boundary

可自主执行：
- 知识分类与目录路由
- .md 文件原子化存储（frontmatter + 正文）
- RAG 向量化（调用 build_index.py）
- 认知 record（tags 含 knowledge-ingest）
- 索引更新（IndexQueryService.reload）

需用户确认：
- 交易决策类知识入库（需人工审核后才可入库）
- 批量知识入库（>10 条）

禁止：
- 修改已有知识文件内容（HC-8: 只新增不修改）
- 删除知识库中的已有条目
- 将未审核的交易决策知识直接入库

---

# Knowledge Ingest SKILL — 知识沉淀

> SKILL 执行完成后（特别是调研类），将产出的知识/案例分类存入知识库 + 向量化 + 认知记录 + 索引更新，形成"执行→沉淀→复用"闭环。是 CognitiveContextBuilder 知识维度的数据来源。

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **调研类 SKILL 执行完成**：dream-research-workflow, dream-science-* 系列执行产出调研报告/案例/经验
2. **认知事件驱动**：认知系统 `record` 时 `tags` 含 `knowledge-ingest`，自动触发同步
   - **hook 配置**：`TAG_HOOKS = {"knowledge-ingest": "knowledge-ingest"}`
   - **FAIL-OPEN**：hook 异常不影响 record 主流程
3. **显式调用**：用户/上层编排器要求将特定内容入库

**不触发的场景**：
- 交易执行类任务（产出的是交易决策，非知识）
- 简单问答类任务（无知识沉淀价值）
- 纯代码变更（无文档/知识产出）

---

## 二、5 步标准流程

### 步骤 1：分类（确定入库目录）

**分类规则**：

| 内容类型 | 入库目录 | 判定关键词 |
|---------|---------|-----------|
| 交易策略类 | `2-KNOWLEDGE/1-TRADING/` | 策略、回测、仓位、风控、马丁、网格 |
| 外部调研类 | `2-KNOWLEDGE/7-EXTERNAL-RESEARCH/<domain>/` | 市场、竞品、行业、调研 |
| 方法论类 | `2-KNOWLEDGE/5-METHODOLOGY/` | 方法论、流程、TDD、开发规范 |
| AI 认知类 | `2-KNOWLEDGE/8-AI-COGNITION/` | 认知、记忆、进化、蒸馏 |
| 技术分析类 | `2-KNOWLEDGE/2-TECHNICAL/` | 技术指标、K线、趋势、支撑阻力 |
| 理论类 | `2-KNOWLEDGE/3-THEORY/` | 理论、模型、数学、统计 |

**交易决策类特殊处理**：
- 内容包含 `direction: LONG/SHORT`、`entry_price`、`stop_loss` 等交易指令字段 → 标记 `requires_human_review: true`
- 不自动入库，进入人工审核队列

### 步骤 2：原子化存储

1. 按知识颗粒度拆分为独立 `.md` 文件
2. 每个文件包含 frontmatter：
   ```yaml
   ---
   title: <知识标题>
   domain: <领域分类>
   tags: [<标签列表>]
   source: <来源 SKILL 或调研>
   created_at: <ISO 时间戳>
   requires_human_review: false  # 交易决策类为 true
   ---
   ```
3. 文件名格式：`YYYYMMDD-HHmm-<slug>.md`

### 步骤 3：向量化

调用 `2-KNOWLEDGE/9-RAG-INFRA/vector_store/build_index.py`：
- `build_index(knowledge_dir=<对应目录>, force=False)`
- 增量更新（md5 哈希对比，仅更新变化文件）
- 写入 ChromaDB collection

### 步骤 4：认知记录

调用 `callCognitive('record', ...)`：
- `content`: 知识摘要（≤300 字）
- `quality_level`: 'B'（待验证级）
- `tags`: `knowledge-ingest,<domain>`

### 步骤 5：索引更新

调用 `IndexQueryService.reload()`（通过 `index_query_adapter.py`）：
- 重新扫描 INDEX.md + skill-registry.json
- 更新 ChromaDB index collection

---

## 三、关键约束

- **HC-8**: 知识只新增不修改；交易决策类知识需人工审核
- 每条知识必须有 `source` 字段（来源 SKILL/调研）
- FAIL-OPEN: 任一步骤失败不阻塞主流程，记录错误日志
- 支持 `KNOWLEDGE_INGEST_ENABLED=false` 开关关闭

---

## 四、与现有机制的关系

- 复用 `dream-doc-sync-workflow` 的索引更新逻辑（但本 SKILL 专注知识入库，doc-sync 专注文档索引）
- 复用 `wiki-ingest-trigger` 的认知→Wiki 同步（补充了 wiki-ingest-trigger 只同步 Wiki 不入库知识库的缺口）
- 补充 `dream-research-workflow` 只 record 不入库的缺口
