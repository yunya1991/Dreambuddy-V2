# -*- coding: utf-8 -*-
"""T-DSH-P0 C1: 事件驱动 L1 网关测试（RED）。

依据: SPEC-EVENT-DRIVEN-L1-GATEWAY v0.2（46-DSH架构/docs/tech）。
验收(A1/A2/A4):
  - Trigger 契约: {trigger_id, source, kind, payload_ref, thread_id?, ts}
  - 规则过滤: 白名单 / 去重 / 冷却 / 价值阈值
  - 三分流: 命中事件意图→l1_close; 未命中+价值分≥阈值→escalate_l2; 低价值→silent
  - 批合并: 按 (thread_id, kind) 在窗口内合并(初值 2s)
  - shadow 模式: 决策照算、recorder 记录,但 effective_action=passthrough(不拦截)
  - FAIL-OPEN(HC-1): 任何异常→fallback(行为等价网关不存在,直落现有入口),不抛错
  - 开关 enable_event_l1_gateway 默认 False(HC-2)
  - 零 token(HC-4): 模块不得 import 生成式 LLM 依赖
纯函数+注入依赖(state/recorder 由调用方持有)。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.event_gateway import (  # noqa: E402
    ACTION_ESCALATE_L2,
    ACTION_FALLBACK,
    ACTION_L1_CLOSE,
    ACTION_SILENT,
    GATEWAY_SWITCH,
    GatewayState,
    is_gateway_enabled,
    load_event_intents,
    merge_batch,
    normalize_trigger,
    route_trigger,
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


class TestGatewaySwitch:
    def test_switch_name(self):
        assert GATEWAY_SWITCH == "enable_event_l1_gateway"

    def test_default_off(self):
        assert is_gateway_enabled() is False
        assert is_gateway_enabled({}) is False
        assert is_gateway_enabled(None) is False

    def test_enabled_when_flag_true(self):
        assert is_gateway_enabled({"enable_event_l1_gateway": True}) is True

    def test_non_dict_flags_fail_open(self):
        assert is_gateway_enabled("bad") is False
        assert is_gateway_enabled(123) is False


class TestNormalizeTrigger:
    def test_valid_minimal(self):
        t = normalize_trigger({"trigger_id": "T-1", "source": "timer", "kind": "k"})
        assert t["trigger_id"] == "T-1"
        assert t["source"] == "timer"
        assert t["kind"] == "k"
        assert t["payload_ref"] is None
        assert t["thread_id"] is None
        assert t["ts"] is not None  # 缺省补当前时间

    def test_full_contract(self):
        t = normalize_trigger(_trigger(thread_id="th-9"))
        assert t["thread_id"] == "th-9"
        assert t["payload_ref"] == "p/1"
        assert t["ts"] == 1000.0

    def test_missing_required_fields(self):
        assert normalize_trigger({"source": "s", "kind": "k"}) is None  # 缺 trigger_id
        assert normalize_trigger({"trigger_id": "T", "kind": "k"}) is None  # 缺 source
        assert normalize_trigger({"trigger_id": "T", "source": "s"}) is None  # 缺 kind

    def test_non_dict_fail_open(self):
        assert normalize_trigger(None) is None
        assert normalize_trigger("bad") is None
        assert normalize_trigger([1, 2]) is None


class TestRuleFilter:
    def test_whitelist_source_blocked(self):
        rules = {"whitelist": {"sources": ["timer"]}}
        d = route_trigger(_trigger(source="github"), rules=rules)
        assert d["action"] == ACTION_SILENT
        assert d["reason"] == "whitelist"

    def test_whitelist_kind_blocked(self):
        rules = {"whitelist": {"kinds": ["health_alert"]}}
        d = route_trigger(_trigger(kind="price_tick"), rules=rules)
        assert d["action"] == ACTION_SILENT
        assert d["reason"] == "whitelist"

    def test_whitelist_empty_means_no_limit(self):
        d = route_trigger(_trigger(), rules={"whitelist": {}})
        assert d["action"] != ACTION_SILENT or d["reason"] != "whitelist"

    def test_dedup_within_window(self):
        state = GatewayState()
        rules = {"dedup_window_sec": 300, "kind_value": {"health_alert": 0.9}}
        d1 = route_trigger(_trigger(), rules=rules, state=state, now=1000.0)
        assert d1["action"] == ACTION_ESCALATE_L2
        d2 = route_trigger(_trigger(), rules=rules, state=state, now=1100.0)
        assert d2["action"] == ACTION_SILENT
        assert d2["reason"] == "dedup"

    def test_dedup_after_window_passes(self):
        state = GatewayState()
        rules = {"dedup_window_sec": 300, "kind_value": {"health_alert": 0.9}}
        route_trigger(_trigger(), rules=rules, state=state, now=1000.0)
        d = route_trigger(_trigger(), rules=rules, state=state, now=1400.0)
        assert d["action"] == ACTION_ESCALATE_L2

    def test_cooldown_same_kind(self):
        state = GatewayState()
        rules = {
            "cooldown_sec": {"health_alert": 60},
            "kind_value": {"health_alert": 0.9},
        }
        d1 = route_trigger(_trigger(trigger_id="A"), rules=rules, state=state, now=1000.0)
        assert d1["action"] == ACTION_ESCALATE_L2
        d2 = route_trigger(_trigger(trigger_id="B"), rules=rules, state=state, now=1030.0)
        assert d2["action"] == ACTION_SILENT
        assert d2["reason"] == "cooldown"

    def test_cooldown_different_kind_not_blocked(self):
        state = GatewayState()
        rules = {
            "cooldown_sec": {"health_alert": 60},
            "kind_value": {"health_alert": 0.9, "job_done": 0.9},
        }
        route_trigger(_trigger(trigger_id="A"), rules=rules, state=state, now=1000.0)
        d = route_trigger(
            _trigger(trigger_id="B", kind="job_done"), rules=rules, state=state, now=1030.0
        )
        assert d["action"] == ACTION_ESCALATE_L2


class TestThreeWayRoute:
    def test_intent_hit_l1_close(self):
        intents = {"health_alert": "health_alert"}
        d = route_trigger(_trigger(), intents=intents)
        assert d["action"] == ACTION_L1_CLOSE
        assert d["intent_id"] == "health_alert"

    def test_miss_high_value_escalate(self):
        rules = {"value_threshold": 0.5, "kind_value": {"health_alert": 0.9}}
        d = route_trigger(_trigger(), rules=rules, intents={})
        assert d["action"] == ACTION_ESCALATE_L2
        assert d["value_score"] == 0.9

    def test_miss_low_value_silent(self):
        rules = {"value_threshold": 0.5, "kind_value": {"price_tick": 0.1}}
        d = route_trigger(_trigger(kind="price_tick"), rules=rules, intents={})
        assert d["action"] == ACTION_SILENT
        assert d["reason"] == "low_value"

    def test_default_value_escalates(self):
        # 未知 kind 默认价值分(0.5) ≥ 默认阈值(0.5) → 升级,保证不漏事件
        d = route_trigger(_trigger(kind="unknown_kind"))
        assert d["action"] == ACTION_ESCALATE_L2


class TestShadowMode:
    def test_shadow_records_but_passthrough(self):
        recorded = []
        d = route_trigger(
            _trigger(),
            intents={"health_alert": "health_alert"},
            shadow=True,
            recorder=recorded.append,
        )
        assert d["action"] == ACTION_L1_CLOSE  # 决策照算
        assert d["shadow"] is True
        assert d["effective_action"] == "passthrough"  # 不拦截
        assert len(recorded) == 1  # 已记录可审计

    def test_non_shadow_default_effective_equals_action(self):
        d = route_trigger(_trigger(), intents={"health_alert": "health_alert"})
        assert d["shadow"] is False
        assert d["effective_action"] == ACTION_L1_CLOSE


class TestFailOpen:
    def test_invalid_trigger_fallback(self):
        d = route_trigger({"bad": True})
        assert d["action"] == ACTION_FALLBACK
        assert d["shadow"] is False or "reason" in d

    def test_broken_rules_fallback(self):
        d = route_trigger(_trigger(), rules="not-a-dict")
        assert d["action"] == ACTION_FALLBACK

    def test_broken_state_fallback_but_no_raise(self):
        class BadState:
            def seen_recently(self, *a, **k):
                raise RuntimeError("boom")

        d = route_trigger(_trigger(), state=BadState(), rules={"dedup_window_sec": 1})
        assert d["action"] == ACTION_FALLBACK

    def test_recorder_error_swallowed(self):
        def bad_recorder(_):
            raise RuntimeError("boom")

        d = route_trigger(_trigger(), recorder=bad_recorder, shadow=True)
        assert d["effective_action"] == "passthrough"  # 记录失败不影响分流

    def test_none_inputs_no_raise(self):
        d = route_trigger(None, rules=None, intents=None, state=None)
        assert d["action"] == ACTION_FALLBACK


class TestMergeBatch:
    def test_merge_same_thread_kind_within_window(self):
        ts = [
            _trigger(trigger_id="A", thread_id="th1", ts=1000.0),
            _trigger(trigger_id="B", thread_id="th1", ts=1001.0),
        ]
        batches = merge_batch(ts, window_ms=2000)
        assert len(batches) == 1
        assert batches[0]["count"] == 2
        assert batches[0]["trigger_ids"] == ["A", "B"]
        assert batches[0]["kind"] == "health_alert"
        assert batches[0]["thread_id"] == "th1"

    def test_split_beyond_window(self):
        ts = [
            _trigger(trigger_id="A", thread_id="th1", ts=1000.0),
            _trigger(trigger_id="B", thread_id="th1", ts=1005.0),
        ]
        batches = merge_batch(ts, window_ms=2000)
        assert len(batches) == 2

    def test_different_kind_not_merged(self):
        ts = [
            _trigger(trigger_id="A", thread_id="th1", kind="k1", ts=1000.0),
            _trigger(trigger_id="B", thread_id="th1", kind="k2", ts=1000.5),
        ]
        assert len(merge_batch(ts, window_ms=2000)) == 2

    def test_different_thread_not_merged(self):
        ts = [
            _trigger(trigger_id="A", thread_id="th1", ts=1000.0),
            _trigger(trigger_id="B", thread_id="th2", ts=1000.5),
        ]
        assert len(merge_batch(ts, window_ms=2000)) == 2

    def test_no_thread_merges_by_kind(self):
        ts = [
            _trigger(trigger_id="A", ts=1000.0),
            _trigger(trigger_id="B", ts=1000.5),
        ]
        batches = merge_batch(ts, window_ms=2000)
        assert len(batches) == 1
        assert batches[0]["count"] == 2

    def test_merged_keeps_payload_refs(self):
        ts = [
            _trigger(trigger_id="A", thread_id="t", payload_ref="p/a", ts=1000.0),
            _trigger(trigger_id="B", thread_id="t", payload_ref="p/b", ts=1000.5),
        ]
        b = merge_batch(ts, window_ms=2000)[0]
        assert b["payload_refs"] == ["p/a", "p/b"]
        assert b["payload_ref"] == "p/a"  # 首个为代表

    def test_empty_and_bad_input(self):
        assert merge_batch([]) == []
        assert merge_batch(None) == []
        assert merge_batch("bad") == []


class TestEventIntentsContract:
    """C2: 事件意图契约文件(event_intents.yaml)加载与联通。"""

    def test_default_contract_loads_three_intents(self):
        mapping = load_event_intents()
        assert mapping["alert_confirm"] == "alert_confirm"
        assert mapping["event_triage"] == "event_triage"
        assert mapping["health_alert"] == "health_alert"

    def test_multi_kind_mapping(self):
        mapping = load_event_intents()
        # 一个意图可覆盖多个 kind(health_alert 覆盖服务/定时器健康事件)
        assert mapping["service_down"] == "health_alert"
        assert mapping["timer_missed"] == "health_alert"
        assert mapping["job_done"] == "event_triage"
        assert mapping["file_landed"] == "event_triage"

    def test_missing_file_fail_open(self):
        assert load_event_intents("/nonexistent/intents.yaml") == {}

    def test_bad_yaml_fail_open(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("intents: [{{{{", encoding="utf-8")
        assert load_event_intents(str(bad)) == {}

    def test_wrong_structure_fail_open(self, tmp_path):
        wrong = tmp_path / "wrong.yaml"
        wrong.write_text("hello: world\n", encoding="utf-8")
        assert load_event_intents(str(wrong)) == {}

    def test_contract_drives_l1_close(self):
        # 契约加载结果直接作为 route_trigger intents 入参(联通验证)
        d = route_trigger(_trigger(kind="service_down"), intents=load_event_intents())
        assert d["action"] == ACTION_L1_CLOSE
        assert d["intent_id"] == "health_alert"

    def test_contract_zero_token(self):
        # 契约中每个意图必须 zero_token: true 且 executor 为确定性形态(HC-4)
        import yaml

        path = os.path.join(os.path.dirname(__file__), "..", "core", "event_intents.yaml")
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        for item in doc["intents"]:
            assert item["zero_token"] is True
            assert item["executor"] in ("alert_card", "data_reply")


class TestZeroToken:
    def test_no_llm_imports(self):
        path = os.path.join(os.path.dirname(__file__), "..", "core", "event_gateway.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                for bad in ("openai", "anthropic", "litellm", "langchain"):
                    assert bad not in stripped
