# 18-数据获取中心 — 接口规格文档

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 子系统对外接口规格，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.3

---

## 1. 接口概览

### 1.1 接口类型

| 类型 | 数量 | 说明 |
|------|------|------|
| Python API | 3 | DataCenter / Registry / SqliteSink |
| CLI 命令 | 5+ | Typer CLI（fetch/list/crawl/schedule/monitor） |
| 扩展点 | 1 | BaseCollector 抽象（新增数据源） |

### 1.2 接口列表

| 接口 | 类型 | 签名 | 说明 |
|------|------|------|------|
| `DataCenter.fetch` | Python | `fetch(category: str, **params) -> list[DataRecord]` | 统一采集入口 |
| `DataCenter.list_collectors` | Python | `list_collectors() -> list[tuple[str,str]]` | 列出已注册采集器 |
| `SqliteSink.write` | Python | `write(records: list[DataRecord]) -> int` | 去重落库 |
| `data-center fetch` | CLI | `fetch <category> --source <src> [--series/--symbol/--topic]` | 命令行采集 |
| `data-center list` | CLI | `list collectors` | 列出采集器 |
| `data-center monitor` | CLI | `monitor status/health/alerts` | 监控状态 |

---

## 2. 认证方式

| 方式 | 说明 |
|------|------|
| API Key（环境变量） | 通过 `config/.env` 加载，如 `FRED_API_KEY`、`OKX_API_KEY` |
| 无需认证 | 部分公开数据源（RSSHub、GDELT、FearGreed）无需 Key |

---

## 3. 接口详情

### 3.1 DataCenter（Python 库主入口）

**模块**：`data_center.core.dispatcher`

#### `DataCenter.__init__`

```python
def __init__(
    self,
    config: dict | None = None,
    registry: Registry | None = None,
    env_path: str = _DEFAULT_ENV,
    monitoring: MonitoringBundle | None = None,
)
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `config` | dict | 否 | `{}` | 传递给 collector 的配置 |
| `registry` | Registry | 否 | `default_registry` | 自定义注册表 |
| `env_path` | str | 否 | `config/.env` | .env 文件路径 |
| `monitoring` | MonitoringBundle | 否 | 默认 bundle | 监控三件套注入 |

#### `DataCenter.fetch`

```python
def fetch(self, category: str, **params) -> list[DataRecord]
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `category` | str | 是 | 数据域：`macro`/`finance`/`chain`/`news`/`web`/`coin`/`protocol`/`bdsm` |
| `source` | str | 是（web 除外） | 数据源，如 `fred`/`ccxt`/`etherscan` |
| `series` | str | 否 | 序列 ID（macro 用，如 `FEDFUNDS`） |
| `symbol` | str | 否 | 交易对/标的（chain/finance 用） |
| `topic` | str | 否 | 主题（news 用） |
| `config` | str | 否 | 爬虫配置文件路径（web 用） |

**返回**：`list[DataRecord]`

**DataRecord 结构**（`data_center.core.contract`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | str | 数据源标识 |
| `category` | str | 数据域（CATEGORIES 之一） |
| `sub_category` | str | 子类别 |
| `timestamp` | str | ISO8601 采集时间 |
| `metrics` | dict | 扁平 number/string（禁止嵌套） |
| `events` | list[dict] | 事件流 |
| `timeseries` | list[dict] | 时序列 |
| `raw` | dict | 原始 payload |
| `schema_version` | str | 默认 `"1.0"` |

**示例**：
```python
from data_center import DataCenter, DataRecord

dc = DataCenter()
recs = dc.fetch("macro", series="FEDFUNDS", source="fred")
# recs[0].metrics["value"] 为最新联邦基金利率
```

#### `DataCenter.list_collectors`

```python
def list_collectors(self) -> list[tuple[str, str]]
```

返回所有已注册的 `(category, source)` 列表。

### 3.2 Registry（注册表）

**模块**：`data_center.core.registry`

| 方法 | 签名 | 说明 |
|------|------|------|
| `register` | `register(category, source, cls) -> None` | 注册 collector 类 |
| `get` | `get(category, source) -> type[BaseCollector]` | 获取 collector 类（未注册抛 SourceUnavailableError） |
| `list` | `list() -> list[tuple[str,str]]` | 列出所有注册项 |

### 3.3 SqliteSink（落库）

**模块**：`data_center.storage.sink_sqlite`

| 方法 | 签名 | 说明 |
|------|------|------|
| `write` | `write(records: list[DataRecord]) -> int` | 去重落库，返回写入行数 |
| `query_records` | `query_records(source=None, category=None, since=None) -> list[DataRecord]` | 按条件查询 |
| `latest_records` | `latest_records(source, category, limit=10) -> list[DataRecord]` | 最新 N 条 |
| `source_health` | `source_health() -> dict` | 各源最近采集状态 |

### 3.4 BaseCollector（扩展点）

**模块**：`data_center.collectors._base`

新增数据源需继承此类：

```python
class MyCollector(BaseCollector):
    source = "my_source"
    category = "macro"

    def fetch(self, params: dict) -> list[DataRecord]:
        # 实现采集逻辑
        ...
```

注册到 dispatcher：
```python
from data_center.core.dispatcher import _register_defaults
# 或直接：
default_registry.register("macro", "my_source", MyCollector)
```

### 3.5 CLI 命令

**入口**：`python -m data_center.cli.app` 或 `data-center`

| 命令 | 用法 | 说明 |
|------|------|------|
| `fetch` | `data-center fetch macro --series FEDFUNDS --source fred` | 采集数据，输出 JSON |
| `list` | `data-center list collectors` | 列出所有已注册采集器 |
| `crawl` | `data-center crawl --config sites.yaml` | 爬虫轨（M3） |
| `schedule` | `data-center schedule --cron "0 * * * *"` | 定时调度 |
| `monitor status` | `data-center monitor status` | 调用统计汇总 |
| `monitor health` | `data-center monitor health` | 所有 collector 健康采样 |
| `monitor alerts` | `data-center monitor alerts --last 20` | 最近告警 |

---

## 4. 错误码

| 异常 | 触发场景 |
|------|----------|
| `ContractError` | DataRecord 校验失败（source/category 为空、category 非法、timestamp 非 ISO8601、metrics 嵌套） |
| `SourceUnavailableError` | fetch 未指定 source，或 (category,source) 未注册 |

---

## 5. 版本管理

### 5.1 版本策略

- DataRecord `schema_version` 字段标识契约版本
- 新增 category 不破坏旧版本（CATEGORIES 元组追加）
- Collector 接口稳定：`fetch(params) -> list[DataRecord]`

### 5.2 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-09-30 | 初始接口规格（33 collector + DataCenter + SqliteSink + CLI） |

---

**文档版本**: v1.0
**最后更新**: 2026-09-30
