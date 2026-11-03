# -*- coding: utf-8 -*-
"""T-DSH-P2 P2-2 RED: 45 门禁 shadow→硬门 误拦率统计与转正判据。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 DD4(45 先 shadow,误拦率 <5% 转硬门)
+ P2·验收退出判据(45 业务门禁接为硬门,先 shadow 转正)。

口径(误拦率 = shadow 期间「若转硬门会被拦截」的占比):
  would_block = verdict ∈ {BLOCK, INCONCLUSIVE, ERROR, TIMEOUT}
  would_block_rate = would_block / total(仅统计 shadow 模式记录)
转正判据: 样本数 ≥ min_samples 且 would_block_rate < threshold(默认 5%)

硬约束:
  FAIL-OPEN: 坏路径/坏记录 → rate None / promote False(不贸然转硬门)
  只读统计,不改裁决记录(WORM 语义: 只追加,不修改历史)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.gate_45_stats import (  # noqa: E402  ModuleNotFoundError → RED
    WOULD_BLOCK_VERDICTS,
    load_verdicts,
    record_verdict,
    should_promote_to_hard,
    would_block_rate,
)


def _rec(verdict, mode="shadow", eval_id="EV-1", trace_id="tr-1", ts=1000.0):
    return {"verdict": verdict, "mode": mode, "eval_id": eval_id, "trace_id": trace_id, "ts": ts}


# ---------- 记录与读取(WORM 追加) ----------


def test_record_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "verdicts.jsonl")
    assert record_verdict(_rec("PASS"), path) is True
    assert record_verdict(_rec("BLOCK", trace_id="tr-2"), path) is True
    records = load_verdicts(path)
    assert len(records) == 2
    assert records[0]["verdict"] == "PASS"
    assert records[1]["trace_id"] == "tr-2"


def test_record_fail_open_on_bad_input(tmp_path):
    assert record_verdict(None, str(tmp_path / "x.jsonl")) is False
    assert record_verdict({"no_verdict": 1}, str(tmp_path / "x.jsonl")) is False
    assert load_verdicts(str(tmp_path / "missing.jsonl")) == []
    # 坏行跳过不炸
    p = tmp_path / "bad.jsonl"
    p.write_text('{"verdict":"PASS","mode":"shadow"}\nnot-json\n', encoding="utf-8")
    assert len(load_verdicts(str(p))) == 1


# ---------- 误拦率口径 ----------


def test_would_block_rate_only_counts_shadow():
    records = [
        _rec("PASS"),
        _rec("PASS"),
        _rec("BLOCK"),  # shadow 会被拦 → 计入
        _rec("INCONCLUSIVE"),
        _rec("BLOCK", mode="hard"),  # hard 期记录不计入 shadow 口径
    ]
    rate = would_block_rate(records)
    assert rate == 0.5  # 2/4(shadow 四条中 BLOCK+INCONCLUSIVE)


def test_would_block_verdicts_set():
    assert set(WOULD_BLOCK_VERDICTS) == {"BLOCK", "INCONCLUSIVE", "ERROR", "TIMEOUT"}


def test_would_block_rate_empty_or_bad():
    assert would_block_rate([]) is None
    assert would_block_rate(None) is None
    assert would_block_rate([_rec("PASS", mode="hard")]) is None  # 无 shadow 样本


# ---------- 转正判据(DD4: 误拦率 <5%) ----------


def test_promote_requires_min_samples():
    records = [_rec("PASS") for _ in range(10)]
    assert should_promote_to_hard(records, min_samples=20) is False  # 样本不足
    assert should_promote_to_hard(records, min_samples=10) is True  # 0% < 5%


def test_promote_threshold_boundary():
    # 20 样本 1 个 BLOCK → 5% 误拦率,不小于 5% → 不转正
    records = [_rec("PASS") for _ in range(19)] + [_rec("BLOCK")]
    assert should_promote_to_hard(records, threshold=0.05, min_samples=20) is False
    # 21 样本 1 个 BLOCK ≈ 4.76% < 5% → 转正
    records = [_rec("PASS") for _ in range(20)] + [_rec("BLOCK")]
    assert should_promote_to_hard(records, threshold=0.05, min_samples=20) is True


def test_promote_fail_open():
    assert should_promote_to_hard(None) is False
    assert should_promote_to_hard([]) is False
