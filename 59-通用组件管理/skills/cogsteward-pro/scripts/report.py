#!/usr/bin/env python3
"""纯计算：把调用方给出的指标 JSON 换算成体检报告。

安全边界：
- 不遍历工作区目录、不读取文档、不访问数据库、不联网；
- 唯一输入是 --metrics JSON，契约读取自本技能自带的 references/metrics-contract.json。

用法:
    python3 report.py --metrics '{"metrics":{"broken_links":3},"inventory":{"documents":47}}'
    python3 report.py --metrics @metrics.json
    python3 report.py --metrics @metrics.json --format json
"""

import argparse
import json
import sys
from pathlib import Path

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "references" / "metrics-contract.json"
INVENTORY_KEYS = ("documents", "skills", "memories", "sessions")
MAX_VALUE = 1000000


def load_contract(path=None):
    target = Path(path) if path else CONTRACT_PATH
    with open(target, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data.get("metrics"), list) or not data["metrics"]:
        raise ValueError("契约缺少 metrics")
    if not isinstance(data.get("problem_metrics"), list) or not data["problem_metrics"]:
        raise ValueError("契约缺少 problem_metrics")
    return data


def pct(num, den):
    if num is None or not den or den <= 0:
        return None
    return round(num * 100.0 / den, 2)


def health_of(metrics, contract):
    rules = contract["health"]
    problems = sum(1 for key in contract["problem_metrics"] if (metrics.get(key) or 0) > 0)
    if problems <= rules["ok_max_problems"]:
        return "good"
    if problems <= rules["attention_max_problems"]:
        return "attention"
    return "poor"


def build(payload, contract=None, top=3):
    contract = contract or load_contract()
    metrics = payload.get("metrics") or {}
    inventory = payload.get("inventory") or {}
    score, findings, benchmarks, ratios = 100, [], [], {}

    coverage = {
        "orphan": "complete" if metrics.get("orphan_files") is not None else "unavailable",
    }
    for key in contract["problem_metrics"]:
        coverage[key] = "complete" if key in metrics else "unavailable"

    for rule in contract["metrics"]:
        key = rule["key"]
        if key not in metrics:
            continue
        value = metrics[key]
        state = "high" if value >= rule["high_at"] else "warn" if value >= rule["warn_at"] else "ok"
        score -= (
            rule["weight"]
            if state == "high"
            else int(rule["weight"] * 0.5) if state == "warn" else 0
        )
        benchmarks.append(
            {
                "metric": key,
                "label": rule["label"],
                "value": value,
                "warn_at": rule["warn_at"],
                "high_at": rule["high_at"],
                "status": state,
            }
        )
        if state != "ok":
            findings.append(
                {
                    "id": key,
                    "label": rule["label"],
                    "priority": "P0" if state == "high" else "P1",
                    "value": value,
                    "threshold": "{}/{}".format(rule["warn_at"], rule["high_at"]),
                    "action": rule["action"],
                }
            )

    for rule in contract["ratios"]:
        rid = rule["id"]
        value = pct(metrics.get(rule["metric"]), inventory.get(rule["denominator"]))
        if value is None:
            continue
        state = "high" if value >= rule["high_at"] else "warn" if value >= rule["warn_at"] else "ok"
        ratios[rid] = {
            "id": rid,
            "label": rule["label"],
            "metric": rule["metric"],
            "value": value,
            "warn_at": rule["warn_at"],
            "high_at": rule["high_at"],
            "status": state,
            "informational": bool(rule.get("informational")),
        }

    score = max(0, min(100, score))
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
    findings.sort(key=lambda item: 0 if item["priority"] == "P0" else 1)
    return {
        "schema_version": contract["schema_version"],
        "engine": "local",
        "grade": grade,
        "score": score,
        "health": health_of(metrics, contract),
        "metrics": metrics,
        "inventory": inventory,
        "coverage": coverage,
        "ratios": ratios,
        "benchmarks": benchmarks,
        "findings": findings[: max(1, top)],
        "total_findings": len(findings),
        "disclaimer": "按固定阈值计算，不联网、不上传任何数据；比率在分母为 0 时留空，未采集的指标标记为 unavailable。",
    }


def validate_payload(payload, contract):
    """按契约校验输入，返回 (errors, warnings)。"""
    errors, warnings = [], []
    metric_keys = {rule["key"] for rule in contract["metrics"]}
    for section in ("metrics", "inventory"):
        value = payload.get(section)
        if value is None:
            continue
        if not isinstance(value, dict):
            errors.append("{} 必须是对象".format(section))
            continue
        valid = metric_keys if section == "metrics" else set(INVENTORY_KEYS)
        for key, item in value.items():
            if key not in valid:
                warnings.append(
                    "未知指标：{}（已忽略；{} 可用：{}）".format(
                        key, section, "、".join(sorted(valid))
                    )
                )
                continue
            if isinstance(item, bool) or not isinstance(item, int) or item < 0 or item > MAX_VALUE:
                errors.append(
                    "{}.{} 必须是非负整数（≤{}），当前为 {!r}".format(section, key, MAX_VALUE, item)
                )
    if not any(
        isinstance(payload.get(section), dict) and payload.get(section)
        for section in ("metrics", "inventory")
    ):
        errors.append("缺少可评估数据：metrics 或 inventory 至少提供一项")
    return errors, warnings


def main(argv=None):
    p = argparse.ArgumentParser(description="认知管家 Pro 本地报告（纯计算）")
    p.add_argument("--metrics", required=True, help="指标 JSON，或 @文件路径")
    p.add_argument("--contract", default=None, help="自定义契约路径（默认包内 references）")
    p.add_argument("--format", choices=("text", "json"), default="text", help="输出格式")
    p.add_argument("--top", type=int, default=3, help="展示前 N 条整改动作（默认 3）")
    args = p.parse_args(argv)

    raw = args.metrics
    if raw.startswith("@"):
        with open(raw[1:], "r", encoding="utf-8") as fh:
            raw = fh.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("ERR --metrics 不是合法 JSON：{}".format(exc), file=sys.stderr)
        return 1
    try:
        contract = load_contract(args.contract)
    except (OSError, ValueError) as exc:
        print("ERR 指标契约不可用：{}".format(exc), file=sys.stderr)
        return 1

    errors, warnings = validate_payload(payload, contract)
    for warning in warnings:
        print("WARN {}".format(warning), file=sys.stderr)
    if errors:
        for error in errors:
            print("ERR {}".format(error), file=sys.stderr)
        return 1

    report = build(payload, contract, top=args.top)

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("认知管家 Pro 体检报告（契约 v{}）".format(report["schema_version"]))
    print("  等级 {}  评分 {}  状态 {}".format(report["grade"], report["score"], report["health"]))
    for item in report["ratios"].values():
        suffix = "（参考）" if item.get("informational") else ""
        print(
            "  {:<8} {:>6.2f}%  [{}]{}".format(item["label"], item["value"], item["status"], suffix)
        )
    missing = [
        key
        for key, state in report["coverage"].items()
        if state == "unavailable" and key != "orphan"
    ]
    if report["coverage"]["orphan"] == "unavailable":
        print("\n覆盖：orphan_files 未采集（缺可读的 .cm/index.db），该项不参与评分。")
    if missing:
        print("覆盖：{} 未采集（unavailable），不参与评分。".format("、".join(missing)))
    if report["findings"]:
        print("\n优先修复")
        for index, item in enumerate(report["findings"], 1):
            print(
                "  {}. [{}] {} = {}（阈值 {}）".format(
                    index, item["priority"], item["label"], item["value"], item["threshold"]
                )
            )
            print("     动作：{}".format(item["action"]))
        if report["total_findings"] > len(report["findings"]):
            print(
                "  … 其余 {} 条可用 --top {} 查看".format(
                    report["total_findings"], report["total_findings"]
                )
            )
    else:
        print("\n无异常项。")
    print("\n{}".format(report["disclaimer"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
