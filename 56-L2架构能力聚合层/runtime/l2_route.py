"""认知裁决 → L2 路线选择（SPEC-v1.4 §3.4/§4.1、SPEC-56 IF-1 / GAP-13）。

裁决层第三个动作：L1 拒绝之后，由 `cognition_signal`（覆盖度 + 域内外 verdict）
决定 L2 走哪条路线，并把结果作为 `cognition_signal.l2_route` 透传。

路线枚举（IF-L2-2：禁止自由文本表达路线）：
  - `retrieval_augmented`：域内或覆盖度足够 → 以 L1 已取事实 + 检索增强为主，成本低；
  - `deep_reasoning`：域外或覆盖度不足 → 深度推理，成本高。

阈值：`COVERAGE_THRESHOLD = 0.65`，与 SPEC-v1.4 §3.4 的 C3/C4 裁决阈值、
`34-前端应用训练系统/core/route_confidence.py::THRESHOLD_HIGH` 同值——
全系统只有这一处裁决数值，禁止再引入 0.66 等其他口径。

失败形态：FAIL-OPEN（SPEC-v1.4 §5「认知裁决异常 → 默认 unknown + L2」），
信号缺失/畸形一律回落 `unknown + deep_reasoning`，不得硬性拒答。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

COVERAGE_THRESHOLD = 0.65
VERDICTS = ("in_scope", "unknown", "out_of_scope")
L2_ROUTES = ("retrieval_augmented", "deep_reasoning")
DEFAULT_SOURCE = "capability_catalog"


def _fail_open() -> Dict[str, Any]:
    """裁决不可用时回落 L2（unknown + deep_reasoning），不拒答。"""
    return {
        "coverage": 0.0,
        "source": DEFAULT_SOURCE,
        "verdict": "unknown",
        "l2_route": "deep_reasoning",
    }


def decide_cognition_route(route_signal: Any) -> Dict[str, Any]:
    """消费 `route_signal`，返回闭合四字段的 `cognition_signal`。

    - `in_scope` → `retrieval_augmented`
    - `unknown` 且 coverage ≥ 0.65 → `retrieval_augmented`
    - `unknown` 且 coverage < 0.65 / `out_of_scope` → `deep_reasoning`
    """
    signal = route_signal.get("cognition_signal") if isinstance(route_signal, Mapping) else None
    if not isinstance(signal, Mapping):
        return _fail_open()

    coverage = signal.get("coverage")
    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)):
        return _fail_open()
    coverage = float(coverage)
    if not 0.0 <= coverage <= 1.0:  # NaN 也在此拦下
        return _fail_open()

    verdict = signal.get("verdict", "unknown")
    if verdict not in VERDICTS:
        return _fail_open()

    source = signal.get("source") or DEFAULT_SOURCE
    use_retrieval = verdict == "in_scope" or (
        verdict == "unknown" and coverage >= COVERAGE_THRESHOLD
    )
    return {
        "coverage": coverage,
        "source": str(source),
        "verdict": verdict,
        "l2_route": "retrieval_augmented" if use_retrieval else "deep_reasoning",
    }
