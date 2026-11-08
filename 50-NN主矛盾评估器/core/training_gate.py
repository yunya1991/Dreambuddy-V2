# R4-02: 50 训练门禁（SPEC §5：训练建议 -> 门禁裁决 -> 采纳/拒绝审计）。
#
# 建议制：门禁只输出采纳/拒绝裁决，不直接改 40/50 权重。
# 40 P5/P6 门禁不放宽：建议中含放宽 40 门禁内容直接拒绝。
# W6 冷启动期（cold_start）不得用于 A/B 结论：权重类建议在冷启动期拒绝。
# 权重类建议值必须在截断区间 [0.3, 1.5]。
# 审计落盘：采纳/拒绝记录 append-only（显式目录注入，测试隔离）。
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any

WEIGHT_MIN = 0.3
WEIGHT_MAX = 1.5

# 建议类型
TYPE_WEIGHTS = "weights"        # 50 权重类建议（W6 维度权重）
TYPE_STRATEGY = "strategy"      # 50 策略类建议
TYPE_MACRO = "macro"            # 40 宏观类建议（经 40 P5/P6 门禁，50 侧只审计）


class TrainingGate:
    # 50 训练门禁：裁决训练建议，输出采纳/拒绝 + 理由，不改权重。
    def __init__(self, audit_dir: str | Path | None = None):
        self._audit_path = Path(audit_dir) / "training_gate_audit.jsonl" if audit_dir else None
        if audit_dir:
            Path(audit_dir).mkdir(parents=True, exist_ok=True)

    def adjudicate(
        self,
        suggestion: dict[str, Any],
        w6_state: str = "cold_start",
    ) -> dict[str, Any]:
        # 裁决一条训练建议。返回 {accepted, reason_code, reason, suggestion_id}。
        sid = str(suggestion.get("suggestion_id") or "")
        stype = str(suggestion.get("type") or "")
        reasons: list[str] = []
        accepted = True

        # 1) 建议必须带 id 与类型
        if not sid:
            accepted = False
            reasons.append("missing_suggestion_id")
        if stype not in (TYPE_WEIGHTS, TYPE_STRATEGY, TYPE_MACRO):
            accepted = False
            reasons.append("unknown_suggestion_type")

        # 2) 40 P5/P6 不放宽：含放宽 40 门禁内容直接拒绝
        if suggestion.get("relax_40_gate"):
            accepted = False
            reasons.append("relax_40_gate_forbidden")

        # 3) W6 冷启动期：权重类建议拒绝（cold_start 不得用于 A/B 结论）
        if stype == TYPE_WEIGHTS and w6_state == "cold_start":
            accepted = False
            reasons.append("w6_cold_start_weights_rejected")

        # 4) 权重类建议值必须在截断区间
        if stype == TYPE_WEIGHTS and accepted:
            weights = suggestion.get("weights")
            if not isinstance(weights, dict) or not weights:
                accepted = False
                reasons.append("weights_payload_invalid")
            else:
                for k, v in weights.items():
                    try:
                        fv = float(v)
                    except (TypeError, ValueError):
                        accepted = False
                        reasons.append(f"weight_not_numeric:{k}")
                        continue
                    if fv < WEIGHT_MIN or fv > WEIGHT_MAX:
                        accepted = False
                        reasons.append(f"weight_out_of_band:{k}={fv}")

        result = {
            "suggestion_id": sid,
            "type": stype,
            "accepted": accepted,
            "reason_code": ";".join(reasons) if reasons else "ok",
            "reason": ";".join(reasons) if reasons else "all_gates_passed",
            "w6_state": w6_state,
            "adjudicated_ts": time.time(),
            "source": "50-training-gate",
        }
        self._audit(result)
        return result

    def _audit(self, result: dict[str, Any]) -> None:
        # 采纳/拒绝审计 append-only 落盘；目录未注入时跳过（内存裁决仍可用）。
        if self._audit_path is None:
            return
        try:
            with open(self._audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False))
                f.write(chr(10))
        except OSError:
            pass
