# 23-四层闭环自进化交易架构 — 变更日志

> **版本**: v1.0 | **更新日期**: 2026-09-07
> **定位**: 模块级变更日志，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md)

---

## [v1.0] - 2026-09-07

### 新增 — 文档四件套

- **ENGINEERING_INDEX.md** v1.0：模块工程索引（目录地图/文件清单/核心流程/配置参数/测试体系）
- **TECHNICAL_DESIGN.md** v1.0：技术设计文档（四层架构/双起点触发/三层仓位/SL-TP兜底/数据管线/权重体系/稳定性证明）
- **API_SPEC.md** v1.0：接口规格文档（13个核心类/函数的完整签名+输入输出字段表）
- **CHANGELOG.md** v1.0：本文件

### 新增 — 高频进化增强（2026-09-06）

#### 双起点触发
- `engines/reflection_scanner.py` 新增 ReflectionScanner（反思学习扫描器）
  - 从系统级交易索引库（TradeIndexBuilder）统计币种历史胜率
  - `reflection_ri` 映射: win_rate 0.5→0.50, 0.6→0.56, 0.7→0.62, 1.0→0.80
  - 样本量折扣: n=1→0.72, n=2→0.85, n≥3→1.0
- `engines/kline_event_handler.py` 双起点聚合: `ri = max(ripple_ri, reflection_ri)`
  - `signal_source` 字段标记哪个起点触发

#### 三层仓位分级
- `engines/kline_event_handler.py` 三层分级替代固定 u=0.1:
  - probe(ri≥0.40, ×0.4) / standard(ri≥0.55, ×0.7) / trend(ri≥0.70, ×1.0)
  - Regime乘数: STRONG_TREND_BULL ×1.20, RANGING ×0.80, TREND_BEAR ×0.50 等

#### SL/TP 兜底
- `polling_trader.py` `_evolution_build_position` 建仓后立即设置止损止盈:
  - probe: SL=5%, TP=10%
  - standard: SL=3%, TP=6%
  - trend: SL=2%, TP=4%
  - Regime调整: ranging→SL×1.3/TP×0.8, trend_up→TP×1.2

#### 系统级交易索引库
- `engines/trade_index_builder.py` 新增 TradeIndexBuilder:
  - 自动发现JSONL+SQLite交易记录源（扫描深度5层）
  - 统一字段口径，按trade_id去重
  - 索引库: `.workbuddy/trade_index/all_trades_index.jsonl`
  - 验证结果: 83笔/25币/4源

#### 50币种池 + 美股代币配额
- `adapters/coin_scanner.py` 增强:
  - US_STOCK_COINS白名单130+支美股
  - US_STOCK_RATIO=0.5 配额
  - 美股成交量门槛300K USDT（加密5M USDT）
- `polling_trader.py` 币种池合并: 基础24 + 扫描50 = 50币

### 新增 — 数据管线打通（2026-09-05）

- `adapters/data_pipeline.py` DataPipelineAdapter 统一数据管线装配器
- `adapters/okx_market.py` OKXMarketAdapter（K线+Ticker+持仓）
- `adapters/data_center.py` DataCenterAdapter（data_center.db衍生品）
- `adapters/sentiment_bridge.py` SentimentBridge（SentimentEngine桥接）
- `adapters/ess_provider.py` ESSDirectionProvider（策略基因ESS方向）
- `adapters/subsystem_bridge.py` SubSystemBridge（子交易系统信号）
- `adapters/cognitive_bridge.py` CognitiveBridge（Phase3预留接口）
- `adapters/capital_rotation.py` CapitalRotationAdapter（资金轮动检测）
- `adapters/traditional_finance.py` TraditionalFinanceBridge（Regime/Kelly/Vol）
- `adapters/ripple_provider.py` RippleDataProvider（涟漪关联币数据）
- `adapters/narrative_adapter.py` NarrativeAdapter（叙事标签适配）
- `adapters/path_library.py` PathLibrary（最优路径库）

### 新增 — FTC金融思维链层（2026-09-06）

- `adapters/ftc_orchestrator.py` FTCOrchestrator（FTC编排器）
- `adapters/ftc_executor.py` FTC执行器
- `adapters/ftc_schema.py` FTC数据模式
- `adapters/ftc_similarity.py` FTC相似度
- `adapters/ftc_combiner.py` FTC组合器
- `adapters/ftc_gene_innovation.py` FTC基因创新
- `adapters/ftc_evolution_bridge.py` FTC进化桥接
- `adapters/ftc_backtest.py` FTC回测

### 已有功能（基线）

- **L1 ResistanceVector**: 5维阻力向量计算（R_up/R_down/R_smooth/R_flow/R_reflexivity）
- **Level0 路径代价**: d* = argmin 代价方向
- **L2 StrategyGene**: 策略基因库 + ESS排序（28条件 + 16动作 + 组合库）
- **L3 ShadowRLTracker**: 影子RL样本追踪（Phase3激活gmax变异）
- **L4 BellmanVTracker**: V(s) TD(0)时序差分更新
- **RippleEngine**: 涟漪扩散引擎（龙头检测 + R1/R2/R3三层扩散）
- **ReflectionEngine**: 后验反思引擎（CS一致性 + 四维奖惩表）
- **TightCouplingOrchestrator**: 紧耦合7步闭环编排器
- **TradeSettlementBridge**: 平仓反思桥接器
- **Modifiers**: 三修饰子（情绪/资金流/叙事）
- **EvolutionPipeline**: 四层闭环pipeline编排器
- **Weights**: 权威权重唯一源（ESS 4:4:2, R_REFL 4:3:3, CS 0.4:0.3:0.3, CM 4:3:3）

### 已知问题

- **`_mode_cache` 属性错误**: ETH/SOL 仓位（在SL/TP代码前开的仓）在SLTP sync时触发 `'PollingTrader' object has no attribute '_mode_cache'`。这是pre-existing bug，`_mode_cache` 在 `__init__` L912 初始化，但evolution仓位的SLTP sync路径可能跳过init。待修复。

---

**文档版本**: v1.0
**最后更新**: 2026-09-07
