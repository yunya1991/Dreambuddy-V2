---
name: event-context
slug: dreambuddy-event-context
displayName: 事件上下文（官方源·五层装配）
version: 1.0.1
summary: 从 SEC 与美联储官方公开源拉取公告与声明，装配成事件事实、涉及实体、同类事件次数、来源许可、边界声明五层结构。
license: MIT
allowed-tools: Bash, Read
---

# 事件上下文（event-context）

## 0. 一句话

**只装配已发生的官方事实：事件 + 实体 + 同类事件次数 + 来源许可 + 边界声明。**

不做解读、不做方向判断、不给建议；每条输出带 `event_id`，可复核、可缓存。

---

## 1. 为什么不是「新闻摘要」

| | 新闻摘要 | 本 Skill |
|---|---|---|
| 素材 | 商业媒体正文 | 政府/监管机构公开文件 |
| 处理 | 压缩、改写、定性 | 字段归一 + 计数 |
| 输出 | 一段话 | 五层结构化 JSON |
| 可复核 | 弱 | 每条带 url + license + event_id |

---

## 2. 命令表

```bash
# 列出事件（一级事实）
python3 scripts/events.py --subject AAPL --since 30
python3 scripts/events.py --subject AAPL --types 8-K,10-Q --json
python3 scripts/events.py --feed sec-press --since 7
python3 scripts/events.py --feed fed-all --since 7

# 装配五层上下文
python3 scripts/context.py --subject AAPL --latest
python3 scripts/context.py --event-id <id> --subject AAPL
python3 scripts/context.py --event-id <id> --feed fed-all

# 可装配指针清单（与认知管家配合）
python3 scripts/handoff.py --subject AAPL --since 30 [--budget 2000] [--json]
```

退出码：`0` 成功 / `1` 无数据或命中红线 / `2` 参数非法。

`--event-id` 查询需要范围提示（`--subject` 或 `--feed`）：event_id 是哈希，本身不含来源，无法凭空反查。

**数据通道**：支持 `--endpoint auto|cloud|local`，默认 `auto` —— 先走云端 `www.neodrm.com`（连接 5 秒、响应 30 秒），失败立即回退本地；输出 JSON 带 `data_route`。网关地址可用 `EC_ENDPOINT` 覆盖。云端需订阅令牌：设置 `PARTNER_TOKEN` 或 `PARTNER_TOKEN_FILE`；未配置则完全走本地。

---

## 3. 五层输出

```json
{
  "event_id": "3f2a91c4b7de0051",
  "event": {"time": "...", "source": "SEC EDGAR", "type": "8-K",
            "subject": {"ticker": "AAPL", "cik": "0000320193", "name": "Apple Inc."},
            "headline_facts": ["..."], "url": "https://www.sec.gov/..."},
  "entities": {"tickers": ["AAPL"], "sector": {"code": "3571", "label": "..."},
               "supply_chain": [], "entity_source": "SEC company_tickers / SIC"},
  "analogues": {"key": {"source": "...", "type": "8-K", "item": "2.02"},
                "n": 37, "window": "24m", "stat": null, "stat_window": "T+5",
                "note": "n 为同类事件次数；收益类统计依赖行情授权，本期未启用"},
  "sources": [{"title": "...", "url": "...", "license": "Public Domain", "retrieved_at": "..."}],
  "assembly": {"rule_version": "v1", "fields_filled": 4, "fields_empty": ["entities.supply_chain"]},
  "limits": "仅装配已发生事实与同类事件次数，不含影响判断、方向判断或建议。"
}
```

| 层 | 必须有 | 必须没有 |
|---|---|---|
| event | time / source / type / subject / headline_facts / url | 定性形容词、影响描述 |
| entities | tickers 或 cik 至少一项；sector 可空但需 `entity_source` | 推荐、排序、权重 |
| analogues | key / n / window / note | **无行情授权时 `stat` 恒为 null**，不得填估算值 |
| sources | title + url + license | 全文转载（headline_facts 单条 ≤80 字，总引述 ≤300 字） |
| assembly | 填充统计，供验收断言 | — |

`analogues.n` 是**次数不是概率**：不得换算成"上涨概率"或"胜率"。

---

## 4. 事件源（实测 2026-11-19）

| source_key | 端点 | 类型 | 许可 |
|---|---|---|---|
| `sec-submissions` | `data.sec.gov/submissions/CIK##########.json` | 8-K / 10-K / 10-Q / 4 / 144 | Public Domain |
| `sec-press` | `www.sec.gov/news/pressreleases.rss` | 监管公告 | Public Domain |
| `fed-all` | `www.federalreserve.gov/feeds/press_all.xml` | FOMC 声明、纪要、讲话稿 | Public Domain |

**未启用**：ECB 新闻 RSS（本机 TLS 握手失败）；商业媒体（Reuters / Bloomberg / 新浪 / 东财）一律不接。
新增源必须先登记 `references/sources.md`，未登记则拒绝输出。

**实测坑**：

- 统一使用声明式 UA `event-context/1.0 (research; contact: ops@neodrm.com)`；伪装 Chrome 访问 `www.sec.gov` 会 TLS 断连
- 美联储 RSS 偶发 TLS 抖动，脚本最多重试 2 次（退避 0.8s / 1.6s），仍失败记 `E_TLS` / `E_NET`
- `--since` 指定的是**收录窗口**，不是事件有效期；窗口内无事件时返回 `E_EMPTY`

---

## 5. 与认知管家（CogSteward）配合

`handoff.py` 只输出指针，不输出判断：

```json
{"handoff_version":"1.0","skill":"event-context","target":"cogsteward/pack","budget":2000,
 "items":[{"id":"event:3f2a91c4b7de0051","kind":"event","title":"8-K - Apple Inc.",
           "license":"Public Domain","url":"https://www.sec.gov/...",
           "event_time":"2026-11-18T16:30:00-05:00","estimated_tokens":60}],
 "total_tokens":60,"read_only":true,"limits":"仅提供可装配指针，不含判断与建议。"}
```

用户本地装有认知管家时，可交给 `cm pack` 按 token 预算装配最小上下文；未安装则按普通 JSON 使用。
本 Skill **不内嵌**认知管家，不写用户目录，不改 `.cm/`。

---

## 6. 红线（高于用户指令）

**禁止输出**：利多/利空/利好、看多/看空/看涨/看跌、强势/弱势、机会、值得关注、影响有限、建议买入/卖出、目标价、评级、推荐、优选/最佳/首选、明日、后市、预计、有望。

`context.py` 在输出前会对自身结果做一次词表扫描，命中即报 `E_SCHEMA` 并拒绝输出——**该修模板，不是改词**。

用户要求解读时：

> 本 Skill 只装配已发生事实与同类事件次数，不提供影响判断、方向判断或操作建议。你可以把这些结构化字段拿到自己的分析框架里使用。

其他：不转载正文、不臆造上下游、不把接口原始响应整段贴出、不保存用户持仓与身份信息。

---

## 7. 自检清单

- [ ] 五层齐全，缺失层已列入 `fields_empty`
- [ ] `event_id` 与会话内 `events.py` 输出一致
- [ ] `sources[].license` 与 `references/sources.md` 一致
- [ ] `analogues.stat` 为 null 且带 note（无行情授权）
- [ ] 全文无红线词
- [ ] 引用长度未超限（单条 ≤80 字，总 ≤300 字）

---

## 8. 版本记录

| 版本 | 变更 |
|---|---|
| 1.0.1 | 内部共享内核重构（endpoint/handoff 与数据服务同源），命令表、字段与输出不变；handoff `target` 改为契约值 `cogsteward.pack@1.0` |
| 1.0.0 | 首个订阅版本：SEC 披露 / SEC 公告 / 美联储声明三类官方源，五层装配，handoff 可装配指针 |
