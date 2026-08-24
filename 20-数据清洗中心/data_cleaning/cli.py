"""dc-clean CLI（Spec§C7.2）。

三个子命令：
  1) `dc-clean clean -i <parquet/csv/json> -o <output>` — 跑 Silver 链（输入为 DF，不含 DataRecord）
  2) `dc-clean trace -i <trace.json> [--stage X]` — 审计清洗痕迹（CleaningTrace JSON 化输出）
  3) `dc-clean audit <silver_dir> [--csv]` — 汇总某目录下所有 Silver 审计的 质量报告

CLI 用 argparse，避免外部依赖。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd


def _read_df(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    ext = os.path.splitext(path)[1].lower()
    if ext in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if ext == ".csv":
        return pd.read_csv(path)
    if ext in {".json", ".ndjson"}:
        return pd.read_json(path, lines=ext == ".ndjson")
    raise ValueError(f"不支持的输入格式: {ext}（支持 csv/parquet/json/ndjson）")


def _write_df(df: pd.DataFrame, path: str) -> None:
    ext = os.path.splitext(path)[1].lower()
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    if ext in {".parquet", ".pq"}:
        df.to_parquet(path, index=False)
    elif ext == ".csv":
        df.to_csv(path, index=False)
    elif ext == ".json":
        df.to_json(path, orient="records", force_ascii=False, indent=2)
    elif ext == ".ndjson":
        df.to_json(path, orient="records", lines=True, force_ascii=False)
    else:
        raise ValueError(f"不支持的输出格式: {ext}")


def cmd_clean(args: argparse.Namespace) -> int:
    """把一个已导出 DF 文件跑 Silver 链（4 Cleaner）并输出。"""
    from data_cleaning.cleaners.dedup_align import DedupAlignCleaner
    from data_cleaning.cleaners.missing_imputer import MissingImputer
    from data_cleaning.cleaners.outlier_filter import Outlier3LFilter
    from data_cleaning.cleaners.unit_normalizer import UnitNormalizer
    from data_cleaning.contract import CleaningTrace

    df = _read_df(args.input)
    trace = CleaningTrace()
    print(f"[dc-clean] IN rows={len(df)} cols={list(df.columns)[:8]}...", file=sys.stderr)

    ts_col = args.timestamp_col or "timestamp"
    df, _ = DedupAlignCleaner(
        target_freq=args.freq,
        ffill_limit=int(args.ffill_limit),
        timestamp_col=ts_col,
    ).clean(df, trace)
    df, _ = Outlier3LFilter().clean(df, trace)
    df, _ = MissingImputer(ffill_limit=int(args.ffill_limit)).clean(df, trace)
    df, _ = UnitNormalizer().clean(df, trace)

    # 输出结果 DF
    _write_df(df, args.output)
    print(f"[dc-clean] OUT rows={len(df)} clipped={trace.total_clipped} "
          f"imputed={trace.total_imputed} → {args.output}", file=sys.stderr)
    # 可选 dump trace
    if args.dump_trace:
        p = Path(args.dump_trace)
        p.write_text(_trace_to_json(trace), encoding="utf-8")
        print(f"[dc-clean] trace → {p}", file=sys.stderr)
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    """把 CleaningTrace JSON dump（由 Pipeline.clean 或 cmd_clean dump_trace 产出）打印为可读形式。"""
    raw = Path(args.input).read_text(encoding="utf-8")
    data = json.loads(raw)
    actions = data.get("actions", [])
    if args.stage:
        actions = [a for a in actions if args.stage.lower() in str(a.get("step", "")).lower()]
    cols = ["step", "input_rows", "output_rows", "clipped_count", "imputed_count",
            "blocked_count", "note"]
    rows_df = pd.DataFrame(actions)[cols] if actions else pd.DataFrame(columns=cols)
    if args.format == "table":
        print(rows_df.to_string(index=False))
    else:
        print(rows_df.to_json(orient="records", force_ascii=False, indent=2))
    # summary
    print(f"\n-- summary: actions={len(actions)} "
          f"total_clipped={rows_df['clipped_count'].sum() if len(rows_df) else 0} "
          f"total_imputed={rows_df['imputed_count'].sum() if len(rows_df) else 0}",
          file=sys.stderr)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """给定 Silver 产出目录（含多个 trace.json），汇总失败/拦截。"""
    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"目录不存在: {directory}", file=sys.stderr)
        return 2
    files = sorted(directory.rglob("*trace*.json"))
    if not files:
        print(f"[audit] 0 trace 文件 in {directory}", file=sys.stderr)
        return 0
    summary = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            summary.append({"file": str(f), "error": str(exc)})
            continue
        actions = data.get("actions", [])
        summary.append({
            "file": str(f),
            "actions": len(actions),
            "clipped": sum(a.get("clipped_count", 0) for a in actions),
            "imputed": sum(a.get("imputed_count", 0) for a in actions),
            "blocked": sum(a.get("blocked_count", 0) for a in actions),
            "gate_pass": "".join(sorted({
                "F" if "pass=False" in a.get("note", "") else ""
                for a in actions if a.get("step") == "QualityGate"
            })) or "T",
        })
    df = pd.DataFrame(summary)
    if args.csv:
        print(df.to_csv(index=False))
    else:
        print(df.to_string(index=False))
    return 0


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _trace_to_json(trace) -> str:
    actions = []
    for a in trace.actions:
        actions.append({
            "step": a.step,
            "input_rows": int(a.input_rows),
            "output_rows": int(a.output_rows),
            "clipped_count": int(a.clipped_count),
            "imputed_count": int(a.imputed_count),
            "blocked_count": int(getattr(a, "blocked_count", 0)),
            "note": a.note,
        })
    return json.dumps({
        "started_at": str(getattr(trace, "started_at", "")),
        "finished_at": str(getattr(trace, "finished_at", "")),
        "actions": actions,
    }, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dc-clean", description="Silver 数据清洗 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("clean", help="对 DF 文件跑 Silver 链 (clean → DF 文件)")
    c.add_argument("-i", "--input", required=True, help="输入：csv/parquet/json/ndjson")
    c.add_argument("-o", "--output", required=True, help="输出：csv/parquet/json/ndjson")
    c.add_argument("--freq", default="1h", help="DedupAlign target_freq（默认 1h）")
    c.add_argument("--ffill-limit", default=5, type=int, help="ffill limit（默认 5）")
    c.add_argument("--timestamp-col", default=None, help="timestamp 列名（默认自动识别）")
    c.add_argument("--dump-trace", default=None, help="同时把 CleaningTrace 写到此 JSON 路径")
    c.set_defaults(func=cmd_clean)

    t = sub.add_parser("trace", help="打印清洗 trace")
    t.add_argument("-i", "--input", required=True, help="trace.json 路径")
    t.add_argument("--stage", default=None, help="按步骤名过滤（如 DedupAlign）")
    t.add_argument("-f", "--format", choices=["table", "json"], default="table")
    t.set_defaults(func=cmd_trace)

    a = sub.add_parser("audit", help="批量审计 Silver 产出目录下的 trace")
    a.add_argument("dir", help="包含 *trace*.json 的目录")
    a.add_argument("--csv", action="store_true", help="CSV 格式输出")
    a.set_defaults(func=cmd_audit)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n[dc-clean] interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"[dc-clean] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
