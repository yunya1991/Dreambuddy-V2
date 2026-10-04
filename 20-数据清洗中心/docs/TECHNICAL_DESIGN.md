# 20-数据清洗中心 — 技术设计文档

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 子系统技术架构设计，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.2

---

## 1. 概述

### 1.1 系统定位

20-数据清洗中心是 DreamBuddy-V2 的 **Silver 层数据清洗管道**，位于 Bronze（18-数据获取中心）和 Gold（19-数据访问层）之间。将原始 DataRecord 经过标准化清洗 + QualityGate 质量门禁，产出可入库的 SilverRecord。

### 1.2 设计目标

| 目标 | 描述 |
|------|------|
| **FAIL-OPEN 铁律** | 清洗链异常不阻塞 18 号采集主链路，降级为 gate_passed=False |
| **硬门禁** | QualityGate 未通过 → 拦截 Bronze 数据，仅审计不入库 |
| **可追溯** | CleaningTrace 记录每步算子的输入/输出/裁剪/插补行数 |
| **类别感知** | news 走 FLAT 去重（保留每条 sub_category 语义），macro/finance/chain 走频率对齐 |

### 1.3 业务边界

| 职责 | 归属 |
|------|------|
| DataRecord → DataFrame 转换 | 本模块（adapters.py） |
| 去重/异常/缺失/单位清洗 | 本模块（cleaners/） |
| 质量门禁 | 本模块（gate/quality_gate.py，复用 18 号 QualityChecker） |
| Silver → 19-DAL 写入 | 本模块（dal_sink.py） |
| 数据采集 | 18-数据获取中心（上游） |
| Gold 层存储/查询 | 19-数据访问层（下游） |

---

## 2. 架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  入口层：DataCleaningPipeline.clean()                          │
├─────────────────────────────────────────────────────────────┤
│  适配层：adapters.py  (DataRecord ↔ CleanedDF)                │
├─────────────────────────────────────────────────────────────┤
│  算子层：cleaners/  (4 个清洗算子链式执行)                      │
│    DedupAlign → Outlier3L → MissingImputer → UnitNormalizer   │
├─────────────────────────────────────────────────────────────┤
│  门禁层：gate/quality_gate.py  (QualityGate)                 │
├─────────────────────────────────────────────────────────────┤
│  出口层：dal_sink.py  (DalSink.write_silver → 19-DAL)         │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 模块关系

```
18-数据获取中心 (Bronze DataRecord)
       ↓
DataCleaningPipeline.clean()
       ├─ records_to_cleaned_df()
       ├─ DedupAlignCleaner
       ├─ Outlier3LFilter
       ├─ MissingImputer
       ├─ UnitNormalizer
       ├─ cleaned_df_to_records()
       └─ QualityGate.validate()
              ├─ gate_passed=True  → DalSink.write_silver() → 19-DAL
              └─ gate_passed=False → Bronze 审计 + 告警（不入库）
       ↓
return SilverRecord
```

---

## 3. 核心算法

### 3.1 三层异常过滤（Outlier3LFilter）

**三层联合**：
1. **3σ 原则**：|x - μ| > z_threshold · σ → 标记异常
2. **IQR 方法**：x < Q1 - iqr_coef·IQR 或 x > Q3 + iqr_coef·IQR → 标记异常
3. **ATR 动态阈值**：|x - prev| > atr_k · ATR → 标记异常

**处理方式**：clip 到边界值（不删除行，保留时间序列连续性）。

### 3.2 类别感知去重（DedupAlignCleaner）

- **macro/finance/chain**：按 (src, cat, sub, asset, timestamp) 主键去重 + resample 到 target_freq
- **news**：FLAT 模式，不跨 sub_category resample，保留每条新闻的语义完整性

### 3.3 QualityGate 质量门禁

复用 18 号 `QualityChecker` 的 4 类检查：
1. EMPTY_RESULT — 空结果（降级源可豁免）
2. CONTRACT_INVALID — DataRecord 契约无效
3. DUPLICATE_DETECTED — 主键重复
4. TIMESTAMP_FRESHNESS — 数据新鲜度超阈值

---

## 4. 数据流

### 4.1 主数据流

```
18 号 DataRecord (Bronze)
  ↓
records_to_cleaned_df → CleanedDF(df, records=[AdapterMeta])
  ↓
DedupAlignCleaner → CleanedDF
  ↓
Outlier3LFilter → CleanedDF
  ↓
MissingImputer → CleanedDF
  ↓
UnitNormalizer → CleanedDF
  ↓
cleaned_df_to_records → list[DataRecord]
  ↓
QualityGate.validate → (gate_passed, quality_report)
  ↓
SilverRecord(bronze_id, df, trace, gate_passed, quality_report)
  ↓
gate_passed=True → DalSink.write_silver → 19-DAL
```

### 4.2 核心数据结构

| 结构 | 字段 | 说明 |
|------|------|------|
| `CleanAction` | step, input_rows, output_rows, clipped_count, imputed_count, blocked_count | 单步算子痕迹 |
| `CleaningTrace` | actions: list[CleanAction], started_at, finished_at | 全链路痕迹 |
| `CleanedDF` | df, schema_tag, records, primary_key_count | 清洗中间产物 |
| `SilverRecord` | bronze_id, df, trace, gate_passed, quality_report, schema_tag | 最终产物 |

---

## 5. 接口设计

详见 [API_SPEC.md](./API_SPEC.md)。

**对外入口**：`DataCleaningPipeline.clean(records, *, source, category) -> SilverRecord`

---

## 6. 状态管理

### 6.1 痕迹追踪

`CleaningTrace` 记录完整清洗链，每个 `CleanAction` 包含：
- 算子名（step）
- 输入/输出行数
- 被裁剪/插补/拦截的单元格数
- 自由备注

支持脏数据事后复盘。

---

## 7. 配置管理

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `target_freq` | `"1h"` | 对齐目标频率 |
| `z_threshold` | `3.0` | 3σ 异常阈值 |
| `iqr_coef` | `1.5` | IQR 系数 |
| `atr_k` | `3.0` | ATR 倍数 |
| `enforce_hard_block` | `True` | Gate 硬拦截 |
| `freshness_threshold` | `48h` | 新鲜度阈值 |
| `fail_open` | `False` | 异常兜底开关 |

---

## 8. 错误处理

### 8.1 异常场景

| 场景 | 处理策略 |
|------|----------|
| cleaner 抛异常 | 记录 trace，跳过后续，DF 兜底进 Gate（enforce=False） |
| Gate enforce=True 抛异常 | fail_open=True → catch 返回 gate_passed=False；fail_open=False → 向上抛 |
| DalSink 写入失败 | fail-open，返回 False，不阻塞 |
| 空 records | 返回空 CleanedDF，Gate 按降级源判断 |

### 8.2 降级机制

```
清洗链异常 → trace 记录 → 跳过后续 cleaner → Gate(enforce=False)
Gate 抛异常 → fail_open → gate_passed=False SilverRecord（不入库）
```

---

## 9. 扩展性设计

### 9.1 如何添加新清洗算子

1. 在 `cleaners/` 下新建 `xxx_cleaner.py`，实现 `clean(df) -> CleanedDF`
2. 在 `DataCleaningPipeline._build()` 中实例化
3. 在 `clean()` 方法中按序插入算子链
4. 算子异常由 pipeline 统一 try-except 兜底

### 9.2 如何添加新质量检查

1. 在 18 号 `QualityChecker` 中新增检查项
2. `QualityGate` 自动复用（无需改 20 号代码）

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-09-30 | 初始技术设计（Silver 层 7 步清洗链 + QualityGate + DalSink） |

---

**文档版本**: v1.0
**最后更新**: 2026-09-30
