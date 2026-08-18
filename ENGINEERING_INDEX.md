# DreamBuddy-V2 工程索引

> **版本**: v3.0 | **更新日期**: 2026-07-31
> **定位**: 项目工程入口索引，提供运行入口、核心链路、配置落地点的快速导航
> **架构 SSoT**: ★ [1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md](./1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) v3.0 — 所有架构争议以此为准
> **文档管理**: [0-系统文档管理/INDEX.md](./0-系统文档管理/INDEX.md) v2.0 — 全项目文档导航中枢
> **维护原则**: 工程入口变更时更新本文件；架构变更更新 SSoT；文档变更更新 0-系统文档管理

---

## 0. 使用规则（强制）

### 0.1 变更流程

任何功能修改/扩展遵循以下流程：

1. **先阅读本文件** — 通过"工程索引(0.3)"与"系统索引(§3)"定位入口与既有排障口径
2. **再出方案** — 包含：影响范围、接口/配置变更、验收标准、回滚策略
3. **再改代码** — 小步提交，保持可回退
4. **验收合格后** — 在对应子系统文档追加变更日志（原因、改动点、验证方式、风险）

### 0.2 文档权威边界（SSoT 层级）

| 层级 | 文档 | 权威范围 | 冲突时的优先级 |
|------|------|----------|----------------|
| L0 | **1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md v3.0** | 架构唯一事实源（SSoT）：三层架构、硬约束、模块边界、技术债全景 | **最高（架构层面）** |
| L0 | 本文件（ENGINEERING_INDEX.md v3.0） | 全项目工程索引、运行入口、核心链路、配置落地点 | 最高（工程索引） |
| L0 | DEBT_INDEX.md | 全项目技术债务清单与修复计划 | 最高（债务层面） |
| L0 | 0-系统文档管理/ | 文档元层管理中枢（规范/地图/治理） | 最高（文档管理） |
| L0 | 0-系统文档管理/1-规范体系/DOC_STANDARD.md | 文档编写规范 | 最高（文档规范） |
| L1 | 各子系统 docs/TECHNICAL_DESIGN.md | 子系统技术设计 | 该子系统内最高 |
| L2 | 各子系统 docs/ENGINEERING_INDEX.md | 子系统文件级索引 | 该子系统内最高 |
| 📦 | TECHNICAL_DESIGN.md（根目录） | **已归档**（v3.0 LEGACY），被 SSoT 替代 | 无（历史参考） |

### 0.3 工程索引（必读入口）

#### 运行入口

| 进程 | 入口文件 | 调度方式 | 说明 |
|------|----------|----------|------|
| master_daemon | `ops/master_daemon.py` | launchd | 主守护进程，管理所有定时任务 |
| V15马丁策略 | `14-V15经典马丁策略/run.py trader` | master_daemon hourly | 16层入场+马丁加仓+超时离场 |
| 经典指标系统 | `10-经典指标系统/ml_trade_service.py` | launchd / master_daemon | Flask后端，信号→决策→执行→结算 |
| 前端监控面板 | `10-经典指标系统/frontend/` | Vite dev server | React+TypeScript，端口5173 |
| 易经推理系统 | `11-易经推理系统/scripts/memory_l4/polling_trader.py` | launchd | A0-A9决策链+L4记忆 |
| 资金管理API | `14-V15经典马丁策略/lib/capital_manager_engine.py api` | 独立启动 | HTTP API，端口8770 |

#### 核心链路入口（信号 → 决策 → 执行 → 结算）

| 链路环节 | 入口 | 所属系统 |
|----------|------|----------|
| V15信号生成 | `14-V15经典马丁策略/core/v15_signal.py` → `v15_decision()` | V15马丁 |
| V15交易执行 | `14-V15经典马丁策略/core/v15_trader.py` → `run_poll_cycle()` | V15马丁 |
| 经典指标信号 | `10-经典指标系统/ml_trade_service.py` → `/signals/v1` | 经典指标 |
| 经典指标决策 | `10-经典指标系统/ml_trade_service.py` → `_decision_entry_impl()` | 经典指标 |
| 三屏趋势过滤 | `12-三屏趋势系统/engine.py` → `ScreenEngine` | 三屏趋势 |
| 风控门禁 | `13-通用风控模块/core/pre_trade_gate.py` → `pre_trade_check()` | 通用风控 |
| 离场决策 | `13-通用风控模块/core/exit_engine.py` → `check_exit()` | 通用风控 |
| 经典离场系统 | `10-经典指标系统/classic_exit_system.py` → `ClassicExitSystem` | 经典指标 |
| 易经决策链 | `11-易经推理系统/scripts/memory_l4/polling_trader.py` | 易经推理 |

#### 配置与状态落地点（排障先看）

| 系统 | 配置文件 | 状态文件 |
|------|----------|----------|
| V15马丁 | `14-V15经典马丁策略/config/.env.common` → `.env.v15` | `14-V15经典马丁策略/data/v15_state.json` |
| 经典指标 | `10-经典指标系统/user_data/ml_config.json` | `10-经典指标系统/user_data/arena_state.json`, `tracker_state.json` |
| 三屏趋势 | `12-三屏趋势系统/core/config.py`（代码内配置） | 无独立状态文件 |
| 通用风控 | `13-通用风控模块/core/context.py`（代码内配置） | 无独立状态文件 |
| 易经推理 | `11-易经推理系统/.env` | `11-易经推理系统/artifacts/` 下JSON产物 |
| 全局 | `ops/state/` | master_daemon状态 |

#### 配置加载优先级

```
.env.v15ct (V15CT专属，历史兼容)
    ↓ 覆盖
.env.v15 (V15专属)
    ↓ 覆盖
.env.common (全局公共)
    ↓ 覆盖
代码默认值
```

#### 维护自检（改动后最少跑一遍）

```bash
# 语法自检
python -m py_compile <changed_file.py>

# V15马丁测试
cd 14-V15经典马丁策略 && python -m pytest tests/ -v

# 通用风控测试
cd 13-通用风控模块 && python -m pytest tests/ -v

# 经典指标前端lint
cd 10-经典指标系统/frontend && npm run lint
```

---

## 1. 项目概览

DreamBuddy-V2 是一个 AI 驱动的加密货币交易决策系统，采用多智能体架构，包含策略执行层、支撑服务层和基础设施层。

### 1.1 技术栈

| 层次 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 后端 | Python | 3.10+ | 策略引擎、风控、交易执行 |
| 前端 | Next.js + TypeScript | 18+ | 监控面板、管理界面 |
| 前端（经典指标） | React + Vite + TypeScript | 18+ | 交易监控Dashboard |
| 数据库 | Prisma + SQLite/PostgreSQL | - | 前端数据层 |
| 交易所 API | OKX / Hyperliquid | - | 实盘交易 |
| LLM 集成 | DeepSeek / Qwen / 飞书百炼 | - | AI决策、矛盾分析 |
| 进程管理 | launchd (macOS) | - | 定时任务调度 |
| ML 框架 | XGBoost / scikit-learn | - | 信号评分、模型预测 |

### 1.2 核心特性

- **多策略并行**: 经典马丁(14)、三屏趋势(12)、易经推理(11)、经典指标(10)独立运行
- **AI 驱动决策**: 基于 LLM 的矛盾分析、深度调研、策略推演
- **统一风控**: 13-通用风控模块提供pre-trade gate、仓位计算、离场决策
- **自动化运维**: master_daemon 管理所有定时任务
- **状态持久化**: 持仓状态、交易记录、优化结果持久化存储
- **贝叶斯优化**: V15策略参数自动寻优（8参数，最大化卡尔马比率）

---

## 2. 目录结构

### 2.1 全项目目录树

```
dreambuddy-v2/
│
├── 1-ARCHITECTURE/              # 架构设计 + Dream OS内核（元系统）
│   ├── dreamos/                 # Dream OS 操作系统内核（Python包）
│   │   ├── core/                # SACG四层内核（sense/arrange/compute/graph_store）
│   │   ├── registry/            # 节点注册表
│   │   ├── adapters/            # 适配器框架（Function/SKILL/API）
│   │   ├── nodes/               # 内置节点库（22个：A/C/F/G系列）
│   │   ├── evolution/           # 自我进化引擎
│   │   ├── budget/              # 预算管理
│   │   ├── apps/                # 应用层（TradingAgent/API/CLI）
│   │   ├── cli/                 # CLI工具集
│   │   ├── shared/              # 共享基础组件
│   │   ├── config/              # 配置
│   │   ├── docs/                # 系统文档（ENGINEERING_INDEX + TECHNICAL_DESIGN）
│   │   └── dreamos-tests/       # 测试套件（5个测试文件）
│   ├── dreamos-nodes/           # Dream OS 扩展节点
│   ├── dreamos-tests/           # Dream OS 测试（兄弟目录）
│   ├── registry/                # 模块注册表
│   ├── FAQ/                     # 常见问题（FAQ.md, FAQ_FULL.md）
│   ├── 中台设计/                 # 产品中台、网关中台设计
│   ├── 前端设计/                 # 前端架构、UI规范、渠道设计（17个.md）
│   ├── 工作索引/                 # 文件定位、技能索引、工具映射
│   ├── skills/                  # 架构级技能定义
│   ├── SYSTEM_ARCHITECTURE_OVERVIEW.md
│   ├── WORKBUDDY_OS_MODULAR_ARCHITECTURE.md
│   ├── SUPERPOWERS_INTEGRATION_UPGRADE.md
│   └── ...
│
├── 2-GOVERNANCE/                # 治理合规系统
│   ├── GOVERNANCE_CHARTER.md    # 治理章程
│   ├── GOVERNANCE_SYSTEM.md     # 治理体系
│   ├── COMPLIANCE_RULES.md      # 合规规则
│   └── AUDIT_LOGS.md            # 审计日志
│
├── 2-KNOWLEDGE/                 # 知识库系统（7个INDEX.md）
│   ├── 0-SCHEMA/                # 知识模式定义
│   ├── 1-TRADING/               # 交易知识（A链调度、V9马丁、三屏、信号、风控）
│   ├── 2-TECHNICAL/             # 技术知识（Hermes、数据管道、部署、飞书）
│   ├── 3-THEORY/                # 理论知识（大师谱系、矛盾分析、第一性原理）
│   ├── 4-OPERATIONS/            # 运营知识（OKR、门禁、审批、索引体系）
│   └── 5-METHODOLOGY/           # 方法论（调研、执行、规划、回测、知识管理）
│
├── 3-CHAIN-DEVELOPMENT/         # 链开发协议（21个.md）
│   ├── 1-RESEARCH/              # 调研链：D1调查→D2分析→D3推演→D4规格
│   ├── 2-PLANNING/              # 规划链：Z1扫描→Z2边界→Z3路径→Z4验收
│   ├── 3-EXECUTION/             # 执行链：E1执行→E2测试→E3部署
│   ├── 4-PROTOCOL/              # 协议规范
│   └── 5-GATES/                 # 门禁（会话门禁、链阶段门禁、集成门禁）
│
├── 3-EVOLUTION/                 # 进化引擎（TypeScript，无文档）
│   ├── evolution-orchestrator.ts
│   ├── evolution-engine.ts
│   └── ...
│
├── 3-FRONTEND/                  # 前端系统（旧版文档）
│   └── FRONTEND_SYSTEM.md
│
├── 3.1-FRONTEND/                # 前端系统（新版 Next.js）
│   ├── src/app/                 # Next.js App Router
│   ├── src/lib/                 # 意图路由、知识RAG、SSE、任务管理
│   ├── src/stores/              # 状态管理（auth, ui）
│   └── prisma/schema.prisma     # 数据库Schema
│
├── 4-MEMORY/                    # 记忆系统
│   └── MEMORY_SYSTEM.md         # 四级记忆架构设计（L1-L4）
│
├── 5-BUSINESS/                  # 业务管理系统
│   └── BUSINESS_SYSTEM.md
│
├── 6-TRADING/                   # 交易研究系统（132个.md）
│   ├── scripts/                 # 交易脚本（A1调研、A5守卫、回测、DeepSeek分析等）
│   ├── bridge/                  # 交易桥接（OKX API封装、实时API）
│   ├── docs/                    # 技术文档（架构设计v2.0、桥接架构、技能注册等）
│   ├── skills/                  # A0-A9技能集（76个.md，含SKILL.md和INTEGRATION.md）
│   ├── sessions/                # 交易会话记录
│   ├── baselines/               # 策略基线
│   └── knowledge/               # 交易知识
│
├── 6-图结构上下文压缩/           # 图结构压缩引擎（TypeScript）
│   ├── planner/                 # 链规划器、技能注册、模块注册、交叉验证
│   ├── compressor.ts            # 上下文压缩器
│   ├── graph-state.ts           # 图状态管理
│   ├── intent-gateway.ts        # 意图网关
│   └── ...
│
├── 7-产物中台/                   # 产物管理与投递中台
│   ├── docs/                    # 工程索引、FAQ、superpowers规格/计划
│   ├── 系统研究索引体系/          # Next.js应用（研究索引、会议、组织架构）
│   └── progress_auto_update.py  # 进度自动更新
│
├── 10-经典指标系统/              # 经典指标交易系统（★成熟文档）
│   ├── ml_trade_service.py      # 主服务（Flask，信号→决策→执行→结算）
│   ├── classic_exit_system.py   # 经典离场系统
│   ├── carry_service.py         # 套利策略服务
│   ├── frontend/                # React监控面板（端口5173）
│   ├── agent_client/            # Tauri桌面客户端
│   ├── talib/                   # TA-Lib技术指标封装
│   ├── models/                  # ML模型（XGBoost委员会、ATR乘数）
│   ├── ops/                     # 运维部署（launchd/systemd/cron/nanoclaw）
│   ├── skills/                  # 技能目录（catalog/contracts/playbooks/routing）
│   ├── tools/                   # 工具脚本（参数优化、回测验证、环境检查）
│   ├── user_data/               # 用户数据与配置（20+config_*.json）
│   ├── 技术文档.md               # 旧版技术文档（12414行，DD-006 待归档）
│   ├── 系统运营技术文档.md        # 运营手册（310行）
│   ├── 基本面分析文档.md          # 基本面分析（1994行）
│   └── ...
│
├── 11-易经推理系统/              # 易经推理交易系统（最大子系统）
│   ├── docs/                    # 技术文档（TECHNICAL_DESIGN.md, architecture.md）
│   ├── scripts/                 # 核心脚本
│   │   ├── ci/                  # CI脚本（16个：架构同步、分支生命周期、进化门禁等）
│   │   ├── memory_l4/           # L4记忆引擎（bcrm/19个, qmm/13个, 顶层35个脚本）
│   │   └── trading_demo/        # 交易Demo（HTTP服务器、Redis流消费者）
│   ├── constraints/             # 约束规范（constitution, faq, qmm, workflows-spec）
│   ├── skills/                  # 技能定义（0-CORE, 1-TRADE, 3-SUPPORT, 4-GENERIC）
│   ├── tests/                   # 测试套件（60+测试文件）
│   ├── workflows/               # 工作流（evolution, knowledge, memory, trading）
│   ├── artifacts/               # 产物（evolution, knowledge, memory, trading）
│   └── .github/workflows/       # CI工作流（6个.yml）
│
├── 12-三屏趋势系统/              # 三屏趋势交易系统
│   ├── core/                    # 核心（config, dynamic_weights, fusion, indicators, trend_consistency）
│   ├── data/                    # 数据层（market_data, fundamental_data）
│   ├── docs/                    # 文档（ENGINEERING_INDEX.md, TECHNICAL_DESIGN.md）
│   ├── tests/                   # 测试
│   ├── engine.py                # 主引擎
│   ├── classic_bridge.py        # 经典指标桥接
│   ├── exit_integration.py      # 退出集成
│   └── signals.py               # 信号生成
│
├── 13-通用风控模块/              # 通用风控引擎
│   ├── core/                    # 核心（engine, exit_engine, pre_trade_gate, position_sizer, l1_assessor, ml_model, alert, context, registry）
│   ├── rules/                   # 规则（exit_rules, gate_rules, position_rules）
│   ├── docs/                    # 文档（ENGINEERING_INDEX.md, TECHNICAL_DESIGN.md）
│   └── tests/                   # 测试（test_risk_engine, test_l1_ml_alert）
│
├── 14-V15经典马丁策略/           # V15经典马丁策略（★子系统文档标杆）
│   ├── run.py                   # 统一入口（signal/backtest/trader/capital_engine/test/config）
│   ├── config/                  # 配置（.env.common, .env.v15, .env.v15ct）
│   ├── core/                    # 核心策略（v15_signal, v15_trader, v15_backtest）
│   ├── lib/                     # 工具层（config_loader, okx_client, market_data, strategy_params, capital_manager, capital_manager_engine, bayesian_optimizer, symbol_mapper）
│   ├── tests/                   # 测试套件（5个测试文件）
│   ├── data/                    # 数据（v15_state.json, backtest_cache/, okx_client/）
│   ├── docs/                    # 文档（ENGINEERING_INDEX v4.0, TECHNICAL_DESIGN v4.0, API_SPEC v3.0）
│   └── com.dreambuddy.v15_trader.plist  # launchd配置
│
├── 15-监控告警系统/              # 统一监控告警系统
│   ├── monitor_core.py          # 监控核心（UnifiedMonitor + MonitorAdapter）
│   ├── feishu_alert.py          # 飞书告警模块
│   ├── scheduler.py             # 统一调度器
│   ├── adapters/                # 系统适配器（Yijing/V15/Screen/AgentA/AgentB）
│   ├── config/                  # 配置（monitor_config.json）
│   ├── start_monitor.sh         # 启动脚本
│   └── README.md                # 系统文档
│
├── 16-调控系统/                  # 调控系统（早期阶段）
│   ├── core/                    # 核心（a1_research_adapter, a3_strategy_adapter, skill_engine, unified_position_query）
│   ├── scripts/                 # 脚本（phase0_exit_evaluator）
│   ├── docs/                    # 文档（ENGINEERING_INDEX.md, TECHNICAL_DESIGN.md）
│   ├── artifacts/               # 产物（exit-evaluations/）
│   └── tests/                   # 测试（空，待实现）
│
├── ops/                         # 运维工具
│   ├── master_daemon.py         # 主守护进程
│   ├── launchd_manage.py        # launchd管理
│   └── state/                   # 状态目录
│
├── scripts/                     # 辅助脚本
│   ├── sync_artifact.py         # 产物同步
│   ├── write_health_status.py   # 健康状态写入
│   └── step_controller.py       # 步骤控制器
│
├── .github/workflows/           # GitHub Actions
│   ├── agent-a-actions.yml
│   ├── agent-b-trading.yml
│   └── drift-guard.yml
│
├── ENGINEERING_INDEX.md         # 本文件 — 工程索引（SSoT）
├── TECHNICAL_DESIGN.md          # 技术架构文档
├── DEBT_INDEX.md                # 技术债务索引
├── 0-系统文档管理/              # 文档元层管理中枢（规范/地图/治理）
├── PROJECT_DOC_STANDARD.md      # 已迁移 → 0-系统文档管理/1-规范体系/DOC_STANDARD.md
├── README.md
└── CONTRIBUTING.md
```

---

## 3. 系统索引（文件级）

### 3.1 交易策略模块

#### 3.1.1 14-V15经典马丁策略 ★文档标杆

| 属性 | 值 |
|------|-----|
| 目录 | `14-V15经典马丁策略/` |
| 策略类型 | 马丁格尔 + 纯技术分析 + 智能资金管理 |
| 交易方向 | 只做多 |
| 交易周期 | 4H |
| 监控币种 | 34个 |
| 数据来源 | OKX API |
| 文档状态 | ✅ 完整（ENGINEERING_INDEX v4.0 + TECHNICAL_DESIGN v4.0 + API_SPEC v3.0） |

**文件清单：**

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `run.py` | 6 | 统一入口 | `main()` — signal/backtest/trader/capital_engine/test/config |
| `core/v15_signal.py` | ~25 | 信号引擎：16项指标+16层决策 | `v15_decision()`, `calc_fibonacci()`, `calc_bollinger_bands()`, `calc_macd()`, `calc_adx()`, `calc_pivot_points()`, `calc_obv()`, `calc_supertrend()`, `calc_keltner_channel()`, `calc_stochrsi()`, `calc_vortex()`, `calc_tema()`, `calc_golden_cross()`, `calc_ema_align()` |
| `core/v15_trader.py` | ~20 | 自动交易器 | `run_poll_cycle()`, `execute_open_position()`, `execute_addon()`, `check_take_profit()`, `check_time_exit()`, `_get_dynamic_params()` |
| `core/v15_backtest.py` | ~25 | 回测引擎 | `run_backtest()`, `print_report()`, `get_ma200_stop_loss()`, `get_vol_adjusted_params()` |
| `lib/config_loader.py` | 8 | 配置加载（include语法） | `load_config()`, `get_config()`, `get_config_float()`, `get_config_int()`, `get_config_list()`, `get_config_bool()` |
| `lib/okx_client.py` | — | OKX REST客户端 | `OKXSimulatedClient` — `place_order()`, `get_positions()`, `get_balance()`, `get_kline()` |
| `lib/market_data.py` | 7 | K线获取+基础指标 | `fetch_candles()`, `calc_sma()`, `calc_ema()`, `calc_rsi()` |
| `lib/strategy_params.py` | ~15 | 动态参数+Elder-ray趋势 | `get_dynamic_stop_loss()`, `get_vol_adjusted_params()`, `calc_elder_ray()`, `calc_daily_ma200()`, `check_trend_filter()` |
| `lib/capital_manager.py` | ~12 | 资金管理 | `calculate_per_coin_allocation()`, `calculate_capital_allocation()`, `get_account_balance()`, `get_current_positions()` |
| `lib/capital_manager_engine.py` | ~15 | 资金管理引擎 | `CapitalManagerEngine` — `run_monthly()`, `run_optimization()`, `check_open_permission()` |
| `lib/bayesian_optimizer.py` | ~15 | 贝叶斯参数优化（8参数） | `V15CapitalOptimizer` — `iterate_optimize()`, `_objective()`, `_run_backtest_evaluation()` |
| `lib/symbol_mapper.py` | — | 币种映射 | `to_swap()`, `to_spot()` |

**配置文件：**

| 文件 | 用途 | 关键参数 |
|------|------|----------|
| `config/.env.common` | 公共配置 | OKX密钥、LEVERAGE=5、TOTAL_BUDGET |
| `config/.env.v15` | V15专属 | V15_COINS(34)、V15_POLL_INTERVAL=3600、V15_BASE_POSITION_PCT=0.22 |
| `config/.env.v15ct` | V15CT历史兼容 | 逐步废弃中 |

**文档入口：**

| 文档 | 路径 |
|------|------|
| 工程索引 | `14-V15经典马丁策略/docs/ENGINEERING_INDEX.md` |
| 技术设计 | `14-V15经典马丁策略/docs/TECHNICAL_DESIGN.md` |
| API规格 | `14-V15经典马丁策略/docs/API_SPEC.md` |
| 用户文档 | `14-V15经典马丁策略/README.md` |

---

#### 3.1.2 10-经典指标系统 ★成熟文档

| 属性 | 值 |
|------|-----|
| 目录 | `10-经典指标系统/` |
| 核心服务 | Flask后端（ml_trade_service.py） |
| 服务端口 | 8092（后端）、5173（前端） |
| 文档状态 | ✅ 成熟（docs/TECHNICAL_DESIGN.md 8772行 + 技术文档.md 12414行 + 运营文档310行） |

**核心文件：**

| 文件 | 职责 | 关键入口 |
|------|------|----------|
| `ml_trade_service.py` | 主交易服务（Flask） | `/signals/v1`, `/decision/entry`, `/tracker/update`, `/config/get`, `/config/set` |
| `classic_exit_system.py` | 经典离场系统 | `ClassicExitSystem` — CLOSE/REDUCE/RAISE_TP/HOLD |
| `carry_service.py` | 套利策略服务 | Carry Trade执行 |
| `talib/__init__.py` | TA-Lib封装 | 技术指标计算入口 |
| `frontend/src/App.tsx` | 前端路由入口 | 页面路由配置 |
| `frontend/src/lib/api.ts` | 前端API层 | 后端接口调用 |

**文档体系（SSoT）：**

| 文档 | 行数 | 权威范围 |
|------|------|----------|
| `技术文档.md` | 12414 | 生产交易系统行为边界与排障（历史材料） |
| `docs/TECHNICAL_DESIGN.md` | 8772 | 技术设计文档（由技术文档2.0.md迁入，当前权威） |
| `系统运营技术文档.md` | 310 | 运营闭环、监控、故障处置 |
| `交易AI Agent 技术文档2.0.md` | 268 | AI Agent/沙箱/门禁/审计边界 |
| `skills/SKILLS_技术文档规范.md` | 184 | Skills能力契约、R0-R3分级标准 |
| `基本面分析文档.md` | 1994 | 基本面分析体系 |
| `新闻分析技能技术文档.md` | 438 | 新闻分析技能 |
| `策略开发规范（基于SimpleStrategy）.md` | 170 | 策略开发规范 |

**运维部署：**

| 部署项 | 路径 | 说明 |
|--------|------|------|
| launchd配置 | `ops/launchd/` | com.ft.ml_trade_service.prod.plist 等 |
| systemd配置 | `ops/systemd/` | hl-deriv, okx-sr, okx-ingest 等 |
| cron配置 | `ops/cron.d/` | 参数优化、基本面同步 |
| nanoclaw | `ops/nanoclaw/` | 技能调度框架 |

---

#### 3.1.3 11-易经推理系统

| 属性 | 值 |
|------|-----|
| 目录 | `11-易经推理系统/` |
| 核心引擎 | BCRM 2.0（辩证ML，实盘主力）+ BCRM 1.0（矛盾力学，Fallback）+ QMM（量化记忆） + 逐仓风控（isolated） |
| 决策模型 | 易经八卦 + 辩证法 + A0-A9决策链 + 三引擎协同 |
| 记忆系统 | L4四级记忆架构（M0→M5全链路） |
| 自进化 | 三层反思闭环（A8/做梦部/联网）+ 约束升级通道 |
| CI/CD | 16个CI脚本 + GitHub Actions（6个workflow） |
| 约束层 | 30+约束文档 + 版本化发布 |
| 技能体系 | 5大类40+技能（0-CORE/1-TRADE/2-INTELLIGENCE/3-SUPPORT/4-GENERIC） |
| 文档状态 | ✅ 完整（ENGINEERING_INDEX v2.1 + TECHNICAL_DESIGN v2.1） |
| 基线综合夏普 | 7.45（BTC/ETH/SOL/UNI 4币种组合） |

**核心代码结构：**

| 目录 | 文件数 | 职责 |
|------|--------|------|
| `scripts/memory_l4/bcrm/` | 19 | BCRM 1.0矛盾力学推理引擎（yijing_engine, bagua_engine, liangyi_engine, force_engine, scale_engine, walk_forward） |
| `scripts/memory_l4/bcrm2/` | ~25 | BCRM 2.0辩证ML量化引擎（dialectical_ml_engine, bagua_feature_engine, market_regime, 11个特征模块） |
| `scripts/memory_l4/qmm/` | 13 | QMM量化记忆模型（triple_screen, mrd, uncertainty, drift, xgb_predictor, gate） |
| `scripts/memory_l4/` 顶层 | ~38 | 核心脚本（pipeline, polling_trader, bcrm2_adapter, self_evolution_engine, okx_simulated, classic_exit_system, confidence_optimization, shared_memory_bus） |
| `scripts/ci/` | 16 | CI脚本（架构同步、分支生命周期、进化门禁、安全合并、约束管理） |
| `constraints/` | ~30 | 约束规范（constitution, system-index, workflows-spec, qmm, faq, releases） |
| `skills/` | 40+ | 技能库（0-CORE/1-TRADE/2-INTELLIGENCE/3-SUPPORT） |
| `tests/` | 60+ | 测试套件（CI测试、记忆系统测试、交易协议测试、QMM测试、E2E测试、压力测试） |

**文档入口（按优先级）：**

| 文档 | 路径 | 说明 |
|------|------|------|
| ✅ 工程索引 | `docs/ENGINEERING_INDEX.md` | 系统级工程索引（SSoT），11章节 |
| ✅ 技术设计 | `docs/TECHNICAL_DESIGN.md` | 系统级技术设计，16章节（含BCRM 2.0深度+逐仓风控） |
| 架构基线 | `constraints/system-index/engineering-architecture.md` | 约束层架构基线 |
| 系统概览 | `README.md` | 项目概览与快速开始 |
| 架构简述 | `docs/architecture.md` | 系统架构概述 |

---

#### 3.1.4 12-三屏趋势系统

| 属性 | 值 |
|------|-----|
| 目录 | `12-三屏趋势系统/` |
| 理论基础 | Alexander Elder 三重屏幕交易系统 |
| 文档状态 | ✅ 完整 |

**文件清单：**

| 文件 | 职责 | 关键函数 |
|------|------|----------|
| `engine.py` | 主引擎 | `ScreenEngine` |
| `core/trend_consistency.py` | 趋势一致性判断 | 三屏趋势核心逻辑 |
| `core/fusion.py` | 信号融合 | 多信号融合算法 |
| `core/dynamic_weights.py` | 动态权重 | 基于趋势强度的权重调整 |
| `core/indicators.py` | 指标计算 | MA、EMA、MACD等 |
| `core/config.py` | 配置管理 | 配置加载与验证 |
| `data/market_data.py` | 市场数据 | 行情获取与缓存 |
| `classic_bridge.py` | 经典指标桥接 | 与10-经典指标系统的接口 |
| `exit_integration.py` | 退出集成 | 退出系统集成点 |
| `signals.py` | 信号生成 | 信号输出 |

---

#### 3.1.5 16-调控系统

| 属性 | 值 |
|------|-----|
| 目录 | `16-调控系统/` |
| 状态 | 早期阶段 |
| 文档状态 | ✅ 基本完整（文档已有，代码待实现） |

**文件清单：**

| 文件 | 职责 |
|------|------|
| `core/a1_research_adapter.py` | A1调研适配器 |
| `core/a3_strategy_adapter.py` | A3策略适配器 |
| `core/skill_engine.py` | 技能引擎 |
| `core/unified_position_query.py` | 统一持仓查询 |
| `scripts/phase0_exit_evaluator.py` | Phase0退出评估器 |

---

### 3.2 支撑系统

#### 3.2.1 13-通用风控模块

| 属性 | 值 |
|------|-----|
| 目录 | `13-通用风控模块/` |
| 风控规则 | 17条（gate_rules + position_rules + exit_rules） |
| 测试 | 51个测试通过 |
| 文档状态 | ✅ 完整 |
| ⚠️ 接入状态 | 未接入任何交易策略 |

**文件清单：**

| 文件 | 职责 | 关键函数/类 |
|------|------|-------------|
| `core/engine.py` | 风控引擎入口 | `RiskEngine` |
| `core/pre_trade_gate.py` | 事前门禁 | `pre_trade_check()` |
| `core/exit_engine.py` | 离场决策 | `check_exit()` |
| `core/position_sizer.py` | 仓位计算 | 仓位大小计算 |
| `core/l1_assessor.py` | L1风险评估 | `assess_value_risk()` |
| `core/ml_model.py` | ML模型 | 机器学习风控模型 |
| `core/alert.py` | 告警 | 飞书告警发送 |
| `core/context.py` | 风控上下文 | 风控规则参数 |
| `core/registry.py` | 规则注册 | 规则注册管理 |
| `rules/gate_rules.py` | 门禁规则 | 事前检查规则集 |
| `rules/position_rules.py` | 仓位规则 | 仓位计算规则集 |
| `rules/exit_rules.py` | 离场规则 | 离场决策规则集 |

---

#### 3.2.2 架构与知识系统

| 系统 | 目录 | 文档数 | 核心文档 |
|------|------|--------|----------|
| **Dream OS 内核** | `1-ARCHITECTURE/dreamos/` | 2篇系统文档 + ~45个代码文件 | dreamos/docs/ENGINEERING_INDEX.md, dreamos/docs/TECHNICAL_DESIGN.md |
| 架构设计 | `1-ARCHITECTURE/` | 41+ | SYSTEM_ARCHITECTURE_OVERVIEW.md, WORKBUDDY_OS_MODULAR_ARCHITECTURE.md |
| 治理合规 | `2-GOVERNANCE/` | 5 | GOVERNANCE_CHARTER.md, COMPLIANCE_RULES.md |
| 知识库 | `2-KNOWLEDGE/` | 7个INDEX | 1-TRADING/, 2-TECHNICAL/, 3-THEORY/, 5-METHODOLOGY/ |
| 链开发协议 | `3-CHAIN-DEVELOPMENT/` | 21 | D1-D4调研链, Z1-Z4规划链, E1-E3执行链 |
| 记忆系统 | `4-MEMORY/` | 2 | MEMORY_SYSTEM.md（L1-L4四级架构） |
| 业务管理 | `5-BUSINESS/` | 2 | BUSINESS_SYSTEM.md |
| 交易研究 | `6-TRADING/` | 132 | A0-A9技能集, 架构设计v2.0, 桥接架构 |
| 图结构压缩 | `6-图结构上下文压缩/` | 5 | SPEC.md, TECHNICAL-DOC.md, IMPLEMENTATION.md |
| 产物中台 | `7-产物中台/` | 10 | ENGINEERING_INDEX.md, superpowers规格 |

---

#### 3.2.3 前端系统

| 系统 | 目录 | 技术栈 | 说明 |
|------|------|--------|------|
| 新版前端 | `3.1-FRONTEND/` | Next.js + Prisma | 用户管理、意图路由、知识RAG、SSE |
| 经典指标前端 | `10-经典指标系统/frontend/` | React + Vite | 交易监控Dashboard，端口5173 |
| 经典指标客户端 | `10-经典指标系统/agent_client/` | Tauri + React | 桌面客户端 |
| 旧版前端文档 | `3-FRONTEND/` | — | FRONTEND_SYSTEM.md（参考） |

---

### 3.3 基础设施

| 组件 | 入口 | 职责 |
|------|------|------|
| **Dream OS 内核** | `1-ARCHITECTURE/dreamos/` | 操作系统内核（SACG四层+节点+适配器+进化） |
| master_daemon | `ops/master_daemon.py` | 主守护进程，管理V15马丁等定时任务 |
| launchd管理 | `ops/launchd_manage.py` | launchd服务安装/卸载/状态 |
| 产物同步 | `scripts/sync_artifact.py` | 产物同步到中台 |
| 健康状态 | `scripts/write_health_status.py` | 健康状态写入 |
| 步骤控制 | `scripts/step_controller.py` | 工作流步骤控制 |
| 交易桥接 | `6-TRADING/bridge/run_server.py` | OKX API封装、实时数据服务 |

---

## 4. 系统间依赖关系

### 4.1 交易策略层依赖

```
14-V15经典马丁策略
    ├── 12-三屏趋势系统          ← 趋势过滤（both_bear + MA104）
    ├── 10-经典指标系统           ← 超时离场切换（ClassicExitSystem）
    └── OKX API（自有客户端）

10-经典指标系统
    ├── 12-三屏趋势系统          ← 趋势信号
    └── OKX API / Hyperliquid

11-易经推理系统
    ├── 4-MEMORY/               ← L4记忆引擎
    └── OKX API（自有客户端）

12-三屏趋势系统
    └── 10-经典指标系统           ← 离场集成

13-通用风控模块（待接入）
    └── 应接入: V15马丁, 经典指标, 三屏趋势, 易经推理

16-调控系统（待实现）
    └── 应接入: 所有交易策略（统一调控）
```

### 4.2 数据流

```
数据源
├── OKX API ──→ 14-V15马丁（lib/okx_client.py）
│            ──→ 10-经典指标（ml_trade_service.py）
│            ──→ 11-易经推理（scripts/memory_l4/okx_simulated.py）
│
├── Hyperliquid ──→ 10-经典指标（Carry Trade）
│
├── 新闻数据 ──→ 10-经典指标（nanoclaw/news_crawler）
│
└── 交易数据 ──→ 6-TRADING/bridge/
              ──→ 11-易经推理/

交易信号流
V15信号(16层) ──→ 趋势过滤 ──→ 资金管理 ──→ 风控检查 ──→ 下单执行
经典指标信号 ──→ 决策Gate ──→ Arena投票 ──→ 执行 ──→ 结算
易经推理 ──→ A0-A9决策链 ──→ L4记忆 ──→ 执行
```

### 4.3 风控数据流

```
交易信号 → 13-通用风控/pre_trade_gate.py → 门禁通过/拒绝
              ↓
         position_sizer.py → 仓位计算
              ↓
         exit_engine.py → 离场决策（CLOSE/REDUCE/RAISE_TP/HOLD）
              ↓
         alert.py → 飞书告警
```

> ⚠️ 当前风控数据流为设计态，13-通用风控模块尚未接入任何策略

---

## 5. 关键接口速查

### 5.1 交易执行接口

| 模块 | 文件 | 核心函数/类 | 说明 |
|------|------|-------------|------|
| V15马丁 | `14-V15经典马丁策略/core/v15_trader.py` | `run_poll_cycle()` | 主轮询循环 |
| V15马丁 | `14-V15经典马丁策略/core/v15_signal.py` | `v15_decision()` | 16层信号决策 |
| V15马丁 | `14-V15经典马丁策略/lib/capital_manager.py` | `calculate_per_coin_allocation()` | 资金分配 |
| 经典指标 | `10-经典指标系统/ml_trade_service.py` | `/signals/v1` | 信号接收 |
| 经典指标 | `10-经典指标系统/ml_trade_service.py` | `/decision/entry` | 决策入口 |
| 经典指标 | `10-经典指标系统/ml_trade_service.py` | `/tracker/update` | 成交回传 |
| 三屏趋势 | `12-三屏趋势系统/engine.py` | `ScreenEngine` | 趋势引擎 |
| 易经推理 | `11-易经推理系统/scripts/memory_l4/polling_trader.py` | — | 轮询交易 |

### 5.2 风控接口

| 模块 | 文件 | 核心函数/类 | 说明 |
|------|------|-------------|------|
| 通用风控 | `13-通用风控模块/core/engine.py` | `RiskEngine` | 风控引擎入口 |
| 通用风控 | `13-通用风控模块/core/pre_trade_gate.py` | `pre_trade_check()` | 事前检查 |
| 通用风控 | `13-通用风控模块/core/exit_engine.py` | `check_exit()` | 离场决策 |
| 通用风控 | `13-通用风控模块/core/l1_assessor.py` | `assess_value_risk()` | L1评估 |
| 经典离场 | `10-经典指标系统/classic_exit_system.py` | `ClassicExitSystem` | 离场系统 |

### 5.3 数据接口

| 模块 | 文件 | 核心函数/类 | 说明 |
|------|------|-------------|------|
| OKX客户端 | `14-V15经典马丁策略/lib/okx_client.py` | `OKXSimulatedClient` | OKX API封装 |
| 市场数据 | `14-V15经典马丁策略/lib/market_data.py` | `fetch_candles()` | K线获取 |
| 交易桥接 | `6-TRADING/bridge/run_server.py` | — | 实时数据服务 |
| 前端API | `10-经典指标系统/frontend/src/lib/api.ts` | — | 前端API调用层 |

---

## 6. 配置管理

### 6.1 配置文件位置

| 系统 | 配置文件 | 关键配置项 |
|------|----------|------------|
| 全局 | `14-V15经典马丁策略/config/.env.common` | TOTAL_BUDGET, LEVERAGE=5, OKX密钥 |
| V15马丁 | `14-V15经典马丁策略/config/.env.v15` | V15_COINS(34), V15_POLL_INTERVAL=3600, V15_BASE_POSITION_PCT=0.22 |
| V15CT | `14-V15经典马丁策略/config/.env.v15ct` | 历史兼容，逐步废弃 |
| 经典指标 | `10-经典指标系统/user_data/ml_config.json` | 策略配置、资金参数 |
| 经典指标 | `10-经典指标系统/user_data/config.json` | Freqtrade配置 |
| 三屏趋势 | `12-三屏趋势系统/core/config.py` | 代码内配置 |
| 通用风控 | `13-通用风控模块/core/context.py` | 代码内配置 |
| 易经推理 | `11-易经推理系统/.env` | 环境变量配置 |
| 前端 | `3.1-FRONTEND/.env` | 前端环境变量 |

### 6.2 环境变量优先级

```
.env.v15ct (V15CT专属，历史兼容)
    ↓ 覆盖
.env.v15 (V15专属)
    ↓ 覆盖
.env.common (全局公共)
    ↓ 覆盖
代码默认值
```

---

## 7. 部署与运维

### 7.1 进程管理

| 进程 | 入口文件 | 调度方式 | 说明 |
|------|----------|----------|------|
| master_daemon | `ops/master_daemon.py` | launchd | 主守护进程 |
| V15马丁 | `14-V15经典马丁策略/run.py trader` | master_daemon hourly | 16层入场+马丁加仓 |
| 经典指标 | `10-经典指标系统/ml_trade_service.py` | launchd | Flask后端，端口8092 |
| 经典指标前端 | `10-经典指标系统/frontend/` | Vite dev server | 端口5173 |
| 易经推理 | `11-易经推理系统/scripts/memory_l4/polling_trader.py` | launchd | A0-A9决策链 |
| 资金管理API | `14-V15经典马丁策略/lib/capital_manager_engine.py api` | 独立启动 | 端口8770 |

### 7.2 launchd 配置文件

| 配置文件 | 位置 | 说明 |
|----------|------|------|
| com.dreambuddy.v15_trader.plist | `14-V15经典马丁策略/` | V15马丁策略 |
| com.dreambuddy.yijing_trading.plist | `11-易经推理系统/` | 易经推理交易 |
| com.dreambuddy.yijing_monitor.plist | `11-易经推理系统/` | 易经推理监控 |
| com.ft.ml_trade_service.prod.plist | `10-经典指标系统/ops/launchd/` | 经典指标生产 |
| com.ft.dashboard.plist | `10-经典指标系统/ops/launchd/` | 前端Dashboard |

### 7.3 日志位置

| 系统 | 日志位置 | 说明 |
|------|----------|------|
| master_daemon | `~/.workbuddy/logs/master_daemon.log` | 主进程日志 |
| V15马丁 | `~/.workbuddy/logs/v15_trader.log` | 马丁交易日志 |
| 经典指标 | `~/.workbuddy/logs/ml_trade_service.log` | 指标交易日志 |
| 风控 | `~/.workbuddy/logs/risk_engine.log` | 风控引擎日志 |

### 7.4 启动流程

```bash
# 启动主守护进程
python ops/master_daemon.py

# 启动经典指标系统
python 10-经典指标系统/ml_trade_service.py

# 启动经典指标前端
cd 10-经典指标系统/frontend && npm run dev

# 手动运行V15马丁一次
python 14-V15经典马丁策略/run.py trader --poll-once

# 启动资金管理API（可选）
python 14-V15经典马丁策略/lib/capital_manager_engine.py api --port 8770
```

---

## 8. 测试体系

### 8.1 测试文件位置

| 系统 | 测试目录 | 测试文件 | 测试数 |
|------|----------|----------|--------|
| V15马丁 | `14-V15经典马丁策略/tests/` | test_v15_system.py, test_v15_stress.py, test_multi_scenario.py, test_symbol_mapper.py | ~89 |
| 通用风控 | `13-通用风控模块/tests/` | test_risk_engine.py, test_l1_ml_alert.py | 51 |
| 三屏趋势 | `12-三屏趋势系统/tests/` | test_core.py | ~10 |
| 易经推理 | `11-易经推理系统/tests/` | e2e_l4_test.py, stress_test_l4.py, test_trading_protocol_*.py | 60+ |
| 经典指标 | `10-经典指标系统/test_*.py` | test_exit_system_backtest.py, test_signals_dedup.py, tests_three_chain_eval.py | ~15 |
| 调控系统 | `16-调控系统/tests/` | （空） | 0 |

### 8.2 测试命令

```bash
# V15马丁测试
cd 14-V15经典马丁策略 && python -m pytest tests/ -v

# 通用风控测试
cd 13-通用风控模块 && python -m pytest tests/ -v

# 多场景模拟测试
cd 14-V15经典马丁策略 && python test_multi_scenario.py

# 经典指标测试
cd 10-经典指标系统 && python -m pytest test_*.py -v
```

---

## 9. 技术债务索引

> 详细技术债务清单见 [DEBT_INDEX.md](./DEBT_INDEX.md)

### 9.1 债务分类统计

| 类别 | 数量 | 高优先级 | 中优先级 | 低优先级 |
|------|------|----------|----------|----------|
| 文档缺失 | 6 | 0 | 4 | 2 |
| 代码重复 | 4 | 2 | 2 | 0 |
| 架构不一致 | 3 | 1 | 2 | 0 |
| 未接入模块 | 4 | 2 | 2 | 0 |
| 配置混乱 | 2 | 2 | 0 | 0 |
| 依赖管理 | 2 | 1 | 1 | 0 |
| 性能问题 | 1 | 0 | 1 | 0 |
| **总计** | **22** | **8** | **12** | **2** |

### 9.2 高优先级债务

1. **D001** 通用风控模块未接入任何策略 — 13-通用风控已完成(51测试通过)，但全部策略未接入
2. **D002** V15CT与独立V15系统冗余 — 独立V15已运行，V15CT需清理
3. **D003** 配置文件优先级不清晰 — 三个.env文件加载顺序需文档化
4. **D004** OKX客户端重复实现 — V15马丁与经典指标各有独立实现
5. **D005** RAISE_TP动作不一致 — 只在V15实现，其他系统缺失
6. **D006** 杠杆倍数不一致 — 已修复（统一为5x）
7. **D007** 记忆系统未充分利用 — 仅易经推理部分使用
8. **D008** 依赖版本不统一 — 各子系统独立requirements.txt

---

## 10. 快速导航

### 10.1 按系统导航

| 系统 | 工程索引 | 技术文档 | 核心代码 |
|------|----------|----------|----------|
| **Dream OS 内核** | [dreamos/docs/ENGINEERING_INDEX.md](./1-ARCHITECTURE/dreamos/docs/ENGINEERING_INDEX.md) | [dreamos/docs/TECHNICAL_DESIGN.md](./1-ARCHITECTURE/dreamos/docs/TECHNICAL_DESIGN.md) | [dreamos/__init__.py](./1-ARCHITECTURE/dreamos/__init__.py) |
| V15马丁策略 | [docs/ENGINEERING_INDEX.md](./14-V15经典马丁策略/docs/ENGINEERING_INDEX.md) | [docs/TECHNICAL_DESIGN.md](./14-V15经典马丁策略/docs/TECHNICAL_DESIGN.md) | [core/v15_trader.py](./14-V15经典马丁策略/core/v15_trader.py) |
| 经典指标系统 | [docs/TECHNICAL_DESIGN.md](./10-经典指标系统/docs/TECHNICAL_DESIGN.md) | [技术文档.md](./10-经典指标系统/技术文档.md) | [ml_trade_service.py](./10-经典指标系统/ml_trade_service.py) |
| 三屏趋势系统 | [docs/ENGINEERING_INDEX.md](./12-三屏趋势系统/docs/ENGINEERING_INDEX.md) | [docs/TECHNICAL_DESIGN.md](./12-三屏趋势系统/docs/TECHNICAL_DESIGN.md) | [engine.py](./12-三屏趋势系统/engine.py) |
| 通用风控模块 | [docs/ENGINEERING_INDEX.md](./13-通用风控模块/docs/ENGINEERING_INDEX.md) | [docs/TECHNICAL_DESIGN.md](./13-通用风控模块/docs/TECHNICAL_DESIGN.md) | [core/engine.py](./13-通用风控模块/core/engine.py) |
| 易经推理系统 | [docs/ENGINEERING_INDEX.md](./11-易经推理系统/docs/ENGINEERING_INDEX.md) | [docs/TECHNICAL_DESIGN.md](./11-易经推理系统/docs/TECHNICAL_DESIGN.md) | [scripts/memory_l4/polling_trader.py](./11-易经推理系统/scripts/memory_l4/polling_trader.py) |
| 调控系统 | [docs/ENGINEERING_INDEX.md](./16-调控系统/docs/ENGINEERING_INDEX.md) | [docs/TECHNICAL_DESIGN.md](./16-调控系统/docs/TECHNICAL_DESIGN.md) | [core/skill_engine.py](./16-调控系统/core/skill_engine.py) |
| 架构设计 | [README.md](./1-ARCHITECTURE/README.md) | [SYSTEM_ARCHITECTURE_OVERVIEW.md](./1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) | - |

### 10.2 按功能导航

| 功能 | 文档/代码 |
|------|-----------|
| V15信号生成 | [v15_signal.py](./14-V15经典马丁策略/core/v15_signal.py) |
| 资金管理 | [capital_manager.py](./14-V15经典马丁策略/lib/capital_manager.py) |
| 贝叶斯优化 | [bayesian_optimizer.py](./14-V15经典马丁策略/lib/bayesian_optimizer.py) |
| 风控规则 | [rules/](./13-通用风控模块/rules/) |
| 趋势过滤 | [strategy_params.py](./14-V15经典马丁策略/lib/strategy_params.py) |
| 离场系统 | [classic_exit_system.py](./10-经典指标系统/classic_exit_system.py) |
| 进程管理 | [master_daemon.py](./ops/master_daemon.py) |
| 运维部署 | [ops/launchd/](./10-经典指标系统/ops/launchd/) |

### 10.3 按角色导航

| 角色 | 推荐阅读路径 |
|------|-------------|
| 新开发者 | 本文件 → 目标子系统ENGINEERING_INDEX → TECHNICAL_DESIGN → README |
| 运维人员 | 本文件§7 → 10-经典指标系统/系统运营技术文档.md → ops/ |
| 策略开发者 | 本文件§3.1 → 14-V15/docs/TECHNICAL_DESIGN.md → 10-经典指标/策略开发规范.md |
| 风控开发 | 本文件§3.2 → 13-通用风控模块/docs/ → DEBT_INDEX.md D001 |

---

## 11. 变更日志

| 日期 | 版本 | 变更内容 | 变更人 |
|------|------|----------|--------|
| 2026-07-15 | v2.1 | 易经推理系统切换逐仓风控模式（isolated）；ENGINEERING_INDEX v2.2、TECHNICAL_DESIGN v2.2同步更新；核心引擎描述增加逐仓风控 | DreamBuddy v2 |
| 2026-07-12 | v1.0 | 初始创建 | DreamBuddy v2 |
| 2026-07-13 | v2.0 | 重建为文件级索引，增加SSoT层级、变更流程、入口锚点 | DreamBuddy v2 |

---

_维护原则：本文件是项目的工程入口索引，任何子系统变更影响到入口、依赖关系、配置层级的，必须同步更新本文件。_
