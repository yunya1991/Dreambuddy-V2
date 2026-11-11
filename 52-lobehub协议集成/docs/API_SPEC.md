# API SPEC — 52-LobeHub 协议集成

> **版本**: v1.0.0（对应 52 模块 v0.11.0） | **更新日期**: 2026-11-11
> 覆盖：CLI 契约、PlanCard、outbox 条目、3.1 HTTP 路由、MCP 工具面、trace 字段

---

## 1. 契约总览

| 契约 | 提供方 | 消费方 | 传输 |
|---|---|---|---|
| 编排器 CLI | `orchestrator/brainstorm_orchestrator.py` | 人 / `shadow_batch.py` / 3.1 `/api/agent/brainstorm` | 进程 stdout（末行 JSON） |
| PlanCard | side-A / side-B | 编排器、执行器、蒸馏桥 | HTTP JSON |
| outbox 条目 | 编排器 | 蒸馏桥 | `bridge/outbox.jsonl` |
| cognition record | 蒸馏桥 | L0 cognition 壳 | stdio JSON-RPC |
| Debate 壳 | `agent.debate.mcp` | 编排器 | stdio JSON-RPC |
| 3.1 HTTP | 3.1-FRONTEND | 浏览器 / 编排器 | HTTP POST |

所有契约都遵守：**未知字段容错、必填字段 fail-closed、异常一律降级为可读错误，不抛 500。**

---

## 2. 编排器 CLI

```bash
python3 orchestrator/brainstorm_orchestrator.py --intent "<议题>" [options]
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `--intent` | str | 必填 | 议题/用户意图原文 |
| `--context-refs` | str... | `[]` | 上下文引用列表 |
| `--shadow / --no-shadow` | bool | `True` | 默认 shadow；`--no-shadow` 走 ADR-001 三道门 |
| `--role` | str | `auditor` | 实盘角色，须在 `live_policy.allowed_roles` |
| `--executor-module` | path | `BRAINSTORM_EXECUTOR_MODULE` | 实盘执行器模块（须暴露 `execute(card)->dict`） |
| `--live-policy` | path | `orchestrator/live_policy.json` | 策略文件 |
| `--live-ledger` | path | `orchestrator/live_ledger.jsonl` | 预算账本 |
| `--user-requested-debate` | flag | `False` | T4：用户显式要求辩论 |
| `--trace-path` | path | `orchestrator/traces/brainstorm.jsonl` | trace 输出 |
| `--outbox-path` | path | `bridge/outbox.jsonl` | 蒸馏 outbox |
| `--side-a-plancard` | path | 空 | 给定则跳过 A 侧 HTTP（离线测试） |
| `--disable-recall` | flag | `False` | 禁用 cognition recall 取证（T3 skipped） |
| `--force` | flag | `False` | 跳过意图路由，强制脑暴（仅供人工观察） |
| `--json-out` | flag | `False` | stdout 只输出单行 JSON 摘要 |
| `--n-per-side` | int | `2` | 每侧发散候选数，范围 1-3，越界 exit 2 |
| `--adjudicator` | enum | `both` | `heuristic` / `grounded` / `both` |

### 2.1 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功（含 `skipped=true` 的路由拦截） |
| 2 | 参数非法；或 `--no-shadow` 被 live 门禁拒绝（`PermissionError`） |

### 2.2 stdout 契约

`--json-out` 输出单行 JSON（字段稳定，供 3.1 消费）：

```json
{
  "ok": true,
  "route": "debate",
  "route_rules_version": "r9-v1",
  "skipped": false,
  "reason": null,
  "mode": "debate",
  "winner": {"card_id": "pc-...", "side": "A", "score": 0.912},
  "executed": false,
  "n_per_side": 2,
  "pool_size": 4,
  "debate_id": "deb-...",
  "debate_error": null,
  "trace_id": "run-...",
  "trace_path": "orchestrator/traces/brainstorm.jsonl",
  "outbox_written": 3,
  "evaluators": {"available": true, "names": 7},
  "diversity_violations": [],
  "adjudication": {"heuristic_top": "pc-...", "grounded_winner": "pc-...", "agree": true},
  "decision": {"kind": "dispatch"}
}
```

失败时（stderr）：`{"ok": false, "error": "<原因>"}`，退出码 2。

---

## 3. PlanCard 契约（R8）

Schema 文件：[`schemas/plancard.schema.json`](../schemas/plancard.schema.json)（draft-07）。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `id` | string | 是 | 前缀 `pc-` |
| `intent` | string | 是 | 1-500 字 |
| `context_refs` | string[] | 否 | L0 工具证据引用 |
| `plan_steps` | object[] | 是 | ≥1 项 |
| `plan_steps[].step` | integer | 是 | ≥1 |
| `plan_steps[].action` | string | 是 | 非空 |
| `plan_steps[].tool` | string | 是 | `^l0\.[a-z0-9_-]+\.mcp\.[a-z0-9_]+$`，且必须在 47 registry 内 |
| `plan_steps[].args_hint` | object | 否 | 参数提示 |
| `evidence_refs` | string[] | 否 | debate trace / recall id / backtest id |
| `risk_flags` | string[] | 否 | 命中禁令时进 G4 |
| `cost_estimate` | object | 否 | `{tokens:int, tool_calls:int}` |
| `expected_outcome` | string | 否 | ≤1000 字 |
| `validation.evaluator_refs` | string[] | 是 | `^45\.[a-z0-9_]+@\d+\.\d+\.\d+$` |
| `validation.acceptance_checks` | string[] | 否 | 可观测验收项 |
| `validation.outcome` | string | 否 | 执行后回填 |
| `debate_meta` | object | 否 | `{debate_id, side: A/B, verdict: WIN/LOSE/INCONCLUSIVE}` |

不支持字段不报错（容错），但未知字段不参与门禁与评分。

---

## 4. outbox 条目契约

路径：`bridge/outbox.jsonl`（append-only）；每行一个 JSON 对象。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `type` | string | 是 | 必须命中 R6 映射表，否则拒写 |
| `content` | string | 是 | 非空且 ≤300 字 |
| `tags` | string[] 或逗号串 | 是 | 必须含 `protocol-bridge` |
| `source_ref` | string | 是 | 可追溯（编排器写 `run_id:card_id`） |
| `bridge_ts` | string | 是 | ISO8601 带时区 |

R6 质量映射：

| type | quality_level |
|---|---|
| `expertise_canon` | B |
| `expertise_candidate` | C |
| `debate_winner` | B |
| `debate_loser` | D |
| `brainstorm_winner` | B |
| `brainstorm_loser` | D |
| `session_summary` | C |

编排器实际写入示例（胜方）：

```json
{
  "type": "brainstorm_winner",
  "content": "[脑暴胜出][对比两种回撤控制方案] plancard=pc-01J... side=A score=0.912 steps=3 expected=...",
  "tags": ["protocol-bridge", "brainstorm", "52-lobehub", "winner"],
  "source_ref": "run-20261111T193000:pc-01J...",
  "bridge_ts": "2026-11-11T19:30:00+0800"
}
```

---

## 5. 蒸馏桥 CLI

```bash
python3 bridge/distill_bridge.py --once [options]
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--once` | 关 | 处理一批后退出（当前唯一模式） |
| `--outbox` | `BRIDGE_OUTBOX_PATH` 或 `bridge/outbox.jsonl` | 输入队列 |
| `--cursor` | `bridge/.cursor` | 已消费行号 |
| `--seen` | `BRIDGE_SEEN_PATH` 或 `bridge/.seen` | 内容指纹去重文件 |
| `--no-dedupe` | 关 | 关闭去重（调试用） |
| `--verbose / -v` | 关 | DEBUG 日志 |

统计输出（stderr，末行）：`批次完成: {'processed': n, 'written': n, 'skipped': n, 'errors': n}`。

| 退出码 | 含义 |
|---|---|
| 0 | `errors == 0` |
| 1 | 存在写壳失败（游标停在最后成功行，可重跑续传） |

幂等语义：

- `processed` 只统计游标之后的行；
- 校验失败 → `skipped` 且推进游标（毒丸不阻塞）；
- 指纹命中 → `skipped` 且推进游标（不重复写入认知库）；
- 传输失败 → `errors` 且**不推进**游标。

---

## 6. 批量与调度 CLI

### 6.1 `shadow_batch.py`

```bash
python3 orchestrator/shadow_batch.py [--intents-file PATH] [--log-path PATH] [--max N] [--n-per-side N] [--dry-run]
```

- 逐条 spawn `brainstorm_orchestrator.py --intent ... --json-out`，超时 300s；
- side-A / side-B 任一不可用 → 写 `{"ok":false,"skipped":"services_down"} ` 并跳过整批（不刷错误）；
- 退出码恒 0；结果落 `--log-path`（默认 `orchestrator/logs/shadow_batch.log`）。

### 6.2 `ops/supervisor.py`

```bash
python3 orchestrator/ops/supervisor.py [--hour 22] [--minute 30] [--dry-run]
```

- 每日固定时刻执行 `ops/daily_pipeline.sh`；
- `--dry-run` 只打印 `next run <ISO8601>`；
- pidfile：`orchestrator/ops/.supervisor.pid`；SIGTERM/SIGINT 优雅退出。

### 6.3 `ops/daily_pipeline.sh`

```bash
bash 52-lobehub协议集成/orchestrator/ops/daily_pipeline.sh
```

顺序：`shadow_batch.py --max 5 --n-per-side 2` → `distill_bridge.py --once`；
退出码 = 任一环节失败即非 0；汇总写 `orchestrator/logs/pipeline.log`。

---

## 7. 3.1 HTTP 路由

全部位于 `3.1-FRONTEND/src/app/api/agent/`，统一降级信封：

```json
{"ok": false, "data": null, "degraded": true, "error": "<code>"}
```

### 7.1 `POST /api/agent/brainstorm`

| 项 | 值 |
|---|---|
| Body | `{ "intent": string, "nPerSide"?: 1-3, "force"?: boolean }` |
| 校验 | `intent` 非空且 ≤2000 字；否则 200 `degraded` + `intent_required / intent_too_long` |
| 行为 | spawn 编排器 CLI（`--intent ... --json-out`），超时 180s kill |
| 成功 | 200 + stdout 末行 JSON（即 §2.2 摘要） |
| 失败 | 200 `degraded` + `orchestrator_failed / bad_json / timeout` |
| 其他方法 | 405 |

### 7.2 `POST /api/agent/plan`（side-A）

| 项 | 值 |
|---|---|
| Body | `{ "intent": string, "context_refs"?: string[], "variant"?: {focus, seed} }` |
| 行为 | Vercel AI SDK 选模型 → 生成 PlanCard → `validatePlanCard` 校验 |
| 校验失败 | 200 `degraded` + 错误明细（绝不 500） |
| 未配置模型 | 200 `degraded` |
| 其他方法 | 405 |

### 7.3 `POST /api/agent/chat`

| 项 | 值 |
|---|---|
| Body | `{ "messages": UIMessage[], "provider"?: string, "model"?: string }` |
| 行为 | 模型路由 + MCP 工具消费（含会话摘要写入 outbox） |
| 未配置/异常 | 200 `degraded`，不阻塞主链路 |
| 其他方法 | 405 |

---

## 8. MCP 工具面与授权

| 消费方 | 角色 | 允许工具 | 强制方式 |
|---|---|---|---|
| 3.1 协议层 | `lobehub_frontend` | 只读（如 `recall`、`unified_search`） | 47 registry profile + drift 检查 |
| 蒸馏桥 | `orchestrator` | `record`、`verify` | 代码层白名单断言 `ALLOWED_TOOLS` |
| Debate 壳 | `orchestrator` | `start_debate`、`get_debate_result` | 壳层参数校验 + 铁律⑤ |
| 任何 52 组件 | — | **禁止** trade-exec 及一切交易写工具 | G3/G4 + registry 角色 |

桥调壳时的环境变量覆写（仅此三项）：

```text
COGNITIVE_MCP_MODE=ssh
COGNITIVE_MCP_WRITE_ENABLED=true
COGNITIVE_MCP_DEFAULT_PRINCIPAL=orchestrator
```

`record` 参数由 `build_record_arguments()` 生成：

```json
{
  "content": "<≤300 字>",
  "quality_level": "B",
  "tags": "protocol-bridge,brainstorm,52-lobehub,winner",
  "source": "protocol-bridge",
  "external_id": "bridge:<source_ref>"
}
```

---

## 9. trace 字段

每轮一行（`orchestrator/traces/brainstorm.jsonl`）：

| 字段 | 说明 |
|---|---|
| `run_id` / `trace_id` | 本轮唯一标识 |
| `intent` / `context_refs` | 输入 |
| `route` / `route_rules_version` / `mode` | 路由结果（`debate`/`workers`） |
| `n_per_side` / `pool_size` | 发散与去重后池大小 |
| `proposals[]` | 原始提案（含 `proposer_id`、`model`、`model_kind`、`evidence_path`） |
| `diversity_violations[]` | 铁律⑤ 违规明细 |
| `gates[]` | `{card_id, verdict, reasons}` |
| `scores[]` | `{card_id, score, verdict, breakdown, evaluator_provenance}` |
| `domain_eval` | `{available, names, verdicts}` |
| `triggers` | `{escalate, fired, detail}`（T1 `basis` 标注 `cross_side`/`top2`） |
| `decision` | `{kind: dispatch\|escalate_debate, ...}` |
| `debate` | `{debate_id, error}` |
| `adjudication` | `{heuristic_top, grounded_winner, agree}`（不参与决策） |
| `outbox_written` | 写入条数 |
| `executed` / `execution` | 实盘执行结果（shadow 恒 false） |

---

## 10. 错误码速查

| 来源 | code | 触发 |
|---|---|---|
| 编排器 stderr | `live gate denied: ...` | live 门禁未过（exit 2） |
| 3.1 brainstorm | `intent_required` | 空 intent |
| 3.1 brainstorm | `intent_too_long` | >2000 字 |
| 3.1 brainstorm | `orchestrator_failed` / `bad_json` / `timeout` | spawn 失败 / 非 JSON / 超 180s |
| 3.1 plan | `messages_required` / 校验明细 | 参数缺失 / PlanCard 不合规 |
| 桥 | `unknown_type` / `content_empty` / `content_too_long` / `missing_protocol_bridge_tag` / `missing_source_ref` / `missing_bridge_ts` | 条目不合规（计 `skipped`） |
| 45 适配 | `45_unavailable` / `evaluator_not_found` / `missing_artifacts` / `artifact_not_evaluated` | 均落到 `INCONCLUSIVE` |
