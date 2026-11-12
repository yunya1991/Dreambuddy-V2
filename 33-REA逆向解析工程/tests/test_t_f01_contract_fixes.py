"""SPEC-33-F T-F01 契约修正测试（RED）。

覆盖 P-F01 / P-F02 / P-F03：
  - P-F01 Python analyze 同一响应内 summary 与 Evidence 口径一致（scope 显式标注）
  - P-F02 compare 增加 common_module_names（相对路径尾段名口径），保留 common.modules
  - P-F03 target_refs 支持目录前缀展开；目录命中写入 reasons 且 gate 不得 pass
"""

from __future__ import annotations

import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from core.hypothesis import audit_hypothesis, resolve_target_refs  # noqa: E402

_NODES = ["src/stores/index.ts", "src/stores/cartStore.ts", "src/app/page.tsx"]


# ---------------------------------------------------------------------------
# P-F01：Python analyze 双口径
# ---------------------------------------------------------------------------


def _make_py_project(tmp_path: Path) -> Path:
    root = tmp_path / "py-proj"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "app.py").write_text("import os\n\nfrom pkg import util\n", encoding="utf-8")
    (root / "pkg" / "util.py").write_text("import json\n", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text("import pytest\n", encoding="utf-8")
    return root


def test_pf01_evidence_scope_matches_summary(tmp_path: Path) -> None:
    import dsh_nodes

    root = _make_py_project(tmp_path)
    out = dsh_nodes.S33_rea_analyze({"target": str(root), "scope": "architecture", "force": True})
    assert out["ok"] is True, out
    result = out["result"]
    evidence = result["evidence"]

    # 1) 每一条依赖图证据都必须带 scope 标注（all_files / project_internal）
    scopes = {
        str((e.get("provenance") or {}).get("scope"))
        for e in evidence
        if (e.get("provenance") or {}).get("analysis") == "dependency_graph"
    }
    assert "project_internal" in scopes
    assert "all_files" in scopes

    # 2) project_internal 证据复述的模块/边数必须与 summary/stats 同一分母
    internal = next(
        e
        for e in evidence
        if (e.get("provenance") or {}).get("analysis") == "dependency_graph"
        and (e.get("provenance") or {}).get("scope") == "project_internal"
    )
    assert internal["provenance"]["modules"] == result["stats"]["modules"]
    assert internal["provenance"]["edges"] == result["stats"]["edges"]
    assert str(result["stats"]["modules"]) in str(internal["result"])
    assert str(result["stats"]["edges"]) in str(internal["result"])


# ---------------------------------------------------------------------------
# P-F02：compare 模块口径
# ---------------------------------------------------------------------------


def _make_ts_project(root: Path, files: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "tsconfig.json").write_text("{}", encoding="utf-8")
    for rel in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("export const x = 1;\n", encoding="utf-8")
    return root


def test_pf02_compare_module_names(tmp_path: Path) -> None:
    import dsh_nodes

    a = _make_ts_project(tmp_path / "a", ["src/a/cartStore.ts", "src/a/index.ts"])
    b = _make_ts_project(tmp_path / "b", ["src/b/cartStore.ts", "src/b/index.ts"])

    out = dsh_nodes.S33_rea_compare({"target_a": str(a), "target_b": str(b)})
    assert out["ok"] is True, out
    common = out["result"]["common"]

    # 完整路径口径保持：不同目录同名文件不算 common.modules
    assert common["modules"] == []
    # 新增尾段名口径：同名文件可被识别
    assert common["common_module_names"] == ["cartStore.ts", "index.ts"]


# ---------------------------------------------------------------------------
# P-F03：目录级 target_refs
# ---------------------------------------------------------------------------


def test_pf03_directory_ref_resolves() -> None:
    assert resolve_target_refs(["src/stores"], _NODES) == ["src/stores"]
    assert resolve_target_refs(["src/stores/"], _NODES) == ["src/stores/"]
    assert resolve_target_refs(["src/ghost"], _NODES) == []


def _hypothesis(**overrides):
    base = {
        "hypothesis_id": "H-dir",
        "claim": "store 层可合并",
        "target_refs": ["src/stores", "src/app/page.tsx"],
        "falsifier": "合并后若出现循环依赖或 RSC 边界报错，则假设为假",
        "cost": {"files_touched": 3},
    }
    base.update(overrides)
    return base


def test_pf03_directory_hit_never_pass() -> None:
    out = audit_hypothesis(_hypothesis(), _NODES)
    assert out["gate"] != "pass", out
    assert out["gate"] == "review", out
    assert out["level"] == "inference"
    assert out["unresolved_refs"] == []
    assert any("目录" in r for r in out["reasons"]), out["reasons"]


def test_pf03_exact_refs_still_pass() -> None:
    out = audit_hypothesis(
        _hypothesis(target_refs=["src/stores/index.ts", "src/app/page.tsx"]), _NODES
    )
    assert out["gate"] == "pass", out
    assert out["level"] == "derivation"
