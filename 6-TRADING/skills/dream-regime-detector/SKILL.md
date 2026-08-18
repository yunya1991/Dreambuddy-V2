# Dream-Regime-Detector | 市场Regime检测与自动化触发

**版本**: v1.0
**创建时间**: 2026-04-27
**触发词**: regime检测、市场状态、Regime变化、自动化蒸馏触发

---

## 核心功能

### 1️⃣ Regime形态库检测

基于`.knowledge_base/1_regime_patterns/`中的形态库，执行三维度检测:

| 维度 | 检测内容 | 数据来源 |
|:---|:---|:---|
| **技术指标** | MA200、MACD、RSI、ADX、布林带 | OKX行情API |
| **基本面** | 利率周期、通胀Regime | 联网搜索 |
| **复合信号** | 三屏MA、Elder系统 | 综合计算 |

### 2️⃣ 三屏检测 (Alexander Elder)

```
Screen 1 (周线) ─── 长期趋势过滤
    │
    ▼
Screen 2 (日线) ─── 中期方向确认
    │
    ▼
Screen 3 (60分钟) ─ 入场时机选择
```

### 3️⃣ 自动化蒸馏触发

| 触发类型 | 条件 | 动作 |
|:---|:---|:---|
| **Regime突变** | 形态库中的Regime发生变化 | 评估大师匹配度 |
| **匹配度骤降** | regime_fit_score下降>20% | 触发冻结/蒸馏 |
| **未覆盖Regime** | 出现新Regime | 触发新大师蒸馏 |
| **高波动** | ATR>2x均值 | 降仓告警 |

---

## 检测流程

```yaml
REGIME_DETECTION_WORKFLOW:
  1. 获取市场数据:
     - BTC/USDT价格 (OKX API)
     - MA(20/50/200)
     - MACD, RSI, ADX
     - ATR, Bollinger Bands
  
  2. 执行形态检测:
     - 调用 knowledge_base/1_regime_patterns/
     - 匹配当前Regime类型
     - 计算置信度
  
  3. 基本面检测 (联网):
     - FOMC政策信号
     - CPI/通胀数据
     - 收益率曲线
  
  4. 复合Regime输出:
     - 技术Regime + 基本面Regime
     - 综合评分
     - 操作建议
  
  5. 触发评估:
     - 检查大师匹配度
     - 判断是否触发蒸馏
```

---

## 定时执行

### 每日3次检测 (自动化)

```yaml
scheduled_detection:
  times:
    - "04:00 CST"  # 亚洲开盘前检测
    - "12:00 CST"  # 美国开盘前检测
    - "20:00 CST"  # 美国盘中检测
  
  actions:
    - detect_current_regime
    - compare_with_previous
    - check_master_fit
    - evaluate_distillation_trigger
    - output_report
    - update_knowledge_base
```

---

## 输出格式

```json
{
  "timestamp": "2026-04-27T04:00:00+08:00",
  "regime_detection": {
    "technical": {
      "primary": "TREND_BULL",
      "confidence": 0.85,
      "indicators": {
        "ma200": "above",
        "ma50_above_ma200": true,
        "adx": 28,
        "macd": "positive",
        "rsi": 58,
        "bollinger_width": "normal"
      }
    },
    "fundamental": {
      "primary": "RATE_EASING",
      "confidence": 0.70,
      "cpi": 2.8,
      "fed_policy": "cutting"
    },
    "composite": {
      "score": 45,
      "signal": "BULLISH",
      "action": "重仓操作"
    }
  },
  "master_fit": {
    "livermore_v2": {
      "regime_fit": 88,
      "current_fit": 88,
      "change": 0
    },
    "tharp_v2": {
      "regime_fit": 88,
      "current_fit": 75,
      "change": -13
    }
  },
  "distillation_trigger": {
    "should_trigger": false,
    "reason": null,
    "recommended_actions": [
      "继续观察Tharp匹配度变化"
    ]
  }
}
```

---

## 触发规则配置

```yaml
DISTILLATION_TRIGGER_RULES:
  # Regime突变触发
  regime_change:
    enabled: true
    check_interval_hours: 4
    min_confidence: 0.7
    actions:
      - evaluate_master_fit
      - alert_boss_secretary
  
  # 匹配度骤降触发
  fit_score_drop:
    enabled: true
    threshold: 0.8  # 下降20%触发
    window_hours: 24
    actions:
      - P0_alert
      - freeze_master_candidate
      - schedule_distillation
  
  # 未覆盖Regime触发
  uncovered_regime:
    enabled: true
    actions:
      - P1_alert
      - schedule_new_distillation
  
  # 高波动降仓触发
  high_volatility:
    enabled: true
    atr_threshold: 2.0  # ATR > 2x MA_ATR
    actions:
      - alert_reduce_position
      - recommend_options_hedge
```

---

## 集成点

| 组件 | 集成方式 |
|:---|:---|
| **A1调研** | 提供Regime检测结果作为调研输入 |
| **A6情报监控** | 共享Regime数据 |
| **master-regime-fit-scorer** | 计算大师匹配度 |
| **master-distillation-orchestrator** | 触发蒸馏任务 |
| **boss-secretary** | 发送告警通知 |
| **knowledge_base** | 读取Regime形态库 |

---

## 执行示例

```bash
# 手动执行Regime检测
regime-detector --mode=full --output=json

# 仅检测技术指标
regime-detector --mode=technical

# 检测并评估蒸馏触发
regime-detector --mode=full --check-distillation=true

# 定时执行 (通过automation)
regime-detector --scheduled --interval=4h
```

---

## 知识库依赖

```
.knowledge_base/1_regime_patterns/
├── INDEX.md                    ✅
├── technical/
│   ├── TREND_BULL_v1.md       ✅
│   ├── TREND_BEAR_v1.md       ✅
│   ├── RANGE_BOUND_v1.md      ✅
│   ├── BREAKOUT_v1.md         ✅
│   └── HIGH_VOLATILITY_v1.md  ✅
└── fundamental/
    ├── RATE_CYCLE_v1.md        ✅
    └── INFLATION_REGIME_v1.md ✅
```

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|:---|:---|:---|
| v1.0 | 2026-04-27 | 初版，集成技术+基本面Regime检测 |
