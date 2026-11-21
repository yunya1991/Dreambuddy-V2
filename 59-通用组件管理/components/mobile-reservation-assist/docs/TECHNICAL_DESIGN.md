# 技术设计 — 手机预约助手（mobile-reservation-assist）v0.1

## 1. 背景

上游 `reservation-assist` 已能监控放票并产生命中，但只有网页端 `Transport`（fetch/浏览器），缺少"手机端操作"通道。本组件补上：把命中转为手机端预约动作，由常驻 Agent 在手机上执行，停在官方下单页并预填，最终人工确认与支付。

## 2. 架构

```
reservation-assist 命中
  └─ mra ingest（只读 ra report/watch list --json，归一+去重）
      └─ SQLite jobs
          └─ mra gateway（本地 HTTP + Token）
              ├─ GET  /commands  手机 Agent 认领（原子置 dispatched）
              └─ POST /results   回执 → executor.apply_result → done/unknown/cooldown/failed
```

## 3. 模块职责

| 模块 | 职责 |
|---|---|
| ingest.py | 归一上游命中（join tasks 目标明细），按 `task_id+fingerprint` 去重入队 |
| store.py | SQLite：jobs/results/events/meta，WAL + BEGIN IMMEDIATE，TTL |
| gateway.py | ThreadingHTTPServer；`/health` 免鉴权，`/commands` `/results` 需 Token |
| executor.py | `build_command` 翻译动作序列（强制 stop before payment）；门禁；回执状态映射 |
| phone_adapters/ | 6 平台动作定义；`assert_no_payment` 结构性禁止支付/锁座 |
| security.py | redact、Token（0600 文件）、容器判定、执行开关 |
| notify.py | 本地/飞书通道，失败不静默 |

## 4. 安全门禁

- `MRA_ALLOW_EXECUTE=0` 或容器内 → 不派发（`GateDenied("env")`）。
- 全局 `pause` → `/commands` 返回空。
- 一次性：`(task_id, fingerprint)` 有终态即拒绝重复。
- 无支付：动作序列含支付/锁座/占座词 → `CommandError`，构建即拒绝。
- 回执 `captcha/risk/blocked` → `cooldown`，不自动重试。

## 5. 数据模型

```
jobs(id, adapter, task_id, fingerprint, at, payload_json, state, device_id, dispatched_at, updated_at, UNIQUE(task_id,fingerprint))
results(id, job_id, device_id, state, detail_json, at)
events(id, at, level, code, task_id, payload_json)
meta(key, value)   # schema_version / paused
```

## 6. 分期

- P0（本版）：骨架 + 治理全绿 + 网关 + FakeAgent 全链路 + 6 平台动作占位。
- P1：6 平台真机选择器与步骤细化；launchd 托管 ingest/gateway；真机联调。
