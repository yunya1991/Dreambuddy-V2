# 📘 认识阶段工作流 (A1-A3)

## 实践论指导

> "认识从实践始，经过实践得到了理论的认识，还须再回到实践去。"  
> "你要知道梨子的滋味，你就得变革梨子，亲口吃一吃。"

## 工作流目标

将A1(调研)、A2(第一性原理分析)、A3(战略制定)统一为**认识阶段**，确保认识来源于实践，为A4验证奠定基础。

## 输入

- 市场数据 (价格、成交量、费率等)
- 宏观环境 (经济数据、政策等)
- 历史实践记录 (过往A4-A5结果)

## 输出

- `recognition_report.json` - 认识报告
- A3战略方案 (strategy_directive.json等)

## 工作流步骤

### Step 1: 调查研究 (A1)

**实践论原理**: "没有调查，没有发言权。"

**A1任务**:
1. 收集市场数据 (OKX API)
2. 收集宏观数据 (Tavily搜索)
3. 回顾历史实践 (读取A4-A5历史记录)
4. 识别主要矛盾 (调用A0矛盾论)

**输出**: `a1_research_report.md`

**A7门禁检查**:
```python
def a7_a1_gate():
    checks = {
        "调查全面": "是否收集了多维数据? (技术/宏观/历史实践)",
        "实践来源": "是否回顾了历史实践记录? (避免本本主义)",
        "矛盾识别": "是否识别了当前主要矛盾? (A0调用)"
    }
    return evaluate_gates(checks)
```

### Step 2: 第一性原理分析 (A2)

**实践论原理**: "认识有待于深化，认识的感性阶段有待于发展到理性阶段。"

**A2任务**:
1. 分析市场本质 (阻力最小方向)
2. 分析趋势动力 (延续性)
3. 识别认识偏差 (对比历史实践)
4. 形成理性认识

**输出**: `a2_first_principles.md`

**A7门禁检查**:
```python
def a7_a2_gate():
    checks = {
        "感性到理性": "是否从数据上升到了本质认识?",
        "实践检验": "认识是否经过历史实践检验?",
        "矛盾分析": "是否用A0矛盾论分析了矛盾转化?"
    }
    return evaluate_gates(checks)
```

### Step 3: 战略制定 (A3)

**实践论原理**: "认识从实践始，经过实践得到了理论的认识，还须再回到实践去。"

**A3任务**:
1. 基于A1-A2认识，制定战略
2. 设计验证方案 (如何A4小仓验证?)
3. 明确真理标准 (如何验证战略正确性?)
4. 输出可执行战略

**输出**: 
- `strategy_directive.json` - 战略指令
- `tactical_scenarios.json` - 战术场景
- `risk_budget.json` - 风险预算

**A7门禁检查**:
```python
def a7_a3_gate():
    checks = {
        "认识来源": "战略是否基于A1-A2认识? (禁止凭空制定)",
        "可验证性": "是否设计了A4验证方案? (实践第一性)",
        "真理标准": "是否明确了成功标准? (P&L/胜率/回撤)",
        "可执行性": "战略是否可执行的? (入场/止损/止盈明确)"
    }
    return evaluate_gates(checks)
```

### Step 4: 形成认识报告

**实践论原理**: "感性认识必须上升到理性认识。"

**任务**:
1. 汇总A1-A3认识
2. 明确认识来源 (实践基础)
3. 明确认识不确定性 (哪些未验证?)
4. 输出认识报告

**输出**: `recognition_report.json`

**模板**:
```json
{
  "recognition_id": "RECOG_20260426_01",
  "timestamp": "2026-04-26T10:40:00Z",
  "source": {
    "A1_research": "a1_research_20260426.md",
    "A2_analysis": "a2_first_principles_20260426.md",
    "A3_strategy": "strategy_directive_20260426.json"
  },
  "recognition": {
    "market_view": "BTC区间震荡 $76k-$79k",
    "main_contradiction": "多空力量均衡，等待突破",
    "strategy": "区间边界交易，突破确认后趋势跟踪",
    "uncertainty": "突破方向不确定，需A4验证"
  },
  "practice_foundation": {
    "historical_practice": "过往3次震荡市验证，胜率67%",
    "current_practice": "需A4小仓验证",
    "truth_criteria": "P&L>0, 胜率>50%, 最大回撤<15%"
  },
  "next_stage": "A4实践验证",
  "a7_gate_status": "PASS"
}
```

## 认识阶段注意事项

### ✅ 正确做法

1. **认识来源于实践**: 必须回顾历史实践记录
2. **调查研究先行**: A1必须充分调查，不能跳过
3. **矛盾分析**: 必须调用A0识别主要矛盾
4. **明确不确定性**: 认识有边界，不能绝对化

### ❌ 错误做法

1. **本本主义**: 只依赖历史规律，不回顾近期实践
2. **经验主义**: 只依赖历史经验，不总结理论认识
3. **跳过A1**: 直接A2-A3，认识来源不充分
4. **认识绝对化**: "市场一定会涨"，不承认不确定性

## 输出文件

1. `a1_research_report.md` - A1调研报告
2. `a2_first_principles.md` - A2第一性原理分析
3. `strategy_directive.json` - A3战略指令
4. `recognition_report.json` - 认识报告 (新增，A7核心输出)

## 与其他阶段的关系

```
认识阶段 (A1-A3)
    ↓ 输出: recognition_report.json
实践验证阶段 (A4)
    ↓ 输入: recognition_report.json
    ↓ 输出: verification_report.json + recognition_correction.json
实践执行阶段 (A5)
    ↓ 输入: verification_report.json
    ↓ 输出: execution_report.json + new_recognition.json
复盘阶段 (反思)
    ↓ 输入: execution_report.json
    ↓ 输出: reflection_report.json + updated_recognition.json
        ↓
     (回到认识阶段，螺旋上升)
```

---

**文件版本**: v1.0  
**创建时间**: 2026-04-26  
**对应SKILL**: A7-practice-theory
