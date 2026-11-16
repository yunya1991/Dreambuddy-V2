#!/usr/bin/env python3
"""M1-T 路由表（问题类别 → REA 工具链）。

定位：求解级联 D3 之前的一跳确定性索引。调用方拿问题描述来问「该调哪几个 REA 工具」，
避免每次现拆都从头试探工具。

约束（SPEC-ResidualMemory-Admission §3.6）：
  1. 只存「类别 → 工具链」，不存方法论正文；
  2. 条目计入 M1 指针 150 条上限，超限 fail-loud（要求抽象合并，禁止扩容）；
  3. 未命中必须显式降级（`routing_no_match` + `next=capability_gap_workorder`），
     禁止伪装成「没有这类问题」。

数据文件：`tools/rea_routing_table.yaml`（人工策展）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:  # PyYAML 是运行期依赖；缺失时 fail-loud 而非静默跳过
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

DEFAULT_TABLE = Path(__file__).with_name("rea_routing_table.yaml")
PIN_BUDGET = 150
_REQUIRED_KEYS = ("id", "keywords", "tools")


def _invalid(reason: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "degraded_reason": reason}
    out.update(extra)
    return out


def _validate(table: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(table, dict):
        return ["table_not_mapping"]
    cats = table.get("categories")
    if not isinstance(cats, list) or not cats:
        return ["categories_missing_or_empty"]
    seen: set[str] = set()
    for idx, cat in enumerate(cats):
        if not isinstance(cat, dict):
            errors.append(f"category[{idx}]_not_mapping")
            continue
        for key in _REQUIRED_KEYS:
            if not cat.get(key):
                errors.append(f"category[{idx}].{key}_missing")
        cid = cat.get("id")
        if isinstance(cid, str) and cid:
            if cid in seen:
                errors.append(f"duplicate_id:{cid}")
            seen.add(cid)
        if isinstance(cat.get("keywords"), list) and not all(
            isinstance(k, str) and k.strip() for k in cat["keywords"]
        ):
            errors.append(f"category[{idx}].keywords_malformed")
        if isinstance(cat.get("tools"), list) and not all(
            isinstance(t, str) and t.startswith("mcp_rea_") for t in cat["tools"]
        ):
            errors.append(f"category[{idx}].tools_malformed")
    return errors


def load_table(path: str | Path | None = None) -> dict[str, Any]:
    """加载并校验路由表。

    Returns:
        {"ok": True, "version": int, "budget": int, "count": int, "categories": [...]}
        或 {"ok": False, "degraded_reason": "...", ...}
    """
    p = Path(path) if path else DEFAULT_TABLE
    if yaml is None:
        return _invalid("pyyaml_missing", path=str(p))
    if not p.exists():
        return _invalid("routing_table_missing", path=str(p))
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - 依赖具体文件内容
        return _invalid("routing_table_unparsable", path=str(p), error=str(exc))

    errors = _validate(raw)
    if errors:
        return _invalid("routing_table_invalid", path=str(p), errors=errors)

    budget = int(raw.get("budget") or PIN_BUDGET)
    count = len(raw["categories"])
    if count > budget:
        return _invalid(
            "routing_budget_exceeded",
            path=str(p),
            count=count,
            budget=budget,
            hint="超限必须抽象合并同类类别，禁止直接扩容",
        )
    return {
        "ok": True,
        "version": raw.get("version"),
        "updated_at": raw.get("updated_at"),
        "budget": budget,
        "count": count,
        "categories": raw["categories"],
    }


def _score(query: str, cat: dict[str, Any]) -> tuple[int, list[str]]:
    q = query.casefold()
    matched = [kw for kw in cat.get("keywords") or [] if kw.casefold() in q]
    return len(matched), matched


def route(problem: str, path: str | Path | None = None) -> dict[str, Any]:
    """把问题描述路由到 REA 工具链（确定性关键词命中，不做语义猜测）。"""
    table = load_table(path)
    if not table.get("ok"):
        table.setdefault("next", "D3")
        return table

    best: dict[str, Any] | None = None
    best_score = 0
    best_matched: list[str] = []
    for cat in table["categories"]:
        score, matched = _score(problem or "", cat)
        if score > best_score:  # 同分保持文件顺序，保证确定性
            best, best_score, best_matched = cat, score, matched

    if best is None or best_score == 0:
        return {
            "ok": False,
            "degraded_reason": "routing_no_match",
            "next": "capability_gap_workorder",
            "count": table["count"],
        }

    return {
        "ok": True,
        "category": best.get("id"),
        "summary": best.get("summary", ""),
        "tools": list(best.get("tools") or []),
        "score": best_score,
        "matched_keywords": best_matched,
        "count": table["count"],
        "budget": table["budget"],
    }


def _cli_list(args: argparse.Namespace) -> int:
    table = load_table(args.table)
    if not table.get("ok"):
        print(json.dumps(table, ensure_ascii=False, indent=2))
        return 1
    for cat in table["categories"]:
        print(f"{cat['id']:<22} -> {', '.join(cat['tools'])}")
    print(f"-- {table['count']}/{table['budget']} 条（上限计入 M1 指针）")
    return 0


def _cli_route(args: argparse.Namespace) -> int:
    out = route(args.problem, args.table)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


def _cli_validate(args: argparse.Namespace) -> int:
    out = load_table(args.table)
    print(
        json.dumps(
            out if not out.get("ok") else {k: v for k, v in out.items() if k != "categories"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if out.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M1-T REA 路由表")
    parser.add_argument(
        "--table", default=None, help="路由表路径（默认 tools/rea_routing_table.yaml）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出全部类别")
    p_route = sub.add_parser("route", help="按问题描述路由")
    p_route.add_argument("problem", help="问题描述")
    sub.add_parser("validate", help="校验表结构/预算")

    args = parser.parse_args(argv)
    if args.command == "list":
        return _cli_list(args)
    if args.command == "route":
        return _cli_route(args)
    return _cli_validate(args)


if __name__ == "__main__":
    raise SystemExit(main())
