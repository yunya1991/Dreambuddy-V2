---
name: market-data-pro
slug: market-data-pro
displayName: 数据服务专业版（按次付费）
version: 1.0.2
summary: 按次付费的数据服务：海外宏观、美股披露、A股/港股/美股行情与链上数据，全部返回可复核的结构化事实。
description: 按次付费的数据服务：海外宏观、美股披露、A股/港股/美股行情与链上数据，全部返回可复核的结构化事实。
license: 商业授权（按次计费）
---

# 数据服务专业版（按次付费）

当用户需要**可复核的市场数据事实**时使用本技能：宏观指标、公司披露字段、行情统计、链上数据、交叉统计。输出恒为「数值 + 样本量 + 方法ID + 数据时间戳 + 来源与许可」，不含方向判断、评级、目标价。

## 计费方式

- **按次收费**，每次调用 ¥2.99。
- 协议：HTTP 402（`Payment-Needed`）→ 支付宝支付 → 携带 `Payment-Proof` 重试。
- 计费单元：一次数据请求（一个 `cmd`，可批量传入多个标的/序列）。

## 调用方式

```bash
# 第一次调用会返回 402 与待支付订单
python3 scripts/pay.py --cmd macro --series DGS10,CPIAUCSL

# 支付完成后，用支付凭证重试同一请求
python3 scripts/pay.py --cmd macro --series DGS10,CPIAUCSL --proof <Payment-Proof>
```

服务地址：`https://www.neodrm.com/api/paid/data`（可用环境变量 `MDP_ENDPOINT` 覆盖）。

## 支持的命令

| cmd | 参数 | 返回内容 |
|---|---|---|
| `macro` | `series`（逗号分隔，如 `DGS10,CPIAUCSL`）、`window` | 最新值、1/3 月变动、区间分位、年化波动、样本量 |
| `filings` | `ticker`、`form`、`limit`、`facts` | SEC 披露清单或指定字段（10-K/10-Q/8-K） |
| `quotes` | `symbols`（`sh`/`sz`/`hk`/`us` 前缀）、`window` | 收盘、1/5/20 日变动、分位、波动、最大回撤 |
| `onchain` | `chain`、`blocks` | 区块高度、出块间隔、交易数、gas 消耗 |

## 输出约定

- 每次返回 `rows`、`missing`、`data_date`、`sources`（含 `license`）、`method_ids`。
- 数据源不可用时标注 `数据不可用`，不估算、不编造。
- **不输出**「利多/利空/值得关注/影响有限/后续看涨」等定性结论，也不给推荐名单。

## 服务端付费协议（实现说明）

1. **402 挑战**：无 `Payment-Proof` 时返回 `HTTP 402`，响应头 `Payment-Needed` 携带签名账单（`out_trade_no`、`amount`、`pay_before`、`resource_id`、`seller_signature`），同时本地落库为待支付订单。
2. **验付调用**：收到 `Payment-Proof` 后调用 `alipay.aipay.agent.payment.verify` 校验凭证，得到 `trade_no`、实付金额与 `resource_id`；任一项与本地订单不一致即重新返回 402。
3. **交付**：验付通过后执行数据请求，结果写入订单（`service_result`），同一凭证重复提交直接返回首次结果，不重复计费（幂等）。
4. **履约确认**：交付成功后调用 `alipay.aipay.agent.fulfillment.confirm` 完成履约确认，并把订单标记为 `FULFILLED`；确认失败返回 502，允许用同一凭证重试。

## 边界

- 仅提供已发布数据的统计事实；历史分布不等于未来走势。
- 付费凭证与订单绑定，同一凭证重复使用返回首次结果，不重复计费。

## 版本记录

| 版本 | 日期 | 说明 |
|---|---|---|
| 1.0.1 | 2026-11-20 | 补 `description` 字段；新增「服务端付费协议」说明（402 挑战 / 验付调用 / 幂等交付 / 履约确认） |
| 1.0.0 | 2026-11-19 | 首次发布 |
