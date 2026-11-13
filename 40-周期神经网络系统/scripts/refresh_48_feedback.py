"""refresh_48_feedback.py — 48→40 反馈网关产物刷新（G13）。

在 40 日更流水线中先于 consume_48_feedback.py 执行：
  50/runtime/decisions.jsonl → TrainingEvent 回填 → 48/events/nn_feedback/40_feedback.json

失败即中止流水线（下游消费陈旧产物比停跑更危险）。
"""

import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("DREAMBUDDY_ROOT", Path(__file__).resolve().parents[2]))
GATEWAY_DIR = ROOT / "48-涌现架构" / "metrics"
sys.path.insert(0, str(GATEWAY_DIR))

from nn_feedback_gateway import main as gateway_main  # noqa: E402


def main() -> int:
    return gateway_main([])


if __name__ == "__main__":
    raise SystemExit(main())
