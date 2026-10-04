# 21-特征工程中心 — 工程索引

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 模块级工程索引（L2），对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md)

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 21 |
| 模块名称 | 特征工程中心 |
| 核心职责 | 统一特征工程管道（9 模块 + 配置化集合 + 清洗链 + 血缘） |
| 主入口 | `feature_hub.pipeline.FeaturePipeline` / `feature_hub.hub.feature_registry.FeatureRegistry` |
| 依赖关系 | 上游：OHLCV 数据（19-DAL/20-Silver）；下游：回测引擎、BCRM2 实盘适配器 |
| 文档状态 | ✅ 完整（5 文档齐全） |

---

## 2. 目录地图

```
21-特征工程中心/
├── docs/                        # 文档目录
│   ├── ENGINEERING_INDEX.md     # 本文件
│   ├── TECHNICAL_DESIGN.md      # 技术设计
│   ├── API_SPEC.md              # 接口规格
│   ├── CHANGELOG.md             # 变更日志
│   └── FEATURE_HUB_SPEC.md      # 原始设计规格
├── feature_hub/                 # 核心代码包
│   ├── contract.py              # FeatureVector/FeatureSpec/LineageRecord
│   ├── errors.py                # FeatureSetNotFound
│   ├── pipeline/feature_pipeline.py   # FeaturePipeline 编排
│   ├── hub/                     # 注册表+血缘+版本
│   │   ├── feature_registry.py  # FeatureRegistry（回测/实盘共用）
│   │   ├── lineage.py           # 血缘追踪
│   │   └── versioning.py        # 版本管理
│   ├── modules/                 # 9 大特征模块
│   │   ├── loader.py            # 模块加载器
│   │   ├── crypto_morphology.py
│   │   ├── elder_ray.py
│   │   ├── triple_screen_trend.py
│   │   ├── classic_indicators.py
│   │   ├── talib_aligned.py
│   │   ├── five_domain_fc.py
│   │   ├── martin_features.py
│   │   ├── fundamental_ratios.py
│   │   └── yijing_cycle.py
│   ├── cleaning_chain/
│   │   └── standard_chain.py    # StandardCleaningChain
│   ├── adapters/                # sklearn/registry 适配器
│   ├── gold_reader.py           # Gold 层读取
│   ├── h3_wrapper.py            # H3 地理空间
│   ├── resistance_features.py   # 阻力位特征
│   └── cli/app.py               # fh CLI
├── config/feature_sets.yaml     # 特征启用集合
├── tests/                       # 单元+集成测试
└── README.md
```

---

## 3. 文件清单与职责

### 3.1 契约层

| 文件 | 类数 | 职责 | 关键类 |
|------|------|------|--------|
| `contract.py` | 3 | 特征数据契约 | `FeatureVector`, `FeatureSpec`, `LineageRecord` |
| `errors.py` | 1 | 异常体系 | `FeatureSetNotFound` |

### 3.2 编排层（pipeline/）

| 文件 | 职责 | 关键类/方法 |
|------|------|------------|
| `feature_pipeline.py` | 特征编排管道（按集合串联模块+清洗链） | `FeaturePipeline.run()`, `register_module()`, `register_set()` |

### 3.3 注册表层（hub/）

| 文件 | 职责 | 关键类/方法 |
|------|------|------------|
| `feature_registry.py` | 回测/实盘共用注册表 | `FeatureRegistry.register()`, `compute_all()`, `ENABLED_SETS` |
| `lineage.py` | 血缘追踪 | `LineageRecord.to_dict()` |
| `versioning.py` | 特征版本管理 | — |

### 3.4 特征模块层（modules/）

| 文件 | 职责 | 关键函数 |
|------|------|----------|
| `loader.py` | 模块加载器（9 模块 + YAML 集合） | `load_default_sets()` |
| `crypto_morphology.py` | 加密形态特征 | `compute(df, ...)` |
| `elder_ray.py` | Elder Ray 多空力量 | `compute(df, ...)` |
| `triple_screen_trend.py` | 三重滤网趋势 | `compute(df, ...)` |
| `classic_indicators.py` | 经典技术指标 | `compute(df, ...)` |
| `talib_aligned.py` | TA-Lib 对齐指标 | `compute(df, ...)` |
| `five_domain_fc.py` | 五域因子 | `compute(df, ...)` |
| `martin_features.py` | 马丁策略特征 | `compute(df, ...)` |
| `fundamental_ratios.py` | 基本面比率 | `compute(df, ...)` |
| `yijing_cycle.py` | 易经周期特征 | `compute(df, ...)` |

### 3.5 清洗链层（cleaning_chain/）

| 文件 | 职责 | 关键类 |
|------|------|--------|
| `standard_chain.py` | 标准化清洗链 | `StandardCleaningChain` |

### 3.6 入口层

| 文件 | 职责 | 关键入口 |
|------|------|----------|
| `cli/app.py` | fh CLI | `list`, `inspect`, `run-sample`, `export-schema` |

---

## 4. 核心流程索引

### 4.1 特征计算主流程

```
OHLCV DataFrame
  ↓
FeaturePipeline.run(set_name, df, symbol, ...)       # pipeline/feature_pipeline.py
  ↓
load_default_sets(pipe)                              # modules/loader.py
  ├─ 注册 9 个 Native 模块 compute 函数
  └─ 从 config/feature_sets.yaml 加载启用集合
  ↓
按 set_name 取模块列表 → 逐个调用 compute(df, ...)    # modules/*.py
  ↓ (L1 fail-open: 单模块异常跳过，不影响其他)
StandardCleaningChain.clean(df)                      # cleaning_chain/standard_chain.py
  ↓
LineageRecord 记录血缘                               # contract.py
  ↓
return FeatureVector(df, meta)
```

### 4.2 回测/实盘统一入口

```
回测 walk_forward_backtester ─┐
                              ├→ FeatureRegistry.compute_all(df, ref_df, symbol)
实盘 bcrm2_adapter ───────────┘
                              ↓
                    features, feature_names_by_gua
```

---

## 5. 配置参数索引

| 文件 | 作用 | 关键参数 |
|------|------|----------|
| `config/feature_sets.yaml` | 特征启用集合 | `<set_name>: [module1, module2, ...]` |
| `ENABLED_SETS`（feature_registry.py） | 内置集合（v1~v6） | `btc_morphology_v6` 等 |

---

## 6. 测试体系

| 目录 | 测试内容 |
|------|----------|
| `tests/unit/` | 9 模块 + 清洗链 + 血缘版本 + CLI |
| `tests/integration/` | 跨策略集合 + 一致性 + 端到端 |

**运行命令**：
```bash
cd 21-特征工程中心 && python -m pytest -q
```

---

## 7. 技术债务

| 债务项 | 严重程度 | 说明 |
|--------|----------|------|
| 模块文档 | 🟡 低 | 各模块 compute 函数的输入/输出列定义待补全到 API_SPEC |

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

**文档版本**: v1.0
**最后更新**: 2026-09-30
