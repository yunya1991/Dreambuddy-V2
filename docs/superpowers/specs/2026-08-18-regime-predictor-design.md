# 市场形态预测器（Regime Predictor）— 实现设计 Spec

> 日期: 2026-08-18
> 状态: 待用户审阅 → 用户批准后进入 writing-plans → TDD 实现
> 关联上游: 本 spec 基于前期"弹簧力场 → regime 阈值调节器"实践回测 + 传统金融/GitHub 开源调研
> 方法论: **严格 TDD 测试先行**（每段 Phase 先 RED→GREEN→REFACTOR）
> 回滚铁律: 任一开关关闭时，生产代码行为 100% 等价于开关引入前的 commit

---

## 0. 设计意图与三层架构定位

### 0.1 与现有系统的边界

本设计**新增一层"前置形态预测"**，与现有 BCRM 2.0 方向预测器、后置弹簧力场校正器形成三层结构：

```
┌─ 前置层（ML 训练，本 spec 范围）────────────────────────────────────────────────┐
│                                                                                │
│  【Layer 0：全局 BTC 形态预测】← 整体加密市场形态                               │
│  BTC 日线 → 8 态 → 全局调节：                                                  │
│    多空偏置范围(long_bias/short_bias)                                           │
│    多空持仓比上限(ls_ratio_cap)                                                 │
│    阈值范围偏置(long_threshold_range / short_threshold_range)                   │
│    全局仓位乘数(global_position_mult)                                           │
│                                                                                │
│  【Layer 1：板块龙头形态预测】← 板块级形态 + 资金权重                            │
│  板块龙头日线：                                                                 │
│    DeFi:  UNI / AAVE / COMP / LINK                                             │
│    AI/WEB3: FET / AGIX / RNDR / AR                                              │
│    RWA: ONDO / SYN / PROP / TRAC                                               │
│    MEME: PEPE / DOGE / SHIB / WIF                                              │
│    L2: OP / ARB / STRK / IMX                                                   │
│    （美股: 科技/金融/能源/医药等板块ETF龙头）                                   │
│  → 每个板块独立 8 态 → 板块资金权重分配(sector_weight)                          │
│    + 板块级止盈止损乘数                                                         │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
                             ↓ 输出 5 个全局调节 + 5×板块资金权重
┌─ 核心层（聚焦具体币种，不变）──────────────────────────────────────────────────┐
│  BCRM 2.0 方向预测器（1H，聚焦各板块强势币种）                                   │
│  输入：前置层分配的板块资金权重 → 对该板块强势币种提高仓位                       │
│  输出：具体币种方向预测 + confidence                                             │
└────────────────────────────────────────────────────────────────────────────────┘
                             ↓
┌─ 后置层（已实现）──────────────────────────────────────────────────────────────┐
│  弹簧力场 5 态 + 回测数据 → 调节开仓阈值（已上线，与前置层阈值范围叠加）         │
└────────────────────────────────────────────────────────────────────────────────┘
```

**关键原则**：
1. 前置形态预测**不替代方向预测**，也不替代弹簧力场
2. **前置层是"分层形态预测"**：
   - Layer 0（全局 BTC）→ 管整体加密市场形态：输出多空偏置范围、多空持仓比上限、阈值范围偏置、全局仓位乘数
   - Layer 1（板块龙头）→ 管板块级形态：每个板块独立形态预测，输出板块资金权重 + 板块级止盈止损乘数
   - 板块龙头代表板块整体趋势：某板块形态强势 → 该板块资金权重提高（如 HYP 强 → AI/DeFi 板块权重提高）
3. **核心层管"具体币种"**：BCRM 2.0 聚焦各板块的强势币种做方向预测，前置层提供"给该板块多少资金"的权重
4. 前置层调"多空偏置范围/阈值范围偏置/板块资金权重/仓位/止盈止损"，后置弹簧力场调"开仓阈值"
5. 所有偏置、阈值、持仓比都设计为**范围**（min~max）而非单点值，便于弹簧力场后置层回测后针对性调节
6. 两层独立工作，开关独立可回滚

### 0.2 用户确认的核心决策（2026-08-18）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 前置层架构 | **分层形态预测（Layer 0 全局 BTC + Layer 1 板块龙头）** | 全局管多空偏置/持仓比/阈值范围，板块管资金权重 |
| Layer 0（BTC 全局）输出 | **多空偏置范围 + 多空持仓比上限 + 阈值范围偏置 + 全局仓位乘数** | BTC 训练适用于整体加密市场，偏置/阈值用范围便于后置回测调节 |
| Layer 1（板块龙头）输出 | **板块资金权重 + 板块级止盈止损乘数** | 板块龙头形态强势 → 板块资金权重提高（如 HYP 强 → AI/DeFi 权重提高） |
| 加密板块分类 | DeFi / AI-Web3 / RWA / MEME / L2（每板块 4 个龙头币）| 主流板块覆盖，每板块龙头数足够形成板块形态信号 |
| 美股板块分类 | 科技 / 金融 / 能源 / 医药 / 消费（用板块 ETF 龙头）| 传统金融成熟板块划分 |
| 核心层（BCRM 2.0）职责 | **聚焦具体币种**（各板块的强势币种）方向预测 | 前置层决定"给板块多少钱"，核心层决定"选板块内哪个币+做多做空" |
| 数值范围化原则 | **偏置/阈值/持仓比都设计为 min~max 范围** | 单点值不灵活，范围便于弹簧力场后置回测针对性调节（如牛市末期多空阈值都上调）。形态识别本身也是区间（Level-Trend 连续评分）而非跳变。 |
| 多空持仓比控制 | **全局 ls_ratio_cap（如牛市≤0.10, 熊市≤2.0）** | 极端市场下限制反向开仓：牛市几乎禁止空头，熊市允许空头 |
| **🔄 形态识别路线（2026-08-19 更新）** | **Level-Trend 双维度连续区间 + 8 态软概率 + LightGBM 概率校正（美联储点阵图式融合）** | **不做 LGBM 直接硬分类**。核心锚点是 Level(-4~4)/Trend(-4~4) 两个连续量 + Consensus(0~1) + 8 态概率分布；LightGBM 仅作为"数据驱动的概率校正器"以 0.4 权重与高斯中心概率加权融合。 |
| **输出范围的生成策略（2026-08-19 更新）** | **Level-Trend 纯连续函数方案 A** | 6 全局范围参数 + 5 板块权重 = `clip(base + w_L·L/4 + w_T·T/4 + w_C·(C-0.5))` 的线性函数；区间带宽 = 历史分位宽度 × consensus 收窄系数，随时间自动滚动更新极值。符合「道氏趋势 + 量变引起质变 + 数据驱动修正」。 |
| 特征策略 | **v4 五模块：形态核心 / MA200周期 / 多时间框架 / 滚动统计 / 板块β** | 前三 = LightGBM 校正器特征池；后两 = 方案 A 范围映射和板块权重用 |
| 权重机制 | **LightGBM 概率校正用 log-odds 加权融合（w_gauss=0.6 / w_lgbm=0.4）** | 不改 6 层核心流水线权重；LGBM 权重 Phase 3 P3.3 用 WalkForward PnL 网格调优 |
| 市场广度数据 | **纯价格合成（8 币 MA128 同向等）+ 板块强弱对比** | 零外部依赖，零开发风险 |

### 0.3 调研结论的关键完善点

基于传统金融（Dow Theory/Wyckoff/Elliott）+ GitHub 开源项目（LucasLarese/nyro-github/AIOKA/Raynergy）调研：

1. **ADX(14) + DI**：几乎所有开源项目都用，我们缺失 — 必须新增
2. **Hurst 指数**：趋势 vs 均值回归核心指标 — 必须新增
3. **布林带宽度百分位**：波动率压缩/扩张识别 — 必须新增
4. **距 60 日高点比例**：回撤深度 — 必须新增
5. **8 态标签数据驱动生成**（参考 LucasLarese 4 态扩展到 8 态）— 放弃手工标注
6. **评估指标用 Macro F1**（参考 LucasLarese）— 替代简单准确率
7. **Phase 2 引入 BOCPD + HMM 集成**（开源最佳实践）— 形态切换预警 + 时序建模

---

## 1. 实现边界与交付物

### 1.1 本次实现严格不超出的范围（YAGNI 约束）

| 模块 | 允许改动 | 严格禁止 |
|------|---------|---------|
| `bcrm2/feature_registry.py` | 新增 `ENABLED_SETS["btc_morphology_v4"]` / `v4_layer1`；注册 `rolling_regime_stats` 和 `sector_beta_pool` 两个新模块；新增 `build_feature_schema()` 方法导出 schema.json | 不得修改已有 3 个基础模块的 compute 行为与字段名；不得移除任何 ENABLED_SETS 历史版本 |
| `bcrm2/rolling_regime_stats.py` | 🆕 新建：L/T 滚动分位 (60d/252d) + 共识/熵 20d 均值 + 量 zscore（共 16 列） | 不得依赖 Phase 4 BOCPD/HMM 的任何未落地输出 |
| `bcrm2/sector_beta_pool.py` | 🆕 新建：5 板块 β(252d) / α(60d) / 相关系数 (共 15 列)；调用侧传 `coins_closes` dict | 不允许内置 OKX API 抓行情（调用方负责提供 closes 数据） |
| `bcrm2/lgbm_calibrator.py` | 🆕 新建：LightGBM 8 态概率校正器。fit(X_lgbm_pool=形态三基础模块, y=8态标签)，calibrate(p_gauss, X_lgbm_pool) 返回 p_out；配套 feature_schema.json 校验 + schema 不一致抛 ValueError | **禁止**把 LightGBM 当硬分类器；禁止丢弃高斯中心概率；单条预测与批量必须同一入口走 calibrate(=predict_proba) |
| `bcrm2/parameter_mapper.py` | 🆕 新建：Level-Trend 纯连续函数（方案 A）→ 6 全局范围 (lower, upper) + 5 板块权重 Σ=1 + tp/sl 乘数。随时间自动滚动 min/max 差值界定区间。 | 不得出现 8 态硬查表；不得出现任何 8 态→中心值的经验映射表；所有映射必须是 Level/Trend/Cons 的可微分分段函数。 |
| `bcrm2/regime_mapper.py` | Phase 1 仅允许在构造 `RegimeMapper` 时增加 `lgbm_calibrator` 可选参数，把 `p_gauss` 喂给 LGBM 融合后再走 softmax/Top3/Consensus | 不得修改高斯中心 REGIME_CENTERS 默认坐标；不得改动 `w_mapper=1.0` 时既有行为 |
| `run_evolution_pipeline.py` | 新增 `--with-lgbm model_path` 参数；新增 `--feature-schema-out` 参数；最后一帧增加字段 `global_ranges` 和 `sector_weights`（如传了板块β池） | 不得移除或改变 JSON 中已有的 trajectory/snapshot 字段（防回滚） |
| 新增 `artifacts/btc_lgbm_v4/` 目录 | 保存 booster.json + feature_schema.json + feature_importance.csv | 不提交 > 20MB 模型文件到 git（.gitignore） |

### 1.2 交付物清单（按 Phase 分拆，每个 Phase 独立验收）

| 阶段 | 新增/修改文件 | 交付成果 | 验收通过标准 |
|------|-------------|---------|-------------|
| **Phase 0（已完成 · 2026-08-18~2026-08-19 Day 0-3）** | `bcrm2/indicators.py`（IndicatorBank）/ `score_composer.py` / `temporal_smoother.py` / `regime_mapper.py` / `storage.py` / `run_evolution_pipeline.py` + 3 份 TDD | 6 层核心流水线（IndicatorBank 12 原子 → Level-Trend 钳制 → HMM 平滑 → 高斯 8 态软概率 → JSON Storage → CLI 6/6 验收） | 10 项 TDD 全过；Phase 0 最终验收检查单 6/6：关键日期象限 PASS；consensus≥0.30 占 100%（mean 0.632）；连续性 p99=0.176；概率归一化 100%；Top1 覆盖 4 类、Top3 覆盖 6 类（不坍缩）；BTC 2422 根 × 90 日窗口端到端 1.7 秒 |
| **Phase 1（本阶段）** | `feature_registry.py`（ENABLED_SETS v4 + schema 导出）/ `rolling_regime_stats.py` / `sector_beta_pool.py` / `lgbm_calibrator.py` / `parameter_mapper.py` / `train_lgbm_calibrator_v4.py` 脚本 + `tests/test_feature_registry_v4.py` + `test_lgbm_calibrator.py` + `test_parameter_mapper.py` | **FeatureRegistry v4**（5 模块）+ **LightGBM 概率校正器**（log-odds 融合 w_gauss=0.6 / w_lgbm=0.4，schema 严格校验）+ **Level-Trend 纯连续参数映射器**（方案 A）+ 4 项 TDD 全通过 | T11 LGBM 融合生效（JS 散度 ≥ 0.02）；T12 参数映射单调性成立（C 高带宽窄 + L/T 单调性）；T13 schema 错列顺序抛 ValueError；T14 5 板块权重 Σ=1 + β 高权重大；（可选 T15）BTC 3 关键日期参数方向正确 |
| **Phase 2 前置形态层接入 BTC** | `polling_trader.py`（开关 S5 + 仓位/止盈止损/阈值调节分支）/ `trading_utils.py`（regime_multipliers 字段）/ `tests/test_regime_pred_integration.py` | enable_regime_predictor 开关 + 仓位/止盈止损/阈值调节器 | 开关关闭时行为 100% 等价旧路径（TDD 断言）；开关打开时各 regime 乘数正确应用；回测 PnL ≥ 基线 95% / Sharpe 提升 ≥ 15% |
| **Phase 3 美股形态预测器** | `datafeeds/us_stock_feed.py`（新建）/ `scripts/train_us_stock_regime_predictor.py`/ `polling_trader_us.py`（美股独立策略）/ `tests/test_us_stock_regime.py` | 美股数据源（Yahoo Finance）+ 美股形态预测器 + 独立美股交易策略 | 美股 8 态分类 Macro F1 ≥ 0.50（美股样本更少，阈值略低）；美股独立回测 Sharpe ≥ 0.8 |
| **Phase 4（可选）BOCPD + HMM 集成** | `features/bocpd.py`（新建）/ `models/hmm_regime.py`（新建）/ `regime_predictor.py`（集成接口扩展）/ `tests/test_bocpd_hmm_integration.py` | BOCPD 在线变点检测 + HMM 时序状态建模 + LGBM 集成 | BOCPD 比实际形态转移提前 ≥ 3 日；集成后 Macro F1 ≥ 0.65；HMM 转移矩阵可视化通过 |
| **Phase 5（可选）外部数据源** | `datafeeds/coingecko_feed.py`（新建）/ `datafeeds/macro_feed.py`（VIX/A-D Line） | USDT 市值、BTC.D、VIX、A/D Line 等外部数据 | 外部数据准时率 ≥ 99%；接入后形态预测 Macro F1 提升 ≥ 3% |

---

## 2. Feature Flag 设计

### 2.1 开关清单

| # | 开关属性名 | 默认值 | 控制范围 | "开关=False" 严格语义 | 对应阶段 |
|---|-----------|-------|---------|---------------------|---------|
| S5 | `enable_regime_predictor` | **True**（Phase 2 才写，Phase 0/1 不引用）| 前置形态预测层：仓位/止盈止损/阈值调节 | `regime_multipliers` 恒为 None；仓位/止盈止损/阈值计算走旧路径（无 regime 乘数） | Phase 2 |
| S6 | `enable_bocpd_hmm` | **False**（Phase 4 才写，默认关）| BOCPD + HMM 集成 | 不调用 BOCPD/HMM，形态预测纯用 LGBM | Phase 4 |
| S7 | `enable_external_data` | **False**（Phase 5 才写，默认关）| 外部数据源（CoinGecko/VIX） | 不拉取外部数据，广度组用代理特征 | Phase 5 |

### 2.2 开关组合的合法状态矩阵

| 模式名 | S5 | S6 | S7 | 说明 | 推荐灰度阶段 |
|--------|----|----|----|------|-------------|
| 回滚模式（SAFE）| False | False | False | 100% 等价升级前 | 任何时候出 Bug 先切 |
| Phase 2 验证 | True | False | False | 只启用 LGBM 形态预测层 | 实盘第 1~7 天 |
| Phase 4 集成 | True | True | False | LGBM + BOCPD + HMM 集成 | 实盘第 8~21 天观察 |
| 全功能模式 | True | True | True | 完整启用外部数据 | 实盘第 22 天起 |
| 只跳过 BOCPD/HMM | True | False | True | LGBM + 外部数据，无 HMM 集成 | 异常降级 |

---

## 3. Phase 0：6 层核心流水线落地（Day 0-3 已完成 · 原 4+8 特征设计保留为附录 3A）

> **说明（2026-08-19 更新）**：原 §3 方案（ADX/DI/Hurst/BB宽/广度 12 原子特征直接喂 LGBM 硬分类）在 Day 1 中期评估中与用户的「道氏理论 + 量变引起质变 + 美联储点阵图式软概率区间」方法论不完全对齐。经 Brainstorming 三轮澄清后，Phase 0 最终调整为 **Level-Trend 双维度连续锚点 + 高斯中心 8 态软概率 + HMM 平滑** 方案，同时原 ADX/Hurst/BB 宽等 12 个计算被作为 `IndicatorBank` 的 12 主指标内核保留下来（不喂 LGBM 硬分类，而是加权合成 Level/Trend）。下面的 §3.0 是 Phase 0 **已落地内容**；§3.A 之后的小节保留为「原始设计附录」。

### 3.0 Phase 0 已交付（Day 0-3 2026-08-18 ~ 2026-08-19 · TDD 10/10 通过 · 验收 6/6）

**6 层核心流水线（Layer 1~5）**：

```
IndicatorBank (12 主指标 + 辅助原始值)
     ↓ 12×权重 → 加权合成
ScoreComposer (Level / Trend 双维度 9 格扩展 + 每日钳制 Δmax=0.4/0.3)
     ↓ 连续序列
TemporalSmoother (HMM 3态 Viterbi 解码 + EMA 兜底 + 0.7/0.3 软混合)
     ↓ (L_smooth, T_smooth) ∈ [-4,4]×[-4,4]
RegimeMapper (8 态高斯中心 → softmax(T=0.6) → Top3 + Consensus；冷启动 BTC 8 中心已校准)
     ↓ regime_probs + consensus
Storage JSON（RegimeStateFrame 15 字段 + snapshot_latest + trajectory）
     ↓ CLI
run_evolution_pipeline（6 层串联 + BTC 冷启动校准 + 3 关键日期象限验收 + --window/--out）
```

**验收检查单最终结果（BTC 2021-05 ~ 2026-08 共 2422 根 1D，窗口 90 日）**：

| # | 验收项 | 结果 | 数值 |
|---|---|---|---|
| 1 | 3 关键日期象限方向正确（ATH/FTX/减半）| ✅ PASS | ATH 69k (L=+3.08, T=+1.57) / FTX (L=-2.30, T=-1.54) / 2024 减半 (L=+2.75, T=+1.45) |
| 2 | 90% 日 Consensus ≥ 0.30 | ✅ PASS | 覆盖率 100%，Consensus 均值 = 0.632 |
| 3 | 连续性 p99 = \|ΔL+ΔT\| ≤ 1.0 | ✅ PASS | p99 = 0.176 |
| 4 | JSON 字段完整 (meta/snapshot/trajectory) | ✅ PASS | 2422 帧 × 15 字段完整，round-trip 100% |
| 5 | 8 态概率归一化（所有帧 Σ=1 ±1e-6）| ✅ PASS | 0 帧不归一 |
| 6 | 不坍缩（Top1 覆盖 ≥ 3 类 / Top3 ≥ 5 类）| ✅ PASS | Top1=4 类 · Top3=6 类 |

### 3.A 原 Phase 0 原子特征设计（已内化为 IndicatorBank 子模块，保留为设计背景）

> 本节剩余内容（3.1 ADX/DI → 3.3 BOCPD 特征清单）为 Phase 0 Day 0 早期设计，**最终未作为独立 FeatureRegistry 模块落地**；但 ADX/DI、Hurst、BB 宽、60 日高点比例、道氏 HHHL 等指标全部已纳入 `IndicatorBank` 12 主指标的内部计算实现（见 `bcrm2/indicators.py`），仅不再作为单独特征列输出。保留本节仅为读者理解特征背景来源。

---

### 3.A.1 形态核心组（4 个新特征，在 `classic_experience_features.py`）

#### 3.A.1.1 ADX(14) + DI（Wilder 1978 标准实现）

```python
def compute_adx(highs, lows, closes, period=14):
    """
    Wilder ADX 标准实现
    返回: (adx, plus_di, minus_di)
    
    形态语义:
      ADX > 25 → 趋势形态（TREND_*）
      ADX < 20 → 震荡形态（RANGE_BOUND / CONSOLIDATION）
      +DI > -DI → 多头趋势方向
      -DI > +DI → 空头趋势方向
    """
    # TR (True Range)
    tr = [max(h - l, abs(h - prev_c), abs(l - prev_c))
          for h, l, prev_c in zip(highs[1:], lows[1:], closes[:-1])]
    # +DM / -DM
    plus_dm = []
    minus_dm = []
    for i in range(1, len(highs)):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)
    # Wilder 平滑（EMA 替代）
    plus_di = 100 * ewma(plus_dm, period) / ewma(tr, period)
    minus_di = 100 * ewma(minus_dm, period) / ewma(tr, period)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
    adx = ewma(dx, period)
    return adx, plus_di, minus_di
```

**输出特征**：
- `adx_14`: ADX 值（0-100）
- `adx_plus_di`: +DI 值
- `adx_minus_di`: -DI 值
- `adx_trend_strength_bucket`: 离散化（0=震荡<20, 1=转换20-25, 2=趋势>25）

#### 3.1.2 Hurst 指数（R/S 分析法）

```python
def compute_hurst(series, min_n=10, max_n=100):
    """
    R/S Analysis Hurst Exponent
    
    形态语义:
      H > 0.55 → 趋势性（持续）形态
      H < 0.45 → 均值回归（反持续）形态
      H ≈ 0.5 → 随机游走
    """
    # 对多个窗口大小 n 计算 R/S
    rs_values = []
    ns = []
    for n in range(min_n, min(max_n, len(series)//2)):
        chunks = [series[i:i+n] for i in range(0, len(series), n)]
        rs_chunk = []
        for chunk in chunks:
            if len(chunk) < n:
                continue
            mean = np.mean(chunk)
            deviations = np.cumsum(chunk - mean)
            R = max(deviations) - min(deviations)
            S = np.std(chunk)
            if S > 0:
                rs_chunk.append(R / S)
        if rs_chunk:
            rs_values.append(np.mean(rs_chunk))
            ns.append(n)
    # log-log 回归求斜率 = Hurst
    if len(ns) < 2:
        return 0.5
    log_ns = np.log(ns)
    log_rs = np.log(rs_values)
    slope = np.polyfit(log_ns, log_rs, 1)[0]
    return float(np.clip(slope, 0.0, 1.0))
```

**输出特征**：
- `hurst_exp_50`: 50 周期 Hurst 指数
- `hurst_exp_100`: 100 周期 Hurst 指数
- `hurst_category`: 离散化（0=均值回归<0.45, 1=随机0.45-0.55, 2=趋势>0.55）

#### 3.1.3 布林带宽度百分位

```python
def compute_bb_width_percentile(closes, bb_period=20, lookback=252):
    """
    布林带宽度在最近 lookback 期的百分位
    
    形态语义:
      百分位 < 10 → 极度压缩（ squeeze，即将突破）
      百分位 > 90 → 极度扩张（波动率峰值，可能反转）
    """
    ma = closes.rolling(bb_period).mean()
    std = closes.rolling(bb_period).std()
    bb_width = (4 * std) / ma  # (Upper - Lower) / Middle
    percentile = bb_width.rolling(lookback).rank(pct=True)
    return percentile
```

**输出特征**：
- `bb_width_percentile_252`: 252 日百分位（0-1）
- `bb_squeeze_signal`: 布尔（百分位 < 0.1 → 1，else 0）

#### 3.1.4 距 60 日高点比例

```python
def compute_distance_to_high(closes, lookback=60):
    """
    当前价距 N 日高点的回撤比例
    
    形态语义:
      ratio > 0.95 → 接近新高（突破形态）
      ratio 0.85-0.95 → 高位整理
      ratio 0.70-0.85 → 健康回调
      ratio < 0.70 → 深度回调（可能反转形态）
    """
    high = closes.rolling(lookback).max()
    ratio = closes / high
    return ratio
```

**输出特征**：
- `distance_to_high_60d`: 比例（0-1）
- `distance_to_high_120d`: 120 日版本（长周期对比）

### 3.2 市场广度组（8 个新特征，在 `cross_asset_features.py`）

#### 3.2.1 8 主流币 MA128 同向比例

```python
def compute_breadth_ma128_align(coins_closes: dict, ma_period=128):
    """
    8 主流币（BTC/ETH/SOL/BNB/XRP/ADA/DOGE/AVAX）中
    收盘价 > MA128 的数量占比
    
    形态语义:
      breadth > 0.75 + slope_align > 0.75 → 全面牛市（FOMO_RALLY / TREND_UP_STRONG）
      breadth < 0.25 + slope_align < 0.25 → 全面熊市（VOLATILE_DROP）
      breadth ≈ 0.5 → 震荡/轮动（RANGE_BOUND / CONSOLIDATION）
    """
    coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX"]
    above_count = 0
    slope_up_count = 0
    for coin in coins:
        closes = coins_closes.get(coin, [])
        if len(closes) < ma_period + 5:
            continue
        ma = sum(closes[:ma_period]) / ma_period
        ma_prev = sum(closes[1:ma_period+1]) / ma_period
        if closes[0] > ma:
            above_count += 1
        if ma > ma_prev:
            slope_up_count += 1
    breadth_align = above_count / len(coins)
    breadth_slope = slope_up_count / len(coins)
    return breadth_align, breadth_slope
```

#### 3.2.2 BTC 市占率变化（加密独有广度）

```python
def compute_btc_dominance_change(coins_closes: dict, lookback=30):
    """
    BTC 市值 / 8 币总市值 的 lookback 日变化
    
    形态语义:
      正值（BTC.D 上升）→ 资金回 BTC（避险，山寨熊市）
      负值（BTC.D 下降）→ 山寨行情（风险偏好高）
    """
    coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX"]
    # 用价格代理市值（流通量缓慢变化）
    total_now = sum(coins_closes[c][0] for c in coins if len(coins_closes.get(c, [])) > 0)
    btc_now = coins_closes["BTC"][0]
    total_past = sum(coins_closes[c][lookback] for c in coins if len(coins_closes.get(c, [])) > lookback)
    btc_past = coins_closes["BTC"][lookback]
    dom_now = btc_now / total_now
    dom_past = btc_past / total_past
    return dom_now - dom_past
```

#### 3.2.3 其他 6 个广度特征（简略）

| 特征名 | 计算方式 | 形态语义 |
|--------|---------|---------|
| `breadth_new_high_low_ratio_30d` | 8 币 30 日新高数 / 新低数比 | 突破广度（FOMO 高新高多） |
| `breadth_vol_correlation_20d` | 8 币 20 日滚动收益率的平均两两相关系数 | 市场同步度（低=轮动，高=极端） |
| `alt_vs_btc_excess_return_30d` | 7 山寨等权 30 日超额收益（相对 BTC） | 山寨相对强弱（风险偏好） |
| `btc_mcap_ma128_slope` | BTC 价格×流通量 MA128 斜率 | BTC 市值趋势代理 |
| `stablecoin_inflow_proxy` | 30D BTC 波动率倒数值（低波动率=稳定币入场代理） | 稳定币资金流入代理（Phase 5 用真实数据替代） |
| `breadth_momentum_5d` | 8 币 5 日动量同向比例 | 短期广度动量 |

### 3.3 TDD 测试矩阵

| 测试 | 验证内容 | 通过标准 |
|------|---------|---------|
| `test_adx_trending_market` | ADX 对 BTC 2024 牛市日线 | ADX > 25，+DI > -DI |
| `test_adx_ranging_market` | ADX 对 2023 横盘期 | ADX < 20 |
| `test_hurst_trending` | Hurst 对单调上升趋势序列 | H > 0.55 |
| `test_hurst_mean_reverting` | Hurst 对均值回归序列 | H < 0.45 |
| `test_bb_width_squeeze` | BB 宽度百分位对压缩期 | < 0.1 |
| `test_distance_to_high_ath` | 距高点比例在 ATH 时 | ≈ 1.0 |
| `test_breadth_ma128_all_above` | 8 币全在 MA128 上 | breadth = 1.0 |
| `test_breadth_ma128_mixed` | 4 币在 MA128 上 | breadth = 0.5 |
| `test_btc_dominance_change_positive` | BTC 涨山寨跌 | dominance_change > 0 |
| `test_all_features_registered` | FeatureRegistry 注册 | 12 个新特征都可查询 |

---

## 4. Phase 1: FeatureRegistry v4 + LightGBM 概率校正器 + Level-Trend 纯连续参数映射

> **方法论更新（2026-08-19）**：原 §4 方案（LGBM 多分类器继承 MarketRegimeClassifier，直接输出 8 态硬标签/概率）与当前「Level-Trend 连续区间 + 美联储点阵图式融合」的方法论冲突，已废弃。当前 Phase 1 的 LightGBM **仅作为概率校正器参与 log-odds 加权融合**，不改变 8 态概率的核心来源（Phase 0 高斯中心软分配），参数范围输出采用「Level-Trend 纯连续函数」随时间自动滚动分位界定区间（方案 A）。

### 4.1 FeatureRegistry v4（5 模块 + schema 严格校验）

#### 4.1.1 ENABLED_SETS 新增

```python
ENABLED_SETS["btc_morphology_v4"]        = ["morphology_core","ma200_cycle","multi_timeframe","rolling_regime_stats"]
ENABLED_SETS["btc_morphology_v4_layer1"] = ["morphology_core","ma200_cycle","multi_timeframe","rolling_regime_stats","sector_beta_pool"]
```

| 模块 | 列数 | 作用 | 特征池归属 |
|---|---|---|---|
| morphology_core | ~20 | ADX/Hurst/BB宽/道氏 HHHL/Sperandeo 原子形态特征（已有） | LightGBM 校正器 ✅ |
| ma200_cycle | 10 | MA200 距离 3 列 + 纯价格周期 7 列（已有） | LightGBM 校正器 ✅ |
| multi_timeframe | 7 | MA 对齐/交叉/对数收益/波动率分位/量比（已有） | LightGBM 校正器 ✅ |
| rolling_regime_stats | 16 | 🆕 L/T 60d/252d 分位+熵 20d + 共识 20d 均值 + 量 zscore | **仅参数映射用**（**排除 LGBM 池** 防标签泄露） |
| sector_beta_pool | 15 | 🆕 5 板块 β(252d) + α(60d) + correl(60d) | **仅 Layer1 权重用**（排除 LGBM 池） |

#### 4.1.2 feature_schema.json 持久化（强制校验，防止经验 122221 尺度漂移）

`FeatureRegistry.build_feature_schema(set_name)` 输出：

```json
{
  "schema_version": "feature.v4",
  "set_name": "btc_morphology_v4",
  "feature_names_in_order": ["adx_14", "ma200_distance_pct", "..."],
  "groups": {
    "lgbm_pool":    ["morphology_core", "ma200_cycle", "multi_timeframe"],
    "range_mapper": ["rolling_regime_stats"],
    "sector_pool":  ["sector_beta_pool"]
  },
  "per_feature_scale_note": {
    "adx_14": "raw 0-100",
    "ma200_distance_pct": "% relative raw",
    "volume_zscore_252d": "z-score"
  }
}
```

**LGBM 推理入口必须加载 schema 并逐列比对**：列数不一致 / 列名不一致 / 顺序不一致 → 立即抛 `ValueError`。**禁止**静默 reindex 或 fillna 兜底。

---

### 4.2 LightGBM 概率校正器（`bcrm2/lgbm_calibrator.py`）

```python
class LGBMCalibrator:
    EPS = 1e-12
    REGIME_ORDER = REGIME_ORDER  # 与 regime_labeler.py 8 态顺序严格同一

    # 训练：X ∈ (形态三基础模块 lgbm_pool)；y = 自动生成的 8 态标签
    def fit(self, X: pd.DataFrame, y: pd.Series, schema_path=None):
        """LGBMClassifier(class_weight='balanced', num_leaves=31,
                          lambda_l2=0.5, min_data_in_leaf=80, verbose=-1)"""

    # 推理：log-odds 加权融合（w_gauss=0.6 / w_lgbm=0.4，Phase 3 可调）
    def calibrate(self, p_gauss: np.ndarray, X_lgbm_pool: pd.DataFrame) -> np.ndarray:
        """返回 (n, 8) 归一概率；单条/批量统一入口走 calibrate（=predict_proba）"""

    @staticmethod
    def log_odds_mix(p_gauss, p_lgbm, w_gauss=0.6, w_lgbm=0.4, temperature=0.6) -> np.ndarray:
```

**设计铁律**：
- 「融合」必须生效：`p_out` 对 `p_gauss` 的 JS 散度 ≥ 0.02（TDD T11）。
- 绝不输出硬分类：无 `predict()` 接口；只有 `calibrate()`。
- schema 不匹配 → 直接 `raise ValueError`（TDD T13）。

---

### 4.3 Level-Trend 纯连续参数映射（方案 A · `bcrm2/parameter_mapper.py`）

**核心设计原则**：**无硬查表；一切都是 Level/Trend/Consensus 三个连续量的 clip+线性函数**；区间带宽 = 历史滚动百分位宽度 × consensus 收窄系数，**随时间自动滚动更新 min/max 差值界定范围**（契合「数据驱动+量变引起质变」）。

```python
class ParameterMapper:
    DEFAULT_COEFFS = {
        # center = base + w_L*(L/4) + w_T*(T/4) + w_C*(C-0.5)
        # 输出所有范围 = [center × (1 - half_width), center × (1 + half_width)] ∩ clip
        "global_position_mult":  dict(base=1.0, w_L=+0.4, w_T=+0.2, w_C=+0.1, clip=[0.3, 1.6]),
        "ls_ratio_cap":          dict(base=0.5, w_L=+0.25,w_T=+0.15,w_C=0.0,  clip=[0.2, 1.0]),
        "long_bias":             dict(base=0.5, w_L=+0.2, w_T=+0.15,w_C=0.0,  clip=[0.0, 1.0]),
        "short_bias":            dict(base=0.5, w_L=-0.2, w_T=-0.15,w_C=0.0,  clip=[0.0, 1.0]),
        "long_threshold_mult":   dict(base=1.0, w_L=-0.1, w_T=-0.1, w_C=0.0,  clip=[0.6, 1.4]),
        "short_threshold_mult":  dict(base=1.0, w_L=+0.1, w_T=+0.1, w_C=0.0,  clip=[0.6, 1.4]),
        # 区间宽度：基础 ±12%；C=0 额外 ±12%；C=1 不放大
        "bandwidth_pct":                 0.12,
        "bandwidth_consensus_factor":    0.12,
    }

    # 6 个全局范围（Layer0 输出）
    def map_global_parameters(L, T, C, stats_row) -> dict[str, tuple[float, float]]:
        """返回 {global_position_mult: (lower, upper), ls_ratio_cap: (...), ... ×6}"""

    # 5 板块权重 Σ=1（Layer1 输出）
    def map_sector_weights(L, T, C, sector_betas) -> dict[str, float]:
        """score_s = clip(β_s*(1+α_s)) * (1 + 0.3*L/4 + 0.2*T/4); w_s = softmax(score_s / temp)"""
```

**单调性要求（TDD T12/T14/T15）**：
- 带宽：`C=1.0` 的 6 参数区间宽度 **必须 ≤** `C=0.0`。
- 仓位：`L=+4,T=+4` → global_position_mult 中心 ≥ 1.4；`L=-4,T=-4` → ≤ 0.5。
- 阈值：BTC 牛市时 long_threshold_mult ≤ 1.0（降低做多门槛）；熊市时 short_threshold_mult ≤ 1.0（降低做空门槛）。
- 板块权重：β=1.5 板块在 `L=+3` 时权重 ≥ β=0.5 板块 × 1.15 倍；5 板块权重 Σ ≡ 1（浮点误差 ≤1e-9）。

---

### 4.4 Phase 1 TDD 验收矩阵

| 测试 | 名称 | 通过标准 |
|---|---|---|
| T11 | `test_lgbm_calibrator_shape` | `p_out` 形状 (n,8) Σ=1；纯随机 X 场景下 `p_out` 对 `p_gauss` JS 散度 ≥ 0.02（融合确实生效，不被权重淹掉）|
| T12 | `test_parameter_mapper_ranges` | C=1 → 带宽 ≤ C=0 带宽；`L=+4,T=+4` → mult≥1.4；`L=-4,T=-4` → mult≤0.5（单调性 4 条）|
| T13 | `test_feature_schema_alignment` | 训练时存 schema → 推理时改列顺序 / 删列 / 列数不对 → 必须抛 `ValueError` |
| T14 | `test_sector_weights_sum_to_1` | 5 板块权重 Σ=1；β=1.5 板块权重 ÷ β=0.5 板块权重 ≥ 1.15（L=+3 场景）|
| (T15) | `test_btc_3_dates_parameter_direction`（可选）| ATH 69k → ls_ratio_cap ≥ 0.7；FTX Low → ls_ratio_cap ≤ 0.5；减半 → global_position_mult ≥ 1.15 |

---

### 4.A 原 Phase 1 LGBM 硬分类方案（已废弃，仅归档 · 2026-08-18 初版设计）

#### 4.A.1 8 态自动标签生成器（数据驱动）

放弃手工标注，参考 LucasLarese 4 态方法扩展到 8 态：

```python
# labels/regime_labeler.py

def generate_8state_label(df, forward_days=20, lookback=252):
    """
    数据驱动的 8态自动标签
    
    8 态定义（基于传统金融共识）:
      TREND_UP_STRONG:    trend > +median, ADX > 25        强多头趋势
      TREND_UP_MILD:      trend > +median, ADX 20-25      弱多头趋势
      RANGE_BOUND:         |trend| ≤ median, vol ≤ median  震荡市
      CONSOLIDATION:       |trend| ≤ median, vol < 25th pct 横盘压缩
      REVERSAL:            BOCPD changepoint > 0.5         形态反转
      VOLATILE_DROP:       trend < -median, vol > 75th pct 暴跌
      FOMO_RALLY:          trend > +2σ, vol > 75th pct     狂热上涨
      DISTRIBUTION:        trend < 0, ADX < 20, BB宽度>90th 派发形态
    """
    future_ret = df['close'].pct_change(forward_days).shift(-forward_days)
    trend = np.log(df['close'] / df['close'].shift(60))
    vol = df['close'].pct_change().rolling(20).std()
    adx = df['adx_14']
    bocpd_prob = df['bocpd_changepoint_prob']  # Phase 4 才有，Phase 1 用 0
    bb_width_pct = df['bb_width_percentile_252']
    
    trend_med = trend.rolling(lookback).median()
    vol_med = vol.rolling(lookback).median()
    vol_75 = vol.rolling(lookback).quantile(0.75)
    vol_25 = vol.rolling(lookback).quantile(0.25)
    trend_2sigma = trend.rolling(lookback).mean() + 2 * trend.rolling(lookback).std()
    
    labels = np.where(
        bocpd_prob > 0.5, 'REVERSAL',
        np.where(
            (trend > trend_2sigma) & (vol > vol_75), 'FOMO_RALLY',
            np.where(
                (trend < -trend_med.abs()) & (vol > vol_75), 'VOLATILE_DROP',
                np.where(
                    (trend < 0) & (adx < 20) & (bb_width_pct > 0.90), 'DISTRIBUTION',
                    np.where(
                        (trend > trend_med) & (adx > 25), 'TREND_UP_STRONG',
                        np.where(
                            (trend > trend_med) & (adx > 20) & (adx <= 25), 'TREND_UP_MILD',
                            np.where(
                                (abs(trend) <= trend_med.abs()) & (vol < vol_25), 'CONSOLIDATION',
                                'RANGE_BOUND'  # 默认兜底
                            )))))))
    return labels
```

### 4.2 RegimePredictor 类（继承 MarketRegimeClassifier）

```python
# regime_predictor.py

class RegimePredictor(MarketRegimeClassifier):
    """
    形态预测器（继承 BCRM 2.0 MarketRegimeClassifier）
    
    核心扩展:
    1. 特征权重机制（方差放大 ×2.5/×1.5/×1.0）
    2. BTC / 美股 enabled_feature_set 配置化
    3. 8 态自动标签生成（数据驱动）
    """
    
    FEATURE_WEIGHT_MORPHOLOGY = 2.5    # 形态核心组方差放大倍数
    FEATURE_WEIGHT_BREADTH = 1.5       # 市场广度组方差放大倍数
    FEATURE_WEIGHT_OTHER = 1.0         # 其他保留组
    
    def __init__(self, config_path="regime_predictor_config.json"):
        super().__init__()
        self.config = self._load_config(config_path)
        self.feature_groups = self._parse_feature_groups()
        
    def fit(self, X, y, feature_names=None):
        """
        训练形态预测器
        
        关键步骤:
        1. 按特征组应用方差放大
        2. 调用父类 fit（LGBM 多分类）
        3. 输出 feature_importance 排序
        """
        X_scaled = self._apply_feature_weights(X)
        super().fit(X_scaled, y, feature_names)
        self._log_feature_importance()
        
    def predict(self, X):
        """预测形态，返回 (regime_label, confidence, proba_dict)"""
        X_scaled = self._apply_feature_weights(X)
        proba = self.model.predict_proba(X_scaled)
        regime_idx = np.argmax(proba, axis=1)
        confidence = np.max(proba, axis=1)
        return self._idx_to_label(regime_idx), confidence, proba
        
    def _apply_feature_weights(self, X):
        """按特征组应用方差放大"""
        X_scaled = X.copy()
        morph_cols = self.feature_groups['morphology']
        breadth_cols = self.feature_groups['breadth']
        X_scaled[:, morph_cols] *= self.FEATURE_WEIGHT_MORPHOLOGY
        X_scaled[:, breadth_cols] *= self.FEATURE_WEIGHT_BREADTH
        return X_scaled
```

### 4.3 训练脚本

```python
# scripts/train_btc_regime_predictor.py

def main():
    # 1. 获取 BTC 日线数据（OKX API，5 年）
    closes = fetch_btc_daily_closes(limit=1825)  # 5 年日线
    
    # 2. 计算所有特征（Phase 0 新增的 12 个 + 现有）
    features = feature_registry.compute_all(
        closes, 
        enabled_set="btc_morphology"  # 配置化的特征启用集
    )
    
    # 3. 生成 8 态标签
    labels = generate_8state_label(features)
    
    # 4. WalkForward 5 折训练
    wf = WalkForwardBacktester(n_splits=5, gap=20)  # gap=20 防泄露
    results = wf.run(
        features=features,
        labels=labels,
        model=RegimePredictor(),
        metrics=['macro_f1', 'balanced_accuracy', 'confusion_matrix']
    )
    
    # 5. 输出评估
    print(f"Macro F1: {results['macro_f1']:.4f}")
    print(f"Balanced Accuracy: {results['balanced_accuracy']:.4f}")
    print(f"Confusion Matrix:\n{results['confusion_matrix']}")
    
    # 6. 检查各类别样本数
    for label, count in zip(*np.unique(labels, return_counts=True)):
        if count < 50:
            print(f"WARN: 标签 {label} 样本数 {count} < 50，可能类别稀缺")
    
    # 7. 保存模型
    predictor.save("models/btc_regime_predictor_v1.pkl")
```

### 4.4 TDD 测试矩阵

| 测试 | 验证内容 | 通过标准 |
|------|---------|---------|
| `test_8state_labeler_distribution` | 8 态标签分布 | 每态样本数 ≥ 50（5 年日线） |
| `test_8state_labeler_correctness` | 已知趋势期标签 | 2024 牛市 → TREND_UP_STRONG |
| `test_regime_predictor_fit_predict` | 训练 + 预测 | 输出 8 态之一 + 置信度 [0,1] |
| `test_feature_weights_applied` | 方差放大生效 | 形态组方差 > 原始 ×2.0 |
| `test_walk_forward_no_leakage` | 无未来函数泄露 | 训练集与测试集时间不重叠 |
| `test_macro_f1_threshold` | Macro F1 ≥ 0.55 | 5 折平均 |
| `test_balanced_accuracy_threshold` | Balanced Accuracy ≥ 0.65 | 5 折平均 |
| `test_confusion_adjacent_tolerance` | 相邻态容错 | 容错后准确率 ≥ 0.75 |

---

## 5. Phase 2: 前置形态层接入 BTC（开关 S5）

### 5.1 仓位/止盈止损/阈值调节器

```python
# polling_trader.py 新增

class PollingTrader:
    # 开关 S5
    enable_regime_predictor: bool = True
    
    # Regime → 仓位乘数 / 止盈乘数 / 止损乘数 / 阈值乘数
    REGIME_MULTIPLIERS = {
        # regime: (position_mult, tp_mult, sl_mult, threshold_mult)
        "TREND_UP_STRONG":    (1.20, 1.30, 0.90, 0.85),  # 顺势加仓，止盈放宽，止损收紧，阈值放宽
        "TREND_UP_MILD":      (1.10, 1.15, 0.95, 0.90),
        "RANGE_BOUND":        (0.80, 0.85, 1.00, 1.00),  # 震荡减仓，止盈收紧
        "CONSOLIDATION":      (0.60, 0.70, 1.10, 1.10),  # 压缩期轻仓
        "REVERSAL":           (0.50, 0.80, 1.20, 1.20),  # 反转期极轻仓
        "VOLATILE_DROP":      (0.40, 1.50, 1.30, 1.30),  # 暴跌极轻仓，止盈放宽等反弹
        "FOMO_RALLY":         (0.70, 0.60, 1.40, 1.25),  # 狂热减仓，止盈极紧
        "DISTRIBUTION":       (0.50, 0.75, 1.15, 1.15),  # 派发轻仓
    }
    
    def _get_regime_pred_multipliers(self, coin: str) -> dict:
        """
        获取形态预测器的调节乘数
        
        返回: {"position": x, "tp": y, "sl": z, "threshold": w}
        """
        if not self.enable_regime_predictor:
            return {"position": 1.0, "tp": 1.0, "sl": 1.0, "threshold": 1.0}
        
        # 1. 获取 BTC 日线形态预测（缓存 1 天）
        regime = self._predict_btc_daily_regime()
        
        # 2. 查表
        multipliers = self.REGIME_MULTIPLIERS.get(
            regime, 
            {"position": 1.0, "tp": 1.0, "sl": 1.0, "threshold": 1.0}
        )
        
        self._log(f"regime_pred regime={regime} multipliers={multipliers}")
        return multipliers
    
    def _predict_btc_daily_regime(self) -> str:
        """预测 BTC 日线形态（缓存 24h）"""
        cache_key = "btc_daily_regime"
        if self._is_cache_valid(cache_key, ttl=86400):
            return self._cache[cache_key]
        
        # 1. 获取 BTC 日线 closes
        btc_closes = self._fetch_btc_daily_closes(limit=300)
        
        # 2. 计算特征
        features = self.feature_registry.compute_all(
            btc_closes, enabled_set="btc_morphology"
        )
        
        # 3. 加载模型预测
        regime, confidence, _ = self.regime_predictor.predict(features)
        
        # 4. 缓存
        self._cache[cache_key] = regime
        self._cache_ts[cache_key] = time.time()
        
        return regime
```

### 5.2 集成到现有交易流程

```python
# _execute_trade 中新增（开关 S5）

def _execute_trade(self, coin, signal):
    # ... 现有逻辑 ...
    
    if self.enable_regime_predictor:
        multipliers = self._get_regime_pred_multipliers(coin)
        
        # 1. 仓位调节
        position_size = base_position_size * multipliers["position"]
        
        # 2. 止盈止损调节
        take_profit = base_take_profit * multipliers["tp"]
        stop_loss = base_stop_loss * multipliers["sl"]
        
        # 3. 开仓阈值调节（与弹簧力场后置层叠加）
        final_threshold = (
            self.short_confidence_threshold  # 基础 0.80
            * self._get_regime_short_multiplier(regime_score)  # 弹簧力场后置层
            * multipliers["threshold"]  # 形态预测前置层
        )
        
        self._log(f"regime_pred applied: pos={position_size} tp={take_profit} "
                  f"sl={stop_loss} threshold={final_threshold}")
    else:
        # 开关关闭：走旧路径（无 regime 乘数）
        position_size = base_position_size
        take_profit = base_take_profit
        stop_loss = base_stop_loss
        final_threshold = self.short_confidence_threshold * self._get_regime_short_multiplier(regime_score)
```

### 5.3 TDD 测试矩阵

| 测试 | 验证内容 | 通过标准 |
|------|---------|---------|
| `test_s5_off_equivalent_to_baseline` | 开关关闭时行为 | 字节等价旧路径 |
| `test_s5_on_applies_multipliers` | 开关打开时乘数应用 | position/tp/sl/threshold 都乘了 regime 乘数 |
| `test_regime_cache_24h` | 形态预测缓存 | 24h 内不重新预测 |
| `test_trend_up_strong_increases_position` | TREND_UP_STRONG 时 | position > base |
| `test_volatile_drop_decreases_position` | VOLATILE_DROP 时 | position < base × 0.5 |
| `test_fomo_rally_tightens_tp` | FOMO_RALLY 时 | tp < base × 0.7 |
| `test_layered_thresholds` | 前置层 × 后置层 | final = base × spring × regime_pred |

---

## 6. Phase 3: 美股形态预测器（独立策略）

### 6.1 美股数据源（Yahoo Finance）

```python
# datafeeds/us_stock_feed.py

import yfinance as yf

class USStockFeed:
    def fetch_daily_closes(self, symbol="^GSPC", period="5y"):
        """
        获取美股日线数据
        symbol: ^GSPC (S&P 500) / ^IXIC (Nasdaq) / ^DJI (Dow Jones)
        """
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        closes = df['Close'].values.tolist()
        # newest-first（与 OKX 一致）
        closes = closes[::-1]
        return closes
```

### 6.2 美股专用特征配置

```json
// regime_predictor_config.json
{
  "us_stock_morphology": {
    "enabled_features": {
      "BaguaFeatureEngine": true,
      "ClassicExperienceFeatures": true,
      "WDHFeatures": true,
      "CycleFeatures": ["distance_to_ath"],  // 只保留距 ATH 距离
      "MerrillClockFeatures": true,
      "MacroFeatures": false,  // 关闭加密专属
      "CrossAssetFeatures": false,
      "MarketCap": false,
      "RSISentimentFeatures": true,
      "PivotPoint": true,
      "Fibonacci": true,
      "MetaLabelingFeatures": false,
      "MorphologyFeatures": true,  // Phase 0 新增的 ADX/Hurst/BB/60日高
      "BreadthFeatures": "us_stock_breadth"  // 美股广度（VIX/A-D Line）
    }
  },
  "btc_morphology": {
    "enabled_features": {
      // ... BTC 配置（启用加密专属特征）
    }
  }
}
```

### 6.3 美股独立交易策略

```python
# polling_trader_us.py

class USStockTrader:
    """
    美股独立交易策略
    - 基于 8 态形态预测驱动多空信号
    - 不依赖 BCRM 2.0（BTC 1H 方向预测）
    - 形态 + 简单方向规则 = 信号
    """
    
    def generate_signal(self, regime: str, confidence: float) -> dict:
        """
        形态 → 多空信号映射
        
        规则:
          TREND_UP_STRONG + confidence > 0.7 → 做多
          TREND_UP_MILD + confidence > 0.8 → 做多
          RANGE_BOUND → 观望
          CONSOLIDATION → 观望
          REVERSAL → 观望
          VOLATILE_DROP → 做空（如有做空能力）
          FOMO_RALLY → 观望（不追高）
          DISTRIBUTION → 做空
        """
        # ... 信号生成逻辑 ...
```

### 6.4 TDD 测试矩阵

| 测试 | 验证内容 | 通过标准 |
|------|---------|---------|
| `test_us_stock_data_fetch` | Yahoo Finance 数据拉取 | 5 年日线数据完整 |
| `test_us_stock_feature_compute` | 美股特征计算 | 12 个形态特征都有值 |
| `test_us_stock_regime_labeler` | 美股 8 态标签 | 每态样本数 ≥ 30 |
| `test_us_stock_macro_f1` | 美股形态预测准确率 | Macro F1 ≥ 0.50 |
| `test_us_stock_strategy_backtest` | 美股独立回测 | Sharpe ≥ 0.8 |

---

## 7. Phase 4（可选）: BOCPD + HMM 集成

### 7.1 BOCPD 在线变点检测

```python
# features/bocpd.py

class BOCPD:
    """
    Bayesian Online Changepoint Detection (Adams & MacKay 2007)
    
    输出: changepoint_prob (0-1)
    形态语义: > 0.5 → 形态切换预警
    """
    
    def __init__(self, hazard=0.01, observation_model=None):
        self.hazard = hazard  # 默认 hazard function
        self.observation_model = observation_model or GaussianModel()
        
    def update(self, x):
        """在线更新，返回当前时点的变点概率"""
        # ... Adams-MacKay 算法实现 ...
        return changepoint_prob
```

### 7.2 HMM 时序状态建模

```python
# models/hmm_regime.py

from hmmlearn.hmm import GaussianHMM

class HMMRegime:
    """
    8 态 HMM 模型
    
    优势:
    1. 建模状态转移概率（"形态切换"）
    2. 建模状态持续期（RANGE_BOUND 平均持续 N 天）
    3. 与 LGBM 集成：LGBM 提供特征判别，HMM 提供时序先验
    """
    
    def __init__(self, n_states=8):
        self.model = GaussianHMM(
            n_components=n_states,
            covariance_type="diag",
            n_iter=100
        )
        
    def fit(self, X, lengths=None):
        """训练 HMM"""
        self.model.fit(X, lengths=lengths)
        # 输出转移矩阵可视化
        self._plot_transition_matrix()
        
    def predict_proba(self, X):
        """返回 8 态概率"""
        return self.model.predict_proba(X)
```

### 7.3 LGBM + HMM 集成

```python
# regime_predictor.py 扩展

class RegimePredictor:
    def predict_with_ensemble(self, X_lgbm, X_hmm):
        """
        LGBM + HMM 集成预测
        
        final_prob = α × P_LGBM + (1-α) × P_HMM
        α = 0.7（LGBM 主导，可通过 WalkForward 调参）
        """
        if not self.enable_bocpd_hmm:
            return self.predict(X_lgbm)  # 降级为纯 LGBM
        
        p_lgbm = self.lgbm_model.predict_proba(X_lgbm)
        p_hmm = self.hmm_model.predict_proba(X_hmm)
        alpha = 0.7
        final_prob = alpha * p_lgbm + (1 - alpha) * p_hmm
        regime_idx = np.argmax(final_prob, axis=1)
        return self._idx_to_label(regime_idx), np.max(final_prob, axis=1), final_prob
```

### 7.4 TDD 测试矩阵

| 测试 | 验证内容 | 通过标准 |
|------|---------|---------|
| `test_bocpd_detects_trend_change` | BOCPD 检测趋势切换 | changepoint_prob > 0.5 提前 ≥ 3 日 |
| `test_hmm_transition_matrix` | HMM 转移矩阵 | 对角线 > 0.5（状态持续） |
| `test_ensemble_macro_f1` | 集成后 Macro F1 | ≥ 0.65（比纯 LGBM 提升 0.10） |
| `test_s6_off_equivalent_lgbm` | 开关 S6 关闭 | 等价纯 LGBM |

---

## 8. Phase 5（可选）: 外部数据源

### 8.1 CoinGecko（USDT 市值 / BTC.D）

```python
# datafeeds/coingecko_feed.py

class CoinGeckoFeed:
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    def fetch_usdt_market_cap(self):
        """获取 USDT 总市值"""
        # GET /coins/tether?field=market_data.market_cap.usd
        
    def fetch_btc_dominance(self):
        """获取 BTC 市占率"""
        # GET /global → data.market_cap_percentage.btc
```

### 8.2 宏观指标（VIX / A-D Line）

```python
# datafeeds/macro_feed.py

class MacroFeed:
    def fetch_vix(self):
        """获取 VIX 恐慌指数"""
        # Yahoo Finance: ^VIX
        
    def fetch_advance_decline_line(self):
        """获取 NYSE 涨跌线"""
        # 需付费数据源（如 Stooq 或 FRED）
```

### 8.3 TDD 测试矩阵

| 测试 | 验证内容 | 通过标准 |
|------|---------|---------|
| `test_coingecko_api` | CoinGecko API 调用 | 返回 USDT 市值 |
| `test_vix_fetch` | VIX 数据拉取 | 返回 0-100 数值 |
| `test_external_data_improves_f1` | 外部数据提升 F1 | Macro F1 提升 ≥ 3% |

---

## 9. 评估指标体系

### 9.1 形态预测质量（主指标）

| 指标 | Phase 1 目标 | Phase 4 目标 | 来源 |
|------|-------------|-------------|------|
| **Macro F1 Score**（主） | ≥ 0.55 | ≥ 0.65 | LucasLarese |
| **Balanced Accuracy** | ≥ 0.65 | ≥ 0.75 | LucasLarese |
| **混淆矩阵相邻态容错率** | ≥ 0.75 | ≥ 0.85 | 行业共识 |
| **各类别样本数** | ≥ 50 | ≥ 50 | 类别平衡 |

### 9.2 形态→PnL 区分度

| 指标 | 目标 |
|------|------|
| FOMO_RALLY 做多 PnL / VOLATILE_DROP 做多 PnL | ≥ 1.5（形态有区分度） |
| TREND_UP_STRONG 做多 PnL / RANGE_BOUND 做多 PnL | ≥ 1.3 |
| CONSOLIDATION 后突破成功率 | ≥ 60% |

### 9.3 前置层价值验证

| 指标 | 目标 |
|------|------|
| 回测 PnL（开关 S5 开）vs PnL（S5 关） | ≥ 95%（不显著降低） |
| Sharpe Ratio 提升 | ≥ 15% |
| 最大回撤下降 | ≥ 10% |
| BOCPD 提前量（Phase 4） | ≥ 3 日 |

---

## 10. 分层形态预测与资金分配体系（核心扩展）

> 本节是本 spec 相对初始方案的核心设计扩展：从"单一 BTC 形态"升级为"全局形态 + 板块龙头形态"的双层预测体系，
> 并新增多空偏置范围化、多空持仓比上限、阈值范围偏置、板块资金权重分配 4 个核心机制。

### 10.1 Layer 0：全局 BTC 形态 → 5 个全局调节参数

全局 BTC 形态预测的 8 态结果映射为**5 个全局调节参数**，其中 4 个设计为**范围**而非单点值，便于后置弹簧力层回测针对性调节：

#### 10.1.1 多空偏置范围（long_bias_range / short_bias_range）

**设计意图**：根据整体市场形态决定"允许做多/做空的倾向程度"。偏置是 multiplicative 的置信度因子。

```python
# 8 态 → 多空偏置范围 [min, max]
GLOBAL_LS_BIAS_RANGES = {
    # regime: (long_bias_min, long_bias_max, short_bias_min, short_bias_max)
    "TREND_UP_STRONG":    (1.15, 1.30, 0.20, 0.50),  # 强牛市：做多偏置，做空压制
    "TREND_UP_MILD":      (1.10, 1.20, 0.30, 0.60),  # 弱牛市：温和做多偏置
    "RANGE_BOUND":        (0.90, 1.10, 0.90, 1.10),  # 震荡：多空中性
    "CONSOLIDATION":      (0.85, 1.00, 0.85, 1.00),  # 压缩：略微保守
    "REVERSAL":           (0.50, 0.90, 0.50, 0.90),  # 反转：两端都压制
    "VOLATILE_DROP":      (0.30, 0.50, 1.15, 1.30),  # 暴跌：做空偏置，做多压制
    "FOMO_RALLY":         (0.80, 1.00, 0.80, 1.00),  # 狂热：追高风险高，两端都略压制
    "DISTRIBUTION":       (0.40, 0.70, 1.10, 1.25),  # 派发：做空偏置，做多压制
}
```

**与核心层的集成方式**：
```
最终做多 confidence ≧ long_threshold_range * (1 / long_bias)
最终做空 confidence ≧ short_threshold_range * (1 / short_bias)
```

- 牛市 TREND_UP_STRONG：long_bias = 1.22（中间值），相当于**降低做多阈值**（更容易开多），short_bias = 0.35 → **空头阈值被乘 2.86，几乎禁止做空**
- 熊市 VOLATILE_DROP：short_bias = 1.22 → **降低做空阈值**（更容易开空），long_bias = 0.40 → **多头阈值被乘 2.5，几乎禁止做多**
- 范围 [min, max] 提供弹性：后置弹簧力场回测后，可在该范围内选定最优值（如牛市做空偏置选 0.20 或 0.50）

#### 10.1.2 多空持仓比上限（ls_ratio_cap_range）

**设计意图**：当多空持仓比超过该上限时，禁止新开反向仓。极端市场形态下，用持仓比而非阈值+偏置的**硬限制**兜底。

```python
# 8 态 → 多空持仓比范围 [min_cap, max_cap]
# ls_ratio = abs(short_positions_total_usd) / max(long_positions_total_usd, 1)
# 牛市：ls_ratio_cap 极低（几乎禁止空头开新仓）
# 熊市：ls_ratio_cap 高（允许空头大于多头 2 倍）
GLOBAL_LS_RATIO_CAP_RANGES = {
    "TREND_UP_STRONG":    (0.05, 0.15),  # 强牛市：空头仓位 ≤ 多头的 5%-15%
    "TREND_UP_MILD":      (0.15, 0.40),  # 弱牛市：空头 ≤ 15%-40%
    "RANGE_BOUND":        (0.80, 1.50),  # 震荡：多空基本平衡 80%-150%
    "CONSOLIDATION":      (0.70, 1.20),  # 压缩：略倾向平衡
    "REVERSAL":           (0.40, 0.80),  # 反转：不确定，禁止极端失衡
    "VOLATILE_DROP":      (1.50, 2.00),  # 暴跌：允许空头 > 多头 1.5-2.0 倍
    "FOMO_RALLY":         (0.30, 0.80),  # 狂热：追高风险，限制空头
    "DISTRIBUTION":       (1.20, 1.80),  # 派发：空头可以大于多头
}
```

**执行语义**：
```
每次请求开新仓时，先计算当前全局 ls_ratio
若 ls_ratio > ls_ratio_cap AND 新仓方向会扩大失衡 → 拒绝开仓
```

例：TREND_UP_STRONG 形态，当前多头持仓 10000 U，空头持仓 800 U → ls_ratio = 0.08（处于 0.05-0.15 范围内），允许继续开空头直到 ls_ratio ≥ 0.05-0.15 的上限（如选 0.15，则空头最多开 1500 U）。

#### 10.1.3 阈值范围偏置（long_threshold_range_mult / short_threshold_range_mult）

**设计意图**：按市场形态对基础多空阈值（0.80）进行 multiplicative 调节，同样设计为范围。

**核心场景说明**（来自用户输入的典型用例）：

| 市场场景 | 对应 8 态 | 阈值调节逻辑 | 范围设计理由 |
|---------|----------|------------|------------|
| **牛市确认（早期）** | TREND_UP_STRONG | 多头阈值**降低**（更容易开多），空头阈值**大幅升高**（几乎禁止做空） | 牛市初期趋势明确，范围 [0.80, 0.95] 给多头降 5%-20% 阈值；空头 [1.10, 1.30] 升 10%-30%，配合 short_bias 几乎封死空头 |
| **牛市末期（狂热/派发）** | FOMO_RALLY / DISTRIBUTION | **多空阈值都大幅调高**（两端都要更高置信度才开仓） | 牛市末期形态不确定，随时可能反转。范围 [1.15, 1.35] = 阈值要求提高 15%-35%，防止在顶部反复开仓 |
| **熊市确认（暴跌）** | VOLATILE_DROP | 空头阈值**降低**（更容易开空），多头阈值**大幅升高**（几乎禁止做多） | 暴跌趋势明确，空头 [0.75, 0.95] 降 5%-25%；多头 [1.20, 1.40] 升 20%-40%，配合 long_bias 封死多头 |
| **反转/形态不确定** | REVERSAL | **多空阈值都调高**（两端都严格） | 反转期方向不明，避免假突破。范围 [1.10, 1.30] = 提高 10%-30%，等待方向确认 |
| **压缩期（等方向）** | CONSOLIDATION | **多空阈值略调高**（两端略严） | 压缩期即将突破，但方向未知。范围 [1.00, 1.10] = 略严 0%-10%，防止假突破被洗 |
| **震荡市（中性）** | RANGE_BOUND | **多空阈值中性**（不调节） | 震荡市多空都有机会，范围 [0.95, 1.05] ≈ 中性，靠弹簧力场后置层和 BCRM 2.0 方向预测主导 |

```python
# threshold_mult = [min_mult, max_mult]
# 最终阈值 = base_threshold × threshold_mult × spring_force_multiplier × (1/bias)
GLOBAL_THRESHOLD_RANGES = {
    # regime: (long_th_min, long_th_max, short_th_min, short_th_max)
    "TREND_UP_STRONG":    (0.80, 0.95, 1.10, 1.30),  # 牛市：多头阈值降，空头阈值升
    "TREND_UP_MILD":      (0.85, 1.00, 1.05, 1.20),  # 弱牛市：温和调节
    "RANGE_BOUND":        (0.95, 1.05, 0.95, 1.05),  # 震荡：中性
    "CONSOLIDATION":      (1.00, 1.10, 1.00, 1.10),  # 压缩：两端都略严（等待方向）
    "REVERSAL":           (1.10, 1.30, 1.10, 1.30),  # 反转：都严格（形态不确定）
    "VOLATILE_DROP":      (1.20, 1.40, 0.75, 0.95),  # 暴跌：多头极严，空头降
    "FOMO_RALLY":         (1.15, 1.35, 1.15, 1.35),  # 狂热：追高风险高，两端都严
    "DISTRIBUTION":       (1.15, 1.35, 0.85, 1.00),  # 派发：多头严，空头温和降
}
```

**范围值的弹簧力场调节方式**：
以上范围不是固定值，后期通过弹簧力场回测可针对性调节。例如：
- 发现牛市 TREND_UP_STRONG 下，空头阈值 1.30 仍然有空头信号（但胜率低）→ 可将 max 从 1.30 调到 1.40（更严格封死空头）
- 发现熊市 VOLATILE_DROP 下，空头阈值 0.75 过于宽松（信号太多胜率反而低）→ 可将 min 从 0.75 调到 0.85
- 所有调节通过贝叶斯优化 + 回测验证，不依赖人工猜测

#### 10.1.4 全局仓位乘数（global_position_mult_range）

```python
GLOBAL_POSITION_MULT_RANGES = {
    "TREND_UP_STRONG":    (1.10, 1.30),  # 牛市：加仓
    "TREND_UP_MILD":      (1.00, 1.15),  # 弱牛市：温和加
    "RANGE_BOUND":        (0.80, 1.00),  # 震荡：降仓
    "CONSOLIDATION":      (0.60, 0.85),  # 压缩：轻仓等待
    "REVERSAL":           (0.40, 0.70),  # 反转：极轻
    "VOLATILE_DROP":      (0.30, 0.55),  # 暴跌：极轻仓（风险最高）
    "FOMO_RALLY":         (0.50, 0.80),  # 狂热：减仓（顶点风险）
    "DISTRIBUTION":       (0.40, 0.70),  # 派发：减仓
}
```

#### 10.1.5 全局止盈止损乘数范围（global_tp_mult_range / global_sl_mult_range）

**设计意图**：与仓位乘数对齐，止盈止损也设计为范围，便于后置回测针对性调节。

```python
# 全局止盈乘数范围 [min, max]
GLOBAL_TP_MULT_RANGES = {
    "TREND_UP_STRONG":    (1.15, 1.35),  # 牛市：止盈放宽（让利润奔跑）
    "TREND_UP_MILD":      (1.05, 1.20),  # 弱牛市：温和放宽
    "RANGE_BOUND":        (0.80, 0.95),  # 震荡：止盈收紧（快速获利）
    "CONSOLIDATION":      (0.65, 0.80),  # 压缩：止盈极紧（小波动快出）
    "REVERSAL":           (0.70, 0.90),  # 反转：快止盈
    "VOLATILE_DROP":      (1.20, 1.60),  # 暴跌：止盈放宽等反弹
    "FOMO_RALLY":         (0.55, 0.70),  # 狂热：止盈极紧（不追高）
    "DISTRIBUTION":       (0.70, 0.85),  # 派发：止盈紧
}

# 全局止损乘数范围 [min, max]
GLOBAL_SL_MULT_RANGES = {
    "TREND_UP_STRONG":    (0.80, 0.95),  # 牛市：止损收紧（顺势，假突破少）
    "TREND_UP_MILD":      (0.90, 1.00),  # 弱牛市：温和收紧
    "RANGE_BOUND":        (0.95, 1.10),  # 震荡：中性略宽
    "CONSOLIDATION":      (1.05, 1.20),  # 压缩：止损放宽（假突破多）
    "REVERSAL":           (1.10, 1.30),  # 反转：止损放宽防割肉
    "VOLATILE_DROP":      (1.20, 1.45),  # 暴跌：止损极宽（波动大）
    "FOMO_RALLY":         (1.25, 1.50),  # 狂热：止损极宽（随时反转）
    "DISTRIBUTION":       (1.10, 1.25),  # 派发：止损宽
}
```

### 10.2 Layer 1：板块龙头形态 → 资产类别偏置（板块资金权重 + 板块级止盈止损乘数）

#### 10.2.0 设计意图与完整链路

**为什么需要板块龙头？**
单一 BTC 形态只能判断"整体市场牛熊"，无法回答"哪个板块更强、该给哪个板块更多资金"。例如：
- 2025 年 HYP 等 AI 币强势 → **AI-Web3 板块形态为 TREND_UP_STRONG** → 该板块资金权重从基础 0.20 提高到 0.30+
- DeFi 板块同步走强 → **DeFi 板块 TREND_UP_MILD** → 权重提高到 0.25
- MEME 板块震荡 → 权重维持 0.20
- RWA/L2 偏弱 → 权重降至 0.10-0.15

**资产类别偏置的完整链路**（4 步闭环）：

```
步骤1：板块龙头形态识别（每板块 4 个龙头币日线合成）
  └─ 例：AI-Web3 板块 FET/AGIX/RNDR/AR 四个龙头
       → 计算 8 币广度特征 + 板块间相对强度特征
       → 预测为 TREND_UP_STRONG（置信度 0.78）

步骤2：板块形态 → 板块基础权重乘数
  └─ TREND_UP_STRONG → mult = 1.50（SECTOR_REGIME_BASE_WEIGHT）
     RANGE_BOUND     → mult = 0.90
     VOLATILE_DROP   → mult = 0.30

步骤3：5 板块 raw_weight 归一化（保证总和 = 1.0）
  └─ 例：
     AI-Web3:  0.20 × 1.50 = 0.30  → 归一化后 0.33
     DeFi:     0.20 × 1.20 = 0.24  → 归一化后 0.26
     MEME:     0.20 × 0.90 = 0.18  → 归一化后 0.20
     L2:       0.20 × 0.70 = 0.14  → 归一化后 0.15
     RWA:      0.20 × 0.50 = 0.10  → 归一化后 0.06
     ─────────────────────────────────────────────
     Σ raw = 0.96 → Σ 归一化后 = 1.00

步骤4：板块资金权重 → 核心层币种选择加成 + 板块仓位容量
  └─ 核心层 BCRM 2.0 选币时：
     - AI-Web3 板块币种 confidence × (0.33 / 0.20) = ×1.65（排序优先级提高）
     - RWA 板块币种 confidence × (0.06 / 0.20) = ×0.30（排序优先级降低）
     - 板块目标仓位 = 总可分配仓位 × sector_weight
       → AI-Web3 板块可持仓 1-2 单，RWA 板块最多 0 单
```

**关键原则**：
1. **龙头代表板块，而非单一币种**：FET 涨 ≠ 只买 FET，而是 AI-Web3 整个板块权重提高 → 核心层在该板块内选最强的币（可能是 FET 也可能是 HYP/NEURO 等新币）
2. **仓位的意义不是单一币种**：是"板块 × 币种"的二维分配——先决定给 DeFi/AI 板块多少钱，再在板块内选币
3. **板块龙头配置化**：龙头列表可随时增删改（如新增 HYP 到 AI-Web3 板块），不影响训练管线
4. **板块权重上限兜底**：单板块权重最高 0.40（`sector_weight_max_cap`），防止 ALL IN 一个板块

#### 10.2.1 加密板块定义与龙头列表

```python
CRYPTO_SECTORS = {
    "DeFi": {
        "leaders": ["UNI", "AAVE", "COMP", "LINK"],
        "description": "去中心化金融（DEX/借贷/预言机）",
    },
    "AI-Web3": {
        "leaders": ["FET", "AGIX", "RNDR", "AR"],
        "description": "AI + Web3（AI代币/渲染/存储）",
    },
    "RWA": {
        "leaders": ["ONDO", "SYN", "PROP", "TRAC"],
        "description": "真实世界资产（证券代币化/地产/供应链）",
    },
    "MEME": {
        "leaders": ["PEPE", "DOGE", "SHIB", "WIF"],
        "description": "MEME 币（情绪驱动）",
    },
    "L2": {
        "leaders": ["OP", "ARB", "STRK", "IMX"],
        "description": "Layer 2 （Rollup/zkEVM）",
    },
}
```

> 注：龙头币列表是**配置化**的（`regime_predictor_config.json` 中可调整），随着市场变化可新增/替换龙头。

#### 10.2.2 美股板块定义与 ETF 龙头

```python
US_STOCK_SECTORS = {
    "Tech": {
        "etfs": ["XLK", "QQQ"],  # 科技 ETF
        "stocks": ["AAPL", "MSFT", "NVDA", "META"],
        "description": "科技",
    },
    "Finance": {
        "etfs": ["XLF"],
        "stocks": ["JPM", "BAC", "GS", "MS"],
        "description": "金融",
    },
    "Energy": {
        "etfs": ["XLE"],
        "stocks": ["XOM", "CVX", "COP", "SLB"],
        "description": "能源",
    },
    "Healthcare": {
        "etfs": ["XLV"],
        "stocks": ["JNJ", "UNH", "PFE", "ABBV"],
        "description": "医药",
    },
    "Consumer": {
        "etfs": ["XLY", "XLP"],
        "stocks": ["AMZN", "TSLA", "HD", "WMT"],
        "description": "消费",
    },
}
```

#### 10.2.3 板块形态预测 → 板块资金权重

**每个板块独立训练一个 8 态形态预测器**（特征为该板块 4 个龙头的日线数据合成），然后用板块形态 → 板块资金权重映射：

```python
# 单个板块的"形态 → 基础权重"映射
SECTOR_REGIME_BASE_WEIGHT = {
    "TREND_UP_STRONG":    1.50,   # 板块强势牛市：大幅提高资金权重
    "TREND_UP_MILD":      1.20,   # 板块温和牛市：提高权重
    "RANGE_BOUND":        0.90,   # 板块震荡：标准权重
    "CONSOLIDATION":      0.70,   # 板块压缩：降权
    "REVERSAL":           0.50,   # 板块反转：大幅降权
    "VOLATILE_DROP":      0.30,   # 板块暴跌：极轻仓
    "FOMO_RALLY":         0.80,   # 板块狂热：降低（顶点风险）
    "DISTRIBUTION":       0.40,   # 板块派发：大幅降权
}

# 最终板块资金权重
def compute_sector_weight(sector_regime: str, base_allocation: float = 0.20) -> float:
    """
    base_allocation: 基础平均分配权重（5 板块 = 0.20）
    """
    base_mult = SECTOR_REGIME_BASE_WEIGHT[sector_regime]
    raw_weight = base_allocation * base_mult
    # 归一化：所有板块 raw_weight 求和后再 normalize，保证总和 = 1.0
    return raw_weight
```

**归一化保证**：5 个板块 raw_weight 总和为 S，实际权重 = raw_weight / S，确保总资金分配 100%。

#### 10.2.4 板块级止盈止损乘数

```python
SECTOR_REGIME_TP_SL_MULT = {
    # regime: (tp_mult, sl_mult)
    "TREND_UP_STRONG":    (1.30, 0.85),  # 板块强趋势：止盈放宽，止损收紧
    "TREND_UP_MILD":      (1.15, 0.95),  # 温和趋势：温和放宽/收紧
    "RANGE_BOUND":        (0.85, 1.00),  # 震荡：止盈收紧（快速获利）
    "CONSOLIDATION":      (0.75, 1.05),  # 压缩：止盈极紧（小波动快出）
    "REVERSAL":           (0.80, 1.20),  # 反转：快止盈，给空间
    "VOLATILE_DROP":      (1.50, 1.30),  # 暴跌：止盈放宽等反弹，止损放宽防割
    "FOMO_RALLY":         (0.60, 1.40),  # 狂热：止盈极紧（不追高）
    "DISTRIBUTION":       (0.75, 1.15),  # 派发：止盈紧
}
```

### 10.3 板块间广度特征（新增 ~5 个特征，Layer 1 形态预测专用）

为了增强板块形态预测，新增**板块间相对强弱特征**：

| 特征 | 计算方式 | 形态语义 |
|------|---------|---------|
| `sector_relative_strength_30d` | 板块等权 30 日收益 / BTC 30 日收益（相对 BTC 的 α） | 板块相对整体市场强弱（>1 强于大盘，<1 弱于大盘） |
| `sector_breadth_4c_ma128_align` | 板块内 4 个龙头收盘价 > MA128 比例 | 板块内部广度（>0.75 → 板块整体趋势好） |
| `sector_momentum_dispersion_20d` | 板块内 4 个龙头 20 日动量的标准差（低=板块轮动一致性高） | 板块轮动一致性 |
| `sector_new_high_ratio_30d` | 4 个龙头近 30 日创新高数 / 4 | 板块突破广度 |
| `sector_rotation_rank_5s` | 该板块近 30 日 α 在 5 板块中的排名（1~5） | 板块轮动当前位置（1 = 最强板块） |

### 10.4 资金分配执行模型

```
总分配流程：

  [Layer 0] 全局仓位乘数: global_mult
         ↓
  可分配仓位 = 总可用资金 × global_mult
         ↓
  [Layer 1] 5 个板块形态 → 5 个 sector_weight (归一化和=1)
         ↓
  各板块目标仓位 = 可分配仓位 × sector_weight
         ↓
  [核心层] BCRM 2.0 板块内排序：选板块内 confidence 最高的币种
         ↓
  单个币种目标仓位 = 板块目标仓位 / 板块内持仓数量
         ↓
  [止盈止损] 币种止盈止损 =
    币种基础止盈止损
    × 全局止盈乘数(global_tp_mult)
    × 板块止盈乘数(sector_tp_mult)
    × 币种个体属性（如波动率，由 BCRM 2.0 提供）
```

### 10.5 统一执行框架：多空持仓比 + 资金分配的联动逻辑

**设计意图**：多空持仓比控制（硬限制）与资金分配（软偏置）是**同一枚硬币的两面**——资金分配决定"该给谁多少钱"，多空持仓比决定"反向仓位最多能开多少"。两者共享 Layer 0 全局形态的判断，形成统一的风控 + 偏置体系。

#### 10.5.1 统一逻辑的三层过滤（从硬到软）

```
每次请求开新仓时，按以下顺序检查（从最严格的硬限制到最灵活的软偏置）：

┌─────────────────────────────────────────────────────────────────┐
│ 第1层：多空持仓比硬限制（ls_ratio_cap）                         │
│   └─ 检查：当前 ls_ratio 是否超出 ls_ratio_cap？                │
│      ├─ 超出 AND 新仓会扩大失衡 → 直接拒绝开仓（硬限制）        │
│      └─ 未超出 → 进入第2层                                     │
│                                                                 │
│ 第2层：多空偏置 + 阈值偏置（软过滤）                            │
│   └─ 检查：confidence ≥ base_threshold × threshold_mult × (1/bias)？│
│      ├─ 牛市：多头阈值降，空头阈值升 + 空头 bias 极低          │
│      ├─ 熊市：空头阈值降，多头阈值升 + 多头 bias 极低          │
│      └─ 不满足 → 信号被过滤（软过滤，非硬限制）                │
│                                                                 │
│ 第3层：资金分配 + 板块权重（仓位容量限制）                     │
│   └─ 检查：                                                     │
│      1. 板块是否还有剩余容量？（板块持仓 < 板块目标仓位）       │
│      2. 全局是否还有剩余容量？（总持仓 < max_positions）        │
│      3. 该币种所属板块的 sector_weight 是否 ≥ 最低权重门槛？    │
│         （如 RWA 板块权重 0.06 < 0.08 门槛 → 该板块不开新仓）  │
│      └─ 不满足 → 不开该板块/币种，等下一周期                    │
└─────────────────────────────────────────────────────────────────┘
```

#### 10.5.2 多空持仓比的计算与执行细节

```python
# 统一执行伪代码
def _check_and_apply_regime_pred_context(
    self,
    coin: str,
    direction: str,       # "long" | "short"
    base_confidence: float,
    base_position_size: float,
) -> dict:
    """
    统一执行 Layer 0 + Layer 1 的所有过滤与偏置
    
    返回: {"can_open": bool, "final_position": float, "final_tp": float,
           "final_sl": float, "final_threshold": float, "reason": str}
    """
    ctx = self._apply_regime_pred_context_to_core()  # 获取前置层输出
    
    # ===== 第1层：多空持仓比硬限制 =====
    long_total_usd = self._get_total_position_usd("long")
    short_total_usd = self._get_total_position_usd("short")
    current_ls_ratio = short_total_usd / max(long_total_usd, 1.0)
    ls_ratio_cap = (ctx["ls_ratio_cap"][0] + ctx["ls_ratio_cap"][1]) / 2  # 默认中间值
    
    # 新仓是否会扩大失衡？
    if direction == "short":
        new_short = short_total_usd + base_position_size
        new_ls_ratio = new_short / max(long_total_usd, 1.0)
        if new_ls_ratio > ls_ratio_cap:
            return {"can_open": False, "reason": f"ls_ratio {new_ls_ratio:.2f} > cap {ls_ratio_cap:.2f}"}
    else:  # direction == "long"
        new_long = long_total_usd + base_position_size
        # 注意：ls_ratio = 短/长，所以开多头 = 分母变大 = ls_ratio 变小（更安全）
        # 只有当 当前 ls_ratio > cap 且 方向是做空时 才触发硬限制
        # 开多头永远不会"扩大失衡"到违反 ls_ratio_cap（反而缩小）
    
    # ===== 第2层：多空偏置 + 阈值偏置（软过滤）=====
    if direction == "long":
        bias = (ctx["long_bias"][0] + ctx["long_bias"][1]) / 2
        th_mult = (ctx["long_threshold_mult"][0] + ctx["long_threshold_mult"][1]) / 2
    else:
        bias = (ctx["short_bias"][0] + ctx["short_bias"][1]) / 2
        th_mult = (ctx["short_threshold_mult"][0] + ctx["short_threshold_mult"][1]) / 2
    
    spring_mult = self._get_regime_short_multiplier(regime_score)  # 弹簧力场后置层
    
    final_threshold = (
        self.base_confidence_threshold  # 0.80
        * th_mult                       # 前置形态层阈值偏置
        * spring_mult                   # 后置弹簧力场调节器
        * (1.0 / bias)                  # 前置形态层多空偏置（注意是 1/bias）
    )
    final_threshold = max(0.50, min(0.98, final_threshold))  # 安全 clamp
    
    if base_confidence < final_threshold:
        return {"can_open": False, 
                "reason": f"confidence {base_confidence:.3f} < threshold {final_threshold:.3f}"}
    
    # ===== 第3层：资金分配 + 板块权重（仓位容量）=====
    sector = self._coin_to_sector(coin)
    sector_weight = ctx["sector_weights"].get(sector, 0.20)  # 默认平均权重
    global_pos_mult = (ctx["global_position_mult"][0] + ctx["global_position_mult"][1]) / 2
    sector_tp_mult = ctx["sector_tp_mult"].get(sector, 1.0)
    sector_sl_mult = ctx["sector_sl_mult"].get(sector, 1.0)
    global_tp_mult = (ctx["global_tp_mult"][0] + ctx["global_tp_mult"][1]) / 2
    global_sl_mult = (ctx["global_sl_mult"][0] + ctx["global_sl_mult"][1]) / 2
    
    # 板块容量检查
    sector_target_usd = (self._total_capital_usd * global_pos_mult) * sector_weight
    sector_current_usd = self._get_sector_position_usd(sector)
    sector_min_weight_threshold = 0.08  # 板块权重低于 8% 不开仓
    if sector_weight < sector_min_weight_threshold:
        return {"can_open": False, "reason": f"sector {sector} weight {sector_weight:.2f} < min {sector_min_weight_threshold}"}
    if sector_current_usd + base_position_size > sector_target_usd:
        return {"can_open": False, "reason": f"sector {sector} capacity full: {sector_current_usd:.0f}/{sector_target_usd:.0f}"}
    
    # ===== 所有检查通过：计算最终仓位 / 止盈 / 止损 =====
    final_position = base_position_size * global_pos_mult
    # 6 层乘数叠加后 clamp 防数值爆炸
    final_position_clamped = max(
        0.30 * base_position_size,
        min(3.0 * base_position_size, final_position)
    )
    
    final_tp = base_tp * global_tp_mult * sector_tp_mult
    final_sl = base_sl * global_sl_mult * sector_sl_mult
    
    return {
        "can_open": True,
        "final_position": final_position_clamped,
        "final_tp": final_tp,
        "final_sl": final_sl,
        "final_threshold": final_threshold,
        "reason": "all checks passed",
    }
```

#### 10.5.3 资金分配与多空持仓比的联动场景

| 市场形态 | Layer 0 全局形态 | 多空持仓比 cap | 资金分配 | 联合效果 |
|---------|----------------|---------------|---------|---------|
| **强牛市** | TREND_UP_STRONG | ls_cap = 0.10（空头 ≤ 多头 10%）| global_pos_mult = 1.20；AI/DeFi 板块权重 0.33/0.26 | 几乎封死空头；多头加 20% 仓位；钱优先给 AI/DeFi |
| **牛市末期** | FOMO_RALLY | ls_cap = 0.55（空头 55%）| global_pos_mult = 0.65；所有板块权重均衡（狂热时不追单一板块）| 多空阈值都升 25%；仓位降 35%；板块轮动不过度集中 |
| **熊市（暴跌）** | VOLATILE_DROP | ls_cap = 1.75（空头 1.75×多头）| global_pos_mult = 0.42；所有板块权重降低 | 几乎封死多头；整体轻仓 42%；允许空头大于多头 |
| **震荡市** | RANGE_BOUND | ls_cap = 1.15（多空基本平衡）| global_pos_mult = 0.90；5 板块平均 ~0.20 | 多空中性；仓位略降；板块均衡，靠 BCRM 2.0 方向和弹簧力场选币 |

#### 10.5.4 与易经推理系统现有开关的集成关系

| 现有开关 | 与形态预测层的关系 | 叠加方式 |
|---------|------------------|---------|
| S1 enable_mode_switch（满仓 MODE 切换）| 满仓时 S1 优先调整算力分配，形态预测层仍提供偏置 | 仓位乘数 = S1_MODE3_mult × regime_pred_global_mult（相乘）|
| S3 enable_multi_horizon（多 horizon 预测）| 不直接影响，S3 改信号生成逻辑 | 无乘数叠加，独立开关 |
| S4 enable_ranked_tp（排名止盈）| S4 止盈与形态预测层止盈乘数叠加 | final_tp = S4_tp_mult × regime_pred_global_tp_mult × sector_tp_mult |
| 满仓持仓 ≥ 3 单 | 触发 S1-S4 双轨并行；形态预测层自动降仓位乘数（MODE3 对应 DISTRIBUTION / FOMO_RALLY 概率更高）| 多层乘数独立，最终 clamp [0.30, 3.0] |

### 10.6 与核心层（BCRM 2.0）的交互接口规范

前置层与核心层的边界通过**配置化输入参数**交互，不修改核心层代码：

```python
# polling_trader.py 中前置层的输出，在调用 BCRM 2.0 前注入
def _apply_regime_pred_context_to_core(self):
    """
    前置层输出 → 核心层输入参数
    
    核心层（BCRM 2.0）只需读取以下 4 个 dict，无需知道来源：
    """
    ctx = {
        # Layer 0 全局
        "long_bias": (min, max),       # 范围：多头偏置乘数
        "short_bias": (min, max),      # 范围：空头偏置乘数
        "ls_ratio_cap": (min, max),    # 范围：多空持仓比上限
        "long_threshold_mult": (min, max),  # 范围：多头阈值乘数
        "short_threshold_mult": (min, max), # 范围：空头阈值乘数
        "global_position_mult": (min, max), # 范围：全局仓位乘数
        "global_tp_mult": (min, max),        # 范围：全局止盈乘数
        "global_sl_mult": (min, max),        # 范围：全局止损乘数
        
        # Layer 1 板块
        "sector_weights": {            # 板块资金权重（归一化和=1）
            "DeFi": 0.25,
            "AI-Web3": 0.30,
            "RWA": 0.15,
            "MEME": 0.10,
            "L2": 0.20,
        },
        "sector_tp_mult": {            # 板块级止盈乘数
            "DeFi": 1.20,
            # ...
        },
        "sector_sl_mult": {            # 板块级止损乘数
            "DeFi": 0.90,
            # ...
        },
    }
    return ctx
```

核心层用这些参数调整：
1. **币种选择排序**：高 sector_weight 的板块，币种 confidence 乘以额外的板块权重加成（提高该板块币种的排序优先级）
2. **开仓阈值应用**：`confidence ≥ base_threshold × threshold_mult × spring_force_mult × (1/bias)`
3. **持仓容量**：板块持仓数 ≥ 板块目标仓位 → 该板块不再新开仓
4. **止盈止损**：tp/sl = 基础 × global_mult × sector_mult

### 10.7 范围值的选择机制（弹簧力场后置层回测调优）

前置层输出的是范围 [min, max]，实际执行时需要一个具体值。选择机制：

```
默认选择中间值：
  val = (min + max) / 2

弹簧力场后置层回测后针对性调节（Phase 2 之后）：
  - 某形态下该参数范围内的值的 PnL / Sharpe 分布
  - 选分布中 PnL / Sharpe 最优的具体值
  - 写入进化配置键，后续优先使用

贝叶斯优化调优：
  对于 TREND_UP_STRONG 的 short_bias 范围 [0.20, 0.50]，
  回测 0.20 / 0.25 / 0.30 / 0.35 / 0.40 / 0.45 / 0.50 七组值，
  选 Sharpe 最高的点作为默认执行值。
```

### 10.8 TDD 测试矩阵（分层形态与资金分配）

| 测试 | 验证内容 | 通过标准 |
|------|---------|---------|
| **Layer 0 全局偏置类** | | |
| `test_layer0_tredup_bias` | TREND_UP_STRONG 输出 long_bias > 1, short_bias < 1 | 满足 |
| `test_layer0_volatiledrop_bias` | VOLATILE_DROP 输出 short_bias > 1, long_bias < 1 | 满足 |
| `test_layer0_tp_sl_ranges` | TREND_UP_STRONG tp_mult > 1, sl_mult < 1；VOLATILE_DROP 相反 | 满足映射 |
| `test_layer0_threshold_scenarios` | FOMO_RALLY 多空阈值范围都 > 1（两端严）；TREND_UP_STRONG 多头 < 1 空头 > 1 | min/max 都符合场景表 |
| **多空持仓比硬限制类** | | |
| `test_ls_ratio_cap_enforcement_short` | TREND_UP_STRONG，开新空使 ls_ratio 超 0.10 → 拒绝 | 返回 can_open=False |
| `test_ls_ratio_cap_enforcement_long_safe` | TREND_UP_STRONG，开新多使 ls_ratio 变小 → 允许（开多=分母变大=更安全）| 返回 can_open=True |
| `test_ls_ratio_cap_bear_mode` | VOLATILE_DROP，ls_cap=1.75，允许空头 > 多头 | 开空使 ls_ratio=1.80 才被拒 |
| **阈值 + 偏置软过滤类** | | |
| `test_threshold_with_bias_bull` | TREND_UP_STRONG：final_threshold = 0.80 × 0.875 × spring × (1/1.22) < 0.80 | 多头阈值降低（更容易开） |
| `test_threshold_with_bias_bear` | VOLATILE_DROP：final_threshold = 0.80 × 0.85 × spring × (1/1.22) < 0.80 | 空头阈值降低（更容易开） |
| `test_threshold_clamp_safety` | 多层乘数极端叠加后 final_threshold 在 [0.50, 0.98] | 0.50 ≤ th ≤ 0.98 |
| **板块资金权重类** | | |
| `test_sector_weights_normalized` | 5 板块 raw_weight 归一化后和=1.0 | abs(sum - 1) < 1e-6 |
| `test_sector_regime_weight_ordering` | TREND_UP_STRONG 权重 > RANGE_BOUND > VOLATILE_DROP | 正确排序 |
| `test_sector_weight_max_cap` | 单板块权重 clamp 后 ≤ 0.40（不允许 ALL IN）| sector_weight ≤ 0.40 |
| `test_sector_min_weight_threshold` | 板块权重 < 0.08 → 不开该板块仓 | can_open=False |
| `test_sector_relative_strength` | 板块 α 计算：板块涨 10% vs BTC 涨 5% → α=1.048 | 偏差 ≤ 1% |
| **统一执行三层过滤（完整流程）** | | |
| `test_three_layer_filter_pass` | 强牛市 + AI 板块币 + 高 confidence 做多 → 全部通过 | can_open=True + 乘数正确应用 |
| `test_three_layer_filter_fail_layer1` | 强牛市 + 新空仓使 ls_ratio=0.12 > cap 0.10 → 第1层拒 | can_open=False + reason 正确 |
| `test_three_layer_filter_fail_layer2` | 强牛市 + 低 confidence 做空 → 第2层软过滤拒 | can_open=False + reason 正确 |
| `test_three_layer_filter_fail_layer3` | 强牛市 + RWA 板块权重 0.06 < 0.08 门槛 → 第3层拒 | can_open=False + reason 正确 |
| **乘数叠加安全 clamp** | | |
| `test_multiplier_clamp_lower` | 多层乘数叠加后 < 0.30 × base → clamp 到 0.30 | final_position = 0.30 × base |
| `test_multiplier_clamp_upper` | 多层乘数叠加后 > 3.00 × base → clamp 到 3.00 | final_position = 3.00 × base |
| **接口与默认值类** | | |
| `test_context_injection_complete` | 前置层 → 核心层 ctx 字段齐全（8 个全局 range + 3 个板块 dict） | 所有字段完整 |
| `test_fallback_minmax_default` | 范围值默认取中间值 | val = (min+max)/2 |
| `test_sector_capacity_limit` | 板块仓位达上限时，不再新开该板块仓 | 正确限流 |
| **与现有开关集成类** | | |
| `test_s5_off_equivalent_baseline_integration` | S5=关：三层过滤直接跳过，行为 100% 等价旧路径 | 字节等价旧路径 |
| `test_s1_s5_multiplier_stack` | S1(MODE3_mult) × S5(global_pos_mult) → 两者相乘后 clamp | 符合叠加公式 |
| `test_s4_s5_tp_mult_stack` | S4(ranked_tp) × S5(global_tp) × S5(sector_tp) → 三者相乘 | 符合叠加公式 |

---

## 11. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 8 态标签数据驱动生成不稳定 | 中 | 高 | Phase 1 先验证标签分布，若某态 < 50 样本则合并相近态 |
| BTC 日线样本不足（5 年 = 1825 根） | 中 | 中 | 用 4 年训练 + 1 年测试；必要时扩展到 3D / 6H 周期补充样本 |
| Layer 1 板块龙头样本不足 | 高 | 中 | 多数 DeFi/AI/L2 龙头仅 2023 年以来有日线数据；解决：样本不足的板块先只用 ETF 替代 + 最长可用龙头（如 DOGE/UNI 历史更长） |
| 板块分类不合理（轮动错位） | 中 | 高 | 先用 5 板块覆盖主流，后续若发现轮动错位新增/合并板块；通过 `sector_rotation_rank_5s` 监测轮换模式再调整 |
| ls_ratio_cap 硬限制导致错失行情 | 中 | 中 | cap 是范围 [min, max]，先取中间值偏保守；回测后根据错失行情的机会成本再决定是否放宽 |
| 板块资金权重归一化后某板块资金过于集中 | 低 | 中 | 加设 `sector_weight_max_cap = 0.40`（单个板块最高 40%），防止 ALL IN 一个板块 |
| 美股 8 态分类效果差 | 中 | 中 | Phase 3 先跑 4 态基线（LucasLarese），若 8 态 Macro F1 < 0.40 则降级为 4 态 |
| ADX/Hurst 计算性能慢 | 低 | 低 | 缓存计算结果，日线级一次计算 1 次/天 |
| 方差放大导致过拟合 | 中 | 中 | WalkForward 验证；方差倍数 2.5/1.5 通过贝叶斯优化调参 |
| 外部数据源不可用（Phase 5） | 高 | 低 | 用代理特征替代（稳定币用 BTC 波动率倒数代理） |
| 形态预测与方向预测冲突 | 低 | 中 | 形态预测只调参数，不改方向；方向预测由 BCRM 2.0 主导 |
| 6+ 层乘数叠加数值爆炸 | 中 | 高 | 最终乘数 clamp 到 [0.30, 3.0] 合理区间；阈值 clamp 到 [0.50, 0.98] |
| **三层过滤顺序错误导致漏检** | 低 | 高 | 严格按 硬限制(ls_ratio) → 软过滤(阈值+偏置) → 容量(板块权重) 顺序；TDD 覆盖每层 bypass 场景 |
| **板块最低权重门槛 8% 不合理** | 中 | 中 | 初始 0.08 为经验值；回测若发现优质板块被误过滤（权重 0.07 但该板块币种胜率高）→ 下调至 0.05 或取消 |
| **开多头时 ls_ratio_cap 判断遗漏** | 低 | 高 | 注意：开多头 = 分母(long_total)变大 → ls_ratio 变小（更安全），但极端情况下（如无多头持仓时反向开多）需单独 TDD 覆盖分母为 0 的边界 |
| **范围值中间值非最优** | 高 | 中 | 默认取中间值只是 Phase 2 起步策略；Phase 2+ 必须通过弹簧力场回测 + 贝叶斯优化选出各形态的最优具体值 |

---

## 12. 路线图

| Phase | 周期 | 内容 | 验收标准 |
|-------|------|------|---------|
| **P0** | 3-4 天 | 12 个形态特征新增 + TDD | 单元测试全绿；ADX/Hurst 数值正确 |
| **P1** | 3-5 天 | 8 态自动标签 + BTC 日线形态预测器训练 + WalkForward | Macro F1 ≥ 0.55；Balanced Accuracy ≥ 0.65 |
| **P1.5**（新增） | 2-3 天 | Layer 1 板块龙头特征 + 板块形态预测器（5 板块各一个轻量模型）| 5 板块形态 8 态分类 Macro F1 ≥ 0.45；板块资金权重归一化测试通过 |
| **P2** | 5-7 天 | 前置形态层接入 BTC（开关 S5） + 统一执行框架（三层过滤 + 多空持仓比 + 板块权重 + 止盈止损/阈值/仓位调节）| 开关关=旧路径；Sharpe 提升 ≥ 15%；三层过滤 TDD 全覆盖 |
| **P3** | 4-6 天 | 美股数据源 + 美股形态预测器 + 独立策略 | 美股 Macro F1 ≥ 0.50；Sharpe ≥ 0.8 |
| **P4**（可选） | 5-7 天 | BOCPD + HMM 集成（开关 S6） | Macro F1 ≥ 0.65；BOCPD 提前 ≥ 3 日 |
| **P5**（可选） | 3-5 天 | 外部数据源（开关 S7） | Macro F1 提升 ≥ 3% |
| **P6**（可选，后置弹簧力场调优） | 4-6 天 | 所有范围 [min, max] 参数的贝叶斯优化 + 回测验证 | 各形态最优参数写入进化配置；Sharpe 相比 Phase 2 中间值再提升 ≥ 10% |

---

## 13. 与现有系统的兼容性

### 13.1 不影响的现有功能

- BCRM 2.0 方向预测器（BTC 1H）：完全不变
- 弹簧力场后置层（`_regime_short_filter` / `_get_regime_short_multiplier`）：完全不变
- 现有 4 个开关（S1-S4）：完全不变
- 现有训练管线（`run_bcrm2_backtest.py`）：完全不变

### 13.2 新增的开关与现有开关的关系

```
最终开仓阈值 = base_short_confidence(0.80)
              × score_multiplier（弹簧力场后置层）
              × regime_pred_threshold_mult（前置形态层阈值偏置，S5）
              × (1 / regime_pred_bias)（前置形态层多空偏置，S5）

最终仓位 = base_position_size
          × enable_mode_switch 乘数（S1）
          × enable_ev_radar 乘数（S2）
          × regime_pred_global_position_mult（S5，Layer 0 全局）
          → 最终 clamp [0.30, 3.0]

最终止盈 = base_take_profit
          × enable_ranked_tp 乘数（S4）
          × regime_pred_global_tp_mult（S5，Layer 0 全局）
          × regime_pred_sector_tp_mult（S5，Layer 1 板块）

最终止损 = base_stop_loss
          × regime_pred_global_sl_mult（S5，Layer 0 全局）
          × regime_pred_sector_sl_mult（S5，Layer 1 板块）
```

**层级关系**：前置形态层是"宏观"调节（Layer 0 全局 + Layer 1 板块），后置弹簧力场是"中观"调节（阈值 × score），BCRM 2.0 是"微观"方向预测（选币种 + 判方向 + confidence）。

---

## 14. TDD 实现顺序（每个 Phase 内）

每个 Phase 严格遵循：

1. **RED**：先写测试（测试失败）
2. **GREEN**：最小代码使测试通过
3. **REFACTOR**：重构优化，测试仍绿
4. **集成测试**：与现有系统联合测试
5. **回滚验证**：开关关闭时行为等价旧路径

---

## 附录 A: 参考资源

### 传统金融理论
- Dow Theory（Charles Dow, 1900-1902）：6 阶段市场周期
- Wyckoff Method（Richard Wyckoff, 1931）：吸筹/派发识别
- Elliott Wave（Ralph Elliott, 1938）：5 浪推进 + 3 浪修正
- Wilder ADX（J. Welles Wilder, 1978）：趋势强度指标
- Hurst Exponent（Harold Hurst, 1951）：R/S 分析法

### GitHub 开源项目
- [LucasLarese/market-regime-detection](https://github.com/LucasLarese/market-regime-detection)：4 态趋势×波动率
- [nyro-github/HMM-MarketState](https://github.com/nyro-github/HMM-MarketState)：8 态 HMM
- [taylorjmellon/market-regime-detection](https://github.com/taylorjmellon/market-regime-detection)：K-Means+HMM
- [k3tikvats/market_regime_detection](https://github.com/k3tikvats/market_regime_detection)：GMM/HDBSCAN
- [CameronScarpati/lob-regime-scanner](https://github.com/CameronScarpati/lob-regime-scanner)：HMM+VPIN
- [Raynergy-svg/ml_engine](https://github.com/Raynergy-svg/ml_engine)：BOCPD+Hurst+ADX

### 学术论文
- Adams & MacKay (2007): Bayesian Online Changepoint Detection
- Hamilton (1989): A New Approach to the Economic Analysis of Nonstationary Time Series (HMM)

---

## 附录 B: 8 态与 5 态的映射关系

当需要将 8 态形态预测与 5 态弹簧力场后置层对齐时：

| 8 态（前置层） | 5 态（后置层） | 说明 |
|---------------|---------------|------|
| TREND_UP_STRONG | TREND_BULL | 强多头 |
| TREND_UP_MILD | TREND_BULL | 弱多头 |
| RANGE_BOUND | RANGING | 震荡 |
| CONSOLIDATION | RANGING | 横盘（震荡子类） |
| REVERSAL | MEAN_REVERTING | 反转 |
| VOLATILE_DROP | STRONG_TREND_BEAR | 暴跌 |
| FOMO_RALLY | TREND_BULL | 狂热（多头子类） |
| DISTRIBUTION | MEAN_REVERTING | 派发（均值回归子类） |

注：8 态是更细的分类，5 态是粗粒度，两者**不冲突**，前置层调参数，后置层调阈值。
