"""trade-exec paper 样本消费端（execution_sample_loader Phase 0）契约测试。

覆盖：
  - 文件缺失 → FAIL-OPEN 返回空
  - order_filled → reward = realized_pnl / notional（截断 ±3%）
  - risk_rejected / signal_skipped → 固定惩罚 / 零奖励 + label
  - 同一事件重复行去重
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dreambuddy_evolution.core.execution_sample_loader import (  # noqa: E402
    RISK_REJECT_PENALTY,
    build_dataset,
    to_policy_rows,
    write_policy_rows,
)


def _write(tmp_path: Path, records) -> Path:
    p = tmp_path / "samples.jsonl"
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )
    return p


def test_missing_file_returns_empty(tmp_path):
    ds = build_dataset(tmp_path / "none.jsonl")
    assert ds["rows"] == []
    assert ds["counts"] == {}


def test_order_filled_reward(tmp_path):
    path = _write(
        tmp_path,
        [
            {
                "ts": "2026-11-05T00:00:00+00:00",
                "kind": "order_filled",
                "trace_id": "t1",
                "inst_id": "BTC-USDT-SWAP",
                "side": "buy",
                "size": 0.01,
                "avg_px": 80000.0,
                "realized_pnl": 2.4,
                "confidence": 0.8,
                "mode": "paper",
            }
        ],
    )
    ds = build_dataset(path)
    assert ds["counts"] == {"order_filled": 1}
    row = ds["rows"][0]
    assert row["action"] == "buy"
    assert row["label"] == "filled"
    # 2.4 / (0.01*80000=800) = 0.003
    assert row["reward"] == 0.003
    assert row["meta"]["trace_id"] == "t1"


def test_reject_and_skip_labels():
    rows = to_policy_rows(
        [
            {
                "ts": "a",
                "kind": "risk_rejected",
                "inst_id": "ETH-USDT-SWAP",
                "side": "sell",
                "reason_code": "max_position",
            },
            {"ts": "b", "kind": "signal_skipped", "signal_id": "s1", "reason": "duplicate"},
        ]
    )
    assert rows[0]["reward"] == RISK_REJECT_PENALTY
    assert rows[0]["label"] == "risk_blocked"
    assert rows[1]["reward"] == 0.0
    assert rows[1]["label"] == "duplicate"


def test_duplicate_rows_deduped():
    rec = {
        "ts": "2026-11-05T00:00:00+00:00",
        "kind": "signal_skipped",
        "trace_id": "dup",
        "signal_id": "s1",
        "reason": "neutral",
    }
    rows = to_policy_rows([rec, dict(rec)])
    assert len(rows) == 1


def test_write_policy_rows_is_idempotent(tmp_path):
    samples = _write(
        tmp_path,
        [
            {
                "ts": "2026-11-05T00:00:00+00:00",
                "kind": "order_filled",
                "trace_id": "w1",
                "inst_id": "ETH-USDT-SWAP",
                "side": "sell",
                "size": 0.2,
                "avg_px": 2400.0,
                "realized_pnl": -1.2,
            }
        ],
    )
    out = tmp_path / "policy.jsonl"
    first = write_policy_rows(samples, out)
    second = write_policy_rows(samples, out)
    assert first["written"] == 1
    assert second["written"] == 0
    assert second["skipped"] == 1
