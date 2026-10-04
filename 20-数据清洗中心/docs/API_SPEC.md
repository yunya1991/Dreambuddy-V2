# 20-数据清洗中心 — 接口规格文档

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 子系统对外接口规格，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.3

---

## 1. 接口概览

### 1.1 接口类型

| 类型 | 数量 | 说明 |
|------|------|------|
| Python API | 3 | DataCleaningPipeline / QualityGate / DalSink |
| 清洗算子 | 4 | DedupAlign / Outlier3L / MissingImputer / UnitNormalizer |
| 适配器 | 2 | records_to_cleaned_df / cleaned_df_to_records |

### 1.2 接口列表

| 接口 | 类型 | 签名 | 说明 |
|------|------|------|------|
| `DataCleaningPipeline.clean` | Python | `clean(records, source, category) -> SilverRecord` | 7 步清洗主入口 |
| `QualityGate.validate` | Python | `validate(records, *, source, category, is_degraded) -> tuple[bool, list]` | 质量门禁 |
| `DalSink.write_silver` | Python | `write_silver(silver, source, category, sub_category) -> bool` | Silver → 19-DAL |
| `records_to_cleaned_df` | Python | `records_to_cleaned_df(records) -> CleanedDF` | DataRecord → DataFrame |
| `cleaned_df_to_records` | Python | `cleaned_df_to_records(df, source, category, sub_category) -> list[DataRecord]` | DataFrame → DataRecord |

---

## 2. 认证方式

| 方式 | 说明 |
|------|------|
| 无需认证 | SDK 集成，直接 import |

---

## 3. 接口详情

### 3.1 DataCleaningPipeline（主入口）

**模块**：`data_cleaning.pipeline`

#### `PipelineConfig`

```python
@dataclass
class PipelineConfig:
    target_freq: str = "1h"
    ffill_limit: int = 5
    z_threshold: float = 3.0
    iqr_coef: float = 1.5
    atr_k: float = 3.0
    enforce_hard_block: bool = True
    freshness_threshold: timedelta = timedelta(hours=48)
    allow_empty_degraded_sources: tuple = ()
    timestamp_col: str = "timestamp"
    category: Optional[str] = None
    fail_open: bool = False
    enable_unit_normalize: bool = True
```

#### `DataCleaningPipeline.__init__`

```python
def __init__(self, config: Optional[PipelineConfig] = None, **kwargs) -> None
```

#### `DataCleaningPipeline.clean`

```python
def clean(self, records: list[DataRecord], *, source: str = "", category: str = "") -> SilverRecord
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `records` | list[DataRecord] | 是 | 18 号采集的 Bronze 数据 |
| `source` | str | 是 | 数据源标识 |
| `category` | str | 是 | 数据域（macro/finance/chain/news） |

**返回**：`SilverRecord`

| 字段 | 类型 | 说明 |
|------|------|------|
| `bronze_id` | str | 关联 Bronze DataRecord 的 id |
| `df` | pd.DataFrame | 清洗后数据 |
| `trace` | CleaningTrace | 全链路清洗痕迹 |
| `gate_passed` | bool | QualityGate 是否通过 |
| `quality_report` | list | QualityIssue 列表 |
| `schema_tag` | str | schema 标签 |

**示例**：
```python
from data_cleaning.pipeline import DataCleaningPipeline, PipelineConfig

pipe = DataCleaningPipeline(PipelineConfig(fail_open=True, category="news"))
silver = pipe.clean(records, source="odaily_newsflash", category="news")
if silver.gate_passed:
    # 写入 19-DAL
    from data_cleaning.dal_sink import DalSink
    DalSink().write_silver(silver, source="odaily_newsflash", category="news", sub_category="flash")
```

### 3.2 QualityGate（质量门禁）

**模块**：`data_cleaning.gate.quality_gate`

```python
class QualityGate:
    def __init__(self, *, enforce_hard_block=True, freshness_threshold=timedelta(hours=48),
                 allow_empty_degraded_sources=None) -> None
    def validate(self, records, *, source="", category="", is_degraded=False, trace=None) -> tuple[bool, list[QualityIssue]]
```

**4 类质量检查**（复用 18 号 QualityChecker）：

| 检查项 | QualityIssueCode | 说明 |
|--------|------------------|------|
| 空结果 | `EMPTY_RESULT` | records 为空（降级源可豁免） |
| 契约无效 | `CONTRACT_INVALID` | DataRecord 字段校验失败 |
| 重复检测 | `DUPLICATE_DETECTED` | 主键重复 |
| 时间新鲜度 | `TIMESTAMP_FRESHNESS` | 数据超过 freshness_threshold |

**enforce 行为**：
- `enforce_hard_block=True`：issues 非空 → 抛 `QualityGateFailed`
- `enforce_hard_block=False`：旁路模式，只 report 不抛

### 3.3 DalSink（Silver → 19-DAL）

**模块**：`data_cleaning.dal_sink`

```python
class DalSink:
    def write_silver(self, silver: SilverRecord, *, source: str, category: str, sub_category: str) -> bool
```

将 SilverRecord 写入 19-DAL，**fail-open**：写入失败不影响主链路。

### 3.4 适配器

**模块**：`data_cleaning.adapters`

| 函数 | 签名 | 说明 |
|------|------|------|
| `records_to_cleaned_df` | `records_to_cleaned_df(records: Iterable[DataRecord]) -> CleanedDF` | DataRecord → DataFrame（按 timeseries/metrics/events 三类规范化） |
| `cleaned_df_to_records` | `cleaned_df_to_records(df, source, category, sub_category) -> list[DataRecord]` | DataFrame → DataRecord（还原） |

### 3.5 清洗算子

| 算子 | 类 | 核心参数 |
|------|-----|----------|
| 去重对齐 | `DedupAlignCleaner` | `target_freq`, `ffill_limit`, `category`（news→FLAT） |
| 异常过滤 | `Outlier3LFilter` | `z_threshold`(3σ), `iqr_coef`, `atr_k` |
| 缺失插补 | `MissingImputer` | `ffill_limit` |
| 单位归一 | `UnitNormalizer` | `enable_unit_normalize` |

---

## 4. 错误码

| 异常 | 触发场景 |
|------|----------|
| `QualityGateFailed` | QualityGate enforce=True 且 issues 非空 |

**返回值约定**：
- `gate_passed=False`：拦截，仅 Bronze 审计，不入库
- `DalSink.write_silver()` 返回 `False`：DAL 写入失败（fail-open，不阻塞）

---

## 5. 版本管理

### 5.1 版本策略

- PipelineConfig 字段新增不破坏旧调用（kwargs 覆盖）
- DataRecord 契约由 18 号维护，20 号仅消费
- SilverRecord 结构稳定，新增字段用默认值

### 5.2 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-09-30 | 初始接口规格（DataCleaningPipeline + QualityGate + DalSink + 4 算子） |

---

**文档版本**: v1.0
**最后更新**: 2026-09-30
