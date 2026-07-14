# 离场战略评估报告（Phase 3 完整版）

**生成时间**: 2026-07-13T23:28:41.080175+00:00
**评估版本**: Phase 3 — 宏观+技术融合决策 + AAM投递

## 一、核心结论

- **整体立场**: CLOSE
- **总持仓数**: 21
- **建议平仓**: 11 个
- **建议减仓**: 7 个
- **建议持有**: 3 个
- **建议提止盈**: 0 个

## 二、宏观分析摘要

- **A1 趋势方向**: NEUTRAL_UP
- **A1 信号充分性**: MODERATE
- **A1 BTC RSI**: 73.0
- **A2 阻力最小路径**: UP
- **A2 路径置信度**: 78%
- **A2 市场状态**: TREND_STRONG
- **A3 战略方向**: LONG
- **A3 仓位修正**: 0.78x
- **🌙 做梦产物**: 已集成（最新 2026-07-12T23:45:00+08:00）
- **📚 历史档案**: 3 个相似案例

## 三、技术离场摘要

- **P0 硬退出触发**: 11 个
- **P1 技术信号触发**: 11 个
- **技术平仓建议**: 11 个
- **技术减仓建议**: 0 个

## 四、融合决策（逐持仓）

| 系统 | 币种 | 方向 | 宏观建议 | 技术建议 | 融合建议 | 紧急度 | 可自动执行 |
|------|------|------|----------|----------|----------|--------|:----------:|
| agent_a | ARB | SHORT | CLOSE | HOLD | **REDUCE** | HIGH | ❌ |
| agent_a | UNI | SHORT | CLOSE | HOLD | **REDUCE** | HIGH | ❌ |
| agent_a | ZRO | SHORT | CLOSE | HOLD | **REDUCE** | HIGH | ❌ |
| agent_a | ENA | SHORT | CLOSE | HOLD | **REDUCE** | HIGH | ❌ |
| agent_b | ETH | SHORT | CLOSE | HOLD | **REDUCE** | HIGH | ❌ |
| agent_b | ARB | LONG | RAISE_TP | HOLD | **HOLD** | LOW | ❌ |
| agent_b | LDO | SHORT | CLOSE | HOLD | **REDUCE** | HIGH | ❌ |
| agent_b | WLD | LONG | RAISE_TP | HOLD | **HOLD** | LOW | ❌ |
| agent_b | ZRO | LONG | HOLD | HOLD | **HOLD** | LOW | ❌ |
| agent_b | ZEC | SHORT | CLOSE | HOLD | **REDUCE** | HIGH | ❌ |
| v15_martin | TIA | LONG | HOLD | CLOSE | **CLOSE** | CRITICAL | ❌ |
| v15_martin | INJ | LONG | HOLD | CLOSE | **CLOSE** | CRITICAL | ❌ |
| v15_martin | BTC | LONG | HOLD | CLOSE | **CLOSE** | CRITICAL | ❌ |
| v15_martin | ZEC | LONG | HOLD | CLOSE | **CLOSE** | CRITICAL | ❌ |
| v15_martin | NEAR | LONG | HOLD | CLOSE | **CLOSE** | CRITICAL | ❌ |
| v15_martin | WLD | LONG | HOLD | CLOSE | **CLOSE** | CRITICAL | ❌ |
| yijing_bcrm | DOT | LONG | HOLD | CLOSE | **CLOSE** | CRITICAL | ❌ |
| yijing_bcrm | BTC | SHORT | CLOSE | CLOSE | **CLOSE** | CRITICAL | ❌ |
| yijing_bcrm | DOGE | LONG | HOLD | CLOSE | **CLOSE** | CRITICAL | ❌ |
| yijing_bcrm | XRP | SHORT | CLOSE | CLOSE | **CLOSE** | CRITICAL | ❌ |
| yijing_bcrm | XAU | SHORT | CLOSE | CLOSE | **CLOSE** | CRITICAL | ❌ |

## 五、权限与执行说明

| 系统 | 权限等级 | 自动执行阈值 | 最大减仓比例 |
|------|----------|------------|------------|
| agent_a | ADVISE | CRITICAL | 30% |
| agent_b | ADVISE | CRITICAL | 30% |
| agent_c | ADVISE | CRITICAL | 30% |
| v15_martin | NOTIFY | CRITICAL | 0% |
| yijing_bcrm | ADVISE | HIGH | 50% |
| screen_trend | NOTIFY | CRITICAL | 0% |

> 说明：当前为建议制，所有建议需人工确认后执行。如需自动执行，请在 `config/permission_config.json` 中调整权限等级。

## 七、免责声明

- 本报告仅供参考，不构成投资建议
- 宏观评估为战略级别，各系统技术离场仍为第一道防线
- 建议制模式，不自动执行任何交易操作
- 投资有风险，入市需谨慎