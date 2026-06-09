import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence


ACTION_DIR = Path(__file__).resolve().parent
if str(ACTION_DIR) not in sys.path:
    sys.path.insert(0, str(ACTION_DIR))

from format_report_md import format_report_md


@dataclass(frozen=True)
class DriftVerdict:
    verdict: str
    reason_codes: List[str]
    report: Dict[str, Any]


class DriftGuardError(RuntimeError):
    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise DriftGuardError("CONFIG_MISSING")

    suffix = path.suffix.lower()
    text = _read_text(path)

    if suffix == ".json":
        try:
            cfg = json.loads(text)
        except Exception as exc:
            raise DriftGuardError("CONFIG_INVALID") from exc
    elif suffix in (".yml", ".yaml"):
        try:
            yaml = importlib.import_module("yaml")
        except Exception as exc:
            raise DriftGuardError("CONFIG_YAML_UNSUPPORTED") from exc
        try:
            cfg = yaml.safe_load(text)
        except Exception as exc:
            raise DriftGuardError("CONFIG_INVALID") from exc
    else:
        raise DriftGuardError("CONFIG_UNSUPPORTED_FORMAT")

    if not isinstance(cfg, dict):
        raise DriftGuardError("CONFIG_INVALID")
    return cfg


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _run(cmd: Sequence[str]) -> str:
    out = subprocess.check_output(list(cmd), stderr=subprocess.STDOUT)
    return out.decode("utf-8", errors="replace").strip()


def _diff_files(base_sha: str, head_sha: str) -> List[str]:
    try:
        out = _run(["git", "diff", "--name-only", f"{base_sha}..{head_sha}"])
    except Exception:
        _run(["git", "fetch", "--no-tags", "origin", base_sha, head_sha])
        out = _run(["git", "diff", "--name-only", f"{base_sha}..{head_sha}"])
    return [line.strip().strip('"') for line in out.splitlines() if line.strip()]


def _path_matches(pattern: str, file_path: str) -> bool:
    try:
        return PurePosixPath(file_path).match(pattern)
    except Exception:
        return False


def _match_module(modules: Dict[str, Any], file_path: str) -> Optional[str]:
    if not isinstance(modules, dict):
        return None
    for name in sorted(modules.keys()):
        module_cfg = modules.get(name) or {}
        if not isinstance(module_cfg, dict):
            continue
        patterns = module_cfg.get("paths") or []
        if not isinstance(patterns, list):
            continue
        for pattern in patterns:
            if isinstance(pattern, str) and _path_matches(pattern, file_path):
                return str(name)
    return None


def _normalize_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return []


def evaluate(
    repo_root: Path,
    config_path: Path,
    mode: str,
    change_class: str,
    base_sha: Optional[str],
    head_sha: Optional[str],
) -> DriftVerdict:
    cfg = _load_config(config_path)
    modules = cfg.get("modules", {})
    change_classes = cfg.get("change_classes", {})
    required_docs = _normalize_list(cfg.get("required_docs", []))

    reason_codes: List[str] = []
    report: Dict[str, Any] = {
        "repo_root": str(repo_root),
        "mode": mode,
        "config_path": str(config_path),
        "change_class": change_class,
        "required_docs": required_docs,
        "docs_hashes": {},
        "changed_files": [],
        "changed_files_by_module": {},
        "reason_codes": []
    }

    if not isinstance(change_classes, dict):
        reason_codes.append("CONFIG_INVALID")
        change_classes = {}

    if change_class not in change_classes:
        reason_codes.append("UNKNOWN_CHANGE_CLASS")

    class_cfg = change_classes.get(change_class) or {}
    if not isinstance(class_cfg, dict):
        class_cfg = {}
    allowed_modules = set(_normalize_list(class_cfg.get("allowed_modules", [])))

    docs_hashes: Dict[str, Optional[str]] = {}
    for rel in required_docs:
        if not isinstance(rel, str):
            reason_codes.append("CONFIG_INVALID")
            continue
        file_path = repo_root / rel
        if not file_path.exists():
            reason_codes.append("REQUIRED_DOC_MISSING")
            docs_hashes[rel] = None
        else:
            docs_hashes[rel] = _hash_file(file_path)
    report["docs_hashes"] = docs_hashes

    if mode == "pull_request" and (not base_sha or not head_sha):
        reason_codes.append("MISSING_SHA")

    changed_files: List[str] = []
    if base_sha and head_sha:
        try:
            changed_files = _diff_files(base_sha, head_sha)
        except Exception:
            reason_codes.append("GIT_DIFF_FAILED")
            changed_files = []
    report["changed_files"] = changed_files

    by_module: Dict[str, List[str]] = {}
    unknown: List[str] = []
    for file_path in changed_files:
        module = _match_module(modules, file_path)
        if module is None:
            unknown.append(file_path)
            continue
        by_module.setdefault(module, []).append(file_path)
        if allowed_modules and module not in allowed_modules:
            reason_codes.append("PATH_OUT_OF_SCOPE")

    if unknown:
        reason_codes.append("UNKNOWN_PATH")
        by_module["__unknown__"] = unknown

    report["changed_files_by_module"] = by_module
    report["reason_codes"] = sorted(set(reason_codes))
    verdict = "PASS" if not report["reason_codes"] else "BLOCK"
    return DriftVerdict(verdict=verdict, reason_codes=report["reason_codes"], report=report)


def _write_github_output(
    *,
    verdict: str,
    reason_codes: List[str],
    report_json_path: str,
    report_md_path: str,
) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as handle:
        handle.write(f"verdict={verdict}\n")
        handle.write(f"reason_codes={json.dumps(reason_codes, ensure_ascii=False)}\n")
        handle.write(f"report_json_path={report_json_path}\n")
        handle.write(f"report_md_path={report_md_path}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--change-class", required=True)
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--report-md", required=True)
    args = parser.parse_args()

    repo_root = Path.cwd()
    report_json_path = str(Path(args.report_json))
    report_md_path = str(Path(args.report_md))

    try:
        verdict = evaluate(
            repo_root=repo_root,
            config_path=repo_root / args.config,
            mode=args.mode,
            change_class=args.change_class,
            base_sha=args.base_sha or None,
            head_sha=args.head_sha or None,
        )
    except DriftGuardError as exc:
        report = {
            "repo_root": str(repo_root),
            "mode": args.mode,
            "config_path": str(repo_root / args.config),
            "change_class": args.change_class,
            "required_docs": [],
            "docs_hashes": {},
            "changed_files": [],
            "changed_files_by_module": {},
            "reason_codes": [exc.reason_code],
        }
        verdict = DriftVerdict(verdict="BLOCK", reason_codes=[exc.reason_code], report=report)
    except Exception:
        report = {
            "repo_root": str(repo_root),
            "mode": args.mode,
            "config_path": str(repo_root / args.config),
            "change_class": args.change_class,
            "required_docs": [],
            "docs_hashes": {},
            "changed_files": [],
            "changed_files_by_module": {},
            "reason_codes": ["UNHANDLED_ERROR"],
        }
        verdict = DriftVerdict(verdict="BLOCK", reason_codes=["UNHANDLED_ERROR"], report=report)

    Path(report_json_path).write_text(
        json.dumps(verdict.report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    Path(report_md_path).write_text(format_report_md(verdict.report), encoding="utf-8")

    _write_github_output(
        verdict=verdict.verdict,
        reason_codes=verdict.reason_codes,
        report_json_path=report_json_path,
        report_md_path=report_md_path,
    )

    return 0 if verdict.verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
