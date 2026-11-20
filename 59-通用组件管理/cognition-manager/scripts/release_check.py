#!/usr/bin/env python3
"""发布前一致性闸门（release check）。

一次性校验三端契约副本、版本号与体检口径，任一不一致即退出 1：

1. 三份 `metrics-contract.json`（免费版 / Pro / 后端）逐字节一致；
2. 契约结构合法（`core.contract.validate`）；
3. 版本号一致：`manifest.yaml` / `SKILL.md` / `core.__version__`；
4. `health` 口径与契约一致（good / attention / poor 三档抽样）。

用法：
    python3 scripts/release_check.py [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from core import __version__, contract, report  # noqa: E402

PACKAGE_ROOT = SCRIPT_DIR.parent
MODULE_ROOT = PACKAGE_ROOT.parent

CONTRACT_COPIES = {
    "free": PACKAGE_ROOT / "references" / "metrics-contract.json",
    "pro": MODULE_ROOT / "skills" / "cogsteward-pro" / "references" / "metrics-contract.json",
    "backend": MODULE_ROOT / "services" / "skillhub-audit-api" / "src" / "metrics-contract.json",
}

HEALTH_SAMPLES = (
    ({}, "good"),
    ({"broken_links": 1}, "attention"),
    ({"broken_links": 1, "orphan_files": 1}, "attention"),
    ({"broken_links": 1, "orphan_files": 1, "doc_drift": 1}, "poor"),
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frontmatter_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^version:\s*(\S+)\s*$", text)
    return match.group(1) if match else ""


def check_contract_copies() -> tuple:
    missing = [name for name, path in CONTRACT_COPIES.items() if not path.exists()]
    if missing:
        return False, "缺少契约副本：{}".format(", ".join(missing))

    digests = {name: _digest(path) for name, path in CONTRACT_COPIES.items()}
    if len(set(digests.values())) != 1:
        return False, "契约副本不一致：{}".format(
            ", ".join("{}={}".format(name, digest[:12]) for name, digest in digests.items())
        )
    return True, "三端契约一致（sha256 {}）".format(next(iter(digests.values()))[:12])


def check_contract_structure() -> tuple:
    try:
        data = contract.load(CONTRACT_COPIES["free"])
    except contract.ContractError as exc:
        return False, str(exc)
    return True, "契约 v{}，{} 项指标 / {} 项占比".format(
        data["schema_version"], len(data["metrics"]), len(data["ratios"])
    )


def check_versions() -> tuple:
    manifest = _frontmatter_version(PACKAGE_ROOT / "manifest.yaml")
    skill = _frontmatter_version(PACKAGE_ROOT / "SKILL.md")
    found = {"manifest.yaml": manifest, "SKILL.md": skill, "core.__version__": __version__}
    unique = set(found.values())
    if len(unique) != 1 or "" in unique:
        return False, "版本号不一致：{}".format(
            ", ".join("{}={}".format(name, value or "<空>") for name, value in found.items())
        )
    return True, "版本号一致：{}".format(__version__)


def check_health_alignment() -> tuple:
    data = contract.load(CONTRACT_COPIES["free"])
    problems = contract.problem_keys(data)
    if tuple(report.PROBLEM_KEYS) != tuple(problems):
        return False, "免费版 PROBLEM_KEYS 与契约不一致"
    for values, expected in HEALTH_SAMPLES:
        actual = report.health_of(values)
        if actual != expected:
            return False, "health 抽样不一致：{} → {}（期望 {}）".format(values, actual, expected)
    return True, "health 三档抽样一致（{} 项问题指标）".format(len(problems))


CHECKS = (
    ("契约副本一致", check_contract_copies),
    ("契约结构合法", check_contract_structure),
    ("版本号一致", check_versions),
    ("health 口径一致", check_health_alignment),
)


def run() -> dict:
    results = []
    for name, func in CHECKS:
        try:
            ok, detail = func()
        except Exception as exc:  # 闸门自身异常也要以失败呈现
            ok, detail = False, "检查异常：{}".format(exc)
        results.append({"check": name, "ok": ok, "detail": detail})
    return {
        "ok": all(item["ok"] for item in results),
        "version": __version__,
        "checks": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="认知管家发布前一致性闸门")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    result = run()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("认知管家 · 发布前一致性闸门（v{}）".format(result["version"]))
        for item in result["checks"]:
            print(
                "  [{}] {}：{}".format(
                    "PASS" if item["ok"] else "FAIL", item["check"], item["detail"]
                )
            )
        print("结论：{}".format("通过" if result["ok"] else "未通过"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
