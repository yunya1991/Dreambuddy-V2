"""21-特征工程中心 tests conftest.py — 为 test_resistance_features.py 提供 monkeypatch fixtures（fake_alerts / fake_sentiment_0）
与 4-MEMORY/tests/conftest.py 平行（pytest conftest 目录隔离规则）"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def fake_alerts(monkeypatch):
    """monkeypatch dreambuddy_core.alert_bridge.send_alert → FakeAlert 计数（TR-RV-08 5min3次触发≥1）"""
    class FakeAlert:
        counts: dict[str, int] = {"warn": 0, "critical": 0, "error": 0, "info": 0}
        last_messages: list[str] = []

        @classmethod
        def send(cls, level: str, message: str, **_kwargs):
            level_key = str(level).lower() if isinstance(level, str) else "warn"
            if level_key not in cls.counts:
                cls.counts[level_key] = 0
            cls.counts[level_key] += 1
            cls.last_messages.append(str(message)[:160])

    try:
        from dreambuddy_evolution import alert_bridge as ab
        monkeypatch.setattr(ab, "send_alert", FakeAlert.send, raising=False)
    except Exception:  # pragma: no cover — 如模块缺失（未来 refactor），Fixture 仍返回 FakeAlert 计数对象
        pass
    return FakeAlert


@pytest.fixture
def fake_sentiment_0(monkeypatch):
    """模拟 SentimentEngine USE_FINBERT=0 → FO-1：quality_score -0.15pp（TR-RV-06）
    通过 monkeypatch resistance_features._SENTIMENT_FO1_ACTIVE = True（resistance_features 每次 calculate 会读这个全局变量）。"""
    try:
        # 先注入 feature_hub 到 sys.path（否则 import resistance_features 找不到）
        hub = REPO_ROOT / "21-特征工程中心" / "feature_hub"
        if str(hub) not in sys.path:
            sys.path.insert(0, str(hub))
        import resistance_features as rf_mod  # noqa: E402
        monkeypatch.setattr(rf_mod, "_SENTIMENT_FO1_ACTIVE", True, raising=False)
    except Exception:
        pass

    class _FakeEngine:
        USE_FINBERT: int = 0

        def get_sentiment(self, *a, **kw) -> float:
            return 0.5  # L1 55:45 中性

    return _FakeEngine()
