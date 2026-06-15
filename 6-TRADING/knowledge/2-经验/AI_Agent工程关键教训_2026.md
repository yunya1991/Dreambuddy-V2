# AI Agent工程6大关键教训 (2026)

> **来源**: AI Agent Engineering in 2026: Architectures, Patterns, and Real-World Systems
> **日期**: 2026-06-15 | **搜索关键词**: `multi-agent AI trading system architecture design patterns 2026`
> **评估分**: 相关性4 + 新颖性3 + 实践性3 = **10/15** (borderline, 仅提取关键教训)

---

## 教训1: 状态管理 — CRDT与最终一致性

**问题**: 多Agent系统中，共享状态的同步是最大挑战。

**方案**:
- 使用CRDT (Conflict-free Replicated Data Types) 处理并发写入
- 分布式账本实现最终一致性
- 需要同步启发式算法、冲突检测、回滚策略、版本控制

**对我们**: 
- A系列任务的 `execution_loop.json` 就是共享状态文件
- 当前无并发写入保护 → 如果有两个cron同时读写可能冲突
- **建议**: 为关键状态文件加文件锁 (fcntl.flock)

---

## 教训2: 容错模式 — 健康检查+心跳+动态重分配

**问题**: Agent崩溃或卡死时需要自动恢复。

**方案**:
- Checkpoint + 状态复制用于崩溃恢复
- 健康检查心跳 (heartbeat)
- 动态责任重分配 (dynamic reassignment)

**对我们**:
- Hermes cron 已有 `last_status: error` 检测
- 但缺少**健康检查心跳** — 一个任务可能运行但不产出 (`0字节静默失败`)
- **建议**: 在A系列cron中增加产出大小门禁 (< 100字节 → WARN)

---

## 教训3: 通信协议瓶颈

> "Naive message passing (unstructured sensor data) suffices for coordination. In reality, uncontrolled communication creates bottlenecks, inconsistent states, and brittle systems."

**问题**: Agent间非结构化通信导致瓶颈和不一致。

**方案**:
- 分层协议：上下文过滤、优先级排序、自适应压缩、角色路由
- Agent Communication Language (FIPA-ACL) 提供结构化但增加开销

**对我们**:
- A系列当前通过**文件系统**通信 (Markdown报告)
- 这实际上是一个好的中间方案：文件即消息，无需额外服务
- 但缺少**结构化字段** → 下游需解析全文才能提取关键决策
- **建议**: A系列输出增加YAML frontmatter 包含结构化决策摘要

---

## 教训4: 分层架构 — 感知/推理/执行

```
Perception (感知) → Reasoning (推理) → Actuation (执行)
```

**好处**: 清晰接口边界、故障隔离、团队并行开发

**对我们**:
- A1-A2(感知/调研) → A3-A4(推理/决策) → A5(执行)
- 这个分层已经暗含在我们的管道中，但未显式文档化
- **建议**: 将三屏系统也按此分层重新组织文档

---

## 教训5: 协调模式选择 — 集中式 vs 去中心化 vs 混合

| 模式 | 适用场景 | 风险 |
|:---|:---|:---|
| 集中式 | 需要全局优化/优先级执行 | SPOF + 扩展性限制 |
| 去中心化 | 自然扩展/容错 | 需要复杂Agent逻辑 |
| 混合 | 平衡延迟/鲁棒性 | 设计复杂 |

**对我们**: 当前A系列是**集中式顺序管道**（A1→A2→...）→ 适合确定性交易决策，但SPOF风险高（A2失败则全链断裂）。可考虑为A2/A3/A4添加**去中心化fallback**（若上游缺失，直接使用web_search数据）。

---

## 教训6: 记忆架构 — 持久化 vs 临时

| 类型 | 功能 | 存储 |
|:---|:---|:---|
| 持久化记忆 | 长期知识、学习策略、世界模型 | 分布式数据库、知识图谱、向量存储 |
| 临时记忆 | 瞬态工作数据、即时观察 | 内存、低延迟访问 |

**对我们**: 
- 持久化 = knowledge/ 目录 + memory 系统 ✅
- 临时 = A系列报告文件 (中间产物) ✅
- 但缺少**跨会话记忆传递** — 一个cron任务无法直接引用上一个cron的结果中的具体值
- **建议**: 增加 `6-TRADING/state/` 共享状态目录，存放本日/本周的关键决策参数

---

## 总结：优先级排序

| 优先级 | 改进项 | 预期收益 |
|:---:|:---|:---|
| P0 | 为关键状态文件加文件锁 | 防并发冲突 |
| P0 | A系列产物增加结构化字段 (YAML frontmatter) | 下游可解析 |
| P1 | 增加 `6-TRADING/state/` 共享状态目录 | 跨任务记忆传递 |
| P1 | A2/A3添加去中心化fallback | 防SPOF全链断裂 |
| P2 | 三屏系统按感知/推理/执行分层文档化 | 架构清晰度 |
