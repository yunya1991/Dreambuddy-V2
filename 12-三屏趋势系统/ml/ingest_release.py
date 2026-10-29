#!/usr/bin/env python3
"""P1-3 本地辅训 → GitHub Release 模型分发通道：接收/登记段

从 GitHub Release（tag: ml-<vX>）下载模型产物，校验 manifest.json 的
checksum 与 model.pkl 实际 sha256 一致后，登记进本地模型注册表
（ModelVersionManager.register_external，状态 none，待 G7 eval）。

用法（在 12-三屏趋势系统/ 下）:
    python3 ml/ingest_release.py --release ml-v7 [--models-dir ml/models] [--dry-run]

退出码: 0 成功 / 2 缺少 gh CLI 或依赖 / 3 完整性校验失败 / 4 下载或产物缺失
仅使用标准库。
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent  # 12-三屏趋势系统/（包根，保证 ml 包可导入）
REQUIRED_META_FIELDS = ("version", "performance")


def sha256_file(path: Path) -> str:
    """计算文件 sha256"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_version_manager():
    """加载 ModelVersionManager；依赖缺失时告警返回 None（FAIL-OPEN 不阻塞）"""
    if str(PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(PACKAGE_ROOT))
    try:
        from ml.version_manager import ModelVersionManager

        return ModelVersionManager
    except Exception as exc:  # noqa: BLE001 - 依赖缺失需降级为告警
        print(f"[告警] 无法加载 ModelVersionManager（FAIL-OPEN 不阻塞）: {exc}", file=sys.stderr)
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="从 GitHub Release 接收本地辅训模型并登记")
    parser.add_argument("--release", required=True, help="Release tag，如 ml-v7")
    parser.add_argument(
        "--models-dir",
        default=str(SCRIPT_DIR / "models"),
        help="模型注册表根目录（默认 ml/models）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的动作，不下载不登记")
    args = parser.parse_args(argv)

    tag = args.release.strip()
    if not tag:
        print("[错误] --release 不能为空", file=sys.stderr)
        return 1

    # gh 缺失 → 提示并退出 2
    try:
        subprocess.run(
            ["gh", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(
            "[提示] 未检测到 gh CLI，无法下载 release。安装: brew install gh && gh auth login",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        print(f"[dry-run] 将执行: gh release download {tag} --dir <tmpdir>")
        print("[dry-run] 校验: manifest.json.checksum == sha256(model.pkl)")
        print(f"[dry-run] 校验: meta.json 必填字段 {REQUIRED_META_FIELDS}")
        print(
            f"[dry-run] 将调用: ModelVersionManager({args.models_dir}).register_external(<version>, <model.pkl>, <meta>)"
        )
        return 0

    with tempfile.TemporaryDirectory(prefix="ml-release-") as tmpdir:
        proc = subprocess.run(
            ["gh", "release", "download", tag, "--dir", tmpdir],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(
                f"[错误] gh release download 失败（RC={proc.returncode}）: {proc.stderr.strip()}",
                file=sys.stderr,
            )
            return 4

        tmp = Path(tmpdir)
        manifest_path = tmp / "manifest.json"
        model_path = tmp / "model.pkl"
        meta_path = tmp / "meta.json"
        missing = [p.name for p in (manifest_path, model_path, meta_path) if not p.exists()]
        if missing:
            print(f"[错误] release 缺少产物: {', '.join(missing)}", file=sys.stderr)
            return 4

        manifest = json.loads(manifest_path.read_text())
        meta = json.loads(meta_path.read_text())

        # integrity 校验：manifest.checksum 必须与实际 model.pkl 一致，否则拒绝登记
        actual = sha256_file(model_path)
        expected = str(manifest.get("checksum") or "")
        if expected != actual:
            print(
                f"[拒绝] checksum 不一致: manifest={expected or '(空)'} actual={actual}",
                file=sys.stderr,
            )
            return 3
        print(f"[校验] checksum 一致: {actual}")

        # meta 必填字段校验
        missing_fields = [k for k in REQUIRED_META_FIELDS if k not in meta]
        if missing_fields:
            print(f"[拒绝] meta.json 缺少必填字段: {', '.join(missing_fields)}", file=sys.stderr)
            return 3
        if not isinstance(meta.get("performance"), dict):
            print("[拒绝] meta.json performance 不是对象", file=sys.stderr)
            return 3

        # release 名 ml-vX → 版本号；manifest.version 缺失时按 tag 推导（FAIL-OPEN）
        version = str(manifest.get("version") or "").strip()
        if not version:
            version = tag[3:] if tag.startswith("ml-") else tag
            print(f"[告警] manifest.json 缺少 version，按 tag 推导为 {version}", file=sys.stderr)

        VersionManager = load_version_manager()
        if VersionManager is None:
            return 2
        try:
            version_id = VersionManager(args.models_dir).register_external(
                version, str(model_path), meta
            )
        except (ValueError, FileNotFoundError) as exc:
            print(f"[错误] 登记失败: {exc}", file=sys.stderr)
            return 1

        print(
            f"[完成] 已登记 {version_id} → {args.models_dir}/versions/{version_id}（state=none，待 eval）"
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
