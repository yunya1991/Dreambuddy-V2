#!/usr/bin/env python3
"""Enrich backtest trades — 推断 exit_reason 并补充 tier 字段

读取 .workbuddy/trade_index/backtest_trades.jsonl（3822 条记录，全部
exit_reason="time"，无 tier 字段），对每条记录进行富化：

  - 根据 pnl_pct 推断 exit_reason：
      pnl_pct >  0.01 → "tp_hit"        (盈利交易)
      pnl_pct < -0.01 → "sl_hit"        (亏损交易)
      |pnl_pct| <= 0.01 → "timeout_loss" (中性)
  - 补充 tier: "standard"（默认档位）
  - 输出到 .workbuddy/trade_index/backtest_trades_enriched.jsonl

FAIL-OPEN：单条记录解析失败 → 跳过并告警，不阻塞整体管线。

使用方式：
  python3 enrich_backtest_trades.py
  python3 enrich_backtest_trades.py --input <path> --output <path>
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 项目根目录（scripts → dreambuddy_evolution → 23-四层... → 项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_INPUT = str(PROJECT_ROOT / ".workbuddy" / "trade_index" / "backtest_trades.jsonl")
DEFAULT_OUTPUT = str(
    PROJECT_ROOT / ".workbuddy" / "trade_index" / "backtest_trades_enriched.jsonl"
)

# exit_reason 推断阈值
TP_THRESHOLD = 0.01  # pnl_pct > 1% → tp_hit
SL_THRESHOLD = -0.01  # pnl_pct < -1% → sl_hit


def infer_exit_reason(pnl_pct: float) -> str:
    """根据 pnl_pct 推断 exit_reason

    Args:
        pnl_pct: 盈亏比例（如 0.0725 表示 +7.25%）

    Returns:
        "tp_hit" | "sl_hit" | "timeout_loss"
    """
    if pnl_pct > TP_THRESHOLD:
        return "tp_hit"
    if pnl_pct < SL_THRESHOLD:
        return "sl_hit"
    return "timeout_loss"


def enrich_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """对单条交易记录进行富化

    - 推断 exit_reason（覆盖原始 "time"）
    - 补充 tier 字段（若不存在则设为 "standard"）
    - 保留其他字段不变
    """
    pnl_pct = float(record.get("pnl_pct", 0) or 0)
    record["exit_reason"] = infer_exit_reason(pnl_pct)
    if not record.get("tier"):
        record["tier"] = "standard"
    return record


def enrich_file(input_path: str, output_path: str) -> int:
    """富化整个 jsonl 文件

    FAIL-OPEN：单行解析失败 → 跳过并告警。

    Returns:
        成功写入的记录数
    """
    in_path = Path(input_path)
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    with open(in_path, "r", encoding="utf-8") as fin, open(
        out_path, "w", encoding="utf-8"
    ) as fout:
        for lineno, raw in enumerate(fin, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"record is {type(record).__name__}, expected dict")
                enriched = enrich_record(record)
                fout.write(json.dumps(enriched, ensure_ascii=False) + "\n")
                written += 1
            except Exception as exc:
                logger.warning(
                    "跳过 %s 第 %d 行 (FAIL-OPEN): %s", in_path.name, lineno, exc
                )
                skipped += 1

    logger.info(
        "富化完成: 写入 %d 条 → %s (跳过 %d 条)", written, out_path, skipped
    )
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="富化 backtest 交易记录：推断 exit_reason + 补充 tier"
    )
    parser.add_argument(
        "--input", default=DEFAULT_INPUT, help="输入 jsonl 路径"
    )
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT, help="输出 jsonl 路径"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
    )

    count = enrich_file(args.input, args.output)
    print(f"富化完成: {count} 条记录 → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
