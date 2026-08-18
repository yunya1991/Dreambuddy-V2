# 易经离场 SL/TP 连续调制设计

> **Date**: 2026-08-06
> **Status**: Approved
> **Author**: Trading System Team
> **Scope**: `yijing_exit_system.py` + `polling_trader.py`

## 1. 问题陈述

### 1.1 现状缺陷

当前易经离场系统在动态调整 SL/TP 时存在三个关键 Bug：

**Bug A — LOWER_SL 基线脱节**

`polling_trader.py` L1648 硬编码 `base_sl_roi_pct = 0.02`（2%），与开仓时 ATR 止损（可能 12%）完全脱节。
当 ATR 止损为 12% 时，易经"放宽 50%"算出的止损只有 3% — **反而把止损收紧了 4 倍**。

**Bug B — RAISE_TP 基线脱节**

`polling_trader.py` L1616 硬编码 `target_tp_roi_pct = tp_uplift * 0.5`（固定 15%），与开仓时 ATR 止盈（可能 60%）脱节。
当 ATR 止盈为 60% 时，易经"提高止盈"算出来只有 15% — **反而把止盈从 60% 降到 15%**。

**Bug C — 离散调整，非连续函数**

当前逻辑为离散跳变：risk<0.30 → 放宽 50%，risk≥0.35 → 收紧 30%。中间 0.30~0.35 为空白，且跳变边界容易产生抖动。

### 1.2 设计目标

SL/TP 动态调整应为 **ATR 基线 × 风险/价值连续调制因子**：

```
SL_mult = ATR_base_sl × f(risk_score)     # risk 越低 → SL 越宽（多持）
TP_mult = ATR_base_tp × g(value_score)    # value 越高 → TP 越高（让利润跑）
```

同时保留 ATR 基线兜底：调整后的 SL/TP 不会低于开仓时 ATR 基线的 0.7 倍。

## 2. 架构设计

### 2.1 核心公式

#### 风险 → SL 调制因子（连续函数）

```
sl_modulation(risk) = clamp(2.0 - 2.0 × risk, 0.5, 2.0)
```

| risk_score | sl_modulation | 含义 |
|---|---|---|
| 0.25（低） | 1.50 | 放宽 50%，给趋势空间 |
| 0.50（中） | 1.00 | 保持基线 |
| 0.75（高） | 0.50 | 收紧 50%，保本 |
| 0.00（极低） | 2.00 | 上限：放宽 100% |
| 1.00（极高） | 0.50 | 下限：收紧 50% |

#### 价值 → TP 调制因子（连续函数）

```
tp_modulation(value) = clamp(0.5 + 1.5 × value, 0.5, 2.0)
```

| value_score | tp_modulation | 含义 |
|---|---|---|
| 0.85（高） | 1.78 | 提高 78%，让利润跑 |
| 0.50（中） | 1.25 | 提高 25% |
| 0.30（低） | 0.95 | 基本保持 |
| 0.00（极低） | 0.50 | 下限：降低 50%，提前锁利 |
| 1.00（极高） | 2.00 | 上限：提高 100% |

### 2.2 ATR 基线下限保护

调整后的 SL/TP 不得低于开仓时 ATR 基线的 **0.7 倍**：

```
final_sl_roi = max(modulated_sl_roi, base_atr_sl_roi × 0.7)
final_tp_roi = max(modulated_tp_roi, base_atr_tp_roi × 0.7)
```

这确保即使风险极高（收紧止损），止损也不会比开仓时 ATR 基线窄太多，避免被微小波动扫损。

### 2.3 数据流

```
开仓时:
  ATR 基线 SL/TP → 存入 PositionTracker (base_sl_roi, base_tp_roi)

持仓 ≥ 1h 后（易经评估窗口）:
  hexagram → risk_score, value_score
  → sl_modulation = clamp(2.0 - 2.0 × risk, 0.5, 2.0)
  → tp_modulation = clamp(0.5 + 1.5 × value, 0.5, 2.0)
  → new_sl_roi = base_sl_roi × sl_modulation  (下限: base_sl_roi × 0.7)
  → new_tp_roi = base_tp_roi × tp_modulation  (下限: base_tp_roi × 0.7)
  → 换算价格 → 调用 OKX API 更新 SL/TP
```

## 3. 组件修改

### 3.1 `yijing_exit_system.py` — 新增调制函数

在 `YijingExitSystem` 类中新增两个静态方法：

```python
@staticmethod
def risk_to_sl_modulation(risk_score: float) -> float:
    """风险分 → SL 调制因子（连续函数）
    risk=0.25 → 1.5（放宽50%）
    risk=0.50 → 1.0（保持基线）
    risk=0.75 → 0.5（收紧50%）
    """
    return max(0.5, min(2.0, 2.0 - 2.0 * risk_score))

@staticmethod
def value_to_tp_modulation(value_score: float) -> float:
    """价值分 → TP 调制因子（连续函数）
    value=0.85 → 1.78（提高78%）
    value=0.50 → 1.25（提高25%）
    value=0.30 → 0.95（基本保持）
    """
    return max(0.5, min(2.0, 0.5 + 1.5 * value_score))
```

### 3.2 `polling_trader.py` — 修复 LOWER_SL 路径

**修改前**（Bug A）:
```python
base_sl_roi_pct = 0.02  # 硬编码 2%
new_sl_roi_pct = base_sl_roi_pct * (1 + sl_relax_pct)
```

**修改后**:
```python
# 从 PositionTracker 读取开仓时 ATR 基线止损
base_sl_roi = self._get_base_sl_roi(inst_id)  # 从持仓记录读取
sl_modulation = YijingExitSystem.risk_to_sl_modulation(risk_score)
new_sl_roi = base_sl_roi * sl_modulation
# ATR 基线下限保护
new_sl_roi = max(new_sl_roi, base_sl_roi * 0.7)
```

### 3.3 `polling_trader.py` — 修复 RAISE_TP 路径

**修改前**（Bug B）:
```python
target_tp_roi_pct = tp_uplift * 0.5  # 固定 15%
```

**修改后**:
```python
# 从 PositionTracker 读取开仓时 ATR 基线止盈
base_tp_roi = self._get_base_tp_roi(inst_id)
tp_modulation = YijingExitSystem.value_to_tp_modulation(value_score)
new_tp_roi = base_tp_roi * tp_modulation
# ATR 基线下限保护
new_tp_roi = max(new_tp_roi, base_tp_roi * 0.7)
```

### 3.4 `trading_utils.py` — TradeRecord 增加 ATR 基线字段

`TradeRecord` 新增两个字段，在开仓时记录 ATR 基线 SL/TP 收益率：

```python
base_sl_roi: float = 0.0   # 开仓时 ATR 基线止损收益率（如 0.12 = 12%）
base_tp_roi: float = 0.0   # 开仓时 ATR 基线止盈收益率（如 0.60 = 60%）
```

### 3.5 `polling_trader.py` — 开仓时写入 ATR 基线

在 `_open_position` 中，ATR SL/TP 计算完成后，将收益率写入 TradeRecord。

### 3.6 YijingExitDecision 调整

`YijingExitDecision` 不再携带固定 `sl_adjust_pct` / `tp_adjust_pct`，改为携带调制因子和风险/价值分数，由 polling_trader 统一计算：

```python
sl_modulation: float = 1.0    # 风险调制因子
tp_modulation: float = 1.0    # 价值调制因子
```

## 4. 边界条件

| 场景 | 处理 |
|---|---|
| PositionTracker 无 base_sl_roi（旧持仓） | 回退到当前 SL 价格反算 ROI |
| risk_score = 0 | sl_modulation = 2.0（上限） |
| risk_score = 1 | sl_modulation = 0.5（下限） |
| value_score = 0 | tp_modulation = 0.5（下限） |
| value_score = 1 | tp_modulation = 2.0（上限） |
| base_atr_sl_roi = 0（异常） | 不调整，返回 NO_INTERVENE |

## 5. 测试策略

### 5.1 单元测试（TDD）

| 测试用例 | 验证点 |
|---|---|
| `test_risk_to_sl_modulation_low` | risk=0.25 → 1.5 |
| `test_risk_to_sl_modulation_mid` | risk=0.50 → 1.0 |
| `test_risk_to_sl_modulation_high` | risk=0.75 → 0.5 |
| `test_risk_to_sl_modulation_clamp` | risk=-1 → 2.0, risk=2 → 0.5 |
| `test_value_to_tp_modulation_high` | value=0.85 → 1.775 |
| `test_value_to_tp_modulation_mid` | value=0.50 → 1.25 |
| `test_value_to_tp_modulation_low` | value=0.30 → 0.95 |
| `test_value_to_tp_modulation_clamp` | value=-1 → 0.5, value=2 → 2.0 |
| `test_lower_sl_uses_atr_base` | ATR base=12%, risk=0.25 → new_sl=18%（非 3%） |
| `test_raise_tp_uses_atr_base` | ATR base=60%, value=0.85 → new_tp=106.5%（非 15%） |
| `test_atr_floor_protection_sl` | risk=1.0, base=12% → new_sl ≥ 8.4%（12%×0.7） |
| `test_atr_floor_protection_tp` | value=0, base=60% → new_tp ≥ 42%（60%×0.7） |

### 5.2 集成验证

- `py_compile` 全部修改文件
- 增强器倍率验证脚本通过

## 6. 不在范围内

- 不修改 FORCE_CLOSE 逻辑（卦象极端风险仍直接平仓）
- 不修改 TIGHTEN_SL 的触发条件（仍为风险升高 + 未盈利）
- 不修改经典离场系统（classic_exit_system）的 SL/TP 计算
- 不修改开仓阶段 ATR 基线计算（上一轮已调整）
