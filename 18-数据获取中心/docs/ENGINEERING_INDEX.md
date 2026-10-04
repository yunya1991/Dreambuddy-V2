# 18-数据获取中心 — 工程索引

> **版本**: v1.1 | **更新日期**: 2026-10-01
> **定位**: 模块级工程索引（L2），对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md)

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 18 |
| 模块名称 | 数据获取中心 |
| 核心职责 | 全项目唯一数据入口与信息收口层（万能爬虫 + SDK 采集），统一 DataRecord 契约 |
| 主入口 | `data_center.core.dispatcher.DataCenter` / `data_center.cli.app` |
| 依赖关系 | 上游：外部数据源（FRED/CCXT/Etherscan/RSSHub 等）；下游：20-数据清洗中心、19-数据访问层、各交易子系统 |
| 文档状态 | ✅ 完整（5 文档齐全） |

---

## 2. 目录地图

```
18-数据获取中心/
├── docs/                        # 文档目录
│   ├── README.md                # 文档索引（对齐 DOC_STANDARD L3 五件套）
│   ├── ENGINEERING_INDEX.md     # 本文件
│   ├── TECHNICAL_DESIGN.md      # 技术设计（双轨制架构）
│   ├── API_SPEC.md              # 接口规格
│   ├── CHANGELOG.md             # 变更日志
│   └── archive/                 # 历史归档
│       ├── IMPLEMENTATION_PLAN.md       # 实现计划（M1-M5，已完成归档）
│       └── TECHNICAL_DESIGN_LEGACY_v3.0.md  # 旧版技术设计
├── data_center/                 # 核心代码包
│   ├── __init__.py              # 导出 DataCenter, DataRecord
│   ├── cli/app.py               # Typer CLI 入口（fetch/list/crawl/schedule/monitor）
│   ├── core/                    # 统一契约·注册表·分发·异常
│   │   ├── contract.py          # DataRecord 数据契约 + validate_record
│   │   ├── registry.py          # Registry 注册表 (category,source)->collector
│   │   ├── dispatcher.py        # DataCenter 主入口 + 33 collector 注册
│   │   └── errors.py            # ContractError/SourceUnavailableError
│   ├── collectors/              # SDK 轨采集器（6 域 33 个）
│   │   ├── _base.py             # BaseCollector 抽象
│   │   ├── _proxy.py            # 代理
│   │   ├── macro/               # FRED 宏观
│   │   ├── finance/             # yfinance/CFTC/ETF/Sosovalue
│   │   ├── chain/               # CCXT/Etherscan/DeFiLlama/Coinglass 等
│   │   ├── coin/                # CoinGecko/CoinMarketCap
│   │   ├── news/                # RSSHub/Tavily/GDELT/Odaily 等
│   │   └── bdsm/                # Pump/Aave/Hype/Uniswap 原生爬虫
│   ├── crawler/                 # 爬虫轨（Scrapy + Playwright + Scrapling）
│   ├── compat/                  # 老代码兼容层（data/flow/market_compat）
│   ├── monitoring/              # 监控三件套（metrics/quality/alerting）
│   ├── processing/              # Silver/Gold 处理层
│   └── storage/                 # 去重缓存 + sqlite 落库
│       ├── cache.py             # dedupe_key / stable_id / dedupe
│       └── sink_sqlite.py       # SqliteSink（records/metrics/quality/alerts 表）
├── config/                      # 配置文件
│   ├── .env                     # API Key（.gitignore）
│   ├── .env.example             # API Key 模板
│   ├── sources.yaml             # 33 数据源开关 + 默认序列/标的
│   └── sites.yaml               # 爬虫站点配置
├── launchd/                     # macOS 定时任务 plist
│   ├── com.dreambuddy.datacenter.plist          # 实际运行服务（PYTHONPATH 含 20-数据清洗中心）
│   ├── com.dreambuddy.data-center-scheduler.plist  # 安装模板（有注释，PYTHONPATH 正确）
│   └── archive/                 # 归档的重复/旧版 plist
├── tests/                       # 测试套件（39+ 集成测试，含 verify_e2e_pipeline_blockbeats.py）
├── logs/                        # 运行时日志（.gitignore）
├── data_center_scheduler.py     # 调度器入口
├── dataview_html_parser.py      # Dataview HTML 解析器（Playwright 渲染→DataRecord，被 theblockbeats_dataview 引用）
├── pyproject.toml               # Python 项目配置
├── requirements.txt             # 依赖清单
├── data_center.db               # 运行时 SQLite 数据库（.gitignore，514MB）
└── README.md                    # 用户文档
```

**代码统计**：`data_center/` 共 ~60 个 Python 文件，33 个 collector。

---

## 3. 文件清单与职责

### 3.1 核心层（core/）

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `core/contract.py` | 4 | DataRecord 统一数据契约 + 校验 | `DataRecord`, `validate_record()`, `CATEGORIES` |
| `core/registry.py` | 4 | (category,source)->collector 注册表 | `Registry.register()`, `Registry.get()`, `Registry.list()` |
| `core/dispatcher.py` | 5 | DataCenter 主入口 + 33 collector 注册 + Silver 中间件 | `DataCenter.fetch()`, `DataCenter.list_collectors()`, `_register_defaults()` |
| `core/errors.py` | 3 | 异常体系 | `ContractError`, `SourceUnavailableError` |

### 3.2 采集器层（collectors/）

| 子目录 | collector 数 | 职责 | 代表 collector |
|--------|-------------|------|---------------|
| `macro/` | 1 | 宏观经济数据 | `FredCollector`（FRED API） |
| `finance/` | 4 | 金融市场数据 | `YFinanceCollector`, `CftcCotCollector`, `EtfFlowCollector` |
| `chain/` | 14 | 链上/加密市场数据 | `CcxtCollector`, `EtherscanCollector`, `CoinglassCollector`, `DeribitOptionsCollector` |
| `coin/` | 2 | 币种基本面 | `CoinGeckoCollector`, `CoinMarketCapCollector` |
| `news/` | 10 | 新闻/RSS | `RsshubCollector`, `TavilyCollector`, `OdailyNewsflashCollector` |
| `bdsm/` | 6 | BDSM 原生项目爬虫 | `PumpNativeCollector`, `AaveNativeCollector` |

**BaseCollector 契约**（`collectors/_base.py`）：所有 collector 继承 `BaseCollector`，设置 `source`/`category` 类属性，实现 `fetch(params) -> list[DataRecord]`，可选覆写 `is_available()`。

### 3.3 存储层（storage/）

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `storage/cache.py` | 3 | 类别感知去重 | `stable_id()`, `dedupe_key()`, `dedupe()` |
| `storage/sink_sqlite.py` | ~10 | sqlite 落库（4 表） | `SqliteSink.write()`, `query_records()`, `latest_records()`, `source_health()` |

### 3.4 监控层（monitoring/）

| 文件 | 职责 | 关键类 |
|------|------|--------|
| `monitoring/metrics.py` | 调用统计 | `InvocationMetric`, `MetricsStore` |
| `monitoring/quality.py` | 数据质量检查 | `QualityChecker`, `QualityIssue` |
| `monitoring/alerting.py` | 告警 | `Alert`, `AlertLevel`, `AlertManager` |

### 3.5 入口层

| 文件 | 职责 | 关键入口 |
|------|------|----------|
| `cli/app.py` | Typer CLI | `fetch()`, `list()`, `crawl()`, `schedule()`, `monitor status/health/alerts` |
| `data_center_scheduler.py` | 定时调度器 | `CollectionTask` |

---

## 4. 核心流程索引

### 4.1 采集主流程（SDK 轨）

```
CLI fetch / DataCenter.fetch(category, source=...)
  ↓
dispatcher.DataCenter.fetch()                    # core/dispatcher.py
  ↓
registry.get(category, source) -> Collector 类    # core/registry.py
  ↓
Collector(config).fetch(params) -> list[DataRecord]  # collectors/<域>/<源>_collector.py
  ↓
validate_record(rec)                              # core/contract.py
  ↓
Silver 中间件（EN_SILVER=true）                    # data_cleaning.pipeline
  ├─ QualityGate 未通过 → 拦截返回 []
  └─ 通过 → cleaned_df_to_records → DalSink.write_silver
  ↓
监控埋点（metrics + quality + alerts）             # monitoring/
  ↓
return list[DataRecord]
```

### 4.2 去重落库流程

```
list[DataRecord]
  ↓
dedupe(records)                                   # storage/cache.py
  └─ dedupe_key = sha256(source|category|sub_category|stable_id)
  ↓
SqliteSink.write(records)                         # storage/sink_sqlite.py
  └─ INSERT OR IGNORE INTO records (dedupe_key UNIQUE)
```

---

## 5. 配置参数索引

| 文件 | 作用 | 关键参数 |
|------|------|----------|
| `config/sources.yaml` | 33 数据源开关 + 默认序列/标的 | `<域>.<源>.enabled`, `default_series`, `default_symbols` |
| `config/sites.yaml` | 爬虫站点配置 | 站点 URL + 选择器 |
| `config/.env` | API Key | `FRED_API_KEY`, `OKX_API_KEY` 等 |
| 环境变量 | Silver 中间件 | `EN_SILVER`(默认true), `SILVER_FAIL_OPEN`(默认true), `SILVER_FRESHNESS_HOURS`(默认48) |

**加载优先级**：
```
config/.env (API Key)
    ↓
config/sources.yaml (数据源开关)
    ↓
代码默认值（BaseCollector.config）
```

---

## 6. 测试体系

| 目录 | 测试内容 |
|------|----------|
| `tests/chain/` | CCXT/DeFiLlama/Etherscan/BDSM collector |
| `tests/coin/` | CoinGecko collector |
| `tests/finance/` | yfinance collector |
| `tests/macro/` | FRED/Fed/Semiconductor collector |
| `tests/news/` | RSSHub/Tavily/GDELT/Odaily collector |
| `tests/crawler/` | Scrapy/Playwright/Scrapling 引擎 |
| `tests/monitoring/` | metrics/quality/alerting |
| `tests/processing/` | Silver/Gold 处理层 |
| `tests/test_dispatcher.py` | DataCenter 路由 |
| `tests/test_contract.py` | DataRecord 契约校验 |

**运行命令**：
```bash
cd 18-数据获取中心 && python -m pytest -q
```

---

## 7. 技术债务

| 债务项 | 严重程度 | 说明 |
|--------|----------|------|
| M4 老调用方迁移 | 🟡 中 | 9-基本面分析/12-三屏趋势系统的散落采集代码尚未 @deprecated 并切到 18 号 |
| 爬虫轨完善度 | 🟡 中 | Scrapy + Playwright 骨架已建，站点覆盖待扩充 |

---

## 8. 快速导航

| 目标 | 路径 |
|------|------|
| 用户文档 | [README.md](../README.md) |
| 技术设计 | [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) |
| 接口规格 | [API_SPEC.md](./API_SPEC.md) |
| 变更日志 | [CHANGELOG.md](./CHANGELOG.md) |
| 项目文档索引 | [0-系统文档管理/INDEX.md](../../0-系统文档管理/INDEX.md) |

---

**文档版本**: v1.1
**最后更新**: 2026-10-01
