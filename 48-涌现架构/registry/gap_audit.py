"""gap_audit.py — 基于真实架构图的可测量缺口审计（只扩可验证的样本）。

设计原则：
- 只对**可客观测量**的缺口类型扩样，绝不手写/合成缺口充数；
- 每条缺口都带可复算的度量字段（n、ratio、样本文件），可随时复核；
- 幂等：去重键为「类型 + 目标模块」，同模块只留一条 open。

当前可审计类型（按顶层模块粒度）：
- doc_debt：逐文件文档覆盖率（同名 `<stem>.md` 或目录 README/SKILL）< 0.9；
- architecture_gap：模块内函数名在其他模块重名的比例 ≥ 0.4（call 边按名解析的假依赖风险）；
- interface_mismatch：模块公开函数缺完整签名注解（参数+返回）的比例 ≥ 0.9。

不可审计类型（明确拒绝造数）：
- backtest_evaluator_missing：e2 目录已存在 backtest_evaluator.py，真实缺口是
  「config 级能力缺失」，无法用文件存在性判定；
- domain_state_series_missing：现有域状态仅有单批导出，无稳定数据源可度量。
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PKG_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_ROOT.parent
GRAPH_PATH = (
    PKG_ROOT / "baselines" / "artifacts" / "d2_architecture_graph" / "architecture_graph.json"
)
GAPS_PATH = PKG_ROOT / "registry" / "capability_gaps.jsonl"

MIN_PY_FILES = 20
COVERAGE_TARGET = 0.90
MAX_GAPS_PER_AUDIT = 12
MIN_FUNCS_FOR_AMBIGUITY = 20
AMBIGUITY_THRESHOLD = 0.40
MIN_PUBLIC_FUNCS = 100
NO_ANNOTATION_THRESHOLD = 0.90


def _gap_id(gap_type: str, key: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    digest = hashlib.md5(f"{gap_type}:{key}".encode()).hexdigest()[:8]
    return f"GAP-{stamp}-{digest}"


def _base_gap(
    gap_type: str, module: str, evidence: Dict[str, Any], expected: str, hint: str
) -> Dict[str, Any]:
    return {
        "gap_id": _gap_id(gap_type, module),
        "gap_type": gap_type,
        "evidence": {"source": "gap_audit", "module": module, **evidence},
        "expected_value": expected,
        "target_domain_hint": hint,
        "created_by": "gap_audit",
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "claimed_at": None,
        "claimed_by": None,
        "resolved_at": None,
        "resolution_note": None,
        "alert": False,
    }


def _module_of(path: str) -> str:
    parts = Path(path).parts
    return parts[0] if len(parts) > 1 else "(root)"


def audit_doc_coverage(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按顶层模块统计文档覆盖率，返回覆盖率不足的缺口列表（可复算）。

    判定口径（逐文件，避免"目录里有一个 md 就全算有文档"）：
    - 同名文档：存在 `<stem>.md` 且与 .py 同目录；或
    - 目录级文档：.py 所在目录存在 README.md / SKILL.md / index.md。
    """
    py_by_module: Dict[str, List[str]] = {}
    doc_files: set[tuple[str, str]] = set()
    doc_dirs: set[str] = set()
    dir_level_docs = {"readme.md", "skill.md", "index.md"}
    for node in graph.get("nodes", []):
        path = node.get("id", "")
        if node.get("type") == "python_file":
            py_by_module.setdefault(_module_of(path), []).append(path)
        elif node.get("type") == "markdown_doc":
            parent = str(Path(path).parent)
            doc_files.add((parent, Path(path).stem))
            if Path(path).name.lower() in dir_level_docs:
                doc_dirs.add(parent)

    gaps: List[Dict[str, Any]] = []
    ranked = sorted(py_by_module.items(), key=lambda kv: len(kv[1]), reverse=True)
    for module, files in ranked:
        py_count = len(files)
        if py_count < MIN_PY_FILES:
            continue
        undocumented = []
        for f in files:
            parent = str(Path(f).parent)
            if (parent, Path(f).stem) in doc_files or parent in doc_dirs:
                continue
            undocumented.append(f)
        documented = py_count - len(undocumented)
        coverage = documented / py_count
        if coverage >= COVERAGE_TARGET:
            continue
        gaps.append(
            _base_gap(
                "doc_debt",
                module,
                {
                    "py_files": py_count,
                    "documented_files": documented,
                    "coverage": round(coverage, 4),
                    "criterion": (
                        "逐文件文档覆盖（同名 <stem>.md 或目录 README/SKILL）"
                        f" >= {COVERAGE_TARGET}"
                    ),
                    "sample_undocumented": undocumented[:3],
                },
                f"{module} 文档覆盖率 {coverage:.1%} → ≥ {COVERAGE_TARGET:.0%}，"
                "减少无文档核心模块的维护盲区",
                "0-系统文档管理",
            )
        )
        if len(gaps) >= MAX_GAPS_PER_AUDIT:
            break
    return gaps


def scan_function_stats(
    graph: Dict[str, Any], root: Path = REPO_ROOT
) -> tuple[Dict[str, Dict[str, Any]], List[str]]:
    """AST 扫描架构图中的 python_file，返回 module → 统计 + 解析失败文件清单。"""
    per_module: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"functions": set(), "public": 0, "no_annotation": 0, "files": []}
    )
    failed: List[str] = []
    for node in graph.get("nodes", []):
        if node.get("type") != "python_file":
            continue
        rel = node.get("id", "")
        p = root / rel
        if not p.exists():
            continue
        try:
            tree = ast.parse(p.read_text(errors="ignore"))
        except (SyntaxError, ValueError, OSError):
            failed.append(rel)
            continue
        bucket = per_module[_module_of(rel)]
        bucket["files"].append(rel)
        for sub in ast.walk(tree):
            if not isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            bucket["functions"].add(sub.name)
            if sub.name.startswith("_"):
                continue
            bucket["public"] += 1
            args = sub.args.args + sub.args.kwonlyargs
            annotated = all(a.annotation is not None for a in args) and sub.returns is not None
            if not annotated:
                bucket["no_annotation"] += 1
    return dict(per_module), failed


def audit_architecture_ambiguity(
    graph: Dict[str, Any], root: Path = REPO_ROOT
) -> List[Dict[str, Any]]:
    """模块级 call 边假依赖风险：函数名跨模块重名比例越高，按名解析越不可靠。"""
    per_module, _ = scan_function_stats(graph, root)
    name_owners: Dict[str, set] = defaultdict(set)
    for module, st in per_module.items():
        for name in st["functions"]:
            name_owners[name].add(module)
    ambiguous = {n for n, owners in name_owners.items() if len(owners) > 1}

    scored = []
    for module, st in per_module.items():
        total = len(st["functions"])
        if total < MIN_FUNCS_FOR_AMBIGUITY:
            continue
        amb = [n for n in st["functions"] if n in ambiguous]
        ratio = len(amb) / total
        if ratio >= AMBIGUITY_THRESHOLD:
            scored.append((ratio, module, total, amb))
    scored.sort(reverse=True)

    gaps = []
    for ratio, module, total, amb in scored[:MAX_GAPS_PER_AUDIT]:
        gaps.append(
            _base_gap(
                "architecture_gap",
                module,
                {
                    "metric": "function_name_ambiguity",
                    "functions": total,
                    "ambiguous_functions": len(amb),
                    "ambiguity_ratio": round(ratio, 4),
                    "criterion": f"函数名跨模块重名比例 < {AMBIGUITY_THRESHOLD}",
                    "sample_ambiguous": sorted(amb)[:3],
                },
                f"{module} 重名函数占比 {ratio:.1%} → < {AMBIGUITY_THRESHOLD:.0%}，"
                "call 边按名解析的假依赖率可降到可用水平",
                "33-REA",
            )
        )
    return gaps


def audit_interface_annotations(
    graph: Dict[str, Any], root: Path = REPO_ROOT
) -> List[Dict[str, Any]]:
    """模块级接口契约缺失：公开函数缺完整签名注解（参数+返回）的占比过高。"""
    per_module, _ = scan_function_stats(graph, root)
    scored = []
    for module, st in per_module.items():
        pub = st["public"]
        if pub < MIN_PUBLIC_FUNCS:
            continue
        ratio = st["no_annotation"] / pub
        if ratio >= NO_ANNOTATION_THRESHOLD:
            scored.append((ratio, module, pub, st["no_annotation"]))
    scored.sort(reverse=True)

    gaps = []
    for ratio, module, pub, no_ann in scored[:MAX_GAPS_PER_AUDIT]:
        gaps.append(
            _base_gap(
                "interface_mismatch",
                module,
                {
                    "metric": "public_signature_annotation",
                    "public_functions": pub,
                    "no_annotation": no_ann,
                    "no_annotation_ratio": round(ratio, 4),
                    "criterion": f"公开函数缺完整注解比例 < {NO_ANNOTATION_THRESHOLD}",
                },
                f"{module} 公开函数 {ratio:.1%} 无完整签名注解 → < {NO_ANNOTATION_THRESHOLD:.0%}，"
                "架构图节点可记录接口签名并校验契约一致性",
                "33-REA",
            )
        )
    return gaps


def existing_open(gaps_path: Path) -> List[Dict[str, Any]]:
    if not gaps_path.exists():
        return []
    out = []
    with gaps_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                gap = json.loads(line)
                if gap.get("status") == "open":
                    out.append(gap)
    return out


def _dedupe_key(gap: Dict[str, Any]) -> tuple:
    """稳定去重键：同类型 + 同目标模块只保留一条 open（跨日期也不会重复）。"""
    module = (gap.get("evidence") or {}).get("module")
    if module:
        return (gap.get("gap_type"), module)
    return (gap.get("gap_type"), gap.get("gap_id"))


def append_gaps(gaps: List[Dict[str, Any]], gaps_path: Path = GAPS_PATH) -> int:
    """按「类型+模块」幂等追加，返回实际写入条数。"""
    known = {_dedupe_key(g) for g in existing_open(gaps_path)}
    new = []
    for gap in gaps:
        key = _dedupe_key(gap)
        if key in known:
            continue
        known.add(key)
        new.append(gap)
    if not new:
        return 0
    with gaps_path.open("a") as f:
        for gap in new:
            f.write(json.dumps(gap, ensure_ascii=False) + "\n")
    return len(new)


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    write = "--write" in argv
    graph = json.loads(GRAPH_PATH.read_text())

    doc_gaps = audit_doc_coverage(graph)
    amb_gaps = audit_architecture_ambiguity(graph)
    ann_gaps = audit_interface_annotations(graph)

    print(
        f"[audit] doc_debt 候选 {len(doc_gaps)} 条"
        f"（阈值 py>={MIN_PY_FILES}, coverage<{COVERAGE_TARGET}）"
    )
    for g in doc_gaps:
        ev = g["evidence"]
        print(
            f"  {g['gap_id']}  {ev['module']:<28} py={ev['py_files']:<4} "
            f"coverage={ev['coverage']:.1%}"
        )
    print(
        f"[audit] architecture_gap 候选 {len(amb_gaps)} 条"
        f"（阈值 fn>={MIN_FUNCS_FOR_AMBIGUITY}, 重名率>={AMBIGUITY_THRESHOLD}）"
    )
    for g in amb_gaps:
        ev = g["evidence"]
        print(
            f"  {g['gap_id']}  {ev['module']:<28} fn={ev['functions']:<5} "
            f"ambiguous={ev['ambiguity_ratio']:.1%}"
        )
    print(
        f"[audit] interface_mismatch 候选 {len(ann_gaps)} 条"
        f"（阈值 pub>={MIN_PUBLIC_FUNCS}, 缺注解率>={NO_ANNOTATION_THRESHOLD}）"
    )
    for g in ann_gaps:
        ev = g["evidence"]
        print(
            f"  {g['gap_id']}  {ev['module']:<28} pub={ev['public_functions']:<5} "
            f"no_annotation={ev['no_annotation_ratio']:.1%}"
        )
    print(
        "[audit] 跳过：backtest_evaluator_missing / domain_state_series_missing "
        "（无客观可测量口径，拒绝造数）"
    )

    all_gaps = doc_gaps + amb_gaps + ann_gaps
    if write:
        n = append_gaps(all_gaps)
        print(f"[audit] 已写入 {n} 条到 {GAPS_PATH}")
    else:
        print("[audit] dry-run，未写入（加 --write 落盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
