# 易经推理系统宏观特征集成与基线验证设计

**文档版本**: v1.0  
**创建日期**: 2026-08-05  
**状态**: 待评审  
**作者**: DreamBuddy Team

---

## 一、背景与动机

### 1.1 现状

易经推理系统 BCRM 2.0 当前共有 **392 个特征**（11 个模块），覆盖价格/量能/技术指标/卦象/力学/周期等维度，但存在两个关键问题：

#### 问题 1：实盘推理与回测特征模块不一致

| 模块 | 回测 | 实盘 | 差异 |
|------|:----:|:----:|------|
| 八卦特征 (bagua) | ✅ | ✅ | — |
| 经典经验 (classic_exp) | ✅ | ✅ | — |
| 斐波那契 (fibonacci) | ✅ | ✅ | — |
| 枢纽点 (pivot_point) | ✅ | ✅ | — |
| RSI 情绪 (rsi_sentiment) | ✅ | ✅ | — |
| WDH 三屏 (wdh) | ✅ | ✅ | — |
| 库存周期 (cycle) | ✅ | ❌ | **实盘缺失** |
| 市值等级 (market_cap) | ✅ | ❌ | **实盘缺失** |
| 跨资产 (cross_asset) | ✅ | ❌ | **实盘缺失** |
| 美林时钟 (merrill_clock) | ✅ | ❌ | **实盘缺失** |
| Meta-Labeling V2 | ✅ | ❌ | **实盘缺失** |

- 回测路径：[walk_forward_backtester.py#L320-L472](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/walk_forward_backtester.py#L320-L472) 拼接全部 11 个模块
- 实盘路径：[bcrm2_adapter.py#L192-L225](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2_adapter.py#L192-L225) 仅拼接 6 个模块

**根因**：特征拼接是硬编码的 `pd.concat` 序列，无插件注册机制，回测和实盘各自维护一份代码，导致漂移。

**影响**：回测指标（夏普 7.45、胜率 70.2%）在实盘根本无法复现——实盘模型从未见过那 5 个模块的特征。

#### 问题 2：缺乏真正的宏观/基本面特征

当前 BCRM 2.0 中名为"宏观环境"的特征（[meta_labeling_features_v2.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/meta_labeling_features_v2.py) `_macro_environment_features()`）实际全部由 OHLCV 价格派生（BTC.D 用价格比代理、资金流向用成交量变化代理），**没有任何外部宏观数据注入**。

与此同时，系统已在 [free_fundamental_provider.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/capabilities/trading/free_fundamental_provider.py) 接入 8 个免费数据源（Hyperliquid / CoinGecko / alternative.me / Blockchain.info / OKX / DefiLlama / 币安 Web3 Social / 币安 Web3 Smart Money），但**这些数据只被 DreamOS F 链消费，易经 BCRM 2.0 完全不消费**。

### 1.2 目标

1. **P0 建立可信基线**：修复实盘 vs 回测不一致，重构为 FeatureRegistry 插件机制，保存基线快照
2. **P1 引入宏观特征**：新建 MacroDataFetcher 和 MacroFeatures 模块，回测验证必须高于基线才能实盘
3. **探索方向标记**：未通过基线对比的版本标记为 `exploratory`，不进入实盘配置

### 1.3 原则

- **回测/实盘一致性**：FeatureRegistry 是唯一特征入口，回测和实盘调用同一代码路径
- **无 Mock 兜底**：宏观数据采集失败时特征模块返回空，不伪造数据（吸取 9-基本面分析 `random.uniform` 兜底的教训）
- **时间对齐严格**：宏观数据 forward-fill 到 K 线时间戳，发布延迟 ≥ 1 根 K 线（避免未来函数）
- **显著性检验**：bootstrap 重采样 1000 次计算 p-value，单次回测提升不算数
- **代码驱动**：优先使用成熟稳定的代码实现，AI 大模型仅在必要时辅助

---

## 二、P0：建立可信基线

### 2.1 FeatureRegistry 插件注册机制

#### 2.1.1 设计

新建 [bcrm2/feature_registry.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/feature_registry.py)，作为回测和实盘共用的唯一特征入口。

```python
class FeatureModuleSpec:
    """特征模块规格定义"""
    name: str                           # 模块名（如 "bagua", "macro"）
    module_cls: type                    # 模块类
    participates_in_gua: bool           # 是否参与卦象推导
    requires_ref_df: bool               # 是否需要参考资产（如 BTC）
    requires_macro_df: bool             # 是否需要宏观数据
    requires_config: bool               # 是否需要市值等级配置
    default_enabled: bool               # 默认是否启用


class FeatureRegistry:
    """特征模块注册表，回测/实盘共用同一注册表"""
    _registry: Dict[str, FeatureModuleSpec] = {}
    
    @classmethod
    def register(cls, name: str, module_cls: type,
                 participates_in_gua: bool = False,
                 requires_ref_df: bool = False,
                 requires_macro_df: bool = False,
                 requires_config: bool = False,
                 default_enabled: bool = True) -> None:
        """注册特征模块（在模块文件顶部调用）"""
        ...
    
    @classmethod
    def compute_all(cls, df: pd.DataFrame,
                    ref_df: Optional[pd.DataFrame] = None,
                    macro_df: Optional[pd.DataFrame] = None,
                    config: Optional[dict] = None,
                    enabled: Optional[List[str]] = None) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
        """
        按注册顺序计算所有启用模块的特征
        
        参数:
            enabled: 启用的模块名列表。None 表示启用所有 default_enabled=True 的模块。
                     传入列表时精确控制启用范围（回测/实盘可传入不同配置）。
        
        返回:
            features: 合并后的特征 DataFrame
            feature_names_by_gua: {模块名: [特征名列表]}
        """
        ...
    
    @classmethod
    def list_modules(cls) -> List[str]:
        """列出所有已注册模块"""
        ...
```

#### 2.1.2 模块注册示例

每个特征模块文件在顶部自注册：

```python
# bcrm2/bagua_feature_engine.py
from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

@FeatureRegistry.register("bagua", participates_in_gua=True)
class BaguaFeatureEngine:
    def compute(self, df: pd.DataFrame) -> pd.DataFrame: ...
```

```python
# bcrm2/macro_features.py (P1 新增)
@FeatureRegistry.register("macro", requires_macro_df=True)
class MacroFeatures:
    def compute(self, df: pd.DataFrame, macro_df: pd.DataFrame) -> pd.DataFrame: ...
```

#### 2.1.3 回测和实盘统一调用

重构后，[walk_forward_backtester.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/walk_forward_backtester.py) 和 [bcrm2_adapter.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2_adapter.py) 的特征计算都改为：

```python
from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

features, feature_names_by_gua = FeatureRegistry.compute_all(
    df=df,
    ref_df=ref_df,          # 可选
    macro_df=macro_df,      # P1 才有
    config=market_cap_cfg,  # 可选
    enabled=config["features"]["enabled"]  # 配置驱动
)
```

**效果**：回测和实盘调用同一 `compute_all()`，彻底消除不一致。新增模块只需在文件顶部 `@FeatureRegistry.register(...)`，无需修改回测/实盘代码。

### 2.2 实盘模块对齐

P0 完成后，实盘自动获得与回测一致的 11 个模块（因为统一走 Registry）。

对齐前后的验证方式：
1. 跑同一币种同一时间窗口的回测，对比重构前后的特征矩阵（`pd.testing.assert_frame_equal` 容差 1e-6）
2. 确保重构不改变已有 6 个模块的特征值（回归测试）

### 2.3 基线快照

#### 2.3.1 基线建立流程

1. 在 P0 重构完成后，对当前 15 个代币跑完整 walk-forward 回测
2. 保存基线快照到 `data/baseline/baseline_v1.json`
3. 打 git tag `baseline-v1`

#### 2.3.2 基线指标

> 注：以下为快照文件结构示例，`created_at` / `git_commit` / `metrics` 的具体值在 P0 完成后由脚本自动填充，`per_coin_metrics` 为每个币种的独立指标明细。

```json
{
  "version": "baseline-v1",
  "created_at": "<脚本运行时 ISO 时间>",
  "git_commit": "<git rev-parse HEAD>",
  "feature_modules": ["bagua", "classic_exp", "fibonacci", "pivot_point", 
                      "rsi_sentiment", "wdh", "cycle", "market_cap", 
                      "cross_asset", "merrill_clock", "meta_labeling_v2"],
  "feature_count": 392,
  "coins": ["UNI", "PUMP", "MU", "SKHYNIX", "HYPE", "ETH", "BTC", "SOL",
            "XAU", "XAG", "GOOGL", "NVDA", "AMZN", "OKB", "BNB"],
  "timeframe": "1H",
  "metrics": {
    "sharpe": "<回测实际值>",
    "win_rate": "<回测实际值>",
    "profit_factor": "<回测实际值>",
    "max_drawdown": "<回测实际值>",
    "calmar": "<回测实际值>",
    "total_return": "<回测实际值>",
    "avg_hold_bars": "<回测实际值>",
    "total_trades": "<回测实际值>"
  },
  "per_coin_metrics": {
    "BTC": { "sharpe": "...", "win_rate": "...", "..." : "..." },
    "ETH": { "sharpe": "...", "win_rate": "...", "..." : "..." }
  }
}
```

### 2.4 P0 交付物

| 交付物 | 路径 | 说明 |
|--------|------|------|
| FeatureRegistry | `bcrm2/feature_registry.py` | 插件注册机制核心 |
| 11 个模块自注册改造 | `bcrm2/*.py` | 每个模块顶部加 `@register` |
| walk_forward_backtester 重构 | `bcrm2/walk_forward_backtester.py` | 改为调用 `FeatureRegistry.compute_all()` |
| bcrm2_adapter 重构 | `scripts/memory_l4/bcrm2_adapter.py` | 改为调用 `FeatureRegistry.compute_all()` |
| 基线快照 | `data/baseline/baseline_v1.json` | 回测指标 + git tag |
| 回归测试 | `tests/test_feature_registry.py` | 验证重构前后特征一致性 |
| git tag | `baseline-v1` | 基线版本标记 |

---

## 三、P1：引入宏观特征

### 3.1 MacroDataFetcher 宏观数据采集器

#### 3.1.1 设计

新建 [bcrm2/macro_data_fetcher.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/macro_data_fetcher.py)，复用 [free_fundamental_provider.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/capabilities/trading/free_fundamental_provider.py) 的采集逻辑，独立于 DreamOS。

```python
@dataclass
class MacroData:
    """统一宏观数据容器"""
    timestamp: datetime
    symbol: str
    
    # 情绪维度
    fear_greed_index: Optional[float]
    fear_greed_trend_7d: Optional[float]
    fear_greed_extreme: Optional[bool]
    
    # 资金/衍生品维度
    funding_rate: Optional[float]
    funding_rate_zscore: Optional[float]
    funding_rate_extreme: Optional[bool]
    open_interest_usd: Optional[float]
    open_interest_change: Optional[float]
    
    # 流动性维度
    stablecoin_supply: Optional[float]
    stablecoin_supply_growth: Optional[float]
    tvl: Optional[float]
    tvl_change_7d: Optional[float]
    
    # 链上维度
    hash_rate: Optional[float]
    miners_revenue: Optional[float]
    
    # 聪明钱/社交维度
    smart_money_direction: Optional[float]
    social_hype_score: Optional[float]
    
    # 估值维度
    market_cap: Optional[float]
    market_cap_rank: Optional[int]
    ath_drop_pct: Optional[float]
    supply_ratio: Optional[float]
    
    # 来源标记（拒绝 Mock）
    data_source: str  # "real" | "missing"


class MacroDataFetcher:
    """宏观数据采集器，复用 free_fundamental_provider 逻辑"""
    
    def __init__(self, cache_dir: Path = None):
        self.cache = MacroDataCache(cache_dir)  # SQLite 本地缓存
    
    def fetch_all(self, symbol: str, since: datetime) -> List[MacroData]:
        """采集 8 个免费源，返回时间序列"""
        ...
    
    def align_to_klines(self, macro_list: List[MacroData], 
                        kline_index: pd.DatetimeIndex,
                        lookahead_guard: int = 1) -> pd.DataFrame:
        """
        降频聚合到 K 线时间戳
        
        lookahead_guard: 发布延迟保护（≥1 根 K 线），避免未来函数
        """
        ...
```

#### 3.1.2 数据源清单

| # | 数据源 | 提供字段 | 采集频率 | 无 Key |
|---|--------|----------|:--------:|:------:|
| 1 | Hyperliquid | funding_rate, OI, mark_price | 1H | ✅ |
| 2 | CoinGecko | market_cap, ATH, supply_ratio | 1D | ✅ |
| 3 | alternative.me | FGI, FGI 趋势 | 1D | ✅ |
| 4 | Blockchain.info | hash_rate, miners_revenue | 1D | ✅ |
| 5 | OKX 公开 API | funding_rate, liquidation, OI | 1H | ✅ |
| 6 | DefiLlama | stablecoin_supply, TVL | 1D | ✅ |
| 7 | 币安 Web3 Social | social_hype | 1H | ✅ |
| 8 | 币安 Web3 Smart Money | smart_money_direction | 1H | ✅ |

#### 3.1.3 本地缓存

- SQLite 缓存到 `data/macro_cache/macro_{symbol}.db`
- 缓存有效期：1H 数据 1 小时、1D 数据 1 天
- 回测时优先读缓存，保证可重现
- 采集失败时 `data_source="missing"`，特征模块自动跳过该字段（不兜底 Mock）

#### 3.1.4 时间对齐与未来函数防护

```python
def align_to_klines(self, macro_list, kline_index, lookahead_guard=1):
    """
    将宏观数据对齐到 K 线时间戳
    
    规则:
    1. 宏观数据时间戳 t_macro
    2. K 线时间戳 t_kline
    3. 只有当 t_macro <= t_kline - lookahead_guard * bar_size 时才填充
    4. 否则填充 None（特征模块自动跳过）
    """
```

- `lookahead_guard=1` 表示宏观数据必须比 K 线收盘早至少 1 根 K 线
- 对于 1H K 线，宏观数据发布后至少 1 小时才能被使用
- 对于 1D 数据（如 FGI），使用前一天的数据

### 3.2 MacroFeatures 宏观特征模块

#### 3.2.1 设计

新建 [bcrm2/macro_features.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/macro_features.py)，约 20-30 个特征，**不参与卦象推导**（纯 ML 增强）。

```python
@FeatureRegistry.register("macro", requires_macro_df=True, default_enabled=True)
class MacroFeatures:
    """宏观基本面特征模块"""
    
    def compute(self, df: pd.DataFrame, macro_df: pd.DataFrame = None) -> pd.DataFrame:
        if macro_df is None or macro_df.empty:
            # 宏观数据缺失时返回空 DataFrame（不兜底 Mock）
            return pd.DataFrame(index=df.index)
        
        features = {}
        
        # ── 情绪维度（5 个）──
        features["fgi_zscore"] = self._zscore(macro_df["fear_greed_index"], 30)
        features["fgi_trend_7d"] = macro_df["fear_greed_trend_7d"]
        features["fgi_extreme_fear"] = (macro_df["fear_greed_index"] < 25).astype(int)
        features["fgi_extreme_greed"] = (macro_df["fear_greed_index"] > 75).astype(int)
        features["fgi_divergence"] = self._divergence(df, macro_df["fear_greed_index"])
        
        # ── 资金/衍生品维度（5 个）──
        features["funding_rate_zscore"] = self._zscore(macro_df["funding_rate"], 48)
        features["funding_extreme_positive"] = (features["funding_rate_zscore"] > 2).astype(int)
        features["funding_extreme_negative"] = (features["funding_rate_zscore"] < -2).astype(int)
        features["oi_change_rate"] = macro_df["open_interest_usd"].pct_change(12)
        features["oi_divergence"] = self._divergence(df, macro_df["open_interest_usd"])
        
        # ── 流动性维度（4 个）──
        features["stablecoin_growth"] = macro_df["stablecoin_supply"].pct_change(24)
        features["tvl_change_7d"] = macro_df["tvl_change_7d"]
        features["liquidity_expanding"] = (features["stablecoin_growth"] > 0).astype(int)
        features["liquidity_contracting"] = (features["stablecoin_growth"] < -0.02).astype(int)
        
        # ── 链上维度（3 个，仅 BTC 相关）──
        features["hash_rate_trend"] = macro_df["hash_rate"].pct_change(24)
        features["miners_revenue_zscore"] = self._zscore(macro_df["miners_revenue"], 30)
        features["miner_accumulation"] = (features["hash_rate_trend"] > 0).astype(int)
        
        # ── 聪明钱/社交维度（4 个）──
        features["smart_money_direction"] = macro_df["smart_money_direction"]
        features["smart_money_divergence"] = self._divergence(df, macro_df["smart_money_direction"])
        features["social_hype_zscore"] = self._zscore(macro_df["social_hype_score"], 48)
        features["hype_extreme"] = (features["social_hype_zscore"].abs() > 2).astype(int)
        
        # ── 估值维度（4 个）──
        features["market_cap_rank"] = macro_df["market_cap_rank"]
        features["ath_drop_pct"] = macro_df["ath_drop_pct"]
        features["supply_ratio"] = macro_df["supply_ratio"]
        features["undervalued"] = (macro_df["ath_drop_pct"] < -0.5).astype(int)
        
        return pd.DataFrame(features, index=df.index)
```

#### 3.2.2 特征清单

共 **25 个特征**，分 6 个维度：

| 维度 | 特征数 | 特征列表 |
|------|:------:|----------|
| 情绪 | 5 | fgi_zscore, fgi_trend_7d, fgi_extreme_fear, fgi_extreme_greed, fgi_divergence |
| 资金/衍生品 | 5 | funding_rate_zscore, funding_extreme_positive, funding_extreme_negative, oi_change_rate, oi_divergence |
| 流动性 | 4 | stablecoin_growth, tvl_change_7d, liquidity_expanding, liquidity_contracting |
| 链上 | 3 | hash_rate_trend, miners_revenue_zscore, miner_accumulation |
| 聪明钱/社交 | 4 | smart_money_direction, smart_money_divergence, social_hype_zscore, hype_extreme |
| 估值 | 4 | market_cap_rank, ath_drop_pct, supply_ratio, undervalued |

#### 3.2.3 适用性

- 链上维度（hash_rate / miners_revenue）仅对 BTC 有意义，非 BTC 币种自动返回 None
- 美股永续（MU / SKHYNIX / GOOGL / NVDA / AMZN）的 funding_rate / OI 仍有效（OKX 衍生品），但 FGI / stablecoin / TVL 作为市场整体指标仍适用
- 贵金属（XAU / XAG）的加密特有指标返回 None，特征模块自动跳过

### 3.3 P1 交付物

| 交付物 | 路径 | 说明 |
|--------|------|------|
| MacroDataFetcher | `bcrm2/macro_data_fetcher.py` | 8 源采集 + SQLite 缓存 + 时间对齐 |
| MacroFeatures | `bcrm2/macro_features.py` | 25 个宏观特征，注册到 Registry |
| 回测集成 | `bcrm2/walk_forward_backtester.py` | 传入 macro_df 给 Registry |
| 实盘集成 | `scripts/memory_l4/bcrm2_adapter.py` | 传入 macro_df 给 Registry |
| 缓存目录 | `data/macro_cache/` | SQLite 缓存文件 |
| 单元测试 | `tests/test_macro_features.py` | 特征计算 + 时间对齐 + 缺失处理 |
| 回测对比报告 | `data/baseline/baseline_v1_vs_v2_comparison.json` | 基线对比 + 显著性检验 |

---

## 四、基线验证机制

### 4.1 BaselineManager

新建 [bcrm2/baseline_manager.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/baseline_manager.py)：

```python
class BaselineManager:
    """严格基线验证：全维度不劣化 + 显著性检验"""
    
    CORE_METRICS = ["sharpe", "win_rate", "profit_factor"]
    RISK_METRICS = ["max_drawdown"]
    COMPREHENSIVE_METRICS = ["calmar", "total_return"]
    
    DEGRADATION_TOLERANCE = {
        "sharpe": 0.05,         # 夏普不劣化 5%
        "win_rate": 0.05,       # 胜率不劣化 5%
        "profit_factor": 0.05,  # 盈亏比不劣化 5%
        "max_drawdown": 0.10,   # 最大回撤不恶化 10%
        "calmar": 0.05,         # Calmar 不劣化 5%
    }
    
    def snapshot(self, backtest_result: dict, version: str) -> Path:
        """保存基线快照"""
        ...
    
    def compare(self, new_result: dict, baseline_version: str = "v1") -> ComparisonReport:
        """
        对比新版本与基线
        
        返回 ComparisonReport:
            - all_metrics: 各指标的对比值和 p-value
            - passed: 是否通过（全维度不劣化 + 至少 1 项显著提升）
            - significant_improvements: 显著提升的指标列表
            - degradations: 劣化的指标列表
            - recommendation: "live" | "exploratory"
        """
        ...
    
    def _bootstrap_pvalue(self, baseline_returns, new_returns, metric: str, 
                          n_resamples: int = 1000) -> float:
        """bootstrap 重采样计算 p-value"""
        ...
```

### 4.2 验证规则

**通过条件（全部满足才可实盘）**：

1. **全维度不劣化**：所有核心+风控指标在容差范围内不劣化
   - 夏普、胜率、盈亏比：不劣化 5%
   - 最大回撤：不恶化 10%
   - Calmar：不劣化 5%

2. **至少 1 项显著提升**：核心指标中至少 1 项 bootstrap p-value < 0.05
   - p-value 通过 1000 次 bootstrap 重采样计算

3. **无过拟合信号**：
   - walk-forward 各 fold 的提升方向一致（不允许某 fold 大涨某 fold 大跌）
   - 训练集 vs 验证集指标差距不超过 30%（防止过拟合训练集）

**不通过时的处理**：

```json
{
  "version": "v2-macro-features",
  "baseline_version": "v1",
  "passed": false,
  "recommendation": "exploratory",
  "reason": "profit_factor 劣化 8% (超过 5% 容差)",
  "significant_improvements": [],
  "degradations": ["profit_factor"],
  "action": "标记为探索方向，不进入实盘配置，继续调研特征工程优化"
}
```

### 4.3 回测对比脚本

新建 [bcrm2/run_baseline_comparison.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/run_baseline_comparison.py)：

```bash
# 用法
python -m scripts.memory_l4.bcrm2.run_baseline_comparison \
    --coins BTC,ETH,SOL,UNI \
    --baseline-version v1 \
    --output data/baseline/v1_vs_v2_comparison.json
```

输出对比报告 + 可视化图表（夏普/胜率/盈亏比/回撤的柱状对比图）。

---

## 五、数据流架构

### 5.1 整体数据流

```
┌─────────────────────────────────────────────────────────────────┐
│                        免费数据源 API                            │
│  Hyperliquid | CoinGecko | alternative.me | Blockchain.info     │
│  OKX | DefiLlama | Binance Web3 Social | Binance Smart Money    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MacroDataFetcher                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ 8 源采集器  │→│ SQLite 缓存  │→│ 时间对齐 (forward-fill) │ │
│  │             │  │ macro_X.db  │  │ lookahead_guard=1      │ │
│  └─────────────┘  └──────────────┘  └───────────┬────────────┘ │
└──────────────────────────────────────────────────┼──────────────┘
                                                   │ macro_df
                                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FeatureRegistry.compute_all()                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  bagua(111) │ classic(30) │ fib(10) │ pivot(10)        │   │
│  │  rsi(8)     │ wdh(45)     │ cycle(55) │ market_cap(10) │   │
│  │  cross(33)  │ merrill(55) │ meta_v2(25)               │   │
│  │  ───────── P1 新增 ─────────                          │   │
│  │  macro(25)                                             │   │
│  └────────────────────────────┬────────────────────────────┘   │
│                               │                                 │
│                features + feature_names_by_gua                  │
└───────────────────────────────┼─────────────────────────────────┘
                                │
               ┌────────────────┴────────────────┐
               │                                  │
               ▼                                  ▼
    ┌──────────────────┐              ┌──────────────────┐
    │  walk_forward     │              │  bcrm2_adapter   │
    │  _backtester      │              │  (实盘推理)       │
    │  (回测)           │              │                  │
    └────────┬─────────┘              └────────┬─────────┘
             │                                  │
             ▼                                  ▼
    ┌──────────────────┐              ┌──────────────────┐
    │ BaselineManager  │              │  BCRM2 L1/L2/L3  │
    │ .compare()       │              │  辩证裁决         │
    │ 通过→实盘         │              │                  │
    │ 不通过→探索       │              └──────────────────┘
    └──────────────────┘
```

### 5.2 回测时的数据流

```
1. 加载 K 线历史数据 (OHLCV)
2. MacroDataFetcher.fetch_all(symbol, since) → 从缓存读取历史宏观数据
3. MacroDataFetcher.align_to_klines(macro, kline_index, lookahead_guard=1)
4. FeatureRegistry.compute_all(df, macro_df=macro_aligned)
5. walk-forward 训练 + 验证
6. BaselineManager.compare(new_result, "v1")
7. 输出对比报告
```

### 5.3 实盘时的数据流

```
1. 获取最新 K 线 (OHLCV)
2. MacroDataFetcher.fetch_all(symbol, since=now-7d) → 采集 + 缓存
3. MacroDataFetcher.align_to_klines(macro, kline_index, lookahead_guard=1)
4. FeatureRegistry.compute_all(df, macro_df=macro_aligned)
5. BCRM2 L1→L2→L3 推理
6. 五角校验 + A7 门禁
7. 开仓/持仓决策
```

---

## 六、风险与缓解

### 6.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|:----:|:----:|----------|
| P0 重构引入 bug 导致特征值变化 | 中 | 高 | 回归测试：重构前后特征矩阵 `assert_frame_equal` 容差 1e-6 |
| 宏观数据源 API 限流/不可用 | 高 | 中 | SQLite 缓存 + 采集失败返回 None（不兜底 Mock） |
| 宏观特征引入未来函数 | 低 | 极高 | `lookahead_guard=1` + 单元测试验证时间对齐 |
| 基线对比过拟合到特定时间段 | 中 | 高 | walk-forward 多 fold + bootstrap p-value |
| 实盘宏观数据延迟导致信号滞后 | 中 | 中 | 1H 级别 K 线，1 小时延迟可接受 |

### 6.2 策略风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|:----:|:----:|----------|
| 宏观特征不提升甚至劣化回测指标 | 中 | 中 | 标记为探索方向，不进入实盘，继续优化 |
| 25 个宏观特征过多导致维度灾难 | 低 | 中 | FeatureSelector 已有双层筛选（重要性 + 相关性去冗余） |
| 非加密币种（XAU/美股）宏观特征缺失 | 高 | 低 | 特征模块自动跳过 None 字段，不影响其他特征 |

---

## 七、实施计划

### 7.1 P0 实施步骤

| 步骤 | 内容 | 依赖 |
|:----:|------|------|
| 1 | 创建 `FeatureRegistry` 类 | 无 |
| 2 | 11 个模块自注册改造（每个文件顶部加 `@register`） | 步骤 1 |
| 3 | 重构 `walk_forward_backtester.py` 改为调用 `Registry.compute_all()` | 步骤 2 |
| 4 | 重构 `bcrm2_adapter.py` 改为调用 `Registry.compute_all()` | 步骤 2 |
| 5 | 编写回归测试 `test_feature_registry.py` | 步骤 3,4 |
| 6 | 跑回归测试，确认特征值不变 | 步骤 5 |
| 7 | 跑 15 币种完整回测，保存基线快照 | 步骤 6 |
| 8 | git tag `baseline-v1` | 步骤 7 |

### 7.2 P1 实施步骤

| 步骤 | 内容 | 依赖 |
|:----:|------|------|
| 1 | 创建 `MacroDataFetcher`（8 源采集 + SQLite 缓存） | P0 完成 |
| 2 | 实现时间对齐 `align_to_klines()` + 未来函数防护 | 步骤 1 |
| 3 | 创建 `MacroFeatures` 模块（25 个特征） + 注册到 Registry | 步骤 1 |
| 4 | 回测集成：`walk_forward_backtester` 传入 macro_df | 步骤 2,3 |
| 5 | 实盘集成：`bcrm2_adapter` 传入 macro_df | 步骤 2,3 |
| 6 | 编写单元测试 `test_macro_features.py` | 步骤 3 |
| 7 | 跑回测 + `BaselineManager.compare()` | 步骤 4,6 |
| 8 | 通过→实盘 / 不通过→标记探索方向 | 步骤 7 |

### 7.3 P0-P1 分开交付

- **P0 交付**：FeatureRegistry + 模块对齐 + 基线快照 + 回归测试通过
- **P1 交付**：MacroDataFetcher + MacroFeatures + 回测对比报告

P0 交付后需用户确认基线可信，再启动 P1。

### 7.4 模块注册名约定

为避免文档与代码不一致，注册名统一使用 snake_case，与文件名主干一致：

| 文件 | 注册名 | 类名 |
|------|--------|------|
| bagua_feature_engine.py | `bagua` | BaguaFeatureEngine |
| classic_experience_features.py | `classic_exp` | ClassicExperienceFeatures |
| fibonacci_features.py | `fibonacci` | FibonacciFeatures |
| pivot_point_features.py | `pivot_point` | PivotPointFeatures |
| rsi_sentiment_features.py | `rsi_sentiment` | RSISentimentFeatures |
| wdh_features.py | `wdh` | WDHFeatures |
| cycle_features.py | `cycle` | CycleFeatures |
| market_cap.py | `market_cap` | MarketCapClassifier |
| cross_asset_features.py | `cross_asset` | (函数式，需包装为类) |
| merrill_clock_features.py | `merrill_clock` | MerrillClockFeatures |
| meta_labeling_features_v2.py | `meta_labeling_v2` | MetaLabelingFeaturesV2 |
| macro_features.py (P1 新增) | `macro` | MacroFeatures |

---

## 八、验收标准

### 8.1 P0 验收

- [ ] `FeatureRegistry` 实现完成，支持注册/计算/列表
- [ ] 11 个特征模块全部自注册
- [ ] `walk_forward_backtester` 和 `bcrm2_adapter` 统一调用 `Registry.compute_all()`
- [ ] 回归测试通过：重构前后特征矩阵 `assert_frame_equal` 容差 1e-6
- [ ] 基线快照 `baseline_v1.json` 已保存
- [ ] git tag `baseline-v1` 已打

### 8.2 P1 验收

- [ ] `MacroDataFetcher` 实现 8 源采集 + SQLite 缓存 + 时间对齐
- [ ] `MacroFeatures` 实现 25 个特征并注册到 Registry
- [ ] 单元测试通过：特征计算 + 时间对齐 + 缺失处理
- [ ] 回测对比报告生成
- [ ] `BaselineManager.compare()` 输出明确的通过/不通过结论
- [ ] 通过→实盘配置更新 / 不通过→标记探索方向

---

## 九、附录

### 9.1 相关文件索引

| 类别 | 文件 |
|------|------|
| **特征工程** | [bagua_feature_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/bagua_feature_engine.py) |
| | [meta_labeling_features_v2.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/meta_labeling_features_v2.py) |
| | [feature_selector.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/feature_selector.py) |
| **回测/实盘入口** | [walk_forward_backtester.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/walk_forward_backtester.py) |
| | [bcrm2_adapter.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2_adapter.py) |
| **ML 引擎** | [dialectical_ml_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/dialectical_ml_engine.py) |
| **已有数据源** | [free_fundamental_provider.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/capabilities/trading/free_fundamental_provider.py) |
| **技术文档** | [TECHNICAL_DESIGN.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/docs/TECHNICAL_DESIGN.md) |

### 9.2 基线指标权重与容差

| 指标 | 类别 | 容差 | 说明 |
|------|------|:----:|------|
| 夏普比率 | 核心 | 5% | 风险调整后收益 |
| 胜率 | 核心 | 5% | 盈利交易占比 |
| 盈亏比 | 核心 | 5% | 平均盈利/平均亏损 |
| 最大回撤 | 风控 | 10% | 峰值到谷值最大跌幅 |
| Calmar | 综合 | 5% | 年化收益/最大回撤 |
| 总收益 | 综合 | — | 至少 1 项 p<0.05 显著提升 |
