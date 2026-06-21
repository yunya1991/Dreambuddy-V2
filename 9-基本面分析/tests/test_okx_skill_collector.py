from ops.nanoclaw.core_task1.flow.scripts.okx_skill_collector import build_snapshot_stub


def test_build_snapshot_stub_contains_p0_sources() -> None:
    out = build_snapshot_stub(asset="BTC")
    assert out["asset"] == "BTC"
    assert "okx:market-intel" in out["sources"]
    assert "okx:cmc-okx" in out["sources"]
    assert "okx:alpha-vantage" in out["sources"]
    assert "okx:hyperliquid-analyzer" in out["sources"]
