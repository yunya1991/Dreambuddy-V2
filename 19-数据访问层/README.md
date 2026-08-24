# 19-数据访问层（DAL — Data Access Layer）

> **子系统定位**: DreamBuddy V2 统一数据底座（Schema 设计 + Repository 协议抽象 + SQLite WAL 统一库实现 + 零停机双写迁移）
> **阶段状态**: **v1.0 文档完成（TECHNICAL_DESIGN + SCHEMA_DESIGN + MIGRATION_PLAN）**，等待代码落地
> **正式架构代号**: 🐘 Aardvark（食蚁兽 = 勤劳 + 结构化吃数据 + 一舌精准搞定数据库全家桶）

---

## 🚀 启动必读（5 分钟入门）

| 你想做什么 | 直接跳转 |
|---|---|
| **想了解「为什么要做这个子系统？」** | 👉 [docs/TECHNICAL_DESIGN.md §1 背景与 4 大痛点量化](./docs/TECHNICAL_DESIGN.md#11-背景4-大痛点量化as-is2026-08-24-实锤) |
| **想了解「架构长什么样？（Repository 协议 / DualWrite / 6 Repo）」** | 👉 [docs/TECHNICAL_DESIGN.md §2 架构设计](./docs/TECHNICAL_DESIGN.md#2-架构设计) |
| **想看表结构（21 表 × 6 域 × 22 索引）** | 👉 [docs/SCHEMA_DESIGN.md 表域分区总览 + 逐表字段字典](./docs/SCHEMA_DESIGN.md#1-表域分区总览) |
| **要执行迁移 / 查看门禁 Checklist** | 👉 [docs/MIGRATION_PLAN.md 三批 SOP + 5 项切读门禁](./docs/MIGRATION_PLAN.md#31-门禁-checklist技术负责人--执行双人签) |
| **要找具体文件 / 运行入口 / 测试路径** | 👉 [docs/ENGINEERING_INDEX.md 子系统级工程索引](./docs/ENGINEERING_INDEX.md) |
| **要改代码 / Schema，看变更历史** | 👉 [docs/CHANGELOG.md 变更日志](./docs/CHANGELOG.md) |

---

## 🧭 文档导航金字塔（按权威级排序）

```
                    ┌─────────────────────────────┐
                    │  SSoT 根级（跨子系统）        │
                    │  ../ENGINEERING_INDEX.md v3.0│
                    └──────────────┬──────────────┘
                                   │
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐
  │ TECHNICAL_DESIGN │  │ SCHEMA_DESIGN    │  │  MIGRATION_PLAN      │  ← ★ 本系统 L1 权威三件套
  │ (架构/机制/原则) │  │ (表/字段/索引)   │  │  (SOP/门禁/回滚)     │
  └────────┬─────────┘  └────────┬─────────┘  └──────────┬───────────┘
           │                    │                       │
           └────────────────────┼───────────────────────┘
                                ▼
                    ┌──────────────────────────────┐
                    │ ENGINEERING_INDEX.md（文件级）│  ← L2 快速找文件
                    │ CHANGELOG.md（版本变更）      │
                    └──────────────────────────────┘
                                │
                                ▼
                    ┌──────────────────────────────┐
                    │    代码 inline docstring     │  ← L3 函数级
                    └──────────────────────────────┘
```

---

## 📌 当前阶段（2026-08-24）—— 文档冻结，等待批准代码落地

| 阶段 | 完成度 | 状态 |
|---|---|---|
| 📖 **文档阶段**（TECHNICAL_DESIGN + SCHEMA_DESIGN + MIGRATION_PLAN + 索引） | **100%** | ✅ 完成，PM 审阅中 |
| 🧱 **P0 代码基建**（unified_models + 6 Protocol + JsonLegacyImpl） | 0% | ⏸️ 待 PM 批准后启动（预计 2.5 人日） |
| 🗄️ **P1 统一库 + 迁移**（Schema Init + SqliteImpl + DualWrite + import 三批） | 0% | ⏸️ P0 通过后（预计 3.5 人日） |
| 🔄 **P2 生产切流 + 观察**（5 项门禁 + 切读/断旧写 + Alembic） | 0% | ⏸️ P1 通过后（预计 1.5 人日） |
| 🛡️ **P3 运维加固 + 归档**（Cron 三件套 + 历史归档 + 工程索引更新） | 0% | ⏸️ P2 通过后（预计 1.5 人日） |

**下一动作 = 你决定**：如果你对 3 份文档（TECHNICAL_DESIGN / SCHEMA_DESIGN / MIGRATION_PLAN）无异议，回复"批准启动 P0 代码落地"，我即按 TDD 启动代码开发（P0 阶段 TodoList 会自动生成）。

---

## 🎯 与兄弟子系统的职责边界（防止职责重叠）

| 子系统 | 方向 / 定位 | 与本子系统的关系 |
|---|---|---|
| **18-数据获取中心** | **外→内**：从外部世界（FRED/Etherscan/链上/新闻）拉原始数据 | 18 层 **必须**通过 `from dreambuddy_dal import get_market_macro_repo` **Repo 接口写宏观数据**；严禁 18 层直连 `dreambuddy_core.db`。 |
| **13-通用风控模块** | 风控引擎逻辑（PreTradeGate/PositionSizer/ExitEngine） | 风控引擎的状态持久化 **全部走** `get_risk_repo()`（rs_state / rs_cases）；不再写 risk_state.json |
| **11-易经推理系统** | A0-A9 决策链 + BCRM 模型 + 五计庙算 | 交易执行闭环的 TradeRecord 全部走 `get_trade_repo()`；宏观查询走 `get_market_macro_repo()`；CBR 知识图谱走 `get_kg_repo()` |
| **14-V15 经典马丁** | 马丁策略交易执行 | Trade / Position 持久化走 DAL（替换 v15_state.json + v15_trades.jsonl） |
| **1-ARCHITECTURE DreamOS** | 演化 / 检查点 / 知识图谱检查点 | KG 检查点统一由 `get_kg_repo()` 提供（替代 evolution.sqlite 独立文件） |

> **一句话记忆**：18 负责"吃进来（采集）"，19 负责"存起来 & 取出来（结构化存储访问）"。

---

## 🔧 环境变量速查（运维 / 迁移期高频）

| 环境变量 | 可选值 | 默认 | 作用 | 黄金约束关联 |
|---|---|---|---|---|
| `DB_BACKEND` | `json_legacy` / `dual_write` / `sqlite` / `postgres(未来)` | `json_legacy` | 依赖注入选择后端实现 | ✦ GC1：`json_legacy` = 10 秒回滚 |
| `READ_SOURCE` | `legacy` / `next_gen` | `legacy` | DualWrite 装饰器读来源切换（P2 门禁通过后才改 next_gen） | ✦ GC2：P1 期间永不切 next_gen |
| `DATA_DIR` | 任何绝对路径 | `./data`（相对当前工作目录） | `dreambuddy_core.db` + WAL/SHM + 备份 + 日志的根目录 | 显式优于隐式 |
| `DAL_AUDIT_DIFF_BLOCK` | 0/1 | **0**（永不阻断） | 1 = 双写差异时抛异常阻断主链路（仅测试环境用；生产严禁=1） | ✦ GC3：生产强制=0 |
| `DAL_SLOW_QUERY_MS` | 整数 ms | **200** | 慢查询阈值（WARN 日志打印 EXPLAIN） | 日志规范 §4.3 |

**Kill-Switch 最高优先级**（TECHNICAL_DESIGN §4.4）：若 `$DATA_DIR/DISABLE_DAL_NEW` 文件存在，忽略 `DB_BACKEND` 强制走 `json_legacy`。用于紧急时刻（如 SQLite corruption 未及时触发 integrity_check）。

---

## 📚 参考与依据

- 传统金融行业最佳实践对齐：
  - [NovaQuantLab] 量化交易系统架构白皮书 v2.3
  - [AltStreet Research] 自营团队从 JSON 到 SQLite 到 PG 演进路径 2026
  - [ADR-0014 Phase 8e] 日本 AI 资管平台 SQLite→PG 触发 5 条件
- 项目内既有实现参考（继承设计避免重复造轮子）：
  - [kg_store.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/kg_store.py#L61-L83) FTS5 + 双时态 Schema 设计
  - [storage.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/storage.py#L221-L500) 9 张 BCRM 表设计
  - [macro_data_fetcher.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/macro_data_fetcher.py#L122) 宏观 6 维度采集列
- 迁移经验教训（避免重蹈覆辙）：
  - Experience ID 698940：**绝不只修一张表补丁被追问其他表**；薄适配层保留旧导入符号
  - Experience ID 1040063：**CREATE TABLE 即最终 Schema**；统一 `_add_column_if_missing` helper 幂等补列

---

> **最后更新**: 2026-08-24（文档 v1.0 完成） · **下次更新**: P0 代码启动时追加状态至本节阶段表
