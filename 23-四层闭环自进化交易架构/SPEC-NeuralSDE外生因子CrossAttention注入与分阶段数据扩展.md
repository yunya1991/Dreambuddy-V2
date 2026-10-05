# SPEC: NeuralSDE 外生因子 Cross-Attention 注入 + 分阶段数据扩展（P1+）

> **状态：** 🔵 待评审
> **创建：** 2026-10-06
> **目标：** 通过 IC 筛选的因子池 + Cross-Attention 架构，将 2024 OOS walk-forward ratio 从 1.1127 降至 <0.93（击败 GARCH 7%+）
> **硬约束：** FAIL-OPEN 铁律不可破坏；`use_cross_attention=False` 时行为与当前完全等价；零回归；IC 筛选控制因子数 ≤15
> **核心矛盾：** 外生数据方向已验证有效（-6.25% ratio, -50% max_ratio），但 9 维手工定义的 3×3 结构信息利用率低 → 用 IC 筛选 + Cross-Attention 释放因子组合潜力

***

## 零 · 现状基线

### 0.1 E7 PoC（A1 真实 DAL 历史外生）结果

| 指标 | Config A (无外生) | Config B (9维外生) | 变化 |
|------|-------------------|---------------------|------|
| mean_ratio | 1.1869 | 1.1127 | **-6.25%** ✅ |
| mean_mae | 971.03 | 978.20 | +0.7% |
| max_ratio | 2.7861 | 1.3920 | **-50.0%** ✅ |
| GARCH MAE | 937.73 | 937.73 | — |

**闸门**：不恶化 PASS；P1 目标 <0.93 FAIL。

**结论**：外生数据方向正确，但因子组合和注入方式未达最优。

### 0.2 当前外生注入方式

```
[S_t, time_feat(2), log_sig(15), regime(3), exogenous(9)] → MLP → MoE → drift
```

9 维外生向量直接 concatenate，模型需从固定 9 维中学习组合——**信息利用率低**。

### 0.3 19-DAL 数据全景（mm_metrics 全表扫描）

| 阶段 | 数据类型 | 指标数 | 覆盖时间 | 用途 |
|------|----------|--------|----------|------|
| 阶段1 | 宏观+链上（LONG） | 11 | 2017-2024 | 立即可回测 |
| 阶段2 | 宏观补充（MID） | 10 | 2022-2026 | 需补采 2017-2022 |
| 阶段3 | 衍生品+稳定币+ETF（SHORT） | 30+ | 2026-08+ | 需历史数据补采 |

***

## 一 · 核心矛盾

```
外生数据有效（-6.25% ratio, -50% max_ratio）
但 9 维手工结构 + 简单拼接 → 信息利用率低 → ratio 仍 1.11 > 0.93
```

**解法**：
1. **因子筛选**：用 IC 分析从数据池中找出真正有预测力的因子，避免噪声干扰
2. **架构升级**：Cross-Attention 让模型自动学习因子组合，替代手工 3×3 结构
3. **数据扩展**：分三阶段接入更多 DAL 数据，阶段3 用历史数据源补采而非等实盘

***

## 二 · 分阶段数据扩展路线图

### 阶段 1：立即可用（2017-2024 全覆盖）

| 类别 | sub_category.metric | 时间范围 | 说明 |
|------|---------------------|----------|------|
| 宏观 | `cpi.actual` | 2017-2026 | CPI 月度 |
| 宏观 | `fomc_decision.rate` | 2017-2026 | 联邦基金利率 |
| 宏观 | `fomc_decision.rate_change` | 2017-2026 | 利率变动 |
| 宏观 | `fedwatch.hike_prob` | 2017-2026 | 加息概率 |
| 宏观 | `fedwatch.cut_prob` | 2017-2026 | 降息概率 |
| 宏观 | `macro.m2_sl` | 2017-2024 | M2 货币供应 |
| 宏观 | `DX-Y.NYB.close` | 2017-2024 | DXY 美元指数 |
| 链上 | `btc_basics.market_cap_usd` | 2018-2026 | BTC 市值 |
| 链上 | `btc_basics.tx_count_24h` | 2018-2026 | 24h 交易数 |
| 链上 | `btc_onchain.hash_rate` | 2018-2024 | 算力 |
| 链上 | `btc_onchain.active_addresses` | 2018-2024 | 活跃地址 |

**共 11 个原始指标**，直接可用。

### 阶段 2：补采历史（FRED + yfinance 回填 2017-2022）

| 类别 | sub_category.metric | 现有范围 | 补采来源 |
|------|---------------------|----------|----------|
| 宏观 | `WALCL.value` | 2023-2026 | FRED API |
| 宏观 | `^VIX.value` | 2023-2026 | yfinance |
| 宏观 | `GLD.value` | 2023-2026 | yfinance |
| 宏观 | `SPY.value` | 2023-2026 | yfinance |
| 宏观 | `PPIACO.value` | 2022-2026 | FRED API |
| 宏观 | `CPIAUCSL.value` | 2022-2026 | FRED API |
| 宏观 | `INDPRO.value` | 2022-2026 | FRED API |
| 宏观 | `FEDFUNDS.value` | 2022-2026 | FRED API |
| 宏观 | `T10Y2YM.value` | 2022-2026 | FRED API |
| 宏观 | `M2SL.value` | 2022-2026 | FRED API |

补采后阶段1+2 共 **21 个原始指标**。

### 阶段 3：历史数据补采（加速方案，不等实盘积累）

> **关键决策**：阶段3 不再等实盘积累，而是通过公开历史数据源一次性补采。

| 类别 | 指标 | 补采来源 | 可回溯至 |
|------|------|----------|----------|
| 衍生品 | `funding_rate` | Binance API (`/fapi/v1/fundingRate`) | 2019-09 |
| 衍生品 | `fut_open_interest` | Binance API | 2020-01 |
| 衍生品 | `options.oi` | Deribit API | 2020-01 |
| 稳定币 | `usdt_circulating`, `usdc_circulating` | DefiLlama API | 2020-01 |
| 稳定币 | `stablecoin_total_tvl` | DefiLlama API | 2020-01 |
| 交易所 | `ex_bal_BTC_total`, `ex_bal_ETH_total` | DefiLlama (exchanges endpoint) | 2020-01 |
| ETF | `btc_etf_daily_flow` | farside.co.uk（公开 CSV） | 2024-01 |
| 巨鲸 | `whale_netflow` | Coinglass 免费 API（有限历史） | 2022-01 |
| 情绪 | `crypto_fear_greed` | alternative.me API | 2018-01 |
| 链上 | `utxo_age_distribution` | blockchain.info | 2018-01 |

**注意**：ETF flow 仅能回溯到 2024-01（比特币ETF 2024年1月才上市），但恰好覆盖回测窗口 2024。

#### 阶段3 补采 API 明细（已验证可用）

| 指标 | API 端点 | 频率 | 预计数据量 | 写入 DAL |
|------|----------|------|-----------|----------|
| funding_rate | `GET https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime=1569888000000&limit=1000` | 8h | ~5500 条 | sub_cat=`funding_rate`, metric=`value` |
| 稳定币总流通 | `GET https://stablecoins.llama.fi/stablecoincharts/all?stablecoin=1` | 1d | ~1400 条 | sub_cat=`stablecoin_total`, metric=`circulating_usd` |
| 交易所BTC余额 | `GET https://api.llama.fi/exchanges` + 历史接口 | 1d | ~1200 条 | sub_cat=`exchange_balance`, metric=`btc_total` |
| ETF flow | Farside CSV（比特币ETF上市日起） | 1d | ~300 条 | sub_cat=`etf_flow`, metric=`total_flow` |
| 恐惧贪婪 | `GET https://api.alternative.me/fng/?limit=2000&date_format=cn` | 1d | ~2400 条 | sub_cat=`fear_greed`, metric=`value` |
| 期货OI | `GET https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1d&limit=500` | 1d | ~1500 条 | sub_cat=`fut_oi`, metric=`btc_oi` |

**补采优先级**：
- P0: funding_rate（多空情绪最直接）
- P1: 稳定币流通量（流动性脉冲）、交易所BTC余额（抛压/吸筹）
- P2: ETF flow（2024机构资金）、恐惧贪婪（情绪）、期货OI

***

## 三 · 因子有效性筛选机制（IC 分析）

### 3.1 核心算法

新建 `factor_ic_selector.py`：

```
输入：候选因子池（阶段1/2/3 的原始指标）
处理：
  1. 时序对齐：所有因子对齐到 BTC 价格时间轴（低频前向填充）
  2. 标准化：z-score（滚动窗口，避免未来信息泄露）
  3. IC 计算：对每个因子，计算与 BTC 未来 N 日对数收益的 Spearman RankIC
     - N ∈ {1, 3, 7, 14, 30}
  4. IC_IR：滚动窗口（90 天）计算 IC 序列 → IC_IR = mean(IC) / std(IC)
  5. 筛选：abs(IC_mean) > 0.03 且 abs(IC_IR) > 0.5 且 IC 胜率 > 55%
  6. 共线性检验：VIF > 10 的因子剔除（保留 IC_IR 更高者）
输出：因子排行榜（按 |IC_IR| 降序），取 Top-K（K=15）
```

### 3.2 接口签名

```python
class FactorICSelector:
    def __init__(self, dal_path: str, price_path: str):
        ...

    def select_factors(
        self,
        candidate_metrics: List[Tuple[str, str]],  # [(sub_category, metric_name), ...]
        horizons: List[int] = [1, 3, 7, 14, 30],
        ic_threshold: float = 0.03,
        ir_threshold: float = 0.5,
        win_rate_threshold: float = 0.55,
        vif_threshold: float = 10.0,
        top_k: int = 15,
    ) -> FactorSelectionResult:
        """筛选显著因子并返回排行榜"""

    def get_ranking(self) -> pd.DataFrame:
        """返回完整因子排行榜（含 IC、IC_IR、胜率、VIF）"""
```

### 3.3 输出结构

```python
@dataclass
class FactorSelectionResult:
    selected_factors: List[str]          # 入选因子名列表
    ranking: pd.DataFrame                # 完整排行榜
    ic_by_horizon: Dict[str, np.ndarray] # 每个因子在各 horizon 的 IC
    excluded: List[Dict]                 # 被剔除因子及原因
```

***

## 四 · Cross-Attention 外生注入架构

### 4.1 架构对比

**当前（P1）**：
```
[S_t, time_feat(2), log_sig(15), regime(3), exogenous(9)] → MLP → MoE → drift
```

**方案 C**：
```
价格路径 → SignatureEngine → log_sig → Linear → Q (d_model=32)
                                                       │
                                                       ▼
因子池(N个) → FactorEncoder(Linear+LN) → K, V (N × d_model)
                                                       │
                                                       ▼
                           MultiHeadCrossAttention(Q, K, V)
                                                       │
                                                       ▼
                                  context_vector (d_model)
                                                       │
[S_t, time_feat, context_vector, regime, transition] → MoE MLP → drift
```

**设计原理**：价格作为 Query 询问"当前外生环境如何"，因子作为 Key-Value 提供上下文。注意力权重自动学习"哪些因子在当前价格状态下重要"。

### 4.2 核心组件

#### 4.2.1 FactorEncoder

```python
class FactorEncoder(nn.Module):
    """将 N 个原始因子编码为 d_model 维 token 序列。
    支持可变因子数（IC 筛选后动态调整）。
    """
    def __init__(self, factor_dim: int, d_model: int = 32):
        self.proj = nn.Linear(factor_dim, d_model)
        self.norm = nn.LayerNorm(d_model)

    def forward(self, factors: Tensor) -> Tensor:
        # factors: (B, N, factor_dim) → (B, N, d_model)
        return self.norm(self.proj(factors))
```

#### 4.2.2 MultiHeadCrossAttention

```python
class MultiHeadCrossAttention(nn.Module):
    """标准多头交叉注意力。
    Q 来自价格 signature，K/V 来自外生因子。
    """
    def __init__(self, d_model: int = 32, n_heads: int = 4, dropout: float = 0.1):
        self.q_proj = nn.Linear(d_model, d_model)
        self.k_proj = nn.Linear(d_model, d_model)
        self.v_proj = nn.Linear(d_model, d_model)
        self.out_proj = nn.Linear(d_model, d_model)
        self.n_heads = n_heads

    def forward(self, query: Tensor, key: Tensor, value: Tensor) -> Tensor:
        # query: (B, 1, d_model), key/value: (B, N, d_model)
        # → context: (B, 1, d_model) → squeeze → (B, d_model)
```

#### 4.2.3 _PathSignatureDriftNet 改造

```python
class _PathSignatureDriftNet(nn.Module):
    def __init__(
        self,
        ...,
        use_cross_attention: bool = False,      # NEW: 开关
        exogenous_factor_dim: int = 0,          # NEW: 因子数
        cross_attn_dim: int = 32,               # NEW: 注意力维度
        cross_attn_heads: int = 4,              # NEW: 注意力头数
    ):
        self.use_cross_attention = use_cross_attention
        if use_cross_attention and exogenous_factor_dim > 0:
            self.factor_encoder = FactorEncoder(1, cross_attn_dim)
            self.cross_attn = MultiHeadCrossAttention(cross_attn_dim, cross_attn_heads)
            self.q_proj = nn.Linear(sig_dim, cross_attn_dim)
            # drift_net 输入: 3 + cross_attn_dim + n_regimes + n_transition
            in_dim = 3 + cross_attn_dim + self.n_regimes + self.n_transition
        else:
            # 向后兼容: 原 exogenous_dim 拼接方式
            in_dim = 3 + self.sig_dim + self.n_regimes + self.n_transition + self.exogenous_dim

    def forward(self, t, y, log_sig, regime, transition, exogenous=None, exogenous_factors=None):
        if self.use_cross_attention and exogenous_factors is not None:
            # Q from log_sig
            q = self.q_proj(log_sig).unsqueeze(1)  # (B, 1, d_model)
            # K, V from factors
            k = self.factor_encoder(exogenous_factors)  # (B, N, d_model)
            v = k
            # Cross-attention
            ctx = self.cross_attn(q, k, v).squeeze(1)  # (B, d_model)
            x = cat([y, time_feat, ctx, regime, transition])
        else:
            # 原路径（FAIL-OPEN）
            x = cat([y, time_feat, log_sig, regime, transition, exo_t])
        return self.net(x)
```

### 4.3 FAIL-OPEN 设计

| 场景 | 行为 |
|------|------|
| `use_cross_attention=False` | 完全等价于当前架构（exogenous_dim 拼接） |
| `use_cross_attention=True`, `exogenous_factors=None` | 跳过 cross-attention，context_vector=0，drift_net 退化 |
| 因子数 N 变化 | FactorEncoder 按 N 动态编码，注意力自动适配 |
| 部分因子缺失 | 缺失因子 pad 0，注意力权重自动降低 |

### 4.4 向后兼容

- `use_cross_attention` 默认 `False`，现有代码/模型无需修改
- `exogenous_dim` 参数保留，用于 baseline 对比
- 旧模型 checkpoint 可加载到新架构（use_cross_attention=False 时）

***

## 五 · 实施步骤（TDD）

### C1: 因子 IC 筛选器

- **RED**: `test_factor_ic_selector.py` — 验证 IC 计算、筛选逻辑、VIF 共线性
- **GREEN**: `factor_ic_selector.py` — 实现核心算法
- **验证**: 跑阶段1 11 个因子，输出排行榜

### C2: Cross-Attention 组件

- **RED**: `test_cross_attention.py` — 验证 FactorEncoder、MultiHeadCrossAttention 的维度和 FAIL-OPEN
- **GREEN**: `cross_attention.py` — 实现两个组件
- **验证**: 单元测试 + 过拟合测试（小数据集能过拟合）

### C3: NeuralSDE 改造

- **RED**: `test_neural_sde_cross_attention.py` — 验证 use_cross_attention=True/False 行为
- **GREEN**: 修改 `neural_sde_model.py` 的 `_PathSignatureDriftNet`
- **验证**: 现有 120 个测试零回归 + 新测试通过

### C4: 数据桥接扩展

- **RED**: `test_exogenous_bridge_dynamic.py` — 验证动态因子池拉取
- **GREEN**: 扩展 `exogenous_data_bridge.py` 支持按因子名列表拉取
- **验证**: 阶段1 11 因子 + 阶段2 10 因子可正确拉取并对齐

### C5: E7 PoC 验证

- **脚本**: `poc_p1_cross_attention.py`
- **对比**: baseline(无外生) vs 9维拼接 vs Cross-Attention+IC筛选
- **目标**: ratio < 0.93, max_ratio 进一步降低

### C6: 阶段2/3 数据补采

- **脚本**: `backfill_phase2_macro.py`, `backfill_phase3_derivatives.py`
- **验证**: 补采后重跑 IC 筛选 + E7 PoC

***

## 六 · 验收标准

### 6.1 功能验收

- [ ] `FactorICSelector` 能从 DAL 拉取并筛选因子，输出排行榜
- [ ] 筛选标准：|IC_mean|>0.03 且 |IC_IR|>0.5 且 IC 胜率>55% 且 VIF<10
- [ ] Cross-Attention 组件维度正确，FAIL-OPEN 行为符合设计
- [ ] `use_cross_attention=False` 时 NeuralSDE 行为与当前完全一致
- [ ] 现有 120 个测试零回归

### 6.2 性能验收（E7 walk-forward 2024 OOS）

| 指标 | 当前 | 目标 |
|------|------|------|
| mean_ratio | 1.1127 | **< 0.93** |
| max_ratio | 1.3920 | **< 1.2** |
| 不恶化闸门 | PASS | PASS |

### 6.3 阶段验收

- **阶段1**：11 因子 IC 筛选 + Cross-Attention → ratio < 1.0（中间目标）
- **阶段2**：+10 宏观因子补采 → ratio < 0.93（达标目标）
- **阶段3**：+衍生品/稳定币/ETF 补采 → 确认是否进一步改善

***

## 七 · 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| Cross-Attention 过拟合 | 中 | d_model=32（小）、dropout=0.1、IC 筛选控制 N≤15、早停 |
| 因子共线性导致注意力退化 | 中 | VIF>10 剔除，保留高 IC_IR 因子 |
| 低频宏观信号被稀释 | 低 | 宏观信号做事件式注入（FOMC 日前后权重提升） |
| 训练成本增加 | 低 | Cross-Attention 参数量 ~10K，训练时间 +<20% |
| 阶段3 数据源不稳定 | 中 | 优先用 Binance/DefiLlama 等稳定 API，Coinglass 作补充 |
| ETF flow 仅覆盖 2024 | 低 | 恰好对齐回测窗口，2024 前 pad 0 或用 proxy |

***

## 八 · 认知闭环

- 实施过程中发现的反模式/决策 → `record` 写入认知库
- 各阶段验证结果 → `verify` 更新相关记忆置信度
- E7 最终结果 → 记录为 P1+ 成果案例
