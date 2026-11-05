"""execution_sample_loader.py — trade-exec MCP paper 样本消费端（Phase 0）

生产端：mcp_shells/l0_trade_exec/server.py::_emit_sample → ml_data/samples.jsonl
消费端：本模块把三类执行事件归一化为「执行策略」训练行，供后续 executor agent 训练。

设计边界：
  - 独立于 6 域 DomainCouplingHead（15 对耦合矩阵维度不变，不并入 domain_states）
  - 只读 samples.jsonl，不写生产账本、不触行情

reward 口径（paper 模式，非实盘）：
  order_filled   → realized_pnl / notional，截断 ±REWARD_CLIP
  risk_rejected  → RISK_REJECT_PENALTY（固定风控惩罚）
  signal_skipped → 0.0（未执行，label 标注 reason）
FAIL-OPEN：文件缺失 / 坏行 → 跳过，不 crash。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SAMPLES_PATH = Path(
    os.environ.get("TRADE_EXEC_SAMPLE_PATH")
    or REPO_ROOT / "mcp_shells" / "l0_trade_exec" / "ml_data" / "samples.jsonl"
)

REWARD_CLIP = 0.03
RISK_REJECT_PENALTY = -0.005


def load_samples(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """读取 JSONL 样本；缺失或坏行静默跳过（FAIL-OPEN）。"""
    p = Path(path or DEFAULT_SAMPLES_PATH)
    if not p.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _fill_reward(rec: Dict[str, Any]) -> float:
    try:
        notional = float(rec.get("size") or 0.0) * float(rec.get("avg_px") or 0.0)
        pnl = float(rec.get("realized_pnl") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if notional <= 0:
        return 0.0
    return max(-REWARD_CLIP, min(REWARD_CLIP, pnl / notional))


def _dedupe_key(rec: Dict[str, Any]) -> tuple:
    return (
        rec.get("trace_id", ""),
        rec.get("kind", ""),
        rec.get("ts", ""),
        rec.get("inst_id", ""),
        rec.get("signal_id", ""),
        rec.get("side", ""),
    )


def to_policy_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """事件样本 → 执行策略训练行（同一事件重复落盘只保留一条）。"""
    out: List[Dict[str, Any]] = []
    seen = set()
    for rec in records:
        key = _dedupe_key(rec)
        if key in seen:
            continue
        seen.add(key)

        kind = rec.get("kind", "")
        if kind == "order_filled":
            action = rec.get("side") or "unknown"
            reward = _fill_reward(rec)
            label = "filled"
        elif kind == "risk_rejected":
            action, reward, label = "reject", RISK_REJECT_PENALTY, "risk_blocked"
        elif kind == "signal_skipped":
            action, reward, label = "skip", 0.0, str(rec.get("reason") or "skipped")
        else:
            continue

        out.append(
            {
                "input": {
                    "kind": kind,
                    "inst_id": rec.get("inst_id") or rec.get("symbol") or "",
                    "side": rec.get("side") or rec.get("direction") or "",
                    "size": rec.get("size"),
                    "confidence": rec.get("confidence"),
                    "slippage_bps": rec.get("slippage_bps"),
                    "risk_level": rec.get("risk_level"),
                },
                "action": action,
                "reward": round(reward, 8),
                "label": label,
                "meta": {
                    "trace_id": rec.get("trace_id", ""),
                    "ts": rec.get("ts", ""),
                    "mode": rec.get("mode", "paper"),
                },
            }
        )
    return out


def build_dataset(path: Optional[Path] = None) -> Dict[str, Any]:
    """读取 + 归一化，返回 {rows, counts, source}。"""
    records = load_samples(path)
    rows = to_policy_rows(records)
    counts: Dict[str, int] = {}
    for rec in records:
        k = str(rec.get("kind", ""))
        counts[k] = counts.get(k, 0) + 1
    return {"rows": rows, "counts": counts, "source": str(path or DEFAULT_SAMPLES_PATH)}


DEFAULT_POLICY_OUT = (
    REPO_ROOT
    / "23-四层闭环自进化交易架构"
    / "dreambuddy_evolution"
    / "data"
    / "execution_policy_training.jsonl"
)


def _row_key(row: Dict[str, Any]) -> tuple:
    return (
        row["meta"]["trace_id"],
        row["meta"]["ts"],
        row["label"],
        row["input"]["inst_id"],
        row["input"]["side"],
    )


def write_policy_rows(
    samples_path: Optional[Path] = None, out_path: Optional[Path] = None
) -> Dict[str, Any]:
    """增量落盘执行策略训练行（按事件去重，可重复运行）。"""
    ds = build_dataset(samples_path)
    out = Path(out_path or os.environ.get("EXECUTION_POLICY_TRAINING_PATH") or DEFAULT_POLICY_OUT)
    existing = set()
    if out.exists():
        existing = {_row_key(r) for r in load_samples(out)}
    new_rows = [r for r in ds["rows"] if _row_key(r) not in existing]
    if new_rows:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "a", encoding="utf-8") as f:
            for row in new_rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {
        "written": len(new_rows),
        "skipped": len(ds["rows"]) - len(new_rows),
        "source": ds["source"],
        "out": str(out),
    }


def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description="trade-exec paper 样本 → 执行策略训练行")
    ap.add_argument("--samples", default=None, help="samples.jsonl 路径")
    ap.add_argument("--out", default=None, help="输出 execution_policy_training.jsonl")
    args = ap.parse_args(argv)
    res = write_policy_rows(args.samples, args.out)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
