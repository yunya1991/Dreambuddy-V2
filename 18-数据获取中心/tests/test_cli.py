"""CLI 壳测试 — 对齐 TECHNICAL_DESIGN.md §5.3。

data-center fetch macro --series FEDFUNDS --source fred 端到端；
data-center list collectors 列出已注册采集器。
"""
import pandas as pd
from typer.testing import CliRunner

from data_center.cli.app import app

runner = CliRunner()
FRED_MOD = "data_center.collectors.macro.fred_collector.Fred"


def _make_series():
    idx = [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-08-01")]
    return pd.Series([5.0, 5.25], index=idx)


def test_fetch_macro_fred(mocker, monkeypatch):
    mocker.patch(FRED_MOD).return_value.get_series.return_value = _make_series()
    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    result = runner.invoke(
        app, ["fetch", "macro", "--series", "FEDFUNDS", "--source", "fred"]
    )
    assert result.exit_code == 0, result.stdout
    assert "5.25" in result.stdout
    assert "FEDFUNDS" in result.stdout


def test_list_collectors():
    result = runner.invoke(app, ["list", "collectors"])
    assert result.exit_code == 0, result.stdout
    assert "fred" in result.stdout
    assert "macro" in result.stdout
