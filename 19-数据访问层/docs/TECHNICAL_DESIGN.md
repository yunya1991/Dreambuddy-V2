# 19-数据访问层 技术设计文档

> **版本**: v1.0 | **日期**: 2026-08-24
> **定位**: DreamBuddy V2 统一数据访问层（Data Access Layer, DAL）：Repository 协议抽象、SQLite 统一库架构、零停机双写迁移策略
> **关联文档**: [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) · [SCHEMA_DESIGN.md](./SCHEMA_DESIGN.md) · [MIGRATION_PLAN.md](./MIGRATION_PLAN.md)
> **关联 SSoT**: [ENGINEERING_INDEX.md](../ENGINEERING_INDEX.md) v3.0 · [1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md](../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) v3.0
> **兄弟子系统**: [18-数据获取中心](../18-数据获取中心/) — 采集层（外→内），本系统 = 存储访问层（内→内），职责边界见 §2.5

---

## 0. 文档说明

### 0.1 范围（解决什么问题 / 不解决什么问题）

**✅ 本系统解决的问题（AS-IS → TO-BE）：**

| AS-IS 现状（2026-08-24 已实锤） | TO-BE 目标（v1.0 交付后） |
|---|---|
| TradeRecord 在 5 处文件重复定义（字段漂移风险） | `unified_models.py` = 唯一 SSoT，其余通过 import aliasing 兼容 |
| 25+ 个独立 JSON/JSONL 文件做交易/风控/配置存储 | 所有结构化数据 → 1 个 `dreambuddy_core.db`（SQLite WAL） |
| 14 个币种独立 `macro_*.db` + bcrm/evolution/kg 多库散落 | 一库 21 张表，按前缀分区；跨域 JOIN 可用 |
| 并发写入靠 fcntl 锁 + busy_timeout=5000ms（DB locked 偶发） | 统一连接生命周期管理 + 幂等 UPSERT + 事务隔离 |
| 查询靠 JSONL 逐行 parse（O(n)） | B-tree 复合索引覆盖 95% 查询路径（O(log n)，典型 < 20ms） |
| 无法审计"谁何时改了 risk_state" | 核心表 created_at/updated_at 触发器 + ma_migration_audit |
| schema 演进靠手写 ALTER TABLE（storage.py L424 硬探测） | Alembic 版本化迁移（自动链路 + 幂等补列 helper） |

**❌ 非目标（YAGNI，避免过度设计）：**
- ❌ 不引入 SQLAlchemy/Peewee 等 ORM — 原生 sqlite3 + 轻封装符合项目"代码驱动+精确控制查询"偏好
- ❌ 不做多机部署 / 分布式锁 / 连接池 — PostgreSQL 阶段再做（参见 §7）
- ❌ 不做 Grafana/BI 报表接出
- ❌ 不做用户权限 / 多租户
- ❌ 不做数据采集 / SDK 适配 / API 调用爬取 — 归 [18-数据获取中心](../18-数据获取中心/)

### 0.2 SSoT 层级 & 冲突处理优先级

对齐全项目 [ENGINEERING_INDEX.md](../ENGINEERING_INDEX.md) §0.2 SSoT 体系：

| 层级 | 文档 | 冲突时优先级 |
|------|------|-------------|
| L0 | `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md` v3.0 | 架构层面最高 |
| L0 | 根目录 `ENGINEERING_INDEX.md` v3.0 | 工程索引层面最高 |
| L1 | 本文件（TECHNICAL_DESIGN.md v1.0） | 本子系统架构/机制/原则最高 |
| L1 | [SCHEMA_DESIGN.md](./SCHEMA_DESIGN.md) v1.0 | 表结构/字段/索引权威 |
| L1 | [MIGRATION_PLAN.md](./MIGRATION_PLAN.md) v1.0 | 迁移门禁/回滚SOP权威 |
| L2 | 子系统 `ENGINEERING_INDEX.md` | 文件级导航 |
| L2 | 模块内 docstring / 内联注释 | 代码级细节 |

### 0.3 关键术语表

| 术语 | 定义 |
|---|---|
| **DAL** | Data Access Layer，本系统所指 — 对业务层暴露稳定的 Repository 接口，屏蔽底层存储差异 |
| **Repository 模式** | 领域驱动设计（DDD）的集合式访问模式：每种聚合根（Trade/Position/...）对应一个 Repository，提供类似集合的 add/get/query 语义，业务层不知晓 SQLite/JSON 细节 |
| **Protocol (ABC)** | Python `typing.Protocol` + `abc.ABC` 定义接口合约；实现层按合约提供 JsonLegacy / Sqlite / DualWrite 三种 |
| **双写（DualWrite）** | 迁移期间同时写入旧存储和新存储，读路径锚定旧实现；对账 100% 通过后再切读 |
| **对账（Reconciliation）** | 新旧两存储按 COUNT + 行级 MD5 对比，生成差异报告；差异率 < 0.001% 为通过阈值 |
| **WAL 模式** | SQLite Write-Ahead Logging，并发读写性能 ≥ 3× 传统 DELETE 日志，配合 `synchronous=NORMAL` 最佳实践 |
| **幂等 UPSERT** | `INSERT ... ON CONFLICT(id) DO UPDATE` 语义 — 同一对象重复 add_trade 不产生重复行也不报错 |
| **Fail-Closed (FC)** | DB 不可用时抛出异常（拒绝交易），用于交易/风控域 |
| **Fail-Open (FO)** | DB 不可用时返回默认值（允许降级），用于配置/宏观缓存域 |
| **黄金约束 4 条** | §1.3 所述，任何阶段不可突破：随时可回滚 / 迁移期间不切读 / 差异只报警不阻断 / 旧文件保留 30 天 |

---

## 1. 概述

### 1.1 背景：4 大痛点量化（AS-IS，2026-08-24 实锤）

| # | 痛点 | 影响范围（已扫描） | 严重度 | 典型触发场景 |
|---|---|---|---|---|
| T1 | **并发写冲突丢数据** | `all_trades.jsonl` / 14×`macro_*.db` | 🔴 高 | BTC 急跌时多币种同时平仓 → 多进程竞争写 → "database is locked" → 写丢失 → 本地持仓 ≠ OKX 实盘 |
| T2 | **O(n) 查询性能瓶颈** | PerformanceTracker._load_state() 全 JSONL 加载；跨币种胜率分析 | 🟡 中 | 交易 > 1 万笔后 polling_trader 启动延时 2~5s；CBR KNN 检索需写 Python 聚合脚本 |
| T3 | **TradeRecord 5 处分裂** | trading_utils / dreamos_backtester / yijing_trainer / backtest engine / ab_comparison.py | 🔴 高 | V15 交易被 CBR 分析时缺失 `is_trial` / `regime_pred` 字段 → 静默字段漂移 → 训练-服务偏差 (training-serving skew) |
| T4 | **审计追溯能力缺失** | risk_state.json / 手动调整 daily_stats / releases/*.json | 🟠 中高 | 故障回溯时："8-23 谁改了 risk_state.loss_limit_pct?"——除 git（不记录运行时写入）无任何可举证来源 |

**技术债 SLA（按项目_memory 原则：工业级标准充分研究→彻底解决）**：按当前交易增速（≈ 30~60 笔/日），T1/T2 在 3 个月后恶化为生产阻断级问题；T3 已在 XAG/COIN/SOL 实战案例中观察到隐性影响。必须在 2026Q3 内完成 P0~P2 落地。

### 1.2 设计目标（SMART，5 条）

1. **G1 · 模型统一**：TradeRecord / PositionState / DailyStats / RiskState 4 核心模型 → `unified_models.py` 唯一 SSoT；剩余 4 处旧定义 DeprecationWarning 兼容导入 2 周后完成清理（2026-09-30 前）
2. **G2 · 协议抽象**：完成 6 个 Repository Protocol + 3 种实现（JsonLegacy / Sqlite / DualWrite）；业务代码改 import 路径即可接入，逻辑改动 0 行
3. **G3 · 零停机迁移**：P0~P2 全阶段，`DB_BACKEND=json_legacy` 环境变量 10 秒完成回滚（实测：launchctl 重启进程级）；交易主链路零不可用窗口
4. **G4 · 可演进**：Alembic 版本化迁移接入；Schema 版本号写入 `ma_schema_version`；协议层预留 PostgreSQL 实现接口（业务层零改切换）
5. **G5 · 可审计**：核心表 `created_at` / `updated_at` 触发器自动写入；每日 `PRAGMA integrity_check` 结果入 `ma_integrity_log`；双写差异 30 天历史留存

### 1.3 设计原则（5 条，黄金约束不可破）

1. **单一职责**：一个 Repository 管一个域；一个方法只做一个 CRUD；绝不跨域写多张表（除非显式事务包裹）
2. **开闭原则（OCP）**：对 PG / MySQL 等新存储实现**开放**（只需新增 `PgTradeRepo`）；对业务代码调用方**关闭**（无需改 import 或方法签名）
3. **兼容优先（经验 698940 / 1040063）**：
   - 迁移补丁只做**加列 + 默认值回填**，绝不删列 / 改数据类型
   - 旧 UNIQUE 约束语义保持，新增约束只在新数据上生效（代码侧再兜底去重）
   - CREATE TABLE 直接写**最终目标 Schema**；迁移 helper 只用于旧库补列；双路径无 schema 漂移
4. **显式优于隐式**：
   - 所有 SQL 100% 参数化（防注入 + 可预测 query plan）
   - 数据库路径仅通过 `DATA_DIR` 环境变量注入，禁止写死相对路径
   - DB locked / integrity fail / corrupt 三类异常分别枚举处理，不静默吞
5. **黄金约束 4 条（不可破，违反即 P2 事故）**：
   - ✦ GC1 随时可回滚：`json_legacy` 实现永不删除，保留至少 6 个月
   - ✦ GC2 迁移期间读永不切新：P1 双写阶段，读取永远返回 json_legacy 结果，next_gen 只做影子对账
   - ✦ GC3 差异永远只报警不阻断：DualWrite 期间任何新库写入失败、读取差异 → `ma_migration_audit` 记日志，主链路永远按旧实现执行
   - ✦ GC4 旧文件保留 30 天：所有 JSON/旧 SQLite 文件断旧写后移入 `data/archive/YYYY-MM-DD_pre_unification/`，tar.gz 加密，30 天确认无事故后再决定删除

### 1.4 非目标清单（YAGNI）

| 功能 | 不做的原因 | 触发条件（何时重开讨论） |
|---|---|---|
| 重型 ORM（SQLAlchemy） | 你们偏好原生 SQL，项目已有 kg_store.py / storage.py 熟练使用 sqlite3；ORM 生成 SQL 查询路径不可控 | 同时支持 > 3 种异构数据库且需手写大量方言 SQL |
| PostgreSQL 直接起步 | SQLite 对单机 1-5 写进程完全胜任（行业共识，参考 Predict & Profit 团队最佳实践）；PG 运维成本远超当前收益 | 触发 §7.1 所列 5 条件任意 1 条 |
| 多机部署 / pgbouncer / 分布式锁 | 你们当前是单机单人交易场景（macOS + launchd） | 未来 2 台+ VPS 同时读写同一 DB |
| Grafana / Metabase BI 对接 | 当前无仪表盘诉求；polling_trader 已有飞书推送闭环 | 产品化 / 面向团队需可视化报表 |
| TDE 透明列级加密 | 目前单机 mac + 本地文件；OS 级 FileVault 已覆盖 | 合规审计强制要求或多租户 |

---

## 2. 架构设计

### 2.1 顶层架构图（四层分层）

```
┌──────────────────────────────────────────────────────────────────────────┐
│  业务消费层（Consumer）— 业务代码零改逻辑，仅改 import 路径                │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────┐ ┌────────┐  │
│  │polling_     │ │V15 马丁      │ │ 通用风控     │ │ DreamOS │ │ 18-数据│  │
│  │trader.py    │ │_trader.py    │ │  engine     │ │ 演化    │ │ 获取   │  │
│  │易经 A0-A9   │ │V15 决策执行   │ │ pre-trade   │ │检查点   │ │ 中心   │  │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └────┬────┘ └───┬────┘  │
└─────────┼───────────────┼───────────────┼──────────────┼──────────┼───────┘
          │               │               │              │          │
          ▼               ▼               ▼              ▼          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Repository 协议层（ABC / Protocol） — 稳定不变 SSoT                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐ │
│  │ TradeRepository  │  │PositionRepository│  │ MarketMacroRepository   │ │
│  │ ·add_trade()     │  │ ·open_position() │  │ 14币合并单库            │ │
│  │ ·query_trades()  │  │ ·close_position()│  │ ·append_fear_greed()    │ │
│  │ ·get_daily_stats│  │ ·get_active_pos() │  │ ·append_funding_rate()  │ │
│  └──────────────────┘  └──────────────────┘  │ ·query_*_range()→DataF │ │
│  ┌──────────────────┐  ┌──────────────────┐  └─────────────────────────┘ │
│  │ RiskRepository   │  │ConfigRepository  │  ┌─────────────────────────┐ │
│  │ 单行状态风控     │  │ 258 份版本 config │  │KnowledgeGraphRepository │ │
│  │ ·get_risk_state()│  │ ·get_config(latest│  │ triples/entities/FTS5  │ │
│  │ ·add_risk_case() │  │ ·list_versions()  │  │ 沿用现有 KGStore 设计   │ │
│  └──────────────────┘  └──────────────────┘  └─────────────────────────┘ │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │ 依赖注入（di.py，按环境变量切换后端）
           ┌────────────────────┼────────────────────┐
           ▼                    ▼                    ▼
┌────────────────────┐ ┌────────────────────────┐ ┌────────────────────────┐
│ JsonLegacyImpl     │ │ DualWriteDecorator      │ │ SqliteUnifiedImpl      │
│（现状薄适配器）     │ │（迁移期：写双份+对账）   │ │（统一 SQLite 新实现）   │
│ → 25+ JSON/JSONL   │ │ → 写：先旧后新，旧为准  │ │ → dreambuddy_core.db   │
│ → 18+ 散落 SQLite  │ │ → 读：始终返回旧结果    │ │ → 6 域 × 21 表 × 9 索引│
│ → 5 处模型兼容导入  │ │ → 差异：ma_migration   │ │ → WAL + FK + 复合索引  │
└────────────────────┘ └────────────────────────┘ └────────────────────────┘
           ↑                       ↑                         ↑
           └───────────────────────┴─────────────────────────┘
               DB_BACKEND 环境变量控制三态
             json_legacy / dual_write / sqlite
```

**架构 SLA**：Protocol 层（第二层）一旦 v1.0 冻结，除非经 §0.2 SSoT 流程变更，否则**业务代码永远不感知底层存储切换**。从 JsonLegacy → DualWrite → Sqlite → 未来 Postgres，业务代码仅需改动 1 行环境变量。

### 2.2 Repository 协议定义（SSoT 方法签名）

6 个 Repository 完整方法签名（Protocol + ABC 双保险）：

#### 2.2.1 TradeRepository（交易记录 + 每日统计）

```python
from abc import ABC, abstractmethod
from typing import Literal
from dreambuddy_dal.unified_models import TradeRecord, DailyStats

class TradeRepository(ABC):
    """交易记录与每日绩效聚合的存储协议。

    幂等语义：add_trade 按 trade_id 为 UNIQUE 键，重复调用 = UPDATE updated_at。
    统计语义：get_daily_stats 默认实时聚合（可 5min 结果缓存）。
    """

    @abstractmethod
    def add_trade(self, record: TradeRecord) -> str:
        """幂等写入一笔交易；返回 trade_id（与传入 record.trade_id 一致）"""

    @abstractmethod
    def batch_add_trades(self, records: list[TradeRecord]) -> int:
        """原子事务批量导入；成功返回实际写入行数；失败整体 ROLLBACK。"""

    @abstractmethod
    def get_trade(self, trade_id: str) -> TradeRecord | None:
        """按主键取单条；不存在返回 None（不抛异常）。"""

    @abstractmethod
    def query_trades(
        self,
        symbol: str | None = None,
        direction: Literal["long", "short"] | None = None,
        start_ts: str | None = None,   # ISO 格式 "2026-08-20T00:00:00+0800"
        end_ts: str | None = None,
        is_closed: bool | None = None,  # None=全部 / True=已平仓 / False=持仓中
        is_trial: bool | None = None,   # None=全部 / True=轻仓试错
        strategy_source: str | None = None,  # "v15" / "yijing" / "classic" 等
        limit: int = 1000,
    ) -> list[TradeRecord]:
        """复合查询；symbol + start_ts + end_ts 命中复合索引 idx_trades_symbol_time。"""

    @abstractmethod
    def get_daily_stats(self, date_str: str) -> DailyStats | None:
        """按日期（"2026-08-24"）统计；默认从 trades 实时计算，结果缓存 5min。
        若 daily_stats_overrides 有人工覆盖记录，优先取覆盖值。"""

    @abstractmethod
    def query_daily_stats_range(self, start_date: str, end_date: str) -> list[DailyStats]: ...

    @abstractmethod
    def upsert_daily_stats_override(self, stats: DailyStats, reason: str = "") -> None:
        """人工覆盖某日统计（OKX 对账差异场景）；写入 daily_stats_overrides 表并附理由。"""
```

#### 2.2.2 PositionRepository（当前持仓 + 试错评估标记）

```python
from dreambuddy_dal.unified_models import PositionState, CloseInfo

class PositionRepository(ABC):
    @abstractmethod
    def open_position(self, pos: PositionState) -> str:
        """开仓登记；inst_id 唯一约束；重复 = FailClosed（抛 DuplicatePositionError）。"""

    @abstractmethod
    def close_position(self, inst_id: str, close_info: CloseInfo) -> PositionState:
        """平仓结算；原子更新 exit_price/exit_time/pnl 并标记 closed。"""

    @abstractmethod
    def get_active_positions(self, symbol: str | None = None) -> list[PositionState]:
        """查询当前全部持仓（exit_time IS NULL）；可选按 symbol 过滤。"""

    @abstractmethod
    def get_position(self, inst_id: str) -> PositionState | None: ...

    @abstractmethod
    def update_position_market(
        self, inst_id: str, mark_price: float, unrealized_pnl: float
    ) -> None:
        """轮询刷价专用；只刷新 mark_price/unrealized_pnl/updated_at，不改变 opened_at。"""

    @abstractmethod
    def mark_trial_eval_done(
        self, inst_id: str, result: Literal["add", "close", "hold"]
    ) -> None:
        """XAG 轻仓试错 30 分钟评估标记；置 trial_eval_done=1 并写决策结果。"""
```

#### 2.2.3 MarketMacroRepository（14 币宏观合并单库）

```python
import pandas as pd

class MarketMacroRepository(ABC):
    """所有宏观指标按 symbol + timestamp 复合主键存储；
    读返回 DataFrame，签名对齐现有 macro_data_fetcher.py，保证 0 改动接入。"""

    # 恐惧贪婪指数（全局，无 symbol）
    @abstractmethod
    def append_fear_greed(self, ts: int, index: int, trend_7d: float | None) -> None: ...
    @abstractmethod
    def query_fear_greed_range(self, start_ts: int, end_ts: int) -> pd.DataFrame: ...

    # 资金费率（按币种）
    @abstractmethod
    def append_funding_rate(self, symbol: str, ts: int, funding_rate: float) -> None: ...
    @abstractmethod
    def query_funding_rate_range(self, symbol: str, start_ts: int, end_ts: int) -> pd.DataFrame: ...

    # 未平仓合约量（按币种）
    @abstractmethod
    def append_open_interest(self, symbol: str, ts: int, open_interest: float) -> None: ...
    @abstractmethod
    def query_open_interest_range(self, symbol: str, start_ts: int, end_ts: int) -> pd.DataFrame: ...

    # 以下三类按同样模式（对应 macro_data_fetcher.py 已实现采集维度）：
    @abstractmethod
    def append_liquidation(self, symbol: str, ts: int, liq_long, liq_short) -> None: ...
    @abstractmethod
    def append_long_short_ratio(self, symbol: str, ts: int, ratio) -> None: ...
    @abstractmethod
    def append_taker_volume(self, symbol: str, ts: int, buy_vol, sell_vol) -> None: ...
```

#### 2.2.4 RiskRepository（风控状态 + 风控案例）

```python
from dreambuddy_dal.unified_models import RiskState, RiskCaseRecord

class RiskRepository(ABC):
    @abstractmethod
    def get_risk_state(self) -> RiskState:
        """✅ Fail-Closed：DB 不可用时抛 RiskStateUnavailableError（调用方按项目风控偏好降级）。
        DB 有空或无记录时返回 RiskState.DEFAULT（中性安全默认值）。"""

    @abstractmethod
    def update_risk_state(self, partial: dict) -> RiskState:
        """部分字段原子 UPDATE（id=1 单行约束）；成功后返回最新状态。"""

    @abstractmethod
    def add_risk_case(self, case: RiskCaseRecord) -> str:
        """新增风控告警案例（Risk Case）；幂等 case_id。"""

    @abstractmethod
    def query_risk_cases(
        self, severity_ge: int = 1, start_ts: str | None = None, limit=200
    ) -> list[RiskCaseRecord]: ...
```

#### 2.2.5 ConfigRepository（258 份版本配置）

```python
class ConfigRepository(ABC):
    """策略配置 / baseline 版本管理；替代 releases/v0.1.xxx.json × 258。"""

    @abstractmethod
    def add_config_version(
        self, version: str, payload: dict, changelog: str = "", released_at: str | None = None
    ) -> None:
        """幂等：同一 version 重复提交 = IGNORE（历史不可篡改）。"""

    @abstractmethod
    def get_config(self, version: str | Literal["latest"] = "latest") -> dict:
        """按版本号取配置；"latest" = ORDER BY released_at DESC LIMIT 1。"""

    @abstractmethod
    def list_versions(self, limit: int = 50) -> list[tuple[str, str, str]]:
        """最近 N 版元信息 [(version, released_at, changelog摘要)]。"""
```

#### 2.2.6 KnowledgeGraphRepository（知识图谱 — 沿用现有 KGStore）

```python
# 完全对齐现有 kg_store.py（L61+）的 public 方法签名，避免重写双时态 + FTS5
class KnowledgeGraphRepository(ABC):
    @abstractmethod
    def add_triple(self, s, p, o, confidence=1.0, sources=None, temporal_start=None, ...) -> None: ...
    @abstractmethod
    def query_triples(self, s=None, p=None, o=None) -> list[dict]: ...
    @abstractmethod
    def add_entity(self, entity_id, label, aliases=None, category=None, metadata=None) -> None: ...
    @abstractmethod
    def search_subject(self, keyword: str, top_k=10) -> list[tuple[str, float]]: ...
    @abstractmethod
    def fts_search(self, query: str, top_k=20) -> list[tuple[str, float]]:  # FTS5 MATCH
    ...  # 其余约 18 个 public 方法按 kg_store.py 原样签名对齐
```

### 2.3 DualWriteRepository 装饰器（迁移双写对账核心）

**设计哲学（黄金约束 GC3）**：永远优先锚定旧实现；新实现写失败 / 读差异永不阻断主链路，只写 `ma_migration_audit` 审计日志 + 告警日志。

以 TradeRepo 为例（其余 5 个 Repo 装饰器同理）：

```python
# implementations/dual_write/trade_repo.py
class DualWriteTradeRepository(TradeRepository):
    def __init__(
        self,
        legacy: TradeRepository,
        next_gen: TradeRepository,
        auditor: MigrationAuditor,   # 写 ma_migration_audit 表 + 本地 jsonl 冗余
        fail_fast_on_legacy_error: bool = True,
    ):
        self.legacy = legacy
        self.next_gen = next_gen
        self.auditor = auditor
        self.fail_fast_on_legacy_error = fail_fast_on_legacy_error  # ✅ True（GC1/GC3）

    def add_trade(self, record: TradeRecord) -> str:
        # ⭐ Step 1：先写旧实现（交易主链路锚定旧存储）
        try:
            legacy_id = self.legacy.add_trade(record)
        except Exception as e:
            # 旧写失败 = 真实生产事故（如磁盘满）→ 抛异常给调用方按原链路处理
            self.auditor.log("legacy_write_fail", "add_trade", record.trade_id, str(e))
            raise

        # ⭐ Step 2：后写新实现（异常吞 + 审计，绝不阻断）
        try:
            next_id = self.next_gen.add_trade(record)
        except Exception as e:
            self.auditor.log("next_gen_write_fail", "add_trade", record.trade_id, str(e),
                             severity=2)
            return legacy_id  # ⭐ 永远返回 legacy 结果（GC2：读永不切新）

        # ⭐ Step 3：幂等 ID 一致性校验（仅警告）
        if legacy_id != next_id:
            self.auditor.log("id_mismatch", "add_trade", record.trade_id,
                             f"legacy={legacy_id}, next_gen={next_id}", severity=1)
        return legacy_id

    def query_trades(self, **kwargs) -> list[TradeRecord]:
        """读路径：P1 期间永远返回 legacy；next_gen 仅做影子 CRC32 对比。"""
        primary = self.legacy.query_trades(**kwargs)  # ⭐ 永远以旧为准（GC2）

        try:
            shadow = self.next_gen.query_trades(**kwargs)
            diff = self.auditor.compare_trade_lists(primary, shadow)
            if diff.total_mismatches > 0:
                self.auditor.log(
                    "read_diff", "query_trades",
                    f"sym={kwargs.get('symbol')} range={kwargs.get('start_ts')}~{kwargs.get('end_ts')}",
                    diff.summary(),
                    severity=2 if diff.total_mismatches > 10 else 1,
                )
        except Exception as e:
            self.auditor.log("next_gen_read_fail", "query_trades", "-", str(e), severity=1)
        return primary  # ⭐ 永远返回 legacy
```

**对账门禁（从 DualWrite 进入读切新的硬性条件）**：

| 阶段 | 度量指标 | 持续时长 | 动作 |
|---|---|---|---|
| Day 1~3 | 启动观察期 | 3×24h | 仅双写；不做任何读对比 |
| Day 4~10 | 影子读开启 + 双写差异率 < 0.01% | 连续 7 天 | 允许读对比（后台异步 CRC32） |
| Day 11+ | 读一致率 ≥ 99.99% **且** DB locked 异常 = 0 | 连续 72h | 运维 Checklist 打勾 → 切 env `READ_SOURCE=next_gen` |
| Day 25+ | 读走 next_gen 连续 14 天 0 事故 | 连续 14 天 | 断旧写 → 进入 P2 加固 |

### 2.4 SQLite 单库 Schema 分区策略（1 库 = 7 域前缀 × 约 21 张表）

**ADR-19-003：选 1 库分表前缀，不选 3 库隔离**

| 选项 | 优势 | 劣势 |
|---|---|---|
| ⭐ **1 库 + 表名前缀** | ① 单文件备份/迁移极简（3 个文件：db/WAL/SHM）② 跨域 JOIN 可用（如 risk_state × trades 回撤分析）③ PRAGMA 一处设置 | 单库理论极限 ~ 2TB（你们上限 < 5GB，可忽略） |
| 3 库隔离（交易/宏观/风控） | 隔离性好，坏一库不影响其他 | ① 跨库查询无 JOIN，应用层拼数据 ② 备份策略复杂化 ③ PRAGMA 配置重复维护 |

**推荐：1 库 + 前缀分区**（完全满足你们量级且运维成本最低）。

#### 域前缀约定（SCHEMA_DESIGN.md 详细展开字段）：

| 前缀 | 对应 Repository | 表数 | 表名 | 典型查询频率 |
|---|---|---|---|---|
| `tr_` | TradeRepo | 3 | tr_trades / tr_daily_stats / tr_daily_stats_overrides | 极高（交易触发/分钟级查询） |
| `po_` | PositionRepo | 2 | po_positions / po_price_refresh_log | 高（每分钟刷价） |
| `mm_` | MarketMacroRepo | 6 | mm_fear_greed / mm_funding_rate / mm_open_interest / mm_liquidation / mm_long_short_ratio / mm_taker_volume | 中（15m/1h 级） |
| `rs_` | RiskRepo | 2 | rs_state（单行 CHECK id=1） / rs_cases | 低（事件触发） |
| `cv_` | ConfigRepo | 1 | cv_config_versions | 极低（发版） |
| `kg_` | KnowledgeGraphRepo | 4 | kg_triples / kg_entities / kg_entity_aliases / kg_fts 索引 | 中（知识线写入） |
| `ma_` | Meta 审计域（系统内部） | 3 | ma_schema_version / ma_migration_audit / ma_integrity_log | 低（Cron + 迁移期） |
| **合计** | 6 Repo + Meta | **21** | — | — |

**容量预估（按 3 年增长 5× 交易量）**： ≈ 3~5 GB（远低于 SQLite 官方 280TB 理论上限）；查询通过复合索引 95% 路径命中 → 性能无虞。

### 2.5 与 18-数据获取中心 的职责边界（互补、非替代）

| 维度 | 18-数据获取中心（Collector） | 19-数据访问层（Repository / DAL） |
|---|---|---|
| **数据流向** | 外部世界 → 内部（FRED/Etherscan/新闻/链上等原始数据采集） | 内部 ↔ 内部（业务层读写已结构化落库的数据） |
| **核心能力** | SDK 适配 / Scrapy / Playwright / 脏数据清洗 / 源端去重 | Repository 协议 / 事务 / 并发控制 / 索引 / 审计 / 版本迁移 |
| **数据形态** | DataFrame / 半结构化 JSON（各源 schema 各异） | 强类型 SSoT：TradeRecord / PositionState / DailyStats 等 |
| **写权限** | ✅ 允许调用 `get_market_macro_repo().append_*(...)` **通过 Repo 写** | ❌ 永不直写外部 API（完全只读业务域） |
| **读权限** | ❌ 禁读 trade/position/risk 业务域（隔离原则） | ✅ 6 域全开查询 |
| **依赖关系** | 18 → 依赖 19 的 MarketMacroRepo 作为标准写路径 | 19 零依赖 18（可独立测试/部署） |
| **连接 SQLite** | ❌ 严禁直连 `dreambuddy_core.db` 文件 | ✅ 唯一允许直连的模块（`connection.py` 生命周期统一管理） |

**强制执行手段（编码规范）**：`18-数据获取中心/` 代码中 `grep "sqlite3.connect\|dreambuddy_core.db"` 任何命中 = CI 失败。所有 18 → 19 写入必须通过 `from dreambuddy_dal import get_market_macro_repo`。

---

## 3. 实施路线图与迁移步骤（9 周，可度量可回滚）

（全文同步见 [MIGRATION_PLAN.md](./MIGRATION_PLAN.md)，以下为 TECHNICAL_DESIGN 架构级摘要）

### 3.1 阶段总览（甘特式里程碑）

| 阶段 | 周期 | 人日 | 核心交付物 | 门禁验收标准 |
|---|---|---|---|---|
| P0 · 基建与抽象 | W1~W2 | 2.5 | unified_models.py + 6 Protocol + JsonLegacyImpl×6 + di.py 依赖注入 | TDD 协议层 100% 覆盖；旧 import 路径全兼容（DeprecationWarning） |
| P1 · 统一库+首次迁移 | W3~W5 | 3.5 | dreambuddy_core.db schema_init + SqliteImpl×6 + DualWriteImpl×6 + import_all_from_json.py 三批导入 | 三向对账（源 count = 目标 count = 回读 count）100% 匹配；双写 3 天 0 DB locked |
| P2 · 生产切流+观察 | W6~W7 | 1.5 | DualWrite 生产运行 14 天 + 切读/断旧写门禁 Checklist + Alembic 首版 | 双写差异率 < 0.001% 连续 72h；5 项人工门禁全打勾 |
| P3 · 运维加固+归档 | W8~W9 | 1.5 | backup/integrity/rotate 三件套 + ma_integrity_log 接入 + 旧 JSON 归档脚本 | Cron 7 天执行无异常；冷备份还原演练（restore + PRAGMA + 抽样）100% 匹配 |
| P4 · PG 桥接（可选） | 条件成熟再启动 | ≈3 | PgRepository×6 + pgloader 配置 + 双写 3 天 | 触发 §7.1 5 条 PG 条件任意 1 条 |

### 3.2 P0 阶段关键：统一模型 + 兼容导入（避免被追问"其它表呢"）

**经验落实（1040063 失败教训）**：绝不只给 TradeRecord 做合并后被追问"Position/DailyStats/RiskState 呢" → 一次性合并 4 核心模型并统一出口，迁移 helper 覆盖全表迁移。

**兼容导入 4 步（薄适配 + DeprecationWarning）**：
1. `dreambuddy_dal.unified_models` 作为唯一 SSoT 定义
2. 对 trading_utils.py / dreamos_backtester.py / yijing_trainer.py / backtest engine / ab_comparison.py 5 处旧定义，文件开头 3 行替换：
   ```python
   from dreambuddy_dal.unified_models import (  # noqa: F401 兼容旧导入
       TradeRecord, PositionState, DailyStats, RiskState,
   )
   import warnings
   warnings.warn(
       "请于 2026-09-30 前改为 from dreambuddy_dal import TradeRecord",
       DeprecationWarning, stacklevel=2,
   )
   ```
3. TDD：`tests/test_compat_imports.py` — 5 处旧路径 import 成功 + 字段等价
4. 2026-10-01 前一次性清理 5 处旧 class 定义

### 3.3 P1 阶段关键：幂等初始化 + 三批迁移

**经验落实（1040063：CREATE TABLE = 最终 Schema + _add_column_if_missing helper 统一补列）**：
- `TARGET_CREATE_TABLES_SQL`（21 张完整建表语句，最终态）
- 对旧库（历史已存在的表）：`_add_column_if_missing(conn, table, col, ddl)` 逐列探测补 DEFAULT
- 对 SQLite 不支持的 ADD CONSTRAINT：用"4 步重建法"：建 t_new → 拷数 → drop 旧 → rename
- `CREATE INDEX IF NOT EXISTS` 全部最后执行（避免建表期间索引锁表）

**三批迁移 ROI 排序（独立事务独立对账失败可单独回滚）**：
1. Batch 1 ★：all_trades.jsonl + daily_stats.json + position_tracker.json + risk_state.json → 最高 ROI
2. Batch 2 ★☆：14×macro_*.db + releases/v0.1.xxx.json × 258
3. Batch 3：knowledge_graph.db + RSK cases + guardian cases + 30 天 polling trader logs（可晚一周）

### 3.4 P2 阶段关键：5 项人工门禁 Checklist（全打勾才能切读）

| # | 门禁项 | 测量方法 | 通过标准 | 确认栏 |
|---|---|---|---|---|
| G-1 | 双写差异率 | ma_migration_audit 全量统计 result ≠ OK 的比例 | 连续72h **< 0.001%**（≤1/10万） | ▢ |
| G-2 | DB locked 0 次 | trader_YYYYMMDD.log grep "database is locked" | 连续72h 0 条 | ▢ |
| G-3 | 影子读一致率 | 全量 query_trades / get_daily_stats 新旧对比 CRC32 | 连续72h **≥ 99.99%** | ▢ |
| G-4 | 回滚演练 | 手动改 `DB_BACKEND=json_legacy` 重启进程跑 30min | 写入 JSON 正常；无 DB 句柄残留；30min 数据完整 | ▢ |
| G-5 | 备份可用性 | 取 W6 生成的冷备份 → 还原到新临时路径 → PRAGMA + 10 行抽样查询 | integrity=ok；样本 100% 匹配 | ▢ |

### 3.5 关键失败场景回滚策略（§3 详细版见 MIGRATION_PLAN.md）

| 场景 | 回滚动作 | RTO（恢复时间目标） |
|---|---|---|
| 迁移脚本中途崩溃（Batch N） | 事务已 ROLLBACK → 修正数据/脚本 → 重跑（幂等 UPSERT 已批不重做） | < 30min |
| DualWrite 上线后新库写失败率 > 1% | env 改 `DB_BACKEND=json_legacy` → launchctl 重启 trading；新库可后续重建 | < 10min |
| 切读后 Query 返回结果异常 | env 改 `READ_SOURCE=legacy` 保留双写；查 EXPLAIN 修索引；不切旧写 | < 5min |
| SQLite corruption（极低） | ① 切 json_legacy ② 从最近 integrity=ok 备份还原 ③ sqlite3 .recover 抢救 | 最坏 2~4h |
| Alembic 迁移失败 | 删 db 文件 → 从备份恢复 → 重新 import_all_from_json（幂等） | < 30min |

---

## 4. 错误处理与降级

### 4.1 Fail-Closed / Fail-Open 选择矩阵

| 域 / Repository | 默认策略 | 原因 | 降级默认值（FO 时） |
|---|---|---|---|
| **TradeRepository** | **Fail-Closed** | 交易记录丢失 = 实盘 vs 本地不一致 = 后续开平仓错误（风险：直接亏损） | —（DB 不可用 → 抛 TradeRepoUnavailable → 调用方触发：不开新仓，持仓手动管） |
| **PositionRepository** | **Fail-Closed** | 持仓状态错 → 重复开仓 / 平仓点错 | —（同上，禁开新仓；已有持仓标记"uncertain"走人工处置） |
| **MarketMacroRepository** | **Fail-Open** | 宏观缓存缺几小时数据 ≠ 安全事故（易经推理仍可用最新 OKX 实时 API 兜底） | 空 DataFrame + 告警；调用方按"无宏观数据跳过评分" |
| **RiskRepository** | **Fail-Closed（状态）+ Fail-Open（案例）** | risk_state 错 = 可能超风控上限开仓（严重）；case 丢 = 可补记录 | 状态：DEFAULT_SAFE_RISK_STATE（禁开仓）；案例：空 list + 日志 |
| **ConfigRepository** | **Fail-Open** | 配置加载失败 → 回退代码内硬编码基线 baseline_config_v1.json 即可 | 基线 baseline + 警告日志 |
| **KnowledgeGraphRepo** | **Fail-Open** | KG 是增强能力，缺失不降系统安全等级 | 空搜索结果 + 告警；CBR 仅退化为交易历史匹配 |

### 4.2 SQLite 异常分类处理（具体捕获 + 具体动作）

```python
# connection.py 异常枚举（按 sqlite3 官方错误码分类）
class DalException(Exception): pass
class DalLockedException(DalException): pass       # SQLITE_BUSY / SQLITE_LOCKED → retry 3 次 × 500ms
class DalCorruptException(DalException): pass      # SQLITE_CORRUPT → 切 json_legacy + 告警飞书
class DalMalformedException(DalException): pass    # SQLITE_MALFORMED（SQL语法错，开发期）→ FATAL日志
class DalConstraintException(DalException): pass   # SQLITE_CONSTRAINT（UNIQUE冲突，业务显式处理）
class DalIOException(DalException): pass           # SQLITE_IOERR / SQLITE_NOMEM → 切 json_legacy + 告警
```

**重试策略（DalLockedException only）**：其他异常一律不重试（避免雪崩写入放大）。
```python
@contextmanager
def auto_retry_locked(retries=3, wait_ms=500):
    for attempt in range(retries):
        try:
            yield
            return
        except sqlite3.OperationalError as e:
            if "database is locked" not in str(e).lower() or attempt == retries -1:
                raise DalLockedException(str(e)) from e
            time.sleep(wait_ms / 1000.0 * (attempt + 1))  # 线性退避 500/1000/1500ms
```

### 4.3 日志规范（结构化 JSONL 便于未来切 CH 分析）

所有 DAL 层日志统一写入 `<DATA_DIR>/logs/dal_YYYYMMDD.jsonl`，字段：
```json
{"ts":"2026-08-24T15:30:12+0800","level":"WARN","module":"dal.dualwrite.trade","event":"next_gen_write_fail",
 "trade_id":"TRD-XXXXXX","err":"UNIQUE constraint failed: tr_trades.trade_id","retry_used":2,
 "latency_ms":532}
```

**强制日志触发阈值**：
- **WARN**：查询 > 200ms（需 EXPLAIN 分析）；双写差异任意条；DalLockedException 重试 2 次以上才成功
- **ERROR**：任何 DalCorruptException / DalMalformedException / DalIOException；integrity_check ≠ ok
- **INFO**：连接创建/关闭、backup.sh 成功、Alembic 迁移成功（每次版本升级至少一条）

### 4.4 一键回滚开关（黄金约束 GC1 工程化）

**物理双保险**：
1. **环境变量**（进程级，5 秒生效）：
   ```bash
   # 全局 ~/.zshrc 或 launchd plist 注入
   export DB_BACKEND=json_legacy       # 立刻脱离新库（JsonLegacyImpl 读现有 JSON）
   # launchctl unload && launchctl load 对应交易进程
   ```
2. **应急 kill switch 文件**（秒级检测，无需重启）：
   若 `/path/to/DISABLE_DAL_NEW` 文件存在，DAL 初始化自动 fallback json_legacy（用于极端紧急情况，如进程 launchd 每 30s 自动重启无法改 env）：
   ```python
   # di.py 开头：
   KILL_SWITCH = Path(os.getenv("DATA_DIR", ".")) / "DISABLE_DAL_NEW"
   def _default_backend():
       if KILL_SWITCH.exists():
           logging.critical("[DAL KILL-SWITCH] 检测到应急开关文件，强制使用 json_legacy")
           return "json_legacy"
       return os.getenv("DB_BACKEND", "json_legacy")
   ```

---

## 5. 测试策略（对齐项目 TDD 偏好）

### 5.1 测试金字塔（覆盖率要求 + 示例测试点）

| 测试层 | 占比 | 示例用例 | 覆盖率目标 |
|---|---|---|---|
| **单元测试** | 60% | Protocol 每个方法 × 3 实现各自行为、unified_models 字段兼容导入、auto_retry_locked 退避 | 协议层 100%；实现层 ≥ 90% |
| **集成测试** | 25% | DualWrite 双写差异报警（但不阻断）、三批 import 三向对账 1000 行模拟、FK 约束生效 | 21 表 × 至少 2 条（写+读），100% 覆盖 |
| **迁移测试** | 10% | 真实 `all_trades.jsonl`（脱敏）导入 → DB → 重新导出 → md5 对比；索引命中验证（EXPLAIN QUERY PLAN 含 "USING INDEX"） | 每批 1 条端到端用例（含"坏字段"容错） |
| **故障注入** | 5% | sqlite3 连接抛 OperationalError("database is locked") × 3 次 → DalLockedException；DB 文件截断 → integrity_check fail → 切 json_legacy；磁盘满模拟 (ulimit) | 4.2 枚举的 5 类异常全覆盖 |

### 5.2 关键 TDD 约束

- **写测试在前**：Repository 每个方法写完 Protocol，立刻写 3 份实现的黑盒测试（红）→ 再写实现代码（绿）→ 重构
- **零真 DB 依赖**：测试使用 `:memory:` SQLite 或 `tempfile.mkdtemp()` 用完即删；CI 跑完无数据残留
- **双写契约测试**：DualWrite 装饰器注入 MockLegacy / MockNextGen，逐场景验证：
  - legacy_ok + next_ok → 返回 legacy_id
  - legacy_ok + next_fail → 返回 legacy_id + 审计日志
  - legacy_fail + next_ok → 抛异常（GC3：legacy 为锚定）
  - legacy_fail + next_fail → 抛原异常

### 5.3 性能基线测试（迁移前/后对比）

| 基准测试 | 前（JSONL 现状） | 目标（SQLite 后） | 通过标准 |
|---|---|---|---|
| 1 万笔交易加载 + 筛选最近 30 天 BTC | 2500ms (O(n) 逐行 parse) | < 30ms (idx_trades_symbol_time) | ≥80× 加速 |
| daily_stats 取最近 90 天 | 800ms（重算 90 天） | < 20ms（tr_daily_stats 直接读） | ≥40× 加速 |
| 100 并发 add_trade（多线程模拟） | 4200ms（文件锁冲突） | < 400ms（WAL + 事务批量） | ≥10× 加速 |

---

## 6. 运维与备份

### 6.1 Cron 三件套（SOP 详情见 MIGRATION_PLAN.md）

Cron（或 macOS launchd plist `com.dreambuddy.db-maintenance`）**每日 03:00** 执行：

| 脚本 | 动作 | 告警条件 |
|---|---|---|
| **backup.sh** | `sqlite3 $DB ".backup --wait 5000 $BACKUP_DIR/dreambuddy_core_YYYYMMDD.db"` （SQLite 官方在线热备份命令，安全） | `.backup` 返回非零 → 飞书 CRITICAL |
| **integrity.sh** | ① `PRAGMA integrity_check` 结果写入 `ma_integrity_log`；② 记录文件大小；③ 计算 WAL 积压深度（若 WAL > DB 10% 触发 checkpoint） | result ≠ "ok" → 飞书 CRITICAL + 自动切 json_legacy（Kill-Switch） |
| **rotate.sh** | ① gzip 压缩 7 天前 `.db` → `.db.gz`；② 删除 30 天前 `.db.gz`；③ `ma_schema_version ≥ 1` 才执行（防早期空库误删） | 磁盘剩余 < 20% → 飞书 WARNING |

### 6.2 数据生命周期（3 级分层）

| 层级 | 范围 | 存放路径 | 压缩 | 保留期 |
|---|---|---|---|---|
| 🥇 **热数据** | 最近 30 天交易 / 当前持仓 / 30 天宏观指标 | `dreambuddy_core.db`（主库） | —（WAL） | 永久 |
| 🥈 **冷数据** | 31~365 天前交易 / 历史宏观 | `data/cold_store/cold_YYYY.db`（按月分片导出） | gzip | 12 个月 |
| 🥉 **归档** | 1 年前历史 / 断旧写前的 JSON 快照 | `data/archive/pre_unification_aug_2026.tar.gz.aes256` | AES-256 + gzip | 永久（对象存储备份） |

### 6.3 Alembic 迁移链（Schema 演进 SLA）

**Schema 版本规则 = SemVer 兼容语义**：
```
ma_schema_version.version 格式：MAJOR.MINOR.PATCH
  MAJOR：破坏性变更（删列 / 改类型）→ 必须配合 P4 PG 桥接或新库重建
  MINOR：向后兼容加列 / 加索引 → 旧代码零改可跑
  PATCH：索引调优 / 视图修正
```

**发布流程**：
```
developer: alembic revision -m "add mm_long_short_ratio.base_asset_col"
           ↓ 生成 2a8f9e1c7d_add_...py
           ↓ local alembic upgrade head + alembic downgrade -1 回滚测试通过
           ↓ PR → Code Review（必须包含 downgrade 可执行验证截图）
           ↓ 合 main → 先跑 staging DB（冷备份还原 = staging）升级通过
           ↓ 生产：03:00 Cron 空闲期 alembic upgrade head（失败自动写 ma_migration_audit + rollback）
```

---

## 7. 未来演进（PostgreSQL 桥接）

### 7.1 PostgreSQL 触发条件（参考行业最佳实践 ADR-0014 Phase 8e，**5 条任意 1 条成立才讨论**）

| # | 触发条件 | 测量方法 | 当前状态（2026-08-24） |
|---|---|---|---|
| PG-1 | **多机同时写** | ≥2 台独立 VPS 需要读写同一 DB | ❌（单机 mac mini） |
| PG-2 | **托管式 DB 需求** | 需要 AWS RDS / 阿里云 RDS / Supabase 做高可用 | ❌（无计划上云托管） |
| PG-3 | **写并发瓶颈真实出现** | SQLite 峰值 QPS > 50/s 且 连续 1h busy_timeout 重试率 > 20% | ❌（估计 < 1/s） |
| PG-4 | **PG 特性硬需求** | JSONB 索引查询 / BRIN 分区表 / pgAudit 合规审计 / RLS 行级安全 / PostGIS | ❌（无此类需求） |
| PG-5 | **单库体积 > 10GB** | `du -sh dreambuddy_core.db` | ❌（估计 < 0.5GB） |

### 7.2 PG 切换流程（DAL 协议已抽象 → ≈3 人日完成）

1. **实现层开发**：`implementations/postgres/` 下新增 6 个 `PgTradeRepo / PgPositionRepo / ...`，复用同一 Protocol 签名（SQL 方言差异集中在方言兼容层处理，见 §7.3）
2. **数据迁移工具**：`pgloader dreambuddy_core.db postgresql://user:pass@rds.aliyun.com:5432/dreambuddy`（pgloader 官方工具处理 SQLite→PG schema 差异 + 类型映射）
3. **双写验证**：DualWrite 再跑 3 天（与 P1 阶段完全一致流程），对账差异率 < 0.001% → 切读 → 2 周后断 SQLite 写
4. **运维切换**：backup.sh 从 sqlite3 `.backup` → `pg_dump` + WAL归档；integrity.sh 从 PRAGMA → pg_checksums + amcheck

### 7.3 SQL 方言兼容层（确保协议零改动）

```python
# implementations/_sql_compat.py（跨实现共享，避免每份实现散写 if/else）
class SqlCompat:
    @staticmethod
    def upsert_syntax(backend: str) -> str:  # 幂等写核心差异
        if backend == "sqlite":
            return "INSERT INTO {table} ({cols}) VALUES ({ph}) ON CONFLICT({pk}) DO UPDATE SET ..."
        if backend == "postgres":
            return "INSERT INTO {table} ({cols}) VALUES ({ph}) ON CONFLICT({pk}) DO UPDATE SET ..."
        raise ValueError(backend)
    # 其他 4 处方言差异：AUTOINCREMENT vs SERIAL、TEXT vs VARCHAR、FTS5 vs tsvector、WITHOUT ROWID vs 普通表
```

业务代码零感知：`get_trade_repo(backend="postgres")` 仅替换依赖注入配置。

---

## 8. 技术决策记录（ADR）

### ADR-19-001：选择 SQLite 统一库而非直接上 PostgreSQL
- **日期**：2026-08-24
- **背景**：你们系统出现数据碎片化但并发量极低（估算 < 1 QPS，峰值 < 10 QPS）
- **决策**：采用 SQLite（WAL 模式 + 外键约束）作为统一存储，协议层预留 PG 接口
- **理由**：
  ① Predict & Profit 团队行业共识："SQLite 对于单用户 VPS 交易 bot 是正确工具而非妥协"
  ② 运维成本对比：SQLite ≈ 0 / PostgreSQL ≈ 2 人日/月（pg_hba.conf / pgbouncer / autovacuum / 备份策略）
  ③ 切换成本 ≈ 3 人日（DAL 协议隔离），未来想迁随时可迁，不可逆成本为 0
- **反对理由**：SQLite 不支持多机写 + 真 MVCC
- **缓解措施**：§7 明确列出 PG 5 触发条件；DAL 层设计保证迁移无业务代码改动

### ADR-19-002：选择 Repository Protocol（ABC）而非 ORM
- **日期**：2026-08-24
- **决策**：手写 6 个 ABC 协议 + 原生 sqlite3 封装；不引入 SQLAlchemy / Peewee
- **理由**：① 项目偏好"代码驱动、精确控制查询"；② kg_store.py / storage.py 已熟练用原生 sqlite3，团队学习成本≈0；③ ORM 在 SQLite 查询路径（复合索引、WITHOUT ROWID 覆盖索引）的 SQL 生成不可控，反而需手写 raw SQL 绕开 ORM
- **反对理由**：未来迁 PG 需手写两类方言 SQL
- **缓解措施**：implementations/_sql_compat.py 方言兼容层集中 5 处差异点

### ADR-19-003：选 1 库 + 表前缀分区，不选 3 库隔离
- **日期**：2026-08-24
- **决策**：单一 `dreambuddy_core.db`，按 `tr_/po_/mm_/rs_/cv_/kg_/ma_` 前缀分区
- **理由**：① 备份/恢复/迁移极简（1 个文件）② 跨域 JOIN 可用（trade × risk × config 回撤分析）③ PRAGMA 一处配置
- **反对理由**：隔离性差，一库坏全停
- **缓解措施**：Cron 三件套每日 integrity_check + 双备份（WAL 快照 + 冷备 gzip）

### ADR-19-004：双写 2 周 + 断旧写延迟 2 周
- **日期**：2026-08-24
- **决策**：DualWrite 运行 ≥ 2 周；切读后继续双写 ≥ 14 天；才允许断旧写
- **理由**：① 加密货币周内模式：周末波动小、周一/四波动大，完整 2 周覆盖所有周期性场景 ② 符合黄金约束 GC4 旧文件保留 30 天的精神
- **反对理由**：多 2 周双写 I/O 开销
- **缓解措施**：DualWrite 装饰器 next_gen 写入走独立线程池（非阻塞主链路），I/O 开销 ≈ 5%

### ADR-19-005：CREATE TABLE 直接写目标 Schema + 幂等补列（经验 1040063）
- **日期**：2026-08-24
- **决策**：schema_init.py 中 TARGET_CREATE_TABLES = 最终 Schema；`_add_column_if_missing` helper 对旧库补列；绝不写"CREATE TABLE 半表再 ALTER"的双路径
- **理由**：经验 1040063 失败教训：半表 + ALTER 容易出现新库/旧库 schema 漂移（CREATE 默认值 vs ALTER 默认值不一致）
- **反对理由**：需要一次性设计完整 schema（压力在设计端）
- **缓解措施**：§1.4 YAGNI 控制字段数量；SCHEMA_DESIGN.md 发布前双人 review 每个字段的 NOT NULL / DEFAULT / 索引

---

> **文档更新承诺**：架构/机制变更 → 先改本文档 → 再改 SCHEMA_DESIGN → 再改代码 → 最后写 Alembic 迁移。严格对齐 §0.2 SSoT 层级优先级。
