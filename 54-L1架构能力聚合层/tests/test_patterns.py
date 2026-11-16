# -*- coding: utf-8 -*-
"""归纳层单测（TASKS-20261116 T4-1 / T4-2 / T4-3）。"""

from __future__ import annotations

import json
import os
import sys

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.patterns import (  # noqa: E402
    PATTERN_KEYS,
    _bh,
    _binom_two_sided,
    build_patterns,
    family_of,
    to_json,
    validate_document,
)

ROLES = {"B14": ["R1", "R4"], "R01": ["R2"], "SC62": ["R4"]}


def _finding(
    index: int, rank_ic: float, *, transform="ts_rank60", horizon=5, method="B14", p_adj=0.01
):
    return {
        "eval_id": f"EV-{index:04d}",
        "method": method,
        "transform": transform,
        "horizon": horizon,
        "rank_ic": rank_ic,
        "p_adj": p_adj,
    }


def test_family_mapping():
    assert family_of("ts_rank60") == "mom"
    assert family_of("zscore60") == "mom"
    assert family_of("pct") == "chg"
    assert family_of("quintile5") == "bucket"
    assert family_of("unknown_x") == "other"


def test_binomial_and_bh():
    assert _binom_two_sided(3, 3) == 0.25
    assert _binom_two_sided(0, 0) == 1.0
    adjusted = _bh([0.01, 0.04])
    assert adjusted[0] <= adjusted[1]
    assert all(0.0 <= value <= 1.0 for value in adjusted)


def test_pattern_groups_by_relation_family_horizon():
    findings = [
        _finding(1, 0.20),
        _finding(2, 0.18),
        _finding(3, 0.15),
        _finding(4, -0.12),
    ]
    document = build_patterns(findings, ROLES)
    ids = {pattern["pattern_id"] for pattern in document["patterns"]}
    # 默认 primary_only=True：B14 只归主类 R1，R4 不重复消费同一证据
    assert "PAT-R1-mom-h5" in ids
    assert "PAT-R4-mom-h5" not in ids
    assert document["params"]["primary_only"] is True
    r1 = next(item for item in document["patterns"] if item["pattern_id"] == "PAT-R1-mom-h5")
    assert r1["support"] == 3
    assert r1["oppose"] == 1
    assert r1["direction"] == 1
    assert r1["sign_agreement"] == 0.75
    assert r1["bimodal"] is False
    assert r1["status"] == "candidate"
    assert r1["members"] == ["EV-0001", "EV-0002", "EV-0003", "EV-0004"]


def test_primary_only_false_keeps_secondary_roles():
    findings = [_finding(index, 0.2) for index in range(1, 4)]
    document = build_patterns(findings, ROLES, primary_only=False)
    ids = {pattern["pattern_id"] for pattern in document["patterns"]}
    assert "PAT-R1-mom-h5" in ids
    assert "PAT-R4-mom-h5" in ids


def test_stable_requires_agreement_members_and_fdr():
    # n=10 全同向：二项双侧 p≈0.00195，满足 min_members=10 与 FDR
    findings = [_finding(index, 0.2) for index in range(1, 11)]
    document = build_patterns(findings, ROLES)
    pattern = next(item for item in document["patterns"] if item["pattern_id"] == "PAT-R1-mom-h5")
    assert pattern["significant_n"] == 10
    assert pattern["sign_agreement"] == 1.0
    assert pattern["bimodal"] is False
    assert pattern["status"] == "stable"
    assert pattern["p_adj"] >= pattern["p_value"]
    assert pattern["p_adj"] < 0.05


def test_min_members_ten_is_required_for_stable():
    # n=9 全同向 p≈0.0039 虽显著，但功效不足 min_members=10 → candidate
    findings = [_finding(index, 0.2) for index in range(1, 10)]
    document = build_patterns(findings, ROLES)
    pattern = document["patterns"][0]
    assert pattern["significant_n"] == 9
    assert pattern["p_adj"] < 0.05
    assert pattern["status"] == "candidate"


def test_bimodal_marks_split_regime():
    findings = [_finding(index, 0.2) for index in range(1, 7)] + [
        _finding(index, -0.2) for index in range(7, 11)
    ]
    document = build_patterns(findings, ROLES)
    pattern = document["patterns"][0]
    assert pattern["support"] == 6
    assert pattern["oppose"] == 4
    assert pattern["sign_agreement"] == 0.6
    assert pattern["bimodal"] is True
    assert pattern["status"] == "candidate"


def test_missing_eval_id_is_skipped():
    findings = [
        {"method": "B14", "transform": "ts_rank60", "horizon": 5, "rank_ic": 0.2, "p_adj": 0.01}
    ]
    document = build_patterns(findings, ROLES)
    assert document["patterns"] == []
    assert document["skipped"] == 1


def test_insignificant_and_unmapped_are_excluded():
    findings = [
        _finding(1, 0.2, p_adj=0.5),
        _finding(2, 0.2, method="ZZ99"),
    ]
    document = build_patterns(findings, ROLES)
    assert document["patterns"] == []
    assert document["unmapped"] == ["ZZ99"]
    assert document["skipped"] == 0


def test_schema_rejects_extra_natural_language_field():
    findings = [_finding(1, 0.2), _finding(2, 0.19), _finding(3, 0.18)]
    document = build_patterns(findings, ROLES)
    assert validate_document(document) == []

    broken = json.loads(json.dumps(document))
    broken["patterns"][0]["summary"] = "指标高位后大概率上涨"
    assert any("非法字段" in item for item in validate_document(broken))


def test_output_is_deterministic():
    findings = [_finding(index, 0.1 * (index % 3 - 1)) for index in range(1, 10)]
    first = to_json(build_patterns(findings, ROLES))
    second = to_json(build_patterns(list(reversed(findings)), ROLES))
    assert first == second
    assert set(json.loads(first)["patterns"][0]) == set(PATTERN_KEYS)


def _write_report(root, findings, patterns_doc=None):
    report_dir = os.path.join(root, "20261116-1200")
    os.makedirs(report_dir, exist_ok=True)
    with open(os.path.join(report_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"space_hash": "abc", "n_units": 42, "data_version": "d1"}, fh)
    with open(os.path.join(report_dir, "findings.jsonl"), "w", encoding="utf-8") as fh:
        for item in findings:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    if patterns_doc is not None:
        with open(os.path.join(report_dir, "patterns.json"), "w", encoding="utf-8") as fh:
            fh.write(to_json(patterns_doc))
    return report_dir


def test_discovery_query_exposes_patterns(tmp_path):
    from l1agg.capabilities.eval_exports import discovery_query

    findings = [_finding(index, 0.2) for index in range(1, 4)]
    document = build_patterns(findings, ROLES)
    _write_report(str(tmp_path), findings, document)

    envelope = discovery_query(reports_dir=str(tmp_path), top=5)
    block = envelope["data"]["capabilities"]["D-K02"]
    assert block["patterns"], "patterns 必须进入 D-K02 dataset"
    assert block["patterns"][0]["pattern_id"].startswith("PAT-")
    assert set(block["patterns"][0]) == set(PATTERN_KEYS)


def test_discovery_query_patterns_empty_without_file(tmp_path):
    from l1agg.capabilities.eval_exports import discovery_query

    findings = [_finding(1, 0.2)]
    _write_report(str(tmp_path), findings, None)
    envelope = discovery_query(reports_dir=str(tmp_path), top=5)
    assert envelope["data"]["capabilities"]["D-K02"]["patterns"] == []
