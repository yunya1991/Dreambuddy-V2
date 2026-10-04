# 洗盘 vs 真弱势判定系统 — WashoutDetector / WashoutClassifier 设计 Spec

> 日期: 2026-09-21
> 状态: 设计已确认 → 待写实现计划
> 关联文档:
> - [持仓与离场管理层 ExitManager 策略链](2026-08-20-exit-manager-design.md)（新增 WashoutHoldStrategy priority=15）
> - [BCRM 2.0 满仓算力倾斜 + 三维度离场时机优化](2026-08-18-bcrm2-mode-evolution-design.md)（WashoutDetector 接入点）
> - [数据清洗与 Feature Hub](2026-08-24-data-cleaning-and-feature-hub-spec.md)（CVD/OFI 走奖章架构）
> - [自进化系统架构](2026-08-19-market-morphology-evolution-design.md)（WashoutClassifier 作为自进化子模块）
> 实现策略: **先后后自进化**（WashoutDetector 在 BCRM2.0 先落地 → WashoutClassifier 在自进化后落地）
> 方法论: **严格 TDD**（RED spec 测试 → 实现 → GREEN 验证）
> 回滚铁律: ENABLE_WASHOUT_DETECTOR=False 时，BCRM2.0 与自进化链路字节等价"洗盘判定不存在"
> 硬约束记忆: VM-1789991697324-a06c95f9 (B级)

---

## 1. 动机与背景

### 1.1 问题陈述

当前系统在持仓后面对"价格回调"时无法区分**洗盘**（庄家震仓、散户出局、回调后继续上涨）与**真弱势**（基本面恶化、趋势反转、持续下跌）。这导致：

- **过早止损离场**：把洗盘当真弱势，止损被庄家精准扫掉后价格反弹
- **过晚止损离场**：把真弱势当洗盘，硬扛直到深度亏损
- **exit_strategies.py 6 个策略**（P3/SignalReverse/EvForceClose/Timeout/RankedTp/EvAdjust）均基于 EV/信号反转/超时，缺乏"洗盘 vs 弱势"语义判定

用户提供的 UNI 分析框架触发本设计：

| 维度 | 洗盘特征 | 真弱势特征 |
|---|---|---|
| 成交量 | 缩量整理 | 放量下跌 |
| 支撑位 | 不破关键支撑 | 连续破位 |
| 振幅 | 逐渐收窄 | 持续扩大 |
| 持仓量 | 稳定或微增 | 大幅减少 |
| 消息面 | 无重大利空 | 有负面催化 |
| 大盘联动 | 独立整理 | 跟随下跌 |

### 1.2 目标

- **BCRM2.0 侧**: 在 `bcrm2/` 新增 `WashoutDetector`，融合 8 维特征输出 `WashoutVerdict`，作为 `is_trial=True` 独立子池最多 2 单
- **自进化侧**: 在 `dreamos/evolution/` 新增 `WashoutClassifier`，用 KNN/CBR + 贝叶斯闭环（禁用 LLM），复用 `_sandbox_validate()` 沙箱验证
- **数据源侧**: 在 `18-数据获取中心` 新增 CVD / OFI / L-S Ratio 采集器，遵循奖章架构 Bronze→Silver→Gold
- **退出策略侧**: 在 `exit_strategies.py` 新增 `WashoutHoldStrategy` (priority=15)，洗盘判定下继续持有，真弱势判定下加速离场

### 1.3 设计原则

- **开关形式默认关闭**: `ENABLE_WASHOUT_DETECTOR=False`，触发条件为"币种经历一定上涨后出现回调"才激活
- **KNN/CBR + 贝叶斯**: WashoutClassifier 禁用 LLM，倾向深度学习不倾向大语言模型
- **数据驱动**: 核心是统计学-抽象模型-多路径计算-寻找最小阻力
- **模块化集成**: BCRM2.0/自进化系统/BDSM 作为模块集成，而非独立实现
- **FAIL-OPEN 铁律**: 任何异常→中性兜底（WashoutVerdict.unknown）+6 层堆栈日志，绝不阻塞交易

---

## 2. 调研结论：洗盘 vs 真弱势 12+4 维度框架

### 2.1 传统金融 12 维度

| # | 维度 | 洗盘特征 | 真弱势特征 | 量化指标 |
|---|---|---|---|---|
| 1 | 成交量 | 缩量整理（≤ vol_ma20 × 0.8） | 放量下跌（≥ vol_ma20 × 1.5） | `volume_ratio` |
| 2 | 支撑位 | 不破关键支撑（3 次守住） | 连续破位（破支撑后无回收） | `support_holds_count` |
| 3 | 下跌速度/角度 | 缓坡 45-60° | 垂直下跌 >70° | `decline_angle_deg` |
| 4 | 振幅 | 逐渐收窄（ATR 5d < ATR 20d） | 持续扩大（ATR 5d > ATR 20d） | `atr_compress_ratio` |
| 5 | 持仓量 | 稳定或微增（OI 变化 < ±5%） | 大幅减少（OI 减少 > 10%） | `oi_change_rate` |
| 6 | 位置 | 低位（cycle_position_365d < 0.3） | 高位（cycle_position_365d > 0.7） | `cycle_position_365d` |
| 7 | 时间 | 1-5 天（短期回调） | 数周（长期下跌） | `decline_duration_days` |
| 8 | 反弹力度 | 5 日内收复 50%+ | 反弹弱（< 30%） | `rebound_ratio_5d` |
| 9 | 消息面 | 无重大利空 | 有负面催化 | `news_negative_score` |
| 10 | 大盘联动 | 独立整理（相关性 < 0.5） | 跟随下跌（相关性 > 0.7） | `btc_correlation_30d` |
| 11 | 情绪 | 骂声一片（散户恐慌） | 沉默（无人关注） | `social_hype_zscore` |
| 12 | Wyckoff Climax | 3 阶段见底信号 | 无 climax 信号 | `wyckoff_climax_stage` |

### 2.2 加密货币 4 独有维度

| # | 维度 | 洗盘特征 | 真弱势特征 | 量化指标 |
|---|---|---|---|---|
| 13 | OI×Price 四象限 | OI↑+Price↓=空头建仓（看多反向） | OI↓+Price↓=多头投降（本地底部反转前兆） | `oi_price_quadrant` |
| 14 | Funding Rate | 持续负（空头偏向，洗多头） | 突然转正（反转信号） | `funding_rate_zscore` |
| 15 | CVD (Cumulative Volume Delta) | CVD 下行但价格守住（trapped trader fakeout） | CVD 与价格同步下行 | `cvd_price_divergence` |
| 16 | OFI (Order Flow Imbalance) 标准差 | 低 OFI 方差 + 高 volume（可疑洗盘） | 高 OFI 方差 + 持续卖压 | `ofi_std_20d` |

### 2.3 Wyckoff Selling Climax 3 阶段

| 阶段 | 时长 | 特征 | 判定 |
|---|---|---|---|
| Stage 1: Panic | 5-10min | downtick 占比 > 75%，跌 1-3% | `panic_downtick_pct > 0.75` + `panic_decline_pct ∈ [0.01, 0.03]` |
| Stage 2: Sustained | 5-10min | downtick 占比 > 80%，volume 2-3x 均量，跌 3-5% | `sustained_volume_ratio ∈ [2.0, 3.0]` + `sustained_decline_pct ∈ [0.03, 0.05]` |
| Stage 3: Exhaustion | 1-5min | 量能衰减，速度放缓，ask volume 下降 | `exhaustion_volume_decline > 0.3` + `exhaustion_speed_drop > 0.3` |

**Climax 触发**: `volume ≥ 2 × 20日均线` 且 `价格跌破 20d 低点`
**失效**: 后续下跌量更大 → 视为真弱势非 climax

### 2.4 现有系统映射

| 已有能力 | 文件 | 复用方式 |
|---|---|---|
| MA200/MA50/MA20、cycle_position_365d、dow_hhhl、volume_trend_conf | `bcrm2/indicators.py` IndicatorBank (12 指标) | 直接复用，不重写 |
| funding_rate_zscore, oi_change_rate, funding_divergence, oi_liq_pressure, funding_extreme_positive/negative | `bcrm2/macro_features.py` MacroFeatures | 直接复用 |
| BTC-ETH 相关性、beta、联动方向 | `bcrm2/cross_asset_features.py` | 复用大盘联动维度 |
| 牛熊分界线、Elder-ray、三屏系统 | `bcrm2/classic_experience_features.py` | 复用技术指标维度 |
| 6 个 ExitStrategy 子类 | `bcrm2/exit_strategies.py` | 新增 WashoutHoldStrategy priority=15 |
| FeatureRegistry | `bcrm2/feature_registry.py`（已提升至 `21-特征工程中心/feature_hub/hub/`） | 注册新特征 |
| EvolutionEngine: evolve() / analyze_trades() / _sandbox_validate() / _check_orchestration_optimization() | `dreamos/evolution/engine.py` | WashoutClassifier 复用沙箱验证 |
| Lesson / GapAnalysis / OptimizationSuggestion / EvolutionReport | `dreamos/evolution/types.py` | 复用 dataclass |
| reward = tanh(pnl_pct / 0.02) 归一化 | 自进化系统硬约束 | WashoutClassifier 训练 reward |

**grep 确认**: `bcrm2/` 下无 `wash|climax|capitulation|洗盘|投降` 任何匹配 → 洗盘判定为新模块

---

## 3. 系统架构

### 3.1 总体架构

```
polling_trader._execute_trade(coin, inference)
  ├─ 基础数据准备
  ├─ 静态 SLTP 检查（核心层，不动）
  ├─ ExitManager.evaluate(coin, inference, pos_info, ...)
  │    ├─ priority=10: P3EarlyExitStrategy
  │    ├─ priority=15: WashoutHoldStrategy  ← 【新增】洗盘/真弱势判定
  │    ├─ priority=20: SignalReverseStrategy
  │    ├─ priority=30: EvForceCloseStrategy
  │    ├─ priority=40: TimeoutProfitSwitchStrategy
  │    ├─ priority=50: RankedTpStrategy
  │    └─ priority=60: EvAdjustStrategy
  └─ WashoutDetector（仅在 BCRM2.0 is_trial 子池触发）
       ├─ 触发门：上涨后回调检测
       ├─ 8 维特征融合器
       └─ WashoutVerdict 输出
            ├─ WashoutDetector.run() → WashoutVerdict
            └─ WashoutClassifier.predict() → Bayesian posterior P(washout|features)
                 ↑（自进化侧，BCRM2.0 落地后启用）
```

### 3.2 三层分工

| 层 | 职责 | 模块 | 落地阶段 |
|---|---|---|---|
| **L1 触发门** | 检测"币种经历一定上涨后出现回调"才激活，非全程运行 | WashoutDetector.trigger_gate() | W1 |
| **L2 特征融合器** | 8 维特征（成交量/支撑位/振幅/OI/位置/反弹/消息面/大盘联动）+ 4 维加密独有（OI×Price/Funding/CVD/OFI）融合 | WashoutDetector.extract_features() | W2 |
| **L3 判定器** | WashoutVerdict 输出（washout/weakness/unknown）+ 置信度 | WashoutDetector.classify() → WashoutClassifier.predict() | W3/W4 |

### 3.3 开关架构

```python
# 顶层总开关
ENABLE_WASHOUT_DETECTOR: bool = False  # 默认关闭

# 子开关（按维度）
WASHOUT_CONFIG = {
    "enable_volume_dim": True,         # 维度1: 成交量
    "enable_support_dim": True,        # 维度2: 支撑位
    "enable_amplitude_dim": True,      # 维度3: 振幅
    "enable_oi_dim": True,             # 维度4: 持仓量
    "enable_position_dim": True,       # 维度5: 位置
    "enable_rebound_dim": True,        # 维度6: 反弹力度
    "enable_news_dim": True,           # 维度7: 消息面
    "enable_market_dim": True,         # 维度8: 大盘联动
    "enable_oi_price_quadrant": True,  # 加密独有1: OI×Price
    "enable_funding_rate": True,       # 加密独有2: Funding
    "enable_cvd": True,                # 加密独有3: CVD（需数据源 W3）
    "enable_ofi": True,                # 加密独有4: OFI（需数据源 W3）
    "enable_wyckoff_climax": True,     # Wyckoff climax 3 阶段
}
```

**关断时等价性**: `ENABLE_WASHOUT_DETECTOR=False` 时，`WashoutDetector.run()` 直接返回 `WashoutVerdict.unknown()`，所有子开关失效，BCRM2.0 与自进化链路字节等价"洗盘判定不存在"。

---

## 4. 模块一：WashoutDetector（BCRM2.0 侧）

### 4.1 文件位置

```
11-易经推理系统/scripts/memory_l4/bcrm2/
  ├── washout_detector.py        # WashoutDetector 主类 + WashoutVerdict dataclass
  ├── washout_features.py        # 8 维 + 4 加密独有特征提取器
  └── washout_trigger_gate.py    # 触发门逻辑
```

### 4.2 WashoutVerdict 数据契约

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional


class WashoutLabel(Enum):
    WASHOUT = "washout"        # 洗盘 → 持有
    WEAKNESS = "weakness"      # 真弱势 → 加速离场
    UNKNOWN = "unknown"        # 不确定 → 维持现状


@dataclass(frozen=True)
class WashoutVerdict:
    """WashoutDetector 输出契约。"""
    label: WashoutLabel
    confidence: float                       # [0.0, 1.0]
    trigger_activated: bool                 # 是否通过触发门
    feature_snapshot: Dict[str, float]      # 8+4 维特征快照
    reason: str                             # 触发原因摘要
    timestamp: str                          # ISO 8601 UTC

    @staticmethod
    def unknown() -> "WashoutVerdict":
        """FAIL-OPEN 兜底返回。"""
        return WashoutVerdict(
            label=WashoutLabel.UNKNOWN,
            confidence=0.0,
            trigger_activated=False,
            feature_snapshot={},
            reason="unknown_fallback",
            timestamp="",
        )

    def to_dict(self) -> Dict:
        """序列化用于 log/传输。"""
        ...

    @classmethod
    def from_dict(cls, d: Dict) -> "WashoutVerdict":
        """反序列化，1000 roundtrip 无损。"""
        ...
```

### 4.3 触发门 TriggerGate

```python
class WashoutTriggerGate:
    """洗盘判定触发门：仅在'上涨后回调'场景激活，非全程运行。"""

    # 触发条件：
    #   1. 过去 N 天（默认 30d）内涨幅 >= min_runup_pct（默认 0.15，即 15%）
    #   2. 当前价格较 N 天高点回撤 >= min_drawdown_pct（默认 0.05，即 5%）
    #   3. 价格仍在 MA200 之上（避免熊市假信号）

    def __init__(
        self,
        min_runup_pct: float = 0.15,
        min_drawdown_from_high: float = 0.05,
        runup_lookback_days: int = 30,
        require_above_ma200: bool = True,
    ):
        ...

    def should_activate(self, df: pd.DataFrame) -> bool:
        """检测是否满足触发条件。"""
        ...
```

### 4.4 8 维 + 4 加密独有特征明细

| # | 特征名 | 计算逻辑 | 数据源 | 开关 |
|---|---|---|---|---|
| F1 | `volume_ratio_20d` | vol / vol_ma20 | OHLCV (CCXT) | enable_volume_dim |
| F2 | `support_holds_count` | 近 30d swing low 守住次数 | OHLCV (CCXT) | enable_support_dim |
| F3 | `atr_compress_ratio` | ATR_5d / ATR_20d | OHLCV (CCXT) | enable_amplitude_dim |
| F4 | `oi_change_rate_7d` | (OI_t - OI_{t-7d}) / OI_{t-7d} | CoinGlass/Coinglass | enable_oi_dim |
| F5 | `cycle_position_365d` | (price - low_365d) / (high_365d - low_365d) | OHLCV (CCXT) | enable_position_dim |
| F6 | `rebound_ratio_5d` | (price_t - low_5d) / (high_5d - low_5d) | OHLCV (CCXT) | enable_rebound_dim |
| F7 | `news_negative_score` | 负面新闻占比（来自现有 news_collectors） | NewsCollectors | enable_news_dim |
| F8 | `btc_correlation_30d` | corr(coin_ret, btc_ret, 30d) | OHLCV (CCXT) | enable_market_dim |
| F9 | `oi_price_quadrant` | OI↑Price↓ / OI↓Price↓ / OI↑Price↑ / OI↓Price↑ | CoinGlass | enable_oi_price_quadrant |
| F10 | `funding_rate_zscore` | (funding - mean) / std (30d) | CoinGlass | enable_funding_rate |
| F11 | `cvd_price_divergence` | corr(CVD, price, 7d) — 负值=trapped trader | CVD collector (W3 新增) | enable_cvd |
| F12 | `ofi_std_20d` | OFI 20d 标准差 | OFI collector (W3 新增) | enable_ofi |
| F13 | `wyckoff_climax_stage` | 0/1/2/3 阶段 | 内生计算（基于成交 + 价格） | enable_wyckoff_climax |

### 4.5 WashoutDetector 主类

```python
class WashoutDetector:
    """洗盘 vs 真弱势判定器（BCRM2.0 侧）。

    开关形式默认关闭，触发条件激活后输出 WashoutVerdict。
    """

    def __init__(
        self,
        config: Optional[Dict] = None,        # WASHOUT_CONFIG
        enable: bool = False,                  # ENABLE_WASHOUT_DETECTOR
        trigger_gate: Optional[WashoutTriggerGate] = None,
        classifier: Optional["WashoutClassifier"] = None,  # W4 注入
    ):
        self.enable = enable
        self.config = config or WASHOUT_CONFIG
        self.trigger_gate = trigger_gate or WashoutTriggerGate()
        self.classifier = classifier  # W4 阶段才注入，W1-W3 为 None

    def run(self, coin: str, df: pd.DataFrame, macro_data: Dict) -> WashoutVerdict:
        """主入口。

        Args:
            coin: 币种符号
            df: OHLCV DataFrame，至少 365d 历史
            macro_data: 宏观特征字典（含 OI/funding/news 等）

        Returns:
            WashoutVerdict
        """
        if not self.enable:
            return WashoutVerdict.unknown()

        try:
            if not self.trigger_gate.should_activate(df):
                return WashoutVerdict.unknown()

            features = self.extract_features(coin, df, macro_data)
            if self.classifier is None:
                # W1-W3 阶段：规则化判定
                verdict = self._rule_based_classify(features)
            else:
                # W4 阶段：KNN/CBR + 贝叶斯
                verdict = self.classifier.predict(features)

            return verdict

        except Exception as e:
            # FAIL-OPEN 铁律
            logger.error(f"WashoutDetector FAIL-OPEN: {e}\n{traceback.format_exc()}")
            return WashoutVerdict.unknown()

    def extract_features(self, coin: str, df: pd.DataFrame, macro_data: Dict) -> Dict[str, float]:
        """8 维 + 4 加密独有 + Wyckoff climax 特征提取。"""
        ...

    def _rule_based_classify(self, features: Dict[str, float]) -> WashoutVerdict:
        """W1-W3 阶段规则化判定（W4 后由 WashoutClassifier 替代）。"""
        ...
```

### 4.6 接入点：is_trial 子池

**硬约束**: WashoutDetector 作为 `is_trial=True` 独立子池，最多 2 单（复用 `MAX_TRIAL_POSITIONS = 2`）。

```python
# polling_trader.py 或 BCRM2.0 调用入口
def _should_apply_washout_detector(coin: str, positions: List) -> bool:
    """检查当前币种是否进入 WashoutDetector 子池。

    Returns:
        True if 该子池 < MAX_TRIAL_POSITIONS 且 ENABLE_WASHOUT_DETECTOR=True
    """
    if not ENABLE_WASHOUT_DETECTOR:
        return False
    washout_trial_count = sum(
        1 for p in positions
        if p.get("source_tag") == "washout_trial" and p.get("is_trial", False)
    )
    return washout_trial_count < MAX_TRIAL_POSITIONS
```

**开仓标记**: WashoutDetector 触发的仓位 `source_tag='washout_trial'`，`is_trial=True`，与其他 BCRM 测试仓共享 `MAX_TRIAL_POSITIONS = 2` 上限。

---

## 5. 模块二：WashoutClassifier（自进化侧）

### 5.1 文件位置

```
1-ARCHITECTURE/dreamos/evolution/
  ├── washout_classifier.py       # WashoutClassifier 主类
  ├── washout_case_library.py     # CBR 案例库（KNN 检索）
  └── washout_bayesian_updater.py # 贝叶斯置信度更新
```

### 5.2 算法选择：KNN/CBR + 贝叶斯（禁用 LLM）

**理由**：
- 用户偏好倾向深度学习，不倾向大语言模型
- KNN/CBR 适合案例驱动场景（每笔交易闭环即为一个案例）
- 贝叶斯适合小样本场景（早期数据少）
- 可解释性强（KNN 返回相似历史案例 + 贝叶斯后验概率）

### 5.3 案例库数据结构

```python
@dataclass
class WashoutCase:
    """洗盘/真弱势闭环案例。"""
    case_id: str
    coin: str
    entry_time: str                  # 入场时间
    exit_time: str                   # 出场时间（闭环）
    features_snapshot: Dict[str, float]   # 12+1 维特征
    actual_label: WashoutLabel       # 闭环后真实标签（washout/weakness）
    pnl_pct: float                  # 闭环盈亏百分比
    reward: float                    # tanh(pnl_pct / 0.02) 归一化 [-1, 1]
    timestamp: str
```

### 5.4 WashoutClassifier 主类

```python
class WashoutClassifier:
    """洗盘/真弱势 KNN/CBR + 贝叶斯分类器（自进化侧）。

    禁用 LLM，倾向深度学习；复用 EvolutionEngine 沙箱验证。
    """

    def __init__(
        self,
        case_library: WashoutCaseLibrary,
        k_neighbors: int = 5,
        min_cases: int = 30,            # 案例库 < 30 时降级为规则
        bayesian_prior_alpha: float = 1.0,
    ):
        self.case_library = case_library
        self.k_neighbors = k_neighbors
        self.min_cases = min_cases
        self.bayesian_prior_alpha = bayesian_prior_alpha

    def predict(self, features: Dict[str, float]) -> WashoutVerdict:
        """KNN 检索 + 贝叶斯后验。"""
        if len(self.case_library) < self.min_cases:
            # 数据不足 → 降级为规则
            return self._fallback_rule(features)

        # Step 1: KNN 检索 top-k 相似历史案例
        neighbors = self.case_library.knn_search(features, k=self.k_neighbors)

        # Step 2: 贝叶斯后验 P(washout|features)
        prior_washout = self._compute_prior()
        likelihood = self._compute_likelihood(features, neighbors)
        posterior_washout = self._bayesian_update(prior_washout, likelihood)

        # Step 3: 输出 verdict
        if posterior_washout > 0.65:
            label = WashoutLabel.WASHOUT
        elif posterior_washout < 0.35:
            label = WashoutLabel.WEAKNESS
        else:
            label = WashoutLabel.UNKNOWN

        return WashoutVerdict(
            label=label,
            confidence=posterior_washout if label == WashoutLabel.WASHOUT else 1 - posterior_washout,
            trigger_activated=True,
            feature_snapshot=features,
            reason=f"knn_bayesian_k={self.k_neighbors}_n={len(neighbors)}",
            timestamp=datetime.utcnow().isoformat(),
        )

    def record_case(self, case: WashoutCase) -> None:
        """闭环后记录案例（用于自进化训练）。"""
        self.case_library.add(case)

    def evolve(self) -> Dict:
        """复用 EvolutionEngine._sandbox_validate 进行自进化验证。

        Returns:
            {"accepted": bool, "score": float, "baseline_score": float}
        """
        ...
```

### 5.5 自进化闭环

```
WashoutDetector.run() → WashoutVerdict → 触发交易动作
   ↓
持仓中 → 实时特征更新 → 重新调用 WashoutClassifier.predict()
   ↓
平仓 → 真实标签确定（washout/weakness）→ WashoutCase 入库
   ↓
案例库 >= 30 → KNN/Bayesian 训练 → predict() 置信度提升
   ↓
_evolution_engine._sandbox_validate() 沙箱验证 → 通过则升级权重
   ↓
verify(memory_id, success=True) → 贝叶斯置信度更新（"越用越聪明"）
```

### 5.6 reward 信号

**硬约束**: 自进化矛盾反馈用真实 PnL 作为 reward 信号，`reward = tanh(pnl_pct / 0.02)` 归一化到 [-1, 1]。

- 洗盘判定正确（继续持有 + 最终盈利）→ reward > 0 → 加强该特征模式
- 洗盘判定错误（继续持有 + 最终亏损）→ reward < 0 → 削弱该特征模式
- 真弱势判定正确（加速离场 + 避免更大亏损）→ reward > 0
- 真弱势判定错误（加速离场 + 错过反弹）→ reward < 0

---

## 6. 模块三：数据源扩展（18-数据获取中心）

### 6.1 新增 Collector

```
18-数据获取中心/data_center/collectors/chain/
  ├── cvd_collector.py             # Cumulative Volume Delta
  ├── ofi_collector.py             # Order Flow Imbalance
  └── long_short_ratio_collector.py # 多空比（辅助判定）
```

### 6.2 数据源

| Collector | 数据源 | 频率 | 字段 | 备注 |
|---|---|---|---|---|
| CVD | CoinGlass / Coinglass API | 5min | cvd_value, buy_volume, sell_volume | 需 API key |
| OFI | Binance/OKX 公开订单簿 | 1min snapshot | bid_volume, ask_volume, ofi_value | 免费档够用 |
| L-S Ratio | Binance Futures API | 5min | long_ratio, short_ratio, long_short_ratio | 免费 |

### 6.3 奖章架构接入

```
Bronze 层（原始采集）
  ├─ cvd_raw 表: timestamp, symbol, cvd_value, buy_volume, sell_volume, source
  ├─ ofi_raw 表: timestamp, symbol, bid_volume, ask_volume, ofi_value
  └─ long_short_ratio_raw 表: timestamp, symbol, long_ratio, short_ratio

Silver 层（清洗）
  ├─ 去重: (timestamp, symbol) 唯一
  ├─ 3σ 异常值过滤
  ├─ IQR 异常值过滤
  ├─ 动态 ATR 异常值过滤
  ├─ 时间戳对齐（UTC 5min 对齐）
  └─ 缺失值插补（前值填充，最多 3 个连续缺失）

Gold 层（可用数据）
  ├─ cvd_clean 表: 通过 Schema 验证
  ├─ ofi_clean 表: 通过 Schema 验证
  └─ long_short_ratio_clean 表: 通过 Schema 验证
```

### 6.4 quality.py 硬门禁

**硬约束**: `quality.py` 从监控报警升级为硬门禁拦截，异常数据仅保留在 Bronze 层用于审计。

```python
# quality.py 新增检查
def validate_washout_data(record: Dict) -> bool:
    """洗盘判定数据门禁。"""
    required_fields = ["timestamp", "symbol", "cvd_value", "ofi_value"]
    for f in required_fields:
        if f not in record or record[f] is None:
            return False
    # 数值范围检查
    if not (-1e9 <= record["cvd_value"] <= 1e9):
        return False
    return True
```

### 6.5 FeatureHub 注册

新增 3 个特征在 `21-特征工程中心/feature_hub/hub/feature_registry.py`：

```python
FEATURE_REGISTRY.extend([
    FeatureDef(name="cvd_value", layer="silver", freq="5min", source="cvd_collector"),
    FeatureDef(name="ofi_value", layer="silver", freq="1min", source="ofi_collector"),
    FeatureDef(name="long_short_ratio", layer="silver", freq="5min", source="long_short_ratio_collector"),
])
```

---

## 7. 模块四：与现有离场系统整合（三层防御）

### 7.1 问题分析

当前 exit_strategies.py 6 个策略 + 核心层 SLTP 的触发顺序：

```
Static SLTP 检查（core 层，ExitManager 之前）
  ↓
ExitManager priority 链:
  priority=10: P3EarlyExitStrategy
  priority=20: SignalReverseStrategy
  priority=30: EvForceCloseStrategy
  priority=40: TimeoutProfitSwitchStrategy
  priority=50: RankedTpStrategy
  priority=60: EvAdjustStrategy
  ↓
卦象主离场（core 层）→ Classic 兜底（core 层）
```

**过早止损**（洗盘被当真弱势误退出）的来源：
1. Static SLTP 在洗盘回调中被扫损（core 层，ExitManager 之前触发，WashoutHoldStrategy 来不及拦截）
2. P3EarlyExit (priority=10) 在洗盘时误触发 TDA+Ising 预警（优先级比 WashoutHoldStrategy 15 高，先评估）
3. SignalReverse (priority=20) / EvForceClose (priority=30) 在洗盘时误触发（可被 priority=15 的 hold 阻断）

**过晚止损**（真弱势被当洗盘误持有）的来源：
1. 无策略触发离场，持仓硬扛直到深度亏损
2. RankedTp 延迟止盈，错过离场时机

### 7.2 三层防御架构

```
持仓中价格回调
   ↓
┌──────────────────────────────────────────────────────────┐
│ Layer 1: WashoutSLGuard (新增，整合 Static SLTP 层)         │
│  在 Static SLTP 检查前运行                                 │
│  washout+conf≥0.80 → 动态放宽 SL +2.5%（防扫损，最多 48h） │
│  weakness+conf≥0.70 → 收紧 SL -1.5%（加速离场）            │
│  超时 48h 或 verdict 变化 → 恢复原 SL                      │
│  解决: 过早止损 (SLTP 层) + 过晚止损 (SLTP 层)              │
└──────────────────────────────────────────────────────────┘
   ↓
┌──────────────────────────────────────────────────────────┐
│ Layer 2: P3EarlyExit 洗盘感知改造 (修改现有策略 priority=10) │
│  P3 触发前先查 WashoutVerdict                              │
│  washout+conf≥0.80 → 抑制 P3 退出 (return hold + reason)   │
│  weakness 或 unknown → P3 正常逻辑                         │
│  解决: 过早止损 (P3 层)                                    │
└──────────────────────────────────────────────────────────┘
   ↓
┌──────────────────────────────────────────────────────────┐
│ Layer 3: WashoutHoldStrategy (新增，priority=15)            │
│  washout → hold (阻断 priority=20+ 的 SignalReverse/EvForceClose/Timeout) │
│  weakness+conf≥0.70 → force_close (加速离场，早于 20+)     │
│  unknown → pass                                            │
│  解决: 过早止损 (SignalReverse/EvForceClose 层) + 过晚止损 (加速离场) │
└──────────────────────────────────────────────────────────┘
   ↓
核心层（卦象主离场 + Classic 兜底，不动）
```

### 7.3 Layer 1: WashoutSLGuard（新增组件）

**文件位置**: `11-易经推理系统/scripts/memory_l4/bcrm2/washout_sl_guard.py`

```python
class WashoutSLGuard:
    """洗盘/真弱势 SLTP 动态调节器（整合 Static SLTP 层）。

    在 Static SLTP 检查前运行，根据 WashoutVerdict 动态调节 SL：
    - washout 高置信度 → 放宽 SL（防扫损）
    - weakness 高置信度 → 收紧 SL（加速离场）
    - 超时或 verdict 变化 → 恢复原 SL

    硬约束:
    - HC-SL1: 放宽 SL 不得低于原 SL + 原始 SL 的 25%（防爆仓安全边际）
    - HC-SL2: 收紧 SL 不得高于当前 mark price（防爆仓）
    - HC-SL3: 放宽后的 SL 仍必须严格位于爆仓价 + 0.3% 安全缓冲的安全侧
    - HC-SL4: 放宽窗口最长 48h，超时自动恢复原 SL
    - HC-SL5: SL 放宽/收紧期间持续记录 washout_sl_adjustment_log
    """

    def __init__(
        self,
        detector: WashoutDetector,
        washout_sl_widen_pct: float = 0.025,        # 放宽 2.5%
        weakness_sl_tighten_pct: float = 0.015,    # 收紧 1.5%
        widen_confidence_threshold: float = 0.80,   # 放宽置信度阈值
        tighten_confidence_threshold: float = 0.70, # 收紧置信度阈值
        max_widen_hours: int = 48,                  # 最长放宽窗口
        max_widen_pct_of_original: float = 0.25,   # 放宽不得超原 SL 的 25%
    ):
        self.detector = detector
        self.washout_sl_widen_pct = washout_sl_widen_pct
        self.weakness_sl_tighten_pct = weakness_sl_tighten_pct
        self.widen_confidence_threshold = widen_confidence_threshold
        self.tighten_confidence_threshold = tighten_confidence_threshold
        self.max_widen_hours = max_widen_hours
        self.max_widen_pct_of_original = max_widen_pct_of_original
        self._original_sl: Dict[str, float] = {}        # coin -> original SL price
        self._adjustment_start: Dict[str, datetime] = {} # coin -> adjustment start time

    def adjust_sltp(self, coin: str, pos_info: dict, df: pd.DataFrame, macro_data: dict) -> dict:
        """返回 SL/TP 调整指令。

        Returns:
            {"action": "widen_sl"/"tighten_sl"/"restore_sl"/"no_change",
             "original_sl": float, "new_sl": float, "reason": str}
        """
        if not self.detector.enable:
            return {"action": "no_change"}

        try:
            verdict = self.detector.run(coin, df, macro_data)
            current_sl = float(pos_info.get("sl_price", 0.0))
            mark_price = float(pos_info.get("mark_price", 0.0))
            liq_price = float(pos_info.get("liq_price", 0.0))

            # 记录原始 SL（首次）
            if coin not in self._original_sl and current_sl > 0:
                self._original_sl[coin] = current_sl

            original_sl = self._original_sl.get(coin, current_sl)

            # 检查放宽窗口超时
            if coin in self._adjustment_start:
                elapsed = (datetime.utcnow() - self._adjustment_start[coin]).total_seconds() / 3600
                if elapsed > self.max_widen_hours:
                    self._restore_sl(coin)
                    return {"action": "restore_sl", "original_sl": original_sl,
                            "new_sl": original_sl, "reason": f"widen_timeout:{elapsed:.1f}h"}

            # 根据 verdict 调节
            if verdict.label == WashoutLabel.WASHOUT and verdict.confidence >= self.widen_confidence_threshold:
                # 放宽 SL（防扫损）
                new_sl = self._compute_widened_sl(original_sl, current_sl, mark_price, liq_price)
                if new_sl != current_sl:
                    if coin not in self._adjustment_start:
                        self._adjustment_start[coin] = datetime.utcnow()
                    return {"action": "widen_sl", "original_sl": original_sl,
                            "new_sl": new_sl, "reason": f"washout_widen:conf={verdict.confidence:.2f}"}

            elif verdict.label == WashoutLabel.WEAKNESS and verdict.confidence >= self.tighten_confidence_threshold:
                # 收紧 SL（加速离场）
                new_sl = self._compute_tightened_sl(current_sl, mark_price)
                if new_sl != current_sl and new_sl < mark_price:
                    return {"action": "tighten_sl", "original_sl": original_sl,
                            "new_sl": new_sl, "reason": f"weakness_tighten:conf={verdict.confidence:.2f}"}

            # verdict 变化（washout→unknown/weakness）→ 恢复原 SL
            if coin in self._adjustment_start and verdict.label != WashoutLabel.WASHOUT:
                self._restore_sl(coin)
                return {"action": "restore_sl", "original_sl": original_sl,
                        "new_sl": original_sl, "reason": f"verdict_changed:{verdict.label.value}"}

            return {"action": "no_change"}

        except Exception as e:
            logger.error(f"WashoutSLGuard FAIL-OPEN: {e}\n{traceback.format_exc()}")
            return {"action": "no_change"}

    def _compute_widened_sl(self, original_sl: float, current_sl: float,
                           mark_price: float, liq_price: float) -> float:
        """计算放宽后的 SL，遵守爆仓安全边际约束。"""
        # 放宽方向：做多 SL 下移，做空 SL 上移
        is_long = mark_price > current_sl  # 简化判断
        widen_abs = original_sl * self.washout_sl_widen_pct
        # 硬约束 HC-SL1: 放宽不得超原 SL 的 25%
        max_widen_abs = original_sl * self.max_widen_pct_of_original
        widen_abs = min(widen_abs, max_widen_abs)

        if is_long:
            new_sl = current_sl - widen_abs  # 做多 SL 下移
            # 硬约束 HC-SL3: 必须位于爆仓价 + 0.3% 安全缓冲的安全侧
            safety_buffer = abs(liq_price) * 0.003
            min_sl = liq_price - safety_buffer if liq_price < mark_price else liq_price + safety_buffer
            new_sl = max(new_sl, min_sl)  # 不得低于安全侧
        else:
            new_sl = current_sl + widen_abs  # 做空 SL 上移
            safety_buffer = abs(liq_price) * 0.003
            max_sl = liq_price + safety_buffer if liq_price > mark_price else liq_price - safety_buffer
            new_sl = min(new_sl, max_sl)  # 不得高于安全侧

        return new_sl

    def _compute_tightened_sl(self, current_sl: float, mark_price: float) -> float:
        """计算收紧后的 SL。"""
        tighten_abs = current_sl * self.weakness_sl_tighten_pct
        is_long = mark_price > current_sl
        if is_long:
            new_sl = current_sl + tighten_abs  # 做多 SL 上移（靠近 mark）
            # 硬约束 HC-SL2: 不得高于当前 mark price
            new_sl = min(new_sl, mark_price * 0.995)
        else:
            new_sl = current_sl - tighten_abs  # 做空 SL 下移
            new_sl = max(new_sl, mark_price * 1.005)
        return new_sl

    def _restore_sl(self, coin: str) -> None:
        """恢复原 SL。"""
        self._adjustment_start.pop(coin, None)

    def get_adjustment_log(self, coin: str) -> dict:
        """获取 SL 调整日志（用于审计）。"""
        return {
            "coin": coin,
            "original_sl": self._original_sl.get(coin),
            "adjustment_start": self._adjustment_start.get(coin),
            "elapsed_hours": (
                (datetime.utcnow() - self._adjustment_start[coin]).total_seconds() / 3600
                if coin in self._adjustment_start else None
            ),
        }
```

**接入点**: 在 `polling_trader._check_static_sltp()`（或等效 SLTP 检查函数）之前调用：

```python
# polling_trader.py SLTP 检查段
def _check_sltp(self, coin, pos_info, ...):
    # 【新增】WashoutSLGuard 先于静态 SLTP 运行
    if self._washout_sl_guard:
        adjustment = self._washout_sl_guard.adjust_sltp(coin, pos_info, df, macro_data)
        if adjustment["action"] in ("widen_sl", "tighten_sl"):
            self._adjust_algo_sl(coin, adjustment["new_sl"], reason=adjustment["reason"])
        elif adjustment["action"] == "restore_sl":
            self._adjust_algo_sl(coin, adjustment["new_sl"], reason=adjustment["reason"])

    # 原有静态 SLTP 检查逻辑（不动）
    ...
```

### 7.4 Layer 2: P3EarlyExit 洗盘感知改造（修改现有策略）

**修改文件**: `11-易经推理系统/scripts/memory_l4/bcrm2/exit_strategies.py` 的 `P3EarlyExitStrategy`

```python
class P3EarlyExitStrategy(ExitStrategy):
    """P3 提前退出策略（新增洗盘感知）。

    触发条件:
      - inference["early_exit_signal"] == True
      - 保护期内需浮亏 >= protected_p3_min_loss_pct
      - 连续 N 次触发才确认（exit_confirm_required）
      - 【新增】washout_detector 判定为 washout 且 conf≥0.80 时抑制退出
    """

    name = "p3_early_exit"
    priority = 10

    def __init__(
        self,
        exit_confirm_required: int = 2,
        protected_p3_min_loss_pct: float = -0.08,
        washout_detector: Optional["WashoutDetector"] = None,  # 【新增】
        washout_suppress_confidence: float = 0.80,             # 【新增】抑制阈值
    ):
        self.exit_confirm_required = exit_confirm_required
        self.protected_p3_min_loss_pct = protected_p3_min_loss_pct
        self._confirm_counts: Dict[str, int] = {}
        # 【新增】洗盘感知
        self.washout_detector = washout_detector
        self.washout_suppress_confidence = washout_suppress_confidence

    def evaluate(self, ctx: ExitContext) -> ExitDecision:
        early_exit = ctx.inference.get("early_exit_signal", False)

        if not early_exit:
            self._confirm_counts.pop(ctx.coin, None)
            return ExitDecision.pass_()

        # 【新增】洗盘高置信度时抑制 P3 退出（防过早止损）
        if self.washout_detector and self.washout_detector.enable:
            try:
                df = ctx.get_ohlcv(coin=ctx.coin, lookback=365)
                macro_data = ctx.get_macro_data(coin=ctx.coin)
                verdict = self.washout_detector.run(ctx.coin, df, macro_data)
                if verdict.label == WashoutLabel.WASHOUT and verdict.confidence >= self.washout_suppress_confidence:
                    # 抑制 P3 退出，记录但不触发
                    return ExitDecision(
                        action="hold",
                        reason=f"p3_suppressed_by_washout:conf={verdict.confidence:.2f}",
                    )
            except Exception as e:
                logger.error(f"P3EarlyExit washout check FAIL-OPEN: {e}")
                # FAIL-OPEN: 异常时走原 P3 逻辑

        # 原 P3 逻辑（保护期内 + 浮亏阈值 + N 次确认）
        upl_ratio = float(ctx.pos_info.get("upl_ratio", 0.0))
        if ctx.in_protection and upl_ratio > self.protected_p3_min_loss_pct:
            return ExitDecision.pass_()

        cnt = self._confirm_counts.get(ctx.coin, 0) + 1
        self._confirm_counts[ctx.coin] = cnt
        if cnt < self.exit_confirm_required:
            return ExitDecision(
                action="hold",
                reason=f"p3_early_exit_pending:{cnt}/{self.exit_confirm_required}",
            )

        self._confirm_counts.pop(ctx.coin, None)
        return ExitDecision(action="force_close", reason="p3_early_exit")
```

### 7.5 Layer 3: WashoutHoldStrategy（新增退出策略 priority=15）

**文件位置**: 修改 `11-易经推理系统/scripts/memory_l4/bcrm2/exit_strategies.py`，新增第 7 个策略。

### 7.6 策略定义

```python
class WashoutHoldStrategy(ExitStrategy):
    """洗盘持有 / 真弱势加速离场策略。

    priority=15，位于 P3EarlyExit (10) 与 SignalReverse (20) 之间。
    洗盘判定为 washout → hold（继续持有，等庄家震仓结束）
    真弱势判定为 weakness → force_close（加速离场）
    不确定 unknown → pass（交由后续策略）
    """

    name = "washout_hold"
    priority = 15

    def __init__(
        self,
        detector: Optional[WashoutDetector] = None,
        weakness_confidence_threshold: float = 0.70,  # 真弱势触发阈值
        washout_hold_hours: int = 48,                  # 洗盘最长持有 48h
    ):
        self.detector = detector
        self.weakness_confidence_threshold = weakness_confidence_threshold
        self.washout_hold_hours = washout_hold_hours
        self._hold_start: Dict[str, str] = {}  # coin -> ISO timestamp

    def evaluate(self, ctx: ExitContext) -> ExitDecision:
        if not self.detector or not self.detector.enable:
            return ExitDecision.pass_()

        try:
            df = ctx.get_ohlcv(coin=ctx.coin, lookback=365)
            macro_data = ctx.get_macro_data(coin=ctx.coin)
            verdict = self.detector.run(ctx.coin, df, macro_data)

            if verdict.label == WashoutLabel.WASHOUT:
                # 记录洗盘持有起点
                if ctx.coin not in self._hold_start:
                    self._hold_start[ctx.coin] = ctx.timestamp
                # 检查超时
                hold_hours = self._compute_hold_hours(ctx.coin, ctx.timestamp)
                if hold_hours > self.washout_hold_hours:
                    # 洗盘预期超时 → 转 unknown
                    self._hold_start.pop(ctx.coin, None)
                    return ExitDecision(
                        action="hold",
                        reason=f"washout_timeout:{hold_hours:.1f}h/{self.washout_hold_hours}h",
                    )
                return ExitDecision(
                    action="hold",
                    reason=f"washout_hold:conf={verdict.confidence:.2f}",
                )

            elif verdict.label == WashoutLabel.WEAKNESS:
                if verdict.confidence >= self.weakness_confidence_threshold:
                    self._hold_start.pop(ctx.coin, None)
                    return ExitDecision(
                        action="force_close",
                        reason=f"weakness_exit:conf={verdict.confidence:.2f}",
                    )
                return ExitDecision.pass_()

            else:  # UNKNOWN
                return ExitDecision.pass_()

        except Exception as e:
            logger.error(f"WashoutHoldStrategy FAIL-OPEN: {e}")
            return ExitDecision.pass_()
```

### 7.3 priority 调整

更新 exit_strategies.py 头部注释：

```python
# 策略优先级（数字小先评估）:
#   10: P3EarlyExitStrategy         — P3 提前退出（TDA+Ising 双重预警）
#   15: WashoutHoldStrategy         — 洗盘持有 / 真弱势加速离场 ← 【新增】
#   20: SignalReverseStrategy       — 信号反转
#   30: EvForceCloseStrategy        — EV 雷达强制离场
#   40: TimeoutProfitSwitchStrategy — 超时止盈换仓
#   50: RankedTpStrategy            — 排名止盈 A/B/C 三档
#   60: EvAdjustStrategy            — EV 雷达调整（移动止盈/收紧止损）
```

---

## 8. 文件结构

### 8.1 新增文件

```
11-易经推理系统/scripts/memory_l4/bcrm2/
  ├── washout_detector.py           # WashoutDetector 主类 + WashoutVerdict
  ├── washout_features.py           # 8+4+1 维特征提取器
  ├── washout_trigger_gate.py       # 触发门逻辑
  └── washout_sl_guard.py           # 【新增】Layer 1: SLTP 动态调节器

1-ARCHITECTURE/dreamos/evolution/
  ├── washout_classifier.py         # WashoutClassifier KNN/CBR+贝叶斯
  ├── washout_case_library.py       # 案例库
  └── washout_bayesian_updater.py   # 贝叶斯更新器

18-数据获取中心/data_center/collectors/chain/
  ├── cvd_collector.py               # CVD 采集
  ├── ofi_collector.py              # OFI 采集
  └── long_short_ratio_collector.py # 多空比采集

docs/superpowers/specs/
  └── 2026-09-21-washout-detector-design.md  # 本 spec
```

### 8.2 修改文件（最小改动）

| 文件 | 改动 | 层级 |
|---|---|---|
| `bcrm2/exit_strategies.py` | 新增 WashoutHoldStrategy (priority=15) + 修改 P3EarlyExit 增洗盘感知 | Layer 2 + Layer 3 |
| `bcrm2/exit_manager.py` | 注册 WashoutHoldStrategy 到策略链 + P3EarlyExit 注入 washout_detector | Layer 3 |
| `polling_trader.py` | SLTP 检查前调用 WashoutSLGuard + `_execute_trade` 增加 WashoutDetector 调用 | Layer 1 |
| `bcrm2/indicators.py` | 不动（复用现有 12 指标） | — |
| `bcrm2/macro_features.py` | 不动（复用现有 OI/funding 特征） | — |
| `bcrm2/feature_registry.py` | 注册 3 个新特征 | — |
| `18-数据获取中心/data_center/monitoring/quality.py` | 新增 washout 数据门禁 | — |
| `trading_utils.py` | `OpenPosition` 新增 `washout_verdict: Optional[WashoutVerdict]` | — |
| `dreamos/evolution/engine.py` | `_check_orchestration_optimization` 增加 WashoutClassifier 进化检查 | — |
| `dreamos/evolution/types.py` | 新增 `WashoutLesson` dataclass | — |

---

## 9. 5 阶段实施路径（W1-W5）

### 9.1 W1: 触发门 + 数据契约 + 开关架构

**目标**: 落地 WashoutVerdict 数据契约 + WashoutTriggerGate 触发门 + 开关架构骨架。

**新增文件**:
- `bcrm2/washout_detector.py` (骨架 + WashoutVerdict + unknown() + to_dict/from_dict)
- `bcrm2/washout_trigger_gate.py` (触发门)

**TDD 测试清单** (`tests/test_washout_w1.py`):
1. `test_washout_verdict_unknown_fallback` — `WashoutVerdict.unknown()` 返回 label=UNKNOWN, confidence=0.0
2. `test_washout_verdict_to_dict_from_dict_roundtrip_1000` — 1000 次随机 roundtrip 无损
3. `test_washout_verdict_frozen_immutable` — frozen=True，不可变
4. `test_trigger_gate_no_runup_returns_false` — 无上涨（涨幅 < 15%）→ 不触发
5. `test_trigger_gate_runup_but_no_drawdown_returns_false` — 上涨 15%+ 但无回撤 → 不触发
6. `test_trigger_gate_runup_and_drawdown_returns_true` — 上涨 15%+ 回撤 5%+ → 触发
7. `test_trigger_gate_below_ma200_returns_false` — 价格在 MA200 之下 → 不触发
8. `test_washout_detector_disabled_returns_unknown` — enable=False → unknown
9. `test_washout_detector_enabled_no_trigger_returns_unknown` — enable=True 但触发门未通过 → unknown
10. `test_washout_detector_fail_open_on_exception` — 异常 → unknown + 6 层堆栈日志

**验收标准**:
- WashoutVerdict 数据契约通过 1000 次 roundtrip 无损
- 触发门在"上涨后回调"场景正确激活
- FAIL-OPEN 异常兜底验证通过
- `ENABLE_WASHOUT_DETECTOR=False` 时返回 unknown，BCRM2.0 链路字节等价

### 9.2 W2: 8 维特征融合器（传统金融维度）

**目标**: 落地 8 维传统金融特征提取器（F1-F8）。

**新增文件**:
- `bcrm2/washout_features.py` (F1-F8 提取)

**TDD 测试清单** (`tests/test_washout_w2.py`):
1. `test_extract_volume_ratio_20d_normal` — 正常 vol / vol_ma20 计算正确
2. `test_extract_volume_ratio_zero_vol_returns_neutral` — vol=0 → 中性值 1.0
3. `test_extract_support_holds_count_3_holds` — 3 次守住支撑 → count=3
4. `test_extract_support_holds_count_break_returns_0` — 破支撑 → count=0
5. `test_extract_atr_compress_ratio_narrowing` — ATR_5d < ATR_20d → ratio < 1
6. `test_extract_atr_compress_ratio_widening` — ATR_5d > ATR_20d → ratio > 1
7. `test_extract_oi_change_rate_7d` — OI 7d 变化率计算正确
8. `test_extract_cycle_position_365d_low` — 365d 低位 → < 0.3
9. `test_extract_cycle_position_365d_high` — 365d 高位 → > 0.7
10. `test_extract_rebound_ratio_5d_strong` — 5d 反弹强 → > 0.5
11. `test_extract_news_negative_score_no_news` — 无新闻 → 0.0
12. `test_extract_news_negative_score_negative_news` — 负面新闻占比正确
13. `test_extract_btc_correlation_30d` — 30d 相关性计算正确
14. `test_extract_all_features_dim_switch_off` — 子开关关闭 → 该维度不提取

**验收标准**:
- 8 维特征在正常/边界/异常场景下计算正确
- 子开关独立关断某维度不影响其他维度
- 复用 IndicatorBank / MacroFeatures 现有指标，不重写

### 9.3 W3: 4 加密独有维度 + 数据源扩展

**目标**: 落地 4 维加密独有特征（F9-F12）+ Wyckoff climax（F13）+ CVD/OFI/L-S Ratio 数据采集。

**新增文件**:
- `18-数据获取中心/data_center/collectors/chain/cvd_collector.py`
- `18-数据获取中心/data_center/collectors/chain/ofi_collector.py`
- `18-数据获取中心/data_center/collectors/chain/long_short_ratio_collector.py`
- `bcrm2/washout_features.py` 扩展（F9-F13）

**TDD 测试清单** (`tests/test_washout_w3.py`):
1. `test_cvd_collector_fetch_returns_cvd_value` — 拉取 CVD 数据成功
2. `test_cvd_collector_fail_open_on_api_error` — API 异常 → 返回空 DataFrame 不阻塞
3. `test_ofi_collector_fetch_returns_ofi_value` — 拉取 OFI 数据成功
4. `test_ofi_collector_snapshot_interval` — 1min snapshot 间隔正确
5. `test_long_short_ratio_collector_fetch` — 拉取多空比成功
6. `test_quality_validate_washout_data_rejects_missing` — 缺字段 → 拦截
7. `test_quality_validate_washout_data_rejects_outlier` — 数值越界 → 拦截
8. `test_silver_layer_dedup_unique_constraint` — (timestamp, symbol) 唯一
9. `test_silver_layer_3sigma_filter` — 3σ 外异常值过滤
10. `test_silver_layer_iqr_filter` — IQR 外异常值过滤
11. `test_silver_layer_atr_filter` — 动态 ATR 外异常值过滤
12. `test_gold_layer_schema_validation` — Schema 验证通过
13. `test_extract_oi_price_quadrant_oi_up_price_down` — OI↑+Price↓ → 正确象限
14. `test_extract_funding_rate_zscore_extreme_positive` — funding 极正
15. `test_extract_cvd_price_divergence_trapped_trader` — CVD 下行价格守住 → 负相关
16. `test_extract_ofi_std_20d_low_variance_suspicious` — 低 OFI 方差可疑
17. `test_extract_wyckoff_climax_stage_1_panic` — Stage 1 panic 判定
18. `test_extract_wyckoff_climax_stage_2_sustained` — Stage 2 sustained 判定
19. `test_extract_wyckoff_climax_stage_3_exhaustion` — Stage 3 exhaustion 判定
20. `test_extract_wyckoff_climax_volume_2x_triggers` — volume ≥ 2x 20d 均量触发 climax

**验收标准**:
- CVD/OFI/L-S Ratio 采集器 FAIL-OPEN 验证通过
- 奖章架构 Bronze→Silver→Gold 三层清洗链路通过
- quality.py 硬门禁拦截异常数据
- 4 加密独有维度 + Wyckoff climax 特征计算正确

### 9.4 W4: WashoutClassifier（KNN/CBR + 贝叶斯）

**目标**: 落地 WashoutClassifier + 案例库 + 贝叶斯更新器，接入 WashoutDetector。

**新增文件**:
- `dreamos/evolution/washout_classifier.py`
- `dreamos/evolution/washout_case_library.py`
- `dreamos/evolution/washout_bayesian_updater.py`

**TDD 测试清单** (`tests/test_washout_w4.py`):
1. `test_washout_case_library_add_and_retrieve` — 案例入库 + 检索
2. `test_washout_case_library_knn_search_returns_k_neighbors` — KNN 返回 k 个最近邻
3. `test_washout_case_library_knn_search_distance_euclidean` — 欧氏距离正确
4. `test_washout_classifier_insufficient_cases_fallback_rule` — 案例 < 30 → 降级规则
5. `test_washout_classifier_predict_washout_high_confidence` — 高置信度洗盘判定
6. `test_washout_classifier_predict_weakness_high_confidence` — 高置信度真弱势判定
7. `test_washout_classifier_predict_unknown_middle_confidence` — 中等置信度 → unknown
8. `test_washout_classifier_bayesian_update_prior_posterior` — 贝叶斯先验/后验更新正确
9. `test_washout_classifier_record_case_updates_library` — 闭环后案例入库
10. `test_washout_classifier_evolve_sandbox_validate` — 复用 _sandbox_validate 通过
11. `test_washout_classifier_reward_tanh_normalization` — reward = tanh(pnl/0.02) 归一化
12. `test_washout_classifier_no_llm_dependency` — grep 确认无 LLM 调用
13. `test_washout_classifier_evolution_engine_integration` — 与 EvolutionEngine 集成
14. `test_washout_detector_with_classifier_predict` — WashoutDetector 注入 classifier 后走 KNN/Bayesian

**验收标准**:
- WashoutClassifier KNN/CBR + 贝叶斯闭环
- 禁用 LLM（grep 验证无 LLM 调用）
- 复用 EvolutionEngine._sandbox_validate 沙箱验证
- reward = tanh(pnl_pct / 0.02) 归一化到 [-1, 1]
- 案例库 >= 30 才走 KNN，否则降级规则

### 9.5 W5: 三层防御整合 + 集成测试

**目标**: 落地三层防御（WashoutSLGuard + P3EarlyExit 洗盘感知 + WashoutHoldStrategy priority=15）+ 全链路集成测试 + 文档对齐。

**新增文件**:
- `bcrm2/washout_sl_guard.py` (Layer 1: SLTP 动态调节器)

**修改文件**:
- `bcrm2/exit_strategies.py` (新增 WashoutHoldStrategy + 修改 P3EarlyExit 增洗盘感知)
- `bcrm2/exit_manager.py` (注册 WashoutHoldStrategy + P3EarlyExit 注入 washout_detector)
- `polling_trader.py` (SLTP 检查前调用 WashoutSLGuard + `_execute_trade` 调用 WashoutDetector 仅 is_trial 子池)
- `trading_utils.py` (OpenPosition 增 washout_verdict)

**TDD 测试清单** (`tests/test_washout_w5.py`):

Layer 1: WashoutSLGuard 测试
1. `test_washout_sl_guard_disabled_returns_no_change` — detector.enable=False → no_change
2. `test_washout_sl_guard_washout_widen_sl` — washout+conf≥0.80 → widen_sl
3. `test_washout_sl_guard_weakness_tighten_sl` — weakness+conf≥0.70 → tighten_sl
4. `test_washout_sl_guard_widen_respects_max_25pct` — 放宽不得超原 SL 的 25%
5. `test_washout_sl_guard_widen_respects_liq_safety` — 放宽后 SL 仍位于爆仓价 + 0.3% 安全侧
6. `test_washout_sl_guard_tighten_not_above_mark` — 收紧 SL 不得高于 mark price
7. `test_washout_sl_guard_widen_timeout_48h_restore` — 放宽超 48h → restore_sl
8. `test_washout_sl_guard_verdict_change_restore` — verdict 从 washout→weakness → restore_sl
9. `test_washout_sl_guard_fail_open_on_exception` — 异常 → no_change + 6 层堆栈
10. `test_washout_sl_guard_get_adjustment_log` — 审计日志正确

Layer 2: P3EarlyExit 洗盘感知测试
11. `test_p3_early_exit_washout_suppresses_exit` — washout+conf≥0.80 → P3 返回 hold 抑制退出
12. `test_p3_early_exit_washout_low_confidence_proceeds` — washout+conf<0.80 → P3 正常逻辑
13. `test_p3_early_exit_weakness_proceeds` — weakness → P3 正常逻辑（不抑制）
14. `test_p3_early_exit_unknown_proceeds` — unknown → P3 正常逻辑
15. `test_p3_early_exit_washout_check_fail_open` — washout 检查异常 → 走原 P3 逻辑
16. `test_p3_early_exit_no_detector_proceeds` — washout_detector=None → 原 P3 逻辑

Layer 3: WashoutHoldStrategy 测试
17. `test_washout_hold_strategy_disabled_returns_pass` — detector=None → pass
18. `test_washout_hold_strategy_washout_label_returns_hold` — washout → hold
19. `test_washout_hold_strategy_weakness_high_confidence_force_close` — weakness + conf≥0.70 → force_close
20. `test_washout_hold_strategy_weakness_low_confidence_pass` — weakness + conf<0.70 → pass
21. `test_washout_hold_strategy_unknown_returns_pass` — unknown → pass
22. `test_washout_hold_strategy_timeout_48h_returns_hold_with_reason` — 超 48h → hold + reason
23. `test_washout_hold_strategy_fail_open_on_exception` — 异常 → pass

三层协同 + 集成测试
24. `test_exit_manager_priority_15_between_10_and_20` — priority=15 在 10 和 20 之间
25. `test_exit_manager_washout_hold_short_circuits_after_force_close` — force_close 后 priority=20+ 不评估
26. `test_polling_trader_washout_trial_position_max_2` — is_trial 子池最多 2 单
27. `test_polling_trader_washout_source_tag` — source_tag='washout_trial' 正确
28. `test_open_position_washout_verdict_field` — OpenPosition.washout_verdict 字段存在
29. `test_integration_layer1_sl_guard_widens_sl_during_washout` — 端到端：washout → SLGuard 放宽 SL → 不被扫损
30. `test_integration_layer2_p3_suppressed_during_washout` — 端到端：washout → P3 抑制 → 不误退出
31. `test_integration_layer3_hold_blocks_signal_reverse` — 端到端：washout → WashoutHoldStrategy hold → SignalReverse 不评估
32. `test_integration_weakness_accelerates_exit_all_layers` — 端到端：weakness → SLGuard 收紧 + P3 不抑制 + WashoutHoldStrategy force_close
33. `test_full_regression_all_existing_strategies_unchanged` — 全回归：6 个原策略行为不变
34. `test_full_regression_275_existing_tests_still_pass` — 全回归：275 个测试仍通过
35. `test_integration_washout_detector_to_exit_strategy` — 端到端：detector → verdict → 三层防御 → 交易动作

**验收标准**:
- 三层防御完整落地：WashoutSLGuard (Layer 1) + P3EarlyExit 洗盘感知 (Layer 2) + WashoutHoldStrategy priority=15 (Layer 3)
- 过早止损全链路防护：washout → SL 放宽 + P3 抑制 + priority=20+ 阻断
- 过晚止损全链路加速：weakness → SL 收紧 + P3 不抑制 + force_close 加速
- 爆仓安全边际约束（HC-SL1 至 HC-SL5）全部通过
- is_trial 子池最多 2 单硬约束
- 275 个原有测试零回归
- 端到端：WashoutDetector → WashoutVerdict → 三层防御 → 交易动作
- `ENABLE_WASHOUT_DETECTOR=False` 时三层防御全部 no_change/pass，BCRM2.0 + 自进化链路字节等价

---

## 10. TDD 验证矩阵

| 测试名 | RED 原因 | GREEN 最小实现 | 断言 |
|---|---|---|---|
| `test_washout_verdict_unknown_fallback` | WashoutVerdict 不存在 | dataclass + unknown() | label=UNKNOWN, confidence=0.0 |
| `test_washout_verdict_roundtrip_1000` | to_dict/from_dict 不存在 | 序列化方法 | 1000 次随机 roundtrip 无损 |
| `test_trigger_gate_no_runup_returns_false` | TriggerGate 不存在 | should_activate | 涨幅<15% → False |
| `test_trigger_gate_runup_drawdown_returns_true` | 同上 | 同上 | 涨幅≥15% + 回撤≥5% → True |
| `test_washout_detector_disabled_returns_unknown` | WashoutDetector 不存在 | run() 骨架 | enable=False → unknown |
| `test_washout_detector_fail_open_on_exception` | FAIL-OPEN 未写 | try/except 兜底 | 异常 → unknown + 6 层堆栈 |
| `test_extract_volume_ratio_20d_normal` | 特征提取器不存在 | F1 计算 | vol/vol_ma20 正确 |
| `test_extract_support_holds_count_3_holds` | 同上 | F2 计算 | 3 次守住 → count=3 |
| `test_cvd_collector_fetch_returns_cvd_value` | CVD collector 不存在 | API 调用 | cvd_value 字段存在 |
| `test_quality_validate_washout_data_rejects_missing` | 门禁未写 | quality.py 扩展 | 缺字段 → False |
| `test_washout_classifier_predict_washout` | Classifier 不存在 | KNN+Bayesian | 高置信度 → WASHOUT |
| `test_washout_classifier_no_llm_dependency` | 无 LLM 检查 | grep 验证 | 无 LLM import/调用 |
| `test_washout_hold_strategy_washout_returns_hold` | Strategy 不存在 | evaluate | washout → hold |
| `test_washout_hold_strategy_weakness_force_close` | 同上 | 同上 | weakness+conf≥0.70 → force_close |
| `test_polling_trader_washout_trial_max_2` | is_trial 门禁未写 | _should_apply_washout_detector | 子池 ≥ 2 → False |
| `test_full_regression_275_existing_tests_still_pass` | 集成破坏 | — | 275 个测试零回归 |

---

## 11. 硬约束清单

| # | 硬约束 | 来源 |
|---|---|---|
| HC-1 | `ENABLE_WASHOUT_DETECTOR=False` 默认关闭，触发条件"币种经历一定上涨后出现回调"才激活 | 用户决策 + VM-1789991697324-a06c95f9 |
| HC-2 | WashoutClassifier 用 KNN/CBR + 贝叶斯，禁用 LLM | 用户决策 + VM-1789991697324-a06c95f9 |
| HC-3 | 同步新增 CVD/OFI 数据采集（在 18-数据获取中心） | 用户决策 + VM-1789991697324-a06c95f9 |
| HC-4 | 实施顺序：先 BCRM2.0 (WashoutDetector) 后自进化 (WashoutClassifier) | 用户决策 + VM-1789991697324-a06c95f9 |
| HC-5 | WashoutDetector 作为 `is_trial=True` 独立子池，最多 2 单（复用 `MAX_TRIAL_POSITIONS = 2`） | 用户决策 + VM-1789991697324-a06c95f9 + project_memory |
| HC-6 | 关断时等价性：开关关断时 BCRM2.0 与自进化链路字节等价"洗盘判定不存在" | project_memory 模板 |
| HC-7 | 交易热路径 FAIL-OPEN 铁律：异常 → 中性兜底 + 6 层堆栈日志，5 分钟 ≥3 次触发 Lark 告警 | project_memory |
| HC-8 | 数据清洗奖章架构：Bronze→Silver(3σ→IQR→动态ATR)→Gold(Schema 验证) | project_memory |
| HC-9 | quality.py 硬门禁拦截，异常数据仅保留 Bronze 层用于审计 | project_memory |
| HC-10 | reward = tanh(pnl_pct / 0.02) 归一化到 [-1, 1] | project_memory |
| HC-11 | EvolutionEngine._sandbox_validate 沙箱验证复用：新方案得分 > 现有 × 1.1 才通过 | project_memory |
| HC-12 | evolution 子池 probe 仓阈值 PROBE_THRESHOLD=0.55 不变 | project_memory |
| HC-13 | 开仓静态止损 SL ≥ 8.0% / 止盈 TP ≥ 6.0% 不变 | project_memory |
| HC-14 | SL/TP 时间衰减机制不变（0-12h 6%, 24h 4.5%, 48h 2.25%, 72h+ 1.5%） | project_memory |
| HC-15 | WashoutSLGuard 放宽 SL 不得超原 SL 的 25%（防爆仓安全边际） | 本 spec §7.3 |
| HC-16 | WashoutSLGuard 放宽后 SL 必须位于爆仓价 + 0.3% 安全缓冲的安全侧（爆仓安全优先于放宽） | 本 spec §7.3 + project_memory |
| HC-17 | WashoutSLGuard 收紧 SL 不得高于当前 mark price（防爆仓） | 本 spec §7.3 |
| HC-18 | WashoutSLGuard 放宽窗口最长 48h，超时自动恢复原 SL | 本 spec §7.3 |
| HC-19 | WashoutSLGuard verdict 变化（washout→非 washout）时自动恢复原 SL | 本 spec §7.3 |
| HC-20 | P3EarlyExit 洗盘抑制仅在 washout+conf≥0.80 时生效，weakness/unknown 不抑制 | 本 spec §7.4 |
| HC-21 | P3EarlyExit 洗盘检查异常时 FAIL-OPEN，走原 P3 逻辑不阻塞 | 本 spec §7.4 |
| HC-22 | 三层防御全部在 ENABLE_WASHOUT_DETECTOR=False 时降级为 no_change/pass，链路字节等价 | 本 spec §7.2 |

---

## 12. 与现有文档的关系

| 现有文档 | 关系 |
|---|---|
| `2026-08-20-exit-manager-design.md` | 新增 WashoutHoldStrategy (priority=15) 接入 ExitManager 策略链 |
| `2026-08-18-bcrm2-mode-evolution-design.md` | WashoutDetector 作为 BCRM2.0 子模块，is_trial 子池 |
| `2026-08-24-data-cleaning-and-feature-hub-spec.md` | CVD/OFI 走奖章架构 Bronze→Silver→Gold |
| `2026-08-19-market-morphology-evolution-design.md` | WashoutClassifier 作为自进化子模块，复用 EvolutionEngine |
| `2026-08-22-five-domain-feature-computer-design.md` | 战略层五域不接管洗盘判定（洗盘在 BCRM2.0 侧） |
| `2026-09-10-bdsm-short-trial-design.md` | BDSM is_trial 子池与 WashoutDetector is_trial 子池共享 MAX_TRIAL_POSITIONS=2 上限 |
| `TECHNICAL_DESIGN.md` 9.6 YijingExitSystem | 核心层不动，WashoutHoldStrategy pass 后仍走卦象离场 |
| `TECHNICAL_DESIGN.md` 9.7 ClassicExitSystem | 核心层兜底，不动 |

---

## 13. 风险与约束

1. **核心层不动**: 卦象主离场 + Classic 兜底 + 保护期逻辑 + 静态 SLTP 保持原样，WashoutHoldStrategy 只在 priority=15 编排扩展层
2. **回滚铁律**: `ENABLE_WASHOUT_DETECTOR=False` 时，WashoutDetector.run() 返回 unknown，WashoutHoldStrategy 直接 pass，全链路等价于引入前
3. **is_trial 子池共享**: WashoutDetector 与 BDSM 测试仓共享 MAX_TRIAL_POSITIONS=2 上限，开仓前需统计两类合计
4. **数据源依赖**: CVD/OFI 采集在 W3 才落地，W1-W2 阶段 F11/F12 维度降级跳过
5. **案例库冷启动**: 案例库 < 30 条时 WashoutClassifier 降级为规则化判定（W1-W3 已有规则）
6. **API 限流**: CoinGlass/Coinglass API 有限流，CVD/OFI 采集需带 cache + retry
7. **LLM 禁用**: WashoutClassifier 全程禁用 LLM，grep 验证无 LLM import/调用
8. **进度渐进**: 严格 W1→W2→W3→W4→W5 顺序，每阶段 TDD RED→GREEN→零回归才进入下一阶段

---

## 14. 下一步

Spec 已写完并归档到 `docs/superpowers/specs/2026-09-21-washout-detector-design.md`。请审阅这份实现设计 Spec，确认没有修改/补充后：

1. 进入 writing-plans 生成 W1 详细实现计划
2. 严格按 TDD 循环推进（RED spec 测试 → 实现 → GREEN 验证 → 零回归）
3. 每阶段完成后调用 `record` + `verify` 更新认知记忆（"越用越聪明"闭环）

W1 完成后依次推进 W2-W5，每阶段验收标准全部通过才进入下一阶段。
