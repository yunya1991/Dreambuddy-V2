"""SPEC-33-E T-E1 — replay_pool 三类分层 dry-run（RED/GREEN 守护）

契约：
  - classify：task_type=l1_loop 或 analyzer ∈ 流程集 → process_log；其余 → project_analysis
  - 解析失败 → parse_error（不迁移）
  - dry-run 只写清单、不移动文件；计数守恒；external 不动且统计 source_label 缺失
"""

from __future__ import annotations

import json

from scripts import migrate_replay_pool_layers as layer


def _tree(tmp_path, name, *, analyzers=(), task_type=None, source_label=None):
    tree = {
        "tree_id": name,
        "task": {"task_type": task_type} if task_type else {},
        "nodes": [{"action": {"analyzer": analyzer}} for analyzer in analyzers],
    }
    if source_label is not None:
        tree["source_label"] = source_label
    path = tmp_path / name
    path.write_text(json.dumps(tree), encoding="utf-8")
    return path


def test_classify_process_log_by_analyzer(tmp_path):
    path = _tree(tmp_path, "a.json", analyzers=["acceptance_gate"])
    assert layer.classify(path) == "process_log"


def test_classify_process_log_by_task_type(tmp_path):
    path = _tree(tmp_path, "b.json", analyzers=["ts_project_analyzer"], task_type="l1_loop")
    assert layer.classify(path) == "process_log"


def test_classify_project_analysis(tmp_path):
    path = _tree(tmp_path, "c.json", analyzers=["ts_project_analyzer"], task_type="analyze")
    assert layer.classify(path) == "project_analysis"


def test_classify_parse_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    assert layer.classify(path) == "parse_error"


def test_dry_run_writes_manifest_without_moving(tmp_path, monkeypatch):
    pool = tmp_path / "replay_pool"
    internal = pool / "internal"
    external = pool / "external"
    internal.mkdir(parents=True)
    external.mkdir()
    _tree(internal, "p1.json", analyzers=["code_commit"])
    _tree(internal, "p2.json", analyzers=["doc_sync"])
    _tree(internal, "k1.json", analyzers=["ts_project_analyzer"], task_type="analyze")
    _tree(internal, "k2.json", analyzers=["python_analyzer"], task_type="analyze")
    _tree(external, "e1.json", analyzers=["ts_project_analyzer"], source_label="lobehub")
    _tree(external, "e2.json", analyzers=["ts_project_analyzer"])

    monkeypatch.setattr(layer, "MIN_TREES_FOR_EVAL", 1)
    assert layer.dry_run(pool) == 0

    manifest = json.loads((pool / "_migration_manifest.json").read_text(encoding="utf-8"))
    assert manifest["stats"] == {"process_log": 2, "project_analysis": 2}
    assert manifest["external_case"] == {"total": 2, "missing_source_label": 1}
    assert sorted(manifest["process_log"]) == ["p1.json", "p2.json"]
    assert len(list(internal.glob("*.json"))) == 4
    assert not (pool / "_process").exists()
