#!/usr/bin/env python3
"""组件生命周期状态机检查（P2-1 / GAP-12）。

状态机：draft → beta → active → deprecated → retired

判定口径（机器可查，不依赖人工记忆）:
  - draft/beta/active：只要求 component.yaml 合法、tests/ 存在（G5 已覆盖）
  - deprecated：必须有 `deprecated` 块（at / sunset_at，且 sunset_at > at），
                并给出 replacement 或 reason
  - retired：在 deprecated 要求之上，sunset_at 必须已到期，
             且不允许再出现在 products/*.yaml 的分发表里

用法:
    python3 tools/lifecycle.py check
    python3 tools/lifecycle.py check --json
    python3 tools/lifecycle.py plan <component> --to deprecated
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    import yaml
except ImportError:  # pragma: no cover
    print("E_ENV：缺少 PyYAML（pip install pyyaml）", file=sys.stderr)
    raise SystemExit(2) from None

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "components"
PRODUCTS = ROOT / "products"
STATES = ("draft", "beta", "active", "deprecated", "retired")
TRANSITIONS = {
    "draft": {"beta"},
    "beta": {"draft", "active"},
    "active": {"beta", "deprecated"},
    "deprecated": {"active", "retired"},
    "retired": set(),
}


def load_manifests(components: Path = COMPONENTS) -> Dict[str, Dict[str, Any]]:
    manifests: Dict[str, Dict[str, Any]] = {}
    for path in sorted(components.glob("*/component.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        manifests[path.parent.name] = data
    return manifests


def product_component_refs(products: Path = PRODUCTS) -> Set[str]:
    refs: Set[str] = set()
    for path in sorted(products.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = str(data.get("component") or "")
        if raw.startswith("components/"):
            refs.add(raw.split("/", 1)[1])
    return refs


def _parse_date(value: Any, field: str) -> tuple[Optional[date], List[str]]:
    try:
        return date.fromisoformat(str(value)), []
    except (TypeError, ValueError):
        return None, ["{} 不是 YYYY-MM-DD：{}".format(field, value)]


def validate(
    name: str,
    manifest: Dict[str, Any],
    product_refs: Set[str],
    today: date,
) -> List[str]:
    errors: List[str] = []
    state = str(manifest.get("lifecycle") or "")
    if state not in STATES:
        return ["lifecycle 非法：{}（允许 {}）".format(state, "/".join(STATES))]

    if state not in {"deprecated", "retired"}:
        return errors

    meta = manifest.get("deprecated")
    if not isinstance(meta, dict):
        return ["{} 状态必须声明 deprecated 块（at/sunset_at/replacement|reason）".format(state)]

    started, errs = _parse_date(meta.get("at"), "deprecated.at")
    errors.extend(errs)
    sunset, errs = _parse_date(meta.get("sunset_at"), "deprecated.sunset_at")
    errors.extend(errs)
    if started and sunset and sunset <= started:
        errors.append("deprecated.sunset_at 必须晚于 deprecated.at")
    if not meta.get("replacement") and not meta.get("reason"):
        errors.append("deprecated 必须给出 replacement（替代组件）或 reason（弃用原因）")

    if state == "retired":
        if sunset and sunset > today:
            errors.append("retired 太早：sunset_at={} 尚未到期".format(sunset.isoformat()))
        if name in product_refs:
            errors.append("retired 组件仍被 products/*.yaml 分发：{}".format(name))
    return errors


def check(components: Path = COMPONENTS, products: Path = PRODUCTS, today: Optional[date] = None):
    today = today or date.today()
    manifests = load_manifests(components)
    refs = product_component_refs(products)
    results: Dict[str, Dict[str, Any]] = {}
    for name, manifest in manifests.items():
        errors = validate(name, manifest, refs, today)
        results[name] = {
            "lifecycle": manifest.get("lifecycle"),
            "ok": not errors,
            "errors": errors,
        }
    return results


def plan(
    name: str,
    target: str,
    components: Path = COMPONENTS,
    products: Path = PRODUCTS,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    if target not in STATES:
        raise ValueError("目标状态非法：{}（允许 {}）".format(target, "/".join(STATES)))
    manifests = load_manifests(components)
    if name not in manifests:
        raise ValueError("组件不存在：{}".format(name))
    projected = dict(manifests[name])
    current = str(projected.get("lifecycle") or "")
    if target not in TRANSITIONS.get(current, set()):
        raise ValueError(
            "不允许 {} → {}（允许：{}）".format(
                current, target, "/".join(sorted(TRANSITIONS.get(current, set()))) or "无"
            )
        )
    projected["lifecycle"] = target
    refs = product_component_refs(products)
    errors = validate(name, projected, refs, today or date.today())
    return {
        "component": name,
        "from": manifests[name].get("lifecycle"),
        "to": target,
        "ready": not errors,
        "missing": errors,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="组件生命周期状态机检查")
    sub = parser.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check", help="校验所有组件的 lifecycle 与弃用字段")
    p_check.add_argument("--json", action="store_true")
    p_check.add_argument("--components", type=Path, default=COMPONENTS)
    p_check.add_argument("--products", type=Path, default=PRODUCTS)

    p_plan = sub.add_parser("plan", help="查看晋级/弃用到目标状态还缺什么（只读）")
    p_plan.add_argument("component")
    p_plan.add_argument("--to", required=True, choices=STATES)
    p_plan.add_argument("--json", action="store_true")
    p_plan.add_argument("--components", type=Path, default=COMPONENTS)
    p_plan.add_argument("--products", type=Path, default=PRODUCTS)

    args = parser.parse_args(argv)
    if args.cmd == "plan":
        try:
            result = plan(args.component, args.to, args.components, args.products)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif result["ready"]:
            print("{}：{} → {} 可执行".format(args.component, result["from"], result["to"]))
        else:
            print("{}：{} → {} 缺少条件：".format(args.component, result["from"], result["to"]))
            for item in result["missing"]:
                print("  - {}".format(item))
        return 0 if result["ready"] else 1

    results = check(args.components, args.products)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for name, item in results.items():
            print(
                "{:<28} {:<10} {}".format(name, item["lifecycle"], "OK" if item["ok"] else "FAIL")
            )
            for error in item["errors"]:
                print("  - {}".format(error))
    return 0 if all(item["ok"] for item in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
