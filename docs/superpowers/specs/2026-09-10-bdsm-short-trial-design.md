# BDSM 做空试错单技术规格（Spec）

> **版本**: v1.0
> **日期**: 2026-09-10
> **状态**: Draft（待评审）
> **定位**: 在 BDSM 独立开仓框架中新增"恶化型离场信号转做空试错单"能力，验证 BDSM 基本面恶化信号的做空有效性，与 BCRM2.0 技术面做空形成对比样本

***

## 0. 背景与目标

### 0.1 设计动机

1. **BDSM 离场信号本质是"该卖出"**：BDSM 体系内已有三类离场信号（基本面出场 exit_action、技术趋势止损 trend_stop、价值发现止盈 value_exit），这些信号在持仓时触发减仓/平仓，在无持仓时逻辑上可转化为做空试错信号。
2. **当前 BDSM 只做多**：`_bdsm_independent_open` 硬编码 `direction="UP"`，BDSM 的 SHORT_ONLY 方向约束（score < -0.3）历史从未触发，BDSM 体系内无实际做空能力。
3. **验证对比需求**：BCRM2.0 技术面做空已在运行，需要 BDSM 基本面恶化做空的对照样本，评估两种做空机制的真实表现差异。
4. **基本面恶化优先级高于技术面**：恶化型信号（bds<0、Phase退化、技术大破位）直接转空，不需要技术面确认。

### 0.2 核心原则（铁律）

| #  | 铁律 | 违反后果 |
| -- | ---- | -------- |
| R1 | **只转"恶化型"，不转"高估型"**：仅 bds<0 / Phase退化 / 技术大破位 / E7塌 转做空；估值泡沫（value_exit=full_exit 且 bds≥0）不转空 | 高估≠下跌，误转空会逆势亏损 |
| R2 | **试错性质，轻仓为主**：所有 BDSM 做空单 is_trial=True，L1=0.08 / L2=0.05 | 验证期严控风险 |
| R3 | **约束层不变**：`_apply_bdsm_direction_constraint` 不改动，BDSM 独立开空走 `_bdsm_independent_open` 不受约束层拦截 | 保持约束叠加层职责单一 |
| R4 | **FAIL-OPEN 等价无此功能**：开关关闭 / 快照异常 / 信号缺失 → 不触发做空 | 不阻塞 BDSM 多头主链路 |

***

## 1. 做空信号分级

### 1.1 L1 强做空信号（仓位 0.08）

满足任一即触发：

| 信号源 | 条件 | 含义 |
| ------ | ---- | ---- |
| 基本面 | `bds_score < 0` | 基本面恶化（Artemis 七信号合成分为负） |
| 基本面出场 | `exit_action == "CLOSE_ALL"` | Phase 退化（P2/P3→P1 且 bds<0）或排名连续下降（B5） |
| 技术趋势止损 | `trend_stop.action == "full_exit"` | 连续 5 天收盘低于 MA200 且 MA200 斜率负 |

### 1.2 L2 中做空信号（仓位 0.05）

满足任一即触发：

| 信号源 | 条件 | 含义 |
| ------ | ---- | ---- |
| 基本面出场 | `exit_action == "REDUCE_80"` | E7 塌了（前日 E7>0 今日 ≤0） |
| 技术趋势止损 | `trend_stop.action == "reduce50"` | 连续 3 天收盘低于 MA200 且 MA200 斜率负 |

### 1.3 明确不转空的信号

| 信号 | 不转空原因 |
| ---- | ---------- |
| `value_exit=full_exit` 且 `bds ≥ 0` | 估值泡沫止盈，币可能继续涨，非恶化 |
| `value_exit=reduce30` | 高估减仓，非恶化 |
| `exit_action=REDUCE_50` | P2→P3 高估减仓 或 score 破位减仓，非强恶化 |
| `trend_stop=reduce30` | 死叉轻度减仓，非大破位 |

### 1.4 置信度映射

```
confidence = max(0.40, min(0.70, abs(bds_score)))
```

- 下限 0.40（试错单最低置信度）
- 上限 0.70（试错性质，不给高置信度，避免影响仓位计算）
- 取 abs(bds_score) 映射恶化程度

***

## 2. 架构改动

### 2.1 `_bdsm_independent_open` 扩展（polling_trader.py）

在现有多头开仓分支后新增空头分支：

```python
def _bdsm_independent_open(self, coin, snapshot, bdsm_entry):
    # --- 现有多头分支（不变）---
    if cvs >= 0.3 and bds >= 0.3:
        direction = "UP"
        is_trial = False
        confidence = max(0.40, min(0.95, bds))
        # ... 现有多头逻辑

    # --- 新增空头分支 ---
    elif self._bdsm_short_trial_enabled:
        short_level = self._classify_bdsm_short_signal(snapshot, coin)
        if short_level:
            direction = "DOWN"
            is_trial = True
            bds = snapshot["coins"][coin]["bds_score"]
            confidence = max(0.40, min(0.70, abs(bds)))
            position_pct = 0.08 if short_level == "L1" else 0.05
            # ... 走 _open_position 开空
```

### 2.2 新增辅助方法 `_classify_bdsm_short_signal`

```python
def _classify_bdsm_short_signal(self, snapshot, coin) -> Optional[str]:
    """返回 'L1' / 'L2' / None。只取恶化型信号。"""
    entry = snapshot.get("coins", {}).get(coin, {})
    if not entry:
        return None

    bds_score = entry.get("bds_score", 0.0)
    exit_action = entry.get("exit_action", "NONE")
    trend_action = (entry.get("trend_stop") or {}).get("action", "none")

    # L1 强信号
    if bds_score < 0:
        return "L1"
    if exit_action == "CLOSE_ALL":
        return "L1"
    if trend_action == "full_exit":
        return "L1"

    # L2 中信号
    if exit_action == "REDUCE_80":
        return "L2"
    if trend_action == "reduce50":
        return "L2"

    return None
```

### 2.3 不变的部分

| 模块 | 状态 | 说明 |
| ---- | ---- | ---- |
| `_apply_bdsm_direction_constraint` | 不变 | 约束叠加层，只拦截 BCRM 开仓，不影响 BDSM 独立开仓 |
| 多头开仓逻辑 | 不变 | CVS≥0.3 且 BDS≥0.3 → UP |
| `_bdsm_check_exit_actions` | 不变 | 已有 `market_close_short` 分支支持空头平仓 |
| BDSM 子池容量 | 不变 | ≤3 仓（含多空） |

***

## 3. 仓位与试错约束

### 3.1 仓位

| 级别 | position_pct | is_trial |
| ---- | ------------ | -------- |
| L1 | 0.08 | True |
| L2 | 0.05 | True |

### 3.2 试错单约束

- `is_trial=True`，受 `MAX_TRIAL_POSITIONS=2` 限制（与 BCRM 试错单共享名额）
- 开仓前检查：`_count_trial_positions() < MAX_TRIAL_POSITIONS`
- `source_tag="bdsm"`，审计可区分 BDSM 空头试错单

### 3.3 与 BCRM 空头的关系

- BDSM 做空与 BCRM2.0 做空**独立决策**，互不干扰
- 同一币种若 BDSM 和 BCRM 同时做空，受 `position_tracker.has_open_position(inst_id)` 防重复建仓限制
- 审计通过 `source_tag` 区分来源（bdsm vs bcrm）

***

## 4. 出场逻辑

复用现有 `_bdsm_check_exit_actions`，已支持空头平仓：

| 出场信号 | 多头动作 | 空头动作 |
| -------- | -------- | -------- |
| `exit_action=CLOSE_ALL` | `market_close_long` | `market_close_short` |
| `exit_action=REDUCE_80` | 减仓 80% | 减仓 80% |
| `exit_action=REDUCE_50` | 减仓 50% | 减仓 50% |
| `trend_stop=full_exit` | `market_close_long` | `market_close_short` |
| `value_exit=full_exit` | `market_close_long` | `market_close_short` |

空头平仓后 outcome 标签进入 ReflectionEngine 进化闭环。

***

## 5. 开关与配置

### 5.1 主开关

```python
ENABLE_BDSM_SHORT_TRIAL = False  # 默认关闭，验证用
```

环境变量覆盖：`ENABLE_BDSM_SHORT_TRIAL=1`

### 5.2 仓位参数（可配置）

```python
BDSM_SHORT_L1_POSITION_PCT = 0.08
BDSM_SHORT_L2_POSITION_PCT = 0.05
BDSM_SHORT_CONFIDENCE_FLOOR = 0.40
BDSM_SHORT_CONFIDENCE_CEIL = 0.70
```

***

## 6. FAIL-OPEN 原则

| 异常场景 | 行为 |
| -------- | ---- |
| 开关关闭 | 不触发任何做空 |
| BDSM 快照缺失/异常 | `_classify_bdsm_short_signal` 返回 None |
| `bds_score` 字段缺失 | 默认 0.0，不触发 L1 |
| `exit_action` 字段缺失 | 默认 "NONE"，不触发 |
| `trend_stop` 缺失 | 默认 action="none"，不触发 |
| 试错单名额已满 | 跳过开空，记日志 |

***

## 7. 测试计划

### 7.1 单元测试

1. `_classify_bdsm_short_signal` 各信号分级测试（L1/L2/None）
2. `_classify_bdsm_short_signal` FAIL-OPEN 测试（缺失字段）
3. 高估型信号不转空测试（value_exit=full_exit 且 bds≥0 → None）
4. 置信度映射测试（abs(bds) 在 [0.40, 0.70] 范围内）

### 7.2 集成测试

1. `_bdsm_independent_open` 空头分支触发（L1/L2）
2. 试错单名额满时不重复开空
3. 约束层不拦截 BDSM 独立开空
4. 空头出场 `market_close_short` 正确调用

### 7.3 回归测试

1. 多头开仓逻辑不受影响
2. 开关关闭时行为与改动前完全一致
3. BDSM 约束叠加层行为不变

***

## 8. 验证指标

开启后跟踪以下指标，与 BCRM2.0 技术面做空对比：

| 指标 | BDSM 基本面恶化做空 | BCRM2.0 技术面做空 |
| ---- | ------------------- | ------------------ |
| 胜率 | 待统计 | 待统计 |
| 平均持仓时长 | 待统计 | 待统计 |
| 平均盈亏比 | 待统计 | 待统计 |
| 触发频率 | 低（恶化信号少） | 高 |

***

## 9. 当前预期

基于 2026-09-01 ~ 2026-09-10 历史快照：

- **L1 信号**：仅 SOL（bds=-0.126 持续 9 天）
- **L2 信号**：无（exit_action 无 REDUCE_80，trend_stop 无 reduce50）
- **高估型不转空**：28 次 value_exit=full_exit 全部跳过

样本较少，但质量高（纯基本面恶化）。先开启积累数据，后续根据表现调整阈值或仓位。
