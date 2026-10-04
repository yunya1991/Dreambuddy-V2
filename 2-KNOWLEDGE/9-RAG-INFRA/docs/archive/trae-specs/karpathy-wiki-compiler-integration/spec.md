# Karpathy LLM Wiki 编译层集成 - Product Requirements Document

## Overview
- **Summary**: 在 dreambuddy-v2 现有知识系统（知识库 2-KNOWLEDGE/、认知系统 4-MEMORY/、RAG 索引 9-RAG-INFRA/、Harness 桥接层）之上，新增 Karpathy 风格的 LLM Wiki 编译层，将素材"提取时编译"为结构化、交叉引用的知识网络，并通过 DeepSeek Harness 暴露为可调用工具。
- **Purpose**: 弥补现有 RAG"查询时检索"模式的不足——每次查询从零开始检索原始文档、知识不积累、查询不产生新知识。编译层将素材一次性编译为 sources/entities/concepts/syntheses 页面，实现"一次编译、持续复用、网络密度指数增长"。
- **Target Users**: DreamBuddy 交易系统的 AI Agent（通过 Harness 工具调用）、开发者（通过 CLI/MCP 手动触发编译与巡检）。

## Goals
- 在素材摄入时自动编译生成结构化 Wiki 页面（sources/entities/concepts/syntheses），并建立 `[[wikilink]]` 交叉引用
- 编译产物自动联动现有三大子系统：写入知识库、沉淀为认知记忆、进入 RAG 索引
- 通过 DeepSeek Harness 暴露 `wiki_ingest` / `wiki_query` / `wiki_lint` 三个工具
- 提供 AGENTS.md 模式文件作为 LLM 操作手册，定义页面格式与工作流
- 不破坏现有交易热路径，编译层为异步离线流程，FAIL-OPEN

## Non-Goals
- 不替代现有 RAG 检索引擎（编译层是前置增强，检索仍走 RAG）
- 不修改 4-MEMORY 认知系统核心代码（仅通过 MCP 接口 record/recall/verify）
- 不接入 polling_trader 交易热路径（编译层独立异步运行）
- 不实现 Wiki 浏览器前端（文章中提到的 browser.py 不在本期范围）
- 不实现 projects/ 项目页类型（本期聚焦 sources/entities/concepts/syntheses 四类）

## Background & Context
- dreambuddy-v2 已有四大知识子系统：
  1. **知识库** `2-KNOWLEDGE/`：按业务域分类的 Markdown 文档（策略文档、CBR 案例、外部调研），是 RAG 数据源
  2. **认知系统** `4-MEMORY/`：SQLite + 向量记忆库，5 个 MCP 工具（recall/record/verify/stats/health），贝叶斯置信度更新 + 蒸馏
  3. **RAG 索引** `2-KNOWLEDGE/9-RAG-INFRA/`：ChromaDB 向量 + Whoosh BM25 + NetworkX 知识图谱三路混合检索，`memory_bridge.py` 实现 RAG↔认知双向桥接
  4. **Harness 桥接层** `1-ARCHITECTURE/dream-harness-bridge/`：Cordis plugin + IPC，通过 `ctx.tools.register(defineTool(...))` 暴露工具
- 现有模式是"查询时检索 + 检索后蒸馏"，缺少"摄入时编译"步骤
- Karpathy LLM Wiki 核心：raw/（不可变素材）+ wiki/（LLM 生成知识网络）+ AGENTS.md（模式文件），三大操作 Ingest/Query/Lint

## Functional Requirements

- **FR-1**: 编译层将输入素材（URL 或文本）编译为四类 Wiki 页面：`sources/`（素材摘要）、`entities/`（实体页）、`concepts/`（概念页）、`syntheses/`（综合分析页）
- **FR-2**: 编译生成的页面写入 `2-KNOWLEDGE/wiki/` 目录，使用 YAML frontmatter（title/type/created/updated/sources/tags/status）和 `[[wikilink]]` 交叉引用
- **FR-3**: 实体/概念抽取复用现有 `knowledge_graph/entity_extractor.py`，抽取结果同步更新知识图谱
- **FR-4**: 新生成的 Wiki 页面自动被 `build_index.py` 扫描入 ChromaDB 向量索引和 Whoosh 关键词索引（md5 增量更新，无需额外开发）
- **FR-5**: 编译抽取的核心结论通过认知系统 `record()` 写入记忆库（tags 含 `wiki,编译,<域>`，source=`wiki-compiler`），后续可 `verify()` 升级
- **FR-6**: 通过 DeepSeek Harness 暴露三个工具：`wiki_ingest`（触发编译）、`wiki_query`（基于 Wiki 综合查询）、`wiki_lint`（触发巡检）
- **FR-7**: Harness 工具调用复用现有 IPC 模式（`PythonIPCClient` + NDJSON stdin/stdout），Python 侧实现编译服务
- **FR-8**: 提供 `AGENTS.md` 模式文件，定义页面格式规范、交叉引用约定、Ingest/Query/Lint 工作流步骤
- **FR-9**: `wiki_lint` 巡检检测矛盾、标记过时、发现孤立页面、补充缺失链接

## Non-Functional Requirements

- **NFR-1 (FAIL-OPEN)**: 编译服务异常时工具调用返回降级结果，不阻塞 Harness agent 主流程
- **NFR-2 (不侵入)**: 不修改 4-MEMORY 认知系统核心、不修改 polling_trader 交易热路径
- **NFR-3 (可追溯)**: 每个编译产物页面带 source 溯源，认知记忆带素材来源映射
- **NFR-4 (可演化)**: AGENTS.md 模式文件可扩展，新增页面类型无需改动编译核心
- **NFR-5 (隔离)**: 编译产物存储在 `2-KNOWLEDGE/wiki/` 独立目录，不污染现有业务文档

## Constraints
- **Technical**: 复用现有 DeepSeekLLMClient（降级链 flash→chat→Qwen）；复用 ChromaDB/Whoosh/NetworkX；IPC 用 NDJSON
- **Business**: 编译层为离线异步流程，不影响实盘交易决策；认知记忆只 record 核心结论而非整页，避免记忆库膨胀
- **Dependencies**: 依赖 `2-KNOWLEDGE/9-RAG-INFRA/knowledge_graph/entity_extractor.py`、`4-MEMORY/9-工具与接口/cognitive_loop_entry.py`、`1-ARCHITECTURE/dream-harness-bridge/integration/cognitive_loop_adapter.py`

## Assumptions
- 现有 `build_index.py` 的 md5 增量更新能正确处理 `2-KNOWLEDGE/wiki/` 下的新文件
- `cognitive_loop_adapter.py` 的 record 接口可直接被编译服务调用
- DeepSeek Harness 的 cordis plugin 工具注册模式与 `cordis-plugin-fundamental` 一致
- LLM 编译质量可通过 Lint 巡检 + 认知 verify 闭环保障

## Acceptance Criteria

### AC-1: 编译生成四类 Wiki 页面
- **Type**: `rule`
- **Given**: 输入一篇素材（URL 或文本）
- **When**: 调用 `wiki_ingest` 触发编译
- **Then**: 在 `2-KNOWLEDGE/wiki/` 下生成至少 1 个 sources/ 页面，且抽取到的实体/概念分别写入 entities/ 和 concepts/ 目录
- **Pass Condition**: 编译后 `sources/` 目录新增 ≥1 个 .md 文件，文件含 YAML frontmatter 和 `[[wikilink]]`
- **Evidence**: 检查文件系统 + 文件内容

### AC-2: 编译产物自动入 RAG 索引
- **Type**: `rule`
- **Given**: `2-KNOWLEDGE/wiki/` 下有新生成的 Wiki 页面
- **When**: 执行 `build_index.py` 增量更新
- **Then**: 新页面的 chunks 出现在 ChromaDB 中，可被 `hybrid_search` 检索到
- **Pass Condition**: 用新页面中的关键词检索，返回结果包含该页面
- **Evidence**: `hybrid_search` 返回结果的 source_file 包含 wiki/ 路径

### AC-3: 核心结论沉淀为认知记忆
- **Type**: `rule`
- **Given**: 编译过程抽取了核心结论
- **When**: 编译完成
- **Then**: 认知系统中存在一条 source=`wiki-compiler` 的记忆，内容包含素材来源和核心结论
- **Pass Condition**: `recall` 检索该素材关键词，返回结果中含 source=wiki-compiler 的记忆
- **Evidence**: 认知系统 recall 结果

### AC-4: Harness 暴露 wiki 工具
- **Type**: `rule`
- **Given**: Harness 启动并加载 knowledge-wiki plugin
- **When**: agent 查询可用工具列表
- **Then**: 工具列表包含 `wiki_ingest`、`wiki_query`、`wiki_lint`
- **Pass Condition**: 三个工具均可被 agent 调用且返回有效响应
- **Evidence**: 工具调用日志 + 返回值

### AC-5: AGENTS.md 模式文件定义完整
- **Type**: `rule`
- **Given**: 项目中存在 AGENTS.md
- **When**: 读取该文件
- **Then**: 文件包含页面格式规范（frontmatter 字段）、交叉引用约定（[[wikilink]] 规则）、Ingest/Query/Lint 三大工作流步骤
- **Pass Condition**: 文件覆盖四类页面的 frontmatter 定义和三大工作流的步骤描述
- **Evidence**: 文件内容检查

### AC-6: 编译层不破坏现有链路
- **Type**: `rule`
- **Given**: 编译层已部署
- **When**: 现有 RAG 检索、认知 recall、polling_trader 运行
- **Then**: 现有功能不受影响，无新增报错
- **Pass Condition**: RAG 检索正常返回、认知 recall 正常、trader 日志无 ERROR
- **Evidence**: 现有测试通过 + trader 日志检查

### AC-7: FAIL-OPEN 降级
- **Type**: `rule`
- **Given**: 编译服务不可用（进程崩溃或超时）
- **When**: agent 调用 wiki_ingest
- **Then**: 工具调用返回降级结果（非异常抛出），agent 主流程继续
- **Pass Condition**: 调用在超时时间内返回，不阻塞 agent
- **Evidence**: 模拟服务不可用后的调用返回

### AC-8: 编译质量与可追溯性
- **Type**: `rubric`
- **Dimension**: 编译产物的结构化程度与溯源完整性
- **Scale**: 1-5
- **Anchors**: 1 = 页面无 frontmatter、无交叉引用、无 source 溯源；3 = 有 frontmatter 和基础交叉引用，source 溯源不完整；5 = frontmatter 完整、交叉引用覆盖实体/概念、source 溯源到原始素材
- **Pass Threshold**: >= 4
- **Evidence**: 抽样检查编译生成的 3 个页面

### AC-9: 与现有知识系统的联动深度
- **Type**: `rubric`
- **Dimension**: 编译层与知识库/认知/索引/Harness 的联动完整性
- **Scale**: 1-5
- **Anchors**: 1 = 仅生成页面，无任何联动；3 = 页面写入知识库且入索引，但未沉淀认知记忆；5 = 四大子系统全部联动（知识库写入+索引自动构建+认知记忆沉淀+Harness工具暴露）
- **Pass Threshold**: >= 4
- **Evidence**: 联动点检查清单

## Open Questions
- [ ] 编译服务的 LLM 调用是复用 DreamOS 内部 DeepSeekLLMClient 还是 Harness 侧 deepseek-flash？（倾向复用内部以保持降级链一致）
- [ ] `wiki_query` 是否需要将查询结果也归档为 syntheses/ 综合页？（Karpathy 模式支持，但会增加认知记忆量）
- [ ] Lint 巡检的触发频率（手动触发 vs 定时 cron）？
- [ ] 是否需要为编译产物建立独立的 retrieval_memory_map 映射（类似 RAG 的 memory_bridge）？
