#!/usr/bin/env python3
"""按 products/<product>.yaml 构建分发包（SPEC §7）。

用法:
    python3 tools/build_product.py --product cogsteward --variant pro --dry-run
    python3 tools/build_product.py --product cogsteward --variant free

构建行为:
    校验 component.yaml 与 SKILL.md 版本一致 → 复制 skill/ → 覆写 frontmatter
    → 内联 kernel/_kernel/ → 注入 contracts/metrics-contract.json → 写构建清单

P4 之前 components/ 与 products/ 不存在，脚本以 E_INPUT 明确退出，不做兜底。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

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
IGNORE = ("__pycache__", "*.pyc", ".DS_Store", ".cm")

FRONT_KEYS = {
    "name": "name",
    "slug": "slug",
    "display_name": "displayName",
    "license": "license",
    "summary": "summary",
}


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


def apply_overrides(text: str, overrides: dict) -> str:
    head, body = split_frontmatter(text)
    for key, value in overrides.items():
        rendered = yaml.safe_dump({key: value}, allow_unicode=True).strip().splitlines()[0]
        pattern = re.compile(r"^{}:\s*.*$".format(re.escape(key)))
        for index, line in enumerate(head):
            if pattern.match(line):
                head[index] = rendered
                break
        else:
            head.append(rendered)
    return "\n".join(["---", *head, "---", *body]) + "\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inject_kernel(dest: Path, deps: list[str]) -> dict:
    hashes = {}
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="构建 Skill 分发包")
    parser.add_argument("--product", required=True, help="产品名，对应 products/<name>.yaml")
    parser.add_argument("--variant", default="free", help="变体名，默认 free")
    parser.add_argument("--dry-run", action="store_true", help="只打印构建计划")
    args = parser.parse_args(argv)

    product_cfg = load_yaml(PRODUCTS / "{}.yaml".format(args.product))
    component_ref = str(product_cfg.get("component") or "")
    component_dir = (ROOT / component_ref).resolve()
    if not str(component_dir).startswith(str(COMPONENTS) + "/") or not component_dir.is_dir():
        raise SystemExit(
            "E_INPUT：component 必须指向 components/ 下的目录：{}".format(component_ref)
        )

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
    if args.variant not in variants:
        raise SystemExit("E_INPUT：variants 无 {}".format(args.variant))
    variant = variants[args.variant] or {}

    name = str(variant.get("name") or manifest.get("name") or args.product)
    dest = (DIST / "{}-{}".format(name, version)).resolve()
    if DIST.resolve() not in dest.parents:
        raise SystemExit("E_INPUT：产物目录越界：{}".format(dest))

    overrides = {
        FRONT_KEYS[key]: variant[key] for key in FRONT_KEYS if variant.get(key) is not None
    }
    entrypoints = manifest.get("entrypoints") or []
    kernel_deps = manifest.get("kernel_deps") or []

    plan = [
        "component: {}".format(component_dir.relative_to(ROOT)),
        "variant: {}{}".format(args.product, "/" + args.variant),
        "dest: {}".format(dest.relative_to(ROOT)),
        "frontmatter overrides: {}".format(json.dumps(overrides, ensure_ascii=False)),
        "kernel deps: {}".format(", ".join(kernel_deps) or "—"),
        "metrics contract: {}".format("注入" if variant.get("metrics_contract") else "不注入"),
    ]
    if args.dry_run:
        print("构建计划（dry-run）：")
        for line in plan:
            print("  " + line)
        return 0

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(skill_dir, dest, ignore=shutil.ignore_patterns(*IGNORE))

    updated = apply_overrides((dest / "SKILL.md").read_text(encoding="utf-8"), overrides)
    (dest / "SKILL.md").write_text(updated, encoding="utf-8")

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
        "product": args.product,
        "variant": args.variant,
        "name": name,
        "component": str(component_dir.relative_to(ROOT)),
        "component_version": version,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "skill_sha256": sha256(dest / "SKILL.md"),
        "kernel": kernel_hashes,
        "contracts": contracts_used,
    }
    (DIST / "{}-{}.manifest.json".format(name, version)).write_text(
        json.dumps(build_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("构建完成：{}".format(dest.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
