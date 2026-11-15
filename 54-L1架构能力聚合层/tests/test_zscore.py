# -*- coding: utf-8 -*-
"""D-A05 z-score 能力出口（datacenter.percentile scope）单元测试。"""

import os
import sys

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.capabilities.stats import run_capability, zscore  # noqa: E402


def _ramp(n, *, last=None):
    values = [0.01 * (index + 1) for index in range(n)]
    if last is not None:
        values[-1] = last
    return values


def test_zscore_returns_mean_std_and_winsorized_flag():
    result = zscore(_ramp(40), name="测试序列")
    assert result["ok"] is True
    assert result["capability"] == "D-A05"
    block = result["data"]["capabilities"]["D-A05"]
    assert block["methods"] == ["S26"]
    assert block["zscore"] > 0
    assert block["mean"] > 0 and block["std"] > 0
    assert block["winsorized"] is True
    assert block["sample_n"] == 40 and block["lookback"] == 40
    assert result["quality"]["sources"] == ["datacenter.percentile"]
    assert "z 值为" in result["answer"]


def test_zscore_short_sample_degrades_to_empty():
    result = zscore(_ramp(29))
    assert result["ok"] is False
    assert result["quality"]["status"] == "empty"
    assert "有效样本" in result["answer"]


def test_zscore_zero_variance_is_not_faked():
    result = zscore([0.01] * 40)
    assert result["ok"] is True
    block = result["data"]["capabilities"]["D-A05"]
    assert block["zscore"] is None
    assert block["std"] == 0.0
    assert block["gate"] == "partial"
    assert "zero_variance" in (result["quality"].get("degraded_reason") or "")
    assert "不可计算" in result["answer"]


def test_zscore_lookback_validation_and_truncation():
    assert zscore(_ramp(40), lookback=10)["ok"] is False
    assert "lookback" in zscore(_ramp(40), lookback=10)["answer"]

    truncated = zscore(_ramp(40), lookback=90)
    assert truncated["ok"] is True
    block = truncated["data"]["capabilities"]["D-A05"]
    assert block["lookback"] == 40
    assert "lookback_truncated" in (truncated["quality"].get("degraded_reason") or "")


def test_zscore_invalid_inputs_fail_closed():
    assert zscore([])["quality"]["status"] == "empty"
    assert zscore([0.1, "bad", 0.3])["quality"]["status"] == "empty"
    mismatch = zscore([0.1, 0.2, 0.3] * 10, dates=["2026-11-01"])
    assert mismatch["quality"]["status"] == "empty"
    assert "日期轴" in mismatch["answer"]


def test_zscore_is_dispatchable_through_run_capability():
    result = run_capability("D-A05", values=_ramp(35), symbol="BTC", unit="USD")
    assert result["ok"] is True
    assert result["data"]["capabilities"]["D-A05"]["methods"] == ["S26"]
    assert result["data"]["symbol"] == "BTC"
