# 48 涌现架构 — 事件源清单（P1-4）

E4b（自指纠错）/ E5（规模相变）度量所需的事件数据源。

## 目录结构

```
events/
├── emergence_shadow/          # 涌现影子探针事件（E4b 级联释放观测）
│   ├── bus_*.jsonl            # 事件总线原始事件（PSI 指标触发、z_score、ignited）
│   ├── resp_*.jsonl           # 订阅者响应（subscriber/consumed/action）
│   └── watchlist_eval.json    # 自选股评估快照
├── gates/
│   └── E4B_CASCADE_RELEASED   # E4b 级联释放门禁状态
└── memory_readout/
    └── recall_events.jsonl    # 记忆召回与动作事件（recall/action 两类）
```

## 外部数据源（不在本目录，由 metrics/emergence_metrics.py 读取）

| 数据源 | 实际路径 | 行数 | 用途 |
|---|---|---|---|
| trajectories.jsonl | `.workbuddy/agent_mail/trajectories.jsonl` | 34 | E5 规模相变：轨迹计数 |
| trajectories_real.jsonl | `.workbuddy/agent_mail/trajectories_real.jsonl` | — | 真实轨迹备份 |
| l1_case_store.jsonl | `34-前端应用训练系统/l1_case_store.jsonl` | 4803 | E5 规模相变：案例库计数 |
| bcrm_trades.db | `11-易经推理系统/scripts/data/bcrm_trades.db` | — | D1 交易指标 |

## 可复现性验证

```bash
python 48-涌现架构/metrics/emergence_metrics.py
# 输出：metrics ok: {"trajectories": 34, "cases": 4803, "trades": 49}
```

## 事件 schema

**bus_*.jsonl**（事件总线）：
```json
{"event_id", "trace_id", "ts", "source_domain", "metric", "value",
 "baseline_mean", "baseline_std", "z_score", "ignited", "detail"}
```

**resp_*.jsonl**（订阅者响应）：
```json
{"event_id", "trace_id", "ts", "subscriber", "source_domain", "metric",
 "consumed", "action", "action_detail"}
```

**recall_events.jsonl**（记忆读回）：
```json
{"event_id", "kind": "recall"|"action", "trace_id", "session_id", "ts", ...}
```
