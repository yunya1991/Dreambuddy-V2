# dream-intelligence-analysis 集成规范 (跨团队注入 — Team A + Gate C + Process D)

> **原始 SKILL**: dream-multiskill-v2/skills/2-INTELLIGENCE/dream-intelligence-analysis/SKILL.md v1.0.0
> **集成方式**: 纯提示词注入（无需新建文件结构）
> **集成位置**: Screen1 A1/A2/A3 + Gate C (B6) + Process D A8

---

## 一、职责

将 CIA《情报分析心理学》+ 《结构化分析技术》的核心方法论（认知偏见检查清单、ACH 竞争性假设分析、红队分析）注入到关键决策节点，系统性减少分析偏差。

---

## 二、注入规范

### 2.1 Screen 1 — A1 (dream-strategy-research) 注入

在 A1 调研提示词末尾追加：

```
[认知偏见检查 — IA-A1]
在输出调研报告前执行：
1. 锚定偏见: 当前BTC价格是否过度影响方向判断？上次Screen1的方向是否在惯性延续？
2. 可得性启发: Tavily搜索结果中是否只引用了最显眼的新闻？反向证据是否被忽略？
3. 代表性启发: 是否因"看起来像"历史某次顶部/底部就做出判断，而缺乏深层因果验证？
→ 如发现偏见证据，在 a1-contradiction.md 末尾追加 [BIAS_FLAG: {偏见类型}] 标记
```

### 2.2 Screen 1 — A2 (dream-first-principles) 注入

```
[认知偏见检查 — IA-A2]
1. 确认偏见: A2推导是否在为Phase-0数据"找理由"？反向资金流逻辑是否同样成立？
2. 过度自信: 对趋势延续/逆转的概率是否使用了区间（如60-70%）而非点估计（"很可能"）？
3. 镜像思维: 是否假设所有市场参与者都与自己逻辑相同？多头/空头的反向动机是什么？
→ 如发现偏见证据，在 a2-first-principles.md 末尾追加 [BIAS_FLAG: {偏见类型}] 标记
```

### 2.3 Screen 1 — A3 (dream-strategy-designer) 注入 + 红队分析

```
[红队分析 — IA-A3]
在输出 S1/S2/S3 情景前，执行简化红队分析：
反论构建: 假设Screen1主方向（SHORT/LONG）是错误的 →
  ① 支持反向的3个最强理由
  ② 什么样的1周内可观察数据会证明主方向是错的？
  ③ 当前分析中最脆弱的假设是哪个？
→ 将红队分析写入 a3-simulation.md 末尾的 [RED_TEAM_ANALYSIS] 段落
→ 若红队论据强度 > 主方向论据的40%，在 strategy-type.json 中设置 red_team_flag: true
```

### 2.4 Gate C (B6 dream-pretrade-gatekeeper) 注入

在 Gate C 裁决前执行 ACH 矩阵，并读取 `red_team_flag` 动态调整阈值：

```
[ACH竞争性假设 — IA-GC]
输入读取: 读取 sessions/{最新Screen1_id}/team-a/screen1/strategy-type.json 的 red_team_flag

假设A: 入场信号有效（主假设）
假设B: 入场信号为虚假信号（竞争假设）

诊断性证据（来自 B3 scores_result）:
① 资金费率方向是否与入场方向一致？（诊断性：高）
② Screen1 btc_price_basis 偏差是否 <5%？（诊断性：高）
③ A7 gate score 是否 >30/40？（诊断性：中）

red_team_flag 影响:
→ red_team_flag = true：将 Gate C 通过阈值从 composite_confidence > 60 提高到 > 70
   （上周 A3 已标记反向风险，本次入场需更高信心才可通过）
→ red_team_flag = false 或文件不存在：使用默认阈值 composite_confidence > 60

裁决规则:
→ 若假设B的高诊断证据数量 ≥ 假设A → 自动降级为 SKIP
→ 将 ACH 摘要写入 gate-c/pretrade-check.json 的 ach_summary 字段，包含:
   { "red_team_flag_applied": true/false, "threshold_used": 60/70, "ach_result": "PASS/SKIP" }
```

### 2.5 Process D (A8) 注入

```
[系统性偏见审查 — IA-PD]
1. 确认偏见: 上周 A1/A2/A3 的 BIAS_FLAG 记录中，哪种偏见频率最高？
2. 群体思维: 三子Agent方向是否总一致？是真正共识还是压抑了分歧声音？
3. 过度自信: Screen1方向的实际准确率 vs 预测置信度是否吻合（校准度检查）？
→ 输出到 review/a8-reflection.json 新增 bias_audit 字段
```

---

## 三、产物路径汇总

| 注入位置 | 新增产物 | 路径 |
|---------|---------|------|
| A1 | `[BIAS_FLAG]` 标记 | `sessions/{id}/team-a/screen1/raw/a1-contradiction.md` |
| A2 | `[BIAS_FLAG]` 标记 | `sessions/{id}/team-a/screen1/raw/a2-first-principles.md` |
| A3 | `[RED_TEAM_ANALYSIS]` + `red_team_flag` | `a3-simulation.md` + `strategy-type.json` |
| Gate C | `ach_summary` (含 `red_team_flag_applied`, `threshold_used`) | `sessions/{id}/gate-c/pretrade-check.json` |
| A8 | `bias_audit` 字段 | `sessions/{id}/review/a8-reflection.json` |

---

## 四、red_team_flag 完整流转链

```
A3 (dream-strategy-designer)
  → 红队论据强度 > 40%
  → 写入 strategy-type.json: { red_team_flag: true }
        ↓
master-seminar (MS)
  → red_team_flag=true → 强化4阵营辩论模式
        ↓
Gate C (B6, IA-GC)
  → 读取 red_team_flag → 将通过阈值从 60 升至 70
  → ach_summary.red_team_flag_applied: true
```

---

## 五、核心偏见参考（7大高频偏见）

| 偏见 | 场景 | 缓解工具 |
|------|------|---------|
| 确认偏见 | A2推导 / A8复盘 | 反向论据强制构建 |
| 锚定效应 | A1调研（价格锚定） | 检查最初假设有效性 |
| 镜像思维 | A2第一性原理 | 对手视角分析 |
| 过度自信 | A3情景概率 | 使用概率区间 |
| 可得性启发 | A1信息筛选 | 系统性反向搜索 |
| 群体思维 | 三Agent并行 | 红队分析独立运行 |
| 代表性启发 | 历史类比（配合AC） | 因果机制验证 |

---

*最后更新: 2026-05-26 v1.1 | 修复 GAP-H4: red_team_flag 完整流转链（A3→MS→Gate C）*
