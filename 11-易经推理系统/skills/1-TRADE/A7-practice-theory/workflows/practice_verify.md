# 📘 实践验证工作流 (A4)

## 实践论指导

> "认识从实践始，经过实践得到了理论的认识，还须再回到实践去。"  
> "真理的标准只能是社会的实践。"

## 工作流目标

A4是**实践验证阶段**：用小仓试探验证A1-A3的认识是否正确，避免盲目进入A5大仓执行。

## 输入

- `recognition_report.json` - A1-A3认识报告
- 当前市场数据 (OKX API)
- A7门禁检查结果

## 输出

- `verification_report.json` - 验证报告
- `recognition_correction.json` - 认识修正
- A4实践日志 (`practice_log_A4.json`)

## 工作流步骤

### Step 1: A7门禁检查 (实践第一性)

**实践论原理**: "认识来源于实践，没有实践就没有认识。"

**检查项**:
```python
def a7_a4_practice_gate():
    gates = {
        "认识来源": {
            "check": "A1-A3是否有充分调研? 认识是否来源于实践?",
            "fail_action": "返回A1-A3重新调研"
        },
        "验证设计": {
            "check": "小仓试探方案是否合理? 是否有明确验证标准?",
            "fail_action": "重新设计验证方案"
        },
        "反馈机制": {
            "check": "是否有明确的反馈收集计划? 如何修正认识?",
            "fail_action": "增加反馈收集计划"
        },
        "真理标准": {
            "check": "是否定义了成功的评判标准? (P&L/胜率/回撤)",
            "fail_action": "明确定义成功标准"
        },
        "实践纪律": {
            "check": "是否准备了实践记录? (实践日志模板)",
            "fail_action": "创建实践日志模板"
        }
    }
    
    results = evaluate_gates(gates)
    if all(results.values()):
        return "PASS: 可以进入A4实践验证"
    else:
        return "FAIL: " + format_fail_reasons(results)
```

**输出**: `a7_a4_gate_result.json`

### Step 2: 设计小仓试探方案

**实践论原理**: "实践第一性 - 必须亲自实践，不能纸上谈兵。"

**方案设计**:
```json
{
  "verification_id": "A4_20260426_01",
  "recognition_to_verify": "BTC区间震荡 $76k-$79k",
  "small_position_scheme": {
    "instrument": "BTC-USDT-SWAP",
    "position_size": "0.1张 (约$7,700)",
    "entry_strategy": "区间边界挂单",
    "stop_loss": "$500 (约0.65%)",
    "take_profit": "$1,000 (约1.3%)",
    "max_trials": "5次试探"
  },
  "truth_criteria": {
    "P&L": "盈利 ≥ $0",
    "win_rate": "胜率 ≥ 50% (5次中至少3次盈利)",
    "max_drawdown": "最大回撤 ≤ 2%"
  },
  "feedback_plan": {
    "data_collection": "记录每次试探的入场价、出场价、原因",
    "recognition_correction": "如果胜率<50%，修正认识",
    "next_action": "验证通过→A5执行; 验证失败→返回A1-A3"
  }
}
```

**输出**: `a4_verification_plan.json`

### Step 3: 执行小仓试探 (实践)

**实践论原理**: "通过实践而发现真理，又通过实践而证实真理。"

**执行要求**:
1. 严格按照方案执行，不随意调整
2. 详细记录每次试探 (`practice_log_A4.json`)
3. 实时收集反馈 (市场反应、滑点、手续费等)

**实践日志模板** (`practice_log_A4.json`):
```json
{
  "verification_id": "A4_20260426_01",
  "trial_1": {
    "timestamp": "2026-04-26T09:57:00Z",
    "direction": "LONG",
    "entry_price": "$77,187.1",
    "exit_price": "$77,411.9",
    "P&L": "+$22.48",
    "reason": "区间边界反弹",
    "feedback": "入场价合理，止损偏大"
  },
  "trial_2": {
    ...
  },
  "summary": {
    "total_trials": 3,
    "win_rate": "66.7% (2/3)",
    "total_P&L": "+$45.6",
    "max_drawdown": "1.2%",
    "truth_verification": "PASS: 胜率>50%, P&L>0"
  }
}
```

**输出**: `practice_log_A4.json` (实时更新)

### Step 4: 收集实践反馈 (认识修正)

**实践论原理**: "认识来源于实践 - 实践反馈修正认识。"

**反馈收集**:
1. 分析实践结果 (P&L、胜率、回撤)
2. 对比A1-A3原始认识
3. 识别认识偏差
4. 修正认识

**认识修正模板** (`recognition_correction.json`):
```json
{
  "verification_id": "A4_20260426_01",
  "original_recognition": "BTC区间震荡 $76k-$79k",
  "practice_feedback": {
    "confirmed": "$76k支撑有效，3次试探均反弹",
    "corrected": "震荡区间实际为$76.5k-$78.5k (比预期窄)",
    "new_insight": "成交量在区间边界萎缩，突破可能性增加"
  },
  "recognition_correction": {
    "updated_market_view": "BTC窄幅震荡 $76.5k-$78.5k，关注突破",
    "updated_strategy": "区间边界交易 + 突破确认后趋势跟踪",
    "confidence_level": "中等 (需A5进一步验证)"
  },
  "next_action": "进入A5实践执行"
}
```

**输出**: `recognition_correction.json`

### Step 5: 真理验证 (实践标准)

**实践论原理**: "真理的标准只能是社会的实践。"

**验证方法**:
```python
def verify_truth(criteria, practice_result):
    verification = {}
    
    # 1. P&L验证
    if practice_result["total_P&L"] > 0:
        verification["P&L"] = "PASS"
    else:
        verification["P&L"] = "FAIL"
    
    # 2. 胜率验证
    if practice_result["win_rate"] >= criteria["win_rate"]:
        verification["win_rate"] = "PASS"
    else:
        verification["win_rate"] = "FAIL"
    
    # 3. 回撤验证
    if practice_result["max_drawdown"] <= criteria["max_drawdown"]:
        verification["max_drawdown"] = "PASS"
    else:
        verification["max_drawdown"] = "FAIL"
    
    # 4. 综合判断
    if all(v == "PASS" for v in verification.values()):
        return "PASS: 真理验证通过，认识正确"
    else:
        return "FAIL: 真理验证失败，认识需修正"
```

**输出**: `truth_verification_A4.json`

### Step 6: 输出验证报告

**实践论原理**: "实践、认识、再实践、再认识 - 循环往复。"

**报告内容**:
```json
{
  "verification_id": "A4_20260426_01",
  "timestamp": "2026-04-26T10:40:00Z",
  "input": "recognition_report.json",
  "practice_design": "a4_verification_plan.json",
  "practice_result": "practice_log_A4.json",
  "recognition_correction": "recognition_correction.json",
  "truth_verification": "truth_verification_A4.json",
  "conclusion": {
    "verification_status": "PASS",
    "next_stage": "A5实践执行",
    "updated_recognition": "BTC窄幅震荡 $76.5k-$78.5k，关注突破"
  },
  "a7_gate_status": "PASS: 可以进入A5"
}
```

**输出**: `verification_report.json`

## A4实践验证注意事项

### ✅ 正确做法

1. **小仓试探**: 永远用小仓验证，禁止直接用大仓"验证"
2. **详细记录**: 每次试探必须记录，不能只记结果
3. **修正认识**: 实践反馈必须用来修正认识，不能"记吃不记打"
4. **真理标准**: P&L和胜率是唯一标准，不能"我认为正确"

### ❌ 错误做法

1. **跳过A4**: 直接用A5大仓"验证" → 违反实践第一性
2. **实践不充分**: 只验证1-2次就进入A5 → 认识不牢固
3. **不修正认识**: A4反馈与A3矛盾，但强行进入A5 → 认识脱离实践
4. **主观真理标准**: "我觉得市场会涨"代替P&L验证 → 违反真理标准

## 输出文件

1. `a4_verification_plan.json` - 验证方案
2. `practice_log_A4.json` - 实践日志 (A7核心)
3. `recognition_correction.json` - 认识修正
4. `truth_verification_A4.json` - 真理验证
5. `verification_report.json` - 验证报告 (A4输出)

## 与A5的关系

```
A4实践验证
    ↓ 输出: verification_report.json
    ↓       + recognition_correction.json
    ↓       + practice_log_A4.json
A5实践执行
    ↓ 输入: 上述文件
    ↓ 输出: execution_report.json
    ↓       + new_recognition.json
    ↓       + practice_log_A5.json
复盘 (再认识)
```

---

**文件版本**: v1.0  
**创建时间**: 2026-04-26  
**对应SKILL**: A7-practice-theory
