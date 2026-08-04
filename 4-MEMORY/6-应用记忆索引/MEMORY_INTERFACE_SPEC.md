# 记忆系统接口契约统一 SPEC

> **版本**: v1.0 | **更新日期**: 2026-07-31
> **定位**: 应用记忆系统（AppMemory）的跨子系统统一接口契约，关闭 DD-017
> **权威**: 本文件是 7 标准接口 + 2 便捷方法的唯一事实源（SSoT），所有应用记忆实现必须对齐
> **关联**: [APP_MEMORY_REGISTRY.md](./APP_MEMORY_REGISTRY.md) · [MEMORY_QUALITY.md](../0-元记忆/MEMORY_QUALITY.md) · [ROUTING_TABLE.md](./ROUTING_TABLE.md)

---

## 1. 目的与范围

### 1.1 解决问题

项目存在两套并行的记忆接口实现，命名、签名、返回类型存在多处不一致：

| 差异点 | L4 子系统实现 | 认知系统 VectorMemoryInterface |
|--------|--------------|------------------------------|
| `search` 过滤参数 | `filters: Dict`（领域语义隔离） | `quality_filter/tags_filter/memory_type_filter` 分散参数 |
| `add` 入参 | `memory_entry: Dict` | 多个展开参数 |
| `update` 方法名 | `update` | `update_quality`（仅更新质量） |
| `distill_candidates` | 已实现 | **缺失** |
| `search_similar_cases` | 已实现 | 名为 `search_similar` |
| `run_distill_from_review` | 已实现 | **缺失** |
| `distill_candidates.min_quality` 类型 | TRD 用 `float`，RSK/OPS 用 `str` | — |
| `run_distill_from_review` 返回值 | TRD 返回 `Dict`，RSK 返回 `str` | — |
| 接口形式 | TRD 函数式，RSK/OPS 类式 | 类式 |

### 1.2 适用范围

本 SPEC 适用于所有注册在 [APP_MEMORY_REGISTRY.md](./APP_MEMORY_REGISTRY.md) 的应用记忆实现：

| AM-ID | 子系统 | 实现文件 |
|-------|--------|----------|
| AM-TRD-001 | 11-易经推理系统 | `11-易经推理系统/scripts/memory_l4/app_memory_interface.py` |
| AM-RSK-001 | 13-通用风控模块 | `13-通用风控模块/memory/app_memory_interface.py` |
| AM-OPS-001 | 15-监控告警系统 | `15-监控告警系统/memory/app_memory_interface.py` |
| AM-EXP-001 | experiments | `experiments/ab-trading/memory/app_memory_interface.py` |

> 注：认知系统的 `VectorMemoryInterface`（`4-MEMORY/9-工具与接口/vector_memory_interface.py`）是 L1 向量记忆存储，**不属于应用记忆接口范畴**，但其 `search/add/get/stats/healthcheck` 应与本 SPEC 对齐以便复用。

---

## 2. 接口形式

### 2.1 统一为类式

所有应用记忆实现必须以类形式提供，继承基类 `AppMemoryInterface`：

```python
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

class AppMemoryInterface(ABC):
    """应用记忆统一接口基类。所有应用记忆实现必须继承此类。"""

    @abstractmethod
    def search(self, query: str = "", filters: Optional[Dict[str, Any]] = None,
               memory_type: str = "all", top_k: int = 10) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def add(self, memory_entry: Dict[str, Any]) -> str:
        ...

    @abstractmethod
    def update(self, memory_id: str, updates: Dict[str, Any]) -> bool:
        ...

    @abstractmethod
    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def stats(self) -> Dict[str, Any]:
        ...

    @abstractmethod
    def distill_candidates(self, min_quality: str = "C", limit: int = 10) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def healthcheck(self) -> Dict[str, Any]:
        ...

    def search_similar_cases(self, **kwargs) -> List[Dict[str, Any]]:
        """便捷方法：按领域语义检索相似案例。参数由各应用记忆自行定义。"""
        raise NotImplementedError("该应用记忆未实现 search_similar_cases")

    def run_distill_from_review(self, **kwargs) -> Dict[str, Any]:
        """便捷方法：从复盘记录蒸馏经验。参数由各应用记忆自行定义。"""
        raise NotImplementedError("该应用记忆未实现 run_distill_from_review")
```

### 2.2 filters 语义隔离原则

`filters` 统一为 `Dict[str, Any]`，但**具体字段由各应用记忆自行定义**，以保留领域语义隔离：

| 应用记忆 | filters 字段示例 |
|---------|-----------------|
| AM-TRD-001 | `{"inst_id": "SUI", "regime": "trend", "decision": "long"}` |
| AM-RSK-001 | `{"trigger_type": "drawdown", "severity": "high"}` |
| AM-OPS-001 | `{"alert_level": "critical", "system": "yijing"}` |

跨应用记忆的聚合查询由 [ROUTING_TABLE.md](./ROUTING_TABLE.md) 路由层处理，不在单接口内耦合。

---

## 3. 七个标准接口契约

### 3.1 search — 语义搜索

```python
def search(self, query: str = "", filters: Optional[Dict[str, Any]] = None,
           memory_type: str = "all", top_k: int = 10) -> List[Dict[str, Any]]
```

| 参数 | 类型 | 默认 | 语义 |
|------|------|------|------|
| `query` | `str` | `""` | 自然语言查询；空串表示仅按 filters 过滤 |
| `filters` | `Optional[Dict]` | `None` | 领域语义过滤字段，由各 AM 自定义 |
| `memory_type` | `str` | `"all"` | 记忆类型过滤：`"all"` / `"experience"` / `"lesson"` / `"principle"` 等 |
| `top_k` | `int` | `10` | 返回条数上限 |

**返回**: `List[Dict]`，每条记忆字典包含字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `memory_id` | `str` | 全局唯一 ID |
| `content` | `str` | 记忆内容 |
| `quality_level` | `str` | 质量等级 `"S"/"A"/"B"/"C"/"D"` |
| `confidence` | `float` | 置信度 `[0.0, 1.0]` |
| `verify_count` | `int` | 验证次数 |
| `tags` | `List[str]` | 标签 |
| `memory_type` | `str` | 记忆类型 |
| `source` | `str` | 来源标识 |
| `score` | `float` | 检索相关度分数（仅 search 返回） |
| `created_at` | `str` | 创建时间 ISO8601 |
| `updated_at` | `str` | 更新时间 ISO8601 |

**约定**：结果按 `score` 降序排列。`query` 为空时按 `updated_at` 降序。

### 3.2 add — 添加记忆

```python
def add(self, memory_entry: Dict[str, Any]) -> str
```

| 参数 | 类型 | 语义 |
|------|------|------|
| `memory_entry` | `Dict[str, Any]` | 记忆条目，必填字段见下 |

`memory_entry` 必填 / 可选字段：

| 字段 | 必填 | 类型 | 默认 | 说明 |
|------|------|------|------|------|
| `content` | ✅ | `str` | — | 记忆内容 |
| `quality_level` | ❌ | `str` | `"C"` | 初始质量等级 |
| `confidence` | ❌ | `float` | `0.0` | 初始置信度 |
| `tags` | ❌ | `List[str]` | `[]` | 标签 |
| `memory_type` | ❌ | `str` | `"experience"` | 记忆类型 |
| `source` | ❌ | `str` | `""` | 来源标识 |
| `memory_id` | ❌ | `str` | 自动生成 | 指定 ID（用于去重/幂等） |
| 领域字段 | ❌ | `Any` | — | 各 AM 自定义的领域字段（如 `inst_id`、`trigger_type`） |

**返回**: `str` — 写入或已存在记忆的 `memory_id`。

**幂等约定**：传入 `memory_id` 且已存在时，更新而非报错；不传时自动生成 `AM-XXX-{timestamp}-{hash}`。

### 3.3 update — 更新记忆

```python
def update(self, memory_id: str, updates: Dict[str, Any]) -> bool
```

| 参数 | 类型 | 语义 |
|------|------|------|
| `memory_id` | `str` | 目标记忆 ID |
| `updates` | `Dict[str, Any]` | 待更新字段，可含 `content/quality_level/confidence/tags/memory_type` 及领域字段 |

**返回**: `bool` — 更新成功返回 `True`，记忆不存在返回 `False`。

**关键约定**：
- 当 `updates` 包含 `quality_level` 或 `confidence` 时，必须触发质量变更通知（用于蒸馏引擎订阅）。
- 质量变更应遵循 [MEMORY_QUALITY.md](../0-元记忆/MEMORY_QUALITY.md) 的升降级规则，不得越级跳升（如 C→A 需先经 B）。

> **对齐说明**：认知系统 `VectorMemoryInterface.update_quality` 仅更新质量字段，应重命名为 `update` 并支持通用字段更新。

### 3.4 get — 获取单条记忆

```python
def get(self, memory_id: str) -> Optional[Dict[str, Any]]
```

**返回**: `Optional[Dict]` — 记忆字典（字段同 §3.1 返回），不存在返回 `None`。

### 3.5 stats — 统计信息

```python
def stats(self) -> Dict[str, Any]
```

**返回**:

```python
{
    "total": int,                    # 总记忆数
    "by_quality": {                  # 各等级数量
        "S": int, "A": int, "B": int, "C": int, "D": int
    },
    "by_type": Dict[str, int],       # 各 memory_type 数量
    "avg_confidence": float,         # 平均置信度
    "verified_count": int,           # 已验证（verify_count>0）记忆数
    "distill_pending": int,          # 待蒸馏候选数
    "last_updated": str,             # 最近更新时间 ISO8601
    "db_size_bytes": int             # 存储大小（可选）
}
```

### 3.6 distill_candidates — 蒸馏候选

```python
def distill_candidates(self, min_quality: str = "C", limit: int = 10) -> List[Dict[str, Any]]
```

| 参数 | 类型 | 默认 | 语义 |
|------|------|------|------|
| `min_quality` | `str` | `"C"` | 最低质量等级（等级字母，**非 float**） |
| `limit` | `int` | `10` | 返回条数上限 |

> **对齐说明**：AM-TRD-001 当前用 `min_quality: float`（质量分数），必须改为 `str`（等级字母），与质量分级体系一致。等级比较顺序：`S > A > B > C > D`。

**返回**: `List[Dict]` — 候选记忆列表，每条含 `memory_id/content/quality_level/confidence/distill_score`，按 `distill_score` 降序。

### 3.7 healthcheck — 健康检查

```python
def healthcheck(self) -> Dict[str, Any]
```

**返回**:

```python
{
    "status": "healthy" | "degraded" | "offline",
    "am_id": str,                    # 应用记忆 ID
    "last_check": str,               # 检查时间 ISO8601
    "total_memories": int,
    "db_reachable": bool,
    "issues": List[str],             # 发现的问题列表
    "capacity_pct": float            # 容量使用百分比（可选）
}
```

**被动心跳约定**：`healthcheck()` 是被动查询式接口。应用记忆应保证调用时能在 1 秒内返回。总记忆索引层（`HEALTH_STATUS.md`）定期轮询各 AM 的 `healthcheck()` 维护全局健康视图。

---

## 4. 两个便捷方法契约

便捷方法提供领域语义化的高频操作，参数由各应用记忆自定义（`**kwargs`），但返回类型必须统一。

### 4.1 search_similar_cases — 相似案例检索

```python
def search_similar_cases(self, **kwargs) -> List[Dict[str, Any]]
```

**各 AM 参数定义**：

| AM-ID | 参数 |
|-------|------|
| AM-TRD-001 | `inst_id=None, regime=None, decision=None, top_k=5` |
| AM-RSK-001 | `trigger_type: str, severity=None, top_k=5` |
| AM-OPS-001 | `alert_type: str, system=None, top_k=5` |

**返回**: `List[Dict]` — 相似案例列表（字段同 §3.1 返回，含 `score`），按相似度降序。

> **对齐说明**：认知系统 `VectorMemoryInterface.search_similar` 应对齐命名为 `search_similar_cases`。

### 4.2 run_distill_from_review — 从复盘蒸馏

```python
def run_distill_from_review(self, **kwargs) -> Dict[str, Any]
```

**各 AM 参数定义**：

| AM-ID | 参数 |
|-------|------|
| AM-TRD-001 | `review_record: Dict[str, Any]`（复盘记录） |
| AM-RSK-001 | `case_id: str, review_content: str` |
| AM-OPS-001 | `incident_id: str, review_content: str` |

**返回**: `Dict[str, Any]` — 统一返回字典：

```python
{
    "distill_id": str,               # 蒸馏产物 ID
    "source_count": int,             # 源记忆数量
    "produced": bool,                # 是否产出新记忆
    "new_memory_id": Optional[str],  # 产出的新记忆 ID（未产出为 None）
    "quality_level": str,            # 产出记忆等级
    "confidence": float              # 产出记忆置信度
}
```

> **对齐说明**：AM-RSK-001 当前返回 `str`（蒸馏 ID），必须改为 `Dict[str, Any]`。

---

## 5. 质量分级与接口耦合

### 5.1 五级质量体系

依据 [MEMORY_QUALITY.md](../0-元记忆/MEMORY_QUALITY.md)：

| 等级 | 名称 | 置信度阈值 | 验证次数阈值 | 半衰期 | 进入标准 |
|------|------|-----------|------------|--------|---------|
| S | 公理级 Axiom | ≥ 0.95 | ≥ 10 | 365 天 | 跨场景跨时间有效，无反例 |
| A | 可信级 Trusted | ≥ 0.70 | ≥ 3 | 180 天 | 多场景有效 |
| B | 待验证 Unverified | ≥ 0.40 | ≥ 1 | 90 天 | 有逻辑支撑 |
| C | 假设级 Hypothesis | ≥ 0.00 | ≥ 0 | 30 天 | 推测未验证 |
| D | 已证伪 Disproved | — | — | 15 天 | 发现明确反例 |

### 5.2 接口与质量的耦合点

| 接口 | 耦合行为 |
|------|---------|
| `add` | 新记忆默认 `quality_level="C", confidence=0.0`，除非显式指定 |
| `update` | 更新 `quality_level`/`confidence` 时触发质量变更通知（蒸馏引擎订阅） |
| `search` | 可通过 `filters={"min_quality": "B"}` 过滤质量等级 |
| `distill_candidates` | `min_quality` 参数控制候选最低等级 |
| `run_distill_from_review` | 产出记忆等级由蒸馏逻辑根据源记忆质量推导 |

### 5.3 质量变更禁止越级跳升

升降级路径必须遵循：`C → B → A → S`（逐级验证），`D` 为终态（已证伪不可恢复）。`update` 接口在检测到越级跳升时应拒绝并返回 `False`。

---

## 6. 被动更新机制

应用记忆系统采用**被动更新机制**，保持各应用记忆的独立性和自治性。四种机制如下：

### 6.1 心跳上报（Heartbeat）

- **机制**：总记忆索引层定期轮询各 AM 的 `healthcheck()`，维护 `HEALTH_STATUS.md` 全局健康视图。
- **频率**：建议每 5 分钟轮询一次。
- **降级策略**：连续 3 次无响应标记为 `offline`，查询路由跳过该 AM。

### 6.2 蒸馏候选上报（Distill Candidate Reporting）

- **机制**：当应用记忆中某条记忆质量升级到 B 级以上时，通过 `distill_candidates()` 暴露给蒸馏调度器（`DistillScheduler`）拉取。
- **路径 A（事件驱动）**：`update()` 质量变更 → `DynamicDistillEngine.on_confidence_changed()` → 路由到对应总记忆单元（MU-xxx）。
- **路径 B（定时调度）**：`DistillScheduler.run_daemon()` 每小时调用各 AM 的 `distill_candidates()` → 蒸馏到总记忆。
- **路由映射**（`dynamic_distill_engine.py` 与 `distill_scheduler.py` 中 `MEMORY_ROUTING`）：

| 应用记忆 | 蒸馏目标 |
|---------|---------|
| AM-TRD-001 | MU-TRD（交易记忆单元） |
| AM-RSK-001 | MU-TRD |
| AM-OPS-001 | MU-DEV（开发记忆单元） |
| AM-EXP-001 | MU-TRD |

> **风险提示**：`dynamic_distill_engine.py` 与 `distill_scheduler.py` 各有一份 `MEMORY_ROUTING` 配置，存在不一致风险，应抽取为单一配置源。

### 6.3 索引同步（Index Synchronization）

- **机制**：`ROUTING_TABLE.md` 维护关键词→AM 映射、子系统→AM 映射。
- **更新触发**：新 AM 注册时更新 `APP_MEMORY_REGISTRY.md` 和 `ROUTING_TABLE.md`。
- **默认路由**：无法识别时先查 MU-TRD，无结果再广播所有在线 AM。

### 6.4 按需拉取（On-demand Pull）

- **机制**：AI 或总记忆层按需调用 AM 的 `search()` / `get()` 检索，不在本地缓存。
- **复合查询**：跨 AM 聚合由路由层处理，结果合并去重。

---

## 7. 实现合规检查清单

新增或修改应用记忆实现时，必须通过以下检查：

| # | 检查项 | 通过标准 |
|---|--------|---------|
| 1 | 接口形式 | 继承 `AppMemoryInterface` 基类（类式，非函数式） |
| 2 | search 签名 | `(query, filters, memory_type, top_k)` 四参数 |
| 3 | add 签名 | `(memory_entry: Dict) -> str` 单 dict 入参 |
| 4 | update 签名 | `(memory_id, updates) -> bool`，支持通用字段更新 |
| 5 | update 命名 | 方法名为 `update`（非 `update_quality`） |
| 6 | distill_candidates | `min_quality: str`（等级字母，非 float） |
| 7 | search_similar_cases | 命名为 `search_similar_cases`（非 `search_similar`） |
| 8 | run_distill_from_review | 返回 `Dict[str, Any]`（非 `str`） |
| 9 | 返回字段 | search/get 返回字典含 §3.1 全部标准字段 |
| 10 | 质量变更通知 | update 质量字段时触发蒸馏引擎订阅 |
| 11 | healthcheck | 1 秒内返回，含 status/last_check/total_memories |
| 12 | 幂等性 | add 传入已存在 memory_id 时更新而非报错 |
| 13 | 越级保护 | update 拒绝 C→A 等越级跳升 |
| 14 | 注册 | 在 APP_MEMORY_REGISTRY.md 和 ROUTING_TABLE.md 登记 |

---

## 8. 现有实现对齐状态

| 实现项 | AM-TRD-001 | AM-RSK-001 | AM-OPS-001 | AM-EXP-001 | VectorMemoryInterface |
|--------|-----------|-----------|-----------|-----------|----------------------|
| 类式 | ❌ 函数式 | ✅ | ✅ | ✅ | ✅ |
| search filters | ✅ Dict | ✅ Dict | ✅ Dict | ✅ Dict | ❌ 分散参数 |
| add dict 入参 | ✅ | ✅ | ✅ | ✅ | ❌ 展开参数 |
| update 命名 | ✅ | ✅ | ✅ | ✅ | ❌ update_quality |
| update 通用字段 | ✅ | ✅ | ✅ | ✅ | ❌ 仅质量 |
| distill_candidates | ✅ float⚠️ | ✅ str | ✅ str | ✅ | ❌ 缺失 |
| search_similar_cases | ✅ | ✅ | ✅ | ✅ | ❌ search_similar |
| run_distill_from_review | ✅ Dict⚠️ | ❌ str | ✅ | ✅ | ❌ 缺失 |
| healthcheck | ✅ | ✅ | ✅ | ✅ | ✅ |

**待对齐项**（标记 ⚠️ / ❌）需在后续迭代中修复，优先级：AM-TRD-001 参数类型 > VectorMemoryInterface 缺失接口 > 其余命名对齐。

---

## 9. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-31 | v1.0 | 初始版本，关闭 DD-017；统一 7+2 接口契约、质量分级耦合、被动更新机制、合规检查清单 |

---

**文档版本**: v1.0
**最后更新**: 2026-07-31
**关联债务**: DD-017（已关闭）· [APP_MEMORY_REGISTRY.md](./APP_MEMORY_REGISTRY.md) · [MEMORY_QUALITY.md](../0-元记忆/MEMORY_QUALITY.md)
