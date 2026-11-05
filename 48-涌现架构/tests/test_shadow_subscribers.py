"""TDD RED — E1 shadow 订阅者测试（rea/eval/data 三域）。

动作下限（SPEC v0.3 封口）：仅记日志/仅 ACK 不算动作，必须改变接收模块后续输出。
shadow 期定义：相关事件触发 watchlist 变更（新入列或优先级升级）= 可审计行为改变。
"""

import json

import emergence_bus as eb
import shadow_subscribers as ss


def _setup(tmp_path):
    bus = eb.EmergenceBus(events_dir=tmp_path / "shadow", enabled=True)
    subs = {}
    for domain in ("rea", "eval", "data"):
        sub = ss.ShadowSubscriber(domain, events_dir=tmp_path / "shadow")
        sub.attach(bus)
        subs[domain] = sub
    return bus, subs


def test_relevant_event_triggers_watchlist_action(tmp_path):
    bus, subs = _setup(tmp_path)
    # data 域 PSI 突刺（z=4.2）→ eval 关心 psi → 应消费+动作；rea 不关心 psi → 消费无动作
    bus.report_anomaly("data", "psi", 0.31, 0.10, 0.05)
    wl_eval = json.loads((tmp_path / "shadow" / "watchlist_eval.json").read_text(encoding="utf-8"))
    assert any(e["source_domain"] == "data" and e["metric"] == "psi" for e in wl_eval["entries"])
    # 响应落盘：eval action=True，rea action=False
    resp_files = list((tmp_path / "shadow").glob("resp_*.jsonl"))
    resps = [
        json.loads(line) for line in resp_files[0].read_text(encoding="utf-8").strip().splitlines()
    ]
    by_sub = {r["subscriber"]: r for r in resps}
    assert by_sub["eval"]["consumed"] is True
    assert by_sub["eval"]["action"] is True
    assert by_sub["rea"]["consumed"] is True
    assert by_sub["rea"]["action"] is False


def test_source_domain_not_counted_as_consumer(tmp_path):
    bus, subs = _setup(tmp_path)
    # data 域自己发的事件 → data 订阅者不算"非目标域消费"
    bus.report_anomaly("data", "psi", 0.31, 0.10, 0.05)
    resp_files = list((tmp_path / "shadow").glob("resp_*.jsonl"))
    resps = [
        json.loads(line) for line in resp_files[0].read_text(encoding="utf-8").strip().splitlines()
    ]
    by_sub = {r["subscriber"]: r for r in resps}
    assert by_sub["data"]["consumed"] is False
    assert by_sub["data"]["action"] is False


def test_coupling_event_interests_rea(tmp_path):
    bus, subs = _setup(tmp_path)
    # cognition↔rea coupling 异常 → rea 关心 coupling
    bus.report_anomaly("cognition", "coupling", 0.42, 0.10, 0.08, detail={"pair": "cognition↔rea"})
    resp_files = list((tmp_path / "shadow").glob("resp_*.jsonl"))
    resps = [
        json.loads(line) for line in resp_files[0].read_text(encoding="utf-8").strip().splitlines()
    ]
    by_sub = {r["subscriber"]: r for r in resps}
    assert by_sub["rea"]["action"] is True
    assert by_sub["eval"]["action"] is False


def test_repeat_event_escalates_priority(tmp_path):
    bus, subs = _setup(tmp_path)
    bus.report_anomaly("data", "psi", 0.31, 0.10, 0.05)
    bus.report_anomaly("data", "psi", 0.35, 0.10, 0.05)
    wl = json.loads((tmp_path / "shadow" / "watchlist_eval.json").read_text(encoding="utf-8"))
    entry = next(e for e in wl["entries"] if e["source_domain"] == "data")
    assert entry["hits"] == 2
    assert entry["priority"] > 1  # 优先级升级 = 行为改变
