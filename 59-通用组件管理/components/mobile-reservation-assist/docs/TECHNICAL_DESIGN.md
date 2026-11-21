# 技术设计 — 手机预约助手（mobile-reservation-assist）v0.12.0

## 1. 背景

上游 `reservation-assist` 已能监控放票并产生命中，但只有网页端 `Transport`（fetch/浏览器），缺少"手机端操作"通道。本组件补上：把命中转为手机端预约动作，由常驻 Agent 在手机上执行，停在官方下单页并预填，最终人工确认与支付。

## 2. 架构

```
reservation-assist 命中
  └─ mra ingest（只读 ra report/watch list --json，归一+去重）
      └─ SQLite jobs（含 trace_id）
          └─ mra gateway（本地 HTTP + Token）
              ├─ GET  /commands  手机 Agent 认领（原子置 dispatched + 下发 trace_id）
              └─ POST /results   结构化回执 → executor.apply_result
                                   → done / pending_human / takeover / order_unknown / cooldown / failed
                                        └─ order_unknown → mra reconcile（人工对账收敛）
```

## 3. 分层（P0 工具分层）

```
L3 语义工具层  phone_tools/
   registry.TOOLS：open_app / goto / search / select_session / select_tier /
                   fill_identity / goto_order_page / stop（UI）
                   capture_screenshot / read_page_text / read_order_status（只读证据）
                   pay / submit_order / lock_seat（forbidden，构建即拒绝）
   policy：FORBIDDEN_TOKENS + assert_no_payment + CommandError

L4 业务编排层  phone_adapters/
   BasePhoneAdapter._steps：按平台把 L3 工具编排成动作序列
   describe()：validate_steps 复检 → 输出 command（含 stop_before=payment）
```

纪律：L3 不含任何平台词（架构测试守护）；L4 只能调用已登记工具；高/不可逆风险工具不进入自动编排。

## 4. 模块职责

| 模块 | 职责 |
|---|---|
| ingest.py | 归一上游命中（join tasks 目标明细），按 `task_id+fingerprint` 去重入队 |
| store.py | SQLite：jobs/results/events/meta；WAL + BEGIN IMMEDIATE；状态迁移守卫；对账；TTL |
| gateway.py | ThreadingHTTPServer；`/health` 免鉴权，`/commands` `/results` 需 Token；回写 trace_id |
| executor.py | `build_command` 翻译动作序列（强制 stop before payment）；门禁；回执状态映射与结构化 |
| knowledge.py | `knowledge.ask`：三段式提问 → 解析引用/置信度 → 安全遮蔽 → TTL 缓存 |
| explore.py | 探索录制：快照 → 页面签名/断言 → L3 工具草案 → 适配器源码草案 |
| locator.py | 定位兜底：规则排序 + 本地小模型复核 → `locator.v1`（支付红线） |
| vision.py | 视觉兜底：OCR 块排序（置信度加权）→ `vision.v1`（支付红线） |
| regression.py | 回归任务集：基线 + 录制批量比对 → `regression.v1` |
| phone_tools/ | L3 语义工具注册表与风险策略（平台无关） |
| phone_adapters/ | L4 平台编排（6 个预约平台 + 千问咨询） |
| security.py | redact、Token（0600 文件）、容器判定、执行开关 |
| notify.py | 本地/飞书通道，失败不静默 |

## 5. 状态机

```
pending → dispatched → done | failed | cooldown
                     ├→ pending_human   等待人工确认（支付前/登录实名）
                     ├→ takeover        验证码/风控，人工接管
                     └→ order_unknown   下单响应不确定，等待对账
```

禁止迁移（`store.FORBIDDEN_TRANSITIONS`）：`order_unknown / pending_human / takeover` 不得迁回 `pending` 或 `dispatched`。
`order_unknown` 只能经 `store.reconcile()` 收敛为 `done/failed`（幂等）。

## 6. 安全门禁

- `MRA_ALLOW_EXECUTE=0` 或容器内 → 不派发（`GateDenied("env")`）。
- 全局 `pause` → `/commands` 返回空。
- 一次性：`(task_id, fingerprint)` 处于阻断态（终态/等人工/接管/订单未知）即拒绝重复。
- 无支付：动作序列含支付/锁座/占座词 → `CommandError`，构建即拒绝。
- 回执 `captcha/risk/blocked` → `cooldown`，不自动重试。
- 下单阶段报错/超时 → `order_unknown`，禁止自动重试，必须对账。

## 7. 数据模型

```
jobs(id, adapter, task_id, fingerprint, at, payload_json, state, device_id,
     dispatched_at, updated_at, trace_id, preferred_device, attempts, UNIQUE(task_id,fingerprint))
devices(device_id PK, first_seen, last_seen, last_state)
regression_cases(case_id PK, baseline_name, exploration_id, expect_compatible, tags, created_at)
regression_runs(id PK, started_at, report_json)
results(id, job_id, device_id, state, detail_json, trace_id, stage, screenshot, order_id, at)
events(id, at, level, code, task_id, payload_json)
knowledge_cache(fingerprint PK, app, question, payload_json, created_at, expires_at)
explorations(id, app, goal, state, device_id, started_at, stopped_at)
snapshots(id, exploration_id, seq, at, package, activity, page_text, screenshot, nodes_json, signature)
adapter_baselines(name PK, app, exploration_id, steps_json, assertions_json, created_at)
meta(key, value)   # schema_version(=7) / paused
```

老库升级：`_migrate()` 通过 `PRAGMA table_info` 检测后 `ALTER TABLE ADD COLUMN`。

## 8. 分期

- P0（v0.5.0 已完成）：工具分层、三态补齐、订单对账+幂等、结构化回执。
- P1（已完成，v0.8.0）：`knowledge.ask`、`mra explore`（录制 + 草案）、回放兼容门禁。
- P2（已完成，v0.12.0）：定位兜底、视觉兜底、多设备并发、回归任务集。
