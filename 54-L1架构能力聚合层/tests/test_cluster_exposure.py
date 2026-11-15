# -*- coding: utf-8 -*-
"""L1X-04 相关性簇敞口单测（V-AC21）。"""

import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.trading import cluster, risk, sizing  # noqa: E402

_NAMES = ["BTC", "ETH", "GOLD"]
_MATRIX = [
    [1.00, 0.92, 0.10],
    [0.92, 1.00, 0.05],
    [0.10, 0.05, 1.00],
]


def test_clusters_group_high_corr():
    mapping = cluster.clusters(_NAMES, _MATRIX)
    assert mapping["BTC"] == mapping["ETH"] == "c1"
    assert mapping["GOLD"] == "c2"


def test_threshold_controls_grouping():
    split = cluster.clusters(_NAMES, _MATRIX, threshold=0.95)
    assert split["BTC"] != split["ETH"]


def test_matrix_must_be_square():
    with pytest.raises(ValueError):
        cluster.clusters(_NAMES, [[1.0, 0.9], [0.9, 1.0]])


def test_cluster_exposure_sums_same_cluster():
    mapping = cluster.clusters(_NAMES, _MATRIX)
    exposures = {"BTC": 400.0, "ETH": 100.0, "GOLD": 50.0}
    assert cluster.cluster_exposure("BTC", exposures, mapping) == 500.0
    assert cluster.cluster_exposure("GOLD", exposures, mapping) == 50.0


def test_above_cap_rejected():
    mapping = cluster.clusters(_NAMES, _MATRIX)
    out = cluster.check_cluster_exposure(
        symbol="ETH", notional_usdt=300.0, exposures={"BTC": 400.0, "GOLD": 300.0}, mapping=mapping
    )
    assert out["cluster"] == "c1"
    assert out["ratio"] == 0.7
    assert out["allowed"] is False
    assert out["reject_reason"] == risk.CLUSTER_EXPOSURE


def test_below_cap_allowed():
    mapping = cluster.clusters(_NAMES, _MATRIX)
    out = cluster.check_cluster_exposure(
        symbol="ETH", notional_usdt=100.0, exposures={"BTC": 200.0, "GOLD": 800.0}, mapping=mapping
    )
    assert out["ratio"] == 0.272727
    assert out["allowed"] is True
    assert out["reject_reason"] is None


def test_risk_and_sizing_honor_cluster():
    decision = risk.check_order(
        notional_usdt=300.0,
        equity_usdt=1000.0,
        gross_exposure_usdt=600.0,
        cluster_exposure_usdt=400.0,
    )
    assert decision["allowed"] is False
    assert decision["reject_reason"] == risk.CLUSTER_EXPOSURE
    assert decision["checks"][risk.CLUSTER_EXPOSURE] is True

    sized = sizing.target_position(
        1,
        1.0,
        price=100.0,
        equity_usdt=200.0,
        volatility=0.02,
        gross_exposure_usdt=500.0,
        cluster_exposure_usdt=500.0,
    )
    assert sized["notional_usdt"] == 200.0
    assert sized["reject_reason"] == risk.CLUSTER_EXPOSURE
    assert sized["qty"] == 0.0
