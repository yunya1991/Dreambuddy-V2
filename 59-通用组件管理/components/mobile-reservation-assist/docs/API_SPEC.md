# API 规格 — 手机预约助手（mobile-reservation-assist）v0.1

## HTTP 网关

Base: `http://<host>:<port>`（默认 `127.0.0.1:8765`）
鉴权：请求头 `X-MRA-Token: <token>`，或查询/请求体 `token=<token>`；`/health` 免鉴权。

### GET /health
200 → `{"ok": true}`

### GET /commands?device_id=<id>&limit=<n>
- 401 未授权
- 200 → `{"jobs": [command...], "count": n}`；暂停时 `{"jobs": [], "paused": true}`
- 认领：服务端原子把 pending 置 dispatched，绑定 device_id。

command 结构：
```json
{
  "job_id": 1,
  "adapter": "railway",
  "app": "com.MobileTicket",
  "target": {"target_id": "G1", "session": "2026-12-01", "price_tier": "二等座"},
  "max_price": 600,
  "steps": [{"action": "open_app", "app": "..."}, "..."],
  "stop_before": "payment"
}
```

### POST /results
请求体：
```json
{"job_id": 1, "device_id": "dev-1", "state": "ok", "detail": {"order_ref": "R1"}}
```
- 401 未授权 / 400 缺 job_id
- 200 → `{"ok": true, "result": {"job_id": 1, "state": "done"}}`

state 映射：`ok/success→done`；`needs_human→unknown`；`captcha/risk/blocked→cooldown`；`rejected/error→failed`。

## 输出契约

`mra report --json` → `reservation.v1`：
`schema_version / command / generated_at / tasks[] / hits[] / events[] / limits`（另附 `results[]`）。
