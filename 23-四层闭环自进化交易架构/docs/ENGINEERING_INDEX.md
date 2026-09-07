# 23-四层闭环自进化交易架构 — 工程索引

> **版本**: v1.0 | **更新日期**: 2026-09-07
> **定位**: 模块级工程索引（L2），对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md)

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 23 |
| 模块名称 | 四层闭环自进化交易架构 |
| 核心职责 | 观察→推断→实验→反思→回馈四层闭环自进化交易策略 |
| 主入口 | `dreambuddy_evolution/evolution_pipeline.py` (EvolutionPipeline)、`dreambuddy_evolution/engines/kline_event_handler.py` (KlineEventHandler) |
| 依赖关系 | 上游：OKX API、data_center.db、SentimentEngine、polling_trader；下游：polling_trader 建仓回调 |
| 文档状态 | ⚠️部分（SPEC 2 份 + 本四件套） |

---

## 2. 目录地图

```
23-四层闭环自进化交易架构/
├── docs/                               # 文档目录
│   ├── ENGINEERING_INDEX.md            # 本文件
│   ├── TECHNICAL_DESIGN.md             # 技术设计
│   ├── API_SPEC.md                     # 接口规格
│   └── CHANGELOG.md                    # 变更日志
├── dreambuddy_evolution/
│   ├── engines/                        # 引擎层（核心逻辑）
│   │   ├── kline_event_handler.py     # K线事件处理器（双起点+三层仓位+SL/TP）
│   │   ├── ripple_engine.py            # 涟漪扩散引擎（外察式RI）
│   │   ├── reflection_engine.py        # 反思引擎（CS一致性+ESS奖惩）
│   │   ├── reflection_scanner.py       # 反思学习扫描器（内省式RI）
│   │   ├── trade_index_builder.py     # 系统级交易索引库
│   │   ├── trade_settlement_bridge.py # 平仓反思桥接器
│   │   ├── modifiers.py                # 三修饰子（情绪/资金流/叙事）
│   │   └── tight_coupling_orchestrator.py # 紧耦合编排器（7步闭环）
│   ├── core/                           # 核心计算层
│   │   ├── resistance_vector.py        # L1 5维阻力向量
│   │   ├── level0_path_cost.py         # Level0 路径代价 d*
│   │   ├── strategy_gene.py            # L2 策略基因库（ESS）
│   │   ├── shadow_rl.py                # L3 影子RL追踪器
│   │   ├── bellman_tracker.py          # L4 Bellman V(s) 追踪器
│   │   └── strategy_gene.py            # 策略基因加载/ESS计算
│   ├── adapters/                       # 数据适配层
│   │   ├── data_pipeline.py            # 统一数据管线装配器
│   │   ├── okx_market.py               # OKX行情适配
│   │   ├── data_center.py              # data_center.db适配
│   │   ├── sentiment_bridge.py         # SentimentEngine桥接
│   │   ├── ess_provider.py             # ESS方向提供器
│   │   ├── subsystem_bridge.py        # 子交易系统桥接
│   │   ├── coin_scanner.py             # 50币池扫描器+美股配额
│   │   ├── cognitive_bridge.py         # 认知记忆桥接（Phase3）
│   │   ├── capital_rotation.py         # 资金轮动检测
│   │   ├── ripple_provider.py          # 涟漪关联币数据
│   │   ├── traditional_finance.py      # 传统金融信号（Regime/Kelly）
│   │   ├── narrative_adapter.py        # 叙事标签适配
│   │   ├── path_library.py             # 最优路径库
│   │   ├── ftc_orchestrator.py         # 金融思维链编排器
│   │   ├── ftc_executor.py             # FTC执行器
│   │   ├── ftc_schema.py               # FTC数据模式
│   │   ├── ftc_similarity.py           # FTC相似度
│   │   ├── ftc_combiner.py             # FTC组合器
│   │   ├── ftc_gene_innovation.py      # FTC基因创新
│   │   ├── ftc_evolution_bridge.py     # FTC进化桥接
│   │   ├── ftc_backtest.py             # FTC回测
│   │   ├── knowledge_anchors.py        # 知识锚点
│   │   └── okx_market.py               # OKX行情适配
│   ├── gene_data/                      # 策略基因数据
│   │   ├── strategy_genes/             # 条件+动作基因
│   │   ├── strategy_combinations/      # 组合库+ESS评分
│   │   └── schemas/                    # JSON Schema
│   ├── tests/                          # 测试套件
│   ├── evolution_pipeline.py           # 四层闭环pipeline编排器
│   ├── weights.py                      # 权威权重唯一源
│   └── alert_bridge.py                 # Lark告警桥接
├── SPEC-数据管线打通与能力落地.md        # 数据管线SPEC
└── SPEC-金融思维链层FTC设计.md          # FTC设计SPEC
```

**代码统计**：`engines/` 8 个核心文件，`core/` 6 个，`adapters/` 20+ 个。

---

## 3. 文件清单与职责

### 3.1 引擎层（engines/）

| 文件 | 类/函数 | 职责 | 关键方法 |
|------|---------|------|----------|
| `kline_event_handler.py` | `KlineEventHandler` | K线收盘事件核心处理器 | `on_kline_close()`, `_trigger_build_position()`, `_store_pre_trade_snapshot()` |
| `ripple_engine.py` | `RippleEngine` | 涟漪扩散引擎（外察式RI） | `detect_ripple_source()`, `compute_ri()`, `get_ri_action()` |
| `reflection_engine.py` | `ReflectionEngine` | 后验反思引擎（CS一致性→ESS奖惩） | `create_snapshot()`, `calculate_cs()`, `apply_reward()` |
| `reflection_scanner.py` | `ReflectionScanner` | 反思学习扫描器（内省式RI） | `scan()`, `get_coin_stats()` |
| `trade_index_builder.py` | `TradeIndexBuilder` | 系统级交易索引库构建器 | `_discover_sources()`, `get_trades()`, `build_index()` |
| `trade_settlement_bridge.py` | `TradeSettlementBridge` | 平仓反思桥接器 | `store_snapshot()`, `retrieve_snapshot()`, `on_trade_settled()` |
| `modifiers.py` | `apply_all_modifiers` 等 | 三修饰子（情绪/资金流/叙事） | `apply_sentiment_modifier()`, `apply_capital_modifier()` |
| `tight_coupling_orchestrator.py` | `TightCouplingOrchestrator` | 紧耦合7步闭环编排器 | `observe()`, `hypothesize()`, `experiment()`, `measure()`, `reflect()`, `learn()`, `feedback()` |

### 3.2 核心计算层（core/）

| 文件 | 类/函数 | 职责 | 关键方法 |
|------|---------|------|----------|
| `resistance_vector.py` | `ResistanceVector` | L1 5维阻力向量计算器 | `calculate()` |
| `level0_path_cost.py` | `compute_d_star()`, `compute_g_diag()` | Level0 路径代价计算 | `compute_d_star()` |
| `strategy_gene.py` | `load_gene_library()`, `calculate_ess()`, `top_combinations_by_ess()` | L2 策略基因加载+ESS排序 | `load_gene_library()`, `calculate_ess()` |
| `shadow_rl.py` | `ShadowRLTracker` | L3 影子RL样本追踪 | `record()`, `get_stats()` |
| `bellman_tracker.py` | `BellmanVTracker` | L4 Bellman V(s) TD(0)更新 | `td_update()`, `get_ess_adjustment()` |
| `strategy_gene.py` | 同上 | 策略基因schema校验+ESS | 同上 |

### 3.3 适配层（adapters/）

| 文件 | 类 | 职责 |
|------|-----|------|
| `data_pipeline.py` | `DataPipelineAdapter` | 统一数据管线装配器 |
| `okx_market.py` | `OKXMarketAdapter` | OKX行情适配（K线+Ticker+持仓） |
| `data_center.py` | `DataCenterAdapter` | data_center.db衍生品数据 |
| `sentiment_bridge.py` | `SentimentBridge` | SentimentEngine情绪桥接 |
| `ess_provider.py` | `ESSDirectionProvider` | ESS方向提供器 |
| `subsystem_bridge.py` | `SubSystemBridge` | 子交易系统信号桥接 |
| `coin_scanner.py` | `CoinScanner` | 50币池扫描+美股代币配额 |
| `cognitive_bridge.py` | `CognitiveBridge` | 认知记忆系统桥接（Phase3） |
| `capital_rotation.py` | `CapitalRotationAdapter` | 资金轮动检测 |
| `traditional_finance.py` | `TraditionalFinanceBridge` | 传统金融信号（Regime/Kelly/Vol） |

---

## 4. 核心流程索引

### 4.1 紧耦合7步闭环（TightCouplingOrchestrator）

```
① 观察        ② 推断        ③ 实验        ④ 测量
observe()  →  hypothesize() → experiment() → measure()
  ↓             ↓              ↓             ↓
RippleEngine  RI阈值表     Level0 d*+对齐   TP/SL结算

⑤ 反思        ⑥ 学习        ⑦ 回馈
reflect()  →  learn()    →  feedback()
  ↓             ↓              ↓
CS一致性      ESS delta      ESS→下一轮
```

### 4.2 K线事件主流程（KlineEventHandler.on_kline_close）

```
K线收盘 → L1 R向量 → 三修饰子 → Level0 d* → RippleEngine RI
                                                      ↓
                        ReflectionScanner RI ← 系统级交易索引库
                                    ↓
                    ri = max(ripple_ri, reflection_ri)
                                    ↓
                    三层仓位分级(probe/standard/trend)
                                    ↓
                    建仓回调 + SL/TP兜底 + snapshot持久化
```

### 4.3 四层Pipeline（EvolutionPipeline.run_symbol）

```
L1 状态空间 → Level0 路径代价 → L2 策略匹配 → 对齐决策 → L3 Shadow-RL → L4 Bellman V(s)
```

---

## 5. 配置参数索引

| 文件 | 作用 | 关键参数 |
|------|------|----------|
| `weights.py` | 权威权重唯一源 | `WEIGHTS["ESS"]={H:0.4,S:0.4,N_ratio:0.2}`, `FALLBACK_VALUES={RI:0.29,...}` |
| `kline_event_handler.py` | 三层仓位门槛 | `PROBE_THRESHOLD=0.40`, `STANDARD_THRESHOLD=0.55`, `TREND_THRESHOLD=0.70` |
| `ripple_engine.py` | 涟漪检测门槛 | `vol_ratio_threshold=2.0`, `liq_change_threshold=0.30` |
| `reflection_scanner.py` | 反思学习门槛 | `MIN_WIN_RATE=0.55`, `MAX_HISTORY_DAYS=90` |
| `trade_index_builder.py` | 索引库配置 | `CACHE_TTL=300`, `DISCOVERY_CACHE_TTL=3600`, `MAX_SCAN_DEPTH=5` |

---

## 6. 测试体系

| 文件 | 测试内容 |
|------|----------|
| `test_kline_event_handler.py` | K线事件处理器双起点+三层仓位 |
| `test_tight_coupling.py` | 紧耦合7步闭环 |
| `test_evolution_pipeline.py` | 四层Pipeline |
| `test_resistance_vector.py` | L1 5维阻力向量 |
| `test_strategy_gene.py` | 策略基因加载+ESS |
| `test_weights.py` | 权重一致性 |
| `test_data_pipeline.py` | 数据管线装配 |
| `test_okx_market.py` | OKX行情适配 |
| `test_data_center_adapter.py` | data_center适配 |
| `test_sentiment_bridge.py` | 情绪桥接 |
| `test_ess_provider.py` | ESS方向提供器 |
| `test_subsystem_bridge.py` | 子系统桥接 |
| `test_trade_settlement_bridge.py` | 平仓反思桥接 |
| `test_capital_rotation.py` | 资金轮动 |
| `test_cognitive_bridge.py` | 认知桥接 |
| `test_narrative_adapter.py` | 叙事适配 |
| `test_ripple_provider.py` | 涟漪数据提供 |
| `test_modifiers.py` | 三修饰子 |
| `test_v3_backtest.py` | V3回测 |

**运行命令**：
```bash
cd 23-四层闭环自进化交易架构 && python -m pytest dreambuddy_evolution/tests/ -v
```

---

## 7. 技术债务

| 债务项 | 严重程度 | 说明 | 关联 DEBT_INDEX ID |
|--------|----------|------|---------------------|
| CognitiveBridge Phase3未实现 | 低 | 预留接口，≥2000样本后解冻 | — |
| ShadowRL Phase3未激活 | 低 | 仅记录样本，Phase3启动gmax变异 | — |

详见 [DEBT_INDEX.md](../../DEBT_INDEX.md)。

---

## 8. 快速导航

| 目标 | 路径 |
|------|------|
| 技术设计 | [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) |
| 接口规格 | [API_SPEC.md](./API_SPEC.md) |
| 变更日志 | [CHANGELOG.md](./CHANGELOG.md) |
| 数据管线SPEC | [SPEC-数据管线打通与能力落地.md](../SPEC-数据管线打通与能力落地.md) |
| FTC设计SPEC | [SPEC-金融思维链层FTC设计.md](../SPEC-金融思维链层FTC设计.md) |
| 架构总览 | [四层闭环进化架构-最小阻力路径总览.md](../../2-KNOWLEDGE/1-TRADING/四层闭环进化架构-最小阻力路径总览.md) |
| 项目文档索引 | [0-系统文档管理/INDEX.md](../../0-系统文档管理/INDEX.md) |

---

**文档版本**: v1.0
**最后更新**: 2026-09-07
