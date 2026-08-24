"""
方案 C v3.0 R-2：BCRMContinuityObserver
========================================
连续信号观察器：N=5 笔滚动窗口（P6 冻结），五级连续性判定。

输入：每次 BCRM 推理的 (symbol, direction, ts, conf, hex_name)
输出：(continuity_grade, continuity_score)
  - ALIGN_FULL (1.0)    : 4/5 或 5/5 同向
  - ALIGN_BASIC (0.85)  : 3/5 同向
  - NEUTRAL (0.65)      : 2/5 同向（或空窗）
  - DIVERGE_BASIC (0.45): 1/5 同向
  - DIVERGE_SEVERE (0.30): 0/5 同向，或 ≥1 笔强反信（反方向 conf≥0.85）

fail-open：空窗 / 异常 → ("NEUTRAL", 0.65)
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class _ContinuityEntry:
    ts: datetime
    direction: str            # "LONG" / "SHORT"
    confidence: float
    hexagram_name: str = ""


class BCRMContinuityObserver:
    """
    BCRM 连续信号观察器（每个 symbol 独立维护一个 5 笔环形缓存）。
    """

    def __init__(self, window_n: Optional[int] = None, enable: bool = False):
        from . import phase_c_constants as C
        self.enable = bool(enable)
        self._window_n: int = int(window_n or C.BCRM_CONTINUITY_WINDOW_N)
        self._per_symbol: Dict[str, Deque[_ContinuityEntry]] = {}
        self._last_failopen_logged_hour: str = ""

    # ---------------- 内部：分位键 ----------------
    @staticmethod
    def _sym_key(symbol: str) -> str:
        return str(symbol).upper()

    def _get_window(self, symbol: str) -> Deque[_ContinuityEntry]:
        k = self._sym_key(symbol)
        if k not in self._per_symbol:
            self._per_symbol[k] = deque(maxlen=self._window_n)
        return self._per_symbol[k]

    # ---------------- 公共：追加 & 五级判定 ----------------
    def append_and_grade(self,
                         symbol: str,
                         direction: str,
                         ts: Optional[datetime] = None,
                         confidence: float = 0.65,
                         hexagram_name: str = "",
                         ) -> Tuple[str, float]:
        """
        追加一笔 BCRM 推理结果并返回 (grade, score)。

        Returns:
            (grade_str, continuity_score_float)
        """
        try:
            # enable=False → 旁路 fail-open，不写入 window
            if not self.enable:
                from . import phase_c_constants as C
                return C.FAILOPEN_CONT_GRADE, float(C.FAILOPEN_CONT_SCORE)
            ts = ts or datetime.now()
            entry = _ContinuityEntry(
                ts=ts,
                direction=str(direction).upper(),
                confidence=max(0.0, min(1.0, float(confidence))),
                hexagram_name=str(hexagram_name or ""),
            )
            window = self._get_window(symbol)
            window.append(entry)

            return self._grade_window(window, latest_dir=entry.direction)

        except Exception as e:  # noqa: BLE001 - fail-open 兜底
            from . import phase_c_constants as C
            import datetime as _dt
            hour_tag = _dt.datetime.now().strftime("%Y-%m-%dT%H")
            if self._last_failopen_logged_hour != hour_tag:
                logger.warning(
                    "[BCRMContinuityObserver] fail-open（每小时最多 1 次），原因=%s，返回 NEUTRAL/0.65",
                    type(e).__name__,
                )
                self._last_failopen_logged_hour = hour_tag
            return C.FAILOPEN_CONT_GRADE, float(C.FAILOPEN_CONT_SCORE)

    # ---------------- 公共：只读（不追加）当前档位 ----------------
    def current_grade(self, symbol: str, reference_direction: str) -> Tuple[str, float]:
        try:
            window = self._get_window(symbol)
            return self._grade_window(window, latest_dir=str(reference_direction).upper())
        except Exception:  # noqa: BLE001
            from . import phase_c_constants as C
            return C.FAILOPEN_CONT_GRADE, float(C.FAILOPEN_CONT_SCORE)

    # ---------------- 公共：连续 S_cont（近 20 窗口真实胜率）----------------
    def get_s_cont(self, symbol: str, history_results: Optional[List[Tuple[str, bool]]] = None) -> float:
        """
        S_cont：近 N 窗口的 BCRM 连续信号真实胜率（用于 P8 S 合成）。
        history_results: List[(direction_str, win_bool)]，可选外部注入；
        未提供或样本<5（T4.12 小数定律防护）时退化为中性 0.50。
        """
        try:
            if not history_results or len(history_results) < 5:
                return 0.50
            wins = sum(1 for _, w in history_results if w)
            return wins / max(1, len(history_results))
        except Exception:
            return 0.50

    # ---------------- 核心：五级判定 ----------------
    @staticmethod
    def _grade_window(window: Deque[_ContinuityEntry], latest_dir: str) -> Tuple[str, float]:
        from . import phase_c_constants as C

        n = len(window)
        if n == 0:
            return C.FAILOPEN_CONT_GRADE, float(C.FAILOPEN_CONT_SCORE)

        # 1) 同向计数（以 latest_dir 为"正方向"）
        same = sum(1 for e in window if e.direction == latest_dir)
        ratio = same / max(1, n)

        # 2) 强反信检测：反方向且 conf≥0.85
        strong_opposite = False
        for e in window:
            if e.direction != latest_dir and e.confidence >= 0.85:
                strong_opposite = True
                break

        # 3) 五级映射
        # 0/5 同 + 强反信 → SEVERE
        if same == 0 and strong_opposite:
            return "DIVERGE_SEVERE", 0.30
        if same <= 0:
            return "DIVERGE_SEVERE", 0.30
        if same == 1:
            return "DIVERGE_BASIC", 0.45
        if same == 2:
            return "NEUTRAL", 0.65
        if same == 3:
            return "ALIGN_BASIC", 0.85
        # same ∈ {4,5}
        return "ALIGN_FULL", 1.00

    # ---------------- 辅助：Score_B 合成 ----------------
    @staticmethod
    def compose_score_b(continuity_score: float,
                        single_confidence: float,
                        ) -> float:
        """
        Score_B = P7 · continuity_score + (1-P7) · pure_conf_linear
        pure_conf_linear = 0.40 + 0.60 × single_confidence → 区间 [0.40, 1.0]
        """
        from . import phase_c_constants as C
        conf_linear = 0.40 + 0.60 * max(0.0, min(1.0, float(single_confidence)))
        sc = C.SCORE_B_CONT_WEIGHT * max(0.0, min(1.0, float(continuity_score)))
        sb = C.SCORE_B_CONF_WEIGHT * conf_linear
        return sc + sb
