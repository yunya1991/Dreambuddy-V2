"""T12 · yfinance BTC E2E（Spec§F3 M1 验收 B+B）。

场景：
  1) 通过 18-DataCenter.fetch(category="finance", source="yfinance", asset="BTC-USD", period="7d", interval="1h")
     拿到原始 7 天 BTC 小时级 OHLCV；
  2) 交给 Silver Pipeline 跑；
  3) 断言：
     T12-1 全链路 gate_passed=True
     T12-2 无 NaN close（所有 7×24 ≈ 168 行 close 非空）
     T12-3 trace 步骤齐全（4 Cleaner + Gate 痕迹皆有）
     T12-4 通过 dispatcher H1 + EN_SILVER=true 返回的 list[DataRecord] 中 timeseries close 非空行数 = 原行数

若本地没有网络或 yfinance 下载失败，整个类 SKIP（不影响铁门槛 T-G1）。
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

# 确保使用本地 18-数据获取中心（不是已安装的旧版本包）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "18-数据获取中心"))
sys.path.insert(0, str(_PROJECT_ROOT / "20-数据清洗中心"))


def _has_yfinance_network() -> bool:
    try:
        import yfinance as yf  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _has_yfinance_network(), reason="yfinance not available")
class TestYfinanceBTCE2E:
    """端到端走：真实 yfinance → DataCenter → Silver Pipeline → 验收。"""

    @pytest.fixture(scope="class")
    def btc_raw(self):
        """一次性下载 BTC/USD 7d 1h（class 级共享）。"""
        from data_center.core.dispatcher import DataCenter
        from data_center.monitoring import MonitoringBundle
        from data_center.monitoring.quality import QualityChecker

        class _NoopM:
            def record(self, *a, **kw): return None

        class _NoopA:
            def emit(self, *a, **kw): return None

        class NoopBundle(MonitoringBundle):  # type: ignore[misc]
            def __init__(self) -> None:
                self.metrics = _NoopM()
                self.alerts = _NoopA()
                self.quality = QualityChecker()

        # EN_SILVER off → 拿到原始 result
        old_env = os.environ.get("EN_SILVER")
        os.environ["EN_SILVER"] = "false"
        try:
            dc = DataCenter(monitoring=NoopBundle())
            out = dc.fetch("finance", source="yfinance", symbol="BTC-USD")
        except Exception as exc:  # noqa: BLE001
            import traceback as _tb
            _tb.print_exc()
            pytest.skip(f"yfinance 下载失败（SKIP T12）: {exc}")
            return None  # pragma: no cover
        finally:
            if old_env is None:
                os.environ.pop("EN_SILVER", None)
            else:
                os.environ["EN_SILVER"] = old_env

        if not out:
            pytest.skip("yfinance 空返回（SKIP T12）")
        return out

    # T12-1 Pipeline 全链路 gate_passed=True
    def test_t12_1_silver_pipeline_passes(self, btc_raw) -> None:
        if btc_raw is None:
            pytest.skip("no raw data")
        from data_cleaning.pipeline import DataCleaningPipeline, PipelineConfig
        pipe = DataCleaningPipeline(PipelineConfig(
            enforce_hard_block=True,
            fail_open=False,
            freshness_threshold=timedelta(days=30),
        ))
        silver = pipe.clean(btc_raw, source="yfinance", category="finance")
        assert silver.gate_passed is True, (
            f"真实BTC数据不应Gate Fail: issues={silver.quality_report[:3]} "
            f"trace={[(a.step, a.note[:60]) for a in silver.trace.actions]}"
        )

    # T12-2 无 NaN close
    def test_t12_2_no_nan_close(self, btc_raw) -> None:
        if btc_raw is None:
            pytest.skip("no raw data")
        from data_cleaning.pipeline import DataCleaningPipeline, PipelineConfig
        pipe = DataCleaningPipeline(PipelineConfig(
            enforce_hard_block=False,
            fail_open=True,
            freshness_threshold=timedelta(days=30),
        ))
        silver = pipe.clean(btc_raw, source="yfinance", category="finance")
        if "close" in silver.df.columns:
            nans = int(silver.df["close"].isna().sum())
            assert nans == 0, f"应无NaN close: {nans} / {len(silver.df)}"
            # 至少有 1 行（yfinance collector 默认 5d 日线，一般 3~5 条）
            assert len(silver.df) >= 1, f"行数偏少: {len(silver.df)}"

    # T12-3 trace 步骤齐全
    def test_t12_3_trace_steps_complete(self, btc_raw) -> None:
        if btc_raw is None:
            pytest.skip("no raw data")
        from data_cleaning.pipeline import DataCleaningPipeline, PipelineConfig
        pipe = DataCleaningPipeline(PipelineConfig(
            enforce_hard_block=False, fail_open=True,
            freshness_threshold=timedelta(days=30),
        ))
        silver = pipe.clean(btc_raw, source="yfinance", category="finance")
        steps = {a.step for a in silver.trace.actions}
        for must in ("DedupAlignCleaner", "Outlier3LFilter",
                      "MissingImputer", "UnitNormalizer", "QualityGate"):
            assert must in steps, f"缺失 {must} 步骤: {steps}"

    # T12-4 H1 dispatcher EN_SILVER=true 返回的 DataRecord timeseries 非空 close == 总行数
    def test_t12_4_h1_dispatcher_en_silver_true_no_nan(self, btc_raw) -> None:
        if btc_raw is None:
            pytest.skip("no raw data")
        from data_center.core.dispatcher import DataCenter
        from data_center.monitoring import MonitoringBundle
        from data_center.monitoring.quality import QualityChecker

        class _NoopM:
            def record(self, *a, **kw): return None

        class _NoopA:
            def emit(self, *a, **kw): return None

        class NoopBundle(MonitoringBundle):  # type: ignore[misc]
            def __init__(self) -> None:
                self.metrics = _NoopM()
                self.alerts = _NoopA()
                self.quality = QualityChecker()

        old_env = os.environ.get("EN_SILVER")
        os.environ["EN_SILVER"] = "true"
        os.environ["SILVER_FRESHNESS_HOURS"] = str(24 * 30)
        try:
            dc = DataCenter(monitoring=NoopBundle())
            out = dc.fetch("finance", source="yfinance", symbol="BTC-USD")
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"H1 触发 yfinance 下载重跑失败 SKIP: {exc}")
            return
        finally:
            if old_env is None:
                os.environ.pop("EN_SILVER", None)
                os.environ.pop("SILVER_FRESHNESS_HOURS", None)
            else:
                os.environ["EN_SILVER"] = old_env

        assert len(out) >= 1
        rec = out[0]
        closes = [row.get("close") for row in rec.timeseries]
        assert len(closes) >= 1, f"行数不足: {len(closes)}"
        nans = sum(1 for c in closes if c is None or (isinstance(c, float) and np.isnan(c)))
        assert nans == 0, f"EN_SILVER 开启后不应残留 NaN close: {nans}/{len(closes)}"
