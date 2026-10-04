"""N-P0b VerificationRecord + 多阶段验证信号 + 分数化贝叶斯更新。

设计来源：千问 N-P0b 接口设计稿（2026-09-29）
核心公式：Δconf = clip((p − conf) / 4, −0.15, +0.10)
  - λ = N/3 → k = λ/(N+λ) = 1/4
  - 锚点 conf*=0.6 处 p=1→+0.1, p=0→−0.15 同时成立
  - 现网默认 conf=0.3，首步不精确匹配，靠安全带回退 clip
  - clip 到 [−0.15, +0.10] 保证永不跳出 legacy 包络

硬约束：
- HC-1a：独立模块
- FAIL-OPEN：全 abstain → 回退布尔路径
- 零回归：signals=None 走原路径
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

_VALID_VERDICTS = frozenset({"pass", "fail", "abstain"})

# 安全带回退边界（千问建议默认 ON）
_DELTA_MIN = -0.15
_DELTA_MAX = 0.10
# λ = N/3 → k = 1/4
_K = 0.25


@dataclass(frozen=True)
class VerificationSignal:
    """单维度验证信号输入 DTO。"""
    stage: str                          # cycle_consistency / factuality / applicability
    verdict: str                        # pass / fail / abstain
    verifier_id: str                    # 验证者标识（角色分离用）
    evidence_hash: str = ""             # 可审计证据哈希
    latency_ms: float = 0.0             # 验证耗时

    def __post_init__(self) -> None:
        if self.verdict not in _VALID_VERDICTS:
            raise ValueError(
                f"verdict 必须是 {_VALID_VERDICTS}，got {self.verdict!r}"
            )


@dataclass(frozen=True)
class VerificationRecord:
    """一次 verify 调用的完整证据记录（append-only 一等公民）。

    更正只能追加 CORRECTION 记录，不可修改本条。
    """
    memory_id: str
    signals: Tuple[VerificationSignal, ...]    # tuple 保证不可变
    weight_version: str                         # 权重版本（可重算）
    ts: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "signals": [asdict(s) for s in self.signals],
            "weight_version": self.weight_version,
            "ts": self.ts,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VerificationRecord":
        signals = tuple(
            VerificationSignal(**s) for s in d.get("signals", [])
        )
        return cls(
            memory_id=d["memory_id"],
            signals=signals,
            weight_version=d["weight_version"],
            ts=d.get("ts", time.time()),
            correlation_id=d.get("correlation_id"),
        )


@dataclass(frozen=True)
class VerificationOutcome:
    """verify 聚合结果（判定表输出）。"""
    memory_id: str
    path: str                          # "boolean" / "fractional" / "fallback"
    old_confidence: float
    new_confidence: float
    old_quality: str
    new_quality: str
    # 分数化路径字段
    p: Optional[float] = None
    n_active: int = 0
    has_fail: bool = False
    gate: str = "pass"                 # pass / blocked / fallback
    # 布尔路径字段
    success: Optional[bool] = None


# ---------------------------------------------------------------------------
# 聚合 p 计算
# ---------------------------------------------------------------------------

def compute_aggregated_p(
    signals: List[VerificationSignal],
) -> Tuple[Optional[float], int]:
    """计算加权前的原始通过率 p = pass / active。

    Returns:
        (p, n_active)：全 abstain 或空时 p=None（触发回退布尔路径）。
    """
    if not signals:
        return None, 0
    active = [s for s in signals if s.verdict != "abstain"]
    if not active:
        return None, 0
    n_pass = sum(1 for s in active if s.verdict == "pass")
    return n_pass / len(active), len(active)


# ---------------------------------------------------------------------------
# 分数化 Δconf
# ---------------------------------------------------------------------------

def compute_fractional_delta(p: float, conf: float) -> float:
    """计算分数化置信度增量，clip 到 [−0.15, +0.10]。

    Δconf_raw = (p − conf) / 4
    Δconf = clip(Δconf_raw, −0.15, +0.10)
    """
    raw = (p - conf) * _K
    return max(_DELTA_MIN, min(_DELTA_MAX, raw))


# ---------------------------------------------------------------------------
# quorum 判定
# ---------------------------------------------------------------------------

def resolve_quorum(
    verdicts: List[str],
    min_quorum: int = 1,
) -> Dict[str, Any]:
    """quorum + 弃权判定（千问 14 行判定表核心）。

    gate:
      - "fallback": 全 abstain → 回退布尔路径
      - "blocked": 有 fail 或 n_active < min_quorum
      - "pass": 全 pass 且 n_active >= min_quorum
    """
    active = [v for v in verdicts if v != "abstain"]
    n_active = len(active)
    has_fail = any(v == "fail" for v in active)

    if n_active == 0:
        return {"gate": "fallback", "p": None, "n_active": 0, "has_fail": False}

    n_pass = sum(1 for v in active if v == "pass")
    p = n_pass / n_active

    if has_fail or n_active < min_quorum:
        return {"gate": "blocked", "p": p, "n_active": n_active, "has_fail": has_fail}

    return {"gate": "pass", "p": p, "n_active": n_active, "has_fail": False}
