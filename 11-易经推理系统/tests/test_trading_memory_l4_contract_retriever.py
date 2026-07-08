import importlib.util
from pathlib import Path


REPO_ROOT = Path("/Users/zhangjiangtao/WorkBuddy/dream-multiskill-v2")


def _load_module(rel_path: str):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_retrieve_memory_refs_for_stage_returns_empty_for_a1():
    mod = _load_module("workflows/trading-decision/orchestrator/memory_retriever.py")
    out = mod.retrieve_memory_refs_for_stage("A1", payload={"trace_id": "trace-test"})
    assert out == []


def test_retrieve_memory_refs_for_stage_is_non_blocking_without_index():
    mod = _load_module("workflows/trading-decision/orchestrator/memory_retriever.py")
    out = mod.retrieve_memory_refs_for_stage("A3", payload={"trace_id": "trace-test"}, topk=1)
    assert isinstance(out, list)
