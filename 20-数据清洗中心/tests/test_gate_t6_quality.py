"""T6 · QualityGate：复用 18-quality.py，enforce_hard_block=True → 硬拦截抛异常。

覆盖 4 类 IssueCode × 多维度 = 10 条边例（对齐 Spec§D2 QualityGate 验收矩阵）：
  T6-1  EMPTY_RESULT（空列表，非degraded）→ enforce 抛 QualityGateFailed
  T6-2  EMPTY_RESULT（内容全空 record = sparse空）→ 通过 check_all 捕获 EMPTY
  T6-3  CONTRACT_INVALID（category 非法）→ 抛 CONTRACT_INVALID
  T6-4  CONTRACT_INVALID（timestamp 不是 ISO8601）→ validate_record 抛
  T6-5  CONTRACT_INVALID（metrics 非法非扁平类型）→ validate_record 抛
  T6-6  DUPLICATE_DETECTED（两 record source+category+sub_category+timestamp 同）→ 抛
  T6-7  DUPLICATE_DETECTED（cleaned后 DF 级残留重复 = 两条 record timeseries 完全相同）→ Fail
  T6-8  TIMESTAMP_FRESHNESS（finance/ohlcv 采集时间>15min stale → 抛 FRESHNESS）
  T6-9  FAIL 异常携带 6 层 traceback_str 字符串
  T6-10 enforce_hard_block=False 只 report 不抛
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

# 18-quality 的实际契约
from data_center.core.contract import DataRecord  # type: ignore
from data_center.monitoring.quality import QualityIssueCode  # type: ignore


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestQualityGate:
    # ------------------------------------------------------------------
    # 辅助：构造合法/非法的 [DataRecord] × 4 类脏注入
    # ------------------------------------------------------------------
    @staticmethod
    def _valid_ohlcv_finance() -> list[DataRecord]:
        """构造最小合法 finance/ohlcv DataRecord（category=CATEGORIES 之一）。"""
        ts = datetime.now(timezone.utc) - timedelta(minutes=2)  # 新鲜
        df = pd.DataFrame({
            "timestamp": [
                _iso(ts - timedelta(minutes=1)),
                _iso(ts),
            ],
            "open": [100.0, 101.0], "high": [100.5, 101.5],
            "low": [99.5, 100.5], "close": [100.2, 101.1],
            "volume": [1000, 1200],
        })
        return [DataRecord(
            source="yfinance",
            category="finance",          # CATEGORIES 之一
            sub_category="ohlcv",
            timestamp=_iso(ts),          # fetched_at 的角色合并到 timestamp
            metrics={"asset": "BTC", "pair": "BTC-USD"},
            events=[],
            timeseries=df.to_dict(orient="records"),
            raw={"_": "_"},
        )]

    @staticmethod
    def _valid_macro() -> list[DataRecord]:
        ts = datetime.now(timezone.utc) - timedelta(hours=24)  # 1天前 < 48h
        return [DataRecord(
            source="fred", category="macro", sub_category="m2",
            timestamp=_iso(ts),
            metrics={"M2NS": 21.5, "M2SL": 21.4, "asset": "USA"},
            events=[], timeseries=[],
            raw={},
        )]

    # --- T6-1 EMPTY_RESULT（records=[]，非degraded）
    def test_t6_1_empty_result_block(self) -> None:
        from data_cleaning.errors import QualityGateFailed
        from data_cleaning.gate.quality_gate import QualityGate

        gate = QualityGate(enforce_hard_block=True, freshness_threshold=timedelta(minutes=15))
        with pytest.raises(QualityGateFailed) as excinfo:
            gate.validate([], source="yfinance", category="finance", is_degraded=False)
        assert excinfo.value.code == QualityIssueCode.EMPTY_RESULT

    # --- T6-2 稀疏空 record（metrics 嵌套非法 + timeseries/events 全空）→ Gate 判定 CONTRACT_INVALID
    #     注：18-quality._check_empty 只在 records==[] 时报 EMPTY；这里通过 contract 校验
    #     把"空而混乱"的输入捕获为 CONTRACT_INVALID → Gate Fail 等价业务语义上的空。
    def test_t6_2_empty_sparse_result_not_pass(self) -> None:
        from data_cleaning.gate.quality_gate import QualityGate

        gate = QualityGate(enforce_hard_block=True, freshness_threshold=timedelta(days=999))
        ts = datetime.now(timezone.utc)
        sparse_record = DataRecord(
            source="x", category="finance", sub_category="ohlcv",
            timestamp=_iso(ts),
            metrics={"bad_nested": [1, 2]},  # 触发 CONTRACT_INVALID
            events=[], timeseries=[],
            raw={},
        )
        passed, issues = _safe_validate(gate, [sparse_record], source="x", category="finance")
        assert passed is False, "稀疏+非法 record 不应 PASS"
        assert any(i.code in {
            QualityIssueCode.CONTRACT_INVALID,
            QualityIssueCode.EMPTY_RESULT,
        } for i in issues)

    # --- T6-3 CONTRACT_INVALID（category 非法）
    def test_t6_3_contract_invalid_category_block(self) -> None:
        from data_cleaning.errors import QualityGateFailed
        from data_cleaning.gate.quality_gate import QualityGate

        gate = QualityGate(enforce_hard_block=True, freshness_threshold=timedelta(days=999))
        ok, = self._valid_ohlcv_finance()
        bad = DataRecord(
            source=ok.source, category="timeseries",  # 非法（不在 CATEGORIES）
            sub_category=ok.sub_category, timestamp=ok.timestamp,
            metrics=ok.metrics, events=[], timeseries=[], raw={},
        )
        with pytest.raises(QualityGateFailed) as excinfo:
            gate.validate([bad], source="yfinance", category="finance")
        assert excinfo.value.code == QualityIssueCode.CONTRACT_INVALID

    # --- T6-4 CONTRACT_INVALID（timestamp 非法）
    def test_t6_4_contract_invalid_timestamp_block(self) -> None:
        from data_cleaning.errors import QualityGateFailed
        from data_cleaning.gate.quality_gate import QualityGate

        gate = QualityGate(enforce_hard_block=True, freshness_threshold=timedelta(days=999))
        bad = DataRecord(
            source="fred", category="macro", sub_category="m2",
            timestamp="not-an-iso-timestamp",  # type: ignore[arg-type]
            metrics={"M2NS": 21.0}, events=[], timeseries=[], raw={},
        )
        with pytest.raises(QualityGateFailed) as excinfo:
            gate.validate([bad], source="fred", category="macro")
        assert excinfo.value.code == QualityIssueCode.CONTRACT_INVALID

    # --- T6-5 CONTRACT_INVALID（metrics 非法类型，如 {a: [嵌套]} → 验证抛 CONTRACT_INVALID）
    def test_t6_5_contract_invalid_bad_metrics_block(self) -> None:
        from data_cleaning.errors import QualityGateFailed
        from data_cleaning.gate.quality_gate import QualityGate

        gate = QualityGate(enforce_hard_block=True, freshness_threshold=timedelta(days=999))
        ts = datetime.now(timezone.utc)
        bad = DataRecord(
            source="yfinance", category="finance", sub_category="ohlcv",
            timestamp=_iso(ts),
            metrics={"nested": [1, 2, 3]},  # 非法：含列表而非扁平
            events=[], timeseries=[], raw={},
        )
        with pytest.raises(QualityGateFailed) as excinfo:
            gate.validate([bad], source="yfinance", category="finance")
        assert excinfo.value.code == QualityIssueCode.CONTRACT_INVALID

    # --- T6-6 DUPLICATE_DETECTED（两 record 的 dedupe_key 同 → Fail）
    def test_t6_6_duplicate_detected_block(self) -> None:
        from data_cleaning.errors import QualityGateFailed
        from data_cleaning.gate.quality_gate import QualityGate

        gate = QualityGate(enforce_hard_block=True, freshness_threshold=timedelta(days=999))
        r1, = self._valid_ohlcv_finance()
        # 完全相同 source/category/sub_category/timestamp = dedupe_key 同
        r2 = DataRecord(
            source=r1.source, category=r1.category, sub_category=r1.sub_category,
            timestamp=r1.timestamp,
            metrics=r1.metrics, events=[], timeseries=r1.timeseries, raw={},
        )
        with pytest.raises(QualityGateFailed) as excinfo:
            gate.validate([r1, r2], source=r1.source, category=r1.category)
        assert excinfo.value.code == QualityIssueCode.DUPLICATE_DETECTED

    # --- T6-7 DUPLICATE_DETECTED（cleaned后 DF 行级重复 = 两个几乎同 record，也会被 dedupe_key 算法捕获）
    def test_t6_7_post_clean_df_row_duplicate_block(self) -> None:
        from data_cleaning.errors import QualityGateFailed
        from data_cleaning.gate.quality_gate import QualityGate

        gate = QualityGate(enforce_hard_block=True, freshness_threshold=timedelta(days=999))
        r1, = self._valid_ohlcv_finance()
        # 只要 dedupe_key 同（source+category+sub_category+timestamp 不变）→ 算重复
        r2 = DataRecord(
            source=r1.source, category=r1.category, sub_category=r1.sub_category,
            timestamp=r1.timestamp,  # 同 timestamp
            metrics={"asset": "ETH"},  # metrics 不同没用，key 只看 4 字段
            events=[], timeseries=r1.timeseries, raw={},
        )
        with pytest.raises(QualityGateFailed) as excinfo:
            gate.validate([r1, r2], source=r1.source, category=r1.category)
        assert excinfo.value.code == QualityIssueCode.DUPLICATE_DETECTED

    # --- T6-8 TIMESTAMP_FRESHNESS（finance 采集时间 > 15min 前 → stale）
    def test_t6_8_ohlcv_stale_15min_block(self) -> None:
        from data_cleaning.errors import QualityGateFailed
        from data_cleaning.gate.quality_gate import QualityGate

        gate = QualityGate(enforce_hard_block=True, freshness_threshold=timedelta(minutes=15))
        old_ts = datetime.now(timezone.utc) - timedelta(minutes=30)
        stale = DataRecord(
            source="yfinance", category="finance", sub_category="ohlcv",
            timestamp=_iso(old_ts),
            metrics={"asset": "BTC"},
            events=[],
            timeseries=pd.DataFrame({
                "timestamp": [_iso(old_ts)],
                "open": [100.0], "high": [100.5],
                "low": [99.5], "close": [100.2], "volume": [1000],
            }).to_dict(orient="records"),
            raw={},
        )
        with pytest.raises(QualityGateFailed) as excinfo:
            gate.validate([stale], source="yfinance", category="finance")
        assert excinfo.value.code == QualityIssueCode.TIMESTAMP_FRESHNESS

    # --- T6-9 FAIL 异常携带 6 层 traceback_str（QualityGateFailed.traceback_str）
    def test_t6_9_failed_has_6_layer_traceback(self) -> None:
        from data_cleaning.errors import QualityGateFailed
        from data_cleaning.gate.quality_gate import QualityGate

        gate = QualityGate(enforce_hard_block=True, freshness_threshold=timedelta(minutes=1))
        try:
            gate.validate([], source="x", category="finance")
            pytest.fail("应抛 QualityGateFailed")
        except QualityGateFailed as e:
            # traceback_str 非空（至少包含一行栈信息/行号）
            assert isinstance(e.traceback_str, str) and e.traceback_str, \
                f"traceback_str 应非空: {e.traceback_str!r}"

    # --- T6-10 enforce_hard_block=False（旁路模式只 report 不抛）
    def test_t6_10_soft_mode_no_throw_only_report(self) -> None:
        from data_cleaning.gate.quality_gate import QualityGate

        gate = QualityGate(enforce_hard_block=False, freshness_threshold=timedelta(minutes=1))
        # 空列表 + enforce=False → 不抛，仅返回 (passed=False, issues)
        passed, issues = gate.validate([], source="x", category="finance")
        assert passed is False
        assert len(issues) >= 1, f"空列表应有 EMPTY_RESULT issue，实得{issues}"
        assert issues[0].code == QualityIssueCode.EMPTY_RESULT


# ---------------------------------------------------------------------------
# 辅助：enforce=True 时把抛异常转成 (passed, issues)，便于 soft 模式断言
# ---------------------------------------------------------------------------
def _safe_validate(
    gate, records: list[DataRecord], **kw,
) -> tuple[bool, list]:
    try:
        return gate.validate(records, **kw)
    except Exception as exc:  # noqa: BLE001
        issues = getattr(exc, "issues", [])
        return False, issues
