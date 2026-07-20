# 震荡市增强器技术文档 (Ranging Market Enhancer)

> 版本：v1.0 | 状态：已上线 | 更新：2026-07-20

## 1. 设计背景

易经推理模型在连续10次亏损后，经A8批判性思维分析，定位核心矛盾：**趋势跟踪模型与震荡市环境错配**。模型在震荡市中频繁发出反向信号，导致止损被反复触发。

增强器作为5条优化建议的统一实现入口，嵌入交易流程，在保持趋势市信号效率的同时，大幅降低震荡市中的假信号。

## 2. 核心模块

### 2.1 模块定位

- **文件**：`scripts/memory_l4/ranging_market_enhancer.py`
- **类**：`RangingMarketEnhancer`（主增强器）、`HexagramDataDrivenCalibrator`（卦象校准器）
- **调用方**：`polling_trader.py` 的开仓决策链
- **回测**：`enhancer_backtest_engine.py`

### 2.2 五项优化措施

| # | 优化项 | 实现函数 | 作用 |
|---|--------|----------|------|
| 1 | MA200方向性偏向 | `_calc_directional_bias` | 长期趋势过滤反向信号 |
| 2 | 布林带双信号确认 | `_check_bollinger_confirmation` | 震荡市必须双重确认 |
| 3 | 动态止损宽度 | `_dynamic_atr_multipliers` | 按市场状态调整ATR倍数 |
| 4 | 置信度校准 | `calibrate_confidence` | 预测-实际胜率校准表 |
| 5 | 市场状态自适应 | `_identify_regime` | 5种状态差异化参数 |

## 3. 关键算法详解

### 3.1 市场状态识别（5种状态）

```
TREND_UP    : 趋势强度 > 0.4 且 价格在MA200上方
TREND_DOWN  : 趋势强度 > 0.4 且 价格在MA200下方
RANGING_UP  : 震荡市 + 价格在MA200上方
RANGING_DOWN: 震荡市 + 价格在MA200下方
SIDEWAYS    : 震荡市 + MA200不可用或价格在MA200附近
```

### 3.2 MA200方向性偏向

**算法**：`bias = base_bias × regime_factor`，范围 [-1.0, +1.0]

| 条件 | BTC基础偏向 | 其他币种 |
|------|------------|----------|
| 价格在MA200上方 | +0.6 | +0.3 |
| 价格在MA200上方 + MA200斜率向上 | +0.7 | +0.4 |
| 价格在MA200下方 | -0.6 | -0.3 |
| 价格在MA200下方 + MA200斜率向下 | -0.7 | -0.4 |

**状态调节因子**：
- 趋势市：0.3（趋势本身已有方向，偏向作用减弱）
- 震荡偏多/偏空：1.0（正常）
- 纯横盘：1.2（无方向时MA200偏向作为主要参考）

**影响**：
- 调整置信度阈值：偏多时做多阈值降低 `bias × 0.05`，做空阈值提高
- 反向交易额外过滤：震荡偏多时做空必须在阻力位附近

### 3.3 支撑阻力过滤

**摆动高低点检测**：窗口大小5根K线，左右各5根（共11根）

**判定规则**（仅在震荡市启用）：
- 距离 < 3% → 判定为"在支撑/阻力区"
- 做多 + 在阻力区 → 拒绝（`near_resistance_zone`）
- 做空 + 在支撑区 → 拒绝（`near_support_zone`）

**豁免**：置信度 ≥ 0.78 时跳过此过滤

### 3.4 布林带双信号确认

**信号类型**：
- `LOWER_BOUNCE`：下轨支撑反弹 → 做多
- `UPPER_REJECT`：上轨压力回落 → 做空
- `MID_BREAKOUT_UP/DOWN`：中轨突破
- `SQUEEZE`：布林带极度收窄（width < 0.8%）→ 不开仓
- `NONE`：无明确信号，按价格位置判定

**震荡市中NONE的处理**：
- 价格在上下10%区间内 → 位置合理，确认
- 价格在上轨附近（≥0.9）→ 仅确认做空
- 价格在下轨附近（≤0.1）→ 仅确认做多

**豁免**：置信度 ≥ 0.72 时跳过布林带确认

### 3.5 动态止损止盈

| 市场状态 | 止损倍数 | 止盈倍数 |
|----------|----------|----------|
| TREND_UP/DOWN | 1.5×ATR | 3.0×ATR |
| RANGING_UP/DOWN | 2.5×ATR | 4.5×ATR |
| SIDEWAYS | 3.0×ATR | 5.0×ATR |

### 3.6 置信度阈值推荐

| 市场状态 | 做多阈值 | 做空阈值 |
|----------|----------|----------|
| TREND_UP | 0.45 | 0.60 |
| TREND_DOWN | 0.60 | 0.45 |
| RANGING_UP | 0.50 | 0.58 |
| RANGING_DOWN | 0.58 | 0.50 |
| SIDEWAYS | 0.54 | 0.54 |

阈值还会根据方向偏向额外调整 ±0.05。

## 4. 集成与调用

### 4.1 集成点

在 `polling_trader.py` 的开仓决策链中：

```python
enhance_result = self.ranging_enhancer.enhance(
    price=price, direction=direction, confidence=confidence,
    closes=closes, highs=highs, lows=lows, atr=atr_val,
    is_ranging=is_ranging, ranging_confidence=ranging_confidence,
    trend_strength=trend_strength, coin=coin,
)
if not enhance_result.should_trade:
    return  # 被增强器过滤
```

### 4.2 回退机制

增强器调用异常时，回退到P0简单逻辑：
- 强震荡市（ranging_confidence ≥ 0.75）强制空仓
- 中等震荡市（ranging_confidence ≥ 0.5）阈值提高到0.7

### 4.3 平仓后更新校准

```python
self.ranging_enhancer.update_calibration([trade_for_cal])
self.ranging_enhancer.hex_calibrator.record_trade(...)
```

## 5. 回测验证结果

### 5.1 多币种回测汇总（1H周期，约8.5个月数据）

| 币种 | 策略 | 交易数 | 胜率% | 总收益% | 最大回撤% | 夏普比 |
|------|------|--------|-------|---------|-----------|--------|
| BTC | 基础 | 286 | 36.01 | -9.15 | 10.05 | -3.401 |
| BTC | 增强 | 11 | 36.36 | -0.49 | 1.35 | -0.425 |
| ETH | 基础 | 280 | 38.57 | -9.43 | 9.90 | -2.542 |
| ETH | 增强 | 38 | 47.37 | +1.48 | 2.41 | +0.737 |
| SOL | 基础 | 298 | 33.89 | -11.43 | 12.79 | -2.902 |
| SOL | 增强 | 39 | 33.33 | -1.82 | 2.85 | -0.841 |
| UNI | 基础 | 303 | 32.34 | -15.08 | 18.29 | -2.966 |
| UNI | 增强 | 59 | 33.90 | -6.14 | 8.44 | -1.773 |

### 5.2 核心结论

- ✅ **风控效果显著**：最大回撤降低 54%-87%，交易频率降低 80%-96%
- 🏆 **ETH效果最佳**：胜率提升8.8%，从亏损9.4%扭转为盈利1.5%
- 💡 **核心价值**：风控优先，在基础策略亏损的情况下大幅减少亏损幅度

## 6. 数据持久化

| 文件 | 用途 |
|------|------|
| `data/confidence_calibration.json` | 置信度校准表 |
| `data/hexagram_calibration.json` | 卦象校准统计 |
| `data/backtest/enhancer_backtest_*.json` | 回测报告 |

## 7. 运维要点

- 增强器初始化：`self.ranging_enhancer = RangingMarketEnhancer()`
- 异常回退：增强器调用失败时自动回退到P0简单逻辑
- 风控重置：连续亏损达上限后需手动重置 `risk_state.json`
- 数据积累：500+样本后启用Platt缩放，之前用简单分桶平均
