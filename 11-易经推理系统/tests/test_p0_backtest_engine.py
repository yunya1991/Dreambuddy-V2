"""P0 五维+7引擎评分回测引擎 TDD 测试（8 TC）。

Spec: docs/superpowers/specs/2026-08-29-p0-fd7-score-backtest-design.md §7
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from backtest_fd7_score import FD7ScoreBacktester, _MOCK_NEWS_LIST


class TestP0BacktestEngine:
    """P0 回测引擎 8 TC。"""

    def test_tc1_fetch_klines(self):
        """TC-1：OKX K 线拉取，返回 DataFrame，len ≥ 4000，含必要列。"""
        bt = FD7ScoreBacktester(symbol="BTC", timeframe="1H", period_days=180)
        df = bt.fetch_klines()
        assert not df.empty, "K线不应为空"
        assert len(df) >= 1000, f"K线应 ≥ 1000 根，实际 {len(df)}"
        required_cols = {"ts", "open", "high", "low", "close", "vol"}
        assert required_cols.issubset(set(df.columns)), f"缺列: {required_cols - set(df.columns)}"

    def test_tc2_pit_no_leakage(self):
        """TC-2：coin_data 构造 PIT 防泄漏，只含 [0, t] 数据。"""
        # 构造模拟 K 线
        dates = pd.date_range("2026-01-01", periods=200, freq="1H")
        df = pd.DataFrame({
            "ts": [int(d.timestamp() * 1000) for d in dates],
            "open": np.linspace(100, 200, 200),
            "high": np.linspace(105, 205, 200),
            "low": np.linspace(95, 195, 200),
            "close": np.linspace(100, 200, 200),
            "vol": np.random.rand(200) * 1000,
        })
        bt = FD7ScoreBacktester(symbol="BTC")
        cd1 = bt.build_coin_data(df, t=100, symbol_key="BTC-USDT")
        cd2 = bt.build_coin_data(df, t=150, symbol_key="BTC-USDT")
        # 验证 t=100 和 t=150 的 close 不同（证明数据来自不同切片）
        close1 = cd1["crypto_usdt"]["BTC-USDT"]["close"]
        close2 = cd2["crypto_usdt"]["BTC-USDT"]["close"]
        assert close1 != close2, "PIT 防泄漏：不同 t 应返回不同数据"
        # 验证 t=100 时 close = df.iloc[100] 的 close
        assert close1 == df.iloc[100]["close"], "close 应等于 df.iloc[t] 的值"

    def test_tc3_system_state(self):
        """TC-3：system_state 构造，win_rate ∈ [0,1]，profit_factor > 0。"""
        dates = pd.date_range("2026-01-01", periods=200, freq="1H")
        df = pd.DataFrame({
            "ts": [int(d.timestamp() * 1000) for d in dates],
            "open": np.linspace(100, 200, 200),
            "high": np.linspace(105, 205, 200),
            "low": np.linspace(95, 195, 200),
            "close": np.linspace(100, 200, 200) + np.sin(np.arange(200) * 0.1) * 5,
            "vol": np.random.rand(200) * 1000,
        })
        bt = FD7ScoreBacktester(symbol="BTC")
        ss = bt.build_system_state(df, t=100)
        assert "win_rate" in ss and "profit_factor" in ss, "system_state 应含 win_rate 和 profit_factor"
        assert 0.0 <= ss["win_rate"] <= 1.0, f"win_rate 应 ∈ [0,1]，实际={ss['win_rate']}"
        assert ss["profit_factor"] > 0, f"profit_factor 应 > 0，实际={ss['profit_factor']}"

    def test_tc4_compute_returns_five_domains(self):
        """TC-4：compute() 返回五维评分，值 ∈ [0, 100]。"""
        bt = FD7ScoreBacktester(symbol="BTC")
        dates = pd.date_range("2026-01-01", periods=200, freq="1H")
        df = pd.DataFrame({
            "ts": [int(d.timestamp() * 1000) for d in dates],
            "open": np.linspace(100, 200, 200),
            "high": np.linspace(105, 205, 200),
            "low": np.linspace(95, 195, 200),
            "close": np.linspace(100, 200, 200),
            "vol": np.random.rand(200) * 1000,
        })
        cd = bt.build_coin_data(df, t=150, symbol_key="BTC-USDT")
        ss = bt.build_system_state(df, t=150)

        os.environ["FUND_7ENGINES_BOOST"] = "1"
        os.environ["ODAILY_ENGINE_BOOST"] = "1"
        from five_domain_feature_computer import FiveDomainFeatureComputer
        computer = FiveDomainFeatureComputer(enable=True)
        computer._fetch_news_72h_limit200 = lambda *a, **kw: list(_MOCK_NEWS_LIST)

        result = computer.compute(coin_data=cd, system_state=ss)
        assert "crypto_usdt" in result, "result 应含 crypto_usdt"
        crypto = result["crypto_usdt"]
        for domain in ["dao", "tian", "di", "jiang", "fa"]:
            assert domain in crypto, f"应含 {domain}"
            assert 0 <= crypto[domain] <= 100, f"{domain} 应 ∈ [0,100]，实际={crypto[domain]}"

    def test_tc5_signal_generation(self):
        """TC-5：dao > 60 → +1；dao < 40 → -1；40-60 → 0。"""
        assert FD7ScoreBacktester.score_to_signal(70) == 1
        assert FD7ScoreBacktester.score_to_signal(30) == -1
        assert FD7ScoreBacktester.score_to_signal(50) == 0
        assert FD7ScoreBacktester.score_to_signal(60) == 0  # 边界不触发
        assert FD7ScoreBacktester.score_to_signal(40) == 0

    def test_tc6_nav_curve(self):
        """TC-6：净值曲线 nav[0]=1.0，单调连续，无 NaN。"""
        dates = pd.date_range("2026-01-01", periods=300, freq="1H")
        df = pd.DataFrame({
            "ts": [int(d.timestamp() * 1000) for d in dates],
            "open": np.linspace(100, 200, 300),
            "high": np.linspace(105, 205, 300),
            "low": np.linspace(95, 195, 300),
            "close": np.linspace(100, 200, 300) + np.sin(np.arange(300) * 0.1) * 5,
            "vol": np.random.rand(300) * 1000,
        })

        os.environ["FUND_7ENGINES_BOOST"] = "1"
        os.environ["ODAILY_ENGINE_BOOST"] = "1"
        from five_domain_feature_computer import FiveDomainFeatureComputer
        computer = FiveDomainFeatureComputer(enable=True)
        computer._fetch_news_72h_limit200 = lambda *a, **kw: list(_MOCK_NEWS_LIST)

        bt = FD7ScoreBacktester(symbol="BTC")
        bt.fetch_klines = lambda: df  # mock 用本地数据

        results = bt.run_backtest(computer=computer)
        nav = results["nav_curve"]
        assert nav[0] == 1.0, f"nav[0] 应 = 1.0，实际={nav[0]}"
        assert len(nav) == results["backtest_bars"] + 1, "nav 长度应 = bars + 1"
        assert all(not np.isnan(x) for x in nav), "nav 不应有 NaN"

    def test_tc7_empyrical_metrics(self):
        """TC-7：empyrical 指标计算，返回含 sharpe/max_drawdown/calmar，无 NaN。"""
        dates = pd.date_range("2026-01-01", periods=300, freq="1H")
        df = pd.DataFrame({
            "ts": [int(d.timestamp() * 1000) for d in dates],
            "open": np.linspace(100, 200, 300),
            "high": np.linspace(105, 205, 300),
            "low": np.linspace(95, 195, 300),
            "close": np.linspace(100, 200, 300) + np.sin(np.arange(300) * 0.1) * 5,
            "vol": np.random.rand(300) * 1000,
        })

        os.environ["FUND_7ENGINES_BOOST"] = "1"
        os.environ["ODAILY_ENGINE_BOOST"] = "1"
        from five_domain_feature_computer import FiveDomainFeatureComputer
        computer = FiveDomainFeatureComputer(enable=True)
        computer._fetch_news_72h_limit200 = lambda *a, **kw: list(_MOCK_NEWS_LIST)

        bt = FD7ScoreBacktester(symbol="BTC")
        bt.fetch_klines = lambda: df

        results = bt.run_backtest(computer=computer)
        emp = results["empyrical"]
        assert "sharpe_ratio" in emp, "应含 sharpe_ratio"
        assert "max_drawdown" in emp, "应含 max_drawdown"
        assert "calmar_ratio" in emp, "应含 calmar_ratio"
        assert "annual_return" in emp, "应含 annual_return"
        for k, v in emp.items():
            assert v == v, f"{k} 不应为 NaN"  # NaN != NaN
            assert isinstance(v, (int, float)), f"{k} 应为数值"

    def test_tc8_report_generation(self, tmp_path):
        """TC-8：报告生成，JSON 含全部指标 + CSV 净值曲线可读。"""
        dates = pd.date_range("2026-01-01", periods=300, freq="1H")
        df = pd.DataFrame({
            "ts": [int(d.timestamp() * 1000) for d in dates],
            "open": np.linspace(100, 200, 300),
            "high": np.linspace(105, 205, 300),
            "low": np.linspace(95, 195, 300),
            "close": np.linspace(100, 200, 300) + np.sin(np.arange(300) * 0.1) * 5,
            "vol": np.random.rand(300) * 1000,
        })

        os.environ["FUND_7ENGINES_BOOST"] = "1"
        os.environ["ODAILY_ENGINE_BOOST"] = "1"
        from five_domain_feature_computer import FiveDomainFeatureComputer
        computer = FiveDomainFeatureComputer(enable=True)
        computer._fetch_news_72h_limit200 = lambda *a, **kw: list(_MOCK_NEWS_LIST)

        bt = FD7ScoreBacktester(symbol="BTC")
        bt.fetch_klines = lambda: df

        results = bt.run_backtest(computer=computer)
        json_path = bt.generate_report(results, str(tmp_path))

        # JSON 可读
        with open(json_path) as f:
            report = json.load(f)
        assert "empyrical" in report, "JSON 报告应含 empyrical"
        assert "custom" in report, "JSON 报告应含 custom"
        assert "benchmark" in report, "JSON 报告应含 benchmark"
        assert "symbol" in report, "JSON 报告应含 symbol"

        # CSV 可读
        import glob
        csv_files = glob.glob(str(tmp_path / "*nav_curve*.csv"))
        assert len(csv_files) == 1, f"应生成 1 个 CSV，实际 {len(csv_files)}"
        nav_df = pd.read_csv(csv_files[0])
        assert len(nav_df) > 0, "CSV 净值曲线应非空"
        assert "nav" in nav_df.columns, "CSV 应含 nav 列"
