# Market Morphology Evolution Engine — 详细实施规划

> 关联 Spec: [2026-08-19-market-morphology-evolution-design.md](./2026-08-19-market-morphology-evolution-design.md)
> 制定日期: 2026-08-19
> 预计总工期: 14 天（4 Phase）
> 执行入口目录: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2`

---

## 全局约定

- **代码基准目录（Python 引擎）**：`/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2`
- **后端 API（Flask）**：`/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统/ml_trade_service.py`
- **前端**：`/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统/frontend/src`
- **Spec 引用**：以 `Spec §x.y` 标识对应设计章节
- **数据基准（冷启动/验证）**：BTC 1D 全量 `/11-易经推理系统/scripts/data/klines/BTC_1D_full.csv`（2020-01-01 ~ 2026-08-18，≈2423 根）
- **8 态顺序（全局一致）**：TREND_UP_STRONG, TREND_UP_MILD, RANGE_BOUND, CONSOLIDATION, REVERSAL, VOLATILE_DROP, FOMO_RALLY, DISTRIBUTION（定义在 `labels/regime_labeler.py:REGIME_ORDER`）
- **验收每阶段必须附带的产物**：(a) 脚本命令行可运行；(b) 产出 sample output（JSON / 图表截图）；(c) 单元 / 集成测试（TDD 风格，pytest）

---

## Phase 0：最小可运行版骨架（3 天，目标：跑通六层流水线 + 出真实 BTC trajectory.json）

### 依赖清单（验证环境）

在 Phase 0 启动前先跑一次依赖检查，确认均已满足：

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2
python -c "import pandas, numpy, scipy, hmmlearn, lightgbm, json" 2>&1 | tail -5
```

依赖均在项目中已安装（前次 regime predictor 训练已验证），**无需新增三方库**。

### P0.1 Layer 0-1：指标银行 IndicatorBank 类（新建 `indicators.py`）

**文件**：`.../bcrm2/indicators.py`（**新建**，~300 行）

**目标**：封装 12 个原子指标，输入 BTC 1D OHLCV DataFrame → 输出 Dict[str, pd.Series]，长度与输入对齐（index 同）。

**指标清单（对照 Spec §2.2-2.3）**：

| # | 指标名 | 计算方法 | 复用处 |
|---|---|---|---|
| 1 | `ma200_above_3d` | MA200.rolling(3,min=3).max() == 1 → 1；反之 MA200.rolling(3,min=3).min()==0 → -1；其余 0（三日确认原则） | 调用 `ma200_cycle_features.compute_ma200_features(close)["ma200_above"]` 再做 rolling |
| 2 | `ma50_above` | close > MA50 → +1 / -1 | `close.rolling(50,min=25).mean()` |
| 3 | `ma20_vs_ma50_order` | MA20 > MA50 → +1 / -1 | `close.rolling(20/50)` |
| 4 | `cycle_position_365d` | `cycle_position_in_range`：close 在 [365d_low, 365d_high] 中位置，映射：≥0.75 → +1；≤0.25 → -1；其他 0（不直接用作 unit，供 L2 使用原始值时也返回） | 调用 `ma200_cycle_features.compute_btc_cycle_features(close)["cycle_position_in_range"]` |
| 5 | `ma_alignment_score` | MA20/50/100/200 4 对对齐评分 [-1, 1] | 直接调用 `multi_timeframe_features.compute_ma_alignment_score(close)` |
| 6 | `ma200_slope_signed` | MA200 斜率 20 日：≥0.01（年化约 +26%，强升） → +1；≤ -0.01 → -1；其余 0 | 调用 `ma200_cycle_features.compute_ma200_features(close)["ma200_slope_20d"]` |
| 7 | `dow_hhhl_score` | Swing 检测（lookback=5）→ 近 3 个 SH/SL：HH+HL 连续=+2 / LL+LH=-2 / 混合=0 | 新实现：Swing 点 + 近 3 点评分 |
| 8 | `log_ret_90d` | np.log(close/close.shift(90))；≥0.15 → +1；≤-0.15 → -1 | 直接计算；也保留原始值 |
| 9 | `log_ret_30d` | np.log(close/close.shift(30))；≥0.08 → +0.5；≤-0.08 → -0.5 | 直接计算 |
| 10 | `ma_slope_wavg` | MA20 斜率×2 + MA50 斜率×1 + MA200 斜率×0.5，权重和=3.5；超过阈值 ±1 | 新实现：三个 slope 加权并 tanh 限幅到 [-1,1] 再映射 ± |
| 11 | `volume_trend_conf` | 近 20 日中，`(涨日 vol>1.5均量 && 跌日 vol<0.8均量)` 次数评分；+0.5 / 0 / -0.5 | `volume_ma20_ratio` 从 multi_timeframe_features 取得后做 20 日方向统计 |
| 12 | `vol_60d_pct` | vol_60d_percentile_252d，直接取原值（只用于点阵图支持度计算，L2 Score 不直接用） | `multi_timeframe_features.vol_60d_percentile` |

**接口签名**：
```python
class IndicatorBank:
    def __init__(self):
        pass

    def compute_all(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """返回 12 个指标，index=df.index，长度=len(df)，NaN=0 填充"""
        ...
        return {
            "ma200_above_3d": s1,
            ...
            "vol_60d_pct": s12,
            # 保留原始值（非 ± 值）——供点阵图 & 诊断
            "__raw_ma200_distance_pct": ma200_distance,
            "__raw_log_ret_90d": raw90,
            ...,
        }
```

**测试**：
```bash
pytest -q ../tests/test_evolution_phase0.py::test_indicator_bank_shape -v
```
断言：12 个主指标全部返回 Series，长度 2423，无 NaN。

### P0.2 Layer 2：ScoreComposer（Level/Trend 合成 + 钳制）

**文件**：`.../bcrm2/score_composer.py`（**新建**，~250 行）

**权重初始值（Spec §2.2-2.3）**：
```python
LEVEL_WEIGHTS = {
    "ma200_above_3d":      2.0,   # L1 单位贡献 ±1.0
    "ma50_above":          1.0,   # L2 单位 ±0.5
    "ma20_vs_ma50_order":  1.0,   # L3 单位 ±0.5
    "cycle_position_365d": 1.2,   # L4 单位 ±0.5
    "ma_alignment_score":  1.5,   # L5 单位 ±0.75
    "ma200_slope_signed":  1.0,   # L6 单位 ±0.5
}

TREND_WEIGHTS = {
    "dow_hhhl_score":      2.0,   # T1 ±2.0
    "log_ret_90d":         1.5,   # T2 ±1.0
    "log_ret_30d":         1.0,   # T3 ±0.5
    "ma_slope_wavg":       1.2,   # T4 ±0.75
    "volume_trend_conf":   1.0,   # T5 ±0.5
}
```

**核心算法（Spec §2.4 规则 1 — 钳制）**：
```python
def compose_scores(
    indicators: Dict[str, pd.Series],
    close: pd.Series,
    volume: pd.Series,
    max_daily_delta: float = 0.5,
    extreme_delta: float = 1.0,
    level_weights=None,
    trend_weights=None,
) -> Tuple[pd.Series, pd.Series]:
    """返回 (level_raw_series, trend_raw_series)，长度与 indicators 一致。

    公式（对每日 i 独立计算无约束 raw，再 clamp_delta 得到序列连续化）：
      step1: score_unbound_i = Σ( weight_i * contribution_i ) / Σ( |weight_i| )
      step2: raw_i = clamp( score_unbound_i * 4, -4, +4 )   # 线性扩展到 9 格
      step3: level_i = clamp_delta(level_{i-1}, raw_i, pct_change_i, vol_ratio_i)
    """
```

**测试**：
```bash
pytest -q ../tests/test_evolution_phase0.py::test_score_composer_continuity
```
断言：99% 样本 |ΔL|+|ΔT| ≤ 1.0（钳制生效）。

### P0.3 Layer 3：Temporal Smoother（HMM 3 状态 Viterbi 平滑）

**文件**：`.../bcrm2/temporal_smoother.py`（**新建**，~200 行）

**复用**：`models/hmm_regime.py:HMMRegime`（GaussianHMM，hmmlearn）

**流程**：
1. Level / Trend 的 5 日滚动均值（`level_ma5 = level_raw.rolling(5,min=3).mean()`，trend 同理）
2. 构造观测矩阵 `obs = np.column_stack([level_ma5.fillna(0), trend_ma5.fillna(0)])`（2D 特征）
3. 训练 3 状态 GaussianHMM（Bull=+ / Neutral=0 / Bear=-）
4. 用 Viterbi 解码得到 `hmm_state ∈ {0,1,2}`
5. EMA 兜底平滑：`level_smooth = alpha*level_raw + (1-alpha)*level_prev`，alpha=0.25
6. 如果 HMM 训练失败 → 只用 EMA（降级方案）

**输出**：
```python
@dataclass
class SmootherOutput:
    level_smooth: pd.Series
    trend_smooth: pd.Series
    hmm_state: pd.Series          # 0 Bear / 1 Neutral / 2 Bull
    ema_level: pd.Series          # 兜底 EMA
    bocpd_cp_prob: pd.Series      # Phase 1 接入，此处全 0
```

### P0.4 Layer 4：RegimeMapper（8 态软分配）

**文件**：`.../bcrm2/regime_mapper.py`（**新建**，~250 行）

**冷启动标定** 8 态中心坐标 `REGIME_CENTERS`：
1. 对 BTC_1D_full.csv 跑 `regime_labeler.generate_8state_label(df)` 得到每根 K 线真实标签 y
2. 用 ScoreComposer（前两步）计算 (level_raw, trend_raw)
3. 对 8 种标签，**过滤该标签样本中 consensus≥0.6 的日（后续迭代会用，但 Phase 0 中直接用全部样本）**，计算均值作为冷启动中心：
```
REGIME_CENTERS = {  # (L_center, T_center)
  "TREND_UP_STRONG":   (+2.5, +3.5),
  "TREND_UP_MILD":     (+1.0, +2.0),
  "RANGE_BOUND":       ( 0.0,  0.0),
  "CONSOLIDATION":     (-1.0, -0.5),
  "REVERSAL":          (-2.5, +1.5),
  "VOLATILE_DROP":     (+1.5, -3.0),
  "FOMO_RALLY":        (+3.5, +2.5),
  "DISTRIBUTION":      (+3.0, -1.5),
}
```
——如历史样本均值与上不同，**Phase 0 中直接以样本均值写入常量**（不要硬抄，提供 `calibrate_centers_from_labels(df)` 函数）。

**高斯软分配 + LGBM 0.7:0.3 集成（Spec §2.5 + §3.3 L4-4）**：
```python
class RegimeMapper:
    def __init__(self, centers: Dict[str, Tuple[float,float]] = REGIME_CENTERS,
                 lgbm_predictor_path: Optional[Path] = ARTIFACT_DIR / "best.lgb"):
        ...

    def map_frame(self,
                  level_smooth: float, trend_smooth: float,
                  feature_row: Optional[np.ndarray] = None,  # 16 维 LGBM 特征
                  ) -> Dict[str, Any]:
        """单 frame 计算：
          - 软分配 8 概率
          - 与 LGBM predict_proba 加权（软分配 ×0.7 + LGBM ×0.3）
          - Top-3
          - 共识度 = 1 - H(p) / ln(8)
        """
        ...
```

### P0.5 Layer 5：JSON Storage Backend + 离线 run_pipeline.py

**文件**：
- 新建 `.../bcrm2/storage.py`（~120 行，JSON 文件存储，含 `regime_trajectory_90d` 快照）
- 新建 `.../bcrm2/run_evolution_pipeline.py`（~100 行，CLI 入口）

**执行**：
```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2
python run_evolution_pipeline.py \
    --csv ../data/klines/BTC_1D_full.csv \
    --out ../../artifacts/evolution_btc/sample_trajectory.json \
    --window 90
```

**sample output 结构**：
```json
{
  "meta": {"generated_at_ms": 0, "symbol": "BTCUSDT", "window": 90},
  "snapshot_latest": { ... RegimeStateFrame ... },
  "trajectory": [
    {"t":"2026-05-20","level_raw":1.2,"trend_raw":0.8,"level_smooth":1.1,"trend_smooth":0.9,
     "regime_probs":{"TREND_UP_STRONG":0.01, "TREND_UP_MILD":0.55, ...},
     "consensus":0.68, "hmm_state":2, "price":64800.0,
     "indicators":{"ma_alignment_score":0.6, "dow_hhhl_score":1.33, ...}}
    // 90 条
  ]
}
```

**Phase 0 验收脚本**：
```bash
python run_evolution_pipeline.py --csv ... --out sample.json --window 90 2>&1 | tail -10
# 期望：90% 的日 consensus ≥ 0.30
# 期望：99% 的相邻日 |ΔL|+|ΔT| ≤ 0.50（钳制生效）
# 期望：4 个关键日期（人工标注）的 Level/Trend 在合理象限
#   - 2021-11-10（历史高点 ~69k）→ Level ≥ +2.5
#   - 2022-11-21（FTX 低点 ~15.5k）→ Level ≤ -2.5
#   - 2024-04-20（减半启动 ~64k）→ Trend ≥ +1.0
#   - 2025-10（当前牛市顶附近）→ Trend ≤ +2.5 且 Level ≥ +3.0
```

### P0.6 Phase 0 TDD 测试文件

**新建** `.../tests/test_evolution_phase0.py`（~120 行）
- `test_indicator_bank_shape`：12 指标 + 原始值 shape OK
- `test_score_composer_clamp`：人工构造跳变输入，输出连续性
- `test_regime_probs_sum_to_1`：Mapper 输出 8 概率严格 = 1
- `test_end_to_end_sample50`：取前 200 根数据，run pipeline 无异常

---

## Phase 1：完善机制 + SQLite + 4 API（4 天）

### P1.1 规则 2：Sperandeo 1-2-3 渐进调整

**文件**：修改 `.../bcrm2/score_composer.py` 增加 `apply_sperandeo_adjustment(level_seq, trend_seq, high_seq, low_seq, close_seq, swing_window=5)`。

**实现步骤**：
1. Swing 检测（复用 IndicatorBank 中 dow_hhhl_score 的 `_detect_swings`），得到 pivot SH/SL 列表
2. 近 2 个 SH 和 1 个 SL：
   - 条件①「突破趋势线」：用 SH1-SH2 下降趋势线的线性回归，当前 close 上穿 → Trend +0.33
   - 条件②「回撤不破前低」：回撤最低 close > SL1 → Trend +0.33
   - 条件③「突破前高」：close > SH2 → Trend +0.34（累计 +1.0）
3. 下降趋势同理（三条累计 Trend -1.0）
4. 每条条件不满足 = +0，**不反向扣分**

**测试**：`test_evolution_phase1.py::test_sperandeo_123_bullish_reversal` — 用手工构造 30 根 reversal 序列，断言逐步加分

### P1.2 规则 4：BOCPD 变点 5 日渐进调整

**文件**：修改 `.../bcrm2/temporal_smoother.py` 中 `TemporalSmoother` 添加 bocpd 更新。

**实现**：
```python
class TemporalSmoother:
    def __init__(self, bocpd_hazard=0.01, trigger_p=0.7, volume_ratio_thr=1.5):
        self.bocpd = BOCPD(hazard=bocpd_hazard)
        self.trigger_p = trigger_p
        self.volume_ratio_thr = volume_ratio_thr
        self._pending_adjustments: List[Dict] = []  # [{day_offset, sign, daily_amount}]

    def step(self, i, ret1d, trend_prior, volume, vol_ma20) -> Tuple[float, float]:
        """每日 step：
          1. bocpd.update(ret1d) → cp_prob
          2. if cp_prob > trigger_p AND (volume/vol_ma20) > volume_ratio_thr:
               sign = +1 if 未来 5 日收益 sign（回测可用，实盘用 2 日 EMA 估计）
               pending_adjustments 压入 5 日 × (sign × 0.30 / 5 = sign × 0.06)
          3. 对已有 pending，逐日应用 ±0.06 到 Trend（与 clamp 叠加，钳制为外部最后一道闸）
        """
```

**BOCPD 序列观测**：close 1d log-return（`np.log(close[i]/close[i-1])`）

### P1.3 L4-2：点阵图 12×8 支持度矩阵

**文件**：`.../bcrm2/regime_mapper.py` 新增 `compute_dotplot_support(indicators:Dict[str,Series], regime_labels:pd.Series) -> np.ndarray`（训练时计算，持久化 CDF LUT）+ `indicator_support(indicator_value, cdf_lut) -> float`（在线时查询）。

**算法（指标→形态支持度）**：
- 离线（训练 pipeline 最后一步）：对 8 态中每种标签样本，建立该指标值的 ECDF（经验累积分布函数），并保存为 `cdf_lut = { regime_name -> { indicator_name -> { quantile_x, quantile_y } } }`
- 在线：给定某一指标值 v，查询在 regime X 的 ECDF → 得到分位数 q ∈ [0, 1]；若 q ∈ [0.05, 0.95] → 该指标对 regime X 支持度高（0.8-1.0），否则低（0.0-0.4）。支持度 = 1 - 2 * |q - 0.5|

**输出**：`dotplot { rows:[12指标], cols:[8态名], matrix:float[12][8], marginal_probs:float[8] }`

### P1.4 L4-3：Consensus 共识度 + L4-4 LGBM 集成加权

已在 P0.4 中实现骨架，P1.4 做以下增强：
- Consensus 输出同时计算 **rolling_5_consensus**（5 日均值，避免单日极端）
- LGBM 集成：用 `ARTIFACT_DIR / "best.lgb"` 读取 RegimePredictor 的 predict_proba()，与软分配按 w_mapper=0.7, w_lgbm=0.3 加权。若 LGBM 加载失败只保留软分配（降级）。

### P1.5 SQLite 持久化

**文件**：修改 `.../bcrm2/storage.py`（替换 JSON 存储），Schema 见 Spec §4.1-4.3。

**库选型**：Python 内置 `sqlite3`（无需额外安装）。

**核心接口**：
```python
class EvolutionStorage:
    def __init__(self, db_path: Path):
        # 不存在则创建三张表
        # regime_state_daily, regime_trajectory_90d, regime_model_weights

    def upsert_daily(self, symbol: str, frame: RegimeStateFrame) -> None:
        """INSERT OR REPLACE"""

    def get_trajectory(self, symbol: str, window: int = 90) -> List[Dict]:
        """最近 N 天"""

    def get_latest_dotplot(self, symbol: str) -> Dict:
        """最新一日的 dotplot 结构"""

    def get_indicators_evolution(self, symbol: str, names:List[str], window:int) -> Dict[str, List[float]]:
        """12 指标 N 日历史"""

    def save_weekly_weights(self, week_start: date, weights_obj: Dict, objective: float) -> None:
        """在线学习产物"""
```

### P1.6 Flask 新增 4 条 API

**文件**：修改 `.../10-经典指标系统/ml_trade_service.py`（末尾追加）

**导入**：
```python
import sys
_BCRM2_DIR = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4"
if _BCRM2_DIR not in sys.path: sys.path.insert(0, _BCRM2_DIR)
from bcrm2.run_evolution_pipeline import ensure_evolution_db, get_storage
```

**四条路由**：
```python
@app.route("/regime/evolution/latest", methods=["GET"])
def regime_evolution_latest():
    """
    Query: symbol=BTCUSDT&window=90
    返回: {trajectory:[90], dotplot, indicators:{12×90}, snapshot_latest}
    """
    symbol = request.args.get("symbol", "BTCUSDT")
    window = int(request.args.get("window", 90))
    storage = get_storage()
    return jsonify({
        "trajectory": storage.get_trajectory(symbol, window),
        "dotplot":    storage.get_latest_dotplot(symbol),
        "indicators": storage.get_indicators_evolution(symbol, _ALL12, window),
        "snapshot":   storage.get_snapshot(symbol),
    })

@app.route("/regime/evolution/trajectory", methods=["GET"])
def regime_evolution_trajectory():
    """start/end/symbol — 自定义时间区间 trajectory"""

@app.route("/regime/evolution/dotplot_average", methods=["GET"])
def regime_dotplot_average():
    """区间平均点阵图（Panel 2 切换显示用）"""

@app.route("/regime/evolution/weights/latest", methods=["GET"])
def regime_weights_latest():
    """当前生效的 Level/Trend 权重，供前端诊断"""
```

**与现有 Macro / Viz 路由风格完全一致**：`@app.route(...)` + `request.args.get(...)` + `return jsonify(...)`。

### P1.7 Phase 1 验收

```bash
# 启动后端
python /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统/ml_trade_service.py &
# HTTP 验证
curl -s http://localhost:8092/regime/evolution/latest?window=90 | python -c "import json,sys;d=json.load(sys.stdin);print(len(d['trajectory']), list(d['snapshot'].keys()))"
# 期望: 90, [...RegimeStateFrame 所有字段...]
# 运行测试
pytest -q ../tests/test_evolution_phase1.py -v
```

---

## Phase 2：前端四面板仪表盘（4 天）

### P2.1 新页面路由 + 侧边栏入口

**文件**：`App.tsx` + 新建 `components/RegimeEvolutionPage.tsx`（主页面容器）

**步骤**：
1. `App.tsx` import RegimeEvolutionPage
2. 侧边栏（ShellLayout 区域）新增 NavLink：`/evolution` icon=LineChart label="形态演化"（放在 `/macro` 和 `/evaluation` 之间）
3. 新建 Route：`<Route path="/evolution" element={<RegimeEvolutionPage />} />`

### P2.2 前端 API 层扩展

**文件**：`lib/api.ts`（追加，对应 P1.6 的 4 条 Flask 路由）

```typescript
// 新增类型
export type RegimeTrajectoryItem = {
  t: string; level_raw: number; trend_raw: number;
  level_smooth: number; trend_smooth: number;
  regime_probs: Record<string, number>; consensus: number;
  price: number; hmm_state: 0|1|2; indicators?: Record<string,number>;
};
export type RegimeDotplot = {
  rows: string[]; cols: string[]; matrix: number[][]; marginal_probs: number[];
};
export interface RegimeEvolutionLatest {
  trajectory: RegimeTrajectoryItem[];
  dotplot: RegimeDotplot;
  indicators: Record<string, number[]>;
  snapshot: RegimeTrajectoryItem;
}

// 新增 fetch 方法（沿用 api axios 实例，风格与 fetchMacroViz 一致）
export async function fetchRegimeEvolutionLatest(params?: { symbol?: string; window?: number; }) {
  const search = new URLSearchParams(params as Record<string,string> || {});
  return (await api.get<RegimeEvolutionLatest>(`/regime/evolution/latest?${search.toString()}`)).data;
}
export async function fetchRegimeEvolutionTrajectory(params: { symbol?: string; start?: string; end?: string; }) { ... }
export async function fetchRegimeDotplotAverage(params: { symbol?: string; start: string; end: string; }) { ... }
```

### P2.3 Panel 1：Level-Trend 轨迹图

**组件名**：`components/evolution/EvolutionTrajectoryPanel.tsx`

**实现要点**：
- 用 Plotly.js（`react-plotly.js`？现有项目使用 `dream-data-analysis` 中的 Plotly 封装：参考 `dream-data-analysis:SKILL.md` → `render_trend_chart` 等）
- 8 象限背景：Plotly Layout shapes `type: "rect"` 画 8 块半透明色块（颜色 = MacroPage 8 态配色，opacity 0.10~0.15）
- Trajectory 线：`go.Scatter(x=[L], y=[T], mode='lines+markers')`；markers size ∝ consensus；marker color = Top-1 主导态（颜色映射表 REGIME_COLORS 需要常量化，建议直接沿用 existing regime_predictor 配色）
- 播放动画：frames 支持（Plotly frames），每 100ms 推进一天
- Hover tooltip：自定义 hovertemplate，输出日期、价格、L/T、Top3 概率

### P2.4 Panel 2：共识点阵图

**组件名**：`components/evolution/DotplotPanel.tsx`

**实现**：Plotly subplot + 原生 SVG 画圆点（Plotly 无原生 dot matrix，故用 SVG overlay）：
- 12 rows × 8 cols 网格
- 单元格圆点大小：支持度映射半径 1-6 px
- 单元格颜色：指标色系（6 组），可固定按 MA 组=蓝，动量组=绿，量能组=橙，波动率=紫，周期=灰，道氏=红的配色
- 列底聚合条：8 个小 vertical bar height = marginal_probs（用 plotly Bar）
- 行右指标当前值色阶条：SVG 小矩形 + 文字数值

**状态联动**：用户若在 Panel 3 拖动选择区间，本 Panel 自动切换为「区间平均」调用 `/dotplot_average`。

### P2.5 Panel 3：8 态堆叠面积图

**组件名**：`components/evolution/RegimeProbAreaPanel.tsx`

**Plotly 实现**：`go.Scatter(x=dates, y=probs_regime_X, stackgroup='one', fillstyle='tonexty')` × 8。颜色 REGIME_COLORS。

**顶部黑色分歧线**：`1 - consensus` 作为第二条 y 轴（`yaxis='y2'` overlay），范围 [0, 1]。

**BOCPD 变点日竖线**：`layout.shapes` 中 `type: 'line'` 对 cp_prob≥0.7 的日画竖虚线（opacity 0.45）。

**区间选择**：Plotly 自带 rangeselector + dragmode=select → React 回调 `onSelectionChange` → Context 中设置 `selectedTimeRange`，Panel 1/2 订阅此状态同步重渲染。

### P2.6 Panel 4：指标演变诊断条

**组件名**：`components/evolution/IndicatorDiagnosticPanel.tsx`

**双模式**：顶部 Radio 按钮 `Sparkline` / `Heatmap`
- Sparkline 模式：12 个迷你 Plotly subplots（共享 x 轴，各小折线 + ±1σ 带），Plotly `make_subplots(rows=12, cols=1, shared_xaxes=True, vertical_spacing=0.02)`
- Heatmap 模式：`go.Heatmap(z=normalized_indicators_12×90, colorscale='RdYlGn')`（绿看多、黄中性、红看空）

每行列尾 = 最新值大字号 Badge（色阶文字 color）+ 数值。

### P2.7 全局联动 EvolutionContext + 响应式布局

**组件名**：`components/evolution/EvolutionContext.tsx`（新建）+ `RegimeEvolutionPage.tsx` 改造

**Context 状态**：
```typescript
type EvolutionState = {
  data: RegimeEvolutionLatest | null;
  loading: boolean;
  focusDate: string | null;         // Panel 1 hover 日
  selectedRange: [string, string] | null;  // Panel 3 拖拽区间
  setFocusDate(d: string | null): void;
  setSelectedRange(r: [string,string] | null): void;
};
```

**响应式布局**：`grid grid-cols-1 lg:grid-cols-2 gap-4` — 大屏 2×2，小屏 1×4 纵排。每 Panel 包裹在 `Card + CardHeader + CardContent` 现有 UI 组件中（直接 import `components/ui/card`）。

### P2.8 Phase 2 验收

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统/frontend
npm run build 2>&1 | tail -20
# 期望：TypeScript 0 错误，构建成功
# 本地浏览：http://localhost:5173/evolution （与后端联调，后端启动在 8092）
# 人工验收：
#  - 首屏 4 面板全渲染
#  - 轨迹图 90 日动画播放正常
#  - Panel 3 拖拽选择区间 → Panel 1/2 同步切换
#  - Panel 4 Sparkline/Heatmap 切换无错
```

---

## Phase 3：在线学习 + WalkForward 验收（3 天）

### P3.1 冷启动中心坐标统计

**脚本**：`.../bcrm2/scripts/calibrate_regime_centers.py`（新建，~80 行）

执行：
```bash
python calibrate_regime_centers.py --csv BTC_1D_full.csv --out regime_centers_cold.json
# 输出: {"TREND_UP_STRONG": [2.5, 3.5], ...}
# 对比人工初始值，差超 0.5 格的记录下来
```

将结果写入 `regime_mapper.py:REGIME_CENTERS`。

### P3.2 8 态冷启动 8 态标签 Top-3 命中率回测基线

**脚本**：`.../bcrm2/scripts/eval_walkforward.py`（新建，~200 行）

步骤：
1. 复用 `walk_forward_splitter.py:walk_forward_time_series_split(n=5, expanding=True)`（已有）
2. 对每折：
   - Train 段：校准 REGIME_CENTERS（train 段内标签统计的均值）+ 计算 Level/Trend 权重（用 train 段内 Score 与标签的 rank correlation 做权重微调的启发式，不做过深度优化，先 baseline）
   - Test 段：用 train 段得到的 centers/weights，Mapper 输出 8 概率
   - 统计：Top-3 命中率（真实标签在前 3）、WalkForward Macro F1（若 argmax 与真实标签的 f1_score weighted macro）
3. 合并 5 折 → 汇总指标

```bash
python eval_walkforward.py --csv BTC_1D_full.csv --out ../../artifacts/evolution_btc/wf_baseline.json
```

**产物**：`wf_baseline.json` 含 5 折 Top-3 命中率、Macro F1、每折标签分布。与旧范式（train_report.json 中 avg Macro F1 = 0.299）对比；Top-3 命中率 ≥ 0.70 验收。

### P3.3 坐标连续性 + 拐点滞后统计

**脚本**：`.../bcrm2/scripts/eval_continuity.py`（新建，~80 行）

- 连续性 = 全样本 mean(|ΔL| + |ΔT|)
- 4 个人工拐点（2021-11 顶 / 2022-11 底 / 2024-04 减半启动 / 本轮顶）：先确定真实极值日日期（历史极值），再找最近一次 Sperandeo 123 第 3 条满足日的滞后天数

```bash
python eval_continuity.py --csv BTC_1D_full.csv
# 期望：mean |Δ| ≤ 0.20 / 天；4 拐点滞后 ≤ 10 根日线
```

### P3.4 周度在线学习 batch 脚本

**文件**：`.../bcrm2/scripts/weekly_online_learning.py`（新建，~250 行）

**调参**：BayesOpt（`pip list | grep bayes`，若未安装退化为网格搜索 3^4 组合，参数空间很小完全可接受）。

**搜索空间**（Spec §3.4）：
- Level 6 权重 × [0.90, 1.00, 1.10] 乘数（基础即当前值）
- Trend 5 权重 × [0.90, 1.00, 1.10] 乘数
- 8 态中心每个坐标 ± {0, 0.3}（2^16 = 65536 太大，做贝叶斯采样 128 次）
- MAX_DAILY_DELTA ∈ {0.3, 0.4, 0.5, 0.6, 0.8}

**目标函数计算**：Top-3 × 0.40 - ContinuityLoss × 0.25 + MacroF1 × 0.20 + Consensus-R² × 0.15。

**执行 & 保存**：计算得到的 weights_obj + objective 落表 `regime_model_weights`；若相比上周目标函数下降 ≥2% → DB 回滚，保留上周，在 log 中写「rejected -2%」。

**触发方式**：
```bash
python weekly_online_learning.py --csv BTC_1D_full.csv --storage ../../artifacts/evolution_btc/evolution.db
# 最终：打印 Summary
#   prev_obj: 0.633  new_obj: 0.657  (+3.8%)   -> accepted
#   或 prev_obj: 0.657  new_obj: 0.633  (-3.7%)   -> REJECTED
```

### P3.5 验收报告汇总 + 人工关键区间检视

**产物**：`/11-易经推理系统/artifacts/evolution_btc/acceptance_report.md`（~300 行，Markdown）

必包含：
- WalkForward 5 折 Top-3 命中率 / Macro F1 / 每折明细（表格）
- 连续性 & 拐点滞后统计（表格）
- 4 个关键区间截图：Panel 1 轨迹图在 2021Q4 顶 / 2022Q4 底 / 2024Q2 减半启动 / 2025 当前 — 人工审阅意见
- 在线学习首轮更新结果：prev vs new 权重、中心坐标、obj、是否 accept

**Go/No-Go 决策表（Spec §八）全部量化对比**：

| KPI | 基线（Spec §1.3） | 实际值 | Pass？ |
|---|---|---|---|
| Top-3 命中率 | ≥ 0.70 | | |
| 连续性 | ≤ 0.20 / 天 | | |
| 拐点滞后 | ≤ 10 根 | | |
| Consensus vs Ret20 R² | ≥ 0.30 | | |
| WalkForward Macro F1 | ≥ 0.45 | | |
| 4 区间人工检视 | OK | | |

6 项全满足 = Go，否则列出不通过项及后续修复建议。

---

## 交付文件总清单（按 Phase 分组）

### 新增文件（共 13 个 Python + 5 个 TSX/TS + 1 个报告）

```
bcrm2/
├── indicators.py                     # P0.1 IndicatorBank（~300 行）
├── score_composer.py                 # P0.2 + P1.1 Sperandeo 123（~350 行）
├── temporal_smoother.py              # P0.3 + P1.2 BOCPD 渐进（~320 行）
├── regime_mapper.py                  # P0.4 + P1.3 点阵图支持度（~400 行）
├── storage.py                        # P0.5 JSON + P1.5 SQLite（~280 行）
├── run_evolution_pipeline.py         # P0.5 CLI 入口（~120 行）
├── scripts/
│   ├── calibrate_regime_centers.py   # P3.1 冷启动中心（~80 行）
│   ├── eval_walkforward.py           # P3.2 WF Top-3 回测（~200 行）
│   ├── eval_continuity.py            # P3.3 连续性 + 拐点滞后（~80 行）
│   └── weekly_online_learning.py     # P3.4 周度 batch（~250 行）
tests/
├── test_evolution_phase0.py          # P0.6（~120 行）
└── test_evolution_phase1.py          # P1 相关测试（~150 行）

frontend/src/
├── components/
│   ├── RegimeEvolutionPage.tsx       # P2.1 主容器（~150 行）
│   └── evolution/
│       ├── EvolutionContext.tsx      # P2.7 Context（~60 行）
│       ├── EvolutionTrajectoryPanel.tsx  # P2.3（~280 行）
│       ├── DotplotPanel.tsx          # P2.4（~220 行）
│       ├── RegimeProbAreaPanel.tsx   # P2.5（~200 行）
│       └── IndicatorDiagnosticPanel.tsx  # P2.6（~260 行）
└── lib/api.ts                        # P2.2 追加（+80 行）

ml_trade_service.py                   # P1.6 4 条路由（+~150 行，末尾插入）

artifacts/evolution_btc/
├── sample_trajectory.json            # Phase 0 产物
├── evolution.db                      # Phase 1 SQLite DB
├── wf_baseline.json                  # Phase 3 WF 回测产物
└── acceptance_report.md              # Phase 3 验收报告
```

### 修改文件（共 4 个）

1. `lib/api.ts` + API 类型与 fetch 方法（P2.2）
2. `App.tsx` + 路由 & 侧边栏入口（P2.1）
3. `ml_trade_service.py` + 4 API 路由（P1.6）
4. `regime_predictor_config.json` — 无需修改，新引擎独立运行（LGBM 做为独立验证信号被读取，路径仍保留为 `artifacts/regime_predictor_btc/best.lgb`）

---

## 每日里程碑总览（14 天）

| 日 | Phase | 产出 | 关键验收 |
|---|---|---|---|
| D1 | P0.1 + P0.2 | indicators.py + score_composer.py | 12 指标 shape OK；钳制连续性通过 |
| D2 | P0.3 + P0.4 | temporal_smoother.py + regime_mapper.py | HMM 3 态训练 OK；8 概率 sum=1 |
| D3 | P0.5 + P0.6 + 验收 | storage.py JSON + run_evolution_pipeline.py + tests | sample.json 90 条 OK；4 关键日期象限正确 |
| D4 | P1.1 + P1.2 | Sperandeo 123 + BOCPD 渐进 | 手工 reversal 序列断言通过 |
| D5 | P1.3 + P1.4 | 点阵图 CDF LUT + LGBM 集成加权 | dotplot matrix shape 12×8；概率值有效 |
| D6 | P1.5 SQLite | 三张表 DDL + DML | storage 读写全测试通过 |
| D7 | P1.6 4 API + 验收 | ml_trade_service.py Flask 路由 | curl 返回完整 JSON |
| D8 | P2.1 + P2.2 | 路由/API 层 | TypeScript 编译；api.get 200 |
| D9 | P2.3 + P2.4 | 轨迹图 + 点阵图（Panel 1/2） | 动画播放；hover tooltip |
| D10 | P2.5 + P2.6 | 面积图 + 诊断条（Panel 3/4） | 区间拖动；Sparkline/Heatmap 切换 |
| D11 | P2.7 响应式 + 验收 | EvolutionContext + 2×2 布局 | 大屏/小屏全渲染；构建 0 err |
| D12 | P3.1 + P3.2 | 中心校准 + WF 基线 | Top-3 ≥ 0.70？ |
| D13 | P3.3 + P3.4 | 连续性评估 + 在线学习 batch | lag ≤ 10；首次 online_learning 执行 |
| D14 | P3.5 | acceptance_report.md + Go/No-Go 决策 | 6 项全通过 = 进入实盘（Phase 4 独立 spec） |
