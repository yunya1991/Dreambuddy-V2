"""双窗口周期比对器（7d + 30d 共振校验）。

对应 Spec §四 Step 6：
  对综合力向量同时计算 7 天窗口（短）与 30 天窗口（长）版本，
  做双窗口共振校验 → resonance_state + strength_multiplier。

所有方法 FAIL-OPEN：异常时返回中性默认（强度乘数 1.0，不扭曲 30d 主信号）。
"""
from __future__ import annotations

import numpy as np

from force_vector.models import CycleComparison

# 方向中性阈值：|dir| < 0.1 视为无明确方向
_NEUTRAL_THRESHOLD = 0.1


class CycleComparator:
    """7 天 + 30 天双窗口共振校验器。"""

    def compare(self, direction_7d: float, direction_30d: float,
                magnitude_7d: float, magnitude_30d: float) -> CycleComparison:
        """7天+30天双窗口共振校验。

        判定矩阵（短=7d，长=30d，方向中性阈值 |dir|<0.1）：
          | 短窗口     | 长窗口     | 共振状态    | 强度乘数 |
          | 方向一致   | 方向一致   | resonance  | ×1.2     |  短期变化与长期趋势一致
          | 方向一致   | 方向中性   | emerging   | ×0.9     |  短期变化出现，长趋势未确认
          | 方向相反   | 方向一致   | divergence | ×0.6     |  短期强逆行（|7d|>=|30d|）
          | 方向中性   | 方向一致   | persistent | ×1.0     |  短期无变化，长趋势维持
          | 方向一致   | 方向相反   | turning    | ×0.7     |  长期仍强、短期弱转（|30d|>|7d|）
          | 方向中性   | 方向中性   | observation| ×0.3     |  双窗口均无明确方向

        final_direction = direction_30d（取 30d 为主）
        final_magnitude = magnitude_30d × strength_multiplier
        异常时返回中性默认（strength_multiplier=1.0）。
        """
        try:
            d7 = float(direction_7d)
            d30 = float(direction_30d)

            short_neutral = abs(d7) < _NEUTRAL_THRESHOLD
            long_neutral = abs(d30) < _NEUTRAL_THRESHOLD

            if short_neutral and long_neutral:
                # 双窗口均无明确方向 → 观望
                state, mult = "observation", 0.3
            elif (not short_neutral) and long_neutral:
                # 短期有方向、长趋势中性 → 萌发
                state, mult = "emerging", 0.9
            elif short_neutral and (not long_neutral):
                # 短期无变化、长趋势维持 → 持续
                state, mult = "persistent", 1.0
            elif np.sign(d7) == np.sign(d30):
                # 双窗口同向（同正/同负）→ 共振
                state, mult = "resonance", 1.2
            else:
                # 双窗口均非中性且方向相反：
                #   短期强逆行（|7d|>=|30d|）→ 背离（噪音/反转前兆）
                #   长期仍强、短期弱转（|30d|>|7d|）→ 转折（早期反转信号）
                if abs(d7) >= abs(d30):
                    state, mult = "divergence", 0.6
                else:
                    state, mult = "turning", 0.7

            return CycleComparison(
                direction_7d=d7,
                direction_30d=d30,
                magnitude_7d=float(magnitude_7d),
                magnitude_30d=float(magnitude_30d),
                resonance_state=state,
                strength_multiplier=float(mult),
                final_direction=d30,
                final_magnitude=float(magnitude_30d) * float(mult),
            )
        except Exception:
            # FAIL-OPEN：中性默认，强度乘数 1.0（不扭曲 30d 主信号）
            return CycleComparison(
                direction_7d=float(direction_7d) if self._is_number(direction_7d) else 0.0,
                direction_30d=float(direction_30d) if self._is_number(direction_30d) else 0.0,
                magnitude_7d=float(magnitude_7d) if self._is_number(magnitude_7d) else 0.0,
                magnitude_30d=float(magnitude_30d) if self._is_number(magnitude_30d) else 0.0,
                resonance_state="persistent",
                strength_multiplier=1.0,
                final_direction=float(direction_30d) if self._is_number(direction_30d) else 0.0,
                final_magnitude=(float(magnitude_30d) if self._is_number(magnitude_30d) else 0.0) * 1.0,
            )

    @staticmethod
    def _is_number(v) -> bool:
        """判断 v 是否可转为 float（FAIL-OPEN 兜底用）。"""
        try:
            float(v)
            return True
        except (TypeError, ValueError):
            return False
