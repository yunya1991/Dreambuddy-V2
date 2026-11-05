"""TDD RED — E1 广播总线接线测试（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E1）。

设计要点（BIO 条件 #5）：
  a) 点火阈值 = 3σ 偏离，不能什么都广播（z < 3 → None，不产生事件）
  b) 广播 envelope 落盘 events/emergence_shadow/bus_YYYYMMDD.jsonl（shadow 期）
  c) 复用 4-MEMORY workspace_bus.py（48 域只接线，不复制所有权）
  d) FAIL-OPEN + 开关默认关闭（EMERGENCE_BUS=1 / flag 文件）
"""

import json

import emergence_bus as eb


def _bus(tmp_path, **kw):
    return eb.EmergenceBus(events_dir=tmp_path / "shadow", enabled=True, **kw)


def test_below_3sigma_no_broadcast(tmp_path):
    bus = _bus(tmp_path)
    result = bus.report_anomaly("data", "psi", value=0.15, baseline_mean=0.10, baseline_std=0.05)
    assert result is None  # z=1 < 3 → 不广播
    assert bus.stats()["total_broadcasts"] == 0


def test_above_3sigma_broadcasts_and_persists(tmp_path):
    bus = _bus(tmp_path)
    received = []
    bus.subscribe("eval", lambda content: received.append(content))
    result = bus.report_anomaly("data", "psi", value=0.31, baseline_mean=0.10, baseline_std=0.05)
    # z = (0.31-0.10)/0.05 = 4.2 ≥ 3 → 点燃广播
    assert result is not None
    assert result["ignited"] is True
    assert result["z_score"] == 4.2
    assert result["source_domain"] == "data"
    assert result["trace_id"].startswith("emergence-shadow-")
    assert len(received) == 1  # 订阅者收到
    # shadow envelope 落盘
    files = list((tmp_path / "shadow").glob("bus_*.jsonl"))
    assert len(files) == 1
    env = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert env["event_id"] == result["event_id"]
    assert env["metric"] == "psi"


def test_zero_std_fail_open(tmp_path):
    bus = _bus(tmp_path)
    # std=0 不能除 → FAIL-OPEN 返回 None，不抛异常
    assert bus.report_anomaly("data", "psi", 0.5, 0.5, 0.0) is None


def test_disabled_bus_silent(tmp_path):
    bus = eb.EmergenceBus(events_dir=tmp_path / "shadow", enabled=False)
    assert bus.report_anomaly("data", "psi", 0.9, 0.1, 0.05) is None
    assert not (tmp_path / "shadow").exists()


def test_fail_open_on_unwritable_dir(tmp_path):
    import os
    import stat

    ro_dir = tmp_path / "readonly"
    ro_dir.mkdir()
    os.chmod(ro_dir, stat.S_IRUSR | stat.S_IXUSR)
    bus = eb.EmergenceBus(events_dir=ro_dir / "shadow", enabled=True)
    # 目录不可写 → 广播仍发给订阅者，落盘失败静默
    received = []
    bus.subscribe("rea", lambda c: received.append(c))
    result = bus.report_anomaly("data", "psi", 0.31, 0.10, 0.05)
    assert result is not None
    assert len(received) == 1
    os.chmod(ro_dir, stat.S_IRWXU)
