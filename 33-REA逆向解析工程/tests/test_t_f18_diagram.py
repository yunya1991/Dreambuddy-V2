"""SPEC-33-F T-F18：Mermaid 架构图 + 一页 wiki。

验收：
  - 同输入逐字节一致（确定性）；
  - 节点/边超限时裁剪并记 known_gaps；
  - wiki 超字节预算按行截断并标注；
  - 内核零 LLM：只渲染快照结构事实与 Evidence 摘要。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REA_ROOT = Path(__file__).resolve().parents[1]
if str(_REA_ROOT) not in sys.path:
    sys.path.insert(0, str(_REA_ROOT))

import dsh_nodes  # noqa: E402
from core.diagram import build_diagram, build_mermaid, build_wiki  # noqa: E402

PAYLOAD = {
    "target": "/repo/demo",
    "raw": {
        "modules": [
            {"name": "src/stores/cart.ts", "type": "store"},
            {"name": "src/api/cart.ts", "type": "api"},
            {"name": "src/api/client.ts", "type": "api"},
            {"name": "lib/util.ts", "type": "util"},
        ],
        "dependencies": {
            "src/stores/cart.ts": ["src/api/cart.ts"],
            "src/api/cart.ts": ["src/api/client.ts"],
            "lib/util.ts": [],
        },
        "cycles": [["a", "b", "a"]],
    },
    "evidence": [
        {
            "result": "477 节点 / 689 边",
            "level": "observation",
            "provenance": {"target": "/repo/demo"},
            "confidence": 0.9,
        }
    ],
    "known_gaps": ["未读取运行时数据"],
}


def test_mermaid_is_deterministic_and_grouped():
    first = build_mermaid(PAYLOAD)
    second = build_mermaid(PAYLOAD)
    assert first["mermaid"] == second["mermaid"]
    text = first["mermaid"]
    assert text.startswith("flowchart LR")
    assert "subgraph" in text
    assert "src" in text and "lib" in text
    assert "-->" in text
    assert first["stats"]["nodes"] == 4
    assert first["stats"]["edges"] == 2


def test_mermaid_trims_with_known_gaps():
    trimmed = build_mermaid(PAYLOAD, max_nodes=2)
    assert trimmed["stats"]["nodes"] <= 2
    assert any("节点超限" in gap for gap in trimmed["known_gaps"])


def test_wiki_contains_structure_facts():
    wiki = build_wiki(PAYLOAD)
    text = wiki["markdown"]
    assert "# /repo/demo 架构一页纸" in text
    assert "模块：4" in text
    assert "依赖边：2" in text
    assert "Evidence：1" in text
    assert "src/api/client.ts" in text  # 入度 Top5
    assert "未读取运行时数据" in text
    assert wiki["stats"]["truncated"] is False


def test_wiki_respects_byte_budget():
    wiki = build_wiki(PAYLOAD, max_bytes=180)
    assert wiki["stats"]["truncated"] is True
    assert len(wiki["markdown"].encode("utf-8")) <= 180
    assert any("字节预算" in gap for gap in wiki["known_gaps"])


def test_build_diagram_combines_outputs():
    body = build_diagram(PAYLOAD)
    assert body["mermaid"].startswith("flowchart LR")
    assert body["wiki"].startswith("# /repo/demo")
    assert "mermaid" in body["stats"] and "wiki" in body["stats"]


def test_snapshot_section_diagram(tmp_path, monkeypatch):
    snapshot_id = "snap-test-diagram"
    (tmp_path / f"{snapshot_id}.json").write_text(
        json.dumps(PAYLOAD, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(dsh_nodes, "_SNAPSHOT_DIR", tmp_path)

    out = dsh_nodes.get_rea_snapshot({"snapshot_id": snapshot_id, "section": "diagram"})
    assert out["ok"] is True
    result = out["result"]
    assert result["section"] == "diagram"
    assert result["mermaid"].startswith("flowchart LR")
    assert result["wiki"].startswith("# /repo/demo")
    assert result["total"] == 1
