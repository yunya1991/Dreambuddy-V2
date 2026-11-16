# -*- coding: utf-8 -*-
"""美股龙头动态排名测试（离线：loader 全部注入）。"""

import datetime
import os
import sys

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import stock_ranking as SR  # noqa: E402

_AS_OF = datetime.date(2026, 11, 16)  # 周一


def _series(values, end=datetime.date(2026, 11, 13)):
    """按自然日倒推生成升序 [(date, value)]。"""
    n = len(values)
    return [(end - datetime.timedelta(days=n - 1 - i), float(v)) for i, v in enumerate(values)]


def _loader(prices, amounts):
    def load(symbol, metric):
        table = prices if metric == "close_usd" else amounts
        return table.get(symbol, [])

    return load


def test_freeze_week_is_monday():
    assert SR.freeze_week(datetime.date(2026, 11, 16)) == datetime.date(2026, 11, 16)
    assert SR.freeze_week(datetime.date(2026, 11, 19)) == datetime.date(2026, 11, 16)


def test_zscore_standardizes_and_handles_zero_variance():
    z = SR.zscore([1.0, 2.0, 3.0])
    assert round(sum(z), 10) == 0.0
    assert round(sum(v * v for v in z) / 3, 10) == 1.0
    assert SR.zscore([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]
    assert SR.zscore([]) == []


def test_momentum_needs_lookback_plus_one():
    assert SR._momentum(_series([100.0] * 20), 20) is None
    assert round(SR._momentum(_series([100.0] * 20 + [110.0]), 20), 6) == 0.1


def test_top3_by_combined_score():
    # 成交额：NVDA 最大、META 最小；动量：TSLA 最强
    prices = {
        "NVDA": _series([100.0] * 20 + [101.0]),
        "AAPL": _series([100.0] * 20 + [100.0]),
        "MSFT": _series([100.0] * 20 + [99.0]),
        "TSLA": _series([100.0] * 20 + [120.0]),
        "AMZN": _series([100.0] * 20 + [98.0]),
        "GOOGL": _series([100.0] * 20 + [97.0]),
        "META": _series([100.0] * 20 + [96.0]),
    }
    amounts = {
        "NVDA": _series([5e10] * 20),
        "AAPL": _series([4e10] * 20),
        "MSFT": _series([3e10] * 20),
        "TSLA": _series([2e10] * 20),
        "AMZN": _series([1.5e10] * 20),
        "GOOGL": _series([1e10] * 20),
        "META": _series([5e9] * 20),
    }
    out = SR.compute(_loader(prices, amounts), as_of=_AS_OF)
    assert out["rank_source"] == "dynamic"
    assert out["rank_degraded"] is False
    assert out["degraded_reason"] == ""
    assert [item["symbol"] for item in out["top"]] == ["TSLA", "NVDA", "AAPL"]
    assert [item["rank"] for item in out["top"]] == [1, 2, 3]
    assert out["freeze_week"] == "2026-11-16"
    assert out["data_cutoff"] == "2026-11-15"


def test_missing_amount_degrades_to_static():
    prices = {
        "NVDA": _series([100.0] * 21),
        "AAPL": _series([100.0] * 21),
        "MSFT": _series([100.0] * 21),
        "TSLA": _series([100.0] * 21),
        "AMZN": _series([100.0] * 21),
        "GOOGL": _series([100.0] * 21),
        "META": _series([100.0] * 21),
    }
    out = SR.compute(_loader(prices, {}), as_of=_AS_OF)
    assert out["rank_source"] == "static"
    assert out["rank_degraded"] is True
    assert "amount_lt_20" in out["degraded_reason"]
    assert [item["symbol"] for item in out["top"]] == list(SR.STATIC_TOP)


def test_short_history_marks_candidate_unavailable():
    prices = {"NVDA": _series([100.0] * 20)}  # 只有 20 根，缺基准点
    amounts = {"NVDA": _series([1e10] * 20)}
    out = SR.compute(_loader(prices, amounts), as_of=_AS_OF, candidates=("NVDA",))
    assert out["rank_degraded"] is True
    assert "close_lt_21" in out["degraded_reason"]
    assert out["candidates"][0]["available"] is False


def test_pool_version_stable_in_week_and_changes_across_weeks():
    prices = {s: _series([100.0] * 20 + [105.0]) for s in SR.CANDIDATES}
    amounts = {s: _series([1e10] * 20) for s in SR.CANDIDATES}
    loader = _loader(prices, amounts)
    mon = SR.compute(loader, as_of=datetime.date(2026, 11, 16))
    thu = SR.compute(loader, as_of=datetime.date(2026, 11, 19))
    assert mon["pool_version"] == thu["pool_version"]  # 同周冻结
    nxt = SR.compute(loader, as_of=datetime.date(2026, 11, 23))
    assert nxt["pool_version"] != mon["pool_version"]  # 跨周换版本


def test_records_are_json_serializable():
    import json

    prices = {s: _series([100.0] * 21) for s in SR.CANDIDATES}
    amounts = {s: _series([1e10] * 20 + [1e10]) for s in SR.CANDIDATES}
    out = SR.compute(_loader(prices, amounts), as_of=_AS_OF)
    json.dumps(out, ensure_ascii=False)
