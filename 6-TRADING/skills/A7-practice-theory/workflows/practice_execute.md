# 📘 实践执行工作流 (A5)

## 实践论指导

> "马克思主义哲学认为十分重要的问题，不在于懂得了客观世界的规律性，因而能够解释世界，而在于拿了这种对于客观规律性的认识去能动地改造世界。"

## 工作流目标

A5是**实践执行阶段**：用大仓执行A4验证通过的战略，并在执行中能动地改造世界（根据实践反馈调整）。

## 输入

- `verification_report.json` - A4验证报告
- `recognition_correction.json` - 认识修正
- 当前市场数据 (OKX API)
- A7门禁检查结果

## 输出

- `execution_report.json` - 执行报告
- `new_recognition.json` - 新认识
- A5实践日志 (`practice_log_A5.json`)

## 工作流步骤

### Step 1: A7门禁检查 (实践纪律)

**实践论原理**: "改造世界需要纪律 - 能动性不是随意性。"

**检查项**:
```python
def a7_a5_practice_gate():
    gates = {
        "验证充分": {
            "check": "A4验证是否充分? 是否有足够样本? (至少3-5次)",
            "fail_action": "增加A4验证次数"
        },
        "认识正确": {
            "check": "A4反馈是否修正了认识? 认识是否符合当前市场?",
            "fail_action": "重新分析A4反馈，修正认识"
        },
        "执行纪律": {
            "check": "是否有明确的执行纪律和止损? 改造世界需要纪律",
            "fail_action": "制定详细执行计划和止损策略"
        },
        "风险可控": {
            "check": "实践风险是否在可接受范围? 实践是具体的",
            "fail_action": "降低仓位，直到风险可控"
        },
        "反馈机制": {
            "check": "是否有实时反馈机制? 能否根据实践调整?",
            "fail_action": "建立实时反馈机制"
        }
    }
    
    results = evaluate_gates(gates)
    if all(results.values()):
        return "PASS: 可以进入A5实践执行"
    else:
        return "FAIL: " + format_fail_reasons(results)
```

**输出**: `a7_a5_gate_result.json`

### Step 2: 制定执行计划 (能动地改造世界)

**实践论原理**: "认识去能动地改造世界 - 不是机械执行。"

**计划制定**:
```json
{
  "execution_id": "A5_20260426_01",
  "based_on": "A4_20260426_01 验证通过",
  "position_plan": {
    "instrument": "BTC-USDT-SWAP",
    "position_size": "0.5张 (约$38,500)",
    "entry_strategy": "分批入场 (3次，每次0.17张)",
    "stop_loss": "$76,000 (约1.3%)",
    "take_profit_1": "$78,500 (约1.6%) - 0.25张",
    "take_profit_2": "$80,000 (约3.2%) - 0.25张"
  },
  "execution_discipline": {
    "max_loss_per_day": "$500",
    "max_position": "1张",
    "stop_loss_strict": "严格止损，不移动止损向下"
  },
  "feedback_mechanism": {
    "real_time_monitoring": "每15分钟检查一次市场",
    "adjustment_rules": "如果价格偏离预期>2%，重新评估",
    "record_keeping": "详细记录每次调整原因"
  }
}
```

**输出**: `a5_execution_plan.json`

### Step 3: 执行大仓 (实践)

**实践论原理**: "通过实践而发现真理，又通过实践而证实真理。"

**执行要求**:
1. 严格按照计划执行，但保持能动性 (根据实践调整)
2. 详细记录每次操作 (`practice_log_A5.json`)
3. 实时收集反馈 (市场反应、滑点、手续费等)
4. 能动地调整 (不是机械执行)

**实践日志模板** (`practice_log_A5.json`):
```json
{
  "execution_id": "A5_20260426_01",
  "entry_1": {
    "timestamp": "2026-04-26T09:57:00Z",
    "direction": "LONG",
    "size": "0.17张",
    "price": "$77,187.1",
    "reason": "区间边界反弹，A4验证通过"
  },
  "entry_2": {
    "timestamp": "2026-04-26T11:30:00Z",
    "direction": "LONG",
    "size": "0.17张",
    "price": "$76,950.5",
    "reason": "价格回调，加仓"
  },
  "adjustment_1": {
    "timestamp": "2026-04-26T14:20:00Z",
    "action": "移动止损至$76,500",
    "reason": "价格波动收窄，保护利润"
  },
  "exit_1": {
    "timestamp": "2026-04-26T18:45:00Z",
    "direction": "LONG",
    "size": "0.25张",
    "price": "$78,450.2",
    "reason": "达到止盈目标1，部分获利"
  },
  "current_status": {
    "open_position": "0.09张 LONG @ $77,068.8",
    "unrealized_P&L": "+$134.52",
    "realized_P&L": "+$654.82"
  }
}
```

**输出**: `practice_log_A5.json` (实时更新)

### Step 4: 实时调整 (能动性)

**实践论原理**: "认识依赖于实践，又指导实践 - 能动性。"

**调整原则**:
1. **不违背根本认识**: 调整是战术性的，不是战略性的
2. **基于实践反馈**: 调整必须有实践依据，不能"我觉得"
3. **记录调整原因**: 每次调整必须记录，用于复盘
4. **真理标准不变**: P&L和胜率仍然是唯一标准

**调整类型**:
```json
{
  "adjustment_types": {
    "stop_loss_adjustment": "移动止损 (只能向上移动，不能向下)",
    "position_adjustment": "加仓/减仓 (基于实践反馈)",
    "entry_adjustment": "调整入场价 (更有利的价格)",
    "exit_adjustment": "调整止盈价 (让利润奔跑)"
  },
  "adjustment_rules": {
    "stop_loss": "只能向上移动，保护利润",
    "position": "加仓必须有盈利基础，亏损时不加仓",
    "entry": "限价单，不追涨杀跌",
    "exit": "分批止盈，不一次性平仓"
  }
}
```

### Step 5: 真理验证 (实践标准)

**实践论原理**: "真理的标准只能是社会的实践。"

**验证方法**:
```python
def verify_truth_a5(execution_result, truth_criteria):
    verification = {}
    
    # 1. P&L验证
    if execution_result["total_P&L"] > 0:
        verification["P&L"] = "PASS"
    else:
        verification["P&L"] = "FAIL"
    
    # 2. 胜率验证
    if execution_result["win_rate"] >= truth_criteria["win_rate"]:
        verification["win_rate"] = "PASS"
    else:
        verification["win_rate"] = "FAIL"
    
    # 3. 回撤验证
    if execution_result["max_drawdown"] <= truth_criteria["max_drawdown"]:
        verification["max_drawdown"] = "PASS"
    else:
        verification["max_drawdown"] = "FAIL"
    
    # 4. 执行纪律验证
    if execution_result["discipline_violation"] == 0:
        verification["discipline"] = "PASS"
    else:
        verification["discipline"] = "FAIL"
    
    # 5. 综合判断
    if all(v == "PASS" for v in verification.values()):
        return "PASS: 真理验证通过，认识正确"
    else:
        return "FAIL: 真理验证失败，认识需修正"
```

**输出**: `truth_verification_A5.json`

### Step 6: 输出执行报告 + 新认识

**实践论原理**: "实践、认识、再实践、再认识 - 循环往复以至无穷。"

**报告内容**:
```json
{
  "execution_id": "A5_20260426_01",
  "timestamp": "2026-04-26T22:00:00Z",
  "input": {
    "verification_report": "verification_report.json",
    "recognition_correction": "recognition_correction.json"
  },
  "execution_result": {
    "total_P&L": "+$1,245.36",
    "win_rate": "75% (3/4)",
    "max_drawdown": "1.8%",
    "discipline_violation": 0
  },
  "practice_log": "practice_log_A5.json",
  "truth_verification": "truth_verification_A5.json",
  "new_recognition": {
    "market_view": "BTC震荡偏强，区间$76k-$79k",
    "strategy_validation": "区间边界交易有效，突破确认后趋势跟踪可行",
    "lessons_learned": [
      "止损严格执行，保护利润",
      "分批止盈，让利润奔跑",
      "实时调整，但不违背根本认识"
    ]
  },
  "next_stage": "复盘 (再认识)",
  "a7_gate_status": "PASS: 可以进入复盘"
}
```

**输出**: 
1. `execution_report.json` - 执行报告 (A5输出)
2. `new_recognition.json` - 新认识 (用于复盘)

## A5实践执行注意事项

### ✅ 正确做法

1. **能动地执行**: 不是机械执行，根据实践反馈调整
2. **严格纪律**: 止损严格，不移动止损向下
3. **详细记录**: 每次调整和原因必须记录
4. **真理标准**: P&L和胜率是唯一标准

### ❌ 错误做法

1. **随意调整**: 没有实践依据就调整 → 违背认识指导实践
2. **移动止损向下**: "再给我一次机会" → 忽视实践标准
3. **不记录调整**: "我记得为什么调整" → 复盘时无依据
4. **主观真理标准**: "我觉得这次不一样" → 违背真理的实践标准

## 输出文件

1. `a5_execution_plan.json` - 执行计划
2. `practice_log_A5.json` - 实践日志 (A7核心)
3. `truth_verification_A5.json` - 真理验证
4. `execution_report.json` - 执行报告 (A5输出)
5. `new_recognition.json` - 新认识 (用于复盘)

## 与复盘的关系

```
A5实践执行
    ↓ 输出: execution_report.json
    ↓       + new_recognition.json
    ↓       + practice_log_A5.json
复盘 (再认识)
    ↓ 输入: 上述文件
    ↓ 输出: reflection_report.json
    ↓       + updated_recognition.json
    ↓       + recognition_development_log.json
下一轮实践→认识→实践
```

---

**文件版本**: v1.0  
**创建时间**: 2026-04-26  
**对应SKILL**: A7-practice-theory
