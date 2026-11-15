# -*- coding: utf-8 -*-
"""T1–T3 制品落盘（ADR-V12 / V-AC12 / L1S-04）单元测试。

锁定四件事：幂等字节一致、原子写无临时残留、路径安全、FAIL-OPEN 降级。
"""

import json
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.persistence import artifacts as art  # noqa: E402


def _visual(capability, visual_id, kind="series"):
    return {
        "id": visual_id,
        "kind": kind,
        "spec_version": "1.0",
        "title": f"{capability} 图",
        "source_capability": capability,
        "dataset": {"points": [{"x": "2026-11-12", "y": 1.5}]},
    }


def test_dumps_is_deterministic_and_key_sorted():
    left = art.dumps({"b": 1, "a": {"d": 2, "c": 3}})
    right = art.dumps({"a": {"c": 3, "d": 2}, "b": 1})
    assert left == right
    assert left.endswith(b"}\n")
    text = left.decode("utf-8")
    assert text.index('"a"') < text.index('"b"')
    assert text.index('"c"') < text.index('"d"')


def test_write_artifact_is_idempotent(tmp_path):
    payload = {"capability": "D-E15", "as_of": "2026-11-12", "visuals": []}
    first = art.write_artifact("D-E15", "2026-11-12", payload, root=str(tmp_path))
    assert first["written"] is True
    raw = open(first["path"], "rb").read()

    second = art.write_artifact("D-E15", "2026-11-12", payload, root=str(tmp_path))
    assert second["written"] is False
    assert second["sha256"] == first["sha256"]
    assert open(second["path"], "rb").read() == raw
    assert raw == art.dumps(payload)


def test_write_artifact_versions_by_as_of(tmp_path):
    art.write_artifact("D-E15", "2026-11-11", {"v": 1}, root=str(tmp_path))
    art.write_artifact("D-E15", "2026-11-12", {"v": 2}, root=str(tmp_path))
    folder = os.path.join(str(tmp_path), "D-E15")
    assert sorted(os.listdir(folder)) == ["2026-11-11.json", "2026-11-12.json"]
    assert art.list_artifacts(root=str(tmp_path)) == {"D-E15": ["2026-11-11", "2026-11-12"]}


def test_write_artifact_leaves_no_temp_file(tmp_path):
    art.write_artifact("D-E12", "2026-11-12", {"v": 1}, root=str(tmp_path))
    folder = os.path.join(str(tmp_path), "D-E12")
    assert [name for name in os.listdir(folder) if name.startswith(".tmp-")] == []


@pytest.mark.parametrize("bad", ["../escape", "", ".", "..", "a/b", "a b"])
def test_invalid_tokens_are_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        art.write_artifact(bad, "2026-11-12", {}, root=str(tmp_path))
    with pytest.raises(ValueError):
        art.write_artifact("D-E15", bad, {}, root=str(tmp_path))


def test_read_artifact_latest_and_missing(tmp_path):
    art.write_artifact("D-E15", "2026-11-11", {"v": 1}, root=str(tmp_path))
    art.write_artifact("D-E15", "2026-11-12", {"v": 2}, root=str(tmp_path))
    assert art.read_artifact("D-E15", root=str(tmp_path)) == {"v": 2}
    assert art.read_artifact("D-E15", "2026-11-11", root=str(tmp_path)) == {"v": 1}
    assert art.read_artifact("D-E15", "2026-01-01", root=str(tmp_path)) is None
    assert art.read_artifact("D-E99", root=str(tmp_path)) is None
    assert art.list_artifacts(root=os.path.join(str(tmp_path), "none")) == {}


def test_persist_visuals_groups_filters_and_sorts(tmp_path):
    visuals = [
        _visual("D-E15", "series:d-e15"),
        {"id": "tree", "kind": "tree", "spec_version": "1.0", "source_capability": "T3"},
        _visual("D-E15", "table:d-e15", kind="table"),
        {"id": "note", "kind": "note", "source_capability": "T3"},  # 非图种 → 跳过
        {"id": "no-cap", "kind": "series"},  # 无 source_capability → 跳过
    ]
    result = art.persist_visuals(visuals, "2026-11-12", root=str(tmp_path), extra={"base": "BTC"})
    assert sorted(result["written"]) == ["D-E15", "T3"]
    assert result["unchanged"] == [] and result["errors"] == {}

    payload = json.loads(
        open(os.path.join(str(tmp_path), "D-E15", "2026-11-12.json"), encoding="utf-8").read()
    )
    assert payload["capability"] == "D-E15"
    assert payload["as_of"] == "2026-11-12"
    assert payload["n_visuals"] == 2
    assert [row["id"] for row in payload["visuals"]] == ["series:d-e15", "table:d-e15"]
    assert payload["context"] == {"base": "BTC"}

    again = art.persist_visuals(visuals, "2026-11-12", root=str(tmp_path), extra={"base": "BTC"})
    assert again["written"] == [] and sorted(again["unchanged"]) == ["D-E15", "T3"]


def test_persist_visuals_skips_without_as_of_and_when_disabled(tmp_path, monkeypatch):
    skipped = art.persist_visuals([_visual("D-E15", "series:d-e15")], None, root=str(tmp_path))
    assert skipped["reason"] == "as_of_missing"
    assert art.list_artifacts(root=str(tmp_path)) == {}

    monkeypatch.setenv("L1_ARTIFACTS_ENABLED", "0")
    off = art.persist_visuals([_visual("D-E15", "series:d-e15")], "2026-11-12", root=str(tmp_path))
    assert off == {"enabled": False, "reason": "artifacts_disabled"}
    assert art.list_artifacts(root=str(tmp_path)) == {}


def test_persist_visuals_reports_errors_per_capability(tmp_path):
    result = art.persist_visuals(
        [_visual("D-E15", "series:d-e15"), _visual("bad cap", "series:x")],
        "2026-11-12",
        root=str(tmp_path),
    )
    assert result["written"] == ["D-E15"]
    assert "bad cap" in result["errors"]
    assert result["errors"]["bad cap"].startswith("ValueError")


def test_consume_latest_returns_capability_list(tmp_path):
    art.write_artifact("D-E15", "2026-11-11", {"n_visuals": 1}, root=str(tmp_path))
    art.write_artifact(
        "D-E15", "2026-11-12", {"n_visuals": 2, "spec_version": "1.0"}, root=str(tmp_path)
    )
    art.write_artifact("T3", "2026-11-10", {"n_visuals": 2}, root=str(tmp_path))

    view = art.consume_latest(root=str(tmp_path))
    assert view["ok"] is True
    assert view["capabilities"] == ["D-E15", "T3"]
    assert view["as_of"] == "2026-11-12"  # 全局最新
    assert [(i["capability"], i["as_of"]) for i in view["items"]] == [
        ("D-E15", "2026-11-12"),
        ("T3", "2026-11-10"),
    ]
    assert [i["n_visuals"] for i in view["items"]] == [2, 2]
    assert view["items"][0]["spec_version"] == "1.0"


def test_consume_latest_empty_and_single_capability(tmp_path):
    empty = art.consume_latest(root=str(tmp_path))
    assert empty == {"ok": True, "as_of": None, "capabilities": [], "items": []}

    art.write_artifact("D-E15", "2026-11-12", {"n_visuals": 1}, root=str(tmp_path))
    art.write_artifact("T3", "2026-11-11", {"n_visuals": 2}, root=str(tmp_path))
    one = art.consume_latest(root=str(tmp_path), capability="T3")
    assert one["capabilities"] == ["T3"] and one["as_of"] == "2026-11-11"
    assert art.consume_latest(root=str(tmp_path), capability="D-E99")["capabilities"] == []
