# BDSM 三层置信度递进开仓方案（Spec）

> **版本**: v2.0
> **日期**: 2026-09-18
> **状态**: Approved
> **定位**: 在 BDSM 独立开仓框架中引入"战略层方向过滤 + BDSM 基本面 + 三因子共振 + MA200 趋势"四层信号的置信度递进开仓机制，做多做空对称设计
> **替代**: v1.0 `2026-09-10-bdsm-short-trial-design.md`（单一恶化信号 OR 触发）

***

## 0. 背景与目标

### 0.1 设计动机

1. **v1.0 做空试错的缺陷**：原方案采用 OR 条件（bds<0 / exit=CLOSE_ALL / trend=full_exit 任一触发），单一基本面信号即可开空，缺乏战略层和趋势面确认，误判风险高。
2. **开空需多重确认**：加密货币做空风险高，需战略层方向放行 + 基本面恶化 + 技术趋势确认三重验证。
3. **置信度递进仓位**：信号确认层数越多，置信度越高，仓位/杠杆相应放大，实现"高确信重仓、低确信轻仓"。
4. **做多对称**：做多方向采用相同的三层递进框架，保持多空逻辑一致性。

### 0.2 核心原则（铁律）

| #  | 铁律 | 违反后果 |
| -- | ---- | -------- |
| R1 | **战略层方向过滤优先**：`direction_state` 禁止的方向一律不开仓（LONG_ONLY 禁空，SHORT_ONLY 禁多，FREEZE 全禁） | 逆战略方向开仓 = 逆势亏损 |
| R2 | **置信度递进 = AND 叠加**：L2 必须包含 L1 全部条件 + 三因子共振；L3 必须包含 L2 全部条件 + MA200 趋势确认 | 层级不是 OR 选其一，是逐层叠加确认 |
| R3 | **仓位随层级放大**：L1 基础仓 / L2 加大仓 / L3 放大仓+杠杆，严禁低层级用高层级仓位 | 信号不足重仓 = 风险敞口失控 |
| R4 | **FAIL-OPEN 降级**：信号缺失/异常 → 降级到满足的最高层级或不开仓，不阻塞主链路 | 信号故障不应阻断 BDSM 多头主链路 |
| R5 | **约束层不变**：`_apply_bdsm_direction_constraint` 不改动，BDSM 独立开仓不受约束层拦截 | 保持约束叠加层职责单一 |

***

## 1. 信号源定义

### 1.1 战略层方向状态（direction_state）

来源：`_five_domain_state_cache.direction_state[asset_class]`

| 状态 | 允许做多 | 允许做空 | 说明 |
| ---- | -------- | -------- | ---- |
| `LONG_ONLY` | ✅ | ❌ | 战略层明确看多 |
| `LONG_PREFER` | ✅ | ❌ | 战略层偏多 |
| `NEUTRAL` | ✅ | ✅ | 战略层中性，多空均可（需 BDSM 确认） |
| `SHORT_PREFER` | ❌ | ✅ | 战略层偏空 |
| `SHORT_ONLY` | ❌ | ✅ | 战略层明确看空 |
| `FREEZE` | ❌ | ❌ | 战略层冻结，禁止开仓 |

### 1.2 BDSM 基本面信号（bds_score）

来源：BDSM 快照 `coins[coin].bds_score`

- `bds_score > 0`：基本面向好（做多基础条件）
- `bds_score < 0`：基本面恶化（做空基础条件）

### 1.3 三因子共振信号

#### 做空三因子（ThreeFactorShortDetector，已存在）

| 因子 | 条件 | 含义 |
| ---- | ---- | ---- |
| 形态因子 | `pattern_factor ≤ -0.5` | 头肩顶看跌 |
| BTC 强弱 | `btc_regime == "WEAK"` | BTC 与美股高相关，风险资产联动下跌 |
| ETF 资金 | `etf_flow_norm < -0.1` | ETF 净流出（停滞期后强信号） |

#### 做多三因子（ThreeFactorLongDetector，本次新增）

| 因子 | 条件 | 含义 |
| ---- | ---- | ---- |
| 形态因子 | `pattern_factor ≥ +0.5` | 头肩底看涨 |
| BTC 强弱 | `btc_regime == "STRONG"` | BTC 与美股脱钩，独立强势 |
| ETF 资金 | `etf_flow_norm > +0.1` | ETF 净流入 |

### 1.4 MA200 趋势信号（trend_stop）

来源：BDSM 快照 `coins[coin].trend_stop`

| 字段 | 做空条件（L3） | 做多条件（L3） |
| ---- | -------------- | -------------- |
| `action` | `reduce50` 或 `full_exit` | `none`（未破 MA200） |
| `below_ma200_days` | ≥ 3 | 0 |
| `ma200_slope_negative` | True | False |

- 做空 L3：连续 3+ 天收盘低于 MA200 且 MA200 斜率负
- 做多 L3：站稳 MA200 之上且 MA200 斜率非负

***

## 2. 三层置信度递进开仓

### 2.1 做空方向

| 层级 | 触发条件（AND 叠加） | position_pct | 杠杆 | is_trial |
| ---- | -------------------- | ------------ | ---- | -------- |
| **L1 基础做空** | 战略层放行（SHORT_ONLY/SHORT_PREFER/NEUTRAL）<br>**AND** `bds_score < 0` | 0.05 | 3x | True |
| **L2 加强做空** | L1 全部条件<br>**AND** `three_factor_short_signal == True` | 0.08 | 3x | True |
| **L3 激进做空** | L2 全部条件<br>**AND** `trend_stop.action ∈ {reduce50, full_exit}` | 0.12 | 5x | True |

### 2.2 做多方向

| 层级 | 触发条件（AND 叠加） | position_pct | 杠杆 | is_trial |
| ---- | -------------------- | ------------ | ---- | -------- |
| **L1 基础做多** | 战略层放行（LONG_ONLY/LONG_PREFER/NEUTRAL）<br>**AND** `bds_score > 0` | 0.05 | 3x | False |
| **L2 加强做多** | L1 全部条件<br>**AND** `three_factor_long_signal == True` | 0.08 | 3x | False |
| **L3 激进做多** | L2 全部条件<br>**AND** `trend_stop.action == "none"`（站稳MA200） | 0.12 | 5x | False |

> 做多 is_trial=False（BDSM 价值建仓非试错），做空 is_trial=True（验证期）。

### 2.3 层级判定流程

```
输入: direction, bds_score, direction_state, three_factor_signal, trend_stop

Step 1: 战略层过滤
  if direction_state 禁止该方向 → return None（不开仓）

Step 2: L1 基础层
  if (direction==SHORT and bds<0) or (direction==LONG and bds>0):
    level = L1
  else:
    return None

Step 3: L2 加强层（叠加三因子共振）
  if three_factor_signal == True:
    level = L2

Step 4: L3 激进层（叠加 MA200 趋势）
  if trend_stop 确认同向:
    level = L3

return level
```

***

## 3. 架构改动

### 3.1 新增 `ThreeFactorLongDetector`

路径：`23-四层闭环自进化交易架构/dreambuddy_evolution/engines/three_factor_long.py`

对称 `ThreeFactorShortDetector`：
- `PATTERN_THRESHOLD = +0.5`（头肩底）
- `ETF_INFLOW_THRESHOLD = +0.1`（ETF 净流入）
- `btc_regime == "STRONG"`
- 开关：`enable_three_factor_long`（默认 True）
- FAIL-OPEN：任一因子缺失/异常 → False

### 3.2 重构 `_classify_bdsm_short_signal` → `_classify_bdsm_signal_level`

原函数（OR 条件，仅做空）升级为统一的层级判定函数：

```python
def _classify_bdsm_signal_level(
    self,
    direction: str,          # "UP" / "DOWN"
    coin_entry: dict,        # BDSM 快照币种条目
    direction_state: str,    # 战略层方向状态
    three_factor_signal: bool,  # 三因子共振信号（做多/做空）
) -> Optional[str]:
    """返回 'L1' / 'L2' / 'L3' / None。

    层级递进：L1（战略层+BDSM）→ L2（+三因子）→ L3（+MA200趋势）
    """
```

### 3.3 修改 `_bdsm_independent_open`

- 做多分支：调用 `_classify_bdsm_signal_level("UP", ...)` 获取层级，按层级取 position_pct
- 做空分支：调用 `_classify_bdsm_signal_level("DOWN", ...)` 获取层级，按层级取 position_pct
- 新增战略层 `direction_state` 过滤（由 `_classify_bdsm_signal_level` 内部完成）
- 三因子信号从 `_five_domain_state_cache.three_factor_short_signal` / `three_factor_long_signal` 读取

### 3.4 战略层 direction_state 数据获取

复用已有数据：
```python
_fds = self._five_domain_state_cache
_cls = self._coin_asset_class(coin)
direction_state = _fds.direction_state.get(_cls, "NEUTRAL")
```

三因子做多信号写入（与做空对称）：
```python
_fds.three_factor_long_signal["crypto_usdt"] = _tfl_result
```

### 3.5 不变的部分

| 模块 | 状态 | 说明 |
| ---- | ---- | ---- |
| `_apply_bdsm_direction_constraint` | 不变 | 约束叠加层，只拦截 BCRM 开仓 |
| BCRM2.0 主开仓链路 | 不变 | 不受本次改动影响 |
| `_bdsm_check_exit_actions` | 不变 | 出场逻辑复用 |
| BDSM 子池容量 | 不变 | ≤3 仓（含多空） |

***

## 4. 仓位与杠杆参数

### 4.1 仓位参数

```python
# 做空（试错单）
BDSM_SHORT_L1_POSITION_PCT = 0.05
BDSM_SHORT_L2_POSITION_PCT = 0.08
BDSM_SHORT_L3_POSITION_PCT = 0.12

# 做多（价值建仓）
BDSM_LONG_L1_POSITION_PCT = 0.05
BDSM_LONG_L2_POSITION_PCT = 0.08
BDSM_LONG_L3_POSITION_PCT = 0.12
```

### 4.2 杠杆参数

```python
BDSM_L1_LEVERAGE = 3   # L1/L2 标准杠杆
BDSM_L3_LEVERAGE = 5   # L3 激进杠杆
```

### 4.3 置信度映射

```python
# 做空
confidence = max(0.40, min(0.70, abs(bds_score)))

# 做多
confidence = max(0.40, min(0.95, bds_score))
```

***

## 5. 开关与配置

| 开关 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `ENABLE_BDSM_INDEPENDENT_OPEN` | True | BDSM 独立开仓总开关 |
| `ENABLE_BDSM_SHORT_TRIAL` | False | BDSM 做空试错开关 |
| `ENABLE_BDSM_DIRECTION_STATE_FILTER` | True | 战略层方向过滤开关 |
| `ENABLE_BDSM_TIERED_POSITION` | True | 三层递进仓位开关 |
| `enable_three_factor_long` | True | 三因子做多检测器开关（agi_config） |
| `enable_three_factor_short` | True | 三因子做空检测器开关（已存在） |

***

## 6. FAIL-OPEN 原则

| 异常场景 | 行为 |
| -------- | ---- |
| `direction_state` 读取失败 | 默认 NEUTRAL（多空均可，但仍需 BDSM 确认） |
| 三因子信号读取失败 | 默认 False（不升级到 L2/L3） |
| `trend_stop` 缺失 | 不升级到 L3（停留在 L1/L2） |
| `bds_score` 缺失 | 默认 0.0（不触发 L1） |
| 开关关闭 | 跳过对应逻辑 |

***

## 7. 测试计划

### 7.1 ThreeFactorLongDetector 单元测试

1. 三因子全满足 → True
2. pattern_factor < 0.5 → False
3. btc_regime != STRONG → False
4. etf_flow_norm ≤ 0.1 → False
5. 因子缺失/异常 → False（FAIL-OPEN）
6. 开关关闭 → False

### 7.2 `_classify_bdsm_signal_level` 层级测试

1. direction_state=LONG_ONLY + direction=DOWN → None（战略层禁空）
2. direction_state=SHORT_ONLY + bds<0 → L1
3. direction_state=NEUTRAL + bds<0 + three_factor=True → L2
4. direction_state=SHORT_ONLY + bds<0 + three_factor=True + trend=full_exit → L3
5. bds≥0 + direction=DOWN → None（基本面不支持做空）
6. 做多对称测试（LONG_ONLY + bds>0 → L1 等）

### 7.3 回归测试

1. 多头开仓逻辑在 direction_state=NEUTRAL + bds>0 时正常触发
2. 开关关闭时行为与改动前一致
3. BCRM2.0 主链路不受影响

***

## 8. 验证指标

开启后跟踪以下指标，按层级统计：

| 指标 | L1 | L2 | L3 |
| ---- | -- | -- | -- |
| 触发频率 | 高 | 中 | 低 |
| 胜率 | 待统计 | 待统计 | 待统计 |
| 平均盈亏比 | 待统计 | 待统计 | 待统计 |
| 平均持仓时长 | 待统计 | 待统计 | 待统计 |

预期：L3 胜率最高但频率最低，L1 频率最高但胜率较低。
