# 事件源登记

> 只采**政府 / 监管机构公开文件**。未登记来源不得进入上下文包（`E_LICENSE`）。
> 每条输出必须带 `license` 字段；不转载正文，只取标题与结构化字段。

## 1. 已启用

| source_key | 端点 | 许可 | 可商用 | 署名 | 事件类型 | 实测 |
|---|---|---|---|---|---|---|
| `sec-submissions` | `https://data.sec.gov/submissions/CIK##########.json` | Public Domain | ✅ | 标注 SEC EDGAR | 8-K / 10-K / 10-Q / 4 / 144 | ✅ 2.6s |
| `sec-press` | `https://www.sec.gov/news/pressreleases.rss` | Public Domain | ✅ | 标注 SEC | 监管公告 | ✅ 1.7s |
| `fed-all` | `https://www.federalreserve.gov/feeds/press_all.xml` | Public Domain | ✅ | 标注 Federal Reserve | FOMC 声明 / 纪要 / 讲话稿 | ✅ 3.8s（TLS 偶发抖动） |

辅助端点（仅用于 ticker→CIK 映射）：

| 端点 | 许可 | 说明 |
|---|---|---|
| `https://www.sec.gov/files/company_tickers.json` | Public Domain | 声明式 UA 可用；Chrome UA 会 TLS 断连 |

## 2. 已登记未启用

| source_key | 端点 | 许可 | 原因 |
|---|---|---|---|
| `ecb-press` | `https://www.ecb.europa.eu/rss/press.html` | 免费使用，需署名 | 本机 TLS 握手失败（`SSL: UNEXPECTED_EOF`） |
| `ecb-data` | `https://data-api.ecb.europa.eu/service/data/...` | 免费使用，需署名 | 可用但单次 9s+，非事件型，暂不纳入 |

## 3. 明确排除

| 来源 | 原因 |
|---|---|
| Reuters / Bloomberg / WSJ / FT | 订阅协议禁止再分发 |
| 新浪财经 / 东方财富 / 财联社 | 版权不明或禁止转述 |
| 各类聚合 API 的新闻字段 | 上游多为商业媒体，无法逐个核实授权 |

## 4. 引述与著作权约束

1. `headline_facts` 单条 ≤80 字，总引述 ≤300 字
2. 只存标题、链接、结构化字段（时间/类型/事项编号/报告期），**不存正文**
3. 输出必须带 `license` 与 `url`，使用者可回溯原文
4. 不做翻译改写、不做摘要压缩、不做情感标注

## 5. 请求规范

1. 统一 UA：`event-context/1.0 (research; contact: ops@neodrm.com)`，附联系方式（SEC 要求）
2. 单次失败最多重试 2 次（退避 0.8s / 1.6s），仍失败标 `E_NET` / `E_TLS` / `E_HTTP_4xx`
3. 不缓存、不落盘、不转发原始响应
4. 新增源：先补本文件，再改 `events.py` 的 `FEEDS`
