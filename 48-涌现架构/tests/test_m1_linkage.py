"""TDD RED — M1 广播联动率度量（SPEC §4 E1 + §5 度量总则）。

M1 = 广播事件被非目标域消费并产生动作的比例（actions / consumed）。
双报原始计数（动作下限：watchlist 变更才算动作）。
"""

import m1_linkage as m1


def test_m1_from_e2e_events(tmp_path):
    import emergence_bus as eb
    import shadow_subscribers as ss

    bus = eb.EmergenceBus(events_dir=tmp_path / "shadow", enabled=True)
    for domain in ("rea", "eval", "data"):
        ss.ShadowSubscriber(domain, events_dir=tmp_path / "shadow").attach(bus)
    # 事件1：data psi 突刺 → eval 动作
    bus.report_anomaly("data", "psi", 0.31, 0.10, 0.05)
    # 事件2：cognition coupling 异常 → rea 动作
    bus.report_anomaly("cognition", "coupling", 0.42, 0.10, 0.08)

    result = m1.compute_m1(events_dir=tmp_path / "shadow")
    assert result["status"] == "ok"
    assert result["broadcasts"] == 2
    # 消费：事件1 eval+rea 消费（data 自身不算）=2；事件2 eval+rea+data 消费=3 → 共5
    assert result["consumed"] == 5
    # 动作：事件1 eval=1；事件2 rea=1 → 共2
    assert result["actions"] == 2
    assert abs(result["m1_rate"] - 2 / 5) < 1e-9
    assert result["by_subscriber"]["eval"]["actions"] == 1
    assert result["by_subscriber"]["rea"]["actions"] == 1


def test_m1_empty_dir(tmp_path):
    result = m1.compute_m1(events_dir=tmp_path / "nonexistent")
    assert result["status"] == "no_events"
    assert result["m1_rate"] is None
