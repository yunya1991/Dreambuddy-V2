#!/usr/bin/env python3
"""黄金集评估器：只读，不伪造指标。

用法：
    python3 scripts/eval_golden.py --golden references/golden/dev.jsonl
    python3 scripts/eval_golden.py --golden a.jsonl --pred pred.jsonl --json

输入格式（JSONL，每行一个对象）：
    {"id": "g001", "content": "...", "label": "skill", "labeler": "A",
     "predicted": "skill", "confidence": 0.91}

- `label` 为人工标注；同一 `id` 出现两次且 `labeler` 不同即为双人标注；
- `predicted` / `confidence` 可写在任意一行（同 id 后写覆盖先写）；
- 也可用 `--pred` 提供独立预测文件，格式为 JSONL
  （含 id/predicted/confidence）或 {"id": {"predicted": ..., "confidence": ...}}。

指标：每类 P/R/F1、宏平均、准确率、高置信分组精确率、ECE（10 桶）、Cohen's κ。
阈值：高分组精确率 ≥ 0.90 或 ECE ≤ 0.15 视为达标。
退出码：0 达标 / 1 未达标 / 2 数据不足（需人工标注）/ 3 用法错误。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_BELOW = 1
EXIT_DATA = 2
EXIT_USAGE = 3

LABELS = ("skill", "doc", "memory", "session")
HIGH_CONFIDENCE = 0.80
HIGH_PRECISION_TARGET = 0.90
ECE_TARGET = 0.15
DEFAULT_BINS = 10


class EvalError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _read_jsonl(path: Path) -> list:
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvalError(EXIT_DATA, "无法读取黄金集：{}（{}）".format(path, exc)) from exc
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            row = json.loads(stripped)
        except ValueError as exc:
            raise EvalError(EXIT_DATA, "第 {} 行不是合法 JSON：{}".format(line_no, exc)) from exc
        if not isinstance(row, dict):
            raise EvalError(EXIT_DATA, "第 {} 行应为对象".format(line_no))
        rows.append(row)
    return rows


def _read_predictions(path: Path) -> dict:
    if not path.exists():
        raise EvalError(EXIT_DATA, "预测文件不存在：{}".format(path))
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise EvalError(EXIT_DATA, "预测 JSON 不可用：{}".format(exc)) from exc
        result = {}
        for key, value in (data or {}).items():
            if isinstance(value, dict):
                result[str(key)] = {
                    "predicted": value.get("predicted"),
                    "confidence": value.get("confidence"),
                }
            else:
                result[str(key)] = {"predicted": value, "confidence": None}
        return result

    result = {}
    for row in _read_jsonl(path):
        if "id" not in row:
            continue
        result[str(row["id"])] = {
            "predicted": row.get("predicted"),
            "confidence": row.get("confidence"),
        }
    return result


def _collect(rows, extra_preds: dict):
    reference, predictions, annotations = {}, {}, {}
    for row in rows:
        item_id = str(row.get("id") or "").strip()
        if not item_id:
            continue
        label = row.get("label")
        labeler = str(row.get("labeler") or "A")
        if label:
            annotations.setdefault(item_id, {})[labeler] = str(label)
            if item_id not in reference:
                reference[item_id] = str(label)
        if row.get("predicted"):
            predictions[item_id] = {
                "predicted": str(row["predicted"]),
                "confidence": row.get("confidence"),
            }
    for item_id, value in extra_preds.items():
        if value.get("predicted"):
            predictions[item_id] = value
    return reference, predictions, annotations


def _prf(reference: dict, predictions: dict, label: str) -> dict:
    tp = fp = fn = 0
    for item_id, gold in reference.items():
        pred = (predictions.get(item_id) or {}).get("predicted")
        if gold == label and pred == label:
            tp += 1
        elif gold != label and pred == label:
            fp += 1
        elif gold == label and pred != label:
            fn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "label": label,
        "support": tp + fn,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _kappa(annotations: dict) -> dict:
    pair_ids = [item_id for item_id, labels in annotations.items() if len(labels) >= 2]
    if not pair_ids:
        return {"value": None, "pairs": 0, "note": "需人工标注：缺少同一 id 的双人标注"}

    labelers = sorted({name for item_id in pair_ids for name in annotations[item_id]})
    left_name, right_name = labelers[0], labelers[1]
    left = [annotations[item_id][left_name] for item_id in pair_ids]
    right = [annotations[item_id][right_name] for item_id in pair_ids]
    total = len(pair_ids)
    observed = sum(1 for a, b in zip(left, right, strict=False) if a == b) / total

    left_counts, right_counts = {}, {}
    for value in left:
        left_counts[value] = left_counts.get(value, 0) + 1
    for value in right:
        right_counts[value] = right_counts.get(value, 0) + 1
    expected = sum(
        (left_counts.get(label, 0) / total) * (right_counts.get(label, 0) / total)
        for label in set(left_counts) | set(right_counts)
    )
    if expected >= 1.0:
        value = 1.0 if observed >= 1.0 else 0.0
    else:
        value = (observed - expected) / (1.0 - expected)
    return {
        "value": round(value, 4),
        "pairs": total,
        "labelers": [left_name, right_name],
        "observed_agreement": round(observed, 4),
        "expected_agreement": round(expected, 4),
        "note": "",
    }


def _calibration(reference: dict, predictions: dict, bins: int) -> dict:
    samples = []
    for item_id, gold in reference.items():
        entry = predictions.get(item_id) or {}
        confidence = entry.get("confidence")
        if entry.get("predicted") is None or confidence is None:
            continue
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            continue
        if not (0.0 <= confidence <= 1.0):
            continue
        samples.append((confidence, 1.0 if entry["predicted"] == gold else 0.0))

    if not samples:
        return {
            "ece": None,
            "bins": 0,
            "samples": 0,
            "high_precision": None,
            "high_count": 0,
            "note": "需人工标注：缺少 confidence，无法计算校准",
        }

    total = len(samples)
    bucket = {}
    for confidence, correct in samples:
        index = min(int(math.floor(confidence * bins)), bins - 1)
        entry = bucket.setdefault(index, {"confidence": 0.0, "correct": 0.0, "count": 0})
        entry["confidence"] += confidence
        entry["correct"] += correct
        entry["count"] += 1

    ece = 0.0
    details = []
    for index in sorted(bucket):
        entry = bucket[index]
        average_confidence = entry["confidence"] / entry["count"]
        accuracy = entry["correct"] / entry["count"]
        share = entry["count"] / total
        ece += abs(accuracy - average_confidence) * share
        details.append(
            {
                "bin": index,
                "count": entry["count"],
                "avg_confidence": round(average_confidence, 4),
                "accuracy": round(accuracy, 4),
            }
        )

    high = [correct for confidence, correct in samples if confidence >= HIGH_CONFIDENCE]
    high_precision = sum(high) / len(high) if high else None
    return {
        "ece": round(ece, 4),
        "bins": bins,
        "samples": total,
        "high_precision": round(high_precision, 4) if high_precision is not None else None,
        "high_count": len(high),
        "high_threshold": HIGH_CONFIDENCE,
        "details": details,
        "note": (
            "" if high else "高置信分组为空：没有 confidence ≥ {} 的预测".format(HIGH_CONFIDENCE)
        ),
    }


def evaluate(reference: dict, predictions: dict, annotations: dict, bins: int) -> dict:
    per_class = [_prf(reference, predictions, label) for label in LABELS]
    # 宏平均只统计真实出现过的类别（有标注或预测），避免空类别把均值拉低
    active = [item for item in per_class if item["support"] > 0 or item["tp"] + item["fp"] > 0]
    macro_f1 = sum(item["f1"] for item in active) / len(active) if active else 0.0

    correct = sum(
        1
        for item_id, gold in reference.items()
        if (predictions.get(item_id) or {}).get("predicted") == gold
    )
    accuracy = correct / len(reference) if reference else 0.0
    calibration = _calibration(reference, predictions, bins)

    high_ok = (
        calibration["high_precision"] is not None
        and calibration["high_precision"] >= HIGH_PRECISION_TARGET
    )
    ece_ok = calibration["ece"] is not None and calibration["ece"] <= ECE_TARGET

    if not predictions:
        status = "insufficient"
        note = "缺预测结果：需人工标注并运行预测后才能计算 P/R/F1"
    elif calibration["samples"] == 0:
        status = "insufficient"
        note = "缺 confidence：需人工标注并补充置信度"
    elif high_ok or ece_ok:
        status = "pass"
        note = ""
    else:
        status = "below_threshold"
        note = "高分组精确率 < {} 且 ECE > {}".format(HIGH_PRECISION_TARGET, ECE_TARGET)

    return {
        "schema_version": "1.0",
        "command": "eval_golden",
        "golden_items": len(reference),
        "predicted_items": len(predictions),
        "bins": bins,
        "metrics": {
            "per_class": per_class,
            "macro_f1": round(macro_f1, 4),
            "accuracy": round(accuracy, 4),
        },
        "calibration": {key: value for key, value in calibration.items() if key != "details"},
        "calibration_bins": calibration.get("details", []),
        "agreement": _kappa(annotations),
        "thresholds": {
            "high_precision": HIGH_PRECISION_TARGET,
            "ece": ECE_TARGET,
            "rule": "高分组精确率 ≥ 0.90 或 ECE ≤ 0.15",
        },
        "status": status,
        "note": note,
    }


def _fmt(value, pattern="{:.4f}", empty="—"):
    return empty if value is None else pattern.format(value)


def format_report(result: dict) -> str:
    metrics = result["metrics"]
    lines = [
        "认知管家 · 黄金集评估",
        "样本：{} 条（有预测 {} 条）".format(result["golden_items"], result["predicted_items"]),
        "",
        "类别        P       R      F1     支持",
    ]
    for item in metrics["per_class"]:
        lines.append(
            "{:<10} {:>7} {:>7} {:>7} {:>6}".format(
                item["label"],
                _fmt(item["precision"]),
                _fmt(item["recall"]),
                _fmt(item["f1"]),
                item["support"],
            )
        )
    lines.extend(
        [
            "",
            "宏平均 F1：{}".format(_fmt(metrics["macro_f1"])),
            "准确率：{}".format(_fmt(metrics["accuracy"])),
        ]
    )
    calibration = result["calibration"]
    lines.append(
        "高分组精确率：{}（n={}）".format(
            _fmt(calibration.get("high_precision")), calibration.get("high_count", 0)
        )
    )
    lines.append(
        "ECE：{}（{} 桶）".format(_fmt(calibration.get("ece")), calibration.get("bins", 0))
    )
    agreement = result["agreement"]
    lines.append(
        "Cohen's κ：{}（{} 对双标注）{}".format(
            _fmt(agreement.get("value")),
            agreement.get("pairs", 0),
            "  " + agreement["note"] if agreement.get("note") else "",
        )
    )
    status_text = {
        "pass": "达标",
        "below_threshold": "未达标",
        "insufficient": "数据不足",
    }
    lines.append("")
    lines.append("结论：{}".format(status_text.get(result["status"], result["status"])))
    if result.get("note"):
        lines.append("说明：{}".format(result["note"]))
    return "\n".join(lines)


def _exit_code(status: str) -> int:
    return {"pass": EXIT_OK, "below_threshold": EXIT_BELOW}.get(status, EXIT_DATA)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eval_golden",
        description="认知管家黄金集评估（只读，不伪造指标）",
    )
    parser.add_argument("--golden", required=True, help="黄金集 JSONL 路径")
    parser.add_argument("--pred", default=None, help="可选：独立预测 JSONL / JSON")
    parser.add_argument("--bins", type=int, default=DEFAULT_BINS, help="ECE 分桶数")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.bins <= 0:
        print("错误：--bins 必须大于 0", file=sys.stderr)
        return EXIT_USAGE
    golden = Path(args.golden).expanduser().resolve()
    if not golden.exists():
        print("错误：黄金集不存在：{}（需人工标注）".format(golden), file=sys.stderr)
        return EXIT_DATA

    try:
        rows = _read_jsonl(golden)
        extra_preds = _read_predictions(Path(args.pred).expanduser().resolve()) if args.pred else {}
    except EvalError as exc:
        print("错误：{}".format(exc.message), file=sys.stderr)
        return exc.code

    reference, predictions, annotations = _collect(rows, extra_preds)
    if not reference:
        print("错误：黄金集没有人工标注（label 字段），需人工标注", file=sys.stderr)
        return EXIT_DATA

    result = evaluate(reference, predictions, annotations, args.bins)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else format_report(result))
    return _exit_code(result["status"])


if __name__ == "__main__":
    sys.exit(main())
