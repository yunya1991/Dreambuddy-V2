# -*- coding: utf-8 -*-
"""生成 patterns.json（TASKS-20261116 T4-2）。

读取一期 Discovery 报告目录里的 `findings.jsonl`，按算法注册表的 `method_roles`
归类，产出同目录 `patterns.json`。只读 findings、不改发现结果、不写注册表。

用法：
    python3 scripts/build_patterns.py                     # 最新一期报告
    python3 scripts/build_patterns.py --report-dir <dir>
    python3 scripts/build_patterns.py --check             # 与现有 patterns.json 比对
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

import yaml  # noqa: E402
from l1agg.capabilities.eval_exports import REPORTS_DIR  # noqa: E402
from l1agg.patterns import (  # noqa: E402
    DEFAULT_ALPHA,
    DEFAULT_MIN_AGREE,
    DEFAULT_MIN_MEMBERS,
    build_patterns,
    to_json,
    validate_document,
)

REGISTRY_PATH = os.path.join(_MODULE_ROOT, "config", "algorithm_registry.yaml")
_REPORT_DIR = re.compile(r"^\d{8}")


def _latest_report_dir(root: str) -> Optional[str]:
    try:
        names = sorted((name for name in os.listdir(root) if _REPORT_DIR.match(name)), reverse=True)
    except OSError:
        return None
    for name in names:
        directory = os.path.join(root, name)
        if os.path.isfile(os.path.join(directory, "findings.jsonl")):
            return directory
    return None


def _findings(path: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                items.append(parsed)
    return items


def _roles() -> Dict[str, List[str]]:
    with open(REGISTRY_PATH, "r", encoding="utf-8") as fh:
        registry = yaml.safe_load(fh) or {}
    return {
        str(key): [str(item) for item in value]
        for key, value in (registry.get("method_roles") or {}).items()
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成同类现象归纳 patterns.json")
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    parser.add_argument("--min-agree", type=float, default=DEFAULT_MIN_AGREE)
    parser.add_argument("--min-members", type=int, default=DEFAULT_MIN_MEMBERS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    report_dir = args.report_dir or _latest_report_dir(REPORTS_DIR)
    if not report_dir:
        print(
            json.dumps(
                {"ok": False, "degraded": True, "reason": "no_discovery_report"}, ensure_ascii=False
            )
        )
        return 1
    findings_path = os.path.join(report_dir, "findings.jsonl")
    if not os.path.isfile(findings_path):
        print(
            json.dumps({"ok": False, "degraded": True, "reason": "no_findings"}, ensure_ascii=False)
        )
        return 1

    document = build_patterns(
        _findings(findings_path),
        _roles(),
        alpha=args.alpha,
        min_agree=args.min_agree,
        min_members=args.min_members,
    )
    errors = validate_document(document)
    if errors:
        print(
            json.dumps(
                {"ok": False, "reason": "schema_invalid", "errors": errors}, ensure_ascii=False
            )
        )
        return 1

    text = to_json(document)
    out_path = args.out or os.path.join(report_dir, "patterns.json")

    if args.check:
        if not os.path.isfile(out_path):
            print(
                json.dumps(
                    {"ok": False, "reason": "missing_patterns", "path": out_path},
                    ensure_ascii=False,
                )
            )
            return 1
        with open(out_path, "r", encoding="utf-8") as fh:
            if fh.read() != text:
                print(
                    json.dumps(
                        {"ok": False, "reason": "patterns_drift", "path": out_path},
                        ensure_ascii=False,
                    )
                )
                return 1
        print(
            json.dumps(
                {"ok": True, "path": out_path, "patterns": document["pattern_count"]},
                ensure_ascii=False,
            )
        )
        return 0

    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, out_path)
    print(
        json.dumps(
            {
                "ok": True,
                "path": out_path,
                "report": os.path.basename(report_dir),
                "patterns": document["pattern_count"],
                "stable": sum(1 for item in document["patterns"] if item["status"] == "stable"),
                "unmapped": document["unmapped"],
                "skipped": document["skipped"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
