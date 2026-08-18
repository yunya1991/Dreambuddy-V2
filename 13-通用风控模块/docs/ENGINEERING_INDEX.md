# 通用风控引擎 — 工程索引

> **版本**: v1.0 | **更新日期**: 2026-07-25
> **关联**: [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) · [API_SPEC.md](./API_SPEC.md) v1.1.0 · [CHANGELOG.md](./CHANGELOG.md) v1.1.0

## 1. 模块定位

**模块名称**: 13-通用风控模块
**英文代号**: risk-engine
**核心职责**: 为所有交易模块提供统一的风控能力
**设计模式**: SDK 式集成，低侵入性

### 1.1 模块边界

**在交易系统中的位置：

```
交易策略层
    ↑
    通用风控引擎（本模块）
    ↑
    交易所 / 经典指标系统 / 三屏趋势 / 马丁策略 / 易经推理
    ↑
    交易所 API / 行情数据
```

---

## 2. 目录地图

```
13-通用风控模块/
├── core/                    # 核心引擎（9个模块，1500+ 行代码）
│   ├── engine.py           # RiskEngine 统一入口
│   ├── context.py          # 风控上下文与数据结构
│   ├── registry.py         # 规则注册表
│   ├── pre_trade_gate.py   # 事前门禁层
│   ├── position_sizer.py   # 仓位管理层
│   ├── exit_engine.py      # 事后离场层
│   ├── l1_assessor.py      # L1 价值-风险评估（v1.1新增）
│   ├── ml_model.py         # ML 风控模型集成（v1.1新增）
│   └── alert.py            # 飞书告警通知（v1.1新增）
├── rules/                   # 风控规则集（可插拔）
│   ├── gate_rules.py       # 7 条门禁规则
│   ├── position_rules.py   # 3 条仓位规则
│   └── exit_rules.py       # 7 条离场规则
├── docs/                    # 技术文档
│   ├── TECHNICAL_DESIGN.md  # 技术设计文档
│   ├── ENGINEERING_INDEX.md # 工程索引（本文件）
│   └── API_SPEC.md        # API 规格
├── tests/                   # 单元测试
│   ├── test_risk_engine.py # 24 个测试用例（核心引擎）
│   └── test_l1_ml_alert.py # 27 个测试用例（L1/ML/告警）
├── README.md
└── __init__.py
```

---

## 3. 文件清单与职责

### 3.1 核心引擎层 (core/)

| 文件 | 职责 | 核心类/函数 | 行数 |
|---|---|---|---|
| engine.py | 统一入口，整合三层风控+L1+ML+告警 | RiskEngine | ~380 |
| context.py | 数据结构、上下文状态管理 | RiskContext, PositionState, Signal, ReasonCode, ExitResult | ~300 |
| registry.py | 规则注册、排序、执行 | RuleRegistry, RuleInfo, RuleCategory | ~150 |
| pre_trade_gate.py | 事前门禁层，按优先级执行门禁规则 | PreTradeGate | ~80 |
| position_sizer.py | 仓位管理层，风险预算驱动仓位计算 | PositionSizer | ~120 |
| exit_engine.py | 事后离场层，四层离场决策 | ExitEngine | ~100 |
| l1_assessor.py | L1价值-风险评估（hold_risk/MRD/L2滞回） | L1ValueRiskAssessor, ExitFeatureSet, L2HysteresisState | ~350 |
| ml_model.py | ML风控模型集成（xgb/sklearn/committee） | MLRiskModel, CommitteeModel, MLModelRegistry | ~250 |
| alert.py | 飞书告警通知（webhook/openapi/file） | RiskAlertNotifier, AlertEvent, AlertLevel | ~300 |

### 3.2 规则层 (rules/)

| 文件 | 规则数量 | 类别 |
|---|---|---|
| gate_rules.py | 7 | 门禁规则 |
| position_rules.py | 3 | 仓位规则 |
| exit_rules.py | 7 | 离场规则 |

### 3.3 测试层 (tests/)

| 文件 | 测试类 | 测试数 |
|---|---|---|
| test_risk_engine.py | TestRiskContext, TestRuleRegistry, TestRiskEngine, TestPositionState | 24 |
| test_l1_ml_alert.py | TestL1Assessor, TestMLModel, TestAlertNotifier, TestEngineIntegration | 27 |

---

## 4. 依赖关系

### 4.1 内部依赖

```
RiskEngine (engine.py)
    ├── RiskContext (context.py)
    ├── RuleRegistry (registry.py)
    ├── PreTradeGate (pre_trade_gate.py)
    ├── PositionSizer (position_sizer.py)
    ├── ExitEngine (exit_engine.py)
    ├── L1ValueRiskAssessor (l1_assessor.py)    [v1.1]
    ├── MLModelRegistry (ml_model.py)           [v1.1]
    └── RiskAlertNotifier (alert.py)            [v1.1]
           ↓
    rules/ (注册时注入)
```

### 4.2 外部依赖

- **标准库**: dataclasses, enum, typing, datetime
- **无第三方依赖** — 纯 Python 实现，零外部依赖

### 4.3 被依赖关系

```
14-V15经典马丁策略 → 可接入（待接入)
12-三屏趋势系统 → 可接入（待接入）
11-易经推理系统 → 可接入（待接入）
10-经典指标系统 → 可接入（待接入）
experiments/ → 可接入（待接入）
```

---

## 5. 核心接口速查

### 5.1 RiskEngine 主要方法

| 方法 | 说明 | 返回值 |
|---|---|---|
| register_default_rules() | 注册所有默认规则 | - |
| pre_trade_check(signal, context) | 事前风控检查 | RiskCheckResult |
| calculate_position(signal, context, modifier) | 仓位计算 | PositionSizeResult |
| check_exit(position, market, context) | 离场决策 | ExitResult |
| full_pre_trade(signal, context) | 完整事前流程（门禁+仓位） | dict |
| assess_value_risk(position, features, l1_mode) | L1价值-风险评估 | L1AssessmentResult |
| load_ml_model(name, meta_path) | 加载ML模型 | bool |
| load_ml_committee(name, members) | 加载Committee模型 | bool |
| ml_predict(model_name, features) | ML模型预测 | ModelPrediction |
| alert(event) | 发送告警 | bool |
| get_alert_history(limit) | 获取告警历史 | list |
| register_rule(name, category, handler) | 注册自定义规则 | - |
| enable_rule(name) / disable_rule(name) | 启用/禁用规则 | bool |
| list_rules() | 列出所有规则 | dict |
| get_status(context) | 获取风控状态概览 | dict |

### 5.2 规则总数

| 类别 | 规则数 | 默认启用 |
|---|---|---|
| 门禁规则 (GATE) | 7 | 是 |
| 仓位规则 (POSITION) | 3 | 是 |
| 离场规则 (EXIT) | 7 | 是 |
| **总计** | **17** | - |

---

## 6. 配置参考

### 6.1 核心配置项

```python
{
    "gate": {
        "daily_drawdown_circuit_breaker": {"max_daily_drawdown_pct": 0.10},
        "leverage_cap_check": {"max_leverage": 10.0},
        "concurrent_position_limit": {"max_concurrent_positions": 5},
        "consecutive_losses_limit": {"max_consecutive_losses": 5},
        "confidence_minimum": {"confidence_hard_min": 0.2, "confidence_soft_min": 0.4},
        "drawdown_warning_degrade": {"drawdown_warn_1": 0.05, "drawdown_warn_2": 0.08},
    },
    "position": {
        "risk_per_trade_pct": 0.02,
        "max_risk_per_trade_pct": 0.05,
        "max_position_pct": 0.25,
        "default_stop_pct": 0.03,
    },
    "exit": {
        "max_loss_stop": {"max_loss_pct": 0.10},
        "stop_loss_barrier": {"stop_method": "pct", "stop_loss_pct": 0.03},
        "take_profit_barrier": {"tp_method": "rr", "rr_ratio": 2.0},
        "trailing_stop": {"trailing_arm_pct": 0.03, "trailing_pct": 0.02},
    }
}
```

---

## 7. 测试覆盖

| 测试类 | 测试用例数 | 覆盖范围 |
|---|---|---|
| TestRiskContext | 4 | 上下文基本功能、回撤计算、连续亏损、日度重置 |
| TestRuleRegistry | 4 | 注册获取、优先级排序、启用禁用、装饰器注册 |
| TestRiskEngine | 14 | 初始化、门禁通过/熔断/降级/连续亏损、仓位计算/调整、离场持有/止损/止盈/最大亏损、完整流程、规则列表、状态查询 |
| TestPositionState | 2 | 有效盈亏、多空判断 |
| TestL1Assessor | 10 | hold_risk基础/高回撤、MRD方向性/调整、ML调整、L2动作持有/平仓、滞回状态、风险预算、Regime偏移 |
| TestMLModel | 6 | 不存在文件加载、空模型预测、空Committee、注册表、注册表预测、metaJSON加载 |
| TestAlertNotifier | 7 | 事件创建、卡片构建、文本构建、告警发送、级别过滤、便捷方法、限频 |
| TestEngineIntegration | 4 | L1评估器集成、ML模型管理、告警集成、增强状态概览 |

**总测试数**: 51 (24 核心 + 27 增强)
**测试通过率**: 100%

---

## 8. 开发路线图

### Phase 1: 核心框架 ✅
- [x] 三层架构设计与实现
- [x] 规则注册表机制
- [x] 风控上下文与数据结构
- [x] 17条默认风控规则
- [x] 单元测试（24个用例）
- [x] 技术设计文档

### Phase 2: 深化与扩展 ✅
- [x] L1价值-风险评估（hold_risk 10维加权 + MRD + 风险预算 + L2滞回）
- [x] ML风控模型集成（xgb/sklearn/committee）
- [x] 风控事件告警（飞书Webhook/OpenAPI/文件日志）
- [ ] 马丁加仓策略规则
- [ ] 周线反转检测
- [ ] 风控状态持久化

### Phase 3: 系统对接
- [ ] 马丁策略对接
- [ ] 三屏趋势系统对接
- [ ] 经典指标系统对接
- [ ] 易经推理系统对接

### Phase 4: 高级特性
- [ ] ML 模型训练流水线
- [ ] 多账户统一风控
- [ ] 风控回测验证
- [ ] 风控可视化仪表盘
