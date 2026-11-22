"""把手机 AGENT 唯一主仓同步到 59 域组件（契约单一源 + 文件级复制）。

设计要点（P0/P1 口径）：
- 唯一源：`$SHUNFENGCHE_REPO`（默认 `~/Documents/顺风车业务`）下的
  `mobile-reservation-assist/`；59 侧只保留分发副本。
- `component.yaml` 的动作块由主仓生成，59 侧只保留自己的元数据头；禁止手改。
- `skill/scripts/mra.py` 是代理壳，永远由本脚本重建，不被主仓实现覆盖。
- 复制按文件进行，不建 staging 目录（沙箱只允许改文件、不允许新建目录）。
- 读外置盘偶发 Errno 60 / 超时，统一重试。

用法：
    python3 tools/sync_mobile.py --check        # 漂移检查（主仓缺失时跳过，退出 0）
    python3 tools/sync_mobile.py --check-local  # 只检查副本与 manifest 一致（供 make check）
    python3 tools/sync_mobile.py --write        # 主仓 → 59 副本，并写 manifest
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

MODULE_ROOT = Path(__file__).resolve().parents[1]
DEST = MODULE_ROOT / "components" / "mobile-reservation-assist"
DEFAULT_SOURCE = Path.home() / "Documents" / "顺风车业务"
MANIFEST = DEST / ".mobile_sync.json"
PROXY_REL = "skill/scripts/mra.py"
PROXY_MARKER = "59 域代理壳"

# 同步范围（相对 mobile-reservation-assist/）；SKILL.md 属 59 营销文案，不同步
SYNC_DIRS = ("skill/scripts", "skill/references", "tests", "docs")
IGNORE_NAMES = {"__pycache__", ".pytest_cache"}
IGNORE_SUFFIXES = {".pyc", ".pyo"}
# 主仓里与 Web 桥接 / 安卓 AutoJS 源码强耦合、不属于组件边界的测试
SKIP_FILES = {"test_phone_bridge.py", "test_device_accept.py"}
# 59 副本保留的元数据头字段
HEADER_KEYS = (
    "name",
    "display_name",
    "version",
    "family",
    "lifecycle",
    "summary",
    "entrypoints",
    "kernel_deps",
    "output_contract",
    "products",
    "tests",
    "docs",
)

PROXY_TEMPLATE = '''#!/usr/bin/env python3
"""59 域代理壳：转发到手机 AGENT 主仓 mra.py（实现与状态只一份）。

解析顺序：MOBILE_AGENT_CLI → ~/.config/dreambuddy/mobile_agent.path → 默认路径。
本文件由 tools/sync_mobile.py 生成，请勿手改。
"""

import os
import sys
from pathlib import Path

PROXY_MARKER = "{marker}"
DEFAULT_CLI = Path.home() / "Documents" / "顺风车业务" / "mobile-reservation-assist" / "skill" / "scripts" / "mra.py"


if __name__ != "__main__":
    # 被组件单测 import 时不 exec 主仓 CLI，交给 unittest 跳过整个用例模块
    import unittest

    raise unittest.SkipTest("59 域副本：mra 为代理壳，真实实现与用例在主仓执行")


def _resolve():
    env = os.environ.get("MOBILE_AGENT_CLI")
    if env:
        return Path(env).expanduser()
    cfg = Path.home() / ".config" / "dreambuddy" / "mobile_agent.path"
    if cfg.is_file():
        try:
            candidate = Path(cfg.read_text(encoding="utf-8").strip()).expanduser()
        except OSError:
            candidate = None
        if candidate and candidate.is_file():
            return candidate
    return DEFAULT_CLI


cli = _resolve()
if not cli.is_file():
    sys.stderr.write("E_CLI：未找到手机 AGENT 主仓 mra.py：{{}}\\n".format(cli))
    raise SystemExit(2)

os.execv(sys.executable, [sys.executable, str(cli), *sys.argv[1:]])
'''


def _read_bytes(path: Path, attempts: int = 3) -> bytes:
    last: Optional[OSError] = None
    for _ in range(attempts):
        try:
            return path.read_bytes()
        except OSError as exc:
            last = exc
            time.sleep(0.5)
    raise last  # type: ignore[misc]


def _read_text(path: Path, attempts: int = 3) -> str:
    return _read_bytes(path, attempts).decode("utf-8")


def source_root() -> Path:
    return Path(os.environ.get("SHUNFENGCHE_REPO", str(DEFAULT_SOURCE)))


def source_component() -> Path:
    return source_root() / "mobile-reservation-assist"


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in SKIP_FILES:
            continue
        if any(part in IGNORE_NAMES for part in path.parts):
            continue
        if path.suffix in IGNORE_SUFFIXES:
            continue
        yield path


def collect_hashes(source: Path) -> Dict[str, str]:
    """同步文件的相对路径 → sha256（不含代理壳与自维护文件）。"""
    hashes: Dict[str, str] = {}
    for rel_dir in SYNC_DIRS:
        root = source / rel_dir
        if not root.is_dir():
            continue
        for path in _iter_files(root):
            rel = path.relative_to(source).as_posix()
            if rel == PROXY_REL or rel in {".mobile_sync.json", "component.yaml"}:
                continue
            if rel.startswith("skill/"):
                hashes[rel] = hashlib.sha256(_read_bytes(path)).hexdigest()
            else:
                hashes[rel] = hashlib.sha256(_read_bytes(path)).hexdigest()
    return hashes


def tree_hash(source: Path) -> str:
    digest = hashlib.sha256()
    for rel, sha in sorted(collect_hashes(source).items()):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def source_version(source: Path) -> str:
    manifest = source / "component.yaml"
    for line in _read_text(manifest).splitlines():
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


def _load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(_read_text(path)) or {}


def load_actions(path: Path) -> List[Dict[str, Any]]:
    data = _load_yaml(path)
    actions = data.get("actions") or []
    if not isinstance(actions, list):
        raise ValueError("{} 的 actions 必须是列表".format(path))
    for action in actions:
        if not isinstance(action, dict) or not action.get("name") or not action.get("args"):
            raise ValueError("{} 存在缺少 name/args 的动作：{!r}".format(path, action))
        if action.get("safety") not in {"read", "write", "ui", "irreversible"}:
            raise ValueError("{} 动作 {} 的 safety 非法".format(path, action.get("name")))
    return actions


def build_component(source: Path) -> str:
    """59 元数据头 + 主仓版本/动作块 → component.yaml 文本。"""
    current_path = DEST / "component.yaml"
    header: Dict[str, Any] = {}
    if current_path.is_file():
        existing = _load_yaml(current_path)
        header = {key: existing[key] for key in HEADER_KEYS if key in existing}
    if not header:
        header = {
            "name": "mobile-reservation-assist",
            "display_name": "手机预约助手 Mobile Reservation Assist",
            "family": "reservation-assist",
            "lifecycle": "draft",
            "summary": "手机预约助手组件（59 侧分发副本，脚本经代理壳转发主仓）。",
            "entrypoints": ["scripts/mra.py"],
            "kernel_deps": [],
            "output_contract": "reservation.v1",
            "products": [],
            "tests": {"dir": "tests", "entry": "python3 -m unittest discover -s tests -v"},
            "docs": [
                "docs/ENGINEERING_INDEX.md",
                "docs/TECHNICAL_DESIGN.md",
                "docs/API_SPEC.md",
                "docs/CHANGELOG.md",
            ],
        }
    header["version"] = source_version(source)
    header["actions"] = load_actions(source / "component.yaml")
    text = yaml.safe_dump(header, allow_unicode=True, sort_keys=False, width=1000)
    banner = (
        "# 本文件的 actions 块由 tools/sync_mobile.py 从手机 AGENT 主仓生成，请勿手改。\n"
        "# 唯一源：顺风车业务/mobile-reservation-assist/component.yaml\n"
    )
    return banner + text


def write_proxy() -> None:
    path = DEST / PROXY_REL
    text = PROXY_TEMPLATE.format(marker=PROXY_MARKER)
    if path.is_file() and _read_text(path) == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o755)


def _write_file(src: Path, dst: Path) -> bool:
    payload = _read_bytes(src)
    if dst.is_file() and _read_bytes(dst) == payload:
        return False
    if not dst.parent.is_dir():
        dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(payload)
    return True


def stamp_skill_version(version: str) -> bool:
    """59 侧 SKILL.md 属营销文案，不整体同步，只把版本号对齐主仓。"""
    path = DEST / "skill" / "SKILL.md"
    if not path.is_file():
        return False
    text = _read_text(path)
    stamped = re.sub(r"^version:\s*.*$", "version: {}".format(version), text, count=1, flags=re.M)
    if stamped == text:
        return False
    path.write_text(stamped, encoding="utf-8")
    return True


def write() -> int:
    source = source_component()
    if not source.is_dir():
        print("E_SOURCE：未找到主仓 {}".format(source), file=sys.stderr)
        return 2
    changed = 0
    for rel_dir in SYNC_DIRS:
        root = source / rel_dir
        if not root.is_dir():
            continue
        for src in _iter_files(root):
            rel = src.relative_to(source).as_posix()
            if rel == PROXY_REL:
                continue
            if _write_file(src, DEST / rel):
                changed += 1
    write_proxy()
    version = source_version(source)
    if stamp_skill_version(version):
        changed += 1
    component_text = build_component(source)
    component_path = DEST / "component.yaml"
    if not component_path.is_file() or _read_text(component_path) != component_text:
        component_path.write_text(component_text, encoding="utf-8")
        changed += 1
    hashes = collect_hashes(source)
    payload = {
        "canonical_version": source_version(source),
        "source_hash": tree_hash(source),
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "files": hashes,
    }
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "OK：已同步手机组件 {}（{} 个文件 / {} 个动作，变更 {} 个文件）".format(
            payload["canonical_version"],
            len(hashes),
            len(load_actions(source / "component.yaml")),
            changed,
        )
    )
    return 0


def cli_paths(script: Path) -> List[tuple]:
    """从 argparse 声明里解析全部子命令路径（用于发现未登记命令）。"""
    tree = ast.parse(_read_text(script))
    assigns = sorted(
        [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
        ],
        key=lambda node: node.lineno,
    )
    paths: Dict[str, tuple] = {"parser": ()}
    commands: List[tuple] = []
    for _ in range(3):
        for node in assigns:
            call = node.value
            fn = call.func
            var = node.targets[0].id if isinstance(node.targets[0], ast.Name) else None
            base = fn.value.id if isinstance(fn.value, ast.Name) else None
            if fn.attr == "add_subparsers":
                if var:
                    paths[var] = paths.get(base, ())
            elif fn.attr == "add_parser":
                name = (
                    call.args[0].value
                    if call.args and isinstance(call.args[0], ast.Constant)
                    else None
                )
                if not isinstance(name, str):
                    continue
                path = paths.get(base, ()) + (name,)
                if var:
                    paths[var] = path
                commands.append(path)
    return commands


def check(local_only: bool = False) -> int:
    source = source_component()
    failures: List[str] = []
    warnings: List[str] = []
    if not DEST.is_dir():
        print("SKIP：59 副本不存在")
        return 0
    if not source.is_dir():
        print("SKIP：主仓不存在（{}）".format(source))
        return 0

    component = DEST / "component.yaml"
    proxy = DEST / PROXY_REL
    if not proxy.is_file() or PROXY_MARKER not in _read_text(proxy):
        failures.append("代理壳缺失或被替换：{}".format(PROXY_REL))
    elif proxy.stat().st_size > 20000:
        failures.append("代理壳异常膨胀（{} 字节）".format(proxy.stat().st_size))

    manifest: Dict[str, Any] = {}
    if MANIFEST.is_file():
        try:
            manifest = json.loads(_read_text(MANIFEST))
        except json.JSONDecodeError:
            failures.append("manifest 不是合法 JSON")
    else:
        failures.append("缺少 manifest（请执行 --write）")

    expected_version = source_version(source)
    actual_version = (_load_yaml(component).get("version") if component.is_file() else None) or ""
    if expected_version != actual_version:
        failures.append("版本漂移：主仓 {} != 副本 {}".format(expected_version, actual_version))

    source_actions = load_actions(source / "component.yaml")
    try:
        dest_actions = load_actions(component) if component.is_file() else []
    except ValueError as exc:
        dest_actions = []
        failures.append(str(exc))
    if [a.get("name") for a in source_actions] != [a.get("name") for a in dest_actions]:
        failures.append(
            "动作清单未同步（主仓 {} 个 / 副本 {} 个）".format(
                len(source_actions), len(dest_actions)
            )
        )

    if not local_only:
        expected_hashes = collect_hashes(source)
        for rel, sha in sorted(expected_hashes.items()):
            target = DEST / rel
            if not target.is_file():
                failures.append("遗漏文件：{}".format(rel))
            elif hashlib.sha256(_read_bytes(target)).hexdigest() != sha:
                failures.append("内容漂移：{}".format(rel))
        for rel in sorted(set(manifest.get("files") or {}) - set(expected_hashes)):
            failures.append("主仓已删除但副本仍存在：{}".format(rel))

        commands = cli_paths(source / "skill" / "scripts" / "mra.py")
        declared = [tuple(str(item) for item in action["args"]) for action in source_actions]
        for args in declared:
            if args not in commands:
                failures.append("动作引用了不存在的子命令：{}".format(" ".join(args)))
        leaves = {p for p in commands if not any(q != p and q[: len(p)] == p for q in commands)}
        missing = sorted(" ".join(p) for p in leaves if not any(p[: len(a)] == a for a in declared))
        for name in missing:
            warnings.append("CLI 命令未登记：{}".format(name))

    if failures:
        for item in failures:
            print("FAIL：{}".format(item))
        for item in warnings:
            print("WARN：{}".format(item))
        return 1
    print(
        "OK：手机组件与主仓 {} 一致（{} 个文件 / {} 个动作）".format(
            expected_version, len(manifest.get("files") or {}), len(source_actions)
        )
    )
    for item in warnings:
        print("WARN：{}".format(item))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="同步手机 AGENT 主仓到 59 域组件")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="检查副本与主仓是否一致（含实时漂移）")
    group.add_argument(
        "--check-local", action="store_true", help="只检查副本与 manifest 是否一致（供 make check）"
    )
    group.add_argument("--write", action="store_true", help="把主仓复制到 59 副本")
    args = parser.parse_args(argv)
    if args.write:
        return write()
    return check(local_only=bool(args.check_local))


if __name__ == "__main__":
    raise SystemExit(main())
