# -*- coding: utf-8 -*-
"""P2 生产路径验收：准入裁决 120 应存 / 120 不应存 / 60 敏感（SPEC §4′ P2）。

两组证据：
1. gate() 在 enforce 模式下的判定矩阵；
2. CognitiveLoopEntry.record() 的真实接线（未通过时必须显式拒入）。
"""

import sys
import types
from pathlib import Path

import pytest

_COG_DIR = Path(__file__).resolve().parent.parent
if str(_COG_DIR) not in sys.path:
    sys.path.insert(0, str(_COG_DIR))

import cognitive_loop_entry as cle  # noqa: E402
from residual_memory import gate  # noqa: E402


def _positives() -> list[str]:
    cases = []
    for i in range(30):
        cases.append(f"用户偏好：不要用方案{i}，原因是它和现有口径冲突")
        cases.append(f"事故复盘{i}：根因是连接池未释放，回滚耗时 {i + 1} 小时")
        cases.append(f"维护窗口{i}：每周日 02:00-04:00，属主为值班同学")
        cases.append(f"试过方案{i}，不行：在并发下会丢事件，已放弃")
    return cases


def _negatives() -> list[str]:
    cases = []
    for i in range(30):
        cases.append(f"Python 列表推导式的第 {i} 种写法是什么")
        cases.append(f"接口定义见 4-MEMORY/9-工具与接口/module{i}.md")
        cases.append(f"实现细节可以用 REA 逆向解析第 {i} 个模块得到")
        cases.append(f"运行第 {i} 个 pytest 用例即可复现该行为")
    return cases


def _sensitive() -> list[str]:
    return (
        [f"api_key = sk-test{i:012d}abcdef" for i in range(20)]
        + [f"password = Passw0rd_{i:04d}abc" for i in range(20)]
        + ["%s%s MIIEow%08d" % ("-----BEGIN RSA ", "PRIVATE KEY-----", i) for i in range(20)]
    )


def test_p2_gate_acceptance_matrix():
    positives = _positives()
    negatives = _negatives()
    sensitive = _sensitive()
    assert len(positives) == 120 and len(negatives) == 120 and len(sensitive) == 60

    false_rejects = [c for c in positives if not gate(c, mode="enforce").accepted]
    false_accepts = [c for c in negatives if gate(c, mode="enforce").accepted]
    sensitive_accepts = [c for c in sensitive if gate(c, mode="enforce").accepted]

    assert false_rejects == [], f"漏存 {len(false_rejects)}"
    assert false_accepts == [], f"误存 {len(false_accepts)}"
    assert sensitive_accepts == [], f"敏感误存 {len(sensitive_accepts)}"


class _FakeVM:
    def __init__(self):
        self.added = []

    def add(self, **kwargs):
        self.added.append(kwargs)
        return "VM-P2-TEST"


def _stub(monkeypatch):
    monkeypatch.setattr(cle, "_voyager_persist_extra", lambda **kw: None)
    monkeypatch.setitem(
        sys.modules, "index_rebuild_trigger", types.SimpleNamespace(trigger=lambda: None)
    )
    return types.SimpleNamespace(_vm=_FakeVM(), _l4_state={})


def test_p2_record_wiring_accepts_residual(monkeypatch):
    stub = _stub(monkeypatch)
    memory_id = cle.CognitiveLoopEntry.record(
        stub, "试过了，不行：回滚耗时 2 小时", admission_mode="enforce"
    )
    assert memory_id == "VM-P2-TEST"
    assert stub._vm.added[0]["subclass"] in {"D-policy", "D-tech"}
    assert stub._vm.added[0]["form"] == "M2"


def test_p2_record_wiring_rejects_trajectory_and_sensitive(monkeypatch):
    stub = _stub(monkeypatch)
    with pytest.raises(ValueError, match="admission_rejected:trajectory"):
        cle.CognitiveLoopEntry.record(
            stub, "[RAG检索] query=x", source="rag-bridge", admission_mode="enforce"
        )
    with pytest.raises(ValueError, match="admission_rejected:sensitive"):
        cle.CognitiveLoopEntry.record(
            stub, "api_key = sk-abcdefgh12345678", admission_mode="enforce"
        )
    assert stub._vm.added == []
