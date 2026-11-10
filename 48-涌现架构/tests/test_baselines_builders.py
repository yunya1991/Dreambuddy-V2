"""build_d2_architecture_graph / build_d3_intent_events 的 TDD 测试。

合成小仓库 + 合成 sessions 目录验证：
  - 节点/边类型与闭合校验（0 悬挂边）
  - 确定性：同一输入两次构建 sha256 一致（除 generated_at 外）
  - D3 隐私约束：不复制 action detail 原文
  - D3 时序切分：train 全部早于 test
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

BASELINES = Path(__file__).resolve().parents[1] / "baselines"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


d2 = _load("build_d2_architecture_graph", BASELINES / "build_d2_architecture_graph.py")
d3 = _load("build_d3_intent_events", BASELINES / "build_d3_intent_events.py")


@pytest.fixture()
def mini_repo(tmp_path: Path) -> Path:
    """合成迷你仓库：两个 py 模块互相 import + 调用，两个 md 互相链接。"""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text(
        "import pkg.b\n\n\ndef helper():\n    return 1\n\n\ndef run():\n    return pkg.b.compute()\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg" / "b.py").write_text(
        "import os\n\n\ndef compute():\n    return os.getcwd()\n",
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "x.md").write_text("[y](y.md)\n", encoding="utf-8")
    (tmp_path / "docs" / "y.md").write_text("[x](x.md)\n", encoding="utf-8")
    return tmp_path


class TestBuildD2Graph:
    def test_nodes_edges_closed(self, mini_repo: Path):
        g = d2.build_graph(mini_repo, [])
        ids = {n["id"] for n in g["nodes"]}
        assert "pkg/a.py" in ids and "pkg/b.py" in ids
        assert "docs/x.md" in ids and "docs/y.md" in ids
        kinds = {(e["src"], e["dst"], e["kind"]) for e in g["edges"]}
        assert ("pkg/a.py", "pkg/b.py", "import") in kinds
        assert ("pkg/a.py", "pkg/b.py", "call") in kinds  # run() 调 compute
        assert ("docs/x.md", "docs/y.md", "doc_ref") in kinds
        assert ("docs/y.md", "docs/x.md", "doc_ref") in kinds
        # 未解析的 os → external 节点
        assert any(n["type"] == "external" and n["id"] == "external:os" for n in g["nodes"])
        assert ("pkg/b.py", "external:os", "import") in kinds
        # 闭合校验
        assert g["dangling_edges"] == []
        assert g["parse_errors"] == []

    def test_deterministic_sha(self, mini_repo: Path, tmp_path: Path):
        s1 = d2.run(mini_repo, tmp_path / "out1", [])
        s2 = d2.run(mini_repo, tmp_path / "out2", [])
        assert s1["sha256"] == s2["sha256"]
        assert s1["closed_check"] == "pass"
        # 产物三件套齐全
        for name in ("architecture_graph.json", "graph_summary.json", "manifest.json"):
            assert (tmp_path / "out1" / name).exists()

    def test_parse_error_fail_open(self, mini_repo: Path):
        (mini_repo / "pkg" / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        g = d2.build_graph(mini_repo, [])
        assert any(e["file"] == "pkg/bad.py" for e in g["parse_errors"])
        assert g["dangling_edges"] == []

    def test_scope_limit(self, mini_repo: Path):
        g = d2.build_graph(mini_repo, ["docs"])
        kinds = {e["kind"] for e in g["edges"]}
        assert kinds == {"doc_ref"}
        assert all(n["type"] == "markdown_doc" for n in g["nodes"])


@pytest.fixture()
def mini_sessions(tmp_path: Path) -> Path:
    sdir = tmp_path / "sessions"
    sdir.mkdir()
    for i, (sid, ts, tt) in enumerate(
        [
            ("CS-1", 1000.0, "configuration"),
            ("CS-2", 2000.0, "python-development"),
            ("CS-3", 3000.0, "configuration"),
            ("CS-4", 4000.0, "configuration"),
        ]
    ):
        d = sdir / sid
        d.mkdir()
        (d / "session.json").write_text(
            json.dumps(
                {
                    "id": sid,
                    "start_time": ts,
                    "end_time": ts + 100,
                    "status": "completed",
                    "task_type": tt,
                    "action_count": 2,
                    "recalled_memory_ids": ["VM-1"],
                    "recalled_processes": [{"skill_id": "brainstorming", "kind": "meta"}],
                    "files_touched": ["pkg/a.py"],
                    "task_type_history": (
                        [{"from": "configuration", "to": tt, "timestamp": ts + 50}]
                        if i == 1
                        else []
                    ),
                }
            ),
            encoding="utf-8",
        )
        (d / "action_chain.jsonl").write_text(
            json.dumps(
                {
                    "timestamp": ts,
                    "session_id": sid,
                    "action_type": "file_change",
                    "detail": "用户隐私原文不应外泄",
                    "file": "a.py",
                }
            )
            + "\n"
            + json.dumps({"timestamp": ts + 1, "session_id": sid, "action_type": "recall"})
            + "\n",
            encoding="utf-8",
        )
    # 一个空 session.json（应跳过）+ 一个坏 json（应计入 errors）
    (sdir / "CS-empty").mkdir()
    (sdir / "CS-empty" / "session.json").write_text("", encoding="utf-8")
    (sdir / "CS-bad").mkdir()
    (sdir / "CS-bad" / "session.json").write_text("{broken", encoding="utf-8")
    return sdir


class TestBuildD3IntentEvents:
    def test_events_fields_and_privacy(self, mini_sessions: Path):
        events, errors = d3.load_events(mini_sessions)
        assert len(events) == 4  # 空跳过，坏计入 errors
        assert len(errors) == 1
        e = events[0]
        assert e["session_id"] == "CS-1"
        assert e["intent_proxy"] == "configuration"
        # P0-2 直接意图标签
        assert e["intent_label"] == "configuration:stable:pkg"
        assert e["intent_stable"] is True
        assert e["intent_trajectory"] == ["configuration"]
        assert e["intent_signals"]["transition_count"] == 0
        assert e["intent_label_confidence"] == 1.0
        assert e["recalled_skills"] == ["brainstorming"]
        assert e["action_type_distribution"] == {"file_change": 1, "recall": 1}
        assert e["action_files"] == ["a.py"]
        # 隐私：detail 原文不得出现在任何输出字段
        assert "隐私" not in json.dumps(events, ensure_ascii=False)
        # correction_count 来自 task_type_history
        assert events[1]["correction_count"] == 1

    def test_intent_label_drifted_trajectory(self, mini_sessions: Path):
        events, _ = d3.load_events(mini_sessions)
        drifted = next(e for e in events if e["correction_count"] > 0)
        assert drifted["intent_stable"] is False
        assert "drifted-1" in drifted["intent_label"]
        assert len(drifted["intent_trajectory"]) >= 2
        assert drifted["intent_label_confidence"] < 1.0

    def test_temporal_split(self, mini_sessions: Path):
        events, _ = d3.load_events(mini_sessions)
        split = d3.split_events(events, 0.75)
        assert split["train_count"] == 3 and split["test_count"] == 1
        assert split["train_sessions"] == ["CS-1", "CS-2", "CS-3"]
        assert split["test_sessions"] == ["CS-4"]
        # 时序不打乱
        assert split["train_ts_range"][1] <= split["test_ts_range"][0]

    def test_run_outputs(self, mini_sessions: Path, tmp_path: Path):
        out = tmp_path / "out"
        summary = d3.run(mini_sessions, out, 0.75)
        assert summary["session_count"] == 4
        assert summary["task_type_distribution"]["configuration"] == 3
        for name in (
            "intent_events.jsonl",
            "intent_summary.json",
            "split_manifest.json",
            "manifest.json",
        ):
            assert (out / name).exists()
        # raw JSONL 不含 detail
        raw = (out / "intent_events.jsonl").read_text(encoding="utf-8")
        assert "detail" not in raw
        # manifest 有 sha256
        m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert len(m["artifacts"]["intent_events.jsonl"]["sha256"]) == 64
