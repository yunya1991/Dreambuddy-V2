"""因素-数据序列映射测试 — SPEC-D1-MULTIDIM-STATE §7 P2。

目标：把 FACTOR_ONTOLOGY 的 60 细类映射到真实数据序列，判定可验证性。

可用性口径（预注册）：
  long  : 历史 ≥900 天 → L1 因素预测力可验证
  short : 30-899 天    → 仅 L2/L3 样本内可用
  none  : <30 天或无源 → unverifiable

验收判据（§7 P2）：
  ①≥20 细类有 L1 可验证序列 ②无数据细类如实标 unverifiable ③映射表冻结
"""

from data_center.processing.factor_extractor import FACTOR_ONTOLOGY
from data_center.processing.factor_series_map import (
    AVAILABILITY_RULES,
    SERIES_MAP,
    build_series_map,
    classify_availability,
)

# ── 映射表完整性 ─────────────────────────────────────────────


def test_map_covers_every_ontology_factor():
    """映射表必须与本体 60 细类一一对应，无遗漏、无多余。"""
    onto_ids = {f"{c}.{s}" for c, subs in FACTOR_ONTOLOGY.items() for s in subs}
    assert set(SERIES_MAP) == onto_ids, {
        "missing": onto_ids - set(SERIES_MAP),
        "extra": set(SERIES_MAP) - onto_ids,
    }


def test_every_entry_has_source_and_note():
    """每条映射必须有 source 与非空 note（说明口径，供预注册冻结）。"""
    for fid, m in SERIES_MAP.items():
        assert m.get("source"), fid
        assert m.get("note"), fid
        assert "series" in m, fid


def test_none_series_has_empty_series_key():
    """无数据源时必须显式 series=None，不得留空字符串。"""
    for fid, m in SERIES_MAP.items():
        if m["source"] == "none":
            assert m["series"] is None, fid


# ── 可用性判定 ──────────────────────────────────────────────


def test_availability_thresholds():
    """long ≥900 / short 30-899 / none <30。"""
    assert classify_availability(900) == "long"
    assert classify_availability(899) == "short"
    assert classify_availability(30) == "short"
    assert classify_availability(29) == "none"
    assert classify_availability(0) == "none"


def test_availability_rules_consistent():
    """规则常量自洽：long 下限 > short 下限。"""
    assert AVAILABILITY_RULES["long"] > AVAILABILITY_RULES["short"]


# ── 输出结构 ────────────────────────────────────────────────


def test_build_map_structure_without_data(tmp_path):
    """无数据文件时不抛，全部标 none，结构完整。"""
    out = build_series_map(
        mm_db=tmp_path / "missing.db",
        kline_db=tmp_path / "missing2.db",
        event_jsonl=tmp_path / "missing.jsonl",
    )
    assert out["total_factors"] == len(SERIES_MAP)
    assert out["l1_verifiable"] == 0
    assert set(out["counts"]) == {"long", "short", "none"}
    assert all("availability" in v for v in out["factors"].values())


def test_output_json_serializable(tmp_path):
    """输出可直接 json.dumps（无 Path/日期等不可序列化对象）。"""
    import json

    out = build_series_map(
        mm_db=tmp_path / "m.db",
        kline_db=tmp_path / "k.db",
        event_jsonl=tmp_path / "e.jsonl",
    )
    json.dumps(out, ensure_ascii=False)
