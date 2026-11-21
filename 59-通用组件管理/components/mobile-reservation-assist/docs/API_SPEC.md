# API 规格 — 手机预约助手（mobile-reservation-assist）v0.15.0

## HTTP 网关

Base: `http://<host>:<port>`（默认 `127.0.0.1:8765`）
鉴权：请求头 `X-MRA-Token: <token>`，或查询/请求体 `token=<token>`；`/health` 免鉴权。
完整 OpenAPI 3.1 描述见仓库 `docs/OpenAPI契约.md`。

### GET /health
200 → `{"ok": true}`

### GET /commands?device_id=<id>&limit=<n>
- 401 未授权
- 200 → `{"jobs": [command...], "count": n}`；暂停时 `{"jobs": [], "paused": true}`
- 认领：服务端原子把 pending 置 dispatched，绑定 device_id，并回写 `trace_id`。
- 多设备：每次调用刷新 `devices.last_seen`；认领前自动回收掉线设备（90s 无心跳）的未完成作业。
  绑定 `preferred_device` 的作业只对该设备可见；`attempts` 达 2 次仍掉线则置 `failed`。

command 结构：
```json
{
  "job_id": 1,
  "adapter": "railway",
  "app": "com.MobileTicket",
  "target": {"target_id": "G1", "session": "2026-12-01", "price_tier": "二等座"},
  "max_price": 600,
  "steps": [{"action": "open_app", "app": "..."}, "..."],
  "stop_before": "payment",
  "trace_id": "1-1a2b3c4d-1763712000000",
  "receipt": {
    "schema": "mra.receipt.v1",
    "required": ["trace_id", "stage", "screenshot", "page_text", "order_id"]
  }
}
```

`steps[].action` 必须是 L3 已登记工具（见 `phone_tools/registry.py`）；`pay/submit_order/lock_seat` 永不入列。

### POST /results
请求体：
```json
{
  "job_id": 1,
  "device_id": "dev-1",
  "state": "needs_human",
  "trace_id": "1-1a2b3c4d-1763712000000",
  "detail": {
    "stage": "order_confirm",
    "screenshot": "agent_debug/job_1.png",
    "page_text": "确认订单 | 实付 380 元",
    "order_id": "B20261225001"
  }
}
```
- 401 未授权 / 400 缺 job_id
- 200 → `{"ok": true, "result": {"job_id": 1, "state": "pending_human", "trace_id": "..."}}`

回执状态映射：

| 回执 state | 作业状态 |
|---|---|
| ok / success / done | done |
| needs_human / pending_human | pending_human |
| takeover / needs_login / login | takeover |
| order_unknown | order_unknown |
| captcha / risk / blocked | cooldown |
| rejected / error / failed | failed（若 `detail.stage` ∈ 下单阶段 → order_unknown） |

结构化回执：服务端 `normalize_receipt()` 补齐 `trace_id/stage/screenshot/page_text/order_id`，`page_text` 截断 2000 字，并写入 `results` 结构化列。
幂等：同一 `(trace_id, 归一状态)` 重复回传返回 `result.duplicate=true`，不重复落库。

## CLI 对账

```bash
# 列出待对账（order_unknown）作业
python3 skill/scripts/mra.py reconcile --json

# 人工/对账收敛（幂等；仅 order_unknown 可收敛）
python3 skill/scripts/mra.py reconcile --job 12 --state done --order-id B123 --note "人工确认已下单"
python3 skill/scripts/mra.py reconcile --job 13 --state failed --note "确认未生成订单"
```

### GET /explore?device_id=<id>
- 401 未授权
- 200 → `{"exploration": {"_id": 1, "app": "bilibili", "goal": "...", "state": "recording", ...} | null, "interval_ms": 1500}`

### POST /snapshots
请求体：
```json
{
  "exploration_id": 1,
  "device_id": "dev-1",
  "package": "tv.danmaku.bili",
  "activity": ".MainActivity",
  "page_text": "搜索 | 周杰伦",
  "screenshot": "/sdcard/.../agent_debug/job_explore1_xxx.png",
  "nodes": [{"cls": "TextView", "text": "搜索", "desc": "", "clickable": true, "bounds": [0, 100, 720, 160]}]
}
```
- 400 缺 `exploration_id`
- 404 会话不存在
- 409 会话已停止（`exploration_not_recording`）
- 200 → `{"ok": true, "seq": 3, "duplicate": false}`（`duplicate=true` 表示与上一帧签名一致，仍保留轨迹）

### POST /locate
请求体：
```json
{
  "intent": "会员购",
  "device_id": "dev-1",
  "use_model": true,
  "nodes": [{"cls": "TextView", "text": "会员购", "desc": "", "clickable": true, "bounds": [0, 120, 720, 180]}]
}
```
- 400 缺 `intent` 或 `nodes`
- 401 未授权
- 200 → `locator.v1`：`{schema,intent,ok,source,best,candidates,reason}`

`source`：`rules`（规则命中）/ `model`（本地小模型复核）/ `guard`（支付红线，直接拒绝）。
`best` 含 `index/text/desc/cls/clickable/bounds/score`，手机端按 `bounds` 点击。

### POST /vision/locate
请求体：
```json
{
  "intent": "会员购",
  "device_id": "dev-1",
  "blocks": [{"text": "会员购", "confidence": 0.96, "bounds": [40, 300, 300, 380]}]
}
```
- 400 缺 `intent` 或 `blocks`
- 401 未授权
- 200 → `vision.v1`：`{schema,intent,ok,source,best,candidates,reason}`

过滤规则：空文本、置信度 `< 0.5`、非法坐标（非 4 元组 / 负坐标 / 右下不大于左上）。
`best` 含 `block_index/text/bounds/score/confidence`。`source`：`ocr` / `guard`。

## 探索录制（CLI）

```
mra explore start --app <平台> --goal "<目标>" [--device-id <id>]
mra explore list
mra explore show --id <会话ID>
mra explore stop --id <会话ID>
mra explore draft --id <会话ID> [--out 路径] [--json]
```

`draft` 输出 `explore.draft.v1`：`steps[] / assertions[] / warnings[] / ready / adapter_source`。
`--out` 时把 `adapter_source` 写入目标路径（默认不落盘）；`ready=false` 时退出码 3。

## 回放兼容门禁（CLI）

```
mra explore baseline --id <会话ID> --name <适配器名>
mra explore check --name <适配器名> --id <新会话ID> [--threshold 0.8] [--json]
```

`check` 输出 `explore.check.v1`：

```json
{
  "schema": "explore.check.v1",
  "name": "bilibili",
  "exploration_id": 2,
  "compatible": true,
  "coverage": 1.0,
  "threshold": 0.8,
  "snapshot_count": 5,
  "matched": [{"seq": 1, "matched_seq": 1}],
  "missing": [],
  "step_misses": []
}
```

判定：`coverage >= threshold` 且 `step_misses` 为空才 `compatible=true`；否则退出码 3。

## 回归任务集（CLI）

```
mra regression add --case-id c1 --baseline bilibili --id 2 [--expect compatible|incompatible] [--tags smoke]
mra regression list [--tag smoke] [--limit 10] [--json]
mra regression run [--tag smoke] [--threshold 0.8] [--json]
```

`run` 输出 `regression.v1`：

```json
{
  "schema": "regression.v1",
  "run_id": 1,
  "tag": "smoke",
  "threshold": 0.8,
  "total": 2,
  "passed": 1,
  "failed": 1,
  "errors": 0,
  "ok": false,
  "duration_ms": 12,
  "cases": [
    {"case_id": "c1", "baseline": "bilibili", "exploration_id": 2,
     "expect_compatible": true, "compatible": true, "coverage": 1.0,
     "verdict": "pass", "step_misses": []}
  ]
}
```

判定：`compatible == expect_compatible` → `pass`，否则 `fail`；基线/快照缺失 → `error`。
`ok = 用例非空 且 failed=0 且 errors=0`；不满足时退出码 3。

## 输出契约

`mra report --json` → `reservation.v1`：
`schema_version / command / generated_at / tasks[] / hits[] / events[] / limits`（另附 `results[]`，含结构化证据字段）。

## 知识工具（CLI，只读）

```
mra knowledge ask "<问题>" [--app X] [--max-age 秒] [--no-cache] [--timeout 150] [--json]
```

输出 `knowledge.v1`：

```json
{
  "schema": "knowledge.v1",
  "question": "...",
  "app": "bilibili",
  "ok": true,
  "answer": "...",
  "citations": [{"type": "url", "value": "https://..."}],
  "confidence": 0.9,
  "side_effect": "none",
  "source": "qianwen-app",
  "cached": false,
  "unsafe_actions_detected": false,
  "asked_at": "2026-11-21T12:00:00+08:00"
}
```

- 同 `(app, question)` 在 TTL（默认 7 天）内命中缓存时 `cached=true`，不再占用手机。
- 传输失败（超时/异常）返回 `ok=false`、`confidence=0`、`note` 带原因，退出码 3。
- 无引用时 `confidence ≤ 0.6`；答案含支付/提交类指令时行级遮蔽且 `confidence ≤ 0.3`。

## 顺风车抢单桥接（服务端 `src/services/mra_bridge.py`）

旧手机端协议不变，服务端把顺风车指令映射为 `adapter=carpool` 作业：

| 旧端点 | 桥接行为 |
|---|---|
| `POST /api/v1/phone/heartbeat` | `map_heartbeat_commands()`：`platform ∈ didi\|dida\|hello`（或 `adapter=carpool`）且动词 `start/refresh/accept/stop` 时建 job，`phone_job_links` 记录 `command_id → job_id/trace_id`；返回结构仍是 `{id, command, params}` |
| `POST /api/v1/phone/command/result` | `apply_legacy_result()`：`completed→done`；`accept` 无订单号→`pending_human`；`accept` 失败→`order_unknown`；响应新增 `bridge` 字段 |
| `POST /api/v1/phone/order` | `observe_order()`：只写 `events(phone_order_observed)`，不建 job、不改订单状态 |

动词映射：`start→scan_session`、`refresh→scan_once`、`accept→accept_order`、`stop→stop_scan`；`config/status` 不建 job。
开关：`MRA_PHONE_BRIDGE`（默认开）、`MRA_ACCEPT_ENABLE`（默认关）。接单还需 `params.accept_authorized=true`、当日 `max_accept` 未用尽、价格不低于下限。
设备端二次开关：`config.json` 的 `accept.enabled`（默认关闭）。关闭时 accept 回「自动接单未开启，请人工接单」→ `pending_human`；开启后按订单定位卡片点击接单，成功回传订单号。`accept.max_per_day` 为设备侧单日上限；`config` 指令可热更新 `accept_enabled` / `max_accept`。

```
mra carpool start --platform didi [--min-price 30] [--max-accept 1]
mra carpool refresh --platform didi
mra carpool accept --platform didi --order-id D123 --accept
mra carpool stop --platform didi
mra carpool status [--json]
```
