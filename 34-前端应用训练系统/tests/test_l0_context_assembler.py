# -*- coding: utf-8 -*-
"""T-DSH-P0 C3: 六维上下文信封组装器测试（RED）。

依据: SPEC-EVENT-DRIVEN-L1-GATEWAY v0.2 §三.1 任务4 + 认知 VM-1792148857896
(L0 统一信封铁律: 源不可用=degraded(reason),源可达无数据=ok+data=None)。
验收:
  - 六维齐全: market/skill/knowledge/experience/cases/rea
  - 信封铁律: 逐维保留 L0 子信封语义,degraded(reason) 不得改写成 ok(None),
    ok(None) 不得改写成 degraded
  - L0 访问 in-process 优先(同进程调 fetch_context);L0 异常→该维 degraded,不抛错
  - 未配置 scope 的维 → degraded(scope_unconfigured),不调 L0
  - FAIL-OPEN: l0=None / 坏 trigger → 仍返回信封,不抛错
  - trace_id 透传(E2E 全链一致)
  - 零 token(HC-4): 模块不得 import 生成式 LLM 依赖
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.l0_context_assembler import (  # noqa: E402
    SIX_DIMS,
    build_six_dim_context,
)


def _trigger(**kw):
    base = {
        "trigger_id": "T-1",
        "source": "timer",
        "kind": "health_alert",
        "payload_ref": "p/1",
        "ts": 1000.0,
    }
    base.update(kw)
    return base


def _ok(data):
    return {
        "ok": True,
        "data": data,
        "source": "fake",
        "timestamp": "2026-11-03T00:00:00",
        "degraded": False,
        "meta": {},
    }


def _degraded(reason):
    return {
        "ok": False,
        "data": None,
        "source": "fake",
        "timestamp": "2026-11-03T00:00:00",
        "degraded": True,
        "meta": {"reason": reason},
    }


class FakeL0:
    """记录调用并按 scope 返回预置信封。"""

    def __init__(self, responses=None, raise_on=None):
        self.responses = responses or {}
        self.raise_on = raise_on or set()
        self.calls = []

    def fetch_context(self, scope, params=None):
        self.calls.append((scope, params or {}))
        if scope in self.raise_on:
            raise RuntimeError("boom")
        return self.responses.get(scope, _ok({"scope": scope}))


class TestSixDims:
    def test_all_six_dims_present(self):
        env = build_six_dim_context(_trigger(), l0=FakeL0())
        assert set(SIX_DIMS) == {"market", "skill", "knowledge", "experience", "cases", "rea"}
        dims = env["data"]["six_dims"]
        assert set(dims.keys()) == set(SIX_DIMS)

    def test_trigger_embedded(self):
        env = build_six_dim_context(_trigger(), l0=FakeL0())
        assert env["data"]["trigger"]["trigger_id"] == "T-1"
        assert env["data"]["trigger"]["kind"] == "health_alert"

    def test_trace_id_passthrough(self):
        env = build_six_dim_context(_trigger(), l0=FakeL0(), trace_id="tr-abc")
        assert env["data"]["trace_id"] == "tr-abc"


class TestEnvelopeIronRule:
    def test_degraded_reason_preserved(self):
        l0 = FakeL0(responses={"market.ticker": _degraded("upstream_unavailable")})
        env = build_six_dim_context(_trigger(), l0=l0)
        dim = env["data"]["six_dims"]["market"]
        assert dim["degraded"] is True
        assert dim["meta"]["reason"] == "upstream_unavailable"
        assert dim["ok"] is False
        # 铁律: degraded 不得被改写成 ok+None
        assert not (dim["ok"] is True and dim["data"] is None)

    def test_ok_none_not_rewritten_as_degraded(self):
        l0 = FakeL0(responses={"market.ticker": _ok(None)})
        env = build_six_dim_context(_trigger(), l0=l0)
        dim = env["data"]["six_dims"]["market"]
        assert dim["ok"] is True
        assert dim["degraded"] is False
        assert dim["data"] is None  # 源可达无数据 ≠ 源不可用

    def test_l0_exception_dim_degraded_no_raise(self):
        l0 = FakeL0(raise_on={"market.ticker"})
        env = build_six_dim_context(_trigger(), l0=l0)
        dim = env["data"]["six_dims"]["market"]
        assert dim["degraded"] is True
        assert dim["meta"]["reason"] == "fetch_error"

    def test_unconfigured_dims_not_fetched(self):
        l0 = FakeL0()
        env = build_six_dim_context(_trigger(), l0=l0)
        for dim_name in ("skill", "cases", "rea"):
            dim = env["data"]["six_dims"][dim_name]
            assert dim["degraded"] is True
            assert dim["meta"]["reason"] == "scope_unconfigured"
        # 未配置的维不得调用 L0
        fetched_scopes = {s for s, _ in l0.calls}
        assert "docs.search" in fetched_scopes
        assert "cognitive.recall" in fetched_scopes
        assert len(l0.calls) == 3  # market + knowledge + experience

    def test_top_level_degraded_only_when_all_dims_degraded(self):
        env_all_bad = build_six_dim_context(_trigger(), l0=None)
        assert env_all_bad["degraded"] is True
        assert env_all_bad["ok"] is False
        env_partial = build_six_dim_context(_trigger(), l0=FakeL0())
        assert env_partial["degraded"] is False
        assert env_partial["ok"] is True


class TestParamsPropagation:
    def test_experience_context_mentions_kind(self):
        l0 = FakeL0()
        build_six_dim_context(_trigger(kind="service_down", source="cloud"), l0=l0)
        params = dict(l0.calls)["cognitive.recall"]
        assert "service_down" in params["context"]
        assert "cloud" in params["context"]

    def test_knowledge_query_mentions_kind(self):
        l0 = FakeL0()
        build_six_dim_context(_trigger(kind="timer_missed"), l0=l0)
        params = dict(l0.calls)["docs.search"]
        assert "timer_missed" in params["query"]


class TestFailOpen:
    def test_l0_none_all_dims_degraded(self):
        env = build_six_dim_context(_trigger(), l0=None)
        for dim in env["data"]["six_dims"].values():
            assert dim["degraded"] is True
            assert dim["meta"]["reason"] == "l0_unavailable"

    def test_bad_trigger_no_raise(self):
        env = build_six_dim_context(None, l0=FakeL0())
        assert env["degraded"] is True
        assert env["meta"]["reason"] == "invalid_trigger"

    def test_bad_l0_object_no_raise(self):
        env = build_six_dim_context(_trigger(), l0=object())
        for dim in env["data"]["six_dims"].values():
            assert dim["degraded"] is True


class TestZeroToken:
    def test_no_llm_imports(self):
        path = os.path.join(os.path.dirname(__file__), "..", "core", "l0_context_assembler.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                for bad in ("openai", "anthropic", "litellm", "langchain"):
                    assert bad not in stripped
