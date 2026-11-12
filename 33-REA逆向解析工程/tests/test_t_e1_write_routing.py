"""SPEC-33-E T-E1 写入侧路由（RED）：流程日志落 `_process/`，不再污染 internal。

契约：
  - 经 `AnalysisRecorder` 记录时：task_type == "l1_loop" 或 analyzer ∈ PROCESS_ANALYZERS
    → `_process/`；普通架构分析 → internal/
  - 直接 `pool.save()`（seed/合成语料）不自动路由，避免做梦语料被搬走
  - external 仍 → external/
  - list_trees() 不返回 `_process/`；load(tree_id) 仍能找到（审计/回滚可用）
"""

from __future__ import annotations

from core.reflection.recorder import AnalysisRecorder
from core.reflection.replay_simulator import (
    PROCESS_ANALYZERS,
    DiscoveryNode,
    DiscoveryTree,
    ReplayPool,
    is_process_tree,
)


def _tree(tree_id: str, analyzers=(), task_type="analyze", provenance="internal") -> DiscoveryTree:
    tree = DiscoveryTree(
        tree_id=tree_id,
        task={"task_type": task_type},
        provenance=provenance,
        source_label="fixture",
    )
    parent = "root"
    for index, analyzer in enumerate(analyzers):
        node = DiscoveryNode(
            node_id=f"{tree_id}_n{index}",
            parent_id=parent,
            action={"analyzer": analyzer},
        )
        tree.nodes.append(node)
        parent = node.node_id
    return tree


def _record(pool_dir, task, analyzers):
    recorder = AnalysisRecorder(pool_dir=str(pool_dir))
    assert recorder.begin(task)
    for analyzer in analyzers:
        assert recorder.record(analyzer)
    return recorder.commit()


def test_is_process_tree_matches_task_type_and_analyzers():
    assert is_process_tree(_tree("a", task_type="l1_loop"))
    for analyzer in sorted(PROCESS_ANALYZERS):
        assert is_process_tree(_tree("b", analyzers=["ts_project_analyzer", analyzer]))
    assert not is_process_tree(_tree("c", analyzers=["ts_project_analyzer", "dependency_check"]))


def test_l1_loop_recorded_tree_goes_to_process(tmp_path):
    tree_id = _record(tmp_path, {"target": "t", "task_type": "l1_loop"}, ["ts_project_analyzer"])

    assert (tmp_path / "_process" / f"{tree_id}.json").exists()
    assert not (tmp_path / "internal" / f"{tree_id}.json").exists()


def test_flow_analyzer_recorded_tree_goes_to_process(tmp_path):
    tree_id = _record(tmp_path, {"target": "t", "task_type": "analyze"}, ["code_commit"])

    assert (tmp_path / "_process" / f"{tree_id}.json").exists()


def test_normal_analysis_recorded_tree_stays_internal(tmp_path):
    tree_id = _record(tmp_path, {"target": "t", "task_type": "analyze"}, ["ts_project_analyzer"])

    assert (tmp_path / "internal" / f"{tree_id}.json").exists()


def test_direct_save_is_not_auto_routed(tmp_path):
    """seed/合成语料直接 save，不应被搬进 _process。"""
    pool = ReplayPool(str(tmp_path))
    path = pool.save(_tree("seed1", analyzers=["acceptance_gate"], task_type="acceptance"))

    assert "/internal/" in path


def test_external_tree_stays_external(tmp_path):
    pool = ReplayPool(str(tmp_path))
    path = pool.save(_tree("e1", analyzers=["ts_project_analyzer"], provenance="external"))

    assert "/external/" in path


def test_list_trees_excludes_process_but_load_finds_it(tmp_path):
    pool = ReplayPool(str(tmp_path))
    process_id = _record(tmp_path, {"target": "t", "task_type": "l1_loop"}, ["code_commit"])
    internal_id = _record(
        tmp_path, {"target": "t", "task_type": "analyze"}, ["ts_project_analyzer"]
    )

    assert [tree.tree_id for tree in pool.list_trees()] == [internal_id]
    assert pool.count() == 1
    loaded = pool.load(process_id)
    assert loaded is not None and loaded.layer == "process"
