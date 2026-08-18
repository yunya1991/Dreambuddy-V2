import argparse
import json
import os
import shutil
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_POLICIES = [
    {"path": "raw", "days": 7, "keep_last": 40},
    {"path": "outputs", "days": 30, "keep_last": 80},
    {"path": "flow/raw", "days": 7, "keep_last": 40},
    {"path": "flow/outputs", "days": 30, "keep_last": 80},
]


def _now_ts(now_ts: float | None = None) -> float:
    if isinstance(now_ts, (int, float)):
        return float(now_ts)
    return float(time.time())


def _all_files(dir_path: Path) -> list[Path]:
    out: list[Path] = []
    if not dir_path.exists() or not dir_path.is_dir():
        return out
    for fp in dir_path.rglob("*"):
        if not fp.is_file():
            continue
        if fp.name == ".gitkeep":
            continue
        out.append(fp)
    return out


def collect_expired_files(dir_path: Path, days: int, keep_last: int, now_ts: float | None = None) -> list[Path]:
    files = _all_files(dir_path)
    if not files:
        return []
    rows: list[tuple[Path, float]] = []
    for fp in files:
        try:
            mt = float(fp.stat().st_mtime)
        except Exception:
            mt = 0.0
        rows.append((fp, mt))
    rows.sort(key=lambda x: x[1], reverse=True)
    keep_n = max(0, int(keep_last))
    protected = {str(x[0]) for x in rows[:keep_n]}
    cutoff = _now_ts(now_ts) - max(0, int(days)) * 24 * 3600
    expired: list[Path] = []
    for fp, mt in rows:
        if str(fp) in protected:
            continue
        if mt < cutoff:
            expired.append(fp)
    return expired


def _safe_rel(project_root: Path, fp: Path) -> Path:
    rel = fp.resolve().relative_to(project_root.resolve())
    return Path(str(rel))


def _archive_stamp(now_ts: float | None = None) -> str:
    return datetime.fromtimestamp(_now_ts(now_ts), tz=timezone.utc).strftime("%Y%m%d_%H%M%S")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _index_append(index_file: Path, obj: dict) -> None:
    _ensure_dir(index_file.parent)
    with open(index_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def archive_expired(
    project_root: Path,
    policies: list[dict],
    archive_root: Path,
    dry_run: bool,
    now_ts: float | None = None,
) -> dict:
    project_root = Path(project_root).resolve()
    archive_root = Path(archive_root).resolve()
    stamp = _archive_stamp(now_ts)
    stage_name = f"artifacts_batch_{stamp}"
    stage_dir = archive_root / stage_name
    tar_path = archive_root / f"{stage_name}.tar.gz"
    picked: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for p in policies:
        rel = str(p.get("path") or "").strip()
        if not rel:
            continue
        base = project_root / rel
        days = int(p.get("days") or 0)
        keep_last = int(p.get("keep_last") or 0)
        for fp in collect_expired_files(base, days=days, keep_last=keep_last, now_ts=now_ts):
            k = str(fp.resolve())
            if k in seen:
                continue
            seen.add(k)
            picked.append((fp, rel))
    moved: list[dict] = []
    if dry_run:
        for fp, _ in picked:
            rel = _safe_rel(project_root, fp)
            moved.append(
                {
                    "original_rel": str(rel),
                    "archive_rel": str(Path(stage_name) / rel),
                    "size": int(fp.stat().st_size) if fp.exists() else 0,
                    "mtime": float(fp.stat().st_mtime) if fp.exists() else 0.0,
                }
            )
        return {
            "ok": True,
            "dry_run": True,
            "project_root": str(project_root),
            "archive_root": str(archive_root),
            "archive_file": str(tar_path),
            "moved_files": int(len(moved)),
            "files": moved,
        }
    if not picked:
        return {
            "ok": True,
            "dry_run": False,
            "project_root": str(project_root),
            "archive_root": str(archive_root),
            "archive_file": str(tar_path),
            "moved_files": 0,
            "files": [],
        }
    _ensure_dir(stage_dir)
    for fp, _ in picked:
        if not fp.exists() or not fp.is_file():
            continue
        rel = _safe_rel(project_root, fp)
        dst = stage_dir / rel
        _ensure_dir(dst.parent)
        st = fp.stat()
        shutil.move(str(fp), str(dst))
        moved.append(
            {
                "original_rel": str(rel),
                "archive_rel": str(Path(stage_name) / rel),
                "size": int(st.st_size),
                "mtime": float(st.st_mtime),
            }
        )
    manifest = {
        "ok": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root),
        "archive_root": str(archive_root),
        "archive_file": str(tar_path),
        "moved_files": int(len(moved)),
        "files": moved,
        "policies": policies,
    }
    with open(stage_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(stage_dir / "manifest_paths.txt", "w", encoding="utf-8") as f:
        for row in moved:
            f.write(str(row.get("original_rel") or "") + "\n")
    _ensure_dir(archive_root)
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(stage_dir, arcname=stage_name)
    shutil.rmtree(stage_dir, ignore_errors=True)
    _index_append(
        archive_root / "index.jsonl",
        {
            "created_at": manifest["created_at"],
            "archive_file": str(tar_path),
            "moved_files": int(len(moved)),
        },
    )
    return manifest


def _find_latest_archive(archive_root: Path) -> Path | None:
    if not archive_root.exists():
        return None
    items = sorted(archive_root.glob("artifacts_batch_*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True)
    return items[0] if items else None


def restore_archive(project_root: Path, archive_file: Path, overwrite: bool) -> dict:
    project_root = Path(project_root).resolve()
    archive_file = Path(archive_file).resolve()
    if not archive_file.exists():
        return {"ok": False, "error": "archive_not_found", "archive_file": str(archive_file)}
    restored = 0
    skipped = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        with tarfile.open(archive_file, "r:gz") as tar:
            tar.extractall(tmp)
        manifest_files = list(tmp.rglob("manifest.json"))
        if not manifest_files:
            return {"ok": False, "error": "manifest_not_found", "archive_file": str(archive_file)}
        manifest_path = manifest_files[0]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
        for row in files:
            if not isinstance(row, dict):
                continue
            archive_rel = str(row.get("archive_rel") or "").strip()
            original_rel = str(row.get("original_rel") or "").strip()
            if not archive_rel or not original_rel:
                continue
            src = tmp / archive_rel
            dst = project_root / original_rel
            if not src.exists():
                continue
            if dst.exists() and (not overwrite):
                skipped += 1
                continue
            _ensure_dir(dst.parent)
            if dst.exists() and overwrite:
                if dst.is_file():
                    dst.unlink()
                elif dst.is_dir():
                    shutil.rmtree(dst, ignore_errors=True)
            shutil.move(str(src), str(dst))
            restored += 1
    return {
        "ok": True,
        "archive_file": str(archive_file),
        "project_root": str(project_root),
        "restored_files": int(restored),
        "skipped_files": int(skipped),
        "overwrite": bool(overwrite),
    }


def _policy_from_env() -> list[dict]:
    env = str(os.environ.get("ARTIFACT_RETENTION_POLICIES_JSON") or "").strip()
    if not env:
        return list(DEFAULT_POLICIES)
    try:
        obj = json.loads(env)
    except Exception:
        return list(DEFAULT_POLICIES)
    if not isinstance(obj, list):
        return list(DEFAULT_POLICIES)
    out: list[dict] = []
    for row in obj:
        if not isinstance(row, dict):
            continue
        p = str(row.get("path") or "").strip()
        if not p:
            continue
        out.append(
            {
                "path": p,
                "days": int(row.get("days") or 0),
                "keep_last": int(row.get("keep_last") or 0),
            }
        )
    return out or list(DEFAULT_POLICIES)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_cleanup = sub.add_parser("cleanup")
    p_cleanup.add_argument("--project-root", default=str(Path(__file__).resolve().parent.parent))
    p_cleanup.add_argument("--archive-root", default="")
    p_cleanup.add_argument("--dry-run", action="store_true")
    p_cleanup.add_argument("--days-raw", type=int, default=None)
    p_cleanup.add_argument("--days-outputs", type=int, default=None)
    p_cleanup.add_argument("--days-flow-raw", type=int, default=None)
    p_cleanup.add_argument("--days-flow-outputs", type=int, default=None)
    p_cleanup.add_argument("--keep-last-raw", type=int, default=None)
    p_cleanup.add_argument("--keep-last-outputs", type=int, default=None)
    p_cleanup.add_argument("--keep-last-flow-raw", type=int, default=None)
    p_cleanup.add_argument("--keep-last-flow-outputs", type=int, default=None)
    p_restore = sub.add_parser("restore")
    p_restore.add_argument("--project-root", default=str(Path(__file__).resolve().parent.parent))
    p_restore.add_argument("--archive-root", default="")
    p_restore.add_argument("--archive-file", default="latest")
    p_restore.add_argument("--overwrite", action="store_true")
    p_list = sub.add_parser("list")
    p_list.add_argument("--project-root", default=str(Path(__file__).resolve().parent.parent))
    p_list.add_argument("--archive-root", default="")
    return parser


def _merge_override(base: list[dict], args: argparse.Namespace) -> list[dict]:
    rows = [dict(x) for x in base]
    mapping = {
        "raw": ("days_raw", "keep_last_raw"),
        "outputs": ("days_outputs", "keep_last_outputs"),
        "flow/raw": ("days_flow_raw", "keep_last_flow_raw"),
        "flow/outputs": ("days_flow_outputs", "keep_last_flow_outputs"),
    }
    for row in rows:
        path = str(row.get("path") or "")
        if path not in mapping:
            continue
        k_days, k_keep = mapping[path]
        v_days = getattr(args, k_days, None)
        v_keep = getattr(args, k_keep, None)
        if isinstance(v_days, int):
            row["days"] = int(v_days)
        if isinstance(v_keep, int):
            row["keep_last"] = int(v_keep)
    return rows


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    project_root = Path(str(args.project_root)).resolve()
    archive_root = Path(str(args.archive_root)).resolve() if str(args.archive_root).strip() else (project_root / "archive" / "artifacts")
    if args.cmd == "cleanup":
        policies = _merge_override(_policy_from_env(), args)
        res = archive_expired(
            project_root=project_root,
            policies=policies,
            archive_root=archive_root,
            dry_run=bool(args.dry_run),
            now_ts=time.time(),
        )
        print(json.dumps(res, ensure_ascii=False))
        return 0 if bool(res.get("ok")) else 1
    if args.cmd == "list":
        latest = _find_latest_archive(archive_root)
        rows = sorted(archive_root.glob("artifacts_batch_*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True) if archive_root.exists() else []
        out = {
            "ok": True,
            "archive_root": str(archive_root),
            "latest": (str(latest) if latest else None),
            "archives": [str(x) for x in rows[:100]],
        }
        print(json.dumps(out, ensure_ascii=False))
        return 0
    archive_file = str(args.archive_file or "").strip()
    if archive_file == "latest":
        latest = _find_latest_archive(archive_root)
        if latest is None:
            print(json.dumps({"ok": False, "error": "latest_archive_not_found", "archive_root": str(archive_root)}, ensure_ascii=False))
            return 1
        target_archive = latest
    else:
        target_archive = Path(archive_file).resolve()
    res = restore_archive(project_root=project_root, archive_file=target_archive, overwrite=bool(args.overwrite))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if bool(res.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
