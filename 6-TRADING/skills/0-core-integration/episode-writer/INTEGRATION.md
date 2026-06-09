# learning-episode-writer 集成规范 (Team B — B9)

> **原始 SKILL**: dream-multiskill-v2/skills/0-CORE/learning-episode-writer/SKILL.md
> **集成团队**: Team B — 入场执行
> **触发时机**: A5 执行完成后（无论 ENTER 还是 SKIP，均必须写 episode）

---

## 一、职责

将每次 Team B Screen 3 的决策轮次（入场/跳过/加仓/离场）记录为结构化 episode JSON，替换自由格式 `execution-log.md`，使 Process D 的 D2（learning-lesson-distiller）可以量化统计。

---

## 二、Episode Schema（6-TRADING 版）

```json
{
  "episode_id": "{session_id}-{YYYYMMDDHHMMSS}",
  "trace_id": "{session_id}",
  "ts": "2026-05-26T09:00:00+08:00",
  "inst_id": "BTC-USDT-SWAP",
  "action": "ENTER_SHORT | ADD_SHORT | SKIP | EXIT_TP | EXIT_SL | EXIT_FORCED",
  "direction": "SHORT | LONG | NEUTRAL",
  "martingale_level": 0,
  "scoring": {
    "a7_gate_score": 35,
    "a7_gate_max": 40,
    "composite_confidence": 64,
    "screen1_score": 72
  },
  "gate": {
    "result": "PASS | PASS_WITH_CONDITIONS | SKIP | BLOCK",
    "reason_codes": [],
    "conditions": []
  },
  "execution": {
    "entry_price": null,
    "size_pct_of_capital": null,
    "order_id": null,
    "order_type": "limit | market",
    "stop_loss": null,
    "take_profit_1": null,
    "take_profit_2": null,
    "slippage_bps": null,
    "fee_usdt": null,
    "fee_rate_bps": null,
    "slippage_usdt": null,
    "delay_cost_usdt": null,
    "total_cost_usdt": null,
    "cost_rate_pct": null
  },
  "outcome": {
    "exit_price": null,
    "pnl_usdt": null,
    "pnl_pct": null,
    "max_drawdown_pct": null,
    "holding_hours": null,
    "exit_reason": null
  },
  "skip_tracking": {
    "consecutive_skip_count": 0,
    "sleepwalk_alert": false,
    "sleepwalk_force_review": false
  },
  "evidence_refs": [],
  "data_sources": ["tavily", "screen1_v2"],
  "session_path": "6-TRADING/sessions/{session_id}/"
}
```

---

## 三、[G4 Fix] a7_gate_score 数据来源

`scoring.a7_gate_score` 和 `scoring.a7_gate_max` 的获取规则（按优先级）：

1. **优先读文件**: B9 直接读 `sessions/{session_id}/team-b/a7-gate.json`
   - 字段映射: `a7-gate.json.total_score` → `scoring.a7_gate_score`
   - 字段映射: `a7-gate.json.max_score` → `scoring.a7_gate_max`（默认 40）
   - 字段映射: `a7-gate.json.result` → `gate.result`
   - 字段映射: `a7-gate.json.conditions` → `gate.conditions`

2. **降级处理**: 若 `a7-gate.json` 不存在，则：
   - `scoring.a7_gate_score` = null
   - `scoring.a7_gate_max` = null
   - `gate.result` = "UNKNOWN"
   - 在 `evidence_refs` 中记录 `"a7-gate.json:missing"` 警告

**a7-gate.json 标准结构**（B8 A7 调用后写入）:
```json
{
  "session_id": "20260526-BTC-SCREEN3-v1",
  "ts": "2026-05-26T09:00:00+08:00",
  "result": "PASS_WITH_CONDITIONS",
  "total_score": 35,
  "max_score": 40,
  "conditions": ["确认日线1h拒绝K线后再执行", "仓位不超过 L0 30%"],
  "checks": {
    "screen1_direction_aligned": true,
    "screen2_preset_valid": true,
    "martingale_level_ok": true,
    "funding_rate_ok": false,
    "market_regime_stable": true
  }
}
```

---

## 四、[G5 Fix] consecutive_skip_count 跨 Session 计算规则

`consecutive_skip_count` 是一个**跨 session 的滚动计数器**，B9 必须在写入前计算：

### 计算步骤

1. **读取历史**: 扫描 `sessions/*/team-b/episode.json`，按 `ts` 时间戳降序排列，取最近 **20 条** episodes
2. **从最新往回数**: 从最新 episode 往前遍历，连续统计 `action == "SKIP"` 的数量
3. **遇到非 SKIP 即停**: 遇到第一条 `action != "SKIP"` 的记录停止计数
4. **写入当前 episode**: 将统计结果 +1（包含本次 SKIP）写入 `skip_tracking.consecutive_skip_count`

### 计算示例

```
历史 (最新→旧): SKIP, SKIP, SKIP, ENTER_SHORT, SKIP, SKIP
→ 连续计数 = 3 (到 ENTER_SHORT 停止)
→ 本次若 SKIP → consecutive_skip_count = 4
→ 本次若 ENTER → consecutive_skip_count = 0 (重置)
```

### 特殊情况

| 情况 | 处理 |
|------|------|
| 无历史 episodes | consecutive_skip_count = 1（本次为第 1 次 SKIP）|
| 读取权限失败 | consecutive_skip_count = -1（标记为 UNKNOWN），不触发 sleepwalk 告警 |
| 历史不足 20 条 | 以实际可读条数为准，不报错 |

### 跨 Session 边界处理

同一交易日内多次 Screen 3 执行（如加仓），episode 追加到 `episode_history[]` 数组，不重置计数器。**只有 A9 离场（EXIT_TP/EXIT_SL/EXIT_FORCED）才重置 consecutive_skip_count 为 0**。

---

## 五、P006 梦游惰性检测（6-TRADING 实现）

| 条件 | 动作 |
|------|------|
| `consecutive_skip_count >= 7` | 设置 `sleepwalk_alert: true` |
| `sleepwalk_alert: true` | 设置 `sleepwalk_force_review: true` |
| `sleepwalk_force_review: true` | 在记忆文件 `project_trading_session_state.md` 写入 `sleepwalk_alert: true`，触发 Process D 提前复盘 |

---

## 六、文件路径规范

- 写入位置: `sessions/{session_id}/team-b/episode.json`
- 每次 Screen 3 产生一个 episode
- 同一 session 多次执行（如加仓）追加到 `episode_history[]` 数组

---

## 七、与现有 execution-log.md 的关系

- Phase 1: episode.json 与 execution-log.md 并行存在（execution-log 保留人类可读摘要）
- Phase 2: execution-log.md 由 episode.json 自动生成，不再手写

---

*最后更新: 2026-05-26 v1.1 | 修复 G4 (a7_gate_score 来源) + G5 (consecutive_skip_count 跨session计算)*

---

## 九、memory_db.index_episode() 集成（6-TRADING 本地记忆层）

### 触发时机

screen3_runner.py Phase-2 写 GitHub 成功后，**立即** 调用 `memory_db.index_episode(episode_dict)`，将本次 episode 写入本地 SQLite FTS5 记忆库。

### 实现位置

`C:/tmp/screen3_runner.py` — Phase-M 写回段：

```python
if mdb and not args.dry_run:
    try:
        is_new = mdb.index_episode(episode)
        print(f'[Phase-M] memory_db.index_episode() {"new" if is_new else "updated"}',
              file=sys.stderr)
    except Exception as e:
        print(f'[Phase-M] index_episode 失败（不影响主流程）: {e}', file=sys.stderr)
```

### 下游消费者

| 消费者 | 调用方式 |
|-------|---------|
| screen2_runner.py Phase-M | `mdb.prefetch_context(btc_price, direction)` → 历史注入 A1/A2 |
| Process D Step 3 D2 | `mdb.query_stats(filters)` → win_rate / skip_rate / avg_pnl |
| import_history.py | 历史数据批量回填（冷启动） |

### 失败策略

memory_db 不可用时**降级跳过**，不影响主流程。episode.json 已在 GitHub，重跑 `import_history.py` 可补录。
