# 工程索引 — 16-调控系统

> **定位：** 模块级工程索引（L2），对齐系统 `2-KNOWLEDGE/4-OPERATIONS/索引体系.md` 的 Z 轴三层规范
> **版本：** v2.0 | **更新：** 2026-07-25 | **维护者：** DreamBuddy v2

---

## 目录

- [1. 模块定位](#1-模块定位)
- [2. 目录地图](#2-目录地图)
- [3. 核心层文件清单（core/）](#3-核心层文件清单core)
- [4. 关键模块说明](#4-关键模块说明)
- [5. SKILL 注册清单](#5-skill-注册清单)
- [6. 核心流程索引](#6-核心流程索引)
- [7. 阶段规划](#7-阶段规划)
- [8. 配置与产物](#8-配置与产物)
- [9. 文档对齐说明（范围错位）](#9-文档对齐说明范围错位)
- [10. 快速导航](#10-快速导航)

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 16 |
| 模块名称 | 调控系统（统一 AI 离场评估系统） |
| 系统类型 | 跨系统宏观战略离场决策层 |
| 核心原则 | 建议制，不替代各系统自主离场逻辑 |
| 主入口 | `__init__.py`（导出 `fetch_all_positions` / `get_position_summary` / `SkillEngine` 等） |
| 核心模块目录 | `core/`（19 个 Python 文件 + `__init__.py`） |
| 覆盖交易系统 | Agent A / Agent B / Agent C / V15 马丁 / 易经推理 / 三屏趋势（共 6 个） |
| 四态输出 | CLOSE（平仓）/ REDUCE（减仓）/ HOLD（维持）/ RAISE_TP（提高止盈） |
| 依赖系统 | 10-经典指标系统（ClassicExitSystem）、6-TRADING/skills（SKILL.md 方法论）、13-通用风控、2-KNOWLEDGE |
| 调度方式 | TRAE Work 调度层（每天 08:00 / 20:00） |
| 数据来源 | Hyperliquid REST/WS、OKX API、CoinGecko、各系统 state/memory 文件 |

### 核心架构

```
TRAE Work 调度层（08:00 / 20:00）
        ↓
统一持仓查询层 unified_position_query.py（6 系统聚合）
        ↓
市场数据层 market_data_fetcher.py + realtime_market_stream.py
        ↓
宏观分析层 A1/A2/A3（skill_engine + llm_bridge + dream_insights + archive_center）
        ↓
离场决策层 A9 + technical_exit_adapter + strategy_exit_adapter（四态融合）
        ↓
执行/反馈层 exit_executor + feedback_and_permission + aam_deliverer
        ↓
进化闭环 evolution_loop + enhanced_evolution + backtest_framework
        ↓
产物投递 artifacts/（exit-evaluations / execution_logs / backtests / evolution）
```

---

## 2. 目录地图

### 2.1 顶层结构（16-调控系统/）

```
16-调控系统/
├── core/                                    核心业务逻辑（19 个 .py + __init__.py）
│   ├── __init__.py                          包入口：导出持仓查询 + SKILL 引擎
│   ├── a1_research_adapter.py               A1 调研适配器（dream-strategy-research v1.7.0）
│   ├── a2_first_principles_adapter.py       A2 第一性原理适配器（dream-first-principles v2.6.1）
│   ├── a3_strategy_adapter.py               A3 策略设计适配器（dream-strategy-designer v2.7.0）
│   ├── a9_exit_decision.py                  A9 离场决策（dream-exit-skill-v2 v2.2.0）— 四态输出
│   ├── aam_deliverer.py                     AAM 产物投递（双通道 + index.json）
│   ├── archive_center.py                    历史档案中心（案例检索 + 相似度匹配）
│   ├── backtest_framework.py                回测验证框架（纯技术 vs 宏观+技术对比）
│   ├── dream_insights_integration.py        做梦产物集成（dream_journal/brainstorm/insight）
│   ├── enhanced_evolution.py                增强版进化闭环（三层进化 + Walk-Forward + 观察期）
│   ├── evolution_loop.py                    进化闭环系统（记录→追踪→分析→调优→反馈）
│   ├── exit_executor.py                     离场执行器（评估→权限→执行→记录）
│   ├── feedback_and_permission.py           建议反馈与风险控制（5 级权限体系）
│   ├── llm_bridge.py                        LLM 桥接层（多 Provider + 降级 + 缓存）
│   ├── market_data_fetcher.py               市场数据获取（多源降级 + 60s 缓存）
│   ├── realtime_market_stream.py            实时行情流（Hyperliquid WS + 自动重连）
│   ├── skill_engine.py                      SKILL 执行引擎（方法论程序化框架）
│   ├── strategy_exit_adapter.py             策略离场设计原则适配层（6 种离场哲学）
│   ├── technical_exit_adapter.py            技术离场适配器（technical-exit-adapter v1.0.0）
│   ├── unified_position_query.py            统一持仓查询（6 系统全覆盖 + 降级容错）
│   ├── config/                              配置目录
│   │   └── artifact-hub.config.json         产物中心配置
│   ├── governance/                          治理目录
│   │   └── index.json                       治理索引
│   ├── intent-specs/                        意图规格目录（spec_task_*.json/md）
│   ├── meta/                                元数据目录（artifact_hub.sqlite）
│   └── results/                             结果目录
├── scripts/                                 独立工具脚本（非 crontab 调度）
│   ├── INDEX.md                             脚本索引
│   ├── auto_exit_system.py                  自动离场系统
│   ├── phase0_exit_evaluator.py             Phase 0 离场评估脚本
│   ├── phase2_exit_evaluator.py             Phase 2 离场评估脚本
│   ├── phase3_exit_evaluator.py             Phase 3 离场评估脚本
│   ├── step_controller.py                   步骤控制器
│   ├── skill_importer.py                    SKILL 导入器
│   ├── notebook_hook.py                     Notebook 钩子
│   ├── notebook_stress_test.py              Notebook 压力测试
│   ├── stress_test_7scenarios.py            7 场景压力测试
│   ├── test_e2e_exit_system.py              E2E 离场系统测试
│   ├── test_strategy_exit_adapter.py        策略离场适配器测试
│   ├── review_filter.py                     复盘过滤器
│   ├── sync_artifact.py                     产物同步
│   └── write_health_status.py              健康状态写入
├── docs/                                    技术文档
│   ├── ENGINEERING_INDEX.md                 本文件 — 工程索引
│   └── TECHNICAL_DESIGN.md                  技术设计文档（⚠️ 范围错位，见 §9）
├── artifacts/                               产物目录
│   ├── exit-evaluations/                    离场评估产物（JSON + Markdown）
│   ├── execution_logs/                      执行日志
│   ├── backtests/                           回测数据与报告
│   ├── evolution/                           进化闭环数据（pool/history/params/journal）
│   └── tests/                               E2E 测试产物
├── tests/                                   测试套件
│   └── __init__.py
├── __init__.py                              包入口
└── README.md                                用户文档
```

**代码统计：** `core/` 共 19 个核心 Python 文件（不含 `__init__.py`），覆盖持仓查询、市场数据、SKILL 引擎、宏观分析适配、离场决策、技术/策略融合、执行反馈、进化闭环、回测验证、产物投递等全链路。

---

## 3. 核心层文件清单（core/）

| 文件 | Phase | 职责 | 关键导出 |
|------|-------|------|----------|
| `__init__.py` | — | 包入口，导出持仓查询与 SKILL 引擎 | `fetch_all_positions`, `get_position_summary`, `SkillEngine`, `SkillResult`, `register_skill` |
| `unified_position_query.py` | P1 | 统一持仓查询：聚合 6 个交易系统持仓数据，统一格式输出；单系统失败降级容错；超时控制（单源 5s/总 30s） | `fetch_all_positions()`, `get_position_summary()` |
| `market_data_fetcher.py` | P2 | 市场数据获取：Hyperliquid REST → CoinGecko → 本地缓存多源降级；60s 缓存；统一格式 | 市场数据获取函数 |
| `realtime_market_stream.py` | P2+ | 实时行情流：Hyperliquid WebSocket 全市场 ticker；自动重连；线程安全单例；WS 不可用回退 REST 轮询 | 实时流单例类 |
| `skill_engine.py` | P2 | SKILL 执行引擎：读取 SKILL.md 方法论、解析阶段结构、统一输入/输出契约、降级回退；`@register_skill` 装饰器注册 | `SkillEngine`, `SkillResult`, `register_skill` |
| `llm_bridge.py` | P2+ | LLM 桥接层：OpenAI/DeepSeek/Anthropic/本地多 Provider；失败降级到规则引擎；Token 预算；60s 缓存；JSON 模式 | LLM 调用接口 |
| `a1_research_adapter.py` | P2 | A1 调研适配器（`dream-strategy-research` v1.7.0）：宏观战略调研，结合做梦产物与历史档案 | `a1_research_handler` |
| `a2_first_principles_adapter.py` | P2 | A2 第一性原理适配器（`dream-first-principles` v2.6.1）：第一性原理分析、市场状态分类、综合判断 | `a2_first_principles_handler` |
| `a3_strategy_adapter.py` | P2 | A3 策略设计适配器（`dream-strategy-designer` v2.7.0）：策略方向偏置、仓位修正、杠杆上限、目标币种 | `a3_strategy_designer_handler` |
| `a9_exit_decision.py` | P2 | A9 离场决策（`dream-exit-skill-v2` v2.2.0）：四层决策链（战略一致性→置信度加权→市场状态修正→最终合成+紧急度），输出四态 | `a9_exit_decision_handler` |
| `technical_exit_adapter.py` | P3 | 技术离场适配器（`technical-exit-adapter` v1.0.0）：接入 ClassicExitSystem，与宏观离场融合（P0 一票否决/技术+宏观强化/矛盾降级） | `technical_exit_handler` |
| `strategy_exit_adapter.py` | P3 | 策略离场设计原则适配层：为每个策略定义离场哲学、原生机制、宏观干预边界、专属权重；6 种哲学枚举（趋势/均值/马丁/基本面/情绪/震荡） | `ExitDesignPhilosophy` 等枚举与适配器 |
| `exit_executor.py` | P3+ | 离场执行器：评估结果→权限检查→执行决策→记录结果→反馈进化；默认 dry_run；最大执行数量限制防批量砸盘 | 执行器类与流程 |
| `feedback_and_permission.py` | P3 | 建议反馈与风险控制：采纳/拒绝记录、5 级权限体系（NOTIFY/ADVISE/AUTO_REDUCE/AUTO_CLOSE/FULL_AUTO）、审计日志、效果统计 | 权限与反馈管理 |
| `aam_deliverer.py` | P3 | AAM 产物投递：标准化 frontmatter、双通道投递（秘书邮箱+前端产物中心）、index.json 更新、投递验证 | 投递器接口 |
| `archive_center.py` | P2+ | 历史档案中心：历史 Episode 检索、战略库查询、记忆库查询、基于价格/波动率/RSI 的相似度匹配 | 档案检索函数 |
| `dream_insights_integration.py` | P2+ | 做梦产物集成：搜索并解析 dream_journal/brainstorm/insight 产物，与 A1 调研交叉验证 | 做梦产物解析函数 |
| `evolution_loop.py` | P3+ | 进化闭环系统：记录决策→追踪结果→分析准确性→参数调优→反馈决策→回测验证→采纳/回滚 | 闭环主流程 |
| `enhanced_evolution.py` | P3+ | 增强版进化闭环：集成 AB Trading 三层反思（A8/做梦部/GitHub）+ DreamOS gap_score + 三屏置信度校准 + 过拟合检测 + Walk-Forward + 7 天观察期 | 增强进化流程 |
| `backtest_framework.py` | P3 | 回测验证框架：模拟价格走势（随机漫步）、逐 bar 回测、多策略对比（baseline/macro_enhanced/hold）、绩效指标（胜率/盈亏比/回撤/夏普） | `run_backtest()` 等 |

---

## 4. 关键模块说明

### 4.1 持仓与数据层

- **`unified_position_query.py`** — Phase 1 基石，聚合 6 个交易系统持仓：
  - Agent A/B（Hyperliquid REST）、Agent C（共用 B 账户 + memory.json）、V15 马丁（OKX state.json + API）、易经推理（OKX 模拟盘 open_positions/*.json）、三屏趋势（ml_trade_service API，过渡期）
  - 单系统失败不影响整体，结果缓存，统一数据模型
- **`market_data_fetcher.py`** — Hyperliquid REST → CoinGecko → 本地缓存三源降级，60s 缓存，支持 BTC/ETH/SOL 及持仓币种
- **`realtime_market_stream.py`** — Hyperliquid WebSocket 全市场 ticker，自动重连，线程安全单例，WS 不可用时优雅降级到 REST 轮询

### 4.2 SKILL 引擎与分析适配层

- **`skill_engine.py`** — SKILL 方法论程序化执行框架：读取 `6-TRADING/skills/*/SKILL.md`，解析阶段结构，统一输入/输出契约，支持降级回退与未来 LLM bridge 接入
- **`a1_research_adapter.py`** — A1 宏观战略调研（`dream-strategy-research` v1.7.0），结合 `dream_insights_integration` 与 `archive_center`
- **`a2_first_principles_adapter.py`** — A2 第一性原理分析（`dream-first-principles` v2.6.1），输出市场状态分类与综合判断
- **`a3_strategy_adapter.py`** — A3 策略设计（`dream-strategy-designer` v2.7.0），输出方向偏置、仓位修正、杠杆上限、目标币种
- **`llm_bridge.py`** — 统一 LLM 调用桥接，多 Provider 支持，失败自动降级到规则引擎，Token 预算控制，60s 缓存，JSON 结构化输出
- **`archive_center.py`** — 历史案例检索与相似度匹配（价格走势/波动率/RSI）
- **`dream_insights_integration.py`** — 做梦部产物（dream_journal/brainstorm/insight）解析与 A1 交叉验证

### 4.3 离场决策与融合层

- **`a9_exit_decision.py`** — A9 离场决策核心（`dream-exit-skill-v2` v2.2.0），四层决策链：
  - Layer 1: 战略方向一致性检查
  - Layer 2: 置信度加权
  - Layer 3: 市场状态修正
  - Layer 4: 最终合成 + 紧急度评级
  - 输出四态：CLOSE / REDUCE / HOLD / RAISE_TP
- **`technical_exit_adapter.py`** — 技术离场适配器（`technical-exit-adapter` v1.0.0），接入 ClassicExitSystem SSOT，与宏观离场融合：
  - P0 安全硬退出（技术）→ 一票否决直接执行
  - 技术信号 + 宏观确认 → 强化
  - 技术信号 vs 宏观矛盾 → 降级为观察
  - 宏观信号 + 技术不支持 → 降级（减仓而非平仓）
- **`strategy_exit_adapter.py`** — 策略离场设计原则适配层，为每个策略定义离场哲学（6 种）、原生机制、宏观干预边界、专属权重；核心思想：宏观离场是"增强"而非"替代"

### 4.4 执行与反馈层

- **`exit_executor.py`** — 离场执行器：评估→权限检查→执行决策→记录结果→反馈进化；默认 dry_run，需显式开启实盘；最大执行数量限制防批量砸盘；L4 TradeEvent 跨系统统一记录
- **`feedback_and_permission.py`** — 建议反馈与风险控制：5 级权限体系（NOTIFY/ADVISE/AUTO_REDUCE/AUTO_CLOSE/FULL_AUTO），各系统默认权限（agent_a/b/c=ADVISE、v15_martin=NOTIFY、yijing_bcrm=ADVISE、screen_trend=NOTIFY），完整审计链路
- **`aam_deliverer.py`** — AAM 产物投递：标准化 frontmatter，双通道投递（秘书邮箱 `~/.workbuddy/skills/boss-secretary/reports/trading/` + 前端产物中心 `~/.workbuddy/artifacts/trading/`），index.json 更新与投递验证

### 4.5 进化闭环层

- **`evolution_loop.py`** — 基础进化闭环：① 记录决策 → ② 追踪结果 → ③ 分析准确性 → ④ 参数调优 → ⑤ 反馈决策 → ⑥ 回测验证 → ⑦ 采纳/回滚
- **`enhanced_evolution.py`** — 增强版进化闭环，集成项目多个进化系统：
  - Layer 1: A8 理论实践验证（内部自我批评）
  - Layer 2: 做梦部潜意识分析（外部视角反思）
  - Layer 3: 数据驱动调优（历史准确性参数自适应）
  - 验证三层：回测验证 + Walk-Forward 滚动前向 + 7 天观察期再采纳
  - 集成 DreamOS gap_score、三屏置信度校准（ECE/Platt Scaling）、过拟合检测（参数敏感性/置换检验）
- **`backtest_framework.py`** — 回测验证框架：基于历史波动率随机漫步模拟价格，逐 bar 回测，对比矩阵（baseline 纯技术 / macro_enhanced 宏观+技术 / hold 买入持有），绩效指标（胜率/盈亏比/最大回撤/夏普比）

---

## 5. SKILL 注册清单

> 通过 `@register_skill(name, path, version)` 装饰器注册到 `SkillEngine`

| 模块文件 | SKILL 名称 | SKILL.md 路径 | 版本 |
|----------|-----------|---------------|------|
| `a1_research_adapter.py` | `dream-strategy-research` | `6-TRADING/skills/dream-strategy-research/SKILL.md` | 1.7.0 |
| `a2_first_principles_adapter.py` | `dream-first-principles` | `6-TRADING/skills/dream-first-principles/SKILL.md` | 2.6.1 |
| `a3_strategy_adapter.py` | `dream-strategy-designer` | `6-TRADING/skills/dream-strategy-designer/SKILL.md` | 2.7.0 |
| `a9_exit_decision.py` | `dream-exit-skill-v2` | `6-TRADING/skills/dream-exit-skill-v2/SKILL.md` | 2.2.0 |
| `technical_exit_adapter.py` | `technical-exit-adapter` | `10-经典指标系统/classic_exit_system.py` | 1.0.0 |

---

## 6. 核心流程索引

### 6.1 离场评估主流程（Phase 2/3）

```
TRAE Work 调度（08:00 / 20:00）
  └─→ fetch_all_positions()  ← unified_position_query（6 系统聚合）
       └─→ market_data_fetcher / realtime_market_stream  ← 获取市场数据
            └─→ SkillEngine 执行链
                 ├─→ a1_research_handler          ← A1 调研（+ dream_insights + archive）
                 ├─→ a2_first_principles_handler  ← A2 第一性原理
                 └─→ a3_strategy_designer_handler ← A3 策略设计
                      └─→ a9_exit_decision_handler ← A9 四层决策链 → 四态输出
                           ├─→ technical_exit_handler  ← 技术融合（P0 一票否决）
                           └─→ strategy_exit_adapter   ← 策略专属权重调整
                                └─→ aam_deliverer  ← 产物投递（双通道 + index.json）
```

### 6.2 执行与反馈流程（Phase 3+）

```
离场评估结果
  └─→ exit_executor
       ├─→ 权限检查（feedback_and_permission 5 级权限）
       ├─→ dry_run 默认开启 / 显式开启实盘
       ├─→ 执行决策（最大数量限制防批量砸盘）
       ├─→ 记录结果（L4 TradeEvent 跨系统统一记录）
       └─→ 反馈进化系统
            └─→ evolution_loop / enhanced_evolution
                 ├─→ 记录决策上下文
                 ├─→ 追踪平仓结果
                 ├─→ 分析建议命中率
                 ├─→ 参数调优（置信度门槛/权重）
                 ├─→ backtest_framework 回测验证
                 └─→ 采纳/回滚（7 天观察期）
```

### 6.3 进化闭环流程

```
evolution_loop（基础闭环）
  ① 记录决策 → ② 追踪结果 → ③ 分析准确性 → ④ 参数调优
       → ⑤ 反馈决策 → ⑥ 回测验证 → ⑦ 采纳/回滚 → ①

enhanced_evolution（增强闭环）
  Layer 1: A8 理论实践验证（内部自我批评）
  Layer 2: 做梦部潜意识分析（外部视角反思）
  Layer 3: 数据驱动调优（历史准确性参数自适应）
  验证三层: 回测验证 + Walk-Forward + 7 天观察期再采纳
```

---

## 7. 阶段规划

| 阶段 | 状态 | 核心模块 | 说明 |
|------|------|----------|------|
| Phase 0 MVP | ✅ 完成 | `unified_position_query`（初版） | 技术通路验证 |
| Phase 1 查询层 | ✅ 完成 | `unified_position_query` | 6 系统全覆盖 |
| Phase 2 分析层升级 | ⏳ 进行中 | `skill_engine` / `a1` / `a2` / `a3` / `llm_bridge` / `market_data_fetcher` / `realtime_market_stream` / `archive_center` / `dream_insights_integration` | 接入真实 A1/A2/A3 SKILL |
| Phase 3 决策+执行层 | ⏳ 进行中 | `a9` / `technical_exit_adapter` / `strategy_exit_adapter` / `exit_executor` / `feedback_and_permission` / `aam_deliverer` / `backtest_framework` | 接入 A9 完整决策链 + 技术融合 + 执行反馈 |
| Phase 3+ 进化闭环 | ⏳ 进行中 | `evolution_loop` / `enhanced_evolution` | 越用越聪明的进化闭环 |

---

## 8. 配置与产物

### 8.1 配置

| 文件 | 路径 | 说明 |
|------|------|------|
| 产物中心配置 | `core/config/artifact-hub.config.json` | AAM 产物中心配置 |
| 治理索引 | `core/governance/index.json` | 治理节点索引 |
| 元数据 | `core/meta/artifact_hub.sqlite` | 产物中心元数据库 |

### 8.2 产物目录（artifacts/）

| 目录 | 内容 | 说明 |
|------|------|------|
| `exit-evaluations/` | `exit_evaluation_*.json/.md`、`phase2_*`、`phase3_*` | 离场评估产物（JSON + Markdown 双格式） |
| `execution_logs/` | `exit_execution_*.json` | 离场执行日志 |
| `backtests/` | `backtest_data_*.json`、`backtest_report_*.md` | 回测数据与报告 |
| `evolution/` | `evolution_pool.json`、`evolution_history.json`、`evolution_params.json`、`decision_log.jsonl`、`dream_journal.json`、`a8_inspection_log.json` | 进化闭环数据 |
| `tests/` | `e2e_exit_test.json` | E2E 测试产物 |

### 8.3 意图规格（core/intent-specs/）

存放 `spec_task_*.json` 与 `spec_task_*.md` 文件（2026-07-04 至 2026-07-05 期间生成的任务意图规格），用于记录每次任务化的意图与执行规格。

---

## 9. 文档对齐说明（范围错位）

> ⚠️ **范围错位问题**：当前 `docs/TECHNICAL_DESIGN.md` 的覆盖范围与系统实际能力严重不匹配。

| 维度 | TECHNICAL_DESIGN.md 当前范围 | 系统实际范围 |
|------|------------------------------|--------------|
| 文档标题 | "统一持仓离场评估系统 技术设计文档 v1.0" | 应为"统一 AI 调控系统技术设计" |
| 覆盖子模块 | 仅覆盖**离场评估子模块**（持仓聚合 + A1/A2/A3 + A9 四态） | 19 个核心文件，覆盖持仓/数据/SKILL引擎/分析适配/决策融合/执行反馈/进化闭环/回测/产物投递全链路 |
| 阶段定位 | Phase 2 — SKILL 引擎集成完成 | 已推进至 Phase 3 / Phase 3+（执行反馈 + 进化闭环） |
| 未覆盖模块 | — | `exit_executor` / `feedback_and_permission` / `aam_deliverer` / `evolution_loop` / `enhanced_evolution` / `backtest_framework` / `technical_exit_adapter` / `strategy_exit_adapter` / `market_data_fetcher` / `realtime_market_stream` / `archive_center` / `dream_insights_integration` / `llm_bridge` 等 |
| 创建/更新日期 | 2026-07-12 | 实际代码已迭代至 2026-07-21（执行日志最新时间） |

**建议后续动作**（不在本文档修改范围内）：
- 将 `TECHNICAL_DESIGN.md` 升级为覆盖完整调控系统的设计文档，或拆分为多个子模块设计文档
- 本工程索引（v2.0）已对齐实际代码结构，可作为代码侧的权威索引

---

## 10. 快速导航

| 目标 | 路径 |
|------|------|
| 用户文档 | `README.md` |
| 技术设计文档（⚠️ 范围错位，见 §9） | `docs/TECHNICAL_DESIGN.md` |
| 脚本索引 | `scripts/INDEX.md` |
| 包入口 | `core/__init__.py` |
| 持仓查询 | `core/unified_position_query.py` |
| SKILL 引擎 | `core/skill_engine.py` |
| A9 离场决策 | `core/a9_exit_decision.py` |
| 技术离场融合 | `core/technical_exit_adapter.py` |
| 离场执行 | `core/exit_executor.py` |
| 进化闭环 | `core/evolution_loop.py` / `core/enhanced_evolution.py` |
| 回测框架 | `core/backtest_framework.py` |
| LLM 桥接 | `core/llm_bridge.py` |
| 市场数据 | `core/market_data_fetcher.py` / `core/realtime_market_stream.py` |
| 产物投递 | `core/aam_deliverer.py` |
| 评估产物 | `artifacts/exit-evaluations/` |
| 执行日志 | `artifacts/execution_logs/` |
| 进化数据 | `artifacts/evolution/` |

---

**文档版本**: v2.0
**最后更新**: 2026-07-25
**对齐状态**: 已对齐 `core/` 实际代码结构（19 个核心 Python 文件）
