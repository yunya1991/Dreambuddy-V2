"""40 侧 48 反馈适配器测试：默认关闭、开启后读取、缺失 FAIL-OPEN。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "40-周期神经网络系统" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import adapter_48_feedback as ad  # noqa: E402


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_40_VIA_48", raising=False)
    assert ad.enabled() is False


def test_loads_when_enabled(monkeypatch, tmp_path):
    p = tmp_path / "40_feedback.json"
    p.write_text(
        json.dumps({"gateway_version": "x", "source_window": {"n_events": 2}}), encoding="utf-8"
    )
    monkeypatch.setenv("ENABLE_40_VIA_48", "1")
    fb = ad.load_48_feedback(p)
    assert fb["source_window"]["n_events"] == 2
    payload = ad.attach_to_payload({}, p)
    assert payload["_feedback_48"]["gateway_version"] == "x"


def test_missing_file_fail_open(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_40_VIA_48", "1")
    assert ad.load_48_feedback(tmp_path / "absent.json") is None
    assert ad.attach_to_payload({}, tmp_path / "absent.json") == {}
