# 数据源与许可登记

> 判据是**许可条款明确允许商用再分发**，不是"能不能打开"。未登记的数据源一律不得进入输出（`E_LICENSE`）。

## 1. 已启用（本期上架）

| 源 | 端点 | 许可 | 可商用 | 署名要求 | 用途 |
|---|---|---|---|---|---|
| FRED | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>` | Public Domain | ✅ | 建议标注来源 | D1 宏观序列 |
| SEC EDGAR — 结构化字段 | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | Public Domain | ✅ | 标注 SEC EDGAR | D2 披露字段 |
| SEC EDGAR — 披露清单 | `https://data.sec.gov/submissions/CIK##########.json` | Public Domain | ✅ | 标注 SEC EDGAR | D2 文件清单 |
| SEC — ticker 映射 | `https://www.sec.gov/files/company_tickers.json` | Public Domain | ✅ | 标注 SEC | ticker→CIK |
| 以太坊公共 RPC | `https://ethereum.publicnode.com`（主）<br>`https://rpc.flashbots.net`（备） | 公有链数据自采（public chain, self-collected） | ✅ | 无需署名 | D5 区块指标 |

## 2. 已登记未启用

| 源 | 端点 | 许可 | 状态 | 原因 |
|---|---|---|---|---|
| ECB 数据 API | `https://data-api.ecb.europa.eu/service/data/...` | 免费使用，需署名 | 🟡 后备 | 单次 9s+，仅在显式指定时调用 |
| World Bank | `https://api.worldbank.org/v2/...` | CC BY 4.0 | 🔴 停用 | 本机 TLS 握手失败 |
| ECB 新闻 RSS | `https://www.ecb.europa.eu/rss/press.html` | 免费使用 | 🔴 停用 | 本机 TLS 失败 |

## 3. 明确排除（禁止接入）

| 源 | 原因 |
|---|---|
| 腾讯行情 / 新浪财经 / 东方财富 | 公开可访问但禁止商业再分发（默认不接；书面例外仅见 `contracts/data-sources.yaml` 的 DC-1，本组件不适用） |
| 上交所 / 深交所行情 | 需信息经营许可 |
| Yahoo Finance | 条款禁止再分发与商用 |
| CoinGecko / CoinMarketCap 免费档 | 免费档禁商用；D5 改走自采 |
| Reuters / Bloomberg 等商业媒体 | 订阅协议禁止再分发 |

## 4. 请求规范

1. 统一声明式 UA：`market-data-hub/1.0 (research; contact: ops@neodrm.com)`，并附联系方式（SEC 要求）
2. 单次失败最多重试 2 次（退避 0.8s / 1.6s）；仍失败标 `E_NET` / `E_TLS` / `E_HTTP_4xx`
3. 不缓存、不落盘、不转发原始响应全文
4. 新增数据源必须先在本文件登记「许可 / 可商用 / 署名」三列，再改代码
