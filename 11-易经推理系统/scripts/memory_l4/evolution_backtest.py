#!/usr/bin/env python3
"""
evolution_backtest.py — PROP-20260809-001: 提案级 Walk-Forward 真实回测验证

为 self_evolution_engine._backtest_and_adopt 提供真实的回测验证能力：
  - 数据源: 本地 klines CSV（scripts/data/klines/{SYMBOL}_{TF}.csv），不依赖外网
  - 双引擎对比: baseline=BCRMEngine(当前参数) vs proposed=BCRMEngine(提案参数)
  - 采纳条件: proposed 方向准确率 >= baseline - 容忍带（默认 0.02）

设计要点（Z3 规划）:
  1. 影子参数（无引擎消费点）: 单引擎跑一次，affected_engine=False，
     validated=True（行为不变，诚实记录，不浪费双引擎算力）
  2. 数据不足（bars < min_bars）: 降级 rule_check + degraded=True（保持原行为）
  3. snapshot 构造: price_change_pct/ch4h/rsi/ema20/ema50/volume_ratio
     （market_preprocessor.normalize 契约，Z1 探测确认）
  4. predict_fn 契约: (bar, train_data) → BCRMOutput；
     contradiction_list 由引擎 _auto_generate_contradictions 产生
     （Guardrail 要求非空矛盾列表，Z1 探测确认）

依赖:
  - scripts/memory_l4/bcrm/walk_forward.py (WalkForwardEngine)
  - scripts/memory_l4/bcrm/engine.py (BCRMEngine, @dataclass 可参数注入)
  - scripts/data/klines/*.csv (本地缓存，8 币种×多周期)
"""
import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 路径与常量 ────────────────────────────────────────────────────────────────

_THIS_DIR = Path(__file__).resolve().parent          # scripts/memory_l4
KLINE_DIR = _THIS_DIR.parent / "data" / "klines"     # scripts/data/klines

# 提案 param_key → BCRMEngine 实例字段 的映射
# Z1 扫描结论: 仅 min_confidence_threshold 有真实引擎消费点（dataclass 字段）；
# 其余白名单参数为影子参数（全仓库无消费点），不做双引擎对比。
_PARAM_TO_ENGINE_FIELD = {
    "min_confidence_threshold": "min_confidence_threshold",
}

# 引擎字段合法值域（越界提案直接拒绝，不进回测）
_ENGINE_FIELD_BOUNDS = {
    "min_confidence_threshold": (0.01, 0.95),
}

# Walk-Forward 窗口参数（Z3 规划: 控成本，~250 infer/引擎）
DEFAULT_TRAIN_WINDOW = 50
DEFAULT_TEST_WINDOW  = 10
DEFAULT_STEP         = 20

# 验证容忍带: proposed 准确率不低于 baseline - ACCURACY_TOLERANCE 即采纳
ACCURACY_TOLERANCE = 0.02

# 降级阈值: bars 少于此数不做真实回测（样本无统计意义）
MIN_BARS_FOR_BACKTEST = 60


# ── K线加载与 snapshot 构造 ──────────────────────────────────────────────────

def load_local_bars(symbol: str = "BTC",
                    timeframe: str = "1H",
                    max_bars: int = 300) -> List[Dict[str, Any]]:
    """
    从本地 CSV 加载 K 线 bars。

    Returns:
        bar 列表，每项含 timestamp/open/high/low/close/volume（float）。
        文件不存在或解析失败返回 []（调用方负责降级）。
    """
    csv_path = KLINE_DIR / f"{symbol}_{timeframe}.csv"
    if not csv_path.exists():
        logger.warning("本地K线不存在: %s", csv_path)
        return []

    bars: List[Dict[str, Any]] = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    bars.append({
                        "timestamp": row["timestamp"],
                        "ts": row["timestamp"],  # 别名（下游兼容）
                        "open":   float(row["open"]),
                        "high":   float(row["high"]),
                        "low":    float(row["low"]),
                        "close":  float(row["close"]),
                        "volume": float(row["volume"]),
                    })
                except (KeyError, ValueError, TypeError):
                    continue  # 跳过坏行
    except OSError as e:
        logger.warning("K线读取失败 %s: %s", csv_path, e)
        return []

    # 取最近 max_bars 根（保留时间顺序）
    return bars[-max_bars:] if max_bars and len(bars) > max_bars else bars


def _rsi(closes: List[float], period: int = 14) -> float:
    """简易 RSI（Wilder 近似的均值版），用于 snapshot 构造。"""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def build_snapshot(bars: List[Dict[str, Any]], idx: int) -> Dict[str, Any]:
    """
    从 bars 序列的第 idx 根构造 market_snapshot。

    字段契约来自 bcrm/market_preprocessor.normalize（Z1 扫描确认）：
      price_change_pct(24bar涨跌%) / ch4h / rsi / ema20 / ema50 / volume_ratio
    funding_rate/fgi/oi_change_pct 本地无数据源 → 缺省中性值（baseline 与
    proposed 两侧相同，不影响相对比较）。

    Requires: idx >= 51（需要 50 根历史算 EMA50/24h 动量）。
    """
    closes = [b["close"] for b in bars[max(0, idx - 50): idx + 1]]
    vols   = [b["volume"] for b in bars[max(0, idx - 19): idx + 1]]

    ch24 = (closes[-1] / closes[-25] - 1.0) * 100.0 if len(closes) >= 25 else 0.0
    ch4h = (closes[-1] / closes[-5]  - 1.0) * 100.0 if len(closes) >= 5  else 0.0
    ema20 = sum(closes[-20:]) / min(len(closes), 20)
    ema50 = sum(closes[-50:]) / min(len(closes), 50)

    # 量比: 当前量 / 前19根均量
    vol_ratio = 1.0
    if len(vols) >= 20:
        avg_prev = sum(vols[:-1]) / (len(vols) - 1)
        vol_ratio = vols[-1] / avg_prev if avg_prev > 0 else 1.0

    # RSI 用 50 根窗口内的数据
    rsi = _rsi(closes)
    # 防 RSI 极端值主导: 夹到 [5, 95]
    rsi = max(5.0, min(95.0, rsi))

    return {
        "price":  closes[-1],
        "close":  closes[-1],
        "open":   bars[idx]["open"],
        "high":   bars[idx]["high"],
        "low":    bars[idx]["low"],
        "volume": bars[idx]["volume"],
        "price_change_pct": ch24,
        "ch4h": ch4h,
        "rsi": rsi,
        "ema20": ema20,
        "ema50": ema50,
        "volume_ratio": vol_ratio,
    }


def bars_to_walk_forward_data(bars: List[Dict[str, Any]],
                              warmup: int = 51) -> List[Dict[str, Any]]:
    """
    把原始 bars 转为 WalkForwardEngine.run 所需的 snapshot 序列。

    每根 bar 附带 snapshot 特征（predict_fn 直接使用 bar 本身作为
    market_snapshot 输入）。保留 close/price 供正确性判定
    （walk_forward.default_direction_label 用 close→next close 实际涨跌）。
    """
    data = []
    for idx in range(warmup, len(bars)):
        snap = build_snapshot(bars, idx)
        snap["timestamp"] = bars[idx]["timestamp"]
        snap["regime"] = ""  # walk_forward 记录用，缺省空
        data.append(snap)
    return data


# ── Walk-Forward 双引擎对比 ──────────────────────────────────────────────────

def _make_predict_fn(engine):
    """构造 WalkForwardEngine 所需的 predict_fn。"""
    from scripts.memory_l4.bcrm.market_preprocessor import normalize_snapshot

    def predict_fn(bar: Dict[str, Any], train_data: List[Dict]) -> Any:
        # Guardrail 要求非空矛盾列表 → 用引擎自带的自动推导（Y1 修复逻辑）
        try:
            norm = normalize_snapshot(dict(bar))
            contras = engine._auto_generate_contradictions(norm)
        except Exception:
            contras = None
        return engine.infer(market_snapshot=dict(bar),
                            contradiction_list=contras)
    return predict_fn


def _run_walk_forward(engine, data: List[Dict[str, Any]],
                      train_window: int, test_window: int,
                      step: int) -> Dict[str, Any]:
    """单引擎 walk-forward，返回摘要指标。"""
    from scripts.memory_l4.bcrm.walk_forward import WalkForwardEngine
    wfe = WalkForwardEngine(_make_predict_fn(engine))
    result = wfe.run(data,
                     train_window_size=train_window,
                     test_window_size=test_window,
                     step_size=step)
    return {
        "total_bars": result.total_bars,
        "correct_predictions": result.correct_predictions,
        "wrong_predictions": result.wrong_predictions,
        "direction_accuracy": round(result.direction_accuracy, 4),
        "avg_confidence": round(result.avg_confidence, 4),
        "fail_closed_count": result.fail_closed_count,
        "windows": len(result.per_window_results),
    }


def walk_forward_validate(param_key: str,
                          proposed_value: Any,
                          symbol: str = "BTC",
                          timeframe: str = "1H",
                          max_bars: int = 300,
                          min_bars: int = MIN_BARS_FOR_BACKTEST,
                          accuracy_tolerance: float = ACCURACY_TOLERANCE
                          ) -> Dict[str, Any]:
    """
    提案级 Walk-Forward 真实回测验证（PROP-20260809-001 核心）。

    流程:
      1. 加载本地 bars；不足 min_bars → 降级 rule_check（degraded=True）
      2. 影子参数（param_key 不在 _PARAM_TO_ENGINE_FIELD）→ 单引擎跑一次，
         affected_engine=False, validated=True（提案不影响引擎行为）
      3. 引擎参数 → 双引擎对比:
         baseline = BCRMEngine()（默认/当前参数）
         proposed = BCRMEngine(**{field: proposed_value})
         采纳: proposed.direction_accuracy >= baseline - tolerance

    Args:
        param_key: 提案参数名（self_evolution_engine 白名单内）
        proposed_value: 提案值
        symbol/timeframe: 本地 K 线选择
        max_bars: 最大 bar 数（控成本）
        min_bars: 低于此数降级
        accuracy_tolerance: 准确率容忍带

    Returns:
        backtest_result dict（供 _backtest_and_adopt 记录与判定）
    """
    from scripts.memory_l4.bcrm.engine import BCRMEngine

    # ── 1. 数据加载 ────────────────────────────────────────────────────────
    bars = load_local_bars(symbol, timeframe, max_bars)
    if len(bars) < min_bars:
        logger.warning("回测降级: bars=%d < min_bars=%d (%s_%s)",
                       len(bars), min_bars, symbol, timeframe)
        return {
            "validated": True,
            "method": "rule_check",
            "degraded": True,
            "reason": f"insufficient_bars({len(bars)}<{min_bars})",
            "param_key": param_key,
            "proposed_value": proposed_value,
        }

    data = bars_to_walk_forward_data(bars)
    if len(data) < DEFAULT_TRAIN_WINDOW + DEFAULT_TEST_WINDOW:
        return {
            "validated": True,
            "method": "rule_check",
            "degraded": True,
            "reason": f"insufficient_wf_data({len(data)})",
            "param_key": param_key,
            "proposed_value": proposed_value,
        }

    # 窗口自适应（小样本时收缩）
    train_w = min(DEFAULT_TRAIN_WINDOW, max(20, len(data) // 3))
    test_w  = min(DEFAULT_TEST_WINDOW, max(5, len(data) // 6))
    step    = DEFAULT_STEP

    # ── 2. 影子参数: 单引擎记录，行为不变 ─────────────────────────────────
    engine_field = _PARAM_TO_ENGINE_FIELD.get(param_key)

    # ── 2.5 引擎参数合法性校验（拒绝明显非法值）─────────────────────────
    if engine_field is not None:
        try:
            v = float(proposed_value)
        except (TypeError, ValueError):
            return {
                "validated": False,
                "method": "walk_forward",
                "reason": "invalid_value",
                "param_key": param_key,
                "proposed_value": proposed_value,
            }
        lo, hi = _ENGINE_FIELD_BOUNDS.get(engine_field, (0.0, float("inf")))
        if not (lo <= v <= hi):
            return {
                "validated": False,
                "method": "walk_forward",
                "reason": f"invalid_value(out_of_bounds[{lo},{hi}])",
                "param_key": param_key,
                "proposed_value": proposed_value,
            }

    if engine_field is None:
        baseline_summary = _run_walk_forward(
            BCRMEngine(), data, train_w, test_w, step)
        return {
            "validated": True,
            "method": "walk_forward",
            "affected_engine": False,
            "reason": "shadow_param_no_engine_consumer",
            "param_key": param_key,
            "proposed_value": proposed_value,
            "baseline": baseline_summary,
        }

    # ── 3. 引擎参数: 双引擎对比 ────────────────────────────────────────────
    try:
        baseline_engine = BCRMEngine()
        proposed_engine = BCRMEngine(**{engine_field: proposed_value})
    except Exception as e:
        logger.warning("提案引擎构造失败 %s=%r: %s", param_key, proposed_value, e)
        # W2修复(E2审查): 引擎都构造不出来的提案值 → 拒绝，不自动采纳
        return {
            "validated": False,
            "method": "walk_forward",
            "reason": f"engine_construct_failed: {e}",
            "param_key": param_key,
            "proposed_value": proposed_value,
        }

    baseline_summary = _run_walk_forward(baseline_engine, data, train_w, test_w, step)
    proposed_summary = _run_walk_forward(proposed_engine, data, train_w, test_w, step)

    base_acc = baseline_summary["direction_accuracy"]
    prop_acc = proposed_summary["direction_accuracy"]
    delta_acc = round(prop_acc - base_acc, 4)

    # S1修复(E2审查): 覆盖率门禁，防"交白卷=准确率提升"的幸存者偏差。
    # min_confidence_threshold 直接控制 fail_closed 硬门槛，仅看准确率会
    # 奖励"把没把握的预测全部丢弃"的提案。
    base_fail = baseline_summary["fail_closed_count"]
    prop_fail = proposed_summary["fail_closed_count"]
    fail_limit = base_fail * 1.2 + 5          # 容忍带: 相对+20% 绝对+5
    coverage_ok = prop_fail <= fail_limit
    accuracy_ok = prop_acc >= base_acc - accuracy_tolerance
    validated = accuracy_ok and coverage_ok

    return {
        "validated": validated,
        "method": "walk_forward",
        "affected_engine": True,
        "param_key": param_key,
        "proposed_value": proposed_value,
        "baseline": baseline_summary,
        "proposed": proposed_summary,
        "delta": {
            "direction_accuracy": delta_acc,
            "avg_confidence": round(
                proposed_summary["avg_confidence"]
                - baseline_summary["avg_confidence"], 4),
            "fail_closed": prop_fail - base_fail,
        },
        "tolerance": accuracy_tolerance,
        "fail_limit": fail_limit,
        "gate_detail": {
            "accuracy_ok": accuracy_ok,
            "coverage_ok": coverage_ok,
        },
        "data": {"symbol": symbol, "timeframe": timeframe, "bars": len(data)},
    }
