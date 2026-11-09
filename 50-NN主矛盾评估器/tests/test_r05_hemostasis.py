"""WP-R0.5 止血三件套测试（F1 source 命名 / F2 权重归一+默认维度 / F3 源年龄新鲜度）。

关联：SPEC-M1 §三 M1-M3、§五 M8；PLAN-NN闭环链施工 WP-R0.5 退出标准。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from core.mappings import (
    DEFAULT_DIMENSION,
    SOURCE_WEIGHT_MAP,
    VALID_DIMENSIONS,
    normalize_source,
    role_of,
)
from core.path_synthesis import synthesize_paths

NOW = datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc)


def evidence(**overrides):
    base = {
        "evidence_id": "e1",
        "source": "11-bdsm",
        "symbol": "BTC-USDT-SWAP",
        "granularity": "per_symbol",
        "direction": "long",
        "confidence": 0.8,
        "horizon": "hours",
        "intent": None,
        "ts": "2026-11-09T00:00:00Z",
        "expires_at": "2026-11-09T02:00:00Z",
        "provenance": "42-bus",
        "payload": {},
    }
    base.update(overrides)
    return base


# ── F1：source 命名统一 ──────────────────────────────────────────


def test_f1_legacy_names_normalize_to_canonical():
    """42 双写过渡期旧名必须归一到 canonical 43-strategic。"""
    assert normalize_source("strategic_extension") == "43-strategic"
    assert normalize_source("43-strategic-extension") == "43-strategic"
    assert normalize_source("strategic") == "43-strategic"


def test_f1_canonical_role_is_constraint():
    assert role_of("43-strategic") == "constraint"


def test_f1_legacy_source_no_longer_steals_vote():
    """串线修复：旧名 strategic_extension 曾以 unknown/C3/0.05 混票，现归 constraint 不产 path。"""
    paths = synthesize_paths([evidence(source="strategic_extension")], now=NOW)
    assert paths == []


def test_f1_dual_write_counts_single_vote():
    """双写期 canonical + 旧名同信号上总线，归一后同 dedup key，只计一票（此处均为 constraint 不产 path）。"""
    paths = synthesize_paths(
        [
            evidence(source="43-strategic", evidence_id="sig-1"),
            evidence(source="strategic_extension", evidence_id="sig-1"),
        ],
        now=NOW,
    )
    assert paths == []


# ── F2：默认维度合法 + 权重按 source 归一 ────────────────────────


def test_f2_default_dimension_is_valid():
    """DEFAULT_DIMENSION 必须是 VALID_DIMENSIONS 成员（原 C3 为硬 bug）。"""
    assert DEFAULT_DIMENSION in VALID_DIMENSIONS


def test_f2_weight_normalized_by_source():
    """26 条 bcrm-tactical path 总权重 = 0.35（source 权重），而非 26×0.35=9.10。"""
    evidences = [
        evidence(
            source="11-bcrm-tactical",
            symbol=f"COIN{i:02d}-USDT-SWAP",
            evidence_id=f"e{i}",
        )
        for i in range(26)
    ]
    paths = synthesize_paths(evidences, now=NOW)
    assert len(paths) == 26
    total = sum(p.metadata["weight"] for p in paths)
    assert total == pytest.approx(SOURCE_WEIGHT_MAP["11-bcrm-tactical"])
    expected_each = SOURCE_WEIGHT_MAP["11-bcrm-tactical"] / 26
    for p in paths:
        assert p.metadata["weight"] == pytest.approx(expected_each)
        assert p.metadata["weight_raw"] == SOURCE_WEIGHT_MAP["11-bcrm-tactical"]
        assert p.metadata["source_path_count"] == 26


def test_f2_external_weight_sum_conserved():
    """归一后全体外部源权重之和保持 = 1.0（多源混合场景）。"""
    evidences = []
    for source, n in [
        ("11-bcrm", 2),
        ("11-bdsm", 3),
        ("11-washout", 1),
        ("11-event-arbitrage", 1),
        ("11-bcrm-tactical", 5),
    ]:
        for i in range(n):
            evidences.append(
                evidence(source=source, symbol=f"{source}-{i}", evidence_id=f"{source}-{i}")
            )
    paths = synthesize_paths(evidences, now=NOW)
    total = sum(p.metadata["weight"] for p in paths)
    assert total == pytest.approx(1.0)


# ── F3：源数据年龄校验 ──────────────────────────────────────────


def test_f3_source_stale_evidence_dropped():
    """40-cycle 源数据 15 天前生成（>2×168h TTL）→ 即使总线新鲜也丢弃。"""
    stale = (NOW - timedelta(days=15)).isoformat()
    paths = synthesize_paths(
        [
            evidence(
                source="40-divergence",
                payload={"state_generated_at": stale},
            )
        ],
        now=NOW,
    )
    assert paths == []


def test_f3_source_age_decays_freshness():
    """11 源 payload 12h 前生成（TTL=24h）→ freshness = min(bus 0.5, exp(-0.5)) ≈ 0.5×0.8 折上折。"""
    import math

    generated = (NOW - timedelta(hours=12)).isoformat()
    paths = synthesize_paths(
        [evidence(payload={"state_generated_at": generated})],
        now=NOW,
    )
    assert len(paths) == 1
    # bus freshness = 1h/2h = 0.5；source freshness = exp(-12/24) ≈ 0.607；取 min
    expected = 0.8 * min(0.5, math.exp(-0.5))
    assert paths[0].confidence == pytest.approx(expected)


def test_f3_missing_state_timestamp_fails_open():
    """payload 无源时间戳 → 沿用总线新鲜度（fail-open，不新增降级）。"""
    paths = synthesize_paths([evidence()], now=NOW)
    assert len(paths) == 1
    assert paths[0].confidence == pytest.approx(0.4)  # 0.8 × bus 0.5
