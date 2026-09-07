"""测试 CapitalRotationAdapter — 资金轮动检测器"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dreambuddy_evolution.adapters.capital_rotation import (
    CapitalRotationAdapter,
    COMPETITOR_GROUPS,
)


def _make_candles(vols, closes):
    """构造 OKX 格式 candles（descending, newest first）"""
    return [
        {"c": str(c), "h": str(c), "l": str(c), "o": str(c), "vol": str(v)}
        for c, v in zip(reversed(closes), reversed(vols))
    ]


def test_find_group():
    """竞品组查找"""
    assert CapitalRotationAdapter._find_group("BTC") == "large_cap"
    assert CapitalRotationAdapter._find_group("UNI") in ("dex_platform", "meme_platform")
    assert CapitalRotationAdapter._find_group("UNKNOWN") is None


def test_neutral_result():
    """无竞品组时返回中性"""
    client = MagicMock()
    rot = CapitalRotationAdapter(client)
    result = rot.detect_rotation("UNKNOWN")
    assert result["capital_rotation"] == 0.0
    assert result["rotation_detected"] is False


def test_rotation_positive():
    """本币强于组均值 → 正轮动"""
    client = MagicMock()
    # BTC 强势，其他弱势
    client.get_kline.side_effect = lambda inst_id, bar, limit: {
        "ok": True,
        "candles": _make_candles(
            vols=[100] * 20 if "BTC" in inst_id else [50] * 20,
            closes=[100 + i for i in range(20)] if "BTC" in inst_id else [100 - i for i in range(20)],
        ),
    }
    client.get_open_interest.return_value = {"ok": True, "open_interest": 1e6}

    rot = CapitalRotationAdapter(client)
    result = rot.detect_rotation("BTC")
    assert result["capital_rotation"] > 0
    assert result["token_score"] > result["group_avg_score"]


def test_rotation_negative():
    """本币弱于组均值 → 负轮动（PUMP 案例）"""
    client = MagicMock()
    # PUMP 弱势，UNI 强势
    def kline_resp(inst_id, bar, limit):
        if "PUMP" in inst_id:
            return {"ok": True, "candles": _make_candles([30]*20, [100-i for i in range(20)])}
        return {"ok": True, "candles": _make_candles([150]*20, [100+i for i in range(20)])}
    client.get_kline.side_effect = kline_resp
    client.get_open_interest.return_value = {"ok": True, "open_interest": 1e6}

    rot = CapitalRotationAdapter(client)
    result = rot.detect_rotation("PUMP")
    assert result["capital_rotation"] < 0
    assert result["rotation_detected"] is True


def test_capital_score_components():
    """资金流得分三维加权"""
    client = MagicMock()
    client.get_kline.return_value = {
        "ok": True,
        "candles": _make_candles([200]*20, [100+i*0.5 for i in range(20)]),  # 放量+上涨
    }
    client.get_open_interest.return_value = {"ok": True, "open_interest": 1e7}  # 高OI

    rot = CapitalRotationAdapter(client)
    score = rot._compute_capital_score("BTC")
    assert score is not None
    assert -1.0 <= score <= 1.0
    assert score > 0  # 放量+上涨+高OI → 正得分


def test_fail_open_on_api_error():
    """API 失败 → FAIL-OPEN 返回 None"""
    client = MagicMock()
    client.get_kline.return_value = {"ok": False}
    rot = CapitalRotationAdapter(client)
    assert rot._compute_capital_score("BTC") is None


def test_fail_open_on_crash():
    """异常 → detect_rotation 返回中性"""
    client = MagicMock()
    client.get_kline.side_effect = RuntimeError("boom")
    rot = CapitalRotationAdapter(client)
    result = rot.detect_rotation("BTC")
    assert result["capital_rotation"] == 0.0
    assert result["rotation_detected"] is False
