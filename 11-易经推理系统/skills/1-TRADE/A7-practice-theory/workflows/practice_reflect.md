# 📘 复盘反思工作流 (再认识)

## 实践论指导

> "实践、认识、再实践、再认识，这种形式，循环往复以至无穷。"  
> "通过实践而发现真理，又通过实践而证实真理和发展真理。"

## 工作流目标

复盘是**再认识阶段**：总结A5实践执行的结果，验证认识正确性，发展认识，为下一轮实践→认识→实践做准备。

## 输入

- `execution_report.json` - A5执行报告
- `new_recognition.json` - A5输出的新认识
- `practice_log_A5.json` - A5实践日志
- 历史认识发展日志 (`recognition_development_log.json`)

## 输出

- `reflection_report.json` - 复盘报告
- `updated_recognition.json` - 更新后的认识
- 认识发展记录 (更新`recognition_development_log.json`)

## 工作流步骤

### Step 1: 收集实践结果 (真理标准)

**实践论原理**: "真理的标准只能是社会的实践。"

**收集内容**:
1. A5执行结果 (P&L、胜率、回撤)
2. 执行纪律 (是否违反纪律?)
3. 实践日志 (所有调整和原因)
4. 认识修正 (A5输出的new_recognition.json)

**输出**: `practice_result_summary.json`

### Step 2: 对比原始认识 (认识正确性)

**实践论原理**: "认识依赖于实践，又指导实践。"

**对比项**:
```json
{
  "recognition_evolution": {
    "original": "A1-A3原始认识 (recognition_report.json)",
    "verification": "A4验证后认识 (recognition_correction.json)",
    "execution": "A5执行后新认识 (new_recognition.json)"
  },
  "comparison": {
    "correct_predictions": "原始认识中哪些被实践验证正确?",
    "incorrect_predictions": "原始认识中哪些被实践验证错误?",
    "new_insights": "实践中有哪些新认识?",
    "surprises": "实践中哪些超出原始认识?"
  }
}
```

**输出**: `recognition_comparison.json`

### Step 3: 真理验证 (实践标准)

**实践论原理**: "只有人们的社会实践，才是人们对于外界认识的真理性的标准。"

**验证方法**:
```python
def verify_truth_reflection(execution_result, original_recognition):
    verification = {}
    
    # 1. P&L验证 - 最根本的真理标准
    if execution_result["total_P&L"] > 0:
        verification["P&L"] = {
            "status": "PASS",
            "meaning": "实践验证认识正确，盈利是真理"
        }
    else:
        verification["P&L"] = {
            "status": "FAIL",
            "meaning": "实践验证认识错误，亏损是真理"
        }
    
    # 2. 胜率验证 - 认识稳定性
    if execution_result["win_rate"] >= 50:
        verification["win_rate"] = "PASS: 认识相对稳定"
    else:
        verification["win_rate"] = "FAIL: 认识不稳定"
    
    # 3. 执行纪律验证 - 实践纪律
    if execution_result["discipline_violation"] == 0:
        verification["discipline"] = "PASS: 执行纪律良好"
    else:
        verification["discipline"] = "FAIL: 执行纪律松懈"
    
    # 4. 认识发展验证 - 螺旋上升
    if has_new_insights(execution_result, original_recognition):
        verification["recognition_development"] = "PASS: 认识有发展"
    else:
        verification["recognition_development"] = "FAIL: 认识原地踏步"
    
    return verification
```

**输出**: `truth_verification_reflection.json`

### Step 4: 总结认识发展 (螺旋上升)

**实践论原理**: "实践、认识、再实践、再认识，循环往复以至无穷，而实践和认识之每一循环的内容，都比较地进到了高一级的程度。"

**发展总结**:
```json
{
  "recognition_development": {
    "loop_1": {
      "recognition": "原始认识 (A1-A3)",
      "practice": "A4验证 + A5执行",
      "new_recognition": "新认识 (复盘后)",
      "development": "认识如何发展? (更高级程度?)"
    },
    "loop_2": {
      "recognition": "基于loop_1新认识",
      "practice": "...",
      "new_recognition": "...",
      "development": "..."
    }
  },
  "spiral_upward": {
    "evidence": "认识是否螺旋上升? (不是原地踏步)",
    "examples": [
      "Loop 1: 认为BTC震荡，验证通过",
      "Loop 2: 认识到震荡区间会动态变化，增加区间调整规则",
      "Loop 3: 认识到震荡突破需确认，增加突破确认条件"
    ]
  }
}
```

**输出**: 更新`recognition_development_log.json`

### Step 5: 修正理论 (认识发展)

**实践论原理**: "认识依赖于实践，又指导实践 - 认识必须发展。"

**修正内容**:
```json
{
  "theory_correction": {
    "what_to_correct": "根据实践结果，修正哪些理论认识?",
    "why_correct": "实践证据是什么? (不能凭感觉)",
    "how_to_correct": "如何修正? (具体修正内容)",
    "validation": "修正后如何验证? (下一轮A4-A5)"
  },
  "examples": [
    {
      "original": "BTC在$75k-$80k震荡",
      "practice_evidence": "实际区间$76k-$79k，且会动态变化",
      "correction": "增加'区间动态调整'规则，每隔N根K线重新评估区间"
    },
    {
      "original": "突破后趋势跟踪",
      "practice_evidence": "多次假突破，止损频繁",
      "correction": "增加'突破确认'条件: 突破后回踩不破前高/前低 + 成交量放大"
    }
  ]
}
```

**输出**: `theory_correction.json`

### Step 6: 输出复盘报告 (再认识)

**实践论原理**: "再认识 - 为下一轮实践→认识→实践做准备。"

**报告内容**:
```json
{
  "reflection_id": "REFLECT_20260426_01",
  "timestamp": "2026-04-26T23:00:00Z",
  "input": {
    "execution_report": "execution_report.json",
    "new_recognition": "new_recognition.json",
    "practice_log_A5": "practice_log_A5.json"
  },
  "truth_verification": "truth_verification_reflection.json",
  "recognition_comparison": "recognition_comparison.json",
  "recognition_development": "认识发展总结 (螺旋上升证据)",
  "theory_correction": "theory_correction.json",
  "updated_recognition": {
    "market_view": "更新后的市场认识",
    "strategy": "更新后的策略",
    "rules": "更新后的规则 (理论修正)"
  },
  "next_loop": {
    "A1-A3": "基于updated_recognition重新调研/分析/制定战略",
    "A4": "验证updated_recognition",
    "A5": "执行验证通过的战略"
  },
  "a7_gate_status": "PASS: 再认识完成，可以进入下一轮实践"
}
```

**输出**: `reflection_report.json` + `updated_recognition.json`

## 复盘反思注意事项

### ✅ 正确做法

1. **真理标准**: P&L和胜率是唯一标准，不能"我认为正确"
2. **认识发展**: 必须总结认识如何发展，不能原地踏步
3. **理论修正**: 修正必须有实践证据，不能凭感觉
4. **螺旋上升**: 每一轮循环必须进到高一级程度

### ❌ 错误做法

1. **不复盘**: A5执行完就结束 → 没有再认识环节
2. **复盘形式化**: "嗯，还不错" → 没有深入分析
3. **认识不发展**: 每次复盘都同样认识 → 没有螺旋上升
4. **修正无证据**: "我觉得应该这样" → 没有实践证据

## 输出文件

1. `practice_result_summary.json` - 实践结果摘要
2. `recognition_comparison.json` - 认识对比
3. `truth_verification_reflection.json` - 真理验证 (复盘用)
4. `theory_correction.json` - 理论修正
5. `reflection_report.json` - 复盘报告 (核心输出)
6. `updated_recognition.json` - 更新后的认识
7. 更新`recognition_development_log.json` - 认识发展日志

## 完整循环: 实践→认识→实践

```
        实践论指导
             ↓
    ┌─────────────────┐
    │   A1-A3 (认识)  │
    │   调查研究       │
    │   形成认识       │
    └─────────────────┘
             ↓
    ┌─────────────────┐
    │   A4 (验证)      │
    │   小仓试探       │
    │   认识修正       │
    └─────────────────┘
             ↓
    ┌─────────────────┐
    │   A5 (执行)      │
    │   大仓执行       │
    │   实时调整       │
    └─────────────────┘
             ↓
    ┌─────────────────┐
    │   复盘 (再认识)  │←─┐
    │   真理验证       │  │ 实践、认识、
    │   认识发展       │  │ 再实践、再认识
    └─────────────────┘  │
             ↓           │
    ┌─────────────────┐  │
    │  下一轮A1-A3    │──┘
    │  (基于新认识)   │
    └─────────────────┘
             ↓
          (螺旋上升)
```

---

**文件版本**: v1.0  
**创建时间**: 2026-04-26  
**对应SKILL**: A7-practice-theory
