# 21-特征工程中心 专项 Spec v1.0（摘自全局 Spec v1.0 frozen 对应章节归档）

```
文档状态：归档版（设计冻结，与全局 specs 一致）
来源文档：docs/superpowers/specs/2026-08-24-data-cleaning-and-feature-hub-spec.md
归档范围：本目录 21-特征工程中心 专项内容（FeatureHub / H2+H3集成 / M2+M3阶段 / T13~T28 / 本模块监控）
```

---

## 一、定位（奖章七层中 L5 FeatureHub）

Gold（19-DAL Pandera Validated DF）→ **L5 = 21-特征工程中心**（FeaturePipeline 按 ENABLED_SETS 拉取注册模块 → concat → 标准4步清洗链 → FeatureVector 就绪 → 策略消费）

- 核心原则：**注册接入，不推倒重写**（双入口：Native原生+Adapter适配）
- FeatureRegistry 从 11-易经推理系统 **提拔为全系统标准实现**（语义100%不变，字节等价零回归）
- 0 新增依赖：RobustScaler / VIF / IV 全部手写（不引入 sklearn/tsfresh/Feast）

---

## 二、目录结构

```
21-特征工程中心/
├── feature_hub/
│   ├── __init__.py                         # 统一入口：FeatureHub + StandardCleaningChain
│   ├── contract.py                         # FeatureVector / FeatureSpec / LineageRecord
│   ├── errors.py                           # FeatureError / FeatureSetNotFound
│   ├── hub/                                # 🧩 注册表核心（易经FR提拔）
│   │   ├── feature_registry.py             # ⭐ 从11-易经迁入（@register / ENABLED_SETS 语义不变）
│   │   ├── enabled_sets.py                 # 策略→模块映射（btc_morph_v6 / triple_screen / ...）
│   │   ├── lineage.py                      # 特征血缘追踪（输入→输出，审计）
│   │   └── versioning.py                   # semver：morphology_core:2.1.0
│   ├── cleaning_chain/                     # 🧪 标准特征清洗链（所有模块输出必过）
│   │   ├── cleaning_steps.py               # 4步：①InfNaN ②RobustScaler ③VIF ④IV/RFE
│   │   └── standard_chain.py               # StandardCleaningChain.fit_transform(X, y, skip=小样本)
│   ├── modules/                            # 📦 复用模块库（集中后跨策略可用）
│   │   ├── crypto_morphology.py            # ✅ 易经迁入：morphology_core + ma200 + multi_tf + rolling
│   │   ├── triple_screen_trend.py          # Adapter: 12-TrendFeatureEngineer.create_features()
│   │   ├── elder_ray.py                    # Adapter: 易经Elder-ray.grade()→one-hot + 差分 共7列
│   │   ├── five_domain_fc.py               # Adapter: FiveDomainFeatureComputer→五行5列标准化
│   │   ├── classic_indicators.py           # Adapter: 10-talib 30+常用→特征（默认开 IV≥0.05）
│   │   └── martin_features.py              # Adapter: 14-V15 网格/DD深度→特征
│   ├── adapters/                           # 🔌 子系统 FE→FeatureHub 最小适配层
│   │   ├── base_adapter.py                 # 基类：包装既有 create_features 为统一 compute(df,*ctx)
│   │   ├── registry_adapter.py             # 适配已有 FeatureRegistry → 直接 import 注册
│   │   └── sklearn_style_adapter.py        # 适配 sklearn-style create_features(X)
│   ├── pipeline/
│   │   └── feature_pipeline.py             # 按ENABLED_SETS编排→串清洗链→FeatureVector
│   └── cli/
│       └── app.py                          # fh list / inspect --set / run-sample / export-schema
├── tests/
│   ├── unit/                               # T13~T18 单元
│   └── integration/                        # T17,T18 跨策略集成（样例DF）
├── config/
│   └── feature_sets.yaml                   # ENABLED_SETS 策略→模块映射（回测/实盘共用）
├── requirements.txt
├── docs/
│   └── FEATURE_HUB_SPEC.md                 # 本文件（归档）
└── README.md
```

---

## 三、双入口注册模式（零推倒重写）

| 入口 | 适用场景 | 接入方式 |
|---|---|---|
| **A. Native 原生** | 新模块 & 已迁入（易经FR提拔） | `@FeatureHub.register_module(name, version, enabled_sets=[...])` + `def compute(df, ref_df, macro_df, symbol) → DataFrame` |
| **B. Adapter 适配** | 12/10/14/9 既有 FE（原代码不改） | `SklearnStyleAdapter(FEClass, **kwargs)` / `RegistryAdapter(existing_reg)` → 统一 compute() → 再按入口 A 方式注册（对外字节等同） |

---

## 四、FeatureRegistry 提拔原则（字节等价零回归 · 硬门槛 T-G5）

1. **整体文件迁入**：从 `11-易经推理系统/scripts/memory_l4/bcrm2/feature_registry.py` 整体拷贝到 `21/feature_hub/hub/feature_registry.py`
2. **语义零改变**：`FeatureRegistry.register()` / `ENABLED_SETS` / `FeatureModuleSpec` / `_wdh_sub_key_splitter` / `_cycle_sub_key_splitter` 属性、返回值 100% 不变
3. **原路径改为 shim 反向 re-export（H2 集成点，~5 行）**：
   ```python
   # 11-易经推理系统/scripts/.../bcrm2/feature_registry.py  ← shim
   from feature_hub.hub.feature_registry import (
       FeatureRegistry, ENABLED_SETS, FeatureModuleSpec,
       _wdh_sub_key_splitter, _cycle_sub_key_splitter,
   )
   ```
4. **验收门槛（T-G5）**：易经原单元测试从 shim 路径 import → 11 项**全绿**；shim.FeatureRegistry **is** feature_hub.FeatureRegistry

---

## 五、标准特征清洗链（B8 四步，所有模块输出必过）

```
concat Raw特征 → ① Inf/NaN兜底（+/-inf→median；NaN→ffill(3)→median，全列缺失→全50）
                 ▼
             ② RobustScaler（抗异常值缩放：(X-median)/IQR；IQR=0 恒等不除零；不用 StandardScaler）
                 ▼
             ③ VIF去共线（方差膨胀因子>10从高→低剔除；样本<1000自动跳过）
                 ▼
             ④ IV/RFE（信息值 IV<0.02 剔除；无标签 y 自动跳过）
                 ▼
             FeatureVector（Model-Fit 就绪）
               └─ meta：输入列 / 剔除列与原因 / 摘要 → LineageRecord 审计
               └─ L1 fail-open：任一步异常→Raw特征透传 + log.warning（永不阻塞）
```

---

## 六、跨策略复用价值表（FeatureHub 最大产出 · 原架构做不到）

| 启用集合 | 组成（跨域融合） | 适用策略 | 来源 |
|---|---|---|---|
| `btc_morph_v6` | morphology + ma200_cycle + multi_tf + rolling + five_domain_fc | 易经BTC形态 | 易经原4 + 新接五维 |
| `alt_trend_ensemble` | morphology + elder_ray + triple_screen_trend | SOL/ETH山寨 | ⭐易经形态 + 三屏TrendFE + 易经Elder-ray跨域融合 |
| `equity_classic_trend` | triple_screen + classic_indicators + five_domain_fc(美股jiang=0.18) | 美股COIN/MSTR | 三屏 + 10-经典 + 五维差异化权重（project_memory） |
| `commodity_safe_haven` | classic_indicators + five_domain_fc(黄金tian=0.22) + elder_ray | 黄金XAU/XAG | 10-经典 + 五维黄金 + 易经Elder-ray |

---

## 七、H3 集成点：策略 FE 出口 wrapper（逐策略 ~10 行）

改文件：11/12/10 三个策略入口各加一个 EN 开关 wrapper（共 ≤ 30 行）

```python
# 例：12-三屏趋势系统 predict.py
EN_FEATUREHUB_TRIPLE = os.getenv("EN_FEATUREHUB_TRIPLE_SCREEN", "false").lower() == "true"
if EN_FEATUREHUB_TRIPLE:
    try:
        from feature_hub import FeaturePipeline
        features = FeaturePipeline.run(set_name="triple_screen", df=ohlcv, symbol=symbol)
    except Exception:
        import logging, traceback
        logging.warning("[FeatureHub] triple_screen failed, fallback original, stack=%s",
                        traceback.format_exc(limit=6))
        features = TrendFeatureEngineer(views=None).create_features(ohlcv)  # 自动回退
else:
    features = TrendFeatureEngineer(views=None).create_features(ohlcv)      # 默认：完全不感知
```

灰度 Flag：`EN_FEATUREHUB_*=False（默认旁路）`，异常时自动回退原 FE；逐策略独立开关。秒级回滚=设 False

---

## 八、M2 + M3 阶段交付与验收

| 阶段 | 工期 | 交付物 | 灰度范围 | 测试 & 硬门槛 | 回滚 |
|---|---|---|---|---|---|
| **M2 基建提拔** | 2.5 天 | 21-完整骨架 + FR迁入 + shim + 清洗链 + 3Adapter（TripleScreen/ElderRay/FiveDomainFc）+ fh CLI | 仅跑单测+集成，`EN_FEATUREHUB=False` 策略不动 | T13 FR等价性（T-G5：11单测全绿）→ T14 清洗链边例 → T15 TripleScreen逐列<ε → T16 Elder/FC编码 → T17 3集合样例 → T18 血缘闭合 → T19 编排 → T20 CLI 冒烟 | Flag=False；删 shim；删 21 目录 |
| **M3 全量收口** | 3 天（+ 1周逐策略灰度） | 剩余Adapter（Classic/Martin/基本面）；3个策略分别开开关；docs更新 | 周1全Silver；周2易经btc；周3三屏alt；周4经典美股；周5全开 | T21 8×3 组合 → T22 拦截率≥99.5%（T-G4）→ T23 Adapter等价 → T25 策略一致性≥95%/≥0.97（T-G3）→ T26 L1 fail-open注入 → T27 全局二次回归0回归（T-G2）→ T28 shadow冷启动 | 逐策略Flag=False；全局 EN_SILVER=False |

---

## 九、监控指标（FeatureHub 专项）

| 指标 | 计算方式 | 阈值 |
|---|---|---|
| fh_features_total | 单run产出列数 | 偏离启用集合预期≥10% → WARNING |
| fh_vif_dropped_count / fh_iv_dropped_count | VIF>10 / IV<0.02 剔除列数 | >总列40% → 特征设计重审 |
| fh_lineage_broken_links | 输入→输出血缘断开 | >0 → L3 启动期 FAIL-FAST |
| fh_failopen_count | FE模块异常跳过次数（L1） | 同模块5min≥3 → Lark告警 |
| fh_feature_vector_stale | FE输入DF新鲜度 | ≥ 10min → 旁路离场缓存直接重取 |

---

## 十、日常运维 CLI 快捷入口

| 命令 | 场景 |
|---|---|
| `fh list` | 全注册模块（名/版本/默认启用）+ ENABLED_SETS 清单（上线核对） |
| `fh inspect --set alt_trend_ensemble` | 集合组成 / 预期列数 / VIF&IV最近统计 / 血缘断链检测（策略切换前检查） |
| `fh run-sample --set btc_morph_v6 --symbol BTC --sample 2026-07-01_2026-08-01` | 样例DF快速走一遍全链（手动验） |

---

## 十一、关联回写入口（全局完整版 Spec）

本归档为 21 号专项摘录；完整章节含 奖章全景 / 20-Silver 全参数 / H1集成 / M1阶段 / 错误处理三层 / 新鲜度红线关联易经离场缓存 / T1~T12 等内容：

👉 完整 Spec：[2026-08-24-data-cleaning-and-feature-hub-spec.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/docs/superpowers/specs/2026-08-24-data-cleaning-and-feature-hub-spec.md)
