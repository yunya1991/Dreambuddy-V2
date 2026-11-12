"""SPEC-33-E P0 契约测试：假设校验 + PoE 门禁 + 认知写入边界。

对应任务：T-E2（audit 判定）/ T-E4（RED 用例）
硬约束：不可证伪即 reject；无静态复核证据最高 review；reject 不写认知。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from core.hypothesis import (  # noqa: E402
    audit_hypotheses,
    audit_hypothesis,
    build_write_hint,
    resolve_target_refs,
    validate_hypothesis,
)

_NODES = ["src/stores/index.ts", "src/stores/cartStore.ts", "src/app/page.tsx"]


@pytest.fixture()
def ts_project(tmp_path: Path) -> Path:
    """最小 TS 工程：两个可被 target_refs 命中的模块。"""
    root = tmp_path / "ts-app"
    (root / "src" / "components").mkdir(parents=True)
    (root / "src" / "lib").mkdir(parents=True)
    (root / "tsconfig.json").write_text(
        '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}', encoding="utf-8"
    )
    (root / "package.json").write_text(
        '{"name":"t","dependencies":{"next":"14.0.0"}}', encoding="utf-8"
    )
    (root / "src" / "lib" / "util.ts").write_text(
        "export const fmt = (v: number) => String(v);\n", encoding="utf-8"
    )
    (root / "src" / "components" / "Button.tsx").write_text(
        'import { fmt } from "@/lib/util";\n\nexport const Button = () => fmt(1);\n',
        encoding="utf-8",
    )
    return root


def _hypothesis(**overrides):
    base = {
        "hypothesis_id": "H-001",
        "claim": "12 个 store 可合并为 5 个 slice",
        "target_refs": ["src/stores/index.ts", "src/stores/cartStore.ts"],
        "falsifier": "合并后若出现循环依赖或 RSC 边界报错，则假设为假",
        "cost": {"files_touched": 3},
    }
    base.update(overrides)
    return base


def test_missing_falsifier_rejected():
    errors = validate_hypothesis({"hypothesis_id": "H-x", "claim": "c", "target_refs": ["a"]})
    assert any("falsifier" in e for e in errors)
    out = audit_hypothesis({"hypothesis_id": "H-x", "claim": "c", "target_refs": ["a"]}, _NODES)
    assert out["gate"] == "reject"
    assert out["level"] == "unknown"


def test_vague_falsifier_rejected():
    out = audit_hypothesis(_hypothesis(falsifier="可能不对"), _NODES)
    assert out["gate"] == "reject"


def test_all_refs_resolved_pass_and_derivation():
    out = audit_hypothesis(_hypothesis(), _NODES)
    assert out["gate"] == "pass", out
    assert out["poe_score"] >= 0.8
    assert out["level"] == "derivation"
    assert out["unresolved_refs"] == []


def test_no_resolved_refs_capped_at_review():
    hyp = _hypothesis(target_refs=["src/ghost/a.ts", "src/ghost/b.ts"])
    out = audit_hypothesis(hyp, _NODES)
    assert out["gate"] == "review", out
    assert out["level"] != "derivation"
    assert any("封顶 review" in r for r in out["reasons"])


def test_partial_refs_never_pass():
    hyp = _hypothesis(target_refs=["src/stores/index.ts", "src/ghost/a.ts"])
    out = audit_hypothesis(hyp, _NODES)
    assert out["gate"] != "pass"
    assert "src/ghost/a.ts" in out["unresolved_refs"]


def test_suffix_and_dotted_ref_resolution():
    assert resolve_target_refs(["stores/cartStore.ts"], _NODES) == ["stores/cartStore.ts"]
    assert resolve_target_refs(["core.app"], ["pkg.core", "core.app"]) == ["core.app"]


def test_python_ext_ref_resolves_to_module_node():
    """Python 图节点是模块名，假设引用常带 .py：必须能归一命中。"""
    assert resolve_target_refs(["server.py"], ["server", "test_server"]) == ["server.py"]
    assert resolve_target_refs(["mcp_shells/l0_rea/server.py"], ["server", "other"]) == [
        "mcp_shells/l0_rea/server.py"
    ]
    assert resolve_target_refs(["ghost.py"], ["server"]) == []


def test_batch_and_write_hint_levels():
    results = audit_hypotheses(
        [
            _hypothesis(hypothesis_id="H-pass"),
            _hypothesis(
                hypothesis_id="H-review",
                target_refs=["src/stores/index.ts", "src/stores/cartStore.ts", "src/ghost/x.ts"],
            ),
            _hypothesis(hypothesis_id="H-reject", falsifier=""),
        ],
        _NODES,
    )
    hint = build_write_hint(results, target="3.1-FRONTEND")
    by_level = {w["hypothesis_id"]: w["quality_level"] for w in hint["write"]}
    skipped = {s["hypothesis_id"] for s in hint["skip"]}
    assert by_level.get("H-pass") == "B"
    assert by_level.get("H-review") == "C"
    assert "H-reject" in skipped
    assert "H-reject" not in by_level


# ---------------------------------------------------------------------------
# 节点级：S33_rea_audit（假设模式）/ get_rea_methodology
# ---------------------------------------------------------------------------


def test_audit_node_hypothesis_mode(ts_project: Path) -> None:
    import dsh_nodes

    out = dsh_nodes.S33_rea_audit(
        {
            "target": str(ts_project),
            "hypotheses": [
                _hypothesis(
                    target_refs=["src/components/Button.tsx", "src/lib/util.ts"],
                    cost={"files_touched": 2},
                )
            ],
        }
    )
    assert out["ok"] is True, out
    result = out["result"]
    assert result["mode"] == "hypothesis"
    assert result["language"] == "typescript"
    assert result["stats"]["hypotheses"] == 1
    assert result["hypotheses"][0]["gate"] in ("pass", "review")
    assert result["cognitive_hint"]["write"]


def test_methodology_node_empty_failopen() -> None:
    import dsh_nodes

    out = dsh_nodes.get_rea_methodology({})
    assert out["ok"] is True
    assert out["result"]["methodologies"] == []
    assert out["result"]["known_gaps"]


def test_methodology_node_needs_two_projects() -> None:
    import dsh_nodes

    evidence = {
        "result": "检测到 App Router 文件路由",
        "level": "derivation",
        "provenance": {"files": ["src/app/page.tsx"]},
        "confidence": 0.9,
        "known_gaps": [],
    }
    one = dsh_nodes.get_rea_methodology(
        {
            "investigations": [
                {"target": "proj-a", "patterns": [{"pattern": "app_router", "evidence": evidence}]}
            ]
        }
    )
    two = dsh_nodes.get_rea_methodology(
        {
            "investigations": [
                {"target": "proj-a", "patterns": [{"pattern": "app_router", "evidence": evidence}]},
                {"target": "proj-b", "patterns": [{"pattern": "app_router", "evidence": evidence}]},
            ]
        }
    )
    assert one["result"]["methodologies"] == []
    assert len(two["result"]["methodologies"]) == 1
    assert set(two["result"]["methodologies"][0]["source_projects"]) == {"proj-a", "proj-b"}
