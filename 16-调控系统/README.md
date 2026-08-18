# 16-调控系统

> **统一 AI 离场评估系统** — 跨所有交易系统的宏观战略离场决策层

## 定位

本模块是一个**独立的调控功能模块**，聚合所有交易系统的持仓数据，通过 A1/A2/A3 宏观战略分析 + A9 离场决策，输出统一的四态离场建议（平仓/减仓/HOLD/提高止盈）。

**核心原则**：建议制，不替代各系统自主离场逻辑。

## 架构

```
TRAE Work 调度层（每天 08:00 / 20:00）
        ↓
宏观分析层 A1/A2/A3（战略方向 + 置信度）
        ↓
离场决策层 A9 + ClassicExitSystem（四态：CLOSE/REDUCE/HOLD/RAISE_TP）
        ↓
产物投递层 AAM（JSON + Markdown）
```

## 目录结构

```
16-调控系统/
├── core/
│   ├── __init__.py
│   └── unified_position_query.py   # 统一持仓查询层（6 系统覆盖）
├── scripts/
│   └── phase0_exit_evaluator.py    # 离场评估脚本（Phase 0/1）
├── docs/
│   ├── TECHNICAL_DESIGN.md          # 技术设计文档 v0.2
│   └── ENGINEERING_INDEX.md         # 工程索引
├── artifacts/
│   └── exit-evaluations/            # 评估产物（JSON + Markdown）
├── tests/
│   └── __init__.py
├── __init__.py
└── README.md
```

## 快速使用

### 查询统一持仓

```python
import sys
sys.path.insert(0, "16-调控系统/core")
from unified_position_query import fetch_all_positions

# 获取所有系统持仓
positions = fetch_all_positions()
print(f"总持仓: {positions['total_positions']}")

# 快速摘要
from unified_position_query import get_position_summary
summary = get_position_summary()
```

### 执行离场评估

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
python 16-调控系统/scripts/phase0_exit_evaluator.py
```

### 作为模块调用

```python
from core import fetch_all_positions, get_position_summary
```

## 覆盖的交易系统

| 系统 | 交易所 | 数据来源 | 状态 |
|---|---|---|---|
| Agent A | Hyperliquid | REST API | ✅ |
| Agent B | Hyperliquid | REST API | ✅ |
| Agent C | Hyperliquid | memory.json 文件 | ✅ |
| V15 马丁 | OKX | state.json + API | ✅ |
| 易经推理 | OKX 模拟盘 | open_positions/*.json | ✅ |
| 三屏趋势 | Hyperliquid/Aster | ml_trade_service API | ⚠️ 过渡期 |

## 阶段规划

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0 MVP | ✅ 完成 | 技术通路验证 |
| Phase 1 查询层 | ✅ 完成 | 6 系统全覆盖 |
| **Phase 2 分析层升级** | ⏳ 进行中 | 接入真实 A1/A2/A3 SKILL |
| Phase 3 决策+执行层 | ⏳ 未开始 | 接入 A9 完整决策链 |

## 四态离场行为

| 行为 | 含义 | 触发条件 |
|---|---|---|
| **CLOSE** | 建议平仓 | 持仓方向与战略方向相反 + 高置信度 |
| **REDUCE** | 建议减仓 | 持仓方向与战略方向相反 + 中置信度 |
| **HOLD** | 维持现状 | 战略方向中性 / 低置信度 |
| **RAISE_TP** | 建议提高止盈 | 持仓方向与战略方向一致 + 趋势明确 |

## 相关文档

- [技术设计文档](docs/TECHNICAL_DESIGN.md) — 完整架构设计与阶段规划
- [工程索引](docs/ENGINEERING_INDEX.md) — 文件索引与版本历史
