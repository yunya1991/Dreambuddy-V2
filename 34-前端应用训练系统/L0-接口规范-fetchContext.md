# L0 接口规范 — FoundationLayer fetchContext 数据访问抽象

> 版本: v0.3 | 日期: 2026-11-15 | 依据: SPEC v1.1 §5 FoundationLayer 契约 + SPEC-54 ADR-V20
> 状态: 阶段二「包装收敛」已落地（2026-10-16，P1.1-P1.3）：`core/l0_foundation.py` 10 scope + 十意图 exec_* 全部收敛；阶段三（19 DAL 切换）待 DAL 成熟
> v0.3 增量（2026-11-15）：补登 `datacenter.series` scope + 新增 §6「As-Of 回放（vintage）」

## 1. 目标

将 L1 执行器（data_query_executor.py 十个 exec_* 链路）的硬编码数据访问，收敛到统一的 L0 fetchContext 抽象——数据源路径、查询方式、降级策略集中管理，为 18 中心直查 → 19 DAL 切换提供无缝迁移点。

## 2. 接口定义

```python
class L0Foundation:
    """L0 数据访问抽象（FoundationLayer.fetchContext 的实现规范）"""

    def fetch_context(self, scope: str, params: dict | None = None) -> dict:
        """
        工作前调用: 按 scope 取数据/经验/工程结论。
        Args:
            scope: 数据作用域标识（见 §3 注册表）
            params: 查询参数（symbol/source/limit 等）
        Returns:
            { ok, data, source, timestamp, degraded, meta }
        """

    def settle(self, result: dict, context: dict | None = None) -> None:
        """工作后沉淀: 按类型分流（案例库/认知系统/skill/文档）——已落地实现复用。"""
```

## 3. scope 注册表（数据源统一登记）

| scope | 当前实现 | 数据源 | 迁移目标 |
|---|---|---|---|
| datacenter.record | sqlite3 直查 | 18 中心 data_center.db | 19 DAL（成熟后） |
| datacenter.series | sqlite3 直查 | 19 库 `mm_metrics`；传 `as_of` 时读 `mm_metric_vintages`（见 §6） | 19 DAL（成熟后） |
| evolution.contradiction | 日志解析 | 23 系统 evolution_pipeline.log | — |
| evolution.snapshot | json 解析 | 23 系统 evolution_snapshots.json | — |
| yijing.bcrm2 | json 解析 | 11 系统 bcrm2_hourly_summary.json | — |
| yijing.bdsm | json 解析 | 11 系统 bdsm_snapshot_*.json | — |
| yijing.strategic | 日志解析 | 11 系统 polling_trader 日志 | — |
| event.state | json 解析 | 11 系统 event_driven_state.json | — |
| riskcontrol.trailing | 日志解析 | 16 系统 trailing_runner 日志 | — |
| market.ticker | OKX API | OKX 公开行情 | — |
| cognitive.recall | get_cle().recall | 4-MEMORY 认知系统 | MCP 接口 |

## 4. 渐进式收敛策略

1. **阶段一（规范先行）**: 本规范归档，新增 L1 意图时按 scope 注册表登记数据源，不再新增硬编码路径；
2. **阶段二（包装收敛）**: 逐个将 exec_* 中的数据访问改为 fetch_context(scope) 调用（每次一个意图，回归验证）；
3. **阶段三（DAL 切换）**: 19 DAL 成熟后，datacenter.record scope 的实现从 sqlite 直查切换为 DAL 调用——上层 exec_* 无感知。

## 5. 边界

- 本规范不改变已验证的十意图执行链路行为，仅收敛数据访问方式；
- settle 分流已落地（案例库+认知沉淀），不在本规范范围；
- 每次收敛改动需回归验证对应意图的端到端回复。

## 6. As-Of 回放（vintage）

契约来源：SPEC-54 ADR-V20（修订数据不可覆盖）+ V-AC27（vintage 隔离）。

**调用方式**：`fetch_context("datacenter.series", {"sub_category": ..., "metric_name": ..., "days": ..., "as_of": <unix_ts>})`；不传 `as_of` 即实时口径，行为不变。

**返回标记**：As-Of 命中时 `meta.vintage = true` 且 `meta.as_of = "<ISO8601 UTC>"`；实时口径两者均为 `null`。

**存储**：追加式表 `mm_metric_vintages(source, sub_category, metric_name, period_ts, observed_at, metric_value)`，主键多一维 `observed_at`，同一统计期允许多版本共存；配套索引 `idx_vintages_replay(sub_category, metric_name, period_ts, observed_at)`。

**查询语义**：`period_ts ∈ [start, end) AND observed_at <= as_of`，同一 `period_ts` 取 `observed_at` 最大者（该 As-Of 时点已知的最新版本）。

**降级**：表不存在时抛 `sqlite3.OperationalError`，上层降级为 `vintage_unavailable`——**绝不回落 `mm_metrics`**，否则会读到修订后的值造成前视。

**回填**：`19-数据访问层/scripts/migrate_metric_vintage.py`（幂等，`observed_at := timestamp` 即「首次落库时刻」；云端写库须先 `.backup`）。

**已知边界（v0.3 时点）**：
1. 回填行的 `observed_at` 等于统计期时间戳，无法还原历史真实发布时刻——旧值已被 `mm_metrics` 的 `INSERT OR REPLACE` 覆盖，不可追溯；
2. 采集端尚未写入 `mm_metric_vintages`，表不随采集增长，As-Of 目前只能回放迁移快照（见 19 层 ENGINEERING_INDEX §7 待办）。
