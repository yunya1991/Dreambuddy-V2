# 数据获取中心 — 技术设计文档

> **定位：** 子系统技术架构设计，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.2
> **版本：** v1.0 | **更新日期：** 2026-08-24
> **系统类型：** 全局数据采集与信息收口层（万能爬虫 + 信息搜集工具）
> **关联文档：** [README.md](../README.md)、[API_SPEC.md](./API_SPEC.md)、[0-系统文档管理/2-文档地图/SYSTEM_MAP.md](../../0-系统文档管理/2-文档地图/SYSTEM_MAP.md)
>
> **设计基线：** 本设计基于「双轨制」方案——SDK 适配轨（薄封装成熟库覆盖 API 类数据源）+ 爬虫轨（Scrapy + Playwright 覆盖无 API 的官网/新闻站），统一 `DataRecord` 契约，CLI（Typer）+ Python 库双形态交付。目标是把分散在 `9-基本面分析`（`flow_collector.py` / `data_collector.py`）、`12-三屏趋势系统`（`market_data.py` / `tavily_data.py`）的采集逻辑统一收口。

---

## 目录

- [1. 概述](#1-概述)
- [2. 架构设计](#2-架构设计)
- [3. 核心算法](#3-核心算法)
- [4. 数据流](#4-数据流)
- [5. 接口设计](#5-接口设计)
- [6. 状态管理](#6-状态管理)
- [7. 配置管理](#7-配置管理)
- [8. 错误处理](#8-错误处理)
- [9. 扩展性设计](#9-扩展性设计)
- [10. 迁移路径与里程碑](#10-迁移路径与里程碑)
- [变更记录](#变更记录)

---

## 1. 概述

### 1.1 系统定位

18-数据获取中心是 DreamBuddy-V2 的**唯一数据入口与信息收口层**。当前项目的数据采集能力散落在多个子系统：

| 现有采集代码 | 位置 | 覆盖数据源 |
|---|---|---|
| `flow_collector.py` | `9-基本面分析/ops/nanoclaw/core_task1/flow/scripts/` | FRED 宏观、Yahoo Finance、Etherscan 链上、Glassnode、巨鲸地址 |
| `data_collector.py` | `9-基本面分析/` | Tavily 新闻搜索 + 去重摘要 |
| `market_data.py` / `tavily_data.py` | `12-三屏趋势系统/data/` | 行情、Tavily |

这些代码各自手写 HTTP、各自定义输出结构、各自维护 API Key 与降级逻辑，导致：采集逻辑重复、契约不统一、维护成本高、新数据源接入困难。本系统作为**统一收口重构**：以成熟开源库薄封装替代手写 HTTP，以统一 `DataRecord` 契约替代各自结构，老代码逐步标记 deprecated 并迁移。

### 1.2 设计目标

| 目标 | 描述 |
|---|---|
| **万能爬虫** | 既覆盖 API 类数据源（宏观/金融/链上/新闻 RSS），也覆盖无 API 的政策官网/新闻站（Scrapy + Playwright） |
| **尽量用成熟库** | 优先薄封装 AKShare / fredapi / yfinance / CCXT / Etherscan / web3.py / RSSHub / feedparser / newspaper3k / Scrapy / Playwright，不重复造轮子 |
| **统一契约** | 所有采集器输出统一 `DataRecord`，便于跨子系统消费与去重缓存 |
| **双形态交付** | CLI（类 Claude Code，`data-center` 命令）+ Python 库（供 10/11/12/14 等子系统 import） |
| **收口重构** | 迁移废弃散落采集代码，18 号成为唯一数据入口 |
| **可扩展** | 新增数据源 = 新增一个 collector 文件 + 注册，不动核心 |

### 1.3 业务边界

| 职责 | 归属 |
|---|---|
| 宏观政策/金融/链上/新闻/网页数据采集 | 本模块（`collectors/` + `crawler/`） |
| 统一数据契约 `DataRecord` | 本模块（`core/contract.py`） |
| 去重、缓存、落库 | 本模块（`storage/`） |
| CLI 命令与 Python 库 API | 本模块（`cli/` + `core/dispatcher.py`） |
| 交易决策、信号生成 | 各交易子系统（消费本模块数据） |
| 持仓管理、离场执行 | 13/16 等子系统 |

---

## 2. 架构设计

### 2.1 双轨制分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  对外形态：CLI (Typer)  +  Python 库 (DataCenter)             │
├─────────────────────────────────────────────────────────────┤
│  core/  统一契约 · 注册表 · 分发 · 异常                        │
│   contract.py  registry.py  dispatcher.py  errors.py          │
├──────────────────┬──────────────────────────────────────────┤
│  SDK 适配轨       │  爬虫轨                                   │
│  collectors/      │  crawler/                                 │
│  ┌────────────┐   │  ┌─────────────────────┐                 │
│  │ macro      │   │  │ scrapy_project/     │ Scrapy 骨架       │
│  │ finance    │   │  │  spiders/pipelines/ │ 通用 Spider       │
│  │ chain      │   │  │ playwright_fallback│ JS 站兜底         │
│  │ news       │   │  │ adapters.py        │ 结果→DataRecord  │
│  └────────────┘   │  └─────────────────────┘                 │
│  薄封装成熟库      │  配置驱动 (sites.yaml)                     │
├──────────────────┴──────────────────────────────────────────┤
│  storage/  去重 + 缓存 + 落库 (sqlite / parquet)              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
18-数据获取中心/
├── core/                  # 统一契约与调度核心
│   ├── contract.py        # DataRecord 统一数据契约
│   ├── registry.py        # 采集器注册表 + 路由
│   ├── dispatcher.py      # 域 -> 采集器分发
│   └── errors.py          # 统一异常体系
├── collectors/            # SDK适配轨（薄封装成熟库）
│   ├── _base.py           # BaseCollector 抽象
│   ├── macro/             # AKShare + fredapi + yfinance
│   ├── finance/           # AKShare + tushare + yfinance
│   ├── chain/             # CCXT + etherscan + web3 + glassnode(可选)
│   └── news/              # RSSHub + feedparser + newspaper3k + GDELT + tavily
├── crawler/               # 爬虫轨（万能爬虫）
│   ├── scrapy_project/    # Scrapy 骨架（spiders/pipelines/middlewares）
│   ├── playwright_fallback.py
│   └── adapters.py        # 爬虫结果 -> DataRecord
├── storage/               # 落库与缓存
│   ├── cache.py           # 去重 + 缓存
│   ├── sink_sqlite.py     # 默认 sqlite 落库
│   └── sink_parquet.py    # 时序列 parquet
├── cli/
│   └── app.py             # data-center fetch/crawl/list/schedule
├── config/                # 数据源配置 / API Key / sites.yaml
├── docs/                  # 本目录
├── tests/
├── README.md
└── requirements.txt
```

### 2.3 模块关系

- `cli/app.py` 与外部 Python 调用方都只依赖 `core/dispatcher.py`（统一入口 `DataCenter`）。
- `dispatcher` 通过 `registry` 路由到具体 collector 或 crawler，两者都产出 `DataRecord`。
- `DataRecord` 统一经 `storage/cache.py` 去重后落 `sink_sqlite` / `sink_parquet`。
- collector 与 crawler 互不依赖，仅通过 `DataRecord` 契约解耦。

---

## 3. 核心算法

### 3.1 DataRecord 统一契约

与现有 `data_collector.py` 的 `metrics.core / metrics.breakdown / events / timeseries / timestamp` 契约对齐，保证迁移平滑：

```python
@dataclass
class DataRecord:
    source: str            # "fred"|"akshare"|"ccxt"|"etherscan"|"rsshub"|"scrapy"...
    category: str          # "macro"|"finance"|"chain"|"news"|"web"
    sub_category: str      # "cpi"|"ohlcv"|"whale"|"rss"...
    timestamp: str         # ISO8601 采集时间
    metrics: dict          # 扁平 number/string（core/breakdown）
    events: list[dict]     # 事件流（新闻/巨鲸/政策）
    timeseries: list[dict]  # 时序列（行情/指标）
    raw: dict               # 原始 payload（溯源）
    schema_version: str = "1.0"
```

**约束**：`metrics` 仅存 number/string，不嵌套对象（沿用现有约束）；`raw` 必须保留上游原始响应以便溯源。

### 3.2 双轨分发逻辑

```text
dispatcher.fetch(category, **params)
  ├─ if category in {"macro","finance","chain","news"}:
  │     route = registry.get_sdk_collector(category, source)
  │     records = route.fetch(params)          # SDK 轨：薄封装成熟库
  └─ elif category == "web":
        records = crawler.run(config=params["config"])  # 爬虫轨：Scrapy/Playwright
  → records.map(normalize -> DataRecord) → storage.dedupe_and_sink(records)
```

### 3.3 去重算法

复用现有 URL+标题去重思路，扩展为基于 `source + key_hash` 的通用去重：

```python
def dedupe_key(rec: DataRecord) -> str:
    base = f"{rec.source}|{rec.category}|{rec.sub_category}|{stable_id(rec)}"
    return hashlib.sha256(base.encode()).hexdigest()
# stable_id: 新闻取 url/标题前50字符；行情取 symbol+interval+ts；链上取 tx_hash
```

### 3.4 降级策略

沿用 `flow_collector.py` 的「无 Key 降级」思路：API Key 缺失时，付费源（Glassnode/Tavily）自动降级为免费源或返回空记录并打日志，不抛异常中断。

---

## 4. 数据流

### 4.1 完整链路

```
数据源 (FRED/AKShare/CCXT/Etherscan/RSSHub/政策官网...)
   │
   ▼
[采集] SDK轨(collectors) ──┐         ┌── 爬虫轨(crawler: Scrapy+Playwright)
   │                         │         │
   ▼                         ▼         ▼
[归一] 统一为 DataRecord (core/contract.py)
   │
   ▼
[去重+缓存] storage/cache.py  (source+key_hash)
   │
   ▼
[落库] sqlite(事件/快照)  +  parquet(时序列)
   │
   ▼
[输出] CLI 命令结果  /  Python 库 DataCenter.fetch() 返回 list[DataRecord]
   │
   ▼
[消费] 10/11/12/14 等子系统 import 调用
```

### 4.2 输入与输出

- **输入**：CLI 参数 / Python 库调用参数 + `config/` 下的数据源配置与 API Key。
- **输出**：`list[DataRecord]`（内存） + 落库记录（持久化） + CLI 终端表格/JSON。

---

## 5. 接口设计

### 5.1 Python 库接口（DataCenter）

```python
from data_center import DataCenter

dc = DataCenter()                       # 自动加载 config/.env
dc.fetch("macro", series="CPI", source="fred")          # → list[DataRecord]
dc.fetch("chain", symbol="BTC", exchange="okx", kind="ticker")
dc.fetch("news", topic="crypto", sources=["rsshub", "gdelt"])
dc.fetch("web", config="config/sites.yaml")            # 爬虫轨
dc.list_collectors()                                     # 已注册采集器
```

### 5.2 BaseCollector 接口（SDK 轨扩展点）

```python
class BaseCollector(ABC):
    source: str
    category: str
    @abstractmethod
    def fetch(self, params: dict) -> list[DataRecord]: ...
    def is_available(self) -> bool: ...   # API Key/依赖是否就绪
```

### 5.3 CLI 命令（Typer）

```
data-center fetch macro   --series CPI --source fred
data-center fetch chain   --symbol BTC --exchange okx --kind ticker
data-center fetch news    --topic crypto --sources rsshub,gdelt
data-center crawl         --config sites.yaml        # 爬虫轨
data-center list          collectors                  # 已注册采集器
data-center schedule     --cron "0 * * * *" --task "fetch macro --series CPI"
```

详细 CLI 参数与返回格式见 [API_SPEC.md](./API_SPEC.md)（待补）。

---

## 6. 状态管理

| 状态 | 存储 | 用途 |
|---|---|---|
| 采集状态 | `data/collect_state.json` | 记录每个 source 最后成功采集时间，供增量拉取与调度 |
| 去重缓存 | sqlite `dedupe` 表 | 跨运行去重，避免重复落库 |
| 调度状态 | `data/scheduler_state.json` | cron 任务上次运行/下次运行/失败计数 |
| 原始溯源 | `raw` 字段 + 可选 raw 落盘 | 异常排查与重算 |

状态机（单次采集）：`PENDING → FETCHING → NORMALIZING → DEDUPING → SINKING → DONE`，任一步异常转 `FAILED` 并记错误类型。

---

## 7. 配置管理

### 7.1 配置文件

- `config/.env`：API Key（`FRED_API_KEY` / `TUSHARE_TOKEN` / `TAVILY_API_KEY` / `ETHERSCAN_API_KEY` / `GLASSNODE_API_KEY` 等），复用现有环境变量命名。
- `config/sources.yaml`：SDK 轨各源的开关、默认参数、限流阈值。
- `config/sites.yaml`：爬虫轨目标站点（URL、选择器、频率、是否需 JS 渲染）。

### 7.2 加载优先级

```
config/.env (API Key)
    ↓ 覆盖
config/sources.yaml (源参数)
    ↓ 覆盖
CLI/调用参数 (最高优先级)
    ↓ 覆盖
代码默认值
```

---

## 8. 错误处理

### 8.1 统一异常体系（`core/errors.py`）

| 异常 | 触发场景 | 处理策略 |
|---|---|---|
| `SourceUnavailableError` | API Key 缺失 / 源下线 | 降级到备用源或返回空记录 + WARN 日志 |
| `RateLimitError` | 上游 429 / 配额超限 | 指数退避重试 N 次，仍失败则跳过并记状态 |
| `ParseError` | 上游响应结构变更 | 抛出 + 保留 raw 供排查，不污染落库 |
| `NetworkError` | 超时 / 连接失败 | 重试 3 次后转 FAILED 状态 |

### 8.2 降级与限流

- 无 Key 降级：付费源缺 Key 时自动跳过或切免费源（沿用 `flow_collector.py`）。
- 限流：每个 source 可配 `qps`，collector 内部用令牌桶控制。
- 重试：指数退避，最大 3 次，可配置。

---

## 9. 扩展性设计

### 9.1 新增 SDK 轨 collector

1. 在 `collectors/<domain>/` 新增 `xxx_collector.py`，继承 `BaseCollector`，实现 `fetch`。
2. 在 `registry.py` 注册（或用装饰器自动注册）。
3. 补单测（mock 上游）+ 契约一致性测试。
4. 即可通过 `data-center fetch <domain> --source xxx` 或 `DataCenter.fetch` 调用。

### 9.2 新增爬虫站点

1. 在 `config/sites.yaml` 增加站点条目（URL、选择器、频率、`js_render: bool`）。
2. Scrapy 通用 Spider 按 YAML 驱动，无需写新 Spider；JS 站自动走 `playwright_fallback`。
3. 爬虫结果经 `crawler/adapters.py` 转 `DataRecord(category="web")`。

### 9.3 新增数据域

在 `collectors/` 新增子目录 + 在 `core/contract.py` 的 `category` 枚举注册，dispatcher 自动路由。

---

## 10. 迁移路径与里程碑

| 阶段 | 内容 | 收口对象 |
|---|---|---|
| M1 | 骨架 + `DataRecord` 契约 + CLI 壳 + 1 个 macro collector（迁移 FRED 逻辑） | `flow_collector.py` 的 FRED 部分 |
| M2 | 补全 finance/chain/news SDK 轨 | `flow_collector.py` 的 yahoo/etherscan/glassnode + `data_collector.py` 的 tavily |
| M3 | 爬虫轨（Scrapy + Playwright）+ 配置驱动 | 政策官网/新闻站长尾源 |
| M4 | 老调用方（9 号/12 号）切换到 `data_center` import，老代码标记 `@deprecated` | 全部散落采集代码 |

**选型清单**（薄封装目标库）：

| 域 | 库 | 用途 |
|---|---|---|
| macro | fredapi / AKShare / yfinance | FRED 50万+宏观序列 / 中国宏观 / DXY 美债 |
| finance | AKShare / tushare / yfinance | A股/港股/美股行情+财务 |
| chain | CCXT / etherscan + web3.py / glassnode(可选) / Bitquery(可选 MCP) | 交易所行情 / ETH 链上 / 链上宏观 / DEX+巨鲸 |
| news | RSSHub / feedparser + newspaper3k / GDELT / Tavily(保留) | 万物 RSS / 正文提取 / 全球事件 / AI 搜索 |
| crawler | Scrapy / Playwright | 结构化大规模爬虫 / JS 站兜底 |

---

## 变更记录

## [v1.0] - 2026-08-24

### 新增
- **变更内容**: 初版技术设计文档。确立「双轨制」架构（SDK 适配轨 + 爬虫轨）、统一 `DataRecord` 契约、CLI+Python 库双形态、四阶段迁移收口路径。
- **影响范围**: 新建 `18-数据获取中心/docs/TECHNICAL_DESIGN.md`；后续 M1-M4 将逐步收口 `9-基本面分析` 与 `12-三屏趋势系统` 的散落采集代码。
- **验证方式**: 文档评审通过后，按 M1 落地骨架与首个 macro collector 验证契约可行性。
- **回滚策略**: 文档阶段无回滚风险；M1 落地后若契约不合，回退 `DataRecord` 定义并重设计。
