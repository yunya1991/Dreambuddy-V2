# 20-数据清洗中心 — 工程索引

> **版本**: v1.1 | **更新日期**: 2026-10-01
> **定位**: 模块级工程索引（L2），对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md)

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 20 |
| 模块名称 | 数据清洗中心 |
| 核心职责 | Silver 层数据清洗管道（Bronze DataRecord → 4 步清洗 → QualityGate → SilverRecord → 19-DAL） |
| 主入口 | `data_cleaning.pipeline.DataCleaningPipeline` |
| 依赖关系 | 上游：18-数据获取中心（DataRecord）；下游：19-数据访问层（SilverRecord 写入） |
| 文档状态 | ✅ 完整（5 文档齐全） |

---

## 2. 目录地图

```
20-数据清洗中心/
├── docs/                        # 文档目录
│   ├── README.md                # 文档索引（对齐 DOC_STANDARD L3 五件套）
│   ├── ENGINEERING_INDEX.md     # 本文件
│   ├── TECHNICAL_DESIGN.md      # 技术设计
│   ├── API_SPEC.md              # 接口规格
│   ├── CHANGELOG.md             # 变更日志
│   └── archive/                 # 历史归档（DATA_CLEANING_SPEC v1.0 设计冻结）
├── data_cleaning/               # 核心代码包
│   ├── contract.py              # Silver 层契约
│   ├── pipeline.py              # DataCleaningPipeline + PipelineConfig
│   ├── errors.py                # QualityGateFailed
│   ├── adapters.py              # DataRecord ↔ CleanedDF
│   ├── dal_sink.py              # DalSink → 19-DAL
│   ├── cli.py                   # CLI 入口
│   ├── cleaners/                # 4 个清洗算子
│   │   ├── dedup_align.py       # DedupAlignCleaner
│   │   ├── outlier_filter.py    # Outlier3LFilter
│   │   ├── missing_imputer.py   # MissingImputer
│   │   └── unit_normalizer.py   # UnitNormalizer
│   └── gate/
│       └── quality_gate.py      # QualityGate
├── tests/                       # 测试套件（14+）
├── requirements.txt             # 依赖清单（空，依赖通过 18 号管理）
└── README.md                    # 用户文档
```

---

## 3. 文件清单与职责

### 3.1 契约层

| 文件 | 函数/类数 | 职责 | 关键类/函数 |
|------|----------|------|------------|
| `contract.py` | 6 | Silver 层数据契约 | `CleanAction`, `CleaningTrace`, `CleanedDF`, `AdapterMeta`, `SilverRecord` |
| `errors.py` | 1 | 异常体系 | `QualityGateFailed` |

### 3.2 清洗算子层（cleaners/）

| 文件 | 职责 | 关键类 |
|------|------|--------|
| `dedup_align.py` | 主键去重 + 频率对齐（news=FLAT 模式） | `DedupAlignCleaner` |
| `outlier_filter.py` | 三层异常过滤（3σ + IQR + ATR） | `Outlier3LFilter` |
| `missing_imputer.py` | 缺失值插补（ffill + 均值/中位数） | `MissingImputer` |
| `unit_normalizer.py` | 单位归一化（汇率/百分比转换） | `UnitNormalizer` |

### 3.3 门禁层（gate/）

| 文件 | 职责 | 关键类 |
|------|------|--------|
| `quality_gate.py` | QualityGate（复用 18 号 QualityChecker，4 类检查 + enforce 开关） | `QualityGate.validate()` |

### 3.4 适配层

| 文件 | 职责 | 关键函数 |
|------|------|----------|
| `adapters.py` | DataRecord ↔ CleanedDF 双向转换 | `records_to_cleaned_df()`, `cleaned_df_to_records()` |
| `dal_sink.py` | SilverRecord → 19-DAL 写入（fail-open） | `DalSink.write_silver()` |

### 3.5 入口层

| 文件 | 职责 | 关键入口 |
|------|------|----------|
| `pipeline.py` | DataCleaningPipeline 主入口（7 步编排） | `DataCleaningPipeline.clean()`, `PipelineConfig` |
| `cli.py` | CLI 入口 | `clean` 命令 |

---

## 4. 核心流程索引

### 4.1 Silver 清洗主流程

```
18-数据获取中心 DataRecord (Bronze)
  ↓
records_to_cleaned_df(records)                    # adapters.py
  ↓ (CleanedDF)
DedupAlignCleaner.clean(df)                       # cleaners/dedup_align.py
  ↓
Outlier3LFilter.clean(df)                         # cleaners/outlier_filter.py
  ↓
MissingImputer.clean(df)                          # cleaners/missing_imputer.py
  ↓
UnitNormalizer.clean(df)                          # cleaners/unit_normalizer.py
  ↓
cleaned_df_to_records(df) -> list[DataRecord]     # adapters.py
  ↓
QualityGate.validate(records)                     # gate/quality_gate.py
  ├─ gate_passed=True  → DalSink.write_silver()   # dal_sink.py → 19-DAL
  └─ gate_passed=False → 仅 Bronze 审计 + 告警，不入库
  ↓
return SilverRecord(df, trace, gate_passed, quality_report)
```

### 4.2 FAIL-OPEN 降级流程

```
中间 cleaner 抛异常
  ↓
记录 trace（异常算子的 input_rows/output_rows）
  ↓
跳过后续 cleaner，当前 DF 兜底进入 Gate（enforce=False）
  ↓
Gate enforce=True 抛 QualityGateFailed
  ├─ fail_open=True  → catch，返回 gate_passed=False 的 SilverRecord
  └─ fail_open=False → 向上抛异常（18 号主链路兜底）
```

---

## 5. 配置参数索引

| 配置项（PipelineConfig） | 默认值 | 说明 |
|--------------------------|--------|------|
| `target_freq` | `"1h"` | 对齐目标频率 |
| `ffill_limit` | `5` | 前向填充最大步数 |
| `z_threshold` | `3.0` | 3σ 异常阈值 |
| `iqr_coef` | `1.5` | IQR 系数 |
| `atr_k` | `3.0` | ATR 倍数 |
| `enforce_hard_block` | `True` | Gate 未通过是否抛异常 |
| `freshness_threshold` | `48h` | 时间新鲜度阈值 |
| `category` | `None` | 数据类别（news→FLAT 去重） |
| `fail_open` | `False` | 异常兜底开关 |
| `enable_unit_normalize` | `True` | 是否启用单位归一化 |

---

## 6. 测试体系

| 文件 | 测试内容 |
|------|----------|
| `test_cleaners_t2_dedup_align.py` | 去重对齐 |
| `test_cleaners_t3_outlier.py` | 三层异常过滤 |
| `test_cleaners_t4_missing.py` | 缺失值插补 |
| `test_cleaners_t5_unit.py` | 单位归一化 |
| `test_gate_t6_quality.py` | QualityGate |
| `test_gate_dirty_injection.py` | 脏数据注入 |
| `test_pipeline_t9_e2e.py` | 端到端清洗链 |
| `test_e2e_silver_chain.py` | Silver 全链路 |
| `test_adapters_t7_records_to_df.py` | Record→DF 转换 |
| `test_adapters_t8_df_to_records.py` | DF→Record 转换 |
| `test_dal_sink.py` | DalSink 写入 |
| `test_contract_and_errors.py` | 契约 + 异常 |

**运行命令**：
```bash
cd 20-数据清洗中心 && python -m pytest -q
```

---

## 7. 技术债务

| 债务项 | 严重程度 | 说明 |
|--------|----------|------|
| Gold 层校验 | 🟡 中 | Silver → Gold 的 Pandera schema 校验待完善 |

---

## 8. 快速导航

| 目标 | 路径 |
|------|------|
| 文档索引 | [README.md](./README.md) |
| 用户文档 | [README.md](../README.md) |
| 技术设计 | [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) |
| 接口规格 | [API_SPEC.md](./API_SPEC.md) |
| 变更日志 | [CHANGELOG.md](./CHANGELOG.md) |
| 历史归档 | [archive/](./archive/)（DATA_CLEANING_SPEC v1.0 设计冻结） |
| 项目文档索引 | [0-系统文档管理/INDEX.md](../../0-系统文档管理/INDEX.md) |

---

**文档版本**: v1.1
**最后更新**: 2026-10-01
