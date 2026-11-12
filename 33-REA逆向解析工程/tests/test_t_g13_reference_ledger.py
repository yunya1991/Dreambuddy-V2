"""T-G13 Reference 账本 + license/适配度免疫 + gap 去重 — RED 测试

SPEC-33-G §2.13：
  - 字段：ref_id/source/url/license/stack_fit/adapt_cost/capability/evidence/gap_id/usable
  - license=unknown 或 GPL 系进入闭源产品 → usable=false，只可参考思路
  - stack_fit < 0.4 → 只可参考思路，不得直接移植
  - 同一 gap_id 重复调研命中缓存，不重复消耗探索预算
  - 每条 Reference 必须附 how_verified，否则不算证据
  - §1 G-G12：每条 reference 含 license/stack_fit/adapt_cost；无 license 不得进入候选

RED 契约：core.evolution.reference_ledger 不存在。
"""

from __future__ import annotations

import pytest
from core.evolution.reference_ledger import ReferenceError, ReferenceLedger


def _ref(ref_id="R-001", **overrides):
    ref = {
        "ref_id": ref_id,
        "source": "github",
        "url": "https://github.com/example/ppr",
        "license": "MIT",
        "stack_fit": 0.8,
        "adapt_cost": "S",
        "capability": "PPR 相关性排序",
        "evidence": {"what": "用 PPR 做召回重排", "how_verified": "本地复现，recall@10 +6%"},
        "gap_id": "GAP-007",
    }
    ref.update(overrides)
    return ref


def _ledger(tmp_path, **kwargs):
    return ReferenceLedger(tmp_path / "reference", **kwargs)


# ---------------------------------------------------------------- 契约


def test_record_requires_contract_fields(tmp_path):
    ledger = _ledger(tmp_path)

    with pytest.raises(ReferenceError, match="ref_id"):
        ledger.record(_ref(ref_id=""))
    with pytest.raises(ReferenceError, match="source"):
        ledger.record(_ref(source="twitter"))
    with pytest.raises(ReferenceError, match="adapt_cost"):
        ledger.record(_ref(adapt_cost="XL"))
    with pytest.raises(ReferenceError, match="capability"):
        ledger.record(_ref(capability=""))
    with pytest.raises(ReferenceError, match="gap_id"):
        ledger.record(_ref(gap_id=""))


def test_valid_reference_is_usable_and_persisted(tmp_path):
    ledger = _ledger(tmp_path)
    record = ledger.record(_ref())

    assert record["usable"] is True
    assert record["blocked_reasons"] == []
    assert record["license"] == "MIT"
    assert (tmp_path / "reference" / "references.jsonl").is_file()

    reloaded = _ledger(tmp_path)
    assert reloaded.get("R-001")["usable"] is True
    assert len(reloaded.list()) == 1


def test_duplicate_ref_id_rejected(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record(_ref())
    with pytest.raises(ReferenceError, match="duplicate"):
        ledger.record(_ref())


# ---------------------------------------------------------------- 免疫


def test_unknown_license_is_never_a_candidate(tmp_path):
    ledger = _ledger(tmp_path)
    record = ledger.record(_ref(license="unknown"))
    assert record["usable"] is False
    assert "license_unknown" in record["blocked_reasons"]
    assert ledger.candidates() == []

    missing = ledger.record(_ref("R-002", license=""))
    assert missing["license"] == "unknown"
    assert missing["usable"] is False


def test_gpl_blocked_for_closed_source_but_allowed_when_open(tmp_path):
    closed = _ledger(tmp_path)
    blocked = closed.record(_ref(license="GPL-3.0"))
    assert blocked["usable"] is False
    assert "gpl_closed_source" in blocked["blocked_reasons"]

    open_ledger = _ledger(tmp_path / "open", closed_source=False)
    allowed = open_ledger.record(_ref(license="gpl-3.0"))
    assert allowed["license"] == "GPL-3.0"
    assert allowed["usable"] is True


def test_low_stack_fit_cannot_be_transplanted(tmp_path):
    ledger = _ledger(tmp_path)
    low = ledger.record(_ref(stack_fit=0.39))
    assert low["usable"] is False
    assert "low_stack_fit" in low["blocked_reasons"]

    boundary = ledger.record(_ref("R-002", stack_fit=0.4))
    assert boundary["usable"] is True


def test_missing_how_verified_is_not_evidence(tmp_path):
    ledger = _ledger(tmp_path)
    record = ledger.record(_ref(evidence={"what": "只有描述"}))
    assert record["usable"] is False
    assert "missing_how_verified" in record["blocked_reasons"]

    with pytest.raises(ReferenceError, match="evidence"):
        ledger.record(_ref("R-002", evidence="not-a-dict"))


def test_input_usable_is_ignored(tmp_path):
    ledger = _ledger(tmp_path)
    record = ledger.record(_ref(license="unknown", usable=True))
    assert record["usable"] is False


# ---------------------------------------------------------------- gap 去重


def test_gap_cache_hits_and_stops_duplicate_exploration(tmp_path):
    ledger = _ledger(tmp_path)
    assert ledger.should_explore("GAP-007") is True
    assert ledger.lookup_gap("GAP-007")["cached"] is False

    first = ledger.record(_ref("R-001", stack_fit=0.3))
    second = ledger.record(_ref("R-002", stack_fit=0.9))
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True

    assert ledger.should_explore("GAP-007") is False
    gap = ledger.lookup_gap("GAP-007")
    assert gap["cached"] is True
    assert gap["ref_ids"] == ["R-001", "R-002"]
    assert gap["usable_ref_ids"] == ["R-002"]


def test_candidates_sorted_by_stack_fit_and_filtered_by_gap(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record(_ref("R-001", stack_fit=0.5, gap_id="GAP-1"))
    ledger.record(_ref("R-002", stack_fit=0.9, gap_id="GAP-2"))
    ledger.record(_ref("R-003", stack_fit=0.7, gap_id="GAP-1"))
    ledger.record(_ref("R-004", stack_fit=0.99, license="unknown", gap_id="GAP-1"))

    all_candidates = ledger.candidates()
    assert [item["ref_id"] for item in all_candidates] == ["R-002", "R-003", "R-001"]

    gap_one = ledger.candidates(gap_id="GAP-1")
    assert [item["ref_id"] for item in gap_one] == ["R-003", "R-001"]
