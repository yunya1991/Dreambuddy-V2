# -*- coding: utf-8 -*-
"""点亮阈值分位标定（SPEC-54-L1交易层 §5.3 / B-LT7 / LTL-16 / LT-AC12）。

口径（硬约束）：

  - `lit_pct = p70`、`warm_pct = p40`，统计区间默认 `--since 2023-11-01`；
  - **默认 `--aggregate row`（LTL-16 定稿口径，2026-11-15 用户选择）**：样本为
    **行级合成强度** `lights.rows[].strength`（= `Σ lw·axis / Σ participating lw`）。
    标定统计对象是行级强度；分档消费位置是各轴 `_classify` 与前端行级强度条，
    三者共用同一组绝对阈值，但不承诺各轴自然呈现相同的 p70/p40 比例。
    四轴量纲不一致（`inertia` 是 3 档序数，只能取
    `{1.0, 0.4, 0.0}`）时，池化轴分布会被高权重满值原子抬高，行级合成不受此偏；
  - `--aggregate axis` 为旧口径（四轴 `strength` 池化），只用于横向对照，**不再回写**；
  - 只消费既有事实：输入是 [visual_overview.py](../../3.1-FRONTEND/scripts/visual_overview.py)
    产出的 overview JSON，**不重算任何轴值**；
  - 标定结果与 `calibrated_at` 回写 `config/chart_weights.yaml` 的 `thresholds` 段
    （保留原有注释与其余段落，仅替换三个键的值）；
  - 幂等：同输入 + 同 `calibrated_at` 重复执行字节一致；
  - 只写配置，**不写生产库**（LT-G8）。

用法：

    python3 scripts/calibrate_light.py --input /tmp/overview.json --dry-run
    python3 scripts/calibrate_light.py --input /tmp/overview.json --calibrated-at 2026-11-15
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import chart_weights  # noqa: E402

LIT_QUANTILE = 0.70
WARM_QUANTILE = 0.40
DEFAULT_MIN_SAMPLES = 200
DEFAULT_SINCE = "2023-11-01"
DEFAULT_PATH = os.path.join(_MODULE_ROOT, "config", "chart_weights.yaml")

AGGREGATES = ("row", "axis")
_THRESHOLD_KEYS = ("lit_pct", "warm_pct", "calibrated_at")
_KEY_LINE = re.compile(
    r"^(?P<indent>\s+)(?P<key>[A-Za-z_][A-Za-z0-9_]*):(?P<gap>\s*)(?P<value>[^#]*?)(?P<comment>\s*#.*)?$"
)


class CalibrationError(ValueError):
    """样本不足 / 阈值非法 / 配置段缺失（拒绝静默回写）。"""


# ------------------------------------------------------------ 分位
def percentile(values: Sequence[float], q: float) -> float:
    """线性插值分位（`(n-1) * q`，与 numpy 默认口径一致）；空样本抛错。"""
    if not values:
        raise CalibrationError("分位样本为空")
    if not 0.0 <= q <= 1.0:
        raise CalibrationError(f"分位越界: {q}")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


# ------------------------------------------------------------ 样本抽取
def _iter_rows(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    """兼容三种输入：overview 载荷（`lights.rows`）、`light_block`（`lights` 列表）、裸 `rows`。"""
    block = payload.get("lights")
    if isinstance(block, Mapping):
        rows = block.get("rows")
    elif isinstance(block, list):
        rows = block
    else:
        rows = payload.get("rows")
    for row in rows or ():
        if isinstance(row, Mapping):
            yield row


def extract_strengths(payload: Any, *, since: Optional[str] = None) -> Dict[str, Any]:
    """抽出四轴有效强度（`None`/`unavailable` 跳过，不补零、不插值）。

    `payload` 可以是单个 overview 载荷，也可以是**多个 `as_of` 快照的数组**
    （全样本分位需要跨日期池化，单快照最多 12 标的 × 4 轴 = 48 个样本）。
    """
    snapshots = payload if isinstance(payload, (list, tuple)) else [payload]
    strengths: List[float] = []
    per_axis: Dict[str, int] = {}
    skipped_rows = 0
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            continue
        for row in _iter_rows(snapshot):
            as_of = str(row.get("as_of") or "")
            if since and as_of and as_of < since:
                continue
            axes = row.get("axes") or {}
            if not isinstance(axes, Mapping):
                skipped_rows += 1
                continue
            used = False
            for axis, fact in axes.items():
                if not isinstance(fact, Mapping):
                    continue
                value = fact.get("strength")
                if value is None or fact.get("state") == "unavailable":
                    continue
                number = float(value)
                if not 0.0 <= number <= 1.0:
                    continue
                strengths.append(number)
                per_axis[axis] = per_axis.get(axis, 0) + 1
                used = True
            if not used:
                skipped_rows += 1
    return {
        "strengths": strengths,
        "per_axis": per_axis,
        "skipped_rows": skipped_rows,
        "snapshots": len(snapshots),
        "n": len(strengths),
    }


def extract_row_strengths(payload: Any, *, since: Optional[str] = None) -> Dict[str, Any]:
    """抽出**行级合成强度**（`lights.rows[].strength`，LTL-16 定稿口径）。

    `strength=None`（整标的不可点亮 / 参与轴权重和为 0）跳过，不补零、不插值；
    `per_axis` 只统计**进入样本的行**里参与合成的轴（`strength` 非空且非 `unavailable`），
    用于保留 `axis_missing:<轴>` 数据质量告警。
    """
    snapshots = payload if isinstance(payload, (list, tuple)) else [payload]
    strengths: List[float] = []
    per_axis: Dict[str, int] = {}
    skipped_rows = 0
    for snapshot in snapshots:
        if not isinstance(snapshot, Mapping):
            continue
        for row in _iter_rows(snapshot):
            as_of = str(row.get("as_of") or "")
            if since and as_of and as_of < since:
                continue
            value = row.get("strength")
            if value is None:
                skipped_rows += 1
                continue
            number = float(value)
            if not 0.0 <= number <= 1.0:
                skipped_rows += 1
                continue
            strengths.append(number)
            axes = row.get("axes") or {}
            if isinstance(axes, Mapping):
                for axis, fact in axes.items():
                    if not isinstance(fact, Mapping):
                        continue
                    if fact.get("strength") is None or fact.get("state") == "unavailable":
                        continue
                    per_axis[axis] = per_axis.get(axis, 0) + 1
    return {
        "strengths": strengths,
        "per_axis": per_axis,
        "skipped_rows": skipped_rows,
        "snapshots": len(snapshots),
        "n": len(strengths),
    }


# ------------------------------------------------------------ 标定
def calibrate(
    strengths: Sequence[float],
    *,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    per_axis: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    """`lit_pct = p70`、`warm_pct = p40`；样本不足拒绝出阈值（宁可未标定）。

    `warnings` 只提示数据质量（缺轴 / p70 饱和），不改分位口径、不丢样本：
      - `axis_missing:<轴>`：该轴零有效样本（如 I39 未接时的 cycle），合并分位会偏；
      - `p70_saturated_at_1.0`：归一强度被 clamp 到 1.0 的样本过多，
        标定后退化为「只有满值才点亮」，应等更长历史 / 更多快照再标定。
    """
    values = [float(value) for value in strengths]
    if len(values) < int(min_samples):
        raise CalibrationError(f"有效样本 {len(values)} < min_samples={int(min_samples)}，拒绝标定")
    lit = round(percentile(values, LIT_QUANTILE), 6)
    warm = round(percentile(values, WARM_QUANTILE), 6)
    if not 0.0 <= warm <= lit <= 1.0:
        raise CalibrationError(f"标定结果非法: warm={warm} lit={lit}")

    warnings: List[str] = []
    if per_axis is not None:
        missing = [
            axis for axis in chart_weights.LIGHT_AXES if int(per_axis.get(axis, 0) or 0) <= 0
        ]
        if missing:
            warnings.append(f"axis_missing:{','.join(missing)}")
    if lit >= 1.0:
        warnings.append("p70_saturated_at_1.0")
    return {
        "lit_pct": lit,
        "warm_pct": warm,
        "n": len(values),
        "lit_quantile": LIT_QUANTILE,
        "warm_quantile": WARM_QUANTILE,
        "warnings": warnings,
    }


# ------------------------------------------------------------ 回写（保注释）
def _format_value(key: str, value: Any) -> str:
    if key == "calibrated_at":
        return f'"{value}"'
    return f"{float(value):.6f}"


def write_thresholds(
    path: str,
    thresholds: Mapping[str, Any],
    *,
    calibrated_at: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """就地替换 `thresholds` 段三个键的值（保留注释/其余段落）；`dry_run` 不落盘。"""
    if not os.path.exists(path):
        raise CalibrationError(f"配置不存在: {path}")
    payload = dict(thresholds)
    payload["calibrated_at"] = calibrated_at
    lit = float(payload["lit_pct"])
    warm = float(payload["warm_pct"])
    if not 0.0 <= warm <= lit <= 1.0:
        raise CalibrationError(f"阈值非法: 需 0 ≤ warm_pct ≤ lit_pct ≤ 1（{warm}/{lit}）")

    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    start = None
    for index, line in enumerate(lines):
        if line.strip() == "thresholds:" and not line.startswith((" ", "\t")):
            start = index
            break
    if start is None:
        raise CalibrationError(f"配置缺少顶层 thresholds 段: {path}")

    replaced: Dict[str, str] = {}
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.startswith((" ", "\t")):
            break
        match = _KEY_LINE.match(line)
        if match and match.group("key") in _THRESHOLD_KEYS:
            key = match.group("key")
            new_value = _format_value(key, payload[key])
            lines[end] = f"{match.group('indent')}{key}: {new_value}{match.group('comment') or ''}"
            replaced[key] = new_value
        end += 1

    missing = [key for key in _THRESHOLD_KEYS if key not in replaced]
    if missing:
        raise CalibrationError(f"thresholds 段缺少键: {missing}")

    before = chart_weights.load(path)
    text = "\n".join(lines) + "\n"
    if not dry_run:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        after = chart_weights.load(path)
    else:
        after = None

    return {
        "path": path,
        "dry_run": bool(dry_run),
        "replaced": replaced,
        "light_weights_hash_before": before.light_hash(),
        "light_weights_hash_after": after.light_hash() if after else None,
        "thresholds_uncalibrated_after": (not bool(after.calibrated_at) if after else None),
        "text": text if dry_run else None,
    }


# ------------------------------------------------------------ CLI
def _load_payload(source: str) -> Mapping[str, Any]:
    if source == "-":
        return json.load(sys.stdin)
    with open(source, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="点亮阈值分位标定（lit=p70 / warm=p40）")
    parser.add_argument("--input", required=True, help="overview JSON（或 - 读 stdin）")
    parser.add_argument("--path", default=DEFAULT_PATH, help="chart_weights.yaml 路径")
    parser.add_argument(
        "--aggregate",
        choices=AGGREGATES,
        default="row",
        help="统计口径：row=行级合成强度（默认，LTL-16 定稿）；axis=四轴池化（旧口径，仅对照）",
    )
    parser.add_argument("--since", default=DEFAULT_SINCE, help="样本起始日（as_of ≥）")
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument("--calibrated-at", default=None, help="标定日期（默认今天）")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不回写配置")
    args = parser.parse_args(list(argv) if argv is not None else None)

    since = args.since or None
    extractor = extract_row_strengths if args.aggregate == "row" else extract_strengths
    extracted = extractor(_load_payload(args.input), since=since)
    try:
        result = calibrate(
            extracted["strengths"],
            min_samples=args.min_samples,
            per_axis=extracted["per_axis"],
        )
        written = write_thresholds(
            args.path,
            result,
            calibrated_at=args.calibrated_at or datetime.date.today().isoformat(),
            dry_run=args.dry_run,
        )
    except CalibrationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    report = {
        "ok": True,
        "aggregate": args.aggregate,
        "since": since,
        "samples": extracted["n"],
        "snapshots": extracted["snapshots"],
        "per_axis": extracted["per_axis"],
        "skipped_rows": extracted["skipped_rows"],
        **result,
        **{
            key: written[key]
            for key in (
                "path",
                "dry_run",
                "light_weights_hash_before",
                "light_weights_hash_after",
                "thresholds_uncalibrated_after",
            )
        },
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
