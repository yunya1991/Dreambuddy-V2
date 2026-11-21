#!/usr/bin/env python3
"""供应链校验：商品 → 构建产物 → SkillHub 平台签名（P2-2 / GAP-13）。

两段门禁:
  check（离线，进 make check）: dist 产物与 component/kernel 源一致，防"改了源没重构建"；
  verify（在线，进 make verify-live）: 调 `skillhub verify` 校验平台签名，未配置/未登录时 SKIP。

用法:
    python3 tools/supply_chain.py check
    python3 tools/supply_chain.py verify --online
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    print("E_ENV：缺少 PyYAML（pip install pyyaml）", file=sys.stderr)
    raise SystemExit(2) from None

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = ROOT / "products"
DIST = ROOT / "dist"
KERNEL = ROOT / "kernel"
SKIP_REASONS = ("not logged in", "unauthorized", "401", "E_AUTH", "未登录", "请先登录")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_products(directory: Path = PRODUCTS) -> Dict[str, Dict[str, Any]]:
    items: Dict[str, Dict[str, Any]] = {}
    for path in sorted(directory.glob("*.yaml")):
        items[path.stem] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return items


def check_product_manifest(
    product: str,
    data: Dict[str, Any],
    variant: str,
    manifest: Dict[str, Any],
    dist: Path = DIST,
) -> List[str]:
    errors: List[str] = []
    built = dist / product / variant
    skill_md = built / "SKILL.md"
    if not skill_md.is_file():
        errors.append("{} 缺少 SKILL.md".format(built.relative_to(ROOT)))
    elif manifest.get("skill_sha256") != sha256(skill_md):
        errors.append("SKILL.md 与构建清单哈希不一致（改了源未重建？）")

    component_dir = ROOT / str(manifest.get("component") or "")
    component_yaml = component_dir / "component.yaml"
    if not component_yaml.is_file():
        errors.append("构建清单指向的组件不存在：{}".format(component_dir))
    else:
        source = yaml.safe_load(component_yaml.read_text(encoding="utf-8")) or {}
        if str(source.get("version")) != str(manifest.get("component_version")):
            errors.append(
                "组件版本漂移：源 {} / 清单 {}（先 make build）".format(
                    source.get("version"), manifest.get("component_version")
                )
            )

    for module, digest in (manifest.get("kernel") or {}).items():
        source_path = KERNEL / "{}.py".format(module)
        if not source_path.is_file():
            errors.append("kernel 模块不存在：{}".format(module))
        elif sha256(source_path) != digest:
            errors.append("kernel/{}.py 与构建清单哈希不一致（先 make build）".format(module))

    entrypoints = list((data.get("variants") or {}).get(variant, {}).get("entrypoints") or [])
    for entry in entrypoints:
        if not (built / entry).is_file():
            errors.append("产物缺少入口：{}".format(entry))
    return errors


def check(products: Path = PRODUCTS, dist: Path = DIST) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    for product, data in load_products(products).items():
        variants = data.get("variants") or {}
        product_dir = dist / product
        if not product_dir.is_dir():
            results[product] = {"status": "skip", "reason": "dist 未构建", "errors": []}
            continue
        errors: List[str] = []
        for variant in variants:
            manifest_path = product_dir / "{}.manifest.json".format(variant)
            if not manifest_path.is_file():
                errors.append("缺少构建清单：{}".format(manifest_path.relative_to(ROOT)))
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            errors.extend(check_product_manifest(product, data, variant, manifest, dist))
        results[product] = {
            "status": "fail" if errors else "ok",
            "reason": "",
            "errors": errors,
        }
    return results


def classify_verify(returncode: int, output: str) -> Dict[str, Any]:
    text = output or ""
    lowered = text.lower()
    if any(reason.lower() in lowered for reason in SKIP_REASONS):
        return {"status": "skip", "reason": "skillhub 未登录或无权访问", "detail": text[-300:]}
    if returncode != 0:
        return {
            "status": "fail",
            "reason": "verify 退出码 {}".format(returncode),
            "detail": text[-300:],
        }
    try:
        payload = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        payload = {}
    if payload.get("ok") is False or payload.get("match") is False:
        return {"status": "fail", "reason": "平台签名不一致", "detail": text[-300:]}
    return {"status": "ok", "reason": "", "detail": ""}


def verify(
    online: bool = False,
    products: Path = PRODUCTS,
    runner: Optional[Callable[[List[str]], subprocess.CompletedProcess]] = None,
) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    if not online:
        return {
            product: {"status": "skip", "reason": "未开启在线校验（--online）"}
            for product in load_products(products)
        }
    if runner is None and shutil.which("skillhub") is None:
        return {
            product: {"status": "skip", "reason": "skillhub CLI 未安装"}
            for product in load_products(products)
        }
    for product, data in load_products(products).items():
        variant = next(iter((data.get("variants") or {}).values()), {})
        name = str(variant.get("name") or product)
        if runner is None:
            proc = subprocess.run(
                ["skillhub", "--skip-self-upgrade", "verify", name, "--json"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        else:  # pragma: no cover - 测试注入
            proc = runner(["skillhub", "verify", name, "--json"])
        results[product] = classify_verify(proc.returncode, proc.stdout + proc.stderr)
    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="供应链校验（构建产物 / 平台签名）")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("check", help="离线校验 dist 与源码一致")
    p_verify = sub.add_parser("verify", help="在线校验 SkillHub 平台签名")
    p_verify.add_argument("--online", action="store_true")
    p_verify.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "verify":
        results = verify(online=args.online)
        for product, item in results.items():
            print(
                "{:<20} {:<5} {}".format(product, item["status"].upper(), item.get("reason") or "")
            )
        return 1 if any(item["status"] == "fail" for item in results.values()) else 0

    results = check()
    for product, item in results.items():
        print("{:<20} {:<5} {}".format(product, item["status"].upper(), item.get("reason") or ""))
        for error in item["errors"]:
            print("  - {}".format(error))
    return 1 if any(item["status"] == "fail" for item in results.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
