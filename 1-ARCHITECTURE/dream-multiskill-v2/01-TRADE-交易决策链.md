# 1-TRADE：A0-A9 交易决策链
> **原始SKILL**: dream-contradiction-theory, dream-strategy-research, dream-first-principles,
> dream-strategy-designer, dream-tactical-validator, dream-tactical-executor,
> dream-intelligence-monitor, A7-practice-theory, A8-theory-practice-verification,
> dream-exit-skill-v2, dream-regime-detector, dream-signal-scoring-spec,
> dream-risk-position-sizing, dream-pretrade-gatekeeper, dream-execution-cost-model,
> dream-strategy-parser

---

## 架构总览

```
A0 矛盾论               ← 贯穿全流程，矛盾=方向
 ↓
A1 深度调研             输入：市场/链上/宏观
 ↓
A2 第一性原理           分析：阻力最小路径+趋势
 ↓
A3 战略制定             输出：多情景+应急预案
 ↓
A4 战术验证             三层索引→高级委托验证
 ↓
A5 战术执行             综合判断→执行→仓位同步
 ↓
A6 情报监控             ← 持续运行，反馈A1-A2
 ↓
A7 实践论               ← 门禁：实践检验真理
 ↓
A8 理论验证             ← 治理：知行一致检验
 ↓
A9 离场决策             二层离场 + 四层风险管理
```

---

## A0 矛盾分析 (dream-contradiction-theory)
**定位**: A1/A2/A3的统一矛盾操作系统
**核心**: 蒸馏毛泽东《矛盾论》+《孙子兵法》+克劳塞维茨《战争论》

### 8维度矛盾分析
C1 趋势/震荡 | C2 主要/次要 | C3 内部/外部
C4 渐进/突变 | C5 普遍/特殊 | C6 量变/质变
C7 被压制信号 | C8 转化条件

### 5条铁律
1. **抓主要矛盾** — 复杂事物中必有一种主要矛盾
2. **矛盾转化** — 矛盾双方在条件成熟时转化
3. **两点论** — 看主要也要看次要
4. **重点论** — 矛盾的主要方面决定方向
5. **实践检验** — 矛盾分析的正确性由实践验证

### 4维评分法
力量对比 + 时间紧迫性 + 证据一致性 + 市场影响权重 → 主要矛盾排名

---

## A1 深度调研 (dream-strategy-research v1.7)
**定位**: 战略制定前的侦察兵

### 三角准则(不可绕过)
1. **记忆调研**: 调取MEMORY.md、daily logs、episodes
2. **历史类似行情调研**: 档案中心+外部搜索 → 相似度评分
3. **类似交易策略调研**: 学习相似情境下的策略应对

### 输出结构
```
research_report:
  - summary / market_state / macro_snapshot
  - contradiction_list (供A0/A2使用)
  - dream_insights (做梦部洞察,可选)
  - 顾问评审结论 (QT+RM)
```

---

## A2 第一性原理 (dream-first-principles v2.6)
**定位**: 战略制定的哲学根基

### 双维度分析
**基本面**: 资金流(L1宏观/L2 ETF/L3微观) + 情绪 + 地缘 + 政策
**技术面**: 趋势(MA轨迹法) + 动量(RSI/MACD) + 波动(ATR/Bollinger)

### 左右脑科学方法
- **左脑**: 确定性规则引擎 (IF RSI>70 → -20分)
- **右脑**: 模糊模式识别 (形态/情绪/机构观点)
- **辩证统一**: 左右脑+A0主要矛盾→最终方向

### 阻力最小路径计算
`阻力评分 = Σ(成本0.30 + 流动性0.35 + 拥挤0.20 + 波动0.15) × 权重`
路径判定: <40=UP, 40-60=NEUTRAL, >60=DOWN

### 逆向补偿机制(v2.3)
- FGI<40 + 费率≈零轴 → 阻力评分 -= 15 (空头力竭)
- FGI>70 + 费率≈零轴 → 阻力评分 += 15 (多头力竭)

### 宏观资产共振(v2.6)
黄金↑+BTC↑=通胀预期 | 黄金↑+BTC↓=避险 | 黄金↓+TSLA↑+BTC↑=风险偏好

---

## A3 战略制定 (dream-strategy-designer v2.7)
**定位**: 多情景推演+战略指令生成

### 8Phase流程
Phase 00: A0强制门禁 → Phase 0: 战略调研(工具+币种+策略+历史)
→ Phase 1: 输入验证 → Phase 2: 特征蒸馏 → Phase 3: 历史模式匹配
→ Phase 4: 战略合成 → Phase 5: 战略记忆库 → Phase 6: 战略做梦
→ Phase 7: 应急预案(黑天鹅) → Phase 8: 战略顾问评审(SC+QT)

### 输出结构
- strategy指令: 多情景(A/B/C) + 概率
- 应急预案: 黑天鹅/极端情景预案
- 战略记忆库更新

---

## A4 战术验证 (dream-tactical-validator v7.2)
**定位**: 为A3每个情景设计验证方案

### 三层索引体系(v7.0核心)
1. **策略索引**: 大师→联网→实践 (按序)
2. **工具索引**: Regime→工具匹配矩阵
3. **跨资产设计**: 宏观资产池+相关性+组合

### 10条强约束
V1 仅操作DEMO | V2-V10 见完整SKILL

---

## A5 战术执行 (dream-tactical-executor v3.8)
**定位**: 综合判断决策执行

### 核心链路
A4验证报告 → A6情报 → 综合判断 → 决策执行 → 仓位同步

### 自动/手动切换
- A4确定性高(SI≥±30+Edge同向≥20) → 内置A5自动执行
- 确定性不高 → 等待A5综合判断(A4+A6)

### 门禁
- A7实践论门禁 (INDEPENDENT_AUTO)
- RM顾问评审否决权

---

## A6 情报监控 (dream-intelligence-monitor)
**定位**: 永不间断的市场雷达

### 监控等级
- L1 ROUTINE: 每4h常规行情
- L1.5 SIGNIFICANT: 显著变化→增量更新A2矛盾图谱
- L2 ALERT: 异常→P0告警+强制触发A1

---

## A7 实践论 (A7-practice-theory)
**定位**: 实践是检验真理的唯一标准
**触发**: A5执行前强制调用
**输出**: practice_log → truth_verification

---

## A8 理论验证 (A8-theory-practice-verification)
**定位**: 治理闭环—检验知行一致性
**输出**: hypothesis_template → verification_result → self_criticism

---

## A9 离场决策 (dream-exit-skill-v2)
**定位**: 4层离场决策链 + 21事件风险库
**核心**: 风险预算耗尽 → 趋势反转 → 事件触发 → 时间到期

---

## 配套组件

### Regime检测器
7种Regime + 三屏检测(周/日/60min) + 每日3次定时检测

### 信号评分(signal-scoring-spec)
6维度加权 + 6种Regime自适应 + 战略-战术冲突裁决(RULE_001-004)

### 执行前门禁(pretrade-gatekeeper)
熔断: 日回撤4%/单笔3%/连续止损3次/RSI极值85/15
仓位: 20%单笔/5x杠杆/2%风险

### 仓位管理(risk-position-sizing)
基于风险预算+波动率缩放的仓位计算
