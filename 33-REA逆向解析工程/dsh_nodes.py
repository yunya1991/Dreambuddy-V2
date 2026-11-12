"""
33-REA逆向解析工程 - DSH 节点封装

提供三个 DSH 节点函数，供 DreamOS C-Drive Agent 通过 IPC 调用：

- S33_rea_analyze:  整体架构分析（模块/依赖/调用图）
- S33_rea_trace:    功能追踪 — 某功能的调用链
- S33_rea_compare:  两工程对比

设计原则（Evidence-First）：
- 每条结论带 Evidence（provenance + confidence + known_gaps）
- 节点函数为纯计算 + 静态分析，不生成原始数据
- 输出是结构化 SubagentOutput 摘要（压缩格式）

调用契约（DSH stdin NDJSON）：
    {"method": "s33_rea_analyze", "params": {"target": "/path", "scope": "architecture"}}
    {"method": "s33_rea_trace", "params": {"target": "/path", "feature": "用户登录"}}
    {"method": "s33_rea_compare", "params": {"target_a": "/a", "target_b": "/b", "feature": "架构"}}
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

# 确保模块可导入
_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from core.adapt_plan import build_adapt_plans  # noqa: E402
from core.ai_audit import audit_ai_output  # noqa: E402
from core.call_chain_tracer import CallChainTracer  # noqa: E402
from core.cognitive_integration import (  # noqa: E402
    prepare_audit_record_params,
    prepare_decision_record_params,
    prepare_record_params,
)
from core.cognitive_writeback import writeback_status  # noqa: E402
from core.dependency_graph import DependencyGraph  # noqa: E402
from core.design_decision_recovery import recover_decisions  # noqa: E402
from core.evidence import Evidence, EvidenceLevel  # noqa: E402
from core.evolution_narrative import generate_narrative  # noqa: E402
from core.hypothesis import audit_hypotheses, build_write_hint  # noqa: E402
from core.investigation_workflow import investigate  # noqa: E402
from core.llm_budget import check_budget, record_cost  # noqa: E402
from core.methodology_abstraction import MethodologyAbstractor  # noqa: E402
from core.python_analyzer import PythonAnalyzer  # noqa: E402
from core.relevance import apply_relevance_scores, write_relevance_scores  # noqa: E402
from core.ts_project_analyzer import TSProjectAnalyzer  # noqa: E402

__all__ = [
    "S33_rea_analyze",
    "S33_rea_trace",
    "S33_rea_compare",
    "S33_rea_investigate",
    "S33_rea_recover_decisions",
    "S33_rea_narrative",
    "S33_rea_audit",
    "S33_rea_adapt_plan",
    "S33_rea_score_sources",
    "S33_rea_incremental_index",
    "S33_rea_cost_ledger",
    "S33_rea_writeback",
    "detect_target_language",
    "get_rea_snapshot",
    "get_rea_methodology",
    "DSH_NODE_REGISTRY",
    "dispatch",
]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _make_output(
    node: str,
    trace_id: str,
    ok: bool,
    result: Dict[str, Any],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """构造 DSH SubagentOutput 摘要（压缩格式）。"""
    return {
        "node": node,
        "trace_id": trace_id,
        "ok": ok,
        "result": result,
        "error": error,
        "ts": _now_ms(),
    }


def _gen_trace_id(prefix: str = "s33") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# SPEC-33-G §2.9：无 LLM 降级通道 — pending_actions 注入信封（FAIL-OPEN）
# ---------------------------------------------------------------------------

EVOLUTION_POLICY_ROOT_ENV = "REA_EVOLUTION_POLICY_ROOT"
_PENDING_ENVELOPE_NODES = ("S33_rea_analyze", "S33_rea_trace", "S33_rea_audit")


def evolution_policy_root() -> Path:
    """演化账本根目录：环境变量优先，默认 33-REA/policy。"""
    override = os.environ.get(EVOLUTION_POLICY_ROOT_ENV)
    return Path(override) if override else (_MODULE_DIR / "policy")


def evolution_pending_actions(limit: Optional[int] = 10) -> list[Dict[str, Any]]:
    """读取待人工审批 proposal；任何异常返回空列表（不得阻断主链路）。"""
    try:
        from core.evolution.pending_actions import PendingActionStore

        return PendingActionStore(evolution_policy_root()).actions(limit=limit)
    except Exception:
        return []


def _with_pending_actions(fn):
    """给 analyze / trace / rea_audit 信封附加 pending_actions[]（非空才加）。"""

    @functools.wraps(fn)
    def wrapper(params: Dict[str, Any]) -> Dict[str, Any]:
        output = fn(params)
        actions = evolution_pending_actions()
        if actions and isinstance(output, dict):
            output = dict(output)
            output["pending_actions"] = actions
        return output

    return wrapper


# ---------------------------------------------------------------------------
# SPEC-33-D：语言路由 / scope 分级 / 快照 / 内容寻址缓存
# ---------------------------------------------------------------------------

_TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

_TREE_SKIP_DIRS = {
    "node_modules",
    ".git",
    ".next",
    ".turbo",
    ".vercel",
    ".cache",
    "dist",
    "build",
    "out",
    "coverage",
    "playwright-report",
    "test-results",
    "__pycache__",
    ".venv",
    "venv",
}

_SCOPES = ("summary", "architecture", "full")
_DEFAULT_SCOPE = "summary"
_SUMMARY_MAX_BYTES = 16_384
_ARCHITECTURE_MAX_BYTES = 65_536
_FULL_MAX_BYTES = 4_096
_SCOPE_EVIDENCE_LIMIT = {"summary": 5, "architecture": 20}
_SNAPSHOT_PAGE_LIMIT = 200
_SNAPSHOT_DEFAULT_LIMIT = 20
_CACHE_MAX_ENTRIES = 200
_SNAPSHOT_SECTIONS = (
    "modules",
    "dependencies",
    "cycles",
    "call_graph",
    "components",
    "routes",
    "api_routes",
    "stores",
    "god_components",
    "external_deps",
    "patterns",
    "evidence",
    "graph",
    "diagram",
)

# SPEC-F §2.11：适配环现场采集的 section（不落快照 payload）
_COMPUTED_SNAPSHOT_SECTIONS = (
    "metrics",
    "rules",
    "sarif",
    "pack",
    "archaeology",
    "dependency_hygiene",
    "diagnostics",
    "runtime",
    "taint",
    "semantic",
)
_SARIF_SECTION_MAX_BYTES = 8_192
_RUNTIME_SECTION_MAX_BYTES = 8_192
_PACK_DEFAULT_BUDGET_BYTES = 32_768

_REFLECTION_DIR = _MODULE_DIR / "reflection_data"
_SNAPSHOT_DIR = _REFLECTION_DIR / "snapshots"
_CACHE_DIR = _REFLECTION_DIR / "mcp_cache"

_LEVEL_TO_QUALITY = {"observation": "B", "derivation": "B", "inference": "C"}


def _json_size(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _iter_source_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _TREE_SKIP_DIRS and not d.startswith(".")
        )
        for name in sorted(filenames):
            yield Path(dirpath) / name


def detect_target_language(target: str) -> str:
    """按 SPEC §2.2 判定目标语言：typescript / python / unknown。"""
    path = Path(target).expanduser()
    if path.is_file():
        if path.suffix == ".py":
            return "python"
        if path.suffix in _TS_EXTS or path.name in ("tsconfig.json", "package.json"):
            return "typescript"
        return "unknown"
    if not path.is_dir():
        return "unknown"
    if (path / "tsconfig.json").is_file() or (path / "package.json").is_file():
        return "typescript"
    if (path / "src" / "app").is_dir():
        return "typescript"
    # 子目录目标：逐级向上只认 tsconfig.json（仓库根 package.json 不代表整个仓库是 TS）
    for parent in path.parents:
        if (parent / "tsconfig.json").is_file():
            return "typescript"
    ts_count = 0
    py_count = 0
    for full in _iter_source_files(path):
        if full.name.endswith(_TS_EXTS):
            ts_count += 1
        elif full.name.endswith(".py"):
            py_count += 1
    return "typescript" if ts_count > 0 and ts_count >= py_count else "python"


def _tree_hash(target: str) -> str:
    """目标树指纹：目录取 (相对路径, 大小) 列表摘要；文件取 (文件名, 大小)。"""
    path = Path(target)
    digest = hashlib.sha256()
    if path.is_file():
        try:
            digest.update(f"{path.name}:{path.stat().st_size}".encode("utf-8"))
        except OSError:
            pass
        return digest.hexdigest()
    entries: list[str] = []
    for full in _iter_source_files(path):
        try:
            rel = full.relative_to(path).as_posix()
            entries.append(f"{rel}:{full.stat().st_size}")
        except OSError:
            continue
    digest.update("\n".join(sorted(entries)).encode("utf-8"))
    return digest.hexdigest()


def _snapshot_id(target: str, tree_hash: str) -> str:
    seed = f"{os.path.abspath(target)}\n{tree_hash}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _cache_key(target: str, language: str, tree_hash: str) -> str:
    seed = f"{os.path.abspath(target)}|{language}|{tree_hash}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _cache_path(cache_key: str) -> Path:
    return _CACHE_DIR / f"{cache_key}.json"


def _load_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    try:
        with open(_cache_path(cache_key), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _prune_cache() -> None:
    try:
        files = sorted(_CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for stale in files[: max(0, len(files) - _CACHE_MAX_ENTRIES)]:
        try:
            stale.unlink()
        except OSError:
            pass


def _save_cache(cache_key: str, payload: Dict[str, Any]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(cache_key).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return
    _prune_cache()


def _collect_known_gaps(evidence: list[Dict[str, Any]], limit: int = 20) -> list[str]:
    gaps: list[str] = []
    for item in evidence:
        for gap in item.get("known_gaps") or []:
            gap = str(gap)
            if gap not in gaps:
                gaps.append(gap)
            if len(gaps) >= limit:
                return gaps
    return gaps


def _evidence_counts(evidence: list[Dict[str, Any]]) -> Dict[str, Any]:
    counts: Dict[str, Any] = {
        "total": len(evidence),
        "observation": 0,
        "derivation": 0,
        "inference": 0,
        "unknown": 0,
    }
    for item in evidence:
        level = str(item.get("level") or "unknown")
        counts[level if level in counts and level != "total" else "unknown"] += 1
    return counts


def _analyze_ts_target(target: str) -> Dict[str, Any]:
    """TS/React 项目级分析（TSProjectAnalyzer），raw 原样保留。"""
    result = TSProjectAnalyzer(target).analyze(target)
    raw = dict(result.raw or {})
    evidence = [e.to_dict() for e in result.evidence]
    stats = raw.get("stats") or {"files": 0, "lines": 0}
    degraded = bool(raw.get("error")) or any(
        str(item.get("level")) == "unknown" for item in evidence
    )
    return {
        "target": os.path.abspath(target),
        "language": "typescript",
        "summary": result.summary,
        "stats": stats,
        "evidence": evidence,
        "raw": raw,
        "known_gaps": _collect_known_gaps(evidence),
        "degraded": degraded,
        "recorder_nodes": ["ts_project_analyzer"],
    }


def _python_project_modules(target_dir: str) -> list[str]:
    """项目内 Python 模块名（相对路径转点分），排除 __init__ 与构建目录。"""
    modules: list[str] = []
    for root, dirnames, names in os.walk(target_dir):
        dirnames[:] = [d for d in dirnames if d not in _TREE_SKIP_DIRS]
        for name in names:
            if not name.endswith(".py") or name.startswith("__"):
                continue
            rel = os.path.relpath(os.path.join(root, name), target_dir)
            modules.append(rel.replace(os.sep, ".").removesuffix(".py"))
    return sorted(modules)


def _is_project_module(name: str, project_modules: list[str]) -> bool:
    """判断模块名是否属于项目内。

    兼容两种写法：点分全名（pkg.app）与 `_extract_deps` 产出的顶层/末段名
    （distill_bridge、pkg），后者按包前缀或文件名末段匹配。
    """
    if name in project_modules:
        return True
    prefix = name + "."
    if any(m.startswith(prefix) for m in project_modules):
        return True
    if "." in name:
        return False
    return any(m.split(".")[-1] == name for m in project_modules)


def _split_python_modules(target_dir: str, all_nodes: list[str]) -> tuple[list[str], list[str]]:
    """拆分项目内模块与外部模块（stdlib/第三方），避免模块数被外部依赖虚增。"""
    project = _python_project_modules(target_dir)
    external = sorted(n for n in all_nodes if not _is_project_module(n, project))
    return project, external


def _analyze_python_target(target: str) -> Optional[Dict[str, Any]]:
    """Python 旧路径（PythonAnalyzer / DependencyGraph + CallChainTracer），行为保持不变。"""
    if os.path.isfile(target):
        res = PythonAnalyzer().analyze(target)
        evidence = [e.to_dict() for e in res.evidence]
        raw = dict(res.raw or {})
        functions = raw.get("functions") or []
        return {
            "target": os.path.abspath(target),
            "language": "python",
            "summary": res.summary,
            "stats": {
                "files": 1,
                "modules": 1,
                "functions": len(functions),
                "imports": len(raw.get("imports") or []),
            },
            "evidence": evidence,
            "raw": {**raw, "modules": [os.path.basename(target)]},
            "known_gaps": _collect_known_gaps(evidence),
            "degraded": any(str(e.get("level")) == "unknown" for e in evidence),
            "recorder_nodes": ["python_analyzer"],
        }
    if os.path.isdir(target):
        dep_result = DependencyGraph().build(target)
        chain_result = CallChainTracer().trace(target)
        all_nodes = dep_result.get("nodes", [])
        # SPEC-33-D 修正：模块清单只算项目内文件，外部依赖单列 external_deps
        project_modules, external_modules = _split_python_modules(target, all_nodes)
        project_set = set(project_modules)
        modules = project_modules
        functions = chain_result.get("all_functions", [])
        adjacency = dep_result.get("adjacency", {})
        internal_adjacency = {
            src: [dst for dst in dsts if _is_project_module(dst, project_modules)]
            for src, dsts in adjacency.items()
            if src in project_set
        }
        evidence = [e.to_dict() for e in dep_result.get("evidence", [])] + [
            e.to_dict() for e in chain_result.get("evidence", [])
        ]
        n_edges = sum(len(v) for v in internal_adjacency.values())
        n_cycles = len(dep_result.get("cycles", []))
        # SPEC-F P-F01：Evidence 与 summary 使用同一分母（项目内），并显式标注 scope
        evidence.insert(
            0,
            {
                "evidence_id": "",
                "result": f"依赖图（项目内口径）: {len(modules)} 模块, {n_edges} 边",
                "level": "derivation",
                "provenance": {
                    "target": os.path.abspath(target),
                    "analysis": "dependency_graph",
                    "scope": "project_internal",
                    "modules": len(modules),
                    "edges": n_edges,
                },
                "confidence": 1.0,
                "known_gaps": ["仅统计项目内模块；外部依赖单列 external_deps，不含在模块/边计数内"],
                "observations": [],
                "created_at": 0,
            },
        )
        summary = (
            f"架构分析: {len(modules)} 模块（项目内）, {n_edges} 依赖, "
            f"{n_cycles} 循环依赖, {len(functions)} 函数, "
            f"{len(external_modules)} 个外部依赖"
        )
        return {
            "target": os.path.abspath(target),
            "language": "python",
            "summary": summary,
            "stats": {
                "files": len(project_modules),
                "modules": len(project_modules),
                "external_modules": len(external_modules),
                "functions": len(functions),
                "edges": n_edges,
                "cycles": n_cycles,
            },
            "evidence": evidence,
            "raw": {
                "modules": modules,
                "external_deps": external_modules,
                "dependencies": internal_adjacency,
                "cycles": dep_result.get("cycles", []),
                "call_graph": {
                    "callers": chain_result.get("callers", {}),
                    "callees": chain_result.get("callees", {}),
                },
            },
            "known_gaps": _collect_known_gaps(evidence),
            "degraded": any(str(e.get("level")) == "unknown" for e in evidence),
            "recorder_nodes": ["dependency_graph", "call_chain_tracer"],
        }
    return None


def _write_snapshot(snapshot_id: str, analysis: Dict[str, Any], trace_id: str) -> None:
    payload = {
        "snapshot_id": snapshot_id,
        "created_at": _now_ms(),
        "trace_id": trace_id,
        "target": analysis.get("target"),
        "language": analysis.get("language"),
        "summary": analysis.get("summary"),
        "stats": analysis.get("stats"),
        "known_gaps": analysis.get("known_gaps"),
        "degraded": analysis.get("degraded"),
        "evidence": analysis.get("evidence") or [],
        "raw": analysis.get("raw") or {},
    }
    try:
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        (_SNAPSHOT_DIR / f"{snapshot_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        return


def _build_cognitive_hint(result: Dict[str, Any], snapshot_id: str) -> Optional[Dict[str, Any]]:
    """§2.6 等级映射：observation/derivation→B，inference→C，unknown/degraded→不产出。"""
    evidence = result.get("evidence") or []
    if not evidence:
        return None
    levels = [str(item.get("level") or "unknown") for item in evidence]
    dominant = next((lv for lv in ("observation", "derivation", "inference") if lv in levels), None)
    if dominant is None:
        return None
    target = str(result.get("target") or "")
    patterns = result.get("patterns") or []
    pattern_names = ",".join(str(p.get("pattern")) for p in patterns[:5] if isinstance(p, dict))
    gaps = result.get("known_gaps") or []
    return {
        "content": (
            f"[33-REA][{target}] {str(result.get('summary') or '')[:300]}；"
            f"模式 {pattern_names or '无'}；局限 {len(gaps)} 条"
        ),
        "tags": f"33-REA,架构分析,{result.get('language')},{Path(target).name}",
        "quality_level": _LEVEL_TO_QUALITY[dominant],
        "level": dominant,
        "snapshot_id": snapshot_id,
        "verify_when": "该目标的结构性结论被改动后（如新增/消除依赖环）",
    }


def _note_trimmed(result: Dict[str, Any], key: str, kept: int, total: int) -> None:
    """记录截断事实（G-D2 反静默裁剪）：调用方据此判断证据/明细是否被丢弃。"""
    if kept >= total:
        return
    trimmed = result.setdefault("trimmed", {})
    trimmed[key] = {"kept": kept, "total": total}


def _fit_size(result: Dict[str, Any], limit: int) -> Dict[str, Any]:
    """按 scope 软上限裁剪可选项（evidence / 明细列表），并标记 trimmed/degraded。"""
    if _json_size(result) <= limit:
        return result
    optional = (
        "evidence",
        "patterns",
        "routes",
        "api_routes",
        "stores",
        "god_components",
        "cycles",
        "hubs",
        "orphans",
        "external_deps",
    )
    for key in optional:
        if _json_size(result) <= limit:
            return result
        value = result.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            original = len(value)
            while value and _json_size(result) > limit:
                value.pop()
            _note_trimmed(result, key, len(value), original)
            if not value:
                result.pop(key, None)
        else:
            result.pop(key, None)
    if _json_size(result) > limit:
        result["degraded"] = True
        gaps = result.setdefault("known_gaps", [])
        marker = "结果已按 scope 字节上限截断"
        if marker not in gaps:
            gaps.append(marker)
    return result


def _shape_result(
    analysis: Dict[str, Any],
    *,
    scope: str,
    snapshot_id: str,
    cache_hit: bool,
    trace_id: str,
) -> Dict[str, Any]:
    raw = analysis.get("raw") or {}
    graph = raw.get("graph") or {}
    evidence = list(analysis.get("evidence") or [])
    result: Dict[str, Any] = {
        "target": analysis.get("target"),
        "language": analysis.get("language", "unknown"),
        "scope": scope,
        "summary": analysis.get("summary", ""),
        "stats": analysis.get("stats") or {},
        "known_gaps": list(analysis.get("known_gaps") or []),
        "degraded": bool(analysis.get("degraded", False)),
        "evidence_counts": _evidence_counts(evidence),
        "snapshot_id": snapshot_id,
        "cache_hit": cache_hit,
        "trace_id": trace_id,
    }
    if scope == "summary":
        result["patterns"] = list(raw.get("patterns") or [])
        kept = evidence[: _SCOPE_EVIDENCE_LIMIT["summary"]]
        result["evidence"] = kept
        _note_trimmed(result, "evidence", len(kept), len(evidence))
        limit = _SUMMARY_MAX_BYTES
    elif scope == "architecture":
        kept_arch = evidence[: _SCOPE_EVIDENCE_LIMIT["architecture"]]
        result.update(
            {
                "patterns": list(raw.get("patterns") or []),
                "routes": list(raw.get("routes") or []),
                "api_routes": list(raw.get("api_routes") or []),
                "stores": list(raw.get("stores") or []),
                "god_components": list(raw.get("god_components") or []),
                "cycles": list(raw.get("cycles") or graph.get("cycles") or []),
                "hubs": list(graph.get("hubs") or []),
                "orphans": list(graph.get("orphans") or []),
                "external_deps": list(raw.get("external_deps") or []),
                "evidence": kept_arch,
            }
        )
        _note_trimmed(result, "evidence", len(kept_arch), len(evidence))
        limit = _ARCHITECTURE_MAX_BYTES
    else:
        # full：不内联 raw/evidence，明细一律经 get_rea_snapshot 分页读取（SPEC §2.3）
        limit = _FULL_MAX_BYTES
    if scope in ("summary", "architecture"):
        hint = _build_cognitive_hint(result, snapshot_id)
        if hint is not None:
            result["cognitive_hint"] = hint
    result = _fit_size(result, limit)
    if not result.get("evidence"):
        result.pop("cognitive_hint", None)
    return result


def _begin_analysis_recorder(params: Dict[str, Any], target: str, scope: str):
    try:
        from core.reflection.recorder import AnalysisRecorder

        recorder = AnalysisRecorder(
            pool_dir=str(params.get("pool_dir") or "reflection_data/replay_pool")
        )
        if recorder.begin({"target": target, "task_type": "analyze", "scope": scope}):
            return recorder
    except Exception:
        return None
    return None


def _record_analysis(recorder: Any, analysis: Dict[str, Any], target: str) -> None:
    if recorder is None:
        return
    for node in analysis.get("recorder_nodes") or []:
        try:
            recorder.record(
                node,
                params={"target": target},
                poe_score=0.8,
                cost_calls=1,
                evidence_refs=[{"source": "s33_rea_analyze", "detail": node}],
            )
        except Exception:
            continue


def _commit_recorder(recorder: Any) -> Optional[str]:
    if recorder is None:
        return None
    try:
        return recorder.commit()
    except Exception:
        return None


_TS_GENERIC_STEMS = {"index", "main", "app", "page", "route", "layout", "mod"}


def _resolve_ts_entry(entry: str, nodes: list[str]) -> Optional[str]:
    """入口模块解析：先精确/后缀匹配，再退化为文件名匹配（仅唯一命中时采用）。"""
    needle = entry.strip().replace("\\", "/").lstrip("./")
    if not needle:
        return None
    suffix_matches = [rel for rel in nodes if rel == needle or rel.endswith("/" + needle)]
    if suffix_matches:
        stem = os.path.splitext(os.path.basename(needle))[0]
        # 仅给文件名（无目录）且多命中且是泛名（index/page…）→ 不猜，返回 None
        if len(suffix_matches) == 1 or "/" in needle or stem not in _TS_GENERIC_STEMS:
            return suffix_matches[0]
        return None
    stem = os.path.splitext(os.path.basename(needle))[0]
    candidates = [rel for rel in nodes if os.path.splitext(os.path.basename(rel))[0] == stem]
    # 唯一命中才采用；index/page 等泛名多命中时返回 None，避免静默指向错误模块
    if len(candidates) == 1:
        return candidates[0]
    if stem in _TS_GENERIC_STEMS:
        return None
    return candidates[0] if candidates else None


_TS_TRACE_NEIGHBOR_LIMIT = 10
_TS_TRACE_SEED_LIMIT = 5


def _ts_feature_tokens(feature: str) -> list[str]:
    """feature 拆词（≥2 字符），用于路径/文件内容匹配。"""
    return [t for t in re.split(r"[^0-9a-z_\u4e00-\u9fff]+", feature.lower()) if len(t) >= 2]


def _match_ts_seeds(
    target: str, nodes: list[str], feature: str
) -> tuple[list[str], list[Dict[str, Any]]]:
    """按 feature 匹配种子模块：先匹配路径，无命中再匹配文件内容（避免全量读文件）。"""
    needles = _ts_feature_tokens(feature)
    if not needles:
        return [], []

    path_hits: list[tuple[int, str]] = []
    for rel in nodes:
        low = rel.lower()
        hits = sum(low.count(n) for n in needles)
        if hits:
            path_hits.append((hits, rel))

    match_kind = "path"
    hits_list = path_hits
    if not hits_list:
        match_kind = "content"
        for rel in nodes:
            try:
                with open(os.path.join(target, rel), encoding="utf-8", errors="ignore") as f:
                    text = f.read(200_000).lower()
            except OSError:
                continue
            hits = sum(text.count(n) for n in needles)
            if hits:
                hits_list.append((hits, rel))

    ranked = sorted(hits_list, key=lambda kv: (-kv[0], kv[1]))[:_TS_TRACE_SEED_LIMIT]
    seeds = [rel for _, rel in ranked]
    matched = [{"module": rel, "match": match_kind, "hits": h} for h, rel in ranked]
    return seeds, matched


def _trace_ts_target_legacy(
    target: str, feature: str, entry: Optional[str], trace_id: str
) -> Dict[str, Any]:
    """TS 功能追踪 v1（legacy）：feature/entry 定位种子模块，返回其一跳上下游子图。"""
    result = TSProjectAnalyzer(target).analyze(target)
    raw = result.raw or {}
    graph = raw.get("graph") or {}
    adjacency = graph.get("adjacency") or {}
    nodes = list(graph.get("nodes") or [])

    seeds: list[str] = []
    matched: list[Dict[str, Any]] = []
    entry_rel = _resolve_ts_entry(entry, nodes) if entry else None
    if entry_rel:
        seeds = [entry_rel]
        matched = [{"module": entry_rel, "match": "entry", "hits": 1}]
    elif feature:
        seeds, matched = _match_ts_seeds(target, nodes, feature)
    if not seeds:
        seeds = nodes[:3]

    callers_all: Dict[str, list[str]] = {}
    for src, dsts in adjacency.items():
        for dst in dsts:
            callers_all.setdefault(dst, []).append(src)

    upstream: Dict[str, list[str]] = {}
    downstream: Dict[str, list[str]] = {}
    for rel in seeds:
        up = sorted(set(callers_all.get(rel, [])))[:_TS_TRACE_NEIGHBOR_LIMIT]
        down = sorted(set(adjacency.get(rel, [])))[:_TS_TRACE_NEIGHBOR_LIMIT]
        if up:
            upstream[rel] = up
        if down:
            downstream[rel] = down

    entry_chain: list[str] = []
    if seeds:
        queue = [seeds[0]]
        seen = {seeds[0]}
        while queue and len(entry_chain) < _TS_TRACE_NEIGHBOR_LIMIT:
            current = queue.pop(0)
            entry_chain.append(current)
            for nb in adjacency.get(current, []):
                if nb not in seen:
                    seen.add(nb)
                    queue.append(nb)

    evidence = [e.to_dict() for e in result.evidence]
    known_gaps = _collect_known_gaps(evidence)
    known_gaps.append(
        f"callers/callees 为一跳子图（每种子 ≤{_TS_TRACE_NEIGHBOR_LIMIT}），非全量 import 图"
    )
    if entry and not entry_rel:
        known_gaps.append(
            f"entry={entry!r} 未能唯一解析（路径不存在或 index/page 等泛名多命中），已改用 feature 匹配"
        )
    if feature and not entry and not matched:
        known_gaps.append(f"feature={feature!r} 未匹配到任何模块，种子退化为前 3 个模块")
    if graph.get("unresolved_local_imports"):
        known_gaps.append(f"未解析的本地相对导入: {graph['unresolved_local_imports']}")

    return _make_output(
        "S33_rea_trace",
        trace_id,
        ok=True,
        result={
            "feature": feature,
            "language": "typescript",
            "algorithm": "legacy",
            "matched": matched,
            "call_chain": {
                "seeds": seeds,
                "callers": upstream,
                "callees": downstream,
                "entry_chain": entry_chain,
            },
            "stats": {
                "nodes": len(nodes),
                "edges": sum(len(v) for v in adjacency.values()),
                "seeds": len(seeds),
                "upstream": sum(len(v) for v in upstream.values()),
                "downstream": sum(len(v) for v in downstream.values()),
            },
            "evidence": evidence,
            "known_gaps": known_gaps,
            "trace_id": trace_id,
        },
    )


_TRACE_DEFAULT_BUDGET = 8192
_TRACE_DEFAULT_HOPS = 2
_TRACE_EVIDENCE_KEYS = ("result", "level", "provenance", "confidence", "known_gaps")


def _stable_evidence(evidence: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """剥离 evidence_id / created_at 等易变字段（G-F2 确定性要求）。"""
    return [{k: item.get(k) for k in _TRACE_EVIDENCE_KEYS if k in item} for item in evidence]


def _fit_trace_budget(
    result: Dict[str, Any],
    adjacency: Dict[str, list[str]],
    budget_bytes: int,
    extra_evidence: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """按字节预算裁剪 ranked_nodes / edges，并记录 trimmed（SPEC-F §2.2）。

    预算按整个响应计：预留 256B 给外层信封（node/trace_id/ok/error/ts）。
    """
    from core.graph_rank import edges_within

    budget_bytes = max(256, budget_bytes - 256)
    ranked_all = list(result.get("ranked_nodes") or [])
    result["ranked_nodes"] = []
    result["edges"] = []

    def _cap(key: str, cap: int) -> None:
        items = result.get(key) or []
        if len(items) <= cap:
            return
        result[key] = items[:cap]
        result.setdefault("trimmed", {})[key] = {"kept": cap, "total": len(items)}

    def _cap_call_chain(cap: int) -> None:
        call_chain = result.get("call_chain") or {}
        for key in ("callers", "callees"):
            mapping = call_chain.get(key)
            if isinstance(mapping, dict) and len(mapping) > cap:
                call_chain[key] = dict(list(mapping.items())[:cap])
                result.setdefault("trimmed", {})[f"call_chain.{key}"] = {
                    "kept": cap,
                    "total": len(mapping),
                }

    # 证据先行：primary evidence 保留，辅助字段先封顶；再追加至多 3 条补充 evidence
    _cap("known_gaps", 5)
    _cap("matched", 5)
    _cap_call_chain(5)

    extra_all = list(extra_evidence or [])
    kept_evidence = list(result.get("evidence") or [])
    # 证据补充最多占一半预算，保证 ranked_nodes（核心交付）不被挤空
    for item in extra_all[:3]:
        trial_evidence = kept_evidence + [item]
        if _json_size({**result, "evidence": trial_evidence}) > budget_bytes // 2:
            break
        kept_evidence = trial_evidence
    result["evidence"] = kept_evidence

    kept: list[Dict[str, Any]] = []
    for item in ranked_all:
        trial = kept + [item]
        if _json_size({**result, "ranked_nodes": trial}) > budget_bytes:
            break
        kept = trial
    result["ranked_nodes"] = kept

    evidence_total = 1 + len(extra_all)
    if len(kept_evidence) < evidence_total:
        result.setdefault("trimmed", {})["evidence"] = {
            "kept": len(kept_evidence),
            "total": evidence_total,
        }

    kept_modules = [item["module"] for item in kept]
    edge_candidates = edges_within(adjacency, kept_modules)
    kept_edges: list[Dict[str, str]] = []
    for edge in edge_candidates:
        trial_edges = kept_edges + [edge]
        if _json_size({**result, "edges": trial_edges}) > budget_bytes:
            break
        kept_edges = trial_edges
    result["edges"] = kept_edges

    if len(kept) < len(ranked_all):
        result.setdefault("trimmed", {})["ranked_nodes"] = {
            "kept": len(kept),
            "total": len(ranked_all),
        }
    if len(kept_edges) < len(edge_candidates):
        result.setdefault("trimmed", {})["edges"] = {
            "kept": len(kept_edges),
            "total": len(edge_candidates),
        }
    # 兜底：极端预算下继续压缩辅助字段，但至少保留 1 条 primary evidence
    for key, cap in (("known_gaps", 3), ("matched", 3)):
        if _json_size(result) <= budget_bytes:
            break
        _cap(key, cap)
    for cap in (3, 1):
        if _json_size(result) <= budget_bytes:
            break
        _cap_call_chain(cap)
    return result


def _trace_ts_target_v2(
    target: str,
    feature: str,
    entry: Optional[str],
    trace_id: str,
    *,
    budget_bytes: int = _TRACE_DEFAULT_BUDGET,
    hops: int = _TRACE_DEFAULT_HOPS,
    use_lsp: bool = False,
) -> Dict[str, Any]:
    """TS 功能追踪 v2：PPR 相关性排序 + 预算裁剪 + 确定性输出（SPEC-F §2.2）。"""
    from core.graph_rank import (
        DEFAULT_DAMPING,
        DEFAULT_MAX_ITER,
        DEFAULT_TOL,
        rank_neighborhood,
    )

    result = TSProjectAnalyzer(target).analyze(target)
    raw = result.raw or {}
    graph = raw.get("graph") or {}
    adjacency = {
        str(src): [str(dst) for dst in (dsts or [])]
        for src, dsts in (graph.get("adjacency") or {}).items()
    }
    nodes = sorted({str(n) for n in (graph.get("nodes") or [])})

    seeds: list[str] = []
    matched: list[Dict[str, Any]] = []
    entry_rel = _resolve_ts_entry(entry, nodes) if entry else None
    if entry_rel:
        seeds = [entry_rel]
        matched = [{"module": entry_rel, "match": "entry", "hits": 1}]
    elif feature:
        seeds, matched = _match_ts_seeds(target, nodes, feature)
    lsp_summary: Dict[str, Any] = {}
    lsp_evidence: list[Dict[str, Any]] = []
    lsp_gaps: list[str] = []
    if use_lsp:
        from adapters.lsp_adapter import inspect_symbols

        refs = list(dict.fromkeys(str(value) for value in (entry, feature) if value))
        symbol_report = inspect_symbols(target, refs, language="typescript")
        lsp_modules = sorted(
            {
                str(location.get("file"))
                for locations in (symbol_report.get("locations") or {}).values()
                for location in locations
                if location.get("file") in nodes
            }
        )
        for module in lsp_modules:
            if module not in seeds:
                seeds.append(module)
            if not any(item.get("module") == module for item in matched):
                matched.append({"module": module, "match": "lsp", "hits": 1})
        lsp_evidence = symbol_report.get("evidence") or []
        lsp_gaps = list(symbol_report.get("known_gaps") or [])
        lsp_summary = {
            "degraded": bool(symbol_report.get("degraded")),
            "tools": symbol_report.get("tools") or {},
            "seed_count": len(lsp_modules),
        }
    if not seeds:
        seeds = nodes[:3]

    ranked_all = rank_neighborhood(adjacency, seeds, hops=hops)
    match_by_module = {item["module"]: item for item in matched}
    for item in ranked_all:
        matched_item = match_by_module.get(item["module"])
        if matched_item:
            item["match"] = matched_item["match"]
        elif item["hop"] == 0:
            item["match"] = "seed"
        else:
            item["match"] = "hop"

    callers_all: Dict[str, list[str]] = {}
    for src, dsts in adjacency.items():
        for dst in dsts:
            callers_all.setdefault(dst, []).append(src)

    upstream: Dict[str, list[str]] = {}
    downstream: Dict[str, list[str]] = {}
    for rel in seeds:
        up = sorted(set(callers_all.get(rel, [])))[:_TS_TRACE_NEIGHBOR_LIMIT]
        down = sorted(set(adjacency.get(rel, [])))[:_TS_TRACE_NEIGHBOR_LIMIT]
        if up:
            upstream[rel] = up
        if down:
            downstream[rel] = down

    entry_chain: list[str] = []
    if seeds:
        queue = [seeds[0]]
        seen = {seeds[0]}
        while queue and len(entry_chain) < _TS_TRACE_NEIGHBOR_LIMIT:
            current = queue.pop(0)
            entry_chain.append(current)
            for nb in sorted(set(adjacency.get(current, []))):
                if nb not in seen:
                    seen.add(nb)
                    queue.append(nb)

    evidence: list[Dict[str, Any]] = (
        [
            {
                "result": (
                    "相关性排序: personalized_pagerank"
                    f"(damping={DEFAULT_DAMPING}, max_iter={DEFAULT_MAX_ITER}, "
                    f"tol={DEFAULT_TOL}), hops={hops}, budget_bytes={budget_bytes}"
                ),
                "level": "derivation",
                "provenance": {
                    "analysis": "graph_rank",
                    "algorithm": "ppr_v2",
                    "damping": DEFAULT_DAMPING,
                    "max_iter": DEFAULT_MAX_ITER,
                    "tol": DEFAULT_TOL,
                    "hops": hops,
                    "budget_bytes": budget_bytes,
                    "seeds": list(seeds),
                },
                "confidence": 0.9,
                "known_gaps": ["PPR 仅使用静态 import 邻接，不含运行时调用与动态 import"],
            }
        ]
        + _stable_evidence([e.to_dict() for e in result.evidence])
        + _stable_evidence(lsp_evidence)
    )

    known_gaps = _collect_known_gaps(evidence) + lsp_gaps
    known_gaps.append(f"ranked_nodes 为 {hops} 跳内 PPR 排序结果，超出预算的条目见 trimmed")
    if entry and not entry_rel:
        known_gaps.append(
            f"entry={entry!r} 未能唯一解析（路径不存在或 index/page 等泛名多命中），已改用 feature 匹配"
        )
    if feature and not entry and not matched:
        known_gaps.append(f"feature={feature!r} 未匹配到任何模块，种子退化为前 3 个模块")

    payload: Dict[str, Any] = {
        "feature": feature,
        "language": "typescript",
        "algorithm": "ppr_v2",
        "matched": matched,
        "seeds": seeds,
        "ranked_nodes": ranked_all,
        "edges": [],
        "call_chain": {
            "seeds": seeds,
            "callers": upstream,
            "callees": downstream,
            "entry_chain": entry_chain,
        },
        "stats": {
            "nodes": len(nodes),
            "edges": sum(len(v) for v in adjacency.values()),
            "seeds": len(seeds),
            "ranked": len(ranked_all),
            "upstream": sum(len(v) for v in upstream.values()),
            "downstream": sum(len(v) for v in downstream.values()),
        },
        "evidence": evidence[:1],
        "known_gaps": known_gaps[:8],
        "trace_id": trace_id,
    }
    if lsp_summary:
        payload["lsp"] = lsp_summary
    payload = _fit_trace_budget(payload, adjacency, budget_bytes, extra_evidence=evidence[1:8])
    return _make_output("S33_rea_trace", trace_id, ok=True, result=payload)


# ---------------------------------------------------------------------------
# S33_rea_analyze - 整体架构分析
# ---------------------------------------------------------------------------


def S33_rea_analyze(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_analyze 节点：整体架构分析（SPEC-33-D §2.2/§2.3/§2.4）。

    Params:
        target: 本地路径（目录或文件）（必填）
        scope:  summary / architecture / full（可选，默认 summary；非法值归一化 summary）
        force:  跳过读缓存（可选，默认 false）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {target, language, scope, summary, stats, known_gaps, degraded,
                      evidence_counts, snapshot_id, cache_hit, ...scope 附加项}
        ok=False:
            error: missing_target / invalid_target_type / <异常>
    """
    target = str(params.get("target") or "").strip()
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33an"))
    if not target:
        return _make_output(
            "S33_rea_analyze",
            trace_id,
            ok=False,
            result={},
            error="missing_target",
        )

    scope = str(params.get("scope") or _DEFAULT_SCOPE).strip().lower()
    if scope not in _SCOPES:
        scope = _DEFAULT_SCOPE
    force = _as_bool(params.get("force"))

    language = detect_target_language(target)
    if language == "unknown":
        return _make_output(
            "S33_rea_analyze",
            trace_id,
            ok=False,
            result={},
            error="invalid_target_type",
        )

    # 记录器：日常分析自动回流回放池（FAIL-OPEN，失败不阻断分析）
    recorder = _begin_analysis_recorder(params, target, scope)

    try:
        tree_hash = _tree_hash(target)
        snapshot_id = _snapshot_id(target, tree_hash)
        cache_key = _cache_key(target, language, tree_hash)
        analysis: Optional[Dict[str, Any]] = None
        cache_hit = False

        if not force:
            cached = _load_cache(cache_key)
            if isinstance(cached, dict) and isinstance(cached.get("analysis"), dict):
                analysis = cached["analysis"]
                snapshot_id = str(cached.get("snapshot_id") or snapshot_id)
                cache_hit = True

        if analysis is None:
            if language == "typescript":
                analysis = _analyze_ts_target(target)
            else:
                analysis = _analyze_python_target(target)
            if analysis is None:
                return _make_output(
                    "S33_rea_analyze",
                    trace_id,
                    ok=False,
                    result={},
                    error="invalid_target_type",
                )
            _save_cache(
                cache_key,
                {
                    "snapshot_id": snapshot_id,
                    "language": language,
                    "analysis": analysis,
                },
            )

        # SPEC-F T-F06：rea_rules.yaml 存在时执行架构约束检查
        _check_and_attach_constraints(target, analysis)
        # 首次落盘必须包含约束违例，供 SARIF 等下游 section 消费。
        if not cache_hit or not (_SNAPSHOT_DIR / f"{snapshot_id}.json").is_file():
            _write_snapshot(snapshot_id, analysis, trace_id)

        # 缓存命中也记录一次分析器调用（回放池记录不落分析结果本身）
        _record_analysis(recorder, analysis, target)
        tree_id = _commit_recorder(recorder)
        result = _shape_result(
            analysis,
            scope=scope,
            snapshot_id=snapshot_id,
            cache_hit=cache_hit,
            trace_id=trace_id,
        )
        if tree_id:
            result["replay_tree_id"] = tree_id
        return _make_output("S33_rea_analyze", trace_id, ok=True, result=result)
    except Exception as e:
        return _make_output(
            "S33_rea_analyze",
            trace_id,
            ok=False,
            result={},
            error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# S33_rea_trace - 功能追踪
# ---------------------------------------------------------------------------


def S33_rea_trace(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_trace 节点：功能追踪 — 某功能是怎么实现的。

    Params:
        target:  本地路径（目录或文件）（必填）
        feature: 要追踪的功能描述（必填）
        entry:   可选入口函数/类名
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {feature, call_chain, evidence, known_gaps}
        ok=False:
            error: 错误描述
    """
    target = str(params.get("target") or "").strip()
    if not target:
        return _make_output(
            "S33_rea_trace",
            str(params.get("trace_id") or _gen_trace_id("s33tr")),
            ok=False,
            result={},
            error="missing_target",
        )

    feature = str(params.get("feature") or "").strip()
    if not feature:
        return _make_output(
            "S33_rea_trace",
            str(params.get("trace_id") or _gen_trace_id("s33tr")),
            ok=False,
            result={},
            error="missing_feature",
        )

    entry = params.get("entry")
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33tr"))

    try:
        if detect_target_language(target) == "typescript":
            algorithm = str(params.get("algorithm") or "ppr").strip().lower()
            if algorithm == "legacy":
                return _trace_ts_target_legacy(target, feature, entry, trace_id)
            try:
                budget_bytes = int(params.get("budget_bytes") or _TRACE_DEFAULT_BUDGET)
            except (TypeError, ValueError):
                budget_bytes = _TRACE_DEFAULT_BUDGET
            try:
                hops = int(
                    params.get("hops") if params.get("hops") is not None else _TRACE_DEFAULT_HOPS
                )
            except (TypeError, ValueError):
                hops = _TRACE_DEFAULT_HOPS
            return _trace_ts_target_v2(
                target,
                feature,
                entry,
                trace_id,
                budget_bytes=max(512, min(budget_bytes, 65_536)),
                hops=max(0, min(hops, 3)),
                use_lsp=_as_bool(params.get("lsp")),
            )
        tracer = CallChainTracer()
        chain_result = tracer.trace(target, entry=entry)

        evidence_list = [e.to_dict() for e in chain_result.get("evidence", [])]
        lsp_summary: Dict[str, Any] = {}
        lsp_seeds: list[str] = []
        if _as_bool(params.get("lsp")):
            from adapters.lsp_adapter import inspect_symbols

            refs = [str(value) for value in (entry, feature) if value]
            symbol_report = inspect_symbols(target, refs, language="python")
            lsp_seeds = sorted(
                {
                    str(location.get("file"))
                    for locations in (symbol_report.get("locations") or {}).values()
                    for location in locations
                    if location.get("file")
                }
            )
            evidence_list.extend(symbol_report.get("evidence") or [])
            lsp_summary = {
                "degraded": bool(symbol_report.get("degraded")),
                "tools": symbol_report.get("tools") or {},
                "seed_count": len(lsp_seeds),
            }

        entry_chain = chain_result.get("entry_chain")

        known_gaps = []
        if not entry_chain:
            known_gaps.append("未指定入口或入口函数不在分析范围内")
        if not chain_result.get("callees"):
            known_gaps.append("未检测到函数调用关系（可能全是外部库调用）")

        call_chain = {
            "callers": chain_result.get("callers", {}),
            "callees": chain_result.get("callees", {}),
            "all_functions": chain_result.get("all_functions", []),
            "entry_chain": entry_chain,
        }
        if lsp_summary:
            call_chain["lsp_seeds"] = lsp_seeds

        result = {
            "feature": feature,
            "call_chain": call_chain,
            "evidence": evidence_list,
            "known_gaps": known_gaps,
            "trace_id": trace_id,
        }
        if lsp_summary:
            result["lsp"] = lsp_summary
        return _make_output(
            "S33_rea_trace",
            trace_id,
            ok=True,
            result=result,
        )
    except Exception as e:
        return _make_output(
            "S33_rea_trace",
            trace_id,
            ok=False,
            result={},
            error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# S33_rea_compare - 两工程对比
# ---------------------------------------------------------------------------


def S33_rea_compare(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_compare 节点：两工程对比。

    Params:
        target_a: 工程A路径（必填）
        target_b: 工程B路径（必填）
        feature:  对比的功能描述
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {common, differences, evidence_a, evidence_b}
        ok=False:
            error: 错误描述
    """
    target_a = str(params.get("target_a") or "").strip()
    target_b = str(params.get("target_b") or "").strip()

    if not target_a or not target_b:
        return _make_output(
            "S33_rea_compare",
            str(params.get("trace_id") or _gen_trace_id("s33cmp")),
            ok=False,
            result={},
            error="missing_targets",
        )

    feature = str(params.get("feature") or "整体架构")  # noqa: F841
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33cmp"))

    try:
        # 分析工程A
        result_a = _analyze_project(target_a)
        # 分析工程B
        result_b = _analyze_project(target_b)

        # 对比
        modules_a = set(result_a.get("modules", []))
        modules_b = set(result_b.get("modules", []))
        common_modules = sorted(modules_a & modules_b)
        only_a = sorted(modules_a - modules_b)
        only_b = sorted(modules_b - modules_a)
        # SPEC-F P-F02：两套口径并存——common.modules 仍是完整路径，
        # common_module_names 按相对路径尾段名（basename）比对，跨工程同构时才有意义
        common_module_names = sorted(
            {os.path.basename(m) for m in modules_a} & {os.path.basename(m) for m in modules_b}
        )

        funcs_a = set(result_a.get("functions", []))
        funcs_b = set(result_b.get("functions", []))
        common_funcs = sorted(funcs_a & funcs_b)
        only_a_funcs = sorted(funcs_a - funcs_b)
        only_b_funcs = sorted(funcs_b - funcs_a)

        return _make_output(
            "S33_rea_compare",
            trace_id,
            ok=True,
            result={
                "common": {
                    "modules": common_modules,
                    "common_module_names": common_module_names,
                    "module_names_basis": "relative_path_basename",
                    "functions": common_funcs,
                },
                "differences": {
                    "only_in_a": {"modules": only_a, "functions": only_a_funcs},
                    "only_in_b": {"modules": only_b, "functions": only_b_funcs},
                },
                "evidence_a": result_a.get("evidence", []),
                "evidence_b": result_b.get("evidence", []),
                "summary_a": result_a.get("summary", ""),
                "summary_b": result_b.get("summary", ""),
                "trace_id": trace_id,
            },
        )
    except Exception as e:
        return _make_output(
            "S33_rea_compare",
            trace_id,
            ok=False,
            result={},
            error=f"{type(e).__name__}: {e}",
        )


def _analyze_project(target: str) -> Dict[str, Any]:
    """辅助：分析单个工程，返回模块/函数/evidence（按语言路由，见 SPEC §2.2）。"""
    language = detect_target_language(target)
    result: Dict[str, Any] = {
        "modules": [],
        "functions": [],
        "evidence": [],
        "summary": "",
        "language": language,
    }

    if language == "typescript":
        analysis = _analyze_ts_target(target)
        raw = analysis.get("raw") or {}
        graph = raw.get("graph") or {}
        result["modules"] = list(graph.get("nodes") or [])
        result["functions"] = [
            str(c.get("name")) for c in (raw.get("components") or []) if c.get("name")
        ]
        result["evidence"] = analysis.get("evidence") or []
        result["summary"] = analysis.get("summary") or ""
        return result

    if os.path.isfile(target) and target.endswith(".py"):
        analyzer = PythonAnalyzer()
        res = analyzer.analyze(target)
        result["modules"] = [os.path.basename(target)]
        result["evidence"] = [e.to_dict() for e in res.evidence]
        result["summary"] = res.summary
    elif os.path.isdir(target):
        dep_graph = DependencyGraph()
        dep_res = dep_graph.build(target)
        tracer = CallChainTracer()
        chain_res = tracer.trace(target)
        project_modules, _external = _split_python_modules(target, dep_res.get("nodes", []))

        result["modules"] = project_modules
        result["functions"] = chain_res.get("all_functions", [])
        result["evidence"] = [e.to_dict() for e in dep_res.get("evidence", [])] + [
            e.to_dict() for e in chain_res.get("evidence", [])
        ]
        result["summary"] = f"{len(result['modules'])} 模块, " f"{len(result['functions'])} 函数"

    return result


# ---------------------------------------------------------------------------
# S33_rea_investigate - 逆向调查工作流
# ---------------------------------------------------------------------------


def S33_rea_investigate(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_investigate 节点：四阶段逆向调查工作流。

    定位(Locate)→追踪(Trace)→还原(Reduce)→标注(Annotate)

    Params:
        target: 本地路径（目录或文件）（必填）
        feature: 要调查的功能描述（可选）
        entry: 入口函数名（可选）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {summary, phases, evidence, known_gaps, cognitive_record}
        ok=False:
            error: 错误描述
    """
    target = str(params.get("target") or "").strip()
    if not target:
        return _make_output(
            "S33_rea_investigate",
            str(params.get("trace_id") or _gen_trace_id("s33inv")),
            ok=False,
            result={},
            error="missing_target",
        )

    feature = params.get("feature")
    entry = params.get("entry")
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33inv"))

    try:
        investigation = investigate(target, feature=feature, entry=entry)

        # 准备认知记忆参数
        cognitive_record = prepare_record_params(investigation)

        # 序列化 Evidence
        evidence_dicts = [
            e.to_dict() if hasattr(e, "to_dict") else e for e in investigation.get("evidence", [])
        ]

        return _make_output(
            "S33_rea_investigate",
            trace_id,
            ok=True,
            result={
                "summary": investigation.get("summary", ""),
                "feature": investigation.get("feature"),
                "phases": investigation.get("phases", {}),
                "evidence": evidence_dicts,
                "known_gaps": investigation.get("known_gaps", []),
                "cognitive_record": cognitive_record,
                "trace_id": trace_id,
            },
        )
    except Exception as e:
        return _make_output(
            "S33_rea_investigate",
            trace_id,
            ok=False,
            result={},
            error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# S33_rea_recover_decisions - 设计决策还原（PoE Task 2）
# ---------------------------------------------------------------------------


def S33_rea_recover_decisions(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_recover_decisions 节点：设计决策还原（ADR 风格）。

    Params:
        target: 本地路径（目录或文件）（必填）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {target, decisions, evidence, known_gaps, cognitive_record}
    """
    target = str(params.get("target") or "").strip()
    if not target:
        return _make_output(
            "S33_rea_recover_decisions",
            str(params.get("trace_id") or _gen_trace_id("s33dec")),
            ok=False,
            result={},
            error="missing_target",
        )

    trace_id = str(params.get("trace_id") or _gen_trace_id("s33dec"))

    try:
        decision_result = recover_decisions(target)

        # 准备认知记忆参数
        cognitive_record = prepare_decision_record_params(decision_result)

        # 序列化 Evidence
        evidence_list = []
        known_gaps: list[str] = []
        for e in decision_result.get("evidence", []):
            if hasattr(e, "to_dict"):
                evidence_list.append(e.to_dict())
            else:
                evidence_list.append(e)
            # 提取 known_gaps
            gaps = getattr(e, "known_gaps", []) if hasattr(e, "known_gaps") else []
            known_gaps.extend(gaps)

        return _make_output(
            "S33_rea_recover_decisions",
            trace_id,
            ok=True,
            result={
                "target": target,
                "decisions": decision_result.get("decisions", []),
                "evidence": evidence_list,
                "known_gaps": known_gaps,
                "cognitive_record": cognitive_record,
                "trace_id": trace_id,
            },
        )
    except Exception as e:
        # FAIL-OPEN（TR-7.3）：返回含 unknown Evidence 的部分结果，不中断
        from core.evidence import Evidence, EvidenceLevel

        ev = Evidence(
            result=f"设计决策还原失败: {e}",
            level=EvidenceLevel.UNKNOWN,
            provenance={"target": target, "analysis": "recover_decisions"},
            confidence=0.0,
            known_gaps=[f"节点异常: {type(e).__name__}: {e}"],
        )
        return _make_output(
            "S33_rea_recover_decisions",
            trace_id,
            ok=True,
            result={
                "target": target,
                "decisions": [],
                "evidence": [ev.to_dict()],
                "known_gaps": [f"节点异常: {e}"],
                "trace_id": trace_id,
            },
        )


# ---------------------------------------------------------------------------
# S33_rea_narrative - 演化叙事生成（PoE Task 3）
# ---------------------------------------------------------------------------


def S33_rea_narrative(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_narrative 节点：演化叙事生成。

    Params:
        target: git 仓库根路径（必填）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {target, turning_points, tech_debt_timeline, evidence, known_gaps}
    """
    target = str(params.get("target") or "").strip()
    if not target:
        return _make_output(
            "S33_rea_narrative",
            str(params.get("trace_id") or _gen_trace_id("s33nar")),
            ok=False,
            result={},
            error="missing_target",
        )

    trace_id = str(params.get("trace_id") or _gen_trace_id("s33nar"))

    try:
        narrative_result = generate_narrative(target)

        # 序列化 Evidence + 提取 known_gaps
        evidence_list = []
        known_gaps: list[str] = []
        for e in narrative_result.get("evidence", []):
            if hasattr(e, "to_dict"):
                evidence_list.append(e.to_dict())
            else:
                evidence_list.append(e)
            gaps = getattr(e, "known_gaps", []) if hasattr(e, "known_gaps") else []
            known_gaps.extend(gaps)

        return _make_output(
            "S33_rea_narrative",
            trace_id,
            ok=True,
            result={
                "target": target,
                "turning_points": narrative_result.get("turning_points", []),
                "tech_debt_timeline": narrative_result.get("tech_debt_timeline", []),
                "evidence": evidence_list,
                "known_gaps": known_gaps,
                "trace_id": trace_id,
            },
        )
    except Exception as e:
        from core.evidence import Evidence, EvidenceLevel

        ev = Evidence(
            result=f"演化叙事生成失败: {e}",
            level=EvidenceLevel.UNKNOWN,
            provenance={"target": target, "analysis": "generate_narrative"},
            confidence=0.0,
            known_gaps=[f"节点异常: {type(e).__name__}: {e}"],
        )
        return _make_output(
            "S33_rea_narrative",
            trace_id,
            ok=True,
            result={
                "target": target,
                "turning_points": [],
                "tech_debt_timeline": [],
                "evidence": [ev.to_dict()],
                "known_gaps": [f"节点异常: {e}"],
                "trace_id": trace_id,
            },
        )


# ---------------------------------------------------------------------------
# S33_rea_audit - AI 产出审计（PoE Task 5 — 核心门禁）
# ---------------------------------------------------------------------------


def _analysis_graph_nodes(analysis: Dict[str, Any]) -> list[str]:
    """从分析结果里取静态图节点（TS 用 graph.nodes，Python 用模块+邻接键）。"""
    raw = analysis.get("raw") or {}
    if analysis.get("language") == "typescript":
        return list((raw.get("graph") or {}).get("nodes") or [])
    nodes = set(raw.get("modules") or [])
    nodes.update((raw.get("dependencies") or {}).keys())
    return sorted(nodes)


def _audit_hypotheses_node(
    target: str,
    hypotheses: list[Dict[str, Any]],
    trace_id: str,
    *,
    use_lsp: bool = False,
) -> Dict[str, Any]:
    """SPEC-33-E：假设门禁（契约 → 静态复核 → PoE gate → 认知写入建议）。"""
    language = detect_target_language(target)
    if language == "typescript":
        analysis = _analyze_ts_target(target)
    else:
        analysis = _analyze_python_target(target)
    if analysis is None:
        return _make_output(
            "S33_rea_audit", trace_id, ok=False, result={}, error="invalid_target_type"
        )

    nodes = _analysis_graph_nodes(analysis)
    symbol_report: Dict[str, Any] = {}
    if use_lsp:
        from adapters.lsp_adapter import inspect_symbols

        refs = list(
            dict.fromkeys(
                str(ref)
                for hypothesis in hypotheses
                for ref in (hypothesis.get("target_refs") or [])
            )
        )
        symbol_report = inspect_symbols(target, refs, language=language)
    results = audit_hypotheses(
        hypotheses,
        nodes,
        semantic_locations=(symbol_report.get("locations") or {}) if use_lsp else None,
    )
    counts = {"pass": 0, "review": 0, "reject": 0}
    for item in results:
        gate = str(item.get("gate") or "reject")
        counts[gate] = counts.get(gate, 0) + 1

    evidence = [
        {
            "result": (
                f"假设门禁: {len(results)} 条（pass={counts['pass']}, "
                f"review={counts['review']}, reject={counts['reject']}）"
            ),
            "level": "derivation",
            "provenance": {
                "target": os.path.abspath(target),
                "analysis": "hypothesis_gate",
                "graph_nodes": len(nodes),
            },
            "confidence": 0.85,
            "known_gaps": [
                "target_refs 仅与静态图节点比对，未做语义等价校验",
                "PoE 公式复用 ai_audit，未针对假设场景重新标定权重",
            ],
        }
    ]
    if symbol_report:
        evidence.extend(symbol_report.get("evidence") or [])
    result = {
        "target": os.path.abspath(target),
        "language": language,
        "mode": "hypothesis",
        "stats": {
            "hypotheses": len(results),
            "graph_nodes": len(nodes),
            **counts,
        },
        "hypotheses": results,
        "cognitive_hint": build_write_hint(results, target),
        "evidence": evidence,
        "known_gaps": _collect_known_gaps(evidence),
        "trace_id": trace_id,
    }
    if symbol_report:
        result["lsp"] = {
            "degraded": bool(symbol_report.get("degraded")),
            "tools": symbol_report.get("tools") or {},
            "resolved": sum(bool(v) for v in (symbol_report.get("locations") or {}).values()),
            "total": len(symbol_report.get("locations") or {}),
        }
    return _make_output("S33_rea_audit", trace_id, ok=True, result=result)


def S33_rea_adapt_plan(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_adapt_plan 节点（SPEC-33-E T-E5）：只出改造方案，不改代码。

    Params:
        plans: 方案数组（必填），每条需 plan_id/target_module/change/
               evidence_ref/rollback/acceptance；缺一即丢弃并计 known_gaps
        target: 可选工程根；与 hypotheses 同时提供时按 PoE gate 只采纳 pass
        hypotheses: 可选假设数组（需 target 才能静态复核）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        result = {mode, target, stats, plans, dropped, cognitive_hint,
                  known_gaps, evidence, trace_id}
    """
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33plan"))
    plans = params.get("plans")
    if not isinstance(plans, list) or not plans:
        return _make_output(
            "S33_rea_adapt_plan", trace_id, ok=False, result={}, error="missing_plans"
        )

    target = str(params.get("target") or "").strip()
    gates: Optional[Dict[str, str]] = None
    hypotheses = params.get("hypotheses")
    if target and isinstance(hypotheses, list) and hypotheses:
        language = detect_target_language(target)
        analysis = (
            _analyze_ts_target(target)
            if language == "typescript"
            else _analyze_python_target(target)
        )
        if analysis is None:
            return _make_output(
                "S33_rea_adapt_plan", trace_id, ok=False, result={}, error="invalid_target_type"
            )
        results = audit_hypotheses(
            [h for h in hypotheses if isinstance(h, dict)],
            _analysis_graph_nodes(analysis),
        )
        gates = {
            str(item.get("hypothesis_id")): str(item.get("gate") or "reject") for item in results
        }

    valid_plans = [plan for plan in plans if isinstance(plan, dict)]
    report = build_adapt_plans(valid_plans, gates=gates)
    evidence = [
        {
            "result": (
                f"改造方案: 采纳 {len(report['plans'])} 条，"
                f"丢弃 {len(report['dropped'])} 条（门槛: evidence_ref+rollback+acceptance）"
            ),
            "level": "derivation",
            "provenance": {
                "target": os.path.abspath(target) if target else "",
                "analysis": "adapt_plan",
                "plans": len(valid_plans),
                "gate_mode": "hypothesis" if gates is not None else "unspecified",
            },
            "confidence": 0.85,
            "known_gaps": [],
        }
    ]
    result = {
        "mode": "adapt_plan",
        "target": os.path.abspath(target) if target else "",
        "stats": {
            "plans": len(report["plans"]),
            "dropped": len(report["dropped"]),
            "passed_hypotheses": len(report["passed_hypotheses"]),
        },
        "plans": report["plans"],
        "dropped": report["dropped"],
        "cognitive_hint": report["cognitive_hint"],
        "known_gaps": list(report["known_gaps"]),
        "evidence": evidence,
        "trace_id": trace_id,
    }
    return _make_output("S33_rea_adapt_plan", trace_id, ok=True, result=result)


def S33_rea_score_sources(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_score_sources 节点（SPEC-33-E T-E6）：外部源价值评分门禁。

    Params:
        sources: 源列表（必填，除非给 path）；每条需 id
        scores: 打分数组 [{source_id, relevance_score, gate}]；仅 gate=pass 生效
        path: 可选外部源文件路径；提供时从文件读取源并可用 write=true 落库
        write: 是否把过门禁的分数写回 path（默认 false）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        result = {mode, stats, updated, rejected, written, known_gaps, evidence, trace_id}
    """
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33rel"))
    scores = params.get("scores")
    if not isinstance(scores, list):
        scores = []

    sources = params.get("sources")
    path = str(params.get("path") or "").strip()
    if not isinstance(sources, list):
        if not path:
            return _make_output(
                "S33_rea_score_sources", trace_id, ok=False, result={}, error="missing_sources"
            )
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            sources = payload.get("sources") if isinstance(payload, dict) else payload
        except (OSError, ValueError) as exc:
            return _make_output(
                "S33_rea_score_sources",
                trace_id,
                ok=True,
                result={
                    "mode": "relevance",
                    "stats": {"sources": 0, "updated": 0, "rejected": len(scores)},
                    "updated": [],
                    "rejected": [],
                    "written": None,
                    "known_gaps": [f"外部源文件不可读或损坏: {type(exc).__name__}: {exc}"],
                    "evidence": [],
                    "trace_id": trace_id,
                },
            )
        if not isinstance(sources, list):
            return _make_output(
                "S33_rea_score_sources", trace_id, ok=False, result={}, error="invalid_sources"
            )

    report = apply_relevance_scores(sources, scores)
    written = None
    known_gaps = list(report["known_gaps"])
    if _as_bool(params.get("write")) and path:
        written = write_relevance_scores(path, report)
        known_gaps.extend(written.get("known_gaps") or [])

    evidence = [
        {
            "result": (
                f"外部源评分: 生效 {len(report['updated'])} 条，"
                f"拒绝 {len(report['rejected'])} 条（仅 gate=pass 可写 relevance_score）"
            ),
            "level": "derivation",
            "provenance": {
                "analysis": "relevance_score",
                "sources": len(report["sources"]),
                "path": path,
                "persisted": written is not None,
            },
            "confidence": 0.85,
            "known_gaps": [],
        }
    ]
    return _make_output(
        "S33_rea_score_sources",
        trace_id,
        ok=True,
        result={
            "mode": "relevance",
            "stats": {
                "sources": len(report["sources"]),
                "updated": len(report["updated"]),
                "rejected": len(report["rejected"]),
            },
            "updated": report["updated"],
            "rejected": report["rejected"],
            "written": written,
            "known_gaps": known_gaps,
            "evidence": evidence,
            "trace_id": trace_id,
        },
    )


def S33_rea_incremental_index(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_incremental_index 节点（SPEC-33-F T-F17）：文件级 Merkle 与跨版本 diff。

    Params:
        target: 工程根（必填）
        index_path: 可选索引路径；缺省落 reflection_data/index/<hash>.json
        persist: 是否写回索引（默认 true）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        result = {mode, target, root_hash, stats, invalidated_files, diff,
                  index_path, evidence, known_gaps, trace_id}
    """
    from core.incremental_index import (
        build_merkle,
        diff_merkle,
        load_index,
        save_index,
    )

    trace_id = str(params.get("trace_id") or _gen_trace_id("s33idx"))
    target = str(params.get("target") or "").strip()
    if not target or not Path(target).expanduser().exists():
        return _make_output(
            "S33_rea_incremental_index", trace_id, ok=False, result={}, error="missing_target"
        )

    index_path = str(params.get("index_path") or "").strip()
    if not index_path:
        digest = hashlib.sha1(str(Path(target).expanduser().resolve()).encode("utf-8")).hexdigest()[
            :16
        ]
        index_path = str(_REFLECTION_DIR / "index" / f"{digest}.json")

    previous, known_gaps = load_index(index_path)
    current = build_merkle(target)
    diff = diff_merkle(previous, current)
    persisted = False
    if _as_bool(params.get("persist", True)):
        save_index(index_path, current)
        persisted = True

    total = current["count"]
    reused = diff["unchanged"]
    evidence = [
        {
            "result": (
                f"增量索引: {total} 文件，失效 {len(diff['invalidated_files'])}"
                f"（+{len(diff['added'])} ~{len(diff['modified'])} -{len(diff['removed'])}），"
                f"复用 {reused}"
            ),
            "level": "observation",
            "provenance": {
                "target": str(Path(target).expanduser().resolve()),
                "analysis": "incremental_index",
                "index_path": index_path,
            },
            "confidence": 0.95,
            "known_gaps": [],
        }
    ]
    return _make_output(
        "S33_rea_incremental_index",
        trace_id,
        ok=True,
        result={
            "mode": "incremental_index",
            "root_hash": current["root_hash"],
            "stats": {
                "files": total,
                "added": len(diff["added"]),
                "modified": len(diff["modified"]),
                "removed": len(diff["removed"]),
                "unchanged": reused,
                "reused_ratio": round(reused / total, 4) if total else 0.0,
            },
            "invalidated_files": diff["invalidated_files"],
            "diff": diff,
            "index_path": index_path,
            "persisted": persisted,
            "known_gaps": known_gaps,
            "evidence": evidence,
            "trace_id": trace_id,
        },
    )


def S33_rea_cost_ledger(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_cost_ledger 节点（SPEC-33-E T-E8）：token 预算校验 + 成本记账。

    Params:
        model: 模型标识（必填）
        tokens_in / tokens_out: 本次生成用量
        gate: 本次结论的 PoE gate（可选）
        task: 任务标识（可选）
        path: 台账路径（可选，缺省 reflection_data/reports/llm_cost.jsonl）
        trace_id: 调用方传入的 trace_id（可选）
    """
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33cost"))
    model = str(params.get("model") or "").strip()
    if not model:
        return _make_output(
            "S33_rea_cost_ledger", trace_id, ok=False, result={}, error="missing_model"
        )

    budget = check_budget(params.get("tokens_in"), params.get("tokens_out"))
    recorded = record_cost(
        {
            "model": model,
            "tokens_in": budget["tokens_in"],
            "tokens_out": budget["tokens_out"],
            "gate": params.get("gate"),
            "task": params.get("task"),
        },
        path=params.get("path"),
    )
    known_gaps = list(recorded.get("known_gaps") or [])
    if budget["degraded"]:
        known_gaps.append(f"token 预算超限，降级模板输出: {budget['reason']}")
    evidence = [
        {
            "result": (
                f"成本记账: {model} in={budget['tokens_in']} out={budget['tokens_out']} "
                f"gate={params.get('gate') or 'unknown'} recorded={recorded['recorded']}"
            ),
            "level": "observation",
            "provenance": {"analysis": "llm_cost", "ledger": recorded["path"]},
            "confidence": 0.9,
            "known_gaps": [],
        }
    ]
    return _make_output(
        "S33_rea_cost_ledger",
        trace_id,
        ok=True,
        result={
            "mode": "llm_budget",
            "budget": budget,
            "recorded": recorded["recorded"],
            "path": recorded["path"],
            "record": recorded.get("record"),
            "known_gaps": known_gaps,
            "evidence": evidence,
            "trace_id": trace_id,
        },
    )


def S33_rea_writeback(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_writeback 节点（SPEC-33-E T-E9）：过 gate 结论的认知回写载荷。

    Params:
        items: 假设/方案裁判结果数组（必填）；gate=reject/unknown 不写
        enabled: 可选覆写写开关；缺省读 COGNITIVE_MCP_WRITE_ENABLED
        trace_id: 调用方传入的 trace_id（可选）
    """
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33wb"))
    items = params.get("items")
    if not isinstance(items, list):
        return _make_output(
            "S33_rea_writeback", trace_id, ok=False, result={}, error="missing_items"
        )

    enabled = params.get("enabled")
    status = writeback_status(items, enabled=enabled if isinstance(enabled, bool) else None)
    evidence = [
        {
            "result": (
                f"认知回写: status={status['status']} writes={len(status['writes'])} "
                f"skipped={len(status['skipped'])}"
            ),
            "level": "derivation",
            "provenance": {"analysis": "cognitive_writeback", "enabled": status["enabled"]},
            "confidence": 0.9,
            "known_gaps": [],
        }
    ]
    return _make_output(
        "S33_rea_writeback",
        trace_id,
        ok=True,
        result={
            "mode": "cognitive_writeback",
            "status": status["status"],
            "enabled": status["enabled"],
            "writes": status["writes"],
            "skipped": status["skipped"],
            "known_gaps": status["known_gaps"],
            "evidence": evidence,
            "trace_id": trace_id,
        },
    )


def _coerce_evidence(raw: Any) -> Any:
    """把 JSON 传入的 evidence dict 还原成 Evidence 对象（方法论抽象需要 evidence_id）。"""
    if not isinstance(raw, dict):
        return raw
    try:
        return Evidence(
            result=str(raw.get("result") or ""),
            level=EvidenceLevel(str(raw.get("level") or "unknown")),
            provenance=raw.get("provenance") or {},
            confidence=float(raw.get("confidence") or 0.0),
            known_gaps=list(raw.get("known_gaps") or []),
        )
    except (TypeError, ValueError):
        return None


def get_rea_methodology(params: Dict[str, Any]) -> Dict[str, Any]:
    """方法论抽象（SPEC-33-E T-E3）：跨项目同模式 ≥2 才产出模板。

    Params:
        investigations: 直接传入多项目调查结果（可选）
        targets: 需要先分析的本地项目路径列表（可选）
        trace_id: 调用方传入的 trace_id（可选）
    """
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33mth"))
    investigations: list[Dict[str, Any]] = []
    for item in params.get("investigations") or []:
        if not isinstance(item, dict):
            continue
        patterns = []
        for pattern in item.get("patterns") or []:
            if not isinstance(pattern, dict):
                continue
            evidence = _coerce_evidence(pattern.get("evidence"))
            if pattern.get("pattern") and evidence is not None:
                patterns.append({**pattern, "evidence": evidence})
        investigations.append({**item, "patterns": patterns})
    targets = [str(t) for t in (params.get("targets") or []) if str(t).strip()]

    known_gaps: list[str] = []
    for path in targets:
        language = detect_target_language(path)
        if language == "typescript":
            analysis = _analyze_ts_target(path)
        else:
            analysis = _analyze_python_target(path)
        if analysis is None:
            known_gaps.append(f"目标不可分析，已跳过: {path}")
            continue
        patterns = []
        for item in (analysis.get("raw") or {}).get("patterns") or []:
            if not isinstance(item, dict):
                continue  # NFR-1：无 Evidence 的模式不入聚类
            name = item.get("pattern") or item.get("name")
            item_evidence = _coerce_evidence(item.get("evidence"))
            if name and item_evidence is not None:
                patterns.append(
                    {
                        "pattern": name,
                        "matched_dirs": item.get("matched_dirs") or [],
                        "evidence": item_evidence,
                    }
                )
        investigations.append({"target": os.path.abspath(path), "patterns": patterns})

    if not investigations:
        return _make_output(
            "get_rea_methodology",
            trace_id,
            ok=True,
            result={
                "methodologies": [],
                "stats": {"investigations": 0, "methodologies": 0},
                "evidence": [],
                "known_gaps": ["无输入：请提供 investigations 或 targets"],
                "trace_id": trace_id,
            },
        )

    abstracted = MethodologyAbstractor().abstract(investigations)
    evidence = []
    for e in abstracted.get("evidence", []):
        evidence.append(e.to_dict() if hasattr(e, "to_dict") else e)
    known_gaps.extend(_collect_known_gaps(evidence))
    known_gaps.append("仅统计带 evidence 的模式；同一模式需 ≥2 个项目才蒸馏为模板")
    methodologies = []
    for item in abstracted.get("methodologies", []):
        record = item if isinstance(item, dict) else item.to_dict()
        if hasattr(record.get("evidence"), "to_dict"):
            record["evidence"] = record["evidence"].to_dict()
        methodologies.append(record)
    return _make_output(
        "get_rea_methodology",
        trace_id,
        ok=True,
        result={
            "methodologies": methodologies,
            "stats": {
                "investigations": len(investigations),
                "methodologies": len(methodologies),
            },
            "evidence": evidence,
            "known_gaps": known_gaps,
            "trace_id": trace_id,
        },
    )


def S33_rea_audit(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_audit 节点：AI 产出审计（PoE 核心门禁）。

    Params:
        target: AI 产出代码目录或文件路径（必填）
        ai_context: 可选 AI 上下文（agent_id/model/prompt_hash/timestamp）
        trace_id: 调用方传入的 trace_id（可选）

    Returns (SubagentOutput):
        ok=True:
            result = {
                target, evidence_chain_score, poe_score, gate_decision,
                cognitive_debt, evidence, known_gaps, cognitive_record
            }
        ok=False:
            error: 错误描述
    """
    target = str(params.get("target") or "").strip()
    if not target:
        return _make_output(
            "S33_rea_audit",
            str(params.get("trace_id") or _gen_trace_id("s33aud")),
            ok=False,
            result={},
            error="missing_target",
        )

    trace_id = str(params.get("trace_id") or _gen_trace_id("s33aud"))
    ai_context = params.get("ai_context")

    # SPEC-33-E：带 hypotheses 时走假设门禁模式（校验 + 静态复核 + PoE gate）
    hypotheses = params.get("hypotheses")
    if isinstance(hypotheses, list) and hypotheses:
        valid = [h for h in hypotheses if isinstance(h, dict)]
        return _audit_hypotheses_node(target, valid, trace_id, use_lsp=_as_bool(params.get("lsp")))

    try:
        audit_result = audit_ai_output(target, ai_context=ai_context)

        # 准备认知记忆参数
        cognitive_record = prepare_audit_record_params(audit_result)

        # 序列化 Evidence + 提取 known_gaps
        evidence_list = []
        known_gaps: list[str] = []
        for e in audit_result.get("evidence", []):
            if hasattr(e, "to_dict"):
                evidence_list.append(e.to_dict())
            else:
                evidence_list.append(e)
            gaps = getattr(e, "known_gaps", []) if hasattr(e, "known_gaps") else []
            known_gaps.extend(gaps)

        # 认知债务内嵌 Evidence 需序列化（MCP 边界必须 JSON 可序列化）
        debt_list: list[Dict[str, Any]] = []
        for item in audit_result.get("cognitive_debt", []):
            record = item if isinstance(item, dict) else item.to_dict()
            if hasattr(record.get("evidence"), "to_dict"):
                record["evidence"] = record["evidence"].to_dict()
            debt_list.append(record)

        # FAIL-OPEN：审计失败时 audit_result 已含 unknown Evidence
        return _make_output(
            "S33_rea_audit",
            trace_id,
            ok=True,
            result={
                "target": target,
                "evidence_chain_score": audit_result.get("evidence_chain_score", 0.0),
                "coverage_score": audit_result.get("coverage_score", 0.0),
                "complexity_penalty": audit_result.get("complexity_penalty", 0.0),
                "poe_score": audit_result.get("poe_score", 0.0),
                "gate_decision": audit_result.get("gate_decision", "review"),
                "cognitive_debt": debt_list,
                "audit_layer_status": audit_result.get("audit_layer_status", {}),
                "evidence": evidence_list,
                "known_gaps": known_gaps,
                "cognitive_record": cognitive_record,
                "trace_id": trace_id,
            },
        )
    except Exception as e:
        # FAIL-OPEN（TR-7.3 + PoE §5.5）
        from core.evidence import Evidence, EvidenceLevel

        ev = Evidence(
            result=f"AI 审计失败: {e}",
            level=EvidenceLevel.UNKNOWN,
            provenance={"target": target, "analysis": "ai_audit"},
            confidence=0.0,
            known_gaps=[f"节点异常: {type(e).__name__}: {e}"],
        )
        return _make_output(
            "S33_rea_audit",
            trace_id,
            ok=True,
            result={
                "target": target,
                "evidence_chain_score": 0.0,
                "poe_score": 0.0,
                "gate_decision": "review",
                "cognitive_debt": [],
                "evidence": [ev.to_dict()],
                "known_gaps": [f"节点异常: {e}"],
                "trace_id": trace_id,
            },
        )


# ---------------------------------------------------------------------------
# DSH 节点注册表 - 供 DSH server.py 注册路由
# ---------------------------------------------------------------------------


def S33_rea_locate(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_locate 节点：文件定位（C3，41 SPEC §13.3/§7.11）。
    基于 41 code 类型索引按名称/模式定位源码文件，替代节点自建目录遍历。
    Params:
        name: 文件名或模式（必填，支持子串匹配）
        limit: 返回上限（默认 20）
        trace_id: 调用方传入的 trace_id（可选）
    """
    import json as _json
    import subprocess as _sp

    name = str(params.get("name") or "").strip()
    if not name:
        return _make_output(
            "S33_rea_locate",
            str(params.get("trace_id") or _gen_trace_id("s33lc")),
            ok=False,
            result={},
            error="missing_name",
        )
    limit = int(params.get("limit", 20))
    try:
        proc = _sp.run(
            ["/home/ubuntu/fis-p0/.venv/bin/python", "/home/ubuntu/fis-p0/scripts/search_cli.py"],
            input=_json.dumps({"query": name, "limit": limit, "filters": {"type": ["code"]}}),
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "FIS_PG_PASSWORD": os.environ.get("FIS_PG_PASSWORD")},
        )
        res = _json.loads(proc.stdout or "{}")
        hits = res.get("hits", []) if res.get("success") else []
        matched = [
            h["source"]["path"] for h in hits if name.lower() in h["source"]["path"].lower()
        ][:limit]
        return _make_output(
            "S33_rea_locate",
            str(params.get("trace_id") or _gen_trace_id("s33lc")),
            ok=True,
            result={"matched": matched, "count": len(matched), "source": "fis_code_index"},
        )
    except Exception as e:
        return _make_output(
            "S33_rea_locate",
            str(params.get("trace_id") or _gen_trace_id("s33lc")),
            ok=False,
            result={},
            error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# 反思层节点（SPEC-33-反思层 v0.3 §7.1）
# ---------------------------------------------------------------------------
def _reflection_pool(params: Dict[str, Any]):
    from core.reflection.replay_simulator import ReplayPool

    base = str(params.get("pool_dir") or "reflection_data/replay_pool")
    return ReplayPool(base)


def S33_rea_reflect(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_reflect 节点：对分析结果执行 R1-R3 反思。
    Params:
        report: 分析报告 dict（必填，字段见 ReflectionLayer.reflect）
        trace_id: 调用方传入的 trace_id（可选）
    """
    from core.reflection.reflection_layer import ReflectionLayer

    report = params.get("report")
    if not isinstance(report, dict):
        return _make_output(
            "S33_rea_reflect",
            str(params.get("trace_id") or _gen_trace_id("s33rf")),
            ok=False,
            result={},
            error="missing_report",
        )
    critique = ReflectionLayer().reflect(report)
    return _make_output(
        "S33_rea_reflect",
        str(params.get("trace_id") or _gen_trace_id("s33rf")),
        ok=True,
        result=critique,
    )


def S33_rea_dream(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_dream 节点：触发做梦评估循环。
    Params:
        pool_dir: 回放池目录（可选，默认 reflection_data/replay_pool）
        trace_id: 调用方传入的 trace_id（可选）
    """
    from core.reflection.dreaming import DreamingLoop

    pool = _reflection_pool(params)
    if not pool.eval_ready():
        return _make_output(
            "S33_rea_dream",
            str(params.get("trace_id") or _gen_trace_id("s33dm")),
            ok=False,
            result={},
            error="pool_not_eval_ready",
        )
    # current 策略：调用方显式传入优先；缺省从回放池最近内部树推导
    current = params.get("current")
    if not isinstance(current, dict) or not current.get("analyzer_sequence"):
        trees = pool.list_trees("internal")
        if not trees:
            return _make_output(
                "S33_rea_dream",
                str(params.get("trace_id") or _gen_trace_id("s33dm")),
                ok=False,
                result={},
                error="missing_current_and_no_internal_tree",
            )
        latest = trees[-1]
        seq = []
        for node in latest.nodes:
            analyzer = (node.action or {}).get("analyzer")
            if analyzer and analyzer != "init":
                seq.append(analyzer)
        if not seq:
            seq = [n.action.get("analyzer") for n in latest.nodes if n.action.get("analyzer")][:4]
        current = {
            "budget": {"max_calls": 10},
            "parallelism": 1,
            "analyzer_sequence": seq,
            "transform": "current",
        }
    loop = DreamingLoop(pool)
    result = loop.dream(current)
    result["current_derived_from_pool"] = not isinstance(params.get("current"), dict)
    return _make_output(
        "S33_rea_dream",
        str(params.get("trace_id") or _gen_trace_id("s33dm")),
        ok=True,
        result=result,
    )


def S33_rea_replay(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_replay 节点：查询/重放历史分析轨迹。
    Params:
        tree_id: 指定发现树 ID（可选，缺省列出全部）
        provenance: internal / external 过滤（可选）
        pool_dir: 回放池目录（可选）
        trace_id: 调用方传入的 trace_id（可选）
    """
    pool = _reflection_pool(params)
    tree_id = str(params.get("tree_id") or "").strip()
    if tree_id:
        tree = pool.load(tree_id)
        if tree is None:
            return _make_output(
                "S33_rea_replay",
                str(params.get("trace_id") or _gen_trace_id("s33rp")),
                ok=False,
                result={},
                error=f"tree_not_found: {tree_id}",
            )
        result = {"tree": tree.to_dict()}
    else:
        provenance = params.get("provenance")
        trees = pool.list_trees(provenance=str(provenance) if provenance else None)
        result = {
            "count": len(trees),
            "trees": [t.to_dict() for t in trees],
        }
    return _make_output(
        "S33_rea_replay",
        str(params.get("trace_id") or _gen_trace_id("s33rp")),
        ok=True,
        result=result,
    )


def S33_rea_harvest(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_harvest 节点：触发外部路径获取全链路（E1-E4）。
    Params:
        sources: [{source_type, location, label, patterns}]（必填）
        pool_dir: 回放池目录（可选）
        trace_id: 调用方传入的 trace_id（可选）
    """
    from core.reflection.harvest import ExternalHarvester, HarvestSource

    raw_sources = params.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        return _make_output(
            "S33_rea_harvest",
            str(params.get("trace_id") or _gen_trace_id("s33hv")),
            ok=False,
            result={},
            error="missing_sources",
        )
    sources = []
    for s in raw_sources:
        if not isinstance(s, dict) or not s.get("location"):
            continue
        sources.append(
            HarvestSource(
                source_type=str(s.get("source_type") or "local_path"),
                location=str(s["location"]),
                label=str(s.get("label") or ""),
                patterns=list(s.get("patterns") or []),
            )
        )
    pool = _reflection_pool(params)
    harvester = ExternalHarvester(pool)
    outcome = harvester.harvest(sources)
    return _make_output(
        "S33_rea_harvest",
        str(params.get("trace_id") or _gen_trace_id("s33hv")),
        ok=True,
        result={
            "ok": outcome.ok,
            "injected_trees": outcome.injected_trees,
            "rejected": outcome.rejected,
            "errors": outcome.errors,
        },
    )


# ---------------------------------------------------------------------------
# 输出场景节点（SPEC-33-输出场景-意图系统.md §4/§5）
# ---------------------------------------------------------------------------
def S33_rea_spec_enhance(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_spec_enhance 节点：两段式 Spec 增强（Q1/Q2）。
    Params:
        spec_draft: Spec 草案文本（必填）
        pool_dir: 回放池目录（可选，默认 reflection_data/replay_pool）
        trace_id: 调用方传入的 trace_id（可选）
    """
    from core.reflection.output_scenarios import SpecEnhancer

    spec_draft = str(params.get("spec_draft") or "").strip()
    if not spec_draft:
        return _make_output(
            "S33_rea_spec_enhance",
            str(params.get("trace_id") or _gen_trace_id("s33se")),
            ok=False,
            result={},
            error="missing_spec_draft",
        )
    pool = _reflection_pool(params)
    enhancer = SpecEnhancer(pool)
    result = enhancer.enhance(spec_draft)
    return _make_output(
        "S33_rea_spec_enhance",
        str(params.get("trace_id") or _gen_trace_id("s33se")),
        ok=True,
        result=result,
    )


def S33_rea_optimal_path(params: Dict[str, Any]) -> Dict[str, Any]:
    """S33_rea_optimal_path 节点：双层延迟策略评估（Q3/Q4）。
    Params:
        completed_node: 已完成节点 {analyzer, acceptance{passed, confidence}}（必填）
        force_heavy: 显式触发重量层（可选）
        pool_dir: 回放池目录（可选）
        trace_id: 调用方传入的 trace_id（可选）
    """
    from core.reflection.output_scenarios import OptimalPathEvaluator

    completed_node = params.get("completed_node")
    if not isinstance(completed_node, dict) or not completed_node.get("analyzer"):
        return _make_output(
            "S33_rea_optimal_path",
            str(params.get("trace_id") or _gen_trace_id("s33op")),
            ok=False,
            result={},
            error="missing_completed_node",
        )
    pool = _reflection_pool(params)
    evaluator = OptimalPathEvaluator(pool)
    result = evaluator.evaluate(
        completed_node,
        task_context=params.get("task_context"),
        force_heavy=bool(params.get("force_heavy")),
    )
    return _make_output(
        "S33_rea_optimal_path",
        str(params.get("trace_id") or _gen_trace_id("s33op")),
        ok=True,
        result=result,
    )


def _snapshot_section_items(payload: Dict[str, Any], section: str) -> list[Any]:
    raw = payload.get("raw") or {}
    graph = raw.get("graph") or {}
    if section == "modules":
        items: Any = raw.get("modules") or graph.get("nodes") or []
    elif section == "dependencies":
        deps = raw.get("dependencies")
        if deps is None:
            deps = graph.get("adjacency") or {}
        items = (
            [{"source": k, "targets": v} for k, v in sorted(deps.items())]
            if isinstance(deps, dict)
            else deps
        )
    elif section == "cycles":
        items = raw.get("cycles") or graph.get("cycles") or []
    elif section == "call_graph":
        call_graph = raw.get("call_graph") or {}
        callees = call_graph.get("callees") if isinstance(call_graph, dict) else None
        source = callees if isinstance(callees, dict) else call_graph
        items = (
            [{"module": k, "callees": v} for k, v in sorted(source.items())]
            if isinstance(source, dict)
            else source
        )
    elif section == "evidence":
        items = payload.get("evidence") or []
    else:
        items = raw.get(section) or []
    if isinstance(items, dict):
        items = [{"key": k, "value": v} for k, v in sorted(items.items())]
    return list(items) if isinstance(items, list) else [items]


def _snapshot_page_params(params: Dict[str, Any]) -> tuple[int, int]:
    try:
        cursor = max(0, int(params.get("cursor") or 0))
    except (TypeError, ValueError):
        cursor = 0
    try:
        limit = int(params.get("limit") or _SNAPSHOT_DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = _SNAPSHOT_DEFAULT_LIMIT
    return cursor, max(1, min(limit, _SNAPSHOT_PAGE_LIMIT))


def _snapshot_target(payload: Dict[str, Any]) -> str:
    """从快照 payload / Evidence provenance 中恢复 target（供 metrics/rules section 现场采集）。"""
    target = payload.get("target")
    if isinstance(target, str) and target.strip():
        return target
    for item in payload.get("evidence") or []:
        provenance = (item or {}).get("provenance") or {}
        candidate = provenance.get("target")
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return ""


def _find_rules_file(target: str) -> str | None:
    """在 target 及其父目录中查找 rea_rules.yaml。"""
    current = Path(target).resolve()
    if current.is_file():
        current = current.parent
    for base in (current, *current.parents):
        candidate = base / "rea_rules.yaml"
        if candidate.is_file():
            return str(candidate)
    return None


def _check_and_attach_constraints(target: str, analysis: Dict[str, Any]) -> None:
    """SPEC-F T-F06：rea_rules.yaml 存在时执行约束检查并附加违例 evidence。"""
    rules_path = _find_rules_file(target)
    if not rules_path:
        return
    from core.rules_engine import check_constraints, load_layers, load_rules

    layers = load_layers(rules_path)
    rules = load_rules(rules_path)
    if not layers or not rules:
        return

    raw = analysis.get("raw") or {}
    graph = raw.get("graph") or {}
    adjacency = graph.get("adjacency") or {}
    if not adjacency:
        return

    violations = check_constraints(adjacency, layers, rules)
    if not violations:
        return

    # 约束违例优先于普通观察证据，避免 summary 的 5 条裁剪把违例全部截掉。
    analysis["evidence"] = [v["evidence"] for v in violations] + list(
        analysis.get("evidence") or []
    )
    analysis.setdefault("known_gaps", []).append(
        f"架构约束检查发现 {len(violations)} 条违例（{rules_path}）"
    )


def get_rea_snapshot(params: Dict[str, Any]) -> Dict[str, Any]:
    """get_rea_snapshot 节点：按 section 分页读取 analyze 落盘的快照（SPEC §2.3）。

    Params:
        snapshot_id: 快照 ID（必填）
        section:     modules / dependencies / cycles / call_graph / components /
                     routes / api_routes / stores / god_components / external_deps /
                     patterns / evidence / metrics / rules / sarif / pack / archaeology /
                     dependency_hygiene / diagnostics / runtime / semantic（默认 modules）
        cursor:      起始偏移（默认 0；pack 为文件偏移）
        limit:       每页条数（默认 20，上限 200）
        budget_bytes: pack 的 Markdown 内容字节预算（默认 32768）
        metrics_config: 可选 metrics 阈值配置（JSON/YAML）路径
        metrics_history: 可选历史 metrics JSON 快照路径
        otel_path:   runtime 的可选 OpenTelemetry JSON/JSONL 报告路径
        query:       semantic 的检索语句（必填；复用 41 向量桥，缺通道时降级）
    """
    snapshot_id = str(params.get("snapshot_id") or "").strip()
    trace_id = str(params.get("trace_id") or _gen_trace_id("s33snap"))
    section = str(params.get("section") or "modules").strip()

    # SPEC-33-G §2.9：section=evolution 读无 AI 待办（含 diff 与回滚点），不需要 snapshot_id
    if section == "evolution":
        cursor, limit = _snapshot_page_params(params)
        actions = evolution_pending_actions(limit=None)
        total = len(actions)
        page = actions[cursor : cursor + limit]
        return _make_output(
            "S33_rea_snapshot",
            trace_id,
            ok=True,
            result={
                "snapshot_id": None,
                "section": "evolution",
                "items": page,
                "total": total,
                "next_cursor": cursor + limit if cursor + limit < total else None,
            },
        )

    if section not in _SNAPSHOT_SECTIONS and section not in _COMPUTED_SNAPSHOT_SECTIONS:
        return _make_output(
            "S33_rea_snapshot",
            trace_id,
            ok=False,
            result={},
            error="invalid_section",
        )

    if not snapshot_id:
        return _make_output(
            "S33_rea_snapshot",
            trace_id,
            ok=False,
            result={},
            error="missing_snapshot_id",
        )

    cursor, limit = _snapshot_page_params(params)

    path = _SNAPSHOT_DIR / f"{snapshot_id}.json"
    payload: Optional[Dict[str, Any]] = None
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            payload = loaded if isinstance(loaded, dict) else None
        except (OSError, json.JSONDecodeError):
            payload = None
    if payload is None:
        return _make_output(
            "S33_rea_snapshot",
            trace_id,
            ok=False,
            result={},
            error="snapshot_not_found",
        )

    if section in _COMPUTED_SNAPSHOT_SECTIONS:
        # SPEC-F §2.11：度量/规则是适配环产物，不落快照；按快照 target 现场采集并标 degraded
        target = str(params.get("target") or "").strip() or _snapshot_target(payload)
        if not target and section != "semantic":
            return _make_output(
                "S33_rea_snapshot",
                trace_id,
                ok=False,
                result={},
                error="missing_target_for_computed_section",
            )
        if section == "pack":
            from core.pack_builder import build_pack

            try:
                budget_bytes = int(params.get("budget_bytes") or _PACK_DEFAULT_BUDGET_BYTES)
            except (TypeError, ValueError):
                budget_bytes = _PACK_DEFAULT_BUDGET_BYTES
            packed = build_pack(payload, budget_bytes=budget_bytes, cursor=cursor)
            return _make_output(
                "S33_rea_snapshot",
                trace_id,
                ok=True,
                result={
                    "snapshot_id": snapshot_id,
                    **packed,
                    "total": packed["files_total"],
                },
            )
        if section == "sarif":
            from adapters.rules_adapter import scan_rules
            from adapters.sarif_adapter import build_sarif, write_sarif
            from adapters.taint_adapter import scan_taint

            rules_report = scan_rules(target)
            taint_report = (
                scan_taint(target)
                if _as_bool(params.get("include_taint", True))
                else {"findings": [], "known_gaps": []}
            )
            sarif_payload = dict(payload)
            sarif_payload["target"] = target
            sarif_payload["findings"] = list(rules_report.get("findings") or []) + list(
                taint_report.get("findings") or []
            )
            sarif_payload["known_gaps"] = (
                list(payload.get("known_gaps") or [])
                + list(rules_report.get("known_gaps") or [])
                + list(taint_report.get("known_gaps") or [])
            )
            sarif_report = build_sarif(sarif_payload, target=target)
            artifact = write_sarif(snapshot_id, sarif_payload, target=target)
            items = sarif_report["runs"][0]["results"]
            total = len(items)
            page = items[cursor : cursor + limit]
            requested_count = len(page)
            result = {
                "snapshot_id": snapshot_id,
                "section": section,
                "$schema": sarif_report["$schema"],
                "version": sarif_report["version"],
                "path": str(artifact),
                "items": page,
                "total": total,
                "next_cursor": cursor + len(page) if cursor + len(page) < total else None,
            }
            while _json_size(result) > _SARIF_SECTION_MAX_BYTES and page:
                page.pop()
                next_offset = cursor + (len(page) if page else min(1, requested_count))
                result["next_cursor"] = next_offset if next_offset < total else None
                result.pop("trimmed", None)
                _note_trimmed(result, "results", len(page), requested_count)
            return _make_output("S33_rea_snapshot", trace_id, ok=True, result=result)
        if section == "runtime":
            from adapters.runtime_adapter import scan_runtime

            report = scan_runtime(
                target,
                otel_path=params.get("otel_path"),
                static_nodes=_snapshot_section_items(payload, "modules"),
            )
            items = report.get("reconciled_nodes") or []
        elif section == "diagnostics":
            from adapters.lsp_adapter import scan_diagnostics

            report = scan_diagnostics(target)
            items = report.get("diagnostics") or []
        elif section == "dependency_hygiene":
            from adapters.dependency_hygiene_adapter import scan_dependency_hygiene

            report = scan_dependency_hygiene(target)
            items = report.get("unused_dependencies") or []
        elif section == "archaeology":
            from adapters.archaeology_adapter import scan_archaeology

            report = scan_archaeology(target)
            items = report.get("hotspots") or []
        elif section == "taint":
            from adapters.taint_adapter import scan_taint

            report = scan_taint(target)
            items = report.get("findings") or []
        elif section == "semantic":
            from adapters.semantic_adapter import search_semantic

            report = search_semantic(
                str(params.get("query") or ""), top_k=int(params.get("limit") or 10)
            )
            items = report.get("hits") or []
        elif section == "rules":
            from adapters.rules_adapter import scan_rules

            report = scan_rules(target)
            items = report.get("findings") or []
        else:
            from adapters.metrics_adapter import scan_metrics

            report = scan_metrics(
                target,
                config_path=params.get("metrics_config"),
                history_path=params.get("metrics_history"),
            )
            items = (report.get("complexity") or {}).get("top") or []
        cursor, limit = _snapshot_page_params(params)
        total = len(items)
        page = items[cursor : cursor + limit]
        result = {
            "snapshot_id": snapshot_id,
            "section": section,
            "items": page,
            "total": total,
            "next_cursor": cursor + limit if cursor + limit < total else None,
            "report": report,
        }
        if section == "runtime":
            optional_lists = (
                ("report.spans", report.get("spans") or []),
                ("report.coverage.files", report["coverage"].get("files") or []),
                ("report.reconciled_nodes", report.get("reconciled_nodes") or []),
                (
                    "report.zero_coverage_modules",
                    report.get("zero_coverage_modules") or [],
                ),
                ("report.known_gaps", report.get("known_gaps") or []),
                ("report.evidence", report.get("evidence") or []),
            )
            for label, values in optional_lists:
                original_count = len(values)
                while _json_size(result) > _RUNTIME_SECTION_MAX_BYTES and values:
                    values.pop()
                _note_trimmed(result, label, len(values), original_count)
            requested_count = len(page)
            while _json_size(result) > _RUNTIME_SECTION_MAX_BYTES and page:
                page.pop()
            if len(page) < requested_count:
                _note_trimmed(result, "items", len(page), total)
                next_offset = cursor + (len(page) if page else min(1, requested_count))
                result["next_cursor"] = next_offset if next_offset < total else None
        return _make_output("S33_rea_snapshot", trace_id, ok=True, result=result)

    if section == "graph":
        # SPEC-F T-F13：受限图查询 DSL（只读快照，不重新扫描）
        from core.graph_query import run_graph_query

        try:
            body = run_graph_query(
                payload, str(params.get("query") or "nodes"), cursor=cursor, limit=limit
            )
        except ValueError as exc:
            return _make_output(
                "S33_rea_snapshot",
                trace_id,
                ok=False,
                result={},
                error=f"invalid_query: {exc}",
            )
        return _make_output(
            "S33_rea_snapshot",
            trace_id,
            ok=True,
            result={"snapshot_id": snapshot_id, **body},
        )

    if section == "diagram":
        # SPEC-F T-F18：Mermaid 架构图 + 一页 wiki（内核零 LLM，只渲染结构事实）
        from core.diagram import build_diagram

        try:
            budget = int(params.get("budget_bytes") or _PACK_DEFAULT_BUDGET_BYTES)
        except (TypeError, ValueError):
            budget = _PACK_DEFAULT_BUDGET_BYTES
        body = build_diagram(payload, max_bytes=max(512, min(budget, 32768)))
        return _make_output(
            "S33_rea_snapshot",
            trace_id,
            ok=True,
            result={
                "snapshot_id": snapshot_id,
                "section": section,
                "mermaid": body["mermaid"],
                "wiki": body["wiki"],
                "stats": body["stats"],
                "known_gaps": body["known_gaps"],
                "items": [{"mermaid": body["mermaid"], "wiki": body["wiki"]}],
                "total": 1,
            },
        )

    items = _snapshot_section_items(payload, section)
    total = len(items)
    page = items[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < total else None
    return _make_output(
        "S33_rea_snapshot",
        trace_id,
        ok=True,
        result={
            "snapshot_id": snapshot_id,
            "section": section,
            "items": page,
            "total": total,
            "next_cursor": next_cursor,
        },
    )


# SPEC-33-G §2.9：analyze / trace / rea_audit 信封附 pending_actions[]（非空才加）
for _node_name in _PENDING_ENVELOPE_NODES:
    globals()[_node_name] = _with_pending_actions(globals()[_node_name])
del _node_name

# SPEC-33-F T-F17：analyze 可选增量索引（incremental=true）；只附加 diff，不改变分析结果
_ANALYZE_WITH_PENDING = S33_rea_analyze


def _analyze_with_incremental(params: Dict[str, Any]) -> Dict[str, Any]:
    output = _ANALYZE_WITH_PENDING(params)
    if not _as_bool(params.get("incremental")) or not output.get("ok"):
        return output
    index = S33_rea_incremental_index(
        {"target": params.get("target"), "index_path": params.get("index_path")}
    )
    if index.get("ok") and isinstance(output.get("result"), dict):
        output["result"]["incremental"] = index["result"]
    return output


S33_rea_analyze = _analyze_with_incremental


DSH_NODE_REGISTRY: Dict[str, Any] = {
    "s33_rea_analyze": S33_rea_analyze,
    "s33_rea_trace": S33_rea_trace,
    "s33_rea_compare": S33_rea_compare,
    "s33_rea_investigate": S33_rea_investigate,
    "s33_rea_recover_decisions": S33_rea_recover_decisions,
    "s33_rea_narrative": S33_rea_narrative,
    "s33_rea_audit": S33_rea_audit,
    "s33_rea_adapt_plan": S33_rea_adapt_plan,
    "s33_rea_score_sources": S33_rea_score_sources,
    "s33_rea_incremental_index": S33_rea_incremental_index,
    "s33_rea_cost_ledger": S33_rea_cost_ledger,
    "s33_rea_writeback": S33_rea_writeback,
    "s33_rea_locate": S33_rea_locate,  # C3（41 SPEC §13.3）：41 code 索引文件定位供给
    "s33_rea_reflect": S33_rea_reflect,
    "s33_rea_dream": S33_rea_dream,
    "s33_rea_replay": S33_rea_replay,
    "s33_rea_harvest": S33_rea_harvest,
    "s33_rea_spec_enhance": S33_rea_spec_enhance,
    "s33_rea_optimal_path": S33_rea_optimal_path,
    "get_rea_snapshot": get_rea_snapshot,
    "get_rea_methodology": get_rea_methodology,
}


def dispatch(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """DSH 调度入口：根据 method 路由到对应节点。

    用法（在 DSH server.py 主循环中）：
        if method.startswith("s33_"):
            result = dispatch(method, params)
    """
    fn = DSH_NODE_REGISTRY.get(method)
    if fn is None:
        return _make_output(
            "S33_unknown",
            str(params.get("trace_id") or _gen_trace_id()),
            ok=False,
            result={},
            error=f"unknown_method: {method}",
        )
    try:
        return fn(params)
    except Exception as e:
        return _make_output(
            "S33_error",
            str(params.get("trace_id") or _gen_trace_id()),
            ok=False,
            result={},
            error=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# 命令行自检（可选）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    print("=== S33_rea_analyze self-test ===")
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "test.py")).write_text(
            "import os\n\ndef main():\n    print('hello')\n\nif __name__ == '__main__':\n    main()\n"
        )
        r1 = S33_rea_analyze({"target": d, "scope": "architecture"})
        print(f"  ok={r1['ok']}, summary={r1['result'].get('summary', '')}")

    print("=== S33_rea_trace self-test ===")
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "test.py")).write_text(
            "def func_a():\n    return 1\n\ndef func_b():\n    return func_a()\n"
        )
        r2 = S33_rea_trace({"target": d, "feature": "测试功能", "entry": "func_b"})
        print(f"  ok={r2['ok']}, feature={r2['result'].get('feature', '')}")

    print("=== S33_rea_compare self-test ===")
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        Path(os.path.join(d1, "app.py")).write_text("import os\nprint('a')\n")
        Path(os.path.join(d2, "app.py")).write_text("import sys\nprint('b')\n")
        r3 = S33_rea_compare({"target_a": d1, "target_b": d2, "feature": "架构"})
        print(f"  ok={r3['ok']}")
