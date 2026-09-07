# 18-数据获取中心

DataBuddy 的**唯一数据入口与信息收口层**——万能爬虫 + 信息搜集工具。统一 `DataRecord` 契约，CLI + Python 库双形态，逐步收口 `9-基本面分析`/`12-三屏趋势系统` 的散落采集代码。

> 设计文档：[docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md) ｜ 实现计划：[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)

## 变更日志

### 2026-08-29: Odaily 星球日报快讯采集器

- **新增**: `collectors/news/odaily_newsflash.py` — OdailyNewsflashCollector(BaseCollector)
  - source=`odaily_newsflash`, category=`news`, 14 关键词 8 类 event_type, 5 类 attention_type
  - 三端点：`/newsflash/page` + `/newsflash/checkHasNew` + `/hotWord/list`（host=web-api.odaily.news）
  - 7 扁平 metrics: `od_source_id`/`od_policy_sentiment_0_1`/`od_event_type`/`od_attention_type`/`od_is_important`/`od_decay_hl_hrs`/`od_title_hash`
  - FAIL-OPEN: Session Timeout/Exception→[]，SentimentEngine ImportError→sentiment=0.5
  - 增量去重：`checkHasNew` lastId 三态（首屏=0/无新=空/有新=新批次）
- **修改**: `core/dispatcher.py` — register("news","odaily_newsflash",OdailyNewsflashCollector)
- **修改**: `config/sources.yaml` — `odaily_newsflash: enabled: true`
- **修改**: `scheduler.py` — CollectionTask(interval_sec=14400=4hr, route=latest)
- **测试**: `tests/news/test_odaily_collector.py` — 5 TC GREEN（真 HTTP 20 条 + 增量三态 + FAIL-OPEN）
- **质量**: B7 四门禁全 PASS（DUPLICATE=0/SCHEMA=0/IMPORT_FAIL=0/MISSING=0，20条∈[15,25]）

## 当前状态：M1（已完成）

- ✅ `DataRecord` 统一契约（`core/contract.py`）+ 校验
- ✅ 异常体系（`core/errors.py`）
- ✅ `BaseCollector` 抽象（`collectors/_base.py`）
- ✅ FRED macro collector（`collectors/macro/fred_collector.py`，迁移自 `flow_collector.py` 四序列）
- ✅ Registry + Dispatcher（`core/registry.py`、`core/dispatcher.py`）
- ✅ 去重 + sqlite 落库（`storage/cache.py`、`storage/sink_sqlite.py`）
- ✅ CLI 壳（`cli/app.py`：`fetch`/`list`/`crawl`(stub)/`schedule`(stub)）
- ✅ `from data_center import DataCenter, DataRecord`
- ✅ `.env` 自动加载 + 端到端集成测试（39 项全绿）

## 安装

```bash
cd 18-数据获取中心
pip install -r requirements.txt
```

## 配置

```bash
cp config/.env.example config/.env
# 编辑 config/.env，填入 FRED_API_KEY（https://fred.stlouisfed.org/docs/api/api_key.html）
```

## 使用

### CLI

```bash
# 采集 FRED 联邦基金利率
python -m data_center.cli.app fetch macro --series FEDFUNDS --source fred

# 列出已注册采集器
python -m data_center.cli.app list collectors
```

### Python 库

```python
from data_center import DataCenter, DataRecord

dc = DataCenter()  # 自动加载 config/.env
recs = dc.fetch("macro", series="FEDFUNDS", source="fred")
# recs: list[DataRecord]，rec.metrics["value"] 为最新值

# 落库（去重）
from data_center.storage.sink_sqlite import SqliteSink
sink = SqliteSink("data.db")
sink.write(recs)
```

## 测试

```bash
cd 18-数据获取中心
python -m pytest -q
```

## 后续里程碑

| 里程碑 | 内容 |
|---|---|
| M2 | 补全 finance/chain/news SDK 轨（AKShare/CCXT/Etherscan/RSSHub…） |
| M3 | 爬虫轨（Scrapy + Playwright）+ 配置驱动 |
| M4 | 老调用方切换 import + 老代码 `@deprecated` |
