#!/usr/bin/env python3
"""SkillSet（技能集）打包与校验（P2-2 / GAP-13）。

技能集是一组商品的分发单位：`skillsets/<name>.yaml` 声明商品清单，
`build` 把 `dist/<product>/<variant>/` 打成一个 zip（含 pack.json 清单），
对应 `skillhub pack install <slug>` 的本地离线形态。

用法:
    python3 tools/skillset.py list
    python3 tools/skillset.py show research-desk
    python3 tools/skillset.py check
    python3 tools/skillset.py build research-desk --out dist/packs/research-desk.zip
    python3 tools/skillset.py build research-desk --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    print("E_ENV：缺少 PyYAML（pip install pyyaml）", file=sys.stderr)
    raise SystemExit(2) from None

ROOT = Path(__file__).resolve().parent.parent
SKILLSETS = ROOT / "skillsets"
PRODUCTS = ROOT / "products"
COMPONENTS = ROOT / "components"
DIST = ROOT / "dist"


def load_skillsets(directory: Path = SKILLSETS) -> Dict[str, Dict[str, Any]]:
    items: Dict[str, Dict[str, Any]] = {}
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data["_path"] = path
        items[path.stem] = data
    return items


def load_products(directory: Path = PRODUCTS) -> Dict[str, Dict[str, Any]]:
    items: Dict[str, Dict[str, Any]] = {}
    for path in sorted(directory.glob("*.yaml")):
        items[path.stem] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return items


def validate(
    name: str,
    skillset: Dict[str, Any],
    products: Dict[str, Dict[str, Any]],
    root: Path = ROOT,
) -> List[str]:
    errors: List[str] = []
    if str(skillset.get("skillset") or "") != name:
        errors.append("skillset 字段必须与文件名一致：{}".format(name))
    declared = skillset.get("products")
    if not isinstance(declared, list) or not declared:
        return errors + ["products 必须是非空数组"]
    if len(set(declared)) != len(declared):
        errors.append("products 有重复项")
    for product in declared:
        if product not in products:
            errors.append("商品不存在：{}".format(product))
            continue
        component = str(products[product].get("component") or "")
        if component and not (root / component / "component.yaml").is_file():
            errors.append("{} 指向的组件不存在：{}".format(product, component))
    return errors


def check(skillsets: Path = SKILLSETS, products: Path = PRODUCTS) -> Dict[str, Dict[str, Any]]:
    loaded = load_skillsets(skillsets)
    product_map = load_products(products)
    results: Dict[str, Dict[str, Any]] = {}
    for name, skillset in loaded.items():
        errors = validate(name, skillset, product_map, skillsets.parent)
        results[name] = {
            "ok": not errors,
            "products": skillset.get("products") or [],
            "errors": errors,
        }
    return results


def pack_files(skillset: Dict[str, Any], dist: Path = DIST) -> List[Path]:
    files: List[Path] = []
    for product in skillset.get("products") or []:
        product_dir = dist / product
        if not product_dir.is_dir():
            raise ValueError(
                "缺少构建产物：{}（先运行 make build）".format(product_dir.relative_to(ROOT))
            )
        files.extend(sorted(path for path in product_dir.rglob("*") if path.is_file()))
    return files


def build_pack(
    name: str,
    out: Path,
    skillsets: Path = SKILLSETS,
    dist: Path = DIST,
    products: Path = PRODUCTS,
    dry_run: bool = False,
) -> Dict[str, Any]:
    loaded = load_skillsets(skillsets)
    if name not in loaded:
        raise ValueError("技能集不存在：{}".format(name))
    skillset = loaded[name]
    errors = validate(name, skillset, load_products(products), products.parent)
    if errors:
        raise ValueError("技能集校验失败：{}".format("；".join(errors)))

    files = pack_files(skillset, dist)
    manifest = {
        "skillset": name,
        "display_name": skillset.get("display_name") or name,
        "description": skillset.get("description") or "",
        "products": skillset.get("products") or [],
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "files": [str(path.relative_to(dist)) for path in files],
    }
    if dry_run:
        return {"out": str(out), "manifest": manifest, "dry_run": True}

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pack.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for path in files:
            archive.write(path, path.relative_to(dist).as_posix())
    return {"out": str(out), "manifest": manifest, "dry_run": False}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="SkillSet 技能集打包与校验")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出技能集")
    p_show = sub.add_parser("show", help="查看技能集详情")
    p_show.add_argument("name")
    sub.add_parser("check", help="校验所有技能集引用")
    p_build = sub.add_parser("build", help="把技能集打成 zip")
    p_build.add_argument("name")
    p_build.add_argument("--out", type=Path, default=None)
    p_build.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "list":
        for name, skillset in load_skillsets().items():
            print(
                "{:<20} {:<24} {}".format(
                    name,
                    skillset.get("display_name") or "",
                    ", ".join(skillset.get("products") or []),
                )
            )
        return 0
    if args.cmd == "show":
        skillset = load_skillsets().get(args.name)
        if not skillset:
            print("技能集不存在：{}".format(args.name), file=sys.stderr)
            return 2
        print(
            json.dumps(
                {k: v for k, v in skillset.items() if k != "_path"}, ensure_ascii=False, indent=2
            )
        )
        return 0
    if args.cmd == "build":
        try:
            out = args.out or (DIST / "packs" / "{}.zip".format(args.name))
            result = build_pack(args.name, out, dry_run=args.dry_run)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if result["dry_run"]:
            print("dry-run：将打包 {} 个文件 → {}".format(len(result["manifest"]["files"]), out))
        else:
            print("已生成 {}（{} 个文件）".format(out, len(result["manifest"]["files"])))
        return 0

    results = check()
    for name, item in results.items():
        print("{:<20} {}".format(name, "OK" if item["ok"] else "FAIL"))
        for error in item["errors"]:
            print("  - {}".format(error))
    return 0 if all(item["ok"] for item in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
