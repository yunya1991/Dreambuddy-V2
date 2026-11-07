import pytest

from okx_venue import OkxCliVenue, VenueConfig, VenueError, build_order_adapter


class FakeRunner:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return self.payload


def _cfg(tmp_path):
    return VenueConfig(
        profile="demo", mode="demo", audit_path=tmp_path / "audit.jsonl"
    )


def test_get_ticker_normalizes(tmp_path):
    runner = FakeRunner(
        [{"instId": "BTC-USDT-SWAP", "last": "70000", "bidPx": "69999", "askPx": "70001"}]
    )
    venue = OkxCliVenue(_cfg(tmp_path), runner=runner)
    ticker = venue.get_ticker("BTC-USDT-SWAP")
    assert ticker["last"] == 70000.0
    assert ticker["bid"] == 69999.0
    assert ticker["ask"] == 70001.0
    assert runner.calls[0][0] == ["market", "ticker", "BTC-USDT-SWAP"]


def test_get_balance_prefers_usdt_available(tmp_path):
    runner = FakeRunner(
        [
            {
                "totalEq": "1234.5",
                "details": [
                    {"ccy": "BTC", "availBal": "1"},
                    {"ccy": "USDT", "availBal": "1000", "availEq": "1100"},
                ],
            }
        ]
    )
    venue = OkxCliVenue(_cfg(tmp_path), runner=runner)
    balance = venue.get_balance()
    assert balance["balance"] == 1000.0
    assert balance["total_eq"] == 1234.5
    assert balance["ccy"] == "USDT"


def test_get_positions_normalizes_net_and_side(tmp_path):
    runner = FakeRunner(
        [
            {"instId": "BTC-USDT-SWAP", "pos": "2", "posSide": "long", "avgPx": "70000"},
            {"instId": "ETH-USDT-SWAP", "pos": "-3", "posSide": "net", "avgPx": "3000"},
        ]
    )
    venue = OkxCliVenue(_cfg(tmp_path), runner=runner)
    positions = venue.get_positions()
    assert positions["count"] == 2
    assert positions["positions"][0]["pos_side"] == "long"
    assert positions["positions"][0]["pos"] == 2.0
    assert positions["positions"][1]["pos_side"] == "short"
    assert positions["positions"][1]["pos"] == 3.0


def test_place_swap_market_order_argv(tmp_path):
    runner = FakeRunner({"ordId": "abc", "clOrdId": "c1", "sCode": "0", "sMsg": ""})
    venue = OkxCliVenue(_cfg(tmp_path), runner=runner)
    result = venue.place_order("BTC-USDT-SWAP", "buy", 2, td_mode="cross")
    assert result["ok"] is True
    assert result["order_id"] == "abc"
    argv, kwargs = runner.calls[0]
    assert argv[:2] == ["swap", "place"]
    assert "--instId" in argv and "BTC-USDT-SWAP" in argv
    assert "--tdMode" in argv and "cross" in argv
    assert kwargs["write"] is True
    assert kwargs["operation"] == "place_order"


def test_place_spot_limit_order_argv(tmp_path):
    runner = FakeRunner([{"ordId": "s1", "sCode": "0"}])
    venue = OkxCliVenue(_cfg(tmp_path), runner=runner)
    result = venue.place_order(
        "BTC-USDT", "sell", 0.5, order_type="limit", price=71000
    )
    assert result["ok"] is True
    argv, _ = runner.calls[0]
    assert argv[:2] == ["spot", "place"]
    assert "--tdMode" in argv and "cash" in argv
    assert "--px" in argv and "71000" in argv


def test_place_limit_requires_price(tmp_path):
    venue = OkxCliVenue(_cfg(tmp_path), runner=FakeRunner({}))
    with pytest.raises(VenueError):
        venue.place_order("BTC-USDT", "buy", 1, order_type="limit")


def test_cancel_order_argv(tmp_path):
    runner = FakeRunner({"ordId": "abc", "sCode": "0"})
    venue = OkxCliVenue(_cfg(tmp_path), runner=runner)
    venue.cancel_order("BTC-USDT-SWAP", ord_id="abc")
    argv, kwargs = runner.calls[0]
    assert argv[:2] == ["swap", "cancel"]
    assert "--ordId" in argv and "abc" in argv
    assert kwargs["write"] is True


def test_selector_paper_returns_none(tmp_path):
    assert build_order_adapter("paper", config=_cfg(tmp_path)) is None


def test_selector_demo_returns_adapter(tmp_path):
    adapter = build_order_adapter(
        "okx-cli-demo", config=_cfg(tmp_path), runner=FakeRunner({})
    )
    assert isinstance(adapter, OkxCliVenue)


def test_selector_rejects_live_and_unknown(tmp_path):
    with pytest.raises(VenueError):
        build_order_adapter("okx-cli-live", config=_cfg(tmp_path))
    with pytest.raises(VenueError):
        build_order_adapter("sandbox", config=_cfg(tmp_path))