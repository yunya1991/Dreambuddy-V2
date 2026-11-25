"""signal_calibration_metrics：d_star 口径 / ri / ESS 方向 / 放量门槛 的导出测试。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from exporter.business_metrics_exporter import Collector  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def test_signal_calibration_metrics(tmp_path: Path) -> None:
    runtime = tmp_path / "23-四层闭环自进化交易架构/runtime"
    runtime.mkdir(parents=True)
    ts = _now_iso()
    rows = [
        {
            "ts": ts,
            "stage": "N4",
            "symbol": "BTC-USDT-SWAP",
            "data": {
                "d_star_original": "neutral",
                "d_star_shadow": {
                    "d_star_calibrated": "long",
                    "wait_mode": "calibrated",
                    "wait_margin": 0.3,
                },
            },
        },
        {
            "ts": ts,
            "stage": "N4",
            "symbol": "ETH-USDT-SWAP",
            "data": {
                "d_star_original": "neutral",
                "d_star_shadow": {"d_star_calibrated": "WAIT", "wait_mode": "calibrated"},
            },
        },
        {
            "ts": ts,
            "stage": "N9",
            "symbol": "BTC-USDT-SWAP",
            "data": {
                "ri": 0.5,
                "tier": "probe",
                "ess_top_direction": "",
                "vol_threshold": 1.93,
                "reflection_ri": 0.5,
                "reflection_eligible": False,
            },
        },
        {
            "ts": ts,
            "stage": "N9",
            "symbol": "SOL-USDT-SWAP",
            "data": {
                "ri": 0.62,
                "tier": "standard",
                "ess_top_direction": "long",
                "vol_threshold": 2.61,
                "reflection_ri": 0.55,
                "reflection_eligible": True,
            },
        },
    ]
    (runtime / "chain_events-20261118.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    collector = Collector(tmp_path, BASE / "config/monitoring.yaml", BASE / "config/domains.yaml")
    text = "\n".join(collector.signal_calibration_metrics())

    assert "dreambuddy_dstar_calibrated_enabled 1" in text
    assert 'dreambuddy_dstar_wait_mode{mode="calibrated"} 1' in text
    assert "dreambuddy_dstar_calibrated_wait_1h 1" in text
    assert "dreambuddy_dstar_calibrated_trade_1h 1" in text
    assert "dreambuddy_dstar_calibrated_flip_1h 2" in text
    assert "dreambuddy_ri_neutral_1h 1" in text
    assert "dreambuddy_ess_direction_empty_1h 1" in text
    assert "dreambuddy_reflection_eligible_1h 1" in text
    assert "dreambuddy_reflection_ri_max 0.55" in text
    assert 'dreambuddy_ri_value{symbol="SOL"} 0.62' in text
    assert 'dreambuddy_ripple_vol_threshold{symbol="BTC"} 1.93' in text


def test_reflexivity_observability_metrics(tmp_path: Path) -> None:
    """N2 反射性分项 → r_reflexivity / distinct_24h / sentiment / spread / liq_term 指标。"""
    runtime = tmp_path / "23-四层闭环自进化交易架构/runtime"
    runtime.mkdir(parents=True)
    ts = _now_iso()
    rows = [
        {
            "ts": ts,
            "stage": "N2",
            "symbol": "BTC-USDT-SWAP",
            "data": {
                "R_reflexivity": 0.65,
                "r_inputs": {
                    "news_sentiment_score": 1.0,
                    "bid_ask_spread_bps": None,
                    "refl_components": {"corr_term": 0.5, "liq_term": 0.5, "sent_term": 1.0},
                },
            },
        },
        {
            "ts": ts,
            "stage": "N2",
            "symbol": "BTC-USDT-SWAP",
            "data": {
                "R_reflexivity": 0.65,
                "r_inputs": {
                    "news_sentiment_score": 1.0,
                    "bid_ask_spread_bps": None,
                    "refl_components": {"corr_term": 0.5, "liq_term": 0.5, "sent_term": 1.0},
                },
            },
        },
        {
            "ts": ts,
            "stage": "N2",
            "symbol": "ETH-USDT-SWAP",
            "data": {
                "R_reflexivity": 0.61,
                "r_inputs": {
                    "news_sentiment_score": 0.7,
                    "bid_ask_spread_bps": 3.0,
                    "refl_components": {"corr_term": 0.5, "liq_term": 0.94, "sent_term": 0.7},
                },
            },
        },
    ]
    (runtime / "chain_events-20261125.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    collector = Collector(tmp_path, BASE / "config/monitoring.yaml", BASE / "config/domains.yaml")
    text = "\n".join(collector.signal_calibration_metrics())

    assert 'dreambuddy_r_reflexivity{symbol="BTC"} 0.65' in text
    # BTC 两条完全同值 → 24h 去重值数 = 1（恒定告警依据）
    assert 'dreambuddy_r_reflexivity_distinct_24h{symbol="BTC"} 1' in text
    assert 'dreambuddy_r_reflexivity_distinct_24h{symbol="ETH"} 1' in text
    assert 'dreambuddy_r_refl_sentiment_score{symbol="BTC"} 1.0' in text
    assert 'dreambuddy_r_refl_liq_term{symbol="ETH"} 0.94' in text
    # BTC spread 缺失 → 不导出该 symbol 的 spread 指标
    assert 'dreambuddy_r_refl_spread_bps{symbol="BTC"}' not in text
    assert 'dreambuddy_r_refl_spread_bps{symbol="ETH"} 3.0' in text


def test_reflexivity_distinct_covers_full_24h_beyond_tail(tmp_path: Path) -> None:
    """distinct_24h 必须覆盖完整 24h，不能被 _tail_jsonl 的 512KB 尾部截断压成几分钟窗口。"""
    runtime = tmp_path / "23-四层闭环自进化交易架构/runtime"
    runtime.mkdir(parents=True)
    now = datetime.now(timezone.utc)

    def _iso(hours_ago: float) -> str:
        return (now - __import__("datetime").timedelta(hours=hours_ago)).isoformat()

    def _n2(value: float, hours_ago: float) -> str:
        return json.dumps(
            {
                "ts": _iso(hours_ago),
                "stage": "N2",
                "symbol": "CL-USDT-SWAP",
                "data": {"R_reflexivity": value},
            },
            ensure_ascii=False,
        )

    # 6h 前的 N2 值 + 中间 >512KB 填充 + 最近的 N2 值（尾部截断只能看到后者）
    filler = "\n".join(
        json.dumps(
            {"ts": _iso(5), "stage": "N1", "symbol": "CL-USDT-SWAP", "data": {"pad": "x" * 200}}
        )
        for _ in range(3000)
    )
    content = "\n".join([_n2(0.40, 6), filler, _n2(0.60, 1)]) + "\n"
    (runtime / "chain_events-20261125.jsonl").write_text(content, encoding="utf-8")

    collector = Collector(tmp_path, BASE / "config/monitoring.yaml", BASE / "config/domains.yaml")
    text = "\n".join(collector.signal_calibration_metrics())

    assert 'dreambuddy_r_reflexivity_distinct_24h{symbol="CL"} 2' in text


def test_reflexivity_isolates_stale_formula(tmp_path: Path) -> None:
    """v2 生效后：停更的 legacy-only symbol 不再导出（消除恒 1 假告警），混合 symbol 只按 v2 去重。"""
    runtime = tmp_path / "23-四层闭环自进化交易架构/runtime"
    runtime.mkdir(parents=True)
    now = datetime.now(timezone.utc)

    def _iso(hours_ago: float) -> str:
        return (now - __import__("datetime").timedelta(hours=hours_ago)).isoformat()

    def _row(symbol: str, value: float, hours_ago: float, formula: str | None) -> dict:
        data: dict = {"R_reflexivity": value}
        if formula is not None:
            data["r_inputs"] = {"refl_components": {"formula": formula, "corr_term": 0.5}}
        return {"ts": _iso(hours_ago), "stage": "N2", "symbol": symbol, "data": data}

    rows = [
        _row("COIN-USDT-SWAP", 0.65, 8, None),  # 切换前停更的 legacy-only symbol
        _row("LTC-USDT-SWAP", 0.51, 10, "v2"),  # 停更的 v2 symbol（同一值、仅 1 个样本）
        _row("BTC-USDT-SWAP", 0.65, 3, None),  # 混合：切换前的 legacy 样本
        _row("BTC-USDT-SWAP", 0.50, 2, "v2"),
        _row("CL-USDT-SWAP", 0.52, 1, "v2"),
    ]
    (runtime / "chain_events-20261125.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    collector = Collector(tmp_path, BASE / "config/monitoring.yaml", BASE / "config/domains.yaml")
    text = "\n".join(collector.signal_calibration_metrics())

    # 停更 symbol 不再产生恒值序列 → ReflexivityConstant 不再误报
    assert 'dreambuddy_r_reflexivity{symbol="COIN"}' not in text
    assert 'dreambuddy_r_reflexivity_distinct_24h{symbol="COIN"}' not in text
    # 停更的 v2 symbol 同样不导出（新鲜度门槛 3h）
    assert 'dreambuddy_r_reflexivity{symbol="LTC"}' not in text
    assert 'dreambuddy_r_reflexivity_distinct_24h{symbol="LTC"}' not in text
    # 混合 symbol 只按当前口径（v2）去重，legacy 0.65 不计入
    assert 'dreambuddy_r_reflexivity{symbol="BTC"} 0.5' in text
    assert 'dreambuddy_r_reflexivity_distinct_24h{symbol="BTC"} 1' in text
    assert 'dreambuddy_r_reflexivity_distinct_24h{symbol="CL"} 1' in text
