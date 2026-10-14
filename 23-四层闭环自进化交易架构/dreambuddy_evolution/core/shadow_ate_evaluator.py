"""
Shadow ATE 评估器（含 DML）— 影子期每日产出 A2 门禁态证据
SPEC-Shadow验证自动放量门禁.md §3-§5

仅由子进程 scripts/shadow_ate_eval.py 调用；FAIL-OPEN：任何异常 → None，不抛。
注意：本模块 import DML 相关（causal），**不得**被门禁主链路 import。
"""
from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)


def evaluate_and_record(gate, switch_name: str | None = None) -> dict | None:
    """评估目标开关当日 A2 门禁态并写入 gate 状态文件.

    Returns: 观测 dict（已 record 成功）或 None（无有效观测）。FAIL-OPEN。
    """
    try:
        from dreambuddy_evolution.core.causal_sample_store import CausalSampleStore
        from dreambuddy_evolution.core.causal_engine import CausalEngine
        from dreambuddy_evolution.core.contradiction_identifier import (
            SESOI_TAU_DEFAULT,
            classify_ate_state,
        )
        from dreambuddy_evolution.core.shadow_activation_gate import ShadowActivationGate

        name = switch_name or getattr(gate, "switch_name", None)
        g = gate if gate is not None else ShadowActivationGate(name)

        triplet = CausalSampleStore().build_ate_samples()
        if not triplet:
            return None
        X = triplet["X"]
        treatment = triplet["treatment"]
        y = triplet["y"]
        n = int(len(y))

        result = CausalEngine().estimate_ate(X, treatment, y, method="dml")
        if not isinstance(result, dict):
            return None
        state = classify_ate_state(result, SESOI_TAU_DEFAULT)
        obs = {
            "date": date.today().isoformat(),
            "gate_state": state,
            "ate": float(result.get("ate", 0.0)),
            "lb": float(result.get("lower_bound", 0.0)),
            "ub": float(result.get("upper_bound", 0.0)),
            "source": str(triplet.get("source", "bootstrap")),
            "n": n,
            "method": str(result.get("method", "error")),
        }
        if not g.record(obs):
            return None
        return obs
    except Exception as e:  # noqa: BLE001  HC-AGI-02
        logger.debug("[FO] shadow ate eval fail: %s", e)
        return None
