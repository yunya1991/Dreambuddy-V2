"""9 域 DataCollector 接通 19-DAL 的契约测试。

目标：所有直接使用 DataCollector 的调用方（backend / scripts / 其他域）
在 DAL 可用时拿到真实数据，DAL 不可用时 FAIL-OPEN 回退 legacy mock，
且两者都能被 `_dal_fallback` 明确区分（避免"看起来有数、其实是 mock"）。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data_collector as dc  # noqa: E402
from data_collector import DataCollector  # noqa: E402

MODULES = ("flow", "sentiment", "macro", "breadth", "valuation", "onchain", "intermarket")


class _StubProvider:
    def __init__(self, payload=None, raises=False):
        self.payload = payload
        self.raises = raises
        self.calls: list[str] = []

    def __getattr__(self, name):
        def _fn():
            self.calls.append(name)
            if self.raises:
                raise RuntimeError("dal boom")
            return self.payload

        return _fn


@pytest.fixture
def collector(monkeypatch):
    # legacy 一律替换为标记 dict，避免测试触网
    for m in MODULES:
        monkeypatch.setattr(
            DataCollector,
            f"_collect_{m}_legacy",
            lambda self, _m=m: {"legacy": _m, "meta": {"source": "legacy"}},
        )
    return DataCollector()


def test_dal_payload_is_preferred(collector, monkeypatch):
    payload = {"metrics": {"core": {"score": 61.2}}, "meta": {"source": "19-DAL"}}
    monkeypatch.setattr(dc, "_DAL_PROVIDER", _StubProvider(payload=payload))
    out = collector.collect_flow()
    assert out["metrics"]["core"]["score"] == 61.2
    assert out["_dal_fallback"] is False
    assert out["meta"]["dal_fallback"] is False
    assert "legacy" not in out


def test_dal_empty_falls_back_to_legacy(collector, monkeypatch):
    provider = _StubProvider(payload=None)
    monkeypatch.setattr(dc, "_DAL_PROVIDER", provider)
    out = collector.collect_macro()
    assert out["legacy"] == "macro"
    assert out["_dal_fallback"] is True
    assert out["meta"]["dal_fallback"] is True
    assert provider.calls == ["collect_macro"]


def test_dal_exception_falls_back(collector, monkeypatch):
    monkeypatch.setattr(dc, "_DAL_PROVIDER", _StubProvider(raises=True))
    out = collector.collect_onchain()
    assert out["legacy"] == "onchain"
    assert out["_dal_fallback"] is True


def test_provider_unavailable_falls_back(collector, monkeypatch):
    monkeypatch.setattr(dc, "_DAL_PROVIDER", False)
    out = collector.collect_valuation()
    assert out["legacy"] == "valuation"
    assert out["_dal_fallback"] is True


@pytest.mark.parametrize("module,method", sorted(dc._DAL_MODULE_METHOD.items()))
def test_every_module_routes_to_matching_dal_method(collector, monkeypatch, module, method):
    provider = _StubProvider(payload={"ok": module, "meta": {}})
    monkeypatch.setattr(dc, "_DAL_PROVIDER", provider)
    out = getattr(collector, f"collect_{module}")()
    assert out["ok"] == module
    assert out["_dal_fallback"] is False
    assert provider.calls == [method]
