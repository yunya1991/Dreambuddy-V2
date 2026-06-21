# 新闻锚点增量运行 SOP（不改代码版）

**版本**: v1.0  
**日期**: 2026-03-18  
**适用范围**: `/ops/nanoclaw/core_task1`

## 1. 目标

用“早餐锚点 + 日内增量修订”替代“反复重启式全量解读”，实现同一交易日内参数与趋势连续演进。

## 2. 日内节奏

| 时段 | 频率 | 模式 | 目的 |
|---|---:|---|---|
| 07:40-08:20 | 1 次 | anchor | 生成当日基准视角 |
| 09:00-22:00 | 每 2 小时 | delta | 追踪新增事件与漂移 |
| CPI/FOMC/NFP 前后 | 事件驱动 +15min | delta | 快速修正风险动作 |
| 日终 22:30 | 1 次 | delta | 收口与复盘归档 |

推荐命令：

```bash
cd /Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/core_task1

python3 scripts/news_digest_v2.py --hours 24 --update-mode anchor --use-ollama --ollama-model qwen2.5:7b-instruct
python3 scripts/news_digest_v2.py --hours 2  --update-mode delta  --use-ollama --ollama-model qwen2.5:7b-instruct
python3 scripts/news_digest_v2.py --hours 2  --update-mode auto   --use-ollama --ollama-model qwen2.5:7b-instruct
```

## 3. 阈值规则

### 3.1 事件变化阈值

- 新增事件：`current_event_map - anchor_event_map`
- 消退事件：`anchor_event_map - current_event_map`
- 分数漂移：`|community_effective_score_delta| >= 0.20`
- 动作漂移：`risk_action_proposal` 发生变化即记为漂移

### 3.2 参数漂移阈值

| 指标 | 观察阈值 | 告警阈值 |
|---|---:|---:|
| avg_signal_score | \|Δ\| >= 0.10 | \|Δ\| >= 0.20 |
| negative_ratio | Δ >= 0.08 | Δ >= 0.15 |
| high_risk_ratio | Δ >= 0.08 | Δ >= 0.15 |
| active_narrative_ratio | \|Δ\| >= 0.10 | \|Δ\| >= 0.20 |
| window_gate_open_ratio | Δ <= -0.10 | Δ <= -0.20 |
| expectation_unknown_ratio_macro | Δ >= 0.10 | Δ >= 0.20 |

### 3.3 操作约束

- 若 `high_risk_ratio` 告警且 `avg_signal_score <= -0.20`：只允许 `reduce/hedge/stop_loss/hold`
- 若宏观 `expectation_unknown_ratio_macro >= 0.30`：禁止 `increase/take_profit`
- 若连续两次 delta 出现同向负漂移：提升风险级别一档

## 4. 异常处理规则

### 4.1 数据源异常

- 华尔街见闻早餐不可用：
  - 当天首轮 anchor 失败则延后 30 分钟重试 2 次
  - 仍失败则切换降级源并打标签 `主备源不可用`
- 加密主源不可用：
  - 使用辅源，保留 `source_confidence=low/medium` 降级

### 4.2 状态异常

- delta 找不到 anchor：
  - 立即回退为 anchor 模式，记录异常代码 `DELTA_NO_ANCHOR`
- registry 写入失败：
  - 本轮结果判为失败，不进入“成功发布”
- 输出校验失败（schema/ledger）：
  - 终止发布，保留 step_audit 与失败原因

### 4.3 业务异常

- 单次 delta 新增事件 > 40 条：
  - 判定为“突发信息流冲击”，临时缩短更新频率到每 30 分钟
- 动作漂移连续 3 次反复（如 hold→reduce→hold）：
  - 标记“方向不稳定”，建议人工复核

## 5. 值班执行清单

每次运行后核对：

1. `raw/step_audit_*.json` 状态为 succeeded  
2. `raw/event_ledger_*.jsonl` 存在且非空  
3. `raw/anchor_registry.jsonl` 或 `raw/delta_registry.jsonl` 有新增  
4. `outputs/brief_v3_*_optimized.md` 已更新  
5. 关键漂移字段是否超过阈值并触发对应处置

## 6. 复盘模板

每日收盘后记录：

- 当日 anchor 时间与数据完整性
- delta 次数、有效变化次数、误报次数
- 触发告警次数与处置动作
- 与次日开盘表现的一致性评分（1-5）

## 7. 运行边界

- 本 SOP 仅用于研究和决策支持，不直接触发交易执行
- 涉及真实资金前需通过风控与合规复核
