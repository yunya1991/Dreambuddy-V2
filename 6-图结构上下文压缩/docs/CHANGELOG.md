# 图结构上下文压缩 — 变更记录

## v1.0（2026-10-11）

### 新增
- 补建 docs/ 五件套文档（ENGINEERING_INDEX / TECHNICAL_DESIGN / API_SPEC / CHANGELOG）
- 根目录已有完整文档：README / SPEC / IMPLEMENTATION / TECHNICAL-DOC / THEORY-AND-PRACTICE

### 核心实现
- 压缩策略：增量 / 语义 / 分片
- 图状态管理与持久化
- 图执行器（串行 + 并行）
- HITL 人在回路交互
- 蓝图系统与意图网关
- 可视化支持

### 测试
- graph-state / graph-parallel / graph-integration
- graph-hitl / graph-hitl-integration
- graph-parallel-integration
