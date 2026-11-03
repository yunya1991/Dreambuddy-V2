# -*- coding: utf-8 -*-
"""T-DSH-P2 P2-4 RED: Watchdog 独立巡查。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P2·验收(Watchdog 独立巡查;
退出判据: Watchdog 能识别偏离目标) + 职责边界(Watchdog 不改任务,
只产巡查结论并升级给人或 Router) + 风险 U3(长尾 Ticket 堆积)。

巡查发现类型(纯函数判定,只读不改):
  stalled_live:   live 但最近活动超过 stale_ttl(进展停滞)
  long_paused:    paused/waitsForPerson 超过 paused_ttl(长尾堆积 U3)
  missing_trace:  缺 trace_id(观测链断裂,ADR-7)
  goal_drift:     mandate.goal 与 current_focus 词集零交集(偏离目标)

契约:
  patrol(tickets, now, stale_ttl_s, paused_ttl_s) -> report
  report = {ok, findings: [{ticket_id, kind, detail}], stats, escalate}
  escalate: findings 非空 → True(升级给人/Router;Watchdog 本身不动作)
  FAIL-OPEN: 坏输入 → {ok: False, findings: [], degraded: True}
  硬约束: patrol 不得修改 tickets(Watchdog 不改任务)
"""

import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.watchdog import patrol  # noqa: E402  ModuleNotFoundError → RED

NOW = 10_000.0


def _live(tid, last_ts, **kw):
    t = {
        "ticket_id": tid,
        "state": "live",
        "trace_id": "tr-1",
        "history": [{"from": "live", "to": "live", "ts": last_ts}],
    }
    t.update(kw)
    return t


# ---------- 进展停滞 ----------


def test_stalled_live_detected():
    tickets = [_live("TK-1", last_ts=NOW - 7200)]  # 2h 无活动
    report = patrol(tickets, now=NOW, stale_ttl_s=1800)
    kinds = [f["kind"] for f in report["findings"]]
    assert "stalled_live" in kinds
    f = next(f for f in report["findings"] if f["kind"] == "stalled_live")
    assert f["ticket_id"] == "TK-1"


def test_active_live_not_flagged():
    tickets = [_live("TK-1", last_ts=NOW - 60)]
    report = patrol(tickets, now=NOW, stale_ttl_s=1800)
    assert report["findings"] == []
    assert report["escalate"] is False


# ---------- 长尾堆积(U3) ----------


def test_long_paused_detected():
    t = _live("TK-2", last_ts=NOW - 100)
    t["state"] = "paused"
    t["paused_reason"] = "waiting_event"
    t["history"] = [{"from": "live", "to": "paused", "ts": NOW - 7200}]
    report = patrol([t], now=NOW, paused_ttl_s=3600)
    kinds = [f["kind"] for f in report["findings"]]
    assert "long_paused" in kinds


def test_recent_paused_not_flagged():
    t = _live("TK-2", last_ts=NOW - 100)
    t["state"] = "paused"
    t["history"] = [{"from": "live", "to": "paused", "ts": NOW - 100}]
    report = patrol([t], now=NOW, paused_ttl_s=3600)
    assert report["findings"] == []


# ---------- 观测链断裂 ----------


def test_missing_trace_detected():
    t = _live("TK-3", last_ts=NOW - 10)
    t["trace_id"] = None
    report = patrol([t], now=NOW)
    kinds = [f["kind"] for f in report["findings"]]
    assert "missing_trace" in kinds


# ---------- 偏离目标 ----------


def test_goal_drift_detected():
    t = _live(
        "TK-4",
        last_ts=NOW - 10,
        mandate={"goal": "回测洗盘反转因子并评估收益"},
        current_focus="整理文档索引与链接修复",
    )
    report = patrol([t], now=NOW)
    kinds = [f["kind"] for f in report["findings"]]
    assert "goal_drift" in kinds


def test_goal_aligned_not_flagged():
    t = _live(
        "TK-4",
        last_ts=NOW - 10,
        mandate={"goal": "回测洗盘反转因子"},
        current_focus="回测洗盘反转因子的参数敏感性",
    )
    report = patrol([t], now=NOW)
    assert report["findings"] == []


# ---------- 汇总与升级 ----------


def test_report_stats_and_escalate():
    tickets = [
        _live("TK-1", last_ts=NOW - 7200),  # stalled
        _live("TK-2", last_ts=NOW - 10),  # healthy
        {"ticket_id": "TK-3", "state": "ended", "trace_id": "t", "history": []},  # ended 不巡查
    ]
    report = patrol(tickets, now=NOW, stale_ttl_s=1800)
    assert report["ok"] is True
    assert report["escalate"] is True  # 有发现 → 升级
    assert report["stats"]["total"] == 3
    assert report["stats"]["live"] == 2
    assert len(report["findings"]) == 1  # ended 不参与巡查


# ---------- 硬约束: 不改任务 / FAIL-OPEN ----------


def test_patrol_does_not_mutate_tickets():
    tickets = [_live("TK-1", last_ts=NOW - 7200)]
    snapshot = copy.deepcopy(tickets)
    patrol(tickets, now=NOW, stale_ttl_s=1800)
    assert tickets == snapshot  # Watchdog 不改任务


def test_patrol_fail_open():
    report = patrol(None, now=NOW)
    assert report["ok"] is False
    assert report["findings"] == []
    assert report["degraded"] is True
    report2 = patrol("not-a-list", now=NOW)
    assert report2["ok"] is False
    # 坏元素跳过不炸
    report3 = patrol([None, _live("TK-9", last_ts=NOW - 10)], now=NOW)
    assert report3["ok"] is True
    assert report3["findings"] == []
