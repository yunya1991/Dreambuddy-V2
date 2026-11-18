# -*- coding: utf-8 -*-
"""settle → 残差记忆暂存测试（P2.5 写入口）。

验收：
  - 有价值发现（降级/数据源的坑）→ 暂存候选
  - 正常数据不写候选
  - 候选字段与前端准入契约对齐（content/subclass/anchor/trace_id）
  - 坏输入 FAIL-OPEN
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.l0_foundation import L0Foundation  # noqa: E402
from core.residual_memory_spool import (  # noqa: E402
    append_candidate,
    build_candidate,
    pending_path,
    read_candidates,
)


def test_build_candidate_fields():
    result = {"degraded": True, "answer": "数据源暂不可用", "data": {"source": "okx"}}
    candidate = build_candidate(
        "发现: 数据源暂不可用", "data_query", "查 BTC", result, {"trace_id": "tr-1"}
    )
    assert candidate["content"].startswith("发现:")
    assert candidate["subclass"] == "runtime"
    assert candidate["anchor"] == "source:okx"
    assert candidate["source_anchor"] == "source:okx"
    assert candidate["trace_id"] == "tr-1"
    assert len(candidate["summary"]) <= 200


def test_append_and_read_candidates(tmp_path):
    candidate = build_candidate("发现: x", "i", "m", {}, {})
    assert append_candidate(candidate, str(tmp_path)) is True
    assert len(read_candidates(str(tmp_path))) == 1
    # 坏输入 FAIL-OPEN
    assert append_candidate({}, str(tmp_path)) is False
    assert append_candidate(None, str(tmp_path)) is False


def test_settle_writes_candidate_for_degraded_result(tmp_path):
    l0 = L0Foundation(root=str(tmp_path))
    l0._record_cognitive = lambda *a, **k: None
    result = {"success": True, "degraded": True, "answer": "暂不可用", "data": None}

    l0.settle(result, {"intent": "risk_control", "message": "风控状态", "trace_id": "tr-2"})

    items = read_candidates(str(tmp_path))
    assert len(items) == 1
    assert items[0]["trace_id"] == "tr-2"
    assert items[0]["subclass"] == "runtime"


def test_settle_skips_candidate_for_normal_result(tmp_path):
    l0 = L0Foundation(root=str(tmp_path))
    l0._record_cognitive = lambda *a, **k: None
    result = {"success": True, "answer": "ans", "data": {"metrics": {"cpi": 3.1}}}

    l0.settle(result, {"intent": "data_query", "message": "查 CPI"})

    assert not os.path.exists(pending_path(str(tmp_path)))
