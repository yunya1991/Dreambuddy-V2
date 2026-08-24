"""
方案 C v3.0 子系统 1：ThreeLayerWeighter
========================================
三层动态权重引擎（P1 大周期 / Elder 中周期 / BCRM 小周期）。
每日 00:05 或 run_once 首次命中新交易日时重算 w_p:w_e:w_b。

v3.0 约束：
  - 任一权重 ∈ [0.05, 0.80]，三者和 = 1
  - fail-open：wp=0.45, we=0.30, wb=0.25, source="fail_open"
  - Δ_max（P4*）= 0.10（单日绝对变化上限）
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_THIS_DIR = Path(__file__).resolve().parent
_RUNTIME_DIR = _THIS_DIR / "runtime"
_DYNAMIC_PARAM_PATH = _RUNTIME_DIR / "phase_c_default_params.json"


@dataclass
class ThreeLayerWeights:
    """三层动态权重输出（Σ=1，归一化约束保证）"""
    w_p: float = 0.45
    w_e: float = 0.30
    w_b: float = 0.25
    s_bcrm: float = 0.0
    delta: float = 0.0
    match_boost: float = 0.0
    source: str = "fail_open"

    def as_dict(self) -> Dict[str, float]:
        return {
            "w_p": self.w_p,
            "w_e": self.w_e,
            "w_b": self.w_b,
            "s_bcrm": self.s_bcrm,
            "delta": self.delta,
            "match_boost": self.match_boost,
            "source": self.source,
        }


class ThreeLayerWeighter:
    """
    三层动态权重引擎（Task 3.5 / 子系统 1）

    运行周期：日级（每交易日 00:05 或 run_once 首次触达新日期）
    输入：S_BCRM（近 30/60/120 笔胜率加权）、CBR 基线 match_boost
    输出：ThreeLayerWeights（w_p, w_e, w_b, Σ=1，归一化 + clip 硬约束）

    fail-open 铁则：
      - 任何异常（计算错误 / 样本不足 / 文件缺失）→ 返回冷启动权重 45:30:25
      - 日志 1 次/日去重，含失败原因简码
    """

    # ------------------------------
    # 构造 & 初始化
    # ------------------------------
    def __init__(self, runtime_dir: Optional[Path] = None, enable: bool = False):
        self.enable = bool(enable)
        self._runtime_dir = Path(runtime_dir) if runtime_dir else _RUNTIME_DIR
        self._runtime_dir.mkdir(parents=True, exist_ok=True)

        self._params = self._load_dynamic_params()
        self._last_recalc_date: Optional[date] = None
        self._last_weights: ThreeLayerWeights = self._failopen_weights()
        self._failopen_logged_today: str = ""  # 去重：YYYY-MM-DD

    def _load_dynamic_params(self) -> Dict[str, Any]:
        """加载动态参数文件，不存在返回 §二 默认初值"""
        try:
            if _DYNAMIC_PARAM_PATH.exists():
                raw = _DYNAMIC_PARAM_PATH.read_text(encoding="utf-8")
                data = json.loads(raw)
                merged = dict(DYNAMIC_PARAM_DEFAULTS)
                merged.update({k: float(v) for k, v in data.items()
                               if k in DYNAMIC_PARAM_DEFAULTS})
                return merged
        except (OSError, json.JSONDecodeError, ValueError) as e:
            logger.warning("[ThreeLayerWeighter] 动态参数文件加载失败，回退默认值：%s", e)
        return dict(DYNAMIC_PARAM_DEFAULTS)

    # ------------------------------
    # fail-open 辅助
    # ------------------------------
    @staticmethod
    def _failopen_weights() -> ThreeLayerWeights:
        from . import phase_c_constants as C
        return ThreeLayerWeights(
            w_p=C.FAILOPEN_WP,
            w_e=C.FAILOPEN_WE,
            w_b=C.FAILOPEN_WB,
            s_bcrm=0.0,
            delta=0.0,
            match_boost=0.0,
            source="fail_open",
        )

    def _log_failopen_once(self, reason_code: str) -> None:
        today = date.today().isoformat()
        if self._failopen_logged_today != today:
            logger.warning(
                "[ThreeLayerWeighter] fail-open（每日最多 1 次），原因=%s，返回冷启动权重 45:30:25",
                reason_code,
            )
            self._failopen_logged_today = today

    # ------------------------------
    # 公共接口：核心方法
    # ------------------------------
    def daily_recalc(self, stats: Optional[Dict[str, Any]] = None,
                     force: bool = False) -> ThreeLayerWeights:
        """
        日级重算三层权重。

        Args:
            stats: 统计字典，含：
              - s_bcrm_30 / s_bcrm_60 / s_bcrm_120（近 30/60/120 笔 BCRM 胜率）
              - match_boost（CBR 基线家族命中加成 [-0.20, +0.20]）
            force: 强制重算（忽略日期缓存，主要用于测试）

        Returns:
            ThreeLayerWeights：归一化后的三层权重
        """
        try:
            today = date.today()
            if not force and self._last_recalc_date == today:
                return self._last_weights

            # --- 样本不足或无统计 → fail-open ---
            if not stats:
                self._log_failopen_once("NO_STATS")
                self._last_weights = self._failopen_weights()
                self._last_recalc_date = today
                return self._last_weights

            wp0 = float(self._params.get("wp_cold", 0.45))
            we0 = float(self._params.get("we_cold", 0.30))
            wb0 = float(self._params.get("wb_cold", 0.25))
            delta_max = float(self._params.get("delta_max", 0.10))
            from . import phase_c_constants as C

            # 1) 计算 S_BCRM：近 30/60/120 笔胜率加权（0.5/0.3/0.2），样本不足退化为 0.5
            s30 = stats.get("s_bcrm_30")
            s60 = stats.get("s_bcrm_60")
            s120 = stats.get("s_bcrm_120")
            win_rate_valid_parts: list[Tuple[float, float]] = []
            if isinstance(s30, (int, float)):
                win_rate_valid_parts.append((0.5, float(s30)))
            if isinstance(s60, (int, float)):
                win_rate_valid_parts.append((0.3, float(s60)))
            if isinstance(s120, (int, float)):
                win_rate_valid_parts.append((0.2, float(s120)))
            if not win_rate_valid_parts:
                s_bcrm = 0.5
            else:
                tot_w = sum(w for w, _ in win_rate_valid_parts)
                s_bcrm = sum(w * s for w, s in win_rate_valid_parts) / tot_w if tot_w > 0 else 0.5

            # 2) 计算 delta = delta_max · (2·S_BCRM - 1) ∈ [-Δ_max, +Δ_max]
            delta = delta_max * (2.0 * s_bcrm - 1.0)
            delta = max(-delta_max, min(delta_max, delta))

            # 3) match_boost 截取 [-0.20, 0.20]
            match_boost_raw = float(stats.get("match_boost", 0.0) or 0.0)
            match_boost = max(-0.20, min(0.20, match_boost_raw))

            # 4) 权重调整：w_b += delta + match_boost；w_p - δ1；w_e - δ2（各取一半）
            wb_new = wb0 + delta + match_boost
            transfer = delta + match_boost
            wp_new = wp0 - 0.5 * transfer
            we_new = we0 - 0.5 * transfer

            # 5) 硬 clip：任一 ∈ [0.05, 0.80]（迭代 2 次，防止归一化后再次越界）
            w_min = C.THREE_LAYER_WEIGHT_MIN
            w_max = C.THREE_LAYER_WEIGHT_MAX
            wp_c = max(w_min, min(w_max, wp_new))
            we_c = max(w_min, min(w_max, we_new))
            wb_c = max(w_min, min(w_max, wb_new))

            # 6) 归一化：Σ = 1
            total = wp_c + we_c + wb_c
            if total <= 0 or not math.isfinite(total):
                self._log_failopen_once("NORMALIZE_SUM")
                self._last_weights = self._failopen_weights()
                self._last_recalc_date = today
                return self._last_weights
            wp_n = wp_c / total
            we_n = we_c / total
            wb_n = wb_c / total

            # 6.1) **二次 clip 校正**：归一化可能破坏 [w_min, w_max]（例如 wb clip=0.05 但 Σ=1.10 → wb_n=0.0455）
            # 先迭代最多 3 次 clip→归一化，吸收绝大多数正常场景
            for _ in range(3):
                wp_r = max(w_min, min(w_max, wp_n))
                we_r = max(w_min, min(w_max, we_n))
                wb_r = max(w_min, min(w_max, wb_n))
                tot_r = wp_r + we_r + wb_r
                if tot_r <= 0 or not math.isfinite(tot_r):
                    break
                wp_n, we_n, wb_n = wp_r/tot_r, we_r/tot_r, wb_r/tot_r
                if (w_min - 1e-8 <= wp_n <= w_max + 1e-8
                        and w_min - 1e-8 <= we_n <= w_max + 1e-8
                        and w_min - 1e-8 <= wb_n <= w_max + 1e-8):
                    break

            # 6.2) **最终边界兜底**：浮点残余误差导致的微越界 → 强制拉回边界 + 差额再分配
            # （保证严格 w_min ≤ w ≤ w_max 到 1e-12 精度，且 Σ=1）
            def _final_enforce_bounds(wp: float, we: float, wb: float) -> tuple[float, float, float]:
                vals = [("wp", wp), ("we", we), ("wb", wb)]
                excess = 0.0  # 从越界项挤出的超额
                deficit = 0.0  # 越界项需要补足的缺口
                clipped: list[tuple[str, float]] = []
                for name, v in vals:
                    if v < w_min - 1e-12:
                        deficit += (w_min - v)
                        clipped.append((name, w_min))
                    elif v > w_max + 1e-12:
                        excess += (v - w_max)
                        clipped.append((name, w_max))
                    else:
                        clipped.append((name, v))
                if deficit == 0.0 and excess == 0.0:
                    return clipped[0][1], clipped[1][1], clipped[2][1]
                # 需要再分配：excess/deficit 从非边界项按比例增减
                out_d = {"wp": clipped[0][1], "we": clipped[1][1], "wb": clipped[2][1]}
                need = excess - deficit  # >0 需要扣掉，<0 需要补上
                non_boundary_keys: list[str] = []
                for nm, v_orig in vals:
                    cv = out_d[nm]
                    # 判定是否被 clip 卡了边界（即原始值不在可接受区间）
                    was_bounded = (v_orig < w_min - 1e-12) or (v_orig > w_max + 1e-12)
                    if not was_bounded:
                        non_boundary_keys.append(nm)
                if non_boundary_keys:
                    total_nb = sum(out_d[k] for k in non_boundary_keys)
                    if total_nb > 1e-12:
                        for k in non_boundary_keys:
                            # 按非边界项的相对比例分配
                            share = out_d[k] / total_nb
                            new_v = out_d[k] - share * need
                            # 二次 clip 防极端传播（传播后不再分配）
                            new_v = max(w_min, min(w_max, new_v))
                            out_d[k] = new_v
                wp_f, we_f, wb_f = out_d["wp"], out_d["we"], out_d["wb"]
                # 注：差额分配完成后 Σ 已=1（within 1e-12），不再次归一化（防止卡底/卡顶权重再次被摊薄）
                return wp_f, we_f, wb_f

            wp_n, we_n, wb_n = _final_enforce_bounds(wp_n, we_n, wb_n)

            weights = ThreeLayerWeights(
                w_p=wp_n,
                w_e=we_n,
                w_b=wb_n,
                s_bcrm=s_bcrm,
                delta=delta,
                match_boost=match_boost,
                source="daily_recalc",
            )
            self._last_weights = weights
            self._last_recalc_date = today
            return weights

        except Exception as e:  # noqa: BLE001 - fail-open 兜底
            self._log_failopen_once(f"EXCEPTION:{type(e).__name__}")
            self._last_weights = self._failopen_weights()
            self._last_recalc_date = date.today()
            return self._last_weights

    # ------------------------------
    # Shadow 日志导出辅助
    # ------------------------------
    def last_shadow_dict(self) -> Dict[str, Any]:
        return self._last_weights.as_dict()


# 为了常量文件兼容，保留 DYNAMIC_PARAM_DEFAULTS 引用（与 phase_c_constants.py 重复时取常量文件）
try:
    from .phase_c_constants import DYNAMIC_PARAM_DEFAULTS  # noqa: F401
except ImportError:  # 独立测试环境下兜底
    DYNAMIC_PARAM_DEFAULTS = {
        "wp_cold": 0.45,
        "we_cold": 0.30,
        "wb_cold": 0.25,
        "delta_max": 0.10,
        "p1_block_cap": 0.10,
        "global_clip_high": 1.50,
        "theta_match_star": 0.80,
        "gamma_max_star": 0.20,
    }
