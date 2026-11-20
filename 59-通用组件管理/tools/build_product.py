#!/usr/bin/env python3
"""按 products/<product>.yaml 构建分发包（SPEC §7）。

用法:
    python3 tools/build_product.py --product cogsteward --variant pro --dry-run
    python3 tools/build_product.py --product cogsteward --all
    python3 tools/build_product.py --all

构建行为:
    校验 component.yaml 与 skill/SKILL.md 版本一致 → 复制 skill/
    → 叠加 variants/<variant>/（含该变体 SKILL.md）→ 内联 kernel/_kernel/
    → 注入 contracts/metrics-contract.json → 校验入口 → 写构建清单

产物目录: dist/<product>/<variant>/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from sync_kernel import referenced_modules, resolve_deps

try:
    import yaml
except ImportError:  # pragma: no cover
    print("E_ENV：需要 PyYAML（python3 -m pip install pyyaml）", file=sys.stderr)
    raise SystemExit(2) from None

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "components"
PRODUCTS = ROOT / "products"
KERNEL = ROOT / "kernel"
CONTRACTS = ROOT / "contracts"
DIST = ROOT / "dist"
IGNORE = ("__pycache__", "*.pyc", ".DS_Store", ".cm", "_kernel")


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit("E_INPUT：缺少 {}".format(path.relative_to(ROOT)))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("E_INPUT：{} 顶层必须是对象".format(path.relative_to(ROOT)))
    return data


def split_frontmatter(text: str) -> tuple[list[str], list[str]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SystemExit("E_INPUT：SKILL.md 缺少 frontmatter")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index], lines[index + 1 :]
    raise SystemExit("E_INPUT：SKILL.md frontmatter 未闭合")


def frontmatter_value(text: str, key: str) -> str:
    head, _ = split_frontmatter(text)
    for line in head:
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inject_kernel(dest: Path, deps: list[str]) -> dict:
    hashes = {}
    if not deps:
        return hashes
    target = dest / "scripts" / "_kernel"
    target.mkdir(parents=True, exist_ok=True)
    (target / "__init__.py").write_text("# 构建期内联，请勿手改。\n", encoding="utf-8")
    for module in deps:
        source = KERNEL / "{}.py".format(module)
        if not source.is_file():
            raise SystemExit("E_INPUT：kernel/{}.py 不存在".format(module))
        digest = sha256(source)
        header = "# 构建期内联，请勿手改。\n" "# 源：kernel/{}.py sha256:{}\n".format(
            module, digest
        )
        payload = header + source.read_text(encoding="utf-8")
        (target / "{}.py".format(module)).write_text(payload, encoding="utf-8")
        hashes[module] = digest
    return hashes


def resolve_component(product_cfg: dict) -> Path:
    component_ref = str(product_cfg.get("component") or "")
    component_dir = (ROOT / component_ref).resolve()
    if not str(component_dir).startswith(str(COMPONENTS) + "/") or not component_dir.is_dir():
        raise SystemExit(
            "E_INPUT：component 必须指向 components/ 下的目录：{}".format(component_ref)
        )
    return component_dir


def resolve_overlay(component_dir: Path, variant: dict) -> Path | None:
    overlay_ref = str(variant.get("overlay") or "")
    if not overlay_ref:
        return None
    overlay_dir = (component_dir / overlay_ref).resolve()
    if not str(overlay_dir).startswith(str(component_dir) + "/") or not overlay_dir.is_dir():
        raise SystemExit("E_INPUT：overlay 越界或不存在：{}".format(overlay_ref))
    if not (overlay_dir / "SKILL.md").is_file():
        raise SystemExit("E_INPUT：变体缺少 SKILL.md：{}".format(overlay_ref))
    return overlay_dir


def build_one(product_name: str, variant_name: str, dry_run: bool) -> None:
    product_cfg = load_yaml(PRODUCTS / "{}.yaml".format(product_name))
    component_dir = resolve_component(product_cfg)
    manifest = load_yaml(component_dir / "component.yaml")
    skill_dir = component_dir / str(manifest.get("skill_dir") or "skill")
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SystemExit("E_INPUT：缺少 {}".format(skill_md.relative_to(ROOT)))

    version = str(manifest.get("version") or "")
    declared = frontmatter_value(skill_md.read_text(encoding="utf-8"), "version")
    if declared != version:
        raise SystemExit(
            "E_INPUT：版本不一致 component.yaml={} / SKILL.md={}".format(version, declared)
        )

    variants = product_cfg.get("variants") or {}
    if variant_name not in variants:
        raise SystemExit("E_INPUT：{} 无变体 {}".format(product_name, variant_name))
    variant = variants[variant_name] or {}

    overlay_dir = resolve_overlay(component_dir, variant)
    ship_md = overlay_dir / "SKILL.md" if overlay_dir else skill_md
    ship_text = ship_md.read_text(encoding="utf-8")
    ship_version = frontmatter_value(ship_text, "version")
    ship_name = frontmatter_value(ship_text, "name")
    ship_slug = frontmatter_value(ship_text, "slug")
    ship_license = frontmatter_value(ship_text, "license")

    name = str(variant.get("name") or ship_name or manifest.get("name") or product_name)
    if ship_name and ship_name.isascii() and name not in (ship_name, ship_slug):
        raise SystemExit("E_INPUT：包名 {} 与 SKILL.md name={} 不一致".format(name, ship_name))
    license_decl = str(variant.get("license") or "")
    if license_decl and ship_license and license_decl != ship_license:
        raise SystemExit(
            "E_INPUT：许可不一致 products={} / SKILL.md={}".format(license_decl, ship_license)
        )

    entrypoints = list(variant.get("entrypoints") or manifest.get("entrypoints") or [])
    declared_deps = resolve_deps(manifest.get("kernel_deps") or [])
    scan_dirs = [skill_dir / "scripts"]
    if overlay_dir:
        scan_dirs.append(overlay_dir / "scripts")
    kernel_deps = referenced_modules([path for path in scan_dirs if path.is_dir()])
    undeclared = [dep for dep in kernel_deps if dep not in declared_deps]
    if undeclared:
        raise SystemExit(
            "E_INPUT：脚本引用了未在 kernel_deps 声明的模块：{}".format(", ".join(undeclared))
        )
    dest = (DIST / product_name / variant_name).resolve()
    if DIST.resolve() not in dest.parents or dest == DIST.resolve():
        raise SystemExit("E_INPUT：产物目录越界：{}".format(dest))

    plan = [
        "component: {}".format(component_dir.relative_to(ROOT)),
        "variant: {}{}".format(product_name, "/" + variant_name),
        "dest: {}".format(dest.relative_to(ROOT)),
        "skill: {} (v{})".format(ship_md.relative_to(ROOT), ship_version),
        "channel: {}".format(variant.get("channel") or "-"),
        "overlay: {}".format(overlay_dir.relative_to(ROOT) if overlay_dir else "—"),
        "kernel deps: {}".format(", ".join(kernel_deps) or "—"),
        "metrics contract: {}".format("注入" if variant.get("metrics_contract") else "不注入"),
    ]
    if dry_run:
        print("构建计划（dry-run）：")
        for line in plan:
            print("  " + line)
        return

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(skill_dir, dest, ignore=shutil.ignore_patterns(*IGNORE))
    if overlay_dir:
        shutil.copytree(
            overlay_dir,
            dest,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*IGNORE),
        )

    kernel_hashes = inject_kernel(dest, kernel_deps)

    contracts_used = []
    if variant.get("metrics_contract"):
        source = CONTRACTS / "metrics-contract.json"
        target = dest / "references" / "metrics-contract.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        contracts_used.append(
            {"path": "references/metrics-contract.json", "sha256": sha256(source)}
        )

    for entry in entrypoints:
        if not (dest / entry).is_file():
            raise SystemExit("E_INPUT：产物缺少入口 {}".format(entry))

    build_manifest = {
        "product": product_name,
        "variant": variant_name,
        "name": name,
        "channel": variant.get("channel") or "",
        "product_id": variant.get("product_id") or "",
        "price": variant.get("price") or "",
        "component": str(component_dir.relative_to(ROOT)),
        "component_version": version,
        "skill_version": ship_version,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "skill_sha256": sha256(dest / "SKILL.md"),
        "kernel": kernel_hashes,
        "contracts": contracts_used,
    }
    manifest_path = DIST / product_name / "{}.manifest.json".format(variant_name)
    manifest_path.write_text(
        json.dumps(build_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("构建完成：{}".format(dest.relative_to(ROOT)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="构建 Skill 分发包")
    parser.add_argument("--product", help="产品名，对应 products/<name>.yaml")
    parser.add_argument("--variant", default="", help="变体名；省略时配合 --all 构建全部")
    parser.add_argument("--all", action="store_true", help="构建全部产品与变体")
    parser.add_argument("--dry-run", action="store_true", help="只打印构建计划")
    args = parser.parse_args(argv)

    if not args.all:
        if not args.product:
            parser.error("需要 --product 或 --all")
        variants = load_yaml(PRODUCTS / "{}.yaml".format(args.product)).get("variants") or {}
        targets = [(args.product, args.variant or "free")]
        if args.variant and args.variant not in variants:
            raise SystemExit("E_INPUT：{} 无变体 {}".format(args.product, args.variant))
    else:
        targets = []
        for path in sorted(PRODUCTS.glob("*.yaml")):
            cfg = load_yaml(path)
            for variant_name in cfg.get("variants") or {}:
                targets.append((path.stem, variant_name))

    failed = 0
    for product_name, variant_name in targets:
        try:
            build_one(product_name, variant_name, args.dry_run)
        except SystemExit as exc:
            failed += 1
            print("FAIL {}/{}：{}".format(product_name, variant_name, exc), file=sys.stderr)
    if args.all:
        print("\n合计 {} 个变体，失败 {}".format(len(targets), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
