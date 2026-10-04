# Wiki P1+P2 增强 - Product Requirements Document

## Overview
- **Summary**: 针对千问评估提出的 P1（超时/索引同步/Lint调度）和 P2（可观测性/两步思维链/批量摄入）改进项，增强 Wiki 编译层的工程健壮性与可观测性。
- **Purpose**: 提升编译层在长任务、批量场景下的可靠性，增加可观测性支撑调试与质量监控。
- **Target Users**: DreamBuddy AI Agent、开发者、运维。

## Goals
- 超时可配置，ingest 长任务不被 30s 硬超时截断
- RAG 索引同步幂等，避免重复写入
- Lint 巡检生成健康评分 + 持久化报告
- 编译结果含耗时、页面清单、Token 估算
- 两步思维链摄入提升提取质量（可选）
- 批量摄入支持多素材顺序编译

## Non-Goals
- 不实现真正的异步任务队列（Celery/RQ），仅顺序批量处理
- 不修改 RAG 索引底层实现（ChromaDB/Whoosh）
- 不修改认知系统核心
- 两步思维链不强制，默认关闭

## Functional Requirements

- **FR-1 (超时)**: Harness plugin 的 IPC 超时可配置，ingest 默认 90s，query 默认 30s；WikiCompiler.ingest 内部记录耗时
- **FR-2 (索引幂等)**: `_sync_knowledge_graph` 中 build_keyword_index 调用前检查是否需要重建（基于文件 mtime 或跳过已索引文件），避免全量重复
- **FR-3 (Lint 健康报告)**: wiki_lint 返回 health_score（0-100），报告持久化到 `wiki/lint-reports/{timestamp}.json`
- **FR-4 (可观测性)**: CompileResult 增加 `duration_ms: float`、`pages: List[str]`（所有生成页面）、`token_estimate: int`
- **FR-5 (两步思维链)**: ingest 增加 `two_pass: bool = False` 参数，开启时先 LLM 分析素材结构再提取
- **FR-6 (批量摄入)**: WikiCompiler 增加 `ingest_batch(sources: List[str], source_type="auto") -> List[CompileResult]`

## Non-Functional Requirements
- **NFR-1 (FAIL-OPEN)**: 所有增强功能失败不影响核心编译
- **NFR-2 (向后兼容)**: 现有接口参数不变，新增参数均有默认值
- **NFR-3 (幂等)**: 索引同步和批量摄入可重复执行不产生副作用

## Acceptance Criteria

### AC-1: 超时可配置
- **Type**: `rule`
- **Given**: 调用 wiki_ingest 处理长素材
- **When**: IPC 调用
- **Then**: 超时阈值 ≥ 90s，不因 30s 硬超时失败
- **Pass Condition**: plugin 中 ingest 超时 ≥ 90s
- **Evidence**: 代码审查 index.js

### AC-2: 索引同步幂等
- **Type**: `rule`
- **Given**: 连续两次调用 ingest
- **When**: 第二次 ingest 触发索引同步
- **Then**: 不重复全量重建（检测到无新增文件则跳过或增量）
- **Pass Condition**: 第二次 ingest 的索引同步耗时显著低于第一次或日志显示跳过
- **Evidence**: 日志/耗时对比

### AC-3: Lint 健康评分
- **Type**: `rule`
- **Given**: 调用 wiki_lint
- **When**: 巡检完成
- **Then**: 返回 health_score（0-100），且报告写入 lint-reports/
- **Pass Condition**: 结果含 health_score 字段，lint-reports/ 下有 .json 文件
- **Evidence**: IPC 返回 + 文件系统

### AC-4: 可观测性字段
- **Type**: `rule`
- **Given**: ingest 完成
- **When**: 读取 CompileResult
- **Then**: 含 duration_ms > 0、pages 非空、token_estimate ≥ 0
- **Pass Condition**: 三个字段均有值
- **Evidence**: 单元测试输出

### AC-5: 两步思维链（可选）
- **Type**: `rule`
- **Given**: two_pass=True 且 LLM 可用
- **When**: ingest
- **Then**: 先调用 LLM 分析再提取；two_pass=False 时行为不变
- **Pass Condition**: two_pass=True 时 LLM 调用次数 ≥ 2
- **Evidence**: LLM 可用时验证（降级模式跳过）

### AC-6: 批量摄入
- **Type**: `rule`
- **Given**: ingest_batch([素材1, 素材2])
- **When**: 批量编译完成
- **Then**: 返回 2 个 CompileResult，均成功（或降级）
- **Pass Condition**: 结果列表长度 = 输入长度
- **Evidence**: 批量调用测试
