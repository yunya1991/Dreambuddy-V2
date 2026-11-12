"""SPEC-33-F T-F02 trace v2 测试（RED）：PPR 排序 + 预算裁剪 + 确定性 + legacy 回滚。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from core.graph_rank import (  # noqa: E402
    bounded_hop_distances,
    personalized_pagerank,
    rank_neighborhood,
)


def _write(root: Path, rel: str, content: str = "export const x = 1;\n") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _make_ts_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tsconfig.json").write_text(
        '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}', encoding="utf-8"
    )
    _write(root, "src/lib/util.ts")
    _write(
        root,
        "src/lib/agent/distill-outbox.ts",
        'import { x } from "@/lib/util";\nexport const outbox = x;\n',
    )
    _write(
        root,
        "src/app/api/agent/chat/route.ts",
        'import { outbox } from "@/lib/agent/distill-outbox";\nexport const POST = outbox;\n',
    )
    _write(
        root,
        "src/components/AppShell.tsx",
        'import { POST } from "@/app/api/agent/chat/route";\nexport const Shell = POST;\n',
    )
    _write(root, "src/unrelated/noise.ts")
    return root


def _make_star_project(root: Path, leaves: int = 40) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tsconfig.json").write_text("{}", encoding="utf-8")
    imports = "\n".join(f'import {{ leaf_{i} }} from "./leaf_{i:02d}";' for i in range(leaves))
    _write(root, "src/nodes/hub.ts", imports + "\nexport const hub = 1;\n")
    for i in range(leaves):
        _write(root, f"src/nodes/leaf_{i:02d}.ts", f"export const leaf_{i} = {i};\n")
    return root


# ---------------------------------------------------------------------------
# 内核：确定性 PPR
# ---------------------------------------------------------------------------


def test_ppr_deterministic_and_normalized() -> None:
    adj = {"a": ["b"], "b": ["c"], "c": ["a"], "d": ["a"]}
    first = personalized_pagerank(adj, ["a"])
    second = personalized_pagerank(adj, ["a"])
    assert first == second
    assert abs(sum(first.values()) - 1.0) < 1e-6
    assert first["a"] > first["d"]


def test_rank_neighborhood_desc_and_hops() -> None:
    adj = {"hub": ["a", "b"], "a": ["hub"], "b": ["hub"], "far": ["a"], "farther": ["far"]}
    ranked = rank_neighborhood(adj, ["hub"], hops=1)
    mods = [item["module"] for item in ranked]
    assert set(mods) == {"hub", "a", "b"}
    scores = [item["score"] for item in ranked]
    assert scores == sorted(scores, reverse=True)
    dist = bounded_hop_distances(adj, ["hub"], hops=3)
    assert dist["farther"] == 3


# ---------------------------------------------------------------------------
# 节点：trace v2
# ---------------------------------------------------------------------------


def test_trace_v2_ranked_deterministic_and_budget(tmp_path: Path) -> None:
    import dsh_nodes

    root = _make_ts_project(tmp_path / "ts")
    params = {"target": str(root), "feature": "agent distill outbox", "trace_id": "t-fixed"}
    first = dsh_nodes.S33_rea_trace(params)
    second = dsh_nodes.S33_rea_trace(params)
    assert first["ok"] is True, first

    r1, r2 = first["result"], second["result"]
    assert r1["algorithm"] == "ppr_v2"
    assert json.dumps(r1, sort_keys=True, ensure_ascii=False) == json.dumps(
        r2, sort_keys=True, ensure_ascii=False
    )

    ranked = r1["ranked_nodes"]
    assert ranked
    scores = [item["score"] for item in ranked]
    assert scores == sorted(scores, reverse=True)
    top_modules = [item["module"] for item in ranked[:5]]
    assert "src/lib/agent/distill-outbox.ts" in top_modules
    assert len(json.dumps(first, ensure_ascii=False).encode("utf-8")) <= 8192

    ev = r1["evidence"][0]
    assert ev["provenance"]["algorithm"] == "ppr_v2"
    assert ev["provenance"]["damping"] == 0.85


def test_trace_v2_trims_on_small_budget(tmp_path: Path) -> None:
    import dsh_nodes

    root = _make_star_project(tmp_path / "star")
    out = dsh_nodes.S33_rea_trace(
        {
            "target": str(root),
            "feature": "hub leaf",
            "budget_bytes": 3000,
            "hops": 2,
            "trace_id": "t-star",
        }
    )
    assert out["ok"] is True, out
    result = out["result"]
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) <= 3000
    assert "trimmed" in result
    assert result["trimmed"]["ranked_nodes"]["kept"] < result["trimmed"]["ranked_nodes"]["total"]


def test_trace_legacy_switch(tmp_path: Path) -> None:
    import dsh_nodes

    root = _make_ts_project(tmp_path / "ts")
    out = dsh_nodes.S33_rea_trace(
        {"target": str(root), "feature": "agent distill outbox", "algorithm": "legacy"}
    )
    assert out["ok"] is True, out
    result = out["result"]
    assert result["algorithm"] == "legacy"
    assert "ranked_nodes" not in result
    assert result["call_chain"]["seeds"]
