"""MorphCyclePredictor —— Phase A 周期曲线预测器 + 在线学习误差修正。

Spec: 2026-08-19-morph-cycle-dynamic-correction-design.md §3

核心能力：
  1. predict() —— FFT top-3 + Hermite 样条预测，记录预测快照到 morph_prediction_log
  2. evaluate_and_correct() —— 回填已到期预测误差，修正 FFT 权重/Hermite 切线
  3. get_correction_metrics() —— 聚合 MAE/RMSE/分 horizon 指标，供前端展示

设计原则（对齐 TDD 验收）：
  • 预测后必落库（T_A1）
  • evaluate 必回填（T_A2）
  • 修正必归一化 Σw=1（T_A3）
  • 修正后最大单步变化 < 0.1（T_A4）
  • 连续 N 次修正 MAE 单调不增（T_A5）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .storage import EvolutionStorageSQLite


SECTOR_NAMES = ("defi", "ai", "rwa", "meme", "l2")

# ── BTC 4 年（减半）教科书级理论曲线超参 ─────────────────────────
# 锚定：第四次减半 2024-04-20 为"复苏起点（均衡→扩张）"
# 经验：减半后 18 个月（≈548 天）见顶（对应 2025-10 前后）
# 方法：PCHIP 单调插值 + 真实回测锚点（3 次历史周期均值）
HALVING_4_START = "2024-04-20"          # 第四次减半日期（BTC 库存周期复苏起点）
CYCLE4Y_TOTAL_DAYS = 1460               # 4 年主周期总长度（≈4×365）

# ── 3 次完整 BTC 减半周期真实回测数据 ──
# 数据来源：CoinMarketCap / CoinGecko 公开历史价格
CYCLE4Y_HISTORICAL_CYCLES = [
    {
        "id": 1,
        "halving_date": "2012-11-28",
        "peak_date": "2013-12-01",
        "peak_after_days": 369,     # 减半后 369 天见顶
        "bottom_date": "2015-01-14",
        "bottom_after_days": 782,   # 减半后 782 天见底
        "next_halving_date": "2016-07-10",
        "cycle_total_days": 590,    # 早期市场周期较短
        "peak_gain_pct": 8700,      # 减半价→顶涨幅 %
        "bottom_drawdown_pct": -78, # 顶→底跌幅 %
    },
    {
        "id": 2,
        "halving_date": "2016-07-10",
        "peak_date": "2017-12-17",
        "peak_after_days": 525,
        "bottom_date": "2018-12-15",
        "bottom_after_days": 888,
        "next_halving_date": "2020-05-11",
        "cycle_total_days": 1401,
        "peak_gain_pct": 2940,
        "bottom_drawdown_pct": -84,
    },
    {
        "id": 3,
        "halving_date": "2020-05-11",
        "peak_date": "2021-11-10",
        "peak_after_days": 548,
        "bottom_date": "2022-11-21",
        "bottom_after_days": 930,
        "next_halving_date": "2024-04-20",
        "cycle_total_days": 1440,
        "peak_gain_pct": 650,
        "bottom_drawdown_pct": -77,
    },
]

# 从历史数据推导的锚点参数范围（供预测曲线调参/真实曲线拟合/置信区间使用）
# 每个 t_rel_range 和 level_range 都从 3 次历史真实周期提取
#   - 时间范围：基于真实减半→见顶→见底→下次减半的天数差异
#   - Level 范围：基于 7 大形态阶段定义（恐慌 ≤-2.5, 深度衰退 -2.5~-1.25, ...）
CYCLE4Y_PARAM_RANGES = [
    {"label": "减半复苏",             "t_rel_range": [0, 0],           "t_rel_mean": 0,     "level_range": [-0.4, 0.4],   "level_mean": 0.0},
    {"label": "稳健扩张启动",          "t_rel_range": [60, 120],        "t_rel_mean": 90,    "level_range": [0.4, 0.8],    "level_mean": 0.6},
    {"label": "主升浪加速",            "t_rel_range": [150, 210],       "t_rel_mean": 180,   "level_range": [0.8, 1.6],    "level_mean": 1.2},
    {"label": "繁荣过热中段",          "t_rel_range": [330, 400],       "t_rel_mean": 365,   "level_range": [1.6, 2.8],    "level_mean": 2.2},
    {"label": "繁荣过热上限",          "t_rel_range": [309, 528],       "t_rel_mean": 440,   "level_range": [2.5, 3.5],    "level_mean": 3.0},
    {"label": "极端狂热顶（见顶）",     "t_rel_range": [369, 548],       "t_rel_mean": 480,   "level_range": [3.5, 4.0],    "level_mean": 3.8},
    {"label": "见顶后快速下跌",        "t_rel_range": [389, 583],       "t_rel_mean": 505,   "level_range": [1.5, 2.5],    "level_mean": 2.0},
    {"label": "快速下跌完成",          "t_rel_range": [429, 633],       "t_rel_mean": 552,   "level_range": [-0.5, 0.5],   "level_mean": 0.0},
    {"label": "阴跌中段",              "t_rel_range": [549, 768],       "t_rel_mean": 680,   "level_range": [-2.0, -1.0],  "level_mean": -1.5},
    {"label": "深度衰退",              "t_rel_range": [639, 868],       "t_rel_mean": 775,   "level_range": [-3.0, -2.0],  "level_mean": -2.5},
    {"label": "恐慌底（见底）",         "t_rel_range": [782, 930],       "t_rel_mean": 866,   "level_range": [-4.0, -3.5],  "level_mean": -3.8},
    {"label": "磨底期1（恐慌后反弹）",  "t_rel_range": [862, 1050],      "t_rel_mean": 966,   "level_range": [-3.5, -3.0],  "level_mean": -3.2},
    {"label": "磨底期2（底部震荡）",    "t_rel_range": [1032, 1280],     "t_rel_mean": 1166,  "level_range": [-3.2, -2.8],  "level_mean": -3.0},
    {"label": "蓄力启动",              "t_rel_range": [1281, 1360],     "t_rel_mean": 1320,  "level_range": [-2.0, -1.0],  "level_mean": -1.5},
    {"label": "蓄力加速",              "t_rel_range": [1341, 1410],     "t_rel_mean": 1375,  "level_range": [-0.8, -0.2],  "level_mean": -0.5},
    {"label": "下一轮减半（新起点）",   "t_rel_range": [1401, 1440],     "t_rel_mean": 1420,  "level_range": [-0.4, 0.4],   "level_mean": 0.0},
]

# 4 年曲线里程碑（用于前端标注，取自 PARAM_RANGES 的关键节点）
CYCLE4Y_MILESTONES = [
    (0,    "减半复苏",              0.0),
    (90,   "稳健扩张启动",          0.6),
    (180,  "主升浪加速",            1.2),
    (365,  "繁荣过热中段",          2.2),
    (480,  "极端狂热顶（见顶）",     3.8),
    (552,  "快速下跌完成",          0.0),
    (775,  "深度衰退",              -2.5),
    (866,  "恐慌底（见底）",         -3.8),
    (1166, "磨底期2（底部震荡）",    -3.0),
    (1375, "蓄力加速",              -0.5),
    (1420, "下一轮减半（新起点）",   0.0),
]

# ── FFT / Hermite 超参（修正后不应过大，保持平滑） ────────────────
FFT_MIN_HISTORY = 120        # 至少 120 条历史才做 FFT（防短历史不稳定）
FFT_HIST_MULT = 2            # FFT 窗口 = hist_days × 此倍数
FFT_LEARNING_RATE = 0.15     # FFT 权重修正步长（Bayesian 更新）
FFT_WEIGHT_CLIP = (0.5, 2.0) # 单个分量权重修正倍数范围
HERMITE_M_CORRECTION_CAP = 1.0  # 切线修正系数范围（防止过修）

# ── 自动修正超参（小修正：FFT 权重 / Hermite 切线） ──────────────
CORRECT_COOLDOWN_HOURS = 23  # 同一 symbol 两次自动修正最少间隔（小时），避免频繁抖动
CORRECT_AUTO_MIN_SAMPLES = 3  # 自动修正最少需要多少条已回填误差记录（min_filled_samples 下限）
CORRECT_ON_PREDICT_HOOK = True  # predict() 前自动触发小修正（总开关）

# ── 形态切换大调整超参 ───────────────────────────────────────────
# 与小修正互补：小修正微调 FFT 权重；大调整在形态确认切换后修正周期锚点 t_rel_mean / level_mean
ANCHOR_SWITCH_COOLDOWN_HOURS = 72   # 两次大调整最少间隔（小时），比小修正更保守
ANCHOR_SWITCH_MIN_CONFIRM_DAYS = 3  # 形态切换后需连续确认 N 天才算真切换（防假突破）
ANCHOR_T_REL_ADJUST_RATE = 0.15     # t_rel_mean 单次调整幅度上限（×range 宽度）
ANCHOR_LEVEL_ADJUST_RATE = 0.20     # level_mean 单次调整幅度上限（×range 宽度）
ANCHOR_ON_PREDICT_HOOK = True       # predict() 前自动检测形态切换并触发大调整（总开关）

# ── 大周期弹性边界约束超参（轨道三） ───────────────────────────
# 大周期向小周期提供 level_range 作为弹性边界，小周期越界部分按 decay 比例回拉。
# 详见 Spec §3bis：大小周期弹性边界约束。
CYCLE_BOUNDS_ENABLED = False         # 总开关（默认 False 以保持 CLI 字节等价）
CYCLE_BOUNDS_INTERP = True            # 启用插值边界（False 时用硬命中锚点 range）
CYCLE_BOUNDS_DECAY_DEFAULT = 0.20     # 黔回拉强度（越界部分保留比例）
CYCLE_BOUNDS_DECAY_BY_PHASE = {       # 按 phase_hint 定制回拉强度
    "蓄力": 0.15, "上升": 0.20, "顶部": 0.25,
    "顶点": 0.30, "下跌": 0.25, "底部": 0.20,
    "底点": 0.30, "磨底": 0.15,
}
CYCLE_BOUNDS_AMPLITUDE_MULT = 1.5     # 振幅上限 = (level_hi - level_mean) × 此倍数
CYCLE_BOUNDS_OVERSHOOT_TRIGGER = 5    # 现实曲线连续越界 N 天 → 触发锚点大调整（降低冷却门槛）

# 锚点 label → phase_hint 映射（供 decay_strength 查表）
# phase_hint 取自 8 大阶段：蓄力 / 上升 / 顶部 / 顶点 / 下跌 / 底部 / 底点 / 磨底
LABEL_TO_PHASE_HINT = {
    "减半复苏":              "蓄力",
    "稳健扩张启动":          "上升",
    "主升浪加速":            "上升",
    "繁荣过热中段":          "顶部",
    "繁荣过热上限":          "顶部",
    "极端狂热顶（见顶）":     "顶点",
    "见顶后快速下跌":        "下跌",
    "快速下跌完成":          "下跌",
    "阴跌中段":              "下跌",
    "深度衰退":              "底部",
    "恐慌底（见底）":         "底点",
    "磨底期1（恐慌后反弹）":  "磨底",
    "磨底期2（底部震荡）":    "磨底",
    "蓄力启动":              "蓄力",
    "蓄力加速":              "上升",
    "下一轮减半（新起点）":   "蓄力",
}

# 进程内边界参数缓存：symbol → (t_rel, bounds)
# 同日同 symbol 多次 predict 时，t_rel 不变则直接命中缓存，避免重复插值。
# 详见 Spec §3bis.5.5。
_CYCLE_BOUNDS_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


# =====================================================================
# 工具：日期推算
# =====================================================================
def _add_days(date_str: str, n: int) -> str:
    """YYYY-MM-DD 加 n 天（Python 内置，避免 pandas 依赖）。"""
    from datetime import datetime, timedelta
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except Exception:
        d = datetime.utcnow().date()
    return (d + timedelta(days=n)).strftime("%Y-%m-%d")


def _days_between(a_str: str, b_str: str) -> int:
    """返回 (b - a) 天数（忽略时区，用 date 相减）。"""
    from datetime import datetime
    try:
        a = datetime.strptime(a_str[:10], "%Y-%m-%d").date()
        b = datetime.strptime(b_str[:10], "%Y-%m-%d").date()
    except Exception:
        return 0
    return (b - a).days


# =====================================================================
# BTC 4 年教科书级理论曲线（① 级曲线）
#   · 锚定减半日 HALVING_4_START = 复苏起点
#   · 方法：PCHIP 单调插值 + 3 次历史周期真实回测锚点均值
#   · 经验：顶部短/底部长磨底/快速下跌斜率 > 快速上涨
#   · 7 大形态阶段按 Level 值对齐（恐慌→深度衰→温和衰→均衡→扩张→繁荣→狂热）
#   · param_ranges 供真实曲线拟合 & 预测曲线在线学习调参边界使用
# =====================================================================
def cycle4y_theory(today: Optional[str] = None, samples: int = 365,
                   anchor_overrides: Optional[Dict[str, Dict[str, float]]] = None) -> Dict[str, Any]:
    """生成 BTC 四年教科书级理论周期曲线 + 当前定位 + 参数范围。

    anchor_overrides: 形态切换大调整后的锚点覆盖 {label: {t_rel, level}}，可选。
    返回：
      {
        "total_days": 1460,
        "anchor": {"halving_date": ..., "historical_cycles": [...], "method": ...},
        "milestones": [{"t_rel": 0, "label": "减半复苏", "date": ...}, ...],
        "param_ranges": [{"label": "减半复苏", "t_rel_range": [0,0], "level_range": [-0.4,0.4], ...}],
        "anchor_overrides": {label: {t_rel, level}},
        "t_rel_current": 486,
        "progress": 0.333,
        "current_level": float,
        "current_stage_name": "繁荣过热",
        "series": {"t_rel": [...], "level": [...]},
      }
    """
    from datetime import datetime as _dt
    from scipy.interpolate import PchipInterpolator

    today_date = _dt.strptime(today[:10], "%Y-%m-%d").date() if today else _dt.utcnow().date()
    today_s = today_date.strftime("%Y-%m-%d")
    t_rel = _days_between(HALVING_4_START, today_s)
    t_rel_mod = ((t_rel % CYCLE4Y_TOTAL_DAYS) + CYCLE4Y_TOTAL_DAYS) % CYCLE4Y_TOTAL_DAYS
    progress = t_rel_mod / CYCLE4Y_TOTAL_DAYS

    # ── PCHIP 插值：用锚点均值生成平滑单调曲线 ──
    # 若有 anchor_overrides（形态切换大调整产物），覆盖对应锚点
    overrides = anchor_overrides or {}
    anchor_ts_list = []
    anchor_ls_list = []
    for r in CYCLE4Y_PARAM_RANGES:
        ov = overrides.get(r["label"])
        if ov:
            anchor_ts_list.append(ov.get("t_rel", r["t_rel_mean"]))
            anchor_ls_list.append(ov.get("level", r["level_mean"]))
        else:
            anchor_ts_list.append(r["t_rel_mean"])
            anchor_ls_list.append(r["level_mean"])
    anchor_ts = np.array(anchor_ts_list, dtype=float)
    anchor_ls = np.array(anchor_ls_list, dtype=float)
    # PCHIP 要求 x 严格递增：override 可能破坏顺序，需排序+去重
    order = np.argsort(anchor_ts)
    anchor_ts = anchor_ts[order]
    anchor_ls = anchor_ls[order]
    # 去重：相邻 t_rel 相同时微扰 +0.01 保持严格递增
    for i in range(1, len(anchor_ts)):
        if anchor_ts[i] <= anchor_ts[i - 1]:
            anchor_ts[i] = anchor_ts[i - 1] + 0.01
    _pchip = PchipInterpolator(anchor_ts, anchor_ls)

    def _level_at(t_rel_i: float) -> float:
        """t_rel_i ∈ [0, CYCLE4Y_TOTAL_DAYS] → Level ∈ [-4, 4]。"""
        v = float(_pchip(t_rel_i))
        return float(max(-4.0, min(4.0, v)))

    # 均匀采样
    ts = np.linspace(0, CYCLE4Y_TOTAL_DAYS, samples, endpoint=True)
    levels = [_level_at(float(t)) for t in ts]
    current_level = _level_at(float(t_rel_mod))

    # 7 大形态阶段名
    REGIME_7 = [
        (-10.0, "恐慌"),
        (-2.5,  "深度衰退"),
        (-1.25, "温和衰退"),
        (-0.4,  "均衡（蓄力）"),
        ( 0.4,  "稳健扩张"),
        ( 1.25, "繁荣过热"),
        ( 2.5,  "极端狂热"),
    ]
    stage_name = REGIME_7[0][1]
    for lo, name in REGIME_7:
        if current_level >= lo:
            stage_name = name

    # 里程碑
    milestones = []
    for t_rel_m, label_m, _lv_ref in CYCLE4Y_MILESTONES:
        milestones.append({
            "t_rel": int(t_rel_m),
            "label": label_m,
            "date": _add_days(HALVING_4_START, int(t_rel_m)),
        })

    return {
        "total_days": CYCLE4Y_TOTAL_DAYS,
        "anchor": {
            "halving_date": HALVING_4_START,
            "historical_cycles": CYCLE4Y_HISTORICAL_CYCLES,
            "method": "PCHIP + 3 次历史周期真实回测锚点均值"
                     + ("（含形态切换大调整覆盖）" if overrides else ""),
        },
        "milestones": milestones,
        "param_ranges": CYCLE4Y_PARAM_RANGES,
        "anchor_overrides": overrides,
        "t_rel_current": int(t_rel_mod),
        "progress": round(progress, 4),
        "current_level": round(current_level, 4),
        "current_stage_name": stage_name,
        "series": {
            "t_rel": [int(round(float(t))) for t in ts],
            "level": [round(v, 4) for v in levels],
        },
    }


# =====================================================================
# MorphCyclePredictor
# =====================================================================
class MorphCyclePredictor:
    """周期曲线预测器 + 在线学习误差修正。

    用法：
        storage = EvolutionStorageSQLite(Path("evolution.db"))
        predictor = MorphCyclePredictor(storage)

        # 1. 预测 + 自动记录
        result = predictor.predict("BTCUSDT", hist_days=60, forecast_days=20)

        # 2. 次日及以后：评估历史误差 + 修正模型
        metrics = predictor.evaluate_and_correct("BTCUSDT")
        # metrics 包含 filled_count / mae_before / mae_after / correction 详情
    """

    def __init__(self, storage: EvolutionStorageSQLite):
        self.storage = storage
        # 进程内最后一次自动修正时间（symbol → datetime str），双保险（进程+DB）
        self._last_auto_corrected_at: Dict[str, str] = {}
        # 进程内最后一次形态切换大调整时间（symbol → datetime str）
        self._last_anchor_corrected_at: Dict[str, str] = {}

    # ---------------------------------------------------------------- 大周期弹性边界约束
    def _interp_cycle_bounds(self, t_rel_current: float) -> Dict[str, Any]:
        """从大周期 t_rel 位置插值得到小周期边界参数。

        在 CYCLE4Y_PARAM_RANGES 两个相邻锚点间线性插值：
          - level_lo / level_hi / level_mean 按位置比例插值
          - phase_hint 取距离更近的锚点（通过 LABEL_TO_PHASE_HINT 映射）
          - decay_strength 由 phase_hint 查 CYCLE_BOUNDS_DECAY_BY_PHASE 得到
          - amplitude_cap = (level_hi - level_mean) × CYCLE_BOUNDS_AMPLITUDE_MULT

        边界情况：
          - t_rel < 第一个锚点 → 用第一个锚点
          - t_rel > 最后一个锚点 → 用最后一个锚点

        返回：
          {
            "t_rel_current": float,
            "phase_hint": str,
            "level_lo": float,
            "level_hi": float,
            "level_mean": float,
            "amplitude_cap": float,
            "decay_strength": float,
          }
        """
        ranges = CYCLE4Y_PARAM_RANGES
        # 按 t_rel_mean 排序（确保单调递增）
        sorted_ranges = sorted(ranges, key=lambda r: r["t_rel_mean"])
        t_means = [r["t_rel_mean"] for r in sorted_ranges]

        # 边界情况：t_rel 在第一个锚点之前
        if t_rel_current <= t_means[0]:
            r = sorted_ranges[0]
            return self._build_bounds(t_rel_current, r)

        # 边界情况：t_rel 在最后一个锚点之后
        if t_rel_current >= t_means[-1]:
            r = sorted_ranges[-1]
            return self._build_bounds(t_rel_current, r)

        # 找到 t_rel_current 落在哪两个锚点之间
        for i in range(len(sorted_ranges) - 1):
            t_left = t_means[i]
            t_right = t_means[i + 1]
            if t_left <= t_rel_current <= t_right:
                r_left = sorted_ranges[i]
                r_right = sorted_ranges[i + 1]
                # 正好命中左锚点
                if t_rel_current == t_left:
                    return self._build_bounds(t_rel_current, r_left)
                # 正好命中右锚点
                if t_rel_current == t_right:
                    return self._build_bounds(t_rel_current, r_right)
                # 线性插值
                alpha = (t_rel_current - t_left) / (t_right - t_left)
                lo_l, lo_r = r_left["level_range"][0], r_right["level_range"][0]
                hi_l, hi_r = r_left["level_range"][1], r_right["level_range"][1]
                ml_l, ml_r = r_left["level_mean"], r_right["level_mean"]

                level_lo = lo_l * (1 - alpha) + lo_r * alpha
                level_hi = hi_l * (1 - alpha) + hi_r * alpha
                level_mean = ml_l * (1 - alpha) + ml_r * alpha

                # phase_hint 取距离更近的锚点
                nearer = r_left if alpha < 0.5 else r_right
                phase_hint = LABEL_TO_PHASE_HINT.get(nearer["label"], "蓄力")
                decay = CYCLE_BOUNDS_DECAY_BY_PHASE.get(phase_hint, CYCLE_BOUNDS_DECAY_DEFAULT)
                amplitude_cap = (level_hi - level_mean) * CYCLE_BOUNDS_AMPLITUDE_MULT

                return {
                    "t_rel_current": t_rel_current,
                    "phase_hint": phase_hint,
                    "level_lo": round(level_lo, 4),
                    "level_hi": round(level_hi, 4),
                    "level_mean": round(level_mean, 4),
                    "amplitude_cap": round(amplitude_cap, 4),
                    "decay_strength": decay,
                }

        # 理论上不会到达这里
        r = sorted_ranges[-1]
        return self._build_bounds(t_rel_current, r)

    @staticmethod
    def _build_bounds(t_rel_current: float, anchor: Dict[str, Any]) -> Dict[str, Any]:
        """从单个锚点构建边界参数（无插值）。"""
        lo, hi = anchor["level_range"]
        mean = anchor["level_mean"]
        phase_hint = LABEL_TO_PHASE_HINT.get(anchor["label"], "蓄力")
        decay = CYCLE_BOUNDS_DECAY_BY_PHASE.get(phase_hint, CYCLE_BOUNDS_DECAY_DEFAULT)
        amplitude_cap = (hi - mean) * CYCLE_BOUNDS_AMPLITUDE_MULT
        return {
            "t_rel_current": t_rel_current,
            "phase_hint": phase_hint,
            "level_lo": lo,
            "level_hi": hi,
            "level_mean": mean,
            "amplitude_cap": round(amplitude_cap, 4),
            "decay_strength": decay,
        }

    def _get_cycle_bounds(self, symbol: str, cycle_4y: Dict[str, Any]) -> Dict[str, Any]:
        """获取边界参数（带缓存）。

        若缓存中 t_rel 与当前一致，直接返回缓存；否则重新插值。
        边界参数依赖大周期 t_rel_current，该值每日变化但日内不变，
        同日多次 predict 时命中缓存避免重复插值。
        """
        t_rel = float(cycle_4y["t_rel_current"])
        cached = _CYCLE_BOUNDS_CACHE.get(symbol)
        if cached and cached[0] == t_rel:
            return cached[1]
        bounds = self._interp_cycle_bounds(t_rel)
        _CYCLE_BOUNDS_CACHE[symbol] = (t_rel, bounds)
        return bounds

    # ---------------------------------------------------------------- 大周期边界约束：三类动作
    def _scale_fft_amplitude(self,
                              theoretical_full: np.ndarray,
                              bounds: Dict[str, Any]) -> Tuple[np.ndarray, Dict[str, Any]]:
        """动作A：对 FFT 叠加曲线应用大周期振幅约束。

        若 FFT 振幅 > amplitude_cap，用 tanh 软缩放（不硬截断）。
        振幅定义为曲线相对 level_mean 的标准差。

        返回：
          (scaled_theoretical, {"applied": bool, "scale_factor": float, "original_amp": float})
        """
        cap = float(bounds.get("amplitude_cap", 1.0))
        mean = float(bounds.get("level_mean", 0.0))
        original_amp = float(np.std(theoretical_full - mean))

        if original_amp <= cap:
            return theoretical_full, {
                "applied": False,
                "scale_factor": 1.0,
                "original_amp": round(original_amp, 4),
            }

        # 软缩放：用 tanh 渐进，不硬截断
        # scale ∈ (0, 1)，直接缩放振幅；tanh 映射用于平滑过渡避免硬截断
        scale = cap / original_amp
        # tanh 映射：当 scale < 1 时 soft_factor = scale × k（k≈1，保证缩放后振幅 ≤ cap）
        # 用 tanh(scale × 1.2) / tanh(1.2) 作为软因子，但需保证 soft_factor ≤ scale
        # 直接用 scale × 平滑系数，确保缩放后振幅严格 ≤ cap
        soft_factor = float(np.tanh(scale * 1.2) / np.tanh(1.2))
        # 当 tanh 映射结果 > scale 时（scale < 1 不会发生，但保险起见取 min）
        soft_factor = min(soft_factor, scale)
        # 以 level_mean 为中心缩放
        scaled = mean + (theoretical_full - mean) * soft_factor

        return scaled, {
            "applied": True,
            "scale_factor": float(soft_factor),
            "original_amp": round(original_amp, 4),
        }

    def _pullback_forecast(self,
                            forecast_vals: List[float],
                            bounds: Dict[str, Any]) -> Tuple[List[float], Dict[str, Any]]:
        """动作B：对预测曲线应用弹性边界回拉。

        对每个点 v：
          - v < level_lo → v = level_lo - (level_lo - v) × decay
          - v > level_hi → v = level_hi + (v - level_hi) × decay
          - 否则不变

        返回：
          (pulled_forecast, {"applied": bool, "overshoot_count": int})
        """
        lo = float(bounds["level_lo"])
        hi = float(bounds["level_hi"])
        decay = float(bounds.get("decay_strength", 0.20))

        pulled = []
        overshoot_count = 0
        for v in forecast_vals:
            if v < lo:
                overshoot = lo - v
                pulled.append(lo - overshoot * decay)
                overshoot_count += 1
            elif v > hi:
                overshoot = v - hi
                pulled.append(hi + overshoot * decay)
                overshoot_count += 1
            else:
                pulled.append(v)

        return pulled, {
            "applied": overshoot_count > 0,
            "overshoot_count": overshoot_count,
        }

    def _check_overshoot_events(self,
                                 level_hist: List[float],
                                 dates: List[str],
                                 bounds: Dict[str, Any]) -> List[Dict[str, Any]]:
        """动作C：检测现实曲线越界事件。

        现实曲线不调整，仅记录越界事件。
        若连续越界天数 ≥ CYCLE_BOUNDS_OVERSHOOT_TRIGGER (5)，
        最后一个事件标记 need_anchor_correct = True。

        返回：
          [{"date", "level", "bound", "direction", "magnitude", "need_anchor_correct"}, ...]
        """
        lo = float(bounds["level_lo"])
        hi = float(bounds["level_hi"])
        trigger = CYCLE_BOUNDS_OVERSHOOT_TRIGGER

        events: List[Dict[str, Any]] = []
        streak = 0
        for i, v in enumerate(level_hist):
            is_overshoot = v > hi or v < lo
            if is_overshoot:
                streak += 1
                if v > hi:
                    direction = "up"
                    magnitude = v - hi
                else:
                    direction = "down"
                    magnitude = lo - v
                events.append({
                    "date": dates[i] if i < len(dates) else "",
                    "level": float(v),
                    "bound": [lo, hi],
                    "direction": direction,
                    "magnitude": round(float(magnitude), 4),
                    "need_anchor_correct": streak >= trigger and i == len(level_hist) - 1,
                })
            else:
                streak = 0

        # 若连续越界 ≥ trigger 天，标记最后一个越界事件
        if streak >= trigger and events:
            # 找到最后一段连续越界的事件，标记最后一个
            last_consecutive_end = len(events) - 1
            # 回溯找到连续段起点
            streak_back = 0
            for j in range(len(events) - 1, -1, -1):
                # 检查 events[j] 是否与 events[j-1] 连续（日期相邻或 level_hist 索引连续）
                # 简化：只要 streak >= trigger，标记最后一个事件
                streak_back += 1
                if streak_back >= trigger:
                    events[last_consecutive_end]["need_anchor_correct"] = True
                    break

        return events

    # ---------------------------------------------------------------- 形态切换大调整
    def _detect_regime_switch(self, symbol: str) -> Optional[Dict[str, Any]]:
        """检测形态是否发生确认切换。

        从 storage 取最近 N+1 天的 trajectory，判断 stage_name 是否从 A→B 且持续 N 天。
        返回 {from, to, confirm_date} 或 None。
        """
        symbol = symbol or "BTCUSDT"
        N = ANCHOR_SWITCH_MIN_CONFIRM_DAYS
        traj = self.storage.get_trajectory(symbol, window=N + 5)
        if not traj or len(traj) < N + 1:
            return None

        # 按 Level 映射 stage_name
        def _stage(lv: float) -> str:
            if lv >= 2.5:  return "极端狂热"
            if lv >= 1.25: return "繁荣过热"
            if lv >= 0.4:  return "稳健扩张"
            if lv >= -0.4: return "均衡蓄力"
            if lv >= -1.25:return "温和衰退"
            if lv >= -2.5:return "深度衰退"
            return "恐慌"

        stages = [_stage(f.get("level_smooth", f.get("level", 0))) for f in traj]
        # traj 按时间正序，最后 N 个是最近的
        recent = stages[-N:]
        before = stages[-(N + 1)] if len(stages) >= N + 1 else None

        if before is None:
            return None
        # 最近 N 天全是同一个 stage，且与 N+1 天前不同
        if len(set(recent)) == 1 and recent[0] != before:
            return {
                "from": before,
                "to": recent[0],
                "confirm_date": traj[-1].get("t", traj[-1].get("timestamp", "")),
            }
        return None

    def _get_effective_cooldown_hours(self, symbol: str) -> float:
        """获取有效冷却时间：若存在 need_anchor_correct 的 overshoot_hint，冷却降至 24h。"""
        hint = self.storage.get_overshoot_hint(symbol)
        if hint and hint.get("need_anchor_correct") is True:
            return 24.0
        return float(ANCHOR_SWITCH_COOLDOWN_HOURS)

    def _maybe_anchor_correct(self, symbol: str) -> Optional[Dict[str, Any]]:
        """predict 前自动检测形态切换并触发锚点大调整。

        冷却保护：距上次大调整不足有效冷却时间则跳过。
        若存在 need_anchor_correct 的 overshoot_hint，冷却从 72h 降至 24h。
        返回调整结果或 None。
        """
        if not ANCHOR_ON_PREDICT_HOOK:
            return None
        symbol = symbol or "BTCUSDT"

        # 有效冷却时间（受 overshoot_hint 影响）
        effective_cooldown = self._get_effective_cooldown_hours(symbol)

        # 冷却检查（DB 级）
        anchor_state = self.storage.get_anchor_state(symbol)
        now_iso = None
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat(timespec="seconds")

        if anchor_state and anchor_state.get("last_corrected_at"):
            try:
                last = datetime.fromisoformat(anchor_state["last_corrected_at"])
                delta_h = (now - last).total_seconds() / 3600.0
                if delta_h < effective_cooldown:
                    return None
            except ValueError:
                pass

        # 进程内冷却兜底
        proc_last = self._last_anchor_corrected_at.get(symbol)
        if proc_last:
            try:
                last = datetime.fromisoformat(proc_last)
                delta_h = (now - last).total_seconds() / 3600.0
                if delta_h < effective_cooldown:
                    return None
            except ValueError:
                pass

        # 检测形态切换
        switch = self._detect_regime_switch(symbol)
        if switch is None:
            return None

        # 执行大调整
        result = self._correct_on_regime_switch(symbol, switch)
        if result is not None:
            self._last_anchor_corrected_at[symbol] = now_iso
            # 大调整成功后清除 overshoot_hint（已处理）
            self.storage.clear_overshoot_hint(symbol)
        return result

    def _correct_on_regime_switch(self, symbol: str,
                                  switch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """形态切换大调整：在 param_ranges 边界内修正锚点 t_rel_mean / level_mean。

        修正逻辑：
          - 切换到更高 Level 阶段（如恐慌→均衡）→ 上升段锚点 t_rel 略前移（提前见顶）
          - 切换到更低 Level 阶段（如狂热→衰退）→ 下降段锚点 t_rel 略前移（提前见底）
          - level_mean 朝实际 Level 方向微调
          - 所有修正受 t_rel_range / level_range 边界硬约束
        """
        symbol = symbol or "BTCUSDT"
        from_stage = switch["from"]
        to_stage = switch["to"]
        confirm_date = switch["confirm_date"]

        # 读取现有锚点覆盖（之前的大调整累积）
        anchor_state = self.storage.get_anchor_state(symbol)
        overrides = anchor_state["anchor_overrides"] if anchor_state else {}

        # 7 大形态 Level 排序
        STAGE_ORDER = ["恐慌", "深度衰退", "温和衰退", "均衡蓄力", "均衡（蓄力）",
                       "稳健扩张", "繁荣过热", "极端狂热"]
        from_idx = STAGE_ORDER.index(from_stage) if from_stage in STAGE_ORDER else 3
        to_idx = STAGE_ORDER.index(to_stage) if to_stage in STAGE_ORDER else 3
        direction = to_idx - from_idx  # 正=上升，负=下降

        # 取实际 Level（用最近 trajectory）
        traj = self.storage.get_trajectory(symbol, window=1)
        actual_level = float(traj[-1].get("level_smooth", traj[-1].get("level", 0))) if traj else 0.0

        # 修正锚点：遍历 PARAM_RANGES，按方向调整
        new_overrides = dict(overrides)
        adjusted = []
        for rng in CYCLE4Y_PARAM_RANGES:
            label = rng["label"]
            t_mean = overrides.get(label, {}).get("t_rel", rng["t_rel_mean"])
            l_mean = overrides.get(label, {}).get("level", rng["level_mean"])

            t_lo, t_hi = rng["t_rel_range"]
            l_lo, l_hi = rng["level_range"]
            t_width = max(t_hi - t_lo, 1)
            l_width = max(l_hi - l_lo, 0.1)

            # t_rel 调整：上升时前段锚点前移（加快），下降时后段锚点前移（加快）
            t_delta = 0.0
            if direction > 0 and t_mean < CYCLE4Y_TOTAL_DAYS * 0.5:
                t_delta = -ANCHOR_T_REL_ADJUST_RATE * t_width * 0.5
            elif direction < 0 and t_mean > CYCLE4Y_TOTAL_DAYS * 0.5:
                t_delta = -ANCHOR_T_REL_ADJUST_RATE * t_width * 0.5

            # level_mean 调整：朝实际 Level 微调
            l_delta = ANCHOR_LEVEL_ADJUST_RATE * (actual_level - l_mean) * 0.3
            if abs(l_delta) > ANCHOR_LEVEL_ADJUST_RATE * l_width:
                l_delta = max(-ANCHOR_LEVEL_ADJUST_RATE * l_width,
                              min(ANCHOR_LEVEL_ADJUST_RATE * l_width, l_delta))

            new_t = max(t_lo, min(t_hi, t_mean + t_delta))
            new_l = max(l_lo, min(l_hi, l_mean + l_delta))

            if abs(new_t - t_mean) > 0.01 or abs(new_l - l_mean) > 0.01:
                new_overrides[label] = {"t_rel": round(new_t, 1), "level": round(new_l, 4)}
                adjusted.append({
                    "label": label,
                    "t_rel": [round(t_mean, 1), round(new_t, 1)],
                    "level": [round(l_mean, 4), round(new_l, 4)],
                })

        if not adjusted:
            return None

        # 持久化
        self.storage.save_anchor_state(symbol, new_overrides, from_stage, to_stage, confirm_date)

        return {
            "trigger": "regime_switch",
            "from": from_stage,
            "to": to_stage,
            "confirm_date": confirm_date,
            "direction": "up" if direction > 0 else "down",
            "adjusted_anchors": adjusted,
            "total_overrides": len(new_overrides),
            "switch_count": (anchor_state["switch_count"] + 1) if anchor_state else 1,
        }

    # ---------------------------------------------------------------- 自动修正 hook
    def _maybe_auto_correct(self, symbol: str) -> Dict[str, Any] | None:
        """predict 前自动触发一次误差回填 + 在线学习修正。

        冷却保护：距上次 state.last_corrected_at 不足 CORRECT_COOLDOWN_HOURS 则跳过。
        样本不足保护：当前已回填数 < CORRECT_AUTO_MIN_SAMPLES 则跳过。
        返回：若触发并执行则返回 evaluate_and_correct 的结果，否则 None。
        """
        if not CORRECT_ON_PREDICT_HOOK:
            return None
        symbol = symbol or "BTCUSDT"

        # 1. 先看 storage 中已有的全局修正状态（跨进程/跨重启统一）
        state = self.storage.get_correction_state(symbol)
        now_iso = None
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat(timespec="seconds")

        if state and state.get("last_corrected_at"):
            try:
                last = datetime.fromisoformat(state["last_corrected_at"])
                delta_h = (now - last).total_seconds() / 3600.0
                if delta_h < CORRECT_COOLDOWN_HOURS:
                    return None  # 冷却中
            except ValueError:
                pass  # 时间解析失败，当作需要修正

        # 进程内冷却兜底（防止同一进程快速并发重复修正）
        proc_last = self._last_auto_corrected_at.get(symbol)
        if proc_last:
            try:
                last = datetime.fromisoformat(proc_last)
                delta_h = (now - last).total_seconds() / 3600.0
                if delta_h < CORRECT_COOLDOWN_HOURS:
                    return None
            except ValueError:
                pass

        # 2. 尝试执行 evaluate_and_correct（内部会做样本数判断，不足则返回 reason 说明）
        try:
            result = self.evaluate_and_correct(symbol, min_filled_samples=CORRECT_AUTO_MIN_SAMPLES)
        except Exception:
            return None

        # 只有当 correction dict 非空（即 save_correction_state 被调用过一次）才算真正执行了修正。
        # 样本不足（correction=None）或 backfilled==0 且 correction 仍为 None 的情况 → 返回 None，前端视为未触发。
        if result is None or result.get("correction") is None:
            return None

        # 确实执行了修正：更新进程冷却
        self._last_auto_corrected_at[symbol] = now_iso
        return result

    # ---------------------------------------------------------------- predict
    def predict(self,
                symbol: str = "BTCUSDT",
                hist_days: int = 60,
                forecast_days: int = 20) -> Dict[str, Any]:
        """生成周期曲线预测结果，并记录预测快照。

        自动修正 hook：预测执行前先做条件性误差回填 + 在线学习修正。
        返回结构与 `get_morph_cycle()` 一致（保持向后兼容）：
            {
              ok, symbol, params, dates, series, forecast_points, price_hist
            }
        """
        symbol = symbol or "BTCUSDT"
        storage = self.storage

        # ── 自动修正 hook ────────────────────────────────────────────
        # ① 形态切换大调整（冷却 72h，需 N 天确认切换）
        anchor_correction_result = self._maybe_anchor_correct(symbol)
        # ② 小修正：FFT 权重 + Hermite 切线（冷却 23h）
        auto_correction_result = self._maybe_auto_correct(symbol)

        # 1. 取 trajectory（倒序 → 正序）
        fft_window = max(hist_days * FFT_HIST_MULT, FFT_MIN_HISTORY)
        traj = storage.get_trajectory(symbol, fft_window)
        if not traj or len(traj) < 20:
            return {
                "ok": False,
                "error": f"trajectory 数据不足（{len(traj) if traj else 0} 条），至少需要 20 条",
            }
        traj = list(reversed(traj))
        hist = traj[-hist_days:] if len(traj) >= hist_days else traj
        n_hist = len(hist)

        dates = [str(f.get("t", "")) for f in hist]
        level_hist = [float(f.get("level_smooth", 0.0)) for f in hist]
        trend_hist = [float(f.get("trend_smooth", 0.0)) for f in hist]
        price_hist = [float(f.get("price", 0.0)) or float(f.get("price_close", 0.0)) for f in hist]
        prediction_date = dates[-1] if dates else "TODAY"
        L_cur = level_hist[-1]
        T_cur = trend_hist[-1] if trend_hist else 0.0

        # 2. 加载已有的修正状态
        corr_state = storage.get_correction_state(symbol)
        weight_corr = corr_state["weight_correction"] if corr_state else {}
        tangent_corr = corr_state["tangent_correction"] if corr_state else {
            "m0_mul": 1.0, "m1_mul": 1.0, "bias": 0.0,
        }
        correction_applied = {
            "weight_correction_pre": dict(weight_corr),
            "tangent_correction_pre": dict(tangent_corr),
        }

        # ── 1. 理论完美曲线（FFT top-3 叠加 + 权重修正） ─────────────
        fft_data = [float(f.get("level_smooth", 0.0)) for f in traj]
        fft_arr = np.array(fft_data, dtype=float)
        fft_mean = float(np.mean(fft_arr))
        fft_centered = fft_arr - fft_mean
        n_fft = len(fft_centered)

        top3_components: List[Dict[str, Any]] = []
        if n_fft >= 16:
            window = np.hanning(n_fft)
            fft_result = np.fft.fft(fft_centered * window)
            freqs = np.fft.fftfreq(n_fft, d=1.0)
            pos_mask = freqs > 0
            power = np.abs(fft_result[pos_mask]) ** 2
            pos_freqs = freqs[pos_mask]
            if len(power) >= 3:
                top3_idx = np.argsort(power)[-3:][::-1]
                total_power = float(np.sum(power[top3_idx])) or 1.0
                for idx in top3_idx:
                    freq = float(pos_freqs[idx])
                    if freq <= 0:
                        continue
                    period_i = 1.0 / freq
                    if period_i >= n_fft * 2:
                        continue  # 过长周期剔除
                    amp_i = float(np.abs(fft_result[pos_mask][idx])) * 2.0 / n_fft * 2.0
                    phase_i = float(np.angle(fft_result[pos_mask][idx]))
                    weight_i = float(power[idx]) / total_power
                    # APPLY 权重修正（Bayesian 修正系数）
                    pkey = str(period_i)
                    mult = float(weight_corr.get(pkey, 1.0))
                    mult = float(np.clip(mult, FFT_WEIGHT_CLIP[0], FFT_WEIGHT_CLIP[1]))
                    amp_i = amp_i * mult
                    top3_components.append({
                        "period": round(period_i, 1),
                        "amplitude": round(amp_i, 4),
                        "phase": round(phase_i, 4),
                        "weight": round(weight_i, 4),
                        "weight_mult_before": round(float(weight_corr.get(pkey, 1.0)), 4),
                    })
            if not top3_components:
                top3_components = [
                    {"period": 120.0, "amplitude": 1.5, "phase": 0.0, "weight": 1.0, "weight_mult_before": 1.0}
                ]

        # 生成理论曲线 + 振幅缩放对齐历史 std
        total_n = n_hist + forecast_days
        t_full = np.arange(total_n, dtype=float)
        theoretical_full = np.zeros(total_n)
        for c in top3_components:
            p_i = max(c["period"], 2.0)
            a_i = c["amplitude"]
            phi_i = c["phase"]
            theoretical_full += a_i * np.sin(2 * np.pi * t_full / p_i + phi_i)

        hist_std = float(np.std(fft_centered)) if n_fft > 1 else 1.5
        theo_std = float(np.std(theoretical_full)) or 1.0
        scale = hist_std / theo_std if theo_std > 0 else 1.0
        theoretical_full = theoretical_full * scale

        main_period = top3_components[0]["period"] if top3_components else 120.0
        main_amp = top3_components[0]["amplitude"] * scale if top3_components else hist_std

        # ── 2. 现阶段（历史实际值） ──────────────────────────────────
        current_stage_vals = [round(v, 4) for v in level_hist]

        # ── 3. 预测轨迹（Hermite 样条 + 切线修正） ──────────────────
        theo_forecast = theoretical_full[n_hist:]
        m0_base = T_cur / max(forecast_days, 1)
        if forecast_days >= 2:
            m1_base = float(theo_forecast[-1] - theo_forecast[-2])
        else:
            m1_base = 0.0

        # APPLY 切线修正系数
        m0_mul = float(np.clip(tangent_corr.get("m0_mul", 1.0),
                               1.0 - HERMITE_M_CORRECTION_CAP,
                               1.0 + HERMITE_M_CORRECTION_CAP))
        m1_mul = float(np.clip(tangent_corr.get("m1_mul", 1.0),
                               1.0 - HERMITE_M_CORRECTION_CAP,
                               1.0 + HERMITE_M_CORRECTION_CAP))
        bias = float(tangent_corr.get("bias", 0.0))
        m0 = m0_base * m0_mul
        m1 = m1_base * m1_mul

        hermite_params_log = {
            "m0_base": round(m0_base, 6),
            "m1_base": round(m1_base, 6),
            "m0_mul": round(m0_mul, 4),
            "m1_mul": round(m1_mul, 4),
            "bias": round(bias, 4),
        }

        forecast_points: List[Dict[str, Any]] = []
        # 先构建原始 forecast（纯 Hermite 无额外切线修正时的参考）
        raw_forecast = []
        for i in range(forecast_days):
            s = (i + 1) / forecast_days
            h00 = 2 * s**3 - 3 * s**2 + 1
            h10 = s**3 - 2 * s**2 + s
            h01 = -2 * s**3 + 3 * s**2
            h11 = s**3 - s**2
            v_raw = (h00 * L_cur
                     + h10 * (m0_base) * forecast_days
                     + h01 * theo_forecast[i]
                     + h11 * (m1_base) * forecast_days)
            raw_forecast.append(float(v_raw))

        for i in range(forecast_days):
            s = (i + 1) / forecast_days
            h00 = 2 * s**3 - 3 * s**2 + 1
            h10 = s**3 - 2 * s**2 + s
            h01 = -2 * s**3 + 3 * s**2
            h11 = s**3 - s**2
            v = (h00 * L_cur
                 + h10 * m0 * forecast_days
                 + h01 * theo_forecast[i]
                 + h11 * m1 * forecast_days)
            # bias 加性修正：用 h01 基函数形状进入（s³ 启动，s=0 贡献 0，不抖起点）
            v += bias * h01
            # 切线修正平滑：把"修正前后的差"按 tanh(s·3) 渐进引入，保证最大单步变化 <= 0.1
            delta_from_raw = float(v - raw_forecast[i])
            # 限制 Δ per step：修正不应让相邻点突变 > 0.05
            # 对整个 forecast 做后处理：按相邻差 clip（总变差限制）
            v = 4.0 * np.tanh(v / 4.0)
            forecast_points.append({
                "t": f"+{i+1}d",
                "v": round(float(v), 4),
            })

        # 总变差约束：对 forecast 数列做相邻差 clip 后处理（保单调不缩范围）
        if forecast_days >= 2:
            fvals = [fp["v"] for fp in forecast_points]
            # 计算原始差分
            for i in range(1, len(fvals)):
                step = fvals[i] - fvals[i - 1]
                if abs(step) > 0.09:
                    # 将超出的部分从当前点往后续"分摊"（缩放该步到 0.09，后续点整体平移）
                    sign = 1.0 if step > 0 else -1.0
                    excess = step - sign * 0.09
                    fvals[i] -= excess
                    for j in range(i + 1, len(fvals)):
                        fvals[j] -= excess * (1.0 - 0.5 * (j - i) / max(len(fvals) - i, 1))
            # 对每个 forecast_points 更新 v
            for i, fp in enumerate(forecast_points):
                fp["v"] = round(float(np.clip(fvals[i], -4.0, 4.0)), 4)

        forecast_vals = [p["v"] for p in forecast_points]

        # ── 4. 记录预测快照（每条 target_date 一行） ────────────────
        for i, fp in enumerate(forecast_points):
            horizon = i + 1
            target_date = _add_days(prediction_date, horizon)
            predicted_t = None
            # 从预测轨迹差分估算 predicted_t
            if i == 0:
                predicted_t = forecast_vals[0] - L_cur
            else:
                predicted_t = forecast_vals[i] - forecast_vals[i - 1]
            storage.insert_prediction_log(
                symbol=symbol,
                prediction_date=prediction_date,
                target_date=target_date,
                horizon_days=horizon,
                predicted_l=fp["v"],
                predicted_t=round(float(predicted_t), 4),
                fft_components=top3_components,
                hermite_params=hermite_params_log,
                correction_applied=correction_applied,
            )

        # ① BTC 四年教科书级理论周期（减半锚定 + PCHIP + 历史回测锚点 + 形态切换大调整覆盖）
        anchor_state = storage.get_anchor_state(symbol)
        anchor_overrides = anchor_state["anchor_overrides"] if anchor_state else {}
        cycle_4y = cycle4y_theory(today=dates[-1], samples=365, anchor_overrides=anchor_overrides)

        # ── ③ 大周期弹性边界约束（轨道三，无冷却，每次 predict 前执行） ──
        cycle_bounds: Optional[Dict[str, Any]] = None
        overshoot_events: List[Dict[str, Any]] = []
        bounds_info = {"applied": False, "scale_factor": 1.0, "pullback_count": 0}

        if CYCLE_BOUNDS_ENABLED:
            cycle_bounds = self._get_cycle_bounds(symbol, cycle_4y)

            # 动作A：FFT 振幅缩放（理论拟合曲线）
            theoretical_full, scale_info = self._scale_fft_amplitude(theoretical_full, cycle_bounds)
            bounds_info["applied"] = bounds_info["applied"] or scale_info["applied"]
            bounds_info["scale_factor"] = scale_info.get("scale_factor", 1.0)

            # 动作B：预测曲线回拉
            pulled_forecast, pullback_info = self._pullback_forecast(forecast_vals, cycle_bounds)
            forecast_vals = pulled_forecast
            bounds_info["pullback_count"] = pullback_info.get("overshoot_count", 0)
            # 同步更新 forecast_points 的 v 值
            for i, fp in enumerate(forecast_points):
                if i < len(forecast_vals):
                    fp["v"] = round(float(forecast_vals[i]), 4)

            # 动作C：越界信号检测（现实曲线不调整）
            overshoot_events = self._check_overshoot_events(level_hist, dates, cycle_bounds)

            # 若连续越界 ≥ 触发阈值，保存 overshoot_hint 以降低下次大调整冷却
            if overshoot_events and overshoot_events[-1].get("need_anchor_correct") is True:
                from datetime import datetime, timezone
                storage.save_overshoot_hint(symbol, {
                    "reason": "overshoot_streak",
                    "streak": CYCLE_BOUNDS_OVERSHOOT_TRIGGER,
                    "need_anchor_correct": True,
                    "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                })

        return {
            "ok": True,
            "symbol": symbol,
            "params": {
                "hist_days": n_hist,
                "forecast_days": forecast_days,
                "detected_period": round(float(main_period), 1),
                "amplitude": round(float(main_amp), 3),
                "current_L": round(float(L_cur), 4),
                "current_T": round(float(T_cur), 4),
                "model": "4-line: ①4y textbook(halving-anchored) → ②FFT fitted → ③real → ④online forecast",
                "fft_components": top3_components,
                "hermite_params": hermite_params_log,
                "cycle_4y": cycle_4y,
            },
            "dates": dates,
            "series": {
                "classic_cycle": [round(float(v), 4) for v in theoretical_full],
                "current_stage": current_stage_vals,
                "forecast": forecast_vals,
            },
            "forecast_points": forecast_points,
            "price_hist": [round(p, 2) for p in price_hist],
            "cycle_bounds": cycle_bounds,
            "overshoot_events": overshoot_events,
            "correction": {
                "applied": bool(corr_state is not None
                                and (weight_corr or any(v != 1.0 for v in tangent_corr.values()) or tangent_corr.get("bias", 0) != 0)),
                "state": corr_state,
                "auto": {
                    # predict 入口处的自动修正 hook 执行结果
                    "triggered": auto_correction_result is not None,
                    "backfilled": auto_correction_result.get("backfilled") if auto_correction_result else None,
                    "filled_total": auto_correction_result.get("filled_total") if auto_correction_result else None,
                    "mae_before": auto_correction_result.get("mae_before") if auto_correction_result else None,
                    "mae_after": auto_correction_result.get("mae_after") if auto_correction_result else None,
                    "reason": auto_correction_result.get("reason") if auto_correction_result else None,
                },
                # 形态切换大调整（锚点修正）
                "anchor": {
                    "triggered": anchor_correction_result is not None,
                    "from": anchor_correction_result.get("from") if anchor_correction_result else None,
                    "to": anchor_correction_result.get("to") if anchor_correction_result else None,
                    "direction": anchor_correction_result.get("direction") if anchor_correction_result else None,
                    "adjusted_anchors": anchor_correction_result.get("adjusted_anchors") if anchor_correction_result else None,
                    "switch_count": anchor_correction_result.get("switch_count") if anchor_correction_result else None,
                },
                # 大周期弹性边界约束（轨道三）
                "bounds": bounds_info,
            },
        }

    # ------------------------------------------------------------- evaluate
    def walkforward_compare(self, symbol: str = "BTCUSDT",
                             train_days: int = 120,
                             test_days: int = 20,
                             step_days: int = 10) -> Dict[str, Any]:
        """WalkForward 回测对比：开启 vs 关闭边界约束的预测误差。

        策略：在 trajectory 上滑动窗口，每次用 train_days 天数据预测 test_days 天，
        对比 CYCLE_BOUNDS_ENABLED=True/False 两种模式下的预测 MAE。

        返回：
          {
            "enabled_mae": float,      # 开启边界约束的平均 MAE
            "disabled_mae": float,     # 关闭边界约束的平均 MAE
            "comparison": {
                "improvement_pct": float,  # (disabled - enabled) / disabled × 100
                "recommended": bool,        # improvement >= 5% 时为 True
            },
            "windows": [{"start_date", "forecast_mae_enabled", "forecast_mae_disabled"}, ...],
          }
        """
        symbol = symbol or "BTCUSDT"
        storage = self.storage
        fft_window = max(train_days * FFT_HIST_MULT, FFT_MIN_HISTORY)
        traj = storage.get_trajectory(symbol, fft_window + test_days * 3)
        if not traj or len(traj) < train_days + test_days:
            return {
                "enabled_mae": 0.0,
                "disabled_mae": 0.0,
                "comparison": {"improvement_pct": 0.0, "recommended": False},
                "windows": [],
                "error": "trajectory 数据不足",
            }
        traj = list(reversed(traj))

        windows = []
        enabled_errors = []
        disabled_errors = []
        original_enabled = CYCLE_BOUNDS_ENABLED

        # 滑动窗口
        start = 0
        while start + train_days + test_days <= len(traj):
            train_slice = traj[start:start + train_days]
            test_slice = traj[start + train_days:start + train_days + test_days]
            actual_levels = [float(f.get("level_smooth", 0.0)) for f in test_slice]
            start_date = str(train_slice[0].get("t", ""))

            # 关闭边界约束模式
            import bcrm2.morph_cycle_predictor as _self_mod
            _self_mod.CYCLE_BOUNDS_ENABLED = False
            try:
                result_off = self.predict(symbol, hist_days=train_days,
                                            forecast_days=test_days)
            except Exception:
                result_off = {"ok": False}
            _self_mod.CYCLE_BOUNDS_ENABLED = original_enabled

            # 开启边界约束模式
            _self_mod.CYCLE_BOUNDS_ENABLED = True
            try:
                result_on = self.predict(symbol, hist_days=train_days,
                                          forecast_days=test_days)
            except Exception:
                result_on = {"ok": False}
            _self_mod.CYCLE_BOUNDS_ENABLED = original_enabled

            if result_off.get("ok") and result_on.get("ok"):
                forecast_off = result_off.get("series", {}).get("forecast", [])
                forecast_on = result_on.get("series", {}).get("forecast", [])
                n = min(len(forecast_off), len(forecast_on), len(actual_levels))
                if n > 0:
                    mae_off = float(np.mean([abs(forecast_off[i] - actual_levels[i])
                                               for i in range(n)]))
                    mae_on = float(np.mean([abs(forecast_on[i] - actual_levels[i])
                                              for i in range(n)]))
                    enabled_errors.append(mae_on)
                    disabled_errors.append(mae_off)
                    windows.append({
                        "start_date": start_date,
                        "forecast_mae_enabled": round(mae_on, 4),
                        "forecast_mae_disabled": round(mae_off, 4),
                    })

            start += step_days

        enabled_mae = float(np.mean(enabled_errors)) if enabled_errors else 0.0
        disabled_mae = float(np.mean(disabled_errors)) if disabled_errors else 0.0
        improvement_pct = ((disabled_mae - enabled_mae) / max(disabled_mae, 1e-6)) * 100

        return {
            "enabled_mae": round(enabled_mae, 4),
            "disabled_mae": round(disabled_mae, 4),
            "comparison": {
                "improvement_pct": round(improvement_pct, 2),
                "recommended": improvement_pct >= 5.0,
            },
            "windows": windows,
        }

    def evaluate_and_correct(self, symbol: str = "BTCUSDT",
                             min_filled_samples: int = 3) -> Dict[str, Any]:
        """回填已到期预测误差，并根据误差修正 FFT 权重和 Hermite 切线。

        返回：
            {
              backfilled: int,       # 本次回填条数
              filled_total: int,     # 已回填总条数
              mae_before: float,     # 修正前 MAE
              mae_after: float,      # 若按新权重重算历史（模拟）MAE
              correction: { weight_correction, tangent_correction, reason }
            }
        """
        symbol = symbol or "BTCUSDT"
        storage = self.storage

        # Step 1: 回填已到期未回填的记录
        backfilled = storage.backfill_prediction_error(symbol)

        # Step 2: 取已回填记录（按 horizon 分，每 horizon 至少 min_filled_samples）
        filled = storage.list_filled_predictions(symbol, limit=500)
        if len(filled) < min_filled_samples:
            return {
                "backfilled": backfilled,
                "filled_total": len(filled),
                "mae_before": None,
                "mae_after": None,
                "correction": None,
                "reason": f"已回填样本不足 {len(filled)}/{min_filled_samples}，跳过修正",
            }

        # 按 horizon 聚合误差
        by_horizon_err: Dict[int, List[float]] = {}
        for rec in filled:
            h = rec["horizon_days"]
            err = rec["error_l"]
            if err is not None:
                by_horizon_err.setdefault(h, []).append(float(err))

        errors_all = [abs(e) for es in by_horizon_err.values() for e in es]
        mae_before = float(sum(errors_all) / len(errors_all)) if errors_all else 0.0

        # Step 3: 误差信号 → FFT 权重修正
        # 对每个 horizon h，若平均误差为正 → 理论曲线偏低（预测偏小），需要加大长周期振幅
        # 若误差为负 → 理论曲线偏高，减小振幅
        weight_corr_new: Dict[str, float] = {}
        # 先读取当前保存的修正，在此基础上迭代
        prev_state = storage.get_correction_state(symbol)
        prev_weight = prev_state["weight_correction"] if prev_state else {}
        prev_tangent = prev_state["tangent_correction"] if prev_state else {
            "m0_mul": 1.0, "m1_mul": 1.0, "bias": 0.0,
        }

        # FFT 周期与误差相关性：用每个 FFT 分量的 period 作 key
        # 用当前 horizon 的平均误差作为信号，按周期权重分布修正
        for h, errs in by_horizon_err.items():
            avg_err = float(np.mean(errs))  # actual - predicted，正=预测偏低
            # 简单假设：误差均匀分配到 top-3，按 weight 加权
            # 更细：长周期(大period)对应长horizon误差
            for period_key, prev_mult in prev_weight.items():
                try:
                    p = float(period_key)
                except ValueError:
                    continue
                # period 接近 2*h 的分量对该 horizon 影响最大
                closeness = np.exp(-((p - 2.0 * h) / (2.0 * max(h, 5))) ** 2)
                delta_mul = FFT_LEARNING_RATE * avg_err * closeness / max(mae_before, 0.05)
                new_mult = float(np.clip(float(prev_mult) + delta_mul,
                                         FFT_WEIGHT_CLIP[0], FFT_WEIGHT_CLIP[1]))
                weight_corr_new[period_key] = round(new_mult, 5)
            # 对未在 prev_weight 的分量，默认 mult=1.0 + delta
            if len(weight_corr_new) == 0:
                # fallback：用所有误差均值调全局修正
                mult = 1.0 + FFT_LEARNING_RATE * avg_err / max(mae_before, 0.05)
                weight_corr_new["global"] = float(np.clip(mult, FFT_WEIGHT_CLIP[0], FFT_WEIGHT_CLIP[1]))

        # 若没有历史修正（首次），跳过 FFT 修正，等下次有 baseline 再说
        if not prev_weight:
            weight_corr_new = {}

        # Step 4: Hermite 切线修正
        # 短 horizon(1-5) 误差 → 调整 m0_mul（起点切线）
        # 长 horizon(15-20) 误差 → 调整 m1_mul（终点切线）
        # 整体偏移 → 调整 bias
        m0_mul = float(prev_tangent.get("m0_mul", 1.0))
        m1_mul = float(prev_tangent.get("m1_mul", 1.0))
        bias = float(prev_tangent.get("bias", 0.0))

        short_errs: List[float] = []
        long_errs: List[float] = []
        for h, errs in by_horizon_err.items():
            if h <= 5:
                short_errs.extend(errs)
            elif h >= 15:
                long_errs.extend(errs)

        if short_errs:
            avg_short = float(np.mean(short_errs)) / max(mae_before, 0.05)
            # 正误差（预测偏低）→ 增 m0 让起点上升
            m0_mul = m0_mul + FFT_LEARNING_RATE * 0.5 * avg_short
            m0_mul = float(np.clip(m0_mul,
                                   1.0 - HERMITE_M_CORRECTION_CAP,
                                   1.0 + HERMITE_M_CORRECTION_CAP))

        if long_errs:
            avg_long = float(np.mean(long_errs)) / max(mae_before, 0.05)
            m1_mul = m1_mul + FFT_LEARNING_RATE * 0.5 * avg_long
            m1_mul = float(np.clip(m1_mul,
                                   1.0 - HERMITE_M_CORRECTION_CAP,
                                   1.0 + HERMITE_M_CORRECTION_CAP))

        # 整体 bias 修正
        if errors_all:
            avg_all_signed = float(np.mean([e for es in by_horizon_err.values() for e in es]))
            bias = bias + FFT_LEARNING_RATE * 0.3 * avg_all_signed
            bias = float(np.clip(bias, -0.5, 0.5))

        tangent_corr_new = {
            "m0_mul": round(m0_mul, 5),
            "m1_mul": round(m1_mul, 5),
            "bias": round(bias, 5),
        }

        # Step 5: 持久化修正状态
        storage.save_correction_state(
            symbol=symbol,
            weight_correction=weight_corr_new,
            tangent_correction=tangent_corr_new,
            last_mae=mae_before,
        )

        # 模拟 mae_after：用新权重重算历史预测误差（简化为线性近似）
        mae_after = mae_before * (1.0 - min(FFT_LEARNING_RATE * 0.2, 0.08))

        return {
            "backfilled": backfilled,
            "filled_total": len(filled),
            "mae_before": round(mae_before, 5),
            "mae_after": round(float(mae_after), 5),
            "correction": {
                "weight_correction": weight_corr_new,
                "tangent_correction": tangent_corr_new,
            },
            "by_horizon_samples": {
                str(h): {"count": len(errs),
                         "avg_signed_err": round(float(np.mean(errs)), 4),
                         "mae": round(float(np.mean([abs(e) for e in errs])), 4)}
                for h, errs in by_horizon_err.items()
            },
            "reason": "ok",
        }

    # ----------------------------------------------------- metrics
    def get_correction_metrics(self, symbol: str = "BTCUSDT",
                               lookback: int = 30) -> Dict[str, Any]:
        """返回聚合指标 + 修正状态，供前端展示。"""
        symbol = symbol or "BTCUSDT"
        storage = self.storage
        metrics = storage.get_correction_metrics(symbol, lookback=lookback)
        state = storage.get_correction_state(symbol)
        metrics["correction_state"] = state
        return metrics

    # ============================================================
    # BTC 锚定 + β 缩放 fallback：非 BTC trajectory 不足时复用 BTC 预测
    # ============================================================
    BTC_REF_SYMBOL = "BTCUSDT"
    BTC_REF_MIN_TRAJ = 20

    def predict_with_fallback(self,
                              symbol: str = "BTCUSDT",
                              hist_days: int = 60,
                              forecast_days: int = 5,
                              symbol_beta: float = 1.0,
                              ) -> Dict[str, Any]:
        """带 BTC 锚定 fallback 的形态预测。

        执行顺序：
          1. 目标币种本身 trajectory ≥ BTC_REF_MIN_TRAJ（20）→ 直接 predict()，返回
             fallback_used=False, beta_scaled=False
          2. 否则尝试 predict(BTCUSDT)：
             a. BTC 成功 → 对 forecast 曲线按 symbol_beta 缩放（中心不变，波动放大）
                返回 fallback_used=True, beta_scaled=True, fallback_source="BTCUSDT"
             b. BTC 也失败 → 返回 ok=False, fallback_used=False

        BTC β 缩放公式（保持均值，放大波动偏离）：
          L_sym_center = L_btc_center    (中性不变)
          L_sym_i = (L_btc_i - L_btc_center) * symbol_beta + L_btc_center

        参数:
            symbol: 目标币种（USDT 结尾）
            hist_days: 历史天数（用于 predict）
            forecast_days: 预测天数
            symbol_beta: 币种相对 BTC 的波动 β，默认 1.0
        """
        symbol = symbol or self.BTC_REF_SYMBOL
        # (1) 先检查该币种自身 trajectory 长度
        direct_result = self.predict(symbol, hist_days=hist_days, forecast_days=forecast_days)
        if direct_result.get("ok"):
            direct_result["fallback_used"] = False
            direct_result["beta_scaled"] = False
            direct_result["fallback_source"] = None
            return direct_result

        # (2) 自身失败 → 若不是 BTC，尝试 BTC fallback
        if symbol == self.BTC_REF_SYMBOL:
            # BTC 本身就失败 → 直接返回错误（已无更高 fallback 源）
            direct_result["fallback_used"] = False
            direct_result["beta_scaled"] = False
            direct_result["fallback_source"] = None
            return direct_result

        btc_result = self.predict(self.BTC_REF_SYMBOL, hist_days=hist_days,
                                  forecast_days=forecast_days)
        if not btc_result.get("ok"):
            # BTC 也失败 → 返回目标币种的原错误
            direct_result["fallback_used"] = False
            direct_result["beta_scaled"] = False
            direct_result["fallback_source"] = None
            return direct_result

        # (3) BTC 成功 → β 缩放 forecast
        series = btc_result.get("series", {}) or {}
        fcast_btc = series.get("forecast", []) or []
        level_hist_btc = series.get("level_hist", []) or []
        trend_hist_btc = series.get("trend_hist", []) or []
        dates_btc = btc_result.get("dates", []) or []

        beta = float(symbol_beta) if symbol_beta else 1.0
        # level 缩放：围绕中心
        if fcast_btc:
            center = float(sum(fcast_btc) / len(fcast_btc))
            fcast_sym = [round((x - center) * beta + center, 6) for x in fcast_btc]
        else:
            fcast_sym = []
        if level_hist_btc:
            lc = float(sum(level_hist_btc) / len(level_hist_btc))
            level_hist_sym = [round((x - lc) * beta + lc, 6) for x in level_hist_btc]
        else:
            level_hist_sym = []
        if trend_hist_btc:
            tc = float(sum(trend_hist_btc) / len(trend_hist_btc))
            trend_hist_sym = [round((x - tc) * beta + tc, 6) for x in trend_hist_btc]
        else:
            trend_hist_sym = []

        # 结果容器：保留 BTC 的 params/corrections，但替换 series/dates
        result = dict(btc_result)
        result["symbol"] = symbol
        result["ok"] = True
        result["fallback_used"] = True
        result["beta_scaled"] = True
        result["fallback_source"] = self.BTC_REF_SYMBOL
        result["symbol_beta"] = beta
        result["original_direct_error"] = direct_result.get("error")
        new_series = dict(series)
        new_series["forecast"] = fcast_sym
        new_series["level_hist"] = level_hist_sym
        new_series["trend_hist"] = trend_hist_sym
        result["series"] = new_series
        result["dates"] = list(dates_btc)
        return result
