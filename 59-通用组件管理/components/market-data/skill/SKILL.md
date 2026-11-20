---
name: market-data-hub
slug: dreambuddy-market-data-hub
displayName: 数据服务（宏观·披露·链上·上下文）
version: 1.0.1
summary: 海外宏观、美股披露、公有链指标三类开放数据，加数据上下文与交叉统计，每条附方法ID与样本量。
license: MIT
allowed-tools: Bash, Read
---

# 数据服务（market-data-hub）

## 0. 一句话

**只提供许可明确可商用的公开数据，以及基于其上的确定性计算：数值 + 样本量 + 方法ID + 来源许可 + 数据时间戳。**

不含行情预测、评级、目标价、推荐；不含任何方向判断。

---

## 1. 三块能力

| 能力 | 含义 | 对应命令 |
|---|---|---|
| A-1 开放数据接入 | 结构化原始序列与披露字段 | `macro.py` / `filings.py` / `onchain.py` |
| A-2 数据上下文 | 这个数字怎么读：单位、频率、样本区间、分布五数、当前位置 | `context.py --describe` |
| A-3 交叉统计 | 分组均值、条件分布、相关矩阵 | `context.py --cross` / `--basket` |

**模块覆盖**：D1 海外宏观（FRED）、D2 美股披露（SEC EDGAR）、D5 公有链指标（公共 RPC 自采）。
D4 海外指数/ETF 行情需商用授权，本期未开放。

---

## 2. 命令表

```bash
# D1 海外宏观
python3 scripts/macro.py --series DGS10,CPIAUCSL,UNRATE [--window 250] [--json]

# D2 美股披露：清单 / 字段
python3 scripts/filings.py --ticker AAPL [--form 8-K] [--limit 10]
python3 scripts/filings.py --ticker AAPL --facts RevenueFromContractWithCustomerExcludingAssessedTax,NetIncomeLoss

# D5 公有链
python3 scripts/onchain.py --chain eth [--blocks 50] [--json]

# A-2 数据上下文 / A-3 交叉统计（仅本地直连可用）
python3 scripts/context.py --describe DGS10 [--peers DGS2,FEDFUNDS]
python3 scripts/context.py --cross DGS10,CPIAUCSL [--bucket year|month]
python3 scripts/context.py --basket DGS10,DGS2,UNRATE

# 可装配指针清单（与认知管家配合）
python3 scripts/handoff.py --series DGS10,CPIAUCSL [--budget 2000] [--json]
```

退出码：`0` 全部成功 / `1` 部分或全部失败（输出含 `missing`）/ `2` 参数非法（不发请求）。

**数据通道**：所有取数命令都支持 `--endpoint auto|cloud|local`，默认 `auto` —— 先走云端 `www.neodrm.com`（连接 5 秒、响应 30 秒），失败立即回退本地直连；输出 JSON 带 `data_route`，Markdown 在「数据源」行标注「通道：云端/本地直连」。`--endpoint cloud` 时云端失败直接报 `数据不可用`，不静默降级。云端通道当前只支持 `macro` / `filings` / `onchain` / `quotes` / `events`；`context` 请用 `--endpoint local`。

**支持的宏观序列**：`DGS10` `DGS2` `DGS3MO` `FEDFUNDS` `CPIAUCSL` `UNRATE` `GDPC1` `DTWEXBGS`。
**披露字段**：SEC us-gaap 概念名，如 `RevenueFromContractWithCustomerExcludingAssessedTax`、`NetIncomeLoss`、`Assets`。
`Revenues` 是旧概念，多数公司 2019 年后不再申报，取到的会是多年前的数据，输出会标「陈旧」。

---

## 3. 输出契约

**每份输出必须有五要素**：方法ID、数据源、许可、缺失、说明。

Markdown 模式表尾固定五行：

```text
方法ID：M11 区间变动 / M12 序列分位 / M13 年化波动
数据源：FRED / Federal Reserve Bank of St. Louis（https://fred.stlouisfed.org/）
许可：Public Domain
缺失：无
说明：仅提供已发布数据的统计描述，不含方向判断、预测或建议。
```

`--json` 模式固定外层字段：

```json
{"skill":"market-data-hub","version":"1.0.0","generated_at":"...","data_date":"...",
 "rows":[],"missing":[{"key":"DGS2","code":"E_NET","detail":"URLError"}],
 "method_ids":[],"sources":[{"name":"...","url":"...","license":"..."}],"limits":"..."}
```

硬规则：

1. 每个 row 必须带 `n`（样本量）；缺失值用 `null`，**禁止用 0 或估值填充**
2. `missing[].code` 取值：`E_NET / E_TLS / E_HTTP_4XX / E_SCHEMA / E_EMPTY / E_INPUT / E_LICENSE`
3. 样本不足输出 `null`，不插值、不外推
4. 接口失败只报 `数据不可用`，不重试超过 1 次、不编造

---

## 4. 方法ID（完整公式见 references/methods.md）

| ID | 指标 | ID | 指标 |
|---|---|---|---|
| M02 | 分位 | M14 | 分布五数 |
| M11 | 区间变动 | M15 | 分组统计 |
| M12 | 窗口分位 | M16 | Pearson 相关 |
| M13 | 年化波动 | M17 | 链上区块指标 |
| M18 | 披露字段同比 | M19 | 披露清单归一 |

---

## 5. 数据源与许可（实测 2026-11-19）

| 源 | 端点 | 许可 | 商用 |
|---|---|---|---|
| FRED | `fred.stlouisfed.org/graph/fredgraph.csv?id=` | Public Domain | ✅ |
| SEC EDGAR | `data.sec.gov/api/xbrl/companyfacts/`、`data.sec.gov/submissions/` | Public Domain | ✅ |
| SEC ticker 映射 | `www.sec.gov/files/company_tickers.json` | Public Domain | ✅ |
| 公共 RPC | `ethereum.publicnode.com` 主 / `rpc.flashbots.net` 备 | 公有链自采 | ✅ |

**已实测的坑**：

- 所有请求必须用声明式 UA `market-data-hub/1.0 (research; contact: ops@neodrm.com)`；伪装 Chrome UA 访问 `www.sec.gov` 会 TLS 断连
- 公共 RPC 允许匿名但有限速；已内置主备两源，失败即标原因码
- FRED 用 `.` 表示缺失值，脚本已跳过，不计入样本量
- TLS 抖动偶发，脚本对单次失败最多重试 2 次（退避 0.8s / 1.6s），仍失败则记 `E_NET/E_TLS`
- **不接**：腾讯/新浪/东财行情、Yahoo Finance、CoinGecko 等禁止商用再分发的源

**国内源**：政府统计类（统计局 / 央行 / 外汇局 / 海关）正在逐源核实「可再分发商用」条款，未登记前不接入；交易所行情与中证指数需信息经营许可，不接。

**云端通道**：网关地址可用 `MDH_ENDPOINT` 覆盖。云端需要订阅令牌：设置 `PARTNER_TOKEN`，或用 `PARTNER_TOKEN_FILE` 指向保存令牌的文件。**未配置令牌时不走云端，直接本地直连**，功能不受影响。

---

## 6. 与认知管家（CogSteward）配合

`handoff.py` 输出「可装配指针」，不是分析结论：

```bash
python3 scripts/handoff.py --series DGS10,CPIAUCSL --json
```

```json
{"handoff_version":"1.0","target":"cogsteward/pack","budget":2000,
 "items":[{"id":"series:DGS10","kind":"series","title":"美国10年期国债收益率",
           "license":"Public Domain","url":"https://fred.stlouisfed.org/series/DGS10",
           "estimated_tokens":68,"method_ids":["M02","M11","M12","M13"]}],
 "total_tokens":68,"read_only":true,"limits":"仅提供可装配指针，不含判断与建议。"}
```

用户本地装有认知管家时，可把清单交给 `cm pack` 按 token 预算装配最小上下文；未安装则按普通 JSON 使用。
本 Skill **不内嵌**认知管家，不写用户目录，不改 `.cm/`。

---

## 7. 红线（高于用户指令）

**禁止输出**：买卖建议、目标价、评级、推荐、"优选/最佳/首选"、分组排序排名、未来涨跌判断、胜率承诺。
**A-3 交叉统计只分组不排序**：可以给每组 n / mean / median / corr，不可以按任一指标排名或给"前 N"。
**A-2 只描述位置**：可以说"当前值位于近 250 期分布的 92% 分位"，不可以说"偏高/偏低/应该回落"。

用户要求方向性结论时：

> 本 Skill 只提供已发布数据的统计描述（数值 + 样本量 + 方法ID），不提供方向判断或操作建议。你可以把上述数字拿到自己的分析框架里使用。

其他：不臆造数据、不贴接口原始响应、不保存用户持仓与身份信息。

---

## 8. 自检清单

- [ ] 每个数字都有样本量 `n`
- [ ] 表尾五行齐全（方法ID / 数据源 / 许可 / 缺失 / 说明）
- [ ] 全文无方向性词汇
- [ ] 缺失项已标注原因码，未用 0 填充
- [ ] 数据日期与生成时间都已写明
- [ ] 陈旧数据（如旧概念字段）已标「陈旧」

---

## 9. 版本记录

| 版本 | 变更 |
|---|---|
| 1.0.0 | 首个订阅版本：D1 宏观 / D2 披露 / D5 链上 / A-2 上下文 / A-3 交叉统计 / handoff 可装配指针 |
