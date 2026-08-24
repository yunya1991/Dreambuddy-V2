"""
方案 C v3.0 R-3：BTCSelfReflexValve
====================================
BTC 自反调控闸门（仅限 BTC 多头）。

五重硬门槛（P9）必须同时命中：
  ① D_PE > 0（BTC 多头正在自反 / 做多亢奋）
  ② BCRMContinuityObserver BTC DOWN ≥ ALIGN_BASIC（3/5 同向）
  ③ S_BTC_only ≥ 0.60（近 10 笔 BTC 专属胜率）
  ④ 近 7 窗口实际成交率 n_rev ≥ 60% × N_windows
  ⑤ 24h 内未触发踏空/亏损 >0.5% 熔断（G-01 冷却期外）

λ 公式（P10）：λ = 1 - 0.40 · min(1, n_rev/3) · S_BCRM，clip ∈ [0.60, 1.0]

fail-open：任何异常 → (1.0, {"reason":"fail_open"})（零影响）
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class _BTCReflexState:
    last_n_rev_ts: float = 0.0
    last_lambda: float = 1.0
    last_daily_penalty_acc: float = 0.0
    last_trade_date: str = ""


class BTCSelfReflexValve:
    """
    BTC 自反调控闸门：
      - 仅 BTC / 仅多头生效（其他币种直接 return 1.0）
      - 惩罚冷却：n_rev 冷却 30 分钟
      - 单日惩罚上限：0.70（即 λ ≥ 0.30？不：clip 到 0.60，因此惩罚最多 0.40；
        P9 单交易日最大惩罚 cap=0.70 指 λ 不低于 1 - 0.70 = 0.30，
        与 P10 取更严格：λ = max(P10_low, 1 - daily_cap) = 0.60）
    """

    def __init__(self, enable: bool = False):
        self.enable = bool(enable)
        self._state = _BTCReflexState()
        self._last_failopen_logged_hour: str = ""

    # ---------------- 公共接口 ----------------
    def get_lambda(self, ctx: Optional[Dict[str, Any]] = None) -> Tuple[float, Dict[str, Any]]:
        """
        返回 (lambda_value, shadow_dict)。

        ctx 字典字段（全部可选，缺省时自动退化为 fail-open）：
          - symbol: str（必须 "BTC" / "BTCUSDT" 才生效）
          - direction: str（必须 "LONG" 才生效）
          - d_pe_sign: int（+1 / -1 / 0；P9 ①）
          - btc_cont_grade: str（P9 ② ≥ ALIGN_BASIC）
          - s_btc_only: float（P9 ③ ≥ 0.60）
          - n_rev: int（P9 ④ 近 7 窗口的实际 BTC DOWN 成交笔数）
          - n_windows: int（近 7 窗口总数 = 7）
          - s_bcrm_global: float（λ 公式使用）
          - fuse_blocked_24h: bool（P9 ⑤ 是否处于 G-01/G-04 24h 熔断）
        """
        try:
            from . import phase_c_constants as C

            ctx = ctx or {}
            symbol = str(ctx.get("symbol", "")).upper()
            direction = str(ctx.get("direction", "")).upper()

            # --- 非 BTC / 非多头 → 零惩罚 λ = 1.0 ---
            if "BTC" not in symbol or direction != "LONG":
                return 1.0, {
                    "reason": "skip_non_btc_long",
                    "symbol": symbol,
                    "direction": direction,
                }

            # --- 提取门槛字段 ---
            d_pe_sign = int(ctx.get("d_pe_sign", 0))
            btc_cont_grade = str(ctx.get("btc_cont_grade", "NEUTRAL")).upper()
            s_btc_only = float(ctx.get("s_btc_only", C.FAILOPEN_S_BTC_ONLY_LOW_SAMPLE))
            n_rev = int(ctx.get("n_rev", 0))
            n_windows = int(ctx.get("n_windows", 7))
            s_bcrm = float(ctx.get("s_bcrm_global", 0.5))
            fuse_blocked = bool(ctx.get("fuse_blocked_24h", False))

            shadow = {
                "d_pe_positive": bool(d_pe_sign > 0),
                "btc_cont_grade": btc_cont_grade,
                "s_btc_only": s_btc_only,
                "n_rev": n_rev,
                "n_windows": n_windows,
                "s_bcrm_global": s_bcrm,
                "fuse_blocked_24h": fuse_blocked,
            }

            # --- P9 五重门槛 AND ---
            # ① D_PE > 0
            if d_pe_sign <= 0:
                return 1.0, {**shadow, "reason": "g1_dpe_not_positive"}
            # ② BCRM BTC DOWN 连续性 ≥ ALIGN_BASIC
            grade_rank = {
                "ALIGN_FULL": 4, "ALIGN_BASIC": 3,
                "NEUTRAL": 2, "DIVERGE_BASIC": 1, "DIVERGE_SEVERE": 0,
            }
            if grade_rank.get(btc_cont_grade, 0) < grade_rank.get("ALIGN_BASIC", 3):
                return 1.0, {**shadow, "reason": "g2_cont_not_align_basic"}
            # ③ S_BTC_only ≥ 0.60
            if s_btc_only < C.P9_BTC_S_BTC_ONLY_MIN:
                return 1.0, {**shadow, "reason": f"g3_s_btc_below_{C.P9_BTC_S_BTC_ONLY_MIN}"}
            # ④ n_rev ≥ 60% × n_windows
            fill_ratio = n_rev / max(1, n_windows)
            if fill_ratio < C.P9_BTC_WINDOW_FILL_RATIO:
                return 1.0, {**shadow, "reason": f"g4_fill_ratio_{fill_ratio:.2f}_below_{C.P9_BTC_WINDOW_FILL_RATIO}"}
            # ⑤ 24h 未触发大熔断
            if fuse_blocked:
                return 1.0, {**shadow, "reason": "g5_fuse_blocked_24h"}

            # --- 冷却：n_rev 冷却 30 分钟（P9 n_rev cooldown）---
            now = time.time()
            cooldown_sec = C.P9_BTC_N_REV_COOLDOWN_MIN * 60
            if now - self._state.last_n_rev_ts < cooldown_sec:
                return (
                    float(self._state.last_lambda),
                    {**shadow, "reason": f"cooldown_remaining_{int(cooldown_sec - (now - self._state.last_n_rev_ts))}s"},
                )

            # --- λ 公式：λ = 1 - 0.40 · min(1, n_rev/3) · S_BCRM ---
            n_factor = min(1.0, n_rev / 3.0)
            penalty = C.BTC_REFLEX_PENALTY_MAX * n_factor * max(0.0, min(1.0, s_bcrm))
            lambda_raw = 1.0 - penalty

            # --- 单日惩罚上限：累计 penalty 不超过 P9_BTC_PENALTY_DAILY_CAP ---
            today = datetime.now().strftime("%Y-%m-%d")
            if self._state.last_trade_date != today:
                self._state.last_trade_date = today
                self._state.last_daily_penalty_acc = 0.0
            if self._state.last_daily_penalty_acc + penalty > C.P9_BTC_PENALTY_DAILY_CAP:
                penalty = max(0.0, C.P9_BTC_PENALTY_DAILY_CAP - self._state.last_daily_penalty_acc)
                lambda_raw = 1.0 - penalty
            self._state.last_daily_penalty_acc += penalty

            # --- P10 clip：λ ∈ [0.60, 1.0] ---
            lambda_final = max(C.BTC_REFLEX_LAMBDA_LOW,
                               min(C.BTC_REFLEX_LAMBDA_HIGH, lambda_raw))

            # --- 写入 state 冷却 ---
            self._state.last_n_rev_ts = now
            self._state.last_lambda = float(lambda_final)

            return float(lambda_final), {
                **shadow,
                "n_factor": n_factor,
                "penalty": penalty,
                "lambda_final": float(lambda_final),
                "reason": "applied",
            }

        except Exception as e:  # noqa: BLE001 - fail-open 兜底
            from . import phase_c_constants as C
            import datetime as _dt
            hour_tag = _dt.datetime.now().strftime("%Y-%m-%dT%H")
            if self._last_failopen_logged_hour != hour_tag:
                logger.warning(
                    "[BTCSelfReflexValve] fail-open（每小时最多 1 次），原因=%s，返回 λ=1.0",
                    type(e).__name__,
                )
                self._last_failopen_logged_hour = hour_tag
            return float(C.FAILOPEN_BTC_REFLEX_LAMBDA), {
                "reason": f"fail_open:{type(e).__name__}",
            }
