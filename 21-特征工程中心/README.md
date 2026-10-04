# 21-特征工程中心

> FeatureHub — 统一特征工程管道：9 大特征模块 + 配置化启用集合 + 清洗链 + 血缘追踪

---

## 概述

21-特征工程中心是 DreamBuddy-V2 的 **统一特征工程管道（FeatureHub）**，消除回测与实盘的特征拼接不一致问题。通过注册表机制统一管理 9 大特征模块，按配置化的启用集合（ENABLED_SETS）编排特征计算，串联标准化清洗链，产出带血缘追踪的 FeatureVector，供回测引擎和实盘 BCRM2 适配器共用。

**核心价值**：
- **唯一入口**：回测（walk_forward_backtester）和实盘（bcrm2_adapter）共用 FeatureRegistry.compute_all
- **配置化**：一键启用特征组合（btc_morphology_v1~v6 等），无需改代码
- **可扩展**：新增模块只需 `@register`，自动接入回测/实盘
- **可追溯**：LineageRecord 记录每步特征变换的输入/输出/丢弃列

---

## 目录结构

```
21-特征工程中心/
├── docs/                        # 文档目录
│   ├── README.md                # 本文件
│   ├── ENGINEERING_INDEX.md     # 工程索引
│   ├── TECHNICAL_DESIGN.md      # 技术设计
│   ├── API_SPEC.md              # 接口规格
│   ├── CHANGELOG.md             # 变更日志
│   └── FEATURE_HUB_SPEC.md      # 原始设计规格
├── feature_hub/                 # 核心代码包
│   ├── contract.py              # FeatureVector/FeatureSpec/LineageRecord
│   ├── errors.py                # FeatureSetNotFound 等异常
│   ├── pipeline/feature_pipeline.py    # FeaturePipeline 编排
│   ├── hub/                     # 注册表+血缘+版本
│   │   ├── feature_registry.py  # FeatureRegistry（回测/实盘共用）
│   │   ├── lineage.py           # 血缘追踪
│   │   └── versioning.py        # 特征版本管理
│   ├── modules/                 # 9 大特征模块
│   │   ├── loader.py            # 模块加载器
│   │   ├── crypto_morphology.py # 加密形态
│   │   ├── elder_ray.py         # Elder Ray
│   │   ├── triple_screen_trend.py # 三屏趋势
│   │   ├── classic_indicators.py # 经典指标
│   │   ├── talib_aligned.py     # TA-Lib 对齐
│   │   ├── five_domain_fc.py    # 五域因子
│   │   ├── martin_features.py   # 马丁特征
│   │   ├── fundamental_ratios.py # 基本面比率
│   │   └── yijing_cycle.py      # 易经周期
│   ├── cleaning_chain/          # 标准化清洗链
│   │   └── standard_chain.py    # StandardCleaningChain
│   ├── adapters/                # 适配器（sklearn/registry）
│   ├── gold_reader.py           # Gold 层数据读取
│   ├── h3_wrapper.py            # H3 地理空间
│   ├── resistance_features.py   # 阻力位特征
│   └── cli/app.py               # fh CLI
├── config/feature_sets.yaml     # 特征启用集合配置
├── tests/                       # 测试套件（单元+集成）
├── requirements.txt
└── README.md                    # 本文件
```

---

## 快速开始

### 1. 环境要求

- Python 3.9+
- 依赖：`pip install -r requirements.txt`

### 2. 运行

```python
from feature_hub.pipeline.feature_pipeline import FeaturePipeline
from feature_hub.modules.loader import load_default_sets

pipe = FeaturePipeline()
load_default_sets(pipe)  # 注册 9 模块 + YAML 集合

# 跑特征集合
fv = pipe.run("btc_morphology_v6", df=ohlcv_df, symbol="BTC")
# fv.df: 带特征列的 DataFrame
# fv.meta: 元信息
```

```bash
# CLI
fh list                    # 列出所有模块和集合
fh inspect --set btc_morphology_v6  # 检查集合列数/模块/血缘
fh run-sample --set btc_morphology_v6 --symbol BTC  # 合成数据跑一次
fh export-schema --set btc_morphology_v6  # 导出 JSON schema
```

---

## 核心功能

| 功能 | 说明 | 入口 |
|------|------|------|
| 特征编排 | 按启用集合串联模块 + 清洗链 | `FeaturePipeline.run()` |
| 统一注册表 | 回测/实盘共用，消除不一致 | `FeatureRegistry.compute_all()` |
| 9 大特征模块 | 形态/趋势/指标/因子/周期等 | `modules/` |
| 配置化集合 | YAML 一键启用组合 | `config/feature_sets.yaml` |
| 标准化清洗链 | 缺失/异常/标准化 | `StandardCleaningChain` |
| 血缘追踪 | 每步变换的输入/输出/丢弃列 | `LineageRecord` |
| 版本管理 | 特征版本控制 | `hub/versioning.py` |

---

## 特征模块清单

| 模块 | 说明 |
|------|------|
| `crypto_morphology` | 加密货币形态特征 |
| `elder_ray` | Elder Ray 多空力量 |
| `triple_screen_trend` | 三重滤网趋势 |
| `classic_indicators` | 经典技术指标 |
| `talib_aligned` | TA-Lib 对齐指标 |
| `five_domain_fc` | 五域因子（趋势/动量/波动/量/情绪） |
| `martin_features` | 马丁策略专用特征 |
| `fundamental_ratios` | 基本面比率 |
| `yijing_cycle` | 易经周期特征 |

---

## 配置说明

`config/feature_sets.yaml` 定义启用集合：

| 集合 | 模块 |
|------|------|
| `btc_morphology_v6` | morphology_core + ma200_cycle + multi_timeframe + rolling_regime_stats |
| `btc_morphology_v5` | morphology_core + ma200_cycle + multi_timeframe |
| `btc_morphology_v4` | morphology_core + ma200_cycle + multi_timeframe + rolling_regime_stats |
| `default_all` | 所有 default_enabled=True 的模块 |

---

## 测试

```bash
cd 21-特征工程中心
python -m pytest -q
```

测试覆盖：9 模块 + 清洗链 + 血缘版本 + 端到端集成。

---

## 相关文档

- [工程索引](./docs/ENGINEERING_INDEX.md) — 文件级索引
- [技术设计](./docs/TECHNICAL_DESIGN.md) — 架构设计
- [接口规格](./docs/API_SPEC.md) — API 文档
- [变更日志](./docs/CHANGELOG.md) — 版本历史
- [项目文档索引](../0-系统文档管理/INDEX.md) — 全项目导航

---

**维护者**: DreamBuddy v2
