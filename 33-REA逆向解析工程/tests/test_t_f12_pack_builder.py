"""SPEC-33-F T-F12：确定性语料打包、字节预算与快照 section（RED）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

from core.pack_builder import build_pack  # noqa: E402


def _payload() -> dict:
    return {
        "target": "/repo",
        "language": "typescript",
        "summary": "不应进入 pack 的自然语言摘要",
        "raw": {
            "modules": ["src/z.ts", "src/a.ts"],
            "components": [{"file": "src/a.ts", "name": "App", "kind": "function", "line": 2}],
            "stores": [{"file": "src/z.ts", "name": "useCart", "library": "zustand"}],
            "graph": {
                "adjacency": {"src/a.ts": ["src/z.ts"], "src/z.ts": []},
            },
        },
    }


def test_pack_is_deterministic_and_orders_file_symbols_dependencies() -> None:
    first = build_pack(_payload(), budget_bytes=4096)
    second = build_pack(_payload(), budget_bytes=4096)

    assert first == second
    content = first["content"]
    assert content.index("## File: `src/a.ts`") < content.index("## File: `src/z.ts`")
    a_block = content.split("## File: `src/a.ts`", 1)[1].split("## File:", 1)[0]
    assert a_block.index("### Symbols") < a_block.index("### Dependencies")
    assert "App" in a_block and "src/z.ts" in a_block
    assert "useCart" in content
    assert "不应进入 pack" not in content
    assert first["files_total"] == 2
    assert first["files_included"] == 2
    assert first["next_cursor"] is None
    assert "trimmed" not in first


def test_pack_byte_budget_trims_and_cursor_resumes() -> None:
    payload = {
        "target": "/repo",
        "language": "typescript",
        "raw": {
            "modules": [f"src/very-long-module-name-{index}.ts" for index in range(8)],
            "graph": {"adjacency": {}},
        },
    }

    first = build_pack(payload, budget_bytes=240)

    assert len(first["content"].encode("utf-8")) == first["content_bytes"] <= 240
    assert first["trimmed"]["files"]["kept"] < first["trimmed"]["files"]["total"] == 8
    assert first["next_cursor"] is not None

    rest = build_pack(payload, budget_bytes=4096, cursor=first["next_cursor"])
    assert rest["files_included"] == 8 - first["files_included"]
    assert rest["next_cursor"] is None
    assert "trimmed" not in rest


def test_pack_tiny_budget_remains_valid_utf8() -> None:
    packed = build_pack(_payload(), budget_bytes=1)

    assert packed["content_bytes"] <= 1
    assert packed["content"].encode("utf-8") == packed["content"].encode("utf-8")
    assert packed["trimmed"]["files"]["total"] == 2


def test_snapshot_pack_section_uses_budget_and_cursor(tmp_path: Path, monkeypatch) -> None:
    import dsh_nodes

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", snapshot_dir)
    payload = _payload()
    payload["snapshot_id"] = "pack-fixture"
    (snapshot_dir / "pack-fixture.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    output = dsh_nodes.get_rea_snapshot(
        {"snapshot_id": "pack-fixture", "section": "pack", "budget_bytes": 120}
    )

    assert output["ok"] is True, output
    result = output["result"]
    assert result["section"] == "pack"
    assert result["snapshot_id"] == "pack-fixture"
    assert result["content_bytes"] <= 120
    assert result["total"] == 2
    assert result["trimmed"]["files"]["kept"] < 2
