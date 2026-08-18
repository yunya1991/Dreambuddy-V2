# 13-通用风控模块

通用风控引擎 — 为所有交易模块提供统一的风控能力。

## 架构

```
┌─────────────────────────────────────┐
│          RiskEngine (统一入口)        │
│  ┌────────┐  ┌────────┐  ┌────────┐ │
│  │ 事前门禁 │  │ 仓位管理 │  │ 事后离场 │ │
│  └────────┘  └────────┘  └────────┘ │
└─────────────────────────────────────┘
                ↓
      RuleRegistry (规则注册表)
                ↓
    RiskContext / StateStore (状态层)
```

## 三层风控体系

### L1 - 事前门禁层 (PreTradeGate)
- 战略门禁、杠杆门禁、评分门禁
- 执行风险门禁、账户层门禁
- 日回撤熔断、黑窗时段、连续亏损限制
- Fail-Closed 原则

### L2 - 仓位管理层 (PositionSizer)
- 风险预算驱动的仓位计算
- 马丁加仓计算（可插拔策略）
- 动态仓位调整（置信度/波动率）
- 并发仓位限制

### L3 - 事后离场层 (ExitEngine)
- P0 - 安全硬退出
- P1 - 价值-风险评估
- P2 - 三重屏障
- P3 - 行为约束

## 快速开始

```python
from risk_engine import RiskEngine, RiskContext

# 初始化引擎
config = {
    "max_daily_drawdown_pct": 0.10,
    "risk_per_trade_pct": 0.02,
    "max_concurrent_positions": 5,
}
engine = RiskEngine(config)

# 事前风控检查
context = RiskContext(total_equity=10000, daily_pnl=-300)
result = engine.pre_trade_check(
    signal={"coin": "BTC", "direction": "LONG", "confidence": 0.7},
    context=context
)
print(result["passed"], result["reason_code"])

# 仓位计算
size = engine.calculate_position(
    signal={"coin": "BTC", "direction": "LONG", "confidence": 0.7},
    context=context
)
print(size["base_size_usdt"])
```

## 模块结构

```
13-通用风控模块/
├── core/                    # 核心引擎
│   ├── engine.py           # RiskEngine 统一入口
│   ├── context.py          # 风控上下文与状态
│   ├── registry.py         # 规则注册表
│   ├── pre_trade_gate.py   # 事前门禁层
│   ├── position_sizer.py   # 仓位管理层
│   └── exit_engine.py      # 事后离场层
├── rules/                   # 风控规则集（可插拔）
│   ├── gate_rules.py       # 门禁规则
│   ├── position_rules.py   # 仓位规则
│   └── exit_rules.py       # 离场规则
├── docs/                    # 文档
├── tests/                   # 测试
└── README.md
```
