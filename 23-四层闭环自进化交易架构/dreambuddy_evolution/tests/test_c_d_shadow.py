#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-01：C→D 映射冻结 + shadow 对比（DEC-11 / R-23-02）。

验收口径（49-SPEC §13.6）：
- C_TO_D_MAP 冻结：C1→D2、C2→D4、C3→D3、C4→D1、C6→C6、C7→C7、C8→C8、news→NEWS
- shadow 开关 ENABLE_CD_SHADOW=1 时输出 D 标签 + C 别名，生产字段 dimension 不变
- shadow 观测落盘（C/D 分布可统计），默认关闭时不产生任何文件
"""

from __future__ import annotations

import json

import pytest


def _paths(confidence=0.8, source="bcrm"):
    """至少 2 路径（HC-AGI-23），主路径 source 决定 C 维度。"""
    return [
        {
            "path_id": "p1",
            "source": source,
            "direction": "long",
            "expected_return": 0.1,
            "confidence": confidence,
            "resistance": 0.2,
        },
        {
            "path_id": "p2",
            "source": "trend_following",
            "direction": "short",
            "expected_return": 0.05,
            "confidence": 0.3,
            "resistance": 0.4,
        },
    ]


# ── 1. 映射冻结 ──
def test_c_to_d_map_frozen():
    from dreambuddy_evolution.core.contradiction_identifier import C_TO_D_MAP

    assert C_TO_D_MAP == {
        "C1": "D2",
        "C2": "D4",
        "C3": "D3",
        "C4": "D1",
        "C6": "C6",
        "C7": "C7",
        "C8": "C8",
        "news": "NEWS",
        "NEWS": "NEWS",
    }


def test_c_to_d_helper_unknown_passthrough():
    from dreambuddy_evolution.core.contradiction_identifier import c_to_d

    assert c_to_d("C99") == "C99"
    assert c_to_d("") == ""


# ── 2. shadow 关闭：生产字段不变，无 D 标签、无文件 ──
def test_shadow_off_keeps_production_behavior(monkeypatch, tmp_path):
    monkeypatch.delenv("ENABLE_CD_SHADOW", raising=False)
    shadow_path = tmp_path / "cd_shadow.jsonl"
    monkeypatch.setenv("CD_SHADOW_PATH", str(shadow_path))

    from dreambuddy_evolution.core.contradiction_identifier import (
        PrimaryContradictionIdentifier,
    )

    result = PrimaryContradictionIdentifier().identify(_paths(), {}, {})
    assert result["dimension"] == "C3", "生产字段仍是 C 口径"
    assert "dimension_shadow" not in result
    assert not shadow_path.exists(), "开关关闭不得落盘 shadow"


# ── 3. shadow 开启：D 标签 + C 别名并存，dimension 不变 ──
def test_shadow_on_adds_d_label_and_alias(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_CD_SHADOW", "1")
    monkeypatch.setenv("CD_SHADOW_PATH", str(tmp_path / "cd_shadow.jsonl"))

    from dreambuddy_evolution.core.contradiction_identifier import (
        PrimaryContradictionIdentifier,
    )

    result = PrimaryContradictionIdentifier().identify(_paths(source="bcrm"), {}, {})
    assert result["dimension"] == "C3", "C 别名必须保留（兼容旧消费方）"
    assert result["dimension_shadow"]["d_dimension"] == "D3", "C3→D3"
    assert result["dimension_shadow"]["c_dimension"] == "C3"


@pytest.mark.parametrize(
    "source,c_dim,d_dim",
    [
        ("bdsm", "C1", "D2"),
        ("trend_following", "C2", "D4"),
        ("bcrm", "C3", "D3"),
        ("strategic", "C4", "D1"),
        ("deep_reasoning", "C6", "C6"),
        ("synthesized", "C7", "C7"),
        ("l2_gene", "C8", "C8"),
    ],
)
def test_shadow_mapping_all_sources(monkeypatch, tmp_path, source, c_dim, d_dim):
    monkeypatch.setenv("ENABLE_CD_SHADOW", "1")
    monkeypatch.setenv("CD_SHADOW_PATH", str(tmp_path / "cd_shadow.jsonl"))

    from dreambuddy_evolution.core.contradiction_identifier import (
        PrimaryContradictionIdentifier,
    )

    result = PrimaryContradictionIdentifier().identify(_paths(source=source), {}, {})
    assert result["dimension"] == c_dim
    assert result["dimension_shadow"]["d_dimension"] == d_dim


# ── 4. shadow 观测落盘：每次识别追加一条，含 C/D 与来源 ──
def test_shadow_writes_observation(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_CD_SHADOW", "1")
    shadow_path = tmp_path / "cd_shadow.jsonl"
    monkeypatch.setenv("CD_SHADOW_PATH", str(shadow_path))

    from dreambuddy_evolution.core.contradiction_identifier import (
        PrimaryContradictionIdentifier,
    )

    identifier = PrimaryContradictionIdentifier()
    identifier.identify(_paths(source="bcrm"), {}, {})
    identifier.identify(_paths(source="bdsm"), {}, {})

    lines = [json.loads(x) for x in shadow_path.read_text(encoding="utf-8").splitlines() if x]
    assert len(lines) == 2
    assert lines[0]["c_dimension"] == "C3" and lines[0]["d_dimension"] == "D3"
    assert lines[1]["c_dimension"] == "C1" and lines[1]["d_dimension"] == "D2"
    assert lines[0]["source"] == "bcrm"
    assert "ts" in lines[0]


# ── 5. 观测汇总：C/D 分布 + 映射一致率（≥2 周对比报告口径）──
def test_summarize_missing_file_is_unavailable(tmp_path):
    from dreambuddy_evolution.core.contradiction_identifier import summarize_cd_shadow

    summary = summarize_cd_shadow(str(tmp_path / "absent.jsonl"))
    assert summary["available"] is False
    assert summary["total"] == 0


def test_summarize_counts_and_consistency(tmp_path):
    from dreambuddy_evolution.core.contradiction_identifier import summarize_cd_shadow

    path = tmp_path / "cd_shadow.jsonl"
    rows = [
        {"c_dimension": "C3", "d_dimension": "D3", "source": "bcrm"},
        {"c_dimension": "C3", "d_dimension": "D3", "source": "bcrm"},
        {"c_dimension": "C1", "d_dimension": "D2", "source": "bdsm"},
    ]
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    summary = summarize_cd_shadow(str(path))
    assert summary["available"] is True
    assert summary["total"] == 3
    assert summary["c_distribution"] == {"C3": 2, "C1": 1}
    assert summary["d_distribution"] == {"D3": 2, "D2": 1}
    assert summary["mapping_consistency"] == 1.0


def test_summarize_reports_mapping_drift(tmp_path):
    """映射被改动/写脏时一致率下降（shadow 期间监控口径漂移）。"""
    from dreambuddy_evolution.core.contradiction_identifier import summarize_cd_shadow

    path = tmp_path / "cd_shadow.jsonl"
    rows = [
        {"c_dimension": "C3", "d_dimension": "D3", "source": "bcrm"},
        {"c_dimension": "C1", "d_dimension": "D1", "source": "bdsm"},  # 应为 D2
    ]
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    summary = summarize_cd_shadow(str(path))
    assert summary["total"] == 2
    assert summary["mapping_consistency"] == 0.5
