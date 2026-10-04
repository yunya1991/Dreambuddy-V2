# 21-特征工程中心 — 技术设计文档

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 子系统技术架构设计，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.2

---

## 1. 概述

### 1.1 系统定位

21-特征工程中心是 DreamBuddy-V2 的 **统一特征工程管道（FeatureHub）**，解决回测与实盘特征拼接不一致的核心问题。通过注册表机制统一管理特征模块，按配置化启用集合编排计算，串联标准化清洗链，产出带血缘追踪的 FeatureVector。

### 1.2 设计目标

| 目标 | 描述 |
|------|------|
| **回测/实盘一致** | 共用 FeatureRegistry.compute_all，消除特征拼接漂移 |
| **配置化编排** | ENABLED_SETS 一键启用特征组合，无需改代码 |
| **可扩展** | 新增模块 = @register，自动接入回测/实盘 |
| **可追溯** | LineageRecord 记录每步变换的输入/输出/丢弃列 |
| **fail-open** | 单模块异常不中断管道，其他模块照常 |

### 1.3 业务边界

| 职责 | 归属 |
|------|------|
| 特征模块计算 | 本模块（modules/） |
| 特征编排/集合管理 | 本模块（pipeline/ + hub/） |
| 清洗链 | 本模块（cleaning_chain/） |
| 血缘/版本 | 本模块（hub/lineage.py + versioning.py） |
| OHLCV 数据提供 | 19-DAL / 20-Silver（上游） |
| 特征消费 | 回测引擎、BCRM2 适配器（下游） |

---

## 2. 架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  入口层：FeaturePipeline.run() / FeatureRegistry.compute_all() │
├─────────────────────────────────────────────────────────────┤
│  编排层：ENABLED_SETS 配置 → 模块列表                          │
├─────────────────────────────────────────────────────────────┤
│  模块层：9 大特征模块（compute(df) → df）                      │
├─────────────────────────────────────────────────────────────┤
│  清洗层：StandardCleaningChain（缺失/异常/标准化）              │
├─────────────────────────────────────────────────────────────┤
│  血缘层：LineageRecord + versioning                           │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 模块关系

```
OHLCV df
  ↓
FeaturePipeline.run(set_name)
  ├─ load_default_sets: 9 模块 + YAML 集合
  ├─ 按 set_name 取模块列表
  ├─ 逐个 compute(df) → concat  (L1 fail-open)
  ├─ StandardCleaningChain.clean(df)
  └─ LineageRecord 记录血缘
  ↓
FeatureVector(df, meta)
  ↓
回测引擎 / BCRM2 适配器
```

---

## 3. 核心算法

### 3.1 注册表机制

**设计目标**：消除回测/实盘特征不一致。
- 模块文件底部 `@register` 注册
- 回测和实盘都调用 `FeatureRegistry.compute_all()`
- 新增模块无需修改回测/实盘代码

### 3.2 启用集合（ENABLED_SETS）

配置化特征组合，按版本迭代：
- `btc_morphology_v1` → `v6`：逐步加入 ma200_cycle / multi_timeframe / rolling_regime_stats
- `default_all`：启用所有 default_enabled=True 的模块

### 3.3 L1 fail-open

单模块 compute 抛异常 → log.warning + 跳过该模块，管道继续执行其他模块。

---

## 4. 数据流

### 4.1 主数据流

```
OHLCV DataFrame (Gold/Silver)
  ↓
FeaturePipeline.run(set_name, df, symbol)
  ↓
modules[i].compute(df)  (i=1..N, L1 fail-open)
  ↓ concat
FeatureDataFrame
  ↓
StandardCleaningChain.clean(df)
  ↓
LineageRecord(input_cols, output_cols, dropped_cols)
  ↓
FeatureVector(df, meta={lineage, schema_tag})
```

### 4.2 核心数据结构

| 结构 | 字段 | 说明 |
|------|------|------|
| `FeatureVector` | df, meta | 特征向量（最终输出） |
| `FeatureSpec` | name, version, enabled_sets, input_cols, output_cols | 模块规格 |
| `LineageRecord` | timestamp, module, input_cols, output_cols, dropped_cols, reasons | 血缘记录 |

---

## 5. 接口设计

详见 [API_SPEC.md](./API_SPEC.md)。

**对外入口**：
- `FeaturePipeline.run(set_name, df, symbol) -> FeatureVector`
- `FeatureRegistry.compute_all(df, ref_df, symbol) -> (df, dict)`

---

## 6. 状态管理

### 6.1 血缘追踪

`LineageRecord` 记录每步特征变换：
- 模块名
- 输入列 / 输出列 / 丢弃列
- 丢弃原因

支持特征可解释性与审计。

---

## 7. 配置管理

| 配置 | 位置 | 说明 |
|------|------|------|
| `config/feature_sets.yaml` | YAML 文件 | 特征启用集合 |
| `ENABLED_SETS` | feature_registry.py | 内置集合（v1~v6） |

---

## 8. 错误处理

### 8.1 异常场景

| 场景 | 处理策略 |
|------|----------|
| 模块 compute 异常 | L1 fail-open：跳过 + log.warning |
| 模块 import 失败 | log.warning，不注册 |
| set_name 不存在 | L3 fail-fast：抛 FeatureSetNotFound |

### 8.2 降级机制

```
模块异常 → log.warning → 跳过该模块 → 管道继续
集合不存在 → FeatureSetNotFound → 调用方处理
```

---

## 9. 扩展性设计

### 9.1 如何添加新特征模块

1. 在 `modules/` 下新建 `my_module.py`，实现 `compute(df, **kw) -> pd.DataFrame`
2. 在 `modules/loader.py` 的 `_MODULE_IMPORTS` 中添加导入路径
3. 在 `config/feature_sets.yaml` 中添加到对应集合
4. 或通过 `FeatureRegistry.register("my_module", factory=MyEngine)` 注册

### 9.2 如何添加新启用集合

1. 在 `config/feature_sets.yaml` 中添加 `<set_name>: [module1, module2]`
2. `load_default_sets` 自动加载

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-09-30 | 初始技术设计（FeatureHub 统一特征管道 + 9 模块 + 注册表 + 血缘） |

---

**文档版本**: v1.0
**最后更新**: 2026-09-30
