"""把手机 AGENT 唯一主仓同步到 59 域组件（只复制，不改写业务代码）。

唯一源：`$SHUNFENGCHE_REPO`（默认 `~/Documents/顺风车业务`）下的
`mobile-reservation-assist/`。59 侧只保留分发副本；`skill/SKILL.md` 属 59 营销文案，
不参与同步，其余脚本/测试/参考文档以主仓为准。

用法：
    python3 tools/sync_mobile.py --check   # 漂移检查（主仓缺失时跳过，退出 0）
    python3 tools/sync_mobile.py --write   # 复制主仓 → 59 副本并写 manifest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

MODULE_ROOT = Path(__file__).resolve().parents[1]
DEST = MODULE_ROOT / "components" / "mobile-reservation-assist"
DEFAULT_SOURCE = Path.home() / "Documents" / "顺风车业务"
MANIFEST = DEST / ".mobile_sync.json"

# 同步范围（相对 mobile-reservation-assist/）；SKILL.md 与 component.yaml 由 59 自维护
SYNC_PATHS = (
    "skill/scripts",
    "skill/references",
    "tests",
    "docs",
)
IGNORE_NAMES = {"__pycache__", ".pytest_cache"}
IGNORE_SUFFIXES = {".pyc", ".pyo"}
# 主仓里与 Web 桥接强耦合、不属于组件边界的测试（import src.services）
SKIP_FILES = {"test_phone_bridge.py"}


def source_root() -> Path:
    return Path(os.environ.get("SHUNFENGCHE_REPO", str(DEFAULT_SOURCE)))


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


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _iter_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def source_version(source: Path) -> str:
    manifest = source / "component.yaml"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


def collect_hashes(source: Path) -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    for rel in SYNC_PATHS:
        base = source / rel
        if not base.exists():
            continue
        if base.is_file():
            hashes[rel] = hashlib.sha256(base.read_bytes()).hexdigest()
            continue
        for path in _iter_files(base):
            hashes[path.relative_to(source).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return hashes


def load_manifest() -> dict:
    if not MANIFEST.exists():
        return {}
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def check(local_only: bool = False) -> int:
    source = source_root() / "mobile-reservation-assist"
    if not local_only and not source.exists():
        print("skip：未找到主仓 {}，跳过手机组件同步检查".format(source))
        return 0
    manifest = load_manifest()
    if not manifest:
        print("FAIL：缺少 {}，请先执行 tools/sync_mobile.py --write".format(MANIFEST.name))
        return 1
    recorded = manifest.get("files") or {}
    local_drift = [
        rel
        for rel, sha in recorded.items()
        if (DEST / rel).exists() and hashlib.sha256((DEST / rel).read_bytes()).hexdigest() != sha
    ]
    if local_drift:
        print("FAIL：副本被本地修改：{}".format(", ".join(sorted(local_drift)[:5])))
        return 1
    missing = [rel for rel in recorded if not (DEST / rel).exists()]
    if missing:
        print("FAIL：副本缺少 {} 个文件：{}".format(len(missing), ", ".join(sorted(missing)[:5])))
        return 1
    if local_only:
        print("OK：副本与 manifest 一致（{} 个文件，未比对主仓实时状态）".format(len(recorded)))
        return 0

    version = source_version(source)
    problems: List[str] = []
    if manifest.get("canonical_version") != version:
        problems.append(
            "版本漂移：主仓 {} != 副本 {}".format(version, manifest.get("canonical_version"))
        )
    expected = collect_hashes(source)
    changed = sorted(rel for rel, sha in expected.items() if recorded.get(rel) != sha)
    removed = sorted(rel for rel in recorded if rel not in expected)
    if changed:
        problems.append("主仓有 {} 个文件未同步：{}".format(len(changed), ", ".join(changed[:5])))
    if removed:
        problems.append(
            "主仓已删除 {} 个文件，副本仍保留：{}".format(len(removed), ", ".join(removed[:5]))
        )
    if problems:
        for item in problems:
            print("FAIL：" + item)
        return 1
    print("OK：手机组件与主仓 {} 一致（{} 个文件）".format(version, len(expected)))
    return 0


def display_path(path: Path) -> str:
    """manifest 里不写绝对路径（G2 禁写死 /Users/），家目录显示为 ~/。"""
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return path.as_posix()


def write() -> int:
    source = source_root() / "mobile-reservation-assist"
    if not source.exists():
        print("E_SOURCE：未找到主仓 {}".format(source), file=sys.stderr)
        return 2
    for rel in SYNC_PATHS:
        src = source / rel
        dst = DEST / rel
        if not src.exists():
            continue
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(
                src,
                dst,
                ignore=shutil.ignore_patterns(
                    "__pycache__", ".pytest_cache", "*.pyc", "*.pyo", *sorted(SKIP_FILES)
                ),
            )
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    hashes = collect_hashes(source)
    payload = {
        "canonical_repo": display_path(source_root()),
        "canonical_version": source_version(source),
        "source_hash": tree_hash(source),
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "files": hashes,
    }
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("OK：已同步手机组件 {}（{} 个文件）".format(payload["canonical_version"], len(hashes)))
    return 0


def main(argv: List[str] | None = None) -> int:
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
