"""
AI 边界伸缩计算器 (AI_ENHANCEMENT_ROADMAP §3.4)

S_bt（回测稳健度得分）=
     gross_return_ratio × 0.40
   + calmar_ratio_ratio × 0.30
   + (wf_positive_segments / 5) × 0.20
   + max(0, 1 - abs(mdd_ratio - 1)) × 0.10

K_bound 映射：
   S_bt >= 1.20 → K = 1.20 （优秀，放大边界）
   1.05 <= S_bt < 1.20 → K = 1.00 （合格，默认）
   1.00 <= S_bt < 1.05 → K = 0.80 （刚过，收紧）
   S_bt  < 1.00 → ValueError（不允许启用，铁律 2）

外层铁壳（永远不可越）：K_bound ∈ [0.50, 1.35]
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


def compute_s_bt(
    gross_return_ratio: float,
    calmar_ratio_ratio: float,
    wf_positive_segments: int,
    mdd_ratio: float,
) -> float:
    """§3.4.1 回测稳健度得分 S_bt。所有 ratio 都是相对 v15-final 基线的倍数"""
    gr = float(gross_return_ratio)
    cr = float(calmar_ratio_ratio)
    wf = max(0, min(5, int(wf_positive_segments))) / 5.0
    md = max(0.0, 1.0 - abs(float(mdd_ratio) - 1.0))
    return gr * 0.40 + cr * 0.30 + wf * 0.20 + md * 0.10


def k_bound_from_s_bt(s_bt: float) -> float:
    """按 §3.4.1 映射；S_bt < 1.00 抛 ValueError（铁律 2 禁止启用）"""
    if s_bt < 1.00:
        raise ValueError(
            f"S_bt={s_bt:.3f} < 1.00：AI_ENHANCEMENT_ROADMAP §3.2 铁律 2 不通过，禁止启用"
        )
    if s_bt >= 1.20:
        k = 1.20
    elif s_bt >= 1.05:
        k = 1.00
    else:  # [1.00, 1.05)
        k = 0.80
    # 外层铁壳 [0.50, 1.35]
    return max(0.50, min(1.35, k))


def compute_s_live(
    live_pnl_ai: float,
    live_pnl_baseline_sim: float,
    live_win_rate_ai: float,
    live_win_rate_baseline_sim: float,
    live_mdd_ai: float,
    live_mdd_baseline_sim: float,
) -> float:
    """§3.4.2 实盘跟踪得分 S_live（7 天滚动窗口重算）"""
    if live_pnl_baseline_sim == 0:
        # 基线未产生盈亏 → 只比胜率和回撤
        pnl_ratio = 1.0
    else:
        pnl_ratio = float(live_pnl_ai) / float(live_pnl_baseline_sim)
    win_delta = float(live_win_rate_ai) - float(live_win_rate_baseline_sim)
    win_term = 1.0 + win_delta  # [-1, +1] 居中到 (0, 2)
    if live_mdd_baseline_sim == 0 or live_mdd_baseline_sim == 0:
        mdd_term = 1.0
    else:
        mdd_ratio = float(live_mdd_ai) / float(live_mdd_baseline_sim)
        mdd_term = max(0.0, 1.0 - abs(mdd_ratio - 1.0))
    raw = pnl_ratio * 0.50 + win_term * 0.25 + mdd_term * 0.25
    return raw


def k_bound_step_from_s_live(s_live: float, current_k: float, consecutive_windows: int) -> float:
    """§3.4.2 每 7 天一调，基于当前 K_bound 档位上/下一档；S_live<0.85 立即 raise 回退告警

    Args:
        s_live:              当前 7 天窗口得分
        current_k:           当前生效的 K_bound
        consecutive_windows: 连续多少窗口处于同阈值（≥2 才升降）
    Returns:
        new_k (float)
    Raises:
        RuntimeError: 当 S_live < 0.85，表示必须立即回退基线
    """
    if s_live < 0.85:
        raise RuntimeError(
            f"AI_ROLLBACK_TRIGGERED: S_live={s_live:.3f} < 0.85 触发 §3.4.2 单窗口立即回退基线"
        )
    # 档位阶梯：0.50 → 0.80 → 1.00 → 1.20 → 1.35 (封顶)
    steps = [0.50, 0.80, 1.00, 1.20, 1.35]
    try:
        cur_idx = next(i for i, v in enumerate(steps) if abs(v - current_k) < 1e-9)
    except StopIteration:
        # 非标准值 → 就近吸附
        cur_idx = min(range(len(steps)), key=lambda i: abs(steps[i] - current_k))

    if s_live >= 1.20 and consecutive_windows >= 2:
        new_idx = min(len(steps) - 1, cur_idx + 1)
    elif 0.85 <= s_live < 0.95 and consecutive_windows >= 2:
        new_idx = max(0, cur_idx - 1)
    else:
        new_idx = cur_idx
    return steps[new_idx]


# ================================================================
# 配置持久化：把 K_bound 写入/读出 JSON，与 §7 K_bound_phase_d 锚点对应
# ================================================================
@dataclass
class BoundaryState:
    phase: str  # 'D' / 'E' / 'F'
    k_bound: float
    s_bt: Optional[float] = None
    s_live: Optional[float] = None
    updated_at_iso: str = ""
    consecutive_high: int = 0
    consecutive_low: int = 0


class BoundaryStateStore:
    def __init__(self, state_file: str | os.PathLike[str]):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def load(self, phase: str) -> BoundaryState:
        if self.state_file.is_file():
            try:
                data = json.loads(self.state_file.read_text())
                item = data.get(phase)
                if item:
                    return BoundaryState(**item)
            except Exception:
                pass
        return BoundaryState(phase=phase, k_bound=0.80)  # 默认收紧起

    def save(self, st: BoundaryState) -> None:
        data = {}
        if self.state_file.is_file():
            try:
                data = json.loads(self.state_file.read_text())
            except Exception:
                data = {}
        data[st.phase] = asdict(st)
        self.state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
