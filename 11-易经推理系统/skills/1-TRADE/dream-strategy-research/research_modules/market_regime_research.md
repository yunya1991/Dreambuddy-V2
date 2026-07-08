# 市场典型Regime调研 | Market Regime Research

**版本**: v1.0
**更新时间**: 2026-04-27
**来源**: 集成到A1战略调研部

---

## 调研功能

### 1️⃣ Regime形态库查询

A1每次调研时，必须检查知识库中的Regime形态库：

```yaml
regime_check:
  1. 读取 .knowledge_base/1_regime_patterns/
  2. 对比当前市场状态与已有Regime
  3. 评估是否匹配已知形态
  4. 识别未覆盖的Regime类型
```

### 2️⃣ 形态库更新

当发现新的市场形态时：

1. 识别新形态特征
2. 编写形态定义文档
3. 保存到 `.knowledge_base/1_regime_patterns/`
4. 标记为"待验证"状态

### 3️⃣ 三屏检测 (Elder)

```yaml
triple_screen_research:
  Screen1_周线:
    检测: EMA(26)方向, Force Index周线
    目的: 识别长期趋势
    
  Screen2_日线:
    检测: MACD日线, RSI日线
    目的: 确认中期方向
    
  Screen3_60分钟:
    检测: Stochastic
    目的: 选择入场时机
```

---

## 输出格式

```yaml
regime_research_output:
  timestamp: "2026-04-27T08:00:00+08:00"
  
  current_regime:
    technical: TREND_BULL
    fundamental: RATE_EASING
    composite_score: 45
    confidence: 0.85
  
  pattern_match:
    matched: RANGE_BOUND
    similarity: 0.75
    unmatched_features: []
  
  new_patterns_identified:
    - name: null
      confidence: null
  
  regime_change_signals:
    - signal: "MA200突破"
      timestamp: "2026-04-27T08:00:00+08:00"
      confidence: 0.70
  
  recommendations:
    - "继续使用TREND_BULL策略"
    - "关注MA50支撑"
```

---

## 知识库同步

每次A1调研后，更新以下文件：

| 更新内容 | 目标文件 |
|:---|:---|
| 当前Regime | `1_regime_patterns/current_regime.json` |
| 历史Regime | `1_regime_patterns/history/` |
| 新形态 | `1_regime_patterns/technical/NEW_PATTERN_vX.md` |

---

## 触发规则

| 触发条件 | 动作 |
|:---|:---|
| 识别新Regime | 通知boss-secretary，标记待评估 |
| Regime变化 | 触发distillation评估 |
| 形态库缺失 | 创建新形态文档 |

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|:---|:---|:---|
| v1.0 | 2026-04-27 | 初版，Regime形态库集成、三屏检测 |
