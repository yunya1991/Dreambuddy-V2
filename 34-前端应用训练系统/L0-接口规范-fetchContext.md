# L0 接口规范 — FoundationLayer fetchContext 数据访问抽象

> 版本: v0.2 | 日期: 2026-10-16 | 依据: SPEC v1.1 §5 FoundationLayer 契约
> 状态: 阶段二「包装收敛」已落地（2026-10-16，P1.1-P1.3）：`core/l0_foundation.py` 10 scope + 十意图 exec_* 全部收敛；阶段三（19 DAL 切换）待 DAL 成熟

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
