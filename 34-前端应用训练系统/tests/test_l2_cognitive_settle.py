# -*- coding: utf-8 -*-
"""P3b.1: l2_cognitive_settle 认知 record_hook 接线测试。

被测脚本位于 3.1-FRONTEND/scripts/l2_cognitive_settle.py:
  L2 SSE 任务完成 → cle.record → 返回 memory_id（FAIL-OPEN）。
"""
import json
import os
import sys

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "3.1-FRONTEND", "scripts",
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import l2_cognitive_settle as lcs  # noqa: E402


class FakeCLE:
    """认知入口替身（record 返回字符串 memory_id，与生产一致）。"""

    def __init__(self, resp="VM-test-123", *, boom=False):
        self._resp = resp
        self._boom = boom
        self.records = []

    def record(self, content="", quality_level="C", tags="", **kw):
        self.records.append({"content": content, "quality_level": quality_level,
                             "tags": tags})
        if self._boom:
            raise RuntimeError("cognitive down")
        return self._resp


class _FakeL0:
    def __init__(self, cle):
        self._cle = cle

    def _load_cle(self):
        return self._cle


def _patch_l0(monkeypatch, cle):
    monkeypatch.setattr(lcs, "get_l0", lambda: _FakeL0(cle))


class TestSettleL2:
    def test_record_returns_string_memory_id(self, monkeypatch):
        cle = FakeCLE(resp="VM-1792151811358-e198fc1e")
        _patch_l0(monkeypatch, cle)
        out = lcs.settle_l2("task_1", "simple_qa", "BTC趋势", "趋势偏强", 0.85,
                            "technical_analysis")
        assert out["success"] is True
        assert out["memory_id"] == "VM-1792151811358-e198fc1e"
        # 质量映射: 0.85 >= 0.8 → B
        assert out["quality_level"] == "B"
        assert cle.records[0]["quality_level"] == "B"
        assert "technical_analysis" in cle.records[0]["content"]
        assert "task_1" in cle.records[0]["content"]

    def test_record_returns_dict_memory_id(self, monkeypatch):
        cle = FakeCLE(resp={"memory_id": "VM-dict-1"})
        _patch_l0(monkeypatch, cle)
        out = lcs.settle_l2("t", "i", "m", "a", 0.9)
        assert out["success"] is True
        assert out["memory_id"] == "VM-dict-1"

    def test_low_quality_maps_to_c(self, monkeypatch):
        cle = FakeCLE()
        _patch_l0(monkeypatch, cle)
        out = lcs.settle_l2("t", "i", "m", "a", 0.6)
        assert out["quality_level"] == "C"
        assert cle.records[0]["quality_level"] == "C"

    def test_none_quality_score_safe(self, monkeypatch):
        cle = FakeCLE()
        _patch_l0(monkeypatch, cle)
        out = lcs.settle_l2("t", "i", "m", "a", None)
        assert out["success"] is True
        assert out["quality_level"] == "C"

    def test_cognitive_unavailable_fail_open(self, monkeypatch):
        cle = FakeCLE(boom=True)
        _patch_l0(monkeypatch, cle)
        out = lcs.settle_l2("t", "i", "m", "a", 0.9)
        assert out["success"] is False
        assert out["degraded"] is True
        assert "cognitive_unavailable" in out["reason"]

    def test_empty_memory_id_flagged(self, monkeypatch):
        cle = FakeCLE(resp="")
        _patch_l0(monkeypatch, cle)
        out = lcs.settle_l2("t", "i", "m", "a", 0.9)
        assert out["success"] is False
        assert out["reason"] == "record_no_memory_id"

    def test_hint_omitted_when_empty(self, monkeypatch):
        cle = FakeCLE()
        _patch_l0(monkeypatch, cle)
        lcs.settle_l2("t", "i", "m", "a", 0.9, "")
        assert "l1_hint" not in cle.records[0]["content"]


class TestMain:
    def test_main_outputs_json_last_line(self, monkeypatch, capsys):
        cle = FakeCLE(resp="VM-main-1")
        _patch_l0(monkeypatch, cle)
        monkeypatch.setattr(sys, "argv", [
            "l2_cognitive_settle.py",
            json.dumps({"task_id": "t1", "intent": "simple_qa",
                        "message": "m", "answer_preview": "a",
                        "quality_score": 0.85, "l1_intent_hint": "price_query"}),
        ])
        lcs.main()
        last = capsys.readouterr().out.strip().splitlines()[-1]
        parsed = json.loads(last)
        assert parsed["success"] is True
        assert parsed["memory_id"] == "VM-main-1"

    def test_main_bad_args_fail_open(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["l2_cognitive_settle.py", "not-json"])
        cle = FakeCLE()
        _patch_l0(monkeypatch, cle)
        lcs.main()
        parsed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert "success" in parsed  # 不抛异常即 FAIL-OPEN 达标
