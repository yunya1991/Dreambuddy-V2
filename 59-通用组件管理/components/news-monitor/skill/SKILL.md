---
name: news-monitor
slug: news-monitor
display_name: 新闻监控（云端）
description: "云端新闻监控通用组件：只读拉取 24h 热点影响力榜、情绪与主题指标、关键词检索与明细分页（仅本地令牌）；数据直连 www.neodrm.com 云端快照，不落地原始正文。"
summary: 云端新闻监控：热点榜、情绪/主题指标、关键词检索；只读、直连、不抓正文。
tags: [新闻监控, 热点榜, 情绪指标, 主题簇, 云端只读, neodrm]
version: 0.2.0
license: MIT
allowed-tools: Read, Bash
---

# 新闻监控（news-monitor）

把 `https://www.neodrm.com/dashboard/news` 的新闻监控能力抽成 59 域通用组件，经云端快照只读调用。

## 能力

| 动作 | 安全级 | 作用 |
|---|---|---|
| `hot` | read | 24h 热点新闻榜 Top N（主题 / 情绪 / 影响力 / 来源链接） |
| `metrics` | read | 情绪与影响力核心指标 + 主题簇分布 |
| `search` | read | 按关键词检索新闻（24h / 7d / 30d 窗口） |
| `list` | read | 云端去重新闻明细：分页、主题/情绪/关键词过滤（仅本地令牌） |
| `snapshot` | read | 完整云端快照（指标 + 热点 + 主题簇 + 时序） |

## 用法

```bash
# 今日热点 Top10
python3 skill/scripts/news.py hot --limit 10

# 情绪与主题指标
python3 skill/scripts/news.py metrics

# 关键词检索（24h 窗口）
python3 skill/scripts/news.py search --keyword BTC --window 24h

# 云端明细：24h 全部去重新闻，按影响力排序分页
python3 skill/scripts/news.py list --window 24h --limit 50 --offset 0

# 明细过滤：加密监管主题 + 影响力 >= 60
python3 skill/scripts/news.py list --window 7d --topic crypto_reg --min-importance 60

# 完整快照（时序窗口 7 天）
python3 skill/scripts/news.py snapshot --days 7
```

经统一 CLI：

```bash
dreambuddy run news-monitor hot --limit 10 --endpoint cloud
dreambuddy run news-monitor search --keyword 美联储 --window 24h --endpoint cloud
dreambuddy run news-monitor list --window 24h --limit 50 --offset 0 --endpoint cloud
```

`list` 需要本地令牌（仅本机 600 文件，不随包分发）：

```bash
mkdir -p ~/.local/share/dreambuddy
printf 'NEWS_LOCAL_TOKEN=%s\n' '<云端生成的随机令牌>' > ~/.local/share/dreambuddy/news.env
chmod 600 ~/.local/share/dreambuddy/news.env
```

云端服务环境需设置同名令牌 `DREAMBUDDY_NEWS_LOCAL_TOKEN`；未配置或错误时接口返回 403。

## 数据通道

| 项 | 值 |
|---|---|
| 快照 | `GET {NEWS_ENDPOINT}/api/fundamental/news/snapshot[?days=N]` |
| 检索 | `POST {NEWS_ENDPOINT}/api/data/query`，`{"message":"<关键词> 最近<窗口>新闻"}` |
| 明细 | `GET {NEWS_ENDPOINT}/api/news/items`，需 `X-Dreambuddy-Local-Token`（仅本地） |
| 默认域名 | `https://www.neodrm.com`，可用环境变量 `NEWS_ENDPOINT` 覆盖 |
| 通道 | 仅 `auto` / `cloud`；`local` 返回 `E_INPUT`，不伪造本地数据 |

## 输出

`output_contract: data.v1`：`skill` / `version` / `generated_at` / `data_date` / `rows` / `missing` / `method_ids` / `sources` / `limits` / `data_route=cloud`。

- 热点与检索行带 `event_id`；指标行带 `n`（样本量）。
- 云端失败写入 `missing[{key,code,detail}]`，退出码非 0，**不静默降级**。

## 边界（硬约束）

- 只读：不写云端、不写本地库、不抓取新闻全文正文；
- `list` 仅对本地开放：必须携带本地令牌，云端未配置令牌时一律 403；
- 不绕过来源站点限制，不再分发原始正文；对外只输出标题、主题、情绪、影响力与来源链接；
- 榜单口径为近 24h / 有限窗口，明细库最多近 30 天，不构成投资建议。
