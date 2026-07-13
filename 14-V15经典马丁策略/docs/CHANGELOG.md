# 变更日志 — V15 经典马丁策略

> **定位**：记录每次变更的原因、内容、验证方式
> **格式**：[版本] - 日期 → 变更类型（新增/修改/修复/删除）

---

## [v4.0] - 2026-07-13

### 文档规范化
- **新增**: `docs/CHANGELOG.md` 变更日志文档
- **修改**: README.md 清除V15-CT"当前主力运行版本"描述，更新为独立V15系统为当前运行版本
- **修改**: README.md §2 目录结构补充 `lib/capital_manager_engine.py`、`lib/bayesian_optimizer.py`、`lib/symbol_mapper.py`
- **修改**: README.md §9.1 指标来源从 `v15ct_signal.py` 修正为 `v15_signal.py`
- **修改**: README.md §3 补充 `capital_engine` 子命令使用说明
- **修改**: README.md §12 更新测试文件列表，补充 `test_multi_scenario.py`、`test_symbol_mapper.py`
- **修改**: ENGINEERING_INDEX.md §2.2 标记V15-CT为已废弃
- **修改**: API_SPEC.md §10 路径从 `experiments/ab-trading/` 修正为 `lib/`
- **影响范围**: docs/ 全部文档 + README.md
- **验证方式**: 文档审查，路径与实际代码文件对照

---

## [v3.0] - 2026-07-12

### 修复
- **修复**: 杠杆倍数不一致问题 — 全局统一为5x
  - `.env.common` LEVERAGE 从10修改为5.0
  - `v15_trader.py` 默认杠杆从10修改为5
  - `okx_client.py` 默认杠杆从10修改为5
  - `capital_manager.py` 默认杠杆从10修改为5
  - `strategy_params.py` 默认杠杆从10修改为5
  - `bayesian_optimizer.py` 硬编码5x杠杆（不参与优化）
  - **影响范围**: config/ + lib/ + core/
  - **验证方式**: 全局搜索10x引用确认清除，测试通过
  - **回滚策略**: 恢复各文件中的LEVERAGE默认值

### 新增
- **新增**: RAISE_TP离场动作 — 强势反弹时提高止盈价
  - `classic_exit_system.py` 新增RAISE_TP评估逻辑
  - `v15_trader.py` `check_time_exit()` 支持RAISE_TP动作
  - `v15_backtest.py` 回测支持RAISE_TP模拟
  - **验证方式**: 集成测试确认RAISE_TP在hold_value=0.791时触发，new_tp=4.0xATR

### 修改
- **修改**: 持仓超时与离场系统 — 新增分层计时机制
  - 底仓阶段：max_base_holding_hours（默认48h）
  - 加仓后阶段：golden_window_hours（12h）+ max_post_addon_hours（24h）
  - 三个时间参数均纳入贝叶斯优化
  - **影响范围**: core/v15_trader.py, lib/bayesian_optimizer.py, config/.env.v15
  - **验证方式**: 多场景测试89项100%通过

---

## [v2.0] - 2026-07-12

### 新增
- **新增**: 16层入场信号系统从V15CT迁移到独立V15系统
  - `core/v15_signal.py` 从7层扩展到16层
  - 新增9项技术指标：Pivot Points, OBV, SuperTrend, Keltner Channel, StochRSI, Vortex, TEMA, GoldenCross, EMA Align
  - **影响范围**: core/v15_signal.py
  - **验证方式**: 信号测试通过，TIA成功以Pivot支撑区信号开仓

### 修改
- **修改**: 趋势过滤系统调整
  - 周线/日线MA200趋势过滤 → 改为三屏趋势信号（both_bear + MA104）
  - 保留4H均线系统用于价格位置判定
  - **影响范围**: lib/strategy_params.py
  - **验证方式**: COMP被三屏趋势过滤阻止开多（熊市禁止做多）

---

## [v1.0] - 2026-07-11

### 新增
- **新增**: V15独立系统初始版本
  - 从 `experiments/ab-trading/v15ct_*.py` 迁移到 `14-V15经典马丁策略/`
  - 统一入口 `run.py`（signal/backtest/trader/capital_engine/test/config）
  - 配置体系：`.env.common` + `.env.v15`（include语法）
  - 状态持久化：`data/v15_state.json`
  - launchd配置：`com.dreambuddy.v15_trader.plist`

### 新增
- **新增**: Elder-ray趋势强度计算器
  - 基于Alexander Elder三重滤网系统
  - 日线级别EMA13斜率 + Bull/Bear Power + 背离检测
  - 8类趋势分类，强度评分0-100
  - **影响范围**: lib/strategy_params.py

### 新增
- **新增**: 贝叶斯参数优化系统（8参数）
  - 资金分配参数：base_position_pct, addon1/2/3_pct, max_concurrent_positions
  - 持仓时间参数：max_base_holding_hours, max_post_addon_hours, golden_window_hours
  - 目标函数：最大化卡尔马比率
  - **影响范围**: lib/bayesian_optimizer.py

### 新增
- **新增**: 资金管理引擎（月度优化）
  - 整合回测+趋势过滤+贝叶斯优化+资金管理
  - HTTP API（端口8770）
  - 连续亏损3次自动触发重新优化
  - **影响范围**: lib/capital_manager_engine.py

---

## 历史版本（V15-CT实验版）

> 以下版本在 `experiments/ab-trading/` 目录中开发，已迁移到独立系统

### [v0.x] - 2026-06 ~ 2026-07

- V15-CT实验版开发与迭代
- 16项技术指标逐步引入
- AB测试对比V15独立版与V15-CT版
- master_daemon hourly调度 `v15ct_trader.py --poll-once`
- **状态**: 已废弃，代码保留作为AB对照参考

---

_维护规则：每次代码变更后必须在此文件追加变更记录_
