"""M5-T3 Red/Green — 告警通道测试。"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import pytest

from data_center.monitoring.alerting import (
    Alert,
    AlertChannel,
    AlertLevel,
    AlertRouter,
    FileAlertChannel,
    LarkAlertChannel,
    LogAlertChannel,
)


# ---------------------------------------------------------------------------
# Alert 基础
# ---------------------------------------------------------------------------
def test_alert_to_dict_has_required_fields():
    a = Alert(
        level=AlertLevel.ERROR,
        title="采集失败",
        message="fred/SourceUnavailableError",
        tags=["fred", "macro"],
    )
    d = a.to_dict()
    assert d["level"] == "ERROR"
    assert d["title"] == "采集失败"
    assert d["message"] == "fred/SourceUnavailableError"
    assert "tags" in d and "fred" in d["tags"]
    assert "ts" in d


# ---------------------------------------------------------------------------
# LogAlertChannel
# ---------------------------------------------------------------------------
def test_log_channel_emits_records_via_caplog(caplog):
    caplog.set_level(logging.INFO, logger="data_center.monitoring")
    ch = LogAlertChannel()
    ch.emit(Alert(
        level=AlertLevel.WARNING,
        title="空列表",
        message="fred 返回 0 条",
        tags=["fred", "macro", "EMPTY_RESULT"],
    ))
    titles = [r.message for r in caplog.records]
    assert any("[WARNING] 空列表" in m for m in titles)


# ---------------------------------------------------------------------------
# FileAlertChannel
# ---------------------------------------------------------------------------
def test_file_channel_writes_ndjson_lines():
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "alerts.ndjson"
        ch = FileAlertChannel(fp)
        ch.emit(Alert(level=AlertLevel.ERROR, title="t1", message="m1"))
        ch.emit(Alert(level=AlertLevel.INFO, title="t2", message="m2"))

        lines = fp.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        d1 = json.loads(lines[0])
        assert d1["level"] == "ERROR" and d1["title"] == "t1"
        d2 = json.loads(lines[1])
        assert d2["level"] == "INFO" and d2["title"] == "t2"


def test_file_channel_tail_returns_last_n():
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "alerts.ndjson"
        ch = FileAlertChannel(fp)
        for i in range(5):
            ch.emit(Alert(
                level=AlertLevel.INFO,
                title=f"t{i}",
                message=f"m{i}",
            ))
        last2 = ch.tail(2)
        assert [a["title"] for a in last2] == ["t3", "t4"]


def test_file_channel_missing_tail_empty():
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "not_exist.ndjson"
        ch = FileAlertChannel(fp)
        assert ch.tail(5) == []


# ---------------------------------------------------------------------------
# LarkAlertChannel
# ---------------------------------------------------------------------------
def test_lark_channel_rejects_invalid_webhook():
    with pytest.raises(ValueError):
        LarkAlertChannel("not_a_http_url")


def test_lark_channel_accepts_http_url(caplog):
    caplog.set_level(logging.INFO, logger="data_center.monitoring.lark")
    ch = LarkAlertChannel("https://open.feishu.cn/open-apis/bot/v2/hook/abcd")
    ch.emit(Alert(level=AlertLevel.ERROR, title="t", message="m"))
    msgs = [r.getMessage() for r in caplog.records]
    assert any("[LARK-STUB]" in m for m in msgs)


# ---------------------------------------------------------------------------
# AlertRouter 分发 + min_level 过滤
# ---------------------------------------------------------------------------
class _SpyChannel(AlertChannel):
    def __init__(self):
        self.received: list[Alert] = []

    def emit(self, alert: Alert) -> None:
        self.received.append(alert)


def test_router_routes_to_all_channels():
    sp1 = _SpyChannel()
    sp2 = _SpyChannel()
    router = AlertRouter([sp1, sp2])
    a = Alert(level=AlertLevel.INFO, title="t", message="m")
    router.emit(a)
    assert len(sp1.received) == 1
    assert len(sp2.received) == 1


def test_router_min_level_filters_low_priority():
    sp = _SpyChannel()
    router = AlertRouter([sp], min_level=AlertLevel.WARNING)
    # INFO 被过滤
    router.emit(Alert(level=AlertLevel.INFO, title="i", message="i"))
    assert sp.received == []
    # WARNING 通过
    router.emit(Alert(level=AlertLevel.WARNING, title="w", message="w"))
    router.emit(Alert(level=AlertLevel.ERROR, title="e", message="e"))
    assert len(sp.received) == 2


def test_router_channel_exception_isolated(caplog):
    """一个通道抛异常不能阻塞其他通道。"""
    caplog.set_level(logging.ERROR, logger="data_center.monitoring")

    class _BadChannel(AlertChannel):
        def emit(self, alert):
            raise RuntimeError("boom")

    bad = _BadChannel()
    good = _SpyChannel()
    router = AlertRouter([bad, good])
    router.emit(Alert(level=AlertLevel.ERROR, title="t", message="m"))
    # good 通道仍收到
    assert len(good.received) == 1
    # logging 有异常记录
    errs = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("AlertChannel 失败" in r.getMessage() for r in errs)


def test_router_dynamic_add_channel():
    sp = _SpyChannel()
    router = AlertRouter([])
    router.emit(Alert(level=AlertLevel.INFO, title="before", message="m"))
    assert sp.received == []
    router.add_channel(sp)
    router.emit(Alert(level=AlertLevel.INFO, title="after", message="m"))
    assert [a.title for a in sp.received] == ["after"]
