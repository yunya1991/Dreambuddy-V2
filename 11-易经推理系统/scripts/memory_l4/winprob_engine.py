"""
方案 C v3.0 子系统 5：WinProbEngine
====================================
盈亏概率动态权重（P17）：

步骤（四步计算法）：
  1. KNN 检索：CBR 同大类同方向 top-K 相似案例
  2. 加权胜率：Σ similarity_i · win_i / Σ similarity_i  → pred_win_rate
  3. 自适应权重 w_winprob：Brier 分数 > 0.25 → w_winprob = 0（强制旁路 24h）
     否则 w_winprob ∈ [0, 1] 平滑
  4. 仓位调整：final_winprob_mult = 1 + w_winprob · (pred_win_rate - 0.5) · 2
     clip ∈ [0.80, 1.20]

旁路条件（fail-open）：
  - 样本数 < P17_G2_MIN_SAMPLES = 30 → mult = 1.0
  - 任何异常 → mult = 1.0
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class WinProbOutput:
    pred_win_rate: float
    w_winprob: float
    final_winprob_mult: float
    sample_count: int = 0
    reason: str = "normal"

    def as_shadow_dict(self) -> Dict[str, float]:
        return {
            "pred_win_rate": self.pred_win_rate,
            "w_winprob": self.w_winprob,
            "final_winprob_mult": self.final_winprob_mult,
        }


class WinProbEngine:
    """
    WinProb 盈亏概率因子：基于 CBR 历史案例的加权胜率预测。
    """

    def __init__(self, enable: bool = False):
        self.enable = bool(enable)
        self._brier_force_bypass_until_ts: float = 0.0
        self._last_failopen_logged_hour: str = ""

    # ---------------- 公共接口 ----------------
    def get_multiplier(self, q_vec: Optional[Dict[str, Any]] = None) -> Tuple[float, Dict[str, Any]]:
        """
        返回 (final_winprob_mult, shadow_dict)。

        q_vec 字段（可 None，缺省走旁路）：
          - sample_count: int（同大类同方向有效配对数）
          - pred_win_rate: float（KNN 加权胜率，外部可直接预计算后传入）
          - brier_score: float（历史 Brier 分数，>0.25 → 强制旁路 24h）
          - knn_topk: List[Tuple[similarity, win_bool]]（若未传 pred_win_rate，内部计算）
        """
        try:
            from . import phase_c_constants as C

            q_vec = q_vec or {}
            sample_count = int(q_vec.get("sample_count", 0))
            brier = float(q_vec.get("brier_score", 0.0) or 0.0)

            shadow = {
                "sample_count": sample_count,
                "brier_score": brier,
            }

            # --- P17 G-2：样本不足立即旁路 ---
            if sample_count < C.WINPROB_G2_MIN_SAMPLES:
                return 1.0, {
                    **shadow,
                    "pred_win_rate": 0.5,
                    "w_winprob": 0.0,
                    "final_winprob_mult": 1.0,
                    "reason": f"bypass_samples_{sample_count}_lt_{C.WINPROB_G2_MIN_SAMPLES}",
                }

            # --- G-3：Brier > 0.25 → 强制旁路 24h ---
            now = time.time()
            if brier > C.WINPROB_G3_MAX_BRIER:
                self._brier_force_bypass_until_ts = now + 86400  # 24h
            if now < self._brier_force_bypass_until_ts:
                remain_s = int(self._brier_force_bypass_until_ts - now)
                return 1.0, {
                    **shadow,
                    "pred_win_rate": 0.5,
                    "w_winprob": 0.0,
                    "final_winprob_mult": 1.0,
                    "reason": f"bypass_brier_gt_025_remain_{remain_s}s",
                }

            # --- Step1/2：pred_win_rate ---
            if "pred_win_rate" in q_vec and q_vec["pred_win_rate"] is not None:
                pred_win_rate = max(0.0, min(1.0, float(q_vec["pred_win_rate"])))
            else:
                topk = q_vec.get("knn_topk") or []
                if not topk:
                    return 1.0, {
                        **shadow,
                        "pred_win_rate": 0.5,
                        "w_winprob": 0.0,
                        "final_winprob_mult": 1.0,
                        "reason": "bypass_no_knn",
                    }
                num = 0.0
                den = 0.0
                for sim, win in topk:
                    s = max(0.0, float(sim))
                    w = 1.0 if win else 0.0
                    num += s * w
                    den += s
                pred_win_rate = num / den if den > 0 else 0.5
                pred_win_rate = max(0.0, min(1.0, pred_win_rate))

            # --- Step3：w_winprob 自适应权重（简化：Brier ≤ 0.25 → 1.0）---
            # 后续可按历史预测准确率 EMA 平滑，当前 v3.0 用硬门控
            w_winprob = 1.0 if brier <= C.WINPROB_G3_MAX_BRIER else 0.0

            # --- Step4：仓位调整 ∈ [0.80, 1.20] ---
            raw_mult = 1.0 + w_winprob * (pred_win_rate - 0.5) * 2.0
            final_mult = max(C.WINPROB_MULT_LOW, min(C.WINPROB_MULT_HIGH, raw_mult))

            return float(final_mult), {
                **shadow,
                "pred_win_rate": pred_win_rate,
                "w_winprob": w_winprob,
                "final_winprob_mult": float(final_mult),
                "reason": "applied",
            }

        except Exception as e:  # noqa: BLE001 - fail-open 兜底
            from . import phase_c_constants as C
            import datetime as _dt
            hour_tag = _dt.datetime.now().strftime("%Y-%m-%dT%H")
            if self._last_failopen_logged_hour != hour_tag:
                logger.warning(
                    "[WinProbEngine] fail-open（每小时最多 1 次），原因=%s，返回 1.0",
                    type(e).__name__,
                )
                self._last_failopen_logged_hour = hour_tag
            return float(C.FAILOPEN_WINPROB_MULT), {
                "pred_win_rate": 0.5,
                "w_winprob": 0.0,
                "final_winprob_mult": 1.0,
                "reason": f"fail_open:{type(e).__name__}",
            }
