#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-06：ParamGovernor 发布 + 订阅分发 stub 契约测试。

验收口径（49-SPEC §13.5 P1-06）：
- 参数非默认可发布：adjust_params 在收紧方向/范围内/限幅内生效，版本号递增
- 安全红线：只收紧不放大；单次变更 ≤ weight_adjust_limit；冷却期内不重复调整
- 订阅分发 stub：dispatch 按 registry subscribe 声明写各订阅者参数视图 + 分发日志
- 23/43 至少各 1 个消费者日志：consumer stub 只读视图并追加消费日志（FAIL-OPEN）
- 开关 ENABLE_PARAM_DISPATCH=1；未设置时不发布不分发（回滚路径）
- 默认不改变裁决：开关关闭时 params_active.json 保持默认值
"""

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_42_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _42_ROOT not in sys.path:
    sys.path.insert(0, _42_ROOT)

_REPO_ROOT = os.path.dirname(_42_ROOT)

import param_governor  # noqa: E402


def _load_consumer(module_key, rel_path):
    """按文件路径加载 23/43 消费者 stub（两模块同名 param_consumer，需隔离）。"""
    path = os.path.join(_REPO_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(module_key, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def gov(tmp_path):
    """param_governor 路径隔离 fixture（不触真实 runtime/）。"""
    paths = {
        "active": str(tmp_path / "params_active.json"),
        "history": str(tmp_path / "params_history.jsonl"),
        "dispatch_dir": str(tmp_path / "param_dispatch"),
        "dispatch_log": str(tmp_path / "param_dispatch_log.jsonl"),
    }
    return paths


def _init(paths):
    return param_governor.init_params(active_path=paths["active"], history_path=paths["history"])


# ── 1. 回滚路径：开关未设置时 adjust/dispatch 均不生效 ──
def test_adjust_disabled_without_flag(monkeypatch, gov):
    monkeypatch.delenv("ENABLE_PARAM_DISPATCH", raising=False)
    _init(gov)
    result = param_governor.adjust_params(
        {"position_size_factor": 0.97},
        "test",
        active_path=gov["active"],
        history_path=gov["history"],
    )
    assert result["status"] == "disabled"
    doc = param_governor.load_active(gov["active"])
    assert doc["params"]["position_size_factor"] == 1.0, "开关关闭时默认参数不得改变"


def test_dispatch_disabled_without_flag(monkeypatch, gov):
    monkeypatch.delenv("ENABLE_PARAM_DISPATCH", raising=False)
    _init(gov)
    result = param_governor.dispatch(
        active_path=gov["active"],
        dispatch_dir=gov["dispatch_dir"],
        log_path=gov["dispatch_log"],
    )
    assert result["status"] == "disabled"
    assert not os.path.exists(gov["dispatch_dir"])


# ── 2. 安全红线：只收紧不放大 ──
def test_adjust_rejects_loosening(monkeypatch, gov):
    monkeypatch.setenv("ENABLE_PARAM_DISPATCH", "1")
    _init(gov)
    # long_threshold_multiplier 收紧方向=上调；下调=放大 → 拒绝
    r1 = param_governor.adjust_params(
        {"long_threshold_multiplier": 0.99},
        "loosen",
        active_path=gov["active"],
        history_path=gov["history"],
    )
    assert r1["status"] == "rejected"
    # position_size_factor 收紧方向=下调；从 0.9 上调=放大 → 拒绝
    doc = param_governor.load_active(gov["active"])
    doc["params"]["position_size_factor"] = 0.9
    param_governor.write_active(doc, gov["active"])
    r2 = param_governor.adjust_params(
        {"position_size_factor": 0.92},
        "loosen",
        active_path=gov["active"],
        history_path=gov["history"],
    )
    assert r2["status"] == "rejected"


# ── 3. 范围校验：超出 §4.1 预注册范围拒绝 ──
def test_adjust_rejects_out_of_range(monkeypatch, gov):
    monkeypatch.setenv("ENABLE_PARAM_DISPATCH", "1")
    _init(gov)
    result = param_governor.adjust_params(
        {"long_threshold_multiplier": 2.5},
        "oor",
        active_path=gov["active"],
        history_path=gov["history"],
    )
    assert result["status"] == "rejected"
    assert "范围" in result["reason"] or "range" in result["reason"].lower()


# ── 4. 单次限幅：|delta| > weight_adjust_limit(0.05) 拒绝 ──
def test_adjust_rejects_over_weight_limit(monkeypatch, gov):
    monkeypatch.setenv("ENABLE_PARAM_DISPATCH", "1")
    _init(gov)
    result = param_governor.adjust_params(
        {"position_size_factor": 0.90},
        "over limit",
        active_path=gov["active"],
        history_path=gov["history"],
    )
    assert result["status"] == "rejected"


# ── 5. 合法收紧：发布成功 + 版本递增 + 历史可审计 ──
def test_adjust_accept_tightening(monkeypatch, gov):
    monkeypatch.setenv("ENABLE_PARAM_DISPATCH", "1")
    _init(gov)
    result = param_governor.adjust_params(
        {"position_size_factor": 0.97, "long_threshold_multiplier": 1.02},
        "宏观收紧",
        active_path=gov["active"],
        history_path=gov["history"],
    )
    assert result["status"] == "adjusted", result
    doc = param_governor.load_active(gov["active"])
    assert doc["params"]["position_size_factor"] == 0.97
    assert doc["params"]["long_threshold_multiplier"] == 1.02
    assert doc["version"] != "v1.0", "非默认发布后版本必须递增"
    with open(gov["history"], encoding="utf-8") as f:
        entries = [json.loads(line) for line in f if line.strip()]
    assert any(e.get("action") == "adjust" for e in entries)


# ── 5b. no-op：取值未变化的调整拒绝（不升版本、不写历史）──
def test_adjust_rejects_noop(monkeypatch, gov):
    monkeypatch.setenv("ENABLE_PARAM_DISPATCH", "1")
    _init(gov)
    before = param_governor.load_active(gov["active"])["version"]
    result = param_governor.adjust_params(
        {"position_size_factor": 1.0},
        "no change",
        active_path=gov["active"],
        history_path=gov["history"],
    )
    assert result["status"] == "rejected", result
    assert param_governor.load_active(gov["active"])["version"] == before


# ── 6. 冷却期：冷却窗口内第二次调整拒绝 ──
def test_adjust_cooldown(monkeypatch, gov):
    monkeypatch.setenv("ENABLE_PARAM_DISPATCH", "1")
    _init(gov)
    r1 = param_governor.adjust_params(
        {"position_size_factor": 0.97},
        "first",
        active_path=gov["active"],
        history_path=gov["history"],
    )
    assert r1["status"] == "adjusted"
    r2 = param_governor.adjust_params(
        {"position_size_factor": 0.95},
        "second within cooldown",
        active_path=gov["active"],
        history_path=gov["history"],
    )
    assert r2["status"] == "rejected"
    assert "冷却" in r2["reason"]


# ── 7. 订阅分发：按 registry subscribe 写视图 + 分发日志，含 23/43 ──
def test_dispatch_writes_subscriber_views(monkeypatch, gov):
    monkeypatch.setenv("ENABLE_PARAM_DISPATCH", "1")
    _init(gov)
    result = param_governor.dispatch(
        active_path=gov["active"],
        dispatch_dir=gov["dispatch_dir"],
        log_path=gov["dispatch_log"],
    )
    assert result["status"] == "dispatched", result
    subscribers = result["subscribers"]
    assert "43-strategic-extension" in subscribers
    assert "23-contradiction" in subscribers, "23 必须在 registry 声明订阅参数"
    for name in subscribers:
        view_path = os.path.join(gov["dispatch_dir"], "{}.json".format(name))
        assert os.path.exists(view_path), "缺少订阅者视图: {}".format(name)
        with open(view_path, encoding="utf-8") as f:
            view = json.load(f)
        assert view["subscriber"] == name
        assert "params" in view and "version" in view
    with open(gov["dispatch_log"], encoding="utf-8") as f:
        logs = [json.loads(line) for line in f if line.strip()]
    assert len(logs) == len(subscribers), "每个订阅者一条分发日志（消费可观测）"


# ── 8. 23/43 消费者 stub：只读视图 + 追加消费日志 ──
def test_consumers_log_consumption(monkeypatch, gov, tmp_path):
    monkeypatch.setenv("ENABLE_PARAM_DISPATCH", "1")
    _init(gov)
    param_governor.dispatch(
        active_path=gov["active"],
        dispatch_dir=gov["dispatch_dir"],
        log_path=gov["dispatch_log"],
    )
    consumers = [
        ("consumer_23", "23-四层闭环自进化交易架构/param_consumer.py", "23-contradiction"),
        ("consumer_43", "43-战略承接推演层/param_consumer.py", "43-strategic-extension"),
    ]
    for key, rel, sub_name in consumers:
        module = _load_consumer(key, rel)
        log_path = str(tmp_path / "{}_consumption.jsonl".format(sub_name))
        view_path = os.path.join(gov["dispatch_dir"], "{}.json".format(sub_name))
        result = module.consume(view_path=view_path, log_path=log_path)
        assert result["status"] == "consumed", (sub_name, result)
        with open(log_path, encoding="utf-8") as f:
            entries = [json.loads(line) for line in f if line.strip()]
        assert entries and entries[-1]["consumer"] == sub_name
        assert "version" in entries[-1]


# ── 9. 消费者 fail-open：视图缺失不抛异常 ──
def test_consumer_failopen_on_missing_view(tmp_path):
    module = _load_consumer("consumer_23_missing", "23-四层闭环自进化交易架构/param_consumer.py")
    result = module.consume(
        view_path=str(tmp_path / "nope.json"),
        log_path=str(tmp_path / "log.jsonl"),
    )
    assert result["status"] in ("unavailable", "fail-open")
