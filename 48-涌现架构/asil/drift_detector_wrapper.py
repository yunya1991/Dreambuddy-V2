"""ASIL 漂移检测 wrapper — 复用 4-MEMORY/9-工具与接口/drift_detector.py

SPEC §3.5 三重漂移 + §3.2 R3 psi_stability 归一化。
不重写已有实现，只加 VaR 第三门 + R3 归一化函数。
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

# 复用已有漂移检测器 — 不重写
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))

# 已有实现：compute_psi / ks_test_drift / classify_drift / classify_drift_triple / drift_kill_switch
_drift_mod = import_module("4-MEMORY.9-工具与接口.drift_detector")

# 透传已有 API
PSI_STABLE = _drift_mod.PSI_STABLE
PSI_MINOR_DRIFT = _drift_mod.PSI_MINOR_DRIFT
compute_psi = _drift_mod.compute_psi
ks_test_drift = _drift_mod.ks_test_drift
classify_drift = _drift_mod.classify_drift
classify_drift_triple = _drift_mod.classify_drift_triple
drift_kill_switch = _drift_mod.drift_kill_switch


# ---------------------------------------------------------------------------
# SPEC §3.5 VaR 第三门 + ASIL 三重融合（PSI + KS + VaR）
# ---------------------------------------------------------------------------
def classify_drift_asil(
    psi_value: float,
    ks_drifted: bool,
    var_exceeded: bool = False,
) -> str:
    """ASIL 三重漂移分类（SPEC §3.5）。

    规则：
      PSI minor + KS drifted → 升级 severe_drift
      PSI minor + VaR exceeded → 升级 severe_drift
      PSI severe + VaR exceeded → 确认 severe_drift
      其他 → PSI/KS 融合结果
    """
    level = classify_drift_triple(psi_value, ks_drifted)
    if level == "minor_drift" and var_exceeded:
        return "severe_drift"
    return level


# ---------------------------------------------------------------------------
# SPEC §3.2 R3 psi_stability 归一化
# ---------------------------------------------------------------------------
def r3_psi_stability(psi_value: float) -> float:
    """R3 psi_stability = max(0, 1 - PSI / 0.25)，clip 到 [0, 1]。

    PSI=0 → 1.0（完美稳定）
    PSI=0.25 → 0.0（严重漂移）
    PSI>0.25 → 0.0（饱和）
    """
    raw = 1.0 - psi_value / PSI_MINOR_DRIFT
    return max(0.0, min(1.0, raw))
