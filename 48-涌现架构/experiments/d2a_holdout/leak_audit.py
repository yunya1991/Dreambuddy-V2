"""D2-A 泄漏审计：path / content / hash / canary 四重检查（SPEC v0.4 §4.0 第 11 条）。

判定口径（预注册）：
  1. path    — 输入语料中直接出现被扣留文件本身（路径命中）
  2. content — 内容级泄漏：5-gram shingle 包含度 ≥ 0.5（他处「提及」模块路径属允许的
               线索，不算泄漏；只有整段内容被复制才判污染）。阈值取 0.5 依据实跑分布：
               真实重复副本集中在 0.85-1.0，共享 import/argparse 样板噪声 ≤0.25，0.5 处二分。
  3. hash    — 语料文件与被扣留文件 sha256 相同（跳过空文件/打包样板）
  4. canary  — 被扣留模块专属 GUID 出现在语料或指定索引目录

污染判定 fail-closed：任一重命中即 contaminated，实验不得启动。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
SHINGLE_SIZE = 5
CONTAINMENT_THRESHOLD = 0.5
MIN_TOKENS_FOR_SHINGLE = 20
MIN_BYTES_FOR_HASH_CHECK = 64
BOILERPLATE_NAMES = {"__init__.py", "__init__.pyi", ".gitkeep", "__init__.pyc"}


def tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


def shingles(text: str, size: int = SHINGLE_SIZE) -> set[str]:
    toks = tokens(text)
    if len(toks) < MIN_TOKENS_FOR_SHINGLE:
        return set()
    return {" ".join(toks[i : i + size]) for i in range(len(toks) - size + 1)}


def containment(inner: set[str], outer: set[str]) -> float:
    """inner 的 shingle 有多大比例出现在 outer 中。"""
    if not inner:
        return 0.0
    return len(inner & outer) / len(inner)


def file_hashes(root: Path, files: list[str]) -> dict[str, str]:
    """被扣留文件的 sha256（第三重）。"""
    out: dict[str, str] = {}
    for f in files:
        p = root / f
        if p.is_file():
            out[f] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _read_texts(paths: list[Path]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for p in paths:
        try:
            texts[str(p)] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return texts


def audit(
    root: Path,
    manifest: dict,
    corpus_paths: list[Path],
    prompt_paths: list[Path] | None = None,
    extra_excluded_roots: list[Path] | None = None,
) -> dict:
    """执行四重泄漏审计。

    corpus_paths: 输入语料文件（检索库/派生文档）
    prompt_paths: prompt / few-shot 文件
    extra_excluded_roots: 需整体扫描 canary 的目录（如 RAG 索引）
    """
    removed_files = manifest.get("removed_files", [])
    canary = manifest.get("canary", "")
    all_inputs = corpus_paths + (prompt_paths or [])
    texts = _read_texts(all_inputs)

    findings: list[dict] = []
    checked: list[str] = []

    # 被扣留文件内容指纹（ground truth 用，不进入输入）
    removed_shingles: dict[str, set[str]] = {}
    for f in removed_files:
        p = root / f
        if p.is_file():
            removed_shingles[f] = shingles(p.read_text(encoding="utf-8", errors="replace"))

    # 第 1 重：路径残留 —— 语料文件本身就是被扣留文件
    removed_set = set(removed_files)
    for p in all_inputs:
        checked.append(str(p))
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            rel = p.as_posix()
        if rel in removed_set:
            findings.append({"layer": "path", "file": rel, "hit": rel})

    # 第 2 重：内容级泄漏（shingle 包含度）
    for path_str, text in texts.items():
        corpus_shingles = shingles(text)
        if not corpus_shingles:
            continue
        for f, inner in removed_shingles.items():
            if not inner:
                continue
            c = containment(inner, corpus_shingles)
            if c >= CONTAINMENT_THRESHOLD:
                findings.append(
                    {
                        "layer": "content",
                        "file": Path(path_str).name,
                        "source": f,
                        "containment": round(c, 4),
                    }
                )

    # 第 3 重：hash 相同（跳过空文件与打包样板）
    hashes = file_hashes(root, removed_files)
    hash_set = {
        h
        for f, h in hashes.items()
        if (root / f).stat().st_size >= MIN_BYTES_FOR_HASH_CHECK
        and Path(f).name not in BOILERPLATE_NAMES
    }
    for p in corpus_paths:
        try:
            if p.stat().st_size < MIN_BYTES_FOR_HASH_CHECK:
                continue
            if Path(p).name in BOILERPLATE_NAMES:
                continue
            h = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
        if h in hash_set:
            findings.append({"layer": "hash", "file": p.name, "sha256": h})

    # 第 4 重：canary GUID
    if canary:
        for path_str, text in texts.items():
            if canary.lower() in text.lower():
                findings.append({"layer": "canary", "file": Path(path_str).name, "canary": canary})
        for d in extra_excluded_roots or []:
            if not d.exists():
                continue
            for p in d.rglob("*"):
                if not p.is_file():
                    continue
                try:
                    if canary.lower() in p.read_text(encoding="utf-8", errors="replace").lower():
                        findings.append({"layer": "canary", "file": str(p), "canary": canary})
                except OSError:
                    continue

    layers = ["path", "content", "hash"]
    if canary:
        layers.append("canary")
    result = {
        "module": manifest.get("module"),
        "canary": canary,
        "checked_file_count": len(checked),
        "removed_file_count": len(removed_files),
        "thresholds": {
            "shingle_size": SHINGLE_SIZE,
            "containment": CONTAINMENT_THRESHOLD,
            "min_bytes_for_hash": MIN_BYTES_FOR_HASH_CHECK,
        },
        "findings": findings,
        "finding_count_by_layer": {
            layer: sum(1 for f in findings if f["layer"] == layer) for layer in layers
        },
        "contaminated": bool(findings),
        "verdict": "contaminated" if findings else "clean",
        "layers_run": layers,
    }
    return result


def write_audit(result: dict, out_path: Path) -> str:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(result, ensure_ascii=False, indent=1).encode("utf-8")
    out_path.write_bytes(blob)
    return hashlib.sha256(blob).hexdigest()
