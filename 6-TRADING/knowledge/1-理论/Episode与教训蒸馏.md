# 学习闭环：Episode + 教训蒸馏 (经验 — 复盘方法论)
> **来源**: dream-multiskill-v2/0-CORE/learning-episode-writer + learning-lesson-distiller
> **类别**: 理论 — 复盘与知识沉淀方法论

---

## Episode 记录格式（每轮必写）

每个决策轮（开仓/平仓/SKIP）必须记录为 Episode：

```json
{
  "decision_audit": { "trace_id", "inst_id", "action", "direction", "strategy_id" },
  "scoring": { "各维度分", "理由码", "冲突点" },
  "gate": { "PASS/SKIP", "reason_codes", "数据完整性" },
  "execution": { "订单参数", "成交回报", "滑点偏差" },
  "outcome": { "PnL", "最大回撤", "止损原因" },
  "evidence_refs": ["材料路径", "快照路径"],
  "skip_tracking": { "consecutive_skip_count", "sleepwalk_alert" }
}
```

## 梦游惯性检测（P006）
- 连续 SKIP ≥ 7 次 → 触发**强制复盘**
- 每次 SKIP 累加计数器，PASS 则清零
- 目的是防止因\"不确定所以一直 WAIT\"的惯性瘫痪

## 教训蒸馏（从 Episode → Lessons）

### 阈值规则（防噪声过拟合）
- `min_frequency`: 同一模式至少出现 N 次才晋升为教训
- `min_severity`: 最低严重度门槛
- `min_unique_traces`: 至少来自 N 个不同决策轮的独立轨迹
- `cooldown_episodes`: 同模式在 N 个 Episode 内不再重复晋升

### 教训升级/降级
| 变化 | 触发器 |
|:---|---:|
| P3 → P2 | 出现 3 次 |
| P2 → P1 | 出现 5 次 |
| P1 → P0 | 出现 8 次 |
| 降一级 | 6 个月无复发 |

### 教训类型前缀
- `F_*` = 失败教训 (Failure)
- `S_*` = 成功经验 (Success)
