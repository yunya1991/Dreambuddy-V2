#!/usr/bin/env python3
"""RuminationEngine 单测（P2-7 静息态反刍）"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from rumination_engine import RuminationEngine, RuminationFinding


def _write_episode(dir_path: Path, ts: str, coin: str, regime: str, direction: str, pnl_pct: float):
    ep = {
        "ts": ts, "inst_id": f"{coin}-USDT-SWAP", "coin": coin,
        "regime": regime, "direction": direction, "pnl_pct": pnl_pct,
    }
    fname = f"live_{coin}_{ts.replace(':', '').replace('-', '').replace('+', '')}.json"
    (dir_path / fname).write_text(json.dumps(ep), encoding="utf-8")


def test_ruminate_finds_deviation():
    """偏离基线≥15% 的组产出 finding"""
    with tempfile.TemporaryDirectory() as d:
        ep_dir = Path(d)
        now = datetime.now(timezone.utc)
        # BTC ranging LONG 4笔全亏（胜率0%，远低于基线）
        for i in range(4):
            _write_episode(ep_dir, (now - timedelta(days=i)).isoformat(),
                           "BTC", "ranging", "LONG", -1.0)
        # ETH trending SHORT 4笔全赢（胜率100%，远高于基线）
        for i in range(4):
            _write_episode(ep_dir, (now - timedelta(days=i)).isoformat(),
                           "ETH", "trending", "SHORT", 1.0)

        engine = RuminationEngine()
        findings = engine.ruminate(str(ep_dir), lookback_days=7)
        keys = [f.pattern_key for f in findings]
        assert "BTC|ranging|LONG" in keys
        assert "ETH|trending|SHORT" in keys


def test_ruminate_filters_small_sample():
    """样本<3 的组不产出 finding"""
    with tempfile.TemporaryDirectory() as d:
        ep_dir = Path(d)
        now = datetime.now(timezone.utc)
        _write_episode(ep_dir, now.isoformat(), "BTC", "ranging", "LONG", -1.0)
        _write_episode(ep_dir, now.isoformat(), "BTC", "ranging", "LONG", -1.0)

        engine = RuminationEngine()
        findings = engine.ruminate(str(ep_dir), lookback_days=7)
        assert len(findings) == 0


def test_ruminate_empty_dir():
    """空目录返回空列表"""
    with tempfile.TemporaryDirectory() as d:
        engine = RuminationEngine()
        findings = engine.ruminate(d, lookback_days=7)
        assert findings == []


def test_ruminate_filters_small_deviation():
    """偏离<15% 不产出 finding"""
    with tempfile.TemporaryDirectory() as d:
        ep_dir = Path(d)
        now = datetime.now(timezone.utc)
        # 8 笔 BTC ranging LONG：4 赢 4 输 = 50% 胜率，基线也 50%，偏离≈0
        # 用不同小时偏移避免文件名冲突
        for i in range(4):
            _write_episode(ep_dir, (now - timedelta(days=i, hours=1)).isoformat(),
                           "BTC", "ranging", "LONG", 1.0)
        for i in range(4):
            _write_episode(ep_dir, (now - timedelta(days=i, hours=2)).isoformat(),
                           "BTC", "ranging", "LONG", -1.0)

        engine = RuminationEngine()
        findings = engine.ruminate(str(ep_dir), lookback_days=7)
        assert len(findings) == 0


def test_finding_text_format():
    """finding_text 含币种/regime/方向/胜率/样本"""
    with tempfile.TemporaryDirectory() as d:
        ep_dir = Path(d)
        now = datetime.now(timezone.utc)
        for i in range(4):
            _write_episode(ep_dir, (now - timedelta(days=i)).isoformat(),
                           "BTC", "ranging", "LONG", -1.0)
        engine = RuminationEngine()
        findings = engine.ruminate(str(ep_dir), lookback_days=7)
        assert len(findings) == 1
        text = findings[0].finding_text
        assert "BTC" in text
        assert "ranging" in text
        assert "LONG" in text


if __name__ == "__main__":
    for fn in [
        test_ruminate_finds_deviation,
        test_ruminate_filters_small_sample,
        test_ruminate_empty_dir,
        test_ruminate_filters_small_deviation,
        test_finding_text_format,
    ]:
        try:
            fn()
            print(f"✅ {fn.__name__}")
        except AssertionError as e:
            print(f"❌ {fn.__name__}: {e}")
            raise
