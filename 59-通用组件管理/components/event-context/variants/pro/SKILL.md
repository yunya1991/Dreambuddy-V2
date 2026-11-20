---
name: event-context-pro
slug: event-context-pro
displayName: 事件上下文专业版（按次付费）
version: 1.0.1
summary: 按次付费的事件上下文服务：从 SEC 与美联储官方公开源按主体或事件装配五层事实结构，输出事件、实体、同类事件次数、来源许可与边界声明。
description: 按次付费的事件上下文服务：从 SEC 与美联储官方公开源按主体或事件装配五层事实结构，输出事件、实体、同类事件次数、来源许可与边界声明，全部可复核。
license: 商业授权（按次计费）
---

# 事件上下文专业版（按次付费）

当用户需要**可复核的官方事件事实**时使用本技能：监管公告、公司披露事件、美联储声明，以及同类事件的历史发生次数。输出恒为「事件 + 实体 + 同类事件次数 + 来源许可 + 边界声明」，不含影响判断、方向判断或建议。

## 计费方式

- **按次收费**，每次调用 ¥2.99。
- 协议：HTTP 402（`Payment-Needed`）→ 支付宝支付 → 携带 `Payment-Proof` 重试。
- 计费单元：一次事件请求（一个 `cmd`，可批量传入多个主体或时间窗口）。

## 调用方式

```bash
# 第一次调用会返回 402 与待支付订单
python3 scripts/pay.py --cmd events --subject AAPL --since 30

# 支付完成后，用支付凭证重试同一请求
python3 scripts/pay.py --cmd events --subject AAPL --since 30 --proof <Payment-Proof>

# 装配五层上下文
python3 scripts/pay.py --cmd event-context --subject AAPL --latest
```

服务地址：`https://www.neodrm.com/api/paid/data`（可用环境变量 `ECP_ENDPOINT` 覆盖）。

### 通用参数

| 参数 | 说明 |
|---|---|
| `--proof` | 支付完成后回传的凭证；同一凭证重复提交不重复计费 |
| `--timeout` | 单次请求超时秒数，默认 60 |
| `--retries` | 带凭证时的重试次数，默认 2；无凭证调用不自动重试 |
| `--describe` | 只打印请求体，不联网、不产生订单 |

`--latest` 是布尔开关，不接受取值；参数在本地校验，拼错或缺失会直接报错且不发出请求。

- 返回样例与字段说明：[references/examples.md](./references/examples.md)
- 支付、`--latest`、断网、参数错误的处理：[references/faq.md](./references/faq.md)

## 支持的命令

| cmd | 参数 | 返回内容 |
|---|---|---|
| `events` | `subject`、`since`、`types`（逗号分隔，如 `8-K,10-Q`）、`feed`、`limit` | 事件清单：时间、来源、类型、主体、要点事实、原文链接 |
| `event-context` | `subject` 或 `event-id`（二选一）、`feed`、`latest` | 五层装配：event / entities / analogues / sources / assembly |

`event-id` 是哈希，需配合 `subject` 或 `feed` 才能反查来源范围。

## 输出约定

- 每条事件带 `event_id`、`url`、`license` 与 `retrieved_at`，可复核、可缓存。
- `analogues.n` 是同类事件的历史发生次数，只计数不做统计推断。
- 数据源不可用时标注 `数据不可用`，不估算、不编造。
- **不输出**「利多/利空/值得关注/影响有限」等定性结论，也不给排序或权重。

## 服务端付费协议（实现说明）

1. **402 挑战**：无 `Payment-Proof` 时返回 `HTTP 402`，响应头 `Payment-Needed` 携带签名账单（`out_trade_no`、`amount`、`pay_before`、`resource_id`、`seller_signature`），同时本地落库为待支付订单。
2. **验付调用**：收到 `Payment-Proof` 后调用支付宝验付接口校验凭证，得到 `trade_no`、实付金额与 `resource_id`；任一项与本地订单不一致即重新返回 402。
3. **交付**：验付通过后执行事件装配，结果写入订单（`service_result`），同一凭证重复提交直接返回首次结果，不重复计费（幂等）。
4. **履约确认**：交付成功后调用履约确认接口，并把订单标记为 `FULFILLED`；确认失败返回 502，允许用同一凭证重试。

## 边界

- 只装配已发生的官方事实与同类事件计数；不含影响判断、方向判断或建议。
- 付费凭证与订单绑定，同一凭证重复使用返回首次结果，不重复计费。

## 版本记录

| 版本 | 日期 | 说明 |
|---|---|---|
| 1.0.1 | 2026-11-20 | 评测整改：`--latest` 改为布尔开关并真实进入请求体、网络异常映射（不再抛栈）、`--timeout`/`--retries`/`--describe`、参数本地校验、支付凭证来源与失效提示；新增 examples / FAQ |
| 1.0.0 | 2026-11-19 | 首次发布 |
