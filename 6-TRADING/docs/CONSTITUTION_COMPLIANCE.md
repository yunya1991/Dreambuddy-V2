# Dream-Constitution 6-TRADING 合规映射 v1.0

> **原文档**: dream-multiskill-v2/skills/0-CORE/dream-constitution/SKILL.md v2.9
> **本文件用途**: 将宪法中与交易决策直接相关的章节，逐条映射到 6-TRADING 执行流程。

---

## 一、总则

> 所有 6-TRADING 决策必须以本文件作为前置约束，优先于任何 SKILL 内部逻辑。

**核心原则**: 没有调查就没有发言权。Screen 1 Phase-0 数据采集是「调查」，跳过则无权产出方向判断。

---

## 二、Chapter 2 映射 — 双轨决策路径

宪法原文：
> P0/P1 重大交易通过专属 A1→A5 链执行；P2/常规研究通过 研究→顾问→执行 路径。

**6-TRADING 映射**:

| 宪法路径 | 6-TRADING 对应 | 触发条件 |
|---------|---------------|---------|
| P0 重大交易（A1→A5 链） | Team A Screen1 → Team A Screen2 → Team B Screen3 完整链 | 每周 Screen1 + 每日 Screen2/3 |
| P2 常规研究路径 | Process D A8 复盘 + knowledge 沉淀 | 每周一 Process D |
| A4→A6 约束唤醒链 | Team C C1(A6) 监控触发 Team B A4 补充验证 | 持仓期间 P0/P1 告警 |

**A4→A6 T1-T5 触发条件（Team C 使用）**:

| 触发等级 | 条件 | 动作 |
|---------|------|------|
| T1 价格异常 | 价格偏离 entry_price ±3% 且无持仓 | A6 增量报告 |
| T2 资金费率突变 | 资金费率变化 >2% 且持续 2h | A6 告警 + A4 验证 |
| T3 ETF流向逆转 | ETF 连续 3 日净流入 >5亿（空头持仓中） | A6 P1 告警 + A3 重评 |
| T4 宏观事件 | 美联储紧急声明 / 战争升级 / 重大监管事件 | A6 P0 告警 + A1→A3 重启 |
| T5 ATR 爆炸 | ATR > 2x 30日均值 | 强制减仓至 50% + A9 止损收紧 |

---

## 三、Chapter 4 映射 — 交易主链宪法

宪法原文：
> 日线趋势是所有日内决策的前提。最小阻力原则：在阻力最小方向操作。

**6-TRADING 映射**:

| 宪法条款 | 映射位置 | 执行规则 |
|---------|---------|---------|
| 日线趋势优先 | Screen 2 约束 | Screen 2 的 A1/A2/A3 分析必须在 Screen 1 方向约束下执行，不得独立得出相反方向 |
| 最小阻力原则 | Team B B3 评分 + B4 仓位 | 方向与 Screen 1 一致时 position_modifier +0.2；相反时禁止执行 |
| 入场等待原则 | Team B B7 A4 | 无确认信号（1h 拒绝K线+量能）时，A4 验证结果为 WAITING，不强制入场 |
| 止损=事实标准 | Team C C3 A9 | TP/SL 是宪法真理标准的具体化；止损价位一经设定不得手工删除 |

---

## 四、Chapter 14 映射 — ai-trading-compliance 三门禁

宪法原文：
> ai-trading-compliance 三门禁机制：H001-H009 硬门禁，任何一项触发则 HARD_FAIL。

**6-TRADING 映射 → Gate C (B6 dream-pretrade-gatekeeper)**:

| 硬门禁 | 宪法 H# | Gate C 对应 reason_code |
|--------|--------|------------------------|
| 无 Screen1 方向时不得开仓 | H001 | HARD_FAIL_NO_SCREEN1_DIRECTION |
| Screen1 有效期过期不得开仓 | H002 | HARD_FAIL_SCREEN1_EXPIRED |
| 方向与 Screen1 相反不得开仓 | H003 | HARD_FAIL_STRATEGY_DIRECTION_MISMATCH |
| 无止损设置不得开仓 | H004 | HARD_FAIL_NO_STOP_LOSS |
| 单笔超 150 USDT 不得执行 | H005 | HARD_FAIL_LEVERAGE_EXCEEDS_CAP |
| Gate C BLOCK 后禁止重试 | H006 | — (流程约束，非 code) |
| A7 门禁未通过不得执行 | H007 | HARD_FAIL_A7_GATE_FAILED |
| Phase-0 未完成不得启动 Screen | H008 | SCREEN1_BLOCKED (Team A 层面) |
| 复盘 proposal 未审核不得自动部署参数 | H009 | — (Process D 层面) |

---

## 五、§0 前置准备三问（所有团队通用）

每次触发前，执行提示词应隐式回答：

1. **我的职责是什么？** (Team A 纯研究 / Team B 入场执行 / Team C 监控离场 / Process D 复盘)
2. **我的约束是什么？** (上述 H001-H009 + 本团队的 HARD BLOCK 条件)
3. **我从上一次学到了什么？** (读取 knowledge/ + 最近 episodes)

---

*最后更新: 2026-05-26*
