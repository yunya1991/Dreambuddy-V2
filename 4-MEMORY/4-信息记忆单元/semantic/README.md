# 应用记忆索引 — 总览

> **版本**: v1.1
> **更新日期**: 2026-07-26
> **定位**: 所有应用记忆系统的注册表、路由表、健康状态
> **作用**: 总记忆系统通过这里索引和路由到各应用记忆

---

## 什么是应用记忆索引？

应用记忆索引是总记忆系统的"目录服务"，记录所有应用记忆系统的元信息。

总记忆系统不直接管理应用记忆的内容，而是通过这个索引：
- 知道有哪些应用记忆系统
- 知道每个系统在哪里、做什么
- 知道查询什么类型的内容该路由到哪里
- 知道每个系统的健康状态

---

## 应用记忆注册表

### 已注册的应用记忆系统

| ID | 名称 | 子系统 | 定位 | 存储位置 | 成熟度 | 统一接口 |
|----|------|--------|------|---------|--------|---------|
| AM-TRD-001 | 交易 L4 记忆 | 11-易经推理系统 | 交易策略案例库 + 知识图谱 + 蒸馏 | [11-易经推理系统/scripts/memory_l4/](../../11-易经推理系统/scripts/memory_l4/) | 高（标杆） | ✅ v1.0.0 |
| AM-EXP-001 | 实验记忆 | experiments/ab-trading | AB 实验记录 + 进化路径 | [experiments/ab-trading/core/memory/](../../experiments/ab-trading/core/memory/) | 中 | ❌ 待封装 |
| AM-ORC-001 | 编排记忆 | dreamos（1-ARCHITECTURE） | 编排执行记忆 + 对话记忆 | [1-ARCHITECTURE/dreamos/core/memory/](../../1-ARCHITECTURE/dreamos/core/memory/) | 中 | ❌ 待封装 |
| AM-RSK-001 | 风控记忆 | 13-通用风控模块 | 风控规则 + 告警案例 | 13-通用风控模块/memory/（待建） | 低（待建） | - |
| AM-OPS-001 | 运维记忆 | 15-监控告警系统 | 故障案例 + 性能基线 | 15-监控告警系统/memory/（待建） | 低（待建） | - |

---

### 各系统详细信息

#### AM-TRD-001：交易 L4 记忆（标杆）

| 属性 | 说明 |
|------|------|
| **所属子系统** | 11-易经推理系统 |
| **定位** | 交易策略的案例推理、知识图谱、经验蒸馏 |
| **存储位置** | 11-易经推理系统/scripts/memory_l4/ |
| **核心组件** | CBR 案例库、KG 知识图谱、蒸馏引擎、统计引擎 |
| **技术栈** | Python + SQLite + JSON |
| **成熟度** | 高 — 已经有完整的四层记忆架构 |
| **统一接口** | ✅ 已实现（v1.0.0）— [app_memory_interface.py](../../11-易经推理系统/scripts/memory_l4/app_memory_interface.py) |
| **接口规范版本** | v1.0（7 标准接口 + 2 便捷方法） |
| **最后更新** | 2026-07-26 |
| **健康状态** | ✅ 运行中（pipeline_connected: true, schema_compliance: 0.9365） |

**核心模块**：
- `pipeline.py` — 记忆流水线
- `cbr_engine.py` — CBR 案例推理引擎
- `kg_store.py` — 知识图谱存储
- `distill_engine.py` — 蒸馏引擎
- `stat_engine.py` — 统计引擎
- `app_memory_interface.py` — **统一接口封装（新增）**

**统一接口清单**：
| 接口 | 状态 | 说明 |
|------|------|------|
| `search(query, filters, memory_type, top_k)` | ✅ | 检索记忆（支持 case/review/distill 三类） |
| `add(memory_entry)` | ✅ | 添加记忆（自动生成 ID 和时间戳） |
| `update(memory_id, updates)` | ✅ | 更新记忆 |
| `get(memory_id)` | ✅ | 获取单条记忆 |
| `stats()` | ✅ | 统计信息（数量、类型分布、健康指标） |
| `distill_candidates(min_quality, limit)` | ✅ | 蒸馏候选（可上升为总记忆的经验） |
| `healthcheck()` | ✅ | 健康检查（状态、最后更新、管道指标） |
| `search_similar_cases()` | ✅ | 便捷方法：CBR 语义相似度检索 |
| `run_distill_from_review()` | ✅ | 便捷方法：从复盘记录运行完整蒸馏 |

**search filters 字段声明**（接口语义隔离 — 以下为交易记忆的业务字段）：
| 字段 | 类型 | 说明 | 适用记忆类型 |
|------|------|------|------------|
| `inst_id` | str | 交易对（如 BTC-USDT-SWAP） | case, review |
| `regime` | str | 市场状态（如 trending_up, ranging） | case |
| `decision` | str | 交易方向（LONG, SHORT, CLOSE） | case, review |
| `is_profit` | bool | 是否盈利 | case |
| `system_source` | str | 系统来源（如 bcrm2, qmm, dream_os） | case |
| `direction` | str | 方向（LONG, SHORT） | review |

**当前数据规模**（2026-07-27 快照，实际数据动态变化）：
- 案例 (case): ~457 条
- 复盘 (review): ~4,485 条
- 蒸馏 (distill): ~76 条
- 统计快照 (stats): ~21 份
- 总计: ~5,018 条记忆

---

#### AM-EXP-001：实验记忆

| 属性 | 说明 |
|------|------|
| **所属子系统** | experiments/ab-trading |
| **定位** | AB 实验记录、进化路径、参数优化轨迹 |
| **存储位置** | experiments/ab-trading/core/memory/ |
| **核心组件** | memory_manager.py |
| **技术栈** | Python |
| **成熟度** | 中 — 有基础实现 |
| **统一接口** | 待封装 |
| **最后更新** | - |
| **健康状态** | ⚠️ 基础可用 |

---

#### AM-ORC-001：编排记忆

| 属性 | 说明 |
|------|------|
| **所属子系统** | dreamos（1-ARCHITECTURE） |
| **定位** | 编排执行记忆、对话记忆、工具调用记忆 |
| **存储位置** | 1-ARCHITECTURE/dreamos/core/memory/ |
| **核心组件** | memory.py |
| **技术栈** | Python |
| **成熟度** | 中 — 有基础实现 |
| **统一接口** | 待封装 |
| **最后更新** | - |
| **健康状态** | ⚠️ 基础可用 |

---

## 路由表

> 什么类型的查询应该路由到哪个应用记忆系统？

| 查询类型 | 主路由 | 次路由 | 说明 |
|---------|--------|--------|------|
| 交易策略案例 | AM-TRD-001 | AM-EXP-001 | 具体交易案例和策略经验 |
| 市场分析 | AM-TRD-001 | - | 市场状态和分析方法 |
| 风控规则 | AM-RSK-001（待建） | - | 风控策略和案例 |
| 故障排查 | AM-OPS-001（待建） | AM-TRD-001 | 系统故障和运维经验 |
| 实验数据 | AM-EXP-001 | - | AB 实验和进化数据 |
| 编排执行 | AM-ORC-001 | - | 工作流和工具调用 |
| 通用方法论 | 总记忆 | - | 方法论和原则在总记忆中 |

---

## 健康状态

### 心跳与新鲜度

| 系统 | 最后心跳 | 数据新鲜度 | 状态 |
|------|---------|-----------|------|
| AM-TRD-001 | 2026-07-26T09:43:05+08:00 | 5,018 条记忆 / 合规率 93.65% | ✅ 健康 |
| AM-EXP-001 | - | - | ⚠️ 待接入心跳机制 |
| AM-ORC-001 | - | - | ⚠️ 待接入心跳机制 |
| AM-RSK-001 | - | - | ❌ 待建设 |
| AM-OPS-001 | - | - | ❌ 待建设 |

### 健康检查机制（规划中）

- 各应用记忆定期上报心跳（默认每小时一次）
- 心跳包含：版本、统计数据、最后更新时间
- 超过 24 小时无心跳 → 标记为"失联"
- 超过 7 天无心跳 → 标记为"不可用"

---

## 统一接口规范

所有应用记忆系统最终需要实现以下标准接口：

| 接口 | 功能 | 输入 | 输出 | 标杆实现 |
|------|------|------|------|---------|
| `search(query, filters, memory_type, top_k)` | 检索记忆 | 查询词 + 过滤条件 + 记忆类型 + 返回数量 | 记忆条目列表 | ✅ AM-TRD-001 |
| `add(memory_entry)` | 添加记忆 | 记忆条目（符合类型规范） | 记忆 ID | ✅ AM-TRD-001 |
| `update(id, updates)` | 更新记忆 | 记忆 ID + 更新字段 | 成功/失败 | ✅ AM-TRD-001 |
| `get(id)` | 获取单条 | 记忆 ID | 完整记忆条目 | ✅ AM-TRD-001 |
| `stats()` | 统计信息 | - | 记忆数量、类型分布、更新频率 | ✅ AM-TRD-001 |
| `distill_candidates()` | 蒸馏候选 | - | 可上升为总记忆的候选列表 | ✅ AM-TRD-001 |
| `healthcheck()` | 健康检查 | - | 状态 + 最后更新时间 | ✅ AM-TRD-001 |

**标杆实现参考**：[AM-TRD-001 app_memory_interface.py](../../11-易经推理系统/scripts/memory_l4/app_memory_interface.py)

**设计模式**：适配器模式（Adapter Pattern）— 不修改现有代码，在其上封装统一接口。

**记忆 ID 规范**：`AM-{SYSTEM_CODE}-{TYPE}-{RAW_ID}`
- 示例：`AM-TRD-001-CASE-TC_BATCH_001`

**接口语义隔离原则**：`filters` 的字段语义由各应用记忆系统自行定义，总记忆系统不规定具体字段名。AM-TRD-001 中的 `inst_id`、`regime` 等是交易记忆的业务字段，不是规范要求。详见 [MEMORY_SYSTEM_ARCHITECTURE.md §4.2](../MEMORY_SYSTEM_ARCHITECTURE.md)。

详细接口规范见：[9-工具与接口/](../9-工具与接口/)（待建设）

---

## 注册新的应用记忆

要注册新的应用记忆系统：

1. 在 [APP_MEMORY_REGISTRY.md](./APP_MEMORY_REGISTRY.md) 中添加条目
2. 提供：名称、定位、存储位置、技术栈、成熟度
3. 实现统一接口（或制定接入计划）
4. 设置心跳上报机制
5. 在路由表中添加路由规则

---

**文档版本**: v1.1
**最后更新**: 2026-07-26
