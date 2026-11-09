# R4-03: 48 反馈样本写入适配器（50 决策/执行数据 -> 48，SPEC §5 独立进化链路）。
#
# 零侵入：不修改 48 层任何文件。
# 降级模式：48 训练网关未就绪（SPEC §11 预案），反馈样本先写入 50 层本地缓冲
# （显式目录注入），预留 48 写入钩子，就绪后可回放。
# 样本 append-only + 幂等（sample_id 去重）；任何异常 fail-safe 不阻断决策链路。
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def build_feedback_sample(
    decision: dict[str, Any],
    risk_result: dict[str, Any] | None = None,
    paca_result: dict[str, Any] | None = None,
    exec_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # 组装反馈样本：决策字段 + 三层接线结果摘要。
    exec_receipt = (exec_result or {}).get("receipt") or {}
    return {
        "sample_id": str(decision.get("signal_id") or ""),
        "decision_id": decision.get("signal_id"),
        "symbol": decision.get("symbol"),
        "direction": decision.get("direction"),
        "confidence": decision.get("confidence"),
        "position_pct": decision.get("position_pct"),
        "shadow": decision.get("shadow", True),
        "risk": (
            {
                "passed": (risk_result or {}).get("passed"),
                "reason_code": (risk_result or {}).get("reason_code"),
                "position_modifier": (risk_result or {}).get("position_modifier"),
            }
            if risk_result
            else None
        ),
        "paca": (
            {
                "ok": (paca_result or {}).get("ok"),
                "final_position_pct": ((paca_result or {}).get("advice") or {}).get(
                    "final_position_pct"
                ),
                "fallback_used": ((paca_result or {}).get("advice") or {}).get("fallback_used"),
            }
            if paca_result
            else None
        ),
        "exec": (
            {
                "ok": (exec_result or {}).get("ok"),
                "parent_id": exec_receipt.get("parent", {}).get("parent_id"),
                "audit_status": exec_receipt.get("_audit_status"),
                "fail_open_triggered": exec_receipt.get("fail_open", {}).get("triggered"),
            }
            if exec_result
            else None
        ),
        "created_ts": time.time(),
        "source": "50-nn",
        "dest": "48-emergence",
        "delivery": "buffered",  # buffered=本地缓冲（48 未就绪）；delivered=已投递 48
    }


class FeedbackWriter:
    # 反馈样本写入器：48 钩子优先；未注入钩子时降级本地缓冲（append-only + 幂等）。
    def __init__(self, buffer_dir: str | Path | None = None, sink: Any = None):
        # sink：48 就绪后注入的写入钩子（callable(sample) -> bool）；None 时走本地缓冲。
        self._buffer_path = Path(buffer_dir) / "feedback_samples.jsonl" if buffer_dir else None
        if buffer_dir:
            Path(buffer_dir).mkdir(parents=True, exist_ok=True)
        self._sink = sink
        self._seen_ids: set[str] = set()
        if self._buffer_path and self._buffer_path.exists():
            for line in self._buffer_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    sid = json.loads(line).get("sample_id")
                    if sid:
                        self._seen_ids.add(str(sid))
                except ValueError:
                    continue

    def write(self, sample: dict[str, Any]) -> dict[str, Any]:
        # 写入一条反馈样本。返回 {written, deduped, delivery, reason}。
        try:
            sid = str(sample.get("sample_id") or "")
            if not sid:
                return {
                    "written": False,
                    "deduped": False,
                    "delivery": "none",
                    "reason": "missing_sample_id",
                }
            if sid in self._seen_ids:
                return {
                    "written": False,
                    "deduped": True,
                    "delivery": "none",
                    "reason": "duplicate_sample_id",
                }
            # 48 钩子优先
            if self._sink is not None:
                delivered = bool(self._sink(sample))
                if delivered:
                    self._seen_ids.add(sid)
                    return {
                        "written": True,
                        "deduped": False,
                        "delivery": "delivered",
                        "reason": "ok",
                    }
                return {
                    "written": False,
                    "deduped": False,
                    "delivery": "none",
                    "reason": "sink_rejected",
                }
            # 降级：本地缓冲
            if self._buffer_path is None:
                return {
                    "written": False,
                    "deduped": False,
                    "delivery": "none",
                    "reason": "no_buffer_no_sink",
                }
            payload = dict(sample)
            payload["delivery"] = "buffered"
            with open(self._buffer_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False))
                f.write(chr(10))
            self._seen_ids.add(sid)
            return {"written": True, "deduped": False, "delivery": "buffered", "reason": "ok"}
        except Exception as exc:
            return {
                "written": False,
                "deduped": False,
                "delivery": "none",
                "reason": f"feedback_writer_exception:{exc}",
            }

    def replay_to_sink(self, sink: Any) -> dict[str, Any]:
        # 回放：48 就绪后把本地缓冲样本重放到 48 钩子（幂等，成功后标记 delivered）。
        if self._buffer_path is None or not self._buffer_path.exists():
            return {"replayed": 0, "failed": 0}
        replayed = 0
        failed = 0
        lines = [
            ln for ln in self._buffer_path.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        for line in lines:
            try:
                sample = json.loads(line)
            except ValueError:
                failed += 1
                continue
            try:
                if bool(sink(sample)):
                    replayed += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        return {"replayed": replayed, "failed": failed}
