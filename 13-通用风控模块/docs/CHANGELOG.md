# 变更日志 — 通用风控引擎

> **定位**：记录每次变更的原因、内容、影响范围、验证方式与回滚策略
> **格式**：[版本] - 日期 → 变更类型（新增/修改/修复/删除）
> **当前版本**：v1.1.0 | **更新日期**：2026-07-25

---

## [v1.1.0] - 2026-07-25

### Phase 2 深化与扩展：L1 价值-风险评估 + ML 风控模型集成 + 飞书告警通知

#### 新增

- **新增**: L1 价值-风险评估器（`core/l1_assessor.py`）
  - 复现经典离场系统 `classic_exit_system.py` 的核心评估逻辑
  - `hold_risk` 10 维加权公式（dd_risk 主导 0.42 权重，含 RSI/trend/MACD/ADX/chop/atr/mom/vol/stretch 等因子）
  - MRD Score（最小阻力方向）概率评估，`p_mrd = sigmoid(mrd_score × 3)`
  - 三种评估模式：`L1Mode.HEURISTIC`（纯启发式）/ `L1Mode.MRD`（概率调整）/ `L1Mode.ML`（模型融合）
  - 风险预算序列回撤惩罚（dd 增量归一化 × 0.15 上限，窗口长度 12）
  - L2 滞回状态机（armed + confirm_n + deadband），per-coin 持久化 `L2HysteresisState`
  - Regime 分桶阈值偏移（震荡市 +0.05，低 ADX +0.03，自定义 regime 字段偏移）
  - 动作映射：CLOSE / REDUCE / HOLD，`reduce_frac` 线性插值（base=0.30, max=0.70）
  - 公开类：`L1ValueRiskAssessor`、`ExitFeatureSet`、`L1Mode`、`L2HysteresisState`、`TrendShape`、`L1AssessmentResult`
  - **影响范围**: core/l1_assessor.py, core/engine.py, __init__.py
  - **验证方式**: `tests/test_l1_ml_alert.py` 中 `TestL1Assessor`（10 个用例：hold_risk 基础/高回撤、MRD 方向性/调整、ML 调整、L2 动作持有/平仓、滞回状态、风险预算、Regime 偏移）

- **新增**: ML 风控模型集成框架（`core/ml_model.py`）
  - 支持三类模型：`sklearn_pickle`（lr/rf/xgb sklearn）、`xgb`（XGBoost Booster）、`committee`（多模型加权）
  - `MLRiskModel.load_from_meta()` 从 meta JSON 加载（与 `committee_meta.json` 格式对齐）
  - `CommitteeModel` 多模型加权集成，输出 `p_tail` / `p_move`
  - `MLModelRegistry` 模型注册表，支持 `load_model` / `load_committee` / `predict` / `list_models`
  - meta JSON 格式：`{model_type, model_path, feature_names, latest_version}`
  - 公开类：`MLRiskModel`、`CommitteeModel`、`MLModelRegistry`、`ModelPrediction`
  - **影响范围**: core/ml_model.py, core/engine.py, __init__.py
  - **验证方式**: `tests/test_l1_ml_alert.py` 中 `TestMLModel`（6 个用例：不存在文件加载、空模型预测、空 Committee、注册表、注册表预测、metaJSON 加载）

- **新增**: 飞书告警通知模块（`core/alert.py`）
  - 三种推送模式：`webhook`（轻量级，无需应用凭证）/ `openapi`（复用 `6-TRADING/scripts/feishu_notify.py`）/ `file`（本地日志兜底）
  - 三级告警：`AlertLevel.INFO`（蓝）/ `WARNING`（黄）/ `CRITICAL`（红）
  - 七类告警类别：`GATE_BLOCK` / `GATE_DEGRADE` / `EXIT_TRIGGER` / `DRAWDOWN` / `CONSECUTIVE_LOSS` / `ML_MODEL` / `SYSTEM`
  - `AlertEvent.to_card()` 构建飞书卡片消息，`to_text()` 构建纯文本
  - 级别过滤（`min_level`）+ 同类告警限频（`rate_limit_sec`，默认 60 秒）
  - 五个便捷方法：`alert_gate_block` / `alert_gate_degrade` / `alert_exit_trigger` / `alert_drawdown` / `alert_consecutive_loss`
  - 告警历史记录与查询（`get_history(limit)`）
  - OpenAPI 模块不可用时自动降级为 webhook
  - 公开类：`RiskAlertNotifier`、`AlertEvent`、`AlertLevel`、`AlertCategory`
  - **影响范围**: core/alert.py, core/engine.py, __init__.py
  - **验证方式**: `tests/test_l1_ml_alert.py` 中 `TestAlertNotifier`（7 个用例：事件创建、卡片构建、文本构建、告警发送、级别过滤、便捷方法、限频）

- **新增**: RiskEngine 增强 API
  - `assess_value_risk(position, features, l1_mode)` — L1 价值-风险评估入口，动作触发时自动调用 `alert_exit_trigger`
  - `load_ml_model(name, meta_path)` / `load_ml_committee(name, members)` — ML 模型加载
  - `ml_predict(model_name, features)` — ML 模型预测
  - `list_ml_models()` — 列出所有已注册 ML 模型
  - `alert(event)` / `get_alert_history(limit)` — 告警发送与历史查询
  - `get_status(context)` 增加 `ml_models` 与 `alert_count` 字段
  - **影响范围**: core/engine.py
  - **验证方式**: `tests/test_l1_ml_alert.py` 中 `TestEngineIntegration`（4 个用例：L1 评估器集成、ML 模型管理、告警集成、增强状态概览）

- **新增**: `__init__.py` 导出全部公开类
  - 导出 17 个公开类：`RiskEngine` / `RiskContext` / `PositionState` / `MarketSnapshot` / `Signal` / `RuleRegistry` / `L1ValueRiskAssessor` / `ExitFeatureSet` / `L1Mode` / `L2HysteresisState` / `MLRiskModel` / `CommitteeModel` / `MLModelRegistry` / `ModelPrediction` / `RiskAlertNotifier` / `AlertEvent` / `AlertLevel` / `AlertCategory`
  - `__version__ = "1.1.0"`
  - **影响范围**: __init__.py

- **新增**: 增强测试套件（`tests/test_l1_ml_alert.py`，27 个用例）
  - `TestL1Assessor`（10 个）：hold_risk 计算、MRD 评分、ML 调整、L2 滞回状态机、风险预算、Regime 偏移
  - `TestMLModel`（6 个）：模型加载、预测、Committee、注册表
  - `TestAlertNotifier`（7 个）：事件构建、卡片/文本、发送、级别过滤、便捷方法、限频
  - `TestEngineIntegration`（4 个）：L1/ML/告警与 RiskEngine 的集成
  - **影响范围**: tests/test_l1_ml_alert.py
  - **验证方式**: `python -m pytest tests/test_l1_ml_alert.py -v`（27/27 通过）

#### 修改

- **修改**: RiskEngine 初始化扩展
  - `__init__` 新增 `l1_assessor` / `ml_registry` / `alert_notifier` 三个内部组件
  - 新增 `_l2_states`（per-coin L2 滞回状态字典）与 `_dd_snapshots`（dd 快照历史）内部状态
  - 配置新增 `l1` / `alert` 子键支持
  - **影响范围**: core/engine.py
  - **验证方式**: 全部 51 个测试通过

- **修改**: 技术文档全面更新
  - `TECHNICAL_DESIGN.md` 新增第 9 章「L1 价值-风险评估」、第 10 章「ML 风控模型集成」、第 11 章「飞书告警通知」，更新版本至 v1.1
  - `ENGINEERING_INDEX.md` 核心模块从 6 个扩展至 9 个（新增 l1_assessor / ml_model / alert），测试数从 24 更新至 51，更新版本至 v1.1
  - **影响范围**: docs/TECHNICAL_DESIGN.md, docs/ENGINEERING_INDEX.md

#### 验证与回滚

- **验证方式**:
  - 核心测试：`python -m pytest tests/test_risk_engine.py -v`（24/24 通过）
  - 增强测试：`python -m pytest tests/test_l1_ml_alert.py -v`（27/27 通过）
  - 总测试数：51（24 核心 + 27 增强），通过率 100%
- **回滚策略**:
  - 回退 `__version__` 至 `"1.0.0"`
  - 移除 `core/l1_assessor.py` / `core/ml_model.py` / `core/alert.py` 三个新增模块
  - 还原 `core/engine.py` 至 v1.0 版本（移除 L1/ML/告警相关方法与内部组件）
  - 还原 `__init__.py` 导出列表至 v1.0（仅保留 RiskEngine / RiskContext / PositionState / MarketSnapshot / Signal / RuleRegistry）
  - 删除 `tests/test_l1_ml_alert.py`

---

## [v1.0] - 2026-07-15

### Phase 1 核心框架：三层风控架构 + 规则注册表 + 17 条默认规则

#### 新增

- **新增**: 三层风控架构设计与实现
  - L1 事前门禁层（`core/pre_trade_gate.py`）— 交易前检查，决定是否允许开仓
  - L2 仓位管理层（`core/position_sizer.py`）— 仓位计算，决定开多大仓位
  - L3 事后离场层（`core/exit_engine.py`）— 持仓监控，决定何时离场
  - 三层层层递进，按优先级驱动，遇硬阻断短路执行
  - **影响范围**: core/pre_trade_gate.py, core/position_sizer.py, core/exit_engine.py
  - **验证方式**: `tests/test_risk_engine.py` 中 `TestRiskEngine`（14 个用例）

- **新增**: RiskEngine 统一入口（`core/engine.py`）
  - 整合三层风控体系，提供统一、易用的风控接口
  - 核心方法：`pre_trade_check` / `calculate_position` / `check_exit` / `full_pre_trade`
  - 规则管理：`register_default_rules` / `register_rule` / `enable_rule` / `disable_rule` / `list_rules`
  - 状态查询：`get_status(context)`
  - Fail-Closed 原则，SDK 式集成，低侵入性
  - **影响范围**: core/engine.py
  - **验证方式**: `tests/test_risk_engine.py` 中 `TestRiskEngine`（14 个用例：初始化、门禁通过/熔断/降级/连续亏损、仓位计算/调整、离场持有/止损/止盈/最大亏损、完整流程、规则列表、状态查询）

- **新增**: 规则注册表机制（`core/registry.py`）
  - 可插拔的风控规则注册与管理，支持按类别（GATE / POSITION / EXIT）分组
  - 按优先级排序执行，支持启用/禁用规则
  - 装饰器式注册：`register_gate` / `register_position` / `register_exit`
  - 链式执行（`execute_chain`），遇失败可停止（`stop_on_fail`）
  - 公开类：`RuleRegistry`、`RuleInfo`、`RuleCategory`
  - **影响范围**: core/registry.py
  - **验证方式**: `tests/test_risk_engine.py` 中 `TestRuleRegistry`（4 个用例：注册获取、优先级排序、启用禁用、装饰器注册）

- **新增**: 风控上下文与数据结构（`core/context.py`）
  - `RiskContext` — 全局风控状态的单一真相源（权益、日盈亏、回撤、连续亏损、持仓、交易历史）
  - 持仓状态 `PositionState`（含 `pnl_eff` 有效收益率、`is_long` 多空判断属性）
  - 市场快照 `MarketSnapshot`、交易信号 `Signal`
  - 枚举：`Direction` / `ExitAction` / `ExitPriority` / `RiskLevel` / `ReasonCode`
  - 结果类：`RiskCheckResult`（含 `pass_result` / `fail_result` / `degrade_result` 工厂方法）、`PositionSizeResult`、`ExitResult`
  - `ReasonCode` 理由码体系与知识库 `2-KNOWLEDGE/1-TRADING/风控体系.md` 完全对齐
  - **影响范围**: core/context.py
  - **验证方式**: `tests/test_risk_engine.py` 中 `TestRiskContext`（4 个用例：上下文基本功能、回撤计算、连续亏损、日度重置）+ `TestPositionState`（2 个用例：有效盈亏、多空判断）

- **新增**: 17 条默认风控规则（`rules/`）
  - 门禁规则 7 条（`rules/gate_rules.py`）：
    - `daily_drawdown_circuit_breaker`（P0，priority=5）— 日回撤熔断
    - `leverage_cap_check`（P0，priority=10）— 杠杆上限检查
    - `concurrent_position_limit`（priority=20）— 并发仓位限制
    - `consecutive_losses_limit`（priority=25）— 连续亏损限制
    - `blackout_period_check`（priority=30）— 黑窗时段检查
    - `confidence_minimum`（priority=50）— 最低置信度检查（硬拒/软降级）
    - `drawdown_warning_degrade`（priority=60）— 回撤警告降级
  - 仓位规则 3 条（`rules/position_rules.py`）：
    - `confidence_based_adjustment`（priority=10）— 置信度仓位调整
    - `volatility_based_adjustment`（priority=20）— 波动率仓位调整
    - `max_position_cap`（priority=90）— 最大仓位限制
  - 离场规则 7 条（`rules/exit_rules.py`）：
    - `max_loss_stop`（P0，priority=5）— 最大亏损止损
    - `liquidation_buffer`（P0，priority=8）— 强平安全缓冲
    - `max_hold_time`（P0，priority=10）— 最大持仓时间
    - `stop_loss_barrier`（P2，priority=20）— 止损屏障
    - `take_profit_barrier`（P2，priority=25）— 止盈屏障
    - `time_barrier`（P2，priority=30）— 时间屏障
    - `trailing_stop`（P3，priority=35）— 跟踪止损
  - **影响范围**: rules/gate_rules.py, rules/position_rules.py, rules/exit_rules.py
  - **验证方式**: `tests/test_risk_engine.py` 全部 24 个用例

- **新增**: 单元测试套件（`tests/test_risk_engine.py`，24 个用例）
  - `TestRiskContext`（4 个）：上下文基本功能、回撤计算、连续亏损、日度重置
  - `TestRuleRegistry`（4 个）：注册获取、优先级排序、启用禁用、装饰器注册
  - `TestRiskEngine`（14 个）：初始化、门禁通过/熔断/降级/连续亏损、仓位计算/调整、离场持有/止损/止盈/最大亏损、完整流程、规则列表、状态查询
  - `TestPositionState`（2 个）：有效盈亏、多空判断
  - **影响范围**: tests/test_risk_engine.py
  - **验证方式**: `python -m pytest tests/test_risk_engine.py -v`（24/24 通过）

- **新增**: 技术文档
  - `docs/TECHNICAL_DESIGN.md` — 技术设计文档（架构设计、核心数据结构、核心模块设计、默认规则说明、使用示例、对接路径）
  - `docs/ENGINEERING_INDEX.md` — 工程索引（模块定位、目录地图、文件清单、依赖关系、核心接口速查、配置参考、测试覆盖、开发路线图）
  - **影响范围**: docs/TECHNICAL_DESIGN.md, docs/ENGINEERING_INDEX.md

- **新增**: 包入口 `__init__.py`
  - 导出核心公开类：`RiskEngine` / `RiskContext` / `PositionState` / `MarketSnapshot` / `Signal` / `RuleRegistry`
  - `__version__ = "1.0"`
  - **影响范围**: __init__.py

#### 设计特性

- **统一标准**：为所有交易模块提供一致的风控接口和规则
- **可插拔扩展**：基于注册表的规则机制，支持动态增删风控规则
- **分层架构**：事前-事中-事后三层风控，层层递进
- **Fail-Closed**：缺失数据或异常时默认拒绝，安全第一
- **SDK 集成**：Python 包形式，低侵入，零外部依赖（仅 Python 标准库）
- **理由码体系**：完整的审计追踪，每个决策都有明确原因
- **与知识库对齐**：理由码、门禁优先级与 `2-KNOWLEDGE/1-TRADING/风控体系.md` 完全一致

#### 验证与回滚

- **验证方式**: `python -m pytest tests/test_risk_engine.py -v`（24/24 通过，通过率 100%）
- **回滚策略**: v1.0 为初始版本，无需回滚

---

## 待办版本（Roadmap）

> 以下为后续规划版本，尚未实现

### Phase 3: 系统对接（待办）

- **待办**: 马丁策略对接
  - 用 `PositionSizer` 替换 `capital_manager.py` 的仓位计算
  - 用 `PreTradeGate` 替换硬编码的并发/资金检查
  - 用 `ExitEngine` 替换 `v15_trader.py` 的止损止盈逻辑
- **待办**: 三屏趋势系统对接
  - 接入 `PreTradeGate` 进行事前风控
  - 用 `PositionSizer` 的置信度调整替代内部仓位分级
  - 用 `ExitEngine` 替换 `classic_exit_system.py` 的调用
- **待办**: 经典指标系统对接
  - 逐步迁移 `classic_exit_system.py` 的规则到 `ExitEngine`
  - 统一风控状态到 `RiskContext`
  - 接入 `PreTradeGate` 增强事前风控
- **待办**: 易经推理系统对接
- **待办**: 马丁加仓策略规则
- **待办**: 周线反转检测
- **待办**: 风控状态持久化

### Phase 4: 高级特性（待办）

- **待办**: ML 模型训练流水线
  - 端到端的 p_tail / p_move 模型训练流水线
- **待办**: 多账户统一风控
  - 支持多账户、多交易所的统一风控
- **待办**: 风控回测验证
  - 在回测引擎中统一使用风控引擎
- **待办**: 风控可视化仪表盘
  - 可视化风控状态、规则触发统计

---

_维护规则：每次代码变更后必须在此文件追加变更记录_
_最后更新：2026-07-25 | 来源：13-通用风控模块（risk-engine v1.1.0）_
