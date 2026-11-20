#!/usr/bin/env python3
"""把 kernel/ 模块同步为组件内的 `_kernel/` 注入副本（SPEC §6）。

用法:
    python3 tools/sync_kernel.py --write     # 生成/更新 components/**/scripts/_kernel/
    python3 tools/sync_kernel.py --check     # 只校验，不写盘

规则:
    - 组件源码只写 `from _kernel import ...`，不得 import 源码树 kernel/
    - `_kernel/` 是生成物（.gitignore 已忽略），由本工具与 build_product.py 写入
    - 依赖取 component.yaml 的 kernel_deps，并展开 kernel 模块之间的 `_kernel` 引用
    - 只有真正引用 `_kernel` 的 scripts 目录才生成副本
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("E_ENV：需要 PyYAML（python3 -m pip install pyyaml）", file=sys.stderr)
    raise SystemExit(2) from None

ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ROOT / "components"
KERNEL = ROOT / "kernel"

GENERATED_INIT = "# 生成物：由 tools/sync_kernel.py 写入，请勿手改。\n"
HEADER = (
    "# 生成物：由 tools/sync_kernel.py 写入，请勿手改。\n# 源：kernel/{module}.py sha256:{digest}\n"
)
DEP_RE = re.compile(
    r"from _kernel import ([A-Za-z_]+(?:\s*,\s*[A-Za-z_]+)*)" r"|from _kernel\.([A-Za-z_]+) import"
)
USE_RE = re.compile(r"(^|\n)\s*(from|import)\s+_kernel\b")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_module(module: str) -> bytes:
    path = KERNEL / "{}.py".format(module)
    if not path.is_file():
        raise SystemExit("E_INPUT：kernel/{}.py 不存在".format(module))
    return path.read_bytes()


def resolve_deps(declared) -> list[str]:
    """展开 kernel 模块之间的 `_kernel` 引用，返回有序去重清单。"""
    ordered: list[str] = []
    pending = [str(d) for d in declared or []]
    while pending:
        module = pending.pop(0)
        if module in ordered:
            continue
        if not (KERNEL / "{}.py".format(module)).is_file():
            raise SystemExit("E_INPUT：kernel_deps 引用了不存在的 kernel/{}".format(module))
        ordered.append(module)
        text = (KERNEL / "{}.py".format(module)).read_text(encoding="utf-8")
        for match in DEP_RE.finditer(text):
            names = match.group(1) or match.group(2) or ""
            for name in re.split(r"[,\s]+", names):
                if name and name not in ordered:
                    pending.append(name)
    return ordered


def discover_script_dirs(component_dir: Path) -> list[Path]:
    found = []
    for path in sorted(component_dir.rglob("scripts")):
        if not path.is_dir():
            continue
        if {"__pycache__", "_kernel", "node_modules"} & set(path.parts):
            continue
        found.append(path)
    return found


def uses_kernel(scripts_dir: Path) -> bool:
    for path in scripts_dir.glob("*.py"):
        if USE_RE.search(path.read_text(encoding="utf-8", errors="replace")):
            return True
    return False


def render_package(deps: list[str]) -> dict[str, bytes]:
    files = {"__init__.py": GENERATED_INIT.encode("utf-8")}
    for module in deps:
        raw = read_module(module)
        files["{}.py".format(module)] = (
            HEADER.format(module=module, digest=sha256_bytes(raw)).encode("utf-8") + raw
        )
    return files


def load_declared(component_dir: Path) -> list[str]:
    manifest = component_dir / "component.yaml"
    if not manifest.is_file():
        raise SystemExit("E_CONTRACT：缺少 {}".format(manifest.relative_to(ROOT)))
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    return list(data.get("kernel_deps") or [])


def plan() -> list[tuple[Path, dict[str, bytes] | None]]:
    """返回 (scripts 目录, 期望的 _kernel 文件集合)；None 表示应无副本。"""
    items = []
    for component_dir in sorted(p for p in COMPONENTS.iterdir() if p.is_dir()):
        if component_dir.name.startswith(".") or component_dir.name == "__pycache__":
            continue
        deps = resolve_deps(load_declared(component_dir))
        for scripts_dir in discover_script_dirs(component_dir):
            wanted = render_package(deps) if deps and uses_kernel(scripts_dir) else None
            items.append((scripts_dir, wanted))
    return items


def diff_dir(target: Path, wanted: dict[str, bytes] | None) -> list[str]:
    if wanted is None:
        return [] if not target.exists() else ["多余 {}（该目录不再引用 _kernel）".format(target)]
    problems = []
    if not target.is_dir():
        return ["缺少 {}".format(target)]
    existing = {p.name for p in target.iterdir() if p.is_file() and p.name != "__pycache__"}
    for name, raw in wanted.items():
        path = target / name
        if not path.is_file():
            problems.append("缺少 {}".format(path))
        elif path.read_bytes() != raw:
            problems.append("过期 {}".format(path))
    for name in sorted(existing - set(wanted)):
        problems.append("多余 {}".format(target / name))
    return problems


def write_dir(target: Path, wanted: dict[str, bytes] | None) -> list[str]:
    if wanted is None:
        if target.exists():
            shutil.rmtree(target)
            return ["删除 {}".format(target)]
        return []
    target.mkdir(parents=True, exist_ok=True)
    changes = []
    for name, raw in wanted.items():
        path = target / name
        if not path.is_file() or path.read_bytes() != raw:
            path.write_bytes(raw)
            changes.append("写入 {}".format(path))
    for path in target.iterdir():
        if path.is_file() and path.name not in wanted:
            path.unlink()
            changes.append("删除 {}".format(path))
    return changes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="同步 kernel 注入副本")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="写入 _kernel 副本")
    group.add_argument("--check", action="store_true", help="只校验（默认）")
    args = parser.parse_args(argv)
    if not COMPONENTS.is_dir():
        print("E_INPUT：components/ 不存在", file=sys.stderr)
        return 2

    items = plan()
    if args.write:
        changes = []
        for scripts_dir, wanted in items:
            changes.extend(write_dir(scripts_dir / "_kernel", wanted))
        print("sync_kernel --write：{} 处变更".format(len(changes)))
        for line in changes:
            print("  " + line)
        return 0

    problems = []
    for scripts_dir, wanted in items:
        problems.extend(diff_dir(scripts_dir / "_kernel", wanted))
    if problems:
        print("sync_kernel --check：{} 处不一致".format(len(problems)), file=sys.stderr)
        for line in problems:
            print("  " + line, file=sys.stderr)
        print("请运行：python3 tools/sync_kernel.py --write", file=sys.stderr)
        return 1
    print("sync_kernel --check：{} 个 scripts 目录一致".format(len(items)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
