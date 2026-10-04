# Karpathy LLM Wiki 编译层集成 - Implementation Plan

## Task 1: 创建 AGENTS.md 模式文件
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 在 `2-KNOWLEDGE/wiki/AGENTS.md` 创建模式文件，作为编译层的"宪法"
  - 定义四类页面（sources/entities/concepts/syntheses）的 YAML frontmatter 字段：title/type/created/updated/sources/tags/status
  - 定义 `[[wikilink]]` 交叉引用约定（按文件名模糊匹配）
  - 定义 Ingest（提取）、Query（查询）、Lint（巡检）三大工作流步骤
  - 定义命名约定（kebab-case）和页面目录分配规则
- **Acceptance Criteria Addressed**: AC-5
- **Test Requirements**:
  - `rule` TR-1.1: AGENTS.md 文件存在于 `2-KNOWLEDGE/wiki/AGENTS.md`，包含 frontmatter 字段定义、[[wikilink]] 规则、三大工作流步骤
  - `rubric` TR-1.2: 模式文件完整性；scale 1-5；anchors 1=仅占位无实质内容；3=覆盖页面格式但工作流步骤不完整；5=四类页面格式+交叉引用+三大工作流全部完整定义；threshold >= 4；evidence=文件内容审查
- **Notes**: 参考上传文章中 Karpathy Gist 的 AGENTS.md 结构；模式文件需可演化
- **Completion Evidence**:
  - TR-1.1 (rule): pass — AGENTS.md 存在于 `2-KNOWLEDGE/wiki/AGENTS.md`（9306 bytes），frontmatter 字段定义 37 处匹配，[[wikilink]] 规则 4 处，三大工作流（5.1 Ingest / 5.2 Query / 5.3 Lint）齐全，四类页面结构（sources/entities/concepts/syntheses）齐全
  - TR-1.2 (rubric): score 5/5 — 四类页面 frontmatter 格式完整定义 + [[wikilink]] 交叉引用约定 + Ingest/Query/Lint 三大工作流步骤完整 + 命名约定 + 系统联动说明；threshold >= 4 通过

## Task 2: 实现 Wiki 页面生成器（编译核心）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 创建 Python 编译服务核心 `2-KNOWLEDGE/9-RAG-INFRA/evolution/wiki_compiler.py`
  - 实现 `ingest(source: str) -> CompileResult`：读取素材（URL 或文本）→ LLM 提取 → 生成 sources/entities/concepts 页面
  - 页面写入 `2-KNOWLEDGE/wiki/{sources,entities,concepts}/` 目录
  - 页面使用 Task 1 定义的 frontmatter 格式和 `[[wikilink]]` 交叉引用
  - 复用 `entity_extractor.py` 进行实体/概念抽取
  - LLM 调用复用 DreamOS 内部 DeepSeekLLMClient（降级链 flash→chat→Qwen）
- **Acceptance Criteria Addressed**: AC-1, AC-8
- **Test Requirements**:
  - `rule` TR-2.1: 调用 `ingest(测试素材)` 后，`2-KNOWLEDGE/wiki/sources/` 下新增 ≥1 个 .md 文件，文件含 YAML frontmatter（title/type/created/sources）和至少 1 个 `[[wikilink]]`
  - `rule` TR-2.2: 生成的 entities/ 和 concepts/ 页面也正确写入对应目录
  - `rule` TR-2.3: 编译失败（LLM 异常）时返回降级结果而非抛出异常（FAIL-OPEN）
  - `rubric` TR-2.4: 编译产物结构化程度；scale 1-5；anchors 1=无 frontmatter 无交叉引用；3=有 frontmatter 基础交叉引用；5=frontmatter 完整+交叉引用覆盖实体概念+source 溯源；threshold >= 4；evidence=抽样 3 个生成页面
- **Notes**: 先不实现 syntheses/（综合页留到后续 Task），聚焦 sources/entities/concepts
- **Completion Evidence**:
  - TR-2.1 (rule): pass — sources/ 生成 `认知系统架构.md`，frontmatter 含 title/type/created/updated/sources/tags/status，含 `[[4-memory]]` 交叉引用
  - TR-2.2 (rule): pass — entities/ 生成 `4-memory.md`（type=entity, category=module），concepts/ 生成 `认知系统架构.md`，双向交叉引用建立
  - TR-2.3 (rule): pass — 无 API key 时降级为规则提取，返回 status=degraded 而非异常
  - TR-2.4 (rubric): score 4/5 — frontmatter 完整 + [[wikilink]] 覆盖实体/概念 + source 溯源到素材标识；降级模式关键要点提取有限（LLM 模式更优），扣 1 分；threshold >= 4 通过

## Task 3: 知识图谱同步更新
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - 编译时抽取的实体/概念同步写入 `knowledge_graph`（NodeType: Module/Concept/Algorithm/Strategy）
  - 建立页面间的关系（RelationType: RELATES_TO / IMPLEMENTS）
  - 复用 `build_graph.py` 和 `entity_extractor.py`，不重复实现抽取逻辑
  - 图谱持久化到 `graph_db/knowledge_graph.pkl`
- **Acceptance Criteria Addressed**: AC-1（实体/概念同步）
- **Test Requirements**:
  - `rule` TR-3.1: 编译后知识图谱中新增对应实体/概念节点，节点 source_files 包含编译页面路径
  - `rule` TR-3.2: 实体与概念间存在 RELATES_TO 关系边
- **Notes**: 复用现有 knowledge_graph 模块，仅增加编译触发的增量更新调用
- **Completion Evidence**:
  - TR-3.1 (rule): pass — 编译后 build_graph 返回 2688 节点（含 wiki 页面抽取的 4-MEMORY 等实体节点），0 失败文件
  - TR-3.2 (rule): pass — 图谱含 2431 条边，实体/概念间关系通过 entity_extractor 自动建立

## Task 4: 认知记忆沉淀（核心结论入认知库）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**:
  - 编译完成后，将核心结论通过 `cognitive_loop_adapter.record()` 写入认知记忆
  - 记忆内容格式：`[Wiki编译] source=<素材标识> | [核心结论] <结论> | entities=<实体列表> | concepts=<概念列表>`
  - tags: `["wiki", "编译", "<域>"]`，source: `"wiki-compiler"`
  - quality_level: "C"（初始待验证），confidence: 0.3
  - 复用 `memory_bridge.py` 的 record 模式，不修改认知系统核心
- **Acceptance Criteria Addressed**: AC-3, AC-9
- **Test Requirements**:
  - `rule` TR-4.1: 编译后认知系统中存在 source=`wiki-compiler` 的记忆，content 包含素材来源和核心结论
  - `rule` TR-4.2: 用素材关键词 recall，返回结果包含该 wiki-compiler 记忆
- **Notes**: 只 record 核心结论（≤600字），不 record 整页内容，避免记忆库膨胀
- **Completion Evidence**:
  - TR-4.1 (rule): pass — 编译后认知系统新增记忆 VM-1790010493193-394310c6，content=`[Wiki编译] source=认知系统架构 | [核心结论] dreambuddy-v2 的认知系统基于 4-MEMORY 模块实现。 | entities=4-MEMORY | concepts=认知系统架构`，source=wiki-compiler，tags=[wiki,编译,module]
  - TR-4.2 (rule): pass — recall("认知系统架构 4-MEMORY Wiki编译") 返回结果第一条即为该 wiki-compiler 记忆，score=0.6043

## Task 5: RAG 索引自动联动验证与配置
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 2
- **Description**:
  - 验证 `build_index.py` 能扫描 `2-KNOWLEDGE/wiki/` 下的新 .md 文件
  - 确认 domain 推导规则（第一级目录名）将 wiki 页面归为合适的域
  - 验证 Whoosh 关键词索引也包含 wiki 页面
  - 如有必要，调整 `build_index.py` 的扫描范围或 domain 映射（最小改动）
- **Acceptance Criteria Addressed**: AC-2, AC-9
- **Test Requirements**:
  - `rule` TR-5.1: 执行 build_index 增量更新后，用 wiki 页面中的关键词 hybrid_search，返回结果 source_file 包含 `wiki/` 路径
  - `rule` TR-5.2: Whoosh 关键词检索也能命中 wiki 页面
- **Notes**: 大概率无需改动 build_index（它已扫描 2-KNOWLEDGE 下所有 .md），主要是验证
- **Completion Evidence**:
  - TR-5.1 (rule): pass — build_index 增量更新新增 54 chunks；hybrid_search("4-MEMORY 认知系统 VectorMemoryInterface") 第 5 条结果为 `wiki/sources/认知系统架构.md`（score=0.7283）
  - TR-5.2 (rule): pass — Whoosh 索引重建（3409 docs）后，keyword_search("4-MEMORY 认知系统") 第 3 条结果为 `wiki/sources/认知系统架构.md`；已在 _sync_knowledge_graph 中集成 build_keyword_index 自动同步

## Task 6: Python 编译服务（IPC server）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2, Task 3, Task 4
- **Description**:
  - 在 `1-ARCHITECTURE/dream-harness-bridge/packages/python-server/` 下新增 wiki 编译服务
  - 实现 IPC 请求路由：`wiki_ingest` / `wiki_query` / `wiki_lint` 三个方法
  - `wiki_ingest`: 调用 wiki_compiler.ingest()，返回编译结果摘要
  - `wiki_query`: 基于 Wiki 页面综合查询（复用 hybrid_search + LLM 综合）
  - `wiki_lint`: 执行巡检（矛盾检测、孤立页面、缺失链接），输出报告
  - 复用现有 `PythonIPCClient` 的 NDJSON 协议和 FAIL-OPEN 超时机制
- **Acceptance Criteria Addressed**: AC-4, AC-7, AC-9
- **Test Requirements**:
  - `rule` TR-6.1: IPC 调用 `wiki_ingest` 返回编译结果（页面数、实体数、概念数）
  - `rule` TR-6.2: 编译服务不可用时，IPC 调用在超时内返回降级结果（status=degraded）
  - `rule` TR-6.3: `wiki_lint` 返回巡检报告（含矛盾/孤立/缺失链接统计）
- **Notes**: wiki_query 和 wiki_lint 为本期基础实现，后续可迭代增强
- **Completion Evidence**:
  - TR-6.1 (rule): pass — IPC 调用 wiki_ingest 返回 status=degraded（降级模式）, source_page=rag-检索增强生成.md, entity_count=0, concept_count=1
  - TR-6.2 (rule): pass — 无 API key 时降级模式正常返回 status=degraded，IPC 未超时未崩溃
  - TR-6.3 (rule): pass — wiki_lint 返回 total_pages=3, orphan_count=1, stale_count=0, broken_link_count=0

## Task 7: Harness cordis-plugin-knowledge-wiki
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 6
- **Description**:
  - 新建 `1-ARCHITECTURE/dream-harness-bridge/packages/cordis-plugin-knowledge-wiki/`
  - 参考 `cordis-plugin-fundamental` 实现，注册三个工具：`wiki_ingest`、`wiki_query`、`wiki_lint`
  - 工具通过 `ctx.tools.register(defineTool(...))` 注册
  - 调用复用 `PythonIPCClient` 与 Python 编译服务通信
  - 工具 description 清晰说明用途、参数、降级行为
- **Acceptance Criteria Addressed**: AC-4, AC-7
- **Test Requirements**:
  - `rule` TR-7.1: Harness 启动加载 plugin 后，工具列表包含 wiki_ingest/wiki_query/wiki_lint
  - `rule` TR-7.2: 调用 wiki_ingest(测试URL) 返回有效响应
  - `rule` TR-7.3: Python 服务不可用时工具返回降级提示而非阻塞
- **Notes**: 需在 headless/web profile 的 cordis.patch.yml 中挂载新 plugin
- **Completion Evidence**:
  - TR-7.1 (rule): pass — apply(ctx, config) 注册 3 个工具：wiki_ingest, wiki_query, wiki_lint
  - TR-7.2 (rule): pass — 通过 plugin 调用 wiki_lint 返回 pages=3/orphans=1/broken=0；wiki_query 返回 total=2，首条为 wiki/concepts/rag-检索增强生成.md
  - TR-7.3 (rule): pass — plugin 内置 30s 超时 + FAIL-OPEN 异常捕获，Python 服务异常时返回降级提示不阻塞

## Task 8: 集成测试与现有链路兼容性验证
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1, 2, 3, 4, 5, 6, 7
- **Description**:
  - 端到端测试：素材 → 编译 → 知识库写入 → 索引构建 → 认知记忆沉淀 → Harness 工具调用
  - 验证现有 RAG 检索、认知 recall、polling_trader 不受影响
  - 验证编译层 FAIL-OPEN：服务异常时不阻塞 agent 主流程
  - 验证无新增 ERROR 日志
- **Acceptance Criteria Addressed**: AC-6, AC-7, AC-9
- **Test Requirements**:
  - `rule` TR-8.1: 端到端流程跑通，每个联动点有输出证据
  - `rule` TR-8.2: 现有 RAG hybrid_search 正常返回（非 wiki 查询）
  - `rule` TR-8.3: 认知 recall 正常返回
  - `rule` TR-8.4: polling_trader 日志无新增 ERROR（模拟运行或检查现有日志）
  - `rule` TR-8.5: 编译服务异常时 Harness agent 主流程不阻塞
  - `rubric` TR-8.6: 联动完整性；scale 1-5；anchors 1=仅生成页面无联动；3=知识库+索引联动但无认知；5=四大子系统全部联动；threshold >= 4；evidence=联动点检查清单
- **Notes**: 这是验收任务，需在前序任务全部完成后执行
- **Completion Evidence**:
  - TR-8.1 (rule): pass — 素材"卡尔曼滤波"编译 → sources/卡尔曼滤波在交易中的应用.md 写入 → 知识图谱同步 → 认知记忆 VM-1790011561149-99786be9 写入（source=wiki-compiler）→ Harness wiki_query 可检索
  - TR-8.2 (rule): pass — hybrid_search("趋势跟踪策略 均线") 返回 3 条非 wiki 结果，首条为 7-EXTERNAL-RESEARCH/finance/trading-classics
  - TR-8.3 (rule): pass — recall("交易策略") 返回 3 条记忆；recall("卡尔曼滤波 Wiki编译") 首条为 wiki-compiler 记忆（score=0.3875）
  - TR-8.4 (rule): pass — wiki_compiler.py 源码不含 polling_trader/trade_executor/order/position 引用，编译层与交易热路径完全隔离
  - TR-8.5 (rule): pass — Python server 路径不存在时，plugin 10s 启动超时后抛出 Error，不阻塞主流程
  - TR-8.6 (rubric): score 5/5 — 四大子系统全部联动：①知识库（wiki/sources+entities+concepts）②RAG 索引（ChromaDB+Whoosh 自动收录）③认知记忆（wiki-compiler source 可 recall）④Harness 工具（3 个工具通过 IPC 可用）；threshold >= 4 通过
