# 数据获取中心 — 实现计划

> **定位：** 基于 [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) v1.0 的分阶段落地计划
> **版本：** v1.5（M1-M5 全部完成） | **更新日期：** 2026-08-24
> **方法论：** TDD（Red-Green-Refactor）+ 代码驱动 + 成熟库薄封装
> **关联：** [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) §10 迁移路径

---

## 0. 里程碑总览

| 里程碑 | 内容 | 收口对象 | 依赖 | 状态 |
|---|---|---|---|---|
| **M1** | 骨架 + `DataRecord` 契约 + CLI 壳 + FRED macro collector | `flow_collector.py` 的 FRED 部分 | 无 | ✅ 完成 |
| **M2** | 补全 finance/chain/news SDK 轨 | flow_collector 的 yahoo/etherscan/glassnode + data_collector 的 tavily | M1 | ✅ 完成 |
| **M3** | 爬虫轨（Scrapy + Playwright）+ 配置驱动 | 政策官网/新闻站长尾源 | M1 | ✅ 完成 |
| **M4** | 老调用方切换 import + 老代码 `@deprecated` | 全部散落采集代码 | M1-M3 | ✅ 完成 |
| **M5** | 监控告警（调用统计 + 数据质量 + 告警通道 + 埋点） | DataCenter 全局可观测性 | M4 | ✅ 完成 |

**执行原则**：每个里程碑独立可验证；每组件 TDD（先写失败测试→实现→重构）；不引入未在计划中声明的依赖；M1 完成并评审通过后再进入 M2。

---

## M1 详细任务拆解（TDD 排序，文件级）

### 目标
跑通端到端：`data-center fetch macro --series FEDFUNDS --source fred` → 返回 `DataRecord` 并落 sqlite，契约可被其他子系统 import 消费。

### 依赖（M1 仅需最小集，后续阶段按需追加）
```
typer              # CLI 框架
fredapi            # FRED 成熟库（替代手写 HTTP）
python-dotenv      # .env 加载
pytest
pytest-mock        # mock 上游
```

### 任务清单（按 TDD 执行顺序）

#### T1. 项目骨架
- 建目录：`core/ collectors/macro/ storage/ cli/ config/ tests/ tests/macro/ docs/`
- 写 `requirements.txt`（M1 最小集，附注释分组标注各阶段库）
- 写 `config/.env.example`（`FRED_API_KEY=`）
- 写 `18-数据获取中心/__init__.py` 与各子包 `__init__.py`
- **验证**：`python -c "import core, collectors, storage, cli"` 不报错

#### T2. DataRecord 契约（TDD）
- **Red**：`tests/test_contract.py`
  - 构造 `DataRecord`，断言字段齐全、`schema_version="1.0"`
  - 断言 `metrics` 仅含 number/string（拒绝嵌套 dict/list → 抛 `ContractError`）
  - 断言 `timestamp` 为 ISO8601
- **Green**：`core/contract.py` 实现 `DataRecord` dataclass + `validate()` 函数
- **Refactor**：抽 `ContractError` 到 `core/errors.py`
- **验证**：`pytest tests/test_contract.py` 全绿

#### T3. 异常体系
- `core/errors.py`：`DataCenterError`（基类）/ `ContractError` / `SourceUnavailableError` / `RateLimitError` / `ParseError` / `NetworkError`
- `tests/test_errors.py`：异常继承关系与可捕获性
- **验证**：`pytest tests/test_errors.py`

#### T4. BaseCollector 抽象（TDD）
- **Red**：`tests/test_base_collector.py`
  - 子类化 `BaseCollector`，未实现 `fetch` 抛 `NotImplementedError`
  - `is_available()` 默认逻辑（依赖/Key 检查）
- **Green**：`collectors/_base.py`（`source`/`category` 属性 + 抽象 `fetch` + `is_available`）
- **验证**：`pytest tests/test_base_collector.py`

#### T5. FRED macro collector（TDD，迁移核心）
- **迁移来源**：`9-基本面分析/ops/nanoclaw/core_task1/flow/scripts/flow_collector.py` 的 `fetch_fred_series / fetch_fred_fedfunds / fetch_fred_rrp / fetch_fred_10y_real_yield / fetch_fred_t10yie`（现手写 HTTP 调 `api.stlouisfed.org`，无 Key 时返回 None 降级）
- **Red**：`tests/macro/test_fred_collector.py`
  - mock `fredapi.Fred` 返回固定 observations
  - 断言 `FredCollector.fetch(series="FEDFUNDS")` 返回 `list[DataRecord]`，`source="fred"`、`category="macro"`、`sub_category="FEDFUNDS"`、`metrics.value` 为 float、`timeseries` 含 date/value
  - mock 无 Key 场景 → `is_available()` 为 False，`fetch` 返回空列表 + 不抛异常（无 Key 降级）
  - mock 429 → 抛 `RateLimitError`
- **Green**：`collectors/macro/fred_collector.py` 用 `fredapi.Fred` 薄封装，产出 `DataRecord`，保留 `raw`
- **Refactor**：series→sub_category 映射表（FEDFUNDS/RRPONTSYD/DFII10/T10YIE）
- **验证**：`pytest tests/macro/test_fred_collector.py`

#### T6. Registry + Dispatcher（TDD）
- **Red**：`tests/test_dispatcher.py`
  - 注册 `FredCollector` 后，`DataCenter.fetch("macro", series="FEDFUNDS", source="fred")` 路由到它
  - 未注册 source → 抛 `SourceUnavailableError`
  - `category="web"` → 路由到 crawler（M1 用 stub 返回空，标记 TODO_M3）
- **Green**：`core/registry.py`（注册表 + 装饰器 `@register`）+ `core/dispatcher.py`（`DataCenter` 类）
- **验证**：`pytest tests/test_dispatcher.py`

#### T7. Storage 去重 + sqlite 落库（TDD）
- **Red**：`tests/test_cache.py`
  - 两条相同 `source+key` 的 `DataRecord` → 去重后只落一条
  - 不同 sub_category 不互相去重
- **Red**：`tests/test_sink_sqlite.py` → 落库后可读回，字段一致
- **Green**：`storage/cache.py`（`dedupe_key` = `sha256(source|category|sub_category|stable_id)`）+ `storage/sink_sqlite.py`（表 `records`，schema 对齐 DataRecord）
- **验证**：`pytest tests/test_cache.py tests/test_sink_sqlite.py`

#### T8. CLI 壳（TDD）
- **Red**：`tests/test_cli.py`（用 `typer.testing.CliRunner`）
  - `data-center fetch macro --series FEDFUNDS --source fred` → exit 0，stdout 含 value
  - `data-center list collectors` → 输出含 `fred/macro`
- **Green**：`cli/app.py`（Typer app：`fetch` / `list` / `crawl`(stub) / `schedule`(stub)）
- **验证**：`pytest tests/test_cli.py` + 手动 `python -m cli.app fetch macro --series FEDFUNDS --source fred`

#### T9. DataCenter 库入口
- `core/__init__.py` 暴露 `DataCenter`、`DataRecord`
- 根包 `18-数据获取中心/__init__.py` 或可安装包名 `data_center`：`from data_center import DataCenter`
- **验证**：`python -c "from data_center import DataCenter, DataRecord"`

#### T10. 集成测试 + 配置
- `tests/test_integration_m1.py`：端到端 `DataCenter().fetch("macro", series="FEDFUNDS")`（mock fredapi）→ DataRecord → 去重 → sqlite
- `config/sources.yaml`：fred 源开关 + 默认 series 列表
- `README.md`：M1 快速上手（安装/配置 Key/运行命令）
- **验证**：`pytest -q` 全绿；`data-center fetch macro --series FEDFUNDS --source fred`（真实 Key）返回数值

### M1 验收标准
- [ ] 全部 T1-T10 测试绿
- [ ] `data-center fetch macro --series FEDFUNDS --source fred` 端到端可用
- [ ] `from data_center import DataCenter, DataRecord` 可被外部 import
- [ ] `flow_collector.py` 的 FRED 函数在此有等价实现（无 Key 降级、4 个 series 覆盖）
- [ ] 文档：README + 本计划完成度勾选

---

## M2 大纲（补全 SDK 轨）

| 任务 | 迁移来源 | 成熟库 |
|---|---|---|
| `finance/akshare_collector.py` | flow_collector 的 yahoo 部分 | AKShare + yfinance |
| `chain/ccxt_collector.py` | flow_collector 交易所行情 | CCXT |
| `chain/etherscan_collector.py` | flow_collector 的 Etherscan + 巨鲸地址 | etherscan + web3.py |
| `chain/glassnode_collector.py`(可选) | flow_collector 的 Glassnode | glassnode-client / 直连 API（无 Key 降级） |
| `news/rsshub_collector.py` + `news/feedparser_collector.py` | data_collector 的 tavily | RSSHub + feedparser + newspaper3k |
| `news/tavily_collector.py`(保留 AI 搜索) | data_collector | tavily-python |
| `news/gdelt_collector.py` | 新增 | GDELT 2.1 API |

**依赖追加**：`akshare yfinance ccxt etherscan-python web3 feedparser newspaper3k tavily-python`
**验收**：每 collector 单测（mock 上游）+ 契约一致性测试；`flow_collector` 与 `data_collector` 全部逻辑有等价实现。

---

## M3 大纲（爬虫轨）

| 任务 | 说明 |
|---|---|
| `crawler/scrapy_project/` 骨架 | Scrapy 项目初始化 + 通用 Spider（YAML 驱动选择器） |
| `crawler/playwright_fallback.py` | JS 站点兜底渲染 |
| `crawler/adapters.py` | Scrapy Item → `DataRecord(category="web")` |
| `config/sites.yaml` | 目标站点（URL/选择器/频率/js_render） |
| CLI `crawl` 命令实现 | 替换 M1 stub |

**依赖追加**：`scrapy playwright itemadapter`
**验收**：爬取一个真实政策官网（如央行公告页）→ DataRecord 落库；JS 站走 Playwright。

---

## M4 大纲（收口切换）— ✅ 完成

| 任务 | 说明 | 状态 |
|---|---|---|
| `compat/market_compat.py` | 老市场数据兼容层：`fetch_candles` / `resample_candles` 基于 ccxt 薄封装，inst_id/bar 格式自动转换 | ✅ |
| `compat/data_compat.py` | 老 data_collector 兼容层：`fetch_tavily_news` 用 TavilyCollector 替换；`DataCollector` / `generate_timeseries` 转发老实现 + DeprecationWarning | ✅ |
| `compat/flow_compat.py` | 老 flow_collector 兼容层：`fetch_yahoo_symbol` / `fetch_fred_series` 用新 collector；`run_full_collection` 转发 + 警告 | ✅ |
| `9-基本面分析` 调用方切换 | `ml_trade_service_v2.py` 改为 `from data_center.compat import DataCollector, generate_timeseries` | ✅ |
| `12-三屏趋势系统` 调用方切换 | `live/strategy_runner.py` 改为 import data_center.compat | ✅ |
| flow 调用方切换 | `ops/nanoclaw/core_task1/flow/scripts/run_flow_analysis.py` 改为 import data_center.compat | ✅ |
| 老代码 `@deprecated` | `flow_collector.py` / `data_collector.py` / `market_data.py` 顶部加 `@deprecated` 标记 + `DeprecationWarning` | ✅ |
| 全局回归 | `tests/test_m4_regression.py` 验证调用方切换 + 老模块废弃标记；全量 129 测试绿 | ✅ |

**验收**：
- [x] 散落采集代码全部标记 deprecated 且无活跃调用方直接 import
- [x] 调用方均通过 `data_center.compat` 兼容层访问
- [x] 全量测试 129 passed，子系统回归无异常

---

## M5 大纲（监控告警）

> 目标：为 DataCenter 建立全局可观测性，覆盖调用统计、数据质量、告警通知三个维度，
> 通过非侵入式埋点注入 DataCenter，不影响现有 129 项测试。

### 架构分层

```
┌───────────────────────────────────────────────────────┐
│                DataCenter.fetch() 入口                │
│            (before / after / error hooks)             │
└────────────┬──────────────────┬───────────────────────┘
             ▼                  ▼
    ┌────────────────┐  ┌──────────────────┐
    │ MetricsStore   │  │ QualityChecker   │
    │ (调用统计)     │  │ (数据质量检查)    │
    └───────┬────────┘  └────────┬─────────┘
            ▼                    ▼
    ┌────────────────────────────────────────┐
    │          AlertRouter (告警路由)         │
    │ LogChannel / FileChannel / LarkChannel │
    └────────────────────────────────────────┘
```

### 任务清单（按 TDD 顺序）

#### M5-T1 MetricsStore — 调用统计 TDD
- 文件：`data_center/monitoring/metrics.py` + `tests/monitoring/test_metrics.py`
- 数据模型：`InvocationMetric`（invocation_id, ts, source, category, status, duration_ms, records_count, error_type, error_msg）
- MetricsStore API：`record(metric)` / `query(source?, category?, window_sec?)` / `summary()`
- Red 断言：
  - 记录成功调用：duration_ms > 0, records_count ≥ 0, status="ok"
  - 记录异常调用：error_type 非空, status="error"
  - `summary()` 返回每个 (source, category) 的 total/ok_count/error_count/avg_duration_ms

#### M5-T2 QualityChecker — 数据质量 TDD
- 文件：`data_center/monitoring/quality.py` + `tests/monitoring/test_quality.py`
- 检查项（每一项返回 QualityIssue）：
  - `EMPTY_RESULT`：返回空列表且无正当降级理由
  - `CONTRACT_INVALID`：DataRecord.validate() 抛 ContractError
  - `DUPLICATE_DETECTED`：同一批 DataRecord 中 dedupe_key 重复
  - `TIMESTAMP_FRESHNESS`：最老记录 timestamp 超过 freshness_threshold
- Red 断言：
  - 空列表触发 EMPTY_RESULT
  - validate() 失败的记录触发 CONTRACT_INVALID
  - 相同 dedupe_key 触发 DUPLICATE_DETECTED
  - `check_all(records)` 返回 List[QualityIssue]

#### M5-T3 告警通道抽象 + 日志通道 TDD
- 文件：`data_center/monitoring/alerting.py` + `tests/monitoring/test_alerting.py`
- AlertChannel 抽象：`emit(alert: Alert)` 接口（Alert: level/title/message/tags/ts）
- 内置通道：
  - `LogAlertChannel`：走 Python logging，ERROR 以上打 stderr 红色
  - `FileAlertChannel`：NDJSON 追加到指定文件
  - `LarkAlertChannel`（stub，占位可扩展）：webhook URL，发送卡片
- AlertRouter：按 alert.level 路由到一个或多个 Channel（INFO→Log, ERROR→Log+File+Lark）
- Red 断言：
  - LogChannel emit 后 logging 有对应记录
  - FileChannel emit 后文件追加 NDJSON 行

#### M5-T4 DataCenter 埋点注入 + 集成测试
- 修改：`data_center/core/dispatcher.py` + `data_center/monitoring/__init__.py`
- DataCenter 新增可选参数：`monitoring: MonitoringBundle | None = None`
  - 默认 `default_monitoring_bundle()`：开监控但关闭 Lark（需 webhook 才启用）
  - 内部在 `fetch()` 前后 + except 中埋点：
    - before → start timer
    - after 正常 → MetricsStore.record(ok) + QualityChecker.check_all() → 触发告警
    - except → MetricsStore.record(error) → 触发告警
- 新增：`data_center/monitoring/__init__.py` 导出 `MonitoringBundle`, `default_monitoring_bundle`
- 集成测试：`tests/test_integration_m5.py`
  - mock FredCollector 成功 → 断言有 metric 记录 + 无质量告警
  - mock FredCollector 抛 Exception → 断言 metric.error_count=1 + 触发 ERROR 告警
  - mock FredCollector 返回 Contract 错误的 record → 断言 CONTRACT_INVALID issue

#### M5-T5 CLI 监控命令 + status/health
- 修改：`data_center/cli/app.py`
- 新增命令：
  - `data-center monitor status`：打印 MetricsStore.summary() 表格
  - `data-center monitor health`：跑一次所有内置 collector 采样，打印是否健康
  - `data-center monitor alerts --last N`：读 FileChannel 输出文件，打印最近 N 条
- 验收：CLI 三个命令 exit 0，stdout 有输出

#### M5-T6 全量回归 + 更新文档
- 129 原有测试必须全绿 + M5 新增测试全绿
- IMPLEMENTATION_PLAN.md M5 标记完成，变更记录追加 v1.5

### 依赖
**无新增外部依赖**：全部用 Python 标准库（logging、json、time、dataclasses、threading.Lock），避免引入 prometheus_client/opentelemetry 等重型依赖。

### 验收标准
- [x] M5-T1~T6 测试全绿：原有 129 + M5 新增 35 = 164 全绿
- [x] DataCenter 默认开启监控（`monitoring=None` 自动走 `default_monitoring_bundle()`）
- [x] 调用方无需改动代码即可获得调用统计 / 数据质量 / 异常告警
- [x] CLI `monitor status` / `monitor health` / `monitor alerts` exit 0，输出可读
- [x] IMPLEMENTATION_PLAN.md M5 完成度全勾
- [x] 无新增外部依赖（仅标准库 logging/json/dataclasses/threading）

---

## 风险与对策

| 风险 | 对策 |
|---|---|
| 成熟库 API 变更（fredapi/akshare） | `raw` 字段保留原始响应；契约测试锁定 DataRecord 形态 |
| API Key 缺失阻断开发 | 全部 collector 支持 mock 测试；无 Key 降级为返回空 + 日志 |
| 爬虫轨与 SDK 轨异步模型冲突 | Scrapy 仅在 `category="web"` 路由触发，与 SDK 轨解耦；M3 再处理 |
| 收口切换影响线上子系统 | M4 分系统切换 + 回归测试，不一次性切换 |

---

## 变更记录

## [v1.5] - 2026-08-24
- **新增**: M5 监控告警全套落地：MetricsStore（9 tests）+ QualityChecker（10 tests）+ AlertChannel 体系（11 tests）+ DataCenter 非侵入埋点 + CLI monitor 子命令（status/health/alerts）。
- **验证**: 原有 129 + M5 新增 35 = 164 测试全绿；三 monitor 命令 exit 0；`from data_center import DataCenter` 无需改动代码即获得监控。
- **影响范围**: 新增 `data_center/monitoring/`（metrics/quality/alerting/__init__.py + `MonitoringBundle`），修改 `data_center/core/dispatcher.py`（埋点）与 `data_center/cli/app.py`（monitor 子命令组）。
- **回滚策略**: monitoring 完全可选，移除 monitoring 参数或降级 dispatcher 版本即可退回无监控形态。

## [v1.4] - 2026-08-24
- **新增**: M4 收口切换全部完成。新增 `compat/` 兼容层（market/data/flow），三个老调用方切换到 `data_center.compat`，老模块标记 `@deprecated` + `DeprecationWarning`。
- **验证**: `tests/test_m4_regression.py` 4 项断言全绿；全量 129 测试通过。
- **影响范围**: `18-数据获取中心/data_center/compat/`、`9-基本面分析/ml_trade_service_v2.py`、`12-三屏趋势系统/live/strategy_runner.py`、`9-基本面分析/ops/.../run_flow_analysis.py`、老模块 `flow_collector.py` / `data_collector.py` / `market_data.py`。
- **回滚策略**: 兼容层透明转发，回滚仅需还原调用方 import 行。

## [v1.0] - 2026-08-24
- **新增**: 初版实现计划。M1 详细 TDD 任务拆解（T1-T10，文件级），M2-M4 大纲，验收标准与风险对策。
- **影响范围**: `18-数据获取中心/docs/IMPLEMENTATION_PLAN.md`
- **验证方式**: M1 落地后按验收标准逐项勾选。
- **回滚策略**: 每里程碑独立 git 提交，可按里程碑回退。
