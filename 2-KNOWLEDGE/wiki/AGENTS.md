# AGENTS.md — DreamBuddy Wiki 编译层操作手册

> 本文件是 LLM Wiki 编译层的模式文件（Schema），定义页面组织方式、格式约定和工作流。
> 编译层的核心理念：**提取时编译，而非查询时检索**。素材一次性编译为结构化、交叉引用的知识网络。

## 1. 系统概述

### 1.1 核心理念

- **持久化积累** vs RAG 的即时检索：知识在摄入时被编译为结构化 Wiki 页面，查询时直接基于已编译的知识网络回答
- **角色分工**：人类负责提供素材、提出问题、决策方向；LLM 负责阅读、摘要、抽取实体/概念、建立交叉引用、维护一致性
- **网络增长**：每个新素材不仅新增页面，还更新已有页面的交叉引用，知识网络密度指数增长

### 1.2 三层架构

| 层 | 路径 | 变易性 | 说明 |
|---|---|---|---|
| 原始素材层 | `2-KNOWLEDGE/7-EXTERNAL-RESEARCH/` + 现有业务文档 | 不可变 | 事实根基，LLM 只读不修改 |
| Wiki 知识网络层 | `2-KNOWLEDGE/wiki/` | 可增长 | LLM 生成的结构化页面集合，持续更新 |
| 模式文件层 | `2-KNOWLEDGE/wiki/AGENTS.md`（本文件） | 可演化 | 定义页面格式与工作流，修改即改变系统行为 |

## 2. 目录结构

```
2-KNOWLEDGE/wiki/
├── AGENTS.md          # 本文件（模式文件）
├── index.md           # 内容目录（所有页面的索引）
├── sources/           # 素材摘要页（每个素材 1 页）
├── entities/          # 实体页（人、组织、产品、策略、模块）
├── concepts/          # 概念页（理论、方法、算法、指标）
└── syntheses/         # 综合分析页（跨素材的洞见归档）
```

## 3. 页面格式规范

### 3.1 YAML Frontmatter

每个 Wiki 页面必须以 YAML frontmatter 开头：

```yaml
---
title: <页面标题>
type: <source|entity|concept|synthesis>
created: <YYYY-MM-DD>
updated: <YYYY-MM-DD>
sources:
  - <来源素材标识或 URL>
tags:
  - <标签1>
  - <标签2>
status: <active|stale|archived>
---
```

**字段说明**：

| 字段 | 必填 | 说明 |
|---|---|---|
| `title` | 是 | 页面标题，与文件名（去扩展名）一致 |
| `type` | 是 | 页面类型：`source`/`entity`/`concept`/`synthesis` |
| `created` | 是 | 创建日期，ISO 格式 |
| `updated` | 是 | 最后更新日期，ISO 格式 |
| `sources` | 是 | 来源素材列表（URL 或素材标识），用于溯源 |
| `tags` | 是 | 标签列表，用于分类检索 |
| `status` | 是 | `active`（活跃）/ `stale`（过时待更新）/ `archived`（归档） |

### 3.2 四类页面结构

#### sources/ 素材摘要页

```markdown
---
title: <素材标题>
type: source
created: <date>
updated: <date>
sources:
  - <原始 URL 或标识>
tags:
  - <域标签>
  - <主题标签>
status: active
---

## 核心论点
<一句话概括素材核心主张>

## 关键要点
- <要点 1>
- <要点 2>
- ...

## 详细笔记
<结构化的详细内容摘要>

## 涉及实体
- [[<实体1>]]
- [[<实体2>]]

## 涉及概念
- [[<概念1>]]
- [[<概念2>]]

## 关键引文
> <原文关键引文>
```

#### entities/ 实体页

```markdown
---
title: <实体名称>
type: entity
created: <date>
updated: <date>
sources:
  - <来源素材>
tags:
  - entity
  - <实体类别：person|org|product|strategy|module>
status: active
---

## 概述
<实体的一句话定义>

## 详细说明
<实体的背景、作用、与其他实体的关系>

## 关联概念
- [[<概念1>]]
- [[<概念2>]]

## 出现于
- [[<素材摘要页>]]
```

#### concepts/ 概念页

```markdown
---
title: <概念名称>
type: concept
created: <date>
updated: <date>
sources:
  - <来源素材>
tags:
  - concept
  - <概念类别：theory|method|algorithm|metric>
status: active
---

## 定义
<概念的精确定义>

## 核心要点
- <要点 1>
- <要点 2>

## 关联实体
- [[<实体1>]]

## 关联概念
- [[<概念1>]]

## 出现于
- [[<素材摘要页>]]
```

#### syntheses/ 综合分析页

```markdown
---
title: <综合主题>
type: synthesis
created: <date>
updated: <date>
sources:
  - <素材1>
  - <素材2>
tags:
  - synthesis
  - <主题标签>
status: active
---

## 问题陈述
<本次综合分析要回答的问题>

## 主要发现
1. <发现 1>（出处：[[<素材页>]]）
2. <发现 2>

## 分析
<跨素材的综合分析>

## 结论
<一句话总结>

## 引用页面
- [[<页面1>]]
- [[<页面2>]]
```

## 4. 交叉引用约定

### 4.1 `[[wikilink]]` 格式

- 页面正文中使用 `[[page-name]]` 格式引用其他 Wiki 页面
- 链接解析规则：按文件名（去 `.md` 扩展名）模糊匹配
- 示例：
  - `[[karpathy-llm-wiki-gist]]` → `wiki/sources/karpathy-llm-wiki-gist.md`
  - `[[andrej-karpathy]]` → `wiki/entities/andrej-karpathy.md`
  - `[[llm-wiki-pattern]]` → `wiki/concepts/llm-wiki-pattern.md`

### 4.2 交叉引用维护规则

1. **提取时**：新建页面必须包含指向相关已有页面的 `[[wikilink]]`
2. **双向更新**：新页面引用已有页面时，应在已有页面中补充反向链接（如"出现于"或"关联"部分）
3. **矛盾标注**：若新素材与已有页面内容矛盾，在相关页面标注 `> ⚠️ 矛盾：<矛盾描述>（出处：[[<新素材页>]]）`

## 5. 三大工作流

### 5.1 Ingest（提取）

**触发**：新素材摄入时（URL 或文本）

**步骤**：

1. **获取素材**：读取素材内容，保存为不可变原始记录
2. **阅读理解**：完整阅读素材，提取核心论点、关键要点
3. **创建素材摘要页**：在 `sources/` 创建摘要页，包含元信息、核心论点、关键要点、详细笔记、涉及实体与概念、关键引文
4. **抽取实体**：识别素材中的重要实体（人、组织、产品、策略、模块），在 `entities/` 创建或更新实体页
5. **抽取概念**：识别素材中的重要概念（理论、方法、算法、指标），在 `concepts/` 创建或更新概念页
6. **建立交叉引用**：
   - 摘要页引用所有相关实体/概念页
   - 实体/概念页反向引用摘要页
   - 检查已有页面，补充双向链接
7. **更新索引**：更新 `index.md` 目录
8. **沉淀认知记忆**：将核心结论写入认知系统（source=`wiki-compiler`）

**输出**：1 个 sources 页 + N 个 entities 页 + M 个 concepts 页 + 交叉引用网络

### 5.2 Query（查询）

**触发**：用户基于 Wiki 提问时

**步骤**：

1. **定位相关页面**：读取 `index.md`，扫描所有页面，识别相关页面
2. **读取页面内容**：批量读取相关页面
3. **综合分析**：跨页面综合，产出新洞见
4. **回答问题**：基于综合分析回答
5. **归档（可选）**：若分析产生有价值的新洞见，在 `syntheses/` 创建综合页
6. **更新索引与日志**：更新 `index.md`，记录查询日志

### 5.3 Lint（巡检）

**触发**：定期或手动触发

**检查项**：

| 维度 | 检查内容 | 处理方式 |
|---|---|---|
| 矛盾检测 | 页面间是否有矛盾陈述 | 生成矛盾报告，标注相关页面 |
| 过时信息 | `status: stale` 的页面、`updated` 超过 90 天的页面 | 标记待更新，报告给用户 |
| 孤立页面 | 没有入站 `[[wikilink]]` 的页面 | 自动补充链接或报告 |
| 缺失链接 | 页面中引用了不存在的 `[[wikilink]]` | 自动创建占位页或报告 |
| 缺失交叉引用 | 实体/概念页缺少"出现于"反向链接 | 自动补充 |

**处理原则**：
- 明显问题（缺失交叉引用、孤立页面）自动修复
- 需要判断的问题（矛盾、过时）生成报告供用户决策

## 6. 命名约定

- **文件名**：kebab-case，全小写，单词间用 `-` 连接
  - 示例：`karpathy-llm-wiki-gist.md`、`andrej-karpathy.md`、`llm-wiki-pattern.md`
- **页面目录分配**：
  - `sources/`：每个素材 1 页，文件名 = 素材标题的 kebab-case
  - `entities/`：每个实体 1 页，文件名 = 实体名的 kebab-case
  - `concepts/`：每个概念 1 页，文件名 = 概念名的 kebab-case
  - `syntheses/`：每次综合分析 1 页，文件名 = 综合主题的 kebab-case

## 7. 与现有系统的联动

### 7.1 知识库联动
- 编译产物写入 `2-KNOWLEDGE/wiki/`，作为知识库的一部分
- 自动被 `build_index.py` 扫描入 RAG 索引（ChromaDB + Whoosh）

### 7.2 认知系统联动
- 编译核心结论通过 `record()` 写入认知记忆（source=`wiki-compiler`）
- tags: `["wiki", "编译", "<域>"]`
- 初始 quality_level: `C`，后续通过 `verify()` 升级

### 7.3 知识图谱联动
- 实体/概念抽取复用 `entity_extractor.py`
- 抽取结果同步更新 `knowledge_graph`（NetworkX）

### 7.4 Harness 工具联动
- 通过 `cordis-plugin-knowledge-wiki` 暴露 `wiki_ingest` / `wiki_query` / `wiki_lint`

## 8. 模式文件可演化性

本文件（AGENTS.md）是可演化的。如需新增页面类型或调整工作流：

1. 修改本文件，新增页面类型定义或调整工作流步骤
2. 创建对应目录和模板
3. 编译核心自动遵循新规则（无需改动核心代码）

> 参考 Karpathy Gist 的"项目页"升级案例：用户发现缺少项目类型 → 修改 AGENTS.md → 系统自动遵循新规则。
