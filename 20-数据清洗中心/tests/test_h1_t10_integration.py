"""T10 · H1 集成：18-DataCenter dispatcher 的 Silver 中间件注入 + EN_SILVER Flag。

3条边例（Spec§E3 H1 最小侵入点）：
  T10-1 EN_SILVER=True（默认）→ DataCenter.fetch() 返回的 list[DataRecord] 内部已跑过 DedupAlignCleaner
          （去重后 unique_rows >= 原数 <= 原数；并且 trace 记录存在于监控或 metadata 中——此处用 fetch 的副作用：
          trace 被写入 MonitoringBundle，或者直接：我们让 EN_SILVER 走后 DataRecord 里 timeseries 不再有 NaN）
  T10-2 EN_SILVER=False（旁路）→ 输出与改造前字节等价（不触发任何 Cleaner 痕迹，无 EN_SILVER trace）
  T10-3 EN_SILVER=True + fail_open → 即使 DataCleaningPipeline 抛异常，也不会向上冒泡（fail-open）
          （用 monkey-patch DataCleaningPipeline.clean 抛 RuntimeError 验证）
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from data_center.core.contract import DataRecord  # type: ignore


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mk_fresh_btc_ohlcv(n: int = 6) -> list[DataRecord]:
    ts = datetime.now(timezone.utc) - timedelta(minutes=3)
    rows = pd.date_range(ts - timedelta(hours=n - 1), periods=n, freq="1h")
    return [DataRecord(
        source="yfinance", category="finance", sub_category="ohlcv",
        timestamp=_iso(ts),
        metrics={"asset": "BTC"},
        events=[],
        timeseries=pd.DataFrame({
            "timestamp": [_iso(t) for t in rows],
            "close": [100.0, None, 102.0, None, 104.0, 105.0][:n],
            "volume": [10, 20, 30, 40, 50, 60][:n],
        }).to_dict(orient="records"),
        raw={},
    )]


class TestH1Integration:
    """通过 dispatcher.DataCenter.fetch 的中间件行为测试 EN_SILVER。

    为了避免真实 collector 访问网络，这里直接构造一个"fake collector"通过 registry 注册。
    """

    @pytest.fixture
    def _reg(self):
        from data_center.core.registry import Registry
        reg = Registry()

        class FakeCollector:
            config: dict

            def __init__(self, config: dict | None = None) -> None:
                self.config = config or {}

            def fetch(self, params: dict) -> list[DataRecord]:
                n = int(params.get("n", 6))
                return _mk_fresh_btc_ohlcv(n)

        reg.register("finance", "fakebtc", FakeCollector)
        return reg

    # T10-1 EN_SILVER=True → timeseries close 不再有 NaN（已被 DedupAlign+MissingImputer 处理）
    def test_t10_1_en_silver_true_closes_have_no_nan(self, _reg) -> None:
        from data_center.core.dispatcher import DataCenter

        old_env = os.environ.get("EN_SILVER")
        os.environ["EN_SILVER"] = "true"
        try:
            # 构造真正跑通的 Noop monitoring bundle（不触网）
            from data_center.monitoring import MonitoringBundle

            class _NoopMetrics:
                def record(self, *a, **kw): return None

            class _NoopAlerts:
                def emit(self, *a, **kw): return None

            from data_center.monitoring.quality import QualityChecker

            class NoopBundle(MonitoringBundle):  # type: ignore[misc]
                def __init__(self) -> None:
                    self.metrics = _NoopMetrics()
                    self.alerts = _NoopAlerts()
                    self.quality = QualityChecker()

            dc = DataCenter(registry=_reg, monitoring=NoopBundle())
            out = dc.fetch("finance", source="fakebtc", n=6)
            assert len(out) == 1
            closes = [row.get("close") for row in out[0].timeseries]
            assert len(closes) >= 5, f"行数不足: {len(closes)}"
            # 不应有 None / NaN
            nans = sum(1 for c in closes if c is None or (isinstance(c, float) and pd.isna(c)))
            assert nans == 0, f"EN_SILVER 开启时不应残留 NaN close: {closes}"
        finally:
            if old_env is None:
                os.environ.pop("EN_SILVER", None)
                os.environ.pop("SILVER_FRESHNESS_HOURS", None)
            else:
                os.environ["EN_SILVER"] = old_env

    # T10-2 EN_SILVER=False（旁路）→ 不做任何清洗；原 NaN 应该还在
    def test_t10_2_en_silver_off_bypass(self, _reg) -> None:
        from data_center.core.dispatcher import DataCenter
        from data_center.monitoring import MonitoringBundle
        from data_center.monitoring.quality import QualityChecker

        class _NoopMetrics:
            def record(self, *a, **kw): return None

        class _NoopAlerts:
            def emit(self, *a, **kw): return None

        class NoopBundle(MonitoringBundle):  # type: ignore[misc]
            def __init__(self) -> None:
                self.metrics = _NoopMetrics()
                self.alerts = _NoopAlerts()
                self.quality = QualityChecker()

        old_env = os.environ.get("EN_SILVER")
        os.environ["EN_SILVER"] = "false"
        try:
            dc = DataCenter(registry=_reg, monitoring=NoopBundle())
            out = dc.fetch("finance", source="fakebtc", n=6)
            closes = [row.get("close") for row in out[0].timeseries]
            nans = sum(1 for c in closes if c is None or (isinstance(c, float) and pd.isna(c)))
            # 旁路模式：原始 NaN 还在
            assert nans >= 2, f"EN_SILVER off 旁路失败（应保留原 NaN）：closes={closes}"
        finally:
            if old_env is None:
                os.environ.pop("EN_SILVER", None)
            else:
                os.environ["EN_SILVER"] = old_env

    # T10-3 EN_SILVER=True + fail_open=True（默认）：pipeline 抛 RuntimeError 不应冒泡
    def test_t10_3_en_silver_fail_open_no_raise(self, _reg) -> None:
        from data_center.core.dispatcher import DataCenter
        from data_center.monitoring import MonitoringBundle
        from data_center.monitoring.quality import QualityChecker

        class _NoopMetrics:
            def record(self, *a, **kw): return None

        class _NoopAlerts:
            def emit(self, *a, **kw): return None

        import data_cleaning.pipeline as sil_pipe

        orig_clean = sil_pipe.DataCleaningPipeline.clean

        def boom(self, records, **kw):  # noqa: D401
            raise RuntimeError("network partition, silver pipeline crashed")

        sil_pipe.DataCleaningPipeline.clean = boom  # type: ignore[assignment]

        class NoopBundle(MonitoringBundle):  # type: ignore[misc]
            def __init__(self) -> None:
                self.metrics = _NoopMetrics()
                self.alerts = _NoopAlerts()
                self.quality = QualityChecker()

        old_env = os.environ.get("EN_SILVER")
        os.environ["EN_SILVER"] = "true"
        os.environ["SILVER_FAIL_OPEN"] = "true"
        try:
            dc = DataCenter(registry=_reg, monitoring=NoopBundle())
            out = dc.fetch("finance", source="fakebtc", n=6)
            # fail-open：原 records 兜底返回，不是 None，且能还原
            assert isinstance(out, list) and len(out) == 1
            closes = [row.get("close") for row in out[0].timeseries]
            assert len(closes) == 6
        finally:
            sil_pipe.DataCleaningPipeline.clean = orig_clean  # type: ignore[assignment]
            if old_env is None:
                os.environ.pop("EN_SILVER", None)
                os.environ.pop("SILVER_FAIL_OPEN", None)
            else:
                os.environ["EN_SILVER"] = old_env
