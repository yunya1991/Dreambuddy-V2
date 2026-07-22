# 交易分析评估报告
**报告ID**: eval_20260721_124233
**生成时间**: 2026-07-21T12:42:33.274259

## 概览
- 分析交易数: 219
- 盈利交易数: 0
- 胜率: 0.0%
- 平均盈亏: 0.00%

## 亏损原因分布

## 模块能力评估

### C1 - 技术扫描
| 指标 | 值 |
|------|-----|
| 交易数 | 168 |
| 胜率 | 49.6% |
| 准确率 | 45.2% |
| 盈亏比 | 1.00 |
| 稳定性 | 0.50 |

### C3 - 波动率分析
| 指标 | 值 |
|------|-----|
| 交易数 | 168 |
| 胜率 | 49.2% |
| 准确率 | 45.2% |
| 盈亏比 | 1.00 |
| 稳定性 | 0.48 |

### G1 - 风控
| 指标 | 值 |
|------|-----|
| 交易数 | 100 |
| 胜率 | 57.2% |
| 准确率 | 28.0% |
| 盈亏比 | 1.00 |
| 稳定性 | 0.62 |

### C2 - 动量分析
| 指标 | 值 |
|------|-----|
| 交易数 | 68 |
| 胜率 | 48.7% |
| 准确率 | 70.6% |
| 盈亏比 | 1.00 |
| 稳定性 | 0.50 |

### F1 - 新闻分析
| 指标 | 值 |
|------|-----|
| 交易数 | 51 |
| 胜率 | 49.2% |
| 准确率 | 31.4% |
| 盈亏比 | 1.00 |
| 稳定性 | 0.50 |

### F2 - 资金流分析
| 指标 | 值 |
|------|-----|
| 交易数 | 51 |
| 胜率 | 49.9% |
| 准确率 | 31.4% |
| 盈亏比 | 1.00 |
| 稳定性 | 0.51 |

### F3 - 估值分析
| 指标 | 值 |
|------|-----|
| 交易数 | 51 |
| 胜率 | 49.2% |
| 准确率 | 31.4% |
| 盈亏比 | 1.00 |
| 稳定性 | 0.50 |

### F4 - 链上数据
| 指标 | 值 |
|------|-----|
| 交易数 | 51 |
| 胜率 | 48.1% |
| 准确率 | 31.4% |
| 盈亏比 | 1.00 |
| 稳定性 | 0.43 |

## 编排推荐

### BEAR_HIGH_EXHAUSTION
- **推荐链路**: c_chain
- **推荐节点**: C2, C1, C3
- **置信度**: 88.5%
- **预期改进**: 19.3%
- **理由**: 基于BEAR趋势HIGH波动率场景，历史最优模式: c_chain，强模块: C2, C1, C3

### NEUTRAL_EXTREME_DECELERATING
- **推荐链路**: c_chain
- **推荐节点**: C1, C3, G1, A0, A7, A5
- **置信度**: 42.2%
- **预期改进**: -3.9%
- **理由**: 基于NEUTRAL趋势EXTREME波动率场景，历史最优模式: c_chain，强模块: C1, C3

### BEAR_NORMAL_EXHAUSTION
- **推荐链路**: c_chain
- **推荐节点**: C2, C1, C3
- **置信度**: 80.4%
- **预期改进**: 15.2%
- **理由**: 基于BEAR趋势NORMAL波动率场景，历史最优模式: c_chain，强模块: C2, C1, C3

### BEAR_LOW_EXHAUSTION
- **推荐链路**: f_chain
- **推荐节点**: C2, C1, A1, A4, A5
- **置信度**: 38.5%
- **预期改进**: -5.8%
- **理由**: 基于BEAR趋势LOW波动率场景，历史最优模式: f_chain，强模块: C2

### BEAR_HIGH_ACCELERATING
- **推荐链路**: c_chain
- **推荐节点**: C2, C1, C3, A0, A4, A5, A9
- **置信度**: 43.3%
- **预期改进**: -3.4%
- **理由**: 基于BEAR趋势HIGH波动率场景，历史最优模式: c_chain，强模块: C2, C1, C3

### NEUTRAL_EXTREME_ACCELERATING
- **推荐链路**: c_g_chain
- **推荐节点**: C1, C3, G1
- **置信度**: 77.3%
- **预期改进**: 13.6%
- **理由**: 基于NEUTRAL趋势EXTREME波动率场景，历史最优模式: c_g_chain，强模块: C1, C3, G1

### BULL_LOW_DECELERATING
- **推荐链路**: f_chain
- **推荐节点**: C2, C1, A1, A4, A5
- **置信度**: 57.4%
- **预期改进**: 3.7%
- **理由**: 基于BULL趋势LOW波动率场景，历史最优模式: f_chain，强模块: C2

### NEUTRAL_HIGH_ACCELERATING
- **推荐链路**: f_chain
- **推荐节点**: F2, F1, F3, F4
- **置信度**: 84.2%
- **预期改进**: 17.1%
- **理由**: 基于NEUTRAL趋势HIGH波动率场景，历史最优模式: f_chain，强模块: F2, F1, F3

### NEUTRAL_HIGH_EXHAUSTION
- **推荐链路**: c_chain
- **推荐节点**: C2, C1, C3
- **置信度**: 88.5%
- **预期改进**: 19.2%
- **理由**: 基于NEUTRAL趋势HIGH波动率场景，历史最优模式: c_chain，强模块: C2, C1, C3

### NEUTRAL_NORMAL_EXHAUSTION
- **推荐链路**: full_chain
- **推荐节点**: C2, C1, G1, F2
- **置信度**: 79.7%
- **预期改进**: 14.8%
- **理由**: 基于NEUTRAL趋势NORMAL波动率场景，历史最优模式: full_chain，强模块: C2, C1, G1

### BEAR_NORMAL_DECELERATING
- **推荐链路**: full_chain
- **推荐节点**: C2, C1, C3, A1, A4, A5
- **置信度**: 55.6%
- **预期改进**: 2.8%
- **理由**: 基于BEAR趋势NORMAL波动率场景，历史最优模式: full_chain，强模块: C2, C1

### BULL_HIGH_DECELERATING
- **推荐链路**: full_chain
- **推荐节点**: C2, C1, G1, F2
- **置信度**: 87.6%
- **预期改进**: 18.8%
- **理由**: 基于BULL趋势HIGH波动率场景，历史最优模式: full_chain，强模块: C2, C1, G1

### BULL_EXTREME_EXHAUSTION
- **推荐链路**: c_g_chain
- **推荐节点**: C1, C3, G1
- **置信度**: 82.3%
- **预期改进**: 16.1%
- **理由**: 基于BULL趋势EXTREME波动率场景，历史最优模式: c_g_chain，强模块: C1, C3, G1

### BEAR_HIGH_DECELERATING
- **推荐链路**: c_chain
- **推荐节点**: C2, C1, C3
- **置信度**: 88.5%
- **预期改进**: 19.2%
- **理由**: 基于BEAR趋势HIGH波动率场景，历史最优模式: c_chain，强模块: C2, C1, C3

### BULL_NORMAL_EXHAUSTION
- **推荐链路**: full_chain
- **推荐节点**: C2, C1, G1, F2
- **置信度**: 83.9%
- **预期改进**: 17.0%
- **理由**: 基于BULL趋势NORMAL波动率场景，历史最优模式: full_chain，强模块: C2, C1, G1

### BULL_NORMAL_DECELERATING
- **推荐链路**: full_chain
- **推荐节点**: C2, C1, G1, F2
- **置信度**: 85.5%
- **预期改进**: 17.7%
- **理由**: 基于BULL趋势NORMAL波动率场景，历史最优模式: full_chain，强模块: C2, C1, G1

### BEAR_LOW_ACCELERATING
- **推荐链路**: f_chain
- **推荐节点**: F2, F1, F3, F4
- **置信度**: 78.0%
- **预期改进**: 14.0%
- **理由**: 基于BEAR趋势LOW波动率场景，历史最优模式: f_chain，强模块: F2, F1, F3

### BEAR_NORMAL_ACCELERATING
- **推荐链路**: c_chain
- **推荐节点**: C2, C1, C3
- **置信度**: 85.7%
- **预期改进**: 17.8%
- **理由**: 基于BEAR趋势NORMAL波动率场景，历史最优模式: c_chain，强模块: C2, C1, C3

### NEUTRAL_NORMAL_DECELERATING
- **推荐链路**: c_g_chain
- **推荐节点**: C1, C3, G1
- **置信度**: 73.1%
- **预期改进**: 11.5%
- **理由**: 基于NEUTRAL趋势NORMAL波动率场景，历史最优模式: c_g_chain，强模块: C1, C3, G1

### BULL_EXTREME_ACCELERATING
- **推荐链路**: c_g_chain
- **推荐节点**: C1, C3, G1
- **置信度**: 80.4%
- **预期改进**: 15.2%
- **理由**: 基于BULL趋势EXTREME波动率场景，历史最优模式: c_g_chain，强模块: C1, C3, G1

### BULL_LOW_EXHAUSTION
- **推荐链路**: c_f_chain
- **推荐节点**: C2, C1, F1, F3
- **置信度**: 85.9%
- **预期改进**: 18.0%
- **理由**: 基于BULL趋势LOW波动率场景，历史最优模式: c_f_chain，强模块: C2, C1, F1

### NEUTRAL_NORMAL_ACCELERATING
- **推荐链路**: c_g_chain
- **推荐节点**: C1, C3, A0, A7, A5
- **置信度**: 58.7%
- **预期改进**: 4.3%
- **理由**: 基于NEUTRAL趋势NORMAL波动率场景，历史最优模式: c_g_chain，强模块: C1, C3

### BEAR_EXTREME_EXHAUSTION
- **推荐链路**: c_g_chain
- **推荐节点**: C1, C3, G1
- **置信度**: 77.6%
- **预期改进**: 13.8%
- **理由**: 基于BEAR趋势EXTREME波动率场景，历史最优模式: c_g_chain，强模块: C1, C3, G1

### NEUTRAL_LOW_EXHAUSTION
- **推荐链路**: full_chain
- **推荐节点**: C1, C3, A0, A7, A5
- **置信度**: 52.0%
- **预期改进**: 1.0%
- **理由**: 基于NEUTRAL趋势LOW波动率场景，历史最优模式: full_chain，强模块: C1

### BULL_NORMAL_ACCELERATING
- **推荐链路**: full_chain
- **推荐节点**: C2, C1, G1, F2
- **置信度**: 83.2%
- **预期改进**: 16.6%
- **理由**: 基于BULL趋势NORMAL波动率场景，历史最优模式: full_chain，强模块: C2, C1, G1

### NEUTRAL_HIGH_DECELERATING
- **推荐链路**: c_chain
- **推荐节点**: C2, C1, C3
- **置信度**: 89.0%
- **预期改进**: 19.5%
- **理由**: 基于NEUTRAL趋势HIGH波动率场景，历史最优模式: c_chain，强模块: C2, C1, C3

### BEAR_EXTREME_DECELERATING
- **推荐链路**: c_g_chain
- **推荐节点**: C1, C3, G1
- **置信度**: 77.4%
- **预期改进**: 13.7%
- **理由**: 基于BEAR趋势EXTREME波动率场景，历史最优模式: c_g_chain，强模块: C1, C3, G1

### NEUTRAL_LOW_DECELERATING
- **推荐链路**: c_g_chain
- **推荐节点**: C1, C3, A0, A7, A5
- **置信度**: 58.7%
- **预期改进**: 4.3%
- **理由**: 基于NEUTRAL趋势LOW波动率场景，历史最优模式: c_g_chain，强模块: C1, C3

### NEUTRAL_LOW_ACCELERATING
- **推荐链路**: c_chain
- **推荐节点**: C1, C3, A0, A7, A5
- **置信度**: 39.8%
- **预期改进**: -5.1%
- **理由**: 基于NEUTRAL趋势LOW波动率场景，历史最优模式: c_chain，强模块: C1, C3

### BULL_HIGH_EXHAUSTION
- **推荐链路**: full_chain
- **推荐节点**: C2, C1, G1, F2
- **置信度**: 88.3%
- **预期改进**: 19.1%
- **理由**: 基于BULL趋势HIGH波动率场景，历史最优模式: full_chain，强模块: C2, C1, G1

### BEAR_EXTREME_ACCELERATING
- **推荐链路**: c_g_chain
- **推荐节点**: C1, C3, G1, A0, A4, A5
- **置信度**: 40.0%
- **预期改进**: -5.0%
- **理由**: 基于BEAR趋势EXTREME波动率场景，历史最优模式: c_g_chain，强模块: C1, C3, G1

### BULL_LOW_ACCELERATING
- **推荐链路**: f_chain
- **推荐节点**: F2, F1, F3, F4
- **置信度**: 81.3%
- **预期改进**: 15.7%
- **理由**: 基于BULL趋势LOW波动率场景，历史最优模式: f_chain，强模块: F2, F1, F3

### BEAR_LOW_DECELERATING
- **推荐链路**: f_chain
- **推荐节点**: C2, C1, A1, A4, A5
- **置信度**: 34.1%
- **预期改进**: -7.9%
- **理由**: 基于BEAR趋势LOW波动率场景，历史最优模式: f_chain，强模块: C2

### BULL_EXTREME_DECELERATING
- **推荐链路**: c_g_chain
- **推荐节点**: C1, C3, G1
- **置信度**: 78.8%
- **预期改进**: 14.4%
- **理由**: 基于BULL趋势EXTREME波动率场景，历史最优模式: c_g_chain，强模块: C1, C3, G1

### NEUTRAL_EXTREME_EXHAUSTION
- **推荐链路**: c_g_chain
- **推荐节点**: C1, C3, G1
- **置信度**: 77.3%
- **预期改进**: 13.7%
- **理由**: 基于NEUTRAL趋势EXTREME波动率场景，历史最优模式: c_g_chain，强模块: C1, C3, G1

### BULL_HIGH_ACCELERATING
- **推荐链路**: full_chain
- **推荐节点**: C2, C1, G1, F2
- **置信度**: 87.9%
- **预期改进**: 19.0%
- **理由**: 基于BULL趋势HIGH波动率场景，历史最优模式: full_chain，强模块: C2, C1, G1

## 改进建议