# 离场战略评估报告（Phase 3 完整版）

**生成时间**: 2026-07-13T23:39:20.177966+00:00
**评估版本**: Phase 3 — 宏观+技术融合决策 + AAM投递

## 一、核心结论

- **整体立场**: CLOSE
- **总持仓数**: 22
- **建议平仓**: 11 个
- **建议减仓**: 4 个
- **建议持有**: 7 个
- **建议提止盈**: 0 个

## 二、宏观分析摘要

- **A1 趋势方向**: BEAR
- **A1 信号充分性**: MODERATE
- **A1 BTC RSI**: 19.6
- **A2 阻力最小路径**: DOWN
- **A2 路径置信度**: 80%
- **A2 市场状态**: TREND_EXHAUSTION
- **A3 战略方向**: SHORT
- **A3 仓位修正**: 0.56x
- **🌙 做梦产物**: 已集成（最新 2026-07-12T23:45:00+08:00）
- **📚 历史档案**: 3 个相似案例

## 三、技术离场摘要

- **P0 硬退出触发**: 11 个
- **P1 技术信号触发**: 18 个
- **技术平仓建议**: 11 个
- **技术减仓建议**: 7 个

## 四、策略离场设计原则

每个策略有自己的离场设计哲学，宏观评估尊重策略自身设计，仅在合理边界内提供建议：

| 策略 | 设计哲学 | 宏观影响力 | 技术权重 | 宏观权重 | 关键原则 |
|------|----------|-----------|---------|---------|---------|
| Agent A（LLM 原生） | 趋势跟踪 | 重要参考 | 40% | 60% | 明确的 L1 技术止损信号（自动化风控）... |
| Agent B（Dreambuddy 框架） | 趋势跟踪 | 宏观主导 | 40% | 60% | P0 硬风控底线... |
| Agent C（DreamOS 内核） | 趋势跟踪 | 宏观主导 | 40% | 60% | P0 硬风控底线... |
| 三屏趋势系统 | 趋势跟踪 | 补充参考 | 70% | 30% | 技术面明确的止损信号（趋势跟踪的铁律）... |
| V15 马丁策略 | 马丁格尔 | 仅观察 | 80% | 20% | 正常浮亏区间的马丁加仓（这是策略设计本身）... |
| 易经推理系统 | 情绪驱动 | 重要参考 | 50% | 50% | 卦象明确的离场信号（易经系统的核心规则）... |

> **核心原则**：宏观离场是「增强」而非「替代」策略原生离场机制。马丁策略浮亏是正常设计，不应因浮亏建议平仓；趋势跟踪以技术面为准，宏观仅作补充。

## 五、融合决策（逐持仓）

| 系统 | 币种 | 方向 | 宏观建议 | 调整后宏观 | 技术建议 | 融合建议 | 置信度 | 合理性 |
|------|------|------|----------|-----------|----------|----------|--------|--------|
| agent_a | ARB | SHORT | HOLD | HOLD | REDUCE | **HOLD** | 40% | ✅ |
| agent_a | WLD | LONG | CLOSE | CLOSE | HOLD | **REDUCE** | 48% | ✅ |
| agent_a | UNI | SHORT | HOLD | HOLD | REDUCE | **HOLD** | 40% | ✅ |
| agent_a | ZRO | SHORT | HOLD | HOLD | REDUCE | **HOLD** | 40% | ✅ |
| agent_a | ENA | SHORT | HOLD | HOLD | REDUCE | **HOLD** | 40% | ✅ |
| agent_b | ETH | SHORT | RAISE_TP | RAISE_TP | REDUCE | **HOLD** | 40% | ✅ |
| agent_b | ARB | LONG | CLOSE | CLOSE | HOLD | **REDUCE** | 48% | ✅ |
| agent_b | LDO | SHORT | RAISE_TP | RAISE_TP | REDUCE | **HOLD** | 40% | ✅ |
| agent_b | WLD | LONG | CLOSE | CLOSE | HOLD | **REDUCE** | 48% | ✅ |
| agent_b | ZRO | LONG | CLOSE | CLOSE | HOLD | **REDUCE** | 48% | ✅ |
| agent_b | ZEC | SHORT | RAISE_TP | RAISE_TP | REDUCE | **HOLD** | 40% | ✅ |
| v15_martin | TIA | LONG | CLOSE | CLOSE | CLOSE | **CLOSE** | 95% | ✅ |
| v15_martin | INJ | LONG | CLOSE | CLOSE | CLOSE | **CLOSE** | 95% | ✅ |
| v15_martin | BTC | LONG | CLOSE | CLOSE | CLOSE | **CLOSE** | 95% | ✅ |
| v15_martin | ZEC | LONG | CLOSE | CLOSE | CLOSE | **CLOSE** | 95% | ✅ |
| v15_martin | NEAR | LONG | CLOSE | CLOSE | CLOSE | **CLOSE** | 95% | ✅ |
| v15_martin | WLD | LONG | CLOSE | CLOSE | CLOSE | **CLOSE** | 95% | ✅ |
| yijing_bcrm | DOT | LONG | CLOSE | CLOSE | CLOSE | **CLOSE** | 95% | ✅ |
| yijing_bcrm | BTC | SHORT | HOLD | ~~HOLD~~ → **CLOSE** | CLOSE | **CLOSE** | 95% | ✅ |
| yijing_bcrm | DOGE | LONG | CLOSE | CLOSE | CLOSE | **CLOSE** | 95% | ✅ |
| yijing_bcrm | XRP | SHORT | HOLD | ~~HOLD~~ → **CLOSE** | CLOSE | **CLOSE** | 95% | ✅ |
| yijing_bcrm | XAU | SHORT | HOLD | ~~HOLD~~ → **CLOSE** | CLOSE | **CLOSE** | 95% | ✅ |

说明：
- **调整后宏观**：经过策略合理性检查后的宏观建议（如马丁浮亏不建议平仓）
- **合理性**：⚠️ 表示原始宏观建议被策略设计原则调整过

## 六、策略设计调整详情

所有宏观建议均通过策略合理性检查，无需调整。

## 七、权限与执行说明

| 系统 | 权限等级 | 自动执行阈值 | 最大减仓比例 |
|------|----------|------------|------------|
| agent_a | ADVISE | CRITICAL | 30% |
| agent_b | ADVISE | CRITICAL | 30% |
| agent_c | ADVISE | CRITICAL | 30% |
| v15_martin | NOTIFY | CRITICAL | 0% |
| yijing_bcrm | ADVISE | HIGH | 50% |
| screen_trend | NOTIFY | CRITICAL | 0% |

> 说明：当前为建议制，所有建议需人工确认后执行。如需自动执行，请在 `config/permission_config.json` 中调整权限等级。

## 九、免责声明

- 本报告仅供参考，不构成投资建议
- 宏观评估为战略级别，各系统技术离场仍为第一道防线
- 建议制模式，不自动执行任何交易操作
- 投资有风险，入市需谨慎