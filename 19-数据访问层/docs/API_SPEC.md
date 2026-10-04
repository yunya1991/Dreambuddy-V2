# 19-数据访问层 — 接口规格文档

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 子系统对外接口规格（6 大 Repository Protocol 契约），对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.3

---

## 1. 接口概览

### 1.1 接口类型

| 类型 | 数量 | 说明 |
|------|------|------|
| Python Protocol | 6 | 6 大 Repository 契约（ABC 抽象基类） |
| Python 实现 | 2 | `sqlite_unified`（P1 主实现）+ `json_legacy`（P0 兼容） |
| DI 容器 | 1 | `dreambuddy_dal.di` 自动注入 |

### 1.2 接口列表

| Protocol | 域 | 核心方法数 | 说明 |
|----------|-----|-----------|------|
| `ConfigRepository` | 配置 | 4 | 全局配置版本管理（单版本激活 + 时间线） |
| `TradeRepository` | 交易 | 5 | 交易账本（add/close/query + 日统计） |
| `PositionRepository` | 持仓 | 4 | 净持仓快照（upsert/get/list/refresh） |
| `RiskRepository` | 风控 | 4 | 风控状态（乐观锁）+ 案例记录 |
| `MarketMacroRepository` | 宏观市场 | 14 | 6 张宏观表（恐惧贪婪/资金费率/持仓量/爆仓/多空比/Taker量）+ 通用指标 |
| `KnowledgeGraphRepository` | 知识图谱 | 5 | 实体/别名/三元组 + FTS5 全文搜索 + 子图查询 |

---

## 2. 认证方式

| 方式 | 说明 |
|------|------|
| 无需认证 | SDK 集成，通过 DI 容器获取实现 |
| SQLite | 本地文件，无网络认证 |

---

## 3. 接口详情

### 3.1 ConfigRepository（配置域）

**模块**：`dreambuddy_dal.protocols.config_repo`

| 方法 | 签名 | 说明 |
|------|------|------|
| `get_active_version` | `get_active_version(config_name: str = "global") -> Optional[Dict]` | 取当前激活版本配置值字典；无激活返回 None |
| `activate_version` | `activate_version(config_name, version, *, activated_by="system", activated_at=None) -> bool` | 切某版本为激活（自动取消旧激活）；version 不存在返回 False |
| `get_specific_version` | `get_specific_version(config_name, version) -> Optional[Dict]` | 查指定历史版本（复盘/回滚比对） |
| `create_version` | `create_version(config_name, config_data, *, created_by="system", description=None) -> int` | 创建新配置版本（不自动激活）；返回新版本号 |

**设计原则**：所有配置变更必须先 create_version 再 activate；activate 由 DB 触发器保证全局同一时刻只有 1 条 is_active=1。

### 3.2 TradeRepository（交易域）

**模块**：`dreambuddy_dal.protocols.trade_repo`

| 方法 | 签名 | 说明 |
|------|------|------|
| `add_trade` | `add_trade(trade: TradeRecord) -> Optional[str]` | 新增交易；返回 trade_id（成功）/ None（DualWrite 失败不阻塞） |
| `close_position` | `close_position(trade_id, exit_reason, exit_price, close_ts, realized_pnl, *, slippage_bps=0, execution_id=None) -> Optional[CloseInfo]` | 标记 CLOSED + 写入 CloseInfo |
| `add_or_update_daily_stats` | `add_or_update_daily_stats(stats: DailyStats) -> bool` | 日统计幂等 upsert（主键 stat_date+symbol+sub_sys+strategy） |
| `get_trade` | `get_trade(trade_id: str) -> Optional[TradeRecord]` | 按 trade_id 查 |
| `query_trades` | `query_trades(symbol=None, *, start_ts=None, end_ts=None, strategy=None, status=None, limit=1000) -> List[TradeRecord]` | 交易查询（参数默认=不限制） |
| `get_daily_stats` | `get_daily_stats(symbol, stat_date, *, sub_system=None, strategy_name=None) -> Optional[DailyStats]` | 按日主键查每日统计快照 |

### 3.3 PositionRepository（持仓域）

**模块**：`dreambuddy_dal.protocols.position_repo`

| 方法 | 签名 | 说明 |
|------|------|------|
| `upsert_position` | `upsert_position(position: PositionState) -> bool` | 主键 position_id(symbol:dir:sub_sys) 幂等写入 |
| `get_position` | `get_position(symbol, sub_system=None, direction=None) -> Optional[PositionState]` | 精确查持仓；多子系统歧义抛 ValueError |
| `list_positions` | `list_positions(sub_system=None, *, symbol=None) -> List[PositionState]` | 持仓列表（按子系统/币种过滤） |
| `refresh_mark_price` | `refresh_mark_price(position_id, mark_price, unrealized_pnl, refresh_ts, *, liquidation_price=None) -> bool` | 轻量刷新 mark_price/unrealized_pnl |

### 3.4 RiskRepository（风控域）

**模块**：`dreambuddy_dal.protocols.risk_repo`

| 方法 | 签名 | 说明 |
|------|------|------|
| `get_state` | `get_state(id: int = 1) -> Optional[RiskState]` | 取系统风控状态（永远 id=1）；None=未初始化 |
| `update_state` | `update_state(new_state: RiskState, *, expected_version=None) -> bool` | 乐观锁更新；version 不匹配返回 False（并发冲突重试） |
| `add_case` | `add_case(case: RiskCaseRecord) -> bool` | 记录风控拦截/放行案例 |
| `query_cases` | `query_cases(*, start_ts=None, end_ts=None, min_severity=None, risk_level=None, symbol=None, limit=500) -> List[RiskCaseRecord]` | 风控案例查询 |

**核心约束**：get_state/update_state 强制单行 id=1，DB 层 CHECK(id=1) + 乐观锁 version。

### 3.5 MarketMacroRepository（宏观市场域）

**模块**：`dreambuddy_dal.protocols.market_macro_repo`

每张表 2 方法（upsert + query_by_time），共 6 张表 + 通用指标：

| 表 | upsert 方法 | query 方法 |
|----|------------|-----------|
| 恐惧贪婪 | `upsert_fear_greed(value, classification, ts)` | `query_fear_greed_by_time(start, end)` |
| 资金费率 | `upsert_funding_rate(symbol, rate, ts)` | `query_funding_by_time(symbol, start, end)` |
| 持仓量 | `upsert_open_interest(symbol, oi, oi_value, ts)` | `query_open_interest_by_time(symbol, start, end)` |
| 爆仓数据 | `upsert_liquidation(symbol, qty, side, price, total_qty, ts)` | `query_liquidation_by_time(symbol, start, end)` |
| 多空比 | `upsert_long_short_ratio(symbol, long, short, ratio, ts)` | `query_long_short_ratio_by_time(symbol, start, end)` |
| Taker 主动买卖量 | `upsert_taker_volume(symbol, buy, sell, diff, ratio, ts)` | `query_taker_volume_by_time(symbol, start, end)` |
| 通用指标 | `upsert_metric(source, sub_category, metric_name, value, ts)` | `query_metric_by_time(sub_category, metric_name, start, end)` + `query_latest_metric(sub_category, metric_name)` |

**读写分工**：写=18-数据获取中心；读=易经推理/V15/经典指标。

### 3.6 KnowledgeGraphRepository（知识图谱域）

**模块**：`dreambuddy_dal.protocols.kg_repo`

| 方法 | 签名 | 说明 |
|------|------|------|
| `upsert_entity` | `upsert_entity(entity_id, entity_type, canonical_name, *, description=None, attributes_json=None) -> bool` | 实体 upsert（主键 entity_id） |
| `add_alias` | `add_alias(entity_id, alias, *, confidence=1.0) -> bool` | 给实体加别名（FTS5 索引时合并） |
| `add_triple` | `add_triple(subject_id, predicate, object_id, *, confidence=1.0, source=None, valid_from=None) -> bool` | 增加三元组 subject -[predicate]-> object |
| `fts_search_entities` | `fts_search_entities(query, *, limit=20) -> List[Tuple[str,str,str,float]]` | FTS5 全文搜索实体（名称/别名/描述），返回 (id,type,name,bm25_rank) |
| `query_subgraph_by_entity` | `query_subgraph_by_entity(entity_id, *, hops=2, direction="both", min_confidence=0.5) -> Tuple[List, List]` | 取实体 N 跳邻居子图（易经推理知识线扩展） |

**底层表**：`kg_entities` / `kg_entity_aliases` / `kg_triples` / `kg_entities_fts`（FTS5 虚拟表）。

### 3.7 DI 容器

**模块**：`dreambuddy_dal.di`

通过 DI 容器获取实现，无需手动构造：
```python
from dreambuddy_dal.di import get_container

container = get_container()
trade_repo = container.resolve(TradeRepository)   # 返回 SqliteTradeRepository
config_repo = container.resolve(ConfigRepository)
```

---

## 4. 错误码

| 异常/返回 | 说明 |
|-----------|------|
| `None`（add_trade/close） | DualWrite 新败不阻塞场景 |
| `False`（update_state） | 乐观锁并发冲突，调用方需重试 |
| `ValueError`（get_position） | symbol:dir 有多个子系统持仓，需明确 sub_system |
| `None`（get_trade/get_position/get_state） | 记录不存在 |

---

## 5. 版本管理

### 5.1 版本策略

- Protocol 接口稳定，新增方法不破坏旧实现
- SQLite 实现通过 Alembic 迁移（`migrations/versions/`）
- DualWrite 机制：P0 json_legacy → P1 sqlite_unified 渐进迁移

### 5.2 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-09-30 | 初始接口规格（6 Protocol + sqlite_unified 实现 + DI） |

---

**文档版本**: v1.0
**最后更新**: 2026-09-30
