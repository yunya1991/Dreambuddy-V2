# Dreambuddy OS 变更记录

> **最后更新**：2026-09-30

---

## v1.0 (2026-09-30)

- 初始文档创建（从代码提取真实信息）
- 补齐 README.md、API_SPEC.md、CHANGELOG.md

---

## 历史变更（从代码提取）

### 预算管理体系

- 全局预算管理器 `GlobalBudgetManager` 实现三档预算：lean / standard / full
- 层间预算分配：S 10% / A 5% / C 75% / G 5% / E 5%
- 预算健康度五级：healthy / warning / tight / critical / exhausted
- 降级策略：减少可选节点 → 纯规则模式 → 经典指标系统（零 Token）

### 自动交易（AutoTrader）

- 完整自动化链路：定时触发 → 市场扫描 → A1-A5 分析 → G1 风控 → A5 执行 → 交易所下单 → A9 离场监控
- 支持 dry_run 模拟交易模式
- 支持 Aster 和 OKX 双交易所
- 动态杠杆 `calc_dynamic_leverage()`：置信度 0.4→1x，0.6→3x，0.8→5x
- 降级路径告警：连续 3 次降级暂停该 symbol（`FALLBACK_SUSPEND_THRESHOLD = 3`）
- L4 统一案例库接入：开仓注册 TradeCase，离场回填实际结果

### 动态编排器（DynamicOrchestrator）

- 两级优化：Level 1 L4 粗筛 + Level 2 回测精调
- 整合策略：两者一致→高置信；仅一方→中等；都不支持→不启用
- 更新 `ChainSpec.scenario_nodes`，替换硬编码映射

### 回测引擎（DreamOSBacktester）

- 端到端链路：数据加载 → 指标计算 → 场景分类 → 编排选择 → TradingAgent(A0/A7) → 模拟交易 → 评估
- `WINDOW_SIZE = 48`（前 48 根 K 线计算指标）
- `STEP = 4`（每隔 4 根采样）
- 评估指标：win_rate / total_return / sharpe_ratio / max_drawdown / a0_alignment_rate / a7_pass_rate

### 适配器框架

- `BaseAdapter` 基类 + `AdapterRegistry` 多适配器分发
- 支持 `SkillAdapter` / `APIAdapter` / `FunctionAdapter`
- 将外部能力（SKILL / API / 本地函数）统一包装为 Node

### 节点清单（capabilities/trading/nodes/）

- **A 链**：a0_contradiction / a1_deep_research / a2_comprehensive / a3_strategy / a4_gate / a5_execution / a6_regime_monitor / a7_practice_gate / a8_unity / a9_exit_strategy
- **C 链**：c0_env_scan / c1_symbol_filter / c1_tech_scan / c2_momentum / c2_signal_detect / c3_backtest_verify / c3_volatility / c4_risk_assess / c5_exit_system / c5_param_optimize / c6_plan_generate / c7_exec_monitor / c8_perf_attribution / c_martin_v15
- **F 链**：f1_news / f2_flow_analysis / f3_valuation / f4_onchain_data / f5_macro_analysis
- **G 链**：g1_risk_control / g2_governance

### CLI 命令体系

- 基础命令：status / nodes / history
- 分析命令：analyze / chat
- 交易命令：auto / trade
- 调度命令：schedule / cron / job
- 编排命令：orchestration-backtest / orchestration-memory-list / orchestration-memory-show / orchestration-query / orchestration-evolve / orchestration-feedback

### HTTP API 端点

- 标准端点：/run /run/async /result/<cycle_id> /intent /nodes /history /status /health
- 扩展端点：/analyze /chat /budget /budget/reset
