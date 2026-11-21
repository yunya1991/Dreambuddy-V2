# 技术设计 — reservation-assist

## 1. 分层

```
launchd(KeepAlive) → ra watch run
  ├─ scheduler：VirtualClock / Backoff / in_window
  ├─ adapter.probe(target, transport) → Snapshot
  ├─ adapter.match(snapshot, rule) → [Hit]
  ├─ store.upsert_hit（UNIQUE(task_id, fingerprint)）
  ├─ notify.deliver_once（notified_at 持久化，只发一次）
  └─ security.evaluate_submit（门禁）→ adapter.submit（P3）
```

内核（scheduler / store / notify / security / ra）不认识平台名；平台差异全部在 `adapters/`。

## 2. 数据模型

四张表：`tasks / hits / events / grants`（DDL 见 `store.py`）。要点：

- 指纹 `sha256(adapter|target_id|date|session|price_tier)`，date 按 Asia/Shanghai 归一
- 并发 `WAL + busy_timeout=5000 + synchronous=NORMAL`，写事务 `BEGIN IMMEDIATE` 重试 3 次
- TTL：hits 30d / events 90d，`secure_delete=ON`
- `meta.paused` 作为全局刹车

## 3. 对时

- `estimate_offset`：5 次采样取 RTT 最小 3 次；极差 ≤50ms 且 RTT ≤300ms 才采信
- `VirtualClock`：`t_v = monotonic + offset`，倒计时用 `t_v`
- 置信区间 >1.5s → 盲轮询 + 告警，不长期拒绝冲刺
- `WakeDetector`：`Δwall − Δmono > 5s` 判为休眠唤醒

## 4. 自动提交门禁链

1. `RA_ALLOW_SUBMIT != "0"` 且非容器/云主机
2. 适配器 `SUBMIT_READY is True`
3. `submit_enabled=1`、`max_orders=1`、价格上限、已选观演人/就诊人
4. grant 未过期、指纹一致、HMAC 校验通过（只存 HMAC，有效期 ≤2h）
5. 该指纹无 `submitted/unknown/closed` 记录

不满足任一条抛 `GateDenied` 并写 `submit_denied` 事件。终态停在官方页面，不支付、不锁座。

## 5. 隐私

`redact()` 覆盖证件号、手机号（留后 4）、cookie/token、地址；日志、events、report、`--json` 全部经过。

## 6. 分阶段

P0 骨架与闸门（当前）→ P1 四个演出/铁路适配器监控与 launchd → P2 医疗/政务 → P3 就绪实验后逐个开启 `SUBMIT_READY`。
