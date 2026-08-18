# Screen3 内联入场检查（降级路径）

当 `screen3-trigger` SKILL 不存在或 `screen3_runner.py` 不可用时，由编排层直接执行 Screen3 入场检查。本文档记录已验证的内联检查流程。

## 触发条件
- 每工作日 09:00 cron 触发
- Team A Screen2 已完成（`screen2_presets.status == "WAIT_FOR_ENTRY_SIGNAL"`）
- 当前无持仓（`current_position.status == "no_position"`）

## 执行流程

### Step 1: 读取会话状态
```
优先: read_file(session_state_path)
降级: execute_code + open() — 当 read_file 因路径转义失败时
```

关键字段：
- `screen1_direction`, `screen1_btc_price_basis`
- `screen2_presets.entry_zone`, `screen2_presets.btc_price_at_analysis`
- `team_b_consecutive_skips`, `team_b_sleepwalk_alert`
- `current_position.status`

### Step 2: 获取 BTC 现价
```
web_search("BTCUSDT price now", limit=3)
```
从 TradingView / Binance / Gate 结果中提取当前价格。取多个来源的共识值。

### Step 3: 计算漂移与入场判断
```python
drift_from_screen1 = (current_price - screen1_basis) / screen1_basis * 100
drift_from_screen2 = (current_price - screen2_price) / screen2_price * 100

price_in_entry_zone = entry_zone[0] <= current_price <= entry_zone[1]

if price_in_entry_zone:
    decision = "ENTRY_CHECK"  # 触发完整 Screen3 评估
else:
    decision = "SKIP"
```

### Step 4: 漂移评级
| 漂移范围 | 级别 | 动作 |
|----------|------|------|
| > 10% | CRITICAL | 需重跑 Screen1 + Screen2 |
| 5-10% | WARNING | 继续但标记 Screen2 可能陈旧 |
| < 5% | OK | 正常 |

### Step 5: 梦游检查（P006 宪法约束）
```python
if team_b_consecutive_skips >= 7:
    sleepwalk_alert = True
    # 提前触发 Process D
```

### Step 6: 更新会话状态
写入字段：
```json
{
  "team_b_status": "SKIP_ENTRY_ZONE_NOT_REACHED",
  "team_b_last_check": "<today>",
  "team_b_last_skip_reason": "ENTRY_ZONE_NOT_REACHED_PRICE_<distance>_BELOW_LOWER_BOUND",
  "team_b_consecutive_skips": <new_count>,
  "team_b_sleepwalk_alert": false,
  "last_updated": "<today>",
  "screen3_last_check": {
    "date": "<today>",
    "btc_price": <number>,
    "drift_from_screen1_pct": <number>,
    "drift_from_screen2_pct": <number>,
    "entry_zone": [<low>, <high>],
    "decision": "SKIP|ENTRY_CHECK",
    "reason": "...",
    "screen2_stale_flag": <bool>,
    "price_drift_level": "OK|WARNING|CRITICAL"
  }
}
```

### Step 7: 输出报告
格式见下方「输出模板」。

## 输出模板

```
## 📊 6-TRADING Screen3 入场检查 — YYYY-MM-DD

### 会话状态
| 字段 | 值 |
|------|-----|
| Session | {screen1_id} → {screen2_id} |
| Screen1 方向 | **{direction}** (score: {score}, basis: ${basis}) |
| 持仓状态 | {status} |

### 价格检查
| 指标 | 值 |
|------|-----|
| BTC 现价 | **${price}** |
| Screen1 基准漂移 | **{drift1}%** {level} |
| Screen2 分析价漂移 | **{drift2}%** {stale_flag} |
| 入场区间 | ${low} — ${high} |
| 距边界 | **{distance}** |

### 🚫/✅ 决策：SKIP / ENTRY_CHECK

**原因**: {reason}

### ⚠️ 风险标注
- {warnings}

### 📋 建议
- {recommendations}

### 状态更新
```
{updated_fields}
```

### 下一步
- **Screen2**: 明日 07:30 自动触发
- **Screen3**: 明日 09:00 重新检查入场条件
```

## 已验证案例

### 2026-06-03: SKIP — 入场区未触及（价格远低于下限）
- BTC: $67,124, 入场区: [73,200, 74,800]
- 漂移 Screen1: -8.49% (WARNING), Screen2: -6.77% (陈旧)
- 距下边界: -$6,076 (9.1%)
- 连续跳过: 1→2, 梦游: false
- 产出: 状态更新成功，报告清晰
