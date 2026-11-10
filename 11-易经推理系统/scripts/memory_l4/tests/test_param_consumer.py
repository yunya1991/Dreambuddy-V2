"""WP-R1 N5 测试：11 param_consumer（对齐 23 契约 + 真实应用阈值/仓位系数）。

42 ParamGovernor 分发 elastic_params 视图到 42/runtime/param_dispatch/11-bcrm.json，
11 param_consumer 读取后将 long_threshold_multiplier / position_size_factor 写入
11/runtime/param_governor_override.json，供 polling_trader 加载覆盖。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_11_ROOT = Path(__file__).resolve().parents[3]
_PC_PATH = _11_ROOT / "scripts" / "memory_l4" / "param_consumer.py"


def _load_pc():
    spec = importlib.util.spec_from_file_location("n5_param_consumer", _PC_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["n5_param_consumer"] = mod
    spec.loader.exec_module(mod)
    return mod


def _view(version="v1.1", long_mult=1.05, pos_factor=0.95, topics=None):
    return {
        "subscriber": "11-bcrm",
        "topics": topics or ["elastic_params"],
        "version": version,
        "generated_at": "2026-11-09T13:00:00+00:00",
        "params": {
            "long_threshold_multiplier": long_mult,
            "position_size_factor": pos_factor,
            "weight_adjust_limit": 0.05,
            "cooldown_period_hours": 24,
        },
    }


# ── 正常消费：写 override ──────────────────────────────────────


def test_consume_writes_override_file(tmp_path):
    pc = _load_pc()
    view_path = tmp_path / "11-bcrm.json"
    view_path.write_text(json.dumps(_view()), encoding="utf-8")
    override_path = tmp_path / "override.json"
    log_path = tmp_path / "consume.log"

    result = pc.consume(
        view_path=str(view_path), override_path=str(override_path), log_path=str(log_path)
    )

    assert result["status"] == "applied"
    assert result["consumer"] == "11-bcrm"
    assert override_path.exists()
    ov = json.loads(override_path.read_text(encoding="utf-8"))
    assert ov["long_threshold_multiplier"] == 1.05
    assert ov["position_size_factor"] == 0.95
    assert ov["version"] == "v1.1"
    assert ov["source"] == "42-param_governor"
    assert "applied_at" in ov


def test_consume_logs_consumption(tmp_path):
    pc = _load_pc()
    view_path = tmp_path / "11-bcrm.json"
    view_path.write_text(json.dumps(_view()), encoding="utf-8")
    override_path = tmp_path / "override.json"
    log_path = tmp_path / "consume.log"

    pc.consume(view_path=str(view_path), override_path=str(override_path), log_path=str(log_path))

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["consumer"] == "11-bcrm"
    assert entry["status"] == "applied"


# ── 改 params → override 变化（核心验证）──────────────────────


def test_changing_params_updates_override(tmp_path):
    pc = _load_pc()
    view_path = tmp_path / "11-bcrm.json"
    override_path = tmp_path / "override.json"
    log_path = tmp_path / "consume.log"

    view_path.write_text(json.dumps(_view(long_mult=1.05, pos_factor=0.95)), encoding="utf-8")
    pc.consume(view_path=str(view_path), override_path=str(override_path), log_path=str(log_path))
    ov1 = json.loads(override_path.read_text(encoding="utf-8"))
    assert ov1["long_threshold_multiplier"] == 1.05
    assert ov1["position_size_factor"] == 0.95

    # 参数变更（收紧方向）
    view_path.write_text(
        json.dumps(_view(version="v1.2", long_mult=1.10, pos_factor=0.90)), encoding="utf-8"
    )
    pc.consume(view_path=str(view_path), override_path=str(override_path), log_path=str(log_path))
    ov2 = json.loads(override_path.read_text(encoding="utf-8"))
    assert ov2["long_threshold_multiplier"] == 1.10
    assert ov2["position_size_factor"] == 0.90
    assert ov2["version"] == "v1.2"


# ── FAIL-OPEN：视图缺失 → unavailable，override 不动 ──────────


def test_consume_missing_view_returns_unavailable(tmp_path):
    pc = _load_pc()
    override_path = tmp_path / "override.json"
    # 预置一个旧 override
    override_path.write_text(json.dumps({"long_threshold_multiplier": 1.05}), encoding="utf-8")

    result = pc.consume(
        view_path=str(tmp_path / "nonexistent.json"),
        override_path=str(override_path),
        log_path=str(tmp_path / "consume.log"),
    )
    assert result["status"] == "unavailable"
    # override 保持不变（不回滚默认，避免抖动）
    ov = json.loads(override_path.read_text(encoding="utf-8"))
    assert ov["long_threshold_multiplier"] == 1.05


def test_consume_corrupt_view_returns_unavailable(tmp_path):
    pc = _load_pc()
    view_path = tmp_path / "11-bcrm.json"
    view_path.write_text("{not valid json", encoding="utf-8")
    override_path = tmp_path / "override.json"

    result = pc.consume(
        view_path=str(view_path),
        override_path=str(override_path),
        log_path=str(tmp_path / "consume.log"),
    )
    assert result["status"] == "unavailable"
    assert not override_path.exists()


# ── load_override helper（polling_trader 调用入口）────────────


def test_load_override_returns_dict(tmp_path):
    pc = _load_pc()
    override_path = tmp_path / "override.json"
    assert pc.load_override(str(override_path)) == {}  # 缺失 → 空

    override_path.write_text(json.dumps({"long_threshold_multiplier": 1.10}), encoding="utf-8")
    ov = pc.load_override(str(override_path))
    assert ov["long_threshold_multiplier"] == 1.10
