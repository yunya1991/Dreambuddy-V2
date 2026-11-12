#!/usr/bin/env python3
"""把 D2 ArchitectureGraph 投影为「架构工程地图」（ArchMap/v1）。

契约：1-ARCHITECTURE/specs/ARCH_ENGINEERING_MAP_SPEC.md §3

输入：
  - 48-涌现架构/baselines/artifacts/d2_architecture_graph/architecture_graph.json
  - 48-涌现架构/baselines/arch_map_rules.yaml（唯一人工维护：层归属/能力 paths/phase 映射）

输出：
  - 3.1-FRONTEND/src/data/arch-map/arch-map.json（图，dev chunk 打包，不落 public/）
  - 3.1-FRONTEND/src/data/arch-map/cap-map.json（运行态 phase → cap 映射）

只读图 + 只写产物，不改 builder，不写数据库。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = Path(__file__).resolve().parent
DEFAULT_GRAPH = BASELINE_DIR / "artifacts" / "d2_architecture_graph" / "architecture_graph.json"
DEFAULT_RULES = BASELINE_DIR / "arch_map_rules.yaml"
DEFAULT_OUT = REPO_ROOT / "3.1-FRONTEND" / "src" / "data" / "arch-map"

EXTERNAL_CAP = "X.external"


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _graph_sha(payload: dict) -> str:
    """与 build_d2_architecture_graph.py 完全一致的口径（剔除 generated_at）。"""
    struct = {
        "schema": payload.get("schema", "ArchitectureGraph/v1"),
        "scopes": payload.get("scopes", ["<repo>"]),
        "nodes": payload["nodes"],
        "edges": payload["edges"],
    }
    blob = json.dumps(struct, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class CapMapper:
    def __init__(self, capabilities: list[dict]) -> None:
        # (prefix, cap_id) 按前缀长度降序，保证最长前缀优先
        pairs: list[tuple[str, str]] = []
        for cap in capabilities:
            for prefix in cap.get("paths") or []:
                pairs.append((str(prefix), str(cap["id"])))
        self._pairs = sorted(pairs, key=lambda p: (-len(p[0]), p[0]))
        self._declared = {str(c["id"]): c for c in capabilities}

    def map_node(self, node_id: str) -> str:
        if node_id.startswith("external:"):
            return EXTERNAL_CAP
        for prefix, cap_id in self._pairs:
            if node_id.startswith(prefix):
                return cap_id
        head = node_id.split("/", 1)[0]
        return f"X.other.{head}" if "/" in node_id else "X.other.root"


def _count_loc(path: Path) -> int:
    try:
        with path.open("rb") as fh:
            return fh.read().count(b"\n") + 1
    except OSError:
        return 0


def project(graph: dict, rules: dict, repo_root: Path, include_external: bool = True) -> dict:
    layers = rules.get("layers") or []
    capabilities = rules.get("capabilities") or []
    mapper = CapMapper(capabilities)

    stats: dict[str, dict] = {
        str(c["id"]): {
            "id": str(c["id"]),
            "label": str(c.get("label") or c["id"]),
            "layer": str(c.get("layer") or "X"),
            "files": 0,
            "loc": 0,
            "hit": False,
            "orphan": False,
            "owner_paths": list(c.get("paths") or []),
        }
        for c in capabilities
    }
    stats.setdefault(
        EXTERNAL_CAP,
        {
            "id": EXTERNAL_CAP,
            "label": "外部依赖",
            "layer": "X",
            "files": 0,
            "loc": 0,
            "hit": False,
            "orphan": False,
            "owner_paths": [],
        },
    )

    node_cap: dict[str, str] = {}
    unmapped: dict[str, int] = {}
    for node in graph["nodes"]:
        nid = node["id"]
        cap_id = mapper.map_node(nid)
        node_cap[nid] = cap_id
        if cap_id == EXTERNAL_CAP and not include_external:
            continue
        entry = stats.setdefault(
            cap_id,
            {
                "id": cap_id,
                "label": cap_id.split(".", 1)[-1],
                "layer": "X",
                "files": 0,
                "loc": 0,
                "hit": False,
                "orphan": False,
                "owner_paths": [],
            },
        )
        if node.get("type") == "external":
            entry["files"] += 1
            continue
        entry["files"] += 1
        entry["loc"] += _count_loc(repo_root / nid)
        if cap_id.startswith("X.other."):
            key = cap_id[len("X.other.") :]
            unmapped[key] = unmapped.get(key, 0) + 1

    edge_weights: dict[tuple[str, str, str], int] = {}
    for edge in graph["edges"]:
        src = node_cap.get(edge["src"])
        dst = node_cap.get(edge["dst"])
        if not src or not dst or src == dst:
            continue
        if not include_external and (src == EXTERNAL_CAP or dst == EXTERNAL_CAP):
            continue
        key = (src, dst, edge.get("kind") or "unknown")
        edge_weights[key] = edge_weights.get(key, 0) + 1

    for src, dst, _kind in edge_weights:
        for cap in (src, dst):
            if cap in stats:
                stats[cap]["hit"] = True

    for entry in stats.values():
        entry["orphan"] = entry["files"] > 0 and not entry["hit"]

    nodes = sorted(stats.values(), key=lambda n: (n["layer"], n["id"]))
    edges = [
        {"src": s, "dst": d, "kind": k, "weight": w}
        for (s, d, k), w in sorted(edge_weights.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    total_unmapped_files = sum(unmapped.values())

    return {
        "schema": "ArchMap/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "graph_sha256": _graph_sha(graph),
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
        },
        "layers": [
            {"id": str(layer["id"]), "label": str(layer.get("label") or layer["id"])}
            for layer in layers
        ],
        "nodes": nodes,
        "edges": edges,
        "unmapped": {
            "dirs": sorted(unmapped),
            "files": total_unmapped_files,
        },
    }


def build_cap_map(rules: dict) -> dict:
    caps = [str(c["id"]) for c in (rules.get("capabilities") or [])]
    return {
        "schema": "CapMap/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase_map": {str(k): list(v) for k, v in (rules.get("phase_map") or {}).items()},
        "layer_default": {str(k): list(v) for k, v in (rules.get("layer_default") or {}).items()},
        "cap_ids": caps + [EXTERNAL_CAP],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="投影 D2 ArchitectureGraph → ArchMap")
    ap.add_argument("--graph", default=str(DEFAULT_GRAPH), help="architecture_graph.json 路径")
    ap.add_argument("--rules", default=str(DEFAULT_RULES), help="arch_map_rules.yaml 路径")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="产物输出目录")
    ap.add_argument("--no-external", action="store_true", help="丢弃 external:* 节点与相关边")
    args = ap.parse_args(argv)

    graph_path = Path(args.graph)
    rules_path = Path(args.rules)
    out_dir = Path(args.out)

    if not graph_path.exists():
        print(f"[project] 缺少图产物：{graph_path}", file=sys.stderr)
        print(
            "[project] 先运行 python3 48-涌现架构/baselines/build_d2_architecture_graph.py",
            file=sys.stderr,
        )
        return 2

    graph = _load_json(graph_path)
    with rules_path.open(encoding="utf-8") as fh:
        rules = yaml.safe_load(fh) or {}

    cap_ids = [str(c["id"]) for c in (rules.get("capabilities") or [])]
    dup = sorted({c for c in cap_ids if cap_ids.count(c) > 1})
    if dup:
        print(f"[project] cap id 重复：{dup}", file=sys.stderr)
        return 2

    arch_map = project(graph, rules, REPO_ROOT, include_external=not args.no_external)
    cap_map = build_cap_map(rules)

    out_dir.mkdir(parents=True, exist_ok=True)
    arch_path = out_dir / "arch-map.json"
    cap_path = out_dir / "cap-map.json"
    arch_path.write_text(
        json.dumps(arch_map, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    cap_path.write_text(json.dumps(cap_map, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    arch_kb = arch_path.stat().st_size / 1024
    orphans = [n["id"] for n in arch_map["nodes"] if n["orphan"]]
    empty = [n["id"] for n in arch_map["nodes"] if n["files"] == 0]
    print(
        f"[project] nodes={len(arch_map['nodes'])} edges={len(arch_map['edges'])} "
        f"unmapped_dirs={len(arch_map['unmapped']['dirs'])} "
        f"unmapped_files={arch_map['unmapped']['files']} size={arch_kb:.1f}KB"
    )
    print(f"[project] orphan={len(orphans)} empty_caps={len(empty)}")
    if orphans:
        print(f"[project]   orphan: {', '.join(orphans[:12])}")
    if empty:
        print(f"[project]   empty : {', '.join(empty[:12])}")
    print(f"[project] -> {arch_path}")
    print(f"[project] -> {cap_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
