# 24-图结构上下文压缩 — 变更记录

> **文档版本**: v1.0  
> **更新日期**: 2026-09-30

---

## v1.0.0 — 2026-09-30

### 文档标准化
- 新建 `docs/ENGINEERING_INDEX.md`：模块定位、目录地图、文件职责、配置参数索引、技术债务清单
- 新建 `docs/TECHNICAL_DESIGN.md`：B/A/C 三层架构、四种压缩算法、执行引擎、数据流、状态管理设计
- 新建 `docs/API_SPEC.md`：`Compressor` / `GraphExecutor` / `IncrementalCompressor` 接口签名 + 参数表 + 示例
- 新建 `docs/CHANGELOG.md`（本文件）

### 不变更
- 代码层面无修改，仅补建标准文档

---

## v0.2.0 — 2026-08-02

> 来源：[`README.md`](../README.md) 版本记录

- README 更新至 v0.2
- 补充双维度编排架构说明（S/C/F 链 + 交叉验证）
- 明确模块处于实验状态

---

## v0.1.0 — 2026-06-21

> 来源：[`skills/graph-compressor/SKILL.md`](../skills/graph-compressor/SKILL.md) 版本记录 与 [`contract.ts`](../contract.ts) `VERSION` 常量

### 初始版本
- 实现 B/A/C 三层图结构（Blueprint / Architecture / Chronicle）
- 实现基础压缩算法（C→A→B 回溯压缩，四维度价值评分）
- 实现语义感知压缩（TF-IDF + 关键词命中 + 信息熵）
- 实现分片压缩（长对话优化，按时间切片 + 锚点保留）
- 实现 `blueprint-registry` 意图路由
- 实现 `visualization.ts` 压缩前后三层图对比 + 时间线
- 提供 `createCompressor()` 工厂，支持 `basic` / `semantic` / `sharded` / `auto` 四种模式
- 提供 `getVisualizationData()` 可视化数据输出
- 建立 `contract.ts` 稳定接口契约（`VERSION = '0.1.0'`，`PROTOCOL_VERSION = '1'`）

### 执行引擎（Phase 1-3）
- `graph-state.ts`：运行时状态管理 + 快照
- `graph-checkpointer.ts`：检查点磁盘持久化 + 回滚
- `graph-hitl.ts`：人机协作（approve/reject/edit 决策）
- `graph-parallel.ts`：并行节点调度（parallelGroup + all/any 汇总）
- `graph-executor.ts`：统一执行引擎（组合 State + Checkpoint + HITL）

### 意图识别
- `intent-gateway.ts`：confirmed / clarifying 两态意图识别
- `contract.ts` 集成 `recognizeIntent()` / `clarifyIntent()` / `getNotebookView()` / `addNote()`

### 增量压缩
- `incremental-compressor.ts`：版本链压缩（append / rollback / getDiff / getContextForLLM）
