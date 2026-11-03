#!/usr/bin/env python3
"""test_agent_mail_shadow.py — COMM-SHADOW Phase 0 验收

覆盖：静态域传播 JSON schema / observe() 消费 / L1 一致性比对 /
S1-S3 硬约束（不触发、shadow- trace、仅本地落盘）/ FAIL-OPEN 降级。
"""

from __future__ import annotations

import itertools
import json
import re
from datetime import datetime

import pytest

from mcp_shells._shared.agent_mail_shadow import (
    DEFAULT_STORE_PATH,
    SHADOW_PREFIX,
    STATIC_TRANSMISSION_PATH,
    AgentMailShadow,
)

DOMAINS = ["cognition", "rea", "search", "semantic", "data", "eval"]
LAYER_NAMES = {"L1_anchor", "L2_active", "L3_sensitive"}


# ---------- 静态 JSON schema（SPEC §2 必填字段与取值域） ----------
@pytest.fixture(scope="module")
def static_transmission() -> dict:
    return json.loads(STATIC_TRANSMISSION_PATH.read_text(encoding="utf-8"))


def test_static_transmission_required_fields(static_transmission):
    for key in (
        "domain_layers",
        "domain_transmission",
        "domain_breadth",
        "generated_at",
        "model_version",
        "trace_id",
    ):
        assert key in static_transmission, f"缺必填字段 {key}"

    layers = static_transmission["domain_layers"]
    assert set(layers) == LAYER_NAMES
    assert set(itertools.chain.from_iterable(layers.values())) == set(DOMAINS)

    block = static_transmission["domain_transmission"]
    assert block["state"] in {"neutral", "elevated", "extreme", "recovering"}
    assert block["regime"] in {"bull", "bear", "range", "transition"}

    breadth = static_transmission["domain_breadth"]
    assert 0.0 <= float(breadth["breadth_pct"]) <= 100.0
    assert breadth["state"] in {"strong", "normal", "weak"}
    assert set(breadth["layer_breadth"]) == LAYER_NAMES


def test_static_transmission_identifier_patterns(static_transmission):
    assert re.match(r"^l1-domain-coupling-v\d+\.\d+$", static_transmission["model_version"])
    # Phase A: l1-infer-32hex; Phase B Head 推理: l1-head-infer-16hex
    assert re.match(
        r"^l1-(infer|head-infer)-[a-f0-9]+$", static_transmission["trace_id"]
    ), f"trace_id={static_transmission['trace_id']} 格式非法"
    datetime.fromisoformat(static_transmission["generated_at"])  # 可解析即通过


def test_static_transmission_coupling_matrix(static_transmission):
    """6 域 15 对全枚举，coupling ∈ [0,1]，lags_min ∈ [0,1440]。"""
    coupling = static_transmission["domain_transmission"]["drift_coupling"]
    pairs = set()
    for key, meta in coupling.items():
        assert "↔" in key, f"pair 格式非法：{key}"
        left, right = key.split("↔", 1)
        assert left in DOMAINS and right in DOMAINS, f"未知域：{key}"
        assert left != right
        pairs.add(frozenset((left, right)))
        assert 0.0 <= float(meta["coupling"]) <= 1.0
        assert 0 <= int(meta["lags_min"]) <= 1440

    expected = {frozenset(p) for p in itertools.combinations(DOMAINS, 2)}
    assert pairs == expected, f"缺失配对：{expected - pairs}"


def test_static_transmission_declares_source(static_transmission):
    """PLAN 锚点①+Phase B: source 必须可辨识, 避免被误当实盘信号.

    Phase A 静态先验: source="static";
    Phase B Head 推理: source="neural_sde_head_infer".
    两者都非实盘信号, 必须带 note 说明.
    """
    source = static_transmission["source"]
    assert source in {"static", "neural_sde_head_infer"}, f"未知 source={source}"
    assert "note" in static_transmission


# ---------- observe() 消费 ----------
def _envelope(source: str, trace_id: str = "", **meta) -> dict:
    return {"ok": True, "source": source, "trace_id": trace_id, "meta": meta}


def test_observe_attaches_l1_insights(tmp_path):
    shadow = AgentMailShadow(trajectory_store_path=str(tmp_path / "t.jsonl"))
    result = shadow.observe(
        [
            _envelope("l0.cognition.mcp", "trace-a", poe_score=0.8),
            _envelope("l0.rea.mcp", "trace-b", poe_score=0.6),
        ]
    )
    assert result["observed"] == 2
    assert result["domains"] == ["cognition", "rea"]

    insights = result["l1_insights"]
    assert set(insights) == {"coupling_consistency", "l1_regime_match", "l1_state"}
    assert insights["l1_state"] == "neutral"
    assert insights["l1_regime_match"] == "bull"

    cc = insights["coupling_consistency"]
    assert cc["verdict"] == "consistent"  # cognition↔rea 强耦合边两端均在线
    assert cc["consistency_ratio"] == 1.0


def test_observe_reports_insufficient_data_on_single_domain(tmp_path):
    shadow = AgentMailShadow(trajectory_store_path=str(tmp_path / "t.jsonl"))
    cc = shadow.observe([_envelope("l0.data.mcp")])["l1_insights"]["coupling_consistency"]
    assert cc["verdict"] == "insufficient_data"
    assert cc["checked_pairs"] == []
    assert cc["consistency_ratio"] is None


def test_observe_reports_drift_on_weak_pair_cooccurrence(tmp_path):
    """Phase B Head 推理后 cognition↔data coupling=0.0 (原 0.25 弱带, 仍 ≤0.3).

    测试不再硬编码 coupling 值, 改为断言:
    - band=="weak" (≤0.3 的 pair 共现 → drift)
    - static_coupling ≤ 0.3 (弱带阈值)
    - consistency_ratio == 0.0
    """
    shadow = AgentMailShadow(trajectory_store_path=str(tmp_path / "t.jsonl"))
    cc = shadow.observe([_envelope("l0.cognition.mcp"), _envelope("l0.data.mcp")])["l1_insights"][
        "coupling_consistency"
    ]
    assert cc["verdict"] == "drift"
    assert cc["consistency_ratio"] == 0.0
    pair_info = cc["checked_pairs"][0]
    assert pair_info["band"] == "weak"
    assert pair_info["static_coupling"] <= 0.3


def test_observe_fail_open_without_static_prior(tmp_path):
    shadow = AgentMailShadow(
        l1_transmission_path=str(tmp_path / "missing.json"),
        trajectory_store_path=str(tmp_path / "t.jsonl"),
    )
    result = shadow.observe(_envelope("l0.cognition.mcp"))
    assert result["observed"] == 1
    assert "l1_insights" not in result


def test_observe_fail_open_with_corrupted_prior(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    shadow = AgentMailShadow(
        l1_transmission_path=str(bad), trajectory_store_path=str(tmp_path / "t.jsonl")
    )
    assert shadow.load_transmission() is None
    assert "l1_insights" not in shadow.observe(_envelope("l0.data.mcp"))


def test_load_transmission_rejects_wrong_shape(tmp_path):
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"domain_layers": {}}), encoding="utf-8")
    shadow = AgentMailShadow(l1_transmission_path=str(wrong))
    assert shadow.load_transmission() is None


# ---------- S1/S2/S3 硬约束 ----------
def test_s2_trace_id_carries_shadow_prefix(tmp_path):
    store = tmp_path / "t.jsonl"
    shadow = AgentMailShadow(trajectory_store_path=str(store))
    shadow.observe(
        [
            _envelope("l0.cognition.mcp", "main-trace-001"),
            _envelope("l0.rea.mcp"),  # 无 trace_id → 自动生成
        ]
    )
    rows = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]
    assert all(row["trace_id"].startswith(SHADOW_PREFIX) for row in rows)
    assert rows[0]["trace_id"] == SHADOW_PREFIX + "main-trace-001"

    # 已是 shadow- 前缀则不重复叠加
    shadow.observe(_envelope("l0.data.mcp", SHADOW_PREFIX + "fixed"))
    last = shadow.get_recent_trajectories(limit=1)[0]
    assert last["trace_id"] == SHADOW_PREFIX + "fixed"


def test_s3_only_writes_trajectory_store(tmp_path):
    store = tmp_path / "nested" / "trajectories.jsonl"
    shadow = AgentMailShadow(trajectory_store_path=str(store))
    shadow.observe([_envelope("l0.cognition.mcp"), _envelope("l0.eval.mcp")])
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files == [store]
    assert len(store.read_text(encoding="utf-8").splitlines()) == 2


def test_default_store_path_is_outside_repo_tracking():
    assert DEFAULT_STORE_PATH.as_posix().endswith(".workbuddy/agent_mail/trajectories.jsonl")


def test_ring_buffer_respects_max_entries(tmp_path):
    shadow = AgentMailShadow(trajectory_store_path=str(tmp_path / "t.jsonl"), max_entries=3)
    for _ in range(5):
        shadow.observe(_envelope("l0.data.mcp"))
    assert len(shadow.get_recent_trajectories(limit=10)) == 3


# ---------- 查询 / 评估 / 报告 ----------
def test_get_recent_trajectories_filters_domain(tmp_path):
    shadow = AgentMailShadow(trajectory_store_path=str(tmp_path / "t.jsonl"))
    shadow.observe([_envelope("l0.cognition.mcp"), _envelope("l0.rea.mcp")])
    assert len(shadow.get_recent_trajectories(domain="cognition")) == 1
    assert len(shadow.get_recent_trajectories(limit=1)) == 1


def test_evaluate_policy_value_formula(tmp_path):
    shadow = AgentMailShadow(trajectory_store_path=str(tmp_path / "t.jsonl"))
    shadow.observe(
        [
            _envelope("l0.cognition.mcp", poe_score=0.9, messages_sent=2),
            _envelope("l0.rea.mcp", poe_score=0.3, messages_sent=2),
        ]
    )
    result = shadow.evaluate_policy("baseline")
    assert result["n"] == 2
    assert result["quality"] == 0.6
    assert result["cost"] == 4.0
    assert result["V"] == 0.15
    assert shadow.evaluate_policy("baseline", trajectories=[])["V"] == 0.0


def test_generate_report_contains_l1_state(tmp_path):
    shadow = AgentMailShadow(trajectory_store_path=str(tmp_path / "t.jsonl"))
    shadow.observe([_envelope("l0.cognition.mcp"), _envelope("l0.rea.mcp")])
    report = shadow.generate_report(days=1)
    assert "observations: 2" in report
    assert "l1_state: neutral" in report
    assert "coupling_consistency: consistent" in report


def test_observe_accepts_single_envelope(tmp_path):
    shadow = AgentMailShadow(trajectory_store_path=str(tmp_path / "t.jsonl"))
    result = shadow.observe(_envelope("l0.store-admin.mcp"))
    assert result["domains"] == ["store-admin"]


def test_domain_derives_from_unknown_source_without_crash(tmp_path):
    shadow = AgentMailShadow(trajectory_store_path=str(tmp_path / "t.jsonl"))
    result = shadow.observe({"ok": True, "source": "custom.thing.mcp", "meta": {}})
    assert result["observed"] == 1
