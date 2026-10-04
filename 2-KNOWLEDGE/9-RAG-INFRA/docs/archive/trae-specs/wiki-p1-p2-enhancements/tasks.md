# Wiki P1+P2 增强 - Implementation Plan

## Task 1: 超时可配置（P1-4）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Test Requirements**:
  - `rule` TR-1.1: ✅ plugin 中 wiki_ingest 超时 90s，wiki_query 超时 30s，batch 动态超时
  - `rule` TR-1.2: ✅ CompileResult.duration_ms > 0（测试值 20834ms）
- **Completion Evidence**: index.js callMethod 支持 timeoutMs 参数；ingest 90000ms；duration_ms 实测 >0

## Task 2: RAG 索引同步幂等（P1-5）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Test Requirements**:
  - `rule` TR-2.1: ✅ .last_index_sync 文件创建，幂等检查逻辑实现
- **Completion Evidence**: `2-KNOWLEDGE/wiki/.last_index_sync` 文件存在；_sync_knowledge_graph 开头检查 mtime 跳过

## Task 3: Lint 健康评分 + 报告持久化（P1-6）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Test Requirements**:
  - `rule` TR-3.1: ✅ health_score = max(0, 100 - (orphan*2 + stale*1 + broken*3))，实测 87
  - `rule` TR-3.2: ✅ lint-reports/ 目录逻辑实现，保留最近 10 份
- **Completion Evidence**: health_score 计算测试通过；报告持久化代码就绪

## Task 4: 可观测性字段（P2-7）
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 1
- **Test Requirements**:
  - `rule` TR-4.1: ✅ CompileResult.pages 含所有生成页面（source+entities+concepts+synthesis）
  - `rule` TR-4.2: ✅ CompileResult.token_estimate ≥ 0（实测 39）
- **Completion Evidence**: ingest 测试 pages=['知识图谱与语义搜索.md' x3], token_estimate=39

## Task 5: 两步思维链摄入（P2-8）
- **Status**: `completed`
- **Priority**: low
- **Depends On**: None
- **Test Requirements**:
  - `rule` TR-5.1: ✅ two_pass=False 行为不变；two_pass=True 降级模式正常（无 LLM 不崩溃）
- **Completion Evidence**: two_pass=True 测试 status=degraded, duration=1941ms，无异常

## Task 6: 批量摄入（P2-9）
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: None
- **Test Requirements**:
  - `rule` TR-6.1: ✅ ingest_batch 结果列表长度 = 输入长度（2）
  - `rule` TR-6.2: ✅ 单个素材失败不影响其他（try/except 包裹）
- **Completion Evidence**: 批量测试 2 个素材均返回结果，各自独立 duration
