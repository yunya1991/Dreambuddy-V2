"""consume_48_feedback.py — 40 域 48 反馈消费端（G3 接线）。

职责（SPEC-NN-FEEDBACK-GATEWAY §3.1）：
  1. 通过 40 侧适配器（adapter_48_feedback）读取 48 反馈并挂载 payload；
  2. 消费证据落盘 `40/nn_feedback_consumption.json`（供审计与 G3 验收）；
  3. 双读校验：直读现算 vs 48 通道文件，结果持久化到消费证据中。

纪律：FAIL-OPEN（开关关/文件缺失时记录 skipped 并正常退出，不中断管线）。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE = os.environ.get("DREAMBUDDY_ROOT") or str(Path(__file__).resolve().parents[2])
D40 = os.path.join(_BASE, "40-周期神经网络系统")
D48 = os.path.join(_BASE, "48-涌现架构")
OUT_PATH = os.path.join(D40, "nn_feedback_consumption.json")

sys.path.insert(0, os.path.join(D40, "scripts"))
sys.path.insert(0, os.path.join(D48, "metrics"))

import adapter_48_feedback as adapter  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel(p: str) -> str:
    return os.path.relpath(p, _BASE)


def main() -> int:
    record: dict = {
        "schema_version": "nn_feedback_consumption.v0.1",
        "generated_at": _now_iso(),
        "enable_40_via_48": adapter.enabled(),
    }

    if not adapter.enabled():
        record["status"] = "skipped"
        record["reason"] = "ENABLE_40_VIA_48 off (FAIL-OPEN, 40 直读)"
    else:
        payload: dict = {}
        adapter.attach_to_payload(payload)
        fb = payload.get("_feedback_48")
        if fb is None:
            record["status"] = "degraded"
            record["reason"] = "40_feedback.json 不可读或解析失败（FAIL-OPEN）"
        else:
            # --- 双读校验：直读现算 vs 48 通道文件 ---
            dual_read = None
            try:
                import nn_feedback_gateway as gw  # noqa: E402
                import training_events as te  # noqa: E402

                events = te.load_events()
                direct_fb = gw.build_feedback(events, factor_prior=gw.load_factor_prior())
                direct = {
                    "n_events": direct_fb["source_window"]["n_events"],
                    "n_complete": direct_fb["quality"]["n_complete"],
                    "n_incomplete": direct_fb["quality"]["n_incomplete"],
                    "join_coverage": direct_fb["quality"]["join_coverage"],
                    "n_contradiction_priors": len(direct_fb["contradiction_priors"]),
                    "n_training_suggestions": len(direct_fb["training_suggestions"]),
                }
                via48 = {
                    "n_events": fb["source_window"]["n_events"],
                    "n_complete": fb["quality"]["n_complete"],
                    "n_incomplete": fb["quality"]["n_incomplete"],
                    "join_coverage": fb["quality"]["join_coverage"],
                    "n_contradiction_priors": len(fb["contradiction_priors"]),
                    "n_training_suggestions": len(fb["training_suggestions"]),
                }
                dual_read = gw.verify_dual_read(direct, via48, tolerance=0.1)
            except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
                logger.warning("双读校验失败（降级记录）: %s", exc)
                dual_read = {"consistent": None, "error": str(exc)}

            record["status"] = "consumed"
            record["feedback"] = {
                "gateway_version": fb.get("gateway_version"),
                "data_version": fb.get("data_version"),
                "n_events": fb["source_window"]["n_events"],
                "n_training_suggestions": len(fb.get("training_suggestions", [])),
            }
            record["dual_read"] = dual_read

    record["out"] = _rel(OUT_PATH)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT_PATH)
    print(json.dumps({"status": record["status"], "out": record["out"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
