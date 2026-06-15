# Cron 调度

> A 系列 cron 任务调度链：状态机、Guard 机制、execution_loop 元数据契约、常见修复。

## 调度架构

```python
scheduler.py tick (每60秒, gateway后台线程)
  │
  ├── 调度闭环 (Scheduling Loop)
  │     guard: _execution_loop_guard()  ← 事前状态匹配检查
  │     执行: run_job() → AIAgent/脚本
  │     record: _record_execution_loop_result()  ← 事后结果记录
  │           → record_phase_success() 推进状态机
  │           → record_phase_failure() 回退状态机
  │
  ├── 监控闭环 (Monitoring Loop)
  │     A6产出control_decision JSON
  │     → apply_a6_control_decision() 处理路由/A9管理
  │     → 写state.json的last_control_decision
  │
  └── 治理闭环 (Governance Loop)
        A8 cron → ensure_active_run() → record_governance_result() → 归档
```

## 状态机（execution_loop）

```python
SUCCESS_NEXT_STATE = {
    "A1": "ANALYZING",    # A1完成 → 等待A2
    "A2": "STRATEGIZING", # A2完成 → 等待A3
    "A3": "VALIDATING",   # A3完成 → 等待A4
    "A4": "EXECUTING",    # A4完成 → 等待A5
    "A6": "MONITORING",   # (A5特判推进到此)
    "A9": "PRACTICE",     # A9完成 → orchestrator归档
}

FAILURE_ROLLBACK = {
    "A4": "STRATEGIZING",  # A4失败 → 退回A3重跑
    "A5": "VALIDATING",    # A5失败 → 退回A4重跑
}
```

阶段 ↔ 状态对照：`A1↔RESEARCH`, `A2↔ANALYZING`, `A3↔STRATEGIZING`, `A4↔VALIDATING`, `A5↔EXECUTING`, `A6↔MONITORING`, `A9↔EXIT`

## Guard 机制

受管理任务必须在 `jobs.json` 中有 execution_loop 字段：

```json
"execution_loop": {"managed": true, "phase": "A1"}
```

Guard 检查逻辑：
1. `managed=false` → 放行（传统 cron）
2. `managed=true` → 当前状态 == 期望状态 → 放行；不匹配 → skip（phase_mismatch）

## A 系列 cron 任务清单

| 阶段 | ID | 类型 | 排程 |
|:---|:---|:---:|:---|
| A1 | 4d2530120c32 | LLM | 01:00 daily |
| A2 | 12c3e0b371d3 | LLM | 02:00 daily |
| A3 | 542888cfbd5f | LLM | 03:00 daily |
| A4 | fbc20e789bb3 | LLM | 每240min |
| A5 | 97084d2ba15d | LLM | 每480min |
| A6 | 91117ffb9088 | LLM | 每4h |
| A8 | 4e0e73e0b834 | no_agent | 14:00 daily |
| A9 | 5a1b4b8ade43 | LLM | 每4h（由A6动态启停）|

## A6 control_decision 路由

A6 的 10 种 action 供 scheduler 路由：

| action | 效果 |
|:---|---|
| OBSERVE_ONLY | 正常观察 |
| RERUN_A2_A5 | 重跑 A2→A5 |
| RERUN_A4_A5 | 重跑 A4→A5 |
| RERUN_A1_A3 | 重跑 A1→A3 |
| RERUN_A1_A5 | 全链路重跑 |
| TRIGGER_A7_A8 | 治理审查 |
| DISABLE_A9 | 停用 A9 |
| SET_A9_1H | A9 加速至每小时 |
| SET_A9_2H | A9 每 2 小时 |
| NO_ACTION | 无法决策 |

## 常见陷阱

1. **cronjob update 全字段替换**：只传部分字段会清空其他字段。直接编辑 `jobs.json` 更安全。
2. **A6 无 execution_loop 元数据**：`_record_execution_loop_result()` 会静默跳过，control_decision 永不生效。
3. **A9 guard 死锁**：正常流中状态永不进入 EXIT。实际由 A6 动态启停。
4. **no_agent 脚本路径限制**：必须位于 `~/.hermes/scripts/` 下，否则被安全策略阻止。
5. **model/provider 缺失**：任务会排期但永不执行（last_run_at=null）。
6. **deliver=local**：输出仅存本地不推送消息平台。

<<<<<<< HEAD
## QA常见坑

| # | 现象 | 原因 | 修复 |
|:---|---|:---|---:|
| Q1 | A4/A5 产出80%+时间0字节 | `managed=true` guard 阶段不匹配 → SILENT | 设 managed=false (2026-06-15) |

=======
>>>>>>> 9b8dfd36bc56c4877c634ed18a1f770f118437fc
## 验证清单

```bash
# 检查 cron 运行状态
cronjob action='list'

# 检查 execution_loop 元数据
grep -A5 '"91117ffb9088"' ~/.hermes/cron/jobs.json

# 检查状态机状态
cat ~/.workbuddy/memory/trading_execution_loop.json

# 查看最新输出
ls -lt ~/.hermes/cron/output/<job_id>/
```

最后更新：2026-06-13 | 来源：a-series-intraday-architecture, hermes-cron-maintenance
