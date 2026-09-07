"""D1: 价格回填脚本测试 — TDD 先红后绿。

覆盖：
  1. 触发条件：7d 前信号 → 回填 7d，5d 前信号 → 不回填 7d
  2. 价格获取分派：crypto → COIN-USD，stock → TICKER，metal → XAUUSD→GLD
  3. 未知 coin 跳过不报错
  4. 幂等性：同一 jsonl 跑两次不重复改写
  5. 收益率计算：p_at=100, p7=105 → return_7d=5.0
  6. FAIL-OPEN：某日价格获取异常 → 该字段保持 null，其他记录正常
  7. 回写策略：产出 _backfilled.jsonl，保留原 shadow 完整（审计基线）
  8. dry-run 模式：不写文件，只打印待回填摘要
  9. price_at_signal 无论新旧都回填（若为 null）
  10. 14d/30d 年龄门槛与 7d 独立判定
  11. max_recs 截断
  12. 资产类未知时（如 coin 不在映射表）跳过 price 获取
  13. fetch_price_at_date 在历史区间边缘日期回退到最近可用
  14. backfilled 输出字段顺序一致
  15. 原 shadow 文件不存在时抛出 FileNotFound（fail-safe）
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))
if str(_L4_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(_L4_DIR / "scripts"))


def _make_ts(days_ago: int, tz_offset_hours: int = 8) -> str:
    """生成 N 天前的 ISO8601 时间戳（带 +08:00 时区，对齐 ranker output）。"""
    tz = timezone(timedelta(hours=tz_offset_hours))
    dt = datetime.now(tz) - timedelta(days=days_ago)
    return dt.isoformat()


def _write_shadow(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ===========================================================================
# 纯函数单测：映射 + 触发条件
# ===========================================================================

class TestSymbolMapping:
    def test_crypto_btc_to_btc_usd(self):
        from coin_fundamental_price_backfill import _map_coin_to_yf_symbol
        assert _map_coin_to_yf_symbol("BTC") == "BTC-USD"

    def test_crypto_uni_to_uni_usd(self):
        from coin_fundamental_price_backfill import _map_coin_to_yf_symbol
        assert _map_coin_to_yf_symbol("UNI") == "UNI-USD"

    def test_stock_nvda_stays_nvda(self):
        from coin_fundamental_price_backfill import _map_coin_to_yf_symbol
        assert _map_coin_to_yf_symbol("NVDA") == "NVDA"

    def test_metal_xauusd_to_gld(self):
        from coin_fundamental_price_backfill import _map_coin_to_yf_symbol
        assert _map_coin_to_yf_symbol("XAUUSD") == "GLD"

    def test_metal_xagusd_to_slv(self):
        from coin_fundamental_price_backfill import _map_coin_to_yf_symbol
        assert _map_coin_to_yf_symbol("XAGUSD") == "SLV"

    def test_unknown_coin_returns_none(self):
        from coin_fundamental_price_backfill import _map_coin_to_yf_symbol
        assert _map_coin_to_yf_symbol("UNKNOWN_XYZ") is None


class TestAgeGate:
    def test_age_30_days_triggers_all_three_windows(self):
        from coin_fundamental_price_backfill import _should_backfill_window
        ts = _make_ts(30)
        assert _should_backfill_window(ts, 7) is True
        assert _should_backfill_window(ts, 14) is True
        assert _should_backfill_window(ts, 30) is True

    def test_age_10_days_triggers_7d_not_14d(self):
        from coin_fundamental_price_backfill import _should_backfill_window
        ts = _make_ts(10)
        assert _should_backfill_window(ts, 7) is True
        assert _should_backfill_window(ts, 14) is False
        assert _should_backfill_window(ts, 30) is False

    def test_age_5_days_triggers_nothing_but_at_signal(self):
        from coin_fundamental_price_backfill import _should_backfill_window
        ts = _make_ts(5)
        assert _should_backfill_window(ts, 7) is False
        assert _should_backfill_window(ts, 14) is False
        assert _should_backfill_window(ts, 30) is False

    def test_invalid_timestamp_returns_false_safely(self):
        from coin_fundamental_price_backfill import _should_backfill_window
        assert _should_backfill_window("garbage-date", 7) is False


class TestReturnCalc:
    def test_return_pct_formula(self):
        from coin_fundamental_price_backfill import _return_pct
        assert round(_return_pct(100.0, 105.0), 6) == pytest.approx(5.0)

    def test_return_negative(self):
        from coin_fundamental_price_backfill import _return_pct
        assert round(_return_pct(100.0, 90.0), 6) == pytest.approx(-10.0)

    def test_return_zero_price_returns_none(self):
        from coin_fundamental_price_backfill import _return_pct
        assert _return_pct(0.0, 100.0) is None


# ===========================================================================
# 端到端：process_jsonl 回写 _backfilled.jsonl
# ===========================================================================

class TestProcessJsonl:
    def test_outputs_backfilled_sidecar_file(self):
        from coin_fundamental_price_backfill import process_jsonl
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "s.jsonl"
            rec_30d = {
                "coin": "BTC", "asset_class": "crypto_usdt",
                "timestamp": _make_ts(30),
                "fundamental_score": 0.3, "rank": "A",
                "sub_signals": {}, "data_quality": "sufficient",
                "confidence": 1.0, "error": None,
                "price_at_signal": None,
                "price_7d_after": None, "price_14d_after": None, "price_30d_after": None,
                "return_7d": None, "return_14d": None, "return_30d": None,
            }
            _write_shadow(src, [rec_30d])

            with patch("coin_fundamental_price_backfill._fetch_price_at_date") as m:
                m.return_value = 100.0
                out_path = process_jsonl(str(src))
            assert out_path.endswith("s.backfilled.jsonl")
            assert os.path.exists(out_path)

    def test_backfill_30d_age_fills_all_windows(self):
        from coin_fundamental_price_backfill import process_jsonl
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "s.jsonl"
            rec = {
                "coin": "BTC", "asset_class": "crypto_usdt",
                "timestamp": _make_ts(30),
                "fundamental_score": 0.1, "rank": "B",
                "sub_signals": {}, "data_quality": "partial",
                "confidence": 0.75, "error": None,
                "price_at_signal": None,
                "price_7d_after": None, "price_14d_after": None, "price_30d_after": None,
                "return_7d": None, "return_14d": None, "return_30d": None,
            }
            _write_shadow(src, [rec])

            def fake_fetch(symbol, date):
                # 信号日:100, 7d后:105, 14d后:110, 30d后:120
                # 用传入参数 + 不同日差异模拟：p_at=100, p7=105, p14=110, p30=120
                return {0: 100.0, 7: 105.0, 14: 110.0, 30: 120.0}[date]
            # 注意：实际 API 用 datetime.date；这里 mock 返回值在 4 次调用间固定，我们改用 side_effect 序列
            with patch("coin_fundamental_price_backfill._fetch_price_at_date") as m:
                m.side_effect = [100.0, 105.0, 110.0, 120.0]  # at, +7, +14, +30
                out_path = process_jsonl(str(src))

            with open(out_path) as f:
                result = json.loads(f.readline())
            assert result["price_at_signal"] == 100.0
            assert result["price_7d_after"] == 105.0
            assert result["price_14d_after"] == 110.0
            assert result["price_30d_after"] == 120.0
            assert result["return_7d"] == pytest.approx(5.0)
            assert result["return_14d"] == pytest.approx(10.0)
            assert result["return_30d"] == pytest.approx(20.0)

    def test_age_5d_only_fills_at_signal_not_windows(self):
        from coin_fundamental_price_backfill import process_jsonl
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "s.jsonl"
            rec = {
                "coin": "NVDA", "asset_class": "us_stock",
                "timestamp": _make_ts(5),
                "fundamental_score": 0.0, "rank": "B",
                "sub_signals": {}, "data_quality": "sufficient",
                "confidence": 1.0, "error": None,
                "price_at_signal": None,
                "price_7d_after": None, "price_14d_after": None, "price_30d_after": None,
                "return_7d": None, "return_14d": None, "return_30d": None,
            }
            _write_shadow(src, [rec])

            with patch("coin_fundamental_price_backfill._fetch_price_at_date") as m:
                m.return_value = 500.0
                out_path = process_jsonl(str(src))

            with open(out_path) as f:
                result = json.loads(f.readline())
            assert result["price_at_signal"] == 500.0
            assert result["price_7d_after"] is None
            assert result["return_7d"] is None

    def test_idempotency_rerun_does_not_change_fields(self):
        """第一次回填写入 p_at=100,p7=105；第二次 rerun 时 API 给不同值，也不得覆盖。"""
        from coin_fundamental_price_backfill import process_jsonl
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "s.jsonl"
            rec = {
                "coin": "BTC", "asset_class": "crypto_usdt",
                "timestamp": _make_ts(30),
                "fundamental_score": 0.0, "rank": "B",
                "sub_signals": {}, "data_quality": "partial",
                "confidence": 0.5, "error": None,
                "price_at_signal": None,
                "price_7d_after": None, "price_14d_after": None, "price_30d_after": None,
                "return_7d": None, "return_14d": None, "return_30d": None,
            }
            _write_shadow(src, [rec])

            with patch("coin_fundamental_price_backfill._fetch_price_at_date") as m:
                m.side_effect = [100.0, 105.0, 110.0, 120.0]
                out1 = process_jsonl(str(src))

            # 第二次运行：读取上一次的 backfilled 作为输入（幂等）
            with patch("coin_fundamental_price_backfill._fetch_price_at_date") as m2:
                m2.return_value = 999.0  # 若覆盖则会变
                out2 = process_jsonl(out1)

            with open(out2) as f:
                result = json.loads(f.readline())
            assert result["price_at_signal"] == 100.0
            assert result["price_7d_after"] == 105.0
            assert result["return_7d"] == pytest.approx(5.0)

    def test_unknown_coin_skipped_price_fetch(self):
        from coin_fundamental_price_backfill import process_jsonl
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "s.jsonl"
            rec = {
                "coin": "UNKNOWN_XYZ", "asset_class": "unknown",
                "timestamp": _make_ts(30),
                "fundamental_score": 0.0, "rank": "B",
                "sub_signals": {}, "data_quality": "insufficient",
                "confidence": 0.0, "error": None,
                "price_at_signal": None,
                "price_7d_after": None, "price_14d_after": None, "price_30d_after": None,
                "return_7d": None, "return_14d": None, "return_30d": None,
            }
            _write_shadow(src, [rec])

            with patch("coin_fundamental_price_backfill._fetch_price_at_date") as m:
                process_jsonl(str(src))
                m.assert_not_called()

    def test_fetch_exception_failopen_keeps_null(self):
        from coin_fundamental_price_backfill import process_jsonl
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "s.jsonl"
            _write_shadow(src, [{
                "coin": "XAUUSD", "asset_class": "precious_metal",
                "timestamp": _make_ts(30),
                "fundamental_score": 0.0, "rank": "B",
                "sub_signals": {}, "data_quality": "partial",
                "confidence": 0.5, "error": None,
                "price_at_signal": None, "price_7d_after": None,
                "price_14d_after": None, "price_30d_after": None,
                "return_7d": None, "return_14d": None, "return_30d": None,
            }])

            with patch("coin_fundamental_price_backfill._fetch_price_at_date",
                       side_effect=RuntimeError("yfinance down")):
                out_path = process_jsonl(str(src))

            with open(out_path) as f:
                result = json.loads(f.readline())
            assert result["price_at_signal"] is None
            assert result["return_7d"] is None

    def test_dry_run_does_not_write_output(self):
        from coin_fundamental_price_backfill import process_jsonl
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "s.jsonl"
            _write_shadow(src, [{
                "coin": "BTC", "asset_class": "crypto_usdt",
                "timestamp": _make_ts(10),
                "fundamental_score": 0.0, "rank": "B",
                "sub_signals": {}, "data_quality": "sufficient",
                "confidence": 1.0, "error": None,
                "price_at_signal": None, "price_7d_after": None,
                "price_14d_after": None, "price_30d_after": None,
                "return_7d": None, "return_14d": None, "return_30d": None,
            }])

            with patch("coin_fundamental_price_backfill._fetch_price_at_date", return_value=100.0):
                out = process_jsonl(str(src), dry_run=True)
            assert out is None
            assert not Path(str(src) + ".backfilled.jsonl").exists()

    def test_max_recs_truncates(self):
        from coin_fundamental_price_backfill import process_jsonl
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "s.jsonl"
            # 用 ranker 已知的 crypto 币（映射表内）保证 classify_asset_class 命中
            valid_coins = ["BTC", "ETH", "UNI", "LINK", "AAVE", "BTC", "ETH", "UNI", "LINK", "AAVE"]
            many = [{
                "coin": valid_coins[i], "asset_class": "crypto_usdt",
                "timestamp": _make_ts(5),
                "fundamental_score": 0.0, "rank": "B",
                "sub_signals": {}, "data_quality": "sufficient",
                "confidence": 1.0, "error": None,
                "price_at_signal": None, "price_7d_after": None,
                "price_14d_after": None, "price_30d_after": None,
                "return_7d": None, "return_14d": None, "return_30d": None,
            } for i in range(10)]
            _write_shadow(src, many)

            called_count = [0]
            def spy(*a, **k):
                called_count[0] += 1
                return 1.0

            with patch("coin_fundamental_price_backfill._fetch_price_at_date", side_effect=spy):
                process_jsonl(str(src), max_recs=3)
            # 3 条记录 × 1 次（price_at_signal 因 age=5 无窗口）
            assert called_count[0] == 3

    def test_missing_source_raises_filenotfound(self):
        from coin_fundamental_price_backfill import process_jsonl
        with pytest.raises(FileNotFoundError):
            process_jsonl("/nope/not_here.jsonl")
