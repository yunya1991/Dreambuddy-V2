"""Research Prepass 测试：citation 映射、源降级、脱敏、代码检索。"""
from core import research
from core.research import collect_research, redact


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def close(self):
        pass

    def call(self, tool, arguments=None):
        if tool == "unified_search":
            return {
                "ok": True,
                "data": {
                    "hits": [
                        {"text": "SPEC-49 双决策链", "source": "chroma", "score": 0.9,
                         "ref": "doc-1", "meta": {"path": "49-交易框架协议/SPEC.md"}},
                        {"text": "重复引用", "source": "chroma", "score": 0.8,
                         "ref": "doc-1", "meta": {"path": "49-交易框架协议/SPEC.md"}},
                    ],
                    "degraded_sources": [],
                },
            }
        if tool == "recall":
            return {
                "ok": True,
                "data": {"memories": [{"id": "VM-1", "content": "历史决策", "score": 0.7}]},
            }
        if tool == "get_signal_state":
            return {
                "ok": True,
                "data": {
                    "available": True,
                    "path": "23_signal_state.json",
                    "fallback": False,
                    "signal": {
                        "signal_id": "sig-1",
                        "source": "23-evolution",
                        "symbol": "BTC-USDT-SWAP",
                        "direction": "long",
                        "confidence": 0.72,
                        "horizon": "hours",
                        "mode": "live",
                        "expires_at": "2026-11-09T00:00:00Z",
                        "payload": {
                            "action": "long",
                            "position_tier": "standard",
                            "regime": "expansion",
                            "primary_contradiction": {
                                "dimension": "valuation",
                                "direction": "long",
                                "strength": 0.8,
                            },
                        },
                    },
                },
            }
        if tool == "get_bus_state":
            return {
                "ok": True,
                "data": {
                    "available": True,
                    "path": "42-神经网络交易协调层/runtime/bus_state.json",
                    "generated_at": "2026-11-08T00:00:00Z",
                    "sources": ["bdsm"],
                    "signal_count": 2,
                    "signals": [
                        {"symbol": "BTC", "source": "bdsm",
                         "direction": "long", "confidence": 0.7},
                        {"symbol": "ETH", "source": "bdsm",
                         "direction": "short", "confidence": 0.6},
                    ],
                },
            }
        if tool == "get_cycle_state":
            return {
                "ok": True,
                "data": {
                    "available": True,
                    "path": "40-周期神经网络系统/cycle_state.json",
                    "cycle": {
                        "generated_at": "2026-11-08T00:00:00Z",
                        "real_cycle": {"state": "plateau", "confidence": "high"},
                        "technical_anchor": {
                            "assets": {"BTC/USDT": {"above": True, "distance_pct": 9.5}}
                        },
                    },
                },
            }
        return {"ok": False, "data": {}}


def _fake_code(topic, limit):
    from core.research import Citation, SourceStat
    return (
        [Citation(source="code_search", ref="a.py:1", quote="secret sk-abcdefgh", line=1)],
        SourceStat("code_search", ok=True, count=1),
        "",
    )


def test_collect_research_citations(monkeypatch):
    monkeypatch.setattr(research, "MCPClient", FakeClient)
    monkeypatch.setattr(research, "_code_citations", _fake_code)
    brief = collect_research("双决策链", max_items=8)
    assert len(brief.citations) == 3  # unified dedup + recall + code
    assert brief.source_stats
    assert "<untrusted_source" in brief.brief
    refs = {c.ref for c in brief.citations}
    assert "49-交易框架协议/SPEC.md" in refs
    assert "VM-1" in refs
    assert "a.py:1" in refs
    assert "sk-abcdefgh" not in brief.to_dict()["citations"][2]["quote"]
    assert "[REDACTED]" in brief.to_dict()["citations"][2]["quote"]


def test_collect_research_all_empty_degraded(monkeypatch):
    class EmptyClient:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        def close(self):
            pass

        def call(self, tool, arguments=None):
            return {"ok": True, "data": {"hits": [], "memories": []}}

    monkeypatch.setattr(research, "MCPClient", EmptyClient)
    monkeypatch.setattr(research, "_code_citations", lambda t, l: (
        [], research.SourceStat("code_search", False, 0, True, "no_results"), "code_search:no_results"
    ))
    brief = collect_research("nothing", sources=["unified_search", "recall", "code"])
    assert brief.degraded is True
    assert brief.citations == []
    assert any("no_results" in e for e in brief.errors)


def test_signal_profile_includes_l1_citations(monkeypatch):
    monkeypatch.setattr(research, "MCPClient", FakeClient)
    monkeypatch.setattr(research, "_code_citations", lambda t, l: (
        [], research.SourceStat("code_search", False, 0, True, "no_results"),
        "code_search:no_results",
    ))
    brief = collect_research("BTC 信号", profile="signal", max_items=8)
    sources = {c.source for c in brief.citations}
    assert {"l1_signal", "l1_bus", "l1_cycle"} <= sources
    refs = {c.ref for c in brief.citations}
    assert "l1.signal:sig-1" in refs
    assert any(c.source == "l1_bus" and "bus_state.json" in c.ref
               for c in brief.citations)
    assert any(c.source == "l1_cycle" and "cycle_state.json" in c.ref
               for c in brief.citations)
    assert any(s.source == "l1_signal" and s.ok for s in brief.source_stats)
    assert "l1_signal" in brief.brief


def test_explicit_l1_sources_only(monkeypatch):
    monkeypatch.setattr(research, "MCPClient", FakeClient)
    brief = collect_research(
        "BTC 信号", sources=["l1_signal", "l1_cycle"], max_items=8,
    )
    assert {c.source for c in brief.citations} == {"l1_signal", "l1_cycle"}


def test_l1_unavailable_is_degraded_source(monkeypatch):
    class NoL1Client(FakeClient):
        def call(self, tool, arguments=None):
            if tool in ("get_signal_state", "get_bus_state", "get_cycle_state"):
                return {"ok": False, "data": {"available": False},
                        "error_code": "not_found"}
            return super().call(tool, arguments)

    monkeypatch.setattr(research, "MCPClient", NoL1Client)
    brief = collect_research("BTC 信号", sources=list(research.L1_SOURCES),
                             max_items=8)
    assert brief.citations == []
    assert brief.degraded is True
    assert all(s.degraded for s in brief.source_stats)


def test_redact_patterns():
    assert "sk-" not in redact("token sk-abcdefgh1234")
    assert "gho_" not in redact("gho_abcdefghijklmnopqrstuvwxyz")
    assert "AKIA" not in redact("AKIAABCDEFGHIJKLMNOP")
    assert "[REDACTED]" in redact("Bearer abc.def.ghi")