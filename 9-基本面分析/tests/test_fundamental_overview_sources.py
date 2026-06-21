from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import os


def _load_embedded_service():
    p = Path("backend/src/_embedded_ml_trade_service_source.py").resolve()
    spec = spec_from_file_location("embedded_service_for_test", str(p))
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fundamental_overview_contains_okx_p0_sources() -> None:
    os.environ["FUNDAMENTAL_GRAY_V1"] = "1"
    svc = _load_embedded_service()
    rep = svc._fundamental_overview_latest()
    src = rep.get("source_summary") if isinstance(rep.get("source_summary"), dict) else {}
    primary = src.get("primary_sources") if isinstance(src.get("primary_sources"), list) else []
    cross = src.get("cross_validation") if isinstance(src.get("cross_validation"), list) else []
    assert "okx:market-intel" in primary
    assert "okx:cmc-okx" in primary
    assert "okx:alpha-vantage" in primary
    assert "okx:hyperliquid-analyzer" in primary
    assert "gate-info-research" in cross
    assert "gate-info-coinanalysis" in cross
    assert "binance:crypto-market-rank" in cross


def test_fundamental_overview_hides_source_summary_when_gray_off() -> None:
    os.environ["FUNDAMENTAL_GRAY_V1"] = "0"
    svc = _load_embedded_service()
    rep = svc._fundamental_overview_latest()
    assert "source_summary" not in rep
