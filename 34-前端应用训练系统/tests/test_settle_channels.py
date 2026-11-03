# -*- coding: utf-8 -*-
"""settle 五系统全通道(T-DSH-P3 P3-1) RED 测试。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P3·常驻(settle 五系统全通道) + §⑦
(认知经验 · SKILL 可复用流程 · 调研知识 · 文档 · 索引) + ADR-9(settle 由编排侧
执行,Worker 只读) + H1 FAIL-OPEN(单通道失败不阻塞其他通道) + H2(通道开关
默认关)。

断言:
  - 五通道清单与开关命名;开关默认关 → 通道不执行
  - 仅开启的通道被调用,结果逐一上报
  - 单通道抛错 → 该通道 failed,其余通道照常(FAIL-OPEN 隔离)
  - 通道未配置 callable → unconfigured 跳过
  - 坏输入 → 空报告,不抛错
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.settle_channels import (  # noqa: E402
    SETTLE_CHANNELS,
    channel_switch,
    is_channel_enabled,
    settle_via_channels,
)


def test_five_channels_and_switch_naming():
    assert SETTLE_CHANNELS == ("cognitive", "skill", "knowledge", "docs", "index")
    assert channel_switch("cognitive") == "enable_settle_channel_cognitive"
    assert channel_switch("index") == "enable_settle_channel_index"


def test_switch_default_off():
    assert is_channel_enabled("cognitive", None) is False
    assert is_channel_enabled("cognitive", {}) is False
    assert is_channel_enabled("cognitive", {"enable_settle_channel_cognitive": True}) is True
    # 坏 flags 不抛错
    assert is_channel_enabled("cognitive", "bad") is False
    assert is_channel_enabled("unknown", {"enable_settle_channel_unknown": True}) is False


def test_only_enabled_channels_invoked():
    calls = []
    channels = {
        name: (lambda n: lambda r, c: calls.append(n) or {"written": 1})(name)
        for name in SETTLE_CHANNELS
    }
    flags = {
        "enable_settle_channel_cognitive": True,
        "enable_settle_channel_docs": True,
    }
    report = settle_via_channels({"success": True}, {"intent": "i"}, channels, flags)
    assert sorted(calls) == ["cognitive", "docs"]
    assert report["cognitive"]["status"] == "ok"
    assert report["docs"]["status"] == "ok"
    assert report["skill"]["status"] == "disabled"
    assert report["knowledge"]["status"] == "disabled"
    assert report["index"]["status"] == "disabled"


def test_channel_result_recorded():
    channels = {"cognitive": lambda r, c: {"memory_id": "VM-1"}}
    report = settle_via_channels({}, {}, channels, {"enable_settle_channel_cognitive": True})
    assert report["cognitive"]["status"] == "ok"
    assert report["cognitive"]["detail"] == {"memory_id": "VM-1"}


def test_single_channel_failure_isolated():
    def boom(r, c):
        raise RuntimeError("channel down")

    calls = []
    channels = {
        "cognitive": boom,
        "skill": lambda r, c: calls.append("skill") or {"ok": 1},
        "docs": lambda r, c: calls.append("docs") or {"ok": 1},
    }
    flags = {channel_switch(n): True for n in ("cognitive", "skill", "docs")}
    report = settle_via_channels({"success": True}, {}, channels, flags)
    # 失败通道标 failed,其余通道不受影响(H1 FAIL-OPEN 隔离)
    assert report["cognitive"]["status"] == "failed"
    assert "channel down" in report["cognitive"]["detail"]
    assert report["skill"]["status"] == "ok"
    assert report["docs"]["status"] == "ok"
    assert calls == ["skill", "docs"]


def test_unconfigured_channel_skipped():
    report = settle_via_channels(
        {}, {}, {"cognitive": lambda r, c: {}}, {"enable_settle_channel_skill": True}
    )
    assert report["skill"]["status"] == "unconfigured"


def test_bad_input_fail_open():
    assert settle_via_channels(None, None, None, None) == {}
    assert settle_via_channels({}, {}, "bad", {}) == {}
    assert settle_via_channels({}, {}, {}, "bad") == {}
