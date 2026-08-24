#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase1 / P0 TDD Red 基座：CBRJsonlStore（JSONL 双时点建库存储）10 项测试。

对应实施计划 T1 Step 1：先写测试，全部跑红（CBRJsonlStore / CBR_CANONICAL_5D_KEYS
尚未实现 → ImportError 转为 FAIL 或测试断言失败，均属 RED 阶段预期）。

覆盖计划 C1-C10：
  C1  半条 entry_snapshot 写入后 JSONL 行字段类型正确（schema=v0.3 / exit 全 null）
  C2  finalize_by_case_id 能正确回填半条的 exit_snapshot + pnl_usdt + is_profit
  C3  文件锁占用（flock竞争）时 failopen 返回 False，不阻塞/不抛
  C4  finalize 找不到 case_id 时静默返回 False（G6，不抛 KeyError）
  C5  同一 case_id 重复 finalize 两次，输出幂等（不重复写/不数值漂移）
  C6  JSONL 中混入非法一行时，下一次 finalize 能正常工作（跳过坏行，C6 容错）
  C7  feature_5d 子键名集合 = CBR_CANONICAL_5D_KEYS 并集（Spec §2.3.1 五维表规范）
  C8  runtime/ 不存在时自动 mkdir -p，不抛 FileNotFoundError
  C9  200 条数据 → _rewrite_all（finalize 隐含的重写）耗时 < 0.5s（简单性能阈值）
  C10 engine.enable=False（或构造 disable）时，任何 API 返回 False/None 字节等价
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

import fcntl
import pytest

ROOT = Path(__file__).resolve().parents[3]  # = 11-易经推理系统/
sys.path.insert(0, str(ROOT))


def _import_or_sentinel() -> Dict[str, Any]:
    """RED 阶段懒加载：模块/符号不存在时返回占位，让测试断言 FAIL 而非崩溃。"""
    placeholder = object()
    try:
        from scripts.memory_l4 import cbr_engine as _ce
    except Exception:
        _ce = placeholder
    CBRJsonlStore = getattr(_ce, "CBRJsonlStore", placeholder)
    CBR_CANONICAL_5D_KEYS = getattr(_ce, "CBR_CANONICAL_5D_KEYS", placeholder)
    return {"CBRJsonlStore": CBRJsonlStore, "CBR_CANONICAL_5D_KEYS": CBR_CANONICAL_5D_KEYS,
            "SENTINEL": placeholder}


# ---------------------------------------------------------------------
# C1: 半条 entry 写入字段类型正确
# ---------------------------------------------------------------------
def test_C1_half_entry_writes_valid_v03_schema_line():
    s = _import_or_sentinel()
    assert s["CBRJsonlStore"] is not s["SENTINEL"], "RED: CBRJsonlStore 未实现（属预期内）"
    CBRJsonlStore = s["CBRJsonlStore"]
    with tempfile.TemporaryDirectory() as td:
        store = CBRJsonlStore(runtime_dir=Path(td), enable=True)
        case = {"case_id": "case_BTC_abcd1234", "symbol": "BTC-USDT-SWAP",
                "asset_class": "CRYPTO", "create_ts": 1724300000000,
                "entry_snapshot": {"regime": "sprout", "decision": "SHORT",
                                   "confidence": 0.95, "volatility": 0.035,
                                   "feature_5d": {"rsi_14": 33.1, "macd_hist": -0.02,
                                                  "roc_5d": -1.2, "roc_20d": -3.5,
                                                  "hexagram_confidence": 0.95}}}
        assert store.append_entry_semi(case) is True
        lines = [ln.strip() for ln in (Path(td) / "cbr_cases_v03.jsonl").read_text(
            encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["schema"] == "v0.3"
        assert rec["case_id"] == "case_BTC_abcd1234"
        assert rec["exit_snapshot"] is None and rec["pnl_usdt"] is None
        assert rec["is_profit"] is None and rec["close_ts"] is None
        assert rec["create_ts"] == 1724300000000
        assert rec["entry_snapshot"]["decision"] == "SHORT"


# ---------------------------------------------------------------------
# C2: finalize 回填 exit 成功
# ---------------------------------------------------------------------
def test_C2_finalize_fills_exit_snapshot_and_pnl_fields():
    s = _import_or_sentinel()
    assert s["CBRJsonlStore"] is not s["SENTINEL"]
    CBRJsonlStore = s["CBRJsonlStore"]
    with tempfile.TemporaryDirectory() as td:
        store = CBRJsonlStore(runtime_dir=Path(td), enable=True)
        store.append_entry_semi({
            "case_id": "case_COIN_00aabbcc", "symbol": "COIN-USDT-SWAP",
            "asset_class": "CRYPTO", "create_ts": 1724300000001,
            "entry_snapshot": {"decision": "SHORT", "confidence": 0.95, "volatility": 0.04,
                               "feature_5d": {}}})
        exit_snap = {"exit_reason": "stop_loss_hit", "hold_hours": 4.5,
                     "max_drawdown_pct": -2.3, "max_runup_pct": +0.8}
        ok = store.finalize_by_case_id("case_COIN_00aabbcc", exit_snap, pnl_pct=-2.1,
                                       pnl_usdt=-42.7, is_profit=False)
        assert ok is True
        rec = json.loads(
            [ln for ln in (Path(td) / "cbr_cases_v03.jsonl").read_text(
                encoding="utf-8").splitlines() if ln][0])
        assert rec["exit_snapshot"]["exit_reason"] == "stop_loss_hit"
        assert rec["pnl_pct"] == -2.1
        assert abs(rec["pnl_usdt"] - (-42.7)) < 1e-9
        assert rec["is_profit"] is False
        assert isinstance(rec["close_ts"], int) and rec["close_ts"] > 0


# ---------------------------------------------------------------------
# C3: flock 竞争 → failopen 返回 False
# ---------------------------------------------------------------------
def test_C3_flock_contention_timeout_failopen_returns_false_not_block():
    s = _import_or_sentinel()
    assert s["CBRJsonlStore"] is not s["SENTINEL"]
    CBRJsonlStore = s["CBRJsonlStore"]
    with tempfile.TemporaryDirectory() as td:
        # 第一步 touch + 占锁
        jpath = Path(td) / "cbr_cases_v03.jsonl"
        jpath.touch()
        hold_fd = os.open(str(jpath), os.O_RDWR)
        try:
            fcntl.flock(hold_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 占用
            store = CBRJsonlStore(runtime_dir=Path(td), enable=True)
            t0 = time.perf_counter()
            # 非阻塞 0.1s 超时内必须返回 False（G3 不阻塞卡主流程）
            ok = store.append_entry_semi({
                "case_id": "case_BLOCK_xx", "symbol": "BTC",
                "asset_class": "CRYPTO", "create_ts": 1,
                "entry_snapshot": {"decision": "LONG", "confidence": 0.5, "volatility": 0,
                                   "feature_5d": {}}})
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert ok is False, f"锁竞争时应 failopen=False，实际={ok}"
            # G3：总耗时不能超过 1.0s（0.1s 超时 + 小 overhead）
            assert elapsed_ms < 1000.0, f"锁等待过长 {elapsed_ms:.0f}ms（G3 禁止阻塞）"
        finally:
            fcntl.flock(hold_fd, fcntl.LOCK_UN)
            os.close(hold_fd)


# ---------------------------------------------------------------------
# C4: 找不到 case_id → 静默 False（G6 红线，不抛 KeyError）
# ---------------------------------------------------------------------
def test_C4_finalize_missing_case_id_returns_false_silently_no_exception():
    s = _import_or_sentinel()
    assert s["CBRJsonlStore"] is not s["SENTINEL"]
    CBRJsonlStore = s["CBRJsonlStore"]
    with tempfile.TemporaryDirectory() as td:
        store = CBRJsonlStore(runtime_dir=Path(td), enable=True)
        store.append_entry_semi({
            "case_id": "case_X", "symbol": "BTC", "asset_class": "CRYPTO",
            "create_ts": 1, "entry_snapshot": {
                "decision": "LONG", "confidence": 0.5, "volatility": 0, "feature_5d": {}}})
        # case_id 不存在 → False 不抛
        try:
            ok = store.finalize_by_case_id("CASE_DOES_NOT_EXIST",
                                           {"exit_reason": "x"}, -0.1, -1.0, False)
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"G6 红线违规：找不到 case_id 抛了 {type(e).__name__}: {e}")
        assert ok is False


# ---------------------------------------------------------------------
# C5: finalize 幂等
# ---------------------------------------------------------------------
def test_C5_duplicate_finalize_is_idempotent_same_output():
    s = _import_or_sentinel()
    assert s["CBRJsonlStore"] is not s["SENTINEL"]
    CBRJsonlStore = s["CBRJsonlStore"]
    with tempfile.TemporaryDirectory() as td:
        store = CBRJsonlStore(runtime_dir=Path(td), enable=True)
        store.append_entry_semi({
            "case_id": "case_Y", "symbol": "GOLD", "asset_class": "COMMODITY",
            "create_ts": 7, "entry_snapshot": {"decision": "LONG", "confidence": 0.80,
                                                "volatility": 0.02, "feature_5d": {}}})
        exit_snap = {"exit_reason": "take_profit", "hold_hours": 72}
        store.finalize_by_case_id("case_Y", exit_snap, +1.8, +90.2, True)
        first = json.loads([ln for ln in (Path(td) / "cbr_cases_v03.jsonl").read_text(
            encoding="utf-8").splitlines() if ln][0])
        # 第二次同样参数 → close_ts 可能变，但数值字段必须完全一致
        store.finalize_by_case_id("case_Y", exit_snap, +1.8, +90.2, True)
        second = json.loads([ln for ln in (Path(td) / "cbr_cases_v03.jsonl").read_text(
            encoding="utf-8").splitlines() if ln][0])
        for k in ("pnl_pct", "pnl_usdt", "is_profit", "exit_snapshot"):
            assert first[k] == second[k], f"幂等失败：字段{k}不同 first={first[k]} second={second[k]}"
        assert (Path(td) / "cbr_cases_v03.jsonl").read_text(encoding="utf-8").count("\n") == \
               first.__class__.__len__ is not None or True  # 占位；文件总条数不变（1 行）
        assert len([ln for ln in (Path(td) / "cbr_cases_v03.jsonl").read_text(
            encoding="utf-8").splitlines() if ln]) == 1, "重复 finalize 不应产生新行"


# ---------------------------------------------------------------------
# C6: JSONL 有坏行 → 下一次 finalize 跳过坏行正常继续（容错）
# ---------------------------------------------------------------------
def test_C6_corrupt_line_in_jsonl_is_skipped_without_crash():
    s = _import_or_sentinel()
    assert s["CBRJsonlStore"] is not s["SENTINEL"]
    CBRJsonlStore = s["CBRJsonlStore"]
    with tempfile.TemporaryDirectory() as td:
        jpath = Path(td) / "cbr_cases_v03.jsonl"
        # 手动写一条合法 + 一条非法垃圾
        jpath.write_text(
            json.dumps({"schema": "v0.3", "case_id": "case_A", "exit_snapshot": None,
                        "pnl_pct": None, "pnl_usdt": None, "is_profit": None,
                        "create_ts": 1, "close_ts": None,
                        "symbol": "BTC", "asset_class": "CRYPTO",
                        "entry_snapshot": {"feature_5d": {}}}, ensure_ascii=False)
            + "\nTHIS LINE IS NOT JSON {{{\n", encoding="utf-8")
        store = CBRJsonlStore(runtime_dir=Path(td), enable=True)
        ok = store.finalize_by_case_id("case_A", {"exit_reason": "tp"}, 1.0, 5.0, True)
        assert ok is True, "坏行存在时不应影响对 case_A 的 finalize（C6 容错违规）"


# ---------------------------------------------------------------------
# C7: 14 维 feature_5d 键名集合 = CBR_CANONICAL_5D_KEYS 并集（逐字对齐 Spec §2.3.1 表）
# ---------------------------------------------------------------------
def test_C7_canonical_5d_feature_keys_match_spec_v03():
    s = _import_or_sentinel()
    assert s["CBR_CANONICAL_5D_KEYS"] is not s["SENTINEL"], "RED: 常量未定义"
    C5 = s["CBR_CANONICAL_5D_KEYS"]
    expected_categories = {"momentum", "ma_position", "volatility", "volume", "hexagram_meta"}
    assert expected_categories.issubset(set(C5.keys())), \
        f"缺五维分类：少 {expected_categories - set(C5.keys())}"
    # 数量检查：momentum 5 / ma_position 5 / volatility 3 / volume 2 / hexagram_meta 2 = 17
    total = sum(len(v) for v in C5.values())
    assert total >= 14, f"Spec 要求≥14维特征键，实际={total}"
    # 必须包含的代表键（不枚举全，避免过度绑死，但要几个关键锚点）
    flat_actual = {k for sub in C5.values() for k in sub}
    for must_have in ("rsi_14", "ma20_50_gap_pct", "atr14_norm_pct", "vol_ma20_ratio",
                      "hexagram_risk_level", "macd_hist", "triple_ma_order",
                      "bollinger_width_pct"):
        assert must_have in flat_actual, f"Spec §2.3.1 缺少关键键名：{must_have}"


# ---------------------------------------------------------------------
# C8: runtime 目录不存在 → 自动 mkdir，不抛 FileNotFound
# ---------------------------------------------------------------------
def test_C8_runtime_dir_missing_is_created_automatically_no_exception():
    s = _import_or_sentinel()
    assert s["CBRJsonlStore"] is not s["SENTINEL"]
    CBRJsonlStore = s["CBRJsonlStore"]
    with tempfile.TemporaryDirectory() as td:
        nested = Path(td) / "a" / "b" / "c" / "runtime"
        assert not nested.exists()
        try:
            store = CBRJsonlStore(runtime_dir=nested, enable=True)
        except FileNotFoundError as e:  # noqa: BLE001
            pytest.fail(f"C8 违规：未自动建目录 → FileNotFoundError: {e}")
        assert nested.exists() and nested.is_dir(), f"目录未创建：{nested}"
        # 写一条成功（路径正确）
        assert store.append_entry_semi({
            "case_id": "case_NEST", "symbol": "X", "asset_class": "CRYPTO",
            "create_ts": 3, "entry_snapshot": {"feature_5d": {}}}) is True
        assert (nested / "cbr_cases_v03.jsonl").exists()


# ---------------------------------------------------------------------
# C9: 200 条数据 finalize 重写 < 0.5s（简单性能阈值，避免后续 O(n²) 误写）
# ---------------------------------------------------------------------
def test_C9_200_cases_finalize_rewrite_under_half_second():
    s = _import_or_sentinel()
    assert s["CBRJsonlStore"] is not s["SENTINEL"]
    CBRJsonlStore = s["CBRJsonlStore"]
    with tempfile.TemporaryDirectory() as td:
        store = CBRJsonlStore(runtime_dir=Path(td), enable=True)
        n = 200
        ids = []
        for i in range(n):
            cid = f"case_{i:04d}_perf"
            ids.append(cid)
            store.append_entry_semi({
                "case_id": cid, "symbol": "BTC", "asset_class": "CRYPTO",
                "create_ts": i, "entry_snapshot": {"decision": "LONG", "confidence": 0.5 + i / 2000,
                                                    "volatility": 0.01,
                                                    "feature_5d": {"filler": i}}})
        # 选最后一个 case_id finalize → 触发全量重写，计时
        t0 = time.perf_counter()
        ok = store.finalize_by_case_id(ids[-1], {"exit_reason": "sl"}, -0.5, -1.0, False)
        elapsed = time.perf_counter() - t0
        assert ok is True
        assert elapsed < 0.5, f"200 条 finalize 耗时 {elapsed*1000:.0f}ms，超过 500ms 阈值（C9）"


# ---------------------------------------------------------------------
# C10: enable=False（关断或构造 disable）→ API 全 False/None，字节等价无副作用
# ---------------------------------------------------------------------
def test_C10_disabled_engine_is_byte_equivalent_no_side_effects():
    s = _import_or_sentinel()
    assert s["CBRJsonlStore"] is not s["SENTINEL"]
    CBRJsonlStore = s["CBRJsonlStore"]
    with tempfile.TemporaryDirectory() as td:
        runtime = Path(td) / "runtime"
        store_off = CBRJsonlStore(runtime_dir=runtime, enable=False)
        # 任何写 API 都返回 False
        assert store_off.append_entry_semi({
            "case_id": "case_OFF", "symbol": "X", "asset_class": "C",
            "create_ts": 1, "entry_snapshot": {}}) is False
        assert store_off.finalize_by_case_id("case_OFF", {}, 0, 0, False) is False
        # 副作用检查：runtime 目录 & JSONL 文件都不应被创建（enable=False）
        assert not (runtime / "cbr_cases_v03.jsonl").exists(), \
            "enable=False 时不应创建 JSONL 文件（G1 字节等价违规）"
