#!/usr/bin/env python3
"""架构工程地图复盘 / 漂移检测（M2）。

契约：1-ARCHITECTURE/specs/ARCH_ENGINEERING_MAP_SPEC.md §3.5、§5、§6

用法：
  python3 48-涌现架构/baselines/arch_map_review.py --run-id ARCH-20261112-01
  python3 48-涌现架构/baselines/arch_map_review.py --run-id demo --runtime runtime.json --fail-on-drift

产出：
  .arch-map/history/<ts>_<run_id>.json
  .arch-map/history/<ts>_<run_id>.md
  .arch-map/history/index.json（快照顺序，不入库）

四类信号：
  topology_delta — 能力增删 / 边数变化
  orphan         — 有文件但无任何边
  never_lit      — 本轮运行态从未点亮的能力（需 --runtime）
  ghost          — 运行态出现图中不存在的 cap（规则表过期）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = Path(__file__).resolve().parent
DEFAULT_ARCH_MAP = REPO_ROOT / "3.1-FRONTEND" / "src" / "data" / "arch-map" / "arch-map.json"
DEFAULT_HISTORY = REPO_ROOT / ".arch-map" / "history"

NODE_DRIFT_PCT = 5.0
EDGE_DRIFT_PCT = 10.0
NEVER_LIT_WARN_RATIO = 0.5


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _degree(edges: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    indeg: dict[str, int] = {}
    outdeg: dict[str, int] = {}
    for e in edges:
        outdeg[e["src"]] = outdeg.get(e["src"], 0) + 1
        indeg[e["dst"]] = indeg.get(e["dst"], 0) + 1
    return indeg, outdeg


def build_snapshot(arch_map: dict, run_id: str) -> dict:
    indeg, outdeg = _degree(arch_map["edges"])
    cap_index = {
        n["id"]: {
            "label": n["label"],
            "layer": n["layer"],
            "files": n["files"],
            "in": indeg.get(n["id"], 0),
            "out": outdeg.get(n["id"], 0),
            "orphan": n["orphan"],
        }
        for n in arch_map["nodes"]
    }
    return {
        "schema": "ArchMapSnapshot/v1",
        "run_id": run_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "graph_sha256": arch_map["source"]["graph_sha256"],
        "nodes": len(arch_map["nodes"]),
        "edges": len(arch_map["edges"]),
        "file_nodes": arch_map["source"]["node_count"],
        "orphans": [n["id"] for n in arch_map["nodes"] if n["orphan"]],
        "unmapped": arch_map["unmapped"],
        "cap_index": cap_index,
        "runtime": {"source": "none", "hits": {}, "failed": {}},
    }


def attach_runtime(snapshot: dict, runtime: dict) -> None:
    caps = runtime.get("caps") or {}
    snapshot["runtime"] = {
        "source": runtime.get("since") or runtime.get("exported_at") or "export",
        "hits": {
            cap: int(v.get("hits") or 0) for cap, v in caps.items() if int(v.get("hits") or 0) > 0
        },
        "failed": {
            cap: int(v.get("failed") or 0)
            for cap, v in caps.items()
            if int(v.get("failed") or 0) > 0
        },
        "ghosts": runtime.get("ghosts") or {},
    }


def _pct_delta(cur: int, base: int) -> float:
    if base <= 0:
        return 0.0 if cur <= 0 else 100.0
    return (cur - base) / base * 100.0


def analyze(snapshot: dict, base: dict | None) -> dict:
    cur_caps = snapshot["cap_index"]
    signals: dict = {
        "topology_delta": {},
        "orphan": snapshot["orphans"],
        "never_lit": [],
        "ghost": [],
    }
    reasons: list[str] = []
    warnings: list[str] = []

    if base:
        base_caps = base.get("cap_index") or {}
        added = sorted(set(cur_caps) - set(base_caps))
        removed = sorted(set(base_caps) - set(cur_caps))
        node_pct = _pct_delta(snapshot["nodes"], int(base.get("nodes") or 0))
        edge_pct = _pct_delta(snapshot["edges"], int(base.get("edges") or 0))
        signals["topology_delta"] = {
            "base_run_id": base.get("run_id"),
            "added_caps": added,
            "removed_caps": removed,
            "node_delta_pct": round(node_pct, 2),
            "edge_delta_pct": round(edge_pct, 2),
        }
        if abs(node_pct) > NODE_DRIFT_PCT:
            reasons.append(f"能力数变化 {node_pct:+.1f}% (> {NODE_DRIFT_PCT}%)")
        if abs(edge_pct) > EDGE_DRIFT_PCT:
            reasons.append(f"聚合边变化 {edge_pct:+.1f}% (> {EDGE_DRIFT_PCT}%)")
        if removed:
            reasons.append(f"能力被删除：{', '.join(removed[:6])}")
    else:
        warnings.append("无基准快照（首次运行），topology_delta 跳过")

    runtime = snapshot.get("runtime") or {}
    hits = runtime.get("hits") or {}
    ghost_ids = set(runtime.get("ghosts") or {})
    ghost_ids |= {cap for cap in hits if cap not in cur_caps}
    if ghost_ids:
        signals["ghost"] = sorted(ghost_ids)
        reasons.append(f"ghost：运行态出现图中不存在的 cap {', '.join(sorted(ghost_ids)[:6])}")

    if hits:
        lit = set(hits)
        candidates = [
            cap
            for cap, v in cur_caps.items()
            if v["files"] > 0 and not cap.startswith("X.external")
        ]
        never_lit = sorted(cap for cap in candidates if cap not in lit)
        signals["never_lit"] = never_lit
        ratio = len(never_lit) / len(candidates) if candidates else 0.0
        if ratio > NEVER_LIT_WARN_RATIO:
            warnings.append(
                f"never_lit 覆盖 {ratio:.0%} 的已入图能力（> {NEVER_LIT_WARN_RATIO:.0%}），数据流覆盖不足或事件映射缺失"
            )
    else:
        warnings.append("未提供运行态（--runtime），never_lit / ghost 仅基于图内信息")

    if signals["orphan"]:
        warnings.append(f"存在 {len(signals['orphan'])} 个孤立能力（有文件无边）")

    return {
        "signals": signals,
        "drift": bool(reasons),
        "reasons": reasons,
        "warnings": warnings,
    }


def render_md(snapshot: dict, analysis: dict) -> str:
    s = analysis["signals"]
    td = s["topology_delta"]
    lines = [
        f"# 架构地图复盘 — {snapshot['run_id']}",
        "",
        f"- 时间：{snapshot['ts']}",
        f"- 能力 {snapshot['nodes']} / 聚合边 {snapshot['edges']} / 图中文件 {snapshot['file_nodes']}",
        f"- 结构 sha：`{snapshot['graph_sha256'][:16]}`",
        f"- 漂移结论：{'**DRIFT**' if analysis['drift'] else 'PASS'}",
        "",
        "## 1. topology_delta",
        "",
    ]
    if td:
        lines += [
            f"- 基准：{td['base_run_id']}",
            f"- 能力增删：+{len(td['added_caps'])} / -{len(td['removed_caps'])}（{td['node_delta_pct']:+.1f}%）",
            f"- 聚合边变化：{td['edge_delta_pct']:+.1f}%",
        ]
        if td["added_caps"]:
            lines.append(f"- 新增：{', '.join(td['added_caps'])}")
        if td["removed_caps"]:
            lines.append(f"- 删除：{', '.join(td['removed_caps'])}")
    else:
        lines.append("- 无基准快照，跳过")
    lines += ["", "## 2. orphan（有文件但无任何边）", ""]
    lines.append("- " + (", ".join(s["orphan"]) if s["orphan"] else "无"))
    lines += ["", "## 3. never_lit（本轮未点亮）", ""]
    lines.append("- " + (", ".join(s["never_lit"]) if s["never_lit"] else "无 / 未提供运行态"))
    lines += ["", "## 4. ghost（运行态存在但图中无）", ""]
    lines.append("- " + (", ".join(s["ghost"]) if s["ghost"] else "无"))
    lines += ["", "## 结论", ""]
    if analysis["reasons"]:
        lines += [f"- DRIFT: {r}" for r in analysis["reasons"]]
    else:
        lines.append("- 未触发漂移判据")
    if analysis["warnings"]:
        lines += [f"- 提示: {w}" for w in analysis["warnings"]]
    lines.append("")
    return "\n".join(lines)


def _rebuild() -> int:
    for script in ("build_d2_architecture_graph.py", "project_arch_map.py"):
        path = BASELINE_DIR / script
        print(f"[review] rebuild: {script}")
        proc = subprocess.run([sys.executable, str(path)], cwd=REPO_ROOT)
        if proc.returncode != 0:
            return proc.returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="架构地图复盘 / 漂移检测")
    ap.add_argument("--run-id", required=True, help="本轮架构推进 ID")
    ap.add_argument("--arch-map", default=str(DEFAULT_ARCH_MAP))
    ap.add_argument("--base", default=None, help="基准快照 json（缺省取 history 最后一个）")
    ap.add_argument("--runtime", default=None, help="前端导出的运行态 json（ArchMapRuntime/v1）")
    ap.add_argument("--out", default=str(DEFAULT_HISTORY))
    ap.add_argument("--rebuild", action="store_true", help="先重生成 architecture_graph + arch-map")
    ap.add_argument("--fail-on-drift", action="store_true", help="检测到漂移时退出码 1")
    args = ap.parse_args(argv)

    if args.rebuild:
        code = _rebuild()
        if code != 0:
            print("[review] rebuild 失败", file=sys.stderr)
            return code

    arch_path = Path(args.arch_map)
    if not arch_path.exists():
        print(f"[review] 缺少 arch-map.json：{arch_path}", file=sys.stderr)
        return 2
    arch_map = _load_json(arch_path)
    snapshot = build_snapshot(arch_map, args.run_id)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.json"
    index = (
        _load_json(index_path)
        if index_path.exists()
        else {"schema": "ArchMapHistory/v1", "entries": []}
    )
    entries = [e for e in index.get("entries", []) if isinstance(e, dict)]

    base: dict | None = None
    if args.base:
        base = _load_json(Path(args.base))
    elif entries:
        base = _load_json(out_dir / entries[-1]["file"])

    if args.runtime:
        attach_runtime(snapshot, _load_json(Path(args.runtime)))

    analysis = analyze(snapshot, base)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{ts}_{args.run_id}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    payload = {**snapshot, "analysis": analysis}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md_path.write_text(render_md(snapshot, analysis), encoding="utf-8")

    entries.append(
        {
            "file": f"{stem}.json",
            "run_id": args.run_id,
            "ts": snapshot["ts"],
            "nodes": snapshot["nodes"],
            "edges": snapshot["edges"],
            "drift": analysis["drift"],
        }
    )
    index = {"schema": "ArchMapHistory/v1", "entries": entries}
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(
        f"[review] nodes={snapshot['nodes']} edges={snapshot['edges']} "
        f"orphan={len(analysis['signals']['orphan'])} "
        f"never_lit={len(analysis['signals']['never_lit'])} "
        f"ghost={len(analysis['signals']['ghost'])} drift={analysis['drift']}"
    )
    for reason in analysis["reasons"]:
        print(f"[review]   DRIFT: {reason}")
    for warning in analysis["warnings"]:
        print(f"[review]   WARN : {warning}")
    print(f"[review] -> {json_path}")
    print(f"[review] -> {md_path}")

    if args.fail_on_drift and analysis["drift"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
