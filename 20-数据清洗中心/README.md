# 20-数据清洗中心

> Silver 层数据清洗管道 — Bronze DataRecord → 去重/异常/缺失/单位归一化 → QualityGate → SilverRecord

---

## 概述

20-数据清洗中心是 DreamBuddy-V2 的 **Silver 层数据清洗管道**，位于 18-数据获取中心（Bronze 层）和 19-数据访问层（Gold 层）之间。将 18 号采集的原始 `DataRecord` 经过去重对齐、异常值过滤、缺失值插补、单位归一化四步清洗，通过 QualityGate 质量门禁后产出 `SilverRecord`，写入 19-DAL 供交易子系统消费。

**设计原则**：
- **FAIL-OPEN 铁律**：清洗链异常 → 记录 trace，兜底进入 Gate（enforce=False），不阻塞 18 号采集主链路
- **硬门禁**：QualityGate 未通过 → 拦截 Bronze 数据，仅保留审计，不进入交易热路径
- **可追溯**：CleaningTrace 记录每步算子的输入/输出/裁剪/插补行数，支持脏数据事后复盘

---

## 目录结构

```
20-数据清洗中心/
├── docs/                        # 文档目录
│   ├── README.md                # 文档索引（对齐 DOC_STANDARD L3 五件套）
│   ├── ENGINEERING_INDEX.md     # 工程索引
│   ├── TECHNICAL_DESIGN.md      # 技术设计
│   ├── API_SPEC.md              # 接口规格
│   ├── CHANGELOG.md             # 变更日志
│   └── archive/                 # 历史归档（DATA_CLEANING_SPEC v1.0 设计冻结）
├── data_cleaning/               # 核心代码包
│   ├── contract.py              # Silver 层契约（CleanAction/CleaningTrace/CleanedDF/SilverRecord）
│   ├── pipeline.py              # DataCleaningPipeline 主入口（7 步编排）
│   ├── errors.py                # QualityGateFailed 异常
│   ├── adapters.py              # DataRecord ↔ CleanedDF 双向转换
│   ├── dal_sink.py              # DalSink（Silver → 19-DAL 写入）
│   ├── cli.py                   # CLI 入口
│   ├── cleaners/                # 4 个清洗算子
│   │   ├── dedup_align.py       # 去重对齐（DedupAlignCleaner）
│   │   ├── outlier_filter.py    # 异常值过滤（Outlier3LFilter：3σ+IQR+ATR）
│   │   ├── missing_imputer.py   # 缺失值插补（MissingImputer：ffill+均值）
│   │   └── unit_normalizer.py   # 单位归一化（UnitNormalizer：汇率/百分比）
│   └── gate/                    # 质量门禁
│       └── quality_gate.py      # QualityGate（复用 18 号 QualityChecker）
├── tests/                       # 测试套件（14+）
├── requirements.txt
└── README.md                    # 本文件
```

---

## 快速开始

### 1. 环境要求

- Python 3.9+
- 依赖：`pip install -r requirements.txt`（pandas 等）

### 2. 运行

```python
from data_cleaning.pipeline import DataCleaningPipeline, PipelineConfig
from datetime import timedelta

pipe = DataCleaningPipeline(PipelineConfig(
    target_freq="1h",
    z_threshold=3.0,
    iqr_coef=1.5,
    enforce_hard_block=True,
    fail_open=True,
    freshness_threshold=timedelta(hours=48),
    category="news",  # news → DedupAlign FLAT 模式
))

silver = pipe.clean(records, source="fred", category="macro")
# silver.gate_passed: bool  — QualityGate 是否通过
# silver.df: pd.DataFrame  — 清洗后数据
# silver.trace: CleaningTrace — 全链路痕迹
```

---

## 核心功能

| 功能 | 说明 | 入口 |
|------|------|------|
| 7 步清洗链 | 去重→异常→缺失→单位→还原→门禁→产出 | `DataCleaningPipeline.clean()` |
| 去重对齐 | 主键去重 + 频率对齐（news=FLAT） | `DedupAlignCleaner` |
| 三层异常过滤 | 3σ + IQR + ATR 联合过滤 | `Outlier3LFilter` |
| 缺失值插补 | ffill + 均值/中位数 | `MissingImputer` |
| 单位归一化 | 汇率/百分比转换 | `UnitNormalizer` |
| 质量门禁 | 4 类检查（空/契约/重复/新鲜度）+ enforce 开关 | `QualityGate.validate()` |
| Silver → DAL | 清洗结果写入 19-DAL | `DalSink.write_silver()` |

---

## 配置说明

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

---

## 测试

```bash
cd 20-数据清洗中心
python -m pytest -q
```

测试覆盖：4 个算子 + 端到端清洗链 + QualityGate 脏数据注入 + DalSink + adapters 双向转换。

---

## 相关文档

- [工程索引](./docs/ENGINEERING_INDEX.md) — 文件级索引
- [技术设计](./docs/TECHNICAL_DESIGN.md) — Silver 层架构设计
- [接口规格](./docs/API_SPEC.md) — API 文档
- [变更日志](./docs/CHANGELOG.md) — 版本历史
- [项目文档索引](../0-系统文档管理/INDEX.md) — 全项目导航

---

**维护者**: DreamBuddy v2
