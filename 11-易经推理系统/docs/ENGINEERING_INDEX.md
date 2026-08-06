# 易经推理系统 工程索引（SSoT）

> **版本**: v2.6 | **更新日期**: 2026-07-25
> **定位**: 易经推理系统的工程入口索引（Single Source of Truth），包含所有子模块的文件级索引、入口锚点、依赖关系和快速导航
> **维护原则**: 任何子系统变更影响入口、依赖关系、配置层级的，必须同步更新本文件

---

## 0. 使用规则（强制）

### 0.1 变更流程

任何功能修改/扩展遵循以下流程：

1. **先阅读本文件** — 通过"工程索引(0.3)"与"系统索引(§3)"定位入口与既有排障口径
2. **再出方案** — 包含：影响范围、接口/配置变更、验收标准、回滚策略
3. **再改代码** — 小步提交，保持可回退
4. **验收合格后** — 在对应子系统文档追加变更日志

### 0.2 文档权威边界（SSoT 层级）

| 层级 | 文档 | 权威范围 | 冲突时的优先级 |
|------|------|----------|----------------|
| L0 | 全局 [ENGINEERING_INDEX.md](../../ENGINEERING_INDEX.md) | 全项目工程索引、系统间依赖 | 最高 |
| L0 | 本文件（docs/ENGINEERING_INDEX.md） | 本系统工程索引、模块间依赖 | 系统内最高 |
| L0 | [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | 系统技术架构、设计原则、数据流 | 架构层面最高 |
| L0 | `constraints/system-index/engineering-architecture.md` | 约束层架构基线 | 约束层面最高 |
| L1 | BCRM 2.0 技术文档（内嵌） | BCRM 2.0量化引擎行为边界 | 该子模块内最高 |
| L2 | 各模块内联注释 | 具体实现细节 | 代码级 |

### 0.3 工程索引（必读入口）

#### 运行入口

| 进程 | 入口文件 | 调度方式 | 说明 |
|------|----------|----------|------|
| 轮询交易器 | `scripts/memory_l4/polling_trader.py` | launchd | A0-A9决策链 + BCRM 2.0引擎 + 实盘交易 |
| BCRM 2.0适配器 | `scripts/memory_l4/bcrm2_adapter.py` | 被 polling_trader 调用 | 封装BCRM 2.0训练/推理/缓存，兼容BCRM 1.0接口 |
| 系统诊断 | `scripts/memory_l4/inspect.py` | 手动 / 启动时自检 | 系统健康检查（状态/持仓/模型/连接/风控/飞书） |
| 多场景验证 | `multi_scenario_validation.py` | 手动运行 | 25个用例覆盖推理/离场/风控/反馈/异常五场景 |
| 离场分析工具 | `scripts/memory_l4/analyze_eth_exit.py` | 手动运行 | 持仓离场四场景分析（hold/reduce/raise_tp/close） |
| 置信度优化 | `scripts/memory_l4/confidence_optimization.py` | 手动运行 | 回测不同置信度阈值下的胜率/收益 |
| BCRM 2.0回测 | `scripts/memory_l4/bcrm2/run_phase0_validation.py` | 手动运行 | Phase 0基线回测 |
| 自进化引擎 | `scripts/memory_l4/self_evolution_engine.py` | 手动/触发 | 三层反思闭环 |
| L4记忆管道 | `scripts/memory_l4/pipeline.py` | 事件触发 | case→review→distill→stats全链路 |
| 易经监控 | `scripts/memory_l4/yijing_monitor.py` | launchd | 系统健康监控 + 飞书告警推送 |
| 飞书告警 | `scripts/memory_l4/yijing_feishu_alert.py` | 被 yijing_monitor 调用 | 飞书告警推送模块（心跳/风控/模型/持仓/系统） |
| 统一监控 | `15-监控告警系统/adapters/yijing_adapter.py` | 被统一调度器调用 | 易经推理系统监控适配器（进程/交易/持仓/模型/余额） |
| CI门禁 | `scripts/ci/*.py` + `.github/workflows/` | GitHub Actions | 架构同步、分支生命周期、进化门禁等 |

#### 核心链路入口（信号 → 决策 → 执行 → 记忆沉淀）

| 链路环节 | 入口 | 所属模块 |
|----------|------|----------|
| 矛盾识别 | `bcrm/engine.py` → `BCRMEngine` | BCRM 1.0 |
| 八卦力学 | `bcrm/bagua_engine.py` → `BaguaEngine` | BCRM 1.0 |
| BCRM 2.0推理 | `bcrm2/dialectical_ml_engine.py` → `DialecticalMLEngine` | BCRM 2.0 |
| BCRM 2.0实盘适配 | `bcrm2_adapter.py` → `BCRM2Adapter` | 适配层（含五角校验） |
| 五角校验 | `triangle_verifier.py` → `TriangleVerifier` | 校验层（BCRM2×力学×A0×Ising×TDA） |
| 市态切换 | `bcrm2/market_regime.py` → `MarketRegimeClassifier` | BCRM 2.0 |
| QMM量化记忆 | `qmm/engine.py` → `run_qmm()` | QMM |
| 三屏趋势 | `qmm/triple_screen.py` → `compute_triple_screen()` | QMM |
| 交易执行 | `polling_trader.py` → `PollingTrader` | 顶层 |
| 离场决策（主） | `yijing_exit_system.py` → `YijingExitSystem` | 顶层（v2架构反转后为主） |
| 离场决策（备用） | `classic_exit_system.py` → `ClassicExitSystem` | 顶层（无卦象或降级时调用） |
| 离场决策（DreamOS） | `exit_module_adapter.py` → `YijingExitAdapter` | DreamOS（统一接口+三级卦象降级+9→4映射，详见 TECHNICAL_DESIGN §9.8） |
| 震荡市增强 | `ranging_market_enhancer.py` → `RangingMarketEnhancer` | 顶层（BCRM信号后置增强） |
| CBR 案例检索 | `cbr_engine.py` → `CBREngine` / `cbr_adapter.py` → `CBRSignalEnhancer` | 顶层（BCRM2辅助决策层） |
| 系统诊断 | `inspect.py` → `InspectReport` | 顶层（启动自检 + 手动排障） |
| 记忆沉淀 | `pipeline.py` → `run_pipeline()` | L4记忆 |
| 自进化 | `self_evolution_engine.py` → `SelfEvolutionEngine` | 顶层 |

#### 配置与状态落地点（排障先看）

| 系统 | 配置文件 | 状态文件 |
|------|----------|----------|
| BCRM 2.0 | `configs/baseline_config.json` | `data/bcrm2_phase0/` |
| BCRM 2.0 模型 | 按币种_周期分目录 | `scripts/data/bcrm2_models/{SYMBOL}_{TIMEFRAME}/` |
| 轮询交易器 | 环境变量 + 代码默认值 | `data/polling_trader/trader_*.jsonl` |
| OKX模拟 | `data/okx_sim/config.json` | `data/okx_sim/sim_trades_audit.jsonl` |
| L4记忆 | `scripts/memory_l4/paths.py` 配置 | `artifacts/memory_l4/` |
| 共享内存总线 | 代码内配置 | `artifacts/memory_l4/shared_bus/` |
| 约束层 | `constraints/` 各目录 | `constraints/releases/` 版本快照 |

#### 维护自检（改动后最少跑一遍）

```bash
# 语法自检
python -m py_compile <changed_file.py>

# L4记忆测试
cd 11-易经推理系统 && python -m pytest tests/test_memory_l4_*.py -v

# QMM测试
cd 11-易经推理系统 && python -m pytest tests/test_qmm_*.py -v

# 交易协议测试
cd 11-易经推理系统 && python -m pytest tests/test_trading_*.py -v

# CI脚本测试
cd 11-易经推理系统 && python -m pytest tests/test_ci_*.py -v
```

---

## 1. 系统概览

易经推理系统（I Ching Reasoning System）是一个将易经哲学（八卦、六十四卦、辩证思维）与现代量化交易深度融合的智能决策系统。

### 1.1 核心架构范式

**约束层驱动 + 记忆底座服务 + 并联工作流协同 + 统一产物出口**

```
┌─────────────────────────────────────────────────┐
│  底层约束层 (constraints/)                      │  ← 唯一规则源（SSOT）
│  constitution / system-index / workflows-spec   │
└─────────────────────────────────────────────────┘
                      ↓ 约束
┌─────────────────────────────────────────────────┐
│  记忆工作流 (workflows/memory/) - 底座         │
│  L1/L2/L3/L4 + review + distill + index         │
└─────────────────────────────────────────────────┘
                      ↓ 服务
┌─────────────────────────────────────────────────┐
│  并联工作流 (四条线)                            │
│  governance / trading / knowledge / evolution   │
└─────────────────────────────────────────────────┘
```

### 1.2 技术栈

| 层次 | 技术 | 版本 | 用途 |
|------|------|------|------|
| 核心引擎 | Python | 3.9+ | BCRM/QMM/交易执行 |
| ML框架 | LightGBM / XGBoost | latest | 辩证ML、Meta-Labeling |
| 拓扑数据分析 | ripser + persim | 0.6.x / 0.3.x | TDA持久同调、瓶颈距离 |
| 数据处理 | Pandas / NumPy | latest | 特征工程、回测 |
| 特征工程 | scikit-learn | latest | 特征选择、标准化 |
| 贝叶斯优化 | Optuna | latest | TPE参数搜索 |
| 数据存储 | SQLite | built-in | 交易记录、版本管理 |
| 行情接口 | OKX API | v5 | 实盘行情与交易 |
| CI/CD | GitHub Actions | - | 架构门禁、进化门禁 |
| 进程管理 | launchd (macOS) | - | 定时任务调度 |
| 技能体系 | Skills (0-CORE/1-TRADE/2-INTELLIGENCE/3-SUPPORT/4-GENERIC) | - | 模块化能力封装 |

### 1.3 核心特性

- **双引擎架构**: BCRM 1.0（矛盾力学推理）+ BCRM 2.0（辩证ML）
- **五象力场物理引擎**: 时/空/表/里/流五象力场 + Verlet辛积分 + Langevin随机项 + 卡尔曼滤波
- **五角校验架构 v4**: BCRM2(ML) × 力学引擎(物理) × A0(矛盾) × Ising(相变) × TDA(拓扑) 五源风险信号综合评分→双向风控（仓位/杠杆/止盈/止损）
- **转折预警三层阶梯**: TDA拓扑突变(最早) → Ising相变(中期) → 力学引擎减速(确认)
- **风险注意力机制**: 追踪各源风险预警准确率，指数衰减动态加权（decay=0.97）
- **v4回测验证**: 夏普10.16→10.20(+0.4%)、回撤10.12%→10.34%(+0.22%)、收益135.31%→139.40%(+4.09%)，四项标准全通过
- **八卦特征工程**: 8卦→8维度→~111个特征的易经映射体系
- **辩证ML三层**: L1主方向（正题）→ L2 Meta-Labeling（反题）→ L3辩证裁决（合题）
- **8种市态切换**: 自适应参数调整与仓位管理
- **L4四级记忆**: 实时→短期→长期→归档的完整记忆生命周期
- **自进化闭环**: 三层反思（A8/做梦部/联网）+ 约束升级通道
- **A0-A9决策链**: 矛盾分析→调研→第一性原理→推演→验证→执行→监控→审计→理论实践→离场
- **完整CI/CD**: 15个CI脚本 + 6个GitHub Actions工作流

---

## 2. 目录结构

### 2.1 全系统目录树

```
11-易经推理系统/
│
├── configs/                          # 配置文件
│   └── baseline_config.json          # BCRM 2.0基线配置
│
├── constraints/                      # ★ 底层约束层（SSOT）
│   ├── constitution/                 # 系统最高约束与原则
│   ├── system-index/                 # 架构索引、组件边界
│   │   └── engineering-architecture.md  # 工程架构基线
│   ├── workflows-spec/               # 工作流规范（30+文档）
│   │   ├── l4-memory/                # L4记忆工作流规范
│   │   ├── trading.md                # 交易工作流规范
│   │   ├── evolution.md              # 进化工作流规范
│   │   ├── governance.md             # 治理工作流规范
│   │   ├── knowledge.md              # 知识工作流规范
│   │   ├── memory.md                 # 记忆工作流规范
│   │   ├── a0-a9-fullchain-checklist.md
│   │   ├── trading-communication-protocol-v2.md
│   │   └── communication-contract-v0.1.md
│   ├── qmm/                          # QMM量化记忆模型规范
│   │   ├── phase-1.md ~ phase-4.md   # 四阶段规划
│   │   ├── architecture.md
│   │   └── version-triple-spec.md
│   ├── faq/                          # 常见问题与外部系统问答
│   │   └── OKX_FAQ.md
│   └── releases/                     # 约束版本快照
│       ├── v0.1.json
│       ├── v0.1.1.json
│       └── v0.1.2.json
│
├── docs/                             # 技术文档
│   ├── ENGINEERING_INDEX.md          # 本文件 — 工程索引（SSoT）
│   ├── TECHNICAL_DESIGN.md           # 技术设计文档（BCRM 2.0）
│   ├── architecture.md               # 系统架构简述
│   ├── README.md                     # 文档索引
│   └── superpowers/                  # Superpowers方法论集成
│       ├── plans/                    # 执行计划（7个）
│       └── specs/                    # 设计规范（2个）
│
├── scripts/                          # 核心代码
│   ├── ci/                           # ★ CI/CD脚本（16个）
│   │   ├── architecture_sync_guard.py    # 架构同步门禁
│   │   ├── branch_lifecycle_bot.py       # 分支生命周期
│   │   ├── safe_main_merge_gate.py       # 安全合入门禁
│   │   ├── evolution_decision_gate.py     # 进化决策门禁
│   │   ├── evolution_governance_report.py # 进化治理报告
│   │   ├── evolution_candidate_priority_score.py
│   │   ├── evolution_policy_regression_matrix.py
│   │   ├── evolution_version_compare_dashboard.py
│   │   ├── constraint_release_snapshot.py # 约束发布快照
│   │   ├── constraint_rollback.py         # 约束回滚
│   │   ├── post_merge_audit.py            # 合并后审计
│   │   ├── remote_repo_guard.py           # 远程仓库守护
│   │   ├── review_policy_guard.py         # 评审策略守护
│   │   ├── trading_traceability_guard.py  # 交易可追溯守护
│   │   └── quick_merge.sh                 # 快速合并脚本
│   │
│   ├── memory_l4/                    # ★ L4记忆引擎核心（40+脚本）
│   │   ├── bcrm/                     # BCRM 1.0 — 矛盾力学推理引擎
│   │   │   ├── engine.py             # BCRMEngine 核心入口
│   │   │   ├── yijing_engine.py      # 易经引擎（卦象解释）
│   │   │   ├── bagua_engine.py       # 八卦力学引擎
│   │   │   ├── liangyi_engine.py     # 两仪引擎
│   │   │   ├── force_engine.py       # ★ 力学引擎（五象力场+Verlet+Langevin+Kalman）
│   │   │   ├── kalman_filter.py      # ★ 卡尔曼滤波（速度-加速度贝叶斯状态估计）
│   │   │   ├── ising_phase_detector.py # ★ Ising相变检测（统计力学市场集体状态）
│   │   │   ├── tda_early_warning.py  # ★ TDA拓扑早期预警（持久同调转折点检测）
│   │   │   ├── scale_engine.py       # 规模引擎
│   │   │   ├── sixty_four_guas.py    # 六十四卦定义
│   │   │   ├── walk_forward.py       # Walk-Forward回测
│   │   │   ├── backtest_gate.py      # 回测门禁
│   │   │   ├── guardrail.py          # 护栏规则
│   │   │   ├── knowledge_base.py     # 知识库
│   │   │   ├── memory_adapter.py     # 记忆适配器
│   │   │   ├── a_series_bridge.py    # A系列桥接
│   │   │   ├── case_writer.py        # Case写入器
│   │   │   ├── market_preprocessor.py # 市场预处理器
│   │   │   ├── output_contract.py    # 输出契约
│   │   │   ├── strategy_diversity.py  # 策略多样性
│   │   │   ├── _constants.py         # 常量定义
│   │   │   └── __init__.py
│   │   │
│   │   ├── bcrm2/                    # BCRM 2.0 — 辩证ML量化引擎
│   │   │   ├── run_phase0_validation.py    # Phase 0回测主入口
│   │   │   ├── walk_forward_backtester.py  # Walk-Forward回测引擎
│   │   │   ├── portfolio_backtester.py     # 组合回测引擎
│   │   │   ├── dialectical_ml_engine.py    # ★ 辩证ML引擎(L1/L2/L3)
│   │   │   ├── bagua_feature_engine.py     # ★ 八卦特征引擎(~111特征)
│   │   │   ├── market_regime.py            # ★ 市态切换引擎(8种市态)
│   │   │   ├── feature_selector.py         # 特征选择模块
│   │   │   ├── classic_experience_features.py  # 经典经验特征(~30)
│   │   │   ├── fibonacci_features.py       # 斐波那契特征(~10)
│   │   │   ├── pivot_point_features.py     # 枢纽点特征(~10)
│   │   │   ├── wdh_features.py             # WDH时间维度(~45)
│   │   │   ├── cycle_features.py           # 库存周期特征(~55)
│   │   │   ├── market_cap.py               # 市值等级配置与特征
│   │   │   ├── cross_asset_features.py     # 跨资产特征(~33)
│   │   │   ├── merrill_clock_features.py   # 美林时钟特征(~55)
│   │   │   ├── meta_labeling_features.py   # Meta-Labeling V1
│   │   │   ├── meta_labeling_features_v2.py # Meta-Labeling V2(~25)
│   │   │   ├── rsi_sentiment_features.py   # RSI情绪特征(~8)
│   │   │   ├── anomaly_detector.py         # 异常检测
│   │   │   ├── data_fetcher.py             # 数据获取服务
│   │   │   ├── triple_barrier_labeler.py   # 三重屏障标签
│   │   │   ├── incremental_learner.py      # 增量学习模块
│   │   │   ├── check_hexagram_mismatch.py  # 卦象不一致检查
│   │   │   ├── analyze_btc.py              # BTC专项分析
│   │   │   └── __init__.py
│   │   │
│   │   ├── qmm/                      # QMM — 量化记忆模型
│   │   │   ├── engine.py             # QMM引擎入口 run_qmm()
│   │   │   ├── gate.py               # QMM门禁 GateRunner
│   │   │   ├── triple_screen.py      # 三屏趋势计算
│   │   │   ├── trend_velocity.py     # 趋势速度计算
│   │   │   ├── mrd.py                # 阻力方向（Minimal Resistance Direction）
│   │   │   ├── uncertainty.py        # 不确定性计算
│   │   │   ├── drift.py              # 漂移检测
│   │   │   ├── overfitting.py        # 过拟合检测
│   │   │   ├── data_prep.py          # 数据准备
│   │   │   ├── backtest.py           # 回测集成
│   │   │   ├── xgb_predictor.py      # XGBoost预测器
│   │   │   ├── types.py              # 类型定义
│   │   │   ├── paths.py              # 路径配置
│   │   │   └── __init__.py
│   │   │
│   │   ├── __init__.py
│   │   ├── polling_trader.py         # ★ 轮询交易器（P2完整版，BCRM 2.0实盘+易经离场+震荡增强+CBR）
│   │   ├── bcrm2_adapter.py          # ★ BCRM 2.0适配器（训练/推理/缓存/五角校验）
│   │   ├── bcrm2_real_verifier.py    # BCRM 2.0 实盘推理路径五角校验验证器
│   │   ├── triangle_verifier.py      # ★ 五角校验器（BCRM2×力学×A0×Ising×TDA）
│   │   ├── force_engine_backtest.py  # 力学引擎回测脚本（baseline/p0/p1_kalman/p2_full 四模式）
│   │   ├── pentagon_backtest.py      # 五角校验Walk-Forward完整回测
│   │   ├── bayesian_optimize.py      # 贝叶斯参数优化（Optuna TPE）
│   │   ├── fast_verifier.py          # 五角校验快速验证脚本
│   │   ├── yijing_exit_system.py     # ★★ 主离场系统（FORCE_CLOSE/RAISE_TP/HOLD，v2架构反转后为主）
│   │   ├── classic_exit_system.py    # 备用离场系统（CLOSE/REDUCE/RAISE_TP/HOLD，降级使用）
│   │   ├── ranging_market_enhancer.py # ★ 震荡市增强层（5态自适应+布林双信号+动态止损+置信度校准）
│   │   ├── a0_contradiction_engine.py # ★ A0矛盾引擎（七维矛盾张力，已集成进polling_trader/bcrm2_adapter）
│   │   ├── a7_practice_gate.py       # A7实践门禁
│   │   ├── cbr_engine.py             # ★ CBR案例检索引擎（4R循环：Retrieve→Reuse→Revise→Retain）
│   │   ├── cbr_similarity.py         # CBR相似度计算（特征距离+卦象匹配+市态对齐）
│   │   ├── cbr_sharded_retriever.py  # CBR分片检索器（大规模案例库检索优化）
│   │   ├── cbr_adapter.py            # CBR→BCRM2适配层（CBRSignalEnhancer，三融合策略）
│   │   ├── pipeline.py               # ★ L4记忆全链路管道
│   │   ├── self_evolution_engine.py  # ★ 自进化引擎（三层反思）
│   │   ├── okx_simulated.py          # OKX模拟客户端
│   │   ├── paths.py                  # 全局路径配置
│   │   ├── trading_utils.py          # 交易工具（绩效/风控/持仓）
│   │   ├── learning_scheduler.py     # 学习调度器
│   │   ├── process_guardian.py       # 进程守护
│   │   ├── analyze_eth_exit.py       # 离场分析工具（四场景模拟）
│   │   ├── confidence_optimization.py # 置信度阈值回测优化
│   │   ├── confidence_detailed_analysis.py # 置信度区间详细分析
│   │   ├── shared_memory_bus.py      # 共享内存总线
│   │   ├── agent_acl.py              # Agent访问控制
│   │   ├── case_registry.py          # Case注册表
│   │   ├── a0a9_bridge.py            # A0-A9桥接器
│   │   ├── a7a8_bridge.py            # A7-A8桥接器
│   │   ├── a_research_bridge.py      # 调研桥接器
│   │   ├── ab_bridge.py              # AB桥接器
│   │   ├── knowledge_bridge.py       # 知识库桥接
│   │   ├── review_engine.py          # 复盘引擎
│   │   ├── distill_engine.py         # 蒸馏引擎
│   │   ├── distill_template.py       # 蒸馏模板
│   │   ├── stats_engine.py           # 统计引擎
│   │   ├── index_builder.py          # 索引构建器
│   │   ├── query_similar.py          # 相似查询
│   │   ├── memory_graph.py           # 记忆图谱
│   │   ├── failure_analyzer.py       # 故障分析器
│   │   ├── dashboard_renderer.py     # 仪表板渲染
│   │   ├── meta_learning_tasks.py    # 元学习任务
│   │   ├── migration_mapper.py       # 迁移映射器
│   │   ├── quadrant_migrator.py      # 象限迁移器
│   │   ├── scenario_extender.py      # 场景扩展器
│   │   ├── screen_martin_bridge.py   # 三屏马丁桥接
│   │   ├── yijing_monitor.py         # 易经监控器
│   │   ├── yijing_feishu_alert.py    # 飞书告警模块
│   │   ├── yijing_trainer.py         # 易经训练器
│   │   ├── tavily_macro.py           # Tavily宏观搜索
│   │   ├── batch_backtest.py         # 批量回测
│   │   ├── install_trading.sh        # 交易安装脚本
│   │   ├── start_trading.sh          # 交易启动脚本
│   │   └── com.yijing.trading.plist  # launchd配置
│   │
│   ├── data/                         # 数据文件
│   │   └── klines/                   # K线数据（BTC/ETH/SOL/UNI 1H）
│   │
│   └── trading_demo/                 # 交易Demo
│       ├── http_server.py            # HTTP服务器
│       ├── redis_streams_consumer.py # Redis流消费者
│       ├── e2e_http_smoke.py         # E2E HTTP冒烟测试
│       └── README.md
│
├── skills/                           # ★ 技能库（4大类）
│   ├── 0-CORE/                       # 核心技能（10个）
│   │   ├── memory-manager/           # 记忆管理器
│   │   ├── learning-episode-writer/  # 学习片段写入器
│   │   ├── learning-lesson-distiller/ # 学习教训蒸馏器
│   │   ├── learning-proposal-generator/ # 学习提案生成器
│   │   ├── dream-governance-manager/ # 梦境治理管理器
│   │   ├── dream-knowledge/          # 梦境知识
│   │   ├── dream-constitution/       # 梦境宪章
│   │   ├── architecture-sync-guard/  # 架构同步守护
│   │   ├── artifact-alignment-manager/ # 产物对齐管理器
│   │   ├── branch-lifecycle-automation/ # 分支生命周期自动化
│   │   ├── code-review-merge-assistant/ # 代码评审合并助手
│   │   └── safe-main-merge/          # 安全主分支合并
│   │
│   ├── 1-TRADE/                      # 交易技能（16个）
│   │   ├── dream-contradiction-theory/   # 矛盾理论
│   │   ├── dream-first-principles/       # 第一性原理
│   │   ├── dream-strategy-research/      # 策略研究
│   │   ├── dream-strategy-designer/      # 策略设计器
│   │   ├── dream-strategy-parser/        # 策略解析器
│   │   ├── dream-signal-scoring-spec/    # 信号评分规范
│   │   ├── dream-pretrade-gatekeeper/    # 交易前门禁
│   │   ├── dream-tactical-validator/     # 战术验证器
│   │   ├── dream-tactical-executor/      # 战术执行器
│   │   ├── dream-exit-skill-v2/          # 离场技能v2
│   │   ├── dream-risk-position-sizing/   # 风险仓位计算
│   │   ├── dream-intelligence-monitor/   # 情报监控
│   │   ├── dream-regime-detector/        # 市态检测器
│   │   ├── dream-execution-cost-model/   # 执行成本模型
│   │   ├── A7-practice-theory/           # A7实践理论
│   │   └── A8-theory-practice-verification/ # A8理论实践验证
│   │
│   ├── 2-INTELLIGENCE/               # 智能技能（4个）
│   │   ├── dream-bailian-integration/ # 飞书百炼集成
│   │   ├── dream-data-analysis/      # 数据分析
│   │   ├── dream-knowledge/          # 知识管理
│   │   ├── dream-archive-center/     # 档案中心
│   │   └── ...
│   │
│   └── 3-SUPPORT/                    # 支持技能（7+个）
│       ├── boss-secretary/           # 老板秘书
│       ├── dream-operation-director/ # 运营总监
│       ├── dream-cost-control/       # 成本控制
│       ├── resource-efficiency-analyst/ # 资源效率分析师
│       ├── ai-trading-compliance/    # AI交易合规
│       ├── auto-repair/              # 自动修复
│       └── ...
│
├── tests/                            # ★ 测试套件（60+测试文件）
│   ├── architecture/                 # 架构测试
│   ├── workflows/                    # 工作流测试
│   ├── test_memory_l4_*.py           # L4记忆测试（15个）
│   ├── test_qmm_*.py                 # QMM测试（2个）
│   ├── test_trading_*.py             # 交易测试（20个）
│   ├── test_ci_*.py                  # CI脚本测试（13个）
│   ├── test_workflows_memory_*.py    # 记忆工作流测试（7个）
│   ├── e2e_l4_test.py                # L4端到端测试
│   ├── stress_test_l4.py             # L4压力测试
│   └── stress_test_v2.py             # v2压力测试
│
├── artifacts/                        # 产物目录（运行时生成）
│   ├── evolution/                    # 进化产物
│   │   ├── decision/                 # 决策记录
│   │   ├── sandbox/                  # 沙箱结果
│   │   ├── stress/                   # 压力测试
│   │   ├── backtest/                 # 回测结果
│   │   ├── scenario/                 # 场景测试
│   │   ├── audit/                    # 审计记录
│   │   ├── approval/                 # 审批记录
│   │   ├── rollback/                 # 回滚记录
│   │   ├── policy/                   # 策略版本
│   │   ├── scoring/                  # 评分记录
│   │   ├── feedback/                 # 反馈记录
│   │   ├── reports/                  # 报告
│   │   └── dashboard/                # 仪表板数据
│   ├── governance/                   # 治理产物
│   ├── knowledge/                    # 知识产物
│   ├── memory/                       # 记忆产物
│   ├── memory_l4/                    # L4记忆产物
│   │   └── shared_bus/               # 共享内存总线
│   └── trading/                      # 交易产物
│
├── data/                             # 数据目录
│   ├── bcrm2_phase0/                 # BCRM 2.0 Phase 0回测结果
│   ├── okx_sim/                      # OKX模拟数据
│   ├── polling_trader/               # 轮询交易器日志
│   ├── strategy_diversity/           # 策略多样性统计
│   └── training/                     # 训练数据与回测历史
│
├── .github/workflows/                # ★ GitHub Actions工作流（6个）
│   ├── safe-main-merge-gate.yml      # 安全合入门禁
│   ├── trading-ladder-a1-a3.yml      # 交易阶梯A1-A3
│   ├── trading-a4-validation.yml     # 交易A4验证
│   ├── trading-a5-execution.yml      # 交易A5执行
│   ├── trading-a6-intelligence.yml   # 交易A6情报
│   └── trading-a8-governance.yml     # 交易A8治理
│
├── com.dreambuddy.yijing_trading.plist   # launchd交易配置
├── com.dreambuddy.yijing_monitor.plist   # launchd监控配置
├── data_server_fixed.py              # 数据服务器
└── README.md                         # 项目概览
```

---

## 3. 系统索引（文件级）

### 3.1 核心引擎模块

#### 3.1.1 BCRM 1.0 — 矛盾力学推理引擎

| 属性 | 值 |
|------|-----|
| 目录 | `scripts/memory_l4/bcrm/` |
| 核心理论 | 唯物辩证法三规律 + 矛盾论 + 黑格尔正反合 + 易经六十四卦 |
| 核心原理 | 市场沿阻力最小方向运动 = 力的合成 |
| 架构 | 力学引擎（核心）+ 易经引擎（符号解释层） |
| 七步推理 | 矛盾识别→张力量化→质变判定→正反合裁决→螺旋定位→策略分支→实践指令 |

**核心文件：**

| 文件 | 函数/类数 | 职责 | 关键函数/类 |
|------|-----------|------|------------|
| `engine.py` | 1个主类 | BCRM核心引擎入口 | `BCRMEngine` — 七步推理循环 |
| `yijing_engine.py` | — | 易经引擎（卦象解释） | `YijingEngine` — 卦象翻译与解释 |
| `bagua_engine.py` | — | 八卦力学引擎 | `BaguaEngine` — 八卦特征映射 |
| `liangyi_engine.py` | — | 两仪引擎 | `LiangyiEngine` — 阴阳二象 |
| `force_engine.py` | — | ★ 力学引擎（五象力场） | `ForceEngine` — Verlet积分+Langevin+Kalman+转折预警 |
| `ising_phase_detector.py` | — | ★ Ising相变检测 | `IsingPhaseDetector` — 统计力学市场集体状态识别 |
| `tda_early_warning.py` | — | ★ TDA拓扑早期预警 | `TDAEarlyWarning` — 持久同调转折点检测 |
| `scale_engine.py` | — | 规模引擎 | `ScaleEngine`, `ScaleParams` |
| `sixty_four_guas.py` | — | 六十四卦定义 | 卦名、卦象、含义 |
| `walk_forward.py` | — | Walk-Forward回测 | 时间序列交叉验证 |
| `backtest_gate.py` | — | 回测门禁 | 回测准入检查 |
| `guardrail.py` | — | 护栏规则 | 风险边界保护 |
| `knowledge_base.py` | — | 知识库 | 经验知识存储与检索 |
| `memory_adapter.py` | — | 记忆适配器 | L4记忆对接 |
| `a_series_bridge.py` | — | A系列桥接 | A0-A9决策链对接 |
| `output_contract.py` | — | 输出契约 | `BCRMOutput`, `ContradictionState` 等 |
| `_constants.py` | — | 常量定义 | 方向常量、螺旋常量、哲学常量 |

**四维评分（数据层）：**

| 维度 | 权重 | 说明 |
|------|------|------|
| 供需 (supply_demand) | 0.30 | 价格与成交量的供需关系 |
| 技术 (technical) | 0.25 | 技术指标形态 |
| 资金 (capital_flow) | 0.25 | 资金流向与大单动向 |
| 情绪 (market_sentiment) | 0.20 | 市场情绪与超买超卖 |

---

#### 3.1.2 BCRM 2.0 — 辩证ML量化引擎 ★当前实盘主力

| 属性 | 值 |
|------|-----|
| 目录 | `scripts/memory_l4/bcrm2/` |
| 核心理论 | 辩证法正题-反题-合题 + LightGBM + 易经卦象映射 |
| 三层架构 | L1主方向模型(正题) → L2 Meta-Labeling(反题) → L3辩证裁决(合题) |
| 特征总数 | ~400-460（按市值等级配置） |
| 币种 | BTC, ETH, SOL, UNI |
| 基线综合夏普 | 8.20（五角校验+贝叶斯优化后） |

**核心文件：**

| 文件 | 职责 | 关键函数/类 |
|------|------|------------|
| `run_phase0_validation.py` | Phase 0回测主入口 | `main()` — 命令行接口 |
| `walk_forward_backtester.py` | Walk-Forward回测引擎 | `WalkForwardBacktester`, `run()` |
| `portfolio_backtester.py` | 组合回测引擎 | `PortfolioBacktester`, `run()` |
| `dialectical_ml_engine.py` | ★ 辩证ML引擎 | `DialecticalMLEngine` — L1/L2/L3三层 |
| `bagua_feature_engine.py` | ★ 八卦特征引擎 | ~111个特征，8维度 |
| `market_regime.py` | ★ 市态切换引擎 | `MarketRegimeClassifier`, `RegimeParams` |
| `feature_selector.py` | 特征选择模块 | LightGBM重要性 + 相关性去冗余 |
| `data_fetcher.py` | 数据获取服务 | `get_klines()`, `get_bar_value()` |
| `incremental_learner.py` | 增量学习模块 | `IncrementalLearner` |
| `anomaly_detector.py` | 异常检测 | `AnomalyDetector` |
| `triple_barrier_labeler.py` | 三重屏障标签 | 标签生成 |

**特征模块清单（11个）：**

| 模块 | 特征数 | 适用市值 | 核心思想 |
|------|--------|----------|----------|
| 八卦特征 | ~111 | 全部 | 易经八卦映射8维度 |
| 经典经验 | ~30 | 全部 | 传统技术分析 |
| 斐波那契 | ~10 | 全部 | 黄金比例回撤/扩展 |
| 枢纽点 | ~10 | 全部 | 支撑阻力计算 |
| WDH时间维度 | ~45 | 全部 | 量变→质变（周/日/时三屏） |
| 库存周期 | ~55 | 大/中 | 基钦周期四阶段 |
| 市值等级 | ~10 | 全部 | 市值分层与特征配置 |
| 跨资产 | ~33 | 全部 | BTC→altcoin传导 |
| 美林时钟 | ~55 | 全部 | 宏观周期映射 |
| Meta-Labeling V2 | ~25 | 全部 | L2时机判断（与L1互补） |
| RSI情绪 | ~8 | 全部 | RSI情绪指标 |

---

#### 3.1.3 QMM — 量化记忆模型

| 属性 | 值 |
|------|-----|
| 目录 | `scripts/memory_l4/qmm/` |
| 全称 | Quantitative Memory Model |
| 核心功能 | 从历史案例中提取趋势状态、阻力方向、不确定性估计 |
| 三屏体系 | 长期趋势 + 中期结构 + 短期动量 |

**核心文件：**

| 文件 | 职责 | 关键函数/类 |
|------|------|------------|
| `engine.py` | QMM引擎入口 | `run_qmm()`, `run_qmm_with_gate()` |
| `gate.py` | QMM门禁 | `GateRunner`, `GateResult` |
| `triple_screen.py` | 三屏趋势计算 | `compute_triple_screen()`, `ScreenConfig` |
| `trend_velocity.py` | 趋势速度计算 | `compute_trend_velocity()` |
| `mrd.py` | 最小阻力方向 | `compute_mrd()` — 上下阻力估算 |
| `uncertainty.py` | 不确定性计算 | `compute_uncertainty()` |
| `drift.py` | 漂移检测 | 概念漂移监测 |
| `overfitting.py` | 过拟合检测 | 过拟合风险评估 |
| `data_prep.py` | 数据准备 | `prepare_events()` |
| `xgb_predictor.py` | XGBoost预测器 | ML预测集成 |
| `backtest.py` | 回测集成 | 回测验证 |
| `types.py` | 类型定义 | `QMMOutput`, `MDRResult` |

**输出结构：**

```python
QMMOutput(
    trend_state="UP/DOWN/FLAT/UNKNOWN",
    trend_change_point="STABLE/BREAKOUT/REVERSAL",
    mrd_vector={
        "direction": "BULLISH/BEARISH/NEUTRAL",
        "resistance_up: 0-100,      # 上行阻力
        "resistance_down": 0-100,   # 下行阻力
        "confidence": 0-1,
    },
    uncertainty=0-1,
    reason_codes=[...],
    evidence_refs=[...],
    version_triple=(data_version, feature_def_version, qmm_version),
)
```

---

### 3.2 顶层核心脚本

#### 3.2.1 交易执行类

| 文件 | 职责 | 关键类/函数 |
|------|------|-------------|
| `polling_trader.py` | ★ 轮询交易器（P2完整版，BCRM 2.0实盘+易经离场+震荡增强+CBR） | `PollingTrader` — 实盘交易主循环，支持 `use_bcrm2` 引擎切换 |
| `bcrm2_adapter.py` | ★ BCRM 2.0适配器 | `BCRM2Adapter` — 封装训练/推理/缓存，兼容BCRM 1.0接口 |
| `bcrm2_real_verifier.py` | BCRM 2.0实盘验证器 | 真实推理路径五角校验验证 |
| `okx_simulated.py` | OKX模拟客户端 | `OKXSimulatedClient` — 模拟/实盘交易，逐仓模式(isolated)默认 |
| `yijing_exit_system.py` | ★★ 主离场系统（v2架构反转后为主） | `YijingExitSystem` — FORCE_CLOSE/RAISE_TP/HOLD/LOWER_SL/LOWER_TP + VETO机制 |
| `classic_exit_system.py` | 备用离场系统（降级使用） | `ClassicExitSystem` — CLOSE/REDUCE/RAISE_TP/HOLD 四优先级 |
| `ranging_market_enhancer.py` | ★ 震荡市增强层 | `RangingMarketEnhancer` — 5态自适应+布林双信号+动态止损+置信度校准 |
| `a0_contradiction_engine.py` | ★ A0矛盾引擎 | `A0ContradictionEngine` — 七维矛盾张力分析 |
| `cbr_engine.py` | ★ CBR案例检索引擎 | `CBREngine` — 4R循环（Retrieve→Reuse→Revise→Retain）；Python 3.9+ |
| `cbr_adapter.py` | CBR→BCRM2适配层 | `CBRSignalEnhancer` — 三融合策略（cbr_override/cbr_blend/bcrm_only）；Python 3.9+ |
| `trading_utils.py` | 交易工具集 | `PerformanceTracker`, `RiskManager`, `PositionTracker` |
| `screen_martin_bridge.py` | 三屏马丁桥接 | 三屏趋势与马丁策略对接 |

**PollingTrader 集成功能（P2完整版 + BCRM 2.0实盘 + v2架构反转）：**
- P2-1a: 平仓后自动生成 case 存入 L4
- P2-1b: 定期重训 LiangyiEngine + QMM
- P2-2a: 动态仓位（置信度 + 波动率）
- P2-2b: 日最大亏损限制 + 连续亏损熔断
- P2-3: 交易绩效统计 + PnL 持久化
- P2-4: BCRM 矛盾格式修复
- P2-5: 进程守护 + 异常告警 + 日志持久化
- **BCRM 2.0实盘**: `use_bcrm2=True` 切换至辩证ML引擎，通过 `BCRM2Adapter` 适配
- **易经离场主决策**: `YijingExitSystem.evaluate()` 为主离场（FORCE_CLOSE/RAISE_TP/HOLD），无卦象或降级时调用 `ClassicExitSystem`
- **震荡市增强**: `RangingMarketEnhancer` 后置增强 BCRM 信号（5态自适应+布林双信号+动态止损）
- **CBR 案例检索**: `CBRSignalEnhancer` 增强 BCRM 信号（三融合策略）
- **A0矛盾引擎**: 七维矛盾张力分析，方向一致性校准 + 创伤信号检测
- **置信度优化**: 实盘阈值 0.60（基于回测最优）；代码默认 0.55，通过 `confidence_threshold` 参数或环境变量覆写
- **逐仓模式**: 默认 isolated 逐仓，每个币种独立保证金，风险隔离

---

#### 3.2.2 记忆与进化类

| 文件 | 职责 | 关键类/函数 |
|------|------|-------------|
| `pipeline.py` | ★ L4记忆全链路管道 | `run_pipeline()` — case→review→distill→stats |
| `self_evolution_engine.py` | ★ 自进化引擎（三层反思） | `SelfEvolutionEngine` — A8/做梦部/联网 |
| `learning_scheduler.py` | 学习调度器 | `LearningScheduler` — 定时/定量触发重训 |
| `case_registry.py` | Case注册表 | Case创建与管理 |
| `review_engine.py` | 复盘引擎 | 交易复盘与教训提取 |
| `distill_engine.py` | 蒸馏引擎 | 经验蒸馏与知识浓缩 |
| `stats_engine.py` | 统计引擎 | 绩效统计与指标计算 |
| `index_builder.py` | 索引构建器 | 记忆索引构建 |
| `query_similar.py` | 相似查询 | 相似案例检索 |
| `memory_graph.py` | 记忆图谱 | 知识图谱构建与查询 |
| `failure_analyzer.py` | 故障分析器 | 失败案例深度分析 |
| `scenario_extender.py` | 场景扩展器 | 交易场景生成与扩展 |
| `meta_learning_tasks.py` | 元学习任务 | 元学习任务管理 |
| `migration_mapper.py` | 迁移映射器 | 版本迁移映射 |
| `quadrant_migrator.py` | 象限迁移器 | 四象限迁移逻辑 |
| `yijing_trainer.py` | 易经训练器 | 模型训练入口 |

**L4记忆全链路（M0→M5）：**

```
M0_CASE_REGISTERED → M1_REVIEW_COMPLETED → M2_DISTILLED
     → M3_STATS_UPDATED → M4_INDEXED → M5_CANDIDATE_READY
```

**自进化三层反思：**
- Layer 1: A8 理论与实践验证 — 内部批评自循环
- Layer 2: 做梦部（dream-oneirology）— 潜意识视角
- Layer 3: 联网反思（Tavily + GitHub）— 外部成熟经验

---

#### 3.2.3 基础设施类

| 文件 | 职责 | 关键类/函数 |
|------|------|-------------|
| `paths.py` | 全局路径配置 | 所有目录路径定义 |
| `process_guardian.py` | 进程守护 | 异常监控与自动重启 |
| `shared_memory_bus.py` | 共享内存总线 | `publish_shared_memory_event()` |
| `agent_acl.py` | Agent访问控制 | `authorize()` — 权限检查 |
| `a0a9_bridge.py` | A0-A9桥接器 | 决策链阶段数据收集 |
| `a7a8_bridge.py` | A7-A8桥接器 | 审计与理论实践验证对接 |
| `a_research_bridge.py` | 调研桥接器 | 深度研究对接 |
| `ab_bridge.py` | AB桥接器 | A/B系统桥接 |
| `knowledge_bridge.py` | 知识库桥接 | 知识系统对接 |
| `dashboard_renderer.py` | 仪表板渲染 | 数据可视化输出 |
| `yijing_monitor.py` | 易经监控器 | 系统健康监控 + 飞书告警推送 |
| `yijing_feishu_alert.py` | 飞书告警模块 | 飞书告警推送（心跳/风控/模型/持仓/系统） |
| `tavily_macro.py` | Tavily宏观搜索 | 联网信息获取 |
| `batch_backtest.py` | 批量回测 | 多参数回测批量执行 |

---

### 3.3 CI/CD 模块

| 脚本 | 职责 | 对应Workflow |
|------|------|-------------|
| `safe_main_merge_gate.py` | 安全合入门禁 | safe-main-merge-gate.yml |
| `architecture_sync_guard.py` | 架构同步守护 | — |
| `branch_lifecycle_bot.py` | 分支生命周期自动化 | — |
| `evolution_decision_gate.py` | 进化决策门禁 | — |
| `evolution_governance_report.py` | 进化治理报告 | — |
| `evolution_candidate_priority_score.py` | 进化候选优先级评分 | — |
| `evolution_policy_regression_matrix.py` | 进化策略回归矩阵 | — |
| `evolution_version_compare_dashboard.py` | 进化版本对比仪表板 | — |
| `constraint_release_snapshot.py` | 约束发布快照 | — |
| `constraint_rollback.py` | 约束回滚 | — |
| `post_merge_audit.py` | 合并后审计 | — |
| `remote_repo_guard.py` | 远程仓库守护 | — |
| `review_policy_guard.py` | 评审策略守护 | — |
| `trading_traceability_guard.py` | 交易可追溯守护 | — |

**6个GitHub Actions工作流：**

| Workflow | 触发时机 | 职责 |
|----------|----------|------|
| `safe-main-merge-gate.yml` | PR合入前 | 代码质量与安全检查 |
| `trading-ladder-a1-a3.yml` | 推送 | 交易阶梯A1-A3阶段 |
| `trading-a4-validation.yml` | 推送 | A4战术验证 |
| `trading-a5-execution.yml` | 推送 | A5决策执行 |
| `trading-a6-intelligence.yml` | 定时 | A6情报监控 |
| `trading-a8-governance.yml` | 定时 | A8治理审计 |

---

### 3.4 约束层体系

| 目录 | 文档数 | 职责 | 核心文档 |
|------|--------|------|----------|
| `constitution/` | 1 | 系统最高约束与原则 | README |
| `system-index/` | 2 | 架构索引、组件边界 | engineering-architecture.md |
| `workflows-spec/` | 30+ | 工作流规范与契约 | trading.md, evolution.md, memory.md |
| `qmm/` | 9 | QMM四阶段规划与规范 | phase-1~4.md, architecture.md |
| `faq/` | 1 | 常见问题与外部问答 | OKX_FAQ.md |
| `releases/` | 3 | 约束版本快照 | v0.1.json, v0.1.1.json, v0.1.2.json |

---

### 3.5 技能体系

| 分类 | 数量 | 目录 | 代表技能 |
|------|------|------|----------|
| **0-CORE** | 10+ | `skills/0-CORE/` | memory-manager, dream-governance-manager, architecture-sync-guard |
| **1-TRADE** | 16 | `skills/1-TRADE/` | dream-contradiction-theory, dream-first-principles, dream-exit-skill-v2 |
| **2-INTELLIGENCE** | 4+ | `skills/2-INTELLIGENCE/` | dream-bailian-integration, dream-data-analysis |
| **3-SUPPORT** | 7+ | `skills/3-SUPPORT/` | boss-secretary, dream-operation-director, ai-trading-compliance |
| **4-GENERIC** | — | `skills/4-GENERIC/` | 通用技能 |

---

### 3.6 测试体系

| 测试类别 | 测试文件数 | 测试内容 |
|----------|-----------|----------|
| L4记忆测试 | ~15 | case注册、蒸馏、索引、查询、迁移等 |
| QMM测试 | 2 | 门禁回归、压力场景 |
| 交易测试 | ~20 | 协议执行、状态机、传输路由、Redis等 |
| CI脚本测试 | ~13 | 各CI脚本功能验证 |
| 记忆工作流测试 | ~7 | 记忆引擎核心功能 |
| E2E测试 | 3 | 端到端集成、压力测试 |

**测试命令：**

```bash
# 全部测试
cd 11-易经推理系统 && python -m pytest tests/ -v

# 按类别运行
python -m pytest tests/test_memory_l4_*.py -v      # L4记忆
python -m pytest tests/test_qmm_*.py -v            # QMM
python -m pytest tests/test_trading_*.py -v        # 交易
python -m pytest tests/test_ci_*.py -v             # CI脚本
python -m pytest tests/test_workflows_memory_*.py -v  # 记忆工作流
```

---

## 4. 系统间依赖关系

### 4.1 内部模块依赖

```
polling_trader.py (顶层交易器, BCRM 2.0实盘 + v2架构反转)
    ├── bcrm2_adapter.py → BCRM2Adapter      ← BCRM 2.0适配(训练/推理/缓存)
    │   └── bcrm2/dialectical_ml_engine.py    ← 辩证ML引擎(L1/L2/L3)
    ├── bcrm/engine.py → BCRMEngine           ← BCRM 1.0矛盾推理(Fallback)
    ├── bcrm/bagua_engine.py → BaguaEngine    ← 八卦力学
    ├── bcrm2/market_regime.py                ← 市态切换
    ├── qmm/engine.py → run_qmm()             ← QMM量化记忆
    ├── yijing_exit_system.py → YijingExitSystem ← ★ 主离场(FORCE_CLOSE/RAISE_TP/HOLD)
    ├── classic_exit_system.py → ClassicExitSystem ← 备用离场(降级时调用)
    ├── ranging_market_enhancer.py            ← 震荡市增强层(5态自适应+布林双信号)
    ├── a0_contradiction_engine.py            ← A0矛盾引擎(七维矛盾张力)
    ├── cbr_engine.py / cbr_adapter.py        ← CBR案例检索增强(4R循环+三融合)
    ├── okx_simulated.py → OKXSimulatedClient ← 交易执行
    ├── trading_utils.py                       ← 绩效/风控/持仓
    ├── learning_scheduler.py                  ← 学习调度
    ├── process_guardian.py                    ← 进程守护
    ├── knowledge_bridge.py                    ← 知识库对接
    └── bcrm2/incremental_learner.py          ← 增量学习

pipeline.py (L4记忆管道)
    ├── case_registry.py                      ← Case注册
    ├── a0a9_bridge.py                        ← A0-A9数据收集
    ├── review_engine.py                      ← 复盘
    ├── distill_engine.py                     ← 蒸馏
    ├── stats_engine.py                       ← 统计
    └── index_builder.py                      ← 索引

self_evolution_engine.py (自进化)
    ├── A8技能 (6-TRADING/skills/)            ← 理论实践验证
    ├── dream-oneirology技能                   ← 做梦部潜意识
    ├── tavily_macro.py                        ← 联网反思
    └── bcrm/walk_forward.py                   ← 回测验证
```

### 4.2 外部系统依赖

```
易经推理系统
    ├── 6-TRADING/                            ← A系列技能、策略研究脚本
    ├── 10-经典指标系统/                       ← 离场系统参考
    ├── 12-三屏趋势系统/                       ← 三屏趋势参考
    ├── OKX API                                ← 行情与交易接口
    ├── 飞书/百炼                              ← 通知、知识、LLM
    └── Tavily API                             ← 联网搜索（自进化）
```

### 4.3 数据流

#### 实盘交易数据流

```
OKX API (K线)
    ↓
data_fetcher.py / okx_simulated.py
    ↓
特征工程 (bcrm2/*_features.py)
    ├── 八卦特征
    ├── 经典经验
    ├── WDH时间维度
    └── ...
    ↓
BCRM2Adapter (bcrm2_adapter.py)
    ├── 模型缓存检查 → 命中则直接推理
    └── 未命中 → DialecticalMLEngine 训练 (L1→L2→L3)
    ↓
DialecticalMLEngine (L1→L2→L3) → 置信度 + 方向
    ↓
A0矛盾分析 → 方向一致性校准 + 创伤信号检测
    ↓
五角校验 v4 (TriangleVerifier) → 风险评分 + 仓位/杠杆/止盈/止损双向风控
    ↓
MarketRegimeClassifier (8种市态) → 仓位因子
    ↓
震荡市增强层 (RangingMarketEnhancer) → 5态自适应+布林双信号+动态止损
    ↓
信号生成 (置信度阈值 0.60) + 仓位计算
    ↓
CBR 案例检索增强 (CBRSignalEnhancer) → cbr_override/cbr_blend/bcrm_only
    ↓
RiskManager (日亏损/连续亏损熔断)
    ↓
OKX下单执行
    ↓
持仓跟踪 → YijingExitSystem 主离场决策 (FORCE_CLOSE/RAISE_TP/HOLD)
    ├── 降级路径: NO_INTERVENE → 调用 ClassicExitSystem
    ├── 备用路径: 无卦象 → 直接调用 ClassicExitSystem (P0→P1→P2→P3)
    └── DreamOS路径: YijingExitAdapter → ExitModuleSelector 按场景择优 (详见 §9.8)
    ↓
交易记录 → PerformanceTracker
    ↓
Case生成 → save_case_to_l4()
    ↓
L4记忆管道 (pipeline.py)
    ↓
IncrementalLearner 检查触发再训练?
    ↓
(数据不足时) Fallback → BCRM 1.0 矛盾力学引擎
```

#### 记忆沉淀数据流

```
TradeCase (M0)
    ↓
A0-A9阶段数据收集 (a0a9_bridge.py)
    ↓
复盘引擎 (review_engine.py) → M1_REVIEW_COMPLETED
    ↓
蒸馏引擎 (distill_engine.py) → M2_DISTILLED
    ↓
统计引擎 (stats_engine.py) → M3_STATS_UPDATED
    ↓
索引构建器 (index_builder.py) → M4_INDEXED
    ↓
候选就绪 → M5_CANDIDATE_READY
    ↓
进化引擎评估 → 升级为约束?
```

---

## 5. 关键接口速查

### 5.1 引擎接口

| 模块 | 文件 | 核心类/函数 | 说明 |
|------|------|------------|------|
| BCRM 1.0 | `bcrm/engine.py` | `BCRMEngine` | 矛盾力学推理入口（Fallback） |
| BCRM 2.0 | `bcrm2/dialectical_ml_engine.py` | `DialecticalMLEngine` | 辩证ML推理入口 |
| BCRM 2.0适配 | `bcrm2_adapter.py` | `BCRM2Adapter` | 实盘适配层（训练/推理/缓存） |
| QMM | `qmm/engine.py` | `run_qmm()`, `run_qmm_with_gate()` | 量化记忆查询 |
| 市态检测 | `bcrm2/market_regime.py` | `MarketRegimeClassifier.fit()/predict_regime_names()` | 当前市态分类 |
| 三屏趋势 | `qmm/triple_screen.py` | `compute_triple_screen()` | 三屏趋势对齐 |

### 5.2 交易接口

| 模块 | 文件 | 核心类/函数 | 说明 |
|------|------|------------|------|
| 轮询交易 | `polling_trader.py` | `PollingTrader.run()` | 主交易循环（BCRM 2.0实盘+易经离场+震荡增强+CBR） |
| OKX客户端 | `okx_simulated.py` | `OKXSimulatedClient` | 模拟/实盘交易（逐仓模式默认） |
| 离场系统（主） | `yijing_exit_system.py` | `YijingExitSystem.evaluate()` | 主离场决策（FORCE_CLOSE/RAISE_TP/HOLD，v2架构反转后为主） |
| 离场系统（备用） | `classic_exit_system.py` | `ClassicExitSystem.evaluate_full()` | 备用离场决策（CLOSE/REDUCE/RAISE_TP/HOLD，降级时调用） |
| 震荡市增强 | `ranging_market_enhancer.py` | `RangingMarketEnhancer.enhance()` | BCRM信号后置增强（5态自适应+布林双信号+动态止损） |
| CBR 案例检索 | `cbr_adapter.py` | `CBRSignalEnhancer.enhance()` | CBR增强BCRM信号（三融合策略） |
| 风控 | `trading_utils.py` | `RiskManager` | 风险控制（含动态仓位计算） |
| 绩效 | `trading_utils.py` | `PerformanceTracker` | 绩效统计 |
| 监控适配 | `15-监控告警系统/adapters/yijing_adapter.py` | `YijingAdapter.check_health()` | 系统健康检查（进程/交易/持仓/模型/余额） |

### 5.3 记忆接口

| 模块 | 文件 | 核心类/函数 | 说明 |
|------|------|------------|------|
| L4管道 | `pipeline.py` | `run_pipeline(episode_path)` | 全链路记忆沉淀 |
| Case注册 | `case_registry.py` | `create_case_from_episode_file()` | Case创建 |
| 复盘 | `review_engine.py` | `review_trade()` | 交易复盘 |
| 蒸馏 | `distill_engine.py` | `distill_lesson()` | 经验蒸馏 |
| 相似查询 | `query_similar.py` | `find_similar_cases()` | 相似案例检索 |
| 共享总线 | `shared_memory_bus.py` | `publish_shared_memory_event()` | 事件发布 |

### 5.4 进化接口

| 模块 | 文件 | 核心类/函数 | 说明 |
|------|------|------------|------|
| 自进化 | `self_evolution_engine.py` | `SelfEvolutionEngine` | 三层反思闭环 |
| 学习调度 | `learning_scheduler.py` | `LearningScheduler` | 重训调度 |
| 增量学习 | `bcrm2/incremental_learner.py` | `IncrementalLearner` | 增量训练 |

---

## 6. 配置管理

### 6.1 配置文件位置

| 系统 | 配置文件 | 关键配置项 |
|------|----------|------------|
| BCRM 2.0基线 | `configs/baseline_config.json` | 币种、周期、折数、阈值、模块开关 |
| 轮询交易器 | 构造参数 + 环境变量 | interval, coins, confidence_threshold(默认0.55/实盘0.60), max_positions(10), use_bcrm2(True) |
| OKX模拟 | `data/okx_sim/config.json` | API密钥、模拟模式、td_mode(isolated/cross)、默认杠杆 |
| L4路径 | `scripts/memory_l4/paths.py` | 所有目录路径 |
| QMM | `qmm/paths.py` + 代码默认值 | QMM数据路径 |
| 约束版本 | `constraints/releases/` | v0.1, v0.1.1, v0.1.2 |

### 6.2 BCRM 2.0 基线配置

**文件**: [configs/baseline_config.json](../configs/baseline_config.json)

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 币种 | BTC, ETH, SOL, UNI | 4个币种 |
| K线周期 | 1H | 1小时K线 |
| 数据量 | 6000根 | 约8个月 |
| Walk-Forward折数 | 5 | 80%训练/20%验证 |
| 置信度阈值 | 0.60 | 实盘优化值（回测最优）；代码默认 0.55，实盘通过配置覆写 |
| 止盈 | 3.0x ATR | 动态止盈 |
| 止损 | 2.0x ATR | 动态止损 |
| 最大持仓 | 60根K线 | 约2.5天 |
| 市态切换 | ✅ 启用 | 8种市态自适应 |
| 仓位管理 | ✅ 启用 | position_factor调整阈值 |
| auto_mcap | ✅ 启用 | 按市值等级配置特征 |
| 特征选择 | ✅ 启用 | LightGBM重要性+相关性去冗余 |
| 组合回测 | ✅ 启用 | 大40%/中35%/小25% |
| 美林时钟 | ❌ 禁用 | 实验中 |
| Meta-Labeling | ❌ 禁用 | 调试中 |

---

## 7. 部署与运维

### 7.1 进程管理

| 进程 | 入口文件 | 调度方式 | plist文件 |
|------|----------|----------|-----------|
| 易经交易 | `scripts/memory_l4/polling_trader.py` | launchd | `com.dreambuddy.yijing_trading.plist` |
| 易经监控 | `scripts/memory_l4/yijing_monitor.py` | launchd | `com.dreambuddy.yijing_monitor.plist` |
| 自进化 | `scripts/memory_l4/self_evolution_engine.py` | 手动触发 | — |
| BCRM 2.0回测 | `scripts/memory_l4/bcrm2/run_phase0_validation.py` | 手动运行 | — |
| L4管道 | `scripts/memory_l4/pipeline.py` | 事件触发 | — |

### 7.2 日志与数据位置

| 类型 | 位置 | 说明 |
|------|------|------|
| 交易日志 | `data/polling_trader/trader_YYYYMMDD.jsonl` | 每日交易记录 |
| OKX模拟审计 | `data/okx_sim/sim_trades_audit.jsonl` | 模拟交易审计 |
| BCRM 2.0回测 | `data/bcrm2_phase0/` | 回测报告与交易明细 |
| L4记忆产物 | `artifacts/memory_l4/` | Case、蒸馏、索引 |
| 进化产物 | `artifacts/evolution/` | 决策、沙箱、回滚、审批 |
| 共享总线 | `artifacts/memory_l4/shared_bus/events.jsonl` | 跨Agent事件 |
| 训练数据 | `data/training/` | 训练与回测历史 |

### 7.3 启动流程

```bash
# 安装launchd服务
cd 11-易经推理系统
bash scripts/memory_l4/install_trading.sh

# 启动交易
bash scripts/memory_l4/start_trading.sh

# 手动运行一次轮询
python -m scripts.memory_l4.polling_trader --once --coins BTC,ETH

# 运行BCRM 2.0回测（组合）
cd scripts
python -m memory_l4.bcrm2.run_phase0_validation \
  --symbols BTC,ETH,SOL,UNI --timeframe 1H \
  --n-folds 5 --max-bars 6000 --feature-selection --portfolio

# 触发L4记忆管道
python -m scripts.memory_l4.pipeline <episode_path>

# 运行全部测试
cd 11-易经推理系统 && python -m pytest tests/ -v
```

---

## 8. 性能基准

### 8.1 BCRM 2.0 基线回测（6000根1H K线）

**配置**: 市态切换 + auto_mcap + 特征选择 + 组合回测

#### 单币种表现

| 币种 | 市值 | 特征数 | 交易数 | 胜率 | 总收益 | 最大回撤 | 盈亏比 | 夏普 |
|------|------|--------|--------|------|--------|----------|--------|------|
| BTC | 大 | 429 | 43 | 81.4% | 68.52% | 4.58% | 5.14 | 10.67 |
| ETH | 大 | 463 | 52 | 71.2% | 53.79% | 14.30% | 2.37 | 5.77 |
| SOL | 中 | 463 | 65 | 75.4% | 92.92% | 11.20% | 3.02 | 7.88 |
| UNI | 小 | 402 | 92 | 60.9% | 119.48% | 33.45% | 2.12 | 5.62 |

#### 组合层指标（BTC/ETH/SOL 6000bars/5folds）

| 指标 | Baseline | 五角校验v4风控版 | Delta |
|------|----------|-----------------|-------|
| 平均总收益 | 135.31% | 139.40% | +4.09% |
| 平均夏普 | 10.16 | 10.20 | +0.4% |
| 平均最大回撤 | 10.12% | 10.34% | +0.22% |
| 风控触发率 | — | 22.8% (94/412笔) | — |

> 注：v4 风险评分风控版四项验证标准全部通过（夏普不拖累、回撤不恶化、风控触发、收益提升）。v1/v2 方向投票+贝叶斯优化方案已废弃。

---

## 9. 技术债务索引

| ID | 债务项 | 严重程度 | 说明 |
|----|--------|----------|------|
| D01 | BCRM 1.0与2.0双轨运行 | 低 | BCRM 2.0已切换为实盘主力，1.0作为Fallback保留 |
| D02 | QMM与BCRM集成深度不足 | 中 | QMM更多作为独立模块 |
| D03 | 约束层文档多但代码引用少 | 中 | 约束与实现存在漂移风险 |
| D04 | 测试覆盖不均衡 | 中 | CI/交易测试多，BCRM引擎测试少 |
| D05 | 配置分散 | 中 | 配置在代码、JSON、环境变量中多处定义 |
| D06 | 技能系统与代码不同步 | 低 | skills/ 与 scripts/ 存在功能重叠 |
| D07 | 文档版本碎片化 | 低 | constraints/releases/ 有v0.1~v0.1.2但代码未严格版本化 |
| D08 | 缺少统一API层 | 低 | 各模块直接调用，缺少API网关 |
| D09 | L2 Meta-Labeling训练不稳定 | 中 | 部分币种L2训练失败被跳过，不影响L1主推理 |
| D10 | 小币种数据不足回退 | 低 | BNB等小币种K线数据不足时自动回退BCRM 1.0 |
| D11 | 逐仓模式与全仓模式切换测试 | 低 | 已默认逐仓，全仓模式保留但未做全面回归测试 |

---

## 10. 快速导航

### 10.1 按系统导航

| 系统 | 工程索引 | 技术文档 | 核心代码 |
|------|----------|----------|----------|
| BCRM 2.0 | 本文件§3.1.2 | [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | [dialectical_ml_engine.py](../scripts/memory_l4/bcrm2/dialectical_ml_engine.py) |
| BCRM 1.0 | 本文件§3.1.1 | （内嵌于代码） | [engine.py](../scripts/memory_l4/bcrm/engine.py) |
| QMM | 本文件§3.1.3 | `constraints/qmm/architecture.md` | [engine.py](../scripts/memory_l4/qmm/engine.py) |
| 轮询交易 | 本文件§3.2.1 | — | [polling_trader.py](../scripts/memory_l4/polling_trader.py) |
| L4记忆 | 本文件§3.2.2 | `constraints/workflows-spec/l4-memory/` | [pipeline.py](../scripts/memory_l4/pipeline.py) |
| CI/CD | 本文件§3.3 | — | [scripts/ci/](../scripts/ci/) |
| 约束层 | 本文件§3.4 | `constraints/system-index/engineering-architecture.md` | [constraints/](../constraints/) |

### 10.2 按功能导航

| 功能 | 代码位置 |
|------|----------|
| BCRM 2.0实盘适配 | [bcrm2_adapter.py](../scripts/memory_l4/bcrm2_adapter.py) |
| 八卦特征 | [bcrm2/bagua_feature_engine.py](../scripts/memory_l4/bcrm2/bagua_feature_engine.py) |
| 辩证ML | [bcrm2/dialectical_ml_engine.py](../scripts/memory_l4/bcrm2/dialectical_ml_engine.py) |
| 市态切换 | [bcrm2/market_regime.py](../scripts/memory_l4/bcrm2/market_regime.py) |
| 特征选择 | [bcrm2/feature_selector.py](../scripts/memory_l4/bcrm2/feature_selector.py) |
| 增量学习 | [bcrm2/incremental_learner.py](../scripts/memory_l4/bcrm2/incremental_learner.py) |
| 主离场决策 | [yijing_exit_system.py](../scripts/memory_l4/yijing_exit_system.py) |
| 备用离场决策 | [classic_exit_system.py](../scripts/memory_l4/classic_exit_system.py) |
| 震荡市增强 | [ranging_market_enhancer.py](../scripts/memory_l4/ranging_market_enhancer.py) |
| CBR 案例检索 | [cbr_engine.py](../scripts/memory_l4/cbr_engine.py) |
| CBR 信号增强 | [cbr_adapter.py](../scripts/memory_l4/cbr_adapter.py) |
| A0 矛盾引擎 | [a0_contradiction_engine.py](../scripts/memory_l4/a0_contradiction_engine.py) |
| 五角校验 | [triangle_verifier.py](../scripts/memory_l4/triangle_verifier.py) |
| 离场分析 | [analyze_eth_exit.py](../scripts/memory_l4/analyze_eth_exit.py) |
| 置信度优化 | [confidence_optimization.py](../scripts/memory_l4/confidence_optimization.py) |
| 自进化 | [self_evolution_engine.py](../scripts/memory_l4/self_evolution_engine.py) |
| 共享内存总线 | [shared_memory_bus.py](../scripts/memory_l4/shared_memory_bus.py) |
| 进程守护 | [process_guardian.py](../scripts/memory_l4/process_guardian.py) |

### 10.3 按角色导航

| 角色 | 推荐阅读路径 |
|------|-------------|
| **新开发者** | 本文件 → README.md → TECHNICAL_DESIGN.md → constraints/system-index/engineering-architecture.md |
| **策略开发者** | 本文件§3.1 → bcrm2/ → TECHNICAL_DESIGN.md → 运行回测验证 |
| **运维人员** | 本文件§7 → 检查launchd状态 → 查看data/日志 → 监控告警 |
| **研究人员** | 本文件§3.1.2+§3.1.3 → BCRM理论 → QMM → 回测验证 → 自进化 |
| **治理/架构** | constraints/ → scripts/ci/ → .github/workflows/ → 进化闭环 |

---

## 11. 变更日志

| 日期 | 版本 | 变更内容 | 变更人 |
|------|------|----------|--------|
| 2026-08-05 | v4.0 | **五角校验 v4 风险评分风控版**：①§1.3 核心特性从"五源交叉验证"更新为"五源风险信号综合评分→双向风控"；②§4.1.1c 五角校验架构重写为 v4（风险评分分档+风险注意力+仓位/杠杆/止盈/止损双向调控+v3双预警底线）；③§8.1 性能基线更新为 BTC/ETH/SOL 6000bars/5folds 回测（夏普10.16→10.20、回撤10.12%→10.34%、收益135.31%→139.40%）；④推理链更新五角校验输出字段；⑤v1/v2 方向投票+贝叶斯优化方案废弃；版本号 v3.x→v4.0 | DreamBuddy v2 |
| 2026-07-25 | v2.6 | **P1修复与系统增强**：①§0.3 运行入口新增 `inspect.py`（系统诊断）和 `multi_scenario_validation.py`（多场景验证）；②§0.3 核心链路新增 `InspectReport` 系统诊断环节；③§0.3 配置与状态新增 BCRM 2.0 模型目录 `scripts/data/bcrm2_models/{SYMBOL}_{TIMEFRAME}/`；④§1.2 技术栈补充 ripser+persim（TDA拓扑）、Optuna（贝叶斯优化）；⑤币种规模从 4 扩展至 27；⑥五角校验第五源 TDA 拓扑检测恢复可用（ripser已安装）；版本号 v2.5→v2.6 | DreamBuddy v2 |
| 2026-07-24 | v2.5 | **文档与代码同步更新**：①§2.1 目录树补全 11 个缺失文件（`kalman_filter.py`、`yijing_exit_system.py`、`ranging_market_enhancer.py`、`a0_contradiction_engine.py`、`a7_practice_gate.py`、`bcrm2_real_verifier.py`、`cbr_engine.py`/`cbr_similarity.py`/`cbr_sharded_retriever.py`/`cbr_adapter.py`）；②§0.3/§3.2.1/§4.1/§4.3/§5.2 反映离场架构反转（`YijingExitSystem` 为主，`ClassicExitSystem` 降为备用）；③§3.2.1 PollingTrader 集成功能补全易经离场+震荡增强+CBR+A0矛盾引擎；④§4.3 数据流补全 A0/五角校验/震荡增强/CBR/易经离场环节；⑤§8.1 性能基准统一 Phase 0 基线(7.45)与五角校验+贝叶斯优化后(8.20)两套数值，消除自相矛盾；⑥§10.2 功能导航补全主离场/震荡增强/CBR/A0/五角校验入口；版本号 v2.4→v2.5 | DreamBuddy v2 |
| 2026-07-15 | v2.3 | **保证金计算逻辑修正**：`polling_trader.py::_open_position()` 使用可用余额（而非总权益）计算仓位；新增统一监控适配器入口（`15-监控告警系统/adapters/yijing_adapter.py`）；BCRM 2.0实盘验证通过（BTC/ETH开仓成功） | DreamBuddy v2 |
| 2026-07-15 | v2.2 | 仓位模式从全仓(cross)切换为逐仓(isolated)；okx_simulated.py默认td_mode=isolated；polling_trader.py支持逐仓/全仓保证金检查；新增D11技术债务 | DreamBuddy v2 |
| 2026-07-14 | v2.1 | BCRM 2.0实盘切换：新增BCRM2Adapter适配器、离场分析工具、置信度优化脚本；更新数据流（含Fallback机制）；置信度阈值0.60；新增技术债务D09/D10 | DreamBuddy v2 |
| 2026-07-13 | v2.0 | 重建为完整系统级工程索引，覆盖BCRM 1.0/2.0、QMM、L4记忆、CI/CD、约束层、技能体系、测试体系 | DreamBuddy v2 |
| （历史） | v1.0 | 初始版本，仅覆盖BCRM 2.0模块 | BCRM 2.0团队 |

---

_维护原则：本文件是易经推理系统的工程入口索引，任何模块变更影响入口、依赖关系、配置层级的，必须同步更新本文件。_
