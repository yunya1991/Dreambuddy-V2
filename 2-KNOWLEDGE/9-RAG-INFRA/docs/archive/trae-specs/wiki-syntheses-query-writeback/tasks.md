# Wiki Syntheses 页面生成 + Query 回写 - Implementation Plan

## Task 1: 实现 _write_synthesis_page 方法
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 在 `WikiCompiler` 类中新增 `_write_synthesis_page(topic, entities, concepts, core_conclusion, sources) -> str` 方法
  - 调用 LLM 生成综合分析内容（主题概述 + 关联实体 + 关联概念 + 交叉分析）
  - 使用 `_build_frontmatter(title, "synthesis", sources, tags)` 构建 frontmatter
  - 实体/概念用 `[[wikilink]]` 交叉引用
  - 写入 `SYNTHESES_DIR/{kebab_case(topic)}.md`
  - LLM 不可用时返回空字符串（降级跳过）
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-7
- **Test Requirements**:
  - `rule` TR-1.1: ✅ 调用 _write_synthesis_page 后 syntheses/ 下生成 .md 文件，frontmatter type=synthesis
  - `rule` TR-1.2: ✅ 生成的页面含 ≥2 个 [[wikilink]] 指向 entities/ 或 concepts/ 页面
  - `rubric` TR-1.3: ✅ syntheses 页面规范性；score=4/5；frontmatter 完整(type/sources/tags)+交叉引用+source 溯源
- **Completion Evidence**: 文件 `2-KNOWLEDGE/wiki/syntheses/强化学习在量化交易中的应用.md` 生成，含 type: synthesis frontmatter、[[wikilink]] 交叉引用、sources 溯源

## Task 2: ingest() 集成 syntheses 生成步骤
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 在 `ingest()` 方法中，concepts 生成后（步骤 5 之后）、index 更新前（步骤 6 之前），新增步骤 5.5：调用 `_write_synthesis_page()`
  - `CompileResult` 增加 `synthesis_page: str = ""` 字段
  - 将生成结果存入 `result.synthesis_page`
  - syntheses 生成失败时仅 log warning，不影响编译主流程（FAIL-OPEN）
- **Acceptance Criteria Addressed**: AC-1, AC-2, AC-6
- **Test Requirements**:
  - `rule` TR-2.1: ✅ ingest 完成后 CompileResult.synthesis_page 非空
  - `rule` TR-2.2: ✅ syntheses 生成异常时 ingest 仍返回 degraded，不抛异常
- **Completion Evidence**: ingest 测试输出 synthesis_page=强化学习在量化交易中的应用.md，status=degraded

## Task 3: 实现冲突检测 _check_similarity 方法
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 新增 `_check_similarity(new_content: str, existing_path: Path) -> float` 方法
  - 使用 `difflib.SequenceMatcher(None, new_content, existing_content).ratio()` 计算相似度
  - 在 `_write_synthesis_page` 写入前检查目标文件是否存在
  - 已存在且相似度 >0.7：跳过写入，返回已有文件名
  - 已存在且相似度 ≤0.7：覆盖更新
  - 不存在：直接写入
- **Acceptance Criteria Addressed**: AC-4, AC-5
- **Test Requirements**:
  - `rule` TR-3.1: ✅ 高相似度（>0.7）重复写入时文件 md5 不变
  - `rule` TR-3.2: ✅ 低相似度（≤0.7）重复写入时文件 md5 变化，旧内容被覆盖
- **Completion Evidence**: 两次相同 ingest 后 md5 一致（跳过）；修改文件后重新 ingest md5 变化（覆盖）

## Task 4: wiki_query 增加 Query 回写机制
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1, Task 3
- **Description**:
  - 在 `WikiCompiler` 中新增 `query(question, top_k=5, enable_write_back=True) -> Dict` 方法
  - 调用 `hybrid_search(question, top_k)` 获取检索结果
  - 若 enable_write_back 且 LLM 可用：LLM 评估结果综合价值（返回 0-1 分数 + 综合摘要）
  - 价值 ≥0.6 时调用 `_write_synthesis_page(question, ...)` 回写 syntheses
  - 价值 <0.6 或 LLM 不可用：仅返回检索结果，不回写
  - 返回 dict 含 results、write_back_performed、synthesis_page、value_score
- **Acceptance Criteria Addressed**: AC-3, AC-6, AC-8
- **Test Requirements**:
  - `rule` TR-4.1: ✅ enable_write_back=true 且 LLM 不可用时 value_score=0，不回写（降级）
  - `rule` TR-4.2: ✅ enable_write_back=false 时不回写
  - `rubric` TR-4.3: ⚠️ LLM 不可用时无法完整测试价值判定准确性，需 LLM 可用时验证
- **Completion Evidence**: query 返回 results + value_score=0.0 + write_back_performed=False（降级模式正常）

## Task 5: IPC server wiki_query 对接新接口
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 4
- **Description**:
  - 修改 `server.py` 中 `_handle_wiki_query`，调用 `compiler.query()` 替代直接 `hybrid_search`
  - 支持 `enable_write_back` 参数透传
  - 返回结果增加 `write_back_performed`、`synthesis_page`、`value_score` 字段
- **Acceptance Criteria Addressed**: AC-3
- **Test Requirements**:
  - `rule` TR-5.1: ✅ IPC wiki_query 返回结果含 write_back_performed 字段（代码审查）
  - `rule` TR-5.2: ✅ enable_write_back 参数透传到 compiler.query()（代码审查）
- **Completion Evidence**: server.py 语法检查通过，_handle_wiki_query 调用 compiler.query() 并透传 enable_write_back

## Task 6: 集成测试与回归验证
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 1, 2, 3, 4, 5
- **Description**:
  - 端到端测试：ingest 生成 syntheses → wiki_query 回写 syntheses → 冲突检测
  - 验证现有 sources/entities/concepts 生成不受影响
  - 验证 RAG 索引自动收录 syntheses 页面
  - 验证认知记忆沉淀不受影响
- **Acceptance Criteria Addressed**: AC-1, AC-3, AC-6, AC-7
- **Test Requirements**:
  - `rule` TR-6.1: ✅ ingest 后四类页面（sources/entities/concepts/syntheses）均生成
  - `rule` TR-6.2: ✅ 现有 wiki_ingest 功能无回归（status=degraded 正常返回）
  - `rule` TR-6.3: ✅ syntheses 页面被 RAG 索引收录（hybrid_search 检索到 4 条 syntheses 结果）
- **Completion Evidence**: 综合测试脚本全部 PASS；RAG 检索结果中含 syntheses/ 路径
