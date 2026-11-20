# 返回样例（脱敏）

> 字段结构与线上一致；数值为示例，不代表当前市场。

## 1. 首次调用（HTTP 402）

```text
$ python3 scripts/pay.py --cmd macro --series DGS10,CPIAUCSL
需要按次付费（金额 2.99 元，订单 PAY_1795169006965_001，请在 2026-11-20T18:33:26+08:00 前完成）
  商品：数据服务专业版数据查询（资源 /api/paid/data）
获取 Payment-Proof 的三种方式：
  1) 支付宝 AI 按量付费：按 Payment-Needed 账单完成支付后取回凭证；
  2) 平台订单页：用订单号 PAY_1795169006965_001 查询并复制凭证；
  3) 让 Agent 从支付回调或支付结果邮件中读取凭证。
完成支付后重试（同一凭证重复提交不会重复扣费）：
  python3 pay.py --cmd macro --series DGS10,CPIAUCSL --proof <Payment-Proof>
```

退出码 `2`。

## 2. 携带凭证重试（HTTP 200）

```json
{
  "resource_id": "/api/paid/data",
  "skill": "market-data-pro",
  "cmd": "macro",
  "rows": [
    {
      "series": "DGS10",
      "latest": {"date": "2026-11-18", "value": 4.12},
      "change_1m": -0.08,
      "change_3m": 0.21,
      "percentile_1y": 62.5,
      "vol_annual": 0.83,
      "n": 252
    }
  ],
  "missing": [],
  "data_date": "2026-11-18",
  "sources": [{"name": "FRED", "license": "public-domain"}],
  "method_ids": ["macro.latest_change_percentile.v1"]
}
```

字段说明：

| 字段 | 含义 |
|---|---|
| `rows` | 每个标的/序列的统计事实；空值不出现在 rows 中 |
| `missing` | 数据源不可用的序列或标的，标注原因 |
| `data_date` | 数据截止日（不是调用时间） |
| `sources` | 来源与许可，可复核 |
| `method_ids` | 计算方法编号，配合口径文档使用 |

## 3. 只检查请求体（不联网、不产生订单）

```text
$ python3 scripts/pay.py --cmd quotes --symbols sh600519 --describe
{
  "skill": "market-data-pro",
  "cmd": "quotes",
  "params": {"symbols": "sh600519"}
}
```

## 4. 幂等重放

同一凭证再次提交时返回首次结果，并在末尾提示：

```text
（该订单此前已交付，本次为幂等重放，未重复扣费）
```
