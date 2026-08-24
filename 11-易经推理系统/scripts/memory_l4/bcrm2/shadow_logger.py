"""ShadowLogger —— Phase B 影子模式：记录 reactive vs forecast 参数差异。

Spec: 2026-08-19-morph-cycle-dynamic-correction-design.md §四 Phase B

核心能力：
  1. record_polling() —— 每轮询周期记录 reactive/forecast/actual 三组参数
  2. get_comparison_report() —— 聚合 N 天参数差异统计，供评估报告
  3. _compute_forecast_params() —— 调用 MorphCyclePredictor 预测 L_forecast

设计原则：
  • SHADOW_LOGGER_ENABLED 默认 False，保持 CLI 字节等价
  • 只记录，不改变任何交易参数
  • 异常被调用方 catch，不影响主流程
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from .storage import EvolutionStorageSQLite


# ── Phase B ShadowLogger 超参 ────────────────────────────────────
SHADOW_LOGGER_ENABLED = True           # 总开关（已开启，验证前置层参数差异）
SHADOW_FORECAST_DAYS = 5               # forecast 天数（用预测的第 5 天值）
SHADOW_FORECAST_CACHE_TTL = 3600       # forecast 缓存 TTL（秒），同 symbol 1h 内复用
SHADOW_SECTOR_BETAS_DEFAULT = {        # 默认 identity betas（Phase B 不依赖真实 betas）
    "defi": (1.0, 0.0, 0.5),
    "ai": (1.0, 0.0, 0.5),
    "rwa": (1.0, 0.0, 0.5),
    "meme": (1.0, 0.0, 0.5),
    "l2": (1.0, 0.0, 0.5),
}


class ShadowLogger:
    """Phase B 影子模式：记录 reactive vs forecast 参数差异，不改变交易。

    用法：
        logger = ShadowLogger(storage, predictor, mapper)
        logger.record_polling("BTC", inference, actual_params)
        report = logger.get_comparison_report("BTC", days=7)
    """

    def __init__(self, storage: EvolutionStorageSQLite,
                 morph_predictor: Any,
                 param_mapper: Any):
        self.storage = storage
        self.predictor = morph_predictor
        self.mapper = param_mapper
        # forecast 缓存：symbol → (timestamp_sec, forecast_params)
        self._forecast_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def record_polling(self, symbol: str, inference: Dict[str, Any],
                       actual_params: Dict[str, Any],
                       enable_inject: bool = False,
                       alpha_blend: float = 0.0,
                       fma_on_allowed: bool = None,
                       fma_on_eff_threshold: float = None,
                       fd_crypto_war_state: str = None,
                       fd_crypto_total_score: float = None,
                       fd_crypto_cap_mode: float = None,
                       fd_crypto_mult_mode: float = None,
                       fd_us_stock_war_state: str = None,
                       fd_us_stock_total_score: float = None,
                       sal_type: str = None,
                       sal_regime: str = None,
                       sal_calib_median: float = None,
                       sal_calib_min: float = None,
                       sal_calib_max: float = None,
                       sal_gate: int = None,
                       ) -> Optional[int]:
        """记录一次轮询的参数对比快照（三值：baseline / ai_injected / effective）。

        baseline = 静态基线（v15 regime 查表，完全不注入）
        ai_injected = AI 注入下的理论值（enable_inject=True, forecast+形态）
        effective = 当前实际使用的值（由调用方 actual_params + 当前开关决定）

        参数:
            symbol: 币种（如 "BTC"）
            inference: BCRM 2.0 推理结果 dict（含 snapshot, _regime_multipliers 等）
            actual_params: 实际交易参数（direction, confidence, position_usdt, tp_px, sl_px, threshold）
            enable_inject: 当前 polling_trader 是否开启 AI 注入（T4 融合层开关）
            alpha_blend: 当前 α blend 值
        """
        if not SHADOW_LOGGER_ENABLED:
            return None

        # 1. 提取 reactive 参数
        snapshot = inference.get("snapshot", {}) or {}
        reactive_L = float(snapshot.get("level_smooth", 0.0))
        reactive_T = float(snapshot.get("trend_smooth", 0.0))
        reactive_C = float(snapshot.get("consensus", 0.0))
        reactive_regime = inference.get("_regime_pred") or snapshot.get("regime")
        reg_mult = dict(inference.get("_regime_multipliers", {}) or {})
        regime_baselines = dict(inference.get("_regime_baselines", {}) or {})
        symbol_sector = inference.get("sector") or snapshot.get("sector")
        stats_row = inference.get("stats_row") or snapshot.get("stats_row") or {}

        # 2. 计算 forecast 参数（带缓存）
        forecast_params = self._compute_forecast_params(symbol, reactive_C)

        # 3. 计算三值：baseline / ai_injected / effective
        # baseline: regime_baselines × regime_multipliers 查表
        baseline_pos = float(reg_mult.get("position_mult", 1.0))
        baseline_tp = float(reg_mult.get("tp_mult", 1.0))
        baseline_sl = float(reg_mult.get("sl_mult", 1.0))
        baseline_thr_mult = float(reg_mult.get("threshold_mult", 1.0))

        # ai_injected：调用 mapper 的融合层，强制 enable_inject=True
        try:
            ranges_parsed: Dict[str, Any] = {}
            try:
                if isinstance(forecast_params.get("global_ranges"), str):
                    ranges_parsed = json.loads(forecast_params["global_ranges"])
                else:
                    ranges_parsed = forecast_params.get("global_ranges") or {}
            except (json.JSONDecodeError, TypeError):
                ranges_parsed = {}
            sect_w_parsed = forecast_params.get("sector_weights")
            if isinstance(sect_w_parsed, str):
                try:
                    sect_w_parsed = json.loads(sect_w_parsed)
                except (json.JSONDecodeError, TypeError):
                    sect_w_parsed = {}
            sect_w_parsed = sect_w_parsed or {}

            if (self.mapper is not None
                    and hasattr(self.mapper, "_resolve_effective_params")
                    and stats_row and regime_baselines):
                # 先自己算一份中性 sector_weights 兜底（forecast 的）
                def _neutral_sector_weights():
                    return {"weights": {s: 0.2 for s in ["defi", "ai", "rwa", "meme", "l2"]},
                            "sector_tp_mult": {s: 1.0 for s in ["defi", "ai", "rwa", "meme", "l2"]},
                            "sector_sl_mult": {s: 1.0 for s in ["defi", "ai", "rwa", "meme", "l2"]}}

                sw_use = sect_w_parsed if (isinstance(sect_w_parsed, dict)
                                           and "weights" in sect_w_parsed
                                           and "sector_tp_mult" in sect_w_parsed) else _neutral_sector_weights()
                base_long = inference.get("base_long_threshold") or 0.7955
                base_short = inference.get("base_short_threshold") or 0.7955
                ai_params = self.mapper._resolve_effective_params(
                    ranges=ranges_parsed,
                    stats_row=stats_row,
                    forecast_L=forecast_params.get("L"),
                    forecast_T=forecast_params.get("T"),
                    alpha_blend=float(alpha_blend or 0.0),
                    regime_baselines=regime_baselines,
                    sector_weights_result=sw_use,
                    symbol_sector=symbol_sector,
                    regime_multipliers=reg_mult,
                    enable_inject=True,
                    base_long_threshold=base_long,
                    base_short_threshold=base_short,
                )
            else:
                ai_params = {
                    "position_mult_final": baseline_pos,
                    "tp_mult_final": baseline_tp,
                    "sl_mult_final": baseline_sl,
                    "threshold_mult_final": baseline_thr_mult,
                    "long_conf_threshold": None,
                    "short_conf_threshold": None,
                    "ls_ratio_cap": regime_baselines.get("ls_ratio_cap"),
                }
        except Exception as _e:
            ai_params = {
                "position_mult_final": baseline_pos,
                "tp_mult_final": baseline_tp,
                "sl_mult_final": baseline_sl,
                "threshold_mult_final": baseline_thr_mult,
                "long_conf_threshold": None,
                "short_conf_threshold": None,
                "ls_ratio_cap": None,
                "_inject_error": str(_e),
            }

        # effective: 如果调用方 enable_inject=True，使用 ai_params；否则用 baseline
        eff_pos_mult = ai_params["position_mult_final"] if enable_inject else baseline_pos
        eff_tp_mult = ai_params["tp_mult_final"] if enable_inject else baseline_tp
        eff_sl_mult = ai_params["sl_mult_final"] if enable_inject else baseline_sl
        eff_thr_mult = ai_params["threshold_mult_final"] if enable_inject else baseline_thr_mult

        # 4. 组装记录
        record = {
            # reactive
            "reactive_L": reactive_L,
            "reactive_T": reactive_T,
            "reactive_C": reactive_C,
            "reactive_regime": reactive_regime,
            "reactive_pos_mult": reg_mult.get("position_mult", 1.0),
            "reactive_tp_mult": reg_mult.get("tp_mult", 1.0),
            "reactive_sl_mult": reg_mult.get("sl_mult", 1.0),
            "reactive_threshold": reg_mult.get("threshold_mult", 1.0),
            # forecast
            "forecast_L": forecast_params["L"],
            "forecast_T": forecast_params["T"],
            "forecast_global_ranges": forecast_params["global_ranges"],
            "forecast_sector_weights": forecast_params["sector_weights"],
            # 三值：baseline（静态基线= v15 查表）
            "baseline_pos_mult": baseline_pos,
            "baseline_tp_mult": baseline_tp,
            "baseline_sl_mult": baseline_sl,
            "baseline_threshold_mult": baseline_thr_mult,
            # 三值：ai_injected（AI 注入=理论值，恒以 enable_inject=True 计算）
            "ai_pos_mult": ai_params.get("position_mult_final"),
            "ai_tp_mult": ai_params.get("tp_mult_final"),
            "ai_sl_mult": ai_params.get("sl_mult_final"),
            "ai_threshold_mult": ai_params.get("threshold_mult_final"),
            "ai_long_threshold": ai_params.get("long_conf_threshold"),
            "ai_short_threshold": ai_params.get("short_conf_threshold"),
            "ai_ls_ratio_cap": ai_params.get("ls_ratio_cap"),
            # 三值：effective（当前系统实际使用的值）
            "effective_pos_mult": eff_pos_mult,
            "effective_tp_mult": eff_tp_mult,
            "effective_sl_mult": eff_sl_mult,
            "effective_threshold_mult": eff_thr_mult,
            "enable_inject": bool(enable_inject),
            "alpha_blend": round(float(alpha_blend or 0.0), 4),
            # 实际交易结果
            "actual_direction": actual_params.get("direction"),
            "actual_confidence": actual_params.get("confidence"),
            "actual_position_usdt": actual_params.get("position_usdt"),
            "actual_tp_px": actual_params.get("tp_px"),
            "actual_sl_px": actual_params.get("sl_px"),
            "actual_threshold": actual_params.get("threshold"),
            # H3-FMA 渐进：FMA=ON 影子决策（即便当前 FMA=False 也记录，用于评估开启与否）
            "fma_on_allowed": fma_on_allowed,
            "fma_on_eff_threshold": fma_on_eff_threshold,
            # T5 战略层聚合影子（6字段）
            "fd_crypto_war_state": fd_crypto_war_state,
            "fd_crypto_total_score": fd_crypto_total_score,
            "fd_crypto_cap_mode": fd_crypto_cap_mode,
            "fd_crypto_mult_mode": fd_crypto_mult_mode,
            "fd_us_stock_war_state": fd_us_stock_war_state,
            "fd_us_stock_total_score": fd_us_stock_total_score,
            # T5 策略算法层影子（6字段）
            "sal_type": sal_type,
            "sal_regime": sal_regime,
            "sal_calib_median": sal_calib_median,
            "sal_calib_min": sal_calib_min,
            "sal_calib_max": sal_calib_max,
            "sal_gate": sal_gate,
        }

        # 5. 存储
        return self.storage.save_shadow_log(symbol, record)

    def get_comparison_report(self, symbol: str, days: int = 7) -> Dict[str, Any]:
        """生成 N 天的参数差异报告。

        返回:
            {
                "symbol": "BTC",
                "days": 7,
                "total_records": 168,
                "param_diff_stats": {
                    "L": {"mean_diff": ..., "std_diff": ..., "max_diff": ...},
                    "T": {...},
                },
                "would_change_decision": {
                    "direction_changes": int,
                    "threshold_changes": int,
                    "position_changes": int,
                },
                "direction_consistency": float,
                "regime_distribution": {regime_name: count, ...},
            }
        """
        records = self.storage.get_shadow_log(symbol, days)
        total = len(records)

        # 空记录兜底
        if total == 0:
            return {
                "symbol": symbol,
                "days": days,
                "total_records": 0,
                "param_diff_stats": {
                    "L": {"mean_diff": 0.0, "std_diff": 0.0, "max_diff": 0.0},
                    "T": {"mean_diff": 0.0, "std_diff": 0.0, "max_diff": 0.0},
                },
                "would_change_decision": {
                    "direction_changes": 0,
                    "threshold_changes": 0,
                    "position_changes": 0,
                },
                "direction_consistency": 0.0,
                "regime_distribution": {},
            }

        # 1. param_diff_stats: L 和 T 的差异统计
        L_diffs: List[float] = []
        T_diffs: List[float] = []
        for r in records:
            rL = float(r.get("reactive_L") or 0.0)
            fL = float(r.get("forecast_L") or 0.0)
            rT = float(r.get("reactive_T") or 0.0)
            fT = float(r.get("forecast_T") or 0.0)
            L_diffs.append(fL - rL)
            T_diffs.append(fT - rT)

        def _stats(diffs: List[float]) -> Dict[str, float]:
            n = len(diffs)
            if n == 0:
                return {"mean_diff": 0.0, "std_diff": 0.0, "max_diff": 0.0}
            mean = sum(diffs) / n
            var = sum((d - mean) ** 2 for d in diffs) / n
            std = var ** 0.5
            return {
                "mean_diff": round(mean, 4),
                "std_diff": round(std, 4),
                "max_diff": round(max(abs(d) for d in diffs), 4),
            }

        param_diff_stats = {"L": _stats(L_diffs), "T": _stats(T_diffs)}

        # 2. would_change_decision: forecast 参数是否会导致不同决策
        direction_changes = 0
        threshold_changes = 0
        position_changes = 0
        same_direction_count = 0

        for r in records:
            rL = float(r.get("reactive_L") or 0.0)
            fL = float(r.get("forecast_L") or 0.0)

            # 方向变化：reactive_L 与 forecast_L 符号不同
            if (rL >= 0) != (fL >= 0):
                direction_changes += 1
            else:
                same_direction_count += 1

            # 解析 forecast_global_ranges JSON
            try:
                ranges = json.loads(r.get("forecast_global_ranges") or "{}")
            except (json.JSONDecodeError, TypeError):
                ranges = {}

            # 阈值变化：forecast threshold_mult 中位 vs reactive_threshold 差异 > 0.1
            r_thresh = float(r.get("reactive_threshold") or 1.0)
            direction = r.get("actual_direction") or "LONG"
            thresh_key = "long_threshold_mult" if direction == "LONG" else "short_threshold_mult"
            t_range = ranges.get(thresh_key, [1.0, 1.0])
            f_thresh = (float(t_range[0]) + float(t_range[1])) / 2.0
            if abs(f_thresh - r_thresh) > 0.1:
                threshold_changes += 1

            # 仓位变化：forecast position_mult 中位 vs reactive_pos_mult 差异 > 0.1
            r_pos = float(r.get("reactive_pos_mult") or 1.0)
            p_range = ranges.get("global_position_mult", [1.0, 1.0])
            f_pos = (float(p_range[0]) + float(p_range[1])) / 2.0
            if abs(f_pos - r_pos) > 0.1:
                position_changes += 1

        would_change = {
            "direction_changes": direction_changes,
            "threshold_changes": threshold_changes,
            "position_changes": position_changes,
        }

        # 3. direction_consistency: 方向一致率
        direction_consistency = round(same_direction_count / total, 4)

        # 4. regime_distribution: reactive regime 分布
        regime_dist: Dict[str, int] = {}
        for r in records:
            regime = r.get("reactive_regime") or "UNKNOWN"
            regime_dist[regime] = regime_dist.get(regime, 0) + 1

        return {
            "symbol": symbol,
            "days": days,
            "total_records": total,
            "param_diff_stats": param_diff_stats,
            "would_change_decision": would_change,
            "direction_consistency": direction_consistency,
            "regime_distribution": regime_dist,
        }

    def _compute_forecast_params(self, symbol: str, C: float) -> Dict[str, Any]:
        """计算 forecast 参数（L_forecast, T_forecast, global_ranges, sector_weights）。

        使用 MorphCyclePredictor.predict() 的 forecast 曲线末尾值。
        带 1h 缓存避免每次轮询都重算。
        """
        now = time.time()
        cached = self._forecast_cache.get(symbol)
        if cached and (now - cached[0]) < SHADOW_FORECAST_CACHE_TTL:
            return cached[1]

        # 调用 MorphCyclePredictor 预测（带 BTC 锚定 fallback）
        full_symbol = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
        # 优先用 predict_with_fallback（非 BTC 币种自动回退到 BTC 预测）
        if hasattr(self.predictor, "predict_with_fallback"):
            result = self.predictor.predict_with_fallback(
                full_symbol, hist_days=60, forecast_days=SHADOW_FORECAST_DAYS)
        else:
            result = self.predictor.predict(full_symbol, hist_days=60,
                                             forecast_days=SHADOW_FORECAST_DAYS)
        if not result.get("ok"):
            # 预测失败 → 用 0.0 兜底
            return {"L": 0.0, "T": 0.0, "global_ranges": "{}", "sector_weights": "{}"}

        forecast_series = result.get("series", {}).get("forecast", [])
        if not forecast_series:
            return {"L": 0.0, "T": 0.0, "global_ranges": "{}", "sector_weights": "{}"}

        L_forecast = float(forecast_series[-1])  # 5 天后预测值

        # T_forecast: 从 forecast 曲线的斜率推算（首尾差分）
        if len(forecast_series) >= 2:
            T_forecast = float(forecast_series[-1] - forecast_series[0])
        else:
            T_forecast = 0.0

        # 用 ParameterMapper 计算全局参数范围
        global_ranges = self.mapper.map_global_parameters(L_forecast, T_forecast, C)

        # 用 ParameterMapper 计算板块权重
        sector_weights = self.mapper.map_sector_weights(
            L_forecast, T_forecast, C, SHADOW_SECTOR_BETAS_DEFAULT
        )

        # global_ranges: Dict[str, Tuple[float, float]] → 逐项 round
        _ranges_flat = {}
        for _k, _v in (global_ranges or {}).items():
            try:
                if isinstance(_v, (list, tuple)) and len(_v) >= 2:
                    _ranges_flat[_k] = [round(float(_v[0]), 4), round(float(_v[1]), 4)]
                else:
                    _ranges_flat[_k] = _v
            except (TypeError, ValueError):
                _ranges_flat[_k] = _v

        # sector_weights: 嵌套 dict（weights / sector_tp_mult / sector_sl_mult）
        # → 递归 round 叶子 float，非 float 原样保留
        def _round_nested(d):
            out = {}
            for _k, _v in (d or {}).items():
                if isinstance(_v, dict):
                    out[_k] = _round_nested(_v)
                elif isinstance(_v, (int, float)):
                    out[_k] = round(float(_v), 4)
                else:
                    out[_k] = _v
            return out

        params = {
            "L": L_forecast,
            "T": T_forecast,
            "global_ranges": json.dumps(_ranges_flat, ensure_ascii=False),
            "sector_weights": json.dumps(_round_nested(sector_weights), ensure_ascii=False),
        }

        self._forecast_cache[symbol] = (now, params)
        return params
