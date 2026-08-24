# 奖章三层数据架构 + 特征工程中台规范 Spec v1.0（方案 B，设计全章节冻结稿）

```
文档状态：设计冻结（§一总体架构 → §五错误监控测试 五章节经用户B+B连续确认，可用于落地实现）
创建日期：2026-08-24
最后修订：2026-08-24 v1.0（设计全章节冻结）
    v1.0 frozen 里程碑：
      · 架构层：奖章三层(Bronze/Silver/Gold) + FeatureHub 注册制 双入(Native/Adapter)
      · 20-清洗中心：3σ→IQR→14-ATR×k 三级异常；QualityGate 4项硬拦截；fail-open=50
      · 21-特征中心：FeatureRegistry提拔为标准；4步标准清洗链；7个FE模块跨策略复用
      · 集成：3热点(H1/H2/H3 ≤60行改动) + 2Flag(EN_SILVER/EN_FEATUREHUB) 秒级回滚
      · M1/M2/M3 工期 7~8 工作日：T1~T28 ≈142 新用例 + 2× 全局 0 回归硬门槛
方案评级：B 方案 性价比最优（用户最终选定）
行业对标：Databricks 奖章架构 / quantmini production-pipeline / MLdP Modular Feature
          / FiveDomainFeatureComputer fail-open=50 / FeatureRegistry 注册制
          / RobustScaler 四分位缩放金融抗异常值 / VIF≤10 共线性护栏
0 新增依赖原则：全部基于现有 pandas / numpy / data_center.monitoring 三件套 实现
                 不引入 Great Expectations / Feast / tsfresh / scikit-learn
```

---

## 一、修订记录

| 版本 | 日期 | 章节 | 变更说明 |
|---|---|---|---|
| **v1.0 frozen** | **2026-08-24** | **全章冻结** | 经用户五轮 B+B 连续确认：§一 架构 ✅ → §二 20-清洗 ✅ → §三 21-特征 ✅ → §四 集成迁移 ✅ → §五 错误监控测试 ✅。骨架参数 A1~B9 / C1~M18 全部冻结；0 回归硬门槛确认。 |

---

## 二、骨架参数冻结总表（全量）

> 不带 `*` 参数 = 硬编码冻结；带 `*` 参数 = 默认初值+走查表动态校准。任何参数修改必须以 Spec 评审通过为前置。

| # | 层级 | 参数名 | 冻结值（*=动态） | 来源 / 冻结原因 |
|---|---|---|---|---|
| A1 | 架构 | 奖章层数 | 3（Bronze-L1 / Silver-L2 / Gold-L4） | Databricks Medal + 方案B 用户选定 |
| A2 | 架构 | Silver 强制链路 | True（所有数据入库必过 Silver，失败仅写 Bronze+告警） | 脏数据拦截率 ≥ 99.5% 目标 |
| A3 | 架构 | 策略端 FE 迁移模式 | 注册制（@register_module 接入，不推倒重写） | 各子系统 FE 现状不返工 |
| A4 | 架构 | 目录编号 | **20**-数据清洗中心 / **21**-特征工程中心 | 现有目录编号连续 |
| B1 | 清洗 | ①粗筛 Z-score σ | **3.0**（极端行情档 4.5，按 asset 走查） | 正态分布 3σ 覆盖 99.73% |
| B2 | 清洗 | ②中筛 IQR 系数 | **1.5×**（宏观指标收严 1.3×，走查配置） | Tukey Fence 金融惯例 |
| B3 | 清洗 | ③精筛 ATR 周期 × k | **14-ATR × 3.0**（黄金 k=2.5 / 股票 k=2.8，走查） | Wilder ATR + 事件验证后裁剪 |
| B4 | 清洗 | 粗筛动作 | **标记到 trace 不删**（中筛精筛再处理） | 不丢原始信号原则 |
| B5 | 清洗 | fail-open 兜底 | **中性 50 / 中位数 / 前值 ffill**（热路径不抛） | 对齐 project_memory + FiveDomainFeatureComputer |
| B6 | 清洗 | QualityGate 硬拦截 | **enforce_hard_block=True**（EMPTY / CONTRACT / DUPLICATE / FRESHNESS 四项） | 18-quality.py 从监控→门禁升级 |
| B7 | 清洗 | ffill 连续 N 次保护 | **limit=N=5**（超限→线性插值→中性） | 避免 stale data 自欺 |
| B8 | 特征 | 标准特征清洗链顺序 | ① Inf/NaN兜底 → ② RobustScaler(IQR) → ③ VIF>10剔除 → ④ IV<0.02剔除 | 抗过拟合实践；无 y 时 ③④ 自动跳过 |
| B9 | 特征 | FeatureRegistry 模式 | **保留提拔**（从 11-易经迁入 21-hub/；ENABLED_SETS 语义不变） | 现有模式完全符合业界最佳 |
| **集成参数** | | | | |
| C1 | Flag | EN_SILVER 默认 | **False（旁路）**；按 collector×category 粒度开启 | H1 秒级回滚 |
| C2 | Flag | EN_FEATUREHUB 默认 | **False（旁路）**；按策略逐个开启 | H3 秒级回滚；异常→自动回退原 FE |
| C3 | Shim | FR 提拔反 re-export 方式 | `__getattr__ = FeatureHub.FeatureRegistry`（透传不复制逻辑） | H2 字节等价零回归 |
| C4 | 侵入 | 改动文件 & 行数上限 | dispatcher.py（~10）+ shim1 处（~5）+ 3 策略入口（各~10）= **≤ 60 行** | 最小侵入原则 |
| **监控与告警阈值** | | | | |
| M1 | 告警 | silver_gate_pass_rate 红线 | < 98.0%（连续 3 批次）→ Lark 红警 | 默认拦截率目标 ≥ 99.5% |
| M2 | 告警 | silver_missing_impute_rate | > 10% → 告警（数据源头故障） | |
| M3 | 告警 | fail-open 热路径阈值 | 同模块 5 分钟 ≥ 3 次 → Lark 告警 | L1 铁则防静默降级 |
| M4 | 新鲜度 | OHLCV stale 红灯 | ≥ 15 min → 触发离场缓存时效性旁路重取 | project_memory 易经缓存红线 |
| M5 | 新鲜度 | FRED / 宏观 stale 橙/红 | ≥ 48h 橙色；CPI/PCE ≥ 5 天红色 | |
| M6 | 特征 | VIF / IV 剔除警示 | 任一 > 总列 40% → 设计重审（非硬告警） | |
| **验收与测试铁门槛** | | | | |
| T-G1 | 回归 | M1 全局回归 | 18-M1~M5 **164 / 164 全绿，0 回归** | M1 验收前置；任一红点=M1不通过 |
| T-G2 | 回归 | M3 全局二次回归 | 18 + 19-DAL + 11/12/10/14 策略全库 = **0 回归** | M3 验收前置条件 |
| T-G3 | 一致性 | 策略开关一致性 | 开=True vs 关=False：**信号方向一致率 ≥ 95% / 权益曲线 Pearson ≥ 0.97** | 允许特征更优不允许劣化 |
| T-G4 | 拦截率 | 脏数据注入拦截率 | 8源×3资产 × 4类脏注入 → **总拦截 ≥ 99.5%** | |
| T-G5 | 等价 | FR提拔等价性 | 提拔后易经原 11 项测试 100% 通过；TripleScreen Adapter 逐列 < ε=1e-9 | 字节等价零回归 |
| **工期里程碑** | | | | |
| W1 | 工期 | M1 Silver 基建 + yfinance单源试点 | T1~T12（~40 用例 + 164 回归）→ **2 天**（含评审） | |
| W2 | 工期 | M2 FeatureHub 基建 + 提拔 + 3 Adapter | T13~T20（~27 用例）→ **2.5 天**（含评审） | |
| W3 | 工期 | M3 全量收口 + 逐策略灰度一周 | T21~T28（~75 + 全局回归）→ **3 天**（灰度观测） | |
| W4 | 工期 | **合计** | **7~8 工作日**（含用户 B+B 冻结 + 灰度观察期） | |

---

## 三、§一 总体架构设计（已确认 ✅）

### 3.1 七层数据流全景

```
L0 · 上游数据来源（FRED/yfinance/CCXT/Etherscan/Tavily/RSS/Scrapy）
 │
 ▼ 采集 API/爬虫
L1 · Bronze 原始采集层（18-数据获取中心 现有，不改契约）
 │   8 Collectors · DataRecord 契约 · raw 字段完整保留
 │   原则：任何情况不修改上游原始响应（审计与可追溯）
 │
 ▼ ⚡强制链路：入库必先清洗（★ 不绕过，不旁路）
L2 · Silver 清洗中心（20-🆕 新增，§四详述）
 │   去重对齐 → 三级异常值过滤 → 缺失值智能插补 → 单位统一 → 质量门禁硬拦截
 │   失败分支：不入库，仅写 Bronze 审计日志 + Lark/File 告警
 │
 ▼ Silver 干净数据写入 19-DAL
L3 · DAL 数据访问层（19-现有，不动）
 │   Protocols + Unified Models + Repo 多后端实现
 │
 ▼ Repo 读取为 Schema DF
L4 · Gold 就绪层（概念层，产出=Pandera Schema Validated DataFrame）
 │   契约合规 · Pandera Contract · 可直接输入特征工程
 │
 ▼ 🧩 特征生成 + 标准清洗链
L5 · FeatureHub 特征工程中心（21-🆕 新增，§五详述）
     注册表/版本/血缘/启用集合 · 标准特征清洗链 · 复用模块库 · 各策略注册入口
 │
 ▼ 各策略按需取特征向量
L0 · 策略消费端（11-易经 / 12-三屏 / 10-经典 / 14-V15 / 9-基本面，现状不改）
     ──策略回写旁路（CBR案例/训练样本/标签）──▶ 沿旁路写回 Gold/Bronze ◄──┘
```

### 3.2 核心设计原则（18/19 零破坏性兼容 五条铁律）

1. **奖章分层职责单一**：Bronze 存原（不改）→ Silver 清洗（不丢原始trace）→ Gold 就绪（Schema校验），任何层不改契约；18 的 `DataRecord` 与 19 的 `Repo Protocol` **保持不动**
2. **强制清洗链路**：Silver 是 18→19 必经节点；脏数据拦截率 ≥ 99.5%
3. **特征注册而非重构**：21-FeatureHub 提供 `@FeatureHub.register_module()`，各子系统 FE **保持现状逻辑不重写**，改为注册接入，实现跨域复用
4. **策略回写闭环**：CBR案例/训练样本/标签沿旁路回写Gold，不影响热路径
5. **0新增依赖原则**：不引入 Great Expectations（现有 quality.py 覆盖 80% 场景）、不引入 Feast（规模<10策略，过度设计）、不引入 tsfresh/Featuretools（金融DFS过拟合风险极高）

---

## 四、§二 L2 · 20-数据清洗中心 详细设计（已确认 ✅）

### 4.1 目录结构（编号 20 · 独立包 · data_cleaning）

```
20-数据清洗中心/
├── data_cleaning/                       # 主包
│   ├── __init__.py                      # 导出：CleaningPipeline + SilverLayer
│   ├── contract.py                      # SilverRecord / CleanedDF / CleaningTrace 契约
│   ├── errors.py                        # CleaningError / QualityGateFailed 异常
│   ├── cleaners/                        # 算子层（可组合，责任链节点）
│   │   ├── dedup_align.py               # 去重 + 时间戳对齐 + 重采样 ffill(limit=N)
│   │   ├── outlier_filter.py            # 🔴 三级异常值过滤（核心）
│   │   ├── missing_imputer.py           # 缺失值智能插补（时序/宏观/中性50三级兜底）
│   │   └── unit_normalizer.py           # 币种→USD / % 归一 / 量级统一
│   ├── gate/
│   │   └── quality_gate.py              # 🟠 质量门禁：复用 18-quality.py + enforce_hard_block=True
│   ├── adapters/
│   │   ├── record_to_df.py              # DataRecord(metrics/timeseries/events) → 扁平DF
│   │   └── df_to_record.py              # DF → SilverRecord / DAL 写回格式
│   ├── pipeline/
│   │   └── cleaning_pipeline.py         # CleaningPipeline(Chain of Resp): .add(...).run(record)
│   └── cli/
│       └── app.py                       # dc-clean status / health / verify
├── tests/                               # T1~T12 单元+集成测试（见§七）
├── config/
│   └── cleaning_rules.yaml              # category × sub_category × asset 策略参数查表
├── requirements.txt                     # 仅复用 pandas / numpy（0新增）
├── docs/
│   └── DATA_CLEANING_SPEC.md            # 本模块归档版 Spec
└── README.md
```

### 4.2 流水线编排顺序（不可颠倒，责任链顺序硬编码）

```
[DataRecord (Bronze 输入)]
      │
      ▼ ① DedupAlign
      │   - drop_duplicates(subset=[timestamp, asset, key])
      │   - resample(target_freq) → ffill(limit=B7_N=5)；超限→线性插值→中性50
      │
      ▼ ② Outlier3LFilter（🔴 核心）
      │   ┌──────────────────────────────────────────────────┐
      │   │ ① 粗筛：|Z| > B1_3.0 → 标记到 trace（保留原值不裁剪）
      │   │ ② 中筛：< Q1-1.5IQR 或 > Q3+1.5IQR（IQR=B2_1.5x）→ clip 到边界（事件期保留）
      │   │ ③ 精筛：|Δprice_t| > k × ATR14（B3_k=3.0，按asset查表）
      │   │        → 匹配新闻/巨鲸事件：命中→保留；否则 clip + ffill(1)
      │   └──────────────────────────────────────────────────┘
      │
      ▼ ③ MissingImputer（三级兜底 B5_failopen）
      │   时序 → ffill(limit=5) → linear interp → 中性 50 / 列中位数
      │   宏观 → linear interp → 同值拖尾（稳定期）→ 中性 50
      │   事件 → 发生=1 / 未发生=0 / 未知=0.5
      │
      ▼ ④ UnitNormalizer
      │   非USD价格 × 汇率表；百分比 /100；换手率%→ratio
      │
      ▼ [Cleaned DataFrame + CleaningTrace]
      │
      ▼ 🟠 QualityGate(enforce_hard_block=True)（B6 升级）
      │     EMPTY_RESULT        → 空或有效率<70%        → FAIL
      │     CONTRACT_INVALID    → 缺列/类型不匹配        → FAIL
      │     DUPLICATE_DETECTED  → 清洗后行级重复>0      → FAIL（正常应已在①消除）
      │     TIMESTAMP_FRESHNESS → >T stale（按asset）    → FAIL
      │
      ├─✓ PASS → SilverRecord(DF+trace+bronze_id) → 写入 19-DAL Gold 就绪
      └─✗ FAIL → 仅写 Bronze Audit + log ERROR(6层栈) + Lark/File Alert + silver_block_count++
```

### 4.3 模块设计模式表

| 组件 | 设计模式 | 集成关系 |
|---|---|---|
| CleaningPipeline | Chain of Responsibility | dispatcher._fetch_monitored 在 sink 前调用 |
| QualityGate | Facade on data_center.monitoring.quality | 直接 import 复用；新增 enforce_hard_block 模式 |
| Record↔DF Adapter | Adapter（双向） | 按 DataRecord.category（metrics/timeseries/events）展开列 |
| CleaningRule YAML | Strategy 查表 | category×sub_category×asset 覆盖默认参数 |
| fail-open 兜底 | Circuit Breaker（降级） | 任一环节异常→中性值；不抛到交易热路径 |

### 4.4 与 18 数据中心集成点（H1 · 最小侵入 ~10 行）

```python
# 18-data_center/data_center/core/dispatcher.py   ★ 仅修改本文件约10行
from data_cleaning import CleaningPipeline        # 20号包
_pipe = CleaningPipeline.default_with_gate(enforce_hard_block=True)

async def _fetch_monitored(...):
    record = await collector.fetch(...)
    # ⬇️ 新增：Silver 清洗中间件（失败不抛出，fail-open）
    silver_result = _pipe.run_or_fallback(record)
    if silver_result.gate_passed:
        await sink.write_silver(silver_result.silver_record)   # Gold 写 DAL
    else:
        await sink.write_bronze_only(silver_result.bronze_record)  # 仅审计
        await alerting.dispatch(silver_result.quality_report)      # 告警
    return record   # ⭐ 原调用方不感知，data_center 对外契约字节等价不变
```

---

## 五、§三 L5 · 21-特征工程中心 详细设计（已确认 ✅）

### 5.1 目录结构（编号 21 · 独立包 · feature_hub）

```
21-特征工程中心/
├── feature_hub/
│   ├── __init__.py                          # 统一入口：FeatureHub + StandardCleaningChain
│   ├── contract.py                          # FeatureVector / FeatureSpec / LineageRecord
│   ├── errors.py                            # FeatureError / FeatureSetNotFound
│   ├── hub/                                 # 🧩 注册表核心（易经 FR 提拔迁入）
│   │   ├── feature_registry.py              # ⭐ 从 11-易经迁入：@register / ENABLED_SETS 语义不变
│   │   ├── enabled_sets.py                  # 全系统策略组合（btc_morph_v6 / triple_screen / ...）
│   │   ├── lineage.py                       # 特征血缘追踪（输入列→输出列，便于审计）
│   │   └── versioning.py                    # 特征版本号（semver：morphology_core:2.1.0）
│   ├── cleaning_chain/                      # 🧪 标准特征清洗链（所有模块共用）
│   │   ├── cleaning_steps.py                # 4步：①InfNaN ②RobustScaler ③VIF ④IV/RFE
│   │   └── standard_chain.py                # StandardCleaningChain.fit_transform(X, y, skip=小样本)
│   ├── modules/                             # 📦 复用特征模块库（集中化后跨策略可用）
│   │   ├── crypto_morphology.py             # ✅ 从易经迁入：morphology_core + ma200 + multi_tf + rolling
│   │   ├── triple_screen_trend.py           # Adapter: 12-TrendFeatureEngineer.create_features()
│   │   ├── elder_ray.py                     # Adapter: 易经Elder-ray.grade()→one-hot+差分 共7列
│   │   ├── five_domain_fc.py                # Adapter: FiveDomainFeatureComputer→五行5列标准化
│   │   ├── classic_indicators.py            # Adapter: 10-talib 30+常用→特征；默认仅启用 IV≥0.05
│   │   └── martin_features.py               # Adapter: 14-V15 网格/DD深度→特征
│   ├── adapters/                            # 🔌 子系统 FE → FeatureHub 最小适配层
│   │   ├── base_adapter.py                  # Adapter基类：包装既有 create_features 为统一接口
│   │   ├── registry_adapter.py              # 适配既有 FeatureRegistry → 直接 import 注册
│   │   └── sklearn_style_adapter.py         # 适配 sklearn-style create_features(X)
│   ├── pipeline/
│   │   └── feature_pipeline.py              # FeaturePipeline：按 ENABLED_SETS 编排→串清洗链→FeatureVector
│   └── cli/
│       └── app.py                           # fh list / inspect set / run sample / export-schema
├── tests/
│   ├── unit/ (T13 注册表 / T14 清洗链 / T15 Adapter / T16 血缘)
│   └── integration/ (T17 3策略跑通 / T18 跨策略复用)
├── config/
│   └── feature_sets.yaml                    # ENABLED_SETS 策略→模块映射（回测/实盘共用）
├── requirements.txt
├── docs/
│   └── FEATURE_HUB_SPEC.md                  # 本模块归档版 Spec
└── README.md
```

### 5.2 双入口注册模式（Native + Adapter · 不推倒重写）

| 入口 | 适用场景 | 接入示例 | 标签 |
|---|---|---|---|
| **A. Native 原生** | 新模块 / 已迁入模块（易经FR提拔） | `@FeatureHub.register_module(name="morphology_core", version="2.1.0", enabled_sets=["btc_morph_v6"])` + `def compute(df, ref_df, macro_df, symbol) → DataFrame` | ⭐提拔 / 新增 |
| **B. Adapter 适配** | 12/10/14/9 等子系统既有 FE（原代码不改） | `SklearnStyleAdapter(TrendFeatureEngineer, views=['direction','change',...])` 统一 compute 接口后，再按入口A方式注册（对外字节等同） | 🔌 零侵入适配 |

### 5.3 FeatureRegistry 提拔原则（字节等价零回归）

**从 11-易经推理系统的 `feature_registry.py` 整体文件迁入到 `21-hub/feature_registry.py`**：
- 保持 `FeatureRegistry.register()`、`ENABLED_SETS`、`FeatureModuleSpec` 语义、属性、返回值 **100% 不变**
- 原文件路径（11-易经/scripts/.../feature_registry.py）改为 **shim 文件**，仅：
  ```python
  # 11-.../bcrm2/feature_registry.py  ← shim 反 re-export
  from feature_hub.hub.feature_registry import (  # 从 21 号真源导出
      FeatureRegistry, ENABLED_SETS, FeatureModuleSpec,
      _wdh_sub_key_splitter, _cycle_sub_key_splitter,
  )
  ```
- 原易经单元测试从 shim 导入路径执行，必须 **11 项全绿**（T-G5 铁门槛），从而保证提拔字节等价。

### 5.4 标准特征清洗链（B8 四步，所有模块输出必过）

```
模块 concat 后 Raw 特征矩阵
      │
      ▼ ① Inf / NaN 兜底（零容忍硬性消除）
      │   +-inf → replace_inf → col.median；
      │   NaN → ① ffill(limit=3) → ② 列median；
      │   全列仍缺失 → fail-open: 全列 50（中性）
      │
      ▼ ② RobustScaler（抗异常值缩放，不用 StandardScaler）
      │   (X - median) / IQR(Q75-Q25)；IQR=0 恒等缩放（不除零）
      │
      ▼ ③ VIF 去共线（多重共线性护栏）
      │   方差膨胀因子>10 从高到低剔除；样本 <1000 自动跳过（稳健）
      │
      ▼ ④ IV / RFE（预测力筛选，无训练标签 y 时自动跳过）
      │   IV（信息值）< 0.02 认为无预测力剔除；RFE 递归消冗可选
      │
      ▼ FeatureVector（Model-Fit 就绪）
         含 meta：输入列 / 剔除列与原因 / 每步摘要 → 写入 LineageRecord 审计
         热路径fail-open：任一步异常→使用Raw特征 + log.warning（永不阻塞）
```

### 5.5 跨策略复用价值示例表（FeatureHub 最大产出）

| 启用集合名 | 组成（跨域融合） | 适用策略 | 复用来源 |
|---|---|---|---|
| `btc_morph_v6` | morphology_core + ma200_cycle + multi_tf + rolling_stats + five_domain_fc | 易经 BTC 加密形态 | 易经原4 + 新接五维 |
| `alt_trend_ensemble` | morphology_core + elder_ray_feature + triple_screen_trend | SOL/ETH 山寨趋势策略 | ⭐**易经形态 + 三屏 TrendFE + 易经Elder-ray 跨域融合**（原架构做不到） |
| `equity_classic_trend` | triple_screen_trend + classic_indicators + five_domain_fc(美股jiang权重) | 美股 COIN/MSTR | 三屏 + 10-经典指标 + 五维差异化权重（project_memory表） |
| `commodity_safe_haven` | classic_indicators + five_domain_fc(黄金tian权重) + elder_ray_feature | 黄金 XAU/XAG | 10-经典 + 五维黄金 + 易经Elder-ray |

---

## 六、§四 系统集成方式与 M1/M2/M3 渐进迁移（已确认 ✅）

### 6.1 三大最小侵入集成点（H1 / H2 / H3，合计 ≤60 行改动）

| 热点 | 改哪个文件 | 改动行数 | Flag 回滚 | 安全性 |
|---|---|---|---|---|
| **H1 Silver中间件** | 18-`data_center/core/dispatcher.py` | ~10 | `EN_SILVER=False` 完全旁路；按 collector×category 粒度开 | 双写分支保证 Bronze 永远可审计 |
| **H2 FR提拔 shim** | 11-易经 `bcrm2/feature_registry.py`（→ shim） | ~5 | 删除 shim / 重指回原路径即可 | 字节等价；原单测 100% 通过才过 |
| **H3 策略 FE 出口** | 11/12/10 三个策略入口各加一个 wrapper | 各~10 合计 ≤30 | `EN_FEATUREHUB=False` 默认旁路；异常自动回退原 FE | 逐策略开关，互不影响 |

**H3 wrapper 关键代码（逐策略最小侵入 ~10 行）**：
```python
# 各策略FE调用处（如 12-三屏/predict.py 等）添加：
EN_FEATUREHUB = os.getenv("EN_FEATUREHUB_TRIPLE_SCREEN", "false").lower() == "true"
if EN_FEATUREHUB:
    try:
        from feature_hub import FeaturePipeline                    # 走 FeatureHub
        features = FeaturePipeline.run(set_name="triple_screen", df=ohlcv, symbol=symbol)
    except Exception:                                              # 异常：自动回退 + WARNING
        import logging, traceback
        logging.warning("[FeatureHub] alt_trend_ensemble failed, fallback original, stack=%s",
                        traceback.format_exc(limit=6))
        features = TrendFeatureEngineer(views=None).create_features(ohlcv)  # 回退原 FE
else:
    features = TrendFeatureEngineer(views=None).create_features(ohlcv)      # 默认：不感知
```

### 6.2 M1/M2/M3 渐进迁移路线（每阶段独立可验收 + 秒级回滚）

| 阶段 | 工期 | 交付物 | 开启范围（灰度） | 验收标准 | 回滚方式 |
|---|---|---|---|---|---|
| **M1 Silver基建 + yfinance单源试点** | **2 天**（T1~T12） | 20-完整代码 + yfinance接入 + 双写 + H1集成 + dc-clean CLI | `EN_SILVER=False` 默认旁路；**仅 category=finance,source=yfinance** 开试运行（不影响 crypto/macro/news） | 164 全局回归全绿（T-G1）+ yfinance E2E 清洗入库通过 | 18-config `EN_SILVER=False`；删除 20 目录即可 |
| **M2 FeatureHub基建 + 提拔 + 3 Adapter** | **2.5 天**（T13~T20） | 21-完整代码 + FeatureRegistry迁入 + shim + 标准清洗链 + TripleScreen/ElderRay/FiveDomainFc Adapter + fh CLI | `EN_FEATUREHUB=False`（仅跑单测+集成验证，策略侧不动） | FR提拔等价性 11 单测全过 + 三Adapter逐列diff通过 | `EN_FEATUREHUB=False`；删除 shim 指向；删 21 目录无残留 |
| **M3 全量收口 + 逐策略灰度周** | **3 天**（T21~T28 + 1周观察） | Silver覆盖其余7个collector；剩余Adapter补完；3个策略分别开开关；docs更新 | 周1：EN_SILVER全源开；周2：易经btc开；周3：三屏alt；周4：经典美股；周5：全量开 | 拦截率≥99.5%（T-G4）+ 策略一致性≥95%/≥0.97（T-G3）+ 0回归（T-G2） | 逐策略Flag=False；全局 EN_SILVER=False |

**总工期：7~8 工作日**（含用户B+B评审冻结 + 灰度观察期）

---

## 七、§五 错误处理 · 监控 · 测试 策略（已确认 ✅）

### 7.1 三层错误处理（严格分层绝不越界）

| 层级 | 覆盖场景 | 处理策略（铁则） | 日志/告警 |
|---|---|---|---|
| **🛑 L1 交易热路径**<br/><span class="pill pill-safety">实盘开仓/离场/风控</span> | CleaningPipeline / FeaturePipeline / 标准清洗链 运行时异常 | **FAIL-OPEN**：不抛异常中断交易；Silver→原始DF+中性列；FE→跳过该模块；所有兜底落计数指标 | `log.warning + traceback.format_exc(limit=6)`（对齐战略层6层堆栈）；同模块 5min ≥ 3 次 → Lark告警 |
| **⚠️ L2 批处理/回测/CBR建库**<br/>离线阶段 | 门禁失败率高/特征剔除率高/开-关一致性偏差 | **WARNING + CONTINUE**（跑完批全量不中断，打标签） | 指标落表；超过阈值（5%/40%/>1%）标 WARNING；不发 Lark（减少噪声） |
| **🧱 L3 启动期/导入期**<br/>进程启动阶段 | ENABLED_SETS 名错 / 模块名冲突 / YAML语法错 | **FAIL-FAST**：崩溃早于开仓（Crash先于交易） | `log.critical + raise AssertionError`；进程退出码非 0 |

**L1铁则补充**：绝不允许 `except: pass`（静默吞错），每个 fail-open 必须：① 落指标计数 ② 留 6 层堆栈日志 ③ ≥3次/5min 触发 Lark 告警。

### 7.2 监控指标矩阵（100% 复用 18-monitoring 三件套：Metrics + Quality + Alerting）

| 大类 | 指标 | 计算方式 | 告警阈值 |
|---|---|---|---|
| **Silver清洗效果** | silver_gate_pass_rate | PASS / total | < 98% 连续3批次 → 红警（M1 硬门槛 ≥99.5%） |
| | silver_outlier_clip_count | 按①3σ / ②IQR / ③ATR 分3档统计 | ③ ATR档 > 2×7日均值 → 调查（非硬告警） |
| | silver_missing_impute_rate | NaN被插补cell占比 | > 10% → 告警（源头故障） |
| | silver_failopen_count | 兜底次数（L1） | 同模块 5min ≥ 3 → Lark告警 |
| **FeatureHub健康度** | fh_features_total | 单run产出列数 | 偏离启用集合预期 ≥ 10% → WARNING |
| | fh_vif_dropped_count / fh_iv_dropped_count | VIF>10 / IV<0.02 剔除列数 | > 总列40% → 特征设计重审 |
| | fh_lineage_broken_links | 输入→输出血缘断开 | >0 → L3 FAIL-FAST（已在启动期拦截） |
| | fh_failopen_count | FE模块异常跳过次数（L1） | 同模块 5min ≥ 3 → Lark告警 |
| **🕑 新鲜度红线**<br/>（对齐易经离场缓存不可失效） | silver_ohlcv_stale_sec | now() − latest(timestamp) | ≥ 15 min → **触发离场缓存时效性旁路：直接重取**（project_memory红线）|
| | silver_macro_stale_hour | 同上 | FRED ≥ 48h 橙色；CPI/PCE ≥ 5d 红色 |
| | fh_feature_vector_stale | FE输入DF新鲜度 | ≥ 10 min → 旁路离场缓存直接重取 |

### 7.3 测试策略（边例 + 注入 + 回归三层闭合；2×全局0回归铁门槛）

| 阶段 | 编号 | 覆盖边例（每类≥3） | 典型断言 |
|---|---|---|---|
| **M1** | T1-T2 | Contract / Errors 单测 | dataclass 字段齐全；异常继承层次正确 |
| | T3 | Outlier3L 边例 | IQR=0 不抛；巨鲸事件期保留原值；低波动期合理边界；冷启动NaN处理 |
| | T4 | MissingImputer 边例 | 连续>5空→插值→50兜底；整列全空→全50；事件True/False→0.5中性 |
| | T5 | UnitNormalizer | 非USD×汇率正确；百分比/100；换手率ratio归一 |
| | T6 | QualityGate 脏数据注入 | 4类脏注入全部FAIL；FAIL时DB写入=0；Bronze审计行存在 + 告警计数+1 |
| | T7-T8 | Record↔DF Adapter 双向 | 三类DataRecord(metrics/timeseries/events) → DF → SilverRecord 往返无损 |
| | T9 | Pipeline 全链路 + fail-open | 5 类异常注入均兜底（不抛）；CleaningTrace 不空 |
| | T10 | H1 旁路等价性 | EN_SILVER=False 结果 = 18-M5 原行为 byte-level 等价 |
| | T11 | **M1铁门槛：全局回归** | 18-M1~M5 164项 **164/164通过，0回归**（T-G1硬门槛） |
| | T12 | E2E yfinance BTC 端到端 | 拉取→清洗→入库 完整链；trace 可追溯 + 门禁PASS/FAIL 正确 |
| **M2** | T13 | FR提拔等价性 | shim.FeatureRegistry **is** feature_hub.FeatureRegistry；易经原11项测试 100% 通过（T-G5） |
| | T14 | 标准清洗链 边例 | IQR=0恒等；样本<1000跳过VIF；无y时跳过IV；Inf→median后无±inf |
| | T15 | TripleScreen Adapter 等价 | 逐列 diff < ε=1e-9 与原 TrendFeatureEngineer.create_features 完全一致（T-G5） |
| | T16 | Elder-ray / FiveDomainFc Adapter | rating 五级one-hot编码正确；五行raw_scores标准化5列 |
| | T17 | 跨策略3样例 | btc_morph_v6 / alt_trend_ensemble / equity_classic_trend 3个集合在样例DF上shape正确无NaN |
| | T18 | Lineage & Versioning | 模块注册后版本号记录；输入→输出血缘闭合无断链 |
| | T19 | FeaturePipeline 编排 | 按ENABLED_SETS拉取模块→concat→清洗链→FeatureVector 通 |
| | T20 | CLI手通 | fh list / fh inspect / fh run-sample / fh export-schema 4命令冒烟 |
| **M3** | T21 | 全8 collector × 3典型资产 | 24 组合覆盖 crypto/macro/finance/news/chain 五类 |
| | T22 | **拦截率硬门槛**（T-G4） | 4类脏注入 × 8源 × 3资产，**总拦截 ≥ 99.5%**，漏拦截<0.5% |
| | T23 | 剩余Adapter（Classic/Martin/基本面） | 与原实现逐列等价（3类×3用例） |
| | T24 | 跨策略复用（T25 进阶版） | `alt_trend_ensemble` 三模块融合后列数正确 + 重要特征存在 |
| | T25 | **逐策略一致性硬门槛**（T-G3） | True vs False：信号方向一致≥95%、权益曲线Pearson≥0.97（允许优不允许劣） |
| | T26 | L1 fail-open 注入 | Silver/FE 5处异常注入→均不抛；指标落计数；≥3次/5min→告警计数+1 |
| | T27 | **M3铁门槛：全局二次回归**（T-G2） | 18-164 + 19-DAL + 11/12/10/14 策略全库 **0 回归** |
| | T28 | Shadow-mode E2E | 实盘 shadow-mode 冷启动：行情→清洗→FE→推理→CBR→开仓 完整链 |

### 7.4 日常运维 CLI 快捷入口

| 模块 | 命令 | 典型输出场景 |
|---|---|---|
| 20-Silver | `dc-clean status` | PASS率 / 拦截率 / fail-open次数 / 各源stale 状态巡检 |
| 20-Silver | `dc-clean health --source yfinance --asset BTC` | 近N条清洗trace + 脏数据样本样例（实盘异常复盘） |
| 21-FeatureHub | `fh list` | 全注册模块（名/版本/默认启用）+ ENABLED_SETS 清单（上线前核对） |
| 21-FeatureHub | `fh inspect --set alt_trend_ensemble` | 集合组成 / 预期列数 / VIF&IV最近统计 / 血缘断链检测（策略切换前检查） |

---

## 八、自检清单（Spec 冻结后 11 项必核；实施阶段每次提交后二次核）

> 按 brainstorming 自检惯例；✓=本节已核，⊘=留待实施阶段核。

- [✓] 1. 骨架参数冻结表（§二）A1~B9/C1~W4 全部硬编码值或默认初值明确，无模糊项
- [✓] 2. 奖章三层数据流向（§三）Bronze不改 / Silver强制 / Gold就绪 三职责不越界
- [✓] 3. 20-清洗链顺序（§四.2）去重→3级异常→插补→归一→门禁（不可颠倒）
- [✓] 4. 21-双入口注册（§五.2）Native/Adapter 不推倒重写原则
- [✓] 5. FeatureRegistry提拔字节等价性要求+测试门槛（T-G5）明确
- [✓] 6. 三大集成点H1~H3 文件与行数+回滚Flag明确，≤60行侵入
- [✓] 7. M1/M2/M3 工期/验收/回滚三项齐全，M1/M3有0回归硬门槛（T-G1/T-G2）
- [✓] 8. 错误处理三层分层明确，L1有6层堆栈 + 5min≥3次告警要求
- [✓] 9. 新鲜度红线（§七.2）覆盖 OHLCV15min/宏观/CPI/PCE，并与易经离场缓存关联
- [✓] 10. T1~T28 测试编号唯一，边例+脏注入+一致性+回归四类分布齐全
- [✓] 11. 0 新增依赖：不引入 GE/Feast/tsfresh/sklearn/pandera 等包声明（§二顶部0新增原则）

```
Spec 冻结结论：设计五章 B+B 五次确认 + 骨架参数 40 条冻结 + 0 新增依赖 + 0 回归硬门槛 + 7~8工作日
            → **可一次性进入 writing-plans 生成实现计划（T1→T28 串行拆解为 TODO 列表）**
```
