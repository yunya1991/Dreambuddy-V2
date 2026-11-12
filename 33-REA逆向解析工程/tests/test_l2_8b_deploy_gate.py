"""L2-8B 灰度自动部署 — RED/GREEN 测试

SPEC-33-G §2.7.1 影子运行 / §2.8 八门禁与断路器 / §2.11.4 L2-8 / §2.11.7 部署边界 / §5 回滚：
  - 只允许灰度自动部署，生产自动部署非目标
  - 未演练不得开自动部署；健康检查必须覆盖核心链路
  - 部署窗口避开交易时段与定时任务；flock + pidfile 单实例
  - DDL/schema/registry/定时任务/交易链路/有状态变更一律人工
  - 灰度前必须先跑影子模式（off → shadow → auto），连续影子成功 ≥3 次
  - 部署失败/健康失败 → 回滚 + 冻结 auto 7 天
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from core.evolution.deploy_gate import (
    MODE_AUTO,
    MODE_OFF,
    MODE_SHADOW,
    DeployBlocked,
    DeployGate,
    SingleInstanceLock,
)

SHANGHAI = timezone(timedelta(hours=8))
BASE = datetime(2026, 11, 11, 20, 0, tzinfo=SHANGHAI)
REPO_PROJECT = Path(__file__).resolve().parents[1]
ROLLBACK_SCRIPT = REPO_PROJECT / "scripts" / "rollback_deploy.sh"
DEPLOY_SCRIPT = REPO_PROJECT / "scripts" / "deploy_gray.py"


class Clock:
    def __init__(self, now=BASE):
        self.now = now

    def __call__(self):
        return self.now


# ---------------------------------------------------------------- 构造器


def _change(**overrides):
    payload = {
        "change_id": "CH-1",
        "files": ["33-REA逆向解析工程/core/evolution/demo.py"],
        "flags": {},
        "version": "v2",
        "commit": "c2",
    }
    payload.update(overrides)
    return payload


def _shadow_pass():
    return {"overall": "pass", "section": "demo"}


def _drill_pass(checked_at=BASE):
    return {"overall": "pass", "checked_at": checked_at.isoformat(), "env": "gray"}


def _config(tmp_path, **overrides):
    script = tmp_path / "rollback_deploy.sh"
    script.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    config = {
        "health": {"url": "http://127.0.0.1:8080/health", "smoke": ["api", "strategy"]},
        "rollback_script": str(script),
        "lock_path": str(tmp_path / "deploy.lock"),
        "pidfile_path": str(tmp_path / "deploy.pid"),
        "cron_slots": [],
    }
    config.update(overrides)
    return config


def _gate(tmp_path, clock=None, **config_overrides):
    return DeployGate(
        tmp_path / "policy",
        clock=clock or Clock(),
        config=_config(tmp_path, **config_overrides),
    )


def _readiness(gate, **overrides):
    payload = {
        "change_id": "CH-1",
        "change": _change(),
        "shadow_report": _shadow_pass(),
        "drill_report": _drill_pass(),
        "stage": "S2",
    }
    payload.update(overrides)
    return gate.readiness(**payload)


def _check(report, check_id):
    for item in report["checks"]:
        if item["id"] == check_id:
            return item
    raise AssertionError(f"missing check {check_id}")


def _enable_auto(gate):
    gate.set_mode(MODE_SHADOW)
    for index in range(3):
        gate.record_shadow_run(change_id=f"CH-{index}", result={"overall": "pass"})
    return gate.set_mode(MODE_AUTO)


def _seed_release(gate, version="v1", commit="c1"):
    path = gate.deploy_dir / "releases" / "gray.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "current": {"version": version, "commit": commit, "released_at": BASE.isoformat()},
                "previous": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------- 1. 默认 off


def test_default_mode_off_blocks_deploy(tmp_path):
    gate = _gate(tmp_path)

    assert gate.mode() == MODE_OFF
    report = _readiness(gate)
    assert report["allowed"] is False
    assert _check(report, "mode")["status"] == "fail"
    assert any("mode" in blocker and "off" in blocker for blocker in report["blockers"])

    with pytest.raises(DeployBlocked):
        gate.deploy(
            change_id="CH-1",
            change=_change(),
            deploy_fn=lambda: None,
            health_fn=lambda: True,
            rollback_fn=lambda reason: None,
            shadow_report=_shadow_pass(),
            drill_report=_drill_pass(),
            stage="S2",
        )


# ---------------------------------------------------------------- 2. 健康/演练缺失


def test_missing_health_and_drill_block_without_side_effects(tmp_path):
    gate = _gate(tmp_path, health={}, rollback_script="")
    gate.set_mode(MODE_SHADOW)

    report = _readiness(gate, drill_report=None)
    assert report["allowed"] is False
    assert _check(report, "health")["status"] == "fail"
    assert _check(report, "rollback")["status"] == "fail"
    assert any("回滚脚本" in blocker for blocker in report["blockers"])

    gate_no_drill = _gate(tmp_path)
    gate_no_drill.set_mode(MODE_SHADOW)
    report_no_drill = _readiness(gate_no_drill, drill_report=None)
    assert any("演练" in blocker for blocker in report_no_drill["blockers"])

    calls = {"deploy": 0, "health": 0, "rollback": 0}

    def deploy_fn():
        calls["deploy"] += 1

    def health_fn():
        calls["health"] += 1

    def rollback_fn(reason):
        calls["rollback"] += 1

    with pytest.raises(DeployBlocked):
        gate.deploy(
            change_id="CH-1",
            change=_change(),
            deploy_fn=deploy_fn,
            health_fn=health_fn,
            rollback_fn=rollback_fn,
            shadow_report=_shadow_pass(),
            drill_report=None,
            stage="S2",
        )
    assert calls == {"deploy": 0, "health": 0, "rollback": 0}


# ---------------------------------------------------------------- 3. 演练过期


def test_expired_drill_report_blocks(tmp_path):
    gate = _gate(tmp_path)
    gate.set_mode(MODE_SHADOW)
    stale = BASE - timedelta(days=31)

    report = _readiness(gate, drill_report=_drill_pass(checked_at=stale))
    item = _check(report, "rollback")
    assert item["status"] == "fail"
    assert "过期" in item["reason"] or "30" in item["reason"]


# ---------------------------------------------------------------- 4. 部署窗口


def test_deploy_window_blocks_trading_hours(tmp_path):
    trading = datetime(2026, 11, 12, 10, 0, tzinfo=SHANGHAI)
    gate = _gate(tmp_path, clock=Clock(trading))
    gate.set_mode(MODE_SHADOW)
    report = _readiness(gate)
    assert _check(report, "deploy_window")["status"] == "fail"
    assert "交易时段" in _check(report, "deploy_window")["reason"]

    evening = datetime(2026, 11, 12, 20, 0, tzinfo=SHANGHAI)
    gate_late = _gate(tmp_path, clock=Clock(evening))
    gate_late.set_mode(MODE_SHADOW)
    report_late = _readiness(gate_late)
    assert _check(report_late, "deploy_window")["status"] == "pass"


# ---------------------------------------------------------------- 5. 数据迁移闸门


@pytest.mark.parametrize(
    "overrides",
    [
        {"change": _change(flags={"stateful": True})},
        {"change": _change(flags={"ddl": True})},
        {"change": _change(flags={"registry": True})},
        {"change": _change(flags={"cron": True})},
        {"change": _change(flags={"trading": True})},
        {"change": _change(files=["db/migrations/001_init.sql"])},
        {"change": _change(files=["core/schema/user.py"])},
    ],
)
def test_data_migration_requires_manual(tmp_path, overrides):
    gate = _gate(tmp_path)
    gate.set_mode(MODE_SHADOW)

    report = _readiness(gate, **overrides)
    item = _check(report, "data_migration")
    assert item["status"] == "fail"
    assert "人工" in item["reason"]


# ---------------------------------------------------------------- 6. shadow 模拟


def test_shadow_mode_simulates_without_calling_functions(tmp_path):
    gate = _gate(tmp_path)
    gate.set_mode(MODE_SHADOW)
    calls = {"deploy": 0, "health": 0, "rollback": 0}

    def deploy_fn():
        calls["deploy"] += 1

    def health_fn():
        calls["health"] += 1

    def rollback_fn(reason):
        calls["rollback"] += 1

    result = gate.deploy(
        change_id="CH-1",
        change=_change(),
        deploy_fn=deploy_fn,
        health_fn=health_fn,
        rollback_fn=rollback_fn,
        shadow_report=_shadow_pass(),
        drill_report=_drill_pass(),
        stage="S2",
    )

    assert result["status"] == "simulated"
    assert result["deployed"] is False
    assert result["would_deploy"] is True
    assert calls == {"deploy": 0, "health": 0, "rollback": 0}

    lines = (gate.deploy_dir / "shadow_runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["overall"] == "pass"
    assert not (gate.deploy_dir / "releases" / "gray.json").exists()


# ---------------------------------------------------------------- 7. shadow → auto


def test_shadow_to_auto_requires_three_consecutive_passes(tmp_path):
    gate = _gate(tmp_path)
    gate.set_mode(MODE_SHADOW)

    with pytest.raises(DeployBlocked) as excinfo:
        gate.set_mode(MODE_AUTO)
    assert "影子" in str(excinfo.value)

    gate.record_shadow_run(change_id="CH-1", result={"overall": "pass"})
    gate.record_shadow_run(change_id="CH-2", result={"overall": "pass"})
    with pytest.raises(DeployBlocked):
        gate.set_mode(MODE_AUTO)

    gate.record_shadow_run(change_id="CH-3", result={"overall": "pass"})
    assert gate.consecutive_shadow_passes() == 3
    assert gate.set_mode(MODE_AUTO)["mode"] == MODE_AUTO
    assert gate.mode() == MODE_AUTO


def test_failed_shadow_run_resets_consecutive_passes(tmp_path):
    gate = _gate(tmp_path)
    gate.set_mode(MODE_SHADOW)
    for index in range(3):
        gate.record_shadow_run(change_id=f"CH-{index}", result={"overall": "pass"})
    gate.record_shadow_run(change_id="CH-x", result={"overall": "fail"})

    assert gate.consecutive_shadow_passes() == 0
    with pytest.raises(DeployBlocked):
        gate.set_mode(MODE_AUTO)


def test_frozen_gate_cannot_enable_auto(tmp_path):
    gate = _gate(tmp_path)
    gate.set_mode(MODE_SHADOW)
    for index in range(3):
        gate.record_shadow_run(change_id=f"CH-{index}", result={"overall": "pass"})
    gate.deploy_dir.mkdir(parents=True, exist_ok=True)
    frozen_until = BASE + timedelta(days=7)
    (gate.deploy_dir / "freeze.json").write_text(
        json.dumps(
            {
                "frozen_until": frozen_until.isoformat(),
                "reason": "回滚演练失败",
                "change_id": "CH-1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert gate.is_frozen() is True
    with pytest.raises(DeployBlocked) as excinfo:
        gate.set_mode(MODE_AUTO)
    assert "冻结" in str(excinfo.value)


# ---------------------------------------------------------------- 8. auto 成功


def test_auto_deploy_success_updates_release(tmp_path):
    gate = _gate(tmp_path)
    _enable_auto(gate)
    release_path = _seed_release(gate)
    calls = {"deploy": 0, "health": 0, "rollback": 0}

    def deploy_fn():
        calls["deploy"] += 1

    def health_fn():
        calls["health"] += 1
        return {"status": "pass"}

    def rollback_fn(reason):
        calls["rollback"] += 1

    result = gate.deploy(
        change_id="CH-1",
        change=_change(),
        deploy_fn=deploy_fn,
        health_fn=health_fn,
        rollback_fn=rollback_fn,
        shadow_report=_shadow_pass(),
        drill_report=_drill_pass(),
        stage="S3",
    )

    assert result["status"] == "deployed"
    assert result["deployed"] is True
    assert result["rolled_back"] is False
    assert calls == {"deploy": 1, "health": 1, "rollback": 0}

    release = json.loads(release_path.read_text(encoding="utf-8"))
    assert release["current"]["version"] == "v2"
    assert release["current"]["commit"] == "c2"
    assert release["previous"]["version"] == "v1"
    assert release["previous"]["commit"] == "c1"
    assert gate.is_frozen() is False
    assert not (gate.deploy_dir / "freeze.json").exists()


# ---------------------------------------------------------------- 9. auto 健康失败


def test_auto_health_failure_rolls_back_and_freezes(tmp_path):
    gate = _gate(tmp_path)
    _enable_auto(gate)
    release_path = _seed_release(gate)
    calls = {"deploy": 0, "health": 0, "rollback": 0, "reason": ""}

    def deploy_fn():
        calls["deploy"] += 1

    def health_fn():
        calls["health"] += 1
        return {"status": "fail"}

    def rollback_fn(reason):
        calls["rollback"] += 1
        calls["reason"] = reason

    result = gate.deploy(
        change_id="CH-1",
        change=_change(),
        deploy_fn=deploy_fn,
        health_fn=health_fn,
        rollback_fn=rollback_fn,
        shadow_report=_shadow_pass(),
        drill_report=_drill_pass(),
        stage="S3",
    )

    assert result["rolled_back"] is True
    assert result["deployed"] is False
    assert calls["deploy"] == 1
    assert calls["health"] == 1
    assert calls["rollback"] == 1
    assert "健康检查" in calls["reason"]

    freeze = json.loads((gate.deploy_dir / "freeze.json").read_text(encoding="utf-8"))
    frozen_until = datetime.fromisoformat(freeze["frozen_until"])
    expected = BASE + timedelta(days=7)
    assert abs((frozen_until - expected).total_seconds()) < 1
    assert result["frozen_until"] == freeze["frozen_until"]
    assert gate.is_frozen() is True

    release = json.loads(release_path.read_text(encoding="utf-8"))
    assert release["current"]["version"] == "v1"
    assert release["previous"] is None


def test_auto_deploy_exception_rolls_back(tmp_path):
    gate = _gate(tmp_path)
    _enable_auto(gate)
    calls = {"rollback": 0}

    def deploy_fn():
        raise RuntimeError("镜像拉取失败")

    def health_fn():
        return {"status": "pass"}

    def rollback_fn(reason):
        calls["rollback"] += 1

    result = gate.deploy(
        change_id="CH-1",
        change=_change(),
        deploy_fn=deploy_fn,
        health_fn=health_fn,
        rollback_fn=rollback_fn,
        shadow_report=_shadow_pass(),
        drill_report=_drill_pass(),
        stage="S3",
    )

    assert result["rolled_back"] is True
    assert calls["rollback"] == 1
    assert gate.is_frozen() is True


# ---------------------------------------------------------------- 10. 单实例锁


def test_single_instance_lock_blocks_second_holder(tmp_path):
    first = SingleInstanceLock(tmp_path / "deploy.lock", tmp_path / "deploy.pid", clock=Clock())
    info = first.acquire()
    assert info["pid"] == os.getpid()

    second = SingleInstanceLock(tmp_path / "deploy.lock", tmp_path / "deploy.pid", clock=Clock())
    with pytest.raises(DeployBlocked):
        second.acquire()

    first.release()
    assert second.acquire()["pid"] == os.getpid()
    second.release()


def test_single_instance_lock_takes_over_stale_pid(tmp_path):
    pidfile = tmp_path / "deploy.pid"
    pidfile.write_text("999999\n", encoding="utf-8")

    lock = SingleInstanceLock(tmp_path / "deploy.lock", pidfile, clock=Clock())
    info = lock.acquire()
    assert info["stale_pid"] == "999999"
    assert pidfile.read_text(encoding="utf-8").strip() == str(os.getpid())
    lock.release()
    assert not pidfile.exists()


# ---------------------------------------------------------------- 11/12. 回滚脚本


def _write_state(state_dir, env="gray", *, current, previous, restart="true", health="true"):
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"{env}.json"
    path.write_text(
        json.dumps(
            {
                "current": current,
                "previous": previous,
                "restart_cmd": restart,
                "health_cmd": health,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _run_rollback(*args):
    return subprocess.run(
        ["bash", str(ROLLBACK_SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_rollback_drill_passes_with_valid_state(tmp_path):
    state_dir = tmp_path / "state"
    _write_state(
        state_dir,
        current={"version": "v2", "commit": "c2", "released_at": "2026-11-10T12:00:00+08:00"},
        previous={"version": "v1", "commit": "c1", "released_at": "2026-11-01T12:00:00+08:00"},
    )

    result = _run_rollback("--env", "gray", "--drill", "--state-dir", str(state_dir))

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((state_dir / "gray.drill.json").read_text(encoding="utf-8"))
    assert report["overall"] == "pass"
    assert report["env"] == "gray"
    assert all(item["passed"] for item in report["checks"])
    state = json.loads((state_dir / "gray.json").read_text(encoding="utf-8"))
    assert state["current"]["version"] == "v2"


def test_rollback_drill_fails_without_previous(tmp_path):
    state_dir = tmp_path / "state"
    _write_state(
        state_dir,
        current={"version": "v2", "commit": "c2", "released_at": "2026-11-10T12:00:00+08:00"},
        previous=None,
    )

    result = _run_rollback("--env", "gray", "--drill", "--state-dir", str(state_dir))

    assert result.returncode != 0
    report = json.loads((state_dir / "gray.drill.json").read_text(encoding="utf-8"))
    assert report["overall"] == "fail"
    assert any(not item["passed"] for item in report["checks"])


def test_rollback_swaps_versions_and_writes_log(tmp_path):
    state_dir = tmp_path / "state"
    _write_state(
        state_dir,
        current={"version": "v2", "commit": "c2", "released_at": "2026-11-10T12:00:00+08:00"},
        previous={"version": "v1", "commit": "c1", "released_at": "2026-11-01T12:00:00+08:00"},
        restart="true",
        health="true",
    )

    result = _run_rollback(
        "--env", "gray", "--yes", "--reason", "健康检查失败", "--state-dir", str(state_dir)
    )

    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((state_dir / "gray.json").read_text(encoding="utf-8"))
    assert state["current"]["version"] == "v1"
    assert state["previous"]["version"] == "v2"

    lines = (state_dir / "gray.rollback.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["health"] == "pass"
    assert row["ok"] is True
    assert row["from"]["version"] == "v2"
    assert row["to"]["version"] == "v1"


def test_rollback_unknown_env_fails(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    result = _run_rollback("--env", "mars", "--drill", "--state-dir", str(state_dir))

    assert result.returncode != 0
    assert "未知环境" in result.stderr


def test_rollback_health_failure_exits_3_and_marks_fail(tmp_path):
    state_dir = tmp_path / "state"
    _write_state(
        state_dir,
        current={"version": "v2", "commit": "c2", "released_at": "2026-11-10T12:00:00+08:00"},
        previous={"version": "v1", "commit": "c1", "released_at": "2026-11-01T12:00:00+08:00"},
        restart="true",
        health="false",
    )

    result = _run_rollback("--env", "gray", "--yes", "--state-dir", str(state_dir))

    assert result.returncode == 3
    state = json.loads((state_dir / "gray.json").read_text(encoding="utf-8"))
    assert state["health"] == "fail"
    rows = (state_dir / "gray.rollback.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(rows[0])["health"] == "fail"


# ---------------------------------------------------------------- 13. deploy_gray CLI


def _write_gray_config(root: Path, tmp_path: Path, **overrides):
    root.mkdir(parents=True, exist_ok=True)
    (root / "deploy").mkdir(parents=True, exist_ok=True)
    rollback = tmp_path / "rollback_deploy.sh"
    rollback.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    config = {
        "env": "gray",
        "health": {"url": "http://127.0.0.1:8080/health", "smoke": ["api"]},
        "rollback_script": str(rollback),
        "lock_path": str(tmp_path / "deploy.lock"),
        "pidfile_path": str(tmp_path / "deploy.pid"),
        "blocked_weekdays": [],
        "cron_slots": [],
        "deploy_cmd": ["true"],
        "health_cmd": ["true"],
        "rollback_cmd": ["true"],
    }
    config.update(overrides)
    (root / "deploy" / "gate_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return config


def _write_json(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _run_deploy(*args):
    return subprocess.run(
        [sys.executable, str(DEPLOY_SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_deploy_gray_dry_run_off_mode_exits_1(tmp_path):
    root = tmp_path / "policy"
    _write_gray_config(root, tmp_path)
    change = _write_json(tmp_path / "change.json", _change())
    shadow = _write_json(tmp_path / "shadow.json", _shadow_pass())
    drill = _write_json(tmp_path / "drill.json", _drill_pass(checked_at=datetime.now(timezone.utc)))

    result = _run_deploy(
        "--root",
        str(root),
        "--change",
        str(change),
        "--shadow-report",
        str(shadow),
        "--drill-report",
        str(drill),
        "--stage",
        "S2",
        "--dry-run",
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["allowed"] is False
    assert report["blockers"]
    assert any("mode" in blocker for blocker in report["blockers"])


def test_deploy_gray_shadow_mode_simulates_exit_0(tmp_path):
    root = tmp_path / "policy"
    _write_gray_config(root, tmp_path)
    (root / "deploy").mkdir(parents=True, exist_ok=True)
    _write_json(root / "deploy" / "deploy_mode.json", {"mode": MODE_SHADOW})
    change = _write_json(tmp_path / "change.json", _change())
    shadow = _write_json(tmp_path / "shadow.json", _shadow_pass())
    drill = _write_json(tmp_path / "drill.json", _drill_pass(checked_at=datetime.now(timezone.utc)))

    result = _run_deploy(
        "--root",
        str(root),
        "--change",
        str(change),
        "--shadow-report",
        str(shadow),
        "--drill-report",
        str(drill),
        "--stage",
        "S2",
        "--env",
        "gray",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "simulated"
    assert payload["deployed"] is False
